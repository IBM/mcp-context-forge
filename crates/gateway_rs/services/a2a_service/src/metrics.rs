//! In-memory metrics for A2A invocations.
//!
//! Lock-free per-agent counters (via [`DashMap`] and atomics) plus a global aggregate. The invoker
//! records each request by agent key (URL or id); Python can read aggregates via [`get_aggregate`](MetricsCollector::get_aggregate)
//! or the PyO3 `get_agent_metrics`.
//!
//! Per-agent recent latencies are kept for adaptive timeout (P95-based suggestion when no per-request timeout is set).

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use dashmap::DashMap;

use crate::eviction;

/// Maximum number of recent latencies to keep per agent for P95-based adaptive timeout.
const RECENT_LATENCIES_CAP: usize = 128;

/// Single metric record for batch recording (agent key, success, duration).
#[derive(Debug, Clone)]
pub struct MetricRecord {
    pub agent_key: String,
    pub success: bool,
    pub duration: Duration,
}

/// Snapshot of aggregated A2A invocation metrics for one agent or globally.
#[derive(Debug, Clone, Default)]
pub struct AggregateMetrics {
    /// Total number of invocations.
    pub total_calls: u64,
    /// Invocations that returned HTTP 200.
    pub successful_calls: u64,
    /// Invocations that failed or returned non-2xx.
    pub failed_calls: u64,
    /// Sum of response latencies in microseconds.
    pub total_latency_us: u64,
    /// Minimum observed latency in microseconds.
    pub min_latency_us: u64,
    /// Maximum observed latency in microseconds.
    pub max_latency_us: u64,
}

/// Per-agent metrics (atomic counters + recent latencies for P95). Used both for global aggregate and per-agent entries.
#[derive(Debug)]
pub struct AgentMetrics {
    pub total_calls: AtomicU64,
    pub successful_calls: AtomicU64,
    pub failed_calls: AtomicU64,
    pub total_latency_us: AtomicU64,
    pub min_latency_us: AtomicU64,
    pub max_latency_us: AtomicU64,
    /// Recent latencies in microseconds for P95-based adaptive timeout.
    recent_latencies_us: Mutex<VecDeque<u64>>,
}

impl Default for AgentMetrics {
    fn default() -> Self {
        Self {
            total_calls: AtomicU64::new(0),
            successful_calls: AtomicU64::new(0),
            failed_calls: AtomicU64::new(0),
            total_latency_us: AtomicU64::new(0),
            min_latency_us: AtomicU64::new(u64::MAX),
            max_latency_us: AtomicU64::new(0),
            recent_latencies_us: Mutex::new(VecDeque::new()),
        }
    }
}

impl AgentMetrics {
    fn record_success(&self, latency: Duration) {
        let us = latency.as_micros().min(u64::MAX as u128) as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.successful_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min_max(us);
        self.push_recent_latency(us);
    }

    fn record_failure(&self, latency: Duration) {
        let us = latency.as_micros().min(u64::MAX as u128) as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.failed_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min_max(us);
        self.push_recent_latency(us);
    }

    fn push_recent_latency(&self, us: u64) {
        if let Ok(mut q) = self.recent_latencies_us.lock() {
            q.push_back(us);
            while q.len() > RECENT_LATENCIES_CAP {
                q.pop_front();
            }
        }
    }

    /// P95 of recent latencies in microseconds, or None if fewer than 5 samples.
    fn p95_latency_us(&self) -> Option<u64> {
        let q = self.recent_latencies_us.lock().ok()?;
        let len = q.len();
        if len < 5 {
            return None;
        }
        let mut sorted: Vec<u64> = q.iter().copied().collect();
        sorted.sort_unstable();
        let idx = (len * 95 / 100).min(len.saturating_sub(1));
        Some(sorted[idx])
    }

    fn update_min_max(&self, us: u64) {
        let mut current_min = self.min_latency_us.load(Ordering::Relaxed);
        while us < current_min {
            match self.min_latency_us.compare_exchange_weak(
                current_min,
                us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => current_min = actual,
            }
        }
        let mut current_max = self.max_latency_us.load(Ordering::Relaxed);
        while us > current_max {
            match self.max_latency_us.compare_exchange_weak(
                current_max,
                us,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => current_max = actual,
            }
        }
    }

