"""Borrow checker for Minim (phase 2c).

Intra-procedural ownership / borrow checking.  Returns a list of BorrowError.
Follows docs/OWNERSHIP.md (v0.1): owner-level exclusivity, regions by last use,
no partial moves, no escaping closures, etc.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.nodes import *
from tools.parser import parse
from tools.core_ir import elaborate
from tools.resolve import Resolver
from tools.typecheck import TC, INT, FLOAT, BOOL, STR, NIL, UNKNOWN, ERRT, BYTES, N, L, M, O, R, F, compat, apply


class BorrowError(Exception):
    def __init__(self, msg, node=None):
        span = getattr(node, "span", None)
        loc = f"{span.line}:{span.col}" if span else "?"
        super().__init__(f"{loc}: {msg}")
        self.node = node


# ---------- helpers ----------

def _type_kind(ty):
    if not isinstance(ty, tuple):
        return None
    if ty[0] == "list":
        return "list"
    if ty[0] == "map":
        return "map"
    if ty[0] == "set":
        return "set"
    if ty[0] == "p" and ty[1] == "str":
        return "str"
    if ty[0] == "named":
        return ty[1]
    return None


def _contains_borrow(t):
    if isinstance(t, TypeBorrow):
        return True
    if isinstance(t, TypeSuffix):
        return _contains_borrow(t.base)
    if isinstance(t, TypeName):
        return any(_contains_borrow(a) for a in (t.args or []))
    if isinstance(t, TypeList):
        return _contains_borrow(t.inner)
    if isinstance(t, TypeMap):
        return _contains_borrow(t.key) or _contains_borrow(t.val)
    if isinstance(t, TypeSet):
        return _contains_borrow(t.inner)
    if isinstance(t, TypeTuple):
        return any(_contains_borrow(x) for x in t.items)
    if isinstance(t, TypeFunc):
        return any(_contains_borrow(x) for x in t.params) or (t.ret is not None and _contains_borrow(t.ret))
    if isinstance(t, TypeParen):
        return t.inner is not None and _contains_borrow(t.inner)
    if isinstance(t, Type):
        return _contains_borrow(t.node)
    return False


def _copyable(ty, tc):
    if ty is None:
        return True
    if not isinstance(ty, tuple):
        return True
    if ty[0] == "p":
        return ty[1] in ("int", "float", "bool", "str", "bytes", "nil")
    if ty[0] == "named":
        td = tc.type_defs.get(ty[1])
        if td is None:
            return False
        fields = [m.node for m in td.members if m.kind == "field"]
        return all(_copyable(tc._atype(f.type_) if f.type_ is not None else UNKNOWN, tc) for f in fields)
    if ty[0] == "tuple":
        return all(_copyable(t, tc) for t in ty[1])
    return False


def _add_error(env, msg, node):
    env["errors"].append(BorrowError(msg, node))


# ---------- places ----------

def _flatten_postfix(e):
    ops = []
    cur = e
    while isinstance(cur, Postfix):
        ops = (cur.ops or []) + ops
        cur = cur.base
    return cur, ops


def _place_of(expr, env):
    if isinstance(expr, NameExpr):
        return ("place", expr.name, ())
    if isinstance(expr, SelfExpr):
        return ("place", "self", ())
    if isinstance(expr, ItExpr):
        return ("place", "it", ())
    if isinstance(expr, Postfix):
        base = _place_of(expr.base, env)
        if base is None:
            return None
        parts = list(base[2])
        for op in (expr.ops or []):
            if op[0] == "field":
                parts.append(("field", op[1]))
            elif op[0] == "index":
                parts.append(("index", op[1]))
            else:
                return None
        return ("place", base[1], tuple(parts))
    return None


def _place_from_ast(pl, env=None):
    parts = []
    for part in (pl.parts or []):
        if part[0] == "field":
            parts.append(("field", part[1]))
        elif part[0] == "index":
            parts.append(("index", part[1]))
    return ("place", pl.name, tuple(parts))


def _place_of_postfix_prefix(base, ops_prefix, env):
    p = _place_of(base, env)
    if p is None:
        return None
    parts = list(p[2])
    for op in ops_prefix:
        if op[0] == "field":
            parts.append(("field", op[1]))
        elif op[0] == "index":
            parts.append(("index", op[1]))
        else:
            return None
    return ("place", p[1], tuple(parts))


def _const_int(expr):
    if isinstance(expr, IntLit):
        try:
            return int(expr.value)
        except (ValueError, TypeError):
            return None
    return None


def _same_path_part(a, b):
    if a == b:
        return True
    if a is None or b is None:
        return False
    if a[0] != b[0]:
        return False
    if a[0] == "field":
        return a[1] == b[1]
    if a[0] == "index":
        ca = _const_int(a[1])
        cb = _const_int(b[1])
        if ca is not None and cb is not None:
            return ca == cb
        return False
    return False


def _overlap(p1, p2):
    # exclusivity by place (path), per SOUNDNESS.md §10:
    # two places overlap if one is a prefix of the other, or they diverge
    # conservatively. Constant distinct indices are disjoint.
    if p1 is None or p2 is None:
        return False
    if p1[1] != p2[1]:
        return False
    q1 = p1[2] or ()
    q2 = p2[2] or ()
    n = min(len(q1), len(q2))
    for i in range(n):
        if _same_path_part(q1[i], q2[i]):
            continue
        # diverged at this part
        if (q1[i][0] == "index" and q2[i][0] == "index"):
            ca = _const_int(q1[i][1])
            cb = _const_int(q2[i][1])
            if ca is not None and cb is not None and ca != cb:
                return False
        if (q1[i][0] == "field" and q2[i][0] == "field" and q1[i][1] != q2[i][1]):
            return False
        # otherwise conservative: treat as overlapping
        return True
    # one is prefix of the other (or identical)
    return True


def _is_simple_place(pl):
    if pl is None:
        return False
    for part in pl[2]:
        if part[0] == "index":
            return False
    return True


# ---------- type helpers ----------

def _type_of_place(pl, env):
    try:
        from tools.nodes import Place as P
        ast = P(pl[1], [])
        ast.parts = [ (pp[0], pp[1]) for pp in pl[2] ]
        return env["tc"].place(ast, env["scope"])
    except Exception:
        return None


def _expr_type(e, env):
    try:
        return env["tc"].expr(e, env["scope"])
    except Exception:
        return None


# ---------- access checks ----------

def _check_read_access(env, pl, node):
    if pl[1] in env["moved"]:
        _add_error(env, f"no se puede usar '{pl[1]}' despues de moverla", node)
        return
    for L in env["loans"]:
        if not _overlap(pl, L["origin"]):
            continue
        if L["mode"] == "unique" and not L.get("allow_write", False):
            _add_error(env, f"conflicto de prestamo: '{pl[1]}' tiene un prestamo unico activo", node)
            break


def _check_write_access(env, pl, node):
    for L in env["loans"]:
        if not _overlap(pl, L["origin"]):
            continue
        if L.get("allow_write", False) and L["mode"] == "unique":
            continue
        _add_error(env, f"no se puede escribir '{pl[1]}' con un prestamo activo", node)
        break


def _loan_conflicts(new_loan, loans):
    for L in loans:
        if not _overlap(new_loan["origin"], L["origin"]):
            continue
        # a unique param borrow allows nested temporary unique borrows on the same root
        if L.get("allow_write", False) and L["mode"] == "unique" and not new_loan.get("stored", False):
            continue
        if new_loan["mode"] == "unique" or L["mode"] == "unique":
            return True
    return False


def _check_move_place(env, pl, node):
    if len(pl[2]) > 0:
        _add_error(env, "no hay movimientos parciales en v0.1", node)
        return
    root = pl[1]
    if root in env["moved"]:
        _add_error(env, f"no se puede usar '{root}' despues de moverla", node)
        return
    for L in env["loans"]:
        if _overlap(pl, L["origin"]):
            _add_error(env, f"no se puede mover '{root}' con un prestamo vivo", node)
            break


def _mark_moved(env, pl):
    if len(pl[2]) == 0:
        env["moved"].add(pl[1])


# ---------- index / last-use collection ----------

def _assign_indices_suite(suite, counter):
    for stmt in (suite.stmts if hasattr(suite, "stmts") else []):
        stmt._idx = counter[0]
        counter[0] += 1
        _assign_indices_stmt(stmt, counter)


def _assign_indices_stmt(stmt, counter):
    if isinstance(stmt, IfStmt):
        _assign_indices_suite(stmt.then, counter)
        for ec, es in (stmt.elifs or []):
            _assign_indices_suite(es, counter)
        if stmt.else_ is not None:
            _assign_indices_suite(stmt.else_, counter)
    elif isinstance(stmt, WhileStmt):
        _assign_indices_suite(stmt.body, counter)
    elif isinstance(stmt, ForStmt):
        _assign_indices_suite(stmt.body, counter)
    elif isinstance(stmt, MatchStmt):
        for arm in (stmt.arms or []):
            if isinstance(arm.body, Suite):
                _assign_indices_suite(arm.body, counter)


def _collect_uses_suite(suite, last_use):
    for stmt in (suite.stmts if hasattr(suite, "stmts") else []):
        _collect_uses_stmt(stmt, last_use)


def _collect_uses_stmt(stmt, last_use):
    idx = getattr(stmt, "_idx", 0)
    if isinstance(stmt, (LetStmt, VarStmt)):
        _collect_uses_expr(stmt.value, idx, last_use)
    elif isinstance(stmt, (LetDecl, VarDecl)):
        _collect_uses_expr(stmt.value, idx, last_use)
    elif isinstance(stmt, Assign):
        _collect_uses_place_ast(stmt.place, idx, last_use)
        _collect_uses_expr(stmt.value, idx, last_use)
    elif isinstance(stmt, ExprStmt):
        _collect_uses_expr(stmt.expr, idx, last_use)
    elif isinstance(stmt, IfStmt):
        _collect_uses_expr(stmt.cond, idx, last_use)
        _collect_uses_suite(stmt.then, last_use)
        for ec, es in (stmt.elifs or []):
            _collect_uses_expr(ec, idx, last_use)
            _collect_uses_suite(es, last_use)
        if stmt.else_ is not None:
            _collect_uses_suite(stmt.else_, last_use)
    elif isinstance(stmt, WhileStmt):
        _collect_uses_expr(stmt.cond, idx, last_use)
        _collect_uses_suite(stmt.body, last_use)
    elif isinstance(stmt, ForStmt):
        _collect_uses_expr(stmt.iter, idx, last_use)
        _collect_uses_suite(stmt.body, last_use)
    elif isinstance(stmt, MatchStmt):
        _collect_uses_expr(stmt.expr, idx, last_use)
        for arm in (stmt.arms or []):
            if isinstance(arm.body, Suite):
                _collect_uses_suite(arm.body, last_use)
            elif arm.body is not None:
                _collect_uses_expr(arm.body, idx, last_use)
    elif isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_uses_expr(stmt.value, idx, last_use)
    elif isinstance(stmt, SpawnStmt):
        _collect_uses_expr(stmt.expr, idx, last_use)
    elif isinstance(stmt, AwaitStmt):
        _collect_uses_expr(stmt.expr, idx, last_use)


def _collect_uses_place_ast(pl, idx, last_use):
    last_use[pl.name] = max(last_use.get(pl.name, -1), idx)
    for part in (pl.parts or []):
        if part[0] == "index" and not isinstance(part[1], str):
            _collect_uses_expr(part[1], idx, last_use)


def _collect_uses_expr(e, idx, last_use):
    if isinstance(e, NameExpr):
        last_use[e.name] = max(last_use.get(e.name, -1), idx)
    elif isinstance(e, SelfExpr):
        last_use["self"] = max(last_use.get("self", -1), idx)
    elif isinstance(e, ItExpr):
        last_use["it"] = max(last_use.get("it", -1), idx)
    elif isinstance(e, BorrowExpr):
        _collect_uses_expr(e.operand, idx, last_use)
    elif isinstance(e, UnaryOp):
        if e.operand is not None and not isinstance(e.operand, str):
            _collect_uses_expr(e.operand, idx, last_use)
    elif isinstance(e, BinOp):
        if e.left is not None and not isinstance(e.left, str):
            _collect_uses_expr(e.left, idx, last_use)
        if isinstance(e.right, OrBlock):
            _collect_uses_suite(e.right.body, last_use)
        elif e.right is not None and not isinstance(e.right, str):
            _collect_uses_expr(e.right, idx, last_use)
    elif isinstance(e, Postfix):
        _collect_uses_expr(e.base, idx, last_use)
        for op in (e.ops or []):
            if op[0] in ("index", "slice"):
                if op[1] is not None and not isinstance(op[1], str):
                    _collect_uses_expr(op[1], idx, last_use)
                if len(op) > 2 and op[2] is not None:
                    _collect_uses_expr(op[2], idx, last_use)
            elif op[0] == "call":
                for a in (op[1] or []):
                    val = a.value if isinstance(a, Arg) else a
                    _collect_uses_expr(val, idx, last_use)
    elif isinstance(e, TupleExpr):
        for x in (e.items or []):
            _collect_uses_expr(x, idx, last_use)
    elif isinstance(e, ListExpr):
        for a in (e.items or []):
            val = a.value if isinstance(a, Arg) else a
            _collect_uses_expr(val, idx, last_use)
    elif isinstance(e, MapExpr):
        for a in (e.items or []):
            val = a.value if isinstance(a, Arg) else a
            _collect_uses_expr(val, idx, last_use)
    elif isinstance(e, Lambda):
        _collect_uses_expr(e.body, idx, last_use)
    elif isinstance(e, MoveExpr) and isinstance(e.lambda_, Lambda):
        _collect_uses_expr(e.lambda_.body, idx, last_use)
    elif isinstance(e, IfExpr):
        _collect_uses_expr(e.cond, idx, last_use)
        _collect_uses_expr(e.then, idx, last_use)
        _collect_uses_expr(e.else_, idx, last_use)
    elif isinstance(e, MatchExpr):
        _collect_uses_expr(e.expr, idx, last_use)
        for arm in (e.arms or []):
            if isinstance(arm.body, Suite):
                _collect_uses_suite(arm.body, last_use)
            elif arm.body is not None:
                _collect_uses_expr(arm.body, idx, last_use)


# ---------- statement checking ----------

def _check_suite(suite, env):
    for stmt in (suite.stmts if hasattr(suite, "stmts") else []):
        _check_stmt(stmt, env)


def _check_stmt(stmt, env):
    idx = getattr(stmt, "_idx", 0)
    # filter loans by last use
    env["loans"] = [L for L in env["loans"] if L["issue"] <= idx <= L.get("last_use", idx)]

    if isinstance(stmt, (LetDecl, VarDecl)):
        # module-level declarations
        _check_expr(stmt.value, env, idx)
        pl = _place_of(stmt.value, env)
        ty = _expr_type(stmt.value, env)
        if isinstance(stmt, LetDecl):
            names = [stmt.name]
        else:
            names = [b.name for b in stmt.bindings if b.kind == "name" and b.name]
        if pl is not None and not isinstance(stmt.value, BorrowExpr) and not _copyable(ty, env["tc"]):
            _check_move_place(env, pl, stmt.value)
            if len(pl[2]) == 0:
                _mark_moved(env, pl)
        for nm in names:
            if isinstance(stmt, LetDecl):
                bt = env["tc"]._atype(stmt.type_) if stmt.type_ is not None else (ty if ty is not None else UNKNOWN)
            else:
                # VarDecl bindings
                bt = ty
            env["types"][nm] = bt
        # stored borrow handling
        if isinstance(stmt.value, BorrowExpr):
            loan = _find_loan(env, id(stmt.value))
            if loan is not None:
                name = stmt.name if isinstance(stmt, LetDecl) else (names[0] if names else None)
                if name is not None:
                    loan["stored"] = True
                    loan["handle"] = name
                    loan["last_use"] = max(loan["issue"], env.get("last_use", {}).get(name, loan["issue"]))
        return

    if isinstance(stmt, (LetStmt, VarStmt)):
        _check_expr(stmt.value, env, idx)
        pl = _place_of(stmt.value, env)
        ty = _expr_type(stmt.value, env)
        names = []
        for b in stmt.bindings:
            if b.kind == "name" and b.name:
                names.append(b.name)
        if pl is not None and not isinstance(stmt.value, BorrowExpr) and not _copyable(ty, env["tc"]):
            _check_move_place(env, pl, stmt.value)
            if len(pl[2]) == 0:
                _mark_moved(env, pl)
        for b in stmt.bindings:
            if b.kind == "name" and b.name:
                if b.type_ is not None:
                    bt = env["tc"]._atype(b.type_)
                else:
                    bt = ty if ty is not None else UNKNOWN
                env["types"][b.name] = bt
        if isinstance(stmt.value, BorrowExpr):
            loan = _find_loan(env, id(stmt.value))
            if loan is not None:
                name = names[0] if names else None
                if name is not None:
                    loan["stored"] = True
                    loan["handle"] = name
                    loan["last_use"] = max(loan["issue"], env.get("last_use", {}).get(name, loan["issue"]))
        return

    if isinstance(stmt, Assign):
        pl = _place_from_ast(stmt.place, env)
        _check_write_access(env, pl, stmt)
        # index exprs
        for part in (stmt.place.parts or []):
            if part[0] == "index" and not isinstance(part[1], str):
                _check_expr(part[1], env, idx)
        _check_expr(stmt.value, env, idx)
        plv = _place_of(stmt.value, env)
        ty = _expr_type(stmt.value, env)
        if plv is not None and not isinstance(stmt.value, BorrowExpr) and not _copyable(ty, env["tc"]):
            _check_move_place(env, plv, stmt.value)
            if len(plv[2]) == 0:
                _mark_moved(env, plv)
        return

    if isinstance(stmt, ExprStmt):
        _check_expr(stmt.expr, env, idx)
        return

    if isinstance(stmt, IfStmt):
        _check_expr(stmt.cond, env, idx)
        old_scope = env["scope"]
        env["scope"] = env["scope"].child("block")
        _check_suite(stmt.then, env)
        env["scope"] = old_scope
        for ec, es in (stmt.elifs or []):
            _check_expr(ec, env, idx)
            old_scope = env["scope"]
            env["scope"] = env["scope"].child("block")
            _check_suite(es, env)
            env["scope"] = old_scope
        if stmt.else_ is not None:
            old_scope = env["scope"]
            env["scope"] = env["scope"].child("block")
            _check_suite(stmt.else_, env)
            env["scope"] = old_scope
        return

    if isinstance(stmt, WhileStmt):
        _check_expr(stmt.cond, env, idx)
        old_scope = env["scope"]
        env["scope"] = env["scope"].child("block")
        _check_suite(stmt.body, env)
        env["scope"] = old_scope
        return

    if isinstance(stmt, ForStmt):
        _check_expr(stmt.iter, env, idx)
        old_scope = env["scope"]
        env["scope"] = env["scope"].child("block")
        for b in (stmt.bindings or []):
            if b.kind == "name" and b.name:
                env["types"][b.name] = UNKNOWN
        _check_suite(stmt.body, env)
        env["scope"] = old_scope
        return

    if isinstance(stmt, MatchStmt):
        _check_expr(stmt.expr, env, idx)
        for arm in (stmt.arms or []):
            if arm.is_else:
                old_scope = env["scope"]
                env["scope"] = env["scope"].child("block")
                if isinstance(arm.body, Suite):
                    _check_suite(arm.body, env)
                elif arm.body is not None:
                    _check_expr(arm.body, env, idx)
                env["scope"] = old_scope
                continue
            old_scope = env["scope"]
            env["scope"] = env["scope"].child("block")
            if isinstance(arm.body, Suite):
                _check_suite(arm.body, env)
            elif arm.body is not None:
                _check_expr(arm.body, env, idx)
            env["scope"] = old_scope
        return

    if isinstance(stmt, ReturnStmt):
        if isinstance(stmt.value, (Lambda, MoveExpr)):
            _add_error(env, "la closure escapa", stmt)
        if stmt.value is not None:
            ty = _expr_type(stmt.value, env)
            if isinstance(ty, tuple) and ty[0] == "borrow":
                params = getattr(env["func"], "params", []) or []
                origin_root = None
                pl = _place_of(stmt.value, env)
                if pl is not None:
                    origin_root = pl[1]
                allowed = False
                if origin_root == "self":
                    allowed = True
                elif len(params) == 1 and params[0].name == origin_root:
                    allowed = True
                if not allowed:
                    _add_error(env, "no se puede devolver un prestamo de un local", stmt)
            _check_expr(stmt.value, env, idx)
        return

    if isinstance(stmt, SpawnStmt):
        if env["loans"]:
            _add_error(env, "spawn exige aislamiento: prestamos vivos", stmt)
        _check_expr(stmt.expr, env, idx)
        # rc/arc args
        args = _extract_call_args(stmt.expr)
        for a in args:
            val = a.value if isinstance(a, Arg) else a
            if isinstance(val, NameExpr):
                ty = env["types"].get(val.name)
                if isinstance(ty, tuple) and ty[0] == "named" and ty[1] in ("rc", "arc"):
                    _add_error(env, "rc/arc no esta aislado para spawn", stmt)
        return

    if isinstance(stmt, AwaitStmt):
        _check_expr(stmt.expr, env, idx)
        if env["loans"]:
            _add_error(env, "prestamo vivo que cruza un await", stmt)
        return

    if isinstance(stmt, (BreakStmt, ContinueStmt)):
        return

    # nested decls handled elsewhere; ignore
    return


def _find_loan(env, node_id):
    for L in env["loans"]:
        if L["id"] == node_id:
            return L
    # search by id() of BorrowExpr object
    for L in env["loans"]:
        if L.get("_node_id") == node_id:
            return L
    return None


# ---------- expression checking ----------

def _check_expr(e, env, idx):
    if e is None:
        return
    if isinstance(e, (IntLit, FloatLit, StrLit, FStrLit, RStrLit, BytesLit, MlStrLit, BoolLit, NilLit)):
        return
    if isinstance(e, NameExpr):
        if e.name in env["moved"]:
            _add_error(env, f"no se puede usar '{e.name}' despues de moverla", e)
        pl = ("place", e.name, ())
        _check_read_access(env, pl, e)
        return
    if isinstance(e, SelfExpr):
        pl = ("place", "self", ())
        _check_read_access(env, pl, e)
        return
    if isinstance(e, ItExpr):
        pl = ("place", "it", ())
        _check_read_access(env, pl, e)
        return
    if isinstance(e, BorrowExpr):
        pl = _place_of(e.operand, env)
        if pl is None:
            _check_expr(e.operand, env, idx)
            return
        loan = {"id": id(e), "origin": pl, "mode": "shared", "handle": None,
                "issue": idx, "stored": False, "last_use": idx, "allow_write": False}
        if _loan_conflicts(loan, env["loans"]):
            _add_error(env, "prestamo compartido en conflicto", e)
        env["loans"].append(loan)
        _check_read_access(env, pl, e)
        return
    if isinstance(e, UnaryOp):
        if e.op == "spawn":
            if env["loans"]:
                _add_error(env, "spawn exige aislamiento: prestamos vivos", e)
            args = _extract_call_args(e.operand)
            for a in args:
                val = a.value if isinstance(a, Arg) else a
                if isinstance(val, NameExpr):
                    ty = env["types"].get(val.name)
                    if isinstance(ty, tuple) and ty[0] == "named" and ty[1] in ("rc", "arc"):
                        _add_error(env, "rc/arc no esta aislado para spawn", e)
            _check_expr(e.operand, env, idx)
            return
        if e.op == "await":
            if env["loans"]:
                _add_error(env, "prestamo vivo que cruza un await", e)
            _check_expr(e.operand, env, idx)
            return
        if e.op == "?":
            _check_expr(e.operand, env, idx)
            return
        _check_expr(e.operand, env, idx)
        return
    if isinstance(e, BinOp):
        if e.op == "or":
            _check_expr(e.left, env, idx)
            if isinstance(e.right, OrBlock):
                old_scope = env["scope"]
                env["scope"] = env["scope"].child("block")
                _check_suite(e.right.body, env)
                env["scope"] = old_scope
                return
            if e.right is not None and not isinstance(e.right, str):
                _check_expr(e.right, env, idx)
            return
        _check_expr(e.left, env, idx)
        if e.right is not None and not isinstance(e.right, str):
            _check_expr(e.right, env, idx)
        return
    if isinstance(e, Postfix):
        base_root, all_ops = _flatten_postfix(e)
        base_place = _place_of(base_root, env)
        if base_place is None and not isinstance(base_root, (NameExpr, SelfExpr, ItExpr)):
            _check_expr(base_root, env, idx)
        ops = all_ops
        # index/slice exprs
        for op in ops:
            if op[0] == "index" and not isinstance(op[1], str):
                _check_expr(op[1], env, idx)
            elif op[0] == "slice":
                if op[1] is not None and not isinstance(op[1], str):
                    _check_expr(op[1], env, idx)
                if len(op) > 2 and op[2] is not None:
                    _check_expr(op[2], env, idx)
        # calls
        has_call = False
        i = 0
        while i < len(ops):
            if ops[i][0] == "call":
                has_call = True
                method_name = None
                if i > 0 and ops[i - 1][0] == "field":
                    method_name = ops[i - 1][1]
                prefix_ops = ops[:i - 1] if method_name is not None else ops[:i]
                recv_place = _place_of_postfix_prefix(base_root, prefix_ops, env)
                args = ops[i][1] or []
                func_name = None
                if method_name is None and isinstance(e.base, NameExpr) and not prefix_ops:
                    func_name = e.base.name
                _handle_call(env, idx, method_name, func_name, recv_place, args, e)
                i += 1
            else:
                i += 1
        if base_place is not None and not has_call:
            _check_read_access(env, base_place, e.base)
        return
    if isinstance(e, TupleExpr):
        for x in (e.items or []):
            _check_expr(x, env, idx)
        return
    if isinstance(e, ListExpr):
        for a in (e.items or []):
            val = a.value if isinstance(a, Arg) else a
            _check_expr(val, env, idx)
        return
    if isinstance(e, MapExpr):
        for a in (e.items or []):
            val = a.value if isinstance(a, Arg) else a
            _check_expr(val, env, idx)
        return
    if isinstance(e, Lambda):
        old_scope = env["scope"]
        env["scope"] = env["scope"].child("block")
        for p in (e.params or []):
            env["types"][p.name] = env["tc"]._atype(p.type_) if p.type_ is not None else UNKNOWN
        _check_expr(e.body, env, idx)
        env["scope"] = old_scope
        return
    if isinstance(e, MoveExpr) and isinstance(e.lambda_, Lambda):
        lam = e.lambda_
        old_scope = env["scope"]
        env["scope"] = env["scope"].child("block")
        for p in (lam.params or []):
            env["types"][p.name] = env["tc"]._atype(p.type_) if p.type_ is not None else UNKNOWN
        _check_expr(lam.body, env, idx)
        env["scope"] = old_scope
        return
    if isinstance(e, IfExpr):
        _check_expr(e.cond, env, idx)
        _check_expr(e.then, env, idx)
        _check_expr(e.else_, env, idx)
        return
    if isinstance(e, MatchExpr):
        _check_expr(e.expr, env, idx)
        for arm in (e.arms or []):
            if isinstance(arm.body, Suite):
                _check_suite(arm.body, env)
            elif arm.body is not None:
                _check_expr(arm.body, env, idx)
        return
    if isinstance(e, OrBlock):
        _check_suite(e.body, env)
        return
    return


# ---------- builtin method modes ----------

_MUTATING_METHODS = {"push", "pop", "sort", "reverse", "insert", "remove", "del",
                     "set", "append", "extend", "clear", "sort"}


def _builtin_self_mode(method_name):
    if method_name in _MUTATING_METHODS:
        return "var"
    return None  # shared


def _find_function_decl(program, name):
    for stmt in program.stmts:
        if isinstance(stmt, FnDecl) and stmt.name == name:
            return stmt
    return None


def _find_method_decl(tc, type_name, method_name):
    td = tc.type_defs.get(type_name)
    if td is None:
        return None
    for m in td.members:
        if isinstance(m.node, FnDecl) and m.node.name == method_name:
            return m.node
    return None


def _extract_call_args(expr):
    if isinstance(expr, Postfix):
        for op in reversed(expr.ops or []):
            if op[0] == "call":
                return op[1] or []
    return []


def _handle_call(env, idx, method_name, func_name, recv_place, args, node):
    tc = env["tc"]
    program = env["program"]
    self_mode = None
    param_modes = []
    returns_borrow = False
    borrow_param_index = None
    decl = None

    if method_name is not None:
        recv_type = _type_of_place(recv_place, env) if recv_place is not None else None
        tk = _type_kind(recv_type)
        if tk in ("rc", "arc"):
            for arg in args:
                expr = arg.value if isinstance(arg, Arg) else arg
                _check_expr(expr, env, idx)
            return
        builtin = tk in ("list", "str", "map", "set", "bytes", "int",
                         "float", "bool", "nil")
        if builtin:
            self_mode = _builtin_self_mode(method_name)
            param_modes = [None] * len(args)
        else:
            decl = _find_method_decl(tc, tk, method_name)
            if decl is not None:
                if decl.params and decl.params[0].name == "self":
                    self_mode = decl.params[0].mode
                    param_modes = [p.mode for p in decl.params[1:]]
                else:
                    param_modes = [p.mode for p in decl.params]
                if isinstance(decl.ret, TypeBorrow):
                    returns_borrow = True
                    if decl.params and decl.params[0].name == "self" and len(decl.params) == 1:
                        borrow_param_index = -1
                    elif len(decl.params) == 1 and not (decl.params[0].name == "self"):
                        borrow_param_index = 0
    else:
        if func_name == "drop":
            for arg in args:
                expr = arg.value if isinstance(arg, Arg) else arg
                pl = _place_of(expr, env)
                if pl is not None:
                    for part in pl[2]:
                        if part[0] == "index" and not isinstance(part[1], str):
                            _check_expr(part[1], env, idx)
                    _check_move_place(env, pl, expr)
                    if len(pl[2]) == 0:
                        _mark_moved(env, pl)
                else:
                    _check_expr(expr, env, idx)
            return
        if func_name == "copy":
            for arg in args:
                expr = arg.value if isinstance(arg, Arg) else arg
                _check_expr(expr, env, idx)
            return
        decl = _find_function_decl(program, func_name) if func_name else None
        if decl is not None:
            param_modes = [p.mode for p in decl.params]
            if isinstance(decl.ret, TypeBorrow):
                returns_borrow = True
                if len(decl.params) == 1:
                    borrow_param_index = 0
        if not param_modes:
            param_modes = [None] * len(args)

    while len(param_modes) < len(args):
        param_modes.append(None)

    # returns borrow with no eligible param -> reject
    if returns_borrow:
        if method_name is not None:
            if not (decl is not None and decl.params and decl.params[0].name == "self" and len(decl.params) == 1):
                if borrow_param_index is None and not (decl is not None and len(decl.params) == 1 and decl.params[0].name != "self"):
                    _add_error(env, "no se puede devolver un prestamo de un local", node)
        else:
            if borrow_param_index is None:
                _add_error(env, "no se puede devolver un prestamo de un local", node)

    # temporal borrow check
    if returns_borrow and borrow_param_index is not None and borrow_param_index >= 0:
        if borrow_param_index < len(args):
            expr = args[borrow_param_index].value if isinstance(args[borrow_param_index], Arg) else args[borrow_param_index]
            if _place_of(expr, env) is None:
                _add_error(env, "no se puede devolver un prestamo de un temporal", node)
    if returns_borrow and borrow_param_index == -1:
        if recv_place is None:
            _add_error(env, "no se puede devolver un prestamo de un temporal", node)

    simple_recv = _is_simple_place(recv_place)
    pre_ids = set(id(L) for L in env["loans"])

    if method_name is not None and self_mode == "var" and simple_recv:
        # evaluate args first
        pre_arg_ids = set(id(L) for L in env["loans"])
        for i, arg in enumerate(args):
            pm = param_modes[i] if i < len(param_modes) else None
            _eval_arg(env, arg, pm, idx)
        # remove temporary loans from args before taking unique self
        for L in list(env["loans"]):
            if id(L) not in pre_arg_ids and not L.get("stored", False):
                env["loans"].remove(L)
        # borrow unique self
        if recv_place is not None:
            loan = {"id": ("callself", id(node)), "origin": recv_place, "mode": "unique",
                    "handle": None, "issue": idx, "stored": False, "last_use": idx,
                    "allow_write": False}
            if _loan_conflicts(loan, env["loans"]):
                _add_error(env, "prestamo unico en conflicto", node)
            env["loans"].append(loan)
    else:
        # borrow self first
        if method_name is not None and recv_place is not None:
            if self_mode == "move":
                ty = _type_of_place(recv_place, env)
                if _copyable(ty, tc):
                    _check_read_access(env, recv_place, node)
                else:
                    _check_move_place(env, recv_place, node)
                    if len(recv_place[2]) == 0:
                        _mark_moved(env, recv_place)
            else:
                mode = "unique" if self_mode == "var" else "shared"
                loan = {"id": ("callself", id(node)), "origin": recv_place, "mode": mode,
                        "handle": None, "issue": idx, "stored": False, "last_use": idx,
                        "allow_write": False}
                if _loan_conflicts(loan, env["loans"]):
                    _add_error(env, "prestamo en conflicto", node)
                env["loans"].append(loan)
        # evaluate args
        for i, arg in enumerate(args):
            pm = param_modes[i] if i < len(param_modes) else None
            _eval_arg(env, arg, pm, idx)

    # remove temporary loans created during this call
    for L in list(env["loans"]):
        if id(L) not in pre_ids and not L.get("stored", False):
            env["loans"].remove(L)


def _eval_arg(env, arg, param_mode, idx):
    expr = arg.value if isinstance(arg, Arg) else arg
    pl = _place_of(expr, env)
    if param_mode == "move":
        if pl is not None:
            for part in pl[2]:
                if part[0] == "index" and not isinstance(part[1], str):
                    _check_expr(part[1], env, idx)
            _check_read_access(env, pl, expr)
            ty = _type_of_place(pl, env)
            if _copyable(ty, env["tc"]):
                _check_read_access(env, pl, expr)
            else:
                _check_move_place(env, pl, expr)
                if len(pl[2]) == 0:
                    _mark_moved(env, pl)
        else:
            _check_expr(expr, env, idx)
        return
    if param_mode == "var":
        if pl is not None:
            for part in pl[2]:
                if part[0] == "index" and not isinstance(part[1], str):
                    _check_expr(part[1], env, idx)
            _check_read_access(env, pl, expr)
            loan = {"id": ("argvar", id(expr)), "origin": pl, "mode": "unique",
                    "handle": None, "issue": idx, "stored": False, "last_use": idx,
                    "allow_write": False}
            if _loan_conflicts(loan, env["loans"]):
                _add_error(env, "prestamo unico en conflicto", expr)
            env["loans"].append(loan)
        else:
            _check_expr(expr, env, idx)
        return
    # default shared
    if pl is not None:
        for part in pl[2]:
            if part[0] == "index" and not isinstance(part[1], str):
                _check_expr(part[1], env, idx)
        _check_read_access(env, pl, expr)
        loan = {"id": ("argshr", id(expr)), "origin": pl, "mode": "shared",
                "handle": None, "issue": idx, "stored": False, "last_use": idx,
                "allow_write": False}
        if _loan_conflicts(loan, env["loans"]):
            _add_error(env, "prestamo en conflicto", expr)
        env["loans"].append(loan)
    else:
        _check_expr(expr, env, idx)


# ---------- top-level ----------

def _check_type_decl(td, tc, program, borrow_errors):
    # field borrows
    for m in (td.members or []):
        node = m.node
        if isinstance(node, Field) and node.type_ is not None:
            if _contains_borrow(node.type_):
                borrow_errors.append(BorrowError("los prestamos no se almacenan en campos", node))
    # methods
    for m in (td.members or []):
        node = m.node
        if isinstance(node, FnDecl):
            _check_function(node, td.name, tc, program, borrow_errors)


def _check_function(fn, self_type, tc, program, borrow_errors):
    scope = tc.resolver.func_scopes.get(id(fn))
    if scope is None:
        scope = tc.module_scope.child("func", owner=fn)
    # assign indices
    counter = [0]
    if fn.body is not None:
        _assign_indices_suite(fn.body, counter)
    last_use = {}
    if fn.body is not None:
        _collect_uses_suite(fn.body, last_use)
    for p in (fn.params or []):
        if p.name not in last_use:
            last_use[p.name] = 0

    env = {
        "scope": scope,
        "func": fn,
        "tc": tc,
        "program": program,
        "self_type": self_type,
        "types": {},
        "moved": set(),
        "loans": [],
        "errors": borrow_errors,
        "last_use": last_use,
    }

    for p in (fn.params or []):
        if p.name == "self":
            ty = N(self_type) if self_type else UNKNOWN
        else:
            ty = tc._atype(p.type_) if p.type_ is not None else UNKNOWN
        env["types"][p.name] = ty

    for p in (fn.params or []):
        if p.name == "self":
            _ty = N(self_type) if self_type else UNKNOWN
        else:
            _ty = tc._atype(p.type_) if p.type_ is not None else UNKNOWN
        if _type_kind(_ty) in ("rc", "arc"):
            continue
        if p.mode == "move":
            continue
        if p.mode == "var":
            env["loans"].append({
                "id": ("param", p.name), "origin": ("place", p.name, ()),
                "mode": "unique", "handle": p.name, "issue": 0, "stored": True,
                "last_use": last_use.get(p.name, 0), "allow_write": True,
            })
        else:
            env["loans"].append({
                "id": ("param", p.name), "origin": ("place", p.name, ()),
                "mode": "shared", "handle": p.name, "issue": 0, "stored": True,
                "last_use": last_use.get(p.name, 0), "allow_write": False,
            })

    if fn.body is not None:
        _check_suite(fn.body, env)
        # implicit return (last expression) checks
        if getattr(fn.body, "stmts", None):
            last = fn.body.stmts[-1]
            if isinstance(last, ExprStmt):
                if isinstance(last.expr, (Lambda, MoveExpr)):
                    _add_error(env, "la closure escapa", last.expr)
                ty = _expr_type(last.expr, env)
                if isinstance(ty, tuple) and ty[0] == "borrow":
                    params = getattr(fn, "params", []) or []
                    origin_root = None
                    pl = _place_of(last.expr, env)
                    if pl is not None:
                        origin_root = pl[1]
                    allowed = False
                    if origin_root == "self":
                        allowed = True
                    elif len(params) == 1 and params[0].name == origin_root:
                        allowed = True
                    if not allowed:
                        _add_error(env, "no se puede devolver un prestamo de un local", last.expr)


def _check_program(program, tc, borrow_errors):
    module_env = {
        "scope": tc.module_scope,
        "func": None,
        "tc": tc,
        "program": program,
        "self_type": None,
        "types": {},
        "moved": set(),
        "loans": [],
        "errors": borrow_errors,
        "last_use": {},
    }
    for stmt in program.stmts:
        if isinstance(stmt, (LetDecl, VarDecl, LetStmt, VarStmt, Assign, ExprStmt,
                            IfStmt, WhileStmt, ForStmt, MatchStmt, ReturnStmt,
                            SpawnStmt, AwaitStmt)):
            _check_stmt(stmt, module_env)
        elif isinstance(stmt, FnDecl):
            _check_function(stmt, None, tc, program, borrow_errors)
        elif isinstance(stmt, TypeDecl):
            _check_type_decl(stmt, tc, program, borrow_errors)
        elif isinstance(stmt, TraitDecl):
            pass


def borrow_check(source):
    """Parse + typecheck + borrow check. Returns list of BorrowError."""
    try:
        program = parse(source)
        elaborate(program)
    except Exception as e:
        return [BorrowError(str(e))]
    tc = TC(program)
    type_errors = tc.check()
    borrow_errors = []
    if type_errors:
        for e in type_errors:
            borrow_errors.append(BorrowError(str(e), getattr(e, "node", None)))
        return borrow_errors
    _check_program(program, tc, borrow_errors)
    return borrow_errors


def check(source):
    return borrow_check(source)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 borrow.py <file.mim>")
        sys.exit(1)
    errs = borrow_check(open(sys.argv[1]).read())
    if errs:
        print(f"{len(errs)} borrow errors:")
        for e in errs:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("OK: borrow-checked")
        sys.exit(0)