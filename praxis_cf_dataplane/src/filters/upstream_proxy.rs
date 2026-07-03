// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Upstream Proxy Filter
//!
//! Forwards MCP requests to upstream MCP servers.
//!
//! ## Responsibilities
//!
//! 1. **Conditional Execution**: Only executes if `mcp.route = "upstream"`
//! 2. **Request Forwarding**: Forward request to upstream MCP server
//! 3. **Tool Name Translation**: Translate virtual tool name to upstream tool name (if different)
//! 4. **Response Passthrough**: Return upstream response as-is
//! 5. **Short-circuit**: Return `Reject(200, upstream_response)` to terminate pipeline
//!
//! ## Metadata Read
//!
//! - `mcp.route` - Routing decision (from cf_tools_router)
//! - `mcp.upstream_url` - Upstream server URL (from cf_tools_router)
//! - `mcp.upstream_tool` - Upstream tool name (from cf_tools_router, if tools/call)
//! - `mcp.method` - MCP method (from McpFilter)
//!
//! ## Does NOT
//!
//! - Execute if route != "upstream"
//! - Modify response (passes through as-is)
//! - Continue pipeline (always short-circuits with response)
//!
//! ## Configuration
//!
//! Configured via praxis_cf_dataplane.yaml:
//! ```yaml
//! - filter: cf_upstream_proxy
//!   config:
//!     timeout_seconds: 30
//!     max_retries: 3
//!     condition:
//!       metadata_equals:
//!         mcp.route: upstream
//! ```

use async_trait::async_trait;
use praxis_filter::{FilterAction, FilterError, HttpFilter, HttpFilterContext, Rejection};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
struct Config {
    #[serde(default = "default_timeout")]
    timeout_seconds: u64,
    #[serde(default = "default_max_retries")]
    max_retries: u32,
}

fn default_timeout() -> u64 { 30 }
fn default_max_retries() -> u32 { 3 }

/// Upstream Proxy Filter
///
/// This filter forwards requests to upstream MCP servers.
/// Praxis handles HTTP client, retries, timeouts, and conditional execution via YAML config.
pub struct UpstreamProxyFilter {
    // Will be used for HTTP client timeout configuration once Praxis upstream forwarding is implemented
    #[allow(dead_code)]
    timeout_seconds: u64,
    // Will be used for HTTP client retry configuration once Praxis upstream forwarding is implemented
    #[allow(dead_code)]
    max_retries: u32,
    // TODO: Add HTTP client once Praxis upstream forwarding is documented
    // Praxis load_balancer filter may handle this automatically
}

impl UpstreamProxyFilter {
    /// Factory method for Praxis auto-discovery
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let cfg: Config = serde_yaml::from_value(config.clone())
            .map_err(|e| FilterError::from(e.to_string()))?;
        
        Ok(Box::new(Self {
            timeout_seconds: cfg.timeout_seconds,
            max_retries: cfg.max_retries,
        }))
    }

    /// Translate tool name in request if needed
    // Will be used for tool name translation when forwarding to upstream MCP servers
    #[allow(dead_code)]
    fn translate_tool_name(&self, request_body: &mut Value, upstream_tool: Option<&str>) {
        if let Some(upstream_tool_name) = upstream_tool {
            // For tools/call, replace the tool name in params
            if let Some(params) = request_body.get_mut("params") {
                if let Some(params_obj) = params.as_object_mut() {
                    params_obj.insert("name".to_string(), json!(upstream_tool_name));
                }
            }
        }
    }
}

#[async_trait]
impl HttpFilter for UpstreamProxyFilter {
    fn name(&self) -> &'static str {
        "cf_upstream_proxy"
    }

    async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction, FilterError> {
        // Praxis handles conditional execution via YAML config
        // This filter only executes if mcp.route = "upstream"

        // Read metadata
        let upstream_url = ctx.get_metadata("mcp.upstream_url")
            .ok_or_else(|| FilterError::from("Missing mcp.upstream_url metadata"))?;

        let upstream_tool = ctx.get_metadata("mcp.upstream_tool");
        let method = ctx.get_metadata("mcp.method");

        // TODO: Body parsing needs to happen in on_request_body hook
        // Praxis Request struct only has headers/method/uri, not body
        // For now, forward request as-is without body translation

        // TODO: Forward request to upstream using Praxis HTTP client
        // let response = self.http_client
        //     .post(&upstream_url)
        //     .json(&request_body)
        //     .send()
        //     .await?;
        //
        // let status = response.status();
        // let body = response.bytes().await?;
        //
        // return Ok(FilterAction::Reject(
        //     Response::builder()
        //         .status(status)
        //         .header("content-type", "application/json")
        //         .body(body.to_vec())
        //         .unwrap()
        // ));

        // TEMPORARY: Stub implementation
        eprintln!("STUB: cf_upstream_proxy forwarding to {}", upstream_url);
        eprintln!("  Method: {:?}", method);
        eprintln!("  Tool translation: {:?}", upstream_tool);

        let error_response = json!({
            "jsonrpc": "2.0",
            "id": null,
            "error": {
                "code": -32603,
                "message": "Upstream proxy not yet implemented"
            }
        });

        let error_body = serde_json::to_string(&error_response)
            .map_err(|e| FilterError::from(format!("Failed to serialize error: {}", e)))?;

        Ok(FilterAction::Reject(
            Rejection::status(501)
                .with_header("content-type", "application/json")
                .with_body(error_body)
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_translate_tool_name() {
        let filter = UpstreamProxyFilter::new().unwrap();

        let mut request = json!({
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "tools/call",
            "params": {
                "name": "virtual_tool",
                "arguments": {}
            }
        });

        filter.translate_tool_name(&mut request, Some("upstream_tool"));

        assert_eq!(
            request["params"]["name"],
            "upstream_tool"
        );
    }

    #[test]
    fn test_translate_tool_name_no_change() {
        let filter = UpstreamProxyFilter::new().unwrap();

        let mut request = json!({
            "jsonrpc": "2.0",
            "id": "test-id",
            "method": "tools/call",
            "params": {
                "name": "tool_name",
                "arguments": {}
            }
        });

        let original = request.clone();
        filter.translate_tool_name(&mut request, None);

        assert_eq!(request, original);
    }
}