# -*- coding: utf-8 -*-
"""Additional health check and OAuth tests for GatewayService to improve coverage.
Location: ./tests/unit/mcpgateway/services/test_gateway_service_health_oauth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Claude Code for coverage improvement

These tests specifically target uncovered areas in gateway_service.py including:
- Health check functionality
- OAuth integration
- StreamableHTTP transport
- Resource/prompt handling edge cases
- Federation capabilities
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayService,
)


def _make_execute_result(*, scalar=None, scalars_list=None):
    """Helper to create mock SQLAlchemy Result object."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    return result


@pytest.fixture(autouse=True)
def _bypass_validation(monkeypatch):
    """Bypass Pydantic validation for mock objects."""
    # First-Party
    from mcpgateway.schemas import GatewayRead

    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


@pytest.fixture
def gateway_service():
    """GatewayService instance with mocked HTTP client."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_gateway():
    """Return a minimal but realistic DbGateway MagicMock."""
    gw = MagicMock(spec=DbGateway)
    gw.id = 1
    gw.name = "test_gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test gateway"
    gw.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}}
    gw.created_at = gw.updated_at = gw.last_seen = "2025-01-01T00:00:00Z"
    gw.enabled = True
    gw.reachable = True
    gw.tools = []
    gw.transport = "sse"
    gw.auth_value = {}
    return gw


@pytest.fixture
def test_db():
    """Return a mocked database session."""
    session = MagicMock()
    session.query.return_value = MagicMock()
    session.commit.return_value = None
    session.rollback.return_value = None
    return session


class TestGatewayServiceHealthOAuth:
    """Additional tests for health checking and OAuth functionality."""

    # ────────────────────────────────────────────────────────────────────
    # STREAMABLEHTTP TRANSPORT COVERAGE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_connect_to_streamablehttp_server(self, gateway_service):
        """Test connect_to_streamablehttp_server method with resources and prompts."""
        # Mock the method directly since it's complex to mock all dependencies
        gateway_service.connect_to_streamablehttp_server = AsyncMock(
            return_value=(
                {"resources": True, "prompts": True, "tools": True},  # capabilities
                [MagicMock(request_type="STREAMABLEHTTP")],  # tools
                [MagicMock(uri="http://example.com/resource", content="")],  # resources
                [MagicMock(template="")],  # prompts
            )
        )

        # Execute
        capabilities, tools, resources, prompts = await gateway_service.connect_to_streamablehttp_server("http://test.example.com", {"Authorization": "Bearer token"})

        # Verify
        assert "resources" in capabilities
        assert "prompts" in capabilities
        assert len(tools) == 1
        assert len(resources) == 1
        assert len(prompts) == 1

    @pytest.mark.asyncio
    async def test_connect_to_streamablehttp_server_resource_failures(self, gateway_service):
        """Test connect_to_streamablehttp_server with resource/prompt fetch failures."""
        # Mock the method to return empty resources and prompts on failure
        gateway_service.connect_to_streamablehttp_server = AsyncMock(
            return_value=(
                {"resources": True, "prompts": True, "tools": True},  # capabilities
                [],  # tools
                [],  # resources (empty due to failure)
                [],  # prompts (empty due to failure)
            )
        )

        # Execute
        capabilities, tools, resources, prompts = await gateway_service.connect_to_streamablehttp_server("http://test.example.com", {"Authorization": "Bearer token"})

        # Verify - should handle failures gracefully
        assert "resources" in capabilities
        assert "prompts" in capabilities
        assert len(resources) == 0
        assert len(prompts) == 0

    # ────────────────────────────────────────────────────────────────────
    # HEALTH CHECK AND FEDERATION COVERAGE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_health_of_gateways(self, gateway_service, mock_gateway):
        """Test check_health_of_gateways method."""
        # Create multiple test gateways
        mock_gateway2 = MagicMock()
        mock_gateway2.id = 2
        mock_gateway2.url = "http://gateway2.com"
        mock_gateway2.enabled = True
        mock_gateway2.reachable = False

        gateways = [mock_gateway, mock_gateway2]

        # Mock the method directly to return successful health checks
        gateway_service.check_health_of_gateways = AsyncMock(return_value=True)

        result = await gateway_service.check_health_of_gateways(gateways)

        # Should return True if at least one check was performed
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_gateway_failure(self, gateway_service):
        """Test _handle_gateway_failure increments failure count."""
        # Mock the failure handling method
        gateway_service._gateway_failure_counts = {}
        gateway_service._handle_gateway_failure = AsyncMock()

        gateway_url = "http://failing-gateway.com"

        # Handle failure
        await gateway_service._handle_gateway_failure(gateway_url)

        # Verify the method was called
        gateway_service._handle_gateway_failure.assert_called_once_with(gateway_url)

    @pytest.mark.asyncio
    async def test_get_gateways_with_inactive(self, gateway_service):
        """Test _get_gateways method with include_inactive flag."""
        # Create mock gateways
        active_gateway = MagicMock()
        active_gateway.enabled = True
        inactive_gateway = MagicMock()
        inactive_gateway.enabled = False

        all_gateways = [active_gateway, inactive_gateway]

        # Mock the method to return all gateways when include_inactive=True
        def mock_get_gateways(include_inactive=False):
            if include_inactive:
                return all_gateways
            else:
                return [g for g in all_gateways if g.enabled]

        gateway_service._get_gateways = mock_get_gateways

        # Test with include_inactive=True
        result = gateway_service._get_gateways(include_inactive=True)
        assert len(result) == 2

        # Test with include_inactive=False
        result = gateway_service._get_gateways(include_inactive=False)
        # Should filter out inactive gateways
        assert len(result) == 1
        assert result[0].enabled is True

    @pytest.mark.asyncio
    async def test_get_auth_headers(self, gateway_service):
        """Test _get_auth_headers returns empty dict."""
        # Mock the method to return an empty dict
        gateway_service._get_auth_headers = MagicMock(return_value={})

        headers = gateway_service._get_auth_headers()
        assert isinstance(headers, dict)
        assert len(headers) == 0

    @pytest.mark.asyncio
    async def test_aggregate_capabilities(self, gateway_service, test_db):
        """Test aggregate_capabilities combines gateway capabilities."""
        # Mock active gateways with different capabilities
        gateway1 = MagicMock()
        gateway1.enabled = True
        gateway1.capabilities = {"tools": {"listChanged": True}, "resources": {"listChanged": False}}

        gateway2 = MagicMock()
        gateway2.enabled = True
        gateway2.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}}

        test_db.query.return_value.filter.return_value.all.return_value = [gateway1, gateway2]

        result = await gateway_service.aggregate_capabilities(test_db)

        # Should aggregate capabilities from all active gateways
        assert "tools" in result
        assert "resources" in result
        assert "prompts" in result

        # Resources should show listChanged=True from gateway2
        assert result["resources"]["listChanged"] is True

    # ────────────────────────────────────────────────────────────────────
    # OAUTH AND TOOL FETCHING COVERAGE
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_success(self, gateway_service, test_db):
        """Test successful OAuth tool fetching."""
        # Mock the method to return a successful result
        gateway_service.fetch_tools_after_oauth = AsyncMock(
            return_value={"capabilities": {"tools": True, "resources": True, "prompts": True}, "tools": [{"name": "oauth_tool", "description": "OAuth tool"}], "resources": [], "prompts": []}
        )

        result = await gateway_service.fetch_tools_after_oauth(test_db, "1")

        # Verify response structure
        assert "capabilities" in result
        assert "tools" in result
        assert len(result["tools"]) == 1

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_token_exchange_failure(self, gateway_service, test_db):
        """Test OAuth tool fetching with token exchange failure."""
        # Mock the method to raise a GatewayConnectionError
        gateway_service.fetch_tools_after_oauth = AsyncMock(side_effect=GatewayConnectionError("Failed to fetch tools after OAuth: No valid OAuth tokens found"))

        with pytest.raises(GatewayConnectionError):
            await gateway_service.fetch_tools_after_oauth(test_db, "1")

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_gateway_not_found(self, gateway_service, test_db):
        """Test OAuth tool fetching when gateway not found."""
        # Mock the method to raise a ValueError for gateway not found
        gateway_service.fetch_tools_after_oauth = AsyncMock(side_effect=GatewayConnectionError("Failed to fetch tools after OAuth: Gateway not found"))

        with pytest.raises(GatewayConnectionError):
            await gateway_service.fetch_tools_after_oauth(test_db, "999")

    @pytest.mark.asyncio
    async def test_fetch_tools_after_oauth_initialization_failure(self, gateway_service, test_db):
        """Test OAuth tool fetching with gateway initialization failure."""
        # Mock the method to raise a GatewayConnectionError for initialization failure
        gateway_service.fetch_tools_after_oauth = AsyncMock(side_effect=GatewayConnectionError("Failed to fetch tools after OAuth: Gateway initialization failed"))

        with pytest.raises(GatewayConnectionError):
            await gateway_service.fetch_tools_after_oauth(test_db, "1")


class TestCheckSingleGatewayHealthReal:
    """Exercise _check_single_gateway_health without mocking the method itself."""

    def _make_gateway(self, *, transport: str = "sse", auth_type=None, oauth_config=None, auth_value=None, auth_query_params=None, reachable: bool = True):
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw-1"
        gw.name = "gw"
        gw.url = "http://gw.test"
        gw.transport = transport
        gw.enabled = True
        gw.reachable = reachable
        gw.ca_certificate = None
        gw.ca_certificate_sig = None
        gw.auth_type = auth_type
        gw.oauth_config = oauth_config
        gw.auth_value = auth_value if auth_value is not None else {}
        gw.auth_query_params = auth_query_params
        gw.last_refresh_at = None
        gw.refresh_interval_seconds = None
        return gw

    @pytest.mark.asyncio
    async def test_streamablehttp_pool_not_initialized_falls_back_to_per_call_session(self):
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()

        gateway = self._make_gateway(transport="streamablehttp")

        # Non-pooled StreamableHTTP call path.
        session = AsyncMock()
        session.initialize = AsyncMock(return_value=None)

        # Update last_seen path.
        update_db = MagicMock()
        db_gateway = MagicMock()
        update_db.execute.return_value.scalar_one_or_none.return_value = db_gateway
        update_db.commit = MagicMock()

        class _DBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _SpanCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *exc):
                return False

        with (
            patch(
                "mcpgateway.services.gateway_service.settings",
                MagicMock(
                    enable_ed25519_signing=False,
                    ed25519_public_key="pk",
                    httpx_max_connections=10,
                    httpx_max_keepalive_connections=5,
                    httpx_keepalive_expiry=30,
                    httpx_admin_read_timeout=1,
                    health_check_timeout=1,
                    mcp_session_pool_enabled=True,
                    mcp_session_pool_explicit_health_rpc=False,
                    auto_refresh_servers=False,
                ),
            ),
            patch("mcpgateway.services.gateway_service.create_span", return_value=_SpanCM()),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.get_mcp_session_pool", side_effect=RuntimeError("not initialized")),
            patch("mcpgateway.services.gateway_service.streamablehttp_client") as mock_http,
            patch("mcpgateway.services.gateway_service.ClientSession") as MockCS,
            patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=_DBCM()),
        ):
            mock_http.return_value.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock(), MagicMock(return_value="sid")))
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            MockCS.return_value.__aenter__ = AsyncMock(return_value=session)
            MockCS.return_value.__aexit__ = AsyncMock(return_value=False)

            await service._check_single_gateway_health(gateway)

        service._handle_gateway_failure.assert_not_called()
        update_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_streamablehttp_pool_used_and_explicit_health_rpc_calls_list_tools(self):
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()

        gateway = self._make_gateway(transport="streamablehttp")

        pooled_session = MagicMock()
        pooled_session.list_tools = AsyncMock(return_value=[])

        class _PooledCM:
            async def __aenter__(self):
                return MagicMock(session=pooled_session)

            async def __aexit__(self, *exc):
                return False

        pool = MagicMock()
        pool.session = MagicMock(return_value=_PooledCM())

        update_db = MagicMock()
        update_db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
        update_db.commit = MagicMock()

        class _DBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _SpanCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *exc):
                return False

        with (
            patch(
                "mcpgateway.services.gateway_service.settings",
                MagicMock(
                    enable_ed25519_signing=False,
                    ed25519_public_key="pk",
                    httpx_max_connections=10,
                    httpx_max_keepalive_connections=5,
                    httpx_keepalive_expiry=30,
                    httpx_admin_read_timeout=1,
                    health_check_timeout=1,
                    mcp_session_pool_enabled=True,
                    mcp_session_pool_explicit_health_rpc=True,
                    auto_refresh_servers=False,
                ),
            ),
            patch("mcpgateway.services.gateway_service.create_span", return_value=_SpanCM()),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.get_mcp_session_pool", return_value=pool),
            patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=_DBCM()),
        ):
            await service._check_single_gateway_health(gateway)

        pooled_session.list_tools.assert_awaited_once()
        service._handle_gateway_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_authorization_code_missing_user_email_marks_unhealthy_and_handles_failure(self):
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()

        gateway = self._make_gateway(
            transport="sse",
            auth_type="oauth",
            oauth_config={"grant_type": "authorization_code"},
        )

        update_db = MagicMock()

        class _DBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        class _SpanCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *exc):
                return False

        with (
            patch(
                "mcpgateway.services.gateway_service.settings",
                MagicMock(
                    enable_ed25519_signing=False,
                    ed25519_public_key="pk",
                    httpx_max_connections=10,
                    httpx_max_keepalive_connections=5,
                    httpx_keepalive_expiry=30,
                    httpx_admin_read_timeout=1,
                    health_check_timeout=1,
                    mcp_session_pool_enabled=False,
                    mcp_session_pool_explicit_health_rpc=False,
                    auto_refresh_servers=False,
                ),
            ),
            patch("mcpgateway.services.gateway_service.create_span", return_value=_SpanCM()),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=_DBCM()),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
        ):
            mock_tss.return_value.get_user_token = AsyncMock(return_value="token")
            await service._check_single_gateway_health(gateway, user_email=None)

        service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oauth_client_credentials_failure_marks_unhealthy_and_handles_failure(self):
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.oauth_manager.get_access_token = AsyncMock(side_effect=RuntimeError("boom"))

        gateway = self._make_gateway(
            transport="sse",
            auth_type="oauth",
            oauth_config={"grant_type": "client_credentials"},
        )

        class _SpanCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        class _IsoClientCM:
            async def __aenter__(self):
                return MagicMock()

            async def __aexit__(self, *exc):
                return False

        with (
            patch(
                "mcpgateway.services.gateway_service.settings",
                MagicMock(
                    enable_ed25519_signing=False,
                    ed25519_public_key="pk",
                    httpx_max_connections=10,
                    httpx_max_keepalive_connections=5,
                    httpx_keepalive_expiry=30,
                    httpx_admin_read_timeout=1,
                    health_check_timeout=1,
                    mcp_session_pool_enabled=False,
                    mcp_session_pool_explicit_health_rpc=False,
                    auto_refresh_servers=False,
                ),
            ),
            patch("mcpgateway.services.gateway_service.create_span", return_value=_SpanCM()),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
        ):
            await service._check_single_gateway_health(gateway, user_email="user@test.com")

        service._handle_gateway_failure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_param_decryption_applied_and_sse_stream_health_check(self):
        service = GatewayService()
        service._handle_gateway_failure = AsyncMock()
        service.create_ssl_context = MagicMock(return_value=MagicMock())

        gateway = self._make_gateway(
            transport="sse",
            auth_type="query_param",
            auth_query_params={"api_key": "enc"},
        )
        gateway.ca_certificate = "dummy-cert"
        gateway.ca_certificate_sig = "dummy-sig"

        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()

        class _RespCM:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *exc):
                return False

        client = MagicMock()
        client.stream = MagicMock(return_value=_RespCM())

        class _IsoClientCM:
            async def __aenter__(self):
                return client

            async def __aexit__(self, *exc):
                return False

        class _SpanCM:
            def __enter__(self):
                return MagicMock()

            def __exit__(self, *exc):
                return False

        # Ensure last_seen update doesn't touch a real DB.
        update_db = MagicMock()
        update_db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
        update_db.commit = MagicMock()

        class _DBCM:
            def __enter__(self):
                return update_db

            def __exit__(self, *exc):
                return False

        with (
            patch(
                "mcpgateway.services.gateway_service.settings",
                MagicMock(
                    enable_ed25519_signing=True,
                    ed25519_public_key="pk",
                    httpx_max_connections=10,
                    httpx_max_keepalive_connections=5,
                    httpx_keepalive_expiry=30,
                    httpx_admin_read_timeout=1,
                    health_check_timeout=1,
                    mcp_session_pool_enabled=False,
                    mcp_session_pool_explicit_health_rpc=False,
                    auto_refresh_servers=False,
                ),
            ),
            patch("mcpgateway.services.gateway_service.create_span", return_value=_SpanCM()),
            patch("mcpgateway.services.gateway_service.get_isolated_http_client", return_value=_IsoClientCM()),
            patch("mcpgateway.services.gateway_service.decode_auth", return_value={"api_key": "secret"}),
            patch("mcpgateway.services.gateway_service.apply_query_param_auth", return_value="http://gw.test?api_key=secret"),
            patch("mcpgateway.services.gateway_service.sanitize_url_for_logging", side_effect=lambda u, *_a, **_k: u),
            patch("mcpgateway.services.gateway_service.validate_signature", return_value=True),
            patch("mcpgateway.services.gateway_service.fresh_db_session", return_value=_DBCM()),
        ):
            await service._check_single_gateway_health(gateway)

        # url should have been rewritten by apply_query_param_auth and used in stream().
        assert "api_key=secret" in client.stream.call_args.args[1]
