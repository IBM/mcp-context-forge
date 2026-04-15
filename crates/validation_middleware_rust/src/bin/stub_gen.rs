// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Stub file generator for validation_middleware_rust.

use validation_middleware_rust::stub_info;

fn main() {
    let stub_info = stub_info().expect("Failed to get stub info");
    stub_info.generate().expect("Failed to generate stub file");
    println!("Generated validation_middleware_rust stubs successfully");
}
