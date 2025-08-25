# Migration Test Suite

A comprehensive test suite for validating Alembic database migrations across MCP Gateway container versions following an **n-2 support policy**. This suite tests both SQLite (via Docker) and PostgreSQL/Redis (via docker-compose) deployments with extensive logging and reporting.

## 📋 Version Policy (n-2 Support)

The migration test suite follows an **n-2 support policy**, meaning we test the current version and the two previous versions:

- **n** (latest): Current development version
- **n-1**: Previous stable version  
- **n-2**: Baseline supported version

**Current supported versions**: `0.5.0`, `0.6.0`, `latest`

This policy ensures migration compatibility across supported versions while keeping test execution time reasonable.

## Quick Start

```bash
# Run complete migration test suite
make migration-test-all

# Run specific database tests
make migration-test-sqlite      # SQLite container tests
make migration-test-postgres    # PostgreSQL compose tests
make migration-test-performance # Performance benchmarking

# Environment management
make migration-setup           # Setup test environment
make migration-cleanup         # Clean up containers/volumes
make migration-debug          # Debug failed migrations
```

## Test Architecture

### Core Components

- **Container Manager** (`utils/container_manager.py`): Orchestrates Docker/Podman containers
- **Migration Runner** (`utils/migration_runner.py`): Executes migration test scenarios
- **Schema Validator** (`utils/schema_validator.py`): Compares database schemas
- **Data Seeder** (`utils/data_seeder.py`): Generates realistic test data
- **Report Generator** (`utils/reporting.py`): Creates HTML dashboards

### Test Categories

1. **Forward Migrations**: Sequential version upgrades (0.5.0 → 0.6.0 → latest)
2. **Reverse Migrations**: Sequential downgrades with data preservation
3. **Skip-Version Migrations**: Multi-version jumps (0.4.0 → latest)
4. **Performance Tests**: Large datasets, concurrent operations, stress testing
5. **Data Integrity**: Schema validation, foreign key constraints, data preservation

## Adding New Versions

To add a new version (e.g., `0.7.0`), use the provided helper script:

```bash
# Show instructions and create sample test data
python3 tests/migration/add_version.py 0.7.0

# Check current version status
python3 tests/migration/version_status.py
```

### Manual Steps

1. **Update version configuration** in `tests/migration/version_config.py`:
   ```python
   RELEASES = [
       # ... existing versions ...
       "0.7.0",    # Add new version
       "latest",
   ]
   CURRENT_VERSION = "0.7.0"  # Update if latest numbered version
   ```

2. **Add version metadata** to `RELEASE_INFO` dict
3. **Create test data** in `fixtures/test_data_sets/v0_7_0_sample.json`
4. **Pull container image**: `make migration-setup`

The n-2 policy will automatically adjust to test the new supported versions.

## Configuration

### Environment Variables

```bash
# Container runtime (auto-detected)
CONTAINER_RUNTIME=docker         # or podman

# Test timeouts
MIGRATION_TIMEOUT=300           # seconds
CONTAINER_START_TIMEOUT=60      # seconds

# Performance test settings
PERFORMANCE_DATASET_SIZE=1000   # number of records
MAX_MEMORY_USAGE=512            # MB
```

### Test Scenarios

Edit `fixtures/migration_scenarios.yaml` to configure test scenarios:

```yaml
scenarios:
  forward_migrations:
    - name: "custom_upgrade_path"
      test_pairs:
        - from: "0.5.0"
          to: "0.7.0"
          data_set: "custom_sample"
          expected_duration: 45
          critical: true
```

### Test Data

Create custom test datasets in `fixtures/test_data_sets/`:

```json
{
  "metadata": {
    "version": "0.7.0",
    "description": "Custom test data",
    "total_records": 25
  },
  "data": {
    "tools": [...],
    "servers": [...],
    "gateways": [...]
  }
}
```

## Usage Examples

### Running Specific Migration Tests

```bash
# Test specific version upgrade
pytest tests/migration/test_docker_sqlite_migrations.py::test_sequential_forward_migrations -v

# Test with custom data
pytest tests/migration/test_docker_sqlite_migrations.py -k "test_migration_with_data" -v

# Performance testing with large dataset
pytest tests/migration/test_migration_performance.py::test_large_dataset_migration -v
```

### Custom Container Testing

```python
from tests.migration.utils.container_manager import ContainerManager

async def test_custom_migration():
    container_manager = ContainerManager()
    
    # Start container with specific version
    container_id = await container_manager.start_sqlite_container("0.5.0")
    
    # Run custom migration
    result = await container_manager.exec_alembic_command(
        container_id, "upgrade", "head"
    )
    
    # Validate result
    assert result.returncode == 0
```

### Adding New Test Scenarios

1. **Define scenario** in `fixtures/migration_scenarios.yaml`
2. **Create test data** in `fixtures/test_data_sets/`
3. **Add test method** in appropriate test file
4. **Update Makefile** targets if needed

## Extending the Test Suite

### Adding New Database Support

1. **Create transport module** (e.g., `utils/mysql_manager.py`)
2. **Extend container manager** with new database methods
3. **Add test file** (e.g., `test_mysql_migrations.py`)
4. **Update fixtures** in `conftest.py`

