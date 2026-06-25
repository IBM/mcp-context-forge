// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! MCP server definition built on the official Rust SDK (`rmcp`).
//!
//! Tools are declared once here via the `#[tool]` macros. Their JSON schemas are
//! derived from the parameter types, so the `/mcp` Streamable HTTP transport and
//! the legacy SSE shim ([`crate::transports::sse`]) share a single source of
//! truth. The SSE shim reuses [`FastTimeServer::tool_definitions`] for
//! `tools/list` and [`FastTimeServer::dispatch_tool`] for `tools/call`.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use chrono::Utc;
use rmcp::ErrorData as McpError;
use rmcp::{
    ServerHandler,
    handler::server::{tool::ToolRouter, wrapper::Parameters},
    model::{
        CallToolResult, Content, Implementation, JsonObject, ProtocolVersion, ServerCapabilities,
        ServerInfo, Tool,
    },
    schemars, tool, tool_handler, tool_router,
};
use serde::Deserialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

use crate::config::{APP_NAME, APP_VERSION};
use crate::delay::{compute_delay, validate_delay};
use crate::time::{parse_time_in_timezone, parse_timezone};

/// Total tool invocations served since startup, surfaced by `get_stats`.
static REQUEST_COUNT: AtomicU64 = AtomicU64::new(0);

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub(crate) struct EchoParams {
    #[schemars(description = "Message to echo back")]
    message: String,
    #[serde(default)]
    #[schemars(description = "Delay in milliseconds before responding (max 60000)")]
    delay: Option<u64>,
    #[serde(default)]
    #[schemars(description = "Standard deviation in milliseconds for delay jitter")]
    delay_stddev: Option<f64>,
}

#[derive(Debug, Default, Deserialize, schemars::JsonSchema)]
pub(crate) struct GetSystemTimeParams {
    #[serde(default)]
    #[schemars(description = "IANA timezone name (defaults to UTC)")]
    timezone: Option<String>,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub(crate) struct ConvertTimeParams {
    #[schemars(description = "Time value to convert")]
    time: String,
    #[schemars(description = "Source IANA timezone")]
    source_timezone: String,
    #[schemars(description = "Target IANA timezone")]
    target_timezone: String,
}

#[derive(Clone)]
pub(crate) struct FastTimeServer {
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl FastTimeServer {
    pub(crate) fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
        }
    }

    #[tool(description = "Echo back the provided message.")]
    async fn echo(
        &self,
        Parameters(params): Parameters<EchoParams>,
    ) -> Result<CallToolResult, McpError> {
        let delay = validate_delay(params.delay)
            .map_err(|message| McpError::invalid_params(message, None))?;

        REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
        if let Some(ms) = delay
            && ms > 0
        {
            let actual_ms = compute_delay(ms, params.delay_stddev);
            tokio::time::sleep(std::time::Duration::from_millis(actual_ms)).await;
        }
        Ok(CallToolResult::success(vec![Content::text(params.message)]))
    }

    #[tool(description = "Get current system time in the specified IANA timezone.")]
    async fn get_system_time(
        &self,
        Parameters(params): Parameters<GetSystemTimeParams>,
    ) -> Result<CallToolResult, McpError> {
        let timezone = params.timezone.as_deref().unwrap_or("UTC");

        REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
        match parse_timezone(timezone) {
            Ok(parsed) => Ok(CallToolResult::success(vec![Content::text(
                parsed.format_utc(Utc::now()),
            )])),
            Err(err) => Ok(CallToolResult::error(vec![Content::text(format!(
                "Invalid timezone '{timezone}': {err}"
            ))])),
        }
    }

