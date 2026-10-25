"""Name resolution for Minim: builds symbol tables and resolves identifiers.

Phase 2a of the compiler pipeline. Takes a parsed Program (AST) and:
  - collects module-level declarations (functions, types, traits, consts, vars)
  - collects type members (fields, variants, methods, associated fns)
  - builds nested scopes for function bodies and blocks
  - resolves every NameExpr / Place / type name to its definition
  - reports unbound names

Does NOT type-check or borrow-check. That is phase 2b/2c.
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.parser import parse


class SymKind:
    FUNC = "func"
    TYPE = "type"
    TRAIT = "trait"
    FIELD = "field"
    VARIANT = "variant"
    PARAM = "param"
    LOCAL = "local"
    CONST = "const"
    METHOD = "method"
    ASSOC = "assoc"


class Symbol:
    def __init__(self, name, kind, node, scope, type_hint=None):
        self.name = name
        self.kind = kind
        self.node = node          # AST node that declares it
        self.scope = scope        # defining scope
        self.type_hint = type_hint

    def __repr__(self):
        return f"Sym({self.kind}, {self.name})"


class Scope:
    def __init__(self, kind, parent=None, owner=None):
        self.kind = kind          # 'module', 'type', 'func', 'block', 'trait'
        self.parent = parent
        self.owner = owner        # the node that owns this scope (TypeDecl, FnDecl, ...)
        self.symbols = {}         # name -> Symbol
        self.children = []

    def define(self, sym):
        if sym.name in self.symbols:
            # redefinition: keep first, warn
            pass
        else:
            self.symbols[sym.name] = sym
        return sym

    def lookup(self, name, include_self_fields=False):
        # Walk up scopes. For type scopes, also check fields if include_self_fields.
        s = self
        while s is not None:
            if name in s.symbols:
                return s.symbols[name]
            s = s.parent
        return None

    def child(self, kind, owner=None):
        c = Scope(kind, parent=self, owner=owner)
        self.children.append(c)
        return c


class ResolveError(Exception):
    def __init__(self, msg, node):
        span = getattr(node, "span", None)
        loc = f"{span.line}:{span.col}" if span else "?"
        super().__init__(f"{loc}: {msg}")
        self.node = node


class Resolver:
    def __init__(self, program):
        self.program = program
        self.module_scope = Scope("module")
        self.errors = []
        self.type_scopes = {}   # id(TypeDecl) -> Scope
        self.func_scopes = {}   # id(FnDecl) -> Scope
        self._add_prelude()
        # user modules merged by tools/modules.py are addressed as `alias.name`
        for alias in getattr(program, "merged_modules", {}):
            self.module_scope.define(Symbol(alias, SymKind.TYPE, None, self.module_scope))

    def _add_prelude(self):
        # Functions
        for name in ("print", "eprint", "range", "min", "max", "abs", "str", "int",
                     "float", "assert", "panic", "drop", "copy", "len", "err", "alloc", "dealloc", "memcpy", "memset"):
            self.module_scope.define(Symbol(name, SymKind.FUNC, None, self.module_scope))
        # Types
        for name in ("int", "float", "bool", "str", "bytes", "nil", "map", "set",
                     "arc", "rc", "task", "ptr"):
            self.module_scope.define(Symbol(name, SymKind.TYPE, None, self.module_scope))
        # Constants
        for name in ("pi", "e", "true", "false", "nil"):
            self.module_scope.define(Symbol(name, SymKind.CONST, None, self.module_scope))
        # Modules
        for name in ("fs", "env", "io", "net", "json", "time", "rand", "math", "os", "task"):
            self.module_scope.define(Symbol(name, SymKind.TYPE, None, self.module_scope))

    def resolve(self):
        # Pass 1: collect module-level declarations
        self._collect_module(self.program, self.module_scope)
        # Pass 2: resolve bodies
        self._resolve_program(self.program, self.module_scope)
        return self.module_scope, self.errors

    # ---- collection ----
    def _collect_module(self, program, scope):
        for stmt in program.stmts:
            if isinstance(stmt, (LetDecl,)):
                scope.define(Symbol(stmt.name, SymKind.CONST, stmt, scope, stmt.type_))
            elif isinstance(stmt, VarDecl):
                for b in stmt.bindings:
                    if b.kind == "name" and b.name:
                        scope.define(Symbol(b.name, SymKind.LOCAL, stmt, scope, b.type_))
            elif isinstance(stmt, FnDecl):
                scope.define(Symbol(stmt.name, SymKind.FUNC, stmt, scope, stmt.ret))
                self.func_scopes[id(stmt)] = None  # placeholder
            elif isinstance(stmt, TypeDecl):
                scope.define(Symbol(stmt.name, SymKind.TYPE, stmt, scope))
                ts = scope.child("type", owner=stmt)
                self.type_scopes[id(stmt)] = ts
                self._collect_type(stmt, ts)
            elif isinstance(stmt, TraitDecl):
                scope.define(Symbol(stmt.name, SymKind.TRAIT, stmt, scope))
                ts = scope.child("trait", owner=stmt)
                for m in stmt.methods:
                    ts.define(Symbol(m.name, SymKind.METHOD, m, ts, m.ret))
            elif isinstance(stmt, (UseDecl,)):
                pass  # imports handled in resolve pass

    def _collect_type(self, tdecl, scope):
        for m in tdecl.members:
            node = m.node
            if isinstance(node, Field):
                scope.define(Symbol(node.name, SymKind.FIELD, node, scope, node.type_))
            elif isinstance(node, Variant):
                scope.define(Symbol(node.name, SymKind.VARIANT, node, scope))
                # variant fields
                vs = scope.child("variant", owner=node)
                for fn in node.fields:
                    vs.define(Symbol(fn.name, SymKind.FIELD, fn, vs, fn.type_))
                # nested members
                for nm in node.members:
                    self._collect_member(nm, scope)
            elif isinstance(node, FnDecl):
                if node.params and node.params[0].name == "self":
                    scope.define(Symbol(node.name, SymKind.METHOD, node, scope, node.ret))
                else:
                    scope.define(Symbol(node.name, SymKind.ASSOC, node, scope, node.ret))
            elif isinstance(node, LetDecl):
                scope.define(Symbol(node.name, SymKind.CONST, node, scope, node.type_))

    def _collect_member(self, m, scope):
        node = m.node
        if isinstance(node, Field):
            scope.define(Symbol(node.name, SymKind.FIELD, node, scope, node.type_))
        elif isinstance(node, FnDecl):
            if node.params and node.params[0].name == "self":
                scope.define(Symbol(node.name, SymKind.METHOD, node, scope, node.ret))
            else:
                scope.define(Symbol(node.name, SymKind.ASSOC, node, scope, node.ret))
        elif isinstance(node, LetDecl):
            scope.define(Symbol(node.name, SymKind.CONST, node, scope, node.type_))

    # ---- resolution ----
    def _resolve_program(self, program, scope):
        for stmt in program.stmts:
            self._resolve_stmt(stmt, scope)

    def _resolve_stmt(self, stmt, scope):
        if isinstance(stmt, UseDecl):
            pass  # imports: resolve paths (not implemented for v0.1)
        elif isinstance(stmt, LetDecl):
            self._resolve_expr(stmt.value, scope)
            if stmt.type_:
                self._resolve_type(stmt.type_, scope)
        elif isinstance(stmt, VarDecl):
            self._resolve_expr(stmt.value, scope)
            for b in stmt.bindings:
                self._resolve_binding(b, scope, define=True)
        elif isinstance(stmt, FnDecl):
            fs = scope.child("func", owner=stmt)
            self.func_scopes[id(stmt)] = fs
            if stmt.tparams:
                for tp in stmt.tparams:
                    fs.define(Symbol(tp.name, SymKind.TYPE, tp, fs, tp.bound))
                    if tp.bound:
                        self._resolve_type(tp.bound, fs)
            # params
            for p in stmt.params:
                fs.define(Symbol(p.name, SymKind.PARAM, p, fs, p.type_))
                if p.type_:
                    self._resolve_type(p.type_, fs)
                if p.default:
                    self._resolve_expr(p.default, fs)
            if stmt.ret:
                self._resolve_type(stmt.ret, fs)
            # body
            self._resolve_suite(stmt.body, fs)
        elif isinstance(stmt, TypeDecl):
            ts = self.type_scopes[id(stmt)]
            if stmt.tparams:
                for tp in stmt.tparams:
                    ts.define(Symbol(tp.name, SymKind.TYPE, tp, ts, tp.bound))
                    if tp.bound:
                        self._resolve_type(tp.bound, ts)
            for m in stmt.members:
                self._resolve_member(m, ts)
        elif isinstance(stmt, TraitDecl):
            ts = self.module_scope.children[-1] if self.module_scope.children else scope
            # find trait scope
            for c in scope.children:
                if c.owner is stmt:
                    ts = c
                    break
            for m in stmt.methods:
                fs = ts.child("func", owner=m)
                for p in m.params:
                    fs.define(Symbol(p.name, SymKind.PARAM, p, fs, p.type_))
                    if p.type_:
                        self._resolve_type(p.type_, fs)
                if m.ret:
                    self._resolve_type(m.ret, fs)
        elif isinstance(stmt, LetStmt):
            self._resolve_expr(stmt.value, scope)
            for b in stmt.bindings:
                self._resolve_binding(b, scope, define=True)
        elif isinstance(stmt, VarStmt):
            self._resolve_expr(stmt.value, scope)
            for b in stmt.bindings:
                self._resolve_binding(b, scope, define=True)
        elif isinstance(stmt, Assign):
            self._resolve_place(stmt.place, scope)
            self._resolve_expr(stmt.value, scope)
        elif isinstance(stmt, IfStmt):
            self._resolve_expr(stmt.cond, scope)
            self._resolve_suite(stmt.then, scope)
            for ec, es in stmt.elifs:
                self._resolve_expr(ec, scope)
                self._resolve_suite(es, scope)
            if stmt.else_:
                self._resolve_suite(stmt.else_, scope)
        elif isinstance(stmt, WhileStmt):
            self._resolve_expr(stmt.cond, scope)
            self._resolve_suite(stmt.body, scope)
        elif isinstance(stmt, ForStmt):
            bs = scope.child("block")
            for b in stmt.bindings:
                self._resolve_binding(b, bs, define=True)
            self._resolve_expr(stmt.iter, scope)
            self._resolve_suite(stmt.body, bs)
        elif isinstance(stmt, MatchStmt):
            self._resolve_expr(stmt.expr, scope)
            for arm in stmt.arms:
                self._resolve_arm(arm, scope)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._resolve_expr(stmt.value, scope)
        elif isinstance(stmt, SpawnStmt):
            self._resolve_expr(stmt.expr, scope)
        elif isinstance(stmt, AwaitStmt):
            self._resolve_expr(stmt.expr, scope)
        elif isinstance(stmt, ExprStmt):
            self._resolve_expr(stmt.expr, scope)
        elif isinstance(stmt, (BreakStmt, ContinueStmt)):
            pass

    def _resolve_member(self, m, scope):
        node = m.node
        if isinstance(node, Field):
            if node.type_:
                self._resolve_type(node.type_, scope)
            if node.default:
                self._resolve_expr(node.default, scope)
        elif isinstance(node, Variant):
            vs = None
            for c in scope.children:
                if c.owner is node:
                    vs = c
                    break
            if vs is None:
                vs = scope.child("variant", owner=node)
            for fn in node.fields:
                if fn.type_:
                    self._resolve_type(fn.type_, vs)
            for nm in node.members:
                self._resolve_member(nm, vs if vs else scope)
        elif isinstance(node, FnDecl):
            fs = scope.child("func", owner=node)
            self.func_scopes[id(node)] = fs
            if node.tparams:
                for tp in node.tparams:
                    fs.define(Symbol(tp.name, SymKind.TYPE, tp, fs, tp.bound))
                    if tp.bound:
                        self._resolve_type(tp.bound, fs)
            for p in node.params:
                fs.define(Symbol(p.name, SymKind.PARAM, p, fs, p.type_))
                if p.type_:
                    self._resolve_type(p.type_, fs)
                if p.default:
                    self._resolve_expr(p.default, fs)
            if node.ret:
                self._resolve_type(node.ret, fs)
            self._resolve_suite(node.body, fs)
        elif isinstance(node, LetDecl):
            self._resolve_expr(node.value, scope)
            if node.type_:
                self._resolve_type(node.type_, scope)

    def _resolve_suite(self, suite, scope):
        for stmt in suite.stmts:
            self._resolve_stmt(stmt, scope)

    def _resolve_arm(self, arm, scope):
        if arm.is_else:
            if isinstance(arm.body, Suite):
                self._resolve_suite(arm.body, scope)
            elif arm.body is not None:
                self._resolve_expr(arm.body, scope)
            return
        # resolve pattern bindings
        bs = scope.child("block")
        self._resolve_pattern(arm.pattern, bs, define=True)
        if arm.guard:
            self._resolve_expr(arm.guard, bs)
        if isinstance(arm.body, Suite):
            self._resolve_suite(arm.body, bs)
        elif arm.body is not None:
            self._resolve_expr(arm.body, bs)

    def _resolve_binding(self, binding, scope, define=False):
        if binding.kind == "name":
            if define:
                scope.define(Symbol(binding.name, SymKind.LOCAL, binding, scope, binding.type_))
            if binding.type_:
                self._resolve_type(binding.type_, scope)
        elif binding.kind == "tuple":
            for p in (binding.tuple_patterns or []):
                self._resolve_pattern(p, scope, define=define)
        elif binding.kind == "variant":
            for p in (binding.patterns or []):
                self._resolve_pattern(p, scope, define=define)

    def _resolve_pattern(self, pat, scope, define=False):
        if pat.kind == "name":
            if define:
                scope.define(Symbol(pat.value, SymKind.LOCAL, pat, scope))
        elif pat.kind == "variant":
            # resolve variant name in enclosing type/module scope
            sym = scope.lookup(pat.name) if hasattr(scope, 'lookup') else None
            # walk up to find it
            s = scope
            while s is not None and pat.name not in s.symbols:
                s = s.parent
            if s is None:
                # maybe a variant of a known type; try module scope
                pass
            for p in (pat.patterns or []):
                self._resolve_pattern(p, scope, define=define)
        elif pat.kind == "named_field":
            if pat.sub:
                self._resolve_pattern(pat.sub, scope, define=define)
        elif pat.kind == "tuple":
            for p in (pat.patterns or []):
                self._resolve_pattern(p, scope, define=define)

    def _resolve_place(self, place, scope):
        # resolve the base name
        sym = self._lookup(place.name, scope)
        if sym is None:
            self.errors.append(ResolveError(f"unbound name {place.name!r}", place))
        for part in place.parts:
            if part[0] == "field":
                pass  # field resolution deferred to type checker
            elif part[0] == "index":
                self._resolve_expr(part[1], scope)

    def _resolve_expr(self, expr, scope):
        if isinstance(expr, NameExpr):
            if expr.name in ("self", "it", "true", "false", "nil", "__continue__", "__break__"):
                return
            sym = self._lookup(expr.name, scope)
            if sym is None:
                self.errors.append(ResolveError(f"unbound name {expr.name!r}", expr))
        elif isinstance(expr, IntLit) or isinstance(expr, FloatLit) or isinstance(expr, StrLit) or \
             isinstance(expr, FStrLit) or isinstance(expr, RStrLit) or isinstance(expr, BytesLit) or \
             isinstance(expr, MlStrLit) or isinstance(expr, BoolLit) or isinstance(expr, NilLit) or \
             isinstance(expr, SelfExpr) or isinstance(expr, ItExpr):
            pass
        elif isinstance(expr, BorrowExpr):
            self._resolve_expr(expr.operand, scope)
        elif isinstance(expr, UnaryOp):
            self._resolve_expr(expr.operand, scope)
        elif isinstance(expr, BinOp):
            self._resolve_expr(expr.left, scope)
            if expr.right is not None and not isinstance(expr.right, str):
                self._resolve_expr(expr.right, scope)
        elif isinstance(expr, Postfix):
            self._resolve_expr(expr.base, scope)
            for op in expr.ops:
                if op[0] == "field":
                    pass
                elif op[0] in ("index", "slice"):
                    if op[1] is not None and not isinstance(op[1], str):
                        self._resolve_expr(op[1], scope)
                    if len(op) > 2 and op[2] is not None:
                        self._resolve_expr(op[2], scope)
                elif op[0] == "call":
                    for arg in op[1]:
                        if isinstance(arg, Arg):
                            # label is a param name, not an expression; skip resolution
                            self._resolve_expr(arg.value, scope)
                        else:
                            self._resolve_expr(arg, scope)
                elif op[0] == "as":
                    self._resolve_type(op[1], scope)
                elif op[0] == "typeargs":
                    for t in op[1]:
                        self._resolve_type(t, scope)
        elif isinstance(expr, TupleExpr):
            for e in expr.items:
                self._resolve_expr(e, scope)
        elif isinstance(expr, ListExpr):
            for a in expr.items:
                if isinstance(a, Arg):
                    self._resolve_expr(a.value, scope)
                else:
                    self._resolve_expr(a, scope)
        elif isinstance(expr, MapExpr):
            for a in expr.items:
                if isinstance(a, Arg):
                    self._resolve_expr(a.value, scope)
                else:
                    self._resolve_expr(a, scope)
        elif isinstance(expr, Lambda):
            # new scope for lambda params
            ls = scope.child("func")
            for p in expr.params:
                ls.define(Symbol(p.name, SymKind.PARAM, p, ls, p.type_))
                if p.type_:
                    self._resolve_type(p.type_, ls)
                if p.default:
                    self._resolve_expr(p.default, ls)
            self._resolve_expr(expr.body, ls)
        elif isinstance(expr, MoveExpr):
            if isinstance(expr.lambda_, Lambda):
                ls = scope.child("func")
                for p in expr.lambda_.params:
                    ls.define(Symbol(p.name, SymKind.PARAM, p, ls, p.type_))
                    if p.type_:
                        self._resolve_type(p.type_, ls)
                    if p.default:
                        self._resolve_expr(p.default, ls)
                self._resolve_expr(expr.lambda_.body, ls)
        elif isinstance(expr, IfExpr):
            self._resolve_expr(expr.cond, scope)
            self._resolve_expr(expr.then, scope)
            self._resolve_expr(expr.else_, scope)
        elif isinstance(expr, MatchExpr):
            self._resolve_expr(expr.expr, scope)
            for arm in expr.arms:
                self._resolve_arm(arm, scope)

    def _resolve_type(self, typ, scope):
        if isinstance(typ, TypeName):
            if typ.name not in ("int", "float", "bool", "str", "bytes", "nil", "map", "set", "self", "Self",
                                "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "f32", "f64", "ptr"):
                sym = self._lookup(typ.name, scope)
                if sym is None:
                    self.errors.append(ResolveError(f"unbound type {typ.name!r}", typ))
            for a in typ.args:
                self._resolve_type(a, scope)
        elif isinstance(typ, TypeList):
            self._resolve_type(typ.inner, scope)
        elif isinstance(typ, TypeMap):
            self._resolve_type(typ.key, scope)
            self._resolve_type(typ.val, scope)
        elif isinstance(typ, TypeSet):
            self._resolve_type(typ.inner, scope)
        elif isinstance(typ, TypeBorrow):
            self._resolve_type(typ.inner, scope)
        elif isinstance(typ, TypeTuple):
            for t in typ.items:
                self._resolve_type(t, scope)
        elif isinstance(typ, TypeFunc):
            for t in typ.params:
                self._resolve_type(t, scope)
            self._resolve_type(typ.ret, scope)
        elif isinstance(typ, TypeParen):
            self._resolve_type(typ.inner, scope)
        elif isinstance(typ, TypeSuffix):
            self._resolve_type(typ.base, scope)

    def _lookup(self, name, scope):
        s = scope
        while s is not None:
            if name in s.symbols:
                return s.symbols[name]
            s = s.parent
        # check module scope as fallback
        if name in self.module_scope.symbols:
            return self.module_scope.symbols[name]
        return None


def resolve(source):
    """Convenience: parse + resolve. Returns (scope, errors)."""
    program = parse(source)
    r = Resolver(program)
    scope, errors = r.resolve()
    return scope, errors, program


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 resolve.py <file.mim>")
        sys.exit(1)
    scope, errors, prog = resolve(open(sys.argv[1]).read())
    if errors:
        print(f"{len(errors)} resolution errors:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"OK: resolved {len(scope.symbols)} module symbols")