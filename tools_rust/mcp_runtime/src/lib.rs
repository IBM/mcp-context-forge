pub mod config;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode, header::CONTENT_TYPE},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use futures_util::TryStreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap, hash_map::DefaultHasher},
    hash::{Hash, Hasher},
    path::Path,
    str::{self, FromStr},
    sync::Arc,
    time::{Duration, Instant},
};
use thiserror::Error;
use tokio::sync::Mutex;
use tokio_postgres::NoTls;
use tracing::{error, info, warn};

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
    #[error("postgres error: {0}")]
    Postgres(#[from] tokio_postgres::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone)]
pub struct AppState {
    backend_rpc_url: Arc<str>,
    backend_transport_url: Arc<str>,
    backend_tools_list_url: Arc<str>,
    backend_tools_list_authz_url: Arc<str>,
    backend_tools_call_url: Arc<str>,
    backend_tools_call_resolve_url: Arc<str>,
    client: Client,
    protocol_version: Arc<str>,
    supported_protocol_versions: Arc<Vec<String>>,
    server_name: Arc<str>,
    server_version: Arc<str>,
    instructions: Arc<str>,
    db_pool: Option<Pool>,
    upstream_tool_sessions: Arc<Mutex<HashMap<String, UpstreamToolSession>>>,
    resolved_tool_call_plans: Arc<Mutex<HashMap<String, CachedResolvedToolCallPlan>>>,
    tools_call_plan_ttl: Duration,
    upstream_session_ttl: Duration,
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

#[derive(Debug, Clone, Deserialize)]
struct InternalAuthContext {
    email: Option<String>,
    teams: Option<Vec<String>>,
    #[serde(default)]
    is_admin: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ResolvedMcpToolCallPlan {
    eligible: bool,
    #[serde(default)]
    fallback_reason: Option<String>,
    #[serde(default)]
    server_url: Option<String>,
    #[serde(default)]
    remote_tool_name: Option<String>,
    #[serde(default)]
    headers: Option<HashMap<String, String>>,
    #[serde(default)]
    timeout_ms: Option<u64>,
    #[serde(default)]
    transport: Option<String>,
}

#[derive(Debug, Clone)]
struct UpstreamToolSession {
    session_id: Option<String>,
    last_used: Instant,
}

#[derive(Debug, Clone)]
struct CachedResolvedToolCallPlan {
    plan: ResolvedMcpToolCallPlan,
    cached_at: Instant,
}

#[derive(Debug)]
enum ResolveToolsCallError {
    Fallback(String),
    JsonRpcError {
        payload: Value,
        headers: reqwest::header::HeaderMap,
    },
}

#[derive(Debug, Clone, Serialize)]
struct McpToolDefinition {
    name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    description: Option<String>,
    #[serde(rename = "inputSchema")]
    input_schema: Value,
    #[serde(rename = "annotations")]
    annotations: Value,
    #[serde(rename = "outputSchema", skip_serializing_if = "Option::is_none")]
    output_schema: Option<Value>,
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
            .connect_timeout(Duration::from_millis(config.client_connect_timeout_ms))
            .pool_idle_timeout(Duration::from_secs(
                config.client_pool_idle_timeout_seconds,
            ))
            .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
            .tcp_keepalive(Duration::from_secs(
                config.client_tcp_keepalive_seconds,
            ))
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .build()?;
        let db_pool = build_db_pool(config)?;

        Ok(Self {
            backend_rpc_url: Arc::from(config.backend_rpc_url.clone()),
            backend_transport_url: Arc::from(derive_backend_transport_url(
                &config.backend_rpc_url,
            )),
            backend_tools_list_url: Arc::from(derive_backend_tools_list_url(
                &config.backend_rpc_url,
            )),
            backend_tools_list_authz_url: Arc::from(derive_backend_tools_list_authz_url(
                &config.backend_rpc_url,
            )),
            backend_tools_call_url: Arc::from(derive_backend_tools_call_url(
                &config.backend_rpc_url,
            )),
            backend_tools_call_resolve_url: Arc::from(derive_backend_tools_call_resolve_url(
                &config.backend_rpc_url,
            )),
            client,
            protocol_version: Arc::from(config.protocol_version.clone()),
            supported_protocol_versions: Arc::new(config.effective_supported_protocol_versions()),
            server_name: Arc::from(config.server_name.clone()),
            server_version: Arc::from(config.server_version.clone()),
            instructions: Arc::from(config.instructions.clone()),
            db_pool,
            upstream_tool_sessions: Arc::new(Mutex::new(HashMap::new())),
            resolved_tool_call_plans: Arc::new(Mutex::new(HashMap::new())),
            tools_call_plan_ttl: Duration::from_secs(config.tools_call_plan_ttl_seconds),
            upstream_session_ttl: Duration::from_secs(config.upstream_session_ttl_seconds),
        })
    }

    pub fn backend_rpc_url(&self) -> &str {
        &self.backend_rpc_url
    }

    pub fn backend_transport_url(&self) -> &str {
        &self.backend_transport_url
    }

    pub fn backend_tools_list_url(&self) -> &str {
        &self.backend_tools_list_url
    }

    pub fn backend_tools_list_authz_url(&self) -> &str {
        &self.backend_tools_list_authz_url
    }

    pub fn backend_tools_call_url(&self) -> &str {
        &self.backend_tools_call_url
    }

    pub fn backend_tools_call_resolve_url(&self) -> &str {
        &self.backend_tools_call_resolve_url
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

    pub fn db_pool(&self) -> Option<&Pool> {
        self.db_pool.as_ref()
    }

    fn upstream_tool_sessions(&self) -> &Arc<Mutex<HashMap<String, UpstreamToolSession>>> {
        &self.upstream_tool_sessions
    }

    fn resolved_tool_call_plans(
        &self,
    ) -> &Arc<Mutex<HashMap<String, CachedResolvedToolCallPlan>>> {
        &self.resolved_tool_call_plans
    }

    fn tools_call_plan_ttl(&self) -> Duration {
        self.tools_call_plan_ttl
    }

    fn upstream_session_ttl(&self) -> Duration {
        self.upstream_session_ttl
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(healthz))
        .route("/healthz", get(healthz))
        .route("/rpc", post(rpc))
        .route("/rpc/", post(rpc))
        .route("/mcp", get(transport_get).delete(transport_delete).post(rpc))
        .route("/mcp/", get(transport_get).delete(transport_delete).post(rpc))
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

async fn transport_get(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    forward_transport_request(&state, reqwest::Method::GET, headers, uri).await
}

async fn transport_delete(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    forward_transport_request(&state, reqwest::Method::DELETE, headers, uri).await
}

async fn rpc(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> Response {
    if let Err(response) = validate_protocol_version(&state, &headers) {
        return response;
    }

    let request = match decode_request(&body) {
        Ok(request) => request,
        Err(response) => return response,
    };

    let server_scoped_tools_list =
        request.method == "tools/list" && is_server_scoped_tools_list(&headers);
    let rust_db_direct_tools_list = server_scoped_tools_list && state.db_pool().is_some();
    let specialized_tools_call = request.method == "tools/call";

    let mode = if request.is_notification() {
        "notification-forward"
    } else if request.method == "ping" {
        "local"
    } else if specialized_tools_call {
        "backend-tools-call-direct"
    } else if rust_db_direct_tools_list {
        "db-tools-list-direct"
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

    if rust_db_direct_tools_list {
        return direct_server_tools_list(&state, headers, request.id.clone()).await;
    }

    if server_scoped_tools_list {
        return forward_server_tools_list_to_backend(&state, headers, request.id.clone()).await;
    }

    if specialized_tools_call {
        return handle_tools_call(&state, headers, body, request).await;
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

fn derive_backend_transport_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/transport");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/transport");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/transport");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/transport");
    }
    format!(
        "{}/_internal/mcp/transport",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_tools_list_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/tools/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/tools/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/list/authz");
    }
    format!(
        "{}/_internal/mcp/tools/list/authz",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_tools_call_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/tools/call");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/call");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/tools/call");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/call");
    }
    format!(
        "{}/_internal/mcp/tools/call",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_tools_call_resolve_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/tools/call/resolve");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/call/resolve");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/tools/call/resolve");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/tools/call/resolve");
    }
    format!(
        "{}/_internal/mcp/tools/call/resolve",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn build_db_pool(config: &RuntimeConfig) -> Result<Option<Pool>, RuntimeError> {
    let Some(database_url) = config.database_url.as_deref() else {
        return Ok(None);
    };

    if database_url.starts_with("sqlite:") {
        warn!("Rust MCP direct DB mode disabled: sqlite is not supported");
        return Ok(None);
    }

    let normalized_url = database_url.replace("postgresql+psycopg://", "postgresql://");
    let pg_config = tokio_postgres::Config::from_str(&normalized_url).map_err(|err| {
        RuntimeError::Config(format!(
            "invalid MCP_RUST_DATABASE_URL '{}': {err}",
            normalized_url
        ))
    })?;
    let mgr_config = ManagerConfig {
        recycling_method: RecyclingMethod::Fast,
    };
    let manager = Manager::from_config(pg_config, NoTls, mgr_config);
    let pool = Pool::builder(manager)
        .max_size(config.db_pool_max_size)
        .build()
        .map_err(|err| RuntimeError::Config(format!("failed to build Rust MCP DB pool: {err}")))?;

    Ok(Some(pool))
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

async fn forward_transport_request(
    state: &AppState,
    method: reqwest::Method,
    incoming_headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    let backend_response = match send_transport_to_backend(state, method, &incoming_headers, &uri).await
    {
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

async fn direct_server_tools_list(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
) -> Response {
    let server_id = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers(&incoming_headers);

    let (Some(server_id), Ok(auth_context)) = (server_id, auth_context) else {
        warn!(
            "Rust MCP direct tools/list missing trusted context; falling back to Python dispatcher"
        );
        return forward_server_tools_list_to_backend(state, incoming_headers, request_id).await;
    };

    if let Err(response) =
        authorize_server_tools_list_via_backend(state, &incoming_headers, request_id.clone()).await
    {
        return response;
    }

    match query_server_tools_list_from_db(state, &server_id, &auth_context).await {
        Ok(tools) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "tools": tools,
                },
            }),
        ),
        Err(err) => {
            error!(
                "Rust MCP direct tools/list DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_server_tools_list_to_backend(state, incoming_headers, request_id).await
        }
    }
}

async fn authorize_server_tools_list_via_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request_id: Option<Value>,
) -> Result<(), Response> {
    let backend_response = state
        .client
        .post(state.backend_tools_list_authz_url())
        .headers(build_forwarded_headers(incoming_headers))
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP tools/list authz failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP tools/list authz failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })?;

    if backend_response.status().is_success() {
        return Ok(());
    }

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP tools/list authz response decode failed: {err}");
            return Err(json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP tools/list authz decode failed",
                        "data": err.to_string(),
                    }
                }),
            ));
        }
    };

    Err(response_from_json_with_headers(
        status,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": payload,
        }),
        &backend_headers,
    ))
}

