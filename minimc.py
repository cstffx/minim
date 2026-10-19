#!/usr/bin/env python3
"""minimc -- single-entrypoint CLI for the minim compiler.

Usage:
    minimc build <file.mim> [-o out.wasm]
    minimc check <file.mim>

`build` runs the full pipeline (lex -> parse -> resolve/typecheck ->
borrow check -> elaborate -> wasm codegen -> encode) and writes a .wasm
module. `check` runs everything except codegen and reports errors only
(useful for editors/CI, or for .mim files that use constructs codegen
doesn't support yet).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.lexer import LexerError
from tools.parser import parse, ParseError
from tools.core_ir import elaborate
from tools.resolve import ResolveError
from tools.typecheck import TC
from tools.borrow import borrow_check
from tools.codegen_wasm import WasmCodegen, CodegenError


class CompileFailure(Exception):
    """Raised with a list of (stage, message) pairs for CLI reporting."""
    def __init__(self, stage, errors):
        self.stage = stage
        self.errors = errors
        super().__init__(f"{stage}: {len(errors)} error(s)")


def compile_pipeline(source, want_wasm):
    """Run every stage up through typecheck + borrow check.

    Returns (program, tc) on success. Raises CompileFailure on the first
    stage that reports errors.
    """
    try:
        program = parse(source)
    except (LexerError, ParseError) as e:
        raise CompileFailure("parse", [str(e)])

    try:
        elaborate(program)
    except Exception as e:
        raise CompileFailure("elaborate", [str(e)])

    tc = TC(program)
    try:
        type_errors = tc.check()
    except ResolveError as e:
        raise CompileFailure("resolve", [str(e)])
    if type_errors:
        raise CompileFailure("typecheck", [str(e) for e in type_errors])

    borrow_errors = borrow_check(source)
    if borrow_errors:
        raise CompileFailure("borrow", [str(e) for e in borrow_errors])

    return program, tc


def cmd_check(args):
    source = open(args.file).read()
    try:
        compile_pipeline(source, want_wasm=False)
    except CompileFailure as f:
        _report(args.file, f)
        return 1
    print(f"OK: {args.file} passes parse/typecheck/borrow check")
    return 0


def cmd_build(args):
    source = open(args.file).read()
    try:
        program, tc = compile_pipeline(source, want_wasm=True)
        cg = WasmCodegen(program, tc)
        wasm_bytes = cg.generate()
    except CompileFailure as f:
        _report(args.file, f)
        return 1
    except CodegenError as e:
        _report(args.file, CompileFailure("codegen", [str(e)]))
        return 1

    out = args.output or os.path.splitext(args.file)[0] + ".wasm"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(wasm_bytes)
    print(f"wrote {out} ({len(wasm_bytes)} bytes)")
    return 0


def _report(file, failure):
    print(f"FAIL [{failure.stage}] {file}", file=sys.stderr)
    for e in failure.errors:
        print(f"  {e}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="minimc")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="compile a .mim file to WebAssembly")
    p_build.add_argument("file")
    p_build.add_argument("-o", "--output", default=None, help="output .wasm path")
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("check", help="run parse/typecheck/borrow check only")
    p_check.add_argument("file")
    p_check.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
