# Minim 0.1 — ¿es el *borrow checker* matemáticamente infalible?

**No.** Tal como estaba especificado en `docs/OWNERSHIP.md` no es ni siquiera un sistema
formal: es un boceto en prosa. No hay semántica operacional, no hay reglas de tipado, no hay
demostración, y había **agujeros concretos**, uno de los cuales invalidaba dos promesas del
diseño (índice estable y *firewall* incremental). Este documento dice qué es alcanzable, qué
estaba mal, qué se ha corregido, y qué haría falta para poder usar la palabra "demostrado".

## 1. Qué tendría que significar "infalible"

| Propiedad | Definición | ¿Alcanzable? |
|---|---|---|
| Determinismo de la especificación | El conjunto de programas aceptados está bien definido por las reglas | **Sí**, y es obligatorio |
| **Solidez** (*soundness*) | Si el compilador acepta `P`, ninguna ejecución de `P` accede a memoria liberada, ni libera dos veces, ni tiene carreras | **Sí**, para un subconjunto explícito |
| **Completitud** | Si `P` es seguro, el compilador lo acepta | **No**, imposible (teorema de Rice) |
| Principalidad de la inferencia | Si existe solución para los tipos/modos, el algoritmo la encuentra | **Sí**, si se restringe la inferencia a lo local |
| Terminación del chequeo | El análisis acaba | **Sí** (dataflow sobre retículo finito) |

Un compilador **solo sólido** rechaza programas seguros: eso no es un fallo, es el precio.
El error grave es lo contrario: aceptar programas inseguros. Sin demostración de solidez,
"infalible" es una afirmación sin contenido.

## 2. Agujeros que tenía el diseño

| # | Agujero | Consecuencia | Estado |
|---|---|---|---|
| A1 | **El modo del parámetro/receptor se infería del cuerpo** (`fn inc(self)` mutaba) | La firma dejaría de ser el contrato: índice de símbolos incompleto, `firewall` incremental roto (un cambio de cuerpo cambiaría la interfaz), e inferencia no local con recursión mutua | **Corregido**: el modo está en la firma |
| A2 | **Devolver un préstamo de un parámetro** sin regla de elisión, y sin modelo de temporales | Referencia colgante: `let r = f(temp())` sobrevive al temporal | **Corregido**: elisión restringida + temporales mueren al final de la sentencia |
| A3 | **Movimientos parciales** sin banderas de drop | Doble liberación o liberación de un campo ya movido | **Corregido**: prohibido mover campos en v0.1 |
| A4 | **Closures que escapan** (devolverse o guardarse) | La closure captura por préstamo y sobrevive al dueño | **Corregido**: las closures no escapan en v0.1 |
| A5 | **`spawn`/`await` sin reglas de aislamiento** | Carrera de datos: un préstamo vivo que cruza `await`, o `rc` compartido entre hilos | **Corregido**: `spawn` consumes argumentos y exige aislamiento |
| A6 | **`rc`/`arc` con mutación interior** | Los préstamos pasan a comprobarse en *runtime* (como `RefCell`): se sale del mundo estático | **Declarado** en vez de oculto (§5) |
| A7 | **Exclusividad a nivel de dueño**, no de campo | Rechaza programas seguros (`swap(p.a, p.b)`) | **Resuelto** en §10: exclusividad por **lugar** (camino) |
| A8 | Sin reglas de **reb presta** ni *two-phase borrows* | Más incompletitud (`v.push(v.len)` falla) | **Parcialmente corregido** en v0.1: ver §9 (receptor simple) |
| A9 | Sin semántica de **orden de drop** en cada salida (`?`, `or:`, `return`, `break`) | Fugas o doble drop en salidas tempranas | Pendiente de especificar (mecánico) |

A1 es el más grave porque no era un problema de seguridad, sino de **coherencia del diseño**:
prometía "el escaneo de firmas es O(declaraciones) y define la interfaz", y a la vez infería
parte de la firma desde el cuerpo. Dos promesas incompatibles. Se ha resuelto a favor de la
interfaz (y el receptor mutante cuesta 1 token más: `var self`).

## 3. Las reglas que quedan (núcleo mínimo sólido)

**Juicio.** `Γ; Δ ⊢ e : τ ▷ Γ′; Δ′`, donde

- `Γ` mapea variables a estado: `Owned τ`, `Moved`, `Borrowed(κ)`.
- `Δ` mapea préstamos `κ` a `(lugar, modo ∈ {shared, unique}, región)`.
- `región` es un intervalo `[definición, último uso]` del préstamo (*lifetimes* internos,
  nunca escritos por el programador: solo se calculan).