async fn query_server_tools_list_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
) -> Result<Vec<McpToolDefinition>, RuntimeError> {
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.is_admin && auth_context.teams.is_none();
    let rows = if is_unrestricted_admin {
        client
            .query(
                "SELECT t.name, t.description, t.input_schema, t.output_schema, t.annotations \
                 FROM tools t \
                 JOIN server_tool_association sta ON t.id = sta.tool_id \
                 WHERE sta.server_id = $1 AND t.enabled = TRUE",
                &[&server_id],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = match auth_context.teams.as_ref() {
            None => true,
            Some(teams) => teams.is_empty(),
        };
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query(
                "SELECT t.name, t.description, t.input_schema, t.output_schema, t.annotations \
                 FROM tools t \
                 JOIN server_tool_association sta ON t.id = sta.tool_id \
                 WHERE sta.server_id = $1 \
                   AND t.enabled = TRUE \
                   AND ( \
                        t.visibility = 'public' \
                        OR ($2::bool AND t.owner_email = $3) \
                        OR (COALESCE(array_length($4::text[], 1), 0) > 0 AND t.team_id = ANY($4::text[]) AND t.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    Ok(rows
        .into_iter()
        .map(|row| McpToolDefinition {
            name: row.get("name"),
            description: row.get("description"),
            input_schema: row
                .get::<_, Option<Value>>("input_schema")
                .unwrap_or_else(|| json!({"type": "object", "properties": {}})),
            annotations: row
                .get::<_, Option<Value>>("annotations")
                .unwrap_or_else(|| json!({})),
            output_schema: row.get("output_schema"),
        })
        .collect())
}

fn decode_internal_auth_context_from_headers(
    incoming_headers: &HeaderMap,
) -> Result<InternalAuthContext, String> {
    let header_value = incoming_headers
        .get("x-contextforge-auth-context")
        .and_then(|value| value.to_str().ok())
        .ok_or_else(|| "missing x-contextforge-auth-context".to_string())?;
    let decoded = URL_SAFE_NO_PAD
        .decode(header_value)
        .map_err(|err| format!("invalid auth context encoding: {err}"))?;
    serde_json::from_slice::<InternalAuthContext>(&decoded)
        .map_err(|err| format!("invalid auth context payload: {err}"))
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
    state
        .client
        .post(state.backend_rpc_url())
        .headers(build_forwarded_headers(&incoming_headers))
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

async fn send_transport_to_backend(
    state: &AppState,
    method: reqwest::Method,
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
) -> Result<reqwest::Response, Response> {
    let target_url = build_backend_transport_url(state.backend_transport_url(), uri);
    state
        .client
        .request(method, target_url)
        .headers(build_forwarded_headers(incoming_headers))
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP transport dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "error": "Bad Gateway",
                    "message": "Backend MCP transport dispatch failed",
                    "data": err.to_string(),
                }),
            )
        })
}

