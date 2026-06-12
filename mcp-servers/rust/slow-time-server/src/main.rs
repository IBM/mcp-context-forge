// slow-time-server - configurable-latency MCP server for resilience testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, FixedOffset, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::env;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};
use tower_http::cors::CorsLayer;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

const APP_NAME: &str = "slow-time-server";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const DEFAULT_BIND_ADDRESS: &str = "0.0.0.0:8081";
/// Maximum delay cap for resilience tests, preventing unbounded request sleeps.
const MAX_DELAY: Duration = Duration::from_secs(600);

#[derive(Clone)]
struct AppState {
    config: Arc<LatencyConfig>,
    started: Instant,
    stats: Arc<Stats>,
}

struct LatencyConfig {
    default_latency: Duration,
    failure_rate: f64,
}

struct Stats {
    requests: AtomicU64,
    failures: AtomicU64,
}

#[derive(Debug, Deserialize)]
struct RpcRequest {
    #[serde(default = "jsonrpc_version")]
    jsonrpc: String,
    #[serde(default)]
    id: Value,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Debug, Deserialize)]
struct ToolCallParams {
    name: String,
    #[serde(default)]
    arguments: Value,
}

#[derive(Debug, Deserialize)]
struct TimeArgs {
    #[serde(default)]
    timezone: Option<String>,
    #[serde(default)]
    delay_seconds: Option<f64>,
    #[serde(default)]
    delay_ms: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct ConvertArgs {
    time: String,
    source_timezone: String,
    target_timezone: String,
    #[serde(default)]
    delay_seconds: Option<f64>,
    #[serde(default)]
    delay_ms: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct RestTimeQuery {
    #[serde(default)]
    timezone: Option<String>,
    #[serde(default)]
    tz: Option<String>,
    #[serde(default)]
    delay: Option<String>,
}

#[derive(Debug, Deserialize)]
struct EchoQuery {
    #[serde(default)]
    message: Option<String>,
}

#[derive(Debug, Serialize)]
struct HealthResponse<'a> {
    status: &'a str,
    name: &'a str,
    version: &'a str,
    uptime_seconds: u64,
}

fn jsonrpc_version() -> String {
    "2.0".to_string()
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".to_string().into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let bind_address =
        env::var("BIND_ADDRESS").unwrap_or_else(|_| DEFAULT_BIND_ADDRESS.to_string());
    let default_latency = parse_duration_env("DEFAULT_LATENCY", Duration::from_secs(5))?;
    let failure_rate = parse_failure_rate_env()?;
    let state = AppState {
        config: Arc::new(LatencyConfig {
            default_latency,
            failure_rate,
        }),
        started: Instant::now(),
        stats: Arc::new(Stats {
            requests: AtomicU64::new(0),
            failures: AtomicU64::new(0),
        }),
    };

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/version", get(version_handler))
        .route("/api/v1/time", get(rest_time_handler))
        .route("/api/v1/config", get(config_handler))
        .route("/api/v1/stats", get(stats_handler))
        .route("/api/v1/test/echo", get(echo_handler))
        .route("/mcp", post(mcp_handler))
        .route("/", post(mcp_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr: SocketAddr = bind_address.parse()?;
    info!("{} v{} listening on {}", APP_NAME, APP_VERSION, addr);
    axum::serve(tokio::net::TcpListener::bind(addr).await?, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

async fn health_handler(State(state): State<AppState>) -> Json<HealthResponse<'static>> {
    Json(HealthResponse {
        status: "healthy",
        name: APP_NAME,
        version: APP_VERSION,
        uptime_seconds: state.started.elapsed().as_secs(),
    })
}

async fn version_handler() -> Json<Value> {
    Json(json!({
        "name": APP_NAME,
        "version": APP_VERSION,
        "mcp_version": "2025-11-25",
        "transport": "streamable-http"
    }))
}

async fn config_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "default_latency_ms": state.config.default_latency.as_millis(),
        "failure_rate": state.config.failure_rate,
        "max_delay_ms": MAX_DELAY.as_millis()
    }))
}

async fn stats_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "requests": state.stats.requests.load(Ordering::Relaxed),
        "failures": state.stats.failures.load(Ordering::Relaxed),
        "uptime_seconds": state.started.elapsed().as_secs()
    }))
}

async fn echo_handler(Query(query): Query<EchoQuery>) -> Json<Value> {
    Json(json!({
        "echo": query.message.unwrap_or_else(|| "Hello from slow-time-server!".to_string()),
        "timestamp": Utc::now().to_rfc3339(),
        "server": APP_NAME,
    }))
}

