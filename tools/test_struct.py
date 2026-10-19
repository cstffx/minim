import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.codegen_wasm import compile_source
src = """
type Point
	x: int
	y: int

fn main() -> int
	let p = Point(x: 1, y: 2)
	p.x + p.y
"""
data = compile_source(src)
open('/tmp/opencode/struct.wasm','wb').write(data)
print("ok", len(data))
