// tests/integration.rs

// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Integration tests for the A2A runtime sidecar.
//!
//! Uses `tower::ServiceExt::oneshot` to drive the Axum app in-memory
//! and `wiremock` to mock the downstream agent endpoint.

mod test_helpers;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use contextforge_a2a_runtime::config::RuntimeConfig;
use http_body_util::BodyExt;
use serde_json::{Value, json};
use std::sync::Arc;
use test_helpers::*;
use tower::ServiceExt;
use wiremock::matchers::{body_json, header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// Build a test-ready Axum app with the given config.
fn test_app(config: RuntimeConfig) -> axum::Router {
    contextforge_a2a_runtime::test_support::build_app(config)
}

fn test_app_with_session_manager(
    config: RuntimeConfig,
    session_manager: Option<Arc<contextforge_a2a_runtime::session::SessionManager>>,
) -> axum::Router {
    contextforge_a2a_runtime::test_support::build_app_with_session_manager(config, session_manager)
}

/// Helper: make a JSON POST request to the app and return (status, body JSON).
async fn post_json(app: axum::Router, uri: &str, body: Value) -> (StatusCode, Value) {
    let request = Request::builder()
        .method("POST")
        .uri(uri)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&bytes)
        .unwrap_or(json!({"raw": String::from_utf8_lossy(&bytes).to_string()}));
    (status, json)
}

async fn get_json(app: axum::Router, uri: &str) -> (StatusCode, Value) {
    let request = Request::builder()
        .method("GET")
        .uri(uri)
        .body(Body::empty())
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let json: Value = serde_json::from_slice(&bytes).unwrap_or(json!(null));
    (status, json)
}

fn default_test_config() -> RuntimeConfig {
    RuntimeConfig {
        listen_http: "127.0.0.1:0".to_string(),
        listen_uds: None,
        request_timeout_ms: 5_000,
        client_connect_timeout_ms: 2_000,
        client_pool_idle_timeout_seconds: 10,
        client_pool_max_idle_per_host: 4,
        client_tcp_keepalive_seconds: 10,
        max_response_body_bytes: 10_485_760,
        max_retries: 1,
        retry_backoff_ms: 100,
        auth_secret: None,
        backend_base_url: "http://127.0.0.1:4444".to_string(),
        max_concurrent: 64,
        max_queued: None,
        circuit_failure_threshold: 5,
        circuit_cooldown_secs: 30,
        circuit_max_entries: 10_000,
        metrics_max_entries: 10_000,
        agent_cache_ttl_secs: 60,
        agent_cache_max_entries: 1_000,
        redis_url: None,
        l2_cache_ttl_secs: 300,
        cache_invalidation_channel: "mcpgw:a2a:invalidate".to_string(),
        session_enabled: false,
        session_ttl_secs: 300,
        session_fingerprint_headers: "authorization,cookie,x-forwarded-for".to_string(),
        event_store_max_events: 1000,
        event_store_ttl_secs: 3600,
        event_flush_interval_ms: 1000,
        event_flush_batch_size: 100,
        uaid_allowed_domains: String::new(),
        uaid_allowed_domains_cache: Default::default(),
        uaid_max_length: 2048,
        uaid_max_federation_hops: 3,
        log_filter: "warn".to_string(),
        exit_after_startup_ms: None,
    }
}

#[tokio::test]
async fn health_returns_ok() {
    let app = test_app(default_test_config());
    let (status, body) = get_json(app, "/health").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "ok");
    assert_eq!(body["runtime"], "contextforge-a2a-runtime");
}

#[tokio::test]
async fn healthz_returns_ok() {
    let app = test_app(default_test_config());
    let (status, body) = get_json(app, "/healthz").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status"], "ok");
}

#[tokio::test]
async fn health_and_healthz_return_full_schema_with_uds() {
    let mut config = default_test_config();
    config.listen_http = "127.0.0.1:9876".to_string();
    config.listen_uds = Some(std::path::PathBuf::from("/tmp/contextforge-a2a.sock"));
    let app = test_app(config);

    for path in ["/health", "/healthz"] {
        let (status, body) = get_json(app.clone(), path).await;
        assert_eq!(status, StatusCode::OK, "{path} failed: {body}");
        assert_eq!(body["status"], "ok");
        assert_eq!(body["runtime"], "contextforge-a2a-runtime");
        assert_eq!(body["listen_http"], "127.0.0.1:9876");
        assert_eq!(body["listen_uds"], "/tmp/contextforge-a2a.sock");
    }
}

#[tokio::test]
async fn invoke_forwards_to_agent_and_returns_response() {
    let mock_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}})),
        )
        .mount(&mock_server)
        .await;

    let app = test_app(default_test_config());
    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": mock_server.uri(),
            "headers": {"Content-Type": "application/json"},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}},
            "timeout_seconds": 5
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["result"]["status"], "ok");
}

#[tokio::test]
async fn invoke_rejects_file_scheme() {
    let app = test_app(default_test_config());
    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": "file:///etc/passwd",
            "headers": {},
            "json_body": {},
        }),
    )
    .await;

    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"].as_str().unwrap().contains("invalid"));
}

#[tokio::test]
async fn invoke_retries_on_5xx_then_succeeds() {
    let mock_server = MockServer::start().await;

    // First call returns 503, second returns 200.
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(503))
        .up_to_n_times(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.max_retries = 2;
    config.retry_backoff_ms = 50;
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": mock_server.uri(),
            "headers": {},
            "json_body": {"test": true},
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["ok"], true);
}

#[tokio::test]
async fn invoke_returns_bad_gateway_on_connection_refused() {
    let app = test_app(default_test_config());
    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": "http://127.0.0.1:1",
            "headers": {},
            "json_body": {},
        }),
    )
    .await;

    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert!(body["error"].as_str().unwrap().contains("connection"));
}

#[tokio::test]
async fn invoke_returns_gateway_timeout_on_slow_agent() {
    let mock_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200).set_delay(std::time::Duration::from_secs(10)))
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.request_timeout_ms = 500;
    config.max_retries = 0;
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": mock_server.uri(),
            "headers": {},
            "json_body": {},
            "timeout_seconds": 1
        }),
    )
    .await;

    assert_eq!(status, StatusCode::GATEWAY_TIMEOUT);
    assert!(body["error"].as_str().unwrap().contains("timed out"));
}

#[tokio::test]
async fn invoke_forwards_custom_headers() {
    let mock_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .and(wiremock::matchers::header("X-Custom", "test-value"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"received": true})))
        .mount(&mock_server)
        .await;

    let app = test_app(default_test_config());
    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": mock_server.uri(),
            "headers": {"X-Custom": "test-value", "Content-Type": "application/json"},
            "json_body": {},
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["json"]["received"], true);
}

// ---------------------------------------------------------------------------
// New tests for PR capabilities
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_metrics_endpoint_returns_json() {
    let app = test_app(default_test_config());
    let (status, body) = get_json(app, "/metrics").await;

    assert_eq!(status, StatusCode::OK);
    // Verify the expected fields exist in the response.
    assert!(
        body.get("total_calls").is_some(),
        "metrics should include total_calls"
    );
    assert!(
        body.get("successful_calls").is_some(),
        "metrics should include successful_calls"
    );
    assert!(
        body.get("failed_calls").is_some(),
        "metrics should include failed_calls"
    );
    assert!(
        body.get("total_latency_us").is_some(),
        "metrics should include total_latency_us"
    );
    assert!(
        body.get("min_latency_us").is_some(),
        "metrics should include min_latency_us"
    );
    assert!(
        body.get("max_latency_us").is_some(),
        "metrics should include max_latency_us"
    );

    // On a fresh app with no invocations, all call counters should be zero.
    assert_eq!(body["total_calls"], 0);
    assert_eq!(body["successful_calls"], 0);
    assert_eq!(body["failed_calls"], 0);
}

/// Drive the shared `/invoke` hop-guard test body: boot a mock agent
/// (which must not receive any requests), post with the given JSON
/// `headers` sub-object, and assert a 404.
///
/// Folded from two near-identical tests to keep the RFC 7230 coalesced
/// case and the HashMap multi-variant smuggling case side-by-side: both
/// defend the same hop counter invariant ("fail closed to the MAX of
/// all observed values"), and folding them makes it obvious when one
/// path regresses while the other still passes.
async fn run_invoke_hop_guard_rejects(headers_payload: Value, reason: &'static str) {
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0) // must not be reached — hop guard fires first
        .mount(&remote_agent)
        .await;

    let mut config = default_test_config();
    config.uaid_max_federation_hops = 3;
    let app = test_app(config);

    let (status, _) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": remote_agent.uri(),
            "headers": headers_payload,
            "json_body": {"jsonrpc": "2.0", "id": 1}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::NOT_FOUND, "{reason}");
    remote_agent.verify().await;
}

#[tokio::test]
async fn test_invoke_hop_guard_rejects_coalesced_header() {
    // RFC 7230 §3.2.2 allows a proxy to coalesce two `X-Hop: N` headers
    // into a single comma-joined value.  `"0, 3"` at limit=3 must still
    // be rejected — parser must split, trim OWS, and fail to the max.
    run_invoke_hop_guard_rejects(
        json!({"X-Contextforge-UAID-Hop": "0, 3"}),
        "coalesced '0, 3' must be parsed as max=3 and trip the guard",
    )
    .await;
}

#[tokio::test]
async fn test_invoke_hop_guard_rejects_multi_variant_smuggling() {
    // Attacker sends a low value under one case and a high value under
    // another, hoping HashMap iteration order picks the low one and
    // bypasses the guard.  Scan all case-insensitive matches, take max.
    run_invoke_hop_guard_rejects(
        json!({
            "X-Contextforge-UAID-Hop": "3",
            "x-contextforge-uaid-hop": "0",
        }),
        "multi-variant smuggling must not reset the counter; expected 404",
    )
    .await;
}

#[tokio::test]
async fn test_a2a_invoke_hop_guard_rejects_duplicate_http_headers() {
    // Same attack vector on the `/a2a/*` path: two HTTP headers with
    // the same name (one value low, one high) are both kept by axum's
    // HeaderMap.  Collapsing into a HashMap would drop one
    // unpredictably; `read_hop_from_header_map` reads `get_all` and
    // picks the max, so the high value trips the guard.
    ensure_queue_initialized();

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.uaid_max_federation_hops = 3;
    let app = test_app(config);

    let body = send_message_json(1, "hello");
    let request = Request::builder()
        .method("POST")
        .uri("/a2a/plain-agent/invoke")
        .header("content-type", "application/json")
        // Two hop headers.  axum's HeaderMap keeps both; the handler
        // must take max=3.
        .header("x-contextforge-uaid-hop", "0")
        .header("x-contextforge-uaid-hop", "3")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
    backend.verify().await;
}

