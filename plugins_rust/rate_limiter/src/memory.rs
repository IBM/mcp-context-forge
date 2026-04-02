// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// In-process memory backend for the rate limiter engine.
//
// Per-key locking via `parking_lot::RwLock` — no single global lock (MEM-01).
// Typed key is the raw string passed from the engine; callers are responsible
// for constructing distinct keys per dimension (e.g. "user:alice", "tenant:acme").
//
// Algorithms implemented:
//   - FixedWindow  (MEM-02): HashMap<key, (count, window_start_nanos)>
//   - SlidingWindow (MEM-03): HashMap<key, VecDeque<timestamp_nanos>>
//   - TokenBucket  (MEM-04): HashMap<key, (tokens_u64_x1000, last_refill_nanos)>
//
// Cleanup is amortized on access — no background sweep thread (MEM-05).
// Idle key eviction runs every ~128 calls to reclaim memory (MEM-06).

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};

use parking_lot::RwLock;

use crate::clock::{Nanos, UnixSecs};
use crate::config::Algorithm;
use crate::types::DimResult;

/// How often (in calls) the amortized sweep runs.  Power of 2 for cheap
/// modulo via bitwise AND.  128 means ~0.8% of calls pay the sweep cost.
const SWEEP_INTERVAL: u64 = 128;

/// Token bucket keys inactive for longer than this are evicted (1 hour in
/// nanos).  Matches the Python `TokenBucketAlgorithm.sweep` threshold.
const TOKEN_BUCKET_STALE_NANOS: u64 = 3_600_000_000_000;

// ---------------------------------------------------------------------------
// Per-key state
// ---------------------------------------------------------------------------

#[derive(Debug)]
enum KeyState {
    FixedWindow {
        count: u64,
        window_start: Nanos,
        /// Unix timestamp when the window started — used to compute a constant
        /// reset_timestamp within the window (matching Python backend behaviour).
        window_start_unix: UnixSecs,
        /// Window duration in nanos — stored per key so sweep can evict at the
        /// actual window boundary instead of using a hardcoded 1-hour threshold.
        window_nanos: Nanos,
    },
    SlidingWindow {
        timestamps: VecDeque<Nanos>,
        /// Window duration in nanos — stored per key so sweep can drain stale
        /// timestamps and evict idle keys without waiting for the next access.
        window_nanos: Nanos,
    },
    TokenBucket {
        /// Tokens × 1000 to avoid floating-point (CORR-05).
        tokens_milli: u64,
        last_refill: Nanos,
    },
}

// ---------------------------------------------------------------------------
// MemoryStore
// ---------------------------------------------------------------------------

pub struct MemoryStore {
    inner: RwLock<HashMap<String, RwLock<KeyState>>>,
    call_count: AtomicU64,
}

impl Default for MemoryStore {
    fn default() -> Self {
        Self::new()
    }
}

