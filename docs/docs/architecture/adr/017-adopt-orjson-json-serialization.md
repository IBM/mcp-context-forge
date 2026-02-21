# ADR-0017: Adopt orjson for High-Performance JSON Serialization

- *Status:* Accepted
- *Date:* 2025-10-27
- *Deciders:* Core Engineering Team

## Context

The ContextForge handles large volumes of JSON-RPC requests and responses, tool invocations, resource payloads, and API endpoints. JSON serialization and deserialization is a critical performance bottleneck in high-throughput scenarios.

Python's standard library `json` module is implemented in pure Python with some C optimizations, but still represents a significant CPU overhead for:

- Large endpoint responses (GET /tools, GET /servers)
- JSON-RPC message processing
- Bulk export operations
- API response serialization

We needed a drop-in replacement that provides substantial performance improvements without breaking RFC 8259 compliance or requiring changes to existing code.

## Decision

We will adopt **orjson** as the default JSON serialization library for all FastAPI responses and internal JSON operations.

**orjson** is a Rust-based JSON library that provides:

- **5-6x faster serialization** compared to Python's standard library
- **1.5-2x faster deserialization**
- **7% smaller output size** (more compact JSON)
- RFC 8259 compliant (strict JSON specification)
- Native support for datetime, UUID, numpy arrays
- Zero configuration (drop-in replacement)

Implementation:

- FastAPI default_response_class: `ORJSONResponse` (mcpgateway/main.py:408)
- Response class: `mcpgateway/utils/orjson_response.py`
- Options: `OPT_NON_STR_KEYS` (allows int keys), `OPT_SERIALIZE_NUMPY` (numpy support)
- Datetime format: RFC 3339 (ISO 8601 with timezone)

## Consequences

### Positive

- ⚡ **5-6x faster serialization** - Large endpoint responses (GET /tools) complete 20-40% faster
- 🚀 **1.5-2x faster deserialization** - JSON-RPC request parsing is significantly faster
- 📦 **7% smaller output** - Reduced bandwidth usage, faster network transfer
- 🦀 **Rust implementation** - Memory-safe, no GIL contention during serialization
- 🔌 **Drop-in replacement** - No API changes required, fully compatible
- 📈 **Higher throughput** - 15-30% more requests/second at scale
- 💰 **Lower CPU usage** - 10-20% reduction in CPU per request

### Negative

- 🔒 **Rust dependency** - Requires Rust toolchain for building from source (prebuilt wheels available)
- 📚 **Less flexible** - Stricter RFC 8259 compliance (e.g., no NaN/Infinity)
- 🔄 **Binary dependency** - Not pure Python (but provides cross-platform wheels)

### Neutral

- 🧪 **Testing required** - Ensure datetime serialization matches expected format
- 📝 **Documentation** - Note orjson-specific behavior for custom JSON types

## Performance Impact

Based on benchmarks (scripts/benchmark_json_serialization.py):

| Operation | Standard json | orjson | Improvement |
|-----------|--------------|--------|-------------|
| Serialization (large payload) | 100ms | 16-18ms | 5-6x faster |
| Deserialization (large payload) | 50ms | 23-33ms | 1.5-2x faster |
| Output size | 100KB | 93KB | 7% smaller |

**Real-world impact:**

- Large endpoints (GET /tools, GET /servers): 20-40% faster response time
- Bulk exports: 50-60% faster serialization
- API throughput: 15-30% higher requests/second
- CPU usage: 10-20% lower per request

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| **ujson (UltraJSON)** | Faster than standard json but 2-3x slower than orjson; less maintained |
| **simplejson** | Pure Python, no performance benefit over standard library |
| **rapidjson** | C++ based, good performance but slower than orjson and less maintained |
| **Standard library json** | 5-6x slower serialization, significant bottleneck at scale |
| **msgpack** | Binary format, not JSON; breaks compatibility with JSON-RPC and REST APIs |

## Migration Path

1. Install orjson: `pip install orjson`
2. Replace FastAPI default_response_class with ORJSONResponse
3. Update custom response handling to use orjson
4. Run comprehensive test suite to verify compatibility
5. Benchmark endpoints to measure performance improvement

## Status

This decision has been implemented. All FastAPI endpoints use orjson for JSON serialization via the ORJSONResponse class.

## References

- orjson GitHub: https://github.com/ijl/orjson
- Benchmark script: `scripts/benchmark_json_serialization.py`
- Response class: `mcpgateway/utils/orjson_response.py`
- FastAPI configuration: `mcpgateway/main.py:408`
- Performance docs: `docs/docs/testing/performance.md`
