// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Axum HTTP server with A2A invoke, proxy, and metrics routes.

use crate::circuit::CircuitBreaker;
use crate::config::RuntimeConfig;
use crate::http::{InvokeRequestDto, InvokeResultDto, ResolvedAgent};
use crate::invoke;
use crate::metrics::MetricsCollector;
use crate::queue;
use crate::trust;
use crate::uaid;
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::error::Error;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};
use tracing::{info, warn};
use url::Url;

/// Rate-limit cadence for the "empty allowlist → cross-gateway permitted
/// to any host" warning.  Once-per-process goes silent after the first
/// call; warning on every request spams the hot path.  60 s is a
/// compromise: an operator watching `journalctl -f` sees the warning
/// within a minute of any cross-gateway activity, without filling the
/// log during traffic bursts.
const UAID_EMPTY_ALLOWLIST_WARN_INTERVAL_SECS: u64 = 60;

/// Process-start anchor for monotonic rate-limit timestamps.  Initialised
/// on the first cross-gateway call.  Using `Instant` instead of
/// `SystemTime` means a wall-clock skew (NTP step, leap-second bug,
/// pre-1970 `unwrap_or(0)` fallback) cannot cause the guard to either
/// spam or go silent.
static UAID_EMPTY_ALLOWLIST_WARN_ANCHOR: OnceLock<Instant> = OnceLock::new();

/// Seconds elapsed (from the anchor) at the last emitted warning.
/// `u64::MAX` is the "never logged" sentinel so the first call always
/// falls through to the warn arm.
static UAID_EMPTY_ALLOWLIST_WARN_LAST: AtomicU64 = AtomicU64::new(u64::MAX);

/// Logged exactly once per process on the first cross-gateway UAID
/// call — symmetric with the Python `_invoke_remote_agent` warning.
/// Cross-gateway requests do not forward caller credentials; the
/// remote agent must enforce its own authentication.
static UAID_AUTH_GAP_WARNING: OnceLock<()> = OnceLock::new();

/// HTTP header used by the federation hop counter.  Must match
/// `HOP_HEADER` in `mcpgateway/utils/uaid.py` exactly.
const HOP_HEADER: &str = "x-contextforge-uaid-hop";

/// Ceiling at which a parsed hop value saturates.  Matches the Python
/// `_HOP_MAX` (`2**31 - 1`) so both runtimes agree on the on-wire range.
const HOP_MAX: u32 = i32::MAX as u32;

/// Parse a single hop token — strict ASCII digits, saturating, with
/// a warn on malformed input.  Extracted so the coalesced-header
/// branch of `parse_hop_count` can apply the same strict rules to
/// each comma-separated element.
fn parse_single_hop_token(token: &str) -> u32 {
    if token.is_empty() || !token.bytes().all(|b| b.is_ascii_digit()) {
        if !token.is_empty() {
            warn!(
                header = HOP_HEADER,
                value = %token,
                "rejecting malformed hop token; treating as 0"
            );
        }
        return 0;
    }
    match token.parse::<u64>() {
        Ok(v) => u32::try_from(v.min(HOP_MAX as u64)).unwrap_or(HOP_MAX),
        Err(_) => HOP_MAX,
    }
}

/// Parse a `HOP_HEADER` value into a non-negative hop count using the
/// same strict rules as `mcpgateway.utils.uaid.parse_hop_count`:
///
/// - Missing or empty value → 0.
/// - Single value: pure ASCII digits (`[0-9]+`) — no leading sign,
///   no whitespace, no hex, no decimal point, no Unicode digits.
/// - Coalesced form (RFC 7230 §3.2.2): a proxy allowed to combine
///   duplicate `X-Hop: 0` + `X-Hop: 10` lines into `X-Hop: 0, 10`.
///   Split on `,`, trim OWS (space/tab) per RFC 7230 §3.2.6, parse
///   each token strictly, return the MAX across valid tokens.
/// - Malformed tokens inside a coalesced value are skipped (warn
///   still fires) rather than tainting the whole header — otherwise
///   an attacker could pair a valid high hop with garbage to drop
///   the effective value to 0.
/// - Values exceeding `HOP_MAX` saturate rather than wrap.
fn parse_hop_count(raw: Option<&String>) -> u32 {
    let Some(value) = raw else {
        return 0;
    };
    if !value.contains(',') {
        // Fast path: single value, strict — no OWS trim here; OWS
        // is only legal around comma separators in RFC 7230.
        return parse_single_hop_token(value);
    }
    let mut max_hop: u32 = 0;
    for token in value.split(',') {
        let stripped = token.trim_matches(|c: char| c == ' ' || c == '\t');
        let parsed = parse_single_hop_token(stripped);
        if parsed > max_hop {
            max_hop = parsed;
        }
    }
    max_hop
}

/// Return the next hop value to stamp on an outbound request,
/// saturating at `HOP_MAX` so degenerate input at the ceiling cannot
/// wrap through u32::MAX.  Mirrors the saturation in
/// `mcpgateway.utils.uaid.stamp_hop`.
fn next_hop(hop_count: u32) -> u32 {
    hop_count.saturating_add(1).min(HOP_MAX)
}

/// Read the hop counter from a JSON-deserialized `HashMap<String, String>`
/// (the `POST /invoke` body's `headers` field).
///
/// A naive case-insensitive lookup is vulnerable to header smuggling:
/// an attacker who sends both `{"X-Contextforge-UAID-Hop": "10",
/// "x-contextforge-uaid-hop": "0"}` exploits `HashMap`'s unpredictable
/// iteration order to pick whichever value happens to win.  Defend by
/// scanning **all** case-insensitive matches and taking the MAX — an
/// attacker can't lower the effective hop by adding a lower-cased
/// duplicate with value "0", and the highest value correctly trips
/// the guard.  A warn is emitted when more than one variant is seen
/// because that's an attack signal.
fn read_hop_from_dto_headers(headers: &HashMap<String, String>) -> u32 {
    let mut max_hop: u32 = 0;
    let mut variant_count: usize = 0;
    for (k, v) in headers.iter() {
        if k.eq_ignore_ascii_case(HOP_HEADER) {
            variant_count += 1;
            let parsed = parse_hop_count(Some(v));
            if parsed > max_hop {
                max_hop = parsed;
            }
        }
    }
    if variant_count > 1 {
        warn!(
            header = HOP_HEADER,
            variant_count,
            max_hop,
            "multiple case variants of hop header present; failing closed to max to block smuggling"
        );
    }
    max_hop
}

/// Read the hop counter from axum's `HeaderMap` — the entry path for
/// `/a2a/*` handlers.  `HeaderMap` is a multi-map (duplicate header
/// names keep all values), so a client sending two `X-Contextforge-UAID-Hop`
/// headers on the wire can push both through.  Same defense as
/// `read_hop_from_dto_headers`: take the max of every value returned
/// by `get_all`.  HeaderName is already case-normalized so case
/// variance isn't a concern here; duplication is.
fn read_hop_from_header_map(headers: &HeaderMap) -> u32 {
    let mut max_hop: u32 = 0;
    let mut variant_count: usize = 0;
    for value in headers.get_all(HOP_HEADER) {
        variant_count += 1;
        let Ok(text) = value.to_str() else {
            // Fail closed: a non-ASCII hop value is either malformed or
            // a smuggling attempt.  Skipping it silently would let an
            // attacker submit `X-Contextforge-UAID-Hop: ９` and have the
            // loop read hop=0.  Promote to HOP_MAX so the guard trips
            // regardless of the configured `uaid_max_federation_hops`.
            warn!(
                header = HOP_HEADER,
                "hop header value is not valid ASCII/Latin-1; failing closed to HOP_MAX (federation-loop protection)"
            );
            max_hop = HOP_MAX;
            continue;
        };
        let parsed = parse_hop_count(Some(&text.to_string()));
        if parsed > max_hop {
            max_hop = parsed;
        }
    }
    if variant_count > 1 {
        warn!(
            header = HOP_HEADER,
            variant_count,
            max_hop,
            "multiple hop header values present on inbound request; failing closed to max"
        );
    }
    max_hop
}

/// Emit the "empty allowlist" warning iff at least
/// `UAID_EMPTY_ALLOWLIST_WARN_INTERVAL_SECS` have passed since the last
/// one.  `compare_exchange` guarantees only one thread wins each
/// interval even under concurrent cross-gateway calls.
fn maybe_warn_empty_uaid_allowlist() {
    let anchor = *UAID_EMPTY_ALLOWLIST_WARN_ANCHOR.get_or_init(Instant::now);
    let now = anchor.elapsed().as_secs();
    let last = UAID_EMPTY_ALLOWLIST_WARN_LAST.load(Ordering::Relaxed);
    // `last == u64::MAX` is the first-call sentinel — fall through to warn.
    if last != u64::MAX && now.saturating_sub(last) < UAID_EMPTY_ALLOWLIST_WARN_INTERVAL_SECS {
        return;
    }
    if UAID_EMPTY_ALLOWLIST_WARN_LAST
        .compare_exchange(last, now, Ordering::Relaxed, Ordering::Relaxed)
        .is_err()
    {
        // Another thread won the race; its log covers this request.
        return;
    }
    warn!(
        "cross-gateway UAID invocation with empty A2A_RUST_UAID_ALLOWED_DOMAINS — \
         this runtime will route to any host. Set the allowlist in production \
         to restrict cross-gateway routing to trusted domains"
    );
}

const RUNTIME_NAME: &str = "contextforge-a2a-runtime";
const CONTENT_TYPE_SSE: &str = "text/event-stream";

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<RuntimeConfig>,
    pub client: Client,
    pub circuit: Arc<CircuitBreaker>,
    pub metrics: Arc<MetricsCollector>,
    pub worker_state: Arc<queue::WorkerState>,
    #[allow(dead_code)]
    pub(crate) redis_pool: Option<Arc<crate::cache::RedisPool>>,
    pub(crate) agent_cache: Arc<crate::cache::TieredCache<ResolvedAgent>>,
    pub(crate) session_manager: Option<Arc<crate::session::SessionManager>>,
    pub(crate) event_store: Option<Arc<crate::event_store::EventStore>>,
}

// ---------------------------------------------------------------------------
// DTOs (backward-compatible with existing Python client)
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: &'static str,
    runtime: &'static str,
    listen_http: String,
    listen_uds: Option<String>,
}

#[derive(Debug, Deserialize)]
struct InvokeRequest {
    endpoint_url: String,
    #[serde(default)]
    headers: HashMap<String, String>,
    json_body: Value,
    timeout_seconds: Option<u64>,
    /// AES-GCM ciphertext of the auth-header map (produced by
    /// ``services_auth.encode_auth`` on the Python side).  Decrypted by
    /// the sidecar and merged into ``headers`` before the upstream call.
    #[serde(default)]
    auth_headers_encrypted: Option<String>, // pragma: allowlist secret
    /// Map of query-param-name → AES-GCM ciphertext for per-param auth
    /// (e.g., ``?api_key=<token>``). // pragma: allowlist secret
    #[serde(default)]
    auth_query_params_encrypted: Option<HashMap<String, String>>, // pragma: allowlist secret
    /// Optional correlation ID threaded to the upstream agent via
    /// ``x-correlation-id``.  Ignored when already present in ``headers``.
    #[serde(default)]
    correlation_id: Option<String>,
    /// Optional W3C Trace Context header.
    #[serde(default)]
    traceparent: Option<String>,
}

#[derive(Debug, Serialize)]
struct InvokeResponse {
    status_code: u16,
    headers: HashMap<String, String>,
    json: Option<Value>,
    text: String,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: String,
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

pub fn router(state: AppState) -> Router {
    // The A2A sub-router uses a nested Router so that the specific
    // `/{agent_name}/invoke` route does not conflict with the `/{*rest}`
    // catch-all proxy.
    let a2a_routes = Router::new()
        .route("/{agent_name}/invoke", post(handle_a2a_invoke))
        .fallback(handle_a2a_proxy)
        .with_state(state.clone());

    Router::new()
        .route("/health", get(health))
        .route("/healthz", get(health))
        .route("/invoke", post(handle_invoke))
        .route("/metrics", get(handle_metrics))
        .nest("/a2a", a2a_routes)
        .with_state(state)
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        runtime: RUNTIME_NAME,
        listen_http: state.config.listen_http.clone(),
        listen_uds: state
            .config
            .listen_uds
            .as_ref()
            .map(|path| path.display().to_string()),
    })
}

