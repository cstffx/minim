from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class AccessMixin:
    def _gen_slice(self, e, code, qname):
        # string slice: s[a:b], s[:b], s[a:]
        if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "slice":
            base_ty = self._tc_type(e.base, qname)
            if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                base_ty = base_ty[1]
            if base_ty in (STR, BYTES):
                sl = e.ops[0]
                self._gen_expr(e.base, code, qname)
                code += GLOBAL_SET(self.slice_base_global)
                if sl[1] is None:
                    code += i64_const(0)
                else:
                    self._gen_expr(sl[1], code, qname)
                code += GLOBAL_SET(self.list_val_i64)   # start (i64)
                if len(sl) <= 2 or sl[2] is None:
                    code += GLOBAL_GET(self.slice_base_global)
                    code += CALL(self._ensure_str_helpers()["len"])
                else:
                    self._gen_expr(sl[2], code, qname)
                    code += bytes([0xA7])
                # n = end - start
                code += GLOBAL_GET(self.list_val_i64)
                code += bytes([0xA7])
                code += bytes([0x6B])
                code += GLOBAL_SET(self.list_tmp_global)
                # dest = heap; heap += n + 1
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_SET(self.tmp_global)
                code += GLOBAL_GET(self.heap_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += i32_const(1)
                code += bytes([0x6A])
                code += bytes([0x6A])
                code += GLOBAL_SET(self.heap_global)
                # copy loop
                code += i32_const(0)
                code += GLOBAL_SET(self.list_idx_global)
                code += BLOCK(BLK_VOID)
                code += LOOP(BLK_VOID)
                code += GLOBAL_GET(self.list_idx_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += bytes([0x4E])  # i32.ge_s
                code += bytes([0x0D, 0x01])
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.list_idx_global)
                code += bytes([0x6A])
                code += GLOBAL_GET(self.slice_base_global)
                code += GLOBAL_GET(self.list_val_i64)
                code += bytes([0xA7])
                code += GLOBAL_GET(self.list_idx_global)
                code += bytes([0x6A])
                code += bytes([0x6A])
                code += bytes([0x2D, 0x00, 0x00])
                code += bytes([0x3A, 0x00, 0x00])
                code += GLOBAL_GET(self.list_idx_global)
                code += i32_const(1)
                code += bytes([0x6A])
                code += GLOBAL_SET(self.list_idx_global)
                code += bytes([0x0C, 0x00])
                code += END
                code += END
                # NUL terminator
                code += GLOBAL_GET(self.tmp_global)
                code += GLOBAL_GET(self.list_tmp_global)
                code += bytes([0x6A])
                code += i32_const(0)
                code += bytes([0x3A, 0x00, 0x00])
                code += GLOBAL_GET(self.tmp_global)
                return True
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
                return True
        return False

    def _gen_index(self, e, code, qname):
        # string / bytes index: s[i] -> one-char str, b[i] -> int byte
        if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "index":
            base_ty = self._tc_type(e.base, qname)
            if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                base_ty = base_ty[1]
            if base_ty in (STR, BYTES):
                self._gen_expr(e.base, code, qname)
                code += GLOBAL_SET(self.slice_base_global)
                self._gen_expr(e.ops[0][1], code, qname)
                code += bytes([0xA7])  # i32.wrap_i64
                code += GLOBAL_GET(self.slice_base_global)
                code += bytes([0x6A])
                if base_ty == BYTES:
                    # raw byte as int
                    code += bytes([0x2D, 0x00, 0x00])  # i32.load8_u
                    code += bytes([0xAD])             # i64.extend_i32_u
                else:
                    # one-character string: allocate 2 bytes
                    code += bytes([0x2D, 0x00, 0x00])
                    code += bytes([0xAD])             # i64.extend_i32_u
                    code += GLOBAL_SET(self.list_val_i64)
                    code += GLOBAL_GET(self.heap_global)
                    code += GLOBAL_SET(self.tmp_global)
                    code += GLOBAL_GET(self.heap_global)
                    code += i32_const(2)
                    code += bytes([0x6A])
                    code += GLOBAL_SET(self.heap_global)
                    code += GLOBAL_GET(self.tmp_global)
                    code += GLOBAL_GET(self.list_val_i64)
                    code += bytes([0xA7])
                    code += bytes([0x3A, 0x00, 0x00])  # i32.store8
                    code += GLOBAL_GET(self.tmp_global)
                    code += i32_const(1)
                    code += bytes([0x6A])
                    code += i32_const(0)
                    code += bytes([0x3A, 0x00, 0x00])
                    code += GLOBAL_GET(self.tmp_global)
                return True
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
                if is_float_val:
                    code += bytes([0xBF])  # f64.reinterpret_i64
                return True
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
                return True
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
                    return True
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
                return True
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
                return True
        return False

    def _gen_field(self, e, code, qname):

        # handle calls
        # field access (no call)
        if (not (e.ops and e.ops[-1][0] == "call")) and e.ops and e.ops[0][0] == "field":
            fname = e.ops[0][1]
            field_info = None
            base_ty = self._tc_type(e.base, qname)
            if isinstance(base_ty, tuple) and base_ty[0] == "borrow":
                base_ty = base_ty[1]
            candidates = []
            if isinstance(base_ty, tuple) and base_ty[0] == "named":
                candidates = [self.struct_layouts.get(base_ty[1], [])]
            if not candidates:
                candidates = list(self.struct_layouts.values())
            for fields in candidates:
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
                code += _uleb128_static(2 if wtype == WasmEncoder.I32 else 3)
                code += _uleb128_static(off)
                return True
            # zero-argument method called without parentheses: `b.len`
            if field_info is None and len(e.ops) == 1 and isinstance(base_ty, tuple) and base_ty[0] == "named":
                mdecl = self._method_decl(base_ty[1], fname)
                qmethod = f"{base_ty[1]}.{fname}"
                if (mdecl is not None and len(mdecl.params) == 1
                        and mdecl.params[0].name == "self" and qmethod in self.func_index):
                    self._gen_expr(e.base, code, qname)
                    code += CALL(self.func_index[qmethod])
                    return True
        # constructor call for sum-type variants: Type.Variant(args)
        return False

    def _gen_name_expr(self, e, code, qname):
        if not isinstance(e, NameExpr):
            return False
        if e.name == "pi":
            code += f64_const(3.141592653589793)
            return True
        if e.name == "e":
            code += f64_const(2.718281828459045)
            return True
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
                code += _uleb128_static(2 if wtype == WasmEncoder.I32 else 3)
                code += _uleb128_static(off)
            else:
                _unsupported(f"la variable/nombre '{e.name}' (no es local ni campo conocido)", e)
        return True
