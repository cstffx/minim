"""Verdict-conformance test for formal/CASES.md.

Unlike test_borrow.py (which only checks the checker doesn't crash),
this asserts the checker produces the EXACT documented verdict
(RECHAZAR[*] -> borrow_check() must return a non-empty error list,
ACEPTAR -> it must return an empty list) for the canonical cases in
formal/CASES.md.

Exit code 0 if every case matches its documented verdict, 1 otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.borrow import borrow_check

REJECT = "reject"
ACCEPT = "accept"

# (case id, expected verdict, source). Sourced from formal/CASES.md section 1-3.
CASES = [
    ("R1", REJECT, """
fn main()
\tlet a = [1, 2, 3]
\tlet b = a
\tprint(a.len)          # 'a' se movio
"""),
    ("R3", REJECT, """
fn push1(v: [int])
\tv.push(1)             # 'v' no es 'var'
"""),
    ("R4", REJECT, """
fn fill(var v: [int], n: int)
\tfor i in 0..n
\t\tv.push(i)

fn main()
\tvar v = [1, 2, 3]
\tlet r = &v
\tfill(v, 4)            # 'v' tiene un prestamo vivo ('r' se usa mas abajo)
\tprint(r.len)
"""),
    ("R5", REJECT, """
fn leak() -> &int
\tlet x = 5
\t&x                    # 'x' muere al salir de 'leak'
"""),
    ("R6", REJECT, """
fn first(v: [int]) -> &int
\tv[0]

fn main()
\tlet r = first([1, 2, 3])   # el temporal muere al final de la sentencia
\tprint(r)
"""),
    ("R8", REJECT, """
type Buf
\tdata: [int] = []

fn main()
\tvar b = Buf()
\tb.push(1)
\tlet d = b.data        # error v0.1: no hay movimientos parciales
\tprint(b.len)
"""),
    # R12's documented code block is actually the A11 simple-receptor case (doc was stale,
    # corrected in formal/CASES.md): it ACCEPTS. The still-open general case (index/call
    # receptor) has no confirmed minimal example yet -- see TODO in formal/CASES.md R12.
    ("R12", ACCEPT, """
fn main()
\tvar v = [1, 2, 3]
\tv.push(v.len)         # lugar simple: ACEPTA via two-phase borrow (A11)
"""),
    # R13: los dos casos que SI solapan siguen RECHAZAR (alias real, no incompletitud).
    ("R13-same-place", REJECT, """
type Pair
\ta: [int] = []
\tb: [int] = []

fn swap(var x: [int], var y: [int])
\tlet t = x[0]
\tx[0] = y[0]
\ty[0] = t

fn main()
\tvar p = Pair()
\tswap(p, p)            # RECHAZAR: los dos argumentos son el mismo lugar
"""),
    ("R13-same-field", REJECT, """
type Pair
\ta: [int] = []
\tb: [int] = []

fn swap(var x: [int], var y: [int])
\tlet t = x[0]
\tx[0] = y[0]
\ty[0] = t

fn main()
\tvar p = Pair()
\tswap(p.a, p.a)        # RECHAZAR: el mismo campo dos veces
"""),
    ("A1", ACCEPT, """
fn main()
\tvar v = [1, 2, 3]
\tlet r = &v
\tprint(r.len)          # ultimo uso de 'r'
\tv.push(4)             # legal: el prestamo ya termino
"""),
    # KNOWN BUG (see formal/CASES.md A2 note): the checker currently REJECTS this with
    # "no se puede mover 'v' con un prestamo vivo". Root cause: calling sum(v) -- whose body
    # does `for x in v` on its OWN parameter named v -- appears to leak a "borrow of v" into
    # the caller's scope, even though the callee's v is a distinct binding. This looks like a
    # name-based (not scope-qualified) borrow-liveness bug in tools/borrow.py, not a real
    # aliasing hazard. Per instructions, we assert the DOCUMENTED-correct verdict (ACCEPT) so
    # this test fails loudly until the real bug in tools/borrow.py is fixed.
    ("A2", ACCEPT, """
fn fill(var v: [int], n: int)
\tfor i in 0..n
\t\tv.push(i)

fn sum(v: [int]) -> int
\tvar t = 0
\tfor x in v
\t\tt += x
\tt

fn main()
\tvar v = [1, 2, 3]
\tprint(sum(v))         # prestamo compartido solo durante la llamada
\tprint(v.len)          # 'v' sigue vivo
\tfill(v, 5)            # y se puede mutar despues
"""),
    ("A3", ACCEPT, """
fn main()
\tlet v = [1, 2, 3]
\tlet a = &v
\tlet b = &v
\tprint(a.len + b.len)  # compartidos: ilimitados
"""),
    ("A4", ACCEPT, """
fn take(move v: [int]) -> int
\tv.len

fn main()
\tlet v = [1, 2, 3]
\tprint(take(v))        # 'v' se transfiere; no se usa despues
"""),
    ("A6", ACCEPT, """
fn first(v: [int]) -> &int
\tv[0]

fn main()
\tlet a = [1, 2, 3]
\tlet r = first(a)      # un unico parametro de referencia: el prestamo se ata a 'a'
\tprint(r)
\tprint(a.len)          # 'a' sigue viva
"""),
    ("A8", ACCEPT, """
type Point
\tx: float
\ty: float

fn main()
\tlet p = Point(x: 1, y: 2)
\tlet q = p             # copia: todos los campos son copiables
\tprint(p.x + q.x)
"""),
    ("A11", ACCEPT, """
fn main()
\tvar v = [1, 2, 3]
\tv.push(v.len)              # argumento que LEE el dueno
\tv.push(v.pop() or 0)       # argumento que pide prestamo UNICO del dueno

type Cfg
\titems: [int]
\tfn addDefault(var self)
\t\titems.push(items.len)  # 'items' es una ruta de campos: lugar simple

fn main()
\tlet c = Cfg()
\tc.addDefault()
"""),
    ("A12", ACCEPT, """
type Pair
\ta: [int] = []
\tb: [int] = []

fn swap(var x: [int], var y: [int])
\tlet t = x[0]
\tx[0] = y[0]
\ty[0] = t

fn main()
\tvar p = Pair(a: [1], b: [2])
\tswap(p.a, p.b)        # ACEPTAR: overlap(p.a, p.b) es falso, los lugares son disjuntos
\tprint(f"{p.a[0]} {p.b[0]}")
"""),
    ("A13", ACCEPT, """
type Pair
\ta: [int] = []
\tb: [int] = []

fn fill(var v: [int], n: int)
\tfor i in 0..n
\t\tv.push(i)

fn main()
\tvar p = Pair()
\tfill(p.a, 1)          # ACEPTAR ya en v0.1: este prestamo muere en su ultimo uso (R7)
\tfill(p.b, 1)          # y el siguiente empieza despues: no se solapan en el tiempo
"""),
]


def main():
    failures = []
    for case_id, expected, source in CASES:
        errors = borrow_check(source)
        actual = REJECT if errors else ACCEPT
        if actual != expected:
            failures.append((case_id, expected, actual))
    if failures:
        print(f"FAIL: {len(failures)} verdict mismatches")
        for case_id, expected, actual in failures:
            print(f"  {case_id}: expected {expected!r}, got {actual!r}")
        sys.exit(1)
    print(f"OK: all {len(CASES)} formal/CASES.md verdicts match")


if __name__ == "__main__":
    main()
