# Rust-Accelerated ContextForge Plugins

High-performance Rust implementations of compute-intensive ContextForge plugins, built with PyO3 for seamless Python integration.

## 🚀 Performance

Rust plugins deliver 5-10x speedup over Python implementations for compute-intensive operations.

## 📁 Structure

Each plugin is a fully independent crate with its own directory. CI discovers plugins by scanning for direct subdirectories that contain a `Cargo.toml`.

```
crates/plugins/
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

## 📦 Installation

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build all maturin crates in the workspace (from repo root; includes crates/plugins, crates/tools, etc.)
make rust-install

# Or build a specific plugin
cd crates/plugins/pii_filter && make install
```

## 🔧 Development

```bash
# Per-plugin commands (run from plugin directory, e.g. crates/plugins/pii_filter)
make install          # Install plugin
make test             # Run tests
make test-verbose     # Run tests with output
make bench            # Run benchmarks
make fmt              # Format code
make fmt-check        # Check format (CI)
make clippy           # Lint
make doc              # Build Rust docs
make audit            # Security audit (cargo audit)

# All maturin crates (from repo root)
make rust-test        # Test workspace
make rust-check       # Format, clippy, test all
make rust-audit       # Security audit
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

Start gateway normally - Rust plugins activate automatically.

## 🧪 Verification

```bash
# Verify installation (PII filter example)
python -c "from pii_filter_rust.pii_filter_rust import PIIDetectorRust; print('✓ Rust PII filter OK')"

# Run benchmarks
cd crates/plugins/pii_filter && make bench
# Security audit (from repo root)
make rust-audit
# Or per plugin:
cd crates/plugins/pii_filter && cargo audit
```

## 🔒 Security

```bash
make rust-audit       # Audit all plugins (from repo root)
# Or per plugin:
cd crates/plugins/pii_filter && cargo audit
```

Rust provides guaranteed memory safety (no buffer overflows, use-after-free, data races, or null pointer dereferences). Rust plugins auto-activate with graceful Python fallback; start the gateway with `make dev` or `make serve`.

## 📚 Resources

- Plugin-specific docs: `crates/plugins/[plugin_name]/README.md`
- Full docs: `docs/docs/using/plugins/rust-plugins.md`

## 🤝 Contributing

```bash
make rust-check       # Format, clippy, test (from repo root)
# Or per plugin: make fmt && make fmt-check && make clippy && make test
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE)
