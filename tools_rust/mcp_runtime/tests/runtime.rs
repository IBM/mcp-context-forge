// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
// Authors: Mihai Criveti

use axum::{
    Json, Router,
    http::{HeaderMap, StatusCode, Uri},
    response::IntoResponse,
    routing::{any, delete, get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use contextforge_mcp_runtime::{AppState, build_router, config::RuntimeConfig};
use futures_util::StreamExt;
use redis::AsyncCommands;
use reqwest::header::HeaderValue;
use serde_json::{Value, json};
use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use uuid::Uuid;

type ObservedBackendCall = (String, Option<String>, Option<String>);

#[derive(Clone, Default)]
struct BackendObservation {
    calls: Arc<Mutex<Vec<ObservedBackendCall>>>,
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}

fn hex_decode(input: &str) -> Vec<u8> {
    input
        .as_bytes()
        .chunks_exact(2)
        .filter_map(|chunk| {
            let high = (chunk[0] as char).to_digit(16)?;
            let low = (chunk[1] as char).to_digit(16)?;
            u8::try_from((high << 4) | low).ok()
        })
        .collect()
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

fn test_runtime_config() -> RuntimeConfig {
    RuntimeConfig {
        backend_rpc_url: "http://127.0.0.1:4444/rpc".to_string(),
        listen_http: "127.0.0.1:8787".to_string(),
        listen_uds: None,
        public_listen_http: None,
        protocol_version: "2025-11-25".to_string(),
        supported_protocol_versions: vec![],
        server_name: "ContextForge".to_string(),
        server_version: "0.1.0".to_string(),
        instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
        request_timeout_ms: 30_000,
        client_connect_timeout_ms: 5_000,
        client_pool_idle_timeout_seconds: 90,
        client_pool_max_idle_per_host: 1024,
        client_tcp_keepalive_seconds: 30,
        tools_call_plan_ttl_seconds: 30,
        upstream_session_ttl_seconds: 300,
        use_rmcp_upstream_client: false,
        session_core_enabled: false,
        event_store_enabled: false,
        resume_core_enabled: false,
        live_stream_core_enabled: false,
        affinity_core_enabled: false,
        session_auth_reuse_enabled: false,
        session_auth_reuse_ttl_seconds: 30,
        session_ttl_seconds: 3_600,
        event_store_max_events_per_stream: 100,
        event_store_ttl_seconds: 3_600,
        event_store_poll_interval_ms: 250,
        cache_prefix: "mcpgw:".to_string(),
        database_url: None,
        redis_url: None,
        db_pool_max_size: 20,
        log_filter: "error".to_string(),
        exit_after_startup_ms: None,
    }
}

async fn redis_is_available(redis_url: &str) -> bool {
    let Ok(client) = redis::Client::open(redis_url) else {
        return false;
    };
    let Ok(mut conn) = client.get_multiplexed_async_connection().await else {
        return false;
    };
    redis::cmd("PING")
        .query_async::<String>(&mut conn)
        .await
        .is_ok()
}

async fn cleanup_redis_prefix(redis_url: &str, prefix: &str) {
    let Ok(client) = redis::Client::open(redis_url) else {
        return;
    };
    let Ok(mut conn) = client.get_multiplexed_async_connection().await else {
        return;
    };
    let pattern = format!("{prefix}*");
    let keys = redis::cmd("KEYS")
        .arg(pattern)
        .query_async::<Vec<String>>(&mut conn)
        .await
        .unwrap_or_default();
    if !keys.is_empty() {
        let _ = conn.del::<_, ()>(keys).await;
    }
}

async fn initialize_runtime_session(
    runtime_url: &str,
    session_id: &str,
    auth_context: Option<&str>,
) {
    let client = reqwest::Client::new();
    let mut request = client
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .header("mcp-session-id", session_id)
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}}
        }));
    if let Some(auth_context) = auth_context {
        request = request.header("x-contextforge-auth-context", auth_context);
    }
    let response = request.send().await.expect("initialize response");
    let status = response.status();
    let body = response.text().await.expect("initialize body");
    assert_eq!(
        status,
        StatusCode::OK,
        "initialize session {session_id} failed: {body}"
    );
}

#[tokio::test]
async fn ping_is_handled_locally() {
    let observation = BackendObservation::default();
    let backend = {
        let observation = observation.clone();
        Router::new().route(
            "/rpc",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let observation = observation.clone();
                async move {
                    observation.calls.lock().expect("lock").push((
                        body.get("method")
                            .and_then(Value::as_str)
                            .unwrap_or("unknown")
                            .to_string(),
                        headers
                            .get("authorization")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                    ));
                    Json(json!({"jsonrpc":"2.0","id":1,"result":{"backend":true}}))
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/rpc"))
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "ping",
            "params": {}
        }))
        .send()
        .await
        .expect("ping response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"], json!({}));
    assert!(observation.calls.lock().expect("lock").is_empty());
}

#[tokio::test]
async fn health_alias_is_available_for_gateway_style_probes() {
    let config = RuntimeConfig {
        backend_rpc_url: "http://127.0.0.1:4444/rpc".to_string(),
        listen_http: "127.0.0.1:8787".to_string(),
        listen_uds: None,
        protocol_version: "2025-11-25".to_string(),
        supported_protocol_versions: vec![],
        server_name: "ContextForge".to_string(),
        server_version: "0.1.0".to_string(),
        instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
        request_timeout_ms: 30_000,
        database_url: None,
        db_pool_max_size: 20,
        log_filter: "error".to_string(),
        ..test_runtime_config()
    };
    let runtime_url = spawn_router(build_router(AppState::new(&config).expect("state"))).await;

    let response = reqwest::Client::new()
        .get(format!("{runtime_url}/health"))
        .send()
        .await
        .expect("health response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["status"], "ok");
    assert_eq!(body["session_core_enabled"], json!(false));
    assert_eq!(body["event_store_enabled"], json!(false));
    assert_eq!(body["resume_core_enabled"], json!(false));
    assert_eq!(body["live_stream_core_enabled"], json!(false));
    assert_eq!(body["session_auth_reuse_enabled"], json!(false));
    assert_eq!(body["active_sessions"], json!(0));
    assert_eq!(
        body["runtime_stats"]["session_auth_reuse"]["hits"],
        json!(0)
    );
    assert_eq!(
        body["runtime_stats"]["session_access_denials"]["server_scope_mismatches"],
        json!(0)
    );
    assert!(
        body["supported_protocol_versions"]
            .as_array()
            .expect("supported protocol versions array")
            .iter()
            .any(|value| value == "2025-03-26")
    );
}

#[tokio::test]
async fn server_scoped_public_initialize_authenticates_before_backend_dispatch() {
    let auth_calls = Arc::new(Mutex::new(Vec::<Value>::new()));
    let initialize_calls = Arc::new(Mutex::new(Vec::<(Option<String>, Option<String>)>::new()));

    let backend = {
        let auth_calls = auth_calls.clone();
        let initialize_calls = initialize_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/authenticate",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let auth_calls = auth_calls.clone();
                    async move {
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        auth_calls.lock().expect("lock").push(body.clone());
                        Json(json!({
                            "authContext": {
                                "email": "user@example.com",
                                "teams": ["team-a"],
                                "is_authenticated": true,
                                "is_admin": false,
                                "permission_is_admin": false,
                                "token_use": "session"
                            }
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/initialize",
                post(move |headers: HeaderMap, Json(_body): Json<Value>| {
                    let initialize_calls = initialize_calls.clone();
                    async move {
                        initialize_calls.lock().expect("lock").push((
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            headers
                                .get("x-contextforge-auth-context")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "serverInfo": {"name": "ContextForge", "version": "0.1.0"}
                            }
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            public_listen_http: Some("127.0.0.1:8788".to_string()),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/servers/server-1/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-forwarded-for", "203.0.113.10")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}}
        }))
        .send()
        .await
        .expect("initialize response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );

    let auth_call = auth_calls.lock().expect("lock");
    assert_eq!(auth_call.len(), 1);
    assert_eq!(auth_call[0]["path"], "/servers/server-1/mcp");
    assert!(auth_call[0]["clientIp"].is_null());
    assert_eq!(
        auth_call[0]["headers"]["authorization"],
        "Bearer test-token"
    );

    let initialize_call = initialize_calls.lock().expect("lock");
    assert_eq!(initialize_call.len(), 1);
    assert_eq!(initialize_call[0].0.as_deref(), Some("server-1"));
    assert!(initialize_call[0].1.is_some());
}

#[tokio::test]
async fn public_session_reuses_authenticated_context_when_flag_enabled() {
    let auth_calls = Arc::new(Mutex::new(0usize));
    let roots_calls = Arc::new(Mutex::new(Vec::<Option<String>>::new()));

    let backend = {
        let auth_calls = auth_calls.clone();
        let roots_calls = roots_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/authenticate",
                post(move || {
                    let auth_calls = auth_calls.clone();
                    async move {
                        *auth_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "authContext": {
                                "email": "user@example.com",
                                "teams": ["team-a"],
                                "is_authenticated": true,
                                "is_admin": false,
                                "permission_is_admin": false,
                                "token_use": "session"
                            }
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/transport",
                post(|| async move {
                    Json(json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "ContextForge", "version": "0.1.0"}
                        }
                    }))
                }),
            )
            .route(
                "/_internal/mcp/roots/list",
                post(move |headers: HeaderMap| {
                    let roots_calls = roots_calls.clone();
                    async move {
                        roots_calls.lock().expect("lock").push(
                            headers
                                .get("x-contextforge-auth-context")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        );
                        Json(json!({"jsonrpc":"2.0","id":2,"result":{"roots":[]}}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            public_listen_http: Some("127.0.0.1:8788".to_string()),
            session_core_enabled: true,
            session_auth_reuse_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer alpha")
        .header("mcp-session-id", "session-reuse-1")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}}
        }))
        .send()
        .await
        .expect("initialize response");
    assert_eq!(initialize_response.status(), StatusCode::OK);

    let roots_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer alpha")
        .header("mcp-session-id", "session-reuse-1")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "roots/list",
            "params": {}
        }))
        .send()
        .await
        .expect("roots response");
    assert_eq!(roots_response.status(), StatusCode::OK);

    assert_eq!(*auth_calls.lock().expect("lock"), 1);
    assert_eq!(roots_calls.lock().expect("lock").len(), 1);
    assert!(
        roots_calls.lock().expect("lock")[0].is_some(),
        "Rust should forward the reused auth context header to the backend roots/list route",
    );
}

#[tokio::test]
async fn public_session_denies_when_auth_binding_changes() {
    let auth_calls = Arc::new(Mutex::new(0usize));

    let backend = {
        let auth_calls = auth_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/authenticate",
                post(move || {
                    let auth_calls = auth_calls.clone();
                    async move {
                        *auth_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "authContext": {
                                "email": "user@example.com",
                                "teams": ["team-a"],
                                "is_authenticated": true,
                                "is_admin": false,
                                "permission_is_admin": false,
                                "token_use": "session"
                            }
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/transport",
                post(|| async move {
                    Json(json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "ContextForge", "version": "0.1.0"}
                        }
                    }))
                }),
            )
            .route(
                "/_internal/mcp/roots/list",
                post(|| async move { Json(json!({"jsonrpc":"2.0","id":2,"result":{"roots":[]}})) }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            public_listen_http: Some("127.0.0.1:8788".to_string()),
            session_core_enabled: true,
            session_auth_reuse_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer alpha")
        .header("mcp-session-id", "session-reuse-2")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}}
        }))
        .send()
        .await
        .expect("initialize response");
    assert_eq!(initialize_response.status(), StatusCode::OK);

    let roots_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer beta")
        .header("mcp-session-id", "session-reuse-2")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "roots/list",
            "params": {}
        }))
        .send()
        .await
        .expect("roots response");
    assert_eq!(roots_response.status(), StatusCode::FORBIDDEN);
    let body: Value = roots_response.json().await.expect("roots json");
    assert_eq!(body["detail"], json!("Session access denied"));

    assert_eq!(
        *auth_calls.lock().expect("lock"),
        2,
        "Changed auth material should still be rechecked before the public MCP session is denied",
    );
}

#[tokio::test]
async fn public_session_reauthenticates_after_auth_reuse_ttl_expires() {
    let auth_calls = Arc::new(Mutex::new(0usize));

    let backend = {
        let auth_calls = auth_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/authenticate",
                post(move || {
                    let auth_calls = auth_calls.clone();
                    async move {
                        *auth_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "authContext": {
                                "email": "user@example.com",
                                "teams": ["team-a"],
                                "is_authenticated": true,
                                "is_admin": false,
                                "permission_is_admin": false,
                                "token_use": "session"
                            }
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/transport",
                post(|| async move {
                    Json(json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "ContextForge", "version": "0.1.0"}
                        }
                    }))
                }),
            )
            .route(
                "/_internal/mcp/roots/list",
                post(|| async move { Json(json!({"jsonrpc":"2.0","id":2,"result":{"roots":[]}})) }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            public_listen_http: Some("127.0.0.1:8788".to_string()),
            session_core_enabled: true,
            session_auth_reuse_enabled: true,
            session_auth_reuse_ttl_seconds: 1,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer alpha")
        .header("mcp-session-id", "session-reuse-3")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}}
        }))
        .send()
        .await
        .expect("initialize response");
    assert_eq!(initialize_response.status(), StatusCode::OK);

    let deadline = Instant::now() + Duration::from_secs(4);
    let mut last_status = None;
    while Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(200)).await;
        let roots_response = client
            .post(format!("{runtime_url}/mcp"))
            .header("authorization", "Bearer alpha")
            .header("mcp-session-id", "session-reuse-3")
            .header("mcp-protocol-version", "2025-11-25")
            .json(&json!({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "roots/list",
                "params": {}
            }))
            .send()
            .await
            .expect("roots response");
        last_status = Some(roots_response.status());
        if *auth_calls.lock().expect("lock") == 2 {
            break;
        }
    }
    assert_eq!(last_status, Some(StatusCode::OK));

    assert_eq!(
        *auth_calls.lock().expect("lock"),
        2,
        "Expired session-bound auth context should force Rust to fall back to backend authenticate",
    );
}

