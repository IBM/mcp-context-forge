# -*- coding: utf-8 -*-
"""Unit tests for the bounded process-local asynchronous job service."""

# Standard
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.services import async_job_service as job_module
from mcpgateway.services.async_job_service import (
    AsyncJobNotFoundError,
    AsyncJobPayloadTooLargeError,
    AsyncJobQueueFullError,
    AsyncJobService,
    AsyncJobServiceUnavailableError,
    AsyncJobStateConflictError,
)
from mcpgateway.services.tool_service import ToolNotFoundError


class _Result:
    """Minimal ToolResult-compatible test object."""

    def __init__(self, value: str = "ok") -> None:
        self.value = value

    def model_dump(self, *, by_alias: bool = False) -> dict:
        """Return deterministic serialized output."""
        assert by_alias is True
        return {"content": [{"type": "text", "text": self.value}], "isError": False}


def _service(**overrides) -> AsyncJobService:
    """Build a fast service with test-friendly lifecycle limits."""
    values = {
        "queue_capacity": 4,
        "worker_count": 1,
        "default_timeout_seconds": 0.5,
        "max_timeout_seconds": 2.0,
        "retention_seconds": 60.0,
        "cleanup_interval_seconds": 60.0,
        "max_retained_jobs": 10,
        "max_payload_bytes": 1_048_576,
        "max_result_bytes": 4_194_304,
        "max_retained_result_bytes": 16_777_216,
        "shutdown_timeout_seconds": 0.5,
    }
    values.update(overrides)
    return AsyncJobService(**values)


