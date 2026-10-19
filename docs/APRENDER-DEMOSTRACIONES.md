# Cómo se demuestran estas cosas (desde cero)

Tutorial para quien nunca ha visto una demostración de este tipo. Al final deberías poder
leer `docs/FORMAL.md` sin que te suene a chino.

## 0. Las tres preguntas, respondidas primero

- **¿Es complejo?** La *idea* no. La *práctica* sí.
- **¿Se entiende en una noche?** Sí: qué se demuestra y por qué, con dos pruebas completas
  a mano. No: hacerlo tú para Minim.
- **¿Hace falta ser un genio?** No. Hace falta precisión y paciencia. El modo de fallar
  habitual no es "no soy listo", es "me salté un paso porque era obvio".

## 1. Qué es una "demostración" aquí

No es resolver un problema famoso. Es un procedimiento de cuatro pasos, siempre el mismo:

1. Definir los objetos con precisión ridícula (**sintaxis**).
2. Definir cómo cambian (**semántica**).
3. Enunciar una propiedad.
4. Demostrarla por **inducción estructural**.

Regla de oro: **cada paso debe estar justificado por una definición o una regla escrita antes.**
Nada de "es obvio". Eso es todo el rigor.

## 2. Paso 1: la sintaxis es una definición inductiva

```
t ::= true | false | if t then t else t          (lenguaje "T")
```

Se lee: *un término `t` es `true`, o `false`, o `if t1 then t2 else t3` donde t1, t2, t3 son
términos*. Con tres reglas se generan infinitos programas. Nada más.

- **Valor** = término que ya no se reduce: aquí `true` y `false`.
- El conjunto generado es el **menor** cerrado por las reglas. Esa minimalidad da el
  **principio de inducción estructural**:

> Si una propiedad vale para `true`, vale para `false`, y vale para `if t1 t2 t3` siempre que
> valga para `t1`, `t2` y `t3`, entonces vale para **todos** los términos.

Ese es el motor del 90 % de estas pruebas.

## 3. Paso 2: semántica de paso pequeño

```
if true  then t2 else t3  →  t2                    (E-IfTrue)
if false then t2 else t3  →  t3                    (E-IfFalse)
        t1 → t1'
────────────────────────────────────────           (E-IfCong)
if t1 then t2 else t3 → if t1' then t2 else t3
```

Vamos a leer esto con lupa: es la pieza que más confunde al principio.

### 3.1 Por qué hace falta definir la semántica

"Este programa nunca falla" no es un enunciado hasta que "ejecutar" está definido con la misma
precisión que la sintaxis. La semántica es **otra definición inductiva**, igual que la de §2:
reglas que generan un conjunto de hechos, en este caso de la forma "`t` se convierte en `t'`".

### 3.2 Dos familias, y por qué elegimos la de paso pequeño

- **Paso grande** (*big-step*): `t ⇓ v`, "`t` se evalúa entero y da el valor `v`".
  ```
  t1 ⇓ true    t2 ⇓ v
  ────────────────────
  if t1 then t2 else t3 ⇓ v
  ```
  Es intuitiva y describe un intérprete, pero colapsa toda la ejecución en un solo juicio. No
  puede decir *dónde* se atascó, ni *un* paso, ni intercalar dos hilos.
- **Paso pequeño** (*small-step*): `t → t'`, "`t` da **un** paso y queda `t'`".

Elegimos paso pequeño por una razón concreta: **progreso y preservación hablan de un solo paso**
(§5). Con paso grande, "existe un paso" no significa nada. Además, los hilos y el *borrow
checker* necesitan razonar paso a paso, y los fallos hay que poder **localizarlos** en el paso
concreto que los produce.

### 3.3 Cómo se lee la notación

```
  premisa₁   premisa₂        las premisas: todo lo que debe cumplirse
──────────────────────       la barra: "si todo lo de arriba, entonces..."
     conclusión              la conclusión: lo que queda justificado
                    (E-Nombre) el nombre de la regla, solo para citarla
```

- **Se lee de arriba abajo, nunca al revés.** La barra es un "si... entonces", no un "si y solo
  si". Si ninguna regla encaja, simplemente no hay paso: eso es estar atascado, no un error.
- **Sin premisas = axioma.** `E-IfTrue` no necesita nada para aplicarse.
- `→` no es una función: es una **relación** entre términos, o sea un *conjunto de pares*. Cada
  regla dice que ciertos pares pertenecen a ese conjunto.
- **Metavariables**: `t`, `t1`, `t2`, `t3` **no son variables del programa**. Son huecos que
  abarcan *cualquier* término. `E-IfTrue` dice: para *cualesquiera* `t2` y `t3`, el par
  `(if true then t2 else t3, t2)` está en `→`. La regla es una plantilla, no un caso particular.

### 3.4 Una derivación completa, dibujada

Queremos el paso de `if (if false then 1 else 2) then a else b`.

Primero aplicamos **E-IfFalse** con `t2 = 1`, `t3 = 2`:

```
                                 ────────────────────────────────  (E-IfFalse)
                                 if false then 1 else 2 → 1
───────────────────────────────────────────────────────────────────────  (E-IfCong)
if (if false then 1 else 2) then a else b → if 1 then a else b
```

El resultado **depende** de una subderivación: la premisa de E-IfCong es a su vez la conclusión
de E-IfFalse. Eso es un **árbol de derivación**. Y como cada premisa es estructuralmente más
pequeña que la conclusión, podemos **inducir sobre la derivación** — no sobre el texto del
programa. Esta es la razón técnica de que las pruebas de §6 induzcan sobre la derivación.

### 3.5 Por qué existe la regla "de congruencia"

Para reducir un subtermo hace falta una regla que suba el resultado hasta arriba. En T hay una
sola posición donde puede ocurrir un paso (la condición del `if`), así que hay una sola regla.
En un lenguaje real no: cada posición de cada construcción necesita la suya, y **el orden de
evaluación es una decisión de la especificación** (Minim lo fija de izquierda a derecha en
`docs/DESIGN.md`), porque decide qué efecto ocurre antes.

Truco estándar para no escribir 15 reglas iguales: los **contextos de evaluación**.

```
F ::= □ | if F then t else t
F[e] → F[e'] cuando e → e'
```

`□` es el agujero; `F[e]` es "`F` con `e` metido en el agujero". Una sola regla comprime todas
las congruencias. Es puro *boilerplate*, y conviene saber que existe para leer la literatura.

### 3.6 Cierre transitivo: de un paso a la ejecución

`→*` es "cero o más pasos", definido con dos reglas:

```
──────────  (refl)                t → t'    t' →* t''
t →* t                            ────────────────────  (paso)
                                  t →* t''
```

`→*` es el *intérprete*: lleva la ejecución de principio a fin. Con esto ya se define:

- **atascado**: `t` no es un valor y **no existe** ningún `t'` con `t → t'`.
- **seguro**: ningún término alcanzable por `→*` desde un programa bien tipado está atascado.

### 3.7 Ojo con estos errores, que son los de todos

1. Confundir las metavariables con variables del programa.
2. Leer la barra como "si y solo si". Es solo "si".
3. Creer que "no hay regla" es un error de ejecución. Es una propiedad **sintáctica**: la
   ausencia de un paso. Que esa ausencia sea imposible es justo el teorema de progreso.
4. Dar por buena la conclusión al usar una regla. La premisa hay que **derivarla**.
5. Creer que `→` reduce "el programa". Reduce una **ocurrencia**; la congruencia explica por qué
   se le atribuye al término entero.
6. Suprimir el orden de evaluación "porque no importa". Importa: es parte de la especificación.

### 3.8 Cuando la memoria entra en escena

Con memoria, un paso puede no dar un término peor, sino **entrar en fallo** (`free` de un
puntero vivo, escribir en algo liberado). `docs/FORMAL.md` §2 modela eso con un **estado de
fallo explícito**: `t → fallo`. Entonces el teorema de seguridad se vuelve "ningún fallo es
alcanzable", y el invariante (§7) es exactamente lo que lo demuestra. Todo lo anterior sigue
aplicando: un fallo es solo un término que aparece del lado derecho de `→`.

### 3.9 Un ejemplo real, paso a paso

Ampliamos T con números y una comparación (las reglas de congruencia son las de §3.5):

```
30 < 50 → true          50 < 30 → false          (según el orden de los números)
t1 < t2 → t1' < t2      cuando t1 → t1'
```

Programa real: *"si el precio es menor que 50, sin descuento; si no, un 10 % menos"*.

```
if 30 < 50 then 30 else 30 * 9 / 10
```

| Paso | Término | Regla aplicada |
|---|---|---|
| 0 | `if 30 < 50 then 30 else 30 * 9 / 10` | — término inicial |
| 1 | `if true then 30 else 30 * 9 / 10` | `30 < 50 → true`, más congruencia |
| 2 | `30` | E-IfTrue |

`30` es un valor: el juego termina. Dos observaciones importantes:

- `30 * 9 / 10` **nunca se toca**. Las reglas de paso pequeño solo reescriben la rama que se
  elige; la otra no se evalúa. Eso *es* el significado de "la rama del `else` no se ejecuta".
- Cada paso lo justifica **una** regla y produce **un** término. Nada de magia.

**Ahora el fallo de verdad**, el que ocurre todos los días:

```
if 30 then 30 else 200
```

¿Encaja con alguna regla? `30` no es `true` ni `false`, y las reglas del `if` solo hablan de
`true`/`false`. **No hay paso.** El término queda encallado, y da igual lo que hubiera después:
la ejecución terminó ahí.

| Lenguaje | `if 30 then ...` |
|---|---|
| Python | Funciona: `30` es "verdadero". Bug silencioso. |
| Rust | Error de compilación: el `if` exige un `bool`. |
| Minim | Igual que Rust: el `if` exige `bool`. |

Ese es el puente con el resto del documento: el tipo `bool` no es un adorno; es exactamente la
condición que hace imposible el atasco de arriba. En forma de teorema:

> Si `t : τ` y ninguna regla encaja en `t`, entonces `t` ya es un valor.

Eso es el **progreso** (§5). Su consecuencia: encallarse solo le pasa a programas que el
compilador ya había rechazado.

El mismo programa, real, en Minim:

```
fn price(p: int) -> int
	if p < 50
		p
	else
		p * 9 / 10
```

`if p` (sin la comparación) **no compila**, porque `p : int` no es `bool`. En Python `if p`
compila y genera un bug; en Minim el compilador hizo gratis el trabajo del teorema.

### 3.10 Cómo leer la comilla: `t1` frente a `t1'`

Esta es la duda número uno al empezar, así que merece su propia sección.

