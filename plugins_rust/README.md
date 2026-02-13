# Rust-Accelerated ContextForge Plugins

High-performance Rust implementations of compute-intensive ContextForge plugins, built with PyO3 for seamless Python integration.

## 🚀 Performance

Rust plugins deliver 5-100x speedup over Python implementations for compute-intensive operations.

## 📁 Structure

Each plugin is fully independent with its own directory:

```
plugins_rust/
├── [plugin_name]/        # Independent plugin
│   ├── Cargo.toml        # Rust dependencies
│   ├── pyproject.toml    # Python packaging
│   ├── Makefile          # Build commands
│   └── src/              # Rust source code
└── [another_plugin]/     # Another plugin
```

## 📦 Quick Start

### Build from Source

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build specific plugin
cd plugins_rust/[plugin_name]
make install

cd plugins_rust
```

## 🔧 Development

### Per-Plugin Commands

```bash
cd plugins_rust/[plugin_name]

make dev              # Development build
make test             # Run tests
make bench            # Run benchmarks
make fmt              # Format code
make clippy           # Lint
```

### Gateway Integration

Rust plugins are **auto-detected** at runtime with graceful fallback:

```python
try:
    from plugin_rust import PluginRust  # Fast Rust implementation
    plugin = PluginRust(config)
except ImportError:
    plugin = PythonPlugin(config)  # Fallback to Python
```

Start gateway normally - Rust plugins activate automatically:

```bash
make dev              # Development server
make serve            # Production server
```


## 🧪 Testing & Verification

```bash
# Verify installation
python -c "from plugin_rust import PluginRust; print('✓ OK')"

# Run benchmarks
cd plugins_rust/[plugin_name]
make bench-compare

# Check gateway logs for Rust acceleration messages
```

## 🔒 Security

```bash
make audit            # Check vulnerabilities
```

Rust guarantees memory safety (no buffer overflows, use-after-free, data races).

## 📚 Resources

- Plugin-specific docs: `plugins_rust/[plugin_name]/README.md`
- Benchmarks: `plugins_rust/[plugin_name]/benchmarks/`
- Full docs: `docs/docs/using/plugins/rust-plugins.md`

## 🤝 Contributing

```bash
make fmt clippy test  # Before committing
```

## 📝 License

Apache License 2.0 - See [LICENSE](../LICENSE)
