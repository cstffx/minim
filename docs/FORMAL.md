# Minim — cómo demostrar el *borrow checker* (plan formal)

Respuesta corta: **"matemáticamente exacto" tiene tres significados distintos y solo dos son
demostrables.** Lo que sí es demostrable son teoremas concretos, con enunciados que se pueden
escribir hoy y mecanizar por partes. Este documento dice cuáles son, cómo se prueban, qué
hace falta de cada uno y cuánto cuesta.

---

## 1. Las tres "exactitudes"

| Nombre | Enunciado | ¿Demostrable? | Coste |
|---|---|---|---|
| **E1. Exactitud del algoritmo** | `checker(P) = Aceptar ⟺ ¬∃ error derivable en el sistema declarativo` | **Sí** | semanas |
| **E2. Principalidad de la inferencia** | Si existe asignación de regiones que tipa `P`, la asignación por último uso también | **Sí** | semanas |
| **E3. Solidez** | `Aceptar(P) ⟹ P nunca accede a memoria liberada, ni libera dos veces, ni tiene carreras` | **Sí**, para el núcleo | meses |
| ~~E4. Completitud absoluta~~ | `Aceptar(P) ⟺ P es seguro` | **No** (Rice + argumento diagonal) | — |

E4 es imposible y hay que decirlo explícitamente: **ningún** checker decidible acepta
exactamente los programas seguros. Lo máximo que se puede prometer es:

> E1 y E2 **relativas a las reglas** (el algoritmo implementa las reglas exactamente), y
> E3 **absoluta** (las reglas garantizan seguridad).

La buena noticia es que E1 es exactamente lo que la gente suele querer decir con "exacto", y es
barato de probar si el sistema declarativo se escribe como **Datalog** (§5).

---

## 2. Estrategia en cuatro capas

```
   superficie Minim  ──(elaboración)──►  CoreMin          [T0: fidelidad]
                                            │
                        ┌───────────────────┴───────────────────┐
                        ▼                                       ▼
              semántica operacional                    sistema declarativo
              (pila + heap + fallos)                    (reglas de préstamo)
                        │                                       │
                        │                          ┌────────────┴────────────┐
                        │                          ▼                         ▼
                        │                    algoritmo (punto fijo)   principalidad
                        │                          │
                        └────────►  T3 solidez  ◄──┘
                                    T4 carreras
```

Cada flecha es un teorema independiente. Esa es la clave metodológica: **no se demuestra "el
borrow checker", se demuestran cinco cosas pequeñas y encadenadas.**

---

## 3. Capa 0: CoreMin (el lenguaje que se demuestra)

El lenguaje de superficie es demasiado grande para una demostración. Se extrae un núcleo; el
resto es elaboración.

```
τ ::= int | bool | str | unit | τ × τ | [τ] | &τ | (τ) -> τ
e ::= x | c | fn (x: τ) => e | e e | let x = e in e
    | alloc v | !e | e := e | free e        -- free = drop, explícito en el núcleo
    | &shr x | &uniq x | move x
    | e.f | {f = e} | case C(e) | match e { ... } | let C(x) = e in e
    | if e { e } else { e } | while e { e } | break | continue
    | spawn e | join e
```

**Elaboración** (superficie -> núcleo), lo que hay que demostrar que no cambia el significado:

| Superficie Minim | CoreMin |
|---|---|
| campos sin `self.` | `self.f` |
| `or <expr>` / `or:` | `match ... { ok v => ..., err e => ... }` |
| `?` | `match ... { err e => return err e, ok v => v }` |
| retorno implícito | `return` al final del cuerpo |
| `for x in e` | `while` sobre un iterador |
| `elif` | `else` + `if` |
| **inserción de `free`** | drops explícitos en cada salida de ámbito (incl. `?`, `or:`, `return`, `break`) |
| métodos | llamadas con `self` como primer argumento |
| `spawn f(a)` | `spawn move fn a => f(a)` (transferencia) |
| `v.m(a)` con receptor **lugar simple** | `let t = a in v.m(t)` (ver nota A8) |

