# Performance Profiling Guide

This guide covers tools and techniques for profiling MCP Gateway performance under load. Use these methods to identify bottlenecks, optimize queries, and diagnose production issues.

---

## Quick Reference

| Tool | Purpose | When to Use |
|------|---------|-------------|
| **Locust** | Load testing | Simulate concurrent users |
| **PostgreSQL EXPLAIN** | Query analysis | Find slow/inefficient queries |
| **pg_stat_activity** | Connection monitoring | Debug idle transactions |
| **pg_stat_user_tables** | Table scan stats | Find full table scans |
| **py-spy** | Python profiling | Find CPU hotspots |
| **docker stats** | Resource monitoring | Track CPU/memory usage |
| **Redis CLI** | Cache analysis | Check hit rates |

---

## Load Testing with Locust

### Starting a Load Test

```bash
# Start Locust web UI
make load-test-ui

# Open browser to http://localhost:8089
# Configure users (e.g., 3000) and spawn rate (e.g., 100/s)
```

### Monitoring Locust Stats via API

```bash
# Get current stats as JSON
curl -s http://localhost:8089/stats/requests | python3 -c "
import sys, json
data = json.load(sys.stdin)

print('=== TOP SLOWEST ENDPOINTS ===')
stats = sorted(data.get('stats', []), key=lambda x: x.get('avg_response_time', 0), reverse=True)[:10]
print(f\"{'Endpoint':<45} {'Reqs':>8} {'Avg':>8} {'P95':>8} {'P99':>8}\")
print('-' * 85)
for s in stats:
    name = s.get('name', '')[:43]
    p95 = s.get('response_time_percentile_0.95', 0)
    p99 = s.get('response_time_percentile_0.99', 0)
    print(f\"{name:<45} {s.get('num_requests', 0):>8} {s.get('avg_response_time', 0):>8.0f} {p95:>8.0f} {p99:>8.0f}\")

print()
print(f\"RPS: {data.get('total_rps', 0):.1f}, Users: {data.get('user_count', 0)}, Failures: {data.get('total_fail_count', 0)}\")
"
```

### Checking for Errors

```bash
curl -s http://localhost:8089/stats/requests | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('=== ERRORS ===')
for e in data.get('errors', []):
    print(f\"  {e.get('name')}: {e.get('occurrences')} - {e.get('error')[:80]}\")
"
```

---

## PostgreSQL Profiling

### EXPLAIN ANALYZE

Use `EXPLAIN ANALYZE` to understand query execution plans and find slow queries:

```bash
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT COUNT(*), AVG(response_time)
FROM tool_metrics
WHERE timestamp >= NOW() - INTERVAL '7 days';
"
```

**Key metrics to watch:**

| Metric | Good | Bad |
|--------|------|-----|
| `Seq Scan` | On small tables (<1000 rows) | On large tables |
| `Index Scan` | On filtered queries | Missing when expected |
| `Rows Removed by Filter: 0` | Filter matches few rows | Filter matches all rows |
| `Shared Buffers Hit` | High ratio | Low ratio (disk I/O) |

**Example: Detecting Non-Selective Filters**

```
Parallel Seq Scan on tool_metrics
  Filter: (timestamp >= (now() - '7 days'::interval))
  Rows Removed by Filter: 0  <-- ALL rows match = index not useful
```

This indicates the filter matches 100% of rows, so PostgreSQL chooses a sequential scan over an index scan.

### Table Scan Statistics

Monitor which tables are being scanned excessively:

```bash
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
SELECT
    relname as table_name,
    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
    n_live_tup as live_rows,
    seq_scan,
    seq_tup_read,
    idx_scan,
    CASE WHEN seq_scan > 0 THEN seq_tup_read / seq_scan ELSE 0 END as avg_rows_per_seq_scan
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC
LIMIT 15;
"
```

**Warning signs:**

- `seq_tup_read` in billions = excessive full table scans
- `avg_rows_per_seq_scan` equals `live_rows` = scanning entire table each time
- High `seq_scan` count with large tables = missing index or non-selective filter

### Connection State Analysis

Check for idle-in-transaction connections (a sign of long-running requests or connection leaks):

```bash
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
SELECT
    state,
    COUNT(*) as count,
    MAX(EXTRACT(EPOCH FROM (NOW() - state_change)))::int as max_age_seconds
FROM pg_stat_activity
WHERE datname = 'mcp'
GROUP BY state
ORDER BY count DESC;
"
```

**Healthy state:**

```
state               | count | max_age_seconds
--------------------+-------+-----------------
idle                |    70 |             200
active              |     5 |               0
idle in transaction |     3 |               1
```

**Unhealthy state (connection exhaustion risk):**

```
state               | count | max_age_seconds
--------------------+-------+-----------------
idle in transaction |    60 |             120  <-- Problem!
idle                |    38 |             500
active              |     2 |               0
```

### Finding Stuck Queries

