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
make install
```

## Usage

The Rust implementation is automatically used by the Python PII filter plugin when available.

## Testing

```bash
# Rust unit tests
make test

# Python tests
make test-python

# Benchmarks
make bench
```

## Performance

Expected 5-10x speedup over Python implementation for typical payloads.
