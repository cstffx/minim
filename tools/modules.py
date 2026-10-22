"""Module loading for Minim: `use a, b.c` plus file-as-module semantics.

A module is a file: `use fs` resolves to `std/fs.mim`, `use mylib.util` to
`mylib/util.mim` (looking first in `std/`, then in the project directory).
Every declaration of an imported file is merged into the main program under
the alias `<last path segment>.<name>`, so `util.read(...)` and
`util.MAX` keep working after the merge.

Visibility: names starting with `_` are private. They are still merged (their
own module needs them) but external `alias._name` access is rejected.

Known v0.1 limits (documented in status.md):
  - module-qualified types (`util.Point`) are not implemented; types stay
    global by name.
  - two imported files with the same alias collide (error).
"""

import os
import sys
from dataclasses import fields, is_dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *  # noqa: F401,F403
from tools.parser import parse


BUILTIN_MODULES = {
    "fs", "env", "io", "net", "json", "time", "rand", "math", "os", "task",
    "rc", "arc",
}


class ModuleError(Exception):
    pass


class _Renamer:
    """Prefixes references to module-level symbols; locals are left alone."""

    def __init__(self, symbols, shadowed):
        self.symbols = symbols
        self.shadowed = shadowed

    def ref(self, name):
        if name in self.shadowed:
            return name
        return self.symbols.get(name, name)


def _pattern_names(pat, out):
    if pat is None:
        return
    if isinstance(pat, Pattern):
        if pat.kind == "name" and pat.value:
            out.add(pat.value)
        for p in (pat.patterns or []):
            _pattern_names(p, out)
        for p in (pat.tuple_patterns or []):
            _pattern_names(p, out)
        if pat.sub is not None:
            _pattern_names(pat.sub, out)


def _binding_names(binding, out):
    if binding is None:
        return
    if binding.kind == "name" and binding.name:
        out.add(binding.name)
    for p in (binding.patterns or []):
        _pattern_names(p, out)
    for p in (binding.tuple_patterns or []):
        _pattern_names(p, out)


def _collect_locals(node, out):
    """Approximate shadowing: every name bound anywhere in the function."""
    if node is None or isinstance(node, (str, int, float, bool, bytes)):
        return
    if isinstance(node, list):
        for x in node:
            _collect_locals(x, out)
        return
    if isinstance(node, tuple):
        for x in node:
            _collect_locals(x, out)
        return
    if isinstance(node, FnDecl):
        for p in node.params:
            out.add(p.name)
            if p.default is not None:
                _collect_locals(p.default, out)
        for st in (node.body.stmts if node.body else []):
            _collect_locals(st, out)
        return
    if isinstance(node, Lambda):
        for p in node.params:
            out.add(p.name)
            if p.default is not None:
                _collect_locals(p.default, out)
        _collect_locals(node.body, out)
        return
    if isinstance(node, (LetStmt, VarStmt)):
        for b in node.bindings:
            _binding_names(b, out)
        _collect_locals(node.value, out)
        return
    if isinstance(node, ForStmt):
        for b in node.bindings:
            _binding_names(b, out)
        _collect_locals(node.iter, out)
        _collect_locals(node.body, out)
        return
    if isinstance(node, (MatchStmt, MatchExpr)):
        _collect_locals(node.expr, out)
        for arm in (node.arms or []):
            _pattern_names(arm.pattern, out)
            _collect_locals(arm.guard, out)
            _collect_locals(arm.body, out)
        return
    if is_dataclass(node):
        for f in fields(node):
            if f.name == "span":
                continue
            _collect_locals(getattr(node, f.name), out)


def _local_names(node):
    out = set()
    _collect_locals(node, out)
    return out


def _rewrite(node, ren):
    """Rename NameExpr/Place references in place (types are left global)."""
    if node is None or isinstance(node, (str, int, float, bool, bytes)):
        return node
    if isinstance(node, list):
        for i, x in enumerate(node):
            node[i] = _rewrite(x, ren)
        return node
    if isinstance(node, tuple):
        return tuple(_rewrite(x, ren) for x in node)
    if isinstance(node, NameExpr):
        node.name = ren.ref(node.name)
        return node
    if isinstance(node, Place):
        node.name = ren.ref(node.name)
        for part in node.parts or []:
            if part and part[0] == "index" and len(part) > 1:
                _rewrite(part[1], ren)
        return node
    if isinstance(node, TypeName):
        return node
    if isinstance(node, UseDecl):
        return node
    if is_dataclass(node):
        for f in fields(node):
            if f.name == "span":
                continue
            nv = _rewrite(getattr(node, f.name), ren)
            setattr(node, f.name, nv)
    return node


