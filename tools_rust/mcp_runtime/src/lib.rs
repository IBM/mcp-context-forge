pub mod config;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode, header::CONTENT_TYPE},
    response::{IntoResponse, Response},
    routing::{get, post},
};
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

#[derive(Debug)]
struct BackendHttpResponse {
    status: StatusCode,
    headers: HeaderMap,
    body: Bytes,
}

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

    let mode = if request.is_notification() {
        "notification-forward"
    } else if request.method == "ping" {
        "local"
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

    forward_to_backend(&state, headers, body).await
}

fn decode_request(body: &[u8]) -> Result<JsonRpcRequest, Response> {
    let parsed: Value = serde_json::from_slice(body).map_err(|_| {
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
    })?;

    let object = parsed.as_object().ok_or_else(|| {
        json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": Value::Null,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request",
                }
            }),
        )
    })?;

    if let Some(version) = object.get("jsonrpc").and_then(Value::as_str) {
        if version != JSONRPC_VERSION {
            return Err(json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": object.get("id").cloned().unwrap_or(Value::Null),
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request",
                    }
                }),
            ));
        }
    }

    let method = object
        .get("method")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": object.get("id").cloned().unwrap_or(Value::Null),
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request",
                    }
                }),
            )
        })?;

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

async fn forward_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    if backend_response.status.is_success() {
        return empty_response(StatusCode::ACCEPTED);
    }

    response_from_backend(backend_response)
}

async fn send_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<BackendHttpResponse, Response> {
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

    let backend_response = state
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
        })?;

    let status = backend_response.status();
    let headers = backend_response.headers().clone();
    let body = backend_response.bytes().await.map_err(|err| {
        error!("backend MCP response body read failed: {err}");
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": Value::Null,
                "error": {
                    "code": -32000,
                    "message": "Backend MCP response read failed",
                    "data": err.to_string(),
                }
            }),
        )
    })?;

    Ok(BackendHttpResponse {
        status,
        headers,
        body,
    })
}

fn response_from_backend(backend_response: BackendHttpResponse) -> Response {
    let mut builder = Response::builder().status(backend_response.status);
    builder = builder.header(RUNTIME_HEADER, RUNTIME_NAME);

    if let Some(value) = backend_response.headers.get(CONTENT_TYPE) {
        builder = builder.header(CONTENT_TYPE, value.clone());
    } else if !backend_response.body.is_empty() {
        builder = builder.header(CONTENT_TYPE, "application/json");
    }

    for header_name in [
        "mcp-session-id",
        "x-mcp-session-id",
        "www-authenticate",
        "x-request-id",
        "x-correlation-id",
    ] {
        if let Some(value) = backend_response.headers.get(header_name) {
            builder = builder.header(header_name, value.clone());
        }
    }

    builder
        .body(Body::from(backend_response.body))
        .unwrap_or_else(|_| Response::new(Body::from("internal response construction error")))
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
