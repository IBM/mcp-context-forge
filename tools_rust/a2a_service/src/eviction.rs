//! Shared eviction helper for capacity-bounded maps.
//!
//! Used by circuit breaker and metrics collector to bound memory by removing one entry when at capacity.

use std::hash::Hash;

use dashmap::DashMap;

/// If `max_entries` is `Some(max)` and `map.len() >= max`, removes one arbitrary entry from `map`.
/// No-op when `max_entries` is `None` or map is under capacity.
pub fn evict_one_if_over_capacity<K, V>(map: &DashMap<K, V>, max_entries: Option<usize>)
where
    K: Clone + Hash + Eq,
{
    if let Some(max) = max_entries {
        if map.len() >= max {
            // IMPORTANT: avoid calling `remove` while holding an iterator guard.
            // Some DashMap internals can deadlock if a shard is re-locked while an
            // iterator guard is still alive.
            let key = map.iter().next().map(|entry| entry.key().clone());
            if let Some(key) = key {
                map.remove(&key);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_evict_none_max_entries_no_op() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".to_string(), 1);
        evict_one_if_over_capacity(&map, None);
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn test_evict_under_capacity_no_op() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".to_string(), 1);
        evict_one_if_over_capacity(&map, Some(2));
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn test_evict_at_capacity_removes_one() {
        let map: DashMap<String, i32> = DashMap::new();
        map.insert("a".to_string(), 1);
        map.insert("b".to_string(), 2);
        evict_one_if_over_capacity(&map, Some(2));
        assert_eq!(map.len(), 1);
    }
}
