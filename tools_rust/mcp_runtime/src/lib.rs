pub mod config;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::{Path as AxumPath, State},
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
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, hash_map::DefaultHasher},
    convert::Infallible,
    hash::{Hash, Hasher},
    path::Path,
    str::{self, FromStr},
    sync::Arc,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
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
const SESSION_AUTH_REUSE_HEADER: &str = "x-contextforge-mcp-session-auth-reuse";
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
    backend_authenticate_url: Arc<str>,
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
    backend_resources_list_authz_url: Arc<str>,
    backend_resources_read_authz_url: Arc<str>,
    backend_resource_templates_list_authz_url: Arc<str>,
    backend_prompts_list_authz_url: Arc<str>,
    backend_prompts_get_authz_url: Arc<str>,
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
    session_auth_reuse_enabled: bool,
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
    session_auth_reuse_ttl: Duration,
    public_ingress_enabled: bool,
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
    pub session_auth_reuse_enabled: bool,
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
    #[serde(default)]
    is_authenticated: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct InternalAuthenticateRequest {
    method: String,
    path: String,
    query_string: String,
    headers: HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    client_ip: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InternalAuthenticateResponse {
    auth_context: Value,
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
    encoded_auth_context: Option<String>,
    auth_binding_fingerprint: Option<String>,
    auth_context_expires_at_epoch_ms: Option<u64>,
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
    encoded_auth_context: Option<String>,
    auth_binding_fingerprint: Option<String>,
    auth_context_expires_at_epoch_ms: Option<u64>,
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
            encoded_auth_context: value.encoded_auth_context.clone(),
            auth_binding_fingerprint: value.auth_binding_fingerprint.clone(),
            auth_context_expires_at_epoch_ms: value.auth_context_expires_at_epoch_ms,
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
            encoded_auth_context: value.encoded_auth_context,
            auth_binding_fingerprint: value.auth_binding_fingerprint,
            auth_context_expires_at_epoch_ms: value.auth_context_expires_at_epoch_ms,
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
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
    /// Builds the shared application state for the Rust MCP runtime.
    ///
    /// # Errors
    ///
    /// Returns an error when the HTTP client, database pool, or Redis client cannot be
    /// initialized from the provided configuration.
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
            backend_authenticate_url: Arc::from(derive_backend_authenticate_url(
                &config.backend_rpc_url,
            )),
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
            backend_resources_list_authz_url: Arc::from(derive_backend_resources_list_authz_url(
                &config.backend_rpc_url,
            )),
            backend_resources_read_authz_url: Arc::from(derive_backend_resources_read_authz_url(
                &config.backend_rpc_url,
            )),
            backend_resource_templates_list_authz_url: Arc::from(
                derive_backend_resource_templates_list_authz_url(&config.backend_rpc_url),
            ),
            backend_prompts_list_authz_url: Arc::from(derive_backend_prompts_list_authz_url(
                &config.backend_rpc_url,
            )),
            backend_prompts_get_authz_url: Arc::from(derive_backend_prompts_get_authz_url(
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
            session_auth_reuse_enabled: config.session_auth_reuse_enabled,
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
            session_auth_reuse_ttl: Duration::from_secs(config.session_auth_reuse_ttl_seconds),
            public_ingress_enabled: config.public_listen_http.is_some(),
        })
    }

    #[must_use]
    pub fn backend_rpc_url(&self) -> &str {
        &self.backend_rpc_url
    }

    #[must_use]
    pub fn backend_authenticate_url(&self) -> &str {
        &self.backend_authenticate_url
    }

    #[must_use]
    pub fn backend_initialize_url(&self) -> &str {
        &self.backend_initialize_url
    }

    #[must_use]
    pub fn backend_notifications_initialized_url(&self) -> &str {
        &self.backend_notifications_initialized_url
    }

    #[must_use]
    pub fn backend_notifications_message_url(&self) -> &str {
        &self.backend_notifications_message_url
    }

    #[must_use]
    pub fn backend_notifications_cancelled_url(&self) -> &str {
        &self.backend_notifications_cancelled_url
    }

    #[must_use]
    pub fn backend_transport_url(&self) -> &str {
        &self.backend_transport_url
    }

    #[must_use]
    pub fn backend_tools_list_url(&self) -> &str {
        &self.backend_tools_list_url
    }

    #[must_use]
    pub fn backend_resources_list_url(&self) -> &str {
        &self.backend_resources_list_url
    }

    #[must_use]
    pub fn backend_resources_read_url(&self) -> &str {
        &self.backend_resources_read_url
    }

    #[must_use]
    pub fn backend_resources_subscribe_url(&self) -> &str {
        &self.backend_resources_subscribe_url
    }

    #[must_use]
    pub fn backend_resources_unsubscribe_url(&self) -> &str {
        &self.backend_resources_unsubscribe_url
    }

    #[must_use]
    pub fn backend_resource_templates_list_url(&self) -> &str {
        &self.backend_resource_templates_list_url
    }

    #[must_use]
    pub fn backend_prompts_list_url(&self) -> &str {
        &self.backend_prompts_list_url
    }

    #[must_use]
    pub fn backend_prompts_get_url(&self) -> &str {
        &self.backend_prompts_get_url
    }

    #[must_use]
    pub fn backend_roots_list_url(&self) -> &str {
        &self.backend_roots_list_url
    }

    #[must_use]
    pub fn backend_completion_complete_url(&self) -> &str {
        &self.backend_completion_complete_url
    }

    #[must_use]
    pub fn backend_sampling_create_message_url(&self) -> &str {
        &self.backend_sampling_create_message_url
    }

    #[must_use]
    pub fn backend_logging_set_level_url(&self) -> &str {
        &self.backend_logging_set_level_url
    }

    #[must_use]
    pub fn backend_tools_list_authz_url(&self) -> &str {
        &self.backend_tools_list_authz_url
    }

    #[must_use]
    pub fn backend_resources_list_authz_url(&self) -> &str {
        &self.backend_resources_list_authz_url
    }

    #[must_use]
    pub fn backend_resources_read_authz_url(&self) -> &str {
        &self.backend_resources_read_authz_url
    }

    #[must_use]
    pub fn backend_resource_templates_list_authz_url(&self) -> &str {
        &self.backend_resource_templates_list_authz_url
    }

    #[must_use]
    pub fn backend_prompts_list_authz_url(&self) -> &str {
        &self.backend_prompts_list_authz_url
    }

    #[must_use]
    pub fn backend_prompts_get_authz_url(&self) -> &str {
        &self.backend_prompts_get_authz_url
    }

    #[must_use]
    pub fn backend_tools_call_url(&self) -> &str {
        &self.backend_tools_call_url
    }

    #[must_use]
    pub fn backend_tools_call_resolve_url(&self) -> &str {
        &self.backend_tools_call_resolve_url
    }

    #[must_use]
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

    #[must_use]
    pub fn supported_protocol_versions(&self) -> &[String] {
        self.supported_protocol_versions.as_slice()
    }

    #[must_use]
    pub fn server_name(&self) -> &str {
        &self.server_name
    }

    #[must_use]
    pub fn server_version(&self) -> &str {
        &self.server_version
    }

    #[must_use]
    pub fn instructions(&self) -> &str {
        &self.instructions
    }

    #[allow(clippy::unused_self)]
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

    #[must_use]
    pub fn session_core_enabled(&self) -> bool {
        self.session_core_enabled
    }

    #[must_use]
    pub fn event_store_enabled(&self) -> bool {
        self.event_store_enabled
    }

    #[must_use]
    pub fn resume_core_enabled(&self) -> bool {
        self.resume_core_enabled
    }

    #[must_use]
    pub fn live_stream_core_enabled(&self) -> bool {
        self.live_stream_core_enabled
    }

    #[must_use]
    pub fn affinity_core_enabled(&self) -> bool {
        self.affinity_core_enabled
    }

    #[must_use]
    pub fn session_auth_reuse_enabled(&self) -> bool {
        self.session_auth_reuse_enabled
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

    #[must_use]
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

    fn session_auth_reuse_ttl(&self) -> Duration {
        self.session_auth_reuse_ttl
    }

    fn public_ingress_enabled(&self) -> bool {
        self.public_ingress_enabled
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
        .route(
            "/servers/{server_id}/mcp",
            get(transport_get_server_scoped)
                .delete(transport_delete_server_scoped)
                .post(rpc_server_scoped),
        )
        .route(
            "/servers/{server_id}/mcp/",
            get(transport_get_server_scoped)
                .delete(transport_delete_server_scoped)
                .post(rpc_server_scoped),
        )
        .with_state(state)
}

/// Runs the Rust MCP runtime with the configured listeners.
///
/// # Errors
///
/// Returns an error when configuration parsing fails, listener startup fails, or a listener
/// exits with an application-level runtime error.
pub async fn run(config: RuntimeConfig) -> Result<(), RuntimeError> {
    let state = AppState::new(&config)?;
    let app = build_router(state);

    let primary_target = config.listen_target().map_err(RuntimeError::Config)?;
    let public_http_addr = config.public_listen_addr().map_err(RuntimeError::Config)?;
    let shutdown_after = config.exit_after_startup_ms.map(Duration::from_millis);

    match (primary_target, public_http_addr) {
        (ListenTarget::Http(addr), None) => {
            serve_http(app, addr, shutdown_after).await?;
        }
        (ListenTarget::Http(addr), Some(public_addr)) => {
            tokio::try_join!(
                serve_http(app.clone(), addr, shutdown_after),
                serve_http(app, public_addr, shutdown_after)
            )?;
        }
        (ListenTarget::Uds(path), None) => {
            serve_uds(app, path, shutdown_after).await?;
        }
        (ListenTarget::Uds(path), Some(public_addr)) => {
            tokio::try_join!(
                serve_uds(app.clone(), path, shutdown_after),
                serve_http(app, public_addr, shutdown_after)
            )?;
        }
    }

    Ok(())
}

async fn serve_http(
    app: Router,
    addr: std::net::SocketAddr,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    info!("starting Rust MCP runtime on http://{addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
    }
    Ok(())
}

async fn serve_uds(
    app: Router,
    path: std::path::PathBuf,
    shutdown_after: Option<Duration>,
) -> Result<(), RuntimeError> {
    if Path::new(&path).exists() {
        std::fs::remove_file(&path)?;
    }
    info!("starting Rust MCP runtime on unix://{}", path.display());
    let listener = tokio::net::UnixListener::bind(&path)?;
    if let Some(delay) = shutdown_after {
        axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                tokio::time::sleep(delay).await;
            })
            .await?;
    } else {
        axum::serve(listener, app).await?;
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
        session_auth_reuse_enabled: state.session_auth_reuse_enabled(),
        active_sessions,
    })
}

async fn transport_get(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_get_inner(state, headers, uri, None).await
}

async fn transport_delete(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_delete_inner(state, headers, uri, None).await
}

async fn transport_get_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_get_inner(state, headers, uri, Some(server_id)).await
}

async fn transport_delete_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_delete_inner(state, headers, uri, Some(server_id)).await
}

async fn transport_get_inner(
    state: AppState,
    headers: HeaderMap,
    uri: axum::http::Uri,
    server_id: Option<String>,
) -> Response {
    let (headers, path) = match authenticate_public_request_if_needed(
        &state,
        "GET",
        headers,
        &uri,
        server_id.as_deref(),
    )
    .await
    {
        Ok(result) => result,
        Err(response) => return response,
    };
    forward_transport_request(&state, reqwest::Method::GET, headers, path, uri).await
}

async fn transport_delete_inner(
    state: AppState,
    headers: HeaderMap,
    uri: axum::http::Uri,
    server_id: Option<String>,
) -> Response {
    let (headers, path) = match authenticate_public_request_if_needed(
        &state,
        "DELETE",
        headers,
        &uri,
        server_id.as_deref(),
    )
    .await
    {
        Ok(result) => result,
        Err(response) => return response,
    };
    forward_transport_request(&state, reqwest::Method::DELETE, headers, path, uri).await
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
    rpc_inner(state, headers, uri, body, None).await
}

async fn rpc_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
) -> Response {
    rpc_inner(state, headers, uri, body, Some(server_id)).await
}

