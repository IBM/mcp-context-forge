// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Custom filters for MCP request processing
//!
//! This module provides four custom filters that integrate with Praxis and CPEX:
//!
//! - `ControlPlaneDataFilter` - Fetches session and virtual server config from control plane
//! - `ToolsRouterFilter` - Routes requests to gateway or upstream based on tool resolution
//! - `McpBrokerFilter` - Handles gateway tool execution (conditional on route=gateway)
//! - `UpstreamProxyFilter` - Forwards requests to upstream servers (conditional on route=upstream)
//!
//! See `docs/architecture.md` for complete architecture documentation.
//! See `docs/filter-chain-examples.md` for detailed execution flow examples.

pub mod control_plane_data;
pub mod tools_router;
pub mod mcp_broker;
pub mod upstream_proxy;

pub use control_plane_data::ControlPlaneDataFilter;
pub use tools_router::ToolsRouterFilter;
pub use mcp_broker::McpBrokerFilter;
pub use upstream_proxy::UpstreamProxyFilter;