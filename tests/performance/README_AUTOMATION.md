# Automated Performance Testing

Quick guide to using the automated, configuration-driven performance testing suite.

## Quick Start

```bash
# 1. Start services
make compose-up

# 2. Run automated tests with HTML report
cd tests/performance
./run-configurable.sh

# 3. View the auto-generated HTML report
# (opens automatically in browser on macOS/Linux)
```

## Features

### 🎯 Configuration-Driven
All test settings in `config.yaml`:
- Test profiles (smoke, light, medium, heavy)
- Test scenarios (which endpoints to test)
- SLO thresholds
- Monitoring options
- Report settings

### 📊 Automatic HTML Reports
- Beautiful, responsive design
- Interactive charts (Chart.js)
- SLO compliance visualization
- Performance recommendations
- System metrics graphs
- Single self-contained file

### 🔍 Built-in Monitoring
- CPU usage tracking
- Memory usage tracking
- Docker container stats
- Prometheus metrics collection
- Application log capture

### ⚙️ Flexible Execution
```bash
# Different profiles
./run-configurable.sh -p smoke     # 100 requests
./run-configurable.sh -p light     # 1K requests
./run-configurable.sh -p medium    # 10K requests (default)
./run-configurable.sh -p heavy     # 50K requests

# Specific scenarios only
./run-configurable.sh --scenario tools_benchmark

# Skip optional steps
./run-configurable.sh --skip-monitoring  # Faster
./run-configurable.sh --skip-report      # No HTML
./run-configurable.sh --skip-warmup      # No warmup

# Custom configuration
./run-configurable.sh -c my-config.yaml
```

## Configuration File

Edit `config.yaml` to customize tests:

```yaml
# Add new profile
profiles:
  custom:
    requests: 5000
    concurrency: 75
    duration: "45s"
    timeout: 60

# Add new test scenario
scenarios:
  my_benchmark:
    enabled: true
    description: "My custom tests"
    tests:
      - name: "my_test"
        payload: "payloads/my_test.json"
        endpoint: "/my-endpoint"

# Define SLOs
slos:
  my_test:
    p95_ms: 100
    min_rps: 200
    max_error_rate: 0.01
```

## Report Generator

Generate reports from existing results:

```bash
# Automatic (during test run)
./run-configurable.sh -p medium

# Manual generation
python3 utils/report_generator.py \
  --results-dir results_medium_20251009_143022 \
  --output reports/my_report.html \
  --config config.yaml \
  --profile medium
```

### Report Includes:
- ✅ Executive summary (overall health)
- ✅ SLO compliance table
- ✅ Test results by category
- ✅ Interactive latency charts
- ✅ System resource graphs
- ✅ Database performance metrics
- ✅ Automated recommendations
- ✅ Baseline comparisons

## Monitoring During Tests

The runner automatically collects:

1. **System Metrics** (every 5 seconds)
   - CPU percentage
   - Memory percentage
   - Saved to `system_metrics.csv`

2. **Docker Stats**
   - Per-container CPU/memory
   - Saved to `docker_stats.csv`

3. **Application Metrics**
   - Prometheus metrics snapshot
   - Saved to `prometheus_metrics.txt`

4. **Application Logs**
   - Last 1000 lines
   - Saved to `gateway_logs.txt`

## List Available Scenarios

```bash
./run-configurable.sh --list-scenarios
```

Output:
```
Available scenarios:
  - tools_benchmark
  - resources_benchmark
  - prompts_benchmark
  - gateway_core
  - mcp_server_direct
```

## Example Workflow

### Daily smoke test:
```bash
./run-configurable.sh -p smoke --skip-report
```

### Weekly comprehensive test:
```bash
./run-configurable.sh -p heavy > weekly_test.log 2>&1
```

### Pre-release validation:
```bash
# Run all scenarios with medium load
./run-configurable.sh -p medium

# Check SLO compliance in the HTML report
# Review recommendations
```

## CI/CD Integration

Add to GitHub Actions:

```yaml
name: Performance Tests

on:
  schedule:
    - cron: '0 2 * * 0'  # Weekly

jobs:
  perf-test:
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
          ./run-configurable.sh -p light

      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: performance-report
          path: tests/performance/reports/*.html

      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: performance-results
          path: tests/performance/results_*
```

## Troubleshooting

### Services not healthy
```bash
# Check status
docker compose ps

# Check logs
docker compose logs gateway

# Restart
make compose-down && make compose-up
```

### Authentication failed
```bash
# Regenerate token
./utils/setup-auth.sh

# Verify
source .auth_token
echo $MCPGATEWAY_BEARER_TOKEN
```

### Report not generated
```bash
# Check Python dependencies
pip install pyyaml

# Generate manually
python3 utils/report_generator.py \
  --results-dir results_medium_* \
  --output reports/test.html
```

### hey not found
```bash
# macOS
brew install hey

# Linux/WSL
go install github.com/rakyll/hey@latest

# Verify
which hey
```

## Files Generated

After a test run:

```
tests/performance/
├── results_medium_20251009_143022/
│   ├── tools_benchmark_list_tools_*.txt      # Hey output
│   ├── resources_benchmark_list_*.txt
│   ├── system_metrics.csv                     # CPU/memory
│   ├── docker_stats.csv                       # Container stats
│   ├── prometheus_metrics.txt                 # App metrics
│   └── gateway_logs.txt                       # Application logs
├── reports/
│   └── performance_report_medium_*.html       # HTML report
└── .auth_token                                # JWT token (gitignored)
```

## Best Practices

1. **Start with smoke tests** - Validate setup before running heavy tests
2. **Run medium profile regularly** - Good balance of coverage and speed
3. **Use heavy for stress testing** - Find breaking points
4. **Check reports for trends** - Watch for degradation over time
5. **Archive reports** - Keep historical data for comparison
6. **Review recommendations** - Act on high-priority items

## Next Steps

- Review the generated HTML report
- Compare results with SLOs in `config.yaml`
- Implement recommendations from the report
- Set up scheduled tests in CI/CD
- Establish baselines for comparison

For detailed strategy, see [PERFORMANCE_STRATEGY.md](PERFORMANCE_STRATEGY.md)
