use std::collections::HashMap;
use std::env;
use std::fs;

fn count(path: &str) -> std::io::Result<HashMap<String, i64>> {
    let text = fs::read_to_string(path)?;
    let mut c: HashMap<String, i64> = HashMap::new();
    for line in text.lines() {
        for w in line.split_whitespace() {
            let key = w
                .to_lowercase()
                .trim_matches(|ch: char| ch.is_ascii_punctuation())
                .to_string();
            *c.entry(key).or_insert(0) += 1;
        }
    }
    Ok(c)
}

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| "in.txt".to_string());
    let c = match count(&path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("error: {}", e);
            return;
        }
    };
    let mut v: Vec<_> = c.into_iter().collect();
    v.sort_by(|a, b| b.1.cmp(&a.1));
    for (w, k) in v.iter().take(10) {
        println!("{:6} {}", k, w);
    }
}