**Nota (A8, §18 de `docs/APRENDER-DEMOSTRACIONES.md`)**: el receptor se **evalúa** primero
(orden de izquierda a derecha), pero el **préstamo único** que necesita solo se **toma** cuando la
llamada se ejecuta. Si el receptor es un **lugar simple** —una variable o una ruta de campos, sin
índices ni llamadas—, evaluarlo no tiene efectos observables, así que adelantar la evaluación de
los argumentos no cambia el significado. Entonces `v.push(v.len)` se elabora a
`let t = v.len in v.push(t)` y **se acepta sin tocar las reglas de préstamo** (§5), sin estado de
permiso nuevo y sin cambiar T2 ni I3. El caso general (receptor con índice o con llamada) sigue
rechazado: aceptarlo exige *two-phase borrows* reales (reservado → activo), lo que sí obliga a un
permiso `resv` en la semántica (§4), a un I3 de dos fases y a rehacer T2.

**T0 (fidelidad)**: `elab` es una simulación en ambos sentidos: `P → P'` sii
`elab(P) → elab(P')`. Sin T0, demostrar CoreMin no dice nada de Minim. Es tedioso pero
mecánico (y es donde se prueban de una vez A2: temporales, y A9: orden de *drop*).

---

## 4. Capa 1: semántica operacional

Configuración: `H ; T` donde `H : Loc ⇀ Val` es el heap y `T` es un multiconjunto de hilos
`(σ, e)` con `σ` el entorno de pila.

- Los **fallos** son explícitos: `!ℓ` con `ℓ ∉ dom H` es *fault*; `e := ℓ` sin permiso de
  escritura es *fault*; `free ℓ` con `ℓ ∉ dom H` es *fault* (esto captura el doble *free*).
- Añadimos un **permiso** a cada celda: `H(ℓ) = ⟨v, perm⟩` con `perm ∈ {shr(n), uniq}`, para
  que "escribir sin permiso" sea un fallo *dinámico* y la seguridad sea un teorema sobre la
  semántica, no una definición circular.
- El paso entre hilos es no determinista, pero **solo** cuando hay más de un hilo (`spawn`).

**Safe(P)** ≜ ninguna ejecución de `P` alcanza *fault*.

Sin este paso no hay nada que demostrar: E3 es un enunciado sobre esta semántica.

---

## 5. Capa 2: sistema declarativo

Dos formulaciones equivalentes. La primera es la que se enseña; la segunda es la que se
**mecaniza**, porque su exactitud algorítmica es gratis.

### 5.1 Juicio de tipado con regiones (forma de presentación)

```
Γ ; Δ ; Σ ⊢ e : τ ⊣ (Γ' ; Δ' ; Σ')
```

- `Γ : Var ⇀ Owned(τ) | Moved | Borrowed(κ)`
- `Δ : Loan ⇀ (place, mode, R)` con `mode ∈ {shr, uniq}` y `R ⊆ Puntos` (**región**)
- `Σ : Loc ⇀ τ` (tipado del almacén, como en Tofte–Talpin / Alias Types)

Reglas centrales (las que importan):

```
Γ(x) = Owned(τ)      Γ' = Γ[x ↦ Borrowed(κ)]      κ ∉ dom Δ
──────────────────────────────────────────────────────────────  (BORROW-shr)
Γ;Δ;Σ ⊢ &shr x : &τ ⊣ (Γ'; Δ[κ ↦ (x, shr, R)]; Σ)

Γ(x) = Owned(τ)      Γ' = Γ[x ↦ Borrowed(κ)]
──────────────────────────────────────────────────────────────  (BORROW-uniq)
Γ;Δ;Σ ⊢ &uniq x : &τ ⊣ (Γ'; Δ[κ ↦ (x, uniq, R)]; Σ)
   condición: κ es el único préstamo vivo sobre x en todo punto de R

Γ(x) = Owned(τ)
───────────────────────────────────────────  (MOVE)
Γ;Δ;Σ ⊢ move x : τ ⊣ (Γ[x ↦ Moved]; Δ; Σ)

Γ(x) = Moved
─────────────────────────────────────  (ERROR: uso tras mover)
Γ;Δ;Σ ⊢ x : ⊥
```

Las regiones `R` son **existenciales** en el sistema declarativo (el programador no las
escribe) — de ahí E2.

