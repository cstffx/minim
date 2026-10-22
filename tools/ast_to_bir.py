"""Traductor Minim AST -> BIR (babirusas). Prototipo inicial."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "babirusas", "src"))

from tools.nodes import *
from babirusas.src.borrowir.ir import *  # noqa

# map Minim type names to BIR Type
def to_type(t):
    if t is None:
        return Type("unit")
    # Type can be NameType etc; simplify
    name = getattr(t, "name", None) or str(t)
    if name in ("int","i64"):
        return Type("i64")
    if name in ("float","f64"):
        return Type("f64")
    if name in ("bool",):
        return Type("bool")
    if name in ("str",):
        return Type("str")
    return Type(name or "unit")

def expr_to_rvalue(e):
    if isinstance(e, IntLit):
        return Rvalue("const", const_type=Type("i64"), const_value=int(e.value))
    if isinstance(e, FloatLit):
        return Rvalue("const", const_type=Type("f64"), const_value=float(e.value))
    if isinstance(e, StrLit):
        return Rvalue("const", const_type=Type("str"), const_value=e.value)
    if isinstance(e, BoolLit):
        return Rvalue("const", const_type=Type("bool"), const_value=bool(e.value))
    if isinstance(e, NameExpr):
        return Rvalue("use", place=Place("local", e.name))
    if isinstance(e, BinOp):
        return Rvalue("binop", op=e.op, a=expr_to_rvalue(e.left), b=expr_to_rvalue(e.right))
    if isinstance(e, UnaryOp):
        return Rvalue("unaryop", op=e.op, a=expr_to_rvalue(e.operand))
    raise NotImplementedError(f"expr not supported: {type(e).__name__}")

def translate_stmt(st, fn, block):
    if isinstance(st, LetDecl) or isinstance(st, LetStmt):
        bindings = st.bindings if hasattr(st, "bindings") else [Binding("name", st.name)]
        # single binding assumed
        name = None
        for b in bindings:
            if getattr(b, "kind", None) == "name":
                name = b.name
            elif hasattr(b, "name"):
                name = b.name
        if name is None and hasattr(st, "name"):
            name = st.name
        typ = to_type(getattr(st, "type_", None))
        fn.locals.append(Local(name, typ, False))
        block.stmts.append(Stmt("StorageLive", place=Place("local", name)))
        if getattr(st, "value", None) is not None:
            block.stmts.append(Stmt("Assign", place=Place("local", name), rvalue=expr_to_rvalue(st.value)))
        return
    if isinstance(st, VarDecl) or isinstance(st, VarStmt):
        bindings = st.bindings if hasattr(st, "bindings") else []
        name = None
        for b in bindings:
            name = getattr(b, "name", name)
        if name is None and hasattr(st, "name"):
            name = st.name
        typ = to_type(getattr(st, "type_", None))
        fn.locals.append(Local(name, typ, True))
        block.stmts.append(Stmt("StorageLive", place=Place("local", name)))
        if getattr(st, "value", None) is not None:
            block.stmts.append(Stmt("Assign", place=Place("local", name), rvalue=expr_to_rvalue(st.value)))
        return
    if isinstance(st, Assign):
        place = Place("local", st.place.name)
        # apply field/index parts
        for part in (st.place.parts or []):
            if isinstance(part, tuple) and part and part[0] == "field":
                place = Place("field", base=place, field=part[1])
            elif isinstance(part, tuple) and part and part[0] == "index":
                place = Place("index", base=place, idx=expr_to_rvalue(part[1]))
        if st.op in ("=", "+=", "-=", "*=", "/="):
            if st.op == "=":
                block.stmts.append(Stmt("Assign", place=place, rvalue=expr_to_rvalue(st.value)))
            else:
                op = st.op[0]
                rv = Rvalue("binop", op=op, a=Rvalue("use", place=place), b=expr_to_rvalue(st.value))
                block.stmts.append(Stmt("Assign", place=place, rvalue=rv))
        return
    if isinstance(st, ReturnStmt):
        if st.value is not None:
            # store in a temp? For now ignore value
            pass
        block.terminator = Term("Return")
        return
    if isinstance(st, ExprStmt):
        # only handle direct calls as statements
        e = st.expr
        if isinstance(e, Postfix) and e.ops and e.ops[-1][0] == "call":
            # function name from base
            fname = e.base.name if isinstance(e.base, NameExpr) else str(e.base)
            args = []
            for a in (e.ops[-1][1] or []):
                val = a.value if isinstance(a, Arg) else a
                args.append(expr_to_rvalue(val))
            call = Stmt("Call", call_func=fname, call_args=args, call_target=len(fn.blocks))  # placeholder
            block.stmts.append(call)
        return
    # If/While/For: todo
    raise NotImplementedError(f"stmt not supported: {type(st).__name__}")

def translate_function(fd: FnDecl) -> Function:
    fn = Function(fd.name)
    for p in (fd.params or []):
        fn.params.append(Param(p.name, to_type(getattr(p, "type_", None)), getattr(p, "mutable", False)))
        fn.locals.append(Local(p.name, to_type(getattr(p, "type_", None)), getattr(p, "mutable", False)))
    block = Block(0)
    fn.blocks.append(block)
    fn.entry = 0
    body = fd.body
    stmts = body.stmts if hasattr(body, "stmts") else []
    for st in stmts:
        translate_stmt(st, fn, block)
    if block.terminator is None:
        block.terminator = Term("Return")
    return fn

def translate_program(prog: Program):
    fns = []
    for st in prog.stmts:
        if isinstance(st, FnDecl):
            fns.append(translate_function(st))
    return fns
