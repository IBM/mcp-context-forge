// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! CLI and environment-backed configuration for the Rust A2A runtime.

use clap::Parser;
use std::{net::SocketAddr, path::PathBuf};

#[derive(Debug, Clone, Parser)]
#[command(name = "contextforge-a2a-runtime")]
#[command(about = "Experimental Rust A2A runtime sidecar for ContextForge")]
pub struct RuntimeConfig {
    #[arg(long, env = "A2A_RUST_LISTEN_HTTP", default_value = "127.0.0.1:8788")]
    pub listen_http: String,

    #[arg(long, env = "A2A_RUST_LISTEN_UDS")]
    pub listen_uds: Option<PathBuf>,

    #[arg(long, env = "A2A_RUST_REQUEST_TIMEOUT_MS", default_value_t = 30_000)]
    pub request_timeout_ms: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_CONNECT_TIMEOUT_MS",
        default_value_t = 5_000
    )]
    pub client_connect_timeout_ms: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_POOL_IDLE_TIMEOUT_SECONDS",
        default_value_t = 90
    )]
    pub client_pool_idle_timeout_seconds: u64,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_POOL_MAX_IDLE_PER_HOST",
        default_value_t = 256
    )]
    pub client_pool_max_idle_per_host: usize,

    #[arg(
        long,
        env = "A2A_RUST_CLIENT_TCP_KEEPALIVE_SECONDS",
        default_value_t = 30
    )]
    pub client_tcp_keepalive_seconds: u64,

    #[arg(long, env = "A2A_RUST_LOG", default_value = "info")]
    pub log_filter: String,

    #[arg(long, env = "A2A_RUST_EXIT_AFTER_STARTUP_MS", hide = true)]
    pub exit_after_startup_ms: Option<u64>,
}

#[derive(Debug, Clone)]
pub enum ListenTarget {
    Http(SocketAddr),
    Uds(PathBuf),
}

impl RuntimeConfig {
    pub fn listen_target(&self) -> Result<ListenTarget, String> {
        if let Some(path) = &self.listen_uds {
            return Ok(ListenTarget::Uds(path.clone()));
        }

        self.listen_http
            .parse::<SocketAddr>()
            .map(ListenTarget::Http)
            .map_err(|err| {
                format!(
                    "invalid A2A_RUST_LISTEN_HTTP value '{}': {err}",
                    self.listen_http
                )
            })
    }
}
