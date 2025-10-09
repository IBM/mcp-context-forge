# MCP Gateway Performance Testing Suite

**Version 2.0** - Complete performance testing with server profiles, infrastructure testing, and baseline comparison.

## Quick Start

```bash
# 1. Install dependencies
make install

# 2. Run standard test
make test

# 3. Run quick smoke test
make quick
```

That's it! Results are saved in `results_*/` and reports in `reports/`.

## What's Included

This comprehensive performance testing suite provides:

✅ **Load Testing** - Test with different request volumes (smoke → heavy)
✅ **Server Profiling** - Compare different Gunicorn worker/thread configurations
✅ **Infrastructure Testing** - Test complete environment setups (dev → production)
✅ **Database Comparison** - Compare PostgreSQL versions (15, 16, 17)
✅ **Horizontal Scaling** - Test with 1-8 gateway instances
✅ **Baseline Tracking** - Save and compare performance over time
✅ **Regression Detection** - Automatically detect performance degradation
✅ **HTML Reports** - Beautiful reports with charts and recommendations

## Common Commands

### Basic Testing

```bash
make test          # Standard medium load test
make quick         # Quick smoke test (100 requests)
make heavy         # Heavy load test (50K requests)
```

### Server Profile Testing

```bash
make test-optimized    # Test with 8 workers (high throughput)
make test-memory       # Test with 8 threads (many connections)
make test-io           # Test with optimized DB pools
```

### Infrastructure Testing

```bash
make test-production   # Test production infrastructure (4 instances)
make test-staging      # Test staging setup (2 instances)
make test-ha           # Test high-availability (6 instances)
```

### Database Comparison

```bash
make compare-postgres  # Compare PostgreSQL 15 vs 17
make test-pg17         # Test with PostgreSQL 17
```

### Baseline & Comparison

```bash
make baseline          # Save current results as baseline
make compare           # Compare with production baseline
make list-baselines    # List all saved baselines
```

## Documentation

| Document | Purpose |
|----------|---------|
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | Command cheat sheet and examples |
| **[SERVER_PROFILES_GUIDE.md](SERVER_PROFILES_GUIDE.md)** | Detailed server profile guide |
| **[PERFORMANCE_STRATEGY.md](PERFORMANCE_STRATEGY.md)** | Complete testing strategy |
| **[README_AUTOMATION.md](README_AUTOMATION.md)** | Automation and CI/CD guide |
| **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)** | Implementation details |

## Architecture

### Test Runners

```
make test
  └─> run-advanced.sh              (Main runner with all features)
       ├─> config.yaml              (Configuration)
       ├─> generate_docker_compose  (Infrastructure setup)
       ├─> run-configurable.sh      (Test execution)
       ├─> baseline_manager         (Baseline operations)
       ├─> compare_results          (Comparison)
       └─> report_generator         (HTML reports)
```

### Directory Structure

```
tests/performance/
├── Makefile                       # 👈 START HERE - Main entrypoint
├── README.md                      # 👈 This file
├── config.yaml                    # Configuration
│
├── run-advanced.sh                # Advanced runner (infrastructure, profiles)
├── run-configurable.sh            # Config-driven test execution
│
├── utils/
│   ├── generate_docker_compose.py # Generate docker-compose from profiles
│   ├── compare_results.py         # Compare baselines
│   ├── baseline_manager.py        # Manage baselines
│   ├── report_generator.py        # HTML reports
│   ├── check-services.sh          # Health checks
│   └── setup-auth.sh              # Authentication
│
├── scenarios/                     # Individual test scenarios
├── payloads/                      # Test payloads (JSON)
├── profiles/                      # Load profiles (light, medium, heavy)
├── baselines/                     # Saved baselines
└── reports/                       # Generated HTML reports
```

## Available Profiles

### Load Profiles

| Profile | Requests | Concurrency | Use Case |
|---------|----------|-------------|----------|
| **smoke** | 100 | 5 | Quick validation |
| **light** | 1,000 | 10 | Fast testing |
| **medium** | 10,000 | 50 | Realistic load (default) |
| **heavy** | 50,000 | 200 | Stress testing |

### Server Profiles

| Profile | Workers | Threads | DB Pool | Best For |
|---------|---------|---------|---------|----------|
| **minimal** | 1 | 2 | 5 | Small deployments |
| **standard** | 4 | 4 | 20 | Balanced (default) |
| **optimized** | 8 | 2 | 30 | CPU-bound, high throughput |
| **memory_optimized** | 4 | 8 | 40 | Many concurrent connections |
| **io_optimized** | 6 | 4 | 50 | Database-heavy workloads |

### Infrastructure Profiles