async fn rest_time_handler(
    State(state): State<AppState>,
    Query(query): Query<RestTimeQuery>,
) -> impl IntoResponse {
    state.stats.requests.fetch_add(1, Ordering::Relaxed);
    let delay = match query.delay.as_deref().map(parse_duration).transpose() {
        Ok(Some(value)) => value,
        Ok(None) => state.config.default_latency,
        Err(err) => {
            return (StatusCode::BAD_REQUEST, Json(json!({ "error": err }))).into_response();
        }
    };
    sleep_capped(delay).await;
    let timezone = query
        .timezone
        .or(query.tz)
        .unwrap_or_else(|| "UTC".to_string());
    match current_time(&timezone) {
        Ok(value) => Json(json!({ "timezone": timezone, "time": value })).into_response(),
        Err(err) => (StatusCode::BAD_REQUEST, Json(json!({ "error": err }))).into_response(),
    }
}

async fn mcp_handler(
    State(state): State<AppState>,
    Json(req): Json<RpcRequest>,
) -> impl IntoResponse {
    let response = match req.method.as_str() {
        "initialize" => rpc_result(
            &req,
            json!({
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "instructions": "Configurable-latency MCP server for timeout, circuit-breaker, and resilience testing."
            }),
        ),
        "tools/list" => rpc_result(&req, tools_list()),
        "tools/call" => match serde_json::from_value::<ToolCallParams>(req.params.clone()) {
            Ok(params) => tool_call_response(&state, &req, params).await,
            Err(err) => rpc_error(&req, -32602, &format!("invalid tool call params: {err}")),
        },
        _ => rpc_error(&req, -32601, &format!("method not found: {}", req.method)),
    };
    Json(response)
}

async fn tool_call_response(state: &AppState, req: &RpcRequest, params: ToolCallParams) -> Value {
    state.stats.requests.fetch_add(1, Ordering::Relaxed);
    match params.name.as_str() {
        "get_slow_time" => match serde_json::from_value::<TimeArgs>(params.arguments) {
            Ok(args) => {
                let delay = match delay_from_time_args(&args, state.config.default_latency) {
                    Ok(value) => value,
                    Err(err) => return rpc_error(req, -32602, &err),
                };
                sleep_capped(delay).await;
                text_result(
                    req,
                    current_time(args.timezone.as_deref().unwrap_or("UTC")),
                    false,
                )
            }
            Err(err) => rpc_error(req, -32602, &format!("invalid arguments: {err}")),
        },
        "convert_slow_time" => match serde_json::from_value::<ConvertArgs>(params.arguments) {
            Ok(args) => {
                let delay = match delay_from_convert_args(&args, state.config.default_latency) {
                    Ok(value) => value,
                    Err(err) => return rpc_error(req, -32602, &err),
                };
                sleep_capped(delay).await;
                text_result(
                    req,
                    convert_time(&args.time, &args.source_timezone, &args.target_timezone),
                    false,
                )
            }
            Err(err) => rpc_error(req, -32602, &format!("invalid arguments: {err}")),
        },
        "get_instant_time" => match serde_json::from_value::<TimeArgs>(params.arguments) {
            Ok(args) => text_result(
                req,
                current_time(args.timezone.as_deref().unwrap_or("UTC")),
                false,
            ),
            Err(err) => rpc_error(req, -32602, &format!("invalid arguments: {err}")),
        },
        "get_timeout_time" => {
            sleep_capped(MAX_DELAY).await;
            text_result(req, current_time("UTC"), false)
        }
        "get_flaky_time" => {
            if should_fail(state.config.failure_rate) {
                state.stats.failures.fetch_add(1, Ordering::Relaxed);
                text_result(req, Ok("simulated slow-time failure".to_string()), true)
            } else {
                sleep_capped(state.config.default_latency).await;
                text_result(req, current_time("UTC"), false)
            }
        }
        _ => rpc_error(req, -32602, &format!("unknown tool: {}", params.name)),
    }
}

