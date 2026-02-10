# -*- coding: utf-8 -*-
"""Location: ./tests/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
import os
import sys
import tempfile
import warnings
from unittest.mock import AsyncMock

# Set environment variable BEFORE any other imports to disable Redis in tests
# This must happen at module level, before pytest collects tests
os.environ["METRICS_CACHE_USE_REDIS"] = "false"

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_SQLITE_MEMORY_URL = "sqlite:///:memory:"
EXTERNAL_TEST_DB_OPT_IN_ENV = "MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB"
EXTERNAL_TEST_DB_OPT_IN_FLAGS = {"--allow-external-db", "--yes-external-db"}
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _is_external_db_opted_in() -> bool:
    """Return True when external test DB usage is explicitly enabled."""
    env_opt_in = os.getenv(EXTERNAL_TEST_DB_OPT_IN_ENV, "").strip().lower() in _TRUTHY_ENV_VALUES
    cli_opt_in = any(flag in sys.argv for flag in EXTERNAL_TEST_DB_OPT_IN_FLAGS)
    return env_opt_in or cli_opt_in


def _force_safe_test_db_defaults() -> None:
    """Force hermetic in-memory SQLite defaults unless external DB is explicitly enabled."""
    if _is_external_db_opted_in():
        return

    configured = []

    db_env = os.getenv("DB")
    if db_env and db_env.strip().lower() in {"postgres", "mariadb"}:
        configured.append(f"DB={db_env}")

    database_url_env = os.getenv("DATABASE_URL")
    if database_url_env and database_url_env != TEST_SQLITE_MEMORY_URL:
        configured.append("DATABASE_URL=<set>")

    test_database_url_env = os.getenv("TEST_DATABASE_URL")
    if test_database_url_env and test_database_url_env != TEST_SQLITE_MEMORY_URL:
        configured.append("TEST_DATABASE_URL=<set>")

    if configured:
        warnings.warn(
            "External DB-related test env ignored "
            f"({', '.join(configured)}). "
            f"Set {EXTERNAL_TEST_DB_OPT_IN_ENV}=1 or pass --allow-external-db to allow it. "
            f"Using {TEST_SQLITE_MEMORY_URL}.",
            UserWarning,
            stacklevel=2,
        )

    # Hard-force hermetic defaults even if host env has DB/DATABASE_URL configured.
    os.environ["DB"] = "sqlite"
    os.environ["DATABASE_URL"] = TEST_SQLITE_MEMORY_URL
    os.environ["TEST_DATABASE_URL"] = TEST_SQLITE_MEMORY_URL


_force_safe_test_db_defaults()

# First-Party
import mcpgateway.db as db_mod  # noqa: E402  # must load after test DB env hardening
from mcpgateway.config import Settings  # noqa: E402  # must load after test DB env hardening

# Local

# Skip session-level RBAC patching for now - let individual tests handle it
# _session_rbac_originals = patch_rbac_decorators()


def pytest_addoption(parser):
    """Add explicit opt-in flags for running tests against external databases."""
    parser.addoption(
        "--allow-external-db",
        "--yes-external-db",
        action="store_true",
        default=False,
        help=f"Allow external test DB backends (same as setting {EXTERNAL_TEST_DB_OPT_IN_ENV}=1).",
    )


def resolve_test_db_url():
    """Return DB URL for tests.

    Default behavior is hermetic in-memory SQLite.
    External DB backends are only allowed when explicitly enabled with:
      MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB=1
    """
    if not _is_external_db_opted_in():
        return TEST_SQLITE_MEMORY_URL

    explicit_test_url = os.getenv("TEST_DATABASE_URL")
    if explicit_test_url:
        return explicit_test_url

    db = os.getenv("DB", "sqlite").lower()

    if db == "sqlite":
        return TEST_SQLITE_MEMORY_URL

    if db == "postgres":
        # Matches GitHub Service container
        return "postgresql://postgres:test@localhost:5432/test"

    if db == "mariadb":
        # Matches gitHub service container + compatible driver
        return "mysql+pymysql://root:test@localhost:3306/test"

    raise ValueError(f"Unsupported test DB type: {db}")


@pytest.fixture(scope="session")
def test_db_url():
    return resolve_test_db_url()


@pytest.fixture(scope="session")
def test_engine(test_db_url):
    """Create a SQLAlchemy engine for testing."""
    if test_db_url.startswith("sqlite"):
        engine = create_engine(
            test_db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(test_db_url)

    db_mod.Base.metadata.create_all(bind=engine)
    yield engine
    try:
        db_mod.Base.metadata.drop_all(bind=engine)
    finally:
        engine.dispose()
        if os.path.exists("./test.db"):
            os.remove("./test.db")


@pytest.fixture
def test_db(test_engine):
    """Create a fresh database session for a test."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_settings():
    """Create test settings with in-memory database."""
    return Settings(
        database_url="sqlite:///:memory:",
        basic_auth_user="testuser",
        basic_auth_password="testpass",
        auth_required=False,
        mcp_client_auth_enabled=False,
    )


