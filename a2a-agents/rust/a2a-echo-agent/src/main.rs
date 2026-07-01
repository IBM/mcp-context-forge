// a2a-echo-agent - lightweight Rust A2A echo agent for integration testing
//
// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::StatusCode;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::{DateTime, Utc};
use futures::stream::{self, Stream};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::VecDeque;
use std::convert::Infallible;
use std::env;
use std::net::SocketAddr;
use std::sync::{Arc, RwLock, RwLockReadGuard, RwLockWriteGuard};
use std::time::Duration;
use tower_http::cors::CorsLayer;
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
use uuid::Uuid;

const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const DEFAULT_ADDR: &str = "0.0.0.0:9100";
const DEFAULT_NAME: &str = "a2a-echo-agent";
const DEFAULT_PROTOCOL_VERSION: &str = "1.0.0";
const MAX_REQUEST_BODY_BYTES: usize = 1_048_576;
const MAX_STORED_TASKS: usize = 10_000;

#[derive(Clone)]
struct AppState {
    config: Arc<Config>,
    tasks: Arc<RwLock<TaskStore>>,
}

#[derive(Clone)]
struct Config {
    name: String,
    protocol_version: String,
    fixed_response: Option<String>,
    public_url: Option<String>,
}

#[derive(Default)]
struct TaskStore {
    order: VecDeque<String>,
    tasks: std::collections::HashMap<String, StoredTask>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StoredTask {
    id: String,
    context_id: String,
    input_text: String,
    output_text: String,
    state: String,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
struct JsonRpcRequest {
    #[serde(default = "jsonrpc_version")]
    jsonrpc: String,
    #[serde(default)]
    id: Value,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Debug, Serialize)]
struct JsonRpcResponse {
    jsonrpc: String,
    #[serde(skip_serializing_if = "Value::is_null")]
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
}

#[derive(Debug, Serialize)]
struct JsonRpcError {
    code: i32,
    message: String,
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

    let addr = env::var("A2A_ECHO_ADDR").unwrap_or_else(|_| DEFAULT_ADDR.to_string());
    let config = Config {
        name: env::var("A2A_ECHO_NAME").unwrap_or_else(|_| DEFAULT_NAME.to_string()),
        protocol_version: env::var("A2A_ECHO_PROTOCOL_VERSION")
            .unwrap_or_else(|_| DEFAULT_PROTOCOL_VERSION.to_string()),
        fixed_response: env::var("A2A_ECHO_FIXED_RESPONSE")
            .ok()
            .filter(|value| !value.trim().is_empty()),
        public_url: env::var("A2A_ECHO_PUBLIC_URL")
            .ok()
            .filter(|value| !value.trim().is_empty()),
    };
    let state = AppState {
        config: Arc::new(config),
        tasks: Arc::new(RwLock::new(TaskStore::default())),
    };

    let app = Router::new()
        .route("/", get(root_handler).post(jsonrpc_handler))
        .route("/run", post(run_handler))
        .route("/health", get(health_handler))
        .route("/.well-known/agent-card.json", get(agent_card_handler))
        .route("/.well-known/agent.json", get(agent_card_handler))
        .route("/extendedAgentCard", get(extended_agent_card_handler))
        .layer(CorsLayer::permissive())
        .layer(DefaultBodyLimit::max(MAX_REQUEST_BODY_BYTES))
        .with_state(state);

    let addr: SocketAddr = addr.parse()?;
    info!("{} v{} listening on {}", DEFAULT_NAME, APP_VERSION, addr);
    axum::serve(tokio::net::TcpListener::bind(addr).await?, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    Ok(())
}

async fn root_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "name": state.config.name,
        "version": APP_VERSION,
        "protocol_version": state.config.protocol_version,
        "status": "running"
    }))
}

async fn health_handler(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "status": "healthy",
        "name": state.config.name,
        "version": APP_VERSION
    }))
}

async fn agent_card_handler(State(state): State<AppState>) -> Json<Value> {
    Json(agent_card(
        &state.config,
        state
            .config
            .public_url
            .as_deref()
            .unwrap_or("http://localhost:9100"),
    ))
}

async fn extended_agent_card_handler(State(state): State<AppState>) -> Json<Value> {
    Json(extended_agent_card(
        &state.config,
        state
            .config
            .public_url
            .as_deref()
            .unwrap_or("http://localhost:9100"),
    ))
}

