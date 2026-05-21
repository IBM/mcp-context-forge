# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_redis_leadership.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for Redis leadership election and heartbeat in GatewayService.
"""

# Standard
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.gateway_service import GatewayService


def _make_service(**overrides):
    service = GatewayService()
    service._leader_key = overrides.get("leader_key", "test:leader")  # pylint: disable=protected-access
    service._instance_id = overrides.get("instance_id", "test-instance")  # pylint: disable=protected-access
    service._leader_ttl = overrides.get("leader_ttl", 15)  # pylint: disable=protected-access
    service._leader_heartbeat_interval = overrides.get("heartbeat_interval", 0)  # pylint: disable=protected-access
    service._follower_election_task = overrides.get("follower_election_task", None)  # pylint: disable=protected-access
    service._redis_client = overrides.get("redis_client", None)  # pylint: disable=protected-access
    service._health_check_task = overrides.get("health_check_task", None)  # pylint: disable=protected-access
    service._leader_heartbeat_task = overrides.get("leader_heartbeat_task", None)  # pylint: disable=protected-access
    return service


class TestRunLeaderHeartbeat:
    """Tests for _run_leader_heartbeat."""

    @pytest.mark.asyncio
    async def test_exits_when_redis_client_unavailable(self):
        """Heartbeat exits after max_failures when Redis client is None."""
        service = _make_service()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._run_leader_heartbeat()  # pylint: disable=protected-access

        # No follower election started — Redis client is unavailable for it too
        assert service._follower_election_task is None  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_exits_when_leadership_lost(self):
        """Heartbeat exits when another instance holds the leader key."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value="other-instance")
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_start_follower_election") as mock_start:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await service._run_leader_heartbeat()  # pylint: disable=protected-access

        mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_refreshes_ttl_when_leader(self):
        """Heartbeat refreshes the leader key TTL when still leader."""
        redis_mock = AsyncMock()
        # First call: still leader; second call: lost leadership (to exit loop)
        redis_mock.get = AsyncMock(side_effect=["test-instance", "other-instance"])
        redis_mock.expire = AsyncMock()
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_start_follower_election"):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await service._run_leader_heartbeat()  # pylint: disable=protected-access

        redis_mock.expire.assert_called_once_with("test:leader", 15)

    @pytest.mark.asyncio
    async def test_exits_after_max_consecutive_failures(self):
        """Heartbeat exits after 3 consecutive exceptions and starts follower election."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(side_effect=RuntimeError("connection lost"))
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_start_follower_election") as mock_start:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await service._run_leader_heartbeat()  # pylint: disable=protected-access

        mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_failure_count_on_success(self):
        """Consecutive failure counter resets on a successful heartbeat."""
        redis_mock = AsyncMock()
        # Fail twice, succeed once (resets counter), then lose leadership to exit
        redis_mock.get = AsyncMock(
            side_effect=[
                RuntimeError("transient"),
                RuntimeError("transient"),
                "test-instance",  # success - resets counter
                "other-instance",  # lost leadership - exit
            ]
        )
        redis_mock.expire = AsyncMock()
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_start_follower_election"):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await service._run_leader_heartbeat()  # pylint: disable=protected-access

        # Exited via "lost leadership", not max_failures — proves counter was reset
        redis_mock.expire.assert_called_once()


class TestStartFollowerElection:
    """Tests for _start_follower_election."""

    @pytest.mark.asyncio
    async def test_starts_task_when_none(self):
        """Creates a follower election task when none exists."""
        service = _make_service()

        with patch.object(service, "_run_follower_election", new_callable=AsyncMock) as mock_election:
            with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                mock_settings.platform_admin_email = "admin@test.com"
                service._start_follower_election()  # pylint: disable=protected-access

        assert service._follower_election_task is not None  # pylint: disable=protected-access
        mock_election.assert_called_once_with("admin@test.com")

    @pytest.mark.asyncio
    async def test_skips_when_task_running(self):
        """Does not create a new task when one is already running."""
        service = _make_service()
        existing_task = MagicMock()
        existing_task.done.return_value = False
        service._follower_election_task = existing_task  # pylint: disable=protected-access

        with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
            mock_settings.platform_admin_email = "admin@test.com"
            service._start_follower_election()  # pylint: disable=protected-access

        assert service._follower_election_task is existing_task  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_restarts_when_task_done(self):
        """Creates a new task when the existing one has completed."""
        service = _make_service()
        done_task = MagicMock()
        done_task.done.return_value = True
        service._follower_election_task = done_task  # pylint: disable=protected-access

        with patch.object(service, "_run_follower_election", new_callable=AsyncMock):
            with patch("mcpgateway.services.gateway_service.settings") as mock_settings:
                mock_settings.platform_admin_email = "admin@test.com"
                service._start_follower_election()  # pylint: disable=protected-access

        assert service._follower_election_task is not done_task  # pylint: disable=protected-access


class TestRunFollowerElection:
    """Tests for _run_follower_election."""

    @pytest.mark.asyncio
    async def test_acquires_leadership(self):
        """Follower acquires leadership and starts health check + heartbeat tasks."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        redis_mock.set.assert_called_once_with("test:leader", "test-instance", ex=15, nx=True)
        assert service._health_check_task is not None  # pylint: disable=protected-access
        assert service._leader_heartbeat_task is not None  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_retries_until_leadership_acquired(self):
        """Follower retries polling Redis until leadership is acquired."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(side_effect=[False, False, True])
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        assert redis_mock.set.call_count == 3

    @pytest.mark.asyncio
    async def test_continues_when_redis_unavailable(self):
        """Follower keeps retrying when Redis client is unavailable."""
        service = _make_service(redis_client=None, leader_ttl=15)

        call_count = 0

        async def cancel_after_iterations(_):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=cancel_after_iterations):
            with pytest.raises(asyncio.CancelledError):
                await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_handles_redis_exceptions_and_retries(self):
        """Follower continues polling after Redis exceptions."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(
            side_effect=[
                RuntimeError("connection error"),
                True,
            ]
        )
        service = _make_service(redis_client=redis_mock)

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        assert redis_mock.set.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_correct_retry_interval(self):
        """Follower polls at 1/3 of leader TTL."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        service = _make_service(redis_client=redis_mock, leader_ttl=15)

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        mock_sleep.assert_called_with(5)  # 15 // 3 = 5


class TestInitializeFollowerElection:
    """Tests for follower election task creation in initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_starts_follower_when_not_leader(self):
        """initialize() creates a follower election task when leadership is not acquired."""
        service = GatewayService()
        service._leader_key = "test:leader"  # pylint: disable=protected-access
        service._instance_id = "test-instance"  # pylint: disable=protected-access
        service._leader_ttl = 10  # pylint: disable=protected-access
        service._leader_heartbeat_interval = 5  # pylint: disable=protected-access
        service._follower_election_task = None  # pylint: disable=protected-access
        service.redis_url = "redis://localhost:6379"

        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock()
        redis_mock.set = AsyncMock(return_value=False)

        with patch.object(service._event_service, "initialize", new_callable=AsyncMock):  # pylint: disable=protected-access
            with patch("mcpgateway.services.gateway_service.REDIS_AVAILABLE", True):
                with patch("mcpgateway.services.gateway_service.get_redis_client", return_value=redis_mock):
                    await service.initialize()

        assert service._follower_election_task is not None  # pylint: disable=protected-access

        # Clean up
        service._follower_election_task.cancel()  # pylint: disable=protected-access
        try:
            await service._follower_election_task  # pylint: disable=protected-access
        except (asyncio.CancelledError, Exception):
            pass