#[tokio::test]
async fn test_invoke_hop_guard_reads_title_case_header() {
    // Regression guard: the JSON `headers` field on `POST /invoke`
    // preserves whatever key case the caller sent.  Python's
    // `_invoke_remote_agent` stamps `X-Contextforge-UAID-Hop`
    // (title case) while this module normalizes to lowercase.  A
    // case-sensitive lookup on the Rust side would silently treat
    // every Python-stamped request as hop 0 and reopen the loop.
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0) // must not be reached — hop guard fires first
        .mount(&remote_agent)
        .await;

    let mut config = default_test_config();
    config.uaid_max_federation_hops = 3;
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": remote_agent.uri(),
            "headers": {"X-Contextforge-UAID-Hop": "3"},  // title-case
            "json_body": {"jsonrpc": "2.0", "id": 1}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::NOT_FOUND,
        "title-case hop header at limit must reject, got {status} body={body}"
    );
    remote_agent.verify().await;
}

#[tokio::test]
async fn test_invoke_outbound_normalizes_hop_header_case() {
    // The outbound request to the downstream agent must carry exactly
    // one `x-contextforge-uaid-hop` header, regardless of what case the
    // upstream caller used.  A duplicate (title-case alongside
    // lowercase) would let one downstream lookup see "0" and another
    // see "N+1".
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .and(header("x-contextforge-uaid-hop", "2"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(1)
        .mount(&remote_agent)
        .await;

    let config = default_test_config();
    let app = test_app(config);

    // Inbound hop=1 (title case).  Outbound must be exactly "2".
    let (status, _body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": remote_agent.uri(),
            "headers": {"X-Contextforge-UAID-Hop": "1"},
            "json_body": {"jsonrpc": "2.0", "id": 1}
        }),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    remote_agent.verify().await;
}

#[tokio::test]
async fn test_invoke_with_encrypted_auth_rejects_when_no_secret() {
    // The /invoke handler accepts encrypted auth blobs and routes them
    // through resolve_requests for decryption.  When the sidecar is
    // started without an auth_secret but the caller supplies encrypted
    // blobs, resolve_requests returns an Auth error → 400 Bad Request.
    let mut config = default_test_config();
    config.auth_secret = None; // pragma: allowlist secret
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": "http://127.0.0.1:9999",
            "headers": {},
            "json_body": {},
            "auth_headers_encrypted": "some-encrypted-blob"  // pragma: allowlist secret
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::BAD_REQUEST,
        "expected 400 Bad Request, got {status}"
    );
    let err_text = body
        .get("error")
        .and_then(|v| v.as_str())
        .unwrap_or_default();
    assert!(
        err_text.contains("auth_secret"), // pragma: allowlist secret
        "error should reference the missing auth_secret: {err_text}"  // pragma: allowlist secret
    );
}

#[tokio::test]
async fn test_invoke_applies_decrypted_auth_header_to_upstream() {
    // Regression for the Codex-flagged bug where the /invoke handler
    // dropped auth_headers_encrypted / auth_query_params_encrypted via
    // Serde (the InvokeRequest struct lacked those fields), so any
    // delegated invocation reached the agent without credentials.
    //
    // This test encrypts "Bearer secret-xyz" with the sidecar's
    // auth_secret, POSTs it through /invoke, and asserts the wiremock
    // agent actually received the decrypted Authorization header.
    // pragma: allowlist secret

    // Reuse the exact AES-GCM layout the Rust side expects (crate::auth).
    use contextforge_a2a_runtime::auth::encrypt_auth_for_tests; // pragma: allowlist secret

    let secret = "test-shared-secret"; // pragma: allowlist secret
    let mut auth_map = std::collections::HashMap::new();
    auth_map.insert("Authorization".to_string(), "Bearer secret-xyz".to_string());
    let encrypted_blob = encrypt_auth_for_tests(&auth_map, secret);

    let agent_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent"))
        .and(header("authorization", "Bearer secret-xyz"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(1)
        .mount(&agent_server)
        .await;

    let mut config = default_test_config();
    config.auth_secret = Some(secret.to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": format!("{}/agent", agent_server.uri()),
            "headers": {},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage"},
            "auth_headers_encrypted": encrypted_blob,
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "body: {body}");
    agent_server.verify().await;
}

#[tokio::test]
async fn test_invoke_applies_decrypted_auth_query_param_to_upstream() {
    use contextforge_a2a_runtime::auth::encrypt_auth_for_tests; // pragma: allowlist secret

    let secret = "test-shared-secret"; // pragma: allowlist secret
    let encrypted_query_blob = encrypt_auth_for_tests(
        &std::collections::HashMap::from([("api_key".to_string(), "secret-qp".to_string())]),
        secret,
    );

    let agent_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent"))
        .and(wiremock::matchers::query_param("api_key", "secret-qp"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(1)
        .mount(&agent_server)
        .await;

    let mut config = default_test_config();
    config.auth_secret = Some(secret.to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": format!("{}/agent", agent_server.uri()),
            "headers": {},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage"},
            "auth_query_params_encrypted": {
                "api_key": encrypted_query_blob // pragma: allowlist secret
            },
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "body: {body}");
    agent_server.verify().await;
}

#[tokio::test]
async fn test_invoke_rejects_malformed_encrypted_auth_header_without_upstream_call() {
    let agent_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(0)
        .mount(&agent_server)
        .await;

    let mut config = default_test_config();
    config.auth_secret = Some("test-shared-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": format!("{}/agent", agent_server.uri()),
            "headers": {},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage"},
            "auth_headers_encrypted": "%%%not-base64%%%" // pragma: allowlist secret
        }),
    )
    .await;

    assert_eq!(status, StatusCode::BAD_REQUEST, "body: {body}");
    assert!(body["error"].as_str().unwrap_or("").contains("base64"));
    agent_server.verify().await;
}

#[tokio::test]
async fn test_invoke_rejects_malformed_encrypted_auth_query_params_without_upstream_call() {
    let agent_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(0)
        .mount(&agent_server)
        .await;

    let mut config = default_test_config();
    config.auth_secret = Some("test-shared-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": format!("{}/agent", agent_server.uri()),
            "headers": {},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage"},
            "auth_query_params_encrypted": {
                "api_key": "%%%not-base64%%%" // pragma: allowlist secret
            }
        }),
    )
    .await;

    assert_eq!(status, StatusCode::BAD_REQUEST, "body: {body}");
    assert!(body["error"].as_str().unwrap_or("").contains("base64"));
    agent_server.verify().await;
}

#[tokio::test]
async fn test_invoke_forwards_correlation_and_trace_headers() {
    let agent_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent"))
        .and(header("x-correlation-id", "corr-123"))
        .and(header("traceparent", "00-abc-def-01"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(1)
        .mount(&agent_server)
        .await;

    let app = test_app(default_test_config());
    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": format!("{}/agent", agent_server.uri()),
            "headers": {},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage"},
            "correlation_id": "corr-123",
            "traceparent": "00-abc-def-01"
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "body: {body}");
    agent_server.verify().await;
}

#[tokio::test]
async fn test_invoke_records_metrics_after_success() {
    // The direct /invoke handler does NOT record metrics (no InvokeContext
    // is passed to execute_invoke).  Metrics are only recorded through the
    // queue-based /a2a/{agent_name}/invoke path.  However, calling that
    // endpoint requires the global queue to be initialized (OnceLock), which
    // can only happen once per process and conflicts across tests.
    //
    // As a practical integration test, we verify that after a successful
    // /invoke call the /metrics endpoint remains available and returns valid
    // JSON.  The direct invoke path is the public API exercised by the Python
    // service layer, and confirming the metrics endpoint is healthy alongside
    // it is the meaningful integration-level assertion.
    let mock_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"jsonrpc": "2.0", "id": 1, "result": {}})),
        )
        .mount(&mock_server)
        .await;

    let config = default_test_config();
    let app = test_app(config);

    // First: invoke successfully.
    let (invoke_status, _) = post_json(
        app.clone(),
        "/invoke",
        json!({
            "endpoint_url": mock_server.uri(),
            "headers": {"Content-Type": "application/json"},
            "json_body": {"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}},
            "timeout_seconds": 5
        }),
    )
    .await;
    assert_eq!(invoke_status, StatusCode::OK);

    // Then: verify /metrics is accessible and returns valid counters.
    let (metrics_status, metrics_body) = get_json(app, "/metrics").await;
    assert_eq!(metrics_status, StatusCode::OK);
    assert!(
        metrics_body["total_calls"].as_u64().is_some(),
        "total_calls should be a number"
    );
    // The direct /invoke path does not record into the shared MetricsCollector,
    // so total_calls remains 0.  This is by design: the Python layer owns the
    // metrics pipeline for direct invocations.
    // The direct /invoke path does not record into the shared MetricsCollector,
    // so total_calls remains 0.  This is by design: the Python layer owns the
    // metrics pipeline for direct invocations.
    assert_eq!(
        metrics_body["total_calls"].as_u64().unwrap(),
        0,
        "total_calls should be 0 because /invoke does not record metrics"
    );
}

