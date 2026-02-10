# Rust-Accelerated MCP Gateway Plugins

This directory contains high-performance Rust implementations of compute-intensive MCP Gateway plugins, built with PyO3 for seamless Python integration.

## 🚀 Performance Benefits

| Plugin | Python (baseline) | Rust | Speedup |
|--------|------------------|------|---------|
| PII Filter | ~10ms/request | ~1-2ms/request | **5-10x** |
| Secrets Detection | ~5ms/request | ~0.8ms/request | **5-8x** |
| SQL Sanitizer | ~3ms/request | ~0.6ms/request | **4-6x** |

**Overall Impact**: 3-5x gateway throughput improvement with all Rust plugins enabled.

## 📦 Installation

### Pre-compiled Wheels (Recommended)

```bash
# Install MCP Gateway with Rust acceleration
pip install mcpgateway[rust]
```

Supported platforms:
- Linux x86_64 (glibc 2.17+)
- macOS x86_64 (10.12+)
- macOS ARM64 (11.0+)
- Windows x86_64

### Building from Source

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install maturin
pip install maturin

# Build and install
cd plugins_rust
maturin develop --release
```

## 🏗 Architecture

### Directory Structure

```
plugins_rust/
├── Cargo.toml              # Rust dependencies and build config
├── pyproject.toml          # Python packaging config
├── README.md               # This file - Quick start guide
├── QUICKSTART.md           # Getting started guide
├── Makefile                # Build automation
├── src/
│   ├── lib.rs              # PyO3 module entry point
│   └── pii_filter/         # PII Filter implementation
│       ├── mod.rs          # Module exports
│       ├── detector.rs     # Core detection logic
│       ├── patterns.rs     # Regex pattern compilation
│       ├── masking.rs      # Masking strategies
│       └── config.rs       # Configuration types
├── benches/                # Rust criterion benchmarks
│   └── pii_filter.rs
├── benchmarks/             # Python vs Rust comparison
│   ├── README.md           # Benchmarking guide
│   ├── compare_pii_filter.py
│   ├── results/            # JSON benchmark results
│   └── docs/               # Benchmark documentation
├── tests/                  # Integration tests
│   └── integration.rs
└── docs/                   # Development documentation
    ├── implementation-guide.md  # Implementation details
    └── build-and-test.md        # Build and test results
```

### Python Integration

Rust plugins are **automatically detected** at runtime with graceful fallback:

```python
# Python side (plugins/pii_filter/pii_filter.py)
try:
    from plugins_rust import PIIDetectorRust
    detector = PIIDetectorRust(config)  # 5-10x faster
except ImportError:
    detector = PythonPIIDetector(config)  # Fallback
```

No code changes needed! The plugin automatically uses the fastest available implementation.

## 🔧 Development

### Build for Development

```bash
# Fast debug build
maturin develop

# Optimized release build
maturin develop --release
```

### Run Tests

```bash
# Rust unit tests
cargo test

# Python integration tests
pytest ../tests/unit/mcpgateway/plugins/test_pii_filter_rust.py

# Differential tests (Rust vs Python)
pytest ../tests/differential/
```

### Run Benchmarks

```bash
# Criterion benchmarks (HTML reports in target/criterion/)
cargo bench

# Python comparison benchmarks
python benchmarks/compare_pii_filter.py
```

### Code Quality

```bash
# Format code
cargo fmt

# Lint with clippy
cargo clippy -- -D warnings

# Check for security vulnerabilities
cargo audit
```

## 🎯 Performance Optimization Techniques

### 1. RegexSet for Parallel Pattern Matching

```rust
// Instead of testing each pattern sequentially (Python):
// O(N patterns × M text length)
for pattern in patterns {
    if pattern.search(text) { ... }
}

// Use RegexSet for single-pass matching (Rust):
// O(M text length)
let set = RegexSet::new(patterns)?;
let matches = set.matches(text);  // All patterns in one pass!
```

**Result**: 5-10x faster regex matching

### 2. Copy-on-Write Strings

```rust
use std::borrow::Cow;

