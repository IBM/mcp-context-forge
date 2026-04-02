// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Rate Limiter Engine — Rust implementation.
//
// Exposed to Python via PyO3. One public class: `RateLimiterEngine`.
// One public hot-path method: `evaluate_many()` (ARCH-01, IFACE-02).

use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;

pub mod clock;
pub mod config;
pub mod engine;
pub mod memory;
pub mod redis_backend;
pub mod types;

pub use engine::RateLimiterEngine;
pub use types::{EvalDimension, EvalResult};

/// Python module definition.
#[pymodule]
fn rate_limiter_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Bridge Rust `log` macros into Python's `logging` module so Rust
    // engine messages appear in the same log stream as the Python plugin.
    pyo3_log::init();

    m.add_class::<RateLimiterEngine>()?;
    m.add_class::<EvalResult>()?;
    m.add_class::<EvalDimension>()?;
    Ok(())
}

// Generate Python type stubs (.pyi files).
define_stub_info_gatherer!(stub_info);