    /// Take a point-in-time snapshot of this agent's metrics.
    pub fn snapshot(&self) -> AggregateMetrics {
        let min = self.min_latency_us.load(Ordering::Relaxed);
        AggregateMetrics {
            total_calls: self.total_calls.load(Ordering::Relaxed),
            successful_calls: self.successful_calls.load(Ordering::Relaxed),
            failed_calls: self.failed_calls.load(Ordering::Relaxed),
            total_latency_us: self.total_latency_us.load(Ordering::Relaxed),
            min_latency_us: if min == u64::MAX { 0 } else { min },
            max_latency_us: self.max_latency_us.load(Ordering::Relaxed),
        }
    }
}

/// In-memory metrics collector for A2A invocations.
/// Records counts and latency per agent (DashMap) and globally (aggregate).
#[derive(Debug)]
pub struct MetricsCollector {
    /// Per-agent metrics keyed by agent id or URL.
    invocations: DashMap<String, AgentMetrics>,
    /// Global aggregate (all agents combined).
    global: AgentMetrics,
    /// When set, evict one entry when at capacity to bound memory.
    max_entries: Option<usize>,
}

impl Default for MetricsCollector {
    fn default() -> Self {
        Self::new()
    }
}

impl MetricsCollector {
    /// Create an unbounded metrics collector (for tests).
    pub fn new() -> Self {
        Self::with_capacity(None)
    }

    /// Create a metrics collector with optional max per-agent entries. When `Some(n)`, evicts one entry when at capacity.
    pub fn with_capacity(max_entries: Option<usize>) -> Self {
        Self {
            invocations: DashMap::new(),
            global: AgentMetrics::default(),
            max_entries,
        }
    }

    /// Record a single invocation for an agent. Also updates global aggregate.
    pub fn record_invocation(&self, agent: &str, success: bool, duration: Duration) {
        eviction::evict_one_if_over_capacity(&self.invocations, self.max_entries);
        let metrics = self
            .invocations
            .entry(agent.to_string())
            .or_insert_with(AgentMetrics::default);
        if success {
            metrics.record_success(duration);
        } else {
            metrics.record_failure(duration);
        }
        if success {
            self.global.record_success(duration);
        } else {
            self.global.record_failure(duration);
        }
    }

    /// Record a batch of metric records. Updates both per-agent and global metrics.
    pub fn record_batch(&self, results: &[MetricRecord]) {
        for r in results {
            self.record_invocation(&r.agent_key, r.success, r.duration);
        }
    }

    /// Get aggregated metrics for a specific agent, if any.
    pub fn get_aggregate(&self, agent: &str) -> Option<AggregateMetrics> {
        self.invocations
            .get(agent)
            .map(|m| m.snapshot())
    }

    /// Suggested timeout for an agent when no per-request timeout is set: P95 of recent latencies
    /// multiplied by 1.5, clamped to [min_duration, max_duration]. Returns default_duration if
    /// there are too few samples.
    pub fn suggest_timeout_for_agent(
        &self,
        agent: &str,
        default_duration: Duration,
        min_duration: Duration,
        max_duration: Duration,
    ) -> Duration {
        let p95_us = self
            .invocations
            .get(agent)
            .and_then(|m| m.p95_latency_us());
        match p95_us {
            None => default_duration,
            Some(us) => {
                let p95 = Duration::from_micros(us);
                let suggested = p95 + p95 / 2; // 1.5 * P95
                suggested.clamp(min_duration, max_duration)
            }
        }
    }

    /// Take a point-in-time snapshot of the global metrics.
    pub fn snapshot(&self) -> AggregateMetrics {
        self.global.snapshot()
    }