| Profile | Instances | PostgreSQL | Resources | Use Case |
|---------|-----------|------------|-----------|----------|
| **development** | 1 | 17 | Minimal | Local development |
| **staging** | 2 | 17 | Moderate | Pre-production |
| **production** | 4 | 17 | Optimized | Production |
| **production_ha** | 6 | 17 | High | High availability |

## Examples

### Example 1: Find Optimal Configuration

```bash
# Test different server profiles
make test-minimal
make test-standard
make test-optimized

# Compare results to find best cost/performance ratio
```

### Example 2: Plan Database Upgrade

```bash
# Compare PostgreSQL versions
make compare-postgres

# Review comparison report
cat results_*/comparison_*.json
```

### Example 3: Capacity Planning

```bash
# Test with different instance counts
make test-single              # 1 instance
make test-scaling             # 4 instances

# Determine how many instances needed for your load
```

### Example 4: Regression Testing

```bash
# Save baseline before changes
make baseline-production

# After code changes, compare
make compare

# Fails if regressions detected
```

## Complete Workflows

### Optimization Workflow

```bash
make workflow-optimize
```

This runs:
1. Baseline with standard configuration
2. Test with optimized configuration
3. Compare and generate recommendation

### Upgrade Workflow

```bash
make workflow-upgrade
```

This runs:
1. Baseline with current PostgreSQL version
2. Test with new version
3. Compare and show upgrade impact

### Capacity Planning Workflow

```bash
make workflow-capacity
```

This runs:
1. Test with 1, 2, 4 instances
2. Save all baselines
3. Compare to find optimal scaling

## Advanced Usage

### Direct Runner Access

```bash
# Use run-advanced.sh directly for more control
./run-advanced.sh -p medium --server-profile optimized --save-baseline my_test.json

# Compare with custom baseline
./run-advanced.sh -p medium --infrastructure production --compare-with my_test.json

# Test specific PostgreSQL version
./run-advanced.sh -p medium --postgres-version 16-alpine
```

### Custom Configuration

Edit `config.yaml` to:
- Add custom server profiles
- Define new infrastructure setups
- Adjust SLO thresholds
- Configure monitoring options

### Generate Docker Compose Manually

```bash
./utils/generate_docker_compose.py \
  --infrastructure production \
  --server-profile optimized \
  --instances 4 \
  --output my-docker-compose.yml
```

## Output & Reports

### Test Results

```
results_medium_optimized_20241009_123456/
├── tools_list_tools_medium_*.txt          # Individual test results
├── system_metrics.csv                      # CPU, memory over time
├── docker_stats.csv                        # Container resource usage
├── prometheus_metrics.txt                  # Application metrics
└── gateway_logs.txt                        # Application logs
```

### HTML Reports

```
reports/
└── performance_report_medium_20241009_123456.html
```

Reports include:
- Executive summary
- SLO compliance
- Interactive charts
- System metrics
- Automated recommendations

### Baselines

```
baselines/
├── production_baseline.json
├── pg15_comparison.json
└── current_baseline_20241009.json
```

## Troubleshooting

### Services Not Starting

```bash
make check                          # Check health
docker-compose logs gateway         # View logs
make clean && make test             # Clean and retry
```

### Authentication Issues

```bash
./utils/setup-auth.sh               # Regenerate token
source .auth_token                  # Load token
```

### hey Not Installed

```bash
make install                        # Install dependencies
```

### Results Not Generated

```bash
# Check services are running
make check

# Run with verbose output
./run-advanced.sh -p smoke --skip-report
```

## Tips & Best Practices

1. **Start small** - Use `make quick` to validate setup
2. **Save baselines** - Always use `--save-baseline` for future comparison
3. **Compare fairly** - Use same load profile when comparing configurations
4. **Monitor resources** - Check `system_metrics.csv` for bottlenecks
5. **Test incrementally** - Don't jump from light → heavy without testing medium
6. **Document decisions** - Save baselines with descriptive names

## Integration with CI/CD

See [README_AUTOMATION.md](README_AUTOMATION.md) for:
- GitHub Actions integration
- Scheduled performance tests
- Automated regression detection
- Performance dashboards

## Support & Resources

- **Quick Commands**: `make help`
- **List Profiles**: `make list-profiles`
- **Documentation**: `make docs`
- **Clean Results**: `make clean`

## What's New in v2.0

✨ **Server Profile Testing** - Test different worker/thread configurations
✨ **Infrastructure Profiles** - Complete environment testing (dev → production)
✨ **Database Comparison** - Compare PostgreSQL versions
✨ **Horizontal Scaling** - Test with multiple instances
✨ **Baseline Management** - Advanced baseline tracking and comparison
✨ **Makefile Entrypoint** - Simple `make test` commands
✨ **Regression Detection** - Automatic performance regression alerts
✨ **Cost-Benefit Analysis** - Recommendations based on resource usage

---

**Ready to start?** Run `make test` or `make help` for all available commands.
