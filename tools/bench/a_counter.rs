struct Counter {
    n: i64,
}

impl Counter {
    fn new() -> Self {
        Self { n: 0 }
    }

    fn inc(&mut self, by: i64) -> i64 {
        self.n += by;
        self.n
    }
}

fn main() {
    let mut c = Counter::new();
    c.inc(1);
    c.inc(3);
    println!("{}", c.n);
}
