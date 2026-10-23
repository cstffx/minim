"""Traduccion Minim AST -> BIR (babirusas).

Baja el AST de superficie de `tools/nodes.py` (ya pasado por
`core_ir.elaborate`, es decir, sin `ForStmt`) a la IR de babirusas:
`Function` con `params`, `locals`, `blocks` y terminadores.

Puntos de la traduccion:

- Los enlaces (`let`/`var`) declaran `Local` + `StorageLive`; el valor se baja
  a `Assign(place, Rvalue)` o, si tiene control de flujo (if/match/llamada/
  `or`/`?`), a un bloque con destino (un temporal o la variable).
- Las expresiones se bajan a `Rvalue`; las llamadas son
  `Stmt("Call", call_func, call_args, call_dest, call_target)` con un temporal
  como destino. Las llamadas a metodo llevan el receptor como primer argumento
  y se nombran `tipo.metodo` (p. ej. `list.push`, `Shape.area`).
- `if`/`while`/`match` generan bloques y terminadores `SwitchInt`/`Goto`.
  `break`/`continue` se resuelven contra la pila de bucles; en un `for` ya
  desazucarado (`_for_continue_count`) `continue` salta al incremento.
- `return` escribe en el local de retorno `__ret` y termina con `Return`.
- Los patrones de `match` (literales, variantes, tuplas y `else`) se bajan a
  comparaciones de tag/valor; los bindings se asignan a locales de la rama.
- Las closures se elevan a funciones `nombre$lambdaN`; la expresion queda como
  `Aggregate(kind="closure", const_value=fn, items=[capturas])`.

La integracion con babirusas es `borrow_check_program()` /
`borrow_check_function()`: traducen y ejecutan `BorrowChecker` sobre el BIR.
El codegen WASM sigue consumiendo el AST (Fase 6).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "babirusas", "src"))

from tools import nodes as A
from tools.parser import parse
from tools.typecheck import TC
from tools.core_ir import elaborate

from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)


# ---------- types ----------

def _prim(name):
    return {"int": "i64", "i64": "i64", "float": "f64", "f64": "f64",
            "bool": "bool", "str": "str", "bytes": "bytes",
            "nil": "unit", "unit": "unit"}.get(name)


def _ast_type(t):
    """Tipo de `tools/nodes.py` -> `Type` de BIR."""
    if t is None:
        return Type("unit")
    if isinstance(t, A.Type):
        return _ast_type(t.node)
    if isinstance(t, A.TypeName):
        base = _prim(t.name)
        if base is not None:
            return Type(base)
        if t.name in ("task",) and t.args:
            return Type("task", elem=_ast_type(t.args[0]))
        if t.name == "list" and t.args:
            return Type("list", elem=_ast_type(t.args[0]))
        if t.name == "set" and t.args:
            return Type("set", elem=_ast_type(t.args[0]))
        return Type("struct", name=t.name)
    if isinstance(t, A.TypeList):
        return Type("list", elem=_ast_type(t.inner))
    if isinstance(t, A.TypeMap):
        return Type("map", elem=_ast_type(t.key), fields=[("value", _ast_type(t.val))])
    if isinstance(t, A.TypeSet):
        return Type("set", elem=_ast_type(t.inner))
    if isinstance(t, A.TypeBorrow):
        return Type("ref", elem=_ast_type(t.inner), ref_kind=0)
    if isinstance(t, A.TypeTuple):
        return Type("tuple", fields=[(str(i), _ast_type(x)) for i, x in enumerate(t.items)])
    if isinstance(t, A.TypeFunc):
        return Type("func", fields=[("param", _ast_type(x)) for x in (t.params or [])],
                    elem=_ast_type(t.ret))
    if isinstance(t, A.TypeParen):
        return _ast_type(t.inner) if t.inner is not None else Type("unit")
    if isinstance(t, A.TypeSuffix):
        inner = _ast_type(t.base)
        return Type("opt", elem=inner) if t.suffix == "?" else Type("res", elem=inner)
    return Type("unknown")


def _tc_type(ty):
    """Tipo del typechecker (tuplas `("p", ...)`) -> `Type` de BIR."""
    if ty is None:
        return Type("unknown")
    if isinstance(ty, Type):
        return ty
    kind = ty[0]
    if kind == "p":
        return Type(_prim(ty[1]) or ty[1])
    if kind in ("u", "var"):
        return Type("unknown")
    if kind == "err":
        return Type("err")
    if kind in ("list", "set", "opt", "res", "borrow"):
        return Type(kind, elem=_tc_type(ty[1]), ref_kind=0 if kind == "borrow" else 0)
    if kind == "map":
        return Type("map", elem=_tc_type(ty[1]),
                    fields=[("value", _tc_type(ty[2]))])
    if kind == "tuple":
        items = ty[1] if isinstance(ty[1], (tuple, list)) else ()
        return Type("tuple", fields=[(str(i), _tc_type(x)) for i, x in enumerate(items)])
    if kind == "func":
        params = ty[1] or ()
        return Type("func", fields=[("param", _tc_type(x)) for x in params],
                    elem=_tc_type(ty[2]) if ty[2] is not None else Type("unit"))
    if kind == "named":
        name = ty[1]
        args = ty[2] if len(ty) > 2 else ()
        if name == "task" and args:
            return Type("task", elem=_tc_type(args[0]))
        return Type("struct", name=name)
    return Type("unknown")


def to_type(t):
    """Compatibility helper: acepta tipos de AST, del typechecker o BIR."""
    if isinstance(t, Type):
        return t
    if isinstance(t, tuple) and t and isinstance(t[0], str):
        return _tc_type(t)
    if isinstance(t, (A.Type, A.TypeName, A.TypeList, A.TypeMap, A.TypeSet,
                      A.TypeBorrow, A.TypeTuple, A.TypeFunc, A.TypeParen,
                      A.TypeSuffix)):
        return _ast_type(t)
    return Type("unknown")


def _param_mode(p):
    """Modo de parametro de superficie -> modo BIR."""
    return {"var": "unique", "move": "move"}.get(getattr(p, "mode", None), "shared")


def _bir_copyable(ty):
    """Copiabilidad segun el tipo BIR (conservador: structs no)."""
    if ty is None:
        return False
    if ty.kind in ("i64", "f64", "bool", "str", "bytes", "unit", "ref", "func"):
        return True
    if ty.kind == "tuple":
        return all(_bir_copyable(t) for _, t in ty.fields)
    return False


def _type_label(ty):
    """Nombre corto de un tipo del typechecker, para nombrar metodos."""
    if ty is None:
        return "?"
    kind = ty[0]
    if kind == "p":
        return ty[1]
    if kind == "named":
        return ty[1]
    if kind in ("list", "map", "set", "opt", "res", "tuple", "func"):
        return kind
    return "?"


# ---------- small constructors ----------

def _local(name):
    return Place("local", name=name)


def _field(base, name):
    return Place("field", base=base, field=str(name))


def _index(base, idx):
    return Place("index", base=base, idx=idx)


def _use(place):
    return Rvalue("use", place=place)


def _const(ty, value):
    return Rvalue("const", const_type=ty, const_value=value)


def _int_const(v):
    return _const(Type("i64"), int(v))


def _bool_const(v):
    return _const(Type("bool"), bool(v))


def _cmp_eq(place, value):
    return Rvalue("binop", op="==", a=_use(place), b=value)


# ---------- translator ----------

class Translator:
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

    # ---- infraestructura de bloques/locales ----

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

    # ---- tipos desde el typechecker ----

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

    # ---- rvalues / expresiones ----

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
        if isinstance(e, (A.StrLit, A.RStrLit, A.MlStrLit, A.FStrLit)):
            return _const(Type("str"), e.value)
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

    # ---- llamadas y postfijos ----

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

    # ---- closures ----

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

    # ---- control de flujo y asignaciones ----

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

    def assign_to_place(self, dest, value):
        self.lower_into(dest, value)

    # ---- statements ----

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
        base = _local(self._lookup(spec.name))
        for part in (spec.parts or []):
            if part[0] == "field":
                base = _field(base, part[1])
            elif part[0] == "index":
                base = _index(base, self.lower(part[1]))
        return base

    # ---- enlaces / desestructuracion ----

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

    # ---- if / while / match ----

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
            return self._tag_test(tmp, sum_name, pat.name), False
        if pat.kind in ("tuple", "named_field"):
            return None, True
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


# ---------- helpers de captura ----------

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

def place_type_guess(place):
    return Type("unknown")


class _ProgramTranslator(Translator):
    def run(self, prog):
        top = []
        for st in (prog.stmts or []):
            if isinstance(st, A.FnDecl):
                self.add_function(st)
            elif isinstance(st, A.TypeDecl):
                for m in (st.members or []):
                    if isinstance(m.node, A.FnDecl):
                        self.add_function(m.node, owner=st.name)
            elif isinstance(st, A.TraitDecl):
                continue
            elif isinstance(st, A.UseDecl):
                continue
            else:
                top.append(st)
        if top:
            self.add_top_level(top)
        return self.functions

    def add_top_level(self, stmts):
        # BIR no tiene globales: las sentencias de nivel superior se agrupan
        # en una funcion `main`/`__top` (hello.mim y los tests de Fase 1).
        name = "main" if not any(f.name == "main" for f in self.functions) else "__top"
        fd = A.FnDecl(name, [], [], None, A.Suite(stmts))
        self.add_function(fd)

    def add_function(self, fd, owner=None):
        name = fd.name if owner is None else f"{owner}.{fd.name}"
        fn = Function(name)
        saved = (self.fn, self.block, self.scopes, self.decl_scopes,
                 self.scope, self.owner, self.ret_place, self.ret_type,
                 self.loops, self._span, self._initializing)
        self.fn = fn
        self.owner = owner
        fn.entry = 0
        fn.blocks.append(Block(0))
        self.block = 0
        self.scopes = [{}]
        self.decl_scopes = [[]]
        self.loops = []
        self._initializing = set()
        self.ret_type = self._fn_ret_type(fd, owner)
        fn.ret_type = self.ret_type
        self.scope = self._func_scope(fd)
        self.ret_place = _local(self._new_local(self._fresh("ret"), self.ret_type,
                                                mutable=True))
        fn.ret_local = self.ret_place.name

        for p in (fd.params or []):
            if p.type_ is not None:
                pty = _ast_type(p.type_)
            elif p.name == "self" and owner is not None:
                pty = Type("struct", name=owner)
            else:
                pty = Type("unknown")
            mutable = p.mode == "var"
            bir = self._declare(p.name, pty, mutable)
            self.fn.params.append(Param(bir, pty, mutable, _param_mode(p)))

        implicit = self.ret_type.kind not in ("unit", "unknown")
        self.translate_body(fd.body, self.ret_place if implicit else None)
        if not self._terminated():
            self._return()
        self._finish_function()
        self.functions.append(fn)

        (self.fn, self.block, self.scopes, self.decl_scopes,
         self.scope, self.owner, self.ret_place, self.ret_type,
         self.loops, self._span, self._initializing) = saved

    def _func_scope(self, fd):
        if self.tc is None:
            return None
        sc = self.tc.resolver.func_scopes.get(id(fd))
        if sc is None:
            sc = self.tc.module_scope
        return sc

    def translate_body(self, suite, ret_dest):
        stmts = list(suite.stmts) if hasattr(suite, "stmts") else []
        self.push_scope()
        for i, st in enumerate(stmts):
            self._ensure_open()
            self.scope = self.tc.stmt_scopes.get(id(st), self.scope) \
                if self.tc is not None else self.scope
            dest = None
            if i == len(stmts) - 1 and ret_dest is not None and \
                    isinstance(st, (A.ExprStmt, A.IfStmt, A.MatchStmt)):
                dest = ret_dest
            self.translate_stmt(st, dest)
        self.pop_scope()


def translate_program(prog, tc=None):
    """Traduce un `Program` ya elaborado a una lista de `Function` BIR."""
    return _ProgramTranslator(tc).run(prog)


def translate_module(prog, tc=None):
    """Igual que `translate_program`, pero agrupado por nombre."""
    return {f.name: f for f in translate_program(prog, tc)}


def translate_function(fd, tc=None, owner=None):
    """Traduce una unica funcion (incluye las closures que eleva)."""
    tr = _ProgramTranslator(tc)
    tr.add_function(fd, owner=owner)
    fn = next(f for f in tr.functions if f.name == (fd.name if owner is None
                                                     else f"{owner}.{fd.name}"))
    fn._lifted = [f for f in tr.functions if f is not fn]
    return fn


def borrow_check_function(fn, functions=None):
    from babirusas.src.borrowir.borrow import BorrowChecker
    return BorrowChecker(functions).check(fn)


def borrow_check_translated(prog, tc=None):
    """Traduce el programa y devuelve `(functions, errores)`."""
    from babirusas.src.borrowir.borrow import BorrowChecker
    funcs = translate_program(prog, tc)
    checker = BorrowChecker(funcs)
    errors = []
    for fn in funcs:
        errors += [f"{fn.name}: {e}" for e in checker.check(fn)]
    return funcs, errors


def borrow_check_program(prog, tc=None):
    return borrow_check_translated(prog, tc)[1]


def prepare(source):
    """parse + typecheck + elabora `for` + re-typecheck."""
    program = parse(source)
    tc = TC(program)
    errors = tc.check()
    if errors:
        return program, tc, [str(e) for e in errors]
    elaborate(program, tc)
    tc = TC(program)
    errors = tc.check()
    return program, tc, [str(e) for e in errors]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python3 -m tools.ast_to_bir <file.mim> [--dump]")
        return 1
    path = argv[0]
    dump = "--dump" in argv
    program, tc, errors = prepare(open(path).read())
    if errors:
        print(f"FAIL [typecheck] {path}")
        for e in errors:
            print(f"  {e}")
        return 1
    funcs, borrow_errors = borrow_check_translated(program, tc)
    if dump:
        for fn in funcs:
            print(f"fn {fn.name}(" +
                  ", ".join(f"{p.name}: {p.type.kind}" for p in fn.params) + ")")
            for b in fn.blocks:
                print(f"  bb{b.id}:")
                for s in b.stmts:
                    print(f"    {s.kind}")
                if b.terminator is not None:
                    print(f"    -> {b.terminator.kind}")
    if borrow_errors:
        print(f"FAIL [borrow] {path}")
        for e in borrow_errors:
            print(f"  {e}")
        return 1
    print(f"OK: {len(funcs)} funcion(es) BIR, borrow check limpio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