/// `POST /invoke` — backward-compatible Python-initiated invoke path.
///
/// Accepts a single `InvokeRequest` and calls `invoke::execute_invoke()`
/// directly.  No trust validation: Python already authenticated the caller.
///
/// Routes the request through ``http::resolve_requests`` so encrypted auth
/// blobs are decrypted and merged into the upstream headers/URL — without
/// this step, agents using stored basic/bearer/api-key/query-param auth
/// would receive an unauthenticated request and return 401/403.
///
/// Enforces the same federation-hop guard as `handle_a2a_invoke`: if the
/// caller-supplied `headers` contain `X-Contextforge-UAID-Hop: N` at or
/// above `uaid_max_federation_hops`, reject with 404.  On pass-through,
/// stamp `N+1` on the outbound headers so the downstream agent (which
/// may itself be a CF gateway) can continue counting.  The route is
/// publicly mounted on the same listener as `/a2a/*` — if Nginx
/// misroutes or a plugin reaches it directly, we must not become a
/// loop vector.
async fn handle_invoke(
    State(state): State<AppState>,
    Json(request): Json<InvokeRequest>,
) -> Result<Json<InvokeResponse>, (StatusCode, Json<ErrorResponse>)> {
    let hop_count = read_hop_from_dto_headers(&request.headers);
    if hop_count >= state.config.uaid_max_federation_hops {
        warn!(
            hop_count,
            max = state.config.uaid_max_federation_hops,
            "POST /invoke hop limit reached; rejecting to break federation loop"
        );
        return Err((
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: "hop limit reached".to_string(),
            }),
        ));
    }

    let timeout = request
        .timeout_seconds
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_millis(state.config.request_timeout_ms));

    // Stamp outbound hop before building the DTO so `execute_invoke`
    // carries the incremented counter to whatever host `endpoint_url`
    // points at.  Remove any pre-existing hop key (regardless of case)
    // first — a lingering upstream-cased entry would ride alongside
    // our lowercase one and produce two hop headers on the wire.
    let mut outbound_headers = request.headers.clone();
    outbound_headers.retain(|k, _| !k.eq_ignore_ascii_case(HOP_HEADER));
    outbound_headers.insert(HOP_HEADER.to_string(), next_hop(hop_count).to_string());

    let dto = crate::http::InvokeRequestDto {
        id: 0,
        endpoint_url: request.endpoint_url.clone(),
        headers: outbound_headers,
        json_body: request.json_body.clone(),
        timeout_seconds: request.timeout_seconds,
        auth_headers_encrypted: request.auth_headers_encrypted.clone(),
        auth_query_params_encrypted: request.auth_query_params_encrypted.clone(),
        correlation_id: request.correlation_id.clone(),
        traceparent: request.traceparent.clone(),
        agent_name: None,
        agent_id: None,
        interaction_type: None,
        scope_id: None,
        request_id: None,
    };

    let mut resolved = crate::http::resolve_requests(
        std::slice::from_ref(&dto),
        state.config.auth_secret.as_deref(),
    )
    .map_err(|e| {
        (
            e.http_status(),
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        )
    })?;
    let resolved = resolved
        .pop()
        .expect("resolve_requests returned empty result");

    let result = invoke::execute_invoke(
        &state.client,
        &state.config,
        &resolved.endpoint_url,
        &resolved.headers,
        &resolved.json_body,
        timeout,
        None,
    )
    .await;

    match result {
        Ok(invoke_result) => Ok(Json(InvokeResponse {
            status_code: invoke_result.status_code,
            headers: invoke_result.headers,
            json: invoke_result.json,
            text: invoke_result.text,
        })),
        Err(err) => Err((
            err.http_status(),
            Json(ErrorResponse {
                error: err.to_string(),
            }),
        )),
    }
}

/// `GET /metrics` — returns the global metrics snapshot.
async fn handle_metrics(State(state): State<AppState>) -> Json<crate::metrics::AggregateMetrics> {
    Json(state.metrics.snapshot())
}

/// Convert Axum `HeaderMap` into a plain `HashMap<String, String>`.
///
/// Non-ASCII/non-Latin-1 values are dropped (axum's `HeaderValue::to_str`
/// rejects bytes >= 0x80 plus controls).  A benign client shouldn't send
/// non-UTF-8 headers, but a malformed or malicious one might — log the
/// drop so operators can see it happened rather than having the value
/// silently disappear.
///
/// Security exception: the federation hop header (`HOP_HEADER`) is not
/// droppable on malformed input.  Silently removing it would let an
/// attacker bypass the hop guard by sending a non-ASCII value (e.g.,
/// `X-Contextforge-UAID-Hop: ９`) — the handler would see no header
/// and read hop=0.  Substitute `HOP_MAX` instead so `parse_hop_count`
/// trips the guard no matter how `uaid_max_federation_hops` is set.
fn extract_headers(headers: &HeaderMap) -> HashMap<String, String> {
    headers
        .iter()
        .filter_map(|(name, value)| match value.to_str() {
            Ok(v) => Some((name.as_str().to_string(), v.to_string())),
            Err(_) => {
                if name.as_str().eq_ignore_ascii_case(HOP_HEADER) {
                    warn!(
                        header = name.as_str(),
                        "non-ASCII value on hop header — failing closed to HOP_MAX (federation-loop protection)"
                    );
                    Some((name.as_str().to_string(), HOP_MAX.to_string()))
                } else {
                    warn!(
                        header = name.as_str(),
                        "dropping header with non-ASCII value from extract_headers"
                    );
                    None
                }
            }
        })
        .collect()
}

/// Map a public A2A method to the internal authz action used by Python.
fn authz_action_for_method(method: Option<&str>) -> &'static str {
    match method {
        Some(
            "GetTask"
            | "tasks/get"
            | "GetExtendedAgentCard"
            | "agent/getExtendedCard"
            | "agent/getAuthenticatedExtendedCard"
            | "GetTaskPushNotificationConfig"
            | "tasks/pushNotificationConfig/get",
        ) => "get",
        Some(
            "ListTasks"
            | "tasks/list"
            | "ListTaskPushNotificationConfigs"
            | "tasks/pushNotificationConfig/list",
        ) => "list",
        _ => "invoke",
    }
}

/// Normalize public A2A task params into the internal Python request shape.
///
/// ``resolved_agent_id`` is the database ID of the agent derived from the
/// URL path (``/a2a/{agent_name}/...``).  Injecting it into the proxy body
/// ensures the Python task service filters by ``(a2a_agent_id, task_id)``
/// — the actual unique key — rather than by ``task_id`` alone, which can
/// collide across agents.
fn normalize_task_proxy_params(action: &str, body: &Value, resolved_agent_id: &str) -> Value {
    let mut params = body
        .get("params")
        .cloned()
        .unwrap_or(Value::Object(Default::default()));

    if let Value::Object(ref mut map) = params {
        match action {
            "get" | "cancel" if !map.contains_key("task_id") => {
                if let Some(task_id) = map.get("id").cloned() {
                    map.insert("task_id".to_string(), task_id);
                }
            }
            "list" if !map.contains_key("state") => {
                if let Some(state) = map.get("status").cloned() {
                    map.insert("state".to_string(), state);
                }
            }
            _ => {}
        }
        // Always override the caller's agent_id with the server-resolved
        // value.  Trusting a client-supplied agent_id here would undermine
        // the URL-based scoping of task lookups.
        map.insert(
            "agent_id".to_string(),
            Value::String(resolved_agent_id.to_string()),
        );
    }

    params
}

/// Safely append path segments to the configured backend base URL.
///
/// Necessary because `agent_name` can be a UAID whose `nativeId` is a
/// full URL (e.g. `http://agent.example.com/send`) — interpolating that
/// into a `format!()` path would smuggle `/` characters and fragment
/// the request into multiple segments, producing a 404 on the Python
/// backend. `Url::path_segments_mut().push()` percent-encodes `/`, `?`,
/// and `#` while leaving `:` and `;` untouched (both are legal in a
/// path segment per RFC 3986).
fn internal_backend_url(base: &str, segments: &[&str]) -> Result<Url, String> {
    let mut url = Url::parse(base.trim_end_matches('/'))
        .map_err(|e| format!("invalid backend_base_url {base:?}: {e}"))?;
    url.path_segments_mut()
        .map_err(|_| format!("backend_base_url {base:?} cannot have path segments appended"))?
        .pop_if_empty()
        .extend(segments);
    Ok(url)
}

/// Reuse a previously resolved agent if one was captured by the UAID
/// pre-resolve step in `handle_a2a_invoke`, otherwise call `resolve_agent`.
///
/// Threading the pre-resolved value through the downstream task/push/
/// invoke branches avoids calling the resolver twice for a UAID hit —
/// the second call can observe a concurrent cache eviction and return
/// 404 even though the first call succeeded.  `.take()` moves the value
/// out so the helper can only short-circuit once per request.
async fn take_or_resolve(
    preresolved: &mut Option<ResolvedAgent>,
    state: &AppState,
    agent_name: &str,
    auth_context: &Value,
) -> Result<ResolvedAgent, (StatusCode, String)> {
    if let Some(agent) = preresolved.take() {
        return Ok(agent);
    }
    resolve_agent(state, agent_name, auth_context).await
}

/// Convert a `resolve_agent` / `take_or_resolve` error tuple into the
/// `(StatusCode, Json<ErrorResponse>)` shape the axum handlers return,
/// translating `403 FORBIDDEN` into `404 NOT_FOUND` to hide the
/// existence of private agents from unauthorized callers.
///
/// The Python `/_internal/.../resolve` endpoint deliberately returns
/// 403 when an agent exists but the caller lacks visibility — that
/// signal lets the sidecar distinguish "doesn't exist" from "exists
/// but hidden", e.g. so a UAID local-miss doesn't then fall through
/// to cross-gateway dispatch.  But 403 must NOT leak to the end user:
/// an external caller probing for private agents by name or UAID
/// would otherwise see 403-vs-404 and enumerate the private fleet.
///
/// Every axum-edge call site that surfaces a resolve error must go
/// through this helper.
fn map_agent_resolve_err(
    agent_name: &str,
    err: (StatusCode, String),
) -> (StatusCode, Json<ErrorResponse>) {
    let (status, msg) = err;
    if status == StatusCode::FORBIDDEN {
        return (
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: format!("agent '{agent_name}' not found"),
            }),
        );
    }
    (status, Json(ErrorResponse { error: msg }))
}

