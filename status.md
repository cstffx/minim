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

## Fase 3: Patron matching y concurrencia (completada)
- [x] `match` con patrones, guardas (`case x if cond:`) y `else`; sentencia y
      expresion.
- [x] `spawn`/`await` y `task[T]`: en v0.1 `spawn` evalua de forma secuencial y
      `await` es la identidad; `task[T]` se representa como `T` (sin hilo ni
      scheduler, WASM MVP sin threads).
- [x] `for`: rangos (`a..b`, `a..=b`), listas, indices (`for i, x in xs`), mapas
      (`for k in m` recorre claves, `for k, v in m` recorre pares) y `continue`
      ejecutando el incremento. Los mapas se desazucaran con el tipo estatico del
      iterable (core IR tras typecheck: `.keys()` / `.items()`).

### Simplificaciones Fase 3 (documentadas)
- `spawn` no crea concurrencia real: el cuerpo se evalua en el punto de
  `spawn` y `await` devuelve el valor ya calculado. La representacion de un
  `task[T]` es la del propio `T`.
- `for` sobre mapas copia claves/items a una lista auxiliar, igual que
  `keys()`/`items()`.
- `for k, v in lista` sigue la semantica indice + elemento (primer binding
  `int`); no desestructura tuplas. Para pares de un mapa usar el mapa.

### Tests Fase 3
- `python3 -m tools.test_core`: 3 casos nuevos (for sobre rangos/listas/
  indices/mapas con continue; match con guardas y else; spawn/await/task).
- `minimc run` usa ahora la memoria exportada por el modulo (imprime `str`
  correctamente) y compila tras ejecutar typecheck y desazucar el core IR.


## Fase 4: AST -> BIR (completada)
- [x] `tools/ast_to_bir.py`: traduce todo el AST soportado hoy (el que produce
      `tools/core_ir.py`, con `for` ya desazucarado) a BIR de
      `babirusas/src/borrowir/ir.py`.
- [x] Locals/params/blocks/terminators: un `Local` por binding, temporales para
      valores intermedios, `StorageLive`/`StorageDead` por scope, bloques con
      `Goto`/`SwitchInt`/`Return` y orden DFS/RPO desde la entrada.
- [x] Expresiones a `Rvalue` (`Use`, `BinOp`, `UnOp`, `Aggregate`, `Cast`,
      `Const`, `Call`) y llamadas a `Stmt("Call")` con `call_func`,
      `call_args`, `call_dest` y `call_target`.
- [x] Cobertura: `let`/`var` (binding simple y destructuring), asignacion y
      compuestas, `if`/`elif`/`else`, `while`, `match` (sentencia y expresion),
      `return`, `break`/`continue`, `spawn`/`await`; literales, nombres, binop,
      unario, llamadas (incluidas metodos `Type.metodo`/`list.push`/...),
      campo/indice, listas/mapas/sets/tuplas, constructores producto/suma,
      `if`/`match` como expresion, closures e `it` (elevadas a
      `<owner>$lambdaN` con capturas como parametros), `or`/`?`.
- [x] Integracion con babirusas: `translate_program`/`translate_module`/
      `translate_function`, `borrow_check_function`/`borrow_check_translated`/
      `borrow_check_program` y CLI
      `python3 -m tools.ast_to_bir <file.mim> [--dump]`.
- [x] Sin cambios en el pipeline: `minimc.py` sigue compilando desde AST (el
      codegen desde BIR es Fase 6).

### Decisiones Fase 4 (documentadas)
- Sin globals en BIR: las sentencias de nivel superior se agrupan en `main`
  (o `__top` si ya existe `main`).
- Asignaciones de tipos copiables usan `Rvalue("cast", ...)` para que el borrow
  checker basico no las trate como moves; listas/mapas/sets si son moves.
- Tests de variante de suma como `binop("==", unaryop("tag", tmp), const_int(i))`;
  los bindings de `match` usan `cast` para evitar falsos moves parciales.
- Bloques reordenados por DFS/RPO desde la entrada para que el recorrido lineal
  del borrow checker se aproxime al orden de ejecucion (necesario para
  `wordcount.mim`).
- `self` se resuelve fijando `tc.cur_type = owner` al tipar metodos.

### Tests Fase 4
- `python3 -m tools.test_ast_to_bir`: 9 casos (aritmetica, if/else,
  while+break/continue, llamada con retorno, struct/suma+match,
  list/map/set/tuple, closures/`it`, `or`/`?`, integracion con borrow checker
  y caso negativo de move).
- Los 19 casos de `python3 -m tools.test_core` traducen y pasan el borrow
  check; todos los `examples/*.mim` (incluido `wordcount.mim`) tambien.
- `python3 -m tools.test_core`, `test_parser`, `test_codegen`, `test_encoder`,
  `test_struct`, `minimc.py check examples/hello.mim` y
  `examples/shapes.mim`: pasan.

## Fase 5: Borrow checker
- [x] `babirusas` implementado (IR + borrow checker basico, 3 tests).
- [ ] NLL completo y spans.

## Fase 6: Codegen desde BIR
- [ ] Pendiente.

## Notas
- Borrow checker canonico: `babirusas/src/borrowir`.
- `minimc.py` sigue compilando desde AST; el codegen desde BIR llega en Fase 6.
