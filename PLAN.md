# Plan completo: compilador Minim (AST -> BIR -> borrow check -> codegen -> WASM)

Objetivo: implementar toda la especificacion de Minim 0.1, paso a paso, sin retroceder.

## Fase 0: Infraestructura
- [ ] Paquete `minimc` CLI (`run|build|fmt|index|test`).
- [ ] Parser + lexer estables (tab-only, continuacion en brackets).
- [ ] Formateador canonico (`minim fmt`).
- [ ] Indexador (`.mimidx`).

## Fase 1: Nucleo del lenguaje (tipos primitivos y control)
- [ ] Tipos: int, float, bool, str, bytes, nil, anchos explicitos.
- [ ] Literales: enteros, floats, str, raw, f-string, bytes, multilinea, listas, mapas, sets, tuplas.
- [ ] Operadores aritmeticos, comparacion encadenable, logicos, bits, acceso.
- [ ] Sentencias: let/var, assign, if/elif/else, while, break/continue, return, expr stmt.
- [ ] Expresiones: precedencia, if-expr, match-expr, closures, `it`.
- [ ] Funciones: params tipados, retorno inferido, ultima expr = retorno, sin declaraciones adelantadas.
- [ ] Modulos: use, fichero = modulo, visibilidad por `_`.

## Fase 2: Tipos compuestos y genericos
- [ ] type (producto) con campos y metodos.
- [ ] type suma con case (variantes).
- [ ] trait y generico acotado `T: Trait`.
- [ ] Tipado estructural, copia/move automatico.
- [ ] Colecciones: [T], map[K,V], set[T], tuplas, slices.
- [ ] Opcionales T?, errores T! y `?`, `or`, `or:` con `it`.
- [ ] Conversiones `as`, `str()`, `parse[T]()`.

## Fase 3: Patron matching y concurrencia
- [ ] match con patrones, guardas, else.
- [ ] spawn/await, task[T].
- [ ] for (rangos, listas, indices, mapas).

## Fase 4: Traduccion AST -> BIR
- [ ] Traducir todas las construcciones anteriores a BIR.
- [ ] Generar locals/params/blocks/terminators.
- [ ] Expresiones a Rvalue, calls a Stmt Call.
- [ ] Integrar con babirusas (borrow check).

## Fase 5: Borrow checker completo (NLL)
- [ ] Un valor, un dueño; move al asignar/pasar (salvo copiables).
- [ ] Préstamos compartidos (`&x`) y únicos (`var x` en firma).
- [ ] Modos de parámetro: compartido/unico/move; mutar sin `var` es error.
- [ ] Exclusividad: `&mut` exclusivo; `&` permite múltiples lectores.
- [ ] Préstamos parciales por campo.
- [ ] NLL: préstamo vive hasta último uso del target.
- [ ] Drops implícitos al salir de scope (StorageDead).
- [ ] Interacción con errores (`?`/`or`), match y closures.
- [ ] Diagnósticos con spans exactos.

## Fase 6: Codegen desde BIR -> WASM
- [ ] Refactor WasmCodegen para consumir BIR.
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
