# Load Testing Data Generator

Production-scale load data generation framework for MCP Gateway performance testing, scalability validation, and capacity planning.

## Overview

This framework generates realistic, production-scale test data including:
- **160,000+ users** with realistic names and emails
- **1,600,000+ teams** with power-law size distribution
- **10,000,000+ team members** with relationships
- **16,000,000+ resources and prompts** per user/team
- **500,000+ tools** across 10,000 gateways
- **Billions of audit logs and metrics**

## Quick Start

```bash
# Generate small dataset for development (100 users, <1 minute)
python -m tests.load.generate --profile small

# Generate production-scale dataset (160K users, <30 minutes)
python -m tests.load.generate --profile production

# Cleanup test data
python -m tests.load.cleanup --profile production --confirm

# Verify data integrity
python -m tests.load.verify --profile production
```

## Installation

The load testing framework requires these additional dependencies:

```bash
pip install faker pyyaml tqdm numpy
```

## Profiles

### Small (Development)
- **Users**: 100
- **Teams**: ~600
- **Resources**: ~2,000
- **Time**: <1 minute
- **Use case**: Development testing, quick validation

### Medium (Staging)
- **Users**: 10,000
- **Teams**: ~110,000
- **Resources**: ~1,000,000
- **Time**: <10 minutes
- **Use case**: Staging environment, pagination testing

### Large (Pre-Production)
- **Users**: 50,000
- **Teams**: ~550,000
- **Resources**: ~5,000,000
- **Time**: <20 minutes
- **Use case**: Pre-production validation, stress testing

### Production
- **Users**: 160,000
- **Teams**: ~1,760,000
- **Resources**: ~16,000,000
- **Time**: <30 minutes
- **Use case**: Production capacity planning, scalability validation

### Massive (Future Scale)
- **Users**: 1,000,000
- **Teams**: ~11,000,000
- **Resources**: ~100,000,000
- **Time**: <2 hours
- **Use case**: Future scale planning, extreme stress testing

## CLI Commands

### Generate Data

```bash
# Basic usage with profile
python -m tests.load.generate --profile production

# Custom configuration
python -m tests.load.generate --config tests/load/configs/custom.yaml

# Dry run (show what would be generated)
python -m tests.load.generate --profile production --dry-run

# Custom seed for reproducibility
python -m tests.load.generate --profile medium --seed 12345

# Override batch size
python -m tests.load.generate --profile production --batch-size 2000

# Save report to custom location
python -m tests.load.generate --profile production --output /tmp/load_report.json
```

### Cleanup Data

```bash
# Dry run (see what would be deleted)
python -m tests.load.cleanup --profile production --dry-run

# Delete production test data
python -m tests.load.cleanup --profile production --confirm

# Delete all test data (matches email domain)
python -m tests.load.cleanup --all --confirm

# Custom email domain
python -m tests.load.cleanup --all --email-domain test.example.com --confirm

# DANGEROUS: Truncate all tables
python -m tests.load.cleanup --truncate --confirm
```

### Verify Data

```bash
# Verify all aspects
python -m tests.load.verify --profile production

# Verbose output
python -m tests.load.verify --profile production --verbose

# Save verification report
python -m tests.load.verify --profile production --output /tmp/verify_report.json
```

## Configuration

### YAML Configuration Schema

```yaml
profile:
  name: custom
  description: "Custom load profile"
  version: 1.0

global:
  random_seed: 42                      # For reproducibility
  batch_size: 1000                     # Records per batch insert
  progress_bar: true
  parallel: true
  workers: 8
  email_domain: "loadtest.example.com"

scale:
  users: 160000
  personal_teams_per_user: 1
  additional_teams_per_user: 10

  members_per_team_min: 1
  members_per_team_max: 100
  members_per_team_distribution: "power_law"

  tokens_per_user_avg: 5
  gateways: 10000
  tools_per_gateway_avg: 50
  resources_per_user_avg: 100
  prompts_per_user_avg: 100
  servers_per_user_avg: 10

distributions:
  team_size: "power_law"               # Few large, many small teams
  resource_access: "zipf"              # 80/20 access pattern
  temporal: "exponential_decay"        # More recent data

temporal:
  start_date: "2023-01-01"
  end_date: "2025-10-12"
  recent_data_percent: 80              # 80% data in last 30 days
```

## Data Distributions

### Power Law (Team Sizes)
Creates realistic team size distribution where:
- Most teams have 1-5 members (80%)
- Some teams have 10-20 members (15%)
- Few teams have 50-100 members (5%)

### Zipf (Resource Access)
Models realistic access patterns (80/20 rule):
- 20% of resources get 80% of traffic
- Follows actual user behavior patterns

