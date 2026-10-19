fn main() {
    let mut v = vec![1, 2, 3, 4];
    let i = 2;
    let (a, b) = (&mut v[..i], &mut v[i..]);
    a[0] = b[0];
    println!("{:?} {:?}", a, b);
}
