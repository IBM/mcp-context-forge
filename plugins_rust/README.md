# Rust-Accelerated ContextForge Plugins

High-performance Rust implementations of compute-intensive ContextForge plugins, built with PyO3 for seamless Python integration.

## 🚀 Performance

Rust plugins deliver 5-10x speedup over Python implementations for compute-intensive operations.

## 📁 Structure

Each plugin is fully independent with its own directory:

```
plugins_rust/
├── pii_filter/               # PII detection and masking
│   ├── Cargo.toml
│   ├── pyproject.toml
│   ├── Makefile
│   └── src/
├── secrets_detection/        # Secret scanning
│   ├── Cargo.toml
│   ├── Makefile
│   └── src/
└── encoded_exfil_detection/  # Encoded exfiltration detection
    ├── Cargo.toml
    └── src/
```

## 📦 Quick Start

### Build from Source

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build a specific plugin
cd plugins_rust/pii_filter
make install

# Or build all plugins from project root
make rust-dev
```

## 🔧 Development

### Per-Plugin Commands

```bash
cd plugins_rust/pii_filter

make develop          # Development build
make test             # Run tests
make bench            # Run benchmarks
make fmt              # Format code
make clippy           # Lint
```

### Gateway Integration

Rust plugins are **auto-detected** at runtime with graceful fallback:

```python
try:
    from pii_filter_rust import PIIDetectorRust  # Fast Rust implementation
    detector = PIIDetectorRust(config)
except ImportError:
    detector = PythonPIIDetector(config)  # Fallback to Python
```

Start gateway normally - Rust plugins activate automatically:

```bash
make dev              # Development server
make serve            # Production server
```


## 🧪 Testing & Verification

```bash
# Verify PII filter installation
python -c "from pii_filter_rust import PIIDetectorRust; print('OK')"

# Run benchmarks
cd plugins_rust/pii_filter
make bench-compare
```

## 🔒 Security

```bash
cargo audit           # Check vulnerabilities (run from plugin directory)
```

Rust guarantees memory safety (no buffer overflows, use-after-free, data races).

## 📚 Resources

- Plugin-specific docs: `plugins_rust/[plugin_name]/README.md`
- Full docs: `docs/docs/using/plugins/rust-plugins.md`

## 🤝 Contributing

```bash
cargo fmt && cargo clippy && cargo test  # Before committing
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE)
