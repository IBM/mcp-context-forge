// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

//! Rust MCP runtime sidecar for `ContextForge`.
//!
//! This crate owns the Rust-backed public MCP HTTP edge and, in `full` mode,
//! can also own MCP session/event-store/resume/live-stream/affinity cores while
//! still delegating authentication and RBAC authority to Python.

pub mod backend_url_validator;
pub mod config;
pub mod observability;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::{ConnectInfo, FromRequestParts, Path as AxumPath, State},
    http::request::Parts,
    http::{HeaderMap, HeaderName, HeaderValue, StatusCode, header::CONTENT_TYPE},
    response::{
        IntoResponse, Response,
        sse::{Event, KeepAlive, Sse},
    },
    routing::{get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use bytes::BytesMut;
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use futures_util::{StreamExt, TryStreamExt};
use rand::Rng;
use redis::{AsyncCommands, Script, aio::ConnectionManager as RedisConnectionManager};
use reqwest::{Client, Url};
#[cfg(feature = "rmcp-upstream-client")]
use reqwest_rmcp::Client as RmcpReqwestClient;
use rustls::{
    ClientConfig as RustlsClientConfig, RootCertStore,
    pki_types::{CertificateDer, pem::PemObject},
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, hash_map::DefaultHasher},
    convert::Infallible,
    fs,
    hash::{Hash, Hasher},
    net::{IpAddr, SocketAddr},
    path::Path,
    str::{self, FromStr},
    sync::{
        Arc, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use thiserror::Error;
use tokio::sync::Mutex;
use tokio_postgres::config::SslMode;
use tokio_postgres_rustls::MakeRustlsConnect;
use tracing::{Instrument, debug, error, info, warn};
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
use crate::observability::{
    TraceRequestContext, derive_langfuse_trace_name, inject_current_trace_context,
    is_input_capture_enabled, is_output_capture_enabled, serialize_trace_payload,
    set_langfuse_trace_name, set_span_attribute, set_span_error, start_child_span, start_root_span,
    trace_request_context,
};

const JSONRPC_VERSION: &str = "2.0";
const RUNTIME_HEADER: &str = "x-contextforge-mcp-runtime";
const RUNTIME_NAME: &str = "rust";
const INTERNAL_RUNTIME_AUTH_HEADER: &str = "x-contextforge-mcp-runtime-auth";
const INTERNAL_RUNTIME_AUTH_CONTEXT: &str = "contextforge-internal-mcp-runtime-v1";
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
/// Top-level runtime errors surfaced during startup and listener execution.
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
/// Shared application state for the Rust MCP runtime.
///
/// The state intentionally separates:
///
/// - the direct-path reqwest client used for Python/internal HTTP calls
/// - the RMCP reqwest client used by the optional RMCP upstream transport
/// - runtime/session/tool caches that keep the public MCP hot path off repeated
///   backend lookups where possible
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
    backend_tools_call_metric_url: Arc<str>,
    client: Client,
    // RMCP currently uses reqwest 0.13 while the direct gateway/runtime path
    // uses reqwest 0.12, so the runtime keeps a separate shared client for that
    // transport instead of rebuilding it per upstream session/client.
    #[cfg(feature = "rmcp-upstream-client")]
    rmcp_client: RmcpReqwestClient,
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
    backend_url_validator: backend_url_validator::BackendUrlValidator,
    public_ingress_enabled: bool,
    runtime_stats: Arc<RuntimeStats>,
}

#[derive(Debug, Clone, Deserialize)]
/// Minimal JSON-RPC request envelope accepted by the runtime edge.
pub struct JsonRpcRequest {
    pub jsonrpc: Option<String>,
    pub method: String,
    #[serde(default)]
    pub params: Value,
    #[serde(default)]
    pub id: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
/// Health payload returned by `/health` and `/healthz`.
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
    pub runtime_stats: RuntimeStatsSnapshot,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PublicHealthResponse {
    status: &'static str,
    runtime: &'static str,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimeStatsSnapshot {
    pub session_auth_reuse: SessionAuthReuseStatsSnapshot,
    pub session_access_denials: SessionAccessDenialStatsSnapshot,
    pub affinity: AffinityStatsSnapshot,
    pub transport: TransportStatsSnapshot,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TransportStatsSnapshot {
    // #4205: Total GETs rejected with 405 because a passive SSE stream could
    // not be anchored to a session — sum of both branches below.
    pub get_rejected_no_session: u64,
    // #4205: Subset of `get_rejected_no_session` where `session_core` is
    // disabled on this runtime (deployment-config condition, distinct from
    // normal client behaviour). Non-zero here means clients are being turned
    // away even if they *did* present a session id.
    pub get_rejected_session_core_disabled: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SessionAuthReuseStatsSnapshot {
    pub hits: u64,
    pub misses: u64,
    pub backend_auth_round_trips: u64,
    pub miss_disabled: u64,
    pub miss_no_session: u64,
    pub miss_server_scope_mismatch: u64,
    pub miss_missing_encoded_auth_context: u64,
    pub miss_missing_auth_binding_fingerprint: u64,
    pub miss_auth_binding_mismatch: u64,
    pub miss_ttl_expired: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SessionAccessDenialStatsSnapshot {
    pub server_scope_mismatches: u64,
    pub missing_auth_context: u64,
    pub owner_email_mismatches: u64,
    pub missing_auth_binding_fingerprint: u64,
    pub auth_binding_mismatches: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AffinityStatsSnapshot {
    pub forward_attempts: u64,
    pub forwarded_requests: u64,
}

#[derive(Debug, Default)]
struct RuntimeStats {
    session_auth_reuse_hits: AtomicU64,
    session_auth_reuse_misses: AtomicU64,
    session_auth_backend_round_trips: AtomicU64,
    session_auth_reuse_miss_disabled: AtomicU64,
    session_auth_reuse_miss_no_session: AtomicU64,
    session_auth_reuse_miss_server_scope_mismatch: AtomicU64,
    session_auth_reuse_miss_missing_encoded_auth_context: AtomicU64,
    session_auth_reuse_miss_missing_auth_binding_fingerprint: AtomicU64,
    session_auth_reuse_miss_auth_binding_mismatch: AtomicU64,
    session_auth_reuse_miss_ttl_expired: AtomicU64,
    session_access_server_scope_mismatches: AtomicU64,
    session_access_missing_auth_context: AtomicU64,
    session_access_owner_email_mismatches: AtomicU64,
    session_access_missing_auth_binding_fingerprint: AtomicU64,
    session_access_auth_binding_mismatches: AtomicU64,
    affinity_forward_attempts: AtomicU64,
    affinity_forwarded_requests: AtomicU64,
    transport_get_rejected_no_session: AtomicU64,
    transport_get_rejected_session_core_disabled: AtomicU64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionAuthReuseMissReason {
    Disabled,
    NoSession,
    ServerScopeMismatch,
    MissingEncodedAuthContext,
    MissingAuthBindingFingerprint,
    AuthBindingMismatch,
    TtlExpired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionAccessDenyReason {
    MissingAuthContext,
    OwnerEmailMismatch,
    MissingAuthBindingFingerprint,
    AuthBindingMismatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TransportGetRejectReason {
    // GET arrived without a session id in either header or query param.
    NoSessionId,
    // `session_core` is disabled globally, so no GET can be anchored.
    SessionCoreDisabled,
}

const CLIENT_ERROR_DETAIL: &str = "See server logs";

#[derive(Debug, Clone, Copy, Default)]
struct TrustedPeerAddr(Option<SocketAddr>);

impl<S> FromRequestParts<S> for TrustedPeerAddr
where
    S: Send + Sync,
{
    type Rejection = Infallible;

    async fn from_request_parts(parts: &mut Parts, _state: &S) -> Result<Self, Self::Rejection> {
        Ok(Self(
            parts
                .extensions
                .get::<ConnectInfo<SocketAddr>>()
                .map(|info| info.0),
        ))
    }
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
/// Minimal normalized auth context returned by Python to the Rust edge.
///
/// Rust uses this for ownership checks and optional session-bound auth reuse,
/// but Python remains the source of truth for authentication and RBAC.
struct InternalAuthContext {
    email: Option<String>,
    teams: Option<Vec<String>>,
    #[serde(default)]
    team_name: Option<String>,
    #[serde(default)]
    auth_method: Option<String>,
    #[serde(default)]
    permission_is_admin: Option<bool>,
    #[serde(default)]
    is_admin: bool,
    #[serde(default)]
    is_authenticated: bool,
}

impl InternalAuthContext {
    fn effective_is_admin(&self) -> bool {
        self.permission_is_admin.unwrap_or(self.is_admin)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
/// Payload sent to Python's trusted internal authenticate endpoint.
///
/// The request captures the public MCP request shape after nginx/Rust ingress
/// normalization so Python can evaluate auth and token scoping exactly once.
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
/// Successful response from Python's trusted internal authenticate endpoint.
struct InternalAuthenticateResponse {
    auth_context: Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
/// Pre-resolved direct-execution plan for a `tools/call` request.
///
/// Python decides whether a call is eligible for Rust-side direct execution and
/// returns the concrete upstream routing information. Rust then caches the
/// parsed form of the plan to keep the hot path off repeated JSON/header work.
struct ResolvedMcpToolCallPlan {
    eligible: bool,
    #[serde(default)]
    fallback_reason: Option<String>,
    #[serde(default)]
    tool_name: Option<String>,
    #[serde(default)]
    tool_id: Option<String>,
    #[serde(default)]
    gateway_id: Option<String>,
    #[serde(default)]
    server_id: Option<String>,
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
    #[serde(skip)]
    parsed_headers: Option<Vec<(HeaderName, HeaderValue)>>,
    #[serde(skip)]
    headers_hash: Option<u64>,
    #[serde(default)]
    has_pre_invoke_hooks: bool,
    #[serde(default)]
    modified_args: Option<Value>,
    #[serde(default)]
    post_invoke_retry_policy: Option<NativePostInvokeRetryPolicy>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativePostInvokeRetryPolicy {
    kind: String,
    max_retries: u32,
    backoff_base_ms: u64,
    max_backoff_ms: u64,
    retry_on_status: Vec<i32>,
    jitter: bool,
}

#[derive(Debug, Clone)]
/// Cached upstream session for a direct or RMCP tool target.
///
/// The key is derived from the downstream MCP session plus the resolved tool
/// plan so unrelated callers or upstreams never share the same upstream MCP
/// session accidentally.
struct UpstreamToolSession {
    session_id: Option<String>,
    last_used: Instant,
}

#[allow(dead_code)]
#[derive(Debug, Clone)]
/// Runtime-owned metadata for a public MCP session.
///
/// This is the central record used for session ownership, optional auth-context
/// reuse, server-scope pinning, and cross-worker sharing via Redis.
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

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ToolsCallMetricRecordRequest {
    tool_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    server_id: Option<String>,
    duration_ms: f64,
    success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
/// Redis-serializable subset of [`RuntimeSessionRecord`].
///
/// Local-only timing state such as `created_at` and `last_used` is intentionally
/// rebuilt per worker because it is only used for in-process cache management.
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

fn normalize_tool_input_schema(input_schema: Option<Value>) -> Value {
    let mut schema = input_schema.unwrap_or_else(|| json!({"type": "object", "properties": {}}));

    let Some(schema_object) = schema.as_object_mut() else {
        return schema;
    };

    let is_object_schema = schema_object.get("type").and_then(Value::as_str) == Some("object");
    let has_properties = schema_object
        .get("properties")
        .is_some_and(Value::is_object);

    if (is_object_schema || has_properties) && !schema_object.contains_key("required") {
        schema_object.insert("required".to_string(), Value::Array(Vec::new()));
    }

    schema
}

fn jsonrpc_response_status(status: StatusCode) -> StatusCode {
    if status.is_success() {
        status
    } else {
        StatusCode::OK
    }
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
        ensure_internal_runtime_auth_secret()?;
        let client = Client::builder()
            .connect_timeout(Duration::from_millis(config.client_connect_timeout_ms))
            .pool_idle_timeout(Duration::from_secs(config.client_pool_idle_timeout_seconds))
            .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
            .tcp_keepalive(Duration::from_secs(config.client_tcp_keepalive_seconds))
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .redirect(reqwest::redirect::Policy::none())
            .build()?;
        #[cfg(feature = "rmcp-upstream-client")]
        let rmcp_client = RmcpReqwestClient::builder()
            .connect_timeout(Duration::from_millis(config.client_connect_timeout_ms))
            .pool_idle_timeout(Duration::from_secs(config.client_pool_idle_timeout_seconds))
            .pool_max_idle_per_host(config.client_pool_max_idle_per_host)
            .tcp_keepalive(Duration::from_secs(config.client_tcp_keepalive_seconds))
            .timeout(Duration::from_millis(config.request_timeout_ms))
            .redirect(reqwest_rmcp::redirect::Policy::none())
            .build()
            .map_err(|err| RuntimeError::Config(format!("rmcp http client error: {err}")))?;
        let db_pool = build_db_pool(config)?;
        let redis_client = build_redis_client(config)?;
        let backend_url_validator = backend_url_validator::BackendUrlValidator::from_config(config)
            .map_err(|e| RuntimeError::Config(format!("Backend URL validator error: {}", e)))?;
        backend_url_validator
            .validate_url(&config.backend_rpc_url, "Backend RPC URL (startup)")
            .map_err(|err| {
                RuntimeError::Config(format!(
                    "MCP_RUST_BACKEND_RPC_URL rejected by validator: {err}"
                ))
            })?;

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
            backend_tools_call_metric_url: Arc::from(derive_backend_tools_call_metric_url(
                &config.backend_rpc_url,
            )),
            client,
            #[cfg(feature = "rmcp-upstream-client")]
            rmcp_client,
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
            backend_url_validator,
            public_ingress_enabled: config.public_listen_http.is_some(),
            runtime_stats: Arc::new(RuntimeStats::default()),
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
    pub fn backend_tools_call_metric_url(&self) -> &str {
        &self.backend_tools_call_metric_url
    }

    /// Validates a backend URL before making an outgoing HTTP request.
    ///
    /// This protects against SSRF via misconfigured environment variables.
    /// See `backend_url_validator` module for threat model and design.
    #[allow(clippy::result_large_err)]
    fn validate_backend_url(&self, url: &str, description: &str) -> Result<(), Response> {
        self.backend_url_validator
            .validate_url(url, description)
            .map_err(|e| {
                error!("Backend URL validation failed for {}: {}", description, e);
                validation_error_response(e)
            })
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

    fn runtime_stats(&self) -> &Arc<RuntimeStats> {
        &self.runtime_stats
    }
}

fn ensure_internal_runtime_auth_secret() -> Result<(), RuntimeError> {
    if std::env::var("AUTH_ENCRYPTION_SECRET")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .is_some()
    {
        Ok(())
    } else {
        Err(RuntimeError::Config(
            "AUTH_ENCRYPTION_SECRET must be set for internal MCP runtime authentication"
                .to_string(),
        ))
    }
}

impl RuntimeStats {
    fn snapshot(&self) -> RuntimeStatsSnapshot {
        RuntimeStatsSnapshot {
            session_auth_reuse: SessionAuthReuseStatsSnapshot {
                hits: self.session_auth_reuse_hits.load(Ordering::Relaxed),
                misses: self.session_auth_reuse_misses.load(Ordering::Relaxed),
                backend_auth_round_trips: self
                    .session_auth_backend_round_trips
                    .load(Ordering::Relaxed),
                miss_disabled: self
                    .session_auth_reuse_miss_disabled
                    .load(Ordering::Relaxed),
                miss_no_session: self
                    .session_auth_reuse_miss_no_session
                    .load(Ordering::Relaxed),
                miss_server_scope_mismatch: self
                    .session_auth_reuse_miss_server_scope_mismatch
                    .load(Ordering::Relaxed),
                miss_missing_encoded_auth_context: self
                    .session_auth_reuse_miss_missing_encoded_auth_context
                    .load(Ordering::Relaxed),
                miss_missing_auth_binding_fingerprint: self
                    .session_auth_reuse_miss_missing_auth_binding_fingerprint
                    .load(Ordering::Relaxed),
                miss_auth_binding_mismatch: self
                    .session_auth_reuse_miss_auth_binding_mismatch
                    .load(Ordering::Relaxed),
                miss_ttl_expired: self
                    .session_auth_reuse_miss_ttl_expired
                    .load(Ordering::Relaxed),
            },
            session_access_denials: SessionAccessDenialStatsSnapshot {
                server_scope_mismatches: self
                    .session_access_server_scope_mismatches
                    .load(Ordering::Relaxed),
                missing_auth_context: self
                    .session_access_missing_auth_context
                    .load(Ordering::Relaxed),
                owner_email_mismatches: self
                    .session_access_owner_email_mismatches
                    .load(Ordering::Relaxed),
                missing_auth_binding_fingerprint: self
                    .session_access_missing_auth_binding_fingerprint
                    .load(Ordering::Relaxed),
                auth_binding_mismatches: self
                    .session_access_auth_binding_mismatches
                    .load(Ordering::Relaxed),
            },
            affinity: AffinityStatsSnapshot {
                forward_attempts: self.affinity_forward_attempts.load(Ordering::Relaxed),
                forwarded_requests: self.affinity_forwarded_requests.load(Ordering::Relaxed),
            },
            transport: TransportStatsSnapshot {
                get_rejected_no_session: self
                    .transport_get_rejected_no_session
                    .load(Ordering::Relaxed),
                get_rejected_session_core_disabled: self
                    .transport_get_rejected_session_core_disabled
                    .load(Ordering::Relaxed),
            },
        }
    }

    fn record_session_auth_reuse_hit(&self) {
        self.session_auth_reuse_hits.fetch_add(1, Ordering::Relaxed);
    }

    fn record_session_auth_reuse_miss(&self, reason: SessionAuthReuseMissReason) {
        self.session_auth_reuse_misses
            .fetch_add(1, Ordering::Relaxed);
        match reason {
            SessionAuthReuseMissReason::Disabled => {
                self.session_auth_reuse_miss_disabled
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::NoSession => {
                self.session_auth_reuse_miss_no_session
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::ServerScopeMismatch => {
                self.session_auth_reuse_miss_server_scope_mismatch
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::MissingEncodedAuthContext => {
                self.session_auth_reuse_miss_missing_encoded_auth_context
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::MissingAuthBindingFingerprint => {
                self.session_auth_reuse_miss_missing_auth_binding_fingerprint
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::AuthBindingMismatch => {
                self.session_auth_reuse_miss_auth_binding_mismatch
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAuthReuseMissReason::TtlExpired => {
                self.session_auth_reuse_miss_ttl_expired
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    fn record_session_auth_backend_round_trip(&self) {
        self.session_auth_backend_round_trips
            .fetch_add(1, Ordering::Relaxed);
    }

    fn record_session_access_denial(&self, reason: SessionAccessDenyReason) {
        match reason {
            SessionAccessDenyReason::MissingAuthContext => {
                self.session_access_missing_auth_context
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAccessDenyReason::OwnerEmailMismatch => {
                self.session_access_owner_email_mismatches
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAccessDenyReason::MissingAuthBindingFingerprint => {
                self.session_access_missing_auth_binding_fingerprint
                    .fetch_add(1, Ordering::Relaxed);
            }
            SessionAccessDenyReason::AuthBindingMismatch => {
                self.session_access_auth_binding_mismatches
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    fn record_session_server_scope_mismatch(&self) {
        self.session_access_server_scope_mismatches
            .fetch_add(1, Ordering::Relaxed);
    }

    fn record_affinity_forward_attempt(&self) {
        self.affinity_forward_attempts
            .fetch_add(1, Ordering::Relaxed);
    }

    fn record_affinity_forwarded_request(&self) {
        self.affinity_forwarded_requests
            .fetch_add(1, Ordering::Relaxed);
    }

    fn record_transport_get_rejected_no_session(&self, reason: TransportGetRejectReason) {
        self.transport_get_rejected_no_session
            .fetch_add(1, Ordering::Relaxed);
        if matches!(reason, TransportGetRejectReason::SessionCoreDisabled) {
            self.transport_get_rejected_session_core_disabled
                .fetch_add(1, Ordering::Relaxed);
        }
    }
}

/// Builds the Axum router for the Rust MCP runtime.
///
/// The router exposes public MCP ingress, health probes, and internal helpers
/// used by tests and mode-specific runtime slices.
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

fn build_public_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(public_healthz))
        .route("/healthz", get(public_healthz))
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
    spawn_local_cache_sweeper(state.clone());
    let app = build_router(state.clone());
    let public_app = build_public_router(state);

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
                serve_http(public_app, public_addr, shutdown_after)
            )?;
        }
        (ListenTarget::Uds(path), None) => {
            serve_uds(app, path, shutdown_after).await?;
        }
        (ListenTarget::Uds(path), Some(public_addr)) => {
            tokio::try_join!(
                serve_uds(app.clone(), path, shutdown_after),
                serve_http(public_app, public_addr, shutdown_after)
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
        axum::serve(
            listener,
            app.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .with_graceful_shutdown(async move {
            tokio::time::sleep(delay).await;
        })
        .await?;
    } else {
        axum::serve(
            listener,
            app.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .await?;
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
        runtime_stats: state.runtime_stats().snapshot(),
    })
}

async fn public_healthz() -> Json<PublicHealthResponse> {
    Json(PublicHealthResponse {
        status: "ok",
        runtime: RUNTIME_NAME,
    })
}

async fn transport_get(
    State(state): State<AppState>,
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_get_inner(state, peer_addr.0, headers, uri, None).await
}

async fn transport_delete(
    State(state): State<AppState>,
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_delete_inner(state, peer_addr.0, headers, uri, None).await
}

async fn transport_get_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_get_inner(state, peer_addr.0, headers, uri, Some(server_id)).await
}

async fn transport_delete_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
) -> Response {
    transport_delete_inner(state, peer_addr.0, headers, uri, Some(server_id)).await
}

async fn transport_get_inner(
    state: AppState,
    peer_addr: Option<SocketAddr>,
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
        peer_addr,
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
    peer_addr: Option<SocketAddr>,
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
        peer_addr,
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
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
) -> Response {
    rpc_inner(state, peer_addr.0, headers, uri, body, None).await
}

async fn rpc_server_scoped(
    State(state): State<AppState>,
    AxumPath(server_id): AxumPath<String>,
    peer_addr: TrustedPeerAddr,
    headers: HeaderMap,
    uri: axum::http::Uri,
    body: Bytes,
) -> Response {
    rpc_inner(state, peer_addr.0, headers, uri, body, Some(server_id)).await
}

async fn rpc_inner(
    state: AppState,
    peer_addr: Option<SocketAddr>,
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
        peer_addr,
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

    if specialized_prompts_get
        && let Some(params) = request.params.as_object()
        && let Err(response) = validate_prompt_get_arguments(params, request.id.as_ref())
    {
        return response;
    }

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

const BACKEND_RPC_SUFFIXES: &[&str] =
    &["/_internal/mcp/rpc", "/_internal/mcp/rpc/", "/rpc", "/rpc/"];

fn derive_backend_url(backend_rpc_url: &str, path: &str) -> String {
    for suffix in BACKEND_RPC_SUFFIXES {
        if let Some(prefix) = backend_rpc_url.strip_suffix(suffix) {
            return format!("{prefix}/_internal/mcp/{path}");
        }
    }
    format!(
        "{}/_internal/mcp/{path}",
        backend_rpc_url.trim_end_matches('/')
    )
}

fn derive_backend_tools_list_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "tools/list")
}
fn derive_backend_resources_list_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/list")
}
fn derive_backend_resources_read_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/read")
}
fn derive_backend_resources_subscribe_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/subscribe")
}
fn derive_backend_resources_unsubscribe_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/unsubscribe")
}
fn derive_backend_resource_templates_list_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/templates/list")
}
fn derive_backend_prompts_list_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "prompts/list")
}
fn derive_backend_prompts_get_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "prompts/get")
}
fn derive_backend_roots_list_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "roots/list")
}
fn derive_backend_completion_complete_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "completion/complete")
}
fn derive_backend_sampling_create_message_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "sampling/createMessage")
}
fn derive_backend_logging_set_level_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "logging/setLevel")
}
fn derive_backend_initialize_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "initialize")
}
fn derive_backend_transport_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "transport")
}
fn derive_backend_session_delete_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "session")
}
fn derive_backend_notifications_initialized_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "notifications/initialized")
}
fn derive_backend_notifications_message_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "notifications/message")
}
fn derive_backend_notifications_cancelled_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "notifications/cancelled")
}
fn derive_backend_tools_list_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "tools/list/authz")
}
fn derive_backend_resources_list_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/list/authz")
}
fn derive_backend_resources_read_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/read/authz")
}
fn derive_backend_resource_templates_list_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "resources/templates/list/authz")
}
fn derive_backend_prompts_list_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "prompts/list/authz")
}
fn derive_backend_prompts_get_authz_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "prompts/get/authz")
}
fn derive_backend_tools_call_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "tools/call")
}
fn derive_backend_tools_call_resolve_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "tools/call/resolve")
}
fn derive_backend_tools_call_metric_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "tools/call/metric")
}
fn derive_backend_authenticate_url(backend_rpc_url: &str) -> String {
    derive_backend_url(backend_rpc_url, "authenticate")
}

