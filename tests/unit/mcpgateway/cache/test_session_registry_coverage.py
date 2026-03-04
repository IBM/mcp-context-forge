# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/cache/test_session_registry_coverage.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Additional tests to improve coverage for session_registry.py.
Targets specific uncovered lines and branches.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mcpgateway.cache.session_registry import SessionRegistry
from mcpgateway.config import settings


# ---------------------------------------------------------------------------
# Minimal SSE transport stub
# ---------------------------------------------------------------------------
class FakeSSETransport:
    """Stub implementing just the subset of the API used by SessionRegistry."""

    def __init__(self, session_id: str, connected: bool = True):
        self.session_id = session_id
        self._connected = connected
        self.sent: List[Any] = []
        self.disconnect_called = False

    async def disconnect(self) -> None:
        self._connected = False
        self.disconnect_called = True

    async def is_connected(self) -> bool:
        return self._connected

    async def send_message(self, msg) -> None:
        if not self._connected:
            raise ConnectionError("Transport disconnected")
        self.sent.append(json.loads(json.dumps(msg)))


class _FakeQuery:
    """Minimal SQLAlchemy-like query stub for session owner tests."""

    def __init__(self, db_session: "_FakeDbSession"):
        self._db_session = db_session

    def filter(self, *_args, **_kwargs):  # noqa: D401 - test helper
        return self

    def first(self):  # noqa: D401 - test helper
        if self._db_session.first_results:
            return self._db_session.first_results.pop(0)
        return None

    def update(self, values, synchronize_session=False):  # noqa: D401 - test helper, ARG002
        self._db_session.updated_values.append(values)
        if self._db_session.update_results:
            return self._db_session.update_results.pop(0)
        return 0


class _FakeDbSession:
    """Minimal DB session stub for exercising database owner branches."""

    def __init__(
        self,
        *,
        first_results: Optional[List[Any]] = None,
        update_results: Optional[List[int]] = None,
        commit_effects: Optional[List[Any]] = None,
    ):
        self.first_results = list(first_results or [])
        self.update_results = list(update_results or [])
        self.commit_effects = list(commit_effects or [])
        self.added: List[Any] = []
        self.updated_values: List[Dict[str, Any]] = []
        self.flush_called = False
        self.rollback_called = False
        self.closed = False
        self.commit_called = 0

    def query(self, _model):  # noqa: D401 - test helper
        return _FakeQuery(self)

    def add(self, obj):  # noqa: D401 - test helper
        self.added.append(obj)

    def flush(self):  # noqa: D401 - test helper
        self.flush_called = True

    def commit(self):  # noqa: D401 - test helper
        self.commit_called += 1
        if self.commit_effects:
            effect = self.commit_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect

    def rollback(self):  # noqa: D401 - test helper
        self.rollback_called = True

    def close(self):  # noqa: D401 - test helper
        self.closed = True


