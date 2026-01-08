// fast-test-server - Ultra-fast MCP server for performance testing
//
// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// This server provides minimal, blazing-fast tools for load testing:
// - echo: Echoes back whatever you send it
// - get_system_time: Returns current time in specified timezone
//
// Transport: Streamable HTTP (no auth)
// Default: http://127.0.0.1:9080/mcp

use std::env;
use std::sync::Arc;

use axum::Router;
use chrono::{DateTime, FixedOffset, Utc};
use rmcp::{
    ErrorData as McpError, RoleServer, ServerHandler,
    handler::server::router::tool::ToolRouter,
    model::*,
    schemars,
    service::RequestContext,
    tool, tool_handler, tool_router,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService,
        session::local::LocalSessionManager,
    },
};
use serde_json::json;
use tokio::sync::Mutex;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

const DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:9080";
const APP_NAME: &str = "fast-test-server";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");

// ============================================================================
// Request/Response Schemas
// ============================================================================

#[derive(Debug, serde::Deserialize, schemars::JsonSchema)]
pub struct EchoRequest {
    /// The message to echo back
    pub message: String,
}

#[derive(Debug, serde::Deserialize, schemars::JsonSchema)]
pub struct GetTimeRequest {
    /// IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Defaults to UTC.
    #[serde(default)]
    pub timezone: Option<String>,
}

// ============================================================================
// FastTestServer Implementation
// ============================================================================

#[derive(Clone)]
pub struct FastTestServer {
    tool_router: ToolRouter<FastTestServer>,
    request_count: Arc<Mutex<u64>>,
}

#[tool_router]
impl FastTestServer {
    pub fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
            request_count: Arc::new(Mutex::new(0)),
        }
    }

    /// Echo back whatever message is sent
    #[tool(description = "Echo back the provided message. Useful for testing connectivity and latency.")]
    async fn echo(
        &self,
        rmcp::handler::server::wrapper::Parameters(req): rmcp::handler::server::wrapper::Parameters<EchoRequest>,
    ) -> Result<CallToolResult, McpError> {
        let mut count = self.request_count.lock().await;
        *count += 1;

        Ok(CallToolResult::success(vec![Content::text(&req.message)]))
    }

    /// Get current system time in specified timezone
    #[tool(description = "Get current system time in the specified IANA timezone. Defaults to UTC if no timezone provided.")]
    async fn get_system_time(
        &self,
        rmcp::handler::server::wrapper::Parameters(req): rmcp::handler::server::wrapper::Parameters<GetTimeRequest>,
    ) -> Result<CallToolResult, McpError> {
        let mut count = self.request_count.lock().await;
        *count += 1;

        let tz_name = req.timezone.as_deref().unwrap_or("UTC");

        // Get current time in UTC
        let now_utc: DateTime<Utc> = Utc::now();

        // Parse timezone and convert
        let result = match parse_timezone(tz_name) {
            Ok(offset) => {
                let local_time = now_utc.with_timezone(&offset);
                local_time.to_rfc3339()
            }
            Err(e) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "Invalid timezone '{}': {}",
                    tz_name, e
                ))]));
            }
        };

        Ok(CallToolResult::success(vec![Content::text(result)]))
    }

    /// Get server statistics
    #[tool(description = "Get server statistics including request count and uptime.")]
    async fn get_stats(&self) -> Result<CallToolResult, McpError> {
        let count = self.request_count.lock().await;

        let stats = json!({
            "server": APP_NAME,
            "version": APP_VERSION,
            "requests_handled": *count,
        });

        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&stats).unwrap_or_default(),
        )]))
    }
}

#[tool_handler]
impl ServerHandler for FastTestServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder()
                .enable_tools()
                .build(),
            server_info: Implementation::from_build_env(),
            instructions: Some(
                "Ultra-fast MCP test server. Tools: echo (echoes message), get_system_time (returns time in timezone), get_stats (server stats).".to_string()
            ),
        }
    }

    async fn initialize(
        &self,
        _request: InitializeRequestParam,
        _context: RequestContext<RoleServer>,
    ) -> Result<InitializeResult, McpError> {
        info!("Client connected to {}", APP_NAME);
        Ok(self.get_info())
    }
}

// ============================================================================
// Timezone Parsing
// ============================================================================

