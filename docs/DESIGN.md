# Minim 0.1 — diseño del lenguaje

Documento normativo. Todo lo demás (`grammar.ebnf`, ejemplos, `TOKENS.md`) se deriva de aquí.

---

## 0. Principios

| # | Principio | Consecuencia |
|---|---|---|
| P1 | **Una sola forma de hacerlo** (OWTDI) | Menos entropía: el modelo predice mejor el siguiente token y comete menos errores. Hay **una** forma de declarar, **una** de iterar, **una** de ramificar por variantes. |
| P2 | **Lo frecuente debe ser corto** | La forma más común de cada construcción no lleva marcadores opcionales (p. ej. un método que solo lee no escribe `&self`). |
| P3 | **Cero puntuación redundante** | Sin `;`, sin `{}` para bloques, sin paréntesis obligatorios en `if/while`. |
| P4 | **El compilador puede adivinar; el humano no debería tener que escribir** | Inferencia de tipos en locales, retorno y expresiones; regiones de préstamo; `async` inferido; `self.` implícito. **El modo de un parámetro no se infiere**: forma parte de la firma. |
| P5 | **Las declaraciones son la unidad de indexación** | Cabecera en columna 0, palabra clave primero, firma en una línea, documento justo encima. |
| P6 | **Análisis local** | Todo lo comprobable se comprueba función a función: sin análisis global, sin solver, sin recursión de tipos sin límite. |

**Nombre / extensión:** `Minim`, ficheros `.mim`. Índice: `.mimidx`. CLI: `minim run|build|fmt|index|test`.

---

## 1. Léxico

### 1.1 Fichero
- UTF-8, saltos de línea `LF` (se toleran `CRLF`).
- **Un fichero = una unidad = un módulo.** El nombre del módulo es la ruta relativa sin extensión:
  `use fs` -> `std/fs.mim`; `use mylib.util` -> `mylib/util.mim` (primero `std/`, luego el directorio del proyecto).
- `use a, b.c` — una sola forma de importar, sin `from/import/module`.

### 1.2 Sangría ⚠️
- **Un tabulador por nivel. Solo tabuladores.** Prohibido mezclar espacios y tabuladores (error léxico).
- El formateador canónico emite tabuladores. Razón medida: `\n\t` + `x` se fusiona en un token frente a
  **dos** tokens de `\n` + `    `; ahorra ~1 token por línea indentada (`docs/TOKENS.md` §4).
- La continuación de línea **solo** es posible dentro de `( ) [ ] { }`. No existe `\`, ni continuación
  implícita tras operador. Si una condición es larga, se rodea de paréntesis.
  (Los fragmentos de este documento usan 4 espacios por legibilidad; el código real usa
  tabuladores, ver `examples/`.)

### 1.3 Comentarios
- `#` hasta fin de línea. Única forma.
- Un bloque de líneas `#` **inmediatamente encima** de una declaración es su documentación
  (posicional, sin `##`, `///` ni docstrings: coste cero en tokens nuevos).

### 1.4 Identificadores ⚠️
- ASCII, `[A-Za-z][A-Za-z0-9]*`.
- **`lowerCamelCase`** para valores, campos, funciones y módulos. **`PascalCase`** para tipos y traits.
- **Sin guiones bajos** en nombres compuestos: `userId`, no `user_id`.
  Medido: `userName` = 1 token (cl100k) frente a `user_name` = 2 tokens; con `o200k` empatan.
  Nunca cuesta más y a menudo cuesta la mitad.
- Prefijo `_` = privado del módulo. Sin prefijo = público. **No existe `pub`.** ⚠️
- `_` solo = descarte (`let _, b = pair`).
- Sin sobrecarga de funciones ni de operadores: **cada nombre identifica un único símbolo del módulo**.

### 1.5 Literales
```
123            0x1f   0b1010          # enteros (sin separadores: '_' cuesta tokens)
1.5   1e9      1.5e-3                 # flotantes
"texto\n"      r"c:\raw"              # str y str cruda
f"hoy {name}, {n} items"              # str interpolada
b"\x00\x01"                           # bytes
"""varias
lineas"""                             # multilínea
true   false   nil                    # bool / unidad
[1, 2, 3]                             # lista
{"a": 1, "b": 2}                      # mapa
{1, 2, 3}                             # conjunto
(1, "a")                              # tupla
```

