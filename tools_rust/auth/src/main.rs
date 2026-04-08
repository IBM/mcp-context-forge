// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Binary entry point for the auth service.

use clap::Parser;
use contextforge_auth::{config::AuthConfig, run};

#[tokio::main]
async fn main() {
    let config = AuthConfig::parse();

    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::new(config.log_filter.clone()))
        .init();

    if let Err(err) = run(config).await {
        eprintln!("contextforge-auth failed: {err}");
        std::process::exit(1);
    }
}
