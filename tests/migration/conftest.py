# -*- coding: utf-8 -*-
"""Migration testing pytest configuration and fixtures.

This module provides specialized fixtures for migration testing,
including container management, test data generation, and cleanup utilities.
"""

# Standard
import logging
from pathlib import Path
import tempfile
from typing import Dict, Generator

# Third-Party
import pytest

# Local
from .utils.container_manager import ContainerManager
from .utils.migration_runner import MigrationTestRunner
from .version_config import VersionConfig

# Configure logging for migration tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('tests/migration/reports/migration_tests.log', mode='a')
    ]
)

logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def migration_test_dir():
    """Create temporary directory for migration test artifacts."""
    with tempfile.TemporaryDirectory(prefix="mcp_migration_test_") as temp_dir:
        test_dir = Path(temp_dir)
        logger.info(f"🗂️ Created migration test directory: {test_dir}")

        # Create subdirectories
        (test_dir / "databases").mkdir()
        (test_dir / "schemas").mkdir()
        (test_dir / "reports").mkdir()
        (test_dir / "logs").mkdir()

        yield test_dir
        logger.info(f"🧹 Cleaning up migration test directory: {test_dir}")


@pytest.fixture(scope="session")
def container_runtime():
    """Detect and return the available container runtime."""
    # Standard
    import subprocess

    # Try Docker first
    try:
        subprocess.run(["docker", "--version"],
                      capture_output=True, check=True, timeout=10)
        logger.info("🐳 Using Docker as container runtime")
        return "docker"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try Podman
    try:
        subprocess.run(["podman", "--version"],
                      capture_output=True, check=True, timeout=10)
        logger.info("🦭 Using Podman as container runtime")
        return "podman"
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    pytest.skip("No container runtime (Docker or Podman) available")


@pytest.fixture(scope="module")
def container_manager(container_runtime) -> Generator[ContainerManager, None, None]:
    """Create container manager for SQLite migration testing."""
    logger.info(f"🚀 Creating ContainerManager with {container_runtime}")

    cm = ContainerManager(runtime=container_runtime, verbose=True)

    # Ensure required images are available
    try:
        logger.info("📦 Pulling required container images...")
        cm.pull_images(["0.5.0", "0.6.0", "latest"])  # Start with subset for faster testing
    except Exception as e:
        logger.warning(f"⚠️ Could not pull some images: {e}")

    yield cm

    # Cleanup all containers created during tests
    logger.info("🧹 Cleaning up all migration test containers")
    cm.cleanup_all()


@pytest.fixture(scope="module")
def migration_runner(container_manager) -> MigrationTestRunner:
    """Create migration test runner."""
    logger.info("🏃 Creating MigrationTestRunner")
    return MigrationTestRunner(container_manager)


@pytest.fixture
def sample_test_data() -> Dict:
    """Generate sample test data for migration testing."""
    logger.info("🎲 Generating sample test data")

    return {
        "tools": [
            {
                "name": "test_tool_basic",
                "description": "Basic test tool for migration validation",
                "schema": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Input parameter"}
                    },
                    "required": ["input"]
                },
                "annotations": {"category": "test", "version": "1.0"}
            },
            {
                "name": "test_tool_complex",
                "description": "Complex test tool with nested schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "config": {
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "settings": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "key": {"type": "string"},
                                            "value": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "metadata": {"type": "object", "additionalProperties": True}
                    }
                },
                "annotations": {"category": "test", "complexity": "high"}
            }
        ],
        "servers": [
            {
                "name": "test_server_basic",
                "description": "Basic test server",
                "transport": "sse",
                "annotations": {"environment": "test", "purpose": "migration"}
            },
            {
                "name": "test_server_websocket",
                "description": "WebSocket test server",
                "transport": "websocket",
                "connection_string": "ws://localhost:8080/ws",
                "annotations": {"transport": "websocket", "protocol": "mcp"}
            }
        ],
        "gateways": [
            {
                "name": "test_gateway_federation",
                "base_url": "http://test-peer.example.com:4444",
                "description": "Test gateway for federation scenarios",
                "annotations": {"type": "federation", "region": "test"}
            }
        ],
        "resources": [
            {
                "name": "test_resource_file",
                "uri": "file:///app/test_data/sample.txt",
                "description": "Test file resource",
                "mimeType": "text/plain",
                "annotations": {"source": "test", "type": "file"}
            }
        ],
        "prompts": [
            {
                "name": "test_prompt_simple",
                "description": "Simple test prompt",
                "template": "Hello, {{name}}! How are you today?",
                "annotations": {"category": "greeting", "complexity": "low"}
            }
        ]
    }


