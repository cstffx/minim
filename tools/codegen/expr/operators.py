from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class OperatorsMixin:
    def _gen_binop(self, e, code, qname):
        if not isinstance(e, BinOp):
            return False
        op = e.op
        if op == "or":
            left_ty = self._tc_type(e.left, qname)
            if isinstance(e.right, OrBlock):
                self._gen_or_block(e.left, e.right, code, qname)
                return True
            if isinstance(e.right, NameExpr) and e.right.name in ("__continue__", "__break__"):
                kind = "loop" if e.right.name == "__continue__" else "exit"
                self._gen_expr(e.left, code, qname)
                self._store_tmp_value(left_ty, code)
                if isinstance(left_ty, tuple) and left_ty[0] == "res":
                    code += GLOBAL_GET(self.err_flag_global)
                else:
                    code += GLOBAL_GET(self.list_val_i64)
                    code += i64_const(0)
                    code += I64_EQ
                code += bytes([0x04, 0x40])
                code += self._branch_to(kind)
                code += bytes([0x0B])
                self._load_tmp_value(left_ty, code)
                return True
            if isinstance(left_ty, tuple) and left_ty[0] == "res":
                inner = left_ty[1]
                self._gen_expr(e.left, code, qname)
                self._store_tmp_value(left_ty, code)
                code += GLOBAL_GET(self.err_flag_global)
                code += IF(self._wasm_type(inner))
                code += i32_const(0)
                code += GLOBAL_SET(self.err_flag_global)
                self._gen_expr(e.right, code, qname)
                code += bytes([0x05])  # else
                self._load_tmp_value(inner, code)
                code += bytes([0x0B])
            elif isinstance(left_ty, tuple) and left_ty[0] == "opt":
                inner = left_ty[1]
                self._gen_expr(e.left, code, qname)
                self._store_tmp_value(left_ty, code)
                if inner == FLOAT:
                    code += GLOBAL_GET(self.list_val_f64)
                    code += f64_const(0.0)
                    code += F64_EQ
                else:
                    code += GLOBAL_GET(self.list_val_i64)
                    code += i64_const(0)
                    code += I64_EQ
                code += IF(self._wasm_type(inner))  # if nil
                self._gen_expr(e.right, code, qname)
                code += bytes([0x05])  # else
                self._load_tmp_value(inner, code)
                code += bytes([0x0B])
            else:
                self._gen_expr(e.left, code, qname)
                code += i64_const(0)
                code += I64_NE
                code += IF(BLK_I64)
                code += i64_const(1)
                code += ELSE
                self._gen_expr(e.right, code, qname)
                code += END
            return True
        if op == "and":
            self._gen_expr(e.left, code, qname)
            code += i64_const(0)
            code += I64_NE
            code += IF(BLK_I64)
            self._gen_expr(e.right, code, qname)
            code += ELSE
            code += i64_const(0)
            code += END
            return True
        if op == "in":
            self._gen_contains(e.left, e.right, code, qname)
            code += bytes([0xAD])
            return True
        f = self._is_float(e, qname)
        self._gen_expr(e.left, code, qname)
        if not f and self._operand_is_ptr(e.left, qname):
            code += bytes([0xAC])
        self._gen_expr(e.right, code, qname)
        if not f and self._operand_is_ptr(e.right, qname):
            code += bytes([0xAC])
        op = e.op
        if f:
            if op == "+":
                code += F64_ADD
            elif op == "-":
                code += F64_SUB
            elif op == "*":
                code += F64_MUL
            elif op == "/":
                code += F64_DIV
            elif op == "<=":
                code += F64_LE
                code += bytes([0xAD])
            elif op == ">=":
                code += F64_GE
                code += bytes([0xAD])
            elif op == "<":
                code += F64_LT
                code += bytes([0xAD])
            elif op == ">":
                code += F64_GT
                code += bytes([0xAD])
            elif op == "==":
                code += F64_EQ
                code += bytes([0xAD])
            elif op == "!=":
                code += F64_NE
                code += bytes([0xAD])
            else:
                _unsupported(f"el operador binario '{op}' (float)", e)
        else:
            if op == "+":
                code += I64_ADD
            elif op == "-":
                code += I64_SUB
            elif op == "*":
                code += I64_MUL
            elif op == "/":
                code += I64_DIV_S
            elif op == "%":
                code += I64_REM_S
            elif op == "<=":
                code += I64_LE_S
                code += bytes([0xAD])
            elif op == ">=":
                code += I64_GE_S
                code += bytes([0xAD])
            elif op == "<":
                code += I64_LT_S
                code += bytes([0xAD])
            elif op == ">":
                code += I64_GT_S
                code += bytes([0xAD])
            elif op == "==":
                code += I64_EQ
                code += bytes([0xAD])
            elif op == "!=":
                code += I64_NE
                code += bytes([0xAD])
            elif op in ("is", "is not"):
                # identity: values are integers/pointers in v0.1
                code += I64_EQ
                if op == "is not":
                    code += bytes([0x45])
                code += bytes([0xAD])
            elif op == "&":
                code += bytes([0x83])
            elif op == "|":
                code += bytes([0x84])
            elif op == "^":
                code += bytes([0x85])
            elif op == "<<":
                code += bytes([0x86])
            elif op == ">>":
                code += bytes([0x87])
            elif op == "**":
                code += CALL(self._ensure_pow_helper())
            elif op == "//":
                code += I64_DIV_S
            else:
                _unsupported(f"el operador binario '{op}'", e)
        return True

    def _gen_unaryop(self, e, code, qname):
        if not isinstance(e, UnaryOp):
            return False
        if e.op == "-":
            if self._is_float(e, qname):
                code += f64_const(0.0)
                self._gen_expr(e.operand, code, qname)
                code += F64_SUB
            else:
                code += i64_const(0)
                self._gen_expr(e.operand, code, qname)
                code += I64_SUB
        elif e.op == "?":
            self._gen_try(e.operand, code, qname)
        elif e.op == "~":
            self._gen_expr(e.operand, code, qname)
            code += i64_const(-1)
            code += bytes([0x85])  # i64.xor
        elif e.op == "not":
            self._gen_expr(e.operand, code, qname)
            if self._tc_type(e.operand, qname) == FLOAT:
                code += f64_const(0.0)
                code += F64_EQ
            else:
                code += I64_EQZ
            code += bytes([0xAD])
        elif e.op in ("spawn", "await"):
            # v0.1: ejecucion secuencial; spawn evalua ya y await es
            # la identidad sobre el valor de la tarea.
            self._gen_expr(e.operand, code, qname)
        else:
            _unsupported(f"el operador unario '{e.op}'", e)
        return True
