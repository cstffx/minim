"""Conformance harness for the Minim borrow checker.

Runs the borrow checker over every .mim file and every python code block in the docs.
Exit code 0 if all run without internal errors, 1 otherwise.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.borrow import borrow_check

DOCS = [
    "docs/OWNERSHIP.md",
    "docs/SOUNDNESS.md",
    "docs/APRENDER-DEMOSTRACIONES.md",
    "formal/CASES.md",
]


def main():
    failures = []
    for f in sorted(glob.glob("**/*.mim", recursive=True)):
        try:
            borrow_check(open(f).read())
        except Exception as e:
            failures.append((f, str(e)[:120]))
    for doc in DOCS:
        text = open(doc).read()
        blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        for i, b in enumerate(blocks):
            try:
                borrow_check(b)
            except Exception as e:
                failures.append((f"{doc} block {i}", str(e)[:120]))
    if failures:
        print(f"FAIL: {len(failures)} failures")
        for f, e in failures[:20]:
            print(f"  {f}: {e}")
        sys.exit(1)
    print("OK: borrow checker ran without internal errors")


if __name__ == "__main__":
    main()