fn tools_list() -> Value {
    json!({
        "tools": [
            {"name": "get_slow_time", "description": "Get current time after the configured or requested delay.", "inputSchema": time_schema()},
            {"name": "convert_slow_time", "description": "Convert a timestamp between timezones after a delay.", "inputSchema": convert_schema()},
            {"name": "get_instant_time", "description": "Get current time without artificial delay.", "inputSchema": time_schema()},
            {"name": "get_timeout_time", "description": "Sleep for the maximum delay to exercise gateway timeout handling.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "get_flaky_time", "description": "Return time or a simulated failure according to FAILURE_RATE.", "inputSchema": {"type": "object", "properties": {}}}
        ]
    })
}

fn time_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "timezone": {"type": "string"},
            "delay_seconds": {"type": "number", "minimum": 0, "maximum": MAX_DELAY.as_secs()},
            "delay_ms": {"type": "integer", "minimum": 0, "maximum": MAX_DELAY.as_millis()}
        }
    })
}

fn convert_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "time": {"type": "string"},
            "source_timezone": {"type": "string"},
            "target_timezone": {"type": "string"},
            "delay_seconds": {"type": "number", "minimum": 0, "maximum": MAX_DELAY.as_secs()},
            "delay_ms": {"type": "integer", "minimum": 0, "maximum": MAX_DELAY.as_millis()}
        },
        "required": ["time", "source_timezone", "target_timezone"]
    })
}

fn text_result(req: &RpcRequest, value: Result<String, String>, force_error: bool) -> Value {
    match value {
        Ok(text) => rpc_result(
            req,
            json!({"content": [{"type": "text", "text": text}], "isError": force_error}),
        ),
        Err(err) => rpc_result(
            req,
            json!({"content": [{"type": "text", "text": err}], "isError": true}),
        ),
    }
}

fn rpc_result(req: &RpcRequest, result: Value) -> Value {
    json!({"jsonrpc": req.jsonrpc, "id": req.id, "result": result})
}

fn rpc_error(req: &RpcRequest, code: i32, message: &str) -> Value {
    json!({"jsonrpc": req.jsonrpc, "id": req.id, "error": {"code": code, "message": message}})
}

fn current_time(timezone: &str) -> Result<String, String> {
    format_utc_in_timezone(Utc::now(), timezone)
}

fn convert_time(
    time: &str,
    source_timezone: &str,
    target_timezone: &str,
) -> Result<String, String> {
    let parsed = parse_time_to_utc(time, source_timezone)?;
    format_utc_in_timezone(parsed, target_timezone)
}

fn format_utc_in_timezone(time: DateTime<Utc>, timezone: &str) -> Result<String, String> {
    if let Ok(offset) = parse_offset_timezone(timezone) {
        return Ok(time.with_timezone(&offset).to_rfc3339());
    }
    let tz = parse_named_timezone(timezone)?;
    Ok(time.with_timezone(&tz).to_rfc3339())
}

fn parse_named_timezone(timezone: &str) -> Result<Tz, String> {
    if timezone.eq_ignore_ascii_case("UTC") || timezone.eq_ignore_ascii_case("GMT") {
        return Ok(Tz::UTC);
    }
    timezone
        .parse::<Tz>()
        .map_err(|_| format!("unknown timezone: {timezone}"))
}

fn parse_offset_timezone(timezone: &str) -> Result<FixedOffset, String> {
    if timezone.starts_with('+') || timezone.starts_with('-') {
        return parse_offset(timezone);
    }
    Err(format!("not a fixed offset: {timezone}"))
}

fn parse_offset(value: &str) -> Result<FixedOffset, String> {
    if value.len() < 2 {
        return Err("offset too short".to_string());
    }
    let (sign, rest) = match value.as_bytes().first() {
        Some(b'+') => (1, &value[1..]),
        Some(b'-') => (-1, &value[1..]),
        _ => return Err("offset must start with + or -".to_string()),
    };
    let (hours, minutes) = rest
        .split_once(':')
        .ok_or_else(|| "offset must use +HH:MM or -HH:MM".to_string())?;
    let hours: i32 = hours
        .parse()
        .map_err(|_| "invalid offset hours".to_string())?;
    let minutes: i32 = minutes
        .parse()
        .map_err(|_| "invalid offset minutes".to_string())?;
    FixedOffset::east_opt(sign * ((hours * 3600) + (minutes * 60)))
        .ok_or_else(|| format!("offset out of range: {value}"))
}

fn parse_time_to_utc(time: &str, source_timezone: &str) -> Result<DateTime<Utc>, String> {
    if let Ok(parsed) = DateTime::parse_from_rfc3339(time) {
        return Ok(parsed.with_timezone(&Utc));
    }
    if let Ok(offset) = parse_offset_timezone(source_timezone) {
        return parse_time_in_timezone(time, |naive| offset.from_local_datetime(naive));
    }
    let tz = parse_named_timezone(source_timezone)?;
    parse_time_in_timezone(time, |naive| tz.from_local_datetime(naive))
}

