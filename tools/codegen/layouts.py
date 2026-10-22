from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from .util import _unsupported

class LayoutsMixin:
        def _wasm_type(self, ty):
            if isinstance(ty, tuple):
                if ty[0] == "p":
                    if ty[1] == "int":
                        return WasmEncoder.I64
                    if ty[1] == "float":
                        return WasmEncoder.F64
                    if ty[1] == "bool":
                        return WasmEncoder.I64
                    if ty[1] == "str":
                        return WasmEncoder.I32
                    if ty[1] == "bytes":
                        return WasmEncoder.I32
                if ty[0] == "named":
                    return WasmEncoder.I32
                if ty[0] in ("opt", "res", "borrow"):
                    return self._wasm_type(ty[1])
                if ty[0] in ("list", "map", "set", "tuple", "func"):
                    return WasmEncoder.I32
            return WasmEncoder.I64

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
            try:
                if self_type is None:
                    sym = self.tc.module_scope.lookup(fn.name)
                else:
                    td = self.tc.type_defs.get(self_type)
                    ts = self.tc.resolver.type_scopes.get(id(td)) if td is not None else None
                    sym = ts.lookup(fn.name) if ts is not None else None
                ty = getattr(sym, "ty", None)
                if isinstance(ty, tuple) and ty[0] == "func":
                    return ty[2]
            except Exception:
                pass
            return None

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
            # collect string literals
            offset = 0
            def walk_str(e):
                nonlocal offset
                if isinstance(e, (StrLit, RStrLit, MlStrLit, BytesLit)):
                    if e.value in self.str_value_offsets:
                        self.str_offsets[id(e)] = self.str_value_offsets[e.value]
                    elif id(e) not in self.str_offsets:
                        raw = (e.value.encode("latin-1") if isinstance(e, BytesLit)
                               else e.value.encode("utf-8"))
                        b = raw + b"\x00"
                        self.str_offsets[id(e)] = offset
                        self.str_value_offsets[e.value] = offset
                        self.enc.add_data(offset, b)
                        offset += len(b)
                    else:
                        self.str_value_offsets[e.value] = self.str_offsets[id(e)]
                elif isinstance(e, FStrLit):
                    if e.value in self.str_value_offsets:
                        self.str_offsets[id(e)] = self.str_value_offsets[e.value]
                    elif id(e) not in self.str_offsets:
                        b = e.value.encode("utf-8") + b"\x00"
                        self.str_offsets[id(e)] = offset
                        self.str_value_offsets[e.value] = offset
                        self.enc.add_data(offset, b)
                        offset += len(b)
                    else:
                        self.str_value_offsets[e.value] = self.str_offsets[id(e)]
                elif isinstance(e, (BinOp, UnaryOp)):
                    if isinstance(e, BinOp):
                        walk_str(e.left)
                        if not isinstance(e.right, str):
                            walk_str(e.right)
                    else:
                        walk_str(e.operand)
                elif isinstance(e, Postfix):
                    walk_str(e.base)
                    for op in (e.ops or []):
                        if op[0] == "call":
                            for a in (op[1] or []):
                                val = a.value if isinstance(a, Arg) else a
                                walk_str(val)
                        elif op[0] in ("index", "slice"):
                            if op[1] is not None and not isinstance(op[1], str):
                                walk_str(op[1])
                            if len(op) > 2 and op[2] is not None:
                                walk_str(op[2])
                elif isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
                    for a in (getattr(e, "items", None) or []):
                        val = a.value if isinstance(a, Arg) else a
                        walk_str(val)
                        if isinstance(e, MapExpr) and isinstance(a, Arg) and a.is_named and isinstance(a.label, StrLit):
                            key = a.label.value
                            if key not in self.str_value_offsets:
                                b = key.encode("utf-8") + b"\x00"
                                self.str_value_offsets[key] = offset
                                self.str_offsets[id(a.label)] = offset
                                self.enc.add_data(offset, b)
                                offset += len(b)
                            else:
                                self.str_offsets[id(a.label)] = self.str_value_offsets[key]
                        elif isinstance(e, MapExpr) and isinstance(a, Arg) and a.is_named and isinstance(a.label, NameExpr):
                            key = a.label.name
                            if key not in self.str_value_offsets:
                                b = key.encode("utf-8") + b"\x00"
                                self.str_value_offsets[key] = offset
                                self.enc.add_data(offset, b)
                                offset += len(b)
                elif isinstance(e, IfExpr):
                    walk_str(e.cond); walk_str(e.then); walk_str(e.else_)
                elif isinstance(e, MatchExpr):
                    walk_str(e.expr)
                    for arm in (e.arms or []):
                        if arm.guard is not None:
                            walk_str(arm.guard)
                        if isinstance(arm.body, Suite):
                            for st in (arm.body.stmts if hasattr(arm.body, "stmts") else []):
                                walk_str_stmt(st)
                        elif arm.body is not None:
                            walk_str(arm.body)
                elif isinstance(e, (LetStmt, VarStmt)):
                    walk_str(e.value)
                elif isinstance(e, ExprStmt):
                    walk_str(e.expr)
                elif isinstance(e, IfStmt):
                    walk_str(e.cond)
                    for st in (e.then.stmts if hasattr(e.then,"stmts") else []):
                        walk_str_stmt(st)
                    if e.else_:
                        for st in (e.else_.stmts if hasattr(e.else_,"stmts") else []):
                            walk_str_stmt(st)
                elif isinstance(e, WhileStmt):
                    walk_str(e.cond)
                    for st in (e.body.stmts if hasattr(e.body,"stmts") else []):
                        walk_str_stmt(st)
                elif isinstance(e, ForStmt):
                    if not isinstance(e.iter, str):
                        walk_str(e.iter)
                    for st in (e.body.stmts if hasattr(e.body,"stmts") else []):
                        walk_str_stmt(st)
                elif isinstance(e, ReturnStmt) and e.value is not None:
                    walk_str(e.value)
                elif isinstance(e, Assign):
                    walk_str(e.value)
            def walk_str_stmt(st):
                if isinstance(st, (LetStmt, VarStmt)):
                    walk_str(st.value)
                elif isinstance(st, ExprStmt):
                    walk_str(st.expr)
                elif isinstance(st, Assign):
                    walk_str(st.value)
                elif isinstance(st, ForStmt):
                    if not isinstance(st.iter, str): walk_str(st.iter)
                    for s in (st.body.stmts if hasattr(st.body,"stmts") else []): walk_str_stmt(s)
                elif isinstance(st, ReturnStmt) and st.value is not None:
                    walk_str(st.value)
                elif isinstance(st, IfStmt):
                    walk_str(st.cond)
                    for s in (st.then.stmts if hasattr(st.then,"stmts") else []): walk_str_stmt(s)
                    for ec, es in (st.elifs or []):
                        walk_str(ec)
                        for s in (es.stmts if hasattr(es,"stmts") else []): walk_str_stmt(s)
                    if st.else_ is not None:
                        for s in (st.else_.stmts if hasattr(st.else_,"stmts") else []): walk_str_stmt(s)
                elif isinstance(st, WhileStmt):
                    walk_str(st.cond)
                    for s in (st.body.stmts if hasattr(st.body,"stmts") else []): walk_str_stmt(s)
                elif isinstance(st, MatchStmt):
                    walk_str(st.expr)
                    for arm in (st.arms or []):
                        if isinstance(arm.body, Suite):
                            for s in arm.body.stmts: walk_str_stmt(s)
                        elif arm.body is not None:
                            walk_str(arm.body)
                        if arm.guard is not None:
                            walk_str(arm.guard)
            for stmt in self.program.stmts:
                if isinstance(stmt, (LetDecl, VarDecl)):
                    walk_str(stmt.value)
                elif isinstance(stmt, FnDecl):
                    if stmt.body:
                        for st in stmt.body.stmts:
                            walk_str_stmt(st)
                elif isinstance(stmt, (LetStmt, VarStmt, ExprStmt, Assign, IfStmt, WhileStmt, ForStmt, ReturnStmt)):
                    walk_str_stmt(stmt)
                elif isinstance(stmt, TypeDecl):
                    for m in stmt.members:
                        if isinstance(m.node, FnDecl) and m.node.body:
                            for st in m.node.body.stmts:
                                walk_str_stmt(st)
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
                return ty == FLOAT
            except Exception:
                return False

        def _tc_type(self, e, qname):
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
            for stmt in self.program.stmts:
                if isinstance(stmt, TypeDecl):
                    variants = [m.node for m in stmt.members if isinstance(m.node, Variant)]
                    if variants:
                        self.sum_types.add(stmt.name)
                        vindex = {}
                        vfields = {}
                        max_payload = 0
                        for vi, v in enumerate(variants):
                            vindex[v.name] = vi
                            vfs = v.fields if v.fields else [mm.node for mm in getattr(v, "members", []) if isinstance(mm.node, Field)]
                            offset = 0
                            fields = []
                            for f in vfs:
                                ty = None
                                if f.type_ is not None:
                                    try:
                                        ty = self.tc._atype(f.type_)
                                    except Exception:
                                        ty = None
                                wtype = self._wasm_type(ty) if ty is not None else WasmEncoder.I64
                                size = 8 if wtype in (WasmEncoder.I64, WasmEncoder.F64) else 4
                                if offset % 8 != 0:
                                    offset += 8 - (offset % 8)
                                fields.append((f.name, wtype, 8 + offset, ty, None))
                                offset += size
                            if offset == 0:
                                offset = 8
                            vfields[v.name] = fields
                            if offset > max_payload:
                                max_payload = offset
                        size = 8 + max_payload
                        if size < 8:
                            size = 8
                        self.variant_index[stmt.name] = vindex
                        self.variant_fields[stmt.name] = vfields
                        self.struct_layouts[stmt.name] = []
                        self.struct_sizes[stmt.name] = size
                    else:
                        offset = 0
                        fields = []
                        for m in stmt.members:
                            if isinstance(m.node, Field):
                                f = m.node
                                ty = None
                                if f.type_ is not None:
                                    try:
                                        ty = self.tc._atype(f.type_)
                                    except Exception:
                                        ty = None
                                wtype = self._wasm_type(ty) if ty is not None else WasmEncoder.I64
                                size = 8 if wtype in (WasmEncoder.I64, WasmEncoder.F64) else 4
                                # align to 8
                                if offset % 8 != 0:
                                    offset += 8 - (offset % 8)
                                fields.append((f.name, wtype, offset, ty, f.default))
                                offset += size
                        if offset == 0:
                            offset = 8
                        self.struct_layouts[stmt.name] = fields
                        self.struct_sizes[stmt.name] = offset
