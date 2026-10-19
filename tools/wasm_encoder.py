"""Minimal WebAssembly binary encoder (MVP).

Emits a wasm module with: type/function/export/code sections, plus imports.
Supports i64 (int) and f64 (float) values and a small instruction set.
"""
import struct


class WasmEncoder:
    def __init__(self):
        self.types = []      # list of (params list of valtype, result list)
        self.imports = []    # list of (module, name, typeidx)
        self.functions = []  # list of (typeidx, locals list of valtype, code bytes)
        self.exports = []    # list of (name, kind, index)
        self.memories = []   # list of (min, max or None)
        self.data = []       # list of (offset, bytes)
        self.globals = []    # list of (valtype, mutable, init bytes)

    # valtypes
    I32 = 0x7F
    I64 = 0x7E
    F32 = 0x7D
    F64 = 0x7C

    def add_type(self, params, results):
        self.types.append((list(params), list(results)))
        return len(self.types) - 1

    def add_import(self, module, name, typeidx):
        self.imports.append((module, name, typeidx))
        return len(self.imports) - 1  # import index in function namespace? imports come first

    def add_function(self, typeidx, locals_, code):
        self.functions.append((typeidx, list(locals_), bytes(code)))
        return len(self.imports) + len(self.functions) - 1

    def add_export_func(self, name, funcidx):
        self.exports.append((name, 0x00, funcidx))

    def add_memory(self, min_pages, max_pages=None):
        self.memories.append((min_pages, max_pages))

    def add_data(self, offset, data_bytes):
        self.data.append((offset, bytes(data_bytes)))

    def add_global(self, valtype, mutable, init_bytes):
        self.globals.append((valtype, mutable, bytes(init_bytes)))
        return len(self.globals) - 1

    def add_export_memory(self, name, memidx=0):
        self.exports.append((name, 0x02, memidx))

    def _uleb128(self, val):
        out = bytearray()
        while True:
            byte = val & 0x7F
            val >>= 7
            if val:
                byte |= 0x80
            out.append(byte)
            if not val:
                break
        return bytes(out)

    def _encode_str(self, s):
        b = s.encode("utf-8")
        return self._uleb128(len(b)) + b

    def _section(self, id_, payload):
        return bytes([id_]) + self._uleb128(len(payload)) + payload

    def encode(self):
        out = bytearray(b"\x00asm\x01\x00\x00\x00")
        # type section (1)
        if self.types:
            payload = bytearray()
            payload += self._uleb128(len(self.types))
            for params, results in self.types:
                payload.append(0x60)  # func
                payload += self._uleb128(len(params))
                for p in params:
                    payload.append(p)
                payload += self._uleb128(len(results))
                for r in results:
                    payload.append(r)
            out += self._section(1, bytes(payload))
        # import section (2)
        if self.imports:
            payload = bytearray()
            payload += self._uleb128(len(self.imports))
            for module, name, typeidx in self.imports:
                payload += self._encode_str(module)
                payload += self._encode_str(name)
                payload.append(0x00)  # func import
                payload += self._uleb128(typeidx)
            out += self._section(2, bytes(payload))
        # function section (3)
        if self.functions:
            payload = bytearray()
            payload += self._uleb128(len(self.functions))
            for typeidx, locals_, code in self.functions:
                payload += self._uleb128(typeidx)
            out += self._section(3, bytes(payload))
        # memory section (5)
        if self.memories:
            payload = bytearray()
            payload += self._uleb128(len(self.memories))
            for minp, maxp in self.memories:
                if maxp is None:
                    payload.append(0x00)
                    payload += self._uleb128(minp)
                else:
                    payload.append(0x01)
                    payload += self._uleb128(minp)
                    payload += self._uleb128(maxp)
            out += self._section(5, bytes(payload))
        # global section (6)
        if self.globals:
            payload = bytearray()
            payload += self._uleb128(len(self.globals))
            for valtype, mutable, init in self.globals:
                payload.append(valtype)
                payload.append(0x01 if mutable else 0x00)
                payload += init
                payload.append(0x0B)  # end
            out += self._section(6, bytes(payload))
        # export section (7)
        if self.exports:
            payload = bytearray()
            payload += self._uleb128(len(self.exports))
            for name, kind, idx in self.exports:
                payload += self._encode_str(name)
                payload.append(kind)
                payload += self._uleb128(idx)
            out += self._section(7, bytes(payload))
        # code section (10)
        if self.functions:
            payload = bytearray()
            payload += self._uleb128(len(self.functions))
            for typeidx, locals_, code in self.functions:
                body = bytearray()
                # locals
                # group by type
                groups = []
                for vt in locals_:
                    if groups and groups[-1][0] == vt:
                        groups[-1][1] += 1
                    else:
                        groups.append([vt, 1])
                body += self._uleb128(len(groups))
                for vt, count in groups:
                    body += self._uleb128(count)
                    body.append(vt)
                body += code
                body.append(0x0B)  # end
                payload += self._uleb128(len(body))
                payload += body
            out += self._section(10, bytes(payload))
        # data section (11)
        if self.data:
            payload = bytearray()
            payload += self._uleb128(len(self.data))
            for offset, db in self.data:
                payload.append(0x00)  # active, memory 0
                payload += bytes([0x41])  # i32.const
                payload += _leb128_signed(offset)
                payload.append(0x0B)  # end
                payload += self._uleb128(len(db))
                payload += db
            out += self._section(11, bytes(payload))
        return bytes(out)


