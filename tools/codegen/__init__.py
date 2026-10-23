"""Minim -> WebAssembly code generator (MVP, int-only subset)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.parser import parse
from tools.core_ir import elaborate
from tools.resolve import Resolver, Scope, Symbol, SymKind
from tools.typecheck import TC, FLOAT, INT, BOOL, UNKNOWN, STR, BYTES
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *


class CodegenError(Exception):
    pass


from .util import _unsupported

from .match import MatchMixin
from .layouts import LayoutsMixin
from .stmt import StmtMixin
from .expr import ExprMixin

class WasmCodegen(MatchMixin, LayoutsMixin, StmtMixin, ExprMixin):
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
        self.str_value_offsets = {}
        self.struct_layouts = {}  # type_name -> list of (field_name, wasm_type, offset)
        self.struct_sizes = {}
        self.list_tmp_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.list_val_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.list_val_f64 = self.enc.add_global(WasmEncoder.F64, True, f64_const(0.0))
        self.sort_val_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.sort_val_f64 = self.enc.add_global(WasmEncoder.F64, True, f64_const(0.0))
        self.list_idx_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.ctor_base_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.set_found_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.match_scrut_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.match_scrut_f64 = self.enc.add_global(WasmEncoder.F64, True, f64_const(0.0))
        self.match_addr_i64 = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.tuple_base_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.tuple_save_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.slice_base_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.err_flag_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.err_msg_global = self.enc.add_global(WasmEncoder.I32, True, i32_const(0))
        self.err_code_global = self.enc.add_global(WasmEncoder.I64, True, i64_const(0))
        self.sum_types = set()
        self.variant_index = {}   # type_name -> {variant_name: tag}
        self.variant_fields = {}  # type_name -> {variant_name: [(name,wtype,offset,ty,default)]}
        self.scope_map = {}
        self._lambda_counter = 0
        self.lambda_vars = {}
        self._map_get_helpers = {}  # (is_float) -> func idx


    def _collect_locals(self, fn, qname=None):
        if qname is None:
            qname = fn.name        # collect local variable names
        names = set()
        def _collect_from_expr(e):
            if isinstance(e, MatchExpr):
                for name in self._match_bound_types(e, qname):
                    names.add(name)
                _collect_from_expr(e.expr)
                for arm in (e.arms or []):
                    if arm.guard is not None:
                        _collect_from_expr(arm.guard)
                    if isinstance(arm.body, Suite):
                        walk_suite(arm.body)
                    elif arm.body is not None:
                        _collect_from_expr(arm.body)
            elif isinstance(e, IfExpr):
                _collect_from_expr(e.then)
                _collect_from_expr(e.else_)
            elif isinstance(e, BinOp):
                _collect_from_expr(e.left)
                if isinstance(e.right, OrBlock):
                    names.add("it")
                    for st in (e.right.body.stmts if hasattr(e.right.body, "stmts") else []):
                        walk(st)
                else:
                    _collect_from_expr(e.right)
            elif isinstance(e, UnaryOp):
                _collect_from_expr(e.operand)
            elif isinstance(e, Postfix):
                _collect_from_expr(e.base)
                for op in (e.ops or []):
                    if op[0] == "call":
                        for a in (op[1] or []):
                            _collect_from_expr(a.value if isinstance(a, Arg) else a)
                    elif op[0] in ("index", "slice"):
                        if isinstance(op[1], object) and not isinstance(op[1], str):
                            _collect_from_expr(op[1])
            elif isinstance(e, (TupleExpr, ListExpr, MapExpr, SetExpr)):
                for a in (getattr(e, "items", None) or []):
                    _collect_from_expr(a.value if isinstance(a, Arg) else a)
            elif isinstance(e, Call) if False else False:
                pass
        def walk(s):
            if isinstance(s, (LetDecl, VarDecl)):
                _collect_from_expr(s.value)
            elif isinstance(s, (LetStmt, VarStmt)):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        names.add(b.name)
                _collect_from_expr(s.value)
            elif isinstance(s, ExprStmt):
                _collect_from_expr(s.expr)
            elif isinstance(s, ReturnStmt) and s.value is not None:
                _collect_from_expr(s.value)
            elif isinstance(s, ForStmt):
                for b in s.bindings:
                    if b.kind == "name" and b.name:
                        names.add(b.name)
            elif isinstance(s, IfStmt):
                _collect_from_expr(s.cond)
                walk_suite(s.then)
                for ec, es in (s.elifs or []):
                    _collect_from_expr(ec)
                    walk_suite(es)
                if s.else_:
                    walk_suite(s.else_)
            elif isinstance(s, WhileStmt):
                _collect_from_expr(s.cond)
                walk_suite(s.body)
            elif isinstance(s, ForStmt):
                walk_suite(s.body)
            elif isinstance(s, MatchStmt):
                for arm in (s.arms or []):
                    if isinstance(arm.body, Suite):
                        walk_suite(arm.body)
                    elif arm.body is not None:
                        _collect_from_expr(arm.body)
                    if arm.guard is not None:
                        _collect_from_expr(arm.guard)
                for name in self._match_bound_types(s, qname):
                    names.add(name)
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
                    if self._erase_task(tc._atype(p.type_)) == FLOAT:
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
                                if self._erase_task(tc._atype(b.type_)) == FLOAT:
                                    fvars.add(b.name)
                            except Exception:
                                pass
                        elif isinstance(s.value, FloatLit):
                            fvars.add(b.name)
                        else:
                            try:
                                ty = self._tc_type(s.value, qname)
                                while isinstance(ty, tuple) and ty[0] in ("opt", "res", "borrow"):
                                    ty = ty[1]
                                if ty == FLOAT:
                                    fvars.add(b.name)
                            except Exception:
                                pass
                vty = self._tc_type(s.value, qname)
                if isinstance(vty, tuple) and vty[0] == "tuple" and len(s.bindings) > 1:
                    for b, et in zip(s.bindings, vty[1]):
                        if getattr(b, "kind", None) == "name" and et == FLOAT:
                            fvars.add(b.name)
                if isinstance(s.value, MatchExpr):
                    for name, ty in self._match_bound_types(s.value, qname).items():
                        if ty == FLOAT:
                            fvars.add(name)
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
            elif isinstance(s, MatchStmt):
                for arm in (s.arms or []):
                    if isinstance(arm.body, Suite):
                        for st in arm.body.stmts: walk_float(st)
                for name, ty in self._match_bound_types(s, qname).items():
                    if ty == FLOAT:
                        fvars.add(name)
        if fn.body is not None:
            for st in fn.body.stmts:
                walk_float(st)
        self.float_vars[qname] = fvars
        # collect struct vars
        svars = set()
        for p in fn.params:
            if p.type_ is not None:
                try:
                    ty = self._erase_task(self.tc._atype(p.type_))
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
                                ty = self._erase_task(self.tc._atype(b.type_))
                                if isinstance(ty, tuple) and ty[0] == "named":
                                    svars.add(b.name)
                                if ty == STR or ty == BYTES:
                                    svars.add(b.name)
                            except Exception:
                                pass
                        elif isinstance(s.value, Postfix) and isinstance(s.value.base, NameExpr) and s.value.base.name in self.struct_layouts:
                            svars.add(b.name)
                        elif isinstance(s.value, NameExpr) and s.value.name in self.struct_layouts:
                            svars.add(b.name)
                if isinstance(s.value, TupleExpr):
                    svars.add(b.name)
                vty = self._tc_type(s.value, qname)
                if isinstance(vty, tuple) and vty[0] == "tuple" and len(s.bindings) > 1:
                    for b, et in zip(s.bindings, vty[1]):
                        if getattr(b, "kind", None) == "name" and self._type_is_ptr(et):
                            svars.add(b.name)
                if isinstance(s.value, (Lambda, MoveExpr)):
                    svars.add(b.name)
                ty = self._tc_type(s.value, qname)
                if isinstance(ty, tuple) and ty[0] == "tuple":
                    svars.add(b.name)
                if ty == STR or ty == BYTES:
                    svars.add(b.name)
                if isinstance(ty, tuple) and ty[0] in ("map", "set", "func"):
                    svars.add(b.name)
                if isinstance(s.value, MatchExpr):
                    for name, ty in self._match_bound_types(s.value, qname).items():
                        if isinstance(ty, tuple) and ty[0] in ("named", "tuple"):
                            svars.add(name)
                        if ty == STR:
                            svars.add(name)
                if len(s.bindings) == 1:
                    try:
                        vty = self._tc_type(s.value, qname)
                    except Exception:
                        vty = None
                    if self._type_is_ptr(vty):
                        for b in s.bindings:
                            if getattr(b, "kind", None) == "name" and b.name:
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
            elif isinstance(s, MatchStmt):
                for arm in (s.arms or []):
                    if isinstance(arm.body, Suite):
                        for st in arm.body.stmts: walk_struct(st)
                for name, ty in self._match_bound_types(s, qname).items():
                    if isinstance(ty, tuple) and ty[0] in ("named", "tuple"):
                        svars.add(name)
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
                                ty = self._erase_task(self.tc._atype(b.type_))
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
                if isinstance(s.value, MatchExpr):
                    for name, ty in self._match_bound_types(s.value, qname).items():
                        if isinstance(ty, tuple) and ty[0] == "list":
                            lvars.add(name)
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
            elif isinstance(s, MatchStmt):
                for arm in (s.arms or []):
                    if isinstance(arm.body, Suite):
                        for st in arm.body.stmts: walk_list(st)
                for name, ty in self._match_bound_types(s, qname).items():
                    if isinstance(ty, tuple) and ty[0] == "list":
                        lvars.add(name)
        if fn.body is not None:
            for st in fn.body.stmts:
                walk_list(st)
        if not hasattr(self, "list_vars"):
            self.list_vars = {}
        self.list_vars[qname] = lvars
        # locals
        local_names = self._collect_locals(fn, qname)
        # `it` in an `or:` block is the error message (a str pointer).
        if "it" in local_names:
            svars.add("it")
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
        code += i32_const(0)
        code += GLOBAL_SET(self.err_flag_global)
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



def compile_source(source, filename=None):
    program = parse(source)
    from tools.modules import load_modules
    base = os.path.dirname(os.path.abspath(filename)) if filename else os.getcwd()
    load_modules(program, base)
    # Typecheck before elaboration so `for` loops can be desugared with the
    # static type of the iterable (maps vs lists), then re-check the core IR.
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise CodegenError(str(errs[0]))
    elaborate(program, tc)
    from tools.monomorph import monomorphize
    try:
        program = monomorphize(program)
    except ValueError as e:
        raise CodegenError(str(e))
    tc = TC(program)
    errs = tc.check()
    if errs:
        raise CodegenError(str(errs[0]))
    cg = WasmCodegen(program, tc)
    return cg.generate()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: codegen_wasm.py <file.mim>")
        sys.exit(1)
    src = open(sys.argv[1]).read()
    data = compile_source(src)
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/out.wasm"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "wb").write(data)
    print("wrote", out, len(data))
