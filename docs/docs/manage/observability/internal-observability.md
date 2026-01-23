# Internal Observability System

MCP Gateway includes a built-in observability system that provides comprehensive performance monitoring, error tracking, and analytics without requiring external observability platforms. All trace data is stored in your database (SQLite/PostgreSQL/MariaDB) and visualized through the Admin UI.

## Overview

The internal observability system captures detailed performance metrics and traces for:

- **Tools** - Invocation frequency, performance metrics, error rates
- **Prompts** - Rendering frequency, latency percentiles, error tracking
- **Resources** - Fetch frequency, performance metrics, error tracking
- **HTTP Requests** - Complete request/response tracing with timing

Unlike OpenTelemetry (which sends traces to external systems like Phoenix or Jaeger), the internal observability system is self-contained, making it ideal for:

- Development and testing environments
- Organizations that prefer self-hosted solutions
- Scenarios where external observability platforms are not available
- Quick performance analysis without additional infrastructure

## Key Features

### Performance Analytics

- **Latency Percentiles**: p50, p90, p95, p99 metrics for detailed performance analysis
- **Duration Tracking**: Millisecond-precision timing for all operations
- **Throughput Metrics**: Request counts and rates over time
- **Comparative Analysis**: Side-by-side comparison of multiple resources

### Error Tracking

- **Error Rate Monitoring**: Percentage of failed operations with health indicators
- **Error-Prone Analysis**: Identify resources with highest failure rates
- **Status Code Tracking**: HTTP response codes and error messages
- **Root Cause Analysis**: Detailed traces with full context

### Interactive Dashboards

- **Summary Cards**: At-a-glance health status, most used, slowest, and most error-prone resources
- **Performance Charts**: Interactive visualizations using Chart.js
- **Time-Based Filtering**: Analyze performance over custom time ranges
- **Auto-Refresh**: Dashboards update every 60 seconds automatically

### Trace Visualization

- **Gantt Chart Timeline**: Visual representation of span execution order and timing
- **Flame Graphs**: Hierarchical view of nested operations
- **Trace Details**: Complete trace metadata, attributes, and context
- **Span Explorer**: Drill down into individual operations

## Quick Start

### 1. Enable Observability

Add to your `.env` file:

```bash
# Enable internal observability
OBSERVABILITY_ENABLED=true

# Automatically trace HTTP requests
OBSERVABILITY_TRACE_HTTP_REQUESTS=true

# Retention and limits
OBSERVABILITY_TRACE_RETENTION_DAYS=7
OBSERVABILITY_MAX_TRACES=100000

# Trace sampling (1.0 = 100%, 0.1 = 10%)
OBSERVABILITY_SAMPLE_RATE=1.0

# Include paths (JSON array of regex patterns)
OBSERVABILITY_INCLUDE_PATHS=["^/rpc/?$","^/sse$","^/message$","^/mcp(?:/|$)","^/servers/[^/]+/mcp/?$","^/servers/[^/]+/sse$","^/servers/[^/]+/message$","^/a2a(?:/|$)"]

# Exclude paths (JSON array of regex patterns, applied after include patterns)
OBSERVABILITY_EXCLUDE_PATHS=["/health","/healthz","/ready","/metrics","/static/.*"]

# Enable metrics and events
OBSERVABILITY_METRICS_ENABLED=true
OBSERVABILITY_EVENTS_ENABLED=true
```

### 2. Start MCP Gateway

```bash
# With environment variables
export OBSERVABILITY_ENABLED=true
mcpgateway

# Or start development server
make dev
```

### 3. Access Admin UI

Navigate to the Observability section in the Admin UI:

```
http://localhost:4444/admin/observability
```

## Configuration Reference

### Core Settings

| Variable | Description | Default | Options |
|----------|-------------|---------|---------|
| `OBSERVABILITY_ENABLED` | Master switch for internal observability | `false` | `true`, `false` |
| `OBSERVABILITY_TRACE_HTTP_REQUESTS` | Auto-trace HTTP requests | `true` | `true`, `false` |

