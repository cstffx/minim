fn push_all(dst: &mut Vec<i64>, src: &[i64]) {
    for x in src {
        dst.push(*x);
    }
}

fn first_or(v: &[i64], d: i64) -> i64 {
    if v.is_empty() {
        return d;
    }
    v[0]
}
