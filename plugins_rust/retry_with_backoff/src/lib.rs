// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;

use log::{debug, warn};
use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::*;
use rand::Rng;

// ---------------------------------------------------------------------------
// State struct — mirrors Python's _ToolRetryState dataclass.
// ---------------------------------------------------------------------------
pub struct ToolRetryState {
    pub consecutive_failures: u32,
    pub last_failure_at: f64,
}

impl ToolRetryState {
    fn new() -> Self {
        ToolRetryState {
            consecutive_failures: 0,
            last_failure_at: 0.0,
        }
    }
}

// ---------------------------------------------------------------------------
// Global state — mirrors Python's module-level _STATE dict.
// Mutex protects concurrent access; OnceLock ensures single initialisation.
//
// NOTE: This map is process-global and shared across all RetryStateManager
// instances.  The gateway creates a single plugin instance so this is fine
// in practice, but if multiple instances with different configs are ever
// constructed they will share state entries.
// ---------------------------------------------------------------------------
static STATE: OnceLock<Mutex<HashMap<String, ToolRetryState>>> = OnceLock::new();

/// Monotonic reference point — equivalent of Python's `time.monotonic()` epoch.
/// Using `Instant` instead of `SystemTime` ensures TTL eviction is immune to
/// wall-clock jumps from NTP sync or manual adjustment.
static MONO_EPOCH: OnceLock<Instant> = OnceLock::new();

/// Entries older than this (in seconds) are considered orphaned — e.g. the
/// retry sleep was cancelled by a client disconnect — and are evicted.
const STATE_TTL_SECS: f64 = 300.0;

/// Return a monotonic timestamp in seconds, analogous to Python's `time.monotonic()`.
fn monotonic_secs() -> f64 {
    let epoch = MONO_EPOCH.get_or_init(Instant::now);
    epoch.elapsed().as_secs_f64()
}

fn state_map() -> &'static Mutex<HashMap<String, ToolRetryState>> {
    STATE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Remove entries whose `last_failure_at` is older than `STATE_TTL_SECS`.
/// Called under an already-held lock by `check_and_update`.
fn evict_stale(map: &mut HashMap<String, ToolRetryState>) {
    let cutoff = monotonic_secs() - STATE_TTL_SECS;
    map.retain(|_, v| v.last_failure_at <= 0.0 || v.last_failure_at >= cutoff);
}

fn make_key(tool: &str, request_id: &str) -> String {
    format!("{tool}:{request_id}")
}

// ---------------------------------------------------------------------------
// Pure functions — no PyO3 types.  Called from RetryStateManager methods.
// ---------------------------------------------------------------------------

// Exponential backoff with optional jitter, capped at max_ms.
fn compute_delay_ms(attempt: u32, base_ms: u64, max_ms: u64, jitter: bool) -> u64 {
    let ceiling = base_ms
        .saturating_mul(2u64.saturating_pow(attempt))
        .min(max_ms);
    if jitter {
        rand::thread_rng().gen_range(0..=ceiling)
    } else {
        ceiling
    }
}

// Checks the two pre-extracted failure signals: outer isError flag and status code.
// Text-content parsing (signal 3) is handled entirely in Python.
//
// When isError is true AND a status code is present (e.g. the gateway extracted
// it from an httpx.HTTPStatusError), the code is checked against retry_on_status
// so that non-transient HTTP errors (400, 401, 404 …) are not wastefully retried.
// Generic exceptions with no status code (connection errors, timeouts) are always
// considered retryable.
fn is_failure_from_signals(
    is_error: bool,
    status_code: Option<i32>,
    retry_on_status: &HashSet<i32>,
) -> bool {
    if is_error {
        return match status_code {
            Some(sc) => retry_on_status.contains(&sc),
            None => true,
        };
    }
    if let Some(sc) = status_code {
        return retry_on_status.contains(&sc);
    }
    false
}