### Retention & Limits

| Variable | Description | Default | Range |
|----------|-------------|---------|-------|
| `OBSERVABILITY_TRACE_RETENTION_DAYS` | Days to retain trace data | `7` | 1-365 |
| `OBSERVABILITY_MAX_TRACES` | Maximum traces to store | `100000` | 1000+ |

### Sampling & Filtering

| Variable | Description | Default | Range |
|----------|-------------|---------|-------|
| `OBSERVABILITY_SAMPLE_RATE` | Trace sampling rate | `1.0` | 0.0-1.0 |
| `OBSERVABILITY_INCLUDE_PATHS` | Regex patterns to include for tracing | `["^/rpc/?$","^/sse$","^/message$","^/mcp(?:/|$)","^/servers/[^/]+/mcp/?$","^/servers/[^/]+/sse$","^/servers/[^/]+/message$","^/a2a(?:/|$)"]` | JSON array |
| `OBSERVABILITY_EXCLUDE_PATHS` | Regex patterns to exclude (after include patterns) | `["/health","/healthz","/ready","/metrics","/static/.*"]` | JSON array |

### Feature Flags

| Variable | Description | Default | Options |
|----------|-------------|---------|---------|
| `DB_METRICS_RECORDING_ENABLED` | Enable execution metrics (tool/resource/prompt/server/A2A) | `true` | `true`, `false` |
| `OBSERVABILITY_METRICS_ENABLED` | Enable metrics collection | `true` | `true`, `false` |
| `OBSERVABILITY_EVENTS_ENABLED` | Enable event logging | `true` | `true`, `false` |

## Admin UI Dashboards

### Tools Dashboard

**Path**: `/admin/observability/tools`

Provides comprehensive analytics for MCP tool invocations:

#### Summary Cards

- **Overall Health**: Success rate with color-coded status
  - Green: <5% errors (healthy)
  - Yellow: 5-20% errors (degraded)
  - Red: >20% errors (unhealthy)
- **Most Used**: Top tool by invocation count
- **Slowest**: Tool with highest p99 latency
- **Most Error-Prone**: Tool with highest error rate

#### Performance Charts

1. **Tool Usage Chart**: Bar chart showing invocation counts
2. **Average Latency Chart**: Bar chart with millisecond precision
3. **Error Rate Chart**: Percentage visualization with color coding
4. **Top N Error-Prone Tools**: Focused view of problematic tools

#### Detailed Metrics Table

For each tool:

- **Invocation Count**: Total number of calls
- **Latency Percentiles**: p50, p90, p95, p99 in milliseconds
- **Error Rate**: Percentage with color-coded status
- **Last Used**: Timestamp of most recent invocation

#### Filtering Options

- **Time Range**: Last 1 hour, 24 hours, 7 days, 30 days
- **Result Limit**: Top 10, 20, 50, or 100 tools
- **Auto-Refresh**: 60-second automatic updates

### Prompts Dashboard

**Path**: `/admin/observability/prompts`

Analyzes MCP prompt rendering performance:

#### Summary Cards

- **Overall Health**: Rendering success rate
- **Most Used**: Most frequently rendered prompt
- **Slowest**: Prompt with highest p99 latency
- **Most Error-Prone**: Prompt with highest failure rate

#### Performance Charts

1. **Prompt Render Frequency**: Usage distribution
2. **Average Latency**: Rendering performance
3. **Error Rate**: Failure rate analysis
4. **Top N Error-Prone Prompts**: Problem identification

#### Detailed Metrics

- **Render Count**: Total rendering operations
- **Latency Percentiles**: p50, p90, p95, p99 metrics
- **Error Rate**: Failure percentage with status
- **Last Rendered**: Most recent usage timestamp

### Resources Dashboard

**Path**: `/admin/observability/resources`

Monitors MCP resource fetch operations:

#### Summary Cards

- **Overall Health**: Fetch success rate
- **Most Used**: Most accessed resource
- **Slowest**: Resource with highest p99 latency
- **Most Error-Prone**: Resource with highest error rate