### 1.6 Operadores
```
Binarios   +  -  *  /  //  %  **        aritmética  (// división entera, ** potencia)
Comparación ==  !=  <  <=  >  >=        (encadenables: a < b < c)
            and  or  not   in  is  as
Bits       &  |  ^  ~  <<  >>
Acceso     .  []  ()  :  ,  ..  ..=  ?
Módulos    &  (préstamo)   ->  (retorno)   =  +=  -=  *=  /=  //=  %=  **=
```
- `!` **no** es negación lógica (es `not`); `!` solo aparece como sufijo de tipo (`T!`).
- `?` es sufijo de expresión (propaga error) y sufijo de tipo (`T?` opcional).
- Sin `++`, `--`, sin `?:`, sin `&&`/`||` (medido: mismo coste en tokens que `and/or`, y `!`/`||` se
  confunden con tipos de error).

---

## 2. Palabras clave (29)

Todas son 1 token en todos los tokenizadores probados, así que **acortarlas no ahorra tokens**;
lo que ahorra es *no tener más*. Cada una existe solo si sustituye a ≥2 tokens de sintaxis.

| Grupo | Palabras |
|---|---|
| Módulo y declaración | `use` `let` `var` `fn` `type` `case` `trait` |
| Control | `if` `elif` `else` `for` `in` `while` `break` `continue` `return` `match` |
| Expresión | `and` `or` `not` `is` `as` |
| Propiedad | `self` `move` `var` |
| Concurrencia | `spawn` `await` |
| Constantes | `true` `false` `nil` |

### 2.1 Lo que **no** existe (y por qué)

| No existe | Se escribe | Ahorro |
|---|---|---|
| `pub` | público por defecto, `_nombre` privado | 1 token por declaración |
| `const` | `let` en el módulo se evalúa en tiempo de compilación si es literal | 1 palabra clave |
| `enum` | `type` + `case` | 1 palabra clave, misma semántica |
| `class` `struct` `impl` | `type` con métodos dentro | 3 palabras clave y un nivel de sangría |
| `module` `import` `from` | fichero = módulo; `use` | 3 palabras clave |
| `mut` | `var` (1 token) en el enlace; el modo va en la firma | `let mut` (2) -> `var` (1) |
| `try` `except` `raise` `finally` | `or`, `?`, tipo `T!` | ~15 tokens por manejo de error |
| `async` | inferido por el uso de `await` en el cuerpo | 1 palabra clave + 1 token por `fn` |
| `new` | llamada al tipo: `Point(x: 1)` | 1 token por construcción |
| `lambda` | `fn x => x + 1` | 0 |
| `pass` | un bloque puede estar vacío | 1 palabra clave |
| `with` | destrucción determinista al salir de ámbito | 2 tokens por recurso |
| `yield` | `v0.2` (iteradores por `trait`) | — |
| `del` | `x.remove(k)` / `x.pop()` | 1 palabra clave |
| `self.` | resolución local -> campo (como Kotlin/Dart) | **~30% del cuerpo de un método** |
| *lifetimes* `'a` | los préstamos no se guardan en estructuras | toda la sintaxis de regiones |
| `&mut` | `var x` en el parámetro (modo único) | 1 token por préstamo, y el modo se escribe una vez |

---

## 3. Declaraciones (columna 0)

```python
use fs, env                 # importaciones

let maxItems = 100          # constante de módulo (inmutable, plegada si es literal)

type Point                  # tipo producto + metodos
	x: float
	y: float
	fn len(self) -> float   # prestamo compartido implicito (!)
		(x * x + y * y) ** 0.5

type Shape                  # tipo suma: variantes con 'case'
	case Circle
		r: float
	case Rect
		w: float
		h: float
	fn area(self) -> float
		match self
			case Circle(r): pi * r * r
			case Rect(w, h): w * h

trait Ord
	fn cmp(self, o: Self) -> int

fn max[T: Ord](a: T, b: T) -> T    # generico acotado
	if a.cmp(b) > 0: a else: b
```

Reglas:

- **`let`** = enlace inmutable. **`var`** = enlace mutable. Locales y módulo usan lo mismo.
  (Medido: `var x = 0` = 5 tokens frente a `let mut x = 0` = 6.)
- **El tipo se omite** cuando se puede inferir (`let n = 3`). Es obligatorio en los **parámetros**
  (lo necesita el índice) y **opcional en el retorno** (se infiere del cuerpo, que ya está compilado
  porque las firmas se escanearon primero).
- **El modo también es obligatorio en la firma**: sin marcador = préstamo compartido, `var` =
  préstamo único, `move` = transferencia. Mutar a través de un parámetro sin `var` es un error.
  Motivo: la firma es el contrato del índice y de la compilación incremental
  (`docs/SOUNDNESS.md` §2, A1).
