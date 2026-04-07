# MCP Benchmark Results — Python Core on OCP

## Configuration

| Component | Pods | CPU | Memory | Key Settings |
|-----------|------|-----|--------|-------------|
| Gateway (Python) | 3 | 8 each | 8Gi | Gunicorn 8 workers, session pool enabled |
| NGINX | 3 | 4 each | 1Gi | 32K worker connections |
| CrunchyData Postgres | 1 | 4 | 8Gi | shared_buffers 512MB, sync_commit off, max_conn 800 |
| CrunchyData PgBouncer | 1 | default | default | pool 600, max DB 700 |
| Redis | 1 | 2 | 2Gi | Auth enabled |
| Fast-time-server | 2 | default | default | Go MCP server |
| Fast-test-server | 1 | default | default | Rust MCP server (TCP_NODELAY) |
| Locust | 1 master + 3-4 workers | 4 / 2 each | 2Gi / 1Gi | Distributed mode |

Gateway tuning:
- Image: `ghcr.io/ibm/mcp-context-forge:latest`
- `GUNICORN_WORKERS: 8` per pod (24 total)
- `COMPRESSION_ENABLED: false`
- `MCP_SESSION_POOL_ENABLED: true` (critical for performance)
- `MCP_SESSION_POOL_MAX_PER_KEY: 200`
- `TRANSPORT_TYPE: streamablehttp`
- Cache TTLs: 300s (auth, registry, teams)
- Plugins: disabled (benchmark mode)

## Test Parameters

- Locustfile: `tests/loadtest/locustfile_mcp_protocol.py`
- User classes: all MCP protocol classes (MCPToolCallerUser, MCPAgentUser, MCPDiscoveryUser, MCPSessionChurnUser, MCPStressUser)
- Users: 125 concurrent
- Spawn rate: 30 users/s
- Duration: 60 seconds

## Results

| Metric | Value |
|--------|-------|
| Total requests | ~19,500 |
| RPS | **371** |
| Avg response | 255ms |
| Tool call avg | 462ms |
| p50 | 98ms |
| Failures | **0%** |

## Conclusion

Python MCP core delivers **371 RPS with 0% failures** across 3 gateway pods on OCP.

## Steps to Reproduce

1. Prerequisites:
   - OCP cluster with CrunchyData PGO operator installed
   - CrunchyData PostgresCluster CR applied (see `crunchydata-postgres-cr.yaml`)
   - Local secrets file created from example (not committed to git)

2. Deploy (two-step for migration):
   ```bash
   helm install gp-context-forge charts/mcp-stack \
     -n <namespace> \
     -f charts/mcp-stack/values-ocp-pgo.yaml \
     -f charts/mcp-stack/values-ocp-pgo-secrets.yaml \
     --set mcpContextForge.replicaCount=1
   # Wait for gateway pod to be 1/1 Ready
   helm upgrade gp-context-forge charts/mcp-stack \
     -n <namespace> \
     -f charts/mcp-stack/values-ocp-pgo.yaml \
     -f charts/mcp-stack/values-ocp-pgo-secrets.yaml
   ```

3. Register MCP servers:
   ```bash
   POST /gateways  — register fast-test and fast-time servers
   POST /servers   — create virtual server
   ```

4. Run benchmark:
   ```bash
   curl -X POST http://locust:8089/swarm \
     -d 'user_count=125&spawn_rate=30&run_time=60s'
   ```
