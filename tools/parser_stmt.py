from tools.lexer import tokenize
from tools import nodes as A
from tools.nodes import Span
from tools.parser_types import ParseError



class StmtMixin:
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