/// Resolve an agent by name, using the tiered cache when possible.
///
/// On cache miss the Python `/_internal/a2a/agents/{name}/resolve` endpoint
/// is called (L3).  Successful responses are written to both L1 and L2.
async fn resolve_agent(
    state: &AppState,
    agent_name: &str,
    auth_context: &Value,
) -> Result<ResolvedAgent, (StatusCode, String)> {
    // Check tiered cache (L1 → L2).
    if let Some(agent) = state.agent_cache.get(agent_name).await {
        return Ok(agent);
    }

    // L1+L2 miss — call Python resolve endpoint (L3).
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = internal_backend_url(
        &state.config.backend_base_url,
        &["_internal", "a2a", "agents", agent_name, "resolve"],
    )
    .map_err(|e| (StatusCode::BAD_GATEWAY, e))?;
    let mut trust_headers = trust::build_trust_headers(auth_secret);
    trust_headers.insert(
        "x-contextforge-auth-context".to_string(),
        trust::encode_auth_context(auth_context),
    );
    let response = state
        .client
        .post(url)
        .headers(trust::reqwest_headers(&trust_headers))
        .send()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, format!("resolve failed: {e}")))?;

    if response.status().as_u16() == 404 {
        return Err((
            StatusCode::NOT_FOUND,
            format!("agent '{agent_name}' not found"),
        ));
    }
    if response.status().as_u16() == 403 {
        // Python surfaces 403 for visibility-denied (found-but-hidden),
        // distinct from 404 (does-not-exist). Propagate the distinction
        // so UAID dispatch can refuse to fall through to cross-gateway
        // for agents that exist locally but the caller cannot see.
        return Err((
            StatusCode::FORBIDDEN,
            format!("access denied to agent '{agent_name}'"),
        ));
    }
    if response.status().as_u16() != 200 {
        let status = response.status();
        let detail = response.text().await.unwrap_or_default();
        // Detail may contain a Python traceback, SQL error, or internal
        // hostname — log it server-side for diagnosis but surface only
        // the status to the (potentially untrusted) caller so we don't
        // reflect backend internals into the client response.
        warn!(
            agent = ?agent_name,
            http_status = %status,
            detail = ?detail,
            "Python resolve returned non-2xx"
        );
        return Err((
            StatusCode::BAD_GATEWAY,
            format!("resolve failed: HTTP {status}"),
        ));
    }

    let agent: ResolvedAgent = response.json().await.map_err(|e| {
        (
            StatusCode::BAD_GATEWAY,
            format!("invalid resolve response: {e}"),
        )
    })?;

    // Populate L1 + L2.
    state.agent_cache.set(agent_name, agent.clone()).await;

    Ok(agent)
}

/// Proxy a task read method (GetTask/ListTasks) to the Python backend.
///
/// Calls `/_internal/a2a/tasks/{action}` with the JSON-RPC params and
/// wraps the result in a JSON-RPC response envelope.  ``agent_id`` is the
/// server-resolved agent id derived from the URL path — it disambiguates
/// task lookups when two agents share the same ``task_id``.
async fn proxy_task_method(
    state: &AppState,
    action: &str,
    body: &Value,
    auth_context: &Value,
    agent_id: &str,
) -> Result<Json<InvokeResultDto>, (StatusCode, Json<ErrorResponse>)> {
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = format!(
        "{}/_internal/a2a/tasks/{}",
        state.config.backend_base_url.trim_end_matches('/'),
        action,
    );

    let mut headers = trust::build_trust_headers(auth_secret);
    headers.insert(
        "x-contextforge-auth-context".to_string(),
        trust::encode_auth_context(auth_context),
    );
    headers.insert("content-type".to_string(), "application/json".to_string());

    let params = normalize_task_proxy_params(action, body, agent_id);

    let response = state
        .client
        .post(&url)
        .headers(trust::reqwest_headers(&headers))
        .json(&params)
        .send()
        .await
        .map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("task {action} proxy failed: {e}"),
                }),
            )
        })?;

    let status_code = response.status().as_u16();
    let response_json: Option<Value> = match response.json().await {
        Ok(v) => Some(v),
        Err(e) => {
            // Non-JSON body on a proxied Python response — log the decode
            // error so a generic "operation failed" envelope does not hide
            // a malformed upstream reply (e.g., HTML error page on 5xx).
            warn!(error = %e, status = status_code, "failed to parse JSON body from internal A2A proxy response");
            None
        }
    };
    let request_id = body.get("id").cloned().unwrap_or(Value::Number(1.into()));

    // Wrap in JSON-RPC response envelope.
    let jsonrpc_result = if (200..300).contains(&status_code) {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": response_json,
        })
    } else {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -(status_code as i64),
                "message": response_json
                    .as_ref()
                    .and_then(|v| v.get("error"))
                    .and_then(|e| e.as_str())
                    .unwrap_or("task operation failed"),
            },
        })
    };

    Ok(Json(InvokeResultDto {
        id: 0,
        status_code,
        json: Some(jsonrpc_result),
        text: String::new(),
        headers: HashMap::new(),
        success: (200..300).contains(&status_code),
        error: None,
        code: None,
        duration_secs: 0.0,
        agent_name: None,
        session_id: None,
    }))
}

/// Proxy a push notification config method to the Python backend.
///
/// Calls `/_internal/a2a/push/{action}` with the JSON-RPC params and
/// wraps the result in a JSON-RPC response envelope.  ``agent_id`` is the
/// server-resolved agent id derived from the URL path — it scopes the
/// push-config operation to the agent the caller addressed and prevents
/// `list` from leaking configs across agents and `get` from hitting the
/// task-id ambiguity guard when two agents share a `task_id`.
async fn proxy_push_method(
    state: &AppState,
    action: &str,
    body: &Value,
    auth_context: &Value,
    agent_id: &str,
) -> Result<Json<InvokeResultDto>, (StatusCode, Json<ErrorResponse>)> {
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = format!(
        "{}/_internal/a2a/push/{}",
        state.config.backend_base_url.trim_end_matches('/'),
        action,
    );

    let mut headers = trust::build_trust_headers(auth_secret);
    headers.insert(
        "x-contextforge-auth-context".to_string(),
        trust::encode_auth_context(auth_context),
    );
    headers.insert("content-type".to_string(), "application/json".to_string());

    // Extract params from the JSON-RPC body to send as the request body.
    let mut params = body
        .get("params")
        .cloned()
        .unwrap_or(Value::Object(Default::default()));

    // Force the URL-path agent_id into the proxied params.  Trusting a
    // client-supplied agent_id would let a caller scoped to /a2a/foo
    // mutate or read configs for /a2a/bar — same threat model as the
    // task-method fix.
    if let Value::Object(ref mut map) = params {
        map.insert("agent_id".to_string(), Value::String(agent_id.to_string()));
    }

    let response = state
        .client
        .post(&url)
        .headers(trust::reqwest_headers(&headers))
        .json(&params)
        .send()
        .await
        .map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("push {action} proxy failed: {e}"),
                }),
            )
        })?;

    let status_code = response.status().as_u16();
    let response_json: Option<Value> = match response.json().await {
        Ok(v) => Some(v),
        Err(e) => {
            // Non-JSON body on a proxied Python response — log the decode
            // error so a generic "operation failed" envelope does not hide
            // a malformed upstream reply (e.g., HTML error page on 5xx).
            warn!(error = %e, status = status_code, "failed to parse JSON body from internal A2A proxy response");
            None
        }
    };
    let request_id = body.get("id").cloned().unwrap_or(Value::Number(1.into()));

    // Wrap in JSON-RPC response envelope.
    let jsonrpc_result = if (200..300).contains(&status_code) {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": response_json,
        })
    } else {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -(status_code as i64),
                "message": response_json
                    .as_ref()
                    .and_then(|v| v.get("error"))
                    .and_then(|e| e.as_str())
                    .unwrap_or("push notification config operation failed"),
            },
        })
    };

    Ok(Json(InvokeResultDto {
        id: 0,
        status_code,
        json: Some(jsonrpc_result),
        text: String::new(),
        headers: HashMap::new(),
        success: (200..300).contains(&status_code),
        error: None,
        code: None,
        duration_secs: 0.0,
        agent_name: None,
        session_id: None,
    }))
}

/// Proxy an agent card request to the Python backend.
///
/// Calls `/_internal/a2a/agents/{agent_name}/card` and wraps the result
/// in a JSON-RPC response envelope.  This serves GetExtendedAgentCard,
/// agent/getExtendedCard, and agent/getAuthenticatedExtendedCard methods.
///
/// `preresolved` is passed when the UAID pre-resolve step in
/// `handle_a2a_invoke` already located the agent — we then key the card
/// endpoint by the resolved canonical name instead of the UAID.  Python's
/// `/_internal/a2a/agents/{name}/card` matches by `name` only, so a UAID
/// would otherwise 404 here even though the agent exists locally.
async fn proxy_agent_card(
    state: &AppState,
    agent_name: &str,
    body: &Value,
    auth_context: &Value,
    preresolved: Option<&ResolvedAgent>,
) -> Result<Json<InvokeResultDto>, (StatusCode, Json<ErrorResponse>)> {
    let lookup_name = preresolved.map(|a| a.name.as_str()).unwrap_or(agent_name);
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = internal_backend_url(
        &state.config.backend_base_url,
        &["_internal", "a2a", "agents", lookup_name, "card"],
    )
    .map_err(|e| (StatusCode::BAD_GATEWAY, Json(ErrorResponse { error: e })))?;

    let mut headers = trust::build_trust_headers(auth_secret);
    headers.insert(
        "x-contextforge-auth-context".to_string(),
        trust::encode_auth_context(auth_context),
    );
    headers.insert("content-type".to_string(), "application/json".to_string());

    let response = state
        .client
        .post(url)
        .headers(trust::reqwest_headers(&headers))
        .send()
        .await
        .map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("agent card proxy failed: {e}"),
                }),
            )
        })?;

    let status_code = response.status().as_u16();
    let response_json: Option<Value> = match response.json().await {
        Ok(v) => Some(v),
        Err(e) => {
            // Non-JSON body on a proxied Python response — log the decode
            // error so a generic "operation failed" envelope does not hide
            // a malformed upstream reply (e.g., HTML error page on 5xx).
            warn!(error = %e, status = status_code, "failed to parse JSON body from internal A2A proxy response");
            None
        }
    };
    let request_id = body.get("id").cloned().unwrap_or(Value::Number(1.into()));

    // Wrap in JSON-RPC response envelope.
    let jsonrpc_result = if (200..300).contains(&status_code) {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": response_json,
        })
    } else {
        serde_json::json!({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -(status_code as i64),
                "message": response_json
                    .as_ref()
                    .and_then(|v| v.get("error"))
                    .and_then(|e| e.as_str())
                    .unwrap_or("agent card operation failed"),
            },
        })
    };

    Ok(Json(InvokeResultDto {
        id: 0,
        status_code,
        json: Some(jsonrpc_result),
        text: String::new(),
        headers: HashMap::new(),
        success: (200..300).contains(&status_code),
        error: None,
        code: None,
        duration_secs: 0.0,
        agent_name: None,
        session_id: None,
    }))
}

/// Perform full Python authenticate for an inbound request.
async fn full_authenticate(
    state: &AppState,
    request_headers: &HashMap<String, String>,
    agent_name: &str,
) -> Result<serde_json::Value, (StatusCode, Json<ErrorResponse>)> {
    let auth_request = trust::AuthenticateRequest {
        method: "POST".to_string(),
        path: format!("/a2a/{agent_name}/invoke"),
        query_string: String::new(),
        headers: request_headers.clone(),
        client_ip: None,
    };
    trust::authenticate(
        &state.client,
        &state.config.backend_base_url,
        state.config.auth_secret.as_deref().unwrap_or(""),
        &auth_request,
    )
    .await
    .map_err(|e| {
        (
            StatusCode::FORBIDDEN,
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        )
    })
}

/// Create a new session if the session manager is available.
async fn create_session(
    state: &AppState,
    auth_context: &serde_json::Value,
    request_headers: &HashMap<String, String>,
) -> Option<String> {
    if let Some(ref mgr) = state.session_manager {
        let fingerprint = mgr.compute_fingerprint(request_headers);
        mgr.create(auth_context, &fingerprint).await
    } else {
        None
    }
}