async fn rpc_inner(
    state: AppState,
    headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
    server_id: Option<String>,
) -> Response {
    let (headers, path) = match authenticate_public_request_if_needed(
        &state,
        "POST",
        headers,
        &uri,
        server_id.as_deref(),
    )
    .await
    {
        Ok(result) => result,
        Err(response) => return response,
    };

    if let Err(response) = validate_protocol_version(&state, &headers) {
        return response;
    }

    let request = match decode_request(&body) {
        Ok(request) => request,
        Err(response) => return response,
    };

    let server_scoped_request = has_server_scope(&headers);
    let server_scoped_tools_list = request.method == "tools/list" && server_scoped_request;
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
    let rust_db_direct_resources_list =
        specialized_resources_list && server_scoped_request && state.db_pool().is_some();
    let rust_db_direct_resources_read = specialized_resources_read
        && server_scoped_request
        && state.db_pool().is_some()
        && can_use_direct_resources_read(&request.params);
    let rust_db_direct_resource_templates_list =
        specialized_resource_templates_list && server_scoped_request && state.db_pool().is_some();
    let rust_db_direct_prompts_list =
        specialized_prompts_list && server_scoped_request && state.db_pool().is_some();
    let rust_db_direct_prompts_get = specialized_prompts_get
        && server_scoped_request
        && state.db_pool().is_some()
        && can_use_direct_prompts_get(&request.params);
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
            path.as_str(),
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
    } else if rust_db_direct_resources_list {
        "db-resources-list-direct"
    } else if specialized_resources_list {
        "backend-resources-list-direct"
    } else if rust_db_direct_resources_read {
        "db-resources-read-direct"
    } else if specialized_resources_read {
        "backend-resources-read-direct"
    } else if specialized_resources_subscribe {
        "backend-resources-subscribe-direct"
    } else if specialized_resources_unsubscribe {
        "backend-resources-unsubscribe-direct"
    } else if rust_db_direct_resource_templates_list {
        "db-resource-templates-list-direct"
    } else if specialized_resource_templates_list {
        "backend-resource-templates-list-direct"
    } else if rust_db_direct_prompts_list {
        "db-prompts-list-direct"
    } else if specialized_prompts_list {
        "backend-prompts-list-direct"
    } else if rust_db_direct_prompts_get {
        "db-prompts-get-direct"
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

    if rust_db_direct_resources_list {
        return direct_server_resources_list(&state, effective_headers, request.id.clone()).await;
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

    if rust_db_direct_resources_read {
        return direct_server_resources_read(
            &state,
            effective_headers,
            request.id.clone(),
            &request,
            body,
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

    if rust_db_direct_resource_templates_list {
        return direct_server_resource_templates_list(
            &state,
            effective_headers,
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

    if rust_db_direct_prompts_list {
        return direct_server_prompts_list(&state, effective_headers, request.id.clone()).await;
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

    if rust_db_direct_prompts_get {
        return direct_server_prompts_get(
            &state,
            effective_headers,
            request.id.clone(),
            &request,
            body,
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

    if request.method == "initialize"
        && let Err(response) =
            validate_initialize_params(&state, &request.params, request.id.as_ref())
    {
        return response;
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

fn derive_backend_resources_list_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/list/authz");
    }
    format!(
        "{}/_internal/mcp/resources/list/authz",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resources_read_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/read/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/read/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/read/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/read/authz");
    }
    format!(
        "{}/_internal/mcp/resources/read/authz",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_resource_templates_list_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/resources/templates/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/templates/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/resources/templates/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/resources/templates/list/authz");
    }
    format!(
        "{}/_internal/mcp/resources/templates/list/authz",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_prompts_list_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/list/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/list/authz");
    }
    format!(
        "{}/_internal/mcp/prompts/list/authz",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_prompts_get_authz_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/get/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/get/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/prompts/get/authz");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/prompts/get/authz");
    }
    format!(
        "{}/_internal/mcp/prompts/get/authz",
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

fn derive_backend_authenticate_url(backend_rpc_url: &str) -> String {
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc") {
        return format!("{prefix}/_internal/mcp/authenticate");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/_internal/mcp/rpc/") {
        return format!("{prefix}/_internal/mcp/authenticate");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc") {
        return format!("{prefix}/_internal/mcp/authenticate");
    }
    if let Some(prefix) = backend_rpc_url.strip_suffix("/rpc/") {
        return format!("{prefix}/_internal/mcp/authenticate");
    }
    format!(
        "{}/_internal/mcp/authenticate",
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
            "invalid MCP_RUST_DATABASE_URL '{normalized_url}': {err}"
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
        RuntimeError::Config(format!("invalid MCP_RUST_REDIS_URL '{redis_url}': {err}"))
    })?;
    Ok(Some(client))
}

fn has_server_scope(headers: &HeaderMap) -> bool {
    headers.contains_key("x-contextforge-server-id")
}

fn can_use_direct_resources_read(params: &Value) -> bool {
    let Some(params) = params.as_object() else {
        return false;
    };
    matches!(params.get("uri"), Some(Value::String(uri)) if !uri.is_empty())
        && !params.contains_key("requestId")
        && !params.contains_key("_meta")
}

fn can_use_direct_prompts_get(params: &Value) -> bool {
    let Some(params) = params.as_object() else {
        return false;
    };

    let has_name = matches!(params.get("name"), Some(Value::String(name)) if !name.is_empty());
    let arguments_are_empty = match params.get("arguments") {
        None | Some(Value::Null) => true,
        Some(Value::Object(arguments)) => arguments.is_empty(),
        _ => false,
    };

    has_name && arguments_are_empty && !params.contains_key("_meta")
}

fn public_mcp_path(uri: &axum::http::Uri, server_id: Option<&str>) -> String {
    match server_id {
        Some(server_id) if uri.path().ends_with('/') => format!("/servers/{server_id}/mcp/"),
        Some(server_id) => format!("/servers/{server_id}/mcp"),
        None => uri.path().to_string(),
    }
}

fn build_public_auth_headers(incoming_headers: &HeaderMap) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    for (name, value) in incoming_headers {
        if matches!(
            name.as_str(),
            "host"
                | "content-length"
                | "connection"
                | "transfer-encoding"
                | "keep-alive"
                | RUNTIME_HEADER
                | SESSION_VALIDATED_HEADER
                | INTERNAL_AFFINITY_FORWARDED_HEADER
                | "x-contextforge-auth-context"
        ) {
            continue;
        }

        if let Ok(value) = value.to_str() {
            headers.insert(name.as_str().to_string(), value.to_string());
        }
    }
    headers
}

fn public_client_ip(incoming_headers: &HeaderMap) -> Option<String> {
    if let Some(value) = incoming_headers
        .get("x-real-ip")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        return Some(value.to_string());
    }

    incoming_headers
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(',').next())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn unix_epoch_millis() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis(),
    )
    .unwrap_or(u64::MAX)
}

fn current_encoded_auth_context_header(incoming_headers: &HeaderMap) -> Option<String> {
    incoming_headers
        .get("x-contextforge-auth-context")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn auth_binding_fingerprint(incoming_headers: &HeaderMap) -> Option<String> {
    let mut material = String::new();

    for header_name in ["authorization", "cookie"] {
        if let Some(value) = incoming_headers
            .get(header_name)
            .and_then(|value| value.to_str().ok())
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            material.push_str(header_name);
            material.push('=');
            material.push_str(value);
            material.push('\n');
        }
    }

    if material.is_empty() {
        return None;
    }

    let digest = Sha256::digest(material.as_bytes());
    Some(URL_SAFE_NO_PAD.encode(digest))
}

fn can_reuse_session_auth(
    state: &AppState,
    record: &RuntimeSessionRecord,
    incoming_headers: &HeaderMap,
    requested_server_id: Option<&str>,
) -> Option<String> {
    if !state.session_auth_reuse_enabled() {
        return None;
    }

    if requested_server_id.is_some() && record.server_id.as_deref() != requested_server_id {
        return None;
    }

    let expected_fingerprint = record.auth_binding_fingerprint.as_deref()?;
    let actual_fingerprint = auth_binding_fingerprint(incoming_headers)?;
    if actual_fingerprint != expected_fingerprint {
        return None;
    }

    let expires_at = record.auth_context_expires_at_epoch_ms?;
    if unix_epoch_millis() >= expires_at {
        return None;
    }

    record.encoded_auth_context.clone()
}

#[allow(clippy::result_large_err)]
fn encode_internal_auth_context_header(auth_context: &Value) -> Result<HeaderValue, Response> {
    let encoded = URL_SAFE_NO_PAD.encode(serde_json::to_vec(auth_context).map_err(|err| {
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": format!("Internal MCP auth context serialization failed: {err}"),
            }),
        )
    })?);

    HeaderValue::from_str(&encoded).map_err(|err| {
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": format!("Internal MCP auth context header encoding failed: {err}"),
            }),
        )
    })
}

async fn authenticate_public_request_if_needed(
    state: &AppState,
    method: &str,
    mut incoming_headers: HeaderMap,
    uri: &axum::http::Uri,
    server_id: Option<&str>,
) -> Result<(HeaderMap, String), Response> {
    if let Some(server_id) = server_id {
        inject_server_id_header(&mut incoming_headers, server_id);
    }

    let public_path = public_mcp_path(uri, server_id);
    if !state.public_ingress_enabled() {
        return Ok((incoming_headers, public_path));
    }
    if incoming_headers.contains_key("x-contextforge-auth-context") {
        return Ok((incoming_headers, public_path));
    }

    if state.session_core_enabled()
        && let Some(session_id) = runtime_session_id_from_request(&incoming_headers, uri)
        && let Some(record) = get_runtime_session(state, &session_id).await
        && let Some(encoded_auth_context) =
            can_reuse_session_auth(state, &record, &incoming_headers, server_id)
    {
        let encoded_auth_context = HeaderValue::from_str(&encoded_auth_context).map_err(|err| {
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": format!("Stored MCP auth context header encoding failed: {err}"),
                }),
            )
        })?;
        incoming_headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encoded_auth_context,
        );
        return Ok((incoming_headers, public_path));
    }

    let request_body = InternalAuthenticateRequest {
        method: method.to_string(),
        path: public_path.clone(),
        query_string: uri.query().unwrap_or_default().to_string(),
        headers: build_public_auth_headers(&incoming_headers),
        client_ip: public_client_ip(&incoming_headers),
    };

    let backend_response = state
        .client
        .post(state.backend_authenticate_url())
        .header(RUNTIME_HEADER, RUNTIME_NAME)
        .json(&request_body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP authenticate failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": "Backend MCP authenticate failed",
                    "error": err.to_string(),
                }),
            )
        })?;

    if !backend_response.status().is_success() {
        return Err(response_from_backend(backend_response));
    }

    let response_body: InternalAuthenticateResponse =
        backend_response.json().await.map_err(|err| {
            error!("backend MCP authenticate decode failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "detail": "Backend MCP authenticate decode failed",
                    "error": err.to_string(),
                }),
            )
        })?;

    let encoded_auth_context = encode_internal_auth_context_header(&response_body.auth_context)?;
    incoming_headers.insert(
        HeaderName::from_static("x-contextforge-auth-context"),
        encoded_auth_context,
    );

    Ok((incoming_headers, public_path))
}

#[allow(clippy::result_large_err)]
fn decode_request(body: &[u8]) -> Result<JsonRpcRequest, Response> {
    let parsed: Value = serde_json::from_slice(body).map_err(|_| parse_error_response())?;

    if parsed.is_array() {
        return Err(batch_rejected_response());
    }

    let object = parsed
        .as_object()
        .ok_or_else(|| invalid_request_response(&Value::Null))?;

    let request_id = object.get("id").cloned().unwrap_or(Value::Null);
    if let Some(version) = object.get("jsonrpc").and_then(Value::as_str)
        && version != JSONRPC_VERSION
    {
        return Err(invalid_request_response(&request_id));
    }

    let method = object
        .get("method")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid_request_response(&request_id))?;

    Ok(JsonRpcRequest {
        jsonrpc: Some(JSONRPC_VERSION.to_string()),
        method: method.to_string(),
        params: object.get("params").cloned().unwrap_or_else(|| json!({})),
        id: object.get("id").cloned(),
    })
}

#[allow(clippy::result_large_err)]
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

