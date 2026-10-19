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


def _desugar_suite(suite):
    if not hasattr(suite, "stmts"):
        return
    new = []
    for st in suite.stmts:
        if isinstance(st, ForStmt):
            new.extend(desugar_for_stmt(st))
        elif isinstance(st, IfStmt):
            if st.then is not None:
                _desugar_suite(st.then)
            for ec, es in (st.elifs or []):
                _desugar_suite(es)
            if st.else_ is not None:
                _desugar_suite(st.else_)
            new.append(st)
        elif isinstance(st, WhileStmt):
            if st.body is not None:
                _desugar_suite(st.body)
            new.append(st)
        elif isinstance(st, (LetStmt, VarStmt, FnDecl)):
            if isinstance(st, FnDecl) and st.body is not None:
                _desugar_suite(st.body)
            new.append(st)
        elif isinstance(st, TypeDecl):
            for m in (st.members or []):
                if isinstance(m.node, FnDecl) and m.node.body is not None:
                    _desugar_suite(m.node.body)
            new.append(st)
        else:
            new.append(st)
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