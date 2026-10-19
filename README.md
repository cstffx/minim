# Minim

Lenguaje de programación de alto nivel diseñado **para que una IA escriba código con
el mínimo número de tokens posible**, sin renunciar a tipado estático, verificación de
préstamos (*borrow checker*) ni compilación rápida de un solo paso.

> Estado: **diseño** (v0.1). No hay implementación todavía.

## Los 6 requisitos -> las 6 decisiones

| Requisito | Decisión de diseño |
|---|---|
| Sintaxis parecida a Python | Bloques por sangría, `:` al final de cabecera, `and/or/not`, `for x in y`, `match/case/else`, última expresión = valor de retorno |
| Tipado | Estático y estructural, con inferencia total en locales y en el retorno; genéricos monomorfizados y acotados por `trait` |
| Borrow checker | Un dueño por valor, préstamos con `&`, mutabilidad **inferida**, sin sintaxis de *lifetimes* (los préstamos no se pueden guardar en estructuras) |
| Mínimos tokens | 29 palabras reservadas, cero puntuación redundante, errores con `?` y `or`, campos sin `self.` |
| Indexación fácil | Toda declaración empieza en columna 0 con una palabra clave; la firma es una línea; documento = comentarios `#` encima. El índice es un subproducto del compilador |
| Compilación fácil (Delphi) | Un fichero = una unidad, sin cabeceras ni declaraciones adelantadas, 2 pasadas baratas (firmas -> cuerpos), sin sobrecarga, análisis local |

## Ejemplo

```python
use fs, env

# cuenta palabras de un fichero y muestra las 10 mas frecuentes
fn count(path: str) -> map[str, int]!
	var c = map[str, int]()
	for line in fs.read(path)?
		for w in line.words()
			c[w.lower().strip(".,;:!?")] += 1
	c

fn main()
	let path = env.arg(1) or "in.txt"
	let c = count(path) or
		eprint(f"error: {it}")
		return
	for w, k in c.top(10)
		print(f"{k:6} {w}")
```

Equivalente en Python tipado: **206 tokens**. En Rust: **272**. En Minim: **130**.
(medido con `o200k_base`, `tools/measure.py`).

## Resultados medidos

Coste total de los 5 programas de `tools/bench*` (tokenizador `o200k_base`):

| | Minim | Python | Python tipado | Rust |
|---|---|---|---|---|
| tokens | **341** | 400 | 469 | 595 |
| vs Minim | — | −15% | −27% | −43% |

Las decisiones concretas y su ahorro medido están en [`docs/TOKENS.md`](docs/TOKENS.md).

## Documentación

1. [`docs/DESIGN.md`](docs/DESIGN.md) — el lenguaje completo: léxico, palabras clave, sentencias, tipos, prelude.
2. [`docs/OWNERSHIP.md`](docs/OWNERSHIP.md) — modelo de propiedad y reglas del *borrow checker*.
3. [`docs/SOUNDNESS.md`](docs/SOUNDNESS.md) — ¿es infalible? Agujeros, correcciones y qué falta para demostrarlo.
4. [`docs/FORMAL.md`](docs/FORMAL.md) — plan de demostración: CoreMin, semántica, reglas Datalog, teoremas T1-T6, mecanización.
5. [`docs/TOKENS.md`](docs/TOKENS.md) — metodología de medición, tablas y reglas de minimización.
6. [`docs/COMPILACION.md`](docs/COMPILACION.md) — pipeline de compilación estilo Delphi.
7. [`docs/INDEXACION.md`](docs/INDEXACION.md) — índice de símbolos, formato `.mimidx`, uso en RAG/LLM.
8. [`docs/INDICE-LLM.md`](docs/INDICE-LLM.md) — el índice como servicio: cómo lo consulta un modelo sin leer el código.
9. [`docs/grammar.ebnf`](docs/grammar.ebnf) — gramática formal.
10. [`docs/APRENDER-DEMOSTRACIONES.md`](docs/APRENDER-DEMOSTRACIONES.md) — cómo se demuestran estas cosas, desde cero.
11. [`examples/`](examples/) — programas de ejemplo.
12. [`formal/CASES.md`](formal/CASES.md) — corpus de conformidad: 11 casos inseguros, 2 de incompletitud, 10 válidos.

## Decisiones abiertas

Marcadas con ⚠️ en `docs/DESIGN.md`; las tres más importantes:

1. **Parámetros por préstamo por defecto** (`fn f(v: [int])` no consume `v`; `move v` o `var v` para cambiarlo).
   Ahorra ~2 tokens por parámetro y evita la mayoría de errores de la IA, pero oculta el coste de copia.
2. **`lowerCamelCase` para identificadores** en lugar de `snake_case` (medido: ahorra ~50% en identificadores
   de varias palabras con `cl100k_base`, nunca cuesta más con `o200k_base`).
3. **Sangría con TAB** (medido: 1 token menos por línea indentada que 4 o 2 espacios).

## Herramientas

```bash
pip install tiktoken
python3 tools/measure.py     # comparativa real Minim / Python / Rust
python3 tools/micro.py       # coste en tokens de cada decision de sintaxis
python3 tools/index.py examples/ --tokens   # indice de firmas vs fuente (fase 1, sin compilador)
```
