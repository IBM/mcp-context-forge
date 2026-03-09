pub mod config;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode, header::CONTENT_TYPE},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use futures_util::TryStreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{path::Path, sync::Arc, time::Duration};
use thiserror::Error;
use tracing::{error, info};

use crate::config::{ListenTarget, RuntimeConfig};

const JSONRPC_VERSION: &str = "2.0";
const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
const RUNTIME_NAME: &str = "rust";
const MCP_PROTOCOL_VERSION_HEADER: &str = "mcp-protocol-version";

#[derive(Debug, Error)]
pub enum RuntimeError {
    #[error("{0}")]
    Config(String),
    #[error("http client error: {0}")]
    HttpClient(#[from] reqwest::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone)]
pub struct AppState {
    backend_rpc_url: Arc<str>,
    backend_tools_list_url: Arc<str>,
    client: Client,
    protocol_version: Arc<str>,
    supported_protocol_versions: Arc<Vec<String>>,
    server_name: Arc<str>,
    server_version: Arc<str>,
    instructions: Arc<str>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct JsonRpcRequest {
    pub jsonrpc: Option<String>,
    pub method: String,
    #[serde(default)]
    pub params: Value,
    #[serde(default)]
    pub id: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub runtime: &'static str,
    pub backend_rpc_url: String,
    pub protocol_version: String,
    pub supported_protocol_versions: Vec<String>,
    pub server_name: String,
}

#[derive(Debug, Clone, Deserialize)]
struct InitializeParams {
    #[serde(rename = "protocolVersion")]
    protocol_version: Option<String>,
}

impl JsonRpcRequest {
    fn is_notification(&self) -> bool {
        matches!(self.id.as_ref(), None | Some(Value::Null))
            && self.method.starts_with("notifications/")
    }
}

impl AppState {
    pub fn new(config: &RuntimeConfig) -> Result<Self, RuntimeError> {
        let client = Client::builder()
            .pool_idle_timeout(Duration::from_secs(90))
            .tcp_keepalive(Duration::from_secs(30))
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .build()?;

        Ok(Self {
            backend_rpc_url: Arc::from(config.backend_rpc_url.clone()),
            backend_tools_list_url: Arc::from(derive_backend_tools_list_url(&config.backend_rpc_url)),
            client,
            protocol_version: Arc::from(config.protocol_version.clone()),
            supported_protocol_versions: Arc::new(config.effective_supported_protocol_versions()),
            server_name: Arc::from(config.server_name.clone()),
            server_version: Arc::from(config.server_version.clone()),
            instructions: Arc::from(config.instructions.clone()),
        })
    }

    pub fn backend_rpc_url(&self) -> &str {
        &self.backend_rpc_url
    }

    pub fn backend_tools_list_url(&self) -> &str {
        &self.backend_tools_list_url
    }

    pub fn protocol_version(&self) -> &str {
        &self.protocol_version
    }

    pub fn supported_protocol_versions(&self) -> &[String] {
        self.supported_protocol_versions.as_slice()
    }

    pub fn server_name(&self) -> &str {
        &self.server_name
    }

    pub fn server_version(&self) -> &str {
        &self.server_version
    }

    pub fn instructions(&self) -> &str {
        &self.instructions
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(healthz))
        .route("/healthz", get(healthz))
        .route("/rpc", post(rpc))
        .route("/rpc/", post(rpc))
        .route("/mcp", post(rpc))
        .route("/mcp/", post(rpc))
        .with_state(state)
}

pub async fn run(config: RuntimeConfig) -> Result<(), RuntimeError> {
    let state = AppState::new(&config)?;
    let app = build_router(state);

    match config.listen_target().map_err(RuntimeError::Config)? {
        ListenTarget::Http(addr) => {
            info!("starting Rust MCP runtime on http://{addr}");
            let listener = tokio::net::TcpListener::bind(addr).await?;
            axum::serve(listener, app).await?;
        }
        ListenTarget::Uds(path) => {
            if Path::new(&path).exists() {
                std::fs::remove_file(&path)?;
            }
            info!("starting Rust MCP runtime on unix://{}", path.display());
            let listener = tokio::net::UnixListener::bind(&path)?;
            axum::serve(listener, app).await?;
        }
    }

    Ok(())
}

async fn healthz(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        runtime: RUNTIME_NAME,
        backend_rpc_url: state.backend_rpc_url().to_string(),
        protocol_version: state.protocol_version().to_string(),
        supported_protocol_versions: state.supported_protocol_versions().to_vec(),
        server_name: state.server_name().to_string(),
    })
}

async fn rpc(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> Response {
    if let Err(response) = validate_protocol_version(&state, &headers) {
        return response;
    }

    let request = match decode_request(&body) {
        Ok(request) => request,
        Err(response) => return response,
    };

    let server_scoped_tools_list = request.method == "tools/list" && is_server_scoped_tools_list(&headers);

    let mode = if request.is_notification() {
        "notification-forward"
    } else if request.method == "ping" {
        "local"
    } else if server_scoped_tools_list {
        "backend-tools-list-direct"
    } else {
        "backend-forward"
    };
    info!("rust_mcp_runtime method={} mode={}", request.method, mode);

    if request.is_notification() {
        return forward_notification_to_backend(&state, headers, body).await;
    }

    if request.method == "ping" {
        return json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request.id,
                "result": {},
            }),
        );
    }

    if request.method == "initialize" {
        if let Err(response) =
            validate_initialize_params(&state, &request.params, request.id.clone())
        {
            return response;
        }
    }

    if server_scoped_tools_list {
        return forward_server_tools_list_to_backend(&state, headers, request.id.clone()).await;
    }

    forward_to_backend(&state, headers, body).await
}

