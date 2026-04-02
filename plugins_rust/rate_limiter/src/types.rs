// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Public result types for the rate limiter engine.
//
// `EvalResult` is the compact typed struct returned by `evaluate_many()`.
// It matches the shape described in IFACE-03 and is the only type that
// crosses the PyO3 boundary.

use pyo3::prelude::*;
use pyo3_stub_gen::derive::*;

/// The outcome of a single dimension check.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DimResult {
    pub allowed: bool,
    /// Configured request limit for this dimension.
    pub limit: u64,
    /// Requests remaining in the current window (0 when blocked).
    pub remaining: u64,
    /// Unix timestamp when the current window resets.
    pub reset_timestamp: i64,
    /// Seconds until the window resets — `Some` only when blocked.
    pub retry_after: Option<i64>,
}

/// The outcome of a single active dimension, exposed to Python for
/// per-dimension inspection (e.g. which dimension blocked the request).
#[gen_stub_pyclass]
#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
pub struct EvalDimension {
    /// Requests remaining for this active dimension.
    pub remaining: u64,
    /// Unix timestamp when this dimension resets or refills.
    pub reset_timestamp: i64,
    /// Seconds until retry — populated only for blocked dimensions.
    pub retry_after: Option<i64>,
}

/// The aggregated result returned to Python via `evaluate_many()`.
///
/// Contains the most restrictive outcome across all active dimensions
/// (min remaining, earliest unblock among blocked dimensions — matching
/// Python `_select_most_restrictive`).
#[gen_stub_pyclass]
#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
pub struct EvalResult {
    /// `True` if all active dimensions allow the request.
    pub allowed: bool,
    /// Configured limit for the most restrictive active dimension.
    pub limit: u64,
    /// Remaining requests for the most restrictive active dimension.
    pub remaining: u64,
    /// Unix timestamp when the most restrictive dimension resets.
    pub reset_timestamp: i64,
    /// Seconds until reset — populated only when `allowed == False`.
    pub retry_after: Option<i64>,
    /// Per-dimension outcomes that were blocked for this request.
    pub violated_dimensions: Vec<EvalDimension>,
    /// Per-dimension outcomes that still allowed this request.
    pub allowed_dimensions: Vec<EvalDimension>,
}

#[gen_stub_pymethods]
#[pymethods]
impl EvalResult {
    fn __repr__(&self) -> String {
        format!(
            "EvalResult(allowed={}, limit={}, remaining={}, reset_timestamp={}, retry_after={:?})",
            self.allowed, self.limit, self.remaining, self.reset_timestamp, self.retry_after
        )
    }
}

impl EvalResult {
    /// Construct an "unlimited" result used when no dimensions are configured.
    pub fn unlimited(reset_timestamp: i64) -> Self {
        Self {
            allowed: true,
            limit: u64::MAX,
            remaining: u64::MAX,
            reset_timestamp,
            retry_after: None,
            violated_dimensions: Vec::new(),
            allowed_dimensions: Vec::new(),
        }
    }

