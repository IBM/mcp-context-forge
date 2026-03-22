use criterion::{Criterion, criterion_group, criterion_main};
use std::collections::HashSet;
use std::hint::black_box;
use url_reputation_rust::engine::URLReputationPlugin;
use url_reputation_rust::types::URLReputationConfig;

fn create_plugin_with_heuristics() -> URLReputationPlugin {
    let config = URLReputationConfig {
        whitelist_domains: HashSet::new(),
        allowed_patterns: Vec::new(),
        blocked_domains: HashSet::new(),
        blocked_patterns: Vec::new(),
        use_heuristic_check: true,
        entropy_threshold: 3.65,
        block_non_secure_http: true,
    };
    URLReputationPlugin::new(config)
}

fn benchmark_full_heuristic_validation(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();

    // Test URLs that trigger all heuristic checks (largest pathway)
    let test_urls = vec![
        "https://legitimate-domain-name.com/path/to/resource",
        "https://another-valid-site.org/api/v1/endpoint",
        "https://example-website.net/some/long/path/here",
        "https://test-domain-123.com/resource",
        "https://my-secure-site.io/data/fetch",
    ];

    c.bench_function("full_heuristic_validation", |b| {
        b.iter(|| {
            for url in &test_urls {
                black_box(plugin.validate_url(black_box(url)));
            }
        })
    });
}

fn benchmark_single_url_heuristic(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    let url = "https://legitimate-domain-name.com/path/to/resource";

    c.bench_function("single_url_full_heuristic", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_complex_url_heuristic(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // Complex URL with query parameters and fragments
    let url = "https://complex-domain-name.com/api/v2/users?id=123&filter=active&sort=desc#section";

    c.bench_function("complex_url_full_heuristic", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_high_entropy_detection(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // URL with high entropy domain (should fail entropy check)
    let url = "https://axb12c34d56ef78gh90ij.com/path";

    c.bench_function("high_entropy_detection", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_unicode_security_check(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // URL with mixed scripts (should fail unicode security)
    let url = "https://pаypal.com/login"; // Contains Cyrillic 'а'

    c.bench_function("unicode_security_check", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_tld_validation(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // URL with invalid TLD
    let url = "https://test-domain.invalidtld/path";

    c.bench_function("tld_validation", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_ipv4_validation(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // IPv4 URL (skips heuristic checks)
    let url = "https://192.168.1.1:8080/api";

    c.bench_function("ipv4_validation", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_ipv6_validation(c: &mut Criterion) {
    let plugin = create_plugin_with_heuristics();
    // IPv6 URL (skips heuristic checks)
    let url = "https://[2001:0db8:85a3:0000:0000:8a2e:0370:7334]:8080/api";

    c.bench_function("ipv6_validation", |b| {
        b.iter(|| {
            black_box(plugin.validate_url(black_box(url)));
        })
    });
}

fn benchmark_blocked_pattern_matching(c: &mut Criterion) {
    // Create plugin with multiple blocked patterns
    let config = URLReputationConfig {
        whitelist_domains: HashSet::new(),
        allowed_patterns: Vec::new(),
        blocked_domains: HashSet::new(),
        blocked_patterns: vec![
            r".*phishing.*".to_string(),
            r".*malware.*".to_string(),
            r".*crypto-scam.*".to_string(),
            r".*fake-bank.*".to_string(),
            r".*suspicious.*".to_string(),
        ],
        use_heuristic_check: false,
        entropy_threshold: 3.65,
        block_non_secure_http: false,
    };
    let plugin = URLReputationPlugin::new(config);

    // Test URLs that should match blocked patterns
    let blocked_urls = vec![
        "https://example.com/phishing-page",
        "https://malware-site.com/download",
        "https://crypto-scam.net/invest",
        "https://fake-bank-login.com/auth",
        "https://suspicious-domain.org/data",
    ];

    c.bench_function("blocked_pattern_matching", |b| {
        b.iter(|| {
            for url in &blocked_urls {
                black_box(plugin.validate_url(black_box(url)));
            }
        })
    });
}

fn benchmark_allowed_pattern_matching(c: &mut Criterion) {
    // Create plugin with allowed patterns
    let config = URLReputationConfig {
        whitelist_domains: HashSet::new(),
        allowed_patterns: vec![
            r"https://api\.trusted\.com/.*".to_string(),
            r"https://cdn\.safe\.net/.*".to_string(),
            r"https://.*\.internal\.corp/.*".to_string(),
        ],
        blocked_domains: HashSet::new(),
        blocked_patterns: Vec::new(),
        use_heuristic_check: false,
        entropy_threshold: 3.65,
        block_non_secure_http: false,
    };
    let plugin = URLReputationPlugin::new(config);

    // Test URLs that should match allowed patterns
    let allowed_urls = vec![
        "https://api.trusted.com/v1/users",
        "https://cdn.safe.net/assets/image.png",
        "https://service.internal.corp/data",
    ];

    c.bench_function("allowed_pattern_matching", |b| {
        b.iter(|| {
            for url in &allowed_urls {
                black_box(plugin.validate_url(black_box(url)));
            }
        })
    });
}

fn benchmark_pattern_no_match(c: &mut Criterion) {
    // Create plugin with patterns that won't match
    let config = URLReputationConfig {
        whitelist_domains: HashSet::new(),
        allowed_patterns: Vec::new(),
        blocked_domains: HashSet::new(),
        blocked_patterns: vec![
            r".*phishing.*".to_string(),
            r".*malware.*".to_string(),
            r".*crypto-scam.*".to_string(),
        ],
        use_heuristic_check: false,
        entropy_threshold: 3.65,
        block_non_secure_http: false,
    };
    let plugin = URLReputationPlugin::new(config);

    // Test URLs that won't match any patterns (worst case - checks all patterns)
    let clean_urls = vec![
        "https://legitimate-site.com/page",
        "https://normal-domain.org/api",
        "https://safe-website.net/resource",
    ];

    c.bench_function("pattern_no_match", |b| {
        b.iter(|| {
            for url in &clean_urls {
                black_box(plugin.validate_url(black_box(url)));
            }
        })
    });
}

criterion_group!(
    benches,
    benchmark_full_heuristic_validation,
    benchmark_single_url_heuristic,
    benchmark_complex_url_heuristic,
    benchmark_high_entropy_detection,
    benchmark_unicode_security_check,
    benchmark_tld_validation,
    benchmark_ipv4_validation,
    benchmark_ipv6_validation,
    benchmark_blocked_pattern_matching,
    benchmark_allowed_pattern_matching,
    benchmark_pattern_no_match
);
criterion_main!(benches);
