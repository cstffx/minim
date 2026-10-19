fn total(lines: &[String]) -> i64 {
    let mut t: i64 = 0;
    for s in lines {
        let n: i64 = match s.trim().parse::<i64>() {
            Ok(n) => n,
            Err(_) => continue,
        };
        if n % 2 == 0 {
            t += n;
        }
    }
    t
}
