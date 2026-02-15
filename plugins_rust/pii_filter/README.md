# PII Filter (Rust)

High-performance PII detection and masking library for MCP Gateway.

## Features

- Detects 12+ PII types (SSN, email, credit cards, phone numbers, AWS keys, etc.)
- Multiple masking strategies (partial, hash, tokenize, remove)
- Parallel regex matching with RegexSet (5-10x faster than Python)
- Zero-copy operations for nested JSON/dict traversal
- Whitelist support for false positive filtering

## Build

```bash
cd plugins_rust
maturin develop --release
```

## Usage

The Rust implementation is automatically used by the Python PII filter plugin when available. Set `MCPGATEWAY_FORCE_PYTHON_PLUGINS=true` to force Python fallback.

## Testing

```bash
# Rust unit tests
cargo test

# Python integration tests
pytest tests/unit/mcpgateway/plugins/test_pii_filter_rust.py -v

# Benchmarks
cargo bench
```

## Performance

Expected 5-10x speedup over Python implementation for typical payloads.
