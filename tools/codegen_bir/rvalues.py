from tools.wasm_encoder import *
from babirusas.src.borrowir.ir import Type
from .layouts import LayoutError, wasm_repr
from .aggregates import BIRAggregatesMixin


class BIRRvaluesMixin(BIRAggregatesMixin):
    def _ensure_str_helpers(self):
        if getattr(self, "_str_helpers", None):
            return self._str_helpers
        self._ensure_allocator()
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

        # __to_str_i64(n) -> i32
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

    def _rv_type(self, rv):
        if rv.kind == "unaryop" and rv.op == "tag":
            return Type("i64")
        if rv.kind == "cast" and rv.cast_type is not None and rv.cast_type.kind == "str":
            return Type("str")
        return super()._rv_type(rv)

    def _gen_unaryop(self, rv):
        if rv.op == "tag":
            code = self._gen_rvalue(rv.a)
            return code + bytes([0x28]) + uleb128(2) + uleb128(0) + bytes([0xAC])
        return super()._gen_unaryop(rv)

    def _gen_cast(self, rv):
        src = self._rv_type(rv.a)
        dst = rv.cast_type
        code = self._gen_rvalue(rv.a)
        if src is None or dst is None:
            return code
        if dst.kind == "str":
            helpers = self._ensure_str_helpers()
            if src.kind == "f64":
                return code + i32_const(6) + CALL(helpers["f64"])
            # Actually helper expects value then precision; we already generated value. Need push precision.
            # Fix below.
            if src.kind in ("i64", "bool", "i32", "i8", "i16", "u8", "u16", "u32", "u64"):
                return code + CALL(helpers["i64"])
            if src.kind == "str":
                return code
            return code
        if src.kind == "f64" and dst.kind in ("i64", "bool"):
            return code + I64_TRUNC_F64
        if src.kind in ("i64", "bool") and dst.kind == "f64":
            return code + F64_CONVERT_I64
        return code

    def _gen_binop(self, rv):
        a_ty = self._rv_type(rv.a)
        b_ty = self._rv_type(rv.b) if rv.b is not None else a_ty
        str_op = (a_ty is not None and a_ty.kind == "str" and
                  b_ty is not None and b_ty.kind == "str")
        if str_op:
            if rv.op == "+":
                helpers = self._ensure_str_helpers()
                return (self._gen_rvalue(rv.a) + self._gen_rvalue(rv.b) +
                        CALL(helpers["concat"]))
            left = self._gen_rvalue(rv.a) + bytes([0xAC])
            right = self._gen_rvalue(rv.b) + bytes([0xAC])
            if rv.op == "==":
                return left + right + bytes([0x51]) + bytes([0xAD])
            if rv.op == "!=":
                return left + right + bytes([0x52]) + bytes([0xAD])
            if rv.op == "<":
                return left + right + bytes([0x53]) + bytes([0xAD])
            if rv.op == ">":
                return left + right + bytes([0x55]) + bytes([0xAD])
            if rv.op == "<=":
                return left + right + bytes([0x57]) + bytes([0xAD])
            if rv.op == ">=":
                return left + right + bytes([0x59]) + bytes([0xAD])
            self._fail(f"operador str '{rv.op}' no soportado")
        return super()._gen_binop(rv)
