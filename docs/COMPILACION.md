# Minim 0.1 — modelo de compilación (estilo Delphi)

Objetivo: **compilar rápido, de forma incremental y determinista**, sin cabeceras, sin
declaraciones adelantadas y con análisis local. Delphi consigue tiempos de compilación
excelentes por cuatro razones, y Minim las reproduce de forma explícita.

## 1. Qué hace rápida a una compilación (y cómo se replica)

| Delphi | Minim |
|---|---|
| `interface` + `implementation` en el mismo fichero | **Bloque de firmas** extraído por escaneo del propio `.mim` |
| Una unidad = un fichero | Un `.mim` = una unidad = un módulo |
| Sin ficheros de cabecera que parsear dos veces | Sin cabeceras, sin `.h`, sin `declare` |
| Sin declaraciones adelantadas | El escaneo conoce todas las firmas antes de compilar el primer cuerpo |
| Compilación por unidad con caché | Huella por unidad; recompilación solo si cambia su **interfaz** |
| Sin plantillas complejas | Genéricos monomorfizados, memoizados y acotados por `trait` |
| Pocas pasadas sobre el código | 2 pasadas baratas: firmas (O(declaraciones)) + cuerpo (1 pasada) |

## 2. Pipeline

```
   .mim
    │
    ├─(1) ESCANEO ─────────────► .mimidx      índice de símbolos + huella de interfaz
    │      por líneas, columna 0, O(declaraciones)
    │
    ├─(2) COMPILACIÓN DE CUERPO ─► IR          una pasada, top-down, por función
    │      nombres + tipos + borrow check (local) + inserción de drops
    │
    ├─(3) MONOMORFIZACIÓN ──────► IR           instancias de genéricos, memoizadas
    │
    └─(4) LOWERING ─────────────► .mimo        bytecode de pila (v0.1)
                                                └─► nativo (v0.2, Cranelift)
```

### (1) Escaneo de firmas
Es el mismo algoritmo que el indexador (`docs/INDEXACION.md`): recorre líneas y solo mira
las que empiezan en columna 0 con `use|let|var|fn|type|trait|case`. No parsea expresiones,
no resuelve tipos, no toca cuerpos. Coste O(número de declaraciones), no O(líneas de código).

Resultado:
- tabla de símbolos del módulo (nombre -> firma, tipo, documento, span),
- huella de interfaz (hash),
- grafo de dependencias (`use`).

### (2) Compilación del cuerpo, una pasada
Se recorre cada cuerpo **de arriba a abajo** emitiendo IR. Consecuencias directas de que
exista la fase 1:

- **No hacen falta declaraciones adelantadas**: `fn a()` puede llamar a `fn b()` declarada 40
  líneas más abajo, porque `b` ya está en la tabla de símbolos.
- **No hay sobrecarga**: `nombre` -> un símbolo. La resolución es una búsqueda en tabla
  (local -> campo -> módulo -> prelude) sin candidatos múltiples ni resolución de
  sobrecargas, que es la parte cara de C++/Rust.
- **Sin coerciones implícitas** más allá de un literal entero a un tipo numérico; no hay
  inferencia global ni unificación entre funciones.
- **El tipo de retorno se infiere** del cuerpo. Es seguro *porque* el cuerpo se compila antes
  que cualquier llamada a esa función (las llamadas hacia delante pasan por la firma de la
  fase 1 y, si el retorno se omitió, por la instancia ya compilada, o por la firma escaneada).

### Borrado de tipos (*monomorphization*) y `trait`
- Un `trait` no genera vtable: el despacho es **estático** en v0.1 (sin `dyn`). El coste es
  código por instancia; la ventaja, cero análisis de tipos dinámicos.
- Cada instancia `list[int]`, `map[str, int]` se genera **una vez** por módulo de compilación
  y se memoiza en la caché. Límite de profundidad para evitar explosión.

### (3) *Borrow checker* local
El análisis de propiedad es **intra-procedural**: un recorrido del flujo de la función con un
estado por variable (`moved`, `shared(n)`, `unique`, `dropped`). No requiere mirar otras
funciones: los modos de parámetro ya están en la firma escaneada. Esto es lo que permite
compilar en una sola pasada sin esperar a un solver global.

- Se insertan los `drop` en los puntos de salida de ámbito (incluidos `?`, `or:` y `return`).
- Un préstamo termina en su último uso -> se puede reutilizar el nombre después.
- El chequeo se hace sobre el IR, con el mismo recorrido que el tipado.

