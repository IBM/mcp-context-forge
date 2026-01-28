# MCP Gateway Performance Testing

Comprehensive performance testing suite for MCP Gateway with load testing, server profiling, infrastructure testing, and baseline comparison.

## Quick Start

```bash
make install          # Install dependencies (hey)
make test            # Run standard performance test
make test-gateway-core  # Test gateway internals
make test-database   # Test database connection pool
```

Results go to `results/{profile}_{timestamp}/`, reports to `reports/`.

## Common Commands

### Basic Testing
```bash
make test            # Standard test (10K requests, 50 concurrent)
make quick           # Quick smoke test (100 requests)
make heavy           # Heavy load (50K requests, 200 concurrent)
```

### New Comprehensive Tests
```bash
make test-gateway-core    # 11 gateway core tests (health, admin API, etc.)
make test-database        # 4 database connection pool tests
make test-all-scenarios   # Run all test scenarios
```

### Server Profiles
```bash
make test-optimized       # 8 workers, 2 threads - high throughput
make test-memory          # 4 workers, 8 threads - many connections
make test-io              # 6 workers, 50 DB pool - I/O heavy
```

### Infrastructure
```bash
make test-production      # 4 instances with nginx load balancer
make test-scaling         # Test with 4 instances
make compare-postgres     # Compare PostgreSQL 15 vs 17
```

### Plugins
```bash
make test-plugins         # 1000 calls per hook type, overall performance table
make test-plugins-details # 1000 calls per hook type, overall performance table, top-20 results
```

See [plugins profiling guide](PLUGIN_PROFILING.md) for detailed information.

### Baseline Management
```bash
make baseline             # Save current as baseline
make compare              # Compare with baseline
make list-baselines       # List all baselines

# Save specific results
make save-baseline BASELINE=my-test RESULTS=results/medium_20241010_123456
```

Plugins baseline management:
```bash
make baseline-plugins     # Save current plugin profiles directory as baseline
make compare-plugins      # Compare current plugin profiles with baseline"
```

### Cleanup
```bash
make clean                # Clean result files
make clean-results        # Remove all result directories
make clean-all            # Deep clean (results + baselines + reports)
```

## Available Profiles

### Load Profiles
| Profile | Requests | Concurrency | Use Case |
|---------|----------|-------------|----------|
| smoke | 100 | 5 | Quick validation |
| light | 1,000 | 10 | Fast testing |
| medium | 10,000 | 50 | Realistic load |
| heavy | 50,000 | 200 | Stress testing |

### Server Profiles
| Profile | Workers | Threads | DB Pool | Best For |
|---------|---------|---------|---------|----------|
| minimal | 1 | 2 | 5 | Dev/testing |
| standard | 4 | 4 | 20 | Balanced (default) |
| optimized | 8 | 2 | 30 | CPU-bound, high RPS |
| memory_optimized | 4 | 8 | 40 | Many connections |
| io_optimized | 6 | 4 | 50 | Database-heavy |

### Infrastructure Profiles
| Profile | Instances | PostgreSQL | nginx | Use Case |
|---------|-----------|------------|-------|----------|
| development | 1 | 17-alpine | No | Local dev |
| staging | 2 | 17-alpine | Yes | Pre-prod |
| production | 4 | 17-alpine | Yes | Production |
| production_ha | 6 | 17-alpine | Yes | High availability |

## Examples

### Find Optimal Configuration
```bash
# Test all server profiles
make test-minimal
make test-standard
make test-optimized

# Compare results, choose best cost/performance
```

### Plan Database Upgrade
```bash
# Compare PostgreSQL versions
make compare-postgres

# Or manually:
./run-advanced.sh -p medium --postgres-version 15-alpine --save-baseline pg15.json
./run-advanced.sh -p medium --postgres-version 17-alpine --compare-with pg15.json
```

### Capacity Planning
```bash
# Test different instance counts
./run-advanced.sh -p heavy --instances 1 --save-baseline 1x.json
./run-advanced.sh -p heavy --instances 4 --save-baseline 4x.json
./run-advanced.sh -p heavy --instances 8 --save-baseline 8x.json

# Compare to find optimal scaling point
```

### Regression Testing
```bash
# Before code changes
make baseline-production

# After changes
make compare

# Automatically fails if regressions detected
```

## Directory Structure

