// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Tools Router Filter
//!
//! Determines routing for MCP requests based on method and tool name.
//!
//! ## Responsibilities
//!
//! 1. Read MCP method and tool name from metadata (set by McpFilter)
//! 2. Call control plane gRPC to resolve tool routing
//! 3. Write routing decision to metadata for downstream filters
//!
//! ## Metadata Read
//!
//! - `mcp.method` - MCP method (from McpFilter)
//! - `mcp.name` - Tool name (from McpFilter, if tools/call)
//! - `mcp.virtual_server_id` - Virtual server ID (from cf_control_plane_data)
//!
//! ## Metadata Written
//!
//! - `mcp.route` - Routing decision: "gateway" or "upstream"
//! - `mcp.gateway_id` - Gateway ID (if route=gateway)
//! - `mcp.gateway_tool` - Gateway tool name (if route=gateway)
//! - `mcp.upstream_url` - Upstream server URL (if route=upstream)
//! - `mcp.upstream_tool` - Upstream tool name (if route=upstream)
//! - `mcp.tool_sources` - Comma-separated sources for tools/list
//!
//! ## Routing Logic
//!
//! - `tools/call` → Call control plane to resolve tool to gateway or upstream
//! - `tools/list` → Route to gateway (broker will merge catalogs)
//! - `resources/*`, `prompts/*` → Route to upstream
//! - `initialize`, `ping` → Route to gateway
//!
//! ## Configuration
//!
//! Configured via praxis_cf_dataplane.yaml:
//! ```yaml
//! - filter: cf_tools_router
//!   config:
//!     grpc_endpoint: http://localhost:50051
//! ```

use async_trait::async_trait;
use praxis_filter::{FilterAction, FilterError, HttpFilter, HttpFilterContext, Rejection};
use serde::Deserialize;

#[derive(Deserialize)]
struct Config {
    grpc_endpoint: String,
}

/// Tools Router Filter
///
/// This filter makes routing decisions based on MCP method and tool name.
/// All gRPC communication is handled by Praxis via YAML config.
pub struct ToolsRouterFilter {
    // Will be used to initialize gRPC client for control plane communication
    #[allow(dead_code)]
    grpc_endpoint: String,
    // TODO: Add gRPC client once Praxis gRPC integration is documented
    // grpc_client: ControlPlaneServiceClient<Channel>,
}

impl ToolsRouterFilter {
    /// Factory method for Praxis auto-discovery
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let cfg: Config = serde_yaml::from_value(config.clone())
            .map_err(|e| FilterError::from(e.to_string()))?;
        
        Ok(Box::new(Self {
            grpc_endpoint: cfg.grpc_endpoint,
        }))
    }
}

#[async_trait]
impl HttpFilter for ToolsRouterFilter {
    fn name(&self) -> &'static str {
        "cf_tools_router"
    }

    async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction, FilterError> {
        // Read metadata from previous filters
        let method = ctx.get_metadata("mcp.method")
            .ok_or_else(|| FilterError::from("Missing mcp.method metadata"))?;
        
        let virtual_server_id = ctx.get_metadata("mcp.virtual_server_id")
            .ok_or_else(|| FilterError::from("Missing mcp.virtual_server_id metadata"))?;

        // Route based on method
        match method.as_ref() {
            "tools/call" => {
                // Get tool name
                let tool_name = ctx.get_metadata("mcp.name")
                    .ok_or_else(|| FilterError::from("Missing mcp.name metadata for tools/call"))?;

                // TODO: Call control plane gRPC to resolve tool routing
                // let response = self.grpc_client.resolve_tool_call(ResolveToolCallRequest {
                //     virtual_server_id: virtual_server_id.clone(),
                //     tool_name: tool_name.clone(),
                // }).await?;
                //
                // if !response.found {
                //     return Ok(FilterAction::Reject(
                //         Response::builder()
                //             .status(StatusCode::NOT_FOUND)
                //             .body(format!("Tool not found: {}", tool_name))
                //             .unwrap()
                //     ));
                // }
                //
                // let route = response.route.unwrap();
                //
                // match route.source {
                //     ToolSource::Gateway => {
                //         ctx.set_metadata("mcp.route", "gateway")?;
                //         ctx.set_metadata("mcp.gateway_id", &route.gateway_id.unwrap())?;
                //         ctx.set_metadata("mcp.gateway_tool", &route.gateway_tool_name.unwrap())?;
                //     }
                //     ToolSource::Upstream => {
                //         ctx.set_metadata("mcp.route", "upstream")?;
                //         ctx.set_metadata("mcp.upstream_url", &route.upstream_url.unwrap())?;
                //         ctx.set_metadata("mcp.upstream_tool", &route.upstream_tool_name.unwrap())?;
                //     }
                // }

                // TEMPORARY: Stub implementation
                eprintln!("STUB: cf_tools_router resolving tool call");
                eprintln!("  Virtual Server: {}", virtual_server_id);
                eprintln!("  Tool: {}", tool_name);
                ctx.set_metadata("mcp.route", "gateway");
            }

            "tools/list" => {
                // Route to gateway (broker will merge catalogs from all sources)
                ctx.set_metadata("mcp.route", "gateway");
                ctx.set_metadata("mcp.tool_sources", "gateway,upstream");
            }

            "resources/list" | "resources/read" | "prompts/list" | "prompts/get" => {
                // Route to upstream
                ctx.set_metadata("mcp.route", "upstream");
            }

            "initialize" | "ping" => {
                // Route to gateway
                ctx.set_metadata("mcp.route", "gateway");
            }

            _ => {
                return Ok(FilterAction::Reject(Rejection::status(501)));
            }
        }

        Ok(FilterAction::Continue)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_routing_logic() {
        // Test that routing decisions are made correctly
        // Full tests require Praxis test harness
    }
}