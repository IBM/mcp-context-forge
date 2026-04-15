// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Binary entry point for the Rust A2A runtime.

use clap::Parser;
use contextforge_a2a_runtime::{config::RuntimeConfig, run};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() {
    let config = RuntimeConfig::parse();

    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::new(config.log_filter.clone()))
        .with_target(false)
        .compact()
        .init();

    if let Err(err) = run(config).await {
        eprintln!("contextforge-a2a-runtime failed: {err}");
        std::process::exit(1);
    }
}
