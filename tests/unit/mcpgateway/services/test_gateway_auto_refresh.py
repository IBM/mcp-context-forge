# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_auto_refresh.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for the auto-refresh tools/resources/prompts feature in GatewayService.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayConnectionError, GatewayService


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    with (
        patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit,
        patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger,
    ):
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture
def gateway_service():
    """Create a GatewayService instance with mocked dependencies."""
    with patch("mcpgateway.services.gateway_service.SessionLocal"):
        service = GatewayService()
        service.oauth_manager = AsyncMock()
        return service


def _make_mock_gateway(
    gateway_id: str = "gw-123",
    name: str = "test-gateway",
    enabled: bool = True,
    reachable: bool = True,
    oauth_config: Dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock gateway object."""
    mock = MagicMock(spec=DbGateway)
    mock.id = gateway_id
    mock.name = name
    mock.enabled = enabled
    mock.reachable = reachable
    mock.url = "http://test-server:8000"
    mock.transport = "SSE"
    mock.auth_type = "oauth" if oauth_config else None
    mock.auth_value = None
    mock.oauth_config = oauth_config
    mock.ca_certificate = None
    mock.visibility = "private"
    mock.tools = []
    mock.resources = []
    mock.prompts = []
    return mock


def _make_mock_tool(tool_id: str, name: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock tool object."""
    mock = MagicMock(spec=DbTool)
    mock.id = tool_id
    mock.original_name = name
    mock.created_via = created_via
    return mock


def _make_mock_resource(resource_id: str, uri: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock resource object."""
    mock = MagicMock(spec=DbResource)
    mock.id = resource_id
    mock.uri = uri
    mock.created_via = created_via
    return mock


def _make_mock_prompt(prompt_id: str, name: str, created_via: str = "health_check") -> MagicMock:
    """Create a mock prompt object."""
    mock = MagicMock(spec=DbPrompt)
    mock.id = prompt_id
    mock.original_name = name
    mock.created_via = created_via
    return mock


_AUTH_CODE_CONFIG: Dict[str, Any] = {
    "grant_type": "authorization_code",
    "client_id": "cid",
    "authorization_url": "https://auth.example.com/authorize",
    "token_url": "https://auth.example.com/token",
}


def _make_auth_code_gateway(gateway_id: str = "gw-123", name: str = "monday") -> MagicMock:
    """Create a mock gateway configured for the OAuth authorization_code grant."""
    mock = _make_mock_gateway(gateway_id=gateway_id, name=name, oauth_config=dict(_AUTH_CODE_CONFIG))
    mock.auth_query_params = None
    mock.client_cert = None
    mock.client_key = None
    return mock


def _patch_token_storage(token: Any, learned_aud: Any = None):
    """Patch TokenStorageService so the helper resolves a fixed stored token.

    The helper imports TokenStorageService function-locally, so the patch target is the
    definition module rather than gateway_service.
    """
    storage = MagicMock()
    storage.get_user_token = AsyncMock(return_value=token)
    storage.get_user_learned_audience = AsyncMock(return_value=(learned_aud, None))
    return patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=storage)


def _patch_claim_validation(warnings: Any = None, blocking_errors: Any = None):
    """Patch validate_oauth_token_claims with a canned TokenValidationResult stand-in."""
    validation = MagicMock(warnings=warnings or [], blocking_errors=blocking_errors or [])
    return patch("mcpgateway.services.token_validation_service.validate_oauth_token_claims", return_value=validation)


class TestAutoRefreshGatewayToolsResourcesPrompts:
    """Tests for _refresh_gateway_tools_resources_prompts method."""

    @pytest.mark.asyncio
    async def test_refresh_returns_empty_when_gateway_not_found(self, gateway_service):
        """Test that refresh returns empty result when gateway not found."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-404")

        assert result == {
            "tools_added": 0,
            "tools_removed": 0,
            "tools_updated": 0,
            "resources_added": 0,
            "resources_removed": 0,
            "resources_updated": 0,
            "prompts_added": 0,
            "prompts_removed": 0,
            "prompts_updated": 0,
            "success": True,
            "error": None,
            "validation_errors": [],
        }

    @pytest.mark.asyncio
    async def test_refresh_returns_error_when_gateway_disappears_before_update(self, gateway_service):
        """Test refresh returns a failure result if gateway vanishes before DB update phase."""
        initial_gateway = _make_mock_gateway(enabled=True, reachable=True)
        initial_gateway.oauth_config = None
        initial_gateway.auth_query_params = None
        initial_gateway.client_cert = None
        initial_gateway.client_key = None
        initial_gateway.ca_certificate = None

        fetch_session = MagicMock()
        fetch_session.execute.return_value.scalar_one_or_none.return_value = initial_gateway
        update_session = MagicMock()
        update_session.execute.return_value.scalar_one_or_none.return_value = None

        fresh_contexts = [fetch_session, update_session]

        class _FreshSessionContext:
            def __init__(self, session):
                self._session = session

            def __enter__(self):
                return self._session

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("mcpgateway.services.gateway_service.fresh_db_session", side_effect=[_FreshSessionContext(s) for s in fresh_contexts]):
            gateway_service._initialize_gateway = AsyncMock(return_value=({}, [], [], [], []))

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-404")

        assert result["success"] is False
        assert result["error"] == "Gateway gw-404 not found during refresh"

    @pytest.mark.asyncio
    async def test_refresh_skips_disabled_gateway(self, gateway_service):
        """Test that refresh skips disabled gateways."""
        mock_gateway = _make_mock_gateway(enabled=False, reachable=True)
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_skips_unreachable_gateway(self, gateway_service):
        """Test that refresh skips unreachable gateways."""
        mock_gateway = _make_mock_gateway(enabled=True, reachable=False)
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = mock_session

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0

    @pytest.mark.asyncio
    async def test_refresh_skips_auth_code_gateway_with_empty_response(self, gateway_service):
        """Test that refresh skips auth_code gateways when they return empty (incomplete auth)."""
        mock_gateway = _make_mock_gateway(oauth_config={"grant_type": "authorization_code"})
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response from auth_code gateway
            mock_init.return_value = ({}, [], [], [], [])

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["tools_added"] == 0
        assert result["tools_removed"] == 0

    @pytest.mark.asyncio
    async def test_refresh_propagates_validation_errors(self, gateway_service):
        """Validation errors from _initialize_gateway should propagate through auto-refresh."""
        mock_gateway = _make_mock_gateway()
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        validation_errors = [
            "bad_tool: Tool name exceeds MCP spec limit of 128 characters (got 129)",
        ]

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [], [], [], validation_errors)

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        assert result["validation_errors"] == validation_errors
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_refresh_processes_empty_non_auth_code_gateway(self, gateway_service):
        """Test that refresh processes empty responses from non-auth_code gateways."""
        # Gateway with client_credentials OAuth - empty response should trigger cleanup
        mock_gateway = _make_mock_gateway(oauth_config={"grant_type": "client_credentials"})
        mock_gateway.tools = [_make_mock_tool("t1", "old-tool")]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()
        # First call: get gateway metadata; Second call: get gateway with relationships
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response from client_credentials gateway
            mock_init.return_value = ({}, [], [], [], [])
            mock_cache.return_value = AsyncMock()
            mock_tool_cache.return_value = AsyncMock()

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Old tool should be marked for removal
        assert result["tools_removed"] == 1

    @pytest.mark.asyncio
    async def test_refresh_preserves_user_created_items(self, gateway_service):
        """Test that refresh only removes MCP-discovered items, not user-created ones."""
        mock_gateway = _make_mock_gateway()
        # Mix of MCP-discovered and user-created tools with various created_via values
        mock_gateway.tools = [
            _make_mock_tool("t1", "mcp-tool", created_via="health_check"),  # MCP-discovered, should be removed
            _make_mock_tool("t2", "ui-tool", created_via="ui"),  # User-created via UI, should be preserved
            _make_mock_tool("t3", "api-tool", created_via="api"),  # User-created via API, should be preserved
            _make_mock_tool("t4", "legacy-tool", created_via=None),  # Legacy entry, should be preserved
        ]
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch("mcpgateway.services.gateway_service._get_registry_cache") as mock_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as mock_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            # Empty response - should only remove MCP-discovered tools
            mock_init.return_value = ({}, [], [], [], [])
            mock_cache.return_value = AsyncMock()
            mock_tool_cache.return_value = AsyncMock()

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Only MCP-discovered tool (health_check) should be removed
        # ui, api, and None (legacy) should be preserved
        assert result["tools_removed"] == 1

    @pytest.mark.asyncio
    async def test_refresh_passes_pre_auth_headers_to_initialize_gateway(self, gateway_service):
        """Test that pre_auth_headers are passed to _initialize_gateway to avoid double OAuth."""
        mock_gateway = _make_mock_gateway()
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = mock_gateway

        pre_auth_headers = {"Authorization": "Bearer pre-fetched-token"}

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [], [], [], [])

            await gateway_service._refresh_gateway_tools_resources_prompts("gw-123", pre_auth_headers=pre_auth_headers)

        # Verify pre_auth_headers was passed
        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs.get("pre_auth_headers") == pre_auth_headers


