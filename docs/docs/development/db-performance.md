# Database Performance Observability Guide

This guide covers how to measure, debug, and optimize database query performance in MCP Gateway.

## Quick Start

### Recommended: Query Logging to File (Best for N+1 Detection)

The most effective way to find N+1 issues is to log queries grouped by HTTP request:

```bash
# Terminal 1: Start server with query logging
make dev-query-log

# Terminal 2: Watch the query log in real-time
make query-log-tail

# After making some requests, analyze the log
make query-log-analyze

# Clear logs when done
make query-log-clear
```

This creates two log files:
- `logs/db-queries.log` - Human-readable text with N+1 warnings
- `logs/db-queries.jsonl` - JSON Lines for tooling/analysis

### Example Output

```
================================================================================
[2025-01-15T10:30:00Z] GET /tools
User: admin | Correlation-ID: abc123 | Queries: 52 | Total: 45.2ms
================================================================================

⚠️  POTENTIAL N+1 QUERIES DETECTED:
   • 50x similar queries on 'gateways'
     Pattern: SELECT * FROM gateways WHERE id = ?...

    1. [  2.1ms] SELECT * FROM tools WHERE enabled = 1
    2. [  0.8ms] SELECT * FROM gateways WHERE id = ?  ← N+1
    3. [  0.9ms] SELECT * FROM gateways WHERE id = ?  ← N+1
  ...
--------------------------------------------------------------------------------
⚠️  1 potential N+1 pattern(s) detected - see docs/docs/development/db-performance.md
Total: 52 queries, 45.2ms
================================================================================
```

### Alternative: SQLAlchemy Echo Mode (Stdout)

For quick debugging, log all queries to stdout:

```bash
# Dedicated target
make dev-echo

# Or manually
SQLALCHEMY_ECHO=true make dev
```

### Run Performance Tests

```bash
# Run N+1 detection tests
make test-db-perf

# Run with full SQL output
make test-db-perf-verbose
```

---

## Query Logging Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_QUERY_LOG_ENABLED` | `false` | Enable query logging to file |
| `DB_QUERY_LOG_FILE` | `logs/db-queries.log` | Text log file path |
| `DB_QUERY_LOG_JSON_FILE` | `logs/db-queries.jsonl` | JSON log file path |
| `DB_QUERY_LOG_FORMAT` | `both` | Format: `json`, `text`, or `both` |
| `DB_QUERY_LOG_MIN_QUERIES` | `1` | Only log requests with >= N queries |
| `DB_QUERY_LOG_DETECT_N1` | `true` | Auto-detect N+1 patterns |
| `DB_QUERY_LOG_N1_THRESHOLD` | `3` | Min similar queries to flag as N+1 |
| `DB_QUERY_LOG_INCLUDE_PARAMS` | `false` | Include query parameters (security risk) |

### Analyzing Logs

Run the analysis script to get a summary:

```bash
make query-log-analyze
```

Output:
```
================================================================================
DATABASE QUERY LOG ANALYSIS
================================================================================

📊 SUMMARY
   Total requests analyzed: 150
   Total queries executed:  2847
   Avg queries per request: 19.0
   Requests with N+1:       23 (15.3%)

⚠️  N+1 ISSUES DETECTED
   23 requests have potential N+1 query patterns

🔴 TOP N+1 PATTERNS
    156x  gateways: SELECT * FROM gateways WHERE id = ?...
     45x  servers: SELECT * FROM servers WHERE tool_id = ?...

📈 ENDPOINTS BY QUERY COUNT (top 15)
   Endpoint                                   Reqs  Queries    Avg   Max  N+1
   ---------------------------------------------------------------------------
   GET /tools                                   45     2250   50.0    52  ⚠️23
   GET /admin/tools                             30      450   15.0    18    0
   ...
================================================================================
```

---

## Query Counting: Detect N+1 Issues

### 1. SQLAlchemy Event-Based Counter

Create a context manager to count queries in a code block:

