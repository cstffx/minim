"""Extra hardening tests for bir_borrow."""
import unittest
from tools.bir import (Function, Block, Stmt, StmtKind, Place, PlaceKind,
                       Rvalue, RvalueKind, Type, TypeKind, Term, TermKind, Local)
from tools.bir_borrow import check_function


def P(name): return Place(PlaceKind.LOCAL, name=name)
def L(name): return Local(name, Type(TypeKind.I64))


class TestBorrowHardening(unittest.TestCase):
    def test_reborrow_after_drop_ok(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.STORAGE_DEAD, place=P("x")),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="b"),
                 Stmt(StmtKind.STORAGE_DEAD, place=P("x"))]
        f = Function(name="f", locals=[L("x")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_two_independent_mut_different_vars_ok(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("y"), borrow_target="b")]
        f = Function(name="f", locals=[L("x"), L("y")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_move_in_call_arg_invalidates(self):
        S = Type(TypeKind.STRUCT, name="S", fields=[])
        stmts = [Stmt(StmtKind.CALL, func="g", args=[Rvalue(RvalueKind.USE, place=P("x"))], dest=None, target=0),
                 Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x")))]
        f = Function(name="f", locals=[Local("x", S), Local("y", S)], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertTrue(check_function(f))

    def test_const_assign_ok(self):
        stmts = [Stmt(StmtKind.ASSIGN, place=P("x"), rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=7))]
        f = Function(name="f", locals=[L("x")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_multiple_shared_then_mut_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="b"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="c")]
        f = Function(name="f", locals=[L("x")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertTrue(check_function(f))

    def test_nested_field_borrow_ok(self):
        p = Place(PlaceKind.FIELD, base=Place(PlaceKind.FIELD, base=P("s"), field="inner"), field="v")
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=p, borrow_target="a")]
        f = Function(name="f", locals=[L("s")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_index_borrow_then_whole_mut_err(self):
        pi = Place(PlaceKind.INDEX, base=P("a"), idx=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=0))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=pi, borrow_target="r"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("a"), borrow_target="m")]
        f = Function(name="f", locals=[L("a")], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertTrue(check_function(f))


if __name__ == "__main__":
    unittest.main()