- **Sin declaraciones adelantadas:** puedes llamar a una función declarada más abajo; la fase de
  firmas ya la conoce. No hay cabeceras `.h`/`interface`.
- El **último valor** del cuerpo es el retorno (`return` explícito disponible).
- `fn` sin receptor (`fn new(...)`) = función asociada: `Point.new(1, 2)`.
- Los campos con `= valor` tienen valor por defecto y hacen que el tipo tenga constructor
  generado: `Point()` y `Point(x: 1, y: 2)`.

---

## 4. Sentencias

```python
let x = 1                       # inmutable
var n = 0                       # mutable
n += 1
let a, b = pair                 # desestructuracion de tupla
let c: float = 2                # anotacion opcional

if n > 10
	print("grande")
elif n > 3
	print("medio")
else
	print("pequeño")

for x in items                  # iteracion
	print(x)
for i, x in items               # indice + valor
	print(i, x)
for k, v in m.items
	print(k, v)
for i in 0..10                  # sin 'a'
	print(i)
while activo
	tick()
	break

match res                       # ramificacion por variantes
	case ok(v): print(v)
	case err(e) if e.code == 2: print("reintentar")
	else: print("otro")

spawn worker(3)                 # concurrencia
let t = spawn worker(3)
await t
return x                        # opcional (ultima expresion)
```

- **Sin `;`**, una sentencia por línea (el formateador garantiza la forma canónica).
- `:` + salto de línea = 1 solo token en los tokenizadores BPE (medido): la cabecera de bloque
  con `:` es **gratis** frente a no ponerla.
- Los bloques pueden estar vacíos (no hay `pass`).
- Sentencias de nivel superior = cuerpo del programa (como el `begin/end.` de Delphi): si existe
  `main()`, se llama después; útil para programas mínimos donde no se quiere ceremonia.

---

## 5. Expresiones

```python
1 + 2 * 3                      # precedencia habitual
a < b < c                      # comparaciones encadenadas
not found and ready or backup  # and/or/not, sin parentesis obligatorios
x in list      k in map        # pertenencia (reutiliza 'in')
v is nil       v is not nil    # identidad/nulo (reutiliza 'is')
n as float                     # conversion (reutiliza 'as')
&v                             # prestamo; el modo lo fija la firma
p.x    p.len                   # campo / propiedad (sin parentesis para propiedades)
s[2]   s[1:4]   s[:4]  s[2:]   # indice y rebanadas
f(a, b)   f(b: 2, a: 1)        # llamada; argumentos con nombre opcionales
f"{k:6} {w}"                   # interpolacion
(1, "a")   [1, 2]   {"k": 1}   # tuplas, listas, mapas
fn x => x * 2                   # closure (captura por prestamo)
move fn x => x + 1              # captura por valor
it * 2                          # closure implicita: equivalente a fn it => it * 2
if c: a else: b                # if en posicion de expresion (una linea)
match v: case A(x): 1 else: 0  # match en posicion de expresion
```

Decisiones y su porqué:

- **Campos sin `self.`**: dentro de un método, `n` resuelve primero a local, luego a campo del tipo.
  Medido: un cuerpo de método típico pasa de 10 a 7 tokens (**−30%**). Igual que Kotlin/Dart.
- **Propiedades sin paréntesis**: `s.len` (2 tokens) frente a `len(s)` o `s.len()` (3 tokens).
- **Interpolación `f"..."`**: 7 tokens frente a `"{}-{}".format(a, b)` (9) o `printf` (10).
- **Argumentos con nombre** reutilizan `:` (no hay sintaxis nueva) y evitan el error clásico de
  orden de argumentos que más cometen los LLM.
- **`if`/`match` en posición de expresión** permiten escribir en una línea lo que Python escribe
  en tres, reutilizando `:` y `else` (cero palabras clave nuevas).
- **`it` implícito**: en un argumento donde se espera una función de un parámetro (`T -> U`),
  una expresión que usa `it` se eleva a `fn it: T => expr`. Medido: `xs.map(it * 2)` = 7
  tokens frente a `xs.map(fn x => x * 2)` = 11 (**−36 %**); en cadenas,
  `xs.filter(it > 0).map(it * 2)` = 13 frente a 21 (**−38 %**). `it` también es el enlace del
  error en un bloque `or:`. Es una palabra clave, no se puede usar como nombre de variable.

---

## 6. Patrones (`case` de `match` y de variantes)