async def _run_sync_to_thread(func, *args, **kwargs):  # noqa: D401 - test helper
    return func(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixture: memory-backend registry
# ---------------------------------------------------------------------------
@pytest.fixture()
async def registry() -> SessionRegistry:
    reg = SessionRegistry(backend="memory")
    await reg.initialize()
    yield reg
    await reg.shutdown()


# ---------------------------------------------------------------------------
# _cancel_respond_task edge cases (lines 345, 356-357, 368-369, 375-376,
# 382-387, 396-399)
# ---------------------------------------------------------------------------
class TestCancelRespondTaskEdgeCases:
    """Cover additional branches in _cancel_respond_task."""

    @pytest.mark.asyncio
    async def test_cancel_task_cancelled_error_during_wait_for(self, registry):
        """Line 392-395: CancelledError raised by wait_for (not timeout)."""
        event = asyncio.Event()

        async def waiter():
            await event.wait()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("ce_test", task)

        # Make wait_for raise CancelledError directly
        async def fake_wait_for(coro, *, timeout=None):
            raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
            await registry._cancel_respond_task("ce_test")

        assert "ce_test" not in registry._respond_tasks
        # Cleanup
        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_unexpected_exception_during_wait_for(self, registry, caplog):
        """Lines 396-399: Unexpected exception during wait_for."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        event = asyncio.Event()

        async def waiter():
            await event.wait()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("ue_test", task)

        async def fake_wait_for(coro, *, timeout=None):
            raise RuntimeError("unexpected error")

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
            await registry._cancel_respond_task("ue_test")

        assert "ue_test" not in registry._respond_tasks
        assert "Error during respond task cancellation for ue_test" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_escalation_retry_succeeds(self, registry, caplog):
        """Lines 374-376: Retry cancellation succeeds after escalation."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")

        call_count = {"n": 0}

        async def wait_for_mock(coro, *, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError()
            # Second call succeeds (returns normally)
            return None

        event = asyncio.Event()

        async def waiter():
            try:
                await event.wait()
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("retry_ok", task)

        tr = FakeSSETransport("retry_ok")
        await registry.add_session("retry_ok", tr)

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", wait_for_mock):
            await registry._cancel_respond_task("retry_ok")

        assert "retry_ok" not in registry._respond_tasks
        assert "Respond task cancelled after escalation for retry_ok" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_escalation_cancelled_error_during_retry(self, registry, caplog):
        """Lines 382-384: CancelledError during retry after escalation."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")

        call_count = {"n": 0}

        async def wait_for_mock(coro, *, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError()
            raise asyncio.CancelledError()

        event = asyncio.Event()

        async def waiter():
            try:
                await event.wait()
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("retry_ce", task)

        tr = FakeSSETransport("retry_ce")
        await registry.add_session("retry_ce", tr)

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", wait_for_mock):
            await registry._cancel_respond_task("retry_ce")

        assert "retry_ce" not in registry._respond_tasks

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_escalation_unexpected_error_during_retry(self, registry, caplog):
        """Lines 385-387: Unexpected error during retry after escalation."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")

        call_count = {"n": 0}

        async def wait_for_mock(coro, *, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError()
            raise RuntimeError("retry boom")

        event = asyncio.Event()

        async def waiter():
            try:
                await event.wait()
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("retry_ue", task)

        tr = FakeSSETransport("retry_ue")
        await registry.add_session("retry_ue", tr)

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", wait_for_mock):
            await registry._cancel_respond_task("retry_ue")

        assert "retry_ue" not in registry._respond_tasks
        assert "Error during retry cancellation for retry_ue" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_escalation_disconnect_error(self, registry, caplog):
        """Lines 368-369: transport.disconnect() fails during escalation."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")

        call_count = {"n": 0}

        async def wait_for_mock(coro, *, timeout=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise asyncio.TimeoutError()
            return None

        event = asyncio.Event()

        async def waiter():
            try:
                await event.wait()
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        registry.register_respond_task("disc_err", task)

        tr = FakeSSETransport("disc_err")
        tr.disconnect = AsyncMock(side_effect=RuntimeError("disconnect boom"))
        registry._sessions["disc_err"] = tr

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", wait_for_mock):
            await registry._cancel_respond_task("disc_err")

        assert "Failed to force-disconnect transport for disc_err" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_cancel_task_escalation_task_done_after_timeout(self, registry, caplog):
        """Lines 388-390: Task completes during escalation (done after timeout)."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")

        completed = asyncio.Event()

        async def quick_task():
            completed.set()

        task = asyncio.create_task(quick_task())
        await asyncio.sleep(0.01)  # Let it complete

        registry.register_respond_task("done_esc", task)

        call_count = {"n": 0}

        async def wait_for_mock(coro, *, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise asyncio.TimeoutError()
            return None

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", wait_for_mock):
            await registry._cancel_respond_task("done_esc")

        assert "done_esc" not in registry._respond_tasks


# ---------------------------------------------------------------------------
# _reap_stuck_tasks edge cases (lines 448-449, 452-456, 458-465)
# ---------------------------------------------------------------------------
class TestReapStuckTasksEdgeCases:
    """Cover additional paths in _reap_stuck_tasks."""

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_cancel_succeeds(self):
        """Lines 448-449: stuck task cancellation succeeds during reap."""
        registry = SessionRegistry(backend="memory")

        # Create a task that will cancel cleanly
        event = asyncio.Event()

        async def cancelable():
            await event.wait()

        task = asyncio.create_task(cancelable())
        registry._stuck_tasks["can_cancel"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        async def fake_wait_for(coro, *, timeout=None):
            # Task cancellation succeeds
            return None

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
                with pytest.raises(asyncio.CancelledError):
                    await registry._reap_stuck_tasks()

        assert "can_cancel" not in registry._stuck_tasks

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_cancel_raises_cancelled_error(self):
        """Lines 452-454: CancelledError during stuck task reap retry."""
        registry = SessionRegistry(backend="memory")

        event = asyncio.Event()

        async def waiter():
            await event.wait()

        task = asyncio.create_task(waiter())
        registry._stuck_tasks["ce_stuck"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        async def fake_wait_for(coro, *, timeout=None):
            raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
                with pytest.raises(asyncio.CancelledError):
                    await registry._reap_stuck_tasks()

        assert "ce_stuck" not in registry._stuck_tasks

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_cancel_raises_unexpected(self, caplog):
        """Lines 455-456: Unexpected error during stuck task reap."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")

        event = asyncio.Event()

        async def waiter():
            await event.wait()

        task = asyncio.create_task(waiter())
        registry._stuck_tasks["ue_stuck"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        async def fake_wait_for(coro, *, timeout=None):
            raise RuntimeError("reap boom")

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
                with pytest.raises(asyncio.CancelledError):
                    await registry._reap_stuck_tasks()

        assert "Error during stuck task reap for ue_stuck" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_empty_stuck_tasks_continue(self):
        """Line 420: _stuck_tasks is empty, should continue."""
        registry = SessionRegistry(backend="memory")
        # No stuck tasks
        registry._stuck_tasks = {}

        call_count = {"n": 0}

        async def fake_sleep(interval):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await registry._reap_stuck_tasks()

        # Should have slept at least once (continue path)
        assert call_count["n"] >= 1

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_done_task_result_consume(self, caplog):
        """Lines 430-432: Consume result of done stuck tasks."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")

        # Create a completed task
        async def done_ok():
            return "result"

        task = asyncio.create_task(done_ok())
        await asyncio.sleep(0.01)

        registry._stuck_tasks["done_ok"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await registry._reap_stuck_tasks()

        assert "done_ok" not in registry._stuck_tasks
        assert "Reaped 1 completed stuck tasks" in caplog.text

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_general_exception(self, caplog):
        """Lines 464-465: General exception in reaper loop."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")

        call_count = {"n": 0}

        async def fake_sleep(interval):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return  # first sleep completes
            raise asyncio.CancelledError()

        # Put a real-ish entry in stuck tasks so the loop processes it
        registry._stuck_tasks["fake"] = Mock()
        # Make items() raise on the second call (after sleep)
        original_items = registry._stuck_tasks.items

        items_call = {"n": 0}

        def patched_items():
            items_call["n"] += 1
            raise RuntimeError("reaper boom")

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            registry._stuck_tasks = {"fake": Mock()}  # reset
            # Directly patch the dict's items to raise
            registry._stuck_tasks = MagicMock()
            registry._stuck_tasks.__bool__ = Mock(return_value=True)
            registry._stuck_tasks.items = Mock(side_effect=RuntimeError("reaper boom"))
            with pytest.raises(asyncio.CancelledError):
                await registry._reap_stuck_tasks()

        assert "Error in stuck task reaper" in caplog.text

    @pytest.mark.asyncio
    async def test_reap_stuck_tasks_remaining_warning(self, caplog):
        """Lines 458-459: Warning about remaining stuck tasks."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")

        event = asyncio.Event()

        async def waiter():
            await event.wait()

        task = asyncio.create_task(waiter())
        registry._stuck_tasks["remaining"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        async def fake_wait_for(coro, *, timeout=None):
            raise asyncio.TimeoutError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with patch("mcpgateway.cache.session_registry.asyncio.wait_for", fake_wait_for):
                with pytest.raises(asyncio.CancelledError):
                    await registry._reap_stuck_tasks()

        assert "Stuck tasks remaining: 1" in caplog.text

        event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Shutdown edge cases (lines 562-580, 589)
# ---------------------------------------------------------------------------
class TestShutdownEdgeCases:
    """Cover shutdown branches for stuck tasks and respond tasks."""

    @pytest.mark.asyncio
    async def test_shutdown_respond_tasks_timeout(self, caplog):
        """Lines 562-563: Timeout waiting for respond tasks during shutdown."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        event = asyncio.Event()

        async def stubborn():
            try:
                await event.wait()
            except asyncio.CancelledError:
                # Ignore cancellation - be stubborn
                await asyncio.sleep(999)

        task = asyncio.create_task(stubborn())
        registry.register_respond_task("stubborn_shutdown", task)

        # Mock wait_for to always timeout for the gather
        original_wait_for = asyncio.wait_for

        async def selective_wait_for(coro, *, timeout=None):
            if timeout == 10.0:  # The respond tasks gather
                raise asyncio.TimeoutError()
            return await original_wait_for(coro, timeout=timeout)

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", selective_wait_for):
            await registry.shutdown()

        assert "Timeout waiting for respond tasks to cancel" in caplog.text

        event.set()
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=0.1)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    @pytest.mark.asyncio
    async def test_shutdown_stuck_tasks_present(self, caplog):
        """Lines 566-580: Shutdown cancels stuck tasks."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        # Add a stuck task that completes on cancel
        async def completable():
            await asyncio.sleep(999)

        task = asyncio.create_task(completable())
        registry._stuck_tasks["stuck1"] = task

        await registry.shutdown()

        assert "Attempting final cancellation of 1 stuck tasks" in caplog.text

    @pytest.mark.asyncio
    async def test_shutdown_stuck_tasks_timeout(self, caplog):
        """Lines 579-580: Stuck tasks timeout during shutdown."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        event = asyncio.Event()

        async def really_stubborn():
            try:
                await event.wait()
            except asyncio.CancelledError:
                await asyncio.sleep(999)

        task = asyncio.create_task(really_stubborn())
        registry._stuck_tasks["really_stuck"] = task

        original_wait_for = asyncio.wait_for

        async def selective_wait_for(coro, *, timeout=None):
            if timeout == 5.0:  # The stuck tasks gather
                raise asyncio.TimeoutError()
            return await original_wait_for(coro, timeout=timeout)

        with patch("mcpgateway.cache.session_registry.asyncio.wait_for", selective_wait_for):
            await registry.shutdown()

        assert "Some stuck tasks could not be cancelled during shutdown" in caplog.text

        event.set()
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=0.1)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    @pytest.mark.asyncio
    async def test_shutdown_redis_pubsub_timeout(self, monkeypatch, caplog):
        """Line 589: Redis pubsub close times out during shutdown."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        mock_pubsub = AsyncMock()
        mock_pubsub.aclose = AsyncMock(side_effect=asyncio.TimeoutError())

        mock_redis = AsyncMock()
        mock_redis.pubsub = Mock(return_value=mock_pubsub)

        async def mock_get_redis_client():
            return mock_redis

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            await registry.initialize()

            # Override wait_for to simulate timeout
            original_wait_for = asyncio.wait_for

            async def timeout_wait_for(coro, *, timeout=None):
                # Simulate timeout on pubsub close
                if timeout == settings.mcp_session_pool_cleanup_timeout:
                    raise asyncio.TimeoutError()
                return await original_wait_for(coro, timeout=timeout)

            with patch("mcpgateway.cache.session_registry.asyncio.wait_for", timeout_wait_for):
                await registry.shutdown()

            assert "Redis pubsub close timed out" in caplog.text


# ---------------------------------------------------------------------------
# add_session: redis client not initialized (lines 642-643)
# ---------------------------------------------------------------------------
class TestAddSessionEdgeCases:
    """Cover add_session edge cases."""

    @pytest.mark.asyncio
    async def test_add_session_redis_no_client(self, monkeypatch, caplog):
        """Lines 641-643: Redis client not initialized."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return AsyncMock()

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            # Manually set _redis to None to simulate not initialized
            registry._redis = None
            tr = FakeSSETransport("no_redis")
            await registry.add_session("no_redis", tr)

        assert "Redis client not initialized" in caplog.text


# ---------------------------------------------------------------------------
# get_session: redis no client (line 740), remove_session: redis no client
# (line 855), remove session with client_capabilities (lines 838-840)
# ---------------------------------------------------------------------------
class TestGetRemoveSessionEdgeCases:
    """Cover get_session and remove_session edge cases."""

    @pytest.mark.asyncio
    async def test_get_session_redis_no_client(self, monkeypatch):
        """Line 740: get_session when redis client is None."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return AsyncMock()

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            registry._redis = None

            result = await registry.get_session("test")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_session_redis_exists_in_backend_but_not_local(self, registry, caplog):
        """Lines 744-746: Exists in Redis but not local cache (informational log)."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        registry._backend = "redis"
        registry._sessions.clear()
        registry._redis = AsyncMock()
        registry._redis.exists = AsyncMock(return_value=1)

        result = await registry.get_session("sid_exists")
        assert result is None
        assert "exists in Redis but not in local cache" in caplog.text

    @pytest.mark.asyncio
    async def test_get_session_redis_not_in_backend_returns_none(self, registry):
        """Line 744->746: False branch of `if session_exists` (no log)."""
        registry._backend = "redis"
        registry._sessions.clear()
        registry._redis = AsyncMock()
        registry._redis.exists = AsyncMock(return_value=0)

        result = await registry.get_session("sid_missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_database_exists_in_backend_but_not_local(self, monkeypatch, registry, caplog):
        """Lines 780-782: Exists in database but not local cache (informational log)."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        registry._backend = "database"
        registry._sessions.clear()

        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = Mock()
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)

        result = await registry.get_session("sid_exists")
        assert result is None
        assert "exists in database but not in local cache" in caplog.text

    @pytest.mark.asyncio
    async def test_get_session_database_not_in_backend_returns_none(self, monkeypatch, registry):
        """Line 780->782: False branch of `if exists` (no log)."""
        registry._backend = "database"
        registry._sessions.clear()

        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)

        result = await registry.get_session("sid_missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_session_redis_no_client(self, monkeypatch):
        """Line 855: remove_session when redis client is None."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return AsyncMock()

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            tr = FakeSSETransport("redis_rm")
            registry._sessions["redis_rm"] = tr
            registry._redis = None

            await registry.remove_session("redis_rm")
            # Should return early without error
            assert "redis_rm" not in registry._sessions

    @pytest.mark.asyncio
    async def test_remove_session_cleans_client_capabilities(self, registry, caplog):
        """Lines 838-840: Client capabilities cleaned up on remove."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        tr = FakeSSETransport("cap_test")
        await registry.add_session("cap_test", tr)
        await registry.store_client_capabilities("cap_test", {"elicitation": True})

        await registry.remove_session("cap_test")
        result = await registry.get_client_capabilities("cap_test")
        assert result is None
        assert "Removed capabilities for session cap_test" in caplog.text


# ---------------------------------------------------------------------------
# broadcast edge cases: redis no client (lines 954-956),
# database backend (line 968)
# ---------------------------------------------------------------------------
class TestBroadcastEdgeCases:
    """Cover broadcast edge cases."""

    @pytest.mark.asyncio
    async def test_broadcast_redis_no_client(self, monkeypatch, caplog):
        """Lines 954-956: broadcast when redis client is None."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return AsyncMock()

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            registry._redis = None

            await registry.broadcast("test", {"msg": "test"})
            assert "Redis client not initialized" in caplog.text

    @pytest.mark.asyncio
    async def test_broadcast_unknown_backend_falls_through(self, registry):
        """Line 968->exit: Unknown backend falls through without raising (branch coverage)."""
        registry._backend = "unknown"
        await registry.broadcast("sid", {"msg": "noop"})


# ---------------------------------------------------------------------------
# initialize edge case: redis client factory returns None (line 496->511)
# ---------------------------------------------------------------------------
class TestInitializeEdgeCases:
    """Cover initialize edge cases."""

    @pytest.mark.asyncio
    async def test_initialize_redis_client_none(self, monkeypatch):
        """Line 496->511: get_redis_client returns None so pubsub isn't set, but reaper still starts."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return None

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            reg = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            await reg.initialize()
            try:
                assert reg._redis is None
                assert reg._stuck_task_reaper is not None
            finally:
                await reg.shutdown()

    @pytest.mark.asyncio
    async def test_initialize_unknown_backend_branch_arc(self):
        """Line 506->511: Force an unexpected _backend value to cover the final-elif false branch."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "unknown"
        await reg.initialize()
        try:
            assert reg._stuck_task_reaper is not None
        finally:
            await reg.shutdown()


# ---------------------------------------------------------------------------
# respond: redis + database backend coverage (lines 1185-1251, 1305-1480)
# ---------------------------------------------------------------------------
class TestRespondBackends:
    """Cover respond() loops for redis/database backends without real external services."""

    @pytest.mark.asyncio
    async def test_respond_redis_no_client_warns_and_returns(self, caplog):
        """Lines 1185-1187: Redis respond should warn and return when _redis is None."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._redis = None

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert "Redis client not initialized, cannot respond to sid" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_processes_one_message_and_cleans_up(self, monkeypatch):
        """Happy-path through redis respond loop with pubsub cleanup."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        captured: Dict[str, Any] = {}

        async def fake_generate_response(*, message, transport, **kwargs):
            captured["message"] = message
            captured["transport"] = transport
            # Ensure loop exits on next iteration.
            reg._sessions.pop("sid", None)

        monkeypatch.setattr(reg, "generate_response", fake_generate_response)

        class _OneShotPubSub:
            def __init__(self):
                self.unsubscribed: str | None = None
                self.closed = False
                self._sent = False

            async def subscribe(self, channel):
                return None

            async def get_message(self, **_kwargs):
                if self._sent:
                    return None
                self._sent = True
                payload = {"message": {"method": "ping", "id": 1, "params": {}}, "timestamp": 0}
                return {"type": "message", "data": json.dumps(payload).encode("utf-8")}

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def aclose(self):
                self.closed = True

        pubsub = _OneShotPubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert captured["transport"] is tr
        assert captured["message"]["method"] == "ping"
        assert pubsub.unsubscribed == "sid"
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_respond_redis_timeout_error_continues_then_exits(self):
        """Lines 1207-1209: TimeoutError from pubsub.get_message should continue loop."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        class _TimeoutPubSub:
            def __init__(self):
                self._called = False
                self.unsubscribed: str | None = None
                self.closed = False

            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                if not self._called:
                    self._called = True
                    # Trigger timeout path, then force loop exit next iteration.
                    reg._sessions.pop("sid", None)
                    raise asyncio.TimeoutError()
                return None

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def aclose(self):
                self.closed = True

        pubsub = _TimeoutPubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert pubsub.unsubscribed == "sid"
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_respond_redis_msg_none_sleeps_and_continues(self):
        """Lines 1211-1215: None message should sleep briefly to prevent tight loop."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        class _NonePubSub:
            def __init__(self):
                self._called = False
                self.unsubscribed: str | None = None
                self.closed = False

            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                if not self._called:
                    self._called = True
                    # Ensure loop breaks after the sleep/continue.
                    reg._sessions.pop("sid", None)
                    return None
                return None

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def aclose(self):
                self.closed = True

        pubsub = _NonePubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)) as mock_sleep:
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
            mock_sleep.assert_any_await(0.1)

        assert pubsub.unsubscribed == "sid"
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_respond_redis_non_message_type_sleeps_and_continues(self):
        """Lines 1216-1219: Non-message types should also sleep briefly."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        class _NonMessagePubSub:
            def __init__(self):
                self._called = False
                self.unsubscribed: str | None = None
                self.closed = False

            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                if not self._called:
                    self._called = True
                    reg._sessions.pop("sid", None)
                    return {"type": "subscribe", "data": b"{}"}
                return None

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def aclose(self):
                self.closed = True

        pubsub = _NonMessagePubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)) as mock_sleep:
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
            mock_sleep.assert_any_await(0.1)

        assert pubsub.unsubscribed == "sid"
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_respond_redis_pubsub_close_fallback(self):
        """Lines 1243-1245: If pubsub lacks aclose(), use close()."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        class _CloseOnlyPubSub:
            def __init__(self):
                self._called = False
                self.closed = False
                self.unsubscribed: str | None = None

            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                if not self._called:
                    self._called = True
                    # Exit quickly.
                    reg._sessions.pop("sid", None)
                    return None
                return None

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def close(self):
                self.closed = True

        pubsub = _CloseOnlyPubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert pubsub.unsubscribed == "sid"
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_respond_redis_transport_missing_skips_generate_response(self):
        """Line 1224->1196: transport is falsy, so generate_response isn't called and loop continues."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"

        # Keep the key present so the loop starts, but make transport falsy.
        reg._sessions["sid"] = None

        class _PubSub:
            def __init__(self):
                self._called = False
                self.unsubscribed: str | None = None

            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                if not self._called:
                    self._called = True
                    # Remove session so the loop exits next iteration.
                    reg._sessions.pop("sid", None)
                    payload = {"message": {"method": "ping", "id": 1, "params": {}}, "timestamp": 0}
                    return {"type": "message", "data": json.dumps(payload).encode("utf-8")}
                return None

            async def unsubscribe(self, channel):
                self.unsubscribed = channel

            async def aclose(self):
                return None

        pubsub = _PubSub()

        class _MockRedis:
            def pubsub(self):
                return pubsub

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert pubsub.unsubscribed == "sid"

    @pytest.mark.asyncio
    async def test_respond_redis_logs_error_on_exception(self, caplog):
        """Lines 1229-1230: Exceptions in Redis respond loop are logged."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _BoomPubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                raise RuntimeError("boom")

            async def unsubscribe(self, _channel):
                return None

            async def aclose(self):
                return None

        class _MockRedis:
            def pubsub(self):
                return _BoomPubSub()

        reg._redis = _MockRedis()

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert "PubSub listener error for session sid: boom" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_cancelled_error_is_logged_and_propagates(self, caplog):
        """Lines 1226-1228: CancelledError path logs and re-raises."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _CancelPubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                raise asyncio.CancelledError()

            async def unsubscribe(self, _channel):
                return None

            async def aclose(self):
                return None

        class _MockRedis:
            def pubsub(self):
                return _CancelPubSub()

        reg._redis = _MockRedis()

        with pytest.raises(asyncio.CancelledError):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "PubSub listener for session sid cancelled" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_cleanup_unsubscribe_timeout_logged(self, caplog):
        """Lines 1236-1237: unsubscribe TimeoutError is logged at debug."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _TimeoutUnsubPubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                # Exit loop quickly.
                reg._sessions.pop("sid", None)
                return None

            async def unsubscribe(self, _channel):
                raise asyncio.TimeoutError()

            async def aclose(self):
                return None

        class _MockRedis:
            def pubsub(self):
                return _TimeoutUnsubPubSub()

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "Pubsub unsubscribe timed out for session sid" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_cleanup_unsubscribe_exception_logged(self, caplog):
        """Lines 1238-1239: unsubscribe Exception is logged at debug."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _BoomUnsubPubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                reg._sessions.pop("sid", None)
                return None

            async def unsubscribe(self, _channel):
                raise RuntimeError("unsub boom")

            async def aclose(self):
                return None

        class _MockRedis:
            def pubsub(self):
                return _BoomUnsubPubSub()

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "Error unsubscribing pubsub for session sid: unsub boom" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_cleanup_close_timeout_logged(self, caplog):
        """Lines 1245-1246: close TimeoutError is logged at debug."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _TimeoutClosePubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                reg._sessions.pop("sid", None)
                return None

            async def unsubscribe(self, _channel):
                return None

            async def aclose(self):
                raise asyncio.TimeoutError()

        class _MockRedis:
            def pubsub(self):
                return _TimeoutClosePubSub()

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "Pubsub close timed out for session sid" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_redis_cleanup_close_exception_logged(self, caplog):
        """Lines 1247-1248: close Exception is logged at debug."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "redis"
        reg._sessions["sid"] = FakeSSETransport("sid")

        class _BoomClosePubSub:
            async def subscribe(self, _channel):
                return None

            async def get_message(self, **_kwargs):
                reg._sessions.pop("sid", None)
                return None

            async def unsubscribe(self, _channel):
                return None

            async def aclose(self):
                raise RuntimeError("close boom")

        class _MockRedis:
            def pubsub(self):
                return _BoomClosePubSub()

        reg._redis = _MockRedis()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "Error closing pubsub for session sid: close boom" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_database_session_closing_breaks_early(self, caplog):
        """Lines 1426-1427: Closing sessions should stop DB poll loop early."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"
        reg._closing_sessions.add("sid")

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert "closing, stopping poll loop early" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_database_processes_record_and_removes_message(self, monkeypatch):
        """Cover _db_read_session_and_message, message extraction, transport branch, and _db_remove."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr

        # DB mocks for read + remove.
        read_query = Mock()
        read_query.outerjoin.return_value = read_query
        read_query.filter.return_value = read_query
        read_query.order_by.return_value = read_query

        record = Mock()
        record.message = json.dumps({"message": {"method": "ping", "id": 1, "params": {}}, "timestamp": 0})

        session_obj = Mock()
        read_query.first.side_effect = [(session_obj, record), None]

        remove_query = Mock()
        remove_query.filter.return_value = remove_query
        remove_query.delete.return_value = 1

        mock_db = Mock()
        mock_db.rollback = Mock()
        mock_db.commit = Mock()
        mock_db.close = Mock()

        def _query_side_effect(*args):
            if len(args) == 2:
                return read_query
            return remove_query

        mock_db.query.side_effect = _query_side_effect

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)
        monkeypatch.setattr(reg, "generate_response", AsyncMock(return_value=None))

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        reg.generate_response.assert_awaited()
        assert mock_db.commit.called
        assert mock_db.close.called

    @pytest.mark.asyncio
    async def test_respond_database_record_but_no_transport_backoffs(self, monkeypatch):
        """Cover transport-missing branch when a DB record is present."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        read_query = Mock()
        read_query.outerjoin.return_value = read_query
        read_query.filter.return_value = read_query
        read_query.order_by.return_value = read_query

        record = Mock()
        record.message = json.dumps({"message": {"method": "ping"}, "timestamp": 0})
        session_obj = Mock()
        read_query.first.side_effect = [(session_obj, record), None]

        mock_db = Mock()
        mock_db.rollback = Mock()
        mock_db.close = Mock()
        mock_db.query.return_value = read_query

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", AsyncMock(return_value=None)):
            await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert mock_db.close.called

    @pytest.mark.asyncio
    async def test_respond_database_logs_error_on_exception(self, monkeypatch, caplog):
        """Lines 1466-1467: Unexpected exceptions in DB poll loop are logged."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        async def boom_to_thread(*_args, **_kwargs):
            raise RuntimeError("db poll boom")

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", boom_to_thread)
        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        assert "Message check loop error for session sid" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_database_db_read_rolls_back_on_exception(self, monkeypatch):
        """Lines 1321-1323: _db_read_session_and_message rolls back and re-raises."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        read_query = Mock()
        read_query.outerjoin.return_value = read_query
        read_query.filter.return_value = read_query
        read_query.order_by.return_value = read_query
        read_query.first.side_effect = RuntimeError("read boom")

        mock_db = Mock()
        mock_db.query.return_value = read_query
        mock_db.rollback = Mock()
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")
        mock_db.rollback.assert_called()
        mock_db.close.assert_called()

    @pytest.mark.asyncio
    async def test_respond_database_db_remove_rolls_back_on_exception(self, monkeypatch):
        """Lines 1354-1356: _db_remove rolls back and re-raises."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        tr = FakeSSETransport("sid")
        reg._sessions["sid"] = tr
        monkeypatch.setattr(reg, "generate_response", AsyncMock(return_value=None))

        read_query = Mock()
        read_query.outerjoin.return_value = read_query
        read_query.filter.return_value = read_query
        read_query.order_by.return_value = read_query

        record = Mock()
        record.message = json.dumps({"message": {"method": "ping", "id": 1, "params": {}}, "timestamp": 0})
        session_obj = Mock()
        read_query.first.side_effect = [(session_obj, record)]

        remove_query = Mock()
        remove_query.filter.return_value = remove_query
        remove_query.delete.return_value = 1

        mock_db = Mock()
        mock_db.rollback = Mock()
        mock_db.commit = Mock(side_effect=RuntimeError("commit boom"))
        mock_db.close = Mock()

        def _query_side_effect(*args):
            if len(args) == 2:
                return read_query
            return remove_query

        mock_db.query.side_effect = _query_side_effect

        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        async def immediate_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", immediate_to_thread)

        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        mock_db.rollback.assert_called()
        mock_db.close.assert_called()

    @pytest.mark.asyncio
    async def test_respond_database_cancelled_error_propagates(self, monkeypatch, caplog):
        """Lines 1463-1465 and 1474-1476: CancelledError is logged and re-raised."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        reg = SessionRegistry(backend="memory")
        reg._backend = "database"

        async def ok_to_thread(func, *args, **kwargs):
            # Always report session exists with no message so we reach sleep.
            return (Mock(), None)

        monkeypatch.setattr("mcpgateway.cache.session_registry.asyncio.to_thread", ok_to_thread)

        async def cancel_sleep(_interval):
            raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", cancel_sleep):
            with pytest.raises(asyncio.CancelledError):
                await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")

        assert "Message check loop cancelled for session sid" in caplog.text
        assert "Database respond cancelled for session sid" in caplog.text

    @pytest.mark.asyncio
    async def test_respond_unknown_backend_branch_arc(self):
        """Line 1253->exit: Force respond() backend chain fall-through for branch coverage."""
        reg = SessionRegistry(backend="memory")
        reg._backend = "unknown"
        await reg.respond(server_id=None, user={}, session_id="sid", base_url="http://localhost")


# ---------------------------------------------------------------------------
# shutdown branch arcs (lines 541->549, 558->566, 575->584)
# ---------------------------------------------------------------------------
class TestShutdownBranchArcs:
    """Cover hard-to-hit shutdown branch arcs for coverage."""

    @pytest.mark.asyncio
    async def test_shutdown_without_initialize_skips_reaper(self):
        """Line 541->549: _stuck_task_reaper is None, so the block is skipped."""
        reg = SessionRegistry(backend="memory")
        await reg.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_truthy_respond_tasks_but_no_values(self):
        """Line 558->566: _respond_tasks is truthy but values() is empty (branch coverage)."""
        reg = SessionRegistry(backend="memory")
        reg._respond_tasks = MagicMock()
        reg._respond_tasks.__bool__ = Mock(return_value=True)
        reg._respond_tasks.values = Mock(return_value=[])
        reg._respond_tasks.clear = Mock()
        await reg.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_truthy_stuck_tasks_but_no_values(self):
        """Line 575->584: _stuck_tasks is truthy but values() is empty (branch coverage)."""
        reg = SessionRegistry(backend="memory")
        reg._stuck_tasks = MagicMock()
        reg._stuck_tasks.__bool__ = Mock(return_value=True)
        reg._stuck_tasks.values = Mock(return_value=[])
        reg._stuck_tasks.clear = Mock()
        await reg.shutdown()

# ---------------------------------------------------------------------------
# _register_session_mapping and get_all_session_ids (lines 1028-1079, 1087-1088)
# ---------------------------------------------------------------------------
class TestRegisterSessionMapping:
    """Cover _register_session_mapping."""

    @pytest.mark.asyncio
    async def test_register_session_mapping_affinity_disabled(self, registry, monkeypatch):
        """Line 1028-1029: Session affinity disabled."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", False)
        # Should return immediately
        await registry._register_session_mapping("sid", {"method": "tools/call"}, "user@test.com")

    @pytest.mark.asyncio
    async def test_register_session_mapping_not_tools_call(self, registry, monkeypatch):
        """Lines 1032-1034: Method is not tools/call."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        await registry._register_session_mapping("sid", {"method": "tools/list"}, "user@test.com")

    @pytest.mark.asyncio
    async def test_register_session_mapping_no_tool_name(self, registry, monkeypatch):
        """Lines 1038-1040: No tool name in params."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)
        await registry._register_session_mapping("sid", {"method": "tools/call", "params": {}}, "user@test.com")

    @pytest.mark.asyncio
    async def test_register_session_mapping_tool_not_in_cache(self, registry, monkeypatch):
        """Lines 1048-1050: Tool not found in cache."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value=None)

        with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
            await registry._register_session_mapping(
                "sid",
                {"method": "tools/call", "params": {"name": "my_tool"}},
                "user@test.com",
            )

    @pytest.mark.asyncio
    async def test_register_session_mapping_incomplete_gateway(self, registry, monkeypatch):
        """Lines 1058-1060: Incomplete gateway info."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value={"gateway": {"url": None, "id": None, "transport": None}})

        with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
            await registry._register_session_mapping(
                "sid",
                {"method": "tools/call", "params": {"name": "my_tool"}},
                "user@test.com",
            )

    @pytest.mark.asyncio
    async def test_register_session_mapping_success(self, registry, monkeypatch, caplog):
        """Lines 1062-1075: Successful registration."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(return_value={
            "gateway": {"url": "http://gw:9000", "id": "gw1", "transport": "sse"}
        })

        mock_pool = AsyncMock()
        mock_pool.register_session_mapping = AsyncMock()

        with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
            with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                await registry._register_session_mapping(
                    "sid12345678",
                    {"method": "tools/call", "params": {"name": "my_tool"}},
                    "user@test.com",
                )

        mock_pool.register_session_mapping.assert_awaited_once()
        assert "Registered session mapping" in caplog.text

    @pytest.mark.asyncio
    async def test_register_session_mapping_exception(self, registry, monkeypatch, caplog):
        """Lines 1077-1079: Exception during registration."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        mock_cache = AsyncMock()
        mock_cache.get = AsyncMock(side_effect=RuntimeError("cache boom"))

        with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
            await registry._register_session_mapping(
                "sid12345678",
                {"method": "tools/call", "params": {"name": "my_tool"}},
                "user@test.com",
            )

        assert "Failed to register session mapping" in caplog.text


