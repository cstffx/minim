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

    ("tipos producto y suma con metodos", """
type Shape
	case Circle
		r: float
	case Rect
		w: float
		h: float
	fn area(self) -> float
		match self
			case Circle(r): pi * r * r
			case Rect(w, h): w * h
	fn name(self) -> str
		match self
			case Circle: "circulo"
			case Rect: "rectangulo"

fn main()
	let c = Shape.Circle(1.5)
	let r = Shape.Rect(2, 3)
	print(f"{c.area():.2f}{r.area():.2f}{c.name()}{r.name()}")
""", "7.076.00circulorectangulo"),

    ("genericos y trait acotado", """
trait Ord
	fn cmp(self, o: Self) -> int

type Num
	v: int
	fn cmp(self, o: Num) -> int
		v - o.v

fn max[T: Ord](a: T, b: T) -> T
	if a.cmp(b) > 0
		a
	else
		b

fn first[T](xs: [T]) -> T
	xs[0]

fn main()
	print(max(Num(v: 3), Num(v: 5)).v)
	print(first(["a", "b"]))
""", "5a"),

    ("colecciones: list, map, set y tuplas", """
fn main()
	let l = [3, 1, 2]
	l.sort()
	print(f"{l[0]}{l[1]}{l[2]}")
	let s = l.slice(0, 2)
	print(s.len())
	l.reverse()
	print(l[1])
	let m = {"a": 1, "b": 2}
	m.del("a")
	print(m["b"])
	let ks = m.keys()
	print(ks[0])
	let vs = m.values()
	print(vs[0])
	let st = {1, 2, 2}
	st.add(3)
	st.remove(1)
	print(st.len())
	let x, y = (7, "z")
	print(f"{x}{y}")
""", "123222b227z"),

    ("opcionales, errores, ? y or:", """
fn half(x: int) -> int!
	if x % 2 == 0
		return x // 2
	err("impar", 3)

fn inc(x: int) -> int!
	let y = half(x)?
	y + 1

fn find(x: int) -> int?
	if x > 0
		return x
	nil

fn main()
	let a = inc(4) or:
		-1
	let b = inc(3) or:
		print(it)
		-1
	let c = find(9) or:
		-1
	let d = find(-1) or:
		-1
	print(f"{a}{b}{c}{d}")
""", "impar3-19-1"),

    ("conversiones as, str y parse", """
fn main()
	let a = 3.9 as int
	let b = 3 as float
	let c = "42".parse[int]() or:
		-1
	let d = "1.5".parse[float]() or:
		-1.0
	print(f"{a} {b:.1f} {c} {d:.1f} {65 as str} {str(true)}")
""", "3 3.0 42 1.5 65 true"),
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
