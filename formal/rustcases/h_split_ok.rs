fn main() {
    let mut v = vec![1, 2, 3];
    let (a, b) = v.split_at_mut(1);
    std::mem::swap(&mut a[0], &mut b[0]);
    println!("{:?}", v);
}