// ---------------------------------------------------------------------------
// Python-visible class.
// Config is stored in the struct — set once at construction, never
// re-allocated on the hot path.  retry_on_status is kept as a HashSet for
// O(1) membership tests instead of the O(n) Vec scan it replaced.
// ---------------------------------------------------------------------------
#[gen_stub_pyclass]
#[pyclass]
pub struct RetryStateManager {
    max_retries: u32,
    base_ms: u64,
    max_ms: u64,
    jitter: bool,
    retry_on_status: HashSet<i32>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RetryStateManager {
    #[new]
    fn new(
        max_retries: u32,
        base_ms: u64,
        max_ms: u64,
        jitter: bool,
        retry_on_status: Vec<i32>,
    ) -> Self {
        debug!(
            "RetryStateManager created: max_retries={max_retries} base_ms={base_ms} \
             max_ms={max_ms} jitter={jitter} retry_on_status={retry_on_status:?}"
        );
        RetryStateManager {
            max_retries,
            base_ms,
            max_ms,
            jitter,
            // Vec → HashSet: one-time allocation at construction; O(1) lookups thereafter.
            retry_on_status: retry_on_status.into_iter().collect(),
        }
    }

    fn ping(&self) -> &str {
        "retry_with_backoff_rust is alive"
    }

    // Returns consecutive_failures for (tool, request_id), or 0 if absent.
    fn get_failures(&self, tool: &str, request_id: &str) -> u32 {
        let map = state_map().lock().unwrap();
        let key = make_key(tool, request_id);
        map.get(&key).map(|s| s.consecutive_failures).unwrap_or(0)
    }

    // Increments consecutive_failures and records the current timestamp.
    fn record_failure(&self, tool: &str, request_id: &str) -> u32 {
        let mut map = state_map().lock().unwrap();
        let key = make_key(tool, request_id);
        let state = map.entry(key).or_insert_with(ToolRetryState::new);
        state.consecutive_failures += 1;
        state.last_failure_at = monotonic_secs();
        debug!(
            "record_failure: tool={tool} request_id={request_id} consecutive_failures={}",
            state.consecutive_failures
        );
        state.consecutive_failures
    }

    // Resets consecutive_failures to 0 without removing the entry.
    fn record_success(&self, tool: &str, request_id: &str) {
        let mut map = state_map().lock().unwrap();
        let key = make_key(tool, request_id);
        if let Some(state) = map.get_mut(&key) {
            state.consecutive_failures = 0;
            debug!("record_success: tool={tool} request_id={request_id} — failure counter reset");
        }
    }

    // Removes the state entry for a completed invocation (success or exhausted).
    fn delete_state(&self, tool: &str, request_id: &str) {
        let mut map = state_map().lock().unwrap();
        let key = make_key(tool, request_id);
        let _ = map.remove(&key);
    }

    // Number of active (tool, request_id) entries — useful for tests/debugging.
    fn state_count(&self) -> usize {
        state_map().lock().unwrap().len()
    }

    fn compute_delay(&self, attempt: u32) -> u64 {
        compute_delay_ms(attempt, self.base_ms, self.max_ms, self.jitter)
    }

    fn check_failure(&self, is_error: bool, status_code: Option<i32>) -> bool {
        is_failure_from_signals(is_error, status_code, &self.retry_on_status)
    }

    // -----------------------------------------------------------------------
    // Main API called by the Python plugin on every post-invoke hook.
    //
    // Config (max_retries, base_ms, max_ms, jitter, retry_on_status) lives in
    // self — no per-call allocations or list conversions cross the FFI boundary.
    // Only the four truly dynamic arguments are passed.
    //
    // Returns (should_retry, delay_ms):
    //   (true,  delay)  — failure within budget; caller should schedule retry
    //   (false, 0)      — success OR retries exhausted; caller propagates result
    //
    // The Mutex is held for the entire method to make the check-then-act
    // sequence atomic.
    // -----------------------------------------------------------------------
    fn check_and_update(
        &self,
        tool: &str,
        request_id: &str,
        is_error: bool,
        status_code: Option<i32>,
    ) -> (bool, u64) {
        let failed = is_failure_from_signals(is_error, status_code, &self.retry_on_status);

        // Acquire the lock once for the entire check-then-act sequence.
        let mut map = state_map().lock().unwrap();
        evict_stale(&mut map);
        let key = make_key(tool, request_id);

        if failed {
            let state = map.entry(key.clone()).or_insert_with(ToolRetryState::new);
            state.consecutive_failures += 1;
            state.last_failure_at = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs_f64();

            if state.consecutive_failures <= self.max_retries {
                // attempt index is 0-based; saturating_sub guards against underflow.
                let attempt = state.consecutive_failures.saturating_sub(1);
                let delay = compute_delay_ms(attempt, self.base_ms, self.max_ms, self.jitter);
                debug!(
                    "check_and_update: tool={tool} request_id={request_id} \
                     failure={}/{} — retry in {delay}ms",
                    state.consecutive_failures, self.max_retries
                );
                (true, delay)
            } else {
                warn!(
                    "check_and_update: tool={tool} request_id={request_id} \
                     retry budget exhausted ({} failures) — propagating error",
                    state.consecutive_failures
                );
                map.remove(&key);
                (false, 0)
            }
        } else {
            debug!(
                "check_and_update: tool={tool} request_id={request_id} — success, state cleared"
            );
            let _ = map.remove(&key);
            (false, 0)
        }
    }
}

// ---------------------------------------------------------------------------
// Module entry point.
// ---------------------------------------------------------------------------
#[pymodule]
fn retry_with_backoff_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Bridge Rust log records to Python's logging module.
    // After this call, log::debug!/warn!/etc. emit to the logger named
    // "retry_with_backoff_rust" in Python, respecting the Python log level.
    pyo3_log::init();
    m.add_class::<RetryStateManager>()?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);

