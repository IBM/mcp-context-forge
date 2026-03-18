// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Stub file generator for pii_filter module
//
// This binary generates Python type stub files (.pyi) for the pii_filter module.
// Run with: cargo run --bin stub_gen

use log::{debug, info};
use pii_filter_rust::stub_info;
use std::error::Error;

fn main() -> Result<(), Box<dyn Error>> {
    let init_result = pyo3_log::try_init();
    if init_result.is_ok() {
        debug!("pii_filter stub generation logging initialized");
    }

    // Get stub info (returns Result)
    let stub_info = stub_info()?;

    // Generate stub files - paths are determined from pyproject.toml
    stub_info.generate()?;

    info!("pii_filter stub generated");
    Ok(())
}