async fn jsonrpc_handler(State(state): State<AppState>, body: Bytes) -> Response {
    if let Ok(parsed) = serde_json::from_slice::<Value>(&body) {
        if let Some(method) = parsed.get("method").and_then(Value::as_str) {
            if matches!(method, "SendStreamingMessage" | "message/stream") {
                return streaming_jsonrpc_response(state.clone(), parsed).into_response();
            }
            if matches!(method, "SubscribeToTask" | "tasks/resubscribe") {
                return streaming_subscribe_response(state.clone(), parsed).into_response();
            }
        }
    }
    (StatusCode::OK, Json(handle_jsonrpc_body(&state, &body))).into_response()
}

/// Test-driving directive for streaming dispatch. Tests embed
/// `stream:chunks=N,delay_ms=M` as the message text prefix to drive a
/// specific chunk count and per-chunk delay. Without the prefix the
/// agent yields a single chunk and closes (default behavior — the
/// shape compatibility tests rely on at-least-one chunk).
#[derive(Debug, Clone, Copy)]
struct StreamDirective {
    chunks: usize,
    delay_ms: u64,
}

impl Default for StreamDirective {
    fn default() -> Self {
        Self {
            chunks: 1,
            delay_ms: 0,
        }
    }
}

/// Parse `stream:chunks=N,delay_ms=M` from a text part. Missing or
/// unparseable values fall back to the default (1 chunk, no delay)
/// so non-test traffic always sees the simplest viable stream shape.
fn parse_stream_directive(text: &str) -> StreamDirective {
    let Some(rest) = text.strip_prefix("stream:") else {
        return StreamDirective::default();
    };
    let mut directive = StreamDirective::default();
    for piece in rest.split(',') {
        if let Some((key, value)) = piece.split_once('=') {
            match key.trim() {
                "chunks" => {
                    if let Ok(n) = value.trim().parse::<usize>() {
                        directive.chunks = n.max(1);
                    }
                }
                "delay_ms" => {
                    if let Ok(n) = value.trim().parse::<u64>() {
                        directive.delay_ms = n;
                    }
                }
                _ => {}
            }
        }
    }
    directive
}

/// Build an SSE response that emits one or more JSON-RPC envelopes
/// for streaming dispatch. Intermediate chunks advertise the task in
/// `working` state; the final chunk advertises `completed`. Each
/// chunk is a complete JSON-RPC envelope (matches what the gateway's
/// `dispatch_a2a_jsonrpc_streaming` expects to parse out of `data:`
/// lines).
fn streaming_jsonrpc_response(
    state: AppState,
    parsed: Value,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let id = parsed.get("id").cloned().unwrap_or(Value::Null);
    let method = parsed
        .get("method")
        .and_then(Value::as_str)
        .unwrap_or("SendStreamingMessage")
        .to_string();
    let jsonrpc = parsed
        .get("jsonrpc")
        .and_then(Value::as_str)
        .unwrap_or("2.0")
        .to_string();
    let params = parsed.get("params").cloned().unwrap_or(Value::Null);
    let text = extract_text(&params).unwrap_or_default();
    let directive = parse_stream_directive(&text);
    let output_text = echo_text(&state.config, &text);
    let use_v1 = uses_v1_method(&method);

    let final_task = StoredTask {
        id: Uuid::new_v4().to_string(),
        context_id: Uuid::new_v4().to_string(),
        input_text: text,
        output_text,
        state: "completed".to_string(),
        created_at: Utc::now(),
        updated_at: Utc::now(),
    };
    store_task(&state, final_task.clone());

    let chunks_total = directive.chunks;
    let delay = Duration::from_millis(directive.delay_ms);
    let task_arc = Arc::new(final_task);
    let id_arc = Arc::new(id);
    let jsonrpc_arc = Arc::new(jsonrpc);

    let stream = stream::unfold(
        (0usize, task_arc, id_arc, jsonrpc_arc),
        move |(index, task, id, jsonrpc)| async move {
            if index >= chunks_total {
                return None;
            }
            if index > 0 && !delay.is_zero() {
                tokio::time::sleep(delay).await;
            }
            let is_last = index + 1 == chunks_total;
            let mut chunk = (*task).clone();
            chunk.state = if is_last { "completed" } else { "working" }.to_string();
            chunk.updated_at = Utc::now();
            let task_value = task_to_value(&chunk, use_v1);
            let result = if use_v1 {
                json!({ "task": task_value })
            } else {
                task_value
            };
            let envelope = json!({
                "jsonrpc": (*jsonrpc).clone(),
                "id": (*id).clone(),
                "result": result,
            });
            let event = Event::default().data(envelope.to_string());
            Some((Ok::<_, Infallible>(event), (index + 1, task, id, jsonrpc)))
        },
    );

    Sse::new(stream).keep_alive(KeepAlive::default())
}

