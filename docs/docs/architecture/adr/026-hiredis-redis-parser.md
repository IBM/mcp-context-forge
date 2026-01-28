# ADR-0026: Add Hiredis as Default Redis Parser

- *Status:* Accepted
- *Date:* 2025-12-21
- *Deciders:* Core Engineering Team

## Context

MCP Gateway uses redis-py for Redis connections (caching, federation, leader election, metrics). The default pure-Python protocol parser in redis-py has significant overhead, especially for large responses. This impacts performance for:

- Tool registry queries returning many tools
- Bulk operations and federation
- Cached response retrieval
- Metrics aggregation

Hiredis is a minimalistic C client library for Redis that provides significantly faster protocol parsing. The `hiredis` Python package provides Python bindings that redis-py can use as a drop-in replacement for its pure-Python parser.

## Decision

We will use **hiredis** as the **default Redis parser** while providing a pure-Python fallback option.

**Key points:**
- `redis[hiredis]` is the default dependency (includes hiredis)
- `redis-pure` optional dependency available for environments where hiredis wheels aren't available
- Users can switch parsers via the `REDIS_PARSER` environment variable
- Auto-detection (default) uses hiredis if available, falls back to pure-Python

**Usage:**
```bash
# Default: auto-detect (uses hiredis if available)
REDIS_PARSER=auto

# Force pure-Python parser (debugging, restricted environments)
REDIS_PARSER=python

# Require hiredis (fails if not installed)
REDIS_PARSER=hiredis
```

## Performance Benchmarks

Based on hiredis-py benchmarks:

| Operation | Pure Python | With Hiredis | Improvement |
|-----------|-------------|--------------|-------------|
| Simple SET/GET | Baseline | +10% | 1.1x |
| LRANGE (10 items) | Baseline | +170% | 2.7x |
| LRANGE (100 items) | Baseline | +900% | ~10x |
| LRANGE (999 items) | Baseline | +8220% | **83.2x** |

**Key insight:** The larger the response, the greater the improvement. This is critical for MCP Gateway operations that retrieve large datasets from Redis.

### Impact on MCP Gateway

| Use Case | Typical Response Size | Expected Improvement |
|----------|----------------------|---------------------|
| Single tool lookup | Small | 1.1x |
| Tool list (50 tools) | Medium | 5-10x |
| Federation sync | Large | 20-50x |
| Bulk operations | Very large | 50-80x |

## Consequences

### Positive

- **Significantly faster Redis operations** - Up to 83x for large responses
- **Lower latency** - Faster parsing reduces overall request latency
- **Reduced CPU usage** - C extension is more efficient than Python parsing
- **Transparent upgrade** - Existing code works without changes
- **Fallback available** - Pure-Python parser remains an option

### Negative

- **Binary dependency** - Requires compiled C extension
- **Platform coverage** - Wheels may not be available for all platforms (though coverage is excellent)
- **Debugging complexity** - C extension errors harder to debug than pure Python
- **Build requirements** - Building from source requires C compiler

### Neutral

- **Same API** - redis-py API unchanged
- **Same configuration** - Most Redis settings work identically
- **Coexistence** - Both parsers can be installed simultaneously

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_PARSER` | `auto` | Parser selection: `auto`, `hiredis`, `python` |

### Parser Selection Logic

```
REDIS_PARSER=auto (default)
├── hiredis installed? → Use HiredisParser
└── hiredis not installed? → Use PythonParser

REDIS_PARSER=hiredis
├── hiredis installed? → Use HiredisParser
└── hiredis not installed? → ERROR (fail startup)

REDIS_PARSER=python
└── Always use PythonParser
```

### Installation Options

```bash
# Default: includes hiredis for performance
pip install "mcp-contextforge-gateway[redis]"

# Pure-Python only (no C dependencies)
pip install "mcp-contextforge-gateway[redis-pure]"
```

## When to Use Each Parser

### Use Hiredis (default) when:
- Running in production environments
- Handling large response payloads
- Maximum throughput is required
- Pre-built wheels are available for your platform

### Use Pure-Python parser when:
- Debugging Redis protocol issues
- Platform lacks hiredis wheel support
- Minimizing binary dependencies
- Running in restricted environments (some containerized/sandboxed setups)

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Added `redis[hiredis]` as default, `redis-pure` fallback |
| `mcpgateway/config.py` | Added `redis_parser` setting |
| `mcpgateway/utils/redis_client.py` | Parser selection logic |
| `.env.example` | Added `REDIS_PARSER` documentation |
| `docker-compose.yml` | Added `REDIS_PARSER` environment variable |

## Verification

To verify which parser is being used:

```python
from mcpgateway.utils.redis_client import get_redis_parser_info

# Returns: "HiredisParser (C extension)" or "PythonParser (pure-Python)"
print(get_redis_parser_info())
```

Or check the startup logs:

```
Redis client initialized: parser=HiredisParser (C extension, auto-detected), pool_size=50, timeout=2.0s
```

## Recommendation

**For most users: Use the default (auto)**

The default `REDIS_PARSER=auto` setting provides the best experience:
- Uses hiredis when available for maximum performance
- Falls back gracefully to pure-Python if needed
- No configuration required

**Consider `REDIS_PARSER=python` when:**
- Debugging Redis protocol issues
- Troubleshooting connection problems
- Running on platforms without hiredis wheels

## Status

This decision has been implemented. Both parsers are available:
- Hiredis: **Default** (via `redis[hiredis]`)
- Pure-Python: **Fallback** (via `redis-pure` or `REDIS_PARSER=python`)

## References

- GitHub Issue: #1702
- Related ADR: ADR-0025 (Granian HTTP Server - similar pattern)
- Hiredis GitHub: https://github.com/redis/hiredis
- Hiredis-py PyPI: https://pypi.org/project/hiredis/
- Redis-py Documentation: https://redis-py.readthedocs.io/