/// `POST /a2a/{agent_name}/invoke` — Nginx-facing invoke path.
///
/// Implements the full trust chain: authenticate the inbound request via
/// the Python gateway (or session cache), authorize the `invoke` action,
/// resolve the target agent (with caching), then build and submit the
/// invoke job to the queue worker.
///
/// Returns a polymorphic `Response` — either JSON for synchronous methods
/// or SSE for streaming methods (`SendStreamingMessage` / `message/stream`).
async fn handle_a2a_invoke(
    State(state): State<AppState>,
    Path(agent_name): Path<String>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // --- 1. Extract request headers --------------------------------------
    let request_headers = extract_headers(&headers);

    // --- 2. Authenticate (session fast-path or full Python call) ---------
    let session_id_header = request_headers
        .get("x-a2a-session-id")
        .or_else(|| request_headers.get("mcp-session-id"))
        .cloned();

    let (auth_context, session_id) =
        if let (Some(mgr), Some(sid)) = (&state.session_manager, &session_id_header) {
            // Try to reuse an existing session.
            if let Some(record) = mgr.lookup(sid).await {
                let fingerprint = mgr.compute_fingerprint(&request_headers);
                if mgr.validate_fingerprint(&record, &fingerprint) {
                    // Cache hit — extend TTL and reuse auth_context.
                    mgr.extend(sid).await;
                    (record.auth_context, Some(sid.clone()))
                } else {
                    // Fingerprint mismatch — security-relevant signal.  A
                    // valid session ID replayed from a client with a
                    // different fingerprint (e.g., different User-Agent or
                    // X-Forwarded-For) may indicate session-token theft.
                    // Log before invalidating so operators can correlate.
                    warn!(
                        session_id = %sid,
                        agent_name = ?agent_name,
                        "session fingerprint mismatch; invalidating and re-authenticating"
                    );
                    mgr.invalidate(sid).await;
                    let ctx = full_authenticate(&state, &request_headers, &agent_name).await?;
                    let new_sid = create_session(&state, &ctx, &request_headers).await;
                    (ctx, new_sid)
                }
            } else {
                // Session not found — full authenticate and create new session.
                let ctx = full_authenticate(&state, &request_headers, &agent_name).await?;
                let new_sid = create_session(&state, &ctx, &request_headers).await;
                (ctx, new_sid)
            }
        } else {
            // No session manager or no session ID header — full authenticate.
            let ctx = full_authenticate(&state, &request_headers, &agent_name).await?;
            let new_sid = create_session(&state, &ctx, &request_headers).await;
            (ctx, new_sid)
        };

    // --- 2. Authorize ----------------------------------------------------
    let method = body.get("method").and_then(|m| m.as_str());
    trust::authorize(
        &state.client,
        &state.config.backend_base_url,
        state.config.auth_secret.as_deref().unwrap_or(""),
        &auth_context,
        authz_action_for_method(method),
    )
    .await
    .map_err(|e| match e {
        trust::TrustError::AuthorizationDenied { .. } => (
            StatusCode::FORBIDDEN,
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        ),
        _ => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        ),
    })?;

    // --- 2a. Federation hop guard (applies to every invocation) ---------
    // Read the hop counter before any other dispatch — applies equally
    // to UAID and named-agent invocations because a self-referential
    // `endpoint_url` (agent whose URL points back at this gateway)
    // loops through `handle_a2a_invoke` on every hop regardless of
    // whether the original identifier was a UAID.  Outbound paths
    // (cross-gateway below AND the regular invoke DTO) stamp
    // `X-Contextforge-UAID-Hop: N+1` so the next hop can count.
    //
    // Read from the raw `HeaderMap` rather than the collapsed
    // `request_headers` HashMap: a client sending two hop headers on
    // the wire has both values in the HeaderMap, but `.collect()`ing
    // into HashMap keeps only the last-inserted value (arbitrary
    // order).  `read_hop_from_header_map` scans `get_all` and takes
    // the max so smuggling a low value alongside a high one doesn't
    // reset the counter.
    let hop_count = read_hop_from_header_map(&headers);
    if hop_count >= state.config.uaid_max_federation_hops {
        warn!(
            agent = ?agent_name,
            hop_count,
            max = state.config.uaid_max_federation_hops,
            "A2A invoke hop limit reached; rejecting to break loop"
        );
        return Err((
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: format!("agent '{agent_name}' not found"),
            }),
        ));
    }

    // --- 2b. UAID cross-gateway routing -----------------------------------
    // HCS-14 UAIDs embed the target agent's endpoint in the identifier
    // itself. If the path segment is a UAID, ask the resolver whether
    // the agent is registered locally first — the resolver must match
    // on any identifier kind (name/uuid/uaid) the caller supplies.
    //
    // Status semantics from the Python resolver:
    //   200 → local hit; fall through to normal method dispatch.
    //   403 → found, but the caller cannot see it. Refuse to fall
    //         through to cross-gateway (that would let a caller invoke
    //         a private local agent by its UAID) and return 404 to the
    //         end user so existence is not leaked.
    //   404 → truly not local; forward the JSON-RPC body to the agent
    //         URL encoded in the UAID (A2A 1.0-compliant cross-gateway).
    //   5xx → backend problem; surface as-is.
    //
    // The resolved agent is captured into `preresolved_agent` so the
    // method-dispatch branches below can reuse it rather than calling
    // `resolve_agent` a second time — a race between the two calls can
    // otherwise let a concurrent cache eviction turn a valid invoke
    // into a spurious 404.
    let mut preresolved_agent: Option<ResolvedAgent> = None;
    if uaid::is_uaid(&agent_name) {
        match resolve_agent(&state, &agent_name, &auth_context).await {
            Ok(agent) => {
                preresolved_agent = Some(agent);
            }
            Err((StatusCode::NOT_FOUND, _)) => {
                return handle_uaid_cross_gateway(
                    &state,
                    &agent_name,
                    &body,
                    &request_headers,
                    session_id.clone(),
                    hop_count,
                )
                .await;
            }
            Err((StatusCode::FORBIDDEN, _)) => {
                return Err((
                    StatusCode::NOT_FOUND,
                    Json(ErrorResponse {
                        error: format!("agent '{agent_name}' not found"),
                    }),
                ));
            }
            Err((status, msg)) => {
                return Err((status, Json(ErrorResponse { error: msg })));
            }
        }
    }

    // --- 2c. Method-based routing for task operations ---------------------
    // If the JSON-RPC method is a task read operation, proxy to the
    // Python task endpoints instead of invoking the agent directly.
    //
    // Task methods pre-resolve the agent (from the URL-path ``agent_name``)
    // so we can pass its ``agent_id`` to the Python task service — without
    // that, ``task_id`` alone is ambiguous across agents.
    if let Some(method) = method {
        let task_action = match method {
            "GetTask" | "tasks/get" => Some("get"),
            "ListTasks" | "tasks/list" => Some("list"),
            "CancelTask" | "tasks/cancel" => Some("cancel"),
            _ => None,
        };
        if let Some(action) = task_action {
            // Fail-closed for orphaned tasks: if the agent in the URL path
            // no longer exists (e.g., it was deleted while tasks remain —
            // the ``a2a_tasks`` FK does not currently cascade), resolve
            // returns 404 and the task op also returns 404 even though the
            // task row still exists.  This is intentional — surfacing
            // tasks via the URL of a non-existent agent would let a caller
            // probe for stale rows by name.
            let resolved =
                take_or_resolve(&mut preresolved_agent, &state, &agent_name, &auth_context)
                    .await
                    .map_err(|e| map_agent_resolve_err(&agent_name, e))?;
            return proxy_task_method(&state, action, &body, &auth_context, &resolved.agent_id)
                .await
                .map(IntoResponse::into_response);
        }
        let push_action = match method {
            "CreateTaskPushNotificationConfig" | "tasks/pushNotificationConfig/set" => {
                Some("create")
            }
            "GetTaskPushNotificationConfig" | "tasks/pushNotificationConfig/get" => Some("get"),
            "ListTaskPushNotificationConfigs" | "tasks/pushNotificationConfig/list" => Some("list"),
            "DeleteTaskPushNotificationConfig" | "tasks/pushNotificationConfig/delete" => {
                Some("delete")
            }
            _ => None,
        };
        if let Some(action) = push_action {
            let resolved =
                take_or_resolve(&mut preresolved_agent, &state, &agent_name, &auth_context)
                    .await
                    .map_err(|e| map_agent_resolve_err(&agent_name, e))?;
            return proxy_push_method(&state, action, &body, &auth_context, &resolved.agent_id)
                .await
                .map(IntoResponse::into_response);
        }
        match method {
            "GetExtendedAgentCard"
            | "agent/getExtendedCard"
            | "agent/getAuthenticatedExtendedCard" => {
                return proxy_agent_card(
                    &state,
                    &agent_name,
                    &body,
                    &auth_context,
                    preresolved_agent.as_ref(),
                )
                .await
                .map(IntoResponse::into_response);
            }
            "SendStreamingMessage" | "message/stream" => {
                return handle_streaming_method(
                    &state,
                    &agent_name,
                    &body,
                    &request_headers,
                    &auth_context,
                    preresolved_agent.take(),
                    hop_count,
                )
                .await;
            }
            _ => {} // Fall through to agent invoke
        }
    }

    // --- 3. Resolve agent (with cache) -----------------------------------
    let resolved = take_or_resolve(&mut preresolved_agent, &state, &agent_name, &auth_context)
        .await
        .map_err(|e| map_agent_resolve_err(&agent_name, e))?;

    // --- 4. Build DTO and invoke -----------------------------------------
    // Stamp the outbound hop counter UNCONDITIONALLY.  An earlier
    // revision gated on `uaid_allowed_domains` to avoid leaking the
    // header to third-party backends, but that reopens the self-loop
    // for any gateway reached through a host alias missing from the
    // allowlist (internal LB, split-horizon DNS, misconfigured partner
    // peer).  A ContextForge-internal header is safe to send to third
    // parties — they don't recognise it and ignore it; silently
    // skipping loop protection is not.  Mirrors Python's
    // `_execute_agent_request`.
    let mut outbound_headers = HashMap::new();
    outbound_headers.insert(
        "x-contextforge-uaid-hop".to_string(),
        next_hop(hop_count).to_string(),
    );
    let dto = InvokeRequestDto {
        id: 0,
        endpoint_url: resolved.endpoint_url.clone(),
        json_body: body,
        headers: outbound_headers,
        timeout_seconds: None,
        auth_headers_encrypted: resolved.auth_value_encrypted.clone(),
        auth_query_params_encrypted: resolved.auth_query_params_encrypted.clone(),
        correlation_id: None,
        traceparent: None,
        agent_name: Some(resolved.name.clone()),
        agent_id: Some(resolved.agent_id.clone()),
        interaction_type: Some("query".to_string()),
        scope_id: None,
        request_id: None,
    };

    let resolved_reqs = crate::http::resolve_requests(&[dto], state.config.auth_secret.as_deref())
        .map_err(|e| {
            (
                e.http_status(),
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
        })?;

    let timeout = Duration::from_millis(state.config.request_timeout_ms);
    let rx = queue::try_submit_batch(resolved_reqs, timeout).map_err(|e| {
        let status = match &e {
            queue::QueueError::Full => StatusCode::SERVICE_UNAVAILABLE,
            queue::QueueError::NotInitialized => StatusCode::INTERNAL_SERVER_ERROR,
            queue::QueueError::Shutdown => StatusCode::SERVICE_UNAVAILABLE,
        };
        (
            status,
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        )
    })?;

    let results = rx.await.map_err(|_| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: "queue worker dropped result".to_string(),
            }),
        )
    })?;

    let job_result = results.into_iter().next().ok_or_else(|| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: "no result from queue".to_string(),
            }),
        )
    })?;

    let result_dto = match job_result.result.as_ref() {
        Ok(inv) => {
            let success = (200..300).contains(&inv.status_code);
            InvokeResultDto {
                id: 0,
                status_code: inv.status_code,
                json: inv.json.clone(),
                text: inv.text.clone(),
                headers: inv.headers.clone(),
                success,
                error: None,
                code: None,
                duration_secs: job_result.duration.as_secs_f64(),
                agent_name: job_result.agent_name.clone(),
                session_id: session_id.clone(),
            }
        }
        Err(err_msg) => InvokeResultDto {
            id: 0,
            status_code: 502,
            json: None,
            text: String::new(),
            headers: HashMap::new(),
            success: false,
            error: Some(err_msg.clone()),
            code: Some("invoke_error".to_string()),
            duration_secs: job_result.duration.as_secs_f64(),
            agent_name: job_result.agent_name.clone(),
            session_id: session_id.clone(),
        },
    };

    Ok(Json(result_dto).into_response())
}

// ---------------------------------------------------------------------------
// UAID cross-gateway routing (A2A 1.0-compliant)
// ---------------------------------------------------------------------------

