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
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use tracing::{info, warn};

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
async fn handle_invoke(
    State(state): State<AppState>,
    Json(request): Json<InvokeRequest>,
) -> Result<Json<InvokeResponse>, (StatusCode, Json<ErrorResponse>)> {
    let timeout = request
        .timeout_seconds
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_millis(state.config.request_timeout_ms));

    let result = invoke::execute_invoke(
        &state.client,
        &state.config,
        &request.endpoint_url,
        &request.headers,
        &request.json_body,
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
fn extract_headers(headers: &HeaderMap) -> HashMap<String, String> {
    headers
        .iter()
        .filter_map(|(name, value)| {
            value
                .to_str()
                .ok()
                .map(|v| (name.as_str().to_string(), v.to_string()))
        })
        .collect()
}

/// Resolve an agent by name, using the tiered cache when possible.
///
/// On cache miss the Python `/_internal/a2a/agents/{name}/resolve` endpoint
/// is called (L3).  Successful responses are written to both L1 and L2.
async fn resolve_agent(
    state: &AppState,
    agent_name: &str,
) -> Result<ResolvedAgent, (StatusCode, String)> {
    // Check tiered cache (L1 → L2).
    if let Some(agent) = state.agent_cache.get(agent_name).await {
        return Ok(agent);
    }

    // L1+L2 miss — call Python resolve endpoint (L3).
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = format!(
        "{}/_internal/a2a/agents/{}/resolve",
        state.config.backend_base_url.trim_end_matches('/'),
        agent_name,
    );
    let trust_headers = trust::build_trust_headers(auth_secret);
    let response = state
        .client
        .post(&url)
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
    if response.status().as_u16() != 200 {
        let status = response.status();
        let detail = response.text().await.unwrap_or_default();
        return Err((
            StatusCode::BAD_GATEWAY,
            format!("resolve failed: HTTP {status}: {detail}"),
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
/// wraps the result in a JSON-RPC response envelope.
async fn proxy_task_method(
    state: &AppState,
    action: &str,
    body: &Value,
    auth_context: &Value,
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

    // Extract params from the JSON-RPC body to send as the request body.
    let params = body
        .get("params")
        .cloned()
        .unwrap_or(Value::Object(Default::default()));

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
    let response_json: Option<Value> = response.json().await.ok();
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
/// wraps the result in a JSON-RPC response envelope.
async fn proxy_push_method(
    state: &AppState,
    action: &str,
    body: &Value,
    auth_context: &Value,
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
    let params = body
        .get("params")
        .cloned()
        .unwrap_or(Value::Object(Default::default()));

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
    let response_json: Option<Value> = response.json().await.ok();
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
async fn proxy_agent_card(
    state: &AppState,
    agent_name: &str,
    body: &Value,
    auth_context: &Value,
) -> Result<Json<InvokeResultDto>, (StatusCode, Json<ErrorResponse>)> {
    let auth_secret = state.config.auth_secret.as_deref().unwrap_or("");
    let url = format!(
        "{}/_internal/a2a/agents/{}/card",
        state.config.backend_base_url.trim_end_matches('/'),
        agent_name,
    );

    let mut headers = trust::build_trust_headers(auth_secret);
    headers.insert(
        "x-contextforge-auth-context".to_string(),
        trust::encode_auth_context(auth_context),
    );
    headers.insert("content-type".to_string(), "application/json".to_string());

    let response = state
        .client
        .post(&url)
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
    let response_json: Option<Value> = response.json().await.ok();
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
                    // Fingerprint mismatch — invalidate old session and create a new one.
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
    trust::authorize(
        &state.client,
        &state.config.backend_base_url,
        state.config.auth_secret.as_deref().unwrap_or(""),
        &auth_context,
        "invoke",
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

    // --- 2b. Method-based routing for task operations ---------------------
    // If the JSON-RPC method is a task read operation, proxy to the
    // Python task endpoints instead of invoking the agent directly.
    if let Some(method) = body.get("method").and_then(|m| m.as_str()) {
        match method {
            "GetTask" | "tasks/get" => {
                return proxy_task_method(&state, "get", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "ListTasks" | "tasks/list" => {
                return proxy_task_method(&state, "list", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "CancelTask" | "tasks/cancel" => {
                return proxy_task_method(&state, "cancel", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "GetExtendedAgentCard"
            | "agent/getExtendedCard"
            | "agent/getAuthenticatedExtendedCard" => {
                return proxy_agent_card(&state, &agent_name, &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "CreateTaskPushNotificationConfig" | "tasks/pushNotificationConfig/set" => {
                return proxy_push_method(&state, "create", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "GetTaskPushNotificationConfig" | "tasks/pushNotificationConfig/get" => {
                return proxy_push_method(&state, "get", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "ListTaskPushNotificationConfigs" | "tasks/pushNotificationConfig/list" => {
                return proxy_push_method(&state, "list", &body, &auth_context)
                    .await
                    .map(IntoResponse::into_response);
            }
            "DeleteTaskPushNotificationConfig" | "tasks/pushNotificationConfig/delete" => {
                return proxy_push_method(&state, "delete", &body, &auth_context)
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
                )
                .await;
            }
            _ => {} // Fall through to agent invoke
        }
    }

    // --- 3. Resolve agent (with cache) -----------------------------------
    let resolved = resolve_agent(&state, &agent_name)
        .await
        .map_err(|e| (e.0, Json(ErrorResponse { error: e.1 })))?;

    // --- 4. Build DTO and invoke -----------------------------------------
    let dto = InvokeRequestDto {
        id: 0,
        endpoint_url: resolved.endpoint_url.clone(),
        json_body: body,
        headers: HashMap::new(),
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
) -> Result<Response, (StatusCode, Json<ErrorResponse>)> {
    // --- Last-Event-ID reconnect -----------------------------------------
    if let Some(last_event_id) = request_headers.get("last-event-id") {
        if let Some(ref store) = state.event_store {
            // Parse "task_id:sequence" or just a numeric sequence with a
            // task_id from the body params.
            if let Some((task_id, after_seq)) = parse_last_event_id(last_event_id, body) {
                info!(
                    task_id = %task_id,
                    after_seq,
                    "replaying SSE events from store (Last-Event-ID reconnect)"
                );
                let sse = crate::stream::replay_from_store(Arc::clone(store), task_id, after_seq);
                return Ok(sse.into_response());
            }
        }
    }

    // --- Resolve agent ---------------------------------------------------
    let resolved = resolve_agent(state, agent_name)
        .await
        .map_err(|e| (e.0, Json(ErrorResponse { error: e.1 })))?;

    // --- Decrypt auth and build agent request ----------------------------
    let dto = InvokeRequestDto {
        id: 0,
        endpoint_url: resolved.endpoint_url.clone(),
        json_body: body.clone(),
        headers: HashMap::new(),
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
            task_id = %task_id,
            "forwarding agent SSE stream"
        );
        let sse =
            crate::stream::forward_agent_sse(agent_response, state.event_store.clone(), task_id);
        Ok(sse.into_response())
    } else {
        // Agent returned JSON (doesn't support streaming) — return as JSON.
        let status_code = agent_response.status().as_u16();
        let response_json: Option<Value> = agent_response.json().await.ok();
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
    match header.rfind(':') {
        Some(pos) => {
            let task_id_part = &header[..pos];
            let sequence_part = &header[pos + 1..];

            match (task_id_part.is_empty(), sequence_part.parse::<i64>()) {
                // Non-empty task_id with valid sequence
                (false, Ok(seq)) => return Some((task_id_part.to_string(), seq)),
                // Empty task_id or invalid sequence — fall through to next attempt
                _ => {}
            }
        }
        None => {}
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
        .body(body.to_vec())
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