class TestGetAllSessionIds:
    """Cover get_all_session_ids."""

    @pytest.mark.asyncio
    async def test_get_all_session_ids(self, registry):
        """Lines 1087-1088."""
        tr1 = FakeSSETransport("s1")
        tr2 = FakeSSETransport("s2")
        await registry.add_session("s1", tr1)
        await registry.add_session("s2", tr2)

        ids = await registry.get_all_session_ids()
        assert set(ids) == {"s1", "s2"}


# ---------------------------------------------------------------------------
# _refresh_session_db (lines 1593-1605)
# ---------------------------------------------------------------------------
class TestRefreshSessionDb:
    """Cover _refresh_session_db."""

    @pytest.mark.asyncio
    async def test_refresh_session_db_found(self, monkeypatch):
        """Lines 1593-1599: Session found and refreshed."""
        mock_db = Mock()
        mock_session_record = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_session_record
        mock_db.commit = Mock()
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
        result = registry._refresh_session_db("test_session")
        assert result is True
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_session_db_not_found(self, monkeypatch):
        """Line 1600: Session not found."""
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
        result = registry._refresh_session_db("test_session")
        assert result is False
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_session_db_exception(self, monkeypatch):
        """Lines 1601-1603: Exception during refresh."""
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.side_effect = RuntimeError("db boom")
        mock_db.rollback = Mock()
        mock_db.close = Mock()

        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        monkeypatch.setattr("mcpgateway.cache.session_registry.get_db", lambda: iter([mock_db]))

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")
        with pytest.raises(RuntimeError, match="db boom"):
            registry._refresh_session_db("test_session")

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# _cleanup_database_sessions (lines 1626, 1629-1631, 1656, 1660-1661)
# ---------------------------------------------------------------------------
class TestCleanupDatabaseSessions:
    """Cover _cleanup_database_sessions."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_disconnected_sessions(self, monkeypatch):
        """Line 1626: Disconnected session removed."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        tr = FakeSSETransport("disc_sess", connected=False)
        registry._sessions["disc_sess"] = tr

        with patch.object(registry, "remove_session", new_callable=AsyncMock) as mock_remove:
            await registry._cleanup_database_sessions()
            mock_remove.assert_called_with("disc_sess")

    @pytest.mark.asyncio
    async def test_cleanup_connection_check_error(self, monkeypatch, caplog):
        """Lines 1629-1631: Error checking connection."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        tr = FakeSSETransport("err_sess")
        tr.is_connected = AsyncMock(side_effect=RuntimeError("conn check boom"))
        registry._sessions["err_sess"] = tr

        await registry._cleanup_database_sessions()
        assert "Error checking connection for session err_sess" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_refresh_exception_result(self, monkeypatch, caplog):
        """Line 1656: Refresh returns an Exception result."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        tr = FakeSSETransport("ref_err", connected=True)
        registry._sessions["ref_err"] = tr

        async def mock_to_thread(func, *args, **kwargs):
            raise RuntimeError("refresh boom")

        monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

        await registry._cleanup_database_sessions()
        assert "Error refreshing session ref_err" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_refresh_returns_false(self, monkeypatch):
        """Lines 1658-1659: Refresh returns False, session removed."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        tr = FakeSSETransport("gone_sess", connected=True)
        registry._sessions["gone_sess"] = tr

        async def mock_to_thread(func, *args, **kwargs):
            return False

        monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

        with patch.object(registry, "remove_session", new_callable=AsyncMock) as mock_remove:
            await registry._cleanup_database_sessions()
            mock_remove.assert_called_with("gone_sess")

    @pytest.mark.asyncio
    async def test_cleanup_process_result_error(self, monkeypatch, caplog):
        """Lines 1660-1661: Error processing refresh result."""
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)
        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        tr = FakeSSETransport("proc_err", connected=True)
        registry._sessions["proc_err"] = tr

        async def mock_to_thread(func, *args, **kwargs):
            return False

        monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

        with patch.object(registry, "remove_session", new_callable=AsyncMock, side_effect=RuntimeError("remove boom")):
            await registry._cleanup_database_sessions()
            assert "Error processing refresh result for session proc_err" in caplog.text


# ---------------------------------------------------------------------------
# _memory_cleanup_task edge case (lines 1656, 1660-1661) - tested above
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _get_oauth_experimental_config (lines 1708-1738)
# ---------------------------------------------------------------------------
class TestGetOauthExperimentalConfig:
    """Cover _get_oauth_experimental_config."""

    def test_oauth_config_server_not_found(self, monkeypatch):
        """Lines 1711-1736: Server not found."""
        mock_db = Mock()
        mock_db.get.return_value = None
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is None
        mock_db.close.assert_called_once()

    def test_oauth_config_server_oauth_disabled(self, monkeypatch):
        """Server found but oauth_enabled is False."""
        mock_server = Mock()
        mock_server.oauth_enabled = False
        mock_server.oauth_config = None

        mock_db = Mock()
        mock_db.get.return_value = mock_server
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is None

    def test_oauth_config_with_authorization_servers(self, monkeypatch, caplog):
        """Lines 1720-1721: oauth_config with authorization_servers."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        mock_server = Mock()
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["read", "write"],
            "bearer_methods_supported": ["header"],
        }

        mock_db = Mock()
        mock_db.get.return_value = mock_server
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is not None
        assert "oauth" in result
        assert result["oauth"]["authorization_servers"] == ["https://auth.example.com"]
        assert result["oauth"]["scopes_supported"] == ["read", "write"]

    def test_oauth_config_with_authorization_server_singular(self, monkeypatch):
        """Lines 1722-1723: oauth_config with authorization_server (singular)."""
        mock_server = Mock()
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_server": "https://auth.example.com",
            "scopes": ["read"],
        }

        mock_db = Mock()
        mock_db.get.return_value = mock_server
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is not None
        assert result["oauth"]["authorization_servers"] == ["https://auth.example.com"]
        assert result["oauth"]["scopes_supported"] == ["read"]

    def test_oauth_config_no_auth_servers(self, monkeypatch):
        """Lines 1733: No authorization_servers key - returns None."""
        mock_server = Mock()
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "scopes": ["read"],
        }

        mock_db = Mock()
        mock_db.get.return_value = mock_server
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is None