    /// Reset all metrics (per-agent and global).
    pub fn reset(&self) {
        self.invocations.clear();
        self.global.total_calls.store(0, Ordering::Relaxed);
        self.global.successful_calls.store(0, Ordering::Relaxed);
        self.global.failed_calls.store(0, Ordering::Relaxed);
        self.global.total_latency_us.store(0, Ordering::Relaxed);
        self.global.min_latency_us.store(u64::MAX, Ordering::Relaxed);
        self.global.max_latency_us.store(0, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_agent_metrics_default() {
        let m = AgentMetrics::default();
        assert_eq!(m.total_calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn test_aggregate_metrics_default() {
        let a = AggregateMetrics::default();
        assert_eq!(a.total_calls, 0);
        assert_eq!(a.successful_calls, 0);
        assert_eq!(a.failed_calls, 0);
        assert_eq!(a.total_latency_us, 0);
        assert_eq!(a.min_latency_us, 0);
        assert_eq!(a.max_latency_us, 0);
    }

    #[test]
    fn test_record_invocation_per_agent() {
        let c = MetricsCollector::new();
        c.record_invocation("agent1", true, Duration::from_millis(100));
        c.record_invocation("agent1", false, Duration::from_millis(50));
        c.record_invocation("agent2", true, Duration::from_millis(200));

        let a1 = c.get_aggregate("agent1").unwrap();
        assert_eq!(a1.total_calls, 2);
        assert_eq!(a1.successful_calls, 1);
        assert_eq!(a1.failed_calls, 1);
        assert_eq!(a1.min_latency_us, 50_000);
        assert_eq!(a1.max_latency_us, 100_000);

        let a2 = c.get_aggregate("agent2").unwrap();
        assert_eq!(a2.total_calls, 1);
        assert_eq!(a2.successful_calls, 1);

        let global = c.snapshot();
        assert_eq!(global.total_calls, 3);
        assert_eq!(global.successful_calls, 2);
        assert_eq!(global.failed_calls, 1);
    }

    #[test]
    fn test_get_aggregate_missing() {
        let c = MetricsCollector::new();
        assert!(c.get_aggregate("nonexistent").is_none());
    }

    #[test]
    fn test_snapshot_empty() {
        let c = MetricsCollector::new();
        let s = c.snapshot();
        assert_eq!(s.total_calls, 0);
        assert_eq!(s.successful_calls, 0);
        assert_eq!(s.failed_calls, 0);
        assert_eq!(s.max_latency_us, 0);
    }

    #[test]
    fn test_record_batch() {
        let c = MetricsCollector::new();
        c.record_batch(&[
            MetricRecord {
                agent_key: "a1".to_string(),
                success: true,
                duration: Duration::from_millis(10),
            },
            MetricRecord {
                agent_key: "a1".to_string(),
                success: false,
                duration: Duration::from_millis(20),
            },
            MetricRecord {
                agent_key: "a2".to_string(),
                success: true,
                duration: Duration::from_millis(30),
            },
        ]);
        let s1 = c.get_aggregate("a1").unwrap();
        assert_eq!(s1.total_calls, 2);
        assert_eq!(s1.successful_calls, 1);
        assert_eq!(s1.failed_calls, 1);
        assert_eq!(s1.min_latency_us, 10_000);
        assert_eq!(s1.max_latency_us, 20_000);
        let s2 = c.get_aggregate("a2").unwrap();
        assert_eq!(s2.total_calls, 1);
        let global = c.snapshot();
        assert_eq!(global.total_calls, 3);
    }

    #[test]
    fn test_reset() {
        let c = MetricsCollector::new();
        c.record_invocation("a1", true, Duration::from_millis(1));
        c.reset();
        assert!(c.get_aggregate("a1").is_none());
        let s = c.snapshot();
        assert_eq!(s.total_calls, 0);
    }

    #[test]
    fn test_suggest_timeout_no_samples() {
        let c = MetricsCollector::new();
        let default = Duration::from_secs(30);
        let min = Duration::from_secs(1);
        let max = Duration::from_secs(300);
        let out = c.suggest_timeout_for_agent("agent1", default, min, max);
        assert_eq!(out, default);
    }

    #[test]
    fn test_suggest_timeout_from_p95() {
        let c = MetricsCollector::new();
        for _ in 0..10 {
            c.record_invocation("agent1", true, Duration::from_millis(100));
        }
        let default = Duration::from_secs(30);
        let min = Duration::from_secs(1);
        let max = Duration::from_secs(300);
        let out = c.suggest_timeout_for_agent("agent1", default, min, max);
        assert!(out >= min);
        assert!(out <= max);
        assert!(out >= Duration::from_millis(150)); // 1.5 * 100ms
    }
}
