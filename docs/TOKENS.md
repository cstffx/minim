# Minim 0.1 — coste en tokens: reglas y mediciones

Todo lo que sigue está **medido**, no estimado. Reproducible con
`python3 tools/measure.py` y `python3 tools/micro.py`.

## 1. Metodología

- Tokenizadores BPE **reales** de OpenAI: `o200k_base` (GPT-4o/5) y `cl100k_base`
  (GPT-4, y el que más se parece al de la mayoría de modelos abiertos).
- Se mide el **fichero completo** tal cual, sin normalizar ni minificar nada: es lo que un
  modelo tendría que generar o leer.
- Corpus: 5 programas en Minim, Python (sin y con anotaciones de tipo) y Rust. Cada trío
  implementa exactamente lo mismo.
- Las micro-mediciones aíslan *una* decisión de sintaxis cada vez, sobre fragmentos equivalentes.
- Formato de las tablas: `o200k / cl100k`.
- Advertencia honesta: son 5 programas, no un benchmark. Con `d_borrow`, Python **sin tipos**
  es más corto que Minim (40 vs 53 tokens): el ahorro de Minim es frente a lenguajes
  **tipados** y con propiedad verificada, y frente a Python cuando este también se tipa.

## 2. Resultados por programa

| programa | Minim | Python | Python tipado | Rust |
|---|---|---|---|---|
| `a_counter` tipo + método + uso | **50 / 50** | 65 / 65 | 65 / 65 | 91 / 91 |
| `b_shapes` tipo suma + `match` | **57 / 57** | 83 / 85 | 83 / 85 | 79 / 78 |
| `c_total` bucle + error | **51 / 51** | 58 / 57 | 58 / 57 | 83 / 83 |
| `d_borrow` firmas con préstamo | **53 / 53** | 40 / 40 | 57 / 57 | 70 / 70 |
| `wordcount` CLI completo | **130 / 132** | 154 / 153 | 206 / 205 | 272 / 266 |
| **TOTAL** | **341 / 343** | 400 / 400 | 469 / 469 | 595 / 588 |

| | Python | Python tipado | Rust |
|---|---|---|---|
| vs Minim (`o200k`) | **−15 %** | **−27 %** | **−43 %** |
| vs Minim (`cl100k`) | −14 % | −27 % | −42 % |

## 3. Reglas de minimización (cada una, con su medición)

### R1. Sin puntuación redundante
Sin `;`, sin `{}` para bloques. Y el `:` que abre bloque **es gratis**: `if x:` y `if x\n`
cuestan lo mismo (3 tokens) porque `":\n"` es **un único token**.

| | tokens |
|---|---|
| `if x:` + bloque de 4 líneas | 25 |
| `if (x) { ... }` equivalente | 28 |

### R2. Palabras clave cortas no ahorran; tener menos, sí
`fn`, `def`, `function` cuestan 1 token cada uno. Por eso Minim **no alarga** nada: lo que
hace es eliminar construcciones enteras (ver §2.1 de `DESIGN.md`). 29 palabras clave.

### R3. Inferencia de tipos en locales y en el retorno
`var t = 0` en vez de `var t: int = 0`. El tipo solo se escribe donde el índice lo necesita:
parámetros.

| | tokens |
|---|---|
| `fn f() -> int` | 5 |
| `fn f() -> i64` | 6 |
| `def f() -> int:` | 6 |

### R4. `var` en vez de `let mut`

| | tokens |
|---|---|
| `let mut x = 0` (Rust) | 6 |
| `var x = 0` (Minim) | 5 |
| `x = 0` (Python) | 4 |

### R5. Mutabilidad de préstamo explícita en la firma (sin `&mut`)

| | tokens |
|---|---|
| `fn f(var v: [int])` | 8 |
| `fn f(v: &mut Vec<i64>)` | 10 |
| `fn f(v: &[i64])` | 8 |
| `fn f(v: vector<int>)` | 7 |

El modo (`var`) se escribe **una vez en la firma**, no en cada llamada: por eso cuesta 2 tokens
menos que Rust sin perder la exclusividad. Un modo inferido del cuerpo ahorraría 1 token más
(`fn inc(self)` en vez de `fn inc(var self)`) pero rompería el contrato que publican el índice y
la huella incremental, así que se descarta (`docs/SOUNDNESS.md` §2, A1).

### R6. Sin `self.` en el cuerpo de un método
El nombre resuelve local -> campo.

| cuerpo equivalente | tokens |
|---|---|
| `n += by` / `n` | **7** |
| `self.n += by` / `return self.n` | 10 |

### R7. Errores como valores con `?` y `or` (en vez de `try/except` o `match Ok/Err`)

| caso | tokens |
|---|---|
| `let n = s.parse[int]()?` (propagar) | **8** |
| `let n = s.parse[int]() or continue` (ignorar) | **9** |
| Rust: `match ... { Ok(n) => n, Err(_) => continue }` | 24 |
| Rust: `match ... { Ok(n) => n, Err(e) => return Err(e) }` | 28 |

### R8. Interpolación de cadenas

