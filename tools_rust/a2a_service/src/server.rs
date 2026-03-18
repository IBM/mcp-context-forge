// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! Axum router and handlers for the A2A invoke service (used by binary and integration tests).

use std::sync::Arc;

use axum::{
    extract::State,
    http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use futures::future::join_all;

use crate::{
    submit_batch, BatchSubmitError, InvokeRequestDto, QueueError,
};

/// Shared state for the A2A HTTP server.
#[derive(Clone)]
pub struct AppState {
    /// Optional auth secret for decrypting encrypted auth blobs in invoke requests.
    pub auth_secret: Option<String>,
    /// Per-request timeout in seconds for low-level invoke.
    pub timeout_secs: f64,
    /// Base URL of the Python gateway (for proxy and a2a invoke).
    pub backend_base_url: String,
    /// HTTP client for proxying to the backend.
    pub client: reqwest::Client,
}

/// Build the Axum router with all A2A routes. Caller must have called `init_invoker` and `init_queue` before using `/invoke`.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/health", get(health))
        .route("/invoke", post(invoke_low_level))
        .route("/a2a/{agent_name}/invoke", post(a2a_invoke))
        .nest("/a2a", Router::new().fallback(a2a_proxy))
        .with_state(state)
}

async fn health() -> &'static str {
    "ok"
}

/// POST /invoke: low-level endpoint for internal use.
/// Body is either a single `InvokeRequestDto` or an array of them (batch).
/// Optional header X-Auth-Secret overrides config auth secret for decryption.
async fn invoke_low_level(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<axum::body::Body>,
) -> impl IntoResponse {
    let auth_secret = request
        .headers()
        .get("X-Auth-Secret")
        .and_then(|v| v.to_str().ok().map(String::from))
        .or_else(|| state.auth_secret.clone());

    let body = match axum::body::to_bytes(request.into_body(), 100 * 1024 * 1024).await {
        Ok(b) => b,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": format!("body read: {}", e) })),
            )
                .into_response();
        }
    };

    let requests: Vec<InvokeRequestDto> = match serde_json::from_slice::<serde_json::Value>(&body) {
        Ok(serde_json::Value::Array(arr)) => {
            match serde_json::from_value(serde_json::Value::Array(arr)) {
                Ok(r) => r,
                Err(e) => {
                    return (
                        StatusCode::BAD_REQUEST,
                        Json(serde_json::json!({ "error": format!("batch array: {}", e) })),
                    )
                        .into_response();
                }
            }
        }
        Ok(serde_json::Value::Object(_)) => match serde_json::from_slice::<InvokeRequestDto>(&body)
        {
            Ok(single) => vec![single],
            Err(e) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({ "error": format!("single request: {}", e) })),
                )
                    .into_response();
            }
        },
        _ => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": "body must be a JSON object or array" })),
            )
                .into_response();
        }
    };

    if requests.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({ "error": "empty batch" })),
        )
            .into_response();
    }

    match submit_batch(&requests, auth_secret.as_deref(), state.timeout_secs).await {
        Ok(results) => {
            let json = if results.len() == 1 {
                serde_json::to_value(&results[0]).unwrap_or(serde_json::Value::Null)
            } else {
                serde_json::to_value(&results).unwrap_or(serde_json::Value::Array(vec![]))
            };
            (StatusCode::OK, Json(json)).into_response()
        }
        Err(e) => {
            let (status, msg) = match &e {
                BatchSubmitError::Parse(_) => (StatusCode::BAD_REQUEST, e.to_string()),
                BatchSubmitError::Queue(QueueError::Full) => {
                    (StatusCode::SERVICE_UNAVAILABLE, "queue full".to_string())
                }
                BatchSubmitError::Queue(QueueError::NotInitialized) => (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "queue not initialized".to_string(),
                ),
                BatchSubmitError::Queue(QueueError::Shutdown) => {
                    (StatusCode::SERVICE_UNAVAILABLE, "queue shutdown".to_string())
                }
            };
            (status, Json(serde_json::json!({ "error": msg }))).into_response()
        }
    }
}

/// POST /a2a/{agent_name}/invoke: single or batch; batch fans out to backend per item.
async fn a2a_invoke(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(agent_name): axum::extract::Path<String>,
    headers: HeaderMap,
    request: axum::http::Request<axum::body::Body>,
) -> impl IntoResponse {
    let body_bytes = match axum::body::to_bytes(request.into_body(), 100 * 1024 * 1024).await {
        Ok(b) => b,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": format!("body read: {}", e) })),
            )
                .into_response();
        }
    };

    let value: serde_json::Value = match serde_json::from_slice(&body_bytes) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": format!("invalid json: {}", e) })),
            )
                .into_response();
        }
    };

    if let serde_json::Value::Array(items) = value {
        let futs = items.into_iter().map(|item| {
            let agent = item
                .get("agent_name")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .unwrap_or_else(|| agent_name.clone());
            proxy_invoke_one(state.clone(), agent, &headers, item)
        });
        let results = join_all(futs).await;
        return (StatusCode::OK, Json(serde_json::Value::Array(results))).into_response();
    }

    proxy_invoke_raw(state, &agent_name, &headers, body_bytes.to_vec()).await
}

