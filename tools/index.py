#!/usr/bin/env python3
"""index.py - fase 1 (docs/INDEXACION.md): indice de simbolos de Minim.

No parsea expresiones ni resuelve tipos: es un automata de tres estados sobre lineas.
Produce la tabla de simbolos completa, params/ret, spans, hashes y llamadas.

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
  --json           vuelca el indice completo en JSON (un modulo por fichero)
  --write [DIR]    escribe .minim/index.json (todos los modulos) en DIR (default: dir del target)
  --refs [OUT]     escribe indice invertido de referencias (default stdout)
  --changed        compara con .minim/index.json e imprime modulos con interfaz cambiada
  (sin consulta)   la tabla de simbolos completa
"""
import os
import re
import sys
import json
import hashlib

KEYWORD = re.compile(r"^(use|let|var|fn|type|trait)\b")
MEMBER = re.compile(r"^(fn|case)\b")
FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*(:|=)")
NAMEOF = re.compile(r"^(?:use\s+|let\s+|var\s+|fn\s+|type\s+|trait\s+|case\s+)([A-Za-z_][A-Za-z0-9_]*)")


def indent_of(line):
    return len(line) - len(line.lstrip("\t"))


def parse_params(sig, owner=None):
    m = re.match(r"^fn\s+\w+\s*\((.*)\)\s*(->\s*(.+))?$", sig.strip())
    if not m:
        return [], None
    params_str = m.group(1).strip()
    ret = m.group(3).strip() if m.group(3) else None
    params = []
    if params_str:
        depth = 0
        cur = ""
        parts = []
        for ch in params_str:
            if ch in "([{":
                depth += 1
                cur += ch
            elif ch in ")]}":
                depth -= 1
                cur += ch
            elif ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            mode = "borrow"
            if p.startswith("var "):
                mode = "unique"
                p = p[4:].strip()
            elif p.startswith("move "):
                mode = "move"
                p = p[5:].strip()
            if ":" in p:
                name, typ = [x.strip() for x in p.split(":", 1)]
            else:
                name = p
                typ = owner if (name == "self" and owner) else (owner or "self")
            params.append({"name": name, "type": typ, "mode": mode})
    return params, ret