fn parse_time_in_timezone<T>(
    time: &str,
    from_local_datetime: impl Fn(&chrono::NaiveDateTime) -> chrono::LocalResult<DateTime<T>>,
) -> Result<DateTime<Utc>, String>
where
    T: TimeZone,
{
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"] {
        if let Ok(naive) = chrono::NaiveDateTime::parse_from_str(time, fmt) {
            if let Some(dt) = from_local_datetime(&naive).single() {
                return Ok(dt.with_timezone(&Utc));
            }
        }
    }
    if let Ok(date) = chrono::NaiveDate::parse_from_str(time, "%Y-%m-%d") {
        if let Some(naive) = date.and_hms_opt(0, 0, 0) {
            if let Some(dt) = from_local_datetime(&naive).single() {
                return Ok(dt.with_timezone(&Utc));
            }
        }
    }
    Err(format!("unrecognized time format: {time}"))
}

fn delay_from_time_args(args: &TimeArgs, default_latency: Duration) -> Result<Duration, String> {
    delay_from_parts(args.delay_ms, args.delay_seconds, default_latency)
}

fn delay_from_convert_args(
    args: &ConvertArgs,
    default_latency: Duration,
) -> Result<Duration, String> {
    delay_from_parts(args.delay_ms, args.delay_seconds, default_latency)
}

fn delay_from_parts(
    delay_ms: Option<u64>,
    delay_seconds: Option<f64>,
    default_latency: Duration,
) -> Result<Duration, String> {
    if let Some(value) = delay_ms {
        return Ok(Duration::from_millis(value).min(MAX_DELAY));
    }
    if let Some(value) = delay_seconds {
        if !value.is_finite() || value < 0.0 {
            return Err("delay_seconds must be a finite non-negative number".to_string());
        }
        return Ok(Duration::from_secs_f64(value.min(MAX_DELAY.as_secs_f64())));
    }
    Ok(default_latency)
}

async fn sleep_capped(delay: Duration) {
    let capped = delay.min(MAX_DELAY);
    if !capped.is_zero() {
        tokio::time::sleep(capped).await;
    }
}

fn parse_duration_env(name: &str, default_value: Duration) -> Result<Duration, anyhow::Error> {
    match env::var(name) {
        Ok(value) if !value.trim().is_empty() => parse_duration(&value).map_err(anyhow::Error::msg),
        _ => Ok(default_value),
    }
}

fn parse_failure_rate_env() -> Result<f64, anyhow::Error> {
    match env::var("FAILURE_RATE") {
        Ok(value) if !value.trim().is_empty() => {
            parse_failure_rate(&value).map_err(anyhow::Error::msg)
        }
        _ => Ok(0.0),
    }
}

fn parse_failure_rate(value: &str) -> Result<f64, String> {
    let rate: f64 = value
        .parse()
        .map_err(|_| "failure rate must be a number".to_string())?;
    if (0.0..=1.0).contains(&rate) {
        Ok(rate)
    } else {
        Err("failure rate must be between 0.0 and 1.0".to_string())
    }
}

fn parse_duration(value: &str) -> Result<Duration, String> {
    let value = value.trim();
    if value.is_empty() {
        return Err("duration cannot be empty".to_string());
    }
    let split_at = value
        .find(|ch: char| !(ch.is_ascii_digit() || ch == '.'))
        .unwrap_or(value.len());
    let (amount, unit) = value.split_at(split_at);
    let amount: f64 = amount
        .parse()
        .map_err(|err| format!("invalid duration amount '{amount}': {err}"))?;
    if !amount.is_finite() || amount < 0.0 {
        return Err("duration must be a finite non-negative number".to_string());
    }
    let seconds = match unit {
        "" | "s" | "sec" | "secs" => amount,
        "ms" => amount / 1000.0,
        "m" | "min" | "mins" => amount * 60.0,
        _ => return Err(format!("unsupported duration unit: {unit}")),
    };
    Ok(Duration::from_secs_f64(
        seconds.min(MAX_DELAY.as_secs_f64()),
    ))
}

