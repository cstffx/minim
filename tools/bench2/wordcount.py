import sys
from collections import Counter


def count(path: str) -> Counter[str]:
    c: Counter[str] = Counter()
    with open(path) as f:
        for line in f:
            for w in line.split():
                c[w.lower().strip(".,;:!?")] += 1
    return c


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "in.txt"
    try:
        c = count(path)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return
    for w, k in c.most_common(10):
        print(f"{k:6} {w}")


main()
