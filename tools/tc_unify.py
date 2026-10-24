import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.resolve import Resolver, Symbol, SymKind
from tools.tc_types import (
    INT, FLOAT, BOOL, STR, NIL, UNKNOWN, ERRT, BYTES, INT_WIDTHS, FLOAT_WIDTHS,
    L, M, O, R, N, V, F, TypeCheckError, _bound_name, _tyname, _struct_compat,
    compat, merge_types, apply, _subst_type,
)



class UnifyMixin:
    def unify(self,a,b,subst):
        a=apply(a,subst); b=apply(b,subst)
        if a==b: return
        if a[0]=="var": subst[a[1]]=b; return
        if b[0]=="var": subst[b[1]]=a; return
        if a[0]==b[0]:
            if a[0] in ("list","set","opt","res","borrow"): self.unify(a[1],b[1],subst)
            elif a[0]=="map":
                self.unify(a[1],b[1],subst); self.unify(a[2],b[2],subst)
            elif a[0]=="tuple" and len(a[1])==len(b[1]):
                for x,y in zip(a[1],b[1]): self.unify(x,y,subst)
            elif a[0]=="named" and a[1]==b[1] and len(a[2])==len(b[2]):
                for x,y in zip(a[2],b[2]): self.unify(x,y,subst)
            elif a[0]=="func":
                if a[1] is not None and b[1] is not None and len(a[1])==len(b[1]):
                    for x,y in zip(a[1],b[1]): self.unify(x,y,subst)
                if a[2] is not None and b[2] is not None: self.unify(a[2],b[2],subst)
