// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Shared utility for capacity-bounded DashMap collections.

use dashmap::DashMap;
use std::hash::Hash;

/// Remove one arbitrary entry when `map.len() >= max_entries`.
///
/// When `max_entries` is `None` the call is a no-op (unlimited).
/// The iterator guard is dropped before calling `remove` to avoid deadlock.
pub fn evict_one_if_over_capacity<K, V>(map: &DashMap<K, V>, max_entries: Option<usize>)
where
    K: Clone + Eq + Hash,
{
    let limit = match max_entries {
        Some(n) => n,
        None => return,
    };

    if map.len() < limit {
        return;
    }

    // Grab a key while holding the read guard, then drop it before mutating.
    let key = {
        let entry = map.iter().next();
        match entry {
            Some(r) => r.key().clone(),
            None => return,
        }
    };

    map.remove(&key);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_op_when_max_entries_is_none() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".into(), 1);
        evict_one_if_over_capacity(&map, None);
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn no_op_when_under_capacity() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".into(), 1);
        evict_one_if_over_capacity(&map, Some(5));
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn evicts_when_at_capacity() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".into(), 1);
        map.insert("b".into(), 2);
        evict_one_if_over_capacity(&map, Some(2));
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn evicts_when_over_capacity() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".into(), 1);
        map.insert("b".into(), 2);
        map.insert("c".into(), 3);
        evict_one_if_over_capacity(&map, Some(2));
        assert_eq!(map.len(), 2);
    }
}
