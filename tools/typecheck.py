import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.parser import parse
from tools.resolve import Resolver, Symbol, SymKind

from tools.tc_types import *
from tools.tc_types import (
    TypeCheckError, _bound_name, compat, merge_types, apply, F, L, M, O, R, N,
    V, INT, FLOAT, BOOL, STR, NIL, UNKNOWN, ERRT, BYTES, INT_WIDTHS,
    FLOAT_WIDTHS,
)
from tools.tc_stmt import StmtMixin
from tools.tc_expr import ExprMixin
from tools.tc_unify import UnifyMixin
from tools.tc_types import TypesMixin


class TC(TypesMixin, StmtMixin, ExprMixin, UnifyMixin):
    def __init__(self,program):
        self.program=program
        self.errors=[]
        self.resolver=Resolver(program)
        self.module_scope,res_errs=self.resolver.resolve()
        for e in res_errs:
            self.errors.append(TypeCheckError(str(e),getattr(e,"node",None)))
        self.type_defs={s.name:s for s in program.stmts if isinstance(s,TypeDecl)}
        self.traits={s.name:s for s in program.stmts if isinstance(s,TraitDecl)}
        self.generic_bounds={}
        for s in program.stmts:
            if isinstance(s,(FnDecl,TypeDecl)):
                for tp in (s.tparams or []):
                    if tp.bound is not None:
                        self.generic_bounds[(s.name,tp.name)]=_bound_name(tp.bound)
        self.bounds={}
        self.cur_type=None; self.cur_func=None; self.tvs=set(); self.mono=set()
        # scope used while checking each statement (consumed by core_ir to
        # desugar `for` loops with the static type of the iterable).
        self.stmt_scopes={}
        self._register_structs()
        self.module_aliases=dict(getattr(program,"merged_modules",{}))
        self._register()

    def err(self,msg,node=None): self.errors.append(TypeCheckError(msg,node))

    def check(self):
        self.check_program(); return self.errors

    def check_program(self):
        for s in self.program.stmts:
            if isinstance(s,LetDecl): self._letdecl(s,self.module_scope)
            elif isinstance(s,VarDecl): self._vardecl(s,self.module_scope)
        for s in self.program.stmts:
            if isinstance(s,FnDecl):
                sc=self.resolver.func_scopes.get(id(s))
                if sc is None:
                    sc=self.module_scope.child("func",owner=s); self.resolver.func_scopes[id(s)]=sc
                self._func(s,sc,None)
            elif isinstance(s,TypeDecl):
                ts=self.resolver.type_scopes.get(id(s))
                if ts is None:
                    ts=self.module_scope.child("type",owner=s); self.resolver.type_scopes[id(s)]=ts
                self._typedecl(s,ts)


def typecheck(source):
    program=parse(source)
    tc=TC(program)
    errors=tc.check()
    return errors,program,tc

def check(source):
    return typecheck(source)[0]

if __name__=="__main__":
    if len(sys.argv)<2:
        print("usage: python3 typecheck.py <file.mim>"); sys.exit(1)
    src=open(sys.argv[1]).read()
    errors,program,tc=typecheck(src)
    if errors:
        print(f"{len(errors)} type errors:")
        for e in errors: print(f"  {e}")
        sys.exit(1)
    else:
        print(f"OK: type-checked {len(program.stmts)} top-level statements")
        sys.exit(0)
