#-------------------------------------------------------------------------------
#   Generate Rust bindings.
#
#-------------------------------------------------------------------------------
import gen_ir
import os, shutil, sys

import gen_util as util

module_names = {
    'sg_':      'gfx',
    'sapp_':    'app',
    'stm_':     'time',
    'saudio_':  'audio',
    'sgl_':     'gl',
    'sdtx_':    'debugtext',
    'sshape_':  'shape',
}

c_source_paths = {
    'sg_':      'sokol-rust/src/sokol/c/sokol_gfx.c',
    'sapp_':    'sokol-rust/src/sokol/c/sokol_app.c',
    'stm_':     'sokol-rust/src/sokol/c/sokol_time.c',
    'saudio_':  'sokol-rust/src/sokol/c/sokol_audio.c',
    'sgl_':     'sokol-rust/src/sokol/c/sokol_gl.c',
    'sdtx_':    'sokol-rust/src/sokol/c/sokol_debugtext.c',
    'sshape_':  'sokol-rust/src/sokol/c/sokol_shape.c',
}

ignores = [
    'sdtx_printf',
    'sdtx_vprintf',
    'sg_install_trace_hooks',
    'sg_trace_hooks',
]

# NOTE: syntax for function results: "func_name.RESULT"
overrides = {
    'sgl_error':                            'sgl_get_error',   # 'error' is reserved in Zig
    'sgl_deg':                              'sgl_as_degrees',
    'sgl_rad':                              'sgl_as_radians',
    'sg_context_desc.color_format':         'int',
    'sg_context_desc.depth_format':         'int',
    'sg_apply_uniforms.ub_index':           'uint32_t',
    'sg_draw.base_element':                 'uint32_t',
    'sg_draw.num_elements':                 'uint32_t',
    'sg_draw.num_instances':                'uint32_t',
    'sshape_element_range_t.base_element':  'uint32_t',
    'sshape_element_range_t.num_elements':  'uint32_t',
    'sdtx_font.font_index':                 'uint32_t',
    'SGL_NO_ERROR':                         'SGL_ERROR_NO_ERROR',
    'type': 'r#type'
}

prim_types = {
    'int':          'i32',
    'bool':         'bool',
    'char':         'u8',
    'int8_t':       'i8',
    'uint8_t':      'u8',
    'int16_t':      'i16',
    'uint16_t':     'u16',
    'int32_t':      'i32',
    'uint32_t':     'u32',
    'int64_t':      'i64',
    'uint64_t':     'u64',
    'float':        'f32',
    'double':       'f64',
    'uintptr_t':    'usize',
    'intptr_t':     'isize',
    'size_t':       'usize'
}

prim_defaults = {
    'int':          '0',
    'bool':         'false',
    'int8_t':       '0',
    'uint8_t':      '0',
    'int16_t':      '0',
    'uint16_t':     '0',
    'int32_t':      '0',
    'uint32_t':     '0',
    'int64_t':      '0',
    'uint64_t':     '0',
    'float':        '0.0',
    'double':       '0.0',
    'uintptr_t':    '0',
    'intptr_t':     '0',
    'size_t':       '0'
}


struct_types = []
enum_types = []
enum_items = {}
out_lines = ''

def reset_globals():
    global struct_types
    global enum_types
    global enum_items
    global out_lines
    struct_types = []
    enum_types = []
    enum_items = {}
    out_lines = ''

def l(s):
    global out_lines
    out_lines += s + '\n'

def as_rust_prim_type(s):
    return prim_types[s]

# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_rust_struct_type(s, prefix):
    parts = s.lower().split('_')
    outp = '' if s.startswith(prefix) else f'{parts[0]}.'
    for part in parts[1:]:
        # ignore '_t' type postfix
        if (part != 't'):
            outp += part.capitalize()
    return outp

# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_rust_enum_type(s, prefix):
    parts = s.lower().split('_')
    outp = '' if s.startswith(prefix) else f'{parts[0]}.'
    for part in parts[1:]:
        if (part != 't'):
            outp += part.capitalize()
    return outp

def check_override(name, default=None):
    if name in overrides:
        return overrides[name]
    elif default is None:
        return name
    else:
        return default

def check_ignore(name):
    return name in ignores

# PREFIX_ENUM_BLA => Bla, _PREFIX_ENUM_BLA => Bla
def as_enum_item_name(s):
    outp = s.lstrip('_')
    parts = outp.split('_')[2:]
    outp = '_'.join(parts)
    outp = util.as_upper_camel_case(outp, '')
    if outp[0].isdigit():
        outp = 'Num' + outp
    return outp