La comilla (prima) **no es un símbolo matemático especial**. Es una forma perezosa de poner un
apodo: significa **"y este es el mismo, después de haber dado un paso"**.

| Símbolo | Se lee | En el juego |
|---|---|---|
| `t1` | la versión **antes** | lo que hay en la pizarra ahora |
| `t1'` | la versión **después** | lo que queda tras aplicar **una** regla |
| `t1 → t1'` | "t1 se convierte en t1-prime" | un turno |

Como con Juan y Jua**n'**: el segundo es el primero, pero ya cambiado. Se podría llamar `u`, pero
entonces habría que recordar qué era `u`; con la comilla se ve a simple vista que son **pareja**.

Leídas en español normal, las tres reglas dicen:

- `E-IfTrue`: *"si veo `if true` con cualquier cosa de preguntas y respuestas, borro el `if`
  entero y dejo la respuesta 1"*.
- `E-IfFalse`: *"igual, pero me quedo con la respuesta 2"*.
- `E-IfCong`: *"si la **pregunta** puede dar un paso, entonces el `if` entero da ese paso con la
  pregunta ya cambiada"*.

`E-IfCong` es la regla que "sube" los cambios de dentro hacia fuera. En palabras: *"lo de dentro
cambió, así que la pizarra cambió"*.

Ejemplo, con `t1 = 30 < 50` y `t1' = true`:

```
       30 < 50 → true               esto es la premisa
───────────────────────────────     t1 = 30<50   t1' = true   t2 = 30   t3 = 200
if 30 < 50 then 30 else 200  →  if true then 30 else 200
```

Y el `→ if true then 30 else 200` de la derecha es exactamente lo mismo que había, **con `t1'`
metido en el hueco de `t1`**. Es una sustitución de huecos, nada más.

Fíjate además en algo que se ve en las reglas: `t2` y `t3` **no tienen comilla** en ningún
sitio. Eso es intencionado: no existe ninguna regla para dar un paso dentro de las respuestas.
Por eso `30 * 9 / 10` nunca se evaluó en el ejemplo del descuento (§3.9): **la rama que no se
elige no se ejecuta**.

### 3.11 Qué significa la flecha `→`

También es una duda universal, porque el mismo dibujo se usa para cosas distintas según el
contexto. En las reglas del juego:

> `t → t'` se lee **"`t` da un paso y queda `t'`"**.

Es una **afirmación**, no una orden. `30 < 50 → true` es una frase que es verdadera o falsa,
igual que `2 + 2 = 4`. No le está mandando nada a nadie. Las reglas del juego son lo único que
puede hacerla verdadera.

¿Y por qué una flecha y no un `=`? Porque **el camino no tiene vuelta**:

```
30 < 50 → true          correcto
true → 30 < 50          no existe ninguna regla así
```

Eso es exactamente lo que aporta la flecha: **dirección, sin regreso**. El `=` va en los dos
sentidos; la flecha solo va hacia adelante.

Cuidado: la flecha **no** es un "si... entonces". El "si... entonces" es la **barra horizontal**
de las reglas; la flecha solo dice "se convierte en".

Y ojo, que el mismo dibujo aparece en otros sitios con otro significado:

| Símbolo | Dónde | Se lee |
|---|---|---|
| `→` | reglas del juego | "da **un** paso y queda" |
| `→*` | ejecución completa (§3.6) | "da **cero o más** pasos y queda" |
| `⇓` | semántica de paso grande (§3.2) | "se evalúa entero y da" |
| `:` | reglas de tipos (§4) | "**tiene** tipo" |
| `⊢` | juicios (§7) | "se puede demostrar que" |
| `->` | código Minim, Rust, etc. | "**devuelve** / es de tipo" |

El último es el que más confunde al principio: en

```
fn price(p: int) -> int
```

la flecha **no** es la del juego. Ahí se lee *"recibe un `int`, devuelve un `int`"*. Es el mismo
dibujo para otra idea: en las reglas es *cambio*, en el código es *tipo del resultado*.

### 3.12 Tabla de símbolos del documento

| Símbolo | Se lee | Ejemplo |
|---|---|---|
| `t`, `t1`, `t2`, `t3` | un término **cualquiera** (hueco) | `t1` = `30 < 50` |
| `t1'` | ese término **después** de un paso | `t1'` = `true` |
| `v` | un **valor** (ya no se reduce) | `30`, `true` |
| `n` | un número | `50` |
| `τ`, `σ` | un **tipo** | `int`, `bool` |
| `Γ` | el **entorno**: qué variables existen y de qué tipo | `Γ = {p : int}` |
| `H` | la **memoria**: qué hay en cada dirección | `H = {1001 : 30}` |
| `P` | el **invariante**: la propiedad que hay que conservar | §7 |
| `□` | el **agujero** de un contexto | `if □ then t else t` |
| `F[e]` | el contexto `F` con `e` **metido en el agujero** | §3.5 |

### 3.13 Vocabulario: cómo se llama cada cosa

```
      premisa₁    premisa₂          ← las PREMISAS (antecedentes, hipótesis)
    ────────────────────────         ← la BARRA (línea de inferencia)
       conclusión                    ← la CONCLUSIÓN (consecuente)
                          (E-IfTrue) ← la ETIQUETA (nombre de la regla)
```

- **Regla de inferencia**: el bloque entero. Es la unidad mínima.
- **Premisas** / **antecedentes** / **hipótesis**: lo de arriba.
- **Conclusión** / **consecuente**: lo de abajo.
- **Línea de inferencia** (o barra): la raya. No tiene nombre matemático propio más allá de eso.
- **Etiqueta**: el nombre a la derecha, solo sirve para citarla.
- **Axioma** (o *esquema de axioma*): una regla **sin premisas**, como `E-IfTrue`.
- **Condición lateral**: un requisito escrito en el texto, del tipo *"cuando `n > 0`"*.
- **Instancia de regla**: el resultado de llenar los huecos de una regla con términos concretos.

Y del resto de la maquinaria:

| Nombre | Qué es | En el juego |
|---|---|---|
| **Juicio** (*judgement*) | una afirmación de la forma `t → t'` | una jugada concreta |
| **Derivación** (*derivation*) | el árbol formado apilando reglas | la explicación de por qué hay jugada |
| **Definición inductiva** | definir un conjunto con reglas | el conjunto de todas las jugadas |
| **Sistema deductivo** (o *cálculo*) | el conjunto de todas las reglas | el libro de reglas entero |
| **Metateoría** (*metatheory*) | los teoremas **sobre** el sistema | "el juego nunca se encalla" |
| **Metateorema** | cada uno de esos teoremas | progreso, preservación, seguridad |

Ese par **teoría / metateoría** es la respuesta corta a "¿cómo se llama todo esto?": la teoría es
el lenguaje y sus reglas; la metateoría son las demostraciones *acerca* de ellas.

### 3.14 Qué matemática estudia esto

No hay una sola: es un cruce de tres o cuatro.

| Rama | Qué aporta | Referencia fundacional |
|---|---|---|
| **Lógica matemática** → **teoría de la demostración** | la forma de escribir reglas con premisas y conclusiones | Gentzen, 1935 (*deducción natural*, *cálculo de secuentes*) |
| **Teoría de tipos** | los tipos como objetos matemáticos; Curry–Howard | Church; Martin-Löf, 1972 |
| **Teoría de retículos y orden** | por qué las definiciones inductivas tienen una solución **mínima** (punto fijo) | Knaster–Tarski; Kleene |
| **Reescritura de términos** (*term rewriting*) | el paso pequeño como relación de reescritura, confluencia y terminación | TeReSe, 2003 |

Y su aplicación a la informática es una asignatura propia:

| Nombre | Qué estudia | Fundador |
|---|---|---|
| **Semántica operacional estructural (SOS)** | definir la ejecución con reglas de inferencia | Plotkin, 1981 |
| **Semántica denotacional** | traducir cada programa a una función matemática | Scott y Strachey, 1970s |
| **Semántica axiomática** | especificar con pre/postcondiciones (Hoare) | Hoare, 1969 |
| **Teoría de lenguajes de programación** (*PL theory*) | todo lo anterior junto, dentro de informática | — |
| **Métodos formales / verificación** | aplicar esto a programas reales | — |

Un dato útil: **el estilo de escritura** que estamos usando (premisas, barra, conclusión) se
llama **deducción natural** y su inventor fue **Gerhard Gentzen** en 1935. No es una notación de
informática: se importó de la lógica. Y la prueba de que las reglas de un lenguaje no se
encallan se llama **soundness** (solidez), que es un **metateorema** de la **semántica
operacional** del lenguaje.

### 3.15 ¿Se lee de arriba abajo o de abajo arriba?

Buena pregunta, y la respuesta es: **depende de para qué estés leyendo**. Son dos cosas distintas
que usan la misma regla.

| Para qué | Dirección | Cómo se llama |
|---|---|---|
| **Entender lo que dice** la regla | arriba → abajo | leer la regla como un "si... entonces" |
| **Construir una derivación** (o una prueba) | abajo → arriba | **búsqueda hacia atrás** / dirigida por el objetivo (*goal-directed*) |

El diagrama de siempre, con la flecha de cada lectura:

```
                      30 < 50 → true
                    ─────────────────        ← esta es la premisa
                    if 30 < 50 then 30 else 200 → if true then 30 else 200
```

- **De abajo arriba (buscar)**: "quiero justificar la línea de abajo; ¿qué regla podría haberla
  producido? La de congruencia. Entonces ahora **debo** justificar su premisa…". Las premisas
  aparecen como **obligaciones** que hay que pagar.
- **De arriba abajo (justificar)**: una vez que la premisa está pagada, la conclusión **queda**
  justificada. El "vale" viaja de arriba hacia abajo.

**La trampa, y es la trampa gorda:** leer de abajo arriba **no** convierte la barra en un "si y
solo si". La conclusión **no** te regala las premisas: te da **deberes**. Si no puedes pagarlos,
no tienes nada. Por eso una regla es una promesa condicional y no una igualdad.

Cómo se usa esto en la práctica:

- **En el juego**: miras el término de la **izquierda** de la flecha y su forma te dice **qué**
  regla aplicar. No hay búsqueda que hacer.
- **En el guardia de tipos (§4)**: quieres comprobar `e : τ`; la **forma de `e`** te dice qué
  regla usar, y de ahí salen las obligaciones sobre sus partes. Por eso el guardia "trabaja de
  abajo hacia arriba": va subiendo por el árbol del programa pidiendo pruebas a los trozos.
  Eso se llama sistema **dirigido por la sintaxis** (*syntax-directed*) y es la razón de que
  comprobar tipos sea rápido y no requiera adivinar nada: **una forma de expresión, una regla**.

