pub mod config;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode, header::CONTENT_TYPE},
    response::{
        IntoResponse, Response,
        sse::{Event, KeepAlive, Sse},
    },
    routing::{get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use futures_util::{StreamExt, TryStreamExt};
use redis::{AsyncCommands, Script, aio::ConnectionManager as RedisConnectionManager};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, HashMap, hash_map::DefaultHasher},
    convert::Infallible,
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
use uuid::Uuid;

#[cfg(feature = "rmcp-upstream-client")]
use rmcp::{
    ServiceError as RmcpServiceError,
    model::{
        CallToolRequestParams as RmcpCallToolRequestParams,
        ClientCapabilities as RmcpClientCapabilities, ClientInfo as RmcpClientInfo,
        Implementation as RmcpImplementation, ProtocolVersion as RmcpProtocolVersion,
    },
    serve_client as rmcp_serve_client,
    service::{RoleClient as RmcpRoleClient, RunningService as RmcpRunningService},
    transport::{
        StreamableHttpClientTransport, streamable_http_client::StreamableHttpClientTransportConfig,
    },
};

use crate::config::{ListenTarget, RuntimeConfig};

const JSONRPC_VERSION: &str = "2.0";
const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
const RUNTIME_NAME: &str = "rust";
const UPSTREAM_CLIENT_HEADER: &str = "x-contextforge-mcp-upstream-client";
const MCP_PROTOCOL_VERSION_HEADER: &str = "mcp-protocol-version";
const SESSION_VALIDATED_HEADER: &str = "x-contextforge-session-validated";
const SESSION_CORE_HEADER: &str = "x-contextforge-mcp-session-core";
const EVENT_STORE_HEADER: &str = "x-contextforge-mcp-event-store";
const RESUME_CORE_HEADER: &str = "x-contextforge-mcp-resume-core";
const LIVE_STREAM_CORE_HEADER: &str = "x-contextforge-mcp-live-stream-core";
const AFFINITY_CORE_HEADER: &str = "x-contextforge-mcp-affinity-core";
const INTERNAL_AFFINITY_FORWARDED_HEADER: &str = "x-contextforge-affinity-forwarded";
const INTERNAL_AFFINITY_FORWARDED_VALUE: &str = "rust";

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

#[derive(Clone)]
pub struct AppState {
    backend_rpc_url: Arc<str>,
    backend_initialize_url: Arc<str>,
    backend_notifications_initialized_url: Arc<str>,
    backend_notifications_message_url: Arc<str>,
    backend_notifications_cancelled_url: Arc<str>,
    backend_transport_url: Arc<str>,
    backend_tools_list_url: Arc<str>,
    backend_resources_list_url: Arc<str>,
    backend_resources_read_url: Arc<str>,
    backend_resources_subscribe_url: Arc<str>,
    backend_resources_unsubscribe_url: Arc<str>,
    backend_resource_templates_list_url: Arc<str>,
    backend_prompts_list_url: Arc<str>,
    backend_prompts_get_url: Arc<str>,
    backend_roots_list_url: Arc<str>,
    backend_completion_complete_url: Arc<str>,
    backend_sampling_create_message_url: Arc<str>,
    backend_logging_set_level_url: Arc<str>,
    backend_tools_list_authz_url: Arc<str>,
    backend_tools_call_url: Arc<str>,
    backend_tools_call_resolve_url: Arc<str>,
    client: Client,
    redis_client: Option<redis::Client>,
    redis_manager: Arc<Mutex<Option<RedisConnectionManager>>>,
    protocol_version: Arc<str>,
    supported_protocol_versions: Arc<Vec<String>>,
    server_name: Arc<str>,
    server_version: Arc<str>,
    instructions: Arc<str>,
    #[cfg(feature = "rmcp-upstream-client")]
    use_rmcp_upstream_client: bool,
    session_core_enabled: bool,
    event_store_enabled: bool,
    resume_core_enabled: bool,
    live_stream_core_enabled: bool,
    affinity_core_enabled: bool,
    cache_prefix: Arc<str>,
    event_store_max_events_per_stream: usize,
    event_store_ttl: Duration,
    event_store_poll_interval: Duration,
    db_pool: Option<Pool>,
    runtime_sessions: Arc<Mutex<HashMap<String, RuntimeSessionRecord>>>,
    upstream_tool_sessions: Arc<Mutex<HashMap<String, UpstreamToolSession>>>,
    #[cfg(feature = "rmcp-upstream-client")]
    rmcp_upstream_clients: Arc<Mutex<HashMap<String, CachedRmcpUpstreamClient>>>,
    resolved_tool_call_plans: Arc<Mutex<HashMap<String, CachedResolvedToolCallPlan>>>,
    tools_call_plan_ttl: Duration,
    upstream_session_ttl: Duration,
    session_ttl: Duration,
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
    pub session_core_enabled: bool,
    pub event_store_enabled: bool,
    pub resume_core_enabled: bool,
    pub live_stream_core_enabled: bool,
    pub affinity_core_enabled: bool,
    pub active_sessions: usize,
}

#[derive(Debug, Default, Clone)]
struct PendingSseFrame {
    id: Option<String>,
    event: Option<String>,
    data_lines: Vec<String>,
    retry_ms: Option<u64>,
    saw_field: bool,
}