/// SubscribeToTask MUST stream SSE per A2A 1.0 spec, even when the
/// task is not found -- unary 200 error envelopes are not an
/// acceptable response shape on this method.
fn streaming_subscribe_response(
    state: AppState,
    parsed: Value,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let id = parsed.get("id").cloned().unwrap_or(Value::Null);
    let method = parsed
        .get("method")
        .and_then(Value::as_str)
        .unwrap_or("SubscribeToTask")
        .to_string();
    let jsonrpc = parsed
        .get("jsonrpc")
        .and_then(Value::as_str)
        .unwrap_or("2.0")
        .to_string();
    let params = parsed.get("params").cloned().unwrap_or(Value::Null);

    let envelope = match task_id_from_params(&params) {
        Ok(task_id) => match get_task(&state, &task_id) {
            Some(task) => {
                let use_v1 = uses_v1_method(&method);
                let task_value = task_to_value(&task, use_v1);
                let result = if use_v1 {
                    json!({ "task": task_value })
                } else {
                    task_value
                };
                json!({
                    "jsonrpc": jsonrpc,
                    "id": id,
                    "result": result,
                })
            }
            None => json!({
                "jsonrpc": jsonrpc,
                "id": id,
                "error": { "code": -32001, "message": "task not found" },
            }),
        },
        Err(err) => json!({
            "jsonrpc": jsonrpc,
            "id": id,
            "error": { "code": -32602, "message": err },
        }),
    };

    let event = Event::default().data(envelope.to_string());
    let stream = stream::once(async move { Ok::<_, Infallible>(event) });
    Sse::new(stream).keep_alive(KeepAlive::default())
}

fn handle_jsonrpc_body(state: &AppState, body: &[u8]) -> JsonRpcResponse {
    // JSON-RPC 2.0 § 5.1 reserves -32700 specifically for "invalid JSON".
    // Well-formed JSON with a malformed envelope is -32600 "Invalid Request",
    // and that includes the common case of `method` being missing.
    let parsed: Value = match serde_json::from_slice(body) {
        Ok(value) => value,
        Err(_) => return rpc_error_with_id(Value::Null, -32700, "parse error"),
    };

    let id = parsed.get("id").cloned().unwrap_or(Value::Null);

    if !parsed.is_object() {
        return rpc_error_with_id(id, -32600, "request must be a JSON object");
    }
    if parsed.get("method").and_then(Value::as_str).is_none() {
        return rpc_error_with_id(id, -32600, "missing or invalid method field");
    }

    match serde_json::from_value::<JsonRpcRequest>(parsed) {
        Ok(req) => dispatch_jsonrpc_request(state, &req),
        Err(_) => rpc_error_with_id(id, -32600, "invalid JSON-RPC envelope"),
    }
}

fn dispatch_jsonrpc_request(state: &AppState, req: &JsonRpcRequest) -> JsonRpcResponse {
    match req.method.as_str() {
        "SendMessage" | "message/send" | "SendStreamingMessage" | "message/stream" => {
            match handle_send_message(state, &req.method, &req.params) {
                Ok(result) => rpc_result(req, result),
                Err(err) => rpc_error(req, -32602, &err),
            }
        }
        "GetTask" | "tasks/get" => match task_id_from_params(&req.params) {
            Ok(id) => match get_task(state, &id) {
                Some(task) => rpc_result(req, task_to_value(&task, uses_v1_method(&req.method))),
                None => rpc_error(req, -32001, "task not found"),
            },
            Err(err) => rpc_error(req, -32602, &err),
        },
        "ListTasks" | "tasks/list" => {
            rpc_result(req, list_tasks(state, uses_v1_method(&req.method)))
        }
        "CancelTask" | "tasks/cancel" => match task_id_from_params(&req.params) {
            Ok(id) => match cancel_task(state, &id) {
                Some(task) => rpc_result(req, task_to_value(&task, uses_v1_method(&req.method))),
                None => rpc_error(req, -32001, "task not found"),
            },
            Err(err) => rpc_error(req, -32602, &err),
        },
        "GetExtendedAgentCard" | "agent/getExtendedCard" | "agent/getAuthenticatedExtendedCard" => {
            rpc_result(
                req,
                extended_agent_card(
                    &state.config,
                    state
                        .config
                        .public_url
                        .as_deref()
                        .unwrap_or("http://localhost:9100"),
                ),
            )
        }
        _ => rpc_error(
            req,
            -32601,
            &format!("method not supported: {}", req.method),
        ),
    }
}