    /// Select the most restrictive result across a slice of `DimResult`s.
    ///
    /// Rules (matching Python `_select_most_restrictive`):
    /// - Any blocked dimension → result is blocked.
    /// - Among blocked: lowest `retry_after` wins (soonest retry).
    /// - Among allowed: lowest `remaining` wins (closest to limit).
    /// - `retry_after` is set iff the result is blocked.
    ///
    /// The "lowest retry_after" policy signals the next state change — the
    /// caller learns when at least one dimension will re-open, even if other
    /// dimensions remain blocked longer.  An alternative (max) would
    /// guarantee success on retry but delays the first attempt.  This is a
    /// deliberate product-level contract shared by both implementations.
    pub fn from_dims(dims: &[DimResult]) -> Self {
        if dims.is_empty() {
            return Self::unlimited(0);
        }

        let any_blocked = dims.iter().any(|d| !d.allowed);
        let violated_dimensions: Vec<EvalDimension> = dims
            .iter()
            .filter(|d| !d.allowed)
            .map(|d| EvalDimension {
                remaining: d.remaining,
                reset_timestamp: d.reset_timestamp,
                retry_after: d.retry_after,
            })
            .collect();
        let allowed_dimensions: Vec<EvalDimension> = dims
            .iter()
            .filter(|d| d.allowed)
            .map(|d| EvalDimension {
                remaining: d.remaining,
                reset_timestamp: d.reset_timestamp,
                retry_after: None,
            })
            .collect();

        if any_blocked {
            // Among blocked dimensions, pick the one that unblocks soonest.
            let worst = dims
                .iter()
                .filter(|d| !d.allowed)
                .min_by_key(|d| d.retry_after.unwrap_or(i64::MAX))
                .unwrap();
            Self {
                allowed: false,
                limit: worst.limit,
                remaining: 0,
                reset_timestamp: worst.reset_timestamp,
                retry_after: worst.retry_after,
                violated_dimensions,
                allowed_dimensions,
            }
        } else {
            // All allowed — pick the one with the fewest remaining.
            let most_restrictive = dims.iter().min_by_key(|d| d.remaining).unwrap();
            Self {
                allowed: true,
                limit: most_restrictive.limit,
                remaining: most_restrictive.remaining,
                reset_timestamp: most_restrictive.reset_timestamp,
                retry_after: None,
                violated_dimensions,
                allowed_dimensions,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dim(allowed: bool, remaining: u64, reset: i64) -> DimResult {
        DimResult {
            allowed,
            limit: 10,
            remaining,
            reset_timestamp: reset,
            retry_after: if allowed { None } else { Some(reset - 1000) },
        }
    }

    // --- IFACE-03: EvalResult field types ---

    #[test]
    fn eval_result_fields_accessible() {
        let r = EvalResult {
            allowed: true,
            limit: 30,
            remaining: 25,
            reset_timestamp: 9_999_999,
            retry_after: None,
            violated_dimensions: Vec::new(),
            allowed_dimensions: vec![EvalDimension {
                remaining: 25,
                reset_timestamp: 9_999_999,
                retry_after: None,
            }],
        };
        assert!(r.allowed);
        assert_eq!(r.limit, 30);
        assert_eq!(r.remaining, 25);
        assert_eq!(r.reset_timestamp, 9_999_999);
        assert!(r.retry_after.is_none());
    }

    #[test]
    fn eval_result_retry_after_populated_when_blocked() {
        let r = EvalResult {
            allowed: false,
            limit: 30,
            remaining: 0,
            reset_timestamp: 9_999_999,
            retry_after: Some(42),
            violated_dimensions: vec![EvalDimension {
                remaining: 0,
                reset_timestamp: 9_999_999,
                retry_after: Some(42),
            }],
            allowed_dimensions: Vec::new(),
        };
        assert!(!r.allowed);
        assert_eq!(r.retry_after, Some(42));
    }

    // --- CORR-07: from_dims aggregation ---

    #[test]
    fn from_dims_empty_is_unlimited() {
        let r = EvalResult::from_dims(&[]);
        assert!(r.allowed);
        assert_eq!(r.limit, u64::MAX);
        assert!(r.allowed_dimensions.is_empty());
        assert!(r.violated_dimensions.is_empty());
    }

    #[test]
    fn from_dims_all_allowed_picks_min_remaining() {
        let dims = vec![dim(true, 20, 2000), dim(true, 5, 1500), dim(true, 15, 1800)];
        let r = EvalResult::from_dims(&dims);
        assert!(r.allowed);
        assert_eq!(r.remaining, 5);
        assert_eq!(r.reset_timestamp, 1500);
        assert!(r.retry_after.is_none());
        assert_eq!(r.allowed_dimensions.len(), 3);
        assert!(r.violated_dimensions.is_empty());
    }

    #[test]
    fn from_dims_any_blocked_result_is_blocked() {
        let dims = vec![dim(true, 5, 1500), dim(false, 0, 2000), dim(true, 10, 1800)];
        let r = EvalResult::from_dims(&dims);
        assert!(!r.allowed);
        assert_eq!(r.remaining, 0);
        assert_eq!(r.allowed_dimensions.len(), 2);
        assert_eq!(r.violated_dimensions.len(), 1);
    }

    #[test]
    fn from_dims_multiple_blocked_picks_soonest_retry() {
        let dims = vec![
            dim(false, 0, 3000),
            dim(false, 0, 1000),
            dim(false, 0, 2000),
        ];
        let r = EvalResult::from_dims(&dims);
        assert!(!r.allowed);
        assert_eq!(r.reset_timestamp, 1000);
        assert_eq!(r.retry_after, Some(0));
        assert_eq!(r.violated_dimensions.len(), 3);
    }

    #[test]
    fn from_dims_retry_after_none_when_allowed() {
        let dims = vec![dim(true, 1, 9000)];
        let r = EvalResult::from_dims(&dims);
        assert!(r.retry_after.is_none());
        assert_eq!(r.allowed_dimensions[0].remaining, 1);
        assert_eq!(r.allowed_dimensions[0].reset_timestamp, 9000);
    }
}
