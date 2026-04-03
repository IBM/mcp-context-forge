// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Generates Python type stubs (.pyi) for the rate_limiter_rust module.
// Run with: cargo run --bin stub_gen

use rate_limiter_rust::stub_info;

fn main() {
    let stub_info = stub_info().expect("Failed to get stub info");
    stub_info.generate().expect("Failed to generate stub file");
    println!("✓ Generated stub files successfully");
}
