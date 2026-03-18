# Rust Plugins - High-Performance Native Extensions

!!! success "Production Ready"
    Rust plugins provide **5-10x performance improvements** for computationally intensive operations while maintaining 100% API compatibility with Python plugins.

## Overview

MCP Gateway supports high-performance Rust implementations of plugins through PyO3 bindings. Each Rust plugin is fully independent with its own build configuration, providing significant performance benefits for computationally expensive operations while maintaining transparent Python integration.

### Key Benefits

- **🚀 5-10x Performance**: Native compilation, zero-copy operations, parallel processing
- **🔄 Seamless Integration**: Plugin-defined integration model, including auto-detect wrappers and dedicated Rust-only wrappers
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

# Auto-detect wrappers can fall back to Python implementations
# Dedicated Rust-only wrappers such as RustPIIFilterPlugin will fail fast instead
```

## Configuration

### Plugin Configuration

No changes needed! Rust plugins use the same plugin configuration shape as Python plugins:

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

### Rust PII Filter in This Branch

The Rust PII filter now ships as a dedicated plugin path rather than a helper
module tucked under the Python plugin package.

- Plugin class: `plugins.pii_filter_rust.pii_filter_rust.RustPIIFilterPlugin`
- Canonical runtime config: `plugins/config.yaml`
- Plugin metadata manifest: `plugins/pii_filter_rust/plugin-manifest.yaml`
- Compiled detector import: `from pii_filter_rust import PIIDetectorRust`

This wrapper is intentionally Rust-first:

- It uses the Rust detector directly instead of silently falling back to the
  Python detector.
- It passes plugin configuration through to Rust unchanged; the Rust detector is
  the source of truth for supported config keys and defaults.
- If the `pii_filter_rust` package is not installed, plugin initialization fails
  fast with `ImportError`.
- The shipped Rust plugin entry in `plugins/config.yaml` defaults to
  `default_mask_strategy: "partial"` with `block_on_detection: false`.

Supported Rust PII config keys are defined by the shipped Rust plugin entry in
`plugins/config.yaml`. On this branch they include detector toggles for SSN,
BSN, credit card, email, phone, IP address, date of birth, passport, bank
account, medical record, full name, street address, US ZIP code, US EIN, US
ITIN, and driver license, plus:

Driver license detection on this branch is intentionally scoped to U.S. formats
for California, Texas, Florida, and New York only; it accepts either a
driver-license label or a state marker, and it is not a general international
or 50-state detector.

Passport detection on this branch is intentionally limited: it is guaranteed
only for U.S. passport numbers (`9 digits`) and EU-style passport numbers
(`2 uppercase letters + 7 digits`) when paired with either a passport label or
a U.S. / EU region marker. It should not be described as worldwide passport
coverage beyond those documented formats.

Several other detectors are also intentionally narrower than their short config
names may imply:

- `detect_phone` is validated with `rlibphonenumber` and is guaranteed for U.S.
  domestic formats plus international numbers with country code, not all global
  local dialing formats.
- `detect_ip_address` is guaranteed for IPv4 and standard fully expanded or
  compressed IPv6 forms.
- `detect_date_of_birth` is contextual and requires DOB or birth-date style
  labels.
- `detect_bank_account` is guaranteed for contextual numeric account identifiers
  (`8-17 digits`) and checksum-validated IBAN, not arbitrary country-specific
  account schemes.
- `detect_medical_record` is contextual and limited to `MRN` / `Medical Record`
  labeled identifiers.
- `detect_full_name` is contextual and limited to labeled full-name fields.
- `detect_street_address` is contextual and limited to labeled addresses with
  common English street suffixes.

For the current Rust PII detector, the practical contract is:

| Detector | Guaranteed coverage | Explicitly not guaranteed |
| --- | --- | --- |
| `detect_ssn` | U.S. SSN shape with invalid ranges rejected | General 9-digit identifiers outside SSN rules |
| `detect_bsn` | Dutch BSN with explicit BSN context and elfproef validation | Unlabeled 9-digit numbers |
| `detect_credit_card` | Luhn-valid card numbers | Arbitrary 12-19 digit numbers |
| `detect_email` | Standard email address syntax | Deliverability or mailbox ownership |
| `detect_phone` | `rlibphonenumber`-validated U.S. domestic formats and international numbers with country code | Every unlabeled local format worldwide |
| `detect_ip_address` | IPv4 and standard fully expanded or compressed IPv6 | IPv4-mapped IPv6 or every exotic textual variant |
| `detect_date_of_birth` | DOB / birth-date labeled values | Unlabeled dates in free text |
| `detect_passport` | U.S. `9 digits` and EU-style `2 letters + 7 digits` with passport label or `US` / `EU` marker | Other passport schemes or global passport validation |
| `detect_driver_license` | CA, TX, FL, and NY with driver-license label or state marker | Other states, non-U.S. licenses, or global coverage |
| `detect_bank_account` | Contextual `8-17 digit` account numbers and checksum-valid IBAN | Unlabeled U.S. account numbers or arbitrary country-specific schemes |
| `detect_medical_record` | `MRN` / `Medical Record` labeled identifiers | Unlabeled medical identifiers |
| `detect_full_name` | Labeled full-name fields | General NER-style person detection |
| `detect_street_address` | Labeled addresses with common English street suffixes | Unlabeled addresses or global postal parsing |
| `detect_us_aba_routing_number` | 9-digit U.S. ABA routing transit numbers that satisfy prefix and checksum rules | A guarantee that the number is currently assigned or active at a bank |
| `detect_us_zip_code` | Labeled U.S. ZIP / ZIP+4 | Unlabeled 5-digit / 9-digit numbers |
| `detect_us_ein` | Labeled U.S. EIN | Unlabeled 9-digit tax identifiers |
| `detect_us_itin` | Labeled U.S. ITIN in supported ranges | Unlabeled tax identifiers or non-ITIN formats |

- `default_mask_strategy`
- `redaction_text`
- `block_on_detection`
- `log_detections`
- `include_detection_details`
- `custom_patterns`
- `whitelist_patterns`

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
from plugin_rust.plugin_rust import PluginRust

config = {"option1": True, "option2": "value"}
plugin = PluginRust(config)

# Use plugin methods
result = plugin.process(data)
```

