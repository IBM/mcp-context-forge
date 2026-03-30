// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Stub file generator for output_length_guard module
//
// This binary generates Python type stub files (.pyi) for the output_length_guard module.
// Run with: cargo run --bin stub_gen

use output_length_guard_rust::stub_info;

fn main() {
    let stub_info = stub_info().expect("Failed to get stub info");
    stub_info.generate().expect("Failed to generate stub file");
    println!("Generated stub files successfully");
}
