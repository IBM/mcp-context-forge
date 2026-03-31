// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Binary entry point for the Rust MCP runtime.

use clap::Parser;
use contextforge_mcp_runtime::{config::RuntimeConfig, run_cli};

fn main() {
    let config = RuntimeConfig::parse();

    if let Err(err) = run_cli(config) {
        eprintln!("contextforge-mcp-runtime failed: {err}");
        std::process::exit(1);
    }
}
