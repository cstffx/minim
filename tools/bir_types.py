from tools import nodes as A
from babirusas.src.borrowir.ir import Type, Place, Rvalue


def _prim(name):
    return {"int": "i64", "i64": "i64", "float": "f64", "f64": "f64",
            "bool": "bool", "str": "str", "bytes": "bytes",
            "nil": "unit", "unit": "unit"}.get(name)


def _ast_type(t):
    """Tipo de `tools/nodes.py` -> `Type` de BIR."""
    if t is None:
        return Type("unit")
    if isinstance(t, A.Type):
        return _ast_type(t.node)
    if isinstance(t, A.TypeName):
        base = _prim(t.name)
        if base is not None:
            return Type(base)
        if t.name in ("task",) and t.args:
            return Type("task", elem=_ast_type(t.args[0]))
        if t.name == "list" and t.args:
            return Type("list", elem=_ast_type(t.args[0]))
        if t.name == "set" and t.args:
            return Type("set", elem=_ast_type(t.args[0]))
        return Type("struct", name=t.name)
    if isinstance(t, A.TypeList):
        return Type("list", elem=_ast_type(t.inner))
    if isinstance(t, A.TypeMap):
        return Type("map", elem=_ast_type(t.key), fields=[("value", _ast_type(t.val))])
    if isinstance(t, A.TypeSet):
        return Type("set", elem=_ast_type(t.inner))
    if isinstance(t, A.TypeBorrow):
        return Type("ref", elem=_ast_type(t.inner), ref_kind=0)
    if isinstance(t, A.TypeTuple):
        return Type("tuple", fields=[(str(i), _ast_type(x)) for i, x in enumerate(t.items)])
    if isinstance(t, A.TypeFunc):
        return Type("func", fields=[("param", _ast_type(x)) for x in (t.params or [])],
                    elem=_ast_type(t.ret))
    if isinstance(t, A.TypeParen):
        return _ast_type(t.inner) if t.inner is not None else Type("unit")
    if isinstance(t, A.TypeSuffix):
        inner = _ast_type(t.base)
        return Type("opt", elem=inner) if t.suffix == "?" else Type("res", elem=inner)
    return Type("unknown")


def _tc_type(ty):
    """Tipo del typechecker (tuplas `("p", ...)`) -> `Type` de BIR."""
    if ty is None:
        return Type("unknown")
    if isinstance(ty, Type):
        return ty
    kind = ty[0]
    if kind == "p":
        return Type(_prim(ty[1]) or ty[1])
    if kind in ("u", "var"):
        return Type("unknown")
    if kind == "err":
        return Type("err")
    if kind in ("list", "set", "opt", "res", "borrow"):
        return Type(kind, elem=_tc_type(ty[1]), ref_kind=0 if kind == "borrow" else 0)
    if kind == "map":
        return Type("map", elem=_tc_type(ty[1]),
                    fields=[("value", _tc_type(ty[2]))])
    if kind == "tuple":
        items = ty[1] if isinstance(ty[1], (tuple, list)) else ()
        return Type("tuple", fields=[(str(i), _tc_type(x)) for i, x in enumerate(items)])
    if kind == "func":
        params = ty[1] or ()
        return Type("func", fields=[("param", _tc_type(x)) for x in params],
                    elem=_tc_type(ty[2]) if ty[2] is not None else Type("unit"))
    if kind == "named":
        name = ty[1]
        args = ty[2] if len(ty) > 2 else ()
        if name == "task" and args:
            return Type("task", elem=_tc_type(args[0]))
        return Type("struct", name=name)
    return Type("unknown")


def to_type(t):
    """Compatibility helper: acepta tipos de AST, del typechecker o BIR."""
    if isinstance(t, Type):
        return t
    if isinstance(t, tuple) and t and isinstance(t[0], str):
        return _tc_type(t)
    if isinstance(t, (A.Type, A.TypeName, A.TypeList, A.TypeMap, A.TypeSet,
                      A.TypeBorrow, A.TypeTuple, A.TypeFunc, A.TypeParen,
                      A.TypeSuffix)):
        return _ast_type(t)
    return Type("unknown")


def _param_mode(p):
    """Modo de parametro de superficie -> modo BIR."""
    return {"var": "unique", "move": "move"}.get(getattr(p, "mode", None), "shared")


def _bir_copyable(ty):
    """Copiabilidad segun el tipo BIR (conservador: structs no)."""
    if ty is None:
        return False
    if ty.kind in ("i64", "f64", "bool", "str", "bytes", "unit", "ref", "func"):
        return True
    if ty.kind == "tuple":
        return all(_bir_copyable(t) for _, t in ty.fields)
    return False


def _type_label(ty):
    """Nombre corto de un tipo del typechecker, para nombrar metodos."""
    if ty is None:
        return "?"
    kind = ty[0]
    if kind == "p":
        return ty[1]
    if kind == "named":
        return ty[1]
    if kind in ("list", "map", "set", "opt", "res", "tuple", "func"):
        return kind
    return "?"


# ---------- small constructors ----------

def _local(name):
    return Place("local", name=name)


def _field(base, name):
    return Place("field", base=base, field=str(name))


def _index(base, idx):
    return Place("index", base=base, idx=idx)


def _use(place):
    return Rvalue("use", place=place)


def _const(ty, value):
    return Rvalue("const", const_type=ty, const_value=value)


def _int_const(v):
    return _const(Type("i64"), int(v))


def _bool_const(v):
    return _const(Type("bool"), bool(v))


def _cmp_eq(place, value):
    return Rvalue("binop", op="==", a=_use(place), b=value)


def place_type_guess(place):
    return Type("unknown")