Nombres por si te los encuentras:

| Término | Significado |
|---|---|
| **Encadenamiento hacia adelante** (*forward chaining*) | partir de los hechos y ver qué conclusiones salen |
| **Encadenamiento hacia atrás** (*backward chaining*) | partir del objetivo y ver qué obligaciones salen |
| **Búsqueda de pruebas** (*proof search*) | hacer lo segundo sistemáticamente |
| **Dirigido por la sintaxis** (*syntax-directed*) | la forma del objetivo determina la regla; sin adivinar |

### 3.16 ¿Pueden sobrar premisas o reglas sin usar?

Sí, y tiene nombre. Hay que distinguir cuatro situaciones, que se confunden todo el rato:

| Situación | Qué pasa | Cómo se llama | ¿Problema? |
|---|---|---|---|
| Una premisa **siempre** se cumple | se puede borrar sin cambiar nada | premisa **redundante** | no, es solo ruido |
| Una premisa **nunca** se cumple | la regla no se aplica jamás | regla **muerta** | sí, es un error de diseño |
| La regla se puede **demostrar** usando las demás | sobra, pero se deja por comodidad | regla **derivada** | no, es documentación |
| Este juicio ya se prueba por otro camino | esta derivación no la usa, otra sí | derivación **alternativa** | no, es normal |

**La regla de oro, y el error lógico más frecuente:** *"no la he usado en esta derivación"* **no**
significa *"no hace falta"*. Para demostrar que una regla o una premisa sobra **de verdad**, hay
que enseñar un **contraejemplo**: un juicio que **solo** se pueda probar con ella.

Con las tres reglas de §3, ¿sobra alguna? Comprobémoslo con contraejemplos:

- Sin `E-IfCong`, `if (30 < 50) then … else …` no podría dar **ningún** paso. → necesaria.
- Sin `E-IfFalse`, `if false then … else …` se quedaría parado. → necesaria.
- Sin `E-IfTrue`, lo mismo. → necesaria.

Es decir: **las tres son necesarias**, y eso se demuestra enseñando un término que solo ellas
reducen. Eliminar una regla no es una decisión de estilo: cambia el lenguaje.

**Añadir premisas siempre hace la regla más estrecha**, pero con efectos distintos según de qué
regla se trate:

| Regla de… | Añadir una premisa | Efecto |
|---|---|---|
| **Semántica** (el juego) | cambia el **lenguaje**: más términos encallados | cambio de diseño |
| **Tipos** (el guardia) | el guardia rechaza **más** programas | nunca rompe la seguridad; pierde completitud (§4) |

Esa tabla explica por qué el guardia "se puede pasar de estricto" sin peligro: endurecer una
regla de tipos solo puede rechazar de más, nunca dejar entrar un programa malo.

**Y en las demostraciones hay un primo hermano de esto:** el **caso vacío**. En una prueba por
casos sobre las reglas, a veces una combinación es **imposible** y no hay nada que demostrar; se
**descarta**. Descartarlo es en sí una mini-demostración, normalmente con un **lema de inversión**
(mirar la forma del término y ver que esa forma no encaja con las premisas). En los libros
aparece como *"caso imposible"*, *"contradicción"* o *"vacuous case"*. Ejemplo: en la prueba de
progreso, el caso "`t1 : Bool` no es un valor y no da ningún paso" se descarta **por la propia
hipótesis de inducción**.

Buena parte del trabajo real de especificar un lenguaje es exactamente esto: podar reglas y
premisas que se pueden demostrar derivadas. Cuanto más pequeño es el sistema, menos casos tiene
la metateoría (§3.13). En Minim, que no haya dos formas de escribir lo mismo (una forma por
construcción) es justo lo que evita reglas y derivaciones alternativas.

### 3.17 "Esa regla nunca se usa": tres sentidos de "usar"

Es la trampa de §3.16 pisada en vivo, así que merece su propia sección. En el ejemplo del
descuento con precio 30, el término `if false then 30 else 200` no aparece por ningún lado. ¿Es
entonces `E-IfFalse` innecesaria? **No.** La palabra "usar" significa tres cosas distintas:

| Sentido de "usar" | ¿Aparece `if false then …`? | ¿Se usa `E-IfFalse`? |
|---|---|---|
| En **esta ejecución** concreta (precio 30) | no | no |
| Para **definir el lenguaje** | sí: es un término del lenguaje | sí |
| Al **comprobar tipos** | sí: el guardia inspecciona ambas ramas | sí (`T-False`) |

### El contraejemplo: el mismo programa, precio 80

```
if 80 < 50 then 80 else 80 * 9 / 10
```

| Paso | Término | Regla |
|---|---|---|
| 0 | `if 80 < 50 then 80 else 80 * 9 / 10` | — |
| 1 | `if false then 80 else 80 * 9 / 10` | `80 < 50 → false` |
| 2 | `80 * 9 / 10` | **E-IfFalse** |

Ahí está: el **mismo programa** (`fn price(p: int)`), con otra entrada, usa exactamente la regla
que antes sobraba. Y ahora la que sobra es `E-IfTrue`.

Frase para recordar: **en cada ejecución concreta sobra una de las dos reglas del `if`; en el
conjunto de todas las ejecuciones, ninguna sobra.**

### La razón profunda: la ejecución **fabrica** términos

`if false then 80 else 80 * 9 / 10` **no está escrito en el programa**. Nadie lo escribió. Aparece
como resultado del primer paso. Por eso las reglas no hablan de "los programas que uno escribe",
sino de **todos los términos**: la ejecución crea formas nuevas, y el lenguaje tiene que saber
moverse en ellas.

Esa es también la razón de que las pruebas de §6 sean sobre términos **arbitrarios** y no sobre
programas completos: si la semántica debe cubrir todo término alcanzable, el teorema también.

### La asimetría lógica (apúntala)

- Para demostrar que una regla **es necesaria**: basta **una** (∃) — un testigo. Aquí, `price(80)`.
- Para demostrar que una regla **sobra**: hace falta un argumento sobre **todas** (∀) — no vale
  ninguna cantidad de ejemplos.

Por eso "no la he usado" nunca puede cerrar el asunto, y "aquí está el caso que la usa" siempre lo
cierra.

### Y ojo: tu intuición es correcta en otro trabajo distinto

En un **optimizador**, "esta rama nunca se usa" es oro: *constant folding* y *eliminación de
código muerto* borran exactamente lo que se puede demostrar inalcanzable, programa a programa.
Son dos trabajos distintos y ambos legítimos:

| Trabajo | Objetivo | "Nunca se usa" significa |
|---|---|---|
| **Definir el lenguaje** | cubrir **todos** los términos | nada: la regla sigue siendo necesaria |
| **Optimizar un programa** | hacer **este** programa más rápido | borrar esa rama del programa |

## 4. Paso 3: el sistema de tipos es una *condición*, no la demostración

```
──────────  (T-True)                     ──────────  (T-False)
true : Bool                              false : Bool

 t1 : Bool   t2 : Bool   t3 : Bool
────────────────────────────────────     (T-If)
if t1 then t2 then t3 : Bool
```

Un sistema de tipos es una máquina que dice sí o no. Distinción clave: **el sistema de tipos no
es la prueba**; es una condición comprobable que *resulta ser suficiente* para la seguridad. La
prueba demuestra esa suficiencia.

## 5. Paso 4: progreso y preservación

- **Progreso**: si `t : Bool` y `t` no es un valor, existe `t'` con `t → t'`. (Nunca se atasca.)
- **Preservación**: si `t : Bool` y `t → t'`, entonces `t' : Bool`. (El tipo no cambia.)

**Teorema de seguridad** (corolario): si `t : Bool`, toda ejecución es una cadena de términos
bien tipados y ninguno se atasca. Se demuestra por inducción sobre el número de pasos, usando
progreso y preservación. La seguridad **no** se demuestra directamente: se demuestra que esas
dos propiedades se mantienen.

## 6. Una prueba completa (preservación para T)

> Si `t : Bool` y `t → t'`, entonces `t' : Bool`.

Inducción sobre la derivación de `t → t'`; hay tres casos, uno por regla:

- **E-IfTrue**: `t = if true then t2 else t3` y `t' = t2`. Como `t : Bool`, la única regla
  aplicable a `if` es T-If, que exige `t2 : Bool`. Por tanto `t' : Bool`. ∎
- **E-IfFalse**: simétrico. ∎
- **E-IfCong**: `t = if t1 then t2 else t3` con `t1 → t1'` y `t' = if t1' then t2 else t3`.
  Por T-If: `t1 : Bool`, `t2 : Bool`, `t3 : Bool`. Por **hipótesis de inducción** sobre la
  subderivación `t1 → t1'`: `t1' : Bool`. Aplicando T-If otra vez: `t' : Bool`. ∎

Eso es una demostración real y completa. No falta nada. Y ya has visto la estructura de todas
las demás: **casos + reglas + hipótesis de inducción**.

Progreso es igual, pero induciendo sobre la derivación de tipado:

> Si `t : Bool`, entonces `t` es un valor o existe `t'` con `t → t'`.

- T-True / T-False: es un valor. ∎
- T-If: `t = if t1 t2 t3` con `t1 : Bool`. Por hipótesis de inducción sobre `t1`: o es `true`
  (E-IfTrue aplica), o es `false` (E-IfFalse aplica), o `t1 → t1'` (E-IfCong aplica). ∎

## 7. Dónde aparece la dificultad de verdad: la memoria

Hasta aquí el tipo **resumía todo** lo que hacía falta saber del término. Con memoria, no:

```python
let v = [1, 2, 3]
let r = &v
drop(v)
print(r[0])        # r : &int es correcto... y el entero ya no existe
```

`r : &[int]` dice a qué tipo apunta, **no** si el objeto sigue vivo. El sistema de tipos de
arriba no distingue esto del caso correcto, así que progreso falla y no hay teorema.

La solución es la idea central de todo lo que viene después: **llevar una segunda afirmación
junto al tipado**, sobre el estado de la memoria.

```
⊢ H ; t : τ      "t tiene tipo τ Y la memoria H cumple el invariante P"
```

- `H` es la memoria (mapa dirección → valor).
- `P` es el **invariante**: la propiedad que hay que descubrir y que hay que demostrar que
  cada paso conserva.

Todo el arte está en elegir `P`. Ahí es donde la investigación lleva 30 años.

## 8. Un *borrow checker*, contado como una biblioteca

