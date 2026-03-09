# Performance Testing

Use this guide to benchmark **ContextForge** under load, validate performance improvements, and identify bottlenecks before production deployment. For an overview of the high-performance architecture and Rust-powered components that drive ContextForge's performance, see the [Performance Architecture Diagram](../architecture/performance-architecture.md).

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

Before benchmarking the full ContextForge stack, run tests against the **MCP server directly** (if applicable) to establish baseline latency and throughput. This helps isolate issues related to gateway overhead, authentication, or network I/O.

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

## 🔧 Host TCP Tuning for Load Testing

When running high-concurrency load tests (500+ concurrent users), the default Linux TCP settings may cause connection failures. Each MCP tool invocation creates a new TCP connection, which enters TIME_WAIT state after closing. This can exhaust ephemeral ports.

### Check Current Settings

```bash
# View current TCP settings
sysctl net.core.somaxconn \
       net.core.netdev_max_backlog \
       net.ipv4.tcp_max_syn_backlog \
       net.ipv4.tcp_tw_reuse \
       net.ipv4.tcp_fin_timeout \
       net.ipv4.ip_local_port_range
```

### Recommended Settings

#### TCP/Network Settings

| Setting | Default | Recommended | Purpose |
|---------|---------|-------------|---------|
| `net.core.somaxconn` | 4096 | 65535 | Max listen queue depth |
| `net.core.netdev_max_backlog` | 1000 | 65535 | Max packets queued for processing |
| `net.ipv4.tcp_max_syn_backlog` | 1024 | 65535 | Max SYN requests queued |
| `net.ipv4.tcp_tw_reuse` | 0 | 1 | Reuse TIME_WAIT sockets (outbound only) |
| `net.ipv4.tcp_fin_timeout` | 60 | 15 | Faster TIME_WAIT cleanup |
| `net.ipv4.ip_local_port_range` | 32768-60999 | 1024-65535 | More ephemeral ports |

#### Memory/VM Settings

| Setting | Default | Recommended | Purpose |
|---------|---------|-------------|---------|
| `vm.swappiness` | 60 | 10 | Keep more data in RAM (better for databases) |
| `fs.aio-max-nr` | 65536 | 1048576 | Async I/O requests (high disk throughput) |
| `fs.file-max` | varies | 1000000+ | System-wide file descriptor limit |

#### File Descriptor Limits

Check your current limits with `ulimit -n`. For load testing, ensure:

- Soft limit: 65535+
- Hard limit: 65535+

Edit `/etc/security/limits.conf` if needed:
```
*    soft    nofile    65535
*    hard    nofile    65535
```

### Apply Settings (One-liner)

```bash
# Apply all tuning for load testing (requires root)
sudo sysctl -w net.core.somaxconn=65535 \
               net.core.netdev_max_backlog=65535 \
               net.ipv4.tcp_max_syn_backlog=65535 \
               net.ipv4.tcp_tw_reuse=1 \
               net.ipv4.tcp_fin_timeout=15 \
               net.ipv4.ip_local_port_range="1024 65535" \
               vm.swappiness=10 \
               fs.aio-max-nr=1048576
```

Or use the provided tuning script:

```bash
sudo scripts/tune-loadtest.sh
```

### Make Persistent

To persist across reboots, create `/etc/sysctl.d/99-mcp-loadtest.conf`:

```bash
cat << 'EOF' | sudo tee /etc/sysctl.d/99-mcp-loadtest.conf
# ContextForge Load Testing TCP/System Tuning
# See: docs/docs/testing/performance.md

# TCP connection handling
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.ip_local_port_range = 1024 65535

# TCP keepalive (faster dead connection detection)
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 6

# TCP buffer sizes (16MB max)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Memory/VM tuning for database workloads
vm.swappiness = 10

# File handle limits
fs.file-max = 2097152
fs.aio-max-nr = 1048576
EOF

sudo sysctl --system
```

### Why This Matters

Without tuning, you may see errors like:

- `All connection attempts failed` - ephemeral port exhaustion
- `Connection refused` - listen backlog overflow
- High failure rates at 500+ concurrent users

The docker-compose.yml includes per-container TCP tuning via `sysctls`, but host-level settings provide the foundation.

### User Limits (/etc/security/limits.conf)

For persistent file descriptor and process limits, add to `/etc/security/limits.conf`:

