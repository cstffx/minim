struct Holder {
    data: String,
    ptr: &'static str,
}
fn main() {
    let mut h = Holder { data: String::from("hola"), ptr: "" };
    h.ptr = &h.data;
    println!("{}", h.ptr);
}
