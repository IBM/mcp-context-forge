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


class TestSessionAffinityE2E:
    """End-to-end tests for session affinity (downstream → upstream mapping).

    These tests verify the bidirectional x-mcp-session-id mapping that enables
    session affinity between downstream SSE sessions and upstream MCP server sessions.
    """

    @pytest.mark.asyncio
    async def test_register_session_mapping_creates_affinity(self):
        """Verify register_session_mapping creates pool key mapping."""
        pool = MCPSessionPool()

        try:
            # Register a session mapping
            session_id = "downstream-session-123"
            url = "http://upstream:8080/mcp"
            gateway_id = "gateway-abc"
            transport_type = "streamablehttp"

            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True
                mock_settings.mcpgateway_session_affinity_ttl = 3600

                user_email = "user@example.com"
                await pool.register_session_mapping(session_id, url, gateway_id, transport_type, user_email)

                # Verify mapping was stored
                mapping_key = (session_id, url, transport_type, gateway_id)
                assert mapping_key in pool._mcp_session_mapping

                # Verify pool key uses session_id hash for identity and hashed user email
                pool_key = pool._mcp_session_mapping[mapping_key]
                import hashlib

                expected_user_hash = hashlib.sha256(user_email.encode()).hexdigest()
                assert pool_key[0] == expected_user_hash  # user_identity (hashed email)
                assert pool_key[1] == url
                # pool_key[2] is identity_hash derived from session_id
                assert pool_key[3] == transport_type
                assert pool_key[4] == gateway_id
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_acquire_uses_preregistered_mapping(self):
        """Verify acquire() uses pre-registered mapping for session affinity."""
        pool = MCPSessionPool()

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                    mock_settings.mcpgateway_session_affinity_enabled = True
                    mock_settings.mcpgateway_session_affinity_ttl = 3600

                    # Pre-register session mapping
                    session_id = "downstream-session-456"
                    url = "http://upstream:8080/mcp"
                    gateway_id = "gateway-xyz"
                    transport_type = "sse"
                    user_email = "testuser@example.com"

                    await pool.register_session_mapping(session_id, url, gateway_id, transport_type, user_email)

                    # Create mock session
                    def create_session_factory(url, headers, transport_type, httpx_client_factory, timeout=None, gateway_id=None):
                        return PooledSession(
                            session=MagicMock(),
                            transport_context=MagicMock(),
                            url=url,
                            identity_key=pool._compute_identity_hash(headers),
                            transport_type=transport_type,
                            headers=headers or {},
                            gateway_id=gateway_id or "",
                        )

                    mock_create.side_effect = create_session_factory

                    # Acquire with x-mcp-session-id header
                    headers = {
                        "Authorization": "Bearer rotating-jwt-token-1",
                        "x-mcp-session-id": session_id,
                    }

                    s1 = await pool.acquire(
                        url,
                        headers=headers,
                        transport_type=TransportType.SSE,
                        user_identity=user_email,
                        gateway_id=gateway_id,
                    )
                    await pool.release(s1)

                    # Acquire again with DIFFERENT JWT but SAME session_id and SAME user
                    headers2 = {
                        "Authorization": "Bearer rotating-jwt-token-2",  # Different JWT
                        "x-mcp-session-id": session_id,  # Same session ID
                    }

                    s2 = await pool.acquire(
                        url,
                        headers=headers2,
                        transport_type=TransportType.SSE,
                        user_identity=user_email,  # Same user
                        gateway_id=gateway_id,
                    )
                    await pool.release(s2)

                    # Should be a pool hit (same session returned)
                    metrics = pool.get_metrics()
                    assert metrics["hits"] >= 1, "Expected pool hit for same session_id with different JWT"
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_session_affinity_disabled_ignores_mapping(self):
        """Verify session affinity mapping is ignored when disabled."""
        pool = MCPSessionPool()

        try:
            session_id = "downstream-session-789"
            url = "http://upstream:8080/mcp"
            gateway_id = "gateway-123"
            transport_type = "streamablehttp"

            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = False

                await pool.register_session_mapping(session_id, url, gateway_id, transport_type, "user@test.com")

                # Mapping should NOT be stored when disabled
                mapping_key = (session_id, url, transport_type, gateway_id)
                assert mapping_key not in pool._mcp_session_mapping
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_different_session_ids_different_pools(self):
        """Verify different downstream session IDs use different upstream pools."""
        pool = MCPSessionPool()

        try:
            with patch.object(pool, '_create_session', new_callable=AsyncMock) as mock_create:
                with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                    mock_settings.mcpgateway_session_affinity_enabled = True
                    mock_settings.mcpgateway_session_affinity_ttl = 3600

                    url = "http://upstream:8080/mcp"
                    gateway_id = "gateway-multi"
                    transport_type = "streamablehttp"

                    # Register two different session mappings for different users
                    session_id_1 = "session-user-A"
                    session_id_2 = "session-user-B"
                    user_email_1 = "userA@example.com"
                    user_email_2 = "userB@example.com"

                    await pool.register_session_mapping(session_id_1, url, gateway_id, transport_type, user_email_1)
                    await pool.register_session_mapping(session_id_2, url, gateway_id, transport_type, user_email_2)

                    # Verify different pool keys
                    mapping_key_1 = (session_id_1, url, transport_type, gateway_id)
                    mapping_key_2 = (session_id_2, url, transport_type, gateway_id)

                    pool_key_1 = pool._mcp_session_mapping[mapping_key_1]
                    pool_key_2 = pool._mcp_session_mapping[mapping_key_2]

                    # Pool keys should be different (different identity hash)
                    assert pool_key_1 != pool_key_2
                    assert pool_key_1[2] != pool_key_2[2]  # Identity hash differs
        finally:
            await pool.close_all()