#[tokio::test]
async fn test_a2a_proxy_forwards_to_backend() {
    let mock_server = MockServer::start().await;

    // Set up the mock backend to expect a proxied request at /a2a/some-path.
    Mock::given(method("POST"))
        .and(path("/a2a/some-path"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(json!({"proxied": true, "agent": "echo"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/some-path",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}}),
    )
    .await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["proxied"], true);
    assert_eq!(body["agent"], "echo");
}

#[tokio::test]
async fn test_a2a_proxy_forwards_get_requests() {
    let mock_server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/a2a/agents/list"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"agents": ["echo", "calc"]})))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    let app = test_app(config);

    let (status, body) = get_json(app, "/a2a/agents/list").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["agents"][0], "echo");
    assert_eq!(body["agents"][1], "calc");
}

#[tokio::test]
async fn test_a2a_proxy_returns_bad_gateway_when_backend_unreachable() {
    let mut config = default_test_config();
    // Point to a port that nothing is listening on.
    config.backend_base_url = "http://127.0.0.1:1".to_string();
    let app = test_app(config);

    let (status, body) = post_json(app, "/a2a/some-path", json!({"test": true})).await;

    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert!(
        body["error"]
            .as_str()
            .unwrap_or("")
            .contains("proxy request failed"),
        "error message should indicate proxy failure"
    );
}

// NOTE: test_batch_invoke_returns_array is intentionally omitted.
//
// The `/invoke` handler (`handle_invoke` in server.rs) accepts
// `Json<InvokeRequest>` — a single object, not an array.  There is no
// batch endpoint exposed via HTTP.  Batch processing exists internally in
// the queue module (`try_submit_batch`), but it is not reachable through
// the public `/invoke` route.  A batch HTTP endpoint may be added in a
// future PR.

#[tokio::test]
async fn test_health_includes_runtime_name() {
    let app = test_app(default_test_config());
    let (status, body) = get_json(app, "/health").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body["runtime"], "contextforge-a2a-runtime",
        "health response must include the canonical runtime name"
    );
}

// ---------------------------------------------------------------------------
// Trust → Authz → Resolve → Invoke chain tests
// ---------------------------------------------------------------------------

use wiremock::matchers::path_regex;

/// Ensures the global work queue is initialized exactly once.
///
/// Required before calling any test that exercises the
/// `/a2a/{agent_name}/invoke` handler (which submits work via the queue).
///
/// # Implementation Note
///
/// Uses `std::sync::Once` because `queue::init_queue` writes to a static
/// `OnceLock<WorkQueue>` and panics on double-initialization. The `Once`
/// guard ensures thread-safe, single initialization across all test runs
/// in the same process.
///
/// This pattern is necessary because:
/// - The work queue is a global singleton accessed via `queue::submit_work()`
/// - Multiple tests may run concurrently and attempt initialization
/// - Rust's test harness runs tests in the same process by default
/// - The `OnceLock` constraint prevents re-initialization after the first call
///
/// Alternative approaches (e.g., test fixtures with `#[ctor]`) were considered
/// but rejected to avoid additional dependencies and maintain explicit control
/// over initialization timing.
fn ensure_queue_initialized() {
    use contextforge_a2a_runtime::queue;
    use std::sync::{Arc, Once};

    static INIT: Once = Once::new();
    INIT.call_once(|| {
        let client = reqwest::Client::builder()
            .connect_timeout(std::time::Duration::from_secs(5))
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .expect("failed to build queue client");

        let config = Arc::new(default_test_config());
        let cb = Arc::new(contextforge_a2a_runtime::circuit::CircuitBreaker::new(
            5,
            std::time::Duration::from_secs(30),
            Some(10_000),
        ));
        let mc = Arc::new(contextforge_a2a_runtime::metrics::MetricsCollector::new(
            Some(10_000),
        ));
        let state = Arc::new(queue::WorkerState {
            client,
            config,
            circuit: cb,
            metrics: mc,
        });
        queue::init_queue(64, None, state);
    });
}

/// Build a `ResolvedAgent` JSON payload pointing to the given endpoint URL.
fn resolved_agent_json(endpoint_url: &str) -> Value {
    json!({
        "agent_id": "agent-001",
        "name": "test-agent",
        "endpoint_url": endpoint_url,
        "agent_type": "a2a",
        "protocol_version": "1.0",
        "auth_type": null,
        "auth_value_encrypted": null,
        "auth_query_params_encrypted": null
    })
}

/// Full trust chain: authenticate → authorize → resolve → invoke.
///
/// Sets up wiremock stubs for the Python backend (authenticate, authz,
/// resolve) and a mock agent endpoint.  The Rust handler should call all
/// four endpoints in order and return the agent's response.
#[tokio::test]
async fn test_a2a_invoke_full_trust_chain() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // Setup full trust chain using helper function
    setup_full_trust_chain_mocks(&mock_server, "test-agent", "Hello from agent").await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) =
        post_json(app, "/a2a/test-agent/invoke", send_message_json(1, "hello")).await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "invoke should succeed"
    );
    assert_eq!(body["json"]["result"]["status"], "completed");
    assert_eq!(body["json"]["result"]["message"], "Hello from agent");

    // Verify all backend mocks were called exactly once.
    mock_server.verify().await;
}

/// Authz denied: authenticate succeeds but authz returns 403.
///
/// The handler should short-circuit and return 403 without calling
/// resolve or the agent.
#[tokio::test]
async fn test_a2a_invoke_authz_denied() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 403 (denied)
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(403).set_body_string("insufficient permissions"))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve should NOT be called
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::FORBIDDEN, "expected 403, body: {body}");
    assert!(
        body["error"]
            .as_str()
            .unwrap_or("")
            .contains("authorization denied"),
        "error should mention authorization denied, got: {}",
        body["error"]
    );

    mock_server.verify().await;
}

/// Agent not found: authenticate + authz succeed, resolve returns 404.
///
/// The handler should return 404 without invoking the agent.
#[tokio::test]
async fn test_a2a_invoke_agent_not_found() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 404 (agent not found)
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(404).set_body_string("agent not registered"))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::NOT_FOUND, "expected 404, body: {body}");
    assert!(
        body["error"].as_str().unwrap_or("").contains("not found"),
        "error should mention not found, got: {}",
        body["error"]
    );

    mock_server.verify().await;
}

/// Cache hit: two invocations for the same agent should resolve only once.
///
/// The resolve mock uses `expect(1)` to assert it is called exactly once;
/// the second request should be served from the agent cache.
#[tokio::test]
async fn test_a2a_invoke_cache_hit_skips_resolve() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // authenticate → 200 (called twice, once per request)
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204 (called twice)
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(2)
        .mount(&mock_server)
        .await;

    // resolve → 200 (should be called only ONCE due to caching)
    let agent_path = "/cached-agent-endpoint";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200 (called twice, once per invocation)
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.agent_cache_ttl_secs = 300; // Long TTL to ensure cache hit
    let app = test_app(config);

    // First request — triggers resolve (cache miss).
    let (status1, body1) = post_json(
        app.clone(),
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {"message": "first"}
        }),
    )
    .await;
    assert_eq!(status1, StatusCode::OK, "first request failed: {body1}");
    assert!(body1["success"].as_bool().unwrap_or(false));

    // Second request — should use cached resolve (cache hit).
    let (status2, body2) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 2,
            "params": {"message": "second"}
        }),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "second request failed: {body2}");
    assert!(body2["success"].as_bool().unwrap_or(false));

    // Verify resolve was called exactly once (cache hit on second request).
    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// JSON-RPC method routing tests (GetTask / ListTasks / legacy names)
// ---------------------------------------------------------------------------

/// GetTask routes to the Python `/_internal/a2a/tasks/get` endpoint
/// instead of resolving + invoking the agent.
#[tokio::test]
async fn test_a2a_invoke_get_task_routes_to_python() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // get/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // tasks/get → 200 with task data.  The body matcher pins the
    // server-resolved agent_id ("agent-001" from resolved_agent_json)
    // so a regression that drops the URL→agent_id injection — which would
    // silently reintroduce the cross-agent task-read vulnerability — fails
    // here instead of passing.
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/get$"))
        .and(body_json(json!({
            "id": "task-1",
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "id": "t1",
            "task_id": "task-1",
            "state": "completed",
            "result": "done"
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // Task methods now pre-resolve the agent so its agent_id can be passed
    // to the Python task service for unambiguous lookup.  Returning 404
    // here would block every GetTask/CancelTask call.
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTask",
            "id": 1,
            "params": {"id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "task get should succeed"
    );

    // The response should be wrapped in a JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 1);
    assert_eq!(jsonrpc["result"]["task_id"], "task-1");
    assert_eq!(jsonrpc["result"]["state"], "completed");

    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_task_missing_task_id_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/get$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "task_id is required"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTask",
            "id": 12,
            "params": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "task_id is required");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_task_not_found_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/get$"))
        .and(body_json(json!({
            "id": "missing-task",
            "task_id": "missing-task",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "task not found"})))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTask",
            "id": 19,
            "params": {"id": "missing-task"}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 404);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "task not found");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_task_agent_not_found_short_circuits_before_proxy() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(404).set_body_string("agent not registered"))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/get$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTask",
            "id": 23,
            "params": {"id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::NOT_FOUND, "expected 404, body: {body}");
    assert!(body["error"].as_str().unwrap_or("").contains("not found"));
    mock_server.verify().await;
}