```python
# tests/helpers/query_counter.py
from contextlib import contextmanager
from sqlalchemy import event
from sqlalchemy.engine import Engine
import threading

class QueryCounter:
    """Thread-safe SQL query counter using SQLAlchemy events."""

    def __init__(self):
        self.count = 0
        self.queries = []
        self._lock = threading.Lock()

    def _before_execute(self, conn, cursor, statement, parameters, context, executemany):
        with self._lock:
            self.count += 1
            self.queries.append({
                'statement': statement,
                'parameters': parameters,
                'executemany': executemany
            })

    def reset(self):
        with self._lock:
            self.count = 0
            self.queries = []

@contextmanager
def count_queries(engine: Engine, print_queries: bool = False):
    """Context manager to count SQL queries.

    Usage:
        with count_queries(engine) as counter:
            # ... code that runs queries ...
        print(f"Executed {counter.count} queries")

    Args:
        engine: SQLAlchemy engine
        print_queries: If True, print each query as it's executed

    Yields:
        QueryCounter: Counter object with .count and .queries attributes
    """
    counter = QueryCounter()

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        counter._before_execute(conn, cursor, statement, parameters, context, executemany)
        if print_queries:
            print(f"[Query #{counter.count}] {statement[:200]}...")

    event.listen(engine, "before_cursor_execute", before_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
```

### 2. Pytest Fixture for Query Counting

```python
# tests/conftest.py (add to existing)
import pytest
from tests.helpers.query_counter import count_queries

@pytest.fixture
def query_counter(db_engine):
    """Fixture to count database queries in tests.

    Usage:
        def test_something(query_counter, db_session):
            with query_counter() as counter:
                # do database operations
            assert counter.count <= 5, f"Too many queries: {counter.count}"
    """
    def _counter(print_queries=False):
        return count_queries(db_engine, print_queries=print_queries)
    return _counter

@pytest.fixture
def assert_max_queries(db_engine):
    """Fixture to assert maximum query count.

    Usage:
        def test_list_tools(assert_max_queries, db_session):
            with assert_max_queries(5):
                tools = tool_service.list_tools(db_session)
    """
    @contextmanager
    def _assert_max(max_count: int, message: str = None):
        with count_queries(db_engine) as counter:
            yield counter
        if counter.count > max_count:
            query_list = "\n".join(
                f"  {i+1}. {q['statement'][:100]}..."
                for i, q in enumerate(counter.queries)
            )
            msg = message or f"Expected at most {max_count} queries, got {counter.count}"
            raise AssertionError(f"{msg}\n\nQueries executed:\n{query_list}")
    return _assert_max
```

---

## N+1 Query Detection Patterns

### What is N+1?

```python
# BAD: N+1 pattern - 1 query for tools + N queries for each tool's gateway
tools = db.query(Tool).all()  # 1 query
for tool in tools:
    print(tool.gateway.name)  # N queries (one per tool!)

# GOOD: Eager loading - just 1-2 queries
from sqlalchemy.orm import joinedload
tools = db.query(Tool).options(joinedload(Tool.gateway)).all()
for tool in tools:
    print(tool.gateway.name)  # No additional queries
```

### Common Fixes

**1. Use `joinedload` for single relationships:**
```python
from sqlalchemy.orm import joinedload

# Before: N+1
tools = db.query(Tool).all()

# After: Single query with JOIN
tools = db.query(Tool).options(joinedload(Tool.gateway)).all()
```

**2. Use `selectinload` for collections:**
```python
from sqlalchemy.orm import selectinload

# Before: N+1
servers = db.query(Server).all()
for server in servers:
    for tool in server.tools:  # N additional queries!
        print(tool.name)

# After: 2 queries (servers + all tools)
servers = db.query(Server).options(selectinload(Server.tools)).all()
```

**3. Use `contains_eager` with explicit joins:**
```python
from sqlalchemy.orm import contains_eager

tools = (
    db.query(Tool)
    .join(Tool.gateway)
    .options(contains_eager(Tool.gateway))
    .filter(Gateway.status == 'active')
    .all()
)
```

---

## Performance Test Harness

### Test File Structure

```
tests/
├── performance/
│   ├── __init__.py
│   ├── conftest.py           # Performance-specific fixtures
│   ├── test_n_plus_one.py    # N+1 detection tests
│   ├── test_query_counts.py  # Query count regression tests
│   └── benchmarks/
│       ├── test_tool_service.py
│       └── test_server_service.py
```

### Performance Test Fixtures

