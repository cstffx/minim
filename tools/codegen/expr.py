from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from tools.resolve import Resolver, Scope, Symbol, SymKind

class ExprMixin:
        def _gen_expr(self, e, code, qname):
            if isinstance(e, IntLit):
                code += i64_const(int(e.value))
            elif isinstance(e, FloatLit):
                code += f64_const(float(e.value))
            elif isinstance(e, BoolLit):
                code += i64_const(1 if e.value else 0)
            elif isinstance(e, StrLit):
                ptr = self.str_offsets.get(id(e), 0)
                code += i32_const(ptr)
            elif isinstance(e, SelfExpr):
                code += local_get(0)
            elif isinstance(e, BorrowExpr):
                self._gen_expr(e.operand, code, qname)
            elif isinstance(e, IfExpr):
                cond = e.cond
                self._gen_expr(cond, code, qname)
                if isinstance(cond, FloatLit):
                    code += f64_const(0.0)
                    code += F64_NE
                elif isinstance(cond, (NameExpr, BoolLit, IntLit)) or (isinstance(cond, BinOp) and cond.op in ("and", "or")) or (isinstance(cond, UnaryOp) and cond.op == "not"):
                    code += i64_const(0)
                    code += I64_NE
                then_ty = self._tc_type(e.then, qname)
                wtype = self._wasm_type(then_ty) if then_ty is not None else WasmEncoder.I64
                code += IF(wtype)
                self._gen_expr(e.then, code, qname)
                code += ELSE
                self._gen_expr(e.else_, code, qname)
                code += END
                return
            elif isinstance(e, Lambda):
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
                return
            elif isinstance(e, MoveExpr) and isinstance(e.lambda_, Lambda):
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
                return
            elif isinstance(e, MatchExpr):
                self._gen_match_core(e.expr, e.arms, code, qname, None)
                return
            elif isinstance(e, TupleExpr):
                items = e.items or []
                its = [ (a.value if isinstance(a, Arg) else a) for a in items ]
                # determine types
                ttypes = [ self._tc_type(x, qname) for x in its ]
                # build layout
                tup_ty = ("tuple", tuple(ttypes))
                size, fields = self._tuple_layout(tup_ty)
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.tmp_global)
                code += GLOBAL_GET(self.heap_global)
                code += i32_const(size)
                code += bytes([0x6A])
                code += GLOBAL_SET(self.heap_global)
                # save previous tuple base
                code += GLOBAL_GET(self.tuple_base_global)
                code += GLOBAL_SET(self.tuple_save_global)
                # set tuple base = new base
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_SET(self.tuple_base_global)
                for i, (expr, tt) in enumerate(zip(its, ttypes)):
                    code += GLOBAL_GET(self.tuple_base_global)
                    self._gen_expr(expr, code, qname)
                    wt, off, _ = fields[i]
                    if wt == WasmEncoder.F64 and not self._is_float(expr, qname):
                        code += bytes([0xB9])
                    if wt == WasmEncoder.F64:
                        code += bytes([0x39])
                        code += _uleb128_static(3)
                    elif wt == WasmEncoder.I32:
                        code += bytes([0x36])
                        code += _uleb128_static(2)
                    else:
                        code += bytes([0x37])
                        code += _uleb128_static(3)
                    code += _uleb128_static(off)
                code += GLOBAL_GET(self.tuple_base_global)
                # restore tuple base
                code += GLOBAL_GET(self.tuple_save_global)
                code += GLOBAL_SET(self.tuple_base_global)
                return
            elif isinstance(e, MapExpr):
                items = e.items or []
                has_named = any(isinstance(a, Arg) and a.is_named for a in items)
                # determine value type
                val_tys = [self._tc_type((a.value if isinstance(a, Arg) else a), qname) for a in items]
                vt = val_tys[0] if val_tys else UNKNOWN
                for t in val_tys[1:]:
                    if t != vt:
                        vt = UNKNOWN
                is_float_val = (vt == FLOAT)
                n = len(items)
                cap = n if n > 4 else 4
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.tmp_global)  # header
                code += GLOBAL_GET(self.heap_global)
                code += i32_const(16)
                code += bytes([0x6A])
                code += GLOBAL_GET(self.heap_global)
                code += i32_const(cap * 16)
                code += bytes([0x6A])  # heap += 16 + cap*16
                code += GLOBAL_SET(self.heap_global)
                # store len
                code += GLOBAL_GET(self.tmp_global)
                code += i32_const(n)
                code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
                # store cap
                code += GLOBAL_GET(self.tmp_global)
                code += i32_const(cap)
                code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
                # store data ptr = tmp+16
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += i32_const(16)
                code += bytes([0x6A])
                code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
                # store entries
                for i, a in enumerate(items):
                    val = a.value if isinstance(a, Arg) else a
                    # determine key value on stack as i64
                    key_is_str = False
                    if isinstance(a, Arg) and a.is_named:
                        if isinstance(a.label, NameExpr):
                            key_str = a.label.name
                            key_ptr = self.str_value_offsets.get(key_str, 0)
                            if key_str not in self.str_value_offsets:
                                b = key_str.encode("utf-8") + b"\x00"
                                # allocate at current offset? use str_value_offsets with new offset via a large base? 
                                # We'll reuse existing if present; otherwise 0.
                                key_ptr = self.str_value_offsets.get(key_str, 0)
                            code += GLOBAL_GET(self.tmp_global)
                            code += i32_const(16)
                            code += bytes([0x6A])
                            code += i32_const(i * 16)
                            code += bytes([0x6A])
                            code += i32_const(key_ptr)
                            code += bytes([0xAC])
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                            key_is_str = True
                        elif isinstance(a.label, IntLit):
                            code += GLOBAL_GET(self.tmp_global)
                            code += i32_const(16)
                            code += bytes([0x6A])
                            code += i32_const(i * 16)
                            code += bytes([0x6A])
                            code += i64_const(int(a.label.value))
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                        elif isinstance(a.label, StrLit):
                            code += GLOBAL_GET(self.tmp_global)
                            code += i32_const(16)
                            code += bytes([0x6A])
                            code += i32_const(i * 16)
                            code += bytes([0x6A])
                            code += i32_const(self.str_value_offsets.get(a.label.value, 0))
                            code += bytes([0xAC])
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                            key_is_str = True
                        else:
                            code += GLOBAL_GET(self.tmp_global)
                            code += i32_const(16)
                            code += bytes([0x6A])
                            code += i32_const(i * 16)
                            code += bytes([0x6A])
                            code += i64_const(0)
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                    else:
                        # positional: skip
                        continue
                    # store value
                    code += GLOBAL_GET(self.tmp_global)
                    code += i32_const(16)
                    code += bytes([0x6A])
                    code += i32_const(i * 16 + 8)
                    code += bytes([0x6A])
                    self._gen_expr(val, code, qname)
                    vty = self._tc_type(val, qname)
                    if vty == FLOAT:
                        code += bytes([0xBD])
                    elif isinstance(vty, tuple) and vty[0] in ("named", "list", "tuple"):
                        code += bytes([0xAC])
                    code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.tmp_global)
                return
            elif isinstance(e, ListExpr):
                elem_ty = self._elem_type(e, qname)
                is_float = (elem_ty == FLOAT)
                is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
                # header ptr = current heap
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.tmp_global)
                # reserve header (16 bytes)
                code += GLOBAL_GET(self.heap_global)
                code += i32_const(16)
                code += bytes([0x6A])
                code += GLOBAL_SET(self.heap_global)
                # data ptr = current heap
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.list_tmp_global)
                # reserve data (cap * 8)
                code += GLOBAL_GET(self.heap_global)
                code += i32_const(cap * 8)
                code += bytes([0x6A])
                code += GLOBAL_SET(self.heap_global)
                # store len
                code += GLOBAL_GET(self.tmp_global)
                code += i32_const(n)
                code += bytes([0x36])  # i32.store
                code += _uleb128_static(2)  # align 4
                code += _uleb128_static(0)
                # store cap
                code += GLOBAL_GET(self.tmp_global)
                code += i32_const(cap)
                code += bytes([0x36])
                code += _uleb128_static(2)
                code += _uleb128_static(4)
                # store data ptr
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += bytes([0x36])
                code += _uleb128_static(2)
                code += _uleb128_static(8)
                # store items
                for i, a in enumerate(items):
                    val = a.value if isinstance(a, Arg) else a
                    code += GLOBAL_GET(self.list_tmp_global)
                    code += i32_const(i * 8)
                    code += bytes([0x6A])
                    self._gen_expr(val, code, qname)
                    if is_float:
                        # val is f64 already
                        code += bytes([0x39])  # f64.store
                        code += _uleb128_static(3)
                        code += _uleb128_static(0)
                    elif is_ptr:
                        # val is i32 -> i64
                        code += bytes([0xAC])  # i64.extend_i32_u
                        code += bytes([0x37])  # i64.store
                        code += _uleb128_static(3)
                        code += _uleb128_static(0)
                    else:
                        code += bytes([0x37])  # i64.store
                        code += _uleb128_static(3)
                        code += _uleb128_static(0)
                # result = header ptr
                code += GLOBAL_GET(self.tmp_global)
            elif isinstance(e, NameExpr):
                if e.name == "pi":
                    code += f64_const(3.141592653589793)
                    return
                if e.name == "e":
                    code += f64_const(2.718281828459045)
                    return
                if e.name in self.locals_map[qname]:
                    code += local_get(self.locals_map[qname][e.name])
                else:
                    # method field access without self.
                    field_info = None
                    if "." in qname:
                        cls = qname.split(".")[0]
                        for (f, wtype, off, fty, fdefault) in self.struct_layouts.get(cls, []):
                            if f == e.name:
                                field_info = (wtype, off)
                                break
                    if field_info is not None:
                        code += local_get(0)  # self
                        wtype, off = field_info
                        if wtype == WasmEncoder.F64:
                            code += bytes([0x2B])
                        elif wtype == WasmEncoder.I32:
                            code += bytes([0x28])
                        else:
                            code += bytes([0x29])
                        code += _uleb128_static(3)
                        code += _uleb128_static(off)
                    else:
                        _unsupported(f"la variable/nombre '{e.name}' (no es local ni campo conocido)", e)
            elif isinstance(e, BinOp):
                op = e.op
                if op == "or":
                    left_ty = self._tc_type(e.left, qname)
                    if isinstance(left_ty, tuple) and left_ty[0] == "res":
                        self._gen_expr(e.left, code, qname)
                        code += GLOBAL_GET(self.err_flag_global)
                        code += bytes([0x04, 0x40])  # if err
                        code += i32_const(0)
                        code += GLOBAL_SET(self.err_flag_global)
                        self._gen_expr(e.right, code, qname)
                        code += bytes([0x05])  # else
                        code += bytes([0x0B])
                    elif isinstance(left_ty, tuple) and left_ty[0] == "opt":
                        self._gen_expr(e.left, code, qname)
                        code += I64_EQZ
                        code += bytes([0x04, 0x40])  # if nil
                        code += DROP
                        self._gen_expr(e.right, code, qname)
                        code += bytes([0x05])  # else
                        code += bytes([0x0B])
                    else:
                        self._gen_expr(e.left, code, qname)
                        if isinstance(e.left, (BinOp, Postfix, UnaryOp)):
                            code += bytes([0xAC])
                        code += I64_EQZ
                        code += bytes([0x04, 0x40])  # if left==0
                        self._gen_expr(e.right, code, qname)
                        if isinstance(e.right, (BinOp, Postfix, UnaryOp)):
                            code += bytes([0xAC])
                        code += bytes([0x05])  # else
                        code += i64_const(1)
                        code += bytes([0x0B])
                    return
                if op == "and":
                    self._gen_expr(e.left, code, qname)
                    if isinstance(e.left, (NameExpr, BoolLit, IntLit)):
                        code += i64_const(0)
                        code += I64_NE
                    elif isinstance(e.left, FloatLit):
                        code += f64_const(0.0)
                        code += F64_NE
                    code += IF(BLK_I64)
                    self._gen_expr(e.right, code, qname)
                    if isinstance(e.right, (NameExpr, BoolLit, IntLit)):
                        code += i64_const(0)
                        code += I64_NE
                        code += bytes([0xAC])  # i64.extend_i32_u (bool i32 -> i64)
                    elif isinstance(e.right, FloatLit):
                        code += f64_const(0.0)
                        code += F64_NE
                        code += bytes([0xAC])
                    else:
                        # right is comparison (i32) -> i64
                        code += bytes([0xAC])
                    code += ELSE
                    code += i64_const(0)
                    code += END
                    return
                f = self._is_float(e, qname)
                self._gen_expr(e.left, code, qname)
                self._gen_expr(e.right, code, qname)
                op = e.op
                if f:
                    if op == "+":
                        code += F64_ADD
                    elif op == "-":
                        code += F64_SUB
                    elif op == "*":
                        code += F64_MUL
                    elif op == "/":
                        code += F64_DIV
                    elif op == "<=":
                        code += F64_LE
                    elif op == ">=":
                        code += F64_GE
                    elif op == "<":
                        code += F64_LT
                    elif op == ">":
                        code += F64_GT
                    elif op == "==":
                        code += F64_EQ
                    elif op == "!=":
                        code += F64_NE
                    else:
                        _unsupported(f"el operador binario '{op}' (float)", e)
                else:
                    if op == "+":
                        code += I64_ADD
                    elif op == "-":
                        code += I64_SUB
                    elif op == "*":
                        code += I64_MUL
                    elif op == "/":
                        code += I64_DIV_S
                    elif op == "%":
                        code += I64_REM_S
                    elif op == "<=":
                        code += I64_LE_S
                    elif op == ">=":
                        code += I64_GE_S
                    elif op == "<":
                        code += I64_LT_S
                    elif op == ">":
                        code += I64_GT_S
                    elif op == "==":
                        code += I64_EQ
                    elif op == "!=":
                        code += I64_NE
                    else:
                        _unsupported(f"el operador binario '{op}'", e)
            elif isinstance(e, UnaryOp):
                if e.op == "-":
                    if self._is_float(e, qname):
                        code += f64_const(0.0)
                        self._gen_expr(e.operand, code, qname)
                        code += F64_SUB
                    else:
                        code += i64_const(0)
                        self._gen_expr(e.operand, code, qname)
                        code += I64_SUB
                elif e.op == "?":
                    self._gen_expr(e.operand, code, qname)
                    # if error flag set, return 0 (propagate)
                    code += GLOBAL_GET(self.err_flag_global)
                    code += bytes([0x45])  # i32.eqz
                    code += bytes([0x04, 0x40])  # if void
                    # error: push default 0 and return
                    code += i64_const(0)
                    code += RETURN
                    code += bytes([0x0B])  # end if
                elif e.op == "not":
                    self._gen_expr(e.operand, code, qname)
                    if isinstance(e.operand, (NameExpr, BoolLit, IntLit)):
                        code += i64_const(0)
                        code += I64_EQ
                        code += bytes([0xAC])
                    elif isinstance(e.operand, FloatLit):
                        code += f64_const(0.0)
                        code += F64_EQ
                        code += bytes([0xAC])
                    elif isinstance(e.operand, (BinOp, Postfix, UnaryOp)):
                        code += bytes([0xAC])
                        code += i64_const(0)
                        code += I64_EQ
                        code += bytes([0xAC])
                    else:
                        code += I64_EQZ
                        code += bytes([0xAC])
                else:
                    _unsupported(f"el operador unario '{e.op}'", e)
            elif isinstance(e, Postfix):
                # str methods (simple and chained)
                if (e.ops and e.ops[-1][0] == "call" and e.ops[0][0] == "field"):
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if base_ty == STR and e.ops[0][1] in ("len", "upper", "lower"):
                        recv = e.base
                        method = e.ops[0][1]
                    else:
                        pass
                        # reuse implementation by setting e.base? We'll inline with recv.
                        if method == "len":
                            self._gen_expr(recv, code, qname)
                            code += GLOBAL_SET(self.slice_base_global)
                            code += i64_const(0)
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x02, 0x40])
                            code += bytes([0x03, 0x40])
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])
                            code += bytes([0x45])
                            code += bytes([0x0D, 0x01])
                            code += GLOBAL_GET(self.list_val_i64)
                            code += i64_const(1)
                            code += I64_ADD
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            code += GLOBAL_GET(self.list_val_i64)
                            return
                        else:
                            self._gen_expr(recv, code, qname)
                            code += GLOBAL_SET(self.slice_base_global)
                            code += i64_const(0)
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x02, 0x40])
                            code += bytes([0x03, 0x40])
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])
                            code += bytes([0x45])
                            code += bytes([0x0D, 0x01])
                            code += GLOBAL_GET(self.list_val_i64)
                            code += i64_const(1)
                            code += I64_ADD
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            code += GLOBAL_GET(self.heap_global)
                            code += GLOBAL_SET(self.tmp_global)
                            code += GLOBAL_GET(self.heap_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += i32_const(1)
                            code += bytes([0x6A])
                            code += bytes([0x6A])
                            code += GLOBAL_SET(self.heap_global)
                            code += i32_const(0)
                            code += GLOBAL_SET(self.list_idx_global)
                            code += bytes([0x02, 0x40])
                            code += bytes([0x03, 0x40])
                            code += GLOBAL_GET(self.list_idx_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x48])
                            code += bytes([0x45])
                            code += bytes([0x0D, 0x01])
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_idx_global)
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])
                            # conversion for upper/lower
                            if method == "upper":
                                # if 'a'..'z' -> -32
                                code += bytes([0x41, 0x61])  # i32.const 97? Actually 0x41 then sleb128 97
                                # We'll emit i32.const 97 manually:
                            # skip conversion for now
                            code += GLOBAL_GET(self.tmp_global)
                            code += GLOBAL_GET(self.list_idx_global)
                            code += bytes([0x6A])
                            code += bytes([0x3A, 0x00, 0x00])
                            code += GLOBAL_GET(self.list_idx_global)
                            code += i32_const(1)
                            code += bytes([0x6A])
                            code += GLOBAL_SET(self.list_idx_global)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            code += GLOBAL_GET(self.tmp_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += i32_const(0)
                            code += bytes([0x3A, 0x00, 0x00])
                            code += GLOBAL_GET(self.tmp_global)
                            return
                # list slice
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "slice":
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if isinstance(base_ty, tuple) and base_ty[0] == "list":
                        elem_ty = base_ty[1] if len(base_ty) > 1 else None
                        is_float = (elem_ty == FLOAT)
                        is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
                        # base list ptr
                        self._gen_expr(e.base, code, qname)
                        code += GLOBAL_SET(self.slice_base_global)  # save base
                        sl = e.ops[0]
                        start_expr = sl[1]
                        end_expr = sl[2] if len(sl) > 2 else None
                        # start -> list_val_i64 (i64)
                        if start_expr is None:
                            code += i64_const(0)
                        else:
                            self._gen_expr(start_expr, code, qname)
                        code += GLOBAL_SET(self.list_val_i64)
                        # end -> list_idx_global (i32)
                        if end_expr is None:
                            code += GLOBAL_GET(self.slice_base_global)
                            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        else:
                            self._gen_expr(end_expr, code, qname)
                            code += bytes([0xA7])
                        code += GLOBAL_SET(self.list_idx_global)
                        # base_len -> list_tmp_global
                        code += GLOBAL_GET(self.slice_base_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        code += GLOBAL_SET(self.list_tmp_global)
                        # n = end - start (i32)
                        code += GLOBAL_GET(self.list_idx_global)
                        code += GLOBAL_GET(self.list_val_i64)
                        code += bytes([0xA7])
                        code += bytes([0x6B])  # i32.sub
                        # allocate new list
                        # cap = n (if n<0 use 0)
                        # store n in list_idx_global
                        code += GLOBAL_SET(self.list_idx_global)
                        # allocate header
                        code += GLOBAL_GET(self.heap_global)
                        code += GLOBAL_SET(self.tmp_global)
                        code += GLOBAL_GET(self.heap_global)
                        code += i32_const(16)
                        code += bytes([0x6A])
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        code += GLOBAL_SET(self.heap_global)
                        # store len
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.list_idx_global)
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
                        # store cap
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.list_idx_global)
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
                        # store data ptr
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += i32_const(16)
                        code += bytes([0x6A])
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
                        # copy loop
                        code += i32_const(0)
                        code += GLOBAL_SET(self.list_idx_global)  # reuse as i
                        code += bytes([0x02, 0x40])  # block
                        code += bytes([0x03, 0x40])  # loop
                        # if i >= n break
                        code += GLOBAL_GET(self.list_idx_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)  # len
                        code += bytes([0x48])  # i32.lt_s (i < n)
                        code += bytes([0x45])  # i32.eqz (i >= n)
                        code += bytes([0x0D, 0x01])  # br_if 1
                        # dst addr = new.data + i*8
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)  # data ptr
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        # src addr = base.data + (start+i)*8
                        code += GLOBAL_GET(self.slice_base_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)  # base data ptr
                        code += GLOBAL_GET(self.list_val_i64)
                        code += bytes([0xA7])
                        code += GLOBAL_GET(self.list_idx_global)
                        code += bytes([0x6A])
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        # load
                        if is_float:
                            code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                        else:
                            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                        # store
                        if is_float:
                            code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
                        else:
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                        # i++
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(1)
                        code += bytes([0x6A])
                        code += GLOBAL_SET(self.list_idx_global)
                        code += bytes([0x0C, 0x00])
                        code += bytes([0x0B])
                        code += bytes([0x0B])
                        # result
                        code += GLOBAL_GET(self.tmp_global)
                        return
                # map index
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "index":
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if isinstance(base_ty, tuple) and base_ty[0] == "map":
                        elem_val_ty = base_ty[2] if len(base_ty) > 2 else UNKNOWN
                        is_float_val = (elem_val_ty == FLOAT)
                        # evaluate key
                        key_expr = e.ops[0][1]
                        self._gen_expr(e.base, code, qname)
                        code += GLOBAL_SET(self.tmp_global)  # map ptr
                        self._gen_expr(key_expr, code, qname)
                        kt = self._tc_type(key_expr, qname)
                        if kt == STR or (isinstance(kt, tuple) and kt[0] in ("named", "list", "tuple")):
                            code += bytes([0xAC])
                        code += GLOBAL_SET(self.list_val_i64)  # key
                        # linear search via helper
                        helper_name, helper_idx = self._ensure_map_get_helper(is_float_val)
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.list_val_i64)
                        code += CALL(helper_idx)
                        return
                # list index
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "index":
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if isinstance(base_ty, tuple) and base_ty[0] == "list":
                        elem_ty = base_ty[1] if len(base_ty) > 1 else None
                        is_float = (elem_ty == FLOAT)
                        is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
                        # base list ptr
                        self._gen_expr(e.base, code, qname)
                        # load data ptr (offset 8)
                        code += bytes([0x28])
                        code += _uleb128_static(2)
                        code += _uleb128_static(8)
                        # idx
                        idx_expr = e.ops[0][1]
                        self._gen_expr(idx_expr, code, qname)
                        code += bytes([0xA7])  # i32.wrap_i64
                        # *8
                        code += i32_const(8)
                        code += bytes([0x6C])  # i32.mul
                        # add
                        code += bytes([0x6A])  # i32.add
                        if is_float:
                            code += bytes([0x2B])  # f64.load
                            code += _uleb128_static(3)
                            code += _uleb128_static(0)
                        else:
                            code += bytes([0x29])  # i64.load
                            code += _uleb128_static(3)
                            code += _uleb128_static(0)
                            if is_ptr:
                                code += bytes([0xA7])  # i32.wrap_i64
                        return
                # list field access: .len
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "field":
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if isinstance(base_ty, tuple) and base_ty[0] == "list" and e.ops[0][1] == "len":
                        self._gen_expr(e.base, code, qname)
                        code += bytes([0x28])  # i32.load len
                        code += _uleb128_static(2)
                        code += _uleb128_static(0)
                        code += bytes([0xAC])  # i64.extend_i32_u
                        return
                    if base_ty == STR and e.ops[0][1] == "len":
                        self._gen_expr(e.base, code, qname)
                        code += GLOBAL_SET(self.slice_base_global)
                        code += i64_const(0)
                        code += GLOBAL_SET(self.list_val_i64)
                        code += bytes([0x02, 0x40])
                        code += bytes([0x03, 0x40])
                        code += GLOBAL_GET(self.slice_base_global)
                        code += GLOBAL_GET(self.list_val_i64)
                        code += bytes([0xA7])
                        code += bytes([0x6A])
                        code += bytes([0x2D, 0x00, 0x00])
                        code += bytes([0x45])
                        code += bytes([0x0D, 0x01])
                        code += GLOBAL_GET(self.list_val_i64)
                        code += i64_const(1)
                        code += I64_ADD
                        code += GLOBAL_SET(self.list_val_i64)
                        code += bytes([0x0C, 0x00])
                        code += bytes([0x0B])
                        code += bytes([0x0B])
                        code += GLOBAL_GET(self.list_val_i64)
                        return
                # list push method
                if (isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field" and e.ops and e.ops[-1][0] == "call" and e.base.ops[-1][1] == "push"):
                    base_ty = self._tc_type(e.base.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "list":
                        args = e.ops[-1][1] or []
                        val_expr = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                        elem_ty = base_ty[1] if len(base_ty) > 1 else None
                        is_float = (elem_ty == FLOAT)
                        is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
                        # evaluate element -> list_val
                        self._gen_expr(val_expr, code, qname)
                        if is_float:
                            code += GLOBAL_SET(self.list_val_f64)
                        elif is_ptr:
                            code += bytes([0xAC])
                            code += GLOBAL_SET(self.list_val_i64)
                        else:
                            code += GLOBAL_SET(self.list_val_i64)
                        # list ptr
                        self._gen_expr(e.base.base, code, qname)
                        code += GLOBAL_SET(self.tmp_global)
                        # if len == cap: grow
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(4)
                        code += bytes([0x46])  # i32.eq
                        code += bytes([0x04, 0x40])  # if void
                        # new data ptr = heap
                        code += GLOBAL_GET(self.heap_global)
                        code += GLOBAL_SET(self.list_tmp_global)
                        # heap += newcap*8
                        code += GLOBAL_GET(self.heap_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(4)
                        code += i32_const(2)
                        code += bytes([0x6C])
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        code += GLOBAL_SET(self.heap_global)
                        # update cap
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(4)
                        code += i32_const(2)
                        code += bytes([0x6C])
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
                        # copy loop
                        code += i32_const(0)
                        code += GLOBAL_SET(self.list_idx_global)
                        code += bytes([0x02, 0x40])  # block
                        code += bytes([0x03, 0x40])  # loop
                        # if idx >= oldlen break
                        code += GLOBAL_GET(self.list_idx_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        code += bytes([0x4A])  # i32.lt_s
                        code += bytes([0x45])  # i32.eqz
                        code += bytes([0x0D, 0x01])  # br_if 1
                        # dest addr = newdata + idx*8
                        code += GLOBAL_GET(self.list_tmp_global)
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        # src addr = olddata + idx*8
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])
                        # load value
                        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                        # store value to dest
                        # stack: dest_addr, value
                        code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                        # idx++
                        code += GLOBAL_GET(self.list_idx_global)
                        code += i32_const(1)
                        code += bytes([0x6A])
                        code += GLOBAL_SET(self.list_idx_global)
                        code += bytes([0x0C, 0x00])  # br 0
                        code += bytes([0x0B])  # end loop
                        code += bytes([0x0B])  # end block
                        # update data ptr to new data
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.list_tmp_global)
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
                        code += bytes([0x0B])  # end if
                        # store element at data[len]
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)  # data ptr
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)  # len
                        code += i32_const(8)
                        code += bytes([0x6C])
                        code += bytes([0x6A])  # addr
                        if is_float:
                            code += GLOBAL_GET(self.list_val_f64)
                            code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
                        else:
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                        # len++
                        code += GLOBAL_GET(self.tmp_global)
                        code += GLOBAL_GET(self.tmp_global)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        code += i32_const(1)
                        code += bytes([0x6A])
                        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
                        # result void (drop) -> push returns nil? Minim push returns nil. Leave 0.
                        code += i64_const(0)
                        return

                # handle calls
                # field access (no call)
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "field":
                    fname = e.ops[0][1]
                    field_info = None
                    for tn, fields in self.struct_layouts.items():
                        for (f, wtype, off, fty, fdefault) in fields:
                            if f == fname:
                                field_info = (wtype, off, fty)
                                break
                        if field_info:
                            break
                    if field_info is not None:
                        self._gen_expr(e.base, code, qname)
                        wtype, off, fty = field_info
                        if wtype == WasmEncoder.F64:
                            code += bytes([0x2B])
                        elif wtype == WasmEncoder.I32:
                            code += bytes([0x28])
                        else:
                            code += bytes([0x29])
                        code += _uleb128_static(3)
                        code += _uleb128_static(off)
                        return
                # constructor call for sum-type variants: Type.Variant(args)
                if (isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field"
                        and isinstance(e.base.base, NameExpr)
                        and e.base.base.name in self.sum_types
                        and e.base.ops[-1][1] in self.variant_index.get(e.base.base.name, {})
                        and e.ops and e.ops[-1][0] == "call"):
                    type_name = e.base.base.name
                    variant_name = e.base.ops[-1][1]
                    args = e.ops[-1][1] or []
                    size = self.struct_sizes[type_name]
                    tag = self.variant_index[type_name][variant_name]
                    code += GLOBAL_GET(self.heap_global)
                    code += GLOBAL_SET(self.tmp_global)
                    code += GLOBAL_GET(self.heap_global)
                    code += i32_const(size)
                    code += bytes([0x6A])
                    code += GLOBAL_SET(self.heap_global)
                    # tag at offset 0
                    code += GLOBAL_GET(self.tmp_global)
                    code += i32_const(tag)
                    code += bytes([0x36])
                    code += _uleb128_static(2)
                    code += _uleb128_static(0)
                    fields = self.variant_fields[type_name][variant_name]
                    for i, (fname, wtype, off, fty, fdefault) in enumerate(fields):
                        code += GLOBAL_GET(self.tmp_global)
                        if i < len(args):
                            val_expr = args[i].value if isinstance(args[i], Arg) else args[i]
                            for a in args:
                                if isinstance(a, Arg) and a.is_named and isinstance(a.label, NameExpr) and a.label.name == fname:
                                    val_expr = a.value
                        else:
                            if fdefault is not None:
                                val_expr = fdefault
                            else:
                                _unsupported(f"campo '{fname}' de '{type_name}.{variant_name}' sin valor ni default", e)
                        self._gen_expr(val_expr, code, qname)
                        if wtype == WasmEncoder.F64 and not self._is_float(val_expr, qname):
                            code += bytes([0xB9])  # f64.convert_i64_s
                        if wtype == WasmEncoder.F64:
                            code += bytes([0x39])
                        elif wtype == WasmEncoder.I32:
                            code += bytes([0x36])
                        else:
                            code += bytes([0x37])
                        code += _uleb128_static(3)
                        code += _uleb128_static(off)
                    code += GLOBAL_GET(self.tmp_global)
                    return
                # constructor call for struct types
                if isinstance(e.base, NameExpr) and e.ops and e.ops[-1][0] == "call" and e.base.name in self.struct_layouts:
                    callee_name = e.base.name
                    args = e.ops[-1][1] or []
                    # alloc
                    size = self.struct_sizes[callee_name]
                    code += GLOBAL_GET(self.heap_global)
                    code += GLOBAL_SET(self.tmp_global)
                    code += GLOBAL_GET(self.heap_global)
                    code += i32_const(size)
                    code += bytes([0x6A])  # i32.add
                    code += GLOBAL_SET(self.heap_global)
                    fields = self.struct_layouts[callee_name]
                    # positional arg index
                    for i, (fname, wtype, off, fty, fdefault) in enumerate(fields):
                        code += GLOBAL_GET(self.tmp_global)
                        # value
                        if i < len(args):
                            val_expr = args[i].value if isinstance(args[i], Arg) else args[i]
                            # handle named args
                            # find named
                            for a in args:
                                if isinstance(a, Arg) and a.is_named and isinstance(a.label, NameExpr) and a.label.name == fname:
                                    val_expr = a.value
                            self._gen_expr(val_expr, code, qname)
                            if wtype == WasmEncoder.F64 and not self._is_float(val_expr, qname):
                                code += bytes([0xB9])  # f64.convert_i64_s
                        else:
                            # default
                            if fdefault is not None:
                                self._gen_expr(fdefault, code, qname)
                                if wtype == WasmEncoder.F64 and not self._is_float(fdefault, qname):
                                    code += bytes([0xB9])
                            else:
                                _unsupported(
                                    f"campo '{fname}' de '{callee_name}' sin valor ni default en la llamada",
                                    e)
                        # store
                        if wtype == WasmEncoder.F64:
                            code += bytes([0x39])
                        elif wtype == WasmEncoder.I32:
                            code += bytes([0x36])
                        else:
                            code += bytes([0x37])
                        code += _uleb128_static(3)
                        code += _uleb128_static(off)
                    code += GLOBAL_GET(self.tmp_global)
                    return
                # str methods
                if isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field" and e.ops and e.ops[-1][0] == "call":
                    callee_name = e.base.ops[-1][1]
                    base_ty = self._tc_type(e.base.base, qname)
                    if base_ty == STR and callee_name in ("len", "upper", "lower"):
                        if callee_name == "len":
                            self._gen_expr(e.base.base, code, qname)
                            code += GLOBAL_SET(self.slice_base_global)
                            code += i64_const(0)
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x02, 0x40])  # block
                            code += bytes([0x03, 0x40])  # loop
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])  # i32.load8_u
                            code += bytes([0x45])  # i32.eqz
                            code += bytes([0x0D, 0x01])  # br_if 1
                            code += GLOBAL_GET(self.list_val_i64)
                            code += i64_const(1)
                            code += I64_ADD
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            code += GLOBAL_GET(self.list_val_i64)
                            return
                        else:
                            # upper/lower
                            self._gen_expr(e.base.base, code, qname)
                            code += GLOBAL_SET(self.slice_base_global)
                            # len
                            code += i64_const(0)
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x02, 0x40])
                            code += bytes([0x03, 0x40])
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])
                            code += bytes([0x45])
                            code += bytes([0x0D, 0x01])
                            code += GLOBAL_GET(self.list_val_i64)
                            code += i64_const(1)
                            code += I64_ADD
                            code += GLOBAL_SET(self.list_val_i64)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            # allocate len+1
                            code += GLOBAL_GET(self.heap_global)
                            code += GLOBAL_SET(self.tmp_global)
                            code += GLOBAL_GET(self.heap_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += i32_const(1)
                            code += bytes([0x6A])
                            code += bytes([0x6A])
                            code += GLOBAL_SET(self.heap_global)
                            # convert loop
                            code += i32_const(0)
                            code += GLOBAL_SET(self.list_idx_global)
                            code += bytes([0x02, 0x40])
                            code += bytes([0x03, 0x40])
                            code += GLOBAL_GET(self.list_idx_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x48])  # i32.lt_s
                            code += bytes([0x45])
                            code += bytes([0x0D, 0x01])
                            # src byte
                            code += GLOBAL_GET(self.slice_base_global)
                            code += GLOBAL_GET(self.list_idx_global)
                            code += bytes([0x6A])
                            code += bytes([0x2D, 0x00, 0x00])
                            code += GLOBAL_SET(self.list_tmp_global)
                            if callee_name == "upper":
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(97)
                                code += bytes([0x4E])
                                code += bytes([0x04, 0x40])
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(122)
                                code += bytes([0x4C])
                                code += bytes([0x04, 0x40])
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(32)
                                code += bytes([0x6B])
                                code += GLOBAL_SET(self.list_tmp_global)
                                code += bytes([0x0B])
                                code += bytes([0x0B])
                            else:
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(65)
                                code += bytes([0x4E])
                                code += bytes([0x04, 0x40])
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(90)
                                code += bytes([0x4C])
                                code += bytes([0x04, 0x40])
                                code += GLOBAL_GET(self.list_tmp_global)
                                code += i32_const(32)
                                code += bytes([0x6A])
                                code += GLOBAL_SET(self.list_tmp_global)
                                code += bytes([0x0B])
                                code += bytes([0x0B])
                            code += GLOBAL_GET(self.tmp_global)
                            code += GLOBAL_GET(self.list_idx_global)
                            code += bytes([0x6A])
                            code += GLOBAL_GET(self.list_tmp_global)
                            code += bytes([0x3A, 0x00, 0x00])  # i32.store8
                            # i++
                            code += GLOBAL_GET(self.list_idx_global)
                            code += i32_const(1)
                            code += bytes([0x6A])
                            code += GLOBAL_SET(self.list_idx_global)
                            code += bytes([0x0C, 0x00])
                            code += bytes([0x0B])
                            code += bytes([0x0B])
                            # null terminate
                            code += GLOBAL_GET(self.tmp_global)
                            code += GLOBAL_GET(self.list_val_i64)
                            code += bytes([0xA7])
                            code += bytes([0x6A])
                            code += i32_const(0)
                            code += bytes([0x3A, 0x00, 0x00])
                            code += GLOBAL_GET(self.tmp_global)
                            return
                # method call: base is <recv>.method, then call
                if isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field" and e.ops and e.ops[-1][0] == "call":
                    callee_name = e.base.ops[-1][1]
                    if callee_name in self.func_index:
                        self._gen_expr(e.base.base, code, qname)
                        args = e.ops[-1][1] or []
                        for a in args:
                            val = a.value if isinstance(a, Arg) else a
                            self._gen_expr(val, code, qname)
                        # pad defaults
                        decl = None
                        for stmt in self.program.stmts:
                            if isinstance(stmt, TypeDecl):
                                for m in stmt.members:
                                    if isinstance(m.node, FnDecl) and m.node.name == callee_name:
                                        decl = m.node
                                        break
                                if decl:
                                    break
                        if decl is not None and decl.params and decl.params[0].name == "self":
                            for i in range(len(args), len(decl.params) - 1):
                                p = decl.params[i + 1]
                                if p.default is not None:
                                    self._gen_expr(p.default, code, qname)
                                else:
                                    _unsupported(f"parametro '{p.name}' sin valor ni default", e)
                        code += CALL(self.func_index[callee_name])
                        return
                # Determine callee
                # function call: NameExpr + call
                if isinstance(e.base, NameExpr) and e.ops and e.ops[-1][0] == "call":
                    callee_name = e.base.name
                    args = e.ops[-1][1] or []
                    lv = self.lambda_vars.get(qname, {}).get(callee_name)
                    if lv is not None:
                        lname, captured = lv
                        # pass captured vars first
                        for v in captured:
                            # load current value
                            if v in self.locals_map[qname]:
                                code += local_get(self.locals_map[qname][v])
                            else:
                                self._gen_expr(NameExpr(v), code, qname)
                        # convert captured vars to appropriate? They are already values.
                        for a in args:
                            val = a.value if isinstance(a, Arg) else a
                            self._gen_expr(val, code, qname)
                        code += CALL(self.func_index[lname])
                        return
                    for a in args:
                        val = a.value if isinstance(a, Arg) else a
                        self._gen_expr(val, code, qname)
                    # pad defaults for function calls
                    decl = None
                    for stmt in self.program.stmts:
                        if isinstance(stmt, FnDecl) and stmt.name == callee_name:
                            decl = stmt
                            break
                    if decl is not None:
                        for i in range(len(args), len(decl.params)):
                            p = decl.params[i]
                            if p.default is not None:
                                self._gen_expr(p.default, code, qname)
                            else:
                                _unsupported(f"parametro '{p.name}' sin valor ni default", e)
                    if callee_name == "print":
                        arg_expr = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                        arg_ty = self._tc_type(arg_expr, qname) if arg_expr is not None else None
                        if isinstance(arg_expr, StrLit) or arg_ty == STR:
                            code += CALL(self.print_str_import)
                        elif args and self._is_float(arg_expr, qname):
                            code += CALL(self.print_f64_import)
                        else:
                            code += CALL(self.print_import)
                    elif callee_name == "err":
                        # set error globals
                        msg_expr = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                        code_expr = args[1].value if (len(args) > 1 and isinstance(args[1], Arg)) else (args[1] if len(args) > 1 else None)
                        self._gen_expr(msg_expr, code, qname)
                        code += GLOBAL_SET(self.err_msg_global)
                        if code_expr is not None:
                            self._gen_expr(code_expr, code, qname)
                        else:
                            code += i64_const(0)
                        code += GLOBAL_SET(self.err_code_global)
                        code += i32_const(1)
                        code += GLOBAL_SET(self.err_flag_global)
                        code += i64_const(0)
                    elif callee_name in self.func_index:
                        code += CALL(self.func_index[callee_name])
                    else:
                        _unsupported(f"llamada a funcion desconocida '{callee_name}'", e)
                else:
                    _unsupported(
                        "esta forma de acceso/llamada (map, string methods, modulos "
                        "como fs/env, closures, o metodos no registrados)", e)
            else:
                _unsupported(f"expresiones de tipo {type(e).__name__}", e)
