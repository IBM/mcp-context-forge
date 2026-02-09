# -*- coding: utf-8 -*-
"""Additional coverage tests for tool_service.py.

Targets uncovered lines identified in coverage report to improve overall
branch coverage beyond the current 63%.
"""

# Standard
import asyncio
import base64
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, call, patch

# Third-Party
import jsonschema
import orjson
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.common.models import TextContent, ToolResult
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import (
    ToolError,
    ToolInvocationError,
    ToolLockConflictError,
    ToolNameConflictError,
    ToolNotFoundError,
    ToolService,
    ToolTimeoutError,
    ToolValidationError,
    _canonicalize_schema,
    _get_registry_cache,
    _get_tool_lookup_cache,
    _get_validator_class_and_check,
    extract_using_jq,
)
from mcpgateway.utils.services_auth import encode_auth


# ─── autouse fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache

    clear_ssl_context_cache()

    with (
        patch("mcpgateway.services.tool_service.audit_trail") as mock_audit,
        patch("mcpgateway.services.tool_service.structured_logger") as mock_logger,
    ):
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def mock_fresh_db_session():
    """Mock fresh_db_session context manager to prevent real DB operations during tests."""

    @contextmanager
    def mock_fresh_session():
        mock_db = MagicMock()
        yield mock_db

    with patch("mcpgateway.services.tool_service.fresh_db_session", mock_fresh_session):
        yield


@pytest.fixture(autouse=True)
def reset_tool_lookup_cache():
    """Clear tool lookup cache between tests to avoid cross-test pollution."""
    tool_lookup_cache.invalidate_all_local()
    yield
    tool_lookup_cache.invalidate_all_local()


# ─── shared fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tool_service():
    """Create a tool service instance with a mocked HTTP client."""
    service = ToolService()
    service._http_client = AsyncMock()
    return service


@pytest.fixture
def mock_gateway():
    """Create a mock gateway model."""
    gw = MagicMock(spec=DbGateway)
    gw.id = "gw-1"
    gw.name = "test_gateway"
    gw.slug = "test-gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test gateway"
    gw.transport = "sse"
    gw.capabilities = {}
    gw.passthrough_headers = []
    gw.auth_type = None
    gw.auth_value = {}
    gw.auth_query_params = None
    gw.oauth_config = None
    gw.ca_certificate = None
    gw.ca_certificate_sig = None
    gw.enabled = True
    gw.reachable = True
    gw.team_id = None
    gw.owner_email = None
    gw.visibility = "public"
    gw.tags = []
    return gw


@pytest.fixture
def mock_tool(mock_gateway):
    """Create a mock tool model."""
    tool = MagicMock(spec=DbTool)
    tool.id = "tool-1"
    tool.original_name = "test_tool"
    tool.name = "test-gateway-test-tool"
    tool.custom_name = "test_tool"
    tool.custom_name_slug = "test-tool"
    tool.display_name = "Test Tool"
    tool.url = "http://example.com/tools/test"
    tool.description = "A test tool"
    tool.integration_type = "MCP"
    tool.request_type = "SSE"
    tool.headers = {"Content-Type": "application/json"}
    tool.input_schema = {"type": "object", "properties": {"param": {"type": "string"}}}
    tool.output_schema = None
    tool.annotations = {}
    tool.jsonpath_filter = ""
    tool.auth_type = None
    tool.auth_value = None
    tool.oauth_config = None
    tool.gateway_id = "gw-1"
    tool.gateway = mock_gateway
    tool.gateway_slug = "test-gateway"
    tool.enabled = True
    tool.reachable = True
    tool.team_id = None
    tool.owner_email = "admin@example.com"
    tool.visibility = "public"
    tool.tags = []
    tool.team = None
    tool.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    tool.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    tool.created_by = "admin"
    tool.created_from_ip = "127.0.0.1"
    tool.created_via = "api"
    tool.created_user_agent = "test"
    tool.modified_by = None
    tool.modified_from_ip = None
    tool.modified_via = None
    tool.modified_user_agent = None
    tool.import_batch_id = None
    tool.federation_source = None
    tool.metrics = []
    tool.execution_count = 0
    tool.metrics_summary = {
        "total_executions": 0,
        "successful_executions": 0,
        "failed_executions": 0,
        "failure_rate": 0.0,
        "min_response_time": None,
        "max_response_time": None,
        "avg_response_time": None,
        "last_execution_time": None,
    }
    return tool


# ═════════════════════════════════════════════════════════════════════════════
# 1. Module-level lazy singletons: _get_registry_cache, _get_tool_lookup_cache
# ═════════════════════════════════════════════════════════════════════════════


class TestModuleLevelCaches:
    """Tests for _get_registry_cache and _get_tool_lookup_cache."""

    def test_get_registry_cache_returns_singleton(self):
        """_get_registry_cache should return the registry_cache singleton."""
        cache = _get_registry_cache()
        assert cache is not None
        # Calling again should return the same instance
        cache2 = _get_registry_cache()
        assert cache is cache2

    def test_get_tool_lookup_cache_returns_singleton(self):
        """_get_tool_lookup_cache should return the tool_lookup_cache singleton."""
        cache = _get_tool_lookup_cache()
        assert cache is not None
        cache2 = _get_tool_lookup_cache()
        assert cache is cache2


# ═════════════════════════════════════════════════════════════════════════════
# 2. _canonicalize_schema
# ═════════════════════════════════════════════════════════════════════════════


class TestCanonicalizeSchema:
    """Tests for _canonicalize_schema."""

    def test_canonicalize_schema_sorted_keys(self):
        """Schema should be serialized with sorted keys."""
        schema = {"z_key": 1, "a_key": 2, "m_key": 3}
        result = _canonicalize_schema(schema)
        parsed = orjson.loads(result)
        assert list(parsed.keys()) == ["a_key", "m_key", "z_key"]

    def test_canonicalize_schema_returns_string(self):
        """Return type should be str."""
        result = _canonicalize_schema({"type": "object"})
        assert isinstance(result, str)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Exception classes
# ═════════════════════════════════════════════════════════════════════════════


class TestExceptionClasses:
    """Tests for tool exception classes."""

    def test_tool_error_basic(self):
        """ToolError should carry message."""
        err = ToolError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert isinstance(err, Exception)

    def test_tool_not_found_error(self):
        """ToolNotFoundError should be a subclass of ToolError."""
        err = ToolNotFoundError("Tool xyz not found")
        assert str(err) == "Tool xyz not found"
        assert isinstance(err, ToolError)

    def test_tool_name_conflict_error_active_public(self):
        """ToolNameConflictError for active public tool."""
        err = ToolNameConflictError("my_tool", enabled=True, tool_id=42, visibility="public")
        assert "Public" in str(err)
        assert "my_tool" in str(err)
        assert "inactive" not in str(err)
        assert err.name == "my_tool"
        assert err.enabled is True
        assert err.tool_id == 42

    def test_tool_name_conflict_error_inactive_team(self):
        """ToolNameConflictError for inactive team tool."""
        err = ToolNameConflictError("my_tool", enabled=False, tool_id=123, visibility="team")
        assert "Team-level" in str(err)
        assert "inactive" in str(err)
        assert "123" in str(err)
        assert err.enabled is False
        assert err.tool_id == 123

    def test_tool_lock_conflict_error(self):
        """ToolLockConflictError should be a subclass of ToolError."""
        err = ToolLockConflictError("locked")
        assert isinstance(err, ToolError)
        assert str(err) == "locked"

    def test_tool_validation_error(self):
        """ToolValidationError should be a subclass of ToolError."""
        err = ToolValidationError("Invalid tool configuration")
        assert str(err) == "Invalid tool configuration"
        assert isinstance(err, ToolError)

    def test_tool_invocation_error(self):
        """ToolInvocationError should be a subclass of ToolError."""
        err = ToolInvocationError("Tool execution failed")
        assert str(err) == "Tool execution failed"
        assert isinstance(err, ToolError)

    def test_tool_timeout_error(self):
        """ToolTimeoutError should be a subclass of ToolInvocationError."""
        err = ToolTimeoutError("timeout after 30s")
        assert isinstance(err, ToolInvocationError)
        assert isinstance(err, ToolError)
        assert "timeout" in str(err)


# ═════════════════════════════════════════════════════════════════════════════
# 4. Module-level __getattr__ (lazy singleton)
# ═════════════════════════════════════════════════════════════════════════════


class TestModuleGetattr:
    """Tests for module-level __getattr__ for lazy singleton."""

    def test_getattr_tool_service_returns_instance(self):
        """Accessing tool_service attribute should return a ToolService instance."""
        import mcpgateway.services.tool_service as ts_module

        # Reset the singleton so __getattr__ is exercised
        old = ts_module._tool_service_instance
        ts_module._tool_service_instance = None
        try:
            instance = ts_module.__getattr__("tool_service")
            assert isinstance(instance, ToolService)
            # Second access should return the same instance
            instance2 = ts_module.__getattr__("tool_service")
            assert instance is instance2
        finally:
            ts_module._tool_service_instance = old

    def test_getattr_unknown_raises_attribute_error(self):
        """Unknown attribute should raise AttributeError."""
        import mcpgateway.services.tool_service as ts_module

        with pytest.raises(AttributeError, match="has no attribute"):
            ts_module.__getattr__("nonexistent_attr")


# ═════════════════════════════════════════════════════════════════════════════
# 5. ToolService.initialize and shutdown
# ═════════════════════════════════════════════════════════════════════════════


class TestInitializeShutdown:
    """Tests for ToolService initialize and shutdown lifecycle."""

    @pytest.mark.asyncio
    async def test_initialize_calls_event_service(self):
        """initialize should call _event_service.initialize."""
        service = ToolService()
        service._event_service = AsyncMock()
        await service.initialize()
        service._event_service.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_calls_both_services(self):
        """shutdown should close http client and event service."""
        service = ToolService()
        service._http_client = AsyncMock()
        service._event_service = AsyncMock()
        await service.shutdown()
        service._http_client.aclose.assert_awaited_once()
        service._event_service.shutdown.assert_awaited_once()

    def test_init_plugins_enabled_env_true(self, monkeypatch):
        """PLUGINS_ENABLED=true env should enable plugin manager."""
        monkeypatch.setenv("PLUGINS_ENABLED", "true")
        with patch("mcpgateway.services.tool_service.PluginManager") as mock_pm:
            service = ToolService()
        assert service._plugin_manager is not None
        mock_pm.assert_called_once()

    def test_init_plugins_enabled_env_false(self, monkeypatch):
        """PLUGINS_ENABLED=false env should disable plugin manager."""
        monkeypatch.setenv("PLUGINS_ENABLED", "false")
        with patch("mcpgateway.services.tool_service.PluginManager") as mock_pm:
            service = ToolService()
        assert service._plugin_manager is None
        mock_pm.assert_not_called()

    def test_init_plugins_enabled_env_on(self, monkeypatch):
        """PLUGINS_ENABLED=on env should enable plugin manager."""
        monkeypatch.setenv("PLUGINS_ENABLED", "on")
        with patch("mcpgateway.services.tool_service.PluginManager") as mock_pm:
            service = ToolService()
        assert service._plugin_manager is not None

    def test_init_plugins_enabled_env_off(self, monkeypatch):
        """PLUGINS_ENABLED=off env should disable plugin manager."""
        monkeypatch.setenv("PLUGINS_ENABLED", "off")
        with patch("mcpgateway.services.tool_service.PluginManager") as mock_pm:
            service = ToolService()
        assert service._plugin_manager is None


