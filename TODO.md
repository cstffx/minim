# TODO — estado real del compilador (fases 6-10)

Actualizado: 2026-10-22, sincronizado con `status.md` (fases 0-5 completadas) y verificado
ejecutando `minimc build`/`run` sobre cada constructo de esta lista.

El frontend (lexer/parser/resolve/typecheck/core IR/BIR/borrow checker) **ya acepta** toda la
superficie de `docs/DESIGN.md` que cubren los tests. Lo que queda está en el backend WASM
(`tools/codegen/`), en el prelude (fase 7), en la validación formal (fase 8) y en la suite de
tests/benchmarks (fase 9).

Estado end-to-end hoy: **2 de 5 `examples/*.mim` compilan y ejecutan** (`hello`, `shapes`);
`borrow`, `http` y `wordcount` fallan en codegen.

## 1. Fase 6: codegen desde BIR (siguiente)

El pipeline sigue compilando desde el AST elaborado. `minimc build` traduce a BIR solo para
el borrow check; `WasmCodegen` consume el AST. Plan de la fase (ver `PLAN.md`):

- [x] 6.1 Backend BIR para el subset escalar: `int`/`float`/`bool`/`str`/`nil`, locales y
      temporales tipados desde BIR, `Assign`/`Call`, `Goto`/`SwitchInt`/`Return`, funciones,
      recursion, `print`/`print_str`/`print_f64`, `StorageLive`/`StorageDead` como no-ops.
      Implementado en `tools/codegen_bir.py` + `tools/test_bir_codegen.py`; disponible con
      `minimc build|run --bir`.
- [ ] 6.2 Paridad de tipos compuestos en BIR: strings dinámicos, `list`, `tuple`, `struct`,
      sumas, campos/índices/`Place` no-local, agregados y `match` (usa los layouts de
      `tools/codegen/layouts.py`).
- [ ] 6.3 Paridad de `map`/`set`, closures y `T?`/`T!` en BIR.
- [ ] 6.4 Conmutar el pipeline por defecto a BIR y retirar el codegen desde AST cuando
      `test_core` + los 5 ejemplos pasen por la ruta BIR (comparación byte a byte del output).

## 2. Gaps de codegen verificados (ruta AST actual)

### 2.1 Ya soportado (no tocar salvo regresión)

- [x] `match` sentencia y expresión, guardas, `else`, bindings posicionales/nombrados.
- [x] `spawn`/`await`/`task[T]` (secuencial), `break`/`continue`.
- [x] `or`/`or:` con `it`, `?` dentro de funciones que devuelven `T!`, `err(msg, code)`.
- [x] F-strings (incluye formato `.Nf` y campos `{b.len}`), tuplas y destructuring.
- [x] Mapas, sets y sus literales; `map[K,V]`/`set[T]` **vacíos** no.
- [x] Closures `fn`, `move fn`, `it`, `list.map/filter`.
- [x] `if`/`match` como expresión, lógica cortocircuitada, comparaciones encadenadas.
- [x] Slicing de `str`, `bytes` y listas; `bytes` y sus métodos básicos.
- [x] Anchos explícitos `i8..u64`/`f32` (se normalizan, sin truncado real).
- [x] Tipos producto/suma con métodos, genéricos + traits monomorfizados.

### 2.2 Pendiente en codegen

- [ ] Constructores vacíos `map[K,V]()` y `set[T]()` (bloquea `borrow.mim`).
- [ ] `drop(x)` / `copy(x)` como llamadas explícitas de sentencia.
- [ ] Argumentos con nombre en llamadas a funciones libres (`f(b: 2, a: 1)`); solo se
      reordenan en constructores de producto.
- [ ] Préstamos que escapan del caso trivial (`&campo`, `&lista[i]` materializando
      dirección) — hoy `&x` no genera código.
- [ ] Truncado/saturación real por ancho (`i8`, `u32`, `f32`, …).
- [ ] `T?` sin tag: un `0` legítimo es indistinguible de `nil` (limitación documentada).

## 3. Métodos de `str` (`docs/DESIGN.md` §10)