/// Forward an authenticated+authorized JSON-RPC 2.0 request to the agent
/// URL encoded in a UAID's `nativeId` parameter.
///
/// This is the A2A-1.0-compliant counterpart to the Python
/// `_invoke_remote_agent` path: instead of hopping through another
/// ContextForge gateway's invoke endpoint with a custom body shape, we
/// treat the `nativeId` as the target A2A agent URL and POST the
/// original JSON-RPC body there unchanged.
///
/// Security posture:
/// - SSRF: `uaid::resolve_routing` rejects user-info and path-injection
///   attempts, enforces http/https scheme, and applies the configured
///   domain allowlist.
/// - Auth: outbound requests are unauthenticated (matches the Python // pragma: allowlist secret
///   behaviour and the PR's documented tradeoff) — the remote agent is
///   expected to enforce its own authentication.  Inbound auth has
///   already been enforced by `full_authenticate` + `trust::authorize`
///   before we reach this function.
/// - Circuit breaker + metrics: reuse the runtime's shared
///   `CircuitBreaker` and `MetricsCollector` via `invoke::execute_invoke`
///   so cross-gateway failures trip the same breakers as direct invokes.
async fn handle_uaid_cross_gateway(
    state: &AppState,
    uaid_str: &str,
    body: &Value,
    request_headers: &HashMap<String, String>,
    session_id: Option<String>,
    hop_count: u32,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // One-time process-level warning about the auth-forwarding gap.
    // Cross-gateway calls do not forward caller credentials — the
    // remote agent is responsible for its own authentication.  Fires
    // once regardless of traffic volume (compare_exchange via OnceLock).
    // Symmetric with Python `_invoke_remote_agent`'s SECURITY warning
    // so operators see the same signal regardless of which runtime
    // handled the request.
    if UAID_AUTH_GAP_WARNING.set(()).is_ok() {
        warn!(
            "⚠️  SECURITY: first cross-gateway UAID invocation detected. \
             Outbound cross-gateway requests are UNAUTHENTICATED; the \
             remote agent must enforce its own authentication. Configure \
             A2A_RUST_UAID_ALLOWED_DOMAINS to restrict routing to trusted \
             hosts, and verify remote agents require credentials."
        );
    }

    let components = uaid::parse_uaid(uaid_str, state.config.uaid_max_length).map_err(|e| {
        // `parse_uaid` rejection is almost always caller input error —
        // log the variant code so `native_id_user_info` (an SSRF attack
        // signature) doesn't vanish into a plain 400 response with no
        // server-side trace.
        warn!(
            uaid = ?uaid_str,
            code = e.code(),
            error = %e,
            "UAID parse rejected"
        );
        (
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: format!("invalid UAID: {e}"),
            }),
        )
    })?;

    let allowlist = state.config.uaid_allowed_domains_list();
    if allowlist.is_empty() {
        maybe_warn_empty_uaid_allowlist();
    }

    let target = uaid::resolve_routing(&components, allowlist).map_err(|e| {
        // Log before mapping so operators can tell an SSRF attempt
        // (`native_id_user_info`, `native_id_bad_host`,
        // `unsupported_scheme`) from a benign mis-configured UAID.
        warn!(
            uaid = ?uaid_str,
            code = e.code(),
            error = %e,
            "UAID routing rejected"
        );
        // Status mapping:
        //   allowlist deny → 403 (policy)
        //   unsupported proto → 400 (caller input, not a server capability gap —
        //     the separate Proto::Mcp branch below is 501 because that protocol
        //     is recognised but this runtime won't speak it)
        //   everything else → 400 (malformed input)
        let status = match e {
            uaid::UaidError::DomainNotAllowed(_) => StatusCode::FORBIDDEN,
            _ => StatusCode::BAD_REQUEST,
        };
        (
            status,
            Json(ErrorResponse {
                error: e.to_string(),
            }),
        )
    })?;

    // This runtime only speaks A2A 1.0 outbound. MCP-UAIDs are
    // deliberately rejected here and must be handled by a different
    // sidecar or via the Python CF-federation path.  Log the rejection
    // — sibling parse/routing failures above emit `warn!`, and a
    // silent 501 here would hide "MCP UAID hit the A2A sidecar"
    // misrouting events from operators.
    if target.protocol() != uaid::Proto::A2a {
        let proto = target.protocol().as_str();
        warn!(
            uaid = ?uaid_str,
            proto,
            "UAID protocol not handled by A2A runtime"
        );
        return Err((
            StatusCode::NOT_IMPLEMENTED,
            Json(ErrorResponse {
                error: format!(
                    "UAID protocol '{proto}' is not supported by the A2A runtime; \
                     only 'a2a' is routed directly"
                ),
            }),
        ));
    }

    // Streaming methods must be proxied end-to-end as SSE rather than
    // buffered through `execute_invoke` — buffering defeats streaming
    // entirely and, for long-lived task streams, would hold the full
    // response in memory until the remote completes.
    let method = body.get("method").and_then(|v| v.as_str());
    if matches!(method, Some("SendStreamingMessage" | "message/stream")) {
        return handle_uaid_cross_gateway_streaming(
            state,
            uaid_str,
            body,
            request_headers,
            target.url(),
            session_id,
            hop_count,
        )
        .await;
    }

    let mut headers = HashMap::new();
    headers.insert("content-type".to_string(), "application/json".to_string());
    // Stamp outbound hop counter so the receiving gateway (Python or
    // Rust sidecar) can enforce `uaid_max_federation_hops`.  Matches
    // Python `_invoke_remote_agent`'s header exactly so a mixed-runtime
    // federation chain counts hops consistently.
    headers.insert(
        "x-contextforge-uaid-hop".to_string(),
        next_hop(hop_count).to_string(),
    );

    let timeout = Duration::from_millis(state.config.request_timeout_ms);
    let ctx = invoke::InvokeContext {
        circuit: &state.circuit,
        metrics: &state.metrics,
        scope_id: "uaid-cross-gateway",
        agent_key: uaid_str,
    };

    let started = Instant::now();
    let result = invoke::execute_invoke(
        &state.client,
        &state.config,
        target.url().as_str(),
        &headers,
        body,
        timeout,
        Some(&ctx),
    )
    .await;
    let duration = started.elapsed();

    let dto = match result {
        Ok(inv) => {
            let success = (200..300).contains(&inv.status_code);
            info!(
                status_code = inv.status_code,
                uaid = ?uaid_str,
                // `resolve_routing` guarantees a host; "<missing>" would
                // indicate an upstream invariant broke and is worth
                // seeing in the log rather than silently logging "".
                host = target.url().host_str().unwrap_or("<missing>"),
                "UAID cross-gateway invocation completed"
            );
            InvokeResultDto {
                id: 0,
                status_code: inv.status_code,
                json: inv.json,
                text: inv.text,
                headers: inv.headers,
                success,
                error: None,
                code: None,
                duration_secs: duration.as_secs_f64(),
                agent_name: None,
                session_id,
            }
        }
        Err(err) => {
            warn!(
                error = %err,
                uaid = ?uaid_str,
                "UAID cross-gateway invocation failed"
            );
            InvokeResultDto {
                id: 0,
                status_code: err.http_status().as_u16(),
                json: None,
                text: String::new(),
                headers: HashMap::new(),
                success: false,
                error: Some(err.to_string()),
                code: Some(err.error_code().to_string()),
                duration_secs: duration.as_secs_f64(),
                agent_name: None,
                session_id,
            }
        }
    };

    Ok(Json(dto).into_response())
}

/// SSE-capable counterpart to `handle_uaid_cross_gateway`'s buffered path.
///
/// A2A 1.0 `SendStreamingMessage` / `message/stream` invocations against a
/// remote UAID must proxy `text/event-stream` end-to-end; buffering
/// through `execute_invoke` would collapse the stream into a single JSON
/// blob and defeat the point of streaming.  Also handles Last-Event-ID
/// replay from the shared event store so a reconnected client resumes
/// where it disconnected — mirrors `handle_streaming_method`'s behavior
/// for local agents.
async fn handle_uaid_cross_gateway_streaming(
    state: &AppState,
    uaid_str: &str,
    body: &Value,
    request_headers: &HashMap<String, String>,
    target_url: &url::Url,
    session_id: Option<String>,
    hop_count: u32,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // Last-Event-ID replay: if the client is reconnecting and the
    // event store has events for the requested task, replay from there
    // instead of opening a new stream to the remote. If the store has
    // nothing buffered (fast disconnect before the first event was
    // flushed, store TTL elapsed), fall through to a fresh upstream
    // connect — returning an empty SSE stream would make EventSource
    // clients see EOF, retry, and loop forever.
    if let Some(last_event_id) = request_headers.get("last-event-id") {
        if let Some(ref store) = state.event_store {
            match parse_last_event_id(last_event_id, body) {
                Some((task_id, after_seq)) => {
                    let buffered = store.replay_after(&task_id, after_seq).await;
                    if !buffered.is_empty() {
                        info!(
                            uaid = ?uaid_str,
                            task_id = ?task_id,
                            after_seq,
                            event_count = buffered.len(),
                            "replaying SSE events for UAID cross-gateway reconnect"
                        );
                        let sse =
                            crate::stream::replay_from_store(Arc::clone(store), task_id, after_seq);
                        return Ok(sse.into_response());
                    }
                    info!(
                        uaid = ?uaid_str,
                        task_id = ?task_id,
                        after_seq,
                        "Last-Event-ID replay yielded no buffered events; opening fresh upstream stream"
                    );
                }
                None => {
                    warn!(
                        uaid = ?uaid_str,
                        last_event_id = ?last_event_id,
                        "unparseable Last-Event-ID on UAID cross-gateway stream; opening fresh stream"
                    );
                }
            }
        }
    }

    let timeout = Duration::from_millis(state.config.request_timeout_ms);
    let agent_response = state
        .client
        .post(target_url.as_str())
        .header("content-type", "application/json")
        // Stamp outbound hop counter (parity with non-streaming path)
        // so the remote can enforce `uaid_max_federation_hops`.
        .header("x-contextforge-uaid-hop", next_hop(hop_count).to_string())
        .json(body)
        .timeout(timeout)
        .send()
        .await
        .map_err(|e| {
            warn!(
                uaid = ?uaid_str,
                error = %e,
                "UAID cross-gateway streaming request failed"
            );
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("cross-gateway streaming request failed: {e}"),
                }),
            )
        })?;

    let content_type = agent_response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_lowercase();

    if content_type.contains(CONTENT_TYPE_SSE) {
        let task_id = extract_task_id(body);
        info!(
            uaid = ?uaid_str,
            task_id = ?task_id,
            host = target_url.host_str().unwrap_or("<missing>"),
            "forwarding UAID cross-gateway SSE stream"
        );
        let sse =
            crate::stream::forward_agent_sse(agent_response, state.event_store.clone(), task_id);
        Ok(sse.into_response())
    } else {
        // Remote doesn't support streaming — buffer the JSON response so
        // the client sees the remote's error or completion.  This path
        // bypasses `execute_invoke`, so the runtime's response-size cap
        // (`max_response_body_bytes`) must be enforced explicitly here:
        // a hostile remote could otherwise flood the sidecar with an
        // unbounded body and exhaust memory.
        let max_body = state.config.max_response_body_bytes;
        let status_code = agent_response.status().as_u16();

        // Fast reject on advertised Content-Length. Absent or lying
        // headers fall through to the streaming check below.
        if let Some(len) = agent_response.content_length() {
            if len > max_body {
                warn!(
                    uaid = ?uaid_str,
                    content_length = len,
                    limit = max_body,
                    "UAID cross-gateway non-SSE response advertised oversized body"
                );
                return Err((
                    StatusCode::BAD_GATEWAY,
                    Json(ErrorResponse {
                        error: format!(
                            "remote response exceeds max_response_body_bytes limit of {max_body}"
                        ),
                    }),
                ));
            }
        }

        // Read the body as a stream with a running-total check so a
        // chunked/transfer-encoded response with no Content-Length can't
        // buffer unbounded data before the cap is enforced.  Using
        // `.bytes().await` would eagerly drain the whole stream first.
        let body_bytes = read_bounded_body(agent_response, max_body).await.map_err(|reason| {
            match reason {
                BoundedBodyError::Oversized => {
                    warn!(
                        uaid = ?uaid_str,
                        limit = max_body,
                        "UAID cross-gateway non-SSE response body exceeded limit during streaming read"
                    );
                    (
                        StatusCode::BAD_GATEWAY,
                        Json(ErrorResponse {
                            error: format!(
                                "remote response exceeds max_response_body_bytes limit of {max_body}"
                            ),
                        }),
                    )
                }
                BoundedBodyError::Transport(e) => {
                    // Preserve the structured failure signals reqwest
                    // gives us — timeout vs connect vs body vs other.
                    // Without this log, a mid-stream timeout looks
                    // identical to a TLS failure in operator logs.
                    warn!(
                        uaid = ?uaid_str,
                        is_timeout = e.is_timeout(),
                        is_connect = e.is_connect(),
                        is_body = e.is_body(),
                        status = ?e.status(),
                        source = ?e.source(),
                        error = %e,
                        "UAID cross-gateway streaming transport error"
                    );
                    // Upgrade timeout to 504 so clients can distinguish
                    // "upstream slow" from "upstream broken".
                    let status = if e.is_timeout() {
                        StatusCode::GATEWAY_TIMEOUT
                    } else {
                        StatusCode::BAD_GATEWAY
                    };
                    (
                        status,
                        Json(ErrorResponse {
                            error: format!("failed to read remote response body: {e}"),
                        }),
                    )
                }
            }
        })?;

        // Preserve the remote's actual body — the previous `text:
        // String::new()` threw away the payload operators would use to
        // debug why the remote returned this shape.  Body is already
        // bounded by `max_body` so the copy is safe.  `from_utf8_lossy`
        // substitutes U+FFFD for invalid sequences; emit a warn so a
        // remote that sends binary/binary-mimed-as-text data is visible
        // in logs rather than silently corrupted in operator diagnostics.
        let text = match std::str::from_utf8(&body_bytes) {
            Ok(s) => s.to_string(),
            Err(e) => {
                warn!(
                    error = %e,
                    byte_len = body_bytes.len(),
                    "remote non-SSE body was not valid UTF-8; substituting replacement characters for diagnostics"
                );
                String::from_utf8_lossy(&body_bytes).into_owned()
            }
        };
        let response_json: Option<Value> = serde_json::from_slice(&body_bytes).ok();
        let success = (200..300).contains(&status_code);
        let result_dto = InvokeResultDto {
            id: 0,
            status_code,
            json: response_json,
            text,
            headers: HashMap::new(),
            success,
            // Tailor the error message to the status class: a 5xx is
            // an upstream failure, a 4xx is a client/content-type
            // negotiation failure.  A single hardcoded string would
            // mislabel legitimate 4xx/5xx responses from the remote.
            error: if success {
                None
            } else if (500..600).contains(&status_code) {
                Some(format!("remote agent returned HTTP {status_code}"))
            } else {
                Some(format!(
                    "remote agent returned HTTP {status_code} (non-streaming response)"
                ))
            },
            code: None,
            duration_secs: 0.0,
            agent_name: None,
            session_id,
        };
        Ok(Json(result_dto).into_response())
    }
}

