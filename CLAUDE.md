# CLAUDE.md

Spec del repo en formato FlatSpec. Léela entera antes de tocar nada.

```text
behavior of "Minim"
  it is "un lenguaje estático (.mim) con memoria sin GC (ownership + borrow, estilo Rust sin
         lifetimes) que compila a WASM"
  it is "spec-first: docs/*.md es normativo, tools/*.py es la implementación de referencia en
         Python, no el compilador de producción"
  it is "optimizado para mínimo coste en tokens BPE por constructo"

behavior of "una sesión que empieza"
  it should "leer status.md (qué está hecho y qué está roto) y TODO.md (siguiente trabajo)"
  it should "leer docs/DESIGN.md para el lenguaje y docs/OWNERSHIP.md + docs/SOUNDNESS.md para el
             borrow checker y sus agujeros conocidos (A1-A9)"
  it should "usar examples/*.mim como corpus de parseo y formal/CASES.md como casos canónicos
             aceptar/rechazar"
  it should "consultar PLAN.md antes de inventar pasos nuevos"

behavior of "el pipeline"
  it should "ir en este orden: lex -> parse -> resolve -> core IR -> typecheck -> BIR+borrow ->
             codegen -> encode"
  it should "mapear cada etapa a: tools/lexer.py, tools/parser.py, tools/resolve.py,
             tools/core_ir.py, tools/typecheck.py, tools/ast_to_bir.py + tools/bir.py +
             babirusas/src/borrowir, tools/codegen/ + tools/codegen_bir/,
             tools/wasm_encoder.py"

behavior of "la CLI"
  it should "compilar con python3 minimc.py build <f.mim> [-o out.wasm] [--bir]"
  it should "ejecutar con python3 minimc.py run <f.mim>"
  it should "validar sin codegen con python3 minimc.py check <f.mim>"

behavior of "los tests"
  it should "invocarse desde la raíz como módulo: python3 -m tools.test_parser, test_borrow,
             test_cases_formal, test_codegen, test_encoder, test_struct, test_bir_codegen,
             test_bir_layouts, test_core, test_ast_to_bir"
  it must not "invocarse como python3 tools/test_X.py: varios importan tools.X y necesitan la raíz
               en sys.path"
  it must "tener en cuenta que los bloques de código de docs/*.md son fixtures ejecutables de
           test_parser.py y deben ser Minim válido"

behavior of "el código .mim"
  it must "indentar solo con tabs; mezclar espacios y tabs es error léxico"
  it must "declarar el modo de params y receptores en la firma (var / move / desnudo) y nunca
           inferirlo del cuerpo"
  it must not "usar pub, mut, lifetimes, overloading, self. obligatorio, ; ni {}"
  it must "mantener un nombre = un símbolo por módulo (sin sobrecarga de funciones ni operadores)"
  it must not "guardar borrows en campos de un type"

behavior of "cualquier cambio de diseño"
  it must "respetar OWTDI: una sola forma canónica por constructo, sin sintaxis alternativa"
  it must "preservar el determinismo: misma fuente + versión -> artefacto byte-idéntico"

behavior of "el flujo de trabajo"
  it should "actualizar status.md al avanzar y ampliar PLAN.md si aparece un paso no previsto"
  it should "commitear lo pendiente antes de empezar trabajo nuevo"
  it must not "hacer commit automáticamente"
  it must "mantener los comentarios de código en dos líneas como máximo"
```
