# Casos de conformidad del *borrow checker*

Corpus mínimo de comportamiento exigido por la especificación. Cuando exista el compilador,
este fichero se extrae a tests: **un bloque = un caso**.

Tres veredictos posibles:

| Veredicto | Significado |
|---|---|
| `RECHAZAR` | El programa puede alcanzar un fallo en la semántica (§4 de `docs/FORMAL.md`): es un error de seguridad |
| `RECHAZAR*` | El programa **es seguro**, pero el sistema de reglas lo rechaza: incompletitud conocida y documentada, no un fallo |
| `ACEPTAR` | El programa se acepta y no puede fallar |

Cada caso indica la regla o el agujero (`A1`-`A9` según `docs/SOUNDNESS.md` §2).

### Referencia cruzada: casos Rust en `formal/rustcases/`

Aparte de los casos en este documento, `formal/rustcases/*.rs` contiene programas análogos en
Rust real, usados como referencia manual para contrastar el comportamiento del borrow checker de
Minim contra el de `rustc`. No son parte de la suite de tests en Python (`tools/test_*.py`) ni se
ejecutan en CI — son una comprobación manual/opcional. Para ejecutarlos localmente (requiere
`rustc` instalado):

```sh
sh formal/rustcases/run.sh          # usa el rustc del PATH
RUSTC=/ruta/a/rustc sh formal/rustcases/run.sh   # para otro compilador
```

El script compila cada `.rs` e informa si `rustc` lo ACEPTA o RECHAZA. Todos los ficheros están
pensados como programas seguros, así que un `RECHAZA` indica un falso rechazo de `rustc`, no un
fallo de Minim.

---

## 1. Deben rechazarse (inseguros)

### R1 — Uso tras mover (`A1`/R4)
```python
fn main()
	let a = [1, 2, 3]
	let b = a
	print(a.len)          # 'a' se movio
```
`origin`: `move` en la línea 3. Regla Datalog: `error(x,p) :- moved_at(x,p0), p0 < p`.

### R2 — Uso tras liberar (doble *free*)
```python
fn main()
	let a = [1, 2, 3]
	drop(a)
	print(a.len)          # 'a' ya se libero
```
L2 (*drop* exacto): un valor recibe `free` como mucho una vez por camino.

### R3 — Mutar a través de un parámetro compartido (`A1`)
```python
fn push1(v: [int])
	v.push(1)             # 'v' no es 'var'
```
El modo por defecto es compartido; mutar exige `var v` en la firma.

### R4 — Prestamo compartido vivo mientras se muta el dueno
```python
fn fill(var v: [int], n: int)
	for i in 0..n
		v.push(i)

fn main()
	var v = [1, 2, 3]
	let r = &v
	fill(v, 4)            # 'v' tiene un prestamo vivo ('r' se usa mas abajo)
	print(r.len)
```
La región de `r` va hasta su último uso (línea 10), así que cubre la línea 9.

### R5 — Devolver un prestamo de un local (`A2`)
```python
fn leak() -> &int
	let x = 5
	&x                    # 'x' muere al salir de 'leak'
```
Regla de elisión: un `&T` de retorno solo se ata a `self` o a un único parámetro de referencia.
`x` no es ninguno de los dos.

### R6 — Devolver un prestamo de un temporal (`A2`)
```python
fn first(v: [int]) -> &int
	v[0]

fn main()
	let r = first([1, 2, 3])   # el temporal muere al final de la sentencia
	print(r)
```
Los temporales tienen región = la sentencia. Válido con un dueño (`let a = …` → `first(a)`), no con un temporal.

### R7 — Guardar un prestamo en un campo (`A2`)
```python
type Iter
	cur: &[int]           # los prestamos no se almacenan en v0.1
```
Es la restricción que elimina toda la sintaxis de *lifetimes*.

### R8 — Movimiento parcial (`A3`)
```python
type Buf
	data: [int] = []

fn main()
	var b = Buf()
	b.push(1)
	let d = b.data        # error v0.1: no hay movimientos parciales
	print(b.len)
```
La corrección: `let d = copy(b.data)` o leer por préstamo.

### R9 — Closure que escapa (`A4`)
```python
fn make(n: int) -> (int) -> int
	let k = n * 2
	fn x: int => x + k     # la closure captura 'k' por prestamo y escapa
```
Las closures no escapan en v0.1 (no se devuelven ni se guardan).

### R10 — `rc` compartido entre hilos (`A5`/`A6`)
```python
use rc

fn bump(c: rc[int])
	for i in 0..1000
		c.set(c.get() + 1)

fn main()
	let c = rc.new(0)
	let t1 = spawn bump(c)    # error: 'rc' no esta aislado
	let t2 = spawn bump(c)
	await t1
	await t2
```
I5 (aislamiento): `spawn` exige argumentos aislados (sin préstamos vivos, sin `rc`). Para
compartir entre hilos hace falta `arc` con operaciones atómicas.

