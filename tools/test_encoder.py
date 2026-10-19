import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.wasm_encoder import *
os.makedirs('/tmp/opencode', exist_ok=True)
enc = WasmEncoder()
t = enc.add_type([WasmEncoder.I64], [WasmEncoder.I64])
pt = enc.add_type([WasmEncoder.I64], [])
pi = enc.add_import("env", "print", pt)
code = bytearray()
code += local_get(0)
code += local_get(0)
code += I64_ADD
fidx = enc.add_function(t, [], bytes(code))
enc.add_export_func("double", fidx)
mt = enc.add_type([], [WasmEncoder.I64])
mcode = bytearray()
mcode += i64_const(21)
mcode += CALL(fidx)
mcode += CALL(pi)
mcode += i64_const(0)
mainidx = enc.add_function(mt, [], bytes(mcode))
enc.add_export_func("main", mainidx)
data = enc.encode()
open('/tmp/opencode/test.wasm','wb').write(data)
print("written", len(data))