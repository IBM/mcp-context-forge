// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Control Plane Data Filter
//!
//! Fetches session authentication and virtual server configuration from the control plane
//! and populates filter metadata for downstream CPEX policy evaluation.
//!
//! ## Responsibilities
//!
//! 1. Extract JWT token from Authorization header
//! 2. Extract virtual server ID from request path (/server/{server_id}/mcp)
//! 3. Call control plane gRPC to authenticate session
//! 4. Call control plane gRPC to fetch virtual server config
//! 5. Write ALL data to filter metadata for CPEX consumption
//!
//! ## Metadata Written
//!
//! - `mcp.session_id` - Unique session identifier
//! - `mcp.user_email` - User's email address
//! - `mcp.teams` - Comma-separated team memberships
//! - `mcp.is_admin` - Admin flag ("true" or "false")
//! - `mcp.virtual_server_id` - Virtual server identifier
//! - `mcp.virtual_server_tools` - JSON array of exposed tool names
//! - `mcp.virtual_server_access_policy` - JSON object with RBAC rules
//!
//! ## Does NOT
//!
//! - Make authorization decisions (that's CPEX's job)
//! - Modify request/response (pure data fetching)
//! - Implement caching (Praxis handles this via YAML config)
//!
//! ## Configuration
//!
//! Configured via praxis_cf_dataplane.yaml:
//! ```yaml
//! - filter: cf_control_plane_data
//!   config:
//!     grpc_endpoint: http://localhost:50051
//!     session_cache_ttl: 300
//!     session_cache_size: 10000
//! ```

use async_trait::async_trait;
use praxis_filter::{FilterAction, FilterError, HttpFilter, HttpFilterContext, Request};
use serde::Deserialize;

#[derive(Deserialize)]
struct Config {
    grpc_endpoint: String,
    #[serde(default = "default_session_cache_ttl")]
    // Will be used for session cache configuration once Praxis gRPC client is implemented
    #[allow(dead_code)]
    session_cache_ttl: u64,
    #[serde(default = "default_session_cache_size")]
    // Will be used for session cache configuration once Praxis gRPC client is implemented
    #[allow(dead_code)]
    session_cache_size: usize,
}

fn default_session_cache_ttl() -> u64 { 300 }
fn default_session_cache_size() -> usize { 10000 }

/// Control Plane Data Filter
///
/// This filter is a thin wrapper around control plane gRPC calls.
/// All caching, connection pooling, and retry logic is handled by Praxis.
pub struct ControlPlaneDataFilter {
    // Will be used to initialize gRPC client for control plane communication
    #[allow(dead_code)]
    grpc_endpoint: String,
    // TODO: Add gRPC client once Praxis gRPC integration is documented
    // grpc_client: ControlPlaneServiceClient<Channel>,
}

impl ControlPlaneDataFilter {
    /// Factory method for Praxis auto-discovery
    ///
    /// Praxis calls this with config from YAML file during filter registration.
    pub fn from_config(config: &serde_yaml::Value) -> Result<Box<dyn HttpFilter>, FilterError> {
        let cfg: Config = serde_yaml::from_value(config.clone())
            .map_err(|e| FilterError::from(e.to_string()))?;
        
        // TODO: Create gRPC client once Praxis gRPC integration is documented
        // let grpc_client = ControlPlaneServiceClient::connect(&cfg.grpc_endpoint)
        //     .await
        //     .map_err(|e| FilterError::from(e.to_string()))?;
        
        Ok(Box::new(Self {
            grpc_endpoint: cfg.grpc_endpoint,
            // grpc_client,
        }))
    }

    /// Extract JWT token from Authorization header
    fn extract_token(&self, req: &Request) -> Option<String> {
        req.headers
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.strip_prefix("Bearer "))
            .map(|s| s.to_string())
    }

    /// Extract virtual server ID from request path
    /// Path format: /server/{server_id}/mcp
    fn extract_virtual_server_id(&self, req: &Request) -> Option<String> {
        let path = req.uri.path();
        let parts: Vec<&str> = path.split('/').collect();
        
        // Expected: ["", "server", "{server_id}", "mcp"]
        if parts.len() >= 3 && parts[1] == "server" {
            Some(parts[2].to_string())
        } else {
            None
        }
    }
}

