"""Borrow checker sobre BIR con prestamos NLL.

El analisis es intra-procedural y trabaja sobre el CFG:

- *Liveness* hacia atras para saber hasta que punto vive cada referencia
  (el prestatario).  Un prestamo esta activo mientras su local destino esta
  vivo; por tanto termina en su ultimo uso (R7).
- *Moves* hacia adelante (analisis "may") para detectar usos tras mover.
- En cada sentencia se comprueban exclusividad, mutabilidad y movimientos.

Los modos de parametro (`shared`, `unique`, `move`) se leen de `Param.mode`
(con compatibilidad para el viejo `mutable`).  Las llamadas usan las firmas de
las funciones del programa cuando se construye `BorrowChecker(functions)`.
"""
from .ir import *

# Metodos de biblioteca que mutan el receptor y por tanto exigen un
# prestamo unico (el equivalente a `var self`).
MUTATING_METHODS = {
    "list.push", "list.pop", "list.reverse", "list.sort", "list.clear",
    "map.insert", "map.del", "map.remove", "map.clear",
    "set.insert", "set.add", "set.push", "set.remove", "set.del", "set.clear",
}

# Builtins que consumen su argumento.
MOVE_BUILTINS = {"drop"}


def _root(place):
    p = place
    while p is not None and p.kind in ("field", "index", "deref"):
        p = p.base
    return p


def _root_name(place):
    p = _root(place)
    if p is None:
        return None
    return p.name if p.kind == "local" else None


def _param_mode(p):
    if p.mode:
        return p.mode
    return "unique" if p.mutable else "shared"


class Loan:
    __slots__ = ("place", "kind", "target", "span")

    def __init__(self, place, kind, target, span=None):
        self.place = place
        self.kind = kind
        self.target = target
        self.span = span


