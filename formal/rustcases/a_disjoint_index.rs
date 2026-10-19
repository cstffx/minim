fn main() {
    let mut v = vec![1, 2, 3];
    std::mem::swap(&mut v[0], &mut v[1]);
    println!("{:?}", v);
}
