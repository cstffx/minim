from tools import nodes as A
from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)
from tools.bir_types import (
    _prim, _ast_type, _tc_type, to_type, _param_mode, _bir_copyable,
    _type_label, _local, _field, _index, _use, _const, _int_const,
    _bool_const, _cmp_eq, place_type_guess,
)



class ExprMixin:
    def _lower_lambda(self, e):
        lam = e.lambda_ if isinstance(e, A.MoveExpr) else e
        if not isinstance(lam, A.Lambda):
            raise NotImplementedError("closure no soportada")
        move_closure = isinstance(e, A.MoveExpr)
        fn_name = f"{self.fn.name}$lambda{self._next_lambda()}"
        saved = (self.fn, self.block, self.scopes, self.decl_scopes,
                 self.scope, self.ret_place, self.ret_type, self.loops,
                 self._span, self._initializing)

        captures = self._captures(lam)
        owner_scope = self.scope

        # Las capturas por prestamo se materializan como `Borrow` en el
        # llamante; el agregado de la closure usa el temporal de referencia.
        cap_specs = []
        for name, bir, ty in captures:
            if move_closure:
                item = _use(_local(bir))
                if _bir_copyable(ty):
                    item = Rvalue("cast", a=item, cast_type=ty)
                cap_specs.append((name, bir, ty, item))
            else:
                target = self._new_temp(Type("ref", elem=ty))
                self._emit(Stmt("Borrow", place=_local(bir), borrow_kind="shared",
                                borrow_target=target.name))
                cap_specs.append((name, bir, ty, _use(target)))

        fn = Function(fn_name)
        self.fn = fn
        self.block = self._new_block()
        fn.entry = self.block
        self.scopes = [{}]
        self.decl_scopes = [[]]
        self.loops = []
        self._initializing = set()
        self.ret_type = to_type(self._t(lam.body))
        self.ret_place = _local(self._new_local(self._fresh("ret"), self.ret_type,
                                                mutable=True))

        for p in (lam.params or []):
            pty = _ast_type(p.type_) if p.type_ is not None else Type("unknown")
            mode = _param_mode(p)
            mutable = p.mode == "var"
            self.fn.params.append(Param(self._declare(p.name, pty, mutable),
                                        pty, mutable, mode))
        cap_items = []
        for name, bir, ty, item in cap_specs:
            pty = ty if move_closure else Type("ref", elem=ty)
            mode = "move" if move_closure else "shared"
            self.fn.params.append(Param(self._declare(name, pty), pty, False, mode))
            cap_items.append(item)

        self.scope = owner_scope
        self.lower_into(self.ret_place, lam.body)
        if not self._terminated():
            self._return()
        self._finish_function()
        self.functions.append(fn)

        (self.fn, self.block, self.scopes, self.decl_scopes,
         self.scope, self.ret_place, self.ret_type, self.loops,
         self._span, self._initializing) = saved
        return Rvalue("aggregate",
                      agg_kind="closure_move" if move_closure else "closure",
                      const_value=fn_name, items=cap_items)

    def _next_lambda(self):
        self.counter += 1
        return self.counter

    def _captures(self, lam):
        """Nombres libres de la closure que ya existen como locales."""
        bound = {p.name for p in (lam.params or []) if p.name}
        free = []
        _free_names(lam.body, bound, free)
        out = []
        seen = set()
        for name in free:
            if name in seen:
                continue
            seen.add(name)
            bir = self._lookup(name)
            if bir == name and not any(l.name == bir for l in self.fn.locals):
                continue
            local = next((l for l in self.fn.locals if l.name == bir), None)
            if local is None:
                continue
            out.append((name, bir, local.type))
        return out

    def lower_into(self, dest, e):
        """Baja `e` escribiendo el resultado en `dest` (Place)."""
        if isinstance(e, A.IfExpr):
            self._lower_if(e.cond, e.then, [], e.else_, dest)
            return
        if isinstance(e, A.MatchExpr):
            self._lower_match(e.expr, e.arms, dest)
            return
        if isinstance(e, A.UnaryOp) and e.op == "?":
            self._lower_question(dest, e)
            return
        if isinstance(e, A.BinOp) and e.op in ("or", "and"):
            if self._is_error_fallback(e):
                self._lower_fallback(dest, e)
            else:
                self._lower_logic(dest, e)
            return
        rv = self.rvalue(e)
        if rv is None:
            raise NotImplementedError(f"expresion no soportada: {type(e).__name__}")
        if rv.kind == "use" and self._copy_expr(e):
            # Asignar un tipo copiable copia el valor; un `use` a pelo haria
            # que el borrow checker lo tratase como move.
            rv = Rvalue("cast", a=rv, cast_type=to_type(self._t(e)))
        if (rv.kind == "aggregate" and rv.agg_kind == "closure"
                and dest is not None and dest.kind == "local"):
            captures = [it.place.name for it in rv.items
                        if it.kind == "use" and it.place is not None
                        and it.place.kind == "local"]
            loc = next((l for l in self.fn.locals if l.name == dest.name), None)
            if loc is not None:
                loc.captures = captures
        self._emit(Stmt("Assign", place=dest, rvalue=rv))

    def _copy_expr(self, e):
        if self.tc is None:
            return False
        try:
            ty = self._t(e)
            # Sin monomorfizar no se sabe si un `T` generico es copiable;
            # tratarlo como copia evita falsos moves en funciones genericas.
            if ty is not None and ty[0] in ("u", "var"):
                return True
            return self.tc.is_copy(ty)
        except Exception:
            return False

    def _lower_logic(self, dest, e):
        """`and`/`or` booleanos con cortocircuito."""
        cond = self.lower(e.left)
        eval_b = self._new_block()
        short_b = self._new_block()
        join_b = self._new_block()
        if e.op == "and":
            self._term(Term("SwitchInt", discr=cond, cases=[(1, eval_b)],
                            otherwise=short_b))
            self._goto_block(short_b)
            self._emit(Stmt("Assign", place=dest, rvalue=_bool_const(False)))
        else:
            self._term(Term("SwitchInt", discr=cond, cases=[(1, short_b)],
                            otherwise=eval_b))
            self._goto_block(short_b)
            self._emit(Stmt("Assign", place=dest, rvalue=_bool_const(True)))
        self._goto(join_b)
        self._goto_block(eval_b)
        self.lower_into(dest, e.right)
        self._goto(join_b)
        self._goto_block(join_b)

    def _is_error_fallback(self, e):
        ty = self._t(e.left)
        return ty is not None and ty[0] in ("res", "opt")

    def _is_optional(self, e):
        ty = self._t(e)
        return ty is not None and ty[0] == "opt"

    def _is_result(self, e):
        ty = self._t(e)
        return ty is not None and ty[0] == "res"

    def _lower_fallback(self, dest, e):
        left_ty = self._t(e.left)
        tmp = self._new_temp(left_ty)
        self.lower_into(tmp, e.left)
        ok_b = self._new_block()
        fall_b = self._new_block()
        join_b = self._new_block()
        kind = left_ty[0] if left_ty is not None else "opt"
        test = Rvalue("unaryop", op=("is_ok" if kind == "res" else "is_some"),
                      a=_use(tmp))
        self._term(Term("SwitchInt", discr=test, cases=[(1, ok_b)],
                        otherwise=fall_b))
        self._goto_block(ok_b)
        self._emit(Stmt("Assign", place=dest, rvalue=self._rebind(tmp, left_ty)))
        self._goto(join_b)

        self._goto_block(fall_b)
        self.push_scope()
        if isinstance(e.right, A.OrBlock):
            it_ty = ("p", "str") if kind == "res" else \
                (left_ty[1] if left_ty is not None and len(left_ty) > 1 else None)
            bir = self._declare("it", to_type(it_ty) if it_ty else Type("unknown"))
            msg = Rvalue("unaryop", op="err_msg", a=_use(tmp)) if kind == "res" \
                else _use(tmp)
            self._emit(Stmt("Assign", place=_local(bir), rvalue=msg))
            self.translate_suite(e.right.body, dest)
        elif isinstance(e.right, A.NameExpr) and e.right.name in ("__continue__", "__break__"):
            self._loop_jump(e.right.name)
        else:
            self.lower_into(dest, e.right)
        if not self._terminated():
            self._goto(join_b)
        self.pop_scope()
        self._goto_block(join_b)

    def _lower_question(self, dest, e):
        ty = self._t(e.operand)
        kind = ty[0] if ty is not None else "res"
        tmp = self._new_temp(ty)
        self.lower_into(tmp, e.operand)
        ok_b = self._new_block()
        err_b = self._new_block()
        test = Rvalue("unaryop", op=("is_ok" if kind == "res" else "is_some"),
                      a=_use(tmp))
        self._term(Term("SwitchInt", discr=test, cases=[(1, ok_b)],
                        otherwise=err_b))
        self._goto_block(err_b)
        if self.ret_place is not None:
            self._emit(Stmt("Assign", place=self.ret_place,
                            rvalue=self._rebind(tmp, ty)))
        self._return()
        self._goto_block(ok_b)
        self._emit(Stmt("Assign", place=dest, rvalue=self._rebind(tmp, ty)))

    def _loop_jump(self, which):
        if not self.loops:
            raise NotImplementedError(f"`{which}` fuera de un bucle")
        break_b, continue_b = self.loops[-1]
        self._goto(break_b if which == "__break__" else continue_b)


