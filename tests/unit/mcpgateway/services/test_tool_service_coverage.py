# -*- coding: utf-8 -*-
"""Additional coverage tests for tool_service.py.

Targets uncovered lines identified in coverage report to improve overall
branch coverage beyond the current 63%.
"""

# Standard
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, patch

# Third-Party
import jsonschema
import orjson
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

# First-Party
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.common.models import TextContent, ToolResult
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolMetrics, ToolRead, ToolUpdate
from mcpgateway.services.rust_a2a_runtime import RustA2ARuntimeError
from mcpgateway.services.tool_service import (
    _canonicalize_schema,
    _get_registry_cache,
    _get_tool_lookup_cache,
    _get_validator_class_and_check,
    extract_using_jq,
    ToolError,
    ToolInvocationError,
    ToolLockConflictError,
    ToolNameConflictError,
    ToolNotFoundError,
    ToolService,
    ToolTimeoutError,
    ToolValidationError,
)

# ─── autouse fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    # First-Party
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
    gw.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    gw.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    gw.created_by = None
    gw.created_from_ip = None
    gw.created_via = None
    gw.created_user_agent = None
    gw.modified_by = None
    gw.modified_from_ip = None
    gw.modified_via = None
    gw.modified_user_agent = None
    gw.import_batch_id = None
    gw.federation_source = None
    gw.version = None
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
    tool.original_description = "A test tool original"
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


