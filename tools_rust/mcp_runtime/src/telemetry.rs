// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Runtime bootstrap helpers for tracing, Dial9 telemetry, and Tokio console.

use crate::{RuntimeError, config::RuntimeConfig, run};
use tracing::Dispatch;
use tracing_subscriber::{EnvFilter, fmt, prelude::*};

#[cfg(feature = "runtime-telemetry")]
use console_subscriber::Builder as ConsoleSubscriberBuilder;
#[cfg(feature = "runtime-telemetry")]
use dial9_tokio_telemetry::telemetry::{RotatingWriter, TracedRuntime};
#[cfg(feature = "runtime-telemetry")]
use std::{fs, net::SocketAddr};

fn build_dispatch(config: &RuntimeConfig) -> Result<Dispatch, RuntimeError> {
    let filter = EnvFilter::new(config.log_filter.clone());
    let fmt_layer = fmt::layer().with_target(false).compact();

    #[cfg(feature = "runtime-telemetry")]
    {
        if config.tokio_console_enabled {
            let console_bind = config
                .tokio_console_bind
                .parse::<SocketAddr>()
                .map_err(|err| {
                    RuntimeError::Config(format!(
                        "invalid Tokio console bind address '{}': {err}",
                        config.tokio_console_bind
                    ))
                })?;
            let console_layer = ConsoleSubscriberBuilder::default()
                .server_addr(console_bind)
                .spawn();
            return Ok(Dispatch::new(
                tracing_subscriber::registry()
                    .with(filter)
                    .with(fmt_layer)
                    .with(console_layer),
            ));
        }
    }

    Ok(Dispatch::new(
        tracing_subscriber::registry().with(filter).with(fmt_layer),
    ))
}

#[cfg(not(feature = "runtime-telemetry"))]
fn ensure_telemetry_feature_support(config: &RuntimeConfig) -> Result<(), RuntimeError> {
    if config.telemetry_enabled || config.tokio_console_enabled {
        return Err(RuntimeError::Config(
            "Rust runtime telemetry flags require a binary built with the 'runtime-telemetry' Cargo feature".to_string(),
        ));
    }

    Ok(())
}

#[cfg(feature = "runtime-telemetry")]
#[allow(clippy::unnecessary_wraps)]
fn ensure_telemetry_feature_support(_config: &RuntimeConfig) -> Result<(), RuntimeError> {
    Ok(())
}

fn build_standard_runtime(config: RuntimeConfig, dispatch: &Dispatch) -> Result<(), RuntimeError> {
    let mut builder = tokio::runtime::Builder::new_multi_thread();
    builder.enable_all();
    let runtime = builder.build()?;

    tracing::dispatcher::with_default(dispatch, || runtime.block_on(run(config)))
}

#[cfg(feature = "runtime-telemetry")]
fn build_traced_runtime(config: RuntimeConfig, dispatch: &Dispatch) -> Result<(), RuntimeError> {
    if let Some(parent) = config.telemetry_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let writer = RotatingWriter::new(
        &config.telemetry_path,
        config.telemetry_rotate_bytes,
        config.telemetry_max_bytes,
    )?;

    let mut builder = tokio::runtime::Builder::new_multi_thread();
    builder.enable_all();

    let (runtime, _guard) =
        TracedRuntime::build_and_start(builder, Box::new(writer)).map_err(|err| {
            RuntimeError::Config(format!("failed to start Dial9 runtime telemetry: {err}"))
        })?;

    tracing::dispatcher::with_default(dispatch, || runtime.block_on(run(config)))
}

/// Runs the runtime from the CLI/bootstrap path, including optional telemetry setup.
///
/// # Errors
///
/// Returns an error when the runtime configuration is invalid, telemetry support
/// is requested without a telemetry-enabled build, telemetry bootstrap fails, or
/// the runtime itself fails to start or serve.
pub fn run_cli(config: RuntimeConfig) -> Result<(), RuntimeError> {
    config
        .validate_telemetry_config()
        .map_err(RuntimeError::Config)?;
    ensure_telemetry_feature_support(&config)?;

    let dispatch = build_dispatch(&config)?;

    #[cfg(feature = "runtime-telemetry")]
    {
        if config.telemetry_enabled {
            return build_traced_runtime(config, &dispatch);
        }
    }

    build_standard_runtime(config, &dispatch)
}