- La memoria es una biblioteca; cada libro tiene **un dueño** (`let`/`var`).
- Prestar un libro (`&v`) no cambia el dueño.
- Escribir en un libro = mutar; quemar un libro = liberar memoria (`drop`).
- **Invariante**: (a) ningún lector tiene un libro quemado; (b) nadie escribe en un libro
  mientras tenga lectores.
- La política del bibliotecario ("puedes prestar, pero mientras esté prestado no puedes
  escribir ni quemar") es el **sistema de tipos**.
- La demostración es probar que la política implica el invariante tras **cada** acción.

El problema real: la política debe comprobarse **localmente**, sin saber qué hará el programa
después. De ahí la **región**: "este préstamo va desde aquí hasta la última vez que se use esa
referencia". Con eso, comprobar el invariante es mirar un intervalo.

Los cinco invariantes de `docs/FORMAL.md` §3 son literalmente esto; L1 es (a) y L2 es
"cada libro se quema exactamente una vez".

## 9. La escalera de dificultad (y por qué costó 30 años)

| Peldaño | Qué añade | Herramienta | Año |
|---|---|---|---|
| 1 | Cajas, sin punteros | Progreso + preservación | 1994 |
| 2 | Variables | Lema de sustitución | clásico |
| 3 | Referencias y almacén | Tipado de almacén | 1997 |
| 4 | Alias con regiones | *Alias Types*, Cyclone | 2000-2002 |
| 5 | Heap con alias mutables | Lógica de separación | 2002 |
| 6 | Propiedad + vidas | Ownership types, λRust/RustBelt | 1998/2018 |
| 7 | Hilos | *Framing* / disjunción | 2000s |
| 8 | Definir "comportamiento indefinido" | Stacked/Tree Borrows | 2020+ |

La idea **no cambia** en ningún peldaño. Lo que crece es el número de casos y lo sutil que se
vuelve el invariante.

## 10. ¿Y en un ordenador?

Asistentes de prueba (**Coq/Rocq**, **Lean 4**, **Isabelle/HOL**): las definiciones y las
pruebas se escriben como un programa, y el asistente verifica cada paso. `Admitted` (Coq) o
`sorry` (Lean) significa "debo esta prueba". Curiosamente: *el asistente no piensa*, y si está
mal, el error suele ser humano.

Esquema (ilustrativo, no verificado aquí):

```
inductive T   : Type  | ttrue | tfalse | ite (t1 t2 t3 : T)
inductive Paso : T → T → Prop  | ifTrue | ifFalse | ifCong (h : Paso t1 t1')
inductive Tip  : T → Prop      | ttrue | tfalse | ite (h1 h2 h3 : Tip _)

theorem preservacion : Paso t t' → Tip t → Tip t' := by
  intro h ht
  induction h <;> cases ht <;> assumption
```

## 11. Cuánto se tarda de verdad

| Etapa | Contenido | Tiempo |
|---|---|---|
| Noche 1 | Este documento entero, con las dos pruebas escritas a mano | 1-2 h |
| Semanas | TAPL caps. 3, 8, 9, 11 (o Software Foundations, *Logical Foundations*) | 15-40 h |
| Meses | Añadir memoria: tipado de almacén, *Alias Types*, Cyclone | 40-100 h |
| Después | RustBelt (estructura, no los detalles de Iris) | investigación |

## 12. Ejercicios (con solución abreviada)

1. Añade `not t` a T (sintaxis, reglas de paso, regla de tipos) y demuestra preservación.
   *Solución*: caso nuevo `not true → false`, `not false → true`, `not t → not t'`; la prueba
   añade tres casos idénticos en forma a los anteriores.
2. Demuestra progreso para T. *Solución*: los dos casos de arriba.
3. Encuentra un término de T bien tipado y atascado. *Solución*: no existe; ese es exactamente
   el contenido del teorema de progreso.
4. Añade `0`, `succ t`, `iszero t` **sin** cambiar las reglas de tipos. ¿Qué pasa?
   *Solución*: `if 0 then a else b` es sintácticamente válido y está atascado. Hay que añadir
   reglas de tipos (los enteros son de tipo `Int`, y T-If exige `Bool` en la condición) y un
   caso nuevo en progreso. Moraleja: **la seguridad es "no hay términos atascados", y cada
   construcción nueva obliga a tocar el invariante**.
5. Añade variables y escribe el **enunciado** del lema de sustitución (sin probarlo).
   *Solución*: si `Γ, x : τ ⊢ t : σ` y `Γ ⊢ v : τ` entonces `Γ ⊢ t[x := v] : σ`. Es el 80 % de
   una prueba de preservación con variables.
6. (Difícil) Añade `alloc`, `!r` y `free` al lenguaje con referencias y averigua qué invariante
   sobre `H` hace falta para que progreso vuelva a ser cierto. *Solución*: "todo puntero vivo
   apunta a una dirección de `H`" — y a continuación hay que decidir *qué es un puntero vivo*,
   que es el problema del *borrow checker*.

## 13. Lecturas, por dificultad

1. **TAPL** (Pierce), caps. 1-9: el mejor punto de entrada. Ejercicios, con lápiz.
2. **Software Foundations**, *Logical Foundations*: la misma materia, en Coq, gratis.
3. *A Syntactic Approach to Type Soundness* (Wright y Felleisen, 1994): el artículo del §5-6.
4. *Alias Types* (2000) y *Region-Based Memory Management in Cyclone* (2002): el peldaño 4.
5. *RustBelt* (2018): el estado del arte; lee la introducción y la estructura, no Iris.

---

## 14. Cómo se usa todo esto para demostrar el *borrow checker* de Minim

Esta es la sección que cierra el círculo: cada pieza del documento aparece aquí con su nombre en
el plan formal del proyecto (`docs/FORMAL.md`).

### 14.1 Antes de nada: "infalible" tiene dos sentidos, y solo uno es demostrable

| Sentido | Enunciado | ¿Demostrable? |
|---|---|---|
| **Solidez** (nunca deja pasar un programa malo) | `Aceptar(P) ⟹ Safe(P)` | **Sí** (T3) |
| **Completitud** (nunca rechaza un programa bueno) | `Safe(P) ⟹ Aceptar(P)` | **No** (Rice + diagonalización) |

La segunda es imposible, y no por falta de esfuerzo: **ningún** checker decidible acepta
exactamente los programas seguros (§3.16, y `docs/FORMAL.md` §7 para el argumento de la máquina
de Turing). Lo máximo defendible es:

> Nunca deja pasar un programa malo (**absoluto**), y rechaza solo unos pocos programas buenos
> conocidos y documentados (**relativo**).

Esa es la frase "infalible" que sí se puede demostrar. Cualquier otra es mentira.

### 14.2 Cada cosa aprendida, con su nombre en Minim

| Lo aprendido | En Minim | Documento |
|---|---|---|
| Definición inductiva de la sintaxis (§2) | **CoreMin**, el núcleo que se demuestra | `FORMAL.md` §3 |
| Semántica de paso pequeño con estado (§3) | `H ; T`, con **fallos explícitos**: `!ℓ` con `ℓ ∉ dom H`, `free` doble, escritura sin permiso | `FORMAL.md` §4 |
| El sistema de tipos es una condición (§4) | reglas de préstamo `Γ ; Δ ; Σ ⊢ e : τ` | `FORMAL.md` §5.1 |
| El invariante (§7) | **I1–I5** (dueño único, préstamo vivo, exclusividad, *drop* exacto, aislamiento) y **L1–L2** | `SOUNDNESS.md` §3, `FORMAL.md` §6 |
| Progreso + preservación (§5) | **T3**, los pasos 4 y 5 de su prueba | `FORMAL.md` §6 |
| Punto fijo mínimo y Knaster–Tarski (§3.14) | reglas en **Datalog**; aceptar = no derivar `error` | `FORMAL.md` §5.2 |
| Imposibilidad por diagonalización (§3.16) | **E4 es imposible** | `FORMAL.md` §7 |
| Casos vacíos y lemas de inversión (§3.16) | parte pendiente de T3 | — |
| El corpus de conformidad | **23 casos**: 11 a rechazar, 2 rechazados por incompletitud, 10 a aceptar | `formal/CASES.md` |

### 14.3 La receta, en seis pasos

**Paso 1 — Extraer el núcleo y probar que no cambia el significado (T0).** No se demuestra sobre
las 29 palabras clave de la superficie: se demuestra sobre ~15 construcciones (CoreMin). Hace
falta un teorema de **fidelidad**: la traducción de superficie a núcleo es una simulación en
ambos sentidos. Sin T0, demostrar CoreMin no dice nada de Minim.

**Paso 2 — Definir la semántica con fallos explícitos y escribir `Safe(P)`.** Igual que en §3: sin
esto, "infalible" no es un enunciado. Aquí se decide que hay **permisos** en el heap
(`shr(n)`, `uniq`), de modo que "escribir sin permiso" sea un **fallo dinámico**, y que la
seguridad sea un teorema *sobre* la semántica y no una definición circular.

**Paso 3 — Escribir el guardia de forma declarativa (Datalog).** El checker no se define con un
algoritmo, sino con **reglas** (`live`, `uniq`, `error`). Aceptar ≜ no derivar `error`.

**Paso 4 — Demostrar que el algoritmo hace exactamente lo que dicen las reglas (T1) y que las
regiones inferidas son las óptimas (T2).** T1 es *el* resultado bonito y barato: el algoritmo es
un punto fijo mínimo de Datalog, y el punto fijo mínimo coincide con el conjunto de hechos
derivables (teoría estándar de bases de datos). Aquí es donde sirve el §3.14. T2 dice que "el
préstamo termina en su último uso" **no es una heurística**: es la solución mínima del sistema.

**Paso 5 — Demostrar la solidez (T3), que es la parte cara.** Es *exactamente* el §5 y el §7:
tipado de configuración `⊢ H ; T`, los invariantes I1–I5 como hipótesis, **preservación** (cada
paso conserva el tipado y los invariantes) y **progreso** (ningún hilo se atasca), y el corolario
por inducción sobre los pasos: **ningún estado alcanzable es un fallo**. L1 ("todo préstamo vivo
apunta a memoria viva") se prueba por inducción sobre la derivación de `live`, usando las reglas
`error` como contrapositivas.

**Paso 6 — Añadir la concurrencia (T4) y acotar lo que queda fuera (T6).** T4 sale barato por un
**lema de marco**: si los hilos tienen lugares disjuntos, el tipado de uno es invariante frente a
los pasos del otro. Y T6 declara honestamente lo que el teorema **no** cubre: `rc`/`arc`, `unsafe`,
fugas de memoria y la corrección del propio compilador.

### 14.4 Los teoremas, en una línea cada uno

| | Enunciado | Coste |
|---|---|---|
| **T0** | la elaboración superficie→núcleo preserva el significado, en ambos sentidos | tedioso, mecánico |
| **T1** | el checker acepta **⟺** las reglas no derivan `error` | semanas |
| **T2** | si existe una asignación de regiones válida, la de "último uso" también | semanas |
| **T3** | aceptar **⟹** ningún fallo alcanzable (solidez) | **meses** |
| **T4** | aceptar **⟹** sin carreras de datos | semanas |
| **T5** | el punto fijo se alcanza en `O(|Puntos| · |Préstamos|)` y el análisis es local | días |
| **T6** | lo que queda **fuera**: `rc`, `unsafe`, fugas, compilador | — |
| **E4** | aceptar **⟺** ser seguro: **imposible** | — |

Ese es el sentido de "no se demuestra *el borrow checker*: se demuestran siete cosas pequeñas y
encadenadas".

### 14.5 Por qué Minim se puede demostrar y Rust casi no

Cada decisión de diseño del lenguaje **elimina una obligación de prueba**:

| Decisión de Minim | Obligación que evita |
|---|---|
| Sin referencias almacenables en campos | evita la *lifetime logic* de RustBelt: no hacen falta cotas de vida en `Σ` |
| Sin `unsafe` | la prueba es **sintáctica**; no hace falta Iris ni semántica relacional |
| Sin estado compartido mutable | la concurrencia no necesita `Send`/`Sync` finos ni sesiones |
| Sin movimientos parciales (A3) | L2 (*drop* exacto) se prueba por ámbitos, sin banderas dinámicas |
| El modo (`shr`/`uniq`/`move`) va en la **firma**, no se infiere | el índice y la huella (*hash*) son correctos sin analizar cuerpos |
| Regiones por último uso | T2 es un argumento de monotonía, no una búsqueda |

Lo que **complica** la prueba, y hay que pagarlo: los temporales y la elisión de préstamos (A2),
y sobre todo `rc`/`arc` (A6), que sacan el lenguaje del mundo estático.

### 14.6 Cómo se comprueba que la demostración está bien

1. **Mecanización.** Se escriben las definiciones y las pruebas en un asistente (**Coq/Rocq**,
   **Lean**, **Isabelle**). El asistente verifica cada paso; un `Admitted` es deuda declarada
   (§10). Los hitos M0–M5 están en `FORMAL.md` §9.
2. **Validación empírica.** El corpus `formal/CASES.md` (23 casos) no es una prueba, es una red de
   seguridad: si algún día la implementación acepta R1–R11 o rechaza A1–A10, hay un bug. Y los dos
   casos de incompletitud (R12, R13) están ahí **a propósito**, como testigos de que rechazamos
   programas seguros: si algún día se aceptan, el diseño cambió.

Las dos cosas son complementarias y ninguna sustituye a la otra: los tests no demuestran nada para
*todos* los programas, y la prueba no detecta un error de implementación.

### 14.7 El enunciado final que sí se puede defender

> Si el checker de Minim acepta un programa `P`, entonces **ninguna** ejecución de `P` accede a
> memoria liberada, libera dos veces, usa un valor movido ni tiene carreras de datos.
>
> Además, sabemos **exactamente** qué programas seguros rechaza (los testigos R12 y R13), y
> sabemos que **ningún** checker decidible puede hacerlo mejor (Rice).

Eso —y no otra cosa— es lo que significa "matemáticamente infalible" para un *borrow checker*.

---

## 15. ¿Por qué la demostración no cubre todos los programas buenos?

Porque hay **tres razones distintas** que se confunden todo el rato. Una es imposible de evitar,
otra la elegimos nosotros, y la tercera es que esos programas ni siquiera entran en el
enunciado del teorema.

| Tipo | Qué pasa | ¿Evitable? | Ejemplo |
|---|---|---|---|
| **Estructural** | el conjunto de programas seguros **no es decidible** | no (teorema) | cualquier análisis de flujo |
| **Elegida** | simplificamos el lenguaje y perdemos aceptaciones | sí, a cambio de coste | `v.push(v.len)` |
| **Fuera de alcance** | el teorema no habla de ese fragmento | — | `rc`, `unsafe`, FFI |

### 15.1 La imposible: nadie puede saber si un programa es seguro

Ya está en §7 de `docs/FORMAL.md`, y es el argumento de diagonalización de §3.16 puesto a
trabajar: dado que "¿es seguro `P`?" es una pregunta indecidible, **ningún** checker que siempre
termine puede aceptar exactamente los programas seguros. Siempre habrá programas seguros que
rechaza. Eso no es un defecto de Minim: es un teorema sobre **todos** los checkers posibles,
incluido el de Rust.

Analógicamente: un médico no puede certificar *"nunca te romperás un hueso"*. Solo puede
certificar una **condición suficiente**: *"tus huesos están sanos hoy y tu dieta los mantiene
fuertes"*. La condición es comprobable; la verdad completa es indemostrable. Un checker de tipos
es exactamente eso: una condición suficiente, comprobable, que **garantiza** (no "equivale a") la
seguridad.

### 15.2 La elegida: es nuestro intercambio de diseño

Esta es la lista de `docs/SOUNDNESS.md` §6, traducida: **programas seguros que rechazamos a
propósito**, cada uno a cambio de eliminar una prueba o una sintaxis entera.

| Programa seguro que rechazamos | Por qué es seguro | Qué nos ahorra rechazarlo | En Rust |
|---|---|---|---|
| `swap(var s.a, var s.b)` (R13) | son **campos distintos**: direcciones distintas | exclusividad **por dueño** en vez de por campo: no hace falta análisis por lugar | sí (por campo) |
| `v.push(v.len)` (R12) | primero se lee `len`, luego se muta | sin *two-phase borrows*: no hay que aplazar la activación del préstamo único | sí |
| `type Iter  cur: &[int]` | el iterador es válido mientras viva el dueño | **sin referencias almacenables** ⇒ sin `'a`, sin *variance*, sin *lifetime logic* | sí |
| `let x = b.data` dejando `b` medio vivo | solo se movió un campo | **sin movimientos parciales** ⇒ sin *drop flags* | sí (*drop flags*) |
| devolver una closure que captura un local | la captura vive en el *heap* | **sin closures escapantes** ⇒ sin tipos de closure con regiones | sí |
| `fn get(d: map[str,int], k: str) -> &int` | el préstamo sale del parámetro, es válido | sin `'a` en firmas: solo **elisión** | sí |

La frase que resume el intercambio, ya en `docs/SOUNDNESS.md` §6:

> Cada fila elimina una prueba o una sintaxis. Es el intercambio central del diseño: **menos tokens
> y menos análisis a cambio de rechazar más programas seguros.**

### 15.3 La tercera: ni siquiera están en el teorema

`rc`/`arc`, `unsafe`/FFI y las fugas de memoria **no** son programas "rechazados": están **fuera
del enunciado de T3** (`FORMAL.md` §6 T6). Para `rc`, la garantía pasa a ser "*safety* o pánico"
(como `RefCell`); para `unsafe` haría falta un prelude de confianza. No es incompletitud: es
alcance.

### 15.4 Por qué aceptamos ese precio

Tres razones, y las tres son de ingeniería:

1. **Un falso rechazo se ve; un falso acepto no.** El compilador dice "no" en la cara, y hay *workaround*
   (reescribir el código). Una aceptación incorrecta es un *use-after-free* silencioso en
   producción. Errar de más es la dirección **barata** de errar.
2. **El coste se paga en tokens.** Reconocer `v.push(v.len)` exige *two-phase borrows*; admitir
   referencias en campos exige `'a` en las firmas. En un lenguaje diseñado para gastar los mínimos
   tokens (§1 del README), esas construcciones cuestan lo que ahorran.
3. **Menos mecanismos = más demostrable.** Las seis filas de §15.2 son exactamente las seis
   obligaciones de prueba que `FORMAL.md` §8 dice que **no** tenemos.

### 15.5 Regla de disciplina: toda incompletitud va documentada

Una incompletitud es aceptable solo si (a) tiene **nombre**, (b) tiene un **testigo ejecutable** en
`formal/CASES.md`, y (c) tiene un *workaround* documentado. Por eso R12 y R13 están **fijados en el
corpus como casos que deben fallar**: si algún día el checker los acepta, el test se pone rojo y
hay que decidir conscientemente si el diseño cambia.

Así la incompletitud deja de ser un accidente y pasa a ser **especificación**. Un lenguaje con la
lista de sus propios rechazos escritos es más honesto que uno que promete "exacto".

### 15.6 Y lo importante: esto **no** debilita la demostración

Punto lógico que hay que dejar claro:

> T3 dice `Aceptar(P) ⟹ Safe(P)`. Rechazar **más** programas hace T3 **más fácil** de probar, no
> más débil.

La incompletitud solo debilita la **utilidad**, nunca la **seguridad**. La dirección de la
implicación es sagrada: por muchos programas buenos que rechacemos, el teorema sigue siendo
absolutamente verdadero para todo lo que acepta. Es la misma asimetría de §3.17: para romper la
solidez basta **un** programa malo aceptado (∃); para romper la utilidad basta **un** programa
bueno rechazado (∃). Pero solo lo primero sería un fallo; lo segundo es un precio.

---

## 16. ¿Qué se considera un programa "seguro"?

### 16.1 Es una **definición**, no un descubrimiento

No hay una noción absoluta de "seguro" esperando a ser descubierta. Se **elige**, y se escribe en
la semántica:

> **`Safe(P)`** ≜ ninguna ejecución de `P` alcanza un **fallo**.

Y "fallo" se define como un estado concreto dentro de la semántica (§3.8). Es la misma jugada que
en el juego: nosotros decidimos **qué finales cuentan como derrota**. Elegida esa lista, "seguro"
es una propiedad matemática perfectamente precisa.

Truco técnico: los fallos son **explícitos** en la semántica (`docs/FORMAL.md` §4). No son "cosas
raras que a veces pasan"; son configuraciones que el cálculo de pasos alcanza o no alcanza. Así
"seguro" se convierte en una pregunta de **alcanzabilidad**: ¿es `fault` alcanzable?

### 16.2 La lista cerrada de fallos de Minim

| Fallo | Cuándo | Nombre |
|---|---|---|
| leer `!ℓ` con `ℓ ∉ dom H` | memoria liberada (o nunca asignada) | *use-after-free* |
| escribir en un lugar **sin permiso exclusivo** | otro tiene el préstamo vivo | violación de exclusividad |
| `free ℓ` con `ℓ ∉ dom H` | ya se liberó | doble liberación |
| usar `x` con `Γ(x) = Moved` | después de `move x` | uso tras mover |
| dos hilos tocan el mismo lugar y uno escribe | fragmento `spawn` | carrera de datos |

Esa lista es **todo**. No hay una sexta casilla escondida. Si un programa no alcanza ninguna de
esas cinco cosas, es seguro — aunque sea lento, inútil o esté mal.

### 16.3 Lo que NO es seguridad

Aquí es donde casi todo el mundo se pierde. "Seguro" es una propiedad **pequeña y precisa**:

| "Seguro" ≠ | Por qué | ¿Se puede conseguir? |
|---|---|---|
| **correcto** (hace lo que querías) | eso necesita *especificaciones*: otra matemática (Hoare, refinamiento) | sí, pero es otro trabajo |
| **termina** | indecidible, y Minim es Turing-completo | no se promete |
| **sin fugas de memoria** | `sound ≠ sin fugas` (`SOUNDNESS.md` §5) | se podría, con más análisis |
| **sin errores** | en Minim un error es un **valor** (`T!`, `or`, `?`), no un fallo | devolver `err("boom")` es **seguro** |
| **sin pánicos** | un pánico es un fallo *anunciado* y controlado | — |

La analogía: la seguridad vial garantiza que **no te mates en el viaje**. No garantiza que llegues
a tu destino, ni que no te equivoques de carretera, ni que no te quedes sin gasolina. Es una
propiedad pequeña, y precisamente por ser pequeña se puede **demostrar**.

### 16.4 Seguro = sobre **TODAS** las ejecuciones

`Safe(P)` habla de **todas** las entradas y **todos** los entrelazados posibles. Consecuencia
directa —y es la asimetría de §3.17 otra vez—:

- Un **test que falla** demuestra que `P` **no** es seguro (basta ∃).
- Ninguna cantidad de tests demuestra que `P` **es** seguro (hace falta ∀).
- El checker es la vía práctica: una **condición suficiente**, comprobable, y por eso se puede
  aceptar `P` sin probar todos sus infinitos recorridos.

### 16.5 Las dos maneras de conseguir seguridad

| Vía | Cómo | Coste | Ejemplos |
|---|---|---|---|
| **En ejecución** | comprobaciones al vuelo: recolector de basura, refcount, comprobación de índices | coste en **cada operación** del programa | Python, Java, Go, `rc` en Minim |
| **En compilación** | reglas estáticas | **rechaza** programas seguros; coste **cero** al ejecutar | Rust, Minim (núcleo) |

Minim usa la primera vía **solo** donde la segunda no llega: `rc`/`arc`, cuya garantía es
"*safety* o pánico" (`FORMAL.md` §6 T6).

### 16.6 Cómo encaja en el teorema

- **`Safe(P)`** = la definición de esta sección, sobre la semántica. **No es decidible** (§15.1).
- **`Aceptar(P)`** = la condición estática (las reglas de préstamo). Es decidible.
- **T3** dice: `Aceptar(P) ⟹ Safe(P)`. Es decir: la condición decidible **implica** la propiedad
  indecidible. Ahí está toda la jugada del diseño.

El arte de diseñar un *borrow checker* es elegir una condición suficiente que (a) se compruebe
rápido, (b) no rechace demasiado y (c) se pueda demostrar. **Minim apuesta fuerte por (a) y (c), y
paga en (b).**

---

## 17. Ejemplos reales: programas **seguros** que Rust rechaza

Rust no está libre de §15.2: también es incompleto, y sus propios desarrolladores lo documentan
(*"sabemos que este programa es seguro y le decimos que no"*). Esto no es una crítica: es la
prueba de que el fenómeno es **estructural**, no un descuido de Minim.

### 17.1 Los casos, comprobados y reproducibles

Están en `formal/rustcases/`, con un script que los compila con el `rustc` instalado:

```
sh formal/rustcases/run.sh
```

Resultado real (rustc 1.92.0-nightly, `--edition 2021`):

```
RECHAZA  a_disjoint_index.rs    error[E0499]: cannot borrow `v` as mutable more than once
RECHAZA  b_polonius3.rs         error[E0499]: cannot borrow `*map` as mutable more than once
RECHAZA  c_slice_two.rs         error[E0499]: cannot borrow `v` as mutable more than once
ACEPTA   d_fields_ok.rs
ACEPTA   e_two_phase_ok.rs
RECHAZA  f_selfref.rs           error[E0597]: `h.data` does not live long enough
RECHAZA  g_lending.rs           error[E0499]: cannot borrow `it` as mutable more than once
ACEPTA   h_split_ok.rs
ACEPTA   i_gdm_ok.rs
--- motor declarativo (Datalog), nightly:
ACEPTA   b_polonius3.rs         (con -Zpolonius)
```

Todos los ficheros `.rs` son **programas seguros**: ninguna de sus ejecuciones puede acceder a
memoria liberada, ni liberar dos veces, ni tener carreras. Los `RECHAZA` son **falsos rechazos**
(con una excepción declarada, `f_selfref.rs`, ver §17.5).

### 17.2 El más pequeño: dos índices distintos

```rust
let mut v = vec![1, 2, 3];
std::mem::swap(&mut v[0], &mut v[1]);
```

```
error[E0499]: cannot borrow `v` as mutable more than once at a time
3 |     std::mem::swap(&mut v[0], &mut v[1]);
  |     --------------      -          ^ second mutable borrow occurs here
  |     |                   |
  |     |                   first mutable borrow occurs here
  = help: use `.split_at_mut(position)` to obtain two mutable non-overlapping sub-slices
```

Es obviamente seguro: `v[0]` y `v[1]` son **direcciones distintas**. Pero `v[0]` y `v[1]` pasan
ambos por `&mut v`, y el checker ve **un mismo préstamo** dos veces. Es el problema de
**granularidad**: el préstamo es sobre `v` entero, no sobre la posición.

Y aquí está la prueba de que el programa seguro **no se puede escribir de otra forma**: para poder
hacerlo, la biblioteca estándar tuvo que añadir dos funciones, y **las dos están implementadas con
`unsafe` por dentro**:

```
core/src/slice/mod.rs:2086:  pub const unsafe fn split_at_mut_unchecked(...)
core/src/slice/mod.rs:4701:  pub unsafe fn get_disjoint_unchecked_mut(...)
core/src/slice/mod.rs:4778:  unsafe { Ok(self.get_disjoint_unchecked_mut(indices)) }
```

Es decir: `h_split_ok.rs` y `i_gdm_ok.rs` compilan, pero lo que hacen por debajo es exactamente lo
que el checker no sabe comprobar. El `unsafe` de la biblioteca estándar existe, en buena parte,
**por las incompletitudes del *borrow checker***.

### 17.3 El más famoso: el caso 3 de Polonius

```rust
fn get_default<'r, K: Hash + Eq + Copy, V: Default>(
    map: &'r mut HashMap<K, V>,
    key: K,
) -> &'r mut V {
    match map.get_mut(&key) {
        Some(value) => value,
        None => {
            map.insert(key, V::default());
            map.get_mut(&key).unwrap()
        }
    }
}
```

```
error[E0499]: cannot borrow `*map` as mutable more than once at a time
11 |             map.insert(key, V::default());
   |             ^^^ second mutable borrow occurs here
```

Es seguro: el préstamo antiguo y el nuevo **están en ramas distintas**, y solo una se ejecuta.

**Y aquí viene la demostración decisiva**: el mismo fichero, **sin cambiar una línea**, con el
motor declarativo (Datalog) de `rustc`:

```
rustc --edition 2021 -Zpolonius b_polonius3.rs      →  ACEPTA
```

El rechazo no venía del lenguaje ni de las reglas: venía de la **aproximación** que usa el
algoritmo de vivacidad de préstamos. Este caso tiene nombre propio (*NLL Problem Case #3*) y su
solución se llama **Polonius**, y Polonius es… **un programa Datalog**. Exactamente la formulación
que Minim adoptó en `docs/FORMAL.md` §5.2, por la misma razón: es la única cuya exactitud (T1) es
barata de demostrar.

### 17.4 El tercero: iteradores que prestan

```rust
impl Numbers {
    fn next(&mut self) -> Option<&u32> { ... }   // devuelve una referencia a sí mismo
}
while let Some(x) = it.next() { last = Some(x); }
```

```
error[E0499]: cannot borrow `it` as mutable more than once at a time
```

Es el llamado *streaming iterator problem*: el patrón "dame el siguiente elemento **prestado**"
(como `next` en Python, o `IterMut`) es seguro, pero **no se puede escribir** con el rasgo
`Iterator` de Rust, que exige devolver un valor propio. Rust lo resolvió por partes con *GATs*, y
aun así es incómodo. No es un falso rechazo de análisis: es una **falta de expresividad**.

### 17.5 La excepción honesta: `f_selfref.rs`

Ahí una estructura guarda una referencia a su propio campo. Rust lo rechaza... y **no es un falso
rechazo puro**: el programa es seguro **si la estructura nunca se mueve**, y esa condición es
justo lo que Rust no puede comprobar sin `Pin` (y `Pin` tampoco lo hace gratis). Lo listo aquí es
no meterlo en la misma bolsa: es **falta de expresividad + una obligación que no se puede
verificar**, no una aproximación conservadora.

### 17.6 Las tres fuentes de falso rechazo (y dónde está Minim)

| Fuente | Ejemplo | Qué falta | Cómo lo paga Rust |
|---|---|---|---|
| **Granularidad** (índice) | `swap(&mut v[0], &mut v[1])` | préstamos por **posición**, no por variable | `split_at_mut`, `get_disjoint_mut`: **`unsafe` en la biblioteca** |
| **Aproximación de la vivacidad** | caso 3 de Polonius | vivacidad **por camino**, no por intervalo | Polonius (Datalog), **aún no es el motor por defecto** |
| **Expresividad** | iteradores prestados | tipos que devuelven préstamos prestados | GATs, `unsafe`, `Rc<RefCell>` |

Y ahora la comparación honesta de los dos lenguajes, que es el punto de esta sección:

| Programa | Rust | Minim |
|---|---|---|
| `swap(&mut v[0], &mut v[1])` (dos índices) | **rechaza** | rechaza (A7, por dueño) |
| `swap(&mut s.a, &mut s.b)` (dos campos) | **acepta** | **rechaza** (A7) |
| `v.push(v.len())` | **acepta** (*two-phase borrows*) | **rechaza** (A8) |
| caso 3 de Polonius | rechaza (acepta con Polonius) | por decidir con el checker |
| iteradores prestados | rechaza (o necesita GATs/`unsafe`) | rechaza (sin referencias en campos) |

Lectura: **en precisión, Rust va por delante de Minim**, y en los dos primeros renglones lo hace
explícitamente mejor. Minim rechaza **más** casos y a cambio no necesita `'a` en las firmas, ni
`PhantomData`, ni *drop flags*, ni `Send`/`Sync`, ni `Pin`, ni `unsafe` en su biblioteca. Es el
intercambio de §15.4, ahora con ejemplos en la mano.

### 17.7 Lo que esto enseña sobre el teorema

1. La incompletitud es **estructural** (§15.1): a Rust le pasa teniendo 30 años de ingeniería y
   muchos más recursos. No es un fallo de diseño de Minim.
2. Cada falso rechazo se paga con **mecanismos** (`'a`, `PhantomData`, *drop flags*, `Pin`,
   `unsafe`, Polonius). Un lenguaje con menos mecanismos rechaza más: es una ley, no un defecto.
3. **El valor de T1 (exactitud) queda demostrado por contraste**: el rechazo de `b_polonius3.rs`
   desaparece al cambiar el motor por el declarativo. Minim eligió el motor declarativo desde el
   principio, y por eso T1 le cuesta semanas y no una reescritura del compilador.

---

## 18. ¿Por qué Minim rechaza `v.push(v.len)`?

Es el caso **R12** del corpus (`formal/CASES.md`) y el agujero **A8** de `docs/SOUNDNESS.md`. Es la
incompletitud más molesta de Minim, porque el patrón ("añade la longitud actual") es de los más
frecuentes que existen.

### 18.1 Qué pasa, paso a paso

```python
var v = [1, 2, 3]
v.push(v.len)
```

Las dos operaciones piden préstamos **incompatibles** sobre el mismo dueño:

| Operación | Declaración | Préstamo que pide |
|---|---|---|
| `v.push(x)` | `fn push(var self, x: int)` | **único** (por el `var`) |
| `v.len` | propiedad de lectura | **compartido** |

Y los dos préstamos están **vivos en el mismo punto del programa**, porque:

1. El modo va en la **firma, no se infiere** (A1): `var self` significa "préstamo único durante
   **toda** la llamada".
2. No existe ningún mecanismo para **aplazar** el momento en que un préstamo único se activa.

Fíjate en que el préstamo del argumento *moriría* al leerse (regla R7: "un préstamo termina en su
último uso"). El problema no es su duración: es que **el del receptor sigue vivo en ese mismo
punto**.

Salta la regla R1 ("un préstamo único es exclusivo") y, en la formulación Datalog
(`FORMAL.md` §5.2), el hecho:

```
error(κ, κ', p) :- live(κ, p), live(κ', p), origin(κ, x, m), origin(κ', x, m'),
                   κ ≠ κ', (m = uniq ; m' = uniq) .
```

El diagnóstico que le llega al programador (`docs/OWNERSHIP.md` §4):

```
'v' ya tiene un prestamo unico activo
```

### 18.2 Por qué el programa es seguro de verdad

Porque los dos sucesos **no son simultáneos**. El orden de evaluación es de izquierda a derecha
(`DESIGN.md` §5), así que:

1. primero se evalúa el argumento: `v.len` **lee** y devuelve un `int` **copiado**;
2. solo después `push` **escribe**.

Cuando ocurre la escritura, la lectura hace rato que terminó, y el `int` que se copió **ya no tiene
ninguna relación con `v`**. No hay aliasing en ningún instante real. Lo que falla no es el programa:
es que el modelo de préstamos **no sabe decir "este préstamo único está reservado ahora, pero se
activará después"**. Tiene una sola fase por préstamo, no dos.

### 18.3 Cómo lo hace Rust: *two-phase borrows*

Rust acepta `v.push(v.len)` desde 2018 con los *two-phase borrows*:

- El préstamo único nace en estado **reservado** (*reserved*).
- Mientras está reservado, se comporta como una **lectura** a efectos de conflictos: otras lecturas
  (como `v.len`) conviven con él.
- El préstamo pasa a **activo** justo en el **punto de activación**: cuando la llamada empieza de
  verdad, es decir, **después** de evaluar los argumentos.
- Si el préstamo nunca llega a activarse, nunca hubo escritura: no hay peligro.

Dato histórico que lo explica todo: **no se añadió para mejorar, se añadió para arreglar una
regresión**. Cuando NLL llegó a Rust, `vec.push(vec.len())` dejó de compilar y rompió muchísimo
código existente; los *two-phase borrows* se diseñaron para recuperar ese patrón.

Y lo que cuesta: puntos de activación en el grafo de flujo, un estado nuevo de permiso, reglas
especiales para llamadas y asignaciones compuestas — y una borrosidad famosa en los mensajes de
error del *borrow checker* (los diagnósticos de "reserva" son notoriamente confusos).

### 18.4 Por qué Minim no lo hace

Tres razones, todas del mismo tipo: **preferimos rechazar a complicar el sistema**.

| Razón | Detalle |
|---|---|
| **Coste en reglas y pruebas** | harían falta hechos nuevos (`reserved_at`, `activated_at`), reglas `error` que distingan las dos fases, un permiso nuevo en la semántica, y **T2 (principalidad) habría que rehacerlo**: la región deja de ser un único intervalo (`FORMAL.md` §6) |
| **El intercambio de §15.4** | reconocerlo no da seguridad, da comodidad. Y en Minim la comodidad se paga en reglas demostrables |

*(Corrección, ver §19: la firma **no** es un obstáculo. El modo del receptor sigue estando en la
firma y el índice no cambia. El coste real está en la semántica, en I3 y en T2 — y en el caso más
común, ni siquiera eso: se arregla con una regla de elaboración.)*

### 18.5 El arreglo cuesta una línea

```python
let n = v.len
v.push(n)
```

Y no es un parche feo: es la forma **explícita** de decir lo que el checker no puede inferir
("lee primero, escribe después"). El propio Rust obliga a escribir así en otros casos
equivalentes.

Consecuencia de diseño, y es una recomendación: **el diagnóstico de este error debería sugerir
exactamente este arreglo**. Un rechazo por incompletitud bien explicado es un rechazo que el
programador no odia.

### 18.6 Dónde encaja: la hermana temporal de A7

| | Qué es demasiado grueso | Ejemplo |
|---|---|---|
| **A7** | el **espacio**: el préstamo es por dueño entero, no por campo | `swap(var s.a, var s.b)` |
| **A8** | el **tiempo**: el préstamo es todo-o-nada en el punto, no reservado-y-luego-activo | `v.push(v.len)` |

Son la misma enfermedad de fondo: **el modelo es más grueso que la realidad**. Arreglar una exige
refinar las reglas y rehacer T2; por eso las dos están en `formal/CASES.md` §2 como la **frontera
de completitud** del lenguaje:

> Si algún día se aceptan, hay que extender `docs/FORMAL.md` §5 (y las pruebas) en consecuencia.

### 18.7 Un caso hermano que conviene fijar

`v[0] = v[1]` (o `m[k] = m.len` en un mapa) es la **misma forma**: un préstamo único para el lugar
de la izquierda y una lectura de lo mismo a la derecha. Si se acepta o no depende de dos detalles
finos: en qué orden se evalúan el lugar de destino y el valor, y si la región de la lectura termina
antes del punto de la escritura (el intervalo de `live`). Es un candidato claro a **R14** en el
corpus: un caso más que fijar con el checker, en vez de descubrirlo en producción.

---

## 19. Refinamiento: aceptar `v.push(v.len)` pagando casi nada

La observación de partida es correcta y es una mejora real del diseño:

> El préstamo **no ocurre a la vez** que la lectura. El receptor se evalúa primero, pero el
> **préstamo único solo se necesita cuando la llamada se ejecuta**, o sea **después** de evaluar
> los argumentos. Entonces `v.push(v.len)` se puede descomponer como `let t = v.len; v.push(t)`.

Es, en esencia, el mecanismo que Rust llama *two-phase borrows*. Pero hay una distinción que
decide **cuánto cuesta** implementarlo, y es la clave de esta sección.

### 19.1 Evaluar ≠ prestar

- **Evaluar** el receptor: averiguar **dónde está** (su lugar) y ejecutar lo que tenga dentro.
- **Prestar** el receptor: **tomar** el préstamo único que necesita durante la llamada.

Del receptor solo hace falta lo primero antes de los argumentos; lo segundo se necesita al
**ejecutar** la llamada. Por eso los dos préstamos no son simultáneos aunque el texto los ponga en
la misma línea.

### 19.2 El caso barato: receptor que es un **lugar simple**

Si el receptor es una **variable** o una **ruta de campos** (`v`, `x.f`, `x.f.g`), evaluarlo **no
tiene ningún efecto**: es solo "dónde está". Entonces adelantar los argumentos a temporales no
cambia **nada observable**:

```
v.m(a)   ⟹   let t = a
             v.m(t)
```

Y esto es **una regla de elaboración** (territorio de T0, `FORMAL.md` §3), no un cambio de las
reglas de préstamo. Se acepta `v.push(v.len)` **sin tocar**:

- la semántica (no hace falta el permiso `resv`),
- las reglas de préstamo de §5 (¡las mismas!),
- el invariante I3,
- T1 ni T2 (las regiones siguen siendo intervalos),
- la firma como contrato del índice (A1 intacto: el modo sigue en la firma).

Coste total: **una regla de elaboración + una obligación de T0 + un caso de corpus**. Y el ejemplo
se extiende a los argumentos que piden préstamo único:

```python
v.push(v.pop() or 0)      # se elabora a:  let t = v.pop() or 0
                          #                v.push(t)   → dos préstamos SECUENCIALES
```

### 19.3 La condición no es decorativa: hay que exigir "lugar simple"

Si el receptor **no** es un lugar simple, reordenar **cambia el programa**:

```python
var v = [3, 1, 2]
v[v.len - 1].push(limpiar(v))     # el índice LEE 'v'; el argumento MUTA 'v'
```

El receptor es `v[v.len - 1]`: su índice **lee** `v`, y el argumento `limpiar(v)` **muta** `v`.
Intercambiar el orden da **otro resultado**. Por eso el refinamiento se limita a lugares simples
(sin índices ni llamadas) y el caso general sigue rechazado.

### 19.4 Qué queda fuera (y qué costaría arreglarlo)

| Caso | ¿Se acepta? | Qué haría falta |
|---|---|---|
| `v.push(v.len)`, `x.f.push(x.f.len)` | **sí** (elaboración) | nada más |
| `v.push(v.pop() or 0)` | **sí** | nada más |
| `v[v.len - 1].push(f(v))` | no | *two-phase borrows* reales |
| `f().push(g())` | no | *two-phase borrows* reales |

Y el "de verdad" (*reservado → activo*) sí es caro, en cuatro sitios a la vez:

| Pieza | Cambio |
|---|---|
| Semántica (`FORMAL.md` §4) | un tercer permiso en el heap: `perm ∈ { shr(n), resv, uniq }`; reservar **no** da permiso de escritura |
| Sistema declarativo (§5) | hechos `reserved_at` / `activated_at`; las reglas `error` se parten por fase |
| Invariante I3 | pasa a **dos fases**: a lo sumo un préstamo **activo** por lugar; los **reservados** cuentan como lecturas |
| T2 (principalidad) | se rehace: la región deja de ser **un** intervalo y pasa a ser **dos** (reserva, actividad) |

Ahí sí se paga: es tocar tres de las cosas que decimos tener bien atadas.

### 19.5 Recomendación

1. **Adoptar el caso barato en v0.1**: regla de elaboración en `FORMAL.md` §3, obligación de T0, y
   el corpus actualizado (`A11`), con R12 reducido al caso general. Ganancia alta (el patrón es de
   los más frecuentes que hay), coste casi nulo y **cero** cambios en las reglas de préstamo.
2. **Dejar el caso general para v0.2**, con las obligaciones enumeradas en §19.4. Es una extensión
   **compatible** (acepta más programas): aplazarla no genera deuda.
3. **Exigir "lugar simple" desde el primer día**, aunque parezca estrecho: sin la condición, la
   transformación es **incorrecta** (§19.3).

Lección general: **entre "modelo grueso" y "modelo fino" hay un escalón intermedio
sorprendentemente barato — mover el trabajo a la elaboración**, que es donde se declara lo que no
cambia el significado. Ahí está buena parte de la potencia del diseño de Minim (§14.5).

*(Aplicado a los documentos: regla en `docs/FORMAL.md` §3, corrección en `docs/SOUNDNESS.md` §9 y
caso `A11` en `formal/CASES.md`.)*

---

## 20. El caso `swap`: cómo se resuelve (lenguaje natural y lenguaje formal)

### 20.1 En lenguaje natural

Imagina un **armario con dos cajones**, `p.a` y `p.b`. Son cajones **distintos**: lo que pasa en uno
no afecta al otro.

Ahora queremos **intercambiar su contenido** con una función `swap` que necesita escribir en los
dos. Y aquí está el problema: para escribir, cada argumento pide un **préstamo único** (exclusivo).
Como los dos préstamos ocurren **en la misma llamada**, están vivos **a la vez**.

v0.1 mira los dos préstamos y dice: "los dos son sobre `p`… ¡conflicto!". El fallo es que el libro
de préstamos apunta **el armario entero** (`p`) en vez del **cajón** (`p.a`, `p.b`). Rust, que
apunta el cajón, acepta esto sin problemas (`&mut s.a, &mut s.b`).

**La corrección es obvia en lenguaje natural**: apuntar el **cajón**, no el armario. Y comprobar si
dos préstamos chocan preguntando si **uno contiene al otro**:

- `p.a` y `p.b`: ninguno contiene al otro → **no chocan** → se acepta. ✅
- `p` y `p.a`: el armario contiene al cajón → **chocan** → se rechaza. ❌
- `p.a` y `p.a`: es el mismo → **chocan** → se rechaza. ❌

Y hay una segunda parte, más sutil: si la función `swap` recibe **dos parámetros**, ¿cómo sabemos,
dentro del cuerpo, que `x` e `y` no son el mismo cajón? Porque **el llamante lo garantiza en la
puerta**: al llamar, se comprueba que los lugares de los argumentos exclusivos son **disjuntos dos
a dos**. Esa es la única pieza nueva, y usa la **misma** relación de "se contiene".

### 20.2 Cuidado: había dos casos mezclados

Antes de resolver nada hay que separar dos programas que estaban en la misma casilla. **No son el
mismo problema**:

| | Programa | ¿Es un falso rechazo? | Estado en v0.1 |
|---|---|---|---|
| **Secuencial** | `fill(p.a, 1)` y **después** `fill(p.b, 1)` | no | **ya se acepta**: el primer préstamo muere en su último uso (R7) |
| **Simultáneo** | `swap(p.a, p.b)`: dos argumentos `var` en **una** llamada | **sí** | **rechazado** ← este es A7 |

Es decir: el caso que hay que resolver es el **simultáneo**. Y el secuencial **no** es incompletitud
sino comportamiento correcto: si el checker lo rechazara, sería un **bug** de la máquina de estados
(no devolver el dueño al morir el préstamo), no un límite del modelo. Eso ahora es un test (`A13`).

### 20.3 En lenguaje formal: el modelo de lugares

**Definición (lugar o camino).** Un lugar es una ruta desde una raíz:

```
pl ::= x | pl.f | pl[i]
```

Ejemplos: `p`, `p.a`, `p.a[0]`, `p.a[0].b`.

**Definición (solapamiento).** La **única** relación nueva:

```
overlap(pl1, pl2)  ≜  pl1 es prefijo de pl2  ∨  pl2 es prefijo de pl1
```

| | `overlap` | Por qué |
|---|---|---|
| `p.a` , `p.b` | **falso** | ninguno es prefijo del otro |
| `p` , `p.a` | verdadero | `p` es prefijo de `p.a` |
| `p.a` , `p.a[0]` | verdadero | prefijo |
| `p.a[0]` , `p.a[1]` | verdadero (conservador) | los índices no son constantes distintas |

**Las reglas corregidas** (sustituyen a `origin(κ, x, m)` y `same_place(x, x2)` de §5.2):

```
% préstamos y accesos, ahora por LUGAR
error(κ, p)     :- live(κ, p), origin(κ, pl, _), access(pl2, p, write), overlap(pl, pl2) .
error(κ, p)     :- live(κ, p), origin(κ, pl, _), moved_at(pl2, p), overlap(pl, pl2) .
error(κ, κ', p) :- live(κ, p), live(κ', p), origin(κ, pl, m), origin(κ', pl2, m'),
                   κ ≠ κ', overlap(pl, pl2), (m = uniq ; m' = uniq) .

% LA PUERTA: en una llamada, los argumentos 'var' son disjuntos dos a dos
error(pl1, pl2) :- arg(pl1), arg(pl2), pl1 ≠ pl2, overlap(pl1, pl2),
                   (uniq(pl1) ; uniq(pl2)) .
```

Con esto:

- `swap(p.a, p.b)` → `overlap(p.a, p.b)` = falso → **no hay `error`** → se acepta. ✅
- `swap(p, p)` → `overlap(p, p)` = verdadero → **`error`** → se rechaza. ❌
- `swap(p.a, p.a)` → **`error`** → se rechaza. ❌

**El invariante pasa a su forma por lugar:**

> **I3′**: en todo punto `p` y todo lugar `pl`: (a) a lo sumo **un** préstamo vivo `uniq` cuyo lugar
> solape con `pl`; y (b) ningún `uniq` vivo solapa con un préstamo compartido vivo.

**Y la obligación nueva de la demostración (T3):**

> **Lema (actualización disjunta)**: si `pl1` y `pl2` **no** solapan, escribir en `pl2` no cambia
> el valor del lugar `pl1`.

Se prueba por inducción sobre la estructura de los caminos. Es exactamente lo que permite que
`swap` escriba en `p.a` sin invalidar el préstamo sobre `p.b`. Sin este lema, la regla nueva
**no** sería sólida.

**La hipótesis escondida de la que depende todo** (*disjunción de raíces*): dos **variables**
distintas denotan asignaciones distintas — no hay alias entre raíces. Se sostiene porque los
préstamos **no se almacenan** en campos (A2) y porque los argumentos se comprueban en la puerta.
Sin esa hipótesis, comparar caminos sintácticamente no sería correcto. Rust descansa en la misma.

### 20.4 Qué cuesta exactamente

| Pieza | ¿Cambia? | Detalle |
|---|---|---|
| Sintaxis de superficie | **no** | cero tokens: `p.a` ya se escribía así |
| Heap de la semántica | **sí, poco** | se indexa por **caminos**: `H[pl ↦ v]` |
| Reglas §5.2 | **sí** | `origin` guarda un camino; `same_place` → `overlap` |
| Puerta de la llamada | **sí, nueva** | disjunción dos a dos de los argumentos `var` |
| I3 | **sí** | pasa a I3′ |
| T3 | **sí** | **+1 lema**: actualización disjunta |
| **T1, T2** | **no** | mismo argumento; el dominio sigue siendo finito y las reglas monótonas |
| I1, I2, I4, I5 | **no** | — |
| Firma / índice (A1) | **no** | los nombres de campo ya están en el AST |

### 20.5 Por qué resolver A7 antes que A8

| | **A7** (lugares por campo) | **A8** (dos fases) |
|---|---|---|
| Reglas nuevas | **1** (`overlap`) | dos hechos + fase en cada regla `error` |
| Semántica | caminos en el heap | **permiso nuevo** `resv` + pasos de activación |
| Invariante | I3′ (reformular) | I3 **de dos fases** |
| T2 | **sin cambios** | **rehecho** (dos intervalos) |
| Ganancia | `swap(p.a, p.b)` y préstamos simultáneos de campos | `v.push(v.len)` con receptor no simple |

**A7 es mucho más barato y más rentable.** Y el modelo resultante es, literalmente, una **pizca de
lógica de separación** limitada a caminos: `overlap(pl1, pl2)` = falso es el `*` de la lógica de
separación, aplicado solo a sub-lugares de un mismo dueño.

### 20.6 Lo que sigue sin resolverse (y hay que decirlo)

- **Lugares con índice**: `swap(p.a[0], p.a[1])` sigue rechazado, porque los índices no se conocen
  estáticamente. Es lo mismo que hace Rust, que para eso exige `split_at_mut`.
- **`overlap` es sintáctica**: nunca acepta algo inseguro, pero puede rechazar dos lugares que
  casualmente coinciden.
- **`p` frente a `p.a`**: siguen siendo incompatibles, y es correcto: leer el todo mientras alguien
  tiene una parte es legítimamente peligroso.

*(Aplicado: `docs/SOUNDNESS.md` §10, `docs/FORMAL.md` §5.3, y en el corpus `R13` reescrito con
`A12` (simultáneo, aceptar) y `A13` (secuencial, aceptar ya).)*
