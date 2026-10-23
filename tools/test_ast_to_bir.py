"""Tests de Fase 4: traduccion AST -> BIR y borrow check de babirusas.

Se comprueba la forma del BIR (locals, bloques, terminadores, Rvalues y
llamadas), no la ejecucion: el codegen sigue consumiendo el AST hasta Fase 6.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.ast_to_bir import (
    prepare, translate_program, borrow_check_program, borrow_check_translated,
)


def build(src):
    prog, tc, errs = prepare(src)
    if errs:
        raise AssertionError(f"typecheck: {errs}")
    funcs, berrs = borrow_check_translated(prog, tc)
    return funcs, berrs


def fn(funcs, name):
    for f in funcs:
        if f.name == name:
            return f
    raise AssertionError(f"no existe la funcion {name!r}: {[f.name for f in funcs]}")


def stmts(f):
    return [s for b in f.blocks for s in b.stmts]


def terms(f):
    return [b.terminator for b in f.blocks if b.terminator is not None]


def assigns(f):
    return [s for s in stmts(f) if s.kind == "Assign"]


def calls(f):
    return [s for s in stmts(f) if s.kind == "Call"]


def local_names(f):
    return {l.name for l in f.locals}


def ret_name(f):
    return next(l.name for l in f.locals if l.name.startswith("__ret"))


# ---------- casos ----------

def test_aritmetica():
    funcs, berrs = build("""
fn add(a: int, b: int) -> int
	a + b
""")
    f = fn(funcs, "add")
    assert [p.name for p in f.params] == ["a", "b"]
    assert ret_name(f) in local_names(f)
    binops = [s for s in assigns(f)
              if s.rvalue is not None and s.rvalue.kind == "binop"]
    assert len(binops) == 1, binops
    assert binops[0].rvalue.op == "+"
    assert binops[0].rvalue.a.kind == "use"
    assert binops[0].rvalue.b.kind == "use"
    assert any(t.kind == "Return" for t in terms(f))
    assert berrs == [], berrs


def test_if_else():
    funcs, berrs = build("""
fn sign(n: int) -> int
	if n < 0
		-1
	else
		1
""")
    f = fn(funcs, "sign")
    switches = [t for t in terms(f) if t.kind == "SwitchInt"]
    gotos = [t for t in terms(f) if t.kind == "Goto"]
    assert len(switches) == 1, switches
    assert switches[0].cases and switches[0].otherwise is not None
    assert len(gotos) >= 2, gotos
    # ambas ramas escriben el valor de retorno
    ret_assigns = [s for s in assigns(f) if s.place.name == ret_name(f)]
    assert len(ret_assigns) == 2, ret_assigns
    assert berrs == [], berrs


def test_while_break_continue():
    funcs, berrs = build("""
fn f() -> int
	var i = 0
	while i < 10
		i += 1
		if i == 3
			continue
		if i == 7
			break
	i
""")
    f = fn(funcs, "f")
    switches = [t for t in terms(f) if t.kind == "SwitchInt"]
    # condicion del while + dos if
    assert len(switches) >= 3, switches
    # el break salta a un bloque que termina en Return (salida del bucle)
    exits = {b.id for b in f.blocks if b.terminator is not None
             and b.terminator.kind == "Return"}
    gotos = [t for t in terms(f) if t.kind == "Goto"]
    assert any(t.target in exits for t in gotos), gotos
    # continue vuelve a la condicion del while
    assert any(t.target == 1 for t in gotos), gotos
    assert berrs == [], berrs


def test_llamada_con_retorno():
    funcs, berrs = build("""
fn inc(x: int) -> int
	x + 1

fn main()
	let y = inc(2)
	y
""")
    main = fn(funcs, "main")
    cs = calls(main)
    inc = next(c for c in cs if c.call_func == "inc")
    assert inc.call_dest is not None, inc
    assert inc.call_dest.kind == "local"
    assert len(inc.call_args) == 1
    assert inc.call_args[0].kind == "const"
    assert inc.call_target is not None
    assert berrs == [], berrs


def test_struct_suma_y_match():
    funcs, berrs = build("""
type Shape
	case Circle
		r: float
	case Rect
		w: float
		h: float
	fn area(self) -> float
		match self
			case Circle(r): pi * r * r
			case Rect(w, h): w * h

