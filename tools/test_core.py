"""Runtime tests for the Fase 1 language core.

Each case is compiled to wasm and executed with Node. `print` writes the
value without separators, so every assertion is one exact output string.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.codegen_wasm import compile_source

JS = r"""
const fs=require('fs');
const w=fs.readFileSync(process.argv[1]);
const m=new WebAssembly.Module(w);
let inst=null;
function cstr(ptr){
  const u=new Uint8Array(inst.exports.memory.buffer);
  let e=ptr; while(u[e]!==0) e++;
  return Buffer.from(u.subarray(ptr,e)).toString();
}
const env={
  print:(x)=>process.stdout.write(String(x)),
  print_f64:(x)=>process.stdout.write(String(x)),
  print_str:(ptr)=>process.stdout.write(cstr(ptr)),
};
inst=new WebAssembly.Instance(m,{env});
if(inst.exports._start) inst.exports._start();
else if(inst.exports.main) process.stdout.write(String(inst.exports.main()));
"""


def run(src, filename=None):
    data = compile_source(src, filename)
    fd, path = tempfile.mkstemp(suffix=".wasm")
    os.write(fd, data)
    os.close(fd)
    try:
        r = subprocess.run(["node", "-e", JS, path], capture_output=True, text=True)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return r.stdout


CASES = [
    ("enteros y aritmetica", """
fn main()
	print(f"{1 + 2 * 3} {7 // 2} {2 ** 10} {5 % 2} {-3 + 1}")
""", "7 3 1024 1 -2"),

    ("flotantes", """
fn main()
	print(f"{1.5 + 2.25:.2f} {3.0 / 2.0:.2f} {int(3.9)} {float(2):.1f}")
""", "3.75 1.50 3 2.0"),

    ("comparacion, logica y bits", """
fn main()
	print(f"{3 < 4} {1 == 1} {not false} {6 & 3} {1 << 4} {7 ^ 1} {~0}")
""", "1 1 1 2 16 6 -1"),

    ("cadenas", r'''
fn main()
	let s = "hola\nmundo"
	print(s)
	print(r"c:\raw")
	print("""
linea1
linea2""")
	print(len(s))
	print(s.contains("mundo"))
''', 'hola\nmundoc:\\raw\nlinea1\nlinea2101'),

    ("bytes y escapes", r'''
fn main()
	let b = b"\x41\x42"
	print(len(b))
	print(str(65))
''', "265"),

    ("listas, mapas, sets y tuplas", """
fn main()
	let l = [1, 2, 3]
	l.push(4)
	let m = {"a": 10, "b": 20}
	let s = {1, 2, 2, 3}
	let t = (7, "x")
	let v = m["b"]
	print(f"{l.len()} {l[3]} {v} {s.len()} {t.0}{t.1}")
""", "4 4 20 3 7x"),

    ("if, while, break y continue", """
fn main()
	var i = 0
	var acc = 0
	while i < 10
		i += 1
		if i == 3
			continue
		if i == 7
			break
		acc += i
	print(f"{acc} {i}")
""", "18 7"),

    ("if como expresion", """
fn main()
	let x = 5
	let y = if x > 3: 10 else: 20
	print(y)
	print(match x: case 5: "cinco" else: "otro")
""", "10cinco"),

    ("closures e it", """
fn main()
	let inc = fn x => x + 1
	let nums = [1, 2, 3]
	let doubled = nums.map(it * 2)
	let big = nums.filter(it > 1)
	print(inc(4))
	print(doubled[2])
	print(big.len())
""", "562"),

    ("retorno inferido y recursion", """
fn fib(n: int)
	if n < 2
		n
	else
		fib(n - 1) + fib(n - 2)

fn main()
	print(fib(10))
""", "55"),

    ("declaraciones de nivel superior", """
let GREETING = "hola"
var counter = 0

fn bump() -> int
	counter += 1
	counter

print(GREETING)
print(bump())
print(bump())
""", "hola12"),
]


def test_cases():
    failed = 0
    for name, src, expected in CASES:
        try:
            got = run(src)
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {e}")
            continue
        if got != expected:
            failed += 1
            print(f"FAIL {name}: esperado {expected!r}, obtenido {got!r}")
        else:
            print(f"ok {name}")
    return failed


def test_modules():
    d = tempfile.mkdtemp(prefix="minim-mod-")
    with open(os.path.join(d, "util.mim"), "w") as f:
        f.write("""
let MAX = 10

fn add(a: int, b: int) -> int
	a + b

fn _secret() -> int
	99

fn capped(n: int) -> int
	if n > MAX
		MAX
	else
		n
""")
    main = os.path.join(d, "main.mim")
    with open(main, "w") as f:
        f.write("""
use util

fn main()
	print(util.add(2, 3))
	print(util.MAX)
	print(util.capped(42))
""")
    failed = 0
    try:
        got = run(open(main).read(), main)
    except Exception as e:
        print(f"FAIL modulos: {e}")
        return 1
    if got != "51010":
        print(f"FAIL modulos: obtenido {got!r}")
        failed += 1
    else:
        print("ok modulos")

    # private names are rejected by the type checker
    private = os.path.join(d, "private.mim")
    with open(private, "w") as f:
        f.write("use util\n\nfn main()\n\tprint(util._secret())\n")
    try:
        compile_source(open(private).read(), private)
    except Exception:
        print("ok modulo privado")
    else:
        print("FAIL modulo privado: no se rechazo util._secret")
        failed += 1
    return failed


if __name__ == "__main__":
    failures = test_cases() + test_modules()
    if failures:
        print(f"{failures} fallo(s)")
        sys.exit(1)
    print("ok todos")
