# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## IDENTITY
- Minim: token-minimal statically-typed language, `.mim` files, compiles to WASM.
- Design axis: minimize BPE-token cost per construct while keeping memory safety w/o GC (ownership+borrow, Rust-like, lifetime-free).
- Spec-first repo: `docs/*.md` are normative; `tools/*.py` is the reference implementation (Python), not production compiler.
- No `pub`, no `mut`, no lifetimes, no overloading, no `self.` required, no `;`/`{}`. Tabs only for indent (spaces+tabs mixed = lex error).

## PIPELINE (stage -> implementation -> governing spec)
1. Lex          -> `tools/lexer.py`      -> `docs/TOKENS.md`, `docs/DESIGN.md` §1-2 (INDENT/DEDENT like Python, tab-only)
2. Parse        -> `tools/parser.py`     -> `docs/grammar.ebnf`, `docs/DESIGN.md` §3-6 (recursive descent, LL(2))
3. Resolve      -> `tools/resolve.py`    -> `docs/INDEXACION.md` (names/scopes, module symbol table; phase 2a)
4. Core IR      -> `tools/core_ir.py`    -> `docs/CORE-IR.md` (desugars `for`->`while`, surface->reduced AST)
5. Typecheck    -> `tools/typecheck.py`  -> `docs/DESIGN.md` §7 (types; phase 2b; no overload, structural typing)
6. Borrow check -> `tools/borrow.py`     -> `docs/OWNERSHIP.md`, `docs/SOUNDNESS.md` (phase 2c; intra-procedural only)
7. Codegen WASM -> `tools/codegen_wasm.py` -> `docs/COMPILACION.md` §2 (int/float-only MVP subset)
8. Encode       -> `tools/wasm_encoder.py` -> raw wasm binary sections (types/funcs/exports/code)
- Also: `tools/index.py` implements fase-1 signature scan (`.mimidx`) per `docs/INDEXACION.md` / `docs/INDICE-LLM.md`.
- `tools/measure.py`, `tools/micro.py`: token-cost measurement vs Python/Rust (needs `tiktoken`, not installed by default).

## COMPILATION MODEL (docs/COMPILACION.md)
- 2-pass compile: (1) signature scan O(declarations), column-0 keywords only, no body parse; (2) one top-down pass per body -> IR, emitting borrow check + drops inline.
- No forward declarations needed — signatures are all known before any body compiles.
- Return type inferred from body (safe because phase 1 signatures resolve forward calls).
- Monomorphization is memoized per compilation unit; traits dispatch statically (no vtable/`dyn` in v0.1).
- Incremental "firewall": interface hash = hash of signatures only; changing a body never invalidates importers.
- Backends: stack bytecode interpreter (v0.1, `.mimo`) -> Cranelift native (v0.2) -> LLVM (v0.3). This repo only implements WASM codegen, not `.mimo`.
- Determinism required: same source + compiler version -> byte-identical artifact.

