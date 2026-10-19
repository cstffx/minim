# Minim 0.1 — propiedad y *borrow checker*

Objetivo doble: **seguridad de memoria sin GC** y **muy pocos tokens** para expresarlo.
La forma de lograrlo es no escribir nada que el compilador pueda deducir de forma local.

---

## 1. Un valor, un dueño

- Todo valor tiene **un único dueño**: la variable que lo enlaza.
- Al salir de ámbito el dueño se destruye (**drop determinista**), en orden inverso a la
  declaración. No hay recolector de basura ni pausas.
- `let` enlaza inmutable; `var` enlaza mutable. No hay `mut` en ninguna otra posición.

```python
let nombre = "ana"          # dueño: 'nombre', inmutable como enlace
var contador = 0            # dueño: 'contador', mutable
contador += 1               # permitido
# nombre = "luis"           # error: 'nombre' es inmutable
```

## 2. Préstamos: `&x`, con el modo en la firma ⚠️

`&expr` toma prestado el valor **sin transferir la propiedad**. El modo del préstamo
(**compartido** o **único**) se declara **una sola vez, en la cabecera** de la función
(`var` = único); dentro del cuerpo no hay ningún sigilo, así que **no existe `&mut` ni `mut`**.

```python
fn len(v: [int]) -> int         # prestamo compartido: modo por defecto
	v.len

fn push(var v: [int], x: int)   # 'var' declara el prestamo unico
	v.push(x)
```

- Préstamo **compartido**: cuantos se quiera a la vez.
- Préstamo **único**: excluyente (ni lecturas mientras dure).
- El modo forma parte de la **firma**, no se infiere del cuerpo: es lo que permite que el
  índice de símbolos y el *firewall* incremental sean correctos (ver `docs/SOUNDNESS.md` §2,
  agujero A1, y §4).
- Mutar a través de un parámetro sin `var` es un **error**, no una inferencia:
  `fn f(v: [int])` con `v.push(x)` en el cuerpo no compila.
- Escribir a través de un préstamo exige además que el **enlace del llamante** sea `var`:
  `push(v, 1)` falla si `v` se declaró con `let`; el mensaje lo sugiere.
- Un préstamo dura **hasta su último uso** (no hasta el fin del bloque), así que
  `print(v.len)` y luego `v.push(1)` es legal.

Ventaja medida: `fn f(var v: [int])` cuesta **8 tokens** frente a `fn f(v: &mut Vec<i64>)`
(**10**) sin perder la exclusividad, porque el modo se escribe una vez y no en cada llamada.

## 3. Modos de parámetro (los tres únicos)

| Declaración | Significado | ¿Consume el argumento? |
|---|---|---|
| `fn f(x: T)` | préstamo **compartido** (por defecto) | no |
| `fn f(var x: T)` | préstamo **único** | no |
| `fn f(move x: T)` | **transferencia** de propiedad | sí |

**Los parámetros son préstamos por defecto.** Razones: (a) ahorra ~2 tokens por parámetro,
(b) elimina la clase de error más frecuente que cometen los modelos de lenguaje
(*use after move*), (c) hace que llamar a una función nunca destruya tus datos, como en
Python o Go.

**El modo es parte de la firma y no se infiere del cuerpo.** Es una decisión de coherencia:
la firma es el contrato que publican el índice (`docs/INDEXACION.md`), la huella de
compilación incremental (`docs/COMPILACION.md` §3) y el mensaje de error. Si el modo se
dedujera del cuerpo, cambiar un cuerpo cambiaría la interfaz. Dentro del cuerpo sí se infiere
todo lo que es local: tipos de locales y retorno, regiones de préstamo, `async`, resolución de
nombres.

```python
fn consume(move v: [int]) -> int   # se queda con 'v'
	v.len

var datos = [1, 2, 3]
print(consume(datos))              # 'datos' ya no existe aqui
# print(datos.len)                 # error: se movio en la linea anterior
```

**Receptores** en métodos usan las mismas tres formas:

```python
type Buf
	data: [int] = []
	fn len(self) -> int            # prestamo   -> &self
		data.len
	fn push(var self, x: int)      # unico      -> &mut self
		data.push(x)
	fn take(move self) -> [int]    # consume    -> self
		data
```

Sin `&self` ni `&mut self`, sin `self.` para los campos (el nombre resuelve a local y luego
a campo), sin `mut` extra. Es la superficie mínima que expresa lo mismo que Rust.

## 4. Reglas del *borrow checker*

Se comprueban **dentro de cada función** (análisis local, flujo intra-procedural). No hay
análisis global, ni solver, ni parámetros de vida.

| # | Regla | Error típico |
|---|---|---|
| R1 | Un préstamo único es exclusivo: no coexiste con otros préstamos | `'b' ya tiene un prestamo unico activo` |
| R2 | Préstamos compartidos ilimitados | — |
| R3 | Un préstamo no puede sobrevivir al dueño | `'v' se destruye aqui, pero 'r' lo usa despues` |
| R4 | Tras un `move`, el enlace queda inválido | `no se puede usar 'v' despues de moverla` |
| R5 | No se devuelve un préstamo de un local | `no se puede devolver un prestamo de un local` |
| R6 | No se presta mientras hay un préstamo único activo | (misma que R1) |
| R7 | Un préstamo termina en su último uso | — |

**Los préstamos no se guardan en campos de estructuras** (v0.1). Esto es lo que elimina toda
la sintaxis de *lifetimes* (`'a`, `<'a, T>`, `where`): un préstamo solo vive como local,
parámetro, retorno de una llamada o valor de expresión. Compartir y la recursión se expresan
con `T?` (opcional = puntero) y con colecciones.

```python
type Node                      # recursion sin Box ni lifetimes
	valor: int
	sig: Node? = nil
```

