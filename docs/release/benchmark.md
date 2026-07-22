# Benchmark Results

This file tracks benchmark results by release for local performance runs for developers reference only.

## Release 1.0.6

### Environment

- Run type: local machine
- Local load test command: `make load-test LOADTEST_USERS=200 LOADTEST_SPAWN_RATE=20 LOADTEST_RUN_TIME=10m`
- MCP tools benchmark commands: `make testing-up && make benchmark-mcp-tools`

### Results

| Metric | Local Load Test | MCP Benchmark: `benchmark-mcp-tools` |
|---|---:|---:|
| Command | `make load-test LOADTEST_USERS=200 LOADTEST_SPAWN_RATE=20 LOADTEST_RUN_TIME=10m` | `make testing-up && make benchmark-mcp-tools` |
| Concurrent users | 200 | - |
| Ramp up | 20 | - |
| Duration | 10 minutes | 60s |
| Total Requests | 6,128 | 5,460 |
| Total Failures | 480 (7.83%) | 1,723 (31.56%) |
| Requests/sec (RPS) | 20.45 | 91.21 |
| Average Response Time (ms) | 6306.41 | 1066.94 |
| Min Response Time (ms) | 3.68 | 13.11 |
| Max Response Time (ms) | 85570.12 | 30005.24 |
| Median / p50 (ms) | 1100.00 | 230.00 |
| p90 (ms) | 21000.00 | 3500.00 |
| p95 (ms) | 30000.00 | 5800.00 |
| p99 (ms) | 30000.00 | 13000.00 |