def enum_default_item(enum_name):
    return enum_items[enum_name][0]

def is_prim_type(s):
    return s in prim_types

def is_struct_type(s):
    return s in struct_types

def is_enum_type(s):
    return s in enum_types

def is_const_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"const {prim_type} *":
            return True
    return False

def is_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"{prim_type} *":
            return True
    return False

def is_const_struct_ptr(s):
    for struct_type in struct_types:
        if s == f"const {struct_type} *":
            return True
    return False

def type_default_value(s):
    return prim_defaults[s]

def as_c_arg_type(arg_type, prefix):
    if arg_type == "void":
        return "()"
    elif is_prim_type(arg_type):
        return as_rust_prim_type(arg_type)
    elif is_struct_type(arg_type):
        return as_rust_struct_type(arg_type, prefix)
    elif is_enum_type(arg_type):
        return as_rust_enum_type(arg_type, prefix)
    elif util.is_void_ptr(arg_type):
        return "*mut std::ffi::c_void"
    elif util.is_const_void_ptr(arg_type):
        return "*const std::ffi::c_void"
    elif util.is_string_ptr(arg_type):
        return "*const u8"
    elif is_const_struct_ptr(arg_type):
        return f"*const {as_rust_struct_type(util.extract_ptr_type(arg_type), prefix)}"
    elif is_prim_ptr(arg_type):
        return f"*mut {as_rust_prim_type(util.extract_ptr_type(arg_type))}"
    elif is_const_prim_ptr(arg_type):
        return f"*const {as_rust_prim_type(util.extract_ptr_type(arg_type))}"
    else:
        sys.exit(f"Error as_c_arg_type(): {arg_type}")

def as_rust_arg_type(arg_prefix, arg_type, prefix):
    # NOTE: if arg_prefix is None, the result is used as return value
    pre = "" if arg_prefix is None else arg_prefix
    if arg_type == "void":
        if arg_prefix is None:
            return "()"
        else:
            return ""
    elif is_prim_type(arg_type):
        return pre + as_rust_prim_type(arg_type)
    elif is_struct_type(arg_type):
        return pre + as_rust_struct_type(arg_type, prefix)
    elif is_enum_type(arg_type):
        return pre + as_rust_enum_type(arg_type, prefix)
    elif util.is_void_ptr(arg_type):
        return pre + "*mut std::ffi::c_void"
    elif util.is_const_void_ptr(arg_type):
        return pre + "*const std::ffi::c_void"
    elif util.is_string_ptr(arg_type):
        return pre + "*const u8"
    elif is_const_struct_ptr(arg_type):
        # not a bug, pass const structs by value
        return pre + f"{as_rust_struct_type(util.extract_ptr_type(arg_type), prefix)}"
    elif is_prim_ptr(arg_type):
        return pre + f"*mut {as_rust_prim_type(util.extract_ptr_type(arg_type))}"
    elif is_const_prim_ptr(arg_type):
        return pre + f"*const {as_rust_prim_type(util.extract_ptr_type(arg_type))}"
    else:
        sys.exit(f"ERROR as_rust_arg_type(): {arg_type}")

def is_rust_string(rust_type):
    return rust_type == "[:0]const u8"

# get C-style arguments of a function pointer as string
def funcptr_args_c(field_type, prefix):
    tokens = field_type[field_type.index('(*)')+4:-1].split(',')
    s = ""
    for token in tokens:
        arg_type = token.strip()
        if s != "":
            s += ", "
        c_arg = as_c_arg_type(arg_type, prefix)
        if c_arg == "()":
            return ""
        else:
            s += c_arg
    return s

# get C-style result of a function pointer as string
def funcptr_result_c(field_type):
    res_type = field_type[:field_type.index('(*)')].strip()
    if res_type == 'void':
        return '()'
    elif util.is_const_void_ptr(res_type):
        return '*const std::ffi::c_void'
    elif util.is_void_ptr(res_type):
        return '*mut std::ffi::c_void'
    else:
        sys.exit(f"ERROR funcptr_result_c(): {field_type}")

def funcdecl_args_c(decl, prefix):
    s = ""
    func_name = decl['name']
    for param_decl in decl['params']:
        if s != "":
            s += ", "
        param_name = param_decl['name']
        param_type = check_override(f'{func_name}.{param_name}', default=param_decl['type'])
        s += param_name + ": " + as_c_arg_type(param_type, prefix)
    return s

