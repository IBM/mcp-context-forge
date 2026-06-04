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

use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::serve::ListenerExt;
use axum::Router;
use chrono::{DateTime, FixedOffset, TimeZone, Utc};
use rand_distr::Distribution;
use rand_distr::Normal;
use rmcp::{
    handler::server::router::tool::ToolRouter, model::*, schemars, service::RequestContext, tool,
    tool_handler, tool_router, ErrorData as McpError, RoleServer, ServerHandler,
};
use serde_json::json;
use std::env;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tracing::info;
use tracing::trace;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

const DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:9080";
const APP_NAME: &str = "fast-test-server";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const SESSION_HEADER: &str = "mcp-session-id";
static DIRECT_REQUEST_COUNT: AtomicU64 = AtomicU64::new(0);
static SESSION_COUNTER: AtomicU64 = AtomicU64::new(1);

// ============================================================================
// Request/Response Schemas
// ============================================================================

#[derive(Debug, serde::Deserialize, schemars::JsonSchema)]
pub struct EchoRequest {
    /// The message to echo back
    pub message: String,
    /// Optional delay in milliseconds before responding (default 0)
    #[serde(default)]
    pub delay: Option<u64>,
    /// Optional standard deviation in milliseconds for a normal distribution around the delay mean (default 0 = no randomness)
    #[serde(default)]
    pub delay_stddev: Option<f64>,
}

#[derive(Debug, serde::Deserialize, schemars::JsonSchema)]
pub struct GetTimeRequest {
    /// IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Defaults to UTC.
    #[serde(default)]
    pub timezone: Option<String>,
}

#[derive(Debug, serde::Deserialize, schemars::JsonSchema)]
pub struct ConvertTimeRequest {
    /// Time to convert in RFC3339 format or common formats like '2006-01-02 15:04:05'
    pub time: String,
    /// Source IANA timezone name
    pub source_timezone: String,
    /// Target IANA timezone name
    pub target_timezone: String,
}

