"""Tests de layouts (fase 6.2.1): tabla compartida y representacion BIR."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.parser import parse
from tools.typecheck import TC
from tools.codegen import WasmCodegen
from tools.codegen_bir.layouts import BIRLayoutsMixin, LayoutError, wasm_repr
from tools.bir import Type
from tools.layouts import compute_type_layouts
from tools.wasm_encoder import WasmEncoder

SRC = """
type P
	a: int
	b: str

type Shape
	case Circle(r: float)
	case Rect(w: float, h: float)
"""

I32, I64, F64 = WasmEncoder.I32, WasmEncoder.I64, WasmEncoder.F64


def _program():
    program = parse(SRC)
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise AssertionError(f"programa de prueba invalido: {errs[0]}")
    return program, tc


class Harness(BIRLayoutsMixin):
    pass


def check_product(layouts):
    fields = {f[0]: f for f in layouts.fields("P")}
    assert fields["a"][1:] == (I64, 0, ("p", "int"), None), fields["a"]
    assert fields["b"][1:] == (I32, 8, ("p", "str"), None), fields["b"]
    assert layouts.size("P") == 12, layouts.size("P")


def check_sum(layouts):
    assert layouts.sum_types == {"Shape"}, layouts.sum_types
    assert layouts.variant_index["Shape"] == {"Circle": 0, "Rect": 1}
    assert layouts.fields("Shape") == []
    circle = layouts.variant_fields_of("Shape", "Circle")
    rect = layouts.variant_fields_of("Shape", "Rect")
    assert [(f[0], f[1], f[2]) for f in circle] == [("r", F64, 8)], circle
    assert [(f[0], f[1], f[2]) for f in rect] == [("w", F64, 8), ("h", F64, 16)], rect
    assert layouts.size("Shape") == 24, layouts.size("Shape")


def check_parity(program, tc, layouts):
    ast = WasmCodegen(program, tc)
    ast._compute_struct_layouts()
    assert ast.struct_layouts == layouts.struct_layouts
    assert ast.struct_sizes == layouts.struct_sizes
    assert ast.variant_index == layouts.variant_index
    assert ast.variant_fields == layouts.variant_fields
    assert ast.sum_types == layouts.sum_types


def check_wasm_repr():
    i32 = ("str", "bytes", "struct", "tuple", "list", "map", "set", "func", "ref", "i32")
    for kind in i32:
        assert wasm_repr(Type(kind)) == I32, kind
    assert wasm_repr(Type("f64")) == F64
    assert wasm_repr(Type("f32")) == F64
    for kind in ("i64", "bool", "unit", "unknown"):
        assert wasm_repr(Type(kind)) == I64, kind
    assert wasm_repr(Type("opt", elem=Type("str"))) == I32
    assert wasm_repr(Type("res", elem=Type("f64"))) == F64
    try:
        wasm_repr(Type("misterio"))
    except LayoutError:
        pass
    else:
        raise AssertionError("tipo desconocido deberia fallar")


def check_bir_helpers(program, tc):
    h = Harness()
    h.build_layouts(program, tc)
    assert h.size_of(Type("struct", name="P")) == 12
    assert h.field_offset("P", "b") == 8
    assert h.field_type("P", "a").kind == "i64"
    assert h.field_type("P", "b").kind == "str"
    tun = Type("tuple", fields=[("0", Type("i64")), ("1", Type("f64"))])
    fields, size = h.tuple_layout(tun)
    assert [(f[0], f[1], f[2]) for f in fields] == [("0", I64, 0), ("1", F64, 8)], fields
    assert size == 16, size
    assert h.variant_tag("Shape", "Rect") == 1
    assert [f[2] for f in h.variant_fields("Shape", "Rect")] == [8, 16]
    assert h.size_of(Type("str")) == 4
    try:
        h.field_offset("P", "no_existe")
    except LayoutError:
        pass
    else:
        raise AssertionError("campo inexistente deberia fallar")
    empty = Harness()
    empty.build_layouts()
    assert empty.size_of(Type("struct", name="X")) == 8


def main():
    program, tc = _program()
    layouts = compute_type_layouts(program, tc)
    checks = [
        ("producto", lambda: check_product(layouts)),
        ("suma", lambda: check_sum(layouts)),
        ("paridad con backend AST", lambda: check_parity(program, tc, layouts)),
        ("wasm_repr", check_wasm_repr),
        ("helpers BIR", lambda: check_bir_helpers(program, tc)),
    ]
    failures = 0
    for name, fn in checks:
        try:
            fn()
            print(f"ok {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {name}: {e}")
    if failures:
        print(f"{failures} fallo(s)")
        return 1
    print(f"ok {len(checks)} comprobaciones de layout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
