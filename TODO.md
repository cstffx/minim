# TODO — trabajo pendiente (fases 6-10)

Actualizado: 2026-10-23. Solo pendientes; lo completado vive en `status.md`.

## 0. Prioridad: primitivas para construir la std (en lugar de builtins en el codegen)

El compilador debe exponer solo primitivas de bajo nivel; strings, listas y colecciones
deben vivir en una biblioteca estándar compilada con el mismo pipeline.

- [ ] Intrínseco `alloc(n: int) -> ptr` (bump o allocator real).
- [ ] Intrínseco `dealloc(p: ptr)`.
- [ ] Intrínseco `memcpy(dst: ptr, src: ptr, n: int)`.
- [ ] Intrínseco `memset(p: ptr, v: int, n: int)`.
- [ ] Intrínseco `load<T>(p: ptr, off: int) -> T` para T = i8/u8/i16/u16/i32/u32/i64/u64/f32/f64/ptr/bool.
- [ ] Intrínseco `store<T>(p: ptr, off: int, v: T)`.
- [ ] Tipo `ptr` (puntero crudo) en el typechecker y en BIR.
- [ ] Aritmética de punteros: `ptr + int`, `ptr - int`, `ptr - ptr`.
- [ ] Intrínsecos aritméticos por ancho: `add_i8`, `sub_u32`, … (o operadores tipados).
- [ ] Conversiones por ancho: `trunc`, `sext`, `zext`, `ftrunc`, `fext`.
- [ ] Saturación/truncado real en codegen para i8/u32/f32/… .
- [ ] `drop`/`copy` como operaciones primitivas del borrow checker, no del codegen.
- [ ] ABI estable para llamadas a funciones de biblioteca (punteros, retornos, convención).
- [ ] Mover `__str_concat` a `std`.
- [ ] Mover `__str_len` a `std`.
- [ ] Mover `__to_str_i64` a `std`.
- [ ] Mover `__to_str_f64` a `std`.
- [ ] Mover `list.push` a `std`.
- [ ] Mover `list.get` a `std`.
- [ ] Mover `list.slice` a `std`.
- [ ] Mover `list.len` a `std`.
- [ ] Retirar `_ensure_str_helpers` del codegen.
- [ ] Retirar builtins de listas del codegen.

## 1. Fase 6: codegen desde BIR

El pipeline sigue compilando desde el AST elaborado; `minimc build` traduce a BIR solo para
el borrow check y `WasmCodegen` consume el AST. Falta:

- [ ] 6.2 Paridad de tipos compuestos en BIR (pendientes 6.2.2-6.2.8).
      Los stubs de `tools/codegen_bir/` (`layouts`, `aggregates`, `places`, `rvalues`,
      `calls`, `cfg`) ya existen: cada subtarea rellena el suyo y `legacy.py` queda como
      fallback hasta 6.4. Criterio de cierre de 6.2: `hello` y `shapes` dan el
      mismo stdout por `minimc run` y `minimc run --bir`, comparado byte a byte.

  - [ ] 6.2.8 Paridad AST vs BIR (solo `hello`, `shapes`).
        - [ ] Crear `tools/test_bir_parity.py` que compile cada ejemplo por ambas rutas
              y compare stdout byte a byte.
        - [ ] Añadir skips explícitos y listado para lo que siga en 6.3.
        - [ ] Ampliar `tools/test_bir_codegen.py` con casos de `shapes` (tag unaryop,
              match sobre sumas, métodos).
        - [ ] Implementar `unaryop tag` en `codegen_bir` (legacy `_gen_unaryop` o mixin)
              para que `shapes` compile por BIR.
        - [ ] Aceptación: `hello` y `shapes` idénticos byte a byte; sin fallos silenciosos.

- [ ] 6.3 Paridad BIR de `map`/`set`, closures y `T?`/`T!`.
  - [ ] 6.3.1 `map`/`set` aggregate layout en `codegen_bir/aggregates.py`
        (header + buckets, como listas).
  - [ ] 6.3.2 Métodos de `map`/`set` en BIR: `get`, `insert`, `remove`, `len`,
        `contains` (dispatch `Tipo.m`).
  - [ ] 6.3.3 Iteración `for` sobre `map`/`set` en BIR (desazúcar a while).
  - [ ] 6.3.4 Closures en BIR: tabla de funciones + `call_indirect` (o llamada por índice)
        y capturas por préstamo/move.
  - [ ] 6.3.5 `T?`/`T!` en BIR: tag + payload, `is_some`/`is_ok`, `err_msg`, `?`.
  - [ ] 6.3.6 Pruebas de runtime para map/set/closures/option/result en BIR.
