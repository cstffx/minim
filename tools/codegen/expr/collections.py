from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class CollectionsMixin:
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
        # grow when len == cap: newcap = cap*2 + 4
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(4)
        code += bytes([0x46])  # i32.eq
        code += bytes([0x04, 0x40])
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(4)
        code += i32_const(2)
        code += bytes([0x6C])
        code += i32_const(4)
        code += bytes([0x6A])
        code += bytes([0xAD])
        code += GLOBAL_SET(self.err_code_global)   # newcap
        # new data pointer
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_SET(self.slice_base_global)
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_SET(self.heap_global)
        # copy old entries
        code += i32_const(0)
        code += GLOBAL_SET(self.list_idx_global)
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.list_idx_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += bytes([0x4E])
        code += bytes([0x0D, 0x01])
        code += GLOBAL_GET(self.slice_base_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(1)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.list_idx_global)
        code += bytes([0x0C, 0x00])
        code += END
        code += END
        # header = new data/cap
        code += GLOBAL_GET(self.tmp_global)
        code += GLOBAL_GET(self.slice_base_global)
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
        code += GLOBAL_GET(self.tmp_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
        code += END
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

    def _gen_set_remove(self, code, is_float):
        """Remove list_val from the set at tmp_global (no-op when absent)."""
        code += i32_const(0)
        code += GLOBAL_SET(self.set_found_global)
        code += i32_const(0)
        code += GLOBAL_SET(self.list_idx_global)
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.list_idx_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += bytes([0x4E])
        code += bytes([0x0D, 0x01])
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
        code += bytes([0x04, 0x40])
        # shift entries down from list_idx
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(1)
        code += bytes([0x6A])
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += bytes([0x4E])  # i+1 >= len
        code += bytes([0x0D, 0x01])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(1)
        code += bytes([0x6A])
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(1)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.list_idx_global)
        code += bytes([0x0C, 0x00])
        code += END
        code += END
        code += GLOBAL_GET(self.tmp_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += i32_const(1)
        code += bytes([0x6B])
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += END

    def _gen_map_del(self, code):
        """Remove list_val key from the map at tmp_global/data in list_tmp_global."""
        code += i32_const(0)
        code += GLOBAL_SET(self.set_found_global)
        code += i32_const(0)
        code += GLOBAL_SET(self.list_idx_global)
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.list_idx_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += bytes([0x4E])
        code += bytes([0x0D, 0x01])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
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
        code += bytes([0x04, 0x40])
        # j = idx
        code += GLOBAL_GET(self.list_idx_global)
        code += bytes([0xAD])
        code += GLOBAL_SET(self.err_code_global)
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(1)
        code += bytes([0x6A])
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += bytes([0x4E])
        code += bytes([0x0D, 0x01])
        # copy key+value (16 bytes) from j+1 to j
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(1)
        code += bytes([0x6A])
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.err_code_global)
        code += bytes([0xA7])
        code += i32_const(1)
        code += bytes([0x6A])
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(8)
        code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(8)
        code += GLOBAL_GET(self.err_code_global)
        code += i64_const(1)
        code += bytes([0x7C])
        code += GLOBAL_SET(self.err_code_global)
        code += bytes([0x0C, 0x00])
        code += END
        code += END
        code += GLOBAL_GET(self.tmp_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += i32_const(1)
        code += bytes([0x6B])
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += END

    def _gen_map_collect(self, recv, map_ty, kind, code, qname):
        """Build a list with keys/values/items of a map."""
        self._gen_expr(recv, code, qname)
        code += GLOBAL_SET(self.tmp_global)
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += GLOBAL_SET(self.set_found_global)      # len
        code += GLOBAL_GET(self.tmp_global)
        code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
        code += GLOBAL_SET(self.list_tmp_global)       # map data
        # result header
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_SET(self.slice_base_global)
        code += GLOBAL_GET(self.heap_global)
        code += i32_const(16)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.heap_global)
        # result data
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_SET(self.tuple_save_global)
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_GET(self.set_found_global)
        code += i32_const(8)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += GLOBAL_SET(self.heap_global)
        # header fields
        code += GLOBAL_GET(self.slice_base_global)
        code += GLOBAL_GET(self.set_found_global)
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(0)
        code += GLOBAL_GET(self.slice_base_global)
        code += GLOBAL_GET(self.set_found_global)
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(4)
        code += GLOBAL_GET(self.slice_base_global)
        code += GLOBAL_GET(self.tuple_save_global)
        code += bytes([0x36]); code += _uleb128_static(2); code += _uleb128_static(8)
        # loop
        code += i32_const(0)
        code += GLOBAL_SET(self.list_idx_global)
        code += BLOCK(BLK_VOID)
        code += LOOP(BLK_VOID)
        code += GLOBAL_GET(self.list_idx_global)
        code += GLOBAL_GET(self.set_found_global)
        code += bytes([0x4E])
        code += bytes([0x0D, 0x01])
        # entry addr in err_code (i64) temporarily -> use list_val? keep key in list_val_i64
        code += GLOBAL_GET(self.list_tmp_global)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(16)
        code += bytes([0x6C])
        code += bytes([0x6A])
        code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += GLOBAL_SET(self.list_val_i64)
        if kind == "keys":
            code += GLOBAL_GET(self.tuple_save_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_GET(self.list_val_i64)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        elif kind == "values":
            code += GLOBAL_GET(self.tuple_save_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_GET(self.list_tmp_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(16)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(8)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        else:  # items
            # tuple = heap (16 bytes)
            code += GLOBAL_GET(self.heap_global)
            code += bytes([0xAD])
            code += GLOBAL_SET(self.err_code_global)
            code += GLOBAL_GET(self.heap_global)
            code += i32_const(16)
            code += bytes([0x6A])
            code += GLOBAL_SET(self.heap_global)
            # tuple[0] = key
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += GLOBAL_GET(self.list_val_i64)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
            # tuple[1] = value
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0xA7])
            code += GLOBAL_GET(self.list_tmp_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(16)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += bytes([0x29]); code += _uleb128_static(3); code += _uleb128_static(8)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(8)
            # list[i] = tuple ptr
            code += GLOBAL_GET(self.tuple_save_global)
            code += GLOBAL_GET(self.list_idx_global)
            code += i32_const(8)
            code += bytes([0x6C])
            code += bytes([0x6A])
            code += GLOBAL_GET(self.err_code_global)
            code += bytes([0x37]); code += _uleb128_static(3); code += _uleb128_static(0)
        code += GLOBAL_GET(self.list_idx_global)
        code += i32_const(1)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.list_idx_global)
        code += bytes([0x0C, 0x00])
        code += END
        code += END
        code += GLOBAL_GET(self.slice_base_global)

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

    def _gen_map_literal(self, e, code, qname):
        if not isinstance(e, MapExpr):
            return False
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
        return True

    def _gen_collection_method_call(self, e, code, qname):
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
            if isinstance(rty, tuple) and rty[0] == "list":
                if method == "len":
                    self._gen_expr(recv, code, qname)
                    code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                    code += bytes([0xAC])
                    return True
                if method in ("map", "filter"):
                    self._gen_list_map(code, qname, recv, arg, rty, method)
                    return True
                elem_ty = rty[1] if len(rty) > 1 else UNKNOWN
                if self._gen_list_method(recv, method, args, elem_ty, code, qname):
                    return True
            if isinstance(rty, tuple) and rty[0] == "set" and method in ("add", "push", "insert", "contains", "remove", "del", "len"):
                if method == "len":
                    self._gen_expr(recv, code, qname)
                    code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                    code += bytes([0xAC])
                    return True
                if method == "contains":
                    self._gen_contains(arg, recv, code, qname)
                    code += bytes([0xAD])
                    return True
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
                code += GLOBAL_GET(self.tmp_global)
                code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                code += GLOBAL_SET(self.list_tmp_global)
                if method in ("remove", "del"):
                    self._gen_set_remove(code, is_float)
                else:
                    self._emit_set_insert(code, is_float)
                return True
            if isinstance(rty, tuple) and rty[0] == "map" and method in ("len", "has", "get", "del", "keys", "values", "items"):
                if method == "len":
                    self._gen_expr(recv, code, qname)
                    code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(0)
                    code += bytes([0xAC])
                    return True
                if method == "has":
                    self._gen_contains(arg, recv, code, qname)
                    code += bytes([0xAD])
                    return True
                if method == "del":
                    self._gen_expr(arg, code, qname)
                    if self._operand_is_ptr(arg, qname):
                        code += bytes([0xAC])
                    code += GLOBAL_SET(self.list_val_i64)
                    self._gen_expr(recv, code, qname)
                    code += GLOBAL_SET(self.tmp_global)
                    code += GLOBAL_GET(self.tmp_global)
                    code += bytes([0x28]); code += _uleb128_static(2); code += _uleb128_static(8)
                    code += GLOBAL_SET(self.list_tmp_global)
                    self._gen_map_del(code)
                    return True
                if method in ("keys", "values", "items"):
                    self._gen_map_collect(recv, rty, method, code, qname)
                    return True
                self._gen_expr(Postfix(recv, [("index", arg)]), code, qname)
                return True
        return False