#### Performance Charts

1. **Resource Fetch Frequency**: Access patterns
2. **Average Latency**: Fetch performance
3. **Error Rate**: Failure analysis
4. **Top N Error-Prone Resources**: Issue detection

#### Detailed Metrics

- **Fetch Count**: Total access operations
- **Latency Percentiles**: p50, p90, p95, p99 metrics
- **Error Rate**: Failure rate with health status
- **Last Fetched**: Recent access timestamp

## Trace Visualization

### Trace List

**Path**: `/admin/observability/traces`

Browse all captured traces with:

- **Trace ID**: Unique identifier
- **Operation Name**: Human-readable description
- **Start Time**: When the trace began
- **Duration**: Total execution time
- **Status**: Success/error indicator
- **HTTP Details**: Method, URL, status code

### Trace Detail View

**Path**: `/admin/observability/traces/{trace_id}`

Comprehensive trace analysis:

#### Trace Metadata

- **Trace ID**: Unique identifier (W3C format)
- **Name**: Operation description
- **Status**: Overall outcome
- **Duration**: Total execution time
- **HTTP Context**: Method, URL, status code, user agent
- **User Context**: Email, IP address
- **Timestamps**: Start, end, created times

#### Gantt Chart Timeline

Visual representation showing:

- **Span Execution Order**: Chronological flow
- **Nested Operations**: Parent-child relationships
- **Duration Bars**: Relative timing visualization
- **Overlap Detection**: Concurrent operations

#### Flame Graph

Hierarchical view displaying:

- **Call Stack**: Nested span relationships
- **Time Distribution**: Width represents duration
- **Critical Path**: Longest execution chains
- **Bottleneck Identification**: Performance hotspots

#### Spans Table

Detailed span information:

- **Span ID**: Unique identifier
- **Name**: Operation description
- **Kind**: Span type (internal, server, client)
- **Start/End Time**: Execution window
- **Duration**: Millisecond precision
- **Status**: Success/error indicator
- **Resource Info**: Type, name, ID
- **Attributes**: Custom metadata

## Performance Metrics

### Latency Percentiles

The system calculates accurate percentiles using database aggregation:

- **p50 (Median)**: 50% of requests complete faster
- **p90**: 90% of requests complete faster
- **p95**: 95% of requests complete faster
- **p99**: 99% of requests complete faster

These metrics help identify performance outliers and establish SLAs.

### Health Status Indicators

Color-coded status based on error rates:

```
Green  (<5% errors)   - Healthy
Yellow (5-20% errors) - Degraded
Red    (>20% errors)  - Unhealthy
```

### Metrics Calculation

All metrics are calculated dynamically based on your selected time range:

- Real-time aggregation from trace database
- No pre-computation or caching delays
- Accurate percentile calculations using SQLite/PostgreSQL functions
- Efficient indexing for fast queries

## Data Retention

### Automatic Cleanup

Traces older than `OBSERVABILITY_TRACE_RETENTION_DAYS` are automatically deleted:

```bash
# Retain traces for 7 days (default)
OBSERVABILITY_TRACE_RETENTION_DAYS=7

# Extend retention to 30 days
OBSERVABILITY_TRACE_RETENTION_DAYS=30
```

### Size Limits

Prevent unbounded growth with `OBSERVABILITY_MAX_TRACES`:

```bash
# Store up to 100,000 traces (default)
OBSERVABILITY_MAX_TRACES=100000

# Increase for high-volume environments
OBSERVABILITY_MAX_TRACES=1000000
```

When the limit is reached, oldest traces are deleted first.

### Manual Cleanup

Use the CLI for manual trace management:

```bash
# Delete traces older than 7 days
mcpgateway observability cleanup --days 7

# Delete specific trace by ID
mcpgateway observability delete-trace <trace_id>

# Clear all traces (use with caution!)
mcpgateway observability clear-all
```

## Sampling Strategies

### Full Sampling (Development)

Capture all requests for complete visibility:

