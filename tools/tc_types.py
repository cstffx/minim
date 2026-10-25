import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.parser import parse
from tools.resolve import Resolver, Symbol, SymKind

INT=("p","int"); FLOAT=("p","float"); BOOL=("p","bool"); STR=("p","str"); PTR=("p","ptr")
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

def _bound_name(bound):
    if isinstance(bound,TypeName): return bound.name
    if isinstance(bound,Type) and isinstance(bound.node,TypeName): return bound.node.name
    return getattr(bound,"name",str(bound))

def _tyname(ty):
    if ty is None: return "?"
    if ty[0]=="p": return ty[1]
    if ty[0]=="named": return ty[1]
    if ty[0]=="list": return f"[{_tyname(ty[1])}]"
    if ty[0]=="map": return f"map[{_tyname(ty[1])}, {_tyname(ty[2])}]"
    if ty[0]=="set": return f"set[{_tyname(ty[1])}]"
    if ty[0]=="opt": return f"{_tyname(ty[1])}?"
    if ty[0]=="res": return f"{_tyname(ty[1])}!"
    if ty[0]=="tuple": return "(" + ", ".join(_tyname(t) for t in ty[1]) + ")"
    return str(ty)

class TypeCheckError(Exception):
    def __init__(self,msg,node=None):
        span=getattr(node,"span",None)
        loc=f"{span.line}:{span.col}" if span else "?"
        super().__init__(f"{loc}: {msg}")
        self.node=node

# Structural field tables, populated by TC. Minim has no inheritance: a product
# type is defined by its fields, so two differently-named products are
# compatible when their field names/types match exactly.
_STRUCT_FIELDS = {}
_SUM_TYPES = set()
_COMPAT_GUARD = set()

def _struct_compat(a,b):
    if a[1] in _SUM_TYPES or b[1] in _SUM_TYPES:
        return False
    fa=_STRUCT_FIELDS.get(a[1]); fb=_STRUCT_FIELDS.get(b[1])
    if fa is None or fb is None: return False
    if [n for n,_ in fa] != [n for n,_ in fb]: return False
    key=(a[1],b[1])
    if key in _COMPAT_GUARD: return True
    _COMPAT_GUARD.add(key)
    try:
        return all(compat(x,y) for (_,x),(_,y) in zip(fa,fb))
    finally:
        _COMPAT_GUARD.discard(key)

def compat(a,b):
    if a is None or b is None: return True
    if a==b: return True
    if a[0]=="u" or b[0]=="u": return True
    if a[0]=="borrow": a=a[1]
    if b[0]=="borrow": b=b[1]
    if a==b: return True
    if a[0]=="u" or b[0]=="u": return True
    # `task[T]` se representa con el propio valor en v0.1 (spawn/await
    # secuenciales), asi que es compatible con T en ambos sentidos.
    if a[0]=="named" and a[1]=="task" and a[2]: a=a[2][0]
    if b[0]=="named" and b[1]=="task" and b[2]: b=b[2][0]
    if a==b: return True
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
            if a[1]==b[1]:
                if len(a[2])!=len(b[2]): return False
                return all(compat(x,y) for x,y in zip(a[2],b[2]))
            return _struct_compat(a,b)
        if a[0]=="func": return True
    if a[0]=="named" and b[0]=="named":
        return _struct_compat(a,b)
    return False

def merge_types(a,b):
    """Least upper bound used for if/match/return branch joins.

    `nil` lifts to `T?` and `err` lifts to `T!`; this keeps the inference local
    (no constraint solver) while accepting the error/optional idioms.
    """
    if a is None: return b
    if b is None: return a
    if a==b: return a
    if a[0]=="u": return b
    if b[0]=="u": return a
    for cont in ("opt","res"):
        if a[0]==cont and compat(b,a): return a
        if b[0]==cont and compat(a,b): return b
    if a==("p","nil") and b==("p","nil"): return a
    if a==("p","nil"):
        if b==("err",): return b
        return b if b[0] in ("opt","res") else O(b)
    if b==("p","nil"):
        if a==("err",): return a
        return a if a[0] in ("opt","res") else O(a)
    if a==("err",): return b if b[0]=="res" else R(b)
    if b==("err",): return a if a[0]=="res" else R(a)
    if a[0]=="res" or b[0]=="res":
        return R(merge_types(a[1] if a[0]=="res" else a,
                          b[1] if b[0]=="res" else b))
    if a[0]=="opt" or b[0]=="opt":
        return O(merge_types(a[1] if a[0]=="opt" else a,
                           b[1] if b[0]=="opt" else b))
    if compat(a,b): return a
    if compat(b,a): return b
    return UNKNOWN

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

