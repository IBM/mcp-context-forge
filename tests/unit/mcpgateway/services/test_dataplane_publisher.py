# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_dataplane_publisher.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for DataplanePublisherService.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _wait_forever():
    """Block until cancelled by the test cleanup."""
    await asyncio.Event().wait()


# ============================================================================
# Lifecycle Management Tests
# ============================================================================


@pytest.mark.asyncio
async def test_start_creates_background_task():
    """start() creates and schedules the background publisher task."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    assert service.task is None

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = _wait_forever

        await service.start()

        assert service.task is not None
        assert not service.task.done()

        # Cleanup
        service.task.cancel()
        try:
            await service.task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """Calling start() twice doesn't create duplicate tasks."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:
        mock_publish.side_effect = _wait_forever

        await service.start()
        first_task = service.task

        await service.start()
        second_task = service.task

        assert first_task is second_task

        # Cleanup
        service.task.cancel()
        try:
            await service.task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_shutdown_stops_running_task():
    """shutdown() gracefully stops the background task."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish:

        async def _wait_for_shutdown():
            await service._shutdown_event.wait()

        mock_publish.side_effect = _wait_for_shutdown

        await service.start()
        assert service.task is not None

        await service.shutdown()

        assert service.task is None
        assert service._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_handles_timeout():
    """shutdown() cancels task if it doesn't stop within timeout."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    with (
        patch.object(service, "publish_to_redis", new_callable=AsyncMock) as mock_publish,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock) as mock_wait_for,
    ):
        mock_publish.side_effect = _wait_forever
        mock_wait_for.side_effect = asyncio.TimeoutError

        await service.start()
        assert service.task is not None

        await service.shutdown()

        assert service.task is None


