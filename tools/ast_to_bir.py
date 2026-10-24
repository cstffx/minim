"""Traduccion Minim AST -> BIR (babirusas).

Baja el AST de superficie de `tools/nodes.py` (ya pasado por
`core_ir.elaborate`, es decir, sin `ForStmt`) a la IR de babirusas:
`Function` con `params`, `locals`, `blocks` y terminadores.

Puntos de la traduccion:

- Los enlaces (`let`/`var`) declaran `Local` + `StorageLive`; el valor se baja
  a `Assign(place, Rvalue)` o, si tiene control de flujo (if/match/llamada/
  `or`/`?`), a un bloque con destino (un temporal o la variable).
- Las expresiones se bajan a `Rvalue`; las llamadas son
  `Stmt("Call", call_func, call_args, call_dest, call_target)` con un temporal
  como destino. Las llamadas a metodo llevan el receptor como primer argumento
  y se nombran `tipo.metodo` (p. ej. `list.push`, `Shape.area`).
- `if`/`while`/`match` generan bloques y terminadores `SwitchInt`/`Goto`.
  `break`/`continue` se resuelven contra la pila de bucles; en un `for` ya
  desazucarado (`_for_continue_count`) `continue` salta al incremento.
- `return` escribe en el local de retorno `__ret` y termina con `Return`.
- Los patrones de `match` (literales, variantes, tuplas y `else`) se bajan a
  comparaciones de tag/valor; los bindings se asignan a locales de la rama.
- Las closures se elevan a funciones `nombre$lambdaN`; la expresion queda como
  `Aggregate(kind="closure", const_value=fn, items=[capturas])`.

La integracion con babirusas es `borrow_check_program()` /
`borrow_check_function()`: traducen y ejecutan `BorrowChecker` sobre el BIR.
El codegen WASM sigue consumiendo el AST (Fase 6).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "babirusas", "src"))

from tools import nodes as A
from tools.parser import parse
from tools.typecheck import TC
from tools.core_ir import elaborate

from babirusas.src.borrowir.ir import (
    Type, Place, Rvalue, Stmt, Term, Block, Param, Local, Function,
)


from tools.bir_translator import TranslatorCore
from tools.bir_place import PlaceMixin
from tools.bir_expr import ExprMixin
from tools.bir_stmt import StmtMixin
from tools.bir_match import MatchMixin
from tools.bir_types import to_type, _ast_type, _local, _param_mode


class Translator(PlaceMixin, ExprMixin, StmtMixin, MatchMixin,
                 TranslatorCore):
    """Traductor AST -> BIR compuesto por mixins."""
    pass


class _ProgramTranslator(Translator):
    def run(self, prog):
        top = []
        for st in (prog.stmts or []):
            if isinstance(st, A.FnDecl):
                self.add_function(st)
            elif isinstance(st, A.TypeDecl):
                for m in (st.members or []):
                    if isinstance(m.node, A.FnDecl):
                        self.add_function(m.node, owner=st.name)
            elif isinstance(st, A.TraitDecl):
                continue
            elif isinstance(st, A.UseDecl):
                continue
            else:
                top.append(st)
        if top:
            self.add_top_level(top)
        return self.functions

    def add_top_level(self, stmts):
        # BIR no tiene globales: las sentencias de nivel superior se agrupan
        # en una funcion `main`/`__top` (hello.mim y los tests de Fase 1).
        name = "main" if not any(f.name == "main" for f in self.functions) else "__top"
        fd = A.FnDecl(name, [], [], None, A.Suite(stmts))
        self.add_function(fd)

    def add_function(self, fd, owner=None):
        name = fd.name if owner is None else f"{owner}.{fd.name}"
        fn = Function(name)
        saved = (self.fn, self.block, self.scopes, self.decl_scopes,
                 self.scope, self.owner, self.ret_place, self.ret_type,
                 self.loops, self._span, self._initializing)
        self.fn = fn
        self.owner = owner
        fn.entry = 0
        fn.blocks.append(Block(0))
        self.block = 0
        self.scopes = [{}]
        self.decl_scopes = [[]]
        self.loops = []
        self._initializing = set()
        self.ret_type = self._fn_ret_type(fd, owner)
        fn.ret_type = self.ret_type
        self.scope = self._func_scope(fd)
        self.ret_place = _local(self._new_local(self._fresh("ret"), self.ret_type,
                                                mutable=True))
        fn.ret_local = self.ret_place.name

        for p in (fd.params or []):
            if p.type_ is not None:
                pty = _ast_type(p.type_)
            elif p.name == "self" and owner is not None:
                pty = Type("struct", name=owner)
            else:
                pty = Type("unknown")
            mutable = p.mode == "var"
            bir = self._declare(p.name, pty, mutable)
            self.fn.params.append(Param(bir, pty, mutable, _param_mode(p)))

        implicit = self.ret_type.kind not in ("unit", "unknown")
        self.translate_body(fd.body, self.ret_place if implicit else None)
        if not self._terminated():
            self._return()
        self._finish_function()
        self.functions.append(fn)

        (self.fn, self.block, self.scopes, self.decl_scopes,
         self.scope, self.owner, self.ret_place, self.ret_type,
         self.loops, self._span, self._initializing) = saved

    def _func_scope(self, fd):
        if self.tc is None:
            return None
        sc = self.tc.resolver.func_scopes.get(id(fd))
        if sc is None:
            sc = self.tc.module_scope
        return sc

    def translate_body(self, suite, ret_dest):
        stmts = list(suite.stmts) if hasattr(suite, "stmts") else []
        self.push_scope()
        for i, st in enumerate(stmts):
            self._ensure_open()
            self.scope = self.tc.stmt_scopes.get(id(st), self.scope) \
                if self.tc is not None else self.scope
            dest = None
            if i == len(stmts) - 1 and ret_dest is not None and \
                    isinstance(st, (A.ExprStmt, A.IfStmt, A.MatchStmt)):
                dest = ret_dest
            self.translate_stmt(st, dest)
        self.pop_scope()


def translate_program(prog, tc=None):
    """Traduce un `Program` ya elaborado a una lista de `Function` BIR."""
    return _ProgramTranslator(tc).run(prog)


def translate_module(prog, tc=None):
    """Igual que `translate_program`, pero agrupado por nombre."""
    return {f.name: f for f in translate_program(prog, tc)}


def translate_function(fd, tc=None, owner=None):
    """Traduce una unica funcion (incluye las closures que eleva)."""
    tr = _ProgramTranslator(tc)
    tr.add_function(fd, owner=owner)
    fn = next(f for f in tr.functions if f.name == (fd.name if owner is None
                                                     else f"{owner}.{fd.name}"))
    fn._lifted = [f for f in tr.functions if f is not fn]
    return fn


def borrow_check_function(fn, functions=None):
    from babirusas.src.borrowir.borrow import BorrowChecker
    return BorrowChecker(functions).check(fn)


def borrow_check_translated(prog, tc=None):
    """Traduce el programa y devuelve `(functions, errores)`."""
    from babirusas.src.borrowir.borrow import BorrowChecker
    funcs = translate_program(prog, tc)
    checker = BorrowChecker(funcs)
    errors = []
    for fn in funcs:
        errors += [f"{fn.name}: {e}" for e in checker.check(fn)]
    return funcs, errors


def borrow_check_program(prog, tc=None):
    return borrow_check_translated(prog, tc)[1]


def prepare(source):
    """parse + typecheck + elabora `for` + re-typecheck."""
    program = parse(source)
    tc = TC(program)
    errors = tc.check()
    if errors:
        return program, tc, [str(e) for e in errors]
    elaborate(program, tc)
    tc = TC(program)
    errors = tc.check()
    return program, tc, [str(e) for e in errors]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python3 -m tools.ast_to_bir <file.mim> [--dump]")
        return 1
    path = argv[0]
    dump = "--dump" in argv
    program, tc, errors = prepare(open(path).read())
    if errors:
        print(f"FAIL [typecheck] {path}")
        for e in errors:
            print(f"  {e}")
        return 1
    funcs, borrow_errors = borrow_check_translated(program, tc)
    if dump:
        for fn in funcs:
            print(f"fn {fn.name}(" +
                  ", ".join(f"{p.name}: {p.type.kind}" for p in fn.params) + ")")
            for b in fn.blocks:
                print(f"  bb{b.id}:")
                for s in b.stmts:
                    print(f"    {s.kind}")
                if b.terminator is not None:
                    print(f"    -> {b.terminator.kind}")
    if borrow_errors:
        print(f"FAIL [borrow] {path}")
        for e in borrow_errors:
            print(f"  {e}")
        return 1
    print(f"OK: {len(funcs)} funcion(es) BIR, borrow check limpio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
