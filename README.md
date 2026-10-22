# Minim

Lenguaje de programación de alto nivel diseñado desde el comienzo para mantener un
balance de legibilidad y bajo consumo de tokens con modelos de inteligencia artificial,
con tipado estático, verificación de préstamos (*borrow checker*) y compilación rápida
de un solo paso.

## Hola, mundo

```python
fn main()
	print("Hola, mundo!")
```

## Métrica real del ahorro de tokens

Medido con tokenizadores BPE reales (`o200k_base` / `cl100k_base`) sobre 5 programas
(`tools/measure.py`):

| Programa | [APL](code/wordcount/apl.md) | [J](code/wordcount/j.md) | [K](code/wordcount/k.md) | [Minim](code/wordcount/minim.md) | [Python](code/wordcount/python.md) | [Python tipado](code/wordcount/python_typed.md) | [PHP](code/wordcount/php.md) | [Rust](code/wordcount/rust.md) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| a_counter | — | — | — | [50 / 50](code/a_counter/minim.md) | [65 / 65](code/a_counter/python.md) | [65 / 65](code/a_counter/python_typed.md) | [71 / 71](code/a_counter/php.md) | [91 / 91](code/a_counter/rust.md) |
| b_shapes | — | — | — | [57 / 57](code/b_shapes/minim.md) | [83 / 85](code/b_shapes/python.md) | [83 / 85](code/b_shapes/python_typed.md) | [107 / 105](code/b_shapes/php.md) | [79 / 78](code/b_shapes/rust.md) |
| c_total | — | — | — | [51 / 51](code/c_total/minim.md) | [58 / 57](code/c_total/python.md) | [58 / 57](code/c_total/python_typed.md) | [83 / 83](code/c_total/php.md) | [83 / 83](code/c_total/rust.md) |
| d_borrow | — | — | — | [53 / 53](code/d_borrow/minim.md) | [40 / 40](code/d_borrow/python.md) | [57 / 57](code/d_borrow/python_typed.md) | [76 / 76](code/d_borrow/php.md) | [70 / 70](code/d_borrow/rust.md) |
| wordcount | [47 / 52](code/wordcount/apl.md) | [15 / 15](code/wordcount/j.md) | [18 / 18](code/wordcount/k.md) | [130 / 132](code/wordcount/minim.md) | [154 / 153](code/wordcount/python.md) | [206 / 205](code/wordcount/python_typed.md) | [250 / 246](code/wordcount/php.md) | [272 / 266](code/wordcount/rust.md) |
| **TOTAL** | **47 / 52** | **15 / 15** | **18 / 18** | **341 / 343** | **400 / 400** | **469 / 469** | **587 / 581** | **595 / 588** |

Valores `o200k_base / cl100k_base`.

| Comparación (total, o200k_base) | Ahorro de tokens de Minim |
|---|---:|
| Minim vs Python | 14.7% |
| Minim vs Python tipado | 27.3% |
| Minim vs PHP | 41.9% |
| Minim vs Rust | 42.7% |