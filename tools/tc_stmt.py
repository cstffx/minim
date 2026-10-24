import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.resolve import Resolver, Symbol, SymKind
from tools.tc_types import (
    INT, FLOAT, BOOL, STR, NIL, UNKNOWN, ERRT, BYTES, INT_WIDTHS, FLOAT_WIDTHS,
    L, M, O, R, N, V, F, TypeCheckError, _bound_name, _tyname, _struct_compat,
    compat, merge_types, apply, _subst_type,
)



class StmtMixin:
    def _letdecl(self,s,scope):
        vt=self.expr(s.value,scope)
        if s.type_ is not None:
            et=self._atype(s.type_)
            if not compat(vt,et): self.err(f"type mismatch in let {s.name}",s)
            ty=et
        else: ty=vt
        sym=self._lookup(scope,s.name)
        if sym is not None: sym.ty=ty

    def _vardecl(self,s,scope):
        vt=self.expr(s.value,scope)
        self._bind(s.bindings,vt,scope)

    def _bind(self,bindings,value_ty,scope):
        if len(bindings)==1 and bindings[0].kind=="name":
            b=bindings[0]
            if b.type_ is not None:
                et=self._atype(b.type_)
                if not compat(value_ty,et): self.err(f"type mismatch in binding {b.name}",b)
                ty=et
            else: ty=value_ty
            sym=self._lookup(scope,b.name)
            if sym is not None: sym.ty=ty
            elif b.name:
                scope.define(Symbol(b.name,SymKind.LOCAL,b,scope)); scope.lookup(b.name).ty=ty
            return
        if len(bindings)==1 and bindings[0].kind=="tuple":
            b=bindings[0]; pats=b.tuple_patterns or []
            if value_ty is not None and value_ty[0]=="tuple" and len(value_ty[1])==len(pats):
                for pat,et in zip(pats,value_ty[1]): self._bindname(pat,et,scope)
            else:
                for pat in pats: self._bindname(pat,UNKNOWN,scope)
            return
        if value_ty is not None and value_ty[0]=="tuple" and len(value_ty[1])==len(bindings):
            for b,et in zip(bindings,value_ty[1]):
                if b.kind=="name":
                    if b.type_ is not None:
                        aet=self._atype(b.type_)
                        if not compat(et,aet): self.err(f"type mismatch in binding {b.name}",b)
                        ty=aet
                    else: ty=et
                    sym=self._lookup(scope,b.name)
                    if sym is not None: sym.ty=ty
                    elif b.name:
                        scope.define(Symbol(b.name,SymKind.LOCAL,b,scope)); scope.lookup(b.name).ty=ty
        else:
            for b in bindings:
                if b.kind=="name":
                    ty=value_ty if b.type_ is None else self._atype(b.type_)
                    sym=self._lookup(scope,b.name)
                    if sym is not None: sym.ty=ty
                    elif b.name:
                        scope.define(Symbol(b.name,SymKind.LOCAL,b,scope)); scope.lookup(b.name).ty=ty

    def _bindname(self,pat,ty,scope):
        if pat.kind=="name":
            sym=self._lookup(scope,pat.value)
            if sym is not None: sym.ty=ty
            else:
                scope.define(Symbol(pat.value,SymKind.LOCAL,pat,scope)); scope.lookup(pat.value).ty=ty
        elif pat.kind=="tuple":
            if ty is not None and ty[0]=="tuple":
                for p,et in zip(pat.patterns or [],ty[1]): self._bindname(p,et,scope)
            else:
                for p in (pat.patterns or []): self._bindname(p,UNKNOWN,scope)

    def _func(self,f,scope,selftype):
        tps=set(t.name for t in (f.tparams or [])); self.tvs|=tps
        old_bounds=self.bounds
        self.bounds={tp.name:_bound_name(tp.bound) for tp in (f.tparams or []) if tp.bound is not None}
        old_func=self.cur_func; old_type=self.cur_type; self.cur_type=selftype
        params=[]
        for p in f.params:
            if p.name=="self":
                pt=self._atype(p.type_) if p.type_ is not None else (N(selftype) if selftype else UNKNOWN)
            else:
                pt=self._atype(p.type_) if p.type_ is not None else UNKNOWN
            params.append(pt)
            sym=self._lookup(scope,p.name)
            if sym is not None: sym.ty=pt
            else:
                scope.define(Symbol(p.name,SymKind.PARAM,p,scope)); scope.lookup(p.name).ty=pt
        declared=self._atype(f.ret) if f.ret is not None else None
        self.cur_func={"ret":declared}
        body_ty=self.suite(f.body,scope)
        if declared is None:
            ret=body_ty if body_ty is not None else NIL
        else:
            if body_ty is not None and body_ty!=UNKNOWN and not compat(body_ty,declared):
                self.err(f"return type mismatch in {f.name}",f)
            ret=declared
        sym=None
        if selftype is None: sym=self.module_scope.lookup(f.name)
        else:
            ts=self.resolver.type_scopes.get(id(self.type_defs.get(selftype))) if self.type_defs.get(selftype) else None
            if ts is not None: sym=ts.lookup(f.name)
        if sym is not None:
            sym.ty=F(params,ret,[t.name for t in (f.tparams or [])],None)
        self.cur_func=old_func; self.cur_type=old_type; self.tvs-=tps
        self.bounds=old_bounds
        return ret

    def _typedecl(self,td,scope):
        old_type=self.cur_type; self.cur_type=td.name
        tps=set(t.name for t in (td.tparams or [])); self.tvs|=tps
        for m in td.members:
            node=m.node
            if isinstance(node,Field):
                if node.default is not None:
                    dt=self.expr(node.default,scope)
                    if node.type_ is not None:
                        et=self._atype(node.type_)
                        if not compat(dt,et): self.err(f"field default type mismatch {node.name}",node)
            elif isinstance(node,Variant):
                vs=None
                for c in getattr(scope,"children",[]):
                    if getattr(c,"owner",None) is node: vs=c
                if vs is None: vs=scope.child("variant",owner=node)
                for f in node.fields:
                    if f.type_ is not None: self._atype(f.type_)
                for nm in node.members: self._member(nm,vs,td.name)
            elif isinstance(node,FnDecl):
                fs=None
                for c in getattr(scope,"children",[]):
                    if getattr(c,"owner",None) is node: fs=c
                if fs is None: fs=scope.child("func",owner=node)
                self._func(node,fs,td.name)
            elif isinstance(node,LetDecl):
                self._letdecl(node,scope)
        self.tvs-=tps; self.cur_type=old_type

    def _member(self,member,scope,selftype):
        node=member.node
        if isinstance(node,Field):
            if node.default is not None:
                dt=self.expr(node.default,scope)
                if node.type_ is not None:
                    et=self._atype(node.type_)
                    if not compat(dt,et): self.err(f"field default type mismatch {node.name}",node)
        elif isinstance(node,FnDecl):
            fs=None
            for c in getattr(scope,"children",[]):
                if getattr(c,"owner",None) is node: fs=c
            if fs is None: fs=scope.child("func",owner=node)
            self._func(node,fs,selftype)
        elif isinstance(node,LetDecl):
            self._letdecl(node,scope)

    def suite(self,suite,scope):
        last=None
        for st in (suite.stmts if hasattr(suite,"stmts") else []):
            t=self.stmt(st,scope)
            if t is not None: last=t
        return last if last is not None else NIL

    def stmt(self,s,scope):
        self.stmt_scopes[id(s)]=scope
        if isinstance(s,LetStmt):
            vt=self.expr(s.value,scope); self._bind(s.bindings,vt,scope); return None
        if isinstance(s,VarStmt):
            vt=self.expr(s.value,scope); self._bind(s.bindings,vt,scope); return None
        if isinstance(s,Assign):
            pt=self.place(s.place,scope); vt=self.expr(s.value,scope)
            if not compat(vt,pt): self.err(f"assignment type mismatch: {vt} vs {pt}",s)
            return None
        if isinstance(s,IfStmt):
            ct=self.expr(s.cond,scope)
            if ct not in (BOOL,UNKNOWN) and ct[0]!="u": self.err(f"condition must be bool, got {ct}",s.cond)
            t_then=self.suite(s.then,scope); arms=[t_then]
            for ec,es in (s.elifs or []):
                cet=self.expr(ec,scope)
                if cet not in (BOOL,UNKNOWN): self.err(f"condition must be bool, got {cet}",ec)
                arms.append(self.suite(es,scope))
            if s.else_ is not None: arms.append(self.suite(s.else_,scope))
            ct2=arms[0]
            for t in arms[1:]:
                ct2=merge_types(ct2,t)
            return ct2
        if isinstance(s,WhileStmt):
            ct=self.expr(s.cond,scope)
            if ct not in (BOOL,UNKNOWN): self.err(f"while condition must be bool, got {ct}",s.cond)
            self.suite(s.body,scope); return None
        if isinstance(s,ForStmt):
            it_ty=self.expr(s.iter,scope); elem=UNKNOWN; key_ty=UNKNOWN; val_ty=UNKNOWN
            if it_ty[0]=="list": elem=it_ty[1]
            elif it_ty[0]=="map": key_ty,val_ty=it_ty[1],it_ty[2]
            elif it_ty[0]=="set": elem=it_ty[1]
            elif it_ty[0]=="p" and it_ty[1]=="str": elem=STR
            if len(s.bindings)==1:
                b=s.bindings[0]; ty=elem if it_ty[0] in ("list","set","p") else UNKNOWN
                if b.kind=="name":
                    sym=self._lookup(scope,b.name)
                    if sym is None and b.name:
                        scope.define(Symbol(b.name,SymKind.LOCAL,b,scope)); sym=scope.lookup(b.name)
                    if sym is not None:
                        if b.type_ is not None:
                            et=self._atype(b.type_)
                            if not compat(elem,et): self.err("for binding type mismatch",b)
                            sym.ty=et
                        else: sym.ty=ty
            else:
                for i,b in enumerate(s.bindings):
                    if b.kind!="name": continue
                    if it_ty[0]=="map": ty=key_ty if i==0 else val_ty
                    elif it_ty[0]=="list": ty=INT if i==0 else elem
                    else: ty=UNKNOWN
                    sym=self._lookup(scope,b.name)
                    if sym is None and b.name:
                        scope.define(Symbol(b.name,SymKind.LOCAL,b,scope)); sym=scope.lookup(b.name)
                    if sym is not None:
                        if b.type_ is not None:
                            et=self._atype(b.type_)
                            if not compat(ty,et): self.err("for binding type mismatch",b)
                            sym.ty=et
                        else: sym.ty=ty
            body_scope=scope.child("block"); self.suite(s.body,body_scope); return None
        if isinstance(s,MatchStmt):
            scr=self.expr(s.expr,scope); arms=[]
            for arm in (s.arms or []):
                if arm.is_else:
                    cs=scope.child("block")
                    if isinstance(arm.body,Suite): arms.append(self.suite(arm.body,cs))
                    elif arm.body is not None: arms.append(self.expr(arm.body,cs))
                    else: arms.append(NIL)
                    continue
                cs=scope.child("block"); self._bindpat(arm.pattern,scr,cs,scope)
                if arm.guard is not None:
                    gt=self.expr(arm.guard,cs)
                    if gt not in (BOOL,UNKNOWN): self.err(f"guard must be bool, got {gt}",arm.guard)
                if isinstance(arm.body,Suite): bt=self.suite(arm.body,cs)
                elif arm.body is not None: bt=self.expr(arm.body,cs)
                else: bt=NIL
                arms.append(bt)
            ct=arms[0] if arms else NIL
            for t in arms[1:]:
                ct=merge_types(ct,t)
            return ct
        if isinstance(s,ReturnStmt):
            vt=self.expr(s.value,scope) if s.value is not None else NIL
            if self.cur_func is not None:
                dr=self.cur_func.get("ret")
                if dr is not None and vt not in (UNKNOWN,) and not compat(vt,dr):
                    self.err(f"return type mismatch: {vt} vs {dr}",s)
            return vt
        if isinstance(s,SpawnStmt):
            self.expr(s.expr,scope); return None
        if isinstance(s,AwaitStmt):
            self.expr(s.expr,scope); return None
        if isinstance(s,ExprStmt): return self.expr(s.expr,scope)
        if isinstance(s,(BreakStmt,ContinueStmt)): return None
        if isinstance(s,(FnDecl,TypeDecl,TraitDecl,UseDecl,LetDecl,VarDecl)): return None
        return None

    def _bindpat(self,pat,scrut,scope,parent):
        if pat.kind=="name":
            sym=self._lookup(scope,pat.value)
            if sym is None:
                scope.define(Symbol(pat.value,SymKind.LOCAL,pat,scope)); sym=scope.lookup(pat.value)
            if sym is not None: sym.ty=scrut if scrut is not None else UNKNOWN
        elif pat.kind=="variant":
            if scrut is not None and scrut[0]=="named":
                td=self.type_defs.get(scrut[1]); targs=scrut[2]; variant=None
                if td is not None:
                    for m in td.members:
                        if m.kind=="variant" and m.node.name==pat.name: variant=m.node
                if variant is not None:
                    vfs=variant.fields if variant.fields else [mm.node for mm in getattr(variant,"members",[]) if isinstance(mm.node,Field)]
                    for i,p in enumerate(pat.patterns or []):
                        if i<len(vfs):
                            f=vfs[i]
                            if f.type_ is not None:
                                ft=self._atype(f.type_); ft=self._sub(ft,td.tparams,targs)
                            else: ft=UNKNOWN
                        else: ft=UNKNOWN
                        self._bindpat(p,ft,scope,parent)
                else:
                    for p in (pat.patterns or []): self._bindpat(p,UNKNOWN,scope,parent)
            else:
                for p in (pat.patterns or []): self._bindpat(p,UNKNOWN,scope,parent)
        elif pat.kind=="tuple":
            if scrut is not None and scrut[0]=="tuple":
                for p,et in zip(pat.patterns or [],scrut[1]): self._bindpat(p,et,scope,parent)
            else:
                for p in (pat.patterns or []): self._bindpat(p,UNKNOWN,scope,parent)
        elif pat.kind=="named_field":
            if scrut is not None and scrut[0]=="named":
                td=self.type_defs.get(scrut[1]); targs=scrut[2]; field=None
                if td is not None:
                    for m in td.members:
                        if m.kind=="field" and m.node.name==pat.field_name: field=m.node
                if field is not None and field.type_ is not None:
                    ft=self._atype(field.type_); ft=self._sub(ft,td.tparams,targs)
                else: ft=UNKNOWN
                self._bindpat(pat.sub,ft,scope,parent)
            else:
                self._bindpat(pat.sub,UNKNOWN,scope,parent)

    def place(self,pl,scope):
        sym=self._lookup(scope,pl.name)
        if sym is not None and getattr(sym,"ty",None) is not None: ty=sym.ty
        elif pl.name in self.type_defs: ty=N(pl.name)
        elif pl.name in ("true","false"): ty=BOOL
        else: ty=UNKNOWN
        for part in pl.parts:
            if part[0]=="field": ty=self.field(ty,part[1],pl)
            elif part[0]=="index":
                idx=self.expr(part[1],scope); ty=self.idx(ty,idx)
        return ty
