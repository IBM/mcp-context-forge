// SPDX-License-Identifier: Apache-2.0
//! PII Filter Plugin - Rust implementation for ContextForge.
//!
//! Detects and masks personally identifiable information (PII) in text. Flow: build
//! [PIIConfig](config::PIIConfig) (from Python dict or default), compile patterns with
//! [compile_patterns](patterns::compile_patterns), run [detect_pii](detect_pii) to get detections,
//! then [mask_pii](masking::mask_pii) to produce masked text. Exposed to Python via
//! [PIIDetectorRust](detector::PIIDetectorRust).
//!
//! The crate is organized into small, focused modules:
//! - [`config`] parses Python and Rust configuration into [`PIIConfig`](config::PIIConfig).
//! - [`patterns`] compiles regex definitions and whitelist patterns once.
//! - [`detector`] performs candidate extraction, validation, and overlap resolution.
//! - [`masking`] applies the effective masking strategy to each detection.
//! - [`error`] centralizes typed errors used at the Rust and PyO3 boundaries.
//!
//! Basic Rust usage:
//! ```rust
//! use pii_filter_rust::{config::PIIConfig, detect_pii, mask_pii, patterns::compile_patterns};
//!
//! let config = PIIConfig::default();
//! let patterns = compile_patterns(&config).unwrap();
//! let detections = detect_pii("Email: john@example.com", &patterns, &config);
//! let masked = mask_pii("Email: john@example.com", &detections, &config).unwrap();
//! assert!(masked.contains("@example.com") || masked.contains("[REDACTED]"));
//! ```

use log::{debug, warn};
use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;
use std::sync::OnceLock;

pub mod config;
pub mod detector;
pub mod error;
pub mod masking;
pub mod patterns;

pub use detector::{PIIDetectorRust, detect_pii};
use error::PIIFilterError;
pub use masking::mask_pii;

pub(crate) fn init_logging() {
    static INIT: OnceLock<()> = OnceLock::new();

    INIT.get_or_init(|| {
        let init_result = pyo3_log::try_init();

        if init_result.is_ok() {
            debug!("pii_filter logging initialized");
        }
    });
}

pub(crate) fn sanitized_path_depth(path: Option<&str>) -> usize {
    path.filter(|value| !value.is_empty())
        .map(|value| {
            value
                .bytes()
                .filter(|byte| *byte == b'.' || *byte == b'[')
                .count()
                + 1
        })
        .unwrap_or(0)
}

pub(crate) fn sanitized_path_kind(path: Option<&str>) -> &'static str {
    if sanitized_path_depth(path) == 0 {
        "root"
    } else {
        "nested"
    }
}

pub(crate) fn log_boundary_error(operation: &'static str, err: &PIIFilterError) {
    if let Some(field) = err.safe_field_name() {
        warn!(
            "event=pii_filter_boundary_error operation={operation} error_category={} error_kind={} field={field}",
            err.category(),
            err.kind(),
        );
    } else {
        warn!(
            "event=pii_filter_boundary_error operation={operation} error_category={} error_kind={}",
            err.category(),
            err.kind(),
        );
    }
}

/// Python module definition
#[pymodule]
fn pii_filter_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    init_logging();
    m.add_class::<PIIDetectorRust>()?;
    Ok(())
}

// Define stub info gatherer for generating Python type stubs
define_stub_info_gatherer!(stub_info);

#[cfg(test)]
mod tests {
    use super::init_logging;

    #[test]
    fn test_init_logging_is_repeatable() {
        init_logging();
        init_logging();
    }
}