### 5.2 Formulación Datalog (la que se mecaniza) ✅

Los hechos se generan del CFG y de las declaraciones; la aceptación es la ausencia de un hecho
`error`. Es el esquema de Polonius.

```
% --- hechos (extensionales) ---
origin(κ, x, mode)
issued_at(κ, p)
used_at(κ, p)                    % la referencia derivada de κ se usa en p
access(x, p, kind)               % lectura/escritura directa del dueño en p
moved_at(x, p)
deref(r, κ)                      % r procede del préstamo κ
may_borrow(x, κ)                 % correspondencia por subcampos (v0.1: solo el dueño entero)

% --- reglas (intensionales) ---
live(κ, p)      :- issued_at(κ, p0), used_at(κ, p1), p0 ≤ p ≤ p1 .
uniq(κ)         :- origin(κ, _, uniq) .

error(x, p)     :- moved_at(x, p0), p0 < p, reachable(p0, p) .

error(κ, p)     :- live(κ, p), origin(κ, x, _), access(x, p, write) .
error(κ, p)     :- live(κ, p), origin(κ, x, _), moved_at(x, p) .
error(κ, κ', p) :- live(κ, p), live(κ', p), origin(κ, x, m), origin(κ', x, m'),
                   κ ≠ κ', (m = uniq ; m' = uniq) .
error(κ, p)     :- live(κ, p), origin(κ, x, uniq), live(κ2, p),
                   origin(κ2, x2, _), same_place(x, x2) .
```

**Aceptar(P)** ≜ `lfp(F_P) ⊭ error(_, _)`.

Todas las reglas son monótonas y el dominio es finito (`Puntos × Préstamos`), así que el punto
fijo mínimo existe (Knaster–Tarski).

### 5.3 Variante con lugares por campo (resolución de A7) — propuesta

Sustituye a §5.2 en cuanto a `origin`/`same_place`. Motivo y discusión: `docs/SOUNDNESS.md` §10.

```
% --- hechos: el lugar es un CAMINO, no un dueño ---
origin(κ, pl, mode)              % pl ::= x | pl.f | pl[i]
issued_at(κ, p)
used_at(κ, p)
access(pl, p, kind)              % lectura/escritura directa del lugar pl en p
moved_at(pl, p)
arg(pl)                          % argumento de una llamada en curso
uniq(pl)                         % el argumento pl pide prestamo unico

% --- reglas ---
live(κ, p)     :- issued_at(κ, p0), used_at(κ, p1), p0 ≤ p ≤ p1 .
uniq(κ)        :- origin(κ, _, uniq) .

overlap(pl1, pl2)  % definido: pl1 prefijo de pl2  |  pl2 prefijo de pl1

error(pl, p)    :- moved_at(pl, p0), p0 < p, reachable(p0, p) .

error(κ, p)     :- live(κ, p), origin(κ, pl, _), access(pl2, p, write), overlap(pl, pl2) .
error(κ, p)     :- live(κ, p), origin(κ, pl, _), moved_at(pl2, p), overlap(pl, pl2) .
error(κ, κ', p) :- live(κ, p), live(κ', p), origin(κ, pl, m), origin(κ', pl2, m'),
                   κ ≠ κ', overlap(pl, pl2), (m = uniq ; m' = uniq) .

% --- la puerta de la llamada: los argumentos 'var' deben ser disjuntos dos a dos ---
error(pl1, pl2) :- arg(pl1), arg(pl2), pl1 ≠ pl2, overlap(pl1, pl2),
                   (uniq(pl1) ; uniq(pl2)) .
```

**Qué gana**: `swap(p.a, p.b)` se acepta, porque `overlap(p.a, p.b)` es falso. **Qué conserva**:
`swap(p, p)` y `swap(p.a, p.a)` se rechazan (los argumentos solapan); `p` y `p.a` siguen siendo
incompatibles.

**Obligación nueva de T3**: el **lema de actualización disjunta** (`SOUNDNESS.md` §10.3): si
`pl1` y `pl2` no solapan, escribir en `pl2` no cambia el valor de `pl1`. Es lo único que hay que
añadir a la demostración; I3 pasa a su forma por lugar (I3′), y T1/T2 **no cambian**.

---

## 6. Los teoremas, uno por uno

