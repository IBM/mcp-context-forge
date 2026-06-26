# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

GatewayService helper tests.
"""

# Standard
import asyncio
from datetime import datetime, timezone
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, Mock

# Third-Party
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Base, Gateway as DbGateway
from mcpgateway.schemas import GatewayRead
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayNameConflictError, GatewayNotFoundError, GatewayService, OAuthToolValidationError
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.validation.tags import validate_tags_field


@pytest.fixture(autouse=True)
def _default_sync_gateway_lifecycle(monkeypatch):
    """Keep helper tests on sync lifecycle unless they opt into async mode."""
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)


def test_gateway_name_conflict_error_messages():
    error = GatewayNameConflictError("gw-name")
    assert "Public Gateway already exists" in str(error)
    assert error.enabled is True

    error_inactive = GatewayNameConflictError("gw-name", enabled=False, gateway_id=123, visibility="team")
    assert "Team-level Gateway already exists" in str(error_inactive)
    assert "currently inactive" in str(error_inactive)
    assert error_inactive.gateway_id == 123


def test_gateway_service_normalize_url():
    service = GatewayService()
    assert service.normalize_url("http://localhost:8080/path") == "http://localhost:8080/path"
    assert service.normalize_url("http://127.0.0.1:8080/path") == "http://localhost:8080/path"


def test_gateway_service_auth_headers():
    """Test that _get_auth_headers returns only Content-Type (no credentials).

    Gateway credentials are intentionally NOT included to prevent
    sending this gateway's credentials to remote servers.
    """
    service = GatewayService()
    headers = service._get_auth_headers()
    assert headers["Content-Type"] == "application/json"
    # Authorization is intentionally NOT included - each gateway should have its own auth_value
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers


def test_gateway_service_validate_tools():
    service = GatewayService()
    valid_tool = {"name": "tool-1", "integration_type": "REST", "request_type": "POST", "url": "http://example.com"}
    invalid_tool = {"name": None}

    valid, errors = service._validate_tools([valid_tool, invalid_tool])
    assert len(valid) == 1
    assert len(errors) == 1

    with pytest.raises(GatewayConnectionError):
        service._validate_tools([invalid_tool], context="default")

    with pytest.raises(OAuthToolValidationError):
        service._validate_tools([invalid_tool], context="oauth")


def test_gateway_service_lock_path_absolute(monkeypatch):
    monkeypatch.setattr(settings, "cache_type", "file")
    monkeypatch.setattr(settings, "filelock_name", "/var/tmp/gw.lock")

    service = GatewayService()

    assert service._lock_path.startswith(tempfile.gettempdir())
    assert service._lock_path.endswith("var/tmp/gw.lock")


def test_gateway_service_convert_gateway_to_read(monkeypatch):
    service = GatewayService()

    gateway = SimpleNamespace(
        auth_value={"token": "secret"},
        tags=["Analytics", "ml"],
        created_by="tester",
        modified_by=None,
        created_at=None,
        updated_at=None,
        version=None,
        team=None,
    )

    # Mock model_validate to return a mock that returns itself when masked() is called
    # and also stores the original dict for assertions
    class MockGatewayRead:
        def __init__(self, data):
            self._data = data
            self._masked_called = False

        def masked(self):
            self._masked_called = True
            return self

        def __getitem__(self, key):
            return self._data[key]

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: MockGatewayRead(x)))

    result = service.convert_gateway_to_read(gateway)
    assert decode_auth(result["auth_value"]) == {"token": "secret"}
    assert result["tags"] == validate_tags_field(["Analytics", "ml"])
    # SECURITY: Verify .masked() is called to prevent credential leakage
    assert result._masked_called, "convert_gateway_to_read must call .masked() to prevent credential leakage"


def test_gateway_service_validate_tools_valueerror(monkeypatch):
    service = GatewayService()

    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", lambda _data: (_ for _ in ()).throw(ValueError("JSON structure exceeds maximum depth")))

    with pytest.raises(GatewayConnectionError) as excinfo:
        service._validate_tools([{"name": "tool-depth"}])
    assert "schema too deeply nested" in str(excinfo.value)

    monkeypatch.setattr("mcpgateway.services.gateway_service.ToolCreate.model_validate", lambda _data: (_ for _ in ()).throw(ValueError("other")))

    with pytest.raises(GatewayConnectionError) as excinfo:
        service._validate_tools([{"name": "tool-other"}])
    assert "ValueError" in str(excinfo.value)


def test_hard_delete_gateway_deletes_children_and_gateway():
    service = GatewayService()
    gateway = SimpleNamespace(
        id="gw-1",
        tools=[SimpleNamespace(id="t1")],
        resources=[SimpleNamespace(id="r1")],
        prompts=[SimpleNamespace(id="p1")],
    )
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    service._hard_delete_gateway(db, gateway)

    assert db.execute.call_count == 11
    db.expire.assert_called_once_with(gateway)


def test_hard_delete_gateway_raises_when_gateway_row_missing():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-missing", tools=[], resources=[], prompts=[])
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(rowcount=0)

    with pytest.raises(GatewayNotFoundError, match="Gateway not found: gw-missing"):
        service._hard_delete_gateway(db, gateway)


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_once_dispatches_pending_gateway():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1", status="pending")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: gateway)
    service._process_pending_gateway = AsyncMock()
    service._process_deleting_gateway = AsyncMock()

    handled = await service._process_gateway_lifecycle_once(db, "gw-1")

    assert handled is True
    service._process_pending_gateway.assert_awaited_once_with(db, gateway)
    service._process_deleting_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_once_dispatches_deleting_gateway():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1", status="deleting")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: gateway)
    service._process_pending_gateway = AsyncMock()
    service._process_deleting_gateway = AsyncMock()

    handled = await service._process_gateway_lifecycle_once(db, "gw-1")

    assert handled is True
    service._process_deleting_gateway.assert_awaited_once_with(db, gateway)
    service._process_pending_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_once_ignores_non_lifecycle_status():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1", status="active")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: gateway)
    service._process_pending_gateway = AsyncMock()
    service._process_deleting_gateway = AsyncMock()

    handled = await service._process_gateway_lifecycle_once(db, "gw-1")

    assert handled is False
    service._process_pending_gateway.assert_not_called()
    service._process_deleting_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_once_returns_false_when_missing():
    service = GatewayService()
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)

    handled = await service._process_gateway_lifecycle_once(db, "gw-missing")

    assert handled is False


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_once_skips_foreign_claim():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1", status="pending", lifecycle_claimed_by="other-instance")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: gateway)
    service._process_pending_gateway = AsyncMock()

    handled = await service._process_gateway_lifecycle_once(db, "gw-1")

    assert handled is False
    service._process_pending_gateway.assert_not_called()


def test_get_due_gateway_lifecycle_ids_includes_deleting_and_due_pending(monkeypatch):
    service = GatewayService()
    fake_db = MagicMock()
    fake_db.execute.side_effect = [
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["gw-deleting"])),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["gw-pending-now", "gw-pending-retry"])),
    ]

    class FakeSessionFactory:
        def __call__(self):
            return self

        def __enter__(self):
            return fake_db

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", FakeSessionFactory())

    assert service._get_due_gateway_lifecycle_ids() == ["gw-deleting", "pending:gw-pending-now", "pending:gw-pending-retry"]


def test_split_gateway_lifecycle_ids_preserves_delete_priority():
    service = GatewayService()

    deleting_ids, pending_ids = service._split_gateway_lifecycle_ids(["gw-deleting", "pending:gw-pending-now", "pending:gw-pending-retry"])

    assert deleting_ids == ["gw-deleting"]
    assert pending_ids == ["gw-pending-now", "gw-pending-retry"]


def test_claim_due_gateway_lifecycle_ids_claims_due_unclaimed_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with TestingSessionLocal() as db:
            db.add(
                DbGateway(
                    id="gw-pending",
                    name="Pending Gateway",
                    slug="pending-gateway",
                    url="https://example.com/mcp",
                    transport="SSE",
                    capabilities={},
                    status="pending",
                )
            )
            db.commit()

        service = GatewayService()
        monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", TestingSessionLocal)
        monkeypatch.setattr(settings, "gateway_async_lifecycle_lease_seconds", 90)

        claimed_ids = service._claim_due_gateway_lifecycle_ids({"pending"})

        assert claimed_ids == ["gw-pending"]
        with TestingSessionLocal() as db:
            gateway = db.get(DbGateway, "gw-pending")
            assert gateway.lifecycle_claimed_by == service._instance_id
            assert gateway.lifecycle_claimed_at is not None
            assert gateway.lifecycle_claim_expires_at is not None
    finally:
        engine.dispose()


def test_claim_due_gateway_lifecycle_ids_returns_empty_for_no_statuses():
    service = GatewayService()

    assert service._claim_due_gateway_lifecycle_ids(set()) == []


def test_claim_due_gateway_lifecycle_ids_uses_postgres_skip_locked(monkeypatch):
    service = GatewayService()
    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.with_for_update.return_value = fake_query
    fake_db = MagicMock()
    fake_db.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    fake_db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    class FakeSessionFactory:
        def __call__(self):
            return self

        def __enter__(self):
            return fake_db

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.gateway_service.SessionLocal", FakeSessionFactory())
    monkeypatch.setattr("mcpgateway.services.gateway_service.select", MagicMock(return_value=fake_query))

    assert service._claim_due_gateway_lifecycle_ids({"deleting"}) == []
    fake_query.with_for_update.assert_called_once_with(skip_locked=True)


@pytest.mark.asyncio
async def test_process_pending_gateway_uses_dedicated_async_attempt_timeout(monkeypatch):
    service = GatewayService()
    monkeypatch.setattr(settings, "gateway_async_lifecycle_attempt_timeout", 120)
    observed_timeout = None

    gateway = SimpleNamespace(
        id="gw-pending",
        url="https://example.com/mcp",
        auth_type=None,
        auth_query_params=None,
        client_cert=None,
        client_key=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        lifecycle_claimed_by=service._instance_id,
        registration_attempts=0,
    )

    async def fake_initialize_gateway_with_timeout(**kwargs):
        nonlocal observed_timeout
        observed_timeout = kwargs["initialize_timeout"]
        raise RuntimeError("init failed")

    db = MagicMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    service._initialize_gateway_with_timeout = fake_initialize_gateway_with_timeout

    await service._process_pending_gateway(db, gateway)

    assert observed_timeout == 120
    compiled_params = db.execute.call_args.args[0].compile().params
    assert compiled_params["registration_attempts"] == 1
    assert compiled_params["lifecycle_claimed_by"] is None


@pytest.mark.asyncio
async def test_run_gateway_lifecycle_loop_logs_and_continues(monkeypatch):
    service = GatewayService()
    warning_log = Mock()
    service._run_gateway_lifecycle_pass = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("mcpgateway.services.gateway_service.logger.warning", warning_log)

    async def fake_sleep(_delay):
        raise asyncio.CancelledError()

    monkeypatch.setattr("mcpgateway.services.gateway_service.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await service._run_gateway_lifecycle_loop()

    warning_log.assert_called_once()


@pytest.mark.asyncio
async def test_run_gateway_lifecycle_pass_processes_due_gateways(monkeypatch):
    service = GatewayService()
    service._claim_due_gateway_lifecycle_ids = Mock(side_effect=[["gw-delete"], ["gw-pending"]])
    service._process_gateway_lifecycle_batch = AsyncMock()
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)

    await service._run_gateway_lifecycle_pass()

    service._process_gateway_lifecycle_batch.assert_has_awaits(
        [
            call(["gw-delete"]),
            call(["gw-pending"]),
        ]
    )


@pytest.mark.asyncio
async def test_run_gateway_lifecycle_pass_returns_early_when_disabled(monkeypatch):
    service = GatewayService()
    service._claim_due_gateway_lifecycle_ids = Mock()
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", False)

    await service._run_gateway_lifecycle_pass()

    service._claim_due_gateway_lifecycle_ids.assert_not_called()


@pytest.mark.asyncio
async def test_run_gateway_lifecycle_pass_logs_and_continues_on_error(monkeypatch):
    service = GatewayService()
    service._claim_due_gateway_lifecycle_ids = Mock(side_effect=[["gw-1"], []])
    service._process_gateway_lifecycle_once = AsyncMock(side_effect=RuntimeError("boom"))
    warning_log = Mock()
    monkeypatch.setattr(settings, "gateway_async_lifecycle_enabled", True)
    monkeypatch.setattr("mcpgateway.services.gateway_service.logger.warning", warning_log)

    class FakeFreshSession:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: FakeFreshSession())

    await service._run_gateway_lifecycle_pass()

    warning_log.assert_called_once()


@pytest.mark.asyncio
async def test_process_gateway_lifecycle_batch_uses_separate_sessions(monkeypatch):
    service = GatewayService()
    service._process_gateway_lifecycle_once = AsyncMock(return_value=True)

    db_one = MagicMock()
    db_two = MagicMock()
    sessions = [db_one, db_two]

    class FakeFreshSession:
        def __init__(self, db):
            self._db = db

        def __enter__(self):
            return self._db

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("mcpgateway.services.gateway_service.fresh_db_session", lambda: FakeFreshSession(sessions.pop(0)))
    monkeypatch.setattr(settings, "max_concurrent_health_checks", 2)

    await service._process_gateway_lifecycle_batch(["gw-1", "gw-2"])

    service._process_gateway_lifecycle_once.assert_has_awaits([call(db_one, "gw-1"), call(db_two, "gw-2")], any_order=True)


@pytest.mark.asyncio
async def test_process_pending_gateway_marks_gateway_active(monkeypatch):
    service = GatewayService()
    service._active_gateways = set()
    gateway = SimpleNamespace(
        id="gw-1",
        url="http://example.com",
        auth_type=None,
        auth_query_params=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        tools=[],
        resources=[],
        prompts=[],
        status="pending",
        status_message="pending",
        registration_attempts=3,
        next_retry_at="later",
        last_error="boom",
        reachable=False,
        capabilities={},
        last_seen=None,
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.refresh = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    registry_cache = SimpleNamespace(
        invalidate_gateways=AsyncMock(),
        invalidate_tools=AsyncMock(),
        invalidate_resources=AsyncMock(),
        invalidate_prompts=AsyncMock(),
    )
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", Mock())

    connection_material = SimpleNamespace(
        url="http://example.com",
        auth_query_params_decrypted=None,
        client_cert=None,
        client_key=None,
    )
    service._prepare_gateway_connection_material = AsyncMock(return_value=connection_material)
    service._initialize_gateway_with_timeout = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], [], []))
    service._sync_gateway_catalog = Mock(return_value=SimpleNamespace())
    service._reconcile_gateway_catalog = Mock()

    await service._process_pending_gateway(db, gateway)

    assert db.execute.call_count == 1
    assert "http://example.com" in service._active_gateways
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(gateway)
    registry_cache.invalidate_gateways.assert_awaited_once()
    registry_cache.invalidate_tools.assert_awaited_once()
    registry_cache.invalidate_resources.assert_awaited_once()
    registry_cache.invalidate_prompts.assert_awaited_once()
    tool_lookup_cache.invalidate_gateway.assert_awaited_once_with("gw-1")
    service._initialize_gateway_with_timeout.assert_awaited_once_with(
        url="http://example.com",
        authentication=None,
        transport="SSE",
        auth_type=None,
        oauth_config=None,
        ca_certificate=None,
        auth_query_params=None,
        client_cert=None,
        client_key=None,
        initialize_timeout=settings.gateway_async_lifecycle_attempt_timeout,
    )


def test_calculate_gateway_retry_backoff_caps_at_five_minutes():
    service = GatewayService()

    assert service._calculate_gateway_retry_backoff(1) == 1
    assert service._calculate_gateway_retry_backoff(2) == 2
    assert service._calculate_gateway_retry_backoff(3) == 4
    assert service._calculate_gateway_retry_backoff(9) == 256
    assert service._calculate_gateway_retry_backoff(10) == 300
    assert service._calculate_gateway_retry_backoff(11) == 300


@pytest.mark.asyncio
async def test_process_pending_gateway_records_retry_metadata_on_failure():
    service = GatewayService()
    gateway = SimpleNamespace(
        id="gw-1",
        url="http://example.com",
        auth_type=None,
        auth_query_params=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        tools=[],
        resources=[],
        prompts=[],
        status="pending",
        status_message=None,
        registration_attempts=2,
        next_retry_at=None,
        last_error=None,
        reachable=True,
        capabilities={},
        last_seen=None,
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.refresh = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    connection_material = SimpleNamespace(
        url="http://example.com",
        auth_query_params_decrypted=None,
        client_cert=None,
        client_key=None,
    )
    service._prepare_gateway_connection_material = AsyncMock(return_value=connection_material)
    service._initialize_gateway_with_timeout = AsyncMock(side_effect=RuntimeError("dial tcp refused"))
    service._sync_gateway_catalog = Mock()
    service._reconcile_gateway_catalog = Mock()

    before = datetime.now(timezone.utc)
    await service._process_pending_gateway(db, gateway)
    after = datetime.now(timezone.utc)

    expected_delay = service._calculate_gateway_retry_backoff(3)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(gateway)
    service._sync_gateway_catalog.assert_not_called()
    service._reconcile_gateway_catalog.assert_not_called()
    compiled_params = db.execute.call_args.args[0].compile().params
    assert compiled_params["registration_attempts"] == 3
    assert compiled_params["last_error"] == "dial tcp refused"
    assert compiled_params["status_message"] == "dial tcp refused"
    assert compiled_params["reachable"] is False
    lower_bound = before.timestamp() + expected_delay
    upper_bound = after.timestamp() + expected_delay
    assert lower_bound <= compiled_params["next_retry_at"].timestamp() <= upper_bound


@pytest.mark.asyncio
async def test_process_pending_gateway_timeout_records_retry_metadata():
    service = GatewayService()
    gateway = SimpleNamespace(
        id="gw-1",
        url="http://example.com",
        auth_type=None,
        auth_query_params=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        tools=[],
        resources=[],
        prompts=[],
        status="pending",
        status_message=None,
        registration_attempts=0,
        next_retry_at=None,
        last_error=None,
        reachable=True,
        capabilities={},
        last_seen=None,
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.refresh = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    connection_material = SimpleNamespace(
        url="http://example.com",
        auth_query_params_decrypted=None,
        client_cert=None,
        client_key=None,
    )
    service._prepare_gateway_connection_material = AsyncMock(return_value=connection_material)
    service._initialize_gateway_with_timeout = AsyncMock(
        side_effect=GatewayConnectionError("Gateway initialization timed out after 30s for http://example.com")
    )

    await service._process_pending_gateway(db, gateway)

    compiled_params = db.execute.call_args.args[0].compile().params
    assert compiled_params["registration_attempts"] == 1
    assert compiled_params["last_error"] == "Gateway initialization timed out after 30s for http://example.com"
    assert compiled_params["status_message"] == "Gateway initialization timed out after 30s for http://example.com"
    assert compiled_params["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_process_pending_gateway_does_not_overwrite_deleting_status(monkeypatch):
    service = GatewayService()
    service._active_gateways = set()
    gateway = SimpleNamespace(
        id="gw-1",
        url="http://example.com",
        auth_type=None,
        auth_query_params=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        tools=[],
        resources=[],
        prompts=[],
        status="pending",
        status_message=None,
        registration_attempts=0,
        next_retry_at=None,
        last_error=None,
        reachable=False,
        capabilities={},
        last_seen=None,
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.refresh = Mock()
    db.rollback = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=0)

    registry_cache = SimpleNamespace(
        invalidate_gateways=AsyncMock(),
        invalidate_tools=AsyncMock(),
        invalidate_resources=AsyncMock(),
        invalidate_prompts=AsyncMock(),
    )
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", SimpleNamespace(invalidate_tags=AsyncMock()))
    monkeypatch.setattr("mcpgateway.services.gateway_service.register_gateway_capabilities_for_notifications", Mock())

    connection_material = SimpleNamespace(
        url="http://example.com",
        auth_query_params_decrypted=None,
        client_cert=None,
        client_key=None,
    )
    service._prepare_gateway_connection_material = AsyncMock(return_value=connection_material)
    service._initialize_gateway_with_timeout = AsyncMock(return_value=({"tools": {"listChanged": True}}, [], [], [], []))
    service._sync_gateway_catalog = Mock(return_value=SimpleNamespace())
    service._reconcile_gateway_catalog = Mock()

    await service._process_pending_gateway(db, gateway)

    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()
    registry_cache.invalidate_gateways.assert_not_awaited()
    registry_cache.invalidate_tools.assert_not_awaited()
    registry_cache.invalidate_resources.assert_not_awaited()
    registry_cache.invalidate_prompts.assert_not_awaited()
    tool_lookup_cache.invalidate_gateway.assert_not_awaited()
    assert "http://example.com" not in service._active_gateways


@pytest.mark.asyncio
async def test_process_pending_gateway_skips_foreign_claim():
    service = GatewayService()
    gateway = SimpleNamespace(lifecycle_claimed_by="other-instance")
    db = MagicMock()
    service._prepare_gateway_connection_material = AsyncMock()

    await service._process_pending_gateway(db, gateway)

    service._prepare_gateway_connection_material.assert_not_called()


@pytest.mark.asyncio
async def test_process_pending_gateway_failure_skips_retry_when_deleted():
    service = GatewayService()
    gateway = SimpleNamespace(
        id="gw-1",
        url="http://example.com",
        auth_type=None,
        auth_query_params=None,
        auth_value=None,
        transport="SSE",
        oauth_config=None,
        ca_certificate=None,
        client_cert=None,
        client_key=None,
        tools=[],
        resources=[],
        prompts=[],
        status="pending",
        status_message=None,
        registration_attempts=0,
        next_retry_at=None,
        last_error=None,
        reachable=True,
        capabilities={},
        last_seen=None,
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.refresh = Mock()
    db.rollback = Mock()
    db.execute.return_value = SimpleNamespace(rowcount=0)

    connection_material = SimpleNamespace(
        url="http://example.com",
        auth_query_params_decrypted=None,
        client_cert=None,
        client_key=None,
    )
    service._prepare_gateway_connection_material = AsyncMock(return_value=connection_material)
    service._initialize_gateway_with_timeout = AsyncMock(side_effect=RuntimeError("boom"))

    await service._process_pending_gateway(db, gateway)

    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()
    assert gateway.registration_attempts == 0


def test_finalize_pending_gateway_success_requires_matching_pending_claim():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)

    claimed = service._finalize_pending_gateway_success(db, gateway, {"tools": {"listChanged": True}})

    assert claimed is True
    stmt = db.execute.call_args.args[0]
    compiled_params = stmt.compile().params
    assert compiled_params["status"] == "active"
    assert compiled_params["lifecycle_claimed_by"] is None


def test_finalize_pending_gateway_failure_requires_matching_pending_claim():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1")
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(rowcount=0)

    claimed = service._finalize_pending_gateway_failure(db, gateway, "boom", 4)

    assert claimed is False


def test_clear_lifecycle_claim_clears_all_claim_fields():
    service = GatewayService()
    gateway = SimpleNamespace(
        lifecycle_claimed_by="worker-1",
        lifecycle_claimed_at="claimed-at",
        lifecycle_claim_expires_at="expires-at",
    )

    service._clear_lifecycle_claim(gateway)

    assert gateway.lifecycle_claimed_by is None
    assert gateway.lifecycle_claimed_at is None
    assert gateway.lifecycle_claim_expires_at is None


@pytest.mark.asyncio
async def test_process_deleting_gateway_hard_deletes_and_finalizes():
    service = GatewayService()
    gateway = SimpleNamespace(
        id="gw-1",
        name="gw-name",
        url="http://example.com",
        team_id="team-1",
        tools=[],
        resources=[],
        prompts=[],
        lifecycle_claimed_by=service._instance_id,
    )
    db = MagicMock()
    db.commit = Mock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: service._instance_id)
    service._hard_delete_gateway = Mock()
    service._finalize_gateway_deletion = AsyncMock()

    await service._process_deleting_gateway(db, gateway)

    service._hard_delete_gateway.assert_called_once_with(db, gateway)
    db.commit.assert_called_once()
    service._finalize_gateway_deletion.assert_awaited_once_with(
        gateway_id="gw-1",
        gateway_info={"id": "gw-1", "name": "gw-name", "url": "http://example.com"},
        gateway_name="gw-name",
        gateway_team_id="team-1",
        gateway_url="http://example.com",
        user_email=None,
    )


@pytest.mark.asyncio
async def test_process_deleting_gateway_skips_foreign_claim():
    service = GatewayService()
    gateway = SimpleNamespace(lifecycle_claimed_by="other-instance")
    db = MagicMock()
    service._hard_delete_gateway = Mock()

    await service._process_deleting_gateway(db, gateway)

    service._hard_delete_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_process_deleting_gateway_rolls_back_when_claim_lost():
    service = GatewayService()
    gateway = SimpleNamespace(id="gw-1", name="gw-name", url="http://example.com", team_id="team-1", lifecycle_claimed_by=service._instance_id)
    db = MagicMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: "other-instance")
    service._hard_delete_gateway = Mock()

    await service._process_deleting_gateway(db, gateway)

    db.rollback.assert_called_once()
    service._hard_delete_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_run_health_checks_runs_lifecycle_pass_when_enabled(monkeypatch):
    service = GatewayService()
    service._redis_client = None
    service._health_check_interval = 0
    service._run_gateway_maintenance_cycle = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(settings, "cache_type", "none")

    with pytest.raises(asyncio.CancelledError):
        await service._run_health_checks("admin@example.com")

    service._run_gateway_maintenance_cycle.assert_awaited_once_with("admin@example.com")


@pytest.mark.asyncio
async def test_run_health_checks_redis_leader_runs_lifecycle_pass(monkeypatch):
    service = GatewayService()
    service._redis_client = SimpleNamespace(get=AsyncMock(side_effect=["instance-1"]))
    service._leader_key = "leader"
    service._instance_id = "instance-1"
    service._health_check_interval = 0
    service._run_gateway_maintenance_cycle = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(settings, "cache_type", "redis")

    with pytest.raises(asyncio.CancelledError):
        await service._run_health_checks("admin@example.com")

    service._run_gateway_maintenance_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_health_checks_filelock_runs_lifecycle_pass(monkeypatch):
    service = GatewayService()
    service._redis_client = None
    service._health_check_interval = 0
    service._run_gateway_maintenance_cycle = AsyncMock(side_effect=asyncio.CancelledError())
    service._file_lock = SimpleNamespace(acquire=Mock(return_value=None), is_locked=False)
    monkeypatch.setattr(settings, "cache_type", "file")

    with pytest.raises(asyncio.CancelledError):
        await service._run_health_checks("admin@example.com")

    service._run_gateway_maintenance_cycle.assert_awaited_once_with("admin@example.com")


@pytest.mark.asyncio
async def test_run_health_checks_skips_lifecycle_pass_when_disabled(monkeypatch):
    service = GatewayService()
    service._redis_client = None
    service._health_check_interval = 0
    service._run_gateway_maintenance_cycle = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(settings, "cache_type", "none")
    monkeypatch.setattr("mcpgateway.services.gateway_service.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await service._run_health_checks("admin@example.com")

    service._run_gateway_maintenance_cycle.assert_awaited_once_with("admin@example.com")


@pytest.mark.asyncio
async def test_run_gateway_lifecycle_loop_uses_independent_lifecycle_interval(monkeypatch):
    service = GatewayService()
    service._run_gateway_lifecycle_pass = AsyncMock()
    monkeypatch.setattr(settings, "gateway_async_lifecycle_poll_interval", 5.0)

    sleep_calls: list[float] = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)
        raise asyncio.CancelledError()

    monkeypatch.setattr("mcpgateway.services.gateway_service.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await service._run_gateway_lifecycle_loop()

    assert service._run_gateway_lifecycle_pass.await_count == 1
    assert sleep_calls == [5.0]


@pytest.mark.asyncio
async def test_authheaders_auth_value_stored_as_dict(monkeypatch):
    """Verify that registering a gateway with authheaders stores auth_value as a plain dict.

    auth_value DB column is Mapped[Optional[Dict[str, str]]] (JSON). Storing a string
    in that column causes the driver to write JSON null, which breaks health checks
    and the auto-refresh loop. The creation path must store the plain dict, consistent
    with the update path and the column type annotation.
    """
    # Verify the type contract: encode_auth() returns str, NOT a dict.
    # This is why storing its result in a Dict-typed JSON column produces null.
    encoded = encode_auth({"X-Key": "value"})
    assert isinstance(encoded, str), "encode_auth must return str — storing it in a dict JSON column yields null"

    # Build a minimal gateway with authheaders
    # Standard
    from types import SimpleNamespace as NS

    gateway = NS(
        name="test-gw",
        url="http://localhost:8000/mcp",
        description=None,
        transport="sse",
        tags=[],
        passthrough_headers=None,
        auth_type="authheaders",
        auth_value=None,
        auth_headers=[
            {"key": "X-Custom-Auth-Header", "value": "my-token"},
            {"key": "X-Custom-User-ID", "value": "user-123"},
        ],
        auth_query_param_key=None,
        auth_query_param_value=None,
        auth_query_params=None,
        oauth_config=None,
        one_time_auth=False,
        ca_certificate=None,
        ca_certificate_sig=None,
        signing_algorithm=None,
        visibility="public",
        enabled=True,
        team_id=None,
        owner_email=None,
        gateway_mode="cache",
    )

    # First-Party
    from mcpgateway.schemas import ToolCreate

    fake_tool = ToolCreate(name="echo", integration_type="REST", request_type="POST", url="http://localhost:8000/mcp")

    service = GatewayService()
    service._check_gateway_uniqueness = MagicMock(return_value=None)
    service._initialize_gateway = AsyncMock(return_value=({"tools": {}}, [fake_tool], [], [], []))
    service._notify_gateway_added = AsyncMock()

    monkeypatch.setattr("mcpgateway.services.gateway_service.get_for_update", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "mcpgateway.services.gateway_service.GatewayRead.model_validate",
        lambda x: MagicMock(),
    )

    db = MagicMock()
    db.flush = Mock()
    db.refresh = Mock()

    # Snapshot at db.add() time — tools flow through the gateway relationship (gateway.tools=tools),
    # not separate db.add() calls.
    # First-Party
    from mcpgateway.db import Gateway as DbGateway

    captured_gw: dict = {}
    captured_tool_auth_values: list = []

    def _capture_add(obj):
        if isinstance(obj, DbGateway):
            captured_gw["auth_value"] = obj.auth_value  # snapshot before any mutation
            for t in obj.tools or []:
                captured_tool_auth_values.append(t.auth_value)

    db.add = Mock(side_effect=_capture_add)

    await service.register_gateway(db, gateway)

    # --- DbGateway assertion ---
    # auth_value must be a plain dict — NOT a string.
    # A string stored in a Mapped[Optional[Dict[str, str]]] JSON column is written as JSON null.
    assert "auth_value" in captured_gw, "db.add was never called with a DbGateway object"
    assert isinstance(captured_gw["auth_value"], dict), f"DbGateway.auth_value must be dict for authheaders auth type, got {type(captured_gw['auth_value'])}: {captured_gw['auth_value']!r}"
    assert captured_gw["auth_value"] == {"X-Custom-Auth-Header": "my-token", "X-Custom-User-ID": "user-123"}

    # --- DbTool assertion ---
    # DbTool.auth_value is Mapped[Optional[str]] (Text), so it must be an encoded string,
    # not a raw dict. tool_service.py calls decode_auth() on it at read-time.
    assert len(captured_tool_auth_values) == 1, "expected exactly one DbTool to be added"
    assert isinstance(captured_tool_auth_values[0], str), f"DbTool.auth_value must be an encoded string for Text column, got {type(captured_tool_auth_values[0])}: {captured_tool_auth_values[0]!r}"
    # Decoding must recover the original headers dict
    assert decode_auth(captured_tool_auth_values[0]) == {"X-Custom-Auth-Header": "my-token", "X-Custom-User-ID": "user-123"}


@pytest.mark.asyncio
async def test_finalize_gateway_deletion_runs_cache_event_and_audit_finalizers(monkeypatch):
    service = GatewayService()
    service._active_gateways = {"http://example.com"}
    service._notify_gateway_deleted = AsyncMock()

    registry_cache = SimpleNamespace(invalidate_gateways=AsyncMock())
    tool_lookup_cache = SimpleNamespace(invalidate_gateway=AsyncMock())
    stats_cache = SimpleNamespace(invalidate_tags=AsyncMock())
    audit_log = Mock()
    structured_log = Mock()
    evict = AsyncMock(return_value=0)
    invalidate_passthrough = Mock()

    monkeypatch.setattr("mcpgateway.services.gateway_service._evict_upstream_sessions_for_gateway", evict)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_registry_cache", lambda: registry_cache)
    monkeypatch.setattr("mcpgateway.services.gateway_service._get_tool_lookup_cache", lambda: tool_lookup_cache)
    monkeypatch.setattr("mcpgateway.cache.admin_stats_cache.admin_stats_cache", stats_cache)
    monkeypatch.setattr("mcpgateway.utils.passthrough_headers.invalidate_passthrough_header_caches", invalidate_passthrough)
    monkeypatch.setattr("mcpgateway.services.gateway_service.audit_trail.log_action", audit_log)
    monkeypatch.setattr("mcpgateway.services.gateway_service.structured_logger.log", structured_log)

    db = MagicMock()
    gateway_info = {"id": "gw-1", "name": "gw-name", "url": "http://example.com"}

    await service._finalize_gateway_deletion(
        gateway_id="gw-1",
        gateway_info=gateway_info,
        gateway_name="gw-name",
        gateway_team_id="team-1",
        gateway_url="http://example.com",
        user_email="owner@example.com",
    )

    evict.assert_awaited_once_with("gw-1")
    registry_cache.invalidate_gateways.assert_awaited_once()
    tool_lookup_cache.invalidate_gateway.assert_awaited_once_with("gw-1")
    stats_cache.invalidate_tags.assert_awaited_once()
    invalidate_passthrough.assert_called_once_with()
    service._notify_gateway_deleted.assert_awaited_once_with(gateway_info)
    audit_log.assert_called_once()
    structured_log.assert_called_once()
    assert "http://example.com" not in service._active_gateways


def test_update_or_create_tools_authheaders_no_spurious_update():
    """Verify _update_or_create_tools does NOT trigger a spurious update when the
    gateway's auth_value dict matches the existing tool's encoded auth_value.

    encode_auth() uses os.urandom(12) for the AES-GCM nonce, so comparing
    ciphertext would always differ even when the plaintext is identical. The
    comparison must use decoded/plaintext values to avoid write amplification
    on every health-check refresh cycle.
    """
    # Standard
    from types import SimpleNamespace as NS

    service = GatewayService()

    auth_dict = {"X-My-Header": "secret-val"}
    encoded = encode_auth(auth_dict)
    original_encoded = encoded  # save for byte-for-byte comparison

    # Existing tool already has the correctly encoded auth_value stored
    existing = MagicMock()
    existing.original_name = "my-tool"
    existing.url = "http://gw.example.com/mcp"
    existing.description = "desc"
    existing.original_description = "desc"
    existing.integration_type = "MCP"
    existing.request_type = "POST"
    existing.headers = {}
    existing.input_schema = {}
    existing.output_schema = None
    existing.jsonpath_filter = None
    existing.auth_type = "authheaders"
    existing.auth_value = encoded  # Text column — already encoded
    existing.visibility = "public"
    existing.title = None

    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [existing]

    tool = NS(
        name="my-tool",
        description="desc",
        input_schema={},
        output_schema=None,
        request_type="POST",
        headers={},
        annotations=None,
        jsonpath_filter=None,
    )

    gateway = MagicMock()
    gateway.id = "gw-1"
    gateway.url = "http://gw.example.com/mcp"
    gateway.auth_type = "authheaders"
    gateway.auth_value = auth_dict  # JSON column — plain dict
    gateway.visibility = "public"

    result = service._update_or_create_tools(db, [tool], gateway, "update")

    # No new tools returned
    assert result == []
    # auth_value must be the EXACT same string — no spurious re-encryption
    assert existing.auth_value is original_encoded, f"auth_value was spuriously rewritten: {existing.auth_value!r} != {original_encoded!r}"
    assert decode_auth(existing.auth_value) == auth_dict
