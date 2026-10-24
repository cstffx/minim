# TODO — trabajo pendiente (fases 6-10)

Actualizado: 2026-10-23. Solo pendientes; lo completado vive en `status.md`.

## 0. Prioridad: primitivas para construir la std (en lugar de builtins en el codegen)

El compilador debe exponer solo primitivas de bajo nivel; strings, listas y colecciones
deben vivir en una biblioteca estándar compilada con el mismo pipeline.

- [ ] Intrínsecos de memoria: `alloc(n)`, `dealloc(p)`, `memcpy(dst, src, n)`,
      `memset(p, v, n)`, `load<T>(p, off)`, `store<T>(p, off, v)`.
- [ ] Intrínsecos aritméticos/bitwise y conversiones por ancho (i8/u32/f32, …).
- [ ] `drop`/`copy` como operaciones primitivas del borrow checker, no del codegen.
- [ ] ABI estable para llamadas a funciones de biblioteca (punteros, retornos).
- [ ] Mover los helpers de str (`__str_concat`, `__str_len`, `__to_str_*`) a una
      crate `std` compilable, eliminando `_ensure_str_helpers` del codegen.
- [ ] Mover `list.push`/`get`/`slice`/`len` a `std` sobre las primitivas anteriores.
- [ ] Retirar los builtins hardcodeados de `codegen_bir` una vez exista la std.

## 1. Fase 6: codegen desde BIR

El pipeline sigue compilando desde el AST elaborado; `minimc build` traduce a BIR solo para
el borrow check y `WasmCodegen` consume el AST. Falta:

- [ ] 6.2 Paridad de tipos compuestos en BIR (pendientes 6.2.2-6.2.8).
      Los stubs de `tools/codegen_bir/` (`layouts`, `aggregates`, `places`, `rvalues`,
      `calls`, `cfg`) ya existen: cada subtarea rellena el suyo y `legacy.py` queda como
      fallback hasta 6.4. Criterio de cierre de 6.2: `hello`, `shapes` y `borrow` dan el
      mismo stdout por `minimc run` y `minimc run --bir`, comparado byte a byte.

  - [x] 6.2.2 Agregados y memoria lineal. `aggregates.py`: allocator bump-pointer
        compartido (extraído de `tools/codegen/expr/ctors.py`) y
        `Rvalue("aggregate")` para `tuple`, `list`, `struct` y `variant`.
        Desajuste `items=`/`agg_fields` resuelto en la IR de babirusas y en
        `tools/bir.py` (ambos nombres aceptados; `items` es el canónico).
        Aceptación: `(1, 2)` y `P(1, 2)` se crean, se pasan por parámetro y se devuelven
        sin acceder a campos; dos instancias no comparten memoria.

  - [x] 6.2.3 Lectura de places proyectados. `places.py`: `_place_type` y
        `_gen_place_get` para `FIELD`/`INDEX` y proyecciones anidadas (`a.b[i].c`), con
        load i32/i64/f64 según `wasm_repr` y alineación 8.
        Aceptación: `print(t.0)`, `print(p.b)`, `print(xs[1])`, `print(xs[1].a)`.

  - [x] 6.2.4 Escritura de places proyectados. `places.py`: `_gen_place_set` para
        `FIELD`/`INDEX`, anidados y campos de `self` sin cualificar.
        Aceptación: `p.a = 5`, `xs[0] = 7`, `p.inner.x = 1` se leen de vuelta.

  - [x] 6.2.5 Strings dinámicos (puente temporal en codegen; migrar a std). `rvalues.py`: extraer `_ensure_str_helpers`
        (len/concat/eq/cmp) de `expr/legacy.py` a un módulo sin dependencia del AST;
        `_gen_binop` para `str` (`+`, `==`, `!=`, `<`, …); `_storage_wt` devuelve i32.
        Verificar `FStrLit` (hoy se baja como str plano en `ast_to_bir.py:416`) y
        convertirla en concatenación si `core_ir` no lo hace antes.
        Aceptación: concatenar dentro de un bucle, comparar y `print` del resultado;
        `f"{x}"` imprime el valor interpolado.

  - [x] 6.2.6 Match sobre sumas. `unaryop tag` en `_rv_type`/`_gen_unaryop` y bindings
        como lecturas de `FIELD` sobre el payload; completar `_pattern_test` de
        `ast_to_bir.py` para que `named_field` y `tuple` dejen de ser catch-all.
        Aceptación: `case Circle(r): print(r)` usando el binding, patrón anidado y
        guarda.

  - [x] 6.2.7 Llamadas con tipos compuestos (builtins de colecciones temporales; migrar a std). `calls.py`: `Call` a métodos (`Tipo.m`),
        builtins de colecciones (`push`, `get`, `slice`, `len`) y funciones que
        reciben/devuelven punteros, incluyendo `func_index` de métodos monomorfizados.
        Aceptación: `p.move()` muta el receptor, `xs.push(4)`, `print(xs.len)`.

  - [ ] 6.2.8 Paridad AST vs BIR. `tools/test_bir_parity.py`: compila cada
        `examples/*.mim` por ambas rutas y compara stdout byte a byte, con skip explícito
        y listado para lo que siga en 6.3. Ampliar `tools/test_bir_codegen.py` con los
        casos de 6.2.2-6.2.7.
        Aceptación: `hello`, `shapes` y `borrow` idénticos; `http` y `wordcount` fallan
        de forma declarada, nunca en silencio.

- [ ] 6.3 Paridad BIR de `map`/`set`, closures y `T?`/`T!`.
- [ ] 6.4 Conmutar el pipeline por defecto a BIR y retirar el codegen desde AST cuando
      `test_core` + los 5 ejemplos pasen por la ruta BIR (comparación byte a byte del output).

## 2. Gaps de codegen (ruta AST actual)

- [ ] `.insert(i, x)` / `.remove(i)` en listas (typecheck rechaza su aridad; §4).
- [ ] Argumentos con nombre en llamadas a funciones libres (`f(b: 2, a: 1)`); solo se
      reordenan en constructores de producto.
- [ ] Préstamos que escapan del caso trivial (`&campo`, `&lista[i]` materializando
      dirección) — hoy `&x` no genera código.
- [ ] Truncado/saturación real por ancho (`i8`, `u32`, `f32`, …).
- [ ] `T?` sin tag: un `0` legítimo es indistinguible de `nil` (limitación documentada).

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
| `examples/http.mim` | `net`/`json` del prelude | §5 |
| `examples/wordcount.mim` | `fs.read`/`env.arg` y `.strip()` | §3, §5 |

## 10. Orden sugerido

1. `.lines`/`.split`/`.strip` (§3) → deja `wordcount.mim` a un paso.
2. Contrato host + `fs`/`env` → `wordcount.mim` compila.
3. `net`/`json` → `http.mim` compila.
4. `.insert(i, x)`/`.remove(i)` en listas y resto de §4 (paridad de colecciones).
5. Paridad BIR completa (§1, 6.2-6.4) y conmutar el pipeline.
6. Formal, benchmarks y detalles finos.