async fn send_tools_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_tools_list_url())
        .headers(build_forwarded_headers(&incoming_headers))
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

async fn handle_tools_call(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request: JsonRpcRequest,
) -> Response {
    let plan = match resolve_tools_call(state, &incoming_headers, &request, body.clone()).await
    {
        Ok(plan) => plan,
        Err(ResolveToolsCallError::JsonRpcError { payload, headers }) => {
            return response_from_json_with_headers(StatusCode::OK, payload, &headers);
        }
        Err(ResolveToolsCallError::Fallback(err)) => {
            warn!("Rust MCP direct tools/call resolve fallback: {err}");
            return forward_tools_call_to_backend(state, incoming_headers, body).await;
        }
    };

    if !plan.eligible || plan.transport.as_deref() != Some("streamablehttp") {
        if let Some(reason) = plan.fallback_reason.as_deref() {
            info!("Rust MCP direct tools/call falling back to Python: {reason}");
        }
        return forward_tools_call_to_backend(state, incoming_headers, body).await;
    }

    match execute_tools_call_direct(state, &incoming_headers, &request, &plan).await {
        Ok(response) => response,
        Err(err) => {
            warn!("Rust MCP direct tools/call execution fallback: {err}");
            forward_tools_call_to_backend(state, incoming_headers, body).await
        }
    }
}

