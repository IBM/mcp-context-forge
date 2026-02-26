// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Benchmarks for A2A invoker: single-request latency (overhead), batch throughput,
// and auth decryption (decrypt_auth / decrypt_map_values).

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm,
};
use base64::Engine;
use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use reqwest::Client;
use sha2::{Digest, Sha256};
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

use a2a_service::{decrypt_auth, decrypt_map_values, A2AInvokeRequest, A2AInvoker, MetricsCollector};

/// Produce a valid encrypted blob (same format as Python encode_auth) for benchmarking decrypt.
fn make_encrypted_blob(secret: &str, payload: &str) -> String {
    let key = Sha256::digest(secret.as_bytes());
    let cipher = Aes256Gcm::new_from_slice(key.as_slice()).unwrap();
    let nonce: [u8; 12] = [0u8; 12]; // fixed for reproducibility
    let ciphertext = cipher
        .encrypt((&nonce).into(), payload.as_bytes())
        .unwrap();
    let mut combined = nonce.to_vec();
    combined.extend_from_slice(&ciphertext);
    base64::engine::general_purpose::URL_SAFE.encode(combined)
}

async fn run_single(invoker: &A2AInvoker, url: &str, timeout: Duration) -> usize {
    let requests = vec![A2AInvokeRequest {
        id: 0,
        url: url.to_string(),
        body: b"{}".to_vec(),
        headers: HashMap::new(),
        correlation_id: None,
        traceparent: None,
        agent_name: None,
        agent_id: None,
        interaction_type: None,
        scope_id: None,
        request_id: None,
    }];
    let results = invoker.invoke(requests, timeout).await;
    results.len()
}

async fn run_batch(invoker: &A2AInvoker, url: &str, n: usize, timeout: Duration) -> usize {
    let requests: Vec<A2AInvokeRequest> = (0..n)
        .map(|i| A2AInvokeRequest {
            id: i,
            url: url.to_string(),
            body: b"{}".to_vec(),
            headers: HashMap::new(),
            correlation_id: None,
            traceparent: None,
            agent_name: None,
            agent_id: None,
            interaction_type: None,
            scope_id: None,
            request_id: None,
        })
        .collect();
    let results = invoker.invoke(requests, timeout).await;
    results.len()
}

fn bench_invoke_overhead(c: &mut Criterion) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    let body = r#"{"jsonrpc":"2.0","result":{}}"#;
    rt.block_on(async {
        let mock = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_raw(body.as_bytes(), "application/json"),
            )
            .mount(&mock)
            .await;
        let client = Client::builder().build().unwrap();
        let metrics = Arc::new(MetricsCollector::new());
        let invoker = A2AInvoker::new(client, metrics);
        let url = mock.uri();
        let timeout = Duration::from_secs(5);

        let mut group = c.benchmark_group("invoke_overhead");
        group.sample_size(100);
        group.measurement_time(Duration::from_secs(5));
        group.bench_function("single_request_latency", |b| {
            b.iter(|| rt.block_on(run_single(&invoker, &url, timeout)))
        });
        group.finish();
    });
}

fn bench_invoke_throughput(c: &mut Criterion) {
    let rt = tokio::runtime::Runtime::new().unwrap();
    let body = r#"{"jsonrpc":"2.0","result":{}}"#;
    rt.block_on(async {
        let mock = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/"))
            .respond_with(
                ResponseTemplate::new(200).set_body_raw(body.as_bytes(), "application/json"),
            )
            .mount(&mock)
            .await;
        let client = Client::builder().build().unwrap();
        let metrics = Arc::new(MetricsCollector::new());
        let invoker = A2AInvoker::new(client, metrics);
        let url = mock.uri();
        let timeout = Duration::from_secs(30);

        let mut group = c.benchmark_group("invoke_throughput");
        for n in [100, 1_000, 10_000] {
            group.throughput(Throughput::Elements(n as u64));
            group.sample_size(10);
            group.measurement_time(Duration::from_secs(10));
            group.bench_with_input(BenchmarkId::new("batch_concurrent", n), &n, |b, &n| {
                b.iter(|| rt.block_on(run_batch(&invoker, &url, n, timeout)))
            });
        }
        group.finish();
    });
}

fn bench_auth_decrypt(c: &mut Criterion) {
    const SECRET: &str = "bench-secret-32-bytes-long!!!!!!!!";
    let payload = r#"{"Authorization":"Bearer test-token"}"#;
    let blob = make_encrypted_blob(SECRET, payload);

    let mut group = c.benchmark_group("auth_decrypt");
    group.sample_size(1000);
    group.bench_function("decrypt_auth_single", |b| {
        b.iter(|| decrypt_auth(&blob, SECRET).unwrap())
    });

    // decrypt_map_values with one entry (value = encrypted blob)
    let enc_map: HashMap<String, String> = [("auth".to_string(), blob.clone())].into();
    group.bench_function("decrypt_map_values_single", |b| {
        b.iter(|| decrypt_map_values(&enc_map, SECRET).unwrap())
    });

    let enc_map_10: HashMap<String, String> = (0..10)
        .map(|i| (format!("k{}", i), blob.clone()))
        .collect();
    group.throughput(Throughput::Elements(10));
    group.bench_function("decrypt_map_values_10", |b| {
        b.iter(|| decrypt_map_values(&enc_map_10, SECRET).unwrap())
    });
    group.finish();
}

criterion_group!(
    name = benches;
    config = Criterion::default();
    targets = bench_invoke_overhead, bench_invoke_throughput, bench_auth_decrypt
);
criterion_main!(benches);
