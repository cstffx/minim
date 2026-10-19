# Core IR de Minim (estado real)

> Este documento describe lo que **efectivamente implementa** `tools/core_ir.py`
> hoy. Una versión anterior de este archivo describía un IR aspiracional con su
> propia jerarquía de constructores (`Var`, `BinOp`, `Call`, `Borrow`, `Move`,
> `Field`, `Index`, `Struct`, `Place*`, ...) y una tabla de desazúcar completa
> (`match` → `if` anidados, `obj.method(args)` → `method(obj, args)`,
> `v[a:b]` → `slice(...)`, `x += y` → `x = x + y`). **Nada de eso existe en el
> código.** No hay un tipo de nodo "core" separado de la sintaxis de
> superficie: `tools/core_ir.py` reescribe un subárbol muy acotado del AST de
> `tools/nodes.py` *in place* y nada más.

## Lo que `tools/core_ir.py` hace de verdad

El único desazúcar implementado es **`ForStmt` → `WhileStmt`**, vía
`desugar_for_stmt()` y el recorrido `_desugar_suite()` / `elaborate()`:

- `for x in a..b` / `a..=b` (rango): se convierte en
  `let x = a; while x </<= b: { body; x += 1 }`.
- `for x in e` (iterable indexable): se convierte en
  `let _it = e; let _i = 0; while _i < _it.len: { let x = _it[_i]; body; _i += 1 }`.

`elaborate(program)` recorre recursivamente `If`/`While`/`FnDecl`/`TypeDecl`
para desazucarar los `for` anidados en cualquier nivel, y reemplaza los nodos
`ForStmt` del AST por los `WhileStmt` equivalentes. El resultado sigue siendo
un AST de `tools/nodes.py` (no un tipo de dato IR distinto): typecheck, borrow
checker y codegen operan sobre ese mismo AST de superficie, ya sin `ForStmt`.

Nótese que el propio `desugar_for_stmt` genera un `Assign(place, "+=", ...)`
para incrementar el índice — es decir, ni siquiera el desazúcar del `for`
desazucara el `+=` resultante a `x = x + y`.

## Lo que NO está desazucarado (y por qué)

Las siguientes construcciones de superficie se mantienen **tal cual** hasta
el typechecker y el borrow checker; no existe elaboración que las reescriba:

- **`obj.method(args)`** — se mantiene como `Postfix`/llamada a método sobre
  el AST de superficie. El borrow checker (`tools/borrow.py`) necesita el
  sitio de llamada original para inferir el *modo* (`&`, `&mut`, `move`) del
  receptor y de los argumentos; reescribirlo a `method(obj, args)` antes del
  borrow check perdería esa información de modo asociada a la sintaxis de
  llamada.
- **`v[a:b]` (slices)** — por la misma razón: el borrow checker necesita ver
  la indexación/slice en su forma original para calcular regiones y modos de
  préstamo sobre el lugar (`place`) indexado.
- **`match e: case ...`** — no se desazucara a `if`/`else` anidados. Tanto
  `tools/borrow.py` como `tools/typecheck.py` recorren directamente los nodos
  `MatchStmt`/`IfStmt` de superficie; no existe una función que los
  reescriba a un subconjunto reducido antes del análisis.
- **`f"{...}"` (f-strings)** — se mantienen como nodo de superficie;
  tampoco hay elaboración que las convierta en concatenación de `str(...)`.
- **`x += y` y demás asignaciones compuestas** — en `tools/parser.py`
  (`stmt()`, alrededor de la línea 407) se parsean directamente a
  `Assign(place, op, value)` con `op` igual a `"+="`, `"-="`, etc. **No** se
  reescriben a `Assign(place, "=", BinOp(op_sin_igual, place, value))` ni en
  el parser ni en `tools/core_ir.py`. `tools/borrow.py` y `tools/typecheck.py`
  consumen el nodo `Assign` con su operador compuesto directamente (ver los
  `isinstance(stmt, Assign)` en ambos módulos), así que el operador compuesto
  es parte del "core" real, no algo desazucarado.
- **Closures no escapantes** — no hay inlining ni generación de función
  auxiliar; se mantienen como cierres normales.

En resumen: no existe hoy un conjunto "núcleo" de constructores distinto del
AST de superficie, ni un paso de *elaboration* separado que produzca ese
núcleo. Lo único que corre antes del análisis es la eliminación de `for` en
favor de `while`, sobre el mismo tipo de nodos de `tools/nodes.py`.

## Quién consume qué

- El **typechecker** (`tools/typecheck.py`) y el **borrow checker**
  (`tools/borrow.py`) operan directamente sobre el AST de superficie
  (incluyendo `MatchStmt`, llamadas a método, slices y `Assign` con
  operadores compuestos), después de que `core_ir.elaborate()` haya quitado
  los `ForStmt`.
- El **codegen** parte de ese mismo AST post-elaboración de `for`; no hay un
  IR intermedio adicional entre el AST y el codegen.

## Trabajo futuro (aspiracional, no implementado)

Si en algún momento se quiere introducir un IR núcleo real y separado —con
tipos `Place*` dedicados, desazúcar de `match`, de llamadas a método, de
slices y de asignaciones compuestas— habría que:

1. Decidir cómo preservar la información de "modo" (`&`, `&mut`, `move`) que
   hoy el borrow checker obtiene de la sintaxis de llamada a método/slice,
   de forma que sobreviva a la reescritura a `Call`/`Index` genéricos.
2. Definir los constructores núcleo (`Var`, `BinOp`, `Call`, `Borrow`,
   `Move`, `Field`, `Index`, `Struct`, `PlaceVar`, `PlaceField`,
   `PlaceIndex`, ...) como tipos de dato propios, distintos de
   `tools/nodes.py`.
3. Reescribir `tools/borrow.py` y `tools/typecheck.py` para que operen sobre
   ese nuevo tipo de nodos en lugar del AST de superficie.

Ninguno de estos tres pasos existe en el código actual; cualquier mención a
`Place*`, a una tabla de desazúcar completa, o a un "Core IR" como tipo de
dato separado, es trabajo futuro, no una descripción del sistema presente.

## Relación con la gramática

La gramática de `docs/grammar.ebnf` describe la sintaxis de superficie.
`docs/CORE-IR.md` (este archivo) describe únicamente el desazúcar de `for`
implementado en `tools/core_ir.py`. Cualquier nueva característica de
superficie que requiera desazúcar real para el borrow checker debe
documentarse aquí con una referencia concreta a la función que la
implementa, no como una entrada de tabla aspiracional.
