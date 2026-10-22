#!/usr/bin/env python3
"""minim fmt - formateador canonico (prototipo)."""
import os, sys

def format_source(src):
    lines = src.splitlines()
    out = []
    for line in lines:
        # convertir 4 espacios iniciales a tabs (aprox)
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        tabs = "\t" * (indent // 4)
        out.append(tabs + stripped.rstrip())
    # eliminar lineas en blanco al final
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"

def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 1:
        print("usage: fmt <file.mim>", file=sys.stderr)
        return 1
    path = args[0]
    src = open(path).read()
    formatted = format_source(src)
    # escribir in-place
    with open(path, "w") as f:
        f.write(formatted)
    print(f"formatted {path}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
PY