fn mask(text: &str, detections: &[Detection]) -> Cow<str> {
    if detections.is_empty() {
        Cow::Borrowed(text)  // Zero-copy when no PII
    } else {
        Cow::Owned(apply_masking(text, detections))
    }
}
```

**Result**: Zero allocations for clean payloads

### 3. Zero-Copy JSON Traversal

```rust
fn traverse(value: &Value) -> Vec<Detection> {
    match value {
        Value::String(s) => detect_in_string(s),
        Value::Object(map) => {
            map.values().flat_map(|v| traverse(v)).collect()
        }
        // No cloning, just references
    }
}
```

**Result**: 3-5x faster nested structure processing

### 4. Link-Time Optimization (LTO)

```toml
[profile.release]
opt-level = 3
lto = "fat"           # Whole-program optimization
codegen-units = 1     # Maximum optimization
strip = true          # Remove debug symbols
```

**Result**: Additional 10-20% speedup

## 📊 Benchmarking

### Run Official Benchmarks

```bash
cargo bench --bench pii_filter
```

Output:
```
PII Filter/detect/1KB     time:   [450.23 µs 452.45 µs 454.89 µs]
PII Filter/detect/10KB    time:   [1.8234 ms 1.8456 ms 1.8701 ms]
PII Filter/detect/100KB   time:   [14.234 ms 14.567 ms 14.901 ms]
```

Compare to Python baseline:
- 1KB: 450µs (Rust) vs 5ms (Python) = **11x faster**
- 10KB: 1.8ms (Rust) vs 50ms (Python) = **27x faster**
- 100KB: 14.5ms (Rust) vs 500ms (Python) = **34x faster**

### Profile with Flamegraph

```bash
cargo install flamegraph
cargo flamegraph --bench pii_filter
# Opens flamegraph in browser
```

## 🧪 Testing

### Differential Testing

Ensures Rust and Python produce **identical outputs**:

```bash
pytest ../tests/differential/test_pii_filter_differential.py -v
```

This runs 1000+ test cases through both implementations and asserts byte-for-byte identical results.

## 🔒 Security

### Dependency Audit

```bash
# Check for known vulnerabilities
cargo audit

# Review dependency tree
cargo tree
```

All dependencies are from crates.io with:
- \>1000 downloads/month
- Active maintenance
- Security audit history

### Memory Safety

Rust provides **guaranteed memory safety**:
- ✅ No buffer overflows
- ✅ No use-after-free
- ✅ No data races
- ✅ No null pointer dereferences

### Sanitizer Testing

```bash
# Address sanitizer (memory errors)
RUSTFLAGS="-Z sanitizer=address" cargo test --target x86_64-unknown-linux-gnu

# Thread sanitizer (data races)
RUSTFLAGS="-Z sanitizer=thread" cargo test --target x86_64-unknown-linux-gnu
```

## 📈 Monitoring

Rust plugins export the same Prometheus metrics as Python:

```python
pii_filter_detections_duration_seconds{implementation="rust"}
pii_filter_masking_duration_seconds{implementation="rust"}
pii_filter_detections_total{implementation="rust"}
```

Compare Rust vs Python in Grafana dashboards.

## 🐛 Troubleshooting

### ImportError: No module named 'plugins_rust'

**Cause**: Rust extension not built or not on Python path

**Solution**:
```bash
cd plugins_rust
maturin develop --release
```

### Symbol not found: _PyInit_plugins_rust (macOS)

**Cause**: ABI mismatch between Python versions

**Solution**:
```bash
# Use Python 3.11+ with stable ABI
pip install maturin
maturin develop --release
```

### Performance not improving

**Cause**: Debug build instead of release build

**Solution**:
```bash
# Always use --release for benchmarks
maturin develop --release
```

### Force Python implementation for debugging

```bash
export MCPGATEWAY_FORCE_PYTHON_PLUGINS=true
python -m mcpgateway.main
```

## 🚢 Deployment

### Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin
RUN pip install maturin

# Copy and build Rust plugins
COPY plugins_rust/ /app/plugins_rust/
WORKDIR /app/plugins_rust
RUN maturin build --release
RUN pip install target/wheels/*.whl

# Rest of Dockerfile...
```

### Production Checklist

- [ ] Build with `--release` flag
- [ ] Run `cargo audit` (no vulnerabilities)
- [ ] Run differential tests (100% compatibility)
- [ ] Benchmark in staging (verify 5-10x speedup)
- [ ] Monitor metrics (Prometheus)
- [ ] Gradual rollout (canary deployment)

## 📚 Additional Resources

### Project Documentation
- [Quick Start Guide](QUICKSTART.md) - Get started in 5 minutes
- [Benchmarking Guide](benchmarks/README.md) - Performance testing
- [Implementation Guide](docs/implementation-guide.md) - Architecture and design
- [Build & Test Results](docs/build-and-test.md) - Test coverage and benchmarks

### External Resources
- [PyO3 Documentation](https://pyo3.rs/)
- [maturin User Guide](https://www.maturin.rs/)
- [Rust Performance Book](https://nnethercote.github.io/perf-book/)
- [regex crate Performance](https://docs.rs/regex/latest/regex/#performance)

## 🤝 Contributing

See main [CONTRIBUTING.md](../CONTRIBUTING.md) for general guidelines.

Rust-specific requirements:
- Run `cargo fmt` before committing
- Run `cargo clippy` and fix all warnings
- Add tests for new functionality
- Add benchmarks for performance-critical code
- Update documentation

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE) file for details.