/// Error variants for [`read_bounded_body`].
#[derive(Debug)]
enum BoundedBodyError {
    /// The running byte total crossed `max_body` — reject without
    /// draining the remainder of the stream.
    Oversized,
    /// Transport-level failure from `bytes_stream`.
    Transport(reqwest::Error),
}

/// Drain a `reqwest::Response` body into a `Vec<u8>`, checking the
/// accumulating size against `max_body` after each chunk so a
/// chunked/transfer-encoded response without a `Content-Length` header
/// cannot force the runtime to buffer unbounded data.  Returns `Oversized`
/// as soon as the cap is crossed; the remaining unread chunks are
/// abandoned when the stream is dropped, which in turn closes the
/// underlying hyper connection (preventing continued read of the body).
///
/// Caveat: hyper allocates each incoming frame before yielding it to
/// `bytes_stream()`, so this function cannot prevent a single oversized
/// frame from being allocated in memory ahead of our check — reqwest
/// does not expose a per-frame cap.  The per-chunk guard below drops
/// such a frame immediately on detection rather than merging it into
/// `buf`, so the *persistent* buffer is strictly bounded by `max_body`
/// and peak transient memory is bounded by `max_body + one_frame`.
async fn read_bounded_body(
    response: reqwest::Response,
    max_body: u64,
) -> Result<Vec<u8>, BoundedBodyError> {
    // Start empty — we deliberately don't pre-allocate based on a hint
    // because a hostile `Content-Length` or chunked stream could lie.
    // The Vec grows naturally and is strictly bounded by the cap below.
    let mut buf: Vec<u8> = Vec::new();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(BoundedBodyError::Transport)?;
        // Per-chunk fast-reject: a single frame already larger than the
        // cap short-circuits immediately.  Kept separate from the
        // cumulative check for clarity — if/when reqwest exposes a
        // per-frame limit, this is the place that check would migrate to.
        if chunk.len() as u64 > max_body {
            drop(chunk);
            return Err(BoundedBodyError::Oversized);
        }
        if (buf.len() as u64).saturating_add(chunk.len() as u64) > max_body {
            drop(chunk);
            return Err(BoundedBodyError::Oversized);
        }
        buf.extend_from_slice(&chunk);
    }
    Ok(buf)
}

// ---------------------------------------------------------------------------
// Streaming support
// ---------------------------------------------------------------------------

/// Handle `SendStreamingMessage` / `message/stream` methods.
///
/// Resolves the agent, decrypts auth, sends the request to the agent, and
/// returns either:
/// - An SSE stream if the agent responds with `Content-Type: text/event-stream`
/// - A JSON response if the agent responds with regular JSON (fallback)
///
/// Also supports Last-Event-ID reconnect: if the `last-event-id` header is
/// present and the event store has data, replays from the store instead of
/// making a new agent request.
async fn handle_streaming_method(
    state: &AppState,
    agent_name: &str,
    body: &Value,
    request_headers: &HashMap<String, String>,
    auth_context: &Value,
    mut preresolved_agent: Option<ResolvedAgent>,
    hop_count: u32,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // --- Last-Event-ID reconnect -----------------------------------------
    if let Some(last_event_id) = request_headers.get("last-event-id") {
        if let Some(ref store) = state.event_store {
            // Parse "task_id:sequence" or just a numeric sequence with a
            // task_id from the body params.
            match parse_last_event_id(last_event_id, body) {
                Some((task_id, after_seq)) => {
                    info!(
                        task_id = ?task_id,
                        after_seq,
                        "replaying SSE events from store (Last-Event-ID reconnect)"
                    );
                    let sse =
                        crate::stream::replay_from_store(Arc::clone(store), task_id, after_seq);
                    return Ok(sse.into_response());
                }
                None => {
                    // Header present but unparseable — the client expects
                    // replay and will otherwise miss events silently.
                    warn!(
                        last_event_id = ?last_event_id,
                        "unparseable Last-Event-ID header; falling through to live agent request (client may miss replayed events)"
                    );
                }
            }
        }
    }

    // --- Resolve agent ---------------------------------------------------
    // Reuse the agent record already resolved by the UAID pre-resolve
    // step when present; resolving again here would race a concurrent
    // cache eviction and spuriously return 404 on a valid streaming
    // invoke.  Delegates to `take_or_resolve` so the preresolved-agent
    // handling stays in one place (matches `handle_a2a_invoke`).
    let resolved = take_or_resolve(&mut preresolved_agent, state, agent_name, auth_context)
        .await
        .map_err(|e| map_agent_resolve_err(agent_name, e))?;

    // --- Decrypt auth and build agent request ----------------------------
    // Stamp the outbound hop counter UNCONDITIONALLY — parity with the
    // non-streaming path in `handle_a2a_invoke` (see that site for the
    // rationale).  Gating on the UAID allowlist would silently disable
    // loop protection for any gateway reached via a host alias that
    // isn't in the allowlist.
    let mut outbound_headers = HashMap::new();
    outbound_headers.insert(
        "x-contextforge-uaid-hop".to_string(),
        next_hop(hop_count).to_string(),
    );
    let dto = InvokeRequestDto {
        id: 0,
        endpoint_url: resolved.endpoint_url.clone(),
        json_body: body.clone(),
        headers: outbound_headers,
        timeout_seconds: None,
        auth_headers_encrypted: resolved.auth_value_encrypted.clone(),
        auth_query_params_encrypted: resolved.auth_query_params_encrypted.clone(),
        correlation_id: None,
        traceparent: None,
        agent_name: Some(resolved.name.clone()),
        agent_id: Some(resolved.agent_id.clone()),
        interaction_type: Some("stream".to_string()),
        scope_id: None,
        request_id: None,
    };

    let resolved_reqs = crate::http::resolve_requests(&[dto], state.config.auth_secret.as_deref())
        .map_err(|e| {
            (
                e.http_status(),
                Json(ErrorResponse {
                    error: e.to_string(),
                }),
            )
        })?;

    let resolved_req = resolved_reqs.into_iter().next().ok_or_else(|| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(ErrorResponse {
                error: "failed to resolve streaming request".to_string(),
            }),
        )
    })?;

    // Build reqwest headers from the resolved request.
    let mut agent_headers = reqwest::header::HeaderMap::new();
    for (k, v) in &resolved_req.headers {
        if let (Ok(name), Ok(val)) = (
            reqwest::header::HeaderName::from_bytes(k.as_bytes()),
            reqwest::header::HeaderValue::from_str(v),
        ) {
            agent_headers.insert(name, val);
        }
    }

    // Forward auth context to the agent.
    if let (Ok(name), Ok(val)) = (
        reqwest::header::HeaderName::from_bytes(b"x-contextforge-auth-context"),
        reqwest::header::HeaderValue::from_str(&trust::encode_auth_context(auth_context)),
    ) {
        agent_headers.insert(name, val);
    }

    let timeout = Duration::from_millis(state.config.request_timeout_ms);
    let agent_response = state
        .client
        .post(&resolved_req.endpoint_url)
        .headers(agent_headers)
        .json(&resolved_req.json_body)
        .timeout(timeout)
        .send()
        .await
        .map_err(|e| {
            warn!(error = %e, agent = agent_name, "streaming request to agent failed");
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("streaming request failed: {e}"),
                }),
            )
        })?;

    // --- Check response Content-Type -------------------------------------
    let content_type = agent_response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_lowercase();

    if content_type.contains(CONTENT_TYPE_SSE) {
        // Agent supports streaming — forward as SSE.
        let task_id = extract_task_id(body);
        info!(
            agent = agent_name,
            task_id = ?task_id,
            "forwarding agent SSE stream"
        );
        let sse =
            crate::stream::forward_agent_sse(agent_response, state.event_store.clone(), task_id);
        Ok(sse.into_response())
    } else {
        // Agent returned JSON (doesn't support streaming) — return as JSON.
        let status_code = agent_response.status().as_u16();
        let response_json: Option<Value> = match agent_response.json().await {
            Ok(v) => Some(v),
            Err(e) => {
                warn!(error = %e, status = status_code, "failed to parse JSON body from agent streaming fallback response");
                None
            }
        };
        let success = (200..300).contains(&status_code);
        let result_dto = InvokeResultDto {
            id: 0,
            status_code,
            json: response_json,
            text: String::new(),
            headers: HashMap::new(),
            success,
            error: if success {
                None
            } else {
                Some("agent does not support streaming".to_string())
            },
            code: None,
            duration_secs: 0.0,
            agent_name: Some(agent_name.to_string()),
            session_id: None,
        };
        Ok(Json(result_dto).into_response())
    }
}

/// Extract or generate a task ID from the JSON-RPC body.
///
/// Looks for `params.id` (A2A task ID) first, then falls back to a
/// generated UUID.
fn extract_task_id(body: &Value) -> String {
    body.get("params")
        .and_then(|p| p.get("id"))
        .and_then(|id| id.as_str())
        .map(String::from)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string())
}

