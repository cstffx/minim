# Plan: AST -> BIR -> Borrow Check -> Codegen -> WASM

## Fase 1: Traductor AST -> BIR (parcial)
- Soportar FnDecl, params, locals.
- Statements: Let/Var, Assign, Return, ExprStmt (call).
- Expresiones: lit, name, binop, unaryop, postfix call (básico).
- If/While/For/Match pendientes.

## Fase 2: Integración borrow checker
- Convertir Function BIR y ejecutar babirusas.
- Reportar errores con spans.

## Fase 3: Codegen desde BIR
- Refactor WasmCodegen para consumir BIR en lugar de AST.
- Mantener subset int.

## Fase 4: Tests y validación
- Tests por fase.
- Comparar salida con implementación anterior.