async fn proxy_invoke_one(
    state: Arc<AppState>,
    agent_name: String,
    headers: &HeaderMap,
    item: serde_json::Value,
) -> serde_json::Value {
    let body = match serde_json::to_vec(&item) {
        Ok(b) => b,
        Err(e) => return serde_json::json!({ "error": format!("encode: {e}") }),
    };
    let resp = proxy_invoke_raw(state, &agent_name, headers, body).await;
    response_body_to_json(resp).await
}

async fn proxy_invoke_raw(
    state: Arc<AppState>,
    agent_name: &str,
    headers: &HeaderMap,
    body: Vec<u8>,
) -> axum::response::Response {
    let path = format!("/a2a/{}/invoke", agent_name);
    let url = format!("{}{}", state.backend_base_url, path);
    let mut req = state.client.post(url);
    for (k, v) in headers.iter() {
        if should_forward_header(k) {
            req = req.header(k, v);
        }
    }
    match req.body(body).send().await {
        Ok(resp) => response_to_axum(resp).await,
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({ "error": format!("backend invoke: {}", e) })),
        )
            .into_response(),
    }
}

async fn a2a_proxy(
    State(state): State<Arc<AppState>>,
    request: axum::http::Request<axum::body::Body>,
) -> impl IntoResponse {
    proxy_request_with_prefix(state, request, "/a2a").await
}

async fn proxy_request_with_prefix(
    state: Arc<AppState>,
    request: axum::http::Request<axum::body::Body>,
    prefix: &str,
) -> axum::response::Response {
    let (parts, body) = request.into_parts();
    let path_and_query = parts
        .uri
        .path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");
    let url = format!("{}{}{}", state.backend_base_url, prefix, path_and_query);
    let method = parts.method;
    let body_bytes = match axum::body::to_bytes(body, 100 * 1024 * 1024).await {
        Ok(b) => b.to_vec(),
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({ "error": format!("body read: {}", e) })),
            )
                .into_response();
        }
    };

    let mut req = state.client.request(method_to_reqwest(method), url);
    for (k, v) in parts.headers.iter() {
        if should_forward_header(k) {
            req = req.header(k, v);
        }
    }
    match req.body(body_bytes).send().await {
        Ok(resp) => response_to_axum(resp).await,
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({ "error": format!("backend proxy: {}", e) })),
        )
            .into_response(),
    }
}

fn method_to_reqwest(method: Method) -> reqwest::Method {
    match method {
        Method::GET => reqwest::Method::GET,
        Method::POST => reqwest::Method::POST,
        Method::PUT => reqwest::Method::PUT,
        Method::PATCH => reqwest::Method::PATCH,
        Method::DELETE => reqwest::Method::DELETE,
        Method::HEAD => reqwest::Method::HEAD,
        Method::OPTIONS => reqwest::Method::OPTIONS,
        other => reqwest::Method::from_bytes(other.as_str().as_bytes())
            .unwrap_or(reqwest::Method::POST),
    }
}

fn should_forward_header(name: &HeaderName) -> bool {
    !matches!(
        name.as_str().to_ascii_lowercase().as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
            | "host"
            | "content-length"
    )
}

async fn response_to_axum(resp: reqwest::Response) -> axum::response::Response {
    let status = StatusCode::from_u16(resp.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut out_headers = HeaderMap::new();
    for (k, v) in resp.headers().iter() {
        if let (Ok(name), Ok(val)) = (
            HeaderName::from_bytes(k.as_str().as_bytes()),
            HeaderValue::from_bytes(v.as_bytes()),
        ) {
            if should_forward_header(&name) {
                out_headers.insert(name, val);
            }
        }
    }
    let bytes = match resp.bytes().await {
        Ok(b) => b.to_vec(),
        Err(_) => Vec::new(),
    };
    (status, out_headers, bytes).into_response()
}

async fn response_body_to_json(resp: axum::response::Response) -> serde_json::Value {
    let (parts, body) = resp.into_parts();
    let status = parts.status.as_u16();
    let bytes = match axum::body::to_bytes(body, 100 * 1024 * 1024).await {
        Ok(b) => b.to_vec(),
        Err(e) => {
            return serde_json::json!({ "status_code": status, "error": format!("body read: {e}") });
        }
    };
    serde_json::from_slice(&bytes).unwrap_or_else(|_| {
        serde_json::json!({ "status_code": status, "error": "invalid backend response" })
    })
}
