"""Conformance test harness for the Minim parser.

Runs the parser over every .mim file and every python code block in the docs.
Exit code 0 if all pass, 1 otherwise.
"""

import glob
import re
import sys

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.parser import parse

DOCS = [
    "docs/OWNERSHIP.md",
    "docs/SOUNDNESS.md",
    "docs/APRENDER-DEMOSTRACIONES.md",
    "formal/CASES.md",
]


def main():
    failures = []
    # .mim files
    for f in sorted(glob.glob("**/*.mim", recursive=True)):
        try:
            parse(open(f).read())
        except Exception as e:
            failures.append((f, str(e)[:120]))
    # doc code blocks
    for doc in DOCS:
        text = open(doc).read()
        blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
        for i, b in enumerate(blocks):
            try:
                parse(b)
            except Exception as e:
                failures.append((f"{doc} block {i}", str(e)[:120]))
    if failures:
        print(f"FAIL: {len(failures)} failures")
        for f, e in failures[:20]:
            print(f"  {f}: {e}")
        sys.exit(1)
    print("OK: all inputs parse successfully")


if __name__ == "__main__":
    main()