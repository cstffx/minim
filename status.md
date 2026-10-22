# Estado de implementación

Actualizado automáticamente por los agentes (ver CLAUDE.md).

## Fase 0: Infraestructura
- [x] Parser/lexer base.
- [ ] Paquete `minimc` CLI.
- [ ] Formateador canonico.
- [ ] Indexador `.mimidx`.

## Fase 1: Nucleo
- [x] Parser + typecheck + codegen WASM (subset int).
- [ ] Tipos compuestos, genericos, colecciones.
- [ ] match, for, closures, `it`.

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
