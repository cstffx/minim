#!/usr/bin/env python3
"""measure.py - coste real en tokens de los programas de ejemplo de Minim.

Compara el mismo programa escrito en Minim, Python (sin y con anotaciones de tipo) y Rust,
usando tokenizadores BPE reales:
  o200k_base  -> GPT-4o / GPT-5 / modelos o-series
  cl100k_base -> GPT-4 / GPT-3.5 / y el mas parecido al de la mayoria de modelos abiertos

Uso:  pip install tiktoken && python3 tools/measure.py

Sin red: coloca o200k_base.tiktoken y cl100k_base.tiktoken en $TIKTOKEN_CACHE_DIR con el
nombre del SHA-1 de su URL de origen.
"""
import os
import sys

import tiktoken

ENC = ("o200k_base", "cl100k_base")
ROOT = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = [
    ("a_counter", "tipo + metodo + uso", "bench"),
    ("b_shapes", "tipo suma + pattern match", "bench"),
    ("c_total", "bucle + manejo de error", "bench"),
    ("d_borrow", "firmas con prestamo mut/imm", "bench"),
    ("wordcount", "CLI completo", "bench2"),
]
LANGS = ["Minim", "Python", "Python tipado", "Rust"]


def ntok(encs, path):
    src = open(path, encoding="utf-8").read()
    return [len(e.encode(src)) for e in encs]


def main():
    encs = [tiktoken.get_encoding(n) for n in ENC]
    print(f"{'programa':<12} {'Minim':>10} {'Python':>10} {'Py+tipos':>10} {'Rust':>10}   (o200k/cl100k)")
    print("-" * 74)
    total = [[0, 0] for _ in LANGS]
    for name, desc, sub in PROGRAMS:
        d = os.path.join(ROOT, sub)
        variants = [
            os.path.join(d, name + ".mim"),
            os.path.join(d, name + ".py"),
            os.path.join(d, name + "_typed.py"),
            os.path.join(d, name + ".rs"),
        ]
        cells = []
        for i, p in enumerate(variants):
            if os.path.exists(p):
                v = ntok(encs, p)
            else:                                    # sin version tipada: usa la normal
                v = cells[1] if i == 2 else [0, 0]
            cells.append(v)
            total[i] = [a + b for a, b in zip(total[i], v)]
        print(f"{name:<12} " + "".join(f"{a:>4}/{b:<5}" for a, b in cells) + f"  {desc}")
    print("-" * 74)
    print(f"{'TOTAL':<12} " + "".join(f"{a:>4}/{b:<5}" for a, b in total))
    print()
    for i, label in enumerate(LANGS[1:], start=1):
        for j, enc in enumerate(ENC):
            pct = 100 * (1 - total[0][j] / total[i][j])
            print(f"  Minim vs {label:<14} ({enc:>11}) -> {pct:5.1f}% menos tokens")


if __name__ == "__main__":
    sys.exit(main())
