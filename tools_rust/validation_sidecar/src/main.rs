// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Binary entry point for the validation sidecar.

use clap::Parser;
use contextforge_validation_sidecar::{ServerConfig, run, validator::ParserBackend};
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(name = "contextforge-validation-sidecar")]
#[command(about = "Rust UDS validation sidecar for ContextForge")]
struct Cli {
    #[arg(long = "uds-path", env = "EXPERIMENTAL_RUST_VALIDATION_SIDECAR_UDS")]
    uds_path: PathBuf,
    #[arg(
        long = "parser",
        env = "EXPERIMENTAL_RUST_VALIDATION_SIDECAR_PARSER",
        value_enum,
        default_value_t = ParserBackend::SimdJson
    )]
    parser_backend: ParserBackend,
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();
    let config = ServerConfig {
        uds_path: cli.uds_path,
        parser_backend: cli.parser_backend,
    };

    if let Err(error) = run(config).await {
        eprintln!("contextforge-validation-sidecar failed: {error}");
        std::process::exit(1);
    }
}
