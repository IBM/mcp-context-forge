# -*- coding: utf-8 -*-
# tests/integration/test_integration.py
"""Location: ./tests/integration/test_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

End-to-end happy-path integration tests for the MCP Gateway API.
These tests exercise several endpoints together instead of in isolation:

1. Create a tool ➜ create a server that references that tool.
2. MCP protocol handshake: /protocol/initialize ➜ /protocol/ping.
3. Full resource life-cycle: register ➜ read content.
4. Invoke a tool via JSON-RPC.
5. Aggregate metrics endpoint.

All external service calls are patched out with AsyncMocks so the FastAPI app
under test never touches a real database or network.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime
from unittest.mock import ANY, AsyncMock, patch
import urllib.parse

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.common.models import InitializeResult, ResourceContent, ServerCapabilities
from mcpgateway.schemas import ResourceRead, ServerRead, ToolMetrics, ToolRead

# Local
from tests.utils.rbac_mocks import MockPermissionService


# -----------------------------------------------------------------------------
# Test fixtures (local to this file; move to conftest.py to share project-wide)
# -----------------------------------------------------------------------------
@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with proper database setup and auth dependency overridden."""
    # Standard
    import os
    import tempfile

    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    # First-Party
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    db_mod.Base.metadata.create_all(bind=engine)

    # Set up authentication overrides
    app.dependency_overrides[require_auth] = lambda: "integration-test-user"

    # Also need to override RBAC and basic authentication
    # Standard
    # Create mock user for basic auth
    from unittest.mock import MagicMock

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service

    mock_email_user = MagicMock()
    mock_email_user.email = "integration-test-user@example.com"
    mock_email_user.full_name = "Integration Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        db_session = TestSessionLocal()
        return {
            "email": "integration-test-user@example.com",
            "full_name": "Integration Test User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": db_session,
        }

    def mock_get_permission_service(*args, **kwargs):
        """Return a mock permission service that always grants access."""
        return MockPermissionService(always_grant=True)

    def override_get_db():
        """Override database dependency to return our test database."""
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Patch the PermissionService class to always return our mock
    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        client = TestClient(app)
        yield client

        # Cleanup
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Dummy Bearer token accepted by the overridden dependency."""
    return {"Authorization": "Bearer 123.123.integration"}


# -----------------------------------------------------------------------------
# Shared mock objects
# -----------------------------------------------------------------------------
MOCK_METRICS = {
    "total_executions": 1,
    "successful_executions": 1,
    "failed_executions": 0,
    "failure_rate": 0.0,
    "min_response_time": 0.01,
    "max_response_time": 0.01,
    "avg_response_time": 0.01,
    "last_execution_time": "2025-01-01T00:00:00",
}

MOCK_TOOL = ToolRead(
    id="tool-1",
    name="test_tool",
    original_name="test_tool",
    url="http://example.com/tools/test",
    description="demo",
    request_type="POST",
    integration_type="MCP",
    headers={"Content-Type": "application/json"},
    input_schema={"type": "object", "properties": {"foo": {"type": "string"}}},
    annotations={},
    jsonpath_filter=None,
    auth=None,
    created_at=datetime(2025, 1, 1),
    updated_at=datetime(2025, 1, 1),
    enabled=True,
    reachable=True,
    gateway_id=None,
    execution_count=0,
    metrics=ToolMetrics(**MOCK_METRICS),
    gateway_slug="default",
    customName="test_tool",
    customNameSlug="test-tool",
    tags=[],
)

MOCK_SERVER = ServerRead(
    id="srv-1",
    name="test_server",
    description="integration server",
    icon=None,
    created_at=datetime(2025, 1, 1),
    updated_at=datetime(2025, 1, 1),
    enabled=True,
    associated_tools=[MOCK_TOOL.id],
    associated_resources=[],
    associated_prompts=[],
    metrics=MOCK_METRICS,
    tags=[],
)

MOCK_RESOURCE = ResourceRead(
    id="39334ce0ed2644d79ede8913a66930c9",
    uri="file:///tmp/hello.txt",
    name="Hello",
    description="demo text",
    mime_type="text/plain",
    size=5,
    created_at=datetime(2025, 1, 1),
    updated_at=datetime(2025, 1, 1),
    enabled=True,
    metrics=MOCK_METRICS,
    tags=[],
)

# URL-escaped version of the resource URI (used in path parameters)
RESOURCE_URI_ESC = urllib.parse.quote(MOCK_RESOURCE.uri, safe="")


# -----------------------------------------------------------------------------
# Integration test class
# -----------------------------------------------------------------------------
class TestIntegrationScenarios:
    """Happy-path flows that stitch several endpoints together."""

    # --------------------------------------------------------------------- #
    # 1. Create a tool ➜ create a server that references that tool          #
    # --------------------------------------------------------------------- #
    @patch("mcpgateway.main.server_service.register_server", new_callable=AsyncMock)
    @patch("mcpgateway.main.tool_service.register_tool", new_callable=AsyncMock)
    def test_server_with_tools_workflow(
        self,
        mock_register_tool: AsyncMock,
        mock_register_server: AsyncMock,
        test_client: TestClient,
        auth_headers,
    ):
        mock_register_tool.return_value = MOCK_TOOL
        mock_register_server.return_value = MOCK_SERVER

        # 1a. register a tool
        tool_req = {"tool": {"name": "test_tool", "url": "http://example.com"}, "team_id": None, "visibility": "private"}
        resp_tool = test_client.post("/tools/", json=tool_req, headers=auth_headers)
        assert resp_tool.status_code == 200
        mock_register_tool.assert_awaited_once()

        # 1b. register a server that references that tool
        srv_req = {
            "server": {
                "name": "test_server",
                "description": "integration server",
                "associated_tools": [MOCK_TOOL.id],
            },
            "team_id": None,
            "visibility": "private",
        }
        resp_srv = test_client.post("/servers/", json=srv_req, headers=auth_headers)
        assert resp_srv.status_code == 201
        assert resp_srv.json()["associatedTools"] == [MOCK_TOOL.id]
        mock_register_server.assert_awaited_once()

    # --------------------------------------------------------------------- #
    # 2. MCP protocol: initialize ➜ ping                                    #
    # --------------------------------------------------------------------- #
    @patch("mcpgateway.main.session_registry.handle_initialize_logic", new_callable=AsyncMock)
    def test_initialize_and_ping_workflow(
        self,
        mock_init: AsyncMock,
        test_client: TestClient,
        auth_headers,
    ):
        mock_init.return_value = InitializeResult(
            protocolVersion="2025-03-26",
            capabilities=ServerCapabilities(prompts={}, resources={}, tools={}, logging={}, roots={}, sampling={}),
            serverInfo={"name": "gw", "version": "1.0"},
            instructions="hello",
        )

        init_body = {
            "protocol_version": "2025-03-26",
            "capabilities": {},
            "client_info": {"name": "pytest", "version": "0.0.0"},
        }
        resp_init = test_client.post("/protocol/initialize", json=init_body, headers=auth_headers)
        assert resp_init.status_code == 200
        mock_init.assert_awaited_once()

        resp_ping = test_client.post(
            "/protocol/ping",
            json={"jsonrpc": "2.0", "method": "ping", "id": "X"},
            headers=auth_headers,
        )
        assert resp_ping.status_code == 200
        assert resp_ping.json() == {"jsonrpc": "2.0", "id": "X", "result": {}}

    # --------------------------------------------------------------------- #
    # 3. Resource life-cycle                                                #
    # --------------------------------------------------------------------- #
    @patch("mcpgateway.main.resource_service.register_resource", new_callable=AsyncMock)
    @patch("mcpgateway.main.resource_service.read_resource", new_callable=AsyncMock)
    def test_resource_lifecycle(
        self,
        mock_read: AsyncMock,
        mock_register: AsyncMock,
        test_client: TestClient,
        auth_headers,
    ):
        mock_register.return_value = MOCK_RESOURCE

        create_body = {
            "resource": {
                "uri": MOCK_RESOURCE.uri,
                "name": MOCK_RESOURCE.name,
                "description": "demo text",
                "content": "Hello",  # required by ResourceCreate
            },
            "team_id": None,
            "visibility": "private",
        }
        resp_create = test_client.post("/resources/", json=create_body, headers=auth_headers)
        assert resp_create.status_code == 200
        mock_register.assert_awaited_once()
        resource_id = resp_create.json()["id"]

        # read content
        mock_read.return_value = ResourceContent(type="resource", id=str(resource_id), uri=MOCK_RESOURCE.uri, mime_type="text/plain", text="Hello")
        resp_read = test_client.get(f"/resources/{resource_id}", headers=auth_headers)
        assert resp_read.status_code == 200
        assert resp_read.json()["text"] == "Hello"
        mock_read.assert_awaited_once()

    # --------------------------------------------------------------------- #
    # 4. Invoke a tool via JSON-RPC                                         #
    # --------------------------------------------------------------------- #
    @patch("mcpgateway.main.tool_service.invoke_tool", new_callable=AsyncMock)
    def test_rpc_tool_invocation_flow(
        self,
        mock_invoke: AsyncMock,
        test_client: TestClient,
        auth_headers,
    ):
        mock_invoke.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "is_error": False,
        }

        rpc_body = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "test_tool", "arguments": {"foo": "bar"}}}
        resp = test_client.post("/rpc/", json=rpc_body, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["result"]["content"][0]["text"] == "ok"
        mock_invoke.assert_awaited_once_with(db=ANY, name="test_tool", arguments={"foo": "bar"}, request_headers=ANY, app_user_email="integration-test-user@example.com", plugin_context_table=None, plugin_global_context=None)

    # --------------------------------------------------------------------- #
    # 5. Metrics aggregation endpoint                                       #
    # --------------------------------------------------------------------- #
    @patch("mcpgateway.main.prompt_service.aggregate_metrics", new_callable=AsyncMock, return_value={"p": 1})
    @patch("mcpgateway.main.server_service.aggregate_metrics", new_callable=AsyncMock, return_value={"s": 1})
    @patch("mcpgateway.main.resource_service.aggregate_metrics", new_callable=AsyncMock, return_value={"r": 1})
    @patch("mcpgateway.main.tool_service.aggregate_metrics", new_callable=AsyncMock, return_value={"t": 1})
    def test_metrics_happy_path(
        self,
        _tm,
        _rm,
        _sm,
        _pm,
        test_client: TestClient,
        auth_headers,
    ):
        resp = test_client.get("/metrics", headers=auth_headers)
        assert resp.status_code == 200
        payload = resp.json()
        # Make sure all four keys are present regardless of exact values.
        for key in ("tools", "resources", "servers", "prompts"):
            assert key in payload
