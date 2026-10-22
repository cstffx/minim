```python
def total(lines: list[str]) -> int:
    t = 0
    for s in lines:
        try:
            n = int(s)
        except ValueError:
            continue
        if n % 2 == 0:
            t += n
    return t
```
