# MCP Gateway Performance Testing Suite

Comprehensive performance testing framework for the MCP Gateway with fast-time-server integration.

## Overview

This suite provides structured performance testing for MCP Gateway operations including:

- **Tool Invocation**: Testing MCP tool discovery and execution performance
- **Resource Access**: Testing MCP resource listing and retrieval performance
- **Prompt Execution**: Testing MCP prompt discovery and execution performance
- **Mixed Workload**: Realistic concurrent workload patterns

## Quick Start

### Prerequisites

1. **Install `hey` HTTP load testing tool**:
   ```bash
   # macOS
   brew install hey

   # Linux/WSL
   go install github.com/rakyll/hey@latest

   # Or download prebuilt binary from:
   # https://github.com/rakyll/hey/releases
   ```

2. **Start the MCP Gateway stack**:
   ```bash
   make compose-up
   ```

3. **Wait for services to be healthy** (usually 30-60 seconds)

### Running Tests

```bash
# Run all tests with default (medium) profile
cd tests/performance
./run-all.sh

# Run with light profile for quick testing
./run-all.sh -p light

# Run only tool benchmarks
./run-all.sh --tools-only

# Run with heavy load
./run-all.sh -p heavy

# Skip setup steps if services are already running
SKIP_SETUP=true ./run-all.sh
```

## Directory Structure

```
tests/performance/
├── README.md                    # This file
├── run-all.sh                   # Main test runner
├── payloads/                    # Test payloads for various scenarios
│   ├── tools/
│   │   ├── get_system_time.json
│   │   ├── convert_time.json
│   │   └── list_tools.json
│   ├── resources/
│   │   ├── list_resources.json
│   │   ├── read_timezone_info.json
│   │   └── read_world_times.json
│   └── prompts/
│       ├── list_prompts.json
│       └── get_compare_timezones.json
├── scenarios/                   # Individual test scenarios
│   ├── tools-benchmark.sh       # Tool invocation tests
│   ├── resources-benchmark.sh   # Resource access tests
│   ├── prompts-benchmark.sh     # Prompt execution tests
│   └── mixed-workload.sh        # Combined concurrent tests
├── profiles/                    # Load profiles
│   ├── light.env                # Light load (1K requests, 10 concurrent)
│   ├── medium.env               # Medium load (10K requests, 50 concurrent)
│   └── heavy.env                # Heavy load (50K requests, 200 concurrent)
├── utils/                       # Helper scripts
│   ├── setup-auth.sh            # JWT token generation
│   └── check-services.sh        # Service health verification
└── results/                     # Test results (auto-generated)
    ├── tools_*.txt              # Tool benchmark results
    ├── resources_*.txt          # Resource benchmark results
    ├── prompts_*.txt            # Prompt benchmark results
    └── summary_*.md             # Summary reports
```

## Load Profiles

### Light Profile (Quick Testing)
```bash
REQUESTS=1000
CONCURRENCY=10
DURATION=10s
TIMEOUT=30
```

Use for: Quick smoke tests, development verification

### Medium Profile (Realistic Testing)
```bash
REQUESTS=10000
CONCURRENCY=50
DURATION=30s
TIMEOUT=60
```

Use for: Realistic load simulation, baseline measurements

### Heavy Profile (Stress Testing)
```bash
REQUESTS=50000
CONCURRENCY=200
DURATION=60s
TIMEOUT=60
```

Use for: Stress testing, capacity planning, finding bottlenecks

## Test Scenarios

### 1. Tool Invocation Benchmarks

Tests MCP tool operations through the gateway:

```bash
./scenarios/tools-benchmark.sh
```

**Tests:**
- `list_tools` - Tool discovery performance
- `get_system_time` - Simple tool invocation
- `convert_time` - Complex tool with multiple parameters

**Metrics:**
- Request throughput (requests/sec)
- Response time (p50, p95, p99)
- Error rate
- Latency distribution

### 2. Resource Access Benchmarks

Tests MCP resource operations:

```bash
./scenarios/resources-benchmark.sh
```

**Tests:**
- `list_resources` - Resource discovery
- `read_timezone_info` - Static resource access
- `read_world_times` - Dynamic resource access

### 3. Prompt Execution Benchmarks

Tests MCP prompt operations:

```bash
./scenarios/prompts-benchmark.sh
```

**Tests:**
- `list_prompts` - Prompt discovery
- `get_compare_timezones` - Prompt with arguments

### 4. Mixed Workload Benchmark