class TestInitializeGatewayPreAuthHeaders:
    """Tests for _initialize_gateway with pre_auth_headers."""

    @pytest.mark.asyncio
    async def test_pre_auth_headers_bypass_oauth_token_fetch(self, gateway_service):
        """Test that pre_auth_headers bypass OAuth token fetch."""
        pre_auth_headers = {"Authorization": "Bearer pre-fetched-token"}

        with (patch.object(gateway_service, "connect_to_sse_server", new_callable=AsyncMock) as mock_connect,):
            mock_connect.return_value = ({}, [], [], [], [])

            await gateway_service._initialize_gateway(
                url="http://test:8000",
                auth_type="oauth",
                oauth_config={"grant_type": "client_credentials"},
                pre_auth_headers=pre_auth_headers,
            )

        # OAuth manager should NOT have been called
        gateway_service.oauth_manager.get_access_token.assert_not_called()

        # SSE server should have been called with pre_auth_headers
        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        assert call_args[0][1] == pre_auth_headers  # Second positional arg is authentication


class TestCacheInvalidationPerType:
    """Tests for per-type cache invalidation on updates."""

    @pytest.mark.asyncio
    async def test_tool_add_invalidates_tool_cache(self, gateway_service):
        """Test that tool additions invalidate the tools cache."""
        mock_gateway = _make_mock_gateway()
        mock_gateway.tools = []
        mock_gateway.resources = []
        mock_gateway.prompts = []

        mock_session = MagicMock()
        mock_session.dirty = set()  # No dirty objects initially
        mock_session.execute.return_value.scalar_one_or_none.side_effect = [mock_gateway, mock_gateway]

        mock_tool_schema = MagicMock()
        mock_tool_schema.name = "new-tool"

        new_tool = _make_mock_tool("t1", "new-tool")
        mock_cache = AsyncMock()
        mock_tool_lookup_cache = AsyncMock()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch.object(gateway_service, "_update_or_create_tools", return_value=[new_tool]),
            patch.object(gateway_service, "_update_or_create_resources", return_value=[]),
            patch.object(gateway_service, "_update_or_create_prompts", return_value=[]),
            patch("mcpgateway.services.gateway_service._get_registry_cache") as get_cache,
            patch("mcpgateway.services.gateway_service._get_tool_lookup_cache") as get_tool_cache,
        ):
            mock_fresh.return_value.__enter__.return_value = mock_session
            mock_init.return_value = ({}, [mock_tool_schema], [], [], [])
            get_cache.return_value = mock_cache
            get_tool_cache.return_value = mock_tool_lookup_cache

            result = await gateway_service._refresh_gateway_tools_resources_prompts("gw-123")

        # Tools cache should be invalidated due to addition
        assert result["tools_added"] == 1
        mock_cache.invalidate_tools.assert_called_once()
        # Resources and prompts cache should NOT be invalidated (no changes)
        mock_cache.invalidate_resources.assert_not_called()
        mock_cache.invalidate_prompts.assert_not_called()


