// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, OnceLock};

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
// ---------------------------------------------------------------------------
static STATE: OnceLock<Mutex<HashMap<String, ToolRetryState>>> = OnceLock::new();

fn state_map() -> &'static Mutex<HashMap<String, ToolRetryState>> {
    STATE.get_or_init(|| Mutex::new(HashMap::new()))
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
fn is_failure_from_signals(
    is_error: bool,
    status_code: Option<i32>,
    retry_on_status: &HashSet<i32>,
) -> bool {
    if is_error {
        return true;
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
        state.last_failure_at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        state.consecutive_failures
    }

    // Resets consecutive_failures to 0 without removing the entry.
    fn record_success(&self, tool: &str, request_id: &str) {
        let mut map = state_map().lock().unwrap();
        let key = make_key(tool, request_id);
        if let Some(state) = map.get_mut(&key) {
            state.consecutive_failures = 0;
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
                (true, delay)
            } else {
                map.remove(&key);
                (false, 0)
            }
        } else {
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
    m.add_class::<RetryStateManager>()?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);