Implementados: `.len` (como `len(s)`), `.contains`, `.lower`, `.upper`, `.parse[int|float]`.

- [ ] `.words()` (bloquea `wordcount.mim`).
- [ ] `.lines()`.
- [ ] `.split(sep)`.
- [ ] `.trim()`, `.strip(chars)`.
- [ ] `.starts(prefix)`, `.ends(suffix)`.
- [ ] `.replace(a, b)`.
- [ ] `.join(sep)`.
- [ ] `.bytes()`.

## 4. Métodos de `[T]`

Implementados: `.len`, `.push`, `.pop`, `.get`, `.first`, `.last`, `.sort`,
`.reverse`, `.slice`, `.map`, `.filter`, `.contains`, `.count`, `.top`.

- [ ] `.insert(i, x)`, `.remove(i)`.
- [ ] `.fold(init, f)`.
- [ ] `.any(f)`, `.all(f)`, `.find(f)`.
- [ ] `.sortBy(f)`.
- [ ] `.join(sep)` (listas de `str`).

## 5. Módulos del prelude (fase 7)

Nada implementado; requiere definir el contrato de imports WASM del host (§10 y
`docs/COMPILACION.md`) antes de generar las llamadas.

- [ ] `print`/`eprint` completos y `assert`/`panic` con span.
- [ ] `fs` (`read`, `write`, `exists`, …) — bloquea `wordcount.mim`.
- [ ] `env` (`arg`, `get`, `set`) — bloquea `wordcount.mim`.
- [ ] `io`, `net` (`serve`) — bloquea `http.mim`.
- [ ] `json` (`str`, `parse`) — bloquea `http.mim`.
- [ ] `time`, `rand`, `math`, `os`, `task`.

## 6. Formal y soundness (fase 8)

- [ ] Formalizar CoreMin y las reglas R1-R7 (`docs/FORMAL.md`).
- [ ] Cerrar o documentar los agujeros A1-A9 de `docs/SOUNDNESS.md`; A9 (orden de drops
      en salidas tempranas) sigue sin especificar.
- [ ] Datalog/teoremas de `formal/` y casos Rust de contraste.

## 7. Tests y benchmarks (fase 9)

- [ ] Suite por fase end-to-end con salida esperada (hoy `test_core` cubre 17 casos).
- [ ] `examples/*.mim` al 100 % (2/5 hoy).
- [ ] Benchmarks de tokens (`tools/measure.py`, requiere `tiktoken`).
- [ ] `tools/test_borrow.py` y `tools/test_cases_formal.py` citados en `CLAUDE.md` no
      existen; o se crean o se corrige la doc.

## 8. Detalles finos (fase 10)

- [ ] Formateador canónico idempotente (`minim fmt` es un prototipo de 34 líneas).
- [ ] Indexador `.mimidx` con consultas LLM (fase 1 hecha; faltan `--refs` sobre cuerpos).
- [ ] Optimizaciones BIR (constant folding, dead code) antes del codegen.

## 9. Qué bloquea cada ejemplo (verificado)

| Ejemplo | Falla en | Sección |
|---|---|---|
| `examples/hello.mim` | — (ya compila) | — |
| `examples/shapes.mim` | — (ya compila) | — |
| `examples/borrow.mim` | `map[str, int]()` vacío | §2.2 |
| `examples/http.mim` | `net`/`json` del prelude | §5 |
| `examples/wordcount.mim` | `fs.read`/`env.arg` y `.words()`/`.trim()`/`.strip()` | §3, §5 |

## 10. Orden sugerido

1. `map[...]()`/`set[...]()` vacíos + `.insert/.remove` → `borrow.mim` compila.
2. `str.words/lines/split/trim/strip` → deja `wordcount.mim` a un paso.
3. Contrato host + `fs`/`env` → `wordcount.mim` compila.
4. `net`/`json` → `http.mim` compila.
5. Paridad BIR completa (§1, 6.2-6.4) y conmutar el pipeline.
6. Formal, benchmarks y detalles finos.