async fn run_handler(State(state): State<AppState>, Json(body): Json<Value>) -> Json<Value> {
    let input = extract_text(&body).unwrap_or_default();
    Json(json!({
        "response": echo_text(&state.config, &input),
        "status": "success",
        "agent_name": state.config.name,
        "timestamp": Utc::now().to_rfc3339()
    }))
}

fn handle_send_message(state: &AppState, method: &str, params: &Value) -> Result<Value, String> {
    let text = extract_text(params).ok_or_else(|| "message text not found".to_string())?;
    let output = echo_text(&state.config, &text);
    let task = StoredTask {
        id: Uuid::new_v4().to_string(),
        context_id: Uuid::new_v4().to_string(),
        input_text: text,
        output_text: output,
        state: "completed".to_string(),
        created_at: Utc::now(),
        updated_at: Utc::now(),
    };
    store_task(state, task.clone());
    let use_v1 = uses_v1_method(method);
    let task_value = task_to_value(&task, use_v1);
    if use_v1 {
        // v1.0.0 SendMessageResponse is a `oneof { Task task; Message message; }`.
        // Wrap the task so SDK protobuf parsing finds it at the right field path.
        // Legacy v0.3.x SDK transport (CompatJsonRpcTransport) tolerates the
        // unwrapped task shape and is left as-is.
        Ok(json!({ "task": task_value }))
    } else {
        Ok(task_value)
    }
}

fn store_task(state: &AppState, task: StoredTask) {
    let mut store = write_task_store(state);
    store.order.push_back(task.id.clone());
    store.tasks.insert(task.id.clone(), task);
    while store.order.len() > MAX_STORED_TASKS {
        if let Some(oldest) = store.order.pop_front() {
            store.tasks.remove(&oldest);
        }
    }
}

fn get_task(state: &AppState, id: &str) -> Option<StoredTask> {
    read_task_store(state).tasks.get(id).cloned()
}

fn cancel_task(state: &AppState, id: &str) -> Option<StoredTask> {
    let mut store = write_task_store(state);
    let task = store.tasks.get_mut(id)?;
    task.state = "canceled".to_string();
    task.updated_at = Utc::now();
    Some(task.clone())
}

fn list_tasks(state: &AppState, use_v1: bool) -> Value {
    let store = read_task_store(state);
    let tasks: Vec<Value> = store
        .order
        .iter()
        .filter_map(|id| store.tasks.get(id))
        .map(|task| task_to_value(task, use_v1))
        .collect();
    json!({ "tasks": tasks })
}

fn read_task_store(state: &AppState) -> RwLockReadGuard<'_, TaskStore> {
    state.tasks.read().unwrap_or_else(|err| err.into_inner())
}

fn write_task_store(state: &AppState) -> RwLockWriteGuard<'_, TaskStore> {
    state.tasks.write().unwrap_or_else(|err| err.into_inner())
}

