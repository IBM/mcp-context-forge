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

# Build all plugins (from repo root)
make rust-install

# Or build specific plugin
cd plugins_rust/pii_filter && make install
```

## 🔧 Development

```bash
# Per-plugin commands (run from plugin directory, e.g. plugins_rust/pii_filter)
make install          # Install plugin
make test             # Run tests
make test-verbose     # Run tests with output
make bench            # Run benchmarks
make fmt              # Format code
make fmt-check        # Check format (CI)
make clippy           # Lint
make doc              # Build Rust docs

# From repo root (all plugins)
make rust-test        # Test all
make rust-check       # Format, clippy, test all
make rust-audit       # Security audit
```

## 🧪 Verification

```bash
# Verify installation (PII filter example)
python -c "from pii_filter_rust.pii_filter_rust import PIIDetectorRust; print('✓ Rust PII filter OK')"

# Security audit (per plugin)
cd plugins_rust/pii_filter && cargo audit
```

Rust plugins auto-activate with graceful Python fallback. Start gateway normally with `make dev` or `make serve`.

## 🔒 Security

```bash
make rust-audit       # Audit all plugins (from repo root)
# Or per plugin:
cd plugins_rust/pii_filter && cargo audit
```

Rust provides guaranteed memory safety (no buffer overflows, use-after-free, data races, or null pointer dereferences).

## 📚 Resources

- Plugin-specific docs: `plugins_rust/[plugin_name]/README.md`
- Full docs: `docs/docs/using/plugins/rust-plugins.md`

## 🤝 Contributing

```bash
make rust-check       # Format, clippy, test (from repo root)
# Or per plugin: make fmt && make fmt-check && make clippy && make test
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE)
