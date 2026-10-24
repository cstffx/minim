# Refactor de ficheros grandes

Objetivo: trocear los ficheros que ya no caben en una lectura sin perder
comportamiento. Cada corte se valida con la suite existente (`test_codegen` 286 casos,
`test_parser`, `test_core`, `test_struct`, `test_bir_*`) y con `examples/*.mim` por ambas
rutas de codegen.

Prioridad por coste/beneficio. No hay que hacerlos todos ni en este orden, pero sí uno
por commit.

## 1. `tools/codegen/expr/legacy.py` (4027 lineas) — prioridad alta, riesgo bajo

El andamiaje ya existe: `tools/codegen/expr/` tiene los mixins vacios
(`literals`, `operators`, `access`, `ctors`, `collections`, `calls`, `closures`,
`control`) y `ExprMixin` los compone antes de `ExprMixinLegacy`. El refactor es mover
métodos, no rediseñar.

| Destino | Origen (métodos) | Lineas aprox. |
|---|---|---|
| `calls.py` | dispatch de llamadas dentro del bloque `Postfix`: métodos de `str`, `method call`, variantes, constructores de struct y `function call` | 2894-2994, 3436-4027 |
| `access.py` | slices, index (str/bytes/map/list), campo de tupla y `.len` de lista | 2995-3335 |
| `collections.py` | `_gen_set_literal`, `_emit_set_insert`, `_gen_set_remove`, `_gen_map_del`, `_gen_map_collect`, `_gen_list_map`, `_gen_list_method`, `_gen_list_pop`, `_gen_list_optional_at`, `_emit_load_slot`, `_store_elem`, `_elem_wasm`, `list.push` | 734-881, 1269-1728, 1852-2160, 3336-3450 |
| `ctors.py` | `_ctor_begin`, `_ctor_end`, `_zero_value`, `_store_tmp_value`, `_load_tmp_value`, `_is_zero_value` | 1729-1784 |
| `control.py` | `_gen_try`, `_gen_or_block`, `_gen_match_expr`, `_gen_if_expr`, `_gen_lambda`/`MoveExpr` | 925-1000, 1785-1851, 2261-2464 |
| `operators.py` | ramas de `BinOp` y `UnaryOp` de `_gen_expr` | 2700-2893 |
| `literals.py` | ramas de literales de `_gen_expr` (`IntLit`…`NilLit`, `SetExpr`, `ItExpr`, `SelfExpr`, `BorrowExpr`) | 2233-2261 |
| `legacy.py` (queda) | `_ensure_str_helpers`, `_ensure_pow_helper`, `_ensure_str_contains_helper`, `_ensure_str_method_helpers`, `_ensure_parse_helpers`, `_gen_to_str`, `_gen_fstring`, `_type_from_tc`, `_type_is_ptr`, `_operand_is_ptr` | 13-724, 881-975, 1140-1268 |

`_gen_expr` son 1857 lineas y ~1130 son `Postfix`: no se puede mover tal cual. Plan:
extraer primero `field`, `index`, `call` y `slice` a métodos propios
(`_gen_field`, `_gen_index`, `_gen_call_expr`, `_gen_slice`) y dejar `_gen_expr` como
dispatch corto. Ese troceado es lo único manual; el resto es `mv`.

Criterio de cierre: `legacy.py` < 800 lineas, ningún mixin con más de ~400, y
`python3 -m tools.test_codegen` verde sin tocar casos.

## 2. `tools/ast_to_bir.py` (1754 lineas) — prioridad alta, riesgo medio

| Destino | Contenido | Lineas aprox. |
|---|---|---|
| `tools/bir_types.py` | `_prim`, `_ast_type`, `_tc_type`, `to_type`, `_param_mode`, `_bir_copyable`, `_type_label`, constructores (`_local`, `_field`, `_index`, `_use`, `_const`) | 48-205 |
| `tools/bir_translator.py` | `Translator` con scopes, bloques, `lower`/`_lower_value`/`rvalue` | 205-500 |
| `tools/bir_place.py` | `place_of`, `_lower_postfix`, `_lower_call`, `_emit_call`, `_product_ctor`, `_variant_ctor`, `_aggregate_ctor` | 497-760 |
| `tools/bir_expr.py` | lambdas, fallbacks (`or`/`or:`/`?`), lógica cortocircuitada, `lower_into` | 765-1000 |
| `tools/bir_stmt.py` | `translate_suite`, `translate_stmt`, `assign_to_place`, `_eval_discard` | 999-1090 |
| `tools/bir_match.py` | bindings, `_bind_pattern`, `_lower_if`, `_lower_match` | 1092-1754 |