```python
case 0                          # literal
case n                          # enlace
case Circle(r)                  # variante + campos por posicion
case Rect(w: 1)                 # campos por nombre
case (a, b)                     # tupla
case ok(v) if v > 10            # guarda (reutiliza 'if')
else                            # por defecto (reutiliza 'else', no '_')
```

Sin `_`, sin `default`, sin `switch`: `else` hace de comodín y `case` sirve tanto para declarar
como para ramificar.

---

## 7. Sistema de tipos

| Tipo | Tokens | Notas |
|---|---|---|
| `int` | 1 | i64 por defecto |
| `float` | 1 | f64 por defecto |
| `bool` `str` `bytes` `nil` | 1 | — |
| `i8 i16 i32 u8 u16 u32 u64 f32 f64` | 1 | anchos explícitos cuando importan |
| `[T]` | 2 | lista (medido: `[int]` = 2, `Vec<i64>` = 4, `list[int]` = 3) |
| `map[K, V]` | 3 | mapa |
| `set[T]` `(A, B)` | 2-3 | conjunto, tupla |
| `&T` | 2 | préstamo |
| `T?` | 2 | opcional (`nil` o `T`). Medido: 9 frente a `Optional[int]` 11 y `int | None` 12 |
| `T!` | 2 | valor o error |
| `(int, str) -> bool` | 5 | tipo función |

- **Tipado estructural**, sin herencia. Una variante es un tipo producto y el `type` que las
  contiene es la unión.
- **Igualdad y copia**: un tipo se copia implícitamente si todos sus campos son *copiables*
  (tipos primitivos y productos de copiables). Todo lo demás se mueve. No hay `Clone`/`Copy` que
  escribir: lo decide el compilador, y el usuario puede forzar `move`.
- **Genéricos**: `[T]` (medido: mismo coste que `<T>` pero sin ambigüedad con `<`/`>`),
  restringidos por `trait` (`T: Ord`). Monomorfización memoizada, profundidad limitada.
- **Sin overloading** => el nombre de una función es su símbolo. Indexación trivial y resolución
  de llamadas en un solo paso.
- **Los préstamos no se guardan en campos** (`v0.1`) => cero sintaxis de *lifetimes*, cero
  parámetros de tipo de vida, análisis local. Es la simplificación más rentable del diseño.
  Recursión y compartir se expresan con `T?` (opcional = puntero) y `[T]`/`map`.

---

## 8. Errores y opcionales

Un solo mecanismo de error: **el valor**. `T!` = `T` o `err`. El operador `?` propaga.

```python
fn load(p: str) -> Config!             # firma: puede fallar
	let s = fs.read(p)?                # propaga
	json.parse(s)?                     # propaga

let cfg = load(path) or default        # valor por defecto (reutiliza 'or')
let n = s.parse[int]() or continue     # en bucle: ignorar y seguir (9 tokens vs 24 en Rust)
let c = load(path) or:                 # bloque de error (1 token)
	eprint(f"error: {it}")
	return
```

- `err` es un tipo del prelude: `err(msg: str, code: int = 0)`; se construye `err("boom", 404)`.
- Dentro de un bloque `or:` el error está ligado a `it`. El mismo identificador `it` se usa
  como parámetro implícito en funciones de orden superior (ver §5): el contexto decide el enlace.
- `or` es **el mismo operador** que el `or` lógico: "si el lado izquierdo no sirve, usa el derecho".
  Un operador, dos usos, cero palabras clave nuevas. Medido: propagar un error cuesta 8 tokens
  frente a 28 de `match { Ok(n) => n, Err(e) => return Err(e) }` en Rust.
- `T?` (opcional) se comprueba con `is nil`, `or` o `match`; no hay `unwrap` obligatorio ni `!`.

---

## 9. Concurrencia

```python
let t = spawn fetch(url)        # task[response]!
let r = await t?
```

- `spawn` = 1 token, `await` = 1 token, el tipo `task[T]` es del prelude.
- No hay `async`: si el cuerpo de una `fn` usa `await`, es asíncrona.
- Sin canales ni primitivas de sincronización en `v0.1` (llegarán como módulo `task`).

---

## 10. Prelude

Regla de nombres: **≤ 8 caracteres, `lowerCamel`, sin abreviaturas crípticas** (`len` sí, `lng` no).
Todo nombre del prelude es 1 token en todos los tokenizadores probados.