    #[tool(
        description = "Convert a time value from a source IANA timezone to a target IANA timezone."
    )]
    async fn convert_time(
        &self,
        Parameters(params): Parameters<ConvertTimeParams>,
    ) -> Result<CallToolResult, McpError> {
        REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);

        let source_timezone = match parse_timezone(&params.source_timezone) {
            Ok(timezone) => timezone,
            Err(err) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "invalid source timezone: {err}"
                ))]));
            }
        };
        let target_timezone = match parse_timezone(&params.target_timezone) {
            Ok(timezone) => timezone,
            Err(err) => {
                return Ok(CallToolResult::error(vec![Content::text(format!(
                    "invalid target timezone: {err}"
                ))]));
            }
        };
        match parse_time_in_timezone(&params.time, &source_timezone) {
            Ok(parsed) => Ok(CallToolResult::success(vec![Content::text(
                target_timezone.format_utc(parsed),
            )])),
            Err(_) => Ok(CallToolResult::error(vec![Content::text(format!(
                "invalid time format: {}",
                params.time
            ))])),
        }
    }

    #[tool(
        description = "Always returns isError=true.",
        output_schema = fixture_output_schema()
    )]
    async fn schema_error(&self) -> Result<CallToolResult, McpError> {
        REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
        Ok(CallToolResult::error(vec![Content::text(
            "You cannot send more than 200 points",
        )]))
    }

    #[tool(
        description = "Returns a JSON payload that conforms to the declared outputSchema.",
        output_schema = fixture_output_schema()
    )]
    async fn schema_success(&self) -> Result<CallToolResult, McpError> {
        REQUEST_COUNT.fetch_add(1, Ordering::Relaxed);
        // `structured` sets content = [text(payload)], structured_content = payload,
        // and is_error = Some(false), matching the legacy schema_success fixture.
        Ok(CallToolResult::structured(
            json!({ "recognitionId": "rec-123", "message": "ok" }),
        ))
    }

    #[tool(description = "Get server statistics including request count and uptime.")]
    async fn get_stats(&self) -> Result<CallToolResult, McpError> {
        let count = REQUEST_COUNT.fetch_add(1, Ordering::Relaxed) + 1;
        Ok(CallToolResult::success(vec![Content::text(format!(
            "{{\n  \"server\": \"{APP_NAME}\",\n  \"version\": \"{APP_VERSION}\",\n  \"requests_handled\": {count}\n}}"
        ))]))
    }

    /// Tool schemas (sorted by name), shared with the legacy SSE shim's
    /// `tools/list` so it never drifts from the `/mcp` transport.
    pub(crate) fn tool_definitions(&self) -> Vec<Tool> {
        self.tool_router.list_all()
    }

    /// Invoke a tool by name with raw JSON arguments. Used by the legacy SSE
    /// shim; the `/mcp` transport routes through the generated `ServerHandler`.
    pub(crate) async fn dispatch_tool(
        &self,
        name: &str,
        arguments: &Value,
    ) -> Result<CallToolResult, McpError> {
        match name {
            "echo" => self.echo(Parameters(parse_params(arguments)?)).await,
            "get_system_time" => {
                self.get_system_time(Parameters(parse_params(arguments)?))
                    .await
            }
            "convert_time" => {
                self.convert_time(Parameters(parse_params(arguments)?))
                    .await
            }
            "schema_error" => self.schema_error().await,
            "schema_success" => self.schema_success().await,
            "get_stats" => self.get_stats().await,
            _ => Err(McpError::invalid_params(
                "Unknown tool",
                Some(json!({ "tool": name })),
            )),
        }
    }
}

impl Default for FastTimeServer {
    fn default() -> Self {
        Self::new()
    }
}

#[tool_handler]
impl ServerHandler for FastTimeServer {
    fn get_info(&self) -> ServerInfo {
        // `Implementation::from_build_env()` reports rmcp's own crate identity, so
        // build it explicitly to match the legacy SSE shim's serverInfo.
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
            .with_protocol_version(ProtocolVersion::V_2025_11_25)
            .with_server_info(Implementation::new(APP_NAME, APP_VERSION))
            .with_instructions("Ultra-fast MCP test server.")
    }
}

/// Output schema advertised by the `schema_error` / `schema_success` fixtures,
/// used by gateway tests to exercise output-schema handling. `recognitionId` is
/// required; `message` is optional.
fn fixture_output_schema() -> Arc<JsonObject> {
    let schema = json!({
        "type": "object",
        "properties": {
            "recognitionId": { "type": "string" },
            "message": { "type": "string" }
        },
        "required": ["recognitionId"]
    });
    Arc::new(schema.as_object().cloned().unwrap_or_default())
}

