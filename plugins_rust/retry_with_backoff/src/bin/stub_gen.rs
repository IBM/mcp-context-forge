// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Stub file generator for retry_with_backoff module
//
// This binary generates Python type stub files (.pyi) for the retry_with_backoff module.
// Run with: cargo run --bin stub_gen

use retry_with_backoff_rust::stub_info;

fn main() {
    let stub_info = stub_info().expect("Failed to get stub info");
    stub_info.generate().expect("Failed to generate stub file");
    println!("✓ Generated stub files successfully");
}