async fn forward_tools_call_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_tools_call_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    response_from_backend(backend_response)
}

async fn resolve_tools_call_plan_via_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    body: Bytes,
) -> Result<ResolvedMcpToolCallPlan, ResolveToolsCallError> {
    let response = state
        .client
        .post(state.backend_tools_call_resolve_url())
        .headers(build_forwarded_headers(incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| ResolveToolsCallError::Fallback(format!("resolve request failed: {err}")))?;

    let status = response.status();
    let headers = response.headers().clone();
    let response_body = response
        .bytes()
        .await
        .map_err(|err| ResolveToolsCallError::Fallback(format!("resolve read failed: {err}")))?;

    if !status.is_success() {
        if let Ok(payload) = serde_json::from_slice::<Value>(&response_body) {
            if payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string())) && payload.get("error").is_some() {
                return Err(ResolveToolsCallError::JsonRpcError { payload, headers });
            }
        }
        return Err(ResolveToolsCallError::Fallback(format!(
            "resolve returned status {status}"
        )));
    }

    serde_json::from_slice::<ResolvedMcpToolCallPlan>(&response_body).map_err(|err| {
        if let Ok(payload) = serde_json::from_slice::<Value>(&response_body) {
            if payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string())) && payload.get("error").is_some() {
                return ResolveToolsCallError::JsonRpcError { payload, headers };
            }
        }
        ResolveToolsCallError::Fallback(format!("resolve decode failed: {err}"))
    })
}

