# Rust Plugins Quick Start Guide

Get started with Rust-accelerated plugins for ContextForge in under 5 minutes.

## Prerequisites

- Python 3.11+
- Rust 1.70+ (optional for building from source)
- Virtual environment activated

## Quick Install (Pre-built Wheels)

The fastest way to get started is using pre-built wheels (when available):

```bash
# Install ContextForge with Rust plugins
pip install mcpgateway[rust]
```

## Build from Source

If pre-built wheels aren't available for your platform, or you want to customize the build:

### 1. Install Rust Toolchain

```bash
# Install rustup (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Verify installation
rustc --version
cargo --version
```

### 2. Install Build Tools

```bash
# Install maturin (PyO3 build tool)
pip install maturin

# Optional: Install development tools
pip install cargo-watch cargo-tarpaulin
```

### 3. Build Rust Plugins

```bash
# Navigate to rust plugins directory
cd plugins_rust

# Development build (fast compilation, slower runtime)
make dev

# OR Production build (optimized for performance)
make build

# Verify installation
python -c "from plugins_rust import PIIDetectorRust; print('✓ Rust plugins installed')"
```

**Build Times:**
- Development build: ~3-5 seconds
- Release build: ~7-10 seconds

## Starting the Gateway with Rust Plugins

### Method 1: Auto-Detection (Recommended)

The gateway automatically detects and uses Rust plugins when available:

```bash
# Activate virtual environment
source ~/.venv/mcpgateway/bin/activate  # or your venv path

# Start development server
make dev

# OR start production server
make serve
```

The PII Filter plugin will automatically use the Rust implementation if installed.

### Method 2: Explicit Configuration

Force Rust plugin usage via environment variables:

```bash
# Enable plugins
export PLUGINS_ENABLED=true
export PLUGIN_CONFIG_FILE=plugins/config.yaml

# Start gateway
python -m mcpgateway.main
```

### Method 3: Direct Run

```bash
# From project root
cd /home/cmihai/github/mcp-context-forge

# Activate environment
source ~/.venv/mcpgateway/bin/activate

# Run with auto-reload (development)
uvicorn mcpgateway.main:app --reload --host 0.0.0.0 --port 8000

# OR run production server
gunicorn mcpgateway.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:4444
```

## Verify Rust Plugin is Active

### Check via Python

```python
from plugins.pii_filter.pii_filter import PIIFilterPlugin
from plugins.framework import PluginConfig

config = PluginConfig(name='pii_filter', kind='pii_filter', config={})
plugin = PIIFilterPlugin(config)

print(f"Implementation: {plugin.implementation}")
# Expected output: "Implementation: rust"
```

### Check via API

```bash
# Start the gateway
make dev

# In another terminal, make a request
curl -X POST http://localhost:8000/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "detect_pii",
    "arguments": {"text": "My SSN is 123-45-6789"}
  }'
```

Check the server logs for:
```
INFO - Using Rust-accelerated PII filter (35x faster)
```

## Performance Verification

Run benchmarks to verify Rust acceleration:

```bash
# From plugins_rust directory
python benchmarks/compare_pii_filter.py

# OR with custom sizes
python benchmarks/compare_pii_filter.py --sizes 100 500 1000

# Save results to file
python benchmarks/compare_pii_filter.py --output benchmarks/results/latest.json
```

Expected output:
```
Average Speedup: 35.9x
🚀 EXCELLENT: >10x speedup - Highly recommended
```

## Common Issues & Solutions

### Issue: "Rust implementation not available"

**Solution 1 - Install from source:**
```bash
cd plugins_rust
make dev
```

**Solution 2 - Check installation:**
```bash
python -c "from plugins_rust import PIIDetectorRust; print('OK')"
```

**Solution 3 - Rebuild:**
```bash
cd plugins_rust
make clean
make build
```

### Issue: Build fails with "maturin not found"

**Solution:**
```bash
pip install maturin
```