```python
# tests/performance/conftest.py
import pytest
from sqlalchemy import event
import time

@pytest.fixture
def performance_db(db_session, db_engine):
    """Database session with performance instrumentation."""
    queries = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info['query_start'] = time.perf_counter()

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        duration = (time.perf_counter() - conn.info.get('query_start', 0)) * 1000
        queries.append({
            'statement': statement,
            'duration_ms': duration,
            'parameters': parameters,
        })

    event.listen(db_engine, "before_cursor_execute", before_execute)
    event.listen(db_engine, "after_cursor_execute", after_execute)

    class PerfSession:
        session = db_session
        executed_queries = queries

        @property
        def query_count(self):
            return len(queries)

        @property
        def total_query_time_ms(self):
            return sum(q['duration_ms'] for q in queries)

        def get_slow_queries(self, threshold_ms=10):
            return [q for q in queries if q['duration_ms'] > threshold_ms]

        def print_summary(self):
            print(f"\n{'='*60}")
            print(f"Query Summary: {self.query_count} queries, {self.total_query_time_ms:.2f}ms total")
            print(f"{'='*60}")
            for i, q in enumerate(queries, 1):
                print(f"{i}. [{q['duration_ms']:.2f}ms] {q['statement'][:80]}...")

    yield PerfSession()

    event.remove(db_engine, "before_cursor_execute", before_execute)
    event.remove(db_engine, "after_cursor_execute", after_execute)


@pytest.fixture
def seed_performance_data(db_session):
    """Seed database with realistic data volumes for performance testing."""
    from mcpgateway.db import Gateway, Tool, Resource, Prompt

    # Create gateways
    gateways = []
    for i in range(10):
        gw = Gateway(
            name=f"gateway-{i}",
            url=f"http://gateway-{i}.local:8000",
            status="active"
        )
        db_session.add(gw)
        gateways.append(gw)
    db_session.flush()

    # Create tools (100 per gateway = 1000 total)
    for gw in gateways:
        for j in range(100):
            tool = Tool(
                name=f"tool-{gw.id}-{j}",
                description=f"Test tool {j}",
                gateway_id=gw.id,
                input_schema={"type": "object"}
            )
            db_session.add(tool)

    db_session.commit()
    return {"gateways": 10, "tools": 1000}
```

### N+1 Detection Tests

```python
# tests/performance/test_n_plus_one.py
import pytest
from mcpgateway.services.tool_service import ToolService

class TestN1Detection:
    """Tests to detect and prevent N+1 query patterns."""

    def test_list_tools_no_n_plus_one(self, performance_db, seed_performance_data):
        """Listing tools should not cause N+1 queries for gateways."""
        service = ToolService()

        # List all tools
        tools = service.list_tools(performance_db.session)

        # Access gateway for each tool (this would trigger N+1 if not eager loaded)
        for tool in tools:
            _ = tool.gateway.name if tool.gateway else None

        performance_db.print_summary()

        # Should be ~2-3 queries max, not 1000+
        assert performance_db.query_count < 10, (
            f"Potential N+1: {performance_db.query_count} queries for {len(tools)} tools"
        )

    def test_get_tool_with_relations(self, performance_db, seed_performance_data):
        """Getting a single tool should load relations efficiently."""
        service = ToolService()

        tool = service.get_tool(performance_db.session, tool_id="tool-1-0")

        # Access related objects
        _ = tool.gateway
        _ = tool.servers

        # Should be 1-3 queries, not more
        assert performance_db.query_count <= 3


class TestQueryCountRegression:
    """Regression tests for query counts."""

    QUERY_BUDGETS = {
        'list_tools': 5,
        'list_gateways': 3,
        'list_servers': 5,
        'get_tool_detail': 3,
    }

    def test_list_tools_query_budget(self, assert_max_queries, db_session):
        """Tool listing should stay within query budget."""
        from mcpgateway.services.tool_service import ToolService

        with assert_max_queries(self.QUERY_BUDGETS['list_tools']):
            ToolService().list_tools(db_session)

    def test_list_gateways_query_budget(self, assert_max_queries, db_session):
        """Gateway listing should stay within query budget."""
        from mcpgateway.services.gateway_service import GatewayService

        with assert_max_queries(self.QUERY_BUDGETS['list_gateways']):
            GatewayService().list_gateways(db_session)
```

---

## Real-Time Query Monitoring

### Logging Middleware