```
tests/performance/
├── Makefile              # 👈 Main entrypoint (start here)
├── README.md             # 👈 This file
├── PERFORMANCE_STRATEGY.md  # Complete testing strategy
├── config.yaml           # Configuration
│
├── run-advanced.sh       # Advanced runner with all features
├── run-configurable.sh   # Config-driven test execution
│
├── utils/
│   ├── generate_docker_compose.py  # Generate docker-compose + nginx
│   ├── compare_results.py          # Compare baselines
│   ├── baseline_manager.py         # Manage baselines
│   ├── report_generator.py         # HTML reports
│   ├── check-services.sh           # Health checks
│   └── setup-auth.sh               # JWT authentication
│
├── scenarios/
│   ├── tools-benchmark.sh          # MCP tools tests
│   ├── resources-benchmark.sh      # MCP resources tests
│   ├── prompts-benchmark.sh        # MCP prompts tests
│   ├── gateway-core-benchmark.sh   # 11 gateway core tests (NEW)
│   └── database-benchmark.sh       # 4 DB connection tests (NEW)
│
├── results/              # Test results (gitignored)
│   └── {profile}_{timestamp}/
├── baselines/            # Saved baselines (gitignored)
└── reports/              # HTML reports (gitignored)
```

## Advanced Usage

### Custom Results Location
```bash
# Override default results directory
RESULTS_BASE=/mnt/storage/perf make test
```

### Direct Runner
```bash
# Full control with run-advanced.sh
./run-advanced.sh -p medium \
  --server-profile optimized \
  --infrastructure production \
  --postgres-version 17-alpine \
  --instances 4 \
  --save-baseline prod_baseline.json
```

### Generate Docker Compose
```bash
# Generate custom docker-compose with nginx load balancer
./utils/generate_docker_compose.py \
  --infrastructure production \
  --server-profile optimized \
  --instances 4 \
  --output docker-compose.prod.yml

# Creates:
# - docker-compose.prod.yml (4 gateway instances + nginx)
# - nginx.conf (round-robin load balancer)
```

## Output

### Test Results
```
results/medium_standard_20241010_123456/
├── tools_benchmark_list_tools_medium_*.txt  # hey output
├── gateway_admin_list_tools_medium_*.txt    # Gateway tests
├── db_pool_stress_100_medium_*.txt          # DB tests
├── system_metrics.csv                        # CPU, memory
├── docker_stats.csv                          # Container stats
├── prometheus_metrics.txt                    # Metrics snapshot
└── gateway_logs.txt                          # Application logs
```

### Baselines
```json
{
  "version": "1.0",
  "created": "2025-10-10T00:11:09.675032",
  "metadata": {
    "profile": "medium",
    "server_profile": "optimized"
  },
  "results": {
    "tools_list_tools": {
      "rps": 822.45,
      "avg": 12.1,
      "p95": 18.9,
      "p99": 24.5,
      "error_rate": 0.0
    }
  }
}
```

## Configuration

Edit `config.yaml` to customize:
- Load profiles (requests, concurrency, timeouts)
- Server profiles (workers, threads, DB pool sizes)
- Infrastructure profiles (instances, PostgreSQL settings)
- SLO thresholds
- Monitoring options

## Troubleshooting

### Services Not Starting
```bash
make check                    # Check health
docker-compose logs gateway   # View logs
```

### Authentication Failed
```bash
./utils/setup-auth.sh         # Regenerate token
source .auth_token            # Load token
```

### Tests Timeout
```bash
# Tests now have proper timeouts:
# - make test: 600s (10 minutes)
# - make heavy: 1200s (20 minutes)
```

### Cleanup
```bash
make clean-results            # Remove old test runs
make clean-all                # Deep clean everything
```

## What's New (v2.1)

✅ **Timeout Handling** - Tests won't be killed prematurely
✅ **Graceful Shutdown** - Saves partial results on interrupt
✅ **Gateway Core Tests** - 11 new tests for gateway internals
✅ **Database Tests** - 4 new tests for connection pool behavior
✅ **Results Organization** - All results in `results/` subdirectory
✅ **nginx Load Balancer** - Auto-generated for multi-instance tests
✅ **Better Cleanup** - New make targets for cleanup

## Quick Reference

```bash
# List everything
make help                     # Show all commands
make list-profiles            # Show load/server/infra profiles
make list-baselines           # Show saved baselines

# Testing
make test                     # Standard test
make test-gateway-core        # Gateway tests (NEW)
make test-database            # DB tests (NEW)

# Comparison
make baseline                 # Save baseline
make compare                  # Compare with baseline

# Cleanup
make clean                    # Clean files
make clean-results            # Clean directories
```

## Documentation

- **This file** - Quick start and common commands
- **[PERFORMANCE_STRATEGY.md](PERFORMANCE_STRATEGY.md)** - Complete testing strategy, server profile guide, automation guide

---

**Ready?** Run `make test` or `make help`
