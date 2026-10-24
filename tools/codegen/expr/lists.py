from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class ListsMixin:
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

    def _elem_wasm(self, elem_ty):
        if elem_ty == FLOAT:
            return WasmEncoder.F64
        if self._type_is_ptr(elem_ty):
            return WasmEncoder.I32
        return WasmEncoder.I64

    def _emit_load_slot(self, code, elem_ty, off=0):
        """Load an 8-byte collection slot; address must be on the stack."""
        if elem_ty == FLOAT:
            code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(off)
        else:
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(off)
            if self._type_is_ptr(elem_ty):
                code += bytes([0xA7])  # i32.wrap_i64

    def _store_elem(self, code, elem_ty, value_in_global):
        """Store one 8-byte slot. Address is on the stack."""
        if elem_ty == FLOAT:
            code += GLOBAL_GET(self.list_val_f64)
            code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
        else:
            code += GLOBAL_GET(self.list_val_i64)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)

    def _gen_list_optional_at(self, recv, elem_ty, code, qname, idx_expr=None, last=False):
        self._gen_expr(recv, code, qname)
        code += GLOBAL_SET(self.tmp_global)
        if last:
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(1)
            code += bytes([0x6B])
            code += GLOBAL_SET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(0)
            code += bytes([0x4A])  # i32.gt_s (len > 0)
        else:
            if idx_expr is None:
                code += i32_const(0)
            else:
                self._gen_expr(idx_expr, code, qname)
                code += bytes([0xA7])
            code += GLOBAL_SET(self.list_idx_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(0)
            code += bytes([0x4E])  # i32.ge_s (idx >= 0)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x49])  # i32.lt_u
            code += bytes([0x71])  # and
        code += GLOBAL_SET(self.set_found_global)
        code += GLOBAL_GET(self.set_found_global)
        code += IF(self._elem_wasm(elem_ty))
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        self._emit_load_slot(code, elem_ty)
        code += ELSE
        self._zero_value(elem_ty, code)
        code += END

    def _gen_list_pop(self, recv, elem_ty, code, qname):
        self._gen_expr(recv, code, qname)
        code += GLOBAL_SET(self.tmp_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += i32_const(0)
        code += bytes([0x4A])  # len > 0
        code += IF(self._elem_wasm(elem_ty))
        # load last element into the temp value
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += i32_const(1)
        code += bytes([0x6B])
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        if elem_ty == FLOAT:
            code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_SET(self.list_val_f64)
        else:
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_SET(self.list_val_i64)
        # len--
        code += GLOBAL_GET(self.tmp_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += i32_const(1)
        code += bytes([0x6B])
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
        self._load_tmp_value(elem_ty, code)
        code += ELSE
        self._zero_value(elem_ty, code)
        code += END

    def _gen_list_method(self, recv, method, args, elem_ty, code, qname):
        """Codegen for list methods returning O(T)/T. Returns True when handled."""
        arg = args[0].value if (args and isinstance(args[0], Arg)) else (args[0] if args else None)
        wt = self._elem_wasm(elem_ty)
        if method in ("get",):
            self._gen_list_optional_at(recv, elem_ty, code, qname, idx_expr=arg)
            return True
        if method == "pop":
            self._gen_list_pop(recv, elem_ty, code, qname)
            return True
        if method in ("first", "last"):
            self._gen_list_optional_at(recv, elem_ty, code, qname, last=(method == "last"))
            return True
        if method == "count":
            self._gen_expr(recv, code, qname)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0xAC])
            return True
        if method == "contains":
            self._gen_contains(arg, recv, code, qname)
            code += bytes([0xAD])
            return True
        if method == "slice":
            second = args[1].value if (len(args) > 1 and isinstance(args[1], Arg)) else (args[1] if len(args) > 1 else None)
            self._gen_expr(Postfix(recv, [("slice", arg, second)]), code, qname)
            return True
        if method == "reverse":
            self._gen_expr(recv, code, qname)
            code += GLOBAL_SET(self.tmp_global)
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += i32_const(1)
            code += bytes([0x6B])
            code += bytes([0xAD])  # extend to i64 for err_code slot
            code += GLOBAL_SET(self.err_code_global)
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += bytes([0x4E])  # i >= j
            code += bytes([0x0D, 0x01])
            # tmp = data[i]
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_SET(self.list_val_i64)
            # data[i] = data[j]
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            # data[j] = tmp
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_GET(self.list_val_i64)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(1)
            code += bytes([0x6B])
            code += bytes([0xAD])
            code += GLOBAL_SET(self.err_code_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            code += GLOBAL_GET(self.tmp_global)
            return True
        if method == "sort":
            self._gen_expr(recv, code, qname)
            code += GLOBAL_SET(self.tmp_global)
            # bubble sort: i from 0..len-1, j from 0..len-2-i
            code += i32_const(0)
            code += GLOBAL_SET(self.list_idx_global)   # i
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.list_idx_global)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += bytes([0x4E])  # i >= len
            code += bytes([0x0D, 0x01])
            code += i64_const(0)
            code += GLOBAL_SET(self.err_code_global)   # j
            code += BLOCK(BLK_VOID)
            code += LOOP(BLK_VOID)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
            code += GLOBAL_GET(self.list_idx_global)
            code += bytes([0x6B])
            code += i32_const(1)
            code += bytes([0x6B])
            code += bytes([0x4E])  # j >= len-1-i
            code += bytes([0x0D, 0x01])
            # tmp = data[j]
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if wt == WasmEncoder.F64:
                code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_SET(self.sort_val_f64)
            else:
                code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_SET(self.sort_val_i64)
            # next = data[j+1]
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(1)
            code += bytes([0x6A])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if wt == WasmEncoder.F64:
                code += bytes([0x2B]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_SET(self.list_val_f64)
            else:
                code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
                code += GLOBAL_SET(self.list_val_i64)
            # if tmp > next: store next at j, tmp at j+1
            if wt == WasmEncoder.F64:
                code += GLOBAL_GET(self.sort_val_f64)
                code += GLOBAL_GET(self.list_val_f64)
                code += bytes([0x64])  # f64.gt
            else:
                code += GLOBAL_GET(self.sort_val_i64)
                code += GLOBAL_GET(self.list_val_i64)
                code += bytes([0x55])  # i64.gt_s
            code += IF(BLK_VOID)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if wt == WasmEncoder.F64:
                code += GLOBAL_GET(self.list_val_f64)
                code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
            else:
                code += GLOBAL_GET(self.list_val_i64)
                code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += GLOBAL_GET(self.tmp_global)
            code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += i32_const(1)
            code += bytes([0x6A])
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            if wt == WasmEncoder.F64:
                code += GLOBAL_GET(self.sort_val_f64)
                code += bytes([0x39]); code += _uleb128_static(3); code += _uleb128_static(0)
            else:
                code += GLOBAL_GET(self.sort_val_i64)
                code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            code += END
            code += GLOBAL_GET(self.err_code_global)
            code += i64_const(1)
            code += bytes([0x7C])  # i64.add
            code += GLOBAL_SET(self.err_code_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(1)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.list_idx_global)
            code += bytes([0x0C, 0x00])
            code += END
            code += END
            return True
        return False

    def _gen_list_literal(self, e, code, qname):
        if not isinstance(e, ListExpr):
            return False
        items = e.items or []
        elem_ty = self._elem_type(e, qname)
        is_float = (elem_ty == FLOAT)
        is_ptr = not (elem_ty == INT or elem_ty == FLOAT or elem_ty == BOOL)
        n = len(items)
        cap = n if n > 4 else 4
        # header ptr = current heap (kept in slice_base_global: element
        # expressions may use tmp_global, e.g. tuples/structs)
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_SET(self.slice_base_global)
        # reserve header (16 bytes) + data (cap * 8)
        code += GLOBAL_GET(self.heap_global)
        code += i32_const(16 + cap * 8)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.heap_global)
        # store len
        code += GLOBAL_GET(self.slice_base_global)
        code += i32_const(n)
        code += bytes([0x36])  # i32.store
        code += _uleb128_static(2)  # align 4
        code += _uleb128_static(0)
        # store cap
        code += GLOBAL_GET(self.slice_base_global)
        code += i32_const(cap)
        code += bytes([0x36])
        code += _uleb128_static(2)
        code += _uleb128_static(4)
        # store data ptr = header + 16
        code += GLOBAL_GET(self.slice_base_global)
        code += GLOBAL_GET(self.slice_base_global)
        code += i32_const(16)
        code += bytes([0x6A])
        code += bytes([0x36])
        code += _uleb128_static(2)
        code += _uleb128_static(8)
        # store items
        for i, a in enumerate(items):
            val = a.value if isinstance(a, Arg) else a
            code += GLOBAL_GET(self.slice_base_global)
            code += i32_const(16 + i * 8)
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
        code += GLOBAL_GET(self.slice_base_global)
        return True

    def _gen_list_push(self, e, code, qname):
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
                return True
        return False