| | tokens |
|---|---|
| `print(f"{a}-{b}")` | **7** |
| `print("{} - {}".format(a, b))` | 9 |
| `printf("%d-%d", a, b)` | 10 |

### R9. Tipos cortos y en minúscula

| forma | tokens |
|---|---|
| `[int]` | **2** |
| `list[int]` | 3 |
| `Vec<i64>` | 4 |
| `array of Int64` | 4 |
| `int?` (opcional) | **9** |
| `Optional[int]` | 11 |
| `int \| None` | 12 |

### R10. Genéricos con `[T]` en vez de `<T>`

| | tokens |
|---|---|
| `fn max[T: Ord](a: T, b: T) -> T` | 16 |
| `fn max<T: Ord>(a: T, b: T) -> T` | 16 |

Empate en tokens y ventaja en análisis: `[` `]` no se confunde con el operador `<`, no hay que
partir `>>` y el parser es determinista.

### R11. `elif` en vez de `else: if`

| | tokens |
|---|---|
| `if a: ... elif b: ...` | **17** |
| `if a: ... else: if b: ...` | 20 |
| `if a { ... } else if b { ... }` | 21 |

### R12. Propiedades sin paréntesis

| | tokens |
|---|---|
| `x.len` | **2** |
| `len(x)` | 3 |
| `x.len()` | 3 |

### R13. `lowerCamelCase` en vez de `snake_case` ⚠️

Cada `_` es un token propio en `cl100k_base`. Medido con 5 usos del mismo nombre:

| nombre | `snake_case` | `lowerCamel` |
|---|---|---|
| `user_name` | 10 / 10 | 10 / **5** |
| `is_empty` | 10 / 10 | 10 / **5** |
| `parse_int` | 10 / 10 | 10 / **5** |
| `to_string` | 10 / 10 | 10 / **5** |
| `total_price_amount` | 16 / 16 | 16 / **12** |

Nunca cuesta más y en `cl100k` cuesta la mitad. (Los nombres **cortos** de una sola palabra
son idénticos: `user`, `len`, `push` = 1 token siempre.)

### R14. Sangría con tabulador ⚠️

Mismo fichero de 10 líneas, misma lógica:

| sangría | tokens |
|---|---|
| 4 espacios | 58 / 57 |
| 2 espacios | 58 / 57 |
| **1 tab** | **55 / 54** |

`"\n\t"` + primer token se fusiona en un único token; `"\n" + "    "` son dos. ~1 token menos
por línea indentada. Además, tabulador único hace que el lexer no tenga que comparar
profundidades arbitrarias.

### R15. Documentación posicional con `#`

| | tokens |
|---|---|
| dos líneas `#` + `fn` | **22 / 22** |
| dos líneas `///` + `fn` | 22 / 22 |
| docstring de Python | 25 / 24 |

Coste cero en sintaxis nueva: el comentario ya existe, la posición lo convierte en documento.

### R16. Cero nuevas palabras clave para lo que ya existe

`or` es a la vez "o lógico" y "valor por defecto ante error"; `else` es la rama por defecto de
`if` **y** de `match`; `in` es iteración **y** pertenencia; `is` es identidad; `case` declara
variantes **y** ramifica. Cada reutilización es una palabra clave menos que el modelo debe
recordar.

### Contraejemplo medido (lo que NO ahorra)

| | tokens |
|---|---|
| `a and not b or c` | 7 |
| `a && !b \|\| c` | 7 |
| `not v` | 3 |
| `v.is_empty()` | 8 |
| `lambda x: x + 1` / `fn x => x + 1` | 7 / 7 |

No hay ahorro en cambiar símbolos por palabras ni en acortar los nombres del prelude; el
ahorro está en **quitar construcciones**.

## 4. De dónde sale el −43 % frente a Rust

Por orden de impacto medido y estimado sobre el corpus:

| Fuente | Ahorro |
|---|---|
| Sin sintaxis de *lifetimes* ni parámetros de vida | grande, difuso |
| Errores por valor (`?`, `or`) en vez de `match Ok/Err` | 8-28 tokens por punto de fallo |
| Sin `mut`, sin `&mut`, sin `self.` | 1-3 tokens por uso |
| Sin `pub`, sin `Clone`/`into`/`to_string`/`unwrap` | 1-4 tokens por uso |
| Tipos cortos (`[int]`, `int?`, `int!`) | 2-4 tokens por anotación |
| Campos accesibles sin `self.` | ~30 % del cuerpo de un método |
| Interpolación de cadenas | 2-3 tokens por mensaje |
| `lowerCamel` | 5-50 % de los identificadores multipalabra |

## 5. Reproducir

```bash
pip install tiktoken
python3 tools/measure.py     # tablas de §2
python3 tools/micro.py       # tablas de §3
```

Corpus: `tools/bench/` (4 pares Minim/Python/Rust) y `tools/bench2/` (wordcount).
Los tokenizadores se descargan la primera vez; para uso sin red, coloca los ficheros
`o200k_base.tiktoken` y `cl100k_base.tiktoken` en `$TIKTOKEN_CACHE_DIR` con el nombre del
SHA-1 de su URL de origen.
