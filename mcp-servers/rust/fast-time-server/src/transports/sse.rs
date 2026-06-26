// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Legacy MCP HTTP+SSE transport (`/sse` + `/messages` / `/message`).
//!
//! DOCUMENTED EXCEPTION: this transport is hand-rolled rather than provided by
//! `rmcp`. The official SDK targets the modern Streamable HTTP transport (served
//! at `/mcp`); it does not reproduce the bespoke ContextForge legacy-SSE
//! semantics that existing clients depend on — the `endpoint` event, the
//! `sessionId`/`session_id` query aliases, and the exact `202`/`404`/`410`
//! status codes. To avoid drift, the JSON-RPC handling below still delegates all
//! tool work to [`FastTimeServer`]: schemas come from
//! [`FastTimeServer::tool_definitions`] and execution from
//! [`FastTimeServer::dispatch_tool`]. Only the JSON-RPC envelope, the protocol
//! version echo, and the SSE session registry are bespoke.

use axum::Router;
use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use rmcp::ErrorData as McpError;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::convert::Infallible;
use std::pin::Pin;
use std::sync::{Arc, LazyLock, RwLock};
use std::task::{Context, Poll};
use tokio::sync::mpsc;
use tokio_stream::Stream;
use tokio_stream::wrappers::ReceiverStream;
use uuid::Uuid;

use crate::config::{
    APP_NAME, APP_VERSION, MAX_ACTIVE_SESSIONS, MCP_PROTOCOL_VERSION, SSE_CHANNEL_CAPACITY,
    SUPPORTED_PROTOCOL_VERSIONS,
};
use crate::server::FastTimeServer;
use crate::{prompts, resources};

/// Shared server instance backing the legacy SSE transport. Tool schemas and
/// execution are owned by `rmcp`; this shim only frames JSON-RPC around them.
static SERVER: LazyLock<FastTimeServer> = LazyLock::new(FastTimeServer::new);

static SSE_SESSIONS: LazyLock<RwLock<HashMap<String, mpsc::Sender<String>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

#[derive(Clone)]
struct SseState {
    public_url: Arc<str>,
}

impl SseState {
    fn new(public_url: &str) -> Self {
        Self {
            public_url: Arc::from(public_url.trim_end_matches('/')),
        }
    }
}

#[derive(Debug, serde::Deserialize)]
pub(crate) struct MessageQuery {
    #[serde(rename = "sessionId")]
    session_id_camel: Option<String>,
    session_id: Option<String>,
}

impl MessageQuery {
    fn session_id(&self) -> Option<&str> {
        self.session_id_camel
            .as_deref()
            .or(self.session_id.as_deref())
    }
}

struct SessionStream {
    session_id: String,
    endpoint: Option<String>,
    receiver: ReceiverStream<String>,
}

impl SessionStream {
    fn new(session_id: String, receiver: mpsc::Receiver<String>, public_url: &str) -> Self {
        let endpoint = Some(endpoint_url(public_url, &session_id));
        Self {
            session_id,
            endpoint,
            receiver: ReceiverStream::new(receiver),
        }
    }
}

impl Stream for SessionStream {
    type Item = Result<Event, Infallible>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if let Some(endpoint) = self.endpoint.take() {
            return Poll::Ready(Some(Ok(Event::default().event("endpoint").data(endpoint))));
        }

        Pin::new(&mut self.receiver)
            .poll_next(cx)
            .map(|message| message.map(|data| Ok(Event::default().event("message").data(data))))
    }
}

impl Drop for SessionStream {
    fn drop(&mut self) {
        remove_session(&self.session_id);
    }
}

pub(crate) fn routes(public_url: &str) -> Router {
    Router::new()
        .route("/sse", get(handler))
        .route("/messages", post(message_handler))
        .route("/message", post(message_handler))
        .with_state(SseState::new(public_url))
}

async fn handler(State(state): State<SseState>) -> Response {
    let session_id = Uuid::new_v4().to_string();
    let (sender, receiver) = mpsc::channel(SSE_CHANNEL_CAPACITY);
    if !remember_session(session_id.clone(), sender) {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    }

    Sse::new(SessionStream::new(session_id, receiver, &state.public_url))
        .keep_alive(KeepAlive::default())
        .into_response()
}

