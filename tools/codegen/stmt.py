from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *

class StmtMixin:
        def _gen_stmt(self, st, code, qname, fn, is_last=False):
            if isinstance(st, LetStmt) or isinstance(st, VarStmt):
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
            elif isinstance(st, ExprStmt):
                self._gen_expr(st.expr, code, qname)
                is_print = isinstance(st.expr, Postfix) and st.expr.ops and st.expr.ops[-1][0] == "call" and \
                           ((st.expr.base.name if isinstance(st.expr.base, NameExpr) else None) == "print")
                if (not is_last) and (not is_print):
                    code += DROP
            elif isinstance(st, ReturnStmt):
                if st.value is not None:
                    self._gen_expr(st.value, code, qname)
                code += RETURN
            elif isinstance(st, IfStmt):
                self._gen_expr(st.cond, code, qname)
                if isinstance(st.cond, (NameExpr, BoolLit, IntLit)) or (isinstance(st.cond, BinOp) and st.cond.op in ("and", "or")) or (isinstance(st.cond, UnaryOp) and st.cond.op == "not"):
                    if isinstance(st.cond, FloatLit):
                        code += f64_const(0.0)
                        code += F64_NE
                    else:
                        code += i64_const(0)
                        code += I64_NE
                code += IF(BLK_I64)
                self._gen_suite(st.then, code, qname, fn, is_last)
                if st.else_ is not None:
                    code += ELSE
                    self._gen_suite(st.else_, code, qname, fn, is_last)
                code += END
                if not is_last:
                    code += DROP
            elif isinstance(st, WhileStmt):
                # block $exit ... loop $body
                code += BLOCK(BLK_VOID)
                code += LOOP(BLK_VOID)
                self._gen_expr(st.cond, code, qname)
                if isinstance(st.cond, (NameExpr, BoolLit, IntLit)) or (isinstance(st.cond, BinOp) and st.cond.op in ("and", "or")) or (isinstance(st.cond, UnaryOp) and st.cond.op == "not"):
                    if isinstance(st.cond, FloatLit):
                        code += f64_const(0.0)
                        code += F64_NE
                    else:
                        code += i64_const(0)
                        code += I64_NE
                    code += bytes([0x45])  # i32.eqz
                elif isinstance(st.cond, BinOp):
                    code += bytes([0x45])  # i32.eqz
                else:
                    code += I64_EQZ
                code += bytes([0x0D, 0x01])  # br_if 1 (exit)
                self._gen_suite(st.body, code, qname, fn)
                code += bytes([0x0C, 0x00])  # br 0 (loop)
                code += END  # end loop
                code += END  # end block
            elif isinstance(st, Assign):
                vi = self.locals_map[qname].get(st.place.name) if (not st.place.parts) else None
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
                    elif st.op in ("+=",):
                        code += local_get(0)
                        load_op = 0x2B if wtype == WasmEncoder.F64 else (0x28 if wtype == WasmEncoder.I32 else 0x29)
                        code += bytes([load_op])
                        code += _uleb128_static(3)
                        code += _uleb128_static(off)
                        self._gen_expr(st.value, code, qname)
                        if wtype == WasmEncoder.F64:
                            code += F64_ADD
                        else:
                            code += I64_ADD
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
                elif op in ("+=",):
                    code += local_get(vi)
                    self._gen_expr(st.value, code, qname)
                    if self.float_vars.get(qname, set()) and st.place.name in self.float_vars[qname]:
                        code += F64_ADD
                    else:
                        code += I64_ADD
                elif op in ("-=",):
                    code += local_get(vi)
                    self._gen_expr(st.value, code, qname)
                    if self.float_vars.get(qname, set()) and st.place.name in self.float_vars[qname]:
                        code += F64_SUB
                    else:
                        code += I64_SUB
                elif op in ("*=",):
                    code += local_get(vi)
                    self._gen_expr(st.value, code, qname)
                    if self.float_vars.get(qname, set()) and st.place.name in self.float_vars[qname]:
                        code += F64_MUL
                    else:
                        code += I64_MUL
                else:
                    self._gen_expr(st.value, code, qname)
                code += local_set(vi)
            elif isinstance(st, MatchStmt):
                self._gen_match_core(st.expr, st.arms, code, qname, fn)
            else:
                _unsupported(f"sentencias de tipo {type(st).__name__}", st)

        def _gen_suite(self, suite, code, qname, fn, tail=False):
            stmts = (suite.stmts if hasattr(suite, "stmts") else [])
            for i, st in enumerate(stmts):
                self._gen_stmt(st, code, qname, fn, tail and (i == len(stmts) - 1))
