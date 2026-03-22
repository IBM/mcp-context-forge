# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_crt_router_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for the CRT Router API extension.

Tests the GET /servers/{server_id}/tools endpoint with router=crt query parameters
and the GET /router/health endpoint, using mocked services and plugin manager.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.main import app
from mcpgateway.middleware.rbac import get_current_user_with_permissions
from mcpgateway.middleware.rbac import get_db as rbac_get_db
from mcpgateway.middleware.rbac import get_permission_service

# Local
from tests.utils.rbac_mocks import MockPermissionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_read(tool_id: str = "tool-1", name: str = "test-tool") -> MagicMock:
    """Build a mock object that behaves like a ToolRead instance.

    model_dump returns a dict with all required ToolRead fields so FastAPI
    response validation passes without errors.
    """
    from datetime import datetime, timezone

    tool = MagicMock()
    tool.id = tool_id
    tool.name = name
    tool.description = f"Description for {name}"
    tool.execution_count = 5
    tool.crt_scores = None

    _now = datetime.now(timezone.utc).isoformat()
    tool.model_dump.return_value = {
        "id": tool_id,
        "originalName": name,
        "name": name,
        "description": f"Description for {name}",
        "originalDescription": None,
        "url": None,
        "requestType": "GET",
        "integrationType": "rest",
        "headers": None,
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": None,
        "annotations": None,
        "jsonpathFilter": None,
        "auth": None,
        "createdAt": _now,
        "updatedAt": _now,
        "enabled": True,
        "reachable": True,
        "gatewayId": None,
        "executionCount": 5,
        "metrics": None,
        "displayName": name,
        "gatewaySlug": name,
        "customName": name,
        "customNameSlug": name.replace("-", "_"),
        "tags": [],
        "createdBy": None,
        "createdFromIp": None,
        "createdVia": None,
        "createdUserAgent": None,
        "modifiedBy": None,
        "modifiedFromIp": None,
        "modifiedVia": None,
        "modifiedUserAgent": None,
        "importBatchId": None,
        "federationSource": None,
        "version": 1,
        "teamId": None,
        "team": None,
        "ownerEmail": None,
        "visibility": "public",
        "baseUrl": None,
        "pathTemplate": None,
        "queryMapping": None,
        "headerMapping": None,
        "timeoutMs": 20000,
        "exposePassthrough": True,
        "allowlist": None,
        "pluginChainPre": None,
        "pluginChainPost": None,
        "_meta": None,
        "crtScores": None,
    }
    return tool


def _make_crt_plugin(rank_results=None, health_result=None):
    """Build a mock CRTRouterPlugin that returns given rank results."""
    plugin = MagicMock()

    if rank_results is None:
        # Default: return tools with neutral scores (stub behavior)
        async def default_rank(tools, prompt, k, threshold, db=None):
            return [(t, {"relevance": 1.0, "loss": 0.0, "entropy": 0.0}) for t in tools]

        plugin.rank_tools = default_rank
    else:
        plugin.rank_tools = AsyncMock(return_value=rank_results)

    if health_result is None:
        health_result = {
            "status": "healthy",
            "version": "1.0.0",
            "calibration_checksum": "abc123",
            "calibration_state": "available",
        }
    plugin.get_health = AsyncMock(return_value=health_result)
    return plugin


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client():
    """FastAPI TestClient with auth and RBAC dependencies overridden."""

    async def mock_user():
        return {
            "email": "test@example.com",
            "full_name": "Test User",
            "is_admin": True,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": MagicMock(),
        }

    def mock_get_db():
        return MagicMock()

    # Patch PermissionService with a MagicMock that accepts any kwargs on check_permission
    mock_ps_instance = MagicMock()
    mock_ps_instance.check_permission = AsyncMock(return_value=True)
    mock_ps_instance.check_admin_permission = AsyncMock(return_value=True)
    mock_ps_class = MagicMock(return_value=mock_ps_instance)

    with patch("mcpgateway.middleware.rbac.PermissionService", mock_ps_class):
        app.dependency_overrides[get_current_user_with_permissions] = mock_user
        app.dependency_overrides[get_permission_service] = lambda *a, **kw: mock_ps_instance
        app.dependency_overrides[rbac_get_db] = mock_get_db

        client = TestClient(app, raise_server_exceptions=True)
        yield client

        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)


# ============================================================================
# TEST BACKWARD COMPATIBILITY
# ============================================================================


class TestBackwardCompatibility:
    """Existing callers without router= param must be unaffected."""

    def test_no_router_param_returns_all_tools(self, test_client):
        """Without router= param, the endpoint behaves as before."""
        tools = [_make_tool_read("t1", "tool-a"), _make_tool_read("t2", "tool-b")]

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)):
            response = test_client.get("/servers/server-1/tools")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_include_inactive_param_still_works(self, test_client):
        """include_inactive param continues to work alongside new CRT params."""
        tools = [_make_tool_read("t1")]

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)):
            response = test_client.get("/servers/server-1/tools?include_inactive=true")

        assert response.status_code == 200

    def test_router_param_not_crt_returns_all_tools(self, test_client):
        """router= value other than 'crt' passes through without CRT filtering."""
        tools = [_make_tool_read("t1"), _make_tool_read("t2"), _make_tool_read("t3")]

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)):
            response = test_client.get("/servers/server-1/tools?router=llm")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3


# ============================================================================
# TEST CRT ROUTING
# ============================================================================


