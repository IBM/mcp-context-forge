// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! ContextForge MCP Dataplane
//!
//! High-performance MCP protocol dataplane built on Praxis proxy framework.
//! Provides stateless, horizontally scalable MCP request handling with
//! CPEX-based authorization and gRPC control plane integration.
//!
//! ## Architecture
//!
//! 7-filter pipeline:
//! 1. McpFilter (Praxis built-in) - MCP protocol validation
//! 2. cf_control_plane_data - Fetch session + VS config from control plane
//! 3. CPEX Policy #1 - Pre-routing authorization (virtual server access)
//! 4. cf_tools_router - Routing decision (gateway vs upstream)
//! 5. CPEX Policy #2 - Post-routing authorization (gateway/upstream access)
//! 6. cf_mcp_broker - Gateway execution (conditional on route=gateway)
//! 7. cf_upstream_proxy - Upstream forwarding (conditional on route=upstream)
//!
//! ## Configuration
//!
//! All configuration is via YAML file (praxis_cf_dataplane.yaml).
//! See docs/configuration.md for details.

pub mod filters;

use praxis_filter::export_filters;

// Export filters for Praxis auto-discovery
// The build.rs in the Praxis server will discover this crate via
// [package.metadata.praxis-filters] and generate registration code
export_filters! {
    http "cf_control_plane_data" => filters::ControlPlaneDataFilter::from_config,
    http "cf_tools_router" => filters::ToolsRouterFilter::from_config,
    http "cf_mcp_broker" => filters::McpBrokerFilter::from_config,
    http "cf_upstream_proxy" => filters::UpstreamProxyFilter::from_config,
}