/// Parse an IANA timezone name and return a FixedOffset.
/// Supports common timezone names and UTC offsets.
fn parse_timezone(tz: &str) -> Result<FixedOffset, String> {
    // Handle UTC explicitly
    if tz.eq_ignore_ascii_case("UTC") || tz.eq_ignore_ascii_case("GMT") {
        return Ok(FixedOffset::east_opt(0).unwrap());
    }

    // Handle fixed offsets like "+05:30" or "-08:00"
    if tz.starts_with('+') || tz.starts_with('-') {
        return parse_offset(tz);
    }

    // Map common IANA timezone names to their typical offsets
    // Note: This is simplified and doesn't handle DST
    let offset_hours = match tz {
        // Americas
        "America/New_York" | "US/Eastern" => -5,
        "America/Chicago" | "US/Central" => -6,
        "America/Denver" | "US/Mountain" => -7,
        "America/Los_Angeles" | "US/Pacific" => -8,
        "America/Anchorage" | "US/Alaska" => -9,
        "Pacific/Honolulu" | "US/Hawaii" => -10,
        "America/Toronto" => -5,
        "America/Vancouver" => -8,
        "America/Mexico_City" => -6,
        "America/Sao_Paulo" => -3,
        "America/Buenos_Aires" | "America/Argentina/Buenos_Aires" => -3,

        // Europe
        "Europe/London" | "Europe/Dublin" | "GB" => 0,
        "Europe/Paris" | "Europe/Berlin" | "Europe/Rome" | "Europe/Madrid" => 1,
        "Europe/Moscow" => 3,
        "Europe/Istanbul" => 3,
        "Europe/Athens" => 2,
        "Europe/Amsterdam" => 1,
        "Europe/Zurich" => 1,

        // Asia
        "Asia/Tokyo" | "Japan" => 9,
        "Asia/Shanghai" | "Asia/Hong_Kong" | "Asia/Singapore" | "Asia/Taipei" => 8,
        "Asia/Seoul" => 9,
        "Asia/Kolkata" | "Asia/Calcutta" => 5, // Actually +5:30 but we simplify
        "Asia/Dubai" => 4,
        "Asia/Bangkok" => 7,
        "Asia/Jakarta" => 7,
        "Asia/Manila" => 8,

        // Oceania
        "Australia/Sydney" | "Australia/Melbourne" => 10,
        "Australia/Perth" => 8,
        "Pacific/Auckland" | "NZ" => 12,

        // Africa
        "Africa/Cairo" => 2,
        "Africa/Johannesburg" => 2,
        "Africa/Lagos" => 1,

        _ => return Err(format!("Unknown timezone: {}", tz)),
    };

    FixedOffset::east_opt(offset_hours * 3600)
        .ok_or_else(|| format!("Invalid offset for timezone: {}", tz))
}

/// Parse an offset string like "+05:30" or "-08:00"
fn parse_offset(s: &str) -> Result<FixedOffset, String> {
    let (sign, rest) = if s.starts_with('+') {
        (1, &s[1..])
    } else if s.starts_with('-') {
        (-1, &s[1..])
    } else {
        return Err("Offset must start with + or -".to_string());
    };

    let parts: Vec<&str> = rest.split(':').collect();
    if parts.len() != 2 {
        return Err("Offset must be in format +HH:MM or -HH:MM".to_string());
    }

    let hours: i32 = parts[0]
        .parse()
        .map_err(|_| "Invalid hours in offset")?;
    let minutes: i32 = parts[1]
        .parse()
        .map_err(|_| "Invalid minutes in offset")?;

    let total_seconds = sign * (hours * 3600 + minutes * 60);

    FixedOffset::east_opt(total_seconds)
        .ok_or_else(|| format!("Offset out of range: {}", s))
}

