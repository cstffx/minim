from tools.typecheck import FLOAT, INT, BOOL, UNKNOWN, STR, BYTES, NIL
from tools.wasm_encoder import *
from tools.wasm_encoder import _uleb128_static
from tools.nodes import *
from ..util import _unsupported
from tools.lexer import decode_escapes
from tools.resolve import Resolver, Scope, Symbol, SymKind


class LiteralsMixin:
    def _gen_lit(self, e, code, qname):
        if isinstance(e, IntLit):
            code += i64_const(int(e.value))
        elif isinstance(e, FloatLit):
            code += f64_const(float(e.value))
        elif isinstance(e, BoolLit):
            code += i64_const(1 if e.value else 0)
        elif isinstance(e, FStrLit):
            self._gen_fstring(e, code, qname)
        elif isinstance(e, (StrLit, RStrLit, MlStrLit)):
            ptr = self.str_offsets.get(id(e), 0)
            code += i32_const(ptr)
        elif isinstance(e, BytesLit):
            ptr = self.str_offsets.get(id(e), 0)
            code += i32_const(ptr)
        elif isinstance(e, NilLit):
            code += i64_const(0)
        elif isinstance(e, SetExpr):
            self._gen_set_literal(e, qname, code)
        elif isinstance(e, ItExpr):
            lmap = self.locals_map.get(qname, {})
            if "it" in lmap:
                code += local_get(lmap["it"])
            else:
                _unsupported("'it' fuera de una closure implicita", e)
        elif isinstance(e, SelfExpr):
            code += local_get(0)
        elif isinstance(e, BorrowExpr):
            self._gen_expr(e.operand, code, qname)
        else:
            return False
        return True

    def _gen_to_str(self, e, code, qname, prec=None):
        ty = self._tc_type(e, qname)
        while isinstance(ty, tuple) and ty[0] in ("opt", "res", "borrow"):
            ty = ty[1]
        ty = self._erase_task(ty)
        helpers = self._ensure_str_helpers()
        if isinstance(e, NilLit) or ty == ("p", "nil"):
            code += i32_const(self._str_ptr("nil"))
            return
        if isinstance(e, BoolLit):
            code += i32_const(self._str_ptr("true" if e.value else "false"))
            return
        if ty == FLOAT:
            self._gen_expr(e, code, qname)
            code += i32_const(6 if prec is None else prec)
            code += CALL(helpers["f64"])
            return
        self._gen_expr(e, code, qname)
        if ty in (INT, BOOL):
            code += CALL(helpers["i64"])
        elif ty == STR or ty == ("p", "bytes"):
            pass
        else:
            _unsupported(f"interpolar un valor de tipo {ty} en f-string", e)

    def _gen_fstring(self, e, code, qname):
        raw = e.value
        parts = []  # (kind, text/prec, expr)
        buf = []
        i = 0
        n = len(raw)
        while i < n:
            c = raw[i]
            if c == "{" and i + 1 < n and raw[i + 1] == "{":
                buf.append("{")
                i += 2
                continue
            if c == "}" and i + 1 < n and raw[i + 1] == "}":
                buf.append("}")
                i += 2
                continue
            if c == "{":
                if buf:
                    parts.append(("lit", decode_escapes("".join(buf))))
                    buf = []
                depth = 1
                j = i + 1
                quote = None
                while j < n and depth:
                    ch = raw[j]
                    if quote:
                        if ch == "\\":
                            j += 2
                            continue
                        if ch == quote:
                            quote = None
                    elif ch in ("'", '"'):
                        quote = ch
                    elif ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                if depth != 0:
                    buf.append(c)
                    i += 1
                    continue
                inner = raw[i + 1:j]
                fmt = None
                # split format spec on the last top-level ':'
                d = 0
                q = None
                for k, ch in enumerate(inner):
                    if q:
                        if ch == "\\":
                            continue
                        if ch == q:
                            q = None
                    elif ch in ("'", '"'):
                        q = ch
                    elif ch in "([{":
                        d += 1
                    elif ch in ")]}":
                        d -= 1
                    elif ch == ":" and d == 0:
                        fmt = inner[k + 1:]
                        inner = inner[:k]
                        break
                parts.append(("expr", fmt, inner.strip()))
                i = j + 1
                continue
            buf.append(c)
            i += 1
        if buf:
            parts.append(("lit", decode_escapes("".join(buf))))
        if not parts:
            code += i32_const(self._str_ptr(""))
            return
        acc = None
        helpers = self._ensure_str_helpers()
        from tools.parser import parse as _parse
        from tools.nodes import ExprStmt as _ExprStmt
        for part in parts:
            if part[0] == "lit":
                ptr = self._str_ptr(part[1])
                code += i32_const(ptr)
            else:
                fmt = part[1] or ""
                try:
                    prog = _parse(part[2])
                    ex = prog.stmts[0].expr
                except Exception:
                    _unsupported(f"la expresion interpolada {part[2]!r}", e)
                prec = None
                import re as _re
                m = _re.fullmatch(r"\.(\d+)f", fmt)
                if m:
                    prec = int(m.group(1))
                self._gen_to_str(ex, code, qname, prec)
            if acc is not None:
                code += CALL(helpers["concat"])
            acc = True
        return