fn build_db_pool(config: &RuntimeConfig) -> Result<Option<Pool>, RuntimeError> {
    let Some(database_url) = config.database_url.as_deref() else {
        return Ok(None);
    };

    if database_url.starts_with("sqlite:") {
        warn!("Rust MCP direct DB mode disabled: sqlite is not supported");
        return Ok(None);
    }

    let (normalized_url, tls_options) = normalize_postgres_database_url(database_url)?;
    let pg_config = tokio_postgres::Config::from_str(&normalized_url).map_err(|err| {
        RuntimeError::Config(format!(
            "invalid MCP_RUST_DATABASE_URL '{normalized_url}': {err}"
        ))
    })?;
    let tls_connector = build_postgres_tls_connector(&tls_options)?;
    let mgr_config = ManagerConfig {
        recycling_method: RecyclingMethod::Fast,
    };
    match pg_config.get_ssl_mode() {
        SslMode::Disable => info!("Rust MCP direct DB pool TLS disabled via sslmode=disable"),
        SslMode::Prefer => info!("Rust MCP direct DB pool TLS optional via sslmode=prefer"),
        SslMode::Require => info!("Rust MCP direct DB pool TLS required via sslmode=require"),
        _ => info!("Rust MCP direct DB pool TLS configured with a non-default sslmode"),
    }
    let manager = Manager::from_config(pg_config, tls_connector, mgr_config);
    let pool = Pool::builder(manager)
        .max_size(config.db_pool_max_size)
        .build()
        .map_err(|err| RuntimeError::Config(format!("failed to build Rust MCP DB pool: {err}")))?;

    Ok(Some(pool))
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
#[allow(clippy::struct_field_names)]
struct PostgresTlsOptions {
    ssl_root_cert: Option<String>,
    ssl_cert: Option<String>,
    ssl_key: Option<String>,
}

fn normalize_postgres_database_url(
    database_url: &str,
) -> Result<(String, PostgresTlsOptions), RuntimeError> {
    let normalized_url = database_url.replace("postgresql+psycopg://", "postgresql://");
    let mut parsed = Url::parse(&normalized_url).map_err(|err| {
        RuntimeError::Config(format!(
            "invalid MCP_RUST_DATABASE_URL '{normalized_url}': {err}"
        ))
    })?;
    let mut tls_options = PostgresTlsOptions::default();
    let retained_query_pairs = parsed
        .query_pairs()
        .into_owned()
        .filter_map(|(key, value)| match key.as_str() {
            "sslrootcert" => {
                tls_options.ssl_root_cert = Some(value);
                None
            }
            "sslcert" => {
                tls_options.ssl_cert = Some(value);
                None
            }
            "sslkey" => {
                tls_options.ssl_key = Some(value);
                None
            }
            _ => Some((key, value)),
        })
        .collect::<Vec<_>>();
    {
        let mut query_pairs = parsed.query_pairs_mut();
        query_pairs.clear();
        query_pairs.extend_pairs(
            retained_query_pairs
                .iter()
                .map(|(key, value)| (key.as_str(), value.as_str())),
        );
    }

    Ok((parsed.to_string(), tls_options))
}

fn build_postgres_tls_connector(
    tls_options: &PostgresTlsOptions,
) -> Result<MakeRustlsConnect, RuntimeError> {
    if tls_options.ssl_cert.is_some() || tls_options.ssl_key.is_some() {
        return Err(RuntimeError::Config(
            "MCP_RUST_DATABASE_URL client certificate authentication via sslcert/sslkey is not supported yet".to_string(),
        ));
    }

    ensure_rustls_crypto_provider();

    let mut root_cert_store = RootCertStore::empty();
    let native_certs = rustls_native_certs::load_native_certs();
    for load_error in native_certs.errors {
        warn!("Rust MCP DB TLS native root load warning: {load_error}");
    }
    let (_added, _ignored) = root_cert_store.add_parsable_certificates(native_certs.certs);

    if let Some(path) = tls_options.ssl_root_cert.as_deref() {
        let certificates = load_pem_certificates(path)?;
        let (added, _ignored) = root_cert_store.add_parsable_certificates(certificates);
        if added == 0 {
            return Err(RuntimeError::Config(format!(
                "invalid MCP_RUST_DATABASE_URL sslrootcert '{path}': no certificates were parsed"
            )));
        }
    }

    let tls_connector = RustlsClientConfig::builder()
        .with_root_certificates(root_cert_store)
        .with_no_client_auth();

    Ok(MakeRustlsConnect::new(tls_connector))
}

fn load_pem_certificates(path: &str) -> Result<Vec<CertificateDer<'static>>, RuntimeError> {
    let pem_bytes = fs::read(path).map_err(|err| {
        RuntimeError::Config(format!(
            "invalid MCP_RUST_DATABASE_URL sslrootcert '{path}': {err}"
        ))
    })?;
    let certificates = CertificateDer::pem_slice_iter(&pem_bytes)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| {
            RuntimeError::Config(format!(
                "invalid MCP_RUST_DATABASE_URL sslrootcert '{path}': {err}"
            ))
        })?;
    if certificates.is_empty() {
        return Err(RuntimeError::Config(format!(
            "invalid MCP_RUST_DATABASE_URL sslrootcert '{path}': no certificates were parsed"
        )));
    }
    Ok(certificates)
}

fn ensure_rustls_crypto_provider() {
    static RUSTLS_CRYPTO_PROVIDER: OnceLock<()> = OnceLock::new();

    RUSTLS_CRYPTO_PROVIDER.get_or_init(|| {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
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
                | INTERNAL_RUNTIME_AUTH_HEADER
                | "x-contextforge-auth-context"
                | "x-contextforge-server-id"
        ) {
            continue;
        }

        if let Ok(value) = value.to_str() {
            headers.insert(name.as_str().to_string(), value.to_string());
        }
    }
    headers
}

fn public_client_ip(incoming_headers: &HeaderMap, peer_addr: Option<SocketAddr>) -> Option<String> {
    let peer_ip = peer_addr.map(|addr| addr.ip());
    let real_ip = incoming_headers
        .get("x-real-ip")
        .and_then(|value| value.to_str().ok())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);
    let forwarded_for_ip = incoming_headers
        .get("x-forwarded-for")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.split(',').next())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);

    match peer_ip {
        Some(peer_ip) if proxy_header_hop_is_trusted(peer_ip) && trust_proxy_headers_enabled() => {
            real_ip
                .or(forwarded_for_ip)
                .or_else(|| Some(peer_ip.to_string()))
        }
        Some(peer_ip) => Some(peer_ip.to_string()),
        None => None,
    }
}

fn internal_runtime_auth_header_value() -> HeaderValue {
    static HEADER_VALUE: OnceLock<HeaderValue> = OnceLock::new();
    HEADER_VALUE
        .get_or_init(|| {
            let secret = std::env::var("AUTH_ENCRYPTION_SECRET").expect(
                "AUTH_ENCRYPTION_SECRET must be set for internal MCP runtime authentication",
            );
            let digest =
                Sha256::digest(format!("{secret}:{INTERNAL_RUNTIME_AUTH_CONTEXT}").as_bytes());
            HeaderValue::from_str(&hex_encode(digest.as_ref()))
                .expect("derived internal MCP runtime auth header must be valid")
        })
        .clone()
}

fn proxy_header_hop_is_trusted(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ipv4) => ipv4.is_loopback() || ipv4.is_private() || ipv4.is_link_local(),
        IpAddr::V6(ipv6) => {
            ipv6.is_loopback() || ipv6.is_unique_local() || ipv6.is_unicast_link_local()
        }
    }
}

fn trust_proxy_headers_enabled() -> bool {
    env_flag_enabled("TRUST_PROXY_AUTH") && env_flag_enabled("TRUST_PROXY_AUTH_DANGEROUSLY")
}

fn env_flag_enabled(name: &str) -> bool {
    std::env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
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
) -> Result<String, SessionAuthReuseMissReason> {
    if !state.session_auth_reuse_enabled() {
        return Err(SessionAuthReuseMissReason::Disabled);
    }

    if requested_server_id.is_some() && record.server_id.as_deref() != requested_server_id {
        return Err(SessionAuthReuseMissReason::ServerScopeMismatch);
    }

    let encoded_auth_context = record
        .encoded_auth_context
        .clone()
        .ok_or(SessionAuthReuseMissReason::MissingEncodedAuthContext)?;
    let expected_fingerprint = record
        .auth_binding_fingerprint
        .as_deref()
        .ok_or(SessionAuthReuseMissReason::MissingAuthBindingFingerprint)?;
    let actual_fingerprint = auth_binding_fingerprint(incoming_headers)
        .ok_or(SessionAuthReuseMissReason::MissingAuthBindingFingerprint)?;
    if actual_fingerprint != expected_fingerprint {
        return Err(SessionAuthReuseMissReason::AuthBindingMismatch);
    }

    let expires_at = record
        .auth_context_expires_at_epoch_ms
        .ok_or(SessionAuthReuseMissReason::TtlExpired)?;
    if unix_epoch_millis() >= expires_at {
        return Err(SessionAuthReuseMissReason::TtlExpired);
    }

    Ok(encoded_auth_context)
}

#[allow(clippy::result_large_err)]
fn encode_internal_auth_context_header(auth_context: &Value) -> Result<HeaderValue, Response> {
    let encoded = URL_SAFE_NO_PAD.encode(serde_json::to_vec(auth_context).map_err(|err| {
        error!("internal MCP auth context serialization failed: {err}");
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": "Internal MCP auth context serialization failed",
            }),
        )
    })?);

    HeaderValue::from_str(&encoded).map_err(|err| {
        error!("internal MCP auth context header encoding failed: {err}");
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": "Internal MCP auth context header encoding failed",
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
    peer_addr: Option<SocketAddr>,
) -> Result<(HeaderMap, String), Response> {
    // Public Rust ingress still treats Python as the auth authority. Incoming
    // client headers are scrubbed of internal-only state first; the only fast
    // path is reusing auth that was previously bound to this runtime session.
    let public_path = public_mcp_path(uri, server_id);
    if !state.public_ingress_enabled() {
        if let Some(server_id) = server_id {
            inject_server_id_header(&mut incoming_headers, server_id);
        }
        return Ok((incoming_headers, public_path));
    }

    incoming_headers.remove("x-contextforge-auth-context");
    incoming_headers.remove("x-contextforge-server-id");
    if let Some(server_id) = server_id {
        inject_server_id_header(&mut incoming_headers, server_id);
    }

    if state.session_core_enabled()
        && let Some(session_id) = runtime_session_id_from_request(&incoming_headers, uri)
    {
        if let Some(record) = get_runtime_session(state, &session_id).await {
            match can_reuse_session_auth(state, &record, &incoming_headers, server_id) {
                Ok(encoded_auth_context) => {
                    state.runtime_stats().record_session_auth_reuse_hit();
                    let encoded_auth_context = HeaderValue::from_str(&encoded_auth_context)
                        .map_err(|err| {
                            error!("stored MCP auth context header encoding failed: {err}");
                            json_response(
                                StatusCode::BAD_GATEWAY,
                                json!({
                                    "detail": "Stored MCP auth context header encoding failed",
                                }),
                            )
                        })?;
                    incoming_headers.insert(
                        HeaderName::from_static("x-contextforge-auth-context"),
                        encoded_auth_context,
                    );
                    return Ok((incoming_headers, public_path));
                }
                Err(reason) => state.runtime_stats().record_session_auth_reuse_miss(reason),
            }
        } else {
            state
                .runtime_stats()
                .record_session_auth_reuse_miss(SessionAuthReuseMissReason::NoSession);
        }
    }

    state
        .runtime_stats()
        .record_session_auth_backend_round_trip();
    let request_body = InternalAuthenticateRequest {
        method: method.to_string(),
        path: public_path.clone(),
        query_string: uri.query().unwrap_or_default().to_string(),
        headers: build_public_auth_headers(&incoming_headers),
        client_ip: public_client_ip(&incoming_headers, peer_addr),
    };

    let url = state.backend_authenticate_url();
    state.validate_backend_url(url, "Backend authenticate URL")?;

    let backend_response = state
        .client
        .post(url)
        .header(RUNTIME_HEADER, RUNTIME_NAME)
        .header(
            HeaderName::from_static(INTERNAL_RUNTIME_AUTH_HEADER),
            internal_runtime_auth_header_value(),
        )
        .json(&request_body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP authenticate failed: {err}");
            backend_detail_error_response("Backend MCP authenticate failed")
        })?;

    if !backend_response.status().is_success() {
        return Err(response_from_backend(backend_response));
    }

    let response_body: InternalAuthenticateResponse =
        backend_response.json().await.map_err(|err| {
            error!("backend MCP authenticate decode failed: {err}");
            backend_detail_error_response("Backend MCP authenticate decode failed")
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

#[allow(clippy::result_large_err)]
fn validate_prompt_get_arguments(
    params: &Map<String, Value>,
    request_id: Option<&Value>,
) -> Result<(), Response> {
    let Some(arguments) = params.get("arguments") else {
        return Ok(());
    };

    let Some(arguments_object) = arguments.as_object() else {
        return Err(json_response(
            StatusCode::OK,
            json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id.cloned(),
                "error": {
                    "code": -32602,
                    "message": "Prompt arguments must be an object with string values",
                },
            }),
        ));
    };

    for (key, value) in arguments_object {
        if !value.is_string() {
            return Err(json_response(
                StatusCode::OK,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id.cloned(),
                    "error": {
                        "code": -32602,
                        "message": format!("Prompt argument '{key}' must be a string value"),
                    },
                }),
            ));
        }
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

fn validation_error_response(message: String) -> Response {
    json_response(
        StatusCode::BAD_GATEWAY,
        json!({
            "error": "Bad Gateway",
            "message": message,
            "data": CLIENT_ERROR_DETAIL,
        }),
    )
}

async fn forward_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let request_payload = parse_jsonrpc_request_payload(&body);
    let method_name =
        extract_jsonrpc_method(request_payload.as_ref()).unwrap_or_else(|| "unknown".to_string());
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("mcp.forward", &incoming_headers, auth_context.as_ref());
    set_span_attribute(&span, "mcp.method", method_name.clone());
    if is_root_span {
        set_langfuse_trace_name(&span, format!("MCP: {}", method_name.replace('/', ".")));
    }
    if is_input_capture_enabled("mcp.forward") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response =
            match send_to_backend_url(state, state.backend_rpc_url(), incoming_headers, body).await
            {
                Ok(response) => response,
                Err(response) => {
                    set_span_error(
                        &span_for_body,
                        "Backend MCP dispatch failed",
                        Some("RuntimeError"),
                    );
                    return response;
                }
            };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if !status.is_success() {
            set_span_error(
                &span_for_body,
                format!("Backend MCP dispatch returned status {status}"),
                Some("RuntimeError"),
            );
        }

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
}

async fn forward_initialize_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let request_payload = parse_jsonrpc_request_payload(&body);
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("mcp.initialize", &incoming_headers, auth_context.as_ref());
    set_span_attribute(&span, "mcp.method", "initialize");
    if is_root_span {
        set_langfuse_trace_name(&span, "mcp.initialize");
    }
    if is_input_capture_enabled("mcp.initialize") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_to_backend_url(
            state,
            state.backend_initialize_url(),
            incoming_headers,
            body,
        )
        .await
        {
            Ok(response) => response,
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP initialize dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if !status.is_success() {
            set_span_error(
                &span_for_body,
                format!("Backend MCP initialize returned status {status}"),
                Some("RuntimeError"),
            );
        }

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
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
    let request_id = request.id.clone();
    let request_params = request.params.clone();
    let (span, is_root_span) =
        start_runtime_operation_span("mcp.initialize", &incoming_headers, auth_context.as_ref());
    set_span_attribute(&span, "mcp.method", "initialize");
    set_span_attribute(&span, "mcp.session_id", session_id.clone());
    set_span_attribute(&span, "langfuse.session.id", session_id.clone());
    if is_root_span {
        set_langfuse_trace_name(&span, "mcp.initialize");
    }
    if is_input_capture_enabled("mcp.initialize") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }
    let span_for_body = span.clone();

    async move {
        if let Some(existing) = get_runtime_session(state, &session_id).await
            && let Err(reason) =
                runtime_session_access_outcome(&existing, auth_context.as_ref(), &incoming_headers)
        {
            state.runtime_stats().record_session_access_denial(reason);
            set_span_error(&span_for_body, "Access denied", Some("PermissionDenied"));
            return json_response(
                StatusCode::OK,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
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
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP initialize transport dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        let response_session_id = backend_response
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok())
            .map_or_else(|| session_id.clone(), str::to_string);
        set_span_attribute(
            &span_for_body,
            "mcp.session_id",
            response_session_id.clone(),
        );
        set_span_attribute(
            &span_for_body,
            "langfuse.session.id",
            response_session_id.clone(),
        );

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
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
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(
                &span_for_body,
                format!("Backend MCP initialize returned status {status}"),
                Some("RuntimeError"),
            );
            remove_runtime_session(state, &response_session_id).await;
        }

        let mut response = response_from_backend_with_session_hint(
            backend_response,
            Some(response_session_id.as_str()),
        );
        inject_runtime_capability_headers(
            &mut response,
            &[
                (SESSION_CORE_HEADER, state.session_core_enabled()),
                (EVENT_STORE_HEADER, state.event_store_enabled()),
                (
                    SESSION_AUTH_REUSE_HEADER,
                    state.session_auth_reuse_enabled(),
                ),
                (RESUME_CORE_HEADER, state.resume_core_enabled()),
            ],
        );
        response
    }
    .instrument(span)
    .await
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
    match redis.scan_match::<_, String>(pattern).await {
        Ok(mut iter) => {
            let mut count = 0usize;
            while iter.next_item().await.is_some() {
                count = count.saturating_add(1);
            }
            Some(count)
        }
        Err(err) => {
            warn!("Rust MCP session count Redis lookup failed: {err}");
            None
        }
    }
}

async fn sweep_local_caches(state: &AppState) {
    {
        let mut sessions = state.runtime_sessions().lock().await;
        let ttl = state.session_ttl();
        sessions.retain(|_, record| record.last_used.elapsed() < ttl);
    }

    {
        let mut sessions = state.upstream_tool_sessions().lock().await;
        let ttl = state.upstream_session_ttl();
        sessions.retain(|_, record| record.last_used.elapsed() < ttl);
    }

    #[cfg(feature = "rmcp-upstream-client")]
    {
        let mut clients = state.rmcp_upstream_clients().lock().await;
        let ttl = state.upstream_session_ttl();
        clients.retain(|_, cached| cached.last_used.elapsed() < ttl);
    }

    {
        let mut plans = state.resolved_tool_call_plans().lock().await;
        let ttl = state.tools_call_plan_ttl();
        plans.retain(|_, cached| cached.cached_at.elapsed() < ttl);
    }
}

fn spawn_local_cache_sweeper(state: AppState) {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            sweep_local_caches(&state).await;
        }
    });
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

fn pool_owner_key(state: &AppState, session_id: &str) -> String {
    format!("{}pool_owner:{session_id}", state.cache_prefix())
}

fn pool_http_channel(state: &AppState, owner_worker_id: &str) -> String {
    format!("{}pool_http:{owner_worker_id}", state.cache_prefix())
}

fn pool_http_response_channel(state: &AppState, response_id: &str) -> String {
    format!("{}pool_http_response:{response_id}", state.cache_prefix())
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
        .get::<_, Option<String>>(pool_owner_key(state, session_id))
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
    // Affinity forwarding keeps a session on the worker that already owns the
    // long-lived transport state. Requests are only forwarded when affinity is
    // enabled, Redis knows a different owner, and the current request is not
    // itself already an affinity-forwarded replay.
    if !state.affinity_core_enabled() || is_affinity_forwarded_request(incoming_headers) {
        return Ok(None);
    }

    let Some(owner_worker_id) = get_pool_session_owner(state, session_id).await else {
        return Ok(None);
    };

    let Some(redis_client) = state.redis_client.clone() else {
        return Ok(None);
    };

    state.runtime_stats().record_affinity_forward_attempt();
    let owner_channel = pool_http_channel(state, &owner_worker_id);
    let response_channel = pool_http_response_channel(state, &Uuid::new_v4().simple().to_string());
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
        error!("Rust MCP affinity payload serialization failed: {err}");
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({
                "detail": "Rust MCP affinity payload serialization failed",
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
                    "detail": "Timed out waiting for owner worker response",
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
    state.runtime_stats().record_affinity_forwarded_request();
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
        if !should_forward_response_header(lower.as_str()) {
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
            "detail": message,
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
    // The Redis event store keeps a bounded per-stream history plus an index
    // from event id -> (stream id, sequence number). That lets resume lookups
    // answer "replay everything after event X" without scanning all streams.
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
                json!({"detail": "Rust event store write failed"}),
            )
        })?;

    Ok(event_id)
}

