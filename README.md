# Minim

Lenguaje de programación de alto nivel diseñado **para que una IA escriba código con
un bajo consumo de tokens**, sin renunciar a tipado estático, verificación de
préstamos (*borrow checker*) ni compilación rápida de un solo paso.

> Estado: **diseño** (v0.1). No hay implementación todavía.

## Hola, mundo

```python
fn main()
	print("Hola, mundo!")
```

## Ejemplo más complejo (conteo de palabras)

El código completo de cada versión está en la carpeta [`code/`](code/).

## Lenguajes aún más tersos

APL, J y K pueden ganar en brevedad (a costa de legibilidad). Ejemplos del mismo
problema en [`code/apl.md`](code/apl.md), [`code/j.md`](code/j.md) y
[`code/k.md`](code/k.md) (valores en la tabla de métricas).

## Métrica real del ahorro de tokens

Medido con tokenizadores BPE reales (`o200k_base` / `cl100k_base`) sobre 5 programas
(`tools/measure.py`):

| Programa | [Minim](code/minim.md) | [Python](code/python.md) | [Python tipado](code/python_typed.md) | [PHP](code/php.md) | [Rust](code/rust.md) | [APL](code/apl.md) | [J](code/j.md) | [K](code/k.md) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| a_counter | 50 / 50 | 65 / 65 | 65 / 65 | 71 / 71 | 91 / 91 | — | — | — |
| b_shapes | 57 / 57 | 83 / 85 | 83 / 85 | 107 / 105 | 79 / 78 | — | — | — |
| c_total | 51 / 51 | 58 / 57 | 58 / 57 | 83 / 83 | 83 / 83 | — | — | — |
| d_borrow | 53 / 53 | 40 / 40 | 57 / 57 | 76 / 76 | 70 / 70 | — | — | — |
| wordcount | 130 / 132 | 154 / 153 | 206 / 205 | 250 / 246 | 272 / 266 | 47 / 52 | 15 / 15 | 18 / 18 |
| **TOTAL** | **341 / 343** | **400 / 400** | **469 / 469** | **587 / 581** | **595 / 588** | **47 / 52** | **15 / 15** | **18 / 18** |

Valores `o200k_base / cl100k_base`.

| Comparación (total, o200k_base) | Ahorro de tokens de Minim |
|---|---:|
| Minim vs Python | 14.7% |
| Minim vs Python tipado | 27.3% |
| Minim vs PHP | 41.9% |
| Minim vs Rust | 42.7% |
