```python
import sys
from collections import Counter
from collections.abc import Iterable


def count(path: str) -> Counter[str]:
    c: Counter[str] = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            for w in line.split():
                key: str = w.lower().strip(".,;:!?")
                c[key] += 1
    return c


def top(c: Counter[str], k: int) -> Iterable[tuple[str, int]]:
    return c.most_common(k)


def main() -> None:
    path: str = sys.argv[1] if len(sys.argv) > 1 else "in.txt"
    try:
        c: Counter[str] = count(path)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return
    for w, k in top(c, 10):
        print(f"{k:6} {w}")


main()
```
