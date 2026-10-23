"""Monomorfización de funciones genéricas (Fase 2).

El compilador de referencia no tiene un lenguaje intermedio con tipos: la
especialización se hace sobre el AST. Cada llamada a `fn f[T](...)` con tipos
concretos produce una copia `f$<mangle>` con los parámetros de tipo sustituidos.
El despacho de traits es estático: tras sustituir `T` por un tipo concreto, las
llamadas a métodos del trait resuelven al método real del tipo.
"""
import copy

from tools.nodes import *
from tools.typecheck import TC, V, UNKNOWN


def _type_ast(ty):
    """Convierte un tipo del type checker a un nodo Type del parser."""
    if ty is None:
        return None
    k = ty[0]
    if k == "p":
        return Type(TypeName(ty[1], []))
    if k == "named":
        return Type(TypeName(ty[1], [_type_ast(a) for a in ty[2]]))
    if k == "list":
        return Type(TypeList(_type_ast(ty[1])))
    if k == "map":
        return Type(TypeMap(_type_ast(ty[1]), _type_ast(ty[2])))
    if k == "set":
        return Type(TypeSet(_type_ast(ty[1])))
    if k == "tuple":
        return Type(TypeTuple([_type_ast(t) for t in ty[1]]))
    if k == "opt":
        return Type(TypeSuffix(_type_ast(ty[1]), "?"))
    if k == "res":
        return Type(TypeSuffix(_type_ast(ty[1]), "!"))
    if k == "borrow":
        return Type(TypeBorrow(_type_ast(ty[1])))
    if k == "func":
        return Type(TypeFunc([_type_ast(p) for p in (ty[1] or ())], _type_ast(ty[2])))
    return Type(TypeName("int", []))


def _subst_type(t, subst):
    if t is None:
        return None
    if isinstance(t, Type):
        return Type(_subst_type(t.node, subst))
    if isinstance(t, TypeName):
        if t.name in subst and not (t.args or []):
            return _type_ast(subst[t.name])
        return TypeName(t.name, [_subst_type(a, subst) for a in (t.args or [])])
    if isinstance(t, TypeList):
        return TypeList(_subst_type(t.inner, subst))
    if isinstance(t, TypeMap):
        return TypeMap(_subst_type(t.key, subst), _subst_type(t.val, subst))
    if isinstance(t, TypeSet):
        return TypeSet(_subst_type(t.inner, subst))
    if isinstance(t, TypeBorrow):
        return TypeBorrow(_subst_type(t.inner, subst))
    if isinstance(t, TypeTuple):
        return TypeTuple([_subst_type(x, subst) for x in t.items])
    if isinstance(t, TypeFunc):
        return TypeFunc([_subst_type(x, subst) for x in t.params],
                        _subst_type(t.ret, subst))
    if isinstance(t, TypeParen):
        return TypeParen(_subst_type(t.inner, subst))
    if isinstance(t, TypeSuffix):
        return TypeSuffix(_subst_type(t.base, subst), t.suffix)
    return t


def _mangle(ty):
    if ty is None:
        return "u"
    k = ty[0]
    if k == "p":
        return ty[1]
    if k == "named":
        args = "_".join(_mangle(a) for a in ty[2])
        return ty[1] + (f"_{args}" if args else "")
    if k == "list":
        return "list_" + _mangle(ty[1])
    if k == "map":
        return "map_" + _mangle(ty[1]) + "_" + _mangle(ty[2])
    if k == "set":
        return "set_" + _mangle(ty[1])
    if k == "tuple":
        return "tup_" + "_".join(_mangle(t) for t in ty[1])
    if k in ("opt", "res"):
        return k + "_" + _mangle(ty[1])
    return "u"


def _transform_expr(e, subst):
    if e is None:
        return
    if isinstance(e, Postfix):
        for op in (e.ops or []):
            if op[0] == "as":
                e.ops[e.ops.index(op)] = ("as", _subst_type(op[1], subst))
            elif op[0] == "typeargs":
                e.ops[e.ops.index(op)] = ("typeargs", [_subst_type(t, subst) for t in op[1]])
            elif op[0] == "call":
                for a in (op[1] or []):
                    _transform_expr(a.value if isinstance(a, Arg) else a, subst)
            elif op[0] in ("index", "slice"):
                for p in op[1:]:
                    if p is not None:
                        _transform_expr(p, subst)
        _transform_expr(e.base, subst)
    elif isinstance(e, BinOp):
        _transform_expr(e.left, subst)
        if isinstance(e.right, OrBlock):
            _transform_suite(e.right.body, subst)
        else:
            _transform_expr(e.right, subst)
    elif isinstance(e, UnaryOp):
        _transform_expr(e.operand, subst)
    elif isinstance(e, BorrowExpr):
        _transform_expr(e.operand, subst)
    elif isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
        for a in (e.items or []):
            _transform_expr(a.value if isinstance(a, Arg) else a, subst)
    elif isinstance(e, Lambda):
        _transform_expr(e.body, subst)
    elif isinstance(e, MoveExpr):
        _transform_expr(e.lambda_, subst)
    elif isinstance(e, IfExpr):
        _transform_expr(e.cond, subst); _transform_expr(e.then, subst); _transform_expr(e.else_, subst)
    elif isinstance(e, MatchExpr):
        _transform_expr(e.expr, subst)
        for arm in (e.arms or []):
            if arm.guard is not None:
                _transform_expr(arm.guard, subst)
            if isinstance(arm.body, Suite):
                _transform_suite(arm.body, subst)
            else:
                _transform_expr(arm.body, subst)
    elif isinstance(e, OrBlock):
        _transform_suite(e.body, subst)