pub(crate) async fn message_handler(
    Query(query): Query<MessageQuery>,
    axum::Json(req): axum::Json<Value>,
) -> Response {
    let Some(session_id) = query.session_id() else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    let Some(sender) = session_sender(session_id) else {
        return StatusCode::NOT_FOUND.into_response();
    };

    if let Some(message) = handle_jsonrpc(&req).await
        && sender.send(message).await.is_err()
    {
        remove_session(session_id);
        return StatusCode::GONE.into_response();
    }

    StatusCode::ACCEPTED.into_response()
}

/// Frame a single JSON-RPC request into its serialized response, or `None` for
/// notifications (no `id`), which receive no reply.
async fn handle_jsonrpc(req: &Value) -> Option<String> {
    let id = req.get("id")?;

    let method = req
        .get("method")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let body = match method {
        "initialize" => success_envelope(id, initialize_result(negotiate_protocol_version(req))),
        "ping" => success_envelope(id, json!({})),
        "tools/list" => success_envelope(id, json!({ "tools": SERVER.tool_definitions() })),
        "tools/call" => match dispatch_call(req).await {
            Ok(result) => success_envelope(id, to_value(result)),
            Err(err) => error_envelope(id, &err),
        },
        "resources/list" => success_envelope(id, json!({ "resources": resources::list() })),
        "resources/read" => match read_resource(req) {
            Ok(result) => success_envelope(id, to_value(result)),
            Err(err) => error_envelope(id, &err),
        },
        "prompts/list" => success_envelope(id, json!({ "prompts": prompts::list() })),
        "prompts/get" => match get_prompt(req) {
            Ok(result) => success_envelope(id, to_value(result)),
            Err(err) => error_envelope(id, &err),
        },
        _ => error_envelope_code(id, -32601, "Method not found"),
    };

    Some(body)
}

fn to_value<T: serde::Serialize>(value: T) -> Value {
    serde_json::to_value(value).unwrap_or_else(|_| json!({}))
}

async fn dispatch_call(req: &Value) -> Result<rmcp::model::CallToolResult, McpError> {
    let params = req.get("params").cloned().unwrap_or(Value::Null);
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let arguments = params.get("arguments").cloned().unwrap_or(Value::Null);
    SERVER.dispatch_tool(name, &arguments).await
}

fn read_resource(req: &Value) -> Result<rmcp::model::ReadResourceResult, McpError> {
    let uri = req
        .get("params")
        .and_then(|params| params.get("uri"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    resources::read(uri)
}

fn get_prompt(req: &Value) -> Result<rmcp::model::GetPromptResult, McpError> {
    let params = req.get("params").cloned().unwrap_or(Value::Null);
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let arguments = params.get("arguments").cloned().unwrap_or(Value::Null);
    prompts::get(name, &arguments)
}

fn initialize_result(protocol_version: &str) -> Value {
    json!({
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {},
            "resources": { "listChanged": true },
            "prompts": { "listChanged": true }
        },
        "serverInfo": { "name": APP_NAME, "version": APP_VERSION },
        "instructions": "Ultra-fast MCP test server."
    })
}

/// Echo back the client's requested protocol version when supported, otherwise
/// advertise the latest version this server speaks.
fn negotiate_protocol_version(req: &Value) -> &'static str {
    let requested = req
        .get("params")
        .and_then(|params| params.get("protocolVersion"))
        .and_then(Value::as_str);
    SUPPORTED_PROTOCOL_VERSIONS
        .iter()
        .copied()
        .find(|&supported| Some(supported) == requested)
        .unwrap_or(MCP_PROTOCOL_VERSION)
}

fn success_envelope(id: &Value, result: Value) -> String {
    json!({ "jsonrpc": "2.0", "id": id, "result": result }).to_string()
}

fn error_envelope(id: &Value, err: &McpError) -> String {
    json!({ "jsonrpc": "2.0", "id": id, "error": err }).to_string()
}

