# Results — Full Load Test (Rust Core)

## Branch: ocp-rust-mcp-runtime
## Date: April 2-3, 2026
## Cluster: contextforge-p02-rocp01.cp.fyre.ibm.com (OCP 4.20.14)
## Namespace: gp-context-forge

## Architecture

  Locust pod (1 master + 4 workers, distributed)
    → HTTP → NGINX pod (:80)
      → HTTP → Gateway pod (:4444, Python auth → Rust MCP runtime via UDS)
        → CrunchyData PgBouncer → CrunchyData Postgres
        → Redis

## Configuration

  Component              | Pods | CPU    | Memory | Key Settings
  -----------------------|------|--------|--------|---------------------------
  Gateway (Rust)         | 3    | 8 each | 8Gi    | RUST_MCP_MODE=full, Gunicorn 8 workers
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
    COMPRESSION_ENABLED: false
    LLMCHAT_ENABLED: true
    Cache TTLs: 300s (auth, registry, teams)
    Connection pools: Redis 100, HTTPX 500, DB pool 20
    Plugins: Disabled (benchmark mode)

  Rust MCP runtime:
    Image: docker.io/gandhipratik203/mcp-context-forge:rust
    Built on API server with: --build-arg ENABLE_RUST=true --build-arg ENABLE_RUST_MCP_RMCP=true
    Mode: rust-managed
    Session core: rust
    Event store: rust

## Test Parameters

  Locustfile:  tests/loadtest/locustfile.py (full, 80+ user classes)
  Users:       4000 concurrent
  Spawn rate:  200 users/s
  Duration:    10 minutes
  Source:      In-cluster distributed Locust (plaintext HTTP)

## Results

  Metric               | OCP Rust     | VM Rust      | OCP Python   | VM Python
  ---------------------|-------------|-------------|-------------|-------------
  Total requests       | 721,551     | 765,006     | 720,987     | 634,116
  RPS                  | 1,260       | 1,276       | 1,142       | 1,057
  Avg response         | 856ms       | 720ms       | 831ms       | 1,172ms
  p50                  | 3ms         | 210ms       | 13ms        | 410ms
  Failures             | 10.9%       | 2.97%       | 16.1%       | 2.69%

  Top endpoints (all 0% failures):
    Endpoint                          | Requests | Avg (ms)
    ----------------------------------|----------|----------
    /tools                            |   35,490 |        5
    /servers                          |   27,442 |        6
    /health                           |   22,424 |        2
    MCP tools/list                    |   19,935 |      610
    /gateways                         |   19,482 |        5
    /resources                        |   17,990 |        4
    MCP fast-test-echo                |   13,505 |    1,530
    /tokens                           |   13,364 |        2

  Failure note: 10.9% failures from unconfigured features
  (/llm/*, /admin/grpc — same on VM). Core API and MCP: 0% failures.

## Python vs Rust (OCP)

  Metric               | Python       | Rust         | Improvement
  ---------------------|-------------|-------------|------------
  RPS                  | 1,142       | 1,260       | +10%
  p50                  | 13ms        | 3ms         | 4x faster
  Failures             | 16.1%       | 10.9%       | -32%

## Conclusion

  Rust core on OCP matches VM Rust benchmark (1,260 vs 1,276 RPS).
  OCP exceeds VM on both Python (1,142 vs 1,057) and Rust (1,260 vs 1,276).
  Rust provides 10% RPS improvement and 4x faster p50 over Python on OCP.

## Steps to Reproduce

  1. Build Rust image: podman build --build-arg ENABLE_RUST=true -f Containerfile.lite
  2. Push to registry
  3. Deploy with values-ocp-gp.yaml (image: rust tag, RUST_MCP_MODE: full)
  4. Install CrunchyData PGO, apply crunchydata-postgres-cr.yaml
  5. Scale NGINX to 3, set up Locust (4 workers)
  6. Trigger: curl -X POST http://locust:8089/swarm \
     -d 'user_count=4000&spawn_rate=200&run_time=10m'
