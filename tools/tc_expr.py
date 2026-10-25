import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.nodes import *
from tools.resolve import Resolver, Symbol, SymKind
from tools.tc_types import (
    INT, FLOAT, BOOL, STR, NIL, UNKNOWN, ERRT, BYTES, PTR, INT_WIDTHS, FLOAT_WIDTHS,
    L, M, O, R, N, V, F, TypeCheckError, _bound_name, _tyname, _struct_compat,
    compat, merge_types, apply, _subst_type,
)



class ExprMixin:
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
            if name in ("alloc",): return F((INT,),PTR,(),"alloc")
            if name in ("dealloc",): return F((PTR,),NIL,(),"dealloc")
            if name in ("memcpy",): return F((PTR,PTR,INT),NIL,(),"memcpy")
            if name in ("memset",): return F((PTR,INT,INT),NIL,(),"memset")
            if name in ("len",): return F((UNKNOWN,),INT,(),"len")
            if name in ("err",): return F((STR,INT),ERRT,(),"err",(False,True))
            if name in ("fs","env","io","net","json","time","rand","math","os","task","rc","arc"): return ("module",name)
            if name in self.module_aliases: return ("module",name)
            if name in self.type_defs or name in ("int","float","bool","str","bytes","nil","map","set","list","ptr"):
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
                if t[0] in ("res","opt"): return t[1]
                return t
            if op in ("-","~"): return self.expr(e.operand,scope)
            if op=="not":
                self.expr(e.operand,scope); return BOOL
            if op in ("spawn","await"):
                t=self.expr(e.operand,scope)
                if t[0]=="res": return t
                if op=="await" and t[0]=="named" and t[1]=="task" and t[2]:
                    return t[2][0]
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
            vals=[]; kts=[]
            for a in (e.items or []):
                v=a.value if isinstance(a,Arg) else a
                if isinstance(a,Arg) and a.is_named:
                    kts.append(self.expr(a.label,scope))
                vals.append(self.expr(v,scope))
            if kts:
                kt=kts[0]
                for t in kts[1:]:
                    if not compat(t,kt): kt=UNKNOWN
            else:
                kt=UNKNOWN
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
            merged=merge_types(tt,et)
            if merged==UNKNOWN and not compat(tt,et) and not compat(et,tt):
                self.err("if branches type mismatch",e)
            return merged
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
                ct=merge_types(ct,t)
            return ct
        if isinstance(e,OrBlock): return self.suite(e.body,scope)
        return UNKNOWN

    def binop(self,e,scope):
        op=e.op
        if op=="or":
            left_ty=self.expr(e.left,scope)
            if isinstance(e.right,OrBlock):
                if left_ty[0]=="res": it_ty=STR
                elif left_ty[0]=="opt": it_ty=UNKNOWN
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
                if base_ty[0] in ("res","opt"): base_ty=base_ty[1]
        return base_ty

    def typeslice(self,base):
        bt=base
        if bt[0]=="borrow": bt=bt[1]
        if bt[0]=="list": return base
        if bt==STR: return STR
        if bt==BYTES: return BYTES
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
        for tp in tparams:
            bound=self.generic_bounds.get((builtin,tp))
            if bound is None: continue
            actual=subst.get(tp)
            if actual is None: continue
            bname=_bound_name(bound)
            if not self.trait_satisfied(actual,bname):
                self.err(f"type {_tyname(actual)} does not satisfy {bname}",node)
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
        if builtin in ("alloc",): return PTR
        if builtin in ("dealloc",): return NIL
        if builtin in ("memcpy","memset"): return NIL
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
