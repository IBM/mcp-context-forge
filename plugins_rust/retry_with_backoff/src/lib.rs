// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

use rand::Rng;
use pyo3::prelude::*;

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
    let ceiling = base_ms.saturating_mul(2u64.saturating_pow(attempt)).min(max_ms);
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
    retry_on_status: &[i32],
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
// Python-visible class.  No fields — all state lives in the global STATE map.
// ---------------------------------------------------------------------------
#[pyclass]
pub struct RetryStateManager;

#[pymethods]
impl RetryStateManager {
    #[new]
    fn new() -> Self {
        RetryStateManager
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

    fn compute_delay(
        &self,
        attempt: u32,
        base_ms: u64,
        max_ms: u64,
        jitter: bool,
    ) -> u64 {
        compute_delay_ms(attempt, base_ms, max_ms, jitter)
    }

    fn check_failure(
        &self,
        is_error: bool,
        status_code: Option<i32>,
        retry_on_status: Vec<i32>,
    ) -> bool {
        is_failure_from_signals(is_error, status_code, &retry_on_status)
    }

    // -----------------------------------------------------------------------
    // Main API called by the Python plugin on every post-invoke hook.
    //
    // Returns (should_retry, delay_ms):
    //   (true,  delay)  — failure within budget; caller should schedule retry
    //   (false, 0)      — success OR retries exhausted; caller propagates result
    //
    // The Mutex is held for the entire method to make the check-then-act
    // sequence atomic.
    // -----------------------------------------------------------------------
    #[allow(clippy::too_many_arguments)]
    fn check_and_update(
        &self,
        tool: &str,
        request_id: &str,
        is_error: bool,
        status_code: Option<i32>,
        max_retries: u32,
        base_ms: u64,
        max_ms: u64,
        jitter: bool,
        retry_on_status: Vec<i32>,
    ) -> (bool, u64) {
        let failed = is_failure_from_signals(is_error, status_code, &retry_on_status);

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

            if state.consecutive_failures <= max_retries {
                // attempt index is 0-based; saturating_sub guards against underflow.
                let attempt = state.consecutive_failures.saturating_sub(1);
                let delay = compute_delay_ms(attempt, base_ms, max_ms, jitter);
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
