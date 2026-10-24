from tools.lexer import tokenize
from tools import nodes as A
from tools.nodes import Span


class ParseError(Exception):
    def __init__(self, msg, tok):
        super().__init__(f"{tok.line}:{tok.col}: {msg} (got {tok.type!r} {tok.value!r})")
        self.tok = tok



class TypesMixin:
    def path(self):
        name = self.expect("NAME").value
        parts = [name]
        while self.match("."):
            parts.append(self.expect("NAME").value)
        return parts

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
