# Server Profile & Infrastructure Testing Guide

Complete guide to testing different server configurations, infrastructure profiles, and comparing database versions.

## Table of Contents

1. [Overview](#overview)
2. [Server Profiles](#server-profiles)
3. [Infrastructure Profiles](#infrastructure-profiles)
4. [Database Version Comparison](#database-version-comparison)
5. [Horizontal Scaling Tests](#horizontal-scaling-tests)
6. [Configuration Matrix Testing](#configuration-matrix-testing)
7. [Comparison & Analysis](#comparison--analysis)
8. [Examples](#examples)

---

## Overview

Performance varies significantly based on:
- **Server configuration** - Workers, threads, connection pools
- **Infrastructure setup** - Number of instances, database settings
- **Database version** - PostgreSQL 15 vs 16 vs 17
- **Scaling strategy** - Horizontal scaling (multiple instances)

This guide shows how to test and compare all these configurations.

---

## Server Profiles

Server profiles define **application-level settings** like Gunicorn workers, threads, and database connection pools.

### Available Profiles

**Defined in `config.yaml`:**

| Profile | Workers | Threads | DB Pool | Best For |
|---------|---------|---------|---------|----------|
| **minimal** | 1 | 2 | 5 | Small deployments, low traffic |
| **standard** | 4 | 4 | 20 | Balanced production setup |
| **optimized** | 8 | 2 | 30 | CPU-bound, high throughput |
| **memory_optimized** | 4 | 8 | 40 | Many concurrent connections |
| **io_optimized** | 6 | 4 | 50 | Database-heavy workloads |

### Testing a Single Server Profile

```bash
# Test with standard profile (default)
./run-configurable.sh -p medium --server-profile standard

# Test with optimized profile
./run-configurable.sh -p medium --server-profile optimized

# Test with minimal resources
./run-configurable.sh -p medium --server-profile minimal
```

### Comparing Server Profiles

```bash
# 1. Run baseline with minimal profile
./run-configurable.sh -p medium \
  --server-profile minimal \
  --save-baseline minimal_baseline.json

# 2. Test optimized profile and compare
./run-configurable.sh -p medium \
  --server-profile optimized \
  --compare-with minimal_baseline.json

# Output includes:
# - Throughput improvement: +125%
# - Latency reduction: -35%
# - Resource usage increase: CPU +50%, Memory +30%
```

### How Server Profiles Work

Server profiles set environment variables before starting the gateway:

```bash
# For "optimized" profile, these are set:
export GUNICORN_WORKERS=8
export GUNICORN_THREADS=2
export GUNICORN_TIMEOUT=120
export DB_POOL_SIZE=30
export DB_POOL_MAX_OVERFLOW=60
export REDIS_POOL_SIZE=20

# Then gateway is restarted with new config
docker-compose restart gateway
```

### Custom Server Profile

Add to `config.yaml`:

```yaml
server_profiles:
  my_custom:
    description: "Custom tuned for my workload"
    gunicorn_workers: 6
    gunicorn_threads: 3
    gunicorn_timeout: 90
    db_pool_size: 25
    db_pool_max_overflow: 50
    redis_pool_size: 15
```

Use it:
```bash
./run-configurable.sh -p medium --server-profile my_custom
```

---

## Infrastructure Profiles

Infrastructure profiles define **entire environment configurations** including database version, number of gateway instances, PostgreSQL tuning, and Redis settings.

### Available Profiles

**Defined in `config.yaml`:**

| Profile | Instances | PostgreSQL | DB Shared Buffers | Redis | Best For |
|---------|-----------|------------|-------------------|-------|----------|
| **development** | 1 | 17 | 128MB | Disabled | Local development |
| **staging** | 2 | 17 | 512MB | 256MB | Pre-production testing |
| **production** | 4 | 17 | 2GB | 1GB | Production deployment |
| **production_ha** | 6 | 17 | 4GB | 2GB | High-availability production |

### Testing Infrastructure Profiles

```bash
# Test with development infrastructure
./run-configurable.sh -p medium --infrastructure development

# Test with production infrastructure
./run-configurable.sh -p medium --infrastructure production

# Test with HA infrastructure
./run-configurable.sh -p medium --infrastructure production_ha
```

### How Infrastructure Profiles Work

Infrastructure profiles **dynamically generate a new docker-compose.yml**:

```yaml
# For "production" profile, generates:
services:
  postgres:
    image: postgres:17-alpine
    command:
      - "-c"
      - "shared_buffers=2GB"
      - "-c"
      - "effective_cache_size=6GB"
      - "-c"
      - "max_connections=200"

  gateway:
    deploy:
      replicas: 4  # 4 instances

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
```

**Process:**
1. Backup current `docker-compose.yml`
2. Generate new compose file from infrastructure profile
3. Stop all services (`docker-compose down`)
4. Start services with new config (`docker-compose up -d`)
5. Wait for health checks
6. Run performance tests
7. Optionally restore original config

### Comparing Infrastructure Profiles

```bash
# Compare development vs production infrastructure
./compare-infrastructure.sh \
  --profiles development,staging,production \
  --load-profile medium \
  --output infrastructure_comparison.html
```

This runs tests against each infrastructure and generates a comparison report.

### Custom Infrastructure Profile

Add to `config.yaml`:

```yaml
infrastructure_profiles:
  my_cloud:
    description: "Cloud-optimized setup"
    gateway_instances: 3
    postgres_version: "17-alpine"
    postgres_shared_buffers: "1GB"
    postgres_effective_cache_size: "4GB"
    postgres_max_connections: 150
    postgres_random_page_cost: 1.1  # SSD
    redis_enabled: true
    redis_maxmemory: "512mb"
```

---

## Database Version Comparison

Test performance across different PostgreSQL versions to evaluate upgrade impact.

### Configuration

Enable in `config.yaml`:

```yaml
database_comparison:
  enabled: true
  versions:
    - version: "15-alpine"
      label: "PostgreSQL 15"
    - version: "16-alpine"
      label: "PostgreSQL 16"
    - version: "17-alpine"
      label: "PostgreSQL 17"

  common_config:
    shared_buffers: "512MB"
    effective_cache_size: "2GB"
    max_connections: 100
```

### Run Comparison

```bash
# Test all PostgreSQL versions
./run-configurable.sh -p medium --database-comparison

# Output:
# Running tests with PostgreSQL 15...
# Running tests with PostgreSQL 16...
# Running tests with PostgreSQL 17...
# Generating comparison report...
```

### Comparison Report

The report shows side-by-side metrics:

| Metric | PostgreSQL 15 | PostgreSQL 16 | PostgreSQL 17 |
|--------|---------------|---------------|---------------|
| Throughput | 650 rps | 680 rps (+5%) | 720 rps (+11%) |
| p95 Latency | 42ms | 39ms (-7%) | 35ms (-17%) |
| Query Time | 8.2ms | 7.8ms (-5%) | 7.1ms (-13%) |
| Connections | 45 avg | 43 avg | 41 avg |

**Recommendation**: Upgrade to PostgreSQL 17 for 11% throughput improvement and 17% latency reduction.

### Manual Database Version Testing

```bash
# Test with PostgreSQL 15
./run-configurable.sh -p medium --postgres-version 15-alpine

# Test with PostgreSQL 16
./run-configurable.sh -p medium --postgres-version 16-alpine

# Test with PostgreSQL 17
./run-configurable.sh -p medium --postgres-version 17-alpine
```

---

## Horizontal Scaling Tests

Test how performance improves with multiple gateway instances.

### Configuration

Enable in `config.yaml`:

```yaml
scaling_tests:
  enabled: true
  configurations:
    - instances: 1
      description: "Single instance baseline"
    - instances: 2
      description: "Dual instance"
    - instances: 4
      description: "Quad instance"
    - instances: 8
      description: "Eight instance scale-out"

  load_balancer:
    algorithm: "round_robin"
    health_check_interval: 10
```

### Run Scaling Tests

```bash
# Test horizontal scaling
./run-configurable.sh -p heavy --scaling-test

# Output:
# Testing with 1 instance... 500 rps
# Testing with 2 instances... 950 rps (1.9x)
# Testing with 4 instances... 1850 rps (3.7x)
# Testing with 8 instances... 3200 rps (6.4x)
```

### Scaling Efficiency Analysis

The report includes scaling efficiency:

| Instances | Throughput | Scaling Factor | Efficiency |
|-----------|------------|----------------|------------|
| 1 | 500 rps | 1.0x | 100% |
| 2 | 950 rps | 1.9x | 95% |
| 4 | 1850 rps | 3.7x | 92.5% |
| 8 | 3200 rps | 6.4x | 80% |

**Analysis**:
- Near-linear scaling up to 4 instances (92.5% efficiency)
- Diminishing returns at 8 instances (80% efficiency)
- Bottleneck likely at database or network layer
- Recommendation: Use 4 instances for optimal cost/performance

### Manual Scaling Test

```bash
# Test with 2 instances
./run-configurable.sh -p heavy --instances 2

# Test with 4 instances
./run-configurable.sh -p heavy --instances 4
```

---

## Configuration Matrix Testing

Test combinations of configuration parameters to find optimal settings.

### Strategies

**1. One-Factor-at-a-Time (OFAT)**
- Vary one parameter while keeping others constant
- Fast and simple
- Good for initial optimization

**2. Full Factorial**
- Test all combinations
- Exhaustive but time-consuming
- 4 workers × 3 threads × 4 pool sizes = 48 tests

**3. Latin Hypercube Sampling**
- Statistical sampling for representative coverage
- Much faster than full factorial
- Still provides good optimization results

### Configuration

Enable in `config.yaml`:

```yaml
configuration_matrix:
  enabled: true
  strategy: "one_factor_at_a_time"

  variables:
    gunicorn_workers:
      values: [2, 4, 6, 8]
      default: 4

    gunicorn_threads:
      values: [2, 4, 8]
      default: 4

    db_pool_size:
      values: [10, 20, 30, 40]
      default: 20
```

### Run Matrix Test

```bash
# OFAT: Test varying workers only
./run-configurable.sh -p medium --matrix-test --variable workers

# OFAT: Test varying threads only
./run-configurable.sh -p medium --matrix-test --variable threads

# Full factorial (all combinations)
./run-configurable.sh -p medium --matrix-test --strategy full_factorial

# Latin hypercube (sample 20 combinations)
./run-configurable.sh -p medium --matrix-test --strategy latin_hypercube --samples 20
```

### Matrix Test Results

Output shows optimal configuration:

```
Configuration Matrix Results (OFAT - Workers)
==============================================

Workers | Throughput | p95 Latency | Resource Usage
--------|------------|-------------|----------------
2       | 450 rps    | 52ms        | CPU: 35%, Mem: 800MB
4       | 820 rps    | 34ms        | CPU: 60%, Mem: 1.2GB  ← OPTIMAL
6       | 950 rps    | 31ms        | CPU: 85%, Mem: 1.8GB
8       | 980 rps    | 30ms        | CPU: 95%, Mem: 2.4GB

Recommendation: 4 workers provides best cost/performance ratio
- 82% of maximum throughput
- 60% CPU usage (room for spikes)
- 50% cost of 8 workers
```

---

## Comparison & Analysis

### Saving Baselines

```bash
# Save current configuration as baseline
./run-configurable.sh -p medium --save-baseline production_baseline.json
```

### Comparing Against Baseline

```bash
# Test new configuration and compare
./run-configurable.sh -p medium \
  --server-profile optimized \
  --compare-with production_baseline.json
```

### Comparison Report Format

```
Performance Comparison Report
=============================

Configuration Changes:
- Workers: 4 → 8 (+100%)
- Threads: 4 → 2 (-50%)
- DB Pool: 20 → 30 (+50%)

Results:
┌─────────────────┬──────────┬──────────┬──────────┐
│ Metric          │ Baseline │ Current  │ Change   │
├─────────────────┼──────────┼──────────┼──────────┤
│ Throughput      │ 650 rps  │ 920 rps  │ +41.5% ✅ │
│ p95 Latency     │ 45ms     │ 31ms     │ -31.1% ✅ │
│ p99 Latency     │ 78ms     │ 52ms     │ -33.3% ✅ │
│ Error Rate      │ 0.02%    │ 0.01%    │ -50.0% ✅ │
│ CPU Usage       │ 55%      │ 78%      │ +41.8% ⚠️  │
│ Memory Usage    │ 1.2GB    │ 1.8GB    │ +50.0% ⚠️  │
└─────────────────┴──────────┴──────────┴──────────┘

Cost Analysis:
- Performance improvement: +41.5%
- Resource increase: +45%
- Cost per request: -3% ✅

Verdict: ✅ RECOMMENDED
- Significant performance improvement
- Moderate resource increase
- Better cost efficiency
```

---

## Examples

### Example 1: Find Optimal Worker Count

```bash
# Enable matrix testing in config.yaml
configuration_matrix:
  enabled: true
  strategy: "one_factor_at_a_time"
  variables:
    gunicorn_workers:
      values: [2, 4, 6, 8, 12, 16]

# Run test
./run-configurable.sh -p heavy --matrix-test --variable gunicorn_workers

# Review report to find optimal worker count
```

### Example 2: Evaluate PostgreSQL Upgrade

```bash
# Test current version (15)
./run-configurable.sh -p medium \
  --postgres-version 15-alpine \
  --save-baseline pg15_baseline.json

# Test proposed upgrade (17)
./run-configurable.sh -p medium \
  --postgres-version 17-alpine \
  --compare-with pg15_baseline.json

# Review comparison report for upgrade impact
```

### Example 3: Plan Production Capacity

```bash
# Test different infrastructure profiles
./run-configurable.sh -p heavy --infrastructure staging
./run-configurable.sh -p heavy --infrastructure production
./run-configurable.sh -p heavy --infrastructure production_ha

# Compare cost vs. performance
# Choose optimal configuration for expected load
```

### Example 4: Optimize for Cost

```bash
# Start with production profile
./run-configurable.sh -p medium \
  --infrastructure production \
  --save-baseline prod_baseline.json

# Test with fewer instances
./run-configurable.sh -p medium \
  --infrastructure staging \
  --compare-with prod_baseline.json

# If staging meets SLOs with 50% cost savings, use it
```

### Example 5: Stress Test with Scaling

```bash
# Enable scaling tests
scaling_tests:
  enabled: true
  configurations:
    - instances: 1
    - instances: 2
    - instances: 4

# Run sustained load test
./run-configurable.sh -p sustained --scaling-test

# Identify breaking point and plan auto-scaling thresholds
```

---

## Best Practices

### 1. Test Systematically
- Start with OFAT to identify key parameters
- Use Latin hypercube for comprehensive optimization
- Run full factorial only for critical decisions

### 2. Save Baselines
- Save baseline after each major release
- Save baselines for each environment (dev, staging, prod)
- Compare new configurations against relevant baseline

### 3. Consider Cost
- Higher performance = higher cost
- Find sweet spot: diminishing returns point
- Factor in operational costs (maintenance, complexity)

### 4. Test Under Load
- Use realistic load profiles
- Test with expected peak load + 50% headroom
- Run sustained tests (1+ hour) to detect memory leaks

### 5. Validate Horizontally
- Test scaling before relying on it
- Verify load balancer overhead is acceptable
- Check for resource contention at higher instance counts

### 6. Database Tuning
- Test PostgreSQL upgrades in staging first
- Tune shared_buffers based on available RAM
- Monitor connection pool usage during tests

### 7. Document Decisions
- Record why specific configurations were chosen
- Document trade-offs (performance vs. cost)
- Update baselines when infrastructure changes

---

## Troubleshooting

### Docker Compose Generation Fails
```bash
# Check infrastructure profile syntax
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Verify Docker is running
docker info

# Check available resources
docker system df
```

### Services Don't Start After Config Change
```bash
# Check logs
docker-compose logs gateway
docker-compose logs postgres

# Verify health checks
./utils/check-services.sh

# Restore original config
cp docker-compose.yml.backup docker-compose.yml
docker-compose up -d
```

### Comparison Shows Unexpected Results
```bash
# Verify same load profile was used
grep "PROFILE=" baseline.json current.json

# Check if warmup was used consistently
grep "warmup" baseline.json current.json

# Ensure system load was similar
check system metrics during both test runs
```

---

## Next Steps

1. **Start simple**: Test with different server profiles
2. **Optimize**: Use matrix testing to find optimal settings
3. **Scale**: Test horizontal scaling to plan capacity
4. **Upgrade**: Compare database versions before upgrading
5. **Automate**: Integrate into CI/CD for regression detection

For detailed implementation, see [PERFORMANCE_STRATEGY.md](PERFORMANCE_STRATEGY.md).