def extract_calls(src_lines, span):
    text = "\n".join(src_lines[span[0] - 1:span[1]])
    pat = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\(")
    seen = []
    for m in pat.finditer(text):
        c = m.group(1)
        if c not in seen:
            seen.append(c)
    return seen


def body_hash(src_lines, span):
    text = "\n".join(src_lines[span[0] - 1:span[1]])
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def is_public(name):
    return not (name or "").startswith("_")


def scan(src):
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
        d = {"kind": kind, "name": name, "sig": stripped, "doc": doc, "line": i + 1,
             "public": is_public(name)}
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
                    memb_name = NAMEOF.match(s).group(1)
                    memb = {"kind": s.split()[0], "name": memb_name, "sig": s,
                            "line": j + 1, "public": is_public(memb_name), "fields": []}
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
                    ms = j + 1
                    me = k
                    while me < n and (not lines[me].strip() or indent_of(lines[me]) > 1):
                        me += 1
                    memb["span"] = [ms, me]
                    memb["calls"] = extract_calls(lines, memb["span"])
                    memb["hash"] = body_hash(lines, memb["span"])
                    if memb["kind"] == "fn":
                        ps, rt = parse_params(memb["sig"], owner=name)
                        memb["params"] = ps
                        if rt is not None:
                            memb["ret"] = rt
                    members.append(memb)
                    j = k
                    continue
                if ind == 1 and FIELD.match(s):
                    parts = re.split(r"[:=]", s, maxsplit=1)
                    ftype = parts[1].split("=")[0].strip() if len(parts) > 1 else ""
                    members.append({"kind": "field", "name": parts[0].strip(), "sig": s,
                                    "line": j + 1, "public": is_public(parts[0].strip()),
                                    "fields": [{"name": parts[0].strip(), "type": ftype}]})
                j += 1
            d["members"] = members
            d["span"] = [i + 1, max(i + 1, j)]
            d["calls"] = []
            d["hash"] = body_hash(lines, d["span"])
            decls.append(d)
            i = j
            continue
        while j < n and (not lines[j].strip() or indent_of(lines[j]) > 0):
            j += 1
        d["span"] = [i + 1, j]
        d["calls"] = extract_calls(lines, d["span"])
        d["hash"] = body_hash(lines, d["span"])
        if kind == "fn":
            ps, rt = parse_params(d["sig"], owner=None)
            d["params"] = ps
            if rt is not None:
                d["ret"] = rt
        decls.append(d)
        i = j
    return {"uses": uses, "decls": decls}


def module_hash(mod):
    sigs = [d["sig"] for d in mod["decls"]]
    for d in mod["decls"]:
        for m in d.get("members", []):
            sigs.append(m["sig"])
    block = "\n".join(mod["uses"] + sigs)
    return hashlib.md5(block.encode("utf-8")).hexdigest()[:8]


def walk(path):
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for f in sorted(files):
                if f.endswith(".mim"):
                    yield os.path.join(root, f)
    else:
        yield path


def scan_file(path):
    src = open(path, encoding="utf-8").read()
    mod = scan(src)
    mod["path"] = path
    mod["module"] = os.path.splitext(os.path.basename(path))[0]
    mod["hash"] = module_hash(mod)
    mod["format"] = 1
    return mod


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


def refs_index(mods):
    inv = {}
    for mod in mods:
        path = mod["path"]
        src = open(path, encoding="utf-8").read().split("\n")
        for name_decl in [d["name"] for d in mod["decls"]] + [m["name"] for d in mod["decls"] for m in d.get("members", [])]:
            if not name_decl:
                continue
            pat = re.compile(r"\b" + re.escape(name_decl) + r"\b")
            for k, line in enumerate(src, 1):
                if pat.search(line):
                    inv.setdefault(name_decl, []).append(f"{path}:{k}")
    # dotted calls
    for mod in mods:
        path = mod["path"]
        src = open(path, encoding="utf-8").read().split("\n")
        for d in mod["decls"]:
            for c in d.get("calls", []):
                if "." in c:
                    pat = re.compile(r"\b" + re.escape(c) + r"\b")
                    for k, line in enumerate(src, 1):
                        if pat.search(line):
                            inv.setdefault(c, []).append(f"{path}:{k}")
            for m in d.get("members", []):
                for c in m.get("calls", []):
                    if "." in c:
                        pat = re.compile(r"\b" + re.escape(c) + r"\b")
                        for k, line in enumerate(src, 1):
                            if pat.search(line):
                                inv.setdefault(c, []).append(f"{path}:{k}")
    # dedup
    for k in inv:
        inv[k] = sorted(set(inv[k]))
    return inv


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 0
    target = argv[0]
    rest = argv[1:]
    with_docs = "--docs" in rest
    cmd = next((a for a in rest if a.startswith("--") and a not in ("--docs",)), None)
    arg = None
    if cmd:
        k = rest.index(cmd)
        if cmd in ("--write", "--refs") or (cmd not in ("--tokens", "--api", "--json", "--changed") and k + 1 < len(rest)):
            if k + 1 < len(rest):
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

    if cmd == "--json":
        mods = [scan_file(p) for p in paths]
        print(json.dumps({"modules": mods}, indent=2, ensure_ascii=False))
        return 0

    if cmd == "--write":
        outdir = arg if arg else None
        if outdir is None:
            outdir = target if os.path.isdir(target) else os.path.dirname(os.path.abspath(target))
        os.makedirs(os.path.join(outdir, ".minim"), exist_ok=True)
        mods = [scan_file(p) for p in paths]
        outpath = os.path.join(outdir, ".minim", "index.json")
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump({"format": 1, "modules": mods}, f, indent=2, ensure_ascii=False)
        print(f"wrote {outpath}")
        return 0

    if cmd == "--refs":
        mods = [scan_file(p) for p in paths]
        inv = refs_index(mods)
        if arg:
            with open(arg, "w", encoding="utf-8") as f:
                json.dump(inv, f, indent=2, ensure_ascii=False)
            print(f"wrote {arg}")
        else:
            print(json.dumps(inv, indent=2, ensure_ascii=False))
        return 0

    if cmd == "--changed":
        base = os.path.join(target if os.path.isdir(target) else os.path.dirname(os.path.abspath(target)), ".minim", "index.json")
        old = {}
        if os.path.exists(base):
            try:
                old = json.load(open(base, encoding="utf-8"))
            except Exception:
                old = {}
        oldmap = {m.get("path"): m.get("hash") for m in old.get("modules", [])}
        mods = [scan_file(p) for p in paths]
        changed = [m["path"] for m in mods if oldmap.get(m["path"]) != m["hash"]]
        for c in changed:
            print(c)
        return 0

    for p in paths:
        mod = scan_file(p)
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
                    a, b = (member["span"] if member and "span" in member else d["span"])
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