### Exponential Decay (Temporal)
Generates realistic temporal distribution:
- 80% of data created in last 30 days
- 20% of data older than 30 days
- Mimics real system growth

## Architecture

```
tests/load/
├── generate.py          # Main generation CLI
├── cleanup.py           # Data cleanup CLI
├── verify.py            # Data verification CLI
├── configs/             # Configuration profiles
│   ├── small.yaml
│   ├── medium.yaml
│   ├── large.yaml
│   └── production.yaml
├── generators/          # Data generators
│   ├── base.py         # Base generator class
│   ├── users.py        # User generator
│   ├── teams.py        # Team generator
│   ├── team_members.py # Team member generator
│   ├── tokens.py       # API token generator
│   ├── gateways.py     # Gateway generator
│   ├── tools.py        # Tool generator
│   ├── resources.py    # Resource generator
│   ├── prompts.py      # Prompt generator
│   └── servers.py      # Virtual server generator
└── utils/              # Utility functions
    ├── distributions.py # Statistical distributions
    ├── progress.py     # Progress tracking
    └── validation.py   # Data validation
```

## Performance

### Benchmarks (Production Profile, 160K users)

| Component | Records | Time | Rate |
|-----------|---------|------|------|
| Users | 160,000 | 2m | 1,333/s |
| Teams | 1,760,000 | 8m | 3,666/s |
| Team Members | 10,000,000 | 15m | 11,111/s |
| Tokens | 800,000 | 3m | 4,444/s |
| Gateways | 10,000 | 30s | 333/s |
| Tools | 500,000 | 5m | 1,666/s |
| Resources | 16,000,000 | 20m | 13,333/s |
| **Total** | **~156M** | **<30m** | **87,000/s** |

### Memory Usage
- Small: <100 MB
- Medium: <500 MB
- Large: <1 GB
- Production: <2 GB
- Massive: <4 GB

## Validation

Post-generation validation includes:
- **Foreign Key Integrity**: All relationships valid
- **Uniqueness Constraints**: No duplicates
- **Required Fields**: All non-NULL
- **Email Formats**: Valid email addresses
- **Orphaned Records**: Zero orphans
- **Data Distributions**: Match configured patterns

## Use Cases

### 1. Pagination Testing
```bash
# Generate production data
python -m tests.load.generate --profile production

# Test pagination with millions of records
curl "http://localhost:4444/admin/tools?page=1&per_page=100"
curl "http://localhost:4444/admin/tools?page=100&per_page=100"
```

### 2. Performance Benchmarking
```bash
# Generate data
python -m tests.load.generate --profile production

# Run performance tests
make performance-test-heavy

# Cleanup
python -m tests.load.cleanup --all --confirm
```

### 3. Database Migration Testing
```bash
# Generate data
python -m tests.load.generate --profile large

# Run migration
alembic upgrade head

# Verify integrity
python -m tests.load.verify
```

### 4. Query Optimization
```bash
# Generate production data
python -m tests.load.generate --profile production

# Analyze slow queries
EXPLAIN ANALYZE SELECT * FROM tools WHERE team_id = 'team-123' ORDER BY created_at DESC LIMIT 100;

# Add indexes
CREATE INDEX ix_tools_team_created ON tools(team_id, created_at);
```

## Troubleshooting

### Out of Memory
```bash
# Reduce batch size
python -m tests.load.generate --profile production --batch-size 500

# Reduce workers
python -m tests.load.generate --profile production --workers 2
```

### Database Connection Issues
```bash
# Check connection pool settings in config
database:
  pool_size: 10       # Reduce if needed
  max_overflow: 20
  pool_timeout: 60    # Increase timeout
```

### Slow Generation
```bash
# Disable progress bars (reduces overhead)
# Edit config: progress_bar: false

# Increase batch size
python -m tests.load.generate --profile production --batch-size 2000

# Disable validation
python -m tests.load.generate --profile production --skip-validation
```

## Best Practices

1. **Always use dry-run first**
   ```bash
   python -m tests.load.generate --profile production --dry-run
   ```

2. **Use test email domain**
   - Default: `loadtest.example.com`
   - Makes cleanup easy and safe

3. **Save reports**
   - Always save generation reports for analysis
   - Use for capacity planning

4. **Verify after generation**
   ```bash
   python -m tests.load.verify --profile production
   ```

5. **Clean up after testing**
   ```bash
   python -m tests.load.cleanup --all --confirm
   ```

## Related Issues

- [#1224 - Pagination Feature](https://github.com/IBM/mcp-context-forge/issues/1224)
- [#1225 - Load Data Generator Epic](https://github.com/IBM/mcp-context-forge/issues/1225)

## Support

For issues or questions, please create an issue on GitHub.