- [ ] 6.4 Conmutar el pipeline por defecto a BIR y retirar el codegen desde AST.
  - [ ] 6.4.1 Hacer que `minimc build`/`run` usen BIR por defecto.
  - [ ] 6.4.2 Mantener `--ast` como fallback temporal.
  - [ ] 6.4.3 Eliminar `WasmCodegen` cuando `hello` y `shapes` sean idénticos por ambas rutas.
  - [ ] 6.4.4 Actualizar docs y tests que asumen codegen AST.

## 2. Gaps de codegen (ruta AST actual)

- [ ] `.insert(i, x)` / `.remove(i)` en listas.
  - [ ] Ajustar typecheck para aceptar aridad (§4).
  - [ ] Implementar en codegen AST y BIR.
- [ ] Argumentos con nombre en llamadas a funciones libres (`f(b: 2, a: 1)`).
  - [ ] Reordenar argumentos en `_lower_call`/codegen AST, no solo en ctors.
- [ ] Préstamos que escapan del caso trivial.
  - [ ] `&campo` materializando dirección.
  - [ ] `&lista[i]` materializando dirección.
  - [ ] Codegen para `BorrowExpr` más allá de temporales.
- [ ] Truncado/saturación real por ancho.
  - [ ] `i8`/`u8`/`i16`/`u16` en codegen.
  - [ ] `u32`/`i32` signedness.
  - [ ] `f32` (si se añade) o documentar solo f64.
- [ ] `T?` sin tag.
  - [ ] Documentar limitación o añadir tag en layout.

## 3. Métodos de `str` (`docs/DESIGN.md` §10)

- [ ] `.lines()`.
- [ ] `.split(sep)`.
- [ ] `.strip(chars)`.
- [ ] `.starts(prefix)`, `.ends(suffix)`.
- [ ] `.replace(a, b)`.
- [ ] `.join(sep)`.
- [ ] `.bytes()`.

## 4. Métodos de `[T]`

- [ ] `.insert(i, x)`, `.remove(i)`.
- [ ] `.fold(init, f)`.
- [ ] `.any(f)`, `.all(f)`, `.find(f)`.
- [ ] `.sortBy(f)`.
- [ ] `.join(sep)` (listas de `str`).

## 5. Módulos del prelude (fase 7)

Requiere definir el contrato de imports WASM del host (§10 y `docs/COMPILACION.md`)
antes de generar las llamadas.

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

- [ ] Suite por fase end-to-end con salida esperada.
- [ ] `examples/*.mim` al 100 % por ambas rutas de codegen.
- [ ] Benchmarks de tokens (`tools/measure.py`, requiere `tiktoken`).
- [ ] `tools/test_borrow.py` y `tools/test_cases_formal.py` citados en `CLAUDE.md` no
      existen; o se crean o se corrige la doc.

## 8. Detalles finos (fase 10)

- [ ] Formateador canónico idempotente (`minim fmt` es un prototipo de 34 líneas).
- [ ] Indexador `.mimidx` con consultas LLM (fase 1 hecha; faltan `--refs` sobre cuerpos).
- [ ] Optimizaciones BIR (constant folding, dead code) antes del codegen.

## 9. Qué bloquea cada ejemplo

| Ejemplo | Falla en | Sección |
|---|---|---|
| `examples/shapes.mim` | `tag` unaryop en codegen BIR | §1 (6.2.8) |

## 10. Orden sugerido

1. Implementar `tag` unaryop en codegen BIR → `shapes` compila por BIR.
2. Paridad AST vs BIR para `hello`/`shapes` (§1, 6.2.8).
3. Conmutar pipeline a BIR (§1, 6.4).
4. Primitivas de memoria y `ptr` (§0).
5. Formal, benchmarks y detalles finos.
