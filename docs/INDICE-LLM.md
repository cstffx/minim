# Minim 0.1 — el índice como servicio para el modelo

`docs/INDEXACION.md` define **qué es** el índice (`.mimidx`) y cómo se construye. Este documento
define **cómo se consulta**: la superficie que un modelo usa para averiguar tipos, firmas y
lugares **sin leer el código fuente**.

No es una herramienta aparte del compilador: es la **fase 1** (`COMPILACION.md` §2), y por eso
está lista y es gratis cada vez que se compila. Pero es una superficie de **consulta**, no un
artefacto que se vuelca.

## 1. Principio: consultar, no volcar

Medido sobre `examples/` (`o200k_base`):

| | tokens |
|---|---|
| fuente de los 5 ficheros | 835 |
| índice de firmas de los 5 (`--api`) | 183 |
| **una** consulta + su respuesta | **2 + 12 = 14** |
| leer un fichero para encontrar esa firma | 150 |

Es decir: **una consulta puntual es 10.7× más barata que leer el fichero**, y el índice completo
es 4.6× más corto que el fuente. Cuanto más pequeña la pregunta, más se gana; y la pregunta la
elige el modelo.

Corolario medido: se responde en **sintaxis Minim**, nunca en un formato inventado. El mismo
programa serializado como AST en JSON costaba **+63 %** de tokens y como bytecode textual
**+57 %**: el vocabulario del tokenizador es un fósil del código humano, y lo que no está en él
se expande.

**La forma importa más que el contenido:**

- una respuesta = una línea por símbolo, en sintaxis Minim,
- **orden estable** (alfabético por nombre, módulos en orden de `use`): así la misma pregunta
  produce el mismo prefijo y el *prompt cache* del proveedor acierta (`INDEXACION.md` §7),
- **respuesta vacía = `none`** (1 token) en el servicio MCP; el CLI no imprime nada y sale con 0.
  Nunca una frase explicando que no hay nada,
- **nunca prosa**: el servidor no resume, no justifica, no comenta. Si algo no cabe, devuelve lo
  más corto y el **span** para pedir más.

## 2. Por qué el índice es fiable, no solo barato

El índice y la **huella de interfaz** son el mismo dato (`COMPILACION.md` §1 y §3): la huella de
un módulo se calcula **solo sobre su bloque de firmas**. De ahí tres propiedades que un
`rustdoc`/`godoc` no tiene:

1. **Correcto por construcción.** Si la huella coincide, el índice es válido. No hay un
   documento paralelo que envejezca.
2. **Invalidación exacta.** Cambiar un **cuerpo** no cambia la huella: el índice sigue siendo
   válido y no hay que recompilar nada. Cambiar una **firma** invalida el índice de quien la usa.
3. **Determinista byte a byte** (`COMPILACION.md` §4), así que se puede versionar: `git diff`
   sobre el índice muestra **cambios de API**, no cambios de implementación.

**Regla de obsolescencia (obligatoria).** Un índice viejo es *peor* que leer el fuente, porque el
modelo no re-verifica. Por tanto el servidor:

```
antes de responder a cualquier consulta sobre el fichero F:
    s = hash(bloque_de_firmas(F))
    si s != huella_del_indice(F):   rescanear F   (escaneo de líneas, O(declaraciones))
    responder siempre desde el índice fresco
nunca responder desde una caché cuya huella no coincide
```

Reescanear cuesta un recorrido de líneas (`INDEXACION.md` §1), no un parseo: es más barato que
mentir.

## 3. Por qué en Minim el índice *basta* (y en Rust no)

En Rust una firma **no** dice el tipo: `impl Trait` en parámetros y en retorno, *lifetimes*
elididos, cotas de `trait` que hay que resolver, `dyn`, sobrecarga de operadores. Un índice de
firmas no es suficiente y hay que volver al fuente.

En Minim, por construcción:

| propiedad | efecto sobre el índice |
|---|---|
| Sin sobrecarga (`COMPILACION.md` §2) | `nombre` → **un** símbolo. Toda consulta es unívoca |
| Sin `impl Trait` | la firma nombra el tipo exacto |
| Sin *lifetimes* (`OWNERSHIP.md` §4) | no hay nada que resolver fuera de la línea |
| Sin inferencia global | el tipo del retorno ya está escrito o es derivable dentro de la declaración |
| Sin `pub` | la visibilidad es un carácter (`_`), no una regla de módulo |
| Sin macros ni decoradores | el texto del fuente **es** el árbol de símbolos |