```bash
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
SELECT
    pid,
    state,
    EXTRACT(EPOCH FROM (NOW() - state_change))::numeric(8,2) as idle_seconds,
    LEFT(query, 100) as query_snippet
FROM pg_stat_activity
WHERE datname = 'mcp' AND state = 'idle in transaction'
ORDER BY state_change
LIMIT 15;
"
```

### Reset Statistics

To get fresh statistics for a specific test:

```bash
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
SELECT pg_stat_reset();
"
```

---

## Python Profiling with py-spy

[py-spy](https://github.com/benfred/py-spy) is a sampling profiler for Python that can attach to running processes without code changes.

### Installing py-spy

```bash
pip install py-spy

# Or on the host (to profile container processes)
sudo pip install py-spy
```

### Profiling a Running Container

```bash
# Find the Python process ID
docker exec mcp-context-forge-gateway-1 ps aux | grep python

# Run py-spy from host (requires root)
sudo py-spy top --pid $(docker inspect --format '{{.State.Pid}}' mcp-context-forge-gateway-1)

# Generate a flamegraph
sudo py-spy record -o profile.svg --pid $(docker inspect --format '{{.State.Pid}}' mcp-context-forge-gateway-1) --duration 30
```

### Profiling Locally

```bash
# Profile the development server
py-spy top -- python -m mcpgateway

# Generate flamegraph
py-spy record -o flamegraph.svg -- python -m mcpgateway
```

### Interpreting Flamegraphs

- **Wide bars** = functions consuming the most CPU time
- **Deep stacks** = many nested function calls
- **Look for:** Template rendering, JSON serialization, database queries

---

## Container Resource Monitoring

### Real-time Stats

```bash
# Watch all containers
docker stats

# Filter to specific containers
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
  mcp-context-forge-gateway-1 \
  mcp-context-forge-postgres-1 \
  mcp-context-forge-redis-1
```

### Snapshot Stats

```bash
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
  | grep -E "gateway|postgres|redis|nginx"
```

**Healthy resource usage:**

| Container | CPU | Memory |
|-----------|-----|--------|
| gateway (each) | <400% | <4GB |
| postgres | <150% | <1GB |
| redis | <20% | <100MB |

---

## Redis Cache Analysis

### Check Hit Rate

```bash
docker exec mcp-context-forge-redis-1 redis-cli info stats | grep -E "keyspace|ops_per_sec|hits|misses"
```

**Calculate hit rate:**

```bash
docker exec mcp-context-forge-redis-1 redis-cli info stats | python3 -c "
import sys
stats = {}
for line in sys.stdin:
    if ':' in line:
        k, v = line.strip().split(':')
        stats[k] = int(v) if v.isdigit() else v

hits = stats.get('keyspace_hits', 0)
misses = stats.get('keyspace_misses', 0)
total = hits + misses
hit_rate = (hits / total * 100) if total > 0 else 0
print(f'Hits: {hits}, Misses: {misses}, Hit Rate: {hit_rate:.1f}%')
"
```

**Good hit rate:** >90% for cached data

### Check Key Counts

```bash
docker exec mcp-context-forge-redis-1 redis-cli dbsize

# List keys by pattern
docker exec mcp-context-forge-redis-1 redis-cli keys "mcpgw:*" | head -20
```

Tool lookup cache keys (invoke hot path):

```bash
docker exec mcp-context-forge-redis-1 redis-cli keys "mcpgw:tool_lookup:*" | head -20
```

---

## Gateway Log Analysis

### Check for Errors

```bash
docker logs mcp-context-forge-gateway-1 2>&1 | grep -iE "error|exception|timeout|warning" | tail -30
```

### Count Error Types

```bash
docker logs mcp-context-forge-gateway-1 2>&1 | grep -i "error" | \
  sed 's/.*\(Error[^:]*\).*/\1/' | sort | uniq -c | sort -rn | head -10
```

### Check for Idle Transaction Timeouts

```bash
docker logs mcp-context-forge-gateway-1 2>&1 | grep -c "idle transaction timeout"
```

---

## Complete Profiling Session Example

Here's a workflow for diagnosing performance issues under load:

```bash
# 1. Reset PostgreSQL statistics
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "SELECT pg_stat_reset();"

# 2. Start load test
make load-test-ui
# Configure 3000 users in browser, start test

# 3. Take samples every 30 seconds
for i in {1..5}; do
  echo "=== SAMPLE $i ==="

  # Locust stats
  curl -s http://localhost:8089/stats/requests | python3 -c "
import sys, json
d = json.load(sys.stdin)
admin = next((s for s in d.get('stats', []) if s.get('name') == '/admin/'), {})
print(f\"RPS: {d.get('total_rps', 0):.0f}, /admin/ avg: {admin.get('avg_response_time', 0):.0f}ms\")
"

  # Connection states
  docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
    SELECT state, COUNT(*) FROM pg_stat_activity WHERE datname='mcp' GROUP BY state;
  "

  # Container CPU
  docker stats --no-stream --format "{{.Name}}: {{.CPUPerc}}" | grep gateway

  sleep 30
done

# 4. Final analysis
docker exec mcp-context-forge-postgres-1 psql -U postgres -d mcp -c "
SELECT relname, seq_scan, seq_tup_read, idx_scan
FROM pg_stat_user_tables
ORDER BY seq_tup_read DESC LIMIT 10;
"
```

---

## Common Performance Issues

### Issue: High Sequential Scan Count

**Symptom:** `seq_tup_read` in billions

**Causes:**
- Missing index
- Non-selective filter (e.g., 7-day filter matches all recent data)
- Short cache TTL causing repeated queries

**Solutions:**
- Add covering index
- Increase cache TTL
- Add materialized view for aggregations

### Issue: Many Idle-in-Transaction Connections

**Symptom:** 50+ connections in `idle in transaction` state

**Causes:**
- N+1 query patterns
- Long-running requests holding transactions
- Missing connection pool limits

**Solutions:**
- Use batch queries instead of loops
- Set `idle_in_transaction_session_timeout`
- Optimize slow queries

### Issue: Health Check Endpoints Holding PgBouncer Connections

**Symptom:** `SELECT 1` queries stuck in `idle in transaction` state for minutes

```sql
SELECT left(query, 50), count(*), avg(EXTRACT(EPOCH FROM (NOW() - state_change)))::int as avg_age
FROM pg_stat_activity
WHERE state = 'idle in transaction' AND datname = 'mcp'
GROUP BY left(query, 50);

        query         | count | avg_age
----------------------+-------+---------
 SELECT 1             |    45 |     139
```

**Causes:**
- PgBouncer in `transaction` mode holds backend connections until `COMMIT`/`ROLLBACK`
- Health endpoints using `Depends(get_db)` rely on dependency cleanup, which may not execute on timeout/cancellation
- `async def` endpoints calling blocking SQLAlchemy code on event loop thread
- Cross-thread session usage when mixing `asyncio.to_thread` with `Depends(get_db)`

**Solutions:**

1. **Use dedicated sessions instead of `Depends(get_db)`** - Health endpoints should create and manage their own sessions to avoid double-commit and cross-thread issues:

```python
@app.get("/health")
def healthcheck():  # Sync function - FastAPI runs in threadpool
    """Health check with dedicated session."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db.commit()  # Explicitly release PgBouncer connection
        return {"status": "healthy"}
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            try:
                db.invalidate()  # Remove broken connection from pool
            except Exception:
                pass
        return {"status": "unhealthy", "error": str(e)}
    finally:
        db.close()
```

2. **Use sync functions for simple blocking operations** - FastAPI automatically runs `def` (sync) route handlers in a threadpool:

```python
# BAD: async def with blocking calls stalls event loop
@app.get("/health")
async def healthcheck():
    db.execute(text("SELECT 1"))  # Blocks event loop!

# GOOD: sync def runs in threadpool automatically
@app.get("/health")
def healthcheck():
    db.execute(text("SELECT 1"))  # Runs in threadpool
```

3. **For async endpoints, create sessions inside `asyncio.to_thread`** - All DB operations must happen in the same thread:

```python
@app.get("/ready")
async def readiness_check():
    def _check_db() -> str | None:
        # Session created IN the worker thread
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db.commit()
            return None
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                try:
                    db.invalidate()
                except Exception:
                    pass
            return str(e)
        finally:
            db.close()

    error = await asyncio.to_thread(_check_db)
    if error:
        return {"status": "not ready", "error": error}
    return {"status": "ready"}
```

4. **Mirror `get_db` cleanup pattern** - Use rollback → invalidate → close:

```python
except Exception as e:
    try:
        db.rollback()
    except Exception:
        try:
            db.invalidate()  # Remove broken connection from pool
        except Exception:
            pass  # nosec B110 - Best effort cleanup
```

**Why not use `Depends(get_db)`?**

- `get_db` commits after yield, causing double-commit if endpoint commits
- With `asyncio.to_thread`, the session is created in one thread but used in another
- Health endpoints should test actual DB connectivity, not be mockable via `dependency_overrides`

### Issue: High Gateway CPU

**Symptom:** Gateway at 600%+ CPU

**Causes:**
- Template rendering overhead
- JSON serialization of large responses
- Pydantic validation overhead

**Solutions:**
- Enable response caching
- Paginate large result sets
- Use orjson for serialization (enabled by default)

---

## See Also

- [Database Performance Guide](db-performance.md) - N+1 detection and query logging
- [Performance Testing](../testing/performance.md) - Load testing with hey
- [Scaling Guide](../manage/scale.md) - Production scaling configuration
- [Issue #1906](https://github.com/IBM/mcp-context-forge/issues/1906) - Metrics cache optimization
