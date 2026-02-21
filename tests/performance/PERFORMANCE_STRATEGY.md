# Performance Testing Strategy

**Version:** 1.0
**Last Updated:** 2025-10-09
**Status:** Active

## Table of Contents

1. [Overview](#overview)
2. [Testing Phases](#testing-phases)
3. [Testing Methodology](#testing-methodology)
4. [Monitoring & Observability](#monitoring--observability)
5. [Profiling & Analysis](#profiling--analysis)
6. [Database Performance](#database-performance)
7. [Bottleneck Identification](#bottleneck-identification)
8. [Continuous Performance Testing](#continuous-performance-testing)
9. [Performance Baselines & SLOs](#performance-baselines--slos)
10. [Tooling & Infrastructure](#tooling--infrastructure)
11. [Reporting & Visualization](#reporting--visualization)

---

## Overview

This document defines a comprehensive, multi-layered performance testing strategy for the ContextForge ecosystem. The goal is to identify performance bottlenecks, establish baselines, and ensure the system meets service level objectives (SLOs) under various load conditions.

### Objectives

- **Establish baselines** for individual components and the integrated system
- **Identify bottlenecks** at all layers (application, database, network)
- **Monitor resource utilization** during load testing
- **Profile code paths** to find hot spots
- **Optimize database** queries and connection pooling
- **Validate scalability** under increasing load
- **Track performance regression** over time

### Key Principles

1. **Test in isolation first** - Validate individual components before integration
2. **Monitor everything** - Collect metrics at all layers during tests
3. **Profile before optimizing** - Use data to drive optimization decisions
4. **Automate testing** - Make performance testing part of CI/CD
5. **Track trends** - Compare results over time to detect regressions

---

## Testing Phases

### Phase 1: Individual Component Testing

Test each component in isolation to establish baseline performance.

#### 1.1 MCP Server Testing (Standalone)

**Objective:** Measure MCP server performance without gateway overhead.

**Test Targets:**
- `fast-time-server` (Go-based MCP server)
- Other MCP servers (mcp-server-git, etc.)

**Metrics to Collect:**
- Tool invocation latency (p50, p95, p99)
- Resource read latency
- Prompt execution latency
- Throughput (requests/second)
- Memory usage
- CPU utilization
- Error rate

**Test Scenarios:**
```bash
# Direct SSE connection to MCP server
# Test tools/list performance
hey -n 10000 -c 50 -m POST \
  -T "application/json" \
  -D payloads/tools/list_tools.json \
  http://localhost:8888/sse

# Test individual tool invocation
hey -n 5000 -c 25 -m POST \
  -T "application/json" \
  -D payloads/tools/get_system_time.json \
  http://localhost:8888/sse
```

**Success Criteria:**
- Tool listing: <10ms p95
- Simple tool invocation: <20ms p95
- Complex tool invocation: <50ms p95
- Zero errors under normal load

#### 1.2 Gateway Core Testing (No MCP Servers)

**Objective:** Measure gateway overhead without MCP server interactions.

**Test Targets:**
- Health endpoints
- Authentication
- Routing logic
- Admin UI

**Metrics to Collect:**
- Health check latency
- Authentication overhead
- Routing decision time
- Memory footprint
- Database query count

**Test Scenarios:**
```bash
# Health endpoint performance
hey -n 100000 -c 100 /health

# Authentication overhead
hey -n 10000 -c 50 \
  -H "Authorization: Bearer $TOKEN" \
  /health
```

**Success Criteria:**
- Health check: <5ms p95
- Authenticated request: <10ms p95
- Memory stable under sustained load

#### 1.3 Database Layer Testing

**Objective:** Validate database performance in isolation.

**Test Targets:**
- SQLite (default)
- PostgreSQL (production)

**Tests:**
- Connection pool saturation
- Query performance
- Index effectiveness
- Write throughput
- Read throughput
- Transaction overhead

See [Database Performance](#database-performance) section for details.

---

### Phase 2: Integrated Gateway Testing

Test the complete gateway with registered MCP servers.

#### 2.1 Gateway + Single MCP Server

**Objective:** Measure gateway overhead when proxying to one MCP server.

**Setup:**
1. Start fast-time-server
2. Register as gateway peer
3. Create virtual server
4. Run load tests through gateway

**Metrics to Collect:**
- End-to-end latency (client → gateway → MCP server → client)
- Gateway overhead (total latency - MCP server latency)
- Connection pooling efficiency
- SSE/WebSocket performance
- Request queuing delays

**Test Scenarios:**
```bash
# Tools through gateway
./scenarios/tools-benchmark.sh -p heavy

# Resources through gateway
./scenarios/resources-benchmark.sh -p heavy

# Prompts through gateway
./scenarios/prompts-benchmark.sh -p heavy
```

**Success Criteria:**
- Gateway overhead: <15ms p95
- End-to-end tool invocation: <30ms p95
- No connection pool exhaustion
- Zero request drops

#### 2.2 Gateway + Multiple MCP Servers

**Objective:** Test gateway performance with multiple registered servers.

**Setup:**
1. Register 5-10 different MCP servers
2. Create multiple virtual servers
3. Run concurrent workloads across servers

**Metrics to Collect:**
- Per-server latency
- Server selection overhead
- Resource contention
- Database query count
- Cache hit rate

**Test Scenarios:**
```bash
# Mixed workload across multiple servers
./scenarios/mixed-workload.sh -p heavy

# Concurrent virtual server access
./scenarios/multi-server-benchmark.sh
```

**Success Criteria:**
- No degradation with up to 10 servers
- Fair resource allocation across servers
- Cache hit rate >80%

#### 2.3 Gateway Federation Testing

**Objective:** Test performance when federating across multiple gateway instances.

**Setup:**
1. Start 3 gateway instances
2. Configure federation (Redis)
3. Register servers on different gateways
4. Test cross-gateway tool invocation

**Metrics to Collect:**
- Federation discovery latency
- Cross-gateway routing overhead
- Redis performance
- mDNS discovery time
- Network latency between gateways

---

### Phase 3: Stress & Capacity Testing

Push the system to its limits to find breaking points.

#### 3.1 Load Ramp Testing

**Objective:** Find the maximum sustainable load.

**Method:**
- Start with light load (10 concurrent users)
- Gradually increase to heavy load (500+ concurrent users)
- Identify point where latency/errors spike

**Tools:**
```bash
# Gradual ramp
for concurrency in 10 50 100 200 500 1000; do
  hey -n 10000 -c $concurrency -m POST \
    -T "application/json" \
    -D payloads/tools/list_tools.json \
    http://localhost:4444/rpc
  sleep 10
done
```

#### 3.2 Sustained Load Testing

**Objective:** Verify stability under sustained load.

**Duration:** 1-4 hours

**Metrics:**
- Memory leak detection
- Connection leak detection
- CPU degradation over time
- Database bloat

**Tools:**
```bash
# Run for 1 hour
hey -z 1h -c 50 -q 100 -m POST \
  -T "application/json" \
  -D payloads/tools/list_tools.json \
  http://localhost:4444/rpc
```

#### 3.3 Spike Testing

**Objective:** Test system resilience to sudden load spikes.

**Method:**
- Run normal load (50 concurrent)
- Inject spike (500 concurrent for 30s)
- Return to normal load
- Measure recovery time

---

## Testing Methodology

### Load Testing Tools

**Primary:** `hey` (HTTP load testing)
- Fast, concurrent request generation
- Detailed latency histograms
- Easy to script and automate

**Alternative:** `locust` (Python-based)
- More complex scenarios
- Web UI for monitoring
- Custom user behaviors

**Alternative:** `k6` (JavaScript-based)
- Sophisticated scenarios
- Built-in metrics collection
- Cloud integration

### Test Data

**Payloads:**
- Store in `payloads/` directory
- Use realistic data sizes
- Include edge cases (large inputs, unicode, etc.)

**Randomization:**
- Vary request parameters
- Randomize timezones, times, etc.
- Avoid cache bias

### Test Execution

**Environment:**
- Consistent hardware (document specs)
- Isolated network (minimize noise)
- Fresh database state
- Cleared caches

**Process:**
1. Warm up (100 requests, discard results)
2. Run actual test
3. Cool down period
4. Collect metrics
5. Reset state

---

## Monitoring & Observability

### System Metrics Collection

#### 4.1 Host Metrics

**CPU:**
```bash
# Monitor during tests
vmstat 1

# Average CPU usage
sar -u 1 60
```

**Memory:**
```bash
# Real-time monitoring
watch -n 1 free -h

# Detailed memory stats
cat /proc/meminfo
```

**Disk I/O:**
```bash
# I/O statistics
iostat -x 1

# Disk usage
df -h
watch -n 1 du -sh /path/to/db
```

**Network:**
```bash
# Network throughput
iftop

# Connection states
ss -s
netstat -an | awk '/tcp/ {print $6}' | sort | uniq -c
```

#### 4.2 Application Metrics

**Prometheus Metrics:**
```bash
# Enable in .env
MCPGATEWAY_ENABLE_PROMETHEUS=true

# Scrape during tests
curl http://localhost:4444/metrics > metrics_before.txt
# Run test
curl http://localhost:4444/metrics > metrics_after.txt
# Diff and analyze
```

**Key Metrics:**
- `http_requests_total` - Total requests
- `http_request_duration_seconds` - Latency histogram
- `http_requests_in_flight` - Concurrent requests
- `database_connections_active` - Active DB connections
- `database_connections_idle` - Idle DB connections
- `cache_hits_total` / `cache_misses_total` - Cache efficiency

#### 4.3 Database Metrics

**PostgreSQL:**
```sql
-- Connection stats
SELECT * FROM pg_stat_activity;

-- Query performance
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 20;

-- Lock contention
SELECT * FROM pg_locks;

-- Cache hit ratio
SELECT
  sum(heap_blks_read) as heap_read,
  sum(heap_blks_hit) as heap_hit,
  sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as ratio
FROM pg_statio_user_tables;
```

**SQLite:**
```bash
# Enable query logging
sqlite3 mcp.db ".log stdout"
sqlite3 mcp.db ".stats on"

# Analyze queries
sqlite3 mcp.db "EXPLAIN QUERY PLAN SELECT ..."
```

#### 4.4 Container Metrics (Docker)

```bash
# Real-time stats
docker stats

# Continuous monitoring during test
docker stats --no-stream --format \
  "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" \
  > docker_stats.txt &
STATS_PID=$!

# Run test
./run-all.sh -p heavy

# Stop monitoring
kill $STATS_PID
```

### Automated Monitoring Scripts

Create `utils/monitor-during-test.sh`:
```bash
#!/usr/bin/env bash
# Collect all metrics during a test run

OUTPUT_DIR="$1"
INTERVAL="${2:-5}"

mkdir -p "$OUTPUT_DIR"

# CPU & Memory
vmstat $INTERVAL > "$OUTPUT_DIR/vmstat.log" &
PIDS+=($!)

# Network
ss -s > "$OUTPUT_DIR/network_stats.log" &
PIDS+=($!)

# Docker stats
docker stats --no-stream --format "{{.Container}},{{.CPUPerc}},{{.MemUsage}}" \
  > "$OUTPUT_DIR/docker_stats.csv" &
PIDS+=($!)

# Wait for test completion signal
trap "kill ${PIDS[@]}; exit 0" SIGTERM SIGINT

wait
```

---

## Profiling & Analysis

### 5.1 Python Application Profiling

#### cProfile Integration

**Profile a specific endpoint:**
```python
# Add to main.py for temporary profiling
import cProfile
import pstats
from io import StringIO

@app.middleware("http")
async def profile_middleware(request: Request, call_next):
    if request.url.path == "/rpc" and ENABLE_PROFILING:
        profiler = cProfile.Profile()
        profiler.enable()

        response = await call_next(request)

        profiler.disable()
        s = StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
        ps.print_stats()

        # Save to file
        with open(f"profiles/profile_{time.time()}.txt", "w") as f:
            f.write(s.getvalue())

        return response
    return await call_next(request)
```

**Run with profiling:**
```bash
# Enable profiling
export ENABLE_PROFILING=true

# Run test
./scenarios/tools-benchmark.sh -p medium

# Analyze profiles
python3 -m pstats profiles/profile_*.txt
# Commands: sort cumulative, stats 20
```

#### py-spy for Live Profiling

**Install:**
```bash
pip install py-spy
```

**Profile running process:**
```bash
# Find PID
PID=$(ps aux | grep "uvicorn mcpgateway.main:app" | grep -v grep | awk '{print $2}')

# Record flame graph during test
py-spy record -o profile.svg --pid $PID --duration 60 &

# Run load test
./scenarios/tools-benchmark.sh -p heavy

# View profile.svg in browser
```

#### Memory Profiling

**Using memory_profiler:**
```bash
pip install memory-profiler

# Add @profile decorator to functions
# Run with:
python -m memory_profiler mcpgateway/services/gateway_service.py
```

**Using tracemalloc:**
```python
# Add to main.py
import tracemalloc

@app.on_event("startup")
async def startup():
    tracemalloc.start()

@app.get("/admin/memory-snapshot")
async def memory_snapshot():
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')

    return {
        "top_10": [
            {
                "file": str(stat.traceback),
                "size_mb": stat.size / 1024 / 1024,
                "count": stat.count
            }
            for stat in top_stats[:10]
        ]
    }
```

### 5.2 Database Query Profiling

#### PostgreSQL Query Analysis

**Enable pg_stat_statements:**
```sql
-- In postgresql.conf
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all

-- Restart and create extension
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

**Analyze slow queries during test:**
```sql
-- Reset stats before test
SELECT pg_stat_statements_reset();

-- Run performance test
-- ...

-- View slowest queries
SELECT
    substring(query, 1, 100) AS short_query,
    calls,
    total_time,
    mean_time,
    max_time,
    stddev_time
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY mean_time DESC
LIMIT 20;

-- Identify queries with high variability
SELECT
    substring(query, 1, 100) AS short_query,
    calls,
    mean_time,
    stddev_time,
    (stddev_time / mean_time) * 100 AS variability_percent
FROM pg_stat_statements
WHERE calls > 100
ORDER BY variability_percent DESC
LIMIT 20;
```

**EXPLAIN ANALYZE:**
```sql
-- For problematic queries identified above
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
SELECT ...;
```

#### SQLite Query Analysis

**Enable query logging:**
```python
# In config.py
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

**Analyze query plans:**
```bash
sqlite3 mcp.db "EXPLAIN QUERY PLAN SELECT * FROM tools WHERE server_id = 1;"
```

### 5.3 Network Profiling

**Capture traffic during test:**
```bash
# Start capture
tcpdump -i any -w gateway_traffic.pcap port 4444 &
TCPDUMP_PID=$!

# Run test
./scenarios/tools-benchmark.sh

# Stop capture
kill $TCPDUMP_PID

# Analyze with Wireshark or tshark
tshark -r gateway_traffic.pcap -q -z io,stat,1
```

**Measure latency breakdown:**
```bash
# curl with timing
curl -w "\nDNS: %{time_namelookup}s\nConnect: %{time_connect}s\nTLS: %{time_appconnect}s\nStart Transfer: %{time_starttransfer}s\nTotal: %{time_total}s\n" \
  -H "Authorization: Bearer $TOKEN" \
  -X POST -d @payloads/tools/list_tools.json \
  http://localhost:4444/rpc
```

---

## Database Performance

### 6.1 Connection Pool Optimization

#### Current Settings Audit

**PostgreSQL (SQLAlchemy):**
```python
# In config.py, document current settings:
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://...")
SQLALCHEMY_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
SQLALCHEMY_MAX_OVERFLOW = int(os.getenv("DB_POOL_MAX_OVERFLOW", "40"))
SQLALCHEMY_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
SQLALCHEMY_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))
```

#### Connection Pool Testing

**Test 1: Pool Exhaustion**
```bash
# Test with varying pool sizes
for pool_size in 5 10 20 50 100; do
  export DB_POOL_SIZE=$pool_size
  export DB_POOL_MAX_OVERFLOW=$((pool_size * 2))

  # Restart gateway
  make restart

  # Run high concurrency test
  hey -n 10000 -c 200 -m POST \
    -T "application/json" \
    -D payloads/tools/list_tools.json \
    http://localhost:4444/rpc \
    > results/pool_test_${pool_size}.txt
done

# Analyze results
grep "Requests/sec" results/pool_test_*.txt
```

**Test 2: Connection Leak Detection**
```sql
-- Monitor connections during sustained test
-- Run this query every 10 seconds during a 1-hour test

SELECT
    datname,
    count(*) as connections,
    max(now() - state_change) as longest_idle
FROM pg_stat_activity
WHERE datname = 'mcpgateway'
GROUP BY datname;

-- Should remain stable; growing count indicates leak
```

**Test 3: Pool Recycle Effectiveness**
```bash
# Test with different recycle times
for recycle in 300 1800 3600 7200; do
  export DB_POOL_RECYCLE=$recycle

  # Run sustained test
  hey -z 30m -c 50 -q 100 -m POST \
    -T "application/json" \
    -D payloads/tools/list_tools.json \
    http://localhost:4444/rpc

  # Monitor connection age in database
done
```

### 6.2 Query Performance Optimization

#### Index Analysis

**Identify missing indexes:**
```sql
-- PostgreSQL: Find sequential scans on large tables
SELECT
    schemaname,
    tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    seq_tup_read / seq_scan as avg_seq_read
FROM pg_stat_user_tables
WHERE seq_scan > 0
ORDER BY seq_tup_read DESC
LIMIT 20;

-- Tables with high seq_scan need indexes
```

**Test index effectiveness:**
```sql
-- Before adding index
EXPLAIN ANALYZE SELECT * FROM tools WHERE server_id = 1;

-- Add index
CREATE INDEX idx_tools_server_id ON tools(server_id);

-- After adding index
EXPLAIN ANALYZE SELECT * FROM tools WHERE server_id = 1;

-- Compare execution time
```

#### Query Optimization Tests

**Common queries to optimize:**

1. **Tool lookup by server:**
```sql
-- Baseline
EXPLAIN ANALYZE
SELECT * FROM tools WHERE server_id = 1;

-- Add index if missing
CREATE INDEX IF NOT EXISTS idx_tools_server_id ON tools(server_id);

-- Test improvement
```

2. **Virtual server composition:**
```sql
-- Baseline
EXPLAIN ANALYZE
SELECT t.* FROM tools t
JOIN virtual_server_tools vst ON t.id = vst.tool_id
WHERE vst.virtual_server_id = 1;

-- Add composite index
CREATE INDEX IF NOT EXISTS idx_virtual_server_tools_lookup
ON virtual_server_tools(virtual_server_id, tool_id);
```

3. **Gateway peer lookup:**
```sql
-- Baseline
EXPLAIN ANALYZE
SELECT * FROM gateway_peers WHERE is_active = true;

-- Add partial index
CREATE INDEX IF NOT EXISTS idx_active_gateway_peers
ON gateway_peers(is_active) WHERE is_active = true;
```

### 6.3 Database Load Testing

**Write-heavy test:**
```python
# Test tool registration performance
import time
import statistics

times = []
for i in range(1000):
    start = time.time()
    # POST /tools with new tool
    response = requests.post(...)
    times.append(time.time() - start)

print(f"Mean: {statistics.mean(times):.3f}s")
print(f"p95: {statistics.quantiles(times, n=20)[18]:.3f}s")
print(f"p99: {statistics.quantiles(times, n=100)[98]:.3f}s")
```

**Read-heavy test:**
```bash
# GET /tools with pagination
for page_size in 10 50 100 500; do
  hey -n 5000 -c 50 \
    "http://localhost:4444/tools?skip=0&limit=$page_size" \
    > results/read_pagination_${page_size}.txt
done
```

**Mixed workload:**
```python
# Simulate realistic usage pattern
# 70% reads, 25% updates, 5% writes
```

### 6.4 Database Monitoring During Tests

**Create monitoring script:**
```bash
#!/usr/bin/env bash
# utils/monitor-db.sh

while true; do
  psql -U postgres -d mcpgateway -c "
    SELECT
      now(),
      (SELECT count(*) FROM pg_stat_activity WHERE datname='mcpgateway') as connections,
      (SELECT count(*) FROM pg_stat_activity WHERE state='active') as active,
      (SELECT count(*) FROM pg_stat_activity WHERE state='idle') as idle,
      (SELECT pg_database_size('mcpgateway')/1024/1024) as size_mb
  " >> db_stats.log

  sleep 5
done
```

---

## Bottleneck Identification

### 7.1 Systematic Bottleneck Detection

**Process:**

1. **Measure end-to-end latency** (client perspective)
2. **Break down by component:**
   - Network latency
   - Gateway processing
   - Database queries
   - MCP server calls
   - Response serialization
3. **Identify slowest component**
4. **Profile that component**
5. **Optimize and re-test**

**Instrumentation Example:**
```python
# Add timing to each layer
import time
from functools import wraps

def timed(layer_name):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start

            # Log to metrics
            metrics.histogram(f"{layer_name}.duration", duration)

            return result
        return wrapper
    return decorator

@timed("gateway.route")
async def route_request(...):
    ...

@timed("database.query")
async def get_tools(...):
    ...

@timed("mcp.invoke")
async def invoke_tool(...):
    ...
```

### 7.2 Common Bottlenecks

**Symptom:** High latency, low throughput, CPU below 50%
- **Likely cause:** Database connection pool exhaustion
- **Test:** Increase pool size
- **Monitor:** `pg_stat_activity` connection count

**Symptom:** High CPU, good throughput, increasing latency
- **Likely cause:** Inefficient code path
- **Test:** Profile with py-spy
- **Monitor:** CPU per core

**Symptom:** High memory usage, slow responses
- **Likely cause:** Memory leak or large result sets
- **Test:** Memory profiler, check query result sizes
- **Monitor:** Memory growth over time

**Symptom:** Erratic latency, high variance
- **Likely cause:** Lock contention, cache misses
- **Test:** Check database locks, cache hit rate
- **Monitor:** `pg_locks`, cache metrics

### 7.3 Bottleneck Test Matrix

Create a test matrix to systematically identify bottlenecks:

| Component | Metric | Test | Expected | Actual | Bottleneck? |
|-----------|--------|------|----------|--------|-------------|
| Network | Latency | ping | <1ms | 0.5ms | ❌ |
| Gateway Auth | Overhead | /health with auth | <5ms | 3ms | ❌ |
| Gateway Routing | Time | route decision | <2ms | 8ms | ⚠️ |
| DB Connection | Wait time | pool.get() | <10ms | 45ms | ✅ |
| DB Query | Execution | SELECT tools | <5ms | 3ms | ❌ |
| MCP Server | Tool call | direct invoke | <20ms | 15ms | ❌ |
| Serialization | JSON encode | response.json() | <1ms | 0.5ms | ❌ |

**Action:** Focus optimization on DB connection pooling (45ms wait time).

---

## Continuous Performance Testing

### 8.1 CI/CD Integration

**GitHub Actions workflow:**
```yaml
name: Performance Benchmarks

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday at 2 AM

jobs:
  performance:
    runs-on: ubuntu-latest
    timeout-minutes: 60

    steps:
      - uses: actions/checkout@v3

      - name: Install dependencies
        run: |
          go install github.com/rakyll/hey@latest
          pip install -r requirements.txt

      - name: Start services
        run: make compose-up

      - name: Wait for healthy services
        run: ./tests/performance/utils/check-services.sh

      - name: Run performance tests
        run: |
          cd tests/performance
          ./run-all.sh -p light

      - name: Collect metrics
        if: always()
        run: |
          docker stats --no-stream > perf_docker_stats.txt
          docker logs gateway > perf_gateway_logs.txt

      - name: Upload results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: performance-results
          path: |
            tests/performance/results/
            perf_*.txt

      - name: Compare with baseline
        run: |
          python tests/performance/utils/compare_baselines.py \
            --baseline baselines/main_baseline.json \
            --current tests/performance/results/summary_light_*.json \
            --threshold 10  # Fail if >10% regression
```

### 8.2 Performance Regression Detection

**Store baselines:**
```bash
# After major release or optimization
./run-all.sh -p medium

# Save as baseline
cp results/summary_medium_*.md baselines/v1.2.0_baseline.md
```

**Compare script (`utils/compare_baselines.py`):**
```python
#!/usr/bin/env python3
import json
import sys

def compare_results(baseline, current, threshold_percent):
    """
    Compare current results against baseline.
    Fail if any metric regresses by more than threshold_percent.
    """
    regressions = []

    for test_name, baseline_metrics in baseline.items():
        current_metrics = current.get(test_name, {})

        for metric, baseline_value in baseline_metrics.items():
            current_value = current_metrics.get(metric)

            if current_value is None:
                continue

            # Calculate regression percentage
            if baseline_value > 0:
                regression_pct = ((current_value - baseline_value) / baseline_value) * 100

                if regression_pct > threshold_percent:
                    regressions.append({
                        'test': test_name,
                        'metric': metric,
                        'baseline': baseline_value,
                        'current': current_value,
                        'regression': regression_pct
                    })

    return regressions

if __name__ == "__main__":
    # Usage: compare_baselines.py --baseline base.json --current curr.json --threshold 10
    # Returns exit code 1 if regressions found
    ...
```

### 8.3 Performance Dashboard

**Option 1: Static HTML Report**

Generate after each test:
```bash
# utils/generate_report.sh
python3 utils/report_generator.py \
  --results results/ \
  --output reports/perf_report_$(date +%Y%m%d).html
```

**Option 2: Grafana + InfluxDB**

Send metrics to time-series database:
```python
# In test runner
from influxdb_client import InfluxDBClient

client = InfluxDBClient(url="http://localhost:8086", token="...", org="...")
write_api = client.write_api()

# After test
point = Point("performance_test") \
    .tag("test_name", test_name) \
    .tag("profile", profile) \
    .field("requests_per_sec", rps) \
    .field("p95_latency_ms", p95) \
    .field("error_rate", error_rate) \
    .time(datetime.utcnow())

write_api.write(bucket="mcpgateway", record=point)
```

**Option 3: GitHub Pages**

Publish results to GitHub Pages:
```yaml
- name: Deploy results to GitHub Pages
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_dir: ./tests/performance/reports
```

---

## Performance Baselines & SLOs

### 9.1 Service Level Objectives (SLOs)

Define performance targets based on user expectations:

| Operation | Target p95 | Target p99 | Target RPS | Target Error Rate |
|-----------|-----------|-----------|-----------|-------------------|
| Health Check | <5ms | <10ms | 1000+ | 0% |
| Tool List | <30ms | <50ms | 500+ | <0.1% |
| Tool Invoke (simple) | <50ms | <100ms | 300+ | <0.1% |
| Tool Invoke (complex) | <100ms | <200ms | 200+ | <0.5% |
| Resource Read | <40ms | <80ms | 400+ | <0.1% |
| Prompt Get | <60ms | <120ms | 300+ | <0.1% |
| Virtual Server Create | <200ms | <500ms | 50+ | <1% |

### 9.2 Baseline Establishment

**Hardware Specification (Document):**
```
CPU: [e.g., Intel Xeon E5-2670 v3 @ 2.30GHz, 8 cores]
RAM: [e.g., 16GB DDR4]
Disk: [e.g., NVMe SSD, 500GB]
Network: [e.g., 1Gbps]
OS: [e.g., Ubuntu 22.04]
```

**Baseline Test Results:**
```bash
# Run comprehensive baseline
./run-all.sh -p medium | tee baselines/baseline_$(uname -n)_$(date +%Y%m%d).txt

# Save system info
{
  echo "=== System Info ==="
  uname -a
  lscpu | grep "Model name"
  free -h
  df -h
} > baselines/system_info_$(uname -n).txt
```

### 9.3 SLO Monitoring

**Create SLO validation test:**
```python
# tests/performance/validate_slo.py
import json
import sys

SLO_TARGETS = {
    "tools/list": {"p95_ms": 30, "p99_ms": 50, "rps": 500},
    "tools/invoke_simple": {"p95_ms": 50, "p99_ms": 100, "rps": 300},
    # ... more
}

def validate_slo(test_results):
    violations = []

    for test_name, targets in SLO_TARGETS.items():
        actual = test_results.get(test_name, {})

        for metric, target_value in targets.items():
            actual_value = actual.get(metric)

            if actual_value is None:
                continue

            if metric.endswith("_ms") and actual_value > target_value:
                violations.append(f"{test_name}.{metric}: {actual_value}ms > {target_value}ms")
            elif metric == "rps" and actual_value < target_value:
                violations.append(f"{test_name}.{metric}: {actual_value} < {target_value}")

    return violations

if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        results = json.load(f)

    violations = validate_slo(results)

    if violations:
        print("SLO VIOLATIONS:")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)
    else:
        print("✅ All SLOs met")
        sys.exit(0)
```

---

## Tooling & Infrastructure

### 10.1 Required Tools

**Load Generation:**
- ✅ `hey` - HTTP load testing (installed)
- `locust` - Advanced scenarios (optional)
- `k6` - Cloud load testing (optional)

**Monitoring:**
- `htop` / `btop` - Interactive process viewer
- `iotop` - I/O monitoring
- `nethogs` - Network monitoring by process
- `docker stats` - Container resource usage

**Profiling:**
- `py-spy` - Python profiling (no code changes)
- `cProfile` - Built-in Python profiler
- `memory_profiler` - Memory usage profiling
- `perf` - Linux performance analysis

**Database:**
- `pg_stat_statements` - PostgreSQL query stats
- `pgBadger` - PostgreSQL log analyzer
- `sqlite3` - SQLite command-line

**Network:**
- `tcpdump` - Packet capture
- `wireshark` / `tshark` - Packet analysis
- `curl` - HTTP testing with timing

### 10.2 Test Environment Setup

**Dedicated performance test environment:**
```bash
# docker-compose.perf.yml
version: '3.8'

services:
  gateway:
    build: .
    environment:
      - DATABASE_URL=postgresql://perf_user:perf_pass@postgres:5432/mcpgateway_perf
      - REDIS_URL=redis://redis:6379
      - LOG_LEVEL=WARNING  # Reduce logging overhead
      - MCPGATEWAY_ENABLE_PROMETHEUS=true
    ports:
      - "4444:4444"
      - "9090:9090"  # Prometheus metrics

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: mcpgateway_perf
      POSTGRES_USER: perf_user
      POSTGRES_PASSWORD: perf_pass
    ports:
      - "5432:5432"
    volumes:
      - perf_pgdata:/var/lib/postgresql/data
    command:
      - "postgres"
      - "-c"
      - "shared_preload_libraries=pg_stat_statements"
      - "-c"
      - "pg_stat_statements.track=all"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./infra/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9091:9090"

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - perf_grafana_data:/var/lib/grafana

volumes:
  perf_pgdata:
  perf_grafana_data:
```

**Start performance environment:**
```bash
docker-compose -f docker-compose.perf.yml up -d
```

### 10.3 Automation Scripts

Create comprehensive test automation:

**`tests/performance/run-full-suite.sh`:**
```bash
#!/usr/bin/env bash
# Complete performance testing suite with monitoring

set -Eeuo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULTS_DIR="results_${TIMESTAMP}"

mkdir -p "$RESULTS_DIR"/{monitoring,profiles,reports}

# Step 1: Baseline the MCP server directly
echo "=== Testing MCP Server (Standalone) ==="
./scenarios/test-mcp-server-direct.sh > "$RESULTS_DIR/01_mcp_baseline.txt"

# Step 2: Test gateway core
echo "=== Testing Gateway Core ==="
./scenarios/test-gateway-core.sh > "$RESULTS_DIR/02_gateway_core.txt"

# Step 3: Start monitoring
echo "=== Starting Monitoring ==="
./utils/monitor-during-test.sh "$RESULTS_DIR/monitoring" 5 &
MONITOR_PID=$!

# Step 4: Profile during load
echo "=== Starting Profiler ==="
PID=$(ps aux | grep uvicorn | grep -v grep | awk '{print $2}')
py-spy record -o "$RESULTS_DIR/profiles/flame.svg" --pid $PID --duration 300 &
PROFILER_PID=$!

# Step 5: Run full test suite
echo "=== Running Full Test Suite ==="
./run-all.sh -p heavy > "$RESULTS_DIR/03_full_suite.txt"

# Step 6: Stop monitoring
kill $MONITOR_PID $PROFILER_PID

# Step 7: Collect database stats
echo "=== Collecting Database Stats ==="
psql -U perf_user -d mcpgateway_perf -f utils/db_stats.sql > "$RESULTS_DIR/04_db_stats.txt"

# Step 8: Generate report
echo "=== Generating Report ==="
python3 utils/generate_report.py \
  --input "$RESULTS_DIR" \
  --output "$RESULTS_DIR/reports/index.html"

echo "✅ Complete! Results in: $RESULTS_DIR"
```

---

## Reporting & Visualization

### 11.1 Automated Report Generation

The performance testing suite now includes a **fully automated HTML report generator** that creates comprehensive, visually rich reports with charts and recommendations.

**Features:**
- ✅ Automatic parsing of `hey` output files
- ✅ SLO compliance evaluation with visual indicators
- ✅ Interactive charts using Chart.js
- ✅ Performance recommendations based on test results
- ✅ System metrics visualization
- ✅ Baseline comparison (when available)
- ✅ Mobile-responsive design

**Report structure:**
```
reports/
├── performance_report_medium_20251009_143022.html  # Complete HTML report
└── performance_report_heavy_20251009_150133.html   # Multiple reports
```

**Using the Report Generator:**

```bash
# Manual report generation
python3 tests/performance/utils/report_generator.py \
  --results-dir tests/performance/results_medium_20251009_143022 \
  --output reports/my_report.html \
  --config config.yaml \
  --profile medium

# Automatic generation (integrated with run-configurable.sh)
./tests/performance/run-configurable.sh -p medium
# Report automatically generated and opened in browser
```

**Report Sections:**

1. **Executive Summary**
   - Overall status indicator
   - SLO compliance percentage
   - Average throughput
   - Average latency (p95, p99)
   - Regression detection alerts

2. **SLO Compliance Table**
   - Detailed comparison of actual vs. target metrics
   - Pass/fail indicators
   - Margin calculations

3. **Test Results by Category**
   - Tools, resources, prompts performance
   - Interactive bar charts showing p50/p95/p99
   - Baseline comparison indicators
   - Error rate tracking

4. **System Metrics** (when monitoring enabled)
   - CPU usage over time
   - Memory usage over time
   - Peak resource utilization

5. **Database Performance** (when available)
   - Connection pool statistics
   - Query performance
   - Slow query identification

6. **Automated Recommendations**
   - Priority-based (high/medium/low)
   - Specific actions to improve performance
   - Code snippets for investigation

**Example Report Output:**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Performance Test Report - 2025-10-09 14:30:22</title>
    <!-- Embedded Chart.js for visualizations -->
    <!-- Responsive CSS styling -->
</head>
<body>
    <!-- Executive Summary with metric cards -->
    <!-- SLO compliance with color-coded badges -->
    <!-- Interactive charts for each category -->
    <!-- Recommendations with actionable steps -->
</body>
</html>
```

The report is fully self-contained (single HTML file) and can be:
- Viewed locally in any browser
- Shared with team members via email
- Archived for historical comparison
- Published to GitHub Pages or internal dashboards

### 11.2 Visualization with Grafana

**Dashboard JSON:**
```json
{
  "dashboard": {
    "title": "ContextForge Performance",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Request Latency (p95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
          }
        ]
      },
      {
        "title": "Database Connections",
        "targets": [
          {
            "expr": "database_connections_active"
          }
        ]
      }
    ]
  }
}
```

### 11.3 Metrics Export

**Export to CSV:**
```python
# utils/export_metrics.py
import csv

def export_to_csv(results, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp', 'Test', 'RPS', 'p50', 'p95', 'p99', 'Errors'])

        for test in results:
            writer.writerow([
                test['timestamp'],
                test['name'],
                test['rps'],
                test['p50'],
                test['p95'],
                test['p99'],
                test['errors']
            ])
```

**Export to JSON:**
```bash
# In test runner
cat > results/metrics_${TIMESTAMP}.json <<EOF
{
  "timestamp": "$(date -Iseconds)",
  "profile": "$PROFILE",
  "tests": [
    {
      "name": "tools/list",
      "rps": $(grep "Requests/sec" results/tools_list_*.txt | awk '{print $2}'),
      "p95": ...
    }
  ]
}
EOF
```

---

## Server Profile Testing

### Infrastructure Configuration Testing

Performance varies significantly based on infrastructure configuration. The suite supports testing different server profiles to find optimal settings.

### 12.1 Server Profiles

**Server profiles** define different gateway configurations to test:

```yaml
server_profiles:
  minimal:
    description: "Minimal resources for small deployments"
    gunicorn_workers: 1
    gunicorn_threads: 2
    db_pool_size: 5
    db_pool_max_overflow: 10
    redis_pool_size: 5

  standard:
    description: "Standard production configuration"
    gunicorn_workers: 4
    gunicorn_threads: 4
    db_pool_size: 20
    db_pool_max_overflow: 40
    redis_pool_size: 10

  optimized:
    description: "CPU-optimized for high throughput"
    gunicorn_workers: 8
    gunicorn_threads: 2
    db_pool_size: 30
    db_pool_max_overflow: 60
    redis_pool_size: 20

  memory_optimized:
    description: "Memory-optimized for concurrent connections"
    gunicorn_workers: 4
    gunicorn_threads: 8
    db_pool_size: 40
    db_pool_max_overflow: 80
    redis_pool_size: 25
```

**Configuration Parameters:**

- **gunicorn_workers** - Number of worker processes (recommendation: 2-4 × CPU cores)
- **gunicorn_threads** - Threads per worker (2-4 for I/O bound apps)
- **db_pool_size** - Database connection pool size
- **db_pool_max_overflow** - Additional connections when pool is full
- **redis_pool_size** - Redis connection pool size

### 12.2 Horizontal Scaling Tests

Test performance with multiple gateway instances:

```yaml
scaling_tests:
  single_instance:
    instances: 1
    load_balancer: false

  dual_instance:
    instances: 2
    load_balancer: true
    lb_algorithm: round_robin

  quad_instance:
    instances: 4
    load_balancer: true
    lb_algorithm: least_connections

  auto_scale:
    min_instances: 2
    max_instances: 8
    scale_up_threshold: 70  # CPU %
    scale_down_threshold: 30
```

**Test Scenarios:**
1. Measure throughput with 1, 2, 4, 8 instances
2. Validate linear scaling (2x instances ≈ 2x throughput)
3. Test load balancer overhead
4. Verify session affinity (if needed)
5. Test failover when instance goes down

### 12.3 Database Version Comparison

Compare performance across PostgreSQL versions:

```yaml
database_tests:
  postgres_15:
    image: "postgres:15-alpine"
    config_overrides:
      shared_buffers: "256MB"
      effective_cache_size: "1GB"

  postgres_16:
    image: "postgres:16-alpine"
    config_overrides:
      shared_buffers: "256MB"
      effective_cache_size: "1GB"

  postgres_17:
    image: "postgres:17-alpine"
    config_overrides:
      shared_buffers: "256MB"
      effective_cache_size: "1GB"
```

**Test Process:**
1. Run baseline tests with PostgreSQL 15
2. Switch to PostgreSQL 16, migrate schema
3. Run same tests, compare results
4. Switch to PostgreSQL 17, migrate schema
5. Run tests, generate comparison report

**Metrics to Compare:**
- Query execution time
- Connection pool efficiency
- Index performance
- Write throughput
- Read throughput
- Vacuum performance

### 12.4 Configuration Matrix Testing

Test combinations of configurations to find optimal setup:

```yaml
configuration_matrix:
  variables:
    - name: workers
      values: [2, 4, 6, 8]

    - name: threads
      values: [2, 4, 8]

    - name: db_pool_size
      values: [10, 20, 30, 40]

    - name: postgres_version
      values: ["15", "16", "17"]

  # Full factorial: 4 × 3 × 4 × 3 = 144 tests
  # Reduced matrix using Latin hypercube sampling
  strategy: latin_hypercube
  sample_size: 20  # Test 20 representative combinations
```

**Matrix Testing Strategies:**

1. **Full Factorial** - Test all combinations (exhaustive but time-consuming)
2. **One-Factor-at-a-Time** - Vary one parameter while keeping others constant
3. **Latin Hypercube Sampling** - Statistical sampling for representative coverage
4. **Taguchi Method** - Orthogonal array for efficient parameter optimization

### 12.5 Comparison Reporting

**Automated Comparison Reports:**

```bash
# Compare two server profiles
./run-configurable.sh -p medium --server-profile minimal --baseline
./run-configurable.sh -p medium --server-profile optimized --compare-with baseline

# Output: Side-by-side comparison
# - Throughput difference: +125% (minimal: 400 rps → optimized: 900 rps)
# - Latency improvement: -35% (minimal: 45ms → optimized: 29ms)
# - Resource usage: CPU +50%, Memory +30%
```

**Comparison Metrics:**

| Configuration | Throughput | p95 Latency | CPU Usage | Memory Usage | Cost Score |
|---------------|------------|-------------|-----------|--------------|------------|
| Minimal       | 400 rps    | 45ms        | 25%       | 512MB        | 1.0x       |
| Standard      | 750 rps    | 32ms        | 45%       | 1.2GB        | 2.5x       |
| Optimized     | 900 rps    | 29ms        | 75%       | 2.0GB        | 4.0x       |

**Cost-Benefit Analysis:**
- Calculate cost per request
- Determine optimal configuration for budget
- Identify diminishing returns (where adding resources doesn't improve perf)

### 12.6 Dynamic Configuration Testing

Test runtime configuration changes:

```yaml
dynamic_tests:
  connection_pool_sizing:
    description: "Test different pool sizes without restart"
    start_pool_size: 10
    end_pool_size: 50
    step: 5
    requests_per_step: 5000

  worker_scaling:
    description: "Test adding/removing workers"
    initial_workers: 2
    scale_to: 8
    requests_per_level: 10000
```

### 12.7 Infrastructure Profiles

**Complete infrastructure configurations:**

```yaml
infrastructure_profiles:
  development:
    gateway_instances: 1
    gunicorn_workers: 2
    postgres_version: "17"
    redis_enabled: false
    postgres_shared_buffers: "128MB"

  staging:
    gateway_instances: 2
    gunicorn_workers: 4
    postgres_version: "17"
    redis_enabled: true
    postgres_shared_buffers: "512MB"
    postgres_max_connections: 100

  production:
    gateway_instances: 4
    gunicorn_workers: 8
    postgres_version: "17"
    redis_enabled: true
    redis_maxmemory: "1gb"
    postgres_shared_buffers: "2GB"
    postgres_max_connections: 200
    postgres_effective_cache_size: "6GB"

  production_high_availability:
    gateway_instances: 6
    gunicorn_workers: 8
    postgres_version: "17"
    postgres_replication: true
    postgres_replicas: 2
    redis_enabled: true
    redis_sentinel: true
    redis_replicas: 2
```

### 12.8 Automated Infrastructure Switching

**Test runner with infrastructure swapping:**

```bash
# Test with different infrastructure profiles
./run-configurable.sh -p heavy \
  --infrastructure development \
  --output dev_results.json

./run-configurable.sh -p heavy \
  --infrastructure staging \
  --output staging_results.json

./run-configurable.sh -p heavy \
  --infrastructure production \
  --output prod_results.json

# Generate comparison report
./utils/compare_infrastructure.py \
  dev_results.json \
  staging_results.json \
  prod_results.json \
  --output infrastructure_comparison.html
```

**Infrastructure Switching Process:**
1. Save current docker-compose configuration
2. Generate new docker-compose from infrastructure profile
3. Stop current services
4. Start services with new configuration
5. Wait for health checks
6. Run performance tests
7. Collect results
8. Restore original configuration (optional)

### 12.9 Database Tuning Tests

**PostgreSQL configuration variants:**

```yaml
postgres_tuning_profiles:
  default:
    # PostgreSQL defaults
    shared_buffers: "128MB"
    effective_cache_size: "4GB"
    maintenance_work_mem: "64MB"
    checkpoint_completion_target: 0.9
    wal_buffers: "16MB"
    default_statistics_target: 100
    random_page_cost: 4.0
    effective_io_concurrency: 1
    work_mem: "4MB"
    min_wal_size: "80MB"
    max_wal_size: "1GB"

  tuned_oltp:
    # Optimized for Online Transaction Processing
    shared_buffers: "2GB"
    effective_cache_size: "6GB"
    maintenance_work_mem: "512MB"
    checkpoint_completion_target: 0.9
    wal_buffers: "16MB"
    default_statistics_target: 100
    random_page_cost: 1.1  # SSD optimized
    effective_io_concurrency: 200
    work_mem: "10MB"
    min_wal_size: "1GB"
    max_wal_size: "4GB"

  tuned_analytics:
    # Optimized for analytical queries
    shared_buffers: "4GB"
    effective_cache_size: "12GB"
    maintenance_work_mem: "2GB"
    work_mem: "50MB"
    max_parallel_workers_per_gather: 4
    max_parallel_workers: 8
```

### 12.10 Test Execution Workflow

**Step-by-step automated testing:**

```mermaid
graph TD
    A[Start] --> B[Load Config]
    B --> C[For Each Infrastructure Profile]
    C --> D[Generate docker-compose]
    D --> E[Stop Services]
    E --> F[Start Services with New Config]
    F --> G[Wait for Health]
    G --> H[For Each Server Profile]
    H --> I[Update Env Variables]
    I --> J[Restart Gateway]
    J --> K[Run Performance Tests]
    K --> L[Collect Metrics]
    L --> M{More Server Profiles?}
    M -->|Yes| H
    M -->|No| N{More Infrastructure?}
    N -->|Yes| C
    N -->|No| O[Generate Comparison Report]
    O --> P[End]
```

## Automated Test Runner

### Configuration-Driven Testing

The suite now includes a **configurable test runner** that reads all settings from `config.yaml`:

**Configuration File (`config.yaml`):**
```yaml
# Test profiles with different load levels
profiles:
  smoke:    # Quick validation
    requests: 100
    concurrency: 5

  medium:   # Realistic load
    requests: 10000
    concurrency: 50

  heavy:    # Stress testing
    requests: 50000
    concurrency: 200

# Test scenarios (what to test)
scenarios:
  tools_benchmark:
    enabled: true
    tests:
      - name: "list_tools"
        payload: "payloads/tools/list_tools.json"
        endpoint: "/rpc"

# SLO definitions
slos:
  tools_list:
    p95_ms: 30
    min_rps: 500
    max_error_rate: 0.001

# Monitoring settings
monitoring:
  enabled: true
  interval_seconds: 5

# Reporting settings
reporting:
  enabled: true
  include_charts: true
```

**Running Tests:**

```bash
# Run with default configuration (medium profile)
./tests/performance/run-configurable.sh

# Run specific profile
./tests/performance/run-configurable.sh -p heavy

# Run with custom config
./tests/performance/run-configurable.sh -c my-config.yaml -p light

# Run only specific scenario
./tests/performance/run-configurable.sh --scenario tools_benchmark

# Quick run without extras
./tests/performance/run-configurable.sh -p smoke --skip-monitoring --skip-report

# List available scenarios
./tests/performance/run-configurable.sh --list-scenarios
```

**What the Runner Does:**

1. ✅ **Service Health Check** - Validates gateway and MCP servers are ready
2. ✅ **Authentication Setup** - Generates JWT tokens automatically
3. ✅ **System Monitoring** - Collects CPU, memory, Docker stats during tests
4. ✅ **Warmup Phase** - Sends warmup requests to prime caches
5. ✅ **Test Execution** - Runs all configured scenarios
6. ✅ **Metrics Collection** - Gathers Prometheus metrics and logs
7. ✅ **Report Generation** - Creates HTML report and opens in browser
8. ✅ **Cleanup** - Stops monitoring, saves all artifacts

**Output Structure:**
```
results_medium_20251009_143022/
├── tools_benchmark_list_tools_medium_20251009_143022.txt
├── tools_benchmark_get_system_time_medium_20251009_143022.txt
├── resources_benchmark_list_resources_medium_20251009_143022.txt
├── system_metrics.csv
├── docker_stats.csv
├── prometheus_metrics.txt
└── gateway_logs.txt

reports/
└── performance_report_medium_20251009_143022.html
```

## Implementation Checklist

- [x] **Phase 1: Setup**
  - [x] Install all required tools (hey, py-spy, etc.)
  - [x] Create configurable test runner with YAML config
  - [x] Create HTML report generator with charts
  - [ ] Create performance test environment (docker-compose.perf.yml)
  - [ ] Document baseline system specs

- [ ] **Phase 2: Individual Component Tests**
  - [ ] Test fast-time-server standalone
  - [ ] Test gateway core (no MCP servers)
  - [ ] Test database in isolation

- [ ] **Phase 3: Integration Tests**
  - [ ] Test gateway + single MCP server
  - [ ] Test gateway + multiple MCP servers
  - [ ] Test gateway federation

- [ ] **Phase 4: Monitoring & Profiling**
  - [x] Implement monitoring scripts (in run-configurable.sh)
  - [ ] Add profiling middleware
  - [ ] Set up database query logging

- [ ] **Phase 5: Optimization**
  - [ ] Optimize connection pooling
  - [ ] Add missing database indexes
  - [ ] Optimize slow queries

- [ ] **Phase 6: Automation**
  - [x] Create configurable test automation
  - [x] Generate automated HTML reports with charts
  - [ ] Create CI/CD workflow
  - [ ] Set up baseline comparison
  - [x] Implement SLO validation in reports

- [ ] **Phase 7: Continuous Improvement**
  - [x] Establish SLOs in config.yaml
  - [ ] Create performance dashboard (Grafana)
  - [ ] Schedule weekly performance tests

- [ ] **Phase 8: Server Profile & Infrastructure Testing** (NEW)
  - [ ] Implement server profile switching (Gunicorn workers, threads, pool sizes)
  - [ ] Implement infrastructure profile switching (Docker Compose generation)
  - [ ] Add PostgreSQL version comparison (15 vs 16 vs 17)
  - [ ] Add horizontal scaling tests (1, 2, 4, 8 instances)
  - [ ] Create configuration matrix testing
  - [ ] Build infrastructure comparison report generator
  - [ ] Add cost-benefit analysis to reports
  - [ ] Implement automated Docker Compose templating
  - [ ] Create database tuning profile tests
  - [ ] Add dynamic configuration testing (runtime changes)

---

## References & Resources

### Documentation
- [hey Documentation](https://github.com/rakyll/hey)
- [py-spy Documentation](https://github.com/benfred/py-spy)
- [PostgreSQL Performance Tips](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [SQLAlchemy Performance](https://docs.sqlalchemy.org/en/20/faq/performance.html)

### Tools
- [Grafana](https://grafana.com/)
- [Prometheus](https://prometheus.io/)
- [Locust](https://locust.io/)
- [k6](https://k6.io/)

### Best Practices
- [Google SRE Book - Performance](https://sre.google/sre-book/table-of-contents/)
- [Database Performance for Developers](https://use-the-index-luke.com/)

---

**Next Steps:**
1. Review and approve this strategy
2. Prioritize implementation phases
3. Allocate resources for performance testing infrastructure
4. Begin Phase 1 implementation

**Document Owner:** Performance Engineering Team
**Review Cycle:** Quarterly
**Last Review:** 2025-10-09
