from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from .util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind

class ExprMixin:
        # ------------------------------------------------------------------
        # String runtime helpers (phase 1: f-strings / str() conversions)
        # ------------------------------------------------------------------
        def _ensure_str_helpers(self):
            if getattr(self, "_str_helpers", None):
                return self._str_helpers
            self._str_helpers = {}

            # __str_len(ptr) -> i32
            t = self.enc.add_type([WasmEncoder.I32], [WasmEncoder.I32])
            c = bytearray()
            c += i32_const(0)
            c += local_set(1)
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(0)
            c += local_get(1)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])  # i32.load8_u
            c += bytes([0x45])              # i32.eqz
            c += bytes([0x0D, 0x01])
            c += local_get(1)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(1)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(1)
            idx = self.enc.add_function(t, [WasmEncoder.I32], bytes(c))
            self._str_helpers["len"] = idx

            # __str_concat(a, b) -> i32
            t = self.enc.add_type([WasmEncoder.I32, WasmEncoder.I32], [WasmEncoder.I32])
            c = bytearray()
            c += local_get(0)
            c += CALL(self._str_helpers["len"])
            c += local_set(2)  # lenA
            c += local_get(1)
            c += CALL(self._str_helpers["len"])
            c += local_set(3)  # lenB
            c += GLOBAL_GET(self.heap_global)
            c += local_set(4)  # base
            c += GLOBAL_GET(self.heap_global)
            c += local_get(2)
            c += local_get(3)
            c += bytes([0x6A])
            c += i32_const(1)
            c += bytes([0x6A])
            c += bytes([0x6A])
            c += GLOBAL_SET(self.heap_global)
            c += i32_const(0)
            c += local_set(5)  # i
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(5)
            c += local_get(2)
            c += bytes([0x48])  # lt_s
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(4)
            c += local_get(5)
            c += bytes([0x6A])
            c += local_get(0)
            c += local_get(5)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(5)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(5)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += i32_const(0)
            c += local_set(5)
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(5)
            c += local_get(3)
            c += bytes([0x48])
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(4)
            c += local_get(2)
            c += bytes([0x6A])
            c += local_get(5)
            c += bytes([0x6A])
            c += local_get(1)
            c += local_get(5)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(5)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(5)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(4)
            c += local_get(2)
            c += bytes([0x6A])
            c += local_get(3)
            c += bytes([0x6A])
            c += i32_const(0)
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(4)
            idx = self.enc.add_function(t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                                            WasmEncoder.I32], bytes(c))
            self._str_helpers["concat"] = idx

            # __to_str_i64(n) -> i32   (decimal, null terminated)
            t = self.enc.add_type([WasmEncoder.I64], [WasmEncoder.I32])
            c = bytearray()
            c += GLOBAL_GET(self.heap_global)
            c += local_set(1)  # base
            c += GLOBAL_GET(self.heap_global)
            c += i32_const(32)
            c += bytes([0x6A])
            c += GLOBAL_SET(self.heap_global)
            c += local_get(1)
            c += i32_const(31)
            c += bytes([0x6A])
            c += local_set(2)  # pos
            c += local_get(2)
            c += i32_const(0)
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(0)
            c += bytes([0x50])  # i64.eqz
            c += bytes([0x04, 0x40])
            c += local_get(2)
            c += i32_const(1)
            c += bytes([0x6B])
            c += local_set(2)
            c += local_get(1)
            c += local_get(2)
            c += bytes([0x6A])
            c += i32_const(48)
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(1)
            c += local_get(2)
            c += bytes([0x6A])
            c += RETURN
            c += END
            c += local_get(0)
            c += i64_const(0)
            c += bytes([0x53])  # i64.lt_s
            c += local_set(3)   # neg
            c += local_get(3)
            c += bytes([0x04, 0x40])
            c += local_get(0)
            c += i64_const(-1)
            c += bytes([0x7E])  # i64.mul
            c += local_set(0)
            c += END
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(0)
            c += bytes([0x50])  # eqz
            c += bytes([0x0D, 0x01])
            c += local_get(2)
            c += i32_const(1)
            c += bytes([0x6B])
            c += local_set(2)
            c += local_get(1)
            c += local_get(2)
            c += bytes([0x6A])
            c += local_get(0)
            c += i64_const(10)
            c += bytes([0x82])  # i64.rem_u
            c += bytes([0xA7])  # i32.wrap_i64
            c += i32_const(48)
            c += bytes([0x6A])
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(0)
            c += i64_const(10)
            c += bytes([0x80])  # i64.div_u
            c += local_set(0)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(3)
            c += bytes([0x04, 0x40])
            c += local_get(2)
            c += i32_const(1)
            c += bytes([0x6B])
            c += local_set(2)
            c += local_get(1)
            c += local_get(2)
            c += bytes([0x6A])
            c += i32_const(45)
            c += bytes([0x3A, 0x00, 0x00])
            c += END
            c += local_get(1)
            c += local_get(2)
            c += bytes([0x6A])
            idx = self.enc.add_function(t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                                            WasmEncoder.I64], bytes(c))
            self._str_helpers["i64"] = idx

            # __to_str_f64(x, precision) -> i32
            t = self.enc.add_type([WasmEncoder.F64, WasmEncoder.I32], [WasmEncoder.I32])
            c = bytearray()
            # neg = x < 0
            c += local_get(0)
            c += f64_const(0.0)
            c += bytes([0x63])  # f64.lt
            c += local_set(6)
            # ax = abs(x)
            c += local_get(0)
            c += bytes([0x99])  # f64.abs
            c += local_set(12)
            # scale = 10^prec
            c += i64_const(1)
            c += local_set(8)
            c += i32_const(0)
            c += local_set(4)
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(4)
            c += local_get(1)
            c += bytes([0x48])
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(8)
            c += i64_const(10)
            c += bytes([0x7E])
            c += local_set(8)
            c += local_get(4)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(4)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            # n = trunc(ax*scale + 0.5)
            c += local_get(12)
            c += local_get(8)
            c += bytes([0xBA])  # f64.convert_i64_s
            c += bytes([0xA2])  # f64.mul
            c += f64_const(0.5)
            c += bytes([0xA0])  # f64.add
            c += bytes([0xB0])  # i64.trunc_f64_s
            c += local_set(11)
            # intpart = n / scale; frac = n % scale
            c += local_get(11)
            c += local_get(8)
            c += bytes([0x80])  # i64.div_u
            c += local_set(9)
            c += local_get(11)
            c += local_get(8)
            c += bytes([0x82])  # i64.rem_u
            c += local_set(10)
            c += local_get(6)
            c += bytes([0x04, 0x40])
            c += local_get(9)
            c += i64_const(-1)
            c += bytes([0x7E])
            c += local_set(9)
            c += END
            # ptr = to_str_i64(intpart)
            c += local_get(9)
            c += CALL(self._str_helpers["i64"])
            c += local_set(2)
            c += local_get(1)
            c += bytes([0x45])
            c += bytes([0x04, 0x40])
            c += local_get(2)
            c += RETURN
            c += END
            # end = ptr + strlen(ptr); *end = '.'; end++
            c += local_get(2)
            c += local_get(2)
            c += CALL(self._str_helpers["len"])
            c += bytes([0x6A])
            c += local_set(3)
            c += local_get(3)
            c += i32_const(46)
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(3)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(3)
            # divisor = 10^(prec-1)
            c += i64_const(1)
            c += local_set(13)
            c += i32_const(0)
            c += local_set(4)
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(4)
            c += local_get(1)
            c += i32_const(1)
            c += bytes([0x6B])
            c += bytes([0x48])
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(13)
            c += i64_const(10)
            c += bytes([0x7E])
            c += local_set(13)
            c += local_get(4)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(4)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            # emit exactly prec digits
            c += i32_const(0)
            c += local_set(4)
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(4)
            c += local_get(1)
            c += bytes([0x48])
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(3)
            c += local_get(10)
            c += local_get(13)
            c += bytes([0x80])  # div_u
            c += bytes([0xA7])
            c += i32_const(48)
            c += bytes([0x6A])
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(10)
            c += local_get(13)
            c += bytes([0x82])  # rem_u
            c += local_set(10)
            c += local_get(13)
            c += i64_const(10)
            c += bytes([0x80])  # div_u
            c += local_set(13)
            c += local_get(3)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(3)
            c += local_get(4)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(4)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(3)
            c += i32_const(0)
            c += bytes([0x3A, 0x00, 0x00])
            c += local_get(2)
            idx = self.enc.add_function(t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                                            WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                                            WasmEncoder.I64, WasmEncoder.I64, WasmEncoder.I64,
                                            WasmEncoder.I64, WasmEncoder.F64, WasmEncoder.I64], bytes(c))
            self._str_helpers["f64"] = idx
            return self._str_helpers

        def _ensure_pow_helper(self):
            if getattr(self, "_pow_helper", None) is not None:
                return self._pow_helper
            t = self.enc.add_type([WasmEncoder.I64, WasmEncoder.I64], [WasmEncoder.I64])
            c = bytearray()
            c += i64_const(1)
            c += local_set(2)          # acc
            c += i64_const(0)
            c += local_set(3)          # i
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(3)
            c += local_get(1)
            c += bytes([0x53])         # i64.lt_s
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(2)
            c += local_get(0)
            c += bytes([0x7E])         # i64.mul
            c += local_set(2)
            c += local_get(3)
            c += i64_const(1)
            c += bytes([0x7C])         # i64.add
            c += local_set(3)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(2)
            self._pow_helper = self.enc.add_function(
                t, [WasmEncoder.I64, WasmEncoder.I64], bytes(c))
            return self._pow_helper

        def _ensure_str_contains_helper(self):
            if getattr(self, "_str_contains_helper", None) is not None:
                return self._str_contains_helper
            t = self.enc.add_type([WasmEncoder.I32, WasmEncoder.I32], [WasmEncoder.I32])
            c = bytearray()
            c += local_get(0)
            c += CALL(self._ensure_str_helpers()["len"])
            c += local_set(2)                     # hlen
            c += local_get(1)
            c += CALL(self._ensure_str_helpers()["len"])
            c += local_set(3)                     # nlen
            c += local_get(3)
            c += bytes([0x45])                    # nlen == 0 -> true
            c += bytes([0x04, 0x40])
            c += i32_const(1)
            c += RETURN
            c += END
            c += i32_const(0)
            c += local_set(4)                     # i
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(4)
            c += local_get(2)
            c += local_get(3)
            c += bytes([0x6B])                    # hlen - nlen
            c += bytes([0x4A])                    # i > hlen-nlen
            c += bytes([0x0D, 0x01])
            c += i32_const(0)
            c += local_set(5)                     # j
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(5)
            c += local_get(3)
            c += bytes([0x4E])                    # j >= nlen
            c += bytes([0x04, 0x40])
            c += i32_const(1)
            c += RETURN
            c += END
            c += local_get(0)
            c += local_get(4)
            c += bytes([0x6A])
            c += local_get(5)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])        # hay[i+j]
            c += local_get(1)
            c += local_get(5)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])        # needle[j]
            c += bytes([0x47])                    # i32.ne
            c += bytes([0x0D, 0x01])              # mismatch: exit inner loop
            c += local_get(5)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(5)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(4)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(4)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += i32_const(0)
            self._str_contains_helper = self.enc.add_function(
                t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                    WasmEncoder.I32, WasmEncoder.I32], bytes(c))
            return self._str_contains_helper

        def _type_from_tc(self, ty):
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
                return Type(TypeList(self._type_from_tc(ty[1])))
            return None

        def _load_captured(self, names, code, qname):
            for v in names:
                lmap = self.locals_map.get(qname, {})
                if v in lmap:
                    code += local_get(lmap[v])
                elif v in getattr(self, "module_globals", {}):
                    code += GLOBAL_GET(self.module_globals[v][0])
                else:
                    self._gen_expr(NameExpr(v), code, qname)

        def _gen_list_map(self, code, qname, recv, arg, calling_elem_ty, method):
            """list.map(fn)/list.filter(fn) -> new list."""
            src_elem = calling_elem_ty[1] if (isinstance(calling_elem_ty, tuple) and len(calling_elem_ty) > 1) else UNKNOWN
            if isinstance(arg, Lambda) and arg.params and arg.params[0].type_ is None and src_elem != UNKNOWN:
                arg.params[0].type_ = self._type_from_tc(src_elem)
            fty = self._tc_type(arg, qname)
            res_ty = fty[2] if (isinstance(fty, tuple) and fty[0] == "func") else UNKNOWN
            if method == "filter":
                res_ty = src_elem
            is_float_res = (res_ty == FLOAT)
            # receiver -> slice_base_global
            self._gen_expr(recv, code, qname)
            code += GLOBAL_SET(self.slice_base_global)
            # generate lambda (leave/drop function pointer)
            self._gen_expr(arg, code, qname)
            code += DROP
            fname = getattr(self, "_last_lambda_name", None)
            captured = list(getattr(self, "_last_lambda_captured", []))
            if fname is None or fname not in self.func_index:
                _unsupported("list.map necesita una closure", None)
            # allocate result header + data (max = src len)
            code += GLOBAL_GET(self.heap_global)
            code += GLOBAL_SET(self.tmp_global)
            code += GLOBAL_GET(self.heap_global)
            code += i32_const(16)
            code += bytes([0x6A])
            # capacity = receiver length (read from the source list, not the heap)
            code += GLOBAL_GET(self.slice_base_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_SET(self.heap_global)
            code += GLOBAL_GET(self.tmp_global)
            code += i32_const(0)
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += GLOBAL_GET(self.tmp_global)
            code += GLOBAL_GET(self.slice_base_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
            code += GLOBAL_GET(self.tmp_global)
            code += GLOBAL_GET(self.tmp_global)
            code += i32_const(16)
            code += bytes([0x6A])
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.slice_base_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x48]); code += bytes([0x45])
            code += bytes([0x0D, 0x01])
            # load element
            code += GLOBAL_GET(self.slice_base_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if src_elem == FLOAT:
                code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_SET(self.list_val_f64)
            else:
                code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                if self._type_is_ptr(src_elem):
                    code += bytes([0xA7])
                code += GLOBAL_SET(self.list_val_i64)
            # call lambda: captured params first, then the element
            self._load_captured(captured, code, qname)
            if src_elem == FLOAT:
                code += GLOBAL_GET(self.list_val_f64)
            else:
                if self._type_is_ptr(src_elem):
                    code += GLOBAL_GET(self.list_val_i64)
                    code += bytes([0xA7])
                else:
                    code += GLOBAL_GET(self.list_val_i64)
            code += CALL(self.func_index[fname])
            if method == "filter":
                # value on stack is bool (i64); keep element if truthy
                code += i64_const(0)
                code += I64_NE
                code += bytes([0x04, 0x40])
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                # reload element
                code += GLOBAL_GET(self.slice_base_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                code += GLOBAL_GET(self.list_idx_global)
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                if src_elem == FLOAT:
                    code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                    code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
                else:
                    code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                    code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                # len++
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                code += i32_const(1)
                code += bytes([0x6A])
                code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
                code += END
            else:
                # store result at data[len]
                if is_float_res:
                    code += GLOBAL_SET(self.list_val_f64)
                else:
                    code += GLOBAL_SET(self.list_val_i64)
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                code += i32_const(8)
                code += bytes([0x6C])
                code += bytes([0x6A])
                if is_float_res:
                    code += GLOBAL_GET(self.list_val_f64)
                    code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
                else:
                    code += GLOBAL_GET(self.list_val_i64)
                    code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                code += i32_const(1)
                code += bytes([0x6A])
                code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            code += GLOBAL_GET(self.tmp_global)

        def _type_is_ptr(self, ty):
            if isinstance(ty, tuple):
                if ty[0] == "p":
                    return ty[1] in ("str", "bytes")
                if ty[0] in ("named", "list", "map", "set", "tuple", "func"):
                    return True
            return False

        def _operand_is_ptr(self, e, qname):
            ty = self._tc_type(e, qname)
            if isinstance(ty, tuple):
                if ty[0] == "p":
                    return ty[1] in ("str", "bytes")
                if ty[0] in ("named", "list", "map", "set", "tuple", "func"):
                    return True
            return False

        def _gen_contains(self, needle, haystack, code, qname):
            hty = self._tc_type(haystack, qname)
            if isinstance(hty, tuple) and hty[0] == "borrow":
                hty = hty[1]
            # haystack -> tmp_global
            self._gen_expr(haystack, code, qname)
            code += GLOBAL_SET(self.tmp_global)
            if hty == STR:
                self._gen_expr(needle, code, qname)
                code += GLOBAL_SET(self.list_tmp_global)
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += CALL(self._ensure_str_contains_helper())
                return
            if not (isinstance(hty, tuple) and hty[0] in ("list", "set", "map")):
                code += i32_const(0)
                return
            if hty[0] == "map":
                elem_ty = hty[1]
                stride = 16
                is_float = (elem_ty == FLOAT)
            else:
                elem_ty = hty[1] if len(hty) > 1 else UNKNOWN
                stride = 8
                is_float = (elem_ty == FLOAT)
            # needle -> list_val
            self._gen_expr(needle, code, qname)
            if is_float:
                code += GLOBAL_SET(self.list_val_f64)
            else:
                if self._operand_is_ptr(needle, qname):
                    code += bytes([0xAC])  # pointer -> i64
                code += GLOBAL_SET(self.list_val_i64)
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)
            code += i32_const(0)
            code += GLOBAL_SET(self.set_found_global)
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x48]); code += bytes([0x45])
            code += bytes([0x0D, 0x01])
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(stride)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if is_float:
                code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.list_val_f64)
                code += F64_EQ
            else:
                code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.list_val_i64)
                code += I64_EQ
            code += bytes([0x04, 0x40])
            code += i32_const(1)
            code += GLOBAL_SET(self.set_found_global)
            code += bytes([0x0C, 0x02])
            code += END
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            code += GLOBAL_GET(self.set_found_global)

        def _ensure_parse_helpers(self):
            if getattr(self, "_parse_helpers", None):
                return self._parse_helpers
            self._parse_helpers = {}
            # __parse_i64(ptr) -> i64
            t = self.enc.add_type([WasmEncoder.I32], [WasmEncoder.I64])
            c = bytearray()
            c += i32_const(0)
            c += local_set(2)                     # neg
            c += i32_const(0)
            c += local_set(1)                     # i
            c += local_get(0)
            c += bytes([0x2D, 0x00, 0x00])        # s[0]
            c += i32_const(45)                    # '-'
            c += bytes([0x46])                    # eq
            c += bytes([0x04, 0x40])
            c += i32_const(1)
            c += local_set(2)
            c += i32_const(1)
            c += local_set(1)
            c += END
            c += i64_const(0)
            c += local_set(3)                     # acc
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(0)
            c += local_get(1)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])        # c
            c += local_set(4)
            c += local_get(4)
            c += i32_const(48)
            c += bytes([0x6B])                    # c - '0'
            c += local_set(4)
            c += local_get(4)
            c += i32_const(0)
            c += bytes([0x48])                    # < 0
            c += local_get(4)
            c += i32_const(9)
            c += bytes([0x4A])                    # > 9
            c += bytes([0x72])                    # or
            c += bytes([0x0D, 0x01])
            c += local_get(3)
            c += i64_const(10)
            c += bytes([0x7E])
            c += local_get(4)
            c += bytes([0xAC])                    # i64.extend_i32_u
            c += bytes([0x7C])
            c += local_set(3)
            c += local_get(1)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(1)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(2)
            c += bytes([0x04, 0x40])
            c += i64_const(0)
            c += local_get(3)
            c += bytes([0x7D])                    # i64.sub
            c += local_set(3)
            c += END
            c += local_get(3)
            self._parse_helpers["i64"] = self.enc.add_function(
                t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I64, WasmEncoder.I32], bytes(c))
            # __parse_f64(ptr) -> f64
            t = self.enc.add_type([WasmEncoder.I32], [WasmEncoder.F64])
            c = bytearray()
            c += i32_const(0)
            c += local_set(2)                     # neg
            c += i32_const(0)
            c += local_set(3)                     # dot
            c += i32_const(0)
            c += local_set(1)                     # i
            c += local_get(0)
            c += bytes([0x2D, 0x00, 0x00])
            c += i32_const(45)
            c += bytes([0x46])
            c += bytes([0x04, 0x40])
            c += i32_const(1)
            c += local_set(2)
            c += i32_const(1)
            c += local_set(1)
            c += END
            c += f64_const(0.0)
            c += local_set(4)                     # val
            c += f64_const(1.0)
            c += local_set(5)                     # scale
            c += BLOCK(BLK_VOID)
            c += LOOP(BLK_VOID)
            c += local_get(0)
            c += local_get(1)
            c += bytes([0x6A])
            c += bytes([0x2D, 0x00, 0x00])
            c += local_set(6)                     # c
            c += local_get(6)
            c += bytes([0x45])
            c += bytes([0x0D, 0x01])
            c += local_get(6)
            c += i32_const(46)                    # '.'
            c += bytes([0x46])
            c += bytes([0x04, 0x40])
            c += i32_const(1)
            c += local_set(3)
            c += local_get(1)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(1)
            c += bytes([0x0C, 0x01])              # continue loop
            c += END
            c += local_get(6)
            c += i32_const(48)
            c += bytes([0x6B])
            c += local_set(6)
            c += local_get(6)
            c += i32_const(0)
            c += bytes([0x48])
            c += local_get(6)
            c += i32_const(9)
            c += bytes([0x4A])
            c += bytes([0x72])
            c += bytes([0x0D, 0x01])
            c += local_get(3)
            c += bytes([0x04, 0x40])
            c += local_get(5)
            c += f64_const(10.0)
            c += bytes([0xA2])                    # scale *= 10
            c += local_set(5)
            c += local_get(4)
            c += local_get(6)
            c += bytes([0xB7])                    # f64.convert_i32_s
            c += local_get(5)
            c += bytes([0xA3])                    # / scale
            c += bytes([0xA0])                    # +
            c += local_set(4)
            c += bytes([0x05])
            c += local_get(4)
            c += f64_const(10.0)
            c += bytes([0xA2])
            c += local_get(6)
            c += bytes([0xB7])
            c += bytes([0xA0])
            c += local_set(4)
            c += END
            c += local_get(1)
            c += i32_const(1)
            c += bytes([0x6A])
            c += local_set(1)
            c += bytes([0x0C, 0x00])
            c += END
            c += END
            c += local_get(2)
            c += bytes([0x04, 0x40])
            c += f64_const(0.0)
            c += local_get(4)
            c += bytes([0xA1])                    # sub
            c += local_set(4)
            c += END
            c += local_get(4)
            self._parse_helpers["f64"] = self.enc.add_function(
                t, [WasmEncoder.I32, WasmEncoder.I32, WasmEncoder.I32,
                    WasmEncoder.F64, WasmEncoder.F64, WasmEncoder.I32], bytes(c))
            return self._parse_helpers

        def _str_ptr(self, text):
            return self._intern_str(text)

        def _gen_to_str(self, e, code, qname, prec=None):
            ty = self._tc_type(e, qname)
            helpers = self._ensure_str_helpers()
            if isinstance(e, NilLit) or ty == ("p", "nil"):
                code += i32_const(self._str_ptr("nil"))
                return
            if isinstance(e, BoolLit):
                code += i32_const(self._str_ptr("true" if e.value else "false"))
                return
            if ty == FLOAT:
                self._gen_expr(e, code, qname)
                code += i32_const(6 if prec is None else prec)
                code += CALL(helpers["f64"])
                return
            self._gen_expr(e, code, qname)
            if ty in (INT, BOOL):
                code += CALL(helpers["i64"])
            elif ty == STR or ty == ("p", "bytes"):
                pass
            else:
                _unsupported(f"interpolar un valor de tipo {ty} en f-string", e)

        def _gen_fstring(self, e, code, qname):
            raw = e.value
            parts = []  # (kind, text/prec, expr)
            buf = []
            i = 0
            n = len(raw)
            while i < n:
                c = raw[i]
                if c == "{" and i + 1 < n and raw[i + 1] == "{":
                    buf.append("{")
                    i += 2
                    continue
                if c == "}" and i + 1 < n and raw[i + 1] == "}":
                    buf.append("}")
                    i += 2
                    continue
                if c == "{":
                    if buf:
                        parts.append(("lit", decode_escapes("".join(buf))))
                        buf = []
                    depth = 1
                    j = i + 1
                    quote = None
                    while j < n and depth:
                        ch = raw[j]
                        if quote:
                            if ch == "\\":
                                j += 2
                                continue
                            if ch == quote:
                                quote = None
                        elif ch in ("'", '"'):
                            quote = ch
                        elif ch in "([{":
                            depth += 1
                        elif ch in ")]}":
                            depth -= 1
                            if depth == 0:
                                break
                        j += 1
                    if depth != 0:
                        buf.append(c)
                        i += 1
                        continue
                    inner = raw[i + 1:j]
                    fmt = None
                    # split format spec on the last top-level ':'
                    d = 0
                    q = None
                    for k, ch in enumerate(inner):
                        if q:
                            if ch == "\\":
                                continue
                            if ch == q:
                                q = None
                        elif ch in ("'", '"'):
                            q = ch
                        elif ch in "([{":
                            d += 1
                        elif ch in ")]}":
                            d -= 1
                        elif ch == ":" and d == 0:
                            fmt = inner[k + 1:]
                            inner = inner[:k]
                            break
                    parts.append(("expr", fmt, inner.strip()))
                    i = j + 1
                    continue
                buf.append(c)
                i += 1
            if buf:
                parts.append(("lit", decode_escapes("".join(buf))))
            if not parts:
                code += i32_const(self._str_ptr(""))
                return
            acc = None
            helpers = self._ensure_str_helpers()
            from tools.parser import parse as _parse
            from tools.nodes import ExprStmt as _ExprStmt
            for part in parts:
                if part[0] == "lit":
                    ptr = self._str_ptr(part[1])
                    code += i32_const(ptr)
                else:
                    fmt = part[1] or ""
                    try:
                        prog = _parse(part[2])
                        ex = prog.stmts[0].expr
                    except Exception:
                        _unsupported(f"la expresion interpolada {part[2]!r}", e)
                    prec = None
                    import re as _re
                    m = _re.fullmatch(r"\.(\d+)f", fmt)
                    if m:
                        prec = int(m.group(1))
                    self._gen_to_str(ex, code, qname, prec)
                if acc is not None:
                    code += CALL(helpers["concat"])
                acc = True
            return

        def _gen_set_literal(self, e, qname, code):
            items = e.items or []
            items = [a.value if isinstance(a, Arg) else a for a in items]
            elem_ty = self._tc_type(e, qname)
            elem_ty = elem_ty[1] if isinstance(elem_ty, tuple) and elem_ty[0] == "set" else UNKNOWN
            is_float = (elem_ty == FLOAT)
            is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
            # Reuse the list layout (len, cap, data) and deduplicate on insert.
            cap = len(items) if len(items) > 4 else 4
            code += GLOBAL_GET(self.heap_global)
            code += GLOBAL_SET(self.tmp_global)
            code += GLOBAL_GET(self.heap_global)
            code += i32_const(16)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.heap_global)
            code += GLOBAL_GET(self.heap_global)
            code += GLOBAL_SET(self.list_tmp_global)
            code += GLOBAL_GET(self.heap_global)
            code += i32_const(cap * 8)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.heap_global)
            # len = 0
            code += GLOBAL_GET(self.tmp_global)
            code += i32_const(0)
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += GLOBAL_GET(self.tmp_global)
            code += i32_const(cap)
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
            code += GLOBAL_GET(self.tmp_global)
            code += GLOBAL_GET(self.list_tmp_global)
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
            for val in items:
                self._gen_expr(val, code, qname)
                if is_float:
                    code += GLOBAL_SET(self.list_val_f64)
                elif is_ptr:
                    code += bytes([0xAC])
                    code += GLOBAL_SET(self.list_val_i64)
                else:
                    code += GLOBAL_SET(self.list_val_i64)
                self._emit_set_insert(code, is_float)
            code += GLOBAL_GET(self.tmp_global)

        def _emit_set_insert(self, code, is_float):
            # insert list_val into set pointer tmp_global if not already present
            code += i32_const(0)
            code += GLOBAL_SET(self.set_found_global)
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x48]); code += bytes([0x45])
            code += bytes([0x0D, 0x01])
            # compare existing
            code += GLOBAL_GET(self.list_tmp_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if is_float:
                code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.list_val_f64)
                code += F64_EQ
            else:
                code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.list_val_i64)
                code += I64_EQ
            code += bytes([0x04, 0x40])
            code += i32_const(1)
            code += GLOBAL_SET(self.set_found_global)
            code += bytes([0x0C, 0x02])  # br exit block (if=0, loop=1, block=2)
            code += END
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            # append unless already present
            code += GLOBAL_GET(self.set_found_global)
            code += bytes([0x45])  # i32.eqz
            code += bytes([0x04, 0x40])
            code += GLOBAL_GET(self.list_tmp_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if is_float:
                code += GLOBAL_GET(self.list_val_f64)
                code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
            else:
                code += GLOBAL_GET(self.list_val_i64)
                code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_GET(self.tmp_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(1)
            code += bytes([0x6A])
            code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += END

        def _gen_expr(self, e, code, qname):
            # module-qualified access: `mod.fn(...)`, `mod.CONST`,
            # `mod.Type(...)`, `mod.Type.Variant(...)`. The parser nests one
            # Postfix wrapper per operation, so flatten the chain first.
            if isinstance(e, Postfix):
                chain, cur = [], e
                while isinstance(cur, Postfix):
                    chain.append(cur.ops or [])
                    cur = cur.base
                flat = [op for ops in reversed(chain) for op in ops]
                if isinstance(cur, NameExpr) and flat and flat[0][0] == "field":
                    qn = f"{cur.name}.{flat[0][1]}"
                    known = (qn in self.func_index or qn in getattr(self, "module_globals", {})
                             or qn in self.struct_layouts or qn in self.sum_types)
                    if (known and cur.name in getattr(self.tc, "module_aliases", {})
                            and flat[0][1].startswith("_")):
                        known = False
                    if known:
                        rest = flat[1:]
                        if not rest:
                            return self._gen_expr(NameExpr(qn), code, qname)
                        rebuilt = NameExpr(qn)
                        for op in rest:
                            rebuilt = Postfix(rebuilt, [op])
                        return self._gen_expr(rebuilt, code, qname)
            if isinstance(e, IntLit):
                code += i64_const(int(e.value))
            elif isinstance(e, FloatLit):
                code += f64_const(float(e.value))
            elif isinstance(e, BoolLit):
                code += i64_const(1 if e.value else 0)
            elif isinstance(e, FStrLit):
                self._gen_fstring(e, code, qname)
            elif isinstance(e, (StrLit, RStrLit, MlStrLit)):
                ptr = self.str_offsets.get(id(e), 0)
                code += i32_const(ptr)
            elif isinstance(e, BytesLit):
                ptr = self.str_offsets.get(id(e), 0)
                code += i32_const(ptr)
            elif isinstance(e, NilLit):
                code += i64_const(0)
            elif isinstance(e, SetExpr):
                self._gen_set_literal(e, qname, code)
            elif isinstance(e, ItExpr):
                lmap = self.locals_map.get(qname, {})
                if "it" in lmap:
                    code += local_get(lmap["it"])
                else:
                    _unsupported("'it' fuera de una closure implicita", e)
            elif isinstance(e, SelfExpr):
                code += local_get(0)
            elif isinstance(e, BorrowExpr):
                self._gen_expr(e.operand, code, qname)
            elif isinstance(e, IfExpr):
                cond = e.cond
                self._bool_cond(cond, code, qname)
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
                code += i32_const(16 + cap * 16)
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
                    elif self._operand_is_ptr(val, qname):
                        code += bytes([0xAC])
                    code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_GET(self.tmp_global)
                return
            elif isinstance(e, ListExpr):
                items = e.items or []
                elem_ty = self._elem_type(e, qname)
                is_float = (elem_ty == FLOAT)
                is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
                n = len(items)
                cap = n if n > 4 else 4
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
                lmap = self.locals_map.get(qname, {})
                if e.name in lmap:
                    code += local_get(lmap[e.name])
                elif e.name in getattr(self, "module_globals", {}):
                    idx, wtype, ty = self.module_globals[e.name]
                    code += GLOBAL_GET(idx)
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
                        code += i64_const(0)
                        code += I64_NE
                        code += IF(BLK_I64)
                        code += i64_const(1)
                        code += ELSE
                        self._gen_expr(e.right, code, qname)
                        code += END
                    return
                if op == "and":
                    self._gen_expr(e.left, code, qname)
                    code += i64_const(0)
                    code += I64_NE
                    code += IF(BLK_I64)
                    self._gen_expr(e.right, code, qname)
                    code += ELSE
                    code += i64_const(0)
                    code += END
                    return
                if op == "in":
                    self._gen_contains(e.left, e.right, code, qname)
                    code += bytes([0xAD])
                    return
                f = self._is_float(e, qname)
                self._gen_expr(e.left, code, qname)
                if not f and self._operand_is_ptr(e.left, qname):
                    code += bytes([0xAC])
                self._gen_expr(e.right, code, qname)
                if not f and self._operand_is_ptr(e.right, qname):
                    code += bytes([0xAC])
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
                        code += bytes([0xAD])
                    elif op == ">=":
                        code += F64_GE
                        code += bytes([0xAD])
                    elif op == "<":
                        code += F64_LT
                        code += bytes([0xAD])
                    elif op == ">":
                        code += F64_GT
                        code += bytes([0xAD])
                    elif op == "==":
                        code += F64_EQ
                        code += bytes([0xAD])
                    elif op == "!=":
                        code += F64_NE
                        code += bytes([0xAD])
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
                        code += bytes([0xAD])
                    elif op == ">=":
                        code += I64_GE_S
                        code += bytes([0xAD])
                    elif op == "<":
                        code += I64_LT_S
                        code += bytes([0xAD])
                    elif op == ">":
                        code += I64_GT_S
                        code += bytes([0xAD])
                    elif op == "==":
                        code += I64_EQ
                        code += bytes([0xAD])
                    elif op == "!=":
                        code += I64_NE
                        code += bytes([0xAD])
                    elif op in ("is", "is not"):
                        # identity: values are integers/pointers in v0.1
                        code += I64_EQ
                        if op == "is not":
                            code += bytes([0x45])
                        code += bytes([0xAD])
                    elif op == "&":
                        code += bytes([0x83])
                    elif op == "|":
                        code += bytes([0x84])
                    elif op == "^":
                        code += bytes([0x85])
                    elif op == "<<":
                        code += bytes([0x86])
                    elif op == ">>":
                        code += bytes([0x87])
                    elif op == "**":
                        code += CALL(self._ensure_pow_helper())
                    elif op == "//":
                        code += I64_DIV_S
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
                elif e.op == "~":
                    self._gen_expr(e.operand, code, qname)
                    code += i64_const(-1)
                    code += bytes([0x85])  # i64.xor
                elif e.op == "not":
                    self._gen_expr(e.operand, code, qname)
                    if self._tc_type(e.operand, qname) == FLOAT:
                        code += f64_const(0.0)
                        code += F64_EQ
                    else:
                        code += I64_EQZ
                    code += bytes([0xAD])
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
                # tuple field access: t.0, t.1, ...
                if ((not (e.ops and e.ops[-1][0] == "call")) and e.ops
                        and e.ops[0][0] == "field" and isinstance(e.ops[0][1], int)):
                    tup_ty = self._tc_type(e.base, qname)
                    if isinstance(tup_ty, tuple) and tup_ty[0] == "borrow":
                        tup_ty = tup_ty[1]
                    if isinstance(tup_ty, tuple) and tup_ty[0] == "tuple":
                        idx = e.ops[0][1]
                        _size, fields = self._tuple_layout(tup_ty)
                        if 0 <= idx < len(fields):
                            wtype, off, _ty = fields[idx]
                            self._gen_expr(e.base, code, qname)
                            if wtype == WasmEncoder.F64:
                                code += bytes([0x2B])
                            elif wtype == WasmEncoder.I32:
                                code += bytes([0x28])
                            else:
                                code += bytes([0x29])
                            # alignment is log2(natural size): f64/i64 -> 3, i32 -> 2
                            code += _uleb128_static(2 if wtype == WasmEncoder.I32 else 3)
                            code += _uleb128_static(off)
                            return
                # list field access: .len
                if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "field":
                    base_ty = self._tc_type(e.base, qname)
                    if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                        base_ty = base_ty[1]
                    if isinstance(base_ty, tuple) and base_ty[0] in ("list", "set", "map") and e.ops[0][1] == "len":
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
                        # push returns nil: leave nothing on the stack
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
                    if base_ty == STR and callee_name == "contains":
                        args = e.ops[-1][1] or []
                        arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                        if arg is not None:
                            self._gen_contains(arg, e.base.base, code, qname)
                            code += bytes([0xAD])  # i64.extend_i32_s
                        else:
                            code += i64_const(0)
                        return
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
                # set / map methods
                if (isinstance(e.base, Postfix) and e.base.ops
                        and e.base.ops[-1][0] == "field" and e.ops and e.ops[-1][0] == "call"):
                    recv = e.base.base
                    method = e.base.ops[-1][1]
                    rty = self._tc_type(recv, qname)
                    if isinstance(rty, tuple) and rty[0] == "borrow":
                        rty = rty[1]
                    args = e.ops[-1][1] or []
                    arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                    if isinstance(rty, tuple) and rty[0] == "list" and method in ("map", "filter", "len"):
                        if method == "len":
                            self._gen_expr(recv, code, qname)
                            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                            code += bytes([0xAC])
                            return
                        self._gen_list_map(code, qname, recv, arg, rty, method)
                        return
                    if isinstance(rty, tuple) and rty[0] == "set" and method in ("add", "push", "contains", "len"):
                        if method == "len":
                            self._gen_expr(recv, code, qname)
                            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                            code += bytes([0xAC])
                            return
                        if method == "contains":
                            self._gen_contains(arg, recv, code, qname)
                            code += bytes([0xAD])
                            return
                        elem_ty = rty[1] if len(rty) > 1 else UNKNOWN
                        is_float = (elem_ty == FLOAT)
                        self._gen_expr(arg, code, qname)
                        if is_float:
                            code += GLOBAL_SET(self.list_val_f64)
                        else:
                            if self._operand_is_ptr(arg, qname):
                                code += bytes([0xAC])
                            code += GLOBAL_SET(self.list_val_i64)
                        self._gen_expr(recv, code, qname)
                        code += GLOBAL_SET(self.tmp_global)
                        self._emit_set_insert(code, is_float)
                        return
                    if isinstance(rty, tuple) and rty[0] == "map" and method in ("len", "has", "get"):
                        if method == "len":
                            self._gen_expr(recv, code, qname)
                            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                            code += bytes([0xAC])
                            return
                        if method == "has":
                            self._gen_contains(arg, recv, code, qname)
                            code += bytes([0xAD])
                            return
                        self._gen_expr(Postfix(recv, [("index", arg)]), code, qname)
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
                    if callee_name in ("str", "int", "float", "len", "min", "max", "abs", "copy"):
                        arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
                        if arg is None:
                            code += i64_const(0)
                            return
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
                        return
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
                        if (isinstance(arg_expr, (StrLit, RStrLit, MlStrLit, BytesLit, FStrLit))
                                or arg_ty == STR
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
                else:
                    _unsupported(
                        "esta forma de acceso/llamada (map, string methods, modulos "
                        "como fs/env, closures, o metodos no registrados)", e)
            else:
                _unsupported(f"expresiones de tipo {type(e).__name__}", e)
