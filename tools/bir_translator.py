from tools import nodes as A
from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)
from tools.bir_types import (
    _prim, _ast_type, _tc_type, to_type, _param_mode, _bir_copyable,
    _type_label, _local, _field, _index, _use, _const, _int_const,
    _bool_const, _cmp_eq, place_type_guess,
)



class TranslatorCore:
    def __init__(self, tc=None):
        self.tc = tc
        self.functions = []
        self.fn = None
        self.block = 0
        self.counter = 0

        # Scopes: pila de {nombre fuente: nombre BIR}. Los locales son
        # function-wide en BIR; el sufijo `$N` evita colisiones por sombreado.
        self.scopes = []
        self.decl_scopes = []
        self.loops = []          # [(break_bid, continue_bid)]
        self.scope = None        # scope del typechecker para tipar expresiones
        self.owner = None        # tipo propietario si la funcion es un metodo
        self.ret_place = None
        self.ret_type = Type("unit")
        self._span = None        # span de la sentencia en curso
        self._initializing = set()  # locales que se estan inicializando

    def _fresh(self, prefix):
        while True:
            self.counter += 1
            name = f"__{prefix}{self.counter}"
            if not any(l.name == name for l in self.fn.locals):
                return name

    def _new_local(self, name, ty, mutable=False):
        self.fn.locals.append(Local(name, ty if isinstance(ty, Type) else to_type(ty), mutable))
        if self.decl_scopes:
            self.decl_scopes[-1].append(name)
        return name

    def _new_temp(self, ty):
        return _local(self._new_local(self._fresh("t"), to_type(ty), mutable=True))

    def _declare(self, name, ty, mutable=False):
        """Declara un enlace con nombre BIR unico y lo registra en el scope."""
        bir = name
        if any(l.name == bir for l in self.fn.locals):
            while any(l.name == bir for l in self.fn.locals):
                self.counter += 1
                bir = f"{name}${self.counter}"
        self._new_local(bir, ty, mutable)
        self.scopes[-1][name] = bir
        self._emit(Stmt("StorageLive", place=_local(bir)))
        return bir

    def _lookup(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return name

    def push_scope(self):
        self.scopes.append({})
        self.decl_scopes.append([])

    def pop_scope(self, emit_dead=True):
        names = self.decl_scopes.pop() if self.decl_scopes else []
        if emit_dead and not self._terminated():
            for n in reversed(names):
                self._emit(Stmt("StorageDead", place=_local(n)))
        if self.scopes:
            self.scopes.pop()

    def _block(self):
        return self.fn.blocks[self.block]

    def _emit(self, stmt):
        if getattr(stmt, "span", None) is None:
            stmt.span = self._span
        if (stmt.kind == "Assign" and stmt.place is not None
                and stmt.place.kind == "local"
                and stmt.place.name in self._initializing):
            stmt.init = True
        self._block().stmts.append(stmt)

    def _new_block(self):
        b = Block(len(self.fn.blocks))
        self.fn.blocks.append(b)
        return b.id

    def _goto_block(self, bid):
        self.block = bid

    def _terminated(self):
        return self._block().terminator is not None

    def _term(self, term):
        if getattr(term, "span", None) is None:
            term.span = self._span
        self._block().terminator = term

    def _goto(self, target):
        self._term(Term("Goto", target=target))

    def _return(self):
        self._term(Term("Return"))

    def _ensure_open(self):
        """Tras un `return`/`break`/`continue`, el codigo siguiente va a un
        bloque muerto en vez de colgar sentencias de un bloque terminado."""
        if self._terminated():
            self._goto_block(self._new_block())

    def _t(self, e):
        if self.tc is None or e is None:
            return None
        old = getattr(self.tc, "cur_type", None)
        if self.owner is not None:
            self.tc.cur_type = self.owner
        try:
            return self.tc.expr(e, self.scope or self.tc.module_scope)
        except Exception:
            return None
        finally:
            self.tc.cur_type = old

    def _bir_t(self, e):
        return to_type(self._t(e))

    def _fn_ret_type(self, fd, owner):
        if fd.ret is not None:
            return _ast_type(fd.ret)
        ty = None
        if self.tc is not None:
            try:
                if owner is None:
                    sym = self.tc.module_scope.lookup(fd.name)
                    ty = getattr(sym, "ty", None)
                else:
                    td = self.tc.type_defs.get(owner)
                    ts = self.tc.resolver.type_scopes.get(id(td)) if td is not None else None
                    sym = ts.lookup(fd.name) if ts is not None else None
                    ty = getattr(sym, "ty", None)
            except Exception:
                ty = None
        if ty is not None and ty[0] == "func" and ty[2] is not None:
            return _tc_type(ty[2])
        return Type("unit")

    def _finish_function(self):
        # Reordenar por DFS desde la entrada (RPO): el borrow checker de
        # babirusas recorre `blocks` en orden lineal y asi ve cada camino en
        # orden de ejecucion aproximado (el bloque de salida de un bucle queda
        # despues de su cuerpo, no antes).
        if not self.fn.blocks:
            return
        by_id = {b.id: b for b in self.fn.blocks}
        order = []
        seen = set()

        def visit(bid):
            if bid is None or bid in seen or bid not in by_id:
                return
            seen.add(bid)
            order.append(bid)
            t = by_id[bid].terminator
            if t is None:
                return
            if t.kind == "Goto":
                visit(t.target)
            elif t.kind == "SwitchInt":
                for _, target in (t.cases or []):
                    visit(target)
                visit(t.otherwise)

        visit(self.fn.entry)
        for b in self.fn.blocks:
            visit(b.id)
        self.fn.blocks = [by_id[bid] for bid in order]

    def lower(self, e):
        """Baja `e` a un Rvalue puro, materializando en un temporal las
        expresiones que necesitan sentencias (llamadas, if/match, `or`, `?`)."""
        if e is None:
            return _const(Type("unit"), None)
        rv = self.rvalue(e)
        if rv is not None:
            return rv
        tmp = self._new_temp(self._t(e))
        self.lower_into(tmp, e)
        return _use(tmp)

    def _lower_fstr(self, e):
        from tools.parser import parse as _parse
        from tools.lexer import decode_escapes
        raw = e.value
        parts = []
        buf = []
        i = 0
        n = len(raw)
        while i < n:
            c = raw[i]
            if c == "{" and i + 1 < n and raw[i + 1] == "{":
                buf.append("{")
                i += 2
                continue
            if c == "}" and i + 1 < n and raw[i + 1] == "}":
                buf.append("}")
                i += 2
                continue
            if c == "{":
                if buf:
                    parts.append(("lit", decode_escapes("".join(buf))))
                    buf = []
                depth = 1
                j = i + 1
                quote = None
                while j < n and depth:
                    ch = raw[j]
                    if quote:
                        if ch == "\\\\":
                            j += 2
                            continue
                        if ch == quote:
                            quote = None
                    elif ch in ("'", '"'):
                        quote = ch
                    elif ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if depth != 0:
                    buf.append(c)
                    i += 1
                    continue
                inner = raw[i + 1:j]
                fmt = None
                d = 0
                q = None
                for k, ch in enumerate(inner):
                    if q:
                        if ch == "\\\\":
                            continue
                        if ch == q:
                            q = None
                    elif ch in ("'", '"'):
                        q = ch
                    elif ch in "([{":
                        d += 1
                    elif ch in ")]}":
                        d -= 1
                    elif ch == ":" and d == 0:
                        fmt = inner[k + 1:]
                        inner = inner[:k]
                        break
                parts.append(("expr", fmt, inner.strip()))
                i = j + 1
                continue
            buf.append(c)
            i += 1
        if buf:
            parts.append(("lit", decode_escapes("".join(buf))))

        # Construir Rvalue concatenado.
        acc = None
        for part in parts:
            if part[0] == "lit":
                rv = _const(Type("str"), part[1])
            else:
                _fmt, inner = part[1], part[2]
                try:
                    prog = _parse(inner)
                    ex = prog.stmts[0].expr
                except Exception:
                    ex = None
                if ex is None:
                    rv = _const(Type("str"), "")
                else:
                    rv = self.lower(ex)
                    if rv is None:
                        rv = _const(Type("str"), "")
                    rv = Rvalue("cast", a=rv, cast_type=Type("str"))
                if acc is None:
                    acc = rv
                else:
                    acc = Rvalue("binop", op="+", a=acc, b=rv)
        if acc is None:
            acc = _const(Type("str"), "")
        return acc

    def _lower_value(self, e):
        """Baja un valor copiando los tipos copiables.

        El BIR no lleva tipos completos en los `Rvalue`; el `cast` explicito
        distingue una copia de un move para el borrow checker.
        """
        rv = self.lower(e)
        if rv.kind == "use" and self._copy_expr(e):
            rv = Rvalue("cast", a=rv, cast_type=to_type(self._t(e)))
        return rv

    def rvalue(self, e):
        """Devuelve un Rvalue, o None si `e` requiere control de flujo."""
        if isinstance(e, A.IntLit):
            return _const(Type("i64"), self._int_value(e.value))
        if isinstance(e, A.FloatLit):
            try:
                return _const(Type("f64"), float(str(e.value).replace("_", "")))
            except ValueError:
                return _const(Type("f64"), 0.0)
        if isinstance(e, (A.StrLit, A.RStrLit, A.MlStrLit)):
            return _const(Type("str"), e.value)
        if isinstance(e, A.FStrLit):
            return self._lower_fstr(e)
        if isinstance(e, A.BytesLit):
            return _const(Type("bytes"), e.value)
        if isinstance(e, A.BoolLit):
            return _bool_const(e.value)
        if isinstance(e, A.NilLit):
            return _const(Type("unit"), None)
        if isinstance(e, A.NameExpr):
            if e.name in ("true", "false"):
                return _bool_const(e.name == "true")
            if e.name == "nil":
                return _const(Type("unit"), None)
            if (self.owner is not None
                    and not any(e.name in sc for sc in self.scopes)
                    and not any(l.name == e.name for l in (self.fn.locals if self.fn else []))
                    and self._is_owner_field(e.name)):
                return _use(_field(_local(self._lookup("self")), e.name))
            return _use(_local(self._lookup(e.name)))
        if isinstance(e, A.SelfExpr):
            return _use(_local(self._lookup("self")))
        if isinstance(e, A.ItExpr):
            return _use(_local(self._lookup("it")))
        if isinstance(e, A.BorrowExpr):
            return self._lower_borrow(e.operand)
        if isinstance(e, A.TupleExpr):
            return Rvalue("aggregate", agg_kind="tuple",
                          items=[self._lower_value(x) for x in (e.items or [])])
        if isinstance(e, A.ListExpr):
            return Rvalue("aggregate", agg_kind="list",
                          items=[self._lower_value(self._arg_value(a)) for a in (e.items or [])])
        if isinstance(e, A.SetExpr):
            return Rvalue("aggregate", agg_kind="set",
                          items=[self._lower_value(self._arg_value(a)) for a in (e.items or [])])
        if isinstance(e, A.MapExpr):
            items = []
            for a in (e.items or []):
                if isinstance(a, A.Arg) and a.is_named and a.label is not None:
                    items.append(self._lower_value(a.label))
                items.append(self._lower_value(self._arg_value(a)))
            return Rvalue("aggregate", agg_kind="map", items=items)
        if isinstance(e, (A.Lambda, A.MoveExpr)):
            return self._lower_lambda(e)
        if isinstance(e, A.UnaryOp):
            if e.op == "?":
                return None
            return Rvalue("unaryop", op=e.op, a=self.lower(e.operand))
        if isinstance(e, A.BinOp):
            if e.op in ("and", "or"):
                return None
            return Rvalue("binop", op=e.op,
                          a=self.lower(e.left), b=self.lower(e.right))
        if isinstance(e, A.Postfix):
            return self._lower_postfix(e)
        if isinstance(e, A.IfExpr) or isinstance(e, A.MatchExpr):
            return None
        if isinstance(e, A.BlockExpr):
            return self.rvalue(e.node)
        raise NotImplementedError(f"expresion no soportada: {type(e).__name__}")

    @staticmethod
    def _int_value(text):
        s = str(text).replace("_", "")
        try:
            return int(s, 0)
        except ValueError:
            try:
                return int(s)
            except ValueError:
                return 0

    @staticmethod
    def _arg_value(a):
        return a.value if isinstance(a, A.Arg) else a

    def _lower_borrow(self, operand):
        place = self.place_of(operand)
        if place is None:
            tmp = self._new_temp(self._t(operand))
            self.lower_into(tmp, operand)
            place = tmp
        target = self._new_temp(Type("ref", elem=place_type_guess(place), ref_kind=0))
        self._emit(Stmt("Borrow", place=place, borrow_kind="shared",
                        borrow_target=target.name))
        return _use(target)