async fn replay_events_from_rust_event_store(
    state: &AppState,
    request: EventStoreReplayRequest,
) -> Result<EventStoreReplayResponse, Response> {
    // Replay is intentionally tolerant. Missing index entries or replay points
    // older than the retained stream window return an empty replay rather than
    // surfacing a hard error to the public transport path.
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
                json!({"detail": "Rust event store replay lookup failed"}),
            )
        })?
    else {
        return Ok(EventStoreReplayResponse {
            stream_id: None,
            events: Vec::new(),
        });
    };

    let index_record: EventIndexRecord = serde_json::from_str(&index_payload).map_err(|err| {
        error!("Rust event store index decode failed: {err}");
        json_response(
            StatusCode::BAD_GATEWAY,
            json!({"detail": "Rust event store index decode failed"}),
        )
    })?;
    let meta_key = format!("{key_prefix}:{}:meta", index_record.stream_id);
    let events_key = format!("{key_prefix}:{}:events", index_record.stream_id);
    let messages_key = format!("{key_prefix}:{}:messages", index_record.stream_id);

    if let Some(start_seq) = redis
        .hget::<_, _, Option<i64>>(&meta_key, "start_seq")
        .await
        .map_err(|err| {
            error!("Rust event store meta lookup failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": "Rust event store meta lookup failed"}),
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
            error!("Rust event store replay scan failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({"detail": "Rust event store replay scan failed"}),
            )
        })?;

    let mut events = Vec::with_capacity(event_ids.len());
    for event_id in event_ids {
        let Some(message_json) = redis
            .hget::<_, _, Option<String>>(&messages_key, &event_id)
            .await
            .map_err(|err| {
                error!("Rust event store replay fetch failed: {err}");
                json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({"detail": "Rust event store replay fetch failed"}),
                )
            })?
        else {
            continue;
        };

        match serde_json::from_str::<Value>(&message_json) {
            Ok(message) => events.push(EventStoreReplayEvent { event_id, message }),
            Err(err) => {
                error!(
                    "Rust event store replay decode failed for stream {} event {}: {err}",
                    index_record.stream_id, event_id
                );
                return Err(json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({"detail": "Rust event store replay decode failed"}),
                ));
            }
        }
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
    // Session validation is intentionally strict:
    // - the session must exist
    // - server-scoped requests must stay on the original server
    // - the current caller must match the stored auth binding/owner
    // Only after that do we normalize the session/server headers that the
    // downstream Python transport bridge expects.
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
        state.runtime_stats().record_session_server_scope_mismatch();
        return Err(json_response(
            StatusCode::FORBIDDEN,
            json!({
                "detail": "Session access denied",
            }),
        ));
    }

    let auth_context = decode_internal_auth_context_from_headers_optional(incoming_headers);
    if let Err(reason) =
        runtime_session_access_outcome(&record, auth_context.as_ref(), incoming_headers)
    {
        state.runtime_stats().record_session_access_denial(reason);
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

fn runtime_session_access_outcome(
    record: &RuntimeSessionRecord,
    auth_context: Option<&InternalAuthContext>,
    incoming_headers: &HeaderMap,
) -> Result<(), SessionAccessDenyReason> {
    // The auth-binding fingerprint prevents a caller from reusing another
    // client's session identifier even when the email or visible scope appears
    // superficially compatible.
    if let Some(expected_fingerprint) = record.auth_binding_fingerprint.as_deref() {
        let Some(actual_fingerprint) = auth_binding_fingerprint(incoming_headers) else {
            return Err(SessionAccessDenyReason::MissingAuthBindingFingerprint);
        };
        if actual_fingerprint != expected_fingerprint {
            return Err(SessionAccessDenyReason::AuthBindingMismatch);
        }
    }

    let Some(owner_email) = record.owner_email.as_deref() else {
        return Ok(());
    };
    let Some(auth_context) = auth_context else {
        return Err(SessionAccessDenyReason::MissingAuthContext);
    };
    if auth_context.email.as_deref() == Some(owner_email) {
        Ok(())
    } else {
        Err(SessionAccessDenyReason::OwnerEmailMismatch)
    }
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
    // Accept both `mcp-session-id` (canonical per MCP Streamable HTTP) and
    // `x-mcp-session-id` (legacy alias the Python gateway already honours).
    // Keeping the two runtimes aligned avoids clients being accepted by one
    // and 405'd by the other when they migrate between them.
    incoming_headers
        .get("mcp-session-id")
        .or_else(|| incoming_headers.get("x-mcp-session-id"))
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
    // Session auth reuse is opt-in and conservative. Any missing or
    // unauthenticated signal clears the cached auth material so the next public
    // request will round-trip back through Python authentication.
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
    // The runtime tracks both sessions created by initialize responses and
    // client-provided session ids reused by the Python transport bridge so that
    // follow-up GET/POST/DELETE requests can be validated consistently.
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
    // This is a minimal SSE parser for upstream responses. It keeps only the
    // fields the runtime needs to preserve (`id`, `event`, `data`, `retry`) and
    // intentionally ignores comments and unknown fields.
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
    // Empty lines terminate the current SSE frame. Frames without any parsed
    // fields are treated as keep-alive noise and dropped.
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
    // Resumable GET /mcp replays events from the Rust event store first and
    // then tails the same stream by polling Redis for newly appended events.
    // The stream stops once the owning runtime session disappears.
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
            // Protocol versions are ISO dates (`YYYY-MM-DD`), so lexical
            // ordering matches chronological ordering for this gate.
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
    inject_runtime_capability_headers(
        &mut response,
        &[
            (SESSION_CORE_HEADER, true),
            (EVENT_STORE_HEADER, true),
            (RESUME_CORE_HEADER, true),
            (
                SESSION_AUTH_REUSE_HEADER,
                state.session_auth_reuse_enabled(),
            ),
            (LIVE_STREAM_CORE_HEADER, state.live_stream_core_enabled()),
        ],
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
    // Live stream mode keeps Python as the transport source of truth and has
    // Rust act as an SSE relay. Rust parses the upstream byte stream into SSE
    // frames so it can preserve event ids and attach its own runtime metadata.
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
        let mut buffer = BytesMut::new();
        let mut frame = PendingSseFrame::default();

        loop {
            match upstream_stream.next().await {
                Some(Ok(chunk)) => {
                    buffer.extend_from_slice(&chunk);

                    while let Some(newline_index) = buffer.iter().position(|byte| *byte == b'\n') {
                        let mut line_bytes = buffer.split_to(newline_index + 1);
                        if matches!(line_bytes.last(), Some(b'\n')) {
                            line_bytes.truncate(line_bytes.len().saturating_sub(1));
                        }
                        if matches!(line_bytes.last(), Some(b'\r')) {
                            line_bytes.truncate(line_bytes.len().saturating_sub(1));
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
    inject_runtime_capability_headers(
        &mut response,
        &[
            (LIVE_STREAM_CORE_HEADER, true),
            (SESSION_CORE_HEADER, state.session_core_enabled()),
            (EVENT_STORE_HEADER, state.event_store_enabled()),
            (RESUME_CORE_HEADER, state.resume_core_enabled()),
            (
                SESSION_AUTH_REUSE_HEADER,
                state.session_auth_reuse_enabled(),
            ),
        ],
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
    // Validate backend URL before making request
    state.validate_backend_url(backend_url, "Backend RPC URL")?;

    state
        .client
        .post(backend_url)
        .headers(build_forwarded_headers(&incoming_headers))
        .body(body)
        .send()
        .await
        .map_err(|err| {
            error!("backend MCP dispatch failed: {err}");
            backend_jsonrpc_error_response(None, "Backend MCP dispatch failed")
        })
}

async fn forward_transport_request(
    state: &AppState,
    method: reqwest::Method,
    mut incoming_headers: HeaderMap,
    public_path: String,
    uri: axum::http::Uri,
) -> Response {
    // This is the main transport router for GET/DELETE streamable-HTTP traffic.
    // It decides, in order:
    // - whether a runtime session must be validated
    // - whether the request is a resumable GET served by Rust event replay
    // - whether affinity should forward the request to another Rust worker
    // - whether live SSE streaming should be proxied directly by Rust
    // - otherwise, whether the request should fall through to Python's
    //   existing transport/session implementation
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
            if let Err(reason) =
                runtime_session_access_outcome(&record, auth_context.as_ref(), &incoming_headers)
            {
                state.runtime_stats().record_session_access_denial(reason);
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
            inject_runtime_capability_headers(
                &mut response,
                &[(AFFINITY_CORE_HEADER, state.affinity_core_enabled())],
            );
            return response;
        }
    }

    if method == reqwest::Method::GET
        && state.live_stream_core_enabled()
        && accepts_sse(&incoming_headers)
        && !incoming_headers.contains_key("last-event-id")
    {
        // ADR-052: Guard the live-stream relay with a 405 when we have no
        // session to anchor a passive SSE stream to. Two branches land here:
        //   (a) session_core is disabled globally — Rust has no session
        //       infrastructure to validate against.
        //   (b) session_core is enabled but no valid session id was presented
        //       (neither `Mcp-Session-Id`/`x-mcp-session-id` header nor
        //       `session_id` query parameter).
        // The 405 is spec-mandated, not a workaround: per MCP Streamable HTTP
        // ("Listening for messages from the server"), GET /mcp requires a
        // session id. The Python transport bridge enforces the same rule.
        //
        // What changed in ADR-052: the GET-with-session path below now
        // delivers real server-initiated messages (Python's GET handler
        // returns a Pub/Sub-backed SSE stream). The Rust relay was always
        // correctly designed; the empty-stream cascade that motivated the
        // #4205 405 was a downstream symptom of Python returning 405 for
        // *every* GET. With Python serving spec-conformant SSE, this relay
        // passes events through unchanged.
        //
        // Why 405 rather than 404/400: the `/mcp` path exists and the
        // request is syntactically valid; 405 + `Allow: POST, DELETE` tells
        // the client the resource is real and which verbs it supports,
        // which is what the MCP Streamable HTTP spec (2025-03-26 rev.)
        // sanctions here. Counter (total + session-core-disabled subcount)
        // and level-split logs let ops distinguish "no traffic" from "every
        // client rejected"; capability headers keep parity with the other
        // terminal responses in this function.
        if session_id.is_none() {
            let session_core_enabled = state.session_core_enabled();
            let reject_reason = if !session_core_enabled {
                TransportGetRejectReason::SessionCoreDisabled
            } else {
                TransportGetRejectReason::NoSessionId
            };
            state
                .runtime_stats()
                .record_transport_get_rejected_no_session(reject_reason);
            let detail = if session_core_enabled {
                "Passive SSE stream requires an Mcp-Session-Id from a prior initialize."
            } else {
                "Passive SSE stream not available: session management is disabled on this runtime."
            };
            // Log level split by reason: disabled session_core is an
            // operator-facing config condition (warn); missing session id is
            // routine behaviour from strict MCP clients probing before
            // `initialize` and would flood info-level logs (debug).
            match reject_reason {
                TransportGetRejectReason::SessionCoreDisabled => {
                    warn!(
                        path = %public_path,
                        session_core_enabled = session_core_enabled,
                        "rejecting passive-stream GET with 405 — session_core disabled"
                    );
                }
                TransportGetRejectReason::NoSessionId => {
                    debug!(
                        path = %public_path,
                        session_core_enabled = session_core_enabled,
                        "rejecting passive-stream GET with 405 — no session id presented"
                    );
                }
            }
            let mut response =
                json_response(StatusCode::METHOD_NOT_ALLOWED, json!({ "detail": detail }));
            response.headers_mut().insert(
                HeaderName::from_static("allow"),
                HeaderValue::from_static("POST, DELETE"),
            );
            inject_runtime_capability_headers(
                &mut response,
                &[
                    (SESSION_CORE_HEADER, session_core_enabled),
                    (EVENT_STORE_HEADER, state.event_store_enabled()),
                    (RESUME_CORE_HEADER, state.resume_core_enabled()),
                    (LIVE_STREAM_CORE_HEADER, state.live_stream_core_enabled()),
                    (AFFINITY_CORE_HEADER, state.affinity_core_enabled()),
                ],
            );
            return response;
        }

        return handle_live_stream_transport_request(
            state,
            &incoming_headers,
            &uri,
            session_id.as_deref(),
        );
    }

    // Session-less DELETE: the MCP Streamable HTTP spec frames DELETE as
    // "client-initiated termination — server MAY support, else 405". Without
    // a session id there is nothing to terminate; the spec-conformant answers
    // are 405 (this gateway does not honor the attempt) or 200/204 (treat as
    // a no-op). We pick 405 to match the GET-without-session symmetry in
    // this file and to give the client a clear `Allow` header.
    //
    // We probe the header (or query string) directly rather than the
    // ``session_id`` variable above: that variable is only populated when
    // Rust is validating sessions (``session_core_enabled``). In edge mode
    // Python validates sessions, so a request with a real ``Mcp-Session-Id``
    // header arrives here with ``session_id == None`` — and we still want
    // to forward such DELETEs to Python rather than reject them. Without
    // this branch DELETE without any session header falls through to the
    // generic backend-forward path and the Python SDK returns 400
    // "Missing session ID", which fails
    // `test_delete_mcp_terminates_session_or_405`.
    if method == reqwest::Method::DELETE
        && runtime_session_id_from_request(&incoming_headers, &uri).is_none()
    {
        let mut response = json_response(
            StatusCode::METHOD_NOT_ALLOWED,
            json!({
                "detail": "DELETE /mcp requires Mcp-Session-Id; without one there is no session to terminate."
            }),
        );
        response.headers_mut().insert(
            HeaderName::from_static("allow"),
            HeaderValue::from_static("POST, GET, DELETE"),
        );
        inject_runtime_capability_headers(
            &mut response,
            &[
                (SESSION_CORE_HEADER, state.session_core_enabled()),
                (EVENT_STORE_HEADER, state.event_store_enabled()),
                (RESUME_CORE_HEADER, state.resume_core_enabled()),
                (LIVE_STREAM_CORE_HEADER, state.live_stream_core_enabled()),
                (AFFINITY_CORE_HEADER, state.affinity_core_enabled()),
            ],
        );
        return response;
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
        inject_runtime_capability_headers(
            &mut response,
            &[
                (SESSION_CORE_HEADER, state.session_core_enabled()),
                (EVENT_STORE_HEADER, state.event_store_enabled()),
                (RESUME_CORE_HEADER, state.resume_core_enabled()),
                (LIVE_STREAM_CORE_HEADER, state.live_stream_core_enabled()),
                (AFFINITY_CORE_HEADER, state.affinity_core_enabled()),
            ],
        );
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
    inject_runtime_capability_headers(
        &mut response,
        &[
            (SESSION_CORE_HEADER, state.session_core_enabled()),
            (EVENT_STORE_HEADER, state.event_store_enabled()),
            (RESUME_CORE_HEADER, state.resume_core_enabled()),
            (LIVE_STREAM_CORE_HEADER, state.live_stream_core_enabled()),
            (AFFINITY_CORE_HEADER, state.affinity_core_enabled()),
        ],
    );
    response
}

fn start_runtime_operation_span(
    name: &'static str,
    incoming_headers: &HeaderMap,
    auth_context: Option<&InternalAuthContext>,
) -> (tracing::Span, bool) {
    let trace_context = trace_request_context(incoming_headers, auth_context);
    let current_span = tracing::Span::current();
    if !current_span.is_none() {
        let child_span = start_child_span(name, &trace_context);
        if !child_span.is_none() {
            return (child_span, false);
        }
    }

    (start_root_span(name, &trace_context), true)
}

fn parse_jsonrpc_request_payload(body: &Bytes) -> Option<Value> {
    serde_json::from_slice::<Value>(body).ok()
}

fn extract_jsonrpc_method(payload: Option<&Value>) -> Option<String> {
    payload
        .and_then(Value::as_object)
        .and_then(|value| value.get("method"))
        .and_then(Value::as_str)
        .map(str::to_string)
}

fn extract_jsonrpc_params(payload: Option<&Value>) -> Value {
    payload
        .and_then(Value::as_object)
        .and_then(|value| value.get("params"))
        .cloned()
        .unwrap_or_else(|| json!({}))
}

async fn forward_server_tools_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("tool.list", &incoming_headers, auth_context.as_ref());
    if is_root_span {
        set_langfuse_trace_name(&span, derive_langfuse_trace_name("tool.list", &[]));
    }
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&span, "server_id", server_id.to_string());
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP tools/list decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return backend_jsonrpc_error_response(
                    request_id.clone(),
                    "Backend MCP tools/list decode failed",
                );
            }
        };

        if status.is_success() {
            let tool_count = payload
                .get("tools")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "tool.count", tool_count);
            if is_output_capture_enabled("tool.list") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
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

    if let Err(response) = authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_tools_list_authz_url(),
        "tools/list",
    )
    .await
    {
        return response;
    }

    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("tool.list", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_langfuse_trace_name(&span, derive_langfuse_trace_name("tool.list", &[]));

    let span_for_body = span.clone();
    async move {
        match query_server_tools_list_from_db(state, &server_id, &auth_context).await {
            Ok(tools) => {
                set_span_attribute(&span_for_body, "tool.count", tools.len());
                if is_output_capture_enabled("tool.list") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&json!({ "tools": tools })),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": {
                            "tools": tools,
                        },
                    }),
                )
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
                error!(
                    "Rust MCP direct tools/list DB query failed: {err}; falling back to Python dispatcher"
                );
                forward_server_tools_list_to_backend(state, incoming_headers, request_id).await
            }
        }
    }
    .instrument(span)
    .await
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

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
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
            input_schema: normalize_tool_input_schema(row.get::<_, Option<Value>>("input_schema")),
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
    // Direct DB-backed reads are only used when Rust already has the trusted
    // auth context and Python authorizes the server-scoped method. Any missing
    // context or DB/read-shape mismatch falls back to the Python dispatcher.
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

    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("resource.list", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_langfuse_trace_name(&span, derive_langfuse_trace_name("resource.list", &[]));

    let span_for_body = span.clone();
    async move {
        match query_server_resources_list_from_db(state, &server_id, &auth_context).await {
            Ok(resources) => {
                set_span_attribute(&span_for_body, "resource.count", resources.len());
                if is_output_capture_enabled("resource.list") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&json!({ "resources": resources })),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": {
                            "resources": resources,
                        },
                    }),
                )
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
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
    .instrument(span)
    .await
}

async fn direct_server_resource_templates_list(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
) -> Response {
    // Resource template listing follows the same conservative pattern as
    // `resources/list`: trust Python for authz, use Rust for the common DB read
    // path, and fall back immediately when the local preconditions are missing.
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

    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("resource_template.list", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_langfuse_trace_name(
        &span,
        derive_langfuse_trace_name("resource_template.list", &[]),
    );

    let span_for_body = span.clone();
    async move {
        match query_server_resource_templates_list_from_db(state, &server_id, &auth_context).await {
            Ok(resource_templates) => {
                set_span_attribute(&span_for_body, "resource_template.count", resource_templates.len());
                if is_output_capture_enabled("resource_template.list") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&json!({ "resourceTemplates": resource_templates })),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": {
                            "resourceTemplates": resource_templates,
                        },
                    }),
                )
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
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
    .instrument(span)
    .await
}

async fn direct_server_prompts_list(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
) -> Response {
    // Prompt listing is safe to serve directly from Rust when visibility can be
    // expressed with a single DB query over the trusted auth context.
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

    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("prompt.list", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_langfuse_trace_name(&span, derive_langfuse_trace_name("prompt.list", &[]));

    let span_for_body = span.clone();
    async move {
        match query_server_prompts_list_from_db(state, &server_id, &auth_context).await {
            Ok(prompts) => {
                set_span_attribute(&span_for_body, "prompt.count", prompts.len());
                if is_output_capture_enabled("prompt.list") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&json!({ "prompts": prompts })),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": {
                            "prompts": prompts,
                        },
                    }),
                )
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
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
    .instrument(span)
    .await
}

async fn direct_server_resources_read(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Response {
    // `resources/read` is intentionally more conservative than list-style
    // methods. Rust only serves the read directly for simple stored-resource
    // rows; gateway-backed content, templates, ambiguous rows, or unsupported
    // shapes deliberately fall back to Python for parity.
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

    let authz_decision = match authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_resources_read_authz_url(),
        "resources/read",
    )
    .await
    {
        Ok(decision) => decision,
        Err(response) => return response,
    };
    if !authz_decision.direct_execution_eligible {
        debug!(
            "Rust MCP direct resources/read falling back to Python: {}",
            authz_decision
                .fallback_reason
                .as_deref()
                .unwrap_or("direct-execution-disabled")
        );
        return forward_resources_read_to_backend(state, incoming_headers, body, request_id).await;
    }

    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("resource.read", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_span_attribute(&span, "resource.uri", uri.to_string());
    set_langfuse_trace_name(
        &span,
        derive_langfuse_trace_name("resource.read", &[("resource.uri", uri.to_string())]),
    );
    if is_input_capture_enabled("resource.read") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&json!({ "uri": uri })),
        );
    }

    let span_for_body = span.clone();
    async move {
        match query_server_resource_read_from_db(state, &server_id, &auth_context, uri).await {
            Ok(Some(content)) => {
                if is_output_capture_enabled("resource.read") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&json!({ "contents": [content.clone()] })),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": {
                            "contents": [content],
                        },
                    }),
                )
            }
            Ok(None) => {
                set_span_error(
                    &span_for_body,
                    format!("Resource not found: {uri}"),
                    Some("ResourceNotFound"),
                );
                json_response(
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
                )
            }
            Err(RuntimeError::Config(reason)) if reason == "fallback-python" => {
                forward_resources_read_to_backend(state, incoming_headers, body, request_id).await
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
                error!(
                    "Rust MCP direct resources/read DB query failed: {err}; falling back to Python dispatcher"
                );
                forward_resources_read_to_backend(state, incoming_headers, body, request_id).await
            }
        }
    }
    .instrument(span)
    .await
}

async fn direct_server_prompts_get(
    state: &AppState,
    incoming_headers: HeaderMap,
    request_id: Option<Value>,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Response {
    // Rust serves the direct prompt/get path for the same conservative subset
    // as prompt eligibility detection: trusted server scope, authz approved by
    // Python, and a DB-backed prompt that can be returned without invoking an
    // upstream gateway or plugin hook chain.
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

    let Some(params) = request.params.as_object() else {
        return forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await;
    };

    let Some(name) = params
        .get("name")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    else {
        return forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await;
    };

    if let Err(response) = validate_prompt_get_arguments(params, request_id.as_ref()) {
        return response;
    }

    let authz_decision = match authorize_server_method_via_backend(
        state,
        &incoming_headers,
        request_id.clone(),
        state.backend_prompts_get_authz_url(),
        "prompts/get",
    )
    .await
    {
        Ok(decision) => decision,
        Err(response) => return response,
    };
    if !authz_decision.direct_execution_eligible {
        debug!(
            "Rust MCP direct prompts/get falling back to Python: {}",
            authz_decision
                .fallback_reason
                .as_deref()
                .unwrap_or("direct-execution-disabled")
        );
        return forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await;
    }

    let prompt_name = name.to_string();
    let prompt_arguments = params
        .get("arguments")
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}));
    let trace_context = trace_request_context(&incoming_headers, Some(&auth_context));
    let span = start_root_span("prompt.render", &trace_context);
    set_span_attribute(&span, "server_id", server_id.as_str());
    set_span_attribute(&span, "prompt.id", prompt_name.clone());
    set_span_attribute(
        &span,
        "arguments_count",
        prompt_arguments.as_object().map_or(0, serde_json::Map::len),
    );
    set_langfuse_trace_name(
        &span,
        derive_langfuse_trace_name("prompt.render", &[("prompt.id", prompt_name.clone())]),
    );
    if is_input_capture_enabled("prompt.render") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&prompt_arguments),
        );
    }

    let span_for_body = span.clone();
    async move {
        if let Ok(Some((canonical_name, prompt_version))) =
            query_server_prompt_observability_metadata(
                state,
                &server_id,
                &auth_context,
                &prompt_name,
            )
                .await
        {
            set_span_attribute(
                &span_for_body,
                "langfuse.observation.prompt.name",
                canonical_name,
            );
            if let Some(prompt_version) = prompt_version {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.prompt.version",
                    prompt_version,
                );
            }
        }

        match query_server_prompt_get_from_db(state, &server_id, &auth_context, &prompt_name).await {
            Ok(Some(payload)) => {
                set_span_attribute(&span_for_body, "success", true);
                let messages_count = payload
                    .get("messages")
                    .and_then(Value::as_array)
                    .map_or(0, Vec::len);
                set_span_attribute(&span_for_body, "messages.count", messages_count);
                if is_output_capture_enabled("prompt.render") {
                    set_span_attribute(
                        &span_for_body,
                        "langfuse.observation.output",
                        serialize_trace_payload(&payload),
                    );
                }
                json_response(
                    StatusCode::OK,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "result": payload,
                    }),
                )
            }
            Ok(None) => {
                set_span_attribute(&span_for_body, "success", false);
                set_span_error(
                    &span_for_body,
                    format!("Prompt not found: {prompt_name}"),
                    Some("PromptNotFoundError"),
                );
                json_response(
                    jsonrpc_response_status(StatusCode::NOT_FOUND),
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32002,
                            "message": "Prompt not found",
                            "data": {"name": prompt_name.clone()},
                        },
                    }),
                )
            }
            Err(RuntimeError::Config(reason)) if reason == "fallback-python" => {
                debug!(
                    "Rust MCP direct prompts/get falling back to Python dispatcher for prompt '{prompt_name}'"
                );
                forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await
            }
            Err(err) => {
                set_span_error(&span_for_body, err.to_string(), Some("RuntimeError"));
                error!(
                    "Rust MCP direct prompts/get DB query failed: {err}; falling back to Python dispatcher"
                );
                forward_prompts_get_to_backend(state, incoming_headers, body, request_id).await
            }
        }
    }
    .instrument(span)
    .await
}