def _module_symbols(stmts):
    """Top-level value symbols of one module, mapped to `alias.name`."""
    syms = {}
    for st in stmts:
        if isinstance(st, FnDecl):
            syms[st.name] = None
        elif isinstance(st, LetDecl):
            syms[st.name] = None
        elif isinstance(st, VarDecl):
            for b in st.bindings:
                if b.kind == "name" and b.name:
                    syms[b.name] = None
    return syms


def _rewrite_decl(st, syms):
    if isinstance(st, FnDecl):
        ren = _Renamer(syms, _local_names(st))
        for p in st.params:
            if p.default is not None:
                _rewrite(p.default, ren)
        _rewrite(st.body, ren)
        st.name = syms.get(st.name, st.name)
    elif isinstance(st, LetDecl):
        ren = _Renamer(syms, set())
        _rewrite(st.value, ren)
        st.name = syms.get(st.name, st.name)
    elif isinstance(st, VarDecl):
        ren = _Renamer(syms, set())
        _rewrite(st.value, ren)
        for b in st.bindings:
            if b.kind == "name" and b.name:
                b.name = syms.get(b.name, b.name)
    elif isinstance(st, TypeDecl):
        for m in st.members:
            node = m.node
            if isinstance(node, FnDecl):
                ren = _Renamer(syms, _local_names(node))
                _rewrite(node.body, ren)
            else:
                _rewrite(node, _Renamer(syms, set()))
    elif isinstance(st, TraitDecl):
        for m in st.methods:
            ren = _Renamer(syms, _local_names(m))
            _rewrite(m.body, ren)
    else:
        _rewrite(st, _Renamer(syms, set()))


class _Loader:
    def __init__(self, base_dir):
        self.base_dir = os.path.abspath(base_dir or ".")
        self.loaded = {}   # abspath -> alias
        self.aliases = {}  # alias -> abspath
        self.root = None

    def resolve(self, parts):
        rel = os.path.join(*parts) + ".mim"
        for cand in (os.path.join(self.base_dir, "std", rel),
                     os.path.join(self.base_dir, rel)):
            if os.path.isfile(cand):
                return os.path.abspath(cand)
        return None

    def load(self, program):
        self.root = program
        self._process(program)
        program.stmts = [s for s in program.stmts if not isinstance(s, UseDecl)]
        program.merged_modules = dict(self.aliases)
        return program

    def _process(self, program):
        uses = [s for s in program.stmts if isinstance(s, UseDecl)]
        for use in uses:
            for parts in use.paths:
                if len(parts) == 1 and parts[0] in BUILTIN_MODULES:
                    continue
                alias = parts[-1]
                path = self.resolve(parts)
                if path is None:
                    raise ModuleError(
                        f"{_loc(use)}: cannot find module {'/'.join(parts)!r} "
                        f"(looked in std/ and {self.base_dir})")
                if alias in self.aliases and self.aliases[alias] != path:
                    raise ModuleError(
                        f"{_loc(use)}: module alias {alias!r} is already used by "
                        f"{os.path.relpath(self.aliases[alias], self.base_dir)}")
                if path in self.loaded:
                    continue
                self.loaded[path] = alias
                self.aliases[alias] = path
                try:
                    src = open(path, encoding="utf-8").read()
                except OSError as e:
                    raise ModuleError(f"{_loc(use)}: cannot read {path}: {e}")
                try:
                    sub = parse(src)
                except Exception as e:
                    raise ModuleError(f"{path}: {e}")
                # dependencies first, then this module's declarations
                self._process(sub)
                self._merge(sub, alias)
        return program

    def _merge(self, module_program, alias):
        syms = _module_symbols(module_program.stmts)
        renamed = {name: f"{alias}.{name}" for name in syms}
        for st in module_program.stmts:
            if isinstance(st, UseDecl):
                continue
            _rewrite_decl(st, renamed)
            self.root.stmts.append(st)


def _loc(node):
    span = getattr(node, "span", None)
    return f"{span.line}:{span.col}" if span else "?"


def load_modules(program, base_dir=None):
    """Resolve `use` declarations and merge imported files into `program`."""
    return _Loader(base_dir).load(program)
