from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class ControlMixin:
    def _gen_try(self, operand, code, qname):
        """`expr?`: propagate errors (T!) / nil (T?) by returning early."""
        ty = self._tc_type(operand, qname)
        if not (isinstance(ty, tuple) and ty[0] in ("res", "opt")):
            self._gen_expr(operand, code, qname)
            return
        inner = ty[1]
        self._gen_expr(operand, code, qname)
        self._store_tmp_value(ty, code)
        rty = getattr(self, "func_ret", {}).get(qname)
        if ty[0] == "res":
            code += GLOBAL_GET(self.err_flag_global)
            code += bytes([0x04, 0x40])  # if void
            self._zero_value(rty, code)
            code += RETURN
            code += bytes([0x0B])
        else:
            self._load_tmp_value(ty, code)
            if inner == FLOAT:
                code += f64_const(0.0)
                code += F64_EQ
            else:
                code += i64_const(0)
                code += I64_EQ
            code += bytes([0x04, 0x40])
            self._zero_value(rty, code)
            code += RETURN
            code += bytes([0x0B])
        self._load_tmp_value(ty, code)

    def _gen_or_block(self, left, block, code, qname):
        lty = self._tc_type(left, qname)
        is_res = isinstance(lty, tuple) and lty[0] == "res"
        is_opt = isinstance(lty, tuple) and lty[0] == "opt"
        inner = lty[1] if (is_res or is_opt) else lty
        self._gen_expr(left, code, qname)
        self._store_tmp_value(lty if (is_res or is_opt) else inner, code)
        if is_res:
            code += GLOBAL_GET(self.err_flag_global)
        elif inner == FLOAT:
            code += GLOBAL_GET(self.list_val_f64)
            code += f64_const(0.0)
            code += F64_EQ
        else:
            code += GLOBAL_GET(self.list_val_i64)
            code += i64_const(0)
            code += I64_EQ
        wt = self._wasm_type(inner) if inner not in (None, NIL) else WasmEncoder.I64
        code += IF(wt)
        self._open_block("if")
        if is_res:
            code += i32_const(0)
            code += GLOBAL_SET(self.err_flag_global)
            if "it" in self.locals_map.get(qname, {}):
                code += GLOBAL_GET(self.err_msg_global)
                code += local_set(self.locals_map[qname]["it"])
        self._gen_suite(block.body, code, qname, None, True)
        # A block ending in return/break/continue diverges; still leave a
        # value on the stack so wasm's static typing accepts the branch.
        last = block.body.stmts[-1] if getattr(block.body, "stmts", None) else None
        if last is None or isinstance(last, (ReturnStmt, BreakStmt, ContinueStmt)):
            self._zero_value(inner, code)
        code += ELSE
        self._load_tmp_value(lty if (is_res or is_opt) else inner, code)
        code += END
        self._close_block()

    def _gen_if_expr(self, e, code, qname):
        if not isinstance(e, IfExpr):
            return False
        cond = e.cond
        self._bool_cond(cond, code, qname)
        then_ty = self._tc_type(e.then, qname)
        wtype = self._wasm_type(then_ty) if then_ty is not None else WasmEncoder.I64
        code += IF(wtype)
        self._gen_expr(e.then, code, qname)
        code += ELSE
        self._gen_expr(e.else_, code, qname)
        code += END
        return True

    def _gen_match_expr(self, e, code, qname):
        if not isinstance(e, MatchExpr):
            return False
        self._gen_match_core(e.expr, e.arms, code, qname, None)
        return True
