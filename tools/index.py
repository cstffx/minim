#!/usr/bin/env python3
"""index.py - prototipo de la fase 1 (docs/INDEXACION.md): indice de simbolos de Minim.

No parsea expresiones ni resuelve tipos: es un automata de tres estados sobre lineas.
Es lo que produce `.mimidx` y lo que sirve las consultas de docs/INDICE-LLM.md.

Uso:
  python3 tools/index.py <ruta.mim|dir> [consulta]

Consultas:
  --api            firma (+ doc con --docs) de cada declaracion, en orden estable
  --type NOMBRE    variantes, campos y metodos de un tipo
  --sig NOMBRE     la firma literal, una linea
  --doc NOMBRE     el comentario '#' de encima
  --find NOMBRE    referencias: fichero:linea
  --body NOMBRE    el cuerpo por span
  --tokens         coste medido: fuente vs indice (necesita tiktoken)
  (sin consulta)   la tabla de simbolos completa

Opciones: --docs  incluye los '#' de encima en --api y en --tokens
"""
import os
import re
import sys

KEYWORD = re.compile(r"^(use|let|var|fn|type|trait)\b")
MEMBER = re.compile(r"^(fn|case)\b")
FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*(:|=)")
NAMEOF = re.compile(r"^(?:use\s+|let\s+|var\s+|fn\s+|type\s+|trait\s+|case\s+)([A-Za-z_][A-Za-z0-9_]*)")


def indent_of(line):
    return len(line) - len(line.lstrip("\t"))


def scan(src):
    """Devuelve {uses, decls}. Un decl: kind, name, sig, doc, line, span, [members]."""
    lines = src.split("\n")
    decls, uses = [], []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        text = raw.rstrip()
        if not text or indent_of(raw) != 0 or not KEYWORD.match(text.strip()):
            i += 1
            continue
        stripped = text.strip()
        kind = stripped.split()[0] if stripped.split() else ""
        name = NAMEOF.match(stripped)
        name = name.group(1) if name else None
        doc = None
        if i and lines[i - 1].lstrip().startswith("#"):
            doc = lines[i - 1].strip()
        if kind == "use":
            uses += [p.strip() for p in stripped[4:].split(",") if p.strip()]
            i += 1
            continue
        d = {"kind": kind, "name": name, "sig": stripped, "doc": doc, "line": i + 1}
        j = i + 1
        if kind in ("type", "trait"):
            members = []
            while j < n:
                m = lines[j]
                mt = m.rstrip()
                if not mt:
                    j += 1
                    continue
                ind = indent_of(m)
                if ind == 0:
                    break
                s = mt.strip()
                if ind == 1 and MEMBER.match(s):
                    memb = {"kind": s.split()[0], "name": NAMEOF.match(s).group(1),
                            "sig": s, "line": j + 1, "fields": []}
                    k = j + 1
                    while k < n:
                        f = lines[k].rstrip()
                        if not f:
                            k += 1
                            continue
                        if indent_of(lines[k]) != 2:
                            break
                        if FIELD.match(f.strip()):
                            parts = re.split(r"[:=]", f.strip(), maxsplit=1)
                            ftype = parts[1].split("=")[0].strip() if len(parts) > 1 else ""
                            memb["fields"].append({"name": parts[0].strip(), "type": ftype})
                        k += 1
                    j = k
                    members.append(memb)
                    continue
                if ind == 1 and FIELD.match(s):            # campo directo del tipo
                    parts = re.split(r"[:=]", s, maxsplit=1)
                    ftype = parts[1].split("=")[0].strip() if len(parts) > 1 else ""
                    members.append({"kind": "field", "name": parts[0].strip(),
                                    "sig": s, "line": j + 1,
                                    "fields": [{"name": parts[0].strip(), "type": ftype}]})
                j += 1
            d["members"] = members
            d["span"] = [i + 1, max(i + 1, j)]
            decls.append(d)
            i = j
            continue
        # cuerpo: hasta la linea en columna 0 que no este vacia
        while j < n and (not lines[j].strip() or indent_of(lines[j]) > 0):
            j += 1
        d["span"] = [i + 1, j]
        decls.append(d)
        i = j
    return {"uses": uses, "decls": decls}


