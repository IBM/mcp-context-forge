// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
//! Integration tests for the A2A Axum app: health, invoke, and proxy routes.

use std::sync::Arc;

use a2a_service::{init_invoker, init_queue, server};
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use tower::ServiceExt;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

fn test_state(backend_base_url: String) -> Arc<server::AppState> {
    Arc::new(server::AppState {
        auth_secret: None,
        timeout_secs: 60.0,
        backend_base_url,
        client: reqwest::Client::new(),
    })
}

/// Ensure queue and invoker are initialized so /invoke can run (shared state across tests).
fn ensure_init() {
    init_invoker(4, 1);
    init_queue(4, Some(100), None);
}

#[tokio::test]
async fn test_health_returns_ok() {
    let state = test_state("http://127.0.0.1:4444".to_string());
    let app = server::router(state);

    let request = Request::builder()
        .uri("/health")
        .body(Body::empty())
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let body = response.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(body.as_ref(), b"ok");
}

#[tokio::test]
async fn test_invoke_empty_batch_returns_400() {
    ensure_init();
    let state = test_state("http://127.0.0.1:4444".to_string());
    let app = server::router(state);

    let body = serde_json::json!([]);
    let request = Request::builder()
        .method("POST")
        .uri("/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_invoke_invalid_json_returns_400() {
    ensure_init();
    let state = test_state("http://127.0.0.1:4444".to_string());
    let app = server::router(state);

    let request = Request::builder()
        .method("POST")
        .uri("/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(Vec::from(b"not json" as &[u8])))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_invoke_not_object_or_array_returns_400() {
    ensure_init();
    let state = test_state("http://127.0.0.1:4444".to_string());
    let app = server::router(state);

    let request = Request::builder()
        .method("POST")
        .uri("/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(Vec::from(b"\"string\"" as &[u8])))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn test_invoke_single_request_success() {
    let mock = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/"))
        .respond_with(ResponseTemplate::new(200).set_body_string(r#"{"result":true}"#))
        .mount(&mock)
        .await;

    ensure_init();
    let state = test_state("http://127.0.0.1:4444".to_string());
    let app = server::router(state);

    let body = serde_json::json!({
        "id": 1,
        "base_url": mock.uri(),
        "body": "{}"
    });
    let request = Request::builder()
        .method("POST")
        .uri("/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let buf = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&buf).unwrap();
    assert_eq!(json.get("status_code").and_then(|v| v.as_u64()), Some(200));
    assert_eq!(json.get("success").and_then(|v| v.as_bool()), Some(true));
}

#[tokio::test]
async fn test_a2a_invoke_batch_returns_array() {
    let mock = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/a2a/my_agent/invoke"))
        .respond_with(ResponseTemplate::new(200).set_body_string(r#"{"ok":true}"#))
        .mount(&mock)
        .await;

    let uri = mock.uri();
    let base = uri.trim_end_matches('/').to_string();
    let state = test_state(base);
    let app = server::router(state);

    let body = serde_json::json!([{"query": "a"}, {"query": "b"}]);
    let request = Request::builder()
        .method("POST")
        .uri("/a2a/my_agent/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let buf = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&buf).unwrap();
    let arr = json.as_array().unwrap();
    assert_eq!(arr.len(), 2);
}

#[tokio::test]
async fn test_a2a_proxy_forwards_to_backend() {
    let mock = MockServer::start().await;
    // Axum nesting may forward /a2a as either /a2a or /a2a/ depending on slash normalization.
    Mock::given(method("GET"))
        .and(path("/a2a"))
        .respond_with(ResponseTemplate::new(200).set_body_string(r#"{"agents":[]}"#))
        .mount(&mock)
        .await;
    Mock::given(method("GET"))
        .and(path("/a2a/"))
        .respond_with(ResponseTemplate::new(200).set_body_string(r#"{"agents":[]}"#))
        .mount(&mock)
        .await;

    let base = mock.uri().trim_end_matches('/').to_string();
    let state = test_state(base);
    let app = server::router(state);

    let request = Request::builder()
        .method("GET")
        .uri("/a2a")
        .body(Body::empty())
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let buf = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&buf).unwrap();
    assert!(json.get("agents").is_some());
}

#[tokio::test]
async fn test_a2a_proxy_post_returns_backend_response() {
    let mock = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/a2a"))
        .respond_with(ResponseTemplate::new(201).set_body_string(r#"{"id":"new"}"#))
        .mount(&mock)
        .await;
    Mock::given(method("POST"))
        .and(path("/a2a/"))
        .respond_with(ResponseTemplate::new(201).set_body_string(r#"{"id":"new"}"#))
        .mount(&mock)
        .await;

    let base = mock.uri().trim_end_matches('/').to_string();
    let state = test_state(base);
    let app = server::router(state);

    let request = Request::builder()
        .method("POST")
        .uri("/a2a")
        .header("Content-Type", "application/json")
        .body(Body::from(Vec::from(b"{}" as &[u8])))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::CREATED);
}

#[tokio::test]
async fn test_a2a_invoke_single_proxies_to_backend() {
    let mock = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/a2a/foo/invoke"))
        .respond_with(ResponseTemplate::new(200).set_body_string(r#"{"result":"ok"}"#))
        .mount(&mock)
        .await;

    let base = mock.uri().trim_end_matches('/').to_string();
    let state = test_state(base);
    let app = server::router(state);

    let request = Request::builder()
        .method("POST")
        .uri("/a2a/foo/invoke")
        .header("Content-Type", "application/json")
        .body(Body::from(Vec::from(b"{\"method\":\"test\"}" as &[u8])))
        .unwrap();
    let response = app.oneshot(request).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let buf = response.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&buf).unwrap();
    assert_eq!(json.get("result").and_then(|v| v.as_str()), Some("ok"));
}
