// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Binary entry point for the Rust MCP runtime.

use clap::Parser;
use contextforge_mcp_runtime::{config::RuntimeConfig, observability, run};

#[tokio::main]
async fn main() {
    let config = RuntimeConfig::parse();

    let telemetry = match observability::init_tracing(&config.log_filter) {
        Ok(telemetry) => telemetry,
        Err(err) => {
            eprintln!("contextforge-mcp-runtime failed to initialize observability: {err}");
            std::process::exit(1);
        }
    };

    if let Err(err) = run(config).await {
        telemetry.shutdown();
        eprintln!("contextforge-mcp-runtime failed: {err}");
        std::process::exit(1);
    }

    telemetry.shutdown();
}