**Invariantes del heap** (lo que hay que preservar en cada paso de ejecución):

1. **I1 Dueño único**: cada objeto del heap tiene exactamente un dueño.
2. **I2 Préstamo vivo**: todo `κ` vivo apunta a un lugar cuyo dueño está vivo y no movido.
3. **I3 Exclusividad**: si `κ` es `unique`, no hay otro `κ′` vivo sobre el mismo lugar ni
   acceso directo al dueño; si es `shared`, solo otros `shared`.
4. **I4 Drop exacto**: todo valor no copiable se libera exactamente una vez en cada camino.
5. **I5 Aislamiento**: ningún valor con préstamo vivo cruza un `spawn`/`await` (formaliza la
   restricción de hilos; es el papel de `Send`/`Sync` en Rust).

**Teoremas a demostrar** (hoy: enunciados, no demostrados):

| | Enunciado |
|---|---|
| T1 Progreso | Un programa aceptado y cerrado no se atasca: toda expresión en posición de evaluación da un paso o es un valor |
| T2 Preservación | Si `Γ; Δ ⊢ P` y `P → P′`, entonces `Γ′; Δ′ ⊢ P′` y los invariantes I1-I5 siguen valiendo |
| T3 No uso tras mover/liberar | Corolario de I1-I2-I4: no hay *use-after-free* ni doble liberación |
| T4 Ausencia de carreras | En el fragmento concurrente con I5, dos hilos no acceden al mismo lugar si uno escribe |
| T5 Terminación | El chequeo es un *dataflow* sobre un retículo finito: punto fijo en `O(n · v)` |
| T6 Adecuación del algoritmo | El algoritmo acepta `P` solo si las reglas derivan `P` (solidez de la implementación respecto de la especificación) |

**Región de un préstamo (el cálculo concreto).** Un préstamo `κ` sobre `x` nace en la
expresión `&x` y muere en su último uso posterior (estilo NLL). Con solo intervalos, la
comprobación de I3 es una verificación de solapamiento por lugar; con estados por variable es
un recorrido del flujo de control. Ambos son polinómicos y locales a la función.

## 4. Lo que se corrigió hoy

**Modo explícito en la firma** (`docs/OWNERSHIP.md` §3):

```python
fn len(self) -> int            # shared   (por defecto)
fn inc(var self, by: int = 1)  # unique   (obligatorio si muta)
fn take(move self) -> [int]    # consume
```

- Omitir el modo significa **compartido**, siempre. Mutar a través de un parámetro sin `var`
  es un **error de compilación**, no una inferencia.
- Dentro del cuerpo, `&x` sigue sin sigilo: el modo ya está declarado una vez en la cabecera,
  que es donde tiene que estar (contrato, índice, huella incremental).
- Aún se infiere lo que es genuinamente local: tipos de locales y retorno, regiones de
  préstamo, `async`, resolución de nombres.

Coste medido: 1 token por método mutante (`fn inc(var self, ...)` = 14 tokens, igual que
`fn inc(&mut self, by: i64) -> i64` de Rust). El diseño anterior gastaba 13 y era inconsistente.

## 5. Dónde la solidez estática termina (y hay que decirlo)

- **`rc[T]` / `arc[T]`**: hay mutación interior, así que el préstamo se comprueba en
  *runtime* (como `RefCell`). Un uso incorrecto **aborta en ejecución**, no en compilación.
  Está bien tenerlo, siempre que no se venda como garantía estática.
- **Fugas de memoria**: `sound` no significa "sin fugas". Un ciclo con `rc` puede no liberarse
  nunca; eso es correcto (no inseguro) y hay que documentarlo como tal.
- **`drop` y `panic`**: si un destructor falla a mitad, hay que definir si se aborta o se
  continúa soltando lo demás (opción: abortar, como en Rust ante *panic* en *drop*).
- **Nada de `unsafe` en v0.1**: sin escotilla de escape, todo el lenguaje cae dentro del
  teorema. Renunciar a `unsafe` también renuncia a implementar `rc`/`net` en Minim puro
  (habrá que marcar un prelude de confianza, `@trusted` o similar).

## 6. Incompletitud asumida (programas seguros que se rechazan)

