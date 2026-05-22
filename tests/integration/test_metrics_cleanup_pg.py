# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_metrics_cleanup_pg.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Suresh Kumar Moharajan

Postgres-gated integration tests for MetricsCleanupService._cleanup_table.

Verifies that the batched-delete logic (with inter-batch sleep) correctly
removes rows older than the retention cutoff from a real database while
leaving rows within the window untouched.

Skip condition: runs only when DATABASE_URL points at a PostgreSQL instance
(i.e. when MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB=1 is set and DATABASE_URL is
a postgresql:// URL).  In the default hermetic test run the conftest forces
sqlite:///:memory: and these tests are automatically skipped.
"""

# Standard
from datetime import datetime, timedelta, timezone
import os
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

# First-Party
import mcpgateway.db as db_mod
from mcpgateway.db import Base, Tool, ToolMetric

try:
    from mcpgateway.services.metrics_cleanup_service import MetricsCleanupService as _MetricsCleanupService

    _CLEANUP_IMPORTABLE = True
except ImportError:
    _MetricsCleanupService = None  # type: ignore[assignment,misc]
    _CLEANUP_IMPORTABLE = False


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------


def _is_postgresql() -> bool:
    db_env = os.getenv("DB", "").lower()
    database_url = os.getenv("DATABASE_URL", "").lower()
    return db_env == "postgres" or "postgresql" in database_url


SKIP_IF_NOT_POSTGRES = pytest.mark.skipif(
    not _is_postgresql() or not _CLEANUP_IMPORTABLE,
    reason="Postgres-gated: set MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB=1 and DATABASE_URL=postgresql://... (also requires cpex installed)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    """Real Postgres engine for the duration of this test module."""
    url = os.getenv("DATABASE_URL")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine, monkeypatch):
    """Session bound to the Postgres engine; patches db_mod.SessionLocal so
    fresh_db_session() inside _cleanup_table picks up the same engine."""
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestSession, raising=True)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture()
def seeded_tool(pg_session):
    """Insert a Tool row; yield its id; delete it (cascades metrics) on teardown."""
    tool_id = uuid.uuid4().hex
    tool = Tool(
        id=tool_id,
        original_name="cleanup-test-tool",
        custom_name="cleanup-test-tool",
        custom_name_slug=f"cleanup-test-tool-{tool_id}",
        input_schema={},
    )
    tool.name = f"cleanup-test-tool-{tool_id}"
    pg_session.add(tool)
    pg_session.commit()
    yield tool_id
    pg_session.delete(pg_session.get(Tool, tool_id))
    pg_session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)
_NOW = datetime.now(timezone.utc)


def _add_metrics(session, tool_id: str, timestamps: list) -> None:
    for ts in timestamps:
        session.add(ToolMetric(tool_id=tool_id, timestamp=ts, response_time=0.01, is_success=True))
    session.commit()


def _count_metrics(session, tool_id: str) -> int:
    return session.execute(select(func.count()).select_from(ToolMetric).where(ToolMetric.tool_id == tool_id)).scalar() or 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@SKIP_IF_NOT_POSTGRES
def test_cleanup_table_deletes_old_rows_keeps_recent(seeded_tool, pg_session):
    """5 old rows deleted, 3 recent rows survive."""
    old_ts = [_OLD + timedelta(days=i) for i in range(5)]
    recent_ts = [_NOW - timedelta(hours=i) for i in range(3)]
    _add_metrics(pg_session, seeded_tool, old_ts + recent_ts)

    assert _count_metrics(pg_session, seeded_tool) == 8

    cutoff = _NOW - timedelta(days=30)
    service = _MetricsCleanupService()
    service.batch_size = 10  # single batch — all 5 old rows gone in one pass
    service.batch_sleep_ms = 0  # no sleep in tests

    result = service._cleanup_table(ToolMetric, "tool_metrics", cutoff)

    assert result.error is None
    assert result.deleted_count == 5
    assert _count_metrics(pg_session, seeded_tool) == 3
    assert result.duration_seconds > 0


@SKIP_IF_NOT_POSTGRES
def test_cleanup_table_multi_batch_deletes_all_old(seeded_tool, pg_session):
    """With batch_size=2 and 6 old rows, cleanup runs 3 batches and deletes all 6."""
    old_ts = [_OLD + timedelta(days=i) for i in range(6)]
    _add_metrics(pg_session, seeded_tool, old_ts)

    assert _count_metrics(pg_session, seeded_tool) == 6

    cutoff = _NOW - timedelta(days=30)
    service = _MetricsCleanupService()
    service.batch_size = 2
    service.batch_sleep_ms = 0

    result = service._cleanup_table(ToolMetric, "tool_metrics", cutoff)

    assert result.error is None
    assert result.deleted_count == 6
    assert _count_metrics(pg_session, seeded_tool) == 0
    assert result.remaining_count == 0


@SKIP_IF_NOT_POSTGRES
def test_cleanup_table_empty_table_noop(seeded_tool, pg_session):
    """No rows → deleted_count == 0, no error."""
    assert _count_metrics(pg_session, seeded_tool) == 0

    cutoff = _NOW - timedelta(days=30)
    service = _MetricsCleanupService()
    service.batch_sleep_ms = 0

    result = service._cleanup_table(ToolMetric, "tool_metrics", cutoff)

    assert result.error is None
    assert result.deleted_count == 0


@SKIP_IF_NOT_POSTGRES
def test_cleanup_table_nothing_to_delete_when_all_recent(seeded_tool, pg_session):
    """All rows within retention window → none deleted."""
    recent_ts = [_NOW - timedelta(hours=i) for i in range(4)]
    _add_metrics(pg_session, seeded_tool, recent_ts)

    cutoff = _NOW - timedelta(days=30)
    service = _MetricsCleanupService()
    service.batch_sleep_ms = 0

    result = service._cleanup_table(ToolMetric, "tool_metrics", cutoff)

    assert result.error is None
    assert result.deleted_count == 0
    assert _count_metrics(pg_session, seeded_tool) == 4
