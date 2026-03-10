use axum::{
    Json, Router,
    http::{HeaderMap, StatusCode, Uri},
    response::IntoResponse,
    routing::{get, post},
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use contextforge_mcp_runtime::{AppState, build_router, config::RuntimeConfig};
use reqwest::header::HeaderValue;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};

#[derive(Clone, Default)]
struct BackendObservation {
    calls: Arc<Mutex<Vec<(String, Option<String>, Option<String>)>>>,
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
        database_url: None,
        db_pool_max_size: 20,
        log_filter: "error".to_string(),
    }
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
    assert!(
        body["supported_protocol_versions"]
            .as_array()
            .expect("supported protocol versions array")
            .iter()
            .any(|value| value == "2025-03-26")
    );
}

#[tokio::test]
async fn get_and_delete_mcp_routes_forward_to_internal_transport_bridge() {
    let transport_calls = Arc::new(Mutex::new(Vec::<(String, Option<String>, Option<String>, Option<String>)>::new()));
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
                        [( "content-type", HeaderValue::from_static("text/event-stream"))],
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
    assert_eq!(get_response.text().await.expect("stream text"), "data: ping\n\n");

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
    assert_eq!(calls[0], ("GET".to_string(), Some("Bearer test-token".to_string()), Some("client-session-1".to_string()), Some("session_id=session-42".to_string())));
    assert_eq!(calls[1], ("DELETE".to_string(), Some("Bearer test-token".to_string()), Some("client-session-1".to_string()), Some("session_id=session-42".to_string())));
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
    let observation = BackendObservation::default();
    let backend = {
        let observation = observation.clone();
        Router::new().route(
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
                    Json(json!({"jsonrpc":"2.0","result":{}}))
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

    let calls = observation.calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].0, "notifications/initialized");
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
    assert_eq!(body["result"]["x_mcp_session_id"], Value::Null);
    assert_eq!(body["result"]["runtime_header"], "rust");
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