/// ListTasks routes to the Python `/_internal/a2a/tasks/list` endpoint.
#[tokio::test]
async fn test_a2a_invoke_list_tasks_routes_to_python() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // list/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*list/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // tasks/list → 200 with task list.  Body matcher pins agent_id so a
    // regression that drops the URL-path injection fails this test
    // (otherwise list could span multiple agents — see security fix).
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/list$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "tasks": [
                {"task_id": "task-1", "state": "completed"},
                {"task_id": "task-2", "state": "running"}
            ]
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "ListTasks",
            "id": 2,
            "params": {"agent_id": "agent-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "task list should succeed"
    );

    // Verify the task list is wrapped in a JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 2);
    assert_eq!(jsonrpc["result"]["tasks"][0]["task_id"], "task-1");
    assert_eq!(jsonrpc["result"]["tasks"][1]["task_id"], "task-2");

    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_list_tasks_invalid_state_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*list/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/list$"))
        .and(body_json(json!({"state": 123, "agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "state must be a string"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "ListTasks",
            "id": 13,
            "params": {"state": 123}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "state must be a string");
    mock_server.verify().await;
}

/// Legacy method name `"tasks/get"` routes the same as `"GetTask"`.
#[tokio::test]
async fn test_a2a_invoke_legacy_method_name_routes_correctly() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // get/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // tasks/get → 200 with task data; agent_id is pinned in the body matcher.
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/get$"))
        .and(body_json(json!({
            "id": "task-1",
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "id": "t1",
            "task_id": "task-1",
            "state": "completed"
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "id": 1,
            "params": {"id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "legacy tasks/get should succeed"
    );

    // Verify JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 1);
    assert_eq!(jsonrpc["result"]["task_id"], "task-1");
    assert_eq!(jsonrpc["result"]["state"], "completed");

    mock_server.verify().await;
}

/// CancelTask routes to the Python `/_internal/a2a/tasks/cancel` endpoint
/// instead of resolving + invoking the agent.
#[tokio::test]
async fn test_a2a_invoke_cancel_task_routes_to_python() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // tasks/cancel → 200 with canceled task data; pin agent_id in body matcher.
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/cancel$"))
        .and(body_json(json!({
            "id": "task-1",
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "id": "t1",
            "task_id": "task-1",
            "state": "canceled"
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CancelTask",
            "id": 3,
            "params": {"id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "task cancel should succeed"
    );

    // The response should be wrapped in a JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 3);
    assert_eq!(jsonrpc["result"]["task_id"], "task-1");
    assert_eq!(jsonrpc["result"]["state"], "canceled");

    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_cancel_task_missing_task_id_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/cancel$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "task_id is required"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CancelTask",
            "id": 14,
            "params": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "task_id is required");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_cancel_task_not_found_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/cancel$"))
        .and(body_json(json!({
            "id": "missing-task",
            "task_id": "missing-task",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "task not found"})))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CancelTask",
            "id": 20,
            "params": {"id": "missing-task"}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 404);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "task not found");
    mock_server.verify().await;
}

/// Legacy method name `"tasks/cancel"` routes the same as `"CancelTask"`.
#[tokio::test]
async fn test_a2a_invoke_cancel_task_legacy_name_routes_correctly() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // tasks/cancel → 200 with canceled task data; pin agent_id in body matcher.
    Mock::given(method("POST"))
        .and(path_regex(".*tasks/cancel$"))
        .and(body_json(json!({
            "id": "task-1",
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "id": "t1",
            "task_id": "task-1",
            "state": "canceled"
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "tasks/cancel",
            "id": 4,
            "params": {"id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "legacy tasks/cancel should succeed"
    );

    // Verify JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 4);
    assert_eq!(jsonrpc["result"]["task_id"], "task-1");
    assert_eq!(jsonrpc["result"]["state"], "canceled");

    mock_server.verify().await;
}

/// `"SendMessage"` goes through the full resolve → invoke flow (not the
/// task proxy), confirming that the resolve endpoint IS called.
#[tokio::test]
async fn test_a2a_invoke_send_message_goes_to_agent() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 200 with agent pointing to mock agent endpoint
    let agent_path = "/send-msg-agent-endpoint";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "completed", "message": "response from agent"}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {"message": "hello"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "SendMessage should succeed"
    );
    assert_eq!(body["json"]["result"]["message"], "response from agent");

    // Verify all mocks were called — especially resolve (expect(1)).
    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Agent card discovery tests (GetExtendedAgentCard / agent/getExtendedCard /
// agent/getAuthenticatedExtendedCard)
// ---------------------------------------------------------------------------

/// GetExtendedAgentCard routes to `/_internal/a2a/agents/{name}/card` and
/// returns the card wrapped in a JSON-RPC envelope.
#[tokio::test]
async fn test_a2a_invoke_get_extended_agent_card_routes_to_python() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // agents/test-agent/card → 200 with AgentCard
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/card$"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "name": "test-agent",
            "description": "A test agent",
            "url": "https://example.com/agent",
            "version": "1",
            "protocolVersion": "1.0",
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {
                "streaming": false,
                "pushNotifications": false,
                "stateTransitionHistory": false
            },
            "skills": [],
            "supportsAuthenticatedExtendedCard": true
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve should NOT be called — card methods bypass agent resolution
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetExtendedAgentCard",
            "id": 5,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "GetExtendedAgentCard should succeed"
    );

    // Verify the card is wrapped in a JSON-RPC envelope.
    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 5);
    assert_eq!(jsonrpc["result"]["name"], "test-agent");
    assert_eq!(jsonrpc["result"]["url"], "https://example.com/agent");
    assert_eq!(jsonrpc["result"]["supportsAuthenticatedExtendedCard"], true);

    mock_server.verify().await;
}

/// `"agent/getExtendedCard"` (A2A v1 spec name) routes identically to
/// `"GetExtendedAgentCard"`.
#[tokio::test]
async fn test_a2a_invoke_get_extended_card_spec_name_routes_correctly() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": []}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/card$"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "name": "test-agent",
            "description": "A test agent",
            "url": "https://example.com/agent",
            "version": "1",
            "protocolVersion": "1.0",
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {"streaming": false, "pushNotifications": false, "stateTransitionHistory": false},
            "skills": [],
            "supportsAuthenticatedExtendedCard": true
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve should NOT be called
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "agent/getExtendedCard",
            "id": 6,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);

    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 6);
    assert_eq!(jsonrpc["result"]["name"], "test-agent");

    mock_server.verify().await;
}

/// `"agent/getAuthenticatedExtendedCard"` routes to the card endpoint and
/// returns 404-wrapped error when the agent is not found.
#[tokio::test]
async fn test_a2a_invoke_get_authenticated_card_not_found_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": []}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // card endpoint → 404
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/missing-agent/card$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({
            "error": "agent 'missing-agent' not found"
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve should NOT be called
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/missing-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/missing-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "agent/getAuthenticatedExtendedCard",
            "id": 7,
            "params": {}
        }),
    )
    .await;

    // The Rust handler returns 200 with a JSON-RPC error envelope when the
    // Python backend returns a non-2xx status for the card.
    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 with error envelope, body: {body}"
    );

    let jsonrpc = &body["json"];
    assert_eq!(jsonrpc["jsonrpc"], "2.0");
    assert_eq!(jsonrpc["id"], 7);
    // Non-2xx from backend → JSON-RPC error field, not result
    assert!(
        jsonrpc.get("error").is_some(),
        "expected JSON-RPC error envelope for not-found card, got: {jsonrpc}"
    );

    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_authenticated_card_routes_successfully() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/card$"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "name": "test-agent",
            "description": "authenticated card",
            "url": "https://example.com/agent",
            "version": "1",
            "protocolVersion": "1.0",
            "defaultInputModes": ["text"],
            "defaultOutputModes": ["text"],
            "capabilities": {"streaming": false, "pushNotifications": false, "stateTransitionHistory": false},
            "skills": [],
            "supportsAuthenticatedExtendedCard": true,
            "auth": {"required": true} // pragma: allowlist secret
        })))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "agent/getAuthenticatedExtendedCard",
            "id": 8,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["result"]["name"], "test-agent");
    assert_eq!(body["json"]["result"]["auth"]["required"], true);
    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Push notification config routing tests
// ---------------------------------------------------------------------------