```bash
OBSERVABILITY_SAMPLE_RATE=1.0  # 100% sampling
```

### Partial Sampling (Production)

Reduce overhead while maintaining visibility:

```bash
# Sample 10% of requests
OBSERVABILITY_SAMPLE_RATE=0.1

# Sample 1% of requests (high volume)
OBSERVABILITY_SAMPLE_RATE=0.01
```

### Path Exclusion

Tune which paths are traced:

```bash
# Limit tracing to MCP/A2A endpoints (default include list)
OBSERVABILITY_INCLUDE_PATHS=["^/rpc/?$","^/sse$","^/message$","^/mcp(?:/|$)","^/servers/[^/]+/mcp/?$","^/servers/[^/]+/sse$","^/servers/[^/]+/message$","^/a2a(?:/|$)"]

# Trace all endpoints (leave include list empty)
OBSERVABILITY_INCLUDE_PATHS=[]

# Default exclusions
OBSERVABILITY_EXCLUDE_PATHS=["/health","/healthz","/ready","/metrics","/static/.*"]

# Custom exclusions (regex patterns applied after includes)
OBSERVABILITY_EXCLUDE_PATHS=["/health.*","/metrics.*","/static/.*","/admin/assets/.*"]
```

## Database Schema

### ObservabilityTrace Table

Stores complete request traces:

```sql
CREATE TABLE observability_traces (
    trace_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_ms FLOAT,
    status VARCHAR(20) DEFAULT 'unset',
    status_message TEXT,
    http_method VARCHAR(10),
    http_url VARCHAR(767),
    http_status_code INTEGER,
    user_email VARCHAR(255),
    user_agent TEXT,
    ip_address VARCHAR(45),
    attributes JSON,
    resource_attributes JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### ObservabilitySpan Table

Stores individual operations within traces:

```sql
CREATE TABLE observability_spans (
    span_id VARCHAR(36) PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL,
    parent_span_id VARCHAR(36),
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(20) DEFAULT 'internal',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_ms FLOAT,
    status VARCHAR(20) DEFAULT 'unset',
    status_message TEXT,
    attributes JSON,
    resource_name VARCHAR(255),
    resource_type VARCHAR(50),
    resource_id VARCHAR(36),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trace_id) REFERENCES observability_traces(trace_id),
    FOREIGN KEY (parent_span_id) REFERENCES observability_spans(span_id)
);
```

### Performance Indexes

Optimized for fast queries:

```sql
-- Trace indexes
CREATE INDEX idx_observability_traces_start_time ON observability_traces(start_time);
CREATE INDEX idx_observability_traces_user_email ON observability_traces(user_email);
CREATE INDEX idx_observability_traces_status ON observability_traces(status);
CREATE INDEX idx_observability_traces_http_status_code ON observability_traces(http_status_code);

-- Span indexes
CREATE INDEX idx_observability_spans_trace_id ON observability_spans(trace_id);
CREATE INDEX idx_observability_spans_parent_span_id ON observability_spans(parent_span_id);
CREATE INDEX idx_observability_spans_start_time ON observability_spans(start_time);
CREATE INDEX idx_observability_spans_resource_type ON observability_spans(resource_type);
CREATE INDEX idx_observability_spans_resource_name ON observability_spans(resource_name);
```

## REST API

### List Traces

```bash
GET /observability/traces
```

Query parameters:

- `start_time`: Filter traces after this timestamp (ISO 8601)
- `end_time`: Filter traces before this timestamp
- `min_duration_ms`: Minimum duration in milliseconds
- `max_duration_ms`: Maximum duration in milliseconds
- `status`: Filter by status (`ok`, `error`)
- `http_status_code`: Filter by HTTP status code
- `http_method`: Filter by HTTP method
- `user_email`: Filter by user email
- `limit`: Maximum results (default: 100)
- `offset`: Result offset (default: 0)

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/observability/traces?limit=10&status=error"
```

### Get Trace Details

```bash
GET /observability/traces/{trace_id}
```