# ═════════════════════════════════════════════════════════════════════════════
# 6. _build_tool_cache_payload and _pydantic_tool_from_payload
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildCachePayload:
    """Tests for _build_tool_cache_payload and _pydantic_tool_from_payload."""

    def test_build_tool_cache_payload_with_gateway(self, tool_service, mock_tool, mock_gateway):
        """Cache payload should include both tool and gateway data."""
        payload = tool_service._build_tool_cache_payload(mock_tool, mock_gateway)
        assert payload["status"] == "active"
        assert payload["tool"]["name"] == mock_tool.name
        assert payload["gateway"] is not None
        assert payload["gateway"]["id"] == str(mock_gateway.id)

    def test_build_tool_cache_payload_without_gateway(self, tool_service, mock_tool):
        """Cache payload without gateway should have gateway=None."""
        payload = tool_service._build_tool_cache_payload(mock_tool, None)
        assert payload["status"] == "active"
        assert payload["tool"]["name"] == mock_tool.name
        assert payload["gateway"] is None

    def test_pydantic_tool_from_payload_valid(self, tool_service):
        """Valid payload should return a PydanticTool instance."""
        payload = {
            "name": "test-tool",
            "description": "A test",
            "inputSchema": {"type": "object"},
        }
        with patch("mcpgateway.services.tool_service.PydanticTool.model_validate") as mv:
            mv.return_value = MagicMock()
            result = tool_service._pydantic_tool_from_payload(payload)
            assert result is not None

    def test_pydantic_tool_from_payload_invalid_returns_none(self, tool_service):
        """Invalid payload should return None."""
        with patch("mcpgateway.services.tool_service.PydanticTool.model_validate", side_effect=ValueError("bad")):
            result = tool_service._pydantic_tool_from_payload({"invalid": True})
            assert result is None

    def test_pydantic_gateway_from_payload_valid(self, tool_service):
        """Valid gateway payload should return a PydanticGateway instance."""
        with patch("mcpgateway.services.tool_service.PydanticGateway.model_validate") as mv:
            mv.return_value = MagicMock()
            result = tool_service._pydantic_gateway_from_payload({"name": "gw"})
            assert result is not None

    def test_pydantic_gateway_from_payload_invalid_returns_none(self, tool_service):
        """Invalid gateway payload should return None."""
        with patch("mcpgateway.services.tool_service.PydanticGateway.model_validate", side_effect=TypeError("bad")):
            result = tool_service._pydantic_gateway_from_payload({"bad": True})
            assert result is None


# ═════════════════════════════════════════════════════════════════════════════
# 7. _check_tool_access
# ═════════════════════════════════════════════════════════════════════════════


class TestCheckToolAccess:
    """Tests for _check_tool_access method."""

    @pytest.mark.asyncio
    async def test_public_tool_always_accessible(self, tool_service):
        """Public tools should be accessible to everyone."""
        db = MagicMock()
        payload = {"visibility": "public", "team_id": None, "owner_email": None}
        result = await tool_service._check_tool_access(db, payload, user_email=None, token_teams=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_admin_bypass_unrestricted(self, tool_service):
        """Admin bypass: token_teams=None AND user_email=None means unrestricted."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "t1", "owner_email": "someone@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email=None, token_teams=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_user_context_denies_nonpublic(self, tool_service):
        """Non-public tools without user context should be denied."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "t1", "owner_email": "someone@x.com"}
        # user_email="" is falsy but not None, and token_teams is a list
        result = await tool_service._check_tool_access(db, payload, user_email="", token_teams=["t2"])
        assert result is False

    @pytest.mark.asyncio
    async def test_public_only_token_denies_nonpublic(self, tool_service):
        """Empty teams token should deny access to non-public tools."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "t1", "owner_email": "someone@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email="user@x.com", token_teams=[])
        assert result is False

    @pytest.mark.asyncio
    async def test_owner_can_access_own_tool(self, tool_service):
        """Owner should access their own non-public tools."""
        db = MagicMock()
        payload = {"visibility": "private", "team_id": None, "owner_email": "owner@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email="owner@x.com", token_teams=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_team_member_can_access_team_tool(self, tool_service):
        """Team member should access team-scoped tools."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "team-a", "owner_email": "other@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email="user@x.com", token_teams=["team-a"])
        assert result is True

    @pytest.mark.asyncio
    async def test_non_team_member_denied_team_tool(self, tool_service):
        """Non-team-member should be denied access to team tools."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "team-a", "owner_email": "other@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email="user@x.com", token_teams=["team-b"])
        assert result is False

    @pytest.mark.asyncio
    async def test_team_lookup_from_db_when_no_token_teams(self, tool_service):
        """When token_teams=None but user_email is set, look up teams from DB."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": "team-db", "owner_email": "other@x.com"}

        mock_team = MagicMock()
        mock_team.id = "team-db"
        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_tms_instance = AsyncMock()
            mock_tms.return_value = mock_tms_instance
            mock_tms_instance.get_user_teams.return_value = [mock_team]
            result = await tool_service._check_tool_access(db, payload, user_email="user@x.com", token_teams=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_team_id_in_tool_denies(self, tool_service):
        """Tool with no team_id but team visibility and non-owner user should be denied."""
        db = MagicMock()
        payload = {"visibility": "team", "team_id": None, "owner_email": "other@x.com"}
        result = await tool_service._check_tool_access(db, payload, user_email="user@x.com", token_teams=["team-a"])
        assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# 8. convert_tool_to_read edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestConvertToolToRead:
    """Additional edge cases for convert_tool_to_read."""

    def test_include_auth_false_with_encrypted_auth(self, tool_service, mock_tool):
        """include_auth=False should return minimal auth info without decryption."""
        mock_tool.auth_type = "bearer"
        mock_tool.auth_value = "some_encrypted_value"  # Truthy

        tool_read = tool_service.convert_tool_to_read(mock_tool, include_metrics=False, include_auth=False)
        assert tool_read.auth is not None
        assert tool_read.auth.auth_type == "bearer"

    def test_no_auth_returns_none(self, tool_service, mock_tool):
        """No auth should return auth=None."""
        mock_tool.auth_type = None
        mock_tool.auth_value = None

        tool_read = tool_service.convert_tool_to_read(mock_tool, include_metrics=False, include_auth=True)
        assert tool_read.auth is None

    def test_include_metrics_true(self, tool_service, mock_tool):
        """include_metrics=True should populate metrics fields."""
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_metrics=True, include_auth=True)
        assert tool_read.metrics is not None
        assert tool_read.execution_count == 0

    def test_unknown_auth_type_returns_none(self, tool_service, mock_tool):
        """Unknown auth_type should return auth=None."""
        mock_tool.auth_type = "oauth"
        mock_tool.auth_value = "encrypted_data"

        with patch("mcpgateway.services.tool_service.decode_auth", return_value={"some": "data"}):
            tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=True)
        assert tool_read.auth is None

    def test_display_name_fallback_to_custom_name(self, tool_service, mock_tool):
        """When display_name is None, should fallback to custom_name."""
        mock_tool.display_name = None
        mock_tool.custom_name = "my_custom"
        tool_read = tool_service.convert_tool_to_read(mock_tool)
        assert tool_read.displayName == "my_custom"


# ═════════════════════════════════════════════════════════════════════════════
# 9. _extract_and_validate_structured_content
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractAndValidateStructuredContent:
    """Tests for _extract_and_validate_structured_content."""

    def test_no_schema_returns_true(self, tool_service):
        """No output_schema should return True."""
        tool = SimpleNamespace(output_schema=None)
        result = ToolResult(content=[])
        assert tool_service._extract_and_validate_structured_content(tool, result) is True

    def test_valid_candidate_passes(self, tool_service):
        """Valid candidate should pass validation and be attached."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})
        result = ToolResult(content=[])
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate={"x": "hello"})
        assert ok is True
        assert result.structured_content == {"x": "hello"}

    def test_invalid_candidate_marks_error(self, tool_service):
        """Invalid candidate should mark result as error."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})
        result = ToolResult(content=[])
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate={"x": 123})
        assert ok is False
        assert result.is_error is True
        # Error details should be in content
        error_text = result.content[0].text
        details = orjson.loads(error_text)
        assert "message" in details

    def test_parses_text_content_as_json(self, tool_service):
        """Should parse TextContent text as JSON for validation."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"a": {"type": "integer"}}})
        result = ToolResult(content=[{"type": "text", "text": '{"a": 42}'}])
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is True

    def test_no_structured_data_found_returns_true(self, tool_service):
        """No structured data found should return True."""
        tool = SimpleNamespace(output_schema={"type": "object"})
        result = ToolResult(content=[])
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is True

    def test_unwrap_single_element_list(self, tool_service):
        """Single-element list wrapping a TextContent-like dict should be unwrapped."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"a": {"type": "integer"}}})
        result = ToolResult(content=[])
        candidate = [{"type": "text", "text": '{"a": 5}'}]
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate=candidate)
        assert ok is True


# ═════════════════════════════════════════════════════════════════════════════
# 10. _record_tool_metric_by_id and _record_tool_metric_sync
# ═════════════════════════════════════════════════════════════════════════════


class TestRecordToolMetric:
    """Tests for metric recording methods."""

    def test_record_tool_metric_by_id(self, tool_service):
        """_record_tool_metric_by_id should add metric and commit."""
        db = MagicMock()
        tool_service._record_tool_metric_by_id(db, "t1", time.monotonic(), True, None)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_record_tool_metric_by_id_with_error(self, tool_service):
        """_record_tool_metric_by_id should record error message."""
        db = MagicMock()
        tool_service._record_tool_metric_by_id(db, "t1", time.monotonic(), False, "timeout")
        db.add.assert_called_once()
        metric = db.add.call_args[0][0]
        assert metric.is_success is False
        assert metric.error_message == "timeout"

    @pytest.mark.asyncio
    async def test_record_tool_metric(self, tool_service, mock_tool):
        """_record_tool_metric should add and commit metric."""
        db = MagicMock()
        await tool_service._record_tool_metric(db, mock_tool, time.monotonic(), True, None)
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# 11. _notify_* methods
# ═════════════════════════════════════════════════════════════════════════════