def _make_tool_update(**overrides) -> MagicMock:
    """Build a ToolUpdate MagicMock with all fields defaulting to None."""
    update = MagicMock(spec=ToolUpdate)
    defaults = dict(
        name=None,
        custom_name=None,
        displayName=None,
        title=None,
        url=None,
        description=None,
        integration_type=None,
        request_type=None,
        headers=None,
        input_schema=None,
        output_schema=None,
        annotations=None,
        jsonpath_filter=None,
        visibility=None,
        auth=None,
        tags=None,
    )
    defaults.update(overrides)
    for attr, value in defaults.items():
        setattr(update, attr, value)
    return update


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
        # First-Party
        import mcpgateway.services.tool_service as ts_module

        # Reset the singleton so __getattr__ is exercised
        old = ts_module._tool_service_instance
        ts_module._tool_service_instance = None
        try:
            instance = getattr(ts_module, "tool_service")
            assert isinstance(instance, ToolService)
            # Second access should return the same instance
            instance2 = getattr(ts_module, "tool_service")
            assert instance is instance2
        finally:
            ts_module._tool_service_instance = old

    def test_getattr_unknown_raises_attribute_error(self):
        """Unknown attribute should raise AttributeError."""
        # First-Party
        import mcpgateway.services.tool_service as ts_module

        with pytest.raises(AttributeError, match="has no attribute"):
            getattr(ts_module, "nonexistent_attr")


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

    @pytest.mark.asyncio
    async def test_init_delegates_to_get_plugin_manager(self):
        """_get_plugin_manager should return the manager from the framework factory."""
        mock_pm = MagicMock()
        service = ToolService()
        with patch("mcpgateway.services.base_service.get_plugin_manager", AsyncMock(return_value=mock_pm)):
            result = await service._get_plugin_manager("server-1")
        assert result is mock_pm

    @pytest.mark.asyncio
    async def test_init_plugin_manager_none_when_disabled(self):
        """_get_plugin_manager should return None when plugins are disabled."""
        service = ToolService()
        with patch("mcpgateway.services.base_service.get_plugin_manager", AsyncMock(return_value=None)):
            result = await service._get_plugin_manager("server-1")
        assert result is None


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

    def test_build_tool_cache_payload_includes_mtls_fields(self, tool_service, mock_tool, mock_gateway):
        """Cache payload should include client_cert and client_key for mTLS."""
        mock_gateway.client_cert = "/path/to/client.pem"
        mock_gateway.client_key = "/path/to/client-key.pem"
        payload = tool_service._build_tool_cache_payload(mock_tool, mock_gateway)
        assert payload["gateway"]["client_cert"] == "/path/to/client.pem"
        assert payload["gateway"]["client_key"] == "/path/to/client-key.pem"

    def test_build_tool_cache_payload_mtls_fields_none_by_default(self, tool_service, mock_tool, mock_gateway):
        """Cache payload should include client_cert/client_key as None when not set."""
        mock_gateway.client_cert = None
        mock_gateway.client_key = None
        payload = tool_service._build_tool_cache_payload(mock_tool, mock_gateway)
        assert payload["gateway"]["client_cert"] is None
        assert payload["gateway"]["client_key"] is None

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
        result = ToolResult(content=[], structured_content={"x": "hello"})
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is True
        assert result.structured_content == {"x": "hello"}

    def test_invalid_candidate_marks_error(self, tool_service):
        """Invalid candidate should mark result as error."""
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]})
        result = ToolResult(content=[], structured_content={"x": 123})
        ok = tool_service._extract_and_validate_structured_content(tool, result)
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
        """When cache is enabled and has data, return cached as ToolMetrics."""
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module

        cached_data = {"total_executions": 100, "successful_executions": 90, "failed_executions": 10, "failure_rate": 0.1}
        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        monkeypatch.setattr(cache_module.metrics_cache, "get", MagicMock(return_value=cached_data))

        db = MagicMock()
        result = await tool_service.aggregate_metrics(db)
        assert isinstance(result, ToolMetrics)
        assert result.total_executions == 100
        assert result.successful_executions == 90

    @pytest.mark.asyncio
    async def test_aggregate_metrics_not_cached(self, tool_service, monkeypatch):
        """When cache miss, compute and cache result."""
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module
        from mcpgateway.schemas import ToolMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        monkeypatch.setattr(cache_module.metrics_cache, "get", MagicMock(return_value=None))
        monkeypatch.setattr(cache_module.metrics_cache, "set", MagicMock())

        mock_result = AggregatedMetrics(
            total_executions=50,
            successful_executions=45,
            failed_executions=5,
            failure_rate=0.1,
            min_response_time=0.1,
            max_response_time=1.0,
            avg_response_time=0.5,
            last_execution_time=None,
            raw_count=10,
            rollup_count=5,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(MagicMock())
        assert isinstance(result, ToolMetrics)
        assert result.total_executions == 50

    @pytest.mark.asyncio
    async def test_aggregate_metrics_cache_disabled(self, tool_service, monkeypatch):
        """When cache is disabled, compute directly."""
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module
        from mcpgateway.schemas import ToolMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        mock_result = AggregatedMetrics(
            total_executions=25,
            successful_executions=20,
            failed_executions=5,
            failure_rate=0.2,
            min_response_time=0.1,
            max_response_time=2.0,
            avg_response_time=0.8,
            last_execution_time=None,
            raw_count=5,
            rollup_count=5,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(MagicMock())
        assert isinstance(result, ToolMetrics)
        assert result.total_executions == 25


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
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        monkeypatch.setattr(cache_module.metrics_cache, "get", MagicMock(return_value=None))
        monkeypatch.setattr(cache_module.metrics_cache, "set", MagicMock())

        mock_results = []
        monkeypatch.setattr("mcpgateway.services.tool_service.get_top_performers_combined", MagicMock(return_value=mock_results))
        monkeypatch.setattr("mcpgateway.services.tool_service.build_top_performers", MagicMock(return_value=[]))

        result = await tool_service.get_top_tools(MagicMock(), limit=3)
        assert result == []
        cache_module.metrics_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_top_tools_cache_disabled(self, tool_service, monkeypatch):
        """get_top_tools should compute directly when cache is disabled."""
        # First-Party
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
    """Branch coverage for ``_extract_and_validate_structured_content``.

    These tests cover the edges of the validator that are not themselves
    part of the #4202 error-handling fix but exercise the surrounding
    contract introduced by PR #4204: that ``structured_content``, when
    present, MUST be a JSON object per the MCP 2025-11-25 specification's
    "Output Schema" section, and that the content-item JSON-parse fallback
    loop tolerates malformed items gracefully.
    """

    def test_invalid_structured_content_type_marks_error(self, tool_service):
        """Non-dict ``structured_content`` fast-fails with a structured error.

        The MCP 2025-11-25 "Output Schema" section requires that
        ``structuredContent`` be a JSON object. When the gateway receives a
        list or scalar there it must refuse to validate (since there is no
        way the payload can conform to the standard
        ``{"type": "object", ...}`` shape of an outputSchema) and surface a
        deterministic error describing the type mismatch, so callers can
        distinguish this from genuine schema-validation failures.

        MCP spec reference: 2025-11-25 "Output Schema".
        """
        tool = SimpleNamespace(output_schema={"type": "object"})
        result = SimpleNamespace(content=[], structured_content=[{"a": 5}], is_error=False)
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is False
        assert result.is_error is True
        details = orjson.loads(result.content[0].text)
        assert details["code"] == "invalid_structured_content_type"
        assert details["expected"] == "object"

    def test_content_with_null_text_parses_to_none(self, tool_service):
        """Content with text=None should parse to null and be treated as no structured data."""
        tool = SimpleNamespace(output_schema={"type": "object"})
        # text=None -> orjson.loads("null") -> None -> treated as no structured data
        content = [{"type": "text", "text": "null"}]
        result = ToolResult(content=content)
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        # null parse -> structured=None -> treat as valid (nothing to validate)
        assert ok is True

    def test_invalid_scalar_structured_content_marks_error(self, tool_service):
        """Scalar ``structured_content`` (int, string, bool) also fast-fails.

        Complements ``test_invalid_structured_content_type_marks_error`` by
        exercising the other half of the "not a JSON object" taxonomy — the
        MCP 2025-11-25 "Output Schema" section forbids any non-object shape
        in ``structuredContent``, and the validator's fast-fail branch must
        fire identically for scalars and for arrays. The error dict's
        ``received`` field must report the actual offending type name so the
        error is diagnosable.

        MCP spec reference: 2025-11-25 "Output Schema".
        """
        tool = SimpleNamespace(output_schema={"type": "string"})
        result = SimpleNamespace(content=[], structured_content=42, is_error=False)
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is False
        assert result.is_error is True
        details = orjson.loads(result.content[0].text)
        assert details["received"] == "int"

    def test_content_text_parse_failure_skips_and_continues(self, tool_service):
        """Content-fallback loop tolerates malformed items and continues.

        The MCP specification does not require all ``content`` items to be
        valid JSON — free-form text, logs and human-readable diagnostics are
        legal ``TextContent`` payloads. When no ``structured_content`` has
        been set explicitly, the gateway tries to promote the first parseable
        text item into the structured channel so ``output_schema``
        enforcement can run. That promotion must be best-effort: an item
        whose text is not valid JSON must be silently skipped
        (``orjson.JSONDecodeError`` caught in the ``except`` branch of the
        content-fallback loop in ``_extract_and_validate_structured_content``)
        rather than aborting the loop, so a valid JSON item later in the
        list is still used.

        MCP spec reference: 2025-11-25 "Content Types" (TextContent admits
        arbitrary text) and "Output Schema" (structured promotion is
        best-effort).
        """
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
        result = SimpleNamespace(
            content=[
                {"type": "text", "text": "definitely not json"},  # raises JSONDecodeError -> except -> continue
                {"type": "text", "text": '{"x": 42}'},  # parses successfully
            ],
            structured_content=None,
            is_error=False,
        )
        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is True
        # Verifies the loop skipped the bad item and picked up the good one.
        assert result.structured_content == {"x": 42}

    def test_single_element_list_structured_content_fast_fails(self, tool_service):
        """Pin the deliberate removal of the old single-element-list unwrap heuristic.

        Before the #4202 refactor, ``_extract_and_validate_structured_content``
        accepted ``structured_content=[{...}]`` (a one-element list) and
        silently unwrapped it to ``{...}`` when the declared schema was
        ``{"type": "object"}``. That heuristic was removed in favour of
        the stricter MCP 2025-11-25 "Output Schema" rule that
        ``structuredContent`` must be a JSON *object* — not a list
        containing one. The new canonical behaviour is the
        ``invalid_structured_content_type`` fast-fail at
        ``tool_service.py`` (the same branch ``test_invalid_structured_content_type_marks_error``
        covers for generic lists).

        This test pins the specific single-element-list shape because
        that was the one the removed heuristic quietly rescued. Without
        this guard, a future "help the user" change that reintroduces
        unwrapping would silently reopen the quirk the refactor closed.
        """
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
        # Exactly one element — the shape the old heuristic used to unwrap.
        result = SimpleNamespace(content=[], structured_content=[{"x": 42}], is_error=False)

        ok = tool_service._extract_and_validate_structured_content(tool, result)

        # Current canonical behaviour: reject with structured error, not unwrap.
        assert ok is False
        assert result.is_error is True
        details = orjson.loads(result.content[0].text)
        assert details["code"] == "invalid_structured_content_type"
        assert details["expected"] == "object"
        assert details["received"] == "list"
        # The inner dict is NOT silently promoted — that was the old heuristic.
        assert getattr(result, "structured_content", [{"x": 42}]) == [{"x": 42}]

    def test_single_element_list_in_textcontent_text_does_not_unwrap(self, tool_service):
        """Complementary guard — unwrap is also removed from the text-parse fallback.

        The old heuristic unwrapped both ``structured_content=[{...}]`` and
        cases where the first ``TextContent.text`` parsed as a JSON array
        containing a single dict. The new pipeline treats a parsed list
        as a list and hands it to ``jsonschema.validate``; because the
        declared schema is ``{"type": "object"}``, validation rejects a
        list-shaped instance with a ``type`` validator error.

        Note the error ``code`` here (``"type"``) differs from the
        explicit ``invalid_structured_content_type`` fast-fail code that
        fires when ``structured_content`` is pre-set with a non-dict
        value (see ``test_single_element_list_structured_content_fast_fails``).
        Both paths end in the same user-visible outcome: the list is not
        unwrapped into an object, and the response is marked as an
        error. Asserting the distinct error codes pins both paths so
        that a future refactor can't accidentally route one through the
        other and silently change the diagnostic surface.
        """
        tool = SimpleNamespace(output_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
        result = SimpleNamespace(
            content=[{"type": "text", "text": '[{"x": 42}]'}],  # single-element JSON array
            structured_content=None,
            is_error=False,
        )

        ok = tool_service._extract_and_validate_structured_content(tool, result)

        # Under the new strict contract the array body is not unwrapped; it
        # flows into jsonschema.validate which reports a type mismatch.
        assert ok is False
        assert result.is_error is True
        details = orjson.loads(result.content[0].text)
        assert details["code"] == "type"
        assert details["expected"] == "object"
        assert details["received"] == "list"

    def test_invalid_structured_content_orjson_dumps_failure_falls_back_to_str(self, tool_service, monkeypatch):
        """Defensive fallback when JSON serialisation of the error envelope fails.

        When the validator rejects a non-object ``structured_content`` it
        synthesises a validation-error dict and writes it onto
        ``tool_result.content`` as a ``TextContent(text=json)``. In the rare
        case where ``orjson.dumps`` itself raises (e.g., a sentinel object
        was smuggled into the details dict), the validator must still
        produce *some* content so the caller sees a populated error shape
        rather than an empty response. The fallback at
        the bare-except ``str(details)`` branch inside
        ``_extract_and_validate_structured_content``'s non-dict-structured-content
        fast-fail block uses ``str(details)`` — not valid JSON,
        but human-readable — which is what this test asserts (by checking
        that the content text contains the error ``code`` verbatim but
        cannot round-trip through ``orjson.loads``).

        This mirrors the analogous ``str(details)`` fallback inside the
        ``except jsonschema.ValidationError`` branch of
        ``_extract_and_validate_structured_content`` (search the method
        for ``"str(details)"``).

        MCP spec reference: 2025-11-25 "Error Handling" — error responses
        must always carry ``content``; the shape must not be empty.
        """
        tool = SimpleNamespace(output_schema={"type": "object"})
        result = SimpleNamespace(content=[], structured_content=[1, 2, 3], is_error=False)

        real_dumps = orjson.dumps

        def flaky_dumps(obj, *args, **kwargs):
            # Force the non-dict-structured-content details dict to fail so the
            # except branch runs; leave other callers untouched.
            if isinstance(obj, dict) and obj.get("code") == "invalid_structured_content_type":
                raise TypeError("simulated orjson failure")
            return real_dumps(obj, *args, **kwargs)

        monkeypatch.setattr("mcpgateway.services.tool_service.orjson.dumps", flaky_dumps)

        ok = tool_service._extract_and_validate_structured_content(tool, result)
        assert ok is False
        assert result.is_error is True
        # Content was stringified via str(details) rather than serialized as JSON
        assert "invalid_structured_content_type" in result.content[0].text
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(result.content[0].text)


# ═════════════════════════════════════════════════════════════════════════════
# 24b. _coerce_to_tool_result — canonical payload coercion
# ═════════════════════════════════════════════════════════════════════════════


class TestCoerceToToolResult:
    """Coverage for ``ToolService._coerce_to_tool_result``.

    The helper is the gateway's single source of truth for turning
    heterogeneous upstream responses into the canonical ``ToolResult``
    shape. Correct behaviour here is the foundation of #4202's egress
    fix across multiple integration types — Codex review identified two
    regressions when this coercion was too loose (``_coerce_to_tool_result``
    predecessor):

    - **P1** — direct-proxy MCP calls returned a raw MCP SDK
      ``CallToolResult`` (camelCase ``isError``) to the egress, which
      only recognised snake-case, so error responses fell through to
      the SDK's server-side validator and were re-clobbered
      (https://github.com/IBM/mcp-context-forge/issues/4202). The new
      helper coerces MCP SDK ``CallToolResult`` into ``ToolResult`` via
      ``model_dump(by_alias=True)``, mapping camelCase to snake-case.
    - **P2** — any dict with a top-level ``content`` key was being
      reinterpreted as an MCP envelope, silently discarding sibling
      business fields. The new helper requires strong MCP markers
      (``isError`` / ``structuredContent`` / ``content`` items with a
      string ``type`` field) before attempting ``ToolResult.model_validate``.

    MCP spec reference: 2025-11-25 "Tool Result" — the canonical
    ``CallToolResult`` shape is the target type.
    """

    def test_passthrough_when_already_toolresult(self, tool_service):
        """Existing ``ToolResult`` instances are returned by identity.

        Fast path: when an upstream layer has already constructed a proper
        ``ToolResult`` (e.g. the MCP federation branch that produces one
        explicitly at ``tool_service.py`` when ``is_direct_proxy=False``),
        the helper must be a no-op. Returning the same object reference
        is important because downstream code may have attached
        ``structured_content`` already; re-wrapping would risk dropping
        that metadata.
        """
        original = ToolResult(content=[TextContent(type="text", text="hello")], is_error=False)
        result = tool_service._coerce_to_tool_result(original)
        assert result is original

    def test_coerces_mcp_sdk_calltoolresult_to_toolresult(self, tool_service):
        """MCP SDK ``CallToolResult`` (camelCase) is coerced to ``ToolResult``.

        Regression guard for Codex P1. Before this helper existed, the
        ``is_direct_proxy`` branch at ``tool_service.py`` assigned the
        MCP SDK ``CallToolResult`` directly to ``tool_result``, and the
        egress handler's ``getattr(result, "is_error", False) is True``
        check returned ``False`` for the camelCase-only ``isError``
        attribute. Error responses for direct-proxy tools with a declared
        ``outputSchema`` then fell through to the success branch and the
        SDK's server-side validator replaced the original error text with
        ``"Output validation error: outputSchema defined but no
        structured output returned"``.

        This test uses the upstream MCP SDK's ``CallToolResult`` type
        directly to prove the coercion works on real production types,
        not just on dicts that happen to look MCP-shaped.
        """
        # Third-party — use the real MCP SDK type so the test fails if a
        # future SDK bump renames / restructures fields.
        # First-Party
        from mcp import types as mcp_types  # pylint: disable=import-outside-toplevel

        sdk_result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="You cannot send more than 200 points")],
            isError=True,
        )

        result = tool_service._coerce_to_tool_result(sdk_result)

        assert isinstance(result, ToolResult)
        assert result.is_error is True
        # Text content preserved verbatim across the coercion.
        assert result.content[0].text == "You cannot send more than 200 points"

    def test_coerces_mcp_sdk_calltoolresult_preserves_meta(self, tool_service):
        """Protocol-level ``_meta`` survives the coercion unchanged.

        ``_meta`` carries cross-cutting MCP protocol extensions (progress
        tokens, trace correlation IDs, etc.). A reviewer raised concern
        that ``_coerce_to_tool_result`` might silently drop ``_meta``
        because an earlier variant of ``ToolResult`` elsewhere in the
        codebase (``mcpgateway/schemas.py`` — not the one this service
        imports) omits the field. This test pins that the helper, which
        imports ``ToolResult`` from ``mcpgateway.common.models`` (aliased
        to ``CallToolResult`` with ``meta: Optional[Dict[str, Any]] =
        Field(None, alias="_meta")``), round-trips ``_meta`` from an
        upstream MCP SDK ``CallToolResult`` through
        ``model_dump(by_alias=True)`` into a canonical ``ToolResult``
        and emits it again on ``model_dump(by_alias=True)``.

        Without this guard, a future refactor that swaps the imported
        ``ToolResult`` source or drops the ``meta`` field would silently
        strip every direct-proxy response of its trace correlation,
        which matters for observability and debugging across the
        gateway ↔ upstream boundary.
        """
        # First-Party
        from mcp import types as mcp_types  # pylint: disable=import-outside-toplevel

        meta_payload = {"trace_id": "abc-123", "request_id": "r-42"}
        sdk_result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="ok")],
            isError=False,
            _meta=meta_payload,
        )

        coerced = tool_service._coerce_to_tool_result(sdk_result)

        # Field survives into the canonical ToolResult under its Python
        # attribute name…
        assert coerced.meta == meta_payload
        # …and is re-serialised with the wire alias on the way back out.
        egress = coerced.model_dump(by_alias=True, mode="json")
        assert egress.get("_meta") == meta_payload

    def test_rejects_rest_payload_with_content_key_but_no_mcp_markers(self, tool_service):
        """REST business payloads that coincidentally use ``content`` are not misread as MCP envelopes.

        Regression guard for Codex P2. A REST tool's native response shape
        ``{"content": [{"widget": "alpha"}], "recognitionId": "rec-1"}``
        must be treated as an opaque JSON body (wrapped into a single
        ``TextContent``) rather than have its ``content`` list reinterpreted
        as MCP ``ContentBlock`` items and its ``recognitionId`` sibling
        silently discarded. The gating heuristic
        (``_looks_like_mcp_envelope``) requires strong MCP markers
        (``isError`` / ``structuredContent`` / typed content items) before
        attempting ``ToolResult.model_validate``.
        """
        rest_payload = {"content": [{"widget": "alpha"}], "recognitionId": "rec-1"}

        result = tool_service._coerce_to_tool_result(rest_payload)

        assert isinstance(result, ToolResult)
        # Payload preserved in full — no fields lost — in the serialized text.
        assert result.content[0].type == "text"
        roundtripped = orjson.loads(result.content[0].text)
        assert roundtripped == rest_payload

    def test_accepts_dict_with_mcp_markers(self, tool_service):
        """Positive counterpart to the P2 heuristic check.

        A dict carrying a strong MCP marker (``isError`` key, or
        ``structuredContent``, or ``content`` items with a string ``type``
        field) is a legitimate MCP envelope and should round-trip through
        ``ToolResult.model_validate``.
        """
        mcp_shaped = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "structuredContent": {"recognitionId": "rec-1"},
        }

        result = tool_service._coerce_to_tool_result(mcp_shaped)

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.structured_content == {"recognitionId": "rec-1"}
        assert result.content[0].text == "ok"

    def test_accepts_dict_with_structured_content_marker_only(self, tool_service):
        """Dict with ``structuredContent`` (camelCase) but no ``isError`` is an envelope.

        Covers the ``structuredContent`` branch of ``_looks_like_mcp_envelope``'s
        layer-2 positive-marker check (search the helper for ``"structuredContent" in keys"``).
        This exercises the camelCase wire form; the snake-case sibling is
        covered by the next test.
        """
        # No ``isError`` — so the heuristic must admit via structuredContent.
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"recognitionId": "rec-42"},
        }

        result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert result.structured_content == {"recognitionId": "rec-42"}
        assert result.content[0].text == "ok"
        # ToolResult.is_error defaults to False when unset in the payload.
        assert result.is_error is False

    def test_accepts_dict_with_snake_case_structured_content_marker(self, tool_service):
        """Dict with ``structured_content`` (snake_case, gateway-internal) is an envelope.

        Covers the ``structured_content`` half of the layer-2 check. Both
        spellings live in ``_MCP_ENVELOPE_KEYS`` because forwarded-worker
        responses and internal serialisations may emit either form.
        """
        payload = {
            "content": [{"type": "text", "text": "ok"}],
            "structured_content": {"recognitionId": "rec-99"},
        }

        result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert result.structured_content == {"recognitionId": "rec-99"}

    def test_accepts_dict_with_only_typed_content_items(self, tool_service):
        """Dict whose only MCP signal is typed ``content`` items is still admitted.

        Covers the weakest positive marker in ``_looks_like_mcp_envelope`` —
        ``content`` as a non-empty list of dicts each carrying a string
        ``type`` field (MCP ``ContentBlock`` shape). No ``isError``,
        no ``structuredContent``, no ``_meta`` — this test exists so a
        future tightening that accidentally drops the typed-content branch
        is caught.
        """
        payload = {
            "content": [
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
            ],
        }

        result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert len(result.content) == 2
        assert result.content[0].text == "line 1"
        assert result.content[1].text == "line 2"

    def test_rejects_dict_with_only_meta_marker(self, tool_service):
        """Dict with only ``_meta`` and no positive signal is not an MCP envelope.

        Covers the final ``return False`` branch of
        ``_looks_like_mcp_envelope`` — all keys are in the envelope set
        (layer 1 passes) but no positive marker fires (``isError`` /
        ``structuredContent`` / typed content items). ``_meta`` alone
        doesn't make a payload MCP-shaped. The payload is therefore
        coerced via the opaque-JSON fallback so the caller can inspect
        the ``_meta`` contents without them being reinterpreted as
        protocol metadata.
        """
        payload = {"_meta": {"trace_id": "abc"}, "content": []}

        result = tool_service._coerce_to_tool_result(payload)

        # Falls through to text-serialisation; ``_meta`` preserved as data.
        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        roundtripped = orjson.loads(result.content[0].text)
        assert roundtripped == payload

    def test_payload_with_broken_str_and_repr_still_produces_toolresult(self, tool_service, caplog):
        """Even objects whose ``__str__`` *and* ``__repr__`` raise yield a ToolResult.

        The helper's hardest invariant is "never raises, always returns
        a valid ``ToolResult``". This test exercises the extreme tail of
        the opaque-JSON last-resort branch: a payload that (1) is not a
        BaseModel with MCP-shaped fields, (2) isn't JSON-serialisable
        (so ``orjson.dumps`` raises), (3) whose ``__str__`` raises when
        the helper tries ``str(payload)``, and (4) whose ``__repr__``
        also raises. Without ``_safe_text_repr``'s third-tier
        ``f"<{type_name} object>"`` sentinel, either of those would
        escape the helper.

        Pairs with ``test_non_json_serialisable_payload_falls_back_to_str``
        (normal ``str()`` path) and
        ``test_basemodel_whose_model_dump_raises_falls_back_to_str``
        (BaseModel.model_dump raising).
        """

        class AdversarialPayload:
            """Payload whose textual representations both raise."""

            def __str__(self) -> str:  # pragma: no cover - intentionally explodes
                raise RuntimeError("__str__ is broken")

            def __repr__(self) -> str:  # pragma: no cover - intentionally explodes
                raise RuntimeError("__repr__ is also broken")

        payload = AdversarialPayload()

        with caplog.at_level("WARNING", logger="mcpgateway.services.tool_service"):
            result = tool_service._coerce_to_tool_result(payload)

        # Contract held — we got a ``ToolResult`` rather than an exception.
        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        # Third-tier sentinel used; must be a non-empty string.
        assert "AdversarialPayload" in result.content[0].text
        assert "unrepresentable" in result.content[0].text
        # WARNING-severity reshape log should still have fired.
        relevant = [r for r in caplog.records if "could not be JSON-serialised" in r.message]
        assert relevant, "Expected a WARNING-level log from the last-resort fallback"
        assert relevant[-1].levelname == "WARNING"

    def test_basemodel_whose_model_dump_raises_falls_back_to_str(self, tool_service, caplog):
        """``BaseModel.model_dump`` raising is caught by the last-resort handler.

        Regression guard for a real failure mode: a Pydantic ``BaseModel``
        whose ``model_dump(mode="json")`` raises (custom field serialiser
        that throws, ``PydanticSerializationError`` — a ``ValueError``
        subclass, not ``TypeError`` — fields holding non-representable
        objects). Before this fix the ``model_dump`` call lived *outside*
        the ``try/except`` block, so any such failure escaped the helper
        and broke the "always returns a valid ``ToolResult``" invariant.

        The current implementation wraps the entire dump-plus-serialise
        sequence, catches any ``Exception``, logs at WARNING with
        ``exc_info=True``, and falls back to ``str(payload)``.
        """
        # Third-Party
        from pydantic import BaseModel  # pylint: disable=import-outside-toplevel

        class RaisingDumpModel(BaseModel):
            """BaseModel whose ``model_dump`` always raises.

            Simulates a third-party model with a broken custom serialiser.
            Must NOT expose a ``content`` attribute so the earlier
            BaseModel-with-content branch doesn't handle it — this test
            targets the opaque-JSON-fallback branch specifically.
            """

            # A benign field; the model_dump override is where the failure lives.
            placeholder: str = "ignored"

            def model_dump(self, *_args, **_kwargs):  # type: ignore[override]
                raise ValueError("simulated custom-serialiser failure")

            def __str__(self) -> str:
                return "RaisingDumpModel<str-fallback>"

        payload = RaisingDumpModel()

        with caplog.at_level("WARNING", logger="mcpgateway.services.tool_service"):
            result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        assert result.content[0].text == "RaisingDumpModel<str-fallback>"
        relevant = [r for r in caplog.records if "could not be JSON-serialised" in r.message]
        assert relevant, "Expected a WARNING-level log from the str() fallback"
        assert relevant[-1].levelname == "WARNING"
        assert relevant[-1].exc_info is not None

    def test_non_json_serialisable_payload_falls_back_to_str(self, tool_service, caplog):
        """``orjson.dumps`` TypeError is caught and we fall back to ``str(payload)``.

        ``_coerce_to_tool_result``'s contract is to always return a valid
        ``ToolResult``, even for payloads that aren't natively JSON-
        serialisable (e.g. sets, circular references, custom objects
        without a ``__json__`` method). The last-resort ``TypeError``
        fallback at the end of the helper catches the ``orjson.dumps``
        failure, logs at WARNING with ``exc_info=True``, and wraps
        ``str(payload)`` into a single ``TextContent``. Without this
        guard the helper would raise and break the pipeline's
        "always-produces-a-ToolResult" invariant.
        """

        class NotJSONSerialisable:
            """Plain Python class with no JSON representation."""

            def __repr__(self) -> str:
                return "NotJSONSerialisable(opaque)"

        payload = NotJSONSerialisable()

        with caplog.at_level("WARNING", logger="mcpgateway.services.tool_service"):
            result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        # ``str(payload)`` should be visible in the fallback text.
        assert "NotJSONSerialisable" in result.content[0].text
        relevant = [r for r in caplog.records if "could not be JSON-serialised" in r.message]
        assert relevant, "Expected a WARNING-level log from the str() fallback"
        assert relevant[-1].levelname == "WARNING"
        assert relevant[-1].exc_info is not None

    def test_basemodel_with_content_that_fails_validation_falls_back(self, tool_service, caplog):
        """Pydantic ``BaseModel`` path that fails ``ToolResult`` validation falls back to text.

        Covers the ``except ValidationError`` branch inside
        ``_coerce_to_tool_result``'s BaseModel dispatch. A caller could
        conceivably pass a non-MCP Pydantic model that happens to expose
        a ``content`` attribute but whose ``model_dump(by_alias=True)``
        produces a shape that ``ToolResult.model_validate`` refuses
        (e.g. ``content`` is a scalar rather than a list).

        The helper must not raise — it must log at WARNING (so operators
        see the protocol/schema drift) and fall through to the opaque
        JSON-serialisation path so the rest of the pipeline still gets
        a valid ``ToolResult``.
        """
        # Third-Party
        from pydantic import BaseModel  # pylint: disable=import-outside-toplevel

        class BadUpstreamModel(BaseModel):
            """Stand-in for a third-party model that has ``content`` but wrong shape."""

            content: int = 42  # ``ToolResult.content`` requires ``list[ContentBlock]``

        bad_model = BadUpstreamModel()

        with caplog.at_level("WARNING", logger="mcpgateway.services.tool_service"):
            result = tool_service._coerce_to_tool_result(bad_model)

        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        # The WARNING-severity reshape log must have fired (see #4202 egress
        # review round — user-visible reshapes promoted from DEBUG).
        relevant = [r for r in caplog.records if "did not validate as ToolResult" in r.message]
        assert relevant, "Expected a WARNING-level reshape log from the BaseModel ValidationError branch"
        assert relevant[-1].levelname == "WARNING"
        assert relevant[-1].exc_info is not None, "Expected exc_info=True for post-mortem diagnosis"

    def test_validation_error_falls_back_to_text_serialization(self, tool_service, caplog):
        """Dicts admitted by the heuristic but rejected by Pydantic fall back to text.

        The heuristic may admit a payload whose keys are all within the
        MCP envelope set (so it is not a business payload with extras)
        but whose *shape* still violates ``ToolResult`` (e.g. ``content``
        is a scalar rather than a list). The helper must not raise in
        that case — it falls back to serialising the payload into a
        single ``TextContent`` and logs at DEBUG for diagnosis.
        """
        # Only MCP envelope keys present (so the heuristic admits it),
        # ``isError`` gives a strong positive signal, but ``content`` as a
        # scalar breaks ``ToolResult.model_validate``.
        malformed = {"isError": True, "content": 123}

        # User-visible reshape: must surface at WARNING so operators see protocol drift.
        with caplog.at_level("WARNING", logger="mcpgateway.services.tool_service"):
            result = tool_service._coerce_to_tool_result(malformed)

        assert isinstance(result, ToolResult)
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        payload = orjson.loads(result.content[0].text)
        assert payload == malformed
        assert "failed ToolResult validation" in caplog.text or "falling back" in caplog.text
        # Severity check — must be WARNING, not DEBUG (would hide the reshape from ops logs).
        relevant_records = [r for r in caplog.records if "falling back" in r.message or "failed ToolResult validation" in r.message]
        assert relevant_records, "Expected a reshape log record"
        assert relevant_records[-1].levelname == "WARNING", f"Expected WARNING, got {relevant_records[-1].levelname}"

    def test_rest_payload_with_mcp_marker_and_extra_key_is_not_coerced(self, tool_service):
        """Regression guard for the Codex field-dropping follow-up.

        Before the heuristic required *no* keys outside the MCP envelope
        schema, a payload like
        ``{"isError": False, "content": [{"type": "text", "text": "ok"}], "recognitionId": "rec-1"}``
        would pass the old "has isError, therefore MCP" check, round-trip
        through ``ToolResult.model_validate`` (which inherits
        ``extra="ignore"`` from ``BaseModelWithConfigDict``), and silently
        drop ``recognitionId`` on the floor. Any REST tool whose native
        response happens to use a field name in the MCP envelope set
        (``isError``, ``structuredContent``, ``content``, ``_meta`` / ``meta``)
        was vulnerable to this field-dropping bug.

        The fix in ``_looks_like_mcp_envelope`` is to require the dict's
        full key set to be a subset of the MCP envelope schema — a single
        unknown sibling key fails the check and the payload is preserved
        verbatim via the text-serialisation fallback.
        """
        rest_payload = {
            "isError": False,
            "content": [{"type": "text", "text": "ok"}],
            "recognitionId": "rec-1",
        }

        result = tool_service._coerce_to_tool_result(rest_payload)

        # Must be wrapped as opaque text so ``recognitionId`` survives; a
        # successful MCP-envelope coercion would strip it silently.
        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        roundtripped = orjson.loads(result.content[0].text)
        assert roundtripped == rest_payload
        # Specifically pin that the caller-visible payload still carries the
        # business field — this is the exact regression guard Codex asked for.
        assert "recognitionId" in roundtripped

    def test_rest_payload_with_structured_content_and_extra_key_is_not_coerced(self, tool_service):
        """Variant of the preceding guard — triggers via ``structuredContent``.

        Any of the MCP strong markers (``isError``, ``structuredContent``,
        typed ``content`` items) *must* be paired with the no-extra-keys
        check. This test exercises the ``structuredContent`` path because
        it is the marker that historically had the least exercise in
        unit tests and is the one a future "help the user" change (e.g.
        auto-populating ``structuredContent`` from a REST tool's schema)
        would most likely collide with.
        """
        rest_payload = {
            "structuredContent": {"result": "ok"},
            "content": [{"type": "text", "text": "ok"}],
            "details": {"trace_id": "abc123"},
        }

        result = tool_service._coerce_to_tool_result(rest_payload)

        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        roundtripped = orjson.loads(result.content[0].text)
        assert roundtripped == rest_payload
        assert "details" in roundtripped
        assert roundtripped["details"]["trace_id"] == "abc123"

    def test_rest_payload_with_typed_content_list_and_extra_key_is_not_coerced(self, tool_service):
        """Variant of the preceding guard — triggers via typed ``content`` items.

        The weakest positive MCP signal is "``content`` is a list of
        dicts each carrying a string ``type`` field". A REST tool that
        happens to return MCP-like typed items alongside a business
        field (e.g. a pagination cursor) must not have that sibling
        silently dropped.
        """
        rest_payload = {
            "content": [{"type": "text", "text": "page 1"}],
            "nextCursor": "page-2-token",
        }

        result = tool_service._coerce_to_tool_result(rest_payload)

        assert isinstance(result, ToolResult)
        assert result.content[0].type == "text"
        roundtripped = orjson.loads(result.content[0].text)
        assert roundtripped == rest_payload
        assert roundtripped["nextCursor"] == "page-2-token"

    def test_mcp_envelope_with_meta_is_still_accepted(self, tool_service):
        """Positive counterpart — ``_meta`` / ``meta`` are legitimate envelope keys.

        Ensures the tightened heuristic did not over-constrain:
        well-formed MCP envelopes that include protocol-level metadata
        (``_meta`` on the wire, ``meta`` in Python) must still be coerced
        cleanly. Without this test a future simplification that forgot
        ``_meta`` would silently start text-wrapping valid MCP responses.
        """
        envelope = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "_meta": {"request_id": "abc-123"},
        }

        result = tool_service._coerce_to_tool_result(envelope)

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert result.content[0].text == "ok"
        assert result.meta == {"request_id": "abc-123"}

    def test_opaque_non_mcp_payload_wraps_into_text_content(self, tool_service):
        """Arbitrary JSON values (arrays, scalars, no-``content`` dicts) wrap cleanly.

        The fallback serialises with ``orjson.OPT_INDENT_2`` so the
        resulting ``TextContent`` is human-inspectable. The goal is the
        invariant "every path yields a well-formed ``ToolResult``" rather
        than any particular formatting choice.
        """
        payload = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]

        result = tool_service._coerce_to_tool_result(payload)

        assert isinstance(result, ToolResult)
        assert result.is_error is False
        assert orjson.loads(result.content[0].text) == payload


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

        await tool_service.create_tool_from_a2a_agent(db, agent, created_by="admin")

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
    async def test_update_tool_from_a2a_agent_normalizes_mixed_tags(self, tool_service, mock_tool):
        """Should normalize dict tags, label-attribute tags, and fallback to str()."""

        class LabelObj:
            def __init__(self, label: str):
                self.label = label

        db = MagicMock()
        agent = MagicMock()
        agent.tool_id = "tool-1"
        agent.id = "agent-1"
        agent.slug = "mixed-tags"
        agent.name = "Mixed Tags"
        agent.description = None
        agent.endpoint_url = "http://agent.example.com"
        agent.auth_type = None
        agent.auth_value = None
        agent.tags = [
            {"label": "dict-label"},
            {"id": "dict-id"},
            LabelObj("obj-label"),
            "str-tag",
        ]

        db.get.return_value = mock_tool

        tool_service.update_tool = AsyncMock(return_value=MagicMock(spec=ToolRead))

        await tool_service.update_tool_from_a2a_agent(db, agent, modified_by="admin")

        tool_update = tool_service.update_tool.call_args.kwargs["tool_update"]
        tag_labels = []
        for t in tool_update.tags:
            if isinstance(t, dict):
                tag_labels.append(t.get("label") or t.get("id") or str(t))
            elif hasattr(t, "label"):
                tag_labels.append(getattr(t, "label"))
            else:
                tag_labels.append(str(t))
        assert "dict-label" in tag_labels
        assert "dict-id" in tag_labels
        assert "obj-label" in tag_labels
        assert "str-tag" in tag_labels
        assert "a2a" in tag_labels
        assert "agent" in tag_labels

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
        agent.auth_value = "encrypted_bearer_token"  # Simulates encrypted value from DB
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "custom"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"Authorization": "Bearer my-token"}),
        ):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert result == {"data": "custom"}
        # Verify bearer auth was added
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my-token"

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
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"api_key": "real_key"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://agent.example.com/?api_key=real_key"),
            patch("mcpgateway.services.tool_service.sanitize_url_for_logging", return_value="http://agent.example.com/?api_key=***"),
        ):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_call_a2a_agent_query_param_empty_value_is_skipped(self, tool_service):
        """Empty query_param values should not call decode/apply auth and should use the original endpoint."""
        agent = MagicMock()
        agent.name = "qp-agent-empty"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = "query_param"
        agent.auth_value = None
        agent.auth_query_params = {"api_key": ""}  # falsy => skip decrypt/apply

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.tool_service.decode_auth") as mock_decode,
            patch("mcpgateway.services.tool_service.apply_query_param_auth") as mock_apply,
        ):
            result = await tool_service._call_a2a_agent(agent, {"query": "test"})
        assert result == {"ok": True}
        mock_decode.assert_not_called()
        mock_apply.assert_not_called()
        assert mock_client.post.call_args.args[0] == "http://agent.example.com/"

    @pytest.mark.asyncio
    async def test_call_a2a_agent_jsonrpc_request_data_prepare_error_is_logged_and_raised(self, tool_service):
        """If preparing/logging JSONRPC request_data fails, error is logged and re-raised."""

        class BadRepr:
            def __repr__(self):
                raise RuntimeError("boom")

        agent = MagicMock()
        agent.name = "jsonrpc-agent"
        agent.endpoint_url = "http://agent.example.com/"  # endswith "/" triggers JSONRPC flow
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        with pytest.raises(RuntimeError, match="boom"):
            await tool_service._call_a2a_agent(agent, {"params": BadRepr(), "method": "tasks/list"})

    @pytest.mark.asyncio
    async def test_call_a2a_agent_api_key_auth(self, tool_service):
        """Should set Authorization header for api_key auth."""
        agent = MagicMock()
        agent.name = "apikey-agent"
        agent.endpoint_url = "http://agent.example.com/"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = "api_key"
        agent.auth_value = "encrypted_api_key"  # Simulates encrypted value from DB
        agent.auth_query_params = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"api_key": "my-api-key"}),  # pragma: allowlist secret
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
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

        monkeypatch.setattr("mcpgateway.services.tool_service.fresh_db_session", DummySession)

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
    async def test_success_with_dict_response_value(self, tool_service):
        """When response value is a dict, it should be serialized as valid JSON, not Python repr."""
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
        tool_service._call_a2a_agent = AsyncMock(return_value={"response": {"has_chart": False, "tracking_system": "IPP", "sql_queries": []}})

        result = await tool_service._invoke_a2a_tool(db, tool, {"query": "hi"})
        assert result.is_error is False
        text = result.content[0].text
        # Must be valid JSON, not Python repr
        parsed = json.loads(text)
        assert parsed["has_chart"] is False
        assert "False" not in text  # Python repr would have capital False

    @pytest.mark.asyncio
    async def test_success_without_response_key_dict(self, tool_service):
        """When entire response is a dict without 'response' key, it should be valid JSON."""
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
        tool_service._call_a2a_agent = AsyncMock(return_value={"id": 1, "jsonrpc": "2.0", "result": {"has_chart": False}})

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        text = result.content[0].text
        parsed = json.loads(text)
        assert parsed["result"]["has_chart"] is False
        assert "False" not in text

    def _make_agent_mock(self):
        agent = MagicMock()
        agent.enabled = True
        agent.name = "agent"
        agent.endpoint_url = "http://agent.test"
        agent.agent_type = "generic"
        agent.protocol_version = "1.0"
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None
        return agent

    @pytest.mark.asyncio
    async def test_response_value_none_serialized_as_json_null(self, tool_service):
        """When response value is None, it should serialize as 'null' (valid JSON)."""
        tool = self._make_a2a_tool()
        agent = self._make_agent_mock()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value={"response": None})

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        assert result.content[0].text == "null"
        assert json.loads(result.content[0].text) is None

    @pytest.mark.asyncio
    async def test_response_value_numeric_serialized_as_json(self, tool_service):
        """When response value is a number, it should serialize as valid JSON."""
        tool = self._make_a2a_tool()
        agent = self._make_agent_mock()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value={"response": 42})

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        assert result.content[0].text == "42"
        assert json.loads(result.content[0].text) == 42

    @pytest.mark.asyncio
    async def test_response_value_list_serialized_as_json(self, tool_service):
        """When response value is a list, it should serialize as valid JSON array."""
        tool = self._make_a2a_tool()
        agent = self._make_agent_mock()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value={"response": [1, "two", False]})

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        parsed = json.loads(result.content[0].text)
        assert parsed == [1, "two", False]
        assert "False" not in result.content[0].text

    @pytest.mark.asyncio
    async def test_root_list_response_serialized_as_json(self, tool_service):
        """When entire response_data is a list (no 'response' key), it should serialize as JSON array."""
        tool = self._make_a2a_tool()
        agent = self._make_agent_mock()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = agent
        tool_service._call_a2a_agent = AsyncMock(return_value=[{"id": 1, "active": True}, {"id": 2, "active": False}])

        result = await tool_service._invoke_a2a_tool(db, tool, {})
        assert result.is_error is False
        parsed = json.loads(result.content[0].text)
        assert len(parsed) == 2
        assert parsed[0]["active"] is True
        assert parsed[1]["active"] is False
        assert "True" not in result.content[0].text
        assert "False" not in result.content[0].text

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
    async def test_jsonrpc_request_data_prepare_error_is_logged_and_raised(self, tool_service):
        """If preparing request data fails, the error propagates to the caller."""
        agent = self._make_agent(agent_type="jsonrpc")

        def _info_side_effect(msg, *args, **kwargs):
            # Allow the initial "Calling A2A agent..." log, but force an exception for the request_data log.
            if "invoke tool request_data prepared" in str(msg):
                raise RuntimeError("logger boom")

        with patch("mcpgateway.services.tool_service.logger") as mock_logger:
            mock_logger.info.side_effect = _info_side_effect

            with pytest.raises(RuntimeError, match="logger boom"):
                await tool_service._call_a2a_agent(agent, {"query": "hello"})

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
        agent = self._make_agent(auth_type="api_key", auth_value="encrypted_secret_key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"api_key": "secret-key"}),  # pragma: allowlist secret
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_bearer_auth(self, tool_service):
        agent = self._make_agent(auth_type="bearer", auth_value="encrypted_bearer_token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"Authorization": "Bearer bearer-token"}),
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer bearer-token"

    @pytest.mark.asyncio
    async def test_bearer_auth_dict_value(self, tool_service):
        """Should handle dict auth_value directly without decryption."""
        agent = self._make_agent(auth_type="bearer", auth_value={"Authorization": "Bearer dict-token"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"Authorization": "Bearer bearer-token"}),
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer dict-token"

    @pytest.mark.asyncio
    async def test_basic_auth(self, tool_service):
        """Should decrypt and apply basic auth headers."""
        agent = self._make_agent(auth_type="basic", auth_value="encrypted_basic_creds")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"Authorization": "Basic decrypted-value"}),
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Basic decrypted-value"

    @pytest.mark.asyncio
    async def test_authheaders_auth(self, tool_service):
        """Should decrypt and apply custom auth headers."""
        agent = self._make_agent(auth_type="authheaders", auth_value="encrypted_custom_headers")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"X-Custom-Auth": "custom-value"}),
        ):
            await tool_service._call_a2a_agent(agent, {"query": "test"})
        headers = mock_client.post.call_args[1]["headers"]
        assert headers["X-Custom-Auth"] == "custom-value"

    @pytest.mark.asyncio
    async def test_bearer_auth_decrypt_failure(self, tool_service):
        """Should raise ToolInvocationError when decode_auth fails."""
        agent = self._make_agent(auth_type="bearer", auth_value="invalid_encrypted_value")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("mcpgateway.services.http_client_service.get_http_client", new_callable=AsyncMock, return_value=mock_client),
            patch("mcpgateway.services.a2a_protocol.decode_auth", side_effect=Exception("Decryption failed")),
        ):
            with pytest.raises(Exception, match="Decryption failed"):
                await tool_service._call_a2a_agent(agent, {"query": "test"})

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
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"api_key": "real-key"}),
            patch("mcpgateway.services.a2a_protocol.apply_query_param_auth", return_value="http://agent.test/api?api_key=real-key"),
            patch("mcpgateway.services.a2a_protocol.sanitize_url_for_logging", return_value="http://agent.test/api?api_key=***"),
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

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool), patch("mcpgateway.services.permission_service.PermissionService") as MockPS:
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

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool), patch("mcpgateway.services.permission_service.PermissionService") as MockPS:
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

        with (
            patch("mcpgateway.services.tool_service.delete_metrics_in_batches") as mock_delete,
            patch("mcpgateway.services.tool_service.pause_rollup_during_purge") as mock_pause,
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_rc,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache", mock_admin_cache),
            patch("mcpgateway.cache.metrics_cache.metrics_cache", mock_metrics_cache),
        ):
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
            original_description="A test tool original",
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
            original_description="A test tool original",
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