### Issue: Build fails with "cargo not found"

**Solution:**
```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

### Issue: Gateway doesn't use Rust plugins

**Check 1 - Verify installation:**
```bash
python -c "import plugins_rust; print(plugins_rust.__file__)"
```

**Check 2 - Check logs:**
```bash
# Look for this line in gateway logs:
# "Using Rust-accelerated PII filter"
```

**Check 3 - Force Rust usage:**
```python
from plugins.pii_filter.pii_filter_rust import RustPIIDetector, RUST_AVAILABLE
print(f"Rust available: {RUST_AVAILABLE}")
```

### Issue: Import errors after building

**Solution - Add to Python path:**
```bash
export PYTHONPATH=/home/cmihai/github/mcp-context-forge:$PYTHONPATH
```

Or in Python:
```python
import sys
sys.path.insert(0, '/home/cmihai/github/mcp-context-forge')
```

## Development Workflow

### 1. Make Changes to Rust Code

```bash
cd plugins_rust
# Edit files in src/pii_filter/*.rs
```

### 2. Rebuild

```bash
# Fast rebuild with development mode
make dev

# OR full release build
make build
```

### 3. Test Changes

```bash
# Run Rust unit tests
make test

# Run Python integration tests
make test-python

# Run all tests
make test-all
```

### 4. Restart Gateway

```bash
# If using auto-reload (development)
# Changes are picked up automatically after rebuild

# If not using auto-reload
# Restart the gateway process
```

## Production Deployment

### 1. Build Optimized Release

```bash
cd plugins_rust
make build
```

### 2. Run Tests

```bash
make test-all
make verify
```

### 3. Deploy

```bash
# Copy wheel to production server
scp target/wheels/*.whl production-server:/tmp/

# On production server
pip install /tmp/mcpgateway_rust-*.whl

# Start gateway
gunicorn mcpgateway.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:4444
```

## Configuration

### Environment Variables

```bash
# Enable plugins
export PLUGINS_ENABLED=true

# Plugin configuration file
export PLUGIN_CONFIG_FILE=plugins/config.yaml

# Log level
export LOG_LEVEL=INFO
```

### Plugin Configuration (plugins/config.yaml)

```yaml
plugins:
  - name: pii_filter
    enabled: true
    module: plugins.pii_filter.pii_filter
    class: PIIFilterPlugin
    priority: 100
    config:
      mask_strategy: partial
      detect_ssn: true
      detect_credit_card: true
      detect_email: true
      detect_phone: true
      detect_ip: true
```

## Next Steps

1. **Read Full Documentation**: `docs/docs/using/plugins/rust-plugins.md`
2. **Run Benchmarks**: `python benchmarks/compare_pii_filter.py`
3. **Review Test Results**: `plugins_rust/BUILD_AND_TEST_RESULTS.md`
4. **Explore Examples**: Check `tests/unit/mcpgateway/plugins/test_pii_filter_rust.py`
5. **Join Development**: See `plugins_rust/README.md` for contribution guidelines

## Performance Summary

With Rust plugins enabled, you get:

- **7-18x faster** for typical PII detection
- **27-77x faster** for large datasets (100-1000 instances)
- **100x faster** for clean text (no PII)
- **35.9x average speedup** across all workloads

## Support

- **Issues**: https://github.com/anthropics/mcp-context-forge/issues
- **Documentation**: `docs/docs/using/plugins/rust-plugins.md`
- **Build Results**: `plugins_rust/BUILD_AND_TEST_RESULTS.md`
- **Makefile Help**: `cd plugins_rust && make help`

---

**Quick Command Reference:**

```bash
# Install
pip install mcpgateway[rust]

# Build from source
cd plugins_rust && make build

# Start gateway
make dev

# Run benchmarks
python benchmarks/compare_pii_filter.py

# Run tests
cd plugins_rust && make test-all

# Get help
cd plugins_rust && make help
```