// ============================================================================
// Main Entry Point
// ============================================================================

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".to_string().into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Get bind address from environment or use default
    let bind_address = env::var("BIND_ADDRESS").unwrap_or_else(|_| DEFAULT_BIND_ADDRESS.to_string());

    info!("{} v{} starting...", APP_NAME, APP_VERSION);
    info!("Binding to: {}", bind_address);

    // Create cancellation token for graceful shutdown
    let ct = tokio_util::sync::CancellationToken::new();

    // Create the MCP service
    let service = StreamableHttpService::new(
        || Ok(FastTestServer::new()),
        LocalSessionManager::default().into(),
        StreamableHttpServerConfig {
            cancellation_token: ct.child_token(),
            ..Default::default()
        },
    );

    // Build router with health check endpoint and REST API for benchmarking
    let router = Router::new()
        // Health & version
        .route("/health", axum::routing::get(health_handler))
        .route("/version", axum::routing::get(version_handler))
        // REST API for benchmarking (bypasses MCP session overhead)
        .route("/api/echo", axum::routing::post(rest_echo_handler))
        .route("/api/time", axum::routing::get(rest_time_handler))
        // MCP protocol endpoint
        .nest_service("/mcp", service);

    // Bind and serve
    let tcp_listener = tokio::net::TcpListener::bind(&bind_address).await?;

    info!("MCP endpoint:   http://{}/mcp", bind_address);
    info!("REST API:       http://{}/api/echo (POST), /api/time (GET)", bind_address);
    info!("Health check:   http://{}/health", bind_address);
    info!("Version info:   http://{}/version", bind_address);
    info!("");
    info!("Benchmark with:");
    info!("  hey -n 1000000 -c 200 -m POST -T 'application/json' \\");
    info!("      -d '{{\"message\":\"hello\"}}' http://{}/api/echo", bind_address);

    axum::serve(tcp_listener, router)
        .with_graceful_shutdown(async move {
            tokio::signal::ctrl_c().await.unwrap();
            info!("Shutting down...");
            ct.cancel();
        })
        .await?;

    Ok(())
}

// Health check handler
async fn health_handler() -> axum::Json<serde_json::Value> {
    axum::Json(json!({
        "status": "healthy",
        "server": APP_NAME,
        "version": APP_VERSION
    }))
}

// Version handler
async fn version_handler() -> axum::Json<serde_json::Value> {
    axum::Json(json!({
        "name": APP_NAME,
        "version": APP_VERSION,
        "mcp_version": "2024-11-05"
    }))
}

// ============================================================================
// REST API Handlers (for benchmarking - bypasses MCP session overhead)
// ============================================================================

#[derive(Debug, serde::Deserialize)]
struct RestEchoRequest {
    message: String,
}

#[derive(Debug, serde::Deserialize)]
struct RestTimeQuery {
    #[serde(default)]
    tz: Option<String>,
}

// POST /api/echo - Simple echo for benchmarking
async fn rest_echo_handler(
    axum::Json(req): axum::Json<RestEchoRequest>,
) -> axum::Json<serde_json::Value> {
    axum::Json(json!({
        "message": req.message
    }))
}

// GET /api/time?tz=America/New_York - Get time for benchmarking
async fn rest_time_handler(
    axum::extract::Query(query): axum::extract::Query<RestTimeQuery>,
) -> axum::Json<serde_json::Value> {
    let tz_name = query.tz.as_deref().unwrap_or("UTC");
    let now_utc = Utc::now();

    match parse_timezone(tz_name) {
        Ok(offset) => {
            let local_time = now_utc.with_timezone(&offset);
            axum::Json(json!({
                "time": local_time.to_rfc3339(),
                "timezone": tz_name
            }))
        }
        Err(e) => axum::Json(json!({
            "error": format!("Invalid timezone '{}': {}", tz_name, e)
        })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_utc() {
        let offset = parse_timezone("UTC").unwrap();
        assert_eq!(offset.local_minus_utc(), 0);
    }

    #[test]
    fn test_parse_gmt() {
        let offset = parse_timezone("GMT").unwrap();
        assert_eq!(offset.local_minus_utc(), 0);
    }

    #[test]
    fn test_parse_dublin() {
        let offset = parse_timezone("Europe/Dublin").unwrap();
        assert_eq!(offset.local_minus_utc(), 0);
    }

    #[test]
    fn test_parse_new_york() {
        let offset = parse_timezone("America/New_York").unwrap();
        assert_eq!(offset.local_minus_utc(), -5 * 3600);
    }

    #[test]
    fn test_parse_tokyo() {
        let offset = parse_timezone("Asia/Tokyo").unwrap();
        assert_eq!(offset.local_minus_utc(), 9 * 3600);
    }

    #[test]
    fn test_parse_fixed_offset_positive() {
        let offset = parse_offset("+05:30").unwrap();
        assert_eq!(offset.local_minus_utc(), 5 * 3600 + 30 * 60);
    }

    #[test]
    fn test_parse_fixed_offset_negative() {
        let offset = parse_offset("-08:00").unwrap();
        assert_eq!(offset.local_minus_utc(), -8 * 3600);
    }

    #[test]
    fn test_unknown_timezone() {
        let result = parse_timezone("Invalid/Timezone");
        assert!(result.is_err());
    }
}