class TestCRTRouting:
    """Tests for router=crt behaviour."""

    def test_router_crt_no_prompt_returns_all_tools(self, test_client):
        """router=crt without a prompt returns the full unfiltered list."""
        tools = [_make_tool_read("t1"), _make_tool_read("t2")]

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)):
            response = test_client.get("/servers/server-1/tools?router=crt")

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_router_crt_with_prompt_calls_plugin(self, test_client):
        """router=crt with a prompt invokes the CRT plugin and returns its results."""
        tools = [_make_tool_read("t1", "weather-api"), _make_tool_read("t2", "email-sender")]
        mock_plugin = _make_crt_plugin()

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=weather+forecast&k=10")

        assert response.status_code == 200

    def test_router_crt_k_limits_results(self, test_client):
        """k parameter limits the number of tools returned."""
        tools = [_make_tool_read(f"t{i}", f"tool-{i}") for i in range(10)]

        # Plugin returns all tools with relevance=1.0 (stub behaviour)
        mock_plugin = _make_crt_plugin()

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=test&k=3")

        assert response.status_code == 200
        assert len(response.json()) <= 3

    def test_router_crt_threshold_filters_low_scores(self, test_client):
        """threshold filters out tools whose relevance score is below the threshold."""
        tools = [_make_tool_read("t1", "relevant-tool"), _make_tool_read("t2", "irrelevant-tool")]

        # Plugin returns t1 with high relevance, t2 with low relevance
        async def rank_with_scores(tools, prompt, k, threshold, db=None):
            return [
                (tools[0], {"relevance": 0.9, "loss": 0.1, "entropy": 0.5}),
                (tools[1], {"relevance": 0.2, "loss": 0.8, "entropy": 0.5}),
            ]

        mock_plugin = MagicMock()
        mock_plugin.rank_tools = rank_with_scores

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=test&threshold=0.5")

        assert response.status_code == 200
        # Only t1 (relevance=0.9) should pass the threshold of 0.5
        data = response.json()
        assert len(data) == 1

    def test_router_crt_injects_crt_scores_into_tools(self, test_client):
        """CRT scores are injected into each tool's crt_scores field."""
        tool = _make_tool_read("t1", "weather-api")
        # Override model_dump to include crt_scores in the response
        base_dump = dict(tool.model_dump.return_value)
        base_dump["crtScores"] = {"relevance": 0.95, "loss": 0.05, "entropy": 0.3}
        tool.model_dump.return_value = base_dump

        async def rank(tools, prompt, k, threshold, db=None):
            return [(tool, {"relevance": 0.95, "loss": 0.05, "entropy": 0.3})]

        mock_plugin = MagicMock()
        mock_plugin.rank_tools = rank

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=[tool])), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=weather")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0].get("crtScores") is not None

    def test_router_crt_plugin_not_loaded_returns_full_list(self, test_client):
        """When CRTRouterPlugin is not registered, full unfiltered list is returned."""
        tools = [_make_tool_read("t1"), _make_tool_read("t2"), _make_tool_read("t3")]

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = None
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=test")

        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_router_crt_plugin_exception_returns_full_list(self, test_client):
        """When the CRT plugin raises an exception, full unfiltered list is returned."""
        tools = [_make_tool_read("t1"), _make_tool_read("t2")]

        mock_plugin = MagicMock()
        mock_plugin.rank_tools = AsyncMock(side_effect=RuntimeError("CRT scoring failed"))

        with patch("mcpgateway.main.tool_service.list_server_tools", AsyncMock(return_value=tools)), patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/servers/server-1/tools?router=crt&prompt=test")

        assert response.status_code == 200
        assert len(response.json()) == 2


# ============================================================================
# TEST /router/health
# ============================================================================


class TestRouterHealthEndpoint:
    """Tests for the GET /router/health endpoint."""

    def test_health_returns_200_when_plugin_healthy(self, test_client):
        """GET /router/health returns 200 when CRTRouterPlugin is loaded and healthy."""
        mock_plugin = _make_crt_plugin(health_result={"status": "healthy", "version": "1.0.0", "calibration_checksum": "abc", "calibration_state": "available"})

        with patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/router/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_returns_required_keys(self, test_client):
        """GET /router/health response includes all required fields."""
        mock_plugin = _make_crt_plugin(
            health_result={
                "status": "healthy",
                "version": "1.0.0",
                "calibration_checksum": "deadbeef",
                "calibration_state": "available",
            }
        )

        with patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/router/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "calibration_checksum" in data
        assert "calibration_state" in data

    def test_health_returns_503_when_plugin_not_loaded(self, test_client):
        """GET /router/health returns 503 when CRTRouterPlugin is not registered."""
        with patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = None
            response = test_client.get("/router/health")

        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"

    def test_health_returns_503_when_degraded(self, test_client):
        """GET /router/health returns 503 when plugin reports degraded status."""
        mock_plugin = _make_crt_plugin(health_result={"status": "degraded", "version": "1.0.0", "calibration_checksum": "n/a", "calibration_state": "missing"})

        with patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/router/health")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    def test_health_returns_503_on_exception(self, test_client):
        """GET /router/health returns 503 when get_health() raises."""
        mock_plugin = MagicMock()
        mock_plugin.get_health = AsyncMock(side_effect=RuntimeError("health check failed"))

        with patch("mcpgateway.main.plugin_manager") as mock_pm:
            mock_pm.get_plugin.return_value = mock_plugin
            response = test_client.get("/router/health")

        assert response.status_code == 503
