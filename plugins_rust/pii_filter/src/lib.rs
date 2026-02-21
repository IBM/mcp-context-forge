// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// PII Filter Plugin - Rust Implementation
//
// High-performance PII detection and masking using:
// - RegexSet for parallel pattern matching (5-10x faster)
// - Copy-on-write strings for zero-copy operations
// - Zero-copy JSON traversal with serde_json

use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;

pub mod config;
pub mod detector;
pub mod masking;
pub mod patterns;

pub use detector::PIIDetectorRust;

/// Python module definition
#[pymodule]
fn pii_filter_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PIIDetectorRust>()?;
    Ok(())
}

// Define stub info gatherer for generating Python type stubs
define_stub_info_gatherer!(stub_info);