@pytest.mark.asyncio
async def test_shutdown_is_idempotent():
    """Calling shutdown() when not started is a no-op."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    assert service.task is None

    await service.shutdown()

    assert service.task is None


# ============================================================================
# Integration Test with Mock Database
# ============================================================================


@pytest.mark.asyncio
async def test_full_payload_generation_with_mock_db():
    """Integration test: fetch_payload() with mock database covering main code paths."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService
    from unittest.mock import Mock

    service = DataplanePublisherService()

    # Mock database session and queries
    mock_db = MagicMock()

    # Create properly configured mocks
    server1 = Mock()
    server1.id = "s1"
    server1.owner_email = "user1@example.com"
    server1.team_id = "team1"
    server1.visibility = "public"
    server1.enabled = True

    server2 = Mock()
    server2.id = "s2"
    server2.owner_email = "user2@example.com"
    server2.team_id = "team2"
    server2.visibility = "private"
    server2.enabled = True

    gateway1 = Mock()
    gateway1.id = "g1"
    gateway1.name = "Gateway 1"
    gateway1.url = "http://localhost:9000"
    gateway1.transport = "sse"
    gateway1.passthrough_headers = ["Authorization"]
    gateway1.owner_email = "user1@example.com"
    gateway1.team_id = "team1"
    gateway1.visibility = "public"
    gateway1.enabled = True

    prompt1 = Mock()
    prompt1.id = "p1"
    prompt1.name = "Prompt 1"
    prompt1.owner_email = "user1@example.com"
    prompt1.team_id = "team1"
    prompt1.visibility = "public"
    prompt1.enabled = True

    resource1 = Mock()
    resource1.id = "r1"
    resource1.name = "Resource 1"
    resource1.owner_email = "user1@example.com"
    resource1.team_id = "team1"
    resource1.visibility = "public"
    resource1.enabled = True

    tool1 = Mock()
    tool1.id = "t1"
    tool1.name = "public_tool"
    tool1.owner_email = "user1@example.com"
    tool1.team_id = "team1"
    tool1.visibility = "public"
    tool1.enabled = True

    tool2 = Mock()
    tool2.id = "t2"
    tool2.name = "private_tool"
    tool2.owner_email = "user1@example.com"
    tool2.team_id = "team1"
    tool2.visibility = "private"
    tool2.enabled = True

    tool3 = Mock()
    tool3.id = "t3"
    tool3.name = "team2_tool"
    tool3.owner_email = "user2@example.com"
    tool3.team_id = "team2"
    tool3.visibility = "team"
    tool3.enabled = True

    # Mock active users and user-team memberships
    mock_db.execute.return_value.all.side_effect = [
        # Active users query
        [("user1@example.com", False), ("user2@example.com", False), ("user3@example.com", False)],
        # User-team query
        [("user1@example.com", "team1"), ("user2@example.com", "team2")],
        # Server query
        [server1, server2],
        # Gateway query
        [gateway1],
        # Prompt query
        [prompt1],
        # Resource query
        [resource1],
        # Tool query
        [tool1, tool2, tool3],
        # Tool associations
        [("s1", "t1", "g1"), ("s1", "t2", "g1"), ("s1", "t3", "g1")],
        # Resource associations
        [("s1", "r1", "g1")],
        # Prompt associations
        [("s1", "p1", "g1")],
    ]

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        payload = await service.fetch_payload()

        # Verify payload structure
        assert payload is not None
        assert "user1@example.com" in payload
        assert "user2@example.com" in payload
        assert "user3@example.com" in payload

        # Verify user1 payload (has access to public server)
        user1_config = payload["user1@example.com"]
        assert "virtual_hosts" in user1_config
        assert "s1" in user1_config["virtual_hosts"]

        # Verify backend configuration
        server1 = user1_config["virtual_hosts"]["s1"]
        assert "backends" in server1
        assert "g1" in server1["backends"]

        backend = server1["backends"]["g1"]
        assert backend["name"] == "Gateway 1"
        assert backend["url"] == "http://localhost:9000"
        assert backend["transport"] == "sse"
        assert backend["passthrough_headers"] == ["Authorization"]
        assert backend["allowed_tool_names"] == ["public_tool", "private_tool"]
        assert backend["allowed_resource_names"] == ["Resource 1"]
        assert backend["allowed_prompt_names"] == ["Prompt 1"]

        # Verify user2 sees public server but not private server from user1
        user2_config = payload["user2@example.com"]
        assert "s1" in user2_config["virtual_hosts"]  # public
        assert "s2" in user2_config["virtual_hosts"]  # own private
        user2_backend = user2_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user2_backend["allowed_tool_names"] == ["public_tool", "team2_tool"]

        # Verify active users with no team membership still get public-only config.
        user3_config = payload["user3@example.com"]
        assert "s1" in user3_config["virtual_hosts"]
        assert "s2" not in user3_config["virtual_hosts"]
        user3_backend = user3_config["virtual_hosts"]["s1"]["backends"]["g1"]
        assert user3_backend["allowed_tool_names"] == ["public_tool"]


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_payload_handles_db_error():
    """fetch_payload() returns None when database query fails."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("Database error")

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        result = await service.fetch_payload()

        assert result is None


@pytest.mark.asyncio
async def test_fetch_payload_empty_database():
    """fetch_payload() handles empty database (no active users)."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_db = MagicMock()
    mock_db.execute.return_value.all.return_value = []  # No users

    with patch("mcpgateway.services.dataplane_publisher.fresh_db_session") as mock_session:
        mock_session.return_value.__enter__.return_value = mock_db

        result = await service.fetch_payload()

        assert result == {}