#[tokio::test]
async fn get_and_delete_mcp_routes_forward_to_internal_transport_bridge() {
    let transport_calls = Arc::new(Mutex::new(Vec::<(
        String,
        Option<String>,
        Option<String>,
        Option<String>,
    )>::new()));
    let backend = {
        let get_transport_calls = transport_calls.clone();
        let delete_transport_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            get(move |headers: HeaderMap, uri: Uri| {
                let transport_calls = get_transport_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push((
                        "GET".to_string(),
                        headers
                            .get("authorization")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        uri.query().map(str::to_string),
                    ));
                    (
                        StatusCode::OK,
                        [(
                            "content-type",
                            HeaderValue::from_static("text/event-stream"),
                        )],
                        "data: ping\n\n",
                    )
                }
            })
            .delete(move |headers: HeaderMap, uri: Uri| {
                let transport_calls = delete_transport_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push((
                        "DELETE".to_string(),
                        headers
                            .get("authorization")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        uri.query().map(str::to_string),
                    ));
                    StatusCode::NO_CONTENT
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let get_response = client
        .get(format!("{runtime_url}/mcp?session_id=session-42"))
        .header("authorization", "Bearer test-token")
        .header("mcp-session-id", "client-session-1")
        .header("x-contextforge-server-id", "server-1")
        .send()
        .await
        .expect("get response");

    assert_eq!(get_response.status(), StatusCode::OK);
    assert_eq!(
        get_response
            .headers()
            .get("content-type")
            .and_then(|value| value.to_str().ok()),
        Some("text/event-stream")
    );
    assert_eq!(
        get_response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    assert_eq!(
        get_response.text().await.expect("stream text"),
        "data: ping\n\n"
    );

    let delete_response = client
        .delete(format!("{runtime_url}/mcp?session_id=session-42"))
        .header("authorization", "Bearer test-token")
        .header("mcp-session-id", "client-session-1")
        .header("x-contextforge-server-id", "server-1")
        .send()
        .await
        .expect("delete response");

    assert_eq!(delete_response.status(), StatusCode::NO_CONTENT);
    assert_eq!(
        delete_response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.len(), 2);
    assert_eq!(
        calls[0],
        (
            "GET".to_string(),
            Some("Bearer test-token".to_string()),
            Some("client-session-1".to_string()),
            Some("session_id=session-42".to_string())
        )
    );
    assert_eq!(
        calls[1],
        (
            "DELETE".to_string(),
            Some("Bearer test-token".to_string()),
            Some("client-session-1".to_string()),
            Some("session_id=session-42".to_string())
        )
    );
}

#[tokio::test]
async fn session_core_initialize_tracks_session_and_reuses_server_scope_for_transport_requests() {
    let transport_calls = Arc::new(Mutex::new(Vec::<(
        String,
        Option<String>,
        Option<String>,
        Option<String>,
        Option<String>,
    )>::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        let delete_calls = transport_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/transport",
                post(move |headers: HeaderMap, uri: Uri, Json(body): Json<Value>| {
                    let transport_calls = post_calls.clone();
                    async move {
                        transport_calls.lock().expect("lock").push((
                            "POST".to_string(),
                            headers
                                .get("mcp-session-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            uri.query().map(str::to_string),
                            headers
                                .get("x-contextforge-session-validated")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        let mut response_headers = HeaderMap::new();
                        response_headers.insert(
                            "mcp-session-id",
                            HeaderValue::from_static("transport-session-1"),
                        );
                        (
                            StatusCode::OK,
                            response_headers,
                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"ContextForge","version":"0.1.0"}}
                            })),
                        )
                    }
                })
                .get(move |headers: HeaderMap, uri: Uri| {
                    let transport_calls = get_calls.clone();
                    async move {
                        transport_calls.lock().expect("lock").push((
                            "GET".to_string(),
                            headers
                                .get("mcp-session-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            uri.query().map(str::to_string),
                            headers
                                .get("x-contextforge-session-validated")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        (
                            StatusCode::OK,
                            [("content-type", HeaderValue::from_static("text/event-stream"))],
                            "data: ping\n\n",
                        )
                    }
                }),
            )
            .route(
                "/_internal/mcp/session",
                delete(move |headers: HeaderMap| {
                    let transport_calls = delete_calls.clone();
                    async move {
                        transport_calls.lock().expect("lock").push((
                            "SESSION_DELETE".to_string(),
                            headers
                                .get("mcp-session-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                            None,
                            headers
                                .get("x-contextforge-session-validated")
                                .and_then(|value| value.to_str().ok())
                                .map(str::to_string),
                        ));
                        StatusCode::NO_CONTENT
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "user@example.com",
            "teams": ["team-a"],
            "is_admin": false
        }))
        .expect("auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context.clone())
        .header("x-contextforge-server-id", "server-123")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{"elicitation":{}}}
        }))
        .send()
        .await
        .expect("initialize response");

    assert_eq!(initialize_response.status(), StatusCode::OK);
    assert_eq!(
        initialize_response
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("transport-session-1")
    );
    assert_eq!(
        initialize_response
            .headers()
            .get("x-contextforge-mcp-session-core")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );

    let get_response = client
        .get(format!("{runtime_url}/mcp?session_id=transport-session-1"))
        .header("x-contextforge-auth-context", auth_context.clone())
        .send()
        .await
        .expect("get response");
    assert_eq!(get_response.status(), StatusCode::OK);

    let delete_response = client
        .delete(format!("{runtime_url}/mcp?session_id=transport-session-1"))
        .header("x-contextforge-auth-context", auth_context)
        .send()
        .await
        .expect("delete response");
    assert_eq!(delete_response.status(), StatusCode::NO_CONTENT);

    let health_response = client
        .get(format!("{runtime_url}/health"))
        .send()
        .await
        .expect("health response");
    let health_body: Value = health_response.json().await.expect("health json");
    assert_eq!(health_body["session_core_enabled"], json!(true));
    assert_eq!(health_body["active_sessions"], json!(0));
    assert_eq!(
        health_body["runtime_stats"]["session_auth_reuse"]["hits"],
        json!(0)
    );

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls[0].0, "POST".to_string());
    assert!(calls[0].1.is_some());
    assert_eq!(calls[0].2.as_deref(), Some("server-123"));
    assert_eq!(calls[0].3, None);
    assert_eq!(calls[0].4, None);
    assert_eq!(
        calls[1],
        (
            "GET".to_string(),
            Some("transport-session-1".to_string()),
            Some("server-123".to_string()),
            Some("session_id=transport-session-1".to_string()),
            Some("rust".to_string()),
        )
    );
    assert_eq!(
        calls[2],
        (
            "SESSION_DELETE".to_string(),
            Some("transport-session-1".to_string()),
            Some("server-123".to_string()),
            None,
            Some("rust".to_string()),
        )
    );
}

#[tokio::test]
async fn affinity_core_preserves_owner_access_across_workers_and_denies_peer_reuse() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        eprintln!(
            "skipping cross-worker affinity test because Redis is unavailable at {redis_url}"
        );
        return;
    }

    let cache_prefix = format!("mcpgw:rust-affinity-itest:{}:", Uuid::new_v4());
    cleanup_redis_prefix(redis_url, &cache_prefix).await;

    let owner_worker_id = format!("worker-{}", Uuid::new_v4().simple());
    let session_id = format!("affinity-session-{}", Uuid::new_v4().simple());
    let backend_calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let backend_calls_clone = backend_calls.clone();
    let initialize_session_id = session_id.clone();
    let backend = Router::new()
        .route(
            "/_internal/mcp/authenticate",
            post(|Json(body): Json<Value>| async move {
                let auth_context = if body["headers"]["authorization"]
                    .as_str()
                    .is_some_and(|value| value.contains("peer-token"))
                {
                    json!({
                        "email": "peer@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": true,
                        "is_admin": false,
                        "permission_is_admin": false,
                        "token_use": "session"
                    })
                } else {
                    json!({
                        "email": "owner@example.com",
                        "teams": ["team-a"],
                        "is_authenticated": true,
                        "is_admin": false,
                        "permission_is_admin": false,
                        "token_use": "session"
                    })
                };
                Json(json!({"authContext": auth_context}))
            }),
        )
        .route(
            "/_internal/mcp/transport",
            post(move || {
                let initialize_session_id = initialize_session_id.clone();
                async move {
                    (
                        StatusCode::OK,
                        [("mcp-session-id", initialize_session_id)],
                        Json(json!({
                            "protocolVersion": "2025-11-25",
                            "capabilities": {}
                        })),
                    )
                }
            }),
        )
        .route(
            "/_internal/mcp/rpc",
            post(move || {
                let backend_calls = backend_calls_clone.clone();
                async move {
                    backend_calls
                        .lock()
                        .expect("lock")
                        .push("tools-list".to_string());
                    Json(json!({
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"tools": [{"name": "fast-time-get-system-time"}]},
                    }))
                }
            }),
        )
        .route(
            "/_internal/mcp/tools/list",
            post({
                let backend_calls = backend_calls.clone();
                move || {
                    let backend_calls = backend_calls.clone();
                    async move {
                        backend_calls
                            .lock()
                            .expect("lock")
                            .push("tools-list".to_string());
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": 2,
                            "result": {"tools": [{"name": "fast-time-get-system-time"}]},
                        }))
                    }
                }
            }),
        )
        .fallback({
            let backend_calls = backend_calls.clone();
            any(move |uri: Uri| {
                let backend_calls = backend_calls.clone();
                async move {
                    backend_calls
                        .lock()
                        .expect("lock")
                        .push(format!("unexpected:{}", uri.path()));
                    (StatusCode::NOT_FOUND, uri.path().to_string())
                }
            })
        });
    let backend_url = spawn_router(backend).await;

    let runtime_1 = {
        let mut config = test_runtime_config();
        config.backend_rpc_url = format!("{backend_url}/_internal/mcp/rpc");
        config.public_listen_http = Some("127.0.0.1:8788".to_string());
        config.session_core_enabled = true;
        config.affinity_core_enabled = true;
        config.session_auth_reuse_enabled = true;
        config.redis_url = Some(redis_url.to_string());
        config.cache_prefix = cache_prefix.clone();
        build_router(AppState::new(&config).expect("state 1"))
    };
    let runtime_2 = {
        let mut config = test_runtime_config();
        config.backend_rpc_url = format!("{backend_url}/_internal/mcp/rpc");
        config.public_listen_http = Some("127.0.0.1:8788".to_string());
        config.session_core_enabled = true;
        config.affinity_core_enabled = true;
        config.session_auth_reuse_enabled = true;
        config.redis_url = Some(redis_url.to_string());
        config.cache_prefix = cache_prefix.clone();
        build_router(AppState::new(&config).expect("state 2"))
    };
    let runtime_1_url = spawn_router(runtime_1).await;
    let runtime_2_url = spawn_router(runtime_2).await;

    let redis_client = redis::Client::open(redis_url).expect("redis client");
    let mut redis = redis_client
        .get_multiplexed_async_connection()
        .await
        .expect("redis connection");
    redis
        .set_ex::<_, _, ()>(
            format!("{cache_prefix}pool_owner:{session_id}"),
            owner_worker_id.clone(),
            300,
        )
        .await
        .expect("set owner");

    let responder = {
        let redis_client = redis_client.clone();
        let runtime_2_url = runtime_2_url.clone();
        let owner_worker_id = owner_worker_id.clone();
        let cache_prefix = cache_prefix.clone();
        tokio::spawn(async move {
            let mut pubsub = redis_client.get_async_pubsub().await.expect("pubsub");
            pubsub
                .subscribe(format!("{cache_prefix}pool_http:{owner_worker_id}"))
                .await
                .expect("subscribe");
            let mut stream = pubsub.on_message();
            if let Some(message) = stream.next().await {
                let payload_json: String = message.get_payload().expect("payload");
                let payload: Value = serde_json::from_str(&payload_json).expect("payload json");
                let method = payload["method"].as_str().expect("method");
                let path = payload["path"].as_str().expect("path");
                let query = payload["query_string"].as_str().unwrap_or_default();
                let response_channel = payload["response_channel"]
                    .as_str()
                    .expect("response channel")
                    .to_string();

                let mut request_builder = reqwest::Client::new()
                    .request(
                        reqwest::Method::from_bytes(method.as_bytes()).expect("request method"),
                        if query.is_empty() {
                            format!("{runtime_2_url}{path}")
                        } else {
                            format!("{runtime_2_url}{path}?{query}")
                        },
                    )
                    .header("x-contextforge-affinity-forwarded", "rust");

                for (name, value) in payload["headers"].as_object().expect("headers map") {
                    request_builder =
                        request_builder.header(name, value.as_str().expect("header value"));
                }

                let body_hex = payload["body"].as_str().unwrap_or_default();
                if !body_hex.is_empty() {
                    request_builder = request_builder.body(hex_decode(body_hex));
                }

                let response = request_builder.send().await.expect("forwarded response");
                let status = response.status().as_u16();
                let headers = response
                    .headers()
                    .iter()
                    .filter_map(|(name, value)| {
                        value
                            .to_str()
                            .ok()
                            .map(|value_str| (name.as_str().to_string(), value_str.to_string()))
                    })
                    .collect::<std::collections::HashMap<String, String>>();
                let body = response.bytes().await.expect("response body");
                let response = serde_json::to_string(&json!({
                    "status": status,
                    "headers": headers,
                    "body": hex_encode(&body),
                }))
                .expect("response payload");
                let mut publish_conn = redis_client
                    .get_multiplexed_async_connection()
                    .await
                    .expect("publish connection");
                redis::cmd("PUBLISH")
                    .arg(response_channel)
                    .arg(response)
                    .query_async::<i64>(&mut publish_conn)
                    .await
                    .expect("publish response");
            }
        })
    };

    let client = reqwest::Client::new();
    let initialize = client
        .post(format!("{runtime_1_url}/mcp"))
        .header("authorization", "Bearer owner-token")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    assert_eq!(initialize.status(), StatusCode::OK);

    let owner_response = client
        .post(format!("{runtime_1_url}/mcp"))
        .header("authorization", "Bearer owner-token")
        .header("mcp-protocol-version", "2025-11-25")
        .header("mcp-session-id", session_id.clone())
        .json(&json!({
            "jsonrpc":"2.0",
            "id":2,
            "method":"tools/list",
            "params":{}
        }))
        .send()
        .await
        .expect("owner response");
    let owner_status = owner_response.status();
    let owner_text = owner_response.text().await.expect("owner body");
    assert!(
        owner_status == StatusCode::OK,
        "owner status={owner_status} body={owner_text}"
    );
    let owner_body: Value = serde_json::from_str(&owner_text).expect("owner json");
    assert_eq!(
        owner_body["result"]["tools"][0]["name"],
        json!("fast-time-get-system-time")
    );
    responder.await.expect("responder");

    let peer_response = client
        .post(format!("{runtime_1_url}/mcp"))
        .header("authorization", "Bearer peer-token")
        .header("mcp-protocol-version", "2025-11-25")
        .header("mcp-session-id", session_id.clone())
        .json(&json!({
            "jsonrpc":"2.0",
            "id":3,
            "method":"tools/list",
            "params":{}
        }))
        .send()
        .await
        .expect("peer response");
    assert_eq!(peer_response.status(), StatusCode::FORBIDDEN);

    let health_response = client
        .get(format!("{runtime_1_url}/health"))
        .send()
        .await
        .expect("health response");
    let health_body: Value = health_response.json().await.expect("health json");
    assert_eq!(
        health_body["runtime_stats"]["affinity"]["forward_attempts"],
        json!(1)
    );
    assert_eq!(
        health_body["runtime_stats"]["affinity"]["forwarded_requests"],
        json!(1)
    );
    assert_eq!(
        health_body["runtime_stats"]["session_access_denials"]["auth_binding_mismatches"],
        json!(1)
    );

    {
        let calls = backend_calls.lock().expect("lock");
        assert_eq!(calls.as_slice(), &["tools-list".to_string()]);
    }
    cleanup_redis_prefix(redis_url, &cache_prefix).await;
}