### R11 — Prestamo vivo que cruza un `await` (`A5`)
```python
fn later(v: [int]) -> int
	await task.yield()    # 'v' es un prestamo vivo que cruza un await
	v.len
```
La corrección: `fn later(move v: [int])`.

---

## 2. Deben rechazarse por incompletitud (son seguros)

### R12 — *Two-phase borrow* (`A8`)
**Nota (corrección):** el bloque de código de esta sección quedó obsoleto. `v.push(v.len)` tiene
receptor de **lugar simple**, así que desde el refinamiento v0.1 (`docs/SOUNDNESS.md` §9) ya
**ACEPTA** — es exactamente el caso cubierto por `A11`, no una instancia de R12. Verificado por
ejecución directa del checker.

Lo que de verdad sigue sin implementar (y por tanto `RECHAZAR*`, incompletitud conocida) es el
**caso general**: receptor con **índice** o con **llamada**, donde la reordenación de la
elaboración de two-phase-borrow cambiaría el significado (p. ej. `v[v.len - 1].push(f(v))`). No
hay todavía un ejemplo mínimo confirmado por ejecución directa para ese caso general — queda
pendiente como TODO antes de poder fijarlo como test automatizado en `tools/test_cases_formal.py`.

### R13 — Exclusividad por **dueño**, no por lugar (`A7`, **simultáneo**) — **ya corregido, ver `A12`**
`swap(p.a, p.b)` (dos préstamos únicos simultáneos sobre **campos distintos** de `p`) **ya no es
un caso de esta sección**: desde que `tools/borrow.py` implementa `_overlap` (lugares = caminos,
`docs/SOUNDNESS.md` §10 / `docs/FORMAL.md` §5.3), ese programa **ACEPTA**. Verificado por
ejecución directa del checker. Ver el caso movido a `A12`.

Lo que **sigue** siendo `RECHAZAR` bajo el nombre `R13` son únicamente los dos casos donde los
lugares **sí solapan** (mismo dueño exacto, o mismo campo repetido):
```python
type Pair
	a: [int] = []
	b: [int] = []

fn swap(var x: [int], var y: [int])
	let t = x[0]
	x[0] = y[0]
	y[0] = t

fn main()
	var p = Pair()
	swap(p, p)            # RECHAZAR: los dos argumentos son el mismo lugar
	swap(p.a, p.a)        # RECHAZAR: el mismo campo dos veces
```
Estos dos sí son inseguros (alias real), no incompletitud: en sentido estricto pertenecen a la
§1 ("Deben rechazarse"); se mantienen aquí solo por continuidad con el nombre histórico `R13`.

Ojo: la variante **secuencial** (`fill(p.a, 1)` y luego `fill(p.b, 1)`) **no** es este caso y debe
**ACEPTARSE** ya en v0.1: la región del primer préstamo termina en su último uso (regla R7). Si el
checker la rechaza, es un **bug** de la máquina de estados, no incompletitud. Está fijada como
test en `A13`.

R12 sigue siendo la **única** frontera de completitud abierta: si algún día se acepta el caso
general, hay que extender `docs/FORMAL.md` §5 (y las pruebas) en consecuencia. La variante
owner-level de R13 ya se resolvió: `docs/SOUNDNESS.md` §10 y `docs/FORMAL.md` §5.3 están
implementados en `tools/borrow.py` (función `_overlap`), no es trabajo futuro.

---

## 3. Deben aceptarse (seguros)

### A1 — El prestamo termina en su último uso
```python
fn main()
	var v = [1, 2, 3]
	let r = &v
	print(r.len)          # ultimo uso de 'r'
	v.push(4)             # legal: el prestamo ya termino
```
T2 (principalidad): la región mínima es la correcta.

### A2 — Prestamo compartido y dueño vivo después
```python
fn fill(var v: [int], n: int)
	for i in 0..n
		v.push(i)

fn sum(v: [int]) -> int
	var t = 0
	for x in v
		t += x
	t

fn main()
	var v = [1, 2, 3]
	print(sum(v))         # prestamo compartido solo durante la llamada
	print(v.len)          # 'v' sigue vivo
	fill(v, 5)            # y se puede mutar despues
```

### A3 — Dos prestamos compartidos simultaneos
```python
fn main()
	let v = [1, 2, 3]
	let a = &v
	let b = &v
	print(a.len + b.len)  # compartidos: ilimitados
```

### A4 — Modo `move` (transferencia)
```python
fn take(move v: [int]) -> int
	v.len

fn main()
	let v = [1, 2, 3]
	print(take(v))        # 'v' se transfiere; no se usa despues
```

### A5 — Receptor mutante y campos sin `self.`
```python
type Counter
	n: int = 0
	fn inc(var self, by: int = 1) -> int
		n += by
		n

fn main()
	var c = Counter()
	c.inc()
	print(c.n)
```