| Simplificación | Programa seguro rechazado |
|---|---|
| Exclusividad por dueño, no por campo | `swap(var s.a, var s.b)` |
| Sin *two-phase borrows* | `v.push(v.len)` |
| Sin referencias en campos | `type Iter  cur: &[int]` (iteradores con préstamo) |
| Sin movimientos parciales | `let x = b.data` dejando `b` parcialmente vivo |
| Closures no escapantes | devolver una closure que captura un local |
| Sin préstamos devueltos salvo elisión | `fn get(d: map[str, int], k: str) -> &int` |

Cada fila es una simplificación que **elimina una prueba o una sintaxis** (lifetimes,
variance, drop flags, `PhantomData`). Es el intercambio central del diseño: menos tokens y
menos análisis a cambio de rechazar más programas seguros.

## 7. Por qué Rust necesita lo que necesita (y Minim lo evita)

Cada mecanismo de Rust existe por un agujero concreto de este listado:

| Rust | Agujero que cierra | Minim |
|---|---|---|
| NLL / Polonius | Regiones de préstamo precisas en flujo con ramas | Regiones simples por último uso (v0.1) |
| *Two-phase borrows* | `v.push(v.len)` | No implementado: se rechaza |
| *Drop flags* | Movimientos parciales | Movimientos parciales prohibidos |
| `PhantomData` / variance | Préstamos y tipos fantasma en genéricos | Referencias no almacenables |
| `Send` / `Sync` | Carreras de datos con hilos y `async` | Restricción de `spawn` (I5), más tosca |
| `Pin` | Auto-referencias | No hay auto-referencias |
| `unsafe` | Implementar `rc`, colecciones, FFI | No existe: prelude de confianza o `@trusted` |
| `'a` en firmas | Préstamos devueltos y guardados | Elisión + préstamos no almacenables |

Minim no es "Rust sin *lifetimes* por elegancia": es un lenguaje **más pequeño a cambio de
rechazar más**, y ese intercambio es lo que hay que poder justificar con una demostración, no
con una afirmación.

## 8. Criterio para poder llamarlo "infalible"

- [ ] Semántica operacional de Minim (pila + heap + drops), informal y luego formal.
- [ ] Reglas de tipado completas (los juicios de §3, para cada forma del lenguaje).
- [ ] Prueba de **progreso** (T1) y **preservación** (T2) por inducción sobre la derivación.
- [ ] Prueba de **ausencia de carreras** (T4) para el fragmento con `spawn`/`await`.
- [ ] Prueba de **terminación y adecuación del algoritmo** (T5, T6): que el chequeo acepta
      exactamente lo que las reglas derivan.
- [ ] Especificación del **orden de drop** en todas las salidas (`?`, `or:`, `return`,
      `break`, `panic`) — A9.
- [ ] Suite de **pruebas de mutación**: programas inseguros que deben ser rechazados
      (use-after-move, doble drop, préstamo exclusivo solapado, préstamo que cruza `await`,
      retorno de préstamo a temporal, doble liberación por movimiento parcial).

El plan detallado para cerrar cada casilla está en [`docs/FORMAL.md`](FORMAL.md): enunciados
formales (T1-T6), qué obligación genera cada decisión de diseño, con qué herramienta se
mecaniza y cuánto cuesta. Los programas testigo, en [`formal/CASES.md`](../formal/CASES.md).

Hasta la primera casilla, el *borrow checker* de Minim es **un diseño razonable y con un caso
de uso claro**, no un resultado matemático. Lo que exigiría la palabra "infalible" es la lista
completa, y hay precedentes de que es realizable: Rust, Cyclone, Pony y Mezzo tienen el
teorema escrito para sistemas más ricos que este.

---

## 9. Corrección parcial de A8: el receptor simple

**El problema**: `v.push(v.len)` exige un préstamo único (por `var self`) y una lectura de `v` en
el **mismo punto**. Pero los dos hechos **no son simultáneos**: el orden de evaluación es de
izquierda a derecha y el argumento se lee **antes** de que la llamada se ejecute.

**La distinción que lo resuelve**: *evaluar* el receptor no es *tomar su préstamo único*.
Del receptor solo hace falta, antes de los argumentos, **dónde está** (su lugar); el préstamo único
se necesita cuando la llamada **se ejecuta**, o sea **después** de evaluar los argumentos.

**La corrección (v0.1, sin coste en el resto del diseño)**: es una **regla de elaboración**
(T0), no un cambio de las reglas de préstamo. Si el receptor es un **lugar simple** —una variable o
una ruta de campos (`v`, `x.f`, `x.f.g`), **sin índices ni llamadas**—, adelantar los argumentos a
temporales no cambia el significado, porque evaluar un lugar simple no tiene efectos:

