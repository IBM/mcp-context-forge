# Performance Testing Quick Reference

Fast reference for common performance testing commands.

## Basic Testing

```bash
# Simple test with defaults
./run-configurable.sh

# Test with different load profile
./run-configurable.sh -p light    # Quick test
./run-configurable.sh -p medium   # Default
./run-configurable.sh -p heavy    # Stress test
```

## Server Profile Testing

```bash
# Test with minimal resources
./run-advanced.sh -p medium --server-profile minimal

# Test with optimized configuration
./run-advanced.sh -p medium --server-profile optimized

# Test with I/O optimized profile
./run-advanced.sh -p heavy --server-profile io_optimized

# List available server profiles
./run-advanced.sh --list-server-profiles
```

## Infrastructure Testing

```bash
# Test development infrastructure
./run-advanced.sh -p medium --infrastructure development

# Test production infrastructure
./run-advanced.sh -p heavy --infrastructure production

# Test high-availability setup
./run-advanced.sh -p heavy --infrastructure production_ha

# List available infrastructure profiles
./run-advanced.sh --list-infrastructure
```

## PostgreSQL Version Comparison

```bash
# Test PostgreSQL 15
./run-advanced.sh -p medium --postgres-version 15-alpine --save-baseline pg15.json

# Test PostgreSQL 17 and compare
./run-advanced.sh -p medium --postgres-version 17-alpine --compare-with pg15.json
```

## Horizontal Scaling

```bash
# Test with 1 instance (baseline)
./run-advanced.sh -p heavy --instances 1 --save-baseline single.json

# Test with 4 instances and compare
./run-advanced.sh -p heavy --instances 4 --compare-with single.json
```

## Baseline Management

```bash
# Save current run as baseline
./run-advanced.sh -p medium --save-baseline production_baseline.json

# Run test and compare with baseline
./run-advanced.sh -p medium --compare-with production_baseline.json

# List all baselines
./utils/baseline_manager.py list --dir baselines

# View baseline details
./utils/baseline_manager.py load baselines/production_baseline.json
```

## Comparison & Analysis

```bash
# Compare two test runs
./utils/compare_results.py \
  baselines/pg15_baseline.json \
  baselines/pg17_baseline.json

# Fail build if regressions detected
./utils/compare_results.py \
  baselines/production.json \
  baselines/current.json \
  --fail-on-regression
```

## Docker Compose Generation

```bash
# Generate docker-compose for production infrastructure
./utils/generate_docker_compose.py \
  --infrastructure production \
  --server-profile optimized \
  --output docker-compose.prod.yml

# Generate with custom PostgreSQL version
./utils/generate_docker_compose.py \
  --infrastructure staging \
  --postgres-version 16-alpine \
  --output docker-compose.staging.yml

# Generate with multiple instances
./utils/generate_docker_compose.py \
  --infrastructure production \
  --instances 4 \
  --output docker-compose.scaled.yml
```

## Common Workflows

### 1. Find Optimal Server Profile

```bash
# Test all profiles and compare
for profile in minimal standard optimized memory_optimized io_optimized; do
  ./run-advanced.sh -p medium \
    --server-profile $profile \
    --save-baseline ${profile}_baseline.json
done

# Review results and choose best cost/performance ratio
```

### 2. Evaluate Database Upgrade

```bash
# Baseline with current version
./run-advanced.sh -p medium \
  --postgres-version 15-alpine \
  --save-baseline pg15_production.json

# Test with new version
./run-advanced.sh -p medium \
  --postgres-version 17-alpine \
  --compare-with pg15_production.json
```

### 3. Plan Capacity

```bash
# Test different instance counts
for instances in 1 2 4 8; do
  ./run-advanced.sh -p heavy \
    --instances $instances \
    --save-baseline ${instances}x_baseline.json
done

# Compare results to find optimal scaling point
```

### 4. Regression Testing

