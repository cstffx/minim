from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class CallsMixin:
    def _gen_str_builtin_method(self, e, code, qname):
        # str methods (simple and chained)
        if (e.ops and e.ops[-1][0] == "call" and e.ops[0][0] == "field"):
            base_ty = self._tc_type(e.base, qname)
            if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                base_ty = base_ty[1]
            recv = e.base
            method = e.ops[0][1]
            if base_ty == STR and method in ("len", "upper", "lower"):
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
                    return True
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
                    return True
        return False

    def _gen_ctor_call(self, e, code, qname):
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
            self._ctor_begin(size, code)
            # tag at offset 0
            code += GLOBAL_GET(self.ctor_base_global)
            code += i32_const(tag)
            code += bytes([0x36])
            code += _uleb128_static(2)
            code += _uleb128_static(0)
            fields = self.variant_fields[type_name][variant_name]
            for i, (fname, wtype, off, fty, fdefault) in enumerate(fields):
                code += GLOBAL_GET(self.ctor_base_global)
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
                code += _uleb128_static(2 if wtype == WasmEncoder.I32 else 3)
                code += _uleb128_static(off)
            self._ctor_end(code)
            return True
        # empty map/set constructors: map[K,V]() / set[T]()
        if (isinstance(e.base, Postfix) and e.base.base is not None
                and isinstance(e.base.base, NameExpr)
                and e.base.base.name in ("map", "set")
                and e.base.ops and e.base.ops[-1][0] == "typeargs"
                and e.ops and e.ops[-1][0] == "call"):
            args = e.ops[-1][1] or []
            if not args:
                if e.base.base.name == "map":
                    self._gen_expr(MapExpr([]), code, qname)
                else:
                    self._gen_expr(SetExpr([]), code, qname)
                return True
        # constructor call for struct types
        if isinstance(e.base, NameExpr) and e.ops and e.ops[-1][0] == "call" and e.base.name in self.struct_layouts:
            callee_name = e.base.name
            args = e.ops[-1][1] or []
            # alloc
            size = self.struct_sizes[callee_name]
            self._ctor_begin(size, code)
            fields = self.struct_layouts[callee_name]
            # positional arg index
            for i, (fname, wtype, off, fty, fdefault) in enumerate(fields):
                code += GLOBAL_GET(self.ctor_base_global)
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
                code += _uleb128_static(2 if wtype == WasmEncoder.I32 else 3)
                code += _uleb128_static(off)
            self._ctor_end(code)
            return True
        return False

    def _gen_str_method_call(self, e, code, qname):
        # str methods
        if isinstance(e.base, Postfix) and e.base.ops and e.base.ops[-1][0] == "field" and e.ops and e.ops[-1][0] == "call":
            callee_name = e.base.ops[-1][1]
            base_ty = self._tc_type(e.base.base, qname)
            if base_ty == STR and callee_name == "contains":
                args = e.ops[-1][1] or []
                arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                if arg is not None:
                    self._gen_contains(arg, e.base.base, code, qname)
                    code += bytes([0xAD])  # i64.extend_i32_s
                else:
                    code += i64_const(0)
                return True
            if base_ty == STR and callee_name == "words":
                h = self._ensure_str_method_helpers()
                self._gen_expr(e.base.base, code, qname)
                code += CALL(h["words"])
                return True
            if base_ty == STR and callee_name in ("trim", "strip", "starts", "ends"):
                args = e.ops[-1][1] or []
                arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                h = self._ensure_str_method_helpers()
                self._gen_expr(e.base.base, code, qname)
                if callee_name == "trim":
                    code += i32_const(0)
                    code += i32_const(0)
                    code += CALL(h["trim"])
                elif callee_name == "strip":
                    code += i32_const(1)
                    self._gen_expr(arg, code, qname)
                    code += CALL(h["trim"])
                else:
                    self._gen_expr(arg, code, qname)
                    code += CALL(h["starts" if callee_name == "starts" else "ends"])
                    code += bytes([0xAD])
                return True
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
                    return True
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
                    return True
        return False

    def _gen_method_call(self, e, code, qname):
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
                return True
        return False

    def _gen_function_call(self, e, code, qname):
        # Determine callee
        # function call: NameExpr + call
        if isinstance(e.base, NameExpr) and e.ops and e.ops[-1][0] == "call":
            callee_name = e.base.name
            args = e.ops[-1][1] or []
            if callee_name in ("str", "int", "float", "len", "min", "max", "abs", "copy"):
                arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                if arg is None:
                    code += i64_const(0)
                    return True
                aty = self._tc_type(arg, qname)
                if isinstance(aty, tuple) and aty[0] == "borrow":
                    aty = aty[1]
                if callee_name == "str":
                    self._gen_to_str(arg, code, qname)
                elif callee_name == "int":
                    if aty == STR:
                        self._gen_expr(arg, code, qname)
                        code += CALL(self._ensure_parse_helpers()["i64"])
                    else:
                        self._gen_expr(arg, code, qname)
                        if aty == FLOAT:
                            code += bytes([0xB0])  # i64.trunc_f64_s
                elif callee_name == "float":
                    if aty == STR:
                        self._gen_expr(arg, code, qname)
                        code += CALL(self._ensure_parse_helpers()["f64"])
                    else:
                        self._gen_expr(arg, code, qname)
                        if aty != FLOAT:
                            code += bytes([0xB9])  # f64.convert_i64_s
                elif callee_name == "len":
                    if aty == STR or aty == BYTES:
                        self._gen_expr(arg, code, qname)
                        code += CALL(self._ensure_str_helpers()["len"])
                        code += bytes([0xAC])
                    elif isinstance(aty, tuple) and aty[0] == "tuple":
                        code += i64_const(len(aty[1]))
                    else:
                        self._gen_expr(arg, code, qname)
                        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                        code += bytes([0xAC])
                elif callee_name == "abs":
                    self._gen_expr(arg, code, qname)
                    if aty == FLOAT:
                        code += bytes([0x99])  # f64.abs
                    else:
                        code += i64_const(0)
                        code += bytes([0x53])  # lt_s
                        code += bytes([0x04, WasmEncoder.I64])
                        code += i64_const(0)
                        self._gen_expr(arg, code, qname)
                        code += bytes([0x7D])  # sub
                        code += bytes([0x05])
                        self._gen_expr(arg, code, qname)
                        code += END
                else:  # min / max
                    arg2 = args[1].value if (len(args) > 1 and isinstance(args[1], Arg)) else (args[1] if len(args) > 1 else None)
                    if aty == FLOAT:
                        self._gen_expr(arg, code, qname)
                        code += GLOBAL_SET(self.list_val_f64)
                        self._gen_expr(arg2, code, qname)
                        code += GLOBAL_SET(self.match_scrut_f64)
                        code += GLOBAL_GET(self.list_val_f64)
                        code += GLOBAL_GET(self.match_scrut_f64)
                        code += GLOBAL_GET(self.list_val_f64)
                        code += GLOBAL_GET(self.match_scrut_f64)
                        code += F64_LT if callee_name == "min" else F64_GT
                        code += bytes([0x1B])  # select
                    else:
                        self._gen_expr(arg, code, qname)
                        code += GLOBAL_SET(self.list_val_i64)
                        self._gen_expr(arg2, code, qname)
                        code += GLOBAL_SET(self.err_code_global)
                        code += GLOBAL_GET(self.list_val_i64)
                        code += GLOBAL_GET(self.err_code_global)
                        code += GLOBAL_GET(self.list_val_i64)
                        code += GLOBAL_GET(self.err_code_global)
                        code += bytes([0x53]) if callee_name == "min" else bytes([0x55])
                        code += bytes([0x1B])  # select
                return True
            lv = self.lambda_vars.get(qname, {}).get(callee_name)
            if lv is None:
                lv = self.lambda_vars.get(None, {}).get(callee_name)
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
                return True
            if callee_name == "err":
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
                return True
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
                if isinstance(arg_ty, tuple) and arg_ty[0] == "borrow":
                    arg_ty = arg_ty[1]
                arg_ty = self._erase_task(arg_ty)
                if (isinstance(arg_expr, (StrLit, RStrLit, MlStrLit, BytesLit, FStrLit, ItExpr))
                        or arg_ty == STR
                        or (isinstance(arg_ty, tuple) and arg_ty[0] in ("opt","res") and arg_ty[1] == STR)
                        or (isinstance(arg_ty, tuple) and arg_ty[0] == "p" and arg_ty[1] == "bytes")):
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
            return True
        return False