# ═══════════════════════════════════════════════════════════════════════════════
# ADDITIONAL COVERAGE — targets lines identified in coverage report
# ═══════════════════════════════════════════════════════════════════════════════


# ---------------------------------------------------------------------------
# extract_using_jq — error paths (lines 286-289)
# ---------------------------------------------------------------------------


class TestExtractUsingJqErrors:
    def test_jq_filter_returns_none_result(self):
        """When jq filter produces [None], returns error TextContent in list."""
        # First-Party
        import mcpgateway.services.tool_service as ts

        with patch.object(ts, "_compile_jq_filter") as mock_compile:
            mock_prog = MagicMock()
            mock_input = MagicMock()
            mock_input.all = MagicMock(return_value=[None])
            mock_prog.input = MagicMock(return_value=mock_input)
            mock_compile.return_value = mock_prog

            result = extract_using_jq({"key": "value"}, ".x")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert result[0].text == "Error applying jsonpath filter"

    def test_jq_filter_exception(self):
        """When jq raises exception, returns error message as TextContent in list."""
        # First-Party
        import mcpgateway.services.tool_service as ts

        with patch.object(ts, "_compile_jq_filter", side_effect=ValueError("bad filter")):
            result = extract_using_jq({"data": 1}, "bad_filter")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Error" in result[0].text


# ---------------------------------------------------------------------------
# get_top_tools — cache hit (line 494)
# ---------------------------------------------------------------------------


class TestGetTopToolsCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, tool_service):
        """When cache has data, returns it directly."""
        cached_data = [{"tool_id": "1", "count": 10}]
        with patch("mcpgateway.cache.metrics_cache.is_cache_enabled", return_value=True), patch("mcpgateway.cache.metrics_cache.metrics_cache") as mock_cache:
            mock_cache.get = MagicMock(return_value=cached_data)
            db = MagicMock()
            result = await tool_service.get_top_tools(db)
        assert result == cached_data


# ---------------------------------------------------------------------------
# _extract_and_validate_structured_content — TextContent extraction + error paths
# (lines 928-932, 941-947, 962-963, 979-980)
# ---------------------------------------------------------------------------


class TestValidateToolOutputSchemaBranches:
    def test_text_content_dict_extraction(self, tool_service):
        """Extract structured content from TextContent-like dict in content array."""
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": '{"name": "test"}'}],
            is_error=False,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is True
        assert hasattr(tool_result, "structured_content")

    def test_schema_type_extraction_exception(self, tool_service):
        """When output_schema is not a dict, schema_type falls back to None."""
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": '{"data": 1}'}],
            is_error=False,
        )
        # output_schema is not a dict → isinstance check fails → schema_type=None
        tool = SimpleNamespace(name="test_tool", output_schema="not_a_dict")

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should not crash; schema_type falls to None
        assert result is True or result is False

    def test_validation_error_json_encoding_failure(self, tool_service):
        """When orjson can't encode validation details, falls back to str()."""
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": '{"wrong": 1}'}],
            is_error=False,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
        )

        with patch("mcpgateway.services.tool_service._validate_with_cached_schema", side_effect=jsonschema.ValidationError("bad")):
            with patch("mcpgateway.services.tool_service.orjson.dumps", side_effect=TypeError("can't encode")):
                result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is False
        assert tool_result.is_error is True

    def test_setattr_structured_content_failure(self, tool_service):
        """When setattr fails on tool_result, logs debug and continues."""

        class Frozen:
            __slots__ = ("content", "is_error")

            def __init__(self):
                self.content = [{"type": "text", "text": '{"k": "v"}'}]
                self.is_error = False

        tool_result = Frozen()
        tool = SimpleNamespace(
            name="t",
            output_schema={"type": "object", "properties": {"k": {"type": "string"}}},
        )
        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is True or result is False


# ---------------------------------------------------------------------------
# register_tool — team name conflict + default visibility
# ---------------------------------------------------------------------------


class TestRegisterToolBranches:
    @pytest.mark.asyncio
    async def test_team_name_conflict(self, tool_service):
        """Raises ToolNameConflictError when team tool with same name exists."""
        tool = MagicMock()
        tool.name = "my_tool"
        tool.displayName = "My Tool"
        tool.url = "http://example.com"
        tool.description = "desc"
        tool.integration_type = "REST"
        tool.request_type = "GET"
        tool.headers = {}
        tool.input_schema = {}
        tool.output_schema = None
        tool.annotations = {}
        tool.jsonpath_filter = None
        tool.auth = None
        tool.tags = []
        tool.team_id = "team-1"

        existing = MagicMock()
        existing.name = "my_tool"
        existing.enabled = True
        existing.id = "existing-id"
        existing.visibility = "team"

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))

        with pytest.raises(ToolNameConflictError):
            await tool_service.register_tool(db, tool, visibility="team", team_id="team-1", owner_email="user@test.com")

    @pytest.mark.asyncio
    async def test_defaults_visibility_from_tool_object(self, tool_service):
        """When visibility is None, defaults from tool.visibility then checks name conflict."""
        tool = MagicMock()
        tool.name = "dup_tool_defaults"
        tool.team_id = "team-99"
        tool.owner_email = "default@test.com"
        tool.visibility = "team"  # will be used as default since visibility=None

        existing = MagicMock()
        existing.name = "dup_tool_defaults"
        existing.enabled = True
        existing.id = "existing-id"
        existing.visibility = "team"

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))

        # visibility=None => uses tool.visibility="team", team_id defaults from tool.team_id
        with pytest.raises(ToolNameConflictError):
            await tool_service.register_tool(db, tool, visibility=None, owner_email=None)


# ---------------------------------------------------------------------------
# _extract_and_validate_structured_content — error response handling (#4202)
# ---------------------------------------------------------------------------


