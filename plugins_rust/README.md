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

## 📦 Installation

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build all plugins
cd plugins_rust && make install

# Or build specific plugin
cd pii_filter && make install
```

## 🔧 Development

```bash
# Per-plugin commands (run from plugin directory)
make install          # Install plugin
make test             # Run tests
make bench            # Run benchmarks
make fmt              # Format code
make clippy           # Lint

# All plugins (run from plugins_rust directory)
make test             # Test all
make fmt              # Format all
make clippy           # Lint all
```

## 🧪 Verification

```bash
# Verify installation
python -c "from pii_filter import PIIDetectorRust; print('OK')"

# Security audit
cd plugins_rust/pii_filter && cargo audit
```

Rust plugins auto-activate with graceful Python fallback. Start gateway normally with `make dev` or `make serve`.

## 📚 Resources

- Plugin-specific docs: `plugins_rust/[plugin_name]/README.md`
- Full docs: `docs/docs/using/plugins/rust-plugins.md`

## 🤝 Contributing

```bash
cargo fmt && cargo clippy && cargo test  # Before committing
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE)
