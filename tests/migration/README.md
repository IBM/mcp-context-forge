# Migration Test Suite

A comprehensive test suite for validating **application-level database migrations** across MCP Gateway container versions following an **n-2 support policy**. This suite tests both SQLite (via Docker) and PostgreSQL/Redis (via docker-compose) deployments using realistic application container scenarios with extensive logging and reporting.

**Migration Approach**: This test suite validates **application-managed migrations** where containers handle their own database initialization and schema evolution automatically, rather than executing manual Alembic commands. This approach reflects real-world deployment scenarios where applications manage their own database state.

## 🔄 Migration Methodology

### Application-Level Migration Testing

This test suite implements **application-level migration validation** with the following key principles:

1. **Container-as-Application**: Each container is treated as a complete application that manages its own database state
2. **Automatic Schema Detection**: Applications automatically detect existing database schemas and apply necessary migrations on startup
3. **Volume Persistence**: Database files are preserved across container version switches using Docker volume mounts
4. **REST API Validation**: Data integrity and schema correctness are validated through application REST endpoints
5. **Python3 HTTP Client**: All HTTP requests use Python3's urllib library for maximum container compatibility

### Migration Test Flow

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Start v0.5.0   │───▶│   Seed Data      │───▶│ Capture State   │
│   Container     │    │   via REST API   │    │  (API Health)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                                               │
         ▼                                               ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Preserve       │───▶│  Start v0.7.0    │───▶│ Auto-Migration  │
│  Data Volume    │    │   Container      │    │  (Application)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                                               │
         ▼                                               ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Validate      │───▶│  Data Integrity  │───▶│ Generate        │
│   API Health    │    │     Check        │    │   Report        │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## 📋 Version Policy (n-2 Support)

The migration test suite follows an **n-2 support policy**, meaning we test the current version and the two previous versions:

- **n** (latest): Current development version
- **n-1**: Previous stable version
- **n-2**: Baseline supported version

**Current supported versions**: `0.5.0`, `0.7.0`, `latest`

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

- **Container Manager** (`utils/container_manager.py`): Orchestrates Docker/Podman containers with volume persistence
- **Migration Runner** (`utils/migration_runner.py`): Executes application-level migration test scenarios
- **Schema Validator** (`utils/schema_validator.py`): Validates application-managed schema evolution
- **Data Seeder** (`utils/data_seeder.py`): Seeds test data via REST API endpoints
- **Report Generator** (`utils/reporting.py`): Creates comprehensive HTML dashboards

**Key Features**:
- **Data Persistence**: Preserves database files across container version switches
- **REST API Integration**: Uses application endpoints for data seeding and validation
- **Python3 HTTP Client**: Uses Python3 urllib instead of curl for container compatibility
- **Volume Management**: Automatic file ownership and permission handling

### Test Categories

1. **Application-Level Forward Migrations**: Sequential version upgrades (0.5.0 → 0.7.0 → latest)
   - Containers automatically detect and migrate existing databases
   - Data persistence validation across version switches
   - REST API-based data integrity verification

2. **Reverse Migrations**: Sequential downgrades with data preservation
3. **Skip-Version Migrations**: Multi-version jumps (0.4.0 → latest)
4. **Performance Tests**: Large datasets, concurrent operations, stress testing
5. **Data Integrity**: Application health checks, API endpoint validation, record count verification

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
from tests.migration.utils.migration_runner import MigrationTestRunner

def test_custom_migration():
    container_manager = ContainerManager()
    migration_runner = MigrationTestRunner(container_manager)

    # Start container with specific version
    container_id = container_manager.start_sqlite_container("0.5.0")

    # Let application initialize database automatically
    time.sleep(3)  # Allow application startup

    # Validate application is ready
    health_result = container_manager._run_command([
        container_manager.runtime, "exec", container_id,
        "python3", "-c",
        "import urllib.request; "
        "resp = urllib.request.urlopen('http://localhost:4444/health', timeout=5); "
        "print(resp.read().decode())"
    ], capture_output=True)

    assert health_result.returncode == 0
    assert "healthy" in health_result.stdout
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
# Check application migration status
make migration-debug

# Application health and API checks in container
docker exec <container_id> python3 -c "import urllib.request; resp = urllib.request.urlopen('http://localhost:4444/health'); print(resp.read().decode())"

# Check application logs for migration details
docker logs <container_id> | grep -i migration

# Test API endpoints
docker exec <container_id> python3 -c "import urllib.request; resp = urllib.request.urlopen('http://localhost:4444/tools'); print(resp.read().decode())"
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
docker tag mcp-context-forge:latest ghcr.io/ibm/mcp-context-forge:0.7.0
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
# Fix volume permissions for application user (uid=1001)
sudo chown -R 1001:1001 /tmp/migration_test_*
# or make world-writable for testing
sudo chmod -R 777 /tmp/migration_test_*
```

**Container HTTP request failures:**
```bash
# Test if python3 urllib works in container
docker exec <container_id> python3 -c "import urllib.request; print('urllib available')"

# Check if application is listening on all interfaces
docker exec <container_id> netstat -tulpn | grep :4444

# Verify HOST=0.0.0.0 is set
docker exec <container_id> env | grep HOST
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

## Technical Notes

### Recent Improvements

**v2.0 (Application-Level Migration Testing)**:
- ✅ **Python3 HTTP Client**: Replaced all `curl` commands with `python3 urllib.request` for container compatibility
- ✅ **Volume Persistence**: Fixed data directory preservation across container version switches
- ✅ **File Permissions**: Automatic ownership management for container user (uid=1001, gid=1001)
- ✅ **REST API Integration**: All data operations use application endpoints instead of direct database access
- ✅ **Application-Level Migrations**: Tests now validate how applications handle migrations automatically
- ✅ **Enhanced Logging**: Comprehensive logging throughout all migration phases

**HTTP Request Format**:
```python
# Modern approach (Python3 urllib)
docker exec <container_id> python3 -c "import urllib.request; resp = urllib.request.urlopen('http://localhost:4444/health', timeout=5); print(resp.read().decode())"

# Legacy approach (curl - not available in containers)
docker exec <container_id> curl -s -f http://localhost:4444/health
```

**Data Directory Management**:
- Temporary directories are created with proper ownership (`1001:1001`)
- Data volumes are preserved when switching between container versions
- Database files persist across the entire migration test lifecycle

### Architecture Decisions

1. **Why Application-Level Testing?**
   - Mirrors real-world deployment scenarios where applications manage their own database state
   - Tests the actual migration behavior users will experience
   - Validates container startup, health checks, and API availability

2. **Why Python3 Instead of curl?**
   - Container images don't include curl by default
   - Python3 is available in all application containers
   - Provides better error handling and timeout control

3. **Why Volume Persistence?**
   - Essential for testing actual migration behavior across versions
   - Validates data preservation during upgrades
   - Enables realistic upgrade/rollback scenarios

## Contributing

When adding new migration tests:

1. Follow existing naming conventions
2. Add comprehensive logging with emojis
3. Include both positive and negative test cases
4. Use **python3 urllib.request** for HTTP requests (never curl)
5. Ensure proper **data volume persistence** across container switches
6. Test **application-level migration behavior** rather than manual Alembic commands
7. Update this README with new features
8. Add appropriate Makefile targets
9. Test with both SQLite and PostgreSQL

---

For more details on the MCP Gateway project, see the main [README.md](../../README.md) and [CLAUDE.md](../../CLAUDE.md) files.