@pytest.fixture(autouse=True)
def _grant_worker_rbac(monkeypatch):
    """Keep unit tests focused while the worker's fresh RBAC check is mocked."""
    monkeypatch.setattr(job_module.PermissionService, "check_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(job_module, "get_plugin_manager", AsyncMock(return_value=None))


def _tool_service(*, integration_type: str = "REST", invoke_side_effect=None) -> MagicMock:
    """Return a ToolService-shaped mock used by both authorization checks."""
    service = MagicMock()
    service.get_tool = AsyncMock(
        return_value=SimpleNamespace(
            name="demo-tool",
            integration_type=integration_type,
            visibility="public",
            team_id=None,
            owner_email=None,
        )
    )
    service.invoke_tool = AsyncMock(return_value=_Result())
    if invoke_side_effect is not None:
        service.invoke_tool.side_effect = invoke_side_effect
    return service


@contextmanager
def _fresh_session():
    """Yield a request-independent fake worker session."""
    yield MagicMock(name="worker_db")


async def _enqueue(service: AsyncJobService, *, owner: str = "owner@example.com", timeout: float | None = None, **credential):
    """Queue a standard test invocation."""
    credential.setdefault("policy_client_host", "127.0.0.1")
    credential.setdefault("policy_user_agent", "pytest")
    return await service.enqueue_tool_invocation(
        MagicMock(name="request_db"),
        owner_email=owner,
        access_user_email=owner,
        access_is_admin=False,
        token_teams=["team-1"],
        tool_id="tool-1",
        arguments={"value": 1},
        request_headers={"authorization": "Bearer private"},
        metadata={"x-tenant": "alpha"},
        timeout_seconds=timeout,
        **credential,
    )


async def _wait_for_status(service: AsyncJobService, job_id: str, expected: str, *, owner: str = "owner@example.com"):
    """Poll an in-process job without introducing long sleeps."""
    for _attempt in range(200):
        snapshot = await service.get_job(job_id, owner, access_user_email=owner, token_teams=["team-1"])
        if snapshot.status == expected:
            return snapshot
        await __import__("asyncio").sleep(0.002)
    raise AssertionError(f"Job {job_id} did not reach {expected}")


@pytest.mark.asyncio
async def test_success_reauthorizes_executes_and_hides_execution_credentials(monkeypatch):
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service(integration_type="gRPC")
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        finished = await _wait_for_status(service, accepted.id, "succeeded")

        assert finished.result == {"content": [{"type": "text", "text": "ok"}], "isError": False}
        assert finished.duration_ms is not None
        assert not hasattr(finished, "request_headers")
        assert tool_service.get_tool.await_count == 2
        request_check, worker_check = tool_service.get_tool.await_args_list
        assert request_check.args[0] is not worker_check.args[0]
        for check in (request_check, worker_check):
            assert check.kwargs["requesting_user_email"] == "owner@example.com"
            assert check.kwargs["requesting_user_is_admin"] is False
            assert check.kwargs["token_teams"] == ["team-1"]
        call = tool_service.invoke_tool.await_args
        assert call.kwargs["app_user_email"] == "owner@example.com"
        assert call.kwargs["user_email"] == "owner@example.com"
        assert call.kwargs["token_teams"] == ["team-1"]
        assert call.kwargs["timeout_override"] == 0.5
        assert call.kwargs["meta_data"] == {
            "async_job_id": accepted.id,
            "grpc_metadata": {"x-tenant": "alpha"},
            "capture_grpc_call_metadata": True,
        }

        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job(accepted.id, "other@example.com", access_user_email="other@example.com", token_teams=["team-1"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_failure_is_terminal_and_redacts_credentials(monkeypatch):
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service(invoke_side_effect=RuntimeError("upstream failed authorization=Bearer secret-value"))
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.result is None
        assert failed.error == {"type": "RuntimeError", "message": "upstream failed authorization=***"}
        assert "secret-value" not in str(failed.error)
        record = service._jobs[accepted.id]  # pylint: disable=protected-access
        assert record.arguments == {}
        assert record.request_headers == {}
        assert record.metadata == {}
        with pytest.raises(AsyncJobStateConflictError):
            await service.cancel_job(accepted.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_timeout_cancels_invocation_and_records_failure(monkeypatch):
    # Standard
    import asyncio

    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    cancelled = asyncio.Event()

    async def block_until_cancelled(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service = _service(default_timeout_seconds=0.02)
    await service.start(_tool_service(invoke_side_effect=block_until_cancelled))
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {"type": "TimeoutError", "message": "Tool invocation exceeded 0.02 seconds"}
        assert cancelled.is_set()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_queue_capacity_and_queued_cancellation_release_capacity(monkeypatch):
    # Standard
    import asyncio

    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    gate = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        await gate.wait()
        return _Result()

    service = _service(queue_capacity=1)
    await service.start(_tool_service(invoke_side_effect=blocked))
    try:
        running = await _enqueue(service)
        await _wait_for_status(service, running.id, "running")
        queued = await _enqueue(service)
        with pytest.raises(AsyncJobQueueFullError):
            await _enqueue(service)

        cancelled = await service.cancel_job(queued.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        assert cancelled.status == "cancelled"
        replacement = await _enqueue(service)
        assert replacement.status == "queued"

        await service.cancel_job(running.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        await service.cancel_job(replacement.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
    finally:
        gate.set()
        await service.shutdown()


@pytest.mark.asyncio
async def test_list_filters_by_owner_and_status(monkeypatch):
    # Standard
    import asyncio

    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    gate = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        await gate.wait()
        return _Result()

    service = _service(worker_count=1)
    await service.start(_tool_service(invoke_side_effect=blocked))
    try:
        owner_running = await _enqueue(service)
        await _wait_for_status(service, owner_running.id, "running")
        owner_queued = await _enqueue(service)
        other_queued = await _enqueue(service, owner="other@example.com")

        queued = await service.list_jobs("owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"], status="queued")
        assert [item.id for item in queued] == [owner_queued.id]
        assert not hasattr(queued[0], "result")
        assert all(item.id != other_queued.id for item in await service.list_jobs("owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"]))
        assert await service.list_jobs("OWNER@example.com", access_user_email="OWNER@example.com", token_teams=["team-1"]) == []
    finally:
        gate.set()
        await service.shutdown()


@pytest.mark.asyncio
async def test_job_reads_and_cancellation_reapply_current_target_visibility_scope():
    """A same-owner token cannot read retained data outside its current Layer-1 scope."""
    service = _service()
    await service.start(_tool_service())

    def record(job_id: str, visibility: str, *, team_id: str | None = None, target_owner: str | None = None):
        return job_module._JobRecord(  # pylint: disable=protected-access
            id=job_id,
            owner_email="owner@example.com",
            access_user_email="owner@example.com",
            access_is_admin=False,
            token_teams=["team-1"],
            tool_id=f"tool-{job_id}",
            tool_name=f"tool-{job_id}",
            target_visibility=visibility,
            target_team_id=team_id,
            target_owner_email=target_owner,
            arguments={},
            request_headers={},
            metadata={},
            timeout_seconds=1.0,
        )

    public = record("public", "public")
    team = record("team", "team", team_id="team-1")
    private = record("private", "private", target_owner="owner@example.com")
    other_private = record("other-private", "private", target_owner="other@example.com")
    service._jobs.update({item.id: item for item in (public, team, private, other_private)})  # pylint: disable=protected-access
    try:
        public_only = await service.list_jobs("owner@example.com", access_user_email="owner@example.com", token_teams=[])
        assert {item.id for item in public_only} == {"public"}

        team_scoped = await service.list_jobs("owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        assert {item.id for item in team_scoped} == {"public", "team", "private"}

        admin_bypass = await service.list_jobs("owner@example.com", access_user_email="owner@example.com", token_teams=None)
        assert {item.id for item in admin_bypass} == {"public", "team", "private"}

        # A lower-privilege token for the same principal cannot recover a
        # result queued under a team it no longer carries, or cancel that job.
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job("team", "owner@example.com", access_user_email="owner@example.com", token_teams=["team-2"])
        with pytest.raises(AsyncJobNotFoundError):
            await service.cancel_job("team", "owner@example.com", access_user_email="owner@example.com", token_teams=["team-2"])
        assert team.status == "queued"

        # Owner visibility is retained for non-empty scopes, while an explicit
        # public-only scope suppresses it exactly as BaseService does.
        assert (await service.get_job("private", "owner@example.com", access_user_email="owner@example.com", token_teams=["team-2"])).id == "private"
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job("private", "owner@example.com", access_user_email="owner@example.com", token_teams=[])
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job("other-private", "owner@example.com", access_user_email="owner@example.com", token_teams=None)

        cancelled = await service.cancel_job("team", "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        assert cancelled.status == "cancelled"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_retention_cleanup_removes_only_finished_jobs(monkeypatch):
    # Standard
    import asyncio

    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    service = _service(retention_seconds=0.01)
    await service.start(_tool_service())
    try:
        accepted = await _enqueue(service)
        await _wait_for_status(service, accepted.id, "succeeded")
        await asyncio.sleep(0.02)

        assert await service.cleanup() == 1
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job(accepted.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_cleanup_enforces_max_retained_terminal_jobs(monkeypatch):
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    service = _service(max_retained_jobs=1)
    await service.start(_tool_service())
    try:
        first = await _enqueue(service)
        await _wait_for_status(service, first.id, "succeeded")
        second = await _enqueue(service)
        await _wait_for_status(service, second.id, "succeeded")

        assert await service.cleanup() == 1
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job(first.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        assert (await service.get_job(second.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])).status == "succeeded"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_running_and_queued_jobs(monkeypatch):
    # Standard
    import asyncio

    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)

    async def blocked(*_args, **_kwargs):
        await asyncio.Event().wait()

    service = _service()
    await service.start(_tool_service(invoke_side_effect=blocked))
    running = await _enqueue(service)
    await _wait_for_status(service, running.id, "running")
    queued = await _enqueue(service)

    await service.shutdown()

    assert service.started is False
    with pytest.raises(AsyncJobServiceUnavailableError):
        await _enqueue(service)
    # Lifecycle is stopped, but retained records remain inspectable only after a
    # restart; no worker-local endpoint is available while shutdown is complete.
    assert service._jobs[running.id].status == "cancelled"  # pylint: disable=protected-access
    assert service._jobs[queued.id].status == "cancelled"  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_enqueue_before_start_is_rejected():
    service = _service()
    with pytest.raises(AsyncJobServiceUnavailableError):
        await _enqueue(service)


@pytest.mark.asyncio
async def test_payload_and_retained_result_are_byte_bounded(monkeypatch):
    """Large requests are rejected before authorization and large results are not retained."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    service = _service(max_payload_bytes=300, max_result_bytes=100)
    await service.start(tool_service)
    try:
        with pytest.raises(AsyncJobPayloadTooLargeError):
            await service.enqueue_tool_invocation(
                MagicMock(),
                owner_email="owner@example.com",
                access_user_email="owner@example.com",
                access_is_admin=False,
                token_teams=[],
                tool_id="tool-1",
                arguments={"value": "x" * 1000},
                request_headers={},
                metadata={},
                timeout_seconds=None,
            )
        tool_service.get_tool.assert_not_awaited()

        tool_service.invoke_tool.return_value = _Result("x" * 200)
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")
        assert failed.result is None
        assert failed.error == {
            "type": "AsyncJobResultTooLargeError",
            "message": "Async job result exceeds the 100-byte retention limit",
        }
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_aggregate_result_budget_evicts_oldest_terminal_job(monkeypatch):
    """Successful results never exceed the process-wide retained-byte budget."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    result_value = "x" * 80
    serialized_size = len(job_module.orjson.dumps(_Result(result_value).model_dump(by_alias=True)))
    tool_service = _tool_service()
    tool_service.invoke_tool.side_effect = [_Result(result_value), _Result(result_value)]
    service = _service(max_retained_result_bytes=serialized_size + 1)
    await service.start(tool_service)
    try:
        first = await _enqueue(service)
        await _wait_for_status(service, first.id, "succeeded")
        second = await _enqueue(service)
        await _wait_for_status(service, second.id, "succeeded")

        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job(first.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])
        assert (await service.get_job(second.id, "owner@example.com", access_user_email="owner@example.com", token_teams=["team-1"])).result is not None
        assert service._retained_result_bytes == serialized_size  # pylint: disable=protected-access
        assert service._retained_result_bytes <= service.max_retained_result_bytes  # pylint: disable=protected-access
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_result_larger_than_aggregate_budget_is_not_retained(monkeypatch):
    """A single result that cannot fit the aggregate cap becomes a bounded failure."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    tool_service.invoke_tool.return_value = _Result("x" * 200)
    service = _service(max_result_bytes=1000, max_retained_result_bytes=100)
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")
        assert failed.result is None
        assert failed.error == {
            "type": "AsyncJobResultTooLargeError",
            "message": "Async job result exceeds the 100-byte aggregate retention budget",
        }
        assert service._retained_result_bytes == 0  # pylint: disable=protected-access
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_session_job_rechecks_current_membership_and_rbac_before_execution(monkeypatch):
    """A queued session job must fail closed after membership/permission revocation."""
    worker_db = MagicMock(name="worker_db")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = SimpleNamespace(is_admin=False)
    membership_result = MagicMock()
    membership_result.scalars.return_value.__iter__.return_value = iter(())
    worker_db.execute.side_effect = [user_result, membership_result]

    @contextmanager
    def revoked_session():
        yield worker_db

    async def deny_without_team(_permission_service, **kwargs):
        assert kwargs["token_teams"] == []
        return False

    monkeypatch.setattr(job_module, "fresh_db_session", revoked_session)
    monkeypatch.setattr(job_module.PermissionService, "check_permission", deny_without_team)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await service.enqueue_tool_invocation(
            MagicMock(name="request_db"),
            owner_email="owner@example.com",
            access_user_email="owner@example.com",
            access_is_admin=False,
            token_teams=["team-1"],
            tool_id="tool-1",
            arguments={},
            request_headers={},
            metadata={},
            timeout_seconds=None,
            token_use="session",
        )
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Tool execution permission was revoked before the job started",
        }
        assert tool_service.get_tool.await_count == 2
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_job_rejects_token_expired_while_queued(monkeypatch):
    """A verified token expiry remains authoritative at worker execution."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(
            service,
            auth_method="jwt",
            token_jti="jti-expired",
            token_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Authentication token expired before the job started",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_job_rejects_token_revoked_while_queued(monkeypatch):
    """The worker checks the fresh blocklist rather than an enqueue snapshot."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    monkeypatch.setattr(job_module, "get_token_blocklist_service", lambda db: SimpleNamespace(is_token_revoked=lambda _jti: True))
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service, auth_method="jwt", token_jti="jti-revoked")
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Authentication token was revoked before the job started",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_job_rejects_enqueue_token_scope_without_execute(monkeypatch):
    """Layer-1 token scope is rechecked immediately before execution."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service, auth_method="api_token", token_scopes=["tools.read"])
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Token scope no longer permits tool execution",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_server_scoped_job_requires_association_and_invokes_in_server_context(monkeypatch):
    """A server-scoped token cannot escape its virtual-server tool catalog."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        request_db = MagicMock(name="request_db")
        request_db.execute.return_value.first.return_value = None
        with pytest.raises(ToolNotFoundError):
            await service.enqueue_tool_invocation(
                request_db,
                owner_email="owner@example.com",
                access_user_email="owner@example.com",
                access_is_admin=False,
                token_teams=["team-1"],
                tool_id="tool-1",
                arguments={},
                request_headers={},
                metadata={},
                timeout_seconds=None,
                token_server_id="server-1",
            )

        request_db.execute.return_value.first.return_value = ("tool-1",)
        accepted = await service.enqueue_tool_invocation(
            request_db,
            owner_email="owner@example.com",
            access_user_email="owner@example.com",
            access_is_admin=False,
            token_teams=["team-1"],
            tool_id="tool-1",
            arguments={},
            request_headers={},
            metadata={},
            timeout_seconds=None,
            token_server_id="server-1",
        )
        await _wait_for_status(service, accepted.id, "succeeded")
        assert tool_service.invoke_tool.await_args.kwargs["server_id"] == "server-1"
        assert (
            await service.get_job(
                accepted.id,
                "owner@example.com",
                access_user_email="owner@example.com",
                token_teams=["team-1"],
                token_server_id="server-1",
            )
        ).status == "succeeded"
        assert (
            await service.list_jobs(
                "owner@example.com",
                access_user_email="owner@example.com",
                token_teams=["team-1"],
                token_server_id="server-2",
            )
            == []
        )
        with pytest.raises(AsyncJobNotFoundError):
            await service.get_job(
                accepted.id,
                "owner@example.com",
                access_user_email="owner@example.com",
                token_teams=["team-1"],
                token_server_id="server-2",
            )
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_current_catalog_server_scope_cannot_replace_enqueue_scope(monkeypatch):
    """Changing a queued API token to another server invalidates the job."""
    initial_catalog = SimpleNamespace(id="catalog-1")
    request_db = MagicMock(name="request_db")
    association_result = MagicMock()
    association_result.first.return_value = ("tool-1",)
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none.return_value = initial_catalog
    request_db.execute.side_effect = [association_result, catalog_result]

    current_catalog = SimpleNamespace(
        id="catalog-1",
        jti="jti-1",
        user_email="owner@example.com",
        is_active=True,
        expires_at=None,
        resource_scopes=["tools.execute"],
        server_id="server-2",
        team_id="team-1",
    )
    worker_db = MagicMock(name="worker_db")
    worker_catalog_result = MagicMock()
    worker_catalog_result.scalar_one_or_none.return_value = current_catalog
    worker_db.execute.return_value = worker_catalog_result

    @contextmanager
    def worker_session():
        yield worker_db

    monkeypatch.setattr(job_module, "fresh_db_session", worker_session)
    monkeypatch.setattr(job_module, "get_token_blocklist_service", lambda db: SimpleNamespace(is_token_revoked=lambda _jti: False))
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await service.enqueue_tool_invocation(
            request_db,
            owner_email="owner@example.com",
            access_user_email="owner@example.com",
            access_is_admin=False,
            token_teams=["team-1"],
            tool_id="tool-1",
            arguments={},
            request_headers={},
            metadata={},
            timeout_seconds=None,
            auth_method="api_token",
            token_jti="jti-1",
            token_scopes=["tools.execute"],
            token_server_id="server-1",
        )
        failed = await _wait_for_status(service, accepted.id, "failed")
        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "API token server scope changed before the job started",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_non_session_job_rechecks_account_and_team_membership(monkeypatch):
    """A signed non-session token stops working immediately after team removal."""
    worker_db = MagicMock(name="worker_db")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = SimpleNamespace(is_admin=False)
    membership_result = MagicMock()
    membership_result.scalars.return_value.all.return_value = []
    worker_db.execute.side_effect = [user_result, membership_result]

    @contextmanager
    def worker_session():
        yield worker_db

    monkeypatch.setattr(job_module, "fresh_db_session", worker_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service, auth_method="jwt")
        failed = await _wait_for_status(service, accepted.id, "failed")
        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Authenticated user is no longer a member of the token team",
        }
        tool_service.get_tool.assert_awaited_once()
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_worker_rbac_is_bound_to_target_tool_team(monkeypatch):
    """A role on an unrelated team cannot authorize execution of a team tool."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    tool_service = _tool_service()
    tool_service.get_tool.return_value = SimpleNamespace(name="demo-tool", integration_type="REST", visibility="team", team_id="team-1")

    async def assert_target_scope(_permission_service, **kwargs):
        assert kwargs["resource_type"] == "tool"
        assert kwargs["resource_id"] == "tool-1"
        assert kwargs["team_id"] == "team-1"
        assert kwargs["check_any_team"] is False
        return True

    monkeypatch.setattr(job_module.PermissionService, "check_permission", assert_target_scope)
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        assert (await _wait_for_status(service, accepted.id, "succeeded")).result is not None
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_worker_rejects_target_visibility_scope_change(monkeypatch):
    """A queued job cannot execute after the target's retained access boundary changes."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    team_tool = SimpleNamespace(
        name="demo-tool",
        integration_type="REST",
        visibility="team",
        team_id="team-1",
        owner_email="owner@example.com",
    )
    public_tool = SimpleNamespace(
        name="demo-tool",
        integration_type="REST",
        visibility="public",
        team_id=None,
        owner_email="owner@example.com",
    )
    tool_service = _tool_service()
    tool_service.get_tool.side_effect = [team_tool, public_tool]
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")
        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Tool visibility scope changed before the job started",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_enqueue_rejects_team_tool_permission_from_unrelated_team(monkeypatch):
    """Target-team RBAC is checked before a job consumes queue capacity."""
    tool_service = _tool_service()
    tool_service.get_tool.return_value = SimpleNamespace(name="demo-tool", integration_type="REST", visibility="team", team_id="team-1")

    async def deny_target_team(_permission_service, **kwargs):
        assert kwargs["team_id"] == "team-1"
        assert kwargs["check_any_team"] is False
        return False

    monkeypatch.setattr(job_module.PermissionService, "check_permission", deny_target_team)
    service = _service()
    await service.start(tool_service)
    try:
        with pytest.raises(job_module.AsyncJobAuthorizationError):
            await _enqueue(service)
        assert not service._pending  # pylint: disable=protected-access
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_session_admin_promotion_never_widens_enqueue_scope(monkeypatch):
    """A user promoted while queued remains capped to the original team scope."""
    worker_db = MagicMock(name="worker_db")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = SimpleNamespace(is_admin=True)
    membership_result = MagicMock()
    membership_result.scalars.return_value.__iter__.return_value = iter(("team-1", "team-2"))
    worker_db.execute.side_effect = [user_result, membership_result]

    @contextmanager
    def worker_session():
        yield worker_db

    monkeypatch.setattr(job_module, "fresh_db_session", worker_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service, token_use="session")
        await _wait_for_status(service, accepted.id, "succeeded")
        worker_check = tool_service.get_tool.await_args_list[1]
        assert worker_check.kwargs["requesting_user_is_admin"] is False
        assert worker_check.kwargs["token_teams"] == ["team-1"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_session_public_only_scope_remains_empty_at_execution(monkeypatch):
    """An enqueue-time empty session scope cannot expand to current DB teams."""
    worker_db = MagicMock(name="worker_db")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = SimpleNamespace(is_admin=False)
    membership_result = MagicMock()
    membership_result.scalars.return_value.__iter__.return_value = iter(("team-1", "team-2"))
    worker_db.execute.side_effect = [user_result, membership_result]

    @contextmanager
    def worker_session():
        yield worker_db

    monkeypatch.setattr(job_module, "fresh_db_session", worker_session)
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await service.enqueue_tool_invocation(
            MagicMock(name="request_db"),
            owner_email="owner@example.com",
            access_user_email="owner@example.com",
            access_is_admin=False,
            token_teams=[],
            tool_id="tool-1",
            arguments={},
            request_headers={},
            metadata={},
            timeout_seconds=None,
            token_use="session",
        )
        await _wait_for_status(service, accepted.id, "succeeded")
        worker_check = tool_service.get_tool.await_args_list[1]
        assert worker_check.kwargs["token_teams"] == []
        assert tool_service.invoke_tool.await_args.kwargs["token_teams"] == []
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_worker_replays_dynamic_permission_plugin_and_honors_late_deny(monkeypatch):
    """A policy plugin can revoke execution after enqueue but before dispatch."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    no_decision = SimpleNamespace(modified_payload=None, violation=None, metadata={})
    denied = SimpleNamespace(modified_payload=SimpleNamespace(granted=False), violation=None, metadata={})
    plugin_manager = MagicMock()
    plugin_manager.has_hooks_for.return_value = True
    plugin_manager.invoke_hook = AsyncMock(side_effect=[(no_decision, None), (denied, None)])
    monkeypatch.setattr(job_module, "get_plugin_manager", AsyncMock(return_value=plugin_manager))
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Authorization plugin denied the queued job",
        }
        assert plugin_manager.invoke_hook.await_count == 2
        worker_call = plugin_manager.invoke_hook.await_args_list[1]
        assert worker_call.kwargs["payload"].user_email == "owner@example.com"
        assert worker_call.kwargs["payload"].permission == "tools.execute"
        assert worker_call.kwargs["payload"].resource_type == "tool"
        assert worker_call.kwargs["payload"].client_host == "127.0.0.1"
        assert worker_call.kwargs["payload"].user_agent == "pytest"
        assert worker_call.kwargs["global_context"].request_id == accepted.id
        assert worker_call.kwargs["local_contexts"] is None
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_worker_fails_closed_when_permission_plugin_replay_errors(monkeypatch):
    """Missing request-local plugin state cannot make a delayed job fail open."""
    monkeypatch.setattr(job_module, "fresh_db_session", _fresh_session)
    no_decision = SimpleNamespace(modified_payload=None, violation=None, metadata={})
    plugin_manager = MagicMock()
    plugin_manager.has_hooks_for.return_value = True
    plugin_manager.invoke_hook = AsyncMock(side_effect=[(no_decision, None), RuntimeError("missing fresh policy context")])
    monkeypatch.setattr(job_module, "get_plugin_manager", AsyncMock(return_value=plugin_manager))
    tool_service = _tool_service()
    service = _service()
    await service.start(tool_service)
    try:
        accepted = await _enqueue(service)
        failed = await _wait_for_status(service, accepted.id, "failed")

        assert failed.error == {
            "type": "AsyncJobAuthorizationError",
            "message": "Authorization plugin could not validate the queued job",
        }
        tool_service.invoke_tool.assert_not_awaited()
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_permission_plugin_fails_closed_without_replayable_request_inputs(monkeypatch):
    """Policy hooks are not invoked with fabricated or missing client attributes."""
    plugin_manager = MagicMock()
    plugin_manager.has_hooks_for.return_value = True
    plugin_manager.invoke_hook = AsyncMock()
    monkeypatch.setattr(job_module, "get_plugin_manager", AsyncMock(return_value=plugin_manager))
    service = _service()
    await service.start(_tool_service())
    try:
        with pytest.raises(job_module.AsyncJobAuthorizationError, match="could not validate"):
            await _enqueue(service, policy_client_host=None, policy_user_agent=None)
        plugin_manager.invoke_hook.assert_not_awaited()
        assert not service._pending  # pylint: disable=protected-access
    finally:
        await service.shutdown()


def test_header_minimization_retains_only_target_consumable_headers(monkeypatch):
    """Ambient credentials and unrelated request headers are not persisted."""
    monkeypatch.setattr(job_module.global_config_cache, "get_passthrough_headers", lambda _db, _default: ["X-Tenant-Id"])
    retained = AsyncJobService._minimize_request_headers(  # pylint: disable=protected-access
        MagicMock(),
        SimpleNamespace(gateway_id=None),
        {
            "authorization": "Bearer private",
            "cookie": "jwt_token=private",
            "traceparent": "00-trace-parent",
            "x-noise": "drop-me",
            "x-tenant-id": "tenant-1",
        },
        supplemental_header_names=["x-noise", "x-tenant-id"],
    )

    assert retained == {"traceparent": "00-trace-parent", "x-tenant-id": "tenant-1"}


def test_header_minimization_keeps_subject_token_only_for_token_exchange(monkeypatch):
    """The raw bearer is retained only when the selected gateway consumes it."""
    monkeypatch.setattr(job_module.global_config_cache, "get_passthrough_headers", lambda _db, _default: [])
    db = MagicMock()
    db.get.return_value = SimpleNamespace(
        passthrough_headers=None,
        oauth_config={"grant_type": "token-exchange"},
        auth_type="oauth",
    )
    retained = AsyncJobService._minimize_request_headers(  # pylint: disable=protected-access
        db,
        SimpleNamespace(gateway_id="gateway-1"),
        {"authorization": "Bearer private", "x-noise": "drop-me"},
        supplemental_header_names=[],
    )

    assert retained == {"authorization": "Bearer private"}