def funcdecl_args_rust(decl, prefix):
    s = ""
    func_name = decl['name']
    for param_decl in decl['params']:
        if s != "":
            s += ", "
        param_name = param_decl['name']
        param_type = check_override(f'{func_name}.{param_name}', default=param_decl['type'])
        s += f"{as_rust_arg_type(f'{param_name}: ', param_type, prefix)}"
    return s

def funcdecl_result_c(decl, prefix):
    func_name = decl['name']
    decl_type = decl['type']
    result_type = check_override(f'{func_name}.RESULT', default=decl_type[:decl_type.index('(')].strip())
    return as_c_arg_type(result_type, prefix)

def funcdecl_result_rust(decl, prefix):
    func_name = decl['name']
    decl_type = decl['type']
    result_type = check_override(f'{func_name}.RESULT', default=decl_type[:decl_type.index('(')].strip())
    rust_res_type = as_rust_arg_type(None, result_type, prefix)
    return rust_res_type

def gen_struct(decl, prefix):
    struct_name = check_override(decl['name'])
    rust_type = as_rust_struct_type(struct_name, prefix)
    l(f"#[repr(C)]")
    l(f"pub struct {rust_type} {{")
    for field in decl['fields']:
        field_name = check_override(field['name'])
        field_type = check_override(f'{struct_name}.{field_name}', default=field['type'])
        if is_prim_type(field_type):
            l(f"    {field_name}: {as_rust_prim_type(field_type)},")
        elif is_struct_type(field_type):
            l(f"    {field_name}: {as_rust_struct_type(field_type, prefix)},")
        elif is_enum_type(field_type):
            l(f"    {field_name}: {as_rust_enum_type(field_type, prefix)},")
        elif util.is_string_ptr(field_type):
            l(f"    {field_name}: *mut u8,")
        elif util.is_const_void_ptr(field_type):
            l(f"    {field_name}: *const std::ffi::c_void,")
        elif util.is_void_ptr(field_type):
            l(f"    {field_name}: *mut std::ffi::c_void,")
        elif is_const_prim_ptr(field_type):
            l(f"    {field_name}: *const {as_rust_prim_type(util.extract_ptr_type(field_type))},")
        elif util.is_func_ptr(field_type):
            l(f"    {field_name}: *const extern fn({funcptr_args_c(field_type, prefix)}) -> {funcptr_result_c(field_type)},")
        elif util.is_1d_array_type(field_type):
            array_type = util.extract_array_type(field_type)
            array_sizes = util.extract_array_sizes(field_type)
            if is_prim_type(array_type) or is_struct_type(array_type):
                if is_prim_type(array_type):
                    rust_type = as_rust_prim_type(array_type)
                    def_val = type_default_value(array_type)
                elif is_struct_type(array_type):
                    rust_type = as_rust_struct_type(array_type, prefix)
                    def_val = '.{}'
                elif is_enum_type(array_type):
                    rust_type = as_rust_enum_type(array_type, prefix)
                    def_val = '.{}'
                else:
                    sys.exit(f"ERROR gen_struct is_1d_array_type: {array_type}")
                t0 = f"[{rust_type}; {array_sizes[0]}]"
                t1 = f"{rust_type}[_]"
                l(f"    {field_name}: {t0},")
            elif util.is_const_void_ptr(array_type):
                l(f"    {field_name}: [{array_sizes[0]}]?*const anyopaque = [_]?*const anyopaque {{ null }} ** {array_sizes[0]},")
            else:
                sys.exit(f"ERROR gen_struct: array {field_name}: {field_type} => {array_type} [{array_sizes[0]}]")
        elif util.is_2d_array_type(field_type):
            array_type = util.extract_array_type(field_type)
            array_sizes = util.extract_array_sizes(field_type)
            if is_prim_type(array_type):
                rust_type = as_rust_prim_type(array_type)
                def_val = type_default_value(array_type)
            elif is_struct_type(array_type):
                rust_type = as_rust_struct_type(array_type, prefix)
                def_val = ".{ }"
            else:
                sys.exit(f"ERROR gen_struct is_2d_array_type: {array_type}")
            t0 = f"{rust_type}[{array_sizes[0]}][{array_sizes[1]}]"
            l(f"    {field_name}: {t0} = [_][{array_sizes[1]}]{rust_type}{{[_]{rust_type}{{ {def_val} }}**{array_sizes[1]}}}**{array_sizes[0]},")
        else:
            sys.exit(f"ERROR gen_struct: {field_name}: {field_type};")
    l("}")