#[async_trait]
impl HttpFilter for ControlPlaneDataFilter {
    fn name(&self) -> &'static str {
        "cf_control_plane_data"
    }

    async fn on_request(&self, ctx: &mut HttpFilterContext<'_>) -> Result<FilterAction, FilterError> {
        let req = &ctx.request;

        // Extract JWT token
        let token = self.extract_token(req).ok_or_else(|| {
            FilterError::from("Missing or invalid Authorization header")
        })?;

        // Extract virtual server ID
        let virtual_server_id = self.extract_virtual_server_id(req).ok_or_else(|| {
            FilterError::from("Invalid request path: expected /server/{server_id}/mcp")
        })?;

        // TODO: Call control plane gRPC to authenticate session
        // let auth_response = self.grpc_client.authenticate(AuthenticateRequest {
        //     bearer_token: token,
        // }).await?;
        //
        // if !auth_response.authenticated {
        //     return Ok(FilterAction::Reject(
        //         Response::builder()
        //             .status(StatusCode::UNAUTHORIZED)
        //             .body(auth_response.error_message.unwrap_or_default())
        //             .unwrap()
        //     ));
        // }
        //
        // let session = auth_response.session_context.unwrap();

        // TODO: Call control plane gRPC to fetch virtual server config
        // let vs_response = self.grpc_client.get_virtual_server_config(
        //     GetVirtualServerConfigRequest {
        //         virtual_server_id: virtual_server_id.clone(),
        //     }
        // ).await?;
        //
        // if !vs_response.found {
        //     return Ok(FilterAction::Reject(
        //         Response::builder()
        //             .status(StatusCode::NOT_FOUND)
        //             .body(format!("Virtual server not found: {}", virtual_server_id))
        //             .unwrap()
        //     ));
        // }
        //
        // let vs_config = vs_response.config.unwrap();

        // TODO: Write session metadata
        // ctx.set_metadata("mcp.session_id", &session.session_id)?;
        // ctx.set_metadata("mcp.user_email", &session.user_email)?;
        // ctx.set_metadata("mcp.teams", &session.teams.join(","))?;
        // ctx.set_metadata("mcp.is_admin", if session.is_admin { "true" } else { "false" })?;

        // TODO: Write virtual server metadata
        // ctx.set_metadata("mcp.virtual_server_id", &virtual_server_id)?;
        // ctx.set_metadata("mcp.virtual_server_tools", &serde_json::to_string(&vs_config.tools)?)?;
        // ctx.set_metadata("mcp.virtual_server_access_policy", &serde_json::to_string(&vs_config.access_policy)?)?;

        // TEMPORARY: Stub implementation until Praxis gRPC integration is documented
        eprintln!("STUB: cf_control_plane_data filter called");
        eprintln!("  Token: {}", token);
        eprintln!("  Virtual Server ID: {}", virtual_server_id);
        
        Ok(FilterAction::Continue)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_virtual_server_id() {
        let filter = ControlPlaneDataFilter::new().unwrap();

        let req = Request::builder()
            .uri("/server/vs-123/mcp")
            .body(())
            .unwrap();

        assert_eq!(
            filter.extract_virtual_server_id(&req),
            Some("vs-123".to_string())
        );
    }

    #[test]
    fn test_extract_token() {
        let filter = ControlPlaneDataFilter::new().unwrap();

        let req = Request::builder()
            .uri("/server/vs-123/mcp")
            .header("authorization", "Bearer test-token-123")
            .body(())
            .unwrap();

        assert_eq!(
            filter.extract_token(&req),
            Some("test-token-123".to_string())
        );
    }
}