def walk(path):
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for f in sorted(files):
                if f.endswith(".mim"):
                    yield os.path.join(root, f)
    else:
        yield path


def api_of(mod, with_docs):
    out = []
    if mod["uses"]:
        out.append("use " + ", ".join(mod["uses"]))
    for d in mod["decls"]:
        if with_docs and d["doc"]:
            out.append(d["doc"])
        out.append(d["sig"])
        for m in d.get("members", []):
            if m["kind"] == "case":
                fields = ", ".join(f["name"] + ": " + f["type"] for f in m["fields"])
                out.append("\tcase " + m["name"] + (("(" + fields + ")") if fields else ""))
            elif m["kind"] == "field":
                out.append("\t" + m["sig"])
            elif m["kind"] == "fn":
                out.append("\t" + m["sig"])
    return "\n".join(out)


def find_all(paths, name):
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    hits = []
    for p in paths:
        for k, line in enumerate(open(p, encoding="utf-8").read().split("\n"), 1):
            if pat.search(line):
                hits.append(f"{p}:{k}")
    return hits


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 0
    target = argv[0]
    rest = argv[1:]
    with_docs = "--docs" in rest
    cmd = next((a for a in rest if a.startswith("--") and a != "--docs"), None)
    arg = None
    if cmd:
        k = rest.index(cmd)
        if cmd != "--tokens" and cmd != "--api" and k + 1 < len(rest):
            arg = rest[k + 1]
    paths = list(walk(target))

    if cmd == "--tokens":
        try:
            import tiktoken
            enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            print("necesita tiktoken:  pip install tiktoken", file=sys.stderr)
            return 2
        ts = ti = 0
        print(f"{'fichero':<20}{'fuente':>8}{'indice':>8}{'delta':>9}")
        print("-" * 45)
        for p in paths:
            src = open(p, encoding="utf-8").read()
            a = len(enc.encode(src))
            b = len(enc.encode(api_of(scan(src), with_docs)))
            ts += a
            ti += b
            print(f"{os.path.basename(p):<20}{a:>8}{b:>8}{100 * (b - a) / max(a, 1):>8.1f}%")
        print("-" * 45)
        print(f"{'TOTAL':<20}{ts:>8}{ti:>8}{100 * (ti - ts) / max(ts, 1):>8.1f}%"
              f"   ratio {ts / max(ti, 1):.1f}x")
        return 0

    if cmd == "--find":
        for h in find_all(paths, arg):
            print(h)
        return 0

    for p in paths:
        mod = scan(open(p, encoding="utf-8").read())
        if cmd == "--api":
            print(api_of(mod, with_docs))
            continue
        if cmd in ("--sig", "--doc", "--body", "--type"):
            for d in mod["decls"]:
                hit = (d["name"] == arg)
                member = None
                if not hit:
                    member = next((m for m in d.get("members", []) if m["name"] == arg), None)
                    hit = member is not None
                if not hit:
                    continue
                if cmd == "--sig":
                    print(member["sig"] if member else d["sig"])
                elif cmd == "--doc":
                    if d["doc"]:
                        print(d["doc"])
                elif cmd == "--type":
                    for m in d.get("members", []):
                        if m["kind"] == "case":
                            fs = ", ".join(f["name"] + ": " + f["type"] for f in m["fields"])
                            print(f"case {m['name']}" + (f"({fs})" if fs else ""))
                        else:
                            print(m["sig"])
                else:
                    a, b = d["span"]
                    lines = open(p, encoding="utf-8").read().split("\n")
                    print("\n".join(lines[a - 1:max(a, b - 1)]))
            continue
        print(f"# {p}   uses: {', '.join(mod['uses']) or '-'}")
        for d in mod["decls"]:
            doc = f"   {d['doc']}" if d["doc"] else ""
            print(f"{d['line']:>5}  {d['sig']}{doc}")
            for m in d.get("members", []):
                label = m["sig"] if m["kind"] in ("fn", "field") else "case " + m["name"]
                print(f"{m['line']:>5}    {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