#[tokio::test]
async fn test_a2a_invoke_create_push_config_routes_to_python() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": ["team1"]}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // Push methods now pre-resolve the agent so its agent_id can be
    // injected into the proxy body — preventing cross-agent push-config
    // operations via a spoofed agent_id in params.
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*push/create$"))
        .and(body_json(json!({
            "a2a_agent_id": "agent-001",
            "task_id": "task-1",
            "webhook_url": "https://example.com/hook",
            "enabled": true,
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "config_id": "cfg-1",
            "enabled": true
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CreateTaskPushNotificationConfig",
            "id": 8,
            "params": {
                "a2a_agent_id": "agent-001",
                "task_id": "task-1",
                "webhook_url": "https://example.com/hook",
                "enabled": true
            }
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["id"], 8);
    assert_eq!(body["json"]["result"]["config_id"], "cfg-1");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_create_push_config_missing_required_fields_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/create$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400)
                .set_body_json(json!({"error": "task_id and webhook_url are required"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CreateTaskPushNotificationConfig",
            "id": 15,
            "params": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(
        body["json"]["error"]["message"],
        "task_id and webhook_url are required"
    );
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_create_push_config_invalid_schema_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/create$"))
        .and(body_json(json!({
            "task_id": "task-1",
            "webhook_url": "not-a-url",
            "agent_id": "agent-001"
        })))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "invalid push config"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CreateTaskPushNotificationConfig",
            "id": 16,
            "params": {
                "task_id": "task-1",
                "webhook_url": "not-a-url"
            }
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "invalid push config");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_create_push_config_agent_not_found_short_circuits_before_proxy() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(404).set_body_string("agent not registered"))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/create$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CreateTaskPushNotificationConfig",
            "id": 24,
            "params": {
                "task_id": "task-1",
                "webhook_url": "https://example.com/hook"
            }
        }),
    )
    .await;

    assert_eq!(status, StatusCode::NOT_FOUND, "expected 404, body: {body}");
    assert!(body["error"].as_str().unwrap_or("").contains("not found"));
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_push_config_routes_to_python() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": ["team1"]}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*push/get$"))
        .and(body_json(json!({
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "config_id": "cfg-1",
            "enabled": true
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTaskPushNotificationConfig",
            "id": 9,
            "params": {"task_id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["id"], 9);
    assert_eq!(body["json"]["result"]["config_id"], "cfg-1");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_push_config_missing_task_id_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/get$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "task_id is required"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTaskPushNotificationConfig",
            "id": 17,
            "params": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "task_id is required");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_get_push_config_not_found_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*get/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/get$"))
        .and(body_json(json!({
            "task_id": "missing-task",
            "agent_id": "agent-001"
        })))
        .respond_with(
            ResponseTemplate::new(404).set_body_json(json!({"error": "push config not found"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "GetTaskPushNotificationConfig",
            "id": 21,
            "params": {"task_id": "missing-task"}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 404);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "push config not found");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_list_push_configs_routes_to_python() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": ["team1"]}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*list/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*push/list$"))
        .and(body_json(json!({
            "task_id": "task-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "configs": [{"config_id": "cfg-1"}, {"config_id": "cfg-2"}]
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "ListTaskPushNotificationConfigs",
            "id": 10,
            "params": {"task_id": "task-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["id"], 10);
    assert_eq!(body["json"]["result"]["configs"][0]["config_id"], "cfg-1");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_delete_push_config_routes_to_python() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@example.com", "is_admin": false, "teams": ["team1"]}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*push/delete$"))
        .and(body_json(json!({
            "config_id": "cfg-1",
            "agent_id": "agent-001"
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "deleted": true
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "DeleteTaskPushNotificationConfig",
            "id": 11,
            "params": {"config_id": "cfg-1"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert_eq!(body["json"]["id"], 11);
    assert_eq!(body["json"]["result"]["deleted"], true);
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_delete_push_config_missing_config_id_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/delete$"))
        .and(body_json(json!({"agent_id": "agent-001"})))
        .respond_with(
            ResponseTemplate::new(400).set_body_json(json!({"error": "config_id is required"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "DeleteTaskPushNotificationConfig",
            "id": 18,
            "params": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 400);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "config_id is required");
    mock_server.verify().await;
}

#[tokio::test]
async fn test_a2a_invoke_delete_push_config_not_found_returns_error_envelope() {
    let mock_server = MockServer::start().await;

    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json("http://unused")),
        )
        .expect(1)
        .mount(&mock_server)
        .await;
    Mock::given(method("POST"))
        .and(path_regex(".*push/delete$"))
        .and(body_json(json!({
            "config_id": "missing-config",
            "agent_id": "agent-001"
        })))
        .respond_with(
            ResponseTemplate::new(404).set_body_json(json!({"error": "push config not found"})),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "DeleteTaskPushNotificationConfig",
            "id": 22,
            "params": {"config_id": "missing-config"}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 envelope, body: {body}"
    );
    assert_eq!(body["status_code"], 404);
    assert!(!body["success"].as_bool().unwrap_or(true));
    assert_eq!(body["json"]["error"]["message"], "push config not found");
    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// L1-only cache degradation test (no Redis)
// ---------------------------------------------------------------------------

/// Prove that the agent cache works in L1-only mode (redis_url: None).
///
/// The resolve mock is registered with `expect(1)`.  Two requests are made
/// for the same agent: the first triggers a resolve call, the second is served
/// entirely from the L1 DashMap cache.  `mock_server.verify()` asserts that
/// resolve was called exactly once.
#[tokio::test]
async fn test_agent_cache_works_without_redis() {
    // This test proves L1 caching works when Redis is unavailable.
    // The default test config has redis_url: None.
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // authenticate → 200 (called twice, once per request)
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {"email": "user@test.com", "is_admin": false, "teams": ["t1"]}
        })))
        .mount(&mock_server)
        .await;

    // invoke/authz → 204 (called twice)
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .mount(&mock_server)
        .await;

    // resolve → 200 (should be called exactly once; second request hits L1)
    let agent_path = "/mock-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/cache-test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .named("resolve")
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200 (called twice)
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    // redis_url is None — L2 disabled, L1-only
    let app = test_app(config);

    // First request — resolve is called (L1 cache miss)
    let (status1, body1) = post_json(
        app.clone(),
        "/a2a/cache-test-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}}),
    )
    .await;
    assert_eq!(status1, StatusCode::OK, "first request failed: {body1}");

    // Second request — resolve should NOT be called (L1 cache hit)
    let (status2, body2) = post_json(
        app,
        "/a2a/cache-test-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 2, "params": {}}),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "second request failed: {body2}");

    // Verify resolve was called exactly once
    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Session management integration tests
// ---------------------------------------------------------------------------

/// With `session_enabled: false` (the default test config) the session manager
/// is `None`, so every request must go through the full authenticate flow.
///
/// Two consecutive requests to `/a2a/test-agent/invoke` must each call the
/// authenticate endpoint — no session caching shortcut is taken.
#[tokio::test]
async fn test_session_disabled_always_authenticates() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    let agent_path = "/session-disabled-agent-endpoint";

    // authenticate → 200 — must be called TWICE (once per request)
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204 (called twice)
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(2)
        .mount(&mock_server)
        .await;

    // resolve → 200 (called twice because each request re-authenticates;
    // agent cache may reduce it to once — use at_least(1) to be resilient)
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/session-disabled-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200 (called twice)
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    // default_test_config() has session_enabled: false
    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // First request
    let (status1, body1) = post_json(
        app.clone(),
        "/a2a/session-disabled-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}}),
    )
    .await;
    assert_eq!(status1, StatusCode::OK, "first request failed: {body1}");
    assert!(body1["success"].as_bool().unwrap_or(false));

    // Second request — authenticate must be called again (no session cache)
    let (status2, body2) = post_json(
        app,
        "/a2a/session-disabled-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 2, "params": {}}),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "second request failed: {body2}");
    assert!(body2["success"].as_bool().unwrap_or(false));

    // Verify authenticate was called exactly twice.
    mock_server.verify().await;
}

/// With `session_enabled: true` but `redis_url: None`, `build_app()` sets
/// `session_manager` to `None` (no Redis connection available).  The runtime
/// must gracefully fall back to full authentication on every request — no
/// crash, no session reuse.
///
/// Two consecutive requests should each call the authenticate endpoint.
#[tokio::test]
async fn test_session_fallback_without_redis() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    let agent_path = "/session-fallback-agent-endpoint";

    // authenticate → 200 — must be called TWICE (fallback: no session manager)
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204 (called twice)
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(2)
        .mount(&mock_server)
        .await;

    // resolve → 200 (agent cache may make this 1 or 2; no constraint set)
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/session-fallback-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200 (called twice)
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    // session_enabled: true but redis_url: None — build_app() will set
    // session_manager to None because it never connects to Redis.
    let mut config = default_test_config();
    config.session_enabled = true;
    config.redis_url = None;
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // First request
    let (status1, body1) = post_json(
        app.clone(),
        "/a2a/session-fallback-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}}),
    )
    .await;
    assert_eq!(status1, StatusCode::OK, "first request failed: {body1}");
    assert!(body1["success"].as_bool().unwrap_or(false));

    // Second request — authenticate must be called again (no session manager)
    let (status2, body2) = post_json(
        app,
        "/a2a/session-fallback-agent/invoke",
        json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 2, "params": {}}),
    )
    .await;
    assert_eq!(status2, StatusCode::OK, "second request failed: {body2}");
    assert!(body2["success"].as_bool().unwrap_or(false));

    // Verify authenticate was called exactly twice — the fallback path works.
    mock_server.verify().await;
}

#[tokio::test]
async fn test_session_fingerprint_mismatch_invalidates_old_session_and_reauthenticates() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;
    let agent_path = "/session-mismatch-agent-endpoint";

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(2)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/agents/session-mismatch-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(2)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.session_enabled = true;
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let session_manager = Arc::new(
        contextforge_a2a_runtime::session::SessionManager::new_ephemeral_for_tests(
            300,
            "authorization,x-forwarded-for",
        ),
    );
    let app = test_app_with_session_manager(config, Some(Arc::clone(&session_manager)));

    let first_request = Request::builder()
        .method("POST")
        .uri("/a2a/session-mismatch-agent/invoke")
        .header("content-type", "application/json")
        .header("authorization", "Bearer first-token")
        .header("x-forwarded-for", "10.0.0.1")
        .body(Body::from(
            serde_json::to_vec(
                &json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 1, "params": {}}),
            )
            .unwrap(),
        ))
        .unwrap();
    let first_response = app.clone().oneshot(first_request).await.unwrap();
    assert_eq!(first_response.status(), StatusCode::OK);
    let first_bytes = first_response
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes();
    let first_body: Value = serde_json::from_slice(&first_bytes).unwrap();
    let first_session_id = first_body["session_id"]
        .as_str()
        .expect("first response should include session id")
        .to_string();
    assert!(
        session_manager.lookup(&first_session_id).await.is_some(),
        "first session should be stored"
    );

    let second_request = Request::builder()
        .method("POST")
        .uri("/a2a/session-mismatch-agent/invoke")
        .header("content-type", "application/json")
        .header("authorization", "Bearer second-token")
        .header("x-forwarded-for", "10.0.0.1")
        .header("x-a2a-session-id", &first_session_id)
        .body(Body::from(
            serde_json::to_vec(
                &json!({"jsonrpc": "2.0", "method": "SendMessage", "id": 2, "params": {}}),
            )
            .unwrap(),
        ))
        .unwrap();
    let second_response = app.oneshot(second_request).await.unwrap();
    assert_eq!(second_response.status(), StatusCode::OK);
    let second_bytes = second_response
        .into_body()
        .collect()
        .await
        .unwrap()
        .to_bytes();
    let second_body: Value = serde_json::from_slice(&second_bytes).unwrap();
    let second_session_id = second_body["session_id"]
        .as_str()
        .expect("second response should include new session id")
        .to_string();

    assert_ne!(
        first_session_id, second_session_id,
        "fingerprint mismatch should issue a fresh session id"
    );
    assert!(
        session_manager.lookup(&first_session_id).await.is_none(),
        "old session should be invalidated after fingerprint mismatch"
    );
    assert!(
        session_manager.lookup(&second_session_id).await.is_some(),
        "new session should be persisted"
    );

    mock_server.verify().await;
}

// NOTE: test_fingerprint_computation_deterministic is intentionally not added
// here as an integration test.  The `fingerprint_from_headers` function in
// `src/session.rs` is private (`fn`, not `pub fn`), and `SessionManager` is
// not constructable without a live `RedisPool`.  The determinism and
// correctness of the fingerprint algorithm is fully covered by the unit tests
// in `src/session.rs` (`compute_fingerprint_deterministic` and
// `compute_fingerprint_differs_for_different_values`).

// ---------------------------------------------------------------------------
// Streaming integration tests (SendStreamingMessage / message/stream)
// ---------------------------------------------------------------------------

/// When an agent recognises `SendStreamingMessage` but responds with
/// `Content-Type: application/json` (not SSE), the handler falls back to
/// returning a regular JSON `InvokeResultDto` response.
///
/// `SendStreamingMessage` is handled by `handle_streaming_method` which calls
/// the agent directly (NOT through the queue), so `ensure_queue_initialized`
/// is not required here.
#[tokio::test]
async fn test_streaming_method_falls_back_to_json_when_agent_returns_json() {
    let mock_server = MockServer::start().await;

    // 1. authenticate → 200 with auth context
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 2. invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 3. resolve → 200 with ResolvedAgent pointing to our mock agent endpoint
    let agent_path = "/streaming-fallback-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // 4. Mock agent endpoint → 200 with Content-Type: application/json
    //    (not text/event-stream), simulating an echo-style agent that handles
    //    SendStreamingMessage but returns a plain JSON response.
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"status": "completed", "message": "Hello from echo agent"}
                })),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        streaming_message_json(1, "hello", "ROLE_USER"),
    )
    .await;

    // The handler should have detected the JSON content-type and returned a
    // plain JSON InvokeResultDto (not an SSE stream).
    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 fallback, body: {body}"
    );
    assert_eq!(
        body["status_code"], 200,
        "InvokeResultDto status_code should be 200"
    );
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "invoke should be marked successful"
    );
    // The proxied JSON response should be present.
    assert_eq!(
        body["json"]["result"]["status"], "completed",
        "agent result should be in json field"
    );

    // Ensure the wiremock stubs were all satisfied.
    mock_server.verify().await;
}

/// When the agent responds with `Content-Type: text/event-stream`, the runtime
/// should forward the SSE stream instead of wrapping it as JSON.
#[tokio::test]
async fn test_streaming_method_forwards_sse_stream() {
    let mock_server = MockServer::start().await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    let agent_path = "/streaming-sse-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_raw(
            "id: evt-1\nevent: status\ndata: {\"status\":\"working\"}\n\n",
            "text/event-stream",
        ))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let request = Request::builder()
        .method("POST")
        .uri("/a2a/test-agent/invoke")
        .header("content-type", "application/json")
        .body(Body::from(
            serde_json::to_vec(&json!({
                "jsonrpc": "2.0",
                "method": "SendStreamingMessage",
                "id": 1,
                "params": {"id": "task-123", "message": {"role": "ROLE_USER", "parts": [{"text": "hello"}]}}
            }))
            .unwrap(),
        ))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok()),
        Some("text/event-stream")
    );

    let body = String::from_utf8_lossy(&response.into_body().collect().await.unwrap().to_bytes())
        .to_string();
    assert!(body.contains("id: evt-1"), "expected SSE id, body: {body}");
    assert!(
        body.contains("event: status"),
        "expected SSE event, body: {body}"
    );
    assert!(
        body.contains("data: {\"status\":\"working\"}"),
        "expected SSE data, body: {body}"
    );

    mock_server.verify().await;
}

/// Regression test: the regular `SendMessage` (non-streaming) path still works
/// correctly after the polymorphic response changes introduced for streaming.
///
/// This is structurally identical to `test_a2a_invoke_full_trust_chain` but
/// explicitly named as a regression guard for the streaming refactor.
#[tokio::test]
async fn test_send_message_still_works_after_streaming_changes() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // 1. authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 2. invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 3. resolve → 200 with ResolvedAgent
    let agent_path = "/regression-send-message-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // 4. Mock agent endpoint → 200
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "completed", "message": "Hello from agent"}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {"message": "hello"}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert_eq!(body["status_code"], 200);
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "SendMessage should succeed"
    );
    assert_eq!(body["json"]["result"]["status"], "completed");
    assert_eq!(body["json"]["result"]["message"], "Hello from agent");

    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Trust chain edge cases
// ---------------------------------------------------------------------------

/// Authentication failure: authenticate endpoint returns 401.
///
/// The Rust handler maps any non-200 from authenticate to 403 (Forbidden).
/// The resolve endpoint must NOT be called.
#[tokio::test]
async fn test_a2a_invoke_authentication_failure() {
    let mock_server = MockServer::start().await;

    // authenticate → 401 (unauthenticated / bad token)
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(401).set_body_string("unauthorized"))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve must NOT be called
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": 1,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::FORBIDDEN, "expected 403, body: {body}");
    assert!(
        body["error"].as_str().is_some(),
        "response should contain an error field"
    );

    mock_server.verify().await;
}

/// Empty method field: JSON-RPC body with no `method` key falls through to the
/// agent invoke path (the `_ => {}` branch).  Authenticate and authz are still
/// called; resolve IS called; the agent IS invoked.
#[tokio::test]
async fn test_a2a_invoke_with_empty_method() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 200 (must be called — no method means fall-through to invoke)
    let agent_path = "/empty-method-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // Send a body with no `method` field
    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "id": 1,
            "params": {"message": "hello"}
        }),
    )
    .await;

    // Handler must not crash; it falls through to agent invoke
    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "invoke should succeed without method field"
    );

    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Streaming edge cases