- Funciones: `print` `eprint` `range` `min` `max` `abs` `str` `int` `float` `assert` `panic` `drop`
- Propiedades y métodos de `[T]`: `.len` `.push` `.pop` `.get` `.insert` `.remove` `.sort` `.sortBy`
  `.map` `.filter` `.fold` `.any` `.all` `.find` `.first` `.last` `.reverse` `.slice` `.contains`
  `.join` `.top` `.count`
- `str`: `.len` `.words` `.lines` `.split` `.trim` `.lower` `.upper` `.strip` `.contains` `.starts`
  `.ends` `.parse[T]()` `.replace` `.join` `.bytes`
- `map[K,V]`: `.len` `.get` `.has` `.del` `.keys` `.values` `.items` `.top`
- Módulos: `fs` `env` `io` `net` `json` `time` `rand` `math` `os` `task`
  - `fs.read` `fs.write` `fs.lines` `fs.exists` `fs.ls`
  - `env.args` `env.arg` `env.get` `env.set`
  - `net.get` `net.post` `net.serve`
  - `json.parse` `json.str`
  - `time.now` `time.sleep`
- Constantes: `pi`, `e`, `nil`, `true`, `false`.
- **Sin `unwrap`, sin `clone`, sin `into`, sin `.to_string()`**: conversiones con `str(x)`,
  `x.parse[T]()` y `x as T`.

---

## 11. Estilo canónico (`minim fmt`)

El formateador es normativo: existe **una** representación en bytes de cada programa.
Esto hace que (a) los diffs sean mínimos, (b) el coste en tokens de cada construcción sea
determinista, (c) el prompt cache del modelo sea reutilizable.

- 1 tab por nivel; sin líneas en blanco dobles ni al principio/final de bloque.
- Una sentencia por línea. Bloques de expresión (`case X: expr`, `if c: a else: b`) en una línea.
- Cabeceras de declaración en una línea (los parámetros pueden partirse dentro de `(` `)`).
- `#` con un espacio después. Documento pegado a la declaración, sin línea en blanco entre medias.
- Espacios solo alrededor de operadores binarios; `,` `:` sin espacio delante.

---

## 12. Cómo de fácil es para una IA

Además del coste medido:

1. **Gramática pequeña y LL(1)-ish**: 29 palabras clave, una forma por construcción, sin
   ambigüedades de *dangling else* ni de `<` genérico. Un modelo puede generar el esqueleto con
   pocas decisiones condicionales.
2. **Índice barato**: para saber qué hay en un módulo, la IA solo necesita las líneas que
   empiezan con palabra clave en columna 0 (más el `#` de encima). Es un resumen que cabe en
   contexto sin enviar los cuerpos.
3. **Errores del compilador con nombre exacto**: al no haber sobrecarga ni coerciones implícitas
   profundas, el mensaje apunta a una única declaración: `shape.mim:14: fn area -> Shape no tiene
   campo 'red'`.
4. **Menos tokens de salida = menos latencia y menos coste**, y menos probabilidad de truncar una
   generación (los programas largos caben antes en el límite).
5. **Sin estados globales de sintaxis** (sin `pub`, sin cabeceras, sin orden de declaración): el
   modelo no necesita recordar el contexto de imports ni de visibilidad.

---

## 13. Decisiones abiertas ⚠️

| # | Decisión | Alternativa | A favor de lo elegido |
|---|---|---|---|
| 1 | Parámetros por **préstamo** por defecto; `move`/`var` explícitos | `&` explícito como Rust | −2 tokens por parámetro, menos errores de *move* generados por IA; contra: oculta el coste |
| 2 | **`lowerCamelCase`** | `snake_case` | −50% de tokens en identificadores largos con `cl100k`; contra: menos "pythónico" |
| 3 | **Sangría con tab** | 2 o 4 espacios | −1 token por línea indentada; contra: debate estilístico |
| 4 | Sin préstamos en campos de estructuras | lifetimes `'a` | Elimina toda la sintaxis de regiones y el análisis global |
| 5 | `or:` con bloque + `it` | `try/except` | 1 token frente a ~6 por manejo de error |
| 6 | Campos accesibles sin `self.` | `self.x` obligatorio | −30% en cuerpos de método; contra: sombreado (resuelto a favor del local) |
| 7 | Sin sobrecarga de funciones | overloading | Índice y resolución de llamadas triviales |

**Estado de la garantía de memoria:** el modelo está especificado (`docs/OWNERSHIP.md`) pero
**no demostrado**. Los agujeros conocidos, las correcciones aplicadas y lo que falta para
poder llamarlo *sound* están en [`docs/SOUNDNESS.md`](SOUNDNESS.md).
