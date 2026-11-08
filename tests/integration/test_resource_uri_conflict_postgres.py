# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_resource_uri_conflict_postgres.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify resource conflict checks with independent PostgreSQL transactions.
Enable external test databases and supply a disposable TEST_DATABASE_URL.
"""

# Standard
import asyncio
from concurrent.futures import Future
import os
from unittest.mock import AsyncMock, MagicMock
import uuid

# Third-Party
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Resource as DbResource
from mcpgateway.schemas import ResourceCreate, ResourceUpdate
from mcpgateway.services.resource_service import ResourceError, ResourceService, ResourceURIConflictError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("MCPGATEWAY_TEST_ALLOW_EXTERNAL_DB") != "1", reason="Requires an explicitly enabled disposable PostgreSQL database"),
]


@pytest.fixture(scope="module")
def postgres_engine():
    """Create the schema only in an explicitly selected disposable PostgreSQL database."""
    url = os.environ.get("TEST_DATABASE_URL")
    assert url, "Set TEST_DATABASE_URL for the required PostgreSQL run"
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql", "The required locking tests must use PostgreSQL"
    assert (engine.url.database or "").startswith("uri5955_"), "Use a disposable database named uri5955_<unique suffix>"
    try:
        with engine.connect() as connection:
            assert 180000 <= int(connection.scalar(text("SHOW server_version_num"))) < 190000
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def resource_service(monkeypatch):
    """Keep external notifications and audit writes outside the tested transaction."""
    monkeypatch.setenv("PLUGINS_ENABLED", "false")
    monkeypatch.setattr("mcpgateway.services.resource_service.audit_trail", MagicMock())
    monkeypatch.setattr("mcpgateway.services.resource_service.structured_logger", MagicMock())
    service = ResourceService()
    monkeypatch.setattr(service, "_notify_resource_added", AsyncMock())
    monkeypatch.setattr(service, "_notify_resource_updated", AsyncMock())
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "team", "private"])
@pytest.mark.parametrize("locked_row", ["target", "conflict"])
async def test_resource_uri_checks_preserve_postgres_locking(postgres_engine, resource_service, visibility, locked_row):
    """Updates wait for row locks while creation reads committed conflicts without waiting."""
    session_factory = sessionmaker(bind=postgres_engine)
    suffix = uuid.uuid4().hex
    owner = f"owner-{suffix}@example.com"
    team_id = uuid.uuid4().hex
    gateway_id = uuid.uuid4().hex
    conflict_id = uuid.uuid4().hex
    target_id = uuid.uuid4().hex
    uri = f"file://occupied-{suffix}.txt"
    with session_factory() as setup:
        setup.add(EmailUser(email=owner, full_name="Test Owner", is_active=True))
        setup.flush()
        setup.add(EmailTeam(id=team_id, name="Test Team", slug=f"team-{suffix}", created_by=owner))
        setup.flush()
        setup.add(DbGateway(id=gateway_id, name=f"gateway-{suffix}", slug=f"gateway-{suffix}", url="http://example.com/mcp", transport="sse", capabilities={}))
        setup.flush()
        scope = {"visibility": visibility, "team_id": team_id, "owner_email": owner, "gateway_id": gateway_id}
        setup.add_all(
            [
                DbResource(id=conflict_id, uri=uri, name="Occupied", **scope),
                DbResource(id=target_id, uri=f"file://available-{suffix}.txt", name="Target", **scope),
            ]
        )
        setup.commit()

    with session_factory() as holder:
        holder.execute(select(DbResource).where(DbResource.id == (target_id if locked_row == "target" else conflict_id)).with_for_update())
        with session_factory() as updater:
            updater.execute(text("SET LOCAL lock_timeout = '200ms'"))
            updater.execute(text("SET LOCAL statement_timeout = '3s'"))
            with pytest.raises(ResourceError) as caught:
                await resource_service.update_resource(updater, target_id, ResourceUpdate(uri=uri))
            cause = caught.value.__cause__ or caught.value.__context__
            assert isinstance(cause, OperationalError)
            assert getattr(cause.orig, "sqlstate", None) == "55P03"
        with session_factory() as creator:
            creator.execute(text("SET LOCAL lock_timeout = '200ms'"))
            creator.execute(text("SET LOCAL statement_timeout = '3s'"))
            with pytest.raises(ResourceURIConflictError) as caught:
                await resource_service.register_resource(
                    creator,
                    ResourceCreate(uri=uri, name="Duplicate", content="test", gateway_id=gateway_id),
                    visibility=visibility,
                    team_id=team_id,
                    owner_email=owner,
                    created_by=owner,
                )
            assert caught.value.resource_id == conflict_id
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        updater_pid: Future[int] = Future()

        def update_in_worker() -> None:
            with session_factory() as updater:
                updater.execute(text("SET LOCAL statement_timeout = '15s'"))
                updater_pid.set_result(updater.scalar(text("SELECT pg_backend_pid()")))
                asyncio.run(resource_service.update_resource(updater, target_id, ResourceUpdate(uri=uri)))

        update = asyncio.create_task(asyncio.to_thread(update_in_worker))
        try:
            async with asyncio.timeout(5):
                pid = await asyncio.shield(asyncio.wrap_future(updater_pid))
                with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                    while True:
                        assert not update.done(), "Update finished before PostgreSQL reported a lock wait"
                        waiting = observer.scalar(
                            text("SELECT wait_event_type = 'Lock' AND :holder_pid = ANY(pg_blocking_pids(pid)) FROM pg_stat_activity WHERE pid = :updater_pid"),
                            {"holder_pid": holder_pid, "updater_pid": pid},
                        )
                        if waiting:
                            break
                        await asyncio.sleep(0.025)
        except TimeoutError:
            pytest.fail("PostgreSQL did not report the expected lock wait within five seconds")
        finally:
            holder.rollback()
            await asyncio.gather(update, return_exceptions=True)

    with pytest.raises(ResourceURIConflictError) as caught:
        await update
    assert caught.value.resource_id == conflict_id
    assert caught.value.uri == uri
    assert caught.value.enabled is True

    with session_factory() as verifier:
        target = verifier.get(DbResource, target_id)
        assert target is not None
        assert target.uri == f"file://available-{suffix}.txt"
