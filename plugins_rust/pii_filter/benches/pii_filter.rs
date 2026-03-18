// Copyright 2025
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for PII filter performance

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::hint::black_box;
use std::time::Duration;
// Import the PII filter modules
use pii_filter_rust::{
    config::{MaskingStrategy, PIIConfig},
    detector::detect_pii,
    masking::mask_pii,
    patterns::compile_patterns,
};

fn create_test_config() -> PIIConfig {
    PIIConfig {
        detect_ssn: true,
        detect_bsn: true,
        detect_credit_card: true,
        detect_email: true,
        detect_phone: true,
        detect_ip_address: true,
        detect_date_of_birth: true,
        detect_passport: true,
        detect_bank_account: true,
        detect_medical_record: true,
        detect_full_name: false,
        detect_street_address: false,
        detect_us_zip_code: false,
        detect_us_ein: false,
        detect_us_itin: false,
        default_mask_strategy: MaskingStrategy::Partial,
        redaction_text: "[REDACTED]".to_string(),
        block_on_detection: false,
        log_detections: true,
        include_detection_details: true,
        custom_patterns: vec![],
        whitelist_patterns: vec![],
    }
}

fn bench_pattern_compilation(c: &mut Criterion) {
    let config = create_test_config();

    c.bench_function("pattern_compilation", |b| {
        b.iter(|| black_box(compile_patterns(black_box(&config))))
    });
}

