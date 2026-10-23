# Plan completo: compilador Minim (AST -> BIR -> borrow check -> codegen -> WASM)

Objetivo: implementar toda la especificacion de Minim 0.1, paso a paso, sin retroceder.

## Fase 0: Infraestructura
- [x] Paquete `minimc` CLI (`run|build|fmt|index|test`).
- [x] Parser + lexer estables (tab-only, continuacion en brackets).
- [x] Formateador canonico (`minim fmt`).
- [x] Indexador (`.mimidx`).

## Fase 1: Nucleo del lenguaje (tipos primitivos y control)
- [x] Tipos: int, float, bool, str, bytes, nil, anchos explicitos.
- [x] Literales: enteros, floats, str, raw, f-string, bytes, multilinea, listas, mapas, sets, tuplas.
- [x] Operadores aritmeticos, comparacion encadenable, logicos, bits, acceso.
- [x] Sentencias: let/var, assign, if/elif/else, while, break/continue, return, expr stmt.
- [x] Expresiones: precedencia, if-expr, match-expr, closures, `it`.
- [x] Funciones: params tipados, retorno inferido, ultima expr = retorno, sin declaraciones adelantadas.
- [x] Modulos: use, fichero = modulo, visibilidad por `_`.

## Fase 2: Tipos compuestos y genericos
- [x] type (producto) con campos y metodos.
- [x] type suma con case (variantes).
- [x] trait y generico acotado `T: Trait`.
- [x] Tipado estructural, copia/move automatico.
- [x] Colecciones: [T], map[K,V], set[T], tuplas, slices.
- [x] Opcionales T?, errores T! y `?`, `or`, `or:` con `it`.
- [x] Conversiones `as`, `str()`, `parse[T]()`.

## Fase 3: Patron matching y concurrencia
- [x] match con patrones, guardas, else.
- [x] spawn/await, task[T] (v0.1 secuencial: spawn eager, await identidad).
- [x] for (rangos, listas, indices, mapas).

## Fase 4: Traduccion AST -> BIR
- [x] Traducir todas las construcciones anteriores a BIR.
- [x] Generar locals/params/blocks/terminators.
- [x] Expresiones a Rvalue, calls a Stmt Call.
- [x] Integrar con babirusas (borrow check).

## Fase 5: Borrow checker completo (NLL)
- [x] Un valor, un dueño; move al asignar/pasar (salvo copiables).
- [x] Préstamos compartidos (`&x`) y únicos (`var x` en firma).
- [x] Modos de parámetro: compartido/unico/move; mutar sin `var` es error.
- [x] Exclusividad: `&mut` exclusivo; `&` permite múltiples lectores.
- [x] Préstamos parciales por campo.
- [x] NLL: préstamo vive hasta último uso del target.
- [x] Drops implícitos al salir de scope (StorageDead).
- [x] Interacción con errores (`?`/`or`), match y closures.
- [x] Diagnósticos con spans exactos.

## Fase 6: Codegen desde BIR -> WASM
- [x] Backend BIR para el subset escalar (`tools/codegen_bir.py`): tipos, locales,
      `Assign`/`Call`, CFG (`Goto`/`SwitchInt`/`Return`), funciones y recursion.
- [ ] Paridad BIR de strings/list/tuple/struct/sumas/match (reutilizar layouts).
- [ ] Paridad BIR de map/set, closures y `T?`/`T!`.
- [ ] Conmutar el pipeline por defecto a BIR y retirar el codegen desde AST.
- [ ] Soporte completo de tipos y operaciones.
- [ ] Manejo de errores y opcionales.

## Fase 7: Prelude y modulos estandar
- [ ] Implementar prelude (print, etc.).
- [ ] Modulos fs, env, io, net, json, time, rand, math, os, task.

## Fase 8: Formal y soundness
- [ ] Validacion formal (CoreMin, Datalog, teoremas).
- [ ] Agujeros conocidos y correcciones.

## Fase 9: Tests y benchmarks
- [ ] Suite de tests por fase.
- [ ] Benchmarks de tokens.
- [ ] Verificacion end-to-end.

## Fase 10: Detalles finos
- [ ] Formato canonico (minim fmt) y reglas de estilo.
- [ ] Indexacion (.mimidx) y consultas LLM.
- [ ] Mensajes de error con spans exactos.
- [ ] Optimizaciones basicas en BIR (constant folding, dead code).

Criterio de exito: `minim run examples/*.mim` funciona para toda la spec, borrow checker rechaza programas inseguros, codegen produce WASM valido.
