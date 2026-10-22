# Minim

Lenguaje de programación de alto nivel diseñado **para que una IA escriba código con
un bajo consumo de tokens**, sin renunciar a tipado estático, verificación de
préstamos (*borrow checker*) ni compilación rápida de un solo paso.

> Estado: **diseño** (v0.1). No hay implementación todavía.

## Hola, mundo

```python
fn main()
	print("Hola, mundo!")
```

## Ejemplo más complejo (conteo de palabras)

**Minim**

```python
use fs, env

fn count(path: str) -> map[str, int]!
	var c = map[str, int]()
	for line in fs.read(path)?
		for w in line.words()
			c[w.lower().strip(".,;:!?")] += 1
	c

fn main()
	let path = env.arg(1) or "in.txt"
	let c = count(path) or
		eprint(f"error: {it}")
		return
	for w, k in c.top(10)
		print(f"{k:6} {w}")
```

**Python**

```python
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
```

**PHP**

```php
<?php
function countWords(string $path): array
{
    $c = [];
    $fh = fopen($path, 'r');
    if ($fh === false) {
        throw new RuntimeException("cannot open $path");
    }
    while (($line = fgets($fh)) !== false) {
        foreach (preg_split('/\s+/', trim($line)) as $w) {
            if ($w === '') {
                continue;
            }
            $key = strtolower(trim($w, ".,;:!?"));
            $c[$key] = ($c[$key] ?? 0) + 1;
        }
    }
    fclose($fh);
    return $c;
}

$path = $argv[1] ?? 'in.txt';
try {
    $c = countWords($path);
} catch (Throwable $e) {
    fwrite(STDERR, "error: {$e->getMessage()}\n");
    return;
}
arsort($c);
$i = 0;
foreach ($c as $w => $k) {
    if ($i++ >= 10) {
        break;
    }
    printf("%6d %s\n", $k, $w);
}
```

**Rust**

```rust
use std::collections::HashMap;
use std::env;
use std::fs;

fn count(path: &str) -> std::io::Result<HashMap<String, i64>> {
    let text = fs::read_to_string(path)?;
    let mut c: HashMap<String, i64> = HashMap::new();
    for line in text.lines() {
        for w in line.split_whitespace() {
            let key = w
                .to_lowercase()
                .trim_matches(|ch: char| ch.is_ascii_punctuation())
                .to_string();
            *c.entry(key).or_insert(0) += 1;
        }
    }
    Ok(c)
}

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| "in.txt".to_string());
    let c = match count(&path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {}", e);
            return;
        }
    };
    let mut v: Vec<_> = c.into_iter().collect();
    v.sort_by(|a, b| b.1.cmp(&a.1));
    for (w, k) in v.iter().take(10) {
        println!("{:6} {}", k, w);
    }
}
```

## Métrica real del ahorro de tokens

Medido con tokenizadores BPE reales (`o200k_base` / `cl100k_base`) sobre 5 programas
(`tools/measure.py`):

| Programa | Minim | Python | Python tipado | PHP | Rust |
|---|---:|---:|---:|---:|---:|
| a_counter | 50 / 50 | 65 / 65 | 65 / 65 | 71 / 71 | 91 / 91 |
| b_shapes | 57 / 57 | 83 / 85 | 83 / 85 | 107 / 105 | 79 / 78 |
| c_total | 51 / 51 | 58 / 57 | 58 / 57 | 83 / 83 | 83 / 83 |
| d_borrow | 53 / 53 | 40 / 40 | 57 / 57 | 76 / 76 | 70 / 70 |
| wordcount | 130 / 132 | 154 / 153 | 206 / 205 | 250 / 246 | 272 / 266 |
| **TOTAL** | **341 / 343** | **400 / 400** | **469 / 469** | **587 / 581** | **595 / 588** |

Valores `o200k_base / cl100k_base`.

| Comparación (total, o200k_base) | Ahorro de tokens de Minim |
|---|---:|
| Minim vs Python | 14.7% |
| Minim vs Python tipado | 27.3% |
| Minim vs PHP | 41.9% |
| Minim vs Rust | 42.7% |