fn derive_backend_tools_list_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/tools/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/tools/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/list");
    }
    format!(
        "{}/_internal/mcp/tools/list",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn is_server_scoped_tools_list(headers: &HeaderMap) -> bool {
    headers.contains_key("x-contextforge-server-id")
}

fn decode_request(body: &[u8]) -> Result<JsonRpcRequest, Response> {
    let parsed: Value = serde_json::from_slice(body).map_err(|_| parse_error_response())?;

    if parsed.is_array() {
        return Err(batch_rejected_response());
    }

    let object = parsed
        .as_object()
        .ok_or_else(|| invalid_request_response(Value::Null))?;

    let request_id = object.get("id").cloned().unwrap_or(Value::Null);
    if let Some(version) = object.get("jsonrpc").and_then(Value::as_str) {
        if version != JSONRPC_VERSION {
            return Err(invalid_request_response(request_id));
        }
    }

    let method = object
        .get("method")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid_request_response(request_id.clone()))?;

    Ok(JsonRpcRequest {
        jsonrpc: Some(JSONRPC_VERSION.to_string()),
        method: method.to_string(),
        params: object.get("params").cloned().unwrap_or_else(|| json!({})),
        id: object.get("id").cloned(),
    })
}

fn validate_protocol_version(state: &AppState, headers: &HeaderMap) -> Result<(), Response> {
    let protocol_version = headers
        .get(MCP_PROTOCOL_VERSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .unwrap_or(state.protocol_version());

    if state
        .supported_protocol_versions()
        .iter()
        .any(|supported| supported == protocol_version)
    {
        return Ok(());
    }

    let supported = state.supported_protocol_versions().join(", ");
    Err(json_response(
        StatusCode::BAD_REQUEST,
        json!({
            "error": "Bad Request",
            "message": format!(
                "Unsupported protocol version: {protocol_version}. Supported versions: {supported}"
            ),
        }),
    ))
}

fn validate_initialize_params(
    state: &AppState,
    params: &Value,
    request_id: Option<Value>,
) -> Result<(), Response> {
    let params: InitializeParams = match serde_json::from_value(params.clone()) {
        Ok(params) => params,
        Err(_) => {
            return Err(json_response(
                StatusCode::OK,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params",
                    },
                }),
            ));
        }
    };

    let Some(protocol_version) = params.protocol_version else {
        return Err(json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "Missing protocolVersion",
                },
            }),
        ));
    };

    if state
        .supported_protocol_versions()
        .iter()
        .all(|supported| supported != &protocol_version)
    {
        return Err(json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": format!("Unsupported protocolVersion: {protocol_version}"),
                },
            }),
        ));
    }

    Ok(())
}

fn parse_error_response() -> Response {
    json_response(
        StatusCode::BAD_REQUEST,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": Value::Null,
            "error": {
                "code": -32700,
                "message": "Parse error",
            }
        }),
    )
}

