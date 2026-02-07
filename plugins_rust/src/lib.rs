// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Rust-accelerated plugins for MCP Gateway
// Built with PyO3 for seamless Python integration

// Allow non-local definitions for PyO3 macros (known issue with PyO3 0.20.x)
#![allow(non_local_definitions)]

use pyo3::prelude::*;

// Re-export the pii_filter library (note: lib name is pii_filter_rust in Cargo.toml)
pub use pii_filter_rust as pii_filter;

/// Python module: plugins_rust
///
/// High-performance Rust implementations of MCP Gateway plugins.
/// Provides 5-10x speedup over pure Python implementations.
///
/// # Examples
///
/// ```python
/// from plugins_rust import PIIDetectorRust
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
#[pymodule]
fn plugins_rust(m: &Bound<'_, pyo3::types::PyModule>) -> PyResult<()> {
    // Export PII Filter Rust implementation
    m.add_class::<pii_filter_rust::PIIDetectorRust>()?;

    // Module metadata
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add(
        "__doc__",
        "High-performance Rust implementations of MCP Gateway plugins",
    )?;

    Ok(())
}