#[allow(clippy::result_large_err)]
fn validate_initialize_params(
    state: &AppState,
    params: &Value,
    request_id: Option<&Value>,
) -> Result<(), Response> {
    let params: InitializeParams = match serde_json::from_value(params.clone()) {
        Ok(params) => params,
        Err(_) => {
            return Err(json_response(
                StatusCode::OK,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id.cloned(),
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
                "id": request_id.cloned(),
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

fn invalid_request_response(id: &Value) -> Response {
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

    if let Some(existing) = get_runtime_session(state, &session_id).await
        && !runtime_session_allows_access(&existing, auth_context.as_ref(), &incoming_headers)
    {
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

    inject_session_header(&mut incoming_headers, &session_id);
    if let Some(server_id) = extract_server_id_header(&incoming_headers) {
        inject_server_id_header(&mut incoming_headers, &server_id);
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
        .map_or_else(|| session_id.clone(), str::to_string);

    if status.is_success() {
        let mut record = RuntimeSessionRecord {
            owner_email: auth_context
                .as_ref()
                .and_then(|context| context.email.clone()),
            server_id: extract_server_id_header(&incoming_headers),
            protocol_version: requested_protocol_version(request),
            client_capabilities: extract_client_capabilities(request),
            encoded_auth_context: None,
            auth_binding_fingerprint: None,
            auth_context_expires_at_epoch_ms: None,
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
        };
        maybe_bind_session_auth_context(
            state,
            &mut record,
            &incoming_headers,
            auth_context.as_ref(),
        );
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
    if let Ok(value) = HeaderValue::from_str(if state.session_auth_reuse_enabled() {
        "rust"
    } else {
        "python"
    }) {
        response
            .headers_mut()
            .insert(HeaderName::from_static(SESSION_AUTH_REUSE_HEADER), value);
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

    if state.redis().await.is_some()
        && let Some(redis_count) = count_runtime_sessions_in_redis(state).await
    {
        return redis_count;
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
            if let Ok(ttl_i64) = i64::try_from(state.session_ttl().as_secs()) {
                let _ = redis.expire::<_, bool>(&key, ttl_i64).await;
            }
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
    match redis
        .get::<_, Option<String>>(pool_owner_key(session_id))
        .await
    {
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

    let mut publish_conn = state.redis().await.ok_or_else(|| {
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

    let payload_json: String = message.get_payload().map_err(|err| {
        affinity_forward_error_response("Affinity response payload decode failed", err)
    })?;
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
        if matches!(
            lower.as_str(),
            "connection" | "transfer-encoding" | "keep-alive" | "content-length"
        ) {
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
    if !has_session_id && let Some(session_id) = session_hint {
        builder = builder.header("mcp-session-id", session_id);
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
    if !input.len().is_multiple_of(2) {
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

const STORE_EVENT_LUA: &str = r"
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
";

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
    let ttl_i64 = i64::try_from(ttl).map_err(|_| {
        json_response(
            StatusCode::BAD_REQUEST,
            json!({"detail": "Rust event store ttl exceeds supported range"}),
        )
    })?;
    let max_events_i64 = i64::try_from(max_events).map_err(|_| {
        json_response(
            StatusCode::BAD_REQUEST,
            json!({"detail": "Rust event store max events exceeds supported range"}),
        )
    })?;

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
        .arg(ttl_i64)
        .arg(max_events_i64)
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
        && index_record.seq_num < start_seq
    {
        return Ok(EventStoreReplayResponse {
            stream_id: None,
            events: Vec::new(),
        });
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

    if let (Some(session_server_id), Some(request_server_id)) = (
        record.server_id.as_deref(),
        extract_server_id_header(incoming_headers).as_deref(),
    ) && session_server_id != request_server_id
    {
        return Err(json_response(
            StatusCode::FORBIDDEN,
            json!({
                "detail": "Session access denied",
            }),
        ));
    }

    let auth_context = decode_internal_auth_context_from_headers_optional(incoming_headers);
    if !runtime_session_allows_access(&record, auth_context.as_ref(), incoming_headers) {
        return Err(json_response(
            StatusCode::FORBIDDEN,
            json!({
                "detail": "Session access denied",
            }),
        ));
    }

    inject_session_header(incoming_headers, &session_id);
    if let Some(server_id) = record.server_id.as_deref()
        && !incoming_headers.contains_key("x-contextforge-server-id")
    {
        inject_server_id_header(incoming_headers, server_id);
    }

    Ok(Some(session_id))
}

fn runtime_session_allows_access(
    record: &RuntimeSessionRecord,
    auth_context: Option<&InternalAuthContext>,
    incoming_headers: &HeaderMap,
) -> bool {
    if let Some(expected_fingerprint) = record.auth_binding_fingerprint.as_deref() {
        let Some(actual_fingerprint) = auth_binding_fingerprint(incoming_headers) else {
            return false;
        };
        if actual_fingerprint != expected_fingerprint {
            return false;
        }
    }

    let Some(owner_email) = record.owner_email.as_deref() else {
        return true;
    };
    let Some(auth_context) = auth_context else {
        return false;
    };
    auth_context.email.as_deref() == Some(owner_email)
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

fn maybe_bind_session_auth_context(
    state: &AppState,
    record: &mut RuntimeSessionRecord,
    incoming_headers: &HeaderMap,
    auth_context: Option<&InternalAuthContext>,
) {
    if !state.session_auth_reuse_enabled() {
        record.encoded_auth_context = None;
        record.auth_binding_fingerprint = None;
        record.auth_context_expires_at_epoch_ms = None;
        return;
    }

    let Some(auth_context) = auth_context else {
        record.encoded_auth_context = None;
        record.auth_binding_fingerprint = None;
        record.auth_context_expires_at_epoch_ms = None;
        return;
    };

    if !auth_context.is_authenticated {
        record.encoded_auth_context = None;
        record.auth_binding_fingerprint = None;
        record.auth_context_expires_at_epoch_ms = None;
        return;
    }

    let Some(encoded_auth_context) = current_encoded_auth_context_header(incoming_headers) else {
        record.encoded_auth_context = None;
        record.auth_binding_fingerprint = None;
        record.auth_context_expires_at_epoch_ms = None;
        return;
    };

    let Some(fingerprint) = auth_binding_fingerprint(incoming_headers) else {
        record.encoded_auth_context = None;
        record.auth_binding_fingerprint = None;
        record.auth_context_expires_at_epoch_ms = None;
        return;
    };

    record.encoded_auth_context = Some(encoded_auth_context);
    record.auth_binding_fingerprint = Some(fingerprint);
    let auth_context_ttl_ms =
        u64::try_from(state.session_auth_reuse_ttl().as_millis()).unwrap_or(u64::MAX);
    record.auth_context_expires_at_epoch_ms =
        Some(unix_epoch_millis().saturating_add(auth_context_ttl_ms));
}

fn inject_session_header(incoming_headers: &mut HeaderMap, session_id: &str) {
    if let Ok(value) = HeaderValue::from_str(session_id) {
        incoming_headers.insert(HeaderName::from_static("mcp-session-id"), value);
    }
}

fn inject_server_id_header(incoming_headers: &mut HeaderMap, server_id: &str) {
    if let Ok(value) = HeaderValue::from_str(server_id) {
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

    let session_id = response_session_id.clone()?;

    let existing = get_runtime_session(state, &session_id).await;
    let auth_context = decode_internal_auth_context_from_headers_optional(incoming_headers);
    let now = Instant::now();
    let mut record = RuntimeSessionRecord {
        owner_email: existing
            .as_ref()
            .and_then(|record| record.owner_email.clone())
            .or_else(|| {
                auth_context
                    .as_ref()
                    .and_then(|context| context.email.clone())
            }),
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
        encoded_auth_context: existing
            .as_ref()
            .and_then(|record| record.encoded_auth_context.clone()),
        auth_binding_fingerprint: existing
            .as_ref()
            .and_then(|record| record.auth_binding_fingerprint.clone()),
        auth_context_expires_at_epoch_ms: existing
            .as_ref()
            .and_then(|record| record.auth_context_expires_at_epoch_ms),
        created_at: existing.as_ref().map_or(now, |record| record.created_at),
        last_used: now,
    };
    maybe_bind_session_auth_context(state, &mut record, incoming_headers, auth_context.as_ref());
    upsert_runtime_session(state, session_id.clone(), record).await;

    Some(session_id)
}

fn accepts_sse(headers: &HeaderMap) -> bool {
    headers
        .get("accept")
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| {
            value.split(',').any(|part| {
                let normalized = part.trim().to_ascii_lowercase();
                normalized == "text/event-stream"
                    || normalized.starts_with("text/event-stream;")
                    || normalized == "*/*"
            })
        })
}

fn parse_sse_line(frame: &mut PendingSseFrame, raw_line: &str) {
    if raw_line.starts_with(':') {
        return;
    }

    let (field, value) = raw_line
        .split_once(':')
        .map_or((raw_line, ""), |(field, value)| (field, value.trim_start()));

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
        event = event.id(id);
    }
    if let Some(name) = frame.event.as_deref() {
        event = event.event(name);
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

    let keep_alive = KeepAlive::new().interval(Duration::from_secs(15)).text("");
    let poll_interval = state.event_store_poll_interval();
    let session_id = session_id.map(str::to_string);
    let stream_session_id = session_id.clone();
    let state_cloned = state.clone();
    let mut replay_cursor = last_event_id.clone();
    let mut initial_events = initial_replay.events;
    let stream_id = initial_replay.stream_id;

    let event_stream = async_stream::stream! {
        for event in initial_events.drain(..) {
            replay_cursor.clone_from(&event.event_id);
            yield Ok::<Event, Infallible>(build_sse_event(&event.event_id, &event.message));
        }

        if let Some(stream_id_value) = stream_id {
            if protocol_version.as_str() >= "2025-11-25"
                && let Ok(priming_event_id) = store_event_in_rust_event_store(
                    &state_cloned,
                    EventStoreStoreRequest {
                        stream_id: stream_id_value.clone(),
                        message: None,
                        key_prefix: None,
                        max_events_per_stream: None,
                        ttl_seconds: None,
                    },
                ).await {
                    replay_cursor.clone_from(&priming_event_id);
                    yield Ok::<Event, Infallible>(Event::default().id(priming_event_id).data(""));
                }

            loop {
                if let Some(session_id_value) = stream_session_id.as_deref()
                    && get_runtime_session(&state_cloned, session_id_value).await.is_none()
                {
                    break;
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
                            replay_cursor.clone_from(&event.event_id);
                            yield Ok::<Event, Infallible>(build_sse_event(&event.event_id, &event.message));
                        }
                    }
                    Err(_) => break,
                }
            }
        }
    };

    let mut response = Sse::new(event_stream)
        .keep_alive(keep_alive)
        .into_response();
    response
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("text/event-stream"));
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
        HeaderName::from_static(SESSION_AUTH_REUSE_HEADER),
        HeaderValue::from_str(if state.session_auth_reuse_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
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
    if let Some(session_id_value) = session_id.as_deref()
        && let Ok(value) = HeaderValue::from_str(session_id_value)
    {
        response
            .headers_mut()
            .insert(HeaderName::from_static("mcp-session-id"), value);
    }
    response
}

fn handle_live_stream_transport_request(
    state: &AppState,
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
    session_id: Option<&str>,
) -> Response {
    let keep_alive = KeepAlive::new().interval(Duration::from_secs(15)).text("");
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

    let mut response = Sse::new(event_stream)
        .keep_alive(keep_alive)
        .into_response();
    response
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("text/event-stream"));
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
        HeaderValue::from_str(if state.session_core_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    response.headers_mut().insert(
        HeaderName::from_static(EVENT_STORE_HEADER),
        HeaderValue::from_str(if state.event_store_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    response.headers_mut().insert(
        HeaderName::from_static(RESUME_CORE_HEADER),
        HeaderValue::from_str(if state.resume_core_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    response.headers_mut().insert(
        HeaderName::from_static(SESSION_AUTH_REUSE_HEADER),
        HeaderValue::from_str(if state.session_auth_reuse_enabled() {
            "rust"
        } else {
            "python"
        })
        .unwrap_or_else(|_| HeaderValue::from_static("python")),
    );
    if let Some(session_id_value) = response_session_id.as_deref()
        && let Ok(value) = HeaderValue::from_str(session_id_value)
    {
        response
            .headers_mut()
            .insert(HeaderName::from_static("mcp-session-id"), value);
    }
    response
}

fn build_sse_event(event_id: &str, message: &Value) -> Event {
    let event = Event::default().id(event_id);
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
    public_path: String,
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

            let auth_context =
                decode_internal_auth_context_from_headers_optional(&incoming_headers);
            if !runtime_session_allows_access(&record, auth_context.as_ref(), &incoming_headers) {
                return json_response(
                    StatusCode::FORBIDDEN,
                    json!({
                        "detail": "Session access denied",
                    }),
                );
            }
            inject_session_header(&mut incoming_headers, session_id_value);
            if let Some(server_id) = record.server_id.as_deref()
                && !incoming_headers.contains_key("x-contextforge-server-id")
            {
                inject_server_id_header(&mut incoming_headers, server_id);
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
            public_path.as_str(),
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
            &incoming_headers,
            &uri,
            session_id.as_deref(),
        );
    }

    if state.session_core_enabled() && method == reqwest::Method::DELETE && session_id.is_some() {
        let backend_response =
            match send_session_delete_to_backend(state, &incoming_headers, session_validated).await
            {
                Ok(response) => response,
                Err(response) => return response,
            };

        if backend_response.status().is_success()
            && let Some(session_id_value) = session_id.as_deref()
        {
            remove_runtime_session(state, session_id_value).await;
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
        && let Some(session_id_value) = session_id.as_deref()
    {
        remove_runtime_session(state, session_id_value).await;
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
                    "id": request_id.clone(),
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

async fn direct_server_resources_list(
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
            "Rust MCP direct resources/list missing trusted context; falling back to Python dispatcher"
        );
        return forward_resources_list_to_backend(
            state,
            incoming_headers,
            Bytes::from_static(br#"{"jsonrpc":"2.0","method":"resources/list","params":{}}"#),
            request_id,
        )
        .await;
    };

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_resources_list_authz_url(),
        "resources/list",
    )
    .await
    {
        return response;
    }

    match query_server_resources_list_from_db(state, &server_id, &auth_context).await {
        Ok(resources) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "resources": resources,
                },
            }),
        ),
        Err(err) => {
            error!(
                "Rust MCP direct resources/list DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_resources_list_to_backend(
                state,
                incoming_headers,
                Bytes::from_static(br#"{"jsonrpc":"2.0","method":"resources/list","params":{}}"#),
                request_id,
            )
            .await
        }
    }
}

async fn direct_server_resource_templates_list(
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
            "Rust MCP direct resources/templates/list missing trusted context; falling back to Python dispatcher"
        );
        return forward_resource_templates_list_to_backend(
            state,
            incoming_headers,
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","method":"resources/templates/list","params":{}}"#,
            ),
            request_id,
        )
        .await;
    };

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_resource_templates_list_authz_url(),
        "resources/templates/list",
    )
    .await
    {
        return response;
    }

    match query_server_resource_templates_list_from_db(state, &server_id, &auth_context).await {
        Ok(resource_templates) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "resourceTemplates": resource_templates,
                },
            }),
        ),
        Err(err) => {
            error!(
                "Rust MCP direct resources/templates/list DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_resource_templates_list_to_backend(
                state,
                incoming_headers,
                Bytes::from_static(
                    br#"{"jsonrpc":"2.0","method":"resources/templates/list","params":{}}"#,
                ),
                request_id,
            )
            .await
        }
    }
}

async fn direct_server_prompts_list(
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
            "Rust MCP direct prompts/list missing trusted context; falling back to Python dispatcher"
        );
        return forward_prompts_list_to_backend(
            state,
            incoming_headers,
            Bytes::from_static(br#"{"jsonrpc":"2.0","method":"prompts/list","params":{}}"#),
            request_id,
        )
        .await;
    };

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_prompts_list_authz_url(),
        "prompts/list",
    )
    .await
    {
        return response;
    }

    match query_server_prompts_list_from_db(state, &server_id, &auth_context).await {
        Ok(prompts) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "prompts": prompts,
                },
            }),
        ),
        Err(err) => {
            error!(
                "Rust MCP direct prompts/list DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_prompts_list_to_backend(
                state,
                incoming_headers,
                Bytes::from_static(br#"{"jsonrpc":"2.0","method":"prompts/list","params":{}}"#),
                request_id,
            )
            .await
        }
    }
}

async fn direct_server_resources_read(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Response {
    let server_id = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers(&incoming_headers);

    let (Some(server_id), Ok(auth_context)) = (server_id, auth_context) else {
        warn!(
            "Rust MCP direct resources/read missing trusted context; falling back to Python dispatcher"
        );
        return forward_resources_read_to_backend(state, incoming_headers, body, request_id).await;
    };

    let Some(uri) = request
        .params
        .as_object()
        .and_then(|params| params.get("uri"))
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return forward_resources_read_to_backend(state, incoming_headers, body, request_id).await;
    };

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_resources_read_authz_url(),
        "resources/read",
    )
    .await
    {
        return response;
    }

    match query_server_resource_read_from_db(state, &server_id, &auth_context, uri).await {
        Ok(Some(content)) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": {
                    "contents": [content],
                },
            }),
        ),
        Ok(None) => json_response(
            StatusCode::NOT_FOUND,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32002,
                    "message": format!("Resource not found: {uri}"),
                    "data": {"uri": uri},
                },
            }),
        ),
        Err(RuntimeError::Config(reason)) if reason == "fallback-python" => {
            forward_resources_read_to_backend(state, incoming_headers, body, request_id).await
        }
        Err(err) => {
            error!(
                "Rust MCP direct resources/read DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_resources_read_to_backend(state, incoming_headers, body, request_id).await
        }
    }
}