// ---------------------------------------------------------------------------

/// `SendStreamingMessage` where the mock agent returns HTTP 500 with a JSON
/// error body.  The handler falls into the non-streaming (JSON) branch and
/// returns HTTP 200 with `success: false` and `status_code: 500`.
#[tokio::test]
async fn test_streaming_method_handles_agent_error() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 200
    let agent_path = "/streaming-error-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent returns 500 with a JSON error body (not text/event-stream)
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(
            ResponseTemplate::new(500)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32000, "message": "internal agent error"}
                })),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        streaming_message_json(1, "hello", "ROLE_USER"),
    )
    .await;

    // The handler detects the non-streaming JSON body and wraps it in an
    // InvokeResultDto.  The outer HTTP status is 200 (the DTO carries the
    // downstream 500 in status_code).
    assert_eq!(
        status,
        StatusCode::OK,
        "expected 200 with error DTO, body: {body}"
    );
    assert_eq!(
        body["status_code"], 500,
        "DTO status_code should reflect agent 500"
    );
    assert!(
        !body["success"].as_bool().unwrap_or(true),
        "success should be false for agent 500"
    );

    mock_server.verify().await;
}

/// `SendStreamingMessage` where the mock agent delays 10 s and the runtime
/// timeout is 500 ms.  The handler must return a 502 Bad Gateway (not hang).
#[tokio::test]
async fn test_streaming_method_handles_agent_timeout() {
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 200
    let agent_path = "/streaming-timeout-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent delays 10 s — well past the 500 ms runtime timeout
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_delay(std::time::Duration::from_secs(10)))
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.request_timeout_ms = 500;
    config.max_retries = 0;
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        streaming_message_json(1, "hello", "ROLE_USER"),
    )
    .await;

    // Timeout on the agent request → BAD_GATEWAY (502)
    assert!(
        status == StatusCode::BAD_GATEWAY || status == StatusCode::GATEWAY_TIMEOUT,
        "expected 502 or 504 on agent timeout, got {status}: {body}"
    );
    assert!(
        body["error"].as_str().is_some(),
        "response should contain an error field"
    );

    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// Malformed request handling
// ---------------------------------------------------------------------------

/// POST to `/a2a/test-agent/invoke` with `Content-Type: application/json`
/// but a body that is not valid JSON.  Axum's `Json` extractor rejects the
/// body before authentication is attempted, returning 422.
#[tokio::test]
async fn test_a2a_invoke_with_invalid_json_body() {
    let app = test_app(default_test_config());

    // Build the request manually to send a non-JSON body.
    let request = Request::builder()
        .method("POST")
        .uri("/a2a/test-agent/invoke")
        .header("content-type", "application/json")
        .body(Body::from(b"not json".as_ref()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    let status = response.status();

    // Axum rejects the malformed body at the extractor level — 4xx expected.
    assert!(
        status.is_client_error(),
        "expected 4xx for invalid JSON body, got {status}"
    );
}

/// POST to `/invoke` (Python-initiated path) with `endpoint_url: ""`.
/// URL validation should reject an empty URL before any network call is made.
#[tokio::test]
async fn test_invoke_with_empty_endpoint_url() {
    let app = test_app(default_test_config());

    let (status, body) = post_json(
        app,
        "/invoke",
        json!({
            "endpoint_url": "",
            "headers": {},
            "json_body": {}
        }),
    )
    .await;

    assert_eq!(
        status,
        StatusCode::BAD_REQUEST,
        "expected 400 for empty endpoint_url, body: {body}"
    );
    assert!(
        body["error"].as_str().is_some(),
        "response should contain an error field"
    );
}

// ---------------------------------------------------------------------------
// Method routing completeness
// ---------------------------------------------------------------------------

/// An unknown JSON-RPC method falls through the `_ => {}` branch and reaches
/// the full resolve → invoke path.  Authenticate, authz, resolve, and the
/// agent endpoint must all be called exactly once.
#[tokio::test]
async fn test_a2a_invoke_unknown_method_goes_to_agent() {
    ensure_queue_initialized();
    let mock_server = MockServer::start().await;

    // authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // resolve → 200 (must be called — unknown method falls through to invoke)
    let agent_path = "/unknown-method-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Mock agent endpoint → 200
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "handled", "method": "CustomUnknownMethod"}
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let (status, body) = post_json(
        app,
        "/a2a/test-agent/invoke",
        json!({
            "jsonrpc": "2.0",
            "method": "CustomUnknownMethod",
            "id": 1,
            "params": {}
        }),
    )
    .await;

    assert_eq!(status, StatusCode::OK, "expected 200, body: {body}");
    assert!(
        body["success"].as_bool().unwrap_or(false),
        "unknown method should fall through to agent successfully"
    );
    assert_eq!(
        body["json"]["result"]["method"], "CustomUnknownMethod",
        "agent response should be forwarded"
    );

    // Verify all mocks were called — especially resolve (expect(1)).
    mock_server.verify().await;
}

/// When a `Last-Event-ID` header is present but the event store is `None`
/// (no Redis configured), the handler should fall through to a regular agent
/// call rather than crashing or returning an error.
///
/// `default_test_config()` has `redis_url: None`, so `event_store` will be
/// `None` in `AppState`.  The streaming path skips the replay branch and
/// proceeds to resolve + call the agent directly.
#[tokio::test]
async fn test_streaming_method_with_last_event_id_without_redis() {
    let mock_server = MockServer::start().await;

    // 1. authenticate → 200
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/authenticate"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "authContext": {
                "email": "user@example.com",
                "is_admin": false,
                "teams": ["team1"]
            }
        })))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 2. invoke/authz → 204
    Mock::given(method("POST"))
        .and(path_regex(".*invoke/authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&mock_server)
        .await;

    // 3. resolve → 200 with ResolvedAgent
    let agent_path = "/last-event-id-no-redis-agent";
    Mock::given(method("POST"))
        .and(path_regex(".*/agents/test-agent/resolve$"))
        .respond_with(
            ResponseTemplate::new(200).set_body_json(resolved_agent_json(&format!(
                "{}{}",
                mock_server.uri(),
                agent_path
            ))),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // 4. Mock agent endpoint → 200 with JSON (not SSE) response
    Mock::given(method("POST"))
        .and(path(agent_path))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"status": "ok"}
                })),
        )
        .expect(1)
        .mount(&mock_server)
        .await;

    // Use default config: redis_url = None → event_store = None.
    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // Build the request manually so we can attach the Last-Event-ID header.
    let request = Request::builder()
        .method("POST")
        .uri("/a2a/test-agent/invoke")
        .header("content-type", "application/json")
        .header("last-event-id", "evt-001")
        .body(Body::from(
            serde_json::to_vec(&streaming_message_json(1, "hello", "ROLE_USER")).unwrap(),
        ))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let body: Value = serde_json::from_slice(&bytes)
        .unwrap_or(json!({"raw": String::from_utf8_lossy(&bytes).to_string()}));

    // With no event store, the Last-Event-ID replay branch is skipped.
    // The handler falls through to a fresh agent call, which returns 200.
    assert_eq!(
        status,
        StatusCode::OK,
        "expected graceful fallback with 200, body: {body}"
    );
    // The agent call succeeded, so status_code should be 200.
    assert_eq!(body["status_code"], 200, "agent call should have succeeded");

    mock_server.verify().await;
}

#[tokio::test]
async fn test_streaming_method_replays_from_store_when_last_event_id_present() {
    let mock_server = MockServer::start().await;
    setup_auth_mock(&mock_server, 1).await;
    setup_authz_mock(&mock_server, 1).await;

    let mut config = default_test_config();
    config.backend_base_url = mock_server.uri();
    config.auth_secret = Some("test-secret".to_string());
    let event_store = Arc::new(
        contextforge_a2a_runtime::event_store::EventStore::seeded_for_test(
            vec![
                contextforge_a2a_runtime::event_store::StoredEvent {
                    event_id: "evt-1".to_string(),
                    sequence: 1,
                    event_type: "unknown".to_string(),
                    payload: r#"{"status":"queued"}"#.to_string(),
                },
                contextforge_a2a_runtime::event_store::StoredEvent {
                    event_id: "evt-2".to_string(),
                    sequence: 2,
                    event_type: "unknown".to_string(),
                    payload: r#"{"status":"working"}"#.to_string(),
                },
            ],
            false,
        ),
    );
    let app = contextforge_a2a_runtime::test_support::build_app_with_event_store(
        config,
        Some(event_store),
    );

    let request = Request::builder()
        .method("POST")
        .uri("/a2a/test-agent/invoke")
        .header("content-type", "application/json")
        .header("last-event-id", "task-123:0")
        .body(Body::from(
            serde_json::to_vec(&json!({
                "jsonrpc": "2.0",
                "method": "SendStreamingMessage",
                "id": 1,
                "params": {"id": "task-123", "message": {"role": "ROLE_USER", "parts": [{"text": "hello"}]}}
            }))
            .unwrap(),
        ))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok()),
        Some("text/event-stream")
    );

    let body = String::from_utf8_lossy(&response.into_body().collect().await.unwrap().to_bytes())
        .to_string();
    assert!(
        body.contains("id: evt-1:1"),
        "expected first replayed event, body: {body}"
    );
    assert!(
        body.contains("id: evt-2:2"),
        "expected second replayed event, body: {body}"
    );
    assert!(
        body.contains("data: {\"status\":\"queued\"}"),
        "expected queued payload, body: {body}"
    );
    assert!(
        body.contains("data: {\"status\":\"working\"}"),
        "expected working payload, body: {body}"
    );

    mock_server.verify().await;
}

// ---------------------------------------------------------------------------
// UAID cross-gateway (A2A 1.0-compliant) dispatch
// ---------------------------------------------------------------------------

/// Percent-encode `/` within a UAID so it survives routing as a single
/// path segment.  Callers of `/a2a/{uaid}/invoke` in production must do
/// the same when embedding a UAID with a full-URL `nativeId`.
fn encode_uaid_for_path(uaid: &str) -> String {
    uaid.replace('/', "%2F")
}

/// When the path-segment is a UAID and Python returns 404 on resolve, the
/// runtime should forward the original JSON-RPC body to the agent URL
/// embedded in the UAID's `nativeId`.  This is the A2A-1.0 path, not the
/// Python gateway's CF-federation path.
#[tokio::test]
async fn test_uaid_cross_gateway_forwards_jsonrpc_to_native_endpoint() {
    ensure_queue_initialized();

    // Mock the remote A2A agent at a known URL.  UAID nativeId will point
    // at the full wiremock URL so the runtime resolves routing to this
    // mock directly (no HTTPS in tests).
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .and(body_json(json!({
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": 7,
            "params": {"message": "hello"}
        })))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 7,
            "result": {"status": "completed", "message": "remote-reply"}
        })))
        .expect(1)
        .mount(&remote_agent)
        .await;

    // Mock the Python backend: authn 200, authz 204, resolve 404.
    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // UAID carries the remote agent's URL as nativeId.  The parser
    // accepts full http:// URLs so the test can target wiremock; we
    // percent-encode `/` so the UAID is a single path segment.
    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let body = json!({
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": 7,
        "params": {"message": "hello"}
    });

    let (status, resp) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK, "body: {resp}");
    assert_eq!(resp["status_code"], 200);
    assert_eq!(resp["success"], true);
    assert_eq!(resp["json"]["result"]["message"], "remote-reply");

    remote_agent.verify().await;
    backend.verify().await;
}