#[derive(Debug, Clone)]
struct FinalizedSseFrame {
    id: Option<String>,
    event: Option<String>,
    data: String,
    retry_ms: Option<u64>,
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

#[allow(dead_code)]
#[derive(Debug, Clone)]
struct RuntimeSessionRecord {
    owner_email: Option<String>,
    server_id: Option<String>,
    protocol_version: Option<String>,
    client_capabilities: Option<Value>,
    created_at: Instant,
    last_used: Instant,
}

#[cfg(feature = "rmcp-upstream-client")]
#[derive(Debug, Clone)]
struct CachedRmcpUpstreamClient {
    client: Arc<RmcpRunningService<RmcpRoleClient, RmcpClientInfo>>,
    last_used: Instant,
}

#[derive(Debug, Clone)]
struct CachedResolvedToolCallPlan {
    plan: ResolvedMcpToolCallPlan,
    cached_at: Instant,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct StoredRuntimeSessionRecord {
    owner_email: Option<String>,
    server_id: Option<String>,
    protocol_version: Option<String>,
    client_capabilities: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EventStoreStoreRequest {
    stream_id: String,
    #[serde(default)]
    message: Option<Value>,
    #[serde(default)]
    key_prefix: Option<String>,
    #[serde(default)]
    max_events_per_stream: Option<usize>,
    #[serde(default)]
    ttl_seconds: Option<u64>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EventStoreStoreResponse {
    event_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EventStoreReplayRequest {
    last_event_id: String,
    #[serde(default)]
    key_prefix: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EventStoreReplayResponse {
    stream_id: Option<String>,
    events: Vec<EventStoreReplayEvent>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EventStoreReplayEvent {
    event_id: String,
    message: Value,
}

#[derive(Debug, Serialize)]
struct AffinityForwardRequest<'a> {
    #[serde(rename = "type")]
    kind: &'static str,
    response_channel: String,
    mcp_session_id: &'a str,
    method: &'a str,
    path: &'a str,
    query_string: &'a str,
    headers: HashMap<String, String>,
    body: String,
    original_worker: &'static str,
    timestamp: f64,
}

#[derive(Debug, Deserialize)]
struct AffinityForwardResponse {
    status: u16,
    #[serde(default)]
    headers: HashMap<String, String>,
    #[serde(default)]
    body: String,
}

#[derive(Debug, Deserialize)]
struct EventIndexRecord {
    stream_id: String,
    seq_num: i64,
}

impl From<&RuntimeSessionRecord> for StoredRuntimeSessionRecord {
    fn from(value: &RuntimeSessionRecord) -> Self {
        Self {
            owner_email: value.owner_email.clone(),
            server_id: value.server_id.clone(),
            protocol_version: value.protocol_version.clone(),
            client_capabilities: value.client_capabilities.clone(),
        }
    }
}

impl From<StoredRuntimeSessionRecord> for RuntimeSessionRecord {
    fn from(value: StoredRuntimeSessionRecord) -> Self {
        Self {
            owner_email: value.owner_email,
            server_id: value.server_id,
            protocol_version: value.protocol_version,
            client_capabilities: value.client_capabilities,
            created_at: Instant::now(),
            last_used: Instant::now(),
        }
    }
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
            .pool_idle_timeout(Duration::from_secs(config.client_pool_idle_timeout_seconds))
            .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
            .tcp_keepalive(Duration::from_secs(config.client_tcp_keepalive_seconds))
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .build()?;
        let db_pool = build_db_pool(config)?;
        let redis_client = build_redis_client(config)?;

        Ok(Self {
            backend_rpc_url: Arc::from(config.backend_rpc_url.clone()),
            backend_initialize_url: Arc::from(derive_backend_initialize_url(
                &config.backend_rpc_url,
            )),
            backend_notifications_initialized_url: Arc::from(
                derive_backend_notifications_initialized_url(&config.backend_rpc_url),
            ),
            backend_notifications_message_url: Arc::from(derive_backend_notifications_message_url(
                &config.backend_rpc_url,
            )),
            backend_notifications_cancelled_url: Arc::from(
                derive_backend_notifications_cancelled_url(&config.backend_rpc_url),
            ),
            backend_transport_url: Arc::from(derive_backend_transport_url(&config.backend_rpc_url)),
            backend_tools_list_url: Arc::from(derive_backend_tools_list_url(
                &config.backend_rpc_url,
            )),
            backend_resources_list_url: Arc::from(derive_backend_resources_list_url(
                &config.backend_rpc_url,
            )),
            backend_resources_read_url: Arc::from(derive_backend_resources_read_url(
                &config.backend_rpc_url,
            )),
            backend_resources_subscribe_url: Arc::from(derive_backend_resources_subscribe_url(
                &config.backend_rpc_url,
            )),
            backend_resources_unsubscribe_url: Arc::from(derive_backend_resources_unsubscribe_url(
                &config.backend_rpc_url,
            )),
            backend_resource_templates_list_url: Arc::from(
                derive_backend_resource_templates_list_url(&config.backend_rpc_url),
            ),
            backend_prompts_list_url: Arc::from(derive_backend_prompts_list_url(
                &config.backend_rpc_url,
            )),
            backend_prompts_get_url: Arc::from(derive_backend_prompts_get_url(
                &config.backend_rpc_url,
            )),
            backend_roots_list_url: Arc::from(derive_backend_roots_list_url(
                &config.backend_rpc_url,
            )),
            backend_completion_complete_url: Arc::from(derive_backend_completion_complete_url(
                &config.backend_rpc_url,
            )),
            backend_sampling_create_message_url: Arc::from(
                derive_backend_sampling_create_message_url(&config.backend_rpc_url),
            ),
            backend_logging_set_level_url: Arc::from(derive_backend_logging_set_level_url(
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
            redis_client,
            redis_manager: Arc::new(Mutex::new(None)),
            protocol_version: Arc::from(config.protocol_version.clone()),
            supported_protocol_versions: Arc::new(config.effective_supported_protocol_versions()),
            server_name: Arc::from(config.server_name.clone()),
            server_version: Arc::from(config.server_version.clone()),
            instructions: Arc::from(config.instructions.clone()),
            #[cfg(feature = "rmcp-upstream-client")]
            use_rmcp_upstream_client: config.use_rmcp_upstream_client,
            session_core_enabled: config.session_core_enabled,
            event_store_enabled: config.event_store_enabled,
            resume_core_enabled: config.resume_core_enabled,
            live_stream_core_enabled: config.live_stream_core_enabled,
            affinity_core_enabled: config.affinity_core_enabled,
            cache_prefix: Arc::from(config.cache_prefix.clone()),
            event_store_max_events_per_stream: config.event_store_max_events_per_stream,
            event_store_ttl: Duration::from_secs(config.event_store_ttl_seconds),
            event_store_poll_interval: Duration::from_millis(config.event_store_poll_interval_ms),
            db_pool,
            runtime_sessions: Arc::new(Mutex::new(HashMap::new())),
            upstream_tool_sessions: Arc::new(Mutex::new(HashMap::new())),
            #[cfg(feature = "rmcp-upstream-client")]
            rmcp_upstream_clients: Arc::new(Mutex::new(HashMap::new())),
            resolved_tool_call_plans: Arc::new(Mutex::new(HashMap::new())),
            tools_call_plan_ttl: Duration::from_secs(config.tools_call_plan_ttl_seconds),
            upstream_session_ttl: Duration::from_secs(config.upstream_session_ttl_seconds),
            session_ttl: Duration::from_secs(config.session_ttl_seconds),
        })
    }

    pub fn backend_rpc_url(&self) -> &str {
        &self.backend_rpc_url
    }

    pub fn backend_initialize_url(&self) -> &str {
        &self.backend_initialize_url
    }

    pub fn backend_notifications_initialized_url(&self) -> &str {
        &self.backend_notifications_initialized_url
    }

    pub fn backend_notifications_message_url(&self) -> &str {
        &self.backend_notifications_message_url
    }

    pub fn backend_notifications_cancelled_url(&self) -> &str {
        &self.backend_notifications_cancelled_url
    }

    pub fn backend_transport_url(&self) -> &str {
        &self.backend_transport_url
    }

    pub fn backend_tools_list_url(&self) -> &str {
        &self.backend_tools_list_url
    }

    pub fn backend_resources_list_url(&self) -> &str {
        &self.backend_resources_list_url
    }

    pub fn backend_resources_read_url(&self) -> &str {
        &self.backend_resources_read_url
    }

    pub fn backend_resources_subscribe_url(&self) -> &str {
        &self.backend_resources_subscribe_url
    }

    pub fn backend_resources_unsubscribe_url(&self) -> &str {
        &self.backend_resources_unsubscribe_url
    }

    pub fn backend_resource_templates_list_url(&self) -> &str {
        &self.backend_resource_templates_list_url
    }

    pub fn backend_prompts_list_url(&self) -> &str {
        &self.backend_prompts_list_url
    }

    pub fn backend_prompts_get_url(&self) -> &str {
        &self.backend_prompts_get_url
    }

    pub fn backend_roots_list_url(&self) -> &str {
        &self.backend_roots_list_url
    }

    pub fn backend_completion_complete_url(&self) -> &str {
        &self.backend_completion_complete_url
    }

    pub fn backend_sampling_create_message_url(&self) -> &str {
        &self.backend_sampling_create_message_url
    }

    pub fn backend_logging_set_level_url(&self) -> &str {
        &self.backend_logging_set_level_url
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

    async fn redis(&self) -> Option<RedisConnectionManager> {
        if let Some(manager) = self.redis_manager.lock().await.clone() {
            return Some(manager);
        }

        let client = self.redis_client.clone()?;
        let manager = match RedisConnectionManager::new(client).await {
            Ok(manager) => manager,
            Err(err) => {
                warn!("Rust MCP Redis manager initialization failed: {err}");
                return None;
            }
        };

        let mut slot = self.redis_manager.lock().await;
        *slot = Some(manager.clone());
        Some(manager)
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

    fn use_rmcp_upstream_client(&self) -> bool {
        #[cfg(feature = "rmcp-upstream-client")]
        {
            self.use_rmcp_upstream_client
        }
        #[cfg(not(feature = "rmcp-upstream-client"))]
        {
            false
        }
    }

    pub fn session_core_enabled(&self) -> bool {
        self.session_core_enabled
    }

    pub fn event_store_enabled(&self) -> bool {
        self.event_store_enabled
    }

    pub fn resume_core_enabled(&self) -> bool {
        self.resume_core_enabled
    }

    pub fn live_stream_core_enabled(&self) -> bool {
        self.live_stream_core_enabled
    }

    pub fn affinity_core_enabled(&self) -> bool {
        self.affinity_core_enabled
    }

    fn cache_prefix(&self) -> &str {
        &self.cache_prefix
    }

    fn event_store_max_events_per_stream(&self) -> usize {
        self.event_store_max_events_per_stream
    }

    fn event_store_ttl(&self) -> Duration {
        self.event_store_ttl
    }

    fn event_store_poll_interval(&self) -> Duration {
        self.event_store_poll_interval
    }

    pub fn db_pool(&self) -> Option<&Pool> {
        self.db_pool.as_ref()
    }

    fn runtime_sessions(&self) -> &Arc<Mutex<HashMap<String, RuntimeSessionRecord>>> {
        &self.runtime_sessions
    }

    fn upstream_tool_sessions(&self) -> &Arc<Mutex<HashMap<String, UpstreamToolSession>>> {
        &self.upstream_tool_sessions
    }

    #[cfg(feature = "rmcp-upstream-client")]
    fn rmcp_upstream_clients(&self) -> &Arc<Mutex<HashMap<String, CachedRmcpUpstreamClient>>> {
        &self.rmcp_upstream_clients
    }

    fn resolved_tool_call_plans(&self) -> &Arc<Mutex<HashMap<String, CachedResolvedToolCallPlan>>> {
        &self.resolved_tool_call_plans
    }

    fn tools_call_plan_ttl(&self) -> Duration {
        self.tools_call_plan_ttl
    }

    fn upstream_session_ttl(&self) -> Duration {
        self.upstream_session_ttl
    }

    fn session_ttl(&self) -> Duration {
        self.session_ttl
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(healthz))
        .route("/healthz", get(healthz))
        .route("/_internal/event-store/store", post(store_event_endpoint))
        .route(
            "/_internal/event-store/replay",
            post(replay_events_endpoint),
        )
        .route("/rpc", post(rpc))
        .route("/rpc/", post(rpc))
        .route(
            "/mcp",
            get(transport_get).delete(transport_delete).post(rpc),
        )
        .route(
            "/mcp/",
            get(transport_get).delete(transport_delete).post(rpc),
        )
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
    let active_sessions = active_runtime_session_count(&state).await;
    Json(HealthResponse {
        status: "ok",
        runtime: RUNTIME_NAME,
        backend_rpc_url: state.backend_rpc_url().to_string(),
        protocol_version: state.protocol_version().to_string(),
        supported_protocol_versions: state.supported_protocol_versions().to_vec(),
        server_name: state.server_name().to_string(),
        session_core_enabled: state.session_core_enabled(),
        event_store_enabled: state.event_store_enabled(),
        resume_core_enabled: state.resume_core_enabled(),
        live_stream_core_enabled: state.live_stream_core_enabled(),
        affinity_core_enabled: state.affinity_core_enabled(),
        active_sessions,
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

async fn store_event_endpoint(
    State(state): State<AppState>,
    Json(request): Json<EventStoreStoreRequest>,
) -> Response {
    if !state.event_store_enabled() {
        return json_response(
            StatusCode::NOT_IMPLEMENTED,
            json!({"detail": "Rust event store is disabled"}),
        );
    }

    let event_id = match store_event_in_rust_event_store(&state, request).await {
        Ok(event_id) => event_id,
        Err(response) => return response,
    };

    let mut response = Json(EventStoreStoreResponse { event_id }).into_response();
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response.headers_mut().insert(
        HeaderName::from_static(EVENT_STORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response
}

async fn replay_events_endpoint(
    State(state): State<AppState>,
    Json(request): Json<EventStoreReplayRequest>,
) -> Response {
    if !state.event_store_enabled() {
        return json_response(
            StatusCode::NOT_IMPLEMENTED,
            json!({"detail": "Rust event store is disabled"}),
        );
    }

    let replay = match replay_events_from_rust_event_store(&state, request).await {
        Ok(replay) => replay,
        Err(response) => return response,
    };

    let mut response = Json(replay).into_response();
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response.headers_mut().insert(
        HeaderName::from_static(EVENT_STORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response
}

async fn rpc(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
) -> Response {
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
    let specialized_initialize = request.method == "initialize";
    let specialized_resources_list = request.method == "resources/list";
    let specialized_resources_read = request.method == "resources/read";
    let specialized_resources_subscribe = request.method == "resources/subscribe";
    let specialized_resources_unsubscribe = request.method == "resources/unsubscribe";
    let specialized_resource_templates_list = request.method == "resources/templates/list";
    let specialized_prompts_list = request.method == "prompts/list";
    let specialized_prompts_get = request.method == "prompts/get";
    let specialized_roots_list = request.method == "roots/list";
    let specialized_completion_complete = request.method == "completion/complete";
    let specialized_sampling_create_message = request.method == "sampling/createMessage";
    let specialized_logging_set_level = request.method == "logging/setLevel";
    let specialized_initialized_notification =
        request.is_notification() && request.method == "notifications/initialized";
    let specialized_message_notification =
        request.is_notification() && request.method == "notifications/message";
    let specialized_cancelled_notification =
        request.is_notification() && request.method == "notifications/cancelled";
    let catch_all_notifications = request.method.starts_with("notifications/")
        && !specialized_initialized_notification
        && !specialized_message_notification
        && !specialized_cancelled_notification;
    let catch_all_sampling =
        request.method.starts_with("sampling/") && !specialized_sampling_create_message;
    let catch_all_completion =
        request.method.starts_with("completion/") && !specialized_completion_complete;
    let catch_all_logging =
        request.method.starts_with("logging/") && !specialized_logging_set_level;
    let catch_all_elicitation =
        request.method.starts_with("elicitation/") && request.method != "elicitation/create";
    let specialized_tools_call = request.method == "tools/call";
    let mut effective_headers = headers.clone();

    if state.session_core_enabled() {
        if specialized_initialize {
            return handle_initialize_with_session_core(
                &state,
                effective_headers,
                uri,
                body,
                &request,
            )
            .await;
        }

        if let Err(response) =
            validate_runtime_session_request(&state, &mut effective_headers, &uri).await
        {
            return response;
        }
    }

    let request_session_id = runtime_session_id_from_request(&effective_headers, &uri);
    if state.affinity_core_enabled()
        && state.session_core_enabled()
        && !specialized_initialize
        && request_session_id.is_some()
    {
        let affinity_response = match forward_transport_request_via_affinity_owner(
            &state,
            request_session_id.as_deref().unwrap_or_default(),
            reqwest::Method::POST,
            uri.path(),
            uri.query().unwrap_or_default(),
            &effective_headers,
            &body,
        )
        .await
        {
            Ok(response) => response,
            Err(response) => return response,
        };
        if let Some(response) = affinity_response {
            let mut response = response;
            if let Ok(value) = HeaderValue::from_str(if state.affinity_core_enabled() {
                "rust"
            } else {
                "python"
            }) {
                response
                    .headers_mut()
                    .insert(HeaderName::from_static(AFFINITY_CORE_HEADER), value);
            }
            return response;
        }
    }

    let mode = if request.method == "ping" {
        "local"
    } else if specialized_initialized_notification {
        "backend-notifications-initialized-direct"
    } else if specialized_message_notification {
        "backend-notifications-message-direct"
    } else if specialized_cancelled_notification {
        "backend-notifications-cancelled-direct"
    } else if specialized_resources_list {
        "backend-resources-list-direct"
    } else if specialized_resources_read {
        "backend-resources-read-direct"
    } else if specialized_resources_subscribe {
        "backend-resources-subscribe-direct"
    } else if specialized_resources_unsubscribe {
        "backend-resources-unsubscribe-direct"
    } else if specialized_resource_templates_list {
        "backend-resource-templates-list-direct"
    } else if specialized_prompts_list {
        "backend-prompts-list-direct"
    } else if specialized_prompts_get {
        "backend-prompts-get-direct"
    } else if specialized_roots_list {
        "backend-roots-list-direct"
    } else if specialized_completion_complete {
        "backend-completion-complete-direct"
    } else if specialized_sampling_create_message {
        "backend-sampling-create-message-direct"
    } else if specialized_logging_set_level {
        "backend-logging-set-level-direct"
    } else if catch_all_notifications {
        "local-notifications-catchall"
    } else if catch_all_sampling {
        "local-sampling-catchall"
    } else if catch_all_completion {
        "local-completion-catchall"
    } else if catch_all_logging {
        "local-logging-catchall"
    } else if catch_all_elicitation {
        "local-elicitation-catchall"
    } else if specialized_initialize {
        "backend-initialize-direct"
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

    if specialized_initialized_notification {
        return forward_initialized_notification_to_backend(&state, effective_headers, body).await;
    }

    if specialized_message_notification {
        return forward_message_notification_to_backend(&state, effective_headers, body).await;
    }

    if specialized_cancelled_notification {
        return forward_cancelled_notification_to_backend(&state, effective_headers, body).await;
    }

    if specialized_resources_list {
        return forward_resources_list_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_resources_read {
        return forward_resources_read_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_resources_subscribe {
        return forward_resources_subscribe_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_resources_unsubscribe {
        return forward_resources_unsubscribe_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_resource_templates_list {
        return forward_resource_templates_list_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_prompts_list {
        return forward_prompts_list_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_prompts_get {
        return forward_prompts_get_to_backend(&state, effective_headers, body, request.id.clone())
            .await;
    }

    if specialized_roots_list {
        return forward_roots_list_to_backend(&state, effective_headers, body, request.id.clone())
            .await;
    }

    if specialized_completion_complete {
        return forward_completion_complete_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_sampling_create_message {
        return forward_sampling_create_message_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if specialized_logging_set_level {
        return forward_logging_set_level_to_backend(
            &state,
            effective_headers,
            body,
            request.id.clone(),
        )
        .await;
    }

    if catch_all_notifications {
        if request.is_notification() {
            return empty_response(StatusCode::ACCEPTED);
        }
        return json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request.id,
                "result": {},
            }),
        );
    }

    if catch_all_sampling || catch_all_completion || catch_all_logging || catch_all_elicitation {
        return json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request.id,
                "result": {},
            }),
        );
    }

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

    if specialized_initialize {
        return forward_initialize_to_backend(&state, effective_headers, body).await;
    }

    if rust_db_direct_tools_list {
        return direct_server_tools_list(&state, effective_headers, request.id.clone()).await;
    }

    if server_scoped_tools_list {
        return forward_server_tools_list_to_backend(&state, effective_headers, request.id.clone())
            .await;
    }

    if specialized_tools_call {
        return handle_tools_call(&state, effective_headers, body, request).await;
    }

    forward_to_backend(&state, effective_headers, body).await
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

fn derive_backend_resources_list_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/list");
    }
    format!(
        "{}/_internal/mcp/resources/list",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resources_read_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/read");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/read");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/read");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/read");
    }
    format!(
        "{}/_internal/mcp/resources/read",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resources_subscribe_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/subscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/subscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/subscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/subscribe");
    }
    format!(
        "{}/_internal/mcp/resources/subscribe",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resources_unsubscribe_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/unsubscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/unsubscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/unsubscribe");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/unsubscribe");
    }
    format!(
        "{}/_internal/mcp/resources/unsubscribe",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resource_templates_list_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/templates/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/templates/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/templates/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/templates/list");
    }
    format!(
        "{}/_internal/mcp/resources/templates/list",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_prompts_list_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/list");
    }
    format!(
        "{}/_internal/mcp/prompts/list",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_prompts_get_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/get");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/get");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/get");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/get");
    }
    format!(
        "{}/_internal/mcp/prompts/get",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_roots_list_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/roots/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/roots/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/roots/list");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/roots/list");
    }
    format!(
        "{}/_internal/mcp/roots/list",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_completion_complete_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/completion/complete");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/completion/complete");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/completion/complete");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/completion/complete");
    }
    format!(
        "{}/_internal/mcp/completion/complete",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_sampling_create_message_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/sampling/createMessage");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/sampling/createMessage");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/sampling/createMessage");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/sampling/createMessage");
    }
    format!(
        "{}/_internal/mcp/sampling/createMessage",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_logging_set_level_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/logging/setLevel");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/logging/setLevel");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/logging/setLevel");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/logging/setLevel");
    }
    format!(
        "{}/_internal/mcp/logging/setLevel",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_initialize_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/initialize");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/initialize");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/initialize");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/initialize");
    }
    format!(
        "{}/_internal/mcp/initialize",
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

fn derive_backend_session_delete_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/session");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/session");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/session");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/session");
    }
    format!(
        "{}/_internal/mcp/session",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_notifications_initialized_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/initialized");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/initialized");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/initialized");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/initialized");
    }
    format!(
        "{}/_internal/mcp/notifications/initialized",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_notifications_message_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/message");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/message");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/message");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/message");
    }
    format!(
        "{}/_internal/mcp/notifications/message",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_notifications_cancelled_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/cancelled");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/cancelled");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/notifications/cancelled");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/notifications/cancelled");
    }
    format!(
        "{}/_internal/mcp/notifications/cancelled",
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

fn build_redis_client(config: &RuntimeConfig) -> Result<Option<redis::Client>, RuntimeError> {
    let Some(redis_url) = config.redis_url.as_deref() else {
        return Ok(None);
    };

    let client = redis::Client::open(redis_url).map_err(|err| {
        RuntimeError::Config(format!("invalid MCP_RUST_REDIS_URL '{}': {err}", redis_url))
    })?;
    Ok(Some(client))
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
    let backend_response =
        match send_to_backend_url(state, state.backend_rpc_url(), incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    response_from_backend(backend_response)
}

async fn forward_initialize_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend_url(
        state,
        state.backend_initialize_url(),
        incoming_headers,
        body,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    response_from_backend(backend_response)
}

async fn handle_initialize_with_session_core(
    state: &AppState,
    mut incoming_headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
    request: &JsonRpcRequest,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let session_id = requested_initialize_session_id(&incoming_headers, &uri, request)
        .unwrap_or_else(|| Uuid::new_v4().to_string());

    if let Some(existing) = get_runtime_session(state, &session_id).await {
        if !runtime_session_allows_access(&existing, auth_context.as_ref()) {
            return json_response(
                StatusCode::OK,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request.id,
                    "error": {
                        "code": -32003,
                        "message": "Access denied",
                        "data": {"method": "initialize"},
                    }
                }),
            );
        }
    }

    inject_session_header(&mut incoming_headers, &session_id);
    if let Some(server_id) = extract_server_id_header(&incoming_headers) {
        inject_server_id_header(&mut incoming_headers, server_id);
    }

    let backend_response = match send_transport_to_backend(
        state,
        reqwest::Method::POST,
        &incoming_headers,
        &uri,
        Some(body.clone()),
        false,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let response_session_id = backend_response
        .headers()
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .unwrap_or_else(|| session_id.clone());

    if status.is_success() {
        let record = RuntimeSessionRecord {
            owner_email: auth_context
                .as_ref()
                .and_then(|context| context.email.clone()),
            server_id: extract_server_id_header(&incoming_headers),
            protocol_version: requested_protocol_version(request),
            client_capabilities: extract_client_capabilities(request),
            created_at: Instant::now(),
            last_used: Instant::now(),
        };
        upsert_runtime_session(state, response_session_id.clone(), record).await;
    } else {
        remove_runtime_session(state, &response_session_id).await;
    }

    let mut response = response_from_backend_with_session_hint(
        backend_response,
        Some(response_session_id.as_str()),
    );
    if let Ok(value) = HeaderValue::from_str(if state.session_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(SESSION_CORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.event_store_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(EVENT_STORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.resume_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(RESUME_CORE_HEADER), value);
    }
    response
}

async fn active_runtime_session_count(state: &AppState) -> usize {
    let now = Instant::now();
    let ttl = state.session_ttl();
    let mut sessions = state.runtime_sessions().lock().await;
    sessions.retain(|_, record| now.duration_since(record.last_used) <= ttl);
    let local_count = sessions.len();
    drop(sessions);

    if state.redis().await.is_some() {
        if let Some(redis_count) = count_runtime_sessions_in_redis(state).await {
            return redis_count;
        }
    }

    local_count
}

async fn get_runtime_session(state: &AppState, session_id: &str) -> Option<RuntimeSessionRecord> {
    let now = Instant::now();
    let ttl = state.session_ttl();
    {
        let mut sessions = state.runtime_sessions().lock().await;
        if let Some(record) = sessions.get_mut(session_id) {
            if now.duration_since(record.last_used) > ttl {
                sessions.remove(session_id);
            } else {
                record.last_used = now;
                return Some(record.clone());
            }
        }
    }

    let record = get_runtime_session_from_redis(state, session_id).await?;
    cache_runtime_session_locally(state, session_id.to_string(), record.clone()).await;
    Some(record)
}

async fn upsert_runtime_session(
    state: &AppState,
    session_id: String,
    mut record: RuntimeSessionRecord,
) {
    record.last_used = Instant::now();
    cache_runtime_session_locally(state, session_id.clone(), record.clone()).await;
    upsert_runtime_session_in_redis(state, &session_id, &record).await;
}

async fn remove_runtime_session(state: &AppState, session_id: &str) {
    let mut sessions = state.runtime_sessions().lock().await;
    sessions.remove(session_id);
    drop(sessions);
    remove_runtime_session_from_redis(state, session_id).await;
}

async fn cache_runtime_session_locally(
    state: &AppState,
    session_id: String,
    mut record: RuntimeSessionRecord,
) {
    record.last_used = Instant::now();
    let mut sessions = state.runtime_sessions().lock().await;
    sessions.insert(session_id, record);
}

async fn count_runtime_sessions_in_redis(state: &AppState) -> Option<usize> {
    let mut redis = state.redis().await?;
    let pattern = format!("{}rust:mcp:session:*", state.cache_prefix());
    match redis.keys::<_, Vec<String>>(pattern).await {
        Ok(keys) => Some(keys.len()),
        Err(err) => {
            warn!("Rust MCP session count Redis lookup failed: {err}");
            None
        }
    }
}

async fn get_runtime_session_from_redis(
    state: &AppState,
    session_id: &str,
) -> Option<RuntimeSessionRecord> {
    let mut redis = state.redis().await?;
    let key = runtime_session_key(state, session_id);
    match redis.get::<_, Option<String>>(&key).await {
        Ok(Some(payload)) => {
            let _ = redis
                .expire::<_, bool>(&key, state.session_ttl().as_secs() as i64)
                .await;
            match serde_json::from_str::<StoredRuntimeSessionRecord>(&payload) {
                Ok(record) => Some(record.into()),
                Err(err) => {
                    warn!("Rust MCP session decode failed for {session_id}: {err}");
                    None
                }
            }
        }
        Ok(None) => None,
        Err(err) => {
            warn!("Rust MCP session Redis lookup failed for {session_id}: {err}");
            None
        }
    }
}

async fn upsert_runtime_session_in_redis(
    state: &AppState,
    session_id: &str,
    record: &RuntimeSessionRecord,
) {
    let Some(mut redis) = state.redis().await else {
        return;
    };
    let payload = match serde_json::to_string(&StoredRuntimeSessionRecord::from(record)) {
        Ok(payload) => payload,
        Err(err) => {
            warn!("Rust MCP session serialization failed for {session_id}: {err}");
            return;
        }
    };
    let key = runtime_session_key(state, session_id);
    if let Err(err) = redis
        .set_ex::<_, _, ()>(&key, payload, state.session_ttl().as_secs())
        .await
    {
        warn!("Rust MCP session Redis write failed for {session_id}: {err}");
    }
}

async fn remove_runtime_session_from_redis(state: &AppState, session_id: &str) {
    let Some(mut redis) = state.redis().await else {
        return;
    };
    let key = runtime_session_key(state, session_id);
    if let Err(err) = redis.del::<_, ()>(&key).await {
        warn!("Rust MCP session Redis delete failed for {session_id}: {err}");
    }
}

fn runtime_session_key(state: &AppState, session_id: &str) -> String {
    format!("{}rust:mcp:session:{session_id}", state.cache_prefix())
}

fn pool_owner_key(session_id: &str) -> String {
    format!("mcpgw:pool_owner:{session_id}")
}

fn is_affinity_forwarded_request(headers: &HeaderMap) -> bool {
    headers
        .get(INTERNAL_AFFINITY_FORWARDED_HEADER)
        .and_then(|value| value.to_str().ok())
        == Some(INTERNAL_AFFINITY_FORWARDED_VALUE)
}

async fn get_pool_session_owner(state: &AppState, session_id: &str) -> Option<String> {
    let mut redis = state.redis().await?;
    match redis.get::<_, Option<String>>(pool_owner_key(session_id)).await {
        Ok(owner) => owner,
        Err(err) => {
            warn!("Rust MCP affinity owner lookup failed for {session_id}: {err}");
            None
        }
    }
}

async fn forward_transport_request_via_affinity_owner(
    state: &AppState,
    session_id: &str,
    method: reqwest::Method,
    path: &str,
    query_string: &str,
    incoming_headers: &HeaderMap,
    body: &[u8],
) -> Result<Option<Response>, Response> {
    if !state.affinity_core_enabled() || is_affinity_forwarded_request(incoming_headers) {
        return Ok(None);
    }

    let Some(owner_worker_id) = get_pool_session_owner(state, session_id).await else {
        return Ok(None);
    };

    let Some(redis_client) = state.redis_client.clone() else {
        return Ok(None);
    };

    let owner_channel = format!("mcpgw:pool_http:{owner_worker_id}");
    let response_channel = format!("mcpgw:pool_http_response:{}", Uuid::new_v4().simple());
    let mut pubsub = redis_client
        .get_async_pubsub()
        .await
        .map_err(|err| affinity_forward_error_response("Pub/Sub initialization failed", err))?;

    pubsub
        .subscribe(&response_channel)
        .await
        .map_err(|err| affinity_forward_error_response("Pub/Sub subscribe failed", err))?;

    let mut publish_conn = state
        .redis()
        .await
        .ok_or_else(|| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": "Rust MCP affinity forwarding requires Redis",
                }),
            )
        })?;

    let headers = build_affinity_forward_headers(incoming_headers);
    let payload = AffinityForwardRequest {
        kind: "http_forward",
        response_channel: response_channel.clone(),
        mcp_session_id: session_id,
        method: method.as_str(),
        path,
        query_string,
        headers,
        body: hex_encode(body),
        original_worker: "rust-mcp-runtime",
        timestamp: current_unix_timestamp_seconds(),
    };
    let payload_json = serde_json::to_vec(&payload).map_err(|err| {
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": format!("Rust MCP affinity payload serialization failed: {err}"),
            }),
        )
    })?;

    redis::cmd("PUBLISH")
        .arg(&owner_channel)
        .arg(payload_json)
        .query_async::<i64>(&mut publish_conn)
        .await
        .map_err(|err| affinity_forward_error_response("Affinity request publish failed", err))?;

    let mut stream = pubsub.on_message();
    let timeout = Duration::from_secs(30);
    let message = tokio::time::timeout(timeout, stream.next())
        .await
        .map_err(|_| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": format!("Timed out waiting for owner worker response on {response_channel}"),
                }),
            )
        })?
        .ok_or_else(|| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": "Affinity response channel closed before a response arrived",
                }),
            )
        })?;

    let payload_json: String = message
        .get_payload()
        .map_err(|err| affinity_forward_error_response("Affinity response payload decode failed", err))?;
    let payload: AffinityForwardResponse = serde_json::from_str(&payload_json).map_err(|err| {
        affinity_forward_error_response("Affinity response JSON decode failed", err)
    })?;
    Ok(Some(response_from_affinity_forward_response(
        payload,
        Some(session_id),
    )))
}

