// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Lock-free per-agent metrics with P95 adaptive timeout suggestions.

use crate::eviction::evict_one_if_over_capacity;
use dashmap::DashMap;
use serde::Serialize;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

/// Maximum number of recent latency samples kept per agent for percentile
/// calculations.
const MAX_RECENT_LATENCIES: usize = 128;

/// Minimum number of samples required before P95 estimates are produced.
const MIN_SAMPLES_FOR_P95: usize = 5;

/// A single invocation measurement destined for [`MetricsCollector::record_batch`].
pub struct MetricRecord {
    pub agent_key: String,
    pub success: bool,
    pub duration: Duration,
}

/// Point-in-time snapshot of an agent's (or the global) counters.
#[derive(Debug, Clone, Default, Serialize)]
pub struct AggregateMetrics {
    pub total_calls: u64,
    pub successful_calls: u64,
    pub failed_calls: u64,
    pub total_latency_us: u64,
    pub min_latency_us: u64,
    pub max_latency_us: u64,
}

/// Per-agent counters backed by atomics plus a small latency ring for
/// percentile estimation.
pub struct AgentMetrics {
    total_calls: AtomicU64,
    successful_calls: AtomicU64,
    failed_calls: AtomicU64,
    total_latency_us: AtomicU64,
    min_latency_us: AtomicU64,
    max_latency_us: AtomicU64,
    recent_latencies: Mutex<VecDeque<u64>>,
}

impl Default for AgentMetrics {
    fn default() -> Self {
        Self::new()
    }
}

impl AgentMetrics {
    /// Create a new, zeroed set of counters.
    pub fn new() -> Self {
        Self {
            total_calls: AtomicU64::new(0),
            successful_calls: AtomicU64::new(0),
            failed_calls: AtomicU64::new(0),
            total_latency_us: AtomicU64::new(0),
            min_latency_us: AtomicU64::new(u64::MAX),
            max_latency_us: AtomicU64::new(0),
            recent_latencies: Mutex::new(VecDeque::with_capacity(MAX_RECENT_LATENCIES)),
        }
    }

    /// Record a successful invocation.
    pub fn record_success(&self, duration: Duration) {
        let us = duration.as_micros() as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.successful_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min(us);
        self.update_max(us);
        self.push_recent_latency(us);
    }

    /// Record a failed invocation.
    pub fn record_failure(&self, duration: Duration) {
        let us = duration.as_micros() as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.failed_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min(us);
        self.update_max(us);
        self.push_recent_latency(us);
    }

    /// Push a latency sample into the bounded ring buffer.
    fn push_recent_latency(&self, us: u64) {
        let mut deque = self.recent_latencies.lock().expect("latency lock poisoned");
        if deque.len() >= MAX_RECENT_LATENCIES {
            deque.pop_front();
        }
        deque.push_back(us);
    }

    /// Return the estimated 95th-percentile latency in microseconds.
    ///
    /// Returns `None` when fewer than [`MIN_SAMPLES_FOR_P95`] samples have
    /// been recorded — the estimate would be unreliable.
    pub fn p95_latency_us(&self) -> Option<u64> {
        let deque = self.recent_latencies.lock().expect("latency lock poisoned");
        if deque.len() < MIN_SAMPLES_FOR_P95 {
            return None;
        }
        let mut sorted: Vec<u64> = deque.iter().copied().collect();
        sorted.sort_unstable();
        let idx = ((sorted.len() as f64) * 0.95).ceil() as usize - 1;
        let idx = idx.min(sorted.len() - 1);
        Some(sorted[idx])
    }

    /// Produce a consistent snapshot of the atomic counters.
    pub fn snapshot(&self) -> AggregateMetrics {
        AggregateMetrics {
            total_calls: self.total_calls.load(Ordering::Relaxed),
            successful_calls: self.successful_calls.load(Ordering::Relaxed),
            failed_calls: self.failed_calls.load(Ordering::Relaxed),
            total_latency_us: self.total_latency_us.load(Ordering::Relaxed),
            min_latency_us: self.min_latency_us.load(Ordering::Relaxed),
            max_latency_us: self.max_latency_us.load(Ordering::Relaxed),
        }
    }

