"""Professional borrow checker over BIR (CFG dataflow + NLL + liveness)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, FrozenSet
from tools.bir import (Module, Function, Block, Stmt, StmtKind, Place, PlaceKind,
                       Rvalue, RvalueKind, Type, TypeKind)


@dataclass
class State:
    moved: frozenset = field(default_factory=frozenset)
    loans: frozenset = field(default_factory=frozenset)  # (kind, place_key, target)


def _key(p: Place) -> str:
    if p.kind == PlaceKind.LOCAL:
        return f"local:{p.name}"
    if p.kind == PlaceKind.FIELD:
        return f"field:{_key(p.base)}:{p.field}"
    if p.kind == PlaceKind.INDEX:
        return f"index:{_key(p.base)}"
    if p.kind == PlaceKind.DEREF:
        return f"deref:{_key(p.base)}"
    return "?"

def _root(k: str) -> str:
    parts = k.split(":")
    for i, t in enumerate(parts):
        if t == "local" and i + 1 < len(parts):
            return parts[i + 1]
    return k

def _overlap(a: str, b: str) -> bool:
    if _root(a) != _root(b):
        return False
    if a == b:
        return True
    if a == f"local:{_root(a)}" or b == f"local:{_root(b)}":
        return True
    return a.startswith(b + ":") or b.startswith(a + ":")

COPY_TYPES = {TypeKind.BOOL, TypeKind.I8, TypeKind.I16, TypeKind.I32, TypeKind.I64,
              TypeKind.U8, TypeKind.U16, TypeKind.U32, TypeKind.U64,
              TypeKind.F32, TypeKind.F64}

def _is_copy(t: Optional[Type]) -> bool:
    if t is None:
        return False
    return t.kind in COPY_TYPES

# ---------- type lookup ----------
def _place_type(fn: Function, p: Place) -> Optional[Type]:
    if p.kind == PlaceKind.LOCAL:
        for loc in fn.locals:
            if loc.name == p.name:
                return loc.type
        for par in fn.params:
            if par.name == p.name:
                return par.type
    if p.kind == PlaceKind.FIELD and p.base is not None:
        bt = _place_type(fn, p.base)
        if bt is not None and bt.kind == TypeKind.STRUCT:
            for (fname, ftype) in bt.fields:
                if fname == p.field:
                    return ftype
    if p.kind == PlaceKind.DEREF and p.base is not None:
        bt = _place_type(fn, p.base)
        if bt is not None and bt.kind == TypeKind.REF:
            return bt.elem
    if p.kind == PlaceKind.INDEX and p.base is not None:
        bt = _place_type(fn, p.base)
        if bt is not None and bt.kind in (TypeKind.ARRAY, TypeKind.SLICE):
            return bt.elem
    return None

# ---------- place/rvalue traversal ----------
def _collect_locals_place(p: Optional[Place], uses: Set[str], defs: Set[str] = None):
    if p is None:
        return
    if p.kind == PlaceKind.LOCAL:
        if defs is not None and False:
            pass
        uses.add(p.name)
    if p.kind == PlaceKind.INDEX and p.idx is not None:
        _collect_locals_rvalue(p.idx, uses)
    if p.base is not None:
        _collect_locals_place(p.base, uses, defs)

def _collect_locals_rvalue(rv: Optional[Rvalue], uses: Set[str]):
    if rv is None:
        return
    if rv.kind == RvalueKind.USE and rv.place is not None:
        _collect_locals_place(rv.place, uses)
    if rv.kind == RvalueKind.REF and rv.place is not None:
        _collect_locals_place(rv.place, uses)
    if rv.kind == RvalueKind.CAST and rv.place is not None:
        _collect_locals_place(rv.place, uses)
    if rv.kind == RvalueKind.BINOP:
        _collect_locals_rvalue(rv.a, uses)
        _collect_locals_rvalue(rv.b, uses)
    if rv.kind == RvalueKind.UNARYOP:
        _collect_locals_rvalue(rv.a, uses)
    if rv.kind == RvalueKind.AGGREGATE:
        for f in rv.agg_fields:
            _collect_locals_rvalue(f, uses)
    if rv.kind == RvalueKind.CONST:
        pass

def _stmt_uses(s: Stmt) -> Set[str]:
    u: Set[str] = set()
    if s.place is not None:
        _collect_locals_place(s.place, u)
    if s.rvalue is not None:
        _collect_locals_rvalue(s.rvalue, u)
    if s.borrow_place is not None:
        _collect_locals_place(s.borrow_place, u)
    for a in s.args:
        _collect_locals_rvalue(a, u)
    if s.dest is not None:
        _collect_locals_place(s.dest, u)
    return u

def _stmt_defs(s: Stmt) -> Set[str]:
    d: Set[str] = set()
    if s.kind in (StmtKind.ASSIGN,) and s.place is not None and s.place.kind == PlaceKind.LOCAL:
        d.add(s.place.name)
    if s.kind == StmtKind.CALL and s.dest is not None and s.dest.kind == PlaceKind.LOCAL:
        d.add(s.dest.name)
    return d

def _term_uses(t) -> Set[str]:
    u: Set[str] = set()
    if t is None:
        return u
    if hasattr(t, "discr") and t.discr is not None:
        _collect_locals_rvalue(t.discr, u)
    return u

# ---------- checker core ----------
def _process_place_embedded(fn, p, state, errors, ctx):
    if p is None:
        return
    if p.kind == PlaceKind.INDEX and p.idx is not None:
        _process_rvalue_embedded(fn, p.idx, state, errors, ctx)
    if p.base is not None:
        _process_place_embedded(fn, p.base, state, errors, ctx)

def _process_rvalue_embedded(fn, rv, state, errors, ctx):
    if rv is None:
        return
    if rv.kind == RvalueKind.USE and rv.place is not None:
        _check_use(fn, rv.place, state, errors, ctx)
    if rv.kind == RvalueKind.REF and rv.place is not None:
        _check_use(fn, rv.place, state, errors, ctx)
    if rv.kind == RvalueKind.CAST and rv.place is not None:
        _check_use(fn, rv.place, state, errors, ctx)
    if rv.kind == RvalueKind.BINOP:
        _process_rvalue_embedded(fn, rv.a, state, errors, ctx)
        _process_rvalue_embedded(fn, rv.b, state, errors, ctx)
    if rv.kind == RvalueKind.UNARYOP:
        _process_rvalue_embedded(fn, rv.a, state, errors, ctx)
    if rv.kind == RvalueKind.AGGREGATE:
        for f in rv.agg_fields:
            _process_rvalue_embedded(fn, f, state, errors, ctx)

def _check_use(fn, p, state, errors, ctx):
    _process_place_embedded(fn, p, state, errors, ctx)
    k = _key(p)
    if k in state.moved or any(_overlap(m, k) for m in state.moved):
        errors.append(f"use of moved place {k} ({ctx})")
    for (kind, pk, _target) in state.loans:
        if kind == 1 and _overlap(pk, k):
            errors.append(f"use of {k} while mutably borrowed ({ctx})")

def _check_assign(fn, p, rv, state, errors):
    _process_place_embedded(fn, p, state, errors, "assign")
    k = _key(p)
    for (kind, pk, _t) in state.loans:
        if _overlap(pk, k):
            errors.append(f"assign to {k} while borrowed")
    if rv is not None:
        _process_rvalue_embedded(fn, rv, state, errors, "assign")
    new_moved = set(state.moved)
    if rv is not None and rv.kind == RvalueKind.USE and rv.place is not None:
        src = _key(rv.place)
        ty = _place_type(fn, rv.place)
        if not _is_copy(ty):
            new_moved.add(src)
    new_moved = {m for m in new_moved if not _overlap(m, k)}
    return State(frozenset(new_moved), state.loans)

def _apply_stmt(fn, stmt, state, errors) -> State:
    if stmt.kind == StmtKind.STORAGE_LIVE:
        return state
    if stmt.kind == StmtKind.STORAGE_DEAD:
        k = _key(stmt.place)
        new_loans = frozenset((kind, pk, t) for (kind, pk, t) in state.loans if not _overlap(pk, k))
        new_moved = frozenset(m for m in state.moved if not _overlap(m, k))
        return State(new_moved, new_loans)
    if stmt.kind == StmtKind.ASSIGN:
        return _check_assign(fn, stmt.place, stmt.rvalue, state, errors)
    if stmt.kind == StmtKind.BORROW:
        pk = _key(stmt.borrow_place)
        _process_place_embedded(fn, stmt.borrow_place, state, errors, "borrow")
        _check_use(fn, stmt.borrow_place, state, errors, "borrow")
        if stmt.borrow_kind == 1:
            for (kind, lpk, _t) in state.loans:
                if _overlap(lpk, pk):
                    errors.append(f"mut borrow of {pk} while borrowed")
            new_loans = set(state.loans) | {(1, pk, stmt.borrow_target)}
        else:
            for (kind, lpk, _t) in state.loans:
                if kind == 1 and _overlap(lpk, pk):
                    errors.append(f"shared borrow of {pk} while mutably borrowed")
            new_loans = set(state.loans) | {(0, pk, stmt.borrow_target)}
        return State(state.moved, frozenset(new_loans))
    if stmt.kind == StmtKind.CALL:
        for a in stmt.args:
            _process_rvalue_embedded(fn, a, state, errors, "call arg")
        new_moved = set(state.moved)
        for a in stmt.args:
            if a is not None and a.kind == RvalueKind.USE and a.place is not None:
                ty = _place_type(fn, a.place)
                if not _is_copy(ty):
                    new_moved.add(_key(a.place))
        cur_state = State(frozenset(new_moved), state.loans)
        if stmt.dest is not None:
            cur_state = _check_assign(fn, stmt.dest, None, cur_state, errors)
        return cur_state
    if stmt.kind == StmtKind.DROP:
        _check_use(fn, stmt.place, state, errors, "drop")
        k = _key(stmt.place)
        new_moved = set(state.moved) | {k}
        return State(frozenset(new_moved), state.loans)
    if stmt.kind == StmtKind.NOP:
        return state
    return state

def check_function(fn: Function) -> List[str]:
    errors: List[str] = []
    blocks = {b.id: b for b in fn.blocks}
    # predecessors
    preds: Dict[int, Set[int]] = {b.id: set() for b in fn.blocks}
    for b in fn.blocks:
        t = b.terminator
        if t is None:
            continue
        if t.kind == 0:
            preds[t.target].add(b.id)
        elif t.kind == 1:
            for (_, tgt) in t.cases:
                preds[tgt].add(b.id)
            preds[t.otherwise].add(b.id)

    # ---------- liveness (block level) ----------
    # USE/DEF per block
    use_sets: Dict[int, Set[str]] = {}
    def_sets: Dict[int, Set[str]] = {}
    for b in fn.blocks:
        uses: Set[str] = set()
        defs: Set[str] = set()
        for s in b.stmts:
            uses |= (_stmt_uses(s) - defs)
            defs |= _stmt_defs(s)
        uses |= (_term_uses(b.terminator) - defs)
        use_sets[b.id] = uses
        def_sets[b.id] = defs

    # live-out fixpoint
    live_out: Dict[int, Set[str]] = {b.id: set() for b in fn.blocks}
    # successors
    succs_map: Dict[int, List[int]] = {}
    for b in fn.blocks:
        t = b.terminator
        if t is None:
            succs_map[b.id] = []
        elif t.kind == 0:
            succs_map[b.id] = [t.target]
        elif t.kind == 1:
            succs_map[b.id] = [tgt for (_, tgt) in t.cases] + [t.otherwise]
        else:
            succs_map[b.id] = []

    changed = True
    while changed:
        changed = False
        for b in fn.blocks:
            new_lo = set()
            for s in succs_map[b.id]:
                new_lo |= use_sets[s] | (live_out[s] - def_sets[s])
            if new_lo != live_out[b.id]:
                live_out[b.id] = new_lo
                changed = True

    # per-block last use index (for NLL within block)
    def last_use_index(b: Block) -> Dict[str, int]:
        lu: Dict[str, int] = {}
        for i, s in enumerate(b.stmts):
            for name in _stmt_uses(s):
                lu[name] = i
        # terminator uses count as after last stmt
        for name in _term_uses(b.terminator):
            lu[name] = len(b.stmts)  # sentinel
        return lu

    lu_map = {b.id: last_use_index(b) for b in fn.blocks}

    # ---------- dataflow ----------
    states: Dict[int, State] = {}
    worklist: List[int] = [fn.entry]
    states[fn.entry] = State(frozenset(), frozenset())

    while worklist:
        bid = worklist.pop()
        if bid not in blocks:
            continue
        st = states.get(bid, State(frozenset(), frozenset()))
        blk = blocks[bid]
        cur = st
        lu = lu_map[bid]
        lo = live_out[bid]
        for i, stmt in enumerate(blk.stmts):
            cur = _apply_stmt(fn, stmt, cur, errors)
            # NLL: drop loans whose target's last use is this statement
            # and target not live-out of block
            new_loans = set(cur.loans)
            for (kind, pk, target) in list(cur.loans):
                if lu.get(target, -1) == i and target not in lo:
                    new_loans.discard((kind, pk, target))
            cur = State(cur.moved, frozenset(new_loans))
        # terminator discr check
        t = blk.terminator
        if t is not None and t.kind == 1 and t.discr is not None:
            _process_rvalue_embedded(fn, t.discr, cur, errors, "switch")
        # propagate to successors with NLL: drop loans whose target not live-out
        succs = []
        if t is None:
            pass
        elif t.kind == 0:
            succs = [t.target]
        elif t.kind == 1:
            succs = [tgt for (_, tgt) in t.cases] + [t.otherwise]
        for s in succs:
            # filter loans: keep if target live-out of current block
            filtered_loans = frozenset(
                (kind, pk, target) for (kind, pk, target) in cur.loans
                if target in lo or lu.get(target, -1) == len(blk.stmts)
            )
            # Actually keep loan if target in live_out; also if used in terminator (handled by lu sentinel not in lo maybe). 
            # Conservative: keep if target in lo OR last use index == sentinel (used in terminator) -> then it's used at end, drop after block? terminator is end, so drop.
            # We'll keep simple: keep if target in lo.
            filtered_loans = frozenset(
                (kind, pk, target) for (kind, pk, target) in cur.loans
                if target in lo
            ) | frozenset(
                (kind, pk, target) for (kind, pk, target) in cur.loans
                if target not in lo and lu.get(target, -1) == len(blk.stmts)
            )
            # The above keeps terminator-used loans for this block only; they shouldn't propagate (target used in terminator of this block, then dead). So don't propagate them.
            filtered_loans = frozenset(
                (kind, pk, target) for (kind, pk, target) in cur.loans
                if target in lo
            )
            new_state = State(cur.moved, filtered_loans)
            old = states.get(s)
            if old is None:
                states[s] = new_state
                worklist.append(s)
            else:
                new_moved = old.moved | new_state.moved
                new_loans = old.loans | new_state.loans
                ns = State(frozenset(new_moved), frozenset(new_loans))
                if ns.moved != old.moved or ns.loans != old.loans:
                    states[s] = ns
                    worklist.append(s)

    # dedup
    seen = set()
    out = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def check_module(mod: Module) -> Dict[str, List[str]]:
    out = {}
    for f in mod.functions:
        out[f.name] = check_function(f)
    return out
