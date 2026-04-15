// Copyright 2026
// SPDX-License-Identifier: Apache-2.0

//! Criterion benchmarks for A2A runtime invoke operations.

use std::collections::HashMap;
use std::time::Duration;

use aes_gcm::aead::OsRng;
use aes_gcm::{AeadCore, Aes256Gcm, KeyInit, aead::Aead};
use axum::body::Body;
use axum::http::Request;
use base64::engine::{Engine, general_purpose::URL_SAFE_NO_PAD};
use criterion::{Criterion, criterion_group, criterion_main};
use http_body_util::BodyExt;
use serde_json::json;
use sha2::{Digest, Sha256};
use tower::ServiceExt;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

use contextforge_a2a_runtime::auth::{decrypt_auth, decrypt_map_values}; // pragma: allowlist secret
use contextforge_a2a_runtime::config::RuntimeConfig;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn default_bench_config() -> RuntimeConfig {
    RuntimeConfig {
        listen_http: "127.0.0.1:0".to_string(),
        listen_uds: None,
        request_timeout_ms: 5_000,
        client_connect_timeout_ms: 2_000,
        client_pool_idle_timeout_seconds: 10,
        client_pool_max_idle_per_host: 4,
        client_tcp_keepalive_seconds: 10,
        max_response_body_bytes: 10_485_760,
        max_retries: 0,
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
        log_filter: "error".to_string(),
        exit_after_startup_ms: None,
    }
}

/// Encrypt helper replicating the `#[cfg(test)]` function from `auth.rs`.
fn encrypt_auth(
    payload: &HashMap<String, String>,
    secret: &str, /* pragma: allowlist secret */
) -> String {
    let plaintext = serde_json::to_vec(payload).unwrap();
    let key: [u8; 32] = Sha256::digest(secret.as_bytes()).into();
    let cipher = Aes256Gcm::new(&key.into());
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    let ciphertext = cipher.encrypt(&nonce, plaintext.as_ref()).unwrap();
    let mut combined = nonce.to_vec();
    combined.extend_from_slice(&ciphertext);
    URL_SAFE_NO_PAD.encode(&combined)
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_invoke_overhead(c: &mut Criterion) {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();

    // Start wiremock inside the runtime so it binds to a real port.
    let mock_uri = rt.block_on(async {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(json!({"jsonrpc":"2.0","id":1,"result":{"status":"ok"}})),
            )
            .mount(&server)
            .await;
        // MockServer must stay alive; leak it so the port stays open.
        let uri = server.uri();
        std::mem::forget(server);
        uri
    });

    let mut group = c.benchmark_group("invoke_overhead");
    group.sample_size(100);
    group.measurement_time(Duration::from_secs(5));

    group.bench_function("single_invoke", |b| {
        b.iter(|| {
            rt.block_on(async {
                let app = contextforge_a2a_runtime::test_support::build_app(default_bench_config());
                let body = serde_json::to_vec(&json!({
                    "endpoint_url": &mock_uri,
                    "headers": {"Content-Type": "application/json"},
                    "json_body": {"jsonrpc":"2.0","method":"SendMessage","id":1,"params":{}},
                    "timeout_seconds": 5
                }))
                .unwrap();

                let req = Request::builder()
                    .method("POST")
                    .uri("/invoke")
                    .header("content-type", "application/json")
                    .body(Body::from(body))
                    .unwrap();

                let resp = app.oneshot(req).await.unwrap();
                assert_eq!(resp.status(), 200);
                let _ = resp.into_body().collect().await.unwrap().to_bytes();
            });
        });
    });

    group.finish();
}

fn bench_auth_decrypt(c: &mut Criterion) {
    let secret = "bench-secret-key-2026"; // pragma: allowlist secret

    // Pre-build a single encrypted blob.
    let mut payload = HashMap::new();
    payload.insert("token".to_string(), "bearer-xyz-42".to_string());
    let single_blob = encrypt_auth(&payload, secret);

    // Pre-build a map with 10 entries.
    let encrypted_map: HashMap<String, String> = (0..10)
        .map(|i| {
            let key = format!("param_{i}");
            let mut p = HashMap::new();
            p.insert(key.clone(), format!("value_{i}"));
            (key, encrypt_auth(&p, secret))
        })
        .collect();

    let mut group = c.benchmark_group("auth_decrypt");

    group.bench_function("single_blob/1000", |b| {
        b.iter(|| {
            for _ in 0..1000 {
                let _ = decrypt_auth(&single_blob, secret).unwrap();
            }
        });
    });

    group.bench_function("map_10_entries/100", |b| {
        b.iter(|| {
            for _ in 0..100 {
                let _ = decrypt_map_values(&encrypted_map, secret).unwrap();
            }
        });
    });

    group.finish();
}

criterion_group!(benches, bench_invoke_overhead, bench_auth_decrypt);
criterion_main!(benches);
