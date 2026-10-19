fn main() {
    let mut v = [1, 2, 3, 4];
    let [a, b] = v.get_disjoint_mut([0, 2]).unwrap();
    std::mem::swap(a, b);
    println!("{:?}", v);
}
