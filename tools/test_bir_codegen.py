"""Tests de runtime del backend BIR (fase 6.1: subset escalar).

Cada caso compila con `tools.codegen_bir.compile_source` (no con el backend
desde AST) y se ejecuta con Node, comparando la salida exacta.
"""
import os
import subprocess
import sys
import tempfile

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
]


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
    if failures:
        print(f"{failures} fallo(s)")
        return 1
    print(f"ok {len(CASES)} casos BIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
