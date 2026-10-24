from tools.lexer import tokenize
from tools import nodes as A
from tools.nodes import Span
from tools.parser_types import ParseError



class DeclMixin:
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