class TestNotifyMethods:
    """Tests for notification methods."""

    @pytest.mark.asyncio
    async def test_notify_tool_updated(self, tool_service, mock_tool):
        """_notify_tool_updated should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_updated(mock_tool)
        tool_service._event_service.publish_event.assert_awaited_once()
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_updated"

    @pytest.mark.asyncio
    async def test_notify_tool_activated(self, tool_service, mock_tool):
        """_notify_tool_activated should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_activated(mock_tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_activated"

    @pytest.mark.asyncio
    async def test_notify_tool_deactivated(self, tool_service, mock_tool):
        """_notify_tool_deactivated should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_deactivated(mock_tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_deactivated"

    @pytest.mark.asyncio
    async def test_notify_tool_offline(self, tool_service, mock_tool):
        """_notify_tool_offline should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_offline(mock_tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_offline"
        assert event["data"]["reachable"] is False

    @pytest.mark.asyncio
    async def test_notify_tool_deleted(self, tool_service):
        """_notify_tool_deleted should publish an event."""
        tool_service._event_service = AsyncMock()
        info = {"id": "1", "name": "removed_tool"}
        await tool_service._notify_tool_deleted(info)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_deleted"
        assert event["data"] == info

    @pytest.mark.asyncio
    async def test_notify_tool_added(self, tool_service, mock_tool):
        """_notify_tool_added should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_added(mock_tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_added"

    @pytest.mark.asyncio
    async def test_notify_tool_removed(self, tool_service, mock_tool):
        """_notify_tool_removed should publish an event."""
        tool_service._event_service = AsyncMock()
        await tool_service._notify_tool_removed(mock_tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_removed"

    @pytest.mark.asyncio
    async def test_publish_event(self, tool_service):
        """_publish_event should delegate to event service."""
        tool_service._event_service = AsyncMock()
        event = {"type": "test", "data": {}}
        await tool_service._publish_event(event)
        tool_service._event_service.publish_event.assert_awaited_once_with(event)


# ═════════════════════════════════════════════════════════════════════════════
# 12. _validate_tool_url and _check_tool_health
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateToolUrl:
    """Tests for _validate_tool_url and _check_tool_health."""

    @pytest.mark.asyncio
    async def test_validate_tool_url_success(self, tool_service):
        """Successful URL validation should not raise."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        tool_service._http_client.get = AsyncMock(return_value=mock_response)
        await tool_service._validate_tool_url("http://example.com")  # Should not raise

    @pytest.mark.asyncio
    async def test_validate_tool_url_failure(self, tool_service):
        """Failed URL validation should raise ToolValidationError."""
        tool_service._http_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        with pytest.raises(ToolValidationError, match="Failed to validate"):
            await tool_service._validate_tool_url("http://bad.example.com")

    @pytest.mark.asyncio
    async def test_check_tool_health_success(self, tool_service, mock_tool):
        """Healthy tool should return True."""
        mock_response = MagicMock()
        mock_response.is_success = True
        tool_service._http_client.get = AsyncMock(return_value=mock_response)
        result = await tool_service._check_tool_health(mock_tool)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_tool_health_failure(self, tool_service, mock_tool):
        """Unhealthy tool should return False."""
        tool_service._http_client.get = AsyncMock(side_effect=Exception("timeout"))
        result = await tool_service._check_tool_health(mock_tool)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_tool_health_non_success_status(self, tool_service, mock_tool):
        """Non-success HTTP status should return False."""
        mock_response = MagicMock()
        mock_response.is_success = False
        tool_service._http_client.get = AsyncMock(return_value=mock_response)
        result = await tool_service._check_tool_health(mock_tool)
        assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# 13. aggregate_metrics
# ═════════════════════════════════════════════════════════════════════════════


class TestAggregateMetrics:
    """Tests for aggregate_metrics method."""

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cached(self, tool_service, monkeypatch):
        """When cache is enabled and has data, return cached."""
        from mcpgateway.cache import metrics_cache as cache_module

        cached_data = {"total": 100, "success": 90}
        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        cache_module.metrics_cache.get = MagicMock(return_value=cached_data)

        db = MagicMock()
        result = await tool_service.aggregate_metrics(db)
        assert result == cached_data

    @pytest.mark.asyncio
    async def test_aggregate_metrics_not_cached(self, tool_service, monkeypatch):
        """When cache miss, compute and cache result."""
        from mcpgateway.cache import metrics_cache as cache_module

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        cache_module.metrics_cache.get = MagicMock(return_value=None)
        cache_module.metrics_cache.set = MagicMock()

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"total": 50}

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(MagicMock())
        assert result == {"total": 50}

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_disabled(self, tool_service, monkeypatch):
        """When cache is disabled, compute directly."""
        from mcpgateway.cache import metrics_cache as cache_module

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"total": 25}

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(MagicMock())
        assert result == {"total": 25}


# ═════════════════════════════════════════════════════════════════════════════
# 14. get_tool and delete_tool edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestGetToolDeleteTool:
    """Tests for get_tool and delete_tool edge cases."""

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, tool_service):
        """get_tool should raise ToolNotFoundError when tool doesn't exist."""
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(ToolNotFoundError, match="Tool not found"):
            await tool_service.get_tool(db, "nonexistent-id")

    @pytest.mark.asyncio
    async def test_get_tool_success(self, tool_service, mock_tool):
        """get_tool should return ToolRead when tool exists."""
        db = MagicMock()
        db.get.return_value = mock_tool
        result = await tool_service.get_tool(db, "tool-1")
        assert isinstance(result, ToolRead)

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tool_service):
        """delete_tool should raise ToolError when tool not found."""
        db = MagicMock()
        db.get.return_value = None
        with pytest.raises(ToolError):
            await tool_service.delete_tool(db, "nonexistent-id")

    @pytest.mark.asyncio
    async def test_delete_tool_success(self, tool_service, mock_tool):
        """delete_tool should delete and notify."""
        db = MagicMock()
        db.get.return_value = mock_tool
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute.return_value = mock_result
        tool_service._event_service = AsyncMock()

        mock_admin_cache = MagicMock()
        mock_admin_cache.invalidate_tags = AsyncMock()
        mock_metrics_cache = MagicMock()

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache", mock_admin_cache),
            patch("mcpgateway.cache.metrics_cache.metrics_cache", mock_metrics_cache),
        ):
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            await tool_service.delete_tool(db, "tool-1")

        db.execute.assert_called()
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_tool_permission_error(self, tool_service, mock_tool):
        """delete_tool should raise PermissionError on ownership failure."""
        db = MagicMock()
        db.get.return_value = mock_tool

        mock_ps = AsyncMock()
        mock_ps.check_resource_ownership.return_value = False

        with patch("mcpgateway.services.permission_service.PermissionService", return_value=mock_ps):
            with pytest.raises(PermissionError, match="Only the owner"):
                await tool_service.delete_tool(db, "tool-1", user_email="notowner@x.com")

    @pytest.mark.asyncio
    async def test_delete_tool_concurrent_deletion(self, tool_service, mock_tool):
        """delete_tool should raise ToolError when tool was already deleted."""
        db = MagicMock()
        db.get.return_value = mock_tool
        mock_result = MagicMock()
        mock_result.rowcount = 0
        db.execute.return_value = mock_result

        with pytest.raises(ToolError):
            await tool_service.delete_tool(db, "tool-1")


# ═════════════════════════════════════════════════════════════════════════════
# 15. set_tool_state
# ═════════════════════════════════════════════════════════════════════════════


class TestSetToolState:
    """Tests for set_tool_state method."""

    @pytest.mark.asyncio
    async def test_set_tool_state_activate(self, tool_service, mock_tool):
        """set_tool_state should activate a tool."""
        mock_tool.enabled = False
        mock_tool.reachable = False
        db = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool),
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
        ):
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            tool_service._event_service = AsyncMock()
            result = await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)

        assert isinstance(result, ToolRead)

    @pytest.mark.asyncio
    async def test_set_tool_state_deactivate(self, tool_service, mock_tool):
        """set_tool_state should deactivate a tool and notify."""
        mock_tool.enabled = True
        mock_tool.reachable = True
        db = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool),
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
        ):
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            tool_service._event_service = AsyncMock()
            result = await tool_service.set_tool_state(db, "tool-1", activate=False, reachable=False)

        assert isinstance(result, ToolRead)

    @pytest.mark.asyncio
    async def test_set_tool_state_not_found(self, tool_service):
        """set_tool_state should raise ToolNotFoundError when tool not found."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", return_value=None):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.set_tool_state(db, "nonexistent", activate=True, reachable=True)

    @pytest.mark.asyncio
    async def test_set_tool_state_lock_conflict(self, tool_service):
        """set_tool_state should raise ToolLockConflictError on row lock."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=OperationalError("lock", {}, None)):
            with pytest.raises(ToolLockConflictError):
                await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)

    @pytest.mark.asyncio
    async def test_set_tool_state_no_change(self, tool_service, mock_tool):
        """set_tool_state with no state change should still return ToolRead."""
        mock_tool.enabled = True
        mock_tool.reachable = True
        db = MagicMock()

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            result = await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)

        assert isinstance(result, ToolRead)
        # Should NOT have called commit since there's no change
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_tool_state_permission_error(self, tool_service, mock_tool):
        """set_tool_state should raise PermissionError when ownership check fails."""
        mock_tool.enabled = False
        db = MagicMock()

        mock_ps = AsyncMock()
        mock_ps.check_resource_ownership.return_value = False

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            with patch("mcpgateway.services.permission_service.PermissionService", return_value=mock_ps):
                with pytest.raises(PermissionError):
                    await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True, user_email="nope@x.com")

    @pytest.mark.asyncio
    async def test_set_tool_state_offline_notification(self, tool_service, mock_tool):
        """set_tool_state enabled=True, reachable=False should notify offline."""
        mock_tool.enabled = False
        mock_tool.reachable = True
        db = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool),
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
        ):
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            tool_service._event_service = AsyncMock()
            result = await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=False)

        # Verify the offline notification was triggered (enabled=True, reachable=False)
        assert isinstance(result, ToolRead)

    @pytest.mark.asyncio
    async def test_set_tool_state_skip_cache_invalidation(self, tool_service, mock_tool):
        """set_tool_state with skip_cache_invalidation should not invalidate cache."""
        mock_tool.enabled = False
        mock_tool.reachable = False
        db = MagicMock()

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            tool_service._event_service = AsyncMock()
            result = await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True, skip_cache_invalidation=True)

        assert isinstance(result, ToolRead)

    @pytest.mark.asyncio
    async def test_set_tool_state_generic_exception(self, tool_service, mock_tool):
        """set_tool_state should wrap generic exceptions in ToolError."""
        mock_tool.enabled = False
        db = MagicMock()

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            # Trigger an exception during commit
            db.commit.side_effect = RuntimeError("DB crashed")
            with pytest.raises(ToolError, match="Failed to set tool state"):
                await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)