fn main()
	let a = Shape.Circle(1.5)
	let b = Shape.Rect(2, 3)
	a.area() + b.area()
""")
    area = fn(funcs, "Shape.area")
    assert {"r", "w", "h"} <= local_names(area), local_names(area)
    tags = [t for t in terms(area)
            if t.kind == "SwitchInt" and t.discr is not None
            and t.discr.kind == "binop" and t.discr.a.kind == "unaryop"
            and t.discr.a.op == "tag"]
    assert tags, "el match de suma debe comparar el tag"
    assert any(t.kind == "SwitchInt" for t in terms(area))

    main = fn(funcs, "main")
    ctor = [s.rvalue for s in assigns(main)
            if s.rvalue.kind == "aggregate" and s.rvalue.agg_kind == "variant"]
    assert {a.const_value for a in ctor} == {"Shape.Circle", "Shape.Rect"}, ctor
    method_calls = [c for c in calls(main) if c.call_func == "Shape.area"]
    assert len(method_calls) == 2, method_calls
    # el receptor va como primer argumento
    assert method_calls[0].call_args[0].kind == "use"
    assert berrs == [], berrs


def test_lista_mapa_set_tupla():
    funcs, berrs = build("""
fn main()
	let l = [1, 2]
	let m = {"a": 1}
	let s = {1, 2}
	let t = (7, "x")
	let x, y = t
	let v = m["a"]
	print(f"{l[0]}{v}{s.len()}{x}{y}")
""")
    f = fn(funcs, "main")
    aggs = [s.rvalue for s in assigns(f) if s.rvalue.kind == "aggregate"]
    kinds = {a.agg_kind for a in aggs}
    assert {"list", "map", "set", "tuple"} <= kinds, kinds
    assert any(len(a.items) == 2 for a in aggs if a.agg_kind == "map")
    # desestructuracion: x/y salen de los campos 0/1 del temporal
    fields = [s for s in assigns(f)
              if s.rvalue.kind == "cast" and s.rvalue.a.kind == "use"
              and s.rvalue.a.place.kind == "field"]
    assert len(fields) >= 2, fields
    assert berrs == [], berrs


def test_closure_e_it():
    funcs, berrs = build("""
fn main()
	let nums = [1, 2, 3]
	let doubled = nums.map(it * 2)
	let base = 10
	let add = fn x => x + base
	print(doubled[2])
	print(add(1))
""")
    lambdas = [f for f in funcs if "$lambda" in f.name]
    assert len(lambdas) >= 2, [f.name for f in funcs]
    for lam in lambdas:
        assert any(t.kind == "Return" for t in terms(lam))
    main = fn(funcs, "main")
    map_call = next(c for c in calls(main) if c.call_func == "list.map")
    assert len(map_call.call_args) == 2
    assert map_call.call_args[1].kind == "aggregate"
    assert map_call.call_args[1].agg_kind == "closure"
    # la closure `add` captura `base`
    add_lambda = next(f for f in lambdas if [p.name for p in f.params] == ["x", "base"])
    assert "__ret" in " ".join(local_names(add_lambda))
    assert berrs == [], berrs


def test_or_y_question():
    funcs, berrs = build("""
fn half(x: int) -> int!
	if x % 2 == 0
		return x // 2
	err("impar", 3)

fn inc(x: int) -> int!
	let y = half(x)?
	y + 1

fn main()
	let a = inc(4) or:
		-1
	let b = inc(4) or 0
	print(a + b)
""")
    inc = fn(funcs, "inc")
    assert any(t.kind == "SwitchInt" and t.discr is not None
               and t.discr.kind == "unaryop" and t.discr.op == "is_ok"
               for t in terms(inc)), terms(inc)
    # `?` incluye un Return temprano
    assert any(t.kind == "Return" for t in terms(inc))
    main = fn(funcs, "main")
    assert any(t.kind == "SwitchInt" and t.discr is not None
               and t.discr.op == "is_ok" for t in terms(main)), terms(main)
    assert berrs == [], berrs


def test_borrow_check_integracion():
    # Un move de una lista seguido de uso debe ser detectado por babirusas
    # sobre el BIR traducido (no sobre el AST).
    prog, tc, errs = prepare("""