def _free_names(e, bound, out):
    """Nombres libres de una expresion (sin contar los ligados por `bound`)."""
    if e is None:
        return
    if isinstance(e, A.NameExpr):
        if e.name not in bound and e.name not in ("true", "false", "nil"):
            out.append(e.name)
        return
    if isinstance(e, A.ItExpr) or isinstance(e, A.SelfExpr):
        return
    if isinstance(e, A.Lambda):
        b = set(bound) | {p.name for p in (e.params or []) if p.name}
        _free_names(e.body, b, out)
        return
    if isinstance(e, A.MoveExpr):
        _free_names(e.lambda_, bound, out)
        return
    if isinstance(e, A.BinOp):
        _free_names(e.left, bound, out)
        _free_names(e.right, bound, out)
        return
    if isinstance(e, A.UnaryOp):
        _free_names(e.operand, bound, out)
        return
    if isinstance(e, A.BorrowExpr):
        _free_names(e.operand, bound, out)
        return
    if isinstance(e, A.Postfix):
        _free_names(e.base, bound, out)
        for op in (e.ops or []):
            if op[0] == "call":
                for a in (op[1] or []):
                    _free_names(a.value if isinstance(a, A.Arg) else a, bound, out)
            elif op[0] in ("index", "slice"):
                for part in op[1:]:
                    if part is not None and not isinstance(part, str):
                        _free_names(part, bound, out)
        return
    if isinstance(e, (A.TupleExpr, A.ListExpr, A.MapExpr, A.SetExpr)):
        for a in (e.items or []):
            if isinstance(a, A.Arg):
                _free_names(a.label, bound, out)
                _free_names(a.value, bound, out)
            else:
                _free_names(a, bound, out)
        return
    if isinstance(e, A.IfExpr):
        _free_names(e.cond, bound, out)
        _free_names(e.then, bound, out)
        _free_names(e.else_, bound, out)
        return
    if isinstance(e, A.MatchExpr):
        _free_names(e.expr, bound, out)
        for arm in (e.arms or []):
            b = set(bound)
            _pattern_names(arm.pattern, b)
            _free_names(arm.guard, b, out)
            if isinstance(arm.body, A.Suite):
                for st in arm.body.stmts:
                    _free_stmt(st, b, out)
            else:
                _free_names(arm.body, b, out)
        return
    if isinstance(e, A.OrBlock):
        for st in e.body.stmts:
            _free_stmt(st, bound, out)
        return