// ---------------------------------------------------------------------------
// Unit tests — pure Rust, no Python interpreter required.
// Run with: cargo test  (or: make test)
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn status_set(codes: &[i32]) -> HashSet<i32> {
        codes.iter().cloned().collect()
    }

    fn manager_with(base_ms: u64, max_ms: u64) -> RetryStateManager {
        RetryStateManager::new(2, base_ms, max_ms, false, vec![500, 503])
    }

    // ── compute_delay_ms ────────────────────────────────────────────────────

    #[test]
    fn delay_attempt_zero_returns_base() {
        assert_eq!(compute_delay_ms(0, 100, 10_000, false), 100);
    }

    #[test]
    fn delay_doubles_each_attempt() {
        assert_eq!(compute_delay_ms(1, 100, 10_000, false), 200);
        assert_eq!(compute_delay_ms(2, 100, 10_000, false), 400);
        assert_eq!(compute_delay_ms(3, 100, 10_000, false), 800);
    }

    #[test]
    fn delay_is_capped_at_max_ms() {
        assert_eq!(compute_delay_ms(10, 100, 500, false), 500);
    }

    #[test]
    fn delay_no_overflow_on_extreme_attempt() {
        // saturating_pow / saturating_mul must not panic — result must equal cap.
        let d = compute_delay_ms(63, 100, 5_000, false);
        assert_eq!(d, 5_000, "expected cap, got {d}");
    }

    // ── is_failure_from_signals ─────────────────────────────────────────────

    #[test]
    fn failure_when_is_error_true() {
        assert!(is_failure_from_signals(true, None, &status_set(&[])));
    }

    #[test]
    fn no_failure_when_is_error_false_and_no_status() {
        assert!(!is_failure_from_signals(false, None, &status_set(&[])));
    }

    #[test]
    fn failure_when_status_code_in_retry_set() {
        assert!(is_failure_from_signals(
            false,
            Some(500),
            &status_set(&[500, 503])
        ));
        assert!(is_failure_from_signals(
            false,
            Some(503),
            &status_set(&[500, 503])
        ));
    }

    #[test]
    fn no_failure_when_status_code_not_in_retry_set() {
        assert!(!is_failure_from_signals(
            false,
            Some(200),
            &status_set(&[500, 503])
        ));
        assert!(!is_failure_from_signals(
            false,
            Some(404),
            &status_set(&[500, 503])
        ));
    }

    #[test]
    fn is_error_with_non_retryable_status_does_not_retry() {
        // isError=true + status_code NOT in retry set → not retryable.
        assert!(!is_failure_from_signals(true, Some(200), &status_set(&[])));
        assert!(!is_failure_from_signals(
            true,
            Some(400),
            &status_set(&[500, 503])
        ));
        assert!(!is_failure_from_signals(
            true,
            Some(404),
            &status_set(&[500, 503])
        ));
    }

    #[test]
    fn is_error_with_retryable_status_retries() {
        assert!(is_failure_from_signals(
            true,
            Some(500),
            &status_set(&[500, 503])
        ));
        assert!(is_failure_from_signals(
            true,
            Some(503),
            &status_set(&[500, 503])
        ));
    }

    #[test]
    fn is_error_without_status_always_retries() {
        // isError=true with no status code → generic exception → always retry.
        assert!(is_failure_from_signals(true, None, &status_set(&[])));
        assert!(is_failure_from_signals(true, None, &status_set(&[500])));
    }

    // ── make_key ────────────────────────────────────────────────────────────

    #[test]
    fn key_format_is_tool_colon_request() {
        assert_eq!(make_key("my_tool", "req-123"), "my_tool:req-123");
    }

    #[test]
    fn key_with_empty_parts() {
        assert_eq!(make_key("", ""), ":");
    }

    // ── RetryStateManager: state helpers ────────────────────────────────────

    #[test]
    fn get_failures_returns_zero_for_unknown_key() {
        let m = manager_with(100, 10_000);
        assert_eq!(m.get_failures("unknown_t", "unknown_r"), 0);
    }

    #[test]
    fn record_failure_increments_and_get_failures_reads_back() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("state_rf_t", "state_rf_r");
        m.delete_state(tool, req); // clean slate
        assert_eq!(m.record_failure(tool, req), 1);
        assert_eq!(m.record_failure(tool, req), 2);
        assert_eq!(m.get_failures(tool, req), 2);
        m.delete_state(tool, req);
    }

    #[test]
    fn record_success_resets_failure_counter_to_zero() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("state_rs_t", "state_rs_r");
        m.delete_state(tool, req);
        m.record_failure(tool, req);
        m.record_failure(tool, req);
        m.record_success(tool, req);
        assert_eq!(m.get_failures(tool, req), 0);
        m.delete_state(tool, req);
    }

    #[test]
    fn delete_state_removes_entry() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("state_del_t", "state_del_r");
        m.record_failure(tool, req);
        m.delete_state(tool, req);
        assert_eq!(m.get_failures(tool, req), 0);
    }

    // ── RetryStateManager: check_and_update ─────────────────────────────────

    #[test]
    fn check_and_update_success_returns_no_retry() {
        let m = manager_with(100, 10_000);
        let (retry, delay) = m.check_and_update("cau_ok_t", "cau_ok_r", false, None);
        assert!(!retry);
        assert_eq!(delay, 0);
    }

    #[test]
    fn check_and_update_first_failure_triggers_retry_with_base_delay() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("cau_f1_t", "cau_f1_r");
        m.delete_state(tool, req);
        let (retry, delay) = m.check_and_update(tool, req, true, None);
        assert!(retry, "expected retry on first failure");
        assert_eq!(delay, 100, "first failure should use base_ms (attempt 0)");
        m.delete_state(tool, req);
    }

    #[test]
    fn check_and_update_status_code_match_triggers_retry() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("cau_sc_t", "cau_sc_r");
        m.delete_state(tool, req);
        let (retry, _) = m.check_and_update(tool, req, false, Some(500));
        assert!(retry, "status 500 should trigger retry");
        m.delete_state(tool, req);
    }

    #[test]
    fn check_and_update_delay_doubles_with_successive_failures() {
        let m = RetryStateManager::new(2, 100, 10_000, false, vec![]);
        let (tool, req) = ("cau_exp_t", "cau_exp_r");
        m.delete_state(tool, req);
        let (_, d1) = m.check_and_update(tool, req, true, None); // attempt 0 → 100
        let (_, d2) = m.check_and_update(tool, req, true, None); // attempt 1 → 200
        assert_eq!(d1, 100);
        assert_eq!(d2, 200);
        m.delete_state(tool, req);
    }

    #[test]
    fn check_and_update_exhausts_budget_then_stops() {
        let m = manager_with(100, 10_000); // max_retries = 2
        let (tool, req) = ("cau_ex_t", "cau_ex_r");
        m.delete_state(tool, req);
        // First 2 failures are within budget.
        for i in 1..=2 {
            let (retry, _) = m.check_and_update(tool, req, true, None);
            assert!(retry, "failure {i} should still be within retry budget");
        }
        // 3rd failure exceeds max_retries — entry is removed, no retry.
        let (retry, delay) = m.check_and_update(tool, req, true, None);
        assert!(!retry, "retry budget exhausted — should not retry");
        assert_eq!(delay, 0);
    }

    #[test]
    fn check_and_update_success_after_failures_clears_state() {
        let m = manager_with(100, 10_000);
        let (tool, req) = ("cau_clr_t", "cau_clr_r");
        m.delete_state(tool, req);
        m.check_and_update(tool, req, true, None); // record a failure
        let (retry, delay) = m.check_and_update(tool, req, false, None); // success
        assert!(!retry);
        assert_eq!(delay, 0);
        // Entry should be gone — subsequent get_failures returns 0.
        assert_eq!(m.get_failures(tool, req), 0);
    }
}
