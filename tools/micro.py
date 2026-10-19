#!/usr/bin/env python3
"""micro.py - coste en tokens de cada decision de sintaxis de Minim.

Cada fila aisla UNA decision. Las columnas v1, v2... son las variantes equivalentes
(minim, rust, python, etc., segun la fila). Formato de celda: o200k/cl100k.

Uso:  pip install tiktoken && python3 tools/micro.py
"""
import tiktoken

ENCS = [tiktoken.get_encoding(n) for n in ("o200k_base", "cl100k_base")]


def tok(s):
    return "/".join(str(len(e.encode(s))) for e in ENCS)


ROWS = [
    ("binding mutable", ["let mut x = 0", "var x = 0", "x = 0"]),
    ("parametro", ["fn f(var v: [int])", "fn f(v: &mut Vec<i64>)", "fn f(v: &[i64])", "fn f(v: vector<int>)"]),
    ("receptor de metodo", ["fn inc(var self, by: int = 1) -> int", "fn inc(self, by: int = 1) -> int", "fn inc(&mut self, by: i64) -> i64", "def inc(self, by: int = 1) -> int:"]),
    ("cuerpo de metodo", ["    n += by\n    n", "    self.n += by\n    return self.n"]),
    ("linea indentada d=1", ["\n    x = 1", "\n  x = 1", "\n\tx = 1"]),
    ("linea indentada d=3", ["\n            x = 1"]),
    ("bloque if (5 lineas)", ["if x:\n    a = 1\n    b = 2\n    c = 3\nd = 4", "if (x) {\n    a = 1;\n    b = 2;\n    c = 3;\n}\nd = 4"]),
    ("elif vs else-if", ["if a:\n    x = 1\nelif b:\n    x = 2", "if a:\n    x = 1\nelse:\n    if b:\n        x = 2", "if a {\n    x = 1;\n} else if b {\n    x = 2;\n}"]),
    ("ignorar error", ["let n = s.parse[int]() or continue", "match s.trim().parse::<i64>() {\n    Ok(n) => n,\n    Err(_) => continue,\n}"]),
    ("propagar error", ["let n = s.parse[int]()?", "let n = match s.parse::<i64>() {\n    Ok(n) => n,\n    Err(e) => return Err(e),\n};"]),
    ("opcional", ["fn f(x: int?) -> str?", "fn f(x: Optional[int]) -> Optional[str]", "fn f(x: int | None) -> str | None"]),
    ("generico acotado", ["fn max[T: Ord](a: T, b: T) -> T", "fn max<T: Ord>(a: T, b: T) -> T", "def max[T: Ord](a: T, b: T) -> T:"]),
    ("interpolacion", ['print(f"{a}-{b}")', 'print("{} - {}".format(a, b))', 'printf("%d-%d", a, b)']),
    ("doc de 2 lineas", ["# suma x e y\n# devuelve int\nfn add(x: int, y: int) -> int", "/// suma x e y\n/// devuelve int\nfn add(x: int, y: int) -> int", '"""suma x e y\n\ndevuelve int\n"""\ndef add(x: int, y: int) -> int:']),
    ("logicos", ["if a and not b or c", "if a && !b || c"]),
    ("nombre multipalabra x5", ["user_name user_name user_name user_name user_name", "userName userName userName userName userName"]),
    ("nombre largo x5", ["total_price_amount " * 5, "totalPriceAmount " * 5]),
    ("nombre corto x3", ["user user user"]),
    ("propiedad", ["x.len", "len(x)", "x.len()"]),
    ("lambda", ["fn x => x + 1", "lambda x: x + 1", "|x| x + 1"]),
    ("print", ["print(x)", 'println!("{}", x)', "WriteLn(x)"]),
    ("tipo lista", ["[int]", "list[int]", "Vec<i64>", "array of Int64"]),
    ("firma con retorno", ["fn f() -> int", "fn f(): int", "fn f() -> i64", "def f() -> int:"]),
    ("tipo 2 campos", ["type P\n  x: float\n  y: float", "struct P {\n    x: f64,\n    y: f64,\n}"]),
]


def main():
    w = max(len(r[0]) for r in ROWS) + 2
    print("fila / variante".ljust(w) + "".join(f"{'v' + str(i + 1):>9}" for i in range(4)))
    print("-" * (w + 36))
    for label, samples in ROWS:
        print(label.ljust(w) + "".join(f"{tok(s):>9}" for s in samples))


if __name__ == "__main__":
    main()