fn build_affinity_forward_headers(headers: &HeaderMap) -> HashMap<String, String> {
    let mut forwarded = HashMap::new();
    for (name, value) in headers {
        if matches!(
            name.as_str(),
            "host" | "content-length" | "connection" | "transfer-encoding" | "keep-alive"
        ) {
            continue;
        }
        if name.as_str() == INTERNAL_AFFINITY_FORWARDED_HEADER {
            continue;
        }
        if let Ok(value_str) = value.to_str() {
            forwarded.insert(name.as_str().to_string(), value_str.to_string());
        }
    }
    forwarded
}

fn response_from_affinity_forward_response(
    payload: AffinityForwardResponse,
    session_hint: Option<&str>,
) -> Response {
    let status = StatusCode::from_u16(payload.status).unwrap_or(StatusCode::BAD_GATEWAY);
    let body = hex_decode(payload.body.as_bytes()).unwrap_or_default();
    let mut builder = Response::builder().status(status);
    builder = builder.header(RUNTIME_HEADER, RUNTIME_NAME);

    let mut has_content_type = false;
    let mut has_session_id = false;
    for (name, value) in payload.headers {
        let lower = name.to_ascii_lowercase();
        if matches!(lower.as_str(), "connection" | "transfer-encoding" | "keep-alive" | "content-length") {
            continue;
        }
        if lower == "content-type" {
            has_content_type = true;
        }
        if lower == "mcp-session-id" {
            has_session_id = true;
        }
        if let (Ok(header_name), Ok(header_value)) = (
            HeaderName::from_bytes(lower.as_bytes()),
            HeaderValue::from_str(&value),
        ) {
            builder = builder.header(header_name, header_value);
        }
    }

    if !has_content_type {
        builder = builder.header(CONTENT_TYPE, "application/json");
    }
    if !has_session_id {
        if let Some(session_id) = session_hint {
            builder = builder.header("mcp-session-id", session_id);
        }
    }

    builder
        .body(Body::from(body))
        .unwrap_or_else(|_| Response::new(Body::from("internal response construction error")))
}

