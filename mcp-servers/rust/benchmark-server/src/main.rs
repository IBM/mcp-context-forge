// benchmark-server - dynamic MCP server for load and pagination testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use anyhow::Context;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::Utc;
use serde::Deserialize;
use serde_json::{Value, json};
use std::env;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Instant;
use tower_http::cors::CorsLayer;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

const APP_NAME: &str = "benchmark-server";
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const AUTH_TOKEN_ENV: &str = "AUTH_TOKEN";
const BEARER_PREFIX: &str = "Bearer ";

#[derive(Debug, Clone, PartialEq, Eq)]
struct Config {
    listen: String,
    port: u16,
    server_count: u16,
    start_port: u16,
    tools: usize,
    resources: usize,
    prompts: usize,
    tool_size: usize,
    resource_size: usize,
    prompt_size: usize,
    auth_token: Option<String>,
}

#[derive(Clone)]
struct AppState {
    config: Arc<Config>,
    server_index: u16,
    started: Instant,
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
struct ResourceReadParams {
    uri: String,
}

#[derive(Debug, Deserialize)]
struct PromptGetParams {
    name: String,
    #[serde(default)]
    arguments: Value,
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

    let config = Config::from_args(env::args().skip(1))?;
    let mut handles = Vec::with_capacity(config.server_count as usize);
    for index in 0..config.server_count {
        let mut server_config = config.clone();
        server_config.port = config
            .start_port
            .checked_add(index)
            .expect("validated benchmark server port range");
        handles.push(tokio::spawn(serve_one(Arc::new(server_config), index)));
    }

    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("received shutdown signal");
        }
        result = async {
            for handle in handles {
                handle.await??;
            }
            anyhow::Ok(())
        } => {
            result?;
        }
    }
    Ok(())
}

async fn serve_one(config: Arc<Config>, server_index: u16) -> anyhow::Result<()> {
    let bind_address = format!("{}:{}", config.listen, config.port);
    let addr: SocketAddr = bind_address.parse()?;
    let state = AppState {
        config,
        server_index,
        started: Instant::now(),
    };
    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/version", get(version_handler))
        .route("/mcp", post(mcp_handler))
        .route("/", post(mcp_handler))
        .layer(CorsLayer::permissive())
        .with_state(state);

    info!(
        "{} instance {} listening on {}",
        APP_NAME, server_index, addr
    );
    axum::serve(tokio::net::TcpListener::bind(addr).await?, app).await?;
    Ok(())
}

async fn health_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "status": "healthy",
        "name": APP_NAME,
        "version": APP_VERSION,
        "server_index": state.server_index,
        "uptime_seconds": state.started.elapsed().as_secs()
    }))
}

async fn version_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "name": APP_NAME,
        "version": APP_VERSION,
        "mcp_version": "2025-11-25",
        "server_index": state.server_index,
        "tools": state.config.tools,
        "resources": state.config.resources,
        "prompts": state.config.prompts
    }))
}

async fn mcp_handler(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<RpcRequest>,
) -> Response {
    if !is_authorized(&state.config, &headers) {
        return (
            StatusCode::UNAUTHORIZED,
            [("www-authenticate", "Bearer realm=\"MCP Server\"")],
            "Authorization required",
        )
            .into_response();
    }

    Json(match req.method.as_str() {
        "initialize" => rpc_result(
            &req,
            json!({
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "instructions": "Dynamic MCP benchmark server for gateway scale and pagination testing."
            }),
        ),
        "tools/list" => rpc_result(&req, list_tools(&state.config)),
        "tools/call" => match serde_json::from_value::<ToolCallParams>(req.params.clone()) {
            Ok(params) => call_tool(&req, &state, params),
            Err(err) => rpc_error(&req, -32602, &format!("invalid tool call params: {err}")),
        },
        "resources/list" => rpc_result(&req, list_resources(&state.config)),
        "resources/read" => {
            match serde_json::from_value::<ResourceReadParams>(req.params.clone()) {
                Ok(params) => read_resource(&req, &state, params),
                Err(err) => rpc_error(
                    &req,
                    -32602,
                    &format!("invalid resource read params: {err}"),
                ),
            }
        }
        "prompts/list" => rpc_result(&req, list_prompts(&state.config)),
        "prompts/get" => match serde_json::from_value::<PromptGetParams>(req.params.clone()) {
            Ok(params) => get_prompt(&req, &state, params),
            Err(err) => rpc_error(&req, -32602, &format!("invalid prompt get params: {err}")),
        },
        _ => rpc_error(&req, -32601, &format!("method not found: {}", req.method)),
    })
    .into_response()
}