async fn resolve_tools_call(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Result<ResolvedMcpToolCallPlan, ResolveToolsCallError> {
    let cache_key =
        build_tools_call_plan_cache_key(incoming_headers, request).map_err(ResolveToolsCallError::Fallback)?;
    {
        let mut cached_plans = state.resolved_tool_call_plans().lock().await;
        if let Some(cached) = cached_plans.get_mut(&cache_key) {
            if cached.cached_at.elapsed() < state.tools_call_plan_ttl() {
                cached.cached_at = Instant::now();
                return Ok(cached.plan.clone());
            }
        }
    }

    let plan = resolve_tools_call_plan_via_backend(state, incoming_headers, body).await?;
    if plan.eligible && plan.transport.as_deref() == Some("streamablehttp") {
        state.resolved_tool_call_plans().lock().await.insert(
            cache_key,
            CachedResolvedToolCallPlan {
                plan: plan.clone(),
                cached_at: Instant::now(),
            },
        );
    }
    Ok(plan)
}

async fn send_tools_call_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_tools_call_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP tools/call dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP tools/call dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn execute_tools_call_direct(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    plan: &ResolvedMcpToolCallPlan,
) -> Result<Response, String> {
    let server_url = plan
        .server_url
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
    let remote_tool_name = plan
        .remote_tool_name
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing remote_tool_name".to_string())?;
    let protocol_version = incoming_headers
        .get(MCP_PROTOCOL_VERSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .unwrap_or(state.protocol_version())
        .to_string();
    let timeout_ms = plan.timeout_ms.unwrap_or(30_000);
    let downstream_session_id = incoming_headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);

    let upstream_session_id = ensure_upstream_session(
        state,
        plan,
        downstream_session_id.as_deref(),
        &protocol_version,
        timeout_ms,
    )
    .await?;

    let mut tool_response = send_direct_tools_call(
        state,
        server_url,
        plan,
        request,
        remote_tool_name,
        &protocol_version,
        upstream_session_id.as_deref(),
        timeout_ms,
    )
    .await?;

    if !tool_response.status().is_success() {
        let session_key = build_upstream_session_key(downstream_session_id.as_deref(), plan)?;
        state.upstream_tool_sessions().lock().await.remove(&session_key);
        let refreshed_session_id = ensure_upstream_session(
            state,
            plan,
            downstream_session_id.as_deref(),
            &protocol_version,
            timeout_ms,
        )
        .await?;
        tool_response = send_direct_tools_call(
            state,
            server_url,
            plan,
            request,
            remote_tool_name,
            &protocol_version,
            refreshed_session_id.as_deref(),
            timeout_ms,
        )
        .await?;
    }

    let status = tool_response.status();
    let payload = decode_upstream_json_payload(tool_response)
        .await
        .map_err(|err| format!("direct tools/call decode failed: {err}"))?;

    let mut response = json_response(status, payload);
    if let Some(session_id) = downstream_session_id {
        if let Ok(value) = HeaderValue::from_str(&session_id) {
            response
                .headers_mut()
                .insert(HeaderName::from_static("mcp-session-id"), value);
        }
    }
    Ok(response)
}

async fn ensure_upstream_session(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    downstream_session_id: Option<&str>,
    protocol_version: &str,
    timeout_ms: u64,
) -> Result<Option<String>, String> {
    let session_key = build_upstream_session_key(downstream_session_id, plan)?;
    let mut sessions = state.upstream_tool_sessions().lock().await;
    if let Some(existing) = sessions.get_mut(&session_key) {
        if existing.last_used.elapsed() < state.upstream_session_ttl() {
            existing.last_used = Instant::now();
            return Ok(existing.session_id.clone());
        }
    }

    let upstream_session_id = initialize_upstream_session(state, plan, protocol_version, timeout_ms).await?;
    sessions.insert(
        session_key,
        UpstreamToolSession {
            session_id: upstream_session_id.clone(),
            last_used: Instant::now(),
        },
    );
    Ok(upstream_session_id)
}

async fn initialize_upstream_session(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
    timeout_ms: u64,
) -> Result<Option<String>, String> {
    let server_url = plan
        .server_url
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
    let headers = build_upstream_headers(plan, protocol_version, None)?;
    let response = state
        .client
        .post(server_url)
        .headers(headers)
        .timeout(Duration::from_millis(timeout_ms))
        .json(&json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": "__contextforge_init__",
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "contextforge-rust-runtime",
                    "version": state.server_version(),
                }
            }
        }))
        .send()
        .await
        .map_err(|err| format!("upstream initialize failed: {err}"))?;

    if !response.status().is_success() {
        return Err(format!("upstream initialize returned status {}", response.status()));
    }

    let upstream_session_id = response
        .headers()
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let payload = decode_upstream_json_payload(response)
        .await
        .map_err(|err| format!("upstream initialize decode failed: {err}"))?;
    if payload.get("error").is_some() {
        return Err(format!("upstream initialize returned error: {payload}"));
    }

    if let Some(session_id) = upstream_session_id.as_deref() {
        let _ = send_initialized_notification(state, server_url, plan, protocol_version, session_id)
            .await;
    }

    Ok(upstream_session_id)
}