fn affinity_forward_error_response<E>(message: &str, err: E) -> Response
where
    E: std::fmt::Display,
{
    error!("Rust MCP affinity forwarding failed: {message}: {err}");
    json_response(
        StatusCode::BAD_GATEWAY,
        json!({
            "detail": format!("{message}: {err}"),
        }),
    )
}

fn current_unix_timestamp_seconds() -> f64 {
    match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
        Ok(duration) => duration.as_secs_f64(),
        Err(_) => 0.0,
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    encoded
}

fn hex_decode(input: &[u8]) -> Option<Vec<u8>> {
    if input.len() % 2 != 0 {
        return None;
    }

    let mut decoded = Vec::with_capacity(input.len() / 2);
    for chunk in input.chunks_exact(2) {
        let high = hex_value(chunk[0])?;
        let low = hex_value(chunk[1])?;
        decoded.push((high << 4) | low);
    }
    Some(decoded)
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

const STORE_EVENT_LUA: &str = r#"
local meta_key = KEYS[1]
local events_key = KEYS[2]
local messages_key = KEYS[3]

local event_id = ARGV[1]
local message_json = ARGV[2]
local ttl = tonumber(ARGV[3])
local max_events = tonumber(ARGV[4])
local index_prefix = ARGV[5]
local stream_id = ARGV[6]

local seq_num = redis.call('HINCRBY', meta_key, 'next_seq', 1)
local count = redis.call('HINCRBY', meta_key, 'count', 1)
if count == 1 then
  redis.call('HSET', meta_key, 'start_seq', seq_num)
end

redis.call('ZADD', events_key, seq_num, event_id)
redis.call('HSET', messages_key, event_id, message_json)

local index_key = index_prefix .. event_id
redis.call('SET', index_key, cjson.encode({stream_id=stream_id, seq_num=seq_num}), 'EX', ttl)

if count > max_events then
  local to_evict = count - max_events
  local evicted_ids = redis.call('ZRANGE', events_key, 0, to_evict - 1)
  redis.call('ZREMRANGEBYRANK', events_key, 0, to_evict - 1)

  if #evicted_ids > 0 then
    redis.call('HDEL', messages_key, unpack(evicted_ids))
    for _, ev_id in ipairs(evicted_ids) do
      redis.call('DEL', index_prefix .. ev_id)
    end
  end

  redis.call('HSET', meta_key, 'count', max_events)
  local first = redis.call('ZRANGE', events_key, 0, 0, 'WITHSCORES')
  if #first >= 2 then
    redis.call('HSET', meta_key, 'start_seq', tonumber(first[2]))
  else
    redis.call('HSET', meta_key, 'start_seq', seq_num)
  end
end

redis.call('EXPIRE', meta_key, ttl)
redis.call('EXPIRE', events_key, ttl)
redis.call('EXPIRE', messages_key, ttl)

return seq_num
"#;

async fn store_event_in_rust_event_store(
    state: &AppState,
    request: EventStoreStoreRequest,
) -> Result<String, Response> {
    let Some(mut redis) = state.redis().await else {
        return Err(json_response(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({"detail": "Rust Redis event store is unavailable"}),
        ));
    };

    let event_id = Uuid::new_v4().to_string();
    let key_prefix = event_store_key_prefix(state, request.key_prefix.as_deref());
    let message_json = serde_json::to_string(&request.message).map_err(|err| {
        json_response(
            StatusCode::BAD_REQUEST,
            json!({"detail": format!("Invalid event payload: {err}")}),
        )
    })?;
    let ttl = request
        .ttl_seconds
        .unwrap_or(state.event_store_ttl().as_secs());
    let max_events = request
        .max_events_per_stream
        .unwrap_or(state.event_store_max_events_per_stream());

    let meta_key = format!("{key_prefix}:{}:meta", request.stream_id);
    let events_key = format!("{key_prefix}:{}:events", request.stream_id);
    let messages_key = format!("{key_prefix}:{}:messages", request.stream_id);
    let index_prefix = format!("{key_prefix}:event_index:");

    Script::new(STORE_EVENT_LUA)
        .key(meta_key)
        .key(events_key)
        .key(messages_key)
        .arg(event_id.clone())
        .arg(message_json)
        .arg(ttl as i64)
        .arg(max_events as i64)
        .arg(index_prefix)
        .arg(request.stream_id)
        .invoke_async::<i64>(&mut redis)
        .await
        .map_err(|err| {
            error!("Rust event store write failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": format!("Rust event store write failed: {err}")}),
            )
        })?;

    Ok(event_id)
}

