"""Comprehensive tests for bir_borrow borrow checker."""
import unittest
from tools.bir import (Module, Function, Block, Stmt, StmtKind, Place, PlaceKind,
                       Rvalue, RvalueKind, Type, TypeKind, Term, TermKind, Local, Param)
from tools.bir_borrow import check_function


def P(name): return Place(PlaceKind.LOCAL, name=name)
def L(name, ty=None):
    if ty is None: ty = Type(TypeKind.I64)
    return Local(name, ty)
def F(name, locals_, stmts, blocks_extra=None):
    f = Function(name=name, locals=locals_)
    b = Block(id=0, stmts=stmts, terminator=Term(TermKind.RETURN))
    f.blocks.append(b)
    f.entry = 0
    if blocks_extra:
        for blk in blocks_extra:
            f.blocks.append(blk)
    return f


class TestBorrowComprehensive(unittest.TestCase):
    # --- basic loans ---
    def test_no_errors_empty(self):
        f = F("f", [L("x")], [])
        self.assertEqual(check_function(f), [])

    def test_shared_then_shared_ok(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    def test_mut_then_mut_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertTrue(check_function(f))

    def test_shared_then_mut_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertTrue(check_function(f))

    def test_mut_then_shared_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertTrue(check_function(f))

    # --- use after move ---
    def test_move_then_use_err(self):
        S = Type(TypeKind.STRUCT, name="S", fields=[])
        stmts = [Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x"))),
                 Stmt(StmtKind.ASSIGN, place=P("z"), rvalue=Rvalue(RvalueKind.USE, place=P("x")))]
        f = F("f", [Local("x", S), Local("y", S), Local("z", S)], stmts)
        self.assertTrue(check_function(f))

    def test_move_then_reassign_ok(self):
        stmts = [Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x"))),
                 Stmt(StmtKind.ASSIGN, place=P("x"), rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=1))]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertEqual(check_function(f), [])

    # --- assign while borrowed ---
    def test_assign_while_mut_borrowed_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("x"), rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=1))]
        f = F("f", [L("x")], stmts)
        self.assertTrue(check_function(f))

    def test_assign_while_shared_borrowed_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("x"), rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=1))]
        f = F("f", [L("x")], stmts)
        self.assertTrue(check_function(f))

    # --- use while borrowed ---
    def test_use_while_mut_borrowed_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x")))]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertTrue(check_function(f))

    # --- storage dead clears ---
    def test_storage_dead_clears_mut(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.STORAGE_DEAD, place=P("x")),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    def test_storage_dead_clears_shared(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.STORAGE_DEAD, place=P("x")),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="b")]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    def test_storage_dead_clears_move(self):
        S = Type(TypeKind.STRUCT, name="S", fields=[])
        stmts = [Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x"))),
                 Stmt(StmtKind.STORAGE_DEAD, place=P("x")),
                 Stmt(StmtKind.ASSIGN, place=P("z"), rvalue=Rvalue(RvalueKind.USE, place=P("x")))]
        f = F("f", [Local("x", S), Local("y", S), Local("z", S)], stmts)
        self.assertEqual(check_function(f), [])

    # --- drop ---
    def test_drop_use_ok(self):
        stmts = [Stmt(StmtKind.DROP, place=P("x"))]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    def test_drop_moved_err(self):
        S = Type(TypeKind.STRUCT, name="S", fields=[])
        stmts = [Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=Rvalue(RvalueKind.USE, place=P("x"))),
                 Stmt(StmtKind.DROP, place=P("x"))]
        f = F("f", [Local("x", S), Local("y", S)], stmts)
        self.assertTrue(check_function(f))

    # --- call ---
    def test_call_args_checked(self):
        stmts = [Stmt(StmtKind.CALL, func="g", args=[Rvalue(RvalueKind.USE, place=P("x"))], dest=P("y"), target=0)]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertEqual(check_function(f), [])

    def test_call_dest_borrowed_err(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("y"), borrow_target="a"),
                 Stmt(StmtKind.CALL, func="g", args=[], dest=P("y"), target=0)]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertTrue(check_function(f))

    # --- rvalue nested ---
    def test_binop_uses_checked(self):
        rv = Rvalue(RvalueKind.BINOP, op=1, a=Rvalue(RvalueKind.USE, place=P("x")),
                    b=Rvalue(RvalueKind.USE, place=P("y")))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("z"), rvalue=rv)]
        f = F("f", [L("x"), L("y"), L("z")], stmts)
        self.assertTrue(check_function(f))

    def test_aggregate_checked(self):
        rv = Rvalue(RvalueKind.AGGREGATE, agg_kind=0, agg_fields=[Rvalue(RvalueKind.USE, place=P("x"))])
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=rv)]
        # use while mut borrowed -> error
        f = F("f", [L("x"), L("y")], stmts)
        self.assertTrue(check_function(f))

    # --- cast ---
    def test_cast_checked(self):
        rv = Rvalue(RvalueKind.CAST, place=P("x"), cast_type=Type(TypeKind.F64))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=rv)]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertTrue(check_function(f))

    # --- ref rvalue ---
    def test_ref_rvalue_checked(self):
        rv = Rvalue(RvalueKind.REF, ref_kind=0, place=P("x"))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.ASSIGN, place=P("y"), rvalue=rv)]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertTrue(check_function(f))

    # --- multiple locals independent ---
    def test_independent_locals(self):
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a"),
                 Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("y"), borrow_target="b")]
        f = F("f", [L("x"), L("y")], stmts)
        self.assertEqual(check_function(f), [])

    # --- nop ---
    def test_nop_ok(self):
        stmts = [Stmt(StmtKind.NOP)]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    # --- storage live ---
    def test_storage_live_ok(self):
        stmts = [Stmt(StmtKind.STORAGE_LIVE, place=P("x"))]
        f = F("f", [L("x")], stmts)
        self.assertEqual(check_function(f), [])

    # --- switch terminator rvalue ---
    def test_switch_discr_checked(self):
        blk0 = Block(id=0, stmts=[Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P("x"), borrow_target="a")],
                     terminator=Term(TermKind.SWITCHINT, discr=Rvalue(RvalueKind.USE, place=P("x")),
                                     cases=[(1, 1)], otherwise=2))
        blk1 = Block(id=1, stmts=[], terminator=Term(TermKind.RETURN))
        blk2 = Block(id=2, stmts=[], terminator=Term(TermKind.RETURN))
        f = Function(name="f", locals=[L("x")], blocks=[blk0, blk1, blk2], entry=0)
        errs = check_function(f)
        self.assertTrue(errs)

    # --- goto no rvalue ---
    def test_goto_ok(self):
        blk0 = Block(id=0, stmts=[], terminator=Term(TermKind.GOTO, target=1))
        blk1 = Block(id=1, stmts=[], terminator=Term(TermKind.RETURN))
        f = Function(name="f", locals=[L("x")], blocks=[blk0, blk1], entry=0)
        self.assertEqual(check_function(f), [])

    # --- unreachable ---
    def test_unreachable_ok(self):
        blk0 = Block(id=0, stmts=[], terminator=Term(TermKind.UNREACHABLE))
        f = Function(name="f", locals=[L("x")], blocks=[blk0], entry=0)
        self.assertEqual(check_function(f), [])

    # --- field places overlap with whole ---
    def test_field_borrow_blocks_whole_assign(self):
        pa = Place(PlaceKind.FIELD, base=P("s"), field="a")
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=pa, borrow_target="ra"),
                 Stmt(StmtKind.ASSIGN, place=P("s"), rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=1))]
        f = F("f", [L("s")], stmts)
        self.assertTrue(check_function(f))

    # --- deref ---
    def test_deref_borrow_ok(self):
        pd = Place(PlaceKind.DEREF, base=P("p"))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=pd, borrow_target="a")]
        f = F("f", [L("p")], stmts)
        self.assertEqual(check_function(f), [])

    # --- index ---
    def test_index_borrow_ok(self):
        pi = Place(PlaceKind.INDEX, base=P("a"), idx=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=0))
        stmts = [Stmt(StmtKind.BORROW, borrow_kind=0, borrow_place=pi, borrow_target="a")]
        f = F("f", [L("a")], stmts)
        self.assertEqual(check_function(f), [])


if __name__ == "__main__":
    unittest.main()