```
v.m(a)   ⟹   let t = a
             v.m(t)
```

Con eso, `v.push(v.len)` y `v.push(v.pop())` se aceptan, y **no hay que tocar**: ni la semántica
(§2 de este documento), ni las reglas de préstamo (`FORMAL.md` §5), ni el invariante I3, ni T2, ni
la firma como contrato del índice (A1 queda intacto: el modo del receptor sigue estando en la
firma).

**La condición lateral es necesaria, no decorativa.** Si el receptor **no** es un lugar simple, la
reordenación cambia el programa:

```python
var v = [3, 1, 2]
v[v.len - 1].push(limpiar(v))     # el índice lee 'v' antes; el argumento muta 'v'
```

Aquí el receptor es `v[v.len - 1]`: su índice **lee** `v`, y el argumento `limpiar(v)` **muta** `v`.
Intercambiar el orden da otro resultado. Por eso el refinamiento se limita a lugares simples; el
caso general exige reservar el préstamo sin activarlo (*two-phase borrows*), y eso sí es caro:
estado de permiso `resv`, I3 de dos fases, T2 rehecho.

**Obligaciones que genera** (baratas, y hay que apuntarlas):

1. **T0**: la reordenación preserva el significado cuando el receptor es un lugar simple
   (el argumento puede seguir siendo arbitrario: solo se adelanta **su evaluación**, y entre
   él y la llamada no hay nada observable).
2. **Elisión**: el temporal nuevo entra en el modelo de temporales de A2 (muere al final de la
   sentencia) y no debe cambiar la elisión de préstamos devueltos.
3. **Corpus**: `formal/CASES.md` gana el caso `A11` (aceptar) y R12 se queda como testigo del caso
   general que **sigue** rechazado (receptor con índice o llamada).

---

## 10. Resolución de A7: exclusividad **por lugar**, no por dueño

### 10.1 El caso, en lenguaje natural

Un `Pair` tiene dos campos, `a` y `b`. Son **dos cajones distintos del mismo armario**. Prestar
`p.a` en exclusiva a una función y, **a la vez**, `p.b` a otra (o la misma, como segundo
argumento) es perfectamente seguro: nadie va a tocar el cajón del otro. Rust lo acepta
(`&mut s.a, &mut s.b`).

v0.1 lo rechaza porque el libro de préstamos anota **el dueño** (`p`) y no el **lugar** (`p.a`).
Dos préstamos únicos con el mismo dueño parecen el mismo préstamo.

### 10.2 Cuidado: R13 estaba mal enunciado

Hay que separar dos variantes, porque no son el mismo problema:

| Variante | ¿Es A7? | Estado en v0.1 |
|---|---|---|
| **Secuencial**: `fill(p.a, 1)` y **después** `fill(p.b, 1)` | **no** | **aceptado**: la región del primer préstamo termina en su último uso (R7) |
| **Simultánea**: `swap(p.a, p.b)`, dos argumentos `var` en **una** llamada | **sí** | **rechazado**: los dos préstamos tienen `origin = p` y están vivos en el mismo punto |

La variante secuencial **no** es incompletitud: es el comportamiento correcto de las reglas de
§5.2. Si el checker la rechazara, sería un **bug** de la máquina de estados (Γ no devolviendo
`Owned` tras morir el préstamo), no un límite del modelo. Conviene fijarla como test.

### 10.3 La corrección, en lenguaje formal

**Paso 1 — Los lugares son caminos.**

```
pl ::= x | pl.f | pl[i]
```

**Paso 2 — Un solo predicado nuevo: `overlap` (solapamiento de caminos).**

```
overlap(pl1, pl2)  ≜  pl1 es prefijo de pl2  ∨  pl2 es prefijo de pl1
```

- `overlap(p.a, p.b)` = **falso**: ninguno es prefijo del otro. ← aquí se gana el caso swap.
- `overlap(p, p.a)` = **verdadero**: `p` es prefijo. ← un préstamo sobre el todo excluye las partes.
- `overlap(p.a, p.a.b)` = **verdadero**.

**Paso 3 — Se sustituye `origin(κ, x, m)` por `origin(κ, pl, m)` y `same_place(x, x2)` por
`overlap(pl, pl2)` en las reglas de `docs/FORMAL.md` §5.2** (ver allí la variante §5.3).

**Paso 4 — La puerta de la llamada.** Esto es lo que impide que se cuele un alias por la puerta
de atrás: en una llamada, los lugares de los argumentos `var` deben ser **disjuntos dos a dos**:

