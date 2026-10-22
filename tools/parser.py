"""Recursive descent parser for Minim (.mim). LL(2) with INDENT/DEDENT tokens."""

try:
    from tools.lexer import tokenize
    from tools import nodes as A
    from tools.nodes import Span
except ImportError:
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools.lexer import tokenize
    from tools import nodes as A
    from tools.nodes import Span


class ParseError(Exception):
    def __init__(self, msg, tok):
        super().__init__(f"{tok.line}:{tok.col}: {msg} (got {tok.type!r} {tok.value!r})")
        self.tok = tok


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.in_block = False
        self.in_block = False

    # ---- token helpers ----
    def peek(self, off=0):
        idx = self.pos + off
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]  # EOF

    def advance(self):
        t = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return t

    def expect(self, ttype):
        t = self.peek()
        if t.type != ttype:
            raise ParseError(f"expected {ttype}", t)
        return self.advance()

    def match(self, ttype):
        if self.peek().type == ttype:
            self.advance()
            return True
        return False

    def at_end(self):
        return self.peek().type == "EOF"

    # ---- top level ----
    def parse(self):
        stmts = []
        start = self.peek()
        while self.peek().type in ("NEWLINE", "INDENT", "DEDENT"):
            self.advance()
        while not self.at_end():
            s = self.stmt()
            stmts.append(s)
            while self.peek().type in ("NEWLINE", "INDENT", "DEDENT"):
                self.advance()
        prog = A.Program(stmts)
        prog.span = Span(start.line, start.col)
        return prog

    def stmt(self):
        start = self.peek()
        t = self.peek()
        if t.type == "use":
            r = self.use_decl()
        elif t.type in ("let", "var") and self.in_block:
            r = self.simple()
        elif t.type in ("let", "var", "type", "trait"):
            r = self.decl()
        elif t.type == "fn":
            i = 1
            # skip optional name
            if self.pos + i < len(self.tokens) and self.tokens[self.pos + i].type == "NAME":
                i += 1
            # skip optional type params [ ... ]
            if self.pos + i < len(self.tokens) and self.tokens[self.pos + i].type == "[":
                depth = 0
                while self.pos + i < len(self.tokens):
                    tt = self.tokens[self.pos + i].type
                    if tt == "[":
                        depth += 1
                    elif tt == "]":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
            if (self.pos + i < len(self.tokens)
                    and self.tokens[self.pos + i].type == "("):
                r = self.decl()
            else:
                r = self.simple()
        else:
            r = self.simple()
        if hasattr(r, "span") and r.span is None:
            r.span = Span(start.line, start.col)
        return r

    # ---- declarations ----
    def decl(self):
        t = self.peek()
        if t.type == "let":
            return self.let_decl()
        if t.type == "var":
            return self.var_decl()
        if t.type == "fn":
            return self.fn_decl()
        if t.type == "type":
            return self.type_decl()
        if t.type == "trait":
            return self.trait_decl()
        raise ParseError("expected declaration", t)

    def use_decl(self):
        self.expect("use")
        paths = [self.path()]
        while self.match(","):
            paths.append(self.path())
        self._optional_newline()
        return A.UseDecl(paths)

    def path(self):
        name = self.expect("NAME").value
        parts = [name]
        while self.match("."):
            parts.append(self.expect("NAME").value)
        return parts

    def let_decl(self):
        self.expect("let")
        name = self.expect("NAME").value
        type_ = None
        if self.match(":"):
            type_ = self.type()
        self.expect("=")
        val = self.expr()
        self._optional_newline()
        return A.LetDecl(name, type_, val)

    def var_decl(self):
        self.expect("var")
        bindings = [self.binding()]
        while self.match(","):
            bindings.append(self.binding())
        self.expect("=")
        val = self.expr()
        self._optional_newline()
        return A.VarDecl(bindings, val)

    def fn_decl(self):
        self.expect("fn")
        name = self.expect("NAME").value
        tparams = []
        if self.match("["):
            tparams = self.tparams()
            self.expect("]")
        self.expect("(")
        params = []
        if self.peek().type != ")":
            params = self.params()
        self.expect(")")
        ret = None
        if self.match("->"):
            ret = self.type()
        self.match(":")
        body = self.suite()
        return A.FnDecl(name, tparams, params, ret, body)

    def params(self):
        ps = [self.param()]
        while self.match(","):
            if self.peek().type == ")":
                break
            ps.append(self.param())
        return ps

    def param(self):
        mode = None
        if self.peek().type in ("var", "move"):
            mode = self.advance().type
        if self.peek().type == "self":
            name = "self"
            self.advance()
        else:
            name = self.expect("NAME").value
        type_ = None
        if self.match(":"):
            type_ = self.type()
        default = None
        if self.match("="):
            default = self.expr()
        return A.Param(mode, name, type_, default)

    def tparams(self):
        ts = [self.tparam()]
        while self.match(","):
            if self.peek().type == "]":
                break
            ts.append(self.tparam())
        return ts

    def tparam(self):
        name = self.expect("NAME").value
        bound = None
        if self.match(":"):
            bound = self.type()
        return A.TParam(name, bound)

    def type_decl(self):
        self.expect("type")
        name = self.expect("NAME").value
        tparams = []
        if self.match("["):
            tparams = self.tparams()
            self.expect("]")
        self.expect("NEWLINE")
        # optional INDENT
        self._skip_newlines()
        members = []
        if self.match("INDENT"):
            while self.peek().type not in ("DEDENT", "EOF"):
                while self.peek().type == "NEWLINE":
                    self.advance()
                if self.peek().type in ("DEDENT", "EOF"):
                    break
                members.append(self.member())
            self.match("DEDENT")
        return A.TypeDecl(name, tparams, members)

    def member(self):
        t = self.peek()
        if t.type == "field" if False else False:
            pass
        if t.type == "case":
            return self.variant_member()
        if t.type == "fn":
            return A.Member("fn", self.fn_decl())
        if t.type == "let":
            return A.Member("let", self.let_decl())
        # field: NAME [ ':' type ] [ '=' expr ] NEWLINE
        name = self.expect("NAME").value
        type_ = None
        if self.match(":"):
            type_ = self.type()
        default = None
        if self.match("="):
            default = self.expr()
        self._optional_newline()
        return A.Member("field", A.Field(name, type_, default))

    def variant_member(self):
        self.expect("case")
        name = self.expect("NAME").value
        fields = []
        if self.match("("):
            if self.peek().type != ")":
                fields = self.field_list()
            self.expect(")")
        members = []
        if self.peek().type == "NEWLINE":
            self.advance()
            if self.match("INDENT"):
                while self.peek().type not in ("DEDENT", "EOF"):
                    while self.peek().type == "NEWLINE":
                        self.advance()
                    if self.peek().type in ("DEDENT", "EOF"):
                        break
                    members.append(self.member())
                self.match("DEDENT")
        return A.Member("variant", A.Variant(name, fields, members))

    def field_list(self):
        fl = [self.field_name()]
        while self.match(","):
            if self.peek().type == ")":
                break
            fl.append(self.field_name())
        return fl

    def field_name(self):
        name = self.expect("NAME").value
        type_ = None
        if self.match(":"):
            type_ = self.type()
        return A.FieldName(name, type_)

    def trait_decl(self):
        self.expect("trait")
        name = self.expect("NAME").value
        self.expect("NEWLINE")
        self._skip_newlines()
        methods = []
        if self.match("INDENT"):
            while self.peek().type not in ("DEDENT", "EOF"):
                while self.peek().type == "NEWLINE":
                    self.advance()
                if self.peek().type in ("DEDENT", "EOF"):
                    break
                methods.append(self.fn_sig())
            self.match("DEDENT")
        return A.TraitDecl(name, methods)

    def fn_sig(self):
        self.expect("fn")
        name = self.expect("NAME").value
        self.expect("(")
        params = []
        if self.peek().type != ")":
            params = self.params()
        self.expect(")")
        ret = None
        if self.match("->"):
            ret = self.type()
        self._optional_newline()
        return A.FnSig(name, params, ret)

    # ---- simple statements ----
    def place(self):
        name = self.expect("NAME").value
        parts = []
        while self.peek().type == "." or self.peek().type == "[":
            if self.peek().type == ".":
                self.advance()
                fname = self.expect("NAME").value
                parts.append(("field", fname))
            else:
                self.advance()
                idx = self.expr()
                self.expect("]")
                parts.append(("index", idx))
        return A.Place(name, parts)

    def simple(self):
        t = self.peek()
        if t.type == "let":
            return self.let_stmt()
        if t.type == "var":
            return self.var_stmt()
        if t.type == "if":
            saved = self.pos
            self.advance()  # if
            self.expr()  # cond
            # if_stmt if followed by ':' + suite, or directly by suite (no colon)
            if self.peek().type == ":":
                self.match(":")
                if self.peek().type in ("NEWLINE", "INDENT", "DEDENT", "EOF"):
                    self.pos = saved
                    return self.if_stmt()
                # colon followed by expr -> one-line if_expr, fall through
            elif self.peek().type in ("NEWLINE", "INDENT", "DEDENT", "EOF"):
                self.pos = saved
                return self.if_stmt()
            self.pos = saved
            e = self.expr()
            self._optional_newline()
            return A.ExprStmt(e)
        if t.type == "while":
            return self.while_stmt()
        if t.type == "for":
            return self.for_stmt()
        if t.type == "match":
            saved = self.pos
            self.advance()  # match
            self.expr()  # expr
            if self.peek().type == ":":
                self.match(":")
                if self.peek().type in ("case",):
                    # one-line match expression used as statement
                    self.pos = saved
                    e = self.expr()
                    self._optional_newline()
                    return A.ExprStmt(e)
            self.pos = saved
            return self.match_stmt()
        if t.type == "break":
            self.advance()
            self._optional_newline()
            return A.BreakStmt()
        if t.type == "continue":
            self.advance()
            self._optional_newline()
            return A.ContinueStmt()
        if t.type == "return":
            return self.return_stmt()
        if t.type == "spawn":
            return self.spawn_stmt()
        if t.type == "await":
            return self.await_stmt()
        # assign or exprStmt
        # Try assign: place followed by assign op
        # We need to check if it's an assign: parse place, then check for assign op
        # But expr also can start with NAME. Use lookahead.
        # Simple approach: try to parse as assign if next after place is assign op.
        saved = self.pos
        try:
            place = self.place()
            if self.peek().type in ("=", "+=", "-=", "*=", "/=", "//=", "%=", "**="):
                op = self.advance().type
                val = self.expr()
                self._optional_newline()
                return A.Assign(place, op, val)
        except ParseError:
            pass
        self.pos = saved
        e = self.expr()
        self._optional_newline()
        return A.ExprStmt(e)

    def let_stmt(self):
        self.expect("let")
        bindings = [self.binding()]
        while self.match(","):
            bindings.append(self.binding())
        self.expect("=")
        val = self.expr()
        self._optional_newline()
        return A.LetStmt(bindings, val)

    def var_stmt(self):
        self.expect("var")
        bindings = [self.binding()]
        while self.match(","):
            bindings.append(self.binding())
        self.expect("=")
        val = self.expr()
        self._optional_newline()
        return A.VarStmt(bindings, val)

    def if_stmt(self):
        self.expect("if")
        cond = self.expr()
        self.match(":")
        then = self.suite()
        elifs = []
        while self.peek().type == "elif":
            self.advance()
            ec = self.expr()
            self.match(":")
            es = self.suite()
            elifs.append((ec, es))
        else_ = None
        if self.match("else"):
            self.match(":")
            else_ = self.suite()
        return A.IfStmt(cond, then, elifs, else_)

    def while_stmt(self):
        self.expect("while")
        cond = self.expr()
        self.match(":")
        body = self.suite()
        return A.WhileStmt(cond, body)

    def for_stmt(self):
        self.expect("for")
        bindings = [self.binding()]
        while self.match(","):
            bindings.append(self.binding())
        self.expect("in")
        it = self.expr()
        self.match(":")
        body = self.suite()
        return A.ForStmt(bindings, it, body)

    def match_stmt(self):
        self.expect("match")
        e = self.expr()
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
        return A.MatchStmt(e, arms)

    def arm(self):
        if self.peek().type == "else":
            self.advance()
            self.expect(":")
            body = self.arm_body()
            return A.Arm(None, None, body, True)
        self.expect("case")
        pat = self.pattern(False)
        guard = None
        if self.peek().type == "if":
            self.advance()
            guard = self.expr()
        self.expect(":")
        body = self.arm_body()
        return A.Arm(pat, guard, body, False)

    def arm_body(self):
        if self.peek().type == "NEWLINE" or self.peek().type in ("INDENT", "DEDENT", "EOF"):
            # suite? check for INDENT
            if self.peek().type == "INDENT":
                # shouldn't happen here normally
                pass
            # empty or suite
            if self.peek().type == "INDENT":
                return self.suite()
            # try suite via NEWLINE INDENT
            # armBody = expr [NEWLINE] | suite
            # If next is suite form, handle
            return self.suite() if self.peek().type == "NEWLINE" and self.peek(1).type == "INDENT" else None
        # expr
        e = self.expr()
        self._optional_newline()
        return e

    def return_stmt(self):
        self.expect("return")
        val = None
        if self.peek().type not in ("NEWLINE", "DEDENT", "EOF", "INDENT"):
            val = self.expr()
        self._optional_newline()
        return A.ReturnStmt(val)

    def spawn_stmt(self):
        self.expect("spawn")
        e = self.expr()
        self._optional_newline()
        return A.SpawnStmt(e)

    def await_stmt(self):
        self.expect("await")
        e = self.expr()
        self._optional_newline()
        return A.AwaitStmt(e)

    # ---- suite ----
    def suite(self):
        # suite = NEWLINE INDENT { stmt } DEDENT | NEWLINE INDENT DEDENT
        prev_in_block = self.in_block
        if self.peek().type == "NEWLINE":
            self.advance()
        if self.match("INDENT"):
            self.in_block = True
            stmts = []
            while self.peek().type not in ("DEDENT", "EOF"):
                while self.peek().type == "NEWLINE":
                    self.advance()
                if self.peek().type in ("DEDENT", "EOF"):
                    break
                stmts.append(self.stmt())
            self.match("DEDENT")
            self.in_block = prev_in_block
            return A.Suite(stmts)
        # empty suite without indent (shouldn't happen)
        self.in_block = prev_in_block
        return A.Suite([])

    def _skip_newlines(self):
        while self.peek().type in ("NEWLINE",):
            self.advance()

    def _optional_newline(self):
        if self.peek().type == "NEWLINE":
            self.advance()

    # ---- binding ----
    def binding(self):
        if self.peek().type == "(":
            self.advance()
            pats = [self.pattern()]
            while self.match(","):
                pats.append(self.pattern())
            self.expect(")")
            return A.Binding("tuple", tuple_patterns=pats)
        if self.peek().type == "NAME" and self.peek(1).type == "(":
            name = self.advance().value
            self.expect("(")
            pats = []
            if self.peek().type != ")":
                pats = [self.pattern()]
                while self.match(","):
                    if self.peek().type == ")":
                        break
                    pats.append(self.pattern())
            self.expect(")")
            return A.Binding("variant", variant=name, patterns=pats)
        # NAME [ ':' type ]
        name = self.expect("NAME").value
        type_ = None
        if self.match(":"):
            type_ = self.type()
        return A.Binding("name", name=name, type_=type_)

    # ---- pattern ----
    def pattern(self, named_field=True):
        t = self.peek()
        if t.type == "INT" or t.type == "FLOAT" or t.type == "STR" or t.type == "true" or t.type == "false" or t.type == "nil":
            self.advance()
            return A.Pattern("literal", value=t.value)
        if t.type == "(":
            self.advance()
            pats = [self.pattern(named_field)]
            while self.match(","):
                pats.append(self.pattern(named_field))
            self.expect(")")
            return A.Pattern("tuple", patterns=pats)
        if t.type == "NAME" or t.type == "self" or t.type == "it":
            name = self.advance().value
            if self.peek().type == "(":
                self.advance()
                pats = []
                if self.peek().type != ")":
                    pats = [self.pattern(True)]
                    while self.match(","):
                        if self.peek().type == ")":
                            break
                        pats.append(self.pattern(True))
                self.expect(")")
                return A.Pattern("variant", name=name, patterns=pats)
            if named_field and self.peek().type == ":":
                self.advance()
                sub = self.pattern(named_field)
                return A.Pattern("named_field", field_name=name, sub=sub)
            return A.Pattern("name", value=name)
        raise ParseError("expected pattern", t)

    # ---- expressions ----
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

    # ---- types ----
    def type(self):
        base = self.type_atom()
        if self.peek().type in ("!", "?"):
            suf = self.advance().type
            return A.TypeSuffix(base, suf)
        return base

    def type_atom(self):
        t = self.peek()
        if t.type == "NAME" and t.value == "map":
            self.advance()
            self.expect("[")
            k = self.type()
            self.expect(",")
            v = self.type()
            self.expect("]")
            return A.TypeMap(k, v)
        if t.type == "NAME" and t.value == "set":
            self.advance()
            self.expect("[")
            inner = self.type()
            self.expect("]")
            return A.TypeSet(inner)
        if t.type == "NAME":
            name = self.advance().value
            args = []
            if self.peek().type == "[":
                self.advance()
                args = [self.type()]
                while self.match(","):
                    args.append(self.type())
                self.expect("]")
            return A.TypeName(name, args)
        if t.type == "[":
            self.advance()
            inner = self.type()
            self.expect("]")
            return A.TypeList(inner)
        if t.type == "&":
            self.advance()
            inner = self.type()
            return A.TypeBorrow(inner)
        if t.type == "(":
            self.advance()
            if self.peek().type == ")":
                self.advance()
                if self.peek().type == "->":
                    self.advance()
                    ret = self.type()
                    return A.TypeFunc([], ret)
                return A.TypeParen(None)  # unit? shouldn't happen
            first = self.type()
            if self.match(","):
                items = [first]
                while self.peek().type != ")":
                    items.append(self.type())
                    if not self.match(","):
                        break
                self.expect(")")
                if self.peek().type == "->":
                    self.advance()
                    ret = self.type()
                    return A.TypeFunc(items, ret)
                return A.TypeTuple(items)
            self.expect(")")
            if self.peek().type == "->":
                self.advance()
                ret = self.type()
                return A.TypeFunc([first], ret)
            return A.TypeParen(first)
        raise ParseError("expected type", t)


def parse(source):
    toks = tokenize(source)
    p = Parser(toks)
    return p.parse()


if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = open(sys.argv[1]).read()
    try:
        ast = parse(src)
        print(f"OK: {len(ast.stmts)} top-level statements")
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)