async fn replay_events_from_rust_event_store(
    state: &AppState,
    request: EventStoreReplayRequest,
) -> Result<EventStoreReplayResponse, Response> {
    let Some(mut redis) = state.redis().await else {
        return Err(json_response(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({"detail": "Rust Redis event store is unavailable"}),
        ));
    };

    let key_prefix = event_store_key_prefix(state, request.key_prefix.as_deref());
    let index_key = format!("{key_prefix}:event_index:{}", request.last_event_id);
    let Some(index_payload) = redis
        .get::<_, Option<String>>(&index_key)
        .await
        .map_err(|err| {
            error!("Rust event store replay lookup failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": format!("Rust event store replay lookup failed: {err}")}),
            )
        })?
    else {
        return Ok(EventStoreReplayResponse {
            stream_id: None,
            events: Vec::new(),
        });
    };

    let index_record: EventIndexRecord = serde_json::from_str(&index_payload).map_err(|err| {
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({"detail": format!("Rust event store index decode failed: {err}")}),
        )
    })?;
    let meta_key = format!("{key_prefix}:{}:meta", index_record.stream_id);
    let events_key = format!("{key_prefix}:{}:events", index_record.stream_id);
    let messages_key = format!("{key_prefix}:{}:messages", index_record.stream_id);

    if let Some(start_seq) = redis
        .hget::<_, _, Option<i64>>(&meta_key, "start_seq")
        .await
        .map_err(|err| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": format!("Rust event store meta lookup failed: {err}")}),
            )
        })?
    {
        if index_record.seq_num < start_seq {
            return Ok(EventStoreReplayResponse {
                stream_id: None,
                events: Vec::new(),
            });
        }
    }

    let event_ids = redis::cmd("ZRANGEBYSCORE")
        .arg(&events_key)
        .arg(index_record.seq_num + 1)
        .arg("+inf")
        .query_async::<Vec<String>>(&mut redis)
        .await
        .map_err(|err| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": format!("Rust event store replay scan failed: {err}")}),
            )
        })?;

    let mut events = Vec::with_capacity(event_ids.len());
    for event_id in event_ids {
        let Some(message_json) = redis
            .hget::<_, _, Option<String>>(&messages_key, &event_id)
            .await
            .map_err(|err| {
                json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({"detail": format!("Rust event store replay fetch failed: {err}")}),
                )
            })?
        else {
            continue;
        };

        let message = serde_json::from_str::<Value>(&message_json).unwrap_or(Value::Null);
        events.push(EventStoreReplayEvent { event_id, message });
    }

    Ok(EventStoreReplayResponse {
        stream_id: Some(index_record.stream_id),
        events,
    })
}

fn event_store_key_prefix(state: &AppState, override_prefix: Option<&str>) -> String {
    let prefix = override_prefix
        .unwrap_or("eventstore")
        .trim_end_matches(':');
    if prefix.contains(':') {
        prefix.to_string()
    } else {
        format!("{}{}", state.cache_prefix(), prefix)
    }
}

async fn validate_runtime_session_request(
    state: &AppState,
    incoming_headers: &mut HeaderMap,
    uri: &axum::http::Uri,
) -> Result<Option<String>, Response> {
    let Some(session_id) = runtime_session_id_from_request(incoming_headers, uri) else {
        return Ok(None);
    };

    let Some(record) = get_runtime_session(state, &session_id).await else {
        return Err(json_response(
            StatusCode::NOT_FOUND,
            json!({
                "detail": "Session not found",
            }),
        ));
    };

    let auth_context = decode_internal_auth_context_from_headers_optional(incoming_headers);
    if !runtime_session_allows_access(&record, auth_context.as_ref()) {
        return Err(json_response(
            StatusCode::FORBIDDEN,
            json!({
                "detail": "Session access denied",
            }),
        ));
    }

    inject_session_header(incoming_headers, &session_id);
    if let Some(server_id) = record.server_id.as_deref() {
        if !incoming_headers.contains_key("x-contextforge-server-id") {
            inject_server_id_header(incoming_headers, server_id.to_string());
        }
    }

    Ok(Some(session_id))
}

fn runtime_session_allows_access(
    record: &RuntimeSessionRecord,
    auth_context: Option<&InternalAuthContext>,
) -> bool {
    let Some(owner_email) = record.owner_email.as_deref() else {
        return true;
    };
    let Some(auth_context) = auth_context else {
        return false;
    };
    auth_context.is_admin || auth_context.email.as_deref() == Some(owner_email)
}

fn requested_initialize_session_id(
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
    request: &JsonRpcRequest,
) -> Option<String> {
    runtime_session_id_from_request(incoming_headers, uri).or_else(|| {
        request
            .params
            .get("session_id")
            .or_else(|| request.params.get("sessionId"))
            .and_then(Value::as_str)
            .map(str::to_string)
    })
}

fn runtime_session_id_from_request(
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
) -> Option<String> {
    incoming_headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .or_else(|| query_param(uri, "session_id"))
}

