"""Layouts de memoria para el backend BIR (fase 6.2).

El BIR no transporta offsets ni firmas de metodos, asi que el codegen recibe
`program` + `tc` y construye aqui la tabla compartida con el backend AST.
"""
from tools.ast_to_bir import to_type
from tools.bir import Type
from tools.layouts import TypeLayouts, compute_type_layouts
from tools.wasm_encoder import WasmEncoder

# Tipos BIR que ocupan un puntero i32 en memoria lineal.
PTR_KINDS = ("str", "bytes", "struct", "tuple", "list", "map", "set",
             "func", "closure", "ref")

_SCALAR_KINDS = ("i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64",
                 "bool", "unit", "unknown", "err")


class LayoutError(Exception):
    pass


def wasm_repr(ty):
    """Tipo wasm de un `Type` BIR: i32 punteros, f64 floats, i64 el resto."""
    if ty is None:
        raise LayoutError("tipo BIR desconocido")
    kind = ty.kind
    if kind in ("f32", "f64"):
        return WasmEncoder.F64
    if kind in PTR_KINDS:
        return WasmEncoder.I32
    if kind in _SCALAR_KINDS:
        return WasmEncoder.I32 if kind == "i32" else WasmEncoder.I64
    if kind in ("opt", "res", "task") and ty.elem is not None:
        return wasm_repr(ty.elem)
    raise LayoutError(f"codegen BIR no soporta el tipo '{kind}' todavia")


def _align8(offset):
    return offset + (8 - offset % 8) % 8


class BIRLayoutsMixin:
    """Tabla de productos/sumas y helpers de tamano para el codegen BIR."""

    def build_layouts(self, program=None, tc=None):
        self.program = program
        self.tc = tc
        if program is not None and tc is not None:
            self.layouts = compute_type_layouts(program, tc)
        else:
            self.layouts = TypeLayouts()

    # ---- tipos ----

    def size_of(self, ty):
        """Bytes que ocupa un valor de `ty` (punteros = 4)."""
        if ty is None:
            return 8
        kind = ty.kind
        if kind == "struct":
            return self.layouts.size(ty.name)
        if kind == "tuple":
            return self.tuple_layout(ty)[1]
        if kind in PTR_KINDS:
            return 4
        if kind in ("opt", "res", "task") and ty.elem is not None:
            return self.size_of(ty.elem)
        return 8

    def tuple_layout(self, ty):
        """Layout de una tupla BIR -> ([(nombre, wtype, offset, Type)], size)."""
        offset = 0
        fields = []
        for name, fty in (ty.fields or []):
            wtype = wasm_repr(fty)
            offset = _align8(offset)
            fields.append((name, wtype, offset, fty))
            offset += 8 if wtype in (WasmEncoder.I64, WasmEncoder.F64) else 4
        return fields, max(offset, 8)

    # ---- productos ----

    def field_info(self, type_name, field_name):
        """(nombre, wtype, offset, Type BIR, default) o None."""
        f = self.layouts.field(type_name, field_name)
        if f is None:
            return None
        return (f[0], f[1], f[2], to_type(f[3]) if f[3] is not None else Type("unknown"), f[4])

    def field_offset(self, type_name, field_name):
        info = self.field_info(type_name, field_name)
        if info is None:
            raise LayoutError(f"campo '{field_name}' inexistente en '{type_name}'")
        return info[2]

    def field_type(self, type_name, field_name):
        info = self.field_info(type_name, field_name)
        if info is None:
            raise LayoutError(f"campo '{field_name}' inexistente en '{type_name}'")
        return info[3]

    # ---- sumas (tag en el offset 0) ----

    def variant_tag(self, type_name, variant_name):
        index = (self.layouts.variant_index.get(type_name) or {}).get(variant_name)
        if index is None:
            raise LayoutError(f"variante '{variant_name}' inexistente en '{type_name}'")
        return index

    def variant_fields(self, type_name, variant_name):
        """Campos del payload con offsets absolutos (ya incluyen el tag)."""
        raw = self.layouts.variant_fields_of(type_name, variant_name)
        return [(name, wtype, offset, to_type(fty) if fty is not None else Type("unknown"))
                for (name, wtype, offset, fty, _default) in raw]
