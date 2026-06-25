// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

pub(crate) const DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:9080";
pub(crate) const APP_NAME: &str = "fast-time-server";
pub(crate) const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
/// Latest protocol version advertised by the legacy SSE shim and `/version`.
/// The `/mcp` Streamable HTTP transport negotiates independently inside rmcp.
pub(crate) const MCP_PROTOCOL_VERSION: &str = "2025-11-25";
/// Protocol versions echoed back during legacy SSE initialize negotiation;
/// anything else falls back to `MCP_PROTOCOL_VERSION`.
pub(crate) const SUPPORTED_PROTOCOL_VERSIONS: &[&str] = &[
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    MCP_PROTOCOL_VERSION,
];
/// Session id header for the `/mcp` Streamable HTTP transport; used by the
/// session-cap gate to tell session-creating requests from existing ones.
pub(crate) const SESSION_HEADER: &str = "mcp-session-id";
/// Cap on concurrent sessions, applied to both the legacy SSE transport and the
/// `/mcp` Streamable HTTP transport.
pub(crate) const MAX_ACTIVE_SESSIONS: usize = 10_000;
pub(crate) const SSE_CHANNEL_CAPACITY: usize = 64;
pub(crate) const MAX_DELAY_MS: u64 = 60_000;
