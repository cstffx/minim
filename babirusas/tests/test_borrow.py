import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from borrowir.ir import *
from borrowir.borrow import BorrowChecker

def test_conflicting_borrow():
    f = Function("t", [], [], [
      Block(0, [Stmt("StorageLive", Place("local","x")),
                Stmt("Borrow", place=Place("local","x"), borrow_kind="mut", borrow_target="y"),
                Stmt("Borrow", place=Place("local","x"), borrow_kind="shared", borrow_target="z")],
            Term("Return"))
    ], 0)
    assert BorrowChecker().check(f)

def test_move_then_use():
    f = Function("t", [], [], [
      Block(0, [Stmt("StorageLive", Place("local","x")),
                Stmt("Assign", place=Place("local","y"), rvalue=Rvalue("use", place=Place("local","x"))),
                Stmt("Assign", place=Place("local","z"), rvalue=Rvalue("use", place=Place("local","x")))],
            Term("Return"))
    ], 0)
    errs = BorrowChecker().check(f)
    assert any("moved" in e for e in errs), errs

def test_ok_shared():
    f = Function("t", [], [], [
      Block(0, [Stmt("StorageLive", Place("local","x")),
                Stmt("Borrow", place=Place("local","x"), borrow_kind="shared", borrow_target="a"),
                Stmt("Borrow", place=Place("local","x"), borrow_kind="shared", borrow_target="b")],
            Term("Return"))
    ], 0)
    assert BorrowChecker().check(f) == []
