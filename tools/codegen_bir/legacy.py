"""Codegen WASM que consume BIR (fase 6).

Este backend es la primera etapa del refactor de la fase 6: en vez de recorrer
el AST elaborado, recorre las funciones BIR que produce
`tools.ast_to_bir.translate_program`. Cubre el subset escalar:

- tipos `int`/`bool` (i64), `float` (f64), `str`/`bytes` (puntero i32) y `nil`;
- locales, parametros y temporales tipados por BIR;
- `Assign`, `Call` (funciones y `print` del host) y `StorageLive`/`StorageDead`;
- CFG completo (`Goto`, `SwitchInt`, `Return`) mediante un dispatch por `pc`;
- recursion y funciones con/sin valor de retorno.

Los tipos compuestos (`struct`, `list`, `map`, `set`, `tuple`), las closures y
`T?`/`T!` siguen en el backend desde AST hasta las etapas 6.2/6.3. Cuando un
constructo no esta soportado se lanza `BIRCodegenError` de forma explicita (nunca
se emite codigo silencioso).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babirusas.src.borrowir.ir import Type
from tools.parser import parse
from tools.typecheck import TC
from tools.core_ir import elaborate
from tools.ast_to_bir import translate_program, borrow_check_program
from tools.wasm_encoder import (
    WasmEncoder, i32_const, i64_const, f64_const, local_get, local_set,
    uleb128, BLOCK, LOOP, END, RETURN, DROP, BLK_VOID,
    GLOBAL_GET, GLOBAL_SET,
)
from .layouts import LayoutError, wasm_repr


class BIRCodegenError(Exception):
    pass


# ---- opcodes usados por el subset escalar ----

I64_ADD = bytes([0x7C])
I64_SUB = bytes([0x7D])
I64_MUL = bytes([0x7E])
I64_DIV_S = bytes([0x7F])
I64_REM_S = bytes([0x81])
I64_AND = bytes([0x83])
I64_OR = bytes([0x84])
I64_XOR = bytes([0x85])
I64_SHL = bytes([0x86])
I64_SHR_S = bytes([0x87])
I64_EQZ = bytes([0x50])
I64_EQ = bytes([0x51])
I64_NE = bytes([0x52])
I64_LT_S = bytes([0x53])
I64_GT_S = bytes([0x55])
I64_LE_S = bytes([0x57])
I64_GE_S = bytes([0x59])

F64_ADD = bytes([0xA0])
F64_SUB = bytes([0xA1])
F64_MUL = bytes([0xA2])
F64_DIV = bytes([0xA3])
F64_NEG = bytes([0x9A])
F64_EQ = bytes([0x61])
F64_NE = bytes([0x62])
F64_LT = bytes([0x63])
F64_GT = bytes([0x64])
F64_LE = bytes([0x65])
F64_GE = bytes([0x66])

I64_EXTEND_I32 = bytes([0xAC])   # comparaciones -> bool i64
I64_TRUNC_F64 = bytes([0xB0])
F64_CONVERT_I64 = bytes([0xB9])
SELECT = bytes([0x1B])
UNREACHABLE = bytes([0x00])
BR_TABLE = 0x0E

_I64_BIN = {
    "+": I64_ADD, "-": I64_SUB, "*": I64_MUL, "/": I64_DIV_S, "//": I64_DIV_S,
    "%": I64_REM_S, "&": I64_AND, "|": I64_OR, "^": I64_XOR,
    "<<": I64_SHL, ">>": I64_SHR_S,
}
_I64_CMP = {
    "==": I64_EQ, "!=": I64_NE, "<": I64_LT_S, ">": I64_GT_S,
    "<=": I64_LE_S, ">=": I64_GE_S,
}
_F64_BIN = {"+": F64_ADD, "-": F64_SUB, "*": F64_MUL, "/": F64_DIV, "//": F64_DIV}
_F64_CMP = {
    "==": F64_EQ, "!=": F64_NE, "<": F64_LT, ">": F64_GT,
    "<=": F64_LE, ">=": F64_GE,
}

_PTR_KINDS = ("str", "bytes", "ptr")


def _storage_wt(ty):
    """Tipo wasm para un local/param. `unit` ocupa un i64 dummy."""
    try:
        return wasm_repr(ty)
    except LayoutError as e:
        raise BIRCodegenError(str(e))


def _result_wt(ty):
    if ty is None or ty.kind in ("unit", "unknown"):
        return None
    return _storage_wt(ty)


class BIRCodegenLegacy:
    """Traduce una lista de `Function` BIR a un modulo wasm."""

    def __init__(self, functions, program=None, tc=None):
        self.functions = list(functions)
        self.build_layouts(program, tc)
        self.enc = WasmEncoder()
        self.enc.add_memory(1)
        self.enc.add_export_memory("memory")
        self.print_type = self.enc.add_type([WasmEncoder.I64], [])
        self.print_import = self.enc.add_import("env", "print", self.print_type)
        self.print_f64_type = self.enc.add_type([WasmEncoder.F64], [])
        self.print_f64_import = self.enc.add_import("env", "print_f64", self.print_f64_type)
        self.print_str_type = self.enc.add_type([WasmEncoder.I32], [])
        self.print_str_import = self.enc.add_import("env", "print_str", self.print_str_type)
        self.sigs = {}        # name -> (typeidx, ret_type)
        self.func_index = {}  # name -> wasm func idx
        self.fn_context = None
        # Pool de strings en memoria lineal (NUL-terminadas, deduplicadas).
        self.str_offsets = {}
        self._data_offset = 0

    # ---- estado por funcion ----

    def _fail(self, msg):
        where = self.fn_context or "<modulo>"
        raise BIRCodegenError(f"codegen BIR en {where}: {msg}")

    def _local_types(self, fn):
        types = {}
        for p in fn.params:
            types[p.name] = p.type
        for loc in fn.locals:
            types.setdefault(loc.name, loc.type)
        return types

    def _local_type(self, name):
        ty = self._local_types_cache.get(name)
        if ty is None:
            self._fail(f"local desconocido '{name}'")
        return ty

    def _local_idx(self, name):
        if name not in self.local_index:
            self._fail(f"local desconocido '{name}'")
        return self.local_index[name]

    def _rv_type(self, rv):
        kind = rv.kind
        if kind == "const":
            return rv.const_type
        if kind == "use":
            return self._place_type(rv.place)
        if kind == "cast":
            return rv.cast_type
        if kind == "binop":
            if rv.op in _I64_CMP or rv.op in _F64_CMP:
                return Type("bool")
            a = self._rv_type(rv.a)
            b = self._rv_type(rv.b) if rv.b is not None else a
            if a is not None and a.kind == "f64":
                return a
            if b is not None and b.kind == "f64":
                return b
            return a or b
        if kind == "unaryop":
            if rv.op == "not":
                return Type("bool")
            return self._rv_type(rv.a)
        if kind == "ref":
            return Type("ref")
        return None

    def _place_type(self, place):
        if place.kind == "local":
            return self._local_type(place.name)
        self._fail(f"place '{place.kind}' no soportado en 6.1")

    # ---- strings ----

    def _string_offset(self, value):
        raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if raw in self.str_offsets:
            return self.str_offsets[raw]
        off = self._data_offset
        data = raw + b"\x00"
        self.enc.add_data(off, data)
        self._data_offset += len(data)
        self.str_offsets[raw] = off
        return off

    # ---- rvalues ----

    def _gen_rvalue(self, rv):
        kind = rv.kind
        if kind == "const":
            return self._gen_const(rv)
        if kind == "use":
            return self._gen_place_get(rv.place)
        if kind == "cast":
            return self._gen_cast(rv)
        if kind == "binop":
            return self._gen_binop(rv)
        if kind == "unaryop":
            return self._gen_unaryop(rv)
        self._fail(f"rvalue '{kind}' no soportado en 6.1")

    def _gen_const(self, rv):
        ty = rv.const_type
        value = rv.const_value
        if ty is None:
            self._fail("constante sin tipo")
        if ty.kind in ("i64", "bool"):
            return i64_const(int(value) if value is not None else 0)
        if ty.kind == "f64":
            return f64_const(float(value) if value is not None else 0.0)
        if ty.kind in _PTR_KINDS:
            if not isinstance(value, (str, bytes)):
                self._fail("constante str/bytes no textual")
            return i32_const(self._string_offset(value))
        if ty.kind in ("unit", "unknown"):
            return i64_const(0)
        self._fail(f"constante de tipo '{ty.kind}' no soportada")

    def _gen_place_get(self, place):
        if place.kind != "local":
            self._fail(f"lectura de place '{place.kind}' no soportada en 6.1")
        return local_get(self._local_idx(place.name))

    def _gen_place_set(self, place, value_code, value_ty=None):
        if place.kind != "local":
            self._fail(f"escritura de place '{place.kind}' no soportada en 6.1")
        return value_code + local_set(self._local_idx(place.name))

    def _gen_cast(self, rv):
        src = self._rv_type(rv.a)
        dst = rv.cast_type
        code = self._gen_rvalue(rv.a)
        if src is None or dst is None:
            return code
        if src.kind == "f64" and dst.kind in ("i64", "bool"):
            return code + I64_TRUNC_F64
        if src.kind in ("i64", "bool") and dst.kind == "f64":
            return code + F64_CONVERT_I64
        # int <-> bool, punteros y copias: misma representacion.
        return code

    def _gen_binop(self, rv):
        op = rv.op
        a = self._rv_type(rv.a)
        b = self._rv_type(rv.b) if rv.b is not None else a
        use_float = (a is not None and a.kind == "f64") or \
                    (b is not None and b.kind == "f64")
        left = self._gen_rvalue(rv.a)
        right = self._gen_rvalue(rv.b)
        if use_float:
            if op in _F64_CMP:
                return left + right + _F64_CMP[op] + I64_EXTEND_I32
            if op == "%":
                self._fail("`%` sobre float no soportado en 6.1")
            if op == "**":
                self._fail("`**` sobre float no soportado en 6.1")
            if op in _F64_BIN:
                return left + right + _F64_BIN[op]
            self._fail(f"operador float '{op}' no soportado")
        if op in _I64_CMP:
            return left + right + _I64_CMP[op] + I64_EXTEND_I32
        if op in _I64_BIN:
            return left + right + _I64_BIN[op]
        if op == "**":
            self._fail("`**` no soportado en 6.1")
        self._fail(f"operador '{op}' no soportado en 6.1")

    def _gen_unaryop(self, rv):
        op = rv.op
        ty = self._rv_type(rv.a)
        value = self._gen_rvalue(rv.a)
        if op == "-":
            if ty is not None and ty.kind == "f64":
                return value + F64_NEG
            return i64_const(0) + value + I64_SUB
        if op == "not":
            return value + I64_EQZ + I64_EXTEND_I32
        if op == "~":
            return value + i64_const(-1) + I64_XOR
        self._fail(f"operador unario '{op}' no soportado en 6.1")

    # ---- sentencias ----

    def _gen_stmt(self, st):
        if st.kind in ("StorageLive", "StorageDead", "Borrow"):
            return b""
        if st.kind == "Assign":
            rv = st.rvalue
            return self._gen_place_set(st.place, self._gen_rvalue(rv),
                                     self._rv_type(rv))
        if st.kind == "Call":
            return self._gen_call(st)
        self._fail(f"sentencia '{st.kind}' no soportada en 6.1")

    def _gen_call(self, st):
        name = st.call_func
        args = st.call_args
        if name in ("drop", "copy"):
            if len(args) != 1:
                self._fail(f"`{name}` espera 1 argumento")
            code = self._gen_rvalue(args[0])
            if name == "copy" and st.call_dest is not None:
                return self._gen_place_set(st.call_dest, code,
                                         self._rv_type(args[0]))
            return code + DROP
        if name in ("int", "float", "bool"):
            return self._gen_conversion(name, st)
        if name in ("print", "eprint"):
            return self._gen_print(name, st)
        if name == "alloc":
            self._ensure_allocator()
            if len(args) != 1:
                self._fail("`alloc` espera 1 argumento")
            arg = args[0]
            code = bytearray()
            code += GLOBAL_GET(self.heap_global)
            code += GLOBAL_GET(self.heap_global)
            code += self._gen_rvalue(arg)
            # n es i64 -> i32
            code += bytes([0xA7])  # i32.wrap_i64
            code += bytes([0x6A])  # i32.add
            code += GLOBAL_SET(self.heap_global)
            if st.call_dest is not None:
                return self._gen_place_set(st.call_dest, bytes(code), None)
            return bytes(code) + DROP
        if name not in self.sigs:
            self._fail(f"llamada a funcion desconocida '{name}' (prelude/fase 7?)")
        typeidx, ret_ty = self.sigs[name]
        code = bytearray()
        for i, arg in enumerate(args):
            expected = self.functions_by_name[name].params[i] \
                if i < len(self.functions_by_name[name].params) else None
            code += self._gen_rvalue(arg)
            actual = self._rv_type(arg)
            # Los punteros son i32 y el resto valores wasm; BIR ya coerciona.
            if expected is not None and actual is not None and \
                    _storage_wt(expected.type) != _storage_wt(actual):
                self._fail(f"argumento {i + 1} de '{name}' con tipo incompatible")
        code += bytes([0x10]) + uleb128(self.func_index[name])
        if _result_wt(ret_ty) is None:
            if st.call_dest is not None:
                pass  # destino unit: no hay valor que guardar
        elif st.call_dest is not None:
            code = self._gen_place_set(st.call_dest, bytes(code), ret_ty)
        else:
            code += DROP
        return bytes(code)

    def _gen_conversion(self, name, st):
        if len(st.call_args) != 1:
            self._fail(f"`{name}` espera 1 argumento")
        arg = st.call_args[0]
        src = self._rv_type(arg)
        code = self._gen_rvalue(arg)
        if name == "float":
            if src is not None and src.kind != "f64":
                code += F64_CONVERT_I64
        elif name == "int":
            if src is not None and src.kind == "f64":
                code += I64_TRUNC_F64
        elif name == "bool":
            if src is not None and src.kind == "f64":
                code += i64_const(0) + F64_NE + I64_EXTEND_I32
            else:
                code += i64_const(0) + I64_NE + I64_EXTEND_I32
        if st.call_dest is not None:
            return self._gen_place_set(st.call_dest, code, None)
        return code

    def _gen_print(self, name, st):
        if len(st.call_args) != 1:
            self._fail(f"`{name}` espera 1 argumento")
        arg = st.call_args[0]
        ty = self._rv_type(arg)
        code = self._gen_rvalue(arg)
        if ty is not None and ty.kind in _PTR_KINDS:
            idx = self.print_str_import
        elif ty is not None and ty.kind == "f64":
            idx = self.print_f64_import
        else:
            idx = self.print_import
        return code + bytes([0x10]) + uleb128(idx)

    # ---- terminadores / CFG ----

    def _gen_term(self, term, depth):
        if term.kind == "Return":
            ret_ty = self.fn.ret_type
            if _result_wt(ret_ty) is None:
                return RETURN
            if not self.fn.ret_local:
                self._fail("Return sin local de retorno")
            return local_get(self._local_idx(self.fn.ret_local)) + RETURN
        if term.kind == "Goto":
            return i32_const(term.target) + local_set(self.pc_index) + \
                bytes([0x0C]) + uleb128(depth)
        if term.kind == "SwitchInt":
            return self._gen_switch(term, depth)
        self._fail(f"terminador '{term.kind}' no soportado en 6.1")

    def _gen_switch(self, term, depth):
        discr_ty = self._rv_type(term.discr)
        if discr_ty is None:
            discr_ty = Type("i64")
        is_float = discr_ty.kind == "f64"
        scratch = self._add_temp(discr_ty)
        code = bytearray()
        code += self._gen_rvalue(term.discr) + local_set(scratch)
        otherwise = term.otherwise if term.otherwise is not None else term.target
        if otherwise is None:
            self._fail("SwitchInt sin destino por defecto")
        code += i32_const(otherwise) + local_set(self.pc_index)
        for value, target in (term.cases or []):
            code += i32_const(target)
            code += local_get(self.pc_index)
            code += local_get(scratch)
            if is_float:
                code += f64_const(float(value)) + F64_EQ
            else:
                code += i64_const(int(value)) + I64_EQ
            code += SELECT + local_set(self.pc_index)
        code += bytes([0x0C]) + uleb128(depth)
        return bytes(code)

    def _add_temp(self, ty):
        """Anade un local temporal al frame actual y devuelve su indice."""
        idx = len(self.local_types) + len(self.extra_locals)
        self.extra_locals.append(ty)
        return idx

    # ---- funciones ----

    def _gen_function(self, fn):
        self.fn = fn
        self.fn_context = fn.name
        self._local_types_cache = self._local_types(fn)
        # Parametros primero (los locales BIR incluyen el `__ret` antes que
        # los parametros, asi que el mapeo se construye explicitamente).
        self.local_index = {}
        self.local_types = []
        for i, p in enumerate(fn.params):
            self.local_index[p.name] = i
            self.local_types.append(_storage_wt(p.type))
        self.nparams = len(fn.params)
        for loc in fn.locals:
            if loc.name in self.local_index:
                continue
            self.local_index[loc.name] = len(self.local_types)
            self.local_types.append(_storage_wt(loc.type))
        self.extra_locals = []
        self.pc_index = self._add_temp(Type("i32"))

        blocks = fn.blocks
        if not blocks:
            self._fail("funcion BIR sin bloques")
        order = [b.id for b in blocks]
        body = bytearray()
        body += i32_const(fn.entry) + local_set(self.pc_index)

        def emit_dispatch():
            # block $exit / loop $dispatch / block x N / br_table
            body.extend(BLOCK(BLK_VOID))   # exit
            body.extend(LOOP(BLK_VOID))    # dispatch
            for _ in blocks:
                body.extend(BLOCK(BLK_VOID))
            body.extend(local_get(self.pc_index))
            body.append(BR_TABLE)
            body.extend(uleb128(len(blocks)))
            # `pc` guarda el id del bloque, no su posicion en la lista (el
            # traductor reordena por RPO). depth = posicion desde el fondo.
            depth_for_id = {b.id: len(blocks) - 1 - j
                            for j, b in enumerate(blocks)}
            for pc_value in range(len(blocks)):
                if pc_value not in depth_for_id:
                    self._fail(f"id de bloque {pc_value} inexistente")
                body.extend(uleb128(depth_for_id[pc_value]))
            body.extend(uleb128(len(blocks) + 1))  # default -> $exit

            # Cerrar bloques en orden inverso: cada END deja visible el cuerpo
            # del bloque correspondiente.
            for i in range(len(blocks) - 1, -1, -1):
                b = blocks[i]
                body.extend(END)
                for st in b.stmts:
                    body.extend(self._gen_stmt(st))
                if b.terminator is not None:
                    body.extend(self._gen_term(b.terminator, i))
                else:
                    body.extend(RETURN)
            body.extend(END)   # loop
            body.extend(END)   # exit
            body.extend(UNREACHABLE)

        emit_dispatch()

        local_types = list(self.local_types)
        for ty in self.extra_locals:
            # `i32` se representa como Type("i32") por _add_temp; el resto ya
            # viene con su kind BIR.
            local_types.append(WasmEncoder.I32 if ty.kind == "i32"
                               else _storage_wt(ty))
        typeidx, _ = self.sigs[fn.name]
        idx = self.enc.add_function(typeidx, local_types[len(fn.params):], bytes(body))
        self.func_index[fn.name] = idx

    def generate(self):
        # Firmas y nombres.
        self.functions_by_name = {f.name: f for f in self.functions}
        for i, fn in enumerate(self.functions):
            params = [_storage_wt(p.type) for p in fn.params]
            result = _result_wt(fn.ret_type)
            typeidx = self.enc.add_type(params, [] if result is None else [result])
            self.sigs[fn.name] = (typeidx, fn.ret_type)
            # Pre-asignar indices para que las llamadas adelantadas (recursion)
            # resuelvan antes de emitir el cuerpo.
            self.func_index[fn.name] = len(self.enc.imports) + i

        for fn in self.functions:
            self._gen_function(fn)

        # `_start`: ejecuta el cuerpo de modulo (`__top`) y luego `main`.
        start_type = self.enc.add_type([], [])
        start_code = bytearray()
        for name in ("__top", "main"):
            if name in self.func_index:
                start_code.extend(bytes([0x10]) + uleb128(self.func_index[name]))
                if _result_wt(self.sigs[name][1]) is not None:
                    start_code.extend(DROP)
        start_idx = self.enc.add_function(start_type, [], bytes(start_code))
        self.enc.add_export_func("_start", start_idx)
        for name in ("main", "__top"):
            if name in self.func_index:
                self.enc.add_export_func(name, self.func_index[name])
        return self.enc.encode()


# ---- pipeline de conveniencia ----

def prepare_program(source, filename=None):
    """parse -> modulos -> typecheck -> elaborate -> typecheck -> borrow -> BIR.

    Devuelve `(functions, program, tc)`: el codegen BIR necesita el programa y
    el typechecker para calcular layouts y firmas de metodos.
    """
    program = parse(source)
    from tools.modules import load_modules
    base = os.path.dirname(os.path.abspath(filename)) if filename else os.getcwd()
    load_modules(program, base)
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise BIRCodegenError(str(errs[0]))
    elaborate(program, tc)
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise BIRCodegenError(str(errs[0]))
    borrow_errors = borrow_check_program(program, tc)
    if borrow_errors:
        raise BIRCodegenError(borrow_errors[0])
    return translate_program(program, tc), program, tc


def prepare_functions(source, filename=None):
    """Solo las funciones BIR (compatibilidad con los tests de 6.1)."""
    functions, _program, _tc = prepare_program(source, filename)
    return functions


def compile_source(source, filename=None):
    """Compila con el backend BIR."""
    from .core import BIRCodegen
    functions, program, tc = prepare_program(source, filename)
    return BIRCodegen(functions, program, tc).generate()
