"""Layouts de memoria compartidos por los backends (AST y BIR).

`wasm_type` traduce tipos del typechecker a tipos wasm y
`compute_type_layouts` calcula offsets de campos y de variantes. Ambas son
puras: no dependen de ningun backend concreto.
"""
from dataclasses import dataclass, field

from tools.nodes import Field, TypeDecl, Variant
from tools.wasm_encoder import WasmEncoder


def erase_task(ty):
    """v0.1: task[T] se representa como T (spawn/await secuenciales)."""
    while isinstance(ty, tuple) and ty[0] == "named" and ty[1] == "task" and ty[2]:
        ty = ty[2][0]
    return ty


def wasm_type(ty):
    """Tipo wasm para un tipo del typechecker (tuplas `("p", ...)`)."""
    ty = erase_task(ty)
    if isinstance(ty, tuple):
        if ty[0] == "p":
            if ty[1] in ("int", "bool"):
                return WasmEncoder.I64
            if ty[1] == "float":
                return WasmEncoder.F64
            if ty[1] in ("str", "bytes"):
                return WasmEncoder.I32
        if ty[0] == "named":
            return WasmEncoder.I32
        if ty[0] in ("opt", "res", "borrow"):
            return wasm_type(ty[1])
        if ty[0] in ("list", "map", "set", "tuple", "func"):
            return WasmEncoder.I32
    return WasmEncoder.I64


def _slot(wtype, offset):
    """Alinea `offset` a 8 y devuelve `(offset, size)` del campo."""
    size = 8 if wtype in (WasmEncoder.I64, WasmEncoder.F64) else 4
    if offset % 8 != 0:
        offset += 8 - (offset % 8)
    return offset, size


@dataclass
class TypeLayouts:
    """Tabla de layouts: campos, tamano y variantes por nombre de tipo."""

    struct_layouts: dict = field(default_factory=dict)  # name -> [(f, wtype, off, ty, default)]
    struct_sizes: dict = field(default_factory=dict)    # name -> bytes
    variant_index: dict = field(default_factory=dict)   # name -> {variant: idx}
    variant_fields: dict = field(default_factory=dict)  # name -> {variant: [campos]}
    sum_types: set = field(default_factory=set)

    def fields(self, type_name):
        return self.struct_layouts.get(type_name, [])

    def size(self, type_name):
        return self.struct_sizes.get(type_name, 8)

    def field(self, type_name, name):
        for f in self.fields(type_name):
            if f[0] == name:
                return f
        return None

    def variant_fields_of(self, type_name, variant_name):
        return (self.variant_fields.get(type_name) or {}).get(variant_name, [])

    def has_type(self, type_name):
        return type_name in self.struct_sizes


def _field_type(tc, f):
    if f.type_ is None:
        return None
    try:
        return tc._atype(f.type_)
    except Exception:
        return None


def compute_type_layouts(program, tc):
    """Productos y sumas del programa -> `TypeLayouts` (tag en el offset 0)."""
    layouts = TypeLayouts()
    for stmt in program.stmts:
        if not isinstance(stmt, TypeDecl):
            continue
        variants = [m.node for m in stmt.members if isinstance(m.node, Variant)]
        if variants:
            layouts.sum_types.add(stmt.name)
            vindex = {}
            vfields = {}
            max_payload = 0
            for vi, v in enumerate(variants):
                vindex[v.name] = vi
                vfs = v.fields if v.fields else [mm.node for mm in getattr(v, "members", [])
                                                 if isinstance(mm.node, Field)]
                offset = 0
                fields = []
                for f in vfs:
                    ty = _field_type(tc, f)
                    wtype = wasm_type(ty) if ty is not None else WasmEncoder.I64
                    offset, size = _slot(wtype, offset)
                    fields.append((f.name, wtype, 8 + offset, ty, None))
                    offset += size
                if offset == 0:
                    offset = 8
                vfields[v.name] = fields
                if offset > max_payload:
                    max_payload = offset
            size = 8 + max_payload
            if size < 8:
                size = 8
            layouts.variant_index[stmt.name] = vindex
            layouts.variant_fields[stmt.name] = vfields
            layouts.struct_layouts[stmt.name] = []
            layouts.struct_sizes[stmt.name] = size
            continue
        offset = 0
        fields = []
        for m in stmt.members:
            if not isinstance(m.node, Field):
                continue
            f = m.node
            ty = _field_type(tc, f)
            wtype = wasm_type(ty) if ty is not None else WasmEncoder.I64
            offset, size = _slot(wtype, offset)
            fields.append((f.name, wtype, offset, ty, f.default))
            offset += size
        if offset == 0:
            offset = 8
        layouts.struct_layouts[stmt.name] = fields
        layouts.struct_sizes[stmt.name] = offset
    return layouts
