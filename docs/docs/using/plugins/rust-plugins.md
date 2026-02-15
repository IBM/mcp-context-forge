# Rust Plugins - High-Performance Native Extensions

!!! success "Production Ready"
    Rust plugins provide **5-10x performance improvements** for computationally intensive operations while maintaining 100% API compatibility with Python plugins.

## Overview

MCP Gateway supports high-performance Rust implementations of plugins through PyO3 bindings. Each Rust plugin is fully independent with its own build configuration, providing significant performance benefits for computationally expensive operations while maintaining transparent Python integration.

### Key Benefits

- **🚀 5-10x Performance**: Native compilation, zero-copy operations, parallel processing
- **🔄 Seamless Integration**: Automatic fallback to Python when Rust unavailable
- **📦 Zero Breaking Changes**: Identical API to Python plugins
- **⚙️ Auto-Detection**: Automatically uses Rust when available
- **🛡️ Memory Safe**: Rust's ownership system prevents common bugs
- **🔧 Easy Deployment**: Single wheel package, no manual compilation needed

## Architecture

### Independent Plugin Structure

```
plugins_rust/
├── [plugin_name]/        # Each plugin is fully independent
│   ├── Cargo.toml        # Rust dependencies
│   ├── pyproject.toml    # Python packaging
│   ├── Makefile          # Build commands
│   └── src/              # Rust source code
└── [another_plugin]/     # Another independent plugin
```

### Hybrid Python + Rust Design

```
┌─────────────────────────────────────────────────────────┐
│ Python Plugin Layer (plugins/[name]/plugin.py)         │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Auto-Detection Logic                             │  │
│  │ - Check Rust availability                        │  │
│  │ - Select implementation                          │  │
│  └──────────────────────────────────────────────────┘  │
│              │                        │                 │
│      ┌───────┴──────┐        ┌───────┴────────┐       │
│      │ Rust Wrapper │        │ Python Fallback│       │
│      │ (5-10x fast)│        │ (Pure Python)  │       │
│      └───────┬──────┘        └────────────────┘       │
└──────────────┼────────────────────────────────────────┘
               │
               │ PyO3 Bindings
               ▼
┌──────────────────────────────────────┐
│ Rust Implementation (plugins_rust/) │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ Plugin Engine                  │  │
│  │ - Parallel processing          │  │
│  │ - Zero-copy operations         │  │
│  │ - Efficient algorithms         │  │
│  └────────────────────────────────┘  │
│                                      │
│  Compiled to: plugin_rust.so        │
└──────────────────────────────────────┘
```

## Installation

### Option 1: Build from Source (Recommended)

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build specific plugin
cd plugins_rust/[plugin_name]
make install

# Or build all plugins from project root
make rust-dev
```

### Option 2: Use Python Fallback

```bash
# Standard installation (Python-only)
pip install mcpgateway

# Rust plugins will gracefully fall back to Python implementations
```

## Configuration

### Plugin Configuration

No changes needed! Rust plugins use the same configuration as Python:

```yaml
# plugins/config.yaml
plugins:
  - name: "MyPlugin"
    kind: "plugins.my_plugin.my_plugin.MyPlugin"
    hooks:
      - "prompt_pre_fetch"
      - "tool_pre_invoke"
    mode: "enforce"
    priority: 50
    config:
      # Plugin-specific configuration
      option1: true
      option2: "value"
```

## Usage

### Automatic Detection

The plugin system automatically detects and uses the Rust implementation:

```python
from plugins.my_plugin.my_plugin import MyPlugin
from plugins.framework import PluginConfig

# Create plugin (automatically uses Rust if available)
config = PluginConfig(
    name="my_plugin",
    kind="plugins.my_plugin.my_plugin.MyPlugin",
    config={}
)
plugin = MyPlugin(config)

# Check which implementation is being used
print(f"Implementation: {plugin.implementation}")
# Output: "rust" or "python"
```

### Direct API Usage

You can also use the implementations directly:

```python
# Use Rust implementation explicitly
from plugin_rust import PluginRust

config = {"option1": True, "option2": "value"}
plugin = PluginRust(config)

# Use plugin methods
result = plugin.process(data)
```

## Verification

### Check Installation

```bash
# Verify Rust plugin is available
python -c "from plugin_rust import PluginRust; print('✓ Rust plugin available')"

# Check implementation being used
python -c "
from plugins.my_plugin.my_plugin import MyPlugin
from plugins.framework import PluginConfig
config = PluginConfig(name='test', kind='test', config={})
plugin = MyPlugin(config)
print(f'Implementation: {plugin.implementation}')
"
```

### Logging

The gateway logs which implementation is being used:

```
# With Rust available
INFO - ✓ Plugin: Using Rust implementation (5-10x faster)

# Without Rust
WARNING - Plugin: Using Python implementation
WARNING - 💡 Build Rust plugins for better performance
```

## Building from Source

### Prerequisites

- Rust 1.70+ (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
- Python 3.11+
- maturin (`pip install maturin`)

### Build Steps

```bash
# Navigate to a specific Rust plugin directory
cd plugins_rust/pii_filter

