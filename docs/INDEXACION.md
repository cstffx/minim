# Minim 0.1 — indexación

La indexación no es una herramienta aparte: es la **fase 1 del compilador**
(`docs/COMPILACION.md` §2), y por eso compilar siempre deja el índice listo y gratis.

## 1. El ancla: palabra clave en columna 0

Toda declaración empieza en columna 0 con una palabra clave, y su firma cabe en **una línea**:

```python
use fs, env

# cuenta palabras de un fichero y muestra las 10 mas frecuentes
fn count(path: str) -> map[str, int]!
	...

fn main()
	...
```

Un índice se construye con una regla léxica, sin parser: un autómata de **tres estados**.

```
estado TOP
  ^(use|let|var|fn|type|trait)\b      -> declara; si es `type`/`trait`, pasa a TYPE

estado TYPE                           (una sola sangría por debajo del ancla del tipo)
  ^\t(fn|case)\b                      -> declara miembro; si es `fn`, pasa a BODY
  ^\t\t?NOMBRE (:|=)                  -> declara campo
  al volver a columna 0               -> vuelve a TOP

estado BODY                           (cuerpo de un método)
  toda línea con sangría mayor que la del `fn`  -> se ignora
```

**Por qué TYPE es obligatorio** (medido sobre `examples/`, `o200k_base`): la regla literal de
"solo columna 0" produce **92 tokens** frente a los **835** del fuente, pero **no contiene ni un
método ni una variante** — justo lo que un modelo consulta. Con ella, el índice de `shapes.mim`
se queda en `type Shape`, `fn total`, `fn main`: no aparecen `fn area` ni `case Circle`.
Descendiendo un nivel son **183 tokens (−78 %)** y está completo.

**Y BODY es igual de importante**: sin él, los brazos de un `match` (que también empiezan por
`case`, más indentados) entran en el índice como si fueran variantes del tipo.

Propiedades que hacen trivial el índice:

| Propiedad | Efecto |
|---|---|
| Declaración empieza en columna 0 | Un autómata de tres estados basta; sin parser |
| Miembros de un `type` a sangría fija | El estado `TYPE` los encuentra por debajo del ancla, y `BODY` los excluye |
| Firma en una línea | El símbolo completo está en una línea, no en 8 |
| Sin sobrecarga | `nombre` identifica **un** símbolo: no hay desambiguación por tipos |
| Sin `pub` | Público por defecto; privado = prefijo `_` |
| Documento posicional (`#` encima) | La doc viene pegada al span, sin buscar bloques |
| Sin macros ni decoradores | El texto del fuente == el árbol de símbolos |
| Formato canónico | El índice es idéntico en dos máquinas y estable en el tiempo |

## 2. Salida: `.mimidx`

```json
{
  "format": 1,
  "module": "wordcount",
  "path": "src/wordcount.mim",
  "hash": "9f2c41b0",
  "uses": ["fs", "env"],
  "decls": [
    {
      "kind": "fn",
      "name": "count",
      "public": true,
      "sig": "fn count(path: str) -> map[str, int]!",
      "doc": "cuenta palabras de un fichero y muestra las 10 mas frecuentes",
      "line": 4,
      "span": [4, 9],
      "params": [{ "name": "path", "type": "str", "mode": "borrow" }],
      "ret": "map[str, int]!",
      "hash": "b71c9ae2",
      "calls": ["fs.read", "map", "line.words", "lower", "strip"]
    },
    {
      "kind": "fn",
      "name": "main",
      "public": true,
      "sig": "fn main()",
      "line": 11,
      "span": [11, 17],
      "hash": "0d4f11aa",
      "calls": ["env.arg", "count", "eprint", "print"]
    }
  ]
}
```

- `sig` es la línea literal del fuente: sirve de clave estable de declaración.
- `mode` es `borrow`, `unique` o `move` según el modo de parámetro (`var` / `move`).
- `hash` es el hash del **cuerpo** de esa declaración, independiente del resto del fichero.
- `hash` del módulo es el de su bloque de firmas (interfaz), no el del fichero entero.
- `members` (solo en `kind: "type"` / `"trait"`) es la lista de variantes, campos y métodos con
  su línea: es lo que exige el estado TYPE de §1. La `sig` de un método es su línea literal,
  igual que la de una función suelta; un `case` lleva sus campos, no su cuerpo.

## 3. Referencias

Sin sobrecarga ni `use` con alias, encontrar los usos de un símbolo es buscar su nombre en
texto: `\bnombre\b` más `\.nombre\(`. `minim index --refs` produce un índice invertido:

```json
{ "count": ["src/wordcount.mim:12"], "fs.read": ["src/wordcount.mim:6"] }
```

Esto es suficiente para "ir a la definición", "buscar referencias" y renombrar sin ambigüedad,
y no requiere resolver tipos ni plantillas.