/// Parse a `Last-Event-ID` header value into a `(task_id, sequence)` pair.
///
/// Supported formats:
/// - `{task_id}:{sequence}` — task ID and sequence directly in the header
/// - `{event_id}:{sequence}` — event ID with sequence (task_id from body)
/// - `{sequence}` — numeric sequence only (task_id extracted from body)
///
/// Returns `None` if the header cannot be parsed or if the task_id cannot be
/// extracted from the body when needed.
fn parse_last_event_id(header: &str, body: &Value) -> Option<(String, i64)> {
    // Try parsing as "{task_id}:{sequence}" format
    if let Some(pos) = header.rfind(':') {
        let task_id_part = &header[..pos];
        let sequence_part = &header[pos + 1..];

        // Non-empty task_id with valid sequence
        if let (false, Ok(seq)) = (task_id_part.is_empty(), sequence_part.parse::<i64>()) {
            return Some((task_id_part.to_string(), seq));
        }
    }

    // Try parsing entire header as a numeric sequence, extract task_id from body
    match header.parse::<i64>() {
        Ok(seq) => {
            let task_id = body
                .get("params")
                .and_then(|p| p.get("id"))
                .and_then(|id| id.as_str())
                .map(String::from)?;
            Some((task_id, seq))
        }
        Err(_) => None,
    }
}

// ---------------------------------------------------------------------------
// Proxy (catch-all)
// ---------------------------------------------------------------------------

/// Headers that should NOT be forwarded through the proxy.
const HOP_BY_HOP_HEADERS: &[&str] = &[
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
];

/// Fallback handler for `/a2a/...` — proxy catch-all that forwards to the
/// Python backend.  Because this is a `fallback` (not a parameterized route),
/// we extract the sub-path from the request URI.
async fn handle_a2a_proxy(
    State(state): State<AppState>,
    method: Method,
    uri: axum::http::Uri,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // The nested router strips the `/a2a` prefix, so `uri.path()` is the
    // remainder (e.g. `/some-agent/tasks`).  Strip the leading `/`.
    let rest = uri.path().trim_start_matches('/');
    proxy_to_backend(&state, method, rest, &headers, body).await
}