# Build in development mode (with debug symbols)
maturin develop

# Build in release mode (optimized)
maturin develop --release

# Build wheel package
maturin build --release
```

### Using Make

```bash
# From project root (builds all plugins)
make rust-dev              # Build and install (development mode)
make rust-build            # Build release wheel
make rust-test             # Run Rust unit tests
make rust-verify           # Verify installation

# From individual plugin directory
cd plugins_rust/pii_filter
make develop               # Build and install
make test                  # Run tests
make bench                 # Run benchmarks
make bench-compare         # Compare Rust vs Python performance
```

## Performance Benchmarking

### Built-in Benchmarks

```bash
# Run Rust benchmarks (Criterion) for a specific plugin
cd plugins_rust/pii_filter
make bench

# Run Python vs Rust comparison
make bench-compare

# Or from project root (runs all plugin benchmarks)
make rust-bench
```

### Sample Benchmark Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PII Filter Performance Comparison: Python vs Rust
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Single SSN Detection
────────────────────────────────────────────────────────────────
Python: 0.150 ms (7.14 MB/s)
Rust:   0.020 ms (53.57 MB/s)
Speedup: 7.5x faster

2. Multiple PII Types Detection
────────────────────────────────────────────────────────────────
Python: 0.300 ms (3.57 MB/s)
Rust:   0.040 ms (26.79 MB/s)
Speedup: 7.5x faster

3. Large Text Performance (1000 PII instances)
────────────────────────────────────────────────────────────────
Python: 150.000 ms (0.71 MB/s)
Rust:   18.000 ms (5.95 MB/s)
Speedup: 8.3x faster

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Average Speedup: 7.8x
✓ GREAT: 5-10x speedup - Recommended for production
```

## Testing

### Running Tests

```bash
# Rust unit tests (from a specific plugin directory)
cd plugins_rust/pii_filter
cargo test

# Python integration tests
pytest tests/unit/mcpgateway/plugins/test_pii_filter_rust.py

# Differential tests (Rust vs Python compatibility)
pytest tests/differential/test_pii_filter_differential.py

# Or use make
make rust-test-all         # Run all tests
```

### Test Coverage

The Rust plugin system includes comprehensive testing:

- **Rust Unit Tests**: 14 tests covering core Rust functionality
- **Python Integration Tests**: 45 tests covering PyO3 bindings
- **Differential Tests**: 40+ tests ensuring Rust = Python outputs
- **Performance Tests**: Benchmarks verifying >5x speedup

## Troubleshooting

### Rust Plugin Not Available

**Symptom**: Logs show "Using Python implementation"

**Solutions**:
```bash
# 1. Check if Rust extension is installed
python -c "from pii_filter_rust import PIIDetectorRust; print('OK')"

# 2. Build from source
cd plugins_rust/pii_filter
maturin develop --release
```

### Import Errors

**Symptom**: `ImportError: cannot import name 'PIIDetectorRust'`

**Solutions**:
```bash
# 1. Verify installation
pip list | grep mcpgateway-pii-filter

# 2. Rebuild
cd plugins_rust/pii_filter
maturin develop --release

# 3. Check Python version (requires 3.11+)
python --version
```

### Performance Not Improved

**Symptom**: No performance difference between Python and Rust

**Checks**:
```python
# Verify Rust implementation is being used
from plugins.my_plugin.my_plugin import MyPlugin
plugin = MyPlugin(config)
assert plugin.implementation == "rust", "Not using Rust!"
```

### Build Failures

**Symptom**: `maturin develop` fails

**Common Causes**:

1. **Rust not installed**: Install from https://rustup.rs
2. **Wrong Rust version**: Update with `rustup update`
3. **Missing dependencies**: `cargo clean && cargo build`
4. **Python version mismatch**: Ensure Python 3.11+

## Development Guide

### Creating New Rust Plugins

1. **Create Plugin Directory**:
```bash
mkdir plugins_rust/my_plugin
cd plugins_rust/my_plugin
```

2. **Initialize Rust Project**:
```bash
# Create Cargo.toml, pyproject.toml, Makefile
# See existing plugins for templates
```

3. **Implement PyO3 Bindings**:
```rust
// src/lib.rs
use pyo3::prelude::*;

#[pyclass]
pub struct MyPluginRust {
    // Plugin state
}

#[pymethods]
impl MyPluginRust {
    #[new]
    pub fn new(config: &PyDict) -> PyResult<Self> {
        Ok(Self { /* ... */ })
    }

    pub fn process(&self, text: &str) -> PyResult<String> {
        Ok(text.to_uppercase())
    }
}

#[pymodule]
fn my_plugin_rust(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<MyPluginRust>()?;
    Ok(())
}
```

4. **Create Python Wrapper**:
```python
# plugins/my_plugin/my_plugin_rust.py
from my_plugin_rust import MyPluginRust

class RustMyPlugin:
    def __init__(self, config):
        self._rust = MyPluginRust(config.model_dump())

    def process(self, text: str) -> str:
        return self._rust.process(text)
```

