struct S { a: i32, b: i32 }
fn main() {
    let mut s = S { a: 1, b: 2 };
    let (x, y) = (&mut s.a, &mut s.b);
    std::mem::swap(x, y);
    println!("{} {}", s.a, s.b);
}