async fn proxy_to_backend(
    state: &AppState,
    method: Method,
    path: &str,
    headers: &HeaderMap,
    body: Bytes,
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    let url = format!(
        "{}/a2a/{}",
        state.config.backend_base_url.trim_end_matches('/'),
        path,
    );

    // Build filtered header map — skip hop-by-hop headers.
    let mut forwarded = reqwest::header::HeaderMap::new();
    for (name, value) in headers.iter() {
        let name_lower = name.as_str().to_lowercase();
        if HOP_BY_HOP_HEADERS.contains(&name_lower.as_str()) {
            continue;
        }
        if let Ok(rn) = reqwest::header::HeaderName::from_bytes(name.as_str().as_bytes()) {
            forwarded.insert(rn, value.clone());
        }
    }

    let reqwest_method = reqwest::Method::from_bytes(method.as_str().as_bytes()).map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: format!("unsupported HTTP method: {method}"),
            }),
        )
    })?;

    let response = state
        .client
        .request(reqwest_method, &url)
        .headers(forwarded)
        .body(body)
        .send()
        .await
        .map_err(|e| {
            warn!(error = %e, url = %url, "proxy request failed");
            (
                StatusCode::BAD_GATEWAY,
                Json(ErrorResponse {
                    error: format!("proxy request failed: {e}"),
                }),
            )
        })?;

    let status =
        StatusCode::from_u16(response.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);

    // Copy response headers, filtering hop-by-hop.
    let mut response_headers = axum::http::HeaderMap::new();
    for (name, value) in response.headers().iter() {
        let name_lower = name.as_str().to_lowercase();
        if HOP_BY_HOP_HEADERS.contains(&name_lower.as_str()) {
            continue;
        }
        response_headers.insert(name.clone(), value.clone());
    }

    let response_body = response.bytes().await.map_err(|e| {
        (
            StatusCode::BAD_GATEWAY,
            Json(ErrorResponse {
                error: format!("failed to read proxy response: {e}"),
            }),
        )
    })?;

    let mut builder = Response::builder().status(status);
    for (name, value) in &response_headers {
        builder = builder.header(name, value);
    }
    builder
        .body(axum::body::Body::from(response_body))
        .map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: format!("failed to build proxy response: {e}"),
                }),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cache::TieredCache;
    use axum::body::to_bytes;
    use axum::response::IntoResponse;
    use serde_json::json;
    use std::time::Duration;
    use wiremock::matchers::{body_json, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn test_state(backend_base_url: String) -> AppState {
        let config = Arc::new(RuntimeConfig {
            listen_http: "127.0.0.1:0".to_string(),
            listen_uds: None,
            request_timeout_ms: 1_000,
            client_connect_timeout_ms: 200,
            client_pool_idle_timeout_seconds: 1,
            client_pool_max_idle_per_host: 1,
            client_tcp_keepalive_seconds: 1,
            max_response_body_bytes: 1024 * 1024,
            max_retries: 0,
            retry_backoff_ms: 1,
            auth_secret: None,
            backend_base_url,
            max_concurrent: 2,
            max_queued: Some(4),
            circuit_failure_threshold: 2,
            circuit_cooldown_secs: 1,
            circuit_max_entries: 8,
            metrics_max_entries: 8,
            agent_cache_ttl_secs: 60,
            agent_cache_max_entries: 8,
            redis_url: None,
            l2_cache_ttl_secs: 60,
            cache_invalidation_channel: "invalidate".to_string(),
            session_enabled: false,
            session_ttl_secs: 60,
            session_fingerprint_headers: "authorization".to_string(),
            event_store_max_events: 8,
            event_store_ttl_secs: 60,
            event_flush_interval_ms: 100,
            event_flush_batch_size: 8,
            uaid_allowed_domains: String::new(),
            uaid_allowed_domains_cache: Default::default(),
            uaid_max_length: 2048,
            uaid_max_federation_hops: 3,
            log_filter: "warn".to_string(),
            exit_after_startup_ms: None,
        });
        let client = Client::new();
        let circuit = Arc::new(CircuitBreaker::new(2, Duration::from_secs(1), Some(8)));
        let metrics = Arc::new(MetricsCollector::new(Some(8)));
        let worker_state = Arc::new(queue::WorkerState {
            client: client.clone(),
            config: Arc::clone(&config),
            circuit: Arc::clone(&circuit),
            metrics: Arc::clone(&metrics),
        });

        AppState {
            config,
            client,
            circuit,
            metrics,
            worker_state,
            redis_pool: None,
            agent_cache: Arc::new(TieredCache::new(
                Duration::from_secs(60),
                Some(8),
                None,
                60,
                "agent",
            )),
            session_manager: None,
            event_store: None,
        }
    }

    /// Serve a hand-crafted HTTP response once and return the listen
    /// address.  Necessary because wiremock's `set_body_raw` stamps a
    /// `Content-Length` header, which would trip the fast-reject in
    /// `handle_uaid_cross_gateway_streaming` *before* `read_bounded_body`
    /// is exercised.  This helper sends a chunked-transfer response
    /// with no `Content-Length`, which is exactly the shape the
    /// cumulative-cap branch of `read_bounded_body` is meant to catch.
    async fn serve_raw_once(response_bytes: Vec<u8>) -> std::net::SocketAddr {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind");
        let addr = listener.local_addr().expect("local_addr");
        tokio::spawn(async move {
            if let Ok((mut stream, _)) = listener.accept().await {
                use tokio::io::{AsyncReadExt, AsyncWriteExt};
                // Drain the request so reqwest doesn't see a half-open
                // socket before the response arrives.
                let mut buf = [0u8; 4096];
                let _ = stream.read(&mut buf).await;
                let _ = stream.write_all(&response_bytes).await;
                let _ = stream.shutdown().await;
            }
        });
        addr
    }

    #[tokio::test]
    async fn read_bounded_body_caps_chunked_stream_without_content_length() {
        // One chunk larger than the cap, sent with Transfer-Encoding:
        // chunked and no Content-Length.  `reqwest::Response::content_length()`
        // returns None, so the fast-reject in
        // `handle_uaid_cross_gateway_streaming` is bypassed and we must
        // land in the streaming-read path.
        let payload = vec![b'x'; 8192];
        let mut response_bytes = Vec::new();
        response_bytes.extend_from_slice(
            b"HTTP/1.1 200 OK\r\n\
              Content-Type: application/json\r\n\
              Transfer-Encoding: chunked\r\n\
              \r\n",
        );
        response_bytes.extend_from_slice(format!("{:x}\r\n", payload.len()).as_bytes());
        response_bytes.extend_from_slice(&payload);
        response_bytes.extend_from_slice(b"\r\n0\r\n\r\n");

        let addr = serve_raw_once(response_bytes).await;
        let response = reqwest::Client::new()
            .get(format!("http://{addr}/"))
            .send()
            .await
            .expect("send");
        assert!(
            response.content_length().is_none(),
            "test precondition: chunked response must not expose Content-Length"
        );

        let err = read_bounded_body(response, 1024)
            .await
            .expect_err("oversized body must be rejected");
        assert!(matches!(err, BoundedBodyError::Oversized));
    }

    #[tokio::test]
    async fn read_bounded_body_accepts_body_within_limit() {
        // Positive control: a chunked response under the cap should
        // round-trip the bytes without error.
        let payload: &[u8] = b"{\"ok\":true}";
        let mut response_bytes = Vec::new();
        response_bytes.extend_from_slice(
            b"HTTP/1.1 200 OK\r\n\
              Content-Type: application/json\r\n\
              Transfer-Encoding: chunked\r\n\
              \r\n",
        );
        response_bytes.extend_from_slice(format!("{:x}\r\n", payload.len()).as_bytes());
        response_bytes.extend_from_slice(payload);
        response_bytes.extend_from_slice(b"\r\n0\r\n\r\n");

        let addr = serve_raw_once(response_bytes).await;
        let response = reqwest::Client::new()
            .get(format!("http://{addr}/"))
            .send()
            .await
            .expect("send");
        let body = read_bounded_body(response, 1024).await.expect("under cap");
        assert_eq!(body.as_slice(), payload);
    }

    #[test]
    fn internal_backend_url_percent_encodes_slashes_in_segments() {
        // Regression guard against re-introducing `format!()` for path
        // interpolation.  A UAID whose nativeId is a full URL contains
        // `/` and `?` characters; when embedded as a single segment the
        // output must percent-encode them so the receiving Python
        // router sees one `{agent_name}` segment, not several.
        let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=https://agent.example.com/a2a/send?k=v";
        let url = internal_backend_url(
            "http://127.0.0.1:4444",
            &["_internal", "a2a", "agents", uaid, "resolve"],
        )
        .expect("valid URL");
        let path = url.path();
        // The encoded UAID is one path segment: exactly two `/` between
        // `agents` and the segment, one `/` to `resolve`, no extras.
        assert_eq!(
            path.matches('/').count(),
            5,
            "expected 5 slashes (4 delimiters + leading), got path: {path}"
        );
        assert!(
            path.contains("%2F"),
            "expected `/` inside the UAID segment to be percent-encoded, got: {path}"
        );
        assert!(
            path.contains("%3F"),
            "expected `?` inside the UAID segment to be percent-encoded, got: {path}"
        );
        // `Url::path_segments` yields the raw (still-encoded) segments
        // without decoding; the count is what matters here — exactly 5
        // segments proves `/` inside the UAID did not fragment the path.
        let segments: Vec<_> = url.path_segments().expect("hierarchical URL").collect();
        assert_eq!(
            segments.len(),
            5,
            "UAID segment must not fragment into multiple segments: {segments:?}"
        );
        assert_eq!(segments[0], "_internal");
        assert_eq!(segments[1], "a2a");
        assert_eq!(segments[2], "agents");
        assert_eq!(segments[4], "resolve");
    }

    #[test]
    fn authz_action_for_method_maps_read_list_and_invoke_methods() {
        assert_eq!(authz_action_for_method(Some("GetTask")), "get");
        assert_eq!(authz_action_for_method(Some("tasks/get")), "get");
        assert_eq!(authz_action_for_method(Some("GetExtendedAgentCard")), "get");
        assert_eq!(
            authz_action_for_method(Some("tasks/pushNotificationConfig/get")),
            "get"
        );
        assert_eq!(authz_action_for_method(Some("ListTasks")), "list");
        assert_eq!(
            authz_action_for_method(Some("tasks/pushNotificationConfig/list")),
            "list"
        );
        assert_eq!(authz_action_for_method(Some("SendMessage")), "invoke");
        assert_eq!(
            authz_action_for_method(Some("tasks/pushNotificationConfig/delete")),
            "invoke"
        );
        assert_eq!(authz_action_for_method(None), "invoke");
    }

    #[test]
    fn normalize_task_proxy_params_copies_id_and_status_fields() {
        let get_body = json!({"params": {"id": "task-1"}});
        assert_eq!(
            normalize_task_proxy_params("get", &get_body, "agent-xyz"),
            json!({"id": "task-1", "task_id": "task-1", "agent_id": "agent-xyz"})
        );

        let cancel_body = json!({"params": {"id": "task-2"}});
        assert_eq!(
            normalize_task_proxy_params("cancel", &cancel_body, "agent-xyz"),
            json!({"id": "task-2", "task_id": "task-2", "agent_id": "agent-xyz"})
        );

        let list_body = json!({"params": {"status": "working"}});
        assert_eq!(
            normalize_task_proxy_params("list", &list_body, "agent-xyz"),
            json!({"status": "working", "state": "working", "agent_id": "agent-xyz"})
        );
    }

    #[test]
    fn normalize_task_proxy_params_preserves_existing_internal_fields() {
        let body =
            json!({"params": {"id": "public-id", "task_id": "internal-id", "state": "done"}});
        assert_eq!(
            normalize_task_proxy_params("get", &body, "agent-xyz"),
            json!({"id": "public-id", "task_id": "internal-id", "state": "done", "agent_id": "agent-xyz"})
        );
        assert_eq!(
            normalize_task_proxy_params("list", &body, "agent-xyz"),
            json!({"id": "public-id", "task_id": "internal-id", "state": "done", "agent_id": "agent-xyz"})
        );
    }

    #[test]
    fn normalize_task_proxy_params_overrides_client_supplied_agent_id() {
        // A client-supplied ``agent_id`` in params must be replaced with
        // the server-resolved value — trusting the client would undermine
        // URL-based task scoping.
        let body = json!({"params": {"id": "task-1", "agent_id": "attacker-spoofed"}});
        let normalized = normalize_task_proxy_params("get", &body, "server-resolved-id");
        assert_eq!(normalized["agent_id"], json!("server-resolved-id"));
    }

    #[tokio::test]
    async fn proxy_push_method_overrides_client_supplied_agent_id() {
        // Symmetric to normalize_task_proxy_params_overrides_client_supplied_agent_id —
        // verify the push-method proxy refuses a client-supplied agent_id and
        // replaces it with the URL-path-resolved value.
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/get"))
            .and(body_json(
                json!({"task_id": "task-1", "agent_id": "server-resolved"}),
            ))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"config_id": "c1"})))
            .expect(1)
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let result = proxy_push_method(
            &state,
            "get",
            &json!({"id": 1, "params": {"task_id": "task-1", "agent_id": "attacker-spoofed"}}),
            &json!({"sub": "user"}),
            "server-resolved",
        )
        .await
        .unwrap();
        assert_eq!(result.0.status_code, 200);
        server.verify().await;
    }

    #[test]
    fn extract_task_id_uses_params_id_or_generates_uuid() {
        assert_eq!(
            extract_task_id(&json!({"params": {"id": "task-123"}})),
            "task-123".to_string()
        );

        let generated = extract_task_id(&json!({"params": {}}));
        assert!(uuid::Uuid::parse_str(&generated).is_ok());
    }

    #[test]
    fn parse_last_event_id_handles_supported_formats() {
        let body = json!({"params": {"id": "task-from-body"}});

        assert_eq!(
            parse_last_event_id("task-1:9", &body),
            Some(("task-1".to_string(), 9))
        );
        assert_eq!(
            parse_last_event_id("event-123:4", &body),
            Some(("event-123".to_string(), 4))
        );
        assert_eq!(
            parse_last_event_id("8", &body),
            Some(("task-from-body".to_string(), 8))
        );
    }

    #[test]
    fn parse_last_event_id_rejects_invalid_values() {
        let body = json!({"params": {"id": "task-from-body"}});
        assert_eq!(parse_last_event_id(":9", &body), None);
        assert_eq!(parse_last_event_id("task-1:not-a-seq", &body), None);
        assert_eq!(parse_last_event_id("not-a-number", &body), None);
        assert_eq!(parse_last_event_id("7", &json!({"params": {}})), None);
    }

    #[tokio::test]
    async fn resolve_agent_returns_bad_gateway_for_non_200_and_invalid_json() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/agents/demo/resolve"))
            .respond_with(ResponseTemplate::new(500).set_body_string("boom"))
            .up_to_n_times(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/agents/demo/resolve"))
            .respond_with(ResponseTemplate::new(200).set_body_string("not-json"))
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let err = resolve_agent(&state, "demo", &json!({"sub": "user"}))
            .await
            .unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);
        assert!(err.1.contains("resolve failed"));

        let err = resolve_agent(&state, "demo", &json!({"sub": "user"}))
            .await
            .unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);
        assert!(err.1.contains("invalid resolve response"));
    }

    #[tokio::test]
    async fn proxy_task_and_push_methods_wrap_error_responses() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/tasks/get"))
            .and(body_json(
                json!({"task_id": "task-1", "id": "task-1", "agent_id": "agent-test"}),
            ))
            .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "missing"})))
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/push/get"))
            .and(body_json(json!({"id": "cfg-1", "agent_id": "agent-test"})))
            .respond_with(ResponseTemplate::new(400).set_body_json(json!({"error": "bad push"})))
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let task = proxy_task_method(
            &state,
            "get",
            &json!({"id": 9, "params": {"id": "task-1"}}),
            &json!({"sub": "user"}),
            "agent-test",
        )
        .await
        .unwrap();
        let task_json = task.0.json.unwrap();
        assert_eq!(task.0.status_code, 404);
        assert_eq!(task_json["error"]["message"], "missing");

        let push = proxy_push_method(
            &state,
            "get",
            &json!({"id": 8, "params": {"id": "cfg-1"}}),
            &json!({"sub": "user"}),
            "agent-test",
        )
        .await
        .unwrap();
        let push_json = push.0.json.unwrap();
        assert_eq!(push.0.status_code, 400);
        assert_eq!(push_json["error"]["message"], "bad push");
    }

    #[tokio::test]
    async fn proxy_methods_surface_transport_errors() {
        let state = test_state("http://127.0.0.1:1".to_string());

        let err = proxy_task_method(
            &state,
            "get",
            &json!({"id": 1, "params": {"id": "task-1"}}),
            &json!({"sub": "user"}),
            "agent-test",
        )
        .await
        .unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);

        let err = proxy_push_method(
            &state,
            "get",
            &json!({"id": 1, "params": {"id": "cfg-1"}}),
            &json!({"sub": "user"}),
            "agent-test",
        )
        .await
        .unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);

        let err = proxy_agent_card(
            &state,
            "agent",
            &json!({"id": 1}),
            &json!({"sub": "user"}),
            None,
        )
        .await
        .unwrap_err();
        assert_eq!(err.0, StatusCode::BAD_GATEWAY);
    }

    #[tokio::test]
    async fn proxy_agent_card_wraps_error_response() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/_internal/a2a/agents/agent/card"))
            .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "no card"})))
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let card = proxy_agent_card(
            &state,
            "agent",
            &json!({"id": 7}),
            &json!({"sub": "user"}),
            None,
        )
        .await
        .unwrap();
        let card_json = card.0.json.unwrap();
        assert_eq!(card.0.status_code, 404);
        assert_eq!(card_json["error"]["message"], "no card");
    }

    #[tokio::test]
    async fn proxy_to_backend_filters_headers_and_returns_body() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/a2a/agent/tasks"))
            .respond_with(
                ResponseTemplate::new(200)
                    .append_header("x-backend", "ok")
                    .set_body_string("backend-body"),
            )
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let mut headers = HeaderMap::new();
        headers.insert("x-forwarded-test", "yes".parse().unwrap());
        headers.insert("connection", "close".parse().unwrap());

        let response = proxy_to_backend(
            &state,
            Method::POST,
            "agent/tasks",
            &headers,
            Bytes::from_static(br#"{"ok":true}"#),
        )
        .await
        .unwrap()
        .into_response();

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers().get("x-backend").unwrap(), "ok");
        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        assert_eq!(&body[..], b"backend-body");
    }

    #[tokio::test]
    async fn proxy_to_backend_strips_smuggling_headers_on_request_and_response() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/a2a/agent/tasks"))
            .respond_with(
                ResponseTemplate::new(200)
                    .append_header("connection", "close")
                    .append_header("proxy-authorization", "Basic leaked")
                    .append_header("transfer-encoding", "chunked")
                    .append_header("upgrade", "websocket")
                    .append_header("x-safe", "ok")
                    .set_body_string("backend-body"),
            )
            .mount(&server)
            .await;

        let state = test_state(server.uri());
        let mut headers = HeaderMap::new();
        headers.insert("host", "evil.example".parse().unwrap());
        headers.insert("proxy-authorization", "Basic attacker".parse().unwrap());
        headers.insert("content-length", "123".parse().unwrap());
        headers.insert("transfer-encoding", "chunked".parse().unwrap());
        headers.insert("upgrade", "websocket".parse().unwrap());
        headers.insert("x-safe", "yes".parse().unwrap());

        let response = proxy_to_backend(
            &state,
            Method::POST,
            "agent/tasks",
            &headers,
            Bytes::from_static(br#"{"ok":true}"#),
        )
        .await
        .unwrap()
        .into_response();

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response.headers().get("x-safe").unwrap(), "ok");
        assert!(response.headers().get("connection").is_none());
        assert!(response.headers().get("proxy-authorization").is_none());
        assert!(response.headers().get("transfer-encoding").is_none());
        assert!(response.headers().get("upgrade").is_none());
    }

    #[tokio::test]
    async fn handle_streaming_method_replays_from_store_when_last_event_id_is_present() {
        let mut state = test_state("http://127.0.0.1:1".to_string());
        state.event_store = Some(Arc::new(crate::event_store::EventStore::seeded_for_test(
            vec![
                crate::event_store::StoredEvent {
                    event_id: "evt-1".to_string(),
                    sequence: 1,
                    event_type: "unknown".to_string(),
                    payload: r#"{"status":"queued"}"#.to_string(),
                },
                crate::event_store::StoredEvent {
                    event_id: "evt-2".to_string(),
                    sequence: 2,
                    event_type: "status".to_string(),
                    payload: r#"{"status":"working"}"#.to_string(),
                },
            ],
            false,
        )));

        let response = handle_streaming_method(
            &state,
            "test-agent",
            &json!({"params": {"id": "task-123"}}),
            &HashMap::from([("last-event-id".to_string(), "task-123:0".to_string())]),
            &json!({"sub": "user"}),
            None,
            0,
        )
        .await
        .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok()),
            Some("text/event-stream")
        );

        let body = to_bytes(response.into_body(), usize::MAX).await.unwrap();
        let text = String::from_utf8_lossy(&body);
        assert!(
            text.contains("id: evt-1:1"),
            "expected first replayed id, body: {text}"
        );
        assert!(
            text.contains("data: {\"status\":\"queued\"}"),
            "expected first payload, body: {text}"
        );
        assert!(
            text.contains("id: evt-2:2"),
            "expected second replayed id, body: {text}"
        );
    }
}
