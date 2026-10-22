"""Borrow checker sobre BIR (prototipo)."""
from .ir import *


class BorrowChecker:
    def __init__(self):
        self.errors = []

    def err(self, msg):
        self.errors.append(msg)

    def check(self, func: Function):
        self.errors = []
        # mapa de locals
        locals_map = {l.name: l for l in func.locals}
        params_map = {p.name: p for p in func.params}
        # moved set
        moved = set()
        # active loans: list of (place_path, kind, target)
        # procesamos bloque por bloque en orden; expiry simple por bloque
        for block in func.blocks:
            active = []
            for stmt in block.stmts:
                # expire loans whose target is StorageDead? no; keep simple
                self.check_stmt(stmt, active, moved, func, locals_map, params_map)
            # al final del bloque, conservador: no expiramos (NLL aproximado por StorageDead)
        return list(self.errors)

    def place_path(self, p: Place):
        return p.path()

    def overlap(self, p1: Place, p2: Place):
        a = p1.path()
        b = p2.path()
        # overlap si uno es prefijo del otro
        n = min(len(a), len(b))
        return a[:n] == b[:n]

    def is_moved(self, p: Place, moved):
        # check if p or any prefix moved
        pp = p.path()
        for m in moved:
            if len(m) <= len(pp) and pp[:len(m)] == m:
                return True
        return False

    def check_stmt(self, stmt, active, moved, func, locals_map, params_map):
        k = stmt.kind
        if k == "StorageLive":
            return
        if k == "StorageDead":
            # remove loans targeting this place
            if stmt.place is not None:
                pp = stmt.place.path()
                active[:] = [ln for ln in active if ln[0] != pp]
            return
        if k == "Nop":
            return
        if k == "Assign":
            # check rvalue uses
            for up in stmt.rvalue.used_places():
                if self.is_moved(up, moved):
                    self.err(f"use of moved value {up}")
            # if assigning to a moved place? reinit ok
            # move semantics: if rvalue is Use(place) of non-copy, mark source moved
            if stmt.rvalue.kind == "use" and stmt.rvalue.place is not None:
                # conservador: mark moved
                moved.add(stmt.rvalue.place.path())
            return
        if k == "Borrow":
            place = stmt.place
            kind = stmt.borrow_kind or "shared"
            target = stmt.borrow_target
            # check moved
            if self.is_moved(place, moved):
                self.err(f"borrow of moved value {place}")
            # check exclusivity against active loans
            for (lp, lk, lt) in active:
                if self.overlap(place, _path_to_place(lp)):
                    if kind == "mut" or lk == "mut":
                        self.err(f"conflicting borrow: {place} vs {lp}")
            # add loan
            active.append((place.path(), kind, target))
            return
        if k == "Drop":
            if stmt.place is not None and self.is_moved(stmt.place, moved):
                self.err(f"drop of moved value {stmt.place}")
            return
        if k == "Call":
            for a in stmt.call_args:
                for up in a.used_places():
                    if self.is_moved(up, moved):
                        self.err(f"use of moved value {up}")
            if stmt.call_dest is not None and stmt.rvalue is None:
                pass
            return


def _path_to_place(path):
    # reconstruct a Place-ish object with .path() returning path
    class _P:
        def __init__(self, p):
            self._p = p
        def path(self):
            return self._p
    return _P(path)