### T1 — Exactitud del algoritmo (E1)

> `checker(P) = Aceptar  ⟺  ¬∃e. error(e) ∈ lfp(F_P)`

**Prueba.** El algoritmo es semi-naive (o *worklist*): calcula exactamente el punto fijo mínimo
de un sistema Datalog. Es un resultado estándar de teoría de bases de datos
(Abiteboul–Hull–Vianu, *Foundations of Databases*, cap. 13): el punto fijo mínimo coincide con
el conjunto de hechos derivables. La regla de aceptación es la negación de la presencia de un
hecho.

**Qué descarta.** Prueba que no hay "falsos rechazos por implementación" y que no hay "falsas
aceptaciones por reglas no aplicadas": lo que el checker decide es *exactamente* lo que dicen
las reglas. No dice nada sobre si las reglas son las correctas (eso es T3).

### T2 — Principalidad de las regiones (E2)

> Si existe `Δ` con regiones `R` que tipa `P`, entonces el `Δ` con `R = [primer uso, último uso]`
> también tipa `P`.

**Prueba.** Las reglas de error son **monótonas en `R`**: agrandar una región solo añade pares
`live(κ, p)` y, por tanto, solo puede añadir hechos `error`. Encoger una región no introduce
ningún error nuevo; el único límite inferior es que `R` debe cubrir todos los `used_at(κ, ·)`,
si no el préstamo no alcanzaría a sus usos (eso rompería la solidez, no la completitud).
Por tanto, la región "desde la emisión hasta el último uso" es el **mínimo** del retículo y es
la solución principal (misma idea que Talpin–Jouvelot para inferencia de regiones). ∎

**Consecuencia práctica**: el diseño NLL de Minim ("el préstamo termina en su último uso") no es
una heurística: es **la solución óptima** del sistema. Es lo que permite decir que Minim infiere
regiones *sin* escribirlas y sin perder aceptaciones.

### T3 — Solidez (E3)

> `Aceptar(P) ⟹ Safe(P)` para el núcleo **sin** `rc` y sin memoria compartida mutable.

Es la parte cara. Estructura (Wright–Felleisen + tipado de almacén):

1. **Tipado de configuración**: `⊢ H ; T` (heap bien formado + cada hilo bien tipado).
2. **L1 (invariante de préstamo)**: si `live(κ, p)` y `origin(κ, x, m)`, entonces en `p` el lugar
   de `x` está en `dom H`, `Γ(x) ≠ Moved`, y el permiso de ese lugar es compatible con `m`
   (`uniq` ⟹ permiso exclusivo).
   *Se prueba por inducción sobre la derivación de `live`, usando las reglas `error` como
   contrapositivas: la aceptación garantiza que ningún punto de `R` contiene un acceso
   incompatible.*
3. **L2 (*drop* exacto)**: cada valor no copiable recibe `free` como mucho una vez en cada
   camino. *Inducción sobre el árbol de ámbitos. Aquí es donde la decisión "sin movimientos
   parciales" (A3) paga: el conjunto de `free` depende solo del ámbito léxico, no de banderas
   dinámicas.*
4. **Preservación**: si `⊢ H;T` y `H;T → H';T'`, entonces `⊢ H';T'`.
5. **Progreso**: si `⊢ H;T` y un hilo no es un valor, ese hilo da un paso (nunca se atasca en
   `!ℓ` con `ℓ ∉ dom H` ni en un `free` doble).
6. **Corolario T3**: por inducción, ningún estado alcanzable es `Fault`. ∎

### T4 — Ausencia de carreras (fragmento `spawn`/`await`)

> Si `Aceptar(P)` y `P` usa `spawn`, entonces `P` no tiene carreras de datos.

**Prueba.** La restricción de aislamiento (I5) obliga a que los argumentos de `spawn` se
transfieran (`move`) y a que no haya préstamos vivos ni `rc` al cruzar el `spawn`. Por tanto
las configuraciones de los hilos tienen **conjuntos de lugares disjuntos**. Lema de marco
(*frame*): el tipado de un hilo es invariante frente a los pasos de otro hilo disjunto. Una
carrera exige un lugar común con al menos una escritura; eso contradice la disyunción. ∎

