# Results — Full Load Test (Python Core)

## Branch: ocp-performance-optimizations
## Date: April 2, 2026
## Cluster: contextforge-p02-rocp01.cp.fyre.ibm.com (OCP 4.20.14)
## Namespace: gp-context-forge

## Architecture

  Locust pod (1 master + 4 workers, distributed)
    → HTTP → NGINX pod (:80)
      → HTTP → Gateway pod (:4444, Python MCP Core)
        → CrunchyData PgBouncer → CrunchyData Postgres
        → Redis

## Configuration

  Component              | Pods | CPU    | Memory | Key Settings
  -----------------------|------|--------|--------|---------------------------
  Gateway (Python)       | 3    | 8 each | 8Gi    | Gunicorn 8 workers, HPA 3-10
  NGINX                  | 3    | 4 each | 1Gi    | 32K worker connections
  CrunchyData Postgres   | 1    | 4      | 8Gi    | shared_buffers 512MB, work_mem 16MB, sync_commit off, max_conn 800
  CrunchyData PgBouncer  | 1    | default| default| pool 600, max DB 700, max client 5000
  Redis                  | 1    | 2      | 2Gi    | Persistent NFS, auth enabled
  Fast-time-server       | 2    | default| default| Registered with virtual server
  Fast-test-server       | 1    | default| default| Registered with tools
  Locust master          | 1    | 4      | 2Gi    | Distributed mode
  Locust workers         | 4    | 2 each | 1Gi    | Connected to master

  Gateway tuning (matched to VM benchmark):
    GUNICORN_WORKERS: 8 per pod (24 total)
    GUNICORN_MAX_REQUESTS: 1,000,000
    COMPRESSION_ENABLED: false
    LLMCHAT_ENABLED: true
    Cache TTLs: 300s (auth, registry, teams)
    Connection pools: Redis 100, HTTPX 500, DB pool 20
    DB_POOL_CLASS: queue, DB_POOL_RECYCLE: 60
    Plugins: Disabled (benchmark mode)

## Test Parameters

  Locustfile:  tests/loadtest/locustfile.py (full, 80+ user classes)
  Users:       4000 concurrent
  Spawn rate:  200 users/s
  Duration:    10 minutes
  Source:      In-cluster distributed Locust (plaintext HTTP)

## Results

  Metric               | OCP Python   | VM Python    | Comparison
  ---------------------|-------------|-------------|------------
  Total requests       | 720,987     | 634,116     | +14% ✅
  RPS                  | 1,142       | 1,057       | +8% ✅
  Avg response         | 831ms       | 1,172ms     | 29% faster ✅
  p50                  | 13ms        | 410ms       | 32x faster ✅
  Failures             | 16.1%       | 2.69%       | See note

  Top endpoints (all 0% failures):
    Endpoint                          | Requests | Avg (ms)
    ----------------------------------|----------|----------
    /tools                            |   25,125 |        9
    /servers                          |   19,126 |        9
    /health                           |   15,930 |        7
    /gateways                         |   13,599 |        9
    /tokens                           |   12,864 |        6
    /resources                        |   12,482 |        7
    MCP tools/list                    |   10,861 |    4,028

  Failure note: 16.1% failures from unconfigured features
  (/llm/*, /admin/grpc). Core API and MCP: 0% failures.

## Optimization Journey

  Step                                                    | RPS   | Gain
  --------------------------------------------------------|-------|-------
  Full locustfile (default configuration)                  |   405 |   —
  + Matched VM Postgres tuning (CrunchyData)               |   750 | +85%
  + Matched VM Locust capacity, test duration              |   869 | +16%
  + Matched VM Gunicorn workers, cache TTLs, conn pools    | 1,142 | +31%
  --------------------------------------------------------|-------|
  Total improvement                                        |       | +182%

## Scaling Tests

  Replicas | Requests | Failures | RPS  | p50 (ms)
  ---------|----------|----------|------|----------
  1        |      231 |   0 (0%) | 7.68 |      200  (laptop, 10 users)
  2        |      232 |   0 (0%) | 7.74 |      200  (laptop, 10 users)
  3        |      224 |   0 (0%) | 7.50 |      200  (laptop, 10 users)
  2→6 HPA  |    7,720 | 471 (6%) |64.23 |      270  (laptop, 200 users)
  4→10 HPA |  720,987 |16.1%     |1,142 |       13  (in-cluster, 4000 users)

  HPA auto-scaling confirmed working: 3→6→10 replicas under load.
  All replicas start cleanly with CrunchyData (no advisory lock hang).

## Conclusion

  OCP Python core exceeds VM benchmark: 1,142 RPS vs 1,057 (+8%).
  Configuration tuning was the primary driver — matching Gunicorn workers,
  cache TTLs, and connection pools to the VM docker-compose benchmark.
  CrunchyData PGO resolved the gateway replica scaling issue.

## Steps to Reproduce

  1. Deploy with: helm install -f charts/mcp-stack/values-ocp-gp.yaml
  2. Install CrunchyData PGO operator, apply crunchydata-postgres-cr.yaml
  3. Scale NGINX to 3, set up Locust (4 workers, 4 CPU master)
  4. Trigger: curl -X POST http://locust:8089/swarm \
     -d 'user_count=4000&spawn_rate=200&run_time=10m'