@pytest.fixture
def large_test_data() -> Dict:
    """Generate large test dataset for performance testing."""
    logger.info("🎲 Generating large test dataset")

    # Generate 100 tools, 20 servers, 10 gateways
    tools = []
    for i in range(100):
        tools.append({
            "name": f"perf_test_tool_{i:03d}",
            "description": f"Performance test tool number {i}",
            "schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer", "minimum": 0},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            },
            "annotations": {
                "batch": "performance_test",
                "index": i,
                "category": f"category_{i % 10}"
            }
        })

    servers = []
    for i in range(20):
        servers.append({
            "name": f"perf_test_server_{i:02d}",
            "description": f"Performance test server {i}",
            "transport": "sse" if i % 2 == 0 else "websocket",
            "annotations": {"batch": "performance_test", "index": i}
        })

    gateways = []
    for i in range(10):
        gateways.append({
            "name": f"perf_test_gateway_{i:02d}",
            "base_url": f"http://test-gateway-{i}.example.com:4444",
            "description": f"Performance test gateway {i}",
            "annotations": {"batch": "performance_test", "index": i}
        })

    return {
        "tools": tools,
        "servers": servers,
        "gateways": gateways
    }


@pytest.fixture
def version_matrix():
    """Return the version matrix for testing."""
    return {
        "available_versions": ["0.2.0", "0.3.0", "0.4.0", "0.5.0", "0.6.0", "latest"],
        "forward_pairs": [
            ("0.2.0", "0.3.0"),
            ("0.3.0", "0.4.0"),
            ("0.4.0", "0.5.0"),
            ("0.5.0", "0.6.0"),
            ("0.6.0", "latest")
        ],
        "reverse_pairs": [
            ("latest", "0.6.0"),
            ("0.6.0", "0.5.0"),
            ("0.5.0", "0.4.0"),
            ("0.4.0", "0.3.0"),
            ("0.3.0", "0.2.0")
        ],
        "skip_pairs": [
            ("0.2.0", "0.4.0"),  # Skip 0.3.0
            ("0.3.0", "0.6.0"),  # Skip 0.4.0, 0.5.0
            ("0.4.0", "latest"), # Skip 0.5.0, 0.6.0
            ("0.2.0", "latest")  # Skip all intermediate
        ]
    }


@pytest.fixture(autouse=True)
def migration_test_logging(request):
    """Setup logging for each migration test."""
    test_name = request.node.name
    logger.info(f"🧪 Starting migration test: {test_name}")

    yield

    logger.info(f"✅ Completed migration test: {test_name}")


@pytest.fixture
def docker_compose_file():
    """Return path to docker-compose file for PostgreSQL testing."""
    compose_content = '''
version: "3.9"

networks:
  migration_test:
    driver: bridge

volumes:
  postgres_data:
    labels:
      migration-test: "true"

services:
  postgres:
    image: postgres:17
    environment:
      - POSTGRES_USER=test_user
      - POSTGRES_PASSWORD=test_migration_password_123
      - POSTGRES_DB=mcp_test
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [migration_test]
    labels:
      migration-test: "true"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test_user -d mcp_test"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  gateway:
    image: ${IMAGE_LOCAL:-ghcr.io/ibm/mcp-context-forge:latest}
    environment:
      - DATABASE_URL=postgresql://test_user:test_migration_password_123@postgres:5432/mcp_test
      - REDIS_URL=redis://redis:6379/0
      - MCPGATEWAY_UI_ENABLED=false
      - MCPGATEWAY_ADMIN_API_ENABLED=true
      - AUTH_REQUIRED=false
      - LOG_LEVEL=INFO
      - PYTHONUNBUFFERED=1
    ports:
      - "0:4444"  # Random host port
    networks: [migration_test]
    labels:
      migration-test: "true"
    depends_on:
      postgres:
        condition: service_healthy

  redis:
    image: redis:latest
    networks: [migration_test]
    labels:
      migration-test: "true"
'''

    # Write compose file to temporary location
    compose_file = Path("tests/migration/docker-compose.test.yml")
    compose_file.parent.mkdir(parents=True, exist_ok=True)

    with open(compose_file, 'w') as f:
        f.write(compose_content)

    logger.info(f"📄 Created docker-compose file: {compose_file}")
    return str(compose_file)