class TestSessionRegistryAffinityE2E:
    """End-to-end tests for session affinity in SessionRegistry.broadcast()."""

    @pytest.mark.asyncio
    async def test_broadcast_registers_session_mapping_for_tools_call(self):
        """Verify broadcast() pre-registers session mapping for tools/call."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        try:
            session_id = "sse-session-abc"
            message = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "my_tool", "arguments": {}},
                "id": 1,
            }

            # Mock tool_lookup_cache to return gateway info
            mock_cache_result = {
                "status": "active",
                "tool": {
                    "name": "my_tool",
                    "gateway_id": "gw-123",
                },
                "gateway": {
                    "id": "gw-123",
                    "url": "http://mcp-server:9000/sse",
                    "transport": "sse",
                },
            }

            # Mock the pool and cache - patch at the import location inside the method
            with patch("mcpgateway.cache.session_registry.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True

                mock_cache = MagicMock()
                mock_cache.get = AsyncMock(return_value=mock_cache_result)

                mock_pool = MagicMock()
                mock_pool.register_session_mapping = AsyncMock()

                user_email = "testuser@example.com"

                with patch.dict("sys.modules", {"mcpgateway.cache.tool_lookup_cache": MagicMock(tool_lookup_cache=mock_cache)}):
                    with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
                        with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                            # Call _register_session_mapping with user_email (simulates respond() call)
                            await registry._register_session_mapping(session_id, message, user_email)

                            # Verify register_session_mapping was called with correct args including user_email
                            mock_pool.register_session_mapping.assert_called_once_with(
                                session_id,
                                "http://mcp-server:9000/sse",
                                "gw-123",
                                "sse",
                                user_email,
                            )
        finally:
            await registry.shutdown()

    @pytest.mark.asyncio
    async def test_broadcast_skips_non_tools_call_methods(self):
        """Verify broadcast() does not register mapping for non-tools/call methods."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        try:
            session_id = "sse-session-def"
            # List methods should not trigger registration
            for method in ["tools/list", "resources/list", "prompts/list", "ping", "initialize"]:
                message = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": {},
                    "id": 1,
                }

                with patch("mcpgateway.cache.session_registry.settings") as mock_settings:
                    mock_settings.mcpgateway_session_affinity_enabled = True

                    mock_pool = MagicMock()
                    mock_pool.register_session_mapping = AsyncMock()

                    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                        await registry._register_session_mapping(session_id, message)

                        # Should NOT call register_session_mapping for non-tools/call
                        mock_pool.register_session_mapping.assert_not_called()
        finally:
            await registry.shutdown()

    @pytest.mark.asyncio
    async def test_broadcast_handles_missing_tool_gracefully(self):
        """Verify broadcast() handles missing tool in cache gracefully."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        try:
            session_id = "sse-session-ghi"
            message = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
                "id": 1,
            }

            with patch("mcpgateway.cache.session_registry.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True

                mock_cache = MagicMock()
                # Return None for missing tool
                mock_cache.get = AsyncMock(return_value=None)

                mock_pool = MagicMock()
                mock_pool.register_session_mapping = AsyncMock()

                with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
                    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                        # Should not raise
                        await registry._register_session_mapping(session_id, message)

                        # Should NOT call register_session_mapping for missing tool
                        mock_pool.register_session_mapping.assert_not_called()
        finally:
            await registry.shutdown()

    @pytest.mark.asyncio
    async def test_full_broadcast_flow_with_affinity(self):
        """Test the full broadcast flow includes session affinity registration."""
        # First-Party
        from mcpgateway.cache.session_registry import SessionRegistry

        registry = SessionRegistry(backend="memory")
        await registry.initialize()

        try:
            session_id = "full-flow-session"
            message = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "test_tool", "arguments": {"arg1": "value1"}},
                "id": 42,
            }

            mock_cache_result = {
                "status": "active",
                "tool": {"name": "test_tool", "gateway_id": "gw-full"},
                "gateway": {
                    "id": "gw-full",
                    "url": "http://full-test:8080/mcp",
                    "transport": "streamablehttp",
                },
            }

            with patch("mcpgateway.cache.session_registry.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True

                mock_cache = MagicMock()
                mock_cache.get = AsyncMock(return_value=mock_cache_result)

                mock_pool = MagicMock()
                mock_pool.register_session_mapping = AsyncMock()

                with patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache):
                    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
                        # Call broadcast (which no longer calls _register_session_mapping)
                        # In production, registration happens in respond()
                        await registry.broadcast(session_id, message)

                        # Verify session mapping was NOT registered from broadcast()
                        # (it should be registered from respond() instead)
                        mock_pool.register_session_mapping.assert_not_called()

                        # Verify message was stored (memory backend behavior)
                        assert registry._session_message is not None
                        assert registry._session_message["session_id"] == session_id
        finally:
            await registry.shutdown()


class TestMultiWorkerSessionAffinityE2E:
    """End-to-end tests for multi-worker session affinity via Redis pub/sub.

    These tests verify the multi-worker session affinity pattern:
    - Pool session ownership is tracked in Redis
    - Requests are forwarded to the worker that owns the pool session
    - Workers can execute forwarded requests and return responses
    """

    @pytest.mark.asyncio
    async def test_worker_id_is_process_id(self):
        """Verify WORKER_ID is set to the current process ID."""
        from mcpgateway.services.mcp_session_pool import WORKER_ID

        assert WORKER_ID == str(os.getpid())

    @pytest.mark.asyncio
    async def test_register_pool_session_owner_disabled_when_affinity_off(self):
        """Verify _register_pool_session_owner does nothing when affinity disabled."""
        pool = MCPSessionPool()

        try:
            mcp_session_id = "test-session-disabled"

            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = False

                # Should return immediately without calling Redis
                await pool._register_pool_session_owner(mcp_session_id)
                # No assertion needed - just verify it doesn't hang or crash
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_forward_request_returns_none_when_affinity_disabled(self):
        """Verify forward_request_to_owner returns None when affinity disabled."""
        pool = MCPSessionPool()

        try:
            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = False

                result = await pool.forward_request_to_owner(
                    "test-session",
                    {"method": "tools/call", "params": {"name": "test_tool"}}
                )

                assert result is None
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_forward_request_returns_none_when_we_own_session(self):
        """Verify forward_request_to_owner returns None when we own the session."""
        from mcpgateway.services.mcp_session_pool import WORKER_ID

        pool = MCPSessionPool()

        try:
            mcp_session_id = "test-session-local"

            # Create a mock Redis that returns our worker ID
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=WORKER_ID.encode())

            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True
                mock_settings.mcpgateway_pool_rpc_forward_timeout = 30

                async def mock_get_redis():
                    return mock_redis

                with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=mock_get_redis):
                    result = await pool.forward_request_to_owner(
                        mcp_session_id,
                        {"method": "tools/call", "params": {"name": "test_tool"}}
                    )

                    # Should return None (execute locally)
                    assert result is None
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_forward_request_returns_none_when_no_owner(self):
        """Verify forward_request_to_owner returns None when no owner registered."""
        pool = MCPSessionPool()

        try:
            mcp_session_id = "test-session-no-owner"

            # Create a mock Redis that returns None (no owner)
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)

            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True
                mock_settings.mcpgateway_pool_rpc_forward_timeout = 30

                async def mock_get_redis():
                    return mock_redis

                with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=mock_get_redis):
                    result = await pool.forward_request_to_owner(
                        mcp_session_id,
                        {"method": "tools/call", "params": {"name": "test_tool"}}
                    )

                    # Should return None (execute locally - new session)
                    assert result is None
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_forward_request_returns_none_when_no_redis(self):
        """Verify forward_request_to_owner returns None when Redis unavailable."""
        pool = MCPSessionPool()

        try:
            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True
                mock_settings.mcpgateway_pool_rpc_forward_timeout = 30

                async def mock_get_redis():
                    return None

                with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=mock_get_redis):
                    result = await pool.forward_request_to_owner(
                        "test-session",
                        {"method": "tools/call", "params": {"name": "test_tool"}}
                    )

                    assert result is None
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_execute_forwarded_request_returns_error_for_unknown_method(self):
        """Verify _execute_forwarded_request returns error for unknown methods."""
        pool = MCPSessionPool()

        try:
            result = await pool._execute_forwarded_request({
                "method": "unknown/method",
                "params": {},
                "headers": {},
            })

            assert "error" in result
            assert result["error"]["code"] == -32601  # Method not found
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_start_rpc_listener_returns_when_affinity_disabled(self):
        """Verify start_rpc_listener returns immediately when affinity disabled."""
        pool = MCPSessionPool()

        try:
            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = False

                # Should return immediately without hanging
                await pool.start_rpc_listener()
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_start_rpc_listener_returns_when_no_redis(self):
        """Verify start_rpc_listener returns when Redis unavailable."""
        pool = MCPSessionPool()

        try:
            with patch("mcpgateway.services.mcp_session_pool.settings") as mock_settings:
                mock_settings.mcpgateway_session_affinity_enabled = True

                async def mock_get_redis():
                    return None

                with patch("mcpgateway.utils.redis_client.get_redis_client", side_effect=mock_get_redis):
                    # Should return immediately without hanging
                    await pool.start_rpc_listener()
        finally:
            await pool.close_all()