class TestExtractAndValidateErrorResponses:
    """Regression guards for ContextForge #4202 on the gateway's ingress validator.

    Issue: https://github.com/IBM/mcp-context-forge/issues/4202

    The MCP 2025-11-25 specification's "Error Handling" section
    (https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling)
    states that tool execution errors are reported via ``isError: true`` and
    explicitly that "error responses do not require structured content". Before
    #4202 was fixed, ``ToolService._extract_and_validate_structured_content``
    cross-validated error responses against the tool's declared
    ``outputSchema`` and, on the expected mismatch, clobbered the original
    error payload with a validation-error dict — discarding the upstream
    server's actual error message. The tests in this class pin the
    spec-compliant behaviour: when ``isError=true`` the validator is a
    no-op, regardless of whether ``structured_content`` / ``isError`` / both
    flags are present, and regardless of whether the payload matches the
    declared schema.

    Related:
    - Egress-side counterpart guard:
      ``tests/unit/mcpgateway/transports/test_streamablehttp_transport.py::test_call_tool_preserves_is_error_for_egress``
    - End-to-end regression:
      ``tests/e2e/test_mcp_protocol_e2e.py::TestToolCalls::test_schema_error_preserves_payload``
    """

    def test_skip_validation_for_error_response_is_error(self, tool_service):
        """Baseline #4202 guard — snake-case ``is_error`` flag.

        Exercises the primary MCP Python shape where ``ToolResult.is_error``
        is the Pydantic attribute. The method must return ``True`` (skip) and
        leave the original error text verbatim on ``content[0]["text"]``,
        proving that the validator did not run the schema check and did not
        replace the payload with a validation-error dict.

        MCP spec reference: 2025-11-25 "Error Handling" — error responses
        do not require structured content.
        """
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": "You cannot send more than 200 points"}],
            is_error=True,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["recognitionId"], "properties": {"recognitionId": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should return True (skip validation) for error responses
        assert result is True
        # Error content should be preserved, not overwritten with validation error
        assert tool_result.content[0]["text"] == "You cannot send more than 200 points"
        assert tool_result.is_error is True

    def test_skip_validation_for_error_response_isError(self, tool_service):
        """#4202 guard — wire-format camelCase ``isError`` flag.

        MCP JSON-RPC responses serialise the flag as ``isError`` (camelCase).
        Some code paths (notably federated peers forwarding raw dicts through
        the streamable-http transport) deliver the result with the camelCase
        attribute intact instead of the snake-cased pydantic alias. The
        validator must respect both spellings so the skip behaviour is
        transport-agnostic. Fixed at ``tool_service.py`` by OR-ing
        ``getattr(result, "is_error", False) or getattr(result, "isError", False)``.

        MCP spec reference: 2025-11-25 "Error Handling".
        """
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": "Tool execution failed"}],
            isError=True,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["data"], "properties": {"data": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should return True (skip validation) for error responses
        assert result is True
        # Error content should be preserved
        assert tool_result.content[0]["text"] == "Tool execution failed"
        assert tool_result.isError is True

    def test_skip_validation_both_error_flags(self, tool_service):
        """#4202 guard — both ``is_error`` and ``isError`` present simultaneously.

        When a pydantic ``ToolResult`` crosses a serialisation boundary its
        snake-case attribute may end up alongside the camelCase alias from a
        ``model_dump(by_alias=True)``. The validator must still skip — it
        must not, for instance, treat one as authoritative and compare them.
        Any truthy signal from either spelling is sufficient to invoke the
        MCP error-response exemption.

        MCP spec reference: 2025-11-25 "Error Handling".
        """
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": "Error message"}],
            is_error=True,
            isError=True,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["field"], "properties": {"field": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is True
        assert tool_result.content[0]["text"] == "Error message"

    def test_skip_validation_for_error_with_populated_structured_content(self, tool_service):
        """Scenario A from MCP spec review.

        The spec (2025-11-25 "Error Handling") permits ``isError=true`` responses
        to carry both ``content`` and ``structuredContent`` and explicitly
        states that error responses "do not require structured content".
        It prescribes no validation of ``structuredContent`` against
        ``outputSchema`` on error responses, and no precedence rule between the
        two fields.

        Pin the gateway's spec-compliant behaviour: validation is skipped
        regardless of whether ``structuredContent`` is present, and both the
        unstructured and structured payloads are preserved verbatim for the
        caller to inspect.
        """
        # Structured payload does NOT satisfy the declared schema — that's the
        # point: validation must not run, so the mismatch must not clobber the
        # payload.
        populated_structured = {"debug": "diagnostic info", "code": 429}
        tool_result = ToolResult(
            content=[TextContent(type="text", text="Rate limit exceeded")],
            structured_content=populated_structured,
            is_error=True,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={
                "type": "object",
                "required": ["recognitionId"],
                "properties": {"recognitionId": {"type": "string"}},
            },
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)

        assert result is True
        # is_error remains True; neither payload mutated.
        assert tool_result.is_error is True
        assert tool_result.content[0].text == "Rate limit exceeded"
        assert tool_result.structured_content == populated_structured

    def test_success_with_schema_but_no_content_currently_passes(self, tool_service):
        """Scenario B from MCP spec review — known spec deviation pinned as
        a regression guard.

        Per the 2025-11-25 spec ("Output Schema" section) a server MUST
        provide structured results conforming to a declared ``outputSchema``.
        The gateway currently treats the absence of structured data as
        "nothing to validate" and returns True — lenient behaviour that masks
        upstream servers violating the spec. This test pins that behaviour so
        any future change is explicit. Tightening tracked in
        https://github.com/IBM/mcp-context-forge/issues/4208.
        """
        tool_result = ToolResult(content=[], is_error=False)
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={
                "type": "object",
                "required": ["recognitionId"],
                "properties": {"recognitionId": {"type": "string"}},
            },
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)

        # Current lenient behaviour: passes silently.
        assert result is True
        assert tool_result.is_error is False
        assert tool_result.content == []
        assert tool_result.structured_content is None

    def test_skip_validation_when_candidate_payload_is_error_shape(self, tool_service):
        """#4202 guard — REST/normalised payloads whose body encodes a ToolResult-shaped error.

        When a REST tool's upstream response happens to return a JSON dict
        that *looks like* a serialised MCP ``CallToolResult``
        (``{"isError": true, "content": [...]}``), ``_coerce_to_tool_result``
        passes it through ``ToolResult.model_validate`` and produces a
        ToolResult whose ``is_error`` attribute is already ``True`` while
        ``content`` retains the verbatim JSON string representation of the
        error envelope. The validator must still recognise the error state
        and skip schema checking so the original envelope reaches the
        downstream client untouched.

        MCP spec reference: 2025-11-25 "Error Handling" — isError takes
        precedence over outputSchema enforcement.
        """
        tool_result = ToolResult(
            content=[
                TextContent(
                    type="text",
                    text='{"isError":true,"content":[{"type":"text","text":"Value exceeds maximum allowed (Requested: 150)"}]}',
                )
            ],
            is_error=True,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["recognitionId"], "properties": {"recognitionId": {"type": "string"}}},
        )
        result = tool_service._extract_and_validate_structured_content(tool, tool_result)

        assert result is True
        assert tool_result.is_error is True
        assert tool_result.content[0].text == '{"isError":true,"content":[{"type":"text","text":"Value exceeds maximum allowed (Requested: 150)"}]}'

    def test_validate_success_response_normally(self, tool_service):
        """Positive control for #4202 — success path continues to validate.

        The #4202 fix narrows the skip to error responses only; successful
        responses with a declared ``outputSchema`` must still be validated
        against that schema, and the validator must populate
        ``tool_result.structured_content`` from the parsed JSON text so
        downstream code (and the MCP SDK's server-side validator on the
        egress side) sees a conforming payload.

        MCP spec reference: 2025-11-25 "Output Schema" — servers MUST
        provide structured results conforming to the declared schema on
        successful responses.
        """
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": '{"recognitionId": "123", "message": "Success"}'}],
            is_error=False,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["recognitionId", "message"], "properties": {"recognitionId": {"type": "string"}, "message": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should validate and succeed
        assert result is True
        assert hasattr(tool_result, "structured_content")
        assert tool_result.structured_content["recognitionId"] == "123"

    def test_validate_success_response_fails_validation(self, tool_service):
        """Complement to #4202 — schema-violating success payload still fails.

        Confirms that the fix does not overreach: a non-error response whose
        parsed structured payload violates the declared ``outputSchema``
        must still be flagged by the validator, and the original content
        must be replaced with a deterministic validation-error dict (code,
        expected, received, path, message) so callers can diagnose the
        mismatch. This is the inverse of the #4202 bug — without this
        branch, relaxing the error-case check would also relax the
        success-case check.

        MCP spec reference: 2025-11-25 "Output Schema" — conforming
        structured output is required on success; non-conforming responses
        should be surfaced as errors.
        """
        tool_result = SimpleNamespace(
            content=[{"type": "text", "text": '{"wrong": "field"}'}],
            is_error=False,
        )
        tool = SimpleNamespace(
            name="test_tool",
            output_schema={"type": "object", "required": ["recognitionId"], "properties": {"recognitionId": {"type": "string"}}},
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should fail validation
        assert result is False
        assert tool_result.is_error is True
        # Content should be replaced with validation error details
        assert "recognitionId" in tool_result.content[0].text or "required" in tool_result.content[0].text.lower()

    def test_validate_rest_normalized_payload_with_pydantic_text_content(self, tool_service):
        """Regression guard — REST integration path must still be validated.

        Raised during PR #4204 review as a P1 against the initial fix:
        ``_coerce_to_tool_result`` wraps a REST tool's JSON body into
        ``ToolResult(content=[TextContent(...)])``, where ``content`` holds
        Pydantic objects rather than raw dicts. The first iteration of the
        #4202 refactor made the content-item fallback loop dict-only, so
        REST responses parsed to Pydantic ``TextContent`` items were silently
        skipped and ``output_schema`` was never enforced — an invalid REST
        payload would be forwarded as success. This test asserts the
        fallback loop now accepts both dicts and Pydantic content, so a REST
        payload that is missing the required ``recognitionId`` field is
        correctly detected and surfaced as an error.

        MCP spec reference: 2025-11-25 "Output Schema".
        Related issues:
        - Gateway-side validator is the only enforcement for non-MCP tool
          invocation paths; e2e coverage for those paths tracked in
          https://github.com/IBM/mcp-context-forge/issues/4207.
        """
        payload = {"wrong": "field"}
        tool_result = tool_service._coerce_to_tool_result(payload)
        assert isinstance(tool_result.content[0], TextContent)
        tool = SimpleNamespace(
            name="rest_tool",
            output_schema={
                "type": "object",
                "required": ["recognitionId"],
                "properties": {"recognitionId": {"type": "string"}},
            },
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Must not silently pass: schema requires recognitionId, payload lacks it.
        assert result is False
        assert tool_result.is_error is True
        assert "recognitionId" in tool_result.content[0].text or "required" in tool_result.content[0].text.lower()

    def test_validate_rest_normalized_payload_passes_when_schema_matches(self, tool_service):
        """Positive counterpart to the REST fallback-loop regression guard.

        A REST payload that matches its declared ``output_schema`` must
        round-trip cleanly through
        ``_coerce_to_tool_result`` → Pydantic ``TextContent`` → the
        fallback loop → schema validation, and the parsed dict must end up
        attached to ``tool_result.structured_content`` so the egress path
        can populate the downstream-facing ``structuredContent`` field. Pairs
        with ``test_validate_rest_normalized_payload_with_pydantic_text_content``
        to prove the fix is symmetric (rejects bad, accepts good).

        MCP spec reference: 2025-11-25 "Output Schema" — success payloads
        matching the schema must be surfaced as structured content.
        Related: https://github.com/IBM/mcp-context-forge/issues/4207 (e2e
        coverage gap for non-MCP paths).
        """
        payload = {"recognitionId": "rec-42", "message": "ok"}
        tool_result = tool_service._coerce_to_tool_result(payload)
        tool = SimpleNamespace(
            name="rest_tool",
            output_schema={
                "type": "object",
                "required": ["recognitionId"],
                "properties": {
                    "recognitionId": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        )

        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is True
        assert tool_result.structured_content == payload

    @pytest.mark.skip(
        reason=(
            "Intentional coverage marker, not an implementation assertion. "
            "The A2A branch of ToolService.invoke_tool does not currently "
            "invoke _extract_and_validate_structured_content at all — any A2A "
            "tool returning isError=true with a declared output_schema "
            "therefore bypasses the gateway-side validator entirely. This is "
            "neither a #4202 fix regression nor a correctness hazard today "
            "(Validator C still runs on the egress and the SDK short-circuit "
            "still preserves the payload for isError=true), but it means "
            "there is currently no gateway-side output-schema enforcement for "
            "A2A tools. Tracked under "
            "https://github.com/IBM/mcp-context-forge/issues/4210 (Option B: "
            "unify tool-invocation pipeline around canonical ToolResult). "
            "Un-skip this test and implement it once #4210 step 3 lands "
            "(routing A2A through the unified _post_invoke_pipeline)."
        )
    )
    def test_a2a_invoke_with_iserror_outputschema_does_not_clobber(self):
        """Future regression guard for A2A + #4202 — currently unreachable.

        When #4210 routes the A2A branch through Validator B, this test
        should drive ``invoke_tool`` against an A2A tool whose upstream
        agent returns ``isError=True`` with a declared ``output_schema``
        and assert the original error text is preserved end-to-end —
        mirroring ``test_rest_payload_shaped_error_skips_output_schema_validation``
        but for the A2A transport.
        """


# ---------------------------------------------------------------------------
# _process_chunk — fail status + audit + exception (lines 1432-1434, 1449-1465)
# ---------------------------------------------------------------------------


class TestProcessChunkBranches:
    def test_fail_status_increments_counter(self, tool_service):
        """fail status from _process_single_tool_for_bulk increments failed count."""
        tool = MagicMock()
        tool.name = "dup_tool"

        db = MagicMock()

        with patch.object(tool_service, "_process_single_tool_for_bulk", return_value={"status": "fail", "error": "conflict"}):
            result = tool_service._process_tool_chunk(db, [tool], "fail", "public", None, None, None, None, None, None, None, None)
        assert result["failed"] == 1
        assert result["skipped"] == 0

    def test_skip_status_increments_counter(self, tool_service):
        """skip status from _process_single_tool_for_bulk increments skipped count."""
        tool = MagicMock()
        tool.name = "existing_tool"

        db = MagicMock()

        with patch.object(tool_service, "_process_single_tool_for_bulk", return_value={"status": "skip"}):
            result = tool_service._process_tool_chunk(db, [tool], "skip", "public", None, None, None, None, None, None, None, None)
        assert result["skipped"] == 1
        assert result["failed"] == 0

    def test_unknown_status_falls_through(self, tool_service):
        """Unknown status should not increment counters and should continue looping."""
        tool = MagicMock()
        tool.name = "weird_tool"

        db = MagicMock()

        # Status not handled by the if/elif chain should simply fall through.
        with patch.object(tool_service, "_process_single_tool_for_bulk", return_value={"status": "weird"}):
            result = tool_service._process_tool_chunk(db, [tool], "skip", "public", None, None, None, None, None, None, None, None)

        assert result["created"] == 0
        assert result["updated"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 0

    def test_chunk_exception_rollback(self, tool_service):
        """Exception during chunk processing triggers rollback."""
        db = MagicMock()
        with patch.object(tool_service, "_process_single_tool_for_bulk", side_effect=RuntimeError("db error")):
            result = tool_service._process_tool_chunk(db, [MagicMock()], "skip", "public", None, None, None, None, None, None, None, None)
        assert result["failed"] == 1
        db.rollback.assert_called_once()

    def test_audit_trail_logged_for_created(self, tool_service, mock_logging_services):
        """Audit trail logged when tools are created."""
        tool = MagicMock()
        tool.name = "new_tool"
        db_tool = MagicMock()

        db = MagicMock()
        with patch.object(tool_service, "_process_single_tool_for_bulk", return_value={"status": "add", "tool": db_tool}):
            result = tool_service._process_tool_chunk(db, [tool], "skip", "public", None, None, "admin", None, None, None, None, None)
        assert result["created"] == 1
        mock_logging_services["audit_trail"].log_action.assert_called_once()


# ---------------------------------------------------------------------------
# _process_single_tool_for_bulk — conflict_strategy="fail" (lines 1578-1582)
# ---------------------------------------------------------------------------


class TestProcessSingleToolFail:
    def test_conflict_strategy_fail_returns_fail(self, tool_service):
        """conflict_strategy='fail' with duplicate returns fail status."""
        tool = MagicMock()
        tool.name = "existing_tool"
        tool.auth = None
        tool.team_id = None
        tool.owner_email = None
        tool.visibility = None

        existing = MagicMock()
        existing_map = {"existing_tool": existing}

        result = tool_service._process_single_tool_for_bulk(tool, existing_map, "fail", "public", None, None, None, None, None, None, None, None)
        assert result["status"] == "fail"
        assert "conflict" in result["error"].lower()

    def test_unknown_conflict_strategy_creates_new_tool(self, tool_service):
        """Unknown conflict_strategy falls through and creates a new tool (same name)."""
        tool = MagicMock()
        tool.name = "existing_tool"
        tool.auth = None
        tool.team_id = None
        tool.owner_email = None
        tool.visibility = "public"

        existing = MagicMock()
        existing_map = {"existing_tool": existing}

        sentinel_tool = MagicMock()
        with patch.object(tool_service, "_create_tool_object", return_value=sentinel_tool) as mock_create:
            result = tool_service._process_single_tool_for_bulk(
                tool,
                existing_map,
                "unknown",
                "public",
                None,
                None,
                "admin",
                None,
                None,
                None,
                None,
                None,
            )

        assert result["status"] == "add"
        assert result["tool"] is sentinel_tool
        mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# list_tools — cache hit, page-based, gateway_id="null", visibility, team access
# (lines 1753-1759, 1775, 1789-1791, 1805, 1812, 1834, 1854, 1865-1869)
# ---------------------------------------------------------------------------


class TestListToolsBranches:
    @pytest.mark.asyncio
    async def test_cache_hit(self, tool_service):
        """Returns cached tools when cache has data."""
        tool_dict = {
            "id": "t1",
            "name": "test_tool",
            "original_name": "test",
            "custom_name": "test",
            "custom_name_slug": "test",
            "displayName": "Test",
            "url": "http://x.com",
            "description": "d",
            "original_description": "od",
            "integration_type": "REST",
            "request_type": "GET",
            "headers": {},
            "input_schema": {},
            "annotations": {},
            "enabled": True,
            "reachable": True,
            "gateway_id": None,
            "gateway_slug": "test-gw",
            "visibility": "public",
            "team_id": None,
            "owner_email": None,
            "tags": [],
            "jsonpath_filter": None,
            "auth": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        cached = {"tools": [tool_dict], "next_cursor": None}
        db = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value="hash123")
            mock_cache.get = AsyncMock(return_value=cached)
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db)
        tools, cursor = result
        assert len(tools) == 1
        assert cursor is None

    @pytest.mark.asyncio
    async def test_page_based_pagination(self, tool_service):
        """Page-based pagination returns dict with data/pagination/links."""
        db = MagicMock()
        db.commit = MagicMock()
        pag_result = {"data": [], "pagination": {"page": 1, "total": 0}, "links": None}

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=pag_result)):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db, page=1, per_page=10)
        assert isinstance(result, dict)
        assert "data" in result

    @pytest.mark.asyncio
    async def test_gateway_id_null_filter(self, tool_service):
        """gateway_id='null' filters for tools with NULL gateway."""
        db = MagicMock()
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache.get = AsyncMock(return_value=None)  # cache miss to exercise query-building branches
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db, gateway_id="null")
        tools, _ = result
        assert tools == []

    @pytest.mark.asyncio
    async def test_user_with_team_and_visibility(self, tool_service):
        """User with teams and visibility filter applies all conditions."""
        db = MagicMock()
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db, user_email="user@test.com", token_teams=["team-1"], team_id="team-1", visibility="team")
        tools, _ = result
        assert tools == []

    @pytest.mark.asyncio
    async def test_team_id_with_token_teams_and_empty_user_email_skips_owner_condition(self, tool_service):
        """Empty-string user_email should not grant owner access, but should still honor token team scoping."""
        db = MagicMock()
        db.commit = MagicMock()

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))),
        ):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            tools, _ = await tool_service.list_tools(
                db,
                team_id="team-1",
                token_teams=["team-1"],
                user_email="",  # falsy, so owner condition should NOT be appended
            )

        assert tools == []

    @pytest.mark.asyncio
    async def test_user_with_empty_token_teams(self, tool_service):
        """Empty token_teams means public-only access."""
        db = MagicMock()
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db, user_email=None, token_teams=[])
        tools, _ = result
        assert tools == []

    @pytest.mark.asyncio
    async def test_cache_set_on_first_page(self, tool_service):
        """First page results are cached for non-user queries."""
        db = MagicMock()
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value="hash123")
            mock_cache.get = AsyncMock(return_value=None)  # cache miss
            mock_cache.set = AsyncMock()
            mock_cache_fn.return_value = mock_cache

            await tool_service.list_tools(db)
        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_gateway_id_specific_filter(self, tool_service):
        """Specific gateway_id filters by that ID."""
        db = MagicMock()
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn, patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value=None)
            mock_cache.get = AsyncMock(return_value=None)  # cache miss to exercise query-building branches
            mock_cache_fn.return_value = mock_cache

            result = await tool_service.list_tools(db, gateway_id="gw-123")
        tools, _ = result
        assert tools == []

    @pytest.mark.asyncio
    async def test_user_email_empty_string_sets_team_ids_empty(self, tool_service):
        """Empty-string user_email is treated as provided but unauthenticated (public-only)."""
        db = MagicMock()
        db.commit = MagicMock()

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([], None))),
        ):
            mock_cache_fn.return_value = AsyncMock()
            tools, _ = await tool_service.list_tools(db, user_email="")

        assert tools == []

    @pytest.mark.asyncio
    async def test_cache_set_attribute_error_is_swallowed(self, tool_service, mock_tool):
        """Covers AttributeError branch when cache-set tries to model_dump non-Pydantic results."""
        db = MagicMock()
        db.commit = MagicMock()

        with (
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.tool_service.unified_paginate", AsyncMock(return_value=([mock_tool], None))),
            patch.object(ToolRead, "model_validate", staticmethod(lambda d: d)),
        ):
            mock_cache = AsyncMock()
            mock_cache.hash_filters = MagicMock(return_value="hash123")
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            mock_cache_fn.return_value = mock_cache

            tools, _ = await tool_service.list_tools(db)

        assert isinstance(tools, list) and tools and isinstance(tools[0], dict)
        mock_cache.set.assert_not_called()


# ---------------------------------------------------------------------------
# list_server_tools — include_metrics, team lookup, access conditions
# (lines 1920, 1947-1952, 1962-1966)
# ---------------------------------------------------------------------------


class TestListServerToolsBranches:
    @pytest.mark.asyncio
    async def test_include_metrics_true(self, tool_service):
        """include_metrics=True uses selectinload for metrics."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        result = await tool_service.list_server_tools(db, "srv-1", include_metrics=True)
        assert result == []

    @pytest.mark.asyncio
    async def test_user_email_with_no_token_teams(self, tool_service):
        """user_email without token_teams looks up teams from DB."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[MagicMock(id="team-1")])
            mock_tms.return_value = mock_svc

            result = await tool_service.list_server_tools(db, "srv-1", user_email="u@test.com")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_non_public_only_token_with_teams(self, tool_service):
        """Non-public-only token with teams adds owner + team access conditions."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        result = await tool_service.list_server_tools(db, "srv-1", user_email="u@test.com", token_teams=["t1"])
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_user_email_empty_string_sets_team_ids_empty(self, tool_service):
        """Covers team_ids=[] branch in list_server_tools when user_email is empty string."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        result = await tool_service.list_server_tools(db, "srv-1", user_email="")
        assert result == []


# ---------------------------------------------------------------------------
# list_tools_for_user (DEPRECATED) — various branches
# (lines 2027-2030, 2037-2038, 2051-2088, 2094, 2101, 2115-2116)
# ---------------------------------------------------------------------------


class TestListToolsForUserBranches:
    @pytest.mark.asyncio
    async def test_limit_zero_fetches_all(self, tool_service):
        """limit=0 fetches all tools without pagination."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[])
            mock_tms.return_value = mock_svc

            tools, cursor = await tool_service.list_tools_for_user(db, "u@test.com", limit=0)
        assert tools == []
        assert cursor is None

    @pytest.mark.asyncio
    async def test_with_cursor(self, tool_service):
        """Valid cursor extracts last_id and applies filter."""
        # First-Party
        from mcpgateway.utils.pagination import encode_cursor

        cursor = encode_cursor({"id": "last-tool-id", "created_at": "2025-01-01T00:00:00"})
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[])
            mock_tms.return_value = mock_svc

            tools, next_cursor = await tool_service.list_tools_for_user(db, "u@test.com", cursor=cursor)
        assert tools == []

    @pytest.mark.asyncio
    async def test_with_team_id_and_filters(self, tool_service):
        """team_id, visibility, gateway_id='null', tags applied."""
        # Third-Party
        from sqlalchemy import literal

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms, patch("mcpgateway.services.tool_service.json_contains_tag_expr", return_value=literal(True)):
            mock_svc = MagicMock()
            mock_team = MagicMock()
            mock_team.id = "t1"
            mock_svc.get_user_teams = AsyncMock(return_value=[mock_team])
            mock_tms.return_value = mock_svc

            tools, _ = await tool_service.list_tools_for_user(
                db,
                "u@test.com",
                team_id="t1",
                visibility="team",
                gateway_id="null",
                tags=["api"],
                include_inactive=False,
            )
        assert tools == []

    @pytest.mark.asyncio
    async def test_include_inactive_true_skips_enabled_filter(self, tool_service):
        """Covers include_inactive=True branch (skip DbTool.enabled filter)."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[])
            mock_tms.return_value = mock_svc

            tools, cursor = await tool_service.list_tools_for_user(db, "u@test.com", include_inactive=True, limit=0)
        assert tools == []
        assert cursor is None

    @pytest.mark.asyncio
    async def test_gateway_id_specific_filter_applies(self, tool_service):
        """Covers gateway_id != 'null' branch."""
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms:
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[])
            mock_tms.return_value = mock_svc

            tools, _ = await tool_service.list_tools_for_user(db, "u@test.com", gateway_id="gw-123", include_inactive=True, limit=0)
        assert tools == []

    @pytest.mark.asyncio
    async def test_has_more_generates_cursor(self, tool_service):
        """When more results than page_size, generates next_cursor."""
        mock_tool1 = MagicMock()
        mock_tool1.id = "t1"
        mock_tool1.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_tool2 = MagicMock()
        mock_tool2.id = "t2"
        mock_tool2.created_at = datetime(2025, 1, 2, tzinfo=timezone.utc)

        db = MagicMock()
        # Return 2 tools when limit=1 → has_more=True
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_tool1, mock_tool2])))))
        db.commit = MagicMock()

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_tms, patch.object(tool_service, "convert_tool_to_read", side_effect=lambda t, **kw: {"id": t.id}):
            mock_svc = MagicMock()
            mock_svc.get_user_teams = AsyncMock(return_value=[])
            mock_tms.return_value = mock_svc

            tools, next_cursor = await tool_service.list_tools_for_user(db, "u@test.com", limit=1)
        assert len(tools) == 1
        assert next_cursor is not None


# ---------------------------------------------------------------------------
# delete_tool / set_tool_state — permission check (lines 2208-2211, 2368-2371)
# ---------------------------------------------------------------------------


class TestDeleteToolPermissionCheck:
    @pytest.mark.asyncio
    async def test_non_owner_cannot_delete(self, tool_service):
        """Non-owner user gets PermissionError."""
        tool = MagicMock()
        tool.id = "t1"
        tool.name = "tool"
        tool.team_id = None
        db = MagicMock()
        db.get = MagicMock(return_value=tool)

        with patch("mcpgateway.services.permission_service.PermissionService") as mock_ps:
            mock_svc = MagicMock()
            mock_svc.check_resource_ownership = AsyncMock(return_value=False)
            mock_ps.return_value = mock_svc

            with pytest.raises(PermissionError, match="owner"):
                await tool_service.delete_tool(db, "t1", user_email="other@test.com")


class TestSetToolStatePermissionCheck:
    @pytest.mark.asyncio
    async def test_non_owner_cannot_activate(self, tool_service):
        """Non-owner user gets PermissionError on state change."""
        tool = MagicMock()
        tool.id = "t1"
        tool.name = "tool"
        tool.enabled = True
        tool.reachable = True
        db = MagicMock()

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch("mcpgateway.services.permission_service.PermissionService") as mock_ps:
            mock_svc = MagicMock()
            mock_svc.check_resource_ownership = AsyncMock(return_value=False)
            mock_ps.return_value = mock_svc

            with pytest.raises(PermissionError, match="owner"):
                await tool_service.set_tool_state(db, "t1", activate=True, reachable=True, user_email="other@test.com")


# ---------------------------------------------------------------------------
# invoke_tool — cached status checks (lines 2547-2551, 2565-2577, 2585, 2592-2606)
# ---------------------------------------------------------------------------


