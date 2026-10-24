from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from .util import _unsupported

I32_EQZ = bytes([0x45])
I64_TRUNC_F64_S = bytes([0xB0])
F64_CONVERT_I64_S = bytes([0xB9])

CMP_OPS = {"==", "!=", "<", "<=", ">", ">=", "in", "is", "is not"}


class StmtMixin:
        def _expr_is_void(self, e, qname):
            """True when evaluating `e` as a statement leaves no value on the stack."""
            if not (isinstance(e, Postfix) and e.ops and e.ops[-1][0] == "call"):
                return False
            if isinstance(e.base, NameExpr):
                name = e.base.name
                if name in ("print", "eprint", "assert", "panic"):
                    return True
                ret = getattr(self, "func_ret", {}).get(name)
                return ret is None or ret == NIL
            if isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field":
                method = e.base.ops[-1][1]
                recv_ty = self._tc_type(e.base.base, qname)
                if isinstance(recv_ty, tuple) and recv_ty[0] in ("list", "set", "map"):
                    return method in ("push", "add", "insert", "del", "remove", "clear")
                if isinstance(recv_ty, tuple) and recv_ty[0] == "named":
                    ret = getattr(self, "func_ret", {}).get(f"{recv_ty[1]}.{method}")
                    return ret is None or ret == NIL
                # unknown receiver: void only if every method named like this is void
                rets = [r for k, r in getattr(self, "func_ret", {}).items()
                        if k.endswith("." + method)]
                if rets:
                    return all(r is None or r == NIL for r in rets)
            return False

        # ---- structured-control bookkeeping (break/continue) ----
        def _open_block(self, kind):
            if not hasattr(self, "ctrl_stack"):
                self.ctrl_stack = []
                self.block_depth = 0
            self.block_depth += 1
            self.ctrl_stack.append((kind, self.block_depth))

        def _close_block(self):
            self.block_depth -= 1
            self.ctrl_stack.pop()

        def _stmt_type(self, st, qname):
            try:
                import tools.nodes as _nodes
                scope = self.scope_map.get(qname, self.tc.module_scope)
                old = getattr(self.tc, "cur_type", None)
                if "." in (qname or ""):
                    self.tc.cur_type = qname.split(".")[0]
                ty = self.tc.stmt(st, scope)
                self.tc.cur_type = old
                return ty
            except Exception:
                return None

        def _bool_cond(self, e, code, qname):
            """Leave an i32 condition on the stack."""
            self._gen_expr(e, code, qname)
            ty = self._tc_type(e, qname)
            if ty == FLOAT:
                code += f64_const(0.0)
                code += F64_NE
                return
            code += i64_const(0)
            code += I64_NE

        def _emit_assign_op(self, op, code, wtype, cur_on_stack=True):
            if wtype == WasmEncoder.F64:
                code += {
                    "+": F64_ADD, "-": F64_SUB, "*": F64_MUL, "/": F64_DIV,
                }.get(op, None) or _unsupported(f"la asignacion compuesta '{op}' (float)")
                return
            if op == "+":
                code += I64_ADD
            elif op == "-":
                code += I64_SUB
            elif op == "*":
                code += I64_MUL
            elif op == "/":
                code += I64_DIV_S
            elif op == "//":
                code += I64_DIV_S
            elif op == "%":
                code += I64_REM_S
            elif op == "&":
                code += bytes([0x83])
            elif op == "|":
                code += bytes([0x84])
            elif op == "^":
                code += bytes([0x85])
            elif op == "<<":
                code += bytes([0x86])
            elif op == ">>":
                code += bytes([0x88])
            elif op == "**":
                _unsupported("la asignacion '**=' (usa x = x ** n)", None)
            else:
                _unsupported(f"la asignacion compuesta '{op}'", None)

        def _gen_stmt(self, st, code, qname, fn, is_last=False):
            if isinstance(st, (LetDecl, VarDecl)):
                # Module-level declarations become wasm globals (file = module).
                self._gen_module_decl(st, code, qname)
                return
            if isinstance(st, (LetStmt, VarStmt)):
                # tuple destructuring: let a, b = pair()
                vty = self._tc_type(st.value, qname)
                pats = []
                for b in st.bindings:
                    if getattr(b, "kind", None) == "tuple":
                        pats.extend(getattr(b, "tuple_patterns", None) or [])
                    elif getattr(b, "kind", None) == "name" and b.name:
                        pats.append(b)
                if (isinstance(vty, tuple) and vty[0] == "tuple"
                        and (len(st.bindings) > 1 or any(getattr(b, "kind", None) == "tuple" for b in st.bindings))):
                    self._gen_expr(st.value, code, qname)
                    code += GLOBAL_SET(self.tuple_base_global)
                    _size, fields = self._tuple_layout(vty)
                    for i, b in enumerate(pats):
                        if getattr(b, "kind", None) != "name" or not b.name or i >= len(fields):
                            continue
                        wt, off, _fty = fields[i]
                        code += GLOBAL_GET(self.tuple_base_global)
                        if wt == WasmEncoder.F64:
                            code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(off)
                        elif wt == WasmEncoder.I32:
                            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(off)
                        else:
                            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(off)
                        if b.name not in self.locals_map[qname]:
                            self.locals_map[qname][b.name] = len(self.locals_map[qname])
                        code += local_set(self.locals_map[qname][b.name])
                    return
                # evaluate value
                self._gen_expr(st.value, code, qname)
                # track lambda vars
                if isinstance(st.value, (Lambda, MoveExpr)):
                    lname = getattr(self, "_last_lambda_name", None)
                    name = None
                    for b in st.bindings:
                        if b.kind == "name" and b.name:
                            name = b.name
                            break
                    if name is not None and lname is not None:
                        captured = getattr(self, "_last_lambda_captured", [])
                        self.lambda_vars.setdefault(qname, {})[name] = (lname, list(captured))
                # store into first binding name
                name = None
                for b in st.bindings:
                    if b.kind == "name" and b.name:
                        name = b.name
                        break
                if name is not None:
                    if name not in self.locals_map[qname]:
                        # add dynamically? not allowed; should have collected
                        self.locals_map[qname][name] = len(self.locals_map[qname])
                    code += local_set(self.locals_map[qname][name])
                elif len(st.bindings) == 1 and st.bindings[0].kind in ("tuple", "variant"):
                    # destructuring: value pointer is on the stack, keep it in a scratch
                    # local if available; phase 1 only needs name bindings.
                    code += DROP
            elif isinstance(st, ExprStmt):
                if (isinstance(st.expr, NameExpr) and st.expr.name == "__startMain__"):
                    self._gen_main_call(code)
                    return
                if (isinstance(st.expr, Postfix) and isinstance(st.expr.base, NameExpr)
                        and st.expr.base.name in ("drop", "copy") and st.expr.ops
                        and st.expr.ops[-1][0] == "call"):
                    args = st.expr.ops[-1][1] or []
                    if args:
                        val = args[0].value if isinstance(args[0], Arg) else args[0]
                        self._gen_expr(val, code, qname)
                        code += DROP
                    return
                self._gen_expr(st.expr, code, qname)
                ty = self._tc_type(st.expr, qname)
                if (not is_last) and ty != NIL and not self._expr_is_void(st.expr, qname):
                    code += DROP
            elif isinstance(st, ReturnStmt):
                if st.value is not None:
                    self._gen_expr(st.value, code, qname)
                    rty = getattr(self, "func_ret", {}).get(qname)
                    if st.value is not None and rty == FLOAT and not self._is_float(st.value, qname):
                        code += F64_CONVERT_I64_S
                code += RETURN
            elif isinstance(st, IfStmt):
                self._gen_if_stmt(st, code, qname, fn, is_last)
            elif isinstance(st, WhileStmt):
                code += BLOCK(BLK_VOID)
                self._open_block("exit")
                code += LOOP(BLK_VOID)
                self._open_block("loop")
                self._bool_cond(st.cond, code, qname)
                code += I32_EQZ
                code += bytes([0x0D, 0x01])  # br_if 1 (exit)
                fc = getattr(st, "_for_continue_count", None)
                if fc is not None:
                    code += BLOCK(BLK_VOID)
                    self._open_block("for_continue")
                    self._gen_suite(Suite(st.body.stmts[:fc]), code, qname, fn, False)
                    self._close_block()
                    code += END
                    self._gen_suite(Suite(st.body.stmts[fc:]), code, qname, fn, False)
                else:
                    self._gen_suite(st.body, code, qname, fn, False)
                code += bytes([0x0C, 0x00])  # br 0 (loop)
                self._close_block()  # loop
                code += END
                self._close_block()  # exit
                code += END
            elif isinstance(st, BreakStmt):
                code += self._branch_to("exit")
            elif isinstance(st, ContinueStmt):
                target = "loop"
                for k, _d in reversed(getattr(self, "ctrl_stack", [])):
                    if k in ("loop", "for_continue"):
                        target = k
                        break
                code += self._branch_to(target)
            elif isinstance(st, Assign):
                self._gen_assign(st, code, qname)
            elif isinstance(st, (SpawnStmt, AwaitStmt)):
                # v0.1 secuencial: el valor se evalua aqui; como sentencia se
                # descarta (el resultado real se usa via `let t = spawn ...`).
                self._gen_expr(st.expr, code, qname)
                ty = self._tc_type(st.expr, qname)
                if (not is_last) and ty not in (None, NIL):
                    code += DROP
            elif isinstance(st, MatchStmt):
                mv = is_last and self._stmt_type(st, qname) not in (None, NIL)
                self._gen_match_core(st.expr, st.arms, code, qname, fn, want_value=mv)
            else:
                _unsupported(f"sentencias de tipo {type(st).__name__}", st)

        def _branch_to(self, kind):
            stack = getattr(self, "ctrl_stack", [])
            target = None
            for k, depth in reversed(stack):
                if k == kind:
                    target = depth
                    break
            if target is None:
                from tools.codegen import CodegenError
                raise CodegenError(f"{kind} fuera de un bucle")
            return bytes([0x0C]) + _uleb128_static(self.block_depth - target)

        def _gen_if_stmt(self, st, code, qname, fn, is_last):
            result_ty = self._stmt_type(st, qname) if is_last else NIL
            wtype = self._wasm_type(result_ty) if result_ty not in (None, NIL) else None
            tail = wtype is not None

            def branch(cond, suite, els):
                nonlocal code
                self._bool_cond(cond, code, qname)
                code += IF(wtype if wtype is not None else BLK_VOID)
                self._open_block("if")
                self._gen_suite(suite, code, qname, fn, tail)
                if els is not None:
                    code += ELSE
                    if callable(els):
                        els()
                    else:
                        self._gen_suite(els, code, qname, fn, tail)
                elif tail:
                    code += ELSE
                    if wtype == WasmEncoder.F64:
                        code += f64_const(0.0)
                    elif wtype == WasmEncoder.I32:
                        code += i32_const(0)
                    else:
                        code += i64_const(0)
                code += END
                self._close_block()

            elifs = list(st.elifs or [])
            def rest(i):
                if i < len(elifs):
                    ec, es = elifs[i]
                    branch(ec, es, rest(i + 1) if (i + 1 < len(elifs) or st.else_ is not None) else None)
                elif st.else_ is not None:
                    self._gen_suite(st.else_, code, qname, fn, tail)
            if elifs:
                ec, es = elifs[0]
                branch(st.cond, st.then, rest(1) if (len(elifs) > 1 or st.else_ is not None) else None)
            else:
                branch(st.cond, st.then, st.else_)
            if tail and not is_last:
                code += DROP

        def _gen_assign(self, st, code, qname):
            vi = self.locals_map[qname].get(st.place.name) if (not st.place.parts) else None
            # module-level var
            if vi is None and not st.place.parts and st.place.name in getattr(self, "module_globals", {}):
                idx, wtype, ty = self.module_globals[st.place.name]
                if st.op == "=":
                    self._gen_expr(st.value, code, qname)
                else:
                    code += GLOBAL_GET(idx)
                    self._gen_expr(st.value, code, qname)
                    self._emit_assign_op(st.op[:-1], code, wtype)
                if wtype == WasmEncoder.F64 and not self._is_float(st.value, qname) and st.op == "=":
                    code += F64_CONVERT_I64_S
                code += GLOBAL_SET(idx)
                return
            # bare field assignment in method
            field_info = None
            if vi is None and (not st.place.parts) and "." in qname:
                cls = qname.split(".")[0]
                for (f, wtype, off, fty, fdefault) in self.struct_layouts.get(cls, []):
                    if f == st.place.name:
                        field_info = (wtype, off)
                        break
            if field_info is not None:
                wtype, off = field_info
                code += local_get(0)  # self ptr
                if st.op == "=":
                    self._gen_expr(st.value, code, qname)
                    if wtype == WasmEncoder.F64 and not self._is_float(st.value, qname):
                        code += F64_CONVERT_I64_S
                else:
                    load_op = 0x2B if wtype == WasmEncoder.F64 else (0x28 if wtype == WasmEncoder.I32 else 0x29)
                    code += bytes([load_op])
                    code += _uleb128_static(3)
                    code += _uleb128_static(off)
                    self._gen_expr(st.value, code, qname)
                    self._emit_assign_op(st.op[:-1], code, wtype)
                code += bytes([0x39 if wtype == WasmEncoder.F64 else (0x36 if wtype == WasmEncoder.I32 else 0x37)])
                code += _uleb128_static(3)
                code += _uleb128_static(off)
                return
            if vi is None:
                self._gen_expr(st.value, code, qname)
                code += DROP
                return
            op = st.op
            if op == "=":
                self._gen_expr(st.value, code, qname)
                if (qname in self.float_vars and st.place.name in self.float_vars[qname]
                        and not self._is_float(st.value, qname)):
                    code += F64_CONVERT_I64_S
            else:
                code += local_get(vi)
                self._gen_expr(st.value, code, qname)
                wtype = WasmEncoder.F64 if (qname in self.float_vars and st.place.name in self.float_vars[qname]) else WasmEncoder.I64
                self._emit_assign_op(op[:-1], code, wtype)
            code += local_set(vi)

        def _gen_suite(self, suite, code, qname, fn, tail=False):
            stmts = (suite.stmts if hasattr(suite, "stmts") else [])
            for i, st in enumerate(stmts):
                self._gen_stmt(st, code, qname, fn, tail and (i == len(stmts) - 1))