fn task_to_value(task: &StoredTask, use_v1: bool) -> Value {
    // v1.0.0 Task protobuf has exactly these fields: id, context_id, status,
    // artifacts, history, metadata. createdAt / updatedAt are not in the
    // schema and the SDK parser rejects them. Legacy v0.3.x CompatJsonRpcTransport
    // tolerates extras and historically consumed both timestamps, so we keep
    // them on the legacy shape for back-compat.
    let mut value = json!({
        "id": task.id,
        "contextId": task.context_id,
        "status": {
            "state": render_state(&task.state, use_v1),
            "message": build_message(
                &format!("{}-response", task.id),
                "agent",
                &task.output_text,
                use_v1
            ),
            "timestamp": task.updated_at.to_rfc3339()
        },
        "artifacts": [build_artifact(&format!("{}-artifact", task.id), &task.output_text, use_v1)]
    });
    if !use_v1 {
        value["kind"] = json!("task");
        value["createdAt"] = json!(task.created_at.to_rfc3339());
        value["updatedAt"] = json!(task.updated_at.to_rfc3339());
    }
    value
}

fn uses_v1_method(method: &str) -> bool {
    matches!(
        method,
        "SendMessage"
            | "SendStreamingMessage"
            | "GetTask"
            | "ListTasks"
            | "CancelTask"
            | "SubscribeToTask"
            | "GetExtendedAgentCard"
    )
}

fn build_message(message_id: &str, role: &str, text: &str, use_v1: bool) -> Value {
    if use_v1 {
        json!({
            "messageId": message_id,
            "role": render_role(role, true),
            "parts": [{"text": text}]
        })
    } else {
        json!({
            "kind": "message",
            "messageId": message_id,
            "role": render_role(role, false),
            "parts": [{"kind": "text", "text": text}]
        })
    }
}

fn build_artifact(artifact_id: &str, text: &str, use_v1: bool) -> Value {
    if use_v1 {
        json!({
            "artifactId": artifact_id,
            "name": "echo",
            "description": "Echo response",
            "parts": [{"text": text}]
        })
    } else {
        json!({
            "kind": "artifact",
            "artifactId": artifact_id,
            "name": "echo",
            "description": "Echo response",
            "parts": [{"kind": "text", "text": text}]
        })
    }
}

fn render_state(state: &str, use_v1: bool) -> &'static str {
    let normalized = state.trim().to_ascii_lowercase().replace('-', "_");
    let normalized = normalized
        .strip_prefix("task_state_")
        .unwrap_or(&normalized);
    if !use_v1 {
        return match normalized {
            "submitted" => "submitted",
            "working" => "working",
            "input_required" => "input_required",
            "canceled" | "cancelled" => "canceled",
            "failed" => "failed",
            "auth_required" => "auth_required",
            "rejected" => "rejected",
            _ => "completed",
        };
    }
    match normalized {
        "submitted" => "TASK_STATE_SUBMITTED",
        "working" => "TASK_STATE_WORKING",
        "input_required" => "TASK_STATE_INPUT_REQUIRED",
        "canceled" | "cancelled" => "TASK_STATE_CANCELED",
        "failed" => "TASK_STATE_FAILED",
        "auth_required" => "TASK_STATE_AUTH_REQUIRED",
        "rejected" => "TASK_STATE_REJECTED",
        _ => "TASK_STATE_COMPLETED",
    }
}

fn render_role(role: &str, use_v1: bool) -> &'static str {
    match role.trim().to_ascii_lowercase().as_str() {
        "system" | "role_system" => {
            if use_v1 {
                "ROLE_SYSTEM"
            } else {
                "system"
            }
        }
        "agent" | "role_agent" => {
            if use_v1 {
                "ROLE_AGENT"
            } else {
                "agent"
            }
        }
        _ => {
            if use_v1 {
                "ROLE_USER"
            } else {
                "user"
            }
        }
    }
}

fn task_id_from_params(params: &Value) -> Result<String, String> {
    params
        .get("id")
        .and_then(Value::as_str)
        .or_else(|| params.get("taskId").and_then(Value::as_str))
        .map(str::to_string)
        .ok_or_else(|| "task id is required".to_string())
}

fn echo_text(config: &Config, input: &str) -> String {
    config
        .fixed_response
        .clone()
        .unwrap_or_else(|| format!("Echo: {input}"))
}

fn extract_text(value: &Value) -> Option<String> {
    if let Some(text) = value.get("text").and_then(Value::as_str) {
        return Some(text.to_string());
    }
    if let Some(query) = value.get("query").and_then(Value::as_str) {
        return Some(query.to_string());
    }
    let message = value.get("message").unwrap_or(value);
    let parts = message.get("parts").and_then(Value::as_array)?;
    let mut texts = Vec::new();
    for part in parts {
        if let Some(text) = part.get("text").and_then(Value::as_str) {
            texts.push(text);
        } else if let Some(text) = part
            .get("root")
            .and_then(|root| root.get("text"))
            .and_then(Value::as_str)
        {
            texts.push(text);
        }
    }
    if texts.is_empty() {
        None
    } else {
        Some(texts.join("\n"))
    }
}