### A6 — Prestamo devuelto con elisión
```python
fn first(v: [int]) -> &int
	v[0]

fn main()
	let a = [1, 2, 3]
	let r = first(a)      # un unico parametro de referencia: el prestamo se ata a 'a'
	print(r)
	print(a.len)          # 'a' sigue viva
```

### A7 — `or:` cierra prestamos y retorna
```python
use fs

fn load(p: str) -> [int]!
	[fs.read(p)?.len]

fn main()
	let data = load("f.txt") or
		eprint(f"error: {it}")
		return
	print(data.len)
```

### A8 — Copia de un tipo copiable
```python
type Point
	x: float
	y: float

fn main()
	let p = Point(x: 1, y: 2)
	let q = p             # copia: todos los campos son copiables
	print(p.x + q.x)
```

### A9 — `spawn` con transferencia y `await`
```python
fn work(n: int) -> int
	n * 2

fn main()
	let t = spawn work(21)
	print(await t)
```

### A10 — `match` sobre un prestamo sin consumirlo
```python
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

fn total(shapes: [Shape]) -> float
	var t = 0.0
	for s in shapes
		t += s.area()
	t
```
Iterar un préstamo compartido y llamar a un receptor compartido: dos préstamos compartidos
simultáneos (A3), no exclusivos.

### A11 — Receptor de lugar simple con argumentos que tocan al dueño (`A8`)
```python
fn main()
	var v = [1, 2, 3]
	v.push(v.len)              # argumento que LEE el dueno
	v.push(v.pop() or 0)       # argumento que pide prestamo UNICO del dueno

type Cfg
	items: [int]
	fn addDefault(var self)
		items.push(items.len)  # 'items' es una ruta de campos: lugar simple

fn main()
	let c = Cfg()
	c.addDefault()
```
El receptor se **evalúa** antes (de izquierda a derecha) pero su préstamo único solo se **toma**
al ejecutarse la llamada; la elaboración adelanta los argumentos a temporales
(`docs/SOUNDNESS.md` §9, `docs/FORMAL.md` §3). El caso general, con receptor que lleva índice o
llamada, sigue en `R12`.

### A12 — Dos préstamos únicos simultáneos sobre **campos distintos** (`A7`, resuelto)
```python
type Pair
	a: [int] = []
	b: [int] = []

fn swap(var x: [int], var y: [int])
	let t = x[0]
	x[0] = y[0]
	y[0] = t

fn main()
	var p = Pair(a: [1], b: [2])
	swap(p.a, p.b)        # ACEPTAR: overlap(p.a, p.b) es falso, los lugares son disjuntos
	print(f"{p.a[0]} {p.b[0]}")
```
Implementado: la variante §5.3 de `FORMAL.md` (lugares = caminos, `overlap` en vez de `same_place`)
y la puerta de llamada del §10.3 ya están en `tools/borrow.py` (`_overlap`). Verificado por
ejecución directa: el checker acepta este programa. **Este es el caso que `R13` rechazaba
originalmente (ver `R13`, ya actualizado).**

Y sus dos hermanos, que **deben rechazarse siempre** (los lugares solapan):

```python
fn main()
	var p = Pair()
	swap(p, p)            # RECHAZAR: los dos argumentos son el mismo lugar
	swap(p.a, p.a)        # RECHAZAR: el mismo campo dos veces
```

### A13 — Dos préstamos únicos **secuenciales** sobre campos distintos (`A7`, ya aceptado)
```python
type Pair
	a: [int] = []
	b: [int] = []

fn fill(var v: [int], n: int)
	for i in 0..n
		v.push(i)

fn main()
	var p = Pair()
	fill(p.a, 1)          # ACEPTAR ya en v0.1: este prestamo muere en su ultimo uso (R7)
	fill(p.b, 1)          # y el siguiente empieza despues: no se solapan en el tiempo
```
**No es incompletitud** y no depende de §10: las reglas de §5.2 ya lo aceptan. Es un test contra el
bug de no devolver `Owned` al morir un préstamo.

---

## 4. Uso

| Momento | Uso |
|---|---|
| M0 (`docs/FORMAL.md` §9) | Cada caso se ejecuta en el interpretador de referencia; `RECHAZAR` debe dar *fault* si se fuerza la ejecución |
| M1 | El checker debe dar exactamente el veredicto indicado |
| Pruebas de mutación | Quitar la regla de R4 debe hacer que R4 pase a `ACEPTAR`: si no, el caso no prueba nada |
| R12 parcial (v0.1, `A11`) | Aceptar cuando el receptor es un **lugar simple**; rechazar el caso general |
| R13 (v0.1.1, `A12`) — **ya adoptado** | `SOUNDNESS.md` §10 / `FORMAL.md` §5.3 ya están implementados en `tools/borrow.py` (`_overlap`): `A12` se acepta y R13 se redujo a los casos que solapan (`swap(p, p)`, `swap(p.a, p.a)`) |
| `A13` | Debe aceptar **ya** en v0.1: si falla, el bug está en la máquina de estados de préstamos, no en el modelo |