#[tokio::test]
async fn session_core_rejects_missing_session_before_backend_dispatch() {
    let backend_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let backend_calls = backend_calls.clone();
        Router::new().fallback(any(move || {
            let backend_calls = backend_calls.clone();
            async move {
                *backend_calls.lock().expect("lock") += 1;
                (StatusCode::OK, Json(json!({"unexpected": true})))
            }
        }))
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "user@example.com",
            "teams": ["team-a"],
            "is_admin": false,
            "is_authenticated": true,
        }))
        .expect("auth context json"),
    );

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context)
        .header("mcp-session-id", "missing-session")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("missing session response");

    assert_eq!(response.status(), StatusCode::NOT_FOUND);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["detail"], json!("Session not found"));
    assert_eq!(*backend_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn session_core_transport_denies_non_owner_before_backend_dispatch() {
    let transport_calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push(format!(
                        "POST:{}",
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .unwrap_or("missing")
                    ));
                    let mut response_headers = HeaderMap::new();
                    response_headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("owned-session-1"),
                    );
                    (
                        StatusCode::OK,
                        response_headers,
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": body["id"],
                            "result": {"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"ContextForge","version":"0.1.0"}}
                        })),
                    )
                }
            })
            .get(move || {
                let transport_calls = get_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push("GET".to_string());
                    (
                        StatusCode::OK,
                        [("content-type", HeaderValue::from_static("text/event-stream"))],
                        "data: ping\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let owner_auth = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "owner@example.com",
            "teams": ["team-a"],
            "is_admin": false,
            "is_authenticated": true,
        }))
        .expect("owner auth context json"),
    );
    let intruder_auth = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "intruder@example.com",
            "teams": ["team-a"],
            "is_admin": false,
            "is_authenticated": true,
        }))
        .expect("intruder auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", owner_auth)
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    let initialize_status = initialize_response.status();
    let initialize_body = initialize_response.text().await.expect("initialize body");
    assert!(
        initialize_status == StatusCode::OK,
        "initialize status={initialize_status} body={initialize_body}"
    );

    let get_response = client
        .get(format!("{runtime_url}/mcp?session_id=owned-session-1"))
        .header("x-contextforge-auth-context", intruder_auth)
        .send()
        .await
        .expect("get response");

    assert_eq!(get_response.status(), StatusCode::FORBIDDEN);
    let body: Value = get_response.json().await.expect("json body");
    assert_eq!(body["detail"], json!("Session access denied"));
    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert!(calls[0].starts_with("POST:"));
}

#[tokio::test]
async fn session_core_transport_denies_same_email_with_different_auth_binding() {
    let transport_calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push(format!(
                        "POST:{}",
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .unwrap_or("missing")
                    ));
                    let mut response_headers = HeaderMap::new();
                    response_headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("bound-session-1"),
                    );
                    (
                        StatusCode::OK,
                        response_headers,
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": body["id"],
                            "result": {"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"ContextForge","version":"0.1.0"}}
                        })),
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            session_auth_reuse_enabled: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let owner_auth = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "owner@example.com",
            "teams": ["team-a"],
            "is_admin": false,
            "is_authenticated": true,
        }))
        .expect("owner auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer owner-session-token")
        .header("x-contextforge-auth-context", owner_auth.clone())
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    let initialize_status = initialize_response.status();
    let initialize_body = initialize_response.text().await.expect("initialize body");
    assert!(
        initialize_status == StatusCode::OK,
        "initialize status={initialize_status} body={initialize_body}"
    );

    let get_response = client
        .get(format!("{runtime_url}/mcp?session_id=bound-session-1"))
        .header("authorization", "Bearer owner-public-only-token")
        .header("x-contextforge-auth-context", owner_auth)
        .send()
        .await
        .expect("get response");

    assert_eq!(get_response.status(), StatusCode::FORBIDDEN);
    let body: Value = get_response.json().await.expect("json body");
    assert_eq!(body["detail"], json!("Session access denied"));
    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert!(calls[0].starts_with("POST:"));
}

#[tokio::test]
async fn session_core_redis_shares_sessions_across_runtime_instances() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        return;
    }

    let cache_prefix = format!("mcpgw:rust-session-itest:{}:", Uuid::new_v4());
    cleanup_redis_prefix(redis_url, &cache_prefix).await;

    let transport_calls = Arc::new(Mutex::new(Vec::<(
        String,
        Option<String>,
        Option<String>,
        Option<String>,
    )>::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push((
                        "POST".to_string(),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("x-contextforge-server-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        None,
                    ));
                    let mut response_headers = HeaderMap::new();
                    response_headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("redis-session-1"),
                    );
                    (
                        StatusCode::OK,
                        response_headers,
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": body["id"],
                            "result": {"protocolVersion":"2025-11-25","capabilities":{},"serverInfo":{"name":"ContextForge","version":"0.1.0"}}
                        })),
                    )
                }
            })
            .get(move |headers: HeaderMap, uri: Uri| {
                let transport_calls = get_calls.clone();
                async move {
                    transport_calls.lock().expect("lock").push((
                        "GET".to_string(),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("x-contextforge-server-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        uri.query().map(str::to_string),
                    ));
                    (
                        StatusCode::OK,
                        [("content-type", HeaderValue::from_static("text/event-stream"))],
                        "data: ok\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime_1 = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            redis_url: Some(redis_url.to_string()),
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state 1"),
    );
    let runtime_2 = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            redis_url: Some(redis_url.to_string()),
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state 2"),
    );
    let runtime_1_url = spawn_router(runtime_1).await;
    let runtime_2_url = spawn_router(runtime_2).await;

    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "user@example.com",
            "teams": ["team-a"],
            "is_admin": false
        }))
        .expect("auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_1_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context.clone())
        .header("x-contextforge-server-id", "server-redis")
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    let initialize_status = initialize_response.status();
    let initialize_headers = initialize_response.headers().clone();
    let initialize_body = initialize_response.text().await.expect("initialize body");
    assert!(
        initialize_status == StatusCode::OK,
        "initialize status={initialize_status} body={initialize_body}"
    );
    assert_eq!(
        initialize_headers
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("redis-session-1")
    );

    let get_response = client
        .get(format!("{runtime_2_url}/mcp?session_id=redis-session-1"))
        .header("x-contextforge-auth-context", auth_context)
        .send()
        .await
        .expect("get response");
    assert_eq!(get_response.status(), StatusCode::OK);

    {
        let calls = transport_calls.lock().expect("lock");
        assert_eq!(calls[0].0, "POST");
        assert_eq!(calls[0].2.as_deref(), Some("server-redis"));
        assert_eq!(
            calls[1],
            (
                "GET".to_string(),
                Some("redis-session-1".to_string()),
                Some("server-redis".to_string()),
                Some("session_id=redis-session-1".to_string()),
            )
        );
    }

    cleanup_redis_prefix(redis_url, &cache_prefix).await;
}

#[tokio::test]
async fn affinity_core_forwards_session_post_to_owner_worker_channel() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        eprintln!("skipping affinity-core test because Redis is unavailable at {redis_url}");
        return;
    }

    let owner_worker_id = format!("worker-{}", Uuid::new_v4().simple());
    let session_id = format!("affinity-session-{}", Uuid::new_v4().simple());
    cleanup_redis_prefix(redis_url, &format!("mcpgw:pool_owner:{session_id}")).await;

    let backend_calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let backend_calls_clone = backend_calls.clone();
    let initialize_session_id = session_id.clone();
    let backend = Router::new()
        .route(
            "/_internal/mcp/transport",
            post(move || {
                let backend_calls = backend_calls_clone.clone();
                let initialize_session_id = initialize_session_id.clone();
                async move {
                    backend_calls
                        .lock()
                        .expect("lock")
                        .push("initialize".to_string());
                    (
                        StatusCode::OK,
                        [("mcp-session-id", initialize_session_id)],
                        Json(json!({
                            "protocolVersion": "2025-11-25",
                            "capabilities": {}
                        })),
                    )
                }
            }),
        )
        .fallback({
            let backend_calls = backend_calls.clone();
            any(move || {
                let backend_calls = backend_calls.clone();
                async move {
                    backend_calls
                        .lock()
                        .expect("lock")
                        .push("unexpected".to_string());
                    StatusCode::INTERNAL_SERVER_ERROR
                }
            })
        });
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            affinity_core_enabled: true,
            redis_url: Some(redis_url.to_string()),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let redis_client = redis::Client::open(redis_url).expect("redis client");
    let mut redis = redis_client
        .get_multiplexed_async_connection()
        .await
        .expect("redis connection");
    redis
        .set_ex::<_, _, ()>(
            format!("mcpgw:pool_owner:{session_id}"),
            owner_worker_id.clone(),
            300,
        )
        .await
        .expect("set owner");

    let responder = {
        let redis_client = redis_client.clone();
        let session_id = session_id.clone();
        let owner_worker_id = owner_worker_id.clone();
        tokio::spawn(async move {
            let mut pubsub = redis_client.get_async_pubsub().await.expect("pubsub");
            pubsub
                .subscribe(format!("mcpgw:pool_http:{owner_worker_id}"))
                .await
                .expect("subscribe");
            let mut stream = pubsub.on_message();
            let message = tokio::time::timeout(Duration::from_secs(5), stream.next())
                .await
                .expect("timeout waiting for forwarded request")
                .expect("forwarded request");
            let payload_json: String = message.get_payload().expect("payload");
            let payload: Value = serde_json::from_str(&payload_json).expect("payload json");
            assert_eq!(payload["mcp_session_id"], session_id);
            assert_eq!(payload["method"], "POST");
            assert_eq!(payload["path"], "/mcp");
            assert_eq!(payload["query_string"], "");

            let response_body = serde_json::to_vec(&json!({
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"forwarded": true}
            }))
            .expect("response json");
            let mut response_hex = String::with_capacity(response_body.len() * 2);
            for byte in &response_body {
                use std::fmt::Write as _;
                let _ = write!(&mut response_hex, "{byte:02x}");
            }
            let response = serde_json::to_string(&json!({
                "status": 200,
                "headers": {
                    "content-type": "application/json",
                    "mcp-session-id": session_id,
                },
                "body": response_hex,
            }))
            .expect("response payload");
            let response_channel = payload["response_channel"]
                .as_str()
                .expect("response channel")
                .to_string();
            let mut publish_conn = redis_client
                .get_multiplexed_async_connection()
                .await
                .expect("publish connection");
            redis::cmd("PUBLISH")
                .arg(response_channel)
                .arg(response)
                .query_async::<i64>(&mut publish_conn)
                .await
                .expect("publish response");
        })
    };

    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "user@example.com",
            "teams": ["team-a"],
            "is_admin": false
        }))
        .expect("auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context.clone())
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    let initialize_status = initialize_response.status();
    let initialize_body = initialize_response.text().await.expect("initialize body");
    assert!(
        initialize_status == StatusCode::OK,
        "initialize status={initialize_status} body={initialize_body}"
    );

    let response = client
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context)
        .header("mcp-protocol-version", "2025-11-25")
        .header("mcp-session-id", session_id.clone())
        .json(&json!({
            "jsonrpc":"2.0",
            "id":2,
            "method":"tools/list",
            "params":{}
        }))
        .send()
        .await
        .expect("post response");
    let response_headers = response.headers().clone();
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["forwarded"], json!(true));
    assert_eq!(
        response_headers
            .get("x-contextforge-mcp-affinity-core")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );

    responder.await.expect("responder");
    {
        let calls = backend_calls.lock().expect("lock");
        assert_eq!(calls.as_slice(), &["initialize".to_string()]);
    }
    cleanup_redis_prefix(redis_url, &format!("mcpgw:pool_owner:{session_id}")).await;
}