```bash
# Save production baseline
./run-advanced.sh -p medium \
  --infrastructure production \
  --save-baseline production_v1.2.0.json

# After code changes, compare
./run-advanced.sh -p medium \
  --infrastructure production \
  --compare-with production_v1.2.0.json \
  --fail-on-regression
```

## Flags Reference

### Load Profiles
- `-p smoke` - 100 requests, 5 concurrent
- `-p light` - 1K requests, 10 concurrent
- `-p medium` - 10K requests, 50 concurrent (default)
- `-p heavy` - 50K requests, 200 concurrent

### Server Profiles
- `--server-profile minimal` - 1 worker, 2 threads
- `--server-profile standard` - 4 workers, 4 threads (default)
- `--server-profile optimized` - 8 workers, 2 threads
- `--server-profile memory_optimized` - 4 workers, 8 threads
- `--server-profile io_optimized` - 6 workers, 4 threads

### Infrastructure Profiles
- `--infrastructure development` - 1 instance, minimal resources
- `--infrastructure staging` - 2 instances, moderate resources
- `--infrastructure production` - 4 instances, optimized
- `--infrastructure production_ha` - 6 instances, HA setup

### Control Flags
- `--skip-setup` - Skip health checks and auth
- `--skip-monitoring` - Skip system monitoring
- `--skip-report` - Skip HTML report generation
- `--no-restore` - Don't restore original docker-compose

## Environment Variables

```bash
# Override defaults
export PROFILE=heavy
export SERVER_PROFILE=optimized
export SKIP_MONITORING=true

# Run with overrides
./run-advanced.sh
```

## Troubleshooting

```bash
# Services not starting
docker-compose ps
docker-compose logs gateway postgres

# Restore original configuration
cp docker-compose.backup_*.yml docker-compose.yml
docker-compose down && docker-compose up -d

# Check service health
./utils/check-services.sh

# Regenerate authentication
./utils/setup-auth.sh
```

## Tips

1. **Always save baselines** - Use `--save-baseline` for future comparison
2. **Test incrementally** - Start with light profile, then increase load
3. **Monitor resources** - Watch CPU/memory during tests
4. **Compare fairly** - Use same load profile when comparing configurations
5. **Document decisions** - Save baselines with descriptive names

## Examples from Real Scenarios

### Scenario: "My API is slow, how do I optimize?"

```bash
# 1. Baseline current performance
./run-advanced.sh -p medium --save-baseline current.json

# 2. Test with optimized server profile
./run-advanced.sh -p medium \
  --server-profile optimized \
  --compare-with current.json

# 3. If improvement is good, test with heavier load
./run-advanced.sh -p heavy \
  --server-profile optimized \
  --save-baseline optimized_production.json
```

### Scenario: "Should I upgrade PostgreSQL?"

```bash
# Current version
./run-advanced.sh -p medium \
  --postgres-version 15-alpine \
  --save-baseline pg15.json

# New version
./run-advanced.sh -p medium \
  --postgres-version 17-alpine \
  --compare-with pg15.json

# Review comparison report for upgrade decision
```

### Scenario: "How many instances do I need for 1M requests/day?"

```bash
# Test with increasing instance counts
./run-advanced.sh -p heavy --instances 1 --save-baseline 1x.json
./run-advanced.sh -p heavy --instances 2 --save-baseline 2x.json
./run-advanced.sh -p heavy --instances 4 --save-baseline 4x.json

# Calculate: 1M requests/day ≈ 11.6 req/sec average
# Use peak multiplier (e.g., 10x) = 116 req/sec needed
# Choose instance count that sustains >116 req/sec
```

For detailed documentation, see:
- [PERFORMANCE_STRATEGY.md](PERFORMANCE_STRATEGY.md) - Complete strategy
- [SERVER_PROFILES_GUIDE.md](SERVER_PROFILES_GUIDE.md) - Detailed profile guide
- [README_AUTOMATION.md](README_AUTOMATION.md) - Automation guide
