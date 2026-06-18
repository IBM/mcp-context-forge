// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

use axum::extract::Query;
use axum::http::StatusCode;
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use std::collections::HashMap;
use std::convert::Infallible;
use std::pin::Pin;
use std::sync::{LazyLock, RwLock};
use std::task::{Context, Poll};
use tokio::sync::mpsc;
use tokio_stream::Stream;
use tokio_stream::wrappers::ReceiverStream;
use uuid::Uuid;

use crate::config::{MAX_ACTIVE_SESSIONS, SSE_CHANNEL_CAPACITY};
use crate::mcp;

static SSE_SESSIONS: LazyLock<RwLock<HashMap<String, mpsc::Sender<String>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

#[derive(Debug, serde::Deserialize)]
pub(crate) struct MessageQuery {
    #[serde(rename = "sessionId")]
    session_id_camel: Option<String>,
    session_id: Option<String>,
}

impl MessageQuery {
    fn session_id(&self) -> Option<&str> {
        self.session_id_camel
            .as_deref()
            .or(self.session_id.as_deref())
    }
}

struct SessionStream {
    session_id: String,
    endpoint: Option<String>,
    receiver: ReceiverStream<String>,
}

impl SessionStream {
    fn new(session_id: String, receiver: mpsc::Receiver<String>) -> Self {
        let endpoint = Some(format!("/messages?sessionId={session_id}"));
        Self {
            session_id,
            endpoint,
            receiver: ReceiverStream::new(receiver),
        }
    }
}

impl Stream for SessionStream {
    type Item = Result<Event, Infallible>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if let Some(endpoint) = self.endpoint.take() {
            return Poll::Ready(Some(Ok(Event::default().event("endpoint").data(endpoint))));
        }

        Pin::new(&mut self.receiver)
            .poll_next(cx)
            .map(|message| message.map(|data| Ok(Event::default().event("message").data(data))))
    }
}

impl Drop for SessionStream {
    fn drop(&mut self) {
        remove_session(&self.session_id);
    }
}

pub(crate) async fn handler() -> Response {
    let session_id = Uuid::new_v4().to_string();
    let (sender, receiver) = mpsc::channel(SSE_CHANNEL_CAPACITY);
    if !remember_session(session_id.clone(), sender) {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    }

    Sse::new(SessionStream::new(session_id, receiver))
        .keep_alive(KeepAlive::default())
        .into_response()
}

pub(crate) async fn message_handler(
    Query(query): Query<MessageQuery>,
    axum::Json(req): axum::Json<serde_json::Value>,
) -> Response {
    let Some(session_id) = query.session_id() else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    let Some(sender) = session_sender(session_id) else {
        return StatusCode::NOT_FOUND.into_response();
    };

    if let Some(message) = mcp::sse_message_response(&req).await
        && sender.send(message).await.is_err()
    {
        remove_session(session_id);
        return StatusCode::GONE.into_response();
    }

    StatusCode::ACCEPTED.into_response()
}

fn remember_session(session_id: String, sender: mpsc::Sender<String>) -> bool {
    if let Ok(mut sessions) = SSE_SESSIONS.write() {
        if sessions.len() >= MAX_ACTIVE_SESSIONS {
            return false;
        }
        sessions.insert(session_id, sender);
        true
    } else {
        false
    }
}

fn session_sender(session_id: &str) -> Option<mpsc::Sender<String>> {
    SSE_SESSIONS
        .read()
        .ok()
        .and_then(|sessions| sessions.get(session_id).cloned())
}

fn remove_session(session_id: &str) -> bool {
    SSE_SESSIONS
        .write()
        .map(|mut sessions| sessions.remove(session_id).is_some())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn test_sse_message_handler_sends_initialize_response() {
        let session_id = Uuid::new_v4().to_string();
        let (sender, mut receiver) = mpsc::channel(1);
        assert!(remember_session(session_id.clone(), sender));

        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: Some(session_id.clone()),
                session_id: None,
            }),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "sse-smoke",
                        "version": "1.0"
                    }
                },
                "id": 1
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let message = receiver
            .recv()
            .await
            .expect("initialize response should be sent as SSE data");
        let body: serde_json::Value =
            serde_json::from_str(&message).expect("SSE message should be JSON-RPC");
        assert_eq!(
            body["result"]["protocolVersion"],
            crate::config::MCP_PROTOCOL_VERSION
        );
        assert_eq!(
            body["result"]["serverInfo"]["name"],
            crate::config::APP_NAME
        );
        assert!(body["result"]["capabilities"]["tools"].is_object());
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_sse_message_handler_accepts_session_id_alias() {
        let session_id = Uuid::new_v4().to_string();
        let (sender, mut receiver) = mpsc::channel(1);
        assert!(remember_session(session_id.clone(), sender));

        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: None,
                session_id: Some(session_id.clone()),
            }),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 2
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let message = receiver
            .recv()
            .await
            .expect("tools/list response should be sent as SSE data");
        let body: serde_json::Value =
            serde_json::from_str(&message).expect("SSE message should be JSON-RPC");
        assert_eq!(body["result"]["tools"][0]["name"], "echo");
        assert!(remove_session(&session_id));
    }

    #[tokio::test]
    async fn test_sse_message_handler_rejects_unknown_session() {
        let response = message_handler(
            Query(MessageQuery {
                session_id_camel: Some("missing-sse-session".to_string()),
                session_id: None,
            }),
            axum::Json(json!({
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 3
            })),
        )
        .await;

        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }
}
