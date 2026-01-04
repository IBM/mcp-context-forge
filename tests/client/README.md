# HTTPX Client Benchmarks

Benchmark suite for testing HTTPX client performance patterns, connection pooling,
and optimal configuration for high-concurrency MCP Gateway deployments.

## Overview

These benchmarks help determine:

1. **Optimal connection pool settings** for your workload
2. **Performance difference** between per-request vs shared clients
3. **Concurrency sweet spots** for maximum throughput
4. **HTTP/2 benefits** (or lack thereof) for your use case

## Quick Start

```bash
# Start a test server (e.g., fast-time-server)
./fast-time-server -transport=dual -port 8101

# Run a quick benchmark
make benchmark

# Run comprehensive sweep
make sweep

# Run with custom settings
make benchmark URL=http://localhost:8101/health DURATION=60 CONCURRENCY=500
```

## Benchmark Scripts

### `benchmark_httpx.py` - Single Pattern Benchmark

Run a specific benchmark pattern with configurable parameters.

```bash
# Basic usage
python benchmark_httpx.py --url http://localhost:8101/health

# High concurrency test
python benchmark_httpx.py --url http://localhost:8101/health \
    --duration 120 \
    --concurrency 1000 \
    --max-connections 500

# Run all patterns
python benchmark_httpx.py --pattern all --duration 30

# JSON output
python benchmark_httpx.py --output json
```

**Available Patterns:**

| Pattern | Description |
|---------|-------------|
| `per_request` | Creates new httpx.AsyncClient per request (anti-pattern) |
| `shared_no_limits` | Shared client without httpx.Limits |
| `shared_with_limits` | Shared client with configurable Limits (recommended) |
| `http2` | HTTP/2 with shared client and Limits |
| `all` | Run all patterns for comparison |

### `benchmark_sweep.py` - Concurrency Sweep

Automatically tests multiple concurrency/connection combinations to find optimal settings.

```bash
# Default sweep (10 levels, ~5 minutes)
python benchmark_sweep.py --url http://localhost:8101/health

# Quick sweep (3 levels)
python benchmark_sweep.py --quick

# Custom levels
python benchmark_sweep.py --levels "100:100,500:200,1000:500"

# Save results
python benchmark_sweep.py --output results.csv
python benchmark_sweep.py --output results.json
```

**Default Sweep Levels:**

| Concurrency | Max Connections |
|-------------|-----------------|
| 10 | 50 |
| 50 | 100 |
| 100 | 100 |
| 200 | 200 |
| 500 | 200 |
| 500 | 500 |
| 1000 | 500 |
| 1000 | 1000 |
| 2000 | 1000 |
| 3000 | 1000 |

## Environment Variables

All scripts support configuration via environment variables:

```bash
export BENCHMARK_URL=http://localhost:8101/health
export BENCHMARK_DURATION=30
export BENCHMARK_CONCURRENCY=100
export BENCHMARK_MAX_CONNECTIONS=100
export BENCHMARK_MAX_KEEPALIVE=50
```

## Makefile Targets

```bash
make benchmark          # Run single benchmark with defaults
make sweep              # Run concurrency sweep
make sweep-quick        # Quick 3-level sweep
make benchmark-all      # Run all patterns
make benchmark-json     # Output results as JSON
make help               # Show all targets
```

## Sample Results

### Benchmark Output

```
================================================================================
RESULT: shared_c500_l200
================================================================================
  Total Requests:      84,976
  Successful:          84,976
  Failed:              0
  Duration:            121.26s
  Throughput:          700.8 req/s
  Avg Latency:         709.82ms
  P50 Latency:         393.14ms
  P95 Latency:         1790.87ms
  P99 Latency:         6779.09ms
  Max Latency:         32687.63ms
```

### Sweep Summary

```
================================================================================
CONCURRENCY SWEEP RESULTS
================================================================================
Pattern                              Requests          RPS    Avg(ms)    P50(ms)    P99(ms)    Max(ms)   Success%
------------------------------------------------------------------------------------------------------------------------
shared_c100_l100                       45,231       1,507.7       6.51       5.12      15.23      89.12     100.0%
shared_c500_l200                       84,976         700.8     709.82     393.14    6779.09   32687.63     100.0%
shared_c1000_l500                      59,282         464.3    2109.22    1128.15   31836.61   44382.89     100.0%
shared_c3000_l1000                     40,812         252.0    9835.22    6518.99   48333.05  100931.56     100.0%

------------------------------------------------------------------------------------------------------------------------
BEST: shared_c100_l100 with 1,507.7 RPS
```

## Key Findings

Based on extensive benchmarking:

1. **Per-request client is ~20x slower** than shared pooled client
2. **Optimal concurrency != maximum concurrency**
   - c=500/l=200 achieved 700 RPS
   - c=3000/l=1000 only achieved 252 RPS
3. **HTTP/2 provides minimal benefit** for localhost connections
4. **P99 latency explodes at high concurrency**: 6.8s at c=500 → 48s at c=3000

## Recommended Configuration

Based on benchmarks, for MCP Gateway:

```bash
# Optimal for high-throughput
HTTPX_MAX_CONNECTIONS=200
HTTPX_MAX_KEEPALIVE_CONNECTIONS=100
HTTPX_KEEPALIVE_EXPIRY=30.0
HTTPX_CONNECT_TIMEOUT=5.0
HTTPX_READ_TIMEOUT=120.0  # High for slow MCP tool calls
HTTPX_POOL_TIMEOUT=10.0   # Fail fast on pool exhaustion
```

### Tuning Guidelines

| Expected Load | max_connections | max_keepalive | Expected RPS |
|---------------|-----------------|---------------|--------------|
| Low (10-50) | 100 | 50 | ~1,500+ |
| Medium (50-200) | 200 | 100 | ~700-1,500 |
| High (200-500) | 300 | 150 | ~500-700 |
| Very High (500+) | 500 | 250 | ~300-500 |

## Integration with CI/CD

```yaml
# Example GitHub Actions workflow
- name: Run HTTPX Benchmarks
  run: |
    cd tests/client
    make benchmark-json > benchmark-results.json

- name: Upload Results
  uses: actions/upload-artifact@v4
  with:
    name: benchmark-results
    path: tests/client/benchmark-results.json
```

## Troubleshooting

### "Cannot connect to URL"

Ensure your test server is running:

```bash
# Start fast-time-server
./fast-time-server -transport=dual -port 8101

# Or start MCP Gateway
make dev
```

### High Error Rate

Check for:
- File descriptor limits: `ulimit -n`
- System connection limits: `sysctl net.core.somaxconn`
- Target server capacity

### Slow Per-Request Pattern

This is expected! The per-request pattern is intentionally slow to demonstrate
the anti-pattern. Limit concurrency to avoid system overload:

```bash
python benchmark_httpx.py --pattern per_request --concurrency 50
```

## Related Documentation

- [Issue #1897](https://github.com/IBM/mcp-context-forge/issues/1897) - MCP client connection exhaustion
- [todo/configurable-httpx.md](../../todo/configurable-httpx.md) - Full analysis and solution proposal
- [HTTPX Connection Pooling](https://www.python-httpx.org/advanced/#pool-limits)
