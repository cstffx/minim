from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class RuntimeMixin:
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

    def _ensure_str_method_helpers(self):
        """Runtime helpers for str.words/lines/split/trim/strip/starts/ends/
        replace/bytes and list.join. Built lazily on first use."""
        if getattr(self, "_str_method_helpers", None):
            return self._str_method_helpers
        h = {}
        I32 = WasmEncoder.I32
        LD8 = bytes([0x2D, 0x00, 0x00])
        ST8 = bytes([0x3A, 0x00, 0x00])
        EQZ = bytes([0x45])
        EQ = bytes([0x46])
        NE = bytes([0x47])
        LT = bytes([0x48])
        GT = bytes([0x4A])
        LE = bytes([0x4C])
        ADD = bytes([0x6A])
        MUL = bytes([0x6C])
        IOR = bytes([0x72])
        IF = bytes([0x04, 0x40])
        IFR = bytes([0x04, 0x7F])
        ELSE = bytes([0x05])
        BR0 = bytes([0x0C, 0x00])
        BR1 = bytes([0x0D, 0x01])
        EXT = bytes([0xAD])
        WRAP = bytes([0xA7])
        LEN = self._ensure_str_helpers()["len"]

        def i32_load(off):
            return bytes([0x28]) + _uleb128_static(2) + _uleb128_static(off)

        def i32_store(off):
            return bytes([0x36]) + _uleb128_static(2) + _uleb128_static(off)

        def i64_store(off):
            return bytes([0x37]) + _uleb128_static(3) + _uleb128_static(off)

        def func(params, local_types, body):
            t = self.enc.add_type(params, [I32])
            return self.enc.add_function(t, local_types, bytes(body))

        # __copy_range(src, start, end) -> ptr
        c = bytearray()
        c += local_get(2); c += local_get(1); c += bytes([0x6B]); c += local_set(5)  # n
        c += GLOBAL_GET(self.heap_global); c += local_set(3)                          # base
        c += GLOBAL_GET(self.heap_global)
        c += local_get(5); c += i32_const(1); c += ADD; c += ADD
        c += GLOBAL_SET(self.heap_global)
        c += i32_const(0); c += local_set(4)                                          # i
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(5); c += LT; c += EQZ; c += BR1
        c += local_get(3); c += local_get(4); c += ADD
        c += local_get(0); c += local_get(1); c += ADD; c += local_get(4); c += ADD
        c += LD8; c += ST8
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += local_get(3); c += local_get(5); c += ADD; c += i32_const(0); c += ST8
        c += local_get(3)
        h["copy"] = func([I32, I32, I32], [I32, I32, I32], c)

        # __isspace(ch) -> i32
        c = bytearray()
        for i, v in enumerate((32, 9, 10, 13, 11, 12)):
            c += local_get(0); c += i32_const(v); c += EQ
            if i:
                c += IOR
        h["isspace"] = func([I32], [], c)

        # __memchr(s, ch) -> i32 (1 if ch is in s)
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(2)
        c += i32_const(0); c += local_set(3)
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(3); c += local_get(2); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(3); c += ADD; c += LD8
        c += local_get(1); c += EQ
        c += IF; c += i32_const(1); c += RETURN; c += END
        c += local_get(3); c += i32_const(1); c += ADD; c += local_set(3)
        c += BR0
        c += END; c += END
        c += i32_const(0)
        h["memchr"] = func([I32, I32], [I32, I32], c)

        # __match_at(a, i, b) -> i32 (does b occur in a at i?)
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(3)   # na
        c += local_get(2); c += CALL(LEN); c += local_set(4)   # nb
        c += local_get(1); c += local_get(4); c += ADD; c += local_get(3); c += GT
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += i32_const(0); c += local_set(5)                   # j
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(5); c += local_get(4); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(1); c += ADD; c += local_get(5); c += ADD; c += LD8
        c += local_get(2); c += local_get(5); c += ADD; c += LD8
        c += NE
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += local_get(5); c += i32_const(1); c += ADD; c += local_set(5)
        c += BR0
        c += END; c += END
        c += i32_const(1)
        h["match"] = func([I32, I32, I32], [I32, I32, I32], c)

        def emit_trim_test(dst):
            dst += local_get(1); dst += EQZ; dst += IFR
            dst += local_get(6); dst += CALL(h["isspace"])
            dst += ELSE
            dst += local_get(2); dst += local_get(6); dst += CALL(h["memchr"])
            dst += END

        # __trim(s, mode, chars) -> ptr  (mode 0: whitespace, 1: chars)
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(5)   # n
        c += i32_const(0); c += local_set(3)                   # l
        c += local_get(5); c += local_set(4)                   # r
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(3); c += local_get(4); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(3); c += ADD; c += LD8; c += local_set(6)
        emit_trim_test(c)
        c += EQZ; c += BR1
        c += local_get(3); c += i32_const(1); c += ADD; c += local_set(3)
        c += BR0
        c += END; c += END
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(3); c += GT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += i32_const(1)
        c += bytes([0x6B]); c += ADD; c += LD8; c += local_set(6)
        emit_trim_test(c)
        c += EQZ; c += BR1
        c += local_get(4); c += i32_const(1); c += bytes([0x6B]); c += local_set(4)
        c += BR0
        c += END; c += END
        c += local_get(0); c += local_get(3); c += local_get(4); c += CALL(h["copy"])
        h["trim"] = func([I32, I32, I32], [I32, I32, I32, I32], c)

        # __words(s) -> list ptr (list of str)
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(1)
        c += i32_const(0); c += local_set(2)
        c += i32_const(0); c += local_set(4)
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += LD8; c += CALL(h["isspace"]); c += EQZ; c += BR1
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(2); c += i32_const(1); c += ADD; c += local_set(2)
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += LD8; c += CALL(h["isspace"]); c += BR1
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += BR0
        c += END; c += END
        c += local_get(2); c += i32_const(4); c += LT
        c += IF; c += i32_const(4); c += local_set(9)
        c += ELSE; c += local_get(2); c += local_set(9); c += END
        c += GLOBAL_GET(self.heap_global); c += local_set(3)
        c += GLOBAL_GET(self.heap_global)
        c += local_get(9); c += i32_const(8); c += MUL; c += i32_const(16); c += ADD
        c += ADD
        c += GLOBAL_SET(self.heap_global)
        c += local_get(3); c += i32_const(0); c += i32_store(0)
        c += local_get(3); c += local_get(9); c += i32_store(4)
        c += local_get(3); c += local_get(3); c += i32_const(16); c += ADD; c += i32_store(8)
        c += i32_const(0); c += local_set(4)
        c += i32_const(0); c += local_set(7)
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += LD8; c += CALL(h["isspace"]); c += EQZ; c += BR1
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(4); c += local_set(5)
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(1); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += LD8; c += CALL(h["isspace"]); c += BR1
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += local_get(0); c += local_get(5); c += local_get(4); c += CALL(h["copy"]); c += local_set(8)
        c += local_get(3); c += i32_const(16); c += ADD
        c += local_get(7); c += i32_const(8); c += MUL; c += ADD
        c += local_get(8); c += bytes([0xAC])
        c += bytes([0x37]) + _uleb128_static(3) + _uleb128_static(0)
        c += local_get(7); c += i32_const(1); c += ADD; c += local_set(7)
        c += BR0
        c += END; c += END
        c += local_get(3); c += local_get(7); c += i32_store(0)
        c += local_get(3)
        h["words"] = func([I32], [I32]*9, c)

        # __starts(a, b) -> i32
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(2)   # na
        c += local_get(1); c += CALL(LEN); c += local_set(3)   # nb
        c += local_get(3); c += local_get(2); c += GT
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += i32_const(0); c += local_set(4)                   # i
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(4); c += local_get(3); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += LD8
        c += local_get(1); c += local_get(4); c += ADD; c += LD8
        c += NE
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += local_get(4); c += i32_const(1); c += ADD; c += local_set(4)
        c += BR0
        c += END; c += END
        c += i32_const(1)
        h["starts"] = func([I32, I32], [I32, I32, I32], c)

        # __ends(a, b) -> i32
        c = bytearray()
        c += local_get(0); c += CALL(LEN); c += local_set(2)   # na
        c += local_get(1); c += CALL(LEN); c += local_set(3)   # nb
        c += local_get(3); c += local_get(2); c += GT
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += local_get(2); c += local_get(3); c += bytes([0x6B]); c += local_set(4)  # off
        c += i32_const(0); c += local_set(5)                   # i
        c += BLOCK(BLK_VOID); c += LOOP(BLK_VOID)
        c += local_get(5); c += local_get(3); c += LT; c += EQZ; c += BR1
        c += local_get(0); c += local_get(4); c += ADD; c += local_get(5); c += ADD; c += LD8
        c += local_get(1); c += local_get(5); c += ADD; c += LD8
        c += NE
        c += IF; c += i32_const(0); c += RETURN; c += END
        c += local_get(5); c += i32_const(1); c += ADD; c += local_set(5)
        c += BR0
        c += END; c += END
        c += i32_const(1)
        h["ends"] = func([I32, I32], [I32, I32, I32, I32], c)
        self._str_method_helpers = h
        return h

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