async fn query_server_resources_list_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
) -> Result<Vec<Value>, RuntimeError> {
    // Visibility is derived from the same normalized auth context Python
    // produced: unrestricted admins with `teams=null` bypass filters; all other
    // callers see public rows plus any owner/team rows implied by the token.
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
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

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
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

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
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
    // This helper returns `fallback-python` for any case where Rust cannot
    // reproduce Python behavior exactly: duplicate matches, gateway-backed
    // resources, templates, or rows without directly serializable content.
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
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

#[allow(dead_code)]
async fn query_server_prompt_get_from_db(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
    name: &str,
) -> Result<Option<Value>, RuntimeError> {
    // Prompt reads are intentionally normalized into the MCP prompt result
    // shape expected by clients so the direct Rust path can substitute for the
    // Python dispatcher without changing the wire contract. Gateway-backed
    // prompts without a local template still fall back to Python so upstream
    // execution semantics remain authoritative.
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
    let row = if is_unrestricted_admin {
        client
            .query_opt(
                "SELECT p.template, p.description, p.gateway_id \
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
                "SELECT p.template, p.description, p.gateway_id \
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

    let gateway_id = row.get::<_, Option<String>>("gateway_id");
    let template = row.get::<_, String>("template");
    if gateway_id.is_some() && template.is_empty() {
        return Err(RuntimeError::Config("fallback-python".to_string()));
    }

    Ok(Some(json!({
        "description": row.get::<_, Option<String>>("description"),
        "messages": [{
            "role": "user",
            "content": {
                "type": "text",
                "text": template,
            }
        }],
    })))
}

async fn query_server_prompt_observability_metadata(
    state: &AppState,
    server_id: &str,
    auth_context: &InternalAuthContext,
    name_or_id: &str,
) -> Result<Option<(String, Option<i64>)>, RuntimeError> {
    let pool = state
        .db_pool()
        .ok_or_else(|| RuntimeError::Config("Rust MCP DB pool is not configured".to_string()))?;
    let client = pool.get().await.map_err(|err| {
        RuntimeError::Config(format!("failed to acquire Rust MCP DB connection: {err}"))
    })?;

    let is_unrestricted_admin = auth_context.effective_is_admin() && auth_context.teams.is_none();
    let row = if is_unrestricted_admin {
        client
            .query_opt(
                "SELECT p.name, p.version \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 \
                   AND (p.name = $2 OR p.id = $2) \
                   AND p.enabled = TRUE",
                &[&server_id, &name_or_id],
            )
            .await?
    } else {
        let team_ids = auth_context.teams.clone().unwrap_or_default();
        let is_public_only = auth_context.teams.as_ref().is_none_or(Vec::is_empty);
        let allow_owner_access = !is_public_only && auth_context.email.is_some();
        let owner_email = auth_context.email.as_deref();

        client
            .query_opt(
                "SELECT p.name, p.version \
                 FROM prompts p \
                 JOIN server_prompt_association spa ON p.id = spa.prompt_id \
                 WHERE spa.server_id = $1 \
                   AND (p.name = $2 OR p.id = $2) \
                   AND p.enabled = TRUE \
                   AND ( \
                        p.visibility = 'public' \
                        OR ($3::bool AND p.owner_email = $4) \
                        OR (COALESCE(array_length($5::text[], 1), 0) > 0 AND p.team_id = ANY($5::text[]) AND p.visibility IN ('team', 'public')) \
                   )",
                &[&server_id, &name_or_id, &allow_owner_access, &owner_email, &team_ids],
            )
            .await?
    };

    Ok(row.map(|row| {
        (
            row.get::<_, String>("name"),
            row.get::<_, Option<i32>>("version").map(i64::from),
        )
    }))
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

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
struct DirectExecutionAuthorization {
    #[serde(
        default = "default_direct_execution_eligible",
        alias = "directExecutionEligible"
    )]
    direct_execution_eligible: bool,
    #[serde(default, alias = "fallbackReason")]
    fallback_reason: Option<String>,
}

impl Default for DirectExecutionAuthorization {
    fn default() -> Self {
        Self {
            direct_execution_eligible: true,
            fallback_reason: None,
        }
    }
}

const fn default_direct_execution_eligible() -> bool {
    true
}

async fn authorize_server_method_via_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request_id: Option<Value>,
    url: &str,
    method_label: &str,
) -> Result<DirectExecutionAuthorization, Response> {
    state.validate_backend_url(url, &format!("Backend {method_label} authz URL"))?;

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
                        "data": CLIENT_ERROR_DETAIL,
                    }
                }),
            )
        })?;

    if backend_response.status().is_success() {
        if backend_response.status() == StatusCode::NO_CONTENT {
            return Ok(DirectExecutionAuthorization::default());
        }

        let payload = backend_response.bytes().await.map_err(|err| {
            error!("backend MCP {method_label} authz response read failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": format!("Backend MCP {method_label} authz read failed"),
                        "data": CLIENT_ERROR_DETAIL,
                    }
                }),
            )
        })?;

        if payload.is_empty() {
            return Ok(DirectExecutionAuthorization::default());
        }

        return serde_json::from_slice::<DirectExecutionAuthorization>(&payload).map_err(|err| {
            error!("backend MCP {method_label} authz success decode failed: {err}");
            json_response(
                StatusCode::BAD_GATEWAY,
                json!({
                    "jsonrpc": JSONRPC_VERSION,
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": format!("Backend MCP {method_label} authz success decode failed"),
                        "data": CLIENT_ERROR_DETAIL,
                    }
                }),
            )
        });
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
                        "data": CLIENT_ERROR_DETAIL,
                    }
                }),
            ));
        }
    };

    Err(response_from_json_with_headers(
        jsonrpc_response_status(status),
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
    // The internal auth header is produced by Python and transported as a
    // base64url-encoded JSON blob so Rust can validate session ownership
    // without trusting any client-supplied identity fields directly.
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
    let request_payload = parse_jsonrpc_request_payload(&body);
    let method_name = extract_jsonrpc_method(request_payload.as_ref())
        .unwrap_or_else(|| "notifications/unknown".to_string());
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) = start_runtime_operation_span(
        "notification.forward",
        &incoming_headers,
        auth_context.as_ref(),
    );
    set_span_attribute(&span, "mcp.method", method_name.clone());
    if is_root_span {
        set_langfuse_trace_name(
            &span,
            format!("Notification: {}", method_name.replace('/', ".")),
        );
    }
    if is_input_capture_enabled("notification.forward") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_to_backend(state, incoming_headers, body).await {
            Ok(response) => response,
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP notification dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if status.is_success() {
            return empty_response(StatusCode::ACCEPTED);
        }
        set_span_error(
            &span_for_body,
            format!("Backend MCP notification returned status {status}"),
            Some("RuntimeError"),
        );

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
}

async fn forward_initialized_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let request_payload = parse_jsonrpc_request_payload(&body);
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) = start_runtime_operation_span(
        "notification.initialized",
        &incoming_headers,
        auth_context.as_ref(),
    );
    set_span_attribute(&span, "mcp.method", "notifications/initialized");
    if is_root_span {
        set_langfuse_trace_name(&span, "notification.initialized");
    }
    if is_input_capture_enabled("notification.initialized") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_to_backend_url(
            state,
            state.backend_notifications_initialized_url(),
            incoming_headers,
            body,
        )
        .await
        {
            Ok(response) => response,
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP notifications/initialized dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if status.is_success() {
            return empty_response(StatusCode::ACCEPTED);
        }
        set_span_error(
            &span_for_body,
            format!("Backend MCP notifications/initialized returned status {status}"),
            Some("RuntimeError"),
        );

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
}

async fn forward_message_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let request_payload = parse_jsonrpc_request_payload(&body);
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) = start_runtime_operation_span(
        "notification.message",
        &incoming_headers,
        auth_context.as_ref(),
    );
    set_span_attribute(&span, "mcp.method", "notifications/message");
    if is_root_span {
        set_langfuse_trace_name(&span, "notification.message");
    }
    if is_input_capture_enabled("notification.message") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_to_backend_url(
            state,
            state.backend_notifications_message_url(),
            incoming_headers,
            body,
        )
        .await
        {
            Ok(response) => response,
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP notifications/message dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if status.is_success() {
            return empty_response(StatusCode::ACCEPTED);
        }
        set_span_error(
            &span_for_body,
            format!("Backend MCP notifications/message returned status {status}"),
            Some("RuntimeError"),
        );

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
}

async fn forward_resources_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("resource.list", &incoming_headers, auth_context.as_ref());
    if is_root_span {
        set_langfuse_trace_name(&span, derive_langfuse_trace_name("resource.list", &[]));
    }
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&span, "server_id", server_id.to_string());
    }

    let span_for_body = span.clone();
    async move {
        let backend_response =
            match send_resources_list_to_backend(state, incoming_headers, body).await {
                Ok(response) => response,
                Err(response) => return response,
            };

        let status = backend_response.status();
        let backend_headers = backend_response.headers().clone();
        let payload: Value = match backend_response.json().await {
            Ok(payload) => payload,
            Err(err) => {
                error!("backend MCP resources/list response decode failed: {err}");
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP resources/list decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP resources/list decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            let resource_count = payload
                .get("resources")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "resource.count", resource_count);
            if is_output_capture_enabled("resource.list") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_resources_read_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let resource_uri = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("uri"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("resource.read", &incoming_headers, auth_context.as_ref());
    if let Some(uri) = resource_uri.clone() {
        set_span_attribute(&span, "resource.uri", uri.clone());
        if is_root_span {
            set_langfuse_trace_name(
                &span,
                derive_langfuse_trace_name("resource.read", &[("resource.uri", uri)]),
            );
        }
    } else if is_root_span {
        set_langfuse_trace_name(&span, derive_langfuse_trace_name("resource.read", &[]));
    }
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&span, "server_id", server_id.to_string());
    }
    if is_input_capture_enabled("resource.read")
        && let Some(resource_uri) = resource_uri.clone()
    {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&json!({"uri": resource_uri})),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response =
            match send_resources_read_to_backend(state, incoming_headers, body).await {
                Ok(response) => response,
                Err(response) => return response,
            };

        let status = backend_response.status();
        let backend_headers = backend_response.headers().clone();
        let payload: Value = match backend_response.json().await {
            Ok(payload) => payload,
            Err(err) => {
                error!("backend MCP resources/read response decode failed: {err}");
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP resources/read decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP resources/read decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            let content_count = payload
                .get("contents")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "content.count", content_count);
            if is_output_capture_enabled("resource.read") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::NOT_FOUND => "ResourceNotFoundError",
                StatusCode::UNPROCESSABLE_ENTITY => "ResourceReadError",
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_resources_subscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let resource_uri = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("uri"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, _) = start_runtime_operation_span(
        "resource.subscribe",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if let Some(uri) = resource_uri.clone() {
        set_span_attribute(&span, "resource.uri", uri.clone());
    }
    if is_input_capture_enabled("resource.subscribe")
        && let Some(resource_uri) = resource_uri.clone()
    {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&json!({"uri": resource_uri})),
        );
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP resources/subscribe decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP resources/subscribe decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            if is_output_capture_enabled("resource.subscribe") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_resources_unsubscribe_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let resource_uri = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("uri"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, _) = start_runtime_operation_span(
        "resource.unsubscribe",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if let Some(uri) = resource_uri.clone() {
        set_span_attribute(&span, "resource.uri", uri.clone());
    }
    if is_input_capture_enabled("resource.unsubscribe")
        && let Some(resource_uri) = resource_uri.clone()
    {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&json!({"uri": resource_uri})),
        );
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP resources/unsubscribe decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP resources/unsubscribe decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            if is_output_capture_enabled("resource.unsubscribe") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_resource_templates_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) = start_runtime_operation_span(
        "resource_template.list",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if is_root_span {
        set_langfuse_trace_name(
            &span,
            derive_langfuse_trace_name("resource_template.list", &[]),
        );
    }
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&span, "server_id", server_id.to_string());
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP resources/templates/list decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP resources/templates/list decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            let template_count = payload
                .get("resourceTemplates")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "resource_template.count", template_count);
            if is_output_capture_enabled("resource_template.list") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_roots_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let trace_context = trace_request_context(&incoming_headers, auth_context.as_ref());
    let span = start_root_span("root.list", &trace_context);
    set_langfuse_trace_name(&span, derive_langfuse_trace_name("root.list", &[]));

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_roots_list_to_backend(state, incoming_headers, body).await
        {
            Ok(response) => response,
            Err(response) => return response,
        };

        let status = backend_response.status();
        let backend_headers = backend_response.headers().clone();
        let payload: Value = match backend_response.json().await {
            Ok(payload) => payload,
            Err(err) => {
                error!("backend MCP roots/list response decode failed: {err}");
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP roots/list decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP roots/list decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            let root_count = payload
                .get("roots")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "root.count", root_count);
            if is_output_capture_enabled("root.list") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some("RuntimeError"));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_prompts_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) =
        start_runtime_operation_span("prompt.list", &incoming_headers, auth_context.as_ref());
    if is_root_span {
        set_langfuse_trace_name(&span, derive_langfuse_trace_name("prompt.list", &[]));
    }
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&span, "server_id", server_id.to_string());
    }

    let span_for_body = span.clone();
    async move {
        let backend_response =
            match send_prompts_list_to_backend(state, incoming_headers, body).await {
                Ok(response) => response,
                Err(response) => return response,
            };

        let status = backend_response.status();
        let backend_headers = backend_response.headers().clone();
        let payload: Value = match backend_response.json().await {
            Ok(payload) => payload,
            Err(err) => {
                error!("backend MCP prompts/list response decode failed: {err}");
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP prompts/list decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP prompts/list decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            let prompt_count = payload
                .get("prompts")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "success", true);
            set_span_attribute(&span_for_body, "prompt.count", prompt_count);
            if is_output_capture_enabled("prompt.list") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_prompts_get_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let prompt_name = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("name"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let prompt_arguments = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("arguments"))
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}));
    let server_id = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let trace_context = trace_request_context(&incoming_headers, auth_context.as_ref());
    let span = start_root_span("prompt.render", &trace_context);
    if let Some(prompt_name) = prompt_name.clone() {
        set_span_attribute(&span, "prompt.id", prompt_name.clone());
        set_langfuse_trace_name(
            &span,
            derive_langfuse_trace_name("prompt.render", &[("prompt.id", prompt_name)]),
        );
    } else {
        set_langfuse_trace_name(&span, derive_langfuse_trace_name("prompt.render", &[]));
    }
    if let Some(server_id) = &server_id {
        set_span_attribute(&span, "server_id", server_id.clone());
    }
    set_span_attribute(
        &span,
        "arguments_count",
        prompt_arguments.as_object().map_or(0, serde_json::Map::len),
    );
    if is_input_capture_enabled("prompt.render") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&prompt_arguments),
        );
    }

    let span_for_body = span.clone();
    async move {
        if let (Some(server_id), Some(auth_context), Some(prompt_name)) = (
            server_id.as_deref(),
            auth_context.as_ref(),
            prompt_name.as_deref(),
        ) && let Ok(Some((canonical_name, prompt_version))) =
            query_server_prompt_observability_metadata(state, server_id, auth_context, prompt_name)
                .await
        {
            set_span_attribute(
                &span_for_body,
                "langfuse.observation.prompt.name",
                canonical_name,
            );
            if let Some(prompt_version) = prompt_version {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.prompt.version",
                    prompt_version,
                );
            }
        }

        let backend_response =
            match send_prompts_get_to_backend(state, incoming_headers, body).await {
                Ok(response) => response,
                Err(response) => return response,
            };

        let status = backend_response.status();
        let backend_headers = backend_response.headers().clone();
        let payload: Value = match backend_response.json().await {
            Ok(payload) => payload,
            Err(err) => {
                error!("backend MCP prompts/get response decode failed: {err}");
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP prompts/get decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP prompts/get decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            let messages_count = payload
                .get("messages")
                .and_then(Value::as_array)
                .map_or(0, Vec::len);
            set_span_attribute(&span_for_body, "messages.count", messages_count);
            if is_output_capture_enabled("prompt.render") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            let error_type = match status {
                StatusCode::NOT_FOUND => "PromptNotFoundError",
                StatusCode::UNPROCESSABLE_ENTITY => "PromptError",
                StatusCode::FORBIDDEN => "PermissionDenied",
                _ => "RuntimeError",
            };
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some(error_type));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_completion_complete_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let completion_params = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .cloned()
        .unwrap_or_else(|| json!({}));
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, _) = start_runtime_operation_span(
        "completion.complete",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if is_input_capture_enabled("completion.complete") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&completion_params),
        );
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP completion/complete decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP completion/complete decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            if is_output_capture_enabled("completion.complete") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some("RuntimeError"));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_sampling_create_message_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let sampling_params = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .cloned()
        .unwrap_or_else(|| json!({}));
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, _) = start_runtime_operation_span(
        "sampling.create_message",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if is_input_capture_enabled("sampling.create_message") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&sampling_params),
        );
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP sampling/createMessage decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP sampling/createMessage decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            if is_output_capture_enabled("sampling.create_message") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some("RuntimeError"));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_logging_set_level_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
    request_id: Option<Value>,
) -> Response {
    let request_payload = serde_json::from_slice::<Value>(&body).ok();
    let requested_level = request_payload
        .as_ref()
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("params"))
        .and_then(Value::as_object)
        .and_then(|params| params.get("level"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, _) = start_runtime_operation_span(
        "logging.set_level",
        &incoming_headers,
        auth_context.as_ref(),
    );
    if let Some(level) = requested_level.clone() {
        set_span_attribute(&span, "logging.level", level);
    }
    if is_input_capture_enabled("logging.set_level")
        && let Some(request_payload) = request_payload
            .as_ref()
            .and_then(Value::as_object)
            .and_then(|payload| payload.get("params"))
            .cloned()
    {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_payload),
        );
    }

    let span_for_body = span.clone();
    async move {
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
                set_span_error(
                    &span_for_body,
                    format!("Backend MCP logging/setLevel decode failed: {err}"),
                    Some("RuntimeError"),
                );
                return json_response(
                    StatusCode::BAD_GATEWAY,
                    json!({
                        "jsonrpc": JSONRPC_VERSION,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "Backend MCP logging/setLevel decode failed",
                            "data": CLIENT_ERROR_DETAIL,
                        }
                    }),
                );
            }
        };

        if status.is_success() {
            set_span_attribute(&span_for_body, "success", true);
            if is_output_capture_enabled("logging.set_level") {
                set_span_attribute(
                    &span_for_body,
                    "langfuse.observation.output",
                    serialize_trace_payload(&payload),
                );
            }
        } else {
            let error_message = payload
                .get("message")
                .and_then(Value::as_str)
                .map_or_else(|| payload.to_string(), str::to_string);
            set_span_attribute(&span_for_body, "success", false);
            set_span_error(&span_for_body, error_message, Some("RuntimeError"));
        }

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

        response_from_json_with_headers(
            jsonrpc_response_status(status),
            response_payload,
            &backend_headers,
        )
    }
    .instrument(span)
    .await
}

async fn forward_cancelled_notification_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
    body: Bytes,
) -> Response {
    let request_payload = parse_jsonrpc_request_payload(&body);
    let request_params = extract_jsonrpc_params(request_payload.as_ref());
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let (span, is_root_span) = start_runtime_operation_span(
        "notification.cancelled",
        &incoming_headers,
        auth_context.as_ref(),
    );
    set_span_attribute(&span, "mcp.method", "notifications/cancelled");
    if is_root_span {
        set_langfuse_trace_name(&span, "notification.cancelled");
    }
    if is_input_capture_enabled("notification.cancelled") {
        set_span_attribute(
            &span,
            "langfuse.observation.input",
            serialize_trace_payload(&request_params),
        );
    }

    let span_for_body = span.clone();
    async move {
        let backend_response = match send_to_backend_url(
            state,
            state.backend_notifications_cancelled_url(),
            incoming_headers,
            body,
        )
        .await
        {
            Ok(response) => response,
            Err(response) => {
                set_span_error(
                    &span_for_body,
                    "Backend MCP notifications/cancelled dispatch failed",
                    Some("RuntimeError"),
                );
                return response;
            }
        };

        let status = backend_response.status();
        set_span_attribute(&span_for_body, "success", status.is_success());
        if status.is_success() {
            return empty_response(StatusCode::ACCEPTED);
        }
        set_span_error(
            &span_for_body,
            format!("Backend MCP notifications/cancelled returned status {status}"),
            Some("RuntimeError"),
        );

        response_from_backend(backend_response)
    }
    .instrument(span)
    .await
}

async fn send_transport_to_backend(
    state: &AppState,
    method: reqwest::Method,
    incoming_headers: &HeaderMap,
    uri: &axum::http::Uri,
    body: Option<Bytes>,
    session_validated: bool,
) -> Result<reqwest::Response, Response> {
    // Generic transport bridge to Python. When Rust already validated the
    // runtime session, it marks that fact in forwarded headers so Python can
    // skip repeating the same session-ownership check on the internal hop.
    let target_url = build_backend_transport_url(state.backend_transport_url(), uri);

    // Validate backend URL before making request
    state.validate_backend_url(&target_url, "Backend transport URL")?;

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
                "data": CLIENT_ERROR_DETAIL,
            }),
        )
    })
}

async fn send_session_delete_to_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    session_validated: bool,
) -> Result<reqwest::Response, Response> {
    let target_url = derive_backend_session_delete_url(state.backend_rpc_url());

    // Validate backend URL before making request
    state.validate_backend_url(&target_url, "Backend session delete URL")?;

    state
        .client
        .delete(target_url)
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
                    "data": CLIENT_ERROR_DETAIL,
                }),
            )
        })
}

