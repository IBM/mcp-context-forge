// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Stub file generator for encoded_exfil_detection module
//
// This binary generates Python type stub files (.pyi) for the encoded_exfil_detection module.
// Run with: cargo run --bin stub_gen

use encoded_exfil_detection_rust::stub_info;

fn main() {
    // Get stub info (returns Result)
    let stub_info = stub_info().expect("Failed to get stub info");

    // Generate stub files - paths are determined from pyproject.toml
    stub_info.generate().expect("Failed to generate stub file");

    println!("✓ Generated stub files successfully");
}