fn invalid_request_response(id: Value) -> Response {
    json_response(
        StatusCode::BAD_REQUEST,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": id,
            "error": {
                "code": -32600,
                "message": "Invalid Request",
            }
        }),
    )
}

fn batch_rejected_response() -> Response {
    json_response(
        StatusCode::BAD_REQUEST,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": Value::Null,
            "error": {
                "code": -32600,
                "message": "Batch requests are not supported",
            }
        }),
    )
}

async fn forward_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    response_from_backend(backend_response)
}

async fn forward_server_tools_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_tools_list_to_backend(state, incoming_headers).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP tools/list response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP tools/list decode failed",
                        "data": err.to_string(),
                    }
                }),
            );
        }
    };

    let response_payload = if status.is_success() {
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": payload,
        })
    } else {
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": payload,
        })
    };

    response_from_json_with_headers(status, response_payload, &backend_headers)
}

async fn forward_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    if backend_response.status().is_success() {
        return empty_response(StatusCode::ACCEPTED);
    }

    response_from_backend(backend_response)
}

async fn send_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    let mut forwarded_headers = reqwest::header::HeaderMap::new();

    for (name, value) in incoming_headers.iter() {
        if should_forward_header(name) {
            forwarded_headers.insert(name.clone(), value.clone());
        }
    }

    forwarded_headers.insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );

    state
        .client
        .post(state.backend_rpc_url())
        .headers(forwarded_headers)
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_tools_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
) -> Result<reqwest::Response, Response> {
    let mut forwarded_headers = reqwest::header::HeaderMap::new();

    for (name, value) in incoming_headers.iter() {
        if should_forward_header(name) {
            forwarded_headers.insert(name.clone(), value.clone());
        }
    }

    forwarded_headers.insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );

    state
        .client
        .post(state.backend_tools_list_url())
        .headers(forwarded_headers)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP tools/list dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP tools/list dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

fn response_from_backend(backend_response: reqwest::Response) -> Response {
    let status = backend_response.status();
    let headers = backend_response.headers().clone();
    let body = Body::from_stream(backend_response.bytes_stream().map_err(|err| {
        error!("backend MCP response body stream failed: {err}");
        std::io::Error::other(err.to_string())
    }));

    let mut builder = Response::builder().status(status);
    builder = builder.header(RUNTIME_HEADER, RUNTIME_NAME);

    if let Some(value) = headers.get(CONTENT_TYPE) {
        builder = builder.header(CONTENT_TYPE, value.clone());
    } else {
        builder = builder.header(CONTENT_TYPE, "application/json");
    }

    for header_name in [
        "mcp-session-id",
        "x-mcp-session-id",
        "www-authenticate",
        "x-request-id",
        "x-correlation-id",
    ] {
        if let Some(value) = headers.get(header_name) {
            builder = builder.header(header_name, value.clone());
        }
    }

    builder
        .body(body)
        .unwrap_or_else(|_| Response::new(Body::from("internal response construction error")))
}

fn response_from_json_with_headers(
    status: StatusCode,
    payload: Value,
    headers: &reqwest::header::HeaderMap,
) -> Response {
    let mut response = json_response(status, payload);
    let response_headers = response.headers_mut();

    if let Some(value) = headers.get(CONTENT_TYPE) {
        response_headers.insert(CONTENT_TYPE, value.clone());
    }

    for header_name in [
        "mcp-session-id",
        "x-mcp-session-id",
        "www-authenticate",
        "x-request-id",
        "x-correlation-id",
    ] {
        if let Some(value) = headers.get(header_name) {
            if let Ok(name) = HeaderName::from_bytes(header_name.as_bytes()) {
                response_headers.insert(name, value.clone());
            }
        }
    }

    response
}

fn should_forward_header(name: &HeaderName) -> bool {
    !matches!(
        name.as_str(),
        "host"
            | "content-length"
            | "connection"
            | "transfer-encoding"
            | "keep-alive"
            | "x-forwarded-internally"
            | "x-mcp-session-id"
            | RUNTIME_HEADER
    )
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    let mut response = (status, Json(payload)).into_response();
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response
}

fn empty_response(status: StatusCode) -> Response {
    let mut response = Response::new(Body::empty());
    *response.status_mut() = status;
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response
}
