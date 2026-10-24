from tools import nodes as A
from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)
from tools.bir_types import (
    _prim, _ast_type, _tc_type, to_type, _param_mode, _bir_copyable,
    _type_label, _local, _field, _index, _use, _const, _int_const,
    _bool_const, _cmp_eq, place_type_guess,
)



class PlaceMixin:
    def place_of(self, e):
        """Convierte una expresion de lugar (nombre, campo, indice) en Place."""
        if isinstance(e, A.NameExpr):
            return _local(self._lookup(e.name))
        if isinstance(e, A.SelfExpr):
            return _local(self._lookup("self"))
        if isinstance(e, A.ItExpr):
            return _local(self._lookup("it"))
        if isinstance(e, A.Postfix):
            base = self.place_of(e.base)
            if base is None:
                return None
            for op in (e.ops or []):
                if op[0] == "field":
                    base = _field(base, op[1])
                elif op[0] == "index":
                    base = _index(base, self.lower(op[1]))
                else:
                    return None
            return base
        return None

    def _is_value_name(self, name):
        """True si `name` es un local/parametro (no un tipo, modulo o fn)."""
        if name in ("self", "it"):
            return True
        for sc in reversed(self.scopes):
            if name in sc:
                return True
        return any(l.name == name for l in self.fn.locals)

    def _lower_postfix(self, e):
        # Aplanar la cadena de postfijos: primero el base y luego cada op.
        ops = []
        cur = e
        while isinstance(cur, A.Postfix):
            ops = list(cur.ops or []) + ops
            cur = cur.base
        base_expr = cur
        state_expr = base_expr

        if isinstance(base_expr, A.NameExpr) and not self._is_value_name(base_expr.name):
            # `mod.fn`, `Tipo.Variante`, `Tipo(...)`, funcion suelta.
            if base_expr.name in ("true", "false", "nil"):
                place, rv, symbol = None, self.rvalue(base_expr), None
            else:
                place, rv, symbol = None, None, base_expr.name
        else:
            place, rv, symbol = self.place_of(base_expr), None, None
            if place is None:
                rv = self.rvalue(base_expr)
                if rv is None:
                    place = self._new_temp(self._t(base_expr))
                    self.lower_into(place, base_expr)
        typeargs = []
        method_name = None
        subject_expr = state_expr

        def value_rv():
            if place is not None:
                return _use(place)
            if rv is not None:
                return rv
            if symbol is not None:
                return _use(_local(symbol))
            return _const(Type("unit"), None)

        def materialize():
            nonlocal place, rv, symbol
            tmp = self._new_temp(self._t(state_expr))
            self._emit(Stmt("Assign", place=tmp, rvalue=value_rv()))
            place, rv, symbol = tmp, None, None
            return tmp

        for oi, op in enumerate(ops):
            kind = op[0]
            if kind == "field":
                fname = op[1]
                is_method = oi + 1 < len(ops) and ops[oi + 1][0] == "call"
                method_name = fname
                subject_expr = state_expr
                if is_method and place is not None:
                    # `v.push(x)`: el receptor es `v`, no el campo `v.push`.
                    state_expr = A.Postfix(state_expr, [op])
                    continue
                if place is not None:
                    place = _field(place, fname)
                elif symbol is not None:
                    symbol = f"{symbol}.{fname}"
                else:
                    place = _field(materialize(), fname)
                state_expr = A.Postfix(state_expr, [op])
            elif kind == "index":
                idx = self.lower(op[1])
                subject_expr = state_expr
                if place is None:
                    materialize()
                place = _index(place, idx)
                state_expr = A.Postfix(state_expr, [op])
            elif kind == "slice":
                start = self.lower(op[1]) if op[1] is not None else None
                end = self.lower(op[2]) if op[2] is not None else None
                args = [value_rv()]
                if start is not None:
                    args.append(start)
                if end is not None:
                    args.append(end)
                whole = A.Postfix(state_expr, [op])
                tmp = self._new_temp(self._t(whole))
                self._emit(Stmt("Call", call_func="slice", call_args=args,
                                call_dest=tmp, call_target=self.block))
                place, rv, symbol = tmp, None, None
                state_expr = whole
            elif kind == "as":
                target_ty = _ast_type(op[1])
                rv = Rvalue("cast", a=value_rv(), cast_type=target_ty)
                place, symbol = None, None
                state_expr = A.Postfix(state_expr, [op])
            elif kind == "typeargs":
                typeargs = op[1] or []
            elif kind == "call":
                whole = A.Postfix(state_expr, [op])
                args = op[1] or []
                rv = self._lower_call(symbol, place, whole, args, typeargs,
                                      subject_expr, method_name)
                place, symbol, method_name = None, None, None
                state_expr = whole
            else:
                raise NotImplementedError(f"postfijo no soportado: {kind}")

        if rv is not None:
            return rv
        if place is not None:
            return _use(place)
        if symbol is not None:
            return _use(_local(symbol))
        return _const(Type("unit"), None)

    def _lower_call(self, symbol, recv_place, call_expr, args, typeargs,
                    recv_expr, method_name=None):
        ret_ty = self._t(call_expr)
        arg_rvs = [self._lower_value(self._arg_value(a)) for a in args]

        if symbol is not None:
            # `mod.fn(...)`, `Tipo.Metodo(...)`, `Tipo.Variante(...)`,
            # constructor de producto y funciones/builtins sueltos.
            parts = symbol.split(".")
            first = parts[0]
            last = parts[-1]
            if first in ("list", "map", "set") and len(parts) == 1:
                return self._aggregate_ctor(first, arg_rvs, typeargs, call_expr)
            if first in self._struct_names() and len(parts) == 1:
                return self._product_ctor(first, args, call_expr)
            if first in self._struct_names() and len(parts) == 2:
                if self._is_variant(first, last):
                    return self._variant_ctor(first, last, args, call_expr)
                # Metodo "estatico": T.m(...)
                return self._emit_call(symbol, arg_rvs, ret_ty)
            # Funcion normal (posiblemente ya monomorfizada) o builtin.
            return self._emit_call(symbol, arg_rvs, ret_ty)

        # Llamada a metodo: receptor como primer argumento.
        if recv_place is not None:
            recv_rv = _use(recv_place)
            recv_ty = self._t(recv_expr)
        else:
            recv_rv = self.lower(recv_expr)
            recv_ty = self._t(recv_expr)
        if method_name:
            label = _type_label(recv_ty)
            func = f"{label}.{method_name}" if label != "?" else method_name
            return self._emit_call(func, [recv_rv] + arg_rvs, ret_ty)
        # Valor llamable (closure guardada en un local).
        return self._emit_call("__call", [recv_rv] + arg_rvs, ret_ty)

    def _emit_call(self, func, args, ret_ty):
        tmp = self._new_temp(ret_ty)
        self._emit(Stmt("Call", call_func=func, call_args=args, call_dest=tmp,
                        call_target=self.block))
        return _use(tmp)

    def _struct_names(self):
        if self.tc is None:
            return set()
        return set(self.tc.type_defs)

    def _is_variant(self, type_name, variant_name):
        if self.tc is None:
            return False
        td = self.tc.type_defs.get(type_name)
        if td is None:
            return False
        return any(m.kind == "variant" and m.node.name == variant_name
                   for m in td.members)

    def _field_order(self, type_name, variant_name=None):
        if self.tc is None:
            return []
        td = self.tc.type_defs.get(type_name)
        if td is None:
            return []
        if variant_name is None:
            return [m.node.name for m in td.members if m.kind == "field"]
        for m in td.members:
            if m.kind == "variant" and m.node.name == variant_name:
                v = m.node
                fs = v.fields if v.fields else [mm.node for mm in (v.members or [])
                                                if isinstance(mm.node, A.Field)]
                return [f.name for f in fs]
        return []

    def _ordered_args(self, field_names, args):
        """Ordena argumentos con nombre segun el orden de campos del tipo."""
        positional = []
        named = {}
        for a in args:
            if isinstance(a, A.Arg) and a.is_named and isinstance(a.label, A.NameExpr):
                named[a.label.name] = a.value
            elif isinstance(a, A.Arg):
                positional.append(a.value)
            else:
                positional.append(a)
        out = []
        pi = 0
        for fname in field_names:
            if fname in named:
                out.append(self._lower_value(named[fname]))
            elif pi < len(positional):
                out.append(self._lower_value(positional[pi]))
                pi += 1
        while pi < len(positional):
            out.append(self._lower_value(positional[pi]))
            pi += 1
        return out

    def _product_ctor(self, type_name, args, call_expr):
        fields = self._field_order(type_name)
        items = self._ordered_args(fields, args) if fields else \
            [self._lower_value(self._arg_value(a)) for a in args]
        return Rvalue("aggregate", agg_kind="struct", const_value=type_name,
                      items=items)

    def _variant_ctor(self, type_name, variant_name, args, call_expr):
        fields = self._field_order(type_name, variant_name)
        items = self._ordered_args(fields, args) if fields else \
            [self._lower_value(self._arg_value(a)) for a in args]
        return Rvalue("aggregate", agg_kind="variant",
                      const_value=f"{type_name}.{variant_name}", items=items)

    def _aggregate_ctor(self, name, arg_rvs, typeargs, call_expr):
        if name == "map":
            return Rvalue("aggregate", agg_kind="map", items=[])
        if name == "set":
            return Rvalue("aggregate", agg_kind="set", items=[])
        if name == "list":
            return Rvalue("aggregate", agg_kind="list", items=arg_rvs)
        return Rvalue("aggregate", agg_kind=name, items=arg_rvs)

    @staticmethod
    def _builtins():
        return {"print", "eprint", "assert", "panic", "drop", "copy",
                "len", "min", "max", "abs", "range", "err",
                "int", "float", "str"}
