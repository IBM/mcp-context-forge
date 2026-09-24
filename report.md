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

Reservations equal the limits for every service; `prod-up` ignores the `GATEWAY_*_LIMIT` / `GATEWAY_*_RESERVATION` env knobs, `GATEWAY_REPLICAS` still applies.
Gateway runs 3 replicas; each replica contributes 4 CPU / 4 G to the totals.
One-shot containers (migration, register_fast_time) have no resource constraints and are excluded from totals.
Limits are ceilings, not allocations: the stack only needs a host with 32 CPU / 32 G if every service saturates at once.
Mem Reservation is the soft floor Docker applies under memory pressure (`--memory-reservation`); it does not preallocate.
CPU Reservation is declarative only: Docker Compose ignores `reservations.cpus` outside swarm mode.

### Benchmark: `MCP_BENCHMARK_RUN_TIME=1800s make benchmark-mcp-tools`

- **Date**: 2026-09-15
- **Host**: http://localhost:8080
- **Users**: 125, Spawn: 30/s, Duration: 1800s (30 min, overrides the 60s default)
- **Stack**: run on 2026-09-15, before `docker-compose.prod.yml` existed (committed 2026-09-23), so these numbers do not reflect the 4 CPU / 4 G pin above. Re-run under `make prod-up` to compare.

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
