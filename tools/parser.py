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



from tools.parser_types import ParseError, TypesMixin
from tools.parser_decl import DeclMixin
from tools.parser_stmt import StmtMixin
from tools.parser_expr import ExprMixin


class Parser(DeclMixin, StmtMixin, ExprMixin, TypesMixin):
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.in_block = False
        self.in_block = False

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
