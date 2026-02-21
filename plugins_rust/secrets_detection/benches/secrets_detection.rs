// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for secrets detection performance

use criterion::{criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use secrets_detection_rust::{detect_and_redact, SecretsDetectionConfig};
use std::collections::HashMap;
use std::hint::black_box;
use std::time::Duration;

fn create_test_config() -> SecretsDetectionConfig {
    SecretsDetectionConfig {
        enabled: HashMap::from([
            ("aws_access_key_id".to_string(), true),
            ("aws_secret_access_key".to_string(), true),
            ("google_api_key".to_string(), true),
            ("slack_token".to_string(), true),
            ("private_key_block".to_string(), true),
            ("jwt_like".to_string(), true),
            ("hex_secret_32".to_string(), true),
            ("base64_24".to_string(), true),
        ]),
        redact: true,
        redaction_text: "***REDACTED***".to_string(),
        block_on_detection: true,
        min_findings_to_block: 1,
    }
}

fn create_no_redact_config() -> SecretsDetectionConfig {
    SecretsDetectionConfig {
        redact: false,
        ..create_test_config()
    }
}

// Create realistic conversation data with various secret types
fn create_realistic_conversation_data() -> Vec<(&'static str, &'static str)> {
    vec![
        // Clean conversation messages
        (
            "clean",
            "I'm setting up a microservices architecture on Kubernetes. What are the best practices for service discovery?",
        ),
        (
            "clean",
            "For monitoring our services, I recommend using Prometheus with Grafana dashboards and Jaeger for distributed tracing.",
        ),
        // Messages with secrets
        (
            "aws_secret",
            "Here are my AWS credentials: AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000",
        ),
        (
            "slack_token",
            "Our Slack bot token is xoxr-fake-000000000-fake000000000-fakefakefakefake for notifications",
        ),
        (
            "google_api",
            "The Google API key is AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345 for our maps integration",
        ),
        (
            "jwt_token",
            "JWT token: eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678",
        ),
        (
            "hex_secret",
            "Database encryption key: 00face00dead00beef00cafe00fade0000000000000000000000000000000000",
        ),
        (
            "base64_secret",
            "Service account key: dGhpcyBpcyBhIGJhc2U2NCBlbmNvZGVkIHNlY3JldCBrZXkgZm9yIHRlc3RpbmcgcHVycG9zZXM=",
        ),
        (
            "mixed_secrets",
            "Deploy with AWS_KEY=AKIAFAKE67890EXAMPLE SLACK_TOKEN=xoxr-fake-123-456-789 API_KEY=AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345",
        ),
    ]
}

// Benchmark detect_and_redact function with realistic conversation data
fn bench_detect_and_redact(c: &mut Criterion) {
    let messages = create_realistic_conversation_data();
    let config = create_test_config();
    let no_redact_config = create_no_redact_config();

    let mut group = c.benchmark_group("detect_and_redact");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    for (message_type, message) in messages.iter() {
        group.throughput(Throughput::Bytes(message.len() as u64));

        // With redaction
        group.bench_with_input(
            BenchmarkId::new("with_redaction", message_type),
            message,
            |b, msg| {
                b.iter(|| detect_and_redact(black_box(msg), black_box(&config)));
            },
        );

        // Detection only (no redaction)
        group.bench_with_input(
            BenchmarkId::new("detection_only", message_type),
            message,
            |b, msg| {
                b.iter(|| detect_and_redact(black_box(msg), black_box(&no_redact_config)));
            },
        );
    }

    group.finish();
}

// Benchmark batch processing
fn bench_batch_processing(c: &mut Criterion) {
    let messages = create_realistic_conversation_data();
    let config = create_test_config();

    let mut group = c.benchmark_group("batch_processing");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    // Extract just the messages for batch processing
    let message_texts: Vec<&str> = messages.iter().map(|(_, msg)| *msg).collect();
    let total_bytes: u64 = message_texts.iter().map(|m| m.len() as u64).sum();

    group.throughput(Throughput::Bytes(total_bytes));

    group.bench_function("all_messages_batch", |b| {
        b.iter(|| {
            for message in &message_texts {
                let _ = detect_and_redact(black_box(message), black_box(&config));
            }
        });
    });

    // Test individual messages with secrets
    let secret_messages: Vec<&str> = messages
        .iter()
        .filter(|(msg_type, _)| *msg_type != "clean")
        .map(|(_, msg)| *msg)
        .collect();

    for (i, message) in secret_messages.iter().enumerate() {
        group.throughput(Throughput::Bytes(message.len() as u64));
        group.bench_with_input(
            BenchmarkId::new("individual_with_secrets", i),
            message,
            |b, msg| {
                b.iter(|| detect_and_redact(black_box(msg), black_box(&config)));
            },
        );
    }

    group.finish();
}

criterion_group!(benches, bench_detect_and_redact, bench_batch_processing);

criterion_main!(benches);