5. **Add Auto-Detection**:
```python
# plugins/my_plugin/my_plugin.py
try:
    from .my_plugin_rust import RustMyPlugin
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

class MyPlugin(Plugin):
    def __init__(self, config):
        if RUST_AVAILABLE:
            self.impl = RustMyPlugin(config)
        else:
            self.impl = PythonMyPlugin(config)
```

### Best Practices

1. **API Compatibility**: Ensure Rust and Python implementations have identical APIs
2. **Error Handling**: Convert Rust errors to Python exceptions properly
3. **Type Conversions**: Use PyO3's `extract()` and `IntoPy` for seamless conversions
4. **Testing**: Write differential tests to ensure identical behavior
5. **Documentation**: Document performance characteristics and trade-offs

## CI/CD Integration

### GitHub Actions Workflow

The repository includes automated CI/CD for Rust plugins:

```yaml
# .github/workflows/rust-plugins.yml
- Multi-platform builds (Linux, macOS, Windows)
- Rust linting (clippy, rustfmt)
- Comprehensive testing (unit, integration, differential)
- Performance benchmarking
- Security audits (cargo-audit)
- Code coverage tracking
- Automatic wheel publishing to PyPI
```

### Local CI Checks

```bash
# Run full CI pipeline locally
make rust-check            # Format, lint, test
make rust-test-all         # All test suites
make rust-bench            # Performance benchmarks
make rust-audit            # Security audit
make rust-coverage         # Code coverage report
```

## Performance Optimizations

### Rust-Specific Optimizations

1. **RegexSet for Parallel Matching**: All patterns matched in single pass (O(M) vs O(N×M))
2. **Copy-on-Write Strings**: Zero-copy when no masking needed
3. **Stack Allocation**: Minimize heap allocations for hot paths
4. **Inlining**: Aggressive inlining for small functions
5. **LTO (Link-Time Optimization)**: Enabled in release builds

### Configuration for Best Performance

```toml
# plugins_rust/Cargo.toml
[profile.release]
opt-level = 3              # Maximum optimization
lto = "fat"                # Full link-time optimization
codegen-units = 1          # Better optimization, slower compile
strip = true               # Strip symbols for smaller binary
```

## Security Considerations

### Memory Safety

- **No Buffer Overflows**: Rust's ownership system prevents them at compile-time
- **No Use-After-Free**: Borrow checker ensures memory safety
- **No Data Races**: Safe concurrency guarantees
- **Input Validation**: All Python inputs validated before processing

### Audit and Compliance

```bash
# Run security audit (from a specific plugin directory)
cd plugins_rust/pii_filter
cargo audit
```

## Future Rust Plugins

Planned Rust implementations:

- **Regex Filter**: Pattern matching and replacement (5-8x speedup)
- **JSON Repair**: Fast JSON validation and repair (10x+ speedup)
- **SQL Sanitizer**: SQL injection detection (8-10x speedup)
- **Rate Limiter**: High-throughput rate limiting (15x+ speedup)
- **Compression**: Fast compression/decompression (5-10x speedup)

## Resources

### Documentation
- [PyO3 Documentation](https://pyo3.rs)
- [Rust Book](https://doc.rust-lang.org/book/)
- [Maturin Guide](https://www.maturin.rs)

### Project Files
- `plugins_rust/README.md` - Detailed Rust plugin documentation
- `plugins_rust/IMPLEMENTATION_STATUS.md` - Implementation status and results
- `plugins_rust/BUILD_AND_TEST_RESULTS.md` - Build and test report

### Community
- GitHub Issues: https://github.com/IBM/mcp-context-forge/issues
- Contributing: See `CONTRIBUTING.md`

## Migration Guide

### From Python to Rust

If you have an existing Python plugin you want to optimize:

1. **Measure First**: Profile to identify bottlenecks
2. **Start Small**: Convert hot paths first
3. **Maintain API**: Keep identical interface for drop-in replacement
4. **Test Thoroughly**: Use differential testing
5. **Benchmark**: Verify actual performance improvements

### Gradual Migration

You don't need to convert entire plugins at once:

```python
class MyPlugin(Plugin):
    def __init__(self, config):
        # Use Rust for expensive operations
        if RUST_AVAILABLE:
            self.detector = RustDetector(config)
        else:
            self.detector = PythonDetector(config)

        # Keep other logic in Python
        self.cache = {}
        self.stats = PluginStats()

    async def process(self, payload, context):
        # Rust-accelerated detection
        results = self.detector.detect(payload.text)

        # Python logic for everything else
        self.update_stats(results)
        return self.format_response(results)
```

## Support

For issues, questions, or contributions related to Rust plugins:

1. Check existing GitHub issues
2. Review build and test documentation
3. Open a new issue with:

   - Rust/Python versions
   - Build logs
   - Error messages
   - Minimal reproduction case

---

**Status**: Production Ready
**Performance**: 5-10x faster than Python
**Compatibility**: 100% API compatible
**Installation**: `pip install mcpgateway[rust]`
