# ADR-0024: Adopt uvicorn[standard] for Enhanced Server Performance

- *Status:* Accepted
- *Date:* 2025-12-21
- *Deciders:* Core Engineering Team

## Context

MCP Gateway uses Gunicorn with Uvicorn workers (`uvicorn.workers.UvicornWorker`) as its production ASGI server stack. The base `uvicorn` package provides functional async HTTP serving, but lacks optional performance-enhancing components that can provide 15-30% throughput improvements with zero code changes.

The uvicorn package offers a `[standard]` extras bundle that includes:
- **uvloop**: A Cython/libuv-based event loop (2-4x faster than asyncio on Linux/macOS)
- **httptools**: A C extension for HTTP parsing (based on Node.js http-parser)
- **websockets**: WebSocket protocol implementation
- **watchfiles**: Efficient file watching for development `--reload`

Without these extras, Uvicorn falls back to:
- Python's standard `asyncio` event loop
- Python's pure-Python HTTP parser
- Basic file watching mechanisms

## Decision

We will adopt **uvicorn[standard]** as the default uvicorn installation to enable high-performance server components automatically.

**Change:**
```diff
# pyproject.toml
-    "uvicorn>=0.38.0",
+    "uvicorn[standard]>=0.38.0",
```

**Components included:**

| Package | Purpose | Platform Support |
|---------|---------|------------------|
| `uvloop` | Fast event loop (libuv-based) | Linux, macOS only |
| `httptools` | Fast HTTP parsing (C extension) | All platforms |
| `websockets` | WebSocket support | All platforms |
| `watchfiles` | Fast file watching for --reload | All platforms |

**How it works:**
- When Gunicorn spawns `UvicornWorker` processes, Uvicorn automatically detects and uses these high-performance components
- No configuration changes required - detection is automatic
- On Windows, `uvloop` gracefully skips (unavailable), but `httptools` still provides benefits

## Consequences

### Positive

- **15-30% higher throughput** - Faster event loop and HTTP parsing reduce per-request overhead
- **Lower latency** - uvloop provides 20-40% lower event loop latency
- **Zero code changes** - Drop-in enhancement, automatically detected by Uvicorn
- **Consistency** - Matches other projects in the repository (langchain_agent, mcp_eval_server)
- **Better development experience** - watchfiles provides faster, more reliable `--reload`
- **Production-ready** - Used by major deployments (Microsoft, Mozilla, Sentry)

### Negative

- **Platform-specific behavior** - uvloop unavailable on Windows (graceful fallback)
- **Binary dependencies** - Requires compilation or prebuilt wheels (available for all major platforms)
- **Slightly larger install** - Additional packages (~5MB)

### Neutral

- **No configuration needed** - Uvicorn auto-detects available components
- **Transparent to application** - FastAPI/Starlette code unchanged

## Performance Impact

Based on uvloop and httptools benchmarks:

| Metric | Base Uvicorn | With [standard] | Improvement |
|--------|--------------|-----------------|-------------|
| Event loop latency | Baseline | -20-40% | uvloop |
| HTTP parsing overhead | Baseline | -40-60% | httptools |
| Requests/second | Baseline | +15-30% | Combined |
| `--reload` responsiveness | Baseline | Faster | watchfiles |

**Real-world impact:**
- Simple JSON endpoints: 15-25% faster
- WebSocket connections: Better handling via optimized websockets library
- Development cycle: Faster file change detection with watchfiles
- Memory: Similar (slight increase for additional packages)

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **Base uvicorn only** | Leaves 15-30% performance on the table |
| **Manual installation of extras** | Error-prone, inconsistent across environments |
| **Granian (Rust HTTP server)** | Larger migration, under evaluation (see #1695) |
| **Hypercorn** | Less community adoption, similar feature set |

## Relationship to Granian Migration

This change is complementary to the potential Granian migration (#1695):
- **uvicorn[standard]**: Low-effort optimization (this ADR) - implement now
- **Granian**: Larger migration to Rust-based server - evaluate separately

If Granian is adopted in the future, this change would be superseded. Until then, uvicorn[standard] provides immediate benefits with minimal risk.

## Migration Path

1. Update `pyproject.toml`: `uvicorn[standard]>=0.38.0`
2. Reinstall dependencies: `uv sync` or `pip install -e .`
3. Verify extras installed: `pip list | grep -E "uvloop|httptools"`
4. Run test suite: `make test`
5. Benchmark (optional): Compare RPS before/after

## Verification

```bash
# Check installed packages
uv pip list | grep -E "uvicorn|uvloop|httptools|websockets|watchfiles"

# Expected output (Linux/macOS):
# httptools    0.6.x
# uvicorn      0.38.0
# uvloop       0.21.x
# watchfiles   1.x.x
# websockets   15.x.x

# On Windows, uvloop will be absent (expected)
```

## Status

This decision has been implemented. The `pyproject.toml` now specifies `uvicorn[standard]>=0.38.0`.

## References

- GitHub Issue: #1699
- Related Issue: #1695 (Granian evaluation)
- uvicorn deployment docs: https://www.uvicorn.org/deployment/
- uvloop GitHub: https://github.com/MagicStack/uvloop
- httptools GitHub: https://github.com/MagicStack/httptools
- Gunicorn + Uvicorn integration: https://www.uvicorn.org/#running-with-gunicorn
