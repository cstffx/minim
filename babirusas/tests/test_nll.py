"""Tests del borrow checker NLL sobre BIR (sin pasar por el AST)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from borrowir.ir import *
from borrowir.borrow import BorrowChecker
from tools.nodes import Span


def _local(name, ty=None, mutable=True):
    return Local(name, ty or Type("list"), mutable)


def _use(name):
    return Rvalue("use", place=Place("local", name))


def _assign(dest, rv):
    return Stmt("Assign", place=Place("local", dest), rvalue=rv)


def _borrow(src, dst, kind="shared"):
    return Stmt("Borrow", place=Place("local", src), borrow_kind=kind,
                borrow_target=dst)


def _call(func, args, dest="t"):
    return Stmt("Call", call_func=func, call_args=args,
                call_dest=Place("local", dest))


def _fn(name, stmts, locals_=(), params=()):
    return Function(name, list(params), list(locals_),
                    [Block(0, list(stmts), Term("Return"))], 0)


def test_nll_termina_en_ultimo_uso():
    f = _fn("main", [
        Stmt("StorageLive", place=Place("local", "x")),
        _borrow("x", "r"),
        _assign("z", _use("r")),          # ultimo uso de r
        _assign("x", Rvalue("const", const_value=1)),  # el prestamo ya expiro
    ], [_local("x"), _local("r"), _local("z")])
    assert BorrowChecker().check(f) == []


def test_nll_sigue_vivo_hasta_el_uso():
    f = _fn("main", [
        Stmt("StorageLive", place=Place("local", "x")),
        _borrow("x", "r"),
        _assign("x", Rvalue("const", const_value=1)),
        _assign("z", _use("r")),
    ], [_local("x"), _local("r"), _local("z")])
    errs = BorrowChecker().check(f)
    assert any("borrow" in e for e in errs), errs


def test_drop_dueno_prestado():
    f = _fn("main", [
        Stmt("StorageLive", place=Place("local", "x")),
        _borrow("x", "r"),
        Stmt("StorageDead", place=Place("local", "x")),
        _assign("z", _use("r")),
    ], [_local("x"), _local("r"), _local("z")])
    errs = BorrowChecker().check(f)
    assert any("borrowed" in e for e in errs), errs


def test_cast_copia_no_mueve():
    f = _fn("main", [
        _assign("y", Rvalue("cast", a=_use("x"), cast_type=Type("i64"))),
        _assign("z", _use("x")),
    ], [_local("x"), _local("y"), _local("z")])
    assert BorrowChecker().check(f) == []


def test_parametro_move_consume():
    callee = _fn("consume", [], params=[Param("v", Type("list"), False, "move")])
    caller = _fn("main", [
        _call("consume", [_use("x")]),
        _assign("z", _use("x")),
    ], [_local("x"), _local("z")])
    errs = BorrowChecker([callee, caller]).check(caller)
    assert any("moved" in e for e in errs), errs


def test_parametro_unique_exige_var():
    callee = _fn("push", [], params=[Param("v", Type("list"), True, "unique")])
    caller = _fn("main", [
        _call("push", [_use("x")]),
    ], [_local("x", mutable=False)])
    errs = BorrowChecker([callee, caller]).check(caller)
    assert any("unique" in e or "var" in e for e in errs), errs


def test_diagnostico_con_span():
    st = _borrow("x", "r")
    st.span = Span(12, 5)
    write = _assign("x", Rvalue("const", const_value=1))
    write.span = Span(12, 5)
    f = _fn("main", [
        Stmt("StorageLive", place=Place("local", "x")),
        st,
        write,
        _assign("z", _use("r")),
    ], [_local("x"), _local("r"), _local("z")])
    errs = BorrowChecker().check(f)
    assert any(e.startswith("12:5:") for e in errs), errs