impl MemoryStore {
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(HashMap::new()),
            call_count: AtomicU64::new(0),
        }
    }

    /// Amortized sweep: remove keys whose state is stale (MEM-06).
    ///
    /// - FixedWindow: evict if the configured window has fully elapsed.
    /// - SlidingWindow: drain stale timestamps, then evict if the deque is empty.
    /// - TokenBucket: inactive for > 1 hour (matching Python `TokenBucketAlgorithm.sweep`).
    fn sweep(&self, now_mono: Nanos) {
        let mut write = self.inner.write();
        write.retain(|_key, key_lock| {
            // Skip keys that are currently write-locked (actively being used).
            let mut state = match key_lock.try_write() {
                Some(guard) => guard,
                None => return true, // contended — keep
            };
            match &mut *state {
                KeyState::FixedWindow {
                    window_start,
                    window_nanos,
                    ..
                } => {
                    // Evict if the configured window has fully elapsed.
                    now_mono.saturating_sub(*window_start) < *window_nanos
                }
                KeyState::SlidingWindow {
                    timestamps,
                    window_nanos,
                } => {
                    // Drain stale timestamps that have fallen outside the window,
                    // then evict if the deque is empty.  This reclaims keys that
                    // went cold after traffic — previously they lingered forever
                    // because stale timestamps were only drained on access.
                    let cutoff = now_mono.saturating_sub(*window_nanos);
                    while timestamps.front().is_some_and(|&t| t <= cutoff) {
                        timestamps.pop_front();
                    }
                    !timestamps.is_empty()
                }
                KeyState::TokenBucket { last_refill, .. } => {
                    // Evict if inactive for more than 1 hour.
                    now_mono.saturating_sub(*last_refill) < TOKEN_BUCKET_STALE_NANOS
                }
            }
        });
    }

    /// Check the rate for `key` and increment the counter if allowed.
    ///
    /// Returns a `DimResult` with allow/block, remaining, reset_timestamp,
    /// and retry_after. All timing uses the injected `now_mono` and `now_unix`
    /// values — no direct clock calls inside this function (CORR-06).
    pub fn check_and_increment(
        &self,
        key: &str,
        limit: u64,
        window_nanos: u64,
        algorithm: Algorithm,
        now_mono: Nanos,
        now_unix: UnixSecs,
    ) -> DimResult {
        // Fast path: key already exists — single read lock on outer map.
        let result = {
            let read = self.inner.read();
            if let Some(key_lock) = read.get(key) {
                let mut state = key_lock.write();
                Some(evaluate_state(
                    &mut state,
                    limit,
                    window_nanos,
                    now_mono,
                    now_unix,
                ))
            } else {
                None
            }
        };

        let result = result.unwrap_or_else(|| {
            // Slow path: key missing — write lock to insert, then evaluate.
            // Only runs on first access per key; steady-state always hits fast path.
            let mut write = self.inner.write();
            let key_lock = write.entry(key.to_string()).or_insert_with(|| {
                RwLock::new(new_key_state(
                    algorithm,
                    limit,
                    window_nanos,
                    now_mono,
                    now_unix,
                ))
            });
            let mut state = key_lock.write();
            evaluate_state(&mut state, limit, window_nanos, now_mono, now_unix)
        });

        // All locks dropped — amortized sweep (MEM-06).
        let n = self.call_count.fetch_add(1, Ordering::Relaxed);
        if n & (SWEEP_INTERVAL - 1) == 0 && n > 0 {
            self.sweep(now_mono);
        }
        result
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Create the initial key state for a new rate-limit key.
fn new_key_state(
    algorithm: Algorithm,
    limit: u64,
    window_nanos: u64,
    now_mono: Nanos,
    now_unix: UnixSecs,
) -> KeyState {
    match algorithm {
        Algorithm::FixedWindow => KeyState::FixedWindow {
            count: 0,
            window_start: now_mono,
            window_start_unix: now_unix,
            window_nanos,
        },
        Algorithm::SlidingWindow => KeyState::SlidingWindow {
            timestamps: VecDeque::new(),
            window_nanos,
        },
        Algorithm::TokenBucket => KeyState::TokenBucket {
            tokens_milli: limit.saturating_mul(1000),
            last_refill: now_mono,
        },
    }
}

/// Dispatch to the correct algorithm based on the key state variant.
fn evaluate_state(
    state: &mut KeyState,
    limit: u64,
    window_nanos: u64,
    now_mono: Nanos,
    now_unix: UnixSecs,
) -> DimResult {
    match state {
        KeyState::FixedWindow {
            count,
            window_start,
            window_start_unix,
            ..
        } => fixed_window(
            count,
            window_start,
            window_start_unix,
            limit,
            window_nanos,
            now_mono,
            now_unix,
        ),
        KeyState::SlidingWindow { timestamps, .. } => {
            sliding_window(timestamps, limit, window_nanos, now_mono, now_unix)
        }
        KeyState::TokenBucket {
            tokens_milli,
            last_refill,
        } => token_bucket(
            tokens_milli,
            last_refill,
            limit,
            window_nanos,
            now_mono,
            now_unix,
        ),
    }
}

// ---------------------------------------------------------------------------
// Algorithm implementations
// ---------------------------------------------------------------------------

fn fixed_window(
    count: &mut u64,
    window_start: &mut Nanos,
    window_start_unix: &mut UnixSecs,
    limit: u64,
    window_nanos: u64,
    now_mono: Nanos,
    now_unix: UnixSecs,
) -> DimResult {
    // Reset if window has elapsed (amortized cleanup, MEM-05).
    if now_mono.saturating_sub(*window_start) >= window_nanos {
        *count = 0;
        *window_start = now_mono;
        *window_start_unix = now_unix;
    }

    // At least 1 second so reset_timestamp is always in the future, even if
    // window_nanos < 1 billion (sub-second window — currently unreachable via
    // config parsing but guarded defensively).
    let window_secs = (window_nanos / 1_000_000_000).max(1) as i64;
    // Constant within a window — matches Python backend behaviour (CORR-02).
    let reset_timestamp = *window_start_unix + window_secs;

    if *count < limit {
        *count += 1;
        let remaining = limit - *count;
        DimResult {
            allowed: true,
            limit,
            remaining,
            reset_timestamp,
            retry_after: None,
        }
    } else {
        let elapsed_nanos = now_mono.saturating_sub(*window_start);
        let remaining_nanos = window_nanos.saturating_sub(elapsed_nanos);
        let retry_after = (remaining_nanos / 1_000_000_000) as i64;
        DimResult {
            allowed: false,
            limit,
            remaining: 0,
            reset_timestamp,
            retry_after: Some(retry_after.max(1)),
        }
    }
}

fn sliding_window(
    timestamps: &mut VecDeque<Nanos>,
    limit: u64,
    window_nanos: u64,
    now_mono: Nanos,
    now_unix: UnixSecs,
) -> DimResult {
    // Evict timestamps older than the window (amortized cleanup).
    let cutoff = now_mono.saturating_sub(window_nanos);
    while timestamps.front().is_some_and(|&t| t <= cutoff) {
        timestamps.pop_front();
    }

    let count = timestamps.len() as u64;

    // Reset timestamp: when the oldest timestamp in the window expires.
    // .max(1) on the division result ensures reset_timestamp is always
    // strictly in the future, even when the oldest entry expires in < 1 s
    // (integer division would otherwise truncate to 0).
    let reset_timestamp = if let Some(&oldest) = timestamps.front() {
        let nanos_until_oldest_expires = (oldest + window_nanos).saturating_sub(now_mono);
        now_unix + (nanos_until_oldest_expires / 1_000_000_000).max(1) as i64
    } else {
        // No requests in window — reset is now + window.
        now_unix + (window_nanos / 1_000_000_000) as i64
    };

    if count < limit {
        timestamps.push_back(now_mono);
        let remaining = limit - count - 1;
        DimResult {
            allowed: true,
            limit,
            remaining,
            reset_timestamp,
            retry_after: None,
        }
    } else {
        // Oldest timestamp expiry = retry_after.
        let retry_after = if let Some(&oldest) = timestamps.front() {
            let nanos_until = (oldest + window_nanos).saturating_sub(now_mono);
            (nanos_until / 1_000_000_000) as i64
        } else {
            1
        };
        DimResult {
            allowed: false,
            limit,
            remaining: 0,
            reset_timestamp,
            retry_after: Some(retry_after.max(1)),
        }
    }
}

fn token_bucket(
    tokens_milli: &mut u64,
    last_refill: &mut Nanos,
    limit: u64,
    window_nanos: u64,
    now_mono: Nanos,
    now_unix: UnixSecs,
) -> DimResult {
    // Refill tokens proportional to elapsed time (integer math, CORR-05).
    // refill_rate = limit * 1000 tokens per window_nanos nanoseconds.
    let elapsed = now_mono.saturating_sub(*last_refill);
    if elapsed > 0 {
        // tokens_to_add = limit * 1000 * elapsed / window_nanos
        let tokens_to_add = (limit as u128 * 1000 * elapsed as u128 / window_nanos as u128) as u64;
        *tokens_milli = (*tokens_milli + tokens_to_add).min(limit.saturating_mul(1000));
        *last_refill = now_mono;
    }

    let cap_milli = limit.saturating_mul(1000);

    if *tokens_milli >= 1000 {
        *tokens_milli -= 1000;
        let remaining = *tokens_milli / 1000;
        // reset_timestamp: when bucket would next be full if no more requests arrive.
        let tokens_needed_milli = cap_milli.saturating_sub(*tokens_milli);
        let refill_secs = if tokens_needed_milli == 0 {
            0i64
        } else {
            let nanos = (tokens_needed_milli as u128 * window_nanos as u128
                / (limit as u128 * 1000)) as u64;
            (nanos / 1_000_000_000).max(1) as i64
        };
        let reset_timestamp = now_unix + refill_secs;
        DimResult {
            allowed: true,
            limit,
            remaining,
            reset_timestamp,
            retry_after: None,
        }
    } else {
        // No token available — compute time until 1 token refills.
        let tokens_needed_milli = 1000u128.saturating_sub(*tokens_milli as u128);
        let nanos_until_token =
            (tokens_needed_milli * window_nanos as u128 / (limit as u128 * 1000)).max(1);
        let retry_after = nanos_until_token.div_ceil(1_000_000_000).max(1) as i64;
        let reset_timestamp = now_unix + retry_after;
        DimResult {
            allowed: false,
            limit,
            remaining: 0,
            reset_timestamp,
            retry_after: Some(retry_after),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Algorithm;

    const WINDOW: u64 = 1_000_000_000; // 1 second in nanos
    const T0: Nanos = 1_000_000_000_000; // arbitrary start
    const T0_UNIX: UnixSecs = 1_000_000;

    fn check(store: &MemoryStore, key: &str, limit: u64, algo: Algorithm, t: Nanos) -> DimResult {
        store.check_and_increment(
            key,
            limit,
            WINDOW,
            algo,
            t,
            T0_UNIX + ((t - T0) / 1_000_000_000) as i64,
        )
    }

    // --- Fixed window ---

    #[test]
    fn fixed_window_allows_up_to_limit() {
        let store = MemoryStore::new();
        for _ in 0..3 {
            let r = check(&store, "u:a", 3, Algorithm::FixedWindow, T0);
            assert!(r.allowed);
        }
        let r = check(&store, "u:a", 3, Algorithm::FixedWindow, T0);
        assert!(!r.allowed);
    }

    #[test]
    fn fixed_window_resets_after_window() {
        let store = MemoryStore::new();
        for _ in 0..3 {
            check(&store, "u:b", 3, Algorithm::FixedWindow, T0);
        }
        // Advance past window
        let r = check(&store, "u:b", 3, Algorithm::FixedWindow, T0 + WINDOW + 1);
        assert!(r.allowed);
    }

    #[test]
    fn fixed_window_reset_timestamp_constant_within_window() {
        let store = MemoryStore::new();
        let r1 = check(&store, "u:c", 10, Algorithm::FixedWindow, T0);
        let r2 = check(&store, "u:c", 10, Algorithm::FixedWindow, T0 + 100_000_000);
        assert!(r1.allowed);
        assert!(r2.allowed);
        // reset_timestamp must be identical across requests in the same window.
        assert_eq!(r1.reset_timestamp, r2.reset_timestamp);
        assert!(r1.reset_timestamp > T0_UNIX);
    }

    #[test]
    fn fixed_window_retry_after_at_least_one() {
        let store = MemoryStore::new();
        for _ in 0..2 {
            check(&store, "u:d", 2, Algorithm::FixedWindow, T0);
        }
        let r = check(&store, "u:d", 2, Algorithm::FixedWindow, T0);
        assert!(!r.allowed);
        assert!(r.retry_after.unwrap() >= 1);
    }

    // --- Sliding window ---

    #[test]
    fn sliding_window_allows_up_to_limit() {
        let store = MemoryStore::new();
        for _ in 0..3 {
            assert!(check(&store, "sw:a", 3, Algorithm::SlidingWindow, T0).allowed);
        }
        assert!(!check(&store, "sw:a", 3, Algorithm::SlidingWindow, T0).allowed);
    }

    #[test]
    fn sliding_window_allows_after_oldest_expires() {
        let store = MemoryStore::new();
        check(&store, "sw:b", 3, Algorithm::SlidingWindow, T0);
        check(
            &store,
            "sw:b",
            3,
            Algorithm::SlidingWindow,
            T0 + 100_000_000,
        );
        check(
            &store,
            "sw:b",
            3,
            Algorithm::SlidingWindow,
            T0 + 200_000_000,
        );
        // Blocked at T0
        assert!(
            !check(
                &store,
                "sw:b",
                3,
                Algorithm::SlidingWindow,
                T0 + 500_000_000
            )
            .allowed
        );
        // Oldest (T0) expires after WINDOW; T0 + WINDOW + 1 > T0 + WINDOW
        assert!(check(&store, "sw:b", 3, Algorithm::SlidingWindow, T0 + WINDOW + 1).allowed);
    }

    #[test]
    fn sliding_window_no_boundary_burst() {
        // With fixed window you could get 2N at the boundary.
        // Sliding window prevents this: N requests just before window end,
        // then N at window start should still block.
        let store = MemoryStore::new();
        let mid = T0 + WINDOW / 2;
        for _ in 0..3 {
            check(&store, "sw:c", 3, Algorithm::SlidingWindow, mid);
        }
        // Just after window start, the mid-window requests are still in range.
        let r = check(&store, "sw:c", 3, Algorithm::SlidingWindow, T0 + WINDOW + 1);
        // mid timestamps expire at mid + WINDOW = T0 + WINDOW/2 + WINDOW
        // T0 + WINDOW + 1 < T0 + 3*WINDOW/2, so they're still in range → blocked
        assert!(!r.allowed);
    }

    // --- Token bucket ---

    #[test]
    fn token_bucket_allows_up_to_capacity() {
        let store = MemoryStore::new();
        for _ in 0..3 {
            assert!(check(&store, "tb:a", 3, Algorithm::TokenBucket, T0).allowed);
        }
        assert!(!check(&store, "tb:a", 3, Algorithm::TokenBucket, T0).allowed);
    }

    #[test]
    fn token_bucket_refills_over_time() {
        let store = MemoryStore::new();
        // Exhaust 3-token bucket
        for _ in 0..3 {
            check(&store, "tb:b", 3, Algorithm::TokenBucket, T0);
        }
        // Wait full window — should refill to capacity
        let r = check(&store, "tb:b", 3, Algorithm::TokenBucket, T0 + WINDOW);
        assert!(r.allowed);
    }

    #[test]
    fn token_bucket_integer_math_no_overflow() {
        let store = MemoryStore::new();
        // Large limit — should not overflow u64
        let r = check(&store, "tb:c", u64::MAX / 1001, Algorithm::TokenBucket, T0);
        assert!(r.allowed);
    }

    #[test]
    fn token_bucket_reset_timestamp_strictly_greater_than_now() {
        let store = MemoryStore::new();
        let r = check(&store, "tb:d", 10, Algorithm::TokenBucket, T0);
        assert!(r.allowed);
        assert!(r.reset_timestamp > T0_UNIX);
    }

    // --- Key isolation ---

    #[test]
    fn different_keys_have_independent_counters() {
        let store = MemoryStore::new();
        for _ in 0..3 {
            check(&store, "u:x", 3, Algorithm::FixedWindow, T0);
        }
        // Different key must still be allowed
        let r = check(&store, "u:y", 3, Algorithm::FixedWindow, T0);
        assert!(r.allowed);
    }

    // --- Sweep (MEM-06) ---

    #[test]
    fn sweep_evicts_stale_fixed_window_keys() {
        let store = MemoryStore::new();
        check(&store, "sweep:fw", 3, Algorithm::FixedWindow, T0);
        assert_eq!(store.inner.read().len(), 1);

        // Advance just past window_nanos (WINDOW = 1 s) — fixed-window eviction
        // uses the per-key window duration, not TOKEN_BUCKET_STALE_NANOS.
        let stale_time = T0 + WINDOW + 1;
        store.sweep(stale_time);
        assert_eq!(
            store.inner.read().len(),
            0,
            "stale fixed window key must be evicted"
        );
    }

    #[test]
    fn sweep_evicts_empty_sliding_window_keys() {
        let store = MemoryStore::new();
        // Create a sliding window entry then advance past the window so
        // the per-access cleanup drains the deque.
        check(&store, "sweep:sw", 3, Algorithm::SlidingWindow, T0);
        assert_eq!(store.inner.read().len(), 1);

        // Access after window elapses — the per-access cutoff drains all timestamps.
        check(
            &store,
            "sweep:sw",
            3,
            Algorithm::SlidingWindow,
            T0 + WINDOW + 1,
        );
        // Deque now has one fresh entry; sweep should keep it.
        store.sweep(T0 + WINDOW + 1);
        assert_eq!(
            store.inner.read().len(),
            1,
            "active sliding window key must be kept"
        );

        // Advance far enough that a sweep after window drain would evict.
        let far_future = T0 + WINDOW * 100;
        // Access once to create a timestamp, then advance past its window.
        check(&store, "sweep:sw2", 1, Algorithm::SlidingWindow, T0);
        let after_window = T0 + WINDOW + 1;
        // This access drains T0, adds after_window.
        check(
            &store,
            "sweep:sw2",
            1,
            Algorithm::SlidingWindow,
            after_window,
        );
        // Now advance far past, access to drain the deque with a blocked request.
        let _ = check(&store, "sweep:sw2", 1, Algorithm::SlidingWindow, far_future);
        // The above drains old entries and adds one new one; next access after that window:
        let very_far = far_future + WINDOW + 1;
        // This drains the far_future entry (outside window) — but adds a new one.
        // We need the deque truly empty: exhaust limit then wait.
        // Simpler: call sweep directly and check that a key with empty deque gets evicted.
        // Manually construct this scenario:
        {
            let read = store.inner.read();
            if let Some(lock) = read.get("sweep:sw2") {
                let mut state = lock.write();
                if let KeyState::SlidingWindow { timestamps, .. } = &mut *state {
                    timestamps.clear();
                }
            }
        }
        store.sweep(very_far);
        assert!(
            store.inner.read().get("sweep:sw2").is_none(),
            "sliding window key with empty deque must be evicted"
        );
    }

    #[test]
    fn sweep_evicts_stale_token_bucket_keys() {
        let store = MemoryStore::new();
        check(&store, "sweep:tb", 3, Algorithm::TokenBucket, T0);
        assert_eq!(store.inner.read().len(), 1);

        let stale_time = T0 + super::TOKEN_BUCKET_STALE_NANOS + 1;
        store.sweep(stale_time);
        assert_eq!(
            store.inner.read().len(),
            0,
            "stale token bucket key must be evicted"
        );
    }

    #[test]
    fn sweep_keeps_active_keys() {
        let store = MemoryStore::new();
        check(&store, "sweep:active", 10, Algorithm::FixedWindow, T0);
        // Sweep at a time within the window — key should be kept.
        // WINDOW is 1s; sweep 500ms later (still inside the window).
        store.sweep(T0 + 500_000_000);
        assert_eq!(
            store.inner.read().len(),
            1,
            "active key must not be evicted"
        );
    }
}
