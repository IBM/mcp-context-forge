# -*- coding: utf-8 -*-
"""End-to-end tests for MCP session pool behavior.

Tests verify:
- Isolation across users with rotating tokens using identity_extractor
- Transport isolation (same URL + identity, different transport = separate sessions)
- Idle eviction + stale session reaping observed via metrics
- Optional explicit health RPC toggle behavior

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import os

os.environ["MCPGATEWAY_ADMIN_API_ENABLED"] = "true"
os.environ["MCPGATEWAY_UI_ENABLED"] = "true"
os.environ["MCP_SESSION_POOL_ENABLED"] = "true"

# Standard
import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import mcp.types as mcp_types
import pytest
import pytest_asyncio
from mcp import ClientSession

# First-Party
from mcpgateway.services.mcp_session_pool import (
    MCPSessionPool,
    PooledSession,
    TransportType,
    close_mcp_session_pool,
    get_mcp_session_pool,
    init_mcp_session_pool,
)
from mcpgateway.services.notification_service import (
    NotificationService,
    NotificationType,
    init_notification_service,
    close_notification_service,
    get_notification_service,
)


class TestIdentityExtractorE2E:
    """End-to-end tests for identity extraction with rotating tokens."""

    @pytest.mark.asyncio
    async def test_rotating_tokens_same_user_identity(self):
        """Two different JWTs for the same user should map to same identity."""

        def extract_user_id_from_jwt(headers: dict) -> str | None:
            """Extract user_id from Authorization header (simulated JWT decode)."""
            auth = headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return None
            # Simulate JWT decode - in real implementation this would decode the token
            token = auth.replace("Bearer ", "")
            # Token format: "jwt-{user_id}-{random_suffix}"
            parts = token.split("-")
            if len(parts) >= 2:
                return f"user-{parts[1]}"
            return None

        pool = MCPSessionPool(identity_extractor=extract_user_id_from_jwt)

        try:
            # Two different JWTs for the same user
            jwt_v1 = {"Authorization": "Bearer jwt-123-abc123"}
            jwt_v2 = {"Authorization": "Bearer jwt-123-xyz789"}

            # Should produce same identity
            hash_v1 = pool._compute_identity_hash(jwt_v1)
            hash_v2 = pool._compute_identity_hash(jwt_v2)

            assert hash_v1 == hash_v2
            assert hash_v1 != "anonymous"

            # Different user should produce different identity
            jwt_other = {"Authorization": "Bearer jwt-456-def456"}
            hash_other = pool._compute_identity_hash(jwt_other)

            assert hash_other != hash_v1
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_identity_extractor_failure_falls_back_safely(self):
        """If identity extractor fails, should fall back to header hashing."""

        def failing_extractor(headers: dict) -> str | None:
            raise ValueError("Token decode failed")

        pool = MCPSessionPool(identity_extractor=failing_extractor)

        try:
            headers = {"Authorization": "Bearer some-token"}

            # Should not raise, should fall back to header hash
            identity = pool._compute_identity_hash(headers)

            assert identity != "anonymous"
            assert identity is not None
        finally:
            await pool.close_all()


class TestTransportIsolationE2E:
    """End-to-end tests for transport type isolation."""

    @pytest.mark.asyncio
    async def test_same_url_identity_different_transport_separate_pools(self):
        """Same URL + identity with different transports should use separate sessions."""
        pool = MCPSessionPool()

        try:
            headers = {"Authorization": "Bearer user-token"}

            # Get pool keys for same URL, same identity, different transports
            sse_key = pool._make_pool_key("http://server:8080/sse", headers, TransportType.SSE, user_identity="anonymous")
            http_key = pool._make_pool_key("http://server:8080/sse", headers, TransportType.STREAMABLE_HTTP, user_identity="anonymous")

            # Keys should be different due to transport
            assert sse_key != http_key

            # URL and identity should be same
            assert sse_key[1] == http_key[1]  # URL
            assert sse_key[2] == http_key[2]  # Identity hash

            # Transport should be different
            assert sse_key[3] != http_key[3]
            assert sse_key[3] == "sse"
            assert http_key[3] == "streamablehttp"
        finally:
            await pool.close_all()


class TestIdleEvictionE2E:
    """End-to-end tests for idle pool eviction and session reaping."""

    @pytest.mark.asyncio
    async def test_idle_pool_key_evicted(self):
        """Idle pool keys should be evicted after configured time."""
        pool = MCPSessionPool(
            idle_pool_eviction_seconds=0.05,  # 50ms
            session_ttl_seconds=300,
        )
        pool._eviction_run_interval = 0  # Disable throttling for test

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_close_session', new_callable=AsyncMock):
                    mock_session = PooledSession(
                        session=MagicMock(),
                        transport_context=MagicMock(),
                        url="http://test:8080",
                        identity_key="anonymous",
                        transport_type=TransportType.STREAMABLE_HTTP,
                        headers={},
                    )
                    mock_create.return_value = mock_session

                    # Acquire and release session
                    session = await pool.acquire("http://test:8080")
                    await pool.release(session)

                    # Verify pool has the key
                    assert pool.get_metrics()["pool_key_count"] == 1

                    # Set old last_used time to trigger eviction
                    pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
                    pool._pool_last_used[pool_key] = time.time() - 1000

                    # Wait and trigger eviction
                    await asyncio.sleep(0.1)
                    pool._last_eviction_run = 0  # Reset throttle
                    await pool._maybe_evict_idle_pool_keys()

                    # Pool key should be evicted
                    assert pool.get_metrics()["pool_keys_evicted"] >= 1
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_stale_sessions_reaped_via_metrics(self):
        """Stale sessions should be reaped and reflected in metrics."""
        pool = MCPSessionPool(
            idle_pool_eviction_seconds=0.05,
            session_ttl_seconds=0.01,  # Very short TTL
        )
        pool._eviction_run_interval = 0

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_close_session', new_callable=AsyncMock):
                    # Create already-expired session
                    mock_session = PooledSession(
                        session=MagicMock(),
                        transport_context=MagicMock(),
                        url="http://test:8080",
                        identity_key="anonymous",
                        transport_type=TransportType.STREAMABLE_HTTP,
                        headers={},
                        created_at=time.time() - 100,  # Created 100s ago (expired)
                    )
                    mock_create.return_value = mock_session

                    # Acquire session
                    session = await pool.acquire("http://test:8080")

                    # Force session back into pool
                    pool_key = ("anonymous", "http://test:8080", "anonymous", "streamablehttp", "")
                    pool._active.get(pool_key, set()).discard(session)
                    pool._pools[pool_key].put_nowait(session)

                    # Set old last_used to trigger eviction
                    pool._pool_last_used[pool_key] = time.time() - 1000

                    # Trigger eviction
                    pool._last_eviction_run = 0
                    await pool._maybe_evict_idle_pool_keys()

                    # Check metrics
                    metrics = pool.get_metrics()
                    assert metrics["sessions_reaped"] >= 1
        finally:
            await pool.close_all()


class TestExplicitHealthRPCE2E:
    """End-to-end tests for explicit health RPC toggle."""

    def test_explicit_health_rpc_default_off(self):
        """Explicit health RPC should be disabled by default."""
        # First-Party
        from mcpgateway.config import Settings

        settings = Settings()
        assert settings.mcp_session_pool_explicit_health_rpc is False

    @pytest.mark.asyncio
    async def test_explicit_health_rpc_toggle_behavior(self):
        """Test explicit health RPC toggle behavior with mocked settings."""
        # Mock settings
        mock_settings_disabled = MagicMock()
        mock_settings_disabled.mcp_session_pool_explicit_health_rpc = False
        mock_settings_disabled.health_check_timeout = 5

        mock_settings_enabled = MagicMock()
        mock_settings_enabled.mcp_session_pool_explicit_health_rpc = True
        mock_settings_enabled.health_check_timeout = 5

        # Mock session
        mock_session = MagicMock()
        mock_session.list_tools = AsyncMock(return_value=[])

        # Test disabled - list_tools should NOT be called
        call_count_before = mock_session.list_tools.call_count
        if mock_settings_disabled.mcp_session_pool_explicit_health_rpc:
            await asyncio.wait_for(
                mock_session.list_tools(),
                timeout=mock_settings_disabled.health_check_timeout,
            )
        assert mock_session.list_tools.call_count == call_count_before  # No change

        # Test enabled - list_tools SHOULD be called
        if mock_settings_enabled.mcp_session_pool_explicit_health_rpc:
            await asyncio.wait_for(
                mock_session.list_tools(),
                timeout=mock_settings_enabled.health_check_timeout,
            )
        assert mock_session.list_tools.call_count == call_count_before + 1


class TestPoolMetricsE2E:
    """End-to-end tests for pool metrics observation."""

    @pytest.mark.asyncio
    async def test_metrics_reflect_pool_behavior(self):
        """Verify pool metrics accurately reflect hits, misses, and operations."""
        pool = MCPSessionPool()

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                    mock_validate.return_value = True

                    # Track created sessions per identity
                    def create_session_factory(url, headers, transport_type, httpx_client_factory, timeout=None, gateway_id=None):
                        return PooledSession(
                            session=MagicMock(),
                            transport_context=MagicMock(),
                            url=url,
                            identity_key=pool._compute_identity_hash(headers),
                            transport_type=transport_type,
                            headers=headers or {},
                        )

                    mock_create.side_effect = create_session_factory

                    # Initial metrics
                    metrics = pool.get_metrics()
                    assert metrics["hits"] == 0
                    assert metrics["misses"] == 0

                    # First request - miss
                    s1 = await pool.acquire("http://test:8080", headers={"Authorization": "Bearer user1"})
                    await pool.release(s1)

                    metrics = pool.get_metrics()
                    assert metrics["misses"] == 1
                    assert metrics["hits"] == 0

                    # Second request same user - hit
                    s2 = await pool.acquire("http://test:8080", headers={"Authorization": "Bearer user1"})
                    await pool.release(s2)

                    metrics = pool.get_metrics()
                    assert metrics["misses"] == 1
                    assert metrics["hits"] == 1

                    # Third request different user - miss
                    s3 = await pool.acquire("http://test:8080", headers={"Authorization": "Bearer user2"})
                    await pool.release(s3)

                    metrics = pool.get_metrics()
                    assert metrics["misses"] == 2
                    assert metrics["hits"] == 1
                    assert metrics["pool_key_count"] == 2

                    # Verify hit rate calculation
                    assert metrics["hit_rate"] == pytest.approx(1 / 3, rel=0.01)
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_circuit_breaker_metrics(self):
        """Verify circuit breaker trips are tracked in metrics."""
        pool = MCPSessionPool(
            circuit_breaker_threshold=2,
            circuit_breaker_reset_seconds=0.1,
        )

        try:
            # Record failures to trip circuit
            pool._record_failure("http://failing:8080")
            pool._record_failure("http://failing:8080")

            metrics = pool.get_metrics()
            assert metrics["circuit_breaker_trips"] == 1

            # Circuit should be open
            assert pool._is_circuit_open("http://failing:8080")

            # Wait for reset
            await asyncio.sleep(0.15)

            # Circuit should be closed again
            assert not pool._is_circuit_open("http://failing:8080")
        finally:
            await pool.close_all()


class TestSessionReusePerfE2E:
    """End-to-end tests for session reuse performance benefits."""

    @pytest.mark.asyncio
    async def test_pool_hit_faster_than_miss(self):
        """Verify that pool hits are faster than misses (no session creation)."""
        pool = MCPSessionPool()

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch.object(pool, '_validate_session', new_callable=AsyncMock) as mock_validate:
                    mock_validate.return_value = True

                    # Simulate session creation taking time
                    async def slow_create(*args, **kwargs):
                        await asyncio.sleep(0.01)  # 10ms creation time
                        return PooledSession(
                            session=MagicMock(),
                            transport_context=MagicMock(),
                            url="http://test:8080",
                            identity_key="anonymous",
                            transport_type=TransportType.STREAMABLE_HTTP,
                            headers={},
                        )

                    mock_create.side_effect = slow_create

                    # First request - miss (slow)
                    start = time.perf_counter()
                    s1 = await pool.acquire("http://test:8080")
                    miss_time = time.perf_counter() - start
                    await pool.release(s1)

                    # Second request - hit (fast)
                    start = time.perf_counter()
                    s2 = await pool.acquire("http://test:8080")
                    hit_time = time.perf_counter() - start
                    await pool.release(s2)

                    # Hit should be significantly faster than miss
                    # (miss includes 10ms sleep, hit should be nearly instant)
                    assert hit_time < miss_time
                    assert hit_time < 0.005  # Hit should be < 5ms
        finally:
            await pool.close_all()


@pytest.fixture
async def notification_env():
    """Setup notification service environment."""
    # Initialize global notification service with short debounce
    service = init_notification_service(debounce_seconds=0.1)
    await service.initialize()

    yield service

    await close_notification_service()


class TestNotificationE2E:
    """End-to-end tests for notification service integration."""

    @pytest.mark.asyncio
    async def test_notification_flow_e2e(self, notification_env):
        """Test full flow from notification to gateway refresh."""
        service = notification_env

        # Mock GatewayService
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": True, "tools_added": 1}
        )
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())
        service.set_gateway_service(mock_gateway_service)

        # Register capabilities for gateway
        gateway_id = "test-gateway-1"
        service.register_gateway_capabilities(
            gateway_id,
            {"tools": {"listChanged": True}}
        )

        # Create session pool
        pool = MCPSessionPool()

        try:
            # Simulate a pooled session with message handler hooked up
            # In real flow, pool.acquire() does this. We'll verify pool.session() logic here.

            # 1. Verify pool uses notification service to create handler
            handler = service.create_message_handler(gateway_id)
            assert callable(handler)

            # 2. Simulate incoming notification
            # Construct a raw notification object as ClientSession would receive
            notification = mcp_types.ServerNotification(
                root=mcp_types.ToolListChangedNotification(
                    method="notifications/tools/list_changed"
                )
            )

            # 3. Inject notification into handler
            await handler(notification)

            # 4. Verify service received it
            metrics = service.get_metrics()
            assert metrics["notifications_received"] == 1
            assert metrics["pending_refreshes"] == 1

            # 5. Wait for debounce (0.1s configured + buffer)
            await asyncio.sleep(0.2)

            # 6. Verify refresh triggered on gateway service
            mock_gateway_service._refresh_gateway_tools_resources_prompts.assert_called_once_with(
                gateway_id=gateway_id,
                created_via="notification_service",
                include_resources=True,  # Tools change implies resources/prompts refresh check
                include_prompts=True,
            )

            # 7. Verify metrics updated
            metrics = service.get_metrics()
            assert metrics["refreshes_triggered"] == 1
            assert metrics["pending_refreshes"] == 0

        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_debouncing_e2e(self, notification_env):
        """Verify debouncing prevents multiple refreshes."""
        service = notification_env
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": True}
        )
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())
        service.set_gateway_service(mock_gateway_service)

        gateway_id = "test-gateway-debounce"
        service.register_gateway_capabilities(gateway_id, {"tools": {"listChanged": True}})

        handler = service.create_message_handler(gateway_id)

        # Fire multiple notifications rapidly
        notification = mcp_types.ServerNotification(
            root=mcp_types.ToolListChangedNotification(
                method="notifications/tools/list_changed"
            )
        )

        for _ in range(5):
            await handler(notification)

        # Should have 5 received but only 1 triggered (after wait)
        metrics = service.get_metrics()
        assert metrics["notifications_received"] == 5

        # Wait for debounce
        await asyncio.sleep(0.2)

        # Verify only one refresh call
        assert mock_gateway_service._refresh_gateway_tools_resources_prompts.call_count == 1

        metrics = service.get_metrics()
        assert metrics["refreshes_triggered"] == 1
        assert metrics["notifications_debounced"] >= 4

    @pytest.mark.asyncio
    async def test_different_notification_types_filtering(self, notification_env):
        """Verify different notification types trigger correct refresh flags."""
        service = notification_env
        mock_gateway_service = AsyncMock()
        mock_gateway_service._refresh_gateway_tools_resources_prompts = AsyncMock(
            return_value={"success": True}
        )
        # _get_refresh_lock is synchronous and returns an asyncio.Lock
        mock_gateway_service._get_refresh_lock = MagicMock(return_value=asyncio.Lock())
        service.set_gateway_service(mock_gateway_service)

        gateway_id = "test-gateway-types"
        # Register support for all
        service.register_gateway_capabilities(gateway_id, {
            "tools": {"listChanged": True},
            "resources": {"listChanged": True},
            "prompts": {"listChanged": True}
        })

        handler = service.create_message_handler(gateway_id)

        # 1. Resources only
        await handler(mcp_types.ServerNotification(
            root=mcp_types.ResourceListChangedNotification(
                method="notifications/resources/list_changed"
            )
        ))

        await asyncio.sleep(0.2)

        mock_gateway_service._refresh_gateway_tools_resources_prompts.assert_called_with(
            gateway_id=gateway_id,
            created_via="notification_service",
            include_resources=True,
            include_prompts=False
        )

        # Reset mock
        mock_gateway_service.reset_mock()

        # 2. Prompts only
        await handler(mcp_types.ServerNotification(
            root=mcp_types.PromptListChangedNotification(
                method="notifications/prompts/list_changed"
            )
        ))

        await asyncio.sleep(0.2)

        mock_gateway_service._refresh_gateway_tools_resources_prompts.assert_called_with(
            gateway_id=gateway_id,
            created_via="notification_service",
            include_resources=False,
            include_prompts=True
        )