#[tokio::test]
async fn rust_event_store_replays_events_across_runtime_instances() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        return;
    }

    let cache_prefix = format!("mcpgw:rust-eventstore-itest:{}:", Uuid::new_v4());
    cleanup_redis_prefix(redis_url, &cache_prefix).await;

    let runtime_1 = build_router(
        AppState::new(&RuntimeConfig {
            redis_url: Some(redis_url.to_string()),
            event_store_enabled: true,
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state 1"),
    );
    let runtime_2 = build_router(
        AppState::new(&RuntimeConfig {
            redis_url: Some(redis_url.to_string()),
            event_store_enabled: true,
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state 2"),
    );
    let runtime_1_url = spawn_router(runtime_1).await;
    let runtime_2_url = spawn_router(runtime_2).await;
    let client = reqwest::Client::new();

    let first = client
        .post(format!("{runtime_1_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "stream-1",
            "message": {"id": 1},
        }))
        .send()
        .await
        .expect("store first");
    let first_body: Value = first.json().await.expect("first json");
    let first_event_id = first_body["eventId"]
        .as_str()
        .expect("first event id")
        .to_string();

    let second = client
        .post(format!("{runtime_1_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "stream-1",
            "message": {"id": 2},
        }))
        .send()
        .await
        .expect("store second");
    assert_eq!(second.status(), StatusCode::OK);

    let replay = client
        .post(format!("{runtime_2_url}/_internal/event-store/replay"))
        .json(&json!({
            "lastEventId": first_event_id,
        }))
        .send()
        .await
        .expect("replay response");
    assert_eq!(replay.status(), StatusCode::OK);
    assert_eq!(
        replay
            .headers()
            .get("x-contextforge-mcp-event-store")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    let replay_body: Value = replay.json().await.expect("replay json");
    assert_eq!(replay_body["streamId"], "stream-1");
    assert_eq!(replay_body["events"][0]["message"], json!({"id": 2}));

    cleanup_redis_prefix(redis_url, &cache_prefix).await;
}

#[tokio::test]
async fn rust_event_store_replay_fails_closed_on_corrupt_messages() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        return;
    }

    let cache_prefix = format!("mcpgw:rust-eventstore-corrupt-itest:{}:", Uuid::new_v4());
    cleanup_redis_prefix(redis_url, &cache_prefix).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            redis_url: Some(redis_url.to_string()),
            event_store_enabled: true,
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let first = client
        .post(format!("{runtime_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "stream-1",
            "message": {"id": 1},
        }))
        .send()
        .await
        .expect("store first");
    let first_body: Value = first.json().await.expect("first json");
    let first_event_id = first_body["eventId"]
        .as_str()
        .expect("first event id")
        .to_string();

    let second = client
        .post(format!("{runtime_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "stream-1",
            "message": {"id": 2},
        }))
        .send()
        .await
        .expect("store second");
    let second_body: Value = second.json().await.expect("second json");
    let second_event_id = second_body["eventId"]
        .as_str()
        .expect("second event id")
        .to_string();

    let redis_client = redis::Client::open(redis_url).expect("redis client");
    let mut redis = redis_client
        .get_multiplexed_async_connection()
        .await
        .expect("redis connection");
    redis
        .hset::<_, _, _, ()>(
            format!("{cache_prefix}eventstore:stream-1:messages"),
            second_event_id,
            "{not-json",
        )
        .await
        .expect("corrupt stored payload");

    let replay = client
        .post(format!("{runtime_url}/_internal/event-store/replay"))
        .json(&json!({
            "lastEventId": first_event_id,
        }))
        .send()
        .await
        .expect("replay response");
    assert_eq!(replay.status(), StatusCode::BAD_GATEWAY);
    let replay_body: Value = replay.json().await.expect("replay json");
    assert_eq!(
        replay_body,
        json!({"detail": "Rust event store replay decode failed"})
    );

    cleanup_redis_prefix(redis_url, &cache_prefix).await;
}

#[tokio::test]
async fn resume_core_replays_public_get_from_rust_event_store() {
    let redis_url = "redis://127.0.0.1:6379/0";
    if !redis_is_available(redis_url).await {
        return;
    }

    let cache_prefix = format!("mcpgw:rust-resume-itest:{}:", Uuid::new_v4());
    cleanup_redis_prefix(redis_url, &cache_prefix).await;

    let transport_calls: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let backend = {
        let post_transport_calls = transport_calls.clone();
        let get_transport_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move |headers: HeaderMap, Json(_body): Json<Value>| {
                let transport_calls = post_transport_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("POST".to_string());
                    let mut response = Json(json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "ContextForge", "version": "0.1.0"}
                        }
                    }))
                    .into_response();
                    response.headers_mut().insert(
                        "mcp-session-id",
                        headers
                            .get("mcp-session-id")
                            .cloned()
                            .unwrap_or_else(|| HeaderValue::from_static("resume-session-1")),
                    );
                    response
                }
            })
            .get(move || {
                let transport_calls = get_transport_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("GET".to_string());
                    (
                        StatusCode::OK,
                        [("content-type", "text/event-stream")],
                        "data: backend-fallback\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            event_store_enabled: true,
            resume_core_enabled: true,
            redis_url: Some(redis_url.to_string()),
            cache_prefix: cache_prefix.clone(),
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;

    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "resume@example.com",
            "teams": ["team-a"],
            "is_admin": false
        }))
        .expect("auth context json"),
    );
    let client = reqwest::Client::new();

    let initialize_response = client
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context.clone())
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"initialize",
            "params":{"protocolVersion":"2025-11-25","capabilities":{}}
        }))
        .send()
        .await
        .expect("initialize response");
    assert_eq!(initialize_response.status(), StatusCode::OK);
    let session_id = initialize_response
        .headers()
        .get("mcp-session-id")
        .and_then(|value| value.to_str().ok())
        .expect("session id")
        .to_string();

    let store_1 = client
        .post(format!("{runtime_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "resume-stream-1",
            "message": {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info","data":"first"}},
            "keyPrefix": "eventstore"
        }))
        .send()
        .await
        .expect("store event 1");
    assert_eq!(store_1.status(), StatusCode::OK);
    let first_event_id = store_1.json::<Value>().await.expect("store 1 json")["eventId"]
        .as_str()
        .expect("event id")
        .to_string();

    let store_2 = client
        .post(format!("{runtime_url}/_internal/event-store/store"))
        .json(&json!({
            "streamId": "resume-stream-1",
            "message": {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info","data":"second"}},
            "keyPrefix": "eventstore"
        }))
        .send()
        .await
        .expect("store event 2");
    assert_eq!(store_2.status(), StatusCode::OK);
    let second_event_id = store_2.json::<Value>().await.expect("store 2 json")["eventId"]
        .as_str()
        .expect("event id")
        .to_string();

    let mut resume_response = client
        .get(format!("{runtime_url}/mcp?session_id={session_id}"))
        .header("x-contextforge-auth-context", auth_context)
        .header("accept", "text/event-stream")
        .header("mcp-protocol-version", "2025-11-25")
        .header("last-event-id", first_event_id)
        .send()
        .await
        .expect("resume response");
    assert_eq!(resume_response.status(), StatusCode::OK);
    assert_eq!(
        resume_response
            .headers()
            .get("x-contextforge-mcp-resume-core")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );

    let replay_chunk = tokio::time::timeout(std::time::Duration::from_secs(2), async {
        let mut collected = Vec::new();
        loop {
            let Some(chunk) = resume_response.chunk().await.expect("resume chunk") else {
                break;
            };
            collected.extend_from_slice(&chunk);
            if collected
                .windows(second_event_id.len())
                .any(|window| window == second_event_id.as_bytes())
            {
                break;
            }
        }
        collected
    })
    .await
    .expect("resume timeout");
    let replay_text = String::from_utf8_lossy(&replay_chunk);
    assert!(replay_text.contains("event: message"));
    assert!(replay_text.contains(&format!("id: {second_event_id}")));
    assert!(replay_text.contains("\"data\":\"second\""));

    {
        let calls = transport_calls.lock().expect("lock");
        assert_eq!(calls.as_slice(), &["POST".to_string()]);
    }

    cleanup_redis_prefix(redis_url, &cache_prefix).await;
}

#[tokio::test]
async fn resume_core_disabled_falls_back_to_python_transport_get() {
    let transport_calls: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move || {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("POST".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "application/json"),
                            ("mcp-session-id", "fallback-session-1"),
                        ],
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {"protocolVersion": "2025-11-25", "capabilities": {}}
                        })),
                    )
                }
            })
            .get(move || {
                let transport_calls = get_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("GET".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "text/event-stream"),
                            ("mcp-session-id", "fallback-session-1"),
                        ],
                        "data: backend-fallback\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            event_store_enabled: true,
            resume_core_enabled: false,
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    initialize_runtime_session(&runtime_url, "fallback-session-1", None).await;

    let response = client
        .get(format!("{runtime_url}/mcp?session_id=fallback-session-1"))
        .header("accept", "text/event-stream")
        .header("last-event-id", "event-123")
        .send()
        .await
        .expect("get response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-resume-core")
            .and_then(|value| value.to_str().ok()),
        Some("python")
    );
    assert_eq!(
        response.text().await.expect("body"),
        "data: backend-fallback\n\n"
    );

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.as_slice(), &["POST".to_string(), "GET".to_string()]);
}

#[tokio::test]
async fn live_stream_core_restreams_public_get_from_rust_edge() {
    let transport_calls: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move || {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("POST".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "application/json"),
                            ("mcp-session-id", "live-session-1"),
                        ],
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {"protocolVersion": "2025-11-25", "capabilities": {}}
                        })),
                    )
                }
            })
            .get(move || {
                let transport_calls = get_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("GET".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "text/event-stream"),
                            ("mcp-session-id", "live-session-1"),
                        ],
                        "id: evt-1\nevent: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{\"data\":\"hello-live\"}}\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            live_stream_core_enabled: true,
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;
    let auth_context = URL_SAFE_NO_PAD.encode(
        serde_json::to_vec(&json!({
            "email": "live@example.com",
            "teams": ["team-a"],
            "is_admin": false
        }))
        .expect("auth context json"),
    );

    initialize_runtime_session(&runtime_url, "live-session-1", Some(auth_context.as_str())).await;

    let response = reqwest::Client::new()
        .get(format!("{runtime_url}/mcp"))
        .header("x-contextforge-auth-context", auth_context)
        .header("accept", "text/event-stream")
        .header("mcp-session-id", "live-session-1")
        .header("mcp-protocol-version", "2025-03-26")
        .send()
        .await
        .expect("get response");

    assert_eq!(response.status(), StatusCode::OK);
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
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("live-session-1")
    );
    let body = response.text().await.expect("body");
    assert!(body.contains("id: evt-1"));
    assert!(body.contains("event: message"));
    assert!(body.contains("hello-live"));

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.as_slice(), &["POST".to_string(), "GET".to_string()]);
}

#[tokio::test]
async fn live_stream_core_returns_headers_without_waiting_for_backend_sse() {
    let transport_calls: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let backend = {
        let post_calls = transport_calls.clone();
        let get_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            post(move || {
                let transport_calls = post_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("POST".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "application/json"),
                            ("mcp-session-id", "live-session-delayed"),
                        ],
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {"protocolVersion": "2025-11-25", "capabilities": {}}
                        })),
                    )
                }
            })
            .get(move || {
                let transport_calls = get_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("GET".to_string());
                    tokio::time::sleep(Duration::from_millis(400)).await;
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "text/event-stream"),
                            ("mcp-session-id", "live-session-delayed"),
                        ],
                        "id: evt-delayed\nevent: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{\"data\":\"hello-delayed\"}}\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            live_stream_core_enabled: true,
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();
    let started = Instant::now();

    initialize_runtime_session(&runtime_url, "live-session-delayed", None).await;

    let response = client
        .get(format!("{runtime_url}/mcp"))
        .header("accept", "text/event-stream")
        .header("mcp-session-id", "live-session-delayed")
        .send()
        .await
        .expect("get response");

    assert!(
        started.elapsed() < Duration::from_millis(250),
        "live stream headers should be returned before the delayed backend handshake finishes"
    );
    assert_eq!(response.status(), StatusCode::OK);
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
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("live-session-delayed")
    );
    let body = response.text().await.expect("body");
    assert!(body.contains("id: evt-delayed"));
    assert!(body.contains("hello-delayed"));

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.as_slice(), &["POST".to_string(), "GET".to_string()]);
}