async fn send_initialized_notification(
    state: &AppState,
    server_url: &str,
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
    upstream_session_id: &str,
) -> Result<(), String> {
    let headers = build_upstream_headers(plan, protocol_version, Some(upstream_session_id))?;
    state
        .client
        .post(server_url)
        .headers(headers)
        .json(&json!({
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/initialized",
            "params": {}
        }))
        .send()
        .await
        .map_err(|err| format!("upstream initialized notification failed: {err}"))?;
    Ok(())
}

async fn send_direct_tools_call(
    state: &AppState,
    server_url: &str,
    plan: &ResolvedMcpToolCallPlan,
    request: &JsonRpcRequest,
    remote_tool_name: &str,
    protocol_version: &str,
    upstream_session_id: Option<&str>,
    timeout_ms: u64,
) -> Result<reqwest::Response, String> {
    let mut params = request.params.clone();
    let params_object = params
        .as_object_mut()
        .ok_or_else(|| "tools/call params must be an object".to_string())?;
    params_object.insert("name".to_string(), Value::String(remote_tool_name.to_string()));

    state
        .client
        .post(server_url)
        .headers(build_upstream_headers(plan, protocol_version, upstream_session_id)?)
        .timeout(Duration::from_millis(timeout_ms))
        .json(&json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request.id.clone().unwrap_or(Value::String("__contextforge_tools_call__".to_string())),
            "method": "tools/call",
            "params": params,
        }))
        .send()
        .await
        .map_err(|err| format!("direct tools/call request failed: {err}"))
}