def _transform_stmt(st, subst):
    if isinstance(st, (LetStmt, VarStmt)):
        for b in (st.bindings or []):
            if getattr(b, "type_", None) is not None:
                b.type_ = _subst_type(b.type_, subst)
        _transform_expr(st.value, subst)
    elif isinstance(st, (LetDecl, VarDecl)):
        _transform_expr(st.value, subst)
        if getattr(st, "type_", None) is not None:
            st.type_ = _subst_type(st.type_, subst)
        for b in (getattr(st, "bindings", None) or []):
            if getattr(b, "type_", None) is not None:
                b.type_ = _subst_type(b.type_, subst)
    elif isinstance(st, ExprStmt):
        _transform_expr(st.expr, subst)
    elif isinstance(st, Assign):
        _transform_expr(st.value, subst)
    elif isinstance(st, ReturnStmt):
        _transform_expr(st.value, subst)
    elif isinstance(st, IfStmt):
        _transform_expr(st.cond, subst)
        _transform_suite(st.then, subst)
        for ec, es in (st.elifs or []):
            _transform_expr(ec, subst); _transform_suite(es, subst)
        if st.else_ is not None:
            _transform_suite(st.else_, subst)
    elif isinstance(st, WhileStmt):
        _transform_expr(st.cond, subst); _transform_suite(st.body, subst)
    elif isinstance(st, ForStmt):
        _transform_expr(st.iter, subst)
        for b in (st.bindings or []):
            if getattr(b, "type_", None) is not None:
                b.type_ = _subst_type(b.type_, subst)
        _transform_suite(st.body, subst)
    elif isinstance(st, MatchStmt):
        _transform_expr(st.expr, subst)
        for arm in (st.arms or []):
            if arm.guard is not None:
                _transform_expr(arm.guard, subst)
            if isinstance(arm.body, Suite):
                _transform_suite(arm.body, subst)
            else:
                _transform_expr(arm.body, subst)


def _transform_suite(suite, subst):
    for st in (suite.stmts if hasattr(suite, "stmts") else []):
        _transform_stmt(st, subst)


def _specialize(fn, spec, subst):
    cl = copy.deepcopy(fn)
    cl.name = spec
    cl.tparams = []
    for p in (cl.params or []):
        if p.type_ is not None:
            p.type_ = _subst_type(p.type_, subst)
        if p.default is not None:
            _transform_expr(p.default, subst)
    if cl.ret is not None:
        cl.ret = _subst_type(cl.ret, subst)
    _transform_suite(cl.body, subst)
    return cl


def _generic_callee(e):
    """Return (name, name_node, typeargs) when `e` is a call to a bare name."""
    if not isinstance(e, Postfix) or not (e.ops and e.ops[-1][0] == "call"):
        return None
    base = e.base
    typeargs = None
    if isinstance(base, Postfix) and base.ops and base.ops[-1][0] == "typeargs":
        typeargs = base.ops[-1][1]
        base = base.base
    if isinstance(base, NameExpr):
        return base.name, base, typeargs
    return None