## 3. Firewall incremental

La huella de una unidad se calcula **solo sobre su bloque de firmas** (fase 1): tipos
públicos, firmas, constantes `let`, y la lista de `use`.

```
huella(m) = hash( firma_1, firma_2, ..., firma_n )
```

Consecuencias:

- Cambiar **el cuerpo** de una función no cambia la huella: los módulos que la importan **no**
  se recompilan. Recompilación típica: 1 unidad.
- Cambiar una **firma** invalida solo a quien la usa (y con dependencias por símbolo, no por
  fichero).
- Igual que la sección `interface` de Delphi: el trabajo de recompilación se corta en la
  frontera de la interfaz, no en la frontera del fichero.

Los artefactos viven en `.minim/cache/<huella>/`. Caché puramente funcional: misma entrada,
mismo bytecode, sin firmas de tiempo ni rutas absolutas.

## 4. Determinismo

Mismo fuente + misma versión del compilador -> **mismo `.mimo` byte a byte**:

- sin orden dependiente de hash de punteros ni de paralelismo,
- sin metadatos de entorno en el artefacto,
- el formateador canónico (`minim fmt`) garantiza que el mismo programa escrito de dos formas
  distintas produce el mismo fuente y, por tanto, la misma huella.

Esto es lo que hace rentable cachear prompts/compilaciones y comparar hashes entre máquinas.

## 5. Diagnósticos

- Un error = **una línea**: `fichero:línea:col  error: mensaje`, con span exacto.
- Sin cascada: se emiten los primeros 5 errores de cada función y se sigue con las demás.
- Al no haber sobrecarga ni plantillas profundas, el mensaje nombra **una** declaración y una
  causa; nunca "no se pudo deducir el tipo de una expresión de 40 líneas".
- Cada error incluye la corrección más corta (cambiar `let` por `var`, añadir `?`, mover).

## 6. Backends

| Backend | Estado | Notas |
|---|---|---|
| Intérprete de bytecode de pila | v0.1 | `.mimo`, arranque inmediato, depuración fácil |
| Nativo vía Cranelift | v0.2 | misma IR; ABI C simple para interop |
| LLVM | v0.3 | optimizaciones agresivas, opcional |

El bytecode es de pila, con instrucciones de una letra/una palabra (`load`, `add`, `call`,
`drop`, `br`) y sin GC: el `drop` ya está insertado en la fase 2, así que el runtime solo
llama al destructor cuando el programa lo dice.

## 7. Objetivos de rendimiento

| Métrica | Objetivo |
|---|---|
| Compilación desde cero | > 100 000 LOC/s en un hilo |
| Recompilación incremental de 1 unidad | < 10 ms |
| Escaneo de firmas (fase 1) | < 1 ms por 1 000 líneas |
| Memoria del compilador | proporcional a declaraciones + cuerpo en compilación |
| Determinismo | mismo fuente -> mismo bytecode, byte a byte |

## 8. Lo que Minim **no** hace (a propósito)

- No hay cabeceras, `forward`, `extern` ni orden de declaración obligatorio.
- No hay sobrecarga de funciones ni de operadores ni constructores implícitos.
- No hay plantillas sin restricciones ni *type traits* de usuario.
- No hay `dyn Trait` ni reflexión en v0.1.
- No hay análisis global de préstamos ni parámetros de vida.
- No hay macros ni decoradores: nada que reescriba la sintaxis antes de compilar.

Cada uno de esos "no" elimina una fase, un solver o una pasada: es lo que hace que la
compilación sea **fácil** de escribir y rápida de ejecutar, no solo la sintaxis.

## 9. El índice para el modelo

La fase 1 no solo alimenta la caché incremental: es también la superficie que un modelo usa para
averiguar tipos y firmas **sin leer el código**. El índice y la huella de interfaz son el mismo
dato (§3), así que el índice es correcto por construcción y se invalida solo cuando cambia una
firma — no cuando cambia un cuerpo.

Medido sobre `examples/` (`o200k_base`): el índice de firmas son **183 tokens** frente a **835**
del fuente (−78 %), y una consulta puntual con su respuesta **14 tokens** frente a 150 por leer
el fichero (**10.7×**). El protocolo de consulta, la regla de obsolescencia y las consultas que
no existen en otros lenguajes (`borrow`, `diff`) están en [`docs/INDICE-LLM.md`](INDICE-LLM.md);
el prototipo que ya funciona, en `tools/index.py`.