def _pattern_names(pat, bound):
    if pat is None:
        return
    if getattr(pat, "kind", None) == "name":
        bound.add(pat.value)
    for p in (getattr(pat, "patterns", None) or []):
        _pattern_names(p, bound)
    if getattr(pat, "sub", None) is not None:
        _pattern_names(pat.sub, bound)


def _free_stmt(st, bound, out):
    if isinstance(st, (A.LetStmt, A.VarStmt)):
        _free_names(st.value, bound, out)
        for b in (st.bindings or []):
            _binding_names(b, bound)
    elif isinstance(st, A.Assign):
        _free_names(st.value, bound, out)
    elif isinstance(st, A.ExprStmt):
        _free_names(st.expr, bound, out)
    elif isinstance(st, A.ReturnStmt):
        _free_names(st.value, bound, out)
    elif isinstance(st, A.IfStmt):
        _free_names(st.cond, bound, out)
        for s in st.then.stmts:
            _free_stmt(s, bound, out)
        for ec, es in (st.elifs or []):
            _free_names(ec, bound, out)
            for s in es.stmts:
                _free_stmt(s, bound, out)
        if st.else_ is not None:
            for s in st.else_.stmts:
                _free_stmt(s, bound, out)
    elif isinstance(st, A.WhileStmt):
        _free_names(st.cond, bound, out)
        for s in st.body.stmts:
            _free_stmt(s, bound, out)
    elif isinstance(st, A.MatchStmt):
        _free_names(st.expr, bound, out)
        for arm in (st.arms or []):
            b = set(bound)
            _pattern_names(arm.pattern, b)
            _free_names(arm.guard, b, out)
            if isinstance(arm.body, A.Suite):
                for s in arm.body.stmts:
                    _free_stmt(s, b, out)
            else:
                _free_names(arm.body, b, out)
    elif isinstance(st, (A.SpawnStmt, A.AwaitStmt)):
        _free_names(st.expr, bound, out)


def _binding_names(b, bound):
    kind = getattr(b, "kind", None)
    if kind == "name" and b.name:
        bound.add(b.name)
    for p in (getattr(b, "patterns", None) or []):
        _pattern_names(p, bound)
    for p in (getattr(b, "tuple_patterns", None) or []):
        _pattern_names(p, bound)


# ---------- entry points ----------