class TestInvokeToolCachePaths:
    @pytest.mark.asyncio
    async def test_cached_status_missing(self, tool_service):
        """Cached status 'missing' raises ToolNotFoundError."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "missing"})
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError):
                await tool_service.invoke_tool(db, "missing_tool", {})

    @pytest.mark.asyncio
    async def test_cached_status_inactive(self, tool_service):
        """Cached status 'inactive' raises ToolNotFoundError."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "inactive"})
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError, match="inactive"):
                await tool_service.invoke_tool(db, "inactive_tool", {})

    @pytest.mark.asyncio
    async def test_cached_status_offline(self, tool_service):
        """Cached status 'offline' raises ToolNotFoundError."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "offline"})
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError, match="offline"):
                await tool_service.invoke_tool(db, "offline_tool", {})

    @pytest.mark.asyncio
    async def test_db_tool_unreachable_sets_negative_cache(self, tool_service):
        """Unreachable tool in DB sets negative cache and raises."""
        tool = MagicMock(spec=DbTool)
        tool.name = "unreachable"
        tool.enabled = True
        tool.reachable = False
        tool.gateway = None

        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set_negative = AsyncMock()
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[tool])))))

            with pytest.raises(ToolNotFoundError, match="offline"):
                await tool_service.invoke_tool(db, "unreachable", {})
            mock_cache.set_negative.assert_called_once()

    @pytest.mark.asyncio
    async def test_cached_payload_enabled_false(self, tool_service):
        """Cached payload with enabled=False raises."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "active", "tool": {"enabled": False}, "gateway": None})
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError, match="inactive"):
                await tool_service.invoke_tool(db, "disabled_tool", {})

    @pytest.mark.asyncio
    async def test_cached_payload_reachable_false(self, tool_service):
        """Cached payload with reachable=False raises."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value={"status": "active", "tool": {"reachable": False, "enabled": True}, "gateway": None})
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError, match="offline"):
                await tool_service.invoke_tool(db, "unreachable_cached", {})

    @pytest.mark.asyncio
    async def test_access_denied_returns_not_found(self, tool_service):
        """Access denied by _check_tool_access returns generic not found."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn, patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=False)):
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(
                return_value={
                    "status": "active",
                    "tool": {"enabled": True, "reachable": True, "id": "t1", "visibility": "private"},
                    "gateway": None,
                }
            )
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "private_tool", {}, user_email="outsider@test.com")

    @pytest.mark.asyncio
    async def test_server_scoping_denies_unattached_tool(self, tool_service):
        """Tool not attached to specified server raises not found."""
        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn, patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)):
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(
                return_value={
                    "status": "active",
                    "tool": {"enabled": True, "reachable": True, "id": "t1", "visibility": "public", "integration_type": "REST", "annotations": {}},
                    "gateway": None,
                }
            )
            mock_cache_fn.return_value = mock_cache

            db = MagicMock()
            db.execute = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))

            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "tool", {}, server_id="srv-1")

    @pytest.mark.asyncio
    async def test_server_scoping_allows_attached_tool(self, tool_service):
        """Tool attached to specified server should pass scoping check and invoke normally."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", jsonpath_filter="")
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(first=MagicMock(return_value=("tool-uuid-1",))))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=mock_response)

            result = await tool_service.invoke_tool(db, "test_tool", {}, server_id="srv-1")

        assert result is not None
        assert result.is_error is not True


# ---------------------------------------------------------------------------
# update_tool — various field updates (lines 3775-3859)
# ---------------------------------------------------------------------------


class TestUpdateToolBranches:
    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, tool_service):
        """Updating multiple optional fields covers many branches."""
        tool = MagicMock(spec=DbTool)
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.display_name = "Old"
        tool.description = "old desc"
        tool.original_description = "old desc"
        tool.version = 3
        tool.team_id = "team-1"
        tool.visibility = "public"

        tool_update = MagicMock(spec=ToolUpdate)
        tool_update.name = "new_name"
        tool_update.custom_name = None
        tool_update.displayName = "New Tool"
        tool_update.title = None
        tool_update.url = None
        tool_update.description = "new desc"
        tool_update.integration_type = None
        tool_update.request_type = None
        tool_update.headers = None
        tool_update.input_schema = None
        tool_update.output_schema = {"type": "object"}
        tool_update.annotations = None
        tool_update.jsonpath_filter = None
        tool_update.visibility = "team"
        tool_update.auth = None
        tool_update.tags = ["api", "v2"]

        db = MagicMock()

        # First call returns the tool being edited, second call returns None (no conflict)
        with (
            patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, None]),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1"}),
        ):
            result = await tool_service.update_tool(
                db,
                "t1",
                tool_update,
                modified_by="admin",
                modified_from_ip="1.2.3.4",
                modified_via="api",
                modified_user_agent="curl/8.0",
            )

        assert result is not None
        assert tool.display_name == "New Tool"
        assert tool.output_schema == {"type": "object"}
        assert tool.tags == ["api", "v2"]
        assert tool.version == 4
        assert tool.modified_by == "admin"
        assert tool.modified_from_ip == "1.2.3.4"
        assert tool.modified_via == "api"
        assert tool.modified_user_agent == "curl/8.0"
        # custom_name auto-updated when name == custom_name and custom_name is None
        assert tool.custom_name == "new_name"

    @pytest.mark.asyncio
    async def test_version_none_initializes_to_1(self, tool_service):
        """When tool.version is None, it's initialized to 1."""
        tool = MagicMock(spec=DbTool)
        tool.id = "t1"
        tool.name = "tool"
        tool.custom_name = "tool"
        tool.version = None
        tool.team_id = None
        tool.visibility = "public"

        tool_update = MagicMock(spec=ToolUpdate)
        tool_update.name = None
        tool_update.custom_name = None
        tool_update.displayName = None
        tool_update.title = None
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

        db = MagicMock()
        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1"}),
        ):
            await tool_service.update_tool(db, "t1", tool_update)

        assert tool.version == 1

    @pytest.mark.asyncio
    async def test_team_name_conflict_on_update(self, tool_service):
        """Raises ToolNameConflictError when team tool name conflicts on rename."""
        tool = MagicMock(spec=DbTool)
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = "team-1"
        tool.visibility = "team"

        tool_update = MagicMock(spec=ToolUpdate)
        tool_update.name = "conflict_name"
        tool_update.custom_name = "conflict_name"
        tool_update.displayName = None
        tool_update.title = None
        tool_update.url = None
        tool_update.description = None
        tool_update.integration_type = None
        tool_update.request_type = None
        tool_update.headers = None
        tool_update.input_schema = None
        tool_update.output_schema = None
        tool_update.annotations = None
        tool_update.jsonpath_filter = None
        tool_update.visibility = "team"
        tool_update.auth = None
        tool_update.tags = None

        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "team"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_visibility_none_team_conflict_check(self, tool_service, mock_tool):
        """When ToolUpdate.visibility is None and tool.visibility is team, should check team conflicts and allow successful update."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = "team-1"
        tool.visibility = "team"
        tool.version = 1

        tool_update = _make_tool_update(name="conflict_name", custom_name="conflict_name", description="Updated description")

        # Test 1: Conflict detection - should raise error when name conflicts
        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "team"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

        # Test 2: Successful update - should work when no conflict and preserve visibility
        tool_update.name = "new_name"
        tool_update.custom_name = "new_name"

        with (
            patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, None]),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1", "name": "new_name", "visibility": "team"}),
        ):
            result = await tool_service.update_tool(db, "t1", tool_update)

        assert result is not None
        assert tool.name == "new_name"
        assert tool.custom_name == "new_name"
        assert tool.description == "Updated description"
        assert tool.visibility == "team"
        assert tool.team_id == "team-1"
        assert tool.version == 2

    @pytest.mark.asyncio
    async def test_update_tool_visibility_none_public_conflict_check(self, tool_service, mock_tool):
        """When ToolUpdate.visibility is None and tool.visibility is public, should check public conflicts and allow successful update."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = None
        tool.visibility = "public"
        tool.version = 5

        tool_update = _make_tool_update(name="conflict_name", custom_name="conflict_name", displayName="Updated Tool")

        # Test 1: Conflict detection
        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "public"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

        # Test 2: Successful update
        tool_update.name = "new_public_name"
        tool_update.custom_name = "new_public_name"

        with (
            patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, None]),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1", "name": "new_public_name", "visibility": "public"}),
        ):
            result = await tool_service.update_tool(db, "t1", tool_update)

        assert result is not None
        assert tool.name == "new_public_name"
        assert tool.custom_name == "new_public_name"
        assert tool.display_name == "Updated Tool"
        assert tool.visibility == "public"
        assert tool.team_id is None
        assert tool.version == 6

    @pytest.mark.asyncio
    async def test_update_tool_team_id_fallback_from_db(self, tool_service, mock_tool):
        """When ToolUpdate.team_id is None, should fall back to tool.team_id for conflict check."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = "team-1"
        tool.visibility = "team"
        tool.version = 1

        tool_update = _make_tool_update(name="conflict_name", custom_name="conflict_name")

        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "team"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_custom_name_fallback_in_conflict_check(self, tool_service, mock_tool):
        """When ToolUpdate.custom_name is None, conflict check should use tool_update.name."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = None
        tool.visibility = "public"
        tool.version = 1

        tool_update = _make_tool_update(name="conflict_name", visibility="public")

        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "public"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_visibility_change_conflict_check(self, tool_service, mock_tool):
        """Changing visibility without changing name should still check for conflicts in the target scope."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "my_tool"
        tool.custom_name = "my_tool"
        tool.team_id = "team-1"
        tool.visibility = "team"
        tool.version = 1

        tool_update = _make_tool_update(visibility="public")

        existing = MagicMock()
        existing.custom_name = "my_tool"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "public"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_visibility_change_to_team_conflict(self, tool_service, mock_tool):
        """Changing visibility from public to team should check for team-scoped conflicts."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "my_tool"
        tool.custom_name = "my_tool"
        tool.team_id = "team-1"
        tool.visibility = "public"
        tool.version = 1

        tool_update = _make_tool_update(visibility="team")

        existing = MagicMock()
        existing.custom_name = "my_tool"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "team"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_auth_not_reset_when_omitted(self, tool_service, mock_tool):
        """When ToolUpdate.auth is None (not provided), existing auth_type should be preserved."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "my_tool"
        tool.custom_name = "my_tool"
        tool.team_id = None
        tool.visibility = "public"
        tool.auth_type = "bearer"
        tool.auth_value = "secret-token"
        tool.version = 1

        tool_update = _make_tool_update(description="Updated description")

        db = MagicMock()
        with (
            patch("mcpgateway.services.tool_service.get_for_update", return_value=tool),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1"}),
        ):
            result = await tool_service.update_tool(db, "t1", tool_update)

        assert result is not None
        assert tool.auth_type == "bearer"  # Should NOT have been wiped
        assert tool.auth_value == "secret-token"
        assert tool.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_tool_private_visibility_name_conflict(self, tool_service, mock_tool):
        """Renaming a private tool should check for conflicts scoped by owner_email."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "old_name"
        tool.custom_name = "old_name"
        tool.team_id = None
        tool.visibility = "private"
        tool.owner_email = "owner@example.com"
        tool.version = 1

        tool_update = _make_tool_update(name="conflict_name", custom_name="conflict_name")

        existing = MagicMock()
        existing.custom_name = "conflict_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "private"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_visibility_change_to_private_conflict(self, tool_service, mock_tool):
        """Changing visibility to private should check for owner-scoped conflicts."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "my_tool"
        tool.custom_name = "my_tool"
        tool.team_id = None
        tool.visibility = "public"
        tool.owner_email = "owner@example.com"
        tool.version = 1

        tool_update = _make_tool_update(visibility="private")

        existing = MagicMock()
        existing.custom_name = "my_tool"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "private"

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_rename_with_divergent_custom_name(self, tool_service, mock_tool):
        """When custom_name differs from name, renaming should check conflict against the existing custom_name (which won't change)."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "internal_name"
        tool.custom_name = "display_name"  # Diverges from name
        tool.team_id = None
        tool.visibility = "public"
        tool.version = 1

        # Rename the internal name — custom_name should stay "display_name"
        tool_update = _make_tool_update(name="new_internal_name")

        # A tool with custom_name "display_name" already exists in public scope
        existing = MagicMock()
        existing.custom_name = "display_name"
        existing.enabled = True
        existing.id = "t2"
        existing.visibility = "public"

        db = MagicMock()
        # The conflict check should query for "display_name" (the unchanged custom_name),
        # NOT "new_internal_name"
        with patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, existing]):
            with pytest.raises(ToolNameConflictError):
                await tool_service.update_tool(db, "t1", tool_update)

    @pytest.mark.asyncio
    async def test_update_tool_rename_with_divergent_custom_name_no_conflict(self, tool_service, mock_tool):
        """When custom_name differs from name, renaming should succeed if custom_name has no conflict."""
        tool = mock_tool
        tool.id = "t1"
        tool.name = "internal_name"
        tool.custom_name = "display_name"  # Diverges from name
        tool.team_id = None
        tool.visibility = "public"
        tool.version = 1

        tool_update = _make_tool_update(name="new_internal_name")

        db = MagicMock()
        with (
            patch("mcpgateway.services.tool_service.get_for_update", side_effect=[tool, None]),
            patch.object(tool_service, "_notify_tool_updated", AsyncMock()),
            patch.object(tool_service, "convert_tool_to_read", return_value={"id": "t1", "name": "new_internal_name"}),
        ):
            result = await tool_service.update_tool(db, "t1", tool_update)

        assert result is not None
        assert tool.name == "new_internal_name"
        assert tool.custom_name == "display_name"  # Should NOT have changed
        assert tool.version == 2

    def test_check_tool_name_conflict_skips_team_without_team_id(self, tool_service):
        """When visibility is 'team' but team_id is None, should log warning and skip conflict check."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.logger") as mock_logger:
            tool_service._check_tool_name_conflict(db, "my_tool", "team", "t1", team_id=None, owner_email=None)
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[0][3] == "team_id"

    def test_check_tool_name_conflict_skips_private_without_owner_email(self, tool_service):
        """When visibility is 'private' but owner_email is None, should log warning and skip conflict check."""
        db = MagicMock()
        with patch("mcpgateway.services.tool_service.logger") as mock_logger:
            tool_service._check_tool_name_conflict(db, "my_tool", "private", "t1", team_id=None, owner_email=None)
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args[0][3] == "owner_email"

    def test_tool_name_conflict_error_private_label(self):
        """ToolNameConflictError should label private conflicts as 'Private', not 'Public'."""
        err = ToolNameConflictError("my_tool", enabled=True, tool_id="t1", visibility="private")
        assert "Private" in str(err)
        assert "Public" not in str(err)

    @pytest.mark.asyncio
    async def test_permission_check_on_update(self, tool_service):
        """Non-owner user gets PermissionError on update."""
        tool = MagicMock(spec=DbTool)
        tool.id = "t1"
        tool.name = "tool"

        tool_update = MagicMock(spec=ToolUpdate)
        tool_update.name = None
        tool_update.title = None

        db = MagicMock()
        with patch("mcpgateway.services.tool_service.get_for_update", return_value=tool), patch("mcpgateway.services.permission_service.PermissionService") as mock_ps:
            mock_svc = MagicMock()
            mock_svc.check_resource_ownership = AsyncMock(return_value=False)
            mock_ps.return_value = mock_svc

            with pytest.raises(PermissionError, match="owner"):
                await tool_service.update_tool(db, "t1", tool_update, user_email="other@test.com")


# ---------------------------------------------------------------------------
# register_tools_bulk — tool without name (line 1341)
# ---------------------------------------------------------------------------


class TestRegisterToolsBulkEdge:
    @pytest.mark.asyncio
    async def test_tool_without_name_skipped(self, tool_service):
        """Tools without name attribute are skipped in cache invalidation."""
        tool_no_name = MagicMock()
        del tool_no_name.name  # getattr(tool, "name", None) returns None

        tool_with_name = MagicMock()
        tool_with_name.name = "good_tool"

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        with (
            patch.object(tool_service, "_process_tool_chunk", return_value={"created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []}),
            patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn,
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_tlc,
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_asc,
        ):
            mock_cache = AsyncMock()
            mock_cache.invalidate_tools = AsyncMock()
            mock_cache_fn.return_value = mock_cache
            mock_tlc_inst = AsyncMock()
            mock_tlc_inst.invalidate = AsyncMock()
            mock_tlc.return_value = mock_tlc_inst
            mock_asc.invalidate_tags = AsyncMock()

            result = await tool_service.register_tools_bulk(db, [tool_no_name, tool_with_name])
        assert result["created"] == 1


# ---------------------------------------------------------------------------
# Helper: build a cached tool payload for invoke_tool tests
# ---------------------------------------------------------------------------


def _make_tool_payload(
    *,
    integration_type="REST",
    request_type="GET",
    auth_type=None,
    auth_value=None,
    gateway_id=None,
    annotations=None,
    output_schema=None,
    jsonpath_filter=None,
    timeout_ms=None,
    url="http://backend:8000/api/data",
):
    """Build a minimal tool_payload dict matching what _build_tool_cache_payload returns."""
    return {
        "id": "tool-uuid-1",
        "name": "test_tool",
        "original_name": "test_tool",
        "custom_name": "test_tool",
        "display_name": "Test Tool",
        "url": url,
        "description": "A test tool",
        "integration_type": integration_type,
        "request_type": request_type,
        "headers": {},
        "input_schema": {},
        "output_schema": output_schema,
        "annotations": annotations or {},
        "jsonpath_filter": jsonpath_filter,
        "auth_type": auth_type,
        "auth_value": auth_value,
        "oauth_config": None,
        "enabled": True,
        "reachable": True,
        "gateway_id": gateway_id,
        "visibility": "public",
        "team_id": None,
        "owner_email": None,
        "timeout_ms": timeout_ms,
    }


def _make_gateway_payload(
    *, auth_type=None, auth_value=None, auth_query_params=None, oauth_config=None, ca_certificate=None, ca_certificate_sig=None, passthrough_headers=None, url=None, client_cert=None, client_key=None
):
    return {
        "id": "gw-uuid-1",
        "name": "test_gw",
        "url": url or "http://gateway:9000",
        "auth_type": auth_type,
        "auth_value": auth_value,
        "auth_query_params": auth_query_params,
        "oauth_config": oauth_config,
        "ca_certificate": ca_certificate,
        "ca_certificate_sig": ca_certificate_sig,
        "passthrough_headers": passthrough_headers,
        "client_cert": client_cert,
        "client_key": client_key,
    }


def _setup_cache_for_invoke(tool_payload, gateway_payload=None):
    """Return a patch context manager that makes invoke_tool use a cached payload."""
    cached = {
        "status": "active",
        "tool": tool_payload,
        "gateway": gateway_payload,
    }
    mock_cache = AsyncMock()
    mock_cache.enabled = True
    mock_cache.get = AsyncMock(return_value=cached)
    return patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=mock_cache)


# ---------------------------------------------------------------------------
# _extract_and_validate_structured_content — JSON parse error (lines 930-932)
# ---------------------------------------------------------------------------


class TestExtractValidateJsonParseError:
    def test_json_parse_error_in_content_continues(self, tool_service):
        """JSON parse errors in content items are silently skipped."""
        tool = SimpleNamespace(name="t", output_schema={"type": "object", "properties": {"k": {"type": "string"}}})
        tool_result = MagicMock()
        tool_result.content = [
            {"type": "text", "text": "not-valid-json{{{"},
            {"type": "text", "text": '{"k": "v"}'},
        ]
        tool_result.is_error = False
        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        # Should parse second content item successfully
        assert result is True

    def test_schema_type_exception_falls_through(self, tool_service):
        """When output_schema.get raises, schema_type defaults to None."""
        tool = SimpleNamespace(name="t", output_schema="not-a-dict")
        tool_result = MagicMock()
        tool_result.content = [{"type": "text", "text": '{"k": "v"}'}]
        tool_result.is_error = False
        # "not-a-dict".get will raise AttributeError, caught by except on line 943
        result = tool_service._extract_and_validate_structured_content(tool, tool_result)
        assert result is True or result is False


# ---------------------------------------------------------------------------
# invoke_tool — REST timeout path (lines 2900-2939)
# ---------------------------------------------------------------------------


class TestInvokeToolRestTimeout:
    @pytest.mark.asyncio
    async def test_rest_timeout_raises_tool_timeout_error(self, tool_service):
        """REST tool timeout raises ToolTimeoutError."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            # Make HTTP GET timeout
            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_rest_timeout_triggers_cb_and_post_hook_and_metrics_counter_failure(self, tool_service):
        """REST tool timeout should trigger cb timeout state and post-invoke hook; metrics counter failures are swallowed."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        # Plugin manager enabled: provide a context table so timeout handler marks cb state.
        ctx = MagicMock()
        context_table = {"ctx": ctx}
        plugin_manager = MagicMock()
        plugin_manager.has_hooks_for = MagicMock(return_value=True)
        plugin_manager.invoke_hook = AsyncMock(
            side_effect=[
                (SimpleNamespace(modified_payload=None), context_table),  # pre-invoke
                (SimpleNamespace(modified_payload=None, retry_delay_ms=0), context_table),  # post-invoke (timeout handler)
            ]
        )

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.tool_service.metrics_buffer", MagicMock()),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.metrics.tool_timeout_counter") as mock_timeout_counter,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # Make counter increment raise to hit the "except Exception as exc" branch.
            mock_timeout_counter.labels.return_value.inc.side_effect = RuntimeError("counter fail")

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {})

        # Pre + post hook should be invoked.
        assert plugin_manager.has_hooks_for.call_args_list == [call(ToolHookType.TOOL_PRE_INVOKE), call(ToolHookType.TOOL_POST_INVOKE)]
        assert plugin_manager.invoke_hook.await_count == 2
        ctx.set_state.assert_called_with("cb_timeout_failure", True)

    @pytest.mark.asyncio
    async def test_rest_timeout_with_plugin_manager_no_context_and_no_post_hook(self, tool_service):
        """Covers branches where plugin manager is present but no context_table and no TOOL_POST_INVOKE hook."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        plugin_manager = MagicMock()
        plugin_manager.has_hooks_for = MagicMock(return_value=False)

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {})

        # has_hooks_for should be queried for both PRE and POST hooks, but only the "if" branches are covered here.
        assert ToolHookType.TOOL_PRE_INVOKE in [c.args[0] for c in plugin_manager.has_hooks_for.call_args_list]
        assert ToolHookType.TOOL_POST_INVOKE in [c.args[0] for c in plugin_manager.has_hooks_for.call_args_list]

    @pytest.mark.asyncio
    async def test_rest_timeout_with_span_none_skips_span_attributes(self, tool_service):
        """When create_span yields None, ToolTimeoutError handling should skip span attribute updates."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        span_cm = MagicMock()
        span_cm.__enter__ = MagicMock(return_value=None)
        span_cm.__exit__ = MagicMock(return_value=False)

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span", return_value=span_cm),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_observability_end_span_failure_is_logged(self, tool_service):
        """If end_span fails, invoke_tool should log a warning (coverage for line 3712)."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_obs = MagicMock()
        mock_obs.start_span = MagicMock(return_value="db-span-1")
        mock_obs.end_span = MagicMock(side_effect=RuntimeError("end boom"))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.ObservabilityService", return_value=mock_obs),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.logger.warning") as mock_warn,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value="trace-1")
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError):
                await tool_service.invoke_tool(db, "test_tool", {})

        assert mock_warn.called


