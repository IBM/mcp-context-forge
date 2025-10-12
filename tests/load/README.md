# Load Testing Framework

Production-scale load testing and database population system for MCP Gateway with realistic data generation, comprehensive metrics, and validation.

## Quick Start

```bash
# Generate small test dataset (100 users, ~74K records, <1 minute)
make generate-small

# View generated data report
make generate-report

# Check database
sqlite3 mcp.db "SELECT COUNT(*) FROM email_users;"
```

## Available Profiles

| Profile | Users | Teams | Total Records | Time | Database | Command |
|---------|-------|-------|---------------|------|----------|---------|
| **Small** | 100 | ~600 | ~74K | <1 min | SQLite OK | `make generate-small` |
| **Medium** | 10K | ~110K | ~70M | ~10 min | PostgreSQL recommended | `make generate-medium` |
| **Large** | 100K | ~1.1M | ~700M | ~1-2 hours | PostgreSQL/MySQL required | `make generate-large` |
| **Massive** | 1M | ~11M | ~7B | ~10-20 hours | PostgreSQL/MySQL + high-end hardware | `make generate-massive` |

## Command-Line Usage

### Makefile Targets (Easiest)

```bash
make generate-small      # 100 users, ~74K records, <1 min
make generate-medium     # 10K users, ~70M records, ~10 min
make generate-large      # 100K users, ~700M records, ~1-2 hours
make generate-massive    # 1M users, billions of records, ~10-20 hours
make generate-clean      # Clean reports
make generate-report     # Display latest reports
```

### Direct Python Usage

```bash
# Use predefined profile
python -m tests.load.generate --profile small

# Dry run (show what would be generated)
python -m tests.load.generate --profile medium --dry-run

# Custom configuration
python -m tests.load.generate --config path/to/custom.yaml

# Override batch size
python -m tests.load.generate --profile small --batch-size 500

# Set random seed for reproducibility
python -m tests.load.generate --profile small --seed 12345

# Skip validation (faster)
python -m tests.load.generate --profile medium --skip-validation

# Custom output
python -m tests.load.generate --profile small --output custom_report.json
```

## What Gets Generated

Each profile generates realistic data across **29 entity types**. See full architecture section below.

## Database Setup

### SQLite (Development - Default)
```bash
DATABASE_URL=sqlite:///./mcp.db
```
Works out of the box. Suitable for small/medium profiles only.

### PostgreSQL (Recommended)
```bash
docker run -d --name postgres -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=mcp -p 5432:5432 postgres:16
DATABASE_URL=postgresql://postgres:pass@localhost:5432/mcp
alembic upgrade head
```

### MySQL
```bash
docker run -d --name mysql -e MYSQL_ROOT_PASSWORD=pass -e MYSQL_DATABASE=mcp -p 3306:3306 mysql:8.0
DATABASE_URL=mysql+pymysql://root:pass@localhost:3306/mcp
alembic upgrade head
```

## Reports

```bash
# View latest reports
make generate-report

# Or directly
jq . reports/small_load_report.json
```

## Troubleshooting

### "NOT NULL constraint failed: token_usage_logs.id"
**Fixed!** Run migration: `alembic upgrade head`

### Out of Memory
Use PostgreSQL/MySQL, reduce batch size, increase swap.

### Slow Generation
Use SSD storage, PostgreSQL, increase DB_POOL_SIZE.

For full documentation, see sections below.

---

## Full Documentation

### Entity Types Generated

**Core Entities:**
- Users, Teams, Team Members, API Tokens
- Gateways, Tools, Resources, Prompts
- Virtual Servers, A2A Agents

**Associations:**
- Server-Tool, Server-Resource, Server-Prompt, Server-A2A mappings

**Metrics & Analytics:**
- Tool/Resource/Prompt/Server/A2A metrics

**Activity Logs:**
- Token usage logs, Auth events, Permission audits

**Sessions:**
- MCP sessions, Messages, Resource subscriptions

**Workflow State:**
- Team invitations, Join requests, Token revocations, OAuth tokens

### Configuration Files

`tests/load/configs/`:
- `small.yaml` - 100 users, development
- `medium.yaml` - 10K users, staging
- `large.yaml` - 100K users, pre-production
- `massive.yaml` - 1M users, stress testing
- `production.yaml` - Custom scenarios

### Performance Optimization

1. Use PostgreSQL/MySQL for large datasets
2. Increase batch size: `--batch-size 2000`
3. Use SSD storage
4. Increase DB pool: `DB_POOL_SIZE=50` in `.env`
5. Disable validation during load: `--skip-validation`

### Validation

Automatically validates:
- Foreign key integrity
- Orphaned records detection
- Required fields (NOT NULL)
- Email format validation

### Cleanup

```bash
# Clean reports only
make generate-clean

# Clean database
rm mcp.db  # SQLite
docker exec postgres psql -U postgres -c "DROP DATABASE mcp; CREATE DATABASE mcp;"  # PostgreSQL
alembic upgrade head  # Recreate schema
```

### Contributing

See `tests/load/generators/base.py` for generator pattern.

1. Create generator in `tests/load/generators/`
2. Implement: `get_count()`, `get_dependencies()`, `generate()`
3. Register in `generate.py`
4. Add to config `generation_order`
5. Add scale parameters to YAML files

## License

Apache 2.0

## Support

GitHub Issues: https://github.com/ibm/mcp-context-forge/issues