## Verification

### Check Installation

```bash
# Verify the compiled detector is importable
python -c "from pii_filter_rust import PIIDetectorRust; print('✓ Rust detector available')"

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

# Without Rust on an auto-detect wrapper
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
make install               # Build and install
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

# Python unit tests for the Python plugin
uv run pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter.py

# Python unit tests for the Rust plugin
uv run pytest tests/unit/mcpgateway/plugins/plugins/pii_filter/test_pii_filter_rust.py

# Or use make
make rust-test-all         # Run all tests
```

### Test Coverage

Rust PII plugin details, supported config keys, and current limitations are
documented in [`plugins_rust/pii_filter/README.md`](https://github.com/IBM/mcp-context-forge/tree/main/plugins_rust/pii_filter).

Avoid treating this page as the plugin-specific source of truth for the Rust PII
plugin. The plugin README and `plugins/config.yaml` are the canonical sources
for the Rust plugin contract.

## Troubleshooting

### Rust Plugin Not Available

**Symptom**: The Rust PII plugin fails to initialize or logs that the detector
cannot be imported

**Solutions**:
```bash
# 1. Check if the Rust package is installed and importable
python -c "from pii_filter_rust import PIIDetectorRust; print('OK')"

# 2. Build from source
cd plugins_rust/pii_filter
maturin develop --release
```

### Import Errors

**Symptom**: `ImportError: No module named 'pii_filter_rust'` or legacy imports
from `plugins_rust` fail

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

Use the current public import path:

```python
from pii_filter_rust import PIIDetectorRust
```

For the plugin wrapper itself, use:

```python
from plugins.pii_filter_rust.pii_filter_rust import RustPIIFilterPlugin
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
from my_plugin_rust.my_plugin_rust import MyPluginRust

class RustMyPlugin:
    def __init__(self, config):
        self._rust = MyPluginRust(config.model_dump())

    def process(self, text: str) -> str:
        return self._rust.process(text)
```

**Note**: The double-nested import (`my_plugin_rust.my_plugin_rust`) is required because:
- First `my_plugin_rust` = package name (from `Cargo.toml` `[lib] name`)
- Second `my_plugin_rust` = module name (from `#[pymodule]` in `lib.rs`)

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