def test_filter_for_user_visibility_rules():
    """_filter_for_user() correctly applies visibility rules."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService
    from unittest.mock import Mock

    admin_only_row = Mock(visibility="private", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(admin_only_row, "admin@example.com", set(), is_admin=True)

    # Public: visible to all
    public_row = Mock(visibility="public", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(public_row, "anyone@example.com", set())

    # Private: only owner
    private_row = Mock(visibility="private", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(private_row, "owner@example.com", set())
    assert not DataplanePublisherService._filter_for_user(private_row, "other@example.com", {"team1"})

    # Team: team members only
    team_row = Mock(visibility="team", owner_email="owner@example.com", team_id="team1")
    assert DataplanePublisherService._filter_for_user(team_row, "member@example.com", {"team1"})
    assert not DataplanePublisherService._filter_for_user(team_row, "outsider@example.com", {"team2"})


def test_create_payload_filters_empty_backends():
    """create_payload() excludes backends with no items."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        "user@example.com": {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "gateway1": {"tools": [], "resources": [], "prompts": []},
                    },
                }
            ],
            "gateways": [{"id": "gateway1", "name": "Gateway 1", "url": "http://localhost:9000", "transport": "sse", "passthrough_headers": None}],
            "prompts": [],
            "resources": [],
        }
    }

    result = service.create_payload(data)

    # Server exists but has no backends (all empty)
    assert "server1" in result["user@example.com"]["virtual_hosts"]
    assert result["user@example.com"]["virtual_hosts"]["server1"]["backends"] == {}


