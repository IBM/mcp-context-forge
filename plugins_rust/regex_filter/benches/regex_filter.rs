// Copyright 2026
// SPDX-License-Identifier: Apache-2.0
//
// Criterion benchmarks for regex filter performance

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use regex::Regex;
use regex_filter::{SearchReplace, SearchReplaceConfig, SearchReplacePluginRust};
use std::hint::black_box;
use std::time::Duration;

fn create_test_config() -> SearchReplaceConfig {
    // Same patterns as compare_performance.py
    let patterns = vec![
        // Content moderation - profanity filtering
        (r"\bcrap\b", "crud"),
        (r"\bdamn\b", "darn"),
        (r"\bhell\b", "heck"),
        // Terminology standardization - expand abbreviations for clarity
        (r"\bAI\b", "artificial intelligence"),
        // Brand name normalization - consistent formatting
        (r"\bMicrosoft\b", "MS"),
        (r"\bIBM\b", "International Business Machines"),
    ];

    let mut words = Vec::new();
    let mut pattern_strings = Vec::new();

    for (search, replace) in patterns {
        if let Ok(compiled) = Regex::new(search) {
            pattern_strings.push(search.to_string());
            words.push(SearchReplace {
                search: search.to_string(),
                replace: replace.to_string(),
                compiled,
            });
        }
    }

    let pattern_set = if !pattern_strings.is_empty() {
        regex::RegexSet::new(&pattern_strings).ok()
    } else {
        None
    };

    SearchReplaceConfig { words, pattern_set }
}

// Create realistic conversation data matching compare_performance.py
fn create_clean_messages() -> Vec<&'static str> {
    vec![
        "I can help you design a scalable microservices architecture. Let's start by discussing your requirements for service discovery and load balancing.",
        "For monitoring distributed systems, I recommend implementing observability with metrics, logs, and traces. Consider using Prometheus for metrics collection and Grafana for visualization.",
        "The deployment pipeline should include automated testing, security scanning, and gradual rollout strategies. Blue-green deployments minimize downtime during updates.",
        "Your gateway layer should handle cross-cutting concerns like rate limiting, authentication, request routing, and protocol translation between clients and backend services.",
        "Database design is crucial for performance. Consider using connection pooling, read replicas, and caching strategies to optimize query performance at scale.",
        "Container orchestration with Kubernetes provides automated deployment, scaling, and management of containerized applications across clusters of hosts.",
    ]
}

fn create_pattern_messages() -> Vec<&'static str> {
    vec![
        // Content moderation - profanity replacement
        "This legacy codebase is crap and needs refactoring. The damn architecture makes it hard to maintain and extend functionality.",
        "I'm frustrated with this buggy implementation. It's a piece of crap that crashes constantly. Damn, we need to rewrite this module completely.",
        "The documentation is crap and outdated. Damn it, nobody can understand how to use this API without better examples and explanations.",
        // Terminology standardization - AI expansion for clarity
        "The AI model uses deep learning for natural language processing. Our AI system can analyze sentiment and extract entities from text using AI algorithms.",
        "Modern AI applications leverage neural networks. The AI pipeline includes data preprocessing, model training, and inference optimization for AI deployment.",
        "This AI solution provides real-time predictions. The AI framework supports multiple AI models running in parallel for improved throughput.",
        // Brand name standardization - consistent formatting
        "Microsoft Azure and IBM Cloud are leading providers. Microsoft offers Office 365 while IBM provides Watson services for enterprise customers.",
        "The solution integrates with Microsoft Teams and IBM Db2 databases. Microsoft's cloud platform complements IBM's enterprise software offerings.",
        "We're evaluating Microsoft SQL Server versus IBM Db2. Both Microsoft and IBM offer robust enterprise database solutions with different strengths.",
        // Mixed patterns - realistic technical discussion with issues
        "The damn AI integration keeps failing. This crap code needs a complete rewrite. Microsoft's documentation doesn't help much either.",
        "I'm working on the AI pipeline but it's crap. The damn performance is terrible. We should consider IBM's solution instead of this mess.",
        "The AI model training is slow as hell. This damn implementation is crap. Microsoft Azure ML might be faster than our current setup.",
    ]
}

