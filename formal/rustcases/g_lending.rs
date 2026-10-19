struct Numbers { n: u32 }
impl Numbers {
    fn next(&mut self) -> Option<&u32> {
        if self.n == 0 { return None; }
        self.n -= 1;
        Some(&self.n)
    }
}
fn main() {
    let mut it = Numbers { n: 3 };
    let mut last = None;
    while let Some(x) = it.next() { last = Some(x); }
    println!("{:?}", last);
}
