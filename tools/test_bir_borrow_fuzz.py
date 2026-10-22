"""Military-grade fuzz/invariant tests for bir_borrow."""
import random
import unittest
from tools.bir import (Function, Block, Stmt, StmtKind, Place, PlaceKind,
                       Rvalue, RvalueKind, Type, TypeKind, Term, TermKind, Local)
from tools.bir_borrow import check_function


def P(n): return Place(PlaceKind.LOCAL, name=f"x{n}")
def L(n): return Local(f"x{n}", Type(TypeKind.I64))


class TestBorrowFuzz(unittest.TestCase):
    def _gen(self, seed):
        rng = random.Random(seed)
        nvars = rng.randint(1, 5)
        nstmts = rng.randint(0, 12)
        stmts = []
        for _ in range(nstmts):
            choice = rng.randrange(6)
            v = rng.randrange(nvars)
            if choice == 0:
                stmts.append(Stmt(StmtKind.BORROW, borrow_kind=rng.randrange(2),
                                  borrow_place=P(v), borrow_target=f"r{len(stmts)}"))
            elif choice == 1:
                stmts.append(Stmt(StmtKind.STORAGE_DEAD, place=P(v)))
            elif choice == 2:
                src = rng.randrange(nvars)
                stmts.append(Stmt(StmtKind.ASSIGN, place=P(v),
                                  rvalue=Rvalue(RvalueKind.USE, place=P(src))))
            elif choice == 3:
                stmts.append(Stmt(StmtKind.ASSIGN, place=P(v),
                                  rvalue=Rvalue(RvalueKind.CONST, const_type=Type(TypeKind.I64), const_value=rng.randint(0, 9))))
            elif choice == 4:
                stmts.append(Stmt(StmtKind.DROP, place=P(v)))
            else:
                stmts.append(Stmt(StmtKind.NOP))
        locals_ = [L(i) for i in range(nvars)]
        f = Function(name="f", locals=locals_,
                     blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        return f

    def test_fuzz_no_crash(self):
        for seed in range(200):
            f = self._gen(seed)
            try:
                res = check_function(f)
            except Exception as e:
                self.fail(f"seed {seed} raised {e}")
            self.assertIsInstance(res, list)

    def test_fuzz_errors_are_strings(self):
        for seed in range(200):
            f = self._gen(seed)
            res = check_function(f)
            for e in res:
                self.assertIsInstance(e, str)
                self.assertTrue(len(e) > 0)

    def test_determinism(self):
        for seed in range(50):
            f1 = self._gen(seed)
            f2 = self._gen(seed)
            self.assertEqual(check_function(f1), check_function(f2))

    def test_empty_function_ok(self):
        f = Function(name="f", locals=[], blocks=[Block(0, [], Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_all_nop_ok(self):
        stmts = [Stmt(StmtKind.NOP) for _ in range(50)]
        f = Function(name="f", locals=[L(0)], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])

    def test_storage_dead_all_then_borrow_ok(self):
        stmts = []
        for i in range(5):
            stmts.append(Stmt(StmtKind.BORROW, borrow_kind=1, borrow_place=P(0), borrow_target=f"r{i}"))
            stmts.append(Stmt(StmtKind.STORAGE_DEAD, place=P(0)))
        f = Function(name="f", locals=[L(0)], blocks=[Block(0, stmts, Term(TermKind.RETURN))], entry=0)
        self.assertEqual(check_function(f), [])


if __name__ == "__main__":
    unittest.main()