fn agent_card(config: &Config, base_url: &str) -> Value {
    // A2A 1.0.0 introduced the supported_interfaces array for transport
    // advertisement and dropped top-level protocol_version / url from the
    // AgentCard protobuf. v0.3.x kept the flat top-level shape. The agent
    // emits whichever shape matches the configured protocol_version so the
    // SDK's ClientFactory parses the card against the right schema.
    if config.protocol_version.starts_with("1.") {
        agent_card_v1(config, base_url)
    } else {
        agent_card_legacy(config, base_url)
    }
}

fn agent_card_v1(config: &Config, base_url: &str) -> Value {
    json!({
        "name": config.name,
        "description": "Rust A2A echo agent for ContextForge integration testing",
        "version": APP_VERSION,
        "capabilities": {
            "streaming": true,
            "pushNotifications": false,
            "stateTransitionHistory": true,
            "echo": true
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "echo",
            "name": "Echo",
            "description": "Echoes user text and stores completed tasks in memory",
            "tags": ["testing", "echo"],
            "examples": ["hello"]
        }],
        "supportedInterfaces": [{
            "protocolBinding": "JSONRPC",
            "protocolVersion": config.protocol_version,
            "url": base_url
        }]
    })
}

fn agent_card_legacy(config: &Config, base_url: &str) -> Value {
    json!({
        "name": config.name,
        "description": "Rust A2A echo agent for ContextForge integration testing",
        "url": base_url,
        "version": APP_VERSION,
        "protocolVersion": config.protocol_version,
        "capabilities": {
            "streaming": true,
            "pushNotifications": false,
            "stateTransitionHistory": true,
            "echo": true
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "echo",
            "name": "Echo",
            "description": "Echoes user text and stores completed tasks in memory",
            "tags": ["testing", "echo"],
            "examples": ["hello"]
        }]
    })
}

fn extended_agent_card(config: &Config, base_url: &str) -> Value {
    let mut card = agent_card(config, base_url);
    card["authenticated"] = json!(false);
    card["endpoints"] = json!({
        "jsonrpc": base_url,
        "health": format!("{base_url}/health"),
        "agentCard": format!("{base_url}/.well-known/agent-card.json"),
        "extendedAgentCard": format!("{base_url}/extendedAgentCard")
    });
    card
}

fn rpc_result(req: &JsonRpcRequest, result: Value) -> JsonRpcResponse {
    JsonRpcResponse {
        jsonrpc: req.jsonrpc.clone(),
        id: req.id.clone(),
        result: Some(result),
        error: None,
    }
}

fn rpc_error(req: &JsonRpcRequest, code: i32, message: &str) -> JsonRpcResponse {
    JsonRpcResponse {
        jsonrpc: req.jsonrpc.clone(),
        id: req.id.clone(),
        result: None,
        error: Some(JsonRpcError {
            code,
            message: message.to_string(),
        }),
    }
}