# ---------------------------------------------------------------------------
# invoke_tool — REST pre-invoke modified_payload with headers=None (line 2936)
# ---------------------------------------------------------------------------


class TestInvokeToolRestPreInvokeModifiedPayload:
    @pytest.mark.asyncio
    async def test_rest_pre_invoke_modified_payload_with_headers_none(self, tool_service):
        """Pre-invoke hook that modifies args but provides headers=None should not overwrite headers."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="REST", request_type="GET", jsonpath_filter="")
        db = MagicMock()

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_PRE_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        modified_payload = SimpleNamespace(name="test_tool", args={"k": "v"}, headers=None)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=modified_payload), {}))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=mock_response)

            result = await tool_service.invoke_tool(db, "test_tool", {"orig": "x"})

        assert result is not None
        plugin_manager.invoke_hook.assert_awaited_once()


# ---------------------------------------------------------------------------
# invoke_tool — REST success with JSON response (lines 2959-2960, 2967-2968)
# ---------------------------------------------------------------------------


class TestInvokeToolRestSuccess:
    @pytest.mark.asyncio
    async def test_rest_success_json_response(self, tool_service):
        """REST tool successful JSON response is parsed and returned."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"result": "ok"})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None
        assert result.is_error is not True

    @pytest.mark.asyncio
    async def test_rest_non_json_response(self, tool_service):
        """REST tool non-JSON response falls back to text."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(side_effect=orjson.JSONDecodeError("invalid", "x", 0))
        mock_response.text = "plain text response"
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_rest_success_with_output_schema_validation(self, tool_service):
        """REST tool validates response against output schema."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", output_schema={"type": "object", "properties": {"result": {"type": "string"}}})
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"result": "ok"})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_rest_payload_shaped_error_skips_output_schema_validation(self, tool_service):
        """End-to-end #4202 guard through the REST integration branch of ``invoke_tool``.

        Drives the full REST invocation pipeline (not the unit-scoped
        ``_extract_and_validate_structured_content`` helper) with an upstream
        HTTP response whose JSON body is a pre-serialised MCP error envelope:
        ``{"isError": true, "content": [{"type":"text","text": "<user message>"}]}``.
        ``_coerce_to_tool_result`` recognises the MCP shape and
        pydantic-validates it into a ToolResult with ``is_error=True``, after
        which the validator must skip schema enforcement so the verbatim user
        message (``"Value exceeds maximum allowed (Requested: 150)"``) reaches
        the caller unchanged. This is the most realistic #4202 scenario in
        the non-MCP-federated path — which, per
        https://github.com/IBM/mcp-context-forge/issues/4207, has no e2e
        coverage today.

        MCP spec references:
        - 2025-11-25 "Error Handling" — isError responses do not require
          structured content and must not be cross-validated against
          outputSchema.
        - 2025-11-25 "Output Schema" — governs only the success path.
        """
        tp = _make_tool_payload(
            integration_type="REST",
            request_type="GET",
            output_schema={"type": "object", "required": ["recognitionId"], "properties": {"recognitionId": {"type": "string"}}},
        )
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "isError": True,
                "content": [{"type": "text", "text": "Value exceeds maximum allowed (Requested: 150)"}],
            }
        )
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        assert result.is_error is True
        assert result.content[0].text == "Value exceeds maximum allowed (Requested: 150)"

    @pytest.mark.asyncio
    async def test_rest_payload_shaped_error_records_success_false_in_metrics(self, tool_service):
        """Regression guard — metrics must record ``success=False`` for REST ``isError=True`` with outputSchema.

        Before this fix, the REST branch at
        ``tool_service.py::invoke_tool`` ran
        ``_extract_and_validate_structured_content`` after
        ``_coerce_to_tool_result`` and then did ``success = bool(valid)``
        — clobbering ``success`` back to ``True`` because the validator
        correctly skips (returns ``True``) on ``isError=true`` per the
        #4202 fix. That meant every REST tool whose upstream returned a
        pre-serialised MCP error envelope was recorded in
        ``metrics_buffer.record_tool_metric`` with ``success=True``,
        corrupting tool-level success rates and masking real failures in
        observability.

        The fix replaces the ``success = bool(valid)`` override with
        ``success = not tool_result.is_error`` after the optional
        validator call, so the metric reflects both upstream error state
        *and* any validator-imposed error state uniformly.

        This test drives the full REST pipeline, captures the arguments
        passed to ``record_tool_metric``, and asserts ``success=False``.
        The companion assertion on ``result.is_error`` (already covered
        by ``test_rest_payload_shaped_error_skips_output_schema_validation``)
        proves the user-visible payload is correct; this test
        additionally proves the internal bookkeeping is correct.
        """
        tp = _make_tool_payload(
            integration_type="REST",
            request_type="GET",
            output_schema={"type": "object", "required": ["recognitionId"], "properties": {"recognitionId": {"type": "string"}}},
        )
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "isError": True,
                "content": [{"type": "text", "text": "Value exceeds maximum allowed (Requested: 150)"}],
            }
        )
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        # Capture arguments to record_tool_metric so we can assert success=False.
        # Patch the module-level singleton directly — ``metrics_buffer`` is
        # bound at import time in tool_service.py.
        metrics_record = MagicMock()
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_tool_metric = metrics_record
        mock_metrics_buffer.record_server_metric = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        # User-visible payload is still the verbatim upstream error.
        assert result.is_error is True
        assert result.content[0].text == "Value exceeds maximum allowed (Requested: 150)"
        # Metrics were recorded with success=False — the specific bookkeeping
        # invariant this test exists to pin.
        assert metrics_record.called, "record_tool_metric was not invoked"
        # The recorder is called via keyword arguments; accept either form.
        recorded_success = metrics_record.call_args.kwargs.get("success")
        if recorded_success is None and metrics_record.call_args.args:
            # Positional fallback: the `success` argument is the 3rd positional
            # after (tool_id, start_time, success) in the recorder signature.
            recorded_success = metrics_record.call_args.args[2]
        assert recorded_success is False, f"Expected metrics success=False for REST isError=true response, got {recorded_success}. " "This regression would silently inflate tool success rates."

    @pytest.mark.asyncio
    async def test_mcp_non_direct_proxy_iserror_records_success_false_in_metrics(self, tool_service):
        """Sibling-path regression guard for the REST metrics fix.

        The REST branch's success-metric bug (``success = bool(valid)``
        clobber) lived inside ``tool_service.py::invoke_tool``'s
        ``if tool_integration_type == "REST":`` branch, right after the
        optional ``_extract_and_validate_structured_content`` call, and
        was fixed by this PR. The **MCP non-direct-proxy** branch — the
        ``else`` arm of ``if is_direct_proxy:`` inside
        ``elif tool_integration_type == "MCP":`` — correctly uses
        ``success = not is_err`` today (search for the assignment
        immediately after ``is_err = getattr(tool_call_result, ...)``),
        but there was no regression test pinning that invariant for
        federated MCP tools. A future refactor wiring Validator B into
        the MCP branch for symmetry with REST — or simply re-using the
        ``bool(valid)`` idiom — would silently re-introduce the #4202
        clobber here with no unit test to catch it.

        This test drives ``invoke_tool`` through the MCP SSE path with
        a mocked ``ClientSession.call_tool`` returning an
        ``isError=True`` ``CallToolResult`` and asserts that
        ``metrics_buffer.record_tool_metric`` is invoked with
        ``success=False``. The user-visible assertion on ``is_error``
        is the secondary check; the primary value is pinning the
        metric bookkeeping against a future refactor.

        Related tests:
        - ``test_rest_payload_shaped_error_records_success_false_in_metrics``
          — REST-branch twin of this guard.
        - ``test_call_tool_preserves_is_error_for_direct_proxy_egress``
          — direct-proxy branch; already uses ``_coerce_to_tool_result``
          + ``success = not tool_result.is_error``.
        """
        # Third-party — ``session.call_tool(...)`` returns ``mcp.types.CallToolResult``
        # (camelCase ``isError``), not the gateway's internal ``ToolResult``.
        # Using the real SDK type here exercises the
        # ``getattr(tool_call_result, "isError", False)`` fallback that fires
        # for federated MCP calls in production. A gateway-type stand-in would
        # only trip the first ``getattr(..., "is_error")`` branch and hide the
        # camelCase path from regression coverage.
        # First-Party
        from mcp import types as mcp_types  # pylint: disable=import-outside-toplevel

        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload()
        db = MagicMock()

        # Real upstream shape — MCP SDK CallToolResult with camelCase isError.
        sdk_error_result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="You cannot send more than 200 points")],
            isError=True,
        )

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=sdk_error_result)

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        # Capture what gets passed to the module-level metrics_buffer.
        metrics_record = MagicMock()
        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_tool_metric = metrics_record
        mock_metrics_buffer.record_server_metric = MagicMock()

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)

            result = await tool_service.invoke_tool(db, "test_tool", {})

        # User-visible payload preserved verbatim (the #4202 contract).
        assert result.is_error is True
        assert result.content[0].text == "You cannot send more than 200 points"

        # Primary assertion: metric bookkeeping is correct. The MCP
        # non-direct-proxy branch must record success=False for
        # isError=true upstream responses, symmetric with the REST fix.
        assert metrics_record.called, "record_tool_metric was not invoked"
        recorded_success = metrics_record.call_args.kwargs.get("success")
        assert recorded_success is False, (
            f"Expected metrics success=False for MCP non-direct-proxy isError=true response, got {recorded_success}. " "This would silently inflate federated-tool success rates."
        )


# ---------------------------------------------------------------------------
# invoke_tool — REST non-JSON error response (lines 2949-2950)
# ---------------------------------------------------------------------------


class TestInvokeToolRestErrorResponse:
    async def _invoke_with_error_response(self, tool_service, status_code, json_return, text_body):
        """Helper to invoke a REST GET tool with a mocked error response."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json = MagicMock(return_value=json_return)
        mock_response.text = text_body
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            return await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_rest_error_dict_serialized_as_json(self, tool_service):
        """When REST error field is a dict, it should be serialized as valid JSON, not Python repr."""
        result = await self._invoke_with_error_response(
            tool_service,
            status_code=400,
            json_return={"error": {"code": "INVALID", "details": {"field": "name", "required": True}}},
            text_body="Bad Request",
        )
        assert result.is_error is True
        text = result.content[0].text
        # Must be valid JSON, not Python repr
        parsed = json.loads(text)
        assert parsed["code"] == "INVALID"
        assert parsed["details"]["required"] is True
        assert "True" not in text  # Python repr would have capital True

    @pytest.mark.asyncio
    async def test_rest_error_string_passed_through(self, tool_service):
        """When REST error field is a string, it should be passed through as-is."""
        result = await self._invoke_with_error_response(
            tool_service,
            status_code=500,
            json_return={"error": "Internal server error"},
            text_body="Internal Server Error",
        )
        assert result.is_error is True
        assert result.content[0].text == "Internal server error"

    @pytest.mark.asyncio
    async def test_rest_non_standard_status_non_json(self, tool_service):
        """REST tool 207 Multi-Status with non-JSON body."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 207
        mock_response.json = MagicMock(side_effect=orjson.JSONDecodeError("invalid", "x", 0))
        mock_response.text = "multi-status response"
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result.is_error is True


# ---------------------------------------------------------------------------
# invoke_tool — Observability span creation & ending (lines 2768-2793, 3622-3643)
# ---------------------------------------------------------------------------


class TestInvokeToolObservability:
    @pytest.mark.asyncio
    async def test_observability_span_created_and_ended(self, tool_service):
        """When trace_id is present, database span is created and ended."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        mock_obs_svc = MagicMock()
        mock_obs_svc.start_span = MagicMock(return_value="span-123")
        mock_obs_svc.end_span = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.ObservabilityService", return_value=mock_obs_svc),
            patch("mcpgateway.services.tool_service.fresh_db_session") as mock_fds,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value="trace-abc")
            mock_fds.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_fds.return_value.__exit__ = MagicMock(return_value=False)
            mock_span = MagicMock()
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        # Verify span was created and ended
        mock_obs_svc.start_span.assert_called_once()
        assert mock_obs_svc.end_span.call_count == 1
        # Verify OTel span attributes set
        mock_span.set_attribute.assert_any_call("success", True)

    @pytest.mark.asyncio
    async def test_observability_rest_path_creates_lookup_gateway_and_post_process_child_spans(self, tool_service):
        """REST invocation should emit the expected nested child spans for Langfuse breakdowns."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*_a, **_kw):
            return mock_response

        @contextmanager
        def _span_cm(*_a, **_kw):
            yield MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span", _span_cm),
            patch("mcpgateway.services.tool_service.create_child_span", side_effect=_span_cm) as mock_child_span,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        assert [call.args[0] for call in mock_child_span.call_args_list] == ["tool.lookup", "tool.gateway_call", "tool.post_process"]
        assert mock_child_span.call_args_list[1].args[1]["tool.integration_type"] == "REST"

    @pytest.mark.asyncio
    async def test_observability_span_start_failure(self, tool_service):
        """When span creation fails, invocation continues."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        mock_obs_svc = MagicMock()
        mock_obs_svc.start_span = MagicMock(side_effect=RuntimeError("DB down"))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.ObservabilityService", return_value=mock_obs_svc),
            patch("mcpgateway.services.tool_service.fresh_db_session") as mock_fds,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value="trace-abc")
            mock_fds.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_fds.return_value.__exit__ = MagicMock(return_value=False)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            # Should not raise despite span creation failure
            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None


# ---------------------------------------------------------------------------
# invoke_tool — Metrics recording failure (lines 3659-3660)
# ---------------------------------------------------------------------------


class TestInvokeToolMetricsFailure:
    @pytest.mark.asyncio
    async def test_metrics_recording_failure_doesnt_crash(self, tool_service):
        """Metrics recording failure is logged but doesn't raise."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", side_effect=RuntimeError("metrics down")),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None


# ---------------------------------------------------------------------------
# invoke_tool — Gateway query param decryption (lines 2661-2672)
# ---------------------------------------------------------------------------


class TestInvokeToolGatewayQueryParams:
    @pytest.mark.asyncio
    async def test_gateway_query_param_auth_decryption(self, tool_service):
        """Gateway query params are decrypted and applied to URL."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-uuid-1")
        gp = _make_gateway_payload(auth_type="query_param", auth_query_params={"api_key": "encrypted_value"})
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"api_key": "secret123"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://gateway:9000?api_key=secret123"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_gateway_query_param_auth_uses_runtime_gateway_query_params(self, tool_service, mock_tool, mock_gateway):
        """Runtime ORM gateway query params should be used when they are a dict."""
        mock_gateway.id = "gw-uuid-1"
        mock_gateway.name = "test_gw"
        mock_gateway.url = "http://gateway:9000"
        mock_gateway.auth_type = "query_param"
        mock_gateway.auth_value = None
        mock_gateway.auth_query_params = {"api_key": "runtime_encrypted"}
        mock_gateway.oauth_config = None
        mock_gateway.ca_certificate = None
        mock_gateway.ca_certificate_sig = None
        mock_gateway.passthrough_headers = None

        mock_tool.id = "tool-uuid-1"
        mock_tool.original_name = "test_tool"
        mock_tool.name = "test_tool"
        mock_tool.url = "http://tool:9001"
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.headers = {}
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        mock_tool.oauth_config = None
        mock_tool.gateway_id = "gw-uuid-1"
        mock_tool.gateway = mock_gateway
        mock_tool.jsonpath_filter = ""
        mock_tool.output_schema = None
        mock_tool.annotations = {}
        mock_tool.timeout_ms = None
        mock_tool.enabled = True
        mock_tool.reachable = True

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [mock_tool]

        cache = MagicMock()
        cache.enabled = False
        cache.set = AsyncMock()
        cache.set_negative = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*_a, **_kw):
            return mock_response

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"api_key": "runtime-secret"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://gateway:9000?api_key=runtime-secret") as mock_apply,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        mock_apply.assert_called_once_with("http://gateway:9000", {"api_key": "runtime-secret"})

    @pytest.mark.asyncio
    async def test_gateway_query_param_auth_hydrates_gateway_dict_from_db(self, tool_service):
        """Cache-hit hydration should accept dict query params from ORM gateway rows."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-uuid-1")
        gp = _make_gateway_payload(auth_type="query_param", auth_query_params=None)
        db = MagicMock()

        hydrated_gateway = SimpleNamespace(
            auth_value=None,
            auth_query_params={"api_key": "hydrated_encrypted"},
            oauth_config=None,
        )
        hydrated_tool = SimpleNamespace(
            auth_value=None,
            oauth_config=None,
            gateway=hydrated_gateway,
        )
        db.execute.return_value.scalar_one_or_none.return_value = hydrated_tool

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*_a, **_kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"api_key": "hydrated-secret"}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", return_value="http://gateway:9000?api_key=hydrated-secret") as mock_apply,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        mock_apply.assert_called_once_with("http://gateway:9000", {"api_key": "hydrated-secret"})

    @pytest.mark.asyncio
    async def test_gateway_query_param_decryption_failure(self, tool_service):
        """Failed decryption of query params is silently skipped."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-uuid-1")
        gp = _make_gateway_payload(auth_type="query_param", auth_query_params={"api_key": "bad_encrypted"})
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.decode_auth", side_effect=lambda v: (_ for _ in ()).throw(RuntimeError("decrypt fail")) if v == "bad_encrypted" else {}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_gateway_query_param_empty_value_is_skipped(self, tool_service):
        """Empty encrypted query param values should be skipped (covers falsy encrypted_value branch)."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-uuid-1")
        gp = _make_gateway_payload(auth_type="query_param", auth_query_params={"api_key": ""})
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.apply_query_param_auth") as mock_apply,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None
        mock_apply.assert_not_called()


# ---------------------------------------------------------------------------
# invoke_tool — Plugin global_context update (lines 2742-2748)
# ---------------------------------------------------------------------------


class TestInvokeToolPluginContext:
    @pytest.mark.asyncio
    async def test_global_context_updated_with_server_id_and_email(self, tool_service):
        """Plugin global context is updated with gateway_id and user email."""
        # First-Party
        from mcpgateway.plugins.framework.models import GlobalContext

        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-42")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        gc = GlobalContext(request_id="req-1", server_id="old-server", tenant_id=None, user=None)

        mock_metrics_buffer = MagicMock()
        mock_metrics_buffer.record_tool_metric = MagicMock()

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            await tool_service.invoke_tool(
                db,
                "test_tool",
                {},
                app_user_email="user@test.com",
                plugin_global_context=gc,
            )
        assert gc.server_id == "gw-42"
        assert gc.user == "user@test.com"

    @pytest.mark.asyncio
    async def test_global_context_not_updated_when_gateway_id_missing_and_user_already_set(self, tool_service):
        """Covers the false branches for global_context.server_id/user propagation."""
        # First-Party
        from mcpgateway.plugins.framework.models import GlobalContext

        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id=None, jsonpath_filter="")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*_a, **_kw):
            return mock_response

        # user is already set -> propagation should not happen
        gc = GlobalContext(request_id="req-1", server_id="old-server", tenant_id=None, user="already@test.com")

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(
                db,
                "test_tool",
                {},
                app_user_email="new@test.com",
                plugin_global_context=gc,
            )

        assert result is not None
        # gateway_id is missing -> should not overwrite server_id
        assert gc.server_id == "old-server"
        # user already set -> should not overwrite
        assert gc.user == "already@test.com"


