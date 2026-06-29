# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_service_proxy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for GatewayService proxy-specific functionality.
Tests the new reverse proxy integration features including:
- register_gateway with is_proxy=True
- _initialize_gateway with proxy mode
- connect_to_proxy_server
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.schemas import GatewayCreate, ToolCreate, ResourceCreate, PromptCreate
from mcpgateway.services.gateway_service import (
    GatewayConnectionError,
    GatewayService,
)


def _make_execute_result(*, scalar=None, scalars_list=None, rowcount=0):
    """Helper to create mock SQLAlchemy Result objects."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_proxy
    result.rowcount = rowcount
    return result


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache
    clear_ssl_context_cache()

    with patch("mcpgateway.services.gateway_service.audit_trail") as mock_audit, \
         patch("mcpgateway.services.gateway_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def _bypass_gatewayread_validation(monkeypatch):
    """Stub out GatewayRead.model_validate for mock objects."""
    from mcpgateway.schemas import GatewayRead
    monkeypatch.setattr(GatewayRead, "model_validate", staticmethod(lambda x: x))


@pytest.fixture
def gateway_service():
    """A GatewayService instance with mocked HTTP client."""
    service = GatewayService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_db():
    """Return a mocked SQLAlchemy session."""
    session = MagicMock()
    session.query.return_value = MagicMock()
    session.commit.return_value = None
    session.rollback.return_value = None
    session.flush.return_value = None
    session.refresh.return_value = None
    session.add.return_value = None
    return session


@pytest.fixture(autouse=True)
def mock_forward_request_import(monkeypatch, mock_forward_request):
    """Automatically patch the forward_request_to_session method in reverse_proxy_service."""
    # Patch the service method that gateway_service actually calls
    from mcpgateway.services.reverse_proxy_service import ReverseProxyService
    monkeypatch.setattr(
        ReverseProxyService,
        "forward_request_to_session",
        mock_forward_request
    )
    return mock_forward_request


@pytest.fixture
def mock_forward_request():
    """Mock forward_request_func for proxy connections."""
    async def forward_func(session_id, request, authentication=None, auth_type=None):
        """Mock function that simulates forwarding MCP requests."""
        method = request.get("method")

        if method == "initialize":
            return {
                "payload": {
                    "result": {
                        "capabilities": {
                            "tools": {"listChanged": True},
                            "resources": {"subscribe": True},
                            "prompts": {"listChanged": True}
                        },
                        "serverInfo": {"name": "test-server", "version": "1.0.0"}
                    }
                }
            }
        elif method == "notifications/initialized":
            return {"payload": {}}
        elif method == "tools/list":
            return {
                "payload": {
                    "result": {
                        "tools": [
                            {
                                "name": "test_tool",
                                "description": "A test tool",
                                "inputSchema": {"type": "object", "properties": {}}
                            }
                        ]
                    }
                }
            }
        elif method == "resources/list":
            return {
                "payload": {
                    "result": {
                        "resources": [
                            {
                                "uri": "test://resource",
                                "name": "Test Resource",
                                "description": "A test resource",
                                "mimeType": "text/plain"
                            }
                        ]
                    }
                }
            }
        elif method == "prompts/list":
            return {
                "payload": {
                    "result": {
                        "prompts": [
                            {
                                "name": "test_prompt",
                                "description": "A test prompt",
                                "template": "This is a test prompt template"
                            }
                        ]
                    }
                }
            }
        return {"payload": {}}

    return AsyncMock(side_effect=forward_func)


class TestGatewayServiceProxy:
    """Tests for proxy-specific gateway service functionality."""

    # ────────────────────────────────────────────────────────────────────
    # register_gateway with is_proxy=True
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_register_proxy_gateway_success(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test successful registration of a proxy gateway."""
        # Setup mocks - need to provide enough results for all db.execute() calls
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # No existing gateway (line 1075)
                _make_execute_result(scalars_list=[]),  # Valid gateway IDs check for resources (line 921)
                _make_execute_result(scalars_list=[]),  # Candidate resources query (line 922)
                _make_execute_result(scalars_list=[]),  # Valid gateway IDs for prompts (line 1008)
                _make_execute_result(scalars_list=[]),  # Candidate prompts query (line 1009)
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        # Mock GatewayRead.model_validate to return a mock with .masked()
        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "proxy_gateway"
        mock_model.url = "ws://proxy"
        mock_model.id = "test-session-123"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="proxy_gateway",
            url="ws://proxy",
            description="A proxy gateway",
            transport="PROXIED",  # PROXIED transport for reverse proxy gateways
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-session-123",
        )

        # Verify result structure for proxy mode
        assert isinstance(result, tuple)
        assert len(result) == 4
        gateway_read, tool_ids, resource_ids, prompt_ids = result

        # Verify gateway was added
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()  # Implementation uses commit()
        mock_db.refresh.assert_called_once()

        # Verify forward_request was called for MCP protocol
        assert mock_forward_request.call_count >= 2  # At least initialize + initialized

    @pytest.mark.asyncio
    async def test_register_proxy_gateway_missing_session_id(self, gateway_service, mock_db):
        """Test that proxy registration fails without gateway_id."""
        gateway_create = GatewayCreate(
            name="proxy_gateway",
            url="ws://proxy",
            description="A proxy gateway",
            transport="PROXIED",
        )

        with pytest.raises(ValueError, match="gateway_id is required when created_via='reverse_proxy'"):
            await gateway_service.register_gateway(
                mock_db,
                gateway_create,
                created_via="reverse_proxy",
                gateway_id=None,  # Missing!
            )

    @pytest.mark.asyncio
    async def test_register_proxy_gateway_update_existing(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test that registering a proxy gateway with existing ID raises GatewayDuplicateConflictError."""
        # Create existing gateway mock
        existing_gateway = MagicMock(spec=DbGateway)
        existing_gateway.id = "test-session-123"
        existing_gateway.name = "old_name"
        existing_gateway.slug = "old_name"
        existing_gateway.enabled = True
        existing_gateway.visibility = "public"
        existing_gateway.tools = []
        existing_gateway.resources = []
        existing_gateway.prompts = []

        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # No existing gateway with same slug (line 769/778)
                _make_execute_result(scalar=existing_gateway),  # Existing gateway found by ID (line 788)
            ]
        )

        gateway_create = GatewayCreate(
            name="updated_proxy",
            url="ws://proxy",
            description="Updated proxy gateway",
            transport="PROXIED",
        )

        from mcpgateway.services.gateway_service import GatewayDuplicateConflictError

        # Expect GatewayDuplicateConflictError when gateway with same ID already exists
        with pytest.raises(GatewayDuplicateConflictError) as exc_info:
            await gateway_service.register_gateway(
                mock_db,
                gateway_create,
                created_via="reverse_proxy",
                gateway_id="test-session-123",
            )

        # Verify the error contains the existing gateway info
        assert exc_info.value.gateway_id == "test-session-123"
        assert exc_info.value.enabled is True

    # ────────────────────────────────────────────────────────────────────
    # _initialize_gateway with proxy mode
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_initialize_gateway_proxy_mode(self, gateway_service, mock_forward_request):
        """Test _initialize_gateway with reverse proxy mode."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="ws://proxy",
            authentication={},
            transport="PROXIED",
            gateway_id="test-session-123",
        )

        # Verify capabilities were retrieved
        assert "tools" in capabilities
        assert capabilities["tools"]["listChanged"] is True

        # Verify tools were retrieved and converted to ToolCreate
        assert len(tools) == 1
        assert isinstance(tools[0], ToolCreate)
        assert tools[0].name == "test_tool"

        # Verify resources were retrieved
        assert len(resources) == 1
        assert isinstance(resources[0], ResourceCreate)
        assert resources[0].uri == "test://resource"

        # Verify prompts were retrieved
        assert len(prompts) == 1
        assert isinstance(prompts[0], PromptCreate)
        assert prompts[0].name == "test_prompt"

    @pytest.mark.asyncio
    async def test_initialize_gateway_proxy_mode_missing_params(self, gateway_service):
        """Test _initialize_gateway falls back to standard mode when proxy params are missing."""
        # Mock the standard connection method since it will fall back to SSE
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        # When gateway_id and forward_request_func are both None, it should NOT use proxy mode
        # Instead it falls back to standard transport
        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="ws://proxy",
            authentication={},
            transport="SSE",  # Will use SSE since proxy params are missing
            gateway_id=None,  # Missing!
        )

        # Verify it used standard SSE connection, not proxy
        gateway_service.connect_to_sse_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_gateway_standard_mode(self, gateway_service):
        """Test _initialize_gateway with standard transport uses SSE."""
        # Mock the standard connection methods
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={},
            transport="SSE",
        )

        # Verify SSE connection was used
        gateway_service.connect_to_sse_server.assert_called_once()

    # ────────────────────────────────────────────────────────────────────
    # connect_to_proxy_server
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_success(self, gateway_service, mock_forward_request):
        """Test successful connection to proxy server."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=mock_forward_request,
            authentication={},
            include_prompts=True,
            include_resources=True,
        )

        # Verify MCP protocol sequence
        calls = mock_forward_request.call_args_list
        assert len(calls) >= 4  # initialize, initialized, tools/list, resources/list, prompts/list

        # Verify initialize was called first
        init_call = calls[0][0][1]
        assert init_call["method"] == "initialize"
        assert init_call["params"]["protocolVersion"] == "2024-11-05"

        # Verify capabilities
        assert "tools" in capabilities

        # Verify tools
        assert len(tools) == 1
        assert tools[0].name == "test_tool"

        # Verify resources
        assert len(resources) == 1
        assert resources[0].uri == "test://resource"

        # Verify prompts
        assert len(prompts) == 1
        assert prompts[0].name == "test_prompt"

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_no_resources(self, gateway_service, mock_forward_request):
        """Test proxy connection with include_resources=False."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=mock_forward_request,
            authentication={},
            include_prompts=True,
            include_resources=False,  # Skip resources
        )

        # Verify resources were not fetched
        assert len(resources) == 0

        # But tools and prompts should still be fetched
        assert len(tools) == 1
        assert len(prompts) == 1

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_no_prompts(self, gateway_service, mock_forward_request):
        """Test proxy connection with include_prompts=False."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=mock_forward_request,
            authentication={},
            include_prompts=False,  # Skip prompts
            include_resources=True,
        )

        # Verify prompts were not fetched
        assert len(prompts) == 0

        # But tools and resources should still be fetched
        assert len(tools) == 1
        assert len(resources) == 1

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_connection_error(self, gateway_service):
        """Test proxy connection handles errors gracefully."""
        async def failing_forward(session_id, request):
            raise Exception("Connection failed")

        with pytest.raises(GatewayConnectionError, match="Failed to fetch capabilities from reverse proxy session"):
            await gateway_service.connect_to_proxy_server(
                session_id="test-session-123",
                forward_request_func=AsyncMock(side_effect=failing_forward),
                authentication={},
            )

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_tools_fetch_failure(self, gateway_service):
        """Test proxy connection continues when tools fetch fails."""
        async def partial_forward(session_id, request, authentication=None, auth_type=None):
            method = request.get("method")
            if method == "initialize":
                return {
                    "payload": {
                        "result": {
                            "capabilities": {"tools": {"listChanged": True}},
                            "serverInfo": {"name": "test", "version": "1.0"}
                        }
                    }
                }
            elif method == "notifications/initialized":
                return {"payload": {}}
            elif method == "tools/list":
                raise Exception("Tools fetch failed")
            return {"payload": {}}

        # Should not raise, just log warning and return empty tools
        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=AsyncMock(side_effect=partial_forward),
            authentication={},
            include_resources=False,
            include_prompts=False,
        )

        # Verify capabilities were still retrieved
        assert "tools" in capabilities

        # But tools list is empty due to error
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_resource_validation_fallback(self, gateway_service):
        """Test proxy connection handles resource validation errors with fallback."""
        async def forward_with_invalid_resource(session_id, request, authentication=None, auth_type=None):
            method = request.get("method")
            if method == "initialize":
                return {
                    "payload": {
                        "result": {
                            "capabilities": {"resources": {"subscribe": True}},
                            "serverInfo": {"name": "test", "version": "1.0"}
                        }
                    }
                }
            elif method == "notifications/initialized":
                return {"payload": {}}
            elif method == "tools/list":
                return {"payload": {"result": {"tools": []}}}
            elif method == "resources/list":
                return {
                    "payload": {
                        "result": {
                            "resources": [
                                {
                                    "uri": "test://resource",
                                    "name": "Test Resource",
                                    # Missing required fields to trigger validation error
                                }
                            ]
                        }
                    }
                }
            return {"payload": {}}

        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=AsyncMock(side_effect=forward_with_invalid_resource),
            authentication={},
            include_resources=True,
            include_prompts=False,
        )

        # Verify fallback resource was created
        assert len(resources) == 1
        assert resources[0].uri == "test://resource"
        assert resources[0].name == "Test Resource"
        assert resources[0].content == ""  # Default content

    # ────────────────────────────────────────────────────────────────────
    # Additional coverage tests for error paths
    # ────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_initialize_gateway_oauth_authorization_code(self, gateway_service):
        """Test _initialize_gateway with OAuth authorization_code flow."""
        oauth_config = {
            "grant_type": "authorization_code",
            "client_id": "test_client",
            "authorization_endpoint": "https://example.com/oauth/authorize",
        }

        # Should return empty lists for authorization_code flow without oauth_auto_fetch_tool_flag
        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={},
            transport="SSE",
            auth_type="oauth",
            oauth_config=oauth_config,
            oauth_auto_fetch_tool_flag=False,
        )

        # Verify empty results for auth code flow
        assert capabilities == {}
        assert tools == []
        assert resources == []
        assert prompts == []

    @pytest.mark.asyncio
    async def test_initialize_gateway_oauth_client_credentials_success(self, gateway_service):
        """Test _initialize_gateway with OAuth client_credentials flow."""
        oauth_config = {
            "grant_type": "client_credentials",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "token_endpoint": "https://example.com/oauth/token",
        }

        # Mock OAuth manager and SSE connection
        gateway_service.oauth_manager.get_access_token = AsyncMock(return_value="test_access_token")
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={},
            transport="SSE",
            auth_type="oauth",
            oauth_config=oauth_config,
        )

        # Verify OAuth token was obtained with SSL cert parameters
        gateway_service.oauth_manager.get_access_token.assert_called_once_with(
            oauth_config, ca_certificate=None, client_cert=None, client_key=None
        )
        # Verify SSE connection was made with Bearer token
        gateway_service.connect_to_sse_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_gateway_oauth_client_credentials_failure(self, gateway_service):
        """Test _initialize_gateway handles OAuth token fetch failure."""
        oauth_config = {
            "grant_type": "client_credentials",
            "client_id": "test_client",
            "client_secret": "test_secret",
            "token_endpoint": "https://example.com/oauth/token",
        }

        # Mock OAuth manager to fail
        gateway_service.oauth_manager.get_access_token = AsyncMock(
            side_effect=Exception("Token fetch failed")
        )

        with pytest.raises(GatewayConnectionError, match="OAuth authentication failed"):
            await gateway_service._initialize_gateway(
                url="http://example.com",
                authentication={},
                transport="SSE",
                auth_type="oauth",
                oauth_config=oauth_config,
            )

    @pytest.mark.asyncio
    async def test_connect_to_proxy_server_with_auth_type(self, gateway_service, mock_forward_request):
        """Test proxy connection with auth_type parameter."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service.connect_to_proxy_server(
            session_id="test-session-123",
            forward_request_func=mock_forward_request,
            authentication={"Authorization": "Bearer test_token"},
            auth_type="bearer",
            include_prompts=True,
            include_resources=True,
        )

        # Verify capabilities were retrieved
        assert "tools" in capabilities
        assert len(tools) == 1
        assert len(resources) == 1
        assert len(prompts) == 1

    @pytest.mark.asyncio
    async def test_initialize_gateway_with_pre_auth_headers(self, gateway_service):
        """Test _initialize_gateway with pre-authenticated headers."""
        pre_auth_headers = {"Authorization": "Bearer pre_auth_token"}

        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={},
            transport="SSE",
            pre_auth_headers=pre_auth_headers,
        )

        # Verify SSE connection was called
        gateway_service.connect_to_sse_server.assert_called_once()
        # The pre_auth_headers should be used instead of authentication

    @pytest.mark.asyncio
    async def test_initialize_gateway_streamablehttp_transport(self, gateway_service):
        """Test _initialize_gateway with StreamableHTTP transport."""
        gateway_service.connect_to_streamablehttp_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication={},
            transport="StreamableHTTP",
        )

        # Verify StreamableHTTP connection was used
        gateway_service.connect_to_streamablehttp_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_gateway_with_auth_headers(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration with custom auth headers."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "auth_headers_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="auth_headers_gateway",
            url="ws://proxy",
            description="Gateway with auth headers",
            transport="PROXIED",
            auth_headers=[
                {"key": "X-API-Key", "value": "test-key"},
                {"key": "X-Custom-Header", "value": "test-value"}
            ]
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-session-auth",
        )

        assert isinstance(result, tuple)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_register_gateway_with_query_param_auth(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration with query param authentication."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "query_param_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        # Create a mock gateway object with query param auth attributes
        gateway_create = Mock(spec=GatewayCreate)
        gateway_create.name = "query_param_gateway"
        gateway_create.url = "ws://proxy"
        gateway_create.description = "Gateway with query param auth"
        gateway_create.transport = "PROXIED"
        gateway_create.auth_type = "query_param"
        gateway_create.auth_query_param_key = "api_key"
        gateway_create.auth_query_param_value = "secret-key-123"
        gateway_create.auth_value = None
        gateway_create.auth_headers = None
        gateway_create.oauth_config = None
        gateway_create.one_time_auth = False
        gateway_create.tags = []
        gateway_create.passthrough_headers = None
        gateway_create.ca_certificate = None
        gateway_create.ca_certificate_sig = None
        gateway_create.signing_algorithm = None

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-session-query",
        )

        assert isinstance(result, tuple)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_register_gateway_with_string_auth_value(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration with string auth_value (encoded)."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "string_auth_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        # Create an encoded auth value
        from mcpgateway.utils.services_auth import encode_auth
        encoded_auth = encode_auth({"Authorization": "Bearer test-token"})

        gateway_create = GatewayCreate(
            name="string_auth_gateway",
            url="ws://proxy",
            description="Gateway with string auth",
            transport="PROXIED",
            auth_value=encoded_auth
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-session-string",
        )

        assert isinstance(result, tuple)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_register_gateway_with_dict_auth_value(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration with dict auth_value (encoded as string)."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "dict_auth_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        # auth_value must be a string (encoded), not a dict
        # The implementation handles dict internally but the schema expects string
        from mcpgateway.utils.services_auth import encode_auth
        encoded_auth = encode_auth({"Authorization": "Bearer test-token"})

        gateway_create = GatewayCreate(
            name="dict_auth_gateway",
            url="ws://proxy",
            description="Gateway with dict auth",
            transport="PROXIED",
            auth_value=encoded_auth
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-session-dict",
        )

        assert isinstance(result, tuple)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_initialize_gateway_with_basic_auth_string(self, gateway_service):
        """Test _initialize_gateway with basic auth as string."""
        gateway_service.connect_to_sse_server = AsyncMock(
            return_value=({"tools": {}}, [], [], [], [])
        )

        from mcpgateway.utils.services_auth import encode_auth
        encoded_auth = encode_auth({"Authorization": "Basic dGVzdDp0ZXN0"})

        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="http://example.com",
            authentication=encoded_auth,
            transport="SSE",
            auth_type="basic",
        )

        # Verify SSE connection was called
        gateway_service.connect_to_sse_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_gateway_without_resources(self, gateway_service, mock_forward_request):
        """Test _initialize_gateway with include_resources=False."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="ws://proxy",
            authentication={},
            transport="PROXIED",
            gateway_id="test-session-123",
            include_resources=False,
        )

        # Verify resources were not fetched
        assert len(resources) == 0
        # But tools and prompts should be fetched
        assert len(tools) == 1
        assert len(prompts) == 1

    @pytest.mark.asyncio
    async def test_initialize_gateway_without_prompts(self, gateway_service, mock_forward_request):
        """Test _initialize_gateway with include_prompts=False."""
        capabilities, tools, resources, prompts, validation_errors = await gateway_service._initialize_gateway(
            url="ws://proxy",
            authentication={},
            transport="PROXIED",
            gateway_id="test-session-123",
            include_prompts=False,
        )

        # Verify prompts were not fetched
        assert len(prompts) == 0
        # But tools and resources should be fetched
        assert len(tools) == 1
        assert len(resources) == 1

    @pytest.mark.asyncio
    async def test_register_gateway_initialization_timeout(self, gateway_service, mock_db, monkeypatch):
        """Test gateway registration with initialization timeout."""
        import asyncio

        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),  # No existing gateway with same slug
                _make_execute_result(scalar=None),  # No existing gateway by ID
            ]
        )

        # Mock _initialize_gateway to timeout - use asyncio.Event to prevent StopIteration
        async def slow_init(*args, **kwargs):
            # Use an event that never gets set to simulate infinite wait
            event = asyncio.Event()
            await event.wait()  # This will wait forever, causing timeout
            return {}, [], [], []

        gateway_service._initialize_gateway = slow_init

        gateway_create = GatewayCreate(
            name="timeout_gateway",
            url="ws://proxy",
            description="Gateway that times out",
            transport="PROXIED",
        )

        from mcpgateway.services.gateway_service import GatewayConnectionError

        with pytest.raises(GatewayConnectionError, match="Gateway initialization timed out"):
            await gateway_service.register_gateway(
                mock_db,
                gateway_create,
                created_via="reverse_proxy",
                gateway_id="test-timeout",
                initialize_timeout=0.1,  # Very short timeout
            )

    @pytest.mark.asyncio
    async def test_register_gateway_without_initialize_timeout(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration without initialization (initialize_timeout=None)."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "no_init_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        gateway_create = GatewayCreate(
            name="no_init_gateway",
            url="ws://proxy",
            description="Gateway without initialization",
            transport="PROXIED",
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-no-init",
            initialize_timeout=None,  # Skip initialization
        )

        # Should still return tuple for proxy mode
        assert isinstance(result, tuple)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_register_gateway_with_ca_certificate(self, gateway_service, mock_db, mock_forward_request, monkeypatch):
        """Test gateway registration with CA certificate."""
        mock_db.execute = Mock(
            side_effect=[
                _make_execute_result(scalar=None),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
                _make_execute_result(scalars_list=[]),
            ]
        )

        gateway_service._notify_gateway_added = AsyncMock()

        mock_model = Mock()
        mock_model.masked.return_value = mock_model
        mock_model.name = "ca_cert_gateway"

        monkeypatch.setattr(
            "mcpgateway.services.gateway_service.GatewayRead.model_validate",
            lambda x: mock_model,
        )

        # Mock CA certificate
        ca_cert = b"-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----"

        gateway_create = GatewayCreate(
            name="ca_cert_gateway",
            url="ws://proxy",
            description="Gateway with CA cert",
            transport="PROXIED",
            ca_certificate=ca_cert
        )

        result = await gateway_service.register_gateway(
            mock_db,
            gateway_create,
            created_via="reverse_proxy",
            gateway_id="test-ca-cert",
        )

        assert isinstance(result, tuple)
        assert len(result) == 4
