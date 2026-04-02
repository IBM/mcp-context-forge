// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for the rate limiter memory backend.
// PERF-01, MEM-02, MEM-03, MEM-04.
//
// These benchmarks test the raw MemoryStore performance (no PyO3 overhead)
// across various access patterns: single-key, multi-dim, hot-counter,
// blocked-path, many-keys, and multi-threaded contention.

use std::hint::black_box;
use std::sync::Arc;

use criterion::{Criterion, criterion_group, criterion_main};
use rate_limiter_rust::{clock::FakeClock, config::Algorithm, memory::MemoryStore};

const T0_UNIX: i64 = 1_000_000;
const LIMIT: u64 = 100;
const WINDOW: u64 = 60_000_000_000; // 60s in nanos

fn make_store_and_clock() -> (Arc<MemoryStore>, rate_limiter_rust::clock::FakeClockHandle) {
    let (clock, handle) = FakeClock::new(T0_UNIX);
    let _ = clock; // clock is only needed for engine; store uses explicit timestamps
    (Arc::new(MemoryStore::new()), handle)
}

// ---------------------------------------------------------------------------
// Original single-key benchmarks (direct MemoryStore, no Python required)
// ---------------------------------------------------------------------------

fn bench_fixed_window(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    c.bench_function("fixed_window/single_key", |b| {
        b.iter(|| {
            handle.advance_secs(61);
            store.check_and_increment(
                black_box("user:bench"),
                LIMIT,
                WINDOW,
                Algorithm::FixedWindow,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

fn bench_token_bucket(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    c.bench_function("token_bucket/single_key", |b| {
        b.iter(|| {
            handle.advance_secs(61);
            store.check_and_increment(
                black_box("user:bench"),
                LIMIT,
                WINDOW,
                Algorithm::TokenBucket,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

fn bench_sliding_window(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    c.bench_function("sliding_window/single_key", |b| {
        b.iter(|| {
            handle.advance_secs(61);
            store.check_and_increment(
                black_box("user:bench"),
                LIMIT,
                WINDOW,
                Algorithm::SlidingWindow,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

fn bench_multi_dim(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    c.bench_function("fixed_window/three_dims", |b| {
        b.iter(|| {
            handle.advance_secs(61);
            let now_mono = handle.monotonic_nanos();
            let now_unix = handle.unix_secs();
            let _r1 = store.check_and_increment(
                "user:alice",
                LIMIT,
                WINDOW,
                Algorithm::FixedWindow,
                now_mono,
                now_unix,
            );
            let _r2 = store.check_and_increment(
                "tenant:acme",
                LIMIT * 100,
                WINDOW,
                Algorithm::FixedWindow,
                now_mono,
                now_unix,
            );
            let _r3 = store.check_and_increment(
                "tool:search",
                LIMIT / 10,
                WINDOW,
                Algorithm::FixedWindow,
                now_mono,
                now_unix,
            );
        })
    });
}

// ---------------------------------------------------------------------------
// Hot-counter: counter at near-limit, no window reset between iterations
// ---------------------------------------------------------------------------

fn bench_fixed_window_hot_counter(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    let mut iteration = 0u64;
    c.bench_function("fixed_window/hot_counter", |b| {
        b.iter(|| {
            iteration += 1;
            // Reset the window every LIMIT iterations to prevent permanent blocking
            if iteration.is_multiple_of(LIMIT) {
                handle.advance_secs(61);
            }
            store.check_and_increment(
                black_box("user:hot"),
                LIMIT,
                WINDOW,
                Algorithm::FixedWindow,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

// ---------------------------------------------------------------------------
// Blocked-path: counter past limit, measures reject code path
// ---------------------------------------------------------------------------

fn bench_fixed_window_blocked(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    // Exhaust the limit once
    let now_mono = handle.monotonic_nanos();
    let now_unix = handle.unix_secs();
    for _ in 0..LIMIT {
        store.check_and_increment(
            "user:blocked",
            LIMIT,
            WINDOW,
            Algorithm::FixedWindow,
            now_mono,
            now_unix,
        );
    }
    // Now every call hits the blocked path
    c.bench_function("fixed_window/blocked_path", |b| {
        b.iter(|| {
            store.check_and_increment(
                black_box("user:blocked"),
                LIMIT,
                WINDOW,
                Algorithm::FixedWindow,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

// ---------------------------------------------------------------------------
// Many-keys: tests HashMap scaling and cache behavior
// ---------------------------------------------------------------------------

fn bench_fixed_window_many_keys(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();
    let keys: Vec<String> = (0..10_000).map(|i| format!("user:many{}", i)).collect();
    let mut key_idx = 0usize;
    c.bench_function("fixed_window/many_keys_10k", |b| {
        b.iter(|| {
            key_idx = (key_idx + 1) % keys.len();
            store.check_and_increment(
                black_box(&keys[key_idx]),
                LIMIT,
                WINDOW,
                Algorithm::FixedWindow,
                handle.monotonic_nanos(),
                handle.unix_secs(),
            )
        })
    });
}

// ---------------------------------------------------------------------------
// Multi-threaded: concurrent access from N threads (parking_lot contention)
// ---------------------------------------------------------------------------

fn bench_fixed_window_concurrent(c: &mut Criterion) {
    let (store, handle) = make_store_and_clock();

    for threads in [2, 4, 8] {
        c.bench_function(&format!("fixed_window/concurrent_{}t", threads), |b| {
            b.iter(|| {
                handle.advance_secs(61);
                let now_mono = handle.monotonic_nanos();
                let now_unix = handle.unix_secs();
                std::thread::scope(|s| {
                    for t in 0..threads {
                        let store = &store;
                        s.spawn(move || {
                            store.check_and_increment(
                                &format!("user:thread{}", t),
                                LIMIT,
                                WINDOW,
                                Algorithm::FixedWindow,
                                now_mono,
                                now_unix,
                            )
                        });
                    }
                });
            })
        });
    }
}

criterion_group!(
    benches,
    bench_fixed_window,
    bench_token_bucket,
    bench_sliding_window,
    bench_multi_dim,
    bench_fixed_window_hot_counter,
    bench_fixed_window_blocked,
    bench_fixed_window_many_keys,
    bench_fixed_window_concurrent,
);
criterion_main!(benches);