fn rpc_error_with_id(id: Value, code: i32, message: &str) -> JsonRpcResponse {
    JsonRpcResponse {
        jsonrpc: jsonrpc_version(),
        id,
        result: None,
        error: Some(JsonRpcError {
            code,
            message: message.to_string(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state() -> AppState {
        AppState {
            config: Arc::new(Config {
                name: "a2a-echo-agent".to_string(),
                protocol_version: "1.0.0".to_string(),
                fixed_response: None,
                public_url: Some("http://localhost:9100".to_string()),
            }),
            tasks: Arc::new(RwLock::new(TaskStore::default())),
        }
    }

    #[test]
    fn extracts_v1_message_text() {
        let value = json!({
            "message": {
                "parts": [{"text": "hello"}, {"text": "world"}]
            }
        });
        assert_eq!(extract_text(&value).unwrap(), "hello\nworld");
    }

    #[test]
    fn extracts_run_query_text() {
        assert_eq!(extract_text(&json!({"query": "ping"})).unwrap(), "ping");
    }

    #[test]
    fn stores_and_lists_completed_task() {
        let state = state();
        let result = handle_send_message(
            &state,
            "SendMessage",
            &json!({"message": {"parts": [{"text": "hello"}]}}),
        )
        .unwrap();
        let id = result["task"]["id"].as_str().unwrap();
        assert_eq!(get_task(&state, id).unwrap().output_text, "Echo: hello");
        assert_eq!(
            list_tasks(&state, true)["tasks"].as_array().unwrap().len(),
            1
        );
    }

    #[test]
    fn cancel_marks_task_canceled() {
        let state = state();
        let result = handle_send_message(
            &state,
            "SendMessage",
            &json!({"message": {"parts": [{"text": "hello"}]}}),
        )
        .unwrap();
        let id = result["task"]["id"].as_str().unwrap();
        let task = cancel_task(&state, id).unwrap();
        assert_eq!(task.state, "canceled");
    }

    #[test]
    fn unknown_method_returns_method_not_found() {
        let state = state();
        let req = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!(1),
            method: "Nope".to_string(),
            params: Value::Null,
        };
        let response = dispatch_jsonrpc_request(&state, &req);
        assert_eq!(response.error.unwrap().code, -32601);
    }

    #[test]
    fn missing_task_returns_jsonrpc_error() {
        let state = state();
        let req = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!("req-1"),
            method: "GetTask".to_string(),
            params: json!({"id": "missing"}),
        };
        let response = dispatch_jsonrpc_request(&state, &req);
        let error = response.error.unwrap();
        assert_eq!(error.code, -32001);
        assert_eq!(error.message, "task not found");
    }

    #[test]
    fn cancel_missing_task_returns_jsonrpc_error() {
        let state = state();
        let req = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!("req-1"),
            method: "CancelTask".to_string(),
            params: json!({"id": "missing"}),
        };
        let response = dispatch_jsonrpc_request(&state, &req);
        let error = response.error.unwrap();
        assert_eq!(error.code, -32001);
        assert_eq!(error.message, "task not found");
    }

    #[test]
    fn missing_task_id_returns_invalid_params() {
        assert_eq!(
            task_id_from_params(&json!({"other": "missing"})).unwrap_err(),
            "task id is required"
        );
    }

    #[test]
    fn store_task_evicts_oldest_entries() {
        let state = state();
        for index in 0..=MAX_STORED_TASKS {
            store_task(
                &state,
                StoredTask {
                    id: format!("task-{index}"),
                    context_id: format!("context-{index}"),
                    input_text: "input".to_string(),
                    output_text: "output".to_string(),
                    state: "completed".to_string(),
                    created_at: Utc::now(),
                    updated_at: Utc::now(),
                },
            );
        }
        assert!(get_task(&state, "task-0").is_none());
        assert!(get_task(&state, "task-1").is_some());
        assert_eq!(
            list_tasks(&state, true)["tasks"].as_array().unwrap().len(),
            MAX_STORED_TASKS
        );
    }

    #[test]
    fn extract_text_returns_none_for_empty_or_garbage_input() {
        assert!(extract_text(&json!({})).is_none());
        assert!(extract_text(&json!({"message": {"parts": [{"kind": "text"}]}})).is_none());
    }

    #[test]
    fn malformed_json_returns_parse_error_envelope() {
        let state = state();
        let response = handle_jsonrpc_body(&state, br#"{"jsonrpc":"2.0","method":"SendMessage""#);
        let error = response.error.unwrap();
        assert_eq!(error.code, -32700);
        assert_eq!(response.id, Value::Null);
    }

    #[test]
    fn send_message_uses_v1_task_shape() {
        let state = state();
        let result = handle_send_message(
            &state,
            "SendMessage",
            &json!({"message": {"parts": [{"text": "hello"}]}}),
        )
        .unwrap();

        let task = &result["task"];
        assert!(
            task.is_object(),
            "v1 send_message must wrap the task in a SendMessageResponse oneof"
        );
        assert!(
            result.get("kind").is_none(),
            "v1 SendMessageResponse envelope must not carry a kind discriminator"
        );
        assert!(
            task.get("kind").is_none(),
            "v1 Task must not carry a kind discriminator (v0.3.x-only field)"
        );
        assert!(
            task.get("createdAt").is_none(),
            "v1 Task must not emit createdAt (not in v1.0.0 protobuf schema)"
        );
        assert!(
            task.get("updatedAt").is_none(),
            "v1 Task must not emit updatedAt (not in v1.0.0 protobuf schema)"
        );
        assert_eq!(task["status"]["state"], "TASK_STATE_COMPLETED");
        assert_eq!(task["status"]["message"]["role"], "ROLE_AGENT");
        assert_eq!(task["status"]["message"]["parts"][0]["text"], "Echo: hello");
        assert!(task["status"]["message"]["parts"][0].get("kind").is_none());
        assert_eq!(task["artifacts"][0]["parts"][0]["text"], "Echo: hello");
        assert!(task["artifacts"][0]["parts"][0].get("kind").is_none());
    }

    #[test]
    fn legacy_message_send_uses_legacy_task_shape() {
        let state = state();
        let result = handle_send_message(
            &state,
            "message/send",
            &json!({"message": {"parts": [{"text": "hello"}]}}),
        )
        .unwrap();

        assert_eq!(result["kind"], "task");
        assert_eq!(result["status"]["state"], "completed");
        assert_eq!(result["status"]["message"]["kind"], "message");
        assert_eq!(result["status"]["message"]["role"], "agent");
        assert_eq!(result["status"]["message"]["parts"][0]["kind"], "text");
        assert_eq!(result["artifacts"][0]["kind"], "artifact");
        assert_eq!(result["artifacts"][0]["parts"][0]["kind"], "text");
    }

    #[test]
    fn agent_card_v1_uses_supported_interfaces_shape() {
        let config = Config {
            name: "a2a-echo-agent".to_string(),
            protocol_version: "1.0.0".to_string(),
            fixed_response: None,
            public_url: None,
        };
        let card = agent_card(&config, "http://localhost:9100");
        assert_eq!(card["name"], "a2a-echo-agent");
        assert!(
            card.get("protocolVersion").is_none(),
            "v1 card must not advertise protocolVersion at the top level"
        );
        assert!(
            card.get("url").is_none(),
            "v1 card must not advertise url at the top level"
        );
        let interfaces = card["supportedInterfaces"].as_array().unwrap();
        assert_eq!(interfaces.len(), 1);
        assert_eq!(interfaces[0]["protocolBinding"], "JSONRPC");
        assert_eq!(interfaces[0]["protocolVersion"], "1.0.0");
        assert_eq!(interfaces[0]["url"], "http://localhost:9100");
        assert_eq!(card["skills"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn agent_card_legacy_uses_top_level_shape() {
        let config = Config {
            name: "a2a-echo-agent".to_string(),
            protocol_version: "0.3.0".to_string(),
            fixed_response: None,
            public_url: None,
        };
        let card = agent_card(&config, "http://localhost:9100");
        assert_eq!(card["name"], "a2a-echo-agent");
        assert_eq!(card["protocolVersion"], "0.3.0");
        assert_eq!(card["url"], "http://localhost:9100");
        assert!(
            card.get("supportedInterfaces").is_none(),
            "v0.3.x card must not emit supportedInterfaces (v1.0.0-only field)"
        );
        assert_eq!(card["skills"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn missing_method_returns_invalid_request_envelope() {
        let state = state();
        let response =
            handle_jsonrpc_body(&state, br#"{"jsonrpc":"2.0","id":"req-1","params":{}}"#);
        let error = response.error.unwrap();
        assert_eq!(
            error.code, -32600,
            "JSON-RPC 2.0 reserves -32600 for envelopes missing required fields"
        );
        assert_eq!(response.id, json!("req-1"));
    }

    #[test]
    fn fixed_response_overrides_echo() {
        let config = Config {
            name: "a2a-echo-agent".to_string(),
            protocol_version: "1.0.0".to_string(),
            fixed_response: Some("fixed".to_string()),
            public_url: None,
        };
        assert_eq!(echo_text(&config, "hello"), "fixed");
    }

    #[test]
    fn rpc_error_serializes_safely() {
        let req = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id: json!(1),
            method: "unknown".to_string(),
            params: Value::Null,
        };
        let response = serde_json::to_value(rpc_error(&req, -32601, r#"bad "message""#)).unwrap();
        assert_eq!(response["error"]["message"], r#"bad "message""#);
    }
}
