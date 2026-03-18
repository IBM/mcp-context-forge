// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! CLI and environment-backed configuration for the A2A invoke service.

use clap::Parser;
use std::net::SocketAddr;

#[derive(Debug, Clone, Parser)]
#[command(name = "a2a-service")]
#[command(about = "Standalone A2A agent invocation service (ContextForge)")]
pub struct Config {
    #[arg(long, env = "A2A_RUST_LISTEN_HTTP", default_value = "127.0.0.1:8790")]
    pub listen_http: String,

    /// Base URL for the Python gateway backend (used for CRUD proxying and as a fallback).
    #[arg(
        long,
        env = "A2A_RUST_BACKEND_BASE_URL",
        default_value = "http://127.0.0.1:4444"
    )]
    pub backend_base_url: String,

    #[arg(long, env = "A2A_RUST_AUTH_SECRET")]
    pub auth_secret: Option<String>,

    #[arg(long, env = "A2A_RUST_MAX_CONCURRENT", default_value_t = 64)]
    pub max_concurrent: usize,

    #[arg(long, env = "A2A_RUST_MAX_QUEUED")]
    pub max_queued: Option<usize>,

    #[arg(long, env = "A2A_RUST_INVOKE_TIMEOUT_SECS", default_value_t = 60.0)]
    pub invoke_timeout_secs: f64,
}

impl Config {
    pub fn listen_socket_addr(&self) -> Result<SocketAddr, std::net::AddrParseError> {
        let s = self.listen_http.as_str();
        if s.contains(':') {
            s.parse()
        } else {
            format!("{}:8790", s).parse()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_listen_socket_addr_with_port() {
        let c = Config {
            listen_http: "127.0.0.1:8790".to_string(),
            backend_base_url: String::new(),
            auth_secret: None,
            max_concurrent: 64,
            max_queued: None,
            invoke_timeout_secs: 60.0,
        };
        let addr = c.listen_socket_addr().unwrap();
        assert_eq!(addr.port(), 8790);
    }

    #[test]
    fn test_listen_socket_addr_without_port_appends_8790() {
        let c = Config {
            listen_http: "0.0.0.0".to_string(),
            backend_base_url: String::new(),
            auth_secret: None,
            max_concurrent: 64,
            max_queued: None,
            invoke_timeout_secs: 60.0,
        };
        let addr = c.listen_socket_addr().unwrap();
        assert_eq!(addr.port(), 8790);
    }

    #[test]
    fn test_listen_socket_addr_invalid_returns_err() {
        let c = Config {
            listen_http: "not-an-address".to_string(),
            backend_base_url: String::new(),
            auth_secret: None,
            max_concurrent: 64,
            max_queued: None,
            invoke_timeout_secs: 60.0,
        };
        assert!(c.listen_socket_addr().is_err());
    }
}