fn build_upstream_headers(
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
    upstream_session_id: Option<&str>,
) -> Result<reqwest::header::HeaderMap, String> {
    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(
        reqwest::header::ACCEPT,
        HeaderValue::from_static("application/json, text/event-stream"),
    );
    headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    headers.insert(
        HeaderName::from_static(MCP_PROTOCOL_VERSION_HEADER),
        HeaderValue::from_str(protocol_version)
            .map_err(|err| format!("invalid protocol version header: {err}"))?,
    );

    if let Some(header_values) = plan.headers.as_ref() {
        for (name, value) in header_values {
            let header_name = reqwest::header::HeaderName::from_str(name)
                .map_err(|err| format!("invalid upstream header name '{name}': {err}"))?;
            let header_value = HeaderValue::from_str(value)
                .map_err(|err| format!("invalid upstream header '{name}': {err}"))?;
            headers.insert(header_name, header_value);
        }
    }

    if let Some(session_id) = upstream_session_id {
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_str(session_id)
                .map_err(|err| format!("invalid upstream session header: {err}"))?,
        );
    }

    Ok(headers)
}

async fn decode_upstream_json_payload(response: reqwest::Response) -> Result<Value, String> {
    let content_type = response
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let body = response
        .bytes()
        .await
        .map_err(|err| format!("read body failed: {err}"))?;

    decode_upstream_json_payload_bytes(&body, &content_type)
}

fn decode_upstream_json_payload_bytes(body: &[u8], content_type: &str) -> Result<Value, String> {
    if content_type.contains("text/event-stream") || body.starts_with(b"data:") {
        let text = str::from_utf8(body).map_err(|err| format!("invalid utf-8 SSE body: {err}"))?;
        let data = extract_first_sse_data_payload(text)
            .ok_or_else(|| "missing SSE data payload".to_string())?;
        return serde_json::from_str(&data).map_err(|err| format!("invalid SSE JSON payload: {err}"));
    }

    serde_json::from_slice(body).map_err(|err| format!("invalid JSON payload: {err}"))
}

fn extract_first_sse_data_payload(body: &str) -> Option<String> {
    let mut current_event_data = Vec::new();

    for raw_line in body.lines() {
        let line = raw_line.trim_end_matches('\r');
        if line.is_empty() {
            if !current_event_data.is_empty() {
                return Some(current_event_data.join("\n"));
            }
            continue;
        }

        if let Some(data) = line.strip_prefix("data:") {
            current_event_data.push(data.trim_start().to_string());
        }
    }

    if current_event_data.is_empty() {
        None
    } else {
        Some(current_event_data.join("\n"))
    }
}

fn build_upstream_session_key(
    downstream_session_id: Option<&str>,
    plan: &ResolvedMcpToolCallPlan,
) -> Result<String, String> {
    let server_url = plan
        .server_url
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
    let mut hasher = DefaultHasher::new();
    server_url.hash(&mut hasher);
    if let Some(header_values) = plan.headers.as_ref() {
        let ordered: BTreeMap<_, _> = header_values.iter().collect();
        ordered.hash(&mut hasher);
    }
    match downstream_session_id {
        Some(session_id) => Ok(format!("downstream:{session_id}:{}", hasher.finish())),
        None => Ok(format!("shared:{}", hasher.finish())),
    }
}

fn build_tools_call_plan_cache_key(
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
) -> Result<String, String> {
    let tool_name = request
        .params
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| "tools/call params missing name".to_string())?;
    let mut hasher = DefaultHasher::new();
    tool_name.hash(&mut hasher);

    let mut header_pairs = BTreeMap::new();
    for (name, value) in incoming_headers {
        if should_cache_plan_header(name) {
            let header_value = value
                .to_str()
                .map_err(|err| format!("invalid cacheable header '{}': {err}", name.as_str()))?;
            header_pairs.insert(name.as_str().to_string(), header_value.to_string());
        }
    }
    header_pairs.hash(&mut hasher);

    Ok(format!("tool-plan:{}", hasher.finish()))
}

fn should_cache_plan_header(name: &HeaderName) -> bool {
    let name = name.as_str();
    name == "authorization" || name == "cookie" || name.starts_with("x-contextforge-")
}

fn build_forwarded_headers(incoming_headers: &HeaderMap) -> reqwest::header::HeaderMap {
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
    forwarded_headers
}

fn build_backend_transport_url(base_url: &str, uri: &axum::http::Uri) -> String {
    match uri.query() {
        Some(query) if !query.is_empty() => format!("{base_url}?{query}"),
        _ => base_url.to_string(),
    }
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