fn bench_single_ssn_detection(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "My SSN is 123-45-6789";

    c.bench_function("detect_single_ssn", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_single_email_detection(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "Contact me at john.doe@example.com for more info";

    c.bench_function("detect_single_email", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_multiple_pii_types(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text =
        "SSN: 123-45-6789, Email: john@example.com, Phone: (555) 123-4567, IP: 192.168.1.100";

    c.bench_function("detect_multiple_types", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_no_pii_detection(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "This is just normal text without any sensitive information whatsoever. \
                It contains nothing that should be detected as PII. Just plain English text.";

    c.bench_function("detect_no_pii", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_masking_ssn(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN: 123-45-6789";
    let detections = detect_pii(text, &patterns, &config);

    c.bench_function("mask_ssn", |b| {
        b.iter(|| {
            black_box(mask_pii(
                black_box(text),
                black_box(&detections),
                black_box(&config),
            ))
        })
    });
}

fn bench_masking_multiple(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN: 123-45-6789, Email: test@example.com, Phone: 555-1234";
    let detections = detect_pii(text, &patterns, &config);

    c.bench_function("mask_multiple_types", |b| {
        b.iter(|| {
            black_box(mask_pii(
                black_box(text),
                black_box(&detections),
                black_box(&config),
            ))
        })
    });
}

fn bench_large_text_detection(c: &mut Criterion) {
    let mut group = c.benchmark_group("large_text_detection");

    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    for size in [100, 500, 1000, 5000].iter() {
        // Generate text with N PII instances
        let mut text = String::new();
        for i in 0..*size {
            text.push_str(&format!(
                "User {}: SSN {:03}-45-6789, Email user{}@example.com, Phone: (555) {:03}-{:04}\n",
                i,
                i % 1000,
                i,
                i % 1000,
                i % 10000
            ));
        }

        group.throughput(Throughput::Bytes(text.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &text, |b, text| {
            b.iter(|| {
                black_box(detect_pii(
                    black_box(text),
                    black_box(&patterns),
                    black_box(&config),
                ))
            })
        });
    }

    group.finish();
}

fn bench_parallel_regex_matching(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    // Text with multiple PII types to test RegexSet parallelism
    let text = "User details: SSN 123-45-6789, Email john@example.com, \
                Phone (555) 123-4567, Credit Card 4111-1111-1111-1111, \
                AWS Key AKIAIOSFODNN7EXAMPLE, IP 192.168.1.100, \
                DOB 01/15/1990, Passport AB1234567";

    c.bench_function("parallel_regex_set", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_nested_structure_traversal(c: &mut Criterion) {
    // Note: This is a simplified benchmark for the traversal logic
    // Full nested structure benchmarks would require PyO3 integration
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    let text_samples = vec![
        "SSN: 123-45-6789",
        "Email: user@example.com",
        "Phone: 555-1234",
        "No PII here",
        "Credit card: 4111-1111-1111-1111",
    ];

    c.bench_function("traverse_list_items", |b| {
        b.iter(|| {
            for text in &text_samples {
                black_box(detect_pii(
                    black_box(text),
                    black_box(&patterns),
                    black_box(&config),
                ));
            }
        })
    });
}

fn bench_whitelist_checking(c: &mut Criterion) {
    let mut config = create_test_config();
    config.whitelist_patterns = vec!["test@example\\.com".to_string()];

    let patterns = compile_patterns(&config).unwrap();
    let text = "Email1: test@example.com, Email2: john@example.com";

    c.bench_function("whitelist_filtering", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_overlap_heavy_detection(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let text = "SSN 123-45-6789 SSN: 123-45-6789 social security number 123456789 \
                BSN 111222333 passport no: AB1234567 passport no: AB1234567";

    c.bench_function("detect_overlap_heavy", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

fn bench_checksum_heavy_numeric_strings(c: &mut Criterion) {
    let mut group = c.benchmark_group("checksum_heavy_numeric_strings");
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    for size in [50usize, 250, 1000] {
        let mut text = String::new();
        for i in 0..size {
            let invalid_cc = format!(
                "{:04} {:04} {:04} {:04}",
                4111,
                1111,
                1111,
                1000 + (i % 8999)
            );
            let candidate_bsn = format!("Order: {:09}", 100000000 + (i % 899));
            text.push_str(&invalid_cc);
            text.push(' ');
            text.push_str(&candidate_bsn);
            text.push('\n');
        }

        group.throughput(Throughput::Bytes(text.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &text, |b, text| {
            b.iter(|| {
                black_box(detect_pii(
                    black_box(text),
                    black_box(&patterns),
                    black_box(&config),
                ))
            })
        });
    }

    group.finish();
}

fn bench_different_masking_strategies(c: &mut Criterion) {
    let mut group = c.benchmark_group("masking_strategies");

    let base_config = create_test_config();
    let patterns = compile_patterns(&base_config).unwrap();
    let text = "SSN: 123-45-6789, Email: john@example.com";
    let detections = detect_pii(text, &patterns, &base_config);

    let strategies = [
        MaskingStrategy::Partial,
        MaskingStrategy::Redact,
        MaskingStrategy::Hash,
        MaskingStrategy::Tokenize,
        MaskingStrategy::Remove,
    ];

    for strategy in strategies.iter() {
        let mut config = base_config.clone();
        config.default_mask_strategy = *strategy;

        group.bench_with_input(
            BenchmarkId::new("strategy", format!("{:?}", strategy)),
            strategy,
            |b, _| {
                b.iter(|| {
                    black_box(mask_pii(
                        black_box(text),
                        black_box(&detections),
                        black_box(&config),
                    ))
                })
            },
        );
    }

    group.finish();
}

fn bench_empty_vs_pii_text(c: &mut Criterion) {
    let mut group = c.benchmark_group("empty_vs_pii");

    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    let empty_text = "";
    let no_pii_text = "This is just normal text without any PII";
    let with_pii_text = "SSN: 123-45-6789";

    group.bench_function("empty_text", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(empty_text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });

    group.bench_function("no_pii_text", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(no_pii_text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });

    group.bench_function("with_pii_text", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(with_pii_text),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });

    group.finish();
}

fn bench_realistic_workload(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();

    // Simulate realistic API request payload
    let realistic_text = r#"{
        "user": {
            "ssn": "123-45-6789",
            "email": "john.doe@example.com",
            "phone": "(555) 123-4567",
            "address": "123 Main St, Anytown, USA",
            "credit_card": "4111-1111-1111-1111",
            "notes": "Customer called regarding account issue"
        },
        "metadata": {
            "ip_address": "192.168.1.100",
            "timestamp": "2025-01-15T10:30:00Z",
            "request_id": "abc123"
        }
    }"#;

    c.bench_function("realistic_api_payload", |b| {
        b.iter(|| {
            let detections = detect_pii(
                black_box(realistic_text),
                black_box(&patterns),
                black_box(&config),
            );
            black_box(mask_pii(
                black_box(realistic_text),
                black_box(&detections),
                black_box(&config),
            ))
        })
    });
}

fn bench_worst_case_near_misses(c: &mut Criterion) {
    let config = create_test_config();
    let patterns = compile_patterns(&config).unwrap();
    let near_miss = "AKIAIOSFODNN7EXAMPLX api_key: short-token invoice: 12345678 ".repeat(256);

    c.bench_function("worst_case_near_misses", |b| {
        b.iter(|| {
            black_box(detect_pii(
                black_box(&near_miss),
                black_box(&patterns),
                black_box(&config),
            ))
        })
    });
}

criterion_group!(
    name = benches;
    config = Criterion::default()
        .sample_size(50)
        .warm_up_time(Duration::from_secs(1))
        .measurement_time(Duration::from_secs(3));
    targets =
    bench_pattern_compilation,
    bench_single_ssn_detection,
    bench_single_email_detection,
    bench_multiple_pii_types,
    bench_no_pii_detection,
    bench_masking_ssn,
    bench_masking_multiple,
    bench_large_text_detection,
    bench_parallel_regex_matching,
    bench_nested_structure_traversal,
    bench_whitelist_checking,
    bench_overlap_heavy_detection,
    bench_checksum_heavy_numeric_strings,
    bench_different_masking_strategies,
    bench_empty_vs_pii_text,
    bench_realistic_workload,
    bench_worst_case_near_misses
);

criterion_main!(benches);