class TestShutdownFollowerElection:
    """Tests for follower election task cleanup in shutdown()."""

    @pytest.mark.asyncio
    async def test_shutdown_cancels_follower_election_task(self):
        """shutdown() cancels the follower election task."""
        service = GatewayService()
        service._redis_client = AsyncMock()  # pylint: disable=protected-access
        service._event_service = AsyncMock()  # pylint: disable=protected-access
        service._http_client = AsyncMock()  # pylint: disable=protected-access
        service._leader_key = "test:leader"  # pylint: disable=protected-access
        service._instance_id = "test-instance"  # pylint: disable=protected-access

        async def dummy_task():
            await asyncio.sleep(100)

        service._follower_election_task = asyncio.create_task(dummy_task())  # pylint: disable=protected-access

        await service.shutdown()

        assert service._follower_election_task.cancelled()  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_shutdown_cancels_follower_before_health_check(self):
        """shutdown() cancels follower election before health check to prevent race."""
        service = GatewayService()
        service._redis_client = AsyncMock()  # pylint: disable=protected-access
        service._event_service = AsyncMock()  # pylint: disable=protected-access
        service._http_client = AsyncMock()  # pylint: disable=protected-access
        service._leader_key = "test:leader"  # pylint: disable=protected-access
        service._instance_id = "test-instance"  # pylint: disable=protected-access

        cancel_order = []

        async def mock_follower():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancel_order.append("follower")
                raise

        async def mock_health():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancel_order.append("health")
                raise

        service._follower_election_task = asyncio.create_task(mock_follower())  # pylint: disable=protected-access
        service._health_check_task = asyncio.create_task(mock_health())  # pylint: disable=protected-access
        await asyncio.sleep(0)  # Let tasks start running before shutdown

        await service.shutdown()

        # Follower must be cancelled before health check
        assert cancel_order == ["follower", "health"]


class TestFollowerElectionCancelsStale:
    """Tests for stale task cleanup when follower acquires leadership."""

    @pytest.mark.asyncio
    async def test_cancels_stale_health_check_on_reelection(self):
        """Follower election cancels an orphaned health-check loop before starting a new one."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        service = _make_service(redis_client=redis_mock)

        # Simulate a stale health-check task from a previous leadership period
        stale_task = MagicMock()
        stale_task.done.return_value = False
        service._health_check_task = stale_task  # pylint: disable=protected-access

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        # Stale task was cancelled
        stale_task.cancel.assert_called_once()
        # New task was created (overwrites the stale handle)
        assert service._health_check_task is not stale_task  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_skips_cancel_when_old_task_done(self):
        """Follower election does not cancel an already-finished task."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        service = _make_service(redis_client=redis_mock)

        done_task = MagicMock()
        done_task.done.return_value = True
        service._health_check_task = done_task  # pylint: disable=protected-access

        with patch.object(service, "_run_health_checks", new_callable=AsyncMock):
            with patch.object(service, "_run_leader_heartbeat", new_callable=AsyncMock):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._run_follower_election("test@example.com")  # pylint: disable=protected-access

        done_task.cancel.assert_not_called()
