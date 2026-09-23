# Python ContextForge

## Compose Stack Resource Allocation

Services launched by `make prod-up` (docker-compose.prod.yml override, no profile flags).

| Service | Replicas | CPU Limit | Mem Limit | CPU Reservation | Mem Reservation |
|---|---|---|---|---|---|
| nginx | 1 | 4 | 4 G | 4 | 4 G |
| gateway | 3 | 4 | 4 G | 4 | 4 G |
| postgres | 1 | 4 | 4 G | 4 | 4 G |
| pgbouncer | 1 | 4 | 4 G | 4 | 4 G |
| migration | 1 (one-shot) | — | — | — | — |
| redis | 1 | 4 | 4 G | 4 | 4 G |
| fast_time_server | 1 | 4 | 4 G | 4 | 4 G |
| register_fast_time | 1 (one-shot) | — | — | — | — |
| **Total** | | **32** | **32 G** | **32** | **32 G** |

Gateway runs 3 replicas; each replica contributes 4 CPU / 4 G to the totals.
One-shot containers (migration, register_fast_time) have no resource constraints and are excluded from totals.

### Benchmark: `make benchmark-mcp-tools`

- **Date**: 2026-09-15
- **Host**: http://localhost:8080
- **Users**: 125, Spawn: 30/s, Duration: 1800s (30 min)

#### Overall

| Metric | Value |
|---|---|
| Requests/sec (RPS) | 143.97 |
| Total Requests | 259,149 |
| Total Failures | 617 (0.24%) |
| Avg Response Time | 805.35 ms |
| Min Response Time | 20.77 ms |
| Max Response Time | 30,001.84 ms |
| p50 | 600 ms |
| p90 | 1,700 ms |
| p95 | 2,200 ms |
| p99 | 3,200 ms |

#### Endpoint Breakdown

| Endpoint | Requests | Failures | RPS | Avg (ms) | p99 (ms) |
|---|---|---|---|---|---|
| MCP tools/call [rapid] | 246,604 | 579 | 137.0 | 807.2 | 3,200 |
| MCP tools/list [rapid] | 12,420 | 38 | 6.9 | 753.4 | 3,000 |
| MCP initialize | 125 | 0 | 0.1 | 2,245.7 | 9,300 |
