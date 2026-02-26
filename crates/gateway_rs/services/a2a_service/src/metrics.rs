use std::sync::atomic::{AtomicU64, Ordering};
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
/// Records counts and latency per call; supports batch recording after invoke.
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
            min_latency_us: AtomicU64::new(u64::MAX),
            max_latency_us: AtomicU64::new(0),
        }
    }

    /// Record a successful call with the given latency.
    pub fn record_success(&self, latency: Duration) {
        let us = latency.as_micros().min(u64::MAX as u128) as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.successful_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min_max(us);
    }

    /// Record a failed call with the given latency.
    pub fn record_failure(&self, latency: Duration) {
        let us = latency.as_micros().min(u64::MAX as u128) as u64;
        self.total_calls.fetch_add(1, Ordering::Relaxed);
        self.failed_calls.fetch_add(1, Ordering::Relaxed);
        self.total_latency_us.fetch_add(us, Ordering::Relaxed);
        self.update_min_max(us);
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

    /// Record a batch of (success, latency) from an invoke. Used after 1..N requests complete.
    pub fn record_batch(&self, results: &[(bool, Duration)]) {
        for (success, latency) in results {
            if *success {
                self.record_success(*latency);
            } else {
                self.record_failure(*latency);
            }
        }
    }

    /// Take a point-in-time snapshot of the current metrics.
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

    /// Reset all metrics counters.
    pub fn reset(&self) {
        self.total_calls.store(0, Ordering::Relaxed);
        self.successful_calls.store(0, Ordering::Relaxed);
        self.failed_calls.store(0, Ordering::Relaxed);
        self.total_latency_us.store(0, Ordering::Relaxed);
        self.min_latency_us.store(u64::MAX, Ordering::Relaxed);
        self.max_latency_us.store(0, Ordering::Relaxed);
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

    #[test]
    fn test_record_success_and_snapshot() {
        let m = MetricsCollector::new();
        m.record_success(Duration::from_millis(100));
        m.record_success(Duration::from_millis(200));
        m.record_failure(Duration::from_millis(50));
        let s = m.snapshot();
        assert_eq!(s.total_calls, 3);
        assert_eq!(s.successful_calls, 2);
        assert_eq!(s.failed_calls, 1);
        assert_eq!(s.min_latency_us, 50_000);
        assert_eq!(s.max_latency_us, 200_000);
    }

    #[test]
    fn test_record_batch() {
        let m = MetricsCollector::new();
        m.record_batch(&[
            (true, Duration::from_millis(10)),
            (false, Duration::from_millis(20)),
            (true, Duration::from_millis(30)),
        ]);
        let s = m.snapshot();
        assert_eq!(s.total_calls, 3);
        assert_eq!(s.successful_calls, 2);
        assert_eq!(s.failed_calls, 1);
        assert_eq!(s.min_latency_us, 10_000);
        assert_eq!(s.max_latency_us, 30_000);
    }

    #[test]
    fn test_reset() {
        let m = MetricsCollector::new();
        m.record_success(Duration::from_millis(1));
        m.reset();
        let s = m.snapshot();
        assert_eq!(s.total_calls, 0);
        assert_eq!(s.successful_calls, 0);
        assert_eq!(s.min_latency_us, 0);
    }
}