class TestResolveAuthCodeRefreshHeaders:
    """Tests for _resolve_auth_code_refresh_headers."""

    @staticmethod
    async def _call(gateway_service: GatewayService, user_email: Any = "user@example.com"):
        """Invoke the helper with the standard authorization_code fixture arguments."""
        return await gateway_service._resolve_auth_code_refresh_headers(
            gateway_id="gw-123",
            gateway_name="monday",
            gateway_url="https://mcp.monday.com/sse",
            oauth_config=dict(_AUTH_CODE_CONFIG),
            user_email=user_email,
        )

    @pytest.mark.asyncio
    async def test_raises_when_no_user_email(self, gateway_service):
        """No authenticated caller means there is no per-user token to look up."""
        with pytest.raises(GatewayConnectionError) as exc:
            await self._call(gateway_service, user_email=None)

        assert "User authentication required for OAuth gateway monday" in str(exc.value)

    @pytest.mark.asyncio
    async def test_raises_with_authorize_url_when_no_token_stored(self, gateway_service):
        """The unauthorized case from issue #5247 must name the authorization endpoint."""
        with _patch_token_storage(None):
            with pytest.raises(GatewayConnectionError) as exc:
                await self._call(gateway_service)

        message = str(exc.value)
        assert "No OAuth tokens found for user user@example.com on gateway monday" in message
        assert "/oauth/authorize/gw-123" in message

    @pytest.mark.asyncio
    async def test_returns_bearer_header_for_valid_token(self, gateway_service):
        """A stored token that passes claim validation becomes an Authorization header."""
        with _patch_token_storage("tok-abc"), _patch_claim_validation():
            result = await self._call(gateway_service)

        assert result.headers == {"Authorization": "Bearer tok-abc"}

    @pytest.mark.asyncio
    async def test_raises_on_blocking_claim_errors(self, gateway_service):
        """A definitively mismatched claim must stop the token from being forwarded."""
        with _patch_token_storage("tok-abc"), _patch_claim_validation(blocking_errors=["audience 'x' != 'y'"]):
            with pytest.raises(GatewayConnectionError) as exc:
                await self._call(gateway_service)

        message = str(exc.value)
        assert "Refusing to forward OAuth token for gateway 'monday'" in message
        assert "audience 'x' != 'y'" in message

    @pytest.mark.asyncio
    async def test_blocking_error_does_not_leak_the_token(self, gateway_service):
        """The access token must never appear in an error surfaced to the caller."""
        with _patch_token_storage("SUPERSECRETTOKEN"), _patch_claim_validation(blocking_errors=["audience mismatch"]):
            with pytest.raises(GatewayConnectionError) as exc:
                await self._call(gateway_service)

        assert "SUPERSECRETTOKEN" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_non_blocking_warnings_are_logged_and_token_still_returned(self, gateway_service, caplog):
        """Advisory warnings are surfaced in logs but must not fail the refresh."""
        with _patch_token_storage("tok-abc"), _patch_claim_validation(warnings=["issuer claim absent"]):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.services.gateway_service"):
                result = await self._call(gateway_service)

        assert result.headers == {"Authorization": "Bearer tok-abc"}
        assert result.warnings == ["issuer claim absent"]
        assert "issuer claim absent" in caplog.text

    @pytest.mark.asyncio
    async def test_learned_audience_is_passed_to_claim_validation(self, gateway_service):
        """The caller's learned audience must reach validate_oauth_token_claims."""
        with _patch_token_storage("tok-abc", learned_aud="https://api.monday.com"):
            with patch("mcpgateway.services.token_validation_service.validate_oauth_token_claims") as mock_validate:
                mock_validate.return_value = MagicMock(warnings=[], blocking_errors=[])
                await self._call(gateway_service)

        assert mock_validate.call_args.kwargs["learned_aud"] == "https://api.monday.com"
        assert mock_validate.call_args.kwargs["gateway_url"] == "https://mcp.monday.com/sse"


