// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Heavy workload example for flamegraph profiling

use secrets_detection_rust::{detect_and_redact, SecretsDetectionConfig};
use std::collections::HashMap;

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

fn main() {
    let config = create_test_config();

    // Create a large dataset with various secret types
    let test_messages = vec![
        "Clean message about Kubernetes deployment strategies and best practices for microservices.",
        "AWS credentials: AWS_ACCESS_KEY_ID=AKIAFAKE12345EXAMPLE AWS_SECRET_ACCESS_KEY=FAKESecretAccessKeyForTestingEXAMPLE0000",
        "Slack bot token: xoxr-fake-000000000-fake000000000-fakefakefakefake for notifications",
        "Google API key: AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345 for maps integration",
        "JWT token: eyJfake_header_12345.eyJfake_payload_1234.fake_signature_12345678",
        "Database encryption key: 00face00dead00beef00cafe00fade0000000000000000000000000000000000",
        "Service account key: dGhpcyBpcyBhIGJhc2U2NCBlbmNvZGVkIHNlY3JldCBrZXkgZm9yIHRlc3RpbmcgcHVycG9zZXM=",
        "Multiple secrets: AWS_KEY=AKIAFAKE67890EXAMPLE SLACK_TOKEN=xoxr-fake-123-456-789 API_KEY=AIzaFAKE_KEY_FOR_TESTING_ONLY_fake12345",
        "Discussion about Docker container orchestration and service mesh architectures.",
        "Private key block: -----BEGIN RSA PRIVATE KEY----- MIIEpAIBAAKCAQEA... -----END RSA PRIVATE KEY-----",
    ];

    println!("Starting heavy workload processing...");
    println!("Processing {} message types", test_messages.len());

    // Process each message type 100,000 times to create heavy workload
    let iterations = 100_000;
    let mut total_processed = 0;
    let mut secrets_found = 0;

    for iteration in 0..iterations {
        for message in &test_messages {
            let (findings, _redacted) = detect_and_redact(message, &config);
            total_processed += 1;

            if !findings.is_empty() {
                secrets_found += 1;
            }
        }

        // Progress indicator every 10,000 iterations
        if (iteration + 1) % 10_000 == 0 {
            println!(
                "Processed {} iterations ({} total messages, {} with secrets)",
                iteration + 1,
                total_processed,
                secrets_found
            );
        }
    }

    println!("\nWorkload complete!");
    println!("Total messages processed: {}", total_processed);
    println!("Messages with secrets found: {}", secrets_found);
    println!(
        "Detection rate: {:.2}%",
        (secrets_found as f64 / total_processed as f64) * 100.0
    );
}
