# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_rpc_tool_invocation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test RPC tool invocation after PR #746 changes.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.main import app
from mcpgateway.common.models import Tool
from mcpgateway.services.tool_service import ToolService


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_tool_service():
    """Create a mock tool service."""
    service = AsyncMock(spec=ToolService)
    return service


@pytest.fixture
def sample_tool():
    """Create a sample tool for testing."""
    return Tool(
        name="test_tool",
        url="http://localhost:8000/test",
        description="A test tool",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "number", "default": 5}}, "required": ["query"]},
    )


class TestRPCToolInvocation:
    """Test class for RPC tool invocation."""

    def test_tools_call_method_new_format(self, client, mock_db):
        """Test tool invocation using the new tools/call method format."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock) as mock_invoke:
                    mock_invoke.return_value = {"result": "success", "data": "test data"}

                    request_body = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "test_tool", "arguments": {"query": "test", "limit": 5}}, "id": 1}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["id"] == 1

                    mock_invoke.assert_called_once()
                    call_args = mock_invoke.call_args
                    assert call_args.kwargs["name"] == "test_tool"
                    assert call_args.kwargs["arguments"] == {"query": "test", "limit": 5}

    def test_direct_tool_invocation_fails(self, client, mock_db):
        """Test that direct tool invocation (old format) now fails with 'Invalid method'."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                request_body = {"jsonrpc": "2.0", "method": "test_tool", "params": {"query": "test", "limit": 5}, "id": 1}  # Direct tool name as method (old format)

                response = client.post("/rpc", json=request_body)

                assert response.status_code == 200
                result = response.json()
                assert result["jsonrpc"] == "2.0"
                assert "error" in result
                assert result["error"]["code"] == -32000
                assert result["error"]["message"] == "Invalid method"
                assert result["error"]["data"] == {"query": "test", "limit": 5}
                assert result["id"] == 1

    def test_tools_list_method(self, client, mock_db):
        """Test the tools/list method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                    sample_tool = MagicMock()
                    sample_tool.model_dump.return_value = {"name": "test_tool", "description": "A test tool"}
                    mock_list.return_value = ([sample_tool], None)

                    request_body = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert "tools" in result["result"]
                    assert len(result["result"]["tools"]) == 1
                    assert result["result"]["tools"][0]["name"] == "test_tool"

    def test_resources_read_method(self, client, mock_db):
        """Test the resources/read method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock) as mock_read:
                    mock_read.return_value = {"uri": "test://resource", "content": "test content"}

                    request_body = {"jsonrpc": "2.0", "method": "resources/read", "params": {"uri": "test://resource"}, "id": 3}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert "contents" in result["result"]

    def test_prompts_get_method(self, client, mock_db):
        """Test the prompts/get method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.prompt_service.get_prompt", new_callable=AsyncMock) as mock_get:
                    mock_prompt = MagicMock()
                    mock_prompt.model_dump.return_value = {"name": "test_prompt", "description": "A test prompt", "messages": []}
                    mock_get.return_value = mock_prompt

                    request_body = {"jsonrpc": "2.0", "method": "prompts/get", "params": {"name": "test_prompt", "arguments": {}}, "id": 4}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result

    def test_initialize_method(self, client, mock_db):
        """Test the initialize method."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                with patch("mcpgateway.main.session_registry.handle_initialize_logic", new_callable=AsyncMock) as mock_init:
                    mock_init.return_value = MagicMock(model_dump=MagicMock(return_value={"protocolVersion": "1.0", "capabilities": {}, "serverInfo": {"name": "test-server"}}))

                    request_body = {"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion": "1.0", "capabilities": {}, "clientInfo": {"name": "test-client"}}, "id": 5}

                    response = client.post("/rpc", json=request_body)

                    assert response.status_code == 200
                    result = response.json()
                    assert result["jsonrpc"] == "2.0"
                    assert "result" in result
                    assert result["result"]["protocolVersion"] == "1.0"

    @pytest.mark.parametrize(
        "method,expected_result_key",
        [
            ("tools/list", "tools"),
            ("resources/list", "resources"),
            ("prompts/list", "prompts"),
            ("list_gateways", "gateways"),
            ("list_roots", "roots"),
        ],
    )
    def test_list_methods_return_proper_structure(self, client, mock_db, method, expected_result_key):
        """Test that all list methods return results in the proper structure."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                # Mock all possible service methods
                with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock, return_value=([], None)):
                    with patch("mcpgateway.main.resource_service.list_resources", new_callable=AsyncMock, return_value=([], None)):
                        with patch("mcpgateway.main.prompt_service.list_prompts", new_callable=AsyncMock, return_value=([], None)):
                            with patch("mcpgateway.main.gateway_service.list_gateways", new_callable=AsyncMock, return_value=([], None)):
                                with patch("mcpgateway.main.root_service.list_roots", new_callable=AsyncMock, return_value=[]):
                                    request_body = {"jsonrpc": "2.0", "method": method, "params": {}, "id": 100}

                                    response = client.post("/rpc", json=request_body)

                                    assert response.status_code == 200
                                    result = response.json()
                                    assert result["jsonrpc"] == "2.0"
                                    assert "result" in result
                                    assert expected_result_key in result["result"]
                                    assert isinstance(result["result"][expected_result_key], list)

    def test_unknown_method_returns_error(self, client, mock_db):
        """Test that unknown methods return an appropriate error."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_db", return_value=mock_db):
                request_body = {"jsonrpc": "2.0", "method": "unknown/method", "params": {}, "id": 999}

                response = client.post("/rpc", json=request_body)

                assert response.status_code == 200
                result = response.json()
                assert result["jsonrpc"] == "2.0"
                assert "error" in result
                assert result["error"]["code"] == -32000
                assert result["error"]["message"] == "Invalid method"
                assert result["id"] == 999