Simulates realistic concurrent usage:

```bash
./scenarios/mixed-workload.sh
```

Runs all test types concurrently to simulate real-world usage patterns.

## Understanding Results

### Sample Output

```
Summary:
  Total:        15.2340 secs
  Slowest:      0.0856 secs
  Fastest:      0.0012 secs
  Average:      0.0152 secs
  Requests/sec: 656.28

Response time histogram:
  0.001 [1]     |
  0.010 [4523]  |■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
  0.018 [3247]  |■■■■■■■■■■■■■■■■■■■■■■■■■■■■
  0.027 [1456]  |■■■■■■■■■■■■■
  0.035 [542]   |■■■■■
  0.044 [187]   |■■
  0.052 [34]    |
  0.061 [8]     |
  0.069 [2]     |

Status code distribution:
  [200] 10000 responses
```

### Key Metrics

- **Requests/sec**: Throughput - higher is better
- **Average**: Mean response time - lower is better
- **p50/p95/p99**: Percentile response times - lower is better
- **Status codes**: Should be 100% 200s for successful tests

### Interpreting Results

**Good Performance:**
- Tools: >500 req/s, <20ms average
- Resources: >800 req/s, <15ms average
- Prompts: >400 req/s, <25ms average

**Warning Signs:**
- Error rate >1%
- p99 >200ms
- Significant variance between p50 and p99
- Status codes other than 200

## Advanced Usage

### Custom Profiles

Create custom profile in `profiles/custom.env`:

```bash
REQUESTS=25000
CONCURRENCY=100
DURATION=45s
TIMEOUT=60
```

Run with:
```bash
./run-all.sh -p custom
```

### Manual Test Execution

Run individual scenarios directly:

```bash
# Set up environment
export PROFILE=medium
export GATEWAY_URL=http://localhost:4444

# Generate auth token
./utils/setup-auth.sh

# Source the token
source .auth_token

# Run specific test
./scenarios/tools-benchmark.sh
```

### Testing Remote Gateways

```bash
./run-all.sh -u https://gateway.example.com
```

### Parallel Test Execution

The `mixed-workload.sh` script demonstrates concurrent execution:

```bash
# All tests run simultaneously
./scenarios/mixed-workload.sh
```

## Troubleshooting

### Services Not Healthy

```bash
# Check docker compose status
docker compose ps

# Check logs
docker compose logs gateway
docker compose logs fast_time_server

# Restart services
make compose-down
make compose-up
```

### Authentication Failures

```bash
# Regenerate token
./utils/setup-auth.sh

# Verify token
source .auth_token
echo $MCPGATEWAY_BEARER_TOKEN

# Test manually
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
  http://localhost:4444/health
```

### `hey` Not Found

```bash
# Install hey
brew install hey  # macOS
go install github.com/rakyll/hey@latest  # Go

# Verify installation
which hey
hey -version
```

### Port Conflicts

```bash
# Check if ports are in use
lsof -i :4444  # Gateway
lsof -i :8888  # Fast-time-server

# Modify docker-compose.yml if needed
```

## Integration with CI/CD

### Example GitHub Actions

```yaml
name: Performance Tests

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0'  # Weekly

jobs:
  performance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install hey
        run: go install github.com/rakyll/hey@latest

      - name: Start services
        run: make compose-up

      - name: Run performance tests
        run: |
          cd tests/performance
          ./run-all.sh -p light

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: performance-results
          path: tests/performance/results/
```

## Performance Baselines

Track performance over time by saving baseline results:

```bash
# Save current results as baseline
cp results/summary_medium_*.md baselines/baseline_$(date +%Y%m%d).md

# Compare with baseline
diff baselines/baseline_20250101.md results/summary_medium_*.md
```

## Best Practices

1. **Always run tests with services at idle** - Don't run during active development
2. **Use consistent profiles** - Compare results from same profile
3. **Run multiple iterations** - Single runs can be noisy
4. **Monitor system resources** - Check CPU, memory, network during tests
5. **Establish baselines** - Track performance over time
6. **Test in production-like environment** - Results vary by hardware

## Contributing

To add new test scenarios:

1. Create payload in `payloads/{category}/`
2. Add test case to scenario script
3. Update documentation
4. Test with all profiles

## Support

For issues or questions:

- Check existing test results in `results/`
- Review service logs: `docker compose logs`
- Verify service health: `./utils/check-services.sh`
- Check authentication: `./utils/setup-auth.sh`

## License

Part of the MCP Context Forge project.
