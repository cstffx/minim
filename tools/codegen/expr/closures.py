from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class ClosuresMixin:
    def _gen_lambda(self, e, code, qname):
        if not isinstance(e, Lambda):
            return False
        name = f"__lambda_{self._lambda_counter}"
        self._lambda_counter += 1
        self._last_lambda_name = name
        # detect captured variables
        param_names = set(p.name for p in e.params)
        captured = set()
        def collect_free(expr, bound):
            if isinstance(expr, NameExpr):
                if expr.name not in bound and expr.name not in param_names and expr.name in self.locals_map.get(qname, {}):
                    captured.add(expr.name)
            elif isinstance(expr, (BinOp,)):
                collect_free(expr.left, bound); collect_free(expr.right, bound)
            elif isinstance(expr, UnaryOp):
                collect_free(expr.operand, bound)
            elif isinstance(expr, Postfix):
                collect_free(expr.base, bound)
                for op in (expr.ops or []):
                    if op[0] == "call":
                        for a in (op[1] or []):
                            collect_free(a.value if isinstance(a, Arg) else a, bound)
                    elif op[0] in ("index", "slice"):
                        if op[1] is not None and not isinstance(op[1], str):
                            collect_free(op[1], bound)
            elif isinstance(expr, IfExpr):
                collect_free(expr.cond, bound); collect_free(expr.then, bound); collect_free(expr.else_, bound)
            elif isinstance(expr, (TupleExpr, ListExpr, MapExpr)):
                for a in (getattr(expr, "items", None) or []):
                    collect_free(a.value if isinstance(a, Arg) else a, bound)
            elif isinstance(expr, MatchExpr):
                collect_free(expr.expr, bound)
                for arm in (expr.arms or []):
                    if arm.guard is not None:
                        collect_free(arm.guard, bound)
                    if isinstance(arm.body, Suite):
                        pass
                    elif arm.body is not None:
                        collect_free(arm.body, bound)
        collect_free(e.body, set())
        captured_list = sorted(captured)
        self._last_lambda_captured = captured_list
        # param types for captured + original
        captured_tc_types = []
        for v in captured_list:
            # find type
            ty = None
            if v in self.float_vars.get(qname, set()):
                ty = FLOAT
            elif v in self.struct_vars.get(qname, set()) or v in self.list_vars.get(qname, set()):
                ty = ("named" if v in self.struct_vars.get(qname, set()) else "list")  # placeholder
            else:
                ty = INT
            # Better: use tc type via scope? Use locals_map? We'll default INT/float/str/ptr
            captured_tc_types.append(ty)
        # Try to get actual tc type from typecheck symbols
        # Use _tc_type of NameExpr
        for i, v in enumerate(captured_list):
            t = self._tc_type(NameExpr(v), qname)
            if t is not None:
                captured_tc_types[i] = t
        # original param types
        param_tc_types = []
        for p in e.params:
            if p.type_ is not None:
                param_tc_types.append(self.tc._atype(p.type_))
            else:
                param_tc_types.append(UNKNOWN)
        # create Type nodes for captured params
        def tc_type_to_type(ty):
            if ty == FLOAT:
                return Type(TypeName("float", []))
            if ty == INT:
                return Type(TypeName("int", []))
            if ty == BOOL:
                return Type(TypeName("bool", []))
            if ty == STR:
                return Type(TypeName("str", []))
            if isinstance(ty, tuple) and ty[0] == "named":
                return Type(TypeName(ty[1], []))
            if isinstance(ty, tuple) and ty[0] == "list":
                return Type(TypeName("list", []))  # not generic but ok
            return None
        captured_params = []
        for v, ty in zip(captured_list, captured_tc_types):
            captured_params.append(Param(None, v, tc_type_to_type(ty), None))
        all_params = captured_params + [p for p in e.params]
        # scope
        scope = self.tc.module_scope.child("func", owner=None)
        self.scope_map[name] = scope
        # define all params
        all_tc_types = captured_tc_types + param_tc_types
        for p, pt in zip(all_params, all_tc_types):
            sym = scope.lookup(p.name)
            if sym is None:
                scope.define(Symbol(p.name, SymKind.PARAM, p, scope))
                sym = scope.lookup(p.name)
            if sym is not None:
                sym.ty = pt
        body_ty = self.tc.expr(e.body, scope)
        fn = FnDecl(name, [], all_params, None, None)
        fn.body = Suite([ExprStmt(e.body)])
        params_wasm = [self._wasm_type(pt) for pt in all_tc_types]
        ret_wasm = [self._wasm_type(body_ty)] if body_ty is not None else []
        typeidx = self.enc.add_type(params_wasm, ret_wasm)
        self.func_typeidx[name] = typeidx
        self._gen_func(fn, None)
        idx = self.func_index[name]
        # store captured var names for call site
        self._last_lambda_captured = captured_list
        code += i32_const(idx)
        return True

    def _gen_move_lambda(self, e, code, qname):
        if not isinstance(e, MoveExpr):
            return False
        lam = e.lambda_
        name = f"__lambda_{self._lambda_counter}"
        self._lambda_counter += 1
        self._last_lambda_name = name
        param_names = set(p.name for p in lam.params)
        captured = set()
        def collect_free2(expr, bound):
            if isinstance(expr, NameExpr):
                if expr.name not in bound and expr.name not in param_names and expr.name in self.locals_map.get(qname, {}):
                    captured.add(expr.name)
            elif isinstance(expr, (BinOp,)):
                collect_free2(expr.left, bound); collect_free2(expr.right, bound)
            elif isinstance(expr, UnaryOp):
                collect_free2(expr.operand, bound)
            elif isinstance(expr, Postfix):
                collect_free2(expr.base, bound)
                for op in (expr.ops or []):
                    if op[0] == "call":
                        for a in (op[1] or []):
                            collect_free2(a.value if isinstance(a, Arg) else a, bound)
                    elif op[0] in ("index", "slice"):
                        if op[1] is not None and not isinstance(op[1], str):
                            collect_free2(op[1], bound)
            elif isinstance(expr, IfExpr):
                collect_free2(expr.cond, bound); collect_free2(expr.then, bound); collect_free2(expr.else_, bound)
            elif isinstance(expr, (TupleExpr, ListExpr, MapExpr)):
                for a in (getattr(expr, "items", None) or []):
                    collect_free2(a.value if isinstance(a, Arg) else a, bound)
            elif isinstance(expr, MatchExpr):
                collect_free2(expr.expr, bound)
                for arm in (expr.arms or []):
                    if arm.guard is not None:
                        collect_free2(arm.guard, bound)
                    if arm.body is not None and not isinstance(arm.body, Suite):
                        collect_free2(arm.body, bound)
        collect_free2(lam.body, set())
        captured_list = sorted(captured)
        param_tc_types = []
        for p in lam.params:
            if p.type_ is not None:
                param_tc_types.append(self.tc._atype(p.type_))
            else:
                param_tc_types.append(UNKNOWN)
        captured_tc_types = []
        for v in captured_list:
            t = self._tc_type(NameExpr(v), qname)
            captured_tc_types.append(t if t is not None else UNKNOWN)
        def tc_type_to_type(ty):
            if ty == FLOAT: return Type(TypeName("float", []))
            if ty == INT: return Type(TypeName("int", []))
            if ty == BOOL: return Type(TypeName("bool", []))
            if ty == STR: return Type(TypeName("str", []))
            if isinstance(ty, tuple) and ty[0] == "named": return Type(TypeName(ty[1], []))
            return None
        captured_params = [Param(None, v, tc_type_to_type(ty), None) for v, ty in zip(captured_list, captured_tc_types)]
        all_params = captured_params + [p for p in lam.params]
        all_tc_types = captured_tc_types + param_tc_types
        scope = self.tc.module_scope.child("func", owner=None)
        self.scope_map[name] = scope
        for p, pt in zip(all_params, all_tc_types):
            sym = scope.lookup(p.name)
            if sym is None:
                scope.define(Symbol(p.name, SymKind.PARAM, p, scope))
                sym = scope.lookup(p.name)
            if sym is not None:
                sym.ty = pt
        body_ty = self.tc.expr(lam.body, scope)
        fn = FnDecl(name, [], all_params, None, None)
        fn.body = Suite([ExprStmt(lam.body)])
        params_wasm = [self._wasm_type(pt) for pt in all_tc_types]
        ret_wasm = [self._wasm_type(body_ty)] if body_ty is not None else []
        typeidx = self.enc.add_type(params_wasm, ret_wasm)
        self.func_typeidx[name] = typeidx
        self._gen_func(fn, None)
        idx = self.func_index[name]
        self._last_lambda_captured = captured_list
        code += i32_const(idx)
        return True
