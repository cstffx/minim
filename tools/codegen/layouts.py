from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from tools.layouts import compute_type_layouts, erase_task, wasm_type
from .util import _unsupported
from .strings_walk import collect_str_literals

class LayoutsMixin:
        def _erase_task(self, ty):
            """v0.1: task[T] se representa como T (spawn/await secuenciales)."""
            return erase_task(ty)

        def _wasm_type(self, ty):
            return wasm_type(ty)

        def collect_functions(self):
            # top-level functions
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    self._register_func(stmt, None)
                elif isinstance(stmt, TypeDecl):
                    for m in stmt.members:
                        if isinstance(m.node, FnDecl):
                            self._register_func(m.node, stmt.name)

        def _register_func(self, fn, self_type):
            # params
            params = []
            for p in fn.params:
                if p.name == "self":
                    params.append(WasmEncoder.I32)
                else:
                    if p.type_ is not None:
                        params.append(self._wasm_type(self.tc._atype(p.type_)))
                    else:
                        params.append(WasmEncoder.I64)
            # return type: annotation first, otherwise the type checker's
            # inferred signature (phase 1: last expression is the return value).
            if fn.ret is not None:
                ret_ty = self.tc._atype(fn.ret)
            else:
                ret_ty = self._inferred_ret(fn, self_type)
            if ret_ty is None or ret_ty == ("p", "nil"):
                results = []
            else:
                results = [self._wasm_type(ret_ty)]
            typeidx = self.enc.add_type(params, results)
            qname = fn.name if self_type is None else f"{self_type}.{fn.name}"
            self.func_typeidx[qname] = typeidx
            if not hasattr(self, "func_ret"):
                self.func_ret = {}
            self.func_ret[qname] = ret_ty

        def _inferred_ret(self, fn, self_type):
            ret = None
            try:
                if self_type is None:
                    sym = self.tc.module_scope.lookup(fn.name)
                else:
                    td = self.tc.type_defs.get(self_type)
                    ts = self.tc.resolver.type_scopes.get(id(td)) if td is not None else None
                    sym = ts.lookup(fn.name) if ts is not None else None
                ty = getattr(sym, "ty", None)
                if isinstance(ty, tuple) and ty[0] == "func":
                    ret = ty[2]
            except Exception:
                ret = None
            # Resolver symbols for type methods often carry an unknown return
            # type; infer it from the trailing expression of the body instead.
            if ret is None or (isinstance(ret, tuple) and ret[0] == "u"):
                last = None
                if fn.body is not None and fn.body.stmts and isinstance(fn.body.stmts[-1], ExprStmt):
                    last = fn.body.stmts[-1].expr
                # Calls that produce no value at all (builtin mutators) make
                # the enclosing function return nil.
                if (isinstance(last, Postfix) and last.ops and last.ops[-1][0] == "call"
                        and isinstance(last.base, Postfix) and last.base.ops
                        and last.base.ops[-1][0] == "field"
                        and last.base.ops[-1][1] in ("push", "add", "insert", "del", "remove", "clear")):
                    return NIL
                if last is not None:
                    q = fn.name if self_type is None else f"{self_type}.{fn.name}"
                    try:
                        inferred = self._tc_type(last, q)
                    except Exception:
                        inferred = None
                    if inferred is not None:
                        ret = inferred
            return ret

        # ---- module storage / entry point (phase 1) ----
        def _module_decls(self):
            out = []
            for stmt in self.program.stmts:
                if isinstance(stmt, LetDecl):
                    out.append((stmt.name, stmt.value))
                elif isinstance(stmt, VarDecl):
                    for b in stmt.bindings:
                        if b.kind == "name" and b.name:
                            out.append((b.name, stmt.value))
            return out

        def _collect_module_storage(self):
            """Allocate one wasm global per top-level let/var (file = module)."""
            self.module_globals = {}
            for name, value in self._module_decls():
                sym = self.tc.module_scope.lookup(name)
                ty = getattr(sym, "ty", None)
                if ty is None:
                    ty = self._tc_type(value, None)
                wtype = self._wasm_type(ty)
                if wtype == WasmEncoder.F64:
                    init = f64_const(0.0)
                elif wtype == WasmEncoder.I32:
                    init = i32_const(0)
                else:
                    init = i64_const(0)
                idx = self.enc.add_global(wtype, True, init)
                self.module_globals[name] = (idx, wtype, ty)

        def _gen_module_decl(self, st, code, qname):
            pairs = []
            if isinstance(st, LetDecl):
                pairs = [(st.name, st.value)]
            elif isinstance(st, VarDecl):
                for b in st.bindings:
                    if b.kind == "name" and b.name:
                        pairs.append((b.name, st.value))
            for name, value in pairs:
                info = self.module_globals.get(name)
                if info is None:
                    continue
                idx, wtype, ty = info
                self._gen_expr(value, code, qname)
                if isinstance(value, (Lambda, MoveExpr)):
                    lname = getattr(self, "_last_lambda_name", None)
                    if lname is not None:
                        captured = list(getattr(self, "_last_lambda_captured", []))
                        self.lambda_vars.setdefault(qname, {})[name] = (lname, captured)
                        self.lambda_vars.setdefault(None, {})[name] = (lname, captured)
                if wtype == WasmEncoder.F64 and not self._is_float(value, qname):
                    code += bytes([0xB9])  # f64.convert_i64_s
                elif wtype != WasmEncoder.F64 and self._is_float(value, qname):
                    code += bytes([0xB0])  # i64.trunc_f64_s
                code += GLOBAL_SET(idx)

        def _gen_main_call(self, code):
            """Call main() from _start, dropping an integer result if any."""
            if "main" not in self.func_index:
                return
            code += CALL(self.func_index["main"])
            rty = getattr(self, "func_ret", {}).get("main")
            if rty is not None and rty != ("p", "nil"):
                code += DROP

        def _intern_str(self, value):
            if value in self.str_value_offsets:
                return self.str_value_offsets[value]
            data = value.encode("utf-8") + b"\x00"
            off = getattr(self, "_str_next_offset", 0)
            self.str_value_offsets[value] = off
            self.enc.add_data(off, data)
            self._str_next_offset = off + len(data)
            return off

        def generate(self):
            # scope map for type queries
            self.scope_map = getattr(self, "scope_map", {})
            self.scope_map[None] = self.tc.module_scope
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    sc = self.tc.resolver.func_scopes.get(id(stmt))
                    if sc is None:
                        sc = self.tc.module_scope.child("func", owner=stmt)
                    self.scope_map[stmt.name] = sc
                elif isinstance(stmt, TypeDecl):
                    ts = self.tc.resolver.type_scopes.get(id(stmt))
                    if ts is None:
                        ts = self.tc.module_scope.child("type", owner=stmt)
                    for m in stmt.members:
                        if isinstance(m.node, FnDecl):
                            sc = self.tc.resolver.func_scopes.get(id(m.node))
                            if sc is None:
                                sc = ts.child("func", owner=m.node)
                            self.scope_map[f"{stmt.name}.{m.node.name}"] = sc
            self.str_offsets, self.str_value_offsets, offset = collect_str_literals(
                self.program, self.enc.add_data)
            self._compute_struct_layouts()
            self._str_next_offset = offset
            self._collect_module_storage()
            self.collect_functions()
            # pre-assign function indices so recursive calls resolve
            idx = len(self.enc.imports)
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    self.func_index[stmt.name] = idx
                    idx += 1
                elif isinstance(stmt, TypeDecl):
                    for m in stmt.members:
                        if isinstance(m.node, FnDecl):
                            qname = f"{stmt.name}.{m.node.name}"
                            self.func_index[qname] = idx
                            self.func_index[m.node.name] = idx
                            idx += 1
            # generate code
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    self._gen_func(stmt, None)
                elif isinstance(stmt, TypeDecl):
                    for m in stmt.members:
                        if isinstance(m.node, FnDecl):
                            self._gen_func(m.node, stmt.name)
            # module body / entry point: top-level statements + call to main
            self._gen_entry_point()
            # exports: export all top-level functions, plus `_start`
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    if stmt.name.startswith("_") or stmt.name.split(".")[-1].startswith("_"):
                        continue
                    if "$" in stmt.name:
                        continue
                    if stmt.name in self.func_index:
                        self.enc.add_export_func(stmt.name, self.func_index[stmt.name])
            self.enc.add_export_func("_start", self.func_index["_start"])
            self._str_next_offset = offset
            return self.enc.encode()

        def _gen_entry_point(self):
            """Compile the file body (module declarations run in order)."""
            body = []
            for stmt in self.program.stmts:
                if isinstance(stmt, (LetDecl, VarDecl)):
                    body.append(stmt)
            for stmt in self.program.stmts:
                if not isinstance(stmt, (FnDecl, TypeDecl, TraitDecl, UseDecl, LetDecl, VarDecl)):
                    body.append(stmt)
            if "main" in self.func_index:
                body.append(ExprStmt(NameExpr("__startMain__")))
            fn = FnDecl("_start", [], [], None, Suite(body))
            self.func_typeidx["_start"] = self.enc.add_type([], [])
            self.func_index["_start"] = len(self.enc.imports) + len(self.enc.functions)
            self._gen_func(fn, None)

        def _is_float(self, e, qname):
            if isinstance(e, FloatLit):
                return True
            if isinstance(e, NameExpr):
                return e.name in self.float_vars.get(qname, set())
            if isinstance(e, BinOp):
                return self._is_float(e.left, qname) or self._is_float(e.right, qname)
            if isinstance(e, UnaryOp):
                return self._is_float(e.operand, qname)
            try:
                ty = self._tc_type(e, qname)
                if isinstance(ty, tuple) and ty[0] == "borrow":
                    ty = ty[1]
                return self._erase_task(ty) == FLOAT
            except Exception:
                return False

        def _tc_type(self, e, qname):
            # Unqualified field of the enclosing type inside a method
            # (`data` in `Buf.len` means `self.data`). The typechecker leaves
            # these as unknown when queried out of context, so resolve them
            # from the struct layout before falling back to `tc.expr`.
            if isinstance(e, NameExpr) and "." in (qname or ""):
                if (e.name not in self.locals_map.get(qname, {})
                        and e.name not in getattr(self, "module_globals", {})):
                    cls = qname.split(".")[0]
                    for (f, _wt, _off, fty, _fd) in self.struct_layouts.get(cls, []):
                        if f == e.name:
                            return fty
            scope = self.scope_map.get(qname, self.tc.module_scope)
            old = getattr(self.tc, "cur_type", None)
            try:
                if "." in (qname or ""):
                    self.tc.cur_type = qname.split(".")[0]
                return self.tc.expr(e, scope)
            except Exception:
                return None
            finally:
                self.tc.cur_type = old

        def _elem_type(self, e, qname):
            ty = self._tc_type(e, qname)
            if isinstance(ty, tuple) and ty[0] == "list" and len(ty) > 1:
                return ty[1]
            return None


        def _compute_struct_layouts(self):
            computed = compute_type_layouts(self.program, self.tc)
            self.struct_layouts = computed.struct_layouts
            self.struct_sizes = computed.struct_sizes
            self.variant_index = computed.variant_index
            self.variant_fields = computed.variant_fields
            self.sum_types = computed.sum_types
            self.layouts = computed
