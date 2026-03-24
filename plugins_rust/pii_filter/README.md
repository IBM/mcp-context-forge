# PII Filter (Rust)

High-performance PII detection and masking library for ContextForge.

## Features

- Detects 12+ PII types (SSN, email, credit cards, phone numbers, AWS keys, etc.)
- Multiple masking strategies (partial, hash, tokenize, remove)
- Parallel regex matching with RegexSet (5-10x faster than Python)
- Zero-copy operations for nested JSON/dict traversal
- Whitelist support for false positive filtering
- Deterministic overlap resolution: earliest match wins, then the longest match wins
- Structural validation for SSNs and common card issuer ranges to reduce false positives
- Explicit guardrails for oversized inputs and pathological custom patterns

## Build

```bash
make install
```

## Usage

The Rust implementation is automatically used by the Python PII filter plugin when available.

## Security Notes

- Whitelist patterns are compiled case-insensitively.
- Custom patterns must stay within basic length and complexity limits.
- Very large strings and oversized nested collections are rejected instead of being scanned indefinitely.

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
