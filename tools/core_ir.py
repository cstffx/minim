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


def desugar_for_stmt(st):
    """Devuelve una lista de statements core equivalentes a un ForStmt."""
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
            varname = "_i"
        # let var = left
        out = [LetStmt([Binding("name", varname)], it.left)]
        # while var < right (or <=)
        cond = BinOp("<=" if inclusive else "<", NameExpr(varname), it.right)
        loop_body = list(body_stmts) + [Assign(Place(varname, []), "+=", IntLit("1"))]
        out.append(WhileStmt(cond, Suite(loop_body)))
        return out
    # Lista/iterable: for x in e
    varname = None
    for b in (st.bindings or []):
        vn = _binding_name(b)
        if vn:
            varname = vn
            break
    if varname is None:
        varname = "_x"
    out = []
    # Iterate by borrow, not by move: `for x in v` must not consume `v`.
    out.append(LetStmt([Binding("name", "_it")], BorrowExpr(it)))
    out.append(LetStmt([Binding("name", "_i")], IntLit("0")))
    cond = BinOp("<", NameExpr("_i"), Postfix(NameExpr("_it"), [("field", "len")]))
    loop_body = []
    # Bind by borrow, not by value: extracting a non-copyable element by
    # index (`_it[_i]`) would otherwise count as a partial move of `_it`.
    loop_body.append(LetStmt([Binding("name", varname)],
                    BorrowExpr(Postfix(NameExpr("_it"), [("index", NameExpr("_i"))]))))
    loop_body.extend(body_stmts)
    # Touch `_it` after the user body so the borrow's last-use covers the
    # whole loop body, not just its last textual mention of `_it` -- the
    # loan must stay live for every statement in the loop, including ones
    # that don't reference `_it` directly (e.g. mutating the owner, which
    # must be rejected while the iteration borrow is alive).
    loop_body.append(ExprStmt(NameExpr("_it")))
    loop_body.append(Assign(Place("_i", []), "+=", IntLit("1")))
    out.append(WhileStmt(cond, Suite(loop_body)))
    return out


_CMP_OPS = {"<", "<=", ">", ">=", "==", "!="}

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
                    args.append(Arg(a.label, _desugar_expr(val), a.is_named, a.span) if isinstance(a, Arg) else _desugar_expr(val))
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
    if isinstance(e, (TupleExpr, ListExpr, MapExpr)):
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
        return MapExpr(items, e.span)
    return e

def _desugar_stmt_exprs(st):
    if isinstance(st, (LetStmt, VarStmt)):
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
            _desugar_suite(st.then)
        for ec, es in (st.elifs or []):
            ec_new = _desugar_expr(ec)
            # store back
            # elifs is list of (cond, suite)
            pass
        if st.else_ is not None:
            _desugar_suite(st.else_)
    elif isinstance(st, WhileStmt):
        st.cond = _desugar_expr(st.cond)
        if st.body is not None:
            _desugar_suite(st.body)
    elif isinstance(st, MatchStmt):
        st.expr = _desugar_expr(st.expr)
        for arm in (st.arms or []):
            if arm.guard is not None:
                arm.guard = _desugar_expr(arm.guard)
            if isinstance(arm.body, Suite):
                _desugar_suite(arm.body)
            elif arm.body is not None:
                arm.body = _desugar_expr(arm.body)
    elif isinstance(st, ForStmt):
        if not isinstance(st.iter, str):
            st.iter = _desugar_expr(st.iter)
        if st.body is not None:
            _desugar_suite(st.body)
    elif isinstance(st, (FnDecl,)):
        if st.body is not None:
            _desugar_suite(st.body)
    elif isinstance(st, TypeDecl):
        for m in (st.members or []):
            if isinstance(m.node, FnDecl) and m.node.body is not None:
                _desugar_suite(m.node.body)
    # handle elifs properly
    if isinstance(st, IfStmt):
        new_elifs = []
        for ec, es in (st.elifs or []):
            new_elifs.append((_desugar_expr(ec), es))
            _desugar_suite(es)
        st.elifs = new_elifs

def _desugar_suite(suite):
    if not hasattr(suite, "stmts"):
        return
    new = []
    for st in suite.stmts:
        if isinstance(st, ForStmt):
            ds = desugar_for_stmt(st)
            for nst in ds:
                _desugar_stmt_exprs(nst)
            new.extend(ds)
        else:
            _desugar_stmt_exprs(st)
            new.append(st)
            if isinstance(st, (IfStmt, WhileStmt, FnDecl, TypeDecl)):
                pass
    # recurse into nested suites
    for st in new:
        if isinstance(st, IfStmt):
            if st.then is not None: _desugar_suite(st.then)
            for ec, es in (st.elifs or []):
                _desugar_suite(es)
            if st.else_ is not None: _desugar_suite(st.else_)
        elif isinstance(st, WhileStmt):
            if st.body is not None: _desugar_suite(st.body)
        elif isinstance(st, FnDecl):
            if st.body is not None: _desugar_suite(st.body)
        elif isinstance(st, TypeDecl):
            for m in (st.members or []):
                if isinstance(m.node, FnDecl) and m.node.body is not None:
                    _desugar_suite(m.node.body)
    suite.stmts = new


def elaborate(program):
    if hasattr(program, "stmts"):
        _desugar_suite(Suite(program.stmts) if False else _wrap(program))
    return program


def _wrap(program):
    # Treat program as a suite-like container
    s = Suite(program.stmts)
    _desugar_suite(s)
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