/// Shape advertised by schema_* validation fixtures. `recognitionId` is the
/// only required field; the handlers deliberately return payloads that match
/// or violate this schema to exercise both branches of the gateway's output
/// schema validator (including the error-response skip path from #4202).
#[derive(Debug, serde::Serialize, schemars::JsonSchema)]
#[serde(rename_all = "camelCase")]
pub struct SchemaFixtureResponse {
    pub recognition_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

// ============================================================================
// FastTestServer Implementation
// ============================================================================

#[derive(Clone)]
pub struct FastTestServer {
    #[allow(dead_code)]
    tool_router: ToolRouter<FastTestServer>,
    request_count: Arc<AtomicU64>,
}

impl Default for FastTestServer {
    fn default() -> Self {
        Self::new()
    }
}

#[tool_router]
impl FastTestServer {
    pub fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
            request_count: Arc::new(AtomicU64::new(0)),
        }
    }

    /// Echo back whatever message is sent
    #[tool(
        description = "Echo back the provided message. Useful for testing connectivity and
        latency. Optionally delay the response by a specified number of milliseconds. If
        delay_stddev is provided (and gt 0), the actual delay is sampled from a normal distribution
        with mean=delay and the given standard deviation, clamped to  0."
    )]
    async fn echo(
        &self,
        rmcp::handler::server::wrapper::Parameters(req): rmcp::handler::server::wrapper::Parameters<
            EchoRequest,
        >,
    ) -> Result<CallToolResult, McpError> {
        self.request_count.fetch_add(1, Ordering::Relaxed);

        if let Some(ms) = req.delay {
            if ms > 0 {
                let actual_ms = compute_delay(ms, req.delay_stddev);
                tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
            }
        }

        Ok(CallToolResult::success(vec![Content::text(&req.message)]))
    }

    /// Get current system time in specified timezone
    #[tool(
        description = "Get current system time in the specified IANA timezone. Defaults to UTC if no timezone provided."
    )]
    async fn get_system_time(
        &self,
        rmcp::handler::server::wrapper::Parameters(req): rmcp::handler::server::wrapper::Parameters<
            GetTimeRequest,
        >,
    ) -> Result<CallToolResult, McpError> {
        self.request_count.fetch_add(1, Ordering::Relaxed);

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

    /// Convert a time value between two IANA timezones
    #[tool(
        description = "Convert a time value from a source IANA timezone to a target IANA timezone. Accepts RFC3339 or common formats like '2006-01-02 15:04:05'."
    )]
    async fn convert_time(
        &self,
        rmcp::handler::server::wrapper::Parameters(req): rmcp::handler::server::wrapper::Parameters<
            ConvertTimeRequest,
        >,
    ) -> Result<CallToolResult, McpError> {
        self.request_count.fetch_add(1, Ordering::Relaxed);

        let source_offset = match parse_timezone(&req.source_timezone) {
            Ok(o) => o,
            Err(e) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "invalid source timezone: {}",
                    e
                ))]));
            }
        };
        let target_offset = match parse_timezone(&req.target_timezone) {
            Ok(o) => o,
            Err(e) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "invalid target timezone: {}",
                    e
                ))]));
            }
        };

        let parsed = parse_time_in_offset(&req.time, source_offset).map_err(|e| {
            // Surface as isError=true so the gateway forwards the message as-is.
            McpError::invalid_params(e, None)
        });
        let parsed = match parsed {
            Ok(p) => p,
            Err(_) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "invalid time format: {}",
                    req.time
                ))]));
            }
        };

        let converted = parsed.with_timezone(&target_offset).to_rfc3339();
        Ok(CallToolResult::success(vec![Content::text(converted)]))
    }

    /// Always returns isError=true while declaring an outputSchema.
    /// Exercises the gateway's schema-validation skip path for error
    /// responses (MCP specification #4202).
    #[tool(
        description = "Always returns isError=true. Declares an outputSchema the error text intentionally does not satisfy.",
        output_schema = rmcp::handler::server::tool::schema_for_type::<SchemaFixtureResponse>()
    )]
    async fn schema_error(&self) -> Result<CallToolResult, McpError> {
        self.request_count.fetch_add(1, Ordering::Relaxed);
        Ok(CallToolResult::error(vec![Content::text(
            "You cannot send more than 200 points",
        )]))
    }

    /// Returns a success payload that conforms to the declared outputSchema,
    /// surfaced as both text and structured content. Exercises the positive
    /// branch of output-schema validation (MCP SDK + gateway both pass).
    #[tool(
        description = "Returns a JSON payload that conforms to the declared outputSchema.",
        output_schema = rmcp::handler::server::tool::schema_for_type::<SchemaFixtureResponse>()
    )]
    async fn schema_success(&self) -> Result<CallToolResult, McpError> {
        self.request_count.fetch_add(1, Ordering::Relaxed);
        Ok(CallToolResult::structured(json!({
            "recognitionId": "rec-123",
            "message": "ok",
        })))
    }

    /// Get server statistics
    #[tool(description = "Get server statistics including request count and uptime.")]
    async fn get_stats(&self) -> Result<CallToolResult, McpError> {
        let count = self.request_count.load(Ordering::Relaxed);

        let stats = json!({
            "server": APP_NAME,
            "version": APP_VERSION,
            "requests_handled": count,
        });

        Ok(CallToolResult::success(vec![Content::text(
            serde_json::to_string_pretty(&stats).unwrap_or_default(),
        )]))
    }
}

#[tool_handler]
impl ServerHandler for FastTestServer {
    fn get_info(&self) -> ServerInfo {
        let mut info = ServerInfo::default();
        info.protocol_version = ProtocolVersion::V_2024_11_05;
        info.capabilities = ServerCapabilities::builder().enable_tools().build();
        info.server_info = Implementation::from_build_env();
        info.instructions = Some(
            "Ultra-fast MCP test server. Tools: echo, get_system_time, convert_time, get_stats, plus schema_error and schema_success validation fixtures.".to_string()
        );
        info
    }