```python
# mcpgateway/middleware/query_logging.py
import logging
import time
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import event

logger = logging.getLogger(__name__)

# Context var to track queries per request
request_queries: ContextVar[list] = ContextVar('request_queries', default=[])

class QueryLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log query counts and timing per request."""

    async def dispatch(self, request, call_next):
        queries = []
        request_queries.set(queries)

        start_time = time.perf_counter()
        response = await call_next(request)
        total_time = (time.perf_counter() - start_time) * 1000

        query_count = len(queries)
        query_time = sum(q.get('duration_ms', 0) for q in queries)

        # Log warning for high query counts
        if query_count > 20:
            logger.warning(
                f"HIGH QUERY COUNT: {request.method} {request.url.path} "
                f"- {query_count} queries in {query_time:.2f}ms "
                f"(total: {total_time:.2f}ms)"
            )
        elif query_count > 10:
            logger.info(
                f"Query summary: {request.method} {request.url.path} "
                f"- {query_count} queries in {query_time:.2f}ms"
            )

        # Add query info to response headers (development only)
        response.headers['X-Query-Count'] = str(query_count)
        response.headers['X-Query-Time-Ms'] = f"{query_time:.2f}"

        return response


def setup_query_tracking(engine):
    """Setup event listeners to track queries per request."""

    @event.listens_for(engine, "before_cursor_execute")
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info['query_start'] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after_execute(conn, cursor, statement, parameters, context, executemany):
        duration = (time.perf_counter() - conn.info.get('query_start', 0)) * 1000
        try:
            queries = request_queries.get()
            queries.append({
                'statement': statement,
                'duration_ms': duration,
            })
        except LookupError:
            pass  # No request context
```

---

## Configuration Options Summary

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `OBSERVABILITY_ENABLED` | `false` | Enable query span tracking |
| `LOG_LEVEL` | `ERROR` | Set to `DEBUG` for verbose query logs |
| `SQLALCHEMY_ECHO` | `false` | Print all SQL to stdout (development) |
| `DB_POOL_SIZE` | `200` | Connection pool size |
| `PERFORMANCE_THRESHOLD_DATABASE_QUERY_MS` | `100` | Slow query threshold (ms) |

---

## Debugging Workflow

### 1. Quick Investigation
```bash
# Start server with SQL logging (recommended)
make dev-echo

# Or manually:
SQLALCHEMY_ECHO=true make dev
```

### 2. Run Database Performance Tests
```bash
# Run N+1 detection tests
make test-db-perf

# Run with full SQL query output
make test-db-perf-verbose

# Run specific test file
uv run pytest tests/performance/test_db_query_patterns.py -v -s
```

### 3. Count Queries for Specific Endpoint
```python
# In a test or debug script
from tests.helpers.query_counter import count_queries
from mcpgateway.db import engine, SessionLocal

with count_queries(engine, print_queries=True) as counter:
    db = SessionLocal()
    # Your code here
    db.close()

print(f"\nTotal: {counter.count} queries")
```

### 4. Identify N+1 in Production Logs
```bash
# Look for high query counts
grep "HIGH QUERY COUNT" logs/mcpgateway.log

# Parse query patterns
grep "SELECT.*FROM tools" logs/mcpgateway.log | sort | uniq -c | sort -rn
```

---

## Issue #1609 Checklist

Use this checklist when investigating N+1 patterns:

- [ ] Enable query logging (`SQLALCHEMY_ECHO=true` or observability)
- [ ] Identify endpoints with high query counts
- [ ] Check for missing `joinedload`/`selectinload` in queries
- [ ] Add performance tests with query budgets
- [ ] Verify fixes don't regress other endpoints
- [ ] Update query budgets in `QUERY_BUDGETS` dict

---

## Files to Check for N+1

Priority files based on typical N+1 patterns:

1. `mcpgateway/services/tool_service.py` - Tool listing with gateway relations
2. `mcpgateway/services/server_service.py` - Server with tool collections
3. `mcpgateway/services/gateway_service.py` - Gateway with tool/resource counts
4. `mcpgateway/services/resource_service.py` - Resources with content
5. `mcpgateway/admin.py` - Admin UI endpoints loading multiple relations

---

## Related Documentation

- [SQLAlchemy Eager Loading](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html#relationship-loading-techniques)
- [Existing Instrumentation](../mcpgateway/instrumentation/sqlalchemy.py)
- [Performance Strategy](../tests/performance/PERFORMANCE_STRATEGY.md)
