# ADR-030: Metrics Cleanup and Rollup

- *Status:* Accepted
- *Date:* 2025-01-15
- *Deciders:* Platform Team

## Context

In production deployments with high API traffic, the raw metrics tables (`tool_metrics`, `resource_metrics`, `prompt_metrics`, `server_metrics`, `a2a_agent_metrics`) can grow unboundedly, causing:

1. **Storage exhaustion**: Millions of raw metric records consuming disk space
2. **Query performance degradation**: Historical aggregate queries become slow as tables grow
3. **Backup/restore overhead**: Large tables increase backup times and costs

At 1000+ requests/minute, metrics tables can grow by:

- ~1.5 million records/day per active table
- ~45 million records/month
- Query latency increases from <10ms to >500ms for aggregation queries

Related issues: #1735 (Add metrics cleanup and rollup for long-term performance)

## Decision

Implement a two-tier metrics management strategy with configurable cleanup and hourly rollup:

### 1. Metrics Cleanup Service

Automatic deletion of old raw metrics with batched processing to prevent long table locks.

**New module: `mcpgateway/services/metrics_cleanup_service.py`**
- Background task running at configurable intervals (default: 24 hours)
- Batched deletion (default: 10,000 records per batch) to prevent lock contention
- Configurable retention period (default: 30 days)
- Per-table cleanup with statistics reporting
- Manual trigger via admin API

### 2. Metrics Rollup Service

Pre-aggregation of raw metrics into hourly summary tables for efficient historical queries.

**New module: `mcpgateway/services/metrics_rollup_service.py`**
- Hourly aggregation with percentile calculation (p50, p95, p99)
- Background task running at configurable intervals (default: 1 hour)
- Upsert logic for safe re-runs
- Optional deletion of raw metrics after rollup
- Entity name preservation (rollups retain names even if entity is deleted)

### 3. Hourly Summary Tables

Five new database tables for pre-aggregated metrics:

- `tool_metrics_hourly`
- `resource_metrics_hourly`
- `prompt_metrics_hourly`
- `server_metrics_hourly`
- `a2a_agent_metrics_hourly`

Each table includes:

- Entity ID and name (preserved snapshot)
- Hour start timestamp
- Total/success/failure counts
- Min/max/avg response times
- p50, p95, p99 percentiles
- Created timestamp

### 4. Admin API Endpoints

**New router: `mcpgateway/routers/metrics_maintenance.py`**
- `POST /api/metrics/cleanup` - Trigger manual cleanup
- `POST /api/metrics/rollup` - Trigger manual rollup
- `GET /api/metrics/stats` - Get cleanup/rollup statistics
- `GET /api/metrics/config` - Get current configuration

### 5. Configuration Settings

**Cleanup Configuration:**

- `METRICS_CLEANUP_ENABLED` (default: true)
- `METRICS_RETENTION_DAYS` (default: 7, range: 1-365) - fallback when rollup disabled
- `METRICS_CLEANUP_INTERVAL_HOURS` (default: 1, range: 1-168)
- `METRICS_CLEANUP_BATCH_SIZE` (default: 10000, range: 100-100000)

**Rollup Configuration:**

- `METRICS_ROLLUP_ENABLED` (default: true)
- `METRICS_ROLLUP_INTERVAL_HOURS` (default: 1, range: 1-24)
- `METRICS_ROLLUP_RETENTION_DAYS` (default: 365, range: 30-3650)
- `METRICS_ROLLUP_LATE_DATA_HOURS` (default: 1, range: 1-48) - hours to re-process each run for late-arriving data
- `METRICS_DELETE_RAW_AFTER_ROLLUP` (default: true) - delete raw after rollup exists
- `METRICS_DELETE_RAW_AFTER_ROLLUP_HOURS` (default: 1, range: 1-8760)

## Performance Characteristics

### Before (Unbounded Growth)
| Metric | 1 Month | 6 Months | 1 Year |
|--------|---------|----------|--------|
| Raw metrics rows | ~45M | ~270M | ~540M |
| Table size | ~5 GB | ~30 GB | ~60 GB |
| Aggregate query P95 | ~500ms | ~2s | ~5s |