## 4. Chunking para RAG / contexto de un LLM

Regla: **un chunk = una declaración** (sus `#` + su firma + su cuerpo + su span).

- Los límites del chunk son exactamente los límites que el compilador ya conoce: no hay que
  inventar heurísticas de ventana ni solapar trozos.
- `hash` por declaración permite invalidar porciones: si cambias un cuerpo, solo ese chunk
  cambia, y una caché de prompts sigue siendo válida para los demás.
- La representación en texto del chunk es el fuente tal cual (canónico): sin preámbulos, sin
  resúmenes generados, sin metadatos que gasten tokens.

### Presupuesto mínimo de contexto

`minim api M` imprime solo firma + doc, en orden estable, para meter un módulo entero en
el contexto sin cuerpos:

```python
# src/wordcount.mim
use fs, env
fn count(path: str) -> map[str, int]!   # cuenta palabras de un fichero...
fn main()
```

Medido sobre `examples/` con `o200k_base` (`python3 tools/index.py examples/ --tokens`):

| | tokens | vs fuente |
|---|---|---|
| fuente de los 5 ficheros | 835 | — |
| índice de firmas (completo) | **183** | **−78 %** (4.6×) |
| índice + `#` de encima (`--docs`) | 243 | −71 % (3.4×) |
| regla literal "solo columna 0" | 92 | −89 %, pero **sin métodos ni variantes** |

Por fichero el ahorro va de **3× a 7×**. Y la doc es ~25 % del índice: se sirve **a demanda**
(`--doc S`), no en el volcado. Eso basta para que un modelo decida qué leer de verdad.

## 5. Comandos

El índice se **consulta**, no se vuelca: una pregunta cuesta ~2 tokens y una respuesta de una
firma ~12, frente a ~150 por leer el fichero (**10.7×**). Estas son las consultas:

| Comando | Salida | Coste medido |
|---|---|---|
| `minim sig M.f` | la `sig` literal, una línea | 12 tokens |
| `minim type T` | variantes, campos y métodos de `T` | 14–30 |
| `minim find N` | `módulo:línea` de cada uso (sin candidatos múltiples) | 3–10 |
| `minim doc S` | el `#` de encima del símbolo | a demanda |
| `minim body S` | el cuerpo por span, si de verdad hace falta | = fuente |
| `minim borrow pl1, pl2` | ¿solapan estos dos lugares? (`SOUNDNESS` §10) | 1–2 |
| `minim errors F` | diagnóstico de una línea por error (§5 de `COMPILACION.md`) | 10–20 |
| `minim api M` | firma + doc de todo el módulo, orden estable | 21–100 (−71 %) |
| `minim diff A..B` | solo las firmas que cambiaron de interfaz | 5–30 |

| Comando de build | Salida |
|---|---|
| `minim index .` | `.minim/index.json` (todos los módulos, todos los símbolos) |
| `minim index --refs` | índice invertido de referencias |
| `minim index --changed` | solo lo que cambió de interfaz desde el último build |
| `minim fmt --check` | falla si el formato no es el canónico |

El protocolo completo de consulta, y por qué es fiable sin compilador, están en
[`docs/INDICE-LLM.md`](INDICE-LLM.md).

## 6. Uso desde un editor / LSP

| Función | Cómo |
|---|---|
| Contorno (outline) | `decls[]` del `.mimidx` |
| Ir a definición | tabla plana `nombre -> (módulo, span)` |
| Referencias | índice invertido de §3 |
| Hover | `sig` + `doc` |
| Diagnóstico | mensajes `fichero:línea:col`, siempre de una línea |
| Autocompletado | símbolos del módulo + prelude, sin sobrecarga |
| Rename | por nombre exacto, sin ambigüedad |

## 7. Por qué esto importa para los tokens

1. El resumen de un módulo (`--api`) es corto y **estable**: la misma pregunta al modelo
   produce el mismo prefijo, así que el *prompt cache* del proveedor acierta y se paga menos
   por cada token repetido.
2. La IA puede pedir el índice antes de leer cuerpos: menos tokens de entrada.
3. Los errores apuntan a una línea y a un nombre: menos tokens de ida y vuelta corrigiendo.
4. Al emitir código, las anclas de declaración son predecibles: el modelo no tiene que
   decidir *dónde* va la declaración ni en qué orden.
5. Se **consulta, no se vuelca**, y se sirve **en sintaxis Minim**, no en un formato inventado:
   el mismo programa como AST en JSON costaba **+63 %** de tokens (medido). El formato natural
   del código es el que el tokenizador tiene en el vocabulario.
6. El índice y la huella de interfaz son **el mismo dato** (`COMPILACION.md` §3), así que el
   índice es correcto por construcción y se puede versionar: `git diff` sobre él muestra
   **cambios de API**, no cambios de implementación.