#[tokio::test]
async fn live_stream_core_disabled_falls_back_to_python_transport_get() {
    let transport_calls: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let backend = {
        let transport_calls = transport_calls.clone();
        Router::new().route(
            "/_internal/mcp/transport",
            get(move || {
                let transport_calls = transport_calls.clone();
                async move {
                    transport_calls
                        .lock()
                        .expect("lock")
                        .push("GET".to_string());
                    (
                        StatusCode::OK,
                        [
                            ("content-type", "text/event-stream"),
                            ("mcp-session-id", "fallback-live-session-1"),
                        ],
                        "data: backend-live-fallback\n\n",
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = build_router(
        AppState::new(&RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            session_core_enabled: true,
            live_stream_core_enabled: false,
            ..test_runtime_config()
        })
        .expect("state"),
    );
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let response = client
        .get(format!("{runtime_url}/mcp"))
        .header("accept", "text/event-stream")
        .send()
        .await
        .expect("get response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-live-stream-core")
            .and_then(|value| value.to_str().ok()),
        Some("python")
    );
    assert_eq!(
        response.text().await.expect("body"),
        "data: backend-live-fallback\n\n"
    );

    let calls = transport_calls.lock().expect("lock");
    assert_eq!(calls.as_slice(), &["GET".to_string()]);
}

#[tokio::test]
async fn tools_list_is_forwarded_with_auth_and_session_headers() {
    let observation = BackendObservation::default();
    let backend = {
        let observation = observation.clone();
        Router::new().route(
            "/rpc",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let observation = observation.clone();
                async move {
                    observation.calls.lock().expect("lock").push((
                        body.get("method")
                            .and_then(Value::as_str)
                            .unwrap_or("unknown")
                            .to_string(),
                        headers
                            .get("authorization")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                        headers
                            .get("mcp-session-id")
                            .and_then(|value| value.to_str().ok())
                            .map(str::to_string),
                    ));

                    let mut response_headers = HeaderMap::new();
                    response_headers
                        .insert("mcp-session-id", "abc123".parse().expect("session header"));

                    (
                        StatusCode::OK,
                        response_headers,
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": body["id"],
                            "result": {
                                "tools": [{"name": "echo"}]
                            }
                        })),
                    )
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/rpc"))
        .header("authorization", "Bearer test-token")
        .header("mcp-session-id", "session-1")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("tools/list response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("abc123")
    );
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["tools"][0]["name"], "echo");

    let calls = observation.calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].0, "tools/list");
    assert_eq!(calls[0].1.as_deref(), Some("Bearer test-token"));
    assert_eq!(calls[0].2.as_deref(), Some("session-1"));
}

#[tokio::test]
async fn server_scoped_tools_list_uses_specialized_internal_endpoint() {
    let observation = BackendObservation::default();
    let backend = {
        let observation = observation.clone();
        Router::new()
            .route(
                "/rpc",
                post(move |Json(body): Json<Value>| {
                    let observation = observation.clone();
                    async move {
                        observation.calls.lock().expect("lock").push((
                            body.get("method")
                                .and_then(Value::as_str)
                                .unwrap_or("unknown")
                                .to_string(),
                            None,
                            None,
                        ));
                        Json(json!({"jsonrpc":"2.0","id":body["id"],"result":{"unexpected":true}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/list",
                post(|headers: HeaderMap| async move {
                    assert_eq!(
                        headers
                            .get("x-contextforge-server-id")
                            .and_then(|value| value.to_str().ok()),
                        Some("server-1")
                    );
                    Json(json!({
                        "tools": [{
                            "name": "echo",
                            "description": "Echo input",
                            "inputSchema": {"type": "object"},
                            "annotations": {}
                        }]
                    }))
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("tools/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["tools"][0]["name"], "echo");

    let calls = observation.calls.lock().expect("lock");
    assert!(
        calls.is_empty(),
        "server-scoped tools/list should bypass generic /rpc forwarding"
    );
}

#[tokio::test]
async fn resources_list_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let resources_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let resources_calls = resources_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/resources/list",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let resources_calls = resources_calls.clone();
                    async move {
                        *resources_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "resources/list");
                        Json(json!({
                            "resources": [{
                                "uri": "resource://one",
                                "name": "Resource One"
                            }],
                            "nextCursor": "next-1"
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 12,
            "method": "resources/list",
            "params": {"cursor": "cursor-1"}
        }))
        .send()
        .await
        .expect("resources/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["resources"][0]["uri"], "resource://one");
    assert_eq!(body["result"]["nextCursor"], "next-1");
    assert_eq!(*resources_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn resources_read_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let resources_read_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let resources_read_calls = resources_read_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/resources/read",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let resources_read_calls = resources_read_calls.clone();
                    async move {
                        *resources_read_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "resources/read");
                        assert_eq!(body["params"]["uri"], "resource://one");
                        Json(json!({
                            "contents": [{
                                "uri": "resource://one",
                                "text": "hello"
                            }]
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 14,
            "method": "resources/read",
            "params": {"uri": "resource://one"}
        }))
        .send()
        .await
        .expect("resources/read response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["contents"][0]["uri"], "resource://one");
    assert_eq!(*resources_read_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn resources_subscribe_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let subscribe_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let subscribe_calls = subscribe_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/resources/subscribe",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let subscribe_calls = subscribe_calls.clone();
                    async move {
                        *subscribe_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "resources/subscribe");
                        assert_eq!(body["params"]["uri"], "resource://one");
                        Json(json!({}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/servers/server-1/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 17,
            "method": "resources/subscribe",
            "params": {"uri": "resource://one"}
        }))
        .send()
        .await
        .expect("resources/subscribe response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"], json!({}));
    assert_eq!(*subscribe_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn resources_unsubscribe_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let unsubscribe_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let unsubscribe_calls = unsubscribe_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/resources/unsubscribe",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let unsubscribe_calls = unsubscribe_calls.clone();
                    async move {
                        *unsubscribe_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "resources/unsubscribe");
                        assert_eq!(body["params"]["uri"], "resource://one");
                        Json(json!({}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 18,
            "method": "resources/unsubscribe",
            "params": {"uri": "resource://one"}
        }))
        .send()
        .await
        .expect("resources/unsubscribe response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"], json!({}));
    assert_eq!(*unsubscribe_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn resource_templates_list_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let templates_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let templates_calls = templates_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/resources/templates/list",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let templates_calls = templates_calls.clone();
                    async move {
                        *templates_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "resources/templates/list");
                        Json(json!({
                            "resourceTemplates": [{
                                "uriTemplate": "resource://{id}",
                                "name": "Resource Template"
                            }]
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 15,
            "method": "resources/templates/list",
            "params": {}
        }))
        .send()
        .await
        .expect("resources/templates/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(
        body["result"]["resourceTemplates"][0]["uriTemplate"],
        "resource://{id}"
    );
    assert_eq!(*templates_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn prompts_list_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let prompts_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let prompts_calls = prompts_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/prompts/list",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let prompts_calls = prompts_calls.clone();
                    async move {
                        *prompts_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "prompts/list");
                        Json(json!({
                            "prompts": [{
                                "name": "prompt-one",
                                "description": "Prompt One"
                            }],
                            "nextCursor": "next-prompt"
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 13,
            "method": "prompts/list",
            "params": {"cursor": "cursor-1"}
        }))
        .send()
        .await
        .expect("prompts/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["prompts"][0]["name"], "prompt-one");
    assert_eq!(body["result"]["nextCursor"], "next-prompt");
    assert_eq!(*prompts_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn prompts_get_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let prompts_get_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let prompts_get_calls = prompts_get_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let prompts_get_calls = prompts_get_calls.clone();
                    async move {
                        *prompts_get_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "prompts/get");
                        assert_eq!(body["params"]["name"], "prompt-one");
                        Json(json!({
                            "name": "prompt-one",
                            "messages": [{
                                "role": "user",
                                "content": "hello"
                            }]
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 16,
            "method": "prompts/get",
            "params": {"name": "prompt-one"}
        }))
        .send()
        .await
        .expect("prompts/get response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["name"], "prompt-one");
    assert_eq!(*prompts_get_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn prompts_get_rejects_non_string_argument_values_before_backend_dispatch() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let prompts_get_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let prompts_get_calls = prompts_get_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/prompts/get",
                post(move || {
                    let prompts_get_calls = prompts_get_calls.clone();
                    async move {
                        *prompts_get_calls.lock().expect("lock") += 1;
                        Json(json!({"unexpected": true}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 17,
            "method": "prompts/get",
            "params": {
                "name": "prompt-one",
                "arguments": {
                    "target_timezones": ["America/New_York", "Europe/Dublin"]
                }
            }
        }))
        .send()
        .await
        .expect("prompts/get response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["error"]["code"], -32602);
    assert_eq!(
        body["error"]["message"],
        "Prompt argument 'target_timezones' must be a string value"
    );
    assert_eq!(*prompts_get_calls.lock().expect("lock"), 0);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn roots_list_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let roots_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let roots_calls = roots_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/roots/list",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let roots_calls = roots_calls.clone();
                    async move {
                        *roots_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "roots/list");
                        Json(json!({
                            "roots": [{
                                "uri": "file:///tmp",
                                "name": "tmp"
                            }]
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 19,
            "method": "roots/list",
            "params": {}
        }))
        .send()
        .await
        .expect("roots/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["roots"][0]["uri"], "file:///tmp");
    assert_eq!(*roots_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn completion_complete_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let completion_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let completion_calls = completion_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/completion/complete",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let completion_calls = completion_calls.clone();
                    async move {
                        *completion_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "completion/complete");
                        Json(json!({
                            "completion": {
                                "values": [{"value": "done"}],
                                "hasMore": false
                            }
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 20,
            "method": "completion/complete",
            "params": {"prompt": "hi"}
        }))
        .send()
        .await
        .expect("completion/complete response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["completion"]["values"][0]["value"], "done");
    assert_eq!(*completion_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn sampling_create_message_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let sampling_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let sampling_calls = sampling_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/sampling/createMessage",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let sampling_calls = sampling_calls.clone();
                    async move {
                        *sampling_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "sampling/createMessage");
                        Json(json!({
                            "role": "assistant",
                            "content": {"type": "text", "text": "sampled"}
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 21,
            "method": "sampling/createMessage",
            "params": {"messages": []}
        }))
        .send()
        .await
        .expect("sampling/createMessage response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["content"]["text"], "sampled");
    assert_eq!(*sampling_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn logging_set_level_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let logging_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let logging_calls = logging_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/logging/setLevel",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let logging_calls = logging_calls.clone();
                    async move {
                        *logging_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "logging/setLevel");
                        Json(json!({}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 22,
            "method": "logging/setLevel",
            "params": {"level": "warning"}
        }))
        .send()
        .await
        .expect("logging/setLevel response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"], json!({}));
    assert_eq!(*logging_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn representative_specialized_endpoints_wrap_success_and_error_payloads_in_jsonrpc_envelopes()
{
    let backend = Router::new()
        .route(
            "/_internal/mcp/resources/list",
            post(|Json(body): Json<Value>| async move {
                let mut headers = HeaderMap::new();
                if body["id"] == json!(63) {
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("resources-specialized-session"),
                    );
                    (
                        StatusCode::OK,
                        headers,
                        Json(json!({"resources": [{"uri": "resource://one"}]})),
                    )
                        .into_response()
                } else {
                    headers.insert(
                        "www-authenticate",
                        HeaderValue::from_static("Bearer realm=\"contextforge\""),
                    );
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("resources-specialized-denied"),
                    );
                    (
                        StatusCode::FORBIDDEN,
                        headers,
                        Json(json!({"code": -32002, "message": "resources/list denied"})),
                    )
                        .into_response()
                }
            }),
        )
        .route(
            "/_internal/mcp/prompts/get",
            post(|Json(body): Json<Value>| async move {
                let mut headers = HeaderMap::new();
                if body["id"] == json!(65) {
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("prompts-specialized-session"),
                    );
                    (
                        StatusCode::OK,
                        headers,
                        Json(json!({
                            "name": "prompt-one",
                            "messages": [{"role": "user", "content": "hello"}]
                        })),
                    )
                        .into_response()
                } else {
                    headers.insert(
                        "www-authenticate",
                        HeaderValue::from_static("Bearer realm=\"contextforge\""),
                    );
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("prompts-specialized-denied"),
                    );
                    (
                        StatusCode::FORBIDDEN,
                        headers,
                        Json(json!({"code": -32003, "message": "prompts/get denied"})),
                    )
                        .into_response()
                }
            }),
        )
        .route(
            "/_internal/mcp/completion/complete",
            post(|Json(body): Json<Value>| async move {
                let mut headers = HeaderMap::new();
                if body["id"] == json!(67) {
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("completion-specialized-session"),
                    );
                    (
                        StatusCode::OK,
                        headers,
                        Json(json!({
                            "completion": {
                                "values": [{"value": "done"}],
                                "hasMore": false
                            }
                        })),
                    )
                        .into_response()
                } else {
                    headers.insert(
                        "www-authenticate",
                        HeaderValue::from_static("Bearer realm=\"contextforge\""),
                    );
                    headers.insert(
                        "mcp-session-id",
                        HeaderValue::from_static("completion-specialized-denied"),
                    );
                    (
                        StatusCode::FORBIDDEN,
                        headers,
                        Json(json!({"code": -32004, "message": "completion denied"})),
                    )
                        .into_response()
                }
            }),
        );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let mut config = test_runtime_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let resources_ok = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 63,
            "method": "resources/list",
            "params": {}
        }))
        .send()
        .await
        .expect("resources/list success response");
    assert_eq!(resources_ok.status(), StatusCode::OK);
    let resources_ok_body: Value = resources_ok
        .json()
        .await
        .expect("resources/list success json");
    assert_eq!(resources_ok_body["jsonrpc"], json!("2.0"));
    assert_eq!(resources_ok_body["id"], json!(63));
    assert_eq!(
        resources_ok_body["result"]["resources"][0]["uri"],
        json!("resource://one")
    );
    assert!(resources_ok_body["error"].is_null());

    let resources_err = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 64,
            "method": "resources/list",
            "params": {}
        }))
        .send()
        .await
        .expect("resources/list error response");
    assert_eq!(resources_err.status(), StatusCode::FORBIDDEN);
    let resources_err_body: Value = resources_err
        .json()
        .await
        .expect("resources/list error json");
    assert_eq!(resources_err_body["jsonrpc"], json!("2.0"));
    assert_eq!(resources_err_body["id"], json!(64));
    assert_eq!(resources_err_body["error"]["code"], json!(-32002));
    assert!(resources_err_body["result"].is_null());

    let prompts_ok = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 65,
            "method": "prompts/get",
            "params": {"name": "prompt-one"}
        }))
        .send()
        .await
        .expect("prompts/get success response");
    assert_eq!(prompts_ok.status(), StatusCode::OK);
    let prompts_ok_body: Value = prompts_ok.json().await.expect("prompts/get success json");
    assert_eq!(prompts_ok_body["jsonrpc"], json!("2.0"));
    assert_eq!(prompts_ok_body["id"], json!(65));
    assert_eq!(prompts_ok_body["result"]["name"], json!("prompt-one"));
    assert!(prompts_ok_body["error"].is_null());

    let prompts_err = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 66,
            "method": "prompts/get",
            "params": {"name": "prompt-one"}
        }))
        .send()
        .await
        .expect("prompts/get error response");
    assert_eq!(prompts_err.status(), StatusCode::FORBIDDEN);
    let prompts_err_body: Value = prompts_err.json().await.expect("prompts/get error json");
    assert_eq!(prompts_err_body["jsonrpc"], json!("2.0"));
    assert_eq!(prompts_err_body["id"], json!(66));
    assert_eq!(prompts_err_body["error"]["code"], json!(-32003));
    assert!(prompts_err_body["result"].is_null());

    let completion_ok = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 67,
            "method": "completion/complete",
            "params": {"prompt": "hi"}
        }))
        .send()
        .await
        .expect("completion/complete success response");
    assert_eq!(completion_ok.status(), StatusCode::OK);
    let completion_ok_body: Value = completion_ok
        .json()
        .await
        .expect("completion/complete success json");
    assert_eq!(completion_ok_body["jsonrpc"], json!("2.0"));
    assert_eq!(completion_ok_body["id"], json!(67));
    assert_eq!(
        completion_ok_body["result"]["completion"]["values"][0]["value"],
        json!("done")
    );
    assert!(completion_ok_body["error"].is_null());

    let completion_err = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 68,
            "method": "completion/complete",
            "params": {"prompt": "hi"}
        }))
        .send()
        .await
        .expect("completion/complete error response");
    assert_eq!(completion_err.status(), StatusCode::FORBIDDEN);
    assert_eq!(
        completion_err
            .headers()
            .get("www-authenticate")
            .and_then(|value| value.to_str().ok()),
        Some("Bearer realm=\"contextforge\"")
    );
    assert_eq!(
        completion_err
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("completion-specialized-denied")
    );
    let completion_err_body: Value = completion_err
        .json()
        .await
        .expect("completion/complete error json");
    assert_eq!(completion_err_body["jsonrpc"], json!("2.0"));
    assert_eq!(completion_err_body["id"], json!(68));
    assert_eq!(completion_err_body["error"]["code"], json!(-32004));
    assert!(completion_err_body["result"].is_null());
}

#[tokio::test]
async fn unknown_notification_catchall_stays_local() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        Router::new().route(
            "/rpc",
            post(move || {
                let rpc_calls = rpc_calls.clone();
                async move {
                    *rpc_calls.lock().expect("lock") += 1;
                    Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "method": "notifications/unknown",
            "params": {}
        }))
        .send()
        .await
        .expect("notifications/unknown response");

    assert_eq!(response.status(), StatusCode::ACCEPTED);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn unsupported_prefix_methods_stay_local() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        Router::new().route(
            "/rpc",
            post(move || {
                let rpc_calls = rpc_calls.clone();
                async move {
                    *rpc_calls.lock().expect("lock") += 1;
                    Json(json!({"jsonrpc":"2.0","id":"unexpected-rpc-path","result":{}}))
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    for (id, method) in [
        (23, "sampling/unknown"),
        (24, "completion/unknown"),
        (25, "logging/other"),
        (26, "elicitation/other"),
    ] {
        let response = client
            .post(format!("{runtime_url}/mcp"))
            .header("authorization", "Bearer test-token")
            .json(&json!({
                "jsonrpc": "2.0",
                "id": id,
                "method": method,
                "params": {}
            }))
            .send()
            .await
            .expect("catchall response");

        assert_eq!(response.status(), StatusCode::OK, "method={method}");
        let body: Value = response.json().await.expect("json body");
        assert_eq!(body["result"], json!({}), "method={method}");
    }

    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn elicitation_create_forwards_to_backend_rpc_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(Vec::<Value>::new()));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        Router::new().route(
            "/rpc",
            post(move |Json(body): Json<Value>| {
                let rpc_calls = rpc_calls.clone();
                async move {
                    rpc_calls.lock().expect("lock").push(body.clone());
                    Json(json!({
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"decision": "forwarded"}
                    }))
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let mut config = test_runtime_config();
        config.backend_rpc_url = format!("{backend_url}/rpc");
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let request_body = json!({
        "jsonrpc": "2.0",
        "id": 67,
        "method": "elicitation/create",
        "params": {
            "prompt": "Need approval",
            "schema": {"type": "object", "properties": {"approved": {"type": "boolean"}}}
        }
    });
    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&request_body)
        .send()
        .await
        .expect("elicitation/create response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["decision"], json!("forwarded"));

    let calls = rpc_calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0], request_body);
}

#[tokio::test]
async fn server_scoped_tools_list_db_mode_falls_back_to_python_data_endpoint_on_db_failure() {
    let authz_calls = Arc::new(Mutex::new(0usize));
    let list_calls = Arc::new(Mutex::new(0usize));
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let authz_calls = authz_calls.clone();
        let list_calls = list_calls.clone();
        let rpc_calls = rpc_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":1,"result":{"unexpected":true}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/list/authz",
                post(move |headers: HeaderMap| {
                    let authz_calls = authz_calls.clone();
                    async move {
                        *authz_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        StatusCode::NO_CONTENT
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/list",
                post(move || {
                    let list_calls = list_calls.clone();
                    async move {
                        *list_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "tools": [{
                                "name": "echo",
                                "description": "Echo input",
                                "inputSchema": {"type": "object"},
                                "annotations": {}
                            }]
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: Some("postgresql://postgres:postgres@127.0.0.1:1/mcp".to_string()),
            db_pool_max_size: 2,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .header(
            "x-contextforge-auth-context",
            URL_SAFE_NO_PAD.encode(r#"{"email":"user@example.com","teams":["team-1"],"is_authenticated":true,"is_admin":false,"permission_is_admin":false}"#),
        )
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("tools/list response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["tools"][0]["name"], "echo");
    assert_eq!(*authz_calls.lock().expect("lock"), 1);
    assert_eq!(*list_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn tools_call_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let tools_call_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let tools_call_calls = tools_call_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","id":1,"result":{"unexpected":true}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let tools_call_calls = tools_call_calls.clone();
                    async move {
                        *tools_call_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": body["id"],
                            "result": {
                                "content": [{"type": "text", "text": "ok"}],
                                "isError": false
                            }
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"text": "hello"}
            }
        }))
        .send()
        .await
        .expect("tools/call response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["content"][0]["text"], "ok");
    assert_eq!(*tools_call_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn tools_call_surfaces_backend_jsonrpc_errors_from_resolve() {
    let backend_fallback_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let backend_fallback_calls = backend_fallback_calls.clone();
        Router::new()
            .route(
                "/_internal/mcp/tools/call/resolve",
                post(move |Json(body): Json<Value>| async move {
                    (
                        StatusCode::NOT_FOUND,
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": body["id"],
                            "error": {
                                "code": -32601,
                                "message": "Tool not found: nonexistent-tool-xyz"
                            }
                        })),
                    )
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move || {
                    let backend_fallback_calls = backend_fallback_calls.clone();
                    async move {
                        *backend_fallback_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": 99,
                            "result": {"unexpected": true}
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "nonexistent-tool-xyz",
                "arguments": {}
            }
        }))
        .send()
        .await
        .expect("tools/call response");

    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["error"]["code"], -32601);
    assert_eq!(
        body["error"]["message"],
        "Tool not found: nonexistent-tool-xyz"
    );
    assert_eq!(*backend_fallback_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn tools_call_uses_rust_direct_execution_and_reuses_upstream_session() {
    let upstream_initialize_calls = Arc::new(Mutex::new(0usize));
    let upstream_tool_calls = Arc::new(Mutex::new(0usize));
    let backend_fallback_calls = Arc::new(Mutex::new(0usize));
    let backend_resolve_calls = Arc::new(Mutex::new(0usize));
    let backend_metric_calls = Arc::new(Mutex::new(Vec::<Value>::new()));

    let upstream = {
        let upstream_initialize_calls = upstream_initialize_calls.clone();
        let upstream_tool_calls = upstream_tool_calls.clone();
        Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let upstream_initialize_calls = upstream_initialize_calls.clone();
                let upstream_tool_calls = upstream_tool_calls.clone();
                async move {
                    match body.get("method").and_then(Value::as_str) {
                        Some("initialize") => {
                            *upstream_initialize_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("x-upstream-auth")
                                    .and_then(|value| value.to_str().ok()),
                                Some("rust-plan")
                            );
                            let mut response_headers = HeaderMap::new();
                            response_headers.insert(
                                "mcp-session-id",
                                HeaderValue::from_static("upstream-session-1"),
                            );
                            (
                                StatusCode::OK,
                                response_headers,
                                Json(json!({
                                    "jsonrpc":"2.0",
                                    "id": body["id"],
                                    "result": {
                                        "protocolVersion": "2025-11-25",
                                        "serverInfo": {"name": "upstream", "version": "1.0.0"},
                                        "capabilities": {}
                                    }
                                })),
                            )
                                .into_response()
                        }
                        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
                        Some("tools/call") => {
                            *upstream_tool_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("mcp-session-id")
                                    .and_then(|value| value.to_str().ok()),
                                Some("upstream-session-1")
                            );
                            assert_eq!(body["params"]["name"], "echo_remote");
                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {
                                    "content": [{"type": "text", "text": "ok-direct"}],
                                    "isError": false
                                }
                            }))
                            .into_response()
                        }
                        other => (
                            StatusCode::BAD_REQUEST,
                            Json(json!({"unexpected_method": other})),
                        )
                            .into_response(),
                    }
                }
            }),
        )
    };
    let upstream_url = spawn_router(upstream).await;

    let backend = {
        let backend_fallback_calls = backend_fallback_calls.clone();
        let backend_metric_calls = backend_metric_calls.clone();
        let backend_resolve_calls = backend_resolve_calls.clone();
        let upstream_url = upstream_url.clone();
        Router::new()
            .route(
                "/_internal/mcp/tools/call/resolve",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let backend_resolve_calls = backend_resolve_calls.clone();
                    let upstream_url = upstream_url.clone();
                    async move {
                        *backend_resolve_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        assert_eq!(body["params"]["name"], "echo");
                        Json(json!({
                            "eligible": true,
                            "transport": "streamablehttp",
                            "toolId": "tool-1",
                            "serverId": "server-1",
                            "serverUrl": format!("{upstream_url}/mcp"),
                            "remoteToolName": "echo_remote",
                            "headers": {"x-upstream-auth": "rust-plan"},
                            "timeoutMs": 30000
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move || {
                    let backend_fallback_calls = backend_fallback_calls.clone();
                    async move {
                        *backend_fallback_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": 1,
                            "result": {"unexpected": true}
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call/metric",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let backend_metric_calls = backend_metric_calls.clone();
                    async move {
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        backend_metric_calls.lock().expect("lock").push(body);
                        Json(json!({"status": "ok"}))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    for request_id in [31, 32] {
        let response = client
            .post(format!("{runtime_url}/mcp"))
            .header("authorization", "Bearer test-token")
            .header("x-contextforge-server-id", "server-1")
            .header("mcp-session-id", "client-session-1")
            .json(&json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {"text": "hello"}
                }
            }))
            .send()
            .await
            .expect("tools/call response");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("mcp-session-id")
                .and_then(|value| value.to_str().ok()),
            Some("client-session-1")
        );
        let body: Value = response.json().await.expect("json body");
        assert_eq!(body["result"]["content"][0]["text"], "ok-direct");
    }

    assert_eq!(*backend_resolve_calls.lock().expect("lock"), 1);
    assert_eq!(*backend_fallback_calls.lock().expect("lock"), 0);
    assert_eq!(*upstream_initialize_calls.lock().expect("lock"), 1);
    assert_eq!(*upstream_tool_calls.lock().expect("lock"), 2);
    let metric_calls = backend_metric_calls.lock().expect("lock");
    assert_eq!(metric_calls.len(), 2);
    for metric in metric_calls.iter() {
        assert_eq!(metric["toolId"], "tool-1");
        assert_eq!(metric["serverId"], "server-1");
        assert_eq!(metric["success"], true);
        assert!(metric["durationMs"].as_f64().unwrap_or_default() >= 0.0);
        assert!(metric.get("errorMessage").is_none());
    }
}

#[tokio::test]
async fn tools_call_reuses_shared_upstream_session_without_client_session_id() {
    let upstream_initialize_calls = Arc::new(Mutex::new(0usize));
    let upstream_tool_calls = Arc::new(Mutex::new(0usize));
    let backend_fallback_calls = Arc::new(Mutex::new(0usize));
    let backend_resolve_calls = Arc::new(Mutex::new(0usize));

    let upstream = {
        let upstream_initialize_calls = upstream_initialize_calls.clone();
        let upstream_tool_calls = upstream_tool_calls.clone();
        Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let upstream_initialize_calls = upstream_initialize_calls.clone();
                let upstream_tool_calls = upstream_tool_calls.clone();
                async move {
                    match body.get("method").and_then(Value::as_str) {
                        Some("initialize") => {
                            *upstream_initialize_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("x-upstream-auth")
                                    .and_then(|value| value.to_str().ok()),
                                Some("rust-plan")
                            );
                            let mut response_headers = HeaderMap::new();
                            response_headers.insert(
                                "mcp-session-id",
                                HeaderValue::from_static("shared-upstream-session"),
                            );
                            (
                                StatusCode::OK,
                                response_headers,
                                Json(json!({
                                    "jsonrpc":"2.0",
                                    "id": body["id"],
                                    "result": {
                                        "protocolVersion": "2025-11-25",
                                        "serverInfo": {"name": "upstream", "version": "1.0.0"},
                                        "capabilities": {}
                                    }
                                })),
                            )
                                .into_response()
                        }
                        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
                        Some("tools/call") => {
                            *upstream_tool_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("mcp-session-id")
                                    .and_then(|value| value.to_str().ok()),
                                Some("shared-upstream-session")
                            );
                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {
                                    "content": [{"type": "text", "text": "ok-shared"}],
                                    "isError": false
                                }
                            }))
                            .into_response()
                        }
                        other => (
                            StatusCode::BAD_REQUEST,
                            Json(json!({"unexpected_method": other})),
                        )
                            .into_response(),
                    }
                }
            }),
        )
    };
    let upstream_url = spawn_router(upstream).await;

    let backend = {
        let backend_fallback_calls = backend_fallback_calls.clone();
        let backend_resolve_calls = backend_resolve_calls.clone();
        let upstream_url = upstream_url.clone();
        Router::new()
            .route(
                "/_internal/mcp/tools/call/resolve",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let backend_resolve_calls = backend_resolve_calls.clone();
                    let upstream_url = upstream_url.clone();
                    async move {
                        *backend_resolve_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        assert_eq!(body["params"]["name"], "echo");
                        Json(json!({
                            "eligible": true,
                            "transport": "streamablehttp",
                            "serverUrl": format!("{upstream_url}/mcp"),
                            "remoteToolName": "echo_remote",
                            "headers": {"x-upstream-auth": "rust-plan"},
                            "timeoutMs": 30000
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move || {
                    let backend_fallback_calls = backend_fallback_calls.clone();
                    async move {
                        *backend_fallback_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": 1,
                            "result": {"unexpected": true}
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    for request_id in [41, 42] {
        let response = client
            .post(format!("{runtime_url}/mcp"))
            .header("authorization", "Bearer test-token")
            .header("x-contextforge-server-id", "server-1")
            .json(&json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {"text": "hello"}
                }
            }))
            .send()
            .await
            .expect("tools/call response");

        assert_eq!(response.status(), StatusCode::OK);
        assert!(response.headers().get("mcp-session-id").is_none());
        let body: Value = response.json().await.expect("json body");
        assert_eq!(body["result"]["content"][0]["text"], "ok-shared");
    }

    assert_eq!(*backend_resolve_calls.lock().expect("lock"), 1);
    assert_eq!(*backend_fallback_calls.lock().expect("lock"), 0);
    assert_eq!(*upstream_initialize_calls.lock().expect("lock"), 1);
    assert_eq!(*upstream_tool_calls.lock().expect("lock"), 2);
}

#[tokio::test]
async fn tools_call_reinitializes_upstream_session_after_cached_session_failure() {
    let upstream_initialize_calls = Arc::new(Mutex::new(0usize));
    let upstream_tool_calls = Arc::new(Mutex::new(Vec::<String>::new()));
    let session_one_uses = Arc::new(Mutex::new(0usize));
    let backend_resolve_calls = Arc::new(Mutex::new(0usize));

    let upstream = {
        let upstream_initialize_calls = upstream_initialize_calls.clone();
        let upstream_tool_calls = upstream_tool_calls.clone();
        let session_one_uses = session_one_uses.clone();
        Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let upstream_initialize_calls = upstream_initialize_calls.clone();
                let upstream_tool_calls = upstream_tool_calls.clone();
                let session_one_uses = session_one_uses.clone();
                async move {
                    match body.get("method").and_then(Value::as_str) {
                        Some("initialize") => {
                            let init_index = {
                                let mut calls = upstream_initialize_calls.lock().expect("lock");
                                *calls += 1;
                                *calls
                            };
                            let session_id = if init_index == 1 {
                                "retry-upstream-session-1"
                            } else {
                                "retry-upstream-session-2"
                            };
                            let mut response_headers = HeaderMap::new();
                            response_headers.insert(
                                "mcp-session-id",
                                HeaderValue::from_str(session_id).expect("session header"),
                            );
                            (
                                StatusCode::OK,
                                response_headers,
                                Json(json!({
                                    "jsonrpc":"2.0",
                                    "id": body["id"],
                                    "result": {
                                        "protocolVersion": "2025-11-25",
                                        "serverInfo": {"name": "upstream", "version": "1.0.0"},
                                        "capabilities": {}
                                    }
                                })),
                            )
                                .into_response()
                        }
                        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
                        Some("tools/call") => {
                            let session_id = headers
                                .get("mcp-session-id")
                                .and_then(|value| value.to_str().ok())
                                .expect("upstream session id")
                                .to_string();
                            upstream_tool_calls
                                .lock()
                                .expect("lock")
                                .push(session_id.clone());

                            if session_id == "retry-upstream-session-1" {
                                let use_count = {
                                    let mut calls = session_one_uses.lock().expect("lock");
                                    *calls += 1;
                                    *calls
                                };
                                if use_count == 1 {
                                    return Json(json!({
                                        "jsonrpc":"2.0",
                                        "id": body["id"],
                                        "result": {
                                            "content": [{"type": "text", "text": "ok-initial"}],
                                            "isError": false
                                        }
                                    }))
                                    .into_response();
                                }

                                return (
                                    StatusCode::UNAUTHORIZED,
                                    Json(json!({
                                        "code": -32099,
                                        "message": "upstream session expired"
                                    })),
                                )
                                    .into_response();
                            }

                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {
                                    "content": [{"type": "text", "text": "ok-refreshed"}],
                                    "isError": false
                                }
                            }))
                            .into_response()
                        }
                        other => (
                            StatusCode::BAD_REQUEST,
                            Json(json!({"unexpected_method": other})),
                        )
                            .into_response(),
                    }
                }
            }),
        )
    };
    let upstream_url = spawn_router(upstream).await;

    let backend = {
        let backend_resolve_calls = backend_resolve_calls.clone();
        let upstream_url = upstream_url.clone();
        Router::new().route(
            "/_internal/mcp/tools/call/resolve",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let backend_resolve_calls = backend_resolve_calls.clone();
                let upstream_url = upstream_url.clone();
                async move {
                    *backend_resolve_calls.lock().expect("lock") += 1;
                    assert_eq!(
                        headers
                            .get("x-contextforge-server-id")
                            .and_then(|value| value.to_str().ok()),
                        Some("server-1")
                    );
                    assert_eq!(body["params"]["name"], "echo");
                    Json(json!({
                        "eligible": true,
                        "transport": "streamablehttp",
                        "serverUrl": format!("{upstream_url}/mcp"),
                        "remoteToolName": "echo_remote",
                        "headers": {"x-upstream-auth": "rust-plan"},
                        "timeoutMs": 30000
                    }))
                }
            }),
        )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    let initial = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .header("mcp-session-id", "client-session-retry")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"text": "hello"}
            }
        }))
        .send()
        .await
        .expect("initial tools/call response");
    assert_eq!(initial.status(), StatusCode::OK);
    let initial_body: Value = initial.json().await.expect("initial json body");
    assert_eq!(
        initial_body["result"]["content"][0]["text"],
        json!("ok-initial")
    );

    let refreshed = client
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .header("mcp-session-id", "client-session-retry")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 72,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"text": "hello again"}
            }
        }))
        .send()
        .await
        .expect("refreshed tools/call response");
    assert_eq!(refreshed.status(), StatusCode::OK);
    assert_eq!(
        refreshed
            .headers()
            .get("mcp-session-id")
            .and_then(|value| value.to_str().ok()),
        Some("client-session-retry")
    );
    let refreshed_body: Value = refreshed.json().await.expect("refreshed json body");
    assert_eq!(
        refreshed_body["result"]["content"][0]["text"],
        json!("ok-refreshed")
    );

    assert_eq!(*backend_resolve_calls.lock().expect("lock"), 1);
    assert_eq!(*upstream_initialize_calls.lock().expect("lock"), 2);
    assert_eq!(
        upstream_tool_calls.lock().expect("lock").as_slice(),
        &[
            "retry-upstream-session-1".to_string(),
            "retry-upstream-session-1".to_string(),
            "retry-upstream-session-2".to_string(),
        ]
    );
}