Nota: esta prueba es mucho más barata que la de Rust porque Minim **no admite estado compartido
mutable**: no hay `static mut`, no hay referencias en campos, no hay `rc` en el núcleo. Sin
esas construcciones, la concurrencia no necesita ni *lifetime logic* ni sesiones.

### T5 — Terminación y coste

> El punto fijo se alcanza en `O(|Puntos| · |Préstamos|)` iteraciones y el análisis es local a
> la función.

Punto fijo sobre retículo finito ⟹ terminación. Localidad ⟹ no hay análisis global que probar.

### T6 — Lo que queda fuera del teorema

| Construcción | Estado |
|---|---|
| `rc[T]` / `arc[T]` | Mutación interior: la garantía pasa a ser "*safety* o pánico" (como `RefCell`). Probar esto exige semántica relacional (§9) |
| Fugaz de memoria (`rc` cíclico) | Permitido; "sound" ≠ "sin fugas" |
| `unsafe` / FFI | Fuera del teorema; habría que declarar un prelude de confianza |
| Corrección del compilador | Otro teorema (estilo CompCert/CakeML), fuera de alcance |

---

## 7. Por qué E4 es imposible (y con qué argumento)

> Sea `CoreMin` con su semántica con fallos. El conjunto `{P : Safe(P)}` es indecidible.

**Esbozo.** Dada una máquina de Turing `M` y entrada `w`, se construye `P(M,w)` que simula `M`
sobre `w` y, **si `M` para**, hace algo que la semántica marca como fallo (por ejemplo: toma la
referencia `&x`, `free x`, y luego escribe a través de la referencia). `P(M,w)` es seguro sii
`M` no para sobre `w`. Si `Safe` fuera decidible, se decidiría la parada. ∎

Y además, **este** sistema concreto es incompleto aunque se restringiera a programas seguros: los
testigos están en `docs/SOUNDNESS.md` §6 (p. ej. `swap(var s.a, var s.b)`). Es decir, la
incompletitud de Minim es doble: una estructural (imposible de eliminar) y otra *elegida*
(simplificaciones que quitan sintaxis y análisis).

**Conclusión**: "matemáticamente exacto" solo puede significar T1 (exactitud respecto de las
reglas, *relativa*) o T3 (solidez, *absoluta*). Nunca "acepta exactamente los programas seguros".

---

## 8. Qué obligación genera cada decisión de Minim

| Decisión de diseño | Obligación de prueba | ¿Facilita o complica? |
|---|---|---|
| Modo en la firma, no inferido (A1) | T1 sin la regla "calcular modo del cuerpo"; el índice y la huella son correctos | **simplifica** |
| Sin referencias en campos | No hace falta `Σ` con cotas de vida; no hacen falta *variance* ni `PhantomData`; elimina la *lifetime logic* de RustBelt | **simplifica mucho** |
| Sin movimientos parciales (A3) | L2 por inducción sobre ámbitos, sin banderas de *drop* | **simplifica** |
| Sin closures que escapan (A4) | Capturas acotadas al *frame*: no hacen falta tipos de closure con regiones | **simplifica** |
| Sin `unsafe` | T3 sintáctico basta: no hace falta la parte semántica (Iris) | **simplifica mucho** |
| Sin sobrecarga ni traits dinámicos | La resolución de nombres queda fuera del teorema (elaboración) | **simplifica** |
| Regiones por último uso (NLL) | T2 (principalidad) es un argumento de monotonía | **simplifica** |
| Aislamiento de `spawn` | T4 por disjunción de *frames*, sin sesiones ni `Send`/`Sync` finos | **simplifica** |
| Elisión de préstamos devueltos (A2) | Hay que modelar **temporales** con región propia en T0 y T3 | complica (es el precio de permitirlos) |
| `rc`/`arc` (A6) | Sale del mundo estático: obliga a semántica relacional (§9) | **complica mucho** |
| Exclusividad por dueño, no por campo (A7) | No genera obligación: es incompletitud, se documenta con testigos | neutro |

Lectura: el núcleo de Minim está **diseñado para ser demostrable**. Las tres decisiones que
harían la prueba inviable (referencias almacenables, `unsafe`, estado compartido mutable) están
fuera del núcleo a propósito.