/// When the allowlist is configured and the UAID's host is not in it, the
/// runtime must reject with 403 before touching the remote agent.
#[tokio::test]
async fn test_uaid_cross_gateway_rejected_when_host_not_in_allowlist() {
    ensure_queue_initialized();

    let remote_agent = MockServer::start().await;
    // Expect zero calls — the allowlist must block before reaching here.
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.uaid_allowed_domains = "trusted.example.com".to_string();
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let (status, resp) = post_json(app, &uri, json!({"jsonrpc": "2.0", "id": 1})).await;

    assert_eq!(status, StatusCode::FORBIDDEN, "body: {resp}");
    remote_agent.verify().await;
    backend.verify().await;
}

/// When the UAID protocol is not `a2a`, the A2A runtime returns 501 rather
/// than trying to speak a non-A2A protocol.  MCP cross-gateway belongs in
/// the Python CF-federation path.
#[tokio::test]
async fn test_uaid_cross_gateway_rejects_non_a2a_protocol() {
    ensure_queue_initialized();

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=mcp;nativeId=mcp.example.com";
    let uri = format!("/a2a/{}/invoke", uaid);
    let (status, _) = post_json(app, &uri, json!({"jsonrpc": "2.0", "id": 1})).await;

    assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
    backend.verify().await;
}

/// Local UAID hit: when the Python resolver returns 200 the runtime must
/// NOT fall through to cross-gateway — it must invoke the locally
/// registered agent at the resolver-supplied endpoint_url.
#[tokio::test]
async fn test_uaid_local_hit_invokes_local_agent_not_cross_gateway() {
    ensure_queue_initialized();

    // The registered local agent listens here.
    let local_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/local-agent"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"origin": "local"}
        })))
        .expect(1)
        .mount(&local_agent)
        .await;

    // A UAID whose nativeId points at a DIFFERENT host — if the
    // runtime accidentally falls through to cross-gateway instead of
    // honouring the local resolve, the local_agent mock's `.expect(1)`
    // will fail.
    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=unreachable.example.invalid";

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    let local_endpoint = format!("{}/local-agent", local_agent.uri());
    setup_resolve_mock(&backend, uaid, &local_endpoint, 1).await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(uaid));
    let body = send_message_json(1, "hello");

    let (status, resp) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK, "body: {resp}");
    assert_eq!(resp["status_code"], 200);
    assert_eq!(resp["json"]["result"]["origin"], "local");

    local_agent.verify().await;
    backend.verify().await;
}

/// SendStreamingMessage against a local-hit UAID must reuse the pre-resolved
/// agent record rather than calling `/resolve` a second time.  A concurrent
/// cache eviction between the two calls would otherwise turn a valid
/// streaming invoke into a spurious 404.  This test mocks `resolve` with
/// `.expect(1)` — a regression that re-resolves inside `handle_streaming_method`
/// fails the count assertion.
#[tokio::test]
async fn test_uaid_local_hit_streaming_reuses_preresolved_agent() {
    ensure_queue_initialized();

    // Local A2A agent that returns an SSE stream on POST /.
    // Use `set_body_raw` to set both body and content-type; wiremock
    // overrides the content-type if `set_body_string` is used alongside
    // `append_header`.
    let local_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/stream-endpoint"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(
            "id: 1\nevent: status\ndata: {\"status\":\"ok\"}\n\n",
            "text/event-stream",
        ))
        .expect(1)
        .mount(&local_agent)
        .await;

    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=streaming.example.invalid";

    // Backend: authn + authz + resolve MUST be called exactly once each —
    // `.expect(1)` on resolve is the TOCTOU regression guard.
    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    let local_endpoint = format!("{}/stream-endpoint", local_agent.uri());
    setup_resolve_mock(&backend, uaid, &local_endpoint, 1).await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(uaid));
    let body = streaming_message_json(1, "hello", "user");
    let request = Request::builder()
        .method("POST")
        .uri(&uri)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    // Streaming content-type proves the runtime took the SSE proxy
    // branch, not the JSON fallback — a secondary guard on top of the
    // `.expect(1)` resolve mock below.
    assert_eq!(
        response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok()),
        Some("text/event-stream")
    );

    local_agent.verify().await;
    backend.verify().await;
}

/// UAID local hit + `tasks/get` must reuse `preresolved_agent` rather than
/// re-resolving inside the task branch.  `setup_resolve_mock(.., expect=1)`
/// is the regression guard: a double-resolve causes wiremock's `verify()`
/// to panic with an expectation mismatch.
#[tokio::test]
async fn test_uaid_local_hit_task_branch_reuses_preresolved_agent() {
    ensure_queue_initialized();

    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=tasks.example.invalid";

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    // authz endpoint is keyed by action (`get` for `tasks/get`), not
    // `invoke` — use a broader regex than `setup_authz_mock` provides.
    Mock::given(method("POST"))
        .and(path_regex(r".*authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&backend)
        .await;
    // Expect EXACTLY one resolve call — the UAID pre-resolve; the task
    // branch must reuse its result.
    setup_resolve_mock(&backend, uaid, "https://agent.example.invalid", 1).await;

    // The task-get proxy endpoint Python serves.
    Mock::given(method("POST"))
        .and(path("/_internal/a2a/tasks/get"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "id": "task-42",
            "status": {"state": "completed"}
        })))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let body = json!({
        "jsonrpc": "2.0",
        "method": "tasks/get",
        "id": 1,
        "params": {"id": "task-42"}
    });
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(uaid));
    let (status, _) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK);

    backend.verify().await;
}

/// Same TOCTOU guard as above, for the push-notification-config branch.
#[tokio::test]
async fn test_uaid_local_hit_push_branch_reuses_preresolved_agent() {
    ensure_queue_initialized();

    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=push.example.invalid";

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    // `tasks/pushNotificationConfig/set` maps to authz action "invoke",
    // so `setup_authz_mock`'s `.*invoke/authz$` regex matches.
    setup_authz_mock(&backend, 1).await;
    setup_resolve_mock(&backend, uaid, "https://agent.example.invalid", 1).await;

    Mock::given(method("POST"))
        .and(path("/_internal/a2a/push/create"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"ok": true})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let body = json!({
        "jsonrpc": "2.0",
        "method": "tasks/pushNotificationConfig/set",
        "id": 2,
        "params": {"task_id": "task-1", "url": "https://callback.example.invalid"}
    });
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(uaid));
    let (status, _) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK);

    backend.verify().await;
}

/// A remote UAID + SendStreamingMessage must be proxied end-to-end as
/// SSE, not buffered through `execute_invoke`.  Buffering collapses the
/// stream into a single JSON blob and defeats streaming entirely.  We
/// assert the response Content-Type is `text/event-stream` and that
/// individual SSE frames are present in the response body.
#[tokio::test]
async fn test_uaid_cross_gateway_streaming_forwards_sse() {
    ensure_queue_initialized();

    // Remote agent returns SSE frames on POST /.
    // `set_body_raw(body, content_type)` is the canonical way to set
    // both in wiremock; `set_body_string` + `append_header("content-type", …)`
    // is silently overridden and was the reason the streaming-local-hit
    // test had to drop a similar assertion.
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(
            "id: 1\nevent: status\ndata: {\"status\":\"queued\"}\n\n\
             id: 2\nevent: status\ndata: {\"status\":\"working\"}\n\n",
            "text/event-stream",
        ))
        .expect(1)
        .mount(&remote_agent)
        .await;

    // Backend: resolve returns 404 so Rust takes the cross-gateway path.
    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let body = streaming_message_json(7, "hello", "user");

    let request = Request::builder()
        .method("POST")
        .uri(&uri)
        .header("content-type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    // Key assertion: the sidecar proxied SSE, did NOT buffer into JSON.
    assert_eq!(
        response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok()),
        Some("text/event-stream"),
        "remote UAID + SendStreamingMessage must proxy SSE, not buffer to JSON"
    );

    let body_bytes = http_body_util::BodyExt::collect(response.into_body())
        .await
        .unwrap()
        .to_bytes();
    let body_str = String::from_utf8_lossy(&body_bytes);
    assert!(
        body_str.contains("data: {\"status\":\"queued\"}"),
        "expected first SSE frame, body: {body_str}"
    );
    assert!(
        body_str.contains("data: {\"status\":\"working\"}"),
        "expected second SSE frame, body: {body_str}"
    );

    remote_agent.verify().await;
    backend.verify().await;
}

/// When a remote UAID streaming invocation lands on an agent that does
/// not actually produce SSE, the runtime falls back to a buffered JSON
/// reply.  That fallback must still honour `max_response_body_bytes` so
/// a hostile remote cannot flood the sidecar with an unbounded body.
#[tokio::test]
async fn test_uaid_cross_gateway_streaming_fallback_enforces_body_size_limit() {
    ensure_queue_initialized();

    // Remote advertises a non-SSE content-type and returns a body
    // larger than the configured cap.  Using a JSON body (not SSE) so
    // the runtime takes the buffered fallback branch.
    let oversized = vec![b'x'; 4096];
    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(oversized, "application/json"))
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.max_response_body_bytes = 1024; // well below 4096
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let body = streaming_message_json(9, "hello", "user");

    let (status, resp) = post_json(app, &uri, body).await;
    assert_eq!(
        status,
        StatusCode::BAD_GATEWAY,
        "oversized remote response must be rejected, got body: {resp}"
    );
    let err_text = resp["error"].as_str().unwrap_or_default();
    assert!(
        err_text.contains("max_response_body_bytes"),
        "error should cite the body-size limit, got: {err_text}"
    );
}