def _subst_type(ty,name,repl):
    if ty is None: return None
    if ty[0]=="named" and ty[1]==name and not ty[2]: return repl
    if ty[0]=="list": return ("list",_subst_type(ty[1],name,repl))
    if ty[0]=="map": return ("map",_subst_type(ty[1],name,repl),_subst_type(ty[2],name,repl))
    if ty[0]=="set": return ("set",_subst_type(ty[1],name,repl))
    if ty[0]=="tuple": return ("tuple",tuple(_subst_type(t,name,repl) for t in ty[1]))
    if ty[0] in ("opt","res","borrow"): return (ty[0],_subst_type(ty[1],name,repl))
    if ty[0]=="func":
        params=None if ty[1] is None else tuple(_subst_type(t,name,repl) for t in ty[1])
        return ("func",params,_subst_type(ty[2],name,repl),ty[3],ty[4],ty[5] if len(ty)>5 else ())
    if ty[0]=="named": return ("named",ty[1],tuple(_subst_type(t,name,repl) for t in ty[2]))
    return ty


class TypesMixin:
    def _register_structs(self):
        _STRUCT_FIELDS.clear(); _SUM_TYPES.clear()
        for name,td in self.type_defs.items():
            variants=[m.node for m in td.members if isinstance(m.node,Variant)]
            if variants:
                _SUM_TYPES.add(name)
                continue
            if td.tparams:
                continue
            fields=[]
            for m in td.members:
                if isinstance(m.node,Field):
                    f=m.node
                    ft=self._atype(f.type_) if f.type_ is not None else UNKNOWN
                    fields.append((f.name,ft))
            _STRUCT_FIELDS[name]=fields

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
        if isinstance(t,TypeName) and t.name in ("int","float","bool","str","bytes","nil","ptr"):
            _pm={"int":INT,"float":FLOAT,"bool":BOOL,"str":STR,"bytes":BYTES,"nil":NIL,"ptr":PTR}
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

    def is_copy(self, ty, seen=None):
        """Structural copyability (docs/DESIGN.md §7): primitives, strings,
        bytes, nil and tuples/products whose fields are all copyable are copy
        types. Collections (list/map/set), tasks and functions move."""
        if ty is None: return True
        if seen is None: seen=set()
        if ty[0]=="p": return True
        if ty[0] in ("borrow","func"): return True
        if ty[0] in ("list","map","set"): return False
        if ty[0]=="tuple":
            return all(self.is_copy(t,seen) for t in ty[1])
        if ty[0] in ("opt","res"):
            return self.is_copy(ty[1],seen)
        if ty[0]=="named":
            if ty[1] in seen: return False
            td=self.type_defs.get(ty[1])
            if td is None: return False
            seen=seen|{ty[1]}
            fields=[]
            for m in td.members:
                if m.kind=="field":
                    ft=self._atype(m.node.type_) if m.node.type_ is not None else UNKNOWN
                    fields.append(self._sub(ft,td.tparams,ty[2]))
                elif m.kind=="variant":
                    for fm in getattr(m.node,"members",[]) or []:
                        if isinstance(fm.node,Field):
                            ft=self._atype(fm.node.type_) if fm.node.type_ is not None else UNKNOWN
                            fields.append(self._sub(ft,td.tparams,ty[2]))
            return all(self.is_copy(t,seen) for t in fields)
        return False

    def _trait_method(self, trait_name, method_name, self_ty):
        tr=self.traits.get(trait_name)
        if tr is None: return None
        for sig in tr.methods:
            if sig.name!=method_name: continue
            def subst(t):
                if t is None: return UNKNOWN
                ty=self._atype(t)
                return _subst_type(ty,"Self",self_ty)
            params=[]
            for i,p in enumerate(sig.params):
                if p.name=="self": continue
                params.append(subst(p.type_))
            ret=subst(sig.ret) if sig.ret is not None else UNKNOWN
            return F(params,ret,(),None)
        return None

    def struct_fields(self, name, targs=()):
        td=self.type_defs.get(name)
        if td is None: return []
        out=[]
        for m in td.members:
            if m.kind=="field":
                ft=self._atype(m.node.type_) if m.node.type_ is not None else UNKNOWN
                out.append((m.node.name,self._sub(ft,td.tparams,targs)))
        return out

    def trait_satisfied(self, ty, trait_name):
        """Structural trait check: a type satisfies a trait when it exposes all
        the trait's methods (same names). Dispatch is static."""
        tr=self.traits.get(trait_name)
        if tr is None: return True
        if ty is None or ty[0] in ("u","var"): return True
        if ty[0]!="named": return False
        td=self.type_defs.get(ty[1])
        if td is None: return False
        names={m.node.name for m in td.members if m.kind=="fn"}
        return all(sig.name in names for sig in tr.methods)

    def field(self,base,name,node):
        bt=base
        if bt[0]=="borrow": bt=bt[1]
        if bt[0]=="var":
            tr=self.bounds.get(bt[1])
            if tr is not None:
                sig=self._trait_method(_bound_name(tr),name,bt)
                if sig is not None: return sig
            self.err(f"cannot access {name} on {bt}",node); return UNKNOWN
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
            if name in ("insert","add","push"): return F((E,),NIL,(),"set.insert")
            if name in ("remove","del"): return F((E,),NIL,(),"set.remove")
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
        if bt==STR: return STR
        if bt==BYTES: return INT
        if bt[0]=="map": return bt[2]
        if bt[0]=="tuple":
            if len(bt[1])>0: return bt[1][0]
            return UNKNOWN
        return UNKNOWN
