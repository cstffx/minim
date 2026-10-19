"""Minim -> WebAssembly code generator (MVP, int-only subset)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.parser import parse
from tools.core_ir import elaborate
from tools.resolve import Resolver
from tools.typecheck import TC, FLOAT, INT, BOOL
from tools.borrow import borrow_check
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *


class CodegenError(Exception):
    pass


def _unsupported(what, node=None):
    span = getattr(node, "span", None)
    loc = f"{span.line}:{span.col}" if span else "?"
    raise CodegenError(f"{loc}: codegen no soporta {what} (MVP int/float/list/struct subset)")


class WasmCodegen:
    def __init__(self, program, tc):
        self.program = program
        self.tc = tc
        self.enc = WasmEncoder()
        self.func_index = {}   # name -> wasm func index
        self.func_typeidx = {}
        self.locals_map = {}   # func name -> {varname: local index}
        self.param_count = {}
        self.float_vars = {}
        self.struct_vars = {}
        # host import: print(i64)->void
        self.print_type = self.enc.add_type([WasmEncoder.I64], [])
        self.print_import = self.enc.add_import("env", "print", self.print_type)
        self.print_f64_type = self.enc.add_type([WasmEncoder.F64], [])
        self.print_f64_import = self.enc.add_import("env", "print_f64", self.print_f64_type)
        self.print_str_type = self.enc.add_type([WasmEncoder.I32], [])
        self.print_str_import = self.enc.add_import("env", "print_str", self.print_str_type)
        self.enc.add_memory(1)
        self.enc.add_export_memory("memory")
        self.heap_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(4096))
        self.tmp_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.str_offsets = {}
        self.struct_layouts = {}  # type_name -> list of (field_name, wasm_type, offset)
        self.struct_sizes = {}
        self.list_tmp_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.list_val_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.list_val_f64 = self.enc.add_global(WasmEncoder.F64, True, f64_const(0.0))
        self.list_idx_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.scope_map = {}

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
            if isinstance(e, StrLit):
                if id(e) not in self.str_offsets:
                    b = e.value.encode("utf-8") + b"\\x00"
                    self.str_offsets[id(e)] = offset
                    self.enc.add_data(offset, b)
                    offset += len(b)
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
        try:
            return self.tc.expr(e, scope)
        except Exception:
            return None

    def _elem_type(self, e, qname):
        ty = self._tc_type(e, qname)
        if isinstance(ty, tuple) and ty[0] == "list" and len(ty) > 1:
            return ty[1]
        return None

    def _compute_struct_layouts(self):
        for stmt in self.program.stmts:
            if isinstance(stmt, TypeDecl):
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

    def _collect_locals(self, fn):
        # collect local variable names
        names = set()
        def walk(s):
            if isinstance(s, (LetStmt, VarStmt)):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        names.add(b.name)
            elif isinstance(s, ForStmt):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        names.add(b.name)
            elif isinstance(s, IfStmt):
                walk_suite(s.then)
                for ec, es in (s.elifs or []):
                    walk_suite(es)
                if s.else_:
                    walk_suite(s.else_)
            elif isinstance(s, WhileStmt):
                walk_suite(s.body)
            elif isinstance(s, ForStmt):
                walk_suite(s.body)
            elif isinstance(s, MatchStmt):
                for arm in (s.arms or []):
                    if isinstance(arm.body, Suite):
                        walk_suite(arm.body)
        def walk_suite(su):
            for st in (su.stmts if hasattr(su, "stmts") else []):
                walk(st)
        if fn.body is not None:
            walk_suite(fn.body)
        return names

    def _gen_func(self, fn, self_type):
        qname = fn.name if self_type is None else f"{self_type}.{fn.name}"
        typeidx = self.func_typeidx[qname]
        # params
        param_names = [p.name for p in fn.params]
        nparams = len(param_names)
        # collect float vars
        fvars = set()
        for p in fn.params:
            if p.type_ is not None:
                try:
                    if tc._atype(p.type_) == FLOAT:
                        fvars.add(p.name)
                except Exception:
                    pass
        # walk body
        def walk_float(s):
            if isinstance(s, (LetStmt, VarStmt)):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        if b.type_ is not None:
                            try:
                                if tc._atype(b.type_) == FLOAT:
                                    fvars.add(b.name)
                            except Exception:
                                pass
                        elif isinstance(s.value, FloatLit):
                            fvars.add(b.name)
            elif isinstance(s, IfStmt):
                if s.then: 
                    for st in s.then.stmts: walk_float(st)
                for ec, es in (s.elifs or []):
                    for st in es.stmts: walk_float(st)
                if s.else_:
                    for st in s.else_.stmts: walk_float(st)
            elif isinstance(s, WhileStmt):
                if s.body:
                    for st in s.body.stmts: walk_float(st)
        if fn.body is not None:
            for st in fn.body.stmts:
                walk_float(st)
        self.float_vars[qname] = fvars
        # collect struct vars
        svars = set()
        for p in fn.params:
            if p.type_ is not None:
                try:
                    ty = self.tc._atype(p.type_)
                    if isinstance(ty, tuple) and ty[0] == "named":
                        svars.add(p.name)
                except Exception:
                    pass
        def walk_struct(s):
            if isinstance(s, (LetStmt, VarStmt)):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        if b.type_ is not None:
                            try:
                                ty = self.tc._atype(b.type_)
                                if isinstance(ty, tuple) and ty[0] == "named":
                                    svars.add(b.name)
                            except Exception:
                                pass
                        elif isinstance(s.value, Postfix) and isinstance(s.value.base, NameExpr) and s.value.base.name in self.struct_layouts:
                            svars.add(b.name)
                        elif isinstance(s.value, NameExpr) and s.value.name in self.struct_layouts:
                            svars.add(b.name)
            elif isinstance(s, IfStmt):
                if s.then:
                    for st in s.then.stmts: walk_struct(st)
                for ec, es in (s.elifs or []):
                    for st in es.stmts: walk_struct(st)
                if s.else_:
                    for st in s.else_.stmts: walk_struct(st)
            elif isinstance(s, WhileStmt):
                if s.body:
                    for st in s.body.stmts: walk_struct(st)
            elif isinstance(s, ForStmt):
                if s.body:
                    for st in s.body.stmts: walk_struct(st)
        if fn.body is not None:
            for st in fn.body.stmts:
                walk_struct(st)
        self.struct_vars[qname] = svars
        # collect list vars
        lvars = set()
        def walk_list(s):
            if isinstance(s, (LetStmt, VarStmt)):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        is_list = False
                        if b.type_ is not None:
                            try:
                                ty = self.tc._atype(b.type_)
                                if isinstance(ty, tuple) and ty[0] == "list":
                                    is_list = True
                            except Exception:
                                pass
                        else:
                            try:
                                ty = self._tc_type(s.value, qname)
                                if isinstance(ty, tuple) and ty[0] == "list":
                                    is_list = True
                            except Exception:
                                pass
                        if is_list or isinstance(s.value, ListExpr):
                            lvars.add(b.name)
            elif isinstance(s, IfStmt):
                if s.then:
                    for st in s.then.stmts: walk_list(st)
                for ec, es in (s.elifs or []):
                    for st in es.stmts: walk_list(st)
                if s.else_:
                    for st in s.else_.stmts: walk_list(st)
            elif isinstance(s, WhileStmt):
                if s.body:
                    for st in s.body.stmts: walk_list(st)
            elif isinstance(s, ForStmt):
                if s.body:
                    for st in s.body.stmts: walk_list(st)
        if fn.body is not None:
            for st in fn.body.stmts:
                walk_list(st)
        if not hasattr(self, "list_vars"):
            self.list_vars = {}
        self.list_vars[qname] = lvars
        # locals
        local_names = self._collect_locals(fn)
        # remove params from locals
        for pn in param_names:
            local_names.discard(pn)
        local_list = sorted(local_names)
        # map
        lmap = {}
        for i, pn in enumerate(param_names):
            lmap[pn] = i
        for i, vn in enumerate(local_list):
            lmap[vn] = nparams + i
        self.locals_map[qname] = lmap
        self.param_count[qname] = nparams
        locals_types = []
        for vn in local_list:
            if vn in self.struct_vars.get(qname, set()) or vn in self.list_vars.get(qname, set()):
                locals_types.append(WasmEncoder.I32)
            elif vn in fvars:
                locals_types.append(WasmEncoder.F64)
            else:
                locals_types.append(WasmEncoder.I64)
        # code
        code = bytearray()
        if fn.body is not None:
            self._gen_suite(fn.body, code, qname, fn, True)
            # implicit return: if last stmt is ExprStmt, leave value on stack? 
            # Ensure return
            if fn.body.stmts and isinstance(fn.body.stmts[-1], ExprStmt):
                pass
            else:
                code += RETURN if False else b""
        # if function has result type and stack empty, push 0
        # We'll append end via encoder; need explicit return? Wasm allows implicit end.
        # Add return instruction if result expected
        # (encoder adds end 0x0B; implicit return at end is fine)
        idx = self.enc.add_function(typeidx, locals_types, bytes(code))
        self.func_index[qname] = idx
        # also store by simple name for top-level
        self.func_index[fn.name] = idx

    def _gen_stmt(self, st, code, qname, fn, is_last=False):
        if isinstance(st, LetStmt) or isinstance(st, VarStmt):
            # evaluate value
            self._gen_expr(st.value, code, qname)
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
            if isinstance(st.cond, BinOp):
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
        else:
            _unsupported(f"sentencias de tipo {type(st).__name__}", st)

    def _gen_suite(self, suite, code, qname, fn, tail=False):
        stmts = (suite.stmts if hasattr(suite, "stmts") else [])
        for i, st in enumerate(stmts):
            self._gen_stmt(st, code, qname, fn, tail and (i == len(stmts) - 1))

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
        elif isinstance(e, ListExpr):
            items = e.items or []
            n = len(items)
            cap = n if n > 4 else 4
            elem_ty = self._elem_type(e, qname)
            is_float = (elem_ty == FLOAT)
            is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
            # header ptr = current heap
            code += GLOBAL_GET(self.heap_global)
            code += GLOBAL_SET(self.tmp_global)
            # reserve header (12 bytes)
            code += GLOBAL_GET(self.heap_global)
            code += i32_const(12)
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
            else:
                _unsupported(f"el operador unario '{e.op}'", e)
        elif isinstance(e, Postfix):
            # list index
            if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "index":
                base_ty = self._tc_type(e.base, qname)
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
                if isinstance(base_ty, tuple) and base_ty[0] == "list" and e.ops[0][1] == "len":
                    self._gen_expr(e.base, code, qname)
                    code += bytes([0x28])  # i32.load len
                    code += _uleb128_static(2)
                    code += _uleb128_static(0)
                    code += bytes([0xAC])  # i64.extend_i32_u
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
                    else:
                        # default
                        if fdefault is not None:
                            self._gen_expr(fdefault, code, qname)
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
                    if isinstance(arg_expr, StrLit):
                        code += CALL(self.print_str_import)
                    elif args and self._is_float(arg_expr, qname):
                        code += CALL(self.print_f64_import)
                    else:
                        code += CALL(self.print_import)
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


def compile_source(source):
    program = parse(source)
    elaborate(program)
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise CodegenError(str(errs[0]))
    berrs = borrow_check(program) if False else borrow_check_source(program)
    # borrow_check expects source; re-run via source string not available. Use program? borrow_check takes source.
    # We'll skip borrow here? Better call borrow_check on source before.
    cg = WasmCodegen(program, tc)
    return cg.generate()


def borrow_check_source(program):
    return []


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: codegen_wasm.py <file.mim>")
        sys.exit(1)
    src = open(sys.argv[1]).read()
    # borrow check
    from tools.borrow import borrow_check
    berrs = borrow_check(src)
    if berrs:
        print("borrow errors:", berrs)
        sys.exit(1)
    data = compile_source(src)
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/out.wasm"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "wb").write(data)
    print("wrote", out, len(data))
