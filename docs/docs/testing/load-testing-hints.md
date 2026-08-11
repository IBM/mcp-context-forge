# Load Testing Hints

Quick reference for running containerized load tests with `docker compose` and Locust.

---

## Starting the Testing Stack

```bash
# Default: starts gateway, nginx, Locust (web UI), and A2A echo agent
make testing-up
```

All load testing services run inside Docker on the `mcpnet` network. Locust targets `http://nginx:80` by default.

---

## Environment Variable Reference

### Locust Configuration

Override these when calling `make testing-up` or `docker compose --profile testing up`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCUST_LOCUSTFILE` | `locustfile.py` | Which locustfile to run (any file in `tests/loadtest/`) |
| `LOCUST_MODE` | `master` | `master` for web UI, `headless` for CLI-only |
| `LOCUST_USERS` | `100` | Number of concurrent simulated users |
| `LOCUST_SPAWN_RATE` | `10` | Users spawned per second during ramp-up |
| `LOCUST_RUN_TIME` | `5m` | Test duration (headless mode only), e.g. `30s`, `5m`, `1h` |
| `LOCUST_EXPECT_WORKERS` | `1` | Number of distributed workers the master expects |

**Examples:**

```bash
# Run the main load-test locustfile with web UI
LOCUST_LOCUSTFILE=locustfile.py make testing-up

# Use the high-throughput locustfile
LOCUST_LOCUSTFILE=locustfile_highthroughput.py make testing-up

# Scale to 4 Locust workers for higher concurrency
TESTING_LOCUST_WORKERS=4 make testing-up
```

### Gateway Scaling

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_REPLICAS` | `3` | Number of gateway container instances |
| `GATEWAY_CPU_LIMIT` | `8` | CPU limit per replica |
| `GATEWAY_MEM_LIMIT` | `8G` | Memory limit per replica |
| `GATEWAY_CPU_RESERVATION` | `4` | CPU reservation per replica |
| `GATEWAY_MEM_RESERVATION` | `4G` | Memory reservation per replica |
| `GUNICORN_WORKERS` | `24` | Gunicorn worker processes per replica |

**Examples:**

```bash
# 6 small replicas with 5 workers each (30 total workers)
GATEWAY_REPLICAS=6 GATEWAY_CPU_LIMIT=1 GATEWAY_MEM_LIMIT=2G \
  GATEWAY_CPU_RESERVATION=0.5 GATEWAY_MEM_RESERVATION=1G \
  GUNICORN_WORKERS=5 make testing-up

# Single large replica for debugging
GATEWAY_REPLICAS=1 GUNICORN_WORKERS=4 make testing-up
```

### Gateway Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://...@pgbouncer:6432/mcp` | Database connection string |
| `POSTGRES_PASSWORD` | `mysecretpassword` | PostgreSQL password (used in default `DATABASE_URL`) |
| `MCP_SESSION_POOL_ENABLED` | `true` | Enable MCP client session pooling |

**Examples:**

```bash
# Bypass PgBouncer and connect directly to PostgreSQL
DATABASE_URL='postgresql+psycopg://postgres:mysecretpassword@postgres:5432/mcp' make testing-up

# Disable session pooling (uses fresh connection per tool call — slower but more reliable)
MCP_SESSION_POOL_ENABLED=false make testing-up

# Combine: small replicas + direct Postgres + no pool
GATEWAY_REPLICAS=6 GUNICORN_WORKERS=5 MCP_SESSION_POOL_ENABLED=false \
  DATABASE_URL='postgresql+psycopg://postgres:mysecretpassword@postgres:5432/mcp' \
  make testing-up
```


---

## Available Locustfiles

| File | Description |
|------|-------------|
| `locustfile.py` | Main comprehensive test with 20+ user classes |
| `locustfile_baseline.py` | Component baselines (REST, MCP, PostgreSQL, Redis) |
| `locustfile_highthroughput.py` | Optimized for maximum RPS |
| `locustfile_slow_time_server.py` | Resilience testing against slow backends |
| `locustfile_spin_detector.py` | CPU spin loop detection (spike/drop pattern) |
| `locustfile_agentgateway_mcp_server_time.py` | External MCP server testing |

---

## Typical Workflows

### Stress test with many replicas

```bash
LOCUST_LOCUSTFILE=locustfile.py \
  LOCUST_USERS=2000 LOCUST_SPAWN_RATE=100 \
  TESTING_LOCUST_WORKERS=4 \
  GATEWAY_REPLICAS=6 GUNICORN_WORKERS=5 \
  make testing-up
```

### Headless CI run

```bash
LOCUST_LOCUSTFILE=locustfile.py \
  LOCUST_MODE=headless LOCUST_USERS=100 LOCUST_RUN_TIME=60s \
  make testing-up
# Reports saved to reports/locust_report.html and reports/locust_*.csv
```

---

## Stopping the Stack

```bash
make testing-down
```

---

## Host Tuning

For 500+ concurrent users, tune the host OS first. See [Performance Testing](performance.md#host-tcp-tuning-for-load-testing) for TCP, file descriptor, and memory settings, or run:

```bash
sudo scripts/tune-loadtest.sh
```
