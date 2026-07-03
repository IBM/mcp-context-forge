// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! MCP Broker Filter
//!
//! Handles gateway tool execution and catalog management.
//!
//! ## Responsibilities
//!
//! 1. **Conditional Execution**: Only executes if `mcp.route = "gateway"`
//! 2. **tools/call**: Execute tool on gateway's MCP server via control plane
//! 3. **tools/list**: Fetch and merge gateway + upstream catalogs
//! 4. **initialize**: Return gateway capabilities
//! 5. **ping**: Return pong
//! 6. **Short-circuit**: Return `Reject(200, response)` to terminate pipeline
//!
//! ## Metadata Read
//!
//! - `mcp.route` - Routing decision (from cf_tools_router)
//! - `mcp.method` - MCP method (from McpFilter)
//! - `mcp.jsonrpc_id` - Request ID (from McpFilter)
//! - `mcp.gateway_id` - Gateway ID (from cf_tools_router, if tools/call)
//! - `mcp.gateway_tool` - Gateway tool name (from cf_tools_router, if tools/call)
//! - `mcp.tool_sources` - Comma-separated sources (from cf_tools_router, if tools/list)
//! - `mcp.session_id` - Session ID (from cf_control_plane_data)
//!
//! ## Does NOT
//!
//! - Execute if route != "gateway"
//! - Modify request (reads from metadata)
//! - Continue pipeline (always short-circuits with response)
//!
//! ## Configuration
//!
//! Configured via praxis_cf_dataplane.yaml:
//! ```yaml
//! - filter: cf_mcp_broker
//!   config:
//!     grpc_endpoint: http://localhost:50051
//!     condition:
//!       metadata_equals:
//!         mcp.route: gateway
//! ```

use async_trait::async_trait;
use praxis_filter::{FilterAction, FilterError, HttpFilter, HttpFilterContext, Rejection};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
struct Config {
    grpc_endpoint: String,
}

/// MCP Broker Filter
///
/// This filter handles gateway tool execution and catalog merging.
/// Praxis handles conditional execution via YAML config.
pub struct McpBrokerFilter {
    // Will be used to initialize gRPC client for control plane communication
    #[allow(dead_code)]
    grpc_endpoint: String,
    // TODO: Add gRPC client once Praxis gRPC integration is documented
    // grpc_client: ControlPlaneServiceClient<Channel>,
}

impl McpBrokerFilter {
    /// Factory method for Praxis auto-discovery
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let cfg: Config = serde_yaml::from_value(config.clone())
            .map_err(|e| FilterError::from(e.to_string()))?;
        
        Ok(Box::new(Self {
            grpc_endpoint: cfg.grpc_endpoint,
        }))
    }

    /// Handle initialize
    fn handle_initialize(&self, request_id: Value) -> Value {
        json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "serverInfo": {
                    "name": "praxis_cf_dataplane",
                    "version": env!("CARGO_PKG_VERSION")
                }
            }
        })
    }

    /// Handle ping
    fn handle_ping(&self, request_id: Value) -> Value {
        json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        })
    }
}

#[async_trait]
impl HttpFilter for McpBrokerFilter {
    fn name(&self) -> &'static str {
        "cf_mcp_broker"
    }

    async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction, FilterError> {
        // Praxis handles conditional execution via YAML config
        // This filter only executes if mcp.route = "gateway"

        // Read metadata
        let method = ctx.get_metadata("mcp.method")
            .ok_or_else(|| FilterError::from("Missing mcp.method metadata"))?;

        let request_id = ctx.get_metadata("mcp.jsonrpc_id")
            .and_then(|id| serde_json::from_str(&id).ok())
            .unwrap_or(json!(null));

        // Handle method
        let response_json = match method.as_ref() {
            "ping" => self.handle_ping(request_id),
            "initialize" => self.handle_initialize(request_id),
            
            "tools/list" => {
                // TODO: Call control plane gRPC to list and merge tools
                // let gateway_tools = self.grpc_client.list_gateway_tools(...).await?;
                // let upstream_tools = self.grpc_client.list_upstream_tools(...).await?;
                // Merge and return combined catalog
                
                eprintln!("STUB: cf_mcp_broker handling tools/list");
                json!({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": []
                    }
                })
            }
            
            "tools/call" => {
                // TODO: Call control plane gRPC to execute tool on gateway
                // let gateway_id = ctx.get_metadata("mcp.gateway_id").unwrap();
                // let gateway_tool = ctx.get_metadata("mcp.gateway_tool").unwrap();
                // let result = self.grpc_client.execute_tool(...).await?;
                
                eprintln!("STUB: cf_mcp_broker handling tools/call");
                json!({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32603,
                        "message": "Tool execution not yet implemented"
                    }
                })
            }
            
            _ => {
                json!({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": format!("Method not found: {}", method)
                    }
                })
            }
        };

        // Serialize response
        let response_body = serde_json::to_string(&response_json)
            .map_err(|e| FilterError::from(format!("Failed to serialize response: {}", e)))?;

        // Short-circuit with response (terminates filter pipeline)
        Ok(FilterAction::Reject(
            Rejection::status(200)
                .with_header("content-type", "application/json")
                .with_body(response_body)
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_handle_ping() {
        let filter = McpBrokerFilter::new().unwrap();
        let response = filter.handle_ping(json!("test-id"));
        assert_eq!(response["jsonrpc"], "2.0");
        assert_eq!(response["id"], "test-id");
        assert!(response["result"].is_object());
    }

    #[test]
    fn test_handle_initialize() {
        let filter = McpBrokerFilter::new().unwrap();
        let response = filter.handle_initialize(json!("test-id"));
        assert_eq!(response["jsonrpc"], "2.0");
        assert_eq!(response["id"], "test-id");
        assert_eq!(response["result"]["protocolVersion"], "2024-11-05");
        assert_eq!(response["result"]["serverInfo"]["name"], "praxis_cf_dataplane");
    }
}