```
error :- arg(pl1), arg(pl2), pl1 ≠ pl2, overlap(pl1, pl2), (uniq(pl1) ; uniq(pl2)).
```

- Rechaza `swap(p, p)` y `swap(p.a, p.a)` (los dos argumentos solapan).
- **Acepta** `swap(p.a, p.b)` ← el caso A7 resuelto.

Es la misma relación `overlap` usada en dos sitios: dentro (préstamos contra accesos) y en la
puerta (argumentos entre sí). Una relación, dos usos.

**Paso 5 — I3 pasa a ser por lugar.**

> **I3′**: en todo punto `p` y todo lugar `pl`: (a) a lo sumo **un** préstamo vivo `uniq` cuyo
> lugar solape con `pl`; y (b) ningún préstamo `uniq` solapa con un préstamo compartido vivo.

**Paso 6 — El lema que lo sostiene (obligación nueva de T3).**

> **Lema (actualización disjunta)**: si `pl1` y `pl2` **no** solapan, escribir en `pl2` no cambia
> el valor del lugar `pl1`.

Se prueba por inducción sobre la estructura de los caminos. Es exactamente lo que permite que el
cuerpo del callee escriba en `p.a` sin invalidar el préstamo sobre `p.b`.

**La hipótesis de la que todo depende** (*disjunción de raíces*): dos **variables** distintas
denotan asignaciones distintas, es decir, no hay alias entre raíces. Se sostiene porque los
préstamos **no se almacenan** en campos (A2) y porque los argumentos se comprueban en la puerta
(Paso 4). Sin esta hipótesis, comparar caminos sintácticamente no sería sólido. Rust descansa
exactamente en la misma.

### 10.4 Qué cambia y qué no

| Pieza | ¿Cambia? | Detalle |
|---|---|---|
| Sintaxis de superficie | **no** | cero tokens: `p.a` ya se escribe así |
| Semántica (heap) | **sí, poco** | el heap se indexa por **caminos** (`H[pl ↦ v]`), no solo por `Loc` |
| Reglas de préstamo (§5.2) | **sí** | `origin` guarda un camino; `same_place` → `overlap` |
| Puerta de la llamada | **sí, nuevo** | disjunción dos a dos de los argumentos `var` |
| I3 | **sí** | pasa a I3′ (por lugar) |
| T3 | **sí** | +1 lema: actualización disjunta |
| I1, I2, I4, I5 | **no** | — |
| T1 (exactitud) | **no** | el dominio pasa de variables a caminos: sigue siendo **finito**, el punto fijo existe igual |
| T2 (principalidad) | **no** | mismas reglas, misma monotonía en las regiones |
| Índice / firma (A1) | **no** | los nombres de campo ya están en el AST |

### 10.5 Límites que se mantienen (y hay que declarar)

- **Lugares con índice** son conservadores: `p.a[i]` y `p.a[j]` se consideran **solapados** salvo
  si ambos índices son constantes distintas. Así `swap(p.a[0], p.a[1])` sigue rechazado — igual
  que Rust, que para eso exige `split_at_mut`.
- La relación `overlap` es **sintáctica** y por tanto conservadora: nunca acepta algo inseguro,
  pero puede rechazar dos lugares que casualmente coinciden.
- `p` y `p.a` siguen siendo incompatibles: leer el todo mientras alguien tiene una parte es
  legítimamente peligroso.

### 10.6 Por qué resolver A7 antes que A8

| | A7 (lugares por campo) | A8 (dos fases) |
|---|---|---|
| Predicados/reglas nuevas | **1** (`overlap`) | `reserved_at`, `activated_at`, fase en cada regla `error` |
| Semántica | caminos en el heap | **permiso nuevo** `resv` + pasos de activación |
| Invariante | I3′ (reformular) | I3 **de dos fases** |
| T2 | **sin cambios** | **rehecho** (dos intervalos) |
| T1 | sin cambios | sin cambios |
| Ganancia | `swap(p.a, p.b)`, préstamos simultáneos de campos | `v.push(v.len)` con receptor no simple |

Conclusión: **A7 es mucho más barato y más rentable**. Y el modelo que resulta es, literalmente,
una pizca de **lógica de separación** restringida a caminos: `pl1 ⟂ pl2` (no solapan) es el `*`
de la lógica de separación, aplicado solo a sub-lugares de un mismo dueño.

**Recomendación**: adoptar §10 en v0.1.1 (o v0.2) y mover R13 a la columna de **ACEPTAR**; dejar
A8 (caso general) para más adelante.
