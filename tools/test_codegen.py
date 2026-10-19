import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.codegen_wasm import compile_source
src = """
fn add(a: int, b: int) -> int
	a + b

fn main() -> int
	add(2, 3)
"""
data = compile_source(src)
open('/tmp/opencode/cg.wasm','wb').write(data)
print("ok", len(data))