async fn direct_server_prompts_get(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Response {
    let server_id = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers(&incoming_headers);

    let (Some(server_id), Ok(auth_context)) = (server_id, auth_context) else {
        warn!(
            "Rust MCP direct prompts/get missing trusted context; falling back to Python dispatcher"
        );
        return forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await;
    };

    let Some(name) = request
        .params
        .as_object()
        .and_then(|params| params.get("name"))
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await;
    };

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_prompts_get_authz_url(),
        "prompts/get",
    )
    .await
    {
        return response;
    }

    match query_server_prompt_get_from_db(state, &server_id, &auth_context, name).await {
        Ok(Some(result)) => json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": result,
            }),
        ),
        Ok(None) => json_response(
            StatusCode::NOT_FOUND,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32002,
                    "message": format!("Prompt not found: {name}"),
                    "data": {"name": name},
                },
            }),
        ),
        Err(RuntimeError::Config(reason)) if reason == "fallback-python" => {
            forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await
        }
        Err(err) => {
            error!(
                "Rust MCP direct prompts/get DB query failed: {err}; falling back to Python dispatcher"
            );
            forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await
        }
    }
}

async fn query_server_resources_list_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
) -> Result<Vec<Value>, RuntimeError> {
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
                "SELECT r.uri, r.name, r.description, r.mime_type, r.size \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 AND r.uri_template IS NULL AND r.enabled = TRUE",
                &[&server_id],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query(
                "SELECT r.uri, r.name, r.description, r.mime_type, r.size \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 \
                   AND r.uri_template IS NULL \
                   AND r.enabled = TRUE \
                   AND ( \
                        r.visibility = 'public' \
                        OR ($2::bool AND r.owner_email = $3) \
                        OR (COALESCE(array_length($4::text[], 1), 0) > 0 AND r.team_id = ANY($4::text[]) AND r.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    Ok(rows
        .into_iter()
        .map(|row| resource_row_to_value(&row))
        .collect())
}

async fn query_server_resource_templates_list_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
) -> Result<Vec<Value>, RuntimeError> {
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
                "SELECT r.id, r.uri_template, r.name, r.description, r.mime_type \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 AND r.uri_template IS NOT NULL AND r.enabled = TRUE",
                &[&server_id],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query(
                "SELECT r.id, r.uri_template, r.name, r.description, r.mime_type \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 \
                   AND r.uri_template IS NOT NULL \
                   AND r.enabled = TRUE \
                   AND ( \
                        r.visibility = 'public' \
                        OR ($2::bool AND r.owner_email = $3) \
                        OR (COALESCE(array_length($4::text[], 1), 0) > 0 AND r.team_id = ANY($4::text[]) AND r.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    Ok(rows
        .into_iter()
        .map(|row| resource_template_row_to_value(&row))
        .collect())
}

async fn query_server_prompts_list_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
) -> Result<Vec<Value>, RuntimeError> {
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
                "SELECT p.name, p.description, p.argument_schema \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 AND p.enabled = TRUE",
                &[&server_id],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query(
                "SELECT p.name, p.description, p.argument_schema \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 \
                   AND p.enabled = TRUE \
                   AND ( \
                        p.visibility = 'public' \
                        OR ($2::bool AND p.owner_email = $3) \
                        OR (COALESCE(array_length($4::text[], 1), 0) > 0 AND p.team_id = ANY($4::text[]) AND p.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    Ok(rows
        .into_iter()
        .map(|row| prompt_row_to_value(&row))
        .collect())
}

