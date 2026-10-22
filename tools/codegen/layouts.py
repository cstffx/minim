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
                        return WasmEncoder.I32
                    if ty[1] == "str":
                        return WasmEncoder.I32
                if ty[0] == "named":
                    return WasmEncoder.I32
                if ty[0] == "list":
                    return WasmEncoder.I32
                if ty[0] == "tuple":
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
            # return type
            if fn.ret is not None:
                results = [self._wasm_type(self.tc._atype(fn.ret))]
            else:
                results = []
            typeidx = self.enc.add_type(params, results)
            # placeholder func index assigned later; store
            self.func_typeidx[fn.name if self_type is None else f"{self_type}.{fn.name}"] = typeidx

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
                if isinstance(e, (StrLit, FStrLit)):
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
                elif isinstance(e, (TupleExpr, ListExpr, MapExpr)):
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
            # exports: export all top-level functions named main if present, plus all? Export all for testing
            for stmt in self.program.stmts:
                if isinstance(stmt, FnDecl):
                    if stmt.name in self.func_index:
                        self.enc.add_export_func(stmt.name, self.func_index[stmt.name])
            return self.enc.encode()

        def _is_float(self, e, qname):
            if isinstance(e, FloatLit):
                return True
            if isinstance(e, NameExpr):
                return e.name in self.float_vars.get(qname, set())
            if isinstance(e, BinOp):
                return self._is_float(e.left, qname) or self._is_float(e.right, qname)
            if isinstance(e, UnaryOp):
                return self._is_float(e.operand, qname)
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
                            if offset - 8 > max_payload:
                                max_payload = offset - 8
                        size = 8 + (max_payload if max_payload > 0 else 0)
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
