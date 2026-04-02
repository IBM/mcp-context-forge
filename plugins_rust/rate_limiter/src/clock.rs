// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Clock abstraction for rate limiter engine.
//
// All internal rate math uses `Clock::now_monotonic()` (nanoseconds).
// Wall-clock Unix timestamps (for response headers) use `Clock::now_unix_secs()`.
//
// Tests inject `FakeClock` to make all timing-dependent assertions deterministic.

/// Monotonic time in nanoseconds since an arbitrary epoch.
pub type Nanos = u64;

/// Unix timestamp in whole seconds (for X-RateLimit-Reset headers).
pub type UnixSecs = i64;

/// Clock abstraction injected into the engine at construction time.
pub trait Clock: Send + Sync + 'static {
    /// Monotonic nanosecond counter — used for all rate math.
    fn now_monotonic(&self) -> Nanos;

    /// Wall-clock Unix seconds — used only for header timestamps.
    fn now_unix_secs(&self) -> UnixSecs;
}

// ---------------------------------------------------------------------------
// Real clock — delegates to std::time
// ---------------------------------------------------------------------------

/// Production clock backed by `std::time`.
#[derive(Debug, Clone, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_monotonic(&self) -> Nanos {
        use std::sync::OnceLock;
        use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

        // Instant is monotonic; we anchor it to a fixed start to get nanoseconds.
        // We use a process-global anchor so monotonic values are comparable
        // across threads — required because MemoryStore is shared via RwLock.
        static ANCHOR: OnceLock<(Instant, u64)> = OnceLock::new();
        let (anchor_instant, anchor_nanos) = ANCHOR.get_or_init(|| {
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or(Duration::ZERO)
                .as_nanos() as u64;
            (Instant::now(), nanos)
        });
        let elapsed = anchor_instant.elapsed().as_nanos() as u64;
        anchor_nanos + elapsed
    }

    fn now_unix_secs(&self) -> UnixSecs {
        use std::time::{Duration, SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or(Duration::ZERO)
            .as_secs() as i64
    }
}

// ---------------------------------------------------------------------------
// Fake clock — for deterministic tests
// ---------------------------------------------------------------------------

use std::sync::Arc;
use std::sync::atomic::{AtomicI64, AtomicU64, Ordering};

/// Shareable handle to advance a `FakeClock` from test code.
#[derive(Clone, Debug)]
pub struct FakeClockHandle {
    monotonic_nanos: Arc<AtomicU64>,
    unix_secs: Arc<AtomicI64>,
}

impl FakeClockHandle {
    /// Advance the monotonic clock by `nanos` nanoseconds.
    pub fn advance_nanos(&self, nanos: u64) {
        self.monotonic_nanos.fetch_add(nanos, Ordering::SeqCst);
    }

    /// Advance both clocks by `secs` seconds.
    pub fn advance_secs(&self, secs: u64) {
        self.monotonic_nanos
            .fetch_add(secs * 1_000_000_000, Ordering::SeqCst);
        self.unix_secs.fetch_add(secs as i64, Ordering::SeqCst);
    }

    /// Set the Unix wall-clock to an absolute value (for header assertions).
    pub fn set_unix_secs(&self, secs: i64) {
        self.unix_secs.store(secs, Ordering::SeqCst);
    }

    /// Read the current monotonic value.
    pub fn monotonic_nanos(&self) -> u64 {
        self.monotonic_nanos.load(Ordering::SeqCst)
    }

    /// Read the current Unix seconds value.
    pub fn unix_secs(&self) -> i64 {
        self.unix_secs.load(Ordering::SeqCst)
    }
}

/// A `Clock` implementation driven by atomics — suitable for concurrent tests.
pub struct FakeClock {
    monotonic_nanos: Arc<AtomicU64>,
    unix_secs: Arc<AtomicI64>,
}

impl FakeClock {
    /// Create a `FakeClock` starting at the given Unix epoch and a matching
    /// monotonic counter, returning both the clock and a control handle.
    pub fn new(start_unix_secs: i64) -> (Self, FakeClockHandle) {
        let mono = Arc::new(AtomicU64::new(start_unix_secs as u64 * 1_000_000_000));
        let wall = Arc::new(AtomicI64::new(start_unix_secs));
        let clock = FakeClock {
            monotonic_nanos: Arc::clone(&mono),
            unix_secs: Arc::clone(&wall),
        };
        let handle = FakeClockHandle {
            monotonic_nanos: mono,
            unix_secs: wall,
        };
        (clock, handle)
    }
}

impl Clock for FakeClock {
    fn now_monotonic(&self) -> Nanos {
        self.monotonic_nanos.load(Ordering::SeqCst)
    }

    fn now_unix_secs(&self) -> UnixSecs {
        self.unix_secs.load(Ordering::SeqCst)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fake_clock_starts_at_given_epoch() {
        let (clock, handle) = FakeClock::new(1_000_000);
        assert_eq!(clock.now_unix_secs(), 1_000_000);
        assert_eq!(clock.now_monotonic(), 1_000_000 * 1_000_000_000);
        let _ = handle;
    }

    #[test]
    fn fake_clock_advances_in_sync() {
        let (clock, handle) = FakeClock::new(1_000_000);
        handle.advance_secs(60);
        assert_eq!(clock.now_unix_secs(), 1_000_060);
        assert_eq!(clock.now_monotonic(), (1_000_000 + 60) * 1_000_000_000);
    }

    #[test]
    fn fake_clock_advance_nanos_does_not_move_wall() {
        let (clock, handle) = FakeClock::new(1_000_000);
        handle.advance_nanos(500_000_000); // 0.5 s
        assert_eq!(clock.now_unix_secs(), 1_000_000); // wall unchanged
        assert_eq!(
            clock.now_monotonic(),
            1_000_000 * 1_000_000_000 + 500_000_000
        );
    }

    #[test]
    fn fake_clock_handle_clone_shares_state() {
        let (clock, handle) = FakeClock::new(0);
        let handle2 = handle.clone();
        handle2.advance_secs(10);
        assert_eq!(clock.now_unix_secs(), 10);
        assert_eq!(handle.unix_secs(), 10);
    }

    #[test]
    fn system_clock_monotonic_is_non_decreasing() {
        let c = SystemClock;
        let t1 = c.now_monotonic();
        let t2 = c.now_monotonic();
        assert!(t2 >= t1);
    }

    #[test]
    fn system_clock_unix_secs_is_positive() {
        let c = SystemClock;
        assert!(c.now_unix_secs() > 0);
    }
}