```bash
sudo tee -a /etc/security/limits.conf << 'EOF'

# =============================================================================
# Load Testing Limits (Locust 4000+ users)
# =============================================================================

# Open files - each connection needs a file descriptor
*               soft    nofile          65536
*               hard    nofile          65536

# Max user processes - for worker processes and threads
*               soft    nproc           65536
*               hard    nproc           65536

# Max pending signals
*               soft    sigpending      65536
*               hard    sigpending      65536

# Max locked memory (KB) - helps prevent swapping for critical data
*               soft    memlock         unlimited
*               hard    memlock         unlimited

# Max message queue size (bytes)
*               soft    msgqueue        819200
*               hard    msgqueue        819200

# Root user also needs these (limits.conf * doesn't apply to root)
root            soft    nofile          65536
root            hard    nofile          65536
root            soft    nproc           65536
root            hard    nproc           65536
EOF
```

After editing, log out and back in (or for WSL2: `wsl --shutdown` from Windows).

Verify with:
```bash
ulimit -n   # Should show 65536
ulimit -u   # Should show 65536
```

---

## 🦗 Locust Load Testing

ContextForge includes [Locust](https://locust.io/) for comprehensive load testing with realistic user behavior simulation.

### Quick Start

```bash
# Interactive Web UI — configure users, spawn rate, duration in browser
make load-test-ui
# Open http://localhost:8089, pick user classes, click Start

# Headless CLI — runs to completion, prints live stats, generates reports
make load-test-cli
# Reports saved to reports/loadtest.html and reports/loadtest_*.csv
```

Both targets use the same locustfile (`tests/loadtest/locustfile.py`) with all user classes. The Web UI (`load-test-ui`) lets you pick which user types to run interactively; the CLI (`load-test-cli`) runs all types at their configured weights.

### Available Targets

**General load tests** (all endpoints — REST, admin, MCP JSON-RPC, tools):

| Target | Users | Duration | Mode | Description |
|--------|-------|----------|------|-------------|
| `make load-test-ui` | 4000 | 5 min | Web UI | Interactive with class picker at `http://localhost:8089` |
| `make load-test-cli` | 4000 | 5 min | Headless | Live CLI stats + HTML/CSV reports |
| `make load-test-light` | 10 | 30s | Headless | Quick smoke test |
| `make load-test-heavy` | 200 | 120s | Headless | Sustained moderate load |
| `make load-test-sustained` | 25 | 300s | Headless | 5-minute endurance test |
| `make load-test-stress` | 500 | 60s | Headless | Stress test (confirmation prompt) |
| `make load-test-1000` | 1000 | 120s | Headless | High-load ~1000 RPS |

**MCP protocol only** (Streamable HTTP `/servers/{id}/mcp` endpoint):

| Target | Users | Duration | Mode | Description |
|--------|-------|----------|------|-------------|
| `make load-test-mcp-protocol` | 150 | 2 min | Headless | MCP-only with reports |
| `make load-test-mcp-protocol-ui` | 150 | 2 min | Web UI | MCP-only with class picker |
| `make load-test-mcp-protocol-heavy` | 500 | 5 min | Headless | Heavy MCP sustained load |

**Component baselines** (individual servers, database, cache):

| Target | Description |
|--------|-------------|
| `make load-test-baseline` | Fast Time Server REST API (1000 users, 3 min) |
| `make load-test-baseline-ui` | Baseline with class picker |
| `make load-test-fasttime` | Fast Time MCP tools (50 users, 60s) |

### Configuration

Override defaults via environment variables:

```bash
# Custom user count and spawn rate
LOADTEST_USERS=2000 LOADTEST_SPAWN_RATE=100 make load-test-ui

# Custom host (default: http://localhost:8080 via nginx)
LOADTEST_HOST=http://localhost:4444 make load-test-cli

# Limit worker processes (default: auto-detect CPUs)
LOADTEST_PROCESSES=4 make load-test-ui

# Custom run time
LOADTEST_RUN_TIME=10m make load-test-cli
```

### User Classes

The Locust UI provides a class picker to select different user behavior profiles:

| User Class | Weight | Description |
|------------|--------|-------------|
| `HealthCheckUser` | 5 | Health endpoint only |
| `ReadOnlyAPIUser` | 30 | GET endpoints (tools, servers, etc.) |
| `AdminUIUser` | 10 | Admin dashboard pages |
| `MCPJsonRpcUser` | 15 | MCP JSON-RPC protocol |
| `WriteAPIUser` | 5 | POST/PUT/DELETE operations |
| `StressTestUser` | 1 | High-frequency requests |
| `FastTimeUser` | 20 | Fast Time MCP server |
| `RealisticUser` | 10 | Mixed realistic workload |
| `HighThroughputUser` | - | Maximum RPS (separate file) |

### High-Concurrency Testing (4000+ Users)

For testing with 4000+ concurrent users:

1. **Tune the OS first:**
   ```bash
   sudo scripts/tune-loadtest.sh
   ```

2. **Ensure limits are set:**
   ```bash
   ulimit -n   # Should be 65536
   ulimit -u   # Should be 65536
   ```

3. **Run the load test:**
   ```bash
   make load-test-ui
   ```

4. **Monitor during test:**
   ```bash
   # In separate terminals:
   watch -n1 'ss -s'           # Socket statistics
   docker stats                # Container resources
   ```

### Locust Files

| File | Purpose |
|------|---------|
| `tests/loadtest/locustfile.py` | Main locustfile — all endpoints, 20+ user classes |
| `tests/loadtest/locustfile_mcp_protocol.py` | MCP Streamable HTTP protocol only — 6 user classes |
| `tests/loadtest/locustfile_highthroughput.py` | Fast endpoints only — optimized for maximum RPS |
| `tests/loadtest/locustfile_baseline.py` | Component baselines — REST, MCP direct, PostgreSQL, Redis |
| `tests/loadtest/locustfile_spin_detector.py` | CPU spin loop detection (escalating waves) |
| `tests/loadtest/locustfile_slow_time_server.py` | Timeout / circuit breaker testing |

### Performance Tips

- **Start small**: Test with 100-500 users first to identify bottlenecks
- **Scale gradually**: Increase users in steps (500 → 1000 → 2000 → 4000)
- **Monitor errors**: High error rates indicate server saturation
- **Check p95/p99**: Tail latency matters more than average
- **Use `constant_throughput`**: For predictable RPS instead of random waits
- **Nginx caching**: Admin pages use 5s TTL caching by default (see [Nginx Tuning](../manage/tuning.md#7-nginx-reverse-proxy-tuning))

---

## 📦 Test Data Generation

Before running load tests against a realistic dataset, populate the database with synthetic data. The `tests/load/` framework generates production-scale data across 29 entity types (users, teams, tools, servers, metrics, sessions, etc.).

### Quick Start

```bash
# Generate small dataset (100 users, ~74K records, <1 minute)
make generate-small

# Generate medium dataset (10K users, ~70M records, ~10 min, needs PostgreSQL)
make generate-medium

# View generated data report
make generate-report
```

### Profiles

| Profile | Users | Records | Time | Database | Command |
|---------|-------|---------|------|----------|---------|
| Small | 100 | ~74K | <1 min | SQLite OK | `make generate-small` |
| Medium | 10K | ~70M | ~10 min | PostgreSQL | `make generate-medium` |
| Large | 100K | ~700M | ~1-2 hrs | PostgreSQL | `make generate-large` |
| Massive | 1M | ~7B | ~10-20 hrs | PostgreSQL + high-end | `make generate-massive` |

**Why it matters for load testing:** Many performance bottlenecks (N+1 queries, sequential scans, pagination overhead) only manifest with realistic data volumes. Testing with an empty database hides these issues.

For full documentation, configuration options, and custom profiles, see [`tests/load/README.md`](https://github.com/IBM/mcp-context-forge/blob/main/tests/load/README.md).

---

## 🔌 MCP Protocol Load Testing

The MCP Streamable HTTP endpoint (`/servers/{id}/mcp`) has different performance characteristics than the REST API. A dedicated load test isolates MCP protocol overhead from other endpoints.

### Quick Start

```bash
# MCP protocol test (150 users, 2 min, headless with reports)
make load-test-mcp-protocol

# MCP protocol test with Web UI (class picker to select user types)
make load-test-mcp-protocol-ui

# Heavy MCP test (500 users, 5 min)
make load-test-mcp-protocol-heavy
```

### What It Tests

The MCP protocol load test (`locustfile_mcp_protocol.py`) sends JSON-RPC requests exclusively to `/servers/{server_id}/mcp`. It auto-detects a virtual server with the most tools and discovers available tools, resources, and prompts via MCP protocol at startup.

**User Classes (selectable via `--class-picker` in Web UI):**

| User Class | Weight | Simulates |
|------------|--------|-----------|
| `MCPAgentUser` | 10 | Realistic AI agent with up to 6 tools — init, discover, call 1-3 tools per turn |
| `MCPToolCallerUser` | 5 | Heavy `tools/call` in tight loop |
| `MCPDiscoveryUser` | 3 | Discovery-heavy — `tools/list`, `resources/list`, `prompts/list`, templates |
| `MCPSessionChurnUser` | 2 | New MCP session every cycle (serverless worst-case) |
| `MCPStressUser` | 1 | `constant_throughput(5)` for predictable sustained load |
| `RESTBaselineUser` | 0 | `/rpc` + REST comparison baseline (opt-in via class picker) |

### Comparing MCP vs REST Performance

To compare MCP Streamable HTTP overhead against the REST `/rpc` path:

1. Open the Web UI: `make load-test-mcp-protocol-ui`
2. In the class picker, enable **both** MCP user classes and `RESTBaselineUser`
3. Run the test and compare per-endpoint RPS and latency in the statistics table

The MCP path includes additional middleware (MCPPathRewrite, MCP SDK session manager, per-request auth/RBAC database queries) that the `/rpc` endpoint avoids via Redis-backed caching. Under load, this difference is significant — see the [Performance Profiling Guide](../development/profiling.md#mcp-protocol-profiling) for investigation steps.

### Configuration

```bash
# Override the target server
MCP_SERVER_ID=<uuid> make load-test-mcp-protocol

# Override tool names (comma-separated)
MCP_TOOL_NAMES=my-tool-1,my-tool-2 make load-test-mcp-protocol

# Override target host
MCP_PROTOCOL_HOST=http://my-gateway:8080 make load-test-mcp-protocol
```

### What to Look For

- **RPS plateau**: MCP throughput saturates at a lower RPS than REST due to heavier per-request processing
- **PgBouncer/PostgreSQL CPU**: If these are high during MCP load but low during REST load, the MCP path is doing more DB queries per request
- **Redis utilization**: Low Redis CPU during MCP load indicates the MCP path is not leveraging the cache layer
- **Session pool metrics**: Check `/admin/mcp-pool/metrics` to verify upstream connection reuse
- **p99 latency**: Tail latency often reveals contention in the auth/RBAC path or upstream proxy

### Prerequisites

The test requires:

- At least one virtual server registered with associated tools (`POST /servers`)
- At least one MCP gateway connected (`POST /gateways`)
- Authentication configured (JWT auto-generated from `.env`)

Start the full testing stack with:

```bash
make testing-up      # Starts fast_test_server + locust + MCP inspector
```

---

## 🎯 Benchmark Server Stack

ContextForge includes a high-performance Go-based benchmark server that can spawn multiple MCP servers in a single process for load testing gateway registration, federation, and tool invocation at scale.

### Quick Start

```bash
# Start benchmark stack (10 MCP servers by default)
make benchmark-up

# Verify servers are running
curl http://localhost:9000/health
curl http://localhost:9009/health

# Run load tests against registered gateways
make load-test-ui
```

### Make Targets

| Target | Description |
|--------|-------------|
| `make benchmark-up` | Start benchmark servers + auto-register as gateways |
| `make benchmark-down` | Stop benchmark servers |
| `make benchmark-clean` | Stop and remove all benchmark data (volumes) |
| `make benchmark-status` | Show status of benchmark services |
| `make benchmark-logs` | View benchmark server logs |

### Configuration

Configure the number of servers via environment variables:

```bash
# Start 50 benchmark servers (ports 9000-9049)
BENCHMARK_SERVER_COUNT=50 make benchmark-up

# Start 100 servers on a different port range
BENCHMARK_SERVER_COUNT=100 BENCHMARK_START_PORT=9000 make benchmark-up
```

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHMARK_SERVER_COUNT` | 10 | Number of MCP servers to spawn |
| `BENCHMARK_START_PORT` | 9000 | Starting port number |

### Architecture

The benchmark stack consists of:

1. **benchmark_server** - A single Go binary that spawns multiple HTTP servers

   - Each server exposes MCP endpoints on a unique port (9000-9099)
   - Default: 50 tools, 20 resources, 10 prompts per server
   - Supports graceful shutdown via SIGINT/SIGTERM

2. **register_benchmark** - Auto-registration service

   - Registers all benchmark servers as gateways at compose startup
   - No manual registration required

### Endpoints per Server

Each benchmark server (e.g., `http://localhost:9000`) exposes:

| Endpoint | Description |
|----------|-------------|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/health` | Health check (`{"status": "healthy"}`) |
| `/version` | Version information |

### Resource Limits

The benchmark server is configured with reasonable resource limits:

| Servers | CPU Limit | Memory Limit |
|---------|-----------|--------------|
| 1-10 | 2 cores | 1 GB |
| 10-50 | 2 cores | 1 GB |
| 50-100 | 2 cores | 1 GB |

For larger deployments (100+ servers), consider increasing limits in `docker-compose.yml`.

### Example: Load Testing with 50 Gateways

```bash
# 1. Start 50 benchmark servers
BENCHMARK_SERVER_COUNT=50 make benchmark-up

# 2. Verify registration
curl -s http://localhost:8080/gateways -H "Authorization: Bearer $TOKEN" | jq 'length'
# Output: 52 (50 benchmark + fast_time + fast_test)

# 3. Run load test
make load-test-ui
# Open http://localhost:8089
# Select user classes and start swarming
```

### Standalone Usage (Without Docker)

```bash
# Build the benchmark server
cd mcp-servers/go/benchmark-server
make build

# Run single server
./dist/benchmark-server -transport=http -port=9000 -tools=100

# Run multi-server mode
./dist/benchmark-server -transport=http -server-count=10 -start-port=9000
```

### Performance Characteristics

The Go benchmark server is optimized for:

- **Low memory footprint**: ~5-10 MB per server
- **Fast startup**: All servers ready in <1 second
- **High throughput**: 10,000+ req/s per server
- **Graceful shutdown**: Clean termination on SIGINT/SIGTERM

---

## 🚀 JSON Serialization Performance: orjson

ContextForge uses **orjson** for high-performance JSON serialization, providing **5-6x faster serialization** and **1.5-2x faster deserialization** compared to Python's standard library `json` module.

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

ContextForge configures orjson as the default JSON response class for all FastAPI endpoints:

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

## 📈 JMeter Performance Testing

ContextForge includes [Apache JMeter](https://jmeter.apache.org/) test plans for industry-standard performance baseline measurements and CI/CD integration. JMeter is best suited for reproducible benchmarks and CI/CD gating; use Locust for interactive testing with complex user behavior.

### Install & Run

```bash
# Install JMeter (one-time, downloads 5.6.3 locally)
make jmeter-install

# Set up authentication
export MCPGATEWAY_BEARER_TOKEN=$(python -m mcpgateway.utils.create_jwt_token \
  --username admin@example.com --exp 10080 --secret $JWT_SECRET_KEY)

# Run key baselines
make jmeter-rest-baseline                                    # REST API — 1,000 RPS, 10 min
make jmeter-mcp-baseline JMETER_SERVER_ID=<server-id>       # MCP JSON-RPC — 1,000 RPS, 15 min
make jmeter-load JMETER_SERVER_ID=<server-id>               # Production load — 4,000 RPS, 30 min

# Interactive GUI for editing test plans
make jmeter-ui
```

### When to Use JMeter vs Locust

| Criterion | JMeter | Locust |
|-----------|--------|--------|
| Best for | CI/CD baselines, threshold gating | Interactive exploration, complex behavior |
| Protocol | HTTP, WebSocket, JDBC, gRPC | HTTP primarily |
| Config | XML test plans | Python code |
| Output | JTL files, HTML reports | HTML reports, CSV |
| Scaling | Distributed (controller/agent) | `--processes` multi-worker |

Use both: JMeter for repeatable CI checks, Locust for ad-hoc investigation and MCP protocol profiling.

### Available Test Plans

| Test Plan | Description | Duration | Target |
|-----------|-------------|----------|--------|
| `rest_api_baseline.jmx` | REST API endpoints baseline | 10 min | 1,000 RPS |
| `mcp_jsonrpc_baseline.jmx` | MCP JSON-RPC protocol baseline | 15 min | 1,000 RPS |
| `mcp_test_servers_baseline.jmx` | Direct MCP server testing | 10 min | 2,000 RPS |
| `load_test.jmx` | Production load simulation | 30 min | 4,000 RPS |
| `stress_test.jmx` | Progressive stress to breaking point | 30 min | 10,000 RPS |
| `spike_test.jmx` | Traffic spike recovery test | 10 min | 1K→10K→1K |
| `soak_test.jmx` | Memory leak detection | 24 hrs | 2,000 RPS |
| `sse_streaming_baseline.jmx` | SSE connection stability | 10 min | 1,000 conn |
| `websocket_baseline.jmx` | WebSocket performance | 10 min | 500 conn |
| `admin_ui_baseline.jmx` | Admin UI user simulation | 5 min | 50 users |

### Makefile Targets

```bash
# Setup
make jmeter-install                # Download and install JMeter 5.6.3 locally
make jmeter-check                  # Verify JMeter 5.x+ is available
make jmeter-ui                     # Launch JMeter GUI for test editing

# Baseline Tests
make jmeter-rest-baseline          # REST API baseline (1,000 RPS, 10min)
make jmeter-mcp-baseline           # MCP JSON-RPC baseline (1,000 RPS, 15min)
make jmeter-mcp-servers-baseline   # MCP test servers baseline
make jmeter-sse                    # SSE streaming baseline
make jmeter-websocket              # WebSocket baseline
make jmeter-admin-ui               # Admin UI baseline

# Load Tests
make jmeter-load                   # Load test (4,000 RPS, 30min)
make jmeter-stress                 # Stress test (ramp to 10,000 RPS)
make jmeter-spike                  # Spike test (1K→10K→1K recovery)
make jmeter-soak                   # 24-hour soak test (2,000 RPS)

# Reporting
make jmeter-report                 # Generate HTML report from latest JTL
make jmeter-compare                # Compare current vs baseline results
```

### Command-Line Usage

```bash
# Run with default settings
jmeter -n -t tests/jmeter/rest_api_baseline.jmx \
  -JGATEWAY_URL=http://localhost:8080 \
  -JTOKEN=$MCPGATEWAY_BEARER_TOKEN \
  -l results/test.jtl \
  -e -o results/report/

# Run with properties file
jmeter -p tests/jmeter/properties/production.properties \
  -n -t tests/jmeter/load_test.jmx \
  -l results/load.jtl
```

### HTTPS/TLS Testing

All test plans support both HTTP and HTTPS by specifying the full URL:

```bash
# HTTP (port 8080)
make jmeter-rest-baseline JMETER_GATEWAY_URL=http://localhost:8080

# HTTPS/TLS (port 8443)
make jmeter-rest-baseline JMETER_GATEWAY_URL=https://localhost:8443
```

For self-signed certificates, you may need to configure Java's truststore or use the SSL settings in `properties/production.properties`.

### Performance SLAs

| Metric | Baseline | Load | Stress |
|--------|----------|------|--------|
| P50 Latency | < 100ms | < 150ms | < 300ms |
| P95 Latency | < 200ms | < 300ms | < 500ms |
| P99 Latency | < 300ms | < 500ms | < 1000ms |
| Error Rate | < 0.1% | < 0.5% | < 1% |
| Throughput | 1,000 RPS | 4,000 RPS | 10,000 RPS |

### CI/CD Integration

```yaml
- name: Run JMeter baseline
  run: |
    jmeter -n -t tests/jmeter/rest_api_baseline.jmx \
      -p tests/jmeter/properties/ci.properties \
      -JGATEWAY_URL=http://gateway:8080 \
      -JTOKEN=${{ secrets.JWT_TOKEN }} \
      -l results.jtl \
      -e -o report/

- name: Check performance thresholds
  run: |
    # Parse JTL and check P95 < 300ms
    P95=$(awk -F',' 'NR>1 {print $2}' results.jtl | sort -n | awk 'NR==int(ENVIRON["NR"]*0.95)')
    if [ "$P95" -gt 300 ]; then
      echo "P95 latency ($P95 ms) exceeds threshold (300ms)"
      exit 1
    fi
```

### JMeter vs Locust

| Feature | JMeter | Locust |
|---------|--------|--------|
| Protocol support | HTTP, WebSocket, JDBC, etc. | HTTP primarily |
| Configuration | XML-based GUI | Python code |
| CI/CD integration | CLI-based, JTL reports | HTML reports |
| Scripting | BeanShell, Groovy | Python |
| Best for | CI/CD baselines, detailed metrics | Interactive testing, realistic scenarios |

Use **JMeter** for CI/CD baselines and reproducible performance metrics. Use **Locust** for interactive load testing with complex user behaviors.

For full documentation, see `tests/jmeter/README.md`.

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

## See Also

- [Performance Profiling Guide](../development/profiling.md) - py-spy, memray, PostgreSQL profiling, MCP bottleneck triage
- [Gateway Tuning Guide](../manage/tuning.md) - Environment variables, MCP transport settings, session pool tuning, disable unused features
- [Database Performance Guide](../development/db-performance.md) - N+1 detection, query logging, DB vs transport bottleneck triage
- [Performance Architecture](../architecture/performance-architecture.md) - MCP request path, caching layers, scaling capacity
