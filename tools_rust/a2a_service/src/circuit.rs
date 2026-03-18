//! Per-endpoint circuit breaker for A2A invocations.
//!
//! Tracks failures per key (agent URL or id). After `failure_threshold` consecutive failures the
//! circuit opens and requests are rejected until `cooldown` elapses, then one request is allowed
//! (half-open). Success closes the circuit; failure in half-open reopens it.
//!
//! ## Scope: key is `url::scope_id` (per-tenant isolation)
//!
//! The circuit key is `{url}::{scope_id}` (e.g. team or tenant id). Consequence: one tenant's
//! failures do not open the circuit for other tenants using the same agent URL. Alternative would
//! be a global key per URL for faster fail-fast across all tenants, at the cost of one tenant's
//! failures affecting others.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use dashmap::DashMap;

use crate::eviction;

/// Per-agent circuit state.
#[derive(Debug)]
enum CircuitState {
    Closed(u32),
    Open(Instant),
    HalfOpen,
}

/// Circuit breaker: tracks failures per key (agent URL/id), opens after threshold, cooldown then half-open.
#[derive(Debug)]
pub struct CircuitBreaker {
    states: DashMap<String, Mutex<CircuitState>>,
    failure_threshold: u32,
    cooldown: Duration,
    max_entries: Option<usize>,
}

impl CircuitBreaker {
    /// Create a circuit breaker. If `max_entries` is `Some(n)`, evicts one entry when at capacity to bound memory.
    pub fn new(failure_threshold: u32, cooldown: Duration, max_entries: Option<usize>) -> Self {
        Self {
            states: DashMap::new(),
            failure_threshold,
            cooldown,
            max_entries,
        }
    }

    /// Returns true if a request is allowed (closed or half-open). If open, returns false.
    pub fn allow_request(&self, key: &str) -> bool {
        eviction::evict_one_if_over_capacity(&self.states, self.max_entries);
        let now = Instant::now();
        let mut guard = self
            .states
            .entry(key.to_string())
            .or_insert_with(|| Mutex::new(CircuitState::Closed(0)));
        let state = guard.get_mut().unwrap();
        match state {
            CircuitState::Closed(_) => true,
            CircuitState::Open(until) => {
                if now >= *until {
                    *state = CircuitState::HalfOpen;
                    true
                } else {
                    false
                }
            }
            CircuitState::HalfOpen => true,
        }
    }

    /// Record success; resets closed or moves half-open -> closed.
    pub fn record_success(&self, key: &str) {
        let mut guard = match self.states.get_mut(key) {
            Some(g) => g,
            None => return,
        };
        let state = guard.get_mut().unwrap();
        *state = CircuitState::Closed(0);
    }

    /// Record failure; increments closed or opens / keeps open.
    pub fn record_failure(&self, key: &str) {
        eviction::evict_one_if_over_capacity(&self.states, self.max_entries);
        let mut guard = self
            .states
            .entry(key.to_string())
            .or_insert_with(|| Mutex::new(CircuitState::Closed(0)));
        let state = guard.get_mut().unwrap();
        let now = Instant::now();
        match state {
            CircuitState::Closed(n) => {
                *n += 1;
                if *n >= self.failure_threshold {
                    *state = CircuitState::Open(now + self.cooldown);
                }
            }
            CircuitState::Open(until) => {
                *until = now + self.cooldown;
            }
            CircuitState::HalfOpen => {
                *state = CircuitState::Open(now + self.cooldown);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[test]
    fn test_circuit_closed_opens_after_threshold() {
        let cb = CircuitBreaker::new(2, Duration::from_secs(60), None);
        assert!(cb.allow_request("a"));
        cb.record_failure("a");
        assert!(cb.allow_request("a"));
        cb.record_failure("a");
        assert!(!cb.allow_request("a"));
    }

    #[test]
    fn test_circuit_success_resets() {
        let cb = CircuitBreaker::new(2, Duration::from_secs(60), None);
        cb.record_failure("a");
        cb.record_success("a");
        assert!(cb.allow_request("a"));
        cb.record_failure("a");
        assert!(cb.allow_request("a"));
    }

    #[test]
    fn test_circuit_half_open_failure_reopens() {
        let cooldown = Duration::from_millis(20);
        let cb = CircuitBreaker::new(2, cooldown, None);
        cb.record_failure("k");
        cb.record_failure("k");
        assert!(!cb.allow_request("k"));
        std::thread::sleep(cooldown + Duration::from_millis(5));
        assert!(cb.allow_request("k"));
        cb.record_failure("k");
        assert!(!cb.allow_request("k"));
    }
}
