"""Tests de runtime del backend BIR (fase 6.1: subset escalar).

Cada caso compila con `tools.codegen_bir.compile_source` (no con el backend
desde AST) y se ejecuta con Node, comparando la salida exacta.
"""
import os
import subprocess
import sys
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.codegen_bir import compile_source, BIRCodegenError

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


def run(src):
    data = compile_source(src)
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
    ("str constante y print_str", """
fn main()
	print("hola, BIR")
""", "hola, BIR"),

    ("enteros y precedencia", """
fn main()
	print(1 + 2 * 3)
	print(7 // 2)
	print(5 % 2)
	print(-3 + 1)
""", "731-2"),

    ("flotantes y cast explicito", """
fn main()
	print(1.5 + 2.25)
	print(3.0 / 2.0)
	print(int(3.9))
	print(float(2))
""", "3.751.532"),

    ("comparaciones, bits y logica", """
fn main()
	print(3 < 4)
	print(1 == 1)
	print(not false)
	print(6 & 3)
	print(1 << 4)
	print(7 ^ 1)
	print(~0)
""", "1112166-1"),

    ("funciones y recursion", """
fn fact(n: int) -> int
	if n <= 1
		1
	else
		n * fact(n - 1)

fn suma(a: int, b: int) -> int
	a + b

fn main()
	print(fact(5))
	print(suma(2, 3))
""", "1205"),

    ("while, break y continue", """
fn main()
	var i = 0
	var acc = 0
	while i < 10
		i += 1
		if i == 3
			continue
		if i == 8
			break
		acc += i
	print(acc)
""", "25"),

    ("match escalar como sentencia", """
fn main()
	let x = 2
	match x
		case 1:
			print("uno")
		case 2:
			print("dos")
		else:
			print("otro")
""", "dos"),

    ("if como expresion", """
fn main()
	let x = 7
	print(if x > 5: 10 else: 20)
""", "10"),

    ("funcion que devuelve str", """
fn saludo(n: str) -> str
	n

fn main()
	print(saludo("eco"))
""", "eco"),

    ("cuerpo de modulo sin main", """
print("top-level")
""", "top-level"),

    ("firma con struct por valor", """
type P
	a: int
	b: str

fn ident(p: P) -> P
	p

fn main()
	print("struct-ok")
""", "struct-ok"),

    ("tupla creada, pasada y devuelta", """
fn ident(t: (int, int)) -> (int, int)
	t

fn make() -> (int, int)
	(1, 2)

fn main()
	let t = make()
	let u = ident(t)
	print("tupla-ok")
""", "tupla-ok"),

    ("producto creado, pasado y devuelto", """
type P
	a: int
	b: int

fn ident(p: P) -> P
	p

fn make(a: int, b: int) -> P
	P(a, b)

fn main()
	let p = make(1, 2)
	let q = ident(p)
	print("producto-ok")
""", "producto-ok"),

    ("variante creada, pasada y devuelta", """
type Shape
	case Circle(r: float)
	case Rect(w: float, h: float)

fn ident(s: Shape) -> Shape
	s

fn make() -> Shape
	Shape.Circle(1.5)

fn main()
	let a = make()
	let b = ident(Shape.Rect(2.0, 3.0))
	print("variante-ok")
""", "variante-ok"),

    ("lista creada y pasada", """
fn consume(xs: [int])
	print("lista-ok")

fn main()
	let xs = [1, 2, 3]
	let vacia = []
	consume(xs)
	consume(vacia)
""", "lista-oklista-ok"),

    ("agregados anidados", """
type P
	a: (int, int)
	b: int

fn main()
	let p = P((1, 2), 3)
	let t = ((4, 5), 6)
	print("anidado-ok")
""", "anidado-ok"),
]


# JS que llama a `main` dos veces y lee los punteros devueltos (una tupla y un
# producto ocupan los primeros slots de memoria lineal).
JS_ALLOC = r"""
const fs=require('fs');
const w=fs.readFileSync(process.argv[1]);
const m=new WebAssembly.Module(w);
const env={print:(x)=>process.stdout.write(String(x)),
           print_f64:(x)=>process.stdout.write(String(x)),
           print_str:(p)=>process.stdout.write("S")};
const inst=new WebAssembly.Instance(m,{env});
const p1=inst.exports.main();
const p2=inst.exports.main();
const dv=new DataView(inst.exports.memory.buffer);
const out={p1, p2,
  v1:[String(dv.getBigInt64(p1,true)), String(dv.getBigInt64(p1+8,true))],
  v2:[String(dv.getBigInt64(p2,true)), String(dv.getBigInt64(p2+8,true))]};
console.log(JSON.stringify(out));
"""


def check_independent_allocations():
    """Dos instancias del mismo agregado se guardan en direcciones distintas."""
    sources = {
        "tupla": """
fn main() -> (int, int)
	(1, 2)
""",
        "producto": """
type P
	a: int
	b: int

fn main() -> P
	P(1, 2)
""",
    }
    for name, src in sources.items():
        data = compile_source(src)
        fd, path = tempfile.mkstemp(suffix=".wasm")
        os.write(fd, data)
        os.close(fd)
        try:
            r = subprocess.run(["node", "-e", JS_ALLOC, path],
                               capture_output=True, text=True)
        finally:
            os.unlink(path)
        if r.returncode != 0:
            raise AssertionError(f"{name}: {r.stderr}")
        got = json.loads(r.stdout)
        assert got["p1"] != got["p2"], (name, got)
        assert got["v1"] == ["1", "2"], (name, got)
        assert got["v2"] == ["1", "2"], (name, got)


def main():
    failures = 0
    for name, src, expected in CASES:
        try:
            got = run(src)
        except (AssertionError, BIRCodegenError) as e:
            failures += 1
            print(f"FAIL {name}: {e}")
            continue
        if got != expected:
            failures += 1
            print(f"FAIL {name}: esperado {expected!r}, obtenido {got!r}")
        else:
            print(f"ok {name}")
    try:
        check_independent_allocations()
        print("ok agregados sin memoria compartida")
    except AssertionError as e:
        failures += 1
        print(f"FAIL agregados sin memoria compartida: {e}")
    if failures:
        print(f"{failures} fallo(s)")
        return 1
    print(f"ok {len(CASES)} casos BIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