fn list_tools(config: &Config) -> Value {
    let tools: Vec<Value> = (0..config.tools)
        .map(|index| {
            json!({
                "name": format!("benchmark_tool_{index}"),
                "description": format!("Generated benchmark tool {index}"),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string"},
                        "payload_size": {"type": "integer", "minimum": 0}
                    }
                }
            })
        })
        .collect();
    json!({ "tools": tools })
}

fn call_tool(req: &RpcRequest, state: &AppState, params: ToolCallParams) -> Value {
    let Some(index) = parse_index(&params.name, "benchmark_tool_") else {
        return rpc_error(req, -32602, &format!("unknown tool: {}", params.name));
    };
    if index >= state.config.tools {
        return rpc_error(req, -32602, &format!("unknown tool: {}", params.name));
    }
    let payload = generate_payload(&params.name, state.config.tool_size);
    rpc_result(
        req,
        json!({
            "content": [{
                "type": "text",
                "text": json!({
                    "tool": params.name,
                    "server_index": state.server_index,
                    "timestamp": Utc::now().to_rfc3339(),
                    "arguments": params.arguments,
                    "data": payload
                }).to_string()
            }],
            "isError": false
        }),
    )
}

fn list_resources(config: &Config) -> Value {
    let resources: Vec<Value> = (0..config.resources)
        .map(|index| {
            json!({
                "uri": format!("benchmark://resource/{index}"),
                "name": format!("benchmark_resource_{index}"),
                "description": format!("Generated benchmark resource {index}"),
                "mimeType": "application/json"
            })
        })
        .collect();
    json!({ "resources": resources })
}

fn read_resource(req: &RpcRequest, state: &AppState, params: ResourceReadParams) -> Value {
    let Some(index) = parse_index(&params.uri, "benchmark://resource/") else {
        return rpc_error(req, -32602, &format!("unknown resource: {}", params.uri));
    };
    if index >= state.config.resources {
        return rpc_error(req, -32602, &format!("unknown resource: {}", params.uri));
    }
    let payload = generate_payload(&params.uri, state.config.resource_size);
    rpc_result(
        req,
        json!({
            "contents": [{
                "uri": params.uri,
                "mimeType": "application/json",
                "text": json!({
                    "resource": format!("benchmark_resource_{index}"),
                    "server_index": state.server_index,
                    "timestamp": Utc::now().to_rfc3339(),
                    "data": payload
                }).to_string()
            }]
        }),
    )
}

fn list_prompts(config: &Config) -> Value {
    let prompts: Vec<Value> = (0..config.prompts)
        .map(|index| {
            json!({
                "name": format!("benchmark_prompt_{index}"),
                "description": format!("Generated benchmark prompt {index}"),
                "arguments": [{"name": "topic", "description": "Optional benchmark topic", "required": false}]
            })
        })
        .collect();
    json!({ "prompts": prompts })
}

fn get_prompt(req: &RpcRequest, state: &AppState, params: PromptGetParams) -> Value {
    let Some(index) = parse_index(&params.name, "benchmark_prompt_") else {
        return rpc_error(req, -32602, &format!("unknown prompt: {}", params.name));
    };
    if index >= state.config.prompts {
        return rpc_error(req, -32602, &format!("unknown prompt: {}", params.name));
    }
    let payload = generate_payload(&params.name, state.config.prompt_size);
    rpc_result(
        req,
        json!({
            "description": format!("Generated benchmark prompt {index}"),
            "messages": [{
                "role": "user",
                "content": {
                    "type": "text",
                    "text": json!({
                        "prompt": params.name,
                        "server_index": state.server_index,
                        "arguments": params.arguments,
                        "data": payload
                    }).to_string()
                }
            }]
        }),
    )
}

fn rpc_result(req: &RpcRequest, result: Value) -> Value {
    json!({"jsonrpc": req.jsonrpc, "id": req.id, "result": result})
}

fn rpc_error(req: &RpcRequest, code: i32, message: &str) -> Value {
    json!({"jsonrpc": req.jsonrpc, "id": req.id, "error": {"code": code, "message": message}})
}

