use axum::{
    Json, Router,
    http::{HeaderMap, StatusCode},
    routing::post,
};
use contextforge_mcp_runtime::{AppState, build_router, config::RuntimeConfig};
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
            log_filter: "error".to_string(),
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
        log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
    let body: Value = response.json().await.expect("json body");
    assert_eq!(body["result"]["tools"][0]["name"], "echo");

    let calls = observation.calls.lock().expect("lock");
    assert_eq!(calls.len(), 1);
    assert_eq!(calls[0].0, "tools/list");
    assert_eq!(calls[0].1.as_deref(), Some("Bearer test-token"));
    assert_eq!(calls[0].2.as_deref(), Some("session-1"));
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
            log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
            log_filter: "error".to_string(),
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