---

## 9. Mecanización: con qué se hace

| Herramienta | Para qué | Precedente |
|---|---|---|
| **Lean 4** o **Isabelle/HOL** | CoreMin + semántica + progreso/preservación + Datalog/punto fijo | Jinja, JavaLight (Isabelle); Cakeml (HOL) |
| **Coq/Rocq + Iris** | Solo si entra `rc`/interior mutabilidad/concurrencia fina | RustBelt (λRust) |
| **F\*** / **Dafny** / **Why3+SMT** | Verificar el **código** del checker (no el modelo) | proyectos de compiladores verificados |
| Modelo ejecutable (*Stacked Borrows* style) | Validación empírica del modelo de alias | Miri / Stacked Borrows / Tree Borrows |
| Fuzzing + *differential testing* | Encontrar *false accepts* barato | fuzzers de compiladores, `rustc` como referencia |

### Hitos, con definición de "terminado"

| # | Hito | Entregable | Terminado cuando | Esfuerzo |
|---|---|---|---|---|
| M0 | CoreMin + semántica | doc §3-4 + interpretador de referencia | 20 casos de `formal/CASES.md` se ejecutan y coinciden | semanas |
| M1 | Reglas Datalog + motor de punto fijo | §5.2 implementado | **T1** demostrado (o al menos: motor validado contra un checker declarativo independiente) | semanas |
| M2 | Principalidad | prueba de monotonía | **T2** demostrado | semanas |
| M3 | Solidez del núcleo | store typing + L1/L2 | **T3** demostrado en prover | meses |
| M4 | Concurrencia | disjunción de frames | **T4** demostrado | meses |
| M5 | `rc`/interior mutabilidad | modelo relacional (Iris) | T3 extendido a `rc` con "pánico o seguridad" | meses-años |

**Esfuerzo realista**: núcleo sin `rc`, con M0-M4 mecanizados, del orden de **1-2 persona-año**.
Con `rc` y concurrencia fina, **3+ persona-año** (RustBelt: 4 autores, ~3 años, y eso que
reutilizaba Iris y solo cubría λRust + librerías). No es un sprint: es una tesis.

### Validación empírica (complementa, no sustituye)

1. **Suite de conformidad** (`formal/CASES.md`): programas que *deben* rechazarse y programas que
   *deben* aceptarse, con la regla que lo justifica.
2. **Pruebas de mutación**: mutar el checker (quitar una regla, invertir una condición) y
   comprobar que algún caso de "debe rechazar" pasa a aceptarse.
3. **Differential testing**: traducir CoreMin aceptado a Rust y compilar con `rustc`; si `rustc`
   lo rechaza, hay un falso aceptado.
4. **Fuzzing de programas** + ejecución en el interpretador instrumentado con el modelo de alias;
   un *false accept* aparecerá como *fault* dinámico.

---

## 10. Bibliografía mínima

- Wright, Felleisen. *A Syntactic Approach to Type Soundness*. 1994. — progreso/preservación.
- Smith, Walker, Morrisett. *Alias Types*. POPL 2000. — tipado de alias con regiones.
- Tofte, Talpin. *Region-based memory management*. 1997. — inferencia de regiones y principalidad.
- Grossman et al. *Region-Based Memory Management in Cyclone*. PLDI 2002.
- Walker. *Substructural Type Systems*. 2005. — linealidad/afinidad.
- Reynolds. *Separation Logic*. LICS 2002. — semántica de memoria mutable con alias.
- Jung, Jourdan, Krebbers, Dreyer. *RustBelt: Securing the Foundations of the Rust Programming
  Language*. POPL 2018. — λRust + *lifetime logic* en Iris.
- Jung, Dang, Kang, Dreyer. *Stacked Borrows: An Aliasing Model for Rust*. POPL 2020.
- Abiteboul, Hull, Vianu. *Foundations of Databases*. 1995, cap. 13. — semántica de Datalog y
  punto fijo mínimo (la base de T1).
- Clarke, Potter, Noble. *Ownership Types for Flexible Alias Protection*. OOPSLA 1998.
- Protzenko, Pottier. *Mezzo: a typed language for safe effectful concurrent programs*. 2013.