fn requested_protocol_version(request: &JsonRpcRequest) -> Option<String> {
    request
        .params
        .get("protocolVersion")
        .or_else(|| request.params.get("protocol_version"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

fn extract_client_capabilities(request: &JsonRpcRequest) -> Option<Value> {
    request.params.get("capabilities").cloned()
}

fn extract_server_id_header(incoming_headers: &HeaderMap) -> Option<String> {
    incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn requested_protocol_version_from_headers(incoming_headers: &HeaderMap) -> Option<String> {
    incoming_headers
        .get(MCP_PROTOCOL_VERSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn inject_session_header(incoming_headers: &mut HeaderMap, session_id: &str) {
    if let Ok(value) = HeaderValue::from_str(session_id) {
        incoming_headers.insert(HeaderName::from_static("mcp-session-id"), value);
    }
}

fn inject_server_id_header(incoming_headers: &mut HeaderMap, server_id: String) {
    if let Ok(value) = HeaderValue::from_str(&server_id) {
        incoming_headers.insert(HeaderName::from_static("x-contextforge-server-id"), value);
    }
}

fn query_param(uri: &axum::http::Uri, key: &str) -> Option<String> {
    uri.query().and_then(|query| {
        query.split('&').find_map(|pair| {
            let (name, value) = pair.split_once('=')?;
            if name == key {
                Some(value.to_string())
            } else {
                None
            }
        })
    })
}

async fn maybe_upsert_runtime_session_from_transport_response(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request_session_id: Option<&str>,
    response_headers: &reqwest::header::HeaderMap,
) -> Option<String> {
    let response_session_id = response_headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .or_else(|| request_session_id.map(str::to_string));

    if !state.session_core_enabled() {
        return response_session_id;
    }

    let Some(session_id) = response_session_id.clone() else {
        return None;
    };

    let existing = get_runtime_session(state, &session_id).await;
    let auth_context = decode_internal_auth_context_from_headers_optional(incoming_headers);
    let now = Instant::now();
    let record = RuntimeSessionRecord {
        owner_email: existing
            .as_ref()
            .and_then(|record| record.owner_email.clone())
            .or_else(|| auth_context.as_ref().and_then(|context| context.email.clone())),
        server_id: existing
            .as_ref()
            .and_then(|record| record.server_id.clone())
            .or_else(|| extract_server_id_header(incoming_headers)),
        protocol_version: existing
            .as_ref()
            .and_then(|record| record.protocol_version.clone())
            .or_else(|| requested_protocol_version_from_headers(incoming_headers)),
        client_capabilities: existing
            .as_ref()
            .and_then(|record| record.client_capabilities.clone()),
        created_at: existing
            .as_ref()
            .map(|record| record.created_at)
            .unwrap_or(now),
        last_used: now,
    };
    upsert_runtime_session(state, session_id.clone(), record).await;

    Some(session_id)
}

fn accepts_sse(headers: &HeaderMap) -> bool {
    headers
        .get("accept")
        .and_then(|value| value.to_str().ok())
        .map(|value| {
            value.split(',').any(|part| {
                let normalized = part.trim().to_ascii_lowercase();
                normalized == "text/event-stream"
                    || normalized.starts_with("text/event-stream;")
                    || normalized == "*/*"
            })
        })
        .unwrap_or(false)
}

fn parse_sse_line(frame: &mut PendingSseFrame, raw_line: &str) {
    if raw_line.starts_with(':') {
        return;
    }

    let (field, value) = raw_line
        .split_once(':')
        .map(|(field, value)| (field, value.trim_start()))
        .unwrap_or((raw_line, ""));

    match field {
        "id" => {
            frame.id = Some(value.to_string());
            frame.saw_field = true;
        }
        "event" => {
            frame.event = Some(value.to_string());
            frame.saw_field = true;
        }
        "data" => {
            frame.data_lines.push(value.to_string());
            frame.saw_field = true;
        }
        "retry" => {
            frame.retry_ms = value.parse::<u64>().ok();
            frame.saw_field = true;
        }
        _ => {}
    }
}

fn finalize_sse_frame(frame: &mut PendingSseFrame) -> Option<FinalizedSseFrame> {
    if !frame.saw_field {
        *frame = PendingSseFrame::default();
        return None;
    }

    let finalized = FinalizedSseFrame {
        id: frame.id.take(),
        event: frame.event.take(),
        data: frame.data_lines.join("\n"),
        retry_ms: frame.retry_ms.take(),
    };
    *frame = PendingSseFrame::default();
    Some(finalized)
}

fn build_forwarded_sse_event(frame: &FinalizedSseFrame) -> Event {
    let mut event = Event::default();
    if let Some(id) = frame.id.as_deref() {
        event = event.id(id.to_string());
    }
    if let Some(name) = frame.event.as_deref() {
        event = event.event(name.to_string());
    }
    if let Some(retry_ms) = frame.retry_ms {
        event = event.retry(Duration::from_millis(retry_ms));
    }
    event.data(frame.data.clone())
}

async fn handle_resume_transport_request(
    state: &AppState,
    incoming_headers: HeaderMap,
    _uri: axum::http::Uri,
    session_id: Option<&str>,
) -> Response {
    let Some(last_event_id) = incoming_headers
        .get("last-event-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
    else {
        return json_response(
            StatusCode::BAD_REQUEST,
            json!({"detail": "Last-Event-ID header is required for resumable GET /mcp"}),
        );
    };

    let initial_replay = match replay_events_from_rust_event_store(
        state,
        EventStoreReplayRequest {
            last_event_id: last_event_id.clone(),
            key_prefix: None,
        },
    )
    .await
    {
        Ok(replay) => replay,
        Err(response) => return response,
    };
    let protocol_version = incoming_headers
        .get(MCP_PROTOCOL_VERSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .unwrap_or(state.protocol_version())
        .to_string();

    let keep_alive = KeepAlive::new()
        .interval(Duration::from_secs(15))
        .text("");
    let poll_interval = state.event_store_poll_interval();
    let session_id = session_id.map(str::to_string);
    let stream_session_id = session_id.clone();
    let state_cloned = state.clone();
    let mut replay_cursor = last_event_id.clone();
    let mut initial_events = initial_replay.events;
    let stream_id = initial_replay.stream_id;

    let event_stream = async_stream::stream! {
        for event in initial_events.drain(..) {
            replay_cursor = event.event_id.clone();
            yield Ok::<Event, Infallible>(build_sse_event(&event.event_id, &event.message));
        }

        if let Some(stream_id_value) = stream_id {
            if protocol_version.as_str() >= "2025-11-25" {
                if let Ok(priming_event_id) = store_event_in_rust_event_store(
                    &state_cloned,
                    EventStoreStoreRequest {
                        stream_id: stream_id_value.clone(),
                        message: None,
                        key_prefix: None,
                        max_events_per_stream: None,
                        ttl_seconds: None,
                    },
                ).await {
                    replay_cursor = priming_event_id.clone();
                    yield Ok::<Event, Infallible>(Event::default().id(priming_event_id).data(""));
                }
            }

            loop {
                if let Some(session_id_value) = stream_session_id.as_deref() {
                    if get_runtime_session(&state_cloned, session_id_value).await.is_none() {
                        break;
                    }
                }

                match replay_events_from_rust_event_store(
                    &state_cloned,
                    EventStoreReplayRequest {
                        last_event_id: replay_cursor.clone(),
                        key_prefix: None,
                    },
                )
                .await {
                    Ok(replay) => {
                        if replay.events.is_empty() {
                            tokio::time::sleep(poll_interval).await;
                            continue;
                        }
                        for event in replay.events {
                            replay_cursor = event.event_id.clone();
                            yield Ok::<Event, Infallible>(build_sse_event(&event.event_id, &event.message));
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    };

    let mut response = Sse::new(event_stream).keep_alive(keep_alive).into_response();
    response.headers_mut().insert(
        CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream"),
    );
    response.headers_mut().insert(
        HeaderName::from_static("cache-control"),
        HeaderValue::from_static("no-cache, no-transform"),
    );
    response.headers_mut().insert(
        HeaderName::from_static("connection"),
        HeaderValue::from_static("keep-alive"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response.headers_mut().insert(
        HeaderName::from_static(SESSION_CORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(EVENT_STORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(RESUME_CORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(LIVE_STREAM_CORE_HEADER),
        HeaderValue::from_str(if state.live_stream_core_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    if let Some(session_id_value) = session_id.as_deref() {
        if let Ok(value) = HeaderValue::from_str(session_id_value) {
            response
                .headers_mut()
                .insert(HeaderName::from_static("mcp-session-id"), value);
        }
    }
    response
}

async fn handle_live_stream_transport_request(
    state: &AppState,
    incoming_headers: HeaderMap,
    uri: axum::http::Uri,
    session_id: Option<&str>,
) -> Response {
    let keep_alive = KeepAlive::new()
        .interval(Duration::from_secs(15))
        .text("");
    let state_cloned = state.clone();
    let backend_headers = incoming_headers.clone();
    let request_session_id = session_id.map(str::to_string);
    let response_session_id = request_session_id.clone();
    let uri_cloned = uri.clone();

    let event_stream = async_stream::stream! {
        let backend_response = match send_transport_to_backend(
            &state_cloned,
            reqwest::Method::GET,
            &backend_headers,
            &uri_cloned,
            None,
            request_session_id.is_some(),
        )
        .await
        {
            Ok(response) => response,
            Err(response) => {
                error!(
                    "backend MCP live stream open failed with status {}",
                    response.status()
                );
                return;
            }
        };

        let status = backend_response.status();
        let response_headers = backend_response.headers().clone();
        let content_type = response_headers
            .get(CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_ascii_lowercase();

        let _response_session_id = maybe_upsert_runtime_session_from_transport_response(
            &state_cloned,
            &backend_headers,
            request_session_id.as_deref(),
            &response_headers,
        )
        .await;

        if !status.is_success() || !content_type.contains("text/event-stream") {
            error!(
                "backend MCP live stream returned non-stream response status={} content_type={}",
                status,
                content_type
            );
            return;
        }

        let mut upstream_stream = backend_response.bytes_stream();
        let mut buffer: Vec<u8> = Vec::new();
        let mut frame = PendingSseFrame::default();

        loop {
            match upstream_stream.next().await {
                Some(Ok(chunk)) => {
                    buffer.extend_from_slice(&chunk);

                    while let Some(newline_index) = buffer.iter().position(|byte| *byte == b'\n') {
                        let mut line_bytes: Vec<u8> = buffer.drain(..=newline_index).collect();
                        if matches!(line_bytes.last(), Some(b'\n')) {
                            line_bytes.pop();
                        }
                        if matches!(line_bytes.last(), Some(b'\r')) {
                            line_bytes.pop();
                        }

                        let line = String::from_utf8_lossy(&line_bytes);
                        if line.is_empty() {
                            if let Some(finalized) = finalize_sse_frame(&mut frame) {
                                yield Ok::<Event, Infallible>(build_forwarded_sse_event(&finalized));
                            }
                            continue;
                        }

                        parse_sse_line(&mut frame, &line);
                    }
                }
                Some(Err(err)) => {
                    error!("backend MCP live stream read failed: {err}");
                    break;
                }
                None => {
                    if !buffer.is_empty() {
                        let line = String::from_utf8_lossy(&buffer);
                        parse_sse_line(&mut frame, line.trim_end_matches(['\r', '\n']));
                        buffer.clear();
                    }
                    if let Some(finalized) = finalize_sse_frame(&mut frame) {
                        yield Ok::<Event, Infallible>(build_forwarded_sse_event(&finalized));
                    }
                    break;
                }
            }
        }
    };

    let mut response = Sse::new(event_stream).keep_alive(keep_alive).into_response();
    response.headers_mut().insert(
        CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream"),
    );
    response.headers_mut().insert(
        HeaderName::from_static("cache-control"),
        HeaderValue::from_static("no-cache, no-transform"),
    );
    response.headers_mut().insert(
        HeaderName::from_static("connection"),
        HeaderValue::from_static("keep-alive"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response.headers_mut().insert(
        HeaderName::from_static(LIVE_STREAM_CORE_HEADER),
        HeaderValue::from_static("rust"),
    );
    response.headers_mut().insert(
        HeaderName::from_static(SESSION_CORE_HEADER),
        HeaderValue::from_str(if state.session_core_enabled() { "rust" } else { "python" })
            .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    response.headers_mut().insert(
        HeaderName::from_static(EVENT_STORE_HEADER),
        HeaderValue::from_str(if state.event_store_enabled() { "rust" } else { "python" })
            .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    response.headers_mut().insert(
        HeaderName::from_static(RESUME_CORE_HEADER),
        HeaderValue::from_str(if state.resume_core_enabled() { "rust" } else { "python" })
            .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    if let Some(session_id_value) = response_session_id.as_deref() {
        if let Ok(value) = HeaderValue::from_str(session_id_value) {
            response
                .headers_mut()
                .insert(HeaderName::from_static("mcp-session-id"), value);
        }
    }
    response
}

fn build_sse_event(event_id: &str, message: &Value) -> Event {
    let event = Event::default().id(event_id.to_string());
    if message.is_null() {
        return event.data("");
    }

    event
        .event("message")
        .data(serde_json::to_string(message).unwrap_or_else(|_| "null".to_string()))
}

async fn send_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    send_to_backend_url(state, state.backend_rpc_url(), incoming_headers, body).await
}

async fn send_to_backend_url(
    state: &AppState,
    backend_url: &str,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(backend_url)
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

async fn forward_transport_request(
    state: &AppState,
    method: reqwest::Method,
    mut incoming_headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    let session_id = if state.session_core_enabled() {
        match validate_runtime_session_request(state, &mut incoming_headers, &uri).await {
            Ok(session_id) => session_id,
            Err(response) => return response,
        }
    } else {
        None
    };
    let session_validated = state.session_core_enabled() && session_id.is_some();

    if method == reqwest::Method::GET
        && state.resume_core_enabled()
        && state.session_core_enabled()
        && state.event_store_enabled()
        && accepts_sse(&incoming_headers)
        && incoming_headers.contains_key("last-event-id")
    {
        if let Some(session_id_value) = session_id.as_deref() {
            let Some(record) = get_runtime_session(state, session_id_value).await else {
                return json_response(
                    StatusCode::NOT_FOUND,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": "server-error",
                        "error": {
                            "code": -32600,
                            "message": "Session not found",
                        }
                    }),
                );
            };

            let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
            if !runtime_session_allows_access(&record, auth_context.as_ref()) {
                return json_response(
                    StatusCode::FORBIDDEN,
                    json!({
                        "detail": "Session access denied",
                    }),
                );
            }
            inject_session_header(&mut incoming_headers, session_id_value);
            if let Some(server_id) = record.server_id.as_deref() {
                if !incoming_headers.contains_key("x-contextforge-server-id") {
                    inject_server_id_header(&mut incoming_headers, server_id.to_string());
                }
            }
        } else {
            return json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "detail": "mcp-session-id header or session_id query parameter is required for resumable GET /mcp",
                }),
            );
        }

        return handle_resume_transport_request(
            state,
            incoming_headers,
            uri,
            session_id.as_deref(),
        )
        .await;
    }

    if state.affinity_core_enabled()
        && state.session_core_enabled()
        && session_id.is_some()
        && (method == reqwest::Method::GET || method == reqwest::Method::DELETE)
    {
        let affinity_response = match forward_transport_request_via_affinity_owner(
            state,
            session_id.as_deref().unwrap_or_default(),
            method.clone(),
            uri.path(),
            uri.query().unwrap_or_default(),
            &incoming_headers,
            &[],
        )
        .await
        {
            Ok(response) => response,
            Err(response) => return response,
        };
        if let Some(mut response) = affinity_response {
            if let Ok(value) = HeaderValue::from_str(if state.affinity_core_enabled() {
                "rust"
            } else {
                "python"
            }) {
                response
                    .headers_mut()
                    .insert(HeaderName::from_static(AFFINITY_CORE_HEADER), value);
            }
            return response;
        }
    }

    if method == reqwest::Method::GET
        && state.live_stream_core_enabled()
        && accepts_sse(&incoming_headers)
        && !incoming_headers.contains_key("last-event-id")
    {
        return handle_live_stream_transport_request(
            state,
            incoming_headers,
            uri,
            session_id.as_deref(),
        )
        .await;
    }

    if state.session_core_enabled() && method == reqwest::Method::DELETE && session_id.is_some() {
        let backend_response =
            match send_session_delete_to_backend(state, &incoming_headers, session_validated).await
            {
                Ok(response) => response,
                Err(response) => return response,
            };

        if backend_response.status().is_success() {
            if let Some(session_id_value) = session_id.as_deref() {
                remove_runtime_session(state, session_id_value).await;
            }
        }

        let mut response =
            response_from_backend_with_session_hint(backend_response, session_id.as_deref());
        if let Ok(value) = HeaderValue::from_str(if state.session_core_enabled() {
            "rust"
        } else {
            "python"
        }) {
            response
                .headers_mut()
                .insert(HeaderName::from_static(SESSION_CORE_HEADER), value);
        }
        if let Ok(value) = HeaderValue::from_str(if state.event_store_enabled() {
            "rust"
        } else {
            "python"
        }) {
            response
                .headers_mut()
                .insert(HeaderName::from_static(EVENT_STORE_HEADER), value);
        }
        if let Ok(value) = HeaderValue::from_str(if state.resume_core_enabled() {
            "rust"
        } else {
            "python"
        }) {
            response
                .headers_mut()
                .insert(HeaderName::from_static(RESUME_CORE_HEADER), value);
        }
        if let Ok(value) = HeaderValue::from_str(if state.live_stream_core_enabled() {
            "rust"
        } else {
            "python"
        }) {
            response
                .headers_mut()
                .insert(HeaderName::from_static(LIVE_STREAM_CORE_HEADER), value);
        }
        if let Ok(value) = HeaderValue::from_str(if state.affinity_core_enabled() {
            "rust"
        } else {
            "python"
        }) {
            response
                .headers_mut()
                .insert(HeaderName::from_static(AFFINITY_CORE_HEADER), value);
        }
        return response;
    }

    let backend_response = match send_transport_to_backend(
        state,
        method.clone(),
        &incoming_headers,
        &uri,
        None,
        session_validated,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    if state.session_core_enabled()
        && method == reqwest::Method::DELETE
        && backend_response.status().is_success()
        && session_id.is_some()
    {
        if let Some(session_id_value) = session_id.as_deref() {
            remove_runtime_session(state, session_id_value).await;
        }
    }

    let mut response =
        response_from_backend_with_session_hint(backend_response, session_id.as_deref());
    if let Ok(value) = HeaderValue::from_str(if state.session_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(SESSION_CORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.event_store_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(EVENT_STORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.resume_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(RESUME_CORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.live_stream_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(LIVE_STREAM_CORE_HEADER), value);
    }
    if let Ok(value) = HeaderValue::from_str(if state.affinity_core_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(AFFINITY_CORE_HEADER), value);
    }
    response
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

fn decode_internal_auth_context_from_headers_optional(
    incoming_headers: &HeaderMap,
) -> Option<InternalAuthContext> {
    decode_internal_auth_context_from_headers(incoming_headers).ok()
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

async fn forward_initialized_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend_url(
        state,
        state.backend_notifications_initialized_url(),
        incoming_headers,
        body,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    if backend_response.status().is_success() {
        return empty_response(StatusCode::ACCEPTED);
    }

    response_from_backend(backend_response)
}

async fn forward_message_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend_url(
        state,
        state.backend_notifications_message_url(),
        incoming_headers,
        body,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    if backend_response.status().is_success() {
        return empty_response(StatusCode::ACCEPTED);
    }

    response_from_backend(backend_response)
}

async fn forward_resources_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_resources_list_to_backend(state, incoming_headers, body).await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP resources/list response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/list decode failed",
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

async fn forward_resources_read_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_resources_read_to_backend(state, incoming_headers, body).await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP resources/read response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/read decode failed",
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

async fn forward_resources_subscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_resources_subscribe_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP resources/subscribe response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/subscribe decode failed",
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

async fn forward_resources_unsubscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_resources_unsubscribe_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP resources/unsubscribe response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/unsubscribe decode failed",
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

async fn forward_resource_templates_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_resource_templates_list_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP resources/templates/list response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/templates/list decode failed",
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

async fn forward_roots_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_roots_list_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP roots/list response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP roots/list decode failed",
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

async fn forward_prompts_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_prompts_list_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP prompts/list response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP prompts/list decode failed",
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

async fn forward_prompts_get_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response = match send_prompts_get_to_backend(state, incoming_headers, body).await {
        Ok(response) => response,
        Err(response) => return response,
    };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP prompts/get response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP prompts/get decode failed",
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

async fn forward_completion_complete_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_completion_complete_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP completion/complete response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP completion/complete decode failed",
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

async fn forward_sampling_create_message_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_sampling_create_message_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP sampling/createMessage response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP sampling/createMessage decode failed",
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

async fn forward_logging_set_level_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let backend_response =
        match send_logging_set_level_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => return response,
        };

    let status = backend_response.status();
    let backend_headers = backend_response.headers().clone();
    let payload: Value = match backend_response.json().await {
        Ok(payload) => payload,
        Err(err) => {
            error!("backend MCP logging/setLevel response decode failed: {err}");
            return json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP logging/setLevel decode failed",
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

async fn forward_cancelled_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let backend_response = match send_to_backend_url(
        state,
        state.backend_notifications_cancelled_url(),
        incoming_headers,
        body,
    )
    .await
    {
        Ok(response) => response,
        Err(response) => return response,
    };

    if backend_response.status().is_success() {
        return empty_response(StatusCode::ACCEPTED);
    }

    response_from_backend(backend_response)
}

async fn send_transport_to_backend(
    state: &AppState,
    method: reqwest::Method,
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
    body: Option<Bytes>,
    session_validated: bool,
) -> Result<reqwest::Response, Response> {
    let target_url = build_backend_transport_url(state.backend_transport_url(), uri);
    let mut request = state
        .client
        .request(method, target_url)
        .headers(build_forwarded_headers_with_session_validation(
            incoming_headers,
            session_validated,
        ));
    if let Some(body) = body {
        request = request.body(body);
    }
    request.send().await.map_err(|err| {
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

async fn send_session_delete_to_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    session_validated: bool,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .delete(derive_backend_session_delete_url(state.backend_rpc_url()))
        .headers(build_forwarded_headers_with_session_validation(
            incoming_headers,
            session_validated,
        ))
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP session delete dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": "Backend MCP session delete dispatch failed",
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

async fn send_resources_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_resources_list_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP resources/list dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/list dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_resources_read_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_resources_read_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP resources/read dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/read dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_resources_subscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_resources_subscribe_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP resources/subscribe dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/subscribe dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_resources_unsubscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_resources_unsubscribe_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP resources/unsubscribe dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/unsubscribe dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_resource_templates_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_resource_templates_list_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP resources/templates/list dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP resources/templates/list dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_roots_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_roots_list_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP roots/list dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP roots/list dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_completion_complete_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_completion_complete_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP completion/complete dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP completion/complete dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_sampling_create_message_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_sampling_create_message_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP sampling/createMessage dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP sampling/createMessage dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_logging_set_level_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_logging_set_level_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP logging/setLevel dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP logging/setLevel dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_prompts_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_prompts_list_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP prompts/list dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP prompts/list dispatch failed",
                        "data": err.to_string(),
                    }
                }),
            )
        })
}

async fn send_prompts_get_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Result<reqwest::Response, Response> {
    state
        .client
        .post(state.backend_prompts_get_url())
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP prompts/get dispatch failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": Value::Null,
                    "error": {
                        "code": -32000,
                        "message": "Backend MCP prompts/get dispatch failed",
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
    let plan = match resolve_tools_call(state, &incoming_headers, &request, body.clone()).await {
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
            if payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string()))
                && payload.get("error").is_some()
            {
                return Err(ResolveToolsCallError::JsonRpcError { payload, headers });
            }
        }
        return Err(ResolveToolsCallError::Fallback(format!(
            "resolve returned status {status}"
        )));
    }

    serde_json::from_slice::<ResolvedMcpToolCallPlan>(&response_body).map_err(|err| {
        if let Ok(payload) = serde_json::from_slice::<Value>(&response_body) {
            if payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string()))
                && payload.get("error").is_some()
            {
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
    let cache_key = build_tools_call_plan_cache_key(incoming_headers, request)
        .map_err(ResolveToolsCallError::Fallback)?;
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
    if state.use_rmcp_upstream_client() {
        #[cfg(feature = "rmcp-upstream-client")]
        match execute_tools_call_via_rmcp(state, incoming_headers, request, plan).await {
            Ok(response) => return Ok(response),
            Err(err) => warn!("Rust MCP rmcp tools/call fallback: {err}"),
        }
    }

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
        state
            .upstream_tool_sessions()
            .lock()
            .await
            .remove(&session_key);
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
    response.headers_mut().insert(
        HeaderName::from_static(UPSTREAM_CLIENT_HEADER),
        HeaderValue::from_static("native"),
    );
    Ok(response)
}

#[cfg(feature = "rmcp-upstream-client")]
async fn execute_tools_call_via_rmcp(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    plan: &ResolvedMcpToolCallPlan,
) -> Result<Response, String> {
    let remote_tool_name = plan
        .remote_tool_name
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing remote_tool_name".to_string())?;
    let protocol_version = incoming_headers
        .get(MCP_PROTOCOL_VERSION_HEADER)
        .and_then(|value| value.to_str().ok())
        .unwrap_or(state.protocol_version())
        .to_string();
    let downstream_session_id = incoming_headers
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let session_key = build_upstream_session_key(downstream_session_id.as_deref(), plan)?;

    let rmcp_client =
        get_or_create_rmcp_upstream_client(state, plan, &session_key, &protocol_version).await?;

    let response = match invoke_tools_call_via_rmcp(rmcp_client.as_ref(), request, remote_tool_name)
        .await
    {
        Ok(response) => response,
        Err(err) => {
            state
                .rmcp_upstream_clients()
                .lock()
                .await
                .remove(&session_key);
            let retried_client =
                get_or_create_rmcp_upstream_client(state, plan, &session_key, &protocol_version)
                    .await?;
            invoke_tools_call_via_rmcp(retried_client.as_ref(), request, remote_tool_name)
                .await
                .map_err(|retry_err| format!("rmcp retry failed after {err}: {retry_err}"))?
        }
    };

    let mut response = response;
    if let Some(session_id) = downstream_session_id {
        if let Ok(value) = HeaderValue::from_str(&session_id) {
            response
                .headers_mut()
                .insert(HeaderName::from_static("mcp-session-id"), value);
        }
    }
    response.headers_mut().insert(
        HeaderName::from_static(UPSTREAM_CLIENT_HEADER),
        HeaderValue::from_static("rmcp"),
    );
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

    let upstream_session_id =
        initialize_upstream_session(state, plan, protocol_version, timeout_ms).await?;
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
        return Err(format!(
            "upstream initialize returned status {}",
            response.status()
        ));
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
        let _ =
            send_initialized_notification(state, server_url, plan, protocol_version, session_id)
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
    params_object.insert(
        "name".to_string(),
        Value::String(remote_tool_name.to_string()),
    );

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

#[cfg(feature = "rmcp-upstream-client")]
async fn get_or_create_rmcp_upstream_client(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    session_key: &str,
    protocol_version: &str,
) -> Result<Arc<RmcpRunningService<RmcpRoleClient, RmcpClientInfo>>, String> {
    {
        let mut clients = state.rmcp_upstream_clients().lock().await;
        if let Some(existing) = clients.get_mut(session_key) {
            if existing.last_used.elapsed() < state.upstream_session_ttl()
                && !existing.client.is_closed()
            {
                existing.last_used = Instant::now();
                return Ok(existing.client.clone());
            }
            clients.remove(session_key);
        }
    }

    let transport = StreamableHttpClientTransport::from_config(build_rmcp_transport_config(
        plan,
        protocol_version,
    )?);
    let client_info = build_rmcp_client_info(state, protocol_version)?;
    let client = Arc::new(
        rmcp_serve_client(client_info, transport)
            .await
            .map_err(|err| format!("rmcp upstream client initialize failed: {err}"))?,
    );

    state.rmcp_upstream_clients().lock().await.insert(
        session_key.to_string(),
        CachedRmcpUpstreamClient {
            client: client.clone(),
            last_used: Instant::now(),
        },
    );
    Ok(client)
}

#[cfg(feature = "rmcp-upstream-client")]
fn build_rmcp_transport_config(
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
) -> Result<StreamableHttpClientTransportConfig, String> {
    let server_url = plan
        .server_url
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
    let mut custom_headers = HashMap::new();
    custom_headers.insert(
        HeaderName::from_static(MCP_PROTOCOL_VERSION_HEADER),
        HeaderValue::from_str(protocol_version)
            .map_err(|err| format!("invalid protocol version header: {err}"))?,
    );

    if let Some(header_values) = plan.headers.as_ref() {
        for (name, value) in header_values {
            let header_name = HeaderName::from_str(name)
                .map_err(|err| format!("invalid upstream header name '{name}': {err}"))?;
            let header_value = HeaderValue::from_str(value)
                .map_err(|err| format!("invalid upstream header value for '{name}': {err}"))?;
            custom_headers.insert(header_name, header_value);
        }
    }

    Ok(StreamableHttpClientTransportConfig::with_uri(server_url).custom_headers(custom_headers))
}

#[cfg(feature = "rmcp-upstream-client")]
fn build_rmcp_client_info(
    state: &AppState,
    protocol_version: &str,
) -> Result<RmcpClientInfo, String> {
    let protocol_version =
        serde_json::from_value::<RmcpProtocolVersion>(Value::String(protocol_version.to_string()))
            .map_err(|err| format!("invalid rmcp protocol version '{protocol_version}': {err}"))?;

    Ok(RmcpClientInfo::new(
        RmcpClientCapabilities::default(),
        RmcpImplementation::new(
            "contextforge-rust-runtime",
            state.server_version().to_string(),
        ),
    )
    .with_protocol_version(protocol_version))
}

#[cfg(feature = "rmcp-upstream-client")]
async fn invoke_tools_call_via_rmcp(
    client: &RmcpRunningService<RmcpRoleClient, RmcpClientInfo>,
    request: &JsonRpcRequest,
    remote_tool_name: &str,
) -> Result<Response, String> {
    let mut params = request.params.clone();
    let params_object = params
        .as_object_mut()
        .ok_or_else(|| "tools/call params must be an object".to_string())?;
    params_object.insert(
        "name".to_string(),
        Value::String(remote_tool_name.to_string()),
    );

    let params = serde_json::from_value::<RmcpCallToolRequestParams>(params)
        .map_err(|err| format!("rmcp tools/call params decode failed: {err}"))?;
    let response_id = request
        .id
        .clone()
        .unwrap_or(Value::String("__contextforge_tools_call__".to_string()));

    match client.peer().call_tool(params).await {
        Ok(result) => Ok(json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": response_id,
                "result": serde_json::to_value(result)
                    .map_err(|err| format!("rmcp tools/call result encode failed: {err}"))?,
            }),
        )),
        Err(RmcpServiceError::McpError(error)) => Ok(json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": response_id,
                "error": serde_json::to_value(error)
                    .map_err(|err| format!("rmcp tools/call error encode failed: {err}"))?,
            }),
        )),
        Err(err) => Err(format!("rmcp direct tools/call failed: {err}")),
    }
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
        return serde_json::from_str(&data)
            .map_err(|err| format!("invalid SSE JSON payload: {err}"));
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
    build_forwarded_headers_with_session_validation(incoming_headers, false)
}

fn build_forwarded_headers_with_session_validation(
    incoming_headers: &HeaderMap,
    session_validated: bool,
) -> reqwest::header::HeaderMap {
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
    if session_validated {
        forwarded_headers.insert(
            HeaderName::from_static(SESSION_VALIDATED_HEADER),
            HeaderValue::from_static(RUNTIME_NAME),
        );
    }
    forwarded_headers
}

fn build_backend_transport_url(base_url: &str, uri: &axum::http::Uri) -> String {
    match uri.query() {
        Some(query) if !query.is_empty() => format!("{base_url}?{query}"),
        _ => base_url.to_string(),
    }
}

fn response_from_backend(backend_response: reqwest::Response) -> Response {
    response_from_backend_with_session_hint(backend_response, None)
}

fn response_from_backend_with_session_hint(
    backend_response: reqwest::Response,
    session_hint: Option<&str>,
) -> Response {
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

    if headers.get("mcp-session-id").is_none() {
        if let Some(session_id) = session_hint {
            builder = builder.header("mcp-session-id", session_id);
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
            | INTERNAL_AFFINITY_FORWARDED_HEADER
            | SESSION_VALIDATED_HEADER
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