/// Deserialize raw JSON-RPC `arguments` into a typed parameter struct, treating
/// a missing/`null` value as an empty object so optional-only tools still parse.
fn parse_params<T: DeserializeOwned>(arguments: &Value) -> Result<T, McpError> {
    let value = if arguments.is_null() {
        Value::Object(serde_json::Map::new())
    } else {
        arguments.clone()
    };
    serde_json::from_value(value).map_err(|err| McpError::invalid_params(err.to_string(), None))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rmcp::model::ErrorCode;

    fn result_json(result: CallToolResult) -> Value {
        serde_json::to_value(result).expect("CallToolResult should serialize")
    }

    #[test]
    fn test_server_info_reports_app_identity_not_rmcp() {
        let info = FastTimeServer::new().get_info();
        assert_eq!(info.server_info.name, APP_NAME);
        assert_eq!(info.server_info.version, APP_VERSION);
        assert_eq!(info.protocol_version, ProtocolVersion::V_2025_11_25);
    }

    #[tokio::test]
    async fn test_convert_time_matches_go_fast_time_dst_behavior() {
        let server = FastTimeServer::new();
        let result = server
            .dispatch_tool(
                "convert_time",
                &json!({
                    "time": "2025-06-21T16:00:00Z",
                    "source_timezone": "UTC",
                    "target_timezone": "America/New_York"
                }),
            )
            .await
            .expect("convert_time should succeed");
        let body = result_json(result);
        assert_eq!(body["content"][0]["text"], "2025-06-21T12:00:00-04:00");
    }

    #[tokio::test]
    async fn test_convert_time_matches_go_fast_time_half_hour_zones() {
        let server = FastTimeServer::new();
        let result = server
            .dispatch_tool(
                "convert_time",
                &json!({
                    "time": "2025-01-10 10:00:00",
                    "source_timezone": "Asia/Kolkata",
                    "target_timezone": "UTC"
                }),
            )
            .await
            .expect("convert_time should succeed");
        let body = result_json(result);
        assert_eq!(body["content"][0]["text"], "2025-01-10T04:30:00Z");
    }

    #[tokio::test]
    async fn test_echo_rejects_delay_above_limit() {
        let server = FastTimeServer::new();
        let err = server
            .echo(Parameters(EchoParams {
                message: "hello".to_string(),
                delay: Some(crate::config::MAX_DELAY_MS + 1),
                delay_stddev: None,
            }))
            .await
            .expect_err("delay above limit should be rejected");
        assert_eq!(err.code, ErrorCode::INVALID_PARAMS);
        assert_eq!(err.message.as_ref(), "delay exceeds the 60000 ms limit");
    }

    #[tokio::test]
    async fn test_get_system_time_invalid_timezone_is_tool_error() {
        let server = FastTimeServer::new();
        let result = server
            .dispatch_tool("get_system_time", &json!({ "timezone": "Invalid/Zone" }))
            .await
            .expect("tool errors surface as CallToolResult, not protocol errors");
        let body = result_json(result);
        assert_eq!(body["isError"], true);
        assert!(
            body["content"][0]["text"]
                .as_str()
                .unwrap()
                .contains("Invalid timezone 'Invalid/Zone'")
        );
    }

    #[tokio::test]
    async fn test_tool_definitions_cover_all_tools() {
        let server = FastTimeServer::new();
        let names: Vec<String> = server
            .tool_definitions()
            .into_iter()
            .map(|tool| tool.name.to_string())
            .collect();
        for expected in [
            "echo",
            "get_system_time",
            "convert_time",
            "schema_error",
            "schema_success",
            "get_stats",
        ] {
            assert!(names.contains(&expected.to_string()), "missing {expected}");
        }
    }

    #[tokio::test]
    async fn test_dispatch_unknown_tool_is_invalid_params() {
        let server = FastTimeServer::new();
        let err = server
            .dispatch_tool("does_not_exist", &Value::Null)
            .await
            .expect_err("unknown tool should be rejected");
        assert_eq!(err.code, ErrorCode::INVALID_PARAMS);
    }

    #[tokio::test]
    async fn test_schema_fixtures_advertise_output_schema() {
        let server = FastTimeServer::new();
        let tools = server.tool_definitions();
        for name in ["schema_error", "schema_success"] {
            let tool = tools
                .iter()
                .find(|tool| tool.name == name)
                .unwrap_or_else(|| panic!("missing {name}"));
            let schema = tool
                .output_schema
                .as_ref()
                .unwrap_or_else(|| panic!("{name} must advertise an outputSchema"));
            assert_eq!(
                schema.get("required"),
                Some(&json!(["recognitionId"])),
                "{name} outputSchema should require recognitionId"
            );
        }
    }
}
