"""Recogida de literales de cadena y bytes del AST.

Recorre el programa completo antes del codegen para internar cada literal en
la seccion de datos y construir el mapa `id(nodo) -> offset` que consume
`_gen_lit`.
"""
from tools.nodes import (
    Arg, Assign, AwaitStmt, BinOp, BorrowExpr, BytesLit, ExprStmt, FStrLit,
    FnDecl, ForStmt, IfExpr, IfStmt, LetDecl, LetStmt, ListExpr, MapExpr,
    MatchExpr, MatchStmt, MlStrLit, NameExpr, Postfix, ReturnStmt, RStrLit,
    SetExpr, SpawnStmt, StrLit, Suite, TupleExpr, TypeDecl, UnaryOp, VarDecl,
    VarStmt, WhileStmt,
)


def collect_str_literals(program, add_data, start_offset=0,
                         offsets=None, value_offsets=None):
    """Interna los literales de `program` llamando a `add_data(offset, bytes)`.

    Devuelve `(offsets, value_offsets, next_offset)`, donde `offsets` mapea
    `id(nodo)` a offset y `value_offsets` deduplica por valor.
    """
    offsets = {} if offsets is None else offsets
    value_offsets = {} if value_offsets is None else value_offsets
    offset = start_offset
    def walk_str(e):
        nonlocal offset
        if isinstance(e, (StrLit, RStrLit, MlStrLit, BytesLit)):
            if e.value in value_offsets:
                offsets[id(e)] = value_offsets[e.value]
            elif id(e) not in offsets:
                raw = (e.value.encode("latin-1") if isinstance(e, BytesLit)
                       else e.value.encode("utf-8"))
                b = raw + b"\x00"
                offsets[id(e)] = offset
                value_offsets[e.value] = offset
                add_data(offset, b)
                offset += len(b)
            else:
                value_offsets[e.value] = offsets[id(e)]
        elif isinstance(e, FStrLit):
            if e.value in value_offsets:
                offsets[id(e)] = value_offsets[e.value]
            elif id(e) not in offsets:
                b = e.value.encode("utf-8") + b"\x00"
                offsets[id(e)] = offset
                value_offsets[e.value] = offset
                add_data(offset, b)
                offset += len(b)
            else:
                value_offsets[e.value] = offsets[id(e)]
        elif isinstance(e, (BinOp, UnaryOp)):
            if isinstance(e, BinOp):
                walk_str(e.left)
                if not isinstance(e.right, str):
                    walk_str(e.right)
            else:
                walk_str(e.operand)
        elif isinstance(e, BorrowExpr):
            walk_str(e.operand)
        elif isinstance(e, Postfix):
            walk_str(e.base)
            for op in (e.ops or []):
                if op[0] == "call":
                    for a in (op[1] or []):
                        val = a.value if isinstance(a, Arg) else a
                        walk_str(val)
                elif op[0] in ("index", "slice"):
                    if op[1] is not None and not isinstance(op[1], str):
                        walk_str(op[1])
                    if len(op) > 2 and op[2] is not None:
                        walk_str(op[2])
        elif isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
            for a in (getattr(e, "items", None) or []):
                val = a.value if isinstance(a, Arg) else a
                walk_str(val)
                if isinstance(e, MapExpr) and isinstance(a, Arg) and a.is_named and isinstance(a.label, StrLit):
                    key = a.label.value
                    if key not in value_offsets:
                        b = key.encode("utf-8") + b"\x00"
                        value_offsets[key] = offset
                        offsets[id(a.label)] = offset
                        add_data(offset, b)
                        offset += len(b)
                    else:
                        offsets[id(a.label)] = value_offsets[key]
                elif isinstance(e, MapExpr) and isinstance(a, Arg) and a.is_named and isinstance(a.label, NameExpr):
                    key = a.label.name
                    if key not in value_offsets:
                        b = key.encode("utf-8") + b"\x00"
                        value_offsets[key] = offset
                        add_data(offset, b)
                        offset += len(b)
        elif isinstance(e, IfExpr):
            walk_str(e.cond); walk_str(e.then); walk_str(e.else_)
        elif isinstance(e, MatchExpr):
            walk_str(e.expr)
            for arm in (e.arms or []):
                if arm.guard is not None:
                    walk_str(arm.guard)
                if isinstance(arm.body, Suite):
                    for st in (arm.body.stmts if hasattr(arm.body, "stmts") else []):
                        walk_str_stmt(st)
                elif arm.body is not None:
                    walk_str(arm.body)
        elif isinstance(e, (LetStmt, VarStmt)):
            walk_str(e.value)
        elif isinstance(e, (SpawnStmt, AwaitStmt)):
            walk_str(e.expr)
        elif isinstance(e, ExprStmt):
            walk_str(e.expr)
        elif isinstance(e, IfStmt):
            walk_str(e.cond)
            for st in (e.then.stmts if hasattr(e.then,"stmts") else []):
                walk_str_stmt(st)
            if e.else_:
                for st in (e.else_.stmts if hasattr(e.else_,"stmts") else []):
                    walk_str_stmt(st)
        elif isinstance(e, WhileStmt):
            walk_str(e.cond)
            for st in (e.body.stmts if hasattr(e.body,"stmts") else []):
                walk_str_stmt(st)
        elif isinstance(e, ForStmt):
            if not isinstance(e.iter, str):
                walk_str(e.iter)
            for st in (e.body.stmts if hasattr(e.body,"stmts") else []):
                walk_str_stmt(st)
        elif isinstance(e, ReturnStmt) and e.value is not None:
            walk_str(e.value)
        elif isinstance(e, Assign):
            walk_str(e.value)
    def walk_str_stmt(st):
        if isinstance(st, (LetStmt, VarStmt)):
            walk_str(st.value)
        elif isinstance(st, (SpawnStmt, AwaitStmt)):
            walk_str(st.expr)
        elif isinstance(st, ExprStmt):
            walk_str(st.expr)
        elif isinstance(st, Assign):
            walk_str(st.value)
        elif isinstance(st, ForStmt):
            if not isinstance(st.iter, str): walk_str(st.iter)
            for s in (st.body.stmts if hasattr(st.body,"stmts") else []): walk_str_stmt(s)
        elif isinstance(st, ReturnStmt) and st.value is not None:
            walk_str(st.value)
        elif isinstance(st, IfStmt):
            walk_str(st.cond)
            for s in (st.then.stmts if hasattr(st.then,"stmts") else []): walk_str_stmt(s)
            for ec, es in (st.elifs or []):
                walk_str(ec)
                for s in (es.stmts if hasattr(es,"stmts") else []): walk_str_stmt(s)
            if st.else_ is not None:
                for s in (st.else_.stmts if hasattr(st.else_,"stmts") else []): walk_str_stmt(s)
        elif isinstance(st, WhileStmt):
            walk_str(st.cond)
            for s in (st.body.stmts if hasattr(st.body,"stmts") else []): walk_str_stmt(s)
        elif isinstance(st, MatchStmt):
            walk_str(st.expr)
            for arm in (st.arms or []):
                if isinstance(arm.body, Suite):
                    for s in arm.body.stmts: walk_str_stmt(s)
                elif arm.body is not None:
                    walk_str(arm.body)
                if arm.guard is not None:
                    walk_str(arm.guard)
    for stmt in (program.stmts or []):
        if isinstance(stmt, (LetDecl, VarDecl)):
            walk_str(stmt.value)
        elif isinstance(stmt, FnDecl):
            if stmt.body:
                for st in stmt.body.stmts:
                    walk_str_stmt(st)
        elif isinstance(stmt, (LetStmt, VarStmt, ExprStmt, Assign, IfStmt, WhileStmt, ForStmt, ReturnStmt)):
            walk_str_stmt(stmt)
        elif isinstance(stmt, TypeDecl):
            for m in stmt.members:
                if isinstance(m.node, FnDecl) and m.node.body:
                    for st in m.node.body.stmts:
                        walk_str_stmt(st)
    return offsets, value_offsets, offset
