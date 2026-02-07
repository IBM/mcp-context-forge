// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// PII Filter Plugin - Rust Implementation
//
// High-performance PII detection and masking using:
// - RegexSet for parallel pattern matching (5-10x faster)
// - Copy-on-write strings for zero-copy operations
// - Zero-copy JSON traversal with serde_json

pub mod config;
pub mod detector;
pub mod masking;
pub mod patterns;

pub use detector::PIIDetectorRust;

// Standalone Python module (only when building as extension)
#[cfg(feature = "extension-module")]
use pyo3::prelude::*;

/// Python module: pii_filter_rust
///
/// High-performance PII detection and masking for MCP Gateway.
/// Provides 5-10x speedup over pure Python implementations.
///
/// # Examples
///
/// ```python
/// from pii_filter_rust import PIIDetectorRust
///
/// # Create detector with configuration
/// config = {
///     "detect_ssn": True,
///     "detect_credit_card": True,
///     "default_mask_strategy": "redact",
/// }
/// detector = PIIDetectorRust(config)
///
/// # Detect PII in text
/// text = "My SSN is 123-45-6789"
/// detections = detector.detect(text)
/// print(detections)  # {"ssn": [{"value": "123-45-6789", ...}]}
///
/// # Mask detected PII
/// masked = detector.mask(text, detections)
/// print(masked)  # "My SSN is [REDACTED]"
/// ```
#[cfg(feature = "extension-module")]
#[pymodule]
fn pii_filter_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Export PII Detector
    m.add_class::<PIIDetectorRust>()?;

    // Module metadata
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add(
        "__doc__",
        "High-performance PII detection and masking for MCP Gateway",
    )?;

    Ok(())
}