fn generate_payload(name: &str, size: usize) -> String {
    let base = format!("Response from {name}. ");
    if size <= base.len() {
        return base[..size].to_string();
    }
    let filler = "This is benchmark data. ";
    let mut result = String::with_capacity(size);
    result.push_str(&base);
    while result.len() < size {
        result.push_str(filler);
    }
    result.truncate(size);
    result
}

fn parse_index(value: &str, prefix: &str) -> Option<usize> {
    value.strip_prefix(prefix)?.parse().ok()
}

fn is_authorized(config: &Config, headers: &HeaderMap) -> bool {
    let Some(expected_token) = &config.auth_token else {
        return true;
    };
    let Some(header_value) = headers.get("authorization") else {
        return false;
    };
    let Ok(header_text) = header_value.to_str() else {
        return false;
    };
    header_text
        .strip_prefix(BEARER_PREFIX)
        .is_some_and(|provided_token| provided_token == expected_token)
}

impl Config {
    fn from_args<I>(args: I) -> anyhow::Result<Self>
    where
        I: IntoIterator<Item = String>,
    {
        Self::from_args_with_env(
            args,
            env::var(AUTH_TOKEN_ENV)
                .ok()
                .filter(|token| !token.is_empty()),
        )
    }

    fn from_args_with_env<I>(args: I, env_token: Option<String>) -> anyhow::Result<Self>
    where
        I: IntoIterator<Item = String>,
    {
        let mut start_port = None;
        let mut config = Self {
            listen: "0.0.0.0".to_string(),
            port: 8080,
            server_count: 1,
            start_port: 8080,
            tools: 100,
            resources: 100,
            prompts: 100,
            tool_size: 1000,
            resource_size: 1000,
            prompt_size: 1000,
            auth_token: None,
        };
        for arg in args {
            let (key, value) = parse_flag(&arg)?;
            match key {
                "listen" => config.listen = value.to_string(),
                "port" => config.port = parse_flag_value(key, value)?,
                "server-count" => config.server_count = parse_flag_value(key, value)?,
                "start-port" => start_port = Some(parse_flag_value(key, value)?),
                "tools" => config.tools = parse_flag_value(key, value)?,
                "resources" => config.resources = parse_flag_value(key, value)?,
                "prompts" => config.prompts = parse_flag_value(key, value)?,
                "tool-size" | "payload-size" => config.tool_size = parse_flag_value(key, value)?,
                "resource-size" => config.resource_size = parse_flag_value(key, value)?,
                "prompt-size" => config.prompt_size = parse_flag_value(key, value)?,
                "auth-token" => config.auth_token = Some(value.to_string()),
                "transport" => {}
                _ => anyhow::bail!("unknown flag: --{key}"),
            }
        }
        config.start_port = start_port.unwrap_or(config.port);
        if let Some(env_token) = env_token {
            config.auth_token = Some(env_token);
        }
        if config.server_count == 0 {
            anyhow::bail!("server-count must be greater than zero");
        }
        let last_port = u32::from(config.start_port) + u32::from(config.server_count) - 1;
        if last_port > u32::from(u16::MAX) {
            anyhow::bail!(
                "server-count and start-port exceed valid TCP port range: last port would be {last_port}"
            );
        }
        Ok(config)
    }
}

fn parse_flag(arg: &str) -> anyhow::Result<(&str, &str)> {
    let Some(trimmed) = arg.strip_prefix("--").or_else(|| arg.strip_prefix('-')) else {
        anyhow::bail!("unexpected argument: {arg}");
    };
    let Some((key, value)) = trimmed.split_once('=') else {
        anyhow::bail!("malformed flag, expected --name=value: {arg}");
    };
    Ok((key, value))
}

