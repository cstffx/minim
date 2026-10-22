"""Adversarial CFG fuzz for bir_borrow."""
import random
import unittest
from tools.bir import (Function, Block, Stmt, StmtKind, Place, PlaceKind,
                       Rvalue, RvalueKind, Type, TypeKind, Term, TermKind, Local)
from tools.bir_borrow import check_function


def P(n): return Place(PlaceKind.LOCAL, name=f"x{n}")
def L(n): return Local(f"x{n}", Type(TypeKind.I64))


class TestBorrowAdvCFG(unittest.TestCase):
    def _gen(self, seed):
        rng = random.Random(seed)
        nvars = rng.randint(1, 4)
        nblocks = rng.randint(1, 6)
        blocks = []
        for bi in range(nblocks):
            nstmts = rng.randint(0, 6)
            stmts = []
            for _ in range(nstmts):
                choice = rng.randrange(7)
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
                elif choice == 5:
                    stmts.append(Stmt(StmtKind.CALL, func="g", args=[Rvalue(RvalueKind.USE, place=P(v))], dest=P((v+1)%nvars), target=0))
                else:
                    stmts.append(Stmt(StmtKind.NOP))
            # terminator
            term_choice = rng.randrange(4)
            if term_choice == 0 or bi == nblocks-1:
                term = Term(TermKind.RETURN)
            elif term_choice == 1:
                tgt = rng.randrange(nblocks)
                term = Term(TermKind.GOTO, target=tgt)
            else:
                t1 = rng.randrange(nblocks)
                t2 = rng.randrange(nblocks)
                term = Term(TermKind.SWITCHINT, discr=Rvalue(RvalueKind.USE, place=P(rng.randrange(nvars))),
                            cases=[(1, t1)], otherwise=t2)
            blocks.append(Block(bi, stmts, term))
        locals_ = [L(i) for i in range(nvars)]
        f = Function(name="f", locals=locals_, blocks=blocks, entry=0)
        return f

    def test_no_crash(self):
        for seed in range(300):
            f = self._gen(seed)
            try:
                res = check_function(f)
            except Exception as e:
                self.fail(f"seed {seed} raised {e}")
            self.assertIsInstance(res, list)

    def test_determinism(self):
        for seed in range(100):
            f1 = self._gen(seed)
            f2 = self._gen(seed)
            self.assertEqual(check_function(f1), check_function(f2))


if __name__ == "__main__":
    unittest.main()