## 5. Copiar o mover

Un tipo es **copiable** si todos sus campos lo son: `int`, `float`, `bool`, `str` pequeño,
`bytes`, `nil` y productos de copiables. Todo lo demás (listas, mapas, `T?` con contenido)
**se mueve**.

```python
let p = Point(x: 1, y: 2)
let q = p                      # copia: Point es copiable
print(p.x, q.x)                # ambos validos

let a = [1, 2, 3]
let b = a                      # mueve: una lista no es copiable
# print(a.len)                 # error: 'a' se movio
let c = a.copy()               # NO existe .copy() implicito; ver alternativa
```

Para duplicar explícitamente se usa `copy(x)` del prelude (1 token), o se construye de nuevo
(`[...]`), o se pasa por préstamo y se deja que la función copie lo que necesite. No hay
`Clone`, `Into`, `as_ref`, `to_owned`.

**Los movimientos parciales están prohibidos en `v0.1`**: se mueve el valor completo, nunca un
campo aislado. Elimina las banderas de *drop* y con ellas la posibilidad de doble liberación
(ver `docs/SOUNDNESS.md` §2, A3).

## 6. Prestado, movido y devuelto

```python
fn primero(v: [int]) -> int?           # devuelve una copia, nunca un prestamo
	if v.len > 0: v[0] else: nil

fn extremos(v: [int]) -> (int, int)    # dos lecturas prestadas, sin conflicto
	(v.first, v.last)

fn duplica(var v: [int])               # muta in situ
	for i in 0..v.len
		v[i] *= 2
```

**Devolver un préstamo está restringido** (antes este documento lo daba por trivial, y no lo
es: `let r = f(temporal)` colgaría). Reglas de elisión de v0.1:

- Si el retorno contiene `&T`, debe haber **exactamente un** parámetro de referencia **o** el
  receptor `self`: el préstamo devuelto se ata a ese. Cualquier otro caso es error.
- **Los temporales mueren al final de la sentencia**, así que `let r = f([1, 2, 3])` es error
  (el préstamo sobrevive al temporal). Igual que NLL en Rust.
- Un préstamo **no** se puede guardar en un campo ni devolver dentro de una estructura
  (`v0.1`): es lo que elimina la sintaxis de *lifetimes*.

En `v0.1`, `mitad` devuelve una **copia**; las "vistas" persistentes llegarán con `trait View`
en `v0.2`, y con ellas los *lifetimes*. Es una restricción deliberada, no un descuido:
ver `docs/SOUNDNESS.md` §2 (A2) y §6.

```python
fn mitad(v: [int]) -> [int]            # copia, no prestamo devuelto
	v[0:v.len / 2]
```

## 7. Interacción con errores, `match` y closures

```python
let cfg = load(p)?             # si hay error, retorno temprano -> aqui acaban los prestamos
let n = s.parse[int]() or 0    # 'or' no alarga la vida de nada

match buf
	case ok(v): usa(v)         # 'v' es el dueño dentro de la rama
	case err(e): log(e)

let f = fn x: int => x + base    # captura 'base' por prestamo
let g = move fn x: int => x + base  # captura por valor: 'base' se mueve a 'g'
```

- Un retorno temprano (`?`, `or:` + `return`, `return`) **cierra** todos los préstamos activos.
- Un `match` sobre un valor por movimiento consume la rama que elija; sobre un préstamo, no.
- Las closures capturan por préstamo por defecto; `move` antes de la closure captura por valor.
- Las closures **no escapan** en `v0.1`: no se devuelven ni se guardan en campos. Si pudieran,
  sobrevivirían al préstamo que capturan (ver `docs/SOUNDNESS.md` §2, A4).
- `spawn f(a, b)` **transfiere** los argumentos (el `move` es implícito) y exige que estén
  aislados: sin préstamos vivos y sin `rc` (solo `arc`). Ningún valor con préstamo vivo cruza
  un `await`. Esta restricción sustituye a `Send`/`Sync` (`docs/SOUNDNESS.md` §3, I5).

## 8. Dinámico y compartido (std, v0.2)

- `rc[T]` / `arc[T]`: propiedad compartida con conteo de referencias, para grafos y caches.
  Se usan explícitamente (`rc.new(x)`, `x.clone`), nunca de forma implícita.
- `weak[T]` para romper ciclos.
- Ciclos con `T?` y dueño único no pueden fugarse de forma silenciosa.

## 9. Diagnósticos

Un error de propiedad es siempre **una línea, un span, un nombre** (sin sobrecarga ni
coerciones profundas, el compilador siempre puede señalar la declaración exacta):

```
buf.mim:12:9  error: 'b' ya tiene un prestamo unico activo (tomado en 11:3)
buf.mim:12:9  nota: el prestamo termina en su ultimo uso; los prestamos compartidos no lo necesitan
```

Se permite un préstamo compartido mientras el único duerme, y el mensaje propone la solución
más corta, que casi siempre es cambiar `let` por `var` (1 token).

## 10. Resumen frente a Rust

| Necesidad | Rust | Minim | Tokens |
|---|---|---|---|
| Enlace mutable | `let mut x` | `var x` | 6 -> 5 |
| Préstamo mutable en parámetro | `&mut Vec<i64>` | `var [int]` | 10 -> 8 |
| Receptor mutable | `&mut self` | `var self` | 2 tokens menos |
| Campo desde un método | `self.n` | `n` | −30% del cuerpo |
| Devolver o propagar error | `match`/`?` con `Result` | `?` | 28 -> 8 |
| Copia explícita | `.clone()` | `copy(x)` | igual |
| Compartir | `Rc<RefCell<T>>` | `rc[T]` | menos |
| Vidas | `'a` + `where` + `PhantomData` | no existe | la mayor parte del ahorro |