class BorrowChecker:
    def __init__(self, functions=None):
        self.errors = []
        if functions is None:
            functions = []
        if isinstance(functions, dict):
            functions = list(functions.values())
        self.functions = list(functions)
        self._sigs = None

    # ---- diagnostico ----

    def err(self, msg, stmt=None):
        span = getattr(stmt, "span", None) if stmt is not None else None
        if span is not None and getattr(span, "line", None):
            self.errors.append(f"{span.line}:{span.col}: {msg}")
        else:
            self.errors.append(msg)

    # ---- firmas ----

    def sigs(self):
        if self._sigs is None:
            self._sigs = {}
            for f in self.functions:
                self._sigs[f.name] = [_param_mode(p) for p in f.params]
        return self._sigs

    def add_sig(self, func):
        self.sigs()[func.name] = [_param_mode(p) for p in func.params]

    # ---- utilidades de places ----

    @staticmethod
    def overlap(p1, p2):
        a, b = p1.path(), p2.path()
        n = min(len(a), len(b))
        return a[:n] == b[:n]

    @staticmethod
    def _moved(place, moved):
        name = _root_name(place)
        return name in moved

    def _expand_captures(self, names, captures):
        """Un uso de una closure mantiene vivos los locales que captura."""
        out = set(names)
        stack = list(names)
        while stack:
            n = stack.pop()
            for c in captures.get(n, ()):
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    # ---- efectos de rvalues ----

    @staticmethod
    def rvalue_uses(rv):
        return rv.used_places() if rv is not None else []

    @classmethod
    def rvalue_moves(cls, rv):
        """Places que se mueven al evaluar `rv` como valor."""
        if rv is None:
            return []
        if rv.kind == "use" and rv.place is not None:
            return [rv.place]
        if rv.kind == "aggregate" and rv.agg_kind != "closure":
            out = []
            for it in rv.items:
                out += cls.rvalue_moves(it)
            return out
        return []

    @classmethod
    def nested_moves(cls, rv):
        """Movimientos dentro de un agregado, sin mover el `use` exterior."""
        if rv is None:
            return []
        if rv.kind == "aggregate" and rv.agg_kind != "closure":
            out = []
            for it in rv.items:
                out += cls.rvalue_moves(it)
            return out
        return []

    def _loan_source(self, rv):
        """Local cuyo valor es una referencia (posiblemente ya un loan)."""
        if rv is None:
            return None
        if rv.kind == "cast":
            return self._loan_source(rv.a)
        if rv.kind == "use" and rv.place is not None:
            name = _root_name(rv.place)
            if name in self.loans or name in self.captures:
                return name
        return None

    def _resolve_loan(self, name):
        seen = set()
        while name and name not in seen:
            if name in self.loans:
                return self.loans[name]
            seen.add(name)
            parents = self.captures.get(name) or []
            name = parents[0] if parents else None
        return None

    def _loan_for_rvalue(self, rv):
        """Si el rvalue es una referencia a un local prestado, devuelve el loan."""
        if rv is None:
            return None
        if rv.kind == "cast":
            return self._loan_for_rvalue(rv.a)
        if rv.kind == "use" and rv.place is not None:
            return self._resolve_loan(_root_name(rv.place))
        return None

    # ---- uso / definicion para liveness ----

    def _stmt_use_def(self, stmt):
        uses, defs = set(), set()
        k = stmt.kind
        if k == "Assign":
            uses |= {_root_name(p) for p in self.rvalue_uses(stmt.rvalue)}
            d = _root_name(stmt.place)
            if d:
                defs.add(d)
        elif k == "Call":
            for a in stmt.call_args:
                uses |= {_root_name(p) for p in self.rvalue_uses(a)}
            d = _root_name(stmt.call_dest)
            if d:
                defs.add(d)
        elif k == "Borrow":
            u = _root_name(stmt.place)
            if u:
                uses.add(u)
            if stmt.borrow_target:
                defs.add(stmt.borrow_target)
        elif k == "Drop":
            u = _root_name(stmt.place)
            if u:
                uses.add(u)
        elif k in ("StorageLive", "StorageDead"):
            d = _root_name(stmt.place)
            if d:
                defs.add(d)
        uses.discard(None)
        defs.discard(None)
        if getattr(self, "captures", None):
            uses = self._expand_captures(uses, self.captures)
        return uses, defs

    def _term_uses(self, term):
        if term is None or term.discr is None:
            return set()
        uses = {_root_name(p) for p in self.rvalue_uses(term.discr)} - {None}
        if getattr(self, "captures", None):
            uses = self._expand_captures(uses, self.captures)
        return uses

    # ---- CFG / liveness ----

    def _successors(self, term):
        if term is None:
            return []
        if term.kind == "Goto":
            return [term.target] if term.target is not None else []
        if term.kind == "SwitchInt":
            out = [t for _, t in term.cases]
            if term.otherwise is not None:
                out.append(term.otherwise)
            return out
        return []

    def _liveness(self, func):
        blocks = {b.id: b for b in func.blocks}
        succ = {b.id: self._successors(b.terminator) for b in func.blocks}
        use, dfn = {}, {}
        for b in func.blocks:
            u, d = set(), set()
            for stmt in b.stmts:
                su, sd = self._stmt_use_def(stmt)
                u |= su - d
                d |= sd
            tu = self._term_uses(b.terminator)
            u |= tu - d
            use[b.id], dfn[b.id] = u, d

        live_in = {bid: set() for bid in blocks}
        live_out = {bid: set() for bid in blocks}
        changed = True
        while changed:
            changed = False
            for bid in blocks:
                out = set()
                for s in succ[bid]:
                    if s in live_in:
                        out |= live_in[s]
                new_in = use[bid] | (out - dfn[bid])
                if out != live_out[bid] or new_in != live_in[bid]:
                    live_out[bid], live_in[bid] = out, new_in
                    changed = True

        # Liveness en cada punto (justo antes de cada sentencia).
        live_before = {}
        for b in func.blocks:
            live = set(live_out[b.id])
            for j in range(len(b.stmts) - 1, -1, -1):
                u, d = self._stmt_use_def(b.stmts[j])
                live = (live - d) | u
                live_before[(b.id, j)] = set(live)
        return live_in, live_out, live_before

    def _moved_in(self, func):
        blocks = {b.id: b for b in func.blocks}
        succ = {b.id: self._successors(b.terminator) for b in func.blocks}
        in_moved = {bid: set() for bid in blocks}
        if func.entry in in_moved:
            in_moved[func.entry] = set()
        changed = True
        while changed:
            changed = False
            for bid in blocks:
                out = set(in_moved[bid])
                for stmt in blocks[bid].stmts:
                    self._transfer_moved(stmt, out)
                for s in succ[bid]:
                    if s in in_moved:
                        new = in_moved[s] | out
                        if new != in_moved[s]:
                            in_moved[s] = new
                            changed = True
        return in_moved

    def _arg_mode(self, func, i):
        sig = self.sigs().get(func)
        if sig is not None and i < len(sig):
            return sig[i]
        if func in MUTATING_METHODS and i == 0:
            return "unique"
        if func in MOVE_BUILTINS and i == 0:
            return "move"
        return "shared"

    def _transfer_moved(self, stmt, moved):
        k = stmt.kind
        if k == "Assign":
            for p in self.rvalue_moves(stmt.rvalue):
                if _root_name(stmt.place) == _root_name(p):
                    continue
                n = _root_name(p)
                if n:
                    moved.add(n)
            d = _root_name(stmt.place)
            if d:
                moved.discard(d)
        elif k == "Call":
            for i, a in enumerate(stmt.call_args):
                if self._arg_mode(stmt.call_func or "", i) != "move":
                    continue
                for p in self.rvalue_moves(a):
                    n = _root_name(p)
                    if n:
                        moved.add(n)
            d = _root_name(stmt.call_dest)
            if d:
                moved.discard(d)
        elif k in ("StorageLive", "StorageDead"):
            d = _root_name(stmt.place)
            if d:
                moved.discard(d)

    # ---- comprobaciones ----

    def _active_loans(self, live):
        return [ln for t, ln in self.loans.items() if t in live]

    def _check_place(self, place, access, live, moved, stmt, check_moved=True):
        if place is None:
            return
        if check_moved and self._moved(place, moved):
            self.err(f"use of moved value {_root_name(place)}", stmt)
        for ln in self._active_loans(live):
            if not self.overlap(place, ln.place):
                continue
            if access == "read":
                if ln.kind == "unique":
                    self.err(f"cannot read {place_str(place)} while a unique loan is active", stmt)
            elif access == "borrow_shared":
                if ln.kind == "unique":
                    self.err(f"cannot borrow {place_str(place)} while a unique loan is active", stmt)
            elif access == "borrow_unique":
                self.err(f"conflicting borrow: {place_str(place)} vs {place_str(ln.place)}", stmt)
            elif access in ("write", "move", "drop"):
                self.err(f"cannot {access} {place_str(place)} while borrowed by {place_str(ln.place)}", stmt)

    def _check_rvalue(self, rv, live, moved, stmt):
        if rv is None:
            return
        for p in self.rvalue_uses(rv):
            self._check_place(p, "read", live, moved, stmt)

    def _check_move(self, place, live, moved, stmt, top=True):
        if place is None:
            return
        if place.kind != "local":
            self.err(f"partial move of {place_str(place)} is not allowed", stmt)
            return
        name = _root_name(place)
        p = self.params.get(name)
        if p is not None and _param_mode(p) != "move":
            self.err(f"cannot move out of borrowed parameter '{name}'", stmt)
            return
        self._check_place(place, "move", live, moved, stmt)
        if name:
            moved.add(name)

    def _check_mutable(self, place, stmt, block_id, idx):
        root = _root(place)
        if root is None or root.kind != "local":
            return
        name = root.name
        loc = self.locals.get(name)
        if loc is None:
            return
        if loc.mutable or getattr(stmt, "init", False):
            return
        if place.kind == "local" and (block_id, idx) in self.init_sites.get(name, ()):
            return
        self.err(f"cannot assign to immutable binding '{name}'", stmt)

    def _check_unique_arg(self, arg, live, moved, stmt):
        if arg is None:
            return
        for p in self.rvalue_uses(arg):
            self._check_place(p, "read", live, moved, stmt)
        for p in self.nested_moves(arg):
            self._check_move(p, live, moved, stmt, top=False)
        if arg.kind != "use" or arg.place is None:
            # Un temporal se puede mutar durante la llamada.
            return
        place = arg.place
        root = _root_name(place)
        loc = self.locals.get(root)
        if loc is not None and not loc.mutable:
            self.err(f"cannot pass '{root}' to a unique parameter; declare it with 'var'", stmt)
        if self._moved(place, moved):
            self.err(f"use of moved value {root}", stmt)
        for ln in self._active_loans(live):
            if self.overlap(place, ln.place):
                self.err(f"cannot mutate '{place_str(place)}' while borrowed by "
                         f"'{place_str(ln.place)}'", stmt)

    def _check_call(self, stmt, live, moved):
        func = stmt.call_func or ""
        for i, a in enumerate(stmt.call_args):
            mode = self._arg_mode(func, i)
            if mode == "unique":
                self._check_unique_arg(a, live, moved, stmt)
            elif mode == "move":
                self._check_rvalue(a, live, moved, stmt)
                for p in self.rvalue_moves(a):
                    self._check_move(p, live, moved, stmt)
            else:
                self._check_rvalue(a, live, moved, stmt)
                for p in self.nested_moves(a):
                    self._check_move(p, live, moved, stmt, top=False)
        d = stmt.call_dest
        if d is not None:
            self._check_mutable(d, stmt, -1, -1)
            name = _root_name(d)
            if name:
                moved.discard(name)

    def _check_assign(self, stmt, live, moved, block_id, idx):
        dest = stmt.place
        rv = stmt.rvalue
        self._check_rvalue(rv, live, moved, stmt)

        # Devolver un prestamo de un local no es legal (R5).
        dname = _root_name(dest)
        if dname and dname.startswith("__ret"):
            ln = self._loan_for_rvalue(rv)
            if ln is not None:
                owner = _root_name(ln.place)
                if owner not in self.params:
                    self.err(f"cannot return a borrow of local '{owner}'", stmt)

        for p in self.rvalue_moves(rv):
            if _root_name(p) == dname:
                continue
            self._check_move(p, live, moved, stmt)

        if dest is None:
            return
        root = _root_name(dest)
        loc = self.locals.get(root)
        is_local = dest.kind == "local"
        if loc is not None:
            if is_local:
                init = getattr(stmt, "init", False) or \
                    (block_id, idx) in self.init_sites.get(root, ())
                if not loc.mutable and not init:
                    self.err(f"cannot assign to immutable binding '{root}'", stmt)
            else:
                if root in moved:
                    self.err(f"use of moved value {place_str(dest)}", stmt)
                if not loc.mutable:
                    self.err(f"cannot assign to immutable binding '{root}'", stmt)
        self._check_place(dest, "write", live, moved, stmt, check_moved=False)
        if is_local and root:
            moved.discard(root)

    def _check_stmt(self, stmt, live, moved, block_id, idx):
        k = stmt.kind
        if k == "Nop":
            return
        if k == "StorageLive":
            name = _root_name(stmt.place)
            if name:
                moved.discard(name)
            return
        if k == "StorageDead":
            root = _root_name(stmt.place)
            if root:
                for ln in self._active_loans(live):
                    if _root_name(ln.place) == root and ln.target != root:
                        self.err(f"'{root}' is dropped while borrowed", stmt)
                moved.discard(root)
            return
        if k == "Assign":
            self._check_assign(stmt, live, moved, block_id, idx)
            return
        if k == "Borrow":
            kind = "unique" if stmt.borrow_kind in ("mut", "unique") else "shared"
            self._check_place(stmt.place,
                              "borrow_unique" if kind == "unique" else "borrow_shared",
                              live, moved, stmt)
            return
        if k == "Drop":
            self._check_place(stmt.place, "drop", live, moved, stmt)
            return
        if k == "Call":
            self._check_call(stmt, live, moved)
            return

    # ---- entrada ----

    def _collect(self, func):
        self.locals = {l.name: l for l in func.locals}
        self.params = {p.name: p for p in func.params}
        for p in func.params:
            self.locals.setdefault(p.name, Local(p.name, p.type, p.mutable))
        self.loans = {}
        for b in func.blocks:
            for stmt in b.stmts:
                if stmt.kind == "Borrow" and stmt.borrow_target:
                    kind = "unique" if stmt.borrow_kind in ("mut", "unique") else "shared"
                    self.loans[stmt.borrow_target] = Loan(stmt.place, kind,
                                                          stmt.borrow_target,
                                                          stmt.span)
        self.captures = {l.name: list(l.captures) for l in func.locals}
        # Copiar una referencia (`let r = &v`, `let s = r`) mantiene vivo el
        # prestamo original mientras viva la copia.
        for b in func.blocks:
            for stmt in b.stmts:
                if stmt.kind != "Assign":
                    continue
                dest = _root_name(stmt.place)
                src = self._loan_source(stmt.rvalue)
                if dest and src and src != dest:
                    self.captures.setdefault(dest, []).append(src)
        self.init_sites = {}
        seen = set()
        for b in func.blocks:
            for i, stmt in enumerate(b.stmts):
                if stmt.kind in ("Assign", "Call"):
                    d = _root_name(stmt.place if stmt.kind == "Assign" else stmt.call_dest)
                    if d and d not in seen:
                        seen.add(d)
                        self.init_sites.setdefault(d, set()).add((b.id, i))

    def check(self, func):
        self.errors = []
        self.add_sig(func)
        self._collect(func)
        live_in, live_out, live_before = self._liveness(func)
        in_moved = self._moved_in(func)

        for b in func.blocks:
            moved = set(in_moved.get(b.id, ()))
            for i, stmt in enumerate(b.stmts):
                self._check_stmt(stmt, live_before.get((b.id, i), set()),
                                 moved, b.id, i)
            term = b.terminator
            if term is not None:
                self._check_rvalue(term.discr, live_out.get(b.id, set()), moved, term)
        return list(self.errors)


def _path_to_place(path):
    # reconstruct a Place-ish object with .path() returning path
    class _P:
        def __init__(self, p):
            self._p = p

        def path(self):
            return self._p
    return _P(path)
