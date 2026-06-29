// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Command-line interface, mirroring the Go fast-time-server flags.

use clap::{Parser, ValueEnum};
use std::ffi::OsString;

const GO_STYLE_FLAGS: &[&str] = &[
    "addr",
    "allowed-hosts",
    "auth-token",
    "listen",
    "log-level",
    "port",
    "public-url",
    "transport",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
#[value(rename_all = "lowercase")]
pub(crate) enum Transport {
    /// Serve MCP over stdin/stdout.
    Stdio,
    /// Legacy HTTP+SSE transport.
    Sse,
    /// Streamable HTTP transport.
    Http,
    /// SSE, Streamable HTTP, REST, and benchmark routes.
    Dual,
    /// REST routes only.
    Rest,
}

/// Ultra-fast MCP test server with time tools.
///
/// With no arguments it serves every HTTP route on `BIND_ADDRESS`
/// (default `0.0.0.0:8080`), matching the Go fast-time-server image.
#[derive(Debug, Parser)]
#[command(name = "fast-time-server", version, about)]
pub(crate) struct Cli {
    /// Transport: stdio | sse | http | dual | rest.
    #[arg(long, value_enum, default_value_t = Transport::Dual, env = "TRANSPORT")]
    pub transport: Transport,

    /// Full listen address (host:port); overrides --listen/--port. Defaults to
    /// the BIND_ADDRESS env var, then falls back to --listen:--port.
    #[arg(long, default_value = "", env = "BIND_ADDRESS")]
    pub addr: String,

    /// Listen interface for HTTP transports.
    #[arg(long, default_value = "0.0.0.0")]
    pub listen: String,

    /// TCP port for HTTP transports.
    #[arg(long, default_value_t = 8080)]
    pub port: u16,

    /// External base URL advertised to SSE clients (accepted for Go parity).
    #[arg(long, default_value = "")]
    pub public_url: String,

    /// Comma-separated Host values accepted by Streamable HTTP.
    #[arg(long, default_value = "", env = "MCP_ALLOWED_HOSTS")]
    pub allowed_hosts: String,

    /// Bearer token required on HTTP requests (except /health and /version).
    #[arg(long, default_value = "", env = "AUTH_TOKEN")]
    pub auth_token: String,

    /// Logging level: debug | info | warn | error | none.
    #[arg(long, default_value = "info")]
    pub log_level: String,
}

impl Cli {
    /// Parse CLI args while accepting Go-style single-dash long flags like
    /// `-transport=dual`.
    pub(crate) fn parse_compat() -> Self {
        Self::parse_from(normalize_go_style_args(std::env::args_os()))
    }

    /// Resolve the HTTP listen address: `--addr`/`BIND_ADDRESS` wins, otherwise
    /// `--listen:--port`.
    pub(crate) fn effective_addr(&self) -> String {
        if self.addr.is_empty() {
            format!("{}:{}", self.listen, self.port)
        } else {
            self.addr.clone()
        }
    }

    /// Optional Bearer token (None when empty/unset).
    pub(crate) fn auth_token(&self) -> Option<String> {
        if self.auth_token.is_empty() {
            None
        } else {
            Some(self.auth_token.clone())
        }
    }

    /// `tracing` env-filter directive derived from `--log-level`
    /// (`none` maps to `off`).
    pub(crate) fn log_directive(&self) -> &str {
        match self.log_level.as_str() {
            "none" => "off",
            other => other,
        }
    }
}

fn normalize_go_style_args<I>(args: I) -> Vec<OsString>
where
    I: IntoIterator<Item = OsString>,
{
    args.into_iter()
        .map(|arg| {
            let Some(arg_str) = arg.to_str() else {
                return arg;
            };
            normalize_go_style_arg(arg_str).map_or(arg, OsString::from)
        })
        .collect()
}

fn normalize_go_style_arg(arg: &str) -> Option<String> {
    if !arg.starts_with('-') || arg.starts_with("--") {
        return None;
    }

    let body = &arg[1..];
    let name = body.split_once('=').map_or(body, |(name, _)| name);
    GO_STYLE_FLAGS.contains(&name).then(|| format!("--{body}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_effective_addr_prefers_addr() {
        let cli = Cli {
            transport: Transport::Dual,
            addr: "127.0.0.1:3000".into(),
            listen: "0.0.0.0".into(),
            port: 9080,
            public_url: String::new(),
            allowed_hosts: String::new(),
            auth_token: String::new(),
            log_level: "info".into(),
        };
        assert_eq!(cli.effective_addr(), "127.0.0.1:3000");
    }

    #[test]
    fn test_effective_addr_falls_back_to_listen_port() {
        let cli = Cli {
            transport: Transport::Dual,
            addr: String::new(),
            listen: "0.0.0.0".into(),
            port: 8080,
            public_url: String::new(),
            allowed_hosts: String::new(),
            auth_token: String::new(),
            log_level: "none".into(),
        };
        assert_eq!(cli.effective_addr(), "0.0.0.0:8080");
        assert_eq!(cli.log_directive(), "off");
        assert_eq!(cli.auth_token(), None);
    }

    #[test]
    fn test_parse_accepts_go_style_single_dash_flags() {
        let cli = Cli::parse_from(normalize_go_style_args([
            OsString::from("fast-time-server"),
            OsString::from("-transport=dual"),
            OsString::from("-listen=127.0.0.1"),
            OsString::from("-port=8080"),
            OsString::from("-allowed-hosts=time.example.com"),
            OsString::from("-log-level=none"),
        ]));

        assert_eq!(cli.transport, Transport::Dual);
        assert_eq!(cli.effective_addr(), "127.0.0.1:8080");
        assert_eq!(cli.allowed_hosts, "time.example.com");
        assert_eq!(cli.log_directive(), "off");
    }
}
