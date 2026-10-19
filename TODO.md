# TODO — gaps entre la spec (docs/) y el codegen WASM (tools/codegen_wasm.py)

Generado tras hacer que `tools/codegen_wasm.py` falle explícitamente (`CodegenError`) en vez
de emitir `i64_const(0)` silencioso para lo que no soporta (ver commit "codegen: fail
explicitly..."). Esto es una lista de **codegen**, no del lenguaje: el lexer/parser/typecheck/
borrow checker ya aceptan casi toda esta superficie (`tools/test_parser.py` parsea todos los
`.mim` y los bloques de código embebidos en `docs/`). El gap está específicamente en
`WasmCodegen._gen_stmt` / `_gen_expr`.

Estado real hoy: de `examples/*.mim`, **solo `hello.mim` genera código completo**. Los otros
cuatro fallan en el primer construct no soportado que tocan (ver tabla al final).

## 1. Sentencias no implementadas (`_gen_stmt`)

- [ ] `match` como sentencia (`MatchStmt`, `docs/DESIGN.md` §6) — bloquea `examples/shapes.mim`.
      Necesita: discriminación de variante (tag en el layout de struct), bindings de campos por
      posición/nombre, guardas (`if` dentro de `case`), `else` como comodín.
- [ ] `spawn` / `await` como sentencias (`SpawnStmt`, `AwaitStmt`, `docs/DESIGN.md` §9) —
      depende de un runtime de tareas que no existe (ver §5).
- [ ] `break` / `continue` (`BreakStmt`, `ContinueStmt`, `docs/DESIGN.md` §4) — el `WhileStmt`
      actual no deja bloques de salida nombrados accesibles para un `br`/`br_if` dirigido.
- [ ] Bloque `or:` como sentencia (`OrBlock` ligado a `it`, `docs/DESIGN.md` §8) — `let c =
      load(path) or: ...`. Depende de que `T!` (valor-o-error) tenga una representación en
      memoria (ver §4).
- [ ] `drop(x)` / `copy(x)` como llamadas de sentencia explícitas (`docs/DESIGN.md` prelude §10)
      — el borrow checker ya las reconoce (`tools/borrow.py`), el codegen no.

## 2. Expresiones no implementadas (`_gen_expr`)

- [ ] **F-strings** (`FStrLit`, `docs/DESIGN.md` §5) — interpolación `f"{k:6} {w}"`. Bloquea
      `wordcount.mim`. Depende de concatenación/formateo de strings (ver §3).
- [ ] **Tuplas** (`TupleExpr`, `docs/DESIGN.md` §5/§7) — `let a, b = pair`, `(1, "a")`.
- [ ] **Mapas** (`MapExpr` + tipo `map[K,V]`, `docs/DESIGN.md` §7) — literal `{"k": 1}`, índice
      `m[k]`, y todo `.get/.has/.del/.keys/.values/.items/.top` del prelude. Bloquea
      `wordcount.mim` y `borrow.mim`. Es la pieza más grande: no existe ninguna estructura
      clave-valor en el runtime de memoria lineal hoy (solo `list`, ver layout en
      `WasmCodegen._gen_expr` rama `ListExpr`). Requiere diseñar un layout de hash table desde
      cero (buckets, hashing de `str`/`int`, resize).
- [ ] **Sets** (`set[T]`, `docs/DESIGN.md` §7) — ningún método de prelude de `set` implementado.
- [ ] **Closures** (`Lambda`, `MoveExpr` sobre lambda, `it` implícito vía `ItExpr`,
      `docs/DESIGN.md` §5) — `fn x => x*2`, `move fn x => x+1`, `xs.map(it*2)`. Necesita decidir
      representación de función+entorno capturado en WASM (no hay vtables ni punteros a función
      de primera clase todavía en el encoder).
- [ ] **`if`/`match` en posición de expresión** (`IfExpr`, `MatchExpr`, `docs/DESIGN.md` §5) —
      `if c: a else: b` y `match v: case A(x): 1 else: 0` como valor, no solo como sentencia.
- [ ] **Operadores lógicos y de comparación encadenada** (`docs/DESIGN.md` §5): `and`, `or`,
      `not`, comparaciones encadenadas `a < b < c`, `in`/`is`/`is not`, `as` (conversión).
      `BinOp` hoy solo cubre `+ - * / % <= >= < > == !=` aritméticos/comparación simple.
- [ ] **Slicing** (`s[1:4]`, `s[:4]`, `s[2:]`, `docs/DESIGN.md` §5) — el índice simple de lista
      sí existe (`_gen_expr` rama `Postfix` / `index`), el slice no.
- [ ] **Préstamos como valor en runtime** (`BorrowExpr`, `docs/OWNERSHIP.md`) — hoy `&v` no
      genera ningún código especial; funciona por construcción porque WASM no tiene punteros
      reales a locales, pero para campos/listas probablemente haga falta materializar una
      dirección cuando el préstamo escapa del caso trivial.
- [ ] **Argumentos con nombre en llamadas a funciones libres** (`docs/DESIGN.md` §5) —
      `f(b: 2, a: 1)`. El reordenamiento por nombre solo está implementado para constructores de
      struct (`_gen_expr` rama "constructor call for struct types"), no para `FnDecl` genéricas.
- [ ] **Propagación de errores `?`** y el tipo `T!` (`docs/DESIGN.md` §8) — no hay representación
      en memoria para "valor o error", por lo que `?`, `or`, `or:` no tienen nada que propagar.
      Bloquea `http.mim` (usa `err(...)`).
- [ ] **Tipo `err` del prelude** (`err(msg, code)`, `docs/DESIGN.md` §8) — bloquea `http.mim`
      directamente (`llamada a funcion desconocida 'err'`).
- [ ] **Anchos explícitos de entero/float** (`i8 i16 i32 u8 u16 u32 u64 f32 f64`,
      `docs/DESIGN.md` §7) — todo se trata como `i64`/`f64`; no hay truncamiento/extensión por
      ancho.
- [ ] **`bytes`** (`docs/DESIGN.md` §1.5/§7) — tipo y literales sin representación en codegen.

## 3. Métodos de prelude sobre `str` (`docs/DESIGN.md` §10)

Falta todo excepto nada (ni siquiera `.len` de `str` está confirmado en codegen — solo `.len`
de `list`, ver `_gen_expr` rama `Postfix`/`field`). Spec exige: `.len .words .lines .split .trim
.lower .upper .strip .contains .starts .ends .parse[T]() .replace .join .bytes`.
Requiere decidir el layout de `str` en memoria lineal (longitud + puntero a bytes UTF-8, o
null-terminated) — hoy los `StrLit` solo emiten un puntero a datos estáticos (`_gen_expr` rama
`StrLit`), sin operaciones sobre ese buffer.

## 4. Métodos de prelude sobre `[T]` sin implementar

Implementados: `.len`, `.push` (ver `_gen_expr`, rama "list push method"). Lista completa de
`docs/DESIGN.md` §10: `.get .insert .remove .sort .sortBy .map .filter .fold .any .all .find
.first .last .reverse .slice .contains .join .top .count` — todo pendiente.

## 5. Módulos del prelude (I/O de host)

Nada implementado. `docs/DESIGN.md` §10 exige `fs`, `env`, `io`, `net`, `json`, `time`, `rand`,
`math`, `os`, `task`. Bloquea `wordcount.mim` (`fs.read`, `env.arg`). A diferencia de todo lo
anterior, esto no es solo "escribir más codegen": requiere **diseñar el contrato de runtime
host** (qué imports WASM expone el entorno de ejecución, análogo a los `env.print`/
`env.print_str` que ya existen en `WasmCodegen.__init__`) antes de poder generar las llamadas.
`docs/COMPILACION.md` tampoco especifica este contrato todavía — es una decisión de diseño
pendiente, no solo una implementación pendiente.

## 6. Genéricos y traits

`docs/DESIGN.md` §7 pide monomorfización memoizada de `[T]`/`map[K,V]` acotada por `trait`.
Ninguna instancia genérica real se monomorfiza hoy: el codegen asume list/struct concretos
resueltos por `tc._atype`. Pendiente de diseño, no solo de implementación — depende de que exista
primero un `map` real (§2) sobre el que monomorfizar algo.

## 7. Nota sobre el backend objetivo

`docs/COMPILACION.md` §6 especifica el backend v0.1 como un **intérprete de bytecode de pila**
(`.mimo`), con Cranelift (v0.2) y LLVM (v0.3) como pasos posteriores — **WASM no aparece en esa
tabla**. `tools/codegen_wasm.py` es, a juzgar por su alcance actual, un backend experimental/
alternativo, no el backend normativo de v0.1. Vale la pena decidir explícitamente si WASM es un
objetivo de primera clase (y documentarlo en `docs/COMPILACION.md`) o si el esfuerzo de cerrar
esta lista debería ir al intérprete de `.mimo` en su lugar, que no existe todavía en `tools/`.

## Resumen: qué bloquea cada ejemplo hoy

| Ejemplo | Falla en | Sección de este TODO |
|---|---|---|
| `examples/hello.mim` | — (ya compila) | — |
| `examples/shapes.mim` | `MatchStmt` | §1 |
| `examples/http.mim` | builtin `err(...)` | §2 (`err`), §2 (`T!`/`?`) |
| `examples/borrow.mim` | map / string methods | §2 (map), §3 |
| `examples/wordcount.mim` | map, string methods, `fs`/`env` | §2 (map), §3, §5 |

## Sugerencia de orden (de más tractable a más grande)

1. `err(...)` builtin + representación mínima de `T!` → desbloquea `http.mim`.
2. `match` como sentencia → desbloquea `shapes.mim`.
3. Métodos de prelude de `str` básicos (`.len`, `.lower`, `.strip`, `.words`) → acerca
   `wordcount.mim`.
4. `map[K,V]` (hash table en memoria lineal) → la pieza más grande; desbloquea `borrow.mim` y
   (junto con §5) `wordcount.mim`.
5. Contrato de runtime host (`fs`, `env`) → último paso para `wordcount.mim`.
6. Todo lo demás (closures, generics, slicing, lógicos encadenados, anchos explícitos) según
   demanda real de los ejemplos/tests, no por completitud abstracta.