# Performance testing fixtures
@pytest.fixture(scope="session")
def performance_thresholds():
    """Define performance thresholds for migration tests."""
    return {
        "sqlite_upgrade": {
            "max_duration": 30,      # seconds
            "max_memory_mb": 256     # MB
        },
        "postgres_upgrade": {
            "max_duration": 120,     # seconds
            "max_memory_mb": 512     # MB
        },
        "large_dataset": {
            "max_duration": 300,     # seconds
            "max_memory_mb": 1024    # MB
        },
        "skip_version": {
            "max_duration": 60,      # seconds
            "max_memory_mb": 512     # MB
        }
    }


# Cleanup and reporting fixtures
@pytest.fixture(scope="session", autouse=True)
def migration_test_session_setup_teardown():
    """Session-level setup and teardown for migration tests."""
    logger.info("🚀 Starting migration test session")

    # Create reports directory
    reports_dir = Path("tests/migration/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    yield

    logger.info("✅ Migration test session completed")
    logger.info(f"📊 Test reports available in: {reports_dir}")


@pytest.fixture
def test_result_collector():
    """Collect test results for reporting."""
    results = []

    def collect_result(result):
        results.append(result)
        logger.info(f"📊 Collected test result: {result.get('test_name', 'unknown')}")

    yield collect_result

    # Save results at end of test
    if results:
        results_file = Path("tests/migration/reports/test_results.json")
        # Standard
        import json
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"💾 Saved {len(results)} test results to {results_file}")


# Parameterization helpers
def pytest_generate_tests(metafunc):
    """Generate parameterized tests for version combinations using n-2 policy."""
    if "version_pair" in metafunc.fixturenames:
        # Generate version pairs for forward migration testing (n-2 policy)
        pairs = VersionConfig.get_forward_migration_pairs()
        metafunc.parametrize("version_pair", pairs,
                           ids=[f"{p[0]}-to-{p[1]}" for p in pairs])

    elif "reverse_version_pair" in metafunc.fixturenames:
        # Generate version pairs for reverse migration testing (n-2 policy)
        pairs = VersionConfig.get_reverse_migration_pairs()
        metafunc.parametrize("reverse_version_pair", pairs,
                           ids=[f"{p[0]}-to-{p[1]}" for p in pairs])

    elif "skip_version_pair" in metafunc.fixturenames:
        # Generate version pairs for skip-version migration testing (n-2 policy)
        pairs = VersionConfig.get_skip_version_pairs()
        if pairs:  # Only parametrize if we have pairs
            metafunc.parametrize("skip_version_pair", pairs,
                               ids=[f"{p[0]}-to-{p[1]}" for p in pairs])


# Mock fixtures for testing without containers (if needed)
@pytest.fixture
def mock_container_manager():
    """Mock container manager for testing without actual containers."""
    # Standard
    from unittest.mock import MagicMock, Mock

    mock_cm = Mock(spec=ContainerManager)
    mock_cm.runtime = "mock"
    mock_cm.active_containers = []
    mock_cm.AVAILABLE_VERSIONS = ["0.5.0", "0.6.0", "latest"]

    # Mock methods with realistic behavior
    mock_cm.pull_images = MagicMock(return_value=None)
    mock_cm.start_sqlite_container = MagicMock(return_value="mock_container_id")
    mock_cm.exec_alembic_command = MagicMock(return_value="INFO  [alembic.runtime.migration] Context impl SQLiteImpl.")
    mock_cm.get_database_schema = MagicMock(return_value="CREATE TABLE tools (id INTEGER PRIMARY KEY);")
    mock_cm.seed_test_data = MagicMock(return_value=None)
    mock_cm.cleanup_container = MagicMock(return_value=None)
    mock_cm.cleanup_all = MagicMock(return_value=None)

    return mock_cm