Returns complete trace with all spans, events, and metrics.

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/observability/traces/550e8400-e29b-41d4-a716-446655440000"
```

### Query Tool Metrics

```bash
GET /observability/tools/metrics
```

Query parameters:

- `time_range`: Time window (`1h`, `24h`, `7d`, `30d`)
- `limit`: Number of tools to return

Example:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/observability/tools/metrics?time_range=24h&limit=20"
```

### Query Prompt Metrics

```bash
GET /observability/prompts/metrics
```

Same parameters as tool metrics.

### Query Resource Metrics

```bash
GET /observability/resources/metrics
```

Same parameters as tool metrics.

## Comparison: Internal vs OpenTelemetry

| Feature | Internal Observability | OpenTelemetry |
|---------|----------------------|---------------|
| **Storage** | Database (SQLite/PostgreSQL/MariaDB) | External backends (Phoenix, Jaeger, Tempo) |
| **Setup** | Built-in, zero configuration | Requires external services |
| **Cost** | Free, self-hosted | Depends on backend (free OSS or paid SaaS) |
| **Retention** | Configurable in-database | Backend-dependent |
| **UI** | Admin UI dashboards | Backend-specific UIs |
| **Performance Impact** | Minimal (database writes) | Minimal (async exports) |
| **Use Cases** | Development, testing, small deployments | Production, microservices, distributed systems |
| **Standards** | Custom implementation | OpenTelemetry standard |
| **Integration** | Self-contained | Integrates with APM ecosystem |

### When to Use Each

**Use Internal Observability when:**

- You want zero external dependencies
- Database storage is acceptable
- Admin UI visualization is sufficient
- Deployment simplicity is a priority
- You're in development/testing mode

**Use OpenTelemetry when:**

- You need distributed tracing across multiple services
- You want vendor-agnostic standard
- You have existing observability infrastructure
- You need advanced APM features
- You're in production with high scale

**Use Both when:**

- You want local debugging with external production monitoring
- You need different retention policies
- You want redundancy in observability data

## Production Considerations

### Performance Impact

The internal observability system is designed for minimal overhead:

- **Database Writes**: Async, batched when possible
- **Indexing**: Optimized indexes for fast queries
- **Sampling**: Reduce load with configurable sample rates
- **Cleanup**: Automatic retention management

### Scaling Recommendations

For high-volume deployments:

```bash
# Reduce sampling rate
OBSERVABILITY_SAMPLE_RATE=0.1  # 10% sampling

# Aggressive retention
OBSERVABILITY_TRACE_RETENTION_DAYS=3

# Exclude high-frequency paths
OBSERVABILITY_EXCLUDE_PATHS=["/health.*","/metrics.*","/static/.*"]

# Disable HTTP request tracing (manual traces only)
OBSERVABILITY_TRACE_HTTP_REQUESTS=false
```

### Database Considerations

#### SQLite

Suitable for:

- Development and testing
- Single-instance deployments
- Low to medium traffic

Limitations:

- Write concurrency limits
- File-based storage

#### PostgreSQL

Recommended for:

- Production deployments
- High-volume environments
- Multi-instance setups

Benefits:

- Superior write concurrency
- Advanced indexing
- Better query performance

#### MariaDB/MySQL

Alternative production option:

- Good write performance
- Wide deployment support
- Compatible with PostgreSQL features

### Monitoring the Monitor

Track observability system health:

```bash
# Check trace count
SELECT COUNT(*) FROM observability_traces;

# Check database size
SELECT pg_size_pretty(pg_total_relation_size('observability_traces'));
SELECT pg_size_pretty(pg_total_relation_size('observability_spans'));

# Check oldest trace
SELECT MIN(start_time) FROM observability_traces;

# Check cleanup effectiveness
SELECT COUNT(*) FROM observability_traces
WHERE start_time < NOW() - INTERVAL '7 days';
```

## Troubleshooting

### No Traces Appearing

1. **Verify observability is enabled**:

   ```bash
   echo $OBSERVABILITY_ENABLED  # Should be "true"
   ```