    async fn initialize(
        &self,
        _request: InitializeRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<InitializeResult, McpError> {
        info!("Client connected to {}", APP_NAME);
        Ok(self.get_info())
    }
}

// ============================================================================
// Delay Helpers
// ============================================================================

/// Compute the actual delay in ms, optionally sampling from a normal distribution.
/// Returns the mean unchanged when stddev is None, zero, or negative.
fn compute_delay(mean_ms: u64, stddev: Option<f64>) -> u64 {
    match stddev {
        Some(sd) if sd > 0.0 => {
            let dist = Normal::new(mean_ms as f64, sd)
                .unwrap_or_else(|_| Normal::new(mean_ms as f64, 0.0).unwrap());
            let sample = dist.sample(&mut rand::rng());
            // Clamp to >= 0 (negative delays make no sense)
            sample.round().max(0.0) as u64
        }
        _ => mean_ms,
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

/// Parse an input time string in the given offset, accepting RFC3339 and a
/// handful of common formats used by the Go fast-time-server port.
fn parse_time_in_offset(
    time_str: &str,
    offset: FixedOffset,
) -> Result<DateTime<FixedOffset>, String> {
    if let Ok(parsed) = DateTime::parse_from_rfc3339(time_str) {
        return Ok(parsed.with_timezone(&offset));
    }
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"] {
        if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(time_str, fmt) {
            if let Some(dt) = offset.from_local_datetime(&naive).single() {
                return Ok(dt);
            }
        }
        if let Ok(date) = chrono::NaiveDate::parse_from_str(time_str, fmt) {
            if let Some(naive) = date.and_hms_opt(0, 0, 0) {
                if let Some(dt) = offset.from_local_datetime(&naive).single() {
                    return Ok(dt);
                }
            }
        }
    }
    Err(format!("unrecognized time format: {}", time_str))
}

/// Parse an offset string like "+05:30" or "-08:00"
fn parse_offset(s: &str) -> Result<FixedOffset, String> {
    let (sign, rest) = if let Some(stripped) = s.strip_prefix('+') {
        (1, stripped)
    } else if let Some(stripped) = s.strip_prefix('-') {
        (-1, stripped)
    } else {
        return Err("Offset must start with + or -".to_string());
    };

    let parts: Vec<&str> = rest.split(':').collect();
    if parts.len() != 2 {
        return Err("Offset must be in format +HH:MM or -HH:MM".to_string());
    }

    let hours: i32 = parts[0].parse().map_err(|_| "Invalid hours in offset")?;
    let minutes: i32 = parts[1].parse().map_err(|_| "Invalid minutes in offset")?;

    let total_seconds = sign * (hours * 3600 + minutes * 60);

    FixedOffset::east_opt(total_seconds).ok_or_else(|| format!("Offset out of range: {}", s))
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
    let bind_address =
        env::var("BIND_ADDRESS").unwrap_or_else(|_| DEFAULT_BIND_ADDRESS.to_string());

    info!("{} v{} starting...", APP_NAME, APP_VERSION);
    info!("Binding to: {}", bind_address);

    // Build router with health check endpoint and REST API for benchmarking
    let router = Router::new()
        // Health & version
        .route("/health", axum::routing::get(health_handler))
        .route("/version", axum::routing::get(version_handler))
        // REST API for benchmarking (bypasses MCP session overhead)
        .route("/api/echo", axum::routing::post(rest_echo_handler))
        .route("/api/time", axum::routing::get(rest_time_handler))
        // MCP protocol endpoint
        .route(
            "/mcp",
            axum::routing::post(mcp_handler).delete(mcp_delete_handler),
        );

    // Bind and serve
    let tcp_listener = tokio::net::TcpListener::bind(&bind_address)
        .await?
        .tap_io(|tcp_stream| {
            if let Err(err) = tcp_stream.set_nodelay(true) {
                trace!("failed to set TCP_NODELAY on incoming connection: {err:#}");
            }
        });

    info!("MCP endpoint:   http://{}/mcp", bind_address);
    info!(
        "REST API:       http://{}/api/echo (POST), /api/time (GET)",
        bind_address
    );
    info!("Health check:   http://{}/health", bind_address);
    info!("Version info:   http://{}/version", bind_address);
    info!("");
    info!("Benchmark with:");
    info!("  hey -n 1000000 -c 200 -m POST -T 'application/json' \\");
    info!(
        "      -d '{{\"message\":\"hello\"}}' http://{}/api/echo",
        bind_address
    );

    axum::serve(tcp_listener, router)
        .with_graceful_shutdown(async move {
            tokio::signal::ctrl_c().await.unwrap();
            info!("Shutting down...");
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
// Fast Streamable HTTP MCP Handler
// ============================================================================

async fn mcp_delete_handler() -> StatusCode {
    StatusCode::ACCEPTED
}

async fn mcp_handler(
    headers: HeaderMap,
    axum::Json(req): axum::Json<serde_json::Value>,
) -> Response {
    let method = req
        .get("method")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let id = req.get("id");

    if id.is_none() {
        return StatusCode::ACCEPTED.into_response();
    }

    if method != "initialize" && !headers.contains_key(SESSION_HEADER) {
        return mcp_error_response(id, -32000, "Invalid session ID", None);
    }

    match method {
        "initialize" => mcp_initialize_response(id),
        "tools/list" => mcp_tools_list_response(id),
        "tools/call" => mcp_tools_call_response(id, &req).await,
        _ => mcp_error_response(id, -32601, "Method not found", None),
    }
}

fn mcp_base_headers() -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json"),
    );
    headers
}

fn mcp_json_response(headers: HeaderMap, body: String) -> Response {
    (headers, body).into_response()
}

fn mcp_id_json(id: Option<&serde_json::Value>) -> String {
    id.and_then(|value| serde_json::to_string(value).ok())
        .unwrap_or_else(|| "null".to_string())
}

fn mcp_initialize_response(id: Option<&serde_json::Value>) -> Response {
    let mut headers = mcp_base_headers();
    let session_id = SESSION_COUNTER.fetch_add(1, Ordering::Relaxed);
    let session_header = HeaderValue::from_str(&format!("fast-test-{session_id}"))
        .unwrap_or_else(|_| HeaderValue::from_static("fast-test"));
    headers.insert(SESSION_HEADER, session_header);
    mcp_json_response(
        headers,
        format!(
            r#"{{"jsonrpc":"2.0","id":{},"result":{{"protocolVersion":"2024-11-05","capabilities":{{"tools":{{}}}},"serverInfo":{{"name":"{}","version":"{}"}},"instructions":"Ultra-fast MCP test server."}}}}"#,
            mcp_id_json(id),
            APP_NAME,
            APP_VERSION
        ),
    )
}

fn mcp_tools_list_response(id: Option<&serde_json::Value>) -> Response {
    mcp_json_response(
        mcp_base_headers(),
        format!(
            r#"{{"jsonrpc":"2.0","id":{},"result":{{"tools":[{{"name":"echo","description":"Echo back the provided message.","inputSchema":{{"type":"object","properties":{{"message":{{"type":"string"}},"delay":{{"type":"integer","minimum":0}},"delay_stddev":{{"type":"number","minimum":0}}}},"required":["message"]}}}},{{"name":"get_system_time","description":"Get current system time in the specified IANA timezone.","inputSchema":{{"type":"object","properties":{{"timezone":{{"type":"string"}}}}}}}},{{"name":"convert_time","description":"Convert a time value from a source IANA timezone to a target IANA timezone.","inputSchema":{{"type":"object","properties":{{"time":{{"type":"string"}},"source_timezone":{{"type":"string"}},"target_timezone":{{"type":"string"}}}},"required":["time","source_timezone","target_timezone"]}}}},{{"name":"schema_error","description":"Always returns isError=true.","inputSchema":{{"type":"object","properties":{{}}}},"outputSchema":{{"type":"object","properties":{{"recognitionId":{{"type":"string"}},"message":{{"type":"string"}}}},"required":["recognitionId"]}}}},{{"name":"schema_success","description":"Returns a JSON payload that conforms to the declared outputSchema.","inputSchema":{{"type":"object","properties":{{}}}},"outputSchema":{{"type":"object","properties":{{"recognitionId":{{"type":"string"}},"message":{{"type":"string"}}}},"required":["recognitionId"]}}}},{{"name":"get_stats","description":"Get server statistics including request count and uptime.","inputSchema":{{"type":"object","properties":{{}}}}}}]}}}}"#,
            mcp_id_json(id)
        ),
    )
}

async fn mcp_tools_call_response(
    id: Option<&serde_json::Value>,
    req: &serde_json::Value,
) -> Response {
    let params = req.get("params").unwrap_or(&serde_json::Value::Null);
    let name = params
        .get("name")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let arguments = params.get("arguments").unwrap_or(&serde_json::Value::Null);

    match name {
        "echo" => {
            let Some(arguments) = mcp_arguments_object(id, arguments) else {
                return mcp_invalid_params_response(id, "arguments must be an object");
            };
            let Some(message) = mcp_required_string(id, arguments, "message") else {
                return mcp_invalid_params_response(id, "message must be a string");
            };
            let Some(delay) = mcp_optional_u64(id, arguments, "delay") else {
                return mcp_invalid_params_response(id, "delay must be an unsigned integer");
            };
            let Some(delay_stddev) = mcp_optional_f64(id, arguments, "delay_stddev") else {
                return mcp_invalid_params_response(id, "delay_stddev must be a number");
            };

            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            if let Some(ms) = delay {
                if ms > 0 {
                    let actual_ms = compute_delay(ms, delay_stddev);
                    tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
                }
            }
            mcp_text_result_response(id, message, false)
        }
        "get_system_time" => {
            let timezone = if arguments.is_null() {
                None
            } else {
                let Some(arguments) = mcp_arguments_object(id, arguments) else {
                    return mcp_invalid_params_response(id, "arguments must be an object");
                };
                let Some(timezone) = mcp_optional_string(id, arguments, "timezone") else {
                    return mcp_invalid_params_response(id, "timezone must be a string");
                };
                timezone
            };
            let timezone = timezone.unwrap_or("UTC");

            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            match parse_timezone(timezone) {
                Ok(offset) => {
                    let result = Utc::now().with_timezone(&offset).to_rfc3339();
                    mcp_text_result_response(id, &result, false)
                }
                Err(err) => mcp_text_result_response(
                    id,
                    &format!("Invalid timezone '{timezone}': {err}"),
                    true,
                ),
            }
        }
        "convert_time" => mcp_convert_time_response(id, arguments),
        "schema_error" => {
            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            mcp_text_result_response(id, "You cannot send more than 200 points", true)
        }
        "schema_success" => mcp_json_response(mcp_base_headers(), {
            DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
            format!(
                r#"{{"jsonrpc":"2.0","id":{},"result":{{"content":[{{"type":"text","text":"{{\"recognitionId\":\"rec-123\",\"message\":\"ok\"}}"}}],"structuredContent":{{"recognitionId":"rec-123","message":"ok"}},"isError":false}}}}"#,
                mcp_id_json(id)
            )
        }),
        "get_stats" => {
            let count = DIRECT_REQUEST_COUNT.load(Ordering::Relaxed);
            mcp_text_result_response(
                id,
                &format!(
                    "{{\n  \"server\": \"{}\",\n  \"version\": \"{}\",\n  \"requests_handled\": {}\n}}",
                    APP_NAME, APP_VERSION, count
                ),
                false,
            )
        }
        _ => mcp_error_response(id, -32602, "Unknown tool", Some(json!({ "tool": name }))),
    }
}

fn mcp_convert_time_response(
    id: Option<&serde_json::Value>,
    arguments: &serde_json::Value,
) -> Response {
    let Some(arguments) = mcp_arguments_object(id, arguments) else {
        return mcp_invalid_params_response(id, "arguments must be an object");
    };
    let Some(time) = mcp_required_string(id, arguments, "time") else {
        return mcp_invalid_params_response(id, "time must be a string");
    };
    let Some(source_timezone) = mcp_required_string(id, arguments, "source_timezone") else {
        return mcp_invalid_params_response(id, "source_timezone must be a string");
    };
    let Some(target_timezone) = mcp_required_string(id, arguments, "target_timezone") else {
        return mcp_invalid_params_response(id, "target_timezone must be a string");
    };

    DIRECT_REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);

    let source_offset = match parse_timezone(source_timezone) {
        Ok(offset) => offset,
        Err(err) => {
            return mcp_text_result_response(id, &format!("invalid source timezone: {err}"), true)
        }
    };
    let target_offset = match parse_timezone(target_timezone) {
        Ok(offset) => offset,
        Err(err) => {
            return mcp_text_result_response(id, &format!("invalid target timezone: {err}"), true)
        }
    };
    match parse_time_in_offset(time, source_offset) {
        Ok(parsed) => {
            let converted = parsed.with_timezone(&target_offset).to_rfc3339();
            mcp_text_result_response(id, &converted, false)
        }
        Err(_) => mcp_text_result_response(id, &format!("invalid time format: {time}"), true),
    }
}

fn mcp_arguments_object<'a>(
    _id: Option<&serde_json::Value>,
    value: &'a serde_json::Value,
) -> Option<&'a serde_json::Map<String, serde_json::Value>> {
    value.as_object()
}

