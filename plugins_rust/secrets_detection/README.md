# Secrets Detection Plugin (Rust)

High-performance secret detection plugin implemented in Rust with optimized regex pattern matching.

## Features

- **Optimized Pattern Matching**: High-performance regex-based secret detection
- **Zero-Copy PyO3 Integration**: Direct Python object traversal without JSON serialization overhead
- **Pattern Detection**: AWS keys, API tokens, private keys, database credentials, and more
- **Optimized for Large Payloads**: Direct PyO3 traversal avoids Python→JSON→Python round-trip overhead

## Prerequisites

- **Python**: 3.11+ (ABI3 compatible)
- **Rust**: Latest stable toolchain (1.70+)
- **maturin**: Python package builder for Rust extensions
- **Virtual Environment**: Activated ContextForge venv

Install prerequisites:
```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install maturin
pip install maturin
```

## Build

```bash
cd plugins_rust/secrets_detection
maturin develop --release
```

The plugin automatically integrates with the Python fallback implementation in `plugins/secrets_detection/`, providing 2-8x performance improvements when available.

## Configuration

The plugin supports extensive configuration through ContextForge plugin system:

```yaml
# plugins/config.yaml
secrets_detection:
  enabled: true
  config:
    enabled:
      aws_access_key_id: true
      aws_secret_access_key: true
      google_api_key: true
      github_token: true
      stripe_secret_key: true
      generic_api_key_assignment: false  # Broad heuristic; useful for X-API-Key/api_key=... style coverage, but can increase false positives  # pragma: allowlist secret
      slack_token: true
      private_key_block: true
      jwt_like: true
      hex_secret_32: true
      base64_24: false  # Broad intrinsic-shape heuristic; keep opt-in unless you explicitly want aggressive blocking
    redact: false                    # Replace secrets with redaction_text
    redaction_text: "***REDACTED***"
    block_on_detection: true         # Block requests containing secrets
    min_findings_to_block: 1         # Threshold for blocking
```

Warnings:
- `google_api_key`, `github_token`, and `stripe_secret_key` are specific detectors and are safe to leave enabled by default.
- `generic_api_key_assignment` is intentionally broad so it can catch header-style or assignment-style API keys across providers. It is disabled by default and should be enabled only when you want that extra coverage.
- `jwt_like`, `hex_secret_32`, and `base64_24` are also heuristic patterns. If you combine them with blocking mode, expect more false positives.

What the plugin can do:
- Catch supported provider formats directly from their intrinsic token structure, without depending on surrounding labels.
- Catch labeled assignments such as `X-API-Key: ...` when you explicitly enable the broader generic assignment heuristic. <!-- pragma: allowlist secret -->
- Keep false positives relatively low by preferring provider-specific formats over generic entropy-based matching.

What the plugin cannot do:
- It cannot guarantee 100% recall for every secret format in the ecosystem while also maintaining low false positives.
- It will not detect every arbitrary random-looking string with no provider prefix, no delimiter, and no stable structure.
- If you need coverage for a new vendor token format, the right approach is to add a dedicated high-confidence pattern instead of broadening the generic heuristic indefinitely.

## Integration with ContextForge

The Rust plugin seamlessly integrates as an acceleration layer for the existing Python plugin:

1. **Automatic Fallback**: If Rust plugin fails to load, falls back to Python implementation
2. **Hook Integration**: Supports `prompt_pre_fetch`, `tool_post_invoke`, and `resource_post_fetch` hooks
3. **Zero Configuration**: Drop-in replacement requiring no code changes
4. **Performance Logging**: Reports 2-8x speedup when Rust implementation is active

## Performance Comparison

Compare Python vs Rust implementations:

```bash
# From plugin directory
python compare_performance.py

# With custom iterations
python compare_performance.py --iterations 100 --warmup 10
```

The benchmark tests Rust vs Python implementations across multiple data sizes.

## Benchmarks

Run Criterion benchmarks:

```bash
cargo bench
```

Results are saved to `target/criterion/` with HTML reports.

## Performance Results

### Apple M1 Max Benchmarks

Tested on Apple M1 Max (10,000 iterations + 100 warmup):

| Scenario | Python | Rust | Speedup |
|----------|--------|------|---------|
| **1KB (no secrets)** | 0.073 ms | 0.010 ms | **7.17x** 🚀 |
| **1KB (with secrets)** | 0.076 ms | 0.021 ms | **3.65x** 🚀 |
| **5KB (no secrets)** | 0.348 ms | 0.042 ms | **8.25x** 🚀 |
| **5KB (with secrets)** | 0.369 ms | 0.092 ms | **4.01x** 🚀 |

**Key Findings:**
- **3.6-8.2x speedup** across all scenarios
- **Best performance gains** on clean data (no secrets): up to 8.25x faster
- **Significant improvements** even with secret detection: 3.6-4x faster
- **Consistent performance** across different data sizes and patterns

### CPU Architecture Performance

- **Apple Silicon (M1/M2)**: Consistent 1.3-1.6x speedup with optimized regex
- **x86_64**: Similar performance characteristics expected
- **ARM64**: Good performance across ARM-based systems
- **Cross-Platform**: Consistent behavior across all supported architectures

## Development

### Quick Commands

```bash
make install      # Build and install plugin
make test         # Run Rust unit tests
make test-all     # Complete test suite (install, unit tests, integration)
make compare      # Python vs Rust performance comparison
make bench        # Run Criterion benchmarks
```

### Running Tests

```bash
# Rust unit tests
make test

# Complete test suite (recommended)
make test-all     # Installs plugin, runs cargo test and Python tests

# Python unit tests
make test-python

# Performance comparison
make compare           # Full comparison
make compare-quick     # Fewer iterations
make compare-detailed  # More iterations
```

### Adding New Patterns

1. Add pattern to `src/patterns.rs`
2. Update `PATTERNS` constant
3. Add corresponding test
4. Update both Python and Rust implementations

### Performance Profiling

```bash
# Criterion benchmarks
make bench

# Flamegraph profiling (heavy workload)
make flamegraph
```

The `flamegraph` target generates an interactive CPU profiling visualization:

1. Processes 1 million messages with realistic secret patterns
2. Creates `flamegraph.svg` showing CPU time distribution
3. Open the SVG in a browser to explore the interactive visualization

**Flamegraph shows:**
- Time spent in regex pattern matching
- String allocation and manipulation overhead
- Function call hierarchy and hot paths
- Performance bottlenecks in the detection pipeline

This is more useful than benchmark flamegraphs as it avoids Criterion's parallel execution overhead and focuses on the actual secret detection workload.
