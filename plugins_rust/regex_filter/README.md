# Regex Filter Plugin (Rust)

High-performance Rust implementation of the regex filter plugin for MCP Gateway, providing 12-25x faster text transformations compared to the Python implementation.

## Features

- **Native Rust Performance**: 12-25x faster than Python implementation
- **PyO3 Integration**: Seamless Python interoperability via abi3
- **Regex Support**: Full regex pattern matching and replacement
- **Deep Traversal**: Processes nested dictionaries, lists, and strings
- **Zero-Copy Operations**: Optimized for minimal memory allocations

## Installation

Build and install the plugin:

```bash
make install
```

This compiles the Rust code and installs it as a Python module using maturin.

## Performance

Benchmark results (10,000 iterations, Apple Silicon M-series):

| Scenario | Python | Rust | Speedup |
|----------|--------|------|---------|
| 1KB (no patterns) | 0.058 ms | 0.003 ms | **21.2x** 🚀 |
| 1KB (with patterns) | 0.056 ms | 0.004 ms | **12.8x** 🚀 |
| 5KB (no patterns) | 0.248 ms | 0.010 ms | **25.3x** 🚀 |
| 5KB (with patterns) | 0.271 ms | 0.023 ms | **11.7x** 🚀 |

Run benchmarks yourself:

```bash
make bench-compare
```

## Configuration

The Rust implementation uses the same configuration as the Python version. See [`plugins/regex_filter/README.md`](../../plugins/regex_filter/README.md) for full configuration details.

Example:

```yaml
plugins:
  - name: "SearchReplacePlugin"
    kind: "plugins.regex_filter.search_replace.SearchReplacePlugin"
    config:
      words:
        - search: "crap"
          replace: "crud"
        - search: "\\bAI\\b"
          replace: "artificial intelligence"
```

## Usage

The Rust implementation is automatically used when available. The Python plugin detects the Rust module and delegates processing to it:

```python
from plugins.regex_filter.search_replace import SearchReplacePlugin

# Automatically uses Rust implementation if installed
plugin = SearchReplacePlugin(config)
```

## Development

### Build Commands

```bash
make build          # Build release binary
make install        # Build and install as Python module
make test           # Run Rust tests
make bench          # Run Rust benchmarks
make compare        # Compare Python vs Rust performance
```

### Testing

```bash
# Run all tests
make test-all

# Run just Rust tests
make test

# Run Python integration tests
make test-python
```

## License

Apache-2.0