fn error_envelope_code(id: &Value, code: i32, message: &str) -> String {
    json!({ "jsonrpc": "2.0", "id": id, "error": { "code": code, "message": message } }).to_string()
}

fn endpoint_url(public_url: &str, session_id: &str) -> String {
    let path = format!("/messages?sessionId={session_id}");
    if public_url.is_empty() {
        path
    } else {
        format!("{public_url}{path}")
    }
}

fn remember_session(session_id: String, sender: mpsc::Sender<String>) -> bool {
    if let Ok(mut sessions) = SSE_SESSIONS.write() {
        if sessions.len() >= MAX_ACTIVE_SESSIONS {
            return false;
        }
        sessions.insert(session_id, sender);
        true
    } else {
        false
    }
}

fn session_sender(session_id: &str) -> Option<mpsc::Sender<String>> {
    SSE_SESSIONS
        .read()
        .ok()
        .and_then(|sessions| sessions.get(session_id).cloned())
}

fn remove_session(session_id: &str) -> bool {
    SSE_SESSIONS
        .write()
        .map(|mut sessions| sessions.remove(session_id).is_some())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_sse_message_handler_sends_initialize_response() {
        let session_id = Uuid::new_v4().to_string();
        let (sender, mut receiver) = mpsc::channel(1);
        assert!(remember_session(session_id.clone(), sender));

        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: Some(session_id.clone()),
                session_id: None,
            }),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": { "name": "sse-smoke", "version": "1.0" }
                },
                "id": 1
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let message = receiver
            .recv()
            .await
            .expect("initialize response should be sent as SSE data");
        let body: Value = serde_json::from_str(&message).expect("SSE message should be JSON-RPC");
        assert_eq!(body["result"]["protocolVersion"], "2024-11-05");
        assert_eq!(body["result"]["serverInfo"]["name"], APP_NAME);
        assert!(body["result"]["capabilities"]["tools"].is_object());
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_sse_message_handler_lists_tools_via_rmcp_schemas() {
        let session_id = Uuid::new_v4().to_string();
        let (sender, mut receiver) = mpsc::channel(1);
        assert!(remember_session(session_id.clone(), sender));

        // session_id (snake_case) alias is accepted alongside sessionId.
        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: None,
                session_id: Some(session_id.clone()),
            }),
            axum::Json(json!({ "jsonrpc": "2.0", "method": "tools/list", "id": 2 })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let message = receiver
            .recv()
            .await
            .expect("tools/list response should be sent as SSE data");
        let body: Value = serde_json::from_str(&message).expect("SSE message should be JSON-RPC");
        let names: Vec<&str> = body["result"]["tools"]
            .as_array()
            .expect("tools should be an array")
            .iter()
            .filter_map(|tool| tool["name"].as_str())
            .collect();
        assert!(names.contains(&"echo"));
        assert!(names.contains(&"convert_time"));
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_sse_message_handler_calls_tool() {
        let session_id = Uuid::new_v4().to_string();
        let (sender, mut receiver) = mpsc::channel(1);
        assert!(remember_session(session_id.clone(), sender));

        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: Some(session_id.clone()),
                session_id: None,
            }),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": { "name": "echo", "arguments": { "message": "hi there" } },
                "id": 3
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let message = receiver.recv().await.expect("tool response should be sent");
        let body: Value = serde_json::from_str(&message).expect("SSE message should be JSON-RPC");
        assert_eq!(body["result"]["content"][0]["text"], "hi there");
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_sse_message_handler_rejects_unknown_session() {
        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: Some("missing-sse-session".to_string()),
                session_id: None,
            }),
            axum::Json(json!({ "jsonrpc": "2.0", "method": "tools/list", "id": 4 })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn test_endpoint_url_honors_public_url() {
        assert_eq!(
            endpoint_url("https://time.example.com/base", "abc"),
            "https://time.example.com/base/messages?sessionId=abc"
        );
        assert_eq!(endpoint_url("", "abc"), "/messages?sessionId=abc");
    }
}
