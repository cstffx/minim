# Estado de implementación

Actualizado automáticamente por los agentes (ver CLAUDE.md).

## Fase 0: Infraestructura
- [x] Parser/lexer base.
- [x] Paquete `minimc` CLI (build/check/run/fmt/index/test).
- [x] Formateador canonico (prototipo).
- [x] Indexador `.mimidx` (tools/index.py: scan, params/ret, spans, hashes, calls, --json/--write/--refs/--changed).

## Fase 1: Nucleo del lenguaje (completada)
- [x] Tipos: int, float, bool, str, bytes, nil. Anchos explicitos (`i8..u64`,
      `f32/f64`) se normalizan a `int`/`float` (sin truncado todavia).
- [x] Literales: enteros (dec/hex/bin/oct, `_`), floats, str con escapes, raw,
      f-string (int/float/expresiones, precision `.Nf`), bytes, multilinea,
      listas, mapas, sets y tuplas.
- [x] Operadores: `+ - * / // % **`, comparacion encadenable, `and/or/not`,
      bits (`& | ^ ~ << >>`), `in`, `is`, conversion `as`, acceso `. []`.
- [x] Sentencias: let/var, assign y compuestos, if/elif/else, while,
      break/continue, return, expr stmt.
- [x] Expresiones: precedencia, if-expr (`if c: a else: b`), match-expr,
      closures (`fn x => ...`, `move fn`, captura), `it`.
- [x] Funciones: params tipados, retorno inferido, ultima expresion = retorno,
      recursion, sin declaraciones adelantadas.
- [x] Modulos: `use a, b.c` (fichero = modulo), `std/` y luego directorio del
      proyecto, alias = ultimo segmento, nombres `_` privados.
- [x] `minimc run` ejecuta con `print_str(ptr)` terminado en NUL.

### Simplificaciones Fase 1 (documentadas)
- No hay truncado/saturacion para `i8..u64`/`f32`: todos usan i64/f64.
- `{}` sigue siendo mapa vacio; no hay literal de set vacio (usar `set[T]()`).
- Tipos de modulo (`util.Point`) no existen en gramatica: los `type` de los
  modulos se fusionan con nombre global.
- Dos modulos importados con el mismo alias producen error.
- `bytes` admite literal, `len()`, `print`, indexado (`b[i]` devuelve int) y
  slice (`b[a:b]` devuelve bytes); `str[i]` devuelve una cadena de un caracter.
  `str.contains` devuelve bool (i64).

### Tests Fase 1
- `python3 -m tools.test_core`: 16 casos de runtime + modulos + privacidad.
- `tools/test_parser.py`, `test_codegen.py`, `test_encoder.py`,
  `test_struct.py` siguen pasando.
- `python3 minimc.py run examples/hello.mim` compila y ejecuta.

## Fase 2: Tipos compuestos y genericos (completada)
- [x] `type` producto con campos y metodos (`self`, retorno por ultima expresion).
- [x] `type` suma con `case`, construccion `Type.Variant(...)` y `match` con
      bindings posicionales/nombrados.
- [x] `trait` + genericos acotados `T: Trait`; despacho estatico y
      monomorfizacion memoizada en `tools/monomorph.py`.
- [x] Tipado estructural entre productos con los mismos campos (mismo orden y
      tipos); clasificador de copiabilidad `TC.is_copy`.
- [x] Colecciones: listas (`push`, `pop`, `get`, `first`, `last`, `sort`,
      `reverse`, `slice`, `map`, `filter`, `len`), mapas (`get`, `del`,
      `keys`, `values`, `items`, `has`, `len`), sets (`add`, `remove`,
      `contains`, `len`), tuplas y slices de listas/str/bytes.
- [x] Opcionales `T?`, errores `T!`, propagacion `?`, `or` y bloques `or:`
      con `it` (mensaje de error); `or: continue/break` en bucles.
- [x] Conversiones `as` (int/float/bool/str), `str(x)` y `parse[int|float]()`.

### Simplificaciones Fase 2 (documentadas)
- `?`/errores se representan con globales (`err_flag`, `err_msg`, `err_code`),
  no con un tipo suma en runtime. `it` dentro de `or:` para `T!` es el mensaje
  (`str`). En `T?`, `nil` es el valor cero del tipo (0 / 0.0); no hay tag
  separado, asi que un 0 legitimo es indistinguible de `nil`.
- Los genericos se especializan en el AST con nombres `f$<tipos>`; las
  especializaciones no se exportan y los traits se resuelven estaticamente.
- El tipado estructural solo aplica a productos (`type` con campos); las sumas
  son nominales. La compatibilidad exige el mismo orden de campos.
- `TC.is_copy` clasifica copiables (primitivos, `str`, `bytes`, tuplas/productos
  de copiables) frente a movibles (listas, mapas, sets, tareas). El diagnostico
  de uso tras move queda para el borrow checker (Fase 5); el codegen actual no
  libera memoria.
- Listas/sets/mapas usan busqueda lineal y `sort` es burbuja; los slices copian.
  Los mapas permiten claves/valores i64 o f64 y crecen al insertar.
- `parse[T]()` soporta `int` y `float`; el resto de tipos devuelve error.

### Tests Fase 2
- `python3 -m tools.test_core`: 5 casos nuevos (producto/suma con metodos,
  genericos/trait, colecciones, opcionales/errores, conversiones) ademas de
  los 11 de Fase 1.
- `python3 -m tools.test_parser`, `test_codegen`, `test_encoder` y
  `test_struct`: pasan.
- `examples/shapes.mim` compila y produce el total esperado; `examples/hello.mim`
  compila.

## Fase 4: AST -> BIR
- [ ] En progreso: `tools/ast_to_bir.py` (subset).

## Fase 5: Borrow checker
- [x] `babirusas` implementado (IR + borrow checker basico, 3 tests).
- [ ] NLL completo y spans.

## Fase 6: Codegen desde BIR
- [ ] Pendiente.

## Notas
- Borrow checker canonico: `babirusas/src/borrowir`.
- Compilador legacy usa AST directamente hasta completar Fase 4.
