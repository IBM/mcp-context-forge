// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for json_repair performance

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use json_repair::JSONRepairPluginRust;
use std::hint::black_box;
use std::time::Duration;

fn create_plugin() -> JSONRepairPluginRust {
    JSONRepairPluginRust::new().expect("json_repair plugin init")
}

fn create_valid_cases() -> Vec<&'static str> {
    vec![
        r#"{"a":1,"b":2}"#,
        r#"{"user":{"id":42,"active":true},"tags":["x","y","z"]}"#,
        r#"{"items":[{"k":"v"},{"k2":"v2"}],"count":2}"#,
        r#"{"service":"gateway","status":"ok","latency_ms":12}"#,
    ]
}

fn create_repairable_cases() -> Vec<&'static str> {
    vec![
        r#"{"a": 1, "b": 2,}"#, // trailing comma
        "{'a': 1, 'b': 2}",     // single quotes
        "{\n'a': 1,\n'b': 2\n}", // multiline single quotes
        r#""a": 1, "b": 2"#,    // missing outer braces
    ]
}

fn create_unrepairable_cases() -> Vec<&'static str> {
    vec![
        "not-json-at-all",
        "just some plain text without colons",
        "{ this is not valid json syntax",
        "}",
    ]
}

fn make_sized_object_kb(target_kb: usize, repairable: bool) -> String {
    let mut parts = Vec::new();
    let mut idx = 0usize;
    while parts.join(",").len() < target_kb * 1024 {
        if repairable {
            parts.push(format!("'k{}': 'value_{}'", idx, idx));
        } else {
            parts.push(format!(r#""k{}":"value_{}""#, idx, idx));
        }
        idx += 1;
    }
    let body = parts.join(",");
    if repairable {
        format!("{{{},}}", body)
    } else {
        format!("{{{}}}", body)
    }
}

fn bench_repair_cases(c: &mut Criterion) {
    let plugin = create_plugin();

    let mut group = c.benchmark_group("repair_cases");
    group.measurement_time(Duration::from_millis(600));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    for (i, input) in create_valid_cases().iter().enumerate() {
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new("valid", i), input, |b, text| {
            b.iter(|| plugin.repair(black_box(text)));
        });
    }

    for (i, input) in create_repairable_cases().iter().enumerate() {
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new("repairable", i), input, |b, text| {
            b.iter(|| plugin.repair(black_box(text)));
        });
    }

    for (i, input) in create_unrepairable_cases().iter().enumerate() {
        group.throughput(Throughput::Bytes(input.len() as u64));
        group.bench_with_input(BenchmarkId::new("unrepairable", i), input, |b, text| {
            b.iter(|| plugin.repair(black_box(text)));
        });
    }

    group.finish();
}

fn bench_batch_processing(c: &mut Criterion) {
    let plugin = create_plugin();

    let mut group = c.benchmark_group("batch_processing");
    group.measurement_time(Duration::from_millis(600));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(40);

    let valid = create_valid_cases();
    let repairable = create_repairable_cases();
    let unrepairable = create_unrepairable_cases();

    let mut mixed = Vec::new();
    mixed.extend_from_slice(&valid);
    mixed.extend_from_slice(&repairable);
    mixed.extend_from_slice(&unrepairable);
    let total_bytes: u64 = mixed.iter().map(|s| s.len() as u64).sum();

    group.throughput(Throughput::Bytes(total_bytes));
    group.bench_function("mixed_batch", |b| {
        b.iter(|| {
            for text in &mixed {
                let _ = plugin.repair(black_box(text));
            }
        });
    });

    group.finish();
}

fn bench_text_sizes(c: &mut Criterion) {
    let plugin = create_plugin();

    let mut group = c.benchmark_group("text_sizes");
    // Keep enough budget for 200KB repairable samples to avoid Criterion
    // "Unable to complete N samples in target time" warnings.
    group.measurement_time(Duration::from_millis(3000));
    group.warm_up_time(Duration::from_millis(120));
    group.sample_size(40);

    // Representative size tiers used by compare_performance.py as well.
    let sizes_kb = [1usize, 5, 50, 200];

    for size in sizes_kb {
        let valid = make_sized_object_kb(size, false);
        let repairable = make_sized_object_kb(size, true);

        group.throughput(Throughput::Bytes(valid.len() as u64));
        group.bench_with_input(BenchmarkId::new("valid_kb", size), &valid, |b, text| {
            b.iter(|| plugin.repair(black_box(text)));
        });

        group.throughput(Throughput::Bytes(repairable.len() as u64));
        group.bench_with_input(
            BenchmarkId::new("repairable_kb", size),
            &repairable,
            |b, text| {
                b.iter(|| plugin.repair(black_box(text)));
            },
        );
    }

    group.finish();
}

fn bench_early_exit_vs_full_path(c: &mut Criterion) {
    let plugin = create_plugin();

    let mut group = c.benchmark_group("early_exit_vs_full_path");
    group.measurement_time(Duration::from_millis(600));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    let valid = r#"{"a":1,"b":2,"c":[1,2,3],"d":{"ok":true}}"#;
    let repairable = r#"{"a":1,"b":2,"c":[1,2,3],}"#;

    group.throughput(Throughput::Bytes(valid.len() as u64));
    group.bench_function("already_valid_early_exit", |b| {
        b.iter(|| plugin.repair(black_box(valid)));
    });

    group.throughput(Throughput::Bytes(repairable.len() as u64));
    group.bench_function("repairable_full_path", |b| {
        b.iter(|| plugin.repair(black_box(repairable)));
    });

    group.finish();
}

criterion_group!(
    benches,
    bench_repair_cases,
    bench_batch_processing,
    bench_text_sizes,
    bench_early_exit_vs_full_path
);
criterion_main!(benches);