Conclusión: en Minim **una firma es una afirmación de tipo completa y sin ambigüedad**, y
`nombre → un símbolo`. El índice no es una pista: es la verdad. Esto es un activo de diseño, no
una casualidad, y conviene venderlo como tal.

## 4. Protocolo de consulta

Toda consulta devuelve **texto en sintaxis Minim**. Formato exacto por consulta:

| Consulta | Petición | Respuesta | Coste medido |
|---|---|---|---|
| `sig` | `sig count` | `fn count(path: str) -> map[str, int]!` | 2 + 12 |
| `type` | `type Shape` | una línea por variante/campo/método | 14–30 |
| `find` | `find lower` | `fichero:línea` por uso | 3–10 |
| `doc` | `doc fill` | el `#` de encima, una línea | a demanda |
| `body` | `body count` | el span literal, sin reformatear | = fuente |
| `api` | `api wordcount` | firmas (+ doc con `--docs`), orden estable | 21–100 |
| `errors` | `errors F` | `F:l:col error: mensaje` (una línea por error) | 10–20 |
| `borrow` | `borrow p.a, p.b` | `ok` o `overlap` | 1–2 |
| `diff` | `diff 9f2c41b0` | solo las firmas que cambiaron | 5–30 |

Reglas de forma:

- **`type` ignora los cuerpos**: variantes, campos y métodos con su firma. Es lo que exige el
  estado `TYPE` de `INDEXACION.md` §1.
- **`body` es el único que devuelve código de implementación**, y solo si se pide.
- **`find` es texto**: sin sobrecarga ni alias de `use`, `\bnombre\b` más `.nombre(` basta
  (`INDEXACION.md` §3).
- Un **presupuesto** por respuesta (p. ej. 200 tokens): si se excede, se devuelve la forma corta
  más el span, y el modelo decide si quiere el resto.

## 5. Dos consultas que no existen en ningún otro lenguaje

**(a) `borrow pl1, pl2` — ¿solapan estos dos lugares?**
No es un dato de tipos, es **exclusividad por lugar**: la relación `overlap` de `SOUNDNESS.md`
§10, definida sobre **caminos** (`pl ::= x | pl.f | pl[i]`). `borrow p.a, p.b` → `ok`;
`borrow p.a, p.a[0]` → `overlap`. Ningún índice de Rust, Go o TypeScript responde a esto, y en
Minim sale del **mismo** escaneo, porque el análisis es por camino y no por dueño.

Sirve para lo que más itera un agente: *"¿puedo reestructurar esto en dos préstamos simultáneos?"*
— la pregunta que produce el `swap(p.a, p.b)` de `formal/CASES.md`.

**(b) `diff <huella>` — qué cambió de interfaz.**
Como la huella gatea la recompilación, el índice **sabe exactamente qué firmas cambiaron**:
*"estas 3 cambiaron, el resto no"*. Es el contexto mínimo para mantener código, es 10–100× más
pequeño que un diff de fuentes, y **ya necesitas ese hash** para la caché incremental. Coste
añadido: cero.

## 6. Integración: CLI y MCP

**CLI** (para humanos, scripts y CI): los comandos de `INDEXACION.md` §5.

**MCP** (para agentes): un servidor de **solo lectura** sobre el índice, con una herramienta por
consulta. Nombres explícitos, parámetros mínimos:

```
minim_sig(name)                 minim_type(name)
minim_find(name)                minim_doc(name)
minim_body(name)                minim_api(module)
minim_errors(path)              minim_borrow(place1, place2)
minim_diff(revision)
```

Reglas duras del servidor:

1. **Solo lectura.** No compila, no ejecuta el programa, no escribe en el repo.
2. **Nunca devuelve el índice entero** salvo que se pida un módulo concreto (`api`).
3. **Nunca responde desde un índice obsoleto** (§2). Si la huella no coincide, rescanear.
4. **Salida determinista y ordenada**: misma pregunta, mismos bytes (§1).
5. **Cero prosa.** Si no hay resultado, `none`.

Esto es el canal de distribución del que habla la estrategia del proyecto: el modelo consulta
tipos sin leer el código, y el índice es el mismo dato que la caché incremental necesita.

## 7. Límites honestos

- **Obsolescencia.** Mitigada, no eliminada: depende de recomputar la huella en cada consulta
  (§2). Es obligatorio, no opcional.