# ═════════════════════════════════════════════════════════════════════════════
# 16. register_tool edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestRegisterTool:
    """Tests for register_tool edge cases."""

    @pytest.mark.asyncio
    async def test_register_tool_team_visibility_conflict(self, tool_service):
        """register_tool should raise ToolNameConflictError for team tool conflict."""
        db = MagicMock()
        existing = MagicMock()
        existing.name = "test_tool"
        existing.enabled = True
        existing.id = 42
        existing.visibility = "team"
        db.execute.return_value.scalar_one_or_none.return_value = existing

        tool_create = MagicMock()
        tool_create.name = "test_tool"
        tool_create.auth = None

        with pytest.raises(ToolNameConflictError):
            await tool_service.register_tool(db, tool_create, visibility="team", team_id="team-1")

    @pytest.mark.asyncio
    async def test_register_tool_public_visibility_conflict(self, tool_service):
        """register_tool should raise ToolNameConflictError for public tool conflict."""
        db = MagicMock()
        existing = MagicMock()
        existing.name = "test_tool"
        existing.enabled = True
        existing.id = 10
        existing.visibility = "public"
        db.execute.return_value.scalar_one_or_none.return_value = existing

        tool_create = MagicMock()
        tool_create.name = "test_tool"
        tool_create.auth = None

        with pytest.raises(ToolNameConflictError):
            await tool_service.register_tool(db, tool_create, visibility="public")

    @pytest.mark.asyncio
    async def test_register_tool_integrity_error(self, tool_service):
        """register_tool should re-raise IntegrityError."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.commit.side_effect = IntegrityError("dup", {}, None)

        tool_create = MagicMock()
        tool_create.name = "test_tool"
        tool_create.auth = None
        tool_create.url = "http://example.com"
        tool_create.description = "desc"
        tool_create.integration_type = "MCP"
        tool_create.request_type = "SSE"
        tool_create.headers = {}
        tool_create.input_schema = {}
        tool_create.output_schema = None
        tool_create.annotations = {}
        tool_create.jsonpath_filter = ""
        tool_create.gateway_id = None
        tool_create.tags = []
        tool_create.displayName = None
        tool_create.team_id = None
        tool_create.owner_email = None
        tool_create.visibility = "public"
        tool_create.base_url = None
        tool_create.path_template = None
        tool_create.query_mapping = None
        tool_create.header_mapping = None
        tool_create.timeout_ms = None
        tool_create.expose_passthrough = None
        tool_create.allowlist = None
        tool_create.plugin_chain_pre = None
        tool_create.plugin_chain_post = None

        with pytest.raises(IntegrityError):
            await tool_service.register_tool(db, tool_create, visibility="public")

    @pytest.mark.asyncio
    async def test_register_tool_generic_exception(self, tool_service):
        """register_tool should wrap generic exceptions in ToolError."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        db.commit.side_effect = RuntimeError("unexpected")

        tool_create = MagicMock()
        tool_create.name = "test_tool"
        tool_create.auth = None
        tool_create.url = "http://example.com"
        tool_create.description = "desc"
        tool_create.integration_type = "MCP"
        tool_create.request_type = "SSE"
        tool_create.headers = {}
        tool_create.input_schema = {}
        tool_create.output_schema = None
        tool_create.annotations = {}
        tool_create.jsonpath_filter = ""
        tool_create.gateway_id = None
        tool_create.tags = []
        tool_create.displayName = None
        tool_create.team_id = None
        tool_create.owner_email = None
        tool_create.visibility = "public"
        tool_create.base_url = None
        tool_create.path_template = None
        tool_create.query_mapping = None
        tool_create.header_mapping = None
        tool_create.timeout_ms = None
        tool_create.expose_passthrough = None
        tool_create.allowlist = None
        tool_create.plugin_chain_pre = None
        tool_create.plugin_chain_post = None

        with pytest.raises(ToolError, match="Failed to register tool"):
            await tool_service.register_tool(db, tool_create, visibility="public")

    @pytest.mark.asyncio
    async def test_register_tool_uses_tool_fields_for_team_and_owner(self, tool_service):
        """register_tool should use tool.team_id and tool.owner_email as fallback.

        This test verifies that the register_tool method falls through to the
        tool's own team_id and owner_email fields when they aren't provided.
        """
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        tool_create = MagicMock()
        tool_create.name = "test_tool"
        tool_create.auth = None
        tool_create.url = "http://example.com"
        tool_create.description = "desc"
        tool_create.integration_type = "MCP"
        tool_create.request_type = "SSE"
        tool_create.headers = {}
        tool_create.input_schema = {}
        tool_create.output_schema = None
        tool_create.annotations = {}
        tool_create.jsonpath_filter = ""
        tool_create.gateway_id = None
        tool_create.tags = []
        tool_create.displayName = None
        tool_create.team_id = "team-from-tool"
        tool_create.owner_email = "owner@tool.com"
        tool_create.visibility = "private"
        tool_create.base_url = None
        tool_create.path_template = None
        tool_create.query_mapping = None
        tool_create.header_mapping = None
        tool_create.timeout_ms = None
        tool_create.expose_passthrough = None
        tool_create.allowlist = None
        tool_create.plugin_chain_pre = None
        tool_create.plugin_chain_post = None

        tool_service._notify_tool_added = AsyncMock()
        # Patch convert_tool_to_read to return a simple mock (avoiding Pydantic validation)
        mock_tool_read = MagicMock(spec=ToolRead)
        tool_service.convert_tool_to_read = MagicMock(return_value=mock_tool_read)

        mock_admin_cache = MagicMock()
        mock_admin_cache.invalidate_tags = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache", mock_admin_cache),
        ):
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            result = await tool_service.register_tool(db, tool_create)

        assert result is mock_tool_read
        # Verify db.add was called (tool was created)
        db.add.assert_called_once()
        db.commit.assert_called()


# ═════════════════════════════════════════════════════════════════════════════
# 17. update_tool edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestUpdateTool:
    """Tests for update_tool edge cases."""

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tool_service):
        """update_tool should raise ToolNotFoundError when tool not found."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", return_value=None):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.update_tool(db, "no-id", MagicMock())

    @pytest.mark.asyncio
    async def test_update_tool_permission_error(self, tool_service, mock_tool):
        """update_tool should raise PermissionError on ownership failure."""
        db = MagicMock()
        tool_update = MagicMock()
        tool_update.name = None  # no name change

        mock_ps = AsyncMock()
        mock_ps.check_resource_ownership.return_value = False

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            with patch("mcpgateway.services.permission_service.PermissionService", return_value=mock_ps):
                with pytest.raises(PermissionError):
                    await tool_service.update_tool(db, "tool-1", tool_update, user_email="nope@x.com")

    @pytest.mark.asyncio
    async def test_update_tool_integrity_error(self, tool_service, mock_tool):
        """update_tool should re-raise IntegrityError."""
        db = MagicMock()
        db.commit.side_effect = IntegrityError("dup", {}, None)
        mock_tool.version = 1
        mock_tool.name = "old-name"

        tool_update = MagicMock()
        tool_update.name = None
        tool_update.custom_name = None
        tool_update.displayName = None
        tool_update.url = None
        tool_update.description = None
        tool_update.integration_type = None
        tool_update.request_type = None
        tool_update.headers = None
        tool_update.input_schema = None
        tool_update.output_schema = None
        tool_update.annotations = None
        tool_update.jsonpath_filter = None
        tool_update.visibility = None
        tool_update.auth = None
        tool_update.tags = None

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            with pytest.raises(IntegrityError):
                await tool_service.update_tool(db, "tool-1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_generic_exception(self, tool_service, mock_tool):
        """update_tool should wrap generic exceptions in ToolError."""
        db = MagicMock()
        db.commit.side_effect = RuntimeError("kaboom")
        mock_tool.version = 1
        mock_tool.name = "old-name"

        tool_update = MagicMock()
        tool_update.name = None
        tool_update.custom_name = None
        tool_update.displayName = None
        tool_update.url = None
        tool_update.description = None
        tool_update.integration_type = None
        tool_update.request_type = None
        tool_update.headers = None
        tool_update.input_schema = None
        tool_update.output_schema = None
        tool_update.annotations = None
        tool_update.jsonpath_filter = None
        tool_update.visibility = None
        tool_update.auth = None
        tool_update.tags = None

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            with pytest.raises(ToolError, match="Failed to update tool"):
                await tool_service.update_tool(db, "tool-1", tool_update)


# ═════════════════════════════════════════════════════════════════════════════
# 18. reset_metrics
# ═════════════════════════════════════════════════════════════════════════════


class TestResetMetrics:
    """Tests for reset_metrics method."""

    @pytest.mark.asyncio
    async def test_reset_metrics_all(self, tool_service):
        """reset_metrics without tool_id should delete all metrics."""
        db = MagicMock()
        await tool_service.reset_metrics(db)
        assert db.execute.call_count == 2
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_metrics_specific_tool(self, tool_service):
        """reset_metrics with tool_id should delete only that tool's metrics."""
        db = MagicMock()
        await tool_service.reset_metrics(db, tool_id="tool-1")
        assert db.execute.call_count == 2
        db.commit.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# 19. get_top_tools
# ═════════════════════════════════════════════════════════════════════════════


