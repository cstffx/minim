import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.parser import parse
from tools.resolve import Resolver, Symbol, SymKind

INT=("p","int"); FLOAT=("p","float"); BOOL=("p","bool"); STR=("p","str")
NIL=("p","nil"); UNKNOWN=("u",); ERRT=("err",); BYTES=("p","bytes")
# Explicit widths are accepted as spellings of the default machine types.
INT_WIDTHS={"i8","i16","i32","i64","u8","u16","u32","u64"}
FLOAT_WIDTHS={"f32","f64"}
def L(t): return ("list",t)
def M(k,v): return ("map",k,v)
def O(t): return ("opt",t)
def R(t): return ("res",t)
def N(name,args=()): return ("named",name,tuple(args))
def V(name): return ("var",name)
def F(params,ret,tparams=(),builtin=None,defaults=()):
    return ("func", (tuple(params) if params is not None else None), ret, tuple(tparams), builtin, tuple(defaults))

class TypeCheckError(Exception):
    def __init__(self,msg,node=None):
        span=getattr(node,"span",None)
        loc=f"{span.line}:{span.col}" if span else "?"
        super().__init__(f"{loc}: {msg}")
        self.node=node

def compat(a,b):
    if a is None or b is None: return True
    if a==b: return True
    if a[0]=="u" or b[0]=="u": return True
    if a[0]=="borrow": a=a[1]
    if b[0]=="borrow": b=b[1]
    if a==b: return True
    if a[0]=="u" or b[0]=="u": return True
    if b[0] in ("opt","res") and compat(a,b[1]): return True
    if a==("p","nil") and (b[0] in ("opt","res") or b==("p","nil")): return True
    if a==("err",) and b[0]=="res": return True
    if a==("p","int") and b==("p","float"): return True
    if a[0]==b[0]:
        if a[0] in ("list","set","opt","res","borrow"): return compat(a[1],b[1])
        if a[0]=="map": return compat(a[1],b[1]) and compat(a[2],b[2])
        if a[0]=="tuple":
            if len(a[1])!=len(b[1]): return False
            return all(compat(x,y) for x,y in zip(a[1],b[1]))
        if a[0]=="named":
            if a[1]!=b[1] or len(a[2])!=len(b[2]): return False
            return all(compat(x,y) for x,y in zip(a[2],b[2]))
        if a[0]=="func": return True
    return False

def apply(ty,subst):
    if ty is None: return None
    if ty[0]=="var" and ty[1] in subst: return apply(subst[ty[1]],subst)
    if ty[0]=="list": return ("list",apply(ty[1],subst))
    if ty[0]=="map": return ("map",apply(ty[1],subst),apply(ty[2],subst))
    if ty[0]=="set": return ("set",apply(ty[1],subst))
    if ty[0]=="tuple": return ("tuple",tuple(apply(t,subst) for t in ty[1]))
    if ty[0]=="func":
        params=None if ty[1] is None else tuple(apply(t,subst) for t in ty[1])
        ret=apply(ty[2],subst) if ty[2] is not None else None
        defaults=ty[5] if len(ty)>5 else ()
        return ("func",params,ret,ty[3],ty[4],defaults)
    if ty[0] in ("opt","res","borrow"): return (ty[0],apply(ty[1],subst))
    if ty[0]=="named": return ("named",ty[1],tuple(apply(t,subst) for t in ty[2]))
    return ty

