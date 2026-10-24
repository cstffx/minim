from tools import nodes as A
from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)
from tools.bir_types import (
    _prim, _ast_type, _tc_type, to_type, _param_mode, _bir_copyable,
    _type_label, _local, _field, _index, _use, _const, _int_const,
    _bool_const, _cmp_eq, place_type_guess,
)



class MatchMixin:
    def _bind_bindings(self, bindings, value, mutable):
        bindings = bindings or []
        if len(bindings) == 1 and bindings[0].kind == "name":
            self._bind_one(bindings[0], value, mutable)
            return
        val_ty = self._t(value)
        tmp = self._new_temp(val_ty)
        self.lower_into(tmp, value)
        if len(bindings) == 1 and bindings[0].kind == "tuple":
            pats = bindings[0].tuple_patterns or []
            elem_types = val_ty[1] if val_ty is not None and val_ty[0] == "tuple" else ()
            for i, p in enumerate(pats):
                ty = elem_types[i] if i < len(elem_types) else None
                self._bind_pattern(p, _field(tmp, i), ty, mutable)
            return
        if len(bindings) == 1 and bindings[0].kind == "variant":
            self._bind_variant(bindings[0], tmp, val_ty, mutable)
            return
        elem_types = val_ty[1] if val_ty is not None and val_ty[0] == "tuple" else ()
        for i, b in enumerate(bindings):
            ty = elem_types[i] if i < len(elem_types) else None
            self._bind_pattern(b, _field(tmp, i), ty, mutable)

    def _bind_one(self, binding, value, mutable):
        ty = binding.type_ if getattr(binding, "type_", None) is not None else None
        bir_ty = _ast_type(ty) if ty is not None else self._bir_t(value)
        bir = self._declare(binding.name, bir_ty, mutable)
        self._initializing.add(bir)
        try:
            self.lower_into(_local(bir), value)
        finally:
            self._initializing.discard(bir)

    def _bind_variant(self, binding, tmp, val_ty, mutable):
        type_name = val_ty[1] if val_ty is not None and val_ty[0] == "named" else None
        fields = self._field_order(type_name, binding.variant) if type_name else []
        for i, p in enumerate(binding.patterns or []):
            if i < len(fields):
                fname = fields[i]
            else:
                fname = str(i)
            fty = self._field_type(type_name, binding.variant, fname)
            self._bind_pattern(p, _field(tmp, fname), fty, mutable)

    def _field_type(self, type_name, variant_name, field_name):
        if self.tc is None or type_name is None:
            return None
        td = self.tc.type_defs.get(type_name)
        if td is None:
            return None
        members = td.members
        if variant_name is not None:
            for m in members:
                if m.kind == "variant" and m.node.name == variant_name:
                    v = m.node
                    fs = v.fields if v.fields else [mm.node for mm in (v.members or [])
                                                    if isinstance(mm.node, A.Field)]
                    for f in fs:
                        if f.name == field_name:
                            return self.tc._atype(f.type_) if f.type_ is not None else None
                    return None
        for m in members:
            if m.kind == "field" and m.node.name == field_name:
                f = m.node
                return self.tc._atype(f.type_) if f.type_ is not None else None
        return None

    def _rebind(self, place, ty):
        # Extraer un campo/valor de un patron es una copia del binding (v0.1
        # prohibe movimientos parciales); `cast` evita que el borrow checker
        # interprete cada rama de un `match` como un move del mismo campo.
        return Rvalue("cast", a=_use(place),
                      cast_type=to_type(ty) if ty is not None else Type("unknown"))

    def _bind_pattern(self, pat, place, ty, mutable):
        """Bindings de patron (match / desestructuracion) a locales."""
        if pat is None:
            return
        kind = getattr(pat, "kind", None)
        if isinstance(pat, A.Binding) and kind == "name":
            bir = self._declare(pat.name, to_type(ty) if ty is not None else Type("unknown"),
                                mutable)
            self._initializing.add(bir)
            self._emit(Stmt("Assign", place=_local(bir), rvalue=self._rebind(place, ty)))
            self._initializing.discard(bir)
            return
        if isinstance(pat, A.Binding) and kind == "tuple":
            for i, p in enumerate(pat.tuple_patterns or []):
                elem = ty[1][i] if ty is not None and ty[0] == "tuple" and i < len(ty[1]) else None
                self._bind_pattern(p, _field(place, i), elem, mutable)
            return
        if isinstance(pat, A.Binding) and kind == "variant":
            self._bind_variant(pat, place, ty, mutable)
            return

        # Patrones de match.
        if kind == "name":
            sum_name = self._sum_type(ty)
            if sum_name is not None and pat.value in self._variant_names(sum_name):
                # `case Circle` es un tag de variante, no un binding.
                return
            bir = self._declare(pat.value, to_type(ty) if ty is not None else Type("unknown"),
                                mutable)
            self._initializing.add(bir)
            self._emit(Stmt("Assign", place=_local(bir), rvalue=self._rebind(place, ty)))
            self._initializing.discard(bir)
            return
        if kind == "tuple":
            for i, p in enumerate(pat.patterns or []):
                elem = ty[1][i] if ty is not None and ty[0] == "tuple" and i < len(ty[1]) else None
                self._bind_pattern(p, _field(place, i), elem, mutable)
            return
        if kind == "named_field":
            fty = self._field_type(ty[1] if ty is not None and ty[0] == "named" else None,
                                   None, pat.field_name)
            self._bind_pattern(pat.sub, _field(place, pat.field_name), fty, mutable)
            return
        if kind == "variant":
            type_name = ty[1] if ty is not None and ty[0] == "named" else None
            fields = self._field_order(type_name, pat.name) if type_name else []
            for i, p in enumerate(pat.patterns or []):
                if p.kind == "named_field":
                    fty = self._field_type(type_name, pat.name, p.field_name)
                    self._bind_pattern(p.sub, _field(place, p.field_name), fty, mutable)
                else:
                    fname = fields[i] if i < len(fields) else str(i)
                    fty = self._field_type(type_name, pat.name, fname)
                    self._bind_pattern(p, _field(place, fname), fty, mutable)
            return
        # literales no ligan nada
        return

    def _lower_if(self, cond, then_suite, elifs, else_suite, dest):
        cond_rv = self.lower(cond)
        then_b = self._new_block()
        else_b = self._new_block()
        join_b = self._new_block()
        self._term(Term("SwitchInt", discr=cond_rv, cases=[(1, then_b)],
                        otherwise=else_b))

        self._goto_block(then_b)
        self._if_branch(then_suite, dest)
        if not self._terminated():
            self._goto(join_b)

        self._goto_block(else_b)
        if elifs:
            ec, es = elifs[0]
            self._lower_if(ec, es, elifs[1:], else_suite, dest)
        elif else_suite is not None:
            self._if_branch(else_suite, dest)
        if not self._terminated():
            self._goto(join_b)

        self._goto_block(join_b)

    def _if_branch(self, body, dest):
        """Rama de `if`: Suite (sentencia) o expresion (`if` como valor)."""
        if body is None:
            return
        if isinstance(body, A.Suite):
            self.translate_suite(body, dest)
        elif dest is not None:
            self.lower_into(dest, body)
        else:
            self._eval_discard(body)

    def _lower_while(self, st):
        cond_b = self._new_block()
        body_b = self._new_block()
        exit_b = self._new_block()
        self._goto(cond_b)

        self._goto_block(cond_b)
        cond_rv = self.lower(st.cond)
        self._term(Term("SwitchInt", discr=cond_rv, cases=[(1, body_b)],
                        otherwise=exit_b))

        body_stmts = list(st.body.stmts) if hasattr(st.body, "stmts") else []
        cont_count = getattr(st, "_for_continue_count", None)
        if cont_count is not None and 0 <= cont_count < len(body_stmts):
            cont_b = self._new_block()
            user_suite = A.Suite(body_stmts[:cont_count])
            inc_suite = A.Suite(body_stmts[cont_count:])
            self._goto_block(body_b)
            self.loops.append((exit_b, cont_b))
            self.translate_suite(user_suite)
            self.loops.pop()
            if not self._terminated():
                self._goto(cont_b)
            self._goto_block(cont_b)
            self.translate_suite(inc_suite)
            if not self._terminated():
                self._goto(cond_b)
        else:
            self._goto_block(body_b)
            self.loops.append((exit_b, cond_b))
            self.translate_suite(st.body)
            self.loops.pop()
            if not self._terminated():
                self._goto(cond_b)

        self._goto_block(exit_b)

    def _sum_type(self, ty):
        if ty is None:
            return None
        if ty[0] == "borrow":
            ty = ty[1]
        if ty[0] != "named" or self.tc is None:
            return None
        td = self.tc.type_defs.get(ty[1])
        if td is None:
            return None
        if any(m.kind == "variant" for m in td.members):
            return ty[1]
        return None

    def _variant_index(self, sum_name, vname):
        if self.tc is None:
            return 0
        td = self.tc.type_defs.get(sum_name)
        if td is None:
            return 0
        idx = 0
        for m in td.members:
            if m.kind == "variant":
                if m.node.name == vname:
                    return idx
                idx += 1
        return 0

    def _tag_test(self, tmp, sum_name, vname):
        tag = Rvalue("unaryop", op="tag", a=_use(tmp))
        return Rvalue("binop", op="==", a=tag,
                      b=_int_const(self._variant_index(sum_name, vname)))

    def _pattern_test(self, pat, tmp, scrut_ty):
        """Devuelve (rvalue_bool, es_catch_all)."""
        if pat is None:
            return None, True
        sum_name = self._sum_type(scrut_ty)
        if pat.kind == "literal":
            value = pat.value
            if scrut_ty is not None and scrut_ty[0] == "p" and scrut_ty[1] == "float":
                try:
                    rv = _const(Type("f64"), float(value))
                except (TypeError, ValueError):
                    rv = _const(Type("f64"), 0.0)
            elif isinstance(value, bool) or (scrut_ty is not None and scrut_ty[0] == "p"
                                              and scrut_ty[1] == "bool"):
                rv = _bool_const(value in (True, "true"))
            elif scrut_ty is not None and scrut_ty[0] == "p" and scrut_ty[1] == "str":
                rv = _const(Type("str"), value)
            elif isinstance(value, str) and not str(value).lstrip("-").isdigit():
                rv = _const(Type("str"), value)
            else:
                rv = _int_const(self._int_value(value))
            return _cmp_eq(tmp, rv), False
        if pat.kind == "name":
            if sum_name is not None and pat.value in self._variant_names(sum_name):
                return self._tag_test(tmp, sum_name, pat.value), False
            return None, True
        if pat.kind == "variant":
            test = self._tag_test(tmp, sum_name, pat.name)
            type_name = scrut_ty[1] if scrut_ty is not None and scrut_ty[0] == "named" else None
            fields = self._field_order(type_name, pat.name) if type_name else []
            sub_tests = []
            catch_all = True
            for i, p in enumerate(pat.patterns or []):
                if p.kind == "named_field":
                    fname = p.field_name
                else:
                    fname = fields[i] if i < len(fields) else str(i)
                fty = self._field_type(type_name, pat.name, fname)
                st, sc = self._pattern_test(p, _field(tmp, fname), fty if fty is not None else scrut_ty)
                if st is not None:
                    sub_tests.append(st)
                catch_all = catch_all and sc
            for st in sub_tests:
                if test is None:
                    test = st
                else:
                    test = Rvalue("binop", op="&", a=test, b=st)
            # Un patron de variante nunca es catch-all (solo casa una variante).
            catch_all = False
            return test, catch_all
        if pat.kind == "tuple":
            catch_all = True
            test = None
            for i, p in enumerate(pat.patterns or []):
                elem = scrut_ty[1][i] if scrut_ty is not None and scrut_ty[0] == "tuple" and i < len(scrut_ty[1]) else None
                st, sc = self._pattern_test(p, _field(tmp, i), elem)
                if st is not None:
                    if test is None:
                        test = st
                    else:
                        test = Rvalue("binop", op="&", a=test, b=st)
                catch_all = catch_all and sc
            if test is not None:
                catch_all = False
            return test, catch_all
        if pat.kind == "named_field":
            fty = None
            if scrut_ty is not None and scrut_ty[0] == "named":
                fty = self._field_type(scrut_ty[1], None, pat.field_name)
            st, sc = self._pattern_test(pat.sub, _field(tmp, pat.field_name), fty)
            if st is not None:
                return st, False
            return None, sc
        return None, True

    def _variant_names(self, sum_name):
        if self.tc is None:
            return set()
        td = self.tc.type_defs.get(sum_name)
        if td is None:
            return set()
        return {m.node.name for m in td.members if m.kind == "variant"}

    def _lower_match(self, scrut_expr, arms, dest):
        scrut_ty = self._t(scrut_expr)
        tmp = self._new_temp(scrut_ty)
        self.lower_into(tmp, scrut_expr)
        join_b = self._new_block()

        arms = list(arms or [])
        fallthrough = True
        for arm in arms:
            if arm.is_else:
                break
            self._ensure_open()
            body_b = self._new_block()
            next_b = self._new_block()
            test, catch_all = self._pattern_test(arm.pattern, tmp, scrut_ty)
            if test is not None:
                self._term(Term("SwitchInt", discr=test, cases=[(1, body_b)],
                                otherwise=next_b))
            else:
                # Patron irrefutable (tupla, product, binding): solo puede
                # continuar a la siguiente rama si tiene guarda.
                self._goto(body_b)
            self._goto_block(body_b)

            self.push_scope()
            self._bind_pattern(arm.pattern, tmp, scrut_ty, False)
            if arm.guard is not None:
                cont_b = self._new_block()
                g = self.lower(arm.guard)
                self._term(Term("SwitchInt", discr=g, cases=[(1, cont_b)],
                                otherwise=next_b))
                self._goto_block(cont_b)
            self._arm_body(arm, dest)
            if not self._terminated():
                self._goto(join_b)
            self.pop_scope()

            if catch_all and arm.guard is None:
                fallthrough = False
                break
            self._goto_block(next_b)

        if fallthrough:
            else_arm = next((a for a in arms if a.is_else), None)
            if else_arm is not None:
                self._arm_body(else_arm, dest)
            if not self._terminated():
                self._goto(join_b)
        self._goto_block(join_b)

    def _arm_body(self, arm, dest):
        body = arm.body
        if body is None:
            return
        if isinstance(body, A.Suite):
            self.translate_suite(body, dest)
        else:
            if dest is not None:
                self.lower_into(dest, body)
            else:
                self._eval_discard(body)