// Benchmark apply_patterns function with realistic conversation data
fn bench_apply_patterns(c: &mut Criterion) {
    let config = create_test_config();
    let plugin = SearchReplacePluginRust { config };

    let mut group = c.benchmark_group("apply_patterns");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    // Clean messages (no patterns)
    let clean_messages = create_clean_messages();
    for (i, message) in clean_messages.iter().enumerate() {
        group.throughput(Throughput::Bytes(message.len() as u64));
        group.bench_with_input(BenchmarkId::new("clean_message", i), message, |b, msg| {
            b.iter(|| plugin.apply_patterns(black_box(msg)));
        });
    }

    // Pattern messages (with patterns to match)
    let pattern_messages = create_pattern_messages();
    for (i, message) in pattern_messages.iter().enumerate() {
        group.throughput(Throughput::Bytes(message.len() as u64));
        group.bench_with_input(BenchmarkId::new("pattern_message", i), message, |b, msg| {
            b.iter(|| plugin.apply_patterns(black_box(msg)));
        });
    }

    group.finish();
}

// Benchmark batch processing
fn bench_batch_processing(c: &mut Criterion) {
    let config = create_test_config();
    let plugin = SearchReplacePluginRust { config };

    let mut group = c.benchmark_group("batch_processing");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    // All clean messages
    let clean_messages = create_clean_messages();
    let clean_total_bytes: u64 = clean_messages.iter().map(|m| m.len() as u64).sum();
    group.throughput(Throughput::Bytes(clean_total_bytes));
    group.bench_function("all_clean_messages", |b| {
        b.iter(|| {
            for message in &clean_messages {
                let _ = plugin.apply_patterns(black_box(message));
            }
        });
    });

    // All pattern messages
    let pattern_messages = create_pattern_messages();
    let pattern_total_bytes: u64 = pattern_messages.iter().map(|m| m.len() as u64).sum();
    group.throughput(Throughput::Bytes(pattern_total_bytes));
    group.bench_function("all_pattern_messages", |b| {
        b.iter(|| {
            for message in &pattern_messages {
                let _ = plugin.apply_patterns(black_box(message));
            }
        });
    });

    // Mixed messages
    let mut mixed_messages = Vec::new();
    mixed_messages.extend_from_slice(&clean_messages);
    mixed_messages.extend_from_slice(&pattern_messages);
    let mixed_total_bytes: u64 = mixed_messages.iter().map(|m| m.len() as u64).sum();
    group.throughput(Throughput::Bytes(mixed_total_bytes));
    group.bench_function("mixed_messages", |b| {
        b.iter(|| {
            for message in &mixed_messages {
                let _ = plugin.apply_patterns(black_box(message));
            }
        });
    });

    group.finish();
}

// Benchmark early exit optimization
fn bench_early_exit(c: &mut Criterion) {
    let config = create_test_config();
    let plugin = SearchReplacePluginRust { config };

    let mut group = c.benchmark_group("early_exit_optimization");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    // Clean text (should trigger early exit via RegexSet)
    let clean_text = "I can help you design a scalable microservices architecture. Let's start by discussing your requirements for service discovery and load balancing.";
    group.throughput(Throughput::Bytes(clean_text.len() as u64));
    group.bench_function("clean_text_early_exit", |b| {
        b.iter(|| plugin.apply_patterns(black_box(clean_text)));
    });

    // Text with patterns (full processing)
    let pattern_text = "The damn AI integration keeps failing. This crap code needs a complete rewrite. Microsoft's documentation doesn't help much either.";
    group.throughput(Throughput::Bytes(pattern_text.len() as u64));
    group.bench_function("pattern_text_full_processing", |b| {
        b.iter(|| plugin.apply_patterns(black_box(pattern_text)));
    });

    group.finish();
}