class _Scanner:
    def __init__(self, tc, generics):
        self.tc = tc
        self.generics = generics
        self.pending = []   # (postfix_node, spec_name, fn, subst)
        self.created = {}

    def _scope(self, fn):
        return self.tc.resolver.func_scopes.get(id(fn)) or self.tc.module_scope

    def _arg_types(self, args, scope):
        out = []
        for a in args:
            val = a.value if isinstance(a, Arg) else a
            out.append(self.tc.expr(val, scope))
        return out

    def _try_call(self, e, scope):
        got = _generic_callee(e)
        if got is None:
            return
        name, name_node, typeargs = got
        fn = self.generics.get(name)
        if fn is None:
            return
        sym = self.tc.module_scope.lookup(name)
        fty = getattr(sym, "ty", None) if sym is not None else None
        if not (isinstance(fty, tuple) and fty[0] == "func"):
            return
        params = fty[1] or ()
        subst = {}
        if typeargs:
            for tp, ta in zip(fty[3], typeargs):
                subst[tp] = self.tc._atype(ta)
        args = e.ops[-1][1] or []
        ats = self._arg_types(args, scope)
        for i, pt in enumerate(params):
            if i < len(ats):
                self.tc.unify(pt, ats[i], subst)
        if any(tp not in subst for tp in fty[3]):
            return
        if any(v[0] in ("var", "u") for v in subst.values()):
            return
        spec = name + "$" + "_".join(_mangle(subst[tp]) for tp in fty[3])
        self.pending.append((e, spec, fn, dict(subst)))

    def expr(self, e, scope):
        if e is None:
            return
        self._try_call(e, scope)
        if isinstance(e, Postfix):
            self.expr(e.base, scope)
            for op in (e.ops or []):
                if op[0] == "call":
                    for a in (op[1] or []):
                        self.expr(a.value if isinstance(a, Arg) else a, scope)
                elif op[0] in ("index", "slice"):
                    for p in op[1:]:
                        if p is not None:
                            self.expr(p, scope)
        elif isinstance(e, BinOp):
            self.expr(e.left, scope)
            if isinstance(e.right, OrBlock):
                self.suite(e.right.body, scope)
            else:
                self.expr(e.right, scope)
        elif isinstance(e, UnaryOp):
            self.expr(e.operand, scope)
        elif isinstance(e, BorrowExpr):
            self.expr(e.operand, scope)
        elif isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
            for a in (e.items or []):
                self.expr(a.value if isinstance(a, Arg) else a, scope)
        elif isinstance(e, Lambda):
            self.expr(e.body, scope)
        elif isinstance(e, MoveExpr):
            self.expr(e.lambda_, scope)
        elif isinstance(e, IfExpr):
            self.expr(e.cond, scope); self.expr(e.then, scope); self.expr(e.else_, scope)
        elif isinstance(e, MatchExpr):
            self.expr(e.expr, scope)
            for arm in (e.arms or []):
                if arm.guard is not None:
                    self.expr(arm.guard, scope)
                if isinstance(arm.body, Suite):
                    self.suite(arm.body, scope)
                else:
                    self.expr(arm.body, scope)

    def stmt(self, st, scope):
        if isinstance(st, (LetStmt, VarStmt, LetDecl, VarDecl)):
            self.expr(st.value, scope)
        elif isinstance(st, ExprStmt):
            self.expr(st.expr, scope)
        elif isinstance(st, Assign):
            self.expr(st.value, scope)
        elif isinstance(st, ReturnStmt):
            self.expr(st.value, scope)
        elif isinstance(st, IfStmt):
            self.expr(st.cond, scope); self.suite(st.then, scope)
            for ec, es in (st.elifs or []):
                self.expr(ec, scope); self.suite(es, scope)
            if st.else_ is not None:
                self.suite(st.else_, scope)
        elif isinstance(st, WhileStmt):
            self.expr(st.cond, scope); self.suite(st.body, scope)
        elif isinstance(st, ForStmt):
            self.expr(st.iter, scope); self.suite(st.body, scope)
        elif isinstance(st, (SpawnStmt, AwaitStmt)):
            self.expr(st.expr, scope)
        elif isinstance(st, MatchStmt):
            self.expr(st.expr, scope)
            for arm in (st.arms or []):
                if arm.guard is not None:
                    self.expr(arm.guard, scope)
                if isinstance(arm.body, Suite):
                    self.suite(arm.body, scope)
                else:
                    self.expr(arm.body, scope)

    def suite(self, suite, scope):
        for st in (suite.stmts if hasattr(suite, "stmts") else []):
            self.stmt(st, scope)


def monomorphize(program, max_rounds=32):
    """Expand all concrete calls to generic functions in `program`."""
    created = {}
    for _ in range(max_rounds):
        tc = TC(program)
        errs = tc.check()
        if errs:
            raise ValueError(str(errs[0]))
        generics = {s.name: s for s in program.stmts
                    if isinstance(s, FnDecl) and s.tparams}
        sc = _Scanner(tc, generics)
        for st in program.stmts:
            if isinstance(st, FnDecl):
                sc.suite(st.body, sc._scope(st))
            elif isinstance(st, TypeDecl):
                for m in st.members:
                    if isinstance(m.node, FnDecl):
                        sc.suite(m.node.body, sc._scope(m.node))
        # module-level statements
        for st in program.stmts:
            if not isinstance(st, (FnDecl, TypeDecl, TraitDecl, UseDecl)):
                sc.stmt(st, tc.module_scope)
        if not sc.pending:
            break
        new_decls = []
        for node, spec, fn, subst in sc.pending:
            # drop explicit typeargs: the specialization has none
            if isinstance(node.base, Postfix) and node.base.ops and node.base.ops[-1][0] == "typeargs":
                node.base = node.base.base
            if isinstance(node.base, NameExpr):
                node.base.name = spec
            if spec not in created:
                created[spec] = True
                new_decls.append(_specialize(fn, spec, subst))
        program.stmts.extend(new_decls)
    # generic declarations themselves are no longer needed
    program.stmts = [s for s in program.stmts
                     if not (isinstance(s, FnDecl) and s.tparams)]
    return program

