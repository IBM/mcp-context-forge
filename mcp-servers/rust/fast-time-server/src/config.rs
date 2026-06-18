// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

pub(crate) const DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:9080";
pub(crate) const APP_NAME: &str = "fast-time-server";
pub(crate) const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
pub(crate) const MCP_PROTOCOL_VERSION: &str = "2025-11-25";
pub(crate) const SESSION_HEADER: &str = "mcp-session-id";
pub(crate) const MAX_ACTIVE_SESSIONS: usize = 10_000;
pub(crate) const SSE_CHANNEL_CAPACITY: usize = 64;
pub(crate) const MAX_DELAY_MS: u64 = 60_000;
