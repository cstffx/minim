"""Core IR de Minim: subconjunto minimo + elaboracion (desazucar) de superficie.

Elabora ForStmt -> WhileStmt (rangos y listas) para que typecheck/borrow/codegen
operen sobre un conjunto reducido. Method calls y slices se mantienen (el borrow
checker los necesita con su modo).
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.nodes import *
from tools.parser import parse


def _binding_name(b):
    if getattr(b, "kind", None) == "name" and getattr(b, "name", None):
        return b.name
    return None


_loop_seq = [0]


def _fresh(prefix):
    _loop_seq[0] += 1
    return f"__{prefix}{_loop_seq[0]}"


def _method_call(receiver, method, args=()):
    # El parser anida una capa Postfix por operacion; los handlers de codegen
    # asumen esa forma (`recv.method` en `e.base`, llamada en `e.ops`).
    return Postfix(Postfix(receiver, [("field", method)]), [("call", list(args))])


def _index(receiver, idx):
    return Postfix(receiver, [("index", idx)])


def _field(receiver, name):
    return Postfix(receiver, [("field", name)])


def _iter_type(st, tc, scope):
    """Tipo estatico del iterable, cuando se dispone de typecheck."""
    if tc is None or scope is None:
        return None
    try:
        return tc.expr(st.iter, scope)
    except Exception:
        return None


def _desugar_indexed(st, source_expr, body_stmts, mode):
    """Bucle indexado sobre `source_expr`.

    mode:
      "elem"    -> `for x in xs`: x = &it[idx]
      "index"   -> `for i, x in xs`: i = idx, x = &it[idx]
      "fields"  -> `for a, b in pares`: a = pair.0, b = pair.1
    """
    it_name = _fresh("it")
    idx_name = _fresh("i")
    named = [b for b in (st.bindings or []) if _binding_name(b)]
    out = [
        # Iterate by borrow, not by move: `for x in v` must not consume `v`.
        LetStmt([Binding("name", it_name)], BorrowExpr(source_expr)),
        LetStmt([Binding("name", idx_name)], IntLit("0")),
    ]
    cond = BinOp("<", NameExpr(idx_name), _field(NameExpr(it_name), "len"))
    loop_body = []
    if mode == "elem":
        if named:
            loop_body.append(LetStmt([named[0]],
                            BorrowExpr(_index(NameExpr(it_name), NameExpr(idx_name)))))
    elif mode == "index":
        if named:
            loop_body.append(LetStmt([named[0]], NameExpr(idx_name)))
        if len(named) > 1:
            loop_body.append(LetStmt([named[1]],
                            BorrowExpr(_index(NameExpr(it_name), NameExpr(idx_name)))))
    else:
        # let a, b = &it[idx] (tuplas: campos 0 y 1)
        pair = _fresh("pair")
        loop_body.append(LetStmt([Binding("name", pair)],
                        BorrowExpr(_index(NameExpr(it_name), NameExpr(idx_name)))))
        for pos, b in enumerate(named):
            loop_body.append(LetStmt([b], _field(NameExpr(pair), pos)))
    loop_body.extend(body_stmts)
    # Touch the iterator after the user body so the borrow's last-use covers
    # the whole loop body, not just its last textual mention of it -- the
    # loan must stay live for every statement in the loop, including ones
    # that don't reference it directly (e.g. mutating the owner, which
    # must be rejected while the iteration borrow is alive).
    loop_body.append(ExprStmt(NameExpr(it_name)))
    loop_body.append(Assign(Place(idx_name, []), "+=", IntLit("1")))
    loop_stmt = WhileStmt(cond, Suite(loop_body))
    # `continue` in a `for` must still run the loop increment. Codegen uses
    # this marker to wrap the user body in a block that continue targets.
    loop_stmt._for_continue_count = len(loop_body) - 2
    out.append(loop_stmt)
    return out


def desugar_for_stmt(st, tc=None, scope=None):
    """Devuelve una lista de statements core equivalentes a un ForStmt.

    Con `tc` (typecheck ya ejecutado) se distingue el tipo del iterable para
    mapear `for k, v in mapa` y `for i, x in lista` con la semantica correcta.
    """
    it = st.iter
    body_stmts = list(st.body.stmts) if hasattr(st.body, "stmts") else []
    # Range: for x in a..b / a..=b
    if isinstance(it, BinOp) and it.op in ("..", "..="):
        inclusive = it.op == "..="
        varname = None
        for b in (st.bindings or []):
            vn = _binding_name(b)
            if vn:
                varname = vn
                break
        if varname is None:
            varname = _fresh("i")
        # let var = left
        out = [LetStmt([Binding("name", varname)], it.left)]
        # while var < right (or <=)
        cond = BinOp("<=" if inclusive else "<", NameExpr(varname), it.right)
        loop_body = list(body_stmts) + [Assign(Place(varname, []), "+=", IntLit("1"))]
        loop_stmt = WhileStmt(cond, Suite(loop_body))
        # `continue` debe ejecutar el incremento antes de repetir.
        loop_stmt._for_continue_count = len(body_stmts)
        out.append(loop_stmt)
        return out

    ity = _iter_type(st, tc, scope)
    named = [b for b in (st.bindings or []) if _binding_name(b)]
    # Mapas: una variable recorre claves; dos recorren pares (clave, valor).
    if isinstance(ity, tuple) and ity[0] == "map":
        if len(named) <= 1:
            return _desugar_indexed(st, _method_call(it, "keys"), body_stmts,
                                    mode="elem")
        return _desugar_indexed(st, _method_call(it, "items"), body_stmts,
                                mode="fields")
    # Listas: `for i, x in xs` recorre indice + elemento.
    if isinstance(ity, tuple) and ity[0] == "list":
        return _desugar_indexed(st, it, body_stmts,
                                mode=("index" if len(named) > 1 else "elem"))
    # str/bytes/set u otros iterables: una variable; con dos, se asume
    # indice + elemento salvo que el tipo sea desconocido.
    return _desugar_indexed(st, it, body_stmts,
                            mode=("index" if len(named) > 1 else "elem"))


_CMP_OPS = {"<", "<=", ">", ">=", "==", "!="}

def _contains_it(e):
    if isinstance(e, ItExpr):
        return True
    if isinstance(e, Lambda):
        return False
    if isinstance(e, BinOp):
        return _contains_it(e.left) or _contains_it(e.right)
    if isinstance(e, UnaryOp):
        return _contains_it(e.operand)
    if isinstance(e, Postfix):
        if _contains_it(e.base):
            return True
        for op in (e.ops or []):
            if op[0] == "call":
                for a in (op[1] or []):
                    if _contains_it(a.value if isinstance(a, Arg) else a):
                        return True
            elif op[0] in ("index", "slice"):
                for part in op[1:]:
                    if part is not None and not isinstance(part, str) and _contains_it(part):
                        return True
    if isinstance(e, IfExpr):
        return _contains_it(e.cond) or _contains_it(e.then) or _contains_it(e.else_)
    if isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
        for a in (e.items or []):
            if _contains_it(a.value if isinstance(a, Arg) else a):
                return True
    if isinstance(e, MatchExpr):
        if _contains_it(e.expr):
            return True
        for arm in (e.arms or []):
            if arm.guard is not None and _contains_it(arm.guard):
                return True
            if arm.body is not None and not isinstance(arm.body, Suite) and _contains_it(arm.body):
                return True
    return False


def _desugar_expr(e):
    if isinstance(e, BinOp):
        left = _desugar_expr(e.left)
        right = _desugar_expr(e.right)
        if e.op in _CMP_OPS and isinstance(right, BinOp) and right.op in _CMP_OPS:
            mid = right.left
            left_cmp = BinOp(e.op, left, mid)
            right_cmp = right
            return BinOp("and", _desugar_expr(left_cmp), _desugar_expr(right_cmp))
        if e.op in _CMP_OPS and isinstance(left, BinOp) and left.op in _CMP_OPS:
            mid = left.right
            left_cmp = left
            right_cmp = BinOp(e.op, mid, right)
            return BinOp("and", _desugar_expr(left_cmp), _desugar_expr(right_cmp))
        return BinOp(e.op, left, right)
    if isinstance(e, UnaryOp):
        return UnaryOp(e.op, _desugar_expr(e.operand))
    if isinstance(e, Postfix):
        base = _desugar_expr(e.base)
        ops = []
        for op in (e.ops or []):
            if op[0] == "call":
                args = []
                for a in (op[1] or []):
                    val = a.value if isinstance(a, Arg) else a
                    nv = _desugar_expr(val)
                    if isinstance(a, Arg) and not a.is_named and _contains_it(nv):
                        nv = Lambda([Param(None, "it", None, None)], nv)
                    args.append(Arg(a.label, nv, a.is_named, a.span) if isinstance(a, Arg) else nv)
                ops.append((op[0], args))
            elif op[0] in ("index", "slice"):
                idx = op[1]
                if not isinstance(idx, str) and idx is not None:
                    idx = _desugar_expr(idx)
                ops.append((op[0], idx) + tuple(op[2:]))
            else:
                ops.append(op)
        return Postfix(base, ops, e.span)
    if isinstance(e, IfExpr):
        return IfExpr(_desugar_expr(e.cond), _desugar_expr(e.then), _desugar_expr(e.else_), e.span)
    if isinstance(e, MatchExpr):
        arms = []
        for arm in (e.arms or []):
            body = arm.body
            if isinstance(body, Suite):
                _desugar_suite(body)
            elif body is not None:
                body = _desugar_expr(body)
            guard = _desugar_expr(arm.guard) if arm.guard is not None else None
            arms.append(Arm(arm.pattern, guard, body, arm.is_else, arm.span))
        return MatchExpr(_desugar_expr(e.expr), arms, e.one_line, e.span)
    if isinstance(e, LetStmt) if False else False:
        pass
    if isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
        items = []
        for a in (getattr(e, "items", None) or []):
            val = a.value if isinstance(a, Arg) else a
            nv = _desugar_expr(val)
            if isinstance(a, Arg):
                items.append(Arg(a.label, nv, a.is_named, a.span))
            else:
                items.append(nv)
        if isinstance(e, TupleExpr):
            return TupleExpr(items, e.span)
        if isinstance(e, ListExpr):
            return ListExpr(items, e.span)
        if isinstance(e, SetExpr):
            return SetExpr(items, e.span)
        return MapExpr(items, e.span)
    return e

def _desugar_stmt_exprs(st, tc=None):
    if isinstance(st, (LetStmt, VarStmt, LetDecl, VarDecl)):
        st.value = _desugar_expr(st.value)
    elif isinstance(st, Assign):
        st.value = _desugar_expr(st.value)
        if st.place is not None:
            pass
    elif isinstance(st, ExprStmt):
        st.expr = _desugar_expr(st.expr)
    elif isinstance(st, ReturnStmt) and st.value is not None:
        st.value = _desugar_expr(st.value)
    elif isinstance(st, IfStmt):
        st.cond = _desugar_expr(st.cond)
        if st.then is not None:
            _desugar_suite(st.then, tc)
        for ec, es in (st.elifs or []):
            ec_new = _desugar_expr(ec)
            # store back
            # elifs is list of (cond, suite)
            pass
        if st.else_ is not None:
            _desugar_suite(st.else_, tc)
    elif isinstance(st, WhileStmt):
        st.cond = _desugar_expr(st.cond)
        if st.body is not None:
            _desugar_suite(st.body, tc)
    elif isinstance(st, MatchStmt):
        st.expr = _desugar_expr(st.expr)
        for arm in (st.arms or []):
            if arm.guard is not None:
                arm.guard = _desugar_expr(arm.guard)
            if isinstance(arm.body, Suite):
                _desugar_suite(arm.body, tc)
            elif arm.body is not None:
                arm.body = _desugar_expr(arm.body)
    elif isinstance(st, ForStmt):
        if not isinstance(st.iter, str):
            st.iter = _desugar_expr(st.iter)
        if st.body is not None:
            _desugar_suite(st.body, tc)
    elif isinstance(st, (SpawnStmt, AwaitStmt)):
        st.expr = _desugar_expr(st.expr)
    elif isinstance(st, (FnDecl,)):
        if st.body is not None:
            _desugar_suite(st.body, tc)
    elif isinstance(st, TypeDecl):
        for m in (st.members or []):
            if isinstance(m.node, FnDecl) and m.node.body is not None:
                _desugar_suite(m.node.body, tc)
    # handle elifs properly
    if isinstance(st, IfStmt):
        new_elifs = []
        for ec, es in (st.elifs or []):
            new_elifs.append((_desugar_expr(ec), es))
            _desugar_suite(es, tc)
        st.elifs = new_elifs

def _desugar_suite(suite, tc=None):
    if not hasattr(suite, "stmts"):
        return
    new = []
    for st in suite.stmts:
        if isinstance(st, ForStmt):
            ds = desugar_for_stmt(st, tc, tc.stmt_scopes.get(id(st)) if tc else None)
            for nst in ds:
                _desugar_stmt_exprs(nst, tc)
            new.extend(ds)
        else:
            _desugar_stmt_exprs(st, tc)
            new.append(st)
            if isinstance(st, (IfStmt, WhileStmt, FnDecl, TypeDecl)):
                pass
    # recurse into nested suites
    for st in new:
        if isinstance(st, IfStmt):
            if st.then is not None: _desugar_suite(st.then, tc)
            for ec, es in (st.elifs or []):
                _desugar_suite(es, tc)
            if st.else_ is not None: _desugar_suite(st.else_, tc)
        elif isinstance(st, WhileStmt):
            if st.body is not None: _desugar_suite(st.body, tc)
        elif isinstance(st, FnDecl):
            if st.body is not None: _desugar_suite(st.body, tc)
        elif isinstance(st, TypeDecl):
            for m in (st.members or []):
                if isinstance(m.node, FnDecl) and m.node.body is not None:
                    _desugar_suite(m.node.body, tc)
    suite.stmts = new


def elaborate(program, tc=None):
    if hasattr(program, "stmts"):
        _wrap(program, tc)
    return program


def _wrap(program, tc=None):
    # Treat program as a suite-like container
    s = Suite(program.stmts)
    _desugar_suite(s, tc)
    program.stmts = s.stmts
    return program


def main():
    src = open(sys.argv[1]).read()
    prog = parse(src)
    elaborate(prog)
    # dump simple
    for st in prog.stmts or []:
        print(type(st).__name__)


if __name__ == "__main__":
    main()