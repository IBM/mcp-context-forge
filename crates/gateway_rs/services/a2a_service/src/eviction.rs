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
            if let Some(entry) = map.iter().next() {
                let key = entry.key().clone();
                drop(entry);
                map.remove(&key);
            }
        }
    }
}
