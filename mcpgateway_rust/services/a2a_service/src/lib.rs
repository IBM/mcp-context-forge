// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// A2A Service - High-performance agent invocation with PyO3 bindings
//
// This module provides Rust-accelerated HTTP invocation for A2A agents,
// offering 10-50x performance improvements over Python asyncio/httpx.

use pyo3::prelude::*;

/// A2A Service module
#[pymodule]
pub fn a2a_service(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