fn parse_flag_value<T>(key: &str, value: &str) -> anyhow::Result<T>
where
    T: std::str::FromStr,
    T::Err: std::error::Error + Send + Sync + 'static,
{
    value
        .parse()
        .with_context(|| format!("invalid value for --{key}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn payload_generation_returns_exact_size() {
        assert_eq!(generate_payload("tool", 3).len(), 3);
        assert_eq!(generate_payload("tool", 128).len(), 128);
    }

    #[test]
    fn parses_go_style_flags() {
        let config = Config::from_args_with_env(
            [
                "-transport=http".to_string(),
                "-server-count=3".to_string(),
                "-start-port=9000".to_string(),
                "-tools=10".to_string(),
                "-resources=5".to_string(),
                "-prompts=2".to_string(),
                "-payload-size=64".to_string(),
                "-auth-token=secret".to_string(),
            ],
            None,
        )
        .unwrap();
        assert_eq!(config.server_count, 3);
        assert_eq!(config.start_port, 9000);
        assert_eq!(config.tools, 10);
        assert_eq!(config.resources, 5);
        assert_eq!(config.prompts, 2);
        assert_eq!(config.tool_size, 64);
        assert_eq!(config.auth_token.as_deref(), Some("secret"));
    }

    #[test]
    fn explicit_default_start_port_is_preserved() {
        let config = Config::from_args_with_env(
            ["-port=9000".to_string(), "-start-port=8080".to_string()],
            None,
        )
        .unwrap();
        assert_eq!(config.port, 9000);
        assert_eq!(config.start_port, 8080);
    }

    #[test]
    fn missing_start_port_defaults_to_port() {
        let config = Config::from_args_with_env(["-port=9000".to_string()], None).unwrap();
        assert_eq!(config.start_port, 9000);
    }

    #[test]
    fn rejects_port_range_overflow() {
        let err = Config::from_args_with_env(
            [
                "-start-port=65535".to_string(),
                "-server-count=2".to_string(),
            ],
            None,
        )
        .unwrap_err();
        assert!(err.to_string().contains("exceed valid TCP port range"));
    }

    #[test]
    fn rejects_unknown_and_malformed_flags() {
        let err = Config::from_args_with_env(["--toosl=1000".to_string()], None).unwrap_err();
        assert!(err.to_string().contains("unknown flag: --toosl"));

        let err = Config::from_args_with_env(["-tools".to_string()], None).unwrap_err();
        assert!(err.to_string().contains("malformed flag"));
    }

    #[test]
    fn invalid_flag_values_include_flag_name() {
        let err = Config::from_args_with_env(["-tools=abc".to_string()], None).unwrap_err();
        assert!(err.to_string().contains("invalid value for --tools"));
    }

    #[test]
    fn auth_token_requires_matching_bearer_header() {
        let config = Config::from_args_with_env(["-auth-token=secret".to_string()], None).unwrap();
        let mut headers = HeaderMap::new();

        assert!(!is_authorized(&config, &headers));

        headers.insert("authorization", "Bearer wrong".parse().unwrap());
        assert!(!is_authorized(&config, &headers));

        headers.insert("authorization", "Bearer secret".parse().unwrap());
        assert!(is_authorized(&config, &headers));
    }

    #[test]
    fn missing_auth_token_allows_requests() {
        let config = Config::from_args_with_env(std::iter::empty(), None).unwrap();
        assert!(is_authorized(&config, &HeaderMap::new()));
    }

    #[test]
    fn auth_token_env_overrides_flag() {
        let config = Config::from_args_with_env(
            ["-auth-token=flag-secret".to_string()],
            Some("env-secret".to_string()),
        )
        .unwrap();
        assert_eq!(config.auth_token.as_deref(), Some("env-secret"));
    }

    #[test]
    fn dynamic_lists_match_configured_counts() {
        let config = Config {
            listen: "127.0.0.1".to_string(),
            port: 8080,
            server_count: 1,
            start_port: 8080,
            tools: 2,
            resources: 3,
            prompts: 4,
            tool_size: 10,
            resource_size: 10,
            prompt_size: 10,
            auth_token: None,
        };
        assert_eq!(list_tools(&config)["tools"].as_array().unwrap().len(), 2);
        assert_eq!(
            list_resources(&config)["resources"]
                .as_array()
                .unwrap()
                .len(),
            3
        );
        assert_eq!(
            list_prompts(&config)["prompts"].as_array().unwrap().len(),
            4
        );
    }

    #[test]
    fn unknown_tool_returns_jsonrpc_error() {
        let req = RpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!(1),
            method: "tools/call".to_string(),
            params: Value::Null,
        };
        let state = AppState {
            config: Arc::new(Config::from_args_with_env(["-tools=1".to_string()], None).unwrap()),
            server_index: 0,
            started: Instant::now(),
        };
        let response = call_tool(
            &req,
            &state,
            ToolCallParams {
                name: "benchmark_tool_99".to_string(),
                arguments: Value::Null,
            },
        );
        assert_eq!(response["error"]["code"], -32602);
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
}