No partir `translate_program` de la fachada pública: los imports actuales
(`from tools.ast_to_bir import translate_program, borrow_check_program, to_type`) deben
seguir funcionando; el paquete reexporta.

## 3. `tools/typecheck.py` (1219 lineas) — prioridad media, riesgo medio-alto

Acoplado a las tuplas de tipo (`("p", ...)`, `("named", ...)`) que consumen los dos
backends. Cortar solo por responsabilidad, sin tocar la representación:

- `tc_types.py`: `_register_structs`, `_register`, `_ftype`, `_atype`, `_sub`,
  `is_copy`, `struct_fields`, `field`, `idx`, `_trait_method`, `trait_satisfied`
  (~186-267, 278-310, 640-808).
- `tc_stmt.py`: `_letdecl`, `_vardecl`, `_bind*`, `suite`, `stmt`, `place`
  (~325-387, 467-624).
- `tc_expr.py`: `expr`, `binop`, `postfix`, `typeslice`, `inst`, `call`, `ctor`,
  `special` (~808-1181).
- `tc_unify.py`: `unify` y helpers de sustitución (~1181-1219).
- `TC` queda como clase que compone los mixins y mantiene `check()`/`check_program()`.

## 4. `tools/parser.py` (1139 lineas) — prioridad baja, riesgo medio

El parser es LL(2) con estado compartido (`peek`/`advance`/`expect`). Partir por
gramática manteniendo `Parser` como clase base:

- `parser_decl.py`: `decl`, `use_decl`, `let_decl`, `var_decl`, `fn_decl`, `params`,
  `tparams`, `type_decl`, `member`, `variant_member`, `field_list`, `trait_decl`,
  `fn_sig` (~110-328).
- `parser_stmt.py`: `stmt`, `let_stmt`…`suite`, `binding`, `pattern` (~71-110, 419-637).
- `parser_expr.py`: `expr` y toda la cascada de precedencia hasta `unary_expr`
  (~637-1139).
- `parser_types.py`: `path`, `place`, `simple`, tipos y literales (~132-139, 328-419).

## 5. `tools/codegen/__init__.py` (451 lineas) — prioridad baja

Es orquestación y estado del `WasmCodegen`; no hace falta trocearlo. Lo único que
sobra es el walker de literales de `generate()`: `walk_str`/`walk_str_stmt`
(~208-361, ~150 lineas) debería ser `tools/codegen/strings_walk.py` con una función
`collect_str_literals(program) -> (offsets, siguiente_offset)`.

## 6. No refactorizar

- `tools/codegen_bir/legacy.py` (570): se vacía solo al implementar 6.2.2-6.2.7 en sus
  mixins (`aggregates`, `places`, `rvalues`, `calls`, `cfg`). Refactorizarlo ahora sería
  trabajo duplicado.
- `tools/codegen/match.py` (486), `tools/codegen/layouts.py` (452),
  `babirusas/src/borrowir/borrow.py` (571): tamaño razonable y muy acoplados;
  trocearlos añade indirección sin ganancia.
- `tools/index.py` (423), `tools/monomorph.py` (386), `tools/lexer.py` (450): aceptables.

## Orden sugerido

1. `expr/legacy.py` → mixins (mecánico, red de tests amplia).
2. `ast_to_bir.py` → submódulos (necesario antes de 6.2.6, que toca el lowering de match).
3. `typecheck.py` y `parser.py` solo si vuelven a molestar.
4. Walker de strings a su módulo cuando se toque `generate()`.

## Verificación

Antes y después de cada corte, desde la raíz:

```text
python3 -m tools.test_parser
python3 -m tools.test_codegen
python3 -m tools.test_struct
python3 -m tools.test_core
python3 -m tools.test_bir_layouts
python3 -m tools.test_bir_codegen
python3 -m tools.test_ast_to_bir
for f in examples/*.mim; do python3 minimc.py check "$f"; done
```

Cada corte es un commit propio, con el recuento de lineas antes/despues en el mensaje.