    // -- CAS helpers ----------------------------------------------------------

    fn update_min(&self, us: u64) {
        let mut current = self.min_latency_us.load(Ordering::Relaxed);
        while us < current {
            match self.min_latency_us.compare_exchange_weak(
                current,
                us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => current = actual,
            }
        }
    }

    fn update_max(&self, us: u64) {
        let mut current = self.max_latency_us.load(Ordering::Relaxed);
        while us > current {
            match self.max_latency_us.compare_exchange_weak(
                current,
                us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => current = actual,
            }
        }
    }
}

/// Central metrics store keyed by agent identifier.
///
/// All operations are lock-free on the hot path (atomic increments) with a
/// small [`Mutex`]-guarded ring buffer per agent for P95 estimation.
pub struct MetricsCollector {
    agents: DashMap<String, AgentMetrics>,
    global: AgentMetrics,
    max_entries: Option<usize>,
    /// Count of webhook dispatches that exhausted their retry budget.
    /// Exposed for alerting — ``error!`` logs alone are invisible to any
    /// operator without log aggregation.
    webhook_retry_exhausted: AtomicU64,
    /// Count of webhook dispatches that permanently failed on a 4xx
    /// response (no retry attempted — wrong config or bad payload).
    webhook_permanent_failure: AtomicU64,
    /// Count of dispatch cycles aborted before any webhook was attempted
    /// because ``push/list`` was unreachable / non-200 / undeserializable.
    /// A non-zero rate here indicates the sidecar↔backend trust chain is
    /// broken, not that individual webhooks are failing.
    webhook_list_aborted: AtomicU64,
    /// Count of push-config rows whose ``auth_token`` could not be
    /// decrypted during a dispatch listing.  A misconfigured
    /// ``AUTH_ENCRYPTION_SECRET`` will make this rate proportional to
    /// total dispatches.
    push_config_decrypt_failed: AtomicU64,
}

impl MetricsCollector {
    /// Create a new collector.  `max_entries` caps the number of distinct
    /// per-agent buckets; `None` means unlimited.
    pub fn new(max_entries: Option<usize>) -> Self {
        Self {
            agents: DashMap::new(),
            global: AgentMetrics::new(),
            max_entries,
            webhook_retry_exhausted: AtomicU64::new(0),
            webhook_permanent_failure: AtomicU64::new(0),
            webhook_list_aborted: AtomicU64::new(0),
            push_config_decrypt_failed: AtomicU64::new(0),
        }
    }

    /// Record that a webhook-dispatch task gave up after exhausting its
    /// retry budget (typically 3 attempts with exponential backoff).
    pub fn record_webhook_retry_exhausted(&self) {
        self.webhook_retry_exhausted.fetch_add(1, Ordering::Relaxed);
    }

    /// Current count of exhausted-retry webhook dispatches.
    pub fn webhook_retry_exhausted_count(&self) -> u64 {
        self.webhook_retry_exhausted.load(Ordering::Relaxed)
    }