@pytest.fixture
def app():
    """Create a FastAPI test application with proper database setup."""
    # Use the existing app_with_temp_db fixture logic which works correctly
    mp = MonkeyPatch()

    # 1) create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # 2) patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    # Disable auth for tests - allows dependency injection mocking to work
    mp.setattr(settings, "auth_required", False, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)

    # 4) patch the already‑imported main module **without reloading**
    # First-Party
    import mcpgateway.main as main_mod

    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)

    # Also patch security_logger and auth_middleware's SessionLocal
    # First-Party
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod

    mp.setattr(auth_middleware_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(sec_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(struct_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(audit_trail_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(log_aggregator_mod, "SessionLocal", TestSessionLocal, raising=False)

    # 4) create schema
    db_mod.Base.metadata.create_all(bind=engine)

    # First-Party
    from mcpgateway.main import app

    yield app

    # 6) teardown
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def mock_http_client():
    """Create a mock HTTP client."""
    mock = AsyncMock()
    mock.aclose = AsyncMock()
    return mock


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    mock = AsyncMock()
    mock.accept = AsyncMock()
    mock.send_json = AsyncMock()
    mock.receive_json = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture(scope="module")  # one DB per test module is usually fine
def app_with_temp_db():
    """Return a FastAPI app wired to a fresh SQLite database."""
    mp = MonkeyPatch()

    # 1) create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # 2) patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)
    # Disable auth for tests - allows dependency injection mocking to work
    mp.setattr(settings, "auth_required", False, raising=False)

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)

    # 4) patch the already‑imported main module **without reloading**
    # First-Party
    import mcpgateway.main as main_mod

    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)

    # Also patch security_logger and auth_middleware's SessionLocal
    # First-Party
    import mcpgateway.middleware.auth_middleware as auth_middleware_mod
    import mcpgateway.services.security_logger as sec_logger_mod
    import mcpgateway.services.structured_logger as struct_logger_mod
    import mcpgateway.services.audit_trail_service as audit_trail_mod
    import mcpgateway.services.log_aggregator as log_aggregator_mod

    mp.setattr(auth_middleware_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(sec_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(struct_logger_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(audit_trail_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(log_aggregator_mod, "SessionLocal", TestSessionLocal, raising=False)

    # 4) create schema
    db_mod.Base.metadata.create_all(bind=engine)

    # 5) reload main so routers, deps pick up new SessionLocal
    # if "mcpgateway.main" in sys.modules:
    #     import importlib

    #     importlib.reload(sys.modules["mcpgateway.main"])
    # else:
    #     import mcpgateway.main  # noqa: F401

    # First-Party
    from mcpgateway.main import app

    yield app

    # 6) teardown
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


def pytest_sessionfinish(session, exitstatus):
    """Clean up resources at the end of the test session."""
    # Dispose the module-level engine to close all SQLite connections
    # This prevents ResourceWarning about unclosed database connections
    try:
        if hasattr(db_mod, "engine") and db_mod.engine is not None:
            db_mod.engine.dispose()
    except Exception:
        pass  # Ignore errors during cleanup


# ---------------------------------------------------------------------------
# Query counting fixtures for performance testing and N+1 detection
# ---------------------------------------------------------------------------


@pytest.fixture
def query_counter(test_engine):
    """Fixture to count database queries in tests.

    Usage:
        def test_something(query_counter, test_db):
            with query_counter() as counter:
                # do database operations
            assert counter.count <= 5, f"Too many queries: {counter.count}"

    Args:
        test_engine: SQLAlchemy engine fixture

    Returns:
        Callable that returns a context manager for counting queries
    """
    # Local
    from tests.helpers.query_counter import count_queries

    def _counter(print_queries: bool = False, print_summary: bool = False):
        return count_queries(test_engine, print_queries=print_queries, print_summary=print_summary)

    return _counter


@pytest.fixture
def assert_max_queries(test_engine):
    """Fixture to assert maximum query count in tests.

    Usage:
        def test_list_tools(assert_max_queries, test_db):
            with assert_max_queries(5):
                tools = tool_service.list_tools(test_db)

    Args:
        test_engine: SQLAlchemy engine fixture

    Returns:
        Context manager that raises AssertionError if query limit exceeded
    """
    # Local
    from tests.helpers.query_counter import assert_max_queries as _assert_max

    def _fixture(max_count: int, message: str = None):
        return _assert_max(test_engine, max_count, message)

    return _fixture


# ---------------------------------------------------------------------------
# Cache invalidation fixtures for test isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_metrics_cache():
    """Clear the metrics cache before and after each test to ensure isolation.

    This prevents cached values from one test affecting subsequent tests.
    """
    try:
        from mcpgateway.cache.metrics_cache import metrics_cache

        metrics_cache.invalidate()
    except ImportError:
        pass  # Cache module not available

    yield

    try:
        from mcpgateway.cache.metrics_cache import metrics_cache

        metrics_cache.invalidate()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def clear_jwt_cache_between_tests():
    """Ensure JWT caches are cleared between tests for isolation.

    This fixture runs automatically before and after each test to prevent
    cached JWT configuration from leaking between tests that mock different
    settings.
    """
    try:
        from mcpgateway.utils.jwt_config_helper import clear_jwt_caches

        clear_jwt_caches()
    except ImportError:
        pass  # Module not available

    yield

    try:
        from mcpgateway.utils.jwt_config_helper import clear_jwt_caches

        clear_jwt_caches()
    except ImportError:
        pass