async fn query_server_resource_read_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
    uri: &str,
) -> Result<Option<Value>, RuntimeError> {
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
                "SELECT r.uri, r.mime_type, r.text_content, r.binary_content, r.gateway_id, r.uri_template \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 AND r.uri = $2 AND r.enabled = TRUE \
                 LIMIT 2",
                &[&server_id, &uri],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query(
                "SELECT r.uri, r.mime_type, r.text_content, r.binary_content, r.gateway_id, r.uri_template \
                 FROM resources r \
                 JOIN server_resource_association sra ON r.id = sra.resource_id \
                 WHERE sra.server_id = $1 \
                   AND r.uri = $2 \
                   AND r.enabled = TRUE \
                   AND ( \
                        r.visibility = 'public' \
                        OR ($3::bool AND r.owner_email = $4) \
                        OR (COALESCE(array_length($5::text[], 1), 0) > 0 AND r.team_id = ANY($5::text[]) AND r.visibility IN ('team', 'public')) \
                   ) \
                 LIMIT 2",
                &[&server_id, &uri, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    if rows.len() > 1 {
        warn!(
            "Rust MCP direct resources/read found multiple rows for uri={uri}; falling back to Python dispatcher"
        );
        return Err(RuntimeError::Config("fallback-python".to_string()));
    }

    let Some(row) = rows.into_iter().next() else {
        return Ok(None);
    };

    let gateway_id = row.get::<_, Option<String>>("gateway_id");
    let uri_template = row.get::<_, Option<String>>("uri_template");
    if gateway_id.is_some() || uri_template.is_some() {
        return Err(RuntimeError::Config("fallback-python".to_string()));
    }

    let text_content = row.get::<_, Option<String>>("text_content");
    let binary_content = row.get::<_, Option<Vec<u8>>>("binary_content");
    let resource_uri = row.get::<_, String>("uri");
    let mime_type = row.get::<_, Option<String>>("mime_type");

    let mut content = serde_json::Map::new();
    content.insert("uri".to_string(), Value::String(resource_uri));
    if let Some(mime_type) = mime_type {
        content.insert("mimeType".to_string(), Value::String(mime_type));
    }
    if let Some(text_content) = text_content {
        content.insert("text".to_string(), Value::String(text_content));
        return Ok(Some(Value::Object(content)));
    }
    if let Some(binary_content) = binary_content {
        content.insert(
            "blob".to_string(),
            Value::String(base64::engine::general_purpose::STANDARD.encode(binary_content)),
        );
        return Ok(Some(Value::Object(content)));
    }

    Err(RuntimeError::Config("fallback-python".to_string()))
}

async fn query_server_prompt_get_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
    name: &str,
) -> Result<Option<Value>, RuntimeError> {
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.is_admin && auth_context.teams.is_none();
    let row = if is_unrestricted_admin {
        client
            .query_opt(
                "SELECT p.template, p.description \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 AND p.name = $2 AND p.enabled = TRUE",
                &[&server_id, &name],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query_opt(
                "SELECT p.template, p.description \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 \
                   AND p.name = $2 \
                   AND p.enabled = TRUE \
                   AND ( \
                        p.visibility = 'public' \
                        OR ($3::bool AND p.owner_email = $4) \
                        OR (COALESCE(array_length($5::text[], 1), 0) > 0 AND p.team_id = ANY($5::text[]) AND p.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &name, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    let Some(row) = row else {
        return Ok(None);
    };

    Ok(Some(json!({
        "description": row.get::<_, Option<String>>("description"),
        "messages": [{
            "role": "user",
            "content": {
                "type": "text",
                "text": row.get::<_, String>("template"),
            }
        }],
    })))
}

fn resource_row_to_value(row: &tokio_postgres::Row) -> Value {
    let mut resource = serde_json::Map::new();
    resource.insert("uri".to_string(), Value::String(row.get("uri")));
    resource.insert("name".to_string(), Value::String(row.get("name")));
    if let Some(description) = row.get::<_, Option<String>>("description") {
        resource.insert("description".to_string(), Value::String(description));
    }
    if let Some(mime_type) = row.get::<_, Option<String>>("mime_type") {
        resource.insert("mimeType".to_string(), Value::String(mime_type));
    }
    if let Some(size) = row.get::<_, Option<i32>>("size") {
        resource.insert("size".to_string(), Value::Number(size.into()));
    }
    Value::Object(resource)
}

fn resource_template_row_to_value(row: &tokio_postgres::Row) -> Value {
    let mut resource_template = serde_json::Map::new();
    resource_template.insert("id".to_string(), Value::String(row.get("id")));
    resource_template.insert(
        "uriTemplate".to_string(),
        Value::String(row.get("uri_template")),
    );
    resource_template.insert("name".to_string(), Value::String(row.get("name")));
    if let Some(description) = row.get::<_, Option<String>>("description") {
        resource_template.insert("description".to_string(), Value::String(description));
    }
    if let Some(mime_type) = row.get::<_, Option<String>>("mime_type") {
        resource_template.insert("mimeType".to_string(), Value::String(mime_type));
    }
    Value::Object(resource_template)
}

fn prompt_row_to_value(row: &tokio_postgres::Row) -> Value {
    let mut prompt = serde_json::Map::new();
    prompt.insert("name".to_string(), Value::String(row.get("name")));
    if let Some(description) = row.get::<_, Option<String>>("description") {
        prompt.insert("description".to_string(), Value::String(description));
    }
    prompt.insert(
        "arguments".to_string(),
        Value::Array(prompt_arguments_from_schema(
            row.get::<_, Option<Value>>("argument_schema"),
        )),
    );
    Value::Object(prompt)
}

fn prompt_arguments_from_schema(argument_schema: Option<Value>) -> Vec<Value> {
    let Some(argument_schema) = argument_schema else {
        return Vec::new();
    };
    let Some(schema_object) = argument_schema.as_object() else {
        return Vec::new();
    };
    let properties = schema_object
        .get("properties")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let required = schema_object
        .get("required")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();

    let required_names: std::collections::HashSet<String> = required
        .into_iter()
        .filter_map(|value| value.as_str().map(str::to_string))
        .collect();

    let mut arguments = Vec::new();
    for (name, property) in properties {
        let description = property
            .as_object()
            .and_then(|object| object.get("description"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        arguments.push(json!({
            "name": name,
            "description": description,
            "required": required_names.contains(&name),
        }));
    }
    arguments
}

async fn authorize_server_method_via_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request_id: Option<Value>,
    url: &str,
    method_label: &str,
) -> Result<(), Response> {
    let backend_response = state
        .client
        .post(url)
        .headers(build_forwarded_headers(incoming_headers))
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP {method_label} authz failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": format!("Backend MCP {method_label} authz failed"),
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
            error!("backend MCP {method_label} authz response decode failed: {err}");
            return Err(json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": format!("Backend MCP {method_label} authz decode failed"),
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
    let mut request = state.client.request(method, target_url).headers(
        build_forwarded_headers_with_session_validation(incoming_headers, session_validated),
    );
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
        if let Ok(payload) = serde_json::from_slice::<Value>(&response_body)
            && payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string()))
            && payload.get("error").is_some()
        {
            return Err(ResolveToolsCallError::JsonRpcError { payload, headers });
        }
        return Err(ResolveToolsCallError::Fallback(format!(
            "resolve returned status {status}"
        )));
    }

    serde_json::from_slice::<ResolvedMcpToolCallPlan>(&response_body).map_err(|err| {
        if let Ok(payload) = serde_json::from_slice::<Value>(&response_body)
            && payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string()))
            && payload.get("error").is_some()
        {
            return ResolveToolsCallError::JsonRpcError { payload, headers };
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
        if let Some(cached) = cached_plans.get_mut(&cache_key)
            && cached.cached_at.elapsed() < state.tools_call_plan_ttl()
        {
            cached.cached_at = Instant::now();
            return Ok(cached.plan.clone());
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
    if let Some(session_id) = downstream_session_id
        && let Ok(value) = HeaderValue::from_str(&session_id)
    {
        response
            .headers_mut()
            .insert(HeaderName::from_static("mcp-session-id"), value);
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
    if let Some(session_id) = downstream_session_id
        && let Ok(value) = HeaderValue::from_str(&session_id)
    {
        response
            .headers_mut()
            .insert(HeaderName::from_static("mcp-session-id"), value);
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
    if let Some(existing) = sessions.get_mut(&session_key)
        && existing.last_used.elapsed() < state.upstream_session_ttl()
    {
        existing.last_used = Instant::now();
        return Ok(existing.session_id.clone());
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

#[allow(clippy::too_many_arguments)]
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

    for (name, value) in incoming_headers {
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

    if headers.get("mcp-session-id").is_none()
        && let Some(session_id) = session_hint
    {
        builder = builder.header("mcp-session-id", session_id);
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
        if let Some(value) = headers.get(header_name)
            && let Ok(name) = HeaderName::from_bytes(header_name.as_bytes())
        {
            response_headers.insert(name, value.clone());
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
            | "x-real-ip"
            | "x-forwarded-for"
            | "x-forwarded-proto"
            | "x-forwarded-host"
            | "forwarded"
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

#[cfg(test)]
mod unit_tests {
    use super::{
        AffinityForwardResponse, AppState, Bytes, EventStoreReplayRequest, EventStoreStoreRequest,
        InternalAuthContext, JsonRpcRequest, RuntimeConfig, RuntimeError, RuntimeSessionRecord,
        accepts_sse, active_runtime_session_count, affinity_forward_error_response,
        auth_binding_fingerprint, authenticate_public_request_if_needed, batch_rejected_response,
        can_reuse_session_auth, can_use_direct_prompts_get, can_use_direct_resources_read,
        decode_request, derive_backend_authenticate_url, derive_backend_completion_complete_url,
        derive_backend_initialize_url, derive_backend_logging_set_level_url,
        derive_backend_notifications_cancelled_url, derive_backend_notifications_initialized_url,
        derive_backend_notifications_message_url, derive_backend_prompts_get_authz_url,
        derive_backend_prompts_get_url, derive_backend_prompts_list_authz_url,
        derive_backend_prompts_list_url, derive_backend_resource_templates_list_authz_url,
        derive_backend_resource_templates_list_url, derive_backend_resources_list_authz_url,
        derive_backend_resources_list_url, derive_backend_resources_read_authz_url,
        derive_backend_resources_read_url, derive_backend_resources_subscribe_url,
        derive_backend_resources_unsubscribe_url, derive_backend_roots_list_url,
        derive_backend_sampling_create_message_url, derive_backend_session_delete_url,
        derive_backend_tools_call_resolve_url, derive_backend_tools_call_url,
        derive_backend_tools_list_authz_url, derive_backend_tools_list_url,
        derive_backend_transport_url, encode_internal_auth_context_header, event_store_key_prefix,
        extract_client_capabilities, forward_initialize_to_backend, forward_to_backend,
        get_runtime_session, handle_initialize_with_session_core, has_server_scope, hex_decode,
        hex_encode, inject_server_id_header, inject_session_header, invalid_request_response,
        is_affinity_forwarded_request, maybe_bind_session_auth_context,
        maybe_upsert_runtime_session_from_transport_response, parse_error_response, pool_owner_key,
        public_client_ip, query_param, remove_runtime_session, replay_events_endpoint,
        requested_initialize_session_id, requested_protocol_version,
        response_from_affinity_forward_response, run, runtime_session_allows_access,
        runtime_session_id_from_request, runtime_session_key, serve_http, serve_uds,
        store_event_endpoint, transport_delete_server_scoped, transport_get_server_scoped,
        upsert_runtime_session, validate_initialize_params, validate_protocol_version,
        validate_runtime_session_request,
    };
    use axum::{
        Json, Router,
        extract::{Path as AxumPath, State},
        http::{HeaderMap, HeaderName, HeaderValue, StatusCode, Uri},
        routing::{get, post},
    };
    use serde_json::{Value, json};
    use std::{
        net::{SocketAddr, TcpListener},
        path::PathBuf,
        sync::{Arc, Mutex},
        time::Duration,
    };
    use tokio::time::{Instant, sleep};
    use uuid::Uuid;

    fn free_tcp_addr() -> String {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
        let addr = listener.local_addr().expect("local addr");
        drop(listener);
        addr.to_string()
    }

    async fn spawn_router(router: Router) -> String {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind test listener");
        let addr = listener.local_addr().expect("local addr");
        tokio::spawn(async move {
            axum::serve(listener, router)
                .await
                .expect("serve test router");
        });
        format!("http://{addr}")
    }

    fn test_config() -> RuntimeConfig {
        RuntimeConfig {
            backend_rpc_url: "http://127.0.0.1:4444/rpc".to_string(),
            listen_http: free_tcp_addr(),
            listen_uds: None,
            public_listen_http: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: Vec::new(),
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions:
                "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration."
                    .to_string(),
            request_timeout_ms: 30_000,
            client_connect_timeout_ms: 5_000,
            client_pool_idle_timeout_seconds: 90,
            client_pool_max_idle_per_host: 1024,
            client_tcp_keepalive_seconds: 30,
            tools_call_plan_ttl_seconds: 30,
            upstream_session_ttl_seconds: 300,
            use_rmcp_upstream_client: false,
            session_core_enabled: true,
            event_store_enabled: true,
            resume_core_enabled: true,
            live_stream_core_enabled: true,
            affinity_core_enabled: true,
            session_auth_reuse_enabled: true,
            session_auth_reuse_ttl_seconds: 45,
            session_ttl_seconds: 3_600,
            event_store_max_events_per_stream: 123,
            event_store_ttl_seconds: 4_200,
            event_store_poll_interval_ms: 333,
            cache_prefix: "mcpgw:test:".to_string(),
            database_url: None,
            redis_url: None,
            db_pool_max_size: 7,
            log_filter: "error".to_string(),
            exit_after_startup_ms: None,
        }
    }

    #[tokio::test]
    async fn app_state_new_exposes_derived_urls_and_runtime_flags() {
        let config = test_config();
        let state = AppState::new(&config).expect("state");

        assert_eq!(state.backend_rpc_url(), "http://127.0.0.1:4444/rpc");
        assert_eq!(
            state.backend_authenticate_url(),
            "http://127.0.0.1:4444/_internal/mcp/authenticate"
        );
        assert_eq!(
            state.backend_initialize_url(),
            "http://127.0.0.1:4444/_internal/mcp/initialize"
        );
        assert_eq!(
            state.backend_notifications_initialized_url(),
            "http://127.0.0.1:4444/_internal/mcp/notifications/initialized"
        );
        assert_eq!(
            state.backend_notifications_message_url(),
            "http://127.0.0.1:4444/_internal/mcp/notifications/message"
        );
        assert_eq!(
            state.backend_notifications_cancelled_url(),
            "http://127.0.0.1:4444/_internal/mcp/notifications/cancelled"
        );
        assert_eq!(
            state.backend_transport_url(),
            "http://127.0.0.1:4444/_internal/mcp/transport"
        );
        assert_eq!(
            state.backend_tools_list_url(),
            "http://127.0.0.1:4444/_internal/mcp/tools/list"
        );
        assert_eq!(
            state.backend_resources_list_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/list"
        );
        assert_eq!(
            state.backend_resources_read_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/read"
        );
        assert_eq!(
            state.backend_resources_subscribe_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/subscribe"
        );
        assert_eq!(
            state.backend_resources_unsubscribe_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/unsubscribe"
        );
        assert_eq!(
            state.backend_resource_templates_list_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/templates/list"
        );
        assert_eq!(
            state.backend_prompts_list_url(),
            "http://127.0.0.1:4444/_internal/mcp/prompts/list"
        );
        assert_eq!(
            state.backend_prompts_get_url(),
            "http://127.0.0.1:4444/_internal/mcp/prompts/get"
        );
        assert_eq!(
            state.backend_roots_list_url(),
            "http://127.0.0.1:4444/_internal/mcp/roots/list"
        );
        assert_eq!(
            state.backend_completion_complete_url(),
            "http://127.0.0.1:4444/_internal/mcp/completion/complete"
        );
        assert_eq!(
            state.backend_sampling_create_message_url(),
            "http://127.0.0.1:4444/_internal/mcp/sampling/createMessage"
        );
        assert_eq!(
            state.backend_logging_set_level_url(),
            "http://127.0.0.1:4444/_internal/mcp/logging/setLevel"
        );
        assert_eq!(
            state.backend_tools_list_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/tools/list/authz"
        );
        assert_eq!(
            state.backend_resources_list_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/list/authz"
        );
        assert_eq!(
            state.backend_resources_read_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/read/authz"
        );
        assert_eq!(
            state.backend_resource_templates_list_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/resources/templates/list/authz"
        );
        assert_eq!(
            state.backend_prompts_list_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/prompts/list/authz"
        );
        assert_eq!(
            state.backend_prompts_get_authz_url(),
            "http://127.0.0.1:4444/_internal/mcp/prompts/get/authz"
        );
        assert_eq!(
            state.backend_tools_call_url(),
            "http://127.0.0.1:4444/_internal/mcp/tools/call"
        );
        assert_eq!(
            state.backend_tools_call_resolve_url(),
            "http://127.0.0.1:4444/_internal/mcp/tools/call/resolve"
        );
        assert_eq!(state.protocol_version(), "2025-11-25");
        assert_eq!(state.server_name(), "ContextForge");
        assert_eq!(state.server_version(), "0.1.0");
        assert_eq!(
            state.instructions(),
            "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration."
        );
        assert!(
            state
                .supported_protocol_versions()
                .iter()
                .any(|v| v == "2025-03-26")
        );
        assert!(state.session_core_enabled());
        assert!(state.event_store_enabled());
        assert!(state.resume_core_enabled());
        assert!(state.live_stream_core_enabled());
        assert!(state.affinity_core_enabled());
        assert!(state.session_auth_reuse_enabled());
        assert!(state.db_pool().is_none());
        assert_eq!(state.cache_prefix(), "mcpgw:test:");
        assert_eq!(state.event_store_max_events_per_stream(), 123);
        assert_eq!(state.event_store_ttl(), Duration::from_secs(4_200));
        assert_eq!(
            state.event_store_poll_interval(),
            Duration::from_millis(333)
        );
        assert_eq!(state.tools_call_plan_ttl(), Duration::from_secs(30));
        assert_eq!(state.upstream_session_ttl(), Duration::from_secs(300));
        assert_eq!(state.session_ttl(), Duration::from_secs(3_600));
        assert_eq!(state.session_auth_reuse_ttl(), Duration::from_secs(45));
        assert!(!state.public_ingress_enabled());
        assert!(state.runtime_sessions().lock().await.is_empty());
        assert!(state.upstream_tool_sessions().lock().await.is_empty());
        assert!(state.resolved_tool_call_plans().lock().await.is_empty());
        #[cfg(feature = "rmcp-upstream-client")]
        {
            assert!(!state.use_rmcp_upstream_client());
            assert!(state.rmcp_upstream_clients().lock().await.is_empty());
        }
    }

    #[test]
    fn app_state_new_accepts_sqlite_but_disables_direct_db_pool() {
        let mut config = test_config();
        config.database_url = Some("sqlite:///tmp/runtime.db".to_string());

        let state = AppState::new(&config).expect("state");

        assert!(state.db_pool().is_none());
    }

    #[test]
    fn app_state_new_rejects_invalid_database_url() {
        let mut config = test_config();
        config.database_url =
            Some("postgresql+psycopg://user:pass@127.0.0.1:notaport/db".to_string());

        let Err(error) = AppState::new(&config) else {
            panic!("invalid db url should fail");
        };

        match error {
            RuntimeError::Config(message) => {
                assert!(message.contains("invalid MCP_RUST_DATABASE_URL"));
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn app_state_new_rejects_invalid_redis_url() {
        let mut config = test_config();
        config.redis_url = Some("not a redis url".to_string());

        let Err(error) = AppState::new(&config) else {
            panic!("invalid redis url should fail");
        };

        match error {
            RuntimeError::Config(message) => {
                assert!(message.contains("invalid MCP_RUST_REDIS_URL"));
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn backend_url_derivation_helpers_cover_all_supported_rpc_suffixes() {
        type Deriver = fn(&str) -> String;

        let derivations: [(&str, Deriver); 21] = [
            ("_internal/mcp/tools/list", derive_backend_tools_list_url),
            (
                "_internal/mcp/resources/list",
                derive_backend_resources_list_url,
            ),
            (
                "_internal/mcp/resources/read",
                derive_backend_resources_read_url,
            ),
            (
                "_internal/mcp/resources/subscribe",
                derive_backend_resources_subscribe_url,
            ),
            (
                "_internal/mcp/resources/unsubscribe",
                derive_backend_resources_unsubscribe_url,
            ),
            (
                "_internal/mcp/resources/templates/list",
                derive_backend_resource_templates_list_url,
            ),
            (
                "_internal/mcp/prompts/list",
                derive_backend_prompts_list_url,
            ),
            ("_internal/mcp/prompts/get", derive_backend_prompts_get_url),
            ("_internal/mcp/roots/list", derive_backend_roots_list_url),
            (
                "_internal/mcp/completion/complete",
                derive_backend_completion_complete_url,
            ),
            (
                "_internal/mcp/sampling/createMessage",
                derive_backend_sampling_create_message_url,
            ),
            (
                "_internal/mcp/logging/setLevel",
                derive_backend_logging_set_level_url,
            ),
            ("_internal/mcp/initialize", derive_backend_initialize_url),
            ("_internal/mcp/transport", derive_backend_transport_url),
            ("_internal/mcp/session", derive_backend_session_delete_url),
            (
                "_internal/mcp/notifications/initialized",
                derive_backend_notifications_initialized_url,
            ),
            (
                "_internal/mcp/notifications/message",
                derive_backend_notifications_message_url,
            ),
            (
                "_internal/mcp/notifications/cancelled",
                derive_backend_notifications_cancelled_url,
            ),
            (
                "_internal/mcp/tools/list/authz",
                derive_backend_tools_list_authz_url,
            ),
            (
                "_internal/mcp/resources/list/authz",
                derive_backend_resources_list_authz_url,
            ),
            (
                "_internal/mcp/resources/read/authz",
                derive_backend_resources_read_authz_url,
            ),
        ];

        let inputs = [
            (
                "http://gateway.example/_internal/mcp/rpc",
                "http://gateway.example",
            ),
            (
                "http://gateway.example/_internal/mcp/rpc/",
                "http://gateway.example",
            ),
            ("http://gateway.example/rpc", "http://gateway.example"),
            ("http://gateway.example/rpc/", "http://gateway.example"),
            (
                "http://gateway.example/custom/base/",
                "http://gateway.example/custom/base",
            ),
        ];

        for (suffix, derive) in derivations {
            for (input, prefix) in inputs {
                assert_eq!(derive(input), format!("{prefix}/{suffix}"), "input {input}");
            }
        }

        let authz_derivations: [(&str, Deriver); 6] = [
            (
                "_internal/mcp/resources/templates/list/authz",
                derive_backend_resource_templates_list_authz_url,
            ),
            (
                "_internal/mcp/prompts/list/authz",
                derive_backend_prompts_list_authz_url,
            ),
            (
                "_internal/mcp/prompts/get/authz",
                derive_backend_prompts_get_authz_url,
            ),
            ("_internal/mcp/tools/call", derive_backend_tools_call_url),
            (
                "_internal/mcp/tools/call/resolve",
                derive_backend_tools_call_resolve_url,
            ),
            (
                "_internal/mcp/authenticate",
                derive_backend_authenticate_url,
            ),
        ];

        for (suffix, derive) in authz_derivations {
            for (input, prefix) in inputs {
                assert_eq!(derive(input), format!("{prefix}/{suffix}"), "input {input}");
            }
        }
    }

    #[tokio::test]
    async fn run_http_listener_can_exit_after_startup_delay() {
        let mut config = test_config();
        config.exit_after_startup_ms = Some(5);

        run(config).await.expect("run http listener");
    }

    #[tokio::test]
    async fn run_dual_http_listeners_can_exit_after_startup_delay() {
        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.exit_after_startup_ms = Some(5);

        run(config).await.expect("run dual http listeners");
    }

    #[tokio::test]
    async fn run_uds_listener_can_exit_after_startup_delay() {
        let mut config = test_config();
        config.listen_uds = Some(PathBuf::from(format!(
            "/tmp/contextforge-mcp-runtime-{}.sock",
            Uuid::new_v4()
        )));
        config.exit_after_startup_ms = Some(5);

        run(config.clone()).await.expect("run uds listener");

        if let Some(path) = config.listen_uds {
            let _ = std::fs::remove_file(path);
        }
    }

    #[tokio::test]
    async fn run_uds_and_public_http_can_exit_after_startup_delay() {
        let mut config = test_config();
        config.listen_uds = Some(PathBuf::from(format!(
            "/tmp/contextforge-mcp-runtime-{}.sock",
            Uuid::new_v4()
        )));
        config.public_listen_http = Some(free_tcp_addr());
        config.exit_after_startup_ms = Some(5);

        run(config.clone())
            .await
            .expect("run uds and public http listeners");

        if let Some(path) = config.listen_uds {
            let _ = std::fs::remove_file(path);
        }
    }

    #[test]
    fn direct_server_scope_helper_predicates_cover_valid_and_invalid_shapes() {
        let mut headers = HeaderMap::new();
        assert!(!has_server_scope(&headers));
        headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_static("server-1"),
        );
        assert!(has_server_scope(&headers));

        assert!(!can_use_direct_resources_read(&Value::Null));
        assert!(!can_use_direct_resources_read(&json!({"uri": ""})));
        assert!(!can_use_direct_resources_read(
            &json!({"uri": "resource://one", "requestId": "123"})
        ));
        assert!(!can_use_direct_resources_read(
            &json!({"uri": "resource://one", "_meta": {"trace": true}})
        ));
        assert!(can_use_direct_resources_read(
            &json!({"uri": "resource://one"})
        ));

        assert!(!can_use_direct_prompts_get(&Value::Null));
        assert!(!can_use_direct_prompts_get(&json!({"name": ""})));
        assert!(!can_use_direct_prompts_get(
            &json!({"name": "prompt-1", "arguments": {"who": "world"}})
        ));
        assert!(!can_use_direct_prompts_get(
            &json!({"name": "prompt-1", "_meta": {"trace": true}})
        ));
        assert!(can_use_direct_prompts_get(&json!({"name": "prompt-1"})));
        assert!(can_use_direct_prompts_get(
            &json!({"name": "prompt-1", "arguments": {}})
        ));
        assert!(can_use_direct_prompts_get(
            &json!({"name": "prompt-1", "arguments": null})
        ));
    }

    #[tokio::test]
    async fn authenticate_public_request_returns_early_for_python_ingress_and_existing_auth_context()
     {
        let state = AppState::new(&test_config()).expect("state");
        let uri: Uri = "/mcp?session_id=abc".parse().expect("uri");
        let (headers, path) = authenticate_public_request_if_needed(
            &state,
            "GET",
            HeaderMap::new(),
            &uri,
            Some("server-1"),
        )
        .await
        .expect("python ingress path");
        assert_eq!(path, "/servers/server-1/mcp");
        assert_eq!(
            headers
                .get("x-contextforge-server-id")
                .and_then(|value| value.to_str().ok()),
            Some("server-1")
        );

        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.backend_rpc_url = "http://127.0.0.1:1/rpc".to_string();
        let state = AppState::new(&config).expect("state");
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            HeaderValue::from_static("already-present"),
        );
        let (headers, path) = authenticate_public_request_if_needed(
            &state,
            "GET",
            headers,
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await
        .expect("existing auth context bypasses backend auth");
        assert_eq!(path, "/mcp");
        assert_eq!(
            headers
                .get("x-contextforge-auth-context")
                .and_then(|value| value.to_str().ok()),
            Some("already-present")
        );
    }

    #[tokio::test]
    async fn authenticate_public_request_surfaces_backend_transport_and_decode_failures() {
        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.backend_rpc_url = "http://127.0.0.1:1/rpc".to_string();
        let state = AppState::new(&config).expect("state");

        let response = authenticate_public_request_if_needed(
            &state,
            "GET",
            HeaderMap::new(),
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await
        .expect_err("unreachable backend should fail");
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

        let backend = Router::new().route(
            "/_internal/mcp/authenticate",
            post(|| async move { (StatusCode::OK, "not-json") }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        let response = authenticate_public_request_if_needed(
            &state,
            "GET",
            HeaderMap::new(),
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await
        .expect_err("invalid backend payload should fail");
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn event_store_endpoints_report_disabled_and_unavailable_states() {
        let mut disabled_config = test_config();
        disabled_config.event_store_enabled = false;
        let state = AppState::new(&disabled_config).expect("state");

        let disabled_store = store_event_endpoint(
            State(state.clone()),
            Json(EventStoreStoreRequest {
                stream_id: "stream-1".to_string(),
                message: Some(json!({"hello": "world"})),
                key_prefix: None,
                max_events_per_stream: None,
                ttl_seconds: None,
            }),
        )
        .await;
        assert_eq!(disabled_store.status(), StatusCode::NOT_IMPLEMENTED);

        let disabled_replay = replay_events_endpoint(
            State(state),
            Json(EventStoreReplayRequest {
                last_event_id: "event-1".to_string(),
                key_prefix: None,
            }),
        )
        .await;
        assert_eq!(disabled_replay.status(), StatusCode::NOT_IMPLEMENTED);

        let mut config = test_config();
        config.event_store_enabled = true;
        let state = AppState::new(&config).expect("state");

        let unavailable_store = store_event_endpoint(
            State(state.clone()),
            Json(EventStoreStoreRequest {
                stream_id: "stream-1".to_string(),
                message: Some(json!({"hello": "world"})),
                key_prefix: None,
                max_events_per_stream: None,
                ttl_seconds: None,
            }),
        )
        .await;
        assert_eq!(unavailable_store.status(), StatusCode::SERVICE_UNAVAILABLE);

        let unavailable_replay = replay_events_endpoint(
            State(state),
            Json(EventStoreReplayRequest {
                last_event_id: "event-1".to_string(),
                key_prefix: None,
            }),
        )
        .await;
        assert_eq!(unavailable_replay.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn server_scoped_transport_wrappers_inject_server_header() {
        let calls = Arc::new(Mutex::new(Vec::<(String, Option<String>)>::new()));
        let backend = {
            let get_calls = calls.clone();
            let delete_calls = calls.clone();
            Router::new().route(
                "/_internal/mcp/transport",
                get(move |headers: HeaderMap| {
                    let calls = get_calls.clone();
                    async move {
                        calls.lock().expect("lock").push((
                            "GET".to_string(),
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        (
                            StatusCode::OK,
                            [(
                                "content-type",
                                HeaderValue::from_static("text/event-stream"),
                            )],
                            "data: ok\n\n",
                        )
                    }
                })
                .delete(move |headers: HeaderMap| {
                    let calls = delete_calls.clone();
                    async move {
                        calls.lock().expect("lock").push((
                            "DELETE".to_string(),
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        StatusCode::NO_CONTENT
                    }
                }),
            )
        };
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/_internal/mcp/rpc");
        config.session_core_enabled = false;
        config.live_stream_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        let get_response = transport_get_server_scoped(
            State(state.clone()),
            AxumPath("server-xyz".to_string()),
            HeaderMap::new(),
            "/servers/server-xyz/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(get_response.status(), StatusCode::OK);

        let delete_response = transport_delete_server_scoped(
            State(state),
            AxumPath("server-xyz".to_string()),
            HeaderMap::new(),
            "/servers/server-xyz/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(delete_response.status(), StatusCode::NO_CONTENT);

        let calls = calls.lock().expect("lock");
        assert_eq!(
            *calls,
            vec![
                ("GET".to_string(), Some("server-xyz".to_string())),
                ("DELETE".to_string(), Some("server-xyz".to_string())),
            ]
        );
    }

    #[tokio::test]
    async fn public_transport_wrappers_return_backend_auth_failures() {
        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.backend_rpc_url = "http://127.0.0.1:1/rpc".to_string();
        let state = AppState::new(&config).expect("state");

        let get_response = super::transport_get(
            State(state.clone()),
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(get_response.status(), StatusCode::BAD_GATEWAY);

        let delete_response = super::transport_delete(
            State(state.clone()),
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(delete_response.status(), StatusCode::BAD_GATEWAY);

        let post_response = super::rpc(
            State(state),
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
            Bytes::from(
                serde_json::to_vec(&json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "ping",
                    "params": {}
                }))
                .expect("request body"),
            ),
        )
        .await;
        assert_eq!(post_response.status(), StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn serve_http_without_shutdown_can_be_aborted_after_serving_requests() {
        let addr: SocketAddr = free_tcp_addr().parse().expect("socket addr");
        let app = Router::new().route("/health", get(|| async { "ok" }));
        let handle = tokio::spawn(serve_http(app, addr, None));
        let client = reqwest::Client::new();
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut seen_ok = false;
        while Instant::now() < deadline {
            if let Ok(response) = client.get(format!("http://{addr}/health")).send().await
                && response.status() == StatusCode::OK
            {
                seen_ok = true;
                break;
            }
            sleep(Duration::from_millis(10)).await;
        }
        assert!(seen_ok, "serve_http should accept requests before abort");
        handle.abort();
        let _ = handle.await;
    }

    #[tokio::test]
    async fn serve_uds_without_shutdown_removes_existing_socket_file_and_can_be_aborted() {
        let path = PathBuf::from(format!(
            "/tmp/contextforge-mcp-runtime-existing-{}.sock",
            Uuid::new_v4()
        ));
        std::fs::write(&path, b"placeholder").expect("seed placeholder socket file");
        let app = Router::new().route("/health", get(|| async { "ok" }));
        let handle = tokio::spawn(serve_uds(app, path.clone(), None));

        let deadline = Instant::now() + Duration::from_secs(2);
        let mut rebound = false;
        while Instant::now() < deadline {
            if path.exists() {
                rebound = true;
                break;
            }
            sleep(Duration::from_millis(10)).await;
        }
        assert!(rebound, "serve_uds should replace the seeded socket path");

        handle.abort();
        let _ = handle.await;
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn decode_request_and_validation_helpers_cover_error_paths() {
        let state = AppState::new(&test_config()).expect("state");
        let invalid_json = decode_request(br#"{"jsonrpc":"2.0""#).expect_err("parse error");
        assert_eq!(invalid_json.status(), StatusCode::BAD_REQUEST);

        let batch = decode_request(br#"[{"jsonrpc":"2.0","id":1,"method":"ping"}]"#)
            .expect_err("batch should fail");
        assert_eq!(batch.status(), StatusCode::BAD_REQUEST);

        let invalid_version = decode_request(br#"{"jsonrpc":"1.0","id":1,"method":"ping"}"#)
            .expect_err("invalid version should fail");
        assert_eq!(invalid_version.status(), StatusCode::BAD_REQUEST);

        let missing_method =
            decode_request(br#"{"jsonrpc":"2.0","id":1}"#).expect_err("missing method should fail");
        assert_eq!(missing_method.status(), StatusCode::BAD_REQUEST);

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("mcp-protocol-version"),
            HeaderValue::from_static("2099-01-01"),
        );
        let unsupported_protocol =
            validate_protocol_version(&state, &headers).expect_err("unsupported protocol");
        assert_eq!(unsupported_protocol.status(), StatusCode::BAD_REQUEST);

        let invalid_params =
            validate_initialize_params(&state, &json!({"protocolVersion": 5}), Some(&json!(7)))
                .expect_err("invalid params");
        assert_eq!(invalid_params.status(), StatusCode::OK);

        let missing_protocol =
            validate_initialize_params(&state, &json!({"capabilities": {}}), Some(&json!(8)))
                .expect_err("missing protocol");
        assert_eq!(missing_protocol.status(), StatusCode::OK);

        let unsupported_initialize = validate_initialize_params(
            &state,
            &json!({"protocolVersion": "2099-01-01", "capabilities": {}}),
            Some(&json!(9)),
        )
        .expect_err("unsupported initialize protocol");
        assert_eq!(unsupported_initialize.status(), StatusCode::OK);

        assert_eq!(parse_error_response().status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            invalid_request_response(&json!(1)).status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(batch_rejected_response().status(), StatusCode::BAD_REQUEST);
    }

    #[test]
    fn client_ip_and_session_auth_reuse_helpers_cover_edge_cases() {
        let mut headers = HeaderMap::new();
        assert_eq!(public_client_ip(&headers), None);

        headers.insert(
            HeaderName::from_static("x-forwarded-for"),
            HeaderValue::from_static(" 198.51.100.10 , 203.0.113.5 "),
        );
        assert_eq!(
            public_client_ip(&headers),
            Some("198.51.100.10".to_string())
        );

        headers.insert(
            HeaderName::from_static("x-real-ip"),
            HeaderValue::from_static("203.0.113.9"),
        );
        assert_eq!(public_client_ip(&headers), Some("203.0.113.9".to_string()));
        assert_eq!(auth_binding_fingerprint(&HeaderMap::new()), None);

        let mut auth_headers = HeaderMap::new();
        auth_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        let fingerprint = auth_binding_fingerprint(&auth_headers).expect("fingerprint");

        let mut config = test_config();
        config.session_auth_reuse_enabled = true;
        let state = AppState::new(&config).expect("state");
        let now = super::unix_epoch_millis();
        let record = RuntimeSessionRecord {
            owner_email: Some("owner@example.com".to_string()),
            server_id: Some("server-1".to_string()),
            protocol_version: None,
            client_capabilities: None,
            encoded_auth_context: Some("encoded-context".to_string()),
            auth_binding_fingerprint: Some(fingerprint.clone()),
            auth_context_expires_at_epoch_ms: Some(now + 60_000),
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
        };

        assert_eq!(
            can_reuse_session_auth(&state, &record, &auth_headers, Some("server-1")),
            Some("encoded-context".to_string())
        );
        assert_eq!(
            can_reuse_session_auth(&state, &record, &auth_headers, Some("server-2")),
            None
        );

        let mut mismatched_headers = HeaderMap::new();
        mismatched_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer beta"),
        );
        assert_eq!(
            can_reuse_session_auth(&state, &record, &mismatched_headers, Some("server-1")),
            None
        );

        let expired = RuntimeSessionRecord {
            auth_context_expires_at_epoch_ms: Some(now.saturating_sub(1)),
            ..record.clone()
        };
        assert_eq!(
            can_reuse_session_auth(&state, &expired, &auth_headers, Some("server-1")),
            None
        );

        let mut disabled_config = test_config();
        disabled_config.session_auth_reuse_enabled = false;
        let disabled_state = AppState::new(&disabled_config).expect("state");
        assert_eq!(
            can_reuse_session_auth(&disabled_state, &record, &auth_headers, Some("server-1")),
            None
        );
    }

    #[tokio::test]
    async fn authenticate_public_request_handles_invalid_reused_auth_header_and_backend_denials() {
        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.session_core_enabled = true;
        config.session_auth_reuse_enabled = true;
        let state = AppState::new(&config).expect("state");

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("session-1"),
        );
        let fingerprint = auth_binding_fingerprint(&headers).expect("fingerprint");
        state.runtime_sessions().lock().await.insert(
            "session-1".to_string(),
            RuntimeSessionRecord {
                owner_email: Some("owner@example.com".to_string()),
                server_id: None,
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: Some("bad\nheader".to_string()),
                auth_binding_fingerprint: Some(fingerprint),
                auth_context_expires_at_epoch_ms: Some(super::unix_epoch_millis() + 60_000),
                created_at: std::time::Instant::now(),
                last_used: std::time::Instant::now(),
            },
        );

        let response = authenticate_public_request_if_needed(
            &state,
            "GET",
            headers,
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await
        .expect_err("invalid stored auth header should fail");
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

        let backend = Router::new().route(
            "/_internal/mcp/authenticate",
            post(|| async move { (StatusCode::UNAUTHORIZED, Json(json!({"detail": "denied"}))) }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");
        let response = authenticate_public_request_if_needed(
            &state,
            "GET",
            HeaderMap::new(),
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await
        .expect_err("backend denial should be forwarded");
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn runtime_session_request_helpers_cover_headers_params_and_injection() {
        let request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "initialize".to_string(),
            params: json!({
                "sessionId": "param-session-id",
                "protocolVersion": "2025-03-26",
                "capabilities": {"roots": {"listChanged": true}},
            }),
            id: Some(json!(1)),
        };
        let uri = "/mcp?session_id=query-session-id"
            .parse::<Uri>()
            .expect("uri");
        let empty_headers = HeaderMap::new();

        assert_eq!(
            runtime_session_id_from_request(&empty_headers, &uri),
            Some("query-session-id".to_string())
        );
        assert_eq!(
            requested_initialize_session_id(
                &empty_headers,
                &"/mcp".parse::<Uri>().expect("uri"),
                &request
            ),
            Some("param-session-id".to_string())
        );
        assert_eq!(
            requested_protocol_version(&request),
            Some("2025-03-26".to_string())
        );
        assert_eq!(
            extract_client_capabilities(&request),
            Some(json!({"roots": {"listChanged": true}}))
        );
        assert_eq!(
            query_param(&uri, "session_id"),
            Some("query-session-id".to_string())
        );
        assert_eq!(query_param(&uri, "missing"), None);

        let mut headers = HeaderMap::new();
        inject_session_header(&mut headers, "header-session-id");
        inject_server_id_header(&mut headers, "server-123");
        assert_eq!(
            runtime_session_id_from_request(&headers, &uri),
            Some("header-session-id".to_string())
        );
        assert_eq!(
            requested_initialize_session_id(&headers, &uri, &request),
            Some("header-session-id".to_string())
        );
        assert_eq!(
            headers
                .get("x-contextforge-server-id")
                .and_then(|value| value.to_str().ok()),
            Some("server-123")
        );
    }

    #[tokio::test]
    async fn runtime_session_local_cache_helpers_cover_lifecycle_and_keys() {
        let mut config = test_config();
        config.session_ttl_seconds = 1;
        let state = AppState::new(&config).expect("state");
        state.runtime_sessions().lock().await.insert(
            "stale-session".to_string(),
            RuntimeSessionRecord {
                owner_email: Some("stale@example.com".to_string()),
                server_id: None,
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: None,
                auth_binding_fingerprint: None,
                auth_context_expires_at_epoch_ms: None,
                created_at: std::time::Instant::now()
                    .checked_sub(Duration::from_secs(5))
                    .expect("subtract"),
                last_used: std::time::Instant::now()
                    .checked_sub(Duration::from_secs(5))
                    .expect("subtract"),
            },
        );

        assert_eq!(active_runtime_session_count(&state).await, 0);
        assert!(get_runtime_session(&state, "stale-session").await.is_none());

        let record = RuntimeSessionRecord {
            owner_email: Some("owner@example.com".to_string()),
            server_id: Some("server-1".to_string()),
            protocol_version: Some("2025-03-26".to_string()),
            client_capabilities: Some(json!({"roots": {"listChanged": true}})),
            encoded_auth_context: None,
            auth_binding_fingerprint: None,
            auth_context_expires_at_epoch_ms: None,
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
        };
        upsert_runtime_session(&state, "session-1".to_string(), record.clone()).await;
        let fetched = get_runtime_session(&state, "session-1")
            .await
            .expect("session cached");
        assert_eq!(fetched.owner_email, record.owner_email);
        assert_eq!(
            runtime_session_key(&state, "session-1"),
            "mcpgw:test:rust:mcp:session:session-1"
        );
        assert_eq!(pool_owner_key("session-1"), "mcpgw:pool_owner:session-1");

        let mut forwarded_headers = HeaderMap::new();
        assert!(!is_affinity_forwarded_request(&forwarded_headers));
        forwarded_headers.insert(
            HeaderName::from_static("x-contextforge-affinity-forwarded"),
            HeaderValue::from_static("rust"),
        );
        assert!(is_affinity_forwarded_request(&forwarded_headers));

        remove_runtime_session(&state, "session-1").await;
        assert!(get_runtime_session(&state, "session-1").await.is_none());
    }

    #[tokio::test]
    async fn session_auth_binding_and_validation_helpers_cover_access_controls() {
        let mut config = test_config();
        config.session_auth_reuse_enabled = true;
        let state = AppState::new(&config).expect("state");

        let auth_context_json = json!({
            "email": "owner@example.com",
            "teams": ["team-1"],
            "is_admin": false,
            "is_authenticated": true
        });
        let auth_context = InternalAuthContext {
            email: Some("owner@example.com".to_string()),
            teams: Some(vec!["team-1".to_string()]),
            is_admin: false,
            is_authenticated: true,
        };

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encode_internal_auth_context_header(&auth_context_json).expect("encode auth context"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_static("server-1"),
        );

        let mut record = RuntimeSessionRecord {
            owner_email: Some("owner@example.com".to_string()),
            server_id: Some("server-1".to_string()),
            protocol_version: None,
            client_capabilities: None,
            encoded_auth_context: None,
            auth_binding_fingerprint: None,
            auth_context_expires_at_epoch_ms: None,
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
        };
        maybe_bind_session_auth_context(&state, &mut record, &headers, Some(&auth_context));
        assert_eq!(
            record.encoded_auth_context,
            Some(
                headers
                    .get("x-contextforge-auth-context")
                    .and_then(|value| value.to_str().ok())
                    .expect("header value")
                    .to_string()
            )
        );
        assert!(record.auth_binding_fingerprint.is_some());
        assert!(
            record.auth_context_expires_at_epoch_ms.expect("ttl is set")
                > super::unix_epoch_millis()
        );
        assert!(runtime_session_allows_access(
            &record,
            Some(&auth_context),
            &headers
        ));

        upsert_runtime_session(&state, "session-validate".to_string(), record.clone()).await;

        let mut validation_headers = headers.clone();
        validation_headers.remove("x-contextforge-server-id");
        let validated = validate_runtime_session_request(
            &state,
            &mut validation_headers,
            &"/mcp?session_id=session-validate"
                .parse::<Uri>()
                .expect("uri"),
        )
        .await
        .expect("validation succeeds");
        assert_eq!(validated, Some("session-validate".to_string()));
        assert_eq!(
            validation_headers
                .get("x-contextforge-server-id")
                .and_then(|value| value.to_str().ok()),
            Some("server-1")
        );

        let mut wrong_server_headers = headers.clone();
        wrong_server_headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_static("server-2"),
        );
        let response = validate_runtime_session_request(
            &state,
            &mut wrong_server_headers,
            &"/mcp?session_id=session-validate"
                .parse::<Uri>()
                .expect("uri"),
        )
        .await
        .expect_err("server mismatch is denied");
        assert_eq!(response.status(), StatusCode::FORBIDDEN);

        let mut wrong_auth_headers = headers.clone();
        wrong_auth_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer beta"),
        );
        let response = validate_runtime_session_request(
            &state,
            &mut wrong_auth_headers,
            &"/mcp?session_id=session-validate"
                .parse::<Uri>()
                .expect("uri"),
        )
        .await
        .expect_err("auth mismatch is denied");
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
    }

    #[test]
    fn affinity_response_and_hex_helpers_cover_edge_cases() {
        assert_eq!(hex_encode(b"Hi"), "4869");
        assert_eq!(hex_decode(b"4869"), Some(b"Hi".to_vec()));
        assert_eq!(hex_decode(b"486"), None);
        assert_eq!(hex_decode(b"GG"), None);

        let response = response_from_affinity_forward_response(
            AffinityForwardResponse {
                status: 200,
                headers: [
                    ("x-custom".to_string(), "present".to_string()),
                    ("bad header".to_string(), "ignored".to_string()),
                ]
                .into_iter()
                .collect(),
                body: hex_encode(br#"{"ok":true}"#),
            },
            Some("session-hint"),
        );
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-runtime")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|value| value.to_str().ok()),
            Some("application/json")
        );
        assert_eq!(
            response
                .headers()
                .get("mcp-session-id")
                .and_then(|value| value.to_str().ok()),
            Some("session-hint")
        );
        assert_eq!(
            response
                .headers()
                .get("x-custom")
                .and_then(|value| value.to_str().ok()),
            Some("present")
        );
    }

    #[tokio::test]
    async fn maybe_upsert_runtime_session_from_transport_response_persists_session_metadata() {
        let state = AppState::new(&test_config()).expect("state");
        let auth_context_json = json!({
            "email": "owner@example.com",
            "teams": ["team-1"],
            "is_authenticated": true
        });

        let mut request_headers = HeaderMap::new();
        request_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        request_headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encode_internal_auth_context_header(&auth_context_json).expect("encode auth context"),
        );
        request_headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_static("server-1"),
        );
        request_headers.insert(
            HeaderName::from_static("mcp-protocol-version"),
            HeaderValue::from_static("2025-03-26"),
        );

        let mut response_headers = reqwest::header::HeaderMap::new();
        response_headers.insert(
            "mcp-session-id",
            reqwest::header::HeaderValue::from_static("response-session"),
        );
        let session_id = maybe_upsert_runtime_session_from_transport_response(
            &state,
            &request_headers,
            Some("request-session"),
            &response_headers,
        )
        .await
        .expect("session id returned");
        assert_eq!(session_id, "response-session");

        let stored = get_runtime_session(&state, "response-session")
            .await
            .expect("stored session");
        assert_eq!(stored.owner_email.as_deref(), Some("owner@example.com"));
        assert_eq!(stored.server_id.as_deref(), Some("server-1"));
        assert_eq!(stored.protocol_version.as_deref(), Some("2025-03-26"));
        assert!(stored.encoded_auth_context.is_some());
        assert!(stored.auth_binding_fingerprint.is_some());

        let mut disabled_config = test_config();
        disabled_config.session_core_enabled = false;
        let disabled_state = AppState::new(&disabled_config).expect("state");
        let passthrough = maybe_upsert_runtime_session_from_transport_response(
            &disabled_state,
            &HeaderMap::new(),
            Some("request-session"),
            &reqwest::header::HeaderMap::new(),
        )
        .await;
        assert_eq!(passthrough, Some("request-session".to_string()));
    }

    #[tokio::test]
    async fn backend_forward_helpers_and_initialize_session_core_cover_error_and_denial_paths() {
        let mut error_config = test_config();
        error_config.backend_rpc_url = "http://127.0.0.1:1/rpc".to_string();
        let error_state = AppState::new(&error_config).expect("state");

        let response =
            forward_to_backend(&error_state, HeaderMap::new(), Bytes::from_static(b"{}")).await;
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

        let response = forward_initialize_to_backend(
            &error_state,
            HeaderMap::new(),
            Bytes::from_static(b"{}"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

        let state = AppState::new(&test_config()).expect("state");
        let auth_context_json = json!({
            "email": "owner@example.com",
            "teams": ["team-1"],
            "is_authenticated": true
        });
        let mut incoming_headers = HeaderMap::new();
        incoming_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer beta"),
        );
        incoming_headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encode_internal_auth_context_header(&auth_context_json).expect("encode auth context"),
        );
        incoming_headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("denied-session"),
        );
        upsert_runtime_session(
            &state,
            "denied-session".to_string(),
            RuntimeSessionRecord {
                owner_email: Some("owner@example.com".to_string()),
                server_id: None,
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: Some("cached".to_string()),
                auth_binding_fingerprint: Some("different-fingerprint".to_string()),
                auth_context_expires_at_epoch_ms: Some(super::unix_epoch_millis() + 60_000),
                created_at: std::time::Instant::now(),
                last_used: std::time::Instant::now(),
            },
        )
        .await;

        let request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "initialize".to_string(),
            params: json!({"protocolVersion": "2025-03-26"}),
            id: Some(json!(42)),
        };
        let response = handle_initialize_with_session_core(
            &state,
            incoming_headers,
            "/mcp".parse::<Uri>().expect("uri"),
            Bytes::from_static(br#"{"jsonrpc":"2.0","method":"initialize"}"#),
            &request,
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
    }

    #[test]
    fn session_auth_binding_helper_clears_reuse_state_for_disabled_or_invalid_inputs() {
        let stale_value = Some("stale".to_string());
        let stale_ttl = Some(super::unix_epoch_millis() + 60_000);
        let authenticated_context = InternalAuthContext {
            email: Some("owner@example.com".to_string()),
            teams: Some(vec!["team-1".to_string()]),
            is_admin: false,
            is_authenticated: true,
        };
        let unauthenticated_context = InternalAuthContext {
            is_authenticated: false,
            ..authenticated_context.clone()
        };

        let mut base_record = RuntimeSessionRecord {
            owner_email: Some("owner@example.com".to_string()),
            server_id: None,
            protocol_version: None,
            client_capabilities: None,
            encoded_auth_context: stale_value.clone(),
            auth_binding_fingerprint: stale_value.clone(),
            auth_context_expires_at_epoch_ms: stale_ttl,
            created_at: std::time::Instant::now(),
            last_used: std::time::Instant::now(),
        };

        let disabled_state = AppState::new(&{
            let mut config = test_config();
            config.session_auth_reuse_enabled = false;
            config
        })
        .expect("state");
        maybe_bind_session_auth_context(
            &disabled_state,
            &mut base_record,
            &HeaderMap::new(),
            Some(&authenticated_context),
        );
        assert!(base_record.encoded_auth_context.is_none());
        assert!(base_record.auth_binding_fingerprint.is_none());
        assert!(base_record.auth_context_expires_at_epoch_ms.is_none());

        let enabled_state = AppState::new(&test_config()).expect("state");
        let mut record = RuntimeSessionRecord {
            encoded_auth_context: stale_value.clone(),
            auth_binding_fingerprint: stale_value.clone(),
            auth_context_expires_at_epoch_ms: stale_ttl,
            ..base_record.clone()
        };
        maybe_bind_session_auth_context(&enabled_state, &mut record, &HeaderMap::new(), None);
        assert!(record.encoded_auth_context.is_none());

        let mut record = RuntimeSessionRecord {
            encoded_auth_context: stale_value.clone(),
            auth_binding_fingerprint: stale_value.clone(),
            auth_context_expires_at_epoch_ms: stale_ttl,
            ..base_record.clone()
        };
        maybe_bind_session_auth_context(
            &enabled_state,
            &mut record,
            &HeaderMap::new(),
            Some(&unauthenticated_context),
        );
        assert!(record.encoded_auth_context.is_none());

        let auth_context_json = json!({
            "email": "owner@example.com",
            "teams": ["team-1"],
            "is_authenticated": true
        });
        let mut missing_fingerprint_headers = HeaderMap::new();
        missing_fingerprint_headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encode_internal_auth_context_header(&auth_context_json).expect("encode auth context"),
        );
        let mut record = RuntimeSessionRecord {
            encoded_auth_context: stale_value.clone(),
            auth_binding_fingerprint: stale_value.clone(),
            auth_context_expires_at_epoch_ms: stale_ttl,
            ..base_record.clone()
        };
        maybe_bind_session_auth_context(
            &enabled_state,
            &mut record,
            &missing_fingerprint_headers,
            Some(&authenticated_context),
        );
        assert!(record.encoded_auth_context.is_none());

        let mut missing_auth_context_headers = HeaderMap::new();
        missing_auth_context_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        let mut record = RuntimeSessionRecord {
            encoded_auth_context: stale_value,
            auth_binding_fingerprint: Some("fingerprint".to_string()),
            auth_context_expires_at_epoch_ms: stale_ttl,
            ..base_record
        };
        maybe_bind_session_auth_context(
            &enabled_state,
            &mut record,
            &missing_auth_context_headers,
            Some(&authenticated_context),
        );
        assert!(record.encoded_auth_context.is_none());
    }

    #[tokio::test]
    async fn validate_runtime_session_request_covers_missing_and_ownerless_sessions() {
        let state = AppState::new(&test_config()).expect("state");

        let response = validate_runtime_session_request(
            &state,
            &mut HeaderMap::new(),
            &"/mcp?session_id=missing".parse::<Uri>().expect("uri"),
        )
        .await
        .expect_err("missing session is not found");
        assert_eq!(response.status(), StatusCode::NOT_FOUND);

        upsert_runtime_session(
            &state,
            "ownerless".to_string(),
            RuntimeSessionRecord {
                owner_email: None,
                server_id: None,
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: None,
                auth_binding_fingerprint: None,
                auth_context_expires_at_epoch_ms: None,
                created_at: std::time::Instant::now(),
                last_used: std::time::Instant::now(),
            },
        )
        .await;

        let validated = validate_runtime_session_request(
            &state,
            &mut HeaderMap::new(),
            &"/mcp?session_id=ownerless".parse::<Uri>().expect("uri"),
        )
        .await
        .expect("ownerless session is allowed");
        assert_eq!(validated, Some("ownerless".to_string()));
    }

    #[test]
    fn accepts_sse_event_store_prefix_and_injection_helpers_cover_edge_cases() {
        let state = AppState::new(&test_config()).expect("state");
        let mut headers = HeaderMap::new();
        assert!(!accepts_sse(&headers));
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("application/json"),
        );
        assert!(!accepts_sse(&headers));
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream; charset=utf-8"),
        );
        assert!(accepts_sse(&headers));
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("*/*"),
        );
        assert!(accepts_sse(&headers));

        assert_eq!(
            event_store_key_prefix(&state, None),
            "mcpgw:test:eventstore"
        );
        assert_eq!(
            event_store_key_prefix(&state, Some("custom")),
            "mcpgw:test:custom"
        );
        assert_eq!(
            event_store_key_prefix(&state, Some("already:scoped:prefix:")),
            "already:scoped:prefix"
        );

        let mut invalid_headers = HeaderMap::new();
        inject_session_header(&mut invalid_headers, "bad\nsession");
        inject_server_id_header(&mut invalid_headers, "bad\nserver");
        assert!(!invalid_headers.contains_key("mcp-session-id"));
        assert!(!invalid_headers.contains_key("x-contextforge-server-id"));

        let snake_case_request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "initialize".to_string(),
            params: json!({"protocol_version": "2025-11-25"}),
            id: Some(json!(1)),
        };
        assert_eq!(
            requested_protocol_version(&snake_case_request),
            Some("2025-11-25".to_string())
        );

        let weird_uri = "/mcp?broken&session_id=kept".parse::<Uri>().expect("uri");
        assert_eq!(
            query_param(&weird_uri, "session_id"),
            Some("kept".to_string())
        );
    }

    #[test]
    fn affinity_response_helpers_preserve_existing_headers_and_errors() {
        let response = response_from_affinity_forward_response(
            AffinityForwardResponse {
                status: 204,
                headers: [
                    ("content-type".to_string(), "text/plain".to_string()),
                    ("mcp-session-id".to_string(), "already-present".to_string()),
                    ("content-length".to_string(), "99".to_string()),
                    ("connection".to_string(), "keep-alive".to_string()),
                ]
                .into_iter()
                .collect(),
                body: "invalid-hex".to_string(),
            },
            Some("ignored-hint"),
        );
        assert_eq!(response.status(), StatusCode::NO_CONTENT);
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|value| value.to_str().ok()),
            Some("text/plain")
        );
        assert_eq!(
            response
                .headers()
                .get("mcp-session-id")
                .and_then(|value| value.to_str().ok()),
            Some("already-present")
        );
        assert!(!response.headers().contains_key("content-length"));
        assert!(!response.headers().contains_key("connection"));

        let error = affinity_forward_error_response("publish failed", "boom");
        assert_eq!(error.status(), StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn maybe_upsert_runtime_session_from_transport_response_returns_none_without_session_id()
    {
        let state = AppState::new(&test_config()).expect("state");
        assert_eq!(
            maybe_upsert_runtime_session_from_transport_response(
                &state,
                &HeaderMap::new(),
                None,
                &reqwest::header::HeaderMap::new(),
            )
            .await,
            None
        );
    }
}
