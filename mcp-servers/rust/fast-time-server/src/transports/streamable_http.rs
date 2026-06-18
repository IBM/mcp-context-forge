// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::IntoResponse;
use axum::response::Response;
use serde_json::json;
use std::collections::HashMap;
use std::sync::{LazyLock, RwLock};
use std::time::Instant;
use uuid::Uuid;

use crate::config::{MAX_ACTIVE_SESSIONS, SESSION_HEADER, SESSION_IDLE_TTL};
use crate::mcp;

/// Active sessions keyed by id, with the last time each was seen so idle
/// sessions can be evicted instead of leaking until the cap is hit.
static ACTIVE_SESSIONS: LazyLock<RwLock<HashMap<String, Instant>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

pub(crate) async fn delete_handler(headers: HeaderMap) -> StatusCode {
    let Some(session_id) = session_id(&headers) else {
        return StatusCode::BAD_REQUEST;
    };
    if remove_session(session_id) {
        StatusCode::OK
    } else {
        StatusCode::NOT_FOUND
    }
}

pub(crate) async fn handler(
    headers: HeaderMap,
    axum::Json(req): axum::Json<serde_json::Value>,
) -> Response {
    let method = req
        .get("method")
        .and_then(serde_json::Value::as_str)
        .unwrap_or_default();
    let id = req.get("id");

    if method != "initialize" {
        let Err(status) = validate_active_session(&headers) else {
            if id.is_none() {
                return StatusCode::ACCEPTED.into_response();
            }
            return match method {
                "ping" => mcp::empty_result_response(id),
                "tools/list" => mcp::tools_list_response(id),
                "tools/call" => mcp::tools_call_response(id, &req).await,
                _ => mcp::error_response(id, -32601, "Method not found", None),
            };
        };
        if id.is_none() {
            return status.into_response();
        }
        return mcp::error_response_with_status(status, id, -32000, "Invalid session ID", None);
    }

    if id.is_none() {
        return StatusCode::ACCEPTED.into_response();
    }

    match method {
        "initialize" => initialize_response(id, mcp::negotiate_protocol_version(&req)),
        _ => mcp::error_response(id, -32601, "Method not found", None),
    }
}

fn initialize_response(id: Option<&serde_json::Value>, protocol_version: &str) -> Response {
    let session_id = Uuid::new_v4().to_string();
    let session_header =
        HeaderValue::from_str(&session_id).expect("uuid string is always a valid header value");
    if !remember_session(session_id) {
        return mcp::error_response_with_status(
            StatusCode::SERVICE_UNAVAILABLE,
            id,
            -32000,
            "Maximum active sessions reached",
            Some(json!({ "max_sessions": MAX_ACTIVE_SESSIONS })),
        );
    }
    let mut response = mcp::json_response(mcp::initialize_body(id, protocol_version));
    response
        .headers_mut()
        .insert(SESSION_HEADER, session_header);
    response
}

fn remember_session(session_id: String) -> bool {
    if let Ok(mut sessions) = ACTIVE_SESSIONS.write() {
        remember_session_in(&mut sessions, session_id, Instant::now())
    } else {
        false
    }
}

fn remember_session_in(
    sessions: &mut HashMap<String, Instant>,
    session_id: String,
    now: Instant,
) -> bool {
    sessions.retain(|_, last_seen| now.duration_since(*last_seen) < SESSION_IDLE_TTL);
    if sessions.len() >= MAX_ACTIVE_SESSIONS {
        return false;
    }
    sessions.insert(session_id, now).is_none()
}

fn remove_session(session_id: &str) -> bool {
    ACTIVE_SESSIONS
        .write()
        .map(|mut sessions| sessions.remove(session_id).is_some())
        .unwrap_or(false)
}

fn validate_active_session(headers: &HeaderMap) -> Result<(), StatusCode> {
    let Some(session_id) = session_id(headers) else {
        return Err(StatusCode::BAD_REQUEST);
    };
    let Ok(mut sessions) = ACTIVE_SESSIONS.write() else {
        return Err(StatusCode::NOT_FOUND);
    };
    match sessions.get_mut(session_id) {
        Some(last_seen) => {
            *last_seen = Instant::now();
            Ok(())
        }
        None => Err(StatusCode::NOT_FOUND),
    }
}

