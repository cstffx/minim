class Counter:
    def __init__(self, n: int = 0):
        self.n = n

    def inc(self, by: int = 1) -> int:
        self.n += by
        return self.n


c = Counter()
c.inc()
c.inc(3)
print(c.n)
