from tools import nodes as A
from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)
from tools.bir_types import (
    _prim, _ast_type, _tc_type, to_type, _param_mode, _bir_copyable,
    _type_label, _local, _field, _index, _use, _const, _int_const,
    _bool_const, _cmp_eq, place_type_guess,
)



class StmtMixin:
    def assign_to_place(self, dest, value):
        self.lower_into(dest, value)

    def translate_suite(self, suite, dest=None):
        stmts = list(suite.stmts) if hasattr(suite, "stmts") else []
        self.push_scope()
        for i, st in enumerate(stmts):
            self._ensure_open()
            self.scope = self.tc.stmt_scopes.get(id(st), self.scope) \
                if self.tc is not None else self.scope
            last_dest = dest if i == len(stmts) - 1 else None
            self.translate_stmt(st, last_dest)
        self.pop_scope()

    def translate_stmt(self, st, dest=None):
        self._span = getattr(st, "span", None)
        if isinstance(st, (A.LetDecl, A.LetStmt, A.VarDecl, A.VarStmt)):
            mutable = isinstance(st, (A.VarDecl, A.VarStmt))
            if isinstance(st, A.LetDecl):
                self._bind_one(A.Binding("name", name=st.name, type_=st.type_),
                               st.value, mutable)
            else:
                self._bind_bindings(st.bindings, st.value, mutable)
            return
        if isinstance(st, A.Assign):
            place = self._place_from_spec(st.place)
            if st.op == "=":
                self.lower_into(place, st.value)
            else:
                op = st.op[:-1]
                rv = Rvalue("binop", op=op, a=_use(place),
                            b=self.lower(st.value))
                self._emit(Stmt("Assign", place=place, rvalue=rv))
            return
        if isinstance(st, A.IfStmt):
            self._lower_if(st.cond, st.then, st.elifs, st.else_, dest)
            return
        if isinstance(st, A.WhileStmt):
            self._lower_while(st)
            return
        if isinstance(st, A.MatchStmt):
            self._lower_match(st.expr, st.arms, dest)
            return
        if isinstance(st, A.ReturnStmt):
            if st.value is not None:
                self.lower_into(self.ret_place, st.value)
            self._return()
            return
        if isinstance(st, A.BreakStmt):
            self._loop_jump("__break__")
            return
        if isinstance(st, A.ContinueStmt):
            self._loop_jump("__continue__")
            return
        if isinstance(st, A.SpawnStmt):
            self._eval_discard(A.UnaryOp("spawn", st.expr))
            return
        if isinstance(st, A.AwaitStmt):
            self._eval_discard(A.UnaryOp("await", st.expr))
            return
        if isinstance(st, A.ExprStmt):
            if dest is not None:
                self.lower_into(dest, st.expr)
            else:
                self._eval_discard(st.expr)
            return
        if isinstance(st, A.ForStmt):
            raise NotImplementedError(
                "ForStmt debe venir desazucarado por core_ir.elaborate")
        # Declaraciones sin codigo ejecutable.
        if isinstance(st, (A.UseDecl, A.TypeDecl, A.TraitDecl, A.FnDecl)):
            return
        raise NotImplementedError(f"sentencia no soportada: {type(st).__name__}")

    def _eval_discard(self, e):
        # Un nombre suelto es el "touch" que core_ir usa para alargar
        # prestamos; se materializa para no perder el uso.
        tmp = self._new_temp(self._t(e))
        self.lower_into(tmp, e)

    def _place_from_spec(self, spec):
        if spec.name in ("self",):
            base = _local(self._lookup("self"))
        elif spec.name in ("it",):
            base = _local(self._lookup("it"))
        elif (self.owner is not None
              and not any(spec.name in sc for sc in self.scopes)
              and not any(l.name == spec.name for l in (self.fn.locals if self.fn else []))
              and self._is_owner_field(spec.name)):
            base = _field(_local(self._lookup("self")), spec.name)
        else:
            base = _local(self._lookup(spec.name))
        for part in (spec.parts or []):
            if part[0] == "field":
                base = _field(base, part[1])
            elif part[0] == "index":
                base = _index(base, self.lower(part[1]))
        return base