    /// Record that a webhook dispatch permanently failed on a 4xx status
    /// (not retried because the config or payload is wrong).
    pub fn record_webhook_permanent_failure(&self) {
        self.webhook_permanent_failure
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Current count of permanent-failure (4xx) webhook dispatches.
    pub fn webhook_permanent_failure_count(&self) -> u64 {
        self.webhook_permanent_failure.load(Ordering::Relaxed)
    }

    /// Record that a dispatch cycle aborted before attempting any webhook
    /// because ``push/list`` could not be fetched or parsed.
    pub fn record_webhook_list_aborted(&self) {
        self.webhook_list_aborted.fetch_add(1, Ordering::Relaxed);
    }

    /// Current count of aborted (pre-attempt) dispatch cycles.
    pub fn webhook_list_aborted_count(&self) -> u64 {
        self.webhook_list_aborted.load(Ordering::Relaxed)
    }

    /// Record a per-config ``auth_token`` decryption failure encountered
    /// during a dispatch listing.
    pub fn record_push_config_decrypt_failed(&self) {
        self.push_config_decrypt_failed
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Current count of push-config decryption failures.
    pub fn push_config_decrypt_failed_count(&self) -> u64 {
        self.push_config_decrypt_failed.load(Ordering::Relaxed)
    }

    /// Record a single invocation for both the per-agent bucket and the global
    /// aggregate.
    pub fn record_invocation(&self, agent_key: &str, success: bool, duration: Duration) {
        // Per-agent ----------------------------------------------------------
        if !self.agents.contains_key(agent_key) {
            evict_one_if_over_capacity(&self.agents, self.max_entries);
        }
        let entry = self.agents.entry(agent_key.to_owned()).or_default();
        if success {
            entry.record_success(duration);
        } else {
            entry.record_failure(duration);
        }

        // Global -------------------------------------------------------------
        if success {
            self.global.record_success(duration);
        } else {
            self.global.record_failure(duration);
        }
    }

    /// Convenience wrapper that records every item in `records`.
    pub fn record_batch(&self, records: &[MetricRecord]) {
        for r in records {
            self.record_invocation(&r.agent_key, r.success, r.duration);
        }
    }

    /// Suggest a request timeout for the given agent based on observed P95
    /// latency.
    ///
    /// The suggestion is `P95 * 1.5`, clamped to \[1 s, 300 s\].  Returns
    /// `None` when fewer than [`MIN_SAMPLES_FOR_P95`] samples are available.
    pub fn suggest_timeout_for_agent(&self, agent_key: &str) -> Option<Duration> {
        let entry = self.agents.get(agent_key)?;
        let p95_us = entry.p95_latency_us()?;
        let suggested_us = (p95_us as f64 * 1.5) as u64;
        let floor = Duration::from_secs(1);
        let ceiling = Duration::from_secs(300);
        let suggested = Duration::from_micros(suggested_us);
        Some(suggested.clamp(floor, ceiling))
    }

    /// Return a point-in-time snapshot for a single agent.
    pub fn get_aggregate(&self, agent_key: &str) -> Option<AggregateMetrics> {
        self.agents.get(agent_key).map(|entry| entry.snapshot())
    }

    /// Return a point-in-time snapshot of the global (all-agent) counters.
    pub fn snapshot(&self) -> AggregateMetrics {
        self.global.snapshot()
    }

    /// Reset all metrics to their initial state.
    pub fn reset(&self) {
        self.agents.clear();
        self.global.total_calls.store(0, Ordering::Relaxed);
        self.global.successful_calls.store(0, Ordering::Relaxed);
        self.global.failed_calls.store(0, Ordering::Relaxed);
        self.global.total_latency_us.store(0, Ordering::Relaxed);
        self.global
            .min_latency_us
            .store(u64::MAX, Ordering::Relaxed);
        self.global.max_latency_us.store(0, Ordering::Relaxed);
        self.global
            .recent_latencies
            .lock()
            .expect("latency lock poisoned")
            .clear();
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(millis: u64) -> Duration {
        Duration::from_millis(millis)
    }

    // -- AgentMetrics unit tests ---------------------------------------------

    #[test]
    fn record_success_increments_counters() {
        let m = AgentMetrics::new();
        m.record_success(ms(100));
        m.record_success(ms(200));

        let snap = m.snapshot();
        assert_eq!(snap.total_calls, 2);
        assert_eq!(snap.successful_calls, 2);
        assert_eq!(snap.failed_calls, 0);
        assert_eq!(snap.total_latency_us, 300_000);
        assert_eq!(snap.min_latency_us, 100_000);
        assert_eq!(snap.max_latency_us, 200_000);
    }

    #[test]
    fn record_failure_increments_failed_counter() {
        let m = AgentMetrics::new();
        m.record_failure(ms(50));

        let snap = m.snapshot();
        assert_eq!(snap.total_calls, 1);
        assert_eq!(snap.successful_calls, 0);
        assert_eq!(snap.failed_calls, 1);
        assert_eq!(snap.min_latency_us, 50_000);
    }

    #[test]
    fn p95_returns_none_with_fewer_than_five_samples() {
        let m = AgentMetrics::new();
        for i in 0..4 {
            m.record_success(ms(i + 1));
        }
        assert!(m.p95_latency_us().is_none());
    }

    #[test]
    fn p95_returns_correct_percentile() {
        let m = AgentMetrics::new();
        // Record 20 samples: 1ms, 2ms, ..., 20ms
        for i in 1..=20 {
            m.record_success(ms(i));
        }
        let p95 = m.p95_latency_us().expect("should have enough samples");
        // ceil(20 * 0.95) = 19 -> index 18 -> value 19_000 us
        assert_eq!(p95, 19_000);
    }

    // -- MetricsCollector unit tests -----------------------------------------

    #[test]
    fn suggest_timeout_returns_none_when_insufficient_data() {
        let c = MetricsCollector::new(None);
        c.record_invocation("agent-a", true, ms(100));
        assert!(c.suggest_timeout_for_agent("agent-a").is_none());
    }

    #[test]
    fn suggest_timeout_returns_clamped_value() {
        let c = MetricsCollector::new(None);
        // 10 samples of 2 seconds each
        for _ in 0..10 {
            c.record_invocation("agent-b", true, Duration::from_secs(2));
        }
        let timeout = c.suggest_timeout_for_agent("agent-b").expect("enough data");
        // P95 = 2s -> suggestion = 3s, clamped to [1s, 300s] -> 3s
        assert_eq!(timeout, Duration::from_secs(3));

        // Verify floor clamp: very fast agent
        let c2 = MetricsCollector::new(None);
        for _ in 0..10 {
            c2.record_invocation("fast", true, Duration::from_micros(100));
        }
        let timeout = c2.suggest_timeout_for_agent("fast").expect("enough data");
        assert_eq!(timeout, Duration::from_secs(1));

        // Verify ceiling clamp: very slow agent
        let c3 = MetricsCollector::new(None);
        for _ in 0..10 {
            c3.record_invocation("slow", true, Duration::from_secs(250));
        }
        let timeout = c3.suggest_timeout_for_agent("slow").expect("enough data");
        assert_eq!(timeout, Duration::from_secs(300));
    }

    #[test]
    fn batch_recording_updates_per_agent_and_global() {
        let c = MetricsCollector::new(None);
        let records = vec![
            MetricRecord {
                agent_key: "a".into(),
                success: true,
                duration: ms(10),
            },
            MetricRecord {
                agent_key: "b".into(),
                success: false,
                duration: ms(20),
            },
            MetricRecord {
                agent_key: "a".into(),
                success: true,
                duration: ms(30),
            },
        ];

        c.record_batch(&records);

        // Per-agent checks
        let snap_a = c.get_aggregate("a").expect("agent a exists");
        assert_eq!(snap_a.total_calls, 2);
        assert_eq!(snap_a.successful_calls, 2);
        assert_eq!(snap_a.failed_calls, 0);

        let snap_b = c.get_aggregate("b").expect("agent b exists");
        assert_eq!(snap_b.total_calls, 1);
        assert_eq!(snap_b.successful_calls, 0);
        assert_eq!(snap_b.failed_calls, 1);

        // Global check
        let global = c.snapshot();
        assert_eq!(global.total_calls, 3);
        assert_eq!(global.successful_calls, 2);
        assert_eq!(global.failed_calls, 1);
        assert_eq!(global.total_latency_us, 60_000);
    }

    #[test]
    fn reset_clears_everything() {
        let c = MetricsCollector::new(None);
        for _ in 0..10 {
            c.record_invocation("x", true, ms(5));
        }
        assert_eq!(c.snapshot().total_calls, 10);
        assert!(c.get_aggregate("x").is_some());

        c.reset();

        assert_eq!(c.snapshot().total_calls, 0);
        assert!(c.get_aggregate("x").is_none());
        // min should be back to u64::MAX (sentinel)
        assert_eq!(c.snapshot().min_latency_us, u64::MAX);
    }

    #[test]
    fn eviction_caps_agent_count() {
        let c = MetricsCollector::new(Some(3));
        for i in 0..5 {
            c.record_invocation(&format!("agent-{i}"), true, ms(1));
        }
        assert!(c.agents.len() <= 3);
    }
}