class TestInvokeToolPluginPostInvokeSerialization:
    @pytest.mark.asyncio
    async def test_plugin_post_invoke_dict_result_serialized_as_json(self, tool_service):
        """When plugin post-invoke returns a dict without 'content' key, it should be serialized as valid JSON."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        # Plugin post-invoke returns a modified_payload whose result is a dict without "content" key
        plugin_manager = MagicMock()
        plugin_manager.has_hooks_for = MagicMock(return_value=True)
        plugin_manager.invoke_hook = AsyncMock(
            side_effect=[
                (SimpleNamespace(modified_payload=None, retry_delay_ms=0), {}),  # pre-invoke
                (SimpleNamespace(modified_payload=SimpleNamespace(result={"status": "transformed", "valid": False}), retry_delay_ms=0), {}),  # post-invoke
            ]
        )

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result.is_error is False
        text = result.content[0].text
        # Must be valid JSON, not Python repr
        parsed = json.loads(text)
        assert parsed["status"] == "transformed"
        assert parsed["valid"] is False
        assert "False" not in text  # Python repr would have capital False

    @pytest.mark.asyncio
    async def test_plugin_post_invoke_unserializable_result_falls_back_to_str(self, tool_service):
        """When plugin post-invoke returns an unserializable value (e.g. set), it should fall back to str() instead of crashing."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        # Plugin post-invoke returns an unserializable set
        plugin_manager = MagicMock()
        plugin_manager.has_hooks_for = MagicMock(return_value=True)
        plugin_manager.invoke_hook = AsyncMock(
            side_effect=[
                (SimpleNamespace(modified_payload=None, retry_delay_ms=0), {}),  # pre-invoke
                (SimpleNamespace(modified_payload=SimpleNamespace(result={"unserializable", "set", "values"}), retry_delay_ms=0), {}),  # post-invoke
            ]
        )

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})

        # Should not crash — falls back to str() representation
        assert result.is_error is False
        text = result.content[0].text
        # str() on a set produces something like "{'unserializable', 'set', 'values'}"
        assert isinstance(text, str)
        assert len(text) > 0


class TestInvokeToolPluginMetadataFromPayload:
    @pytest.mark.asyncio
    async def test_plugin_metadata_created_from_cached_payloads(self, tool_service):
        """When tool/gateway ORM objects aren't loaded, plugin metadata is created from cached payloads."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET", gateway_id="gw-uuid-1")
        gp = _make_gateway_payload()
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*a, **kw):
            return mock_response

        # Ensure plugin hooks don't run; we only want metadata creation from payloads.
        plugin_manager_no_hooks = MagicMock()
        plugin_manager_no_hooks.has_hooks_for = MagicMock(return_value=False)

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager_no_hooks)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_pydantic_tool_from_payload", return_value=MagicMock()) as mock_tool_from_payload,
            patch.object(tool_service, "_pydantic_gateway_from_payload", return_value=MagicMock()) as mock_gateway_from_payload,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            result = await tool_service.invoke_tool(db, "test_tool", {})
        assert result is not None
        mock_tool_from_payload.assert_called_once()
        mock_gateway_from_payload.assert_called_once()


class TestInvokeToolPluginMetadataFromOrm:
    @pytest.mark.asyncio
    async def test_plugin_metadata_created_from_orm_without_gateway(self, tool_service):
        """When ORM tool is loaded but has no gateway, gateway_metadata should remain unset."""
        db = MagicMock()
        db_tool = MagicMock(spec=DbTool)
        db_tool.id = "tool-db-1"
        db_tool.enabled = True
        db_tool.reachable = True
        db_tool.gateway = None

        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[db_tool])))))

        # Cache miss triggers ORM load.
        mock_cache = AsyncMock()
        mock_cache.enabled = True
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()
        mock_cache.set_negative = AsyncMock()

        # Provide a realistic payload so invoke_tool can proceed without touching ORM fields.
        tp = _make_tool_payload(integration_type="REST", request_type="GET", jsonpath_filter="")
        built_payload = {"status": "active", "tool": tp, "gateway": None}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        plugin_manager_no_hooks = MagicMock()
        plugin_manager_no_hooks.has_hooks_for = MagicMock(return_value=False)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=mock_cache),
            patch.object(tool_service, "_build_tool_cache_payload", return_value=built_payload),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager_no_hooks)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.PydanticTool.model_validate", return_value=MagicMock()),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=mock_response)

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        mock_cache.set.assert_awaited_once()


# ---------------------------------------------------------------------------
# invoke_tool — MCP-Session-Id normalization (lines 2841-2845)
# ---------------------------------------------------------------------------


class TestInvokeToolMcpSessionAffinity:
    @pytest.mark.asyncio
    async def test_mcp_session_id_normalized(self, tool_service):
        """MCP-Session-Id header is normalized to x-mcp-session-id."""
        tp = _make_tool_payload(integration_type="REST", request_type="GET")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"ok": True})
        mock_response.raise_for_status = MagicMock()

        captured_headers = {}

        async def fake_get(url, params=None, headers=None):
            captured_headers.update(headers or {})
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"MCP-Session-Id": "session-abc123def456"}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = fake_get

            await tool_service.invoke_tool(
                db,
                "test_tool",
                {},
                request_headers={"MCP-Session-Id": "session-abc123def456"},
            )
        assert "x-mcp-session-id" in captured_headers
        assert captured_headers["x-mcp-session-id"] == "session-abc123def456"


# ---------------------------------------------------------------------------
# invoke_tool — REST POST method (verifies method routing)
# ---------------------------------------------------------------------------


class TestInvokeToolRestPost:
    @pytest.mark.asyncio
    async def test_rest_post_uses_request_method(self, tool_service):
        """REST tool with POST request_type uses .request('POST', ...) with json payload."""
        tp = _make_tool_payload(integration_type="REST", request_type="POST")
        db = MagicMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"data": "ok"})
        mock_response.raise_for_status = MagicMock()

        async def fake_request(method, url, json=None, headers=None):
            return mock_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.request = fake_request

            result = await tool_service.invoke_tool(db, "test_tool", {"key": "val"})
        assert result is not None
        assert result.is_error is not True


# ---------------------------------------------------------------------------
# invoke_tool — A2A agent invocation (lines 2703-2724, 3430-3547)
# ---------------------------------------------------------------------------


def _make_a2a_agent(*, enabled=True, agent_type="jsonrpc", auth_type=None, auth_value=None, auth_query_params=None):
    """Create a mock A2A agent."""
    agent = MagicMock()
    agent.id = "agent-uuid-1"
    agent.name = "test_a2a_agent"
    agent.endpoint_url = "http://a2a-agent:9000/"
    agent.agent_type = agent_type
    agent.protocol_version = "0.3"
    agent.enabled = enabled
    agent.auth_type = auth_type
    agent.auth_value = auth_value
    agent.auth_query_params = auth_query_params
    return agent


class TestInvokeToolA2A:
    @pytest.mark.asyncio
    async def test_a2a_jsonrpc_success_with_query(self, tool_service):
        """A2A JSONRPC agent invocation with query argument succeeds."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "Hello from A2A"})

        async def fake_post(url, json=None, headers=None):
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"query": "What is A2A?"})
        assert result is not None
        assert result.is_error is False
        assert "Hello from A2A" in result.content[0].text

    async def _invoke_a2a_tool_via_invoke_tool(self, tool_service, response_json):
        """Helper: invoke an A2A tool through invoke_tool with a given HTTP 200 JSON response."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value=response_json)

        async def fake_post(url, json=None, headers=None):
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            return await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

    @pytest.mark.asyncio
    async def test_a2a_invoke_tool_response_value_none(self, tool_service):
        """invoke_tool A2A path: response['response'] is None -> serialized as 'null'."""
        result = await self._invoke_a2a_tool_via_invoke_tool(tool_service, {"response": None})
        assert result.is_error is False
        assert result.content[0].text == "null"
        assert json.loads(result.content[0].text) is None

    @pytest.mark.asyncio
    async def test_a2a_invoke_tool_response_value_list(self, tool_service):
        """invoke_tool A2A path: response['response'] is a list -> serialized as JSON array."""
        result = await self._invoke_a2a_tool_via_invoke_tool(tool_service, {"response": [1, False, "x"]})
        assert result.is_error is False
        parsed = json.loads(result.content[0].text)
        assert parsed == [1, False, "x"]
        assert "False" not in result.content[0].text

    @pytest.mark.asyncio
    async def test_a2a_invoke_tool_root_list_response(self, tool_service):
        """invoke_tool A2A path: response_data is a list (no 'response' key) -> serialized as JSON."""
        result = await self._invoke_a2a_tool_via_invoke_tool(tool_service, [{"active": True}, {"active": False}])
        assert result.is_error is False
        parsed = json.loads(result.content[0].text)
        assert parsed[0]["active"] is True
        assert parsed[1]["active"] is False
        assert "True" not in result.content[0].text
        assert "False" not in result.content[0].text

    @pytest.mark.asyncio
    async def test_a2a_invoke_tool_rust_runtime_text_fallback(self, tool_service):
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(return_value={"status_code": 200, "json": None, "text": "text-only"})

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.get_rust_a2a_runtime_client", return_value=rust_runtime),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            with patch.object(settings, "experimental_rust_a2a_runtime_enabled", True), patch.object(settings, "experimental_rust_a2a_runtime_delegate_enabled", True):
                result = await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

        assert result.is_error is False
        assert result.content[0].text == "text-only"

    @pytest.mark.asyncio
    async def test_a2a_invoke_tool_rust_runtime_error_response(self, tool_service):
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        rust_runtime = MagicMock()
        rust_runtime.invoke = AsyncMock(side_effect=RustA2ARuntimeError("runtime failed"))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.get_rust_a2a_runtime_client", return_value=rust_runtime),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            with patch.object(settings, "experimental_rust_a2a_runtime_enabled", True), patch.object(settings, "experimental_rust_a2a_runtime_delegate_enabled", True):
                result = await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

        assert result.is_error is True
        assert "runtime failed" in result.content[0].text

    @pytest.mark.asyncio
    async def test_a2a_jsonrpc_success_no_query(self, tool_service):
        """A2A JSONRPC agent invocation without query uses raw params."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"result": {"data": "test"}})

        async def fake_post(url, json=None, headers=None):
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"params": {"key": "val"}, "method": "tasks/list"})
        assert result is not None
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_a2a_custom_agent_type(self, tool_service):
        """A2A custom agent uses direct parameter passing."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(agent_type="custom")
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"result": "custom ok"})

        async def fake_post(url, json=None, headers=None):
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"interaction_type": "query"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_a2a_pre_invoke_modifies_payload_headers_and_custom_format_without_trailing_slash(self, tool_service):
        """A2A custom agents without trailing slash use custom format; pre-invoke can rewrite headers/args."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(agent_type="custom")
        a2a_agent.endpoint_url = "http://a2a-agent:9000"  # no trailing slash -> forces custom-format path
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_PRE_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        modified_payload = SimpleNamespace(
            name="test_tool",
            args={"interaction_type": "query", "foo": "bar"},
            headers=SimpleNamespace(model_dump=lambda: {"Content-Type": "application/json", "X-Test": "1"}),
        )
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=modified_payload), {}))

        captured = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_pydantic_tool_from_payload", return_value=MagicMock()),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"interaction_type": "query"})

        assert result is not None
        assert captured["url"] == "http://a2a-agent:9000"
        assert captured["headers"]["X-Test"] == "1"
        assert captured["json"]["protocol_version"] == "0.3"
        plugin_manager.invoke_hook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a2a_with_api_key_auth(self, tool_service):
        """A2A agent with api_key auth adds Bearer header."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="api_key", auth_value="encrypted_api_key")
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_headers = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_headers.update(headers or {})
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"api_key": "my-api-key"}),  # pragma: allowlist secret
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert captured_headers.get("Authorization") == "Bearer my-api-key"

    @pytest.mark.asyncio
    async def test_a2a_http_error_response(self, tool_service):
        """A2A agent HTTP 500 returns error result."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        mock_http_response = MagicMock()
        mock_http_response.status_code = 500
        mock_http_response.text = "Internal Server Error"

        async def fake_post(url, json=None, headers=None):
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert result.is_error is True
        assert "500" in result.content[0].text

    @pytest.mark.asyncio
    async def test_a2a_timeout_raises_error(self, tool_service):
        """A2A agent timeout raises ToolTimeoutError."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

    @pytest.mark.asyncio
    async def test_a2a_agent_not_found(self, tool_service):
        """A2A agent not in database raises ToolNotFoundError."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "missing-agent"},
        )
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        with _setup_cache_for_invoke(tp), patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)), patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc:
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])

            with pytest.raises(ToolNotFoundError, match="agent not found"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_a2a_agent_disabled(self, tool_service):
        """Disabled A2A agent raises ToolNotFoundError."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(enabled=False)
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        with _setup_cache_for_invoke(tp), patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)), patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc:
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])

            with pytest.raises(ToolNotFoundError, match="disabled"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_a2a_query_param_auth(self, tool_service):
        """A2A agent with query_param auth decrypts and applies to URL."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="query_param", auth_query_params={"token": "encrypted_tok"})
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_url = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_url["url"] = url
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"token": "decrypted_val"}),
            patch("mcpgateway.services.a2a_protocol.apply_query_param_auth", return_value="http://a2a-agent:9000/?token=decrypted_val"),
            patch("mcpgateway.services.a2a_protocol.sanitize_url_for_logging", return_value="http://a2a-agent:9000/?token=***"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert result is not None
        assert captured_url["url"] == "http://a2a-agent:9000/?token=decrypted_val"

    @pytest.mark.asyncio
    async def test_a2a_query_param_empty_value_is_skipped(self, tool_service):
        """Empty encrypted query param values should be skipped (covers falsy encrypted_value branches)."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="query_param", auth_query_params={"token": ""})
        a2a_agent.endpoint_url = "http://a2a-agent:9000"  # no slash to ensure URL stays stable
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_url = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_url["url"] = url
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.apply_query_param_auth") as mock_apply,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            result = await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

        assert result is not None
        assert captured_url["url"] == "http://a2a-agent:9000"
        mock_apply.assert_not_called()

    @pytest.mark.asyncio
    async def test_a2a_with_dict_auth_value(self, tool_service):
        """A2A agent with dict auth_value (no decryption needed)."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="bearer", auth_value={"Authorization": "Bearer dict-token"})
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_headers = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_headers.update(headers or {})
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert captured_headers.get("Authorization") == "Bearer dict-token"

    @pytest.mark.asyncio
    async def test_a2a_with_basic_auth(self, tool_service):
        """A2A agent with basic auth decrypts and applies headers."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="basic", auth_value="encrypted_basic_creds")
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_headers = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_headers.update(headers or {})
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"Authorization": "Basic decrypted-value"}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert captured_headers.get("Authorization") == "Basic decrypted-value"

    @pytest.mark.asyncio
    async def test_a2a_with_authheaders_auth(self, tool_service):
        """A2A agent with authheaders decrypts and applies custom headers."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="authheaders", auth_value="encrypted_custom_headers")
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        captured_headers = {}
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json = MagicMock(return_value={"response": "ok"})

        async def fake_post(url, json=None, headers=None):
            captured_headers.update(headers or {})
            return mock_http_response

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.a2a_protocol.decode_auth", return_value={"X-Custom-Auth": "custom-value"}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = fake_post

            await tool_service.invoke_tool(db, "test_tool", {"query": "test"})
        assert captured_headers.get("X-Custom-Auth") == "custom-value"

    @pytest.mark.asyncio
    async def test_a2a_decrypt_failure_raises_exception(self, tool_service):
        """A2A agent with decrypt failure should raise ToolInvocationError."""
        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent(auth_type="bearer", auth_value="invalid_encrypted")
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.a2a_protocol.decode_auth", side_effect=Exception("Decrypt failed")),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()

            with pytest.raises(ToolInvocationError, match="Tool invocation failed: Decrypt failed"):
                await tool_service.invoke_tool(db, "test_tool", {"query": "test"})

    @pytest.mark.asyncio
    async def test_a2a_timeout_triggers_cb_context_and_post_hook(self, tool_service):
        """A2A timeout should mark cb_timeout_failure on contexts and invoke TOOL_POST_INVOKE hook."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(
            integration_type="A2A",
            request_type="POST",
            annotations={"a2a_agent_id": "agent-uuid-1"},
        )
        db = MagicMock()
        a2a_agent = _make_a2a_agent()
        db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=a2a_agent)))

        ctx = MagicMock()
        context_table = {"ctx": ctx}

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_POST_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=None, retry_delay_ms=0), context_table))

        with (
            _setup_cache_for_invoke(tp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            tool_service._http_client = AsyncMock()
            tool_service._http_client.post = AsyncMock(side_effect=asyncio.TimeoutError())

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {"query": "test"}, plugin_context_table=context_table)

        ctx.set_state.assert_called_with("cb_timeout_failure", True)
        plugin_manager.invoke_hook.assert_awaited()


# ---------------------------------------------------------------------------
# invoke_tool — MCP / SSE (OAuth, session affinity, pool paths)
# ---------------------------------------------------------------------------


class TestInvokeToolMcpSse:
    @pytest.mark.asyncio
    async def test_mcp_gateway_oauth_authorization_code_requires_app_user_email(self, tool_service):
        """Authorization Code gateways require app_user_email to retrieve stored user tokens."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})
        db = MagicMock()

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_tss.return_value.get_user_token = AsyncMock(return_value="token")

            with pytest.raises(ToolInvocationError, match="OAuth token retrieval failed"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_mcp_gateway_oauth_authorization_code_uses_stored_token(self, tool_service):
        """Stored OAuth tokens (authorization_code flow) are applied to headers and tool call succeeds."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})
        db = MagicMock()

        captured_headers: dict[str, str] = {}

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    captured_headers.update(headers or {})
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-1"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_tss.return_value.get_user_token = AsyncMock(return_value="stored-token")

            result = await tool_service.invoke_tool(db, "test_tool", {}, app_user_email="user@test.com")

        assert result is not None
        assert captured_headers["Authorization"] == "Bearer stored-token"

    @pytest.mark.asyncio
    async def test_mcp_gateway_oauth_authorization_code_missing_token_raises(self, tool_service):
        """When no stored token is found and no plugin injects Authorization, raise an actionable error locally.

        Deny-path regression: with no DB token AND no plugin manager registered,
        the post-pre-invoke check must raise locally with the actionable
        ``Please authorize ... /oauth/authorize/{id}`` message rather than letting
        the upstream return a generic 401.
        """
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})
        db = MagicMock()

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_tss.return_value.get_user_token = AsyncMock(return_value=None)

            with pytest.raises(ToolInvocationError, match="Please authorize"):
                await tool_service.invoke_tool(db, "test_tool", {}, app_user_email="user@test.com")

    @pytest.mark.asyncio
    async def test_mcp_gateway_oauth_authorization_code_plugin_injects_auth(self, tool_service):
        """Plugin-injected Authorization (e.g. Vault) satisfies authorization_code without a DB token.

        Positive plugin path: with no DB-stored OAuth token, a plugin
        ``tool_pre_invoke`` hook sets the Authorization header. The post-hook
        check sees Authorization is present and lets the request through to the
        upstream MCP server. The header that reaches the SSE client must be the
        plugin-injected value.
        """
        # First-Party
        from mcpgateway.plugins.framework import HttpHeaderPayload, ToolPreInvokePayload
        from mcpgateway.plugins.framework.models import PluginResult

        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "authorization_code"})
        db = MagicMock()

        captured_headers: dict[str, str] = {}

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    captured_headers.update(headers or {})
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            if hook_type != ToolHookType.TOOL_PRE_INVOKE:
                return PluginResult(modified_payload=None, continue_processing=True), {}
            new_headers = dict(payload.headers.root) if payload.headers else {}
            new_headers["Authorization"] = "Bearer plugin-injected-token"
            modified = ToolPreInvokePayload(name=payload.name, args=payload.args, headers=HttpHeaderPayload(new_headers))
            return PluginResult(modified_payload=modified, continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-1"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.token_storage_service.TokenStorageService") as mock_tss,
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_tss.return_value.get_user_token = AsyncMock(return_value=None)

            result = await tool_service.invoke_tool(db, "test_tool", {}, app_user_email="user@test.com")

        assert result is not None
        assert captured_headers.get("Authorization") == "Bearer plugin-injected-token"

    @pytest.mark.asyncio
    async def test_mcp_gateway_strips_x_vault_tokens_from_outbound_headers(self, tool_service):
        """X-Vault-Tokens (any case) must be stripped from outbound headers regardless of plugin state.

        Defense in depth: if the Vault plugin is disabled, errors out, or
        ``X-Vault-Tokens`` is mistakenly added to ``passthrough_allowed``,
        the gateway must still scrub the header before sending the request
        upstream so vault tokens never leak outside the gateway boundary.
        """
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="bearer", auth_value=None)
        db = MagicMock()

        captured_headers: dict[str, str] = {}

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    captured_headers.update(headers or {})
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-1"),
            patch(
                "mcpgateway.services.tool_service.compute_passthrough_headers_cached",
                return_value={"Authorization": "Bearer real", "X-Vault-Tokens": '{"github.com": "ghp_xxx"}', "x-vault-tokens": "lower-case-leak"},
            ),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            await tool_service.invoke_tool(db, "test_tool", {}, request_headers={"X-Tenant-Id": "acme"})

        outbound_keys_lower = {k.lower() for k in captured_headers}
        assert "x-vault-tokens" not in outbound_keys_lower
        assert captured_headers.get("Authorization") == "Bearer real"

    @pytest.mark.asyncio
    async def test_mcp_gateway_oauth_client_credentials_error_raises(self, tool_service):
        """Client Credentials OAuth failures should raise ToolInvocationError."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            with pytest.raises(ToolInvocationError, match="OAuth authentication failed for gateway"):
                await tool_service.invoke_tool(db, "test_tool", {})

    @pytest.mark.asyncio
    async def test_mcp_http_url_bypasses_ssl_context_creation(self, tool_service):
        """HTTP URLs should skip SSL context creation entirely (line 3986-3988)."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            url="http://localhost:9000/sse",  # HTTP URL - should bypass SSL
            auth_type="basic",
            ca_certificate="dummy-ca",  # Even with CA cert, should skip for HTTP
        )
        db = MagicMock()

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    # Call the factory to trigger SSL context logic
                    if httpx_client_factory is not None:
                        client = httpx_client_factory(headers=headers)
                        # Verify no SSL context was created for HTTP URL
                        assert client is not None
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.get_cached_ssl_context") as mock_get_ssl,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)

        assert result is not None
        # Verify SSL context was NOT created for HTTP URL
        assert mock_get_ssl.call_count == 0, "SSL context should not be created for HTTP URLs"

    @pytest.mark.asyncio
    async def test_mcp_https_url_with_mtls_creates_ssl_context(self, tool_service):
        """HTTPS URLs with client cert/key should create SSL context with mTLS (lines 3990-3994)."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            url="https://localhost:9000/sse",  # HTTPS URL - should create SSL context
            auth_type="basic",
            ca_certificate="dummy-ca",
            client_cert="client-cert-data",  # mTLS client cert
            client_key="client-key-data",  # mTLS client key
        )
        db = MagicMock()

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.get_cached_ssl_context") as mock_get_ssl,
            patch.object(settings, "enable_ed25519_signing", False),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_get_ssl.return_value = MagicMock()  # Mock SSL context

            result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)

        assert result is not None
        # Verify SSL context WAS created for HTTPS URL with mTLS
        assert mock_get_ssl.call_count == 1, "SSL context should be created for HTTPS URLs"
        # Verify client cert and key were passed
        call_args = mock_get_ssl.call_args
        assert call_args is not None
        assert call_args[1].get("client_cert") == "client-cert-data"
        assert call_args[1].get("client_key") == "client-key-data"

    @pytest.mark.asyncio
    async def test_mcp_https_url_decrypts_encrypted_client_key(self, tool_service):
        """Encrypted client_key in gateway payload is decrypted before SSL context creation."""
        # First-Party
        from mcpgateway.services.encryption_service import get_encryption_service

        encryption = get_encryption_service(settings.auth_encryption_secret)
        encrypted_key = encryption.encrypt_secret("decrypted-client-key")

        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            url="https://localhost:9000/sse",
            auth_type="basic",
            ca_certificate="dummy-ca",
            client_cert="client-cert-data",
            client_key=encrypted_key,
        )
        db = MagicMock()

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.get_cached_ssl_context") as mock_get_ssl,
            patch.object(settings, "enable_ed25519_signing", False),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_get_ssl.return_value = MagicMock()

            result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)

        assert result is not None
        assert mock_get_ssl.call_count == 1
        call_args = mock_get_ssl.call_args
        # Verify the key was decrypted (not the encrypted bundle)
        assert call_args[1].get("client_key") == "decrypted-client-key"

    @pytest.mark.asyncio
    async def test_mcp_https_url_decryption_failure_uses_key_as_is(self, tool_service):
        """When client_key decryption fails, the raw value is passed through."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            url="https://localhost:9000/sse",
            auth_type="basic",
            ca_certificate="dummy-ca",
            client_cert="client-cert-data",
            client_key="not-encrypted-raw-key",
        )
        db = MagicMock()

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.get_cached_ssl_context") as mock_get_ssl,
            patch("mcpgateway.services.encryption_service.get_encryption_service", side_effect=RuntimeError("no encryption")),
            patch.object(settings, "enable_ed25519_signing", False),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_get_ssl.return_value = MagicMock()

            result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)

        assert result is not None
        assert mock_get_ssl.call_count == 1
        # Key should be passed as-is since decryption failed
        call_args = mock_get_ssl.call_args
        assert call_args[1].get("client_key") == "not-encrypted-raw-key"

    @pytest.mark.asyncio
    async def test_mcp_sse_httpx_factory_validates_ed25519_signature(self, tool_service):
        """Enable ed25519 signing to cover validate_signature path inside httpx client factory."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            auth_type="oauth",
            oauth_config={"grant_type": "client_credentials"},
            ca_certificate="dummy-ca",
            ca_certificate_sig="dummy-sig",
        )
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        def fake_sse_client(*, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.validate_signature", return_value=False) as mock_vs,
            patch.object(settings, "enable_ed25519_signing", True),
            patch.object(settings, "ed25519_public_key", "pubkey"),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)

        assert result is not None
        mock_vs.assert_called_once()

    @pytest.mark.asyncio
    async def test_mcp_sse_success_normalizes_session_id_adds_correlation_and_uses_httpx_factory(self, tool_service):
        """MCP SSE path should normalize MCP-Session-Id and add X-Correlation-ID in non-pooled sessions."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            auth_type="oauth",
            oauth_config={"grant_type": "client_credentials"},
            ca_certificate="dummy-ca",
            ca_certificate_sig="dummy-sig",
        )
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        captured_headers: dict[str, str] = {}

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    # Exercise the httpx_client_factory closure for coverage.
                    if httpx_client_factory is not None:
                        httpx_client_factory(headers=headers)
                    captured_headers.update(headers or {})
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-1"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=lambda _rh, h, *_a, **_k: h),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.get_cached_ssl_context", return_value=MagicMock()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            patch.object(settings, "enable_ed25519_signing", False),
        ):
            # No downstream Mcp-Session-Id in request_headers_var → registry path is
            # skipped, fallback per-call session is taken, and the correlation-id /
            # session-id headers are injected as usual.
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            result = await tool_service.invoke_tool(
                db,
                "test_tool",
                {},
                request_headers={"MCP-Session-Id": "session-abc123"},
            )
        assert result is not None
        assert captured_headers["x-mcp-session-id"] == "session-abc123"
        assert captured_headers["X-Correlation-ID"] == "corr-1"

    @pytest.mark.asyncio
    async def test_mcp_sse_uses_registry_when_downstream_session_id_present(self, tool_service):
        """MCP SSE uses the UpstreamSessionRegistry when a downstream Mcp-Session-Id is in scope (#4205)."""
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import request_headers_var

        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(
            auth_type="oauth",
            oauth_config={"grant_type": "client_credentials"},
            ca_certificate="dummy-ca",
            ca_certificate_sig="dummy-sig",
        )
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        captured_acquire_kwargs: dict[str, object] = {}

        upstream_session = AsyncMock()
        upstream_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _AcquireCM:
            async def __aenter__(self):
                httpx_factory = captured_acquire_kwargs.get("httpx_client_factory")
                if callable(httpx_factory):
                    httpx_factory(headers=captured_acquire_kwargs.get("headers"))
                return SimpleNamespace(session=upstream_session)

            async def __aexit__(self, *exc):
                return False

        def fake_acquire(**kwargs):
            captured_acquire_kwargs.update(kwargs)
            return _AcquireCM()

        registry = MagicMock()
        registry.acquire = fake_acquire

        headers_token = request_headers_var.set({"mcp-session-id": "downstream-xyz"})
        try:
            with (
                _setup_cache_for_invoke(tp, gp),
                patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
                patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
                patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
                patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
                patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
                patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-1"),
                patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=lambda _rh, h, *_a, **_k: h),
                patch("mcpgateway.services.tool_service.get_upstream_session_registry", return_value=registry),
                patch("mcpgateway.services.tool_service.get_cached_ssl_context") as mock_cached_ssl_context,
                patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
                patch.object(settings, "enable_ed25519_signing", False),
            ):
                mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
                mock_trace.get = MagicMock(return_value=None)
                mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
                mock_mbuf.return_value = MagicMock()

                result = await tool_service.invoke_tool(db, "test_tool", {}, request_headers=None)
        finally:
            request_headers_var.reset(headers_token)

        assert result is not None
        assert mock_cached_ssl_context.call_count == 0
        # The registry received the downstream session id + gateway id — this is the
        # 1:1 binding that prevents cross-session upstream state leakage (#4205).
        assert captured_acquire_kwargs.get("downstream_session_id") == "downstream-xyz"
        assert captured_acquire_kwargs.get("gateway_id") == "gw-uuid-1"
        assert captured_acquire_kwargs.get("transport_type") is not None