class TC:
    def __init__(self,program):
        self.program=program
        self.errors=[]
        self.resolver=Resolver(program)
        self.module_scope,res_errs=self.resolver.resolve()
        for e in res_errs:
            self.errors.append(TypeCheckError(str(e),getattr(e,"node",None)))
        self.type_defs={s.name:s for s in program.stmts if isinstance(s,TypeDecl)}
        self.module_aliases=dict(getattr(program,"merged_modules",{}))
        self.cur_type=None; self.cur_func=None; self.tvs=set(); self.mono=set()
        self._register()
    def err(self,msg,node=None): self.errors.append(TypeCheckError(msg,node))
    def _register(self):
        for s in self.program.stmts:
            if isinstance(s,FnDecl):
                sc=self.resolver.func_scopes.get(id(s))
                if sc is None:
                    sc=self.module_scope.child("func",owner=s); self.resolver.func_scopes[id(s)]=sc
                sym=self.module_scope.lookup(s.name)
                if sym is not None: sym.ty=self._ftype(s,sc,None)
        for s in self.program.stmts:
            if isinstance(s,TypeDecl):
                ts=self.resolver.type_scopes.get(id(s))
                if ts is None: continue
                for m in s.members:
                    n=m.node
                    if isinstance(n,FnDecl):
                        fs=None
                        for c in getattr(ts,"children",[]):
                            if getattr(c,"owner",None) is n: fs=c
                        if fs is None: fs=ts.child("func",owner=n)
                        sym=ts.lookup(n.name)
                        if sym is not None: sym.ty=self._ftype(n,fs,s.name)
    def _ftype(self,f,scope,selftype):
        tps=[t.name for t in (f.tparams or [])]
        old=self.tvs; self.tvs=self.tvs | set(tps)
        params=[]
        defaults=[]
        for p in f.params:
            if p.name=="self":
                pt=self._atype(p.type_) if p.type_ is not None else (N(selftype) if selftype else UNKNOWN)
            else:
                pt=self._atype(p.type_) if p.type_ is not None else UNKNOWN
            params.append(pt)
            defaults.append(p.default is not None)
        ret=self._atype(f.ret) if f.ret is not None else None
        self.tvs=old
        return F(params,ret,tuple(tps),None,tuple(defaults))
    def _atype(self,t):
        if isinstance(t,TypeName) and t.name in ("int","float","bool","str","bytes","nil"):
            _pm={"int":INT,"float":FLOAT,"bool":BOOL,"str":STR,"bytes":BYTES,"nil":NIL}
            return _pm[t.name]
        if isinstance(t,TypeName) and t.name in INT_WIDTHS:
            return INT
        if isinstance(t,TypeName) and t.name in FLOAT_WIDTHS:
            return FLOAT
        if isinstance(t,TypeName):
            if t.name in self.tvs: return V(t.name)
            return N(t.name,[self._atype(a) for a in (t.args or [])])
        if isinstance(t,TypeList): return ("list",self._atype(t.inner))
        if isinstance(t,TypeMap): return ("map",self._atype(t.key),self._atype(t.val))
        if isinstance(t,TypeSet): return ("set",self._atype(t.inner))
        if isinstance(t,TypeBorrow): return ("borrow",self._atype(t.inner))
        if isinstance(t,TypeTuple): return ("tuple",tuple(self._atype(x) for x in t.items))
        if isinstance(t,TypeFunc):
            ps=[self._atype(x) for x in t.params]; r=self._atype(t.ret) if t.ret is not None else UNKNOWN
            return F(ps,r)
        if isinstance(t,TypeParen):
            if t.inner is None: return NIL
            return self._atype(t.inner)
        if isinstance(t,TypeSuffix):
            b=self._atype(t.base)
            if t.suffix=="?": return O(b)
            if t.suffix=="!": return R(b)
        if isinstance(t,Type): return self._atype(t.node)
        return UNKNOWN
    def _lookup(self,scope,name):
        sym=scope.lookup(name) if hasattr(scope,"lookup") else None
        if sym is None and scope is not self.module_scope:
            sym=self.module_scope.lookup(name)
        return sym
    def _sub(self,ty,tparams,targs):
        m={}
        for i,tp in enumerate(tparams or []):
            name=tp.name if hasattr(tp,"name") else tp
            if i<len(targs): m[name]=targs[i]
        return apply(ty,m)
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
                if not compat(t,ct2) and not compat(ct2,t): ct2=UNKNOWN
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
                if not compat(t,ct) and not compat(ct,t): ct=UNKNOWN
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
    def field(self,base,name,node):
        bt=base
        if bt[0]=="borrow": bt=bt[1]
        if bt[0]=="tuple":
            try: i=int(name)
            except (TypeError,ValueError): i=-1
            if 0 <= i < len(bt[1]): return bt[1][i]
            self.err(f"tuple index out of range: {name}",node); return UNKNOWN
        if bt[0]=="module":
            mod=bt[1]; bn=f"{mod}.{name}"
            if mod in self.module_aliases:
                if name.startswith("_"):
                    self.err(f"{name!r} is private to module {mod!r}",node)
                    return UNKNOWN
                sym=self.module_scope.lookup(bn)
                if sym is not None:
                    if getattr(sym,"ty",None) is not None: return sym.ty
                    if isinstance(sym.node,FnDecl):
                        fs=self.resolver.func_scopes.get(id(sym.node)) or self.module_scope
                        self._func(sym.node,fs,None)
                        if getattr(sym,"ty",None) is not None: return sym.ty
                    if sym.kind==SymKind.TYPE: return N(bn,())
                return UNKNOWN
            if mod=="fs":
                if name=="read": return F((STR,),R(STR),(),bn)
                if name=="write": return F((STR,STR),R(NIL),(),bn)
                if name=="lines": return F((STR,),R(L(STR)),(),bn)
                if name=="exists": return F((STR,),BOOL,(),bn)
                if name=="ls": return F((STR,),R(L(STR)),(),bn)
            if mod=="env":
                if name=="arg": return F((INT,),O(STR),(),bn)
                if name=="args": return L(STR)
                if name=="get": return F((STR,),O(STR),(),bn)
                if name=="set": return F((STR,STR),NIL,(),bn)
            if mod=="net":
                if name in ("get","post"): return F((STR,) if name=="get" else (STR,STR),R(STR),(),bn)
                if name=="serve": return F((INT,UNKNOWN),R(NIL),(),bn)
            if mod=="json":
                if name=="parse": return F((STR,),R(V("T")),("T",),bn)
                if name=="str": return F((UNKNOWN,),STR,(),bn)
            if mod=="time":
                if name=="now": return F((),INT,(),bn)
                if name=="sleep": return F((INT,),NIL,(),bn)
            if mod in ("rc","arc"):
                if name=="new": return F((UNKNOWN,),N(mod,(UNKNOWN,)),(),bn)
            return F(None,UNKNOWN,(),bn)
        if bt[0]=="p" and bt[1]=="str":
            if name=="len": return F((),INT,(),"str.len")
            if name in ("words","lines"): return F((),L(STR),(),f"str.{name}")
            if name=="split": return F((STR,),L(STR),(),"str.split")
            if name in ("trim","lower","upper"): return F((),STR,(),f"str.{name}")
            if name=="strip": return F((STR,),STR,(),"str.strip")
            if name in ("contains","starts","ends"): return F((STR,),BOOL,(),f"str.{name}")
            if name=="replace": return F((STR,STR),STR,(),"str.replace")
            if name=="parse": return F((),R(V("T")),("T",),"str.parse")
            if name=="bytes": return F((),L(("p","u8")),(),"str.bytes")
            if name=="join": return F((STR,),STR,(),"str.join")
            return F((),UNKNOWN,(),f"str.{name}")
        if bt[0]=="list":
            E=bt[1]
            if name=="len": return F((),INT,(),"list.len")
            if name=="push": return F((E,),NIL,(),"list.push")
            if name=="pop": return F((),O(E),(),"list.pop")
            if name=="get": return F((INT,),O(E),(),"list.get")
            if name in ("first","last"): return F((),O(E),(),f"list.{name}")
            if name=="contains": return F((E,),BOOL,(),"list.contains")
            if name=="reverse": return F((),L(E),(),"list.reverse")
            if name=="sort": return F((),NIL,(),"list.sort")
            if name=="slice": return F((INT,INT),L(E),(),"list.slice")
            if name=="map": return F((F((E,),UNKNOWN,(),None),),L(UNKNOWN),(),"list.map")
            if name=="filter": return F((F((E,),BOOL,(),None),),L(E),(),"list.filter")
            if name=="fold": return F((UNKNOWN,F((UNKNOWN,E),UNKNOWN,(),None)),UNKNOWN,(),"list.fold")
            if name=="any": return F((F((E,),BOOL,(),None),),BOOL,(),"list.any")
            if name=="all": return F((F((E,),BOOL,(),None),),BOOL,(),"list.all")
            if name=="find": return F((F((E,),BOOL,(),None),),O(E),(),"list.find")
            if name=="join": return F((STR,),STR,(),"list.join")
            if name=="count": return F((),INT,(),"list.count")
            if name=="top": return F((INT,),L(E),(),"list.top")
            return F((),UNKNOWN,(),f"list.{name}")
        if bt[0]=="map":
            K,VV=bt[1],bt[2]
            if name=="len": return F((),INT,(),"map.len")
            if name=="get": return F((K,),O(VV),(),"map.get")
            if name=="has": return F((K,),BOOL,(),"map.has")
            if name=="del": return F((K,),NIL,(),"map.del")
            if name=="keys": return F((),L(K),(),"map.keys")
            if name=="values": return F((),L(VV),(),"map.values")
            if name=="items": return F((),L(("tuple",(K,VV))),(),"map.items")
            if name=="top": return F((INT,),L(("tuple",(K,VV))),(),"map.top")
            return F((),UNKNOWN,(),f"map.{name}")
        if bt[0]=="set":
            E=bt[1]
            if name=="len": return F((),INT,(),"set.len")
            if name=="contains": return F((E,),BOOL,(),"set.contains")
            return F((),UNKNOWN,(),f"set.{name}")
        if bt[0]=="named":
            td=self.type_defs.get(bt[1]); targs=bt[2]
            if td is not None:
                for m in td.members:
                    if m.kind=="field" and m.node.name==name:
                        ft=self._atype(m.node.type_) if m.node.type_ is not None else UNKNOWN
                        return self._sub(ft,td.tparams,targs)
                for m in td.members:
                    if m.kind=="variant" and m.node.name==name:
                        v=m.node; pts=[]
                        vfs=v.fields if v.fields else [mm.node for mm in getattr(v,"members",[]) if isinstance(mm.node,Field)]
                        for f in vfs:
                            ft=self._atype(f.type_) if f.type_ is not None else UNKNOWN
                            ft=self._sub(ft,td.tparams,targs); pts.append(ft)
                        return F(pts,N(bt[1],targs),[],None)
                for m in td.members:
                    if m.kind=="fn" and m.node.name==name:
                        f=m.node; ft=self._ftype(f,None,bt[1])
                        params=ft[1]
                        if f.params and f.params[0].name=="self": params=params[1:]
                        ret=ft[2]
                        ret=self._sub(ret,td.tparams,targs) if ret is not None else None
                        params=tuple(self._sub(p,td.tparams,targs) for p in params)
                        defaults=ft[5] if len(ft)>5 else ()
                        if f.params and f.params[0].name=="self":
                            defaults=defaults[1:]
                        return F(params,ret,ft[3],None,defaults)
            if bt[1] in ("rc","arc"):
                T=bt[2][0] if bt[2] else UNKNOWN
                if name=="get": return F((),T,(),f"{bt[1]}.get")
                if name=="set": return F((T,),NIL,(),f"{bt[1]}.set")
            self.err(f"no field {name} on {bt[1]}",node); return UNKNOWN
        if bt[0]=="u": return UNKNOWN
        self.err(f"cannot access {name} on {base}",node); return UNKNOWN
    def idx(self,base,i):
        bt=base
        if bt[0]=="borrow": bt=bt[1]
        if bt[0]=="list": return bt[1]
        if bt[0]=="str": return STR
        if bt[0]=="map": return bt[2]
        if bt[0]=="tuple":
            if len(bt[1])>0: return bt[1][0]
            return UNKNOWN
        return UNKNOWN
    def expr(self,e,scope):
        if isinstance(e,IntLit): return INT
        if isinstance(e,FloatLit): return FLOAT
        if isinstance(e,(StrLit,FStrLit,RStrLit,MlStrLit)): return STR
        if isinstance(e,BytesLit): return BYTES
        if isinstance(e,BoolLit): return BOOL
        if isinstance(e,NilLit): return NIL
        if isinstance(e,NameExpr):
            name=e.name
            if name in ("true","false"): return BOOL
            if name in ("__continue__","__break__"): return BOOL
            if name=="nil": return NIL
            if name in ("pi","e"): return FLOAT
            if name in ("print","eprint","assert","panic"): return F(None,NIL,(),name)
            if name in ("range",): return F((INT,INT),("list",INT),(),"range")
            if name in ("min","max"): return F((UNKNOWN,UNKNOWN),UNKNOWN,(),name)
            if name in ("abs",): return F((UNKNOWN,),UNKNOWN,(),"abs")
            if name in ("str",): return F((UNKNOWN,),STR,(),"str")
            if name in ("int",): return F((UNKNOWN,),INT,(),"int")
            if name in ("float",): return F((UNKNOWN,),FLOAT,(),"float")
            if name in ("drop",): return F((UNKNOWN,),NIL,(),"drop")
            if name in ("copy",): return F((UNKNOWN,),UNKNOWN,(),"copy")
            if name in ("len",): return F((UNKNOWN,),INT,(),"len")
            if name in ("err",): return F((STR,INT),ERRT,(),"err",(False,True))
            if name in ("fs","env","io","net","json","time","rand","math","os","task","rc","arc"): return ("module",name)
            if name in self.module_aliases: return ("module",name)
            if name in self.type_defs or name in ("int","float","bool","str","bytes","nil","map","set","list"):
                return N(name,())
            sym=self._lookup(scope,name)
            if sym is None:
                self.err(f"unbound name {name!r}",e); return UNKNOWN
            if getattr(sym,"ty",None) is not None: return sym.ty
            if sym.kind in (SymKind.FUNC,SymKind.METHOD,SymKind.ASSOC) and isinstance(sym.node,FnDecl):
                fs=self.resolver.func_scopes.get(id(sym.node))
                if fs is None: fs=scope
                self._func(sym.node,fs,self.cur_type)
                if getattr(sym,"ty",None) is not None: return sym.ty
            if sym.kind==SymKind.TYPE: return N(sym.name,())
            return UNKNOWN
        if isinstance(e,SelfExpr):
            if self.cur_type is not None: return N(self.cur_type)
            return UNKNOWN
        if isinstance(e,ItExpr):
            sym=self._lookup(scope,"it")
            if sym is not None and getattr(sym,"ty",None) is not None: return sym.ty
            return UNKNOWN
        if isinstance(e,BorrowExpr): return ("borrow",self.expr(e.operand,scope))
        if isinstance(e,UnaryOp):
            op=e.op
            if op=="?":
                t=self.expr(e.operand,scope)
                if t[0]=="res": return t[1]
                return t
            if op in ("-","~"): return self.expr(e.operand,scope)
            if op=="not":
                self.expr(e.operand,scope); return BOOL
            if op in ("spawn","await"):
                t=self.expr(e.operand,scope)
                if t[0]=="res": return t
                return t
            return self.expr(e.operand,scope)
        if isinstance(e,BinOp): return self.binop(e,scope)
        if isinstance(e,Postfix): return self.postfix(e,scope)
        if isinstance(e,TupleExpr): return ("tuple",tuple(self.expr(x,scope) for x in e.items))
        if isinstance(e,ListExpr):
            its=[self.expr(a.value if isinstance(a,Arg) else a,scope) for a in (e.items or [])]
            if not its: return L(UNKNOWN)
            ct=its[0]
            for t in its[1:]:
                if not compat(t,ct): ct=UNKNOWN
            return L(ct)
        if isinstance(e,MapExpr):
            vals=[]; has_named=False
            for a in (e.items or []):
                v=a.value if isinstance(a,Arg) else a
                if isinstance(a,Arg) and a.is_named: has_named=True
                vals.append(self.expr(v,scope))
            kt=STR if has_named else UNKNOWN
            vt=vals[0] if vals else UNKNOWN
            for t in vals[1:]:
                if not compat(t,vt): vt=UNKNOWN
            return M(kt,vt)
        if isinstance(e,SetExpr):
            its=[self.expr(a.value if isinstance(a,Arg) else a,scope) for a in (e.items or [])]
            if not its: return ("set",UNKNOWN)
            ct=its[0]
            for t in its[1:]:
                if not compat(t,ct): ct=UNKNOWN
            return ("set",ct)
        if isinstance(e,Lambda):
            ls=scope.child("block"); pts=[]
            hint=getattr(e,"_it_hint",None)
            for p in e.params:
                pt=self._atype(p.type_) if p.type_ is not None else (hint if hint is not None else UNKNOWN)
                pts.append(pt)
                sym=ls.lookup(p.name) if hasattr(ls,"lookup") else None
                if sym is None:
                    ls.define(Symbol(p.name,SymKind.PARAM,p,ls)); sym=ls.lookup(p.name)
                if sym is not None: sym.ty=pt
            bt=self.expr(e.body,ls)
            return F(pts,bt,(),None)
        if isinstance(e,MoveExpr) and isinstance(e.lambda_,Lambda):
            lam=e.lambda_; ls=scope.child("block"); pts=[]
            for p in lam.params:
                pt=self._atype(p.type_) if p.type_ is not None else UNKNOWN
                pts.append(pt)
                sym=ls.lookup(p.name)
                if sym is None:
                    ls.define(Symbol(p.name,SymKind.PARAM,p,ls)); sym=ls.lookup(p.name)
                if sym is not None: sym.ty=pt
            bt=self.expr(lam.body,ls)
            return F(pts,bt,(),None)
        if isinstance(e,IfExpr):
            ct=self.expr(e.cond,scope)
            if ct not in (BOOL,UNKNOWN): self.err(f"if condition must be bool, got {ct}",e.cond)
            tt=self.expr(e.then,scope); et=self.expr(e.else_,scope)
            if not compat(tt,et) and not compat(et,tt): self.err("if branches type mismatch",e)
            return tt if compat(et,tt) else et
        if isinstance(e,MatchExpr):
            scr=self.expr(e.expr,scope); arms=[]
            for arm in (e.arms or []):
                if arm.is_else:
                    if isinstance(arm.body,Suite): arms.append(self.suite(arm.body,scope.child("block")))
                    elif arm.body is not None: arms.append(self.expr(arm.body,scope))
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
                if not compat(t,ct) and not compat(ct,t): ct=UNKNOWN
            return ct
        if isinstance(e,OrBlock): return self.suite(e.body,scope)
        return UNKNOWN
    def binop(self,e,scope):
        op=e.op
        if op=="or":
            left_ty=self.expr(e.left,scope)
            if isinstance(e.right,OrBlock):
                if left_ty[0]=="res": it_ty=ERRT
                elif left_ty[0]=="opt": it_ty=NIL
                else: it_ty=left_ty
                cs=scope.child("block")
                sym=cs.lookup("it")
                if sym is None:
                    cs.define(Symbol("it",SymKind.LOCAL,None,cs)); sym=cs.lookup("it")
                if sym is not None: sym.ty=it_ty
                self.suite(e.right.body,cs)
                if left_ty[0]=="res": return left_ty[1]
                if left_ty[0]=="opt": return left_ty[1]
                return BOOL
            if isinstance(e.right,NameExpr) and e.right.name in ("__continue__","__break__"):
                if left_ty[0]=="res": return left_ty[1]
                if left_ty[0]=="opt": return left_ty[1]
                return BOOL
            right_ty=self.expr(e.right,scope)
            if left_ty[0]=="res":
                success=left_ty[1]
                if not compat(right_ty,success): self.err(f"or type mismatch: {right_ty} vs {success}",e)
                return success
            if left_ty[0]=="opt":
                success=left_ty[1]
                if not compat(right_ty,success): self.err(f"or type mismatch: {right_ty} vs {success}",e)
                return success
            self.expr(e.right,scope); return BOOL
        if op=="and":
            self.expr(e.left,scope); self.expr(e.right,scope); return BOOL
        if op in ("==","!=","<","<=" ,">",">=","is","is not","in"):
            self.expr(e.left,scope); self.expr(e.right,scope); return BOOL
        lt=self.expr(e.left,scope); rt=self.expr(e.right,scope)
        if lt[0] in ("opt","res"): lt=lt[1]
        if rt[0] in ("opt","res"): rt=rt[1]
        if lt==FLOAT or rt==FLOAT:
            if lt in (INT,FLOAT,UNKNOWN) and rt in (INT,FLOAT,UNKNOWN): return FLOAT
        if lt==INT and rt==INT: return INT
        if lt==STR or rt==STR:
            if op=="+": return STR
        if lt==UNKNOWN or rt==UNKNOWN: return UNKNOWN
        return lt
    def postfix(self,e,scope):
        # Flatten the postfix chain so auto-invocation of nullary properties is
        # context-aware (a trailing call in the chain suppresses it).
        ops_lists=[]
        cur=e
        while isinstance(cur,Postfix):
            ops_lists.append(cur.ops or [])
            cur=cur.base
        ops_lists.reverse()
        all_ops=[op for lst in ops_lists for op in lst]
        base_ty=self.expr(cur,scope)
        for i,op in enumerate(all_ops):
            if op[0]=="field":
                base_ty=self.field(base_ty,op[1],e)
                nxt=all_ops[i+1] if i+1 < len(all_ops) else None
                if (isinstance(base_ty,tuple) and base_ty[0]=="func"
                        and (base_ty[1] is None or len(base_ty[1])==0)
                        and not (nxt is not None and nxt[0] in ("call","typeargs"))):
                    base_ty=self.call(base_ty,[],scope,e)
            elif op[0]=="index":
                idx_ty=self.expr(op[1],scope) if not isinstance(op[1],str) else UNKNOWN
                base_ty=self.idx(base_ty,idx_ty)
            elif op[0]=="slice": base_ty=self.typeslice(base_ty)
            elif op[0]=="call":
                args=op[1] or []; base_ty=self.call(base_ty,args,scope,e)
            elif op[0]=="typeargs":
                tas=[self._atype(t) for t in (op[1] or [])]; base_ty=self.inst(base_ty,tas)
            elif op[0]=="as": base_ty=self._atype(op[1])
            elif op[0]=="?":
                if base_ty[0]=="res": base_ty=base_ty[1]
        return base_ty
    def typeslice(self,base):
        bt=base
        if bt[0]=="borrow": bt=bt[1]
        if bt[0]=="list": return base
        if bt[0]=="p" and bt[1]=="str": return STR
        return base
    def inst(self,base,tas):
        if base[0]=="named": return N(base[1],tas)
        if base[0]=="func" and base[3]:
            subst={tp:ta for tp,ta in zip(base[3],tas)}
            params=tuple(apply(p,subst) for p in (base[1] or ()))
            ret=apply(base[2],subst) if base[2] is not None else None
            defaults=base[5] if len(base)>5 else ()
            return F(params,ret,(),base[4],defaults)
        return base
    def call(self,base,args,scope,node):
        arg_types=[]
        params=base[1] if (base[0]=="func" and base[1] is not None) else []
        for i,a in enumerate(args):
            expr=a.value if isinstance(a,Arg) else a
            pt=params[i] if i < len(params) else None
            if (isinstance(pt,tuple) and pt[0]=="func" and pt[1] is not None
                    and not isinstance(expr,Lambda) and not (isinstance(expr,MoveExpr) and isinstance(expr.lambda_,Lambda))):
                fparams=pt[1] or ()
                elem=fparams[0] if fparams else UNKNOWN
                cs=scope.child("block")
                sym=cs.lookup("it")
                if sym is None:
                    cs.define(Symbol("it",SymKind.LOCAL,None,cs)); sym=cs.lookup("it")
                if sym is not None: sym.ty=elem
                t=self.expr(expr,cs)
                arg_types.append(F((elem,),t,(),None))
            else:
                if (isinstance(expr, Lambda) and isinstance(pt, tuple) and pt[0] == "func"
                        and pt[1] and expr.params and expr.params[0].type_ is None):
                    # implicit `it` closure: inherit the expected element type
                    expr._it_hint = pt[1][0]
                arg_types.append(self.expr(expr,scope))
        if base[0]=="named": return self.ctor(base,args,arg_types,scope,node)
        if base[0]!="func":
            if base[0]!="u": self.err(f"not callable: {base}",node)
            return UNKNOWN
        params=base[1]; ret=base[2]; tparams=base[3]; builtin=base[4]
        variadic=params is None
        if params is None: params=[]
        defaults=base[5] if len(base)>5 else ()
        # pad defaults to params length
        if len(defaults) < len(params):
            defaults=defaults + (False,)*(len(params)-len(defaults))
        subst={}
        if tparams:
            for i,pt in enumerate(params):
                if i<len(arg_types): self.unify(pt,arg_types[i],subst)
        if not variadic and len(arg_types) > len(params):
            self.err(f"expected {len(params)} arguments, got {len(arg_types)}",node)
        if not variadic and len(arg_types) < len(params):
            for i in range(len(arg_types), len(params)):
                if not (i < len(defaults) and defaults[i]):
                    self.err(f"expected {len(params)} arguments, got {len(arg_types)}",node)
                    break
        for i,at in enumerate(arg_types):
            if i<len(params):
                pt=apply(params[i],subst)
                if not compat(at,pt): self.err(f"argument type mismatch: {at} vs {pt}",node)
        if ret is not None: ret=apply(ret,subst)
        ret=self.special(builtin,base,arg_types,subst,ret)
        if ret is None: ret=UNKNOWN
        if tparams:
            tas=[subst.get(tp,V(tp)) for tp in tparams]
            self.mono.add((builtin if builtin else "?",tuple(str(t) for t in tas)))
        return ret
    def ctor(self,base,args,arg_types,scope,node):
        name=base[1]; targs=base[2]
        if name=="map":
            if len(targs)==2: return M(targs[0],targs[1])
            return M(UNKNOWN,UNKNOWN)
        if name=="set":
            if len(targs)>=1: return ("set",targs[0])
            return ("set",UNKNOWN)
        if name=="list":
            if len(targs)>=1: return L(targs[0])
            if arg_types: return L(arg_types[0])
            return L(UNKNOWN)
        if name in ("int","float","str","bytes"):
            if name=="int": return INT
            if name=="float": return FLOAT
            if name=="str": return STR
            if name=="bytes": return BYTES
        if name in self.type_defs:
            td=self.type_defs[name]
            fields=[m.node for m in td.members if m.kind=="field"]
            fmap={f.name:f for f in fields}; idx=0
            for a in args:
                if isinstance(a,Arg) and a.is_named and isinstance(a.label,NameExpr):
                    fname=a.label.name; f=fmap.get(fname)
                    if f is not None and f.type_ is not None:
                        et=self._sub(self._atype(f.type_),td.tparams,targs)
                        at=self.expr(a.value,scope)
                        if not compat(at,et): self.err(f"field {fname} type mismatch",a.value)
                    else:
                        if f is None: self.err(f"unknown field {fname} in {name}",a.value)
                        self.expr(a.value,scope)
                else:
                    val=a.value if isinstance(a,Arg) else a
                    if idx<len(fields):
                        f=fields[idx]; idx+=1
                        if f.type_ is not None:
                            et=self._sub(self._atype(f.type_),td.tparams,targs)
                            at=self.expr(val,scope)
                            if not compat(at,et): self.err(f"field {f.name} type mismatch",val)
                    else:
                        self.expr(val,scope)
            return N(name,targs)
        return N(name,targs)
    def special(self,builtin,base,arg_types,subst,ret):
        if builtin is None: return ret
        if builtin in ("min","max"): return arg_types[0] if arg_types else UNKNOWN
        if builtin=="abs": return arg_types[0] if arg_types else INT
        if builtin=="copy": return arg_types[0] if arg_types else UNKNOWN
        if builtin in ("int",): return INT
        if builtin in ("float",): return FLOAT
        if builtin in ("str",): return STR
        if builtin in ("len",): return INT
        if builtin=="range": return L(INT)
        if builtin in ("print","eprint","assert","panic","drop"): return NIL
        if builtin=="err": return ERRT
        if builtin=="list.map":
            if arg_types and arg_types[0][0]=="func":
                return L(arg_types[0][2] if arg_types[0][2] is not None else UNKNOWN)
            return ret if ret is not None else L(UNKNOWN)
        if builtin=="list.fold":
            return arg_types[0] if arg_types else UNKNOWN
        if builtin in ("str.parse",): return ret
        if builtin=="json.parse": return ret
        if builtin in ("rc.new","arc.new"):
            if arg_types: return N(builtin.split('.')[0],(arg_types[0],))
            return ret
        return ret
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