## OWNERSHIP / BORROW INVARIANTS (condensed from docs/OWNERSHIP.md + docs/SOUNDNESS.md)
- One owner per value; drop is deterministic, reverse declaration order, no GC.
- 3 param/receiver modes, mode is part of signature (never inferred from body): bare = shared borrow, `var` = unique borrow, `move` = ownership transfer.
- R1-R7 borrow rules (borrow.py enforces): unique excludes all else; shared unlimited; borrow can't outlive owner; use-after-move is error; can't return borrow of a local; borrow ends at last use (NLL-style).
- Copy types: all-copyable-field products (int/float/bool/str/bytes/nil); everything else moves. No partial moves allowed in v0.1 (whole-value move only).
- Closures do not escape in v0.1 (can't be returned/stored) — this is what keeps capture-by-borrow sound.
- `spawn` transfers (implicit move) all args; no live borrow may cross `await` (I5, replaces Send/Sync).
- Borrow checker is NOT proven sound (no formal semantics/soundness proof yet) — see `docs/SOUNDNESS.md` for known holes (A1-A9) and `docs/FORMAL.md` for the proof plan. Treat ownership rules as "best-effort spec," not verified.
- §10 of SOUNDNESS.md: exclusivity is by PATH (`overlap()` on field paths), not by whole-owner — `swap(p.a, p.b)` is sound and accepted; `swap(p.a, p.a)` rejected. Confirm `borrow.py` matches this if touching it.
- A9 (drop ordering on early-exit paths `?`/`or:`/`return`/`break`) is explicitly UNSPECIFIED — be careful extending borrow.py around early returns.

## RUNNING TESTS
- No pytest — these are standalone scripts with their own runner/`__main__` + `sys.exit(1)` on failure. Run directly:
  - `python3 tools/test_parser.py` — parses every `.mim` in `examples/` + every python code-block embedded in `docs/OWNERSHIP.md`, `docs/SOUNDNESS.md`, `docs/APRENDER-DEMOSTRACIONES.md`, `formal/CASES.md`.
  - `python3 tools/test_borrow.py`
  - `python3 tools/test_codegen.py`
  - `python3 tools/test_encoder.py`
  - `python3 tools/test_struct.py`
- Run all: `for f in tools/test_*.py; do python3 "$f" || break; done`
- `docs/*.md` embedded code blocks are part of the conformance surface — editing examples in docs can break `test_parser.py`.

## BENCHMARKS
- `tools/bench/` and `tools/bench2/`: same program in `.mim`/`.py`/`.rs` (+ typed python variant) for perf/token comparison (a_counter, b_shapes, c_total, d_borrow, wordcount).
- `tools/measure.py` / `tools/micro.py`: BPE token-cost comparisons; require `pip install tiktoken` (not present in this env by default).
- `formal/rustcases/run.sh`: feeds `formal/rustcases/*.rs` (all safe programs) through installed `rustc` to catalogue what Rust accepts/rejects, as a baseline for Minim's borrow checker ambitions (`RUSTC=... sh formal/rustcases/run.sh`).

## REPO LAYOUT
- `docs/` — normative spec: DESIGN.md (language), OWNERSHIP.md + SOUNDNESS.md (borrow checker + its proof status), CORE-IR.md, COMPILACION.md (compile/incremental model), INDEXACION.md + INDICE-LLM.md (symbol index for LLM queries), TOKENS.md (token-cost rationale), grammar.ebnf, FORMAL.md (proof plan), APRENDER-DEMOSTRACIONES.md, INDICE-LLM.md.
- `tools/` — Python reference implementation of the pipeline + tests (`test_*.py`) + measurement scripts.
- `formal/` — CASES.md (witness programs: must-accept/must-reject) + `rustcases/*.rs` (rustc baseline comparison).
- `examples/` — sample `.mim` programs (`hello.mim`, `shapes.mim`, `borrow.mim`, `http.mim`, `wordcount.mim`) used as parser conformance corpus.
- `tools/bench/`, `tools/bench2/` — cross-language (mim/py/rs) benchmark sources.

## CRITICAL CONVENTIONS / GOTCHAS
- **One way to do things (OWTDI)** is a hard design principle — do not add alternate syntax for something that already has a canonical form.
- Mode on params/receivers (`var`/`move`/bare) is part of the signature and must NEVER be inferred from the body — this is load-bearing for the incremental firewall and index correctness (A1 in SOUNDNESS.md was exactly this bug).
- Tabs only for indentation in real `.mim` source; mixed space/tab is a lex error. (Docs prose examples use 4 spaces for readability only — don't copy that into `examples/*.mim`.)
- No function/operator overloading: one name = one symbol per module. Don't introduce overloaded builtins.
- No `self.` required inside methods — bare names resolve local-first then field; don't require/add `self.` prefixes in generated code or examples.
- Borrows are never stored in struct fields (v0.1 constraint) — this is what eliminates lifetime syntax; don't design APIs that stash `&T` in a `type`.
- The canonical formatter (`minim fmt`, not yet in `tools/`) defines one true byte representation; if implementing it, it must be idempotent and match `docs/DESIGN.md` §11 exactly (interface hash and caching depend on determinism).
- `docs/*.md` code blocks are executable test fixtures (via `test_parser.py`) — keep them syntactically valid Minim when editing docs.
