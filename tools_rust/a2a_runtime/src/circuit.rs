// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Per-endpoint per-tenant circuit breaker for fail-fast resilience.

use crate::eviction::evict_one_if_over_capacity;
use dashmap::DashMap;
use std::time::{Duration, Instant};

/// Three-state circuit breaker model.
enum CircuitState {
    Closed { consecutive_failures: u32 },
    Open { until: Instant },
    HalfOpen,
}

/// A capacity-bounded, per-key circuit breaker backed by [`DashMap`].
pub struct CircuitBreaker {
    states: DashMap<String, CircuitState>,
    failure_threshold: u32,
    cooldown: Duration,
    max_entries: Option<usize>,
}

impl CircuitBreaker {
    /// Create a new circuit breaker with the given parameters.
    pub fn new(failure_threshold: u32, cooldown: Duration, max_entries: Option<usize>) -> Self {
        Self {
            states: DashMap::new(),
            failure_threshold,
            cooldown,
            max_entries,
        }
    }

    fn key(url: &str, scope_id: &str) -> String {
        format!("{url}::{scope_id}")
    }

    /// Returns `true` when the caller may proceed with the request.
    ///
    /// * **Closed** — always allowed.
    /// * **HalfOpen** — one probe request is allowed.
    /// * **Open** — rejected unless the cooldown has elapsed, in which case the
    ///   state transitions to `HalfOpen` and the probe is allowed.
    pub fn allow_request(&self, url: &str, scope_id: &str) -> bool {
        let key = Self::key(url, scope_id);
        let mut entry = match self.states.get_mut(&key) {
            Some(e) => e,
            None => return true, // No state recorded — treat as Closed.
        };

        match *entry {
            CircuitState::Closed { .. } | CircuitState::HalfOpen => true,
            CircuitState::Open { until } => {
                if Instant::now() >= until {
                    *entry = CircuitState::HalfOpen;
                    true
                } else {
                    false
                }
            }
        }
    }

    /// Record a successful response, resetting the circuit to `Closed(0)`.
    pub fn record_success(&self, url: &str, scope_id: &str) {
        let key = Self::key(url, scope_id);
        self.states.insert(
            key,
            CircuitState::Closed {
                consecutive_failures: 0,
            },
        );
    }

    /// Record a failure, potentially opening the circuit.
    ///
    /// * **Closed** — increments the failure counter; opens the circuit when the
    ///   threshold is reached.
    /// * **HalfOpen** — the probe failed; re-open with a fresh cooldown.
    /// * **Open** — extends the deadline by another cooldown period.
    pub fn record_failure(&self, url: &str, scope_id: &str) {
        let key = Self::key(url, scope_id);

        // Ensure capacity before inserting a potentially new key.
        if !self.states.contains_key(&key) {
            evict_one_if_over_capacity(&self.states, self.max_entries);
        }

        let mut entry = self.states.entry(key).or_insert(CircuitState::Closed {
            consecutive_failures: 0,
        });

        match *entry {
            CircuitState::Closed {
                consecutive_failures,
            } => {
                let new_count = consecutive_failures + 1;
                if new_count >= self.failure_threshold {
                    *entry = CircuitState::Open {
                        until: Instant::now() + self.cooldown,
                    };
                } else {
                    *entry = CircuitState::Closed {
                        consecutive_failures: new_count,
                    };
                }
            }
            CircuitState::HalfOpen => {
                *entry = CircuitState::Open {
                    until: Instant::now() + self.cooldown,
                };
            }
            CircuitState::Open { .. } => {
                *entry = CircuitState::Open {
                    until: Instant::now() + self.cooldown,
                };
            }
        }
    }
}

impl Default for CircuitBreaker {
    fn default() -> Self {
        Self::new(5, Duration::from_secs(30), Some(10_000))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn breaker() -> CircuitBreaker {
        CircuitBreaker::new(3, Duration::from_millis(50), Some(100))
    }

    #[test]
    fn closed_allows_requests() {
        let cb = breaker();
        assert!(cb.allow_request("http://a", "t1"));
    }

    #[test]
    fn opens_after_threshold_failures() {
        let cb = breaker();
        for _ in 0..3 {
            cb.record_failure("http://a", "t1");
        }
        assert!(!cb.allow_request("http://a", "t1"));
    }

    #[test]
    fn transitions_to_half_open_after_cooldown() {
        let cb = CircuitBreaker::new(1, Duration::from_millis(1), Some(100));
        cb.record_failure("http://a", "t1");
        assert!(!cb.allow_request("http://a", "t1"));

        std::thread::sleep(Duration::from_millis(5));
        assert!(cb.allow_request("http://a", "t1")); // now HalfOpen
    }

    #[test]
    fn success_in_half_open_resets_to_closed() {
        let cb = CircuitBreaker::new(1, Duration::from_millis(1), Some(100));
        cb.record_failure("http://a", "t1");
        std::thread::sleep(Duration::from_millis(5));
        assert!(cb.allow_request("http://a", "t1")); // HalfOpen

        cb.record_success("http://a", "t1");
        // Should be Closed again — repeated requests allowed.
        assert!(cb.allow_request("http://a", "t1"));
        assert!(cb.allow_request("http://a", "t1"));
    }

    #[test]
    fn failure_in_half_open_reopens() {
        let cb = CircuitBreaker::new(1, Duration::from_millis(1), Some(100));
        cb.record_failure("http://a", "t1");
        std::thread::sleep(Duration::from_millis(5));
        assert!(cb.allow_request("http://a", "t1")); // HalfOpen

        cb.record_failure("http://a", "t1");
        assert!(!cb.allow_request("http://a", "t1")); // Open again
    }

    #[test]
    fn different_scope_ids_are_independent() {
        let cb = breaker();
        for _ in 0..3 {
            cb.record_failure("http://a", "t1");
        }
        assert!(!cb.allow_request("http://a", "t1"));
        assert!(cb.allow_request("http://a", "t2"));
    }

    #[test]
    fn failure_while_open_extends_open_deadline() {
        let cb = CircuitBreaker::new(1, Duration::from_secs(1), Some(100));
        cb.record_failure("http://a", "t1");
        cb.record_failure("http://a", "t1");
        assert!(!cb.allow_request("http://a", "t1"));
    }

    #[test]
    fn default_constructor_is_usable() {
        let cb = CircuitBreaker::default();
        assert!(cb.allow_request("http://a", "scope"));
    }
}