def gen_consts(decl, prefix):
    for item in decl['items']:
        item_name = check_override(item['name'])

        l(f"pub const {util.as_upper_snake_case(item_name, prefix)}: i32 = {item['value']};")

def gen_enum(decl, prefix):
    enum_name = check_override(decl['name'])
    l(f"#[repr(C)]")
    l(f"pub enum {as_rust_enum_type(enum_name, prefix)} {{")
    for item in decl['items']:
        item_name = as_enum_item_name(check_override(item['name']))
        if item_name != "FORCE_U32":
            if 'value' in item:
                l(f"    {item_name} = {item['value']},")
            else:
                l(f"    {item_name},")
    l("}")

def gen_func_c(decl, prefix):
    l(f"extern {{ pub fn {decl['name']}({funcdecl_args_c(decl, prefix)}) -> {funcdecl_result_c(decl, prefix)}; }}")

def gen_func_rust(decl, prefix):
    c_func_name = decl['name']
    rust_func_name = util.as_lower_snake_case(check_override(decl['name']), prefix)
    rust_res_type = funcdecl_result_rust(decl, prefix)
    l(f"pub fn {rust_func_name}({funcdecl_args_rust(decl, prefix)}) -> {rust_res_type} {{ unsafe {{")
    if is_rust_string(rust_res_type):
        # special case: convert C string to Zig string slice
        s = f"    return cStrToZig({c_func_name}("
    elif rust_res_type != 'void':
        s = f"    return {c_func_name}("
    else:
        s = f"    {c_func_name}("
    for i, param_decl in enumerate(decl['params']):
        if i > 0:
            s += ", "
        arg_name = param_decl['name']
        arg_type = param_decl['type']
        if is_const_struct_ptr(arg_type):
            s += f"&{arg_name}"
        #elif util.is_string_ptr(arg_type):
        #    s += f"@ptrCast([*c]const u8,{arg_name})"
        else:
            s += arg_name
    if is_rust_string(rust_res_type):
        s += ")"
    s += ");"
    l(s)
    l("} }")

def pre_parse(inp):
    global struct_types
    global enum_types
    for decl in inp['decls']:
        kind = decl['kind']
        if kind == 'struct':
            struct_types.append(decl['name'])
        elif kind == 'enum':
            enum_name = decl['name']
            enum_types.append(enum_name)
            enum_items[enum_name] = []
            for item in decl['items']:
                enum_items[enum_name].append(as_enum_item_name(item['name']))

def gen_imports(inp, dep_prefixes):
    for dep_prefix in dep_prefixes:
        dep_module_name = module_names[dep_prefix]
        l(f'mod {dep_module_name};')
    l('')

def gen_helpers(inp):
    pass

def gen_module(inp, dep_prefixes):
    l('// machine generated, do not edit')
    l('')
    gen_imports(inp, dep_prefixes)
    gen_helpers(inp)
    pre_parse(inp)
    prefix = inp['prefix']
    for decl in inp['decls']:
        if not decl['is_dep']:
            kind = decl['kind']
            if kind == 'consts':
                gen_consts(decl, prefix)
            elif not check_ignore(decl['name']):
                if kind == 'struct':
                    gen_struct(decl, prefix)
                elif kind == 'enum':
                    gen_enum(decl, prefix)
                elif kind == 'func':
                    gen_func_c(decl, prefix)
                    gen_func_rust(decl, prefix)

def prepare():
    print('=== Generating Rust bindings:')
    if not os.path.isdir('sokol-rust/src/sokol'):
        os.makedirs('sokol-rust/src/sokol')
    if not os.path.isdir('sokol-rust/src/sokol/c'):
        os.makedirs('sokol-rust/src/sokol/c')

def gen(c_header_path, c_prefix, dep_c_prefixes):
    if not c_prefix in module_names:
        print(f' >> warning: skipping generation for {c_prefix} prefix...')
        return
    module_name = module_names[c_prefix]
    c_source_path = c_source_paths[c_prefix]
    print(f'  {c_header_path} => {module_name}')
    reset_globals()
    shutil.copyfile(c_header_path, f'sokol-rust/src/sokol/c/{os.path.basename(c_header_path)}')
    ir = gen_ir.gen(c_header_path, c_source_path, module_name, c_prefix, dep_c_prefixes)
    gen_module(ir, dep_c_prefixes)
    output_path = f"sokol-rust/src/sokol/{ir['module']}.rs"
    with open(output_path, 'w', newline='\n') as f_outp:
        f_outp.write(out_lines)
