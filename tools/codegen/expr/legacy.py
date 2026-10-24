from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class ExprMixinLegacy:
    def _type_from_tc(self, ty):
        if ty == FLOAT:
            return Type(TypeName("float", []))
        if ty == INT:
            return Type(TypeName("int", []))
        if ty == BOOL:
            return Type(TypeName("bool", []))
        if ty == STR:
            return Type(TypeName("str", []))
        if isinstance(ty, tuple) and ty[0] == "named":
            return Type(TypeName(ty[1], []))
        if isinstance(ty, tuple) and ty[0] == "list":
            return Type(TypeList(self._type_from_tc(ty[1])))
        return None

    def _type_is_ptr(self, ty):
        ty = self._erase_task(ty)
        if isinstance(ty, tuple):
            if ty[0] == "p":
                return ty[1] in ("str", "bytes")
            if ty[0] in ("opt", "res", "borrow"):
                return self._type_is_ptr(ty[1])
            if ty[0] in ("named", "list", "map", "set", "tuple", "func"):
                return True
        return False

    def _operand_is_ptr(self, e, qname):
        ty = self._tc_type(e, qname)
        if isinstance(ty, tuple):
            if ty[0] == "p":
                return ty[1] in ("str", "bytes")
            if ty[0] in ("opt", "res", "borrow"):
                return self._type_is_ptr(ty[1])
            if ty[0] in ("named", "list", "map", "set", "tuple", "func"):
                return True
        return False

    def _method_decl(self, type_name, method_name):
        for stmt in self.program.stmts:
            if isinstance(stmt, TypeDecl) and stmt.name == type_name:
                for m in stmt.members:
                    if isinstance(m.node, FnDecl) and m.node.name == method_name:
                        return m.node
        return None

    def _str_ptr(self, text):
        return self._intern_str(text)

    def _gen_module_access(self, e, code, qname):
        chain, cur = [], e
        while isinstance(cur, Postfix):
            chain.append(cur.ops or [])
            cur = cur.base
        flat = [op for ops in reversed(chain) for op in ops]
        if isinstance(cur, NameExpr) and flat and flat[0][0] == "field":
            qn = f"{cur.name}.{flat[0][1]}"
            known = (qn in self.func_index or qn in getattr(self, "module_globals", {})
                     or qn in self.struct_layouts or qn in self.sum_types)
            if (known and cur.name in getattr(self.tc, "module_aliases", {})
                    and flat[0][1].startswith("_")):
                known = False
            if known:
                rest = flat[1:]
                if not rest:
                    self._gen_expr(NameExpr(qn), code, qname)
                    return True
                rebuilt = NameExpr(qn)
                for op in rest:
                    rebuilt = Postfix(rebuilt, [op])
                self._gen_expr(rebuilt, code, qname)
                return True
        return False

    def _gen_cast(self, e, code, qname):
        if not (e.ops and e.ops[-1][0] == "as"):
            return False
        base = e.base
        if len(e.ops) > 1:
            base = Postfix(base, e.ops[:-1])
        src = self._tc_type(base, qname)
        tgt = self.tc._atype(e.ops[-1][1])
        if tgt == STR:
            self._gen_to_str(base, code, qname)
            return True
        self._gen_expr(base, code, qname)
        if tgt == FLOAT and src != FLOAT:
            code += bytes([0xB9])       # f64.convert_i64_s
        elif tgt == INT and src == FLOAT:
            code += bytes([0xB0])       # i64.trunc_f64_s
        elif tgt == BOOL:
            if src == FLOAT:
                code += f64_const(0.0)
                code += F64_NE
            else:
                code += i64_const(0)
                code += I64_NE
            code += bytes([0xAD])
        return True

    def _gen_parse_call(self, e, code, qname):
        # `str.parse[T]()`: field parse + typeargs + call
        if (isinstance(e.base, Postfix) and e.ops and e.ops[-1][0] == "call"
                and e.base.ops and e.base.ops[-1][0] == "typeargs"
                and isinstance(e.base.base, Postfix) and e.base.base.ops
                and e.base.base.ops[-1][0] == "field"
                and e.base.base.ops[-1][1] == "parse"):
            target = self.tc._atype(e.base.ops[-1][1][0])
            recv = e.base.base.base
            self._gen_expr(recv, code, qname)
            if target == FLOAT:
                code += CALL(self._ensure_parse_helpers()["f64"])
            else:
                code += CALL(self._ensure_parse_helpers()["i64"])
            return True
        return False

    def _gen_expr(self, e, code, qname):
        if isinstance(e, Postfix):
            if self._gen_module_access(e, code, qname):
                return
            if self._gen_cast(e, code, qname):
                return
            if self._gen_parse_call(e, code, qname):
                return
        if self._gen_lit(e, code, qname):
            return
        if self._gen_if_expr(e, code, qname):
            return
        if self._gen_lambda(e, code, qname):
            return
        if self._gen_move_lambda(e, code, qname):
            return
        if self._gen_match_expr(e, code, qname):
            return
        if self._gen_tuple_expr(e, code, qname):
            return
        if self._gen_map_literal(e, code, qname):
            return
        if self._gen_list_literal(e, code, qname):
            return
        if self._gen_name_expr(e, code, qname):
            return
        if self._gen_binop(e, code, qname):
            return
        if self._gen_unaryop(e, code, qname):
            return
        if isinstance(e, Postfix):
            self._gen_postfix(e, code, qname)
            return
        _unsupported(f"expresiones de tipo {type(e).__name__}", e)

    def _gen_postfix(self, e, code, qname):
        if self._gen_slice(e, code, qname):
            return
        if self._gen_index(e, code, qname):
            return
        if self._gen_list_push(e, code, qname):
            return
        if self._gen_field(e, code, qname):
            return
        if self._gen_call_expr(e, code, qname):
            return
        _unsupported(
            "esta forma de acceso/llamada (map, string methods, modulos "
            "como fs/env, closures, o metodos no registrados)", e)

    def _gen_call_expr(self, e, code, qname):
        if self._gen_str_builtin_method(e, code, qname):
            return True
        if self._gen_ctor_call(e, code, qname):
            return True
        if self._gen_str_method_call(e, code, qname):
            return True
        if self._gen_collection_method_call(e, code, qname):
            return True
        if self._gen_method_call(e, code, qname):
            return True
        if self._gen_function_call(e, code, qname):
            return True
        return False