class TestManualRefreshAuthCodeReporting:
    """Regression tests for issue #5247: manual refresh must not silently report success."""

    @staticmethod
    def _session_for(gateway: MagicMock) -> MagicMock:
        """Build a mock DB session whose scalar lookup returns the given gateway."""
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = gateway
        return session

    @pytest.mark.asyncio
    async def test_unauthorized_manual_refresh_reports_failure(self, gateway_service):
        """The issue #5247 repro: no stored token must yield success=False, not success=True."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage(None),
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is False
        assert "/oauth/authorize/gw-123" in result["error"]
        mock_init.assert_not_called()

    @pytest.mark.asyncio
    async def test_manual_refresh_without_user_email_reports_failure(self, gateway_service):
        """An unauthenticated manual refresh cannot resolve a per-user token."""
        gateway = _make_auth_code_gateway()

        with patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh:
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email=None, created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is False
        assert "User authentication required" in result["error"]

    @pytest.mark.asyncio
    async def test_authorized_manual_refresh_connects_with_bearer_token(self, gateway_service):
        """An authorized auth_code gateway must actually reach the MCP server."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage("tok-abc"),
            _patch_claim_validation(),
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch.object(gateway_service, "_sync_gateway_catalog") as mock_sync,
            patch.object(gateway_service, "_reconcile_gateway_catalog") as mock_reconcile,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            mock_init.return_value = ({}, [MagicMock()], [], [], [])
            mock_sync.return_value = MagicMock()
            mock_reconcile.return_value = MagicMock(
                tools_added=1, tools_removed=0, resources_added=0, resources_removed=0, prompts_added=0, prompts_removed=0
            )
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is True
        assert mock_init.call_args.kwargs["pre_auth_headers"] == {"Authorization": "Bearer tok-abc"}

    @pytest.mark.asyncio
    async def test_upstream_rejection_reports_failure(self, gateway_service):
        """A 401 from the MCP server must surface as success=False with the error text."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage("tok-abc"),
            _patch_claim_validation(),
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            mock_init.side_effect = GatewayConnectionError("Failed to initialize gateway at https://mcp.monday.com/sse: 401 Unauthorized")
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is False
        assert "401 Unauthorized" in result["error"]

    @pytest.mark.asyncio
    async def test_blocking_claim_validation_reports_failure(self, gateway_service):
        """A mismatched audience must abort the refresh before any connection."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage("tok-abc"),
            _patch_claim_validation(blocking_errors=["audience 'x' != 'y'"]),
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is False
        assert "Refusing to forward OAuth token" in result["error"]
        mock_init.assert_not_called()

    @pytest.mark.asyncio
    async def test_authorized_empty_response_preserves_existing_catalog(self, gateway_service):
        """An authorized gateway returning nothing must not trigger destructive cleanup."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage("tok-abc"),
            _patch_claim_validation(),
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch.object(gateway_service, "_reconcile_gateway_catalog") as mock_reconcile,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            mock_init.return_value = ({}, [], [], [], [])
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is True
        assert result["tools_removed"] == 0
        mock_reconcile.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_path_is_unchanged(self, gateway_service):
        """Background health checks must not attempt per-user token resolution."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_resolve_auth_code_refresh_headers", new_callable=AsyncMock) as mock_helper,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="health_check", gateway=gateway
            )

        assert result["success"] is True
        mock_helper.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_service_path_is_unchanged(self, gateway_service):
        """NotificationService-driven refresh has no caller identity and must be excluded."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_resolve_auth_code_refresh_headers", new_callable=AsyncMock) as mock_helper,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", created_via="notification_service", gateway=gateway
            )

        assert result["success"] is True
        mock_helper.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_oauth_gateway_is_unaffected(self, gateway_service):
        """Basic-auth gateways never enter the auth_code branch."""
        gateway = _make_mock_gateway()
        gateway.auth_type = "basic"
        gateway.auth_query_params = None
        gateway.client_cert = None
        gateway.client_key = None

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_resolve_auth_code_refresh_headers", new_callable=AsyncMock) as mock_helper,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
            patch.object(gateway_service, "_sync_gateway_catalog") as mock_sync,
            patch.object(gateway_service, "_reconcile_gateway_catalog") as mock_reconcile,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            mock_init.return_value = ({}, [], [], [], [])
            mock_sync.return_value = MagicMock()
            mock_reconcile.return_value = MagicMock(
                tools_added=0, tools_removed=0, resources_added=0, resources_removed=0, prompts_added=0, prompts_removed=0
            )
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert result["success"] is True
        mock_helper.assert_not_called()

    @pytest.mark.asyncio
    async def test_passthrough_authorization_wins_over_oauth_lookup(self, gateway_service):
        """An explicit caller-supplied Authorization header (e.g. renamed from
        X-Upstream-Authorization by get_passthrough_headers()) must take precedence over
        OAuth token resolution: it is a documented escape hatch for supplying the upstream
        token directly, and must not be clobbered -- nor should it require a stored OAuth
        token to exist -- just because the gateway is configured for authorization_code."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            patch.object(gateway_service, "_resolve_auth_code_refresh_headers", new_callable=AsyncMock) as mock_helper,
            patch.object(gateway_service, "_initialize_gateway", new_callable=AsyncMock) as mock_init,
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            mock_init.return_value = ({}, [], [], [], [])
            await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123",
                user_email="user@example.com",
                created_via="manual_refresh",
                gateway=gateway,
                pre_auth_headers={"Authorization": "Bearer caller-supplied-token", "X-Tenant": "acme"},
            )

        mock_helper.assert_not_called()
        assert mock_init.call_args.kwargs["pre_auth_headers"] == {"Authorization": "Bearer caller-supplied-token", "X-Tenant": "acme"}

    @pytest.mark.asyncio
    async def test_error_never_contains_the_access_token(self, gateway_service):
        """The bearer value must not reach the API response body."""
        gateway = _make_auth_code_gateway()

        with (
            patch("mcpgateway.services.gateway_service.fresh_db_session") as mock_fresh,
            _patch_token_storage("SUPERSECRETTOKEN"),
            _patch_claim_validation(blocking_errors=["audience mismatch"]),
        ):
            mock_fresh.return_value.__enter__.return_value = self._session_for(gateway)
            result = await gateway_service._refresh_gateway_tools_resources_prompts(
                "gw-123", user_email="user@example.com", created_via="manual_refresh", gateway=gateway
            )

        assert "SUPERSECRETTOKEN" not in (result["error"] or "")