#[cfg(feature = "rmcp-upstream-client")]
#[tokio::test]
async fn tools_call_can_use_rmcp_upstream_client() {
    let upstream_initialize_calls = Arc::new(Mutex::new(0usize));
    let upstream_tool_calls = Arc::new(Mutex::new(0usize));
    let backend_fallback_calls = Arc::new(Mutex::new(0usize));
    let backend_resolve_calls = Arc::new(Mutex::new(0usize));
    let metric_records: Arc<Mutex<Vec<Value>>> = Arc::new(Mutex::new(Vec::new()));

    let upstream = {
        let upstream_initialize_calls = upstream_initialize_calls.clone();
        let upstream_tool_calls = upstream_tool_calls.clone();
        Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let upstream_initialize_calls = upstream_initialize_calls.clone();
                let upstream_tool_calls = upstream_tool_calls.clone();
                async move {
                    match body.get("method").and_then(Value::as_str) {
                        Some("initialize") => {
                            *upstream_initialize_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("x-upstream-auth")
                                    .and_then(|value| value.to_str().ok()),
                                Some("rust-plan")
                            );
                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {
                                    "protocolVersion": "2025-11-25",
                                    "serverInfo": {"name": "upstream", "version": "1.0.0"},
                                    "capabilities": {}
                                }
                            }))
                            .into_response()
                        }
                        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
                        Some("tools/call") => {
                            *upstream_tool_calls.lock().expect("lock") += 1;
                            assert_eq!(body["params"]["name"], "echo_remote");
                            Json(json!({
                                "jsonrpc":"2.0",
                                "id": body["id"],
                                "result": {
                                    "content": [{"type": "text", "text": "ok-rmcp"}],
                                    "isError": false
                                }
                            }))
                            .into_response()
                        }
                        other => (
                            StatusCode::BAD_REQUEST,
                            Json(json!({"unexpected_method": other})),
                        )
                            .into_response(),
                    }
                }
            }),
        )
    };
    let upstream_url = spawn_router(upstream).await;

    let backend = {
        let backend_fallback_calls = backend_fallback_calls.clone();
        let backend_resolve_calls = backend_resolve_calls.clone();
        let metric_records = metric_records.clone();
        let upstream_url = upstream_url.clone();
        Router::new()
            .route(
                "/_internal/mcp/tools/call/resolve",
                post(move |Json(body): Json<Value>| {
                    let backend_resolve_calls = backend_resolve_calls.clone();
                    let upstream_url = upstream_url.clone();
                    async move {
                        *backend_resolve_calls.lock().expect("lock") += 1;
                        assert_eq!(body["params"]["name"], "echo");
                        Json(json!({
                            "eligible": true,
                            "toolId": "tool-1",
                            "serverId": "server-1",
                            "transport": "streamablehttp",
                            "serverUrl": format!("{upstream_url}/mcp"),
                            "remoteToolName": "echo_remote",
                            "headers": {"x-upstream-auth": "rust-plan"},
                            "timeoutMs": 30000
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call/metric",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let metric_records = metric_records.clone();
                    async move {
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        metric_records.lock().expect("lock").push(body);
                        Json(json!({"status": "ok"}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move || {
                    let backend_fallback_calls = backend_fallback_calls.clone();
                    async move {
                        *backend_fallback_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": 1,
                            "result": {"unexpected": true}
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            use_rmcp_upstream_client: true,
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;
    let client = reqwest::Client::new();

    for request_id in [61, 62] {
        let response = client
            .post(format!("{runtime_url}/mcp"))
            .header("authorization", "Bearer test-token")
            .header("x-contextforge-server-id", "server-1")
            .json(&json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {"text": "hello"}
                }
            }))
            .send()
            .await
            .expect("tools/call response");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get("x-contextforge-mcp-upstream-client")
                .and_then(|value| value.to_str().ok()),
            Some("rmcp")
        );
        let body: Value = response.json().await.expect("json body");
        assert_eq!(body["result"]["content"][0]["text"], "ok-rmcp");
    }

    assert_eq!(*backend_resolve_calls.lock().expect("lock"), 1);
    assert_eq!(*backend_fallback_calls.lock().expect("lock"), 0);
    assert_eq!(*upstream_initialize_calls.lock().expect("lock"), 1);
    assert_eq!(*upstream_tool_calls.lock().expect("lock"), 2);
    let metric_records = metric_records.lock().expect("lock");
    assert_eq!(metric_records.len(), 2);
    for body in metric_records.iter() {
        assert_eq!(body["toolId"], "tool-1");
        assert_eq!(body["serverId"], "server-1");
        assert_eq!(body["success"], true);
        assert!(body["durationMs"].as_f64().unwrap_or_default() >= 0.0);
        assert!(body.get("errorMessage").is_none());
    }
}

#[tokio::test]
async fn tools_call_direct_execution_supports_sse_upstream_responses() {
    let upstream_initialize_calls = Arc::new(Mutex::new(0usize));
    let upstream_tool_calls = Arc::new(Mutex::new(0usize));
    let backend_fallback_calls = Arc::new(Mutex::new(0usize));
    let backend_resolve_calls = Arc::new(Mutex::new(0usize));

    let upstream = {
        let upstream_initialize_calls = upstream_initialize_calls.clone();
        let upstream_tool_calls = upstream_tool_calls.clone();
        Router::new().route(
            "/mcp",
            post(move |headers: HeaderMap, Json(body): Json<Value>| {
                let upstream_initialize_calls = upstream_initialize_calls.clone();
                let upstream_tool_calls = upstream_tool_calls.clone();
                async move {
                    match body.get("method").and_then(Value::as_str) {
                        Some("initialize") => {
                            *upstream_initialize_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("x-upstream-auth")
                                    .and_then(|value| value.to_str().ok()),
                                Some("rust-plan")
                            );
                            let mut response_headers = HeaderMap::new();
                            response_headers.insert(
                                "mcp-session-id",
                                HeaderValue::from_static("sse-upstream-session"),
                            );
                            response_headers.insert(
                                "content-type",
                                HeaderValue::from_static("text/event-stream"),
                            );
                            (
                                StatusCode::OK,
                                response_headers,
                                format!(
                                    "data: {}\n\n",
                                    json!({
                                        "jsonrpc":"2.0",
                                        "id": body["id"],
                                        "result": {
                                            "protocolVersion": "2025-11-25",
                                            "serverInfo": {"name": "upstream", "version": "1.0.0"},
                                            "capabilities": {}
                                        }
                                    })
                                ),
                            )
                                .into_response()
                        }
                        Some("notifications/initialized") => StatusCode::ACCEPTED.into_response(),
                        Some("tools/call") => {
                            *upstream_tool_calls.lock().expect("lock") += 1;
                            assert_eq!(
                                headers
                                    .get("mcp-session-id")
                                    .and_then(|value| value.to_str().ok()),
                                Some("sse-upstream-session")
                            );
                            (
                                StatusCode::OK,
                                [(
                                    "content-type",
                                    HeaderValue::from_static("text/event-stream"),
                                )],
                                format!(
                                    "data: {}\nid: 0/0\n\n",
                                    json!({
                                        "jsonrpc":"2.0",
                                        "id": body["id"],
                                        "result": {
                                            "content": [{"type": "text", "text": "ok-sse-direct"}],
                                            "isError": false
                                        }
                                    })
                                ),
                            )
                                .into_response()
                        }
                        other => (
                            StatusCode::BAD_REQUEST,
                            Json(json!({"unexpected_method": other})),
                        )
                            .into_response(),
                    }
                }
            }),
        )
    };
    let upstream_url = spawn_router(upstream).await;

    let backend = {
        let backend_fallback_calls = backend_fallback_calls.clone();
        let backend_resolve_calls = backend_resolve_calls.clone();
        let upstream_url = upstream_url.clone();
        Router::new()
            .route(
                "/_internal/mcp/tools/call/resolve",
                post(move |Json(body): Json<Value>| {
                    let backend_resolve_calls = backend_resolve_calls.clone();
                    let upstream_url = upstream_url.clone();
                    async move {
                        *backend_resolve_calls.lock().expect("lock") += 1;
                        assert_eq!(body["params"]["name"], "echo");
                        Json(json!({
                            "eligible": true,
                            "transport": "streamablehttp",
                            "serverUrl": format!("{upstream_url}/mcp"),
                            "remoteToolName": "echo_remote",
                            "headers": {"x-upstream-auth": "rust-plan"},
                            "timeoutMs": 30000
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/tools/call",
                post(move || {
                    let backend_fallback_calls = backend_fallback_calls.clone();
                    async move {
                        *backend_fallback_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id": 1,
                            "result": {"unexpected": true}
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("authorization", "Bearer test-token")
        .header("x-contextforge-server-id", "server-1")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"text": "hello"}
            }
        }))
        .send()
        .await
        .expect("tools/call response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["content"][0]["text"], "ok-sse-direct");
    assert_eq!(*backend_resolve_calls.lock().expect("lock"), 1);
    assert_eq!(*backend_fallback_calls.lock().expect("lock"), 0);
    assert_eq!(*upstream_initialize_calls.lock().expect("lock"), 1);
    assert_eq!(*upstream_tool_calls.lock().expect("lock"), 1);
}

#[tokio::test]
async fn mcp_path_aliases_to_the_same_runtime_handler() {
    let backend = Router::new().route(
        "/rpc",
        post(|| async {
            Json(json!({
                "jsonrpc":"2.0",
                "id": 3,
                "result": {"ok": true}
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("mcp alias response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["ok"], true);
}

#[tokio::test]
async fn unsupported_protocol_header_is_rejected() {
    let backend = Router::new().route(
        "/rpc",
        post(|| async {
            Json(json!({
                "jsonrpc":"2.0",
                "id": 1,
                "result": {}
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "1999-01-01")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": "ping-bad-version",
            "method": "ping",
            "params": {}
        }))
        .send()
        .await
        .expect("unsupported version response");

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["error"], "Bad Request");
    assert!(
        body["message"]
            .as_str()
            .expect("message string")
            .contains("Unsupported protocol version: 1999-01-01")
    );
}

#[tokio::test]
async fn notifications_are_forwarded_but_return_accepted() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let initialized_calls = Arc::new(Mutex::new(0usize));
    let message_calls = Arc::new(Mutex::new(0usize));
    let cancelled_calls = Arc::new(Mutex::new(0usize));
    let backend = {
        let rpc_calls = rpc_calls.clone();
        let initialized_calls = initialized_calls.clone();
        let message_calls = message_calls.clone();
        let cancelled_calls = cancelled_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({"jsonrpc":"2.0","result":{}}))
                    }
                }),
            )
            .route(
                "/_internal/mcp/notifications/initialized",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let initialized_calls = initialized_calls.clone();
                    async move {
                        *initialized_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "notifications/initialized");
                        StatusCode::NO_CONTENT.into_response()
                    }
                }),
            )
            .route(
                "/_internal/mcp/notifications/message",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let message_calls = message_calls.clone();
                    async move {
                        *message_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "notifications/message");
                        StatusCode::NO_CONTENT.into_response()
                    }
                }),
            )
            .route(
                "/_internal/mcp/notifications/cancelled",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let cancelled_calls = cancelled_calls.clone();
                    async move {
                        *cancelled_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(body["method"], "notifications/cancelled");
                        StatusCode::NO_CONTENT.into_response()
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let client = reqwest::Client::new();

    let response = client
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }))
        .send()
        .await
        .expect("notification response");

    assert_eq!(response.status(), StatusCode::ACCEPTED);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    assert!(response.bytes().await.expect("body bytes").is_empty());

    let response = client
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "data": "hello",
                "level": "info",
                "logger": "tests"
            }
        }))
        .send()
        .await
        .expect("notification response");

    assert_eq!(response.status(), StatusCode::ACCEPTED);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    assert!(response.bytes().await.expect("body bytes").is_empty());

    let response = client
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": "req-1",
                "reason": "stop"
            }
        }))
        .send()
        .await
        .expect("notification response");

    assert_eq!(response.status(), StatusCode::ACCEPTED);
    assert_eq!(
        response
            .headers()
            .get("x-contextforge-mcp-runtime")
            .and_then(|value| value.to_str().ok()),
        Some("rust")
    );
    assert!(response.bytes().await.expect("body bytes").is_empty());

    assert_eq!(*initialized_calls.lock().expect("lock"), 1);
    assert_eq!(*message_calls.lock().expect("lock"), 1);
    assert_eq!(*cancelled_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn internal_only_headers_are_not_forwarded_to_backend() {
    let backend = Router::new().route(
        "/rpc",
        post(|headers: HeaderMap| async move {
            Json(json!({
                "jsonrpc":"2.0",
                "id": 1,
                "result": {
                    "x_forwarded_internally": headers.get("x-forwarded-internally").and_then(|value| value.to_str().ok()),
                    "x_forwarded_for": headers.get("x-forwarded-for").and_then(|value| value.to_str().ok()),
                    "x_real_ip": headers.get("x-real-ip").and_then(|value| value.to_str().ok()),
                    "x_forwarded_proto": headers.get("x-forwarded-proto").and_then(|value| value.to_str().ok()),
                    "x_mcp_session_id": headers.get("x-mcp-session-id").and_then(|value| value.to_str().ok()),
                    "runtime_header": headers.get("x-contextforge-mcp-runtime").and_then(|value| value.to_str().ok()),
                }
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("x-forwarded-internally", "true")
        .header("x-forwarded-for", "198.51.100.10")
        .header("x-real-ip", "198.51.100.10")
        .header("x-forwarded-proto", "https")
        .header("x-mcp-session-id", "internal-only")
        .header("x-contextforge-mcp-runtime", "spoofed")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }))
        .send()
        .await
        .expect("runtime response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["x_forwarded_internally"], Value::Null);
    assert_eq!(body["result"]["x_forwarded_for"], Value::Null);
    assert_eq!(body["result"]["x_real_ip"], Value::Null);
    assert_eq!(body["result"]["x_forwarded_proto"], Value::Null);
    assert_eq!(body["result"]["x_mcp_session_id"], Value::Null);
    assert_eq!(body["result"]["runtime_header"], "rust");
}

#[tokio::test]
async fn initialize_uses_specialized_internal_endpoint() {
    let rpc_calls = Arc::new(Mutex::new(0usize));
    let initialize_calls = Arc::new(Mutex::new(0usize));

    let backend = {
        let rpc_calls = rpc_calls.clone();
        let initialize_calls = initialize_calls.clone();
        Router::new()
            .route(
                "/rpc",
                post(move || {
                    let rpc_calls = rpc_calls.clone();
                    async move {
                        *rpc_calls.lock().expect("lock") += 1;
                        Json(json!({
                            "jsonrpc":"2.0",
                            "id":"unexpected-rpc-path",
                            "result": {}
                        }))
                    }
                }),
            )
            .route(
                "/_internal/mcp/initialize",
                post(move |headers: HeaderMap, Json(body): Json<Value>| {
                    let initialize_calls = initialize_calls.clone();
                    async move {
                        *initialize_calls.lock().expect("lock") += 1;
                        assert_eq!(
                            headers
                                .get("x-contextforge-mcp-runtime")
                                .and_then(|value| value.to_str().ok()),
                            Some("rust")
                        );
                        assert_eq!(
                            headers
                                .get("x-contextforge-server-id")
                                .and_then(|value| value.to_str().ok()),
                            Some("server-1")
                        );
                        assert_eq!(body["method"], "initialize");
                        Json(json!({
                            "jsonrpc": "2.0",
                            "id": body["id"],
                            "result": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "serverInfo": {"name": "ContextForge", "version": "1.0.0"}
                            }
                        }))
                    }
                }),
            )
    };
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/_internal/mcp/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("x-contextforge-server-id", "server-1")
        .header(
            "x-contextforge-auth-context",
            URL_SAFE_NO_PAD.encode(r#"{"email":"user@example.com","teams":["team-1"],"is_authenticated":true,"is_admin":false,"permission_is_admin":false}"#),
        )
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {}
            }
        }))
        .send()
        .await
        .expect("initialize response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["id"], "init-1");
    assert_eq!(body["result"]["protocolVersion"], "2025-11-25");
    assert_eq!(*initialize_calls.lock().expect("lock"), 1);
    assert_eq!(*rpc_calls.lock().expect("lock"), 0);
}

#[tokio::test]
async fn initialize_missing_protocol_version_returns_invalid_params() {
    let backend = Router::new().route(
        "/rpc",
        post(|| async {
            Json(json!({
                "jsonrpc":"2.0",
                "id": "should-not-be-called",
                "result": {}
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!({
            "jsonrpc": "2.0",
            "id": "init-missing-version",
            "method": "initialize",
            "params": {
                "capabilities": {},
                "clientInfo": {"name": "mcp-compliance-suite", "version": "1.0.0"}
            }
        }))
        .send()
        .await
        .expect("initialize invalid params response");

    assert_eq!(response.status(), StatusCode::OK);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["jsonrpc"], "2.0");
    assert_eq!(body["id"], "init-missing-version");
    assert_eq!(body["error"]["code"], -32602);
}

#[tokio::test]
async fn jsonrpc_batch_payload_is_rejected() {
    let backend = Router::new().route(
        "/rpc",
        post(|| async {
            Json(json!({
                "jsonrpc":"2.0",
                "id": 1,
                "result": {}
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .json(&json!([
            {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        ]))
        .send()
        .await
        .expect("batch rejection response");

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["jsonrpc"], "2.0");
    assert_eq!(body["error"]["code"], -32600);
}

#[tokio::test]
async fn top_level_scalar_payload_is_invalid_request() {
    let backend = Router::new().route(
        "/rpc",
        post(|| async {
            Json(json!({
                "jsonrpc":"2.0",
                "id": 1,
                "result": {}
            }))
        }),
    );
    let backend_url = spawn_router(backend).await;

    let runtime = {
        let config = RuntimeConfig {
            backend_rpc_url: format!("{backend_url}/rpc"),
            listen_http: "127.0.0.1:8787".to_string(),
            listen_uds: None,
            protocol_version: "2025-11-25".to_string(),
            supported_protocol_versions: vec![],
            server_name: "ContextForge".to_string(),
            server_version: "0.1.0".to_string(),
            instructions: "ContextForge providing federated tools, resources and prompts. Use /admin interface for configuration.".to_string(),
            request_timeout_ms: 30_000,
            database_url: None,
            db_pool_max_size: 20,
            log_filter: "error".to_string(),
            ..test_runtime_config()
        };
        build_router(AppState::new(&config).expect("state"))
    };
    let runtime_url = spawn_router(runtime).await;

    let response = reqwest::Client::new()
        .post(format!("{runtime_url}/mcp"))
        .header("mcp-protocol-version", "2025-11-25")
        .body("\"not-an-object\"")
        .send()
        .await
        .expect("invalid request response");

    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["jsonrpc"], "2.0");
    assert_eq!(body["error"]["code"], -32600);
}
