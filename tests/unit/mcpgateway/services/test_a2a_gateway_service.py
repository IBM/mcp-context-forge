# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_gateway_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tests for A2A Gateway Service functionality.
"""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.services.a2a_service import check_agent_visibility_access
from mcpgateway.services.a2a_gateway_service import (
    A2A_COMPATIBLE_AGENT_TYPES,
    A2A_JSONRPC_METHODS,
    A2A_STREAMING_METHODS,
    A2AGatewayAgentDisabledError,
    A2AGatewayAgentIncompatibleError,
    A2AGatewayAgentNotFoundError,
    A2AGatewayError,
    A2AGatewayService,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    make_jsonrpc_error,
    make_jsonrpc_response,
)


class TestMakeJsonrpcError:
    """Tests for make_jsonrpc_error helper."""

    def test_basic_error(self):
        result = make_jsonrpc_error(-32600, "Invalid Request")
        assert result == {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "Invalid Request"},
            "id": None,
        }

    def test_error_with_request_id(self):
        result = make_jsonrpc_error(-32600, "Invalid Request", request_id=42)
        assert result["id"] == 42

    def test_error_with_data(self):
        result = make_jsonrpc_error(-32600, "Bad", data={"detail": "missing field"})
        assert result["error"]["data"] == {"detail": "missing field"}


class TestMakeJsonrpcResponse:
    """Tests for make_jsonrpc_response helper."""

    def test_basic_response(self):
        result = make_jsonrpc_response({"status": "ok"}, request_id=1)
        assert result == {
            "jsonrpc": "2.0",
            "result": {"status": "ok"},
            "id": 1,
        }

    def test_null_result(self):
        result = make_jsonrpc_response(None, request_id="abc")
        assert result["result"] is None
        assert result["id"] == "abc"


class TestA2AGatewayService:
    """Test suite for A2A Gateway Service."""

    @pytest.fixture
    def service(self):
        return A2AGatewayService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=Session)

    # --- validate_jsonrpc_request ---

    def test_validate_valid_request(self, service):
        body = {"jsonrpc": "2.0", "method": "message/send", "params": {}, "id": 1}
        assert service.validate_jsonrpc_request(body) is None

    def test_validate_not_a_dict(self, service):
        result = service.validate_jsonrpc_request("not a dict")
        assert result["error"]["code"] == JSONRPC_INVALID_REQUEST

    def test_validate_missing_jsonrpc(self, service):
        body = {"method": "message/send", "id": 1}
        result = service.validate_jsonrpc_request(body)
        assert result["error"]["code"] == JSONRPC_INVALID_REQUEST

    def test_validate_wrong_jsonrpc_version(self, service):
        body = {"jsonrpc": "1.0", "method": "message/send", "id": 1}
        result = service.validate_jsonrpc_request(body)
        assert result["error"]["code"] == JSONRPC_INVALID_REQUEST

    def test_validate_missing_method(self, service):
        body = {"jsonrpc": "2.0", "id": 1}
        result = service.validate_jsonrpc_request(body)
        assert result["error"]["code"] == JSONRPC_INVALID_REQUEST

    def test_validate_unknown_method(self, service):
        body = {"jsonrpc": "2.0", "method": "unknown/method", "id": 1}
        result = service.validate_jsonrpc_request(body)
        assert result["error"]["code"] == JSONRPC_METHOD_NOT_FOUND

    def test_validate_all_supported_methods(self, service):
        """All A2A JSON-RPC methods should pass validation."""
        for method in A2A_JSONRPC_METHODS:
            body = {"jsonrpc": "2.0", "method": method, "id": 1}
            assert service.validate_jsonrpc_request(body) is None, f"Method {method} failed validation"

    # --- is_streaming_method ---

    def test_streaming_methods(self, service):
        assert service.is_streaming_method("message/stream") is True
        assert service.is_streaming_method("tasks/resubscribe") is True

    def test_non_streaming_methods(self, service):
        assert service.is_streaming_method("message/send") is False
        assert service.is_streaming_method("tasks/get") is False
        assert service.is_streaming_method("tasks/cancel") is False

    # --- check_agent_visibility_access (shared function) ---

    def test_access_public_agent(self, service):
        agent = MagicMock(visibility="public")
        assert check_agent_visibility_access(agent, None, []) is True

    def test_access_admin_bypass(self, service):
        agent = MagicMock(visibility="private", owner_email="admin@test.com")
        # token_teams=None and user_email=None → admin bypass
        assert check_agent_visibility_access(agent, None, None) is True

    def test_access_team_agent_with_matching_team(self, service):
        agent = MagicMock(visibility="team", team_id="team-alpha")
        assert check_agent_visibility_access(agent, "user@test.com", ["team-alpha"]) is True

    def test_access_team_agent_with_wrong_team(self, service):
        agent = MagicMock(visibility="team", team_id="team-alpha")
        assert check_agent_visibility_access(agent, "user@test.com", ["team-beta"]) is False

    def test_access_private_agent_owner_match(self, service):
        agent = MagicMock(visibility="private", owner_email="owner@test.com")
        assert check_agent_visibility_access(agent, "owner@test.com", ["team-1"]) is True

    def test_access_private_agent_non_owner(self, service):
        agent = MagicMock(visibility="private", owner_email="owner@test.com")
        assert check_agent_visibility_access(agent, "other@test.com", ["team-1"]) is False

    def test_access_public_only_token_denies_non_public(self, service):
        agent = MagicMock(visibility="team", team_id="team-1")
        # Empty token_teams = public-only token
        assert check_agent_visibility_access(agent, "user@test.com", []) is False

    def test_access_no_user_email_denies_non_public(self, service):
        agent = MagicMock(visibility="team", team_id="team-1")
        assert check_agent_visibility_access(agent, None, ["team-1"]) is False

    # --- resolve_agent ---

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_not_found(self, mock_get_for_update, service, mock_db):
        mock_get_for_update.return_value = None
        with pytest.raises(A2AGatewayAgentNotFoundError):
            service.resolve_agent(mock_db, "nonexistent-id", "user@test.com", [])

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_disabled(self, mock_get_for_update, service, mock_db):
        agent = MagicMock(visibility="public", enabled=False, slug="test-agent", id="agent-123")
        mock_get_for_update.return_value = agent

        with pytest.raises(A2AGatewayAgentDisabledError):
            service.resolve_agent(mock_db, "agent-123", "user@test.com", [])

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_access_denied_returns_not_found(self, mock_get_for_update, service, mock_db):
        """Access denied should raise NotFound (not 403) to avoid leaking existence."""
        agent = MagicMock(visibility="private", owner_email="other@test.com", enabled=True, id="agent-456")
        mock_get_for_update.return_value = agent

        with pytest.raises(A2AGatewayAgentNotFoundError):
            service.resolve_agent(mock_db, "agent-456", "attacker@test.com", ["some-team"])

    @patch("mcpgateway.services.a2a_service.decode_auth")
    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_success(self, mock_get_for_update, mock_decode_auth, service, mock_db):
        agent = MagicMock(
            visibility="public",
            enabled=True,
            slug="echo",
            id="agent-789",
            endpoint_url="https://echo.example.com/a2a",
            auth_type="bearer",
            auth_value="encrypted-token",
            auth_query_params=None,
            agent_type="generic",
        )
        mock_get_for_update.return_value = agent
        mock_decode_auth.return_value = {"Authorization": "Bearer test-token"}

        resolved_agent, auth_headers, auth_qp = service.resolve_agent(mock_db, "agent-789", "user@test.com", [])

        assert resolved_agent == agent
        assert auth_headers == {"Authorization": "Bearer test-token"}
        assert auth_qp is None  # bearer auth doesn't use query params
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    # --- resolve_agent: agent type compatibility ---

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_openai_type_rejected(self, mock_get_for_update, service, mock_db):
        """OpenAI agent type should be rejected by the A2A gateway."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-openai",
            agent_type="openai", endpoint_url="https://api.openai.com/v1/chat/completions",
            name="OpenAI Bot",
        )
        mock_get_for_update.return_value = agent

        with pytest.raises(A2AGatewayAgentIncompatibleError, match="not compatible"):
            service.resolve_agent(mock_db, "agent-openai", "user@test.com", [])

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_anthropic_type_rejected(self, mock_get_for_update, service, mock_db):
        """Anthropic agent type should be rejected by the A2A gateway."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-anthropic",
            agent_type="anthropic", endpoint_url="https://api.anthropic.com/v1/messages",
            name="Claude Bot",
        )
        mock_get_for_update.return_value = agent

        with pytest.raises(A2AGatewayAgentIncompatibleError, match="not compatible"):
            service.resolve_agent(mock_db, "agent-anthropic", "user@test.com", [])

    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_custom_type_rejected(self, mock_get_for_update, service, mock_db):
        """Custom agent type should be rejected by the A2A gateway."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-custom",
            agent_type="custom", endpoint_url="https://my-api.example.com/api",
            name="Custom API",
        )
        mock_get_for_update.return_value = agent

        with pytest.raises(A2AGatewayAgentIncompatibleError, match="not compatible"):
            service.resolve_agent(mock_db, "agent-custom", "user@test.com", [])

    @patch("mcpgateway.services.a2a_service.decode_auth")
    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_jsonrpc_type_accepted(self, mock_get_for_update, mock_decode_auth, service, mock_db):
        """jsonrpc agent type should be accepted by the A2A gateway."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-jsonrpc",
            agent_type="jsonrpc", endpoint_url="https://a2a-agent.example.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            name="A2A Agent",
        )
        mock_get_for_update.return_value = agent
        mock_decode_auth.return_value = {}

        resolved_agent, _, _ = service.resolve_agent(mock_db, "agent-jsonrpc", "user@test.com", [])
        assert resolved_agent == agent

    @patch("mcpgateway.services.a2a_service.decode_auth")
    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_generic_type_accepted(self, mock_get_for_update, mock_decode_auth, service, mock_db):
        """generic agent type should be accepted by the A2A gateway."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-generic",
            agent_type="generic", endpoint_url="https://a2a-agent.example.com/",
            auth_type=None, auth_value=None, auth_query_params=None,
            name="Generic Agent",
        )
        mock_get_for_update.return_value = agent
        mock_decode_auth.return_value = {}

        resolved_agent, _, _ = service.resolve_agent(mock_db, "agent-generic", "user@test.com", [])
        assert resolved_agent == agent

    @patch("mcpgateway.services.a2a_service.decode_auth")
    @patch("mcpgateway.services.a2a_gateway_service.get_for_update")
    def test_resolve_agent_custom_type_with_trailing_slash_accepted(self, mock_get_for_update, mock_decode_auth, service, mock_db):
        """Custom agent type with URL ending in '/' should be accepted (URL-based JSON-RPC hint)."""
        agent = MagicMock(
            visibility="public", enabled=True, id="agent-custom-slash",
            agent_type="custom", endpoint_url="https://a2a-agent.example.com/a2a/",
            auth_type=None, auth_value=None, auth_query_params=None,
            name="Custom But JSON-RPC",
        )
        mock_get_for_update.return_value = agent
        mock_decode_auth.return_value = {}

        resolved_agent, _, _ = service.resolve_agent(mock_db, "agent-custom-slash", "user@test.com", [])
        assert resolved_agent == agent

    def test_compatible_agent_types_constant(self, service):
        """Verify A2A_COMPATIBLE_AGENT_TYPES includes the expected types."""
        assert "generic" in A2A_COMPATIBLE_AGENT_TYPES
        assert "jsonrpc" in A2A_COMPATIBLE_AGENT_TYPES
        assert "openai" not in A2A_COMPATIBLE_AGENT_TYPES
        assert "anthropic" not in A2A_COMPATIBLE_AGENT_TYPES
        assert "custom" not in A2A_COMPATIBLE_AGENT_TYPES

    # --- generate_agent_card ---

    def test_generate_agent_card_basic(self, service):
        agent = SimpleNamespace(
            name="Echo Agent",
            description="Echoes input",
            id="agent-abc",
            slug="echo",
            protocol_version="1.0",
            capabilities={"streaming": True, "pushNotifications": False},
            config={},
            tags=["echo", "test"],
        )

        card = service.generate_agent_card(agent, "https://gateway.example.com")

        assert card["name"] == "Echo Agent"
        assert "agent-abc" in card["url"]
        assert card["capabilities"]["streaming"] is True
        assert card["capabilities"]["pushNotifications"] is False
        assert card["protocolVersion"] == "1.0"

    def test_generate_agent_card_tags_as_skills(self, service):
        agent = SimpleNamespace(
            name="Test",
            description="",
            id="agent-def",
            slug="test",
            protocol_version="1.0",
            capabilities={},
            config={},
            tags=["coding", "math"],
        )

        card = service.generate_agent_card(agent, "https://gw.com")
        assert len(card["skills"]) == 2
        assert card["skills"][0]["id"] == "coding"

    def test_generate_agent_card_with_provider(self, service):
        agent = SimpleNamespace(
            name="Test",
            description="",
            id="agent-ghi",
            slug="test",
            protocol_version="1.0",
            capabilities={},
            config={"provider": {"organization": "TestOrg"}},
            tags=None,
        )

        card = service.generate_agent_card(agent, "https://gw.com")
        assert card["provider"] == {"organization": "TestOrg"}

    def test_generate_agent_card_uses_configurable_prefix(self, service):
        """Agent card URL should use the configurable route prefix."""
        agent = SimpleNamespace(
            name="Prefix Test",
            description="",
            id="agent-prefix-1",
            slug="prefix-test",
            protocol_version="1.0",
            capabilities={},
            config={},
            tags=None,
        )

        from mcpgateway.config import settings

        prefix = settings.a2a_gateway_route_prefix.strip("/")
        card = service.generate_agent_card(agent, "https://gw.com")
        assert card["url"] == f"https://gw.com/{prefix}/agent-prefix-1"

    def test_generate_agent_card_with_original_card(self, service):
        """Lines 307-324: When original_card is provided, use it as base and override url."""
        agent = SimpleNamespace(
            name="Echo Agent",
            description="Custom description from DB",
            id="agent-xyz",
            slug="echo",
            protocol_version="2.0",
            capabilities={},
            config={},
            tags=None,
        )

        # Original card from downstream agent
        original_card = {
            "name": "Original Echo",
            "description": "Original description",
            "url": "https://downstream.example.com/echo",
            "version": "1.0",
            "protocolVersion": "1.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text", "audio"],
            "defaultOutputModes": ["text", "image"],
            "skills": [{"id": "skill1", "name": "Skill 1"}],
            "provider": {"organization": "DownstreamOrg"},
        }

        card = service.generate_agent_card(agent, "https://gw.com", original_card=original_card)

        # URL should be overridden to point to gateway (line 308)
        assert "https://gw.com" in card["url"]
        assert "agent-xyz" in card["url"]

        # DB description should override original card description (lines 311-312)
        assert card["description"] == "Custom description from DB"

        # Other fields from original card should be preserved
        assert card["capabilities"]["streaming"] is True
        assert card["defaultInputModes"] == ["text", "audio"]
        assert card["defaultOutputModes"] == ["text", "image"]
        assert card["skills"] == [{"id": "skill1", "name": "Skill 1"}]
        assert card["provider"] == {"organization": "DownstreamOrg"}

        # Required fields should be set (lines 315-322)
        assert "name" in card
        assert "protocolVersion" in card

    def test_generate_agent_card_with_original_card_empty_description(self, service):
        """Lines 311-312: Empty DB description doesn't override original card description."""
        agent = SimpleNamespace(
            name="Test Agent",
            description="",  # Empty description
            id="agent-123",
            slug="test",
            protocol_version="1.0",
            capabilities={},
            config={},
            tags=None,
        )

        original_card = {
            "name": "Original Agent",
            "description": "Keep this description",
            "url": "https://downstream.example.com/",
        }

        card = service.generate_agent_card(agent, "https://gw.com", original_card=original_card)

        # Empty description should not override
        assert card["description"] == "Keep this description"

    # --- fetch_downstream_agent_card ---

    @pytest.mark.asyncio
    async def test_fetch_agent_card_cache_hit(self):
        """Lines 127-129: Return cached card if not expired."""
        # First-Party
        from mcpgateway.services.a2a_gateway_service import _agent_card_cache, fetch_downstream_agent_card

        # Manually populate cache
        cached_card = {"name": "Cached Agent", "url": "https://cached.example.com"}
        import time

        _agent_card_cache["agent-cached"] = (cached_card, time.monotonic())

        # Fetch should return cached data without making HTTP request
        result = await fetch_downstream_agent_card(
            agent_id="agent-cached", endpoint_url="https://agent.example.com/a2a", auth_headers={}, cache_ttl=60
        )

        assert result == cached_card

        # Clean up cache
        del _agent_card_cache["agent-cached"]

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_gateway_service._agent_card_cache", {})
    async def test_fetch_agent_card_successful_fetch(self):
        """Lines 158-162: Successfully fetch and cache agent card from downstream."""
        # First-Party
        from mcpgateway.services.a2a_gateway_service import _agent_card_cache, fetch_downstream_agent_card

        # Standard
        from unittest.mock import AsyncMock

        card_data = {"name": "Downstream Agent", "url": "https://downstream.example.com", "capabilities": {}}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = card_data

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        # Patch at import location
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await fetch_downstream_agent_card(
                agent_id="agent-fetch", endpoint_url="https://agent.example.com/a2a", auth_headers={"Authorization": "Bearer token"}, cache_ttl=60
            )

        # Should return the fetched card
        assert result == card_data

        # Should be cached (line 161)
        assert "agent-fetch" in _agent_card_cache
        cached_data, _ = _agent_card_cache["agent-fetch"]
        assert cached_data == card_data

        # Clean up
        del _agent_card_cache["agent-fetch"]

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_gateway_service._agent_card_cache", {})
    async def test_fetch_agent_card_retries_on_url_failures(self):
        """Lines 163-164: Exception during individual URL fetch triggers continue to next URL."""
        # First-Party
        from mcpgateway.services.a2a_gateway_service import _agent_card_cache, fetch_downstream_agent_card

        # Standard
        from unittest.mock import AsyncMock

        card_data = {"name": "Downstream Agent", "url": "https://downstream.example.com", "capabilities": {}}

        # First request fails, second request succeeds
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt fails (lines 163-164: exception caught, continue to next URL)
                raise ConnectionError("First URL failed")
            else:
                # Second attempt succeeds
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = card_data
                return mock_response

        mock_client = MagicMock()
        mock_client.get = mock_get

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await fetch_downstream_agent_card(
                agent_id="agent-retry", endpoint_url="https://agent.example.com/a2a", auth_headers={}, cache_ttl=60
            )

        # Should eventually succeed with the second URL
        assert result == card_data
        # First URL failed, second succeeded
        assert call_count >= 2

        # Clean up
        del _agent_card_cache["agent-retry"]

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_gateway_service._agent_card_cache", {})
    async def test_fetch_agent_card_generic_exception(self):
        """Lines 166-167: Generic exception during fetch returns None."""
        # First-Party
        from mcpgateway.services.a2a_gateway_service import fetch_downstream_agent_card

        # Standard
        from unittest.mock import AsyncMock

        # Simulate an exception during HTTP client setup
        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, side_effect=ConnectionError("Network error")):
            result = await fetch_downstream_agent_card(
                agent_id="agent-error", endpoint_url="https://agent.example.com/a2a", auth_headers={}, cache_ttl=60
            )

        # Should return None on exception (line 169)
        assert result is None


class TestConstants:
    """Verify protocol constants match A2A spec."""

    def test_all_methods_present(self):
        expected = {
            "message/send",
            "message/stream",
            "tasks/get",
            "tasks/list",
            "tasks/cancel",
            "tasks/resubscribe",
            "tasks/pushNotificationConfig/set",
            "tasks/pushNotificationConfig/get",
            "tasks/pushNotificationConfig/list",
            "tasks/pushNotificationConfig/delete",
            "agent/getAuthenticatedExtendedCard",
        }
        assert A2A_JSONRPC_METHODS == expected

    def test_streaming_methods(self):
        assert A2A_STREAMING_METHODS == {"message/stream", "tasks/resubscribe"}

    def test_error_codes(self):
        assert JSONRPC_PARSE_ERROR == -32700
        assert JSONRPC_INVALID_REQUEST == -32600
        assert JSONRPC_METHOD_NOT_FOUND == -32601
        assert JSONRPC_INTERNAL_ERROR == -32603
