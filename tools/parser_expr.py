from tools.lexer import tokenize
from tools import nodes as A
from tools.nodes import Span
from tools.parser_types import ParseError



class ExprMixin:
    def expr(self):
        return self.or_expr()

    def or_expr(self):
        left = self.and_expr()
        rights = []
        while self.peek().type == "or":
            self.advance()
            if self.peek().type == "continue":
                self.advance()
                rights.append(("continue", None))
            elif self.peek().type == "break":
                self.advance()
                rights.append(("break", None))
            elif self.peek().type == "NEWLINE" and self.peek(1).type == "INDENT":
                # orBlock without colon
                suite = self.suite()
                rights.append(("orblock", A.OrBlock(suite)))
            elif self.peek().type == ":":
                self.match(":")
                suite = self.suite()
                rights.append(("orblock", A.OrBlock(suite)))
            else:
                r = self.and_expr()
                rights.append(("or", r))
        if not rights:
            return left
        # Represent as BinOp chain for simplicity, or a special node
        # Use a left-nested structure
        result = left
        for kind, val in rights:
            if kind == "or":
                result = A.BinOp("or", result, val)
            elif kind == "continue":
                result = A.BinOp("or", result, A.NameExpr("__continue__"))
            elif kind == "break":
                result = A.BinOp("or", result, A.NameExpr("__break__"))
            elif kind == "orblock":
                result = A.BinOp("or", result, val)  # placeholder
        return result

    def or_block(self):
        # orBlock = 'or' ':' suite  -- but 'or' already consumed by caller in some paths
        # This method assumes 'or' NOT yet consumed? Let's handle: caller consumed 'or'.
        self.expect(":")
        suite = self.suite()
        return A.OrBlock(suite)

    def and_expr(self):
        left = self.not_expr()
        while self.peek().type == "and":
            self.advance()
            right = self.not_expr()
            left = A.BinOp("and", left, right)
        return left

    def not_expr(self):
        if self.peek().type == "not":
            self.advance()
            operand = self.cmp_expr()
            return A.UnaryOp("not", operand)
        return self.cmp_expr()

    def cmp_expr(self):
        left = self.bitor_expr()
        while self.peek().type in ("==", "!=", "<", "<=", ">", ">=", "is", "in"):
            # handle 'is not'
            if self.peek().type == "is" and self.peek(1).type == "not":
                op = "is not"
                self.advance()
                self.advance()
            else:
                op = self.advance().type
            right = self.bitor_expr()
            left = A.BinOp(op, left, right)
        return left

    def bitor_expr(self):
        left = self.bitxor_expr()
        while self.peek().type == "|":
            self.advance()
            right = self.bitxor_expr()
            left = A.BinOp("|", left, right)
        return left

    def bitxor_expr(self):
        left = self.bitand_expr()
        while self.peek().type == "^":
            self.advance()
            right = self.bitand_expr()
            left = A.BinOp("^", left, right)
        return left

    def bitand_expr(self):
        left = self.shift_expr()
        while self.peek().type == "&":
            self.advance()
            right = self.shift_expr()
            left = A.BinOp("&", left, right)
        return left

    def shift_expr(self):
        left = self.range_expr()
        while self.peek().type in ("<<", ">>"):
            op = self.advance().type
            right = self.range_expr()
            left = A.BinOp(op, left, right)
        return left

    def range_expr(self):
        left = self.add_expr()
        if self.peek().type in ("..", "..="):
            op = self.advance().type
            right = self.add_expr()
            return A.BinOp(op, left, right)
        return left

    def add_expr(self):
        left = self.mul_expr()
        while self.peek().type in ("+", "-"):
            op = self.advance().type
            right = self.mul_expr()
            left = A.BinOp(op, left, right)
        return left

    def mul_expr(self):
        left = self.unary_expr()
        while self.peek().type in ("*", "/", "//", "%"):
            op = self.advance().type
            right = self.unary_expr()
            left = A.BinOp(op, left, right)
        return left

    def unary_expr(self):
        if self.peek().type in ("spawn", "await", "-", "~", "@"):
            op = self.advance().type
            operand = self.power_expr()
            result = A.UnaryOp(op, operand)
        else:
            result = self.power_expr()
        # ? suffix
        while self.peek().type == "?":
            self.advance()
            result = A.UnaryOp("?", result)
        return result

    def power_expr(self):
        base = self.postfix()
        if self.peek().type == "**":
            self.advance()
            exp = self.unary_expr()
            return A.BinOp("**", base, exp)
        return base

    def postfix(self):
        base = self.primary()
        while True:
            if self.peek().type == "?" and self.peek(1).type in (".", "(", "[", "as"):
                self.advance()
                base = A.UnaryOp("?", base)
            elif self.peek().type == ".":
                self.advance()
                if self.peek().type == "INT":
                    # tuple field: t.0, t.1
                    name = int(self.advance().value)
                else:
                    name = self.expect("NAME").value
                # type args? [ ... ] — handle as part of name for generics in calls
                # We'll attach as a special op
                base = A.Postfix(base, [("field", name)])
            elif self.peek().type == "(":
                self.advance()
                args = []
                if self.peek().type != ")":
                    args = self.args()
                self.expect(")")
                base = A.Postfix(base, [("call", args)])
            elif self.peek().type == "[":
                # Decide: type args [T, U] vs index/slice. `[T]` is only a
                # type-argument list when the matching `]` is followed by a
                # call; otherwise it is an index (`xs[i]`).
                depth = 1
                j = self.pos + 1
                while j < len(self.tokens) and depth:
                    if self.tokens[j].type == "[":
                        depth += 1
                    elif self.tokens[j].type == "]":
                        depth -= 1
                    j += 1
                is_typeargs = (depth == 0 and j < len(self.tokens)
                               and self.tokens[j].type == "(")
                if is_typeargs:
                    # type args
                    self.advance()
                    tas = [self.type()]
                    while self.match(","):
                        tas.append(self.type())
                    self.expect("]")
                    base = A.Postfix(base, [("typeargs", tas)])
                else:
                    self.advance()
                    if self.peek().type == ":":
                        self.advance()
                        end = None
                        if self.peek().type not in ("]",):
                            end = self.expr()
                        self.expect("]")
                        base = A.Postfix(base, [("slice", None, end)])
                    else:
                        idx = self.expr()
                        if self.peek().type == ":":
                            self.advance()
                            end = None
                            if self.peek().type != "]":
                                end = self.expr()
                            self.expect("]")
                            base = A.Postfix(base, [("slice", idx, end)])
                        else:
                            self.expect("]")
                            base = A.Postfix(base, [("index", idx)])
            elif self.peek().type == "as":
                self.advance()
                t = self.type()
                base = A.Postfix(base, [("as", t)])
            else:
                break
        return base

    def args(self):
        a = [self.arg()]
        while self.match(","):
            if self.peek().type == ")":
                break
            a.append(self.arg())
        return a

    def arg(self):
        # expr [ ':' expr ]
        val = self.expr()
        if self.peek().type == ":":
            self.advance()
            v2 = self.expr()
            return A.Arg(val, v2, True)
        return A.Arg(None, val, False)

    def primary(self):
        t = self.peek()
        if t.type == "INT":
            self.advance()
            return A.IntLit(t.value)
        if t.type == "FLOAT":
            self.advance()
            return A.FloatLit(t.value)
        if t.type == "STR":
            self.advance()
            return A.StrLit(t.value)
        if t.type == "FSTR":
            self.advance()
            return A.FStrLit(t.value)
        if t.type == "RSTR":
            self.advance()
            return A.RStrLit(t.value)
        if t.type == "BYTES":
            self.advance()
            return A.BytesLit(t.value)
        if t.type == "MLSTR":
            self.advance()
            return A.MlStrLit(t.value)
        if t.type == "true":
            self.advance()
            return A.BoolLit(True)
        if t.type == "false":
            self.advance()
            return A.BoolLit(False)
        if t.type == "nil":
            self.advance()
            return A.NilLit()
        if t.type == "NAME":
            self.advance()
            return A.NameExpr(t.value)
        if t.type == "self":
            self.advance()
            return A.SelfExpr()
        if t.type == "it":
            self.advance()
            return A.ItExpr()
        if t.type == "&":
            self.advance()
            operand = self.postfix()
            return A.BorrowExpr(operand)
        if t.type == "(":
            # tuple or grouped
            self.advance()
            if self.peek().type == ")":
                self.expect(")")
                return A.TupleExpr([])
            e = self.expr()
            if self.match(","):
                items = [e]
                while self.peek().type != ")":
                    items.append(self.expr())
                    if not self.match(","):
                        break
                self.expect(")")
                return A.TupleExpr(items)
            self.expect(")")
            return e
        if t.type == "[":
            self.advance()
            items = []
            if self.peek().type != "]":
                items = self.args()
            self.expect("]")
            return A.ListExpr(items)
        if t.type == "{":
            self.advance()
            items = []
            if self.peek().type != "}":
                items = self.args()
            self.expect("}")
            # `{1, 2}` is a set; `{"k": 1}` uses named args and is a map.
            if items and not any(isinstance(a, A.Arg) and a.is_named for a in items):
                return A.SetExpr(items)
            return A.MapExpr(items)
        if t.type == "move":
            self.advance()
            lam = self.lambda_()
            return A.MoveExpr(lam)
        if t.type == "fn":
            lam = self.lambda_()
            return lam
        if t.type == "if":
            return self.if_expr()
        if t.type == "match":
            return self.match_expr()
        raise ParseError("expected expression", t)

    def if_expr(self):
        self.expect("if")
        cond = self.expr()
        self.expect(":")
        then = self.expr()
        self.expect("else")
        self.expect(":")
        else_ = self.expr()
        return A.IfExpr(cond, then, else_)

    def match_expr(self):
        self.expect("match")
        e = self.expr()
        # one-line form?
        if self.peek().type == ":":
            self.advance()
            # case ... : expr
            arms = []
            self.expect("case")
            pat = self.pattern(False)
            guard = None
            if self.peek().type == "if":
                self.advance()
                guard = self.expr()
            self.expect(":")
            body = self.expr()
            arms.append(A.Arm(pat, guard, body, False))
            while self.peek().type == "case":
                self.advance()
                pat = self.pattern(False)
                guard = None
                if self.peek().type == "if":
                    self.advance()
                    guard = self.expr()
                self.expect(":")
                body = self.expr()
                arms.append(A.Arm(pat, guard, body, False))
            if self.match("else"):
                self.expect(":")
                ebody = self.expr()
                arms.append(A.Arm(None, None, ebody, True))
            return A.MatchExpr(e, arms, True)
        # block form
        self.expect("NEWLINE")
        self._skip_newlines()
        arms = []
        if self.match("INDENT"):
            while self.peek().type not in ("DEDENT", "EOF"):
                while self.peek().type == "NEWLINE":
                    self.advance()
                if self.peek().type in ("DEDENT", "EOF"):
                    break
                arms.append(self.arm())
            self.match("DEDENT")
        return A.MatchExpr(e, arms, False)

    def lambda_(self):
        self.expect("fn")
        params = []
        if self.peek().type != "=>":
            # params
            if self.peek().type == "(":
                # lambda with parenthesized params? grammar: fn [ params ] => expr
                # params not parenthesized in lambda. But handle (x) => by requiring no parens?
                pass
            # parse params (not in parens per grammar)
            # Actually grammar: lambda = 'fn' [ params ] '=>' expr, params = param { ',' param }
            # params are comma-separated without outer parens
            params = [self.param()]
            while self.match(","):
                if self.peek().type == "=>":
                    break
                params.append(self.param())
        self.expect("=>")
        body = self.expr()
        return A.Lambda(params, body)
