use std::sync::atomic::AtomicU64;
use std::time::Duration;

/// Snapshot of aggregated A2A invocation metrics.
#[derive(Debug, Clone, Default)]
pub struct AggregateMetrics {
    pub total_calls: u64,
    pub successful_calls: u64,
    pub failed_calls: u64,
    pub total_latency_us: u64,
    pub min_latency_us: u64,
    pub max_latency_us: u64,
}

/// In-memory metrics collector for A2A invocations.
///
/// For now this is a thin placeholder; its methods are intentionally
/// implemented with `todo!()` until the full metrics pipeline is wired up.
#[derive(Debug)]
pub struct MetricsCollector {
    pub total_calls: AtomicU64,
    pub successful_calls: AtomicU64,
    pub failed_calls: AtomicU64,
    pub total_latency_us: AtomicU64,
    pub min_latency_us: AtomicU64,
    pub max_latency_us: AtomicU64,
}

impl Default for MetricsCollector {
    fn default() -> Self {
        Self::new()
    }
}

impl MetricsCollector {
    pub fn new() -> Self {
        Self {
            total_calls: AtomicU64::new(0),
            successful_calls: AtomicU64::new(0),
            failed_calls: AtomicU64::new(0),
            total_latency_us: AtomicU64::new(0),
            // Start min at MAX so the first observed latency becomes the minimum.
            min_latency_us: AtomicU64::new(u64::MAX),
            max_latency_us: AtomicU64::new(0),
        }
    }

    /// Record a successful call with the given latency.
    pub fn record_success(&self, _latency: Duration) {
        todo!()
    }

    /// Record a failed call with the given latency.
    pub fn record_failure(&self, _latency: Duration) {
        todo!()
    }

    /// Take a point-in-time snapshot of the current metrics.
    pub fn snapshot(&self) -> AggregateMetrics {
        todo!()
    }

    /// Reset all metrics counters.
    pub fn reset(&self) {
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_collector_new() {
        let m = MetricsCollector::new();
        assert_eq!(m.total_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
        assert_eq!(m.successful_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
        assert_eq!(m.failed_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
        assert_eq!(m.total_latency_us.load(std::sync::atomic::Ordering::SeqCst), 0);
        assert_eq!(
            m.min_latency_us.load(std::sync::atomic::Ordering::SeqCst),
            u64::MAX
        );
        assert_eq!(m.max_latency_us.load(std::sync::atomic::Ordering::SeqCst), 0);
    }

    #[test]
    fn test_metrics_collector_default() {
        let m = MetricsCollector::default();
        assert_eq!(m.total_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
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
}