### After (With Cleanup + Rollup)
| Metric | Steady State |
|--------|--------------|
| Raw metrics rows | ~1.5M (30 days) |
| Hourly rollup rows | ~365K (1 year) |
| Total storage | ~500 MB |
| Historical query P95 | <50ms |
| Recent query P95 | <10ms |

**Expected improvement**: 90-99% reduction in storage and query latency

## Consequences

### Positive

- Bounded storage growth with configurable retention
- Fast historical trend queries via pre-aggregated rollups
- Percentile data preserved for SLA reporting
- Batched operations prevent production impact
- Graceful handling of deleted entities (names preserved in rollups)
- Background processing with no blocking of API requests

### Negative

- Raw data loss after retention period (mitigated by rollup preservation)
- Additional database writes during rollup (mitigated by hourly batching)
- Memory usage for rollup percentile calculation
- Slight complexity in choosing optimal retention/rollup settings

### Neutral

- Both features enabled by default (can be disabled)
- No impact on real-time metrics collection
- Existing aggregate queries continue to work (can optionally use rollup tables)
- Database migration required for new tables

## Implementation Details

### Combined Raw + Rollup Query Strategy

All aggregate metrics endpoints (`aggregate_metrics` methods in `tool_service.py`, `resource_service.py`, `prompt_service.py`, `server_service.py`, `a2a_service.py`) now use a combined query strategy via `metrics_query_service.py`:

1. **Recent data**: Query raw metrics table for data within retention period
2. **Historical data**: Query hourly rollup table for data older than retention period
3. **Merge results**: Combine counts, weighted averages, and min/max values

This ensures complete historical coverage even after cleanup deletes old raw metrics.

### Smart Backfill Detection

The background rollup service includes automatic backfill detection:

1. On startup, checks for earliest unprocessed raw metrics
2. Calculates hours since earliest data (capped at retention period)
3. Processes all unprocessed hours on first run
4. Subsequent runs process only the last N hours (configurable via `METRICS_ROLLUP_LATE_DATA_HOURS`, default: 1)

This handles scenarios where the service was down for extended periods and ensures late-arriving metrics (from buffer flushes or ingestion lag) are included in rollups.

### Optimized Rollup Aggregation

The rollup aggregation uses bulk queries to minimize database round trips:

1. Single GROUP BY query for basic aggregations (count, min, max, avg, success_count)
2. Bulk entity name lookup in one query
3. Bulk response time loading for percentile calculation
4. Pre-sorted data from SQL ORDER BY for efficient percentile computation

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Table partitioning | Database-specific, complex to manage |
| External time-series DB | Additional infrastructure complexity |
| No cleanup (archive to cold storage) | Still requires storage management |
| Delete without rollup | Loses historical trend data |
| Real-time streaming aggregation | Over-engineered for current scale |

## Migration Path

1. Apply database migration: `alembic upgrade head`
2. Services auto-start with default configuration
3. First rollup processes last 24 hours of existing data
4. First cleanup runs after configured interval (24h default)

## Compatibility Notes

- Features are enabled by default with conservative settings
- Can be disabled without code changes via environment variables
- No breaking changes to existing APIs
- Existing metrics queries continue to work
- Rollup tables are additive (no schema changes to existing tables)

## References

- GitHub Issue #1735: Add metrics cleanup and rollup for long-term performance
- `mcpgateway/services/metrics_cleanup_service.py` - Cleanup implementation
- `mcpgateway/services/metrics_rollup_service.py` - Rollup implementation
- `mcpgateway/services/metrics_query_service.py` - Combined raw + rollup query service
- `mcpgateway/routers/metrics_maintenance.py` - Admin API endpoints
- `mcpgateway/alembic/versions/q1b2c3d4e5f6_add_metrics_hourly_rollup_tables.py` - Migration

## Status

Implemented and enabled by default. Monitor via `/api/metrics/stats` endpoint.
