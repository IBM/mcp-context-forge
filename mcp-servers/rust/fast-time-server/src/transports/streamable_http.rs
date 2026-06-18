// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::IntoResponse;
use axum::response::Response;
use serde_json::json;
use std::collections::HashSet;
use std::sync::{LazyLock, RwLock};
use uuid::Uuid;

use crate::config::{MAX_ACTIVE_SESSIONS, SESSION_HEADER};
use crate::mcp;

static ACTIVE_SESSIONS: LazyLock<RwLock<HashSet<String>>> =
    LazyLock::new(|| RwLock::new(HashSet::new()));

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
        "initialize" => initialize_response(id),
        _ => mcp::error_response(id, -32601, "Method not found", None),
    }
}

fn initialize_response(id: Option<&serde_json::Value>) -> Response {
    let session_id = Uuid::new_v4().to_string();
    let session_header = HeaderValue::from_str(&session_id)
        .unwrap_or_else(|_| HeaderValue::from_static("fast-time"));
    if !remember_session(session_id) {
        return mcp::error_response_with_status(
            StatusCode::SERVICE_UNAVAILABLE,
            id,
            -32000,
            "Maximum active sessions reached",
            Some(json!({ "max_sessions": MAX_ACTIVE_SESSIONS })),
        );
    }
    let mut response = mcp::json_response(mcp::initialize_body(id));
    response
        .headers_mut()
        .insert(SESSION_HEADER, session_header);
    response
}

fn remember_session(session_id: String) -> bool {
    if let Ok(mut sessions) = ACTIVE_SESSIONS.write() {
        remember_session_in(&mut sessions, session_id)
    } else {
        false
    }
}

fn remember_session_in(sessions: &mut HashSet<String>, session_id: String) -> bool {
    if sessions.len() >= MAX_ACTIVE_SESSIONS {
        return false;
    }
    sessions.insert(session_id)
}

fn remove_session(session_id: &str) -> bool {
    ACTIVE_SESSIONS
        .write()
        .map(|mut sessions| sessions.remove(session_id))
        .unwrap_or(false)
}

fn validate_active_session(headers: &HeaderMap) -> Result<(), StatusCode> {
    let Some(session_id) = session_id(headers) else {
        return Err(StatusCode::BAD_REQUEST);
    };
    if ACTIVE_SESSIONS
        .read()
        .map(|sessions| sessions.contains(session_id))
        .unwrap_or(false)
    {
        Ok(())
    } else {
        Err(StatusCode::NOT_FOUND)
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
        let mut sessions = HashSet::with_capacity(MAX_ACTIVE_SESSIONS);
        for idx in 0..MAX_ACTIVE_SESSIONS {
            assert!(remember_session_in(
                &mut sessions,
                format!("test-session-{idx}")
            ));
        }

        assert!(!remember_session_in(
            &mut sessions,
            "overflow-session".to_string()
        ));
        assert_eq!(sessions.len(), MAX_ACTIVE_SESSIONS);
    }

    #[tokio::test]
    async fn test_initialize_accepts_older_protocol_and_advertises_latest() {
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
        assert!(response.headers().contains_key(SESSION_HEADER));
        let session_id = response
            .headers()
            .get(SESSION_HEADER)
            .expect("initialize should issue session id")
            .to_str()
            .expect("session id should be ascii")
            .to_string();
        assert!(Uuid::parse_str(&session_id).is_ok());
        assert!(!session_id.starts_with("fast-time-"));
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
