use std::collections::HashMap;
use std::hash::Hash;

fn get_default<'r, K: Hash + Eq + Copy, V: Default>(
    map: &'r mut HashMap<K, V>,
    key: K,
) -> &'r mut V {
    match map.get_mut(&key) {
        Some(value) => value,
        None => {
            map.insert(key, V::default());
            map.get_mut(&key).unwrap()
        }
    }
}

fn main() {
    let mut m: HashMap<i32, String> = HashMap::new();
    println!("{}", get_default(&mut m, 1));
}
