# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_observability_timeseries_postgres.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

PostgreSQL integration coverage for durable observability timeseries.
"""

# Standard
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import os
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import ObservabilityTrace
from mcpgateway.services.observability_service import _execution_timeseries_postgresql, _execution_timeseries_python


def _postgres_url() -> str:
    """Return the explicitly configured PostgreSQL test URL."""
    return os.getenv("MCPGATEWAY_TEST_POSTGRES_URL") or os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL", "")


def _postgres_test_enabled() -> bool:
    """Return whether external PostgreSQL testing is explicitly enabled."""
    external_db_enabled = os.getenv("MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB", "").strip().lower() in {"1", "true", "yes", "on"}
    return external_db_enabled and _postgres_url().lower().startswith("postgresql")


pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgresql,
    pytest.mark.skipif(
        not _postgres_test_enabled(),
        reason="PostgreSQL-gated: set MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB=1 and MCPGATEWAY_TEST_POSTGRES_URL",
    ),
]


@pytest.fixture(name="postgres_session")
def _postgres_session() -> Iterator[Session]:
    """Yield a rollback-isolated session connected to real PostgreSQL."""
    engine = create_engine(_postgres_url())
    trace_table = ObservabilityTrace.__table__
    table_created = not inspect(engine).has_table(trace_table.name)
    if table_created:
        trace_table.create(bind=engine)

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        if table_created:
            trace_table.drop(bind=engine, checkfirst=True)
        engine.dispose()


def test_postgresql_and_python_timeseries_paths_match_for_same_traces(postgres_session: Session) -> None:
    """Both bucketing paths return identical status counts for the same PostgreSQL rows."""
    first_bucket = datetime(2100, 1, 1, 12, 0, tzinfo=timezone.utc)
    traces = [
        ObservabilityTrace(trace_id=str(uuid.uuid4()), name="postgres-parity-ok", start_time=first_bucket + timedelta(minutes=5), status="ok"),
        ObservabilityTrace(trace_id=str(uuid.uuid4()), name="postgres-parity-error", start_time=first_bucket + timedelta(minutes=10), status="error"),
        ObservabilityTrace(trace_id=str(uuid.uuid4()), name="postgres-parity-unset", start_time=first_bucket + timedelta(minutes=15), status="unset"),
        ObservabilityTrace(trace_id=str(uuid.uuid4()), name="postgres-parity-error", start_time=first_bucket + timedelta(minutes=65), status="error"),
        ObservabilityTrace(trace_id=str(uuid.uuid4()), name="postgres-parity-error", start_time=first_bucket + timedelta(minutes=70), status="error"),
    ]
    postgres_session.add_all(traces)
    postgres_session.flush()

    postgresql_result = _execution_timeseries_postgresql(postgres_session, first_bucket, 60)
    python_result = _execution_timeseries_python(postgres_session, first_bucket, 60)

    expected = {
        "buckets": ["2100-01-01T12:00:00+00:00", "2100-01-01T13:00:00+00:00"],
        "values": [3, 2],
        "success_count": [1, 0],
        "error_count": [1, 2],
    }
    assert postgresql_result == expected
    assert python_result == expected