### Custom Validation Rules

Extend `schema_validator.py` with custom validation:

```python
class CustomSchemaValidator(SchemaValidator):
    def validate_custom_constraints(self, schema_before, schema_after):
        """Custom validation logic"""
        # Your validation code here
        return ValidationResult(...)
```

### Performance Metrics

Add custom metrics in `migration_runner.py`:

```python
async def collect_custom_metrics(self, container_id):
    """Collect application-specific metrics"""
    metrics = {}
    # Your metrics collection
    return metrics
```

### Report Customization

Extend `reporting.py` for custom reports:

```python
class CustomReportGenerator(MigrationReportGenerator):
    def generate_custom_section(self, results):
        """Generate custom report section"""
        # Your custom reporting logic
        return html_content
```

## Debugging Migration Issues

### Verbose Logging

All components include comprehensive logging. Set log level:

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
make test-migration-sqlite
```

### Container Inspection

```bash
# List migration test containers
docker ps -a | grep migration-test

# Inspect container logs
docker logs <container_id>

# Access container shell
docker exec -it <container_id> /bin/bash
```

### Database Debugging

```bash
# Connect to test database
sqlite3 /tmp/migration_test.db
# or
psql -h localhost -p 5432 -U mcpgateway -d mcpgateway_test
```

### Migration State Investigation

```bash
# Check Alembic history
make migration-debug

# Manual Alembic commands in container
docker exec <container_id> alembic history
docker exec <container_id> alembic current
```

## Performance Optimization

### Container Resource Limits

Configure in `conftest.py`:

```python
@pytest.fixture
def container_limits():
    return {
        "memory": "1g",
        "cpus": "2.0",
        "shm_size": "256m"
    }
```

### Parallel Test Execution

```bash
# Run tests in parallel
pytest tests/migration/ -n auto

# Limit parallel workers
pytest tests/migration/ -n 4
```

### Test Data Optimization

- Use smaller datasets for development
- Enable data multipliers for performance testing
- Cache container images to reduce setup time

## Continuous Integration

### GitHub Actions Example

```yaml
- name: Run Migration Tests
  run: |
    make migration-setup
    make test-migration-all
    
- name: Upload Reports
  uses: actions/upload-artifact@v3
  with:
    name: migration-reports
    path: tests/migration/reports/
```

### Docker Registry Setup

Ensure container images are available:

```bash
# Build and tag images
make docker-prod
docker tag mcp-context-forge:latest ghcr.io/ibm/mcp-context-forge:latest

# For testing multiple versions
docker tag mcp-context-forge:latest ghcr.io/ibm/mcp-context-forge:0.6.0
```

## Troubleshooting

### Common Issues

**Container startup failures:**
```bash
# Check Docker daemon
systemctl status docker
# Check available disk space
df -h
# Clear Docker cache
docker system prune -f
```

**Migration timeouts:**
```bash
# Increase timeout in conftest.py
MIGRATION_TIMEOUT = 600  # 10 minutes
```

**Database connection issues:**
```bash
# Check port conflicts
netstat -tulpn | grep :5432
# Reset Docker networking
docker network prune
```

**Permission errors:**
```bash
# Fix volume permissions
sudo chown -R $USER:$USER /tmp/migration_tests/
```

### Getting Help

1. Check verbose logs in `tests/migration/logs/`
2. Run `make migration-debug` for diagnostic info
3. Use `pytest -vvv` for maximum verbosity
4. Inspect generated HTML reports in `tests/migration/reports/`

## File Structure Reference

```
tests/migration/
├── README.md                           # This file
├── version_config.py                   # 🔧 Centralized version configuration (n-2 policy)
├── version_status.py                   # 📊 Show current version configuration
├── add_version.py                      # ➕ Helper script to add new versions
├── conftest.py                         # pytest configuration and fixtures
├── test_docker_sqlite_migrations.py    # SQLite container migration tests
├── test_compose_postgres_migrations.py # PostgreSQL compose migration tests
├── test_migration_performance.py       # Performance benchmarking tests
├── utils/
│   ├── __init__.py
│   ├── container_manager.py           # Docker/Podman container management
│   ├── migration_runner.py            # Migration test execution engine
│   ├── schema_validator.py            # Database schema comparison
│   ├── data_seeder.py                 # Test data generation utilities
│   └── reporting.py                   # HTML dashboard and report generation
├── fixtures/
│   ├── migration_scenarios.yaml       # Test scenario configuration
│   └── test_data_sets/                # Sample data for each version
│       ├── v0_5_0_sample.json
│       ├── v0_6_0_sample.json
│       └── latest_sample.json
├── logs/                              # Test execution logs (created at runtime)
└── reports/                           # Generated HTML reports (created at runtime)
```

## Contributing

When adding new migration tests:

1. Follow existing naming conventions
2. Add comprehensive logging with emojis
3. Include both positive and negative test cases
4. Update this README with new features
5. Add appropriate Makefile targets
6. Test with both SQLite and PostgreSQL

---

For more details on the MCP Gateway project, see the main [README.md](../../README.md) and [CLAUDE.md](../../CLAUDE.md) files.