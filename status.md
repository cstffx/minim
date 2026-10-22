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
- `bytes` admite literal, `len()` y `print`; indexado/slice de bytes queda para
  Fase 2. `str.contains` devuelve bool (i64).

### Tests Fase 1
- `python3 tools/test_core.py`: 11 casos de runtime + modulos + privacidad.
- `tools/test_parser.py`, `test_codegen.py`, `test_encoder.py`,
  `test_struct.py` siguen pasando.
- `python3 minimc.py run examples/hello.mim` imprime `hola, Minim`.

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
