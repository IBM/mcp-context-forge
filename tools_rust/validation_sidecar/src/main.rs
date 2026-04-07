// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Binary entry point for the validation sidecar.

use clap::Parser;
use contextforge_validation_sidecar::{ServerConfig, run};
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(name = "contextforge-validation-sidecar")]
#[command(about = "Rust UDS validation sidecar for ContextForge")]
struct Cli {
    #[arg(long = "uds-path", env = "EXPERIMENTAL_RUST_VALIDATION_SIDECAR_UDS")]
    uds_path: PathBuf,
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();
    let config = ServerConfig::new(cli.uds_path);

    if let Err(error) = run(config).await {
        eprintln!("contextforge-validation-sidecar failed: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    #[test]
    fn cli_requires_uds_path() {
        let result = Cli::try_parse_from(["contextforge-validation-sidecar"]);

        assert!(result.is_err());
    }
}