fn main()
	let a = [1, 2]
	let b = a
	print(a.len())
""")
    assert errs == []
    errs = borrow_check_program(prog, tc)
    assert any("moved" in e for e in errs), errs


def check(src):
    prog, tc, errs = prepare(src)
    assert errs == [], errs
    return borrow_check_program(prog, tc)


# ---------- Fase 5: borrow checker NLL ----------

def test_fase5_nll_ultimo_uso():
    assert check("""
var v = [1, 2]
let r = &v
print(r)
v.push(3)
""") == []
    errs = check("""
var v = [1, 2]
let r = &v
v.push(3)
print(r)
""")
    assert any("borrow" in e or "mutate" in e for e in errs), errs


def test_fase5_copias_y_moves():
    assert check("""
type P
	x: int
	y: int
let p = P(x: 1, y: 2)
let q = p
print(p.x + q.y)
""") == []
    errs = check("""
type P
	xs: [int]
let p = P(xs: [1])
let q = p
print(p.xs.len)
""")
    assert any("moved" in e for e in errs), errs
    assert check("""
let a = [1]
let b = copy(a)
print(a.len + b.len)
""") == []


def test_fase5_modos_parametro():
    assert check("""
fn len(v: [int]) -> int
	v.len
let v = [1]
print(len(v))
print(v.len)
""") == []
    errs = check("""
fn consume(move v: [int]) -> int
	v.len
let v = [1]
print(consume(v))
print(v.len)
""")
    assert any("moved" in e for e in errs), errs
    errs = check("""
fn push(var v: [int])
	v.push(1)
let v = [1]
push(v)
""")
    assert any("unique" in e or "var" in e for e in errs), errs
    assert check("""
fn push(var v: [int])
	v.push(1)
var v = [1]
push(v)
print(v.len)
""") == []


def test_fase5_mutabilidad():
    errs = check("""
let a = 1
a = 2
""")
    assert any("immutable" in e for e in errs), errs
    assert check("""
var a = 1
a = 2
print(a)
""") == []
    errs = check("""
fn f(v: [int])
	v.push(1)
""")
    assert any("var" in e or "unique" in e for e in errs), errs
    errs = check("""
type P
	x: int
fn f(p: P)
	p.x = 1
""")
    assert any("immutable" in e for e in errs), errs


def test_fase5_exclusividad_y_alias():
    assert check("""
var v = [1]
let a = &v
let b = &v
print(a)
print(b)
""") == []
    errs = check("""
var v = [1]
let r = &v
let s = r
v.push(3)
print(s)
""")
    assert any("borrow" in e or "mutate" in e for e in errs), errs


def test_fase5_prestamos_por_campo():
    assert check("""
type P
	x: int
	y: int
var p = P(x: 1, y: 2)
let r = &p.x
p.y = 3
print(r)
""") == []
    errs = check("""
type P
	x: int
	y: int
var p = P(x: 1, y: 2)
let r = &p.x
p.x = 3
print(r)
""")
    assert any("borrow" in e or "write" in e for e in errs), errs


def test_fase5_closures():
    assert check("""
let base = 1
let f = fn x: int => x + base
print(f(2))
""") == []
    errs = check("""
var base = 1
let f = fn x: int => x + base
base = 2
print(f(0))
""")
    assert any("borrow" in e for e in errs), errs


def test_fase5_drop_y_retorno():
    errs = check("""
let a = [1]
drop(a)
print(a.len)
""")
    assert any("moved" in e for e in errs), errs
    errs = check("""
fn f() -> &[int]
	let v = [1]
	&v
""")
    assert any("return" in e and "borrow" in e for e in errs), errs


def test_fase5_diagnostico_con_span():
    errs = check("""
let a = [1]
let b = a
print(a.len)
""")
    assert any(":4:1:" in e or "4:1:" in e for e in errs), errs


def main():
    cases = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for case in cases:
        try:
            case()
        except Exception as e:
            failed += 1
            print(f"FAIL {case.__name__}: {e}")
        else:
            print(f"ok {case.__name__}")
    if failed:
        print(f"{failed} fallo(s)")
        sys.exit(1)
    print("ok todos")


if __name__ == "__main__":
    main()