# ---------------------------------------------------------------------------
# handle_initialize_logic: store capabilities & OAuth (lines 1793-1806)
# ---------------------------------------------------------------------------
class TestHandleInitializeLogicEdgeCases:
    """Cover handle_initialize_logic edge cases."""

    @pytest.mark.asyncio
    async def test_initialize_stores_client_capabilities(self, registry, caplog):
        """Lines 1793-1795: Store client capabilities."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")
        body = {
            "protocol_version": settings.protocol_version,
            "capabilities": {"elicitation": True},
        }
        await registry.handle_initialize_logic(body, session_id="sess1")

        caps = await registry.get_client_capabilities("sess1")
        assert caps == {"elicitation": True}

    @pytest.mark.asyncio
    async def test_initialize_with_server_id_oauth(self, registry, monkeypatch):
        """Lines 1801-1804: OAuth config queried for server_id."""
        monkeypatch.setattr("asyncio.to_thread", AsyncMock(return_value={"oauth": {"authorization_servers": ["https://auth.example.com"]}}))

        body = {"protocol_version": settings.protocol_version}
        result = await registry.handle_initialize_logic(body, server_id="server1")

        assert result.capabilities.experimental is not None
        assert "oauth" in result.capabilities.experimental

    @pytest.mark.asyncio
    async def test_initialize_with_server_id_oauth_error(self, registry, monkeypatch, caplog):
        """Lines 1805-1806: OAuth config query fails."""
        caplog.set_level(logging.WARNING, logger="mcpgateway.cache.session_registry")
        monkeypatch.setattr("asyncio.to_thread", AsyncMock(side_effect=RuntimeError("oauth boom")))

        body = {"protocol_version": settings.protocol_version}
        result = await registry.handle_initialize_logic(body, server_id="server1")

        assert "Failed to query OAuth config for server server1" in caplog.text
        assert result.capabilities.experimental is None


# ---------------------------------------------------------------------------
# store/get_client_capabilities, elicitation (lines 1829-1831, 1842-1843,
# 1854-1873)
# ---------------------------------------------------------------------------
class TestClientCapabilitiesAndElicitation:
    """Cover store/get_client_capabilities and elicitation methods."""

    @pytest.mark.asyncio
    async def test_store_and_get_capabilities(self, registry):
        """Lines 1829-1831, 1842-1843."""
        await registry.store_client_capabilities("s1", {"elicitation": True})
        result = await registry.get_client_capabilities("s1")
        assert result == {"elicitation": True}

    @pytest.mark.asyncio
    async def test_get_capabilities_not_found(self, registry):
        """Line 1843: Session not found."""
        result = await registry.get_client_capabilities("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_has_elicitation_true(self, registry):
        """Lines 1854-1858: Has elicitation capability."""
        tr = FakeSSETransport("elic1")
        await registry.add_session("elic1", tr)
        await registry.store_client_capabilities("elic1", {"elicitation": True})

        assert await registry.has_elicitation_capability("elic1") is True

    @pytest.mark.asyncio
    async def test_has_elicitation_false(self, registry):
        """Lines 1854-1856: No capabilities stored."""
        assert await registry.has_elicitation_capability("nonexistent") is False

    @pytest.mark.asyncio
    async def test_has_elicitation_false_no_key(self, registry):
        """Line 1858: Capabilities exist but no elicitation key."""
        await registry.store_client_capabilities("s2", {"roots": True})
        assert await registry.has_elicitation_capability("s2") is False

    @pytest.mark.asyncio
    async def test_get_elicitation_capable_sessions(self, registry):
        """Lines 1866-1873: Get sessions with elicitation capability."""
        tr1 = FakeSSETransport("e1")
        tr2 = FakeSSETransport("e2")
        tr3 = FakeSSETransport("e3")
        await registry.add_session("e1", tr1)
        await registry.add_session("e2", tr2)
        await registry.add_session("e3", tr3)

        await registry.store_client_capabilities("e1", {"elicitation": True})
        await registry.store_client_capabilities("e2", {"roots": True})
        await registry.store_client_capabilities("e3", {"elicitation": True})

        result = await registry.get_elicitation_capable_sessions()
        assert set(result) == {"e1", "e3"}

    @pytest.mark.asyncio
    async def test_get_elicitation_capable_sessions_no_session(self, registry):
        """Lines 1871: Session in capabilities but not in _sessions."""
        await registry.store_client_capabilities("orphan", {"elicitation": True})

        result = await registry.get_elicitation_capable_sessions()
        assert "orphan" not in result


# ---------------------------------------------------------------------------
# generate_response edge cases (lines 1926, 1951, 1955, 1962-1968)
# ---------------------------------------------------------------------------
class TestGenerateResponseEdgeCases:
    """Cover generate_response edge cases."""

    @pytest.mark.asyncio
    async def test_generate_response_auth_token_path(self, registry, stub_db, stub_services):
        """Line 1926: user has auth_token."""
        tr = FakeSSETransport("auth_tok")
        await registry.add_session("auth_tok", tr)

        mock_response = Mock()
        mock_response.json.return_value = {"result": {}, "id": 77}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_client

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        msg = {"method": "ping", "id": 77, "params": {}}
        with patch("mcpgateway.cache.session_registry.ResilientHttpClient", MockAsyncClient):
            await registry.generate_response(
                message=msg,
                transport=tr,
                server_id=None,
                user={"auth_token": "my_jwt_token", "email": "user@test.com"},
                base_url="http://host",
            )

        assert tr.sent[-1] == {"jsonrpc": "2.0", "result": {}, "id": 77}

    @pytest.mark.asyncio
    async def test_generate_response_session_affinity_enabled(self, registry, monkeypatch, stub_db, stub_services):
        """Lines 1951, 1955: Session affinity enabled path."""
        monkeypatch.setattr(settings, "mcpgateway_session_affinity_enabled", True)

        tr = FakeSSETransport("affinity_test")
        await registry.add_session("affinity_test", tr)

        mock_response = Mock()
        mock_response.json.return_value = {"result": {}, "id": 88}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_client

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        msg = {"method": "ping", "id": 88, "params": {}}

        with patch("mcpgateway.cache.session_registry.ResilientHttpClient", MockAsyncClient):
            with patch.object(registry, "_register_session_mapping", new_callable=AsyncMock) as mock_reg:
                await registry.generate_response(
                    message=msg,
                    transport=tr,
                    server_id=None,
                    user={"auth_token": "tok", "email": "u@t.com"},
                    base_url="http://host",
                )

                mock_reg.assert_awaited_once()

        # Verify x-mcp-session-id header was passed
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers", {})
        assert "x-mcp-session-id" in headers

    @pytest.mark.asyncio
    async def test_generate_response_servers_path_extraction(self, registry, stub_db, stub_services):
        """Lines 1962-1968: URL path with /servers/ prefix."""
        tr = FakeSSETransport("srv_path")
        await registry.add_session("srv_path", tr)

        mock_response = Mock()
        mock_response.json.return_value = {"result": {}, "id": 99}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_client

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        msg = {"method": "ping", "id": 99, "params": {}}

        with patch("mcpgateway.cache.session_registry.ResilientHttpClient", MockAsyncClient):
            await registry.generate_response(
                message=msg,
                transport=tr,
                server_id=None,
                user={"auth_token": "tok"},
                base_url="http://host/prefix/servers/abc123",
            )

        # Verify the RPC URL strips the /servers/ part
        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "/servers/" not in url
        assert url.endswith("/rpc")


# ---------------------------------------------------------------------------
# Fixtures for stub_db and stub_services (copied from existing test file)
# ---------------------------------------------------------------------------
@pytest.fixture()
def stub_db(monkeypatch):
    """Patch get_db to return a dummy iterator."""

    def _dummy_iter():
        yield None

    monkeypatch.setattr(
        "mcpgateway.cache.session_registry.get_db",
        lambda: _dummy_iter(),
        raising=False,
    )


@pytest.fixture()
def stub_services(monkeypatch):
    """Replace list_* service methods so they return predictable data."""

    class _Item:
        def model_dump(self, *_, **__) -> Dict[str, str]:
            return {"name": "demo"}

    async def _return_items(*args, **kwargs):
        return [_Item()]

    mod = "mcpgateway.cache.session_registry"
    monkeypatch.setattr(f"{mod}.tool_service.list_tools", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.tool_service.list_server_tools", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.prompt_service.list_prompts", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.prompt_service.list_server_prompts", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.resource_service.list_resources", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.resource_service.list_server_resources", _return_items, raising=False)


# ---------------------------------------------------------------------------
# _refresh_redis_sessions: no redis (line 1490)
# ---------------------------------------------------------------------------
class TestRefreshRedisNoClient:
    """Cover _refresh_redis_sessions when _redis is None."""

    @pytest.mark.asyncio
    async def test_refresh_redis_sessions_no_client(self, monkeypatch):
        """Line 1490: _redis is None."""
        monkeypatch.setattr("mcpgateway.cache.session_registry.REDIS_AVAILABLE", True)

        async def mock_get_redis_client():
            return AsyncMock()

        with patch("mcpgateway.cache.session_registry.get_redis_client", mock_get_redis_client):
            registry = SessionRegistry(backend="redis", redis_url="redis://localhost:6379")
            registry._redis = None
            await registry._refresh_redis_sessions()
            # Should return early without error


# ---------------------------------------------------------------------------
# _memory_cleanup_task edge: CancelledError during sleep (already tested
# but verify the exact log message)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _cancel_respond_task: task.done() with CancelledError (line 345)
# and successful cancel path (lines 356-357)
# ---------------------------------------------------------------------------
class TestCancelRespondTaskDoneStates:
    """Cover task.done() edge cases in _cancel_respond_task."""

    @pytest.mark.asyncio
    async def test_cancel_task_done_cancelled(self, registry):
        """Line 345: task.result() raises CancelledError."""
        async def cancelled_task():
            raise asyncio.CancelledError()

        task = asyncio.create_task(cancelled_task())
        await asyncio.sleep(0.01)  # Let task fail with CancelledError
        assert task.done()

        registry.register_respond_task("done_cancelled", task)
        await registry._cancel_respond_task("done_cancelled")
        assert "done_cancelled" not in registry._respond_tasks

    @pytest.mark.asyncio
    async def test_cancel_task_successful_wait(self, registry, caplog):
        """Lines 356-357: task.cancel() + wait_for succeeds normally."""
        caplog.set_level(logging.DEBUG, logger="mcpgateway.cache.session_registry")

        async def swallow_cancel():
            """Swallow CancelledError so wait_for() completes normally (covers 356-357)."""
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(swallow_cancel())
        await asyncio.sleep(0)
        registry.register_respond_task("cancel_ok", task)

        await registry._cancel_respond_task("cancel_ok")
        assert "cancel_ok" not in registry._respond_tasks
        assert "Respond task cancelled for session cancel_ok" in caplog.text


# ---------------------------------------------------------------------------
# _reap_stuck_tasks: done task with exception (lines 431-432)
# ---------------------------------------------------------------------------
class TestReapStuckTasksDoneException:
    """Cover done stuck task result consumption."""

    @pytest.mark.asyncio
    async def test_reap_done_task_with_exception(self, caplog):
        """Lines 431-432: task.result() raises Exception during reap."""
        caplog.set_level(logging.INFO, logger="mcpgateway.cache.session_registry")
        registry = SessionRegistry(backend="memory")

        async def failing():
            raise ValueError("task failed")

        task = asyncio.create_task(failing())
        await asyncio.sleep(0.01)
        assert task.done()

        registry._stuck_tasks["failed_done"] = task

        sleep_calls = {"count": 0}

        async def fake_sleep(interval):
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError()

        with patch("mcpgateway.cache.session_registry.asyncio.sleep", fake_sleep):
            with pytest.raises(asyncio.CancelledError):
                await registry._reap_stuck_tasks()

        assert "failed_done" not in registry._stuck_tasks
        assert "Reaped 1 completed stuck tasks" in caplog.text


# ---------------------------------------------------------------------------
# generate_response: servers path where root_path == "/" (lines 1965-1966)
# ---------------------------------------------------------------------------
class TestGenerateResponseServersPath:
    """Cover the /servers/ path extraction edge case."""

    @pytest.mark.asyncio
    async def test_generate_response_servers_at_root(self, registry, stub_db, stub_services):
        """Lines 1965-1966: root_path == '/' becomes empty string."""
        tr = FakeSSETransport("root_srv")
        await registry.add_session("root_srv", tr)

        mock_response = Mock()
        mock_response.json.return_value = {"result": {}, "id": 55}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_client

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        msg = {"method": "ping", "id": 55, "params": {}}

        with patch("mcpgateway.cache.session_registry.ResilientHttpClient", MockAsyncClient):
            await registry.generate_response(
                message=msg,
                transport=tr,
                server_id=None,
                user={"auth_token": "tok"},
                base_url="http://host/servers/abc123",
            )

        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert url == "http://host/rpc"

    @pytest.mark.asyncio
    async def test_generate_response_servers_index_value_error(self, registry, stub_db, stub_services):
        """Lines 1966-1967: ValueError in path_parts.index('servers') falls back to empty root_path."""
        tr = FakeSSETransport("valerr_srv")
        await registry.add_session("valerr_srv", tr)

        mock_response = Mock()
        mock_response.json.return_value = {"result": {}, "id": 56}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return mock_client

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        class _Parts(list):
            def index(self, *_args, **_kwargs):  # noqa: A003 - match list.index signature
                raise ValueError("servers not found")

        class _Path(str):
            def split(self, sep=None, maxsplit=-1):  # noqa: D401
                return _Parts(super().split(sep, maxsplit))

        class _Parsed:
            scheme = "http"
            netloc = "host"
            path = _Path("/servers/abc123")

        def fake_urlparse(_url: str):  # noqa: D401
            return _Parsed()

        msg = {"method": "ping", "id": 56, "params": {}}

        with patch("mcpgateway.cache.session_registry.urlparse", fake_urlparse):
            with patch("mcpgateway.cache.session_registry.ResilientHttpClient", MockAsyncClient):
                await registry.generate_response(
                    message=msg,
                    transport=tr,
                    server_id=None,
                    user={"auth_token": "tok"},
                    base_url="http://ignored/servers/abc123",
                )

        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert url == "http://host/rpc"


# ---------------------------------------------------------------------------
# OAuth config: scopes fallback (line 1727->1731 branch)
# ---------------------------------------------------------------------------
class TestOauthConfigScopesBranch:
    """Cover oauth config with no scopes."""

    def test_oauth_config_no_scopes(self, monkeypatch):
        """Lines 1726-1728: No scopes_supported or scopes in config."""
        mock_server = Mock()
        mock_server.oauth_enabled = True
        mock_server.oauth_config = {
            "authorization_servers": ["https://auth.example.com"],
            # No scopes at all
        }

        mock_db = Mock()
        mock_db.get.return_value = mock_server
        mock_db.close = Mock()

        mock_session_local = Mock(return_value=mock_db)
        monkeypatch.setattr("mcpgateway.cache.session_registry.SQLALCHEMY_AVAILABLE", True)

        registry = SessionRegistry(backend="database", database_url="sqlite:///test.db")

        with patch("mcpgateway.db.SessionLocal", mock_session_local):
            result = registry._get_oauth_experimental_config("server1")

        assert result is not None
        assert "scopes_supported" not in result["oauth"]
        assert result["oauth"]["bearer_methods_supported"] == ["header"]


class TestSessionOwnerTracking:
    """Cover session owner set/get lifecycle for message authorization."""

    @pytest.mark.asyncio
    async def test_set_and_get_session_owner_memory_backend(self, registry):
        tr = FakeSSETransport("owner-1")
        await registry.add_session("owner-1", tr)

        await registry.set_session_owner("owner-1", "owner@example.com")
        owner = await registry.get_session_owner("owner-1")
        assert owner == "owner@example.com"

    @pytest.mark.asyncio
    async def test_set_session_owner_none_backend_noop(self, registry):
        registry._backend = "none"
        await registry.set_session_owner("owner-none", "owner@example.com")
        assert "owner-none" not in registry._session_owners

    @pytest.mark.asyncio
    async def test_set_session_owner_memory_clear(self, registry):
        await registry.set_session_owner("owner-clear", "owner@example.com")
        await registry.set_session_owner("owner-clear", None)
        assert "owner-clear" not in registry._session_owners

    @pytest.mark.asyncio
    async def test_set_session_owner_redis_without_client(self, registry):
        registry._backend = "redis"
        registry._redis = None
        await registry.set_session_owner("owner-r-noclient", "owner@example.com")
        # Local cache is still updated before backend write attempt.
        assert registry._session_owners["owner-r-noclient"] == "owner@example.com"

    @pytest.mark.asyncio
    async def test_set_session_owner_redis_set_and_delete(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        registry._redis = redis_client

        await registry.set_session_owner("owner-r1", "owner@example.com")
        redis_client.setex.assert_awaited_once_with("mcp:session_owner:owner-r1", registry._session_ttl, "owner@example.com")

        await registry.set_session_owner("owner-r1", None)
        redis_client.delete.assert_awaited_with("mcp:session_owner:owner-r1")

    @pytest.mark.asyncio
    async def test_set_session_owner_redis_logs_error(self, registry, caplog):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.setex.side_effect = RuntimeError("redis down")
        registry._redis = redis_client
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")

        await registry.set_session_owner("owner-r-err", "owner@example.com")
        assert "Redis error setting owner for session owner-r-err" in caplog.text

    @pytest.mark.asyncio
    async def test_set_session_owner_database_creates_record(self, registry):
        registry._backend = "database"
        fake_db = _FakeDbSession(first_results=[None])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            await registry.set_session_owner("owner-db-1", "owner@example.com")

        assert fake_db.flush_called is True
        assert fake_db.commit_called >= 1
        assert fake_db.closed is True

    @pytest.mark.asyncio
    async def test_set_session_owner_database_handles_invalid_existing_data(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data="{invalid-json")
        fake_db = _FakeDbSession(first_results=[fake_record])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            await registry.set_session_owner("owner-db-2", "owner@example.com")

        assert "owner_email" in fake_record.data
        assert fake_db.commit_called >= 1

    @pytest.mark.asyncio
    async def test_set_session_owner_database_parses_existing_dict_and_clears_owner(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data='{"owner_email":"old@example.com","x":1}')
        fake_db = _FakeDbSession(first_results=[fake_record])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            await registry.set_session_owner("owner-db-2b", None)

        assert "owner_email" not in (fake_record.data or "")
        assert '"x":1' in (fake_record.data or "")

    @pytest.mark.asyncio
    async def test_set_session_owner_database_rollback_path(self, registry, caplog):
        registry._backend = "database"
        fake_record = SimpleNamespace(data=None)
        fake_db = _FakeDbSession(first_results=[fake_record], commit_effects=[RuntimeError("db write failed")])

        def fake_get_db():
            yield fake_db

        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            await registry.set_session_owner("owner-db-3", "owner@example.com")

        assert fake_db.rollback_called is True
        assert "Database error setting owner for session owner-db-3" in caplog.text

    @pytest.mark.asyncio
    async def test_remove_session_clears_session_owner(self, registry):
        tr = FakeSSETransport("owner-2")
        await registry.add_session("owner-2", tr)
        await registry.set_session_owner("owner-2", "owner@example.com")

        await registry.remove_session("owner-2")
        owner = await registry.get_session_owner("owner-2")
        assert owner is None

    @pytest.mark.asyncio
    async def test_claim_session_owner_memory_backend_returns_existing_owner(self, registry):
        tr = FakeSSETransport("owner-3")
        await registry.add_session("owner-3", tr)

        first = await registry.claim_session_owner("owner-3", "first@example.com")
        second = await registry.claim_session_owner("owner-3", "second@example.com")

        assert first == "first@example.com"
        assert second == "first@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_memory_backend_is_atomic_under_concurrency(self, registry):
        tr = FakeSSETransport("owner-4")
        await registry.add_session("owner-4", tr)

        first_task = asyncio.create_task(registry.claim_session_owner("owner-4", "first@example.com"))
        second_task = asyncio.create_task(registry.claim_session_owner("owner-4", "second@example.com"))

        first_result, second_result = await asyncio.gather(first_task, second_task)

        assert first_result == second_result
        assert first_result in {"first@example.com", "second@example.com"}

    @pytest.mark.asyncio
    async def test_claim_session_owner_none_backend(self, registry):
        registry._backend = "none"
        claimed = await registry.claim_session_owner("owner-none-claim", "owner@example.com")
        assert claimed == "owner@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_memory_existing_owner_inside_lock(self, registry):
        registry._backend = "memory"
        registry._session_owners.clear()

        class InjectingLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                registry._session_owners["owner-lock"] = "existing@example.com"

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001, ARG002
                return False

        registry._lock = InjectingLock()
        claimed = await registry.claim_session_owner("owner-lock", "owner@example.com")
        assert claimed == "existing@example.com"

    @pytest.mark.asyncio
    async def test_session_exists_memory_backend(self, registry):
        assert await registry.session_exists("missing-session") is False

        tr = FakeSSETransport("owner-5")
        await registry.add_session("owner-5", tr)
        assert await registry.session_exists("owner-5") is True

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_without_client_returns_none(self, registry):
        registry._backend = "redis"
        registry._redis = None

        claimed = await registry.claim_session_owner("owner-6", "owner@example.com")
        assert claimed is None
        assert "owner-6" not in registry._session_owners

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_claim_success(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.return_value = True
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-7", "owner@example.com")
        assert claimed == "owner@example.com"
        assert registry._session_owners["owner-7"] == "owner@example.com"
        redis_client.set.assert_awaited_once_with("mcp:session_owner:owner-7", "owner@example.com", ex=registry._session_ttl, nx=True)

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_returns_existing_owner_when_nx_fails(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = [False]
        redis_client.get.return_value = b"existing@example.com"
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-8", "owner@example.com")
        assert claimed == "existing@example.com"
        assert registry._session_owners["owner-8"] == "existing@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_retry_claim_success(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = [False, True]
        redis_client.get.return_value = None
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-8b", "owner@example.com")
        assert claimed == "owner@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_retry_reads_owner_after_second_failure(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = [False, False]
        redis_client.get.side_effect = [None, b"final@example.com"]
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-8c", "owner@example.com")
        assert claimed == "final@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_retry_returns_none_when_owner_missing(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = [False, False]
        redis_client.get.side_effect = [None, None]
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-8d", "owner@example.com")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_retry_owner_empty_string_returns_none(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = [False, False]
        redis_client.get.side_effect = [None, b""]
        registry._redis = redis_client

        claimed = await registry.claim_session_owner("owner-8d-empty", "owner@example.com")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_session_owner_redis_error(self, registry, caplog):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.set.side_effect = RuntimeError("redis failure")
        registry._redis = redis_client
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")

        claimed = await registry.claim_session_owner("owner-8e", "owner@example.com")
        assert claimed is None
        assert "Redis error claiming owner for session owner-8e" in caplog.text

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_uses_thread_result(self, registry):
        registry._backend = "database"
        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(return_value="dbowner@example.com")):
            claimed = await registry.claim_session_owner("owner-9", "owner@example.com")

        assert claimed == "dbowner@example.com"
        assert registry._session_owners["owner-9"] == "dbowner@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_returns_none_when_unverifiable(self, registry):
        registry._backend = "database"
        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(return_value=None)):
            claimed = await registry.claim_session_owner("owner-10", "owner@example.com")

        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_create_conflict_then_success(self, registry):
        registry._backend = "database"
        # First loop insert commit fails -> rollback/continue; second loop succeeds.
        fake_db = _FakeDbSession(first_results=[None, None], commit_effects=[RuntimeError("dup"), None])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            claimed = await registry.claim_session_owner("owner-db-claim-1", "owner@example.com")

        assert claimed == "owner@example.com"
        assert fake_db.rollback_called is True

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_returns_existing_owner(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data='{"owner_email":"existing@example.com"}')
        fake_db = _FakeDbSession(first_results=[fake_record])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            claimed = await registry.claim_session_owner("owner-db-claim-2", "owner@example.com")

        assert claimed == "existing@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_updates_missing_owner_none_data(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data=None)
        fake_db = _FakeDbSession(first_results=[fake_record], update_results=[1])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            claimed = await registry.claim_session_owner("owner-db-claim-3", "owner@example.com")

        assert claimed == "owner@example.com"
        assert fake_db.updated_values

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_updates_missing_owner_invalid_json(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data="{not-json")
        fake_db = _FakeDbSession(first_results=[fake_record], update_results=[1])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            claimed = await registry.claim_session_owner("owner-db-claim-4", "owner@example.com")

        assert claimed == "owner@example.com"

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_update_conflict_retries_and_returns_none(self, registry):
        registry._backend = "database"
        fake_record = SimpleNamespace(data=None)
        fake_db = _FakeDbSession(first_results=[fake_record, fake_record, fake_record], update_results=[0, 0, 0])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            claimed = await registry.claim_session_owner("owner-db-claim-5", "owner@example.com")

        assert claimed is None

    @pytest.mark.asyncio
    async def test_claim_session_owner_database_outer_exception(self, registry, caplog):
        registry._backend = "database"
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")
        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("thread fail"))):
            claimed = await registry.claim_session_owner("owner-db-claim-6", "owner@example.com")

        assert claimed is None
        assert "Database error claiming owner for session owner-db-claim-6" in caplog.text

    @pytest.mark.asyncio
    async def test_claim_session_owner_unknown_backend_returns_none(self, registry):
        registry._backend = "custom"
        claimed = await registry.claim_session_owner("owner-unknown-backend", "owner@example.com")
        assert claimed is None

    @pytest.mark.asyncio
    async def test_session_exists_redis_backend(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.exists.return_value = 1
        registry._redis = redis_client

        assert await registry.session_exists("owner-11") is True

        redis_client.exists.return_value = 0
        assert await registry.session_exists("owner-12") is False

    @pytest.mark.asyncio
    async def test_session_exists_redis_without_client_is_unverifiable(self, registry):
        registry._backend = "redis"
        registry._redis = None
        assert await registry.session_exists("owner-13") is None

    @pytest.mark.asyncio
    async def test_session_exists_redis_exception_returns_none(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        redis_client.exists.side_effect = RuntimeError("redis exists failed")
        registry._redis = redis_client
        assert await registry.session_exists("owner-13e") is None

    @pytest.mark.asyncio
    async def test_session_exists_database_backend(self, registry):
        registry._backend = "database"
        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(return_value=True)):
            assert await registry.session_exists("owner-14") is True

        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("db error"))):
            assert await registry.session_exists("owner-14") is None

    @pytest.mark.asyncio
    async def test_session_exists_none_and_unknown_backend(self, registry):
        registry._backend = "none"
        assert await registry.session_exists("owner-15") is False

        registry._backend = "custom"
        assert await registry.session_exists("owner-15") is False

    @pytest.mark.asyncio
    async def test_session_exists_database_executes_inner_query(self, registry):
        registry._backend = "database"
        fake_db = _FakeDbSession(first_results=[SimpleNamespace(data=None)])

        def fake_get_db():
            yield fake_db

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            exists = await registry.session_exists("owner-16")

        assert exists is True
        assert fake_db.closed is True

    @pytest.mark.asyncio
    async def test_get_session_owner_redis_branches(self, registry, caplog):
        registry._backend = "redis"
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")

        registry._redis = None
        assert await registry.get_session_owner("owner-17") is None

        redis_client = AsyncMock()
        redis_client.get.side_effect = [None, b"redis@example.com", "redis2@example.com", RuntimeError("redis get error")]
        registry._redis = redis_client

        assert await registry.get_session_owner("owner-18") is None
        assert await registry.get_session_owner("owner-19") == "redis@example.com"
        # Clear cache to cover non-bytes decode path.
        registry._session_owners.pop("owner-19", None)
        assert await registry.get_session_owner("owner-19") == "redis2@example.com"
        # Clear cache to force backend call and exception path.
        registry._session_owners.pop("owner-19", None)
        assert await registry.get_session_owner("owner-19") is None
        assert "Redis error getting owner for session owner-19" in caplog.text

    @pytest.mark.asyncio
    async def test_get_session_owner_database_branches(self, registry, caplog):
        registry._backend = "database"
        caplog.set_level(logging.ERROR, logger="mcpgateway.cache.session_registry")

        # No record
        fake_db_none = _FakeDbSession(first_results=[None])
        # Invalid JSON
        fake_db_invalid = _FakeDbSession(first_results=[SimpleNamespace(data="{bad-json")])
        # Non-dict JSON
        fake_db_nondict = _FakeDbSession(first_results=[SimpleNamespace(data="[]")])
        # Valid owner
        fake_db_valid = _FakeDbSession(first_results=[SimpleNamespace(data='{"owner_email":"db@example.com"}')])
        db_sessions = [fake_db_none, fake_db_invalid, fake_db_nondict, fake_db_valid]

        def fake_get_db():
            yield db_sessions.pop(0)

        with (
            patch("mcpgateway.cache.session_registry.get_db", fake_get_db),
            patch("mcpgateway.cache.session_registry.asyncio.to_thread", _run_sync_to_thread),
        ):
            assert await registry.get_session_owner("owner-db-g1") is None
            assert await registry.get_session_owner("owner-db-g2") is None
            assert await registry.get_session_owner("owner-db-g3") is None
            assert await registry.get_session_owner("owner-db-g4") == "db@example.com"

        with patch("mcpgateway.cache.session_registry.asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("db read error"))):
            assert await registry.get_session_owner("owner-db-g5") is None
        assert "Database error getting owner for session owner-db-g5" in caplog.text

    @pytest.mark.asyncio
    async def test_remove_session_redis_deletes_owner_key(self, registry):
        registry._backend = "redis"
        redis_client = AsyncMock()
        registry._redis = redis_client
        tr = FakeSSETransport("owner-20")
        await registry.add_session("owner-20", tr)
        await registry.set_session_owner("owner-20", "owner@example.com")

        await registry.remove_session("owner-20")
        redis_client.delete.assert_any_await("mcp:session:owner-20")
        redis_client.delete.assert_any_await("mcp:session_owner:owner-20")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