// Benchmark different text sizes (matching compare_performance.py 1KB and 5KB scenarios)
fn bench_text_sizes(c: &mut Criterion) {
    let config = create_test_config();
    let plugin = SearchReplacePluginRust { config };

    let mut group = c.benchmark_group("text_sizes");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    let clean_messages = create_clean_messages();
    let pattern_messages = create_pattern_messages();

    // 1KB clean (no patterns)
    let mut text_1kb_clean = String::new();
    while text_1kb_clean.len() < 1024 {
        for msg in &clean_messages {
            text_1kb_clean.push_str(msg);
            text_1kb_clean.push(' ');
            if text_1kb_clean.len() >= 1024 {
                break;
            }
        }
    }
    group.throughput(Throughput::Bytes(text_1kb_clean.len() as u64));
    group.bench_function("1kb_no_patterns", |b| {
        b.iter(|| plugin.apply_patterns(black_box(&text_1kb_clean)));
    });

    // 1KB with patterns
    let mut text_1kb_patterns = String::new();
    while text_1kb_patterns.len() < 1024 {
        for msg in &pattern_messages {
            text_1kb_patterns.push_str(msg);
            text_1kb_patterns.push(' ');
            if text_1kb_patterns.len() >= 1024 {
                break;
            }
        }
    }
    group.throughput(Throughput::Bytes(text_1kb_patterns.len() as u64));
    group.bench_function("1kb_with_patterns", |b| {
        b.iter(|| plugin.apply_patterns(black_box(&text_1kb_patterns)));
    });

    // 5KB clean (no patterns)
    let mut text_5kb_clean = String::new();
    while text_5kb_clean.len() < 5120 {
        for msg in &clean_messages {
            text_5kb_clean.push_str(msg);
            text_5kb_clean.push(' ');
            if text_5kb_clean.len() >= 5120 {
                break;
            }
        }
    }
    group.throughput(Throughput::Bytes(text_5kb_clean.len() as u64));
    group.bench_function("5kb_no_patterns", |b| {
        b.iter(|| plugin.apply_patterns(black_box(&text_5kb_clean)));
    });

    // 5KB with patterns
    let mut text_5kb_patterns = String::new();
    while text_5kb_patterns.len() < 5120 {
        for msg in &pattern_messages {
            text_5kb_patterns.push_str(msg);
            text_5kb_patterns.push(' ');
            if text_5kb_patterns.len() >= 5120 {
                break;
            }
        }
    }
    group.throughput(Throughput::Bytes(text_5kb_patterns.len() as u64));
    group.bench_function("5kb_with_patterns", |b| {
        b.iter(|| plugin.apply_patterns(black_box(&text_5kb_patterns)));
    });

    group.finish();
}

// Benchmark pattern complexity
fn bench_pattern_complexity(c: &mut Criterion) {
    let mut group = c.benchmark_group("pattern_complexity");
    group.measurement_time(Duration::from_millis(500));
    group.warm_up_time(Duration::from_millis(100));
    group.sample_size(50);

    let test_text = "The AI system integrates with Microsoft Azure and IBM Cloud. This damn crap code needs refactoring.";

    // Few patterns (2)
    let few_patterns = vec![(r"\bcrap\b", "crud"), (r"\bdamn\b", "darn")];
    let few_config = create_config_from_patterns(&few_patterns);
    let few_plugin = SearchReplacePluginRust { config: few_config };
    group.throughput(Throughput::Bytes(test_text.len() as u64));
    group.bench_function("few_patterns_2", |b| {
        b.iter(|| few_plugin.apply_patterns(black_box(test_text)));
    });

    // Many patterns (6) - same as compare_performance.py
    let many_config = create_test_config();
    let many_plugin = SearchReplacePluginRust {
        config: many_config,
    };
    group.throughput(Throughput::Bytes(test_text.len() as u64));
    group.bench_function("many_patterns_6", |b| {
        b.iter(|| many_plugin.apply_patterns(black_box(test_text)));
    });

    group.finish();
}

// Helper function to create config from pattern list
fn create_config_from_patterns(patterns: &[(&str, &str)]) -> SearchReplaceConfig {
    let mut words = Vec::new();
    let mut pattern_strings = Vec::new();

    for (search, replace) in patterns {
        if let Ok(compiled) = Regex::new(search) {
            pattern_strings.push(search.to_string());
            words.push(SearchReplace {
                search: search.to_string(),
                replace: replace.to_string(),
                compiled,
            });
        }
    }

    let pattern_set = if !pattern_strings.is_empty() {
        regex::RegexSet::new(&pattern_strings).ok()
    } else {
        None
    };

    SearchReplaceConfig { words, pattern_set }
}

criterion_group!(
    benches,
    bench_apply_patterns,
    bench_batch_processing,
    bench_early_exit,
    bench_text_sizes,
    bench_pattern_complexity
);

criterion_main!(benches);