# instruction helpers
def i64_const(val):
    return bytes([0x42]) + _leb128_signed(val)


def f64_const(val):
    return bytes([0x44]) + struct.pack("<d", val)


def _leb128_signed(val):
    # module-level helper
    out = bytearray()
    more = True
    while more:
        byte = val & 0x7F
        val >>= 7
        # sign extend
        if (val == 0 and (byte & 0x40) == 0) or (val == -1 and (byte & 0x40) != 0):
            more = False
        else:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


# monkeypatch module-level for use
WasmEncoder._leb128_signed = staticmethod(_leb128_signed)


def local_get(idx):
    return bytes([0x20]) + _uleb128_static(idx)


def local_set(idx):
    return bytes([0x21]) + _uleb128_static(idx)


def local_tee(idx):
    return bytes([0x22]) + _uleb128_static(idx)


def i32_const(val):
    return bytes([0x41]) + _uleb128_static(val & 0xFFFFFFFF)


GLOBAL_GET = lambda idx: bytes([0x23]) + _uleb128_static(idx)
GLOBAL_SET = lambda idx: bytes([0x24]) + _uleb128_static(idx)


def _uleb128_static(val):
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            byte |= 0x80
        out.append(byte)
        if not val:
            break
    return bytes(out)


# expose
def uleb128(val):
    return _uleb128_static(val)


# control
I64_ADD = bytes([0x7C])
I64_SUB = bytes([0x7D])
I64_MUL = bytes([0x7E])
I64_DIV_S = bytes([0x7F])
I64_REM_S = bytes([0x80])
I64_EQZ = bytes([0x50])
I64_EQ = bytes([0x51])
I64_NE = bytes([0x52])
I64_LT_S = bytes([0x53])
I64_GT_S = bytes([0x55])
I64_LE_S = bytes([0x57])
I64_GE_S = bytes([0x59])
I64_EQ = bytes([0x51])
I64_NE = bytes([0x52])

F64_ADD = bytes([0xA0])
F64_SUB = bytes([0xA1])
F64_MUL = bytes([0xA2])
F64_DIV = bytes([0xA3])
F64_LT = bytes([0x63])
F64_GT = bytes([0x64])
F64_LE = bytes([0x65])
F64_GE = bytes([0x66])
F64_EQ = bytes([0x61])
F64_NE = bytes([0x62])

CALL = lambda idx: bytes([0x10]) + _uleb128_static(idx)
BLOCK = lambda bt: bytes([0x02, bt])
LOOP = lambda bt: bytes([0x03, bt])
IF = lambda bt: bytes([0x04, bt])
ELSE = bytes([0x05])
END = bytes([0x0B])
RETURN = bytes([0x0F])
DROP = bytes([0x1A])

BLK_VOID = 0x40
BLK_I64 = 0x7E
BLK_F64 = 0x7C
BLK_I32 = 0x7F