def test_create_payload_handles_missing_references():
    """create_payload() handles missing gateway/resource/prompt references."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    data = {
        "user@example.com": {
            "servers": [
                {
                    "id": "server1",
                    "backend_items": {
                        "missing_gateway": {"tools": ["tool1"], "resources": ["missing_res"], "prompts": ["missing_prompt"]},
                    },
                }
            ],
            "gateways": [],  # Gateway not in list
            "prompts": [],  # Prompt not in list
            "resources": [],  # Resource not in list
        }
    }

    result = service.create_payload(data)

    # Server exists but has no backends (gateway missing)
    assert "server1" in result["user@example.com"]["virtual_hosts"]
    assert result["user@example.com"]["virtual_hosts"]["server1"]["backends"] == {}


@pytest.mark.asyncio
async def test_publish_skips_when_redis_unavailable():
    """publish_to_redis() continues gracefully when Redis is unavailable."""
    from mcpgateway.services.dataplane_publisher import REDIS_PUBLISHER_TIME, DataplanePublisherService

    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_redis.return_value = None
        mock_sleep.side_effect = _sleep_until_shutdown

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        # Should not raise, just log and continue
        mock_sleep.assert_awaited_once_with(REDIS_PUBLISHER_TIME)


@pytest.mark.asyncio
async def test_publish_skips_when_fetch_fails():
    """publish_to_redis() skips publish when fetch_payload returns None."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch.object(service, "fetch_payload", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_get_redis.return_value = mock_redis
        mock_fetch.return_value = None

        await service.start()
        await asyncio.sleep(0.01)
        await service.shutdown()

        # Pipeline should not be called when fetch returns None
        mock_redis.pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_publish_continues_when_lock_acquisition_raises():
    """publish_to_redis() keeps running when Redis lock acquisition fails."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(side_effect=Exception("redis unavailable"))
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis:
        mock_get_redis.return_value = mock_redis

        await service.start()
        await asyncio.sleep(0)
        await service.shutdown()

        mock_redis.set.assert_awaited_once()
        mock_redis.pipeline.assert_not_called()
        mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_skips_when_lock_not_acquired():
    """publish_to_redis() skips publishing when another worker holds the lock."""
    from mcpgateway.services.dataplane_publisher import REDIS_PUBLISHER_TIME, DataplanePublisherService

    service = DataplanePublisherService()
    real_sleep = asyncio.sleep

    async def _sleep_until_shutdown(_timeout):
        await service._shutdown_event.wait()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=False)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch.object(service, "fetch_payload", new_callable=AsyncMock) as mock_fetch,
    ):
        mock_get_redis.return_value = mock_redis
        mock_sleep.side_effect = _sleep_until_shutdown

        await service.start()
        await real_sleep(0)
        await service.shutdown()

        mock_redis.set.assert_awaited_once()
        mock_sleep.assert_awaited_once_with(REDIS_PUBLISHER_TIME)
        mock_fetch.assert_not_awaited()
        mock_redis.pipeline.assert_not_called()
        mock_redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_writes_payload_releases_lock_and_exits_when_shutdown_wait_returns():
    """publish_to_redis() writes msgpack payloads and releases the worker lock."""
    import msgpack

    from mcpgateway.services.dataplane_publisher import PUBLISHER_LOCK_KEY, PUBLISHER_TTL, USER_CONFIG_KEY, WORKER_ID, DataplanePublisherService

    service = DataplanePublisherService()
    payload = {"user@example.com": {"virtual_hosts": {"server1": {"backends": {}}}}}

    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle) as mock_wait_for,
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value=payload),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    pipe.set.assert_called_once()
    key_arg, value_arg = pipe.set.call_args.args
    assert msgpack.unpackb(key_arg, raw=False) == [USER_CONFIG_KEY, "user@example.com"]
    assert msgpack.unpackb(value_arg, raw=False) == payload["user@example.com"]
    assert pipe.set.call_args.kwargs == {"ex": PUBLISHER_TTL}
    pipe.execute.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()
    assert mock_redis.eval.await_args.args[1:] == (1, PUBLISHER_LOCK_KEY, WORKER_ID)
    mock_wait_for.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_releases_lock_when_pipeline_execute_fails():
    """publish_to_redis() logs pipeline failures but still releases the lock."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    pipe = MagicMock()
    pipe.execute = AsyncMock(side_effect=Exception("pipeline boom"))
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value = pipe
    mock_redis.eval = AsyncMock()

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={"user@example.com": {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    pipe.set.assert_called_once()
    pipe.execute.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_logs_lock_release_failure():
    """publish_to_redis() handles Redis errors while releasing the lock."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock(side_effect=Exception("eval boom"))

    async def _finish_cycle(awaitable, timeout):
        del timeout
        awaitable.close()

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_finish_cycle),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={"user@example.com": {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    mock_redis.eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_continues_after_cycle_timeout():
    """publish_to_redis() continues after the inter-cycle wait times out."""
    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()

    mock_redis = MagicMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.pipeline.return_value.execute = AsyncMock()
    mock_redis.eval = AsyncMock()

    async def _timeout_and_stop(awaitable, timeout):
        del timeout
        awaitable.close()
        service._shutdown_event.set()
        raise asyncio.TimeoutError

    with (
        patch("mcpgateway.services.dataplane_publisher.get_redis_client", new_callable=AsyncMock) as mock_get_redis,
        patch("mcpgateway.services.dataplane_publisher.asyncio.wait_for", new_callable=AsyncMock, side_effect=_timeout_and_stop),
        patch.object(service, "fetch_payload", new_callable=AsyncMock, return_value={"user@example.com": {"virtual_hosts": {}}}),
    ):
        mock_get_redis.return_value = mock_redis

        await service.publish_to_redis()

    mock_redis.set.assert_awaited_once()
    mock_redis.eval.assert_awaited_once()


def test_backend_item_helpers_add_items_and_skip_missing_gateway():
    """Backend item helper methods group rows by gateway and skip gateway-less rows."""
    from collections import defaultdict

    from mcpgateway.services.dataplane_publisher import DataplanePublisherService

    service = DataplanePublisherService()
    backend_items_by_server = defaultdict(dict)

    db = MagicMock()
    db.execute.return_value.all.return_value = [("server1", "tool1", None), ("server1", "tool2", "gateway1")]
    service._add_tools_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    db.execute.return_value.all.return_value = [("server1", "resource1", None), ("server1", "resource2", "gateway1")]
    service._add_resources_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    db.execute.return_value.all.return_value = [("server1", "prompt1", None), ("server1", "prompt2", "gateway1")]
    service._add_prompts_to_backends(db, backend_items_by_server)  # pylint: disable=protected-access

    assert dict(backend_items_by_server) == {
        "server1": {
            "gateway1": {
                "tools": ["tool2"],
                "resources": ["resource2"],
                "prompts": ["prompt2"],
            }
        }
    }
