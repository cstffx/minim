from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class CtorsMixin:
    def _ctor_begin(self, size, code):
        """Allocate a struct/variant; save the outer ctor base on the stack."""
        code += GLOBAL_GET(self.ctor_base_global)  # saved outer base
        code += GLOBAL_GET(self.heap_global)
        code += GLOBAL_SET(self.ctor_base_global)
        code += GLOBAL_GET(self.heap_global)
        code += i32_const(size)
        code += bytes([0x6A])
        code += GLOBAL_SET(self.heap_global)

    def _ctor_end(self, code):
        """Return the new pointer and restore the outer ctor base."""
        code += GLOBAL_GET(self.ctor_base_global)
        code += GLOBAL_SET(self.tmp_global)
        code += GLOBAL_SET(self.ctor_base_global)
        code += GLOBAL_GET(self.tmp_global)

    def _zero_value(self, ty, code):
        wt = self._wasm_type(ty) if ty not in (None, NIL) else None
        if wt == WasmEncoder.F64:
            code += f64_const(0.0)
        elif wt == WasmEncoder.I32:
            code += i32_const(0)
        elif wt == WasmEncoder.I64:
            code += i64_const(0)

    def _store_tmp_value(self, ty, code):
        if isinstance(ty, tuple) and ty[0] in ("opt", "res", "borrow"):
            ty = ty[1]
        if ty == FLOAT:
            code += GLOBAL_SET(self.list_val_f64)
        else:
            if self._type_is_ptr(ty):
                code += bytes([0xAC])  # i64.extend_i32_u
            code += GLOBAL_SET(self.list_val_i64)

    def _load_tmp_value(self, ty, code):
        if isinstance(ty, tuple) and ty[0] in ("opt", "res", "borrow"):
            ty = ty[1]
        if ty == FLOAT:
            code += GLOBAL_GET(self.list_val_f64)
        else:
            code += GLOBAL_GET(self.list_val_i64)
            if self._type_is_ptr(ty):
                code += bytes([0xA7])  # i32.wrap_i64

    def _is_zero_value(self, ty, code):
        if isinstance(ty, tuple) and ty[0] in ("opt", "res", "borrow"):
            ty = ty[1]
        if ty == FLOAT:
            code += f64_const(0.0)
            code += F64_EQ
        else:
            code += i64_const(0)
            code += I64_EQ

    def _gen_tuple_expr(self, e, code, qname):
        if not isinstance(e, TupleExpr):
            return False
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
        return True