class TestRPCServerIdScoping:
    """Tests for server_id scoping enforcement in the /rpc handler (issue #2743).

    Pure validate_server_access() unit tests live in
    tests/unit/mcpgateway/utils/test_token_scoping_utils.py.
    These tests cover the HTTP-level enforcement wired into handle_rpc().
    """

    # ------------------------------------------------------------------
    # HTTP-level: 403 returned when validate_server_access rejects
    # ------------------------------------------------------------------

    def test_rpc_returns_403_when_server_scoped_token_accesses_wrong_server(self, client, mock_db):
        """Patching validate_server_access to return False must produce a 403 JSON-RPC error."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_current_user_with_permissions", return_value={"sub": "user@example.com"}):
                with patch("mcpgateway.main.validate_server_access", return_value=False) as mock_validate:
                    response = client.post(
                        "/rpc",
                        json={"jsonrpc": "2.0", "method": "tools/list", "params": {"server_id": "xyz"}, "id": 1},
                    )
                    mock_validate.assert_called_once_with({}, "xyz")

        assert response.status_code == 403
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32003
        assert "xyz" in body["error"]["message"]

    def test_rpc_proceeds_when_server_access_is_allowed(self, client, mock_db):
        """When validate_server_access returns True, the request must proceed to the handler."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_current_user_with_permissions", return_value={"sub": "user@example.com"}):
                with patch("mcpgateway.main.validate_server_access", return_value=True) as mock_validate:
                    with patch("mcpgateway.main.tool_service.list_server_tools", new_callable=AsyncMock) as mock_list:
                        mock_list.return_value = []
                        response = client.post(
                            "/rpc",
                            json={"jsonrpc": "2.0", "method": "tools/list", "params": {"server_id": "abc"}, "id": 3},
                        )
                        mock_validate.assert_called_once_with({}, "abc")

        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "result" in body
        assert "tools" in body["result"]

    def test_rpc_skips_validation_for_unscoped_token_without_server_id(self, client, mock_db):
        """Global token (no scopes.server_id) without server_id in params → proceeds to global list."""
        with patch("mcpgateway.config.settings.auth_required", False):
            with patch("mcpgateway.main.get_current_user_with_permissions", return_value={"sub": "user@example.com"}):
                with patch("mcpgateway.main.validate_server_access") as mock_validate:
                    with patch("mcpgateway.main.tool_service.list_tools", new_callable=AsyncMock) as mock_list:
                        mock_list.return_value = ([], None)
                        response = client.post(
                            "/rpc",
                            json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2},
                        )
                        mock_validate.assert_not_called()

        assert response.status_code == 200

    # ------------------------------------------------------------------
    # Auto-injection: server-scoped token + missing server_id
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auto_injection_sets_server_id_from_scoped_token(self, mock_db):
        """When request omits server_id but token is server-scoped, server_id must be auto-injected.

        Calls handle_rpc() directly with a mock request carrying a server-scoped
        _jwt_verified_payload, bypassing the middleware stack so that the actual
        auto-injection line in main.py is exercised.
        """
        from types import SimpleNamespace  # noqa: PLC0415
        from mcpgateway.main import handle_rpc  # noqa: PLC0415

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.state = SimpleNamespace(
            _jwt_verified_payload=("tok", {"sub": "u@ex.com", "scopes": {"server_id": "srv-abc"}, "is_admin": True, "teams": None}),
            token_teams=None,
        )

        async def mock_body():
            import orjson  # noqa: PLC0415
            return orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 10})

        mock_request.body = mock_body

        with patch("mcpgateway.main.tool_service.list_server_tools", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            await handle_rpc(mock_request, db=mock_db, user={"sub": "u@ex.com"})

            # Auto-injected server_id must route to list_server_tools with "srv-abc"
            mock_list.assert_called_once()
            assert mock_list.call_args[0][1] == "srv-abc"

    def test_auto_injection_skipped_for_global_token(self):
        """Global token (scopes.server_id=None) must NOT auto-inject a server_id."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=("tok", {"sub": "u@ex.com", "scopes": {"server_id": None, "permissions": ["*"]}}))
        server_id = None

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}
        _token_server_id = _token_scopes.get("server_id") if _token_scopes else None

        if server_id:
            pass
        elif _token_server_id is not None:
            server_id = _token_server_id

        assert server_id is None, "Global token must not auto-inject server_id"

    def test_auto_injection_skipped_when_no_jwt(self):
        """No JWT payload (basic auth) must NOT auto-inject a server_id."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=None)
        server_id = None

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}
        _token_server_id = _token_scopes.get("server_id") if _token_scopes else None

        if server_id:
            pass
        elif _token_server_id is not None:
            server_id = _token_server_id

        assert server_id is None, "No JWT must not auto-inject server_id"

    # ------------------------------------------------------------------
    # _jwt_verified_payload tuple-extraction logic
    # ------------------------------------------------------------------

    def test_scopes_correctly_extracted_from_jwt_payload_tuple(self):
        """_jwt_verified_payload is stored as (token, payload) — extraction must unpack correctly."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=("eyJhbGci...", {"sub": "u@ex.com", "scopes": {"server_id": "srv-abc"}}))

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}

        assert _token_scopes == {"server_id": "srv-abc"}

        # First-Party
        from mcpgateway.utils.token_scoping import validate_server_access  # noqa: PLC0415

        assert validate_server_access(_token_scopes, "srv-abc") is True
        assert validate_server_access(_token_scopes, "srv-xyz") is False

    def test_scopes_extraction_handles_missing_payload(self):
        """None _jwt_verified_payload (basic auth / no JWT) must yield empty scopes → full access."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=None)

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}

        assert _token_scopes == {}
        from mcpgateway.utils.token_scoping import validate_server_access  # noqa: PLC0415

        assert validate_server_access(_token_scopes, "any-server") is True

    def test_scopes_extraction_handles_payload_without_scopes_key(self):
        """Token payload without a 'scopes' key must default to empty dict → no restriction."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=("token", {"sub": "u@ex.com", "is_admin": True}))

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}

        assert _token_scopes == {}
        from mcpgateway.utils.token_scoping import validate_server_access  # noqa: PLC0415

        assert validate_server_access(_token_scopes, "any-server") is True

    def test_scopes_extraction_handles_non_dict_payload(self):
        """Non-dict payload in tuple (e.g. string) must be treated as missing → full access."""
        from types import SimpleNamespace  # noqa: PLC0415

        state = SimpleNamespace(_jwt_verified_payload=("token", "not-a-dict"))

        _cached = getattr(state, "_jwt_verified_payload", None)
        _jwt_payload = _cached[1] if (isinstance(_cached, tuple) and len(_cached) == 2 and isinstance(_cached[1], dict)) else None
        _token_scopes = _jwt_payload.get("scopes", {}) if _jwt_payload else {}

        assert _jwt_payload is None
        assert _token_scopes == {}

        from mcpgateway.utils.token_scoping import validate_server_access  # noqa: PLC0415

        assert validate_server_access(_token_scopes, "any-server") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
