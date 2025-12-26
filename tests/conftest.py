# -*- coding: utf-8 -*-
"""Location: ./tests/conftest.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
"""

# Standard
import os
import tempfile
from unittest.mock import AsyncMock

# Third-Party
from _pytest.monkeypatch import MonkeyPatch
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.config import Settings

# Local

# Skip session-level RBAC patching for now - let individual tests handle it
# _session_rbac_originals = patch_rbac_decorators()


def resolve_test_db_url():
    """Return DB URL based on GitHub Actions matrix or default to SQLite."""
    db = os.getenv("DB", "sqlite").lower()

    if db == "sqlite":
        return "sqlite:///:memory:"

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
    db_mod.Base.metadata.drop_all(bind=engine)
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


@pytest_asyncio.fixture
async def async_test_db():
    """Create a fresh async database session for a test.

    Uses aiosqlite for async SQLite support in tests.
    """
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    async_url = f"sqlite+aiosqlite:///{path}"
    sync_url = f"sqlite:///{path}"

    # Create sync engine for schema creation
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db_mod.Base.metadata.create_all(bind=sync_engine)

    # Create async engine and session
    async_engine = create_async_engine(async_url, echo=False)
    TestAsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestAsyncSessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    await async_engine.dispose()
    sync_engine.dispose()
    os.close(fd)
    os.unlink(path)


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
    """Create a FastAPI test application with proper async database setup.

    Uses aiosqlite for async SQLite support so that services using async
    database operations work correctly in tests.
    """
    import asyncio

    mp = MonkeyPatch()

    # 1) create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    sync_url = f"sqlite:///{path}"
    async_url = f"sqlite+aiosqlite:///{path}"

    # 2) patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", async_url, raising=False)

    # Create sync engine for schema creation (metadata.create_all needs sync)
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

    # Create async engine and session factory for actual operations
    test_async_engine = create_async_engine(async_url, echo=False)
    TestAsyncSessionLocal = async_sessionmaker(
        bind=test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Patch db module with async engine and session
    mp.setattr(db_mod, "engine", sync_engine, raising=False)
    mp.setattr(db_mod, "async_engine", test_async_engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(db_mod, "AsyncSessionLocal", TestAsyncSessionLocal, raising=False)
    mp.setattr(db_mod, "_use_async", True, raising=False)

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

    # Enable async mode for services
    mp.setattr(auth_middleware_mod, "_use_async", True, raising=False)
    mp.setattr(auth_middleware_mod, "AsyncSessionLocal", TestAsyncSessionLocal, raising=False)

    # 4) create schema using sync engine
    db_mod.Base.metadata.create_all(bind=sync_engine)

    # First-Party
    from mcpgateway.main import app

    yield app

    # 6) teardown
    mp.undo()

    # Dispose async engine properly
    async def dispose_async():
        await test_async_engine.dispose()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(dispose_async())
        else:
            loop.run_until_complete(dispose_async())
    except RuntimeError:
        asyncio.run(dispose_async())

    sync_engine.dispose()
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
    """Return a FastAPI app wired to a fresh async SQLite database.

    Uses aiosqlite for async SQLite support so that services using async
    database operations work correctly in tests.
    """
    import asyncio

    mp = MonkeyPatch()

    # 1) create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    sync_url = f"sqlite:///{path}"
    async_url = f"sqlite+aiosqlite:///{path}"

    # 2) patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", async_url, raising=False)

    # Create sync engine for schema creation (metadata.create_all needs sync)
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

    # Create async engine and session factory for actual operations
    test_async_engine = create_async_engine(async_url, echo=False)
    TestAsyncSessionLocal = async_sessionmaker(
        bind=test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    # Patch db module with async engine and session
    mp.setattr(db_mod, "engine", sync_engine, raising=False)
    mp.setattr(db_mod, "async_engine", test_async_engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(db_mod, "AsyncSessionLocal", TestAsyncSessionLocal, raising=False)
    mp.setattr(db_mod, "_use_async", True, raising=False)

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

    # Enable async mode for services
    mp.setattr(auth_middleware_mod, "_use_async", True, raising=False)
    mp.setattr(auth_middleware_mod, "AsyncSessionLocal", TestAsyncSessionLocal, raising=False)

    # 4) create schema using sync engine
    db_mod.Base.metadata.create_all(bind=sync_engine)

    # First-Party
    from mcpgateway.main import app

    yield app

    # 6) teardown
    mp.undo()

    # Dispose async engine properly
    async def dispose_async():
        await test_async_engine.dispose()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(dispose_async())
        else:
            loop.run_until_complete(dispose_async())
    except RuntimeError:
        asyncio.run(dispose_async())

    sync_engine.dispose()
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