fn mcp_required_string<'a>(
    _id: Option<&serde_json::Value>,
    arguments: &'a serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<&'a str> {
    arguments.get(field)?.as_str()
}

fn mcp_optional_string<'a>(
    _id: Option<&serde_json::Value>,
    arguments: &'a serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<&'a str>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_str().map(Some),
        None => Some(None),
    }
}

fn mcp_optional_u64(
    _id: Option<&serde_json::Value>,
    arguments: &serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<u64>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_u64().map(Some),
        None => Some(None),
    }
}

fn mcp_optional_f64(
    _id: Option<&serde_json::Value>,
    arguments: &serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Option<Option<f64>> {
    match arguments.get(field) {
        Some(value) if value.is_null() => Some(None),
        Some(value) => value.as_f64().map(Some),
        None => Some(None),
    }
}

fn mcp_text_result_response(
    id: Option<&serde_json::Value>,
    text: &str,
    is_error: bool,
) -> Response {
    let escaped = serde_json::to_string(text).unwrap_or_else(|_| "\"\"".to_string());
    mcp_json_response(
        mcp_base_headers(),
        format!(
            r#"{{"jsonrpc":"2.0","id":{},"result":{{"content":[{{"type":"text","text":{}}}],"isError":{}}}}}"#,
            mcp_id_json(id),
            escaped,
            is_error
        ),
    )
}

fn mcp_error_response(
    id: Option<&serde_json::Value>,
    code: i32,
    message: &str,
    data: Option<serde_json::Value>,
) -> Response {
    let data = data
        .map(|value| format!(r#","data":{}"#, value))
        .unwrap_or_default();
    mcp_json_response(
        mcp_base_headers(),
        format!(
            r#"{{"jsonrpc":"2.0","id":{},"error":{{"code":{},"message":"{}"{}}}}}"#,
            mcp_id_json(id),
            code,
            message,
            data
        ),
    )
}

fn mcp_invalid_params_response(id: Option<&serde_json::Value>, message: &str) -> Response {
    mcp_error_response(id, -32602, message, None)
}

// ============================================================================
// REST API Handlers (for benchmarking - bypasses MCP session overhead)
// ============================================================================

#[derive(Debug, serde::Deserialize)]
struct RestEchoRequest {
    message: String,
    #[serde(default)]
    delay: Option<u64>,
    #[serde(default)]
    delay_stddev: Option<f64>,
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
    if let Some(ms) = req.delay {
        if ms > 0 {
            let actual_ms = compute_delay(ms, req.delay_stddev);
            tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
        }
    }
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

    #[test]
    fn test_default_server() {
        let _server = FastTestServer::default();
    }
}