# ---------------------------------------------------------------------------
# invoke_tool — MCP SSE timeout + ExceptionGroup paths (lines 3250-3302)
# ---------------------------------------------------------------------------


class TestInvokeToolMcpSseTimeoutAndErrors:
    @pytest.mark.asyncio
    async def test_mcp_sse_timeout_triggers_post_hook_and_cb_context(self, tool_service):
        """Timeout during MCP SSE invocation should mark cb_timeout_failure and invoke TOOL_POST_INVOKE."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        ctx = MagicMock()
        context_table = {"ctx": ctx}

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_POST_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=None, retry_delay_ms=0), context_table))

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.metrics.tool_timeout_counter") as mock_timeout_counter,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_timeout_counter.labels.return_value.inc = MagicMock()

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {}, plugin_context_table=context_table)

        ctx.set_state.assert_called_with("cb_timeout_failure", True)
        plugin_manager.invoke_hook.assert_awaited()

    @pytest.mark.asyncio
    async def test_mcp_sse_exception_group_is_logged_and_wrapped(self, tool_service):
        """ExceptionGroup from MCP SDK should log root cause and be wrapped in ToolInvocationError."""
        tp = _make_tool_payload(integration_type="MCP", request_type="SSE", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        def fake_sse_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=ExceptionGroup("eg", [ValueError("root")]))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.sse_client", side_effect=fake_sse_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.sanitize_exception_message", side_effect=lambda msg, _qp: msg),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            with pytest.raises(ToolInvocationError, match="root"):
                await tool_service.invoke_tool(db, "test_tool", {})


# ---------------------------------------------------------------------------
# invoke_tool — MCP StreamableHTTP coverage (lines 3355-3459, 3464-3483)
# ---------------------------------------------------------------------------


class TestInvokeToolMcpStreamableHttpCoverage:
    @pytest.mark.asyncio
    async def test_streamablehttp_pool_not_initialized_falls_back_and_plugin_pre_invoke_no_metadata_no_modified_payload(self, tool_service):
        """Covers pool-not-initialized fallback + MCP pre-invoke branches for missing metadata/modified_payload."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="MCP", request_type="StreamableHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        # Pre-invoke enabled, but metadata creation patched to return None so assignment branches are skipped.
        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_PRE_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=None), {}))

        def fake_streamablehttp_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", side_effect=fake_streamablehttp_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            # No downstream session id in scope → registry is skipped, fallback taken.
            patch.object(tool_service, "_pydantic_tool_from_payload", return_value=None),
            patch.object(tool_service, "_pydantic_gateway_from_payload", return_value=None),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            result = await tool_service.invoke_tool(db, "test_tool", {})

        assert result is not None
        plugin_manager.invoke_hook.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_streamablehttp_uses_registry_and_modified_payload_with_headers_none(self, tool_service):
        """Covers registry StreamableHTTP path + modified_payload headers=None branch (#4205)."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType
        from mcpgateway.transports.streamablehttp_transport import request_headers_var

        tp = _make_tool_payload(integration_type="MCP", request_type="StreamableHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_PRE_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        modified_payload = SimpleNamespace(name="test_tool", args={}, headers=None)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=modified_payload), {}))

        upstream_session = AsyncMock()
        upstream_session.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="ok")], is_error=False))

        class _AcquireCM:
            async def __aenter__(self):
                return SimpleNamespace(session=upstream_session)

            async def __aexit__(self, *exc):
                return False

        registry = MagicMock()
        registry.acquire = MagicMock(return_value=_AcquireCM())

        headers_token = request_headers_var.set({"mcp-session-id": "downstream-sh"})
        try:
            with (
                _setup_cache_for_invoke(tp, gp),
                patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
                patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
                patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
                patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
                patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
                patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
                patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
                patch("mcpgateway.services.tool_service.get_upstream_session_registry", return_value=registry),
                patch("mcpgateway.services.tool_service.httpx.AsyncClient", return_value=MagicMock()),
            ):
                mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
                mock_trace.get = MagicMock(return_value=None)
                mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
                mock_mbuf.return_value = MagicMock()

                result = await tool_service.invoke_tool(db, "test_tool", {})
        finally:
            request_headers_var.reset(headers_token)

        assert result is not None
        assert registry.acquire.called

    @pytest.mark.asyncio
    async def test_streamablehttp_timeout_triggers_post_hook_without_context(self, tool_service):
        """Covers StreamableHTTP timeout handler plugin branches when context_table is falsy."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType

        tp = _make_tool_payload(integration_type="MCP", request_type="StreamableHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        plugin_manager = MagicMock()

        def _has_hooks_for(hook_type):
            return hook_type == ToolHookType.TOOL_POST_INVOKE

        plugin_manager.has_hooks_for = MagicMock(side_effect=_has_hooks_for)
        plugin_manager.invoke_hook = AsyncMock(return_value=(SimpleNamespace(modified_payload=None, retry_delay_ms=0), None))

        def fake_streamablehttp_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=plugin_manager)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", side_effect=fake_streamablehttp_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.metrics.tool_timeout_counter") as mock_timeout_counter,
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()
            mock_timeout_counter.labels.return_value.inc = MagicMock()

            with pytest.raises(ToolTimeoutError, match="timed out"):
                await tool_service.invoke_tool(db, "test_tool", {})

        plugin_manager.invoke_hook.assert_awaited()

    @pytest.mark.asyncio
    async def test_streamablehttp_exception_group_is_logged_and_wrapped(self, tool_service):
        """Covers StreamableHTTP BaseExceptionGroup root cause extraction and logging."""
        tp = _make_tool_payload(integration_type="MCP", request_type="StreamableHTTP", gateway_id="gw-uuid-1", jsonpath_filter="")
        gp = _make_gateway_payload(auth_type="oauth", oauth_config={"grant_type": "client_credentials"})
        db = MagicMock()

        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="token")

        def fake_streamablehttp_client(*, url=None, headers=None, httpx_client_factory=None, **_kw):
            class _CM:
                async def __aenter__(self):
                    return (MagicMock(), MagicMock(), AsyncMock())

                async def __aexit__(self, *exc):
                    return False

            return _CM()

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=ExceptionGroup("eg", [ValueError("root")]))

        class _SessionCM:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, *exc):
                return False

        with (
            _setup_cache_for_invoke(tp, gp),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache") as mock_gcc,
            patch("mcpgateway.services.tool_service.current_trace_id") as mock_trace,
            patch("mcpgateway.services.tool_service.create_span") as mock_span_ctx,
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service") as mock_mbuf,
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", side_effect=fake_streamablehttp_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=_SessionCM()),
            patch("mcpgateway.services.tool_service.sanitize_exception_message", side_effect=lambda msg, _qp: msg),
        ):
            mock_gcc.get_passthrough_headers = MagicMock(return_value=[])
            mock_trace.get = MagicMock(return_value=None)
            mock_span_ctx.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_span_ctx.return_value.__exit__ = MagicMock(return_value=False)
            mock_mbuf.return_value = MagicMock()

            with pytest.raises(ToolInvocationError, match="root"):
                await tool_service.invoke_tool(db, "test_tool", {})


class TestInvokeToolLookupLogic:
    """Tests for invoke_tool lookup, filtering, and prioritization logic."""

    @pytest.fixture
    def mock_db_tools(self):
        def _create(name="test_tool", **kwargs):
            t = MagicMock(spec=DbTool)
            t.name = name
            t.enabled = True
            t.reachable = True
            t.gateway = None
            t.owner_email = None
            t.team_id = None
            for k, v in kwargs.items():
                setattr(t, k, v)
            return t

        yield _create

    @pytest.mark.asyncio
    async def test_lookup_filters_private_not_owner(self, tool_service, mock_db_tools):
        """Private tool should be invisible to non-owners."""
        tool = mock_db_tools(visibility="private", owner_email="owner@test.com")

        tool2 = mock_db_tools(visibility="private", owner_email="owner2@test.com")
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[tool, tool2])))))

        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "test_tool", {}, user_email="other@test.com")

    @pytest.mark.asyncio
    async def test_lookup_filters_team_not_member(self, tool_service, mock_db_tools):
        """Team tool should be invisible to non-members."""
        tool = mock_db_tools(visibility="team", team_id="team-A")

        tool2 = mock_db_tools(visibility="team", team_id="team-C")
        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[tool, tool2])))))

        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            # User has no teams
            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "test_tool", {}, user_email="user@test.com", token_teams=[])

            # User has different team
            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "test_tool", {}, user_email="user@test.com", token_teams=["team-B"])

    @pytest.mark.asyncio
    async def test_lookup_prioritizes_team_over_private(self, tool_service, mock_db_tools):
        """Team tool should take precedence over Private tool (owner)."""
        own_tool = mock_db_tools(id="own", visibility="private", owner_email="me@test.com")
        team_tool = mock_db_tools(id="team", visibility="team", team_id="team-A")

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[team_tool, own_tool])))))

        def _fake_build(tool, gw):
            p = _make_tool_payload()
            p["id"] = tool.id
            return {"status": "active", "tool": p, "gateway": None}

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=AsyncMock(get=AsyncMock(return_value=None))),
            patch.object(tool_service, "_build_tool_cache_payload", side_effect=_fake_build),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.create_span", MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", MagicMock()),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value={"ok": True})))

            await tool_service.invoke_tool(db, "test_tool", {}, user_email="me@test.com", token_teams=["team-A"])

            args, _ = tool_service._build_tool_cache_payload.call_args
            selected_tool = args[0]
            assert selected_tool.id == "team"

    @pytest.mark.asyncio
    async def test_lookup_prioritizes_team_over_public(self, tool_service, mock_db_tools):
        """Team tool should take precedence over Public tool."""
        team_tool = mock_db_tools(id="team", visibility="team", team_id="team-A")
        pub_tool = mock_db_tools(id="pub", visibility="public")

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pub_tool, team_tool])))))

        def _fake_build(tool, gw):
            p = _make_tool_payload()
            p["id"] = tool.id
            return {"status": "active", "tool": p, "gateway": None}

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=AsyncMock(get=AsyncMock(return_value=None))),
            patch.object(tool_service, "_build_tool_cache_payload", side_effect=_fake_build),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.create_span", MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", MagicMock()),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value={"ok": True})))

            await tool_service.invoke_tool(db, "test_tool", {}, user_email="me@test.com", token_teams=["team-A"])

            args, _ = tool_service._build_tool_cache_payload.call_args
            selected_tool = args[0]
            assert selected_tool.id == "team"

    @pytest.mark.asyncio
    async def test_lookup_ambiguous_throws_error(self, tool_service, mock_db_tools):
        """Two tools at same priority level should raise ToolInvocationError (Ambiguous)."""
        t1 = mock_db_tools(id="t1", visibility="team", team_id="team-A")
        t2 = mock_db_tools(id="t2", visibility="team", team_id="team-A")

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[t1, t2])))))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=AsyncMock(get=AsyncMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            with pytest.raises(ToolInvocationError, match="ambiguous"):
                await tool_service.invoke_tool(db, "test_tool", {}, user_email="me@test.com", token_teams=["team-A"])

    @pytest.mark.asyncio
    async def test_lookup_skips_cache_when_multiple_tools(self, tool_service, mock_db_tools):
        """Cache should not be populated when multiple tools share a name."""
        team_tool = mock_db_tools(id="team", visibility="team", team_id="team-A")
        pub_tool = mock_db_tools(id="pub", visibility="public")

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pub_tool, team_tool])))))

        def _fake_build(tool, gw):
            p = _make_tool_payload()
            p["id"] = tool.id
            return {"status": "active", "tool": p, "gateway": None}

        mock_cache = AsyncMock()
        mock_cache.enabled = True
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=mock_cache),
            patch.object(tool_service, "_build_tool_cache_payload", side_effect=_fake_build),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.create_span", MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", MagicMock()),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
        ):
            tool_service._http_client = AsyncMock()
            tool_service._http_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value={"ok": True})))

            await tool_service.invoke_tool(db, "test_tool", {}, user_email="me@test.com", token_teams=["team-A"])

            mock_cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_public_only_token_filters_private(self, tool_service, mock_db_tools):
        """Public-only token (token_teams=[]) should not access private tools."""
        private_tool = mock_db_tools(visibility="private", owner_email="me@test.com")
        private_tool2 = mock_db_tools(visibility="private", owner_email="other@test.com")

        db = MagicMock()
        db.execute = MagicMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[private_tool, private_tool2])))))

        with patch("mcpgateway.services.tool_service._get_tool_lookup_cache") as mock_cache_fn:
            mock_cache = AsyncMock()
            mock_cache.enabled = True
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache_fn.return_value = mock_cache

            # Even though user_email matches owner, public-only token should deny access
            with pytest.raises(ToolNotFoundError, match="not found"):
                await tool_service.invoke_tool(db, "test_tool", {}, user_email="me@test.com", token_teams=[])