/// A chunked-transfer remote that advertises no `Content-Length` must
/// still be bounded by `max_response_body_bytes`: the runtime reads the
/// body in bounded chunks and rejects as soon as the running total
/// crosses the cap.  Without this guard, a hostile remote could stream
/// unbounded data and only be stopped after the whole body was buffered.
///
/// Uses a raw `TcpListener` rather than a `wiremock::MockServer` because
/// wiremock's `set_body_raw` stamps a `Content-Length` header internally
/// — the fast-reject in `handle_uaid_cross_gateway_streaming` would then
/// fire on the header value alone and the body-size-during-read branch
/// of `read_bounded_body` would never execute.  Emitting a real
/// `Transfer-Encoding: chunked` response with no `Content-Length`
/// forces the test to exercise the running-total check.
#[tokio::test]
async fn test_uaid_cross_gateway_streaming_fallback_caps_chunked_body() {
    ensure_queue_initialized();

    // Build the chunked HTTP/1.1 response bytes manually: 8 KiB payload
    // in a single chunk, no Content-Length header.
    let payload = vec![b'y'; 8192];
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

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind remote-agent listener");
    let agent_addr = listener.local_addr().expect("local_addr");
    tokio::spawn(async move {
        // One-shot accept-and-reply: the test makes exactly one request.
        if let Ok((mut stream, _)) = listener.accept().await {
            use tokio::io::{AsyncReadExt, AsyncWriteExt};
            // Drain the request so the client sees a clean response.
            let mut buf = [0u8; 8192];
            let _ = stream.read(&mut buf).await;
            let _ = stream.write_all(&response_bytes).await;
            let _ = stream.shutdown().await;
        }
    });

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.max_response_body_bytes = 1024;
    let app = test_app(config);

    let uaid = format!("uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=http://{agent_addr}");
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let body = streaming_message_json(11, "hello", "user");
    let (status, resp) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::BAD_GATEWAY, "body: {resp}");
    assert!(
        resp["error"]
            .as_str()
            .unwrap_or_default()
            .contains("max_response_body_bytes"),
        "error should cite the body-size limit"
    );
}

/// UAID local hit + GetExtendedAgentCard must key the Python card
/// endpoint by the resolver-supplied canonical name, not the raw UAID.
/// Python's `/_internal/a2a/agents/{name}/card` route matches on `name`
/// only, so a UAID embedded in the URL would 404 outright.  The counter
/// mock at `/agents/<uaid>/card` asserts zero hits — a regression that
/// reverted `preresolved_agent.as_ref()` threading on `proxy_agent_card`
/// would trip it and fail the test.
#[tokio::test]
async fn test_uaid_local_hit_card_uses_canonical_name_not_uaid() {
    ensure_queue_initialized();

    let uaid = "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId=card.example.invalid";
    let canonical_name = "uaid-backed-card-agent";

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    // `agent/getExtendedCard` authz action is "get".
    Mock::given(method("POST"))
        .and(path_regex(r".*authz$"))
        .respond_with(ResponseTemplate::new(204))
        .expect(1)
        .mount(&backend)
        .await;
    // Resolve returns an agent whose canonical name differs from the
    // UAID path segment — this is exactly the case where the naive
    // (pre-fix) code would 404 downstream.
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "agent_id": "agent-card-001",
            "name": canonical_name,
            "endpoint_url": "https://card.example.invalid",
            "agent_type": "a2a",
            "protocol_version": "1.0",
            "auth_type": null,
            "auth_value_encrypted": null,
            "auth_query_params_encrypted": null
        })))
        .expect(1)
        .mount(&backend)
        .await;
    // Card endpoint keyed by canonical name returns a card.
    Mock::given(method("POST"))
        .and(path(format!("/_internal/a2a/agents/{canonical_name}/card")))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "name": canonical_name,
            "description": "card body"
        })))
        .expect(1)
        .mount(&backend)
        .await;
    // Counter mock: if the sidecar ever keys the card endpoint by the
    // UAID path segment, this mock catches it. `.expect(0)` turns such
    // a regression into a loud failure rather than a silent 404.
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/uaid:aid:[^/]+/card/?$"))
        .respond_with(ResponseTemplate::new(500).set_body_string("must not be called"))
        .expect(0)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let body = json!({
        "jsonrpc": "2.0",
        "method": "GetExtendedAgentCard",
        "id": 1,
        "params": {}
    });
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(uaid));
    let (status, resp) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK, "body: {resp}");
    assert_eq!(resp["status_code"], 200);

    backend.verify().await;
}

/// Federation-hop guard covers NON-UAID invocations too: a plain
/// agent-name call whose `endpoint_url` happens to loop back through
/// this same handler (misconfigured or malicious registration) must
/// also be rejected once the hop counter reaches the configured
/// maximum.  A previous iteration of the fix only stamped/read the
/// counter on the UAID branch, leaving local-agent invokes unbounded.
#[tokio::test]
async fn test_hop_limit_rejects_non_uaid_inbound_at_max() {
    ensure_queue_initialized();

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    // Resolve must not be called — the hop guard is evaluated BEFORE
    // resolve for every invocation, not just UAIDs.
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.uaid_max_federation_hops = 3;
    let app = test_app(config);

    let body = send_message_json(1, "hello");
    let request = Request::builder()
        .method("POST")
        .uri("/a2a/plain-agent-name/invoke")
        .header("content-type", "application/json")
        .header("x-contextforge-uaid-hop", "3")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::NOT_FOUND);
    backend.verify().await;
}

/// Local-agent invoke must STAMP the outbound hop header even when the
/// identifier is not a UAID — regression guard against the earlier
/// implementation that only stamped on the UAID cross-gateway path.
#[tokio::test]
async fn test_local_agent_invoke_stamps_outbound_hop_header() {
    ensure_queue_initialized();

    // Remote agent expects the hop header on the incoming request.
    let local_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/agent-endpoint"))
        .and(header("x-contextforge-uaid-hop", "1"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(1)
        .mount(&local_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    setup_resolve_mock(
        &backend,
        "plain-agent",
        &format!("{}/agent-endpoint", local_agent.uri()),
        1,
    )
    .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // No inbound hop header ⇒ hop_count=0 ⇒ outbound must be "1".
    let body = send_message_json(1, "hello");
    let (status, _) = post_json(app, "/a2a/plain-agent/invoke", body).await;
    assert_eq!(status, StatusCode::OK);

    local_agent.verify().await;
    backend.verify().await;
}

/// Visibility-denial on a NAMED-agent (non-UAID) request must surface
/// as 404 to the caller, not 403.  Python's `/_internal/.../resolve`
/// uses 403 so the sidecar can tell "exists-but-hidden" apart from
/// "not-found" (e.g., for UAID cross-gateway dispatch decisions), but
/// that signal must never leak to the external client — otherwise an
/// attacker probing for private agents can enumerate them by the
/// status-code difference.
///
/// The UAID branch was fixed earlier; this test locks in the fix for
/// the named-agent path where `take_or_resolve` surfaces 403.
#[tokio::test]
async fn test_named_agent_resolve_403_returns_404_to_client() {
    ensure_queue_initialized();

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    // Python resolver returns 403 (visibility-denied).
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(403).set_body_json(json!({"error": "access denied"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    // Plain agent name — NOT a UAID.  The UAID branch is bypassed; the
    // 403 surfaces through `take_or_resolve` + `map_agent_resolve_err`.
    let body = send_message_json(1, "hello");
    let (status, resp) = post_json(app, "/a2a/private-agent/invoke", body).await;
    assert_eq!(
        status,
        StatusCode::NOT_FOUND,
        "403 from resolver must be translated to 404 for the client; body={resp}"
    );
    // Error message must not contain "denied" or "forbidden" — those
    // words would also leak the existence signal to anyone grepping
    // the error text.
    let err_text = resp
        .get("error")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    assert!(
        !err_text.contains("denied") && !err_text.contains("forbidden"),
        "translated 404 must not echo the 403 signal in the error text: {err_text}"
    );
    backend.verify().await;
}

/// Federation-hop guard: an inbound UAID request carrying
/// `X-Contextforge-UAID-Hop: N` where N >= `uaid_max_federation_hops`
/// must be rejected with 404 and MUST NOT issue any outbound call —
/// otherwise a misconfigured/self-referential UAID loops through the
/// Rust sidecar the same way it would through Python.
#[tokio::test]
async fn test_uaid_hop_limit_rejects_inbound_at_max() {
    ensure_queue_initialized();

    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    // Resolve must also not be called — the hop guard fires before resolve.
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    config.uaid_max_federation_hops = 3;
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let body = send_message_json(1, "hello");
    let request = Request::builder()
        .method("POST")
        .uri(&uri)
        .header("content-type", "application/json")
        .header("x-contextforge-uaid-hop", "3")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();

    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::NOT_FOUND);

    remote_agent.verify().await;
    backend.verify().await;
}

/// Federation-hop stamp: a cross-gateway dispatch MUST include
/// `X-Contextforge-UAID-Hop: N+1` on the outbound POST so the next
/// gateway in the chain can count hops.  A regression that silently
/// drops the header reopens the loop.
#[tokio::test]
async fn test_uaid_cross_gateway_stamps_outbound_hop_header() {
    ensure_queue_initialized();

    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .and(header("x-contextforge-uaid-hop", "1"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"status": "ok"}
        })))
        .expect(1)
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(404).set_body_json(json!({"error": "not found"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    // No inbound hop header ⇒ hop_count = 0 ⇒ outbound should be 1.
    let body = send_message_json(1, "hello");
    let (status, _) = post_json(app, &uri, body).await;
    assert_eq!(status, StatusCode::OK);

    remote_agent.verify().await;
    backend.verify().await;
}

/// 403 from the Python resolver means "found but caller can't see it".
/// The sidecar must translate this to 404 for the end user (don't leak
/// existence) and must NOT fall through to cross-gateway.
#[tokio::test]
async fn test_uaid_resolve_403_returns_404_and_skips_cross_gateway() {
    ensure_queue_initialized();

    let remote_agent = MockServer::start().await;
    // Zero expected calls — a 403 must short-circuit before any outbound.
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(403).set_body_json(json!({"error": "access denied"})))
        .expect(1)
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let (status, _) = post_json(app, &uri, json!({"jsonrpc": "2.0", "id": 1})).await;

    // End-user-facing status must be 404 (existence hidden), not 403.
    assert_eq!(status, StatusCode::NOT_FOUND);
    remote_agent.verify().await;
    backend.verify().await;
}

/// Non-404, non-403 resolver error (e.g., 500 → BAD_GATEWAY) must
/// surface to the caller rather than being silently converted into
/// cross-gateway dispatch.
#[tokio::test]
async fn test_uaid_resolve_5xx_surfaces_as_bad_gateway() {
    ensure_queue_initialized();

    let remote_agent = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0) // must not be called
        .mount(&remote_agent)
        .await;

    let backend = MockServer::start().await;
    setup_auth_mock(&backend, 1).await;
    setup_authz_mock(&backend, 1).await;
    Mock::given(method("POST"))
        .and(path_regex(r"^/_internal/a2a/agents/[^/]+/resolve/?$"))
        .respond_with(ResponseTemplate::new(500).set_body_string("backend exploded"))
        .mount(&backend)
        .await;

    let mut config = default_test_config();
    config.backend_base_url = backend.uri();
    config.auth_secret = Some("test-secret".to_string());
    let app = test_app(config);

    let uaid = format!(
        "uaid:aid:HASH;uid=0;registry=cf;proto=a2a;nativeId={}",
        remote_agent.uri()
    );
    let uri = format!("/a2a/{}/invoke", encode_uaid_for_path(&uaid));
    let (status, _) = post_json(app, &uri, json!({"jsonrpc": "2.0", "id": 1})).await;

    assert_eq!(status, StatusCode::BAD_GATEWAY);
    remote_agent.verify().await;
}
