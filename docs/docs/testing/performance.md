# Performance Testing

Use this guide to benchmark **MCP Gateway** under load, validate performance improvements, and identify bottlenecks before production deployment. For an overview of the high-performance architecture and Rust-powered components that drive MCP Gateway's performance, see the [Performance Architecture Diagram](../architecture/performance-architecture.md).

---

## ⚙️ Tooling: `hey`

[`hey`](https://github.com/rakyll/hey) is a CLI-based HTTP load generator. Install it with:

```bash
brew install hey            # macOS
sudo apt install hey        # Debian/Ubuntu
go install github.com/rakyll/hey@latest  # From source
```

---

## 🎯 Establishing a Baseline

Before benchmarking the full MCP Gateway stack, run tests against the **MCP server directly** (if applicable) to establish baseline latency and throughput. This helps isolate issues related to gateway overhead, authentication, or network I/O.

If your backend service exposes a direct HTTP interface or gRPC gateway, target it with `hey` using the same payload and concurrency settings.

```bash
hey -n 5000 -c 100 \
  -m POST \
  -T application/json \
  -D tests/hey/payload.json \
  http://localhost:5000/your-backend-endpoint
```

Compare the 95/99th percentile latencies and error rates with and without the gateway in front. Any significant increase can guide you toward:

* Bottlenecks in auth middleware
* Overhead from JSON-RPC wrapping/unwrapping
* Improper worker/thread config in Gunicorn

## 🚀 Scripted Load Tests: `tests/hey/hey.sh`

A wrapper script exists at:

```bash
tests/hey/hey.sh
```

This script provides:

* Strict error handling (`set -euo pipefail`)
* Helpful CLI interface (`-n`, `-c`, `-d`, etc.)
* Required dependency checks
* Optional dry-run mode
* Timestamped logging

Example usage:

```bash
./hey.sh -n 10000 -c 200 \
  -X POST \
  -T application/json \
  -H "Authorization: Bearer $JWT" \
  -d payload.json \
  -u http://localhost:4444/rpc
```

> The `payload.json` file is expected to be a valid JSON-RPC request payload.

Sample payload (`tests/hey/payload.json`):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "convert_time",
  "params": {
    "source_timezone": "Europe/Berlin",
    "target_timezone": "Europe/Dublin",
    "time": "09:00"
  }
}
```

Logs are saved automatically (e.g. `hey-20250610_120000.log`).

---

## 📊 Interpreting Results

When the test completes, look at:

| Metric             | Interpretation                                          |
| ------------------ | ------------------------------------------------------- |
| Requests/sec (RPS) | Raw throughput capability                               |
| 95/99th percentile | Tail latency - tune `timeout`, workers, or DB pooling   |
| Non-2xx responses  | Failures under load - common with CPU/memory starvation |

---

## 🧪 Tips & Best Practices

* Always test against a **realistic endpoint** (e.g. `POST /rpc` with auth and payload).
* Use the same JWT and payload structure your clients would.
* Run from a dedicated machine to avoid local CPU skewing results.
* Use `make run` or `make serve` to launch the app for local testing.

For runtime tuning details, see [Gateway Tuning Guide](../manage/tuning.md).

---

## 🚀 JSON Serialization Performance: orjson

MCP Gateway uses **orjson** for high-performance JSON serialization, providing **5-6x faster serialization** and **1.5-2x faster deserialization** compared to Python's standard library `json` module.

### Why orjson?

orjson is a fast, correct JSON library for Python implemented in Rust. It provides:

- **5-6x faster serialization** than stdlib json
- **1.5-2x faster deserialization** than stdlib json
- **7% smaller output** (more compact JSON)
- **Native type support**: datetime, UUID, numpy arrays, Pydantic models
- **RFC 8259 compliance**: strict JSON specification adherence
- **Zero configuration**: drop-in replacement, works automatically

### Performance Benchmarks

Run the benchmark script to measure JSON serialization performance on your system:

```bash
python scripts/benchmark_json_serialization.py
```

**Sample Results:**

| Payload Size | stdlib json | orjson     | Speedup  |
|--------------|-------------|------------|----------|
| 10 items     | 10.32 μs    | 1.43 μs    | 623%     |
| 100 items    | 91.00 μs    | 13.82 μs   | 558%     |
| 1,000 items  | 893.53 μs   | 135.00 μs  | 562%     |
| 5,000 items  | 4.44 ms     | 682.14 μs  | 551%     |

**Key Findings:**

✅ **Serialization**: 5-6x faster (550-623% speedup)
✅ **Deserialization**: 1.5-2x faster (55-115% speedup)
✅ **Output Size**: 7% smaller (more compact JSON)
✅ **Performance scales**: Advantage increases with payload size

### Where Performance Matters Most

orjson provides the biggest impact for:

- **Large list endpoints**: `GET /tools`, `GET /servers`, `GET /gateways` (100+ items)
- **Bulk export operations**: Exporting 1000+ entities to JSON
- **High-throughput APIs**: Services handling >1000 req/s
- **Real-time streaming**: SSE and WebSocket with frequent JSON events
- **Federation sync**: Tool catalog exchange between gateways
- **Admin UI data loading**: Large tables with many records

### Implementation Details

MCP Gateway configures orjson as the default JSON response class for all FastAPI endpoints:

```python
from mcpgateway.utils.orjson_response import ORJSONResponse

app = FastAPI(
    default_response_class=ORJSONResponse,  # Use orjson for all responses
    # ... other config
)
```

**Options enabled:**
- `OPT_NON_STR_KEYS`: Allow non-string dict keys (integers, UUIDs)
- `OPT_SERIALIZE_NUMPY`: Support numpy arrays if numpy is installed

**Datetime serialization:**
- Uses RFC 3339 format (ISO 8601 with timezone)
- Naive datetimes treated as UTC
- Example: `2025-01-19T12:00:00+00:00`

### Testing orjson Integration

All JSON serialization is automatically handled by orjson. No client changes required.

**Verify orjson is active:**

```bash
# Start the development server
make dev

# Check that responses are using orjson (compact, fast)
curl -s http://localhost:8000/health | jq .

# Measure response time for large endpoint
time curl -s http://localhost:8000/tools > /dev/null
```

**Unit tests:**

```bash
# Run orjson-specific tests
pytest tests/unit/mcpgateway/utils/test_orjson_response.py -v

# Verify 100% code coverage
pytest tests/unit/mcpgateway/utils/test_orjson_response.py --cov=mcpgateway.utils.orjson_response --cov-report=term-missing
```

### Performance Impact

Based on benchmark results, orjson provides:

| Metric                  | Improvement           |
|-------------------------|-----------------------|
| Serialization speed     | 5-6x faster           |
| Deserialization speed   | 1.5-2x faster         |
| Output size             | 7% smaller            |
| API throughput          | 15-30% higher RPS     |
| CPU usage               | 10-20% lower          |
| Response latency (p95)  | 20-40% faster         |

**Production benefits:**
- Higher requests/second capacity
- Lower CPU utilization per request
- Faster page loads for Admin UI
- Reduced bandwidth usage (smaller JSON)
- Better tail latency (p95, p99)

---

## 🔬 Combining Performance Optimizations

For maximum performance, combine multiple optimizations:

1. **orjson serialization** (5-6x faster JSON) ← Automatic
2. **Response compression** (30-70% bandwidth reduction) ← See compression docs
3. **Redis caching** (avoid repeated serialization) ← Optional
4. **Connection pooling** (reuse DB connections) ← Automatic
5. **Async I/O** (non-blocking operations) ← Automatic with FastAPI

These optimizations are complementary and provide cumulative benefits.

---
