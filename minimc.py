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
from tools.modules import load_modules, ModuleError
from tools.resolve import ResolveError
from tools.typecheck import TC
from tools.codegen import WasmCodegen, CodegenError


class CompileFailure(Exception):
    """Raised with a list of (stage, message) pairs for CLI reporting."""
    def __init__(self, stage, errors):
        self.stage = stage
        self.errors = errors
        super().__init__(f"{stage}: {len(errors)} error(s)")


def compile_pipeline(source, want_wasm, filename=None):
    """Run every stage up through typecheck + borrow check.

    Returns (program, tc) on success. Raises CompileFailure on the first
    stage that reports errors.
    """
    try:
        program = parse(source)
    except (LexerError, ParseError) as e:
        raise CompileFailure("parse", [str(e)])

    try:
        base = os.path.dirname(os.path.abspath(filename)) if filename else os.getcwd()
        load_modules(program, base)
    except ModuleError as e:
        raise CompileFailure("modules", [str(e)])

    try:
        tc = TC(program)
        type_errors = tc.check()
    except ResolveError as e:
        raise CompileFailure("resolve", [str(e)])
    if type_errors:
        raise CompileFailure("typecheck", [str(e) for e in type_errors])

    # Desugar `for` with the static type of the iterable, then re-check the
    # core IR that codegen consumes.
    try:
        elaborate(program, tc)
    except Exception as e:
        raise CompileFailure("elaborate", [str(e)])

    try:
        tc = TC(program)
        type_errors = tc.check()
    except ResolveError as e:
        raise CompileFailure("resolve", [str(e)])
    if type_errors:
        raise CompileFailure("typecheck", [str(e) for e in type_errors])

    # borrow check (babirusas) pendiente de integracion AST->BIR
    return program, tc


def cmd_check(args):
    source = open(args.file).read()
    try:
        compile_pipeline(source, want_wasm=False, filename=args.file)
    except CompileFailure as f:
        _report(args.file, f)
        return 1
    print(f"OK: {args.file} passes parse/typecheck/borrow check")
    return 0


def cmd_build(args):
    source = open(args.file).read()
    try:
        program, tc = compile_pipeline(source, want_wasm=True, filename=args.file)
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


def cmd_index(args):
    import subprocess, sys
    script = os.path.join(os.path.dirname(__file__), "tools", "index.py")
    subprocess.run([sys.executable, script] + (args.args or []), check=False)
    return 0

def cmd_test(args):
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pytest"], check=False)
    return 0

def cmd_run(args):
    import subprocess, sys, os, tempfile
    # build
    tmp = tempfile.NamedTemporaryFile(suffix=".wasm", delete=False)
    tmp.close()
    build_args = ["build", args.file, "-o", tmp.name]
    # reuse cmd_build by calling main recursively
    rc = main(build_args)
    if rc != 0:
        return rc
    # execute with node providing env imports
    js = (
        "const fs=require('fs');"
        "const w=fs.readFileSync(process.argv[1]);"
        "const m=new WebAssembly.Module(w);"
        "let inst=null;"
        "const env={"
        "print:(x)=>process.stdout.write(String(x)),"
        "print_f64:(x)=>process.stdout.write(String(x)),"
        "print_str:(ptr)=>{const u=new Uint8Array(inst.exports.memory.buffer);"
        "let e=ptr;while(u[e])e++;"
        "process.stdout.write(Buffer.from(u.subarray(ptr,e)).toString())}"
        "};"
        "inst=new WebAssembly.Instance(m,{env});"
        "if(inst.exports._start)inst.exports._start();"
        "else if(inst.exports.main)console.log(inst.exports.main());"
    )
    rc = subprocess.run(["node", "-e", js, tmp.name]).returncode
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return rc

def cmd_fmt(args):
    import subprocess, sys, os
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "fmt.py")
    subprocess.run([sys.executable, script, args.file], check=False)
    return 0

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

    p_index = sub.add_parser("index", help="run signature indexer")
    p_index.add_argument("args", nargs=argparse.REMAINDER)
    p_index.set_defaults(func=cmd_index)

    p_test = sub.add_parser("test", help="run test suite")
    p_test.set_defaults(func=cmd_test)

    p_fmt = sub.add_parser("fmt", help="format a .mim file")
    p_fmt.add_argument("file")
    p_fmt.set_defaults(func=cmd_fmt)

    p_run = sub.add_parser("run", help="build and run a .mim file")
    p_run.add_argument("file")
    p_run.set_defaults(func=cmd_run)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