async fn send_tools_list_to_backend(
    state: &AppState,
    incoming_headers: HeaderMap,
) -> Result<reqwest::Response, Response> {
    // The helpers below are thin, method-specific bridges to Python's internal
    // MCP handlers. They keep the runtime's public response shaping separate
    // from the actual HTTP dispatch and error translation.
    let url = state.backend_tools_list_url();
    state.validate_backend_url(url, "Backend tools/list URL")?;

    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_resources_list_url();
    state.validate_backend_url(url, "Backend resources/list URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_resources_read_url();
    state.validate_backend_url(url, "Backend resources/read URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_resources_subscribe_url();
    state.validate_backend_url(url, "Backend resources/subscribe URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_resources_unsubscribe_url();
    state.validate_backend_url(url, "Backend resources/unsubscribe URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_resource_templates_list_url();
    state.validate_backend_url(url, "Backend resources/templates/list URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_roots_list_url();
    state.validate_backend_url(url, "Backend roots/list URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_completion_complete_url();
    state.validate_backend_url(url, "Backend completion/complete URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_sampling_create_message_url();
    state.validate_backend_url(url, "Backend sampling/createMessage URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_logging_set_level_url();
    state.validate_backend_url(url, "Backend logging/setLevel URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_prompts_list_url();
    state.validate_backend_url(url, "Backend prompts/list URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    let url = state.backend_prompts_get_url();
    state.validate_backend_url(url, "Backend prompts/get URL")?;
    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
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
    // `tools/call` is the main Rust fast path. The runtime first asks Python to
    // resolve whether the call is eligible for direct execution. Only eligible
    // streamable-http targets stay in Rust; everything else falls back to the
    // existing Python implementation.
    let auth_context = decode_internal_auth_context_from_headers_optional(&incoming_headers);
    let trace_context = trace_request_context(&incoming_headers, auth_context.as_ref());
    let root_span = start_root_span("tool.invoke", &trace_context);
    let requested_tool_name = request
        .params
        .as_object()
        .and_then(|params| params.get("name"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let requested_arguments = request
        .params
        .as_object()
        .and_then(|params| params.get("arguments"))
        .filter(|value| value.is_object())
        .cloned()
        .unwrap_or_else(|| json!({}));

    if let Some(tool_name) = requested_tool_name.clone() {
        set_span_attribute(&root_span, "tool.name", tool_name.clone());
        set_langfuse_trace_name(
            &root_span,
            derive_langfuse_trace_name("tool.invoke", &[("tool.name", tool_name)]),
        );
    }
    set_span_attribute(
        &root_span,
        "arguments_count",
        requested_arguments
            .as_object()
            .map_or(0, serde_json::Map::len),
    );
    set_span_attribute(&root_span, "has_headers", !incoming_headers.is_empty());
    if let Some(server_id) = incoming_headers
        .get("x-contextforge-server-id")
        .and_then(|value| value.to_str().ok())
    {
        set_span_attribute(&root_span, "server_id", server_id.to_string());
    }
    if is_input_capture_enabled("tool.invoke") {
        set_span_attribute(
            &root_span,
            "langfuse.observation.input",
            serialize_trace_payload(&requested_arguments),
        );
    }

    let root_span_for_body = root_span.clone();
    let trace_context_for_body = trace_context.clone();
    async move {
        let lookup_span = start_child_span("tool.lookup", &trace_context_for_body);
        if let Some(tool_name) = requested_tool_name.clone() {
            set_span_attribute(&lookup_span, "tool.name", tool_name);
        }
        let plan = match resolve_tools_call(state, &incoming_headers, &request, body.clone())
            .instrument(lookup_span)
            .await
        {
            Ok(plan) => plan,
            Err(ResolveToolsCallError::JsonRpcError { payload, headers }) => {
                let error_message = payload
                    .get("error")
                    .and_then(Value::as_object)
                    .and_then(|error| error.get("message"))
                    .and_then(Value::as_str)
                    .map_or_else(|| payload.to_string(), str::to_string);
                set_span_attribute(&root_span_for_body, "success", false);
                set_span_error(
                    &root_span_for_body,
                    error_message,
                    Some(tools_call_error_type_from_payload(&payload)),
                );
                return response_from_json_with_headers(StatusCode::OK, payload, &headers);
            }
            Err(ResolveToolsCallError::Fallback(err)) => {
                warn!("Rust MCP direct tools/call resolve fallback: {err}");
                return forward_tools_call_to_backend(
                    state,
                    incoming_headers.clone(),
                    body.clone(),
                )
                .await;
            }
        };

        if let Some(tool_id) = plan.tool_id.clone() {
            set_span_attribute(&root_span_for_body, "tool.id", tool_id);
        }
        if let Some(gateway_id) = plan.gateway_id.clone() {
            set_span_attribute(&root_span_for_body, "tool.gateway_id", gateway_id);
        }
        if let Some(server_id) = plan.server_id.clone() {
            set_span_attribute(&root_span_for_body, "server_id", server_id);
        }

        if !plan.eligible || !matches!(plan.transport.as_deref(), Some("streamablehttp" | "sse")) {
            if let Some(reason) = plan.fallback_reason.as_deref() {
                info!("Rust MCP direct tools/call falling back to Python: {reason}");
                set_span_attribute(
                    &root_span_for_body,
                    "contextforge.rust.fallback_reason",
                    reason.to_string(),
                );
            }
            return forward_tools_call_to_backend(state, incoming_headers.clone(), body.clone())
                .await;
        }

        match execute_tools_call_direct(
            state,
            &incoming_headers,
            &request,
            &plan,
            &trace_context_for_body,
        )
        .await
        {
            Ok(response) => response,
            Err(err) => {
                warn!("Rust MCP direct tools/call execution fallback: {err}");
                set_span_attribute(
                    &root_span_for_body,
                    "contextforge.rust.execution_fallback",
                    err.clone(),
                );
                let mut fallback_headers = incoming_headers.clone();
                // Tell Python that pre-invoke hooks already ran during /resolve so
                // invoke_tool() can skip re-executing them on the fallback path.
                if plan.has_pre_invoke_hooks {
                    fallback_headers.insert(
                        HeaderName::from_static("x-contextforge-pre-invoke-ran"),
                        HeaderValue::from_static("true"),
                    );
                }
                forward_tools_call_to_backend(state, fallback_headers, body.clone()).await
            }
        }
    }
    .instrument(root_span)
    .await
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
    let url = state.backend_tools_call_resolve_url();
    state
        .validate_backend_url(url, "Backend tools/call/resolve URL")
        .map_err(|_| {
            ResolveToolsCallError::Fallback("Backend URL validation failed".to_string())
        })?;

    let response = state
        .client
        .post(url)
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

    let mut plan =
        serde_json::from_slice::<ResolvedMcpToolCallPlan>(&response_body).map_err(|err| {
            if let Ok(payload) = serde_json::from_slice::<Value>(&response_body)
                && payload.get("jsonrpc") == Some(&Value::String(JSONRPC_VERSION.to_string()))
                && payload.get("error").is_some()
            {
                return ResolveToolsCallError::JsonRpcError { payload, headers };
            }
            ResolveToolsCallError::Fallback(format!("resolve decode failed: {err}"))
        })?;
    prepare_resolved_tools_call_plan(&mut plan).map_err(ResolveToolsCallError::Fallback)?;
    Ok(plan)
}

async fn resolve_tools_call(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    body: Bytes,
) -> Result<ResolvedMcpToolCallPlan, ResolveToolsCallError> {
    // Plan resolution is cached by the resolved request shape and selected
    // forwarded headers. This keeps steady-state tools/call traffic off Python
    // resolve requests when the upstream target is stable.
    let cache_key = build_tools_call_plan_cache_key(incoming_headers, request)
        .map_err(ResolveToolsCallError::Fallback)?;
    {
        let mut cached_plans = state.resolved_tool_call_plans().lock().await;
        if let Some(cached) = cached_plans.get_mut(&cache_key) {
            if cached.cached_at.elapsed() < state.tools_call_plan_ttl() {
                cached.cached_at = Instant::now();
                return Ok(cached.plan.clone());
            }
            cached_plans.remove(&cache_key);
        }
    }

    let plan = resolve_tools_call_plan_via_backend(state, incoming_headers, body).await?;
    // Do not cache plans that ran pre-invoke hooks — hook results depend on
    // per-call arguments (e.g. wxo_connection_id) and must be resolved fresh.
    if plan.eligible
        && matches!(plan.transport.as_deref(), Some("streamablehttp" | "sse"))
        && !plan.has_pre_invoke_hooks
    {
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
    let url = state.backend_tools_call_url();
    state.validate_backend_url(url, "Backend tools/call URL")?;

    state
        .client
        .post(url)
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
                        "data": CLIENT_ERROR_DETAIL,
                    }
                }),
            )
        })
}

async fn send_tools_call_metric_to_backend(
    state: &AppState,
    incoming_headers: &HeaderMap,
    payload: &ToolsCallMetricRecordRequest,
) -> Result<(), String> {
    let url = state.backend_tools_call_metric_url();
    state
        .validate_backend_url(url, "Backend tools/call/metric URL")
        .map_err(|_| "Backend URL validation failed".to_string())?;

    let response = state
        .client
        .post(url)
        .headers(build_forwarded_headers(incoming_headers))
        .json(payload)
        .send()
        .await
        .map_err(|err| format!("tools/call metric writeback failed: {err}"))?;

    if response.status().is_success() {
        Ok(())
    } else {
        Err(format!(
            "tools/call metric writeback returned status {}",
            response.status()
        ))
    }
}

fn classify_tools_call_metric_outcome(
    status: StatusCode,
    payload: &Value,
) -> (bool, Option<String>) {
    if let Some(error) = payload.get("error") {
        let message = error
            .get("message")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or_else(|| Some(error.to_string()));
        return (false, message);
    }

    if !status.is_success() {
        return (false, Some(format!("HTTP {}", status.as_u16())));
    }

    (true, None)
}

fn retry_policy_supports_native_execution(policy: &NativePostInvokeRetryPolicy) -> bool {
    policy.kind == "retry_with_backoff"
}

fn compute_retry_delay_ms(policy: &NativePostInvokeRetryPolicy, retry_attempt: u32) -> u64 {
    let ceiling = policy
        .backoff_base_ms
        .saturating_mul(2u64.saturating_pow(retry_attempt))
        .min(policy.max_backoff_ms);
    if policy.jitter {
        rand::thread_rng().gen_range(0..=ceiling)
    } else {
        ceiling
    }
}

fn retry_status_matches(policy: &NativePostInvokeRetryPolicy, status_code: Option<i32>) -> bool {
    status_code
        .map(|code| policy.retry_on_status.contains(&code))
        .unwrap_or(false)
}

fn should_retry_jsonrpc_payload(policy: &NativePostInvokeRetryPolicy, payload: &Value) -> bool {
    if payload.get("error").is_some() {
        return true;
    }

    let result = payload.get("result").unwrap_or(payload);
    let Some(result_object) = result.as_object() else {
        return false;
    };

    let structured = result_object
        .get("structuredContent")
        .or_else(|| result_object.get("structured_content"))
        .and_then(Value::as_object);
    let structured_status = structured
        .and_then(|value| value.get("status_code"))
        .and_then(Value::as_i64)
        .and_then(|value| i32::try_from(value).ok());

    if result_object
        .get("isError")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return match structured_status {
            Some(code) => retry_status_matches(policy, Some(code)),
            None => true,
        };
    }

    if structured
        .and_then(|value| value.get("isError"))
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return true;
    }

    retry_status_matches(policy, structured_status)
}

fn retry_delay_for_payload(
    policy: &NativePostInvokeRetryPolicy,
    payload: &Value,
    retry_attempt: u32,
) -> Option<u64> {
    if !retry_policy_supports_native_execution(policy) || retry_attempt >= policy.max_retries {
        return None;
    }
    if should_retry_jsonrpc_payload(policy, payload) {
        return Some(compute_retry_delay_ms(policy, retry_attempt));
    }
    None
}

fn retry_delay_for_transport_error(
    policy: &NativePostInvokeRetryPolicy,
    retry_attempt: u32,
) -> Option<u64> {
    if !retry_policy_supports_native_execution(policy) || retry_attempt >= policy.max_retries {
        return None;
    }
    Some(compute_retry_delay_ms(policy, retry_attempt))
}

fn jsonrpc_tool_invocation_error_response(
    request_id: Option<Value>,
    error_message: &str,
) -> Response {
    json_response(
        StatusCode::OK,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id.unwrap_or(Value::Null),
            "error": {
                "code": -32000,
                "message": format!("Tool invocation failed: {error_message}"),
            }
        }),
    )
}

fn tools_call_error_type_from_payload(payload: &Value) -> &'static str {
    let code = payload
        .get("error")
        .and_then(Value::as_object)
        .and_then(|error| error.get("code"))
        .and_then(Value::as_i64);

    match code {
        Some(-32003) => "PermissionDenied",
        Some(-32602 | -32600) => "InvalidRequest",
        Some(-32700) => "ParseError",
        _ => "ToolInvocationError",
    }
}

async fn record_tools_call_metric(
    state: &AppState,
    incoming_headers: &HeaderMap,
    plan: &ResolvedMcpToolCallPlan,
    duration_ms: f64,
    success: bool,
    error_message: Option<String>,
) {
    let Some(tool_id) = plan.tool_id.clone() else {
        return;
    };

    let payload = ToolsCallMetricRecordRequest {
        tool_id,
        server_id: plan.server_id.clone(),
        duration_ms,
        success,
        error_message,
    };

    if let Err(err) = send_tools_call_metric_to_backend(state, incoming_headers, &payload).await {
        warn!("{err}");
    }
}

async fn execute_tools_call_direct(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    plan: &ResolvedMcpToolCallPlan,
    trace_context: &TraceRequestContext,
) -> Result<Response, String> {
    let request_started = Instant::now();
    let root_span = tracing::Span::current();
    if let Some(tool_name) = plan.tool_name.clone().or_else(|| {
        request
            .params
            .as_object()
            .and_then(|params| params.get("name"))
            .and_then(Value::as_str)
            .map(str::to_string)
    }) {
        set_span_attribute(&root_span, "tool.name", tool_name.clone());
        set_langfuse_trace_name(
            &root_span,
            derive_langfuse_trace_name("tool.invoke", &[("tool.name", tool_name)]),
        );
    }
    if let Some(tool_id) = plan.tool_id.clone() {
        set_span_attribute(&root_span, "tool.id", tool_id);
    }
    if let Some(gateway_id) = plan.gateway_id.clone() {
        set_span_attribute(&root_span, "tool.gateway_id", gateway_id);
    }
    if let Some(server_id) = plan.server_id.clone() {
        set_span_attribute(&root_span, "server_id", server_id);
    }
    set_span_attribute(&root_span, "tool.integration_type", "MCP");
    let mut retry_attempt = 0u32;
    loop {
        // Direct execution mirrors the MCP client lifecycle explicitly:
        // streamable HTTP reuses cached upstream sessions when they stay healthy,
        // while SSE establishes a native one-shot client exchange without falling
        // back through Python.
        let gateway_call_span = start_child_span("tool.gateway_call", trace_context);
        if let Some(tool_name) = plan.tool_name.clone() {
            set_span_attribute(&gateway_call_span, "tool.name", tool_name);
        }
        if let Some(tool_id) = plan.tool_id.clone() {
            set_span_attribute(&gateway_call_span, "tool.id", tool_id);
        }
        set_span_attribute(&gateway_call_span, "tool.integration_type", "MCP");
        set_span_attribute(&gateway_call_span, "retry_attempt", retry_attempt as i64);

        let gateway_result = async {
            let transport = plan.transport.as_deref().unwrap_or("streamablehttp");
            if transport == "streamablehttp" && state.use_rmcp_upstream_client() {
                #[cfg(feature = "rmcp-upstream-client")]
                match execute_tools_call_via_rmcp(state, incoming_headers, request, plan).await {
                    Ok((response, success, error_message, output_payload, retry_payload)) => {
                        return Ok::<_, String>(EitherToolsCallResponse::Finished((
                            response,
                            success,
                            error_message,
                            output_payload,
                            retry_payload,
                        )));
                    }
                    Err(err) => warn!("Rust MCP rmcp tools/call fallback: {err}"),
                }
            }

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

            if transport == "sse" {
                let (payload, success, error_message) =
                    execute_tools_call_via_sse(state, plan, request, &protocol_version, timeout_ms)
                        .await?;
                let output_payload = if success {
                    Some(
                        payload
                            .get("result")
                            .cloned()
                            .unwrap_or_else(|| payload.clone()),
                    )
                } else {
                    None
                };
                let mut response = json_response(StatusCode::OK, payload.clone());
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
                return Ok::<_, String>(EitherToolsCallResponse::Finished((
                    response,
                    success,
                    error_message,
                    output_payload,
                    Some(payload),
                )));
            }

            let server_url = plan
                .server_url
                .as_deref()
                .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
            let remote_tool_name = plan
                .remote_tool_name
                .as_deref()
                .ok_or_else(|| "resolved tools/call plan missing remote_tool_name".to_string())?;

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
                let session_key =
                    build_upstream_session_key(downstream_session_id.as_deref(), plan)?;
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

            Ok::<_, String>(EitherToolsCallResponse::NeedsPostProcess((
                tool_response,
                downstream_session_id,
            )))
        }
        .instrument(gateway_call_span)
        .await;

        let gateway_result = match gateway_result {
            Ok(result) => result,
            Err(err) => {
                if let Some(policy) = plan.post_invoke_retry_policy.as_ref()
                    && let Some(delay_ms) = retry_delay_for_transport_error(policy, retry_attempt)
                {
                    set_span_attribute(
                        &root_span,
                        "contextforge.rust.retry.delay_ms",
                        delay_ms as i64,
                    );
                    retry_attempt += 1;
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    continue;
                }
                if plan.post_invoke_retry_policy.is_some() {
                    record_tools_call_metric(
                        state,
                        incoming_headers,
                        plan,
                        request_started.elapsed().as_secs_f64() * 1000.0,
                        false,
                        Some(err.clone()),
                    )
                    .await;
                    set_span_attribute(&root_span, "success", false);
                    set_span_attribute(
                        &root_span,
                        "duration.ms",
                        request_started.elapsed().as_secs_f64() * 1000.0,
                    );
                    set_span_error(&root_span, &err, Some("ToolInvocationError"));
                    return Ok(jsonrpc_tool_invocation_error_response(
                        request.id.clone(),
                        &err,
                    ));
                }
                return Err(err);
            }
        };

        match gateway_result {
            EitherToolsCallResponse::Finished((
                response,
                success,
                error_message,
                output_payload,
                retry_payload,
            )) => {
                if let Some(policy) = plan.post_invoke_retry_policy.as_ref()
                    && let Some(payload) = retry_payload.as_ref()
                    && let Some(delay_ms) = retry_delay_for_payload(policy, payload, retry_attempt)
                {
                    set_span_attribute(
                        &root_span,
                        "contextforge.rust.retry.delay_ms",
                        delay_ms as i64,
                    );
                    retry_attempt += 1;
                    tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                    continue;
                }

                record_tools_call_metric(
                    state,
                    incoming_headers,
                    plan,
                    request_started.elapsed().as_secs_f64() * 1000.0,
                    success,
                    error_message.clone(),
                )
                .await;

                if retry_attempt > 0 {
                    set_span_attribute(
                        &root_span,
                        "contextforge.rust.retry.count",
                        retry_attempt as i64,
                    );
                }
                set_span_attribute(&root_span, "success", success);
                set_span_attribute(
                    &root_span,
                    "duration.ms",
                    request_started.elapsed().as_secs_f64() * 1000.0,
                );
                if let Some(error_message) = error_message.as_deref()
                    && !success
                {
                    set_span_error(&root_span, error_message, Some("ToolInvocationError"));
                }
                if success
                    && is_output_capture_enabled("tool.invoke")
                    && let Some(output_payload) = output_payload
                {
                    set_span_attribute(
                        &root_span,
                        "langfuse.observation.output",
                        serialize_trace_payload(&output_payload),
                    );
                }
                return Ok(response);
            }
            EitherToolsCallResponse::NeedsPostProcess((tool_response, downstream_session_id)) => {
                let post_process_span = start_child_span("tool.post_process", trace_context);
                if let Some(tool_name) = plan.tool_name.clone() {
                    set_span_attribute(&post_process_span, "tool.name", tool_name);
                }
                if let Some(tool_id) = plan.tool_id.clone() {
                    set_span_attribute(&post_process_span, "tool.id", tool_id);
                }
                set_span_attribute(&post_process_span, "retry_attempt", retry_attempt as i64);

                let root_span_for_post_process = root_span.clone();
                let post_process_outcome = async move {
                    let status = tool_response.status();
                    let payload = decode_upstream_json_payload(tool_response)
                        .await
                        .map_err(|err| format!("direct tools/call decode failed: {err}"))?;

                    if let Some(policy) = plan.post_invoke_retry_policy.as_ref()
                        && let Some(delay_ms) =
                            retry_delay_for_payload(policy, &payload, retry_attempt)
                    {
                        return Ok::<_, String>(PostProcessOutcome::Retry(delay_ms));
                    }

                    let (success, error_message) =
                        classify_tools_call_metric_outcome(status, &payload);
                    record_tools_call_metric(
                        state,
                        incoming_headers,
                        plan,
                        request_started.elapsed().as_secs_f64() * 1000.0,
                        success,
                        error_message.clone(),
                    )
                    .await;

                    if retry_attempt > 0 {
                        set_span_attribute(
                            &root_span_for_post_process,
                            "contextforge.rust.retry.count",
                            retry_attempt as i64,
                        );
                    }
                    set_span_attribute(&root_span_for_post_process, "success", success);
                    set_span_attribute(
                        &root_span_for_post_process,
                        "duration.ms",
                        request_started.elapsed().as_secs_f64() * 1000.0,
                    );
                    if let Some(error_message) = error_message.as_deref()
                        && !success
                    {
                        set_span_error(
                            &root_span_for_post_process,
                            error_message,
                            Some("ToolInvocationError"),
                        );
                    }
                    if success && is_output_capture_enabled("tool.invoke") {
                        let output_payload = payload
                            .get("result")
                            .cloned()
                            .unwrap_or_else(|| payload.clone());
                        set_span_attribute(
                            &root_span_for_post_process,
                            "langfuse.observation.output",
                            serialize_trace_payload(&output_payload),
                        );
                    }

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
                    Ok(PostProcessOutcome::Response(response))
                }
                .instrument(post_process_span)
                .await?;

                match post_process_outcome {
                    PostProcessOutcome::Retry(delay_ms) => {
                        set_span_attribute(
                            &root_span,
                            "contextforge.rust.retry.delay_ms",
                            delay_ms as i64,
                        );
                        retry_attempt += 1;
                        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
                        continue;
                    }
                    PostProcessOutcome::Response(response) => return Ok(response),
                }
            }
        }
    }
}

enum EitherToolsCallResponse {
    Finished((Response, bool, Option<String>, Option<Value>, Option<Value>)),
    NeedsPostProcess((reqwest::Response, Option<String>)),
}

enum PostProcessOutcome {
    Retry(u64),
    Response(Response),
}

#[cfg(feature = "rmcp-upstream-client")]
async fn execute_tools_call_via_rmcp(
    state: &AppState,
    incoming_headers: &HeaderMap,
    request: &JsonRpcRequest,
    plan: &ResolvedMcpToolCallPlan,
) -> Result<(Response, bool, Option<String>, Option<Value>, Option<Value>), String> {
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

    let (response, success, error_message, output_payload, retry_payload) =
        match invoke_tools_call_via_rmcp(
            rmcp_client.as_ref(),
            request,
            remote_tool_name,
            plan.modified_args.as_ref(),
        )
        .await
        {
            Ok(response) => response,
            Err(err) => {
                state
                    .rmcp_upstream_clients()
                    .lock()
                    .await
                    .remove(&session_key);
                let retried_client = get_or_create_rmcp_upstream_client(
                    state,
                    plan,
                    &session_key,
                    &protocol_version,
                )
                .await?;
                invoke_tools_call_via_rmcp(
                    retried_client.as_ref(),
                    request,
                    remote_tool_name,
                    plan.modified_args.as_ref(),
                )
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
    Ok((
        response,
        success,
        error_message,
        output_payload,
        retry_payload,
    ))
}

async fn ensure_upstream_session(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    downstream_session_id: Option<&str>,
    protocol_version: &str,
    timeout_ms: u64,
) -> Result<Option<String>, String> {
    // Upstream sessions are keyed by both downstream session identity and the
    // resolved upstream target. That keeps parallel callers from sharing an
    // upstream MCP session across users or servers.
    let session_key = build_upstream_session_key(downstream_session_id, plan)?;
    {
        let mut sessions = state.upstream_tool_sessions().lock().await;
        if let Some(existing) = sessions.get_mut(&session_key)
            && existing.last_used.elapsed() < state.upstream_session_ttl()
        {
            existing.last_used = Instant::now();
            return Ok(existing.session_id.clone());
        }
        sessions.remove(&session_key);
    }

    let upstream_session_id =
        initialize_upstream_session(state, plan, protocol_version, timeout_ms).await?;
    let mut sessions = state.upstream_tool_sessions().lock().await;
    if let Some(existing) = sessions.get_mut(&session_key)
        && existing.last_used.elapsed() < state.upstream_session_ttl()
    {
        existing.last_used = Instant::now();
        return Ok(existing.session_id.clone());
    }
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
    // Rust behaves like a well-formed MCP client here: send initialize, record
    // the upstream session id if present, then best-effort send the matching
    // initialized notification before using the session for tools/call.
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
    // Apply plugin-modified arguments from pre-invoke hooks (e.g. wxo_connections
    // strips wxo_* params and injects credential headers via the plan).
    if let Some(ref modified_args) = plan.modified_args {
        params_object.insert("arguments".to_string(), modified_args.clone());
    }

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
    // These are the exact headers Rust forwards to the upstream MCP server for
    // direct execution. Resolved plan headers come from Python authorization
    // and are already filtered before they reach this point.
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

    if let Some(parsed_headers) = plan.parsed_headers.as_ref() {
        for (header_name, header_value) in parsed_headers {
            headers.insert(header_name.clone(), header_value.clone());
        }
    } else if let Some(header_values) = plan.headers.as_ref() {
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

fn build_upstream_sse_connect_headers(
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
) -> Result<reqwest::header::HeaderMap, String> {
    let mut headers = build_upstream_headers(plan, protocol_version, None)?;
    headers.remove(CONTENT_TYPE);
    headers.insert(
        reqwest::header::ACCEPT,
        HeaderValue::from_static("text/event-stream"),
    );
    Ok(headers)
}

fn normalize_upstream_sse_endpoint_url(
    server_url: &str,
    endpoint_value: &str,
) -> Result<String, String> {
    let base_url = Url::parse(server_url)
        .map_err(|err| format!("invalid upstream SSE URL '{server_url}': {err}"))?;
    let endpoint_url = base_url
        .join(endpoint_value)
        .map_err(|err| format!("invalid upstream SSE endpoint '{endpoint_value}': {err}"))?;

    if base_url.scheme() != endpoint_url.scheme()
        || base_url.host_str() != endpoint_url.host_str()
        || base_url.port_or_known_default() != endpoint_url.port_or_known_default()
    {
        return Err(format!(
            "upstream SSE endpoint origin does not match connection origin: {endpoint_url}"
        ));
    }

    Ok(endpoint_url.to_string())
}

async fn post_sse_jsonrpc_message(
    state: &AppState,
    endpoint_url: &str,
    plan: &ResolvedMcpToolCallPlan,
    protocol_version: &str,
    timeout_ms: u64,
    payload: &Value,
) -> Result<(), String> {
    let response = state
        .client
        .post(endpoint_url)
        .headers(build_upstream_headers(plan, protocol_version, None)?)
        .timeout(Duration::from_millis(timeout_ms))
        .json(payload)
        .send()
        .await
        .map_err(|err| format!("upstream SSE message POST failed: {err}"))?;

    if !response.status().is_success() {
        return Err(format!(
            "upstream SSE message POST returned status {}",
            response.status()
        ));
    }

    Ok(())
}

async fn read_next_sse_frame<S>(
    stream: &mut S,
    buffer: &mut BytesMut,
    frame: &mut PendingSseFrame,
    timeout_ms: u64,
) -> Result<Option<FinalizedSseFrame>, String>
where
    S: futures_util::stream::Stream<Item = Result<Bytes, reqwest::Error>> + Unpin,
{
    loop {
        while let Some(newline_index) = buffer.iter().position(|byte| *byte == b'\n') {
            let mut line_bytes = buffer.split_to(newline_index + 1);
            if matches!(line_bytes.last(), Some(b'\n')) {
                line_bytes.truncate(line_bytes.len().saturating_sub(1));
            }
            if matches!(line_bytes.last(), Some(b'\r')) {
                line_bytes.truncate(line_bytes.len().saturating_sub(1));
            }

            let line = String::from_utf8_lossy(&line_bytes);
            if line.is_empty() {
                if let Some(finalized) = finalize_sse_frame(frame) {
                    return Ok(Some(finalized));
                }
                continue;
            }

            parse_sse_line(frame, &line);
        }

        match tokio::time::timeout(Duration::from_millis(timeout_ms), stream.next()).await {
            Ok(Some(Ok(chunk))) => buffer.extend_from_slice(&chunk),
            Ok(Some(Err(err))) => return Err(format!("upstream SSE read failed: {err}")),
            Ok(None) => {
                if !buffer.is_empty() {
                    let line = String::from_utf8_lossy(buffer.as_ref());
                    parse_sse_line(frame, line.trim_end_matches(['\r', '\n']));
                    buffer.clear();
                }
                return Ok(finalize_sse_frame(frame));
            }
            Err(_) => {
                return Err(format!("upstream SSE read timed out after {timeout_ms}ms"));
            }
        }
    }
}

async fn wait_for_sse_endpoint<S>(
    stream: &mut S,
    buffer: &mut BytesMut,
    frame: &mut PendingSseFrame,
    server_url: &str,
    timeout_ms: u64,
) -> Result<String, String>
where
    S: futures_util::stream::Stream<Item = Result<Bytes, reqwest::Error>> + Unpin,
{
    loop {
        let Some(next_frame) = read_next_sse_frame(stream, buffer, frame, timeout_ms).await? else {
            return Err("upstream SSE stream ended before endpoint bootstrap".to_string());
        };

        if next_frame.event.as_deref() == Some("endpoint") {
            return normalize_upstream_sse_endpoint_url(server_url, next_frame.data.trim());
        }
    }
}

async fn wait_for_sse_jsonrpc_message<S>(
    stream: &mut S,
    buffer: &mut BytesMut,
    frame: &mut PendingSseFrame,
    expected_id: &Value,
    timeout_ms: u64,
) -> Result<Value, String>
where
    S: futures_util::stream::Stream<Item = Result<Bytes, reqwest::Error>> + Unpin,
{
    loop {
        let Some(next_frame) = read_next_sse_frame(stream, buffer, frame, timeout_ms).await? else {
            return Err(format!(
                "upstream SSE stream ended before JSON-RPC response for id {expected_id}"
            ));
        };

        if !matches!(next_frame.event.as_deref(), None | Some("message"))
            || next_frame.data.trim().is_empty()
        {
            continue;
        }

        let payload: Value = serde_json::from_str(&next_frame.data)
            .map_err(|err| format!("invalid upstream SSE JSON payload: {err}"))?;
        if payload.get("id") == Some(expected_id) {
            return Ok(payload);
        }
    }
}

async fn execute_tools_call_via_sse(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    request: &JsonRpcRequest,
    protocol_version: &str,
    timeout_ms: u64,
) -> Result<(Value, bool, Option<String>), String> {
    let server_url = plan
        .server_url
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing server_url".to_string())?;
    let remote_tool_name = plan
        .remote_tool_name
        .as_deref()
        .ok_or_else(|| "resolved tools/call plan missing remote_tool_name".to_string())?;

    let sse_response = state
        .client
        .get(server_url)
        .headers(build_upstream_sse_connect_headers(plan, protocol_version)?)
        .timeout(Duration::from_millis(timeout_ms))
        .send()
        .await
        .map_err(|err| format!("upstream SSE connect failed: {err}"))?;

    if !sse_response.status().is_success() {
        return Err(format!(
            "upstream SSE connect returned status {}",
            sse_response.status()
        ));
    }

    let mut stream = sse_response.bytes_stream();
    let mut buffer = BytesMut::new();
    let mut frame = PendingSseFrame::default();
    let message_endpoint_url =
        wait_for_sse_endpoint(&mut stream, &mut buffer, &mut frame, server_url, timeout_ms).await?;

    let initialize_request = json!({
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
    });
    post_sse_jsonrpc_message(
        state,
        &message_endpoint_url,
        plan,
        protocol_version,
        timeout_ms,
        &initialize_request,
    )
    .await?;
    let initialize_payload = wait_for_sse_jsonrpc_message(
        &mut stream,
        &mut buffer,
        &mut frame,
        &Value::String("__contextforge_init__".to_string()),
        timeout_ms,
    )
    .await?;
    if initialize_payload.get("error").is_some() {
        return Err(format!(
            "upstream SSE initialize returned error: {initialize_payload}"
        ));
    }

    post_sse_jsonrpc_message(
        state,
        &message_endpoint_url,
        plan,
        protocol_version,
        timeout_ms,
        &json!({
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/initialized",
            "params": {}
        }),
    )
    .await?;

    let mut params = request.params.clone();
    let params_object = params
        .as_object_mut()
        .ok_or_else(|| "tools/call params must be an object".to_string())?;
    params_object.insert(
        "name".to_string(),
        Value::String(remote_tool_name.to_string()),
    );
    if let Some(ref modified_args) = plan.modified_args {
        params_object.insert("arguments".to_string(), modified_args.clone());
    }

    let request_id = request
        .id
        .clone()
        .unwrap_or(Value::String("__contextforge_tools_call__".to_string()));
    let tool_request = json!({
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id.clone(),
        "method": "tools/call",
        "params": params,
    });
    post_sse_jsonrpc_message(
        state,
        &message_endpoint_url,
        plan,
        protocol_version,
        timeout_ms,
        &tool_request,
    )
    .await?;
    let payload = wait_for_sse_jsonrpc_message(
        &mut stream,
        &mut buffer,
        &mut frame,
        &request_id,
        timeout_ms,
    )
    .await?;
    let (success, error_message) = classify_tools_call_metric_outcome(StatusCode::OK, &payload);
    Ok((payload, success, error_message))
}

#[cfg(feature = "rmcp-upstream-client")]
async fn get_or_create_rmcp_upstream_client(
    state: &AppState,
    plan: &ResolvedMcpToolCallPlan,
    session_key: &str,
    protocol_version: &str,
) -> Result<Arc<RmcpRunningService<RmcpRoleClient, RmcpClientInfo>>, String> {
    // RMCP clients are cached at the same session granularity as direct
    // upstream sessions so the sidecar can amortize setup/TLS cost without
    // weakening cross-user or cross-server isolation.
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

    let transport = StreamableHttpClientTransport::with_client(
        state.rmcp_client.clone(),
        build_rmcp_transport_config(plan, protocol_version)?,
    );
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

    if let Some(parsed_headers) = plan.parsed_headers.as_ref() {
        for (header_name, header_value) in parsed_headers {
            custom_headers.insert(header_name.clone(), header_value.clone());
        }
    } else if let Some(header_values) = plan.headers.as_ref() {
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
    modified_args: Option<&Value>,
) -> Result<(Response, bool, Option<String>, Option<Value>, Option<Value>), String> {
    let mut params = request.params.clone();
    let params_object = params
        .as_object_mut()
        .ok_or_else(|| "tools/call params must be an object".to_string())?;
    params_object.insert(
        "name".to_string(),
        Value::String(remote_tool_name.to_string()),
    );
    if let Some(args) = modified_args {
        params_object.insert("arguments".to_string(), args.clone());
    }

    let params = serde_json::from_value::<RmcpCallToolRequestParams>(params)
        .map_err(|err| format!("rmcp tools/call params decode failed: {err}"))?;
    let response_id = request
        .id
        .clone()
        .unwrap_or(Value::String("__contextforge_tools_call__".to_string()));

    match client.peer().call_tool(params).await {
        Ok(result) => {
            let encoded_result = serde_json::to_value(result)
                .map_err(|err| format!("rmcp tools/call result encode failed: {err}"))?;
            let payload = json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": response_id,
                "result": encoded_result.clone(),
            });
            Ok((
                json_response(StatusCode::OK, payload.clone()),
                true,
                None,
                Some(encoded_result),
                Some(payload),
            ))
        }
        Err(RmcpServiceError::McpError(error)) => {
            let error_message = error.message.to_string();
            let payload = json!({
                "jsonrpc": JSONRPC_VERSION,
                "id": response_id,
                "error": serde_json::to_value(error)
                    .map_err(|err| format!("rmcp tools/call error encode failed: {err}"))?,
            });
            Ok((
                json_response(StatusCode::OK, payload.clone()),
                false,
                Some(error_message),
                None,
                Some(payload),
            ))
        }
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
    if let Some(headers_hash) = plan.headers_hash {
        headers_hash.hash(&mut hasher);
    } else if let Some(header_values) = plan.headers.as_ref() {
        hash_ordered_pairs(
            header_values
                .iter()
                .map(|(name, value)| (name.as_str(), value.as_str())),
        )
        .hash(&mut hasher);
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

    let mut header_pairs = Vec::new();
    for (name, value) in incoming_headers {
        if should_cache_plan_header(name) {
            let header_value = value
                .to_str()
                .map_err(|err| format!("invalid cacheable header '{}': {err}", name.as_str()))?;
            header_pairs.push((name.as_str(), header_value));
        }
    }
    hash_ordered_pairs(header_pairs).hash(&mut hasher);

    Ok(format!("tool-plan:{}", hasher.finish()))
}

fn prepare_resolved_tools_call_plan(plan: &mut ResolvedMcpToolCallPlan) -> Result<(), String> {
    let Some(header_values) = plan.headers.as_ref() else {
        plan.parsed_headers = None;
        plan.headers_hash = None;
        return Ok(());
    };

    // Parse and hash backend-provided headers once when the plan is decoded so
    // hot-path request execution can reuse them without reparsing or rebuilding
    // ordered header maps on every tools/call.
    let mut parsed_headers = Vec::with_capacity(header_values.len());
    for (name, value) in header_values {
        let header_name = HeaderName::from_str(name)
            .map_err(|err| format!("invalid upstream header name '{name}': {err}"))?;
        let header_value = HeaderValue::from_str(value)
            .map_err(|err| format!("invalid upstream header value for '{name}': {err}"))?;
        parsed_headers.push((header_name, header_value));
    }

    plan.headers_hash = Some(hash_ordered_pairs(
        header_values
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    ));
    plan.parsed_headers = Some(parsed_headers);
    Ok(())
}

fn hash_ordered_pairs<'a, I>(pairs: I) -> u64
where
    I: IntoIterator<Item = (&'a str, &'a str)>,
{
    let mut ordered_pairs: Vec<_> = pairs.into_iter().collect();
    ordered_pairs.sort_unstable();
    let mut hasher = DefaultHasher::new();
    for (name, value) in ordered_pairs {
        name.hash(&mut hasher);
        value.hash(&mut hasher);
    }
    hasher.finish()
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
    forwarded_headers.insert(
        HeaderName::from_static(INTERNAL_RUNTIME_AUTH_HEADER),
        internal_runtime_auth_header_value(),
    );
    if session_validated {
        forwarded_headers.insert(
            HeaderName::from_static(SESSION_VALIDATED_HEADER),
            HeaderValue::from_static(RUNTIME_NAME),
        );
    }
    inject_current_trace_context(&mut forwarded_headers);
    forwarded_headers
}

fn build_backend_transport_url(base_url: &str, uri: &axum::http::Uri) -> String {
    match uri.query() {
        Some(query) if !query.is_empty() => format!("{base_url}?{query}"),
        _ => base_url.to_string(),
    }
}

fn should_forward_response_header(name: &str) -> bool {
    matches!(
        name,
        "content-type"
            | "mcp-session-id"
            | "x-mcp-session-id"
            | "www-authenticate"
            | "x-request-id"
            | "x-correlation-id"
    )
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

    if !headers
        .keys()
        .any(|name| should_forward_response_header(name.as_str()) && name == CONTENT_TYPE)
    {
        builder = builder.header(CONTENT_TYPE, "application/json");
    }

    for (header_name, value) in &headers {
        if should_forward_response_header(header_name.as_str()) {
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

    for (header_name, value) in headers {
        if should_forward_response_header(header_name.as_str()) {
            response_headers.insert(header_name.clone(), value.clone());
        }
    }

    response
}

fn inject_runtime_capability_headers(response: &mut Response, headers: &[(&'static str, bool)]) {
    let response_headers = response.headers_mut();
    for (header_name, rust_owned) in headers {
        let value = if *rust_owned { "rust" } else { "python" };
        if let Ok(value) = HeaderValue::from_str(value) {
            response_headers.insert(HeaderName::from_static(header_name), value);
        }
    }
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
            | INTERNAL_RUNTIME_AUTH_HEADER
            | SESSION_VALIDATED_HEADER
            | RUNTIME_HEADER
    )
}

fn json_response(status: StatusCode, payload: Value) -> Response {
    let payload = if status.is_server_error() {
        redact_server_error_payload(payload)
    } else {
        payload
    };
    let mut response = (status, Json(payload)).into_response();
    response.headers_mut().insert(
        HeaderName::from_static(RUNTIME_HEADER),
        HeaderValue::from_static(RUNTIME_NAME),
    );
    response
}

fn backend_detail_error_response(detail: &str) -> Response {
    json_response(
        StatusCode::BAD_GATEWAY,
        json!({
            "detail": detail,
            "error": CLIENT_ERROR_DETAIL,
        }),
    )
}

fn backend_jsonrpc_error_response(
    request_id: Option<Value>,
    message: impl Into<String>,
) -> Response {
    json_response(
        StatusCode::BAD_GATEWAY,
        json!({
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id.unwrap_or(Value::Null),
            "error": {
                "code": -32000,
                "message": message.into(),
                "data": CLIENT_ERROR_DETAIL,
            }
        }),
    )
}

fn redact_server_error_payload(mut payload: Value) -> Value {
    if let Some(error_value) = payload.get_mut("error") {
        if let Some(error_object) = error_value.as_object_mut()
            && let Some(data_value) = error_object.get_mut("data")
            && data_value.is_string()
        {
            *data_value = Value::String(CLIENT_ERROR_DETAIL.to_string());
        }
    }

    payload
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
    use base64::Engine;
    use bytes::BytesMut;

    use super::{
        AffinityForwardResponse, AppState, Bytes, CLIENT_ERROR_DETAIL,
        DirectExecutionAuthorization, EventStoreReplayRequest, EventStoreStoreRequest,
        INTERNAL_RUNTIME_AUTH_HEADER, InternalAuthContext, InternalAuthenticateRequest,
        JsonRpcRequest, RUNTIME_HEADER, RUNTIME_NAME, RuntimeConfig, RuntimeError,
        RuntimeSessionRecord, SessionAuthReuseMissReason, TrustedPeerAddr, URL_SAFE_NO_PAD,
        accepts_sse, active_runtime_session_count, affinity_forward_error_response,
        auth_binding_fingerprint, authenticate_public_request_if_needed,
        authorize_server_method_via_backend, batch_rejected_response, build_forwarded_sse_event,
        build_public_router, can_reuse_session_auth, can_use_direct_prompts_get,
        can_use_direct_resources_read, decode_request, decode_upstream_json_payload_bytes,
        derive_backend_authenticate_url, derive_backend_completion_complete_url,
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
        derive_backend_tools_call_metric_url, derive_backend_tools_call_resolve_url,
        derive_backend_tools_call_url, derive_backend_tools_list_authz_url,
        derive_backend_tools_list_url, derive_backend_transport_url, direct_server_prompts_get,
        direct_server_prompts_list, direct_server_resource_templates_list,
        direct_server_resources_list, direct_server_resources_read,
        encode_internal_auth_context_header, event_store_key_prefix, extract_client_capabilities,
        extract_first_sse_data_payload, finalize_sse_frame, forward_initialize_to_backend,
        forward_to_backend, forward_transport_request, get_runtime_session,
        handle_initialize_with_session_core, handle_resume_transport_request, has_server_scope,
        hex_decode, hex_encode, inject_server_id_header, inject_session_header,
        invalid_request_response, is_affinity_forwarded_request, load_pem_certificates,
        maybe_bind_session_auth_context, maybe_upsert_runtime_session_from_transport_response,
        normalize_postgres_database_url, normalize_tool_input_schema, parse_error_response,
        parse_sse_line, pool_owner_key, prompt_arguments_from_schema, public_client_ip,
        query_param, read_next_sse_frame, remove_runtime_session, replay_events_endpoint,
        requested_initialize_session_id, requested_protocol_version,
        response_from_affinity_forward_response, run, runtime_session_access_outcome,
        runtime_session_id_from_request, runtime_session_key, send_tools_list_to_backend,
        send_transport_to_backend, serve_http, serve_uds, store_event_endpoint,
        tools_call_error_type_from_payload, transport_delete_server_scoped,
        transport_get_server_scoped, upsert_runtime_session, validate_initialize_params,
        validate_protocol_version, validate_runtime_session_request,
    };
    use axum::{
        Json, Router,
        body::to_bytes,
        extract::{Path as AxumPath, State},
        http::{HeaderMap, HeaderName, HeaderValue, StatusCode, Uri},
        response::{IntoResponse, Response, sse::Sse},
        routing::{get, post},
    };
    use futures_util::stream;
    use reqwest::Url;
    use serde_json::{Value, json};
    use std::collections::HashMap;
    use std::sync::Once;
    use std::{
        convert::Infallible,
        fs,
        net::{SocketAddr, TcpListener},
        path::PathBuf,
        sync::{Arc, Mutex},
        time::Duration,
    };
    use tokio::time::{Instant, sleep};
    use tracing::warn;
    use uuid::Uuid;

    static TEST_AUTH_SECRET_INIT: Once = Once::new();

    fn ensure_test_auth_secret() {
        TEST_AUTH_SECRET_INIT.call_once(|| {
            // SAFETY: tests initialize this process-wide env var once before runtime state is built.
            unsafe {
                std::env::set_var(
                    "AUTH_ENCRYPTION_SECRET",
                    "contextforge-rust-runtime-test-secret-1234567890",
                );
            }
        });
    }

    fn generate_test_root_cert_pem() -> Option<String> {
        let native_certs = rustls_native_certs::load_native_certs();
        for load_error in native_certs.errors {
            warn!("Rust MCP test native root load warning: {load_error}");
        }
        let certificate = native_certs.certs.into_iter().next()?;
        let encoded = base64::engine::general_purpose::STANDARD.encode(certificate.as_ref());
        let mut pem = String::from("-----BEGIN CERTIFICATE-----\n");
        for chunk in encoded.as_bytes().chunks(64) {
            pem.push_str(std::str::from_utf8(chunk).expect("base64 chunk is utf-8"));
            pem.push('\n');
        }
        pem.push_str("-----END CERTIFICATE-----\n");
        Some(pem)
    }

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

    fn trusted_auth_context_json() -> Value {
        json!({
            "email": "owner@example.com",
            "teams": ["team-1"],
            "is_authenticated": true
        })
    }

    fn trusted_server_headers(server_id: &str) -> HeaderMap {
        ensure_test_auth_secret();
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encode_internal_auth_context_header(&trusted_auth_context_json())
                .expect("encode auth context"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_str(server_id).expect("valid server id"),
        );
        headers
    }

    async fn response_json(response: Response) -> Value {
        serde_json::from_slice(
            &to_bytes(response.into_body(), usize::MAX)
                .await
                .expect("body"),
        )
        .expect("json body")
    }

    fn test_config() -> RuntimeConfig {
        ensure_test_auth_secret();
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
            backend_validation_enabled: true,
            backend_allowed_hosts: "localhost,127.0.0.1".to_string(),
            backend_blocked_networks: "169.254.169.254/32".to_string(),
            backend_max_url_length: 2048,
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
        assert_eq!(
            state.backend_tools_call_metric_url(),
            "http://127.0.0.1:4444/_internal/mcp/tools/call/metric"
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
    fn app_state_new_rejects_missing_internal_runtime_auth_secret() {
        ensure_test_auth_secret();
        let config = test_config();
        let original = std::env::var("AUTH_ENCRYPTION_SECRET").ok();
        // SAFETY: this test temporarily removes the env var and restores it before returning.
        unsafe {
            std::env::remove_var("AUTH_ENCRYPTION_SECRET");
        }

        let Err(error) = AppState::new(&config) else {
            panic!("missing auth secret should fail");
        };

        if let Some(value) = original {
            // SAFETY: restore original process-wide env var before the test exits.
            unsafe {
                std::env::set_var("AUTH_ENCRYPTION_SECRET", value);
            }
        }

        match error {
            RuntimeError::Config(message) => {
                assert!(message.contains("AUTH_ENCRYPTION_SECRET"));
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn app_state_new_rejects_invalid_database_url() {
        let mut config = test_config();
        config.database_url =
            Some("postgresql+psycopg://user:pass@127.0.0.1:notaport/db".to_string()); // pragma: allowlist secret

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
    fn app_state_new_accepts_database_url_with_sslmode_require() {
        let mut config = test_config();
        config.database_url =
            Some("postgresql+psycopg://user:pass@127.0.0.1:5432/db?sslmode=require".to_string()); // pragma: allowlist secret

        let state = AppState::new(&config).expect("state");

        assert!(state.db_pool().is_some());
    }

    #[test]
    fn app_state_new_rejects_missing_sslrootcert_file() {
        let mut config = test_config();
        config.database_url = Some(
            "postgresql+psycopg://user:pass@127.0.0.1:5432/db?sslmode=require&sslrootcert=/tmp/contextforge-missing-root-ca.pem".to_string(), // pragma: allowlist secret
        );

        let Err(error) = AppState::new(&config) else {
            panic!("missing sslrootcert should fail");
        };

        match error {
            RuntimeError::Config(message) => {
                // Can fail with sslrootcert error OR backend URL validation error
                assert!(
                    message.contains("sslrootcert") || message.contains("Backend URL validator"),
                    "Expected sslrootcert or validator error, got: {}",
                    message
                );
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn load_pem_certificates_accepts_valid_certificate_chain() {
        let path =
            std::env::temp_dir().join(format!("contextforge-root-ca-{}.pem", Uuid::new_v4()));
        let Some(root_cert_pem) = generate_test_root_cert_pem() else {
            return;
        };
        fs::write(&path, root_cert_pem).expect("write pem file");

        let certificates =
            load_pem_certificates(path.to_str().expect("utf-8 path")).expect("certificates");

        fs::remove_file(&path).expect("remove pem file");

        assert_eq!(certificates.len(), 1);
    }

    #[test]
    fn load_pem_certificates_rejects_non_certificate_pem() {
        let path = std::env::temp_dir().join(format!(
            "contextforge-invalid-root-ca-{}.pem",
            Uuid::new_v4()
        ));
        fs::write(
            &path,
            "-----BEGIN PUBLIC KEY-----\nZm9v\n-----END PUBLIC KEY-----\n",
        )
        .expect("write invalid pem file");

        let error = load_pem_certificates(path.to_str().expect("utf-8 path"))
            .expect_err("public key pem should fail");

        fs::remove_file(&path).expect("remove invalid pem file");

        match error {
            RuntimeError::Config(message) => {
                assert!(
                    message.contains("no certificates were parsed")
                        || message.contains("NoItemsFound")
                );
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn app_state_new_rejects_unsupported_client_certificate_parameters() {
        let mut config = test_config();
        config.database_url = Some(
            "postgresql+psycopg://user:pass@127.0.0.1:5432/db?sslmode=require&sslcert=/tmp/client.pem&sslkey=/tmp/client.key".to_string(), // pragma: allowlist secret
        );

        let Err(error) = AppState::new(&config) else {
            panic!("sslcert/sslkey should fail");
        };

        match error {
            RuntimeError::Config(message) => {
                assert!(message.contains("sslcert/sslkey"));
            }
            other => panic!("expected config error, got {other}"),
        }
    }

    #[test]
    fn normalize_postgres_database_url_strips_tls_only_query_parameters() {
        let (normalized_url, tls_options) = normalize_postgres_database_url(
            "postgresql+psycopg://user:pass@db.example.com:5432/mcp?sslmode=require&options=-c%20search_path%3Dmcp_gateway&sslrootcert=/tmp/root-ca.pem", // pragma: allowlist secret
        )
        .expect("normalized");
        let parsed = Url::parse(&normalized_url).expect("parsed");
        let query_pairs = parsed
            .query_pairs()
            .into_owned()
            .collect::<std::collections::HashMap<_, _>>();

        assert!(normalized_url.starts_with("postgresql://user:pass@db.example.com:5432/mcp?")); // pragma: allowlist secret
        assert!(!normalized_url.contains("sslrootcert"));
        assert_eq!(
            query_pairs.get("sslmode").map(String::as_str),
            Some("require")
        );
        assert_eq!(
            query_pairs.get("options").map(String::as_str),
            Some("-c search_path=mcp_gateway")
        );
        assert_eq!(
            tls_options.ssl_root_cert.as_deref(),
            Some("/tmp/root-ca.pem")
        );
        assert_eq!(tls_options.ssl_cert, None);
        assert_eq!(tls_options.ssl_key, None);
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

        let authz_derivations: [(&str, Deriver); 7] = [
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
                "_internal/mcp/tools/call/metric",
                derive_backend_tools_call_metric_url,
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
    async fn authenticate_public_request_strips_client_supplied_internal_headers_on_public_ingress()
    {
        let state = AppState::new(&test_config()).expect("state");
        let uri: Uri = "/mcp?session_id=abc".parse().expect("uri");
        let (headers, path) = authenticate_public_request_if_needed(
            &state,
            "GET",
            HeaderMap::new(),
            &uri,
            Some("server-1"),
            None,
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
        let captured = Arc::new(Mutex::new(None::<InternalAuthenticateRequest>));
        let captured_auth = captured.clone();
        let captured_request_headers = Arc::new(Mutex::new(None::<HashMap<String, String>>));
        let captured_request_headers_auth = captured_request_headers.clone();
        let backend = Router::new().route(
            "/_internal/mcp/authenticate",
            post(
                move |headers: HeaderMap, Json(request): Json<InternalAuthenticateRequest>| {
                    let captured_auth = captured_auth.clone();
                    let captured_request_headers_auth = captured_request_headers_auth.clone();
                    async move {
                        *captured_auth.lock().expect("lock") = Some(request);
                        *captured_request_headers_auth.lock().expect("lock") = Some(
                            headers
                                .iter()
                                .filter_map(|(name, value)| {
                                    value
                                        .to_str()
                                        .ok()
                                        .map(|value| (name.as_str().to_string(), value.to_string()))
                                })
                                .collect(),
                        );
                        Json(json!({
                            "authContext": {
                                "email": "trusted@example.com",
                                "teams": ["team-a"],
                                "is_authenticated": true,
                                "is_admin": false
                            }
                        }))
                    }
                },
            ),
        );
        let backend_url = spawn_router(backend).await;
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            HeaderValue::from_static("already-present"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-server-id"),
            HeaderValue::from_static("forged-server"),
        );
        let (headers, path) = authenticate_public_request_if_needed(
            &state,
            "GET",
            headers,
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
            Some(SocketAddr::from(([198, 51, 100, 9], 44444))),
        )
        .await
        .expect("public ingress auth");
        assert_eq!(path, "/mcp");
        let decoded_auth_context: Value = serde_json::from_slice(
            &URL_SAFE_NO_PAD
                .decode(
                    headers
                        .get("x-contextforge-auth-context")
                        .and_then(|value| value.to_str().ok())
                        .expect("auth context header"),
                )
                .expect("decode auth context"),
        )
        .expect("auth context json");
        assert_eq!(
            decoded_auth_context,
            json!({
                "email": "trusted@example.com",
                "teams": ["team-a"],
                "is_authenticated": true,
                "is_admin": false
            })
        );
        assert!(!headers.contains_key("x-contextforge-server-id"));

        let captured = captured
            .lock()
            .expect("lock")
            .clone()
            .expect("captured request");
        let captured_request_headers = captured_request_headers
            .lock()
            .expect("lock")
            .clone()
            .expect("captured request headers");
        assert!(!captured.headers.contains_key("x-contextforge-auth-context"));
        assert!(
            !captured
                .headers
                .contains_key("x-contextforge-mcp-runtime-auth")
        );
        assert!(!captured.headers.contains_key("x-contextforge-server-id"));
        assert_eq!(captured.client_ip.as_deref(), Some("198.51.100.9"));
        assert_eq!(
            captured_request_headers
                .get(RUNTIME_HEADER)
                .map(String::as_str),
            Some(RUNTIME_NAME)
        );
        assert!(captured_request_headers.contains_key(INTERNAL_RUNTIME_AUTH_HEADER));
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
            None,
        )
        .await
        .expect_err("unreachable backend should fail");
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
        let payload: Value = serde_json::from_slice(
            &to_bytes(response.into_body(), usize::MAX)
                .await
                .expect("body"),
        )
        .expect("json body");
        assert_eq!(payload["detail"], "Backend MCP authenticate failed");
        assert_eq!(payload["error"], CLIENT_ERROR_DETAIL);

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
            None,
        )
        .await
        .expect_err("invalid backend payload should fail");
        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
        let payload: Value = serde_json::from_slice(
            &to_bytes(response.into_body(), usize::MAX)
                .await
                .expect("body"),
        )
        .expect("json body");
        assert_eq!(payload["detail"], "Backend MCP authenticate decode failed");
        assert_eq!(payload["error"], CLIENT_ERROR_DETAIL);
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
    async fn public_router_does_not_expose_internal_event_store_routes() {
        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        let state = AppState::new(&config).expect("state");
        let runtime_url = spawn_router(build_public_router(state)).await;
        let client = reqwest::Client::new();

        let store = client
            .post(format!("{runtime_url}/_internal/event-store/store"))
            .json(&json!({
                "streamId": "stream-1",
                "message": {"hello": "world"},
            }))
            .send()
            .await
            .expect("store response");
        assert_eq!(store.status(), StatusCode::NOT_FOUND);

        let replay = client
            .post(format!("{runtime_url}/_internal/event-store/replay"))
            .json(&json!({
                "lastEventId": "event-1",
            }))
            .send()
            .await
            .expect("replay response");
        assert_eq!(replay.status(), StatusCode::NOT_FOUND);

        let health = client
            .get(format!("{runtime_url}/health"))
            .send()
            .await
            .expect("health response");
        let payload: Value = health.json().await.expect("health json");
        assert_eq!(payload, json!({"status": "ok", "runtime": "rust"}));
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
        // Keep session_core_enabled=true: the 405 gate (#4205) now blocks
        // GETs when session_core is disabled, so this test keeps session_core
        // on and disables live_stream to still exercise the backend fallthrough.
        config.live_stream_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "scoped-session".to_string(),
            RuntimeSessionRecord {
                owner_email: None,
                server_id: Some("server-xyz".to_string()),
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

        // GET requires a session id (see #4205); provide one so this test
        // continues to exercise the server-id-header injection path.
        let mut get_headers = HeaderMap::new();
        get_headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("scoped-session"),
        );
        let get_response = transport_get_server_scoped(
            State(state.clone()),
            AxumPath("server-xyz".to_string()),
            TrustedPeerAddr::default(),
            get_headers,
            "/servers/server-xyz/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(get_response.status(), StatusCode::OK);

        // ADR-052: DELETE without a session id returns 405 directly without
        // touching the backend (the spec frames DELETE as "client-initiated
        // termination — server MAY support, else 405", and there is nothing
        // to terminate without a session id). Verify the new contract; the
        // backend should NOT receive a DELETE call.
        let delete_response = transport_delete_server_scoped(
            State(state),
            AxumPath("server-xyz".to_string()),
            TrustedPeerAddr::default(),
            HeaderMap::new(),
            "/servers/server-xyz/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(delete_response.status(), StatusCode::METHOD_NOT_ALLOWED);
        let allow = delete_response
            .headers()
            .get("allow")
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default();
        assert!(
            allow.contains("DELETE"),
            "405 Allow header should advertise DELETE, got {allow:?}"
        );

        let calls = calls.lock().expect("lock");
        assert_eq!(
            *calls,
            vec![("GET".to_string(), Some("server-xyz".to_string()))],
            "session-less DELETE must not reach the backend (ADR-052)"
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
            TrustedPeerAddr::default(),
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(get_response.status(), StatusCode::BAD_GATEWAY);

        let delete_response = super::transport_delete(
            State(state.clone()),
            TrustedPeerAddr::default(),
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(delete_response.status(), StatusCode::BAD_GATEWAY);

        let post_response = super::rpc(
            State(state),
            TrustedPeerAddr::default(),
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
    async fn backend_dispatch_error_helpers_redact_client_visible_details() {
        let mut config = test_config();
        config.backend_rpc_url = "http://127.0.0.1:1/rpc".to_string();
        let state = AppState::new(&config).expect("state");
        let uri = "/mcp".parse::<Uri>().expect("uri");

        let transport_error = send_transport_to_backend(
            &state,
            reqwest::Method::POST,
            &HeaderMap::new(),
            &uri,
            Some(Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":1,"method":"ping"}"#,
            )),
            false,
        )
        .await
        .expect_err("unreachable backend should fail");
        assert_eq!(transport_error.status(), StatusCode::BAD_GATEWAY);
        let transport_payload: Value = serde_json::from_slice(
            &to_bytes(transport_error.into_body(), usize::MAX)
                .await
                .expect("body"),
        )
        .expect("json body");
        assert_eq!(transport_payload["data"], CLIENT_ERROR_DETAIL);

        let tools_list_error = send_tools_list_to_backend(&state, HeaderMap::new())
            .await
            .expect_err("unreachable backend should fail");
        assert_eq!(tools_list_error.status(), StatusCode::BAD_GATEWAY);
        let tools_list_payload: Value = serde_json::from_slice(
            &to_bytes(tools_list_error.into_body(), usize::MAX)
                .await
                .expect("body"),
        )
        .expect("json body");
        assert_eq!(tools_list_payload["error"]["data"], CLIENT_ERROR_DETAIL);
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
    fn sse_parser_helpers_cover_spec_edge_cases() {
        let mut frame = super::PendingSseFrame::default();
        parse_sse_line(&mut frame, ": keepalive");
        assert!(!frame.saw_field);

        parse_sse_line(&mut frame, "data: hello");
        parse_sse_line(&mut frame, "data:world");
        parse_sse_line(&mut frame, "id: event-1");
        parse_sse_line(&mut frame, "event: message");
        parse_sse_line(&mut frame, "retry: 1500");
        parse_sse_line(&mut frame, "foo: bar");
        let finalized = finalize_sse_frame(&mut frame).expect("frame should finalize");
        assert_eq!(finalized.id.as_deref(), Some("event-1"));
        assert_eq!(finalized.event.as_deref(), Some("message"));
        assert_eq!(finalized.data, "hello\nworld");
        assert_eq!(finalized.retry_ms, Some(1500));

        let mut invalid_retry = super::PendingSseFrame::default();
        parse_sse_line(&mut invalid_retry, "retry: nope");
        parse_sse_line(&mut invalid_retry, "data: payload");
        let invalid_retry = finalize_sse_frame(&mut invalid_retry).expect("invalid retry frame");
        assert_eq!(invalid_retry.retry_ms, None);
        assert_eq!(invalid_retry.data, "payload");

        let mut no_colon_frame = super::PendingSseFrame::default();
        parse_sse_line(&mut no_colon_frame, "data");
        let no_colon = finalize_sse_frame(&mut no_colon_frame).expect("empty data field");
        assert_eq!(no_colon.data, "");

        let mut comments_only = super::PendingSseFrame::default();
        parse_sse_line(&mut comments_only, ": still ignored");
        assert!(finalize_sse_frame(&mut comments_only).is_none());

        let mut empty = super::PendingSseFrame::default();
        assert!(finalize_sse_frame(&mut empty).is_none());
    }

    #[tokio::test]
    async fn read_next_sse_frame_handles_chunk_boundaries_and_eof_flush() {
        let mut stream = stream::iter(vec![
            Ok::<_, reqwest::Error>(Bytes::from_static(b"event: endpoint\r\n")),
            Ok::<_, reqwest::Error>(Bytes::from_static(b"data: /messages")),
            Ok::<_, reqwest::Error>(Bytes::from_static(b"\r\n\r\n")),
            Ok::<_, reqwest::Error>(Bytes::from_static(b"id: 7\r\n")),
            Ok::<_, reqwest::Error>(Bytes::from_static(b"data: {\"ok\":")),
            Ok::<_, reqwest::Error>(Bytes::from_static(b"true}\r\n\r\n")),
        ]);
        let mut buffer = BytesMut::new();
        let mut frame = super::PendingSseFrame::default();

        let endpoint = read_next_sse_frame(&mut stream, &mut buffer, &mut frame, 100)
            .await
            .expect("endpoint frame")
            .expect("endpoint payload");
        assert_eq!(endpoint.event.as_deref(), Some("endpoint"));
        assert_eq!(endpoint.data, "/messages");

        let message = read_next_sse_frame(&mut stream, &mut buffer, &mut frame, 100)
            .await
            .expect("message frame")
            .expect("message payload");
        assert_eq!(message.id.as_deref(), Some("7"));
        assert_eq!(message.data, "{\"ok\":true}");

        let mut eof_stream = stream::iter(vec![Ok::<_, reqwest::Error>(Bytes::from_static(
            b"data: tail-without-terminator",
        ))]);
        let mut eof_buffer = BytesMut::new();
        let mut eof_frame = super::PendingSseFrame::default();
        let eof_message =
            read_next_sse_frame(&mut eof_stream, &mut eof_buffer, &mut eof_frame, 100)
                .await
                .expect("eof frame")
                .expect("eof payload");
        assert_eq!(eof_message.data, "tail-without-terminator");
    }

    #[tokio::test]
    async fn build_forwarded_sse_event_and_payload_decoders_cover_edge_cases() {
        let frame = super::FinalizedSseFrame {
            id: Some("event-7".to_string()),
            event: Some("message".to_string()),
            data: "line one\nline two".to_string(),
            retry_ms: Some(2500),
        };
        let response = Sse::new(stream::iter(vec![Ok::<_, Infallible>(
            build_forwarded_sse_event(&frame),
        )]))
        .into_response();
        let encoded = String::from_utf8(
            to_bytes(response.into_body(), usize::MAX)
                .await
                .expect("encoded event body")
                .to_vec(),
        )
        .expect("utf-8 body");
        assert!(encoded.contains("id: event-7"));
        assert!(encoded.contains("event: message"));
        assert!(encoded.contains("retry: 2500"));
        assert!(encoded.contains("data: line one"));
        assert!(encoded.contains("data: line two"));

        assert_eq!(
            extract_first_sse_data_payload("data: first\n\ndata: second\n\n"),
            Some("first".to_string())
        );
        assert_eq!(
            extract_first_sse_data_payload("data: first\ndata: second"),
            Some("first\nsecond".to_string())
        );
        assert_eq!(extract_first_sse_data_payload("event: message\n\n"), None);
        assert_eq!(
            extract_first_sse_data_payload("data:   padded value\n\n"),
            Some("padded value".to_string())
        );

        let sse_json = decode_upstream_json_payload_bytes(
            br#"data: {"ok":true}

"#,
            "text/event-stream",
        )
        .expect("valid SSE JSON");
        assert_eq!(sse_json["ok"], json!(true));

        let inferred_sse = decode_upstream_json_payload_bytes(br#"data: {"via":"prefix"}"#, "")
            .expect("body prefix infers SSE");
        assert_eq!(inferred_sse["via"], json!("prefix"));

        let plain_json =
            decode_upstream_json_payload_bytes(br#"{"plain":true}"#, "application/json")
                .expect("plain JSON");
        assert_eq!(plain_json["plain"], json!(true));

        let invalid_sse =
            decode_upstream_json_payload_bytes(b"data: not-json\n\n", "text/event-stream")
                .expect_err("invalid SSE JSON should fail");
        assert!(invalid_sse.contains("invalid SSE JSON payload"));

        let empty_json = decode_upstream_json_payload_bytes(b"", "application/json")
            .expect_err("empty JSON body should fail");
        assert!(empty_json.contains("invalid JSON payload"));
    }

    #[test]
    fn client_ip_and_session_auth_reuse_helpers_cover_edge_cases() {
        let mut headers = HeaderMap::new();
        assert_eq!(public_client_ip(&headers, None), None);
        let trust_proxy_auth = std::env::var("TRUST_PROXY_AUTH").ok();
        let trust_proxy_auth_dangerously = std::env::var("TRUST_PROXY_AUTH_DANGEROUSLY").ok();

        headers.insert(
            HeaderName::from_static("x-forwarded-for"),
            HeaderValue::from_static(" 198.51.100.10 , 203.0.113.5 "),
        );
        assert_eq!(
            public_client_ip(&headers, Some(SocketAddr::from(([127, 0, 0, 1], 8080)))),
            Some("127.0.0.1".to_string())
        );

        // SAFETY: test-only env override restored before return.
        unsafe {
            std::env::set_var("TRUST_PROXY_AUTH", "true");
            std::env::set_var("TRUST_PROXY_AUTH_DANGEROUSLY", "true");
        }
        assert_eq!(
            public_client_ip(&headers, Some(SocketAddr::from(([127, 0, 0, 1], 8080)))),
            Some("198.51.100.10".to_string())
        );

        headers.insert(
            HeaderName::from_static("x-real-ip"),
            HeaderValue::from_static("203.0.113.9"),
        );
        assert_eq!(
            public_client_ip(&headers, Some(SocketAddr::from(([127, 0, 0, 1], 8080)))),
            Some("203.0.113.9".to_string())
        );
        assert_eq!(
            public_client_ip(&headers, Some(SocketAddr::from(([198, 51, 100, 77], 9000)))),
            Some("198.51.100.77".to_string())
        );
        if let Some(value) = trust_proxy_auth {
            // SAFETY: restore original process-wide env var before the test exits.
            unsafe {
                std::env::set_var("TRUST_PROXY_AUTH", value);
            }
        } else {
            // SAFETY: remove temporary test env var before exit.
            unsafe {
                std::env::remove_var("TRUST_PROXY_AUTH");
            }
        }
        if let Some(value) = trust_proxy_auth_dangerously {
            // SAFETY: restore original process-wide env var before the test exits.
            unsafe {
                std::env::set_var("TRUST_PROXY_AUTH_DANGEROUSLY", value);
            }
        } else {
            // SAFETY: remove temporary test env var before exit.
            unsafe {
                std::env::remove_var("TRUST_PROXY_AUTH_DANGEROUSLY");
            }
        }
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
            Ok("encoded-context".to_string())
        );
        assert_eq!(
            can_reuse_session_auth(&state, &record, &auth_headers, Some("server-2")),
            Err(SessionAuthReuseMissReason::ServerScopeMismatch)
        );

        let mut mismatched_headers = HeaderMap::new();
        mismatched_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer beta"),
        );
        assert_eq!(
            can_reuse_session_auth(&state, &record, &mismatched_headers, Some("server-1")),
            Err(SessionAuthReuseMissReason::AuthBindingMismatch)
        );

        let expired = RuntimeSessionRecord {
            auth_context_expires_at_epoch_ms: Some(now.saturating_sub(1)),
            ..record.clone()
        };
        assert_eq!(
            can_reuse_session_auth(&state, &expired, &auth_headers, Some("server-1")),
            Err(SessionAuthReuseMissReason::TtlExpired)
        );

        let mut disabled_config = test_config();
        disabled_config.session_auth_reuse_enabled = false;
        let disabled_state = AppState::new(&disabled_config).expect("state");
        assert_eq!(
            can_reuse_session_auth(&disabled_state, &record, &auth_headers, Some("server-1")),
            Err(SessionAuthReuseMissReason::Disabled)
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
        assert_eq!(
            pool_owner_key(&state, "session-1"),
            "mcpgw:test:pool_owner:session-1"
        );

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
            team_name: Some("Team 1".to_string()),
            auth_method: Some("jwt".to_string()),
            permission_is_admin: Some(false),
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
        assert!(runtime_session_access_outcome(&record, Some(&auth_context), &headers).is_ok());

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
        assert_eq!(
            state
                .runtime_stats()
                .snapshot()
                .session_access_denials
                .server_scope_mismatches,
            1
        );

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
        let runtime_stats = state.runtime_stats().snapshot();
        assert_eq!(
            runtime_stats.session_access_denials.auth_binding_mismatches,
            1
        );
    }

    #[tokio::test]
    async fn authenticate_public_request_updates_runtime_stats_for_reuse_hits_and_misses() {
        let backend = Router::new().route(
            "/_internal/mcp/authenticate",
            post(|| async move {
                Json(json!({
                    "authContext": {
                        "email": "owner@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": true,
                        "is_admin": false,
                        "permission_is_admin": false,
                        "token_use": "session"
                    }
                }))
            }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.public_listen_http = Some(free_tcp_addr());
        config.session_core_enabled = true;
        config.session_auth_reuse_enabled = true;
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        let auth_context_json = json!({
            "email": "owner@example.com",
            "teams": ["team-a"],
            "is_authenticated": true
        });
        let encoded_auth_context =
            encode_internal_auth_context_header(&auth_context_json).expect("auth context");
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer alpha"),
        );
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("session-hit"),
        );
        headers.insert(
            HeaderName::from_static("x-contextforge-auth-context"),
            encoded_auth_context.clone(),
        );
        let fingerprint = auth_binding_fingerprint(&headers).expect("fingerprint");
        upsert_runtime_session(
            &state,
            "session-hit".to_string(),
            RuntimeSessionRecord {
                owner_email: Some("owner@example.com".to_string()),
                server_id: None,
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: Some(
                    encoded_auth_context
                        .to_str()
                        .expect("encoded auth context str")
                        .to_string(),
                ),
                auth_binding_fingerprint: Some(fingerprint),
                auth_context_expires_at_epoch_ms: Some(super::unix_epoch_millis() + 60_000),
                created_at: std::time::Instant::now(),
                last_used: std::time::Instant::now(),
            },
        )
        .await;

        let (returned_headers, _) = authenticate_public_request_if_needed(
            &state,
            "POST",
            headers.clone(),
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
            None,
        )
        .await
        .expect("reused auth context");
        assert!(returned_headers.contains_key("x-contextforge-auth-context"));

        let mut miss_headers = HeaderMap::new();
        miss_headers.insert(
            HeaderName::from_static("authorization"),
            HeaderValue::from_static("Bearer beta"),
        );
        miss_headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("session-hit"),
        );
        let (_returned_headers, _path) = authenticate_public_request_if_needed(
            &state,
            "POST",
            miss_headers,
            &"/mcp".parse::<Uri>().expect("uri"),
            None,
            None,
        )
        .await
        .expect("backend auth fallback succeeds");

        let runtime_stats = state.runtime_stats().snapshot();
        assert_eq!(runtime_stats.session_auth_reuse.hits, 1);
        assert_eq!(runtime_stats.session_auth_reuse.misses, 1);
        assert_eq!(
            runtime_stats.session_auth_reuse.miss_auth_binding_mismatch,
            1
        );
        assert_eq!(runtime_stats.session_auth_reuse.backend_auth_round_trips, 1);
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
        assert!(!response.headers().contains_key("x-custom"));
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
            team_name: Some("Team 1".to_string()),
            auth_method: Some("jwt".to_string()),
            permission_is_admin: Some(false),
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
                    ("x-request-id".to_string(), "request-123".to_string()),
                    ("set-cookie".to_string(), "secret=1".to_string()),
                    ("authorization".to_string(), "Bearer hidden".to_string()),
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
        assert_eq!(
            response
                .headers()
                .get("x-request-id")
                .and_then(|value| value.to_str().ok()),
            Some("request-123")
        );
        assert!(!response.headers().contains_key("set-cookie"));
        assert!(!response.headers().contains_key("authorization"));
        assert!(!response.headers().contains_key("content-length"));
        assert!(!response.headers().contains_key("connection"));

        let error = affinity_forward_error_response("publish failed", "boom");
        assert_eq!(error.status(), StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn direct_server_list_methods_fall_back_without_trusted_context() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/resources/list",
                post(|| async { Json(json!({"marker": "resources-list"})) }),
            )
            .route(
                "/_internal/mcp/resources/templates/list",
                post(|| async { Json(json!({"marker": "resource-templates-list"})) }),
            )
            .route(
                "/_internal/mcp/prompts/list",
                post(|| async { Json(json!({"marker": "prompts-list"})) }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        let resources_response =
            direct_server_resources_list(&state, HeaderMap::new(), Some(json!(1))).await;
        assert_eq!(resources_response.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_response).await["result"]["marker"],
            "resources-list"
        );

        let templates_response =
            direct_server_resource_templates_list(&state, HeaderMap::new(), Some(json!(2))).await;
        assert_eq!(templates_response.status(), StatusCode::OK);
        assert_eq!(
            response_json(templates_response).await["result"]["marker"],
            "resource-templates-list"
        );

        let prompts_response =
            direct_server_prompts_list(&state, HeaderMap::new(), Some(json!(3))).await;
        assert_eq!(prompts_response.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_response).await["result"]["marker"],
            "prompts-list"
        );
    }

    #[tokio::test]
    async fn direct_server_read_methods_fall_back_for_missing_required_params() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/resources/read",
                post(|| async { Json(json!({"marker": "resources-read"})) }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(|| async { Json(json!({"marker": "prompts-get"})) }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");
        let trusted_headers = trusted_server_headers("server-1");

        let resources_request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "resources/read".to_string(),
            params: json!({}),
            id: Some(json!(11)),
        };
        let resources_response = direct_server_resources_read(
            &state,
            trusted_headers.clone(),
            Some(json!(11)),
            &resources_request,
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":11,"method":"resources/read","params":{}}"#,
            ),
        )
        .await;
        assert_eq!(resources_response.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_response).await["result"]["marker"],
            "resources-read"
        );

        let prompts_request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "prompts/get".to_string(),
            params: json!({}),
            id: Some(json!(12)),
        };
        let prompts_response = direct_server_prompts_get(
            &state,
            trusted_headers,
            Some(json!(12)),
            &prompts_request,
            Bytes::from_static(br#"{"jsonrpc":"2.0","id":12,"method":"prompts/get","params":{}}"#),
        )
        .await;
        assert_eq!(prompts_response.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_response).await["result"]["marker"],
            "prompts-get"
        );
    }

    #[tokio::test]
    async fn direct_server_prompts_get_falls_back_when_arguments_are_supplied() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/prompts/get/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(|| async {
                    Json(json!({
                        "description": "rendered",
                        "messages": [{
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": "Rendered prompt for America/New_York and Europe/Dublin"
                            }
                        }]
                    }))
                }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        let response = direct_server_prompts_get(
            &state,
            trusted_server_headers("server-1"),
            Some(json!(31)),
            &JsonRpcRequest {
                jsonrpc: Some("2.0".to_string()),
                method: "prompts/get".to_string(),
                params: json!({
                    "name": "fast-time-convert-time-detailed",
                    "arguments": {
                        "time": "2025-01-15T12:00:00Z",
                        "from_timezone": "UTC",
                        "to_timezones": "America/New_York,Europe/Dublin",
                    }
                }),
                id: Some(json!(31)),
            },
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":31,"method":"prompts/get","params":{"name":"fast-time-convert-time-detailed","arguments":{"time":"2025-01-15T12:00:00Z","from_timezone":"UTC","to_timezones":"America/New_York,Europe/Dublin"}}}"#,
            ),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["result"]["description"], "rendered");
        assert_eq!(
            payload["result"]["messages"][0]["content"]["text"],
            "Rendered prompt for America/New_York and Europe/Dublin"
        );
    }

    #[tokio::test]
    async fn direct_server_prompts_get_rejects_non_string_argument_values() {
        let state = AppState::new(&test_config()).expect("state");

        let response = direct_server_prompts_get(
            &state,
            trusted_server_headers("server-1"),
            Some(json!(32)),
            &JsonRpcRequest {
                jsonrpc: Some("2.0".to_string()),
                method: "prompts/get".to_string(),
                params: json!({
                    "name": "fast-time-convert-time-detailed",
                    "arguments": {
                        "target_timezones": ["America/New_York", "Europe/Dublin"]
                    }
                }),
                id: Some(json!(32)),
            },
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":32,"method":"prompts/get","params":{"name":"fast-time-convert-time-detailed","arguments":{"target_timezones":["America/New_York","Europe/Dublin"]}}}"#,
            ),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["error"]["code"], -32602);
        assert_eq!(
            payload["error"]["message"],
            "Prompt argument 'target_timezones' must be a string value"
        );
    }

    #[tokio::test]
    async fn direct_server_methods_fall_back_after_authz_success_without_db_pool() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/resources/list/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/resources/templates/list/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/prompts/list/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/resources/read/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/prompts/get/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/resources/list",
                post(|| async { Json(json!({"marker": "resources-list-db-fallback"})) }),
            )
            .route(
                "/_internal/mcp/resources/templates/list",
                post(|| async { Json(json!({"marker": "resource-templates-db-fallback"})) }),
            )
            .route(
                "/_internal/mcp/prompts/list",
                post(|| async { Json(json!({"marker": "prompts-list-db-fallback"})) }),
            )
            .route(
                "/_internal/mcp/resources/read",
                post(|| async { Json(json!({"marker": "resources-read-db-fallback"})) }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(|| async { Json(json!({"marker": "prompts-get-db-fallback"})) }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");
        let trusted_headers = trusted_server_headers("server-1");

        let resources_list =
            direct_server_resources_list(&state, trusted_headers.clone(), Some(json!(21))).await;
        assert_eq!(resources_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_list).await["result"]["marker"],
            "resources-list-db-fallback"
        );

        let templates_list =
            direct_server_resource_templates_list(&state, trusted_headers.clone(), Some(json!(22)))
                .await;
        assert_eq!(templates_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(templates_list).await["result"]["marker"],
            "resource-templates-db-fallback"
        );

        let prompts_list =
            direct_server_prompts_list(&state, trusted_headers.clone(), Some(json!(23))).await;
        assert_eq!(prompts_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_list).await["result"]["marker"],
            "prompts-list-db-fallback"
        );

        let resources_request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "resources/read".to_string(),
            params: json!({"uri": "time://formats"}),
            id: Some(json!(24)),
        };
        let resources_read = direct_server_resources_read(
            &state,
            trusted_headers.clone(),
            Some(json!(24)),
            &resources_request,
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":24,"method":"resources/read","params":{"uri":"time://formats"}}"#,
            ),
        )
        .await;
        assert_eq!(resources_read.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_read).await["result"]["marker"],
            "resources-read-db-fallback"
        );

        let prompts_request = JsonRpcRequest {
            jsonrpc: Some("2.0".to_string()),
            method: "prompts/get".to_string(),
            params: json!({"name": "hello"}),
            id: Some(json!(25)),
        };
        let prompts_get = direct_server_prompts_get(
            &state,
            trusted_headers,
            Some(json!(25)),
            &prompts_request,
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":25,"method":"prompts/get","params":{"name":"hello"}}"#,
            ),
        )
        .await;
        assert_eq!(prompts_get.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_get).await["result"]["marker"],
            "prompts-get-db-fallback"
        );
    }

    #[tokio::test]
    async fn direct_server_methods_return_structured_authz_errors_before_db_fallback() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/resources/list/authz",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"detail": "resources/list denied"})),
                    )
                }),
            )
            .route(
                "/_internal/mcp/resources/templates/list/authz",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"detail": "templates denied"})),
                    )
                }),
            )
            .route(
                "/_internal/mcp/prompts/list/authz",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"detail": "prompts/list denied"})),
                    )
                }),
            )
            .route(
                "/_internal/mcp/resources/read/authz",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"detail": "resources/read denied"})),
                    )
                }),
            )
            .route(
                "/_internal/mcp/prompts/get/authz",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"detail": "prompts/get denied"})),
                    )
                }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");
        let trusted_headers = trusted_server_headers("server-1");

        let resources_list =
            direct_server_resources_list(&state, trusted_headers.clone(), Some(json!(26))).await;
        assert_eq!(resources_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_list).await["error"]["detail"],
            "resources/list denied"
        );

        let templates_list =
            direct_server_resource_templates_list(&state, trusted_headers.clone(), Some(json!(27)))
                .await;
        assert_eq!(templates_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(templates_list).await["error"]["detail"],
            "templates denied"
        );

        let prompts_list =
            direct_server_prompts_list(&state, trusted_headers.clone(), Some(json!(28))).await;
        assert_eq!(prompts_list.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_list).await["error"]["detail"],
            "prompts/list denied"
        );

        let resources_read = direct_server_resources_read(
            &state,
            trusted_headers.clone(),
            Some(json!(29)),
            &JsonRpcRequest {
                jsonrpc: Some("2.0".to_string()),
                method: "resources/read".to_string(),
                params: json!({"uri": "time://formats"}),
                id: Some(json!(29)),
            },
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":29,"method":"resources/read","params":{"uri":"time://formats"}}"#,
            ),
        )
        .await;
        assert_eq!(resources_read.status(), StatusCode::OK);
        assert_eq!(
            response_json(resources_read).await["error"]["detail"],
            "resources/read denied"
        );

        let prompts_get = direct_server_prompts_get(
            &state,
            trusted_headers,
            Some(json!(30)),
            &JsonRpcRequest {
                jsonrpc: Some("2.0".to_string()),
                method: "prompts/get".to_string(),
                params: json!({"name": "time_prompt"}),
                id: Some(json!(30)),
            },
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":30,"method":"prompts/get","params":{"name":"time_prompt"}}"#,
            ),
        )
        .await;
        assert_eq!(prompts_get.status(), StatusCode::OK);
        assert_eq!(
            response_json(prompts_get).await["error"]["detail"],
            "prompts/get denied"
        );
    }

    #[tokio::test]
    async fn authorize_server_method_via_backend_covers_success_denial_and_decode_failure() {
        let backend = Router::new()
            .route("/authz-ok", post(|| async { StatusCode::OK }))
            .route(
                "/authz-fallback",
                post(|| async {
                    (
                        StatusCode::OK,
                        Json(json!({
                            "directExecutionEligible": false,
                            "fallbackReason": "resource-hooks-configured",
                        })),
                    )
                }),
            )
            .route(
                "/authz-deny",
                post(|| async {
                    (
                        StatusCode::FORBIDDEN,
                        Json(json!({"code": "denied", "detail": "nope"})),
                    )
                }),
            )
            .route(
                "/authz-bad-json",
                post(|| async { (StatusCode::FORBIDDEN, "not-json") }),
            );
        let backend_url = spawn_router(backend).await;
        let state = AppState::new(&{
            let mut config = test_config();
            config.backend_rpc_url = format!("{backend_url}/rpc");
            config
        })
        .expect("state");

        let authz_ok = authorize_server_method_via_backend(
            &state,
            &trusted_server_headers("server-1"),
            Some(json!(31)),
            &format!("{backend_url}/authz-ok"),
            "resources/list",
        )
        .await
        .expect("success should pass through");
        assert_eq!(authz_ok, DirectExecutionAuthorization::default());

        let authz_fallback = authorize_server_method_via_backend(
            &state,
            &trusted_server_headers("server-1"),
            Some(json!(31)),
            &format!("{backend_url}/authz-fallback"),
            "resources/read",
        )
        .await
        .expect("success payload should decode");
        assert_eq!(
            authz_fallback,
            DirectExecutionAuthorization {
                direct_execution_eligible: false,
                fallback_reason: Some("resource-hooks-configured".to_string()),
            }
        );

        let denied = authorize_server_method_via_backend(
            &state,
            &trusted_server_headers("server-1"),
            Some(json!(32)),
            &format!("{backend_url}/authz-deny"),
            "resources/list",
        )
        .await
        .expect_err("deny should return response");
        assert_eq!(denied.status(), StatusCode::OK);
        assert_eq!(response_json(denied).await["error"]["code"], "denied");

        let bad_json = authorize_server_method_via_backend(
            &state,
            &trusted_server_headers("server-1"),
            Some(json!(33)),
            &format!("{backend_url}/authz-bad-json"),
            "resources/list",
        )
        .await
        .expect_err("invalid deny payload should return response");
        assert_eq!(bad_json.status(), StatusCode::BAD_GATEWAY);
        assert_eq!(
            response_json(bad_json).await["error"]["data"],
            CLIENT_ERROR_DETAIL
        );
    }

    #[test]
    fn prompt_arguments_from_schema_covers_edge_cases() {
        assert!(prompt_arguments_from_schema(None).is_empty());
        assert!(prompt_arguments_from_schema(Some(json!("bad"))).is_empty());
        assert!(prompt_arguments_from_schema(Some(json!({"type": "object"}))).is_empty());

        let arguments = prompt_arguments_from_schema(Some(json!({
            "type": "object",
            "properties": {
                "name": {"description": "Person name"},
                "age": {}
            },
            "required": ["name", 123]
        })));
        assert_eq!(arguments.len(), 2);
        assert!(arguments.iter().any(|value| {
            value["name"] == "name"
                && value["description"] == "Person name"
                && value["required"] == true
        }));
        assert!(arguments.iter().any(|value| {
            value["name"] == "age" && value["description"] == "" && value["required"] == false
        }));
    }

    #[test]
    fn normalize_tool_input_schema_adds_empty_required_for_object_schemas() {
        let normalized = normalize_tool_input_schema(Some(json!({
            "type": "object",
            "properties": {
                "timezone": {"type": "string"}
            }
        })));

        assert_eq!(normalized["required"], json!([]));
        assert_eq!(normalized["properties"]["timezone"]["type"], "string");
    }

    #[test]
    fn normalize_tool_input_schema_preserves_existing_required_values() {
        let normalized = normalize_tool_input_schema(Some(json!({
            "type": "object",
            "properties": {
                "time": {"type": "string"}
            },
            "required": ["time"]
        })));

        assert_eq!(normalized["required"], json!(["time"]));
    }

    #[tokio::test]
    async fn direct_server_prompts_get_wraps_backend_not_found_as_jsonrpc_ok_response() {
        let backend = Router::new()
            .route(
                "/_internal/mcp/prompts/get/authz",
                post(|| async { StatusCode::OK }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(|| async {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({
                            "code": -32002,
                            "message": "Prompt not found",
                            "data": {"name": "missing"}
                        })),
                    )
                }),
            );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        let response = direct_server_prompts_get(
            &state,
            trusted_server_headers("server-1"),
            Some(json!(41)),
            &JsonRpcRequest {
                jsonrpc: Some("2.0".to_string()),
                method: "prompts/get".to_string(),
                params: json!({"name": "missing"}),
                id: Some(json!(41)),
            },
            Bytes::from_static(
                br#"{"jsonrpc":"2.0","id":41,"method":"prompts/get","params":{"name":"missing"}}"#,
            ),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let payload = response_json(response).await;
        assert_eq!(payload["id"], 41);
        assert_eq!(payload["error"]["code"], -32002);
        assert_eq!(payload["error"]["message"], "Prompt not found");
    }

    #[test]
    fn tools_call_error_type_from_payload_maps_common_jsonrpc_codes() {
        assert_eq!(
            tools_call_error_type_from_payload(
                &json!({"error": {"code": -32003, "message": "forbidden"}}),
            ),
            "PermissionDenied"
        );
        assert_eq!(
            tools_call_error_type_from_payload(
                &json!({"error": {"code": -32602, "message": "bad params"}}),
            ),
            "InvalidRequest"
        );
        assert_eq!(
            tools_call_error_type_from_payload(
                &json!({"error": {"code": -32700, "message": "parse"}}),
            ),
            "ParseError"
        );
        assert_eq!(
            tools_call_error_type_from_payload(
                &json!({"error": {"code": -32001, "message": "other"}}),
            ),
            "ToolInvocationError"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_delete_removes_runtime_session_and_sets_core_headers() {
        let backend = Router::new().route(
            "/_internal/mcp/session",
            axum::routing::delete(|| async { StatusCode::NO_CONTENT }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "delete-me".to_string(),
            RuntimeSessionRecord {
                owner_email: Some("owner@example.com".to_string()),
                server_id: Some("server-1".to_string()),
                protocol_version: None,
                client_capabilities: None,
                encoded_auth_context: Some("cached".to_string()),
                auth_binding_fingerprint: Some(
                    auth_binding_fingerprint(&trusted_server_headers("server-1"))
                        .expect("fingerprint"),
                ),
                auth_context_expires_at_epoch_ms: None,
                created_at: std::time::Instant::now(),
                last_used: std::time::Instant::now(),
            },
        )
        .await;

        let mut headers = trusted_server_headers("server-1");
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("delete-me"),
        );
        let response = forward_transport_request(
            &state,
            reqwest::Method::DELETE,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NO_CONTENT);
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-session-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-event-store")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-resume-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-live-stream-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-affinity-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert!(get_runtime_session(&state, "delete-me").await.is_none());
    }

    #[tokio::test]
    async fn forward_transport_request_get_forwards_to_backend_and_sets_session_hint_headers() {
        let backend = Router::new().route(
            "/_internal/mcp/transport",
            axum::routing::get(|| async { Json(json!({"ok": true, "path": "transport"})) }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        config.live_stream_core_enabled = false;
        config.affinity_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "read-session".to_string(),
            RuntimeSessionRecord {
                owner_email: None,
                server_id: Some("server-1".to_string()),
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

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("read-session"),
        );
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp?session_id=ignored".parse::<Uri>().expect("uri"),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("mcp-session-id")
                .and_then(|value| value.to_str().ok()),
            Some("read-session")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-session-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-event-store")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        assert_eq!(response_json(response).await["ok"], json!(true));
    }

    #[tokio::test]
    async fn forward_transport_request_delete_backend_failure_keeps_runtime_session() {
        let backend = Router::new().route(
            "/_internal/mcp/session",
            axum::routing::delete(|| async {
                (
                    StatusCode::BAD_GATEWAY,
                    Json(json!({"detail": "backend delete failed"})),
                )
            }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "delete-error".to_string(),
            RuntimeSessionRecord {
                owner_email: None,
                server_id: Some("server-1".to_string()),
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

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("delete-error"),
        );
        let response = forward_transport_request(
            &state,
            reqwest::Method::DELETE,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;

        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
        assert_eq!(
            response_json(response).await["detail"],
            json!("backend delete failed")
        );
        assert!(get_runtime_session(&state, "delete-error").await.is_some());
    }

    #[tokio::test]
    async fn handle_resume_transport_request_requires_last_event_id_header() {
        let state = AppState::new(&test_config()).expect("state");
        let response = handle_resume_transport_request(
            &state,
            HeaderMap::new(),
            "/mcp".parse::<Uri>().expect("uri"),
            None,
        )
        .await;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            response_json(response).await["detail"],
            "Last-Event-ID header is required for resumable GET /mcp"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_resumable_get_requires_session_id() {
        let state = AppState::new(&test_config()).expect("state");
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream"),
        );
        headers.insert(
            HeaderName::from_static("last-event-id"),
            HeaderValue::from_static("event-1"),
        );

        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            response_json(response).await["detail"],
            "mcp-session-id header or session_id query parameter is required for resumable GET /mcp"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_get_without_session_id_returns_method_not_allowed() {
        // #4205: A passive GET SSE stream cannot be served without a session
        // id to anchor it to. 405 + Allow + capability headers + counter tick.
        // Also asserts the session-core-disabled subcounter does NOT tick on
        // this branch, so the split counter stays trustworthy for ops.
        // The 405 gate sits INSIDE the live-stream branch — the request must
        // present `accept: text/event-stream` to reach it; otherwise the GET
        // falls through to the Python transport bridge proxy.
        let state = AppState::new(&test_config()).expect("state");
        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream"),
        );
        let before = state.runtime_stats().snapshot().transport;
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        assert_eq!(
            response
                .headers()
                .get("allow")
                .and_then(|value| value.to_str().ok()),
            Some("POST, DELETE")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-session-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust"),
            "405 response should carry the same capability headers as other terminal responses"
        );
        let body_detail = response_json(response).await["detail"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        assert!(
            body_detail.starts_with("Passive SSE stream requires an Mcp-Session-Id"),
            "unexpected 405 detail: {body_detail}"
        );
        let after = state.runtime_stats().snapshot().transport;
        assert_eq!(
            after.get_rejected_no_session,
            before.get_rejected_no_session + 1,
            "total 405 counter should tick"
        );
        assert_eq!(
            after.get_rejected_session_core_disabled, before.get_rejected_session_core_disabled,
            "session-core-disabled subcounter must NOT tick on the no-session-id branch"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_get_returns_405_when_session_core_disabled_even_with_header()
    {
        // #4205 regression guard: without session_core, Rust can't anchor an
        // SSE stream to a validated session. Even a GET that presents a
        // session header must be 405'd — otherwise live_stream_core would
        // commit to a `text/event-stream` response and relay an empty stream.
        // Also asserts this branch ticks BOTH the total counter AND the
        // session-core-disabled subcounter (the deployment-config signal
        // ops filter on).
        let mut config = test_config();
        config.session_core_enabled = false;
        config.live_stream_core_enabled = true;
        let state = AppState::new(&config).expect("state");

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("client-supplied-id"),
        );
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream"),
        );

        let before = state.runtime_stats().snapshot().transport;
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
        let body_detail = response_json(response).await["detail"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        assert!(
            body_detail.contains("session management is disabled"),
            "unexpected 405 detail: {body_detail}"
        );
        let after = state.runtime_stats().snapshot().transport;
        assert_eq!(
            after.get_rejected_no_session,
            before.get_rejected_no_session + 1,
            "total 405 counter should tick for session-core-disabled branch"
        );
        assert_eq!(
            after.get_rejected_session_core_disabled,
            before.get_rejected_session_core_disabled + 1,
            "session-core-disabled subcounter should tick for this branch"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_get_with_session_id_reaches_live_stream_branch() {
        // #4205 regression guard: the 405 short-circuit must not pre-empt the
        // live-stream branch when a session id IS presented. We set up a
        // backend that returns a valid SSE response so handle_live_stream
        // streams it back.
        let backend = Router::new().route(
            "/_internal/mcp/transport",
            axum::routing::get(|| async {
                (
                    StatusCode::OK,
                    [(
                        "content-type",
                        HeaderValue::from_static("text/event-stream"),
                    )],
                    "data: ok\n\n",
                )
            }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        config.affinity_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "live-session".to_string(),
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

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("live-session"),
        );
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream"),
        );

        let before = state.runtime_stats().snapshot().transport;
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|value| value.to_str().ok()),
            Some("text/event-stream")
        );
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-live-stream-core")
                .and_then(|value| value.to_str().ok()),
            Some("rust")
        );
        let after = state.runtime_stats().snapshot().transport;
        assert_eq!(
            after.get_rejected_no_session, before.get_rejected_no_session,
            "happy-path GET must not tick the 405 counter"
        );
        assert_eq!(
            after.get_rejected_session_core_disabled, before.get_rejected_session_core_disabled,
            "happy-path GET must not tick the session-core-disabled subcounter"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_get_with_session_id_query_param_is_accepted() {
        // #4205: A session id provided via query parameter should be accepted
        // (mirrors runtime_session_id_from_request which checks both header
        // and `session_id` query param).
        let backend = Router::new().route(
            "/_internal/mcp/transport",
            axum::routing::get(|| async { Json(json!({"ok": true})) }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        config.live_stream_core_enabled = false;
        config.affinity_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "qp-session".to_string(),
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

        let before = state.runtime_stats().snapshot().transport;
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            HeaderMap::new(),
            "/mcp".to_string(),
            "/mcp?session_id=qp-session".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::OK);
        let after = state.runtime_stats().snapshot().transport;
        assert_eq!(
            after.get_rejected_no_session, before.get_rejected_no_session,
            "query-param session id must not tick the 405 counter"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_get_accepts_x_mcp_session_id_alias() {
        // #4205 parity: the Python gateway accepts both `mcp-session-id` and
        // `x-mcp-session-id`. Rust must do the same so clients aren't
        // accepted by one runtime and 405'd by the other.
        let backend = Router::new().route(
            "/_internal/mcp/transport",
            axum::routing::get(|| async { Json(json!({"ok": true})) }),
        );
        let backend_url = spawn_router(backend).await;

        let mut config = test_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        config.live_stream_core_enabled = false;
        config.affinity_core_enabled = false;
        let state = AppState::new(&config).expect("state");

        upsert_runtime_session(
            &state,
            "alias-session".to_string(),
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

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("x-mcp-session-id"),
            HeaderValue::from_static("alias-session"),
        );

        let before = state.runtime_stats().snapshot().transport;
        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(
            response.status(),
            StatusCode::OK,
            "x-mcp-session-id alias should be accepted"
        );
        let after = state.runtime_stats().snapshot().transport;
        assert_eq!(
            after.get_rejected_no_session, before.get_rejected_no_session,
            "alias-header GET must not tick the 405 counter"
        );
    }

    #[tokio::test]
    async fn forward_transport_request_resumable_get_reports_unavailable_event_store_without_redis()
    {
        let state = AppState::new(&test_config()).expect("state");
        upsert_runtime_session(
            &state,
            "resume-session".to_string(),
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

        let mut headers = HeaderMap::new();
        headers.insert(
            HeaderName::from_static("accept"),
            HeaderValue::from_static("text/event-stream"),
        );
        headers.insert(
            HeaderName::from_static("last-event-id"),
            HeaderValue::from_static("event-1"),
        );
        headers.insert(
            HeaderName::from_static("mcp-session-id"),
            HeaderValue::from_static("resume-session"),
        );

        let response = forward_transport_request(
            &state,
            reqwest::Method::GET,
            headers,
            "/mcp".to_string(),
            "/mcp".parse::<Uri>().expect("uri"),
        )
        .await;
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(
            response_json(response).await["detail"],
            "Rust Redis event store is unavailable"
        );
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