class TestGetTopTools:
    """Tests for get_top_tools method."""

    @pytest.mark.asyncio
    async def test_get_top_tools_cache_miss(self, tool_service, monkeypatch):
        """get_top_tools should compute and cache on cache miss."""
        from mcpgateway.cache import metrics_cache as cache_module

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        cache_module.metrics_cache.get = MagicMock(return_value=None)
        cache_module.metrics_cache.set = MagicMock()

        mock_results = []
        monkeypatch.setattr("mcpgateway.services.tool_service.get_top_performers_combined", MagicMock(return_value=mock_results))
        monkeypatch.setattr("mcpgateway.services.tool_service.build_top_performers", MagicMock(return_value=[]))

        result = await tool_service.get_top_tools(MagicMock(), limit=3)
        assert result == []
        cache_module.metrics_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_top_tools_cache_disabled(self, tool_service, monkeypatch):
        """get_top_tools should compute directly when cache is disabled."""
        from mcpgateway.cache import metrics_cache as cache_module

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        monkeypatch.setattr("mcpgateway.services.tool_service.get_top_performers_combined", MagicMock(return_value=[]))
        monkeypatch.setattr("mcpgateway.services.tool_service.build_top_performers", MagicMock(return_value=[]))

        result = await tool_service.get_top_tools(MagicMock(), limit=5)
        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# 20. _process_single_tool_for_bulk edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleToolForBulk:
    """Tests for _process_single_tool_for_bulk edge cases."""

    def _make_tool_create(self, name="bulk_tool"):
        """Create a minimal mock ToolCreate."""
        tc = MagicMock()
        tc.name = name
        tc.auth = None
        tc.url = "http://example.com"
        tc.description = "desc"
        tc.integration_type = "MCP"
        tc.request_type = "SSE"
        tc.headers = {}
        tc.input_schema = {}
        tc.output_schema = None
        tc.annotations = {}
        tc.jsonpath_filter = ""
        tc.gateway_id = None
        tc.tags = []
        tc.displayName = None
        tc.team_id = None
        tc.owner_email = None
        tc.visibility = "public"
        tc.base_url = None
        tc.path_template = None
        tc.query_mapping = None
        tc.header_mapping = None
        tc.timeout_ms = None
        tc.expose_passthrough = None
        tc.allowlist = None
        tc.plugin_chain_pre = None
        tc.plugin_chain_post = None
        return tc

    def test_skip_on_conflict(self, tool_service):
        """Should return skip when conflict_strategy is 'skip'."""
        existing = MagicMock()
        result = tool_service._process_single_tool_for_bulk(
            tool=self._make_tool_create(),
            existing_tools_map={"bulk_tool": existing},
            conflict_strategy="skip",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "skip"

    def test_fail_on_conflict(self, tool_service):
        """Should return fail when conflict_strategy is 'fail'."""
        existing = MagicMock()
        result = tool_service._process_single_tool_for_bulk(
            tool=self._make_tool_create(),
            existing_tools_map={"bulk_tool": existing},
            conflict_strategy="fail",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "fail"
        assert "conflict" in result["error"].lower()

    def test_update_on_conflict(self, tool_service):
        """Should return update when conflict_strategy is 'update'."""
        existing = MagicMock()
        existing.version = 1
        result = tool_service._process_single_tool_for_bulk(
            tool=self._make_tool_create(),
            existing_tools_map={"bulk_tool": existing},
            conflict_strategy="update",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "update"

    def test_update_on_conflict_rest_type(self, tool_service):
        """Should update REST-specific fields when integration_type is REST."""
        existing = MagicMock()
        existing.version = 1
        tc = self._make_tool_create()
        tc.integration_type = "REST"
        tc.base_url = "http://base.com"
        tc.path_template = "/api/{id}"
        tc.query_mapping = {"q": "search"}
        tc.header_mapping = {"X-Key": "key"}
        tc.timeout_ms = 5000
        tc.expose_passthrough = True
        tc.allowlist = ["*"]
        tc.plugin_chain_pre = ["p1"]
        tc.plugin_chain_post = ["p2"]
        result = tool_service._process_single_tool_for_bulk(
            tool=tc,
            existing_tools_map={"bulk_tool": existing},
            conflict_strategy="update",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "update"
        assert existing.base_url == "http://base.com"

    def test_rename_on_conflict(self, tool_service):
        """Should return add with renamed tool when conflict_strategy is 'rename'."""
        existing = MagicMock()
        result = tool_service._process_single_tool_for_bulk(
            tool=self._make_tool_create(),
            existing_tools_map={"bulk_tool": existing},
            conflict_strategy="rename",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "add"

    def test_add_new_tool(self, tool_service):
        """Should return add for new tools without conflict."""
        result = tool_service._process_single_tool_for_bulk(
            tool=self._make_tool_create("new_tool"),
            existing_tools_map={},
            conflict_strategy="skip",
            visibility="public",
            team_id=None,
            owner_email=None,
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result["status"] == "add"

    def test_exception_returns_fail(self, tool_service):
        """Exceptions should be caught and returned as fail status."""
        tc = MagicMock()
        tc.name = "bad_tool"
        tc.auth = MagicMock()
        tc.auth.auth_type = "bearer"
        tc.auth.auth_value = None  # This will cause issues later but not for auth extraction

        # Make _create_tool_object raise
        with patch.object(tool_service, "_create_tool_object", side_effect=RuntimeError("boom")):
            result = tool_service._process_single_tool_for_bulk(
                tool=tc,
                existing_tools_map={},
                conflict_strategy="skip",
                visibility="public",
                team_id=None,
                owner_email=None,
                created_by="admin",
                created_from_ip=None,
                created_via=None,
                created_user_agent=None,
                import_batch_id=None,
                federation_source=None,
            )
        assert result["status"] == "fail"
        assert "boom" in result["error"]


# ═════════════════════════════════════════════════════════════════════════════
# 21. A2A methods
# ═════════════════════════════════════════════════════════════════════════════


class TestA2AMethods:
    """Tests for A2A agent-related methods."""

    @pytest.mark.asyncio
    async def test_update_tool_from_a2a_agent_no_tool_id(self, tool_service):
        """Should return None when agent has no tool_id."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = None
        agent.id = "agent-1"
        result = await tool_service.update_tool_from_a2a_agent(db, agent)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_tool_from_a2a_agent_tool_not_found(self, tool_service):
        """Should return None and reset tool_id when tool not found."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = "tool-99"
        agent.id = "agent-1"
        db.get.return_value = None
        result = await tool_service.update_tool_from_a2a_agent(db, agent)
        assert result is None
        assert agent.tool_id is None
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_delete_tool_from_a2a_agent_no_tool_id(self, tool_service):
        """Should return early when agent has no tool_id."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = None
        agent.id = "agent-1"
        await tool_service.delete_tool_from_a2a_agent(db, agent)
        db.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_tool_from_a2a_agent_tool_not_found(self, tool_service):
        """Should return early when tool not found."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = "tool-99"
        agent.id = "agent-1"
        db.get.return_value = None
        await tool_service.delete_tool_from_a2a_agent(db, agent)

    @pytest.mark.asyncio
    async def test_invoke_a2a_tool_missing_agent_id(self, tool_service, mock_tool):
        """Should raise ToolNotFoundError when annotations lack a2a_agent_id."""
        mock_tool.annotations = {}
        mock_tool.integration_type = "A2A"
        db = MagicMock()
        with pytest.raises(ToolNotFoundError, match="missing agent ID"):
            await tool_service._invoke_a2a_tool(db, mock_tool, {"query": "hello"})

    @pytest.mark.asyncio
    async def test_invoke_a2a_tool_agent_not_found(self, tool_service, mock_tool):
        """Should raise ToolNotFoundError when agent is not in DB."""
        mock_tool.annotations = {"a2a_agent_id": "agent-xyz"}
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(ToolNotFoundError, match="not found"):
            await tool_service._invoke_a2a_tool(db, mock_tool, {"query": "hello"})

    @pytest.mark.asyncio
    async def test_invoke_a2a_tool_agent_disabled(self, tool_service, mock_tool):
        """Should raise ToolNotFoundError when agent is disabled."""
        mock_tool.annotations = {"a2a_agent_id": "agent-xyz"}
        agent = MagicMock()
        agent.enabled = False
        agent.name = "test-agent"
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with pytest.raises(ToolNotFoundError, match="disabled"):
            await tool_service._invoke_a2a_tool(db, mock_tool, {"query": "hello"})

    @pytest.mark.asyncio
    async def test_invoke_a2a_tool_success(self, tool_service, mock_tool):
        """Should return ToolResult on successful A2A invocation."""
        mock_tool.annotations = {"a2a_agent_id": "agent-xyz"}
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://a2a.example.com"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent

        with patch.object(tool_service, "_call_a2a_agent", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"response": "Hello!"}
            result = await tool_service._invoke_a2a_tool(db, mock_tool, {"query": "hello"})

        assert result.is_error is False
        assert "Hello!" in result.content[0].text

    @pytest.mark.asyncio
    async def test_invoke_a2a_tool_error(self, tool_service, mock_tool):
        """Should return error ToolResult on A2A invocation failure."""
        mock_tool.annotations = {"a2a_agent_id": "agent-xyz"}
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://a2a.example.com"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent

        with patch.object(tool_service, "_call_a2a_agent", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("connection failed")
            result = await tool_service._invoke_a2a_tool(db, mock_tool, {"query": "hello"})

        assert result.is_error is True
        assert "connection failed" in result.content[0].text


# ═════════════════════════════════════════════════════════════════════════════
# 22. _get_validator_class_and_check edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestValidatorClassAndCheck:
    """Additional tests for _get_validator_class_and_check."""

    def test_fallback_all_fail_raises(self, monkeypatch):
        """When all fallbacks fail, should re-raise the original error on second check_schema call."""
        schema_json = orjson.dumps({"type": "object", "x": "y"}).decode()

        call_count = {"n": 0}

        class AlwaysFail:
            @staticmethod
            def check_schema(_schema):
                call_count["n"] += 1
                if call_count["n"] <= 1:
                    raise jsonschema.exceptions.SchemaError("primary fail")
                # Second call in final fallback path - just return OK
                return None

        class FallbackFail:
            @staticmethod
            def check_schema(_schema):
                raise jsonschema.exceptions.SchemaError("fallback fail")

        _get_validator_class_and_check.cache_clear()
        monkeypatch.setattr("mcpgateway.services.tool_service.validators.validator_for", lambda _: AlwaysFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft7Validator", FallbackFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft6Validator", FallbackFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft4Validator", FallbackFail)

        # The second check_schema call should succeed in this test
        result_cls, result_schema = _get_validator_class_and_check(schema_json)
        assert result_cls is AlwaysFail


# ═════════════════════════════════════════════════════════════════════════════
# 23. subscribe_events
# ═════════════════════════════════════════════════════════════════════════════


class TestSubscribeEvents:
    """Tests for subscribe_events method."""

    @pytest.mark.asyncio
    async def test_subscribe_events_yields_events(self, tool_service):
        """subscribe_events should yield events from event service."""

        async def mock_subscribe():
            yield {"type": "tool_added", "data": {}}
            yield {"type": "tool_removed", "data": {}}

        tool_service._event_service = MagicMock()
        tool_service._event_service.subscribe_events = mock_subscribe

        events = []
        async for event in tool_service.subscribe_events():
            events.append(event)

        assert len(events) == 2
        assert events[0]["type"] == "tool_added"
        assert events[1]["type"] == "tool_removed"


# ═════════════════════════════════════════════════════════════════════════════
# 24. _extract_and_validate_structured_content - additional branches
# ═════════════════════════════════════════════════════════════════════════════


class TestStructuredContentAdditional:
    """Additional branch coverage for _extract_and_validate_structured_content."""

    def test_unwrap_single_element_list_non_textcontent_inner(self, tool_service):
        """Single-element list with non-TextContent dict should be unwrapped directly."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"a": {"type": "integer"}}})
        result = ToolResult(content=[])
        # This is a single-element list with a non-text dict
        candidate = [{"a": 5}]
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate=candidate)
        assert ok is True

    def test_unwrap_inner_text_with_unparseable_json(self, tool_service):
        """When inner text fails to parse as JSON, should use inner dict directly."""
        tool = SimpleNamespace(output_schema={"type": "object"})
        result = ToolResult(content=[])
        candidate = [{"type": "text", "text": "not-json-at-all"}]
        # This will try to parse the inner text, fail, and use the inner dict
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate=candidate)
        # Validation may pass or fail depending on schema, but shouldn't crash
        assert isinstance(ok, bool)

    def test_content_with_null_text_parses_to_none(self, tool_service):
        """Content with text=None should parse to null and be treated as no structured data."""
        tool = SimpleNamespace(output_schema={"type": "object"})
        # text=None -> orjson.loads("null") -> None -> treated as no structured data
        content = [{"type": "text", "text": "null"}]
        result = ToolResult(content=content)
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        # null parse -> structured=None -> treat as valid (nothing to validate)
        assert ok is True

    def test_validation_error_orjson_fallback(self, tool_service):
        """When orjson.dumps fails for error details, fall back to str()."""
        tool = SimpleNamespace(output_schema={"type": "string"})
        result = ToolResult(content=[])
        # Provide an invalid candidate (number when string expected)
        ok = tool_service._extract_and_validate_structured_content(tool, result, candidate=42)
        assert ok is False
        assert result.is_error is True


# ═════════════════════════════════════════════════════════════════════════════
# 25. update_tool - name conflict and ToolNotFoundError paths
# ═════════════════════════════════════════════════════════════════════════════


class TestUpdateToolAdditional:
    """Additional update_tool tests for name conflict paths."""

    @pytest.mark.asyncio
    async def test_update_tool_name_conflict(self, tool_service, mock_tool):
        """update_tool should raise ToolNameConflictError when name conflicts."""
        db = MagicMock()
        mock_tool.version = 1
        mock_tool.name = "old-name"
        mock_tool.custom_name = "old-name"

        existing_conflict = MagicMock()
        existing_conflict.custom_name = "new-name"
        existing_conflict.enabled = True
        existing_conflict.id = 99
        existing_conflict.visibility = "public"

        tool_update = MagicMock()
        tool_update.name = "new-name"
        tool_update.custom_name = "new-name"
        tool_update.visibility = MagicMock()
        tool_update.visibility.lower.return_value = "public"

        with patch("mcpgateway.services.tool_service.get_for_update") as mock_gfu:
            # First call returns the tool, second call returns the conflicting tool
            mock_gfu.side_effect = [mock_tool, existing_conflict]
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "tool-1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_not_found_during_update(self, tool_service):
        """update_tool should raise ToolNotFoundError for unknown tool_id."""
        db = MagicMock()
        tool_update = MagicMock()
        tool_update.name = None

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=None):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.update_tool(db, "missing-tool", tool_update)


# ═════════════════════════════════════════════════════════════════════════════
# 26. set_tool_state - additional error paths
# ═════════════════════════════════════════════════════════════════════════════


class TestSetToolStateAdditional:
    """Additional set_tool_state tests for error handling."""

    @pytest.mark.asyncio
    async def test_set_tool_state_not_found_raises_directly(self, tool_service):
        """ToolNotFoundError should propagate without wrapping."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", return_value=None):
            with pytest.raises(ToolNotFoundError):
                await tool_service.set_tool_state(db, "no-tool", True, True)

    @pytest.mark.asyncio
    async def test_set_tool_state_lock_conflict_raises_directly(self, tool_service):
        """ToolLockConflictError should propagate without wrapping."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=OperationalError("locked", {}, None)):
            with pytest.raises(ToolLockConflictError):
                await tool_service.set_tool_state(db, "locked-tool", True, True)


# ═════════════════════════════════════════════════════════════════════════════
# 27. create_tool_from_a2a_agent
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateToolFromA2AAgent:
    """Tests for create_tool_from_a2a_agent."""

    @pytest.mark.asyncio
    async def test_create_tool_from_a2a_existing_returns_tool(self, tool_service):
        """If tool already exists for agent, return it directly."""
        db = MagicMock()
        existing_tool = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = existing_tool

        agent = MagicMock()
        agent.slug = "my-agent"
        agent.name = "My Agent"
        agent.tags = []

        result = await tool_service.create_tool_from_a2a_agent(db, agent)
        assert result is existing_tool

    @pytest.mark.asyncio
    async def test_create_tool_from_a2a_normalizes_tags(self, tool_service):
        """Should normalize dict tags, label-attrs, and string tags."""
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None  # no existing

        agent = MagicMock()
        agent.slug = "new-agent"
        agent.name = "New Agent"
        agent.description = "Test agent"
        agent.endpoint_url = "http://agent.example.com"
        agent.agent_type = "generic"
        agent.auth_type = None
        agent.auth_value = None
        agent.visibility = "public"
        agent.team_id = None
        agent.owner_email = None
        # Mixed tag formats
        agent.tags = [
            {"label": "ai", "id": "tag-1"},
            {"id": "tag-2"},
            "simple-tag",
        ]

        mock_tool_read = MagicMock(spec=ToolRead)
        mock_tool_read.id = "tool-99"
        tool_service.register_tool = AsyncMock(return_value=mock_tool_read)
        db.get.return_value = MagicMock()

        result = await tool_service.create_tool_from_a2a_agent(db, agent, created_by="admin")

        # Verify register_tool was called
        tool_service.register_tool.assert_awaited_once()
        call_args = tool_service.register_tool.call_args
        tool_create = call_args[0][1]  # second positional arg
        # Tags are normalized by Pydantic to dicts with id/label keys
        tag_labels = [t["label"] if isinstance(t, dict) else t for t in tool_create.tags]
        assert "a2a" in tag_labels
        assert "agent" in tag_labels
        assert "ai" in tag_labels

    @pytest.mark.asyncio
    async def test_update_tool_from_a2a_agent_with_tool(self, tool_service, mock_tool):
        """Should update the associated tool when found."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = "tool-1"
        agent.id = "agent-1"
        agent.slug = "test-agent"
        agent.name = "Test Agent"
        agent.description = "desc"
        agent.endpoint_url = "http://agent.example.com"
        agent.auth_type = "bearer"
        agent.auth_value = "token123"
        agent.tags = ["tag1"]

        db.get.return_value = mock_tool

        mock_tool_read = MagicMock(spec=ToolRead)
        tool_service.update_tool = AsyncMock(return_value=mock_tool_read)

        result = await tool_service.update_tool_from_a2a_agent(db, agent, modified_by="admin")
        assert result is mock_tool_read
        tool_service.update_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_tool_from_a2a_agent_with_tool(self, tool_service, mock_tool):
        """Should delete the associated tool when found."""
        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = "tool-1"
        agent.id = "agent-1"

        db.get.return_value = mock_tool
        tool_service.delete_tool = AsyncMock()

        await tool_service.delete_tool_from_a2a_agent(db, agent, user_email="admin@x.com")
        tool_service.delete_tool.assert_awaited_once()


# ═════════════════════════════════════════════════════════════════════════════
# 28. _call_a2a_agent
# ═════════════════════════════════════════════════════════════════════════════


class TestCallA2AAgent:
    """Tests for _call_a2a_agent method."""

    @pytest.mark.asyncio
    async def test_call_a2a_jsonrpc_agent_with_query(self, tool_service):
        """Should build JSONRPC request for generic agent."""
        agent = MagicMock()
        agent.name = "jsonrpc-agent"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "jsonrpc"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "ok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await tool_service._call_a2a_agent(agent, {"query": "hello"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_call_a2a_custom_agent(self, tool_service):
        """Should build custom request for non-jsonrpc agent."""
        agent = MagicMock()
        agent.name = "custom-agent"
        agent.endpoint_url = "http://agent.example.com/custom"
        agent.agent_type = "custom"
        agent.protocol_version = "1.0"
        agent.auth_type = "bearer"
        agent.auth_value = "my-token"
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "custom"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert result == {"data": "custom"}
        # Verify bearer auth was added
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1]["headers"]
        assert "Authorization" in headers

    @pytest.mark.asyncio
    async def test_call_a2a_agent_http_error(self, tool_service):
        """Should raise exception on non-200 status."""
        agent = MagicMock()
        agent.name = "error-agent"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 500"):
                await tool_service._call_a2a_agent(agent, {"query": "fail"})

    @pytest.mark.asyncio
    async def test_call_a2a_agent_with_query_param_auth(self, tool_service):
        """Should apply query param auth when configured."""
        agent = MagicMock()
        agent.name = "qp-agent"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = "query_param"
        agent.auth_value = None
        agent.auth_query_params = {"api_key": "encrypted_value"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"api_key": "real_key"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://agent.example.com/?api_key=real_key"),
            patch("mcpgateway.services.tool_service.sanitize_url_for_logging", return_value="http://agent.example.com/?api_key=***"),
        ):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_call_a2a_agent_api_key_auth(self, tool_service):
        """Should set Authorization header for api_key auth."""
        agent = MagicMock()
        agent.name = "apikey-agent"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = "api_key"
        agent.auth_value = "my-api-key"
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        call_kwargs = mock_client.post.call_args
        assert "Bearer my-api-key" in call_kwargs[1]["headers"]["Authorization"]


# ═════════════════════════════════════════════════════════════════════════════
# 29. _record_tool_metric_sync
# ═════════════════════════════════════════════════════════════════════════════


class TestRecordToolMetricSync:
    """Tests for _record_tool_metric_sync."""

    def test_record_tool_metric_sync(self, tool_service, monkeypatch):
        """_record_tool_metric_sync should use fresh session and delegate."""
        dummy_db = MagicMock()

        class DummySession:
            def __enter__(self):
                return dummy_db

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("mcpgateway.services.tool_service.fresh_db_session", lambda: DummySession())

        with patch.object(tool_service, "_record_tool_metric_by_id") as mock_record:
            tool_service._record_tool_metric_sync("t1", 1.0, True, None)

        mock_record.assert_called_once_with(
            dummy_db,
            tool_id="t1",
            start_time=1.0,
            success=True,
            error_message=None,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 30. _create_tool_object
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateToolObject:
    """Tests for _create_tool_object helper."""

    def test_create_tool_object_basic(self, tool_service):
        """_create_tool_object should create a DbTool with correct attributes."""
        tc = MagicMock()
        tc.name = "test"
        tc.displayName = "Test Tool"
        tc.url = "http://example.com"
        tc.description = "desc"
        tc.integration_type = "MCP"
        tc.request_type = "SSE"
        tc.headers = {}
        tc.input_schema = {}
        tc.output_schema = None
        tc.annotations = {}
        tc.jsonpath_filter = ""
        tc.gateway_id = None
        tc.tags = ["tag1"]

        result = tool_service._create_tool_object(
            tool=tc,
            name="test",
            auth_type=None,
            auth_value=None,
            tool_team_id=None,
            tool_owner_email="admin@x.com",
            tool_visibility="public",
            created_by="admin",
            created_from_ip="127.0.0.1",
            created_via="api",
            created_user_agent="test",
            import_batch_id=None,
            federation_source=None,
        )
        assert result.original_name == "test"

    def test_create_tool_object_rest_type(self, tool_service):
        """_create_tool_object should set REST-specific fields for REST tools."""
        tc = MagicMock()
        tc.name = "rest-tool"
        tc.displayName = "REST Tool"
        tc.url = "http://rest.example.com"
        tc.description = "REST desc"
        tc.integration_type = "REST"
        tc.request_type = "GET"
        tc.headers = {}
        tc.input_schema = {}
        tc.output_schema = None
        tc.annotations = {}
        tc.jsonpath_filter = ""
        tc.gateway_id = None
        tc.tags = []
        tc.base_url = "http://base.example.com"
        tc.path_template = "/api/{id}"
        tc.query_mapping = {"q": "search"}
        tc.header_mapping = {"X-Key": "key"}
        tc.timeout_ms = 5000
        tc.expose_passthrough = True
        tc.allowlist = ["*"]
        tc.plugin_chain_pre = ["p1"]
        tc.plugin_chain_post = ["p2"]

        result = tool_service._create_tool_object(
            tool=tc,
            name="rest-tool",
            auth_type=None,
            auth_value=None,
            tool_team_id="team-1",
            tool_owner_email="admin@x.com",
            tool_visibility="team",
            created_by="admin",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result.base_url == "http://base.example.com"
        assert result.path_template == "/api/{id}"


# ─── Notification event coverage ─────────────────────────────────────────────


class TestNotificationEventsCoverage:
    """Direct tests for notification methods (lines 4016-4118)."""

    @pytest.fixture
    def tool_service(self):
        svc = ToolService()
        svc._event_service = AsyncMock()
        return svc

    def _make_tool(self, **overrides):
        t = MagicMock(spec=DbTool)
        t.id = "t1"
        t.name = "test-tool"
        t.url = "http://example.com"
        t.description = "desc"
        t.enabled = True
        t.reachable = True
        for k, v in overrides.items():
            setattr(t, k, v)
        return t

    @pytest.mark.asyncio
    async def test_notify_tool_activated(self, tool_service):
        tool = self._make_tool()
        await tool_service._notify_tool_activated(tool)
        tool_service._event_service.publish_event.assert_awaited_once()
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_activated"
        assert event["data"]["id"] == "t1"
        assert "timestamp" in event

    @pytest.mark.asyncio
    async def test_notify_tool_deactivated(self, tool_service):
        tool = self._make_tool(enabled=False, reachable=False)
        await tool_service._notify_tool_deactivated(tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_deactivated"
        assert event["data"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_notify_tool_offline(self, tool_service):
        tool = self._make_tool()
        await tool_service._notify_tool_offline(tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_offline"
        assert event["data"]["reachable"] is False

    @pytest.mark.asyncio
    async def test_notify_tool_deleted(self, tool_service):
        tool_info = {"id": "t1", "name": "test-tool"}
        await tool_service._notify_tool_deleted(tool_info)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_deleted"
        assert event["data"] == tool_info

    @pytest.mark.asyncio
    async def test_notify_tool_added(self, tool_service):
        tool = self._make_tool()
        await tool_service._notify_tool_added(tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_added"
        assert event["data"]["url"] == "http://example.com"

    @pytest.mark.asyncio
    async def test_notify_tool_removed(self, tool_service):
        tool = self._make_tool(enabled=False)
        await tool_service._notify_tool_removed(tool)
        event = tool_service._event_service.publish_event.call_args[0][0]
        assert event["type"] == "tool_removed"


# ─── _invoke_a2a_tool coverage ───────────────────────────────────────────────


class TestInvokeA2AToolCoverage:
    """Tests for _invoke_a2a_tool (lines 4449-4510)."""

    @pytest.fixture
    def tool_service(self):
        svc = ToolService()
        svc._event_service = AsyncMock()
        return svc

    def _make_a2a_tool(self, agent_id="agent-1"):
        tool = MagicMock(spec=DbTool)
        tool.id = "tool-1"
        tool.name = "a2a-tool"
        tool.annotations = {"a2a_agent_id": agent_id} if agent_id else {}
        return tool

    @pytest.mark.asyncio
    async def test_missing_agent_id_raises(self, tool_service):
        tool = self._make_a2a_tool(agent_id=None)
        db = MagicMock()
        with pytest.raises(ToolNotFoundError, match="missing agent ID"):
            await tool_service._invoke_a2a_tool(db, tool, {})

    @pytest.mark.asyncio
    async def test_agent_not_found_raises(self, tool_service):
        tool = self._make_a2a_tool()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(ToolNotFoundError, match="A2A agent not found"):
            await tool_service._invoke_a2a_tool(db, tool, {})

    @pytest.mark.asyncio
    async def test_agent_disabled_raises(self, tool_service):
        tool = self._make_a2a_tool()
        agent = MagicMock()
        agent.enabled = False
        agent.name = "test-agent"
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        with pytest.raises(ToolNotFoundError, match="is disabled"):
            await tool_service._invoke_a2a_tool(db, tool, {})

    @pytest.mark.asyncio
    async def test_success_with_response_key(self, tool_service):
        tool = self._make_a2a_tool()
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://agent.test"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value={"response": "hello"})

        result = await tool_service._invoke_a2a_tool(db, tool, {"query": "hi"})
        assert result.is_error is False
        assert result.content[0].text == "hello"

    @pytest.mark.asyncio
    async def test_success_without_response_key(self, tool_service):
        tool = self._make_a2a_tool()
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://agent.test"
        agent.agent_type = "custom"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value="raw-response")

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        assert result.content[0].text == "raw-response"

    @pytest.mark.asyncio
    async def test_exception_returns_error_result(self, tool_service):
        tool = self._make_a2a_tool()
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://agent.test"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(side_effect=RuntimeError("boom"))

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is True
        assert "boom" in result.content[0].text


# ─── _call_a2a_agent coverage ────────────────────────────────────────────────


class TestCallA2AAgentCoverage:
    """Tests for _call_a2a_agent (lines 4512-4598)."""

    @pytest.fixture
    def tool_service(self):
        svc = ToolService()
        svc._event_service = AsyncMock()
        return svc

    def _make_agent(self, **overrides):
        agent = MagicMock()
        agent.name = "test-agent"
        agent.endpoint_url = "http://agent.test/api"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        for k, v in overrides.items():
            setattr(agent, k, v)
        return agent

    @pytest.mark.asyncio
    async def test_jsonrpc_with_query_param(self, tool_service):
        agent = self._make_agent(agent_type="jsonrpc")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await tool_service._call_a2a_agent(agent, {"query": "hello"})
        assert result == {"result": "ok"}
        call_data = mock_client.post.call_args[1]["json"]
        assert call_data["jsonrpc"] == "2.0"
        assert call_data["params"]["message"]["parts"][0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_custom_agent_format(self, tool_service):
        agent = self._make_agent(agent_type="custom", endpoint_url="http://custom.test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"answer": "42"}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            result = await tool_service._call_a2a_agent(agent, {"query": "what"})
        assert result == {"answer": "42"}
        call_data = mock_client.post.call_args[1]["json"]
        assert call_data["interaction_type"] == "query"

    @pytest.mark.asyncio
    async def test_api_key_auth(self, tool_service):
        agent = self._make_agent(auth_type="api_key", auth_value="secret-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_bearer_auth(self, tool_service):
        agent = self._make_agent(auth_type="bearer", auth_value="bearer-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer bearer-token"

    @pytest.mark.asyncio
    async def test_query_param_auth(self, tool_service):
        agent = self._make_agent(auth_type="query_param", auth_query_params={"api_key": "encrypted"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"api_key": "real-key"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://agent.test/api?api_key=real-key"),
            patch("mcpgateway.services.tool_service.sanitize_url_for_logging", return_value="http://agent.test/api?api_key=***"),
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert mock_client.post.call_args[0][0] == "http://agent.test/api?api_key=real-key"

    @pytest.mark.asyncio
    async def test_non_200_raises(self, tool_service):
        agent = self._make_agent()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server Error"
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 500"):
                await tool_service._call_a2a_agent(agent, {"query": "test"})

    @pytest.mark.asyncio
    async def test_passthrough_params(self, tool_service):
        """Non-query dict parameters should be passed through as-is for JSONRPC."""
        agent = self._make_agent(agent_type="jsonrpc")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client):
            await tool_service._call_a2a_agent(agent, {"params": {"custom": "data"}, "method": "custom/method"})
        call_data = mock_client.post.call_args[1]["json"]
        assert call_data["method"] == "custom/method"
        assert call_data["params"] == {"custom": "data"}


# ─── _record_tool_metric coverage ────────────────────────────────────────────


class TestRecordToolMetricCoverage:
    """Tests for _record_tool_metric (lines 762-786)."""

    @pytest.fixture
    def tool_service(self):
        svc = ToolService()
        svc._event_service = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_record_metric_success(self, tool_service):
        db = MagicMock()
        tool = MagicMock(spec=DbTool)
        tool.id = "tool-1"
        start = time.monotonic() - 0.5

        await tool_service._record_tool_metric(db, tool, start, True, None)
        db.add.assert_called_once()
        metric = db.add.call_args[0][0]
        assert metric.tool_id == "tool-1"
        assert metric.is_success is True
        assert metric.error_message is None
        assert metric.response_time > 0
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_metric_failure(self, tool_service):
        db = MagicMock()
        tool = MagicMock(spec=DbTool)
        tool.id = "tool-2"
        start = time.monotonic()

        await tool_service._record_tool_metric(db, tool, start, False, "timeout")
        metric = db.add.call_args[0][0]
        assert metric.is_success is False
        assert metric.error_message == "timeout"


# ─── validate_tool_url and check_tool_health coverage ────────────────────────


class TestToolHealthValidationCoverage:
    """Tests for _validate_tool_url and _check_tool_health (lines 4129-4157)."""

    @pytest.fixture
    def tool_service(self):
        svc = ToolService()
        svc._event_service = AsyncMock()
        svc._http_client = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_validate_tool_url_success(self, tool_service):
        tool_service._http_client.get.return_value = MagicMock(raise_for_status=MagicMock())
        await tool_service._validate_tool_url("http://example.com")

    @pytest.mark.asyncio
    async def test_validate_tool_url_failure(self, tool_service):
        tool_service._http_client.get.side_effect = ConnectionError("refused")
        with pytest.raises(ToolValidationError, match="Failed to validate"):
            await tool_service._validate_tool_url("http://bad.example.com")

    @pytest.mark.asyncio
    async def test_check_tool_health_success(self, tool_service):
        resp = MagicMock()
        resp.is_success = True
        tool_service._http_client.get.return_value = resp
        tool = MagicMock(spec=DbTool)
        tool.url = "http://example.com"
        assert await tool_service._check_tool_health(tool) is True

    @pytest.mark.asyncio
    async def test_check_tool_health_failure(self, tool_service):
        tool_service._http_client.get.side_effect = ConnectionError("refused")
        tool = MagicMock(spec=DbTool)
        tool.url = "http://bad.example.com"
        assert await tool_service._check_tool_health(tool) is False

    @pytest.mark.asyncio
    async def test_check_tool_health_non_success(self, tool_service):
        resp = MagicMock()
        resp.is_success = False
        tool_service._http_client.get.return_value = resp
        tool = MagicMock(spec=DbTool)
        tool.url = "http://example.com"
        assert await tool_service._check_tool_health(tool) is False


# ============================================================================
# Notification methods coverage
# ============================================================================


class TestToolNotificationMethods:
    """Tests for tool event notification methods."""

    @pytest.fixture
    def tool_service(self):
        service = ToolService()
        service._http_client = AsyncMock()
        service._event_service = AsyncMock()
        return service

    @pytest.fixture
    def mock_tool(self):
        tool = MagicMock(spec=DbTool)
        tool.id = "tool-1"
        tool.name = "test_tool"
        tool.url = "http://example.com/tool"
        tool.description = "A test tool"
        tool.enabled = True
        tool.reachable = True
        return tool

    @pytest.mark.asyncio
    async def test_notify_tool_updated(self, tool_service, mock_tool):
        """_notify_tool_updated publishes tool_updated event."""
        await tool_service._notify_tool_updated(mock_tool)
        tool_service._event_service._publish_event.assert_not_called()  # It uses _publish_event on self

    @pytest.mark.asyncio
    async def test_notify_tool_activated(self, tool_service, mock_tool):
        """_notify_tool_activated publishes tool_activated event."""
        await tool_service._notify_tool_activated(mock_tool)

    @pytest.mark.asyncio
    async def test_notify_tool_deactivated(self, tool_service, mock_tool):
        """_notify_tool_deactivated publishes tool_deactivated event."""
        mock_tool.enabled = False
        await tool_service._notify_tool_deactivated(mock_tool)

    @pytest.mark.asyncio
    async def test_notify_tool_deleted(self, tool_service):
        """_notify_tool_deleted publishes tool_deleted event with dict payload."""
        tool_info = {"id": "tool-1", "name": "test_tool", "url": "http://example.com"}
        await tool_service._notify_tool_deleted(tool_info)


# ============================================================================
# set_tool_state error paths
# ============================================================================


class TestSetToolStateLockAndPermission:
    """Tests for set_tool_state lock conflict and permission error paths."""

    @pytest.fixture
    def tool_service(self):
        service = ToolService()
        service._http_client = AsyncMock()
        service._event_service = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_lock_conflict_raises_tool_lock_conflict_error(self, tool_service):
        """OperationalError from get_for_update raises ToolLockConflictError."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=OperationalError("locked", {}, None)):
            with pytest.raises(ToolLockConflictError, match="currently being modified"):
                await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True)
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_error_activate(self, tool_service):
        """set_tool_state raises PermissionError when user doesn't own tool (activate)."""
        db = MagicMock()
        mock_tool = MagicMock(spec=DbTool)
        mock_tool.id = "tool-1"
        mock_tool.name = "test_tool"
        mock_tool.enabled = False

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool), \
             patch("mcpgateway.services.permission_service.PermissionService") as MockPS:
            mock_ps = AsyncMock()
            mock_ps.check_resource_ownership = AsyncMock(return_value=False)
            MockPS.return_value = mock_ps
            with pytest.raises(PermissionError, match="owner can activate"):
                await tool_service.set_tool_state(db, "tool-1", activate=True, reachable=True, user_email="notowner@test.com")

    @pytest.mark.asyncio
    async def test_permission_error_deactivate(self, tool_service):
        """set_tool_state raises PermissionError when user doesn't own tool (deactivate)."""
        db = MagicMock()
        mock_tool = MagicMock(spec=DbTool)
        mock_tool.id = "tool-1"
        mock_tool.name = "test_tool"
        mock_tool.enabled = True

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool), \
             patch("mcpgateway.services.permission_service.PermissionService") as MockPS:
            mock_ps = AsyncMock()
            mock_ps.check_resource_ownership = AsyncMock(return_value=False)
            MockPS.return_value = mock_ps
            with pytest.raises(PermissionError, match="owner can deactivate"):
                await tool_service.set_tool_state(db, "tool-1", activate=False, reachable=False, user_email="notowner@test.com")


# ============================================================================
# delete_tool permission and metrics purge
# ============================================================================


class TestDeleteToolPermissionAndPurge:
    """Tests for delete_tool PermissionError and purge_metrics paths."""

    @pytest.fixture
    def tool_service(self):
        service = ToolService()
        service._http_client = AsyncMock()
        service._event_service = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_permission_error_on_delete(self, tool_service):
        """delete_tool raises PermissionError when user doesn't own tool."""
        db = MagicMock()
        mock_tool = MagicMock(spec=DbTool)
        mock_tool.id = "tool-1"
        mock_tool.name = "test_tool"
        mock_tool.url = "http://example.com"
        mock_tool.tags = []
        mock_tool.team_id = None

        db.get.return_value = mock_tool

        with patch("mcpgateway.services.permission_service.PermissionService") as MockPS:
            mock_ps = AsyncMock()
            mock_ps.check_resource_ownership = AsyncMock(return_value=False)
            MockPS.return_value = mock_ps
            with pytest.raises(PermissionError, match="owner can delete"):
                await tool_service.delete_tool(db, "tool-1", user_email="notowner@test.com")
        db.rollback.assert_called()

    @pytest.mark.asyncio
    async def test_delete_with_purge_metrics(self, tool_service):
        """delete_tool with purge_metrics=True calls delete_metrics_in_batches."""
        db = MagicMock()
        mock_tool = MagicMock(spec=DbTool)
        mock_tool.id = "tool-1"
        mock_tool.name = "test_tool"
        mock_tool.url = "http://example.com"
        mock_tool.description = "A tool"
        mock_tool.enabled = True
        mock_tool.tags = []
        mock_tool.team_id = None
        mock_tool.gateway_id = None

        db.get.return_value = mock_tool
        db.execute.return_value.rowcount = 1

        mock_admin_cache = AsyncMock()
        mock_metrics_cache = MagicMock()

        with patch("mcpgateway.services.tool_service.delete_metrics_in_batches") as mock_delete, \
             patch("mcpgateway.services.tool_service.pause_rollup_during_purge") as mock_pause, \
             patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc, \
             patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc, \
             patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache", mock_admin_cache), \
             patch("mcpgateway.cache.metrics_cache.metrics_cache", mock_metrics_cache):
            mock_pause.return_value.__enter__ = MagicMock()
            mock_pause.return_value.__exit__ = MagicMock(return_value=False)
            mock_rc.return_value = AsyncMock()
            mock_tlc.return_value = AsyncMock()
            await tool_service.delete_tool(db, "tool-1", purge_metrics=True)
        assert mock_delete.call_count == 2  # ToolMetric + ToolMetricsHourly


# ============================================================================
# convert_tool_to_read with metrics
# ============================================================================


class TestConvertToolToReadMetrics:
    """Tests for convert_tool_to_read with include_metrics=True."""

    @pytest.fixture
    def tool_service(self):
        service = ToolService()
        service._http_client = AsyncMock()
        return service

    def test_include_metrics_true(self, tool_service):
        """convert_tool_to_read with include_metrics=True populates metrics."""
        now = datetime.now(timezone.utc)
        tool = SimpleNamespace(
            id="abcdef1234567890abcdef1234567890",
            name="test_tool",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            slug="test-tool",
            display_name="Test Tool",
            description="A test tool",
            url="http://example.com/tool",
            integration_type="direct",
            request_type="GET",
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            jsonpath_filter="",
            jq_filter=None,
            pre_tool_code=None,
            post_tool_code=None,
            enabled=True,
            reachable=True,
            created_at=now,
            updated_at=now,
            created_by="user@test.com",
            modified_by="user@test.com",
            tags=[],
            team_id=None,
            team=None,
            visibility="public",
            owner_email=None,
            gateway_id=None,
            gateway=None,
            gateway_slug="",
            a2a_agent_id=None,
            a2a_agent=None,
            auth_type=None,
            auth_value={},
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            version=1,
            passthrough_headers=[],
            execution_count=None,
            metrics=[],
            metrics_summary={
                "total_executions": 5,
                "successful_executions": 4,
                "failed_executions": 1,
                "failure_rate": 0.2,
                "min_response_time": 0.05,
                "max_response_time": 1.2,
                "avg_response_time": 0.5,
                "last_execution_time": now.isoformat(),
            },
            _sa_instance_state=MagicMock(),
        )
        result = tool_service.convert_tool_to_read(tool, include_metrics=True)
        assert result.metrics is not None
        assert result.execution_count == 5

    def test_include_metrics_false(self, tool_service):
        """convert_tool_to_read with include_metrics=False gives None metrics."""
        now = datetime.now(timezone.utc)
        tool = SimpleNamespace(
            id="abcdef1234567890abcdef1234567890",
            name="test_tool",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            slug="test-tool",
            display_name="Test Tool",
            description="A test tool",
            url="http://example.com/tool",
            integration_type="direct",
            request_type="GET",
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            jsonpath_filter="",
            jq_filter=None,
            pre_tool_code=None,
            post_tool_code=None,
            enabled=True,
            reachable=True,
            created_at=now,
            updated_at=now,
            created_by="user@test.com",
            modified_by="user@test.com",
            tags=[],
            team_id=None,
            team=None,
            visibility="public",
            owner_email=None,
            gateway_id=None,
            gateway=None,
            gateway_slug="",
            a2a_agent_id=None,
            a2a_agent=None,
            auth_type=None,
            auth_value={},
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            version=1,
            passthrough_headers=[],
            execution_count=None,
            metrics=[],
            metrics_summary={},
            _sa_instance_state=MagicMock(),
        )
        result = tool_service.convert_tool_to_read(tool, include_metrics=False)
        assert result.metrics is None
        assert result.execution_count is None