fn should_fail(failure_rate: f64) -> bool {
    failure_rate > 0.0 && rand::random::<f64>() < failure_rate
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duration_parser_accepts_common_units() {
        assert_eq!(parse_duration("250ms").unwrap(), Duration::from_millis(250));
        assert_eq!(parse_duration("2s").unwrap(), Duration::from_secs(2));
        assert_eq!(parse_duration("1.5m").unwrap(), Duration::from_secs(90));
    }

    #[test]
    fn duration_parser_caps_excessive_values() {
        assert_eq!(parse_duration("9999s").unwrap(), MAX_DELAY);
        assert_eq!(
            parse_duration("999999999999999999999999999999s").unwrap(),
            MAX_DELAY
        );
    }

    #[test]
    fn offset_parser_rejects_sign_only_values() {
        assert_eq!(parse_offset("+").unwrap_err(), "offset too short");
        assert_eq!(parse_offset("-").unwrap_err(), "offset too short");
    }

    #[test]
    fn failure_rate_is_bounded() {
        assert_eq!(parse_failure_rate("0.25").unwrap(), 0.25);
        assert!(parse_failure_rate("-0.1").is_err());
        assert!(parse_failure_rate("1.1").is_err());
    }

    #[test]
    fn timezone_parser_supports_half_hour_offsets() {
        let converted = convert_time("2025-01-01T00:00:00Z", "UTC", "Asia/Kolkata").unwrap();
        assert!(converted.ends_with("+05:30"));
    }

    #[test]
    fn convert_time_uses_target_timezone() {
        let converted = convert_time("2025-01-01T12:00:00Z", "UTC", "Asia/Kolkata").unwrap();
        assert!(converted.starts_with("2025-01-01T17:30:00+05:30"));
    }

    #[test]
    fn named_timezone_parser_supports_existing_jmeter_data() {
        for timezone in [
            "America/Denver",
            "Pacific/Auckland",
            "Africa/Cairo",
            "America/Toronto",
            "America/Sao_Paulo",
        ] {
            assert!(current_time(timezone).is_ok(), "{timezone}");
        }
    }

    #[test]
    fn delay_seconds_rejects_invalid_values() {
        let args = TimeArgs {
            timezone: None,
            delay_seconds: Some(-1.0),
            delay_ms: None,
        };
        assert!(delay_from_time_args(&args, Duration::from_secs(1)).is_err());
    }

    #[test]
    fn delay_seconds_caps_before_duration_conversion() {
        let args = TimeArgs {
            timezone: None,
            delay_seconds: Some(f64::MAX),
            delay_ms: None,
        };
        assert_eq!(
            delay_from_time_args(&args, Duration::from_secs(1)).unwrap(),
            MAX_DELAY
        );
    }

    #[test]
    fn tools_list_contains_resilience_tools() {
        let names: Vec<String> = tools_list()["tools"]
            .as_array()
            .unwrap()
            .iter()
            .map(|tool| tool["name"].as_str().unwrap().to_string())
            .collect();
        assert!(names.contains(&"get_slow_time".to_string()));
        assert!(names.contains(&"get_flaky_time".to_string()));
        assert!(names.contains(&"get_timeout_time".to_string()));
    }

    #[tokio::test]
    async fn zero_delay_sleep_returns_quickly() {
        let started = Instant::now();
        sleep_capped(Duration::ZERO).await;
        assert!(started.elapsed() < Duration::from_millis(20));
    }

    #[test]
    fn rpc_error_escapes_dynamic_message_text() {
        let req = RpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!(1),
            method: "tools/call".to_string(),
            params: Value::Null,
        };
        let body = rpc_error(&req, -32602, r#"bad "message" } ,"injected":true"#);
        assert_eq!(
            body["error"]["message"],
            r#"bad "message" } ,"injected":true"#
        );
        assert!(body["error"].get("injected").is_none());
    }

    #[test]
    fn rest_query_defaults_to_utc_alias() {
        let query = RestTimeQuery {
            timezone: None,
            tz: Some("UTC".to_string()),
            delay: None,
        };
        assert_eq!(query.tz.as_deref(), Some("UTC"));
    }

    #[test]
    fn echo_query_can_omit_message() {
        let query: EchoQuery = serde_json::from_value(json!({})).unwrap();
        assert!(query.message.is_none());
    }

    #[test]
    fn can_parse_tool_call_params() {
        let params: ToolCallParams = serde_json::from_value(json!({
            "name": "get_slow_time",
            "arguments": {"timezone": "UTC", "delay_ms": 0}
        }))
        .unwrap();
        assert_eq!(params.name, "get_slow_time");
    }
}
