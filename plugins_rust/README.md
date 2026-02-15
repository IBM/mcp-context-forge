# Rust-Accelerated MCP Gateway Plugins

High-performance Rust implementations of compute-intensive MCP Gateway plugins, built with PyO3 for seamless Python integration.

## 🚀 Performance Benefits

| Plugin | Python (baseline) | Rust | Speedup |
|--------|------------------|------|---------|
| PII Filter | ~10ms/request | ~1-2ms/request | **5-10x** |

**Overall Impact**: 5-10x speedup for PII detection workloads.

## 📦 Installation

### Building from Source

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install maturin
pip install maturin

# Build and install (from repo root)
cd plugins_rust
maturin develop --release
```

## 🏗 Architecture

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
make dev              # Release build (recommended)
make dev-debug        # Debug build
```

### Run Tests

```bash
make test             # Rust unit tests
make test-python      # Python integration tests
```

### Run Benchmarks

```bash
make bench            # Criterion benchmarks
make bench-compare    # Python vs Rust comparison
```

### Code Quality

```bash
make fmt              # Format code
make clippy           # Lint with clippy
make audit            # Security audit
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

### Run Benchmarks

```bash
make bench            # Criterion benchmarks
make bench-compare    # Python vs Rust comparison
```

## 🧪 Testing

```bash
make test             # Rust unit tests
make test-python      # Python integration tests
```

## 🔒 Security

```bash
make audit            # Check for vulnerabilities
```

Rust provides guaranteed memory safety (no buffer overflows, use-after-free, data races, or null pointer dereferences).


## 🚢 Deployment

```bash
make dev              # Build and install
make audit            # Security check
make test             # Verify tests pass
```

## 📚 Resources

- [QUICKSTART.md](QUICKSTART.md) - Quick start guide
- [pii_filter/benchmarks/README.md](pii_filter/benchmarks/README.md) - Benchmarking guide
- [pii_filter/docs/](pii_filter/docs/) - Implementation docs

## 🤝 Contributing

```bash
make fmt              # Format before commit
make clippy           # Fix all warnings
make test             # Add tests for new code
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE) file for details.