2. **Check sampling rate**:

   ```bash
   echo $OBSERVABILITY_SAMPLE_RATE  # Should be > 0.0
   ```

3. **Review included paths**:

   ```bash
   echo $OBSERVABILITY_INCLUDE_PATHS
   # Ensure your test path is included
   ```

4. **Review excluded paths**:

   ```bash
   echo $OBSERVABILITY_EXCLUDE_PATHS
   # Ensure your test path is not excluded
   ```

5. **Check database connection**:

   ```bash
   # Verify database is accessible
   mcpgateway db-check
   ```

6. **Enable debug logging**:

   ```bash
   export LOG_LEVEL=DEBUG
   mcpgateway
   # Look for observability-related log messages
   ```

### High Database Size

1. **Reduce retention period**:

   ```bash
   OBSERVABILITY_TRACE_RETENTION_DAYS=3
   ```

2. **Lower maximum traces**:

   ```bash
   OBSERVABILITY_MAX_TRACES=10000
   ```

3. **Increase sampling threshold**:

   ```bash
   OBSERVABILITY_SAMPLE_RATE=0.1
   ```

4. **Manually cleanup**:

   ```bash
   mcpgateway observability cleanup --days 1
   ```

### Slow Dashboard Loading

1. **Reduce query time range**:

   - Use shorter time windows (1 hour instead of 30 days)

2. **Limit result count**:

   - Query top 10 instead of top 100

3. **Add database indexes** (if custom deployment):

   ```sql
   CREATE INDEX idx_custom ON observability_spans(resource_type, start_time);
   ```

4. **Optimize database**:

   ```bash
   # PostgreSQL
   VACUUM ANALYZE observability_traces;
   VACUUM ANALYZE observability_spans;

   # SQLite
   VACUUM;
   ```

### Missing Spans or Metrics

1. **Check span creation**:

   - Verify tool/prompt/resource operations are completing
   - Look for errors in application logs

2. **Verify metrics enabled**:

   ```bash
   echo $OBSERVABILITY_METRICS_ENABLED  # Should be "true"
   ```

3. **Check events enabled**:

   ```bash
   echo $OBSERVABILITY_EVENTS_ENABLED  # Should be "true"
   ```

## Best Practices

### Development

```bash
# Full tracing, short retention
OBSERVABILITY_ENABLED=true
OBSERVABILITY_SAMPLE_RATE=1.0
OBSERVABILITY_TRACE_RETENTION_DAYS=1
OBSERVABILITY_MAX_TRACES=10000
```

### Staging

```bash
# Partial tracing, moderate retention
OBSERVABILITY_ENABLED=true
OBSERVABILITY_SAMPLE_RATE=0.5
OBSERVABILITY_TRACE_RETENTION_DAYS=7
OBSERVABILITY_MAX_TRACES=100000
```

### Production

```bash
# Sampled tracing, longer retention
OBSERVABILITY_ENABLED=true
OBSERVABILITY_SAMPLE_RATE=0.1
OBSERVABILITY_TRACE_RETENTION_DAYS=14
OBSERVABILITY_MAX_TRACES=1000000
OBSERVABILITY_EXCLUDE_PATHS=["/health.*","/metrics.*"]
```

## Next Steps

- Review [Configuration Reference](../configuration.md) for all observability settings
- Explore [OpenTelemetry Integration](observability.md) for external monitoring
- Set up [Phoenix Integration](phoenix.md) for AI-specific observability
- Configure [Prometheus Metrics](../observability.md#prometheus-metrics-important) for time-series monitoring
- Implement [Custom Dashboards](#admin-ui-dashboards) based on your metrics

## Related Documentation

- [Configuration Reference](../configuration.md) - Environment variable configuration
- [OpenTelemetry Observability](observability.md) - External tracing backends
- [Phoenix Integration](phoenix.md) - AI/LLM observability
- [Admin UI Documentation](../ui-customization.md) - Customizing the Admin UI
- [Database Configuration](../configuration.md#database-configuration) - Database setup and tuning