- **Cuerpos alucinados.** Con solo firmas, un modelo **inventa** implementaciones. El índice es
  **navegación**, no sustitución: `body` tiene que existir y ser barato.
- **Los bugs viven en los cuerpos.** Los errores de tipo y de préstamos aparecen en el cuerpo,
  así que el índice solo sirve **acompañado** del diagnóstico de una línea
  (`COMPILACION.md` §5). Índice sin errores es medio sistema.
- **El prelude también se indexa** (`list`, `map`, `set`, `str`, `fs`, `env`, `print`): es lo que
  un modelo consulta *más*. Debe ser **estable** entre versiones para poder cachearse.
- **La privacidad es un carácter.** `_` marca privado (`INDEXACION.md` §1), así que `api` puede
  filtrar por visibilidad, pero un agente **dentro del repo** lo ve todo. El índice no es un
  mecanismo de seguridad.

## 8. Construirlo hoy, sin compilador

La regla de `INDEXACION.md` §1 es léxica: **una expresión regular basta; sin estados** (tres
estados, en realidad: `TOP`, `TYPE`, `BODY`). No hace falta parser, ni tipador, ni *borrow
checker*.

`tools/index.py` es el prototipo de **v0** y ya funciona:

```bash
python3 tools/index.py examples/                    # tabla de simbolos
python3 tools/index.py examples/shapes.mim --api    # firmas, orden estable
python3 tools/index.py examples/shapes.mim --type Shape
python3 tools/index.py examples/shapes.mim --sig area
python3 tools/index.py examples/borrow.mim --doc fill
python3 tools/index.py examples/ --find len         # referencias: fichero:linea
python3 tools/index.py examples/ --tokens           # coste medido (necesita tiktoken)
```

| Hito | Necesita | Aporta |
|---|---|---|
| **v0** (hecho: `tools/index.py`) | nada | `sig`, `type`, `find`, `doc`, `body`, `api` |
| v0.1 | el tipador | `errors`: diagnóstico de una línea, ya con spans exactos |
| v0.1 | nada | servidor MCP de solo lectura sobre lo anterior |
| v0.2 | el *borrow checker* | `borrow`: consulta de solapamiento de lugares |
| v0.2 | el build incremental | `diff`: qué cambió de interfaz |
| v0.3 | — | `effects`/`async` si algún día se infieren (`DESIGN.md` P4) |

Presupuesto realista: **~200 líneas** para v0 + MCP. Es el artefacto con mejor relación
valor/esfuerzo del proyecto, y no bloquea nada del resto del diseño.

## 9. Medición

```bash
pip install tiktoken
python3 tools/index.py examples/ --tokens          # indice vs fuente
python3 tools/index.py examples/ --tokens --docs   # con los '#' de encima
```

Resultado sobre `examples/` con `o200k_base`:

| | fuente | índice | delta | ratio |
|---|---|---|---|---|
| total | 835 | **183** | **−78.1 %** | 4.6× |
| + `--docs` | 835 | 243 | −70.9 % | 3.4× |

Por fichero: `borrow.mim` 290 → 60 (−79.3 %), `http.mim` 160 → 55 (−65.6 %), `shapes.mim`
206 → 47 (−77.2 %), `wordcount.mim` 150 → 21 (−86.0 %), `hello.mim` 29 → 0 (sin declaraciones).

Y la regla literal "solo columna 0" da 92 tokens (−89 %) pero **no contiene ni un método ni una
variante**: es la trampa que documenta `INDEXACION.md` §1.

## 10. Relación con el resto del diseño

| Documento | Qué aporta aquí |
|---|---|
| `INDEXACION.md` §1 | la regla léxica (tres estados) que hace posible el índice |
| `INDEXACION.md` §2–3 | formato `.mimidx`, hashes, referencias |
| `COMPILACION.md` §1, §3 | el índice **es** la huella de interfaz: fiabilidad e invalidación exacta |
| `COMPILACION.md` §4 | determinismo: el índice se puede versionar y comparar |
| `COMPILACION.md` §5 | los errores, que son la otra mitad del contexto de un agente |
| `SOUNDNESS.md` §10 | `overlap` por camino: la consulta `borrow` |
| `DESIGN.md` P5 | documento posicional: por qué la doc está pegada al span |
| `TOKENS.md` | por qué se responde en sintaxis Minim y no en un formato nuevo |