fn session_id(headers: &HeaderMap) -> Option<&str> {
    headers.get(SESSION_HEADER)?.to_str().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body;

    async fn response_text(response: Response) -> String {
        let bytes = body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("response body should be readable");
        String::from_utf8(bytes.to_vec()).expect("response body should be utf-8")
    }

    async fn response_json(response: Response) -> serde_json::Value {
        serde_json::from_str(&response_text(response).await).expect("response body should be json")
    }

    async fn initialized_headers() -> HeaderMap {
        let response = handler(
            HeaderMap::new(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "go-parity",
                        "version": "1.0"
                    }
                },
                "id": 1
            })),
        )
        .await;
        let mut headers = HeaderMap::new();
        headers.insert(
            SESSION_HEADER,
            response
                .headers()
                .get(SESSION_HEADER)
                .expect("initialize should issue session id")
                .clone(),
        );
        headers
    }

    #[test]
    fn test_active_session_validation() {
        let session_id = "unit-test-session-validation";
        remove_session(session_id);

        let mut headers = HeaderMap::new();
        headers.insert(SESSION_HEADER, HeaderValue::from_static(session_id));
        assert_eq!(
            validate_active_session(&headers),
            Err(StatusCode::NOT_FOUND)
        );

        assert!(remember_session(session_id.to_string()));
        assert_eq!(validate_active_session(&headers), Ok(()));

        assert!(remove_session(session_id));
        assert_eq!(
            validate_active_session(&headers),
            Err(StatusCode::NOT_FOUND)
        );
    }

    #[test]
    fn test_session_cap_rejects_new_session_when_full() {
        let now = Instant::now();
        let mut sessions = HashMap::with_capacity(MAX_ACTIVE_SESSIONS);
        for idx in 0..MAX_ACTIVE_SESSIONS {
            assert!(remember_session_in(
                &mut sessions,
                format!("test-session-{idx}"),
                now
            ));
        }

        assert!(!remember_session_in(
            &mut sessions,
            "overflow-session".to_string(),
            now
        ));
        assert_eq!(sessions.len(), MAX_ACTIVE_SESSIONS);
    }

    #[test]
    fn test_idle_sessions_are_evicted_on_insert() {
        let stale_at = Instant::now();
        let now = stale_at + SESSION_IDLE_TTL + std::time::Duration::from_secs(1);
        let mut sessions = HashMap::new();
        sessions.insert("stale-session".to_string(), stale_at);

        assert!(remember_session_in(
            &mut sessions,
            "fresh-session".to_string(),
            now
        ));
        assert!(!sessions.contains_key("stale-session"));
        assert!(sessions.contains_key("fresh-session"));
    }

    #[tokio::test]
    async fn test_initialize_negotiates_supported_protocol_version() {
        let response = handler(
            HeaderMap::new(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "go-compat-smoke",
                        "version": "1.0"
                    }
                },
                "id": 1
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let session_id = response
            .headers()
            .get(SESSION_HEADER)
            .expect("initialize should issue session id")
            .to_str()
            .expect("session id should be ascii")
            .to_string();
        assert!(Uuid::parse_str(&session_id).is_ok());
        let body = response_text(response).await;
        assert!(body.contains(r#""protocolVersion":"2024-11-05""#));
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_initialize_falls_back_to_latest_for_unsupported_protocol() {
        let response = handler(
            HeaderMap::new(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "1999-01-01",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "go-compat-smoke",
                        "version": "1.0"
                    }
                },
                "id": 1
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let session_id = response
            .headers()
            .get(SESSION_HEADER)
            .expect("initialize should issue session id")
            .to_str()
            .expect("session id should be ascii")
            .to_string();
        let body = response_text(response).await;
        assert!(body.contains(r#""protocolVersion":"2025-11-25""#));
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_direct_mcp_session_lifecycle_matches_streamable_http() {
        let initialize = handler(
            HeaderMap::new(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "go-compat-smoke",
                        "version": "1.0"
                    }
                },
                "id": 1
            })),
        )
        .await;
        let session_id = initialize
            .headers()
            .get(SESSION_HEADER)
            .expect("initialize should issue session id")
            .clone();

        let mut valid_headers = HeaderMap::new();
        valid_headers.insert(SESSION_HEADER, session_id.clone());
        let valid = handler(
            valid_headers.clone(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 2
            })),
        )
        .await;
        assert_eq!(valid.status(), StatusCode::OK);

        let ping = handler(
            valid_headers.clone(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "ping",
                "id": 6
            })),
        )
        .await;
        assert_eq!(ping.status(), StatusCode::OK);
        let ping_body = response_json(ping).await;
        assert_eq!(ping_body["result"], json!({}));

        let missing = handler(
            HeaderMap::new(),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 3
            })),
        )
        .await;
        assert_eq!(missing.status(), StatusCode::BAD_REQUEST);

        let mut fake_headers = HeaderMap::new();
        fake_headers.insert(SESSION_HEADER, HeaderValue::from_static("fake-session"));
        let fake = handler(
            fake_headers,
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 4
            })),
        )
        .await;
        assert_eq!(fake.status(), StatusCode::NOT_FOUND);

        assert_eq!(delete_handler(valid_headers.clone()).await, StatusCode::OK);
        let deleted = handler(
            valid_headers,
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 5
            })),
        )
        .await;
        assert_eq!(deleted.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn test_mcp_echo_rejects_delay_above_limit() {
        let response = handler(
            initialized_headers().await,
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {
                        "message": "hello",
                        "delay": crate::config::MAX_DELAY_MS + 1
                    }
                },
                "id": 12
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::OK);
        let body = response_json(response).await;
        assert_eq!(body["error"]["code"], -32602);
        assert_eq!(body["error"]["message"], "delay exceeds the 60000 ms limit");
    }
}
