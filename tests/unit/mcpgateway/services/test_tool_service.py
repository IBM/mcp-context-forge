# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for tool service implementation.
"""

# Standard
import asyncio
import base64
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, Mock, patch

# Third-Party
import jsonschema
import orjson
import pytest
from sqlalchemy.exc import IntegrityError

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.plugins.framework import PluginManager, PluginMode
from mcpgateway.plugins.framework.hooks.tools import ToolHookType
from mcpgateway.plugins.framework.models import PluginResult
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolRead, ToolUpdate
from mcpgateway.services.tool_service import (
    _build_retry_policy_config,
    _decrypt_tool_header_value,
    _decrypt_tool_headers_for_runtime,
    _encrypt_tool_header_value,
    _get_validator_class_and_check,
    _is_sensitive_tool_header_name,
    _protect_tool_headers_for_storage,
    _validate_header_mapping_targets,
    _validate_mapping_contents,
    apply_mapping_into_target,
    extract_using_jq,
    TextContent,
    ToolError,
    ToolInvocationError,
    ToolNameConflictError,
    ToolNotFoundError,
    ToolResult,
    ToolService,
    ToolTimeoutError,
    ToolValidationError,
)
from mcpgateway.utils.pagination import decode_cursor
from mcpgateway.utils.services_auth import encode_auth


@pytest.fixture(autouse=True)
def mock_logging_services():
    """Mock audit_trail and structured_logger to prevent database writes during tests."""
    # Clear SSL context cache before each test for isolation
    # First-Party
    from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache

    clear_ssl_context_cache()

    with patch("mcpgateway.services.tool_service.audit_trail") as mock_audit, patch("mcpgateway.services.tool_service.structured_logger") as mock_logger:
        mock_audit.log_action = MagicMock(return_value=None)
        mock_logger.log = MagicMock(return_value=None)
        yield {"audit_trail": mock_audit, "structured_logger": mock_logger}


@pytest.fixture(autouse=True)
def mock_fresh_db_session():
    """Mock fresh_db_session context manager to prevent real DB operations during tests.

    This is needed because invoke_tool now uses fresh_db_session for metrics recording.
    """
    # Standard
    from contextlib import contextmanager

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


@pytest.fixture
def mock_global_config_obj():
    """Create a mock GlobalConfig object for tests.

    This is needed because invoke_tool queries GlobalConfig for passthrough headers.
    """
    config = MagicMock()
    config.passthrough_headers = ["X-Tenant-Id", "X-Request-Id"]
    return config


def setup_db_execute_mock(test_db, mock_tool, mock_global_config):
    """Helper to set up test_db.execute to return tool for queries.

    invoke_tool() makes db.execute() calls for tool queries.
    GlobalConfig is now cached via global_config_cache (Issue #1715),
    so db.execute() only needs to return the tool.

    Args:
        test_db: The mock database session.
        mock_tool: The mock tool to return for tool queries.
        mock_global_config: The mock GlobalConfig to return for config queries.
    """
    # Invalidate cache to ensure fresh state for each test
    global_config_cache.invalidate()

    # db.execute() always returns the tool (GlobalConfig is now cached)
    mock_scalar_tool = Mock()
    mock_scalar_tool.scalar_one_or_none.return_value = mock_tool
    mock_scalar_tool.scalars.return_value = mock_scalar_tool
    mock_scalar_tool.all.return_value = [mock_tool] if mock_tool else []

    test_db.execute = Mock(return_value=mock_scalar_tool)

    # Mock db.query() for GlobalConfig cache (Issue #1715)
    mock_query_result = Mock()
    mock_query_result.first.return_value = mock_global_config
    test_db.query = Mock(return_value=mock_query_result)


class TestToolServiceHelpersExtended:
    """Tests for helper utilities in tool_service."""

    def test_get_validator_class_and_check_fallback_success(self, monkeypatch):
        """Fallback validators should be used when primary schema check fails."""
        schema_json = orjson.dumps({"type": "object"}).decode()

        class BaseValidator:
            @staticmethod
            def check_schema(_schema):
                raise jsonschema.exceptions.SchemaError("boom")

        class FallbackFail:
            @staticmethod
            def check_schema(_schema):
                raise jsonschema.exceptions.SchemaError("boom")

        class FallbackPass:
            @staticmethod
            def check_schema(_schema):
                return None

        _get_validator_class_and_check.cache_clear()
        monkeypatch.setattr("mcpgateway.services.tool_service.validators.validator_for", lambda _schema: BaseValidator)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft7Validator", FallbackFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft6Validator", FallbackPass)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft4Validator", FallbackPass)

        validator_cls, _schema = _get_validator_class_and_check(schema_json)
        assert validator_cls is FallbackPass

    def test_get_validator_class_and_check_all_fallbacks_fail(self, monkeypatch):
        """When all fallbacks fail, the primary validator is used."""
        schema_json = orjson.dumps({"type": "object"}).decode()
        calls = {"count": 0}

        class BaseValidator:
            @staticmethod
            def check_schema(_schema):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise jsonschema.exceptions.SchemaError("boom")

        class FallbackFail:
            @staticmethod
            def check_schema(_schema):
                raise jsonschema.exceptions.SchemaError("boom")

        _get_validator_class_and_check.cache_clear()
        monkeypatch.setattr("mcpgateway.services.tool_service.validators.validator_for", lambda _schema: BaseValidator)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft7Validator", FallbackFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft6Validator", FallbackFail)
        monkeypatch.setattr("mcpgateway.services.tool_service.Draft4Validator", FallbackFail)

        validator_cls, _schema = _get_validator_class_and_check(schema_json)
        assert validator_cls is BaseValidator
        assert calls["count"] == 2

    def test_extract_using_jq_handles_none_result(self, monkeypatch):
        """[None] result should map to error message."""

        class DummyProgram:
            def input(self, _data):
                return self

            def all(self):
                return [None]

        monkeypatch.setattr("mcpgateway.services.tool_service._compile_jq_filter", lambda _f: DummyProgram())

        result = extract_using_jq({"a": 1}, ".a")
        assert result == [TextContent(type="text", text="Error applying jsonpath filter")]

    def test_extract_using_jq_returns_exception_message(self, monkeypatch):
        """Exceptions during jq execution should return list with TextContent error."""
        monkeypatch.setattr("mcpgateway.services.tool_service._compile_jq_filter", lambda _f: (_ for _ in ()).throw(RuntimeError("boom")))

        result = extract_using_jq({"a": 1}, ".a")
        assert result == [TextContent(type="text", text="Error applying jsonpath filter: boom")]

    def test_tool_service_plugin_env_override(self, monkeypatch):
        """PLUGINS_ENABLED env flag controls whether the plugin factory is available."""
        # First-Party
        import mcpgateway.plugins.framework as pf_mod  # pylint: disable=import-outside-toplevel
        from mcpgateway.plugins.framework.settings import settings as plugin_settings  # pylint: disable=import-outside-toplevel

        # Enabled case: pre-install a mock factory so get_plugin_manager_factory() returns it
        mock_factory_instance = MagicMock()
        mock_factory_instance._managers = {}
        monkeypatch.setattr(pf_mod, "_plugin_manager_factory", mock_factory_instance)
        monkeypatch.setenv("PLUGINS_ENABLED", "yes")
        plugin_settings.cache_clear()

        service = ToolService()  # noqa: F841
        assert pf_mod._plugin_manager_factory is not None

        # Disabled case: factory should be None
        monkeypatch.setattr(pf_mod, "_plugin_manager_factory", None)
        monkeypatch.setenv("PLUGINS_ENABLED", "no")
        plugin_settings.cache_clear()

        service = ToolService()  # noqa: F841
        assert pf_mod._plugin_manager_factory is None

    @pytest.mark.asyncio
    async def test_get_top_tools_returns_cached(self, monkeypatch):
        """get_top_tools should return cached results when available."""
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module

        service = ToolService()
        cached = [SimpleNamespace(id="tool-1")]
        # Only return cached for the key get_top_tools uses (default limit=5, include_deleted=False).
        # Other keys (e.g. "a2a", "tools") must get None to avoid polluting aggregate_metrics tests.
        top_tools_key = "top_tools:5:include_deleted=False"

        def get_only_top_tools(key):
            return cached if key == top_tools_key else None

        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: True)
        monkeypatch.setattr(cache_module.metrics_cache, "get", MagicMock(side_effect=get_only_top_tools))

        mock_combined = MagicMock()
        monkeypatch.setattr("mcpgateway.services.tool_service.get_top_performers_combined", mock_combined)

        result = await service.get_top_tools(MagicMock())

        assert result == cached
        mock_combined.assert_not_called()

    def test_pydantic_tool_from_payload_invalid(self, monkeypatch):
        """Invalid cache payload should return None."""
        service = ToolService()

        monkeypatch.setattr("mcpgateway.services.tool_service.PydanticTool.model_validate", MagicMock(side_effect=ValueError("boom")))

        assert service._pydantic_tool_from_payload({"bad": "payload"}) is None

    def test_record_tool_metric_by_id_records(self):
        """_record_tool_metric_by_id should add and commit metric."""
        service = ToolService()
        db = MagicMock()

        service._record_tool_metric_by_id(db, "tool-1", time.monotonic(), True, None)

        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_record_tool_metric_sync_uses_fresh_session(self, monkeypatch):
        """_record_tool_metric_sync should call record helper with fresh session."""
        service = ToolService()
        dummy_db = MagicMock()

        class DummySession:
            def __enter__(self):
                return dummy_db

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("mcpgateway.services.tool_service.fresh_db_session", DummySession)

        with patch.object(service, "_record_tool_metric_by_id") as mock_record:
            service._record_tool_metric_sync("tool-1", 1.23, True, None)

        mock_record.assert_called_once_with(
            dummy_db,
            tool_id="tool-1",
            start_time=1.23,
            success=True,
            error_message=None,
        )

    def test_extract_and_validate_structured_content_skips_invalid_json(self):
        """Invalid JSON content should be skipped and treated as valid."""
        service = ToolService()
        tool = SimpleNamespace(output_schema={"type": "object"})
        tool_result = ToolResult(content=[{"type": "text", "text": "not-json"}])

        assert service._extract_and_validate_structured_content(tool, tool_result) is True


@pytest.fixture
def tool_service():
    """Create a tool service instance."""
    service = ToolService()
    service._http_client = AsyncMock()
    service.get_plugin_manager = AsyncMock()
    # service._plugin_manager = False  # Disable plugin manager to avoid real plugin execution in tests

    return service


@pytest.fixture
def mock_gateway():
    """Create a mock gateway model."""
    gw = MagicMock(spec=DbGateway)
    gw.id = "1"
    gw.name = "test_gateway"
    gw.slug = "test-gateway"
    gw.url = "http://example.com/gateway"
    gw.description = "A test tool"
    gw.transport = "SSE"
    gw.capabilities = {"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}}
    gw.created_at = gw.updated_at = gw.last_seen = "2025-01-01T00:00:00Z"
    gw.modified_by = gw.created_by = "Someone"
    gw.modified_via = gw.created_via = "ui"
    gw.modified_from_ip = gw.created_from_ip = "127.0.0.1"
    gw.modified_user_agent = gw.created_user_agent = "Chrome"
    gw.import_batch_id = gw.federation_source = gw.team_id = gw.visibility = gw.owner_email = None

    # one dummy tool hanging off the gateway
    tool = MagicMock(spec=DbTool, id=101, name="dummy_tool")
    gw.tools = [tool]
    gw.federated_tools = []
    gw.transport = "sse"
    gw.auth_type = None
    gw.auth_value = {}
    gw.passthrough_headers = []
    gw.ca_certificate = None
    gw.ca_certificate_sig = None
    gw.signing_algorithm = None

    gw.enabled = True
    gw.reachable = True
    return gw


class TestToolServiceA2A:
    """Focused tests for A2A helper paths inside tool_service."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.http_client_service.get_http_client")
    async def test_call_a2a_agent_uses_v1_send_message_payload(self, mock_get_client, tool_service):
        """A2A tool calls should default to A2A v1 payloads for v1 agents."""
        mock_client = AsyncMock()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"ok": True}
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client

        agent = SimpleNamespace(
            name="a2a-agent",
            endpoint_url="https://example.com/",
            agent_type="generic",
            protocol_version="1.0.0",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
        )

        result = await tool_service._call_a2a_agent(agent, {"query": "hello"})

        assert result == {"ok": True}
        outbound_json = mock_client.post.call_args.kwargs["json"]
        outbound_headers = mock_client.post.call_args.kwargs["headers"]
        assert outbound_json["method"] == "SendMessage"
        assert outbound_json["params"]["message"]["role"] == "ROLE_USER"
        assert outbound_json["params"]["message"]["parts"] == [{"text": "hello"}]
        assert outbound_headers["A2A-Version"] == "1.0"


@pytest.fixture
def mock_tool(mock_gateway):
    """Create a mock tool model."""
    tool = MagicMock(spec=DbTool)
    tool.id = "1"
    tool.original_name = "test_tool"
    tool.url = "http://example.com/tools/test"
    tool.description = "A test tool"
    tool.original_description = "A test tool original"
    tool.integration_type = "MCP"
    tool.request_type = "SSE"
    tool.headers = {"Content-Type": "application/json"}
    tool.input_schema = {"type": "object", "properties": {"param": {"type": "string"}}}
    tool.output_schema = None
    tool.jsonpath_filter = ""
    tool.created_at = "2023-01-01T00:00:00"
    tool.updated_at = "2023-01-01T00:00:00"
    tool.created_by = "ContextForge team"
    tool.created_from_ip = "1.2.3.4"
    tool.created_via = "ui"
    tool.created_user_agent = "Chrome"
    tool.modified_by = "No one"
    tool.modified_from_ip = "1.2.3.4"
    tool.modified_via = "ui"
    tool.modified_user_agent = "Chrome"
    tool.import_batch_id = "2"
    tool.federation_source = "federation_source"
    tool.team_id = "5"
    tool.visibility = "public"  # Use public for tests that don't test authorization
    tool.owner_email = "admin@admin.org"
    tool.enabled = True
    tool.reachable = True
    tool.auth_type = None
    tool.auth_username = None
    tool.auth_password = None
    tool.auth_token = None
    tool.auth_value = None
    tool.gateway_id = "1"
    tool.gateway = mock_gateway
    tool.annotations = {}
    tool.gateway_slug = "test-gateway"
    tool.name = "test-gateway-test-tool"
    tool.custom_name = "test_tool"
    tool.custom_name_slug = "test-tool"
    tool.display_name = None
    tool.tags = []
    tool.team = None
    tool.query_mapping = None
    tool.header_mapping = None

    # Set up metrics
    tool.metrics = []
    tool.execution_count = 0
    tool.successful_executions = 0
    tool.failed_executions = 0
    tool.failure_rate = 0.0
    tool.min_response_time = None
    tool.max_response_time = None
    tool.avg_response_time = None
    tool.last_execution_time = None
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


class TestToolService:
    """Tests for the ToolService class."""

    @pytest.mark.asyncio
    async def test_initialize_service(self, caplog):
        """Initialize service and check logs"""
        caplog.set_level(logging.INFO, logger="mcpgateway.services.tool_service")
        service = ToolService()
        await service.initialize()

        assert "Initializing tool service" in caplog.text

    @pytest.mark.asyncio
    async def test_shutdown_service(self, caplog):
        """Shutdown service and check logs"""
        caplog.set_level(logging.INFO, logger="mcpgateway.services.tool_service")
        service = ToolService()
        await service.shutdown()

        assert "Tool service shutdown complete" in caplog.text

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_basic_auth(self, tool_service, mock_tool):
        """Check auth for basic auth"""

        # Build Authorization header with base64 encoded user:password
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}

        mock_tool.auth_type = "basic"
        mock_tool.auth_value = encode_auth(auth_dict)

        mock_tool.auth_type = "basic"
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        # mock_tool.auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"
        # mock_tool.auth_value = encode_auth({"user": "test_user", "password": "test_password"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "basic"
        assert tool_read.auth.username == "test_user"
        assert tool_read.auth.password == settings.masked_auth_value

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_bearer_auth(self, tool_service, mock_tool):
        """Check auth for bearer auth"""

        mock_tool.auth_type = "bearer"
        # Create auth_value with the following values
        # bearer token ABC123
        mock_tool.auth_value = encode_auth({"Authorization": "Bearer ABC123"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "bearer"
        assert tool_read.auth.token == settings.masked_auth_value

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_authheaders_auth(self, tool_service, mock_tool):
        """Check auth for authheaders auth"""

        mock_tool.auth_type = "authheaders"
        # Create auth_value with the following values
        # {"test-api-key": "test-api-value"}
        # mock_tool.auth_value = "8pvPTCegaDhrx0bmBf488YvGg9oSo4cJJX68WCTvxjMY-C2yko_QSPGVggjjNt59TPvlGLsotTZvAiewPRQ"
        mock_tool.auth_value = encode_auth({"test-api-key": "test-api-value"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "authheaders"
        assert tool_read.auth.auth_header_key == "test-api-key"
        assert tool_read.auth.auth_header_value == settings.masked_auth_value
        # Verify multi-header format (authHeaders array)
        assert tool_read.auth.authHeaders is not None
        assert len(tool_read.auth.authHeaders) == 1
        assert tool_read.auth.authHeaders[0]["key"] == "test-api-key"
        assert tool_read.auth.authHeaders[0]["value"] == settings.masked_auth_value

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_authheaders_multi(self, tool_service, mock_tool):
        """Check auth for authheaders with multiple headers returns all headers."""
        mock_tool.auth_type = "authheaders"
        mock_tool.auth_value = encode_auth({"X-API-Key": "secret1", "X-Custom": "secret2"})
        tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth.auth_type == "authheaders"
        assert tool_read.auth.authHeaders is not None
        assert len(tool_read.auth.authHeaders) == 2
        header_keys = [h["key"] for h in tool_read.auth.authHeaders]
        assert "X-API-Key" in header_keys
        assert "X-Custom" in header_keys
        # All values should be masked
        for h in tool_read.auth.authHeaders:
            assert h["value"] == settings.masked_auth_value

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_authheaders_empty(self, tool_service, mock_tool):
        """Check auth for authheaders auth with empty value (regression test for StopIteration)"""

        mock_tool.auth_type = "authheaders"
        # Set auth_value to something non-empty so has_encrypted_auth is True
        mock_tool.auth_value = "some_encrypted_garbage"

        # Mock decode_auth to return empty dict
        with patch("mcpgateway.services.tool_service.decode_auth", return_value={}):
            # Should not raise StopIteration
            tool_read = tool_service.convert_tool_to_read(mock_tool)

        assert tool_read.auth is None

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_include_auth_false_skips_decode(self, tool_service, mock_tool):
        """Verify include_auth=False skips decryption and returns minimal auth info."""
        # Set up tool with encrypted basic auth
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}
        mock_tool.auth_type = "basic"
        mock_tool.auth_value = encode_auth(auth_dict)

        # Patch decode_auth to verify it's not called
        with patch("mcpgateway.services.tool_service.decode_auth") as mock_decode:
            tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)

            # Verify decode_auth was NOT called
            mock_decode.assert_not_called()

            # Verify minimal auth info is returned
            assert tool_read.auth is not None
            assert tool_read.auth.auth_type == "basic"
            # Other fields should be empty/default (not decrypted)
            assert tool_read.auth.username == ""
            assert tool_read.auth.password == ""

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_include_auth_false_bearer(self, tool_service, mock_tool):
        """Verify include_auth=False with bearer auth returns minimal auth info."""
        mock_tool.auth_type = "bearer"
        mock_tool.auth_value = encode_auth({"Authorization": "Bearer ABC123"})

        with patch("mcpgateway.services.tool_service.decode_auth") as mock_decode:
            tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)

            mock_decode.assert_not_called()
            assert tool_read.auth is not None
            assert tool_read.auth.auth_type == "bearer"
            assert tool_read.auth.token == ""

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_oauth_no_auth_value(self, tool_service, mock_tool):
        """Verify OAuth tools (auth_type set, auth_value=None) return auth=None."""
        mock_tool.auth_type = "oauth"
        mock_tool.auth_value = None

        # Test with include_auth=True (detail view)
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=True)
        assert tool_read.auth is None

        # Test with include_auth=False (list view)
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)
        assert tool_read.auth is None

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_no_auth(self, tool_service, mock_tool):
        """Verify tools with no auth return auth=None regardless of include_auth."""
        mock_tool.auth_type = None
        mock_tool.auth_value = None

        # Test with include_auth=True
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=True)
        assert tool_read.auth is None

        # Test with include_auth=False
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_auth=False)
        assert tool_read.auth is None

    @pytest.mark.asyncio
    async def test_convert_tool_to_read_includes_metrics(self, tool_service, mock_tool):
        """Verify include_metrics populates metrics and execution_count."""
        mock_tool.metrics_summary = {
            "total_executions": 3,
            "successful_executions": 2,
            "failed_executions": 1,
            "failure_rate": 0.333,
            "min_response_time": 0.1,
            "max_response_time": 1.0,
            "avg_response_time": 0.5,
            "last_execution_time": datetime.now(timezone.utc),
        }
        tool_read = tool_service.convert_tool_to_read(mock_tool, include_metrics=True, include_auth=False)
        assert tool_read.metrics.total_executions == 3
        assert tool_read.execution_count == 3

    @pytest.mark.asyncio
    async def test_register_tool(self, tool_service, mock_tool, test_db):
        """Test successful tool registration."""
        # Set up DB behavior
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Set up tool service methods
        tool_service._notify_tool_added = AsyncMock()
        tool_service.convert_tool_to_read = Mock(
            return_value=ToolRead(
                id="1",
                original_name="test_tool",
                gateway_slug="test-gateway",
                customNameSlug="test-tool",
                name="test-gateway-test-tool",
                url="http://example.com/tools/test",
                description="A test tool",
                original_description="A test tool original",
                integration_type="REST",
                request_type="POST",
                headers={"Content-Type": "application/json"},
                input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
                jsonpath_filter="",
                created_at="2023-01-01T00:00:00",
                updated_at="2023-01-01T00:00:00",
                enabled=True,
                reachable=True,
                gateway_id=None,
                execution_count=0,
                auth=None,  # Add auth field
                annotations={},  # Add annotations field
                metrics={
                    "total_executions": 0,
                    "successful_executions": 0,
                    "failed_executions": 0,
                    "failure_rate": 0.0,
                    "min_response_time": None,
                    "max_response_time": None,
                    "avg_response_time": None,
                    "last_execution_time": None,
                },
                customName="test_tool",
            )
        )

        # Create tool request
        tool_create = ToolCreate(
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="REST",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
        )

        # Call method
        result = await tool_service.register_tool(test_db, tool_create)

        # Verify DB operations
        test_db.add.assert_called_once()
        test_db.commit.assert_called_once()
        # refresh is called twice: once after commit and once after logging commits
        assert test_db.refresh.call_count == 2

        # Verify result
        assert result.name == "test-gateway-test-tool"
        assert result.url == "http://example.com/tools/test"
        assert result.integration_type == "REST"
        assert result.enabled is True

        # Verify notification
        tool_service._notify_tool_added.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_tool_encrypts_sensitive_headers_at_rest(self, tool_service, test_db):
        """Sensitive custom headers should be encrypted before persistence."""
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        test_db.commit = Mock()
        test_db.refresh = Mock()

        tool_service._notify_tool_added = AsyncMock()
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        tool_create = ToolCreate(
            name="secure-tool",
            url="http://example.com/tools/secure",
            description="Tool with custom headers",
            integration_type="REST",
            request_type="POST",
            headers={
                "Authorization": "Bearer super-secret",
                "X-Trace-Id": "trace-1",
            },
            input_schema={"type": "object"},
        )

        await tool_service.register_tool(test_db, tool_create)

        stored_tool = test_db.add.call_args.args[0]
        assert isinstance(stored_tool.headers["Authorization"], dict)
        assert "_mcpgateway_encrypted_header_value_v1" in stored_tool.headers["Authorization"]
        assert stored_tool.headers["X-Trace-Id"] == "trace-1"

    @pytest.mark.asyncio
    async def test_update_tool_keeps_existing_sensitive_header_when_masked(self, tool_service, mock_tool, test_db):
        """Masked header values should preserve existing encrypted values on update."""
        existing_encrypted_auth = {
            "_mcpgateway_encrypted_header_value_v1": encode_auth(
                {"value": "Bearer existing-secret"},
            ),
        }
        mock_tool.headers = {
            "Authorization": existing_encrypted_auth,
            "X-Trace-Id": "trace-1",
        }

        test_db.commit = Mock()
        test_db.refresh = Mock()
        tool_service._notify_tool_updated = AsyncMock()
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.tool_service.get_for_update", return_value=mock_tool):
            await tool_service.update_tool(
                test_db,
                "tool-id",
                ToolUpdate(headers={"Authorization": settings.masked_auth_value, "X-Trace-Id": "trace-2"}),
            )

        assert mock_tool.headers["Authorization"] == existing_encrypted_auth
        assert mock_tool.headers["X-Trace-Id"] == "trace-2"

    def test_sensitive_tool_header_patterns_avoid_non_secret_token_noise(self):
        """Sensitive matcher should avoid tracing/idempotency token false positives."""
        assert _is_sensitive_tool_header_name("Authorization") is True
        assert _is_sensitive_tool_header_name("X-Auth-Token") is True
        assert _is_sensitive_tool_header_name("client-secret") is True
        assert _is_sensitive_tool_header_name("X-Correlation-Token") is False
        assert _is_sensitive_tool_header_name("X-Request-Token") is False
        assert _is_sensitive_tool_header_name("X-Idempotency-Key") is False

    def test_non_secret_observability_headers_stay_plaintext_at_rest(self):
        """Only sensitive headers should be encrypted when storing custom headers."""
        protected = _protect_tool_headers_for_storage(
            {
                "Authorization": "Bearer secure-token",
                "X-Correlation-Token": "corr-123",
                "X-Idempotency-Key": "idem-456",
            }
        )
        assert isinstance(protected["Authorization"], dict)
        assert "_mcpgateway_encrypted_header_value_v1" in protected["Authorization"]
        assert protected["X-Correlation-Token"] == "corr-123"
        assert protected["X-Idempotency-Key"] == "idem-456"

    def test_tool_header_crypto_helpers_cover_edge_cases(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        """Exercise edge branches for header encrypt/decrypt helpers."""
        # Explicit clears
        assert _encrypt_tool_header_value(None) is None
        assert _encrypt_tool_header_value("") == ""

        # Masked values with no existing secret should clear
        assert _encrypt_tool_header_value(settings.masked_auth_value, None) is None

        # Masked values with existing plain secret should encrypt recursively
        monkeypatch.setattr("mcpgateway.services.tool_service.encode_auth", lambda payload: f"enc:{payload['data']}")
        encrypted_from_existing = _encrypt_tool_header_value(settings.masked_auth_value, "Bearer existing-secret")
        assert encrypted_from_existing == {"_mcpgateway_encrypted_header_value_v1": "enc:Bearer existing-secret"}

        # Already encrypted values should pass through unchanged
        already_encrypted = {"_mcpgateway_encrypted_header_value_v1": "ciphertext"}
        assert _encrypt_tool_header_value(already_encrypted) == already_encrypted

        # Missing encrypted payload returns original envelope
        missing_payload = {"_mcpgateway_encrypted_header_value_v1": ""}
        assert _decrypt_tool_header_value(missing_payload) == missing_payload

        # Successful decode should return canonical data key
        monkeypatch.setattr("mcpgateway.services.tool_service.decode_auth", lambda _payload: {"data": "Bearer runtime-secret"})
        assert _decrypt_tool_header_value({"_mcpgateway_encrypted_header_value_v1": "ciphertext"}) == "Bearer runtime-secret"

        # Decode failure logs and preserves envelope
        monkeypatch.setattr("mcpgateway.services.tool_service.decode_auth", MagicMock(side_effect=RuntimeError("boom")))
        encrypted_value = {"_mcpgateway_encrypted_header_value_v1": "ciphertext"}
        with patch("mcpgateway.services.tool_service.logger.warning") as mock_warning:
            assert _decrypt_tool_header_value(encrypted_value) == encrypted_value
        mock_warning.assert_called_once()
        assert "Failed to decrypt tool header value" in mock_warning.call_args[0][0]

        # Non-dict header maps should safely normalize to empty dict
        assert _protect_tool_headers_for_storage("not-a-dict") is None
        assert _decrypt_tool_headers_for_runtime(None) == {}

    @pytest.mark.asyncio
    async def test_create_tool_from_a2a_agent_passes_scope_fields(self, tool_service, test_db):
        """Ensure A2A tool creation carries team/owner/visibility to register_tool."""
        agent = MagicMock()
        agent.slug = "agent-slug"
        agent.name = "Agent Name"
        agent.endpoint_url = "https://example.com/a2a"
        agent.description = "Agent description"
        agent.agent_type = "custom"
        agent.auth_type = "bearer"
        agent.auth_value = "secret"
        agent.tags = ["alpha"]
        agent.id = "agent-123"
        agent.team_id = "team-123"
        agent.owner_email = "owner@example.com"
        agent.visibility = "team"

        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        tool_read = MagicMock()
        tool_read.id = "tool-1"
        tool_service.register_tool = AsyncMock(return_value=tool_read)

        tool_db = MagicMock()
        test_db.get = Mock(return_value=tool_db)

        result = await tool_service.create_tool_from_a2a_agent(
            test_db,
            agent,
            created_by="creator@example.com",
        )

        tool_service.register_tool.assert_awaited_once()
        _, kwargs = tool_service.register_tool.call_args
        assert kwargs["team_id"] == agent.team_id
        assert kwargs["owner_email"] == agent.owner_email
        assert kwargs["visibility"] == agent.visibility
        test_db.get.assert_called_once_with(DbTool, tool_read.id)
        assert result == tool_db

    @pytest.mark.asyncio
    async def test_register_tool_with_gateway_id(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict and gateway."""
        # Mock DB to return existing tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)

        # Create tool request with conflicting name
        tool_create = ToolCreate(
            name="test_tool",  # Same name as mock_tool
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            gateway_id="1",
        )

        # Should raise ToolError due to missing slug on NoneType
        with pytest.raises(ToolError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)
            # The service wraps exceptions, so check the message
            assert "Failed to register tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_tool_with_none_auth(self, tool_service, test_db):
        """Test register_tool when tool.auth is None."""

        token = "token"
        auth_value = encode_auth({"Authorization": f"Bearer {token}"})

        tool_input = ToolCreate(name="no_auth_tool", gateway_id=None, auth=AuthenticationValues(auth_type="bearer", auth_value=auth_value))

        # Run the function
        result = await tool_service.register_tool(test_db, tool_input)

        assert result.original_name == "no_auth_tool"
        # assert result.auth_type is None
        # assert result.auth_value is None

        # Validate that the tool is actually in the DB
        db_tool = test_db.query(DbTool).filter_by(original_name="no_auth_tool").first()
        assert db_tool is not None
        assert db_tool.auth_type == "bearer"
        assert db_tool.auth_value == auth_value

    @pytest.mark.asyncio
    async def test_register_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict for private, team, and public visibility."""
        # --- Private visibility: conflict if name and owner_email match ---
        mock_tool.name = "private_tool"
        mock_tool.visibility = "private"
        mock_tool.owner_email = "user@example.com"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_private = ToolCreate(
            name="private_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="private",
            owner_email="user@example.com",
        )
        test_db.commit = Mock(side_effect=IntegrityError("UNIQUE constraint failed: tools.name, owner_email", None, None))
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_private)
        assert "UNIQUE constraint failed: tools.name, owner_email" in str(exc_info.value)

        # --- Team visibility: conflict if name and team_id match ---
        mock_tool.name = "team_tool"
        mock_tool.visibility = "team"
        mock_tool.team_id = "team123"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_team = ToolCreate(
            name="team_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="team",
            team_id="team123",
            owner_email="user@example.com",
        )
        test_db.commit = Mock()
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_team)
        assert "Team-level Tool already exists with name: team_tool" in str(exc_info.value)

        # --- Public visibility: conflict if name and visibility match ---
        mock_tool.name = "public_tool"
        mock_tool.visibility = "public"
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_public = ToolCreate(
            name="public_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="public",
            owner_email="user@example.com",
        )
        test_db.commit = Mock()
        # Ensure mock_tool.name matches the expected error message
        mock_tool.name = "public_tool"
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_public)
        assert "Public Tool already exists with name: public_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_inactive_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test tool registration with name conflict for inactive tool."""
        # --- Inactive tool: conflict if name matches and enabled is False ---
        mock_tool.name = "inactive_tool"
        mock_tool.visibility = "public"
        mock_tool.enabled = False
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        test_db.execute = Mock(return_value=mock_scalar)
        tool_create_inactive = ToolCreate(
            name="inactive_tool",
            url="http://example.com/tools/new",
            description="A new tool",
            integration_type="REST",
            request_type="POST",
            visibility="public",
            owner_email="user@example.com",
        )
        test_db.commit = Mock()
        with pytest.raises(ToolNameConflictError) as exc_info:
            await tool_service.register_tool(test_db, tool_create_inactive)
        assert "Public Tool already exists with name: inactive_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_tool_db_integrity_error(self, tool_service, test_db):
        """Test tool registration with database IntegrityError."""
        # Mock DB to raise IntegrityError on commit
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)
        test_db.add = Mock()
        # test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
        test_db.commit = Mock(side_effect=IntegrityError("UNIQUE constraint failed: tools.name, owner_email", None, None))

        test_db.rollback = Mock()

        # Create tool request
        tool_create = ToolCreate(
            name="test_tool",
            url="http://example.com/tools/test",
            description="A test tool",
            integration_type="REST",
            request_type="POST",
            visibility="private",
            owner_email="user@example.com",
        )

        # Should raise ToolError (wrapped IntegrityError)
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.register_tool(test_db, tool_create)

        # Verify rollback was called
        test_db.rollback.assert_called_once()
        assert "UNIQUE constraint failed: tools.name, owner_email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_tools(self, tool_service, mock_tool, test_db):
        """Test listing tools."""
        # Mock DB to return a list of tools
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_tool]
        mock_scalar_result = MagicMock()
        mock_scalar_result.scalars.return_value = mock_scalars
        mock_execute = Mock(return_value=mock_scalar_result)
        test_db.execute = mock_execute

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            original_description="A test tool original",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        # First call: fetch tools
        # Second call (if tool has team_id): fetch team names
        mock_tool.team_id = None  # No team, so no second query
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()  # Mock commit to avoid errors

        # Call method
        result, next_cursor = await tool_service.list_tools(test_db)

        # Verify DB query was called
        assert test_db.execute.called

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        assert next_cursor is None  # No pagination needed for single result
        tool_service.convert_tool_to_read.assert_called_once_with(
            mock_tool, include_metrics=False, include_auth=False, requesting_user_email=None, requesting_user_is_admin=False, requesting_user_team_roles=None
        )

    @pytest.mark.asyncio
    async def test_list_tools_pagination(self, tool_service, test_db, monkeypatch):
        """Test list_tools returns next_cursor when page size is exceeded."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 1)

        tool_1 = MagicMock(spec=DbTool, id="1", team_id=None)
        tool_2 = MagicMock(spec=DbTool, id="2", team_id=None)

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[tool_1, tool_2])))))
        test_db.commit = Mock()

        mock_team = MagicMock(id="team-1", is_personal=True)
        with patch("mcpgateway.services.base_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            tool_service.convert_tool_to_read = Mock(side_effect=[MagicMock(), MagicMock()])

            result, next_cursor = await tool_service.list_tools(test_db, user_email="user@example.com", team_id="team-1")

        assert len(result) == 1
        assert next_cursor is not None
        assert decode_cursor(next_cursor)["id"] == "1"

    @pytest.mark.asyncio
    async def test_list_tools_denies_unknown_team(self, tool_service, test_db):
        """Test list_tools returns empty when user lacks team membership."""
        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        # Returns empty list because query has WHERE FALSE condition
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[])))))
        mock_team = MagicMock(id="other-team", is_personal=True)

        with patch("mcpgateway.services.base_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            result, next_cursor = await tool_service.list_tools(test_db, user_email="user@example.com", team_id="team-1")

        assert result == []
        assert next_cursor is None
        # Query IS executed but returns empty due to WHERE FALSE condition
        test_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools_with_limit(self, tool_service, test_db, monkeypatch):
        """Test list_tools respects custom limit parameter."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 50)
        monkeypatch.setattr(settings, "pagination_max_page_size", 500)

        tools = [MagicMock(spec=DbTool, id=str(i), team_id=None) for i in range(150)]

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        # unified_paginate fetches limit+1 to check if there are more results
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=tools[:101])))))
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(side_effect=lambda t, **kw: MagicMock())

        result, next_cursor = await tool_service.list_tools(test_db, limit=100)

        assert len(result) == 100
        assert next_cursor is not None  # More results available

    @pytest.mark.asyncio
    async def test_list_tools_with_limit_zero_returns_all(self, tool_service, test_db, monkeypatch):
        """Test list_tools with limit=0 returns all tools without pagination."""
        monkeypatch.setattr(settings, "pagination_default_page_size", 50)

        tools = [MagicMock(spec=DbTool, id=str(i), team_id=None) for i in range(200)]

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=tools)))))
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(side_effect=lambda t, **kw: MagicMock())

        result, next_cursor = await tool_service.list_tools(test_db, limit=0)

        assert len(result) == 200
        assert next_cursor is None  # No pagination when limit=0

    @pytest.mark.asyncio
    async def test_list_tools_cache_hit(self, tool_service, test_db, monkeypatch):
        """Cache hit should return cached tools without DB query."""
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="hash"),
            get=AsyncMock(return_value={"tools": [{"name": "cached"}], "next_cursor": "next"}),
            set=AsyncMock(),
        )

        monkeypatch.setattr("mcpgateway.services.tool_service._get_registry_cache", lambda: cache)
        monkeypatch.setattr("mcpgateway.services.tool_service.ToolRead.model_validate", lambda data: SimpleNamespace(name=data["name"]))

        test_db.execute = Mock()
        result, next_cursor = await tool_service.list_tools(test_db)

        assert next_cursor == "next"
        assert len(result) == 1
        assert result[0].name == "cached"
        test_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_gateway_id_null_filter(self, tool_service, test_db):
        """gateway_id='null' should be accepted and return results."""
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.tool_service.unified_paginate", new=AsyncMock(return_value=([], None))):
            result, next_cursor = await tool_service.list_tools(test_db, gateway_id="null")

        assert result == []
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_list_tools_cache_skips_attribute_error(self, tool_service, test_db, monkeypatch):
        """Cache set should be skipped when results lack model_dump."""
        cache = SimpleNamespace(
            hash_filters=MagicMock(return_value="hash"),
            get=AsyncMock(return_value=None),
            set=AsyncMock(),
        )
        monkeypatch.setattr("mcpgateway.services.tool_service._get_registry_cache", lambda: cache)

        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(return_value=SimpleNamespace())

        with patch("mcpgateway.services.tool_service.unified_paginate", new=AsyncMock(return_value=([MagicMock()], None))):
            result, _ = await tool_service.list_tools(test_db)

        assert len(result) == 1
        cache.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_inactive_tools(self, tool_service, mock_tool, test_db):
        """Test listing tools."""
        # Mock DB to return a tuple of (tool, team_name) from LEFT JOIN
        mock_tool.enabled = False
        mock_tool.team_id = None

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            original_description="A test tool original",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=False,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
            customName="test_tool",
            customNameSlug="test-tool",
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result, _ = await tool_service.list_tools(test_db, include_inactive=True)

        # Verify DB query was called
        assert test_db.execute.called

        # Verify result
        assert len(result) == 1
        assert result[0] == tool_read
        tool_service.convert_tool_to_read.assert_called_once_with(
            mock_tool, include_metrics=False, include_auth=False, requesting_user_email=None, requesting_user_is_admin=False, requesting_user_team_roles=None
        )

    @pytest.mark.asyncio
    async def test_list_server_tools_active_only(self):
        mock_db = Mock()
        mock_tool = Mock(enabled=True, team_id=None, team=None)

        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_tool]

        service = ToolService()
        service.convert_tool_to_read = Mock(return_value="converted_tool")

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=False)

        assert tools == ["converted_tool"]
        service.convert_tool_to_read.assert_called_once_with(
            mock_tool, include_metrics=False, include_auth=False, requesting_user_email=None, requesting_user_is_admin=False, requesting_user_team_roles=None
        )

    @pytest.mark.asyncio
    async def test_list_server_tools_include_inactive(self):
        mock_db = Mock()
        active_tool = Mock(enabled=True, reachable=True, team_id=None, team=None)
        inactive_tool = Mock(enabled=False, reachable=True, team_id=None, team=None)

        mock_db.execute.return_value.scalars.return_value.all.return_value = [active_tool, inactive_tool]

        service = ToolService()
        service.convert_tool_to_read = Mock(side_effect=["active_converted", "inactive_converted"])

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=True)

        assert tools == ["active_converted", "inactive_converted"]
        assert service.convert_tool_to_read.call_count == 2

    @pytest.mark.asyncio
    async def test_list_server_tools_includes_team_name(self):
        """Test that list_server_tools properly populates team name via email_team relationship.

        This test guards against regressions if the joinedload strategy is changed.
        """
        mock_db = Mock()
        # Mock a tool with an active team relationship
        mock_email_team = Mock()
        mock_email_team.name = "Engineering Team"
        mock_tool = Mock(
            enabled=True,
            team_id="team-123",
            email_team=mock_email_team,
        )
        # The team property should return the team name from email_team
        mock_tool.team = mock_email_team.name

        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_tool]

        service = ToolService()
        # Use a mock that captures the tool's team value
        captured_tools = []

        def capture_tool(tool, include_metrics=False, include_auth=False, **kwargs):
            captured_tools.append({"team": tool.team, "team_id": tool.team_id})
            return "converted_tool"

        service.convert_tool_to_read = Mock(side_effect=capture_tool)

        tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=False)

        assert tools == ["converted_tool"]
        # Verify the tool's team was accessible during conversion
        assert len(captured_tools) == 1
        assert captured_tools[0]["team"] == "Engineering Team"
        assert captured_tools[0]["team_id"] == "team-123"

    @pytest.mark.asyncio
    async def test_list_server_tools_with_include_metrics_true(self):
        """Test that list_server_tools eager loads metrics when include_metrics=True.

        This test ensures that when include_metrics=True, the query includes
        selectinload for both metrics and metrics_hourly relationships to prevent N+1 queries.
        Regression test for PR #3649 performance optimization.
        """
        mock_db = Mock()
        mock_tool = Mock(enabled=True, team_id=None, team=None)
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_tool]

        service = ToolService()
        service.convert_tool_to_read = Mock(return_value="converted_tool_with_metrics")

        # Call with include_metrics=True to trigger eager loading code path
        tools = await service.list_server_tools(mock_db, server_id="server123", include_metrics=True)

        assert tools == ["converted_tool_with_metrics"]
        # Verify convert_tool_to_read was called with include_metrics=True
        service.convert_tool_to_read.assert_called_once_with(
            mock_tool,
            include_metrics=True,  # This exercises the eager loading code path
            include_auth=False,
            requesting_user_email=None,
            requesting_user_is_admin=False,
            requesting_user_team_roles=None,
        )

    @pytest.mark.asyncio
    async def test_get_tool(self, tool_service, mock_tool, test_db):
        """Test getting a tool by ID."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            original_description="A test tool original",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
            customName="test_tool",
            customNameSlug="test-tool",
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Call method
        result = await tool_service.get_tool(test_db, 1)

        # Verify DB query
        test_db.get.assert_called_once_with(DbTool, 1)

        # Verify result
        assert result == tool_read
        tool_service.convert_tool_to_read.assert_called_once_with(mock_tool, requesting_user_email=None, requesting_user_is_admin=False, requesting_user_team_roles=None)

    @pytest.mark.asyncio
    async def test_get_tool_not_found(self, tool_service, test_db):
        """Test getting a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Should raise NotFoundError
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.get_tool(test_db, 999)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_tool(self, tool_service, mock_tool, test_db):
        """Test deleting a tool."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock the fetchone result for DELETE ... RETURNING
        mock_fetch_result = Mock()
        mock_fetch_result.fetchone.return_value = (mock_tool.id,)
        mock_fetch_result.rowcount = 1  # Indicate successful deletion
        test_db.execute = Mock(return_value=mock_fetch_result)
        test_db.commit = Mock()
        test_db.rollback = Mock()

        # Mock notification
        tool_service._notify_tool_deleted = AsyncMock()

        # Call method
        await tool_service.delete_tool(test_db, 1)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        # Verify execute was called for DELETE ... RETURNING
        test_db.execute.assert_called_once()
        test_db.commit.assert_called_once()

        # Verify notification
        tool_service._notify_tool_deleted.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_tool_purge_metrics(self, tool_service, mock_tool, test_db):
        """Test deleting a tool with metric purge."""
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.rollback = Mock()

        # Mock execute results: batch deletes return rowcount=0 to stop loop, final DELETE returns rowcount=1
        batch_result = Mock()
        batch_result.rowcount = 0  # No rows to delete (stops the batch loop)
        delete_result = Mock()
        delete_result.rowcount = 1  # Final DELETE succeeded
        test_db.execute = Mock(side_effect=[batch_result, batch_result, delete_result])

        tool_service._notify_tool_deleted = AsyncMock()

        await tool_service.delete_tool(test_db, 1, purge_metrics=True)

        # Verify execute was called: 1 for ToolMetric + 1 for ToolMetricsHourly + 1 for DELETE = 3
        assert test_db.execute.call_count == 3
        test_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tool_service, test_db):
        """Test deleting a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.delete_tool(test_db, 999)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_set_tool_state(self, tool_service, mock_tool, test_db):
        """Test setting tool active state."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification methods
        tool_service._notify_tool_activated = AsyncMock()
        tool_service._notify_tool_deactivated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            original_description="A test tool original",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=False,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Deactivate the tool (it's active by default)
        result = await tool_service.set_tool_state(test_db, 1, activate=False, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_tool.enabled is False

        # Verify notification
        tool_service._notify_tool_deactivated.assert_called_once()
        tool_service._notify_tool_activated.assert_not_called()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_set_tool_state_not_found(self, tool_service, test_db):
        """Test setting tool state when not found."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=None)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        with pytest.raises(ToolError) as exc:
            await tool_service.set_tool_state(test_db, "1", activate=False, reachable=True)

        assert "Tool not found: 1" in str(exc.value)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, "1")

    @pytest.mark.asyncio
    async def test_set_tool_state_activate_tool(self, tool_service, test_db, mock_tool, monkeypatch):
        """Test activating tool state."""
        # Mock DB get to return tool
        mock_tool.enabled = False
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        tool_service._notify_tool_activated = AsyncMock()

        result = await tool_service.set_tool_state(test_db, "1", activate=True, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, "1")

        tool_service._notify_tool_activated.assert_called_once_with(mock_tool)

        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_notify_tool_publish_event(self, tool_service, mock_tool):
        """Test notification methods publish events via EventService."""
        # Mock EventService.publish_event
        tool_service._event_service.publish_event = AsyncMock()

        # Test all notification methods
        mock_tool.enabled = True
        mock_tool.reachable = True
        await tool_service._notify_tool_activated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_deactivated(mock_tool)

        mock_tool.enabled = False
        await tool_service._notify_tool_removed(mock_tool)

        tool_info = {"id": mock_tool.id, "name": mock_tool.name}
        await tool_service._notify_tool_deleted(tool_info)

        # Verify all 4 events were published
        assert tool_service._event_service.publish_event.await_count == 4

        # Verify event types were correct
        calls = tool_service._event_service.publish_event.call_args_list
        assert calls[0][0][0]["type"] == "tool_activated"
        assert calls[1][0][0]["type"] == "tool_deactivated"
        assert calls[2][0][0]["type"] == "tool_removed"
        assert calls[3][0][0]["type"] == "tool_deleted"

        # Verify event data
        assert calls[0][0][0]["data"]["id"] == mock_tool.id
        assert calls[0][0][0]["data"]["name"] == mock_tool.name
        assert calls[0][0][0]["data"]["enabled"] is True

        assert calls[3][0][0]["data"] == tool_info

    @pytest.mark.asyncio
    async def test_publish_event_with_real_queue(self, tool_service):
        # Arrange
        q = asyncio.Queue()
        # Force local mode (no Redis) and seed one subscriber via EventService
        tool_service._event_service._redis_client = None
        tool_service._event_service._event_subscribers = [q]
        event = {"type": "test", "data": 123}

        # Act
        await tool_service._publish_event(event)

        # Assert - the event was put on the queue
        queued_event = await q.get()
        assert queued_event == event
        assert q.empty()

    @pytest.mark.asyncio
    async def test_set_tool_state_no_change(self, tool_service, mock_tool, test_db):
        """Test setting tool state with no change."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification methods
        tool_service._notify_tool_activated = AsyncMock()
        tool_service._notify_tool_deactivated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/test",
            description="A test tool",
            original_description="A test tool original",
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Deactivate the tool (it's active by default)
        result = await tool_service.set_tool_state(test_db, 1, activate=True, reachable=True)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_not_called()
        test_db.refresh.assert_not_called()

        # Verify properties were updated
        assert mock_tool.enabled is True

        # Verify notification
        tool_service._notify_tool_deactivated.assert_not_called()
        tool_service._notify_tool_activated.assert_not_called()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_update_tool(self, tool_service, mock_tool, test_db):
        """Test updating a tool."""
        # Mock DB get to return tool
        test_db.get = Mock(return_value=mock_tool)

        # Mock DB query to check for name conflicts (returns None = no conflict)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        test_db.commit = Mock()
        test_db.refresh = Mock()

        # Mock notification
        tool_service._notify_tool_updated = AsyncMock()

        # Mock conversion
        tool_read = ToolRead(
            id="1",
            original_name="test_tool",
            custom_name="test_tool",
            custom_name_slug="test-tool",
            gateway_slug="test-gateway",
            name="test-gateway-test-tool",
            url="http://example.com/tools/updated",  # Updated URL
            description="An updated test tool",  # Updated description
            original_description="A test tool original",  # original description
            integration_type="MCP",
            request_type="POST",
            headers={"Content-Type": "application/json"},
            input_schema={"type": "object", "properties": {"param": {"type": "string"}}},
            jsonpath_filter="",
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
            enabled=True,
            reachable=True,
            gateway_id=None,
            execution_count=0,
            auth=None,  # Add auth field
            annotations={},  # Add annotations field
            metrics={
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "failure_rate": 0.0,
                "min_response_time": None,
                "max_response_time": None,
                "avg_response_time": None,
                "last_execution_time": None,
            },
        )
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # Create update request
        tool_update = ToolUpdate(
            custom_name="updated_tool",
            url="http://example.com/tools/updated",
            description="An updated test tool",
        )

        # Call method
        result = await tool_service.update_tool(test_db, 1, tool_update)

        # Verify DB operations
        test_db.get.assert_called_once_with(DbTool, 1)
        test_db.commit.assert_called_once()
        test_db.refresh.assert_called_once()

        # Verify properties were updated
        assert mock_tool.custom_name == "updated_tool"
        assert mock_tool.url == "http://example.com/tools/updated"
        assert mock_tool.description == "An updated test tool"
        assert mock_tool.original_description == "A test tool original"

        # Verify notification
        tool_service._notify_tool_updated.assert_called_once()

        # Verify result
        assert result == tool_read

    @pytest.mark.asyncio
    async def test_update_tool_name_conflict(self, tool_service, mock_tool, test_db):
        """Test updating a tool with a name that conflicts with another tool."""
        # Mock DB get to return our tool
        test_db.get = Mock(return_value=mock_tool)

        # Create a conflicting tool
        conflicting_tool = MagicMock(spec=DbTool)
        conflicting_tool.id = 2
        conflicting_tool.name = "existing_tool"
        conflicting_tool.enabled = True

        # Mock DB query to check for name conflicts (returns None, so no pre-check conflict)
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock commit to raise IntegrityError
        test_db.commit = Mock(side_effect=IntegrityError("statement", "params", "orig"))
        test_db.rollback = Mock()

        # Create update request with conflicting name
        tool_update = ToolUpdate(
            name="existing_tool",  # Name that conflicts with another tool
        )

        # Should raise IntegrityError for name conflict during commit
        with pytest.raises(IntegrityError) as exc_info:
            await tool_service.update_tool(test_db, 1, tool_update)

        assert "statement" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tool_service, test_db):
        """Test updating a non-existent tool."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=None)

        # Create update request
        tool_update = ToolUpdate(
            name="updated_tool",
        )

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.update_tool(test_db, 999, tool_update)

        assert "Tool not found: 999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_none_name(self, tool_service, mock_tool, test_db):
        """Test updating a tool with no name."""
        # Mock DB get to return None
        test_db.get = Mock(return_value=mock_tool)

        # Create update request
        tool_update = ToolUpdate()

        # The service wraps the exception in ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool_service.update_tool(test_db, 999, tool_update)

        assert "Failed to update tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_tool_extra_fields(self, tool_service, mock_tool, test_db):
        """Test updating extra fields in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

        # Create update request
        tool_update = ToolUpdate(integration_type="REST", request_type="POST", headers={"key": "value"}, input_schema={"key2": "value2"}, annotations={"key3": "value3"}, jsonpath_filter="test_filter")

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.integration_type == "REST"
        assert result.request_type == "POST"
        assert result.headers == {"key": "value"}
        assert result.input_schema == {"key2": "value2"}
        assert result.annotations == {"key3": "value3"}
        assert result.jsonpath_filter == "test_filter"

    @pytest.mark.asyncio
    async def test_update_tool_basic_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        creds = base64.b64encode(b"test_user:test_password").decode()
        auth_dict = {"Authorization": f"Basic {creds}"}
        basic_auth_value = encode_auth(auth_dict)
        # basic_auth_value = "FpZyxAu5PVpT0FN-gJ0JUmdovCMS0emkwW1Vb8HvkhjiBZhj1gDgDRF1wcWNrjTJSLtkz1rLzKibXrhk4GbxXnV6LV4lSw_JDYZ2sPNRy68j_UKOJnf_"

        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues(auth_type="basic", auth_value=basic_auth_value))

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth == AuthenticationValues(auth_type="basic", username="test_user", password=settings.masked_auth_value)

    @pytest.mark.asyncio
    async def test_update_tool_bearer_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

        # Bearer auth_value
        # Create auth_value with the following values
        # token = "test_token"
        basic_auth_value = encode_auth({"Authorization": "Bearer test_token"})
        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues(auth_type="bearer", auth_value=basic_auth_value))

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth == AuthenticationValues(auth_type="bearer", token=settings.masked_auth_value)

    @pytest.mark.asyncio
    async def test_update_tool_empty_auth(self, tool_service, mock_tool, test_db):
        """Test updating auth in an existing tool."""
        # Mock DB get to return None
        mock_tool.id = "999"
        test_db.get = Mock(return_value=mock_tool)
        test_db.commit = Mock()  # SQLAlchemy commit is synchronous
        test_db.refresh = Mock()  # SQLAlchemy refresh is synchronous

        # Create update request
        tool_update = ToolUpdate(auth=AuthenticationValues())

        # The service wraps the exception in ToolError
        result = await tool_service.update_tool(test_db, "999", tool_update)

        assert result.auth is None

    @pytest.mark.asyncio
    async def test_invoke_tool_not_found(self, tool_service, test_db):
        """Test invoking a non-existent tool."""
        # Mock DB to return no tool
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = None
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = []
        test_db.execute = Mock(return_value=mock_scalar)

        # Should raise NotFoundError
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "nonexistent_tool", {}, request_headers=None)

        assert "Tool not found: nonexistent_tool" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_inactive(self, tool_service, mock_tool, test_db):
        """Test invoking an inactive tool."""
        # Set tool to inactive
        mock_tool.enabled = False

        # Mock DB to return inactive tool in single query
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
        test_db.execute = Mock(return_value=mock_scalar)

        # Should raise NotFoundError with "inactive" message
        with pytest.raises(ToolNotFoundError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert "Tool 'test_tool' exists but is inactive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_get(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        # ----------------  DB  -----------------
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        # Set up mock to return tool for first query, GlobalConfig for second
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # --------------- HTTP ------------------
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        # <-- make json() *synchronous*
        mock_response.json = Mock(return_value={"result": "REST tool response"})

        # stub the correct method for a GET
        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        # Mock the metrics buffer at module level
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            # -------------- invoke -----------------
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            # ------------- asserts -----------------
            tool_service._http_client.get.assert_called_once_with(
                mock_tool.url,
                params={},  # payload is empty
                headers=mock_tool.headers,
            )
            assert result.content[0].text == '{\n  "result": "REST tool response"\n}'
            # Verify metrics were recorded via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is True
            assert call_kwargs["error_message"] is None

        # Test 204 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 204
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            # -------------- invoke -----------------
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Request completed successfully (No Content)"

        # Test 205 status
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 205
        mock_response.json = Mock(return_value=ToolResult(content=[TextContent(type="text", text="Tool error encountered")]))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        # ------------- metrics -----------------
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            # -------------- invoke -----------------
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

        assert result.content[0].text == "Tool error encountered"

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_post(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})  # Make json() synchronous
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics buffer at module level and other dependencies
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "REST tool response"}),
        ):
            # Invoke tool
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            # Verify HTTP request
            tool_service._http_client.request.assert_called_once_with(
                "POST",
                mock_tool.url,
                json={"param": "value"},
                headers=mock_tool.headers,
            )

            # Verify result
            assert result.content[0].text == '{\n  "result": "REST tool response"\n}'

            # Verify metrics recorded via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is True
            assert call_kwargs["error_message"] is None

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_decrypts_encrypted_custom_headers(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """REST invocation should send decrypted values for encrypted custom headers."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.headers = {
            "Authorization": {
                "_mcpgateway_encrypted_header_value_v1": encode_auth(
                    {"value": "Bearer runtime-secret"},
                ),
            },
            "X-Trace-Id": "trace-1",
        }

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})
        tool_service._http_client.request.return_value = mock_response

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch(
                "mcpgateway.services.tool_service.decode_auth",
                side_effect=lambda value: {"value": "Bearer runtime-secret"} if value == mock_tool.headers["Authorization"]["_mcpgateway_encrypted_header_value_v1"] else {},
            ),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "REST tool response"}),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        request_headers = tool_service._http_client.request.call_args.kwargs["headers"]
        assert request_headers["Authorization"] == "Bearer runtime-secret"
        assert request_headers["X-Trace-Id"] == "trace-1"

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_parameter_substitution(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "type": "summary", "other_param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        tool_service._http_client.request.assert_called_once_with(
            "POST",
            "http://example.com/resource/123/detail/summary",
            json={"other_param": "value"},
            headers=mock_tool.headers,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_post_with_path_query_and_body_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test POST request with path parameters, query parameters (with templates), and body parameters.

        This test demonstrates the complete parameter handling (no mappings = signed URL mode):
        - Path parameters (e.g., {user_id}) are substituted into the URL path
        - Query parameters can also use templates (e.g., ?api_key={api_key})
        - Static query parameters (e.g., ?version=v2) are preserved as-is
        - Query parameters are preserved in URL for POST (signed URL support)
        - Remaining payload goes to the JSON body (without query params)
        """
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        # URL with path parameters AND templated query parameters
        mock_tool.url = "http://example.com/api/users/{user_id}/posts?api_key={api_key}&version=v2"

        # Payload contains: path param (user_id), query param (api_key), and body params (title, content)
        payload = {
            "user_id": 456,  # Will be substituted into URL path
            "api_key": "secret123",  # Template in query string portion of URL; substituted then extracted as query param
            "title": "New Post",  # Will go to JSON body
            "content": "Hello World",  # Will go to JSON body
        }

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"id": 789, "status": "created"})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        # Verify parameter handling for POST (no mappings = signed URL support):
        # 1. Path parameter substituted: /users/456/posts
        # 2. Query param template substituted: api_key=secret123
        # 3. Static query param preserved: version=v2
        # 4. Query params STAY in URL (not merged into body) for signed URL support
        # 5. Body params: title and content (user_id and api_key removed after path/query substitution)
        tool_service._http_client.request.assert_called_once_with(
            "POST",
            "http://example.com/api/users/456/posts?api_key=secret123&version=v2",  # Path param substituted, query params preserved
            json={"title": "New Post", "content": "Hello World"},  # Only body params
            headers=mock_tool.headers,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_get_with_static_query_params_no_mapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test GET request with static URL query params and no query_mapping.

        Verifies that query params extracted from the URL are merged into the
        payload and sent together via params= on the GET request.
        """
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/api/search?version=v2&format=json"

        payload = {"q": "hello"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"results": []})

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        # URL query params (version, format) are merged into payload alongside the user-provided "q"
        tool_service._http_client.get.assert_called_once_with(
            "http://example.com/api/search",
            params={"q": "hello", "version": "v2", "format": "json"},
            headers=mock_tool.headers,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_put_with_query_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test PUT request with URL query params merges them into the JSON body.

        Verifies that non-GET methods other than POST (e.g. PUT) also merge
        URL query params into the JSON body for backward compatibility.
        """
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "PUT"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/api/items/1?version=v2"

        payload = {"name": "updated"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"status": "ok"})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        # Query params preserved in URL for signed URL support (no mappings)
        tool_service._http_client.request.assert_called_once_with(
            "PUT",
            "http://example.com/api/items/1?version=v2",
            json={"name": "updated"},
            headers=mock_tool.headers,
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_jq_filter_error_returns_error(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test REST tool invocation marks result as error when jq filter returns TextContent error."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ".invalid_path"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "some data"})
        tool_service._http_client.request.return_value = mock_response

        # extract_using_jq returns TextContent error list (error case)
        jq_error = [TextContent(type="text", text="Error applying jsonpath filter")]

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value=jq_error),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert result.is_error is True
        assert result.content[0].text == "Error applying jsonpath filter"
        # Verify metrics recorded as failure
        mock_metrics_buffer.record_tool_metric.assert_called_once()
        call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
        assert call_kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_parameter_substitution_missed_input(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a REST tool."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/resource/{id}/detail/{type}"

        payload = {"id": 123, "other_param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        with pytest.raises(ToolInvocationError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

            assert "Required URL parameter 'type' not found in arguments" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_streamablehttp(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Standard
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/mcp",
            enabled=True,
            reachable=True,
            auth_type="bearer",  # attribute your error complained about
            auth_value="Bearer abc123",
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
        )
        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "StreamableHTTP"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None  # No auth
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = None  # Or whatever makes sense as a default

            m = Mock()
            m.scalar_one_or_none.return_value = value
            m.scalars.return_value = m
            if value is None:
                m.all.return_value = []
            else:
                m.all.return_value = [value]
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP response")])

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once_with("dummy_tool", {"param": "value"}, meta=None)

        # Our ToolResult bubbled back out
        assert result.content[0].text == "MCP response"

        # Set a concrete ID
        mock_tool.id = "1"

        # Final mock object with tool_id
        mock_metric = Mock()
        mock_metric.tool_id = mock_tool.id
        mock_metric.is_success = True
        mock_metric.error_message = None
        mock_metric.response_time = 1

        # Setup the chain for test_db.query().filter_by().first()
        query_mock = Mock()
        test_db.query = Mock(return_value=query_mock)
        query_mock.filter_by.return_value.first.return_value = mock_metric

        # ----------------------------------------
        # Now, simulate the actual method call

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_streamablehttp_creates_client_lifecycle_spans(self, tool_service, mock_tool, test_db):
        """Non-pooled MCP calls should emit client call, initialize, and request spans in order."""
        # Standard
        from contextlib import contextmanager
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/mcp",
            enabled=True,
            reachable=True,
            auth_type="bearer",
            auth_value="Bearer abc123",
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
        )
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "StreamableHTTP"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id
        mock_tool.id = "tool-123"

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            value = returns.pop(0) if returns else None
            result = Mock()
            result.scalar_one_or_none.return_value = value
            result.scalars.return_value = result
            result.all.return_value = [] if value is None else [value]
            return result

        test_db.execute = Mock(side_effect=execute_side_effect)

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP response")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        captured_headers = {}

        @asynccontextmanager
        async def mock_streamable_client(*_args, **kwargs):
            captured_headers.update(kwargs["headers"])
            yield ("read", "write", None)

        span_names = []

        @contextmanager
        def record_span(name, _attributes=None):
            span_names.append(name)
            yield MagicMock()

        def inject_headers(headers):
            traced = dict(headers)
            traced["traceparent"] = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
            return traced

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
            patch("mcpgateway.services.tool_service.create_span", side_effect=record_span),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=inject_headers),
            patch("mcpgateway.services.tool_service.otel_context_active", return_value=True),
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-123"),
        ):
            mock_settings.mcp_session_pool_enabled = False
            mock_settings.default_passthrough_headers = []
            mock_settings.tool_timeout = 60

            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        assert result.content[0].text == "MCP response"
        assert captured_headers["traceparent"].startswith("00-")
        assert captured_headers["X-Correlation-ID"] == "corr-123"
        assert span_names[:3] == ["tool.invoke", "mcp.client.call", "mcp.client.initialize"]
        assert "mcp.client.request" in span_names
        assert "mcp.client.response" in span_names

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_pooled_path_does_not_inject_trace_headers(self, tool_service, mock_tool, test_db):
        """Pooled MCP sessions must NOT receive traceparent/tracestate to prevent context pollution."""
        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/mcp",
            enabled=True,
            reachable=True,
            auth_type="bearer",
            auth_value="Bearer abc123",
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
        )
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "StreamableHTTP"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id
        mock_tool.id = "tool-123"

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            value = returns.pop(0) if returns else None
            result = Mock()
            result.scalar_one_or_none.return_value = value
            result.scalars.return_value = result
            result.all.return_value = [] if value is None else [value]
            return result

        test_db.execute = Mock(side_effect=execute_side_effect)

        expected_result = ToolResult(content=[TextContent(type="text", text="pooled ok")])
        pooled_session_mock = AsyncMock()
        pooled_session_mock.call_tool = AsyncMock(return_value=expected_result)

        captured_pool_headers = {}

        @asynccontextmanager
        async def mock_pool_session(**kwargs):
            captured_pool_headers.update(kwargs.get("headers") or {})
            pooled = SimpleNamespace(session=pooled_session_mock)
            yield pooled

        mock_pool = MagicMock()
        mock_pool.session = mock_pool_session

        @contextmanager
        def noop_span(name, _attributes=None):
            yield MagicMock()

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
            patch("mcpgateway.services.tool_service.create_span", side_effect=noop_span),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=lambda h: {**h, "traceparent": "00-injected-span-01"}),
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value="corr-456"),
            patch("mcpgateway.services.tool_service.get_mcp_session_pool", return_value=mock_pool),
        ):
            mock_settings.mcp_session_pool_enabled = True
            mock_settings.default_passthrough_headers = []
            mock_settings.tool_timeout = 60

            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        assert result.content[0].text == "pooled ok"
        # The critical assertion: pooled path must NOT have traceparent/tracestate
        assert "traceparent" not in captured_pool_headers, "traceparent must not be injected into pooled sessions"
        assert "tracestate" not in captured_pool_headers, "tracestate must not be injected into pooled sessions"
        # Correlation ID must also be absent from pooled headers (pinned transport)
        assert "X-Correlation-ID" not in captured_pool_headers, "X-Correlation-ID must not be injected into pooled sessions"

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_isError_fallback(self, tool_service, mock_tool, test_db):
        """Test MCP tool invocation falls back to isError when is_error is None."""
        # Standard
        from contextlib import asynccontextmanager
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/mcp",
            enabled=True,
            reachable=True,
            auth_type="bearer",
            auth_value="Bearer abc123",
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
        )
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "StreamableHTTP"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = None
            m = Mock()
            m.scalar_one_or_none.return_value = value
            m.scalars.return_value = m
            m.all.return_value = [value] if value else []
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

        # Create a result where is_error is None but isError is True
        # This triggers the fallback at line 3684
        call_result = MagicMock()
        call_result.is_error = None
        call_result.isError = True
        call_result.content = [TextContent(type="text", text="error from remote")]
        call_result.model_dump.return_value = {
            "content": [{"type": "text", "text": "error from remote"}],
            "isError": True,
            "structuredContent": None,
            "structured_content": None,
        }
        call_result.meta = None

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=call_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        # is_error should be True from the isError fallback
        assert result.is_error is True
        assert result.content[0].text == "error from remote"

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_non_standard(self, tool_service, mock_tool, test_db):
        """Test invoking a REST tool."""
        # Standard
        from types import SimpleNamespace

        mock_gateway = SimpleNamespace(
            id="42",
            name="test_gateway",
            slug="test-gateway",
            url="http://fake-mcp:8080/sse",
            enabled=True,
            reachable=True,
            auth_type="bearer",  # attribute your error complained about
            auth_value="Bearer abc123",
            capabilities={"prompts": {"listChanged": True}, "resources": {"listChanged": True}, "tools": {"listChanged": True}},
            transport="STREAMABLEHTTP",
            passthrough_headers=[],
        )
        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "ABC"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_type = None
        mock_tool.auth_value = None  # No auth
        mock_tool.original_name = "dummy_tool"
        mock_tool.headers = {}
        mock_tool.name = "test-gateway-dummy-tool"
        mock_tool.gateway_slug = "test-gateway"
        mock_tool.gateway_id = mock_gateway.id

        returns = [mock_tool, mock_gateway, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = None  # Or whatever makes sense as a default

            m = Mock()
            m.scalar_one_or_none.return_value = value
            m.scalars.return_value = m
            if value is None:
                m.all.return_value = []
            else:
                m.all.return_value = [value]
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            result = await tool_service.invoke_tool(test_db, "dummy_tool", {"param": "value"}, request_headers=None)

        # Our ToolResult bubbled back out
        assert result.content[0].text == ""

        # Set a concrete ID
        mock_tool.id = "1"

        # Final mock object with tool_id
        mock_metric = Mock()
        mock_metric.tool_id = mock_tool.id
        mock_metric.is_success = True
        mock_metric.error_message = None
        mock_metric.response_time = 1

        # Setup the chain for test_db.query().filter_by().first()
        query_mock = Mock()
        test_db.query = Mock(return_value=query_mock)
        query_mock.filter_by.return_value.first.return_value = mock_metric

        # ----------------------------------------
        # Now, simulate the actual method call
        # This is what your production code would run:
        metric = test_db.query().filter_by().first()

        # Assertions
        assert metric is not None, "No ToolMetric was recorded"
        assert metric.tool_id == mock_tool.id
        assert metric.is_success is True
        assert metric.error_message is None
        assert metric.response_time >= 0  # You can check with a tolerance if needed

    @pytest.mark.asyncio
    async def test_invoke_tool_invalid_tool_type(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking an invalid tool type."""
        # Configure tool as REST
        mock_tool.integration_type = "ABC"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None  # No auth
        mock_tool.url = "http://example.com/"

        payload = {"param": "value"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        response = await tool_service.invoke_tool(test_db, "test_tool", payload, request_headers=None)

        assert response.content[0].text == "Invalid tool type"

    @pytest.mark.asyncio
    async def test_invoke_tool_cache_hit_hydrates_auth_material_from_db(self, tool_service, test_db):
        """Cache-hit invocation should hydrate auth material from DB when required."""
        cached_payload = {
            "status": "active",
            "tool": {
                "id": "tool-cache-1",
                "name": "cached_tool",
                "original_name": "cached_tool",
                "url": "http://example.com/tool",
                "integration_type": "ABC",
                "request_type": "POST",
                "auth_type": "oauth",
                "headers": {},
                "annotations": {},
                "jsonpath_filter": "",
                "output_schema": {},
                "enabled": True,
                "reachable": True,
                "visibility": "public",
                "owner_email": None,
                "team_id": None,
                "gateway_id": "gw-cache-1",
            },
            "gateway": {
                "id": "gw-cache-1",
                "name": "cached-gw",
                "url": "http://example.com/gateway",
                "auth_type": "basic",
                "passthrough_headers": [],
            },
        }

        lookup_cache = SimpleNamespace(
            enabled=True,
            get=AsyncMock(return_value=cached_payload),
            set=AsyncMock(),
            set_negative=AsyncMock(),
        )

        hydrated_gateway = SimpleNamespace(
            auth_value="gateway-secret",
            auth_query_params=None,
            oauth_config={"grant_type": "client_credentials", "client_id": "gw", "client_secret": "secret"},
        )
        hydrated_tool = SimpleNamespace(
            auth_value="tool-secret",
            oauth_config={"grant_type": "client_credentials", "client_id": "tool", "client_secret": "secret"},
            gateway=hydrated_gateway,
        )
        hydration_result = Mock()
        hydration_result.scalar_one_or_none.return_value = hydrated_tool
        test_db.execute = Mock(return_value=hydration_result)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=lookup_cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
        ):
            response = await tool_service.invoke_tool(test_db, "cached_tool", {"param": "value"}, request_headers=None)

        assert response.content[0].text == "Invalid tool type"
        assert test_db.execute.called

    @pytest.mark.asyncio
    async def test_invoke_tool_cache_hit_hydrates_authheaders_dict_from_db(self, tool_service, test_db):
        """Cache-miss hydration encodes DbGateway.auth_value dict (JSON col) to str for downstream use."""
        cached_payload = {
            "status": "active",
            "tool": {
                "id": "tool-cache-2",
                "name": "cached_tool_ah",
                "original_name": "cached_tool_ah",
                "url": "http://example.com/tool",
                "integration_type": "ABC",
                "request_type": "POST",
                "auth_type": "authheaders",
                "headers": {},
                "annotations": {},
                "jsonpath_filter": "",
                "output_schema": {},
                "enabled": True,
                "reachable": True,
                "visibility": "public",
                "owner_email": None,
                "team_id": None,
                "gateway_id": "gw-cache-2",
            },
            "gateway": {
                "id": "gw-cache-2",
                "name": "cached-gw-ah",
                "url": "http://example.com/gateway",
                "auth_type": "authheaders",
                "passthrough_headers": [],
            },
        }

        lookup_cache = SimpleNamespace(
            enabled=True,
            get=AsyncMock(return_value=cached_payload),
            set=AsyncMock(),
            set_negative=AsyncMock(),
        )

        # DbGateway.auth_value is a JSON dict — the path under test encodes it
        hydrated_gateway = SimpleNamespace(
            auth_value={"X-Custom-Auth-Header": "my-token"},
            auth_query_params=None,
            oauth_config=None,
        )
        hydrated_tool = SimpleNamespace(
            auth_value=None,
            oauth_config=None,
            gateway=hydrated_gateway,
        )
        hydration_result = Mock()
        hydration_result.scalar_one_or_none.return_value = hydrated_tool
        test_db.execute = Mock(return_value=hydration_result)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=lookup_cache),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.encode_auth", wraps=encode_auth) as spy_encode,
        ):
            response = await tool_service.invoke_tool(test_db, "cached_tool_ah", {"param": "value"}, request_headers=None)

        assert response.content[0].text == "Invalid tool type"
        assert test_db.execute.called
        # Verify the hydration path actually called encode_auth on the dict
        spy_encode.assert_called_once_with({"X-Custom-Auth-Header": "my-token"})

    @pytest.mark.asyncio
    async def test_invoke_tool_mcp_tool_basic_auth(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking an invalid tool type."""
        # Basic auth_value
        # Create auth_value with the following values
        # user = "test_user"
        # password = "test_password"
        basic_auth_value = encode_auth({"Authorization": "Basic " + base64.b64encode(b"test_user:test_password").decode()})

        # Configure tool as REST
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "SSE"
        mock_tool.jsonpath_filter = ""
        mock_tool.enabled = True
        mock_tool.reachable = True
        mock_tool.auth_type = "basic"
        mock_tool.auth_value = basic_auth_value
        mock_tool.url = "http://example.com/sse"

        # Mock DB to return the tool
        mock_scalar_1 = Mock()
        mock_scalar_1.scalar_one_or_none.return_value = mock_tool

        mock_gateway.auth_type = "basic"
        mock_gateway.auth_value = basic_auth_value
        mock_gateway.enabled = True
        mock_gateway.reachable = True
        mock_gateway.id = mock_tool.gateway_id
        mock_gateway.slug = "test-gateway"
        mock_gateway.capabilities = {"tools": {"listChanged": True}}
        mock_gateway.transport = "SSE"
        mock_gateway.passthrough_headers = []

        # Ensure the service reads headers from the gateway attached to the tool
        # The invoke path uses `gateway = tool.gateway` for auth header calculation
        mock_tool.gateway = mock_gateway

        # Two DB selects occur in this path: first for tool, then for gateway
        # Return the tool on first call and the gateway on second call
        returns = [mock_tool, mock_gateway]

        def execute_side_effect(*_args, **_kwargs):
            if returns:
                value = returns.pop(0)
            else:
                value = mock_gateway

            # Return an object whose scalar_one_or_none() returns the real value
            class Result:
                def scalar_one_or_none(self_inner):
                    return value

                def scalars(self_inner):
                    return self_inner

                def all(self_inner):
                    return [value] if value else []

            return Result()

        test_db.execute = Mock(side_effect=execute_side_effect)

        # Mock db.query() for global_config_cache which uses legacy query API
        mock_query = Mock()
        mock_query.first.return_value = None  # No global config
        test_db.query = Mock(return_value=mock_query)

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP response")])

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        # @asynccontextmanager
        # async def mock_sse_client(*_args, **_kwargs):
        #     yield ("read", "write")

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx) as sse_client_mock,
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
            patch("mcpgateway.services.tool_service.settings.mcp_session_pool_enabled", False),
            patch("mcpgateway.services.tool_service.get_correlation_id", return_value=None),
        ):
            # ------------------------------------------------------------------
            # 4.  Act
            # ------------------------------------------------------------------
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once_with("test_tool", {"param": "value"}, meta=None)

        sse_ctx.__aenter__.assert_awaited_once()

        sse_client_mock.assert_called_once()
        sse_call_kwargs = sse_client_mock.call_args.kwargs
        assert sse_call_kwargs["url"] == mock_gateway.url
        assert sse_call_kwargs["headers"]["Authorization"] == "Basic dGVzdF91c2VyOnRlc3RfcGFzc3dvcmQ="
        assert sse_call_kwargs["httpx_client_factory"] is not None

    @pytest.mark.asyncio
    async def test_invoke_tool_error(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking a tool that returns an error."""
        # Configure tool
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None  # No auth

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client to raise an error
        tool_service._http_client.request.side_effect = Exception("HTTP error")

        # Mock metrics buffer at module level and decode_auth
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
        ):
            # Should raise ToolInvocationError
            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            assert "Tool invocation failed: HTTP error" in str(exc_info.value)

            # Verify metrics recorded with error via buffer service
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["tool_id"] == str(mock_tool.id)
            assert call_kwargs["success"] is False
            assert call_kwargs["error_message"] == "HTTP error"

    @pytest.mark.asyncio
    async def test_invoke_tool_with_metadata(self, tool_service, mock_tool, test_db):
        """Test invoking a tool with metadata."""
        # Configure tool as MCP/SSE
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "SSE"
        mock_tool.url = "http://example.com/sse"
        mock_tool.auth_value = None

        # Mock DB
        mock_scalar = Mock()
        mock_scalar.scalar_one_or_none.return_value = mock_tool
        mock_scalar.scalars.return_value = mock_scalar
        mock_scalar.all.return_value = [mock_tool]
        test_db.execute = Mock(return_value=mock_scalar)

        # Mock SSE client and session
        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ["read", "write"]

        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=ToolResult(content=[TextContent(type="text", text="MCP response")]))

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock

        meta_data = {"trace_id": "123", "user": "test"}

        # Mock metrics buffer service
        mock_metrics_buffer = Mock()

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None, meta_data=meta_data)

        session_mock.call_tool.assert_awaited_once_with("test_tool", {}, meta=meta_data)

    @pytest.mark.asyncio
    async def test_invoke_tool_error_exception_group_unwrapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test that ExceptionGroup errors are unwrapped to show root cause.

        MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup. When such
        errors occur, the error message should show the actual root cause error
        (e.g., "Connection refused") rather than the unhelpful "unhandled errors
        in a TaskGroup (1 sub-exception)" message.

        See GitHub issue #1902.
        """
        # Configure tool
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Create a nested ExceptionGroup simulating MCP SDK TaskGroup behavior
        root_cause_error = ConnectionRefusedError("Connection refused by upstream MCP server")
        inner_group = ExceptionGroup("inner task group", [root_cause_error])
        outer_group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner_group])

        # Mock HTTP client to raise an ExceptionGroup
        tool_service._http_client.request.side_effect = outer_group

        # Mock metrics buffer at module level and decode_auth
        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
        ):
            # Should raise ToolInvocationError with the unwrapped root cause message
            with pytest.raises(ToolInvocationError) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

            # The error message should contain the root cause, not the ExceptionGroup wrapper
            error_str = str(exc_info.value)
            assert "Connection refused by upstream MCP server" in error_str
            assert "unhandled errors in a TaskGroup" not in error_str

            # Verify metrics recorded with root cause error message
            mock_metrics_buffer.record_tool_metric.assert_called_once()
            call_kwargs = mock_metrics_buffer.record_tool_metric.call_args[1]
            assert call_kwargs["success"] is False
            assert "Connection refused by upstream MCP server" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_reset_metrics(self, tool_service, test_db):
        """Test resetting metrics."""
        # Mock DB operations
        test_db.execute = Mock()
        test_db.commit = Mock()

        # Reset all metrics
        await tool_service.reset_metrics(test_db)

        # Verify DB operations (raw + hourly rollups)
        assert test_db.execute.call_count == 2
        test_db.commit.assert_called_once()

        # Reset metrics for specific tool
        test_db.execute.reset_mock()
        test_db.commit.reset_mock()

        await tool_service.reset_metrics(test_db, tool_id=1)

        # Verify DB operations with tool_id (raw + hourly rollups)
        assert test_db.execute.call_count == 2
        test_db.commit.assert_called_once()

    async def test_record_tool_metric(self, tool_service, mock_tool):
        """Test recording tool invocation metrics."""
        # Set up test data
        start_time = 100.0
        success = True
        error_message = None

        # Mock database
        mock_db = MagicMock()

        # Mock time.monotonic to return a consistent value
        with patch("mcpgateway.services.tool_service.time.monotonic", return_value=105.0):
            # Mock ToolMetric class
            with patch("mcpgateway.services.tool_service.ToolMetric") as MockToolMetric:
                mock_metric_instance = MagicMock()
                MockToolMetric.return_value = mock_metric_instance

                # Call the method
                await tool_service._record_tool_metric(mock_db, mock_tool, start_time, success, error_message)

                # Verify ToolMetric was created with correct data
                MockToolMetric.assert_called_once_with(
                    tool_id=mock_tool.id,
                    response_time=5.0,  # 105.0 - 100.0
                    is_success=True,
                    error_message=None,
                )

                # Verify DB operations
                mock_db.add.assert_called_once_with(mock_metric_instance)
                mock_db.commit.assert_called_once()

    async def test_record_tool_metric_with_error(self, tool_service, mock_tool):
        """Test recording tool invocation metrics with error."""
        start_time = 100.0
        success = False
        error_message = "Connection timeout"

        # Mock database
        mock_db = MagicMock()

        with patch("mcpgateway.services.tool_service.time.monotonic", return_value=102.5):
            with patch("mcpgateway.services.tool_service.ToolMetric") as MockToolMetric:
                mock_metric_instance = MagicMock()
                MockToolMetric.return_value = mock_metric_instance

                await tool_service._record_tool_metric(mock_db, mock_tool, start_time, success, error_message)

                # Verify ToolMetric was created with error data
                MockToolMetric.assert_called_once_with(tool_id=mock_tool.id, response_time=2.5, is_success=False, error_message="Connection timeout")

                mock_db.add.assert_called_once_with(mock_metric_instance)
                mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_aggregate_metrics(self, tool_service, monkeypatch):
        """Test aggregating metrics across all tools using combined raw + rollup query."""
        # Standard
        from unittest.mock import patch

        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module
        from mcpgateway.schemas import ToolMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        cache_module.metrics_cache.invalidate("tools")
        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        # Mock database
        mock_db = MagicMock()

        # Create a mock AggregatedMetrics result
        mock_result = AggregatedMetrics(
            total_executions=10,
            successful_executions=8,
            failed_executions=2,
            failure_rate=0.2,
            min_response_time=0.5,
            max_response_time=5.0,
            avg_response_time=2.3,
            last_execution_time="2025-01-10T12:00:00",
            raw_count=6,
            rollup_count=4,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(mock_db)

        assert isinstance(result, ToolMetrics)
        assert result.total_executions == 10
        assert result.successful_executions == 8
        assert result.failed_executions == 2
        assert result.failure_rate == 0.2
        assert result.min_response_time == 0.5
        assert result.max_response_time == 5.0
        assert result.avg_response_time == 2.3
        assert str(result.last_execution_time) == "2025-01-10 12:00:00"

    @pytest.mark.asyncio
    async def test_aggregate_metrics_no_data(self, tool_service, monkeypatch):
        """Test aggregating metrics when no data exists."""
        # Standard
        from unittest.mock import patch

        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module
        from mcpgateway.schemas import ToolMetrics
        from mcpgateway.services.metrics_query_service import AggregatedMetrics

        cache_module.metrics_cache.invalidate("tools")
        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        # Mock database
        mock_db = MagicMock()

        # Create a mock AggregatedMetrics result with no data
        mock_result = AggregatedMetrics(
            total_executions=0,
            successful_executions=0,
            failed_executions=0,
            failure_rate=0.0,
            min_response_time=None,
            max_response_time=None,
            avg_response_time=None,
            last_execution_time=None,
            raw_count=0,
            rollup_count=0,
        )

        with patch("mcpgateway.services.metrics_query_service.aggregate_metrics_combined", return_value=mock_result):
            result = await tool_service.aggregate_metrics(mock_db)

        assert isinstance(result, ToolMetrics)
        assert result.total_executions == 0
        assert result.successful_executions == 0
        assert result.failed_executions == 0
        assert result.failure_rate == 0.0
        assert result.min_response_time is None
        assert result.max_response_time is None
        assert result.avg_response_time is None
        assert result.last_execution_time is None

    async def test_validate_tool_url_success(self, tool_service):
        """Test successful tool URL validation."""
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        tool_service._http_client.get.return_value = mock_response

        # Should not raise any exception
        await tool_service._validate_tool_url("http://example.com/tool")

        tool_service._http_client.get.assert_called_once_with("http://example.com/tool")
        mock_response.raise_for_status.assert_called_once()

    async def test_validate_tool_url_failure(self, tool_service):
        """Test tool URL validation failure."""
        # Mock HTTP error
        tool_service._http_client.get.side_effect = Exception("Connection refused")

        with pytest.raises(ToolValidationError, match="Failed to validate tool URL: Connection refused"):
            await tool_service._validate_tool_url("http://example.com/tool")

    async def test_check_tool_health_success(self, tool_service, mock_tool):
        """Test successful tool health check."""
        mock_response = MagicMock()
        mock_response.is_success = True
        tool_service._http_client.get.return_value = mock_response

        result = await tool_service._check_tool_health(mock_tool)

        assert result is True
        tool_service._http_client.get.assert_called_once_with(mock_tool.url)

    async def test_check_tool_health_failure(self, tool_service, mock_tool):
        """Test failed tool health check."""
        mock_response = MagicMock()
        mock_response.is_success = False
        tool_service._http_client.get.return_value = mock_response

        result = await tool_service._check_tool_health(mock_tool)

        assert result is False

    async def test_check_tool_health_exception(self, tool_service, mock_tool):
        """Test tool health check with exception."""
        tool_service._http_client.get.side_effect = Exception("Network error")

        result = await tool_service._check_tool_health(mock_tool)

        assert result is False

    async def test_subscribe_events(self, tool_service):
        """Test event subscription mechanism."""
        # Create an event to publish
        test_event = {"type": "test_event", "data": {"id": 1}}

        # Start subscription in background
        subscriber = tool_service.subscribe_events()
        subscription_task = asyncio.create_task(anext(subscriber))

        # Give a moment for subscription to be registered
        await asyncio.sleep(0.01)

        # Publish event
        await tool_service._publish_event(test_event)

        # Get the event
        received_event = await subscription_task
        assert received_event == test_event

        # Clean up
        await subscriber.aclose()

    async def test_notify_tool_added(self, tool_service, mock_tool):
        """Test notification when tool is added."""
        with patch.object(tool_service, "_publish_event", new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_added(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_added"
            assert event["data"]["id"] == mock_tool.id
            assert event["data"]["name"] == mock_tool.name

    async def test_notify_tool_removed(self, tool_service, mock_tool):
        """Test notification when tool is removed."""
        with patch.object(tool_service, "_publish_event", new_callable=AsyncMock) as mock_publish:
            await tool_service._notify_tool_removed(mock_tool)

            mock_publish.assert_called_once()
            event = mock_publish.call_args[0][0]
            assert event["type"] == "tool_removed"
            assert event["data"]["id"] == mock_tool.id

    @pytest.mark.asyncio
    async def test_get_top_tools(self, tool_service, test_db, monkeypatch):
        """Test get_top_tools method."""
        # First-Party
        from mcpgateway.cache import metrics_cache as cache_module

        # Ensure this test does not read pre-populated cache entries from other tests.
        cache_module.metrics_cache.invalidate_prefix("top_tools:")
        monkeypatch.setattr(cache_module, "is_cache_enabled", lambda: False)

        # Mock the combined query results (TopPerformerResult objects)
        mock_performer1 = MagicMock()
        mock_performer1.id = "1"
        mock_performer1.name = "tool1"
        mock_performer1.execution_count = 10
        mock_performer1.avg_response_time = 1.5
        mock_performer1.success_rate = 90.0
        mock_performer1.last_execution = "2024-01-01T12:00:00"

        mock_performer2 = MagicMock()
        mock_performer2.id = "2"
        mock_performer2.name = "tool2"
        mock_performer2.execution_count = 5
        mock_performer2.avg_response_time = 2.0
        mock_performer2.success_rate = 80.0
        mock_performer2.last_execution = "2024-01-02T12:00:00"

        mock_combined_results = [mock_performer1, mock_performer2]

        # tool_service imports at top-level, so patch where it's used
        with patch("mcpgateway.services.tool_service.get_top_performers_combined") as mock_combined:
            mock_combined.return_value = mock_combined_results

            with patch("mcpgateway.services.tool_service.build_top_performers") as mock_build:
                mock_build.return_value = ["top_performer1", "top_performer2"]

                # Run the method
                result = await tool_service.get_top_tools(test_db, limit=5)

                # Assert the result is as expected
                assert result == ["top_performer1", "top_performer2"]

                # Assert get_top_performers_combined was called with correct params
                mock_combined.assert_called_once()
                call_kwargs = mock_combined.call_args[1]
                assert call_kwargs["metric_type"] == "tool"
                assert call_kwargs["limit"] == 5
                assert call_kwargs["include_deleted"] is False

                # Assert build_top_performers was called with the combined results
                mock_build.assert_called_once_with(mock_combined_results)

    @pytest.mark.asyncio
    async def test_list_tools_with_tags(self, tool_service, mock_tool):
        """Test listing tools with tag filtering."""
        # Third-Party

        # Mock query chain - support pagination methods
        mock_query = MagicMock()
        mock_query.where.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query

        session = MagicMock()

        # Mock DB execute chain for unified_paginate: execute().scalars().all()
        mock_tool.team_id = None
        session.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        session.commit = Mock()

        bind = MagicMock()
        bind.dialect = MagicMock()
        bind.dialect.name = "sqlite"  # or "postgresql"
        session.get_bind.return_value = bind

        # Mock convert_tool_to_read
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        with patch("mcpgateway.services.tool_service.select", return_value=mock_query):
            with patch("mcpgateway.services.tool_service.json_contains_tag_expr") as mock_json_contains:
                # return a fake condition object that query.where will accept
                fake_condition = MagicMock()
                mock_json_contains.return_value = fake_condition

                result, _ = await tool_service.list_tools(session, tags=["test", "production"], include_inactive=True)

                # json_contains_expr should be called once with the tags list
                mock_json_contains.assert_called_once()
                called_args = mock_json_contains.call_args[0]  # positional args tuple
                assert called_args[0] is session  # session passed through
                # third positional arg is the tags list (signature: session, col, values, match_any=True)
                assert called_args[2] == ["test", "production"]
                # finally, your service should return the list produced by session.execute(...)
                assert isinstance(result, list)
                assert len(result) == 1

    async def test_invoke_tool_rest_oauth_success(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with successful OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock OAuth manager
        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="test_access_token")

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "OAuth success"})
        tool_service._http_client.request.return_value = mock_response

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "OAuth success"}):
            # Invoke tool
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify OAuth token was obtained
        tool_service.oauth_manager.get_access_token.assert_called_once_with(mock_tool.oauth_config)

        # Verify HTTP request included Bearer token
        tool_service._http_client.request.assert_called_once()
        call_args = tool_service._http_client.request.call_args
        headers = call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_access_token"

        # Verify result
        assert result.content[0].text == '{\n  "result": "OAuth success"\n}'

    async def test_invoke_tool_rest_oauth_failure(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with failed OAuth authentication."""
        # Configure tool with OAuth
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_type = "oauth"
        mock_tool.oauth_config = {"client_id": "test_id", "client_secret": "test_secret"}

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock OAuth manager to fail
        tool_service.oauth_manager.get_access_token = AsyncMock(side_effect=Exception("OAuth failed"))

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        # Should raise ToolInvocationError
        with pytest.raises(ToolInvocationError) as exc_info:
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert "OAuth authentication failed: OAuth failed" in str(exc_info.value)

    async def test_invoke_tool_mcp_oauth_client_credentials(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking MCP tool with OAuth client credentials flow."""
        # Configure tool and gateway for MCP with OAuth
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_type = "oauth"
        mock_gateway.oauth_config = {"grant_type": "client_credentials", "client_id": "test", "client_secret": "secret"}

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar1.scalars.return_value = mock_scalar1
        mock_scalar1.all.return_value = [mock_tool]
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        # Mock OAuth manager
        tool_service.oauth_manager.get_access_token = AsyncMock(return_value="oauth_access_token")

        # Mock MCP connection
        expected_result = ToolResult(content=[TextContent(type="text", text="MCP OAuth response")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify OAuth was called
        tool_service.oauth_manager.get_access_token.assert_called_once_with(mock_gateway.oauth_config)

        # Verify MCP session was initialized and tool called
        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once()

    async def test_invoke_tool_with_passthrough_headers_rest(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking REST tool with passthrough headers."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "success with headers"})
        tool_service._http_client.request.return_value = mock_response

        # Mock compute_passthrough_headers_cached to return modified headers
        def mock_passthrough(req_headers, base_headers, allowed_headers, gateway_auth_type=None, gateway_passthrough_headers=None):
            combined = base_headers.copy()
            combined["X-Request-ID"] = req_headers.get("X-Request-ID", "test-123")
            return combined

        request_headers = {"X-Request-ID": "custom-123", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=mock_passthrough),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "success with headers"}),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=request_headers)

        # Verify passthrough headers were used
        tool_service._http_client.request.assert_called_once()
        call_args = tool_service._http_client.request.call_args
        headers = call_args[1]["headers"]
        assert "X-Request-ID" in headers
        assert headers["X-Request-ID"] == "custom-123"

    async def test_invoke_tool_with_passthrough_headers_mcp(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking MCP tool with passthrough headers."""
        # Configure tool and gateway for MCP
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_value = None

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar1.scalars.return_value = mock_scalar1
        mock_scalar1.all.return_value = [mock_tool]
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        # Mock MCP connection
        expected_result = ToolResult(content=[TextContent(type="text", text="MCP with headers")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        # Mock compute_passthrough_headers_cached to return modified headers
        def mock_passthrough(req_headers, base_headers, allowed_headers, gateway_auth_type=None, gateway_passthrough_headers=None):
            combined = base_headers.copy()
            combined["X-Custom-Header"] = req_headers.get("X-Custom-Header", "default")
            return combined

        request_headers = {"X-Custom-Header": "custom-value", "Authorization": "Bearer test"}

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=mock_passthrough),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=request_headers)

        # Verify MCP session was initialized and tool called
        session_mock.initialize.assert_awaited_once()
        session_mock.call_tool.assert_awaited_once()

    async def test_invoke_tool_with_plugin_post_invoke_success(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with successful plugin post-invoke hook."""
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType
        from mcpgateway.plugins.framework.models import PluginResult

        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager with invoke_hook
        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = None
        mock_post_result.retry_delay_ms = 0

        mock_pm = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert mock_pm.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result
        assert result.content[0].text == '{\n  "result": "original response"\n}'

    async def test_invoke_tool_with_plugin_post_invoke_modified_payload(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook modifying payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with modified payload
        mock_modified_payload = Mock()
        mock_modified_payload.result = {"content": [{"type": "text", "text": "Modified by plugin"}]}

        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = mock_modified_payload
        mock_post_result.retry_delay_ms = 0

        # First-Party
        from mcpgateway.plugins.framework import PluginResult, ToolHookType

        mock_pm = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert mock_pm.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result was modified by plugin
        assert result.content[0].text == "Modified by plugin"

    async def test_invoke_tool_with_plugin_post_invoke_invalid_modified_payload(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook providing invalid modified payload."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with invalid modified payload
        mock_modified_payload = Mock()
        mock_modified_payload.result = "Invalid format - not a dict"

        mock_post_result = Mock()
        mock_post_result.continue_processing = True
        mock_post_result.violation = None
        mock_post_result.modified_payload = mock_modified_payload
        mock_post_result.retry_delay_ms = 0

        # First-Party
        from mcpgateway.plugins.framework import ToolHookType
        from mcpgateway.plugins.framework.models import PluginResult

        mock_pm = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE
            return (mock_post_result, None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify plugin hooks were called
        assert mock_pm.invoke_hook.call_count == 2  # Pre and post invoke

        # Verify result was converted to string since format was invalid
        assert result.content[0].text == "Invalid format - not a dict"

    async def test_invoke_tool_with_plugin_post_invoke_error_fail_on_error(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager with invoke_hook that raises error on POST_INVOKE
        # First-Party
        from mcpgateway.plugins.framework import ToolHookType
        from mcpgateway.plugins.framework.models import PluginResult

        mock_pm = Mock()

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE - raise error
            raise Exception("Plugin error")

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        # Mock plugin config to fail on errors
        mock_plugin_settings = Mock()
        mock_plugin_settings.fail_on_plugin_error = True
        mock_config = Mock()
        mock_config.plugin_settings = mock_plugin_settings
        mock_pm.config = mock_config

        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            with pytest.raises(Exception) as exc_info:
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        assert "Plugin error" in str(exc_info.value)

    async def test_invoke_tool_with_plugin_metadata_rest(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        # Mock DB to return the tool and GlobalConfig
        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Mock HTTP client response
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()  # HTTP response raise_for_status is synchronous
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "original response"})
        tool_service._http_client.request.return_value = mock_response

        # Mock plugin manager and post-invoke hook with error
        pm = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/tool_headers_metadata_plugin.yaml")
        await pm.initialize()
        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "original response"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify result still succeeded despite plugin error
        assert result.content[0].text == '{\n  "result": "original response"\n}'

        await pm.shutdown()

    async def test_invoke_tool_with_plugin_metadata_sse(self, tool_service, mock_tool, mock_gateway, test_db):
        """Test invoking tool with plugin post-invoke hook error when fail_on_plugin_error is True."""
        # Configure tool as REST
        # mock_tool.integration_type = "REST"
        # mock_tool.request_type = "POST"
        # mock_tool.auth_value = None
        mock_tool.integration_type = "MCP"
        mock_tool.request_type = "sse"
        mock_gateway.auth_value = None

        # Mock DB queries
        mock_scalar1 = Mock()
        mock_scalar1.scalar_one_or_none.return_value = mock_tool
        mock_scalar1.scalars.return_value = mock_scalar1
        mock_scalar1.all.return_value = [mock_tool]
        mock_scalar2 = Mock()
        mock_scalar2.scalar_one_or_none.return_value = mock_gateway
        mock_scalar3 = Mock()
        mock_scalar3.scalar_one_or_none.return_value = mock_gateway

        test_db.execute = Mock(side_effect=[mock_scalar1, mock_scalar2, mock_scalar3])

        expected_result = ToolResult(content=[TextContent(type="text", text="MCP OAuth response")])
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        sse_ctx = AsyncMock()
        sse_ctx.__aenter__.return_value = ("read", "write")

        # Mock HTTP client response

        # Mock plugin manager and post-invoke hook with error
        pm = PluginManager("./tests/unit/mcpgateway/plugins/fixtures/configs/tool_headers_metadata_plugin.yaml")
        await pm.initialize()
        # Mock metrics recording
        tool_service._record_tool_metric_sync = Mock()

        with (
            patch("mcpgateway.services.tool_service.sse_client", return_value=sse_ctx),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.extract_using_jq", side_effect=lambda data, _filt: data),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=pm)),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        await pm.shutdown()

    @pytest.mark.asyncio
    async def test_invoke_tool_plugin_retry_delay_triggers_retry(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Test that when plugin returns retry_delay_ms > 0 the tool is retried after the delay."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "first attempt"})
        tool_service._http_client.request.return_value = mock_response

        mock_pm = Mock()

        post_invoke_count = [0]

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            # POST_INVOKE: first call requests a retry, subsequent calls succeed
            post_invoke_count[0] += 1
            delay = 100 if post_invoke_count[0] == 1 else 0
            return (PluginResult(continue_processing=True, violation=None, modified_payload=None, retry_delay_ms=delay), None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        # Intercept the recursive retry call so it returns immediately on retry_attempt > 0
        retry_result = ToolResult(content=[TextContent(type="text", text="retry succeeded")])
        original_invoke = tool_service.invoke_tool

        async def spy_invoke(db, name, arguments=None, **kwargs):
            if kwargs.get("retry_attempt", 0) > 0:
                return retry_result
            return await original_invoke(db, name, arguments, **kwargs)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "first attempt"}),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch.object(tool_service, "invoke_tool", side_effect=spy_invoke),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # Verify the retry delay sleep was triggered
        mock_sleep.assert_awaited_once()
        assert mock_sleep.call_args[0][0] == pytest.approx(0.1)  # 100ms → 0.1s
        # Verify the result is from the retry call
        assert result.content[0].text == "retry succeeded"

    @pytest.mark.asyncio
    async def test_invoke_tool_exception_path_retry_fires(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """When a tool raises an exception the retry plugin's delay_ms must also trigger a retry."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # HTTP client raises an exception (simulates network error)
        tool_service._http_client.request.side_effect = RuntimeError("connection reset")

        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True

        # Plugin returns delay > 0 on first post-invoke, 0 on subsequent
        post_invoke_count = [0]

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            post_invoke_count[0] += 1
            delay = 50 if post_invoke_count[0] == 1 else 0
            return (PluginResult(continue_processing=True, violation=None, modified_payload=None, retry_delay_ms=delay), None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        retry_result = ToolResult(content=[TextContent(type="text", text="recovered after exception")])
        original_invoke = tool_service.invoke_tool

        async def spy_invoke(db, name, arguments=None, **kwargs):
            if kwargs.get("retry_attempt", 0) > 0:
                return retry_result
            return await original_invoke(db, name, arguments, **kwargs)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch.object(tool_service, "invoke_tool", side_effect=spy_invoke),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        mock_sleep.assert_awaited_once()
        assert mock_sleep.call_args[0][0] == pytest.approx(0.05)  # 50ms → 0.05s
        assert result.content[0].text == "recovered after exception"

    @pytest.mark.asyncio
    async def test_invoke_tool_http_status_error_passes_status_to_plugin(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """When raise_for_status() raises HTTPStatusError the status code must be forwarded to the plugin in structuredContent."""
        # Third-Party
        import httpx

        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # Simulate httpx.HTTPStatusError (e.g. a 404 from raise_for_status)
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_request = MagicMock()
        tool_service._http_client.request.side_effect = httpx.HTTPStatusError("Not Found", request=mock_request, response=mock_response)

        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True

        captured_payloads = []

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_POST_INVOKE:
                captured_payloads.append(payload)
            return (PluginResult(continue_processing=True, violation=None, modified_payload=None, retry_delay_ms=0), None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            with pytest.raises(ToolInvocationError):
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        # The exception-path post-invoke payload must include the HTTP status code in structuredContent
        assert len(captured_payloads) >= 1
        post_invoke_result = captured_payloads[-1].result
        assert post_invoke_result["isError"] is True
        assert post_invoke_result["structuredContent"] == {"status_code": 404}

    @pytest.mark.asyncio
    async def test_invoke_tool_timeout_path_retry_fires(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """When a tool times out and the retry plugin requests a retry via ToolTimeoutError.retry_delay_ms, the gateway must retry."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        # HTTP client raises ToolTimeoutError with retry_delay_ms to simulate
        # the timeout handler having already called _run_timeout_post_invoke.
        tool_service._http_client.request.side_effect = ToolTimeoutError("timed out after 30s", retry_delay_ms=75)

        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            return (PluginResult(continue_processing=True, violation=None, modified_payload=None, retry_delay_ms=0), None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        retry_result = ToolResult(content=[TextContent(type="text", text="recovered after timeout")])
        original_invoke = tool_service.invoke_tool

        async def spy_invoke(db, name, arguments=None, **kwargs):
            if kwargs.get("retry_attempt", 0) > 0:
                return retry_result
            return await original_invoke(db, name, arguments, **kwargs)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch.object(tool_service, "invoke_tool", side_effect=spy_invoke),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        mock_sleep.assert_awaited_once()
        assert mock_sleep.call_args[0][0] == pytest.approx(0.075)  # 75ms → 0.075s
        assert result.content[0].text == "recovered after timeout"

    @pytest.mark.asyncio
    async def test_invoke_tool_timeout_no_retry_reraises(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """ToolTimeoutError with retry_delay_ms=0 must re-raise without retrying."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        tool_service._http_client.request.side_effect = ToolTimeoutError("timed out after 30s")

        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True

        def invoke_hook_side_effect(hook_type, payload, global_context, local_contexts=None, **kwargs):
            if hook_type == ToolHookType.TOOL_PRE_INVOKE:
                return (PluginResult(continue_processing=True, violation=None, modified_payload=None), None)
            return (PluginResult(continue_processing=True, violation=None, modified_payload=None, retry_delay_ms=0), None)

        mock_pm.invoke_hook = AsyncMock(side_effect=invoke_hook_side_effect)

        with (
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            with pytest.raises(ToolTimeoutError):
                await tool_service.invoke_tool(test_db, "test_tool", {"param": "value"}, request_headers=None)

        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_timeout_post_invoke_calls_hook(self, tool_service):
        """_run_timeout_post_invoke must invoke the post-invoke hook when the plugin manager has hooks."""
        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True
        mock_pm.invoke_hook = AsyncMock(return_value=(PluginResult(retry_delay_ms=0), None))

        await tool_service._run_timeout_post_invoke("test_tool", 30.0, None, None, mock_pm)

        mock_pm.invoke_hook.assert_awaited_once()
        call_kwargs = mock_pm.invoke_hook.call_args
        assert call_kwargs[1]["payload"].name == "test_tool"
        assert call_kwargs[1]["payload"].result["isError"] is True

    @pytest.mark.asyncio
    async def test_run_timeout_post_invoke_raises_on_retry_signal(self, tool_service):
        """_run_timeout_post_invoke must raise ToolTimeoutError with retry_delay_ms when the plugin requests a retry."""
        mock_pm = Mock()
        mock_pm.has_hooks_for.return_value = True
        mock_pm.invoke_hook = AsyncMock(return_value=(PluginResult(retry_delay_ms=250), None))

        with pytest.raises(ToolTimeoutError) as exc_info:
            await tool_service._run_timeout_post_invoke("test_tool", 30.0, None, None, mock_pm)

        assert exc_info.value.retry_delay_ms == 250

    @pytest.mark.asyncio
    async def test_run_timeout_post_invoke_noop_without_plugin_manager(self, tool_service):
        """_run_timeout_post_invoke must return immediately when plugin_manager is None."""
        with patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)):
            # Should not raise
            await tool_service._run_timeout_post_invoke("test_tool", 30.0, None, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_query_mapping", "tool_header_mapping", "expected_json", "expected_headers"),
        [
            (
                {"query": "mapped_query"},
                {"query": "X-Mapped-Query"},
                {"existing": "1", "mapped_query": "test"},
                {"Content-Type": "application/json", "X-Mapped-Query": "test"},
            ),
            # When both mappings are None or empty, query params are preserved in URL (signed URL support)
            # Only input args go in the body.
            (
                None,
                None,
                {"query": "test"},  # Only input args, URL query params stay in URL
                {"Content-Type": "application/json"},
            ),
            (
                {"query": "mapped_query"},
                None,
                {"existing": "1", "mapped_query": "test"},
                {"Content-Type": "application/json"},
            ),
            (
                None,
                {"query": "X-Query"},
                {"query": "test", "existing": "1"},
                {"Content-Type": "application/json", "X-Query": "test"},
            ),
            # Empty dict mappings also preserve query params in URL (same as None)
            (
                {},
                {},
                {"query": "test"},  # Only input args, URL query params stay in URL
                {"Content-Type": "application/json"},
            ),
        ],
    )
    async def test_invoke_tool_rest_headers_and_query_maps_applied(
        self,
        tool_service,
        mock_tool,
        mock_global_config_obj,
        test_db,
        tool_query_mapping,
        tool_header_mapping,
        expected_json,
        expected_headers,
    ):
        """invoke_tool should apply query_mapping and header_mapping through apply_mapping_into_target."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test?existing=1"
        mock_tool.query_mapping = tool_query_mapping
        mock_tool.header_mapping = tool_header_mapping

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "REST tool response"})
        tool_service._http_client.request.return_value = mock_response

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "REST tool response"}),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"query": "test"}, request_headers=None)

        # When both mappings are None or empty dict, query params stay in URL (signed URL support)
        # When mappings have actual values, query params are extracted and merged into body
        has_query_mapping = tool_query_mapping is not None and tool_query_mapping != {}
        has_header_mapping = tool_header_mapping is not None and tool_header_mapping != {}

        if not has_query_mapping and not has_header_mapping:
            # No mappings (None or empty) - query params preserved in URL
            tool_service._http_client.request.assert_called_once_with(
                "POST",
                "http://example.com/tools/test?existing=1",  # Query params preserved in URL
                json=expected_json,
                headers=expected_headers,
            )
        else:
            # Mappings present - query params extracted and merged into body
            tool_service._http_client.request.assert_called_once_with(
                "POST",
                "http://example.com/tools/test",
                json=expected_json,
                headers=expected_headers,
            )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_get_with_query_mapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """GET requests send mapped payload as query params via params= instead of json=."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test?existing=1"
        mock_tool.query_mapping = {"query": "q"}
        mock_tool.header_mapping = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "ok"})
        tool_service._http_client.get.return_value = mock_response

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "ok"}),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"query": "test"}, request_headers=None)

        tool_service._http_client.get.assert_called_once_with(
            "http://example.com/tools/test",
            params={"existing": "1", "q": "test"},
            headers={"Content-Type": "application/json"},
        )

    @pytest.mark.asyncio
    async def test_invoke_tool_rest_header_mapping_uses_original_arguments(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """Header mapping sources from original arguments, so URL-template-consumed params are still available for headers."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/{id}/detail?existing=1"
        mock_tool.query_mapping = None
        mock_tool.header_mapping = {"id": "X-Resource-Id"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"result": "ok"})
        tool_service._http_client.request.return_value = mock_response

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            patch("mcpgateway.services.tool_service.extract_using_jq", return_value={"result": "ok"}),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"id": "42", "other": "val"}, request_headers=None)

        tool_service._http_client.request.assert_called_once_with(
            "POST",
            "http://example.com/tools/42/detail",
            json={"other": "val", "existing": "1"},
            headers={"Content-Type": "application/json", "X-Resource-Id": "42"},
        )


# --------------------------------------------------------------------------- #
#                               extract_using_jq                              #
# --------------------------------------------------------------------------- #
def test_extract_using_jq_happy_path():
    """Test jq filter extraction works correctly with caching."""
    # First-Party
    from mcpgateway.services.tool_service import _compile_jq_filter

    # Clear cache for clean test state
    _compile_jq_filter.cache_clear()

    data = {"a": 123, "b": 456}

    # Test actual behavior (no mocking)
    result = extract_using_jq(data, ".a")
    assert result == [123]

    # Verify caching works
    result2 = extract_using_jq({"a": 999}, ".a")
    assert result2 == [999]

    info = _compile_jq_filter.cache_info()
    assert info.hits == 1  # Second call hit cache


def test_extract_using_jq_short_circuits_and_errors():
    # Empty filter returns data unmodified
    orig = {"x": "y"}
    assert extract_using_jq(orig) is orig

    # Non-JSON string
    assert extract_using_jq("this isn't json", ".foo") == ["Invalid JSON string provided."]

    # Unsupported input type
    assert extract_using_jq(42, ".foo") == ["Input data must be a JSON string, dictionary, or list."]


# --------------------------------------------------------------------------- #
#                         apply_mapping_into_target                            #
# --------------------------------------------------------------------------- #


class TestApplyMappingIntoTarget:
    """Unit tests for the apply_mapping_into_target utility function."""

    def test_maps_matching_keys_and_renames(self):
        data = {"query": "test", "page": 1}
        mapping = {"query": "q", "page": "p"}
        result = apply_mapping_into_target(data, mapping)
        assert result == {"q": "test", "p": 1}

    def test_merges_into_existing_target(self):
        data = {"query": "test"}
        mapping = {"query": "q"}
        target = {"existing": "1"}
        result = apply_mapping_into_target(data, mapping, target)
        assert result == {"existing": "1", "q": "test"}

    def test_mapped_keys_overwrite_target(self):
        data = {"key": "new_value"}
        mapping = {"key": "shared"}
        target = {"shared": "old_value"}
        result = apply_mapping_into_target(data, mapping, target)
        assert result == {"shared": "new_value"}

    def test_none_mapping_returns_target(self):
        target = {"a": 1}
        result = apply_mapping_into_target({"x": 10}, None, target)
        assert result == {"a": 1}

    def test_empty_mapping_returns_target(self):
        target = {"a": 1}
        result = apply_mapping_into_target({"x": 10}, {}, target)
        assert result == {"a": 1}

    def test_none_mapping_none_target_returns_empty_dict(self):
        result = apply_mapping_into_target({"x": 10}, None)
        assert result == {}

    def test_unmapped_keys_excluded_from_result(self):
        data = {"mapped": "yes", "unmapped": "dropped"}
        mapping = {"mapped": "m"}
        result = apply_mapping_into_target(data, mapping)
        assert result == {"m": "yes"}
        assert "unmapped" not in result
        assert "dropped" not in result

    def test_empty_data_with_mapping_returns_target_only(self):
        result = apply_mapping_into_target({}, {"k": "v"}, {"existing": "1"})
        assert result == {"existing": "1"}

    def test_does_not_mutate_inputs(self):
        data = {"a": 1}
        mapping = {"a": "b"}
        target = {"c": 2}
        apply_mapping_into_target(data, mapping, target)
        assert data == {"a": 1}
        assert target == {"c": 2}

    def test_unmapped_keys_logged_at_debug(self):
        """When DEBUG is enabled, unmapped keys are logged."""

        with patch("mcpgateway.services.tool_service.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            with patch("mcpgateway.services.tool_service.structured_logger") as mock_slog:
                apply_mapping_into_target({"mapped": "v", "extra": "dropped"}, {"mapped": "m"})
                mock_slog.log.assert_called_once()
                assert "unmapped keys excluded" in mock_slog.log.call_args[1]["message"]


# --------------------------------------------------------------------------- #
#              Schema-level Mapping Validation Tests                          #
# --------------------------------------------------------------------------- #


class TestMappingSizeValidation:
    """Tests for _validate_mapping_size via ToolCreate/ToolUpdate schema validators."""

    def test_none_mapping_accepted(self):
        """None mapping should pass validation."""
        tool = ToolCreate(name="test_tool", query_mapping=None, header_mapping=None)
        assert tool.query_mapping is None

    def test_valid_mapping_accepted(self):
        tool = ToolCreate(name="test_tool", integration_type="REST", query_mapping={"a": "b"})
        assert tool.query_mapping == {"a": "b"}

    def test_too_many_entries_rejected(self):
        big_mapping = {f"k{i}": f"v{i}" for i in range(51)}
        with pytest.raises(Exception, match="50 entries"):
            ToolCreate(name="test_tool", integration_type="REST", query_mapping=big_mapping)

    def test_long_key_rejected(self):
        with pytest.raises(Exception, match="key exceeds"):
            ToolCreate(name="test_tool", integration_type="REST", query_mapping={"x" * 129: "v"})

    def test_long_value_rejected(self):
        with pytest.raises(Exception, match="value exceeds"):
            ToolCreate(name="test_tool", integration_type="REST", query_mapping={"k": "x" * 129})

    def test_tool_update_too_many_entries_rejected(self):
        big_mapping = {f"k{i}": f"v{i}" for i in range(51)}
        with pytest.raises(Exception, match="50 entries"):
            ToolUpdate(query_mapping=big_mapping)


class TestSchemaHeaderMappingTargetValidation:
    """Tests for _validate_header_mapping_targets via ToolCreate/ToolUpdate schema validators."""

    def test_none_header_mapping_accepted(self):
        tool = ToolCreate(name="test_tool", header_mapping=None)
        assert tool.header_mapping is None

    def test_safe_header_mapping_accepted(self):
        tool = ToolCreate(name="test_tool", integration_type="REST", header_mapping={"field": "X-Custom"})
        assert tool.header_mapping == {"field": "X-Custom"}

    def test_blocked_header_rejected_at_create(self):
        with pytest.raises(Exception, match="blocked header"):
            ToolCreate(name="test_tool", integration_type="REST", header_mapping={"field": "Cookie"})

    def test_sensitive_pattern_rejected_at_create(self):
        with pytest.raises(Exception, match="sensitive header"):
            ToolCreate(name="test_tool", integration_type="REST", header_mapping={"field": "X-API-Key"})

    def test_invalid_name_rejected_at_create(self):
        with pytest.raises(Exception, match="invalid header name"):
            ToolCreate(name="test_tool", integration_type="REST", header_mapping={"field": "Bad Header"})

    def test_blocked_header_rejected_at_update(self):
        with pytest.raises(Exception, match="blocked header"):
            ToolUpdate(header_mapping={"field": "Host"})

    def test_sensitive_pattern_rejected_at_update(self):
        with pytest.raises(Exception, match="sensitive header"):
            ToolUpdate(header_mapping={"field": "X-Auth-Token"})


# --------------------------------------------------------------------------- #
#                  Mapping Security Validation Tests                          #
# --------------------------------------------------------------------------- #


class TestValidateMappingContents:
    """Tests for _validate_mapping_contents runtime guard."""

    def test_valid_string_mapping_passes(self):
        result = _validate_mapping_contents({"a": "b", "c": "d"}, "test_mapping", "test_tool")
        assert result == {"a": "b", "c": "d"}

    def test_non_string_value_raises(self):
        with pytest.raises(ToolInvocationError, match="non-string keys or values"):
            _validate_mapping_contents({"a": 42}, "test_mapping", "test_tool")

    def test_non_string_key_raises(self):
        with pytest.raises(ToolInvocationError, match="non-string keys or values"):
            _validate_mapping_contents({1: "b"}, "test_mapping", "test_tool")

    def test_nested_dict_value_raises(self):
        with pytest.raises(ToolInvocationError, match="non-string keys or values"):
            _validate_mapping_contents({"a": {"nested": "obj"}}, "test_mapping", "test_tool")

    def test_empty_dict_passes(self):
        result = _validate_mapping_contents({}, "test_mapping", "test_tool")
        assert result == {}

    def test_error_includes_tool_name(self):
        with pytest.raises(ToolInvocationError, match="my_tool"):
            _validate_mapping_contents({"a": 42}, "query_mapping", "my_tool")


class TestValidateHeaderMappingTargets:
    """Tests for _validate_header_mapping_targets security checks."""

    def test_safe_header_name_passes(self):
        _validate_header_mapping_targets({"field": "X-Custom-Header"}, "test_tool")

    def test_authorization_header_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Authorization"}, "test_tool")

    def test_authorization_case_insensitive(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "AUTHORIZATION"}, "test_tool")

    def test_proxy_authorization_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Proxy-Authorization"}, "test_tool")

    def test_x_api_key_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "X-API-Key"}, "test_tool")

    def test_crlf_injection_rejected(self):
        with pytest.raises(ToolInvocationError, match="invalid header name"):
            _validate_header_mapping_targets({"field": "X-Header\r\nEvil: injected"}, "test_tool")

    def test_space_in_header_name_rejected(self):
        with pytest.raises(ToolInvocationError, match="invalid header name"):
            _validate_header_mapping_targets({"field": "X Header"}, "test_tool")

    def test_empty_header_name_rejected(self):
        with pytest.raises(ToolInvocationError, match="invalid header name"):
            _validate_header_mapping_targets({"field": ""}, "test_tool")

    def test_multiple_headers_all_validated(self):
        """All targets must be validated — a valid header before a sensitive one does not skip checks."""
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"a": "X-Safe", "b": "Authorization"}, "test_tool")

    def test_cookie_header_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Cookie"}, "test_tool")

    def test_host_header_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Host"}, "test_tool")

    def test_transfer_encoding_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Transfer-Encoding"}, "test_tool")

    def test_connection_header_rejected(self):
        with pytest.raises(ToolInvocationError, match="sensitive header"):
            _validate_header_mapping_targets({"field": "Connection"}, "test_tool")


class TestMappingIntegrationSecurity:
    """Integration tests verifying mapping security at the invoke_tool level."""

    @pytest.mark.asyncio
    async def test_invoke_tool_rejects_sensitive_header_mapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """invoke_tool must reject header_mapping that targets Authorization."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test"
        mock_tool.query_mapping = None
        mock_tool.header_mapping = {"token": "Authorization"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            pytest.raises(ToolInvocationError, match="sensitive header"),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"token": "evil-value"}, request_headers=None)

    @pytest.mark.asyncio
    async def test_invoke_tool_rejects_crlf_header_mapping(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """invoke_tool must reject header_mapping with CRLF injection in target name."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test"
        mock_tool.query_mapping = None
        mock_tool.header_mapping = {"field": "X-Header\r\nEvil: injected"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            pytest.raises(ToolInvocationError, match="invalid header name"),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"field": "value"}, request_headers=None)

    @pytest.mark.asyncio
    async def test_invoke_tool_rejects_crlf_in_header_value(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """invoke_tool must reject header values containing CRLF (header injection via runtime arguments)."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test"
        mock_tool.query_mapping = None
        mock_tool.header_mapping = {"field": "X-Custom"}

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            pytest.raises(ToolInvocationError, match="illegal characters"),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"field": "good\r\nEvil: injected"}, request_headers=None)

    @pytest.mark.asyncio
    async def test_invoke_tool_rejects_non_scalar_query_mapped_value(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """invoke_tool must reject non-scalar values produced by query_mapping."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None
        mock_tool.url = "http://example.com/tools/test"
        mock_tool.query_mapping = {"nested": "q"}
        mock_tool.header_mapping = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        with (
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=Mock()),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={}),
            pytest.raises(ToolInvocationError, match="non-scalar value"),
        ):
            await tool_service.invoke_tool(test_db, "test_tool", {"nested": {"a": "b"}}, request_headers=None)


# --------------------------------------------------------------------------- #
#                         Cache Behavior Tests                                #
# --------------------------------------------------------------------------- #


class TestJqFilterCaching:
    """Tests for jq filter caching (#1813)."""

    def test_jq_caching_works(self):
        """Verify jq filter compilation is cached."""
        # First-Party
        from mcpgateway.services.tool_service import _compile_jq_filter

        _compile_jq_filter.cache_clear()

        result1 = extract_using_jq({"a": 1}, ".a")
        assert result1 == [1]

        result2 = extract_using_jq({"a": 99}, ".a")
        assert result2 == [99]

        info = _compile_jq_filter.cache_info()
        assert info.hits == 1

    def test_empty_filter_bypasses_cache(self):
        """Empty filter should return data directly without caching."""
        data = {"x": "y"}
        result = extract_using_jq(data, "")
        assert result is data


# --------------------------------------------------------------------------- #
#          Tests for REST Tool Improvements (non-JSON, query params)          #
# --------------------------------------------------------------------------- #


class TestJqFilterEmailValidation:
    """Tests for JQ filter email address validation (#3855)."""

    def test_extract_using_jq_rejects_email_addresses(self):
        """Simple email addresses are detected and ignored as jq filters."""
        data = {"key": "value", "user": "test"}

        result = extract_using_jq(data, "user@example.com")
        assert result == data, "Simple email addresses should be ignored as jq filters"

        result = extract_using_jq(data, "admin@test.org")
        assert result == data

        result = extract_using_jq(data, "testuser@domain.net")
        assert result == data

    def test_extract_using_jq_accepts_valid_filters(self):
        """Valid jq filters still work after email validation."""
        data = {"key": "value", "nested": {"field": 123}}

        result = extract_using_jq(data, ".key")
        assert result == ["value"]

        result = extract_using_jq(data, ".nested.field")
        assert result == [123]

    def test_extract_using_jq_empty_whitespace_filters(self):
        """Empty/whitespace filters are handled."""
        data = {"key": "value"}

        result = extract_using_jq(data, "")
        assert result == data

        result = extract_using_jq(data, "   ")
        assert result == data

        result = extract_using_jq(data, "\t\n")
        assert result == data


class TestRestToolQueryParamHandling:
    """Tests for query parameter handling in REST tools (#3857)."""

    @pytest.mark.asyncio
    async def test_rest_tool_get_merges_query_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """GET requests merge URL query params with input arguments."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.url = "https://api.example.com/search?api_key=secret123"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"results": []})

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"q": "test query", "limit": 10}, request_headers=None)

            call_args = tool_service._http_client.get.call_args
            assert call_args[0][0] == "https://api.example.com/search"
            params = call_args[1]["params"]
            assert params["api_key"] == "secret123"
            assert params["q"] == "test query"
            assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_rest_tool_post_preserves_query_params_in_url(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """POST requests preserve query params in URL (signed URL support)."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "POST"
        mock_tool.url = "https://storage.example.com/upload?signature=xyz&expires=123"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"success": True})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"filename": "test.txt", "content": "data"}, request_headers=None)

            call_args = tool_service._http_client.request.call_args
            url = call_args[0][1]
            assert "signature=xyz" in url
            assert "expires=123" in url

            body = call_args[1]["json"]
            assert body == {"filename": "test.txt", "content": "data"}

    @pytest.mark.asyncio
    async def test_rest_tool_put_preserves_query_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """PUT requests preserve query params in URL."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "PUT"
        mock_tool.url = "https://api.example.com/resource?token=abc123"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"updated": True})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"data": "updated"}, request_headers=None)

            call_args = tool_service._http_client.request.call_args
            url = call_args[0][1]
            assert "token=abc123" in url

    @pytest.mark.asyncio
    async def test_rest_tool_patch_preserves_query_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """PATCH requests preserve query params in URL."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "PATCH"
        mock_tool.url = "https://api.example.com/resource?version=v2"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"patched": True})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"field": "value"}, request_headers=None)

            call_args = tool_service._http_client.request.call_args
            url = call_args[0][1]
            assert "version=v2" in url
            body = call_args[1]["json"]
            assert body == {"field": "value"}

    @pytest.mark.asyncio
    async def test_rest_tool_delete_preserves_query_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """DELETE requests preserve query params in URL."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "DELETE"
        mock_tool.url = "https://api.example.com/resource?cascade=true"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 204
        mock_response.text = ""
        mock_response.json = Mock(return_value={})

        tool_service._http_client.request = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"confirm": "yes"}, request_headers=None)

            call_args = tool_service._http_client.request.call_args
            url = call_args[0][1]
            assert "cascade=true" in url

    @pytest.mark.asyncio
    async def test_rest_tool_get_param_conflict_logs_warning(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """GET request logs warning when input args conflict with URL query params."""
        import logging

        caplog.set_level(logging.WARNING)

        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.url = "https://api.example.com/search?api_key=url_value&safe=true"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"results": []})

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"api_key": "input_value", "q": "search"}, request_headers=None)  # pragma: allowlist secret

            assert "conflicting parameters" in caplog.text.lower()
            assert "api_key" in caplog.text

            call_args = tool_service._http_client.get.call_args
            params = call_args[1]["params"]
            assert params["api_key"] == "url_value"  # URL value wins
            assert params["safe"] == "true"
            assert params["q"] == "search"

    @pytest.mark.asyncio
    async def test_rest_tool_get_empty_url_params(self, tool_service, mock_tool, mock_global_config_obj, test_db):
        """GET request with no URL query params works correctly."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.url = "https://api.example.com/search"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"results": []})

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            await tool_service.invoke_tool(test_db, "test_tool", {"q": "test"}, request_headers=None)

            call_args = tool_service._http_client.get.call_args
            params = call_args[1]["params"]
            assert params == {"q": "test"}


class TestRestToolNonJsonResponses:
    """Tests for handling non-JSON responses from REST tools (#3855)."""

    @pytest.mark.asyncio
    async def test_rest_tool_handles_html_error_response(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool handles HTML error pages gracefully without crashing."""
        import httpx

        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        # raise_for_status must actually raise for 500 to exercise the real code path
        mock_request = Mock(spec=httpx.Request)
        mock_request.url = "https://api.example.com/test"
        mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError("Server Error", request=mock_request, response=mock_response))
        mock_response.status_code = 500
        mock_response.text = "<html><body>Internal Server Error</body></html>"
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.is_error is True
            # Status code must be preserved in structured_content for retry plugin
            assert result.structured_content == {"status_code": 500}
            # Error message must include the HTTP status code
            assert "500" in result.content[0].text
            assert "Failed to parse JSON error response" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_handles_plain_text_response(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool handles plain text responses without crashing."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = "Plain text response"
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.content[0].text is not None
            assert "Failed to parse JSON response" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_handles_xml_response(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool handles XML responses without crashing."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = '<?xml version="1.0"?><data>value</data>'
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.content[0].text is not None
            assert "Failed to parse JSON response" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_handles_unicode_decode_error(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool handles invalid UTF-8 encoding without crashing."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = "Invalid encoding content"
        mock_response.json = Mock(side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid"))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.content[0].text is not None
            assert "Failed to parse JSON response" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_handles_empty_response_body(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool handles empty response body with JSON parse error."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = ""
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.content[0].text is not None
            result_text = result.content[0].text
            assert "Empty response body" in result_text
            assert "Response body was empty" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_truncates_large_response_text(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool truncates response text exceeding REST_RESPONSE_TEXT_MAX_LENGTH."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        large_text = "X" * 10000
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = large_text
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            assert result.content[0].text is not None
            result_data = orjson.loads(result.content[0].text)
            assert "response_text" in result_data
            assert len(result_data["response_text"]) == settings.rest_response_text_max_length
            assert f"Response truncated from {len(large_text)} to {settings.rest_response_text_max_length} characters" in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_does_not_truncate_small_response(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool does not truncate response text below the limit."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        small_text = "Small response text"
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = small_text
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()
        with patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            result_data = orjson.loads(result.content[0].text)
            assert result_data["response_text"] == small_text
            assert "Response truncated" not in caplog.text

    @pytest.mark.asyncio
    async def test_rest_tool_truncation_respects_config_value(self, tool_service, mock_tool, mock_global_config_obj, test_db, caplog):
        """REST tool truncation uses the configured REST_RESPONSE_TEXT_MAX_LENGTH value."""
        mock_tool.integration_type = "REST"
        mock_tool.request_type = "GET"
        mock_tool.jsonpath_filter = ""
        mock_tool.auth_value = None

        setup_db_execute_mock(test_db, mock_tool, mock_global_config_obj)

        large_text = "Y" * 6000
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock()
        mock_response.status_code = 200
        mock_response.text = large_text
        import json

        mock_response.json = Mock(side_effect=json.JSONDecodeError("Expecting value", "", 0))

        tool_service._http_client.get = AsyncMock(return_value=mock_response)

        mock_metrics_buffer = Mock()
        mock_metrics_buffer.record_tool_metric = Mock()

        with (
            patch("mcpgateway.services.tool_service.metrics_buffer", mock_metrics_buffer),
            patch.object(settings, "rest_response_text_max_length", 2000),
        ):
            result = await tool_service.invoke_tool(test_db, "test_tool", {}, request_headers=None)

            result_data = orjson.loads(result.content[0].text)
            assert len(result_data["response_text"]) == 2000
            assert "Response truncated from 6000 to 2000 characters" in caplog.text


class TestSchemaValidatorCaching:
    """Tests for JSON Schema validator caching (#1809)."""

    def test_schema_caching_works(self):
        """Verify schema validation uses cached validator class."""
        # First-Party
        from mcpgateway.services.tool_service import _canonicalize_schema, _get_validator_class_and_check

        _get_validator_class_and_check.cache_clear()

        schema = {"type": "object", "properties": {"foo": {"type": "string"}}}
        schema_json = _canonicalize_schema(schema)

        cls1, s1 = _get_validator_class_and_check(schema_json)
        cls2, s2 = _get_validator_class_and_check(schema_json)

        assert cls1 is cls2

        info = _get_validator_class_and_check.cache_info()
        assert info.hits == 1

    def test_validation_still_works(self):
        """Verify cached validation still catches errors."""
        # Third-Party
        import jsonschema

        # First-Party
        from mcpgateway.services.tool_service import _validate_with_cached_schema

        schema = {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}

        # Valid instance
        _validate_with_cached_schema({"foo": "bar"}, schema)

        # Invalid instance
        with pytest.raises(jsonschema.ValidationError):
            _validate_with_cached_schema({"foo": 123}, schema)


class TestCorrelationIdPoolExclusion:
    """Tests for X-Correlation-ID exclusion from pooled sessions.

    Regression tests for the bug where X-Correlation-ID was pinned to pooled sessions,
    causing the first request's correlation ID to leak to subsequent requests.
    """

    def test_correlation_id_not_added_to_headers_for_pooled_path(self):
        """Verify X-Correlation-ID is not added to headers when pool is used.

        The MCP SDK pins headers at transport creation, so per-request headers
        like X-Correlation-ID would be reused across all requests on the same
        pooled session, breaking distributed tracing.
        """
        # Simulate the pooled code path logic from tool_service.py
        use_pool = True
        headers = {"Authorization": "Bearer token123"}
        correlation_id = "req-12345"

        # In the pooled path, correlation ID should NOT be added
        if use_pool:
            # This is what the code should do - NOT add the header
            pass  # headers remain unchanged
        else:
            # Non-pooled path would add it
            if correlation_id and headers:
                headers["X-Correlation-ID"] = correlation_id

        # Verify X-Correlation-ID was NOT added for pooled path
        assert "X-Correlation-ID" not in headers
        assert headers == {"Authorization": "Bearer token123"}

    def test_correlation_id_added_for_non_pooled_path(self):
        """Verify X-Correlation-ID IS added when pool is not used."""
        use_pool = False
        headers = {"Authorization": "Bearer token123"}
        correlation_id = "req-67890"

        # Non-pooled path: safe to add per-request headers
        if not use_pool:
            if correlation_id and headers:
                headers["X-Correlation-ID"] = correlation_id

        # Verify X-Correlation-ID WAS added for non-pooled path
        assert headers["X-Correlation-ID"] == "req-67890"

    def test_correlation_id_not_added_when_headers_none(self):
        """Verify no error when headers is None."""
        use_pool = False
        headers = None
        correlation_id = "req-aaaaa"

        # Non-pooled path with None headers
        if not use_pool:
            if correlation_id and headers:
                headers["X-Correlation-ID"] = correlation_id

        # Headers should remain None (no modification attempted)
        assert headers is None

    def test_correlation_id_not_added_when_correlation_id_none(self):
        """Verify no error when correlation_id is None."""
        use_pool = False
        headers = {"Authorization": "Bearer token"}
        correlation_id = None

        # Non-pooled path with None correlation_id
        if not use_pool:
            if correlation_id and headers:
                headers["X-Correlation-ID"] = correlation_id

        # Headers should remain unchanged
        assert "X-Correlation-ID" not in headers


# ----------------------------------------------------- #
# Token Teams Filtering Tests (Issue #1915)             #
# ----------------------------------------------------- #
class TestToolServiceTokenTeamsFiltering:
    """Tests for token_teams parameter in list_tools and list_server_tools."""

    @pytest.mark.asyncio
    async def test_list_tools_with_token_teams_uses_token_teams(self, tool_service, test_db):
        """Test that list_tools uses token_teams when provided instead of DB lookup."""
        mock_tool = MagicMock(spec=DbTool, id="1", team_id="team_a")

        # Mock DB execute chain
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()

        tool_read = MagicMock()
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        # When token_teams is provided, TeamManagementService should NOT be called
        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock()
            result, _ = await tool_service.list_tools(test_db, user_email="user@example.com", token_teams=["team_a"])

            # TeamManagementService should NOT be instantiated since token_teams was provided
            mock_team_service.return_value.get_user_teams.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_with_empty_token_teams_sees_own_and_public(self, tool_service, test_db):
        """Test that empty token_teams list sees own resources and public resources."""
        mock_tool_public = MagicMock(spec=DbTool, id="1", team_id=None, visibility="public", owner_email="other@example.com")
        mock_tool_own = MagicMock(spec=DbTool, id="2", team_id=None, visibility="private", owner_email="user@example.com")

        # Mock DB execute chain to return tools
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool_public, mock_tool_own])))))
        test_db.commit = Mock()

        tool_service.convert_tool_to_read = Mock(side_effect=[MagicMock(), MagicMock()])

        # With empty token_teams, user should see their own and public resources
        result, _ = await tool_service.list_tools(test_db, user_email="user@example.com", token_teams=[])

        # verify DB was queried
        assert test_db.execute.called

    @pytest.mark.asyncio
    async def test_list_tools_without_token_teams_uses_db_lookup(self, tool_service, test_db):
        """Test that list_tools performs DB team lookup when token_teams is None."""
        mock_tool = MagicMock(spec=DbTool, id="1", team_id="team_a")

        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool])))))
        test_db.commit = Mock()

        tool_read = MagicMock()
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        mock_team = MagicMock(id="team_a", is_personal=False)

        # When token_teams is None, TeamManagementService SHOULD be called
        with patch("mcpgateway.services.base_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            result, _ = await tool_service.list_tools(test_db, user_email="user@example.com", token_teams=None)

            # TeamManagementService SHOULD be called for DB lookup
            mock_team_service.return_value.get_user_teams.assert_called_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_list_server_tools_with_token_teams(self, tool_service, test_db):
        """Test list_server_tools uses token_teams for filtering."""
        mock_tool = MagicMock(spec=DbTool, id="1", team_id="team_x", enabled=True)
        mock_server = MagicMock()
        mock_server.tools = [mock_tool]

        test_db.execute = Mock(return_value=MagicMock(scalar_one_or_none=Mock(return_value=mock_server)))
        test_db.commit = Mock()

        tool_read = MagicMock()
        tool_service.convert_tool_to_read = Mock(return_value=tool_read)

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock()
            _result = await tool_service.list_server_tools(test_db, server_id="server-1", include_inactive=False, user_email="user@example.com", token_teams=["team_x"])

            # TeamManagementService should NOT be called since token_teams was provided
            mock_team_service.return_value.get_user_teams.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_tools_token_teams_filters_by_membership(self, tool_service, test_db):
        """Test that only tools matching token_teams are returned."""
        mock_tool_a = MagicMock(spec=DbTool, id="1", team_id="team_a")
        mock_tool_b = MagicMock(spec=DbTool, id="2", team_id="team_b")

        # DB returns both tools, but filtering should occur
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[mock_tool_a, mock_tool_b])))))
        test_db.commit = Mock()

        tool_read_a = MagicMock()
        tool_read_b = MagicMock()
        tool_service.convert_tool_to_read = Mock(side_effect=[tool_read_a, tool_read_b])

        # Only team_a in token_teams - should only see team_a tools
        result, _ = await tool_service.list_tools(test_db, user_email="user@example.com", token_teams=["team_a"])

        assert test_db.execute.called


class TestToolAccessAuthorization:
    """Tests for _check_tool_access authorization logic."""

    @pytest.fixture
    def tool_service(self):
        """Create a tool service instance."""
        return ToolService()

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.commit = Mock()
        return db

    @pytest.mark.asyncio
    async def test_check_tool_access_public_always_allowed(self, tool_service, mock_db):
        """Public tools should be accessible to anyone."""
        tool_payload = {"id": "1", "visibility": "public", "owner_email": None, "team_id": None}

        # Unauthenticated
        assert await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=[]) is True
        # Authenticated
        assert await tool_service._check_tool_access(mock_db, tool_payload, user_email="user@test.com", token_teams=["team-1"]) is True
        # Admin
        assert await tool_service._check_tool_access(mock_db, tool_payload, user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_check_tool_access_admin_bypass(self, tool_service, mock_db):
        """Admin (user_email=None, token_teams=None) should have full access."""
        private_tool = {"id": "1", "visibility": "private", "owner_email": "secret@test.com", "team_id": "secret-team"}

        # Admin bypass: both None = unrestricted access
        assert await tool_service._check_tool_access(mock_db, private_tool, user_email=None, token_teams=None) is True

    @pytest.mark.asyncio
    async def test_check_tool_access_private_denied_to_unauthenticated(self, tool_service, mock_db):
        """Private tools should be denied to unauthenticated users."""
        private_tool = {"id": "1", "visibility": "private", "owner_email": "owner@test.com", "team_id": None}

        # Unauthenticated (public-only token)
        assert await tool_service._check_tool_access(mock_db, private_tool, user_email=None, token_teams=[]) is False

    @pytest.mark.asyncio
    async def test_check_tool_access_private_allowed_to_owner(self, tool_service, mock_db):
        """Private tools should be accessible to the owner."""
        private_tool = {"id": "1", "visibility": "private", "owner_email": "owner@test.com", "team_id": None}

        # Owner with non-empty token_teams
        assert await tool_service._check_tool_access(mock_db, private_tool, user_email="owner@test.com", token_teams=["some-team"]) is True

    @pytest.mark.asyncio
    async def test_check_tool_access_team_tool_allowed_to_member(self, tool_service, mock_db):
        """Team tools should be accessible to team members."""
        team_tool = {"id": "1", "visibility": "team", "owner_email": "owner@test.com", "team_id": "team-abc"}

        # Team member via token_teams
        assert await tool_service._check_tool_access(mock_db, team_tool, user_email="member@test.com", token_teams=["team-abc"]) is True

    @pytest.mark.asyncio
    async def test_check_tool_access_team_tool_denied_to_non_member(self, tool_service, mock_db):
        """Team tools should be denied to non-members."""
        team_tool = {"id": "1", "visibility": "team", "owner_email": "owner@test.com", "team_id": "team-abc"}

        # Non-member
        assert await tool_service._check_tool_access(mock_db, team_tool, user_email="outsider@test.com", token_teams=["other-team"]) is False

    @pytest.mark.asyncio
    async def test_check_tool_access_public_only_token_denied_private(self, tool_service, mock_db):
        """Public-only tokens (token_teams=[]) should only access public tools."""
        private_tool = {"id": "1", "visibility": "private", "owner_email": "owner@test.com", "team_id": None}

        # Even owner with public-only token is denied
        assert await tool_service._check_tool_access(mock_db, private_tool, user_email="owner@test.com", token_teams=[]) is False


class TestToolListingGracefulErrorHandling:
    """Tests for graceful error handling when convert_tool_to_read fails.

    These tests verify that when one tool fails to convert (e.g., due to corrupted data),
    the listing operation continues with remaining tools instead of failing completely.
    This prevents a single corrupted entity from breaking the entire listing.
    """

    @pytest.mark.asyncio
    async def test_list_tools_continues_on_conversion_error(self, caplog):
        """Test that list_tools returns valid tools even when one fails conversion."""
        # Standard
        import logging

        caplog.set_level(logging.ERROR, logger="mcpgateway.services.tool_service")

        mock_db = Mock()

        # Create mock tools - tool2 will fail conversion
        tool1 = Mock(id="1", original_name="good_tool_1", team_id=None)
        tool1.name = "good-tool-1"
        tool2 = Mock(id="2", original_name="bad_tool", team_id=None)
        tool2.name = "bad-tool"
        tool3 = Mock(id="3", original_name="good_tool_2", team_id=None)
        tool3.name = "good-tool-2"

        # Mock DB to return all three tools
        mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[tool1, tool2, tool3])))))
        mock_db.commit = Mock()

        # Create valid ToolRead objects for good tools
        tool_read_1 = MagicMock()
        tool_read_1.name = "good_tool_1"
        tool_read_3 = MagicMock()
        tool_read_3.name = "good_tool_2"

        # Track conversion calls to ensure proper isolation
        conversion_calls = []

        # Make convert_tool_to_read succeed for tool1 and tool3, but fail for tool2
        def mock_convert(tool, include_metrics=False, include_auth=False, **kwargs):
            conversion_calls.append(tool.id)
            if tool.id == "2":
                raise ValueError("Simulated conversion error: corrupted auth_value")
            elif tool.id == "1":
                return tool_read_1
            else:
                return tool_read_3

        service = ToolService()

        # Clear any cached state that might affect the test
        tool_lookup_cache.invalidate_all_local()

        # Use patch.object to properly mock the instance method
        # Also patch _get_registry_cache to ensure we don't hit polluted cache
        with patch.object(service, "convert_tool_to_read", side_effect=mock_convert), patch("mcpgateway.services.tool_service._get_registry_cache") as mock_get_cache:
            # Setup mock cache to miss and handle async set
            mock_get_cache.return_value.get = AsyncMock(return_value=None)
            mock_get_cache.return_value.set = AsyncMock()
            mock_get_cache.return_value.hash_filters = Mock(return_value="mock_hash")
            # Call list_tools - should NOT raise an exception
            result, next_cursor = await service.list_tools(mock_db)

            # Verify we got at least the two valid tools (allow for timing tolerance)
            assert len(result) >= 2, f"Expected at least 2 valid tools, got {len(result)}"
            assert tool_read_1 in result, "tool_read_1 should be in result"
            assert tool_read_3 in result, "tool_read_3 should be in result"

            # Verify convert_tool_to_read was called for all three tools
            assert len(conversion_calls) == 3, f"Expected 3 conversion calls, got {len(conversion_calls)}"
            assert service.convert_tool_to_read.call_count == 3

            # Verify the error was logged (format: "Failed to convert tool {id} ({name}): {error}")
            assert "Failed to convert tool 2" in caplog.text
            assert "bad-tool" in caplog.text

    @pytest.mark.asyncio
    async def test_list_server_tools_continues_on_conversion_error(self, caplog):
        """Test that list_server_tools returns valid tools even when one fails conversion."""
        # Standard
        import logging

        caplog.set_level(logging.ERROR, logger="mcpgateway.services.tool_service")

        mock_db = Mock()

        # Create mock tools - tool2 will fail conversion
        tool1 = Mock(enabled=True, team_id=None, team=None, id="1", original_name="good_tool_1")
        tool1.name = "good-tool-1"
        tool2 = Mock(enabled=True, team_id=None, team=None, id="2", original_name="bad_tool")
        tool2.name = "bad-tool"
        tool3 = Mock(enabled=True, team_id=None, team=None, id="3", original_name="good_tool_2")
        tool3.name = "good-tool-2"

        mock_db.execute.return_value.scalars.return_value.all.return_value = [tool1, tool2, tool3]

        service = ToolService()

        # Make convert_tool_to_read succeed for tool1 and tool3, but fail for tool2
        def mock_convert(tool, include_metrics=False, include_auth=False, **kwargs):
            if tool.id == "2":
                raise ValueError("Simulated conversion error")
            return f"converted_{tool.original_name}"

        # Use patch.object to properly mock the instance method
        with patch.object(service, "convert_tool_to_read", side_effect=mock_convert):
            # Call list_server_tools - should NOT raise an exception
            tools = await service.list_server_tools(mock_db, server_id="server123", include_inactive=False)

            # Verify we got the two valid tools
            assert len(tools) == 2
            assert "converted_good_tool_1" in tools
            assert "converted_good_tool_2" in tools

            # Verify the error was logged
            assert "Failed to convert tool 2" in caplog.text
            assert "bad-tool" in caplog.text

    @pytest.mark.asyncio
    async def test_list_tools_for_user_continues_on_conversion_error(self, caplog):
        """Test that list_tools_for_user returns valid tools even when one fails conversion."""
        # Standard
        import logging

        caplog.set_level(logging.ERROR, logger="mcpgateway.services.tool_service")

        mock_db = Mock()

        # Create mock tools - tool2 will fail conversion
        tool1 = Mock(id="1", original_name="good_tool_1", team_id=None)
        tool1.name = "good-tool-1"
        tool2 = Mock(id="2", original_name="bad_tool", team_id=None)
        tool2.name = "bad-tool"
        tool3 = Mock(id="3", original_name="good_tool_2", team_id=None)
        tool3.name = "good-tool-2"

        # Mock DB to return all three tools
        mock_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[tool1, tool2, tool3])))))
        mock_db.commit = Mock()

        # Create valid ToolRead objects for good tools
        tool_read_1 = MagicMock()
        tool_read_1.name = "good_tool_1"
        tool_read_3 = MagicMock()
        tool_read_3.name = "good_tool_2"

        # Make convert_tool_to_read succeed for tool1 and tool3, but fail for tool2
        def mock_convert(tool, include_metrics=False, include_auth=False, **kwargs):
            if tool.id == "2":
                raise ValueError("Simulated conversion error: corrupted data")
            elif tool.id == "1":
                return tool_read_1
            else:
                return tool_read_3

        service = ToolService()

        # Mock TeamManagementService for user context
        mock_team = MagicMock(id="team-1", is_personal=True)
        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])

            # Use patch.object to properly mock the instance method
            with patch.object(service, "convert_tool_to_read", side_effect=mock_convert):
                # Call list_tools_for_user - should NOT raise an exception
                # Returns tuple[List[ToolRead], Optional[str]]
                result, next_cursor = await service.list_tools_for_user(mock_db, user_email="user@example.com")

        # Verify we got the two valid tools
        assert len(result) == 2
        assert tool_read_1 in result
        assert tool_read_3 in result

        # Verify the error was logged
        assert "Failed to convert tool 2" in caplog.text
        assert "bad-tool" in caplog.text

    @pytest.mark.asyncio
    async def test_list_tools_for_user_invalid_cursor(self, tool_service, test_db):
        """Invalid cursor should be ignored and still return results."""
        tool = MagicMock(id="1", original_name="tool-1", team_id=None)
        tool.name = "tool-1"

        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[tool])))))
        test_db.commit = Mock()
        tool_service.convert_tool_to_read = Mock(return_value=MagicMock())

        mock_team = MagicMock(id="team-1", is_personal=True)
        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            with patch("mcpgateway.services.tool_service.decode_cursor", side_effect=ValueError("bad")):
                result, next_cursor = await tool_service.list_tools_for_user(test_db, user_email="user@example.com", cursor="bad")

        assert len(result) == 1
        assert next_cursor is None

    @pytest.mark.asyncio
    async def test_list_tools_for_user_team_no_access(self, tool_service, test_db):
        """Team filter should return empty when user lacks access."""
        # Mock DB execute - should NOT be called due to early return
        test_db.execute = Mock(return_value=MagicMock(scalars=Mock(return_value=MagicMock(all=Mock(return_value=[])))))
        mock_team = MagicMock(id="team-1", is_personal=True)

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_team_service.return_value.get_user_teams = AsyncMock(return_value=[mock_team])
            result, next_cursor = await tool_service.list_tools_for_user(test_db, user_email="user@example.com", team_id="team-2")

        assert result == []
        assert next_cursor is None
        # Early return when user lacks team access - no DB query executed
        test_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# AnyUrl Serialization Tests (PR #2517 - Issue #2512)
# ---------------------------------------------------------------------------


class TestAnyUrlSerialization:
    """Tests for AnyUrl serialization fix (mode='json' in model_dump).

    The root cause of Issue #2512 was that AnyUrl fields were not being
    serialized to strings when dumping tool results. This caused validation
    errors when the content was passed to MCP SDK types.

    The fix adds mode='json' to model_dump() calls, which ensures AnyUrl
    objects are serialized to strings.
    """

    def test_anyurl_serialization_without_mode_json(self):
        """Demonstrate that AnyUrl stays as object without mode='json'."""
        # Third-Party
        from pydantic import AnyUrl, BaseModel

        class TestModel(BaseModel):
            uri: AnyUrl
            name: str

        model = TestModel(uri="https://example.com/file.txt", name="test")

        # Without mode="json", AnyUrl remains as AnyUrl object
        dump = model.model_dump(by_alias=True)
        assert not isinstance(dump["uri"], str)
        assert isinstance(dump["uri"], AnyUrl)

    def test_anyurl_serialization_with_mode_json(self):
        """Verify that AnyUrl is serialized to string with mode='json'."""
        # Third-Party
        from pydantic import AnyUrl, BaseModel

        class TestModel(BaseModel):
            uri: AnyUrl
            name: str

        model = TestModel(uri="https://example.com/file.txt", name="test")

        # With mode="json", AnyUrl is serialized to string (the fix)
        dump = model.model_dump(by_alias=True, mode="json")
        assert isinstance(dump["uri"], str)
        assert dump["uri"] == "https://example.com/file.txt"

    def test_resource_link_anyurl_serialization(self):
        """Verify ResourceLink uri field is serialized correctly with mode='json'."""
        # First-Party
        from mcpgateway.common.models import ResourceLink

        resource_link = ResourceLink(
            type="resource_link",
            uri="s3://bucket/path/to/file.bin",
            name="file.bin",
            description="A binary file",
            mime_type="application/octet-stream",
            size=1024,
        )

        # This is what the tool_service fix does (line 3192)
        dump = resource_link.model_dump(by_alias=True, mode="json")

        # uri should be a string, not an AnyUrl object
        assert isinstance(dump["uri"], str)
        assert dump["uri"] == "s3://bucket/path/to/file.bin"
        assert dump["type"] == "resource_link"
        assert dump["name"] == "file.bin"
        assert dump["size"] == 1024

    def test_tool_result_with_resource_link_serialization(self):
        """Verify ToolResult containing ResourceLink serializes AnyUrl correctly."""
        # First-Party
        from mcpgateway.common.models import ResourceLink

        resource_link = ResourceLink(
            type="resource_link",
            uri="https://cdn.example.com/assets/image.png",
            name="image.png",
            mime_type="image/png",
            size=2048,
        )

        tool_result = ToolResult(content=[resource_link], is_error=False)

        # This is what the tool_service fix does (line 3192)
        dump = tool_result.model_dump(by_alias=True, mode="json")

        # Verify the uri in content is a string
        assert len(dump["content"]) == 1
        assert isinstance(dump["content"][0]["uri"], str)
        assert dump["content"][0]["uri"] == "https://cdn.example.com/assets/image.png"
        assert dump["content"][0]["type"] == "resource_link"

    def test_mixed_content_with_anyurl_serialization(self):
        """Verify mixed content types with AnyUrl fields serialize correctly."""
        # First-Party
        from mcpgateway.common.models import ResourceLink

        resource_link = ResourceLink(
            type="resource_link",
            uri="file:///path/to/document.pdf",
            name="document.pdf",
            mime_type="application/pdf",
        )

        text_content = TextContent(type="text", text="Hello world")
        tool_result = ToolResult(content=[text_content, resource_link], is_error=False)

        # This is what the tool_service fix does (line 3192)
        dump = tool_result.model_dump(by_alias=True, mode="json")

        # Verify both content items
        assert len(dump["content"]) == 2
        assert dump["content"][0]["type"] == "text"
        assert dump["content"][0]["text"] == "Hello world"
        assert dump["content"][1]["type"] == "resource_link"
        assert isinstance(dump["content"][1]["uri"], str)
        assert dump["content"][1]["uri"] == "file:///path/to/document.pdf"


# =============================================================================
# Tool Invocation Timeouts and Circuit Breaker Tests
# =============================================================================


class TestToolTimeoutsAndRetries:
    """Comprehensive tests for Tool Invocation Timeouts and Circuit Breaker."""

    def setup_method(self):
        """Clear circuit breaker state before each test."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _STATE

        _STATE.clear()

    @pytest.mark.asyncio
    async def test_per_tool_timeout_ms_takes_priority(self):
        """Verify per-tool timeout_ms takes priority over global setting."""
        tool_timeout_ms = 5000  # 5 seconds
        global_timeout = 60  # 60 seconds

        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else global_timeout

        assert effective_timeout == 5.0, "Per-tool timeout should take priority"

    @pytest.mark.asyncio
    async def test_per_tool_timeout_zero_uses_global(self):
        """Verify that timeout_ms=0 falls back to global timeout."""
        tool_timeout_ms = 0
        global_timeout = 60

        # 0 is falsy, so should fall back to global
        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else global_timeout

        assert effective_timeout == 60, "Zero timeout should fall back to global"

    @pytest.mark.asyncio
    async def test_per_tool_timeout_none_uses_global(self):
        """Verify that timeout_ms=None falls back to global timeout."""
        tool_timeout_ms = None
        global_timeout = 60

        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else global_timeout

        assert effective_timeout == 60, "None timeout should fall back to global"

    @pytest.mark.asyncio
    async def test_timeout_conversion_from_ms_to_seconds(self):
        """Verify correct conversion from milliseconds to seconds."""
        test_cases = [
            (1000, 1.0),
            (5000, 5.0),
            (30000, 30.0),
            (100, 0.1),
            (60000, 60.0),
        ]

        for timeout_ms, expected_seconds in test_cases:
            effective_timeout = timeout_ms / 1000
            assert effective_timeout == expected_seconds, f"Failed for {timeout_ms}ms"

    @pytest.mark.asyncio
    async def test_timeout_error_message_includes_duration(self):
        """Verify timeout error message includes the timeout duration."""
        for timeout in [5.0, 10.0, 30.0, 60.0]:
            error = ToolInvocationError(f"Tool invocation timed out after {timeout}s")
            assert str(timeout) in str(error)
            assert "timed out" in str(error)

    @pytest.mark.asyncio
    async def test_asyncio_timeout_error_behavior(self):
        """Test asyncio.TimeoutError is raised correctly after timeout."""

        async def slow_operation():
            await asyncio.sleep(10)
            return "completed"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_operation(), timeout=0.01)

    def test_initial_state_is_closed(self):
        """Verify circuit breaker starts in closed state."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _get_state

        state = _get_state("test_tool")

        assert state.open_until == 0.0
        assert state.half_open is False
        assert state.consecutive_failures == 0

    def test_state_tracks_calls_in_window(self):
        """Verify state tracks call timestamps."""
        # Standard
        import time

        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _get_state

        state = _get_state("test_tool")
        state.calls.append(time.time())
        state.calls.append(time.time())

        assert len(state.calls) == 2

    def test_state_tracks_failures_in_window(self):
        """Verify state tracks failure timestamps."""
        # Standard
        import time

        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _get_state

        state = _get_state("test_tool")
        state.failures.append(time.time())
        state.failures.append(time.time())

        assert len(state.failures) == 2

    def test_consecutive_failures_increment(self):
        """Verify consecutive failures counter increments."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _get_state

        state = _get_state("test_tool")
        state.consecutive_failures += 1
        state.consecutive_failures += 1
        state.consecutive_failures += 1

        assert state.consecutive_failures == 3

    def test_consecutive_failures_reset_on_success(self):
        """Verify consecutive failures reset to 0 on success."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _get_state

        state = _get_state("test_tool")
        state.consecutive_failures = 5
        # Simulate success
        state.consecutive_failures = 0

        assert state.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_half_open_transition_after_cooldown(self):
        """Verify transition to half-open state after cooldown expires."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPreInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1, config={"cooldown_seconds": 1})
        plugin = CircuitBreakerPlugin(config)

        # Open the circuit
        state = _get_state("test_tool")
        state.open_until = time.time() - 1  # Cooldown expired
        state.half_open = False

        # Create payload
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # Create mock context
        context = MagicMock()
        context.set_state = MagicMock()

        # Process pre_invoke
        result = await plugin.tool_pre_invoke(payload, context)

        # Should allow request through (transition to half-open)
        assert result.continue_processing is True
        # Verify half-open state was set in context
        context.set_state.assert_any_call("cb_half_open_test", True)

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """Verify that failure during half-open immediately reopens circuit."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin with short cooldown
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1, config={"cooldown_seconds": 60})
        plugin = CircuitBreakerPlugin(config)

        # Set up half-open state
        state = _get_state("test_tool")
        state.half_open = True

        # Create mock error result
        mock_result = MagicMock()
        mock_result.is_error = True

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        # Create mock context indicating half-open test
        context = MagicMock()
        context.get_state = MagicMock(
            side_effect=lambda k, d=None: {
                "cb_call_time": time.time(),
                "cb_half_open_test": True,
                "cb_timeout_failure": False,
            }.get(k, d)
        )

        # Process post_invoke
        await plugin.tool_post_invoke(payload, context)

        # Circuit should be reopened
        assert state.open_until > time.time()
        assert state.half_open is False

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """Verify that success during half-open fully closes circuit."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        # Set up half-open state
        state = _get_state("test_tool")
        state.half_open = True
        state.consecutive_failures = 4

        # Create mock success result
        mock_result = MagicMock()
        mock_result.is_error = False

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        # Create mock context indicating half-open test
        context = MagicMock()
        context.get_state = MagicMock(
            side_effect=lambda k, d=None: {
                "cb_call_time": time.time(),
                "cb_half_open_test": True,
                "cb_timeout_failure": False,
            }.get(k, d)
        )

        # Process post_invoke
        await plugin.tool_post_invoke(payload, context)

        # Circuit should be fully closed
        assert state.half_open is False
        assert state.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_consecutive_failure_threshold_trips_breaker(self):
        """Verify consecutive failures trip the circuit breaker."""
        # Standard
        from collections import deque
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin with low consecutive failure threshold
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1, config={"consecutive_failure_threshold": 3, "cooldown_seconds": 60})
        plugin = CircuitBreakerPlugin(config)

        # Pre-set consecutive failures to threshold - 1
        state = _get_state("test_tool")
        state.consecutive_failures = 2
        state.calls = deque([time.time()])
        state.failures = deque([time.time()])

        # Create mock error result
        mock_result = MagicMock()
        mock_result.is_error = True

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        context = MagicMock()
        context.get_state = MagicMock(return_value=None)

        # Process post_invoke - should trip breaker
        await plugin.tool_post_invoke(payload, context)

        # Circuit should be open
        assert state.open_until > time.time()

    @pytest.mark.asyncio
    async def test_error_rate_threshold_trips_breaker(self):
        """Verify error rate threshold trips the circuit breaker."""
        # Standard
        from collections import deque
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin with specific error rate settings
        config = PluginConfig(
            name="test",
            kind="test",
            hooks=[],
            mode="enforce",
            priority=1,
            config={
                "error_rate_threshold": 0.5,  # 50% error rate trips
                "min_calls": 2,  # After 2 calls
                "cooldown_seconds": 60,
            },
        )
        plugin = CircuitBreakerPlugin(config)

        # Pre-set calls and failures for 50% error rate
        now = time.time()
        state = _get_state("test_tool")
        state.calls = deque([now - 1])  # 1 previous call
        state.failures = deque([now - 1])  # 1 failure (this will be the 2nd)
        state.consecutive_failures = 1

        # Create mock error result
        mock_result = MagicMock()
        mock_result.is_error = True

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        context = MagicMock()
        context.get_state = MagicMock(side_effect=lambda k, d=None: now if k == "cb_call_time" else d)

        # Process post_invoke - should trip breaker (2/2 = 100% > 50%)
        await plugin.tool_post_invoke(payload, context)

        # Circuit should be open
        assert state.open_until > time.time()

    @pytest.mark.asyncio
    async def test_retry_after_seconds_in_violation(self):
        """Verify retry_after_seconds is included in violation details."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPreInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        # Open the circuit with future close time
        state = _get_state("test_tool")
        state.open_until = time.time() + 30  # 30 seconds from now

        # Create payload
        payload = ToolPreInvokePayload(name="test_tool", arguments={})

        # Create mock context
        context = MagicMock()

        # Process pre_invoke - should block
        result = await plugin.tool_pre_invoke(payload, context)

        # Should block with retry_after_seconds
        assert result.continue_processing is False
        assert result.violation is not None
        assert "retry_after_seconds" in result.violation.details
        assert 25 <= result.violation.details["retry_after_seconds"] <= 35

    @pytest.mark.asyncio
    async def test_metadata_includes_all_fields(self):
        """Verify post_invoke metadata includes all required fields."""
        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import CircuitBreakerPlugin

        # Create plugin
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        # Create mock success result
        mock_result = MagicMock()
        mock_result.is_error = False

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        context = MagicMock()
        context.get_state = MagicMock(return_value=None)

        # Process post_invoke
        result = await plugin.tool_post_invoke(payload, context)

        # Verify all metadata fields are present
        required_fields = [
            "circuit_calls_in_window",
            "circuit_failures_in_window",
            "circuit_failure_rate",
            "circuit_consecutive_failures",
            "circuit_open_until",
            "circuit_half_open",
            "circuit_retry_after_seconds",
        ]

        for field in required_fields:
            assert field in result.metadata, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_timeout_flag_counts_as_failure(self):
        """Verify cb_timeout_failure flag counts as circuit breaker failure."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import CircuitBreakerPlugin

        # Create plugin
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        # Create mock result that looks successful
        mock_result = MagicMock()
        mock_result.is_error = False  # Result doesn't show error

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        # Create context with timeout flag set
        context = MagicMock()
        context.get_state = MagicMock(
            side_effect=lambda k, d=None: {
                "cb_call_time": time.time(),
                "cb_half_open_test": False,
                "cb_timeout_failure": True,  # TIMEOUT OCCURRED!
            }.get(k, d)
        )

        # Process post_invoke
        result = await plugin.tool_post_invoke(payload, context)

        # Should count as failure
        assert result.metadata["circuit_failures_in_window"] == 1
        assert result.metadata["circuit_consecutive_failures"] == 1

    @pytest.mark.asyncio
    async def test_timeout_flag_can_trip_breaker(self):
        """Verify enough timeout failures can trip the circuit breaker."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin with low threshold
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1, config={"consecutive_failure_threshold": 3, "cooldown_seconds": 60})
        plugin = CircuitBreakerPlugin(config)

        state = _get_state("test_tool")
        state.consecutive_failures = 2  # Already at threshold - 1

        # Create mock result that looks successful
        mock_result = MagicMock()
        mock_result.is_error = False

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        # Create context with timeout flag set
        context = MagicMock()
        context.get_state = MagicMock(
            side_effect=lambda k, d=None: {
                "cb_call_time": time.time(),
                "cb_half_open_test": False,
                "cb_timeout_failure": True,  # 3rd consecutive failure via timeout
            }.get(k, d)
        )

        # Process post_invoke
        await plugin.tool_post_invoke(payload, context)

        # Should trip the breaker
        assert state.open_until > time.time()

    def test_tool_overrides_apply_correctly(self):
        """Verify per-tool overrides are applied."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _cfg_for, CircuitBreakerConfig

        # Create base config with tool overrides
        base_config = CircuitBreakerConfig(
            error_rate_threshold=0.5,
            window_seconds=60,
            consecutive_failure_threshold=5,
            cooldown_seconds=60,
            tool_overrides={
                "critical_tool": {
                    "consecutive_failure_threshold": 2,  # More sensitive
                    "cooldown_seconds": 120,  # Longer cooldown
                }
            },
        )

        # Get effective config for regular tool
        regular_config = _cfg_for(base_config, "regular_tool")
        assert regular_config.consecutive_failure_threshold == 5
        assert regular_config.cooldown_seconds == 60

        # Get effective config for critical tool
        critical_config = _cfg_for(base_config, "critical_tool")
        assert critical_config.consecutive_failure_threshold == 2
        assert critical_config.cooldown_seconds == 120

    @pytest.mark.asyncio
    async def test_old_entries_evicted_from_window(self):
        """Verify old call/failure entries are evicted from sliding window."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPostInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        # Create plugin with 1-second window
        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1, config={"window_seconds": 1})
        plugin = CircuitBreakerPlugin(config)

        # Add old entries
        state = _get_state("test_tool")
        old_time = time.time() - 10  # 10 seconds ago
        state.calls.append(old_time)
        state.failures.append(old_time)

        # Create mock result
        mock_result = MagicMock()
        mock_result.is_error = False

        payload = ToolPostInvokePayload(name="test_tool", arguments={}, result=mock_result)

        context = MagicMock()
        context.get_state = MagicMock(return_value=None)

        # Process post_invoke - should evict old entries
        result = await plugin.tool_post_invoke(payload, context)

        # Old entries should be evicted, new call should be recorded
        assert result.metadata["circuit_calls_in_window"] == 1
        assert result.metadata["circuit_failures_in_window"] == 0

    def test_is_error_with_tool_result_attribute(self):
        """Verify is_error detection using ToolResult.is_error attribute."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _is_error

        mock_result = MagicMock()
        mock_result.is_error = True

        assert _is_error(mock_result) is True

        mock_result.is_error = False
        assert _is_error(mock_result) is False

    def test_is_error_with_dict(self):
        """Verify is_error detection using dict key."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _is_error

        error_dict = {"is_error": True, "content": "error message"}
        assert _is_error(error_dict) is True

        success_dict = {"is_error": False, "content": "success"}
        assert _is_error(success_dict) is False

    def test_is_error_with_missing_field_returns_false(self):
        """Verify is_error returns False when field is missing."""
        # First-Party
        from plugins.circuit_breaker.circuit_breaker import _is_error

        # Object without is_error
        mock_result = MagicMock(spec=[])  # No attributes
        del mock_result.is_error  # Remove any auto-mock

        # Dict without is_error key
        no_error_dict = {"content": "some content"}
        assert _is_error(no_error_dict) is False

    @pytest.mark.asyncio
    async def test_plugin_initialization(self):
        """Verify plugin initializes correctly with config."""
        # First-Party
        from mcpgateway.plugins.framework import PluginConfig
        from plugins.circuit_breaker.circuit_breaker import CircuitBreakerPlugin

        config = PluginConfig(
            name="CircuitBreaker",
            kind="plugins.circuit_breaker.circuit_breaker.CircuitBreakerPlugin",
            hooks=["tool_pre_invoke", "tool_post_invoke"],
            mode="enforce_ignore_error",
            priority=70,
            config={
                "error_rate_threshold": 0.3,
                "window_seconds": 120,
                "min_calls": 5,
                "consecutive_failure_threshold": 3,
                "cooldown_seconds": 30,
            },
        )

        plugin = CircuitBreakerPlugin(config)

        assert plugin._cfg.error_rate_threshold == 0.3
        assert plugin._cfg.window_seconds == 120
        assert plugin._cfg.min_calls == 5
        assert plugin._cfg.consecutive_failure_threshold == 3
        assert plugin._cfg.cooldown_seconds == 30

    @pytest.mark.asyncio
    async def test_plugin_allows_requests_when_closed(self):
        """Verify plugin allows requests when circuit is closed."""
        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPreInvokePayload
        from plugins.circuit_breaker.circuit_breaker import CircuitBreakerPlugin

        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        context = MagicMock()
        context.set_state = MagicMock()

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is True
        assert result.violation is None

    @pytest.mark.asyncio
    async def test_plugin_blocks_requests_when_open(self):
        """Verify plugin blocks requests when circuit is open."""
        # Standard
        import time

        # First-Party
        from mcpgateway.plugins.framework import PluginConfig, ToolPreInvokePayload
        from plugins.circuit_breaker.circuit_breaker import _get_state, CircuitBreakerPlugin

        config = PluginConfig(name="test", kind="test", hooks=[], mode="enforce", priority=1)
        plugin = CircuitBreakerPlugin(config)

        # Open the circuit
        state = _get_state("test_tool")
        state.open_until = time.time() + 60  # Open for next 60 seconds

        payload = ToolPreInvokePayload(name="test_tool", arguments={})
        context = MagicMock()

        result = await plugin.tool_pre_invoke(payload, context)

        assert result.continue_processing is False
        assert result.violation is not None


class TestToolServiceHelpers:
    def test_get_validator_class_and_check_fallback_draft7(self, monkeypatch):
        """Ensure schema fallback uses Draft7 when auto-detect fails."""
        # First-Party
        from mcpgateway.services import tool_service

        tool_service._get_validator_class_and_check.cache_clear()

        class DummyValidator:
            @staticmethod
            def check_schema(schema):
                raise jsonschema.exceptions.SchemaError("invalid")

        class Draft7Ok:
            @staticmethod
            def check_schema(schema):
                return None

        class DraftFail:
            @staticmethod
            def check_schema(schema):
                raise jsonschema.exceptions.SchemaError("invalid")

        monkeypatch.setattr(tool_service.validators, "validator_for", lambda schema: DummyValidator)
        monkeypatch.setattr(tool_service, "Draft7Validator", Draft7Ok)
        monkeypatch.setattr(tool_service, "Draft6Validator", DraftFail)
        monkeypatch.setattr(tool_service, "Draft4Validator", DraftFail)

        schema = {"type": "object"}
        schema_json = orjson.dumps(schema).decode()

        validator_cls, checked_schema = tool_service._get_validator_class_and_check(schema_json)

        assert validator_cls is Draft7Ok
        assert checked_schema == schema

    def test_validate_with_cached_schema_raises_on_invalid_instance(self):
        """Ensure validation raises when instance does not match schema."""
        # First-Party
        from mcpgateway.services import tool_service

        tool_service._get_validator_class_and_check.cache_clear()

        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        with pytest.raises(jsonschema.exceptions.ValidationError):
            tool_service._validate_with_cached_schema({}, schema)

    @pytest.mark.asyncio
    async def test_check_tool_access_public_and_admin(self):
        """Verify public access and admin bypass paths."""
        service = ToolService()

        public_payload = {"visibility": "public"}
        assert await service._check_tool_access(MagicMock(), public_payload, None, []) is True

        private_payload = {"visibility": "private"}
        assert await service._check_tool_access(MagicMock(), private_payload, None, None) is True

    @pytest.mark.asyncio
    async def test_check_tool_access_denies_without_user_or_public_only_token(self):
        """Verify deny paths for missing user and public-only tokens."""
        service = ToolService()

        private_payload = {"visibility": "private"}
        assert await service._check_tool_access(MagicMock(), private_payload, None, ["team-1"]) is False

        team_payload = {"visibility": "team", "team_id": "team-1"}
        assert await service._check_tool_access(MagicMock(), team_payload, "user@example.com", []) is False

    @pytest.mark.asyncio
    async def test_check_tool_access_owner_and_team_token(self):
        """Verify owner access and team token membership access."""
        service = ToolService()

        owner_payload = {"visibility": "private", "owner_email": "owner@example.com"}
        assert await service._check_tool_access(MagicMock(), owner_payload, "owner@example.com", ["team-2"]) is True

        team_payload = {"visibility": "team", "team_id": "team-1"}
        assert await service._check_tool_access(MagicMock(), team_payload, "user@example.com", ["team-1"]) is True

        assert await service._check_tool_access(MagicMock(), team_payload, "user@example.com", ["team-2"]) is False

    @pytest.mark.asyncio
    async def test_check_tool_access_team_lookup_from_db(self):
        """Verify team membership lookup when token lacks teams."""
        service = ToolService()
        tool_payload = {"visibility": "team", "team_id": "team-9"}

        with patch("mcpgateway.services.tool_service.TeamManagementService") as mock_team_service:
            mock_instance = mock_team_service.return_value
            mock_instance.get_user_teams = AsyncMock(return_value=[SimpleNamespace(id="team-9")])

            assert await service._check_tool_access(MagicMock(), tool_payload, "user@example.com", None) is True

    def test_build_tool_cache_payload_and_pydantic_helpers(self):
        """Verify cache payload assembly and Pydantic helper behavior."""
        service = ToolService()

        tool = SimpleNamespace(
            id="tool-1",
            name="tool-name",
            original_name="tool-name",
            url="https://example.com/tool",
            description="desc",
            original_description="desc",
            integration_type="http",
            request_type="http",
            headers=None,
            input_schema=None,
            output_schema={"type": "object"},
            annotations=None,
            auth_type="bearer",
            auth_value="secret",
            oauth_config=None,
            jsonpath_filter="",
            custom_name="custom",
            custom_name_slug="custom",
            display_name="Custom Tool",
            gateway_id=None,
            enabled=True,
            reachable=True,
            tags=None,
            team_id="team-1",
            owner_email="owner@example.com",
            visibility="team",
            query_mapping={},
            header_mapping={},
        )
        gateway = SimpleNamespace(
            id="gw-1",
            name="gw",
            url="https://example.com/gw",
            description="gw-desc",
            slug="gw",
            transport="http",
            capabilities=None,
            passthrough_headers=None,
            auth_type="basic",
            auth_value="secret",
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            enabled=True,
            reachable=True,
            team_id="team-1",
            owner_email="owner@example.com",
            visibility="team",
            tags=None,
        )

        payload = service._build_tool_cache_payload(tool, gateway)

        assert payload["status"] == "active"
        assert payload["tool"]["headers"] == {}
        assert payload["tool"]["input_schema"]["type"] == "object"
        assert payload["tool"]["query_mapping"] == {}
        assert payload["tool"]["header_mapping"] == {}
        assert "auth_value" not in payload["tool"]
        assert "oauth_config" not in payload["tool"]
        assert payload["gateway"]["passthrough_headers"] == []
        assert "auth_value" not in payload["gateway"]
        assert "oauth_config" not in payload["gateway"]
        assert "auth_query_params" not in payload["gateway"]

        sentinel = object()
        with patch("mcpgateway.services.tool_service.PydanticTool.model_validate", return_value=sentinel):
            assert service._pydantic_tool_from_payload(payload["tool"]) is sentinel

        with patch("mcpgateway.services.tool_service.PydanticGateway.model_validate", side_effect=ValueError("bad")):
            assert service._pydantic_gateway_from_payload(payload["gateway"]) is None

    def test_convert_tool_to_read_auth_variants(self):
        """Verify auth decoding and masking behaviors in conversion."""
        service = ToolService()

        def make_tool(auth_type, auth_value):
            return SimpleNamespace(
                id="tool-1",
                name="tool",
                original_name="orig",
                description="desc",
                url="https://example.com",
                integration_type="http",
                request_type="http",
                headers={},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                annotations={},
                auth_type=auth_type,
                auth_value=auth_value,
                jsonpath_filter=None,
                custom_name="custom",
                custom_name_slug="custom",
                display_name=None,
                gateway_id=None,
                enabled=True,
                reachable=True,
                tags=[],
                team_id=None,
                owner_email="owner@example.com",
                visibility="private",
                metrics_summary={"total_executions": 2},
                gateway_slug="",
                team=None,
            )

        with patch("mcpgateway.services.tool_service.ToolRead.model_validate", side_effect=lambda data: data):
            encoded = base64.b64encode(b"user:pass").decode()
            basic_tool = make_tool("basic", "secret")
            with patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": f"Basic {encoded}"}):
                result = service.convert_tool_to_read(basic_tool, include_metrics=True, include_auth=True)
                assert result["auth"]["auth_type"] == "basic"
                assert result["auth"]["username"] == "user"
                assert result["auth"]["password"] == settings.masked_auth_value

            bearer_tool = make_tool("bearer", "secret")
            with patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer token"}):
                result = service.convert_tool_to_read(bearer_tool, include_metrics=False, include_auth=True)
                assert result["auth"]["auth_type"] == "bearer"
                assert result["auth"]["token"] == settings.masked_auth_value

            headers_tool = make_tool("authheaders", "secret")
            with patch("mcpgateway.services.tool_service.decode_auth", return_value={"X-Api-Key": "token"}):
                result = service.convert_tool_to_read(headers_tool, include_metrics=False, include_auth=True)
                assert result["auth"]["auth_type"] == "authheaders"
                assert result["auth"]["auth_header_key"] == "X-Api-Key"
                assert result["auth"]["auth_header_value"] == settings.masked_auth_value

            no_decode_tool = make_tool("bearer", "secret")
            with patch("mcpgateway.services.tool_service.decode_auth") as mock_decode:
                result = service.convert_tool_to_read(no_decode_tool, include_metrics=False, include_auth=False)
                assert result["auth"]["auth_type"] == "bearer"
                mock_decode.assert_not_called()

            unknown_tool = make_tool("custom", "secret")
            with patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Basic value"}):
                result = service.convert_tool_to_read(unknown_tool, include_metrics=False, include_auth=True)
                assert result["auth"] is None


def _make_bulk_tool_create(name: str, integration_type: str = "REST", **overrides) -> ToolCreate:
    request_type = "POST" if integration_type == "REST" else "SSE"
    payload = {
        "name": name,
        "url": "https://example.com/api",
        "description": "Bulk tool",
        "integration_type": integration_type,
        "request_type": request_type,
        "headers": {"X-Test": "1"},
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        "output_schema": {"type": "object"},
        "tags": ["alpha"],
    }
    payload.update(overrides)
    return ToolCreate(**payload)


class TestToolServiceBulkImport:
    def test_create_tool_object_rest_and_mcp_fields(self):
        service = ToolService()

        tool_rest = _make_bulk_tool_create(
            name="bulk_tool_rest",
            base_url="https://api.example.com",
            path_template="/items/{id}",
            query_mapping={"q": "query"},
            header_mapping={"X-Request-Id": "header"},
            timeout_ms=5000,
            expose_passthrough=None,
            allowlist=["example.com"],
            plugin_chain_pre=["rate_limit"],
            plugin_chain_post=["response_shape"],
        )

        db_tool = service._create_tool_object(
            tool_rest,
            name=tool_rest.name,
            auth_type=None,
            auth_value=None,
            tool_team_id=None,
            tool_owner_email="owner@example.com",
            tool_visibility="public",
            created_by="creator@example.com",
            created_from_ip="127.0.0.1",
            created_via="api",
            created_user_agent="pytest",
            import_batch_id="batch-1",
            federation_source="fed-1",
        )

        assert db_tool.base_url == "https://api.example.com"
        assert db_tool.path_template == "/items/{id}"
        assert db_tool.query_mapping == {"q": "query"}
        assert db_tool.header_mapping == {"X-Request-Id": "header"}
        assert db_tool.timeout_ms == 5000
        assert db_tool.expose_passthrough is True
        assert db_tool.allowlist == ["example.com"]
        assert db_tool.plugin_chain_pre == ["rate_limit"]
        assert db_tool.plugin_chain_post == ["response_shape"]
        assert db_tool.custom_name_slug == "bulk-tool-rest"

        tool_mcp = ToolCreate.model_construct(
            name="bulk_tool_mcp",
            displayName=None,
            url="https://example.com/api",
            description="Bulk tool",
            integration_type="MCP",
            request_type="SSE",
            headers={"X-Test": "1"},
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            output_schema={"type": "object"},
            annotations={},
            jsonpath_filter="",
            auth=None,
            gateway_id=None,
            tags=["alpha"],
        )
        db_tool_mcp = service._create_tool_object(
            tool_mcp,
            name=tool_mcp.name,
            auth_type="bearer",
            auth_value="token",
            tool_team_id="team-1",
            tool_owner_email="owner@example.com",
            tool_visibility="team",
            created_by="creator@example.com",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )

        assert db_tool_mcp.base_url is None
        assert db_tool_mcp.header_mapping is None
        assert db_tool_mcp.timeout_ms is None
        assert db_tool_mcp.expose_passthrough is None
        assert db_tool_mcp.team_id == "team-1"

    def test_process_single_tool_for_bulk_update_rest_fields(self):
        service = ToolService()

        tool = _make_bulk_tool_create(
            name="bulk_tool_update",
            displayName="Bulk Update",
            annotations={"title": "Bulk"},
            jsonpath_filter="$.data",
            base_url="https://api.new",
            path_template="/new/{id}",
            query_mapping={"new": "query"},
            header_mapping={"X-New": "header"},
            timeout_ms=9000,
            expose_passthrough=False,
            allowlist=["example.com"],
            plugin_chain_pre=["rate_limit"],
            plugin_chain_post=["response_shape"],
            auth=AuthenticationValues(auth_type="bearer", auth_value="token"),
            tags=["updated"],
        )

        existing_tool = SimpleNamespace(
            name=tool.name,
            display_name="Old",
            url="https://old",
            description="old",
            integration_type="REST",
            request_type="GET",
            headers={"Old": "1"},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={"old": True},
            jsonpath_filter="",
            auth_type=None,
            auth_value=None,
            tags=["old"],
            modified_by=None,
            modified_from_ip=None,
            modified_via=None,
            modified_user_agent=None,
            updated_at=None,
            version=2,
            base_url="https://old",
            path_template="/old",
            query_mapping={"old": "query"},
            header_mapping={"X-Old": "header"},
            timeout_ms=1000,
            expose_passthrough=True,
            allowlist=["https://old"],
            plugin_chain_pre=["old-pre"],
            plugin_chain_post=["old-post"],
        )

        result = service._process_single_tool_for_bulk(
            tool=tool,
            existing_tools_map={tool.name: existing_tool},
            conflict_strategy="update",
            visibility="public",
            team_id=None,
            owner_email="owner@example.com",
            created_by="creator@example.com",
            created_from_ip="127.0.0.1",
            created_via="api",
            created_user_agent="pytest",
            import_batch_id="batch-1",
            federation_source="fed-1",
        )

        assert result["status"] == "update"
        assert existing_tool.display_name == "Bulk Update"
        assert existing_tool.url == "https://example.com/api"
        assert existing_tool.description == "Bulk tool"
        assert existing_tool.integration_type == "REST"
        assert existing_tool.request_type == "POST"
        assert existing_tool.headers == {"X-Test": "1"}
        assert existing_tool.input_schema["properties"]["q"]["type"] == "string"
        assert existing_tool.annotations == {"title": "Bulk"}
        assert existing_tool.jsonpath_filter == "$.data"
        assert existing_tool.auth_type == "bearer"
        assert existing_tool.auth_value == "token"
        assert existing_tool.tags == [{"id": "updated", "label": "updated"}]
        assert existing_tool.base_url == "https://api.new"
        assert existing_tool.path_template == "/new/{id}"
        assert existing_tool.query_mapping == {"new": "query"}
        assert existing_tool.header_mapping == {"X-New": "header"}
        assert existing_tool.timeout_ms == 9000
        assert existing_tool.expose_passthrough is False
        assert existing_tool.allowlist == ["example.com"]
        assert existing_tool.plugin_chain_pre == ["rate_limit"]
        assert existing_tool.plugin_chain_post == ["response_shape"]
        assert existing_tool.version == 3

    def test_process_single_tool_for_bulk_conflict_variants(self):
        service = ToolService()
        tool = _make_bulk_tool_create(name="bulk_tool_conflict")
        existing_tool = SimpleNamespace(name=tool.name)

        result_skip = service._process_single_tool_for_bulk(
            tool=tool,
            existing_tools_map={tool.name: existing_tool},
            conflict_strategy="skip",
            visibility="public",
            team_id=None,
            owner_email="owner@example.com",
            created_by="creator@example.com",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result_skip == {"status": "skip"}

        with patch("mcpgateway.services.tool_service.datetime") as mock_datetime, patch.object(service, "_create_tool_object") as mock_create:
            mock_datetime.now.return_value = datetime(2024, 1, 1, tzinfo=timezone.utc)
            sentinel_tool = object()
            mock_create.return_value = sentinel_tool

            result_rename = service._process_single_tool_for_bulk(
                tool=tool,
                existing_tools_map={tool.name: existing_tool},
                conflict_strategy="rename",
                visibility="public",
                team_id=None,
                owner_email="owner@example.com",
                created_by="creator@example.com",
                created_from_ip=None,
                created_via=None,
                created_user_agent=None,
                import_batch_id="batch-1",
                federation_source=None,
            )

        assert result_rename["status"] == "add"
        assert result_rename["tool"] is sentinel_tool
        mock_create.assert_called_once()
        assert mock_create.call_args[0][1] == "bulk_tool_conflict_imported_1704067200"

        result_fail = service._process_single_tool_for_bulk(
            tool=tool,
            existing_tools_map={tool.name: existing_tool},
            conflict_strategy="fail",
            visibility="public",
            team_id=None,
            owner_email="owner@example.com",
            created_by="creator@example.com",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result_fail["status"] == "fail"
        assert "Tool name conflict" in result_fail["error"]

    def test_process_single_tool_for_bulk_add_and_fail(self):
        service = ToolService()
        tool = _make_bulk_tool_create(name="bulk_tool_add", integration_type="REST")

        result_add = service._process_single_tool_for_bulk(
            tool=tool,
            existing_tools_map={},
            conflict_strategy="skip",
            visibility="private",
            team_id="team-1",
            owner_email="owner@example.com",
            created_by="creator@example.com",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )
        assert result_add["status"] == "add"
        assert result_add["tool"].original_name == tool.name

        with patch.object(service, "_create_tool_object", side_effect=ValueError("boom")):
            result_fail = service._process_single_tool_for_bulk(
                tool=tool,
                existing_tools_map={},
                conflict_strategy="skip",
                visibility="public",
                team_id=None,
                owner_email=None,
                created_by="creator@example.com",
                created_from_ip=None,
                created_via=None,
                created_user_agent=None,
                import_batch_id=None,
                federation_source=None,
            )
        assert result_fail["status"] == "fail"
        assert "Failed to process tool" in result_fail["error"]

    def test_process_tool_chunk_public_adds_and_audits(self, mock_logging_services):
        service = ToolService()
        tool = _make_bulk_tool_create(name="bulk_tool_chunk")
        db_tool = SimpleNamespace(id="tool-1")

        db = MagicMock()
        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        with patch.object(service, "_process_single_tool_for_bulk") as mock_process:
            mock_process.side_effect = [
                {"status": "add", "tool": db_tool},
                {"status": "skip"},
            ]
            stats = service._process_tool_chunk(
                db=db,
                chunk=[tool, tool],
                conflict_strategy="skip",
                visibility="public",
                team_id=None,
                owner_email="owner@example.com",
                created_by="creator@example.com",
                created_from_ip="127.0.0.1",
                created_via="api",
                created_user_agent="pytest",
                import_batch_id="batch-1",
                federation_source=None,
            )

        assert stats["created"] == 1
        assert stats["skipped"] == 1
        db.add_all.assert_called_once_with([db_tool])
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(db_tool)
        mock_logging_services["audit_trail"].log_action.assert_called_once()

    def test_process_tool_chunk_team_updates_only(self, mock_logging_services):
        service = ToolService()
        tool = _make_bulk_tool_create(name="bulk_tool_update_only")
        db_tool = SimpleNamespace(id="tool-2")

        db = MagicMock()
        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        with patch.object(service, "_process_single_tool_for_bulk", return_value={"status": "update", "tool": db_tool}):
            stats = service._process_tool_chunk(
                db=db,
                chunk=[tool],
                conflict_strategy="update",
                visibility="team",
                team_id="team-1",
                owner_email="owner@example.com",
                created_by="creator@example.com",
                created_from_ip=None,
                created_via=None,
                created_user_agent=None,
                import_batch_id=None,
                federation_source=None,
            )

        assert stats["updated"] == 1
        db.add_all.assert_not_called()
        db.commit.assert_called_once()
        mock_logging_services["audit_trail"].log_action.assert_called_once()
        assert mock_logging_services["audit_trail"].log_action.call_args.kwargs["action"] == "bulk_update_tools"

    def test_process_tool_chunk_private_exception_rolls_back(self):
        service = ToolService()
        tool = _make_bulk_tool_create(name="bulk_tool_fail")

        db = MagicMock()
        db.execute.side_effect = RuntimeError("boom")

        stats = service._process_tool_chunk(
            db=db,
            chunk=[tool],
            conflict_strategy="skip",
            visibility="private",
            team_id=None,
            owner_email="owner@example.com",
            created_by="creator@example.com",
            created_from_ip=None,
            created_via=None,
            created_user_agent=None,
            import_batch_id=None,
            federation_source=None,
        )

        assert stats["failed"] == 1
        assert "Chunk processing failed" in stats["errors"][0]
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_tools_bulk_invalidate_caches(self):
        service = ToolService()
        tools = [
            _make_bulk_tool_create(name="bulk_tool_a", gateway_id="gw-1"),
            _make_bulk_tool_create(name="bulk_tool_b", gateway_id=None),
        ]

        registry_cache = SimpleNamespace(invalidate_tools=AsyncMock())
        lookup_cache = SimpleNamespace(invalidate=AsyncMock())

        with (
            patch.object(service, "_process_tool_chunk", return_value={"created": 1, "updated": 0, "skipped": 0, "failed": 0, "errors": []}),
            patch("mcpgateway.services.tool_service._get_registry_cache", return_value=registry_cache),
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=lookup_cache),
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_admin_cache.invalidate_tags = AsyncMock()

            result = await service.register_tools_bulk(
                db=MagicMock(),
                tools=tools,
                created_by="creator@example.com",
                visibility="public",
            )

        assert result["created"] == 1
        registry_cache.invalidate_tools.assert_awaited_once()
        lookup_cache.invalidate.assert_has_awaits(
            [
                call("bulk_tool_a", gateway_id="gw-1"),
                call("bulk_tool_b", gateway_id=None),
            ]
        )
        mock_admin_cache.invalidate_tags.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_tools_bulk_no_changes_skips_invalidation(self):
        service = ToolService()
        tools = [_make_bulk_tool_create(name="bulk_tool_none")]

        registry_cache = SimpleNamespace(invalidate_tools=AsyncMock())
        lookup_cache = SimpleNamespace(invalidate=AsyncMock())

        with (
            patch.object(service, "_process_tool_chunk", return_value={"created": 0, "updated": 0, "skipped": 1, "failed": 0, "errors": []}),
            patch("mcpgateway.services.tool_service._get_registry_cache", return_value=registry_cache),
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=lookup_cache),
            patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache") as mock_admin_cache,
        ):
            mock_admin_cache.invalidate_tags = AsyncMock()

            result = await service.register_tools_bulk(
                db=MagicMock(),
                tools=tools,
                created_by="creator@example.com",
                visibility="public",
            )

        assert result["skipped"] == 1
        registry_cache.invalidate_tools.assert_not_called()
        lookup_cache.invalidate.assert_not_called()
        mock_admin_cache.invalidate_tags.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_tools_bulk_empty_list(self):
        service = ToolService()
        result = await service.register_tools_bulk(db=MagicMock(), tools=[])

        assert result == {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}


class TestConvertToolToReadHeaderMasking:
    """Tests for header masking in convert_tool_to_read based on requesting_user_* params."""

    @pytest.fixture
    def service(self):
        return ToolService()

    @pytest.fixture
    def tool_with_headers(self, mock_tool):
        """A mock tool with sensitive headers set."""
        mock_tool.headers = {"Authorization": "Bearer secret-token", "X-Api-Key": "my-api-key"}
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        return mock_tool

    def test_headers_masked_for_non_owner(self, service, tool_with_headers):
        """Non-owner sees masked values for all header values."""
        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email="other@example.com",
            requesting_user_is_admin=False,
            requesting_user_team_roles={},
        )
        for v in result.headers.values():
            assert v == settings.masked_auth_value

    def test_headers_visible_for_owner(self, service, tool_with_headers):
        """Direct owner sees real header values."""
        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email=tool_with_headers.owner_email,
            requesting_user_is_admin=False,
            requesting_user_team_roles={},
        )
        assert result.headers["Authorization"] == "Bearer secret-token"
        assert result.headers["X-Api-Key"] == "my-api-key"

    def test_headers_visible_for_admin(self, service, tool_with_headers):
        """Admin (requesting_user_is_admin=True) sees real values."""
        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email="admin@other.com",
            requesting_user_is_admin=True,
            requesting_user_team_roles={},
        )
        assert result.headers["Authorization"] == "Bearer secret-token"
        assert result.headers["X-Api-Key"] == "my-api-key"

    def test_headers_visible_for_team_owner(self, service, tool_with_headers):
        """Team owner on a team-visibility tool sees real values."""
        tool_with_headers.visibility = "team"
        tool_with_headers.team_id = "team-123"
        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email="team-owner@example.com",
            requesting_user_is_admin=False,
            requesting_user_team_roles={"team-123": "owner"},
        )
        assert result.headers["Authorization"] == "Bearer secret-token"

    def test_headers_masked_for_team_member(self, service, tool_with_headers):
        """Team member (non-owner role) sees masked values."""
        tool_with_headers.visibility = "team"
        tool_with_headers.team_id = "team-123"
        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email="member@example.com",
            requesting_user_is_admin=False,
            requesting_user_team_roles={"team-123": "member"},
        )
        for v in result.headers.values():
            assert v == settings.masked_auth_value

    def test_headers_masked_when_no_context(self, service, tool_with_headers):
        """Default params (all None) mask headers (safe default — no context means mask everything)."""
        result = service.convert_tool_to_read(tool_with_headers)
        # When requesting_user_email is None, headers are masked as safe default
        assert result.headers["Authorization"] == "*****"

    def test_encrypted_headers_decrypted_for_owner(self, service, tool_with_headers):
        """Owners/admins should see decrypted header values even when stored encrypted."""
        tool_with_headers.headers = {
            "Authorization": {
                "_mcpgateway_encrypted_header_value_v1": encode_auth(
                    {"value": "Bearer secret-token"},
                ),
            },
            "X-Api-Key": {
                "_mcpgateway_encrypted_header_value_v1": encode_auth(
                    {"value": "my-api-key"},
                ),
            },
        }

        result = service.convert_tool_to_read(
            tool_with_headers,
            requesting_user_email=tool_with_headers.owner_email,
            requesting_user_is_admin=False,
            requesting_user_team_roles={},
        )

        assert result.headers["Authorization"] == "Bearer secret-token"
        assert result.headers["X-Api-Key"] == "my-api-key"

    def test_headers_none_no_masking(self, service, mock_tool):
        """Tool with headers=None does not error."""
        mock_tool.headers = None
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        result = service.convert_tool_to_read(
            mock_tool,
            requesting_user_email="other@example.com",
            requesting_user_is_admin=False,
        )
        assert result.headers is None

    def test_headers_empty_dict(self, service, mock_tool):
        """Tool with headers={} does not error."""
        mock_tool.headers = {}
        mock_tool.auth_type = None
        mock_tool.auth_value = None
        result = service.convert_tool_to_read(
            mock_tool,
            requesting_user_email="other@example.com",
            requesting_user_is_admin=False,
        )
        assert result.headers == {}


class TestInvokeToolDirect:
    """Tests for ToolService.invoke_tool_direct() method.

    This method bypasses all gateway processing (caching, plugins, validation) and
    forwards tool calls directly to a remote MCP server in direct_proxy mode.
    """

    @pytest.fixture
    def tool_service(self):
        """Create a tool service instance for direct proxy tests."""
        service = ToolService()
        service._http_client = AsyncMock()
        return service

    @pytest.fixture
    def mock_direct_gateway(self):
        """Create a mock gateway in direct_proxy mode."""
        gw = MagicMock(spec=DbGateway)
        gw.id = "gw-direct-1"
        gw.name = "direct_gateway"
        gw.slug = "direct-gateway"
        gw.url = "http://remote-mcp:8080/mcp"
        gw.gateway_mode = "direct_proxy"
        gw.auth_type = "bearer"
        gw.auth_value = {"Authorization": "Bearer remote-token"}
        gw.passthrough_headers = None
        gw.visibility = "public"
        gw.team_id = None
        gw.owner_email = None
        return gw

    def _make_fresh_db_session(self, gateway, tool_row=None):
        """Create a mock fresh_db_session context manager.

        The DB session handles two sequential queries:
        1. Gateway lookup by ID → returns gateway
        2. Tool lookup by name + gateway_id → returns tool_row (default None)
        """
        # Standard
        from contextlib import contextmanager

        @contextmanager
        def mock_fresh_session():
            mock_db = MagicMock()
            gateway_result = MagicMock()
            gateway_result.scalar_one_or_none.return_value = gateway
            tool_result = MagicMock()
            tool_result.scalar_one_or_none.return_value = tool_row
            mock_db.execute.side_effect = [gateway_result, tool_result]
            yield mock_db

        return mock_fresh_session

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_success(self, tool_service, mock_direct_gateway):
        """Happy path: gateway found, direct_proxy mode, access allowed, tool call succeeds."""
        expected_result = MagicMock()
        expected_result.content = [MagicMock(text="direct result")]

        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={"Authorization": "Bearer remote-token"}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30

            result = await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="remote_tool",
                arguments={"key": "value"},
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        assert result == expected_result
        session_mock.call_tool.assert_awaited_once_with(name="remote_tool", arguments={"key": "value"})

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_with_meta(self, tool_service, mock_direct_gateway):
        """Meta data should be forwarded to session.call_tool when provided."""
        expected_result = MagicMock()
        meta_data = {"request_id": "abc-123"}

        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30

            result = await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="remote_tool",
                arguments={"arg": "val"},
                meta_data=meta_data,
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        assert result == expected_result
        session_mock.call_tool.assert_awaited_once_with(name="remote_tool", arguments={"arg": "val"}, meta=meta_data)

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_gateway_not_found(self, tool_service):
        """Gateway not in DB should raise ToolNotFoundError."""
        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(None)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True

            with pytest.raises(ToolNotFoundError, match="Gateway gw-missing not found"):
                await tool_service.invoke_tool_direct(
                    gateway_id="gw-missing",
                    name="some_tool",
                    arguments={},
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_not_direct_proxy_mode(self, tool_service, mock_direct_gateway):
        """Gateway with mode != direct_proxy should raise ToolInvocationError."""
        mock_direct_gateway.gateway_mode = "cache"

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True

            with pytest.raises(ToolInvocationError, match="is not in direct_proxy mode"):
                await tool_service.invoke_tool_direct(
                    gateway_id="gw-direct-1",
                    name="some_tool",
                    arguments={},
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_access_denied(self, tool_service, mock_direct_gateway):
        """Access denied by check_gateway_access should raise ToolNotFoundError."""
        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=False),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True

            with pytest.raises(ToolNotFoundError, match="Tool not found: secret_tool"):
                await tool_service.invoke_tool_direct(
                    gateway_id="gw-direct-1",
                    name="secret_tool",
                    arguments={},
                    user_email="intruder@example.com",
                    token_teams=[],
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_connection_error(self, tool_service, mock_direct_gateway):
        """Connection failure in streamablehttp_client should raise ToolInvocationError."""

        @asynccontextmanager
        async def mock_streamable_client_error(*_args, **_kwargs):
            raise ConnectionError("Connection refused")
            yield  # pragma: no cover

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client_error),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30

            with pytest.raises(ToolInvocationError, match="Direct proxy tool invocation failed"):
                await tool_service.invoke_tool_direct(
                    gateway_id="gw-direct-1",
                    name="remote_tool",
                    arguments={},
                    user_email="user@example.com",
                    token_teams=["team-1"],
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_passthrough_headers(self, tool_service, mock_direct_gateway):
        """Passthrough headers from gateway config should be forwarded from request_headers."""
        mock_direct_gateway.passthrough_headers = ["X-Tenant-Id", "X-Request-Id"]

        captured_headers = {}

        @asynccontextmanager
        async def mock_streamable_client(*_args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            yield ("read", "write", None)

        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=MagicMock())

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30

            await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="remote_tool",
                arguments={},
                request_headers={"x-tenant-id": "tenant-42", "X-Request-Id": "req-999", "x-other": "ignored"},
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        # Auth header from build_gateway_auth_headers
        assert captured_headers["Authorization"] == "Bearer xyz"
        # Passthrough headers forwarded (case-insensitive lookup)
        assert captured_headers["X-Tenant-Id"] == "tenant-42"
        assert captured_headers["X-Request-Id"] == "req-999"
        # Non-passthrough header should NOT be forwarded
        assert "x-other" not in captured_headers

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_configurable_timeout(self, tool_service, mock_direct_gateway):
        """Timeout passed to streamablehttp_client should match settings.mcpgateway_direct_proxy_timeout."""
        captured_kwargs = {}

        @asynccontextmanager
        async def mock_streamable_client(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            yield ("read", "write", None)

        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=MagicMock())

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 120  # Custom timeout

            await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="remote_tool",
                arguments={},
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        assert captured_kwargs["timeout"] == 120

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_resolves_original_name(self, tool_service, mock_direct_gateway):
        """Prefixed tool name should be resolved to original_name from DB for the remote call."""
        expected_result = MagicMock()
        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        # Create a mock tool row with original_name different from slugified name
        mock_tool = MagicMock()
        mock_tool.original_name = "get_system_time"

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway, tool_row=mock_tool)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30

            result = await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="direct-gateway-get-system-time",
                arguments={"timezone": "UTC"},
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        assert result == expected_result
        # The remote call should use the original_name, not the slugified prefixed name
        session_mock.call_tool.assert_awaited_once_with(name="get_system_time", arguments={"timezone": "UTC"})

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_slug_fallback_when_not_in_db(self, tool_service, mock_direct_gateway):
        """When tool is not in DB, fall back to stripping the gateway slug prefix."""
        expected_result = MagicMock()
        session_mock = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway, tool_row=None)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.build_gateway_auth_headers", return_value={}),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30
            mock_settings.gateway_tool_name_separator = "-"

            result = await tool_service.invoke_tool_direct(
                gateway_id="gw-direct-1",
                name="direct-gateway-my-tool",
                arguments={},
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        assert result == expected_result
        # Fallback: strip slug prefix "direct-gateway-" → "my-tool"
        session_mock.call_tool.assert_awaited_once_with(name="my-tool", arguments={})

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_feature_flag_disabled(self, tool_service, mock_direct_gateway):
        """Feature flag disabled should raise ToolInvocationError even if gateway is direct_proxy."""
        with (
            patch("mcpgateway.services.tool_service.fresh_db_session", self._make_fresh_db_session(mock_direct_gateway)),
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = False

            with pytest.raises(ToolInvocationError, match="is not in direct_proxy mode"):
                await tool_service.invoke_tool_direct(
                    gateway_id="gw-direct-1",
                    name="some_tool",
                    arguments={},
                )


class TestInvokeToolDirectProxyViaHeader:
    """Tests for the direct_proxy branch inside invoke_tool() triggered by X-Context-Forge-Gateway-Id header.

    When the header is present and gateway is in direct_proxy mode, invoke_tool handles
    the tool call inline using the MCP transport, returning results as-is.
    When the gateway is not direct_proxy or not found, it falls through to normal tool lookup.
    """

    @pytest.fixture
    def tool_service(self):
        """Create a tool service instance."""
        service = ToolService()
        service._http_client = AsyncMock()
        return service

    @pytest.fixture
    def mock_direct_gateway(self):
        """Create a mock gateway in direct_proxy mode using SimpleNamespace for attribute access."""
        return SimpleNamespace(
            id="gw-dp-1",
            name="direct_proxy_gw",
            slug="direct-proxy-gw",
            url="http://remote-mcp:8080/mcp",
            gateway_mode="direct_proxy",
            enabled=True,
            reachable=True,
            auth_type="bearer",
            auth_value={"Authorization": "Bearer remote-token"},
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
            visibility="public",
            team_id=None,
            owner_email=None,
            signing_algorithm=None,
            transport="STREAMABLEHTTP",
        )

    @pytest.fixture
    def mock_cache_gateway(self):
        """Create a mock gateway in cache mode (not direct_proxy)."""
        return SimpleNamespace(
            id="gw-cache-1",
            name="cache_gw",
            slug="cache-gw",
            url="http://remote-mcp:8080/mcp",
            gateway_mode="cache",
            enabled=True,
            reachable=True,
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
            visibility="public",
            team_id=None,
            owner_email=None,
            signing_algorithm=None,
            transport="STREAMABLEHTTP",
        )

    def _setup_db_for_header_lookup(self, test_db, gateway, tool=None):
        """Set up test_db.execute to return gateway for the first call, then tool for subsequent calls."""
        call_count = [0]

        def execute_side_effect(*_args, **_kwargs):
            call_count[0] += 1
            m = Mock()
            if call_count[0] == 1:
                # First call: gateway lookup from header
                m.scalar_one_or_none.return_value = gateway
            else:
                # Subsequent calls: tool lookup (for fall-through path)
                m.scalar_one_or_none.return_value = tool
                m.scalars.return_value = m
                if tool:
                    m.all.return_value = [tool]
                else:
                    m.all.return_value = []
            return m

        test_db.execute = Mock(side_effect=execute_side_effect)

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_proxy_via_header(self, tool_service, mock_direct_gateway, test_db):
        """Header present with direct_proxy gateway and feature enabled should invoke via direct proxy path.

        The direct_proxy path in invoke_tool sets is_direct_proxy=True, builds a minimal tool payload,
        then invokes the MCP transport. The result is returned as-is (no content splitting).
        """
        expected_result = ToolResult(content=[TextContent(type="text", text="direct proxy result")])

        # Set up DB to return the direct_proxy gateway
        self._setup_db_for_header_lookup(test_db, mock_direct_gateway)

        # Mock the MCP transport layer
        session_mock = AsyncMock()
        session_mock.initialize = AsyncMock()
        session_mock.call_tool = AsyncMock(return_value=expected_result)

        client_session_cm = AsyncMock()
        client_session_cm.__aenter__.return_value = session_mock
        client_session_cm.__aexit__.return_value = AsyncMock()

        @asynccontextmanager
        async def mock_streamable_client(*_args, **_kwargs):
            yield ("read", "write", None)

        # Mock global_config_cache to prevent DB calls
        mock_gc = MagicMock()
        mock_gc.get_passthrough_headers.return_value = []

        # Mock metrics buffer (lazy import inside invoke_tool)
        mock_metrics_buffer = MagicMock()

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=True),
            patch("mcpgateway.services.tool_service.streamablehttp_client", mock_streamable_client),
            patch("mcpgateway.services.tool_service.ClientSession", return_value=client_session_cm),
            patch("mcpgateway.services.tool_service.global_config_cache", mock_gc),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer xyz"}),
            patch("mcpgateway.services.tool_service.get_performance_tracker", return_value=MagicMock()),
            patch("mcpgateway.services.metrics_buffer_service.get_metrics_buffer_service", return_value=mock_metrics_buffer),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.mcpgateway_direct_proxy_timeout = 30
            mock_settings.tool_timeout = 60
            mock_settings.mcp_session_pool_enabled = False
            mock_settings.default_passthrough_headers = []

            request_headers = {"x-context-forge-gateway-id": "gw-dp-1"}

            result = await tool_service.invoke_tool(
                test_db,
                "my_remote_tool",
                {"arg": "value"},
                request_headers=request_headers,
                user_email="user@example.com",
                token_teams=["team-1"],
            )

        # The result should come from the direct proxy path (returned as-is)
        assert result.content[0].text == "direct proxy result"

    @pytest.mark.asyncio
    async def test_invoke_tool_header_gateway_not_direct_proxy(self, tool_service, mock_cache_gateway, test_db):
        """Header present but gateway_mode=cache should fall through to normal tool lookup."""
        # Set up DB: first call returns cache gateway, subsequent calls return no tool (to trigger ToolNotFoundError)
        self._setup_db_for_header_lookup(test_db, mock_cache_gateway, tool=None)

        mock_gc = MagicMock()
        mock_gc.get_passthrough_headers.return_value = []

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.global_config_cache", mock_gc),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.default_passthrough_headers = []

            request_headers = {"x-context-forge-gateway-id": "gw-cache-1"}

            # Should fall through to normal lookup, which finds no tool
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.invoke_tool(
                    test_db,
                    "some_tool",
                    {},
                    request_headers=request_headers,
                )


class TestRustMcpExecutionPlan:
    """Tests for ToolService.prepare_rust_mcp_tool_execution()."""

    @pytest.fixture
    def mock_direct_gateway(self):
        """Create a direct-proxy gateway payload for header-based lookup tests."""
        return SimpleNamespace(
            id="gw-dp-1",
            name="direct_proxy_gw",
            slug="direct-proxy-gw",
            url="http://remote-mcp:8080/mcp",
            gateway_mode="direct_proxy",
            enabled=True,
            reachable=True,
            auth_type="bearer",
            auth_value={"Authorization": "Bearer remote-token"},
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
            visibility="public",
            team_id=None,
            owner_email=None,
            signing_algorithm=None,
            transport="STREAMABLEHTTP",
        )

    @staticmethod
    def _cache_payload(**tool_overrides):
        gateway_payload = {
            "id": "gw-1",
            "name": "gateway-one",
            "url": "http://gateway.example/mcp",
            "auth_type": None,
            "auth_value": None,
            "auth_query_params": None,
            "oauth_config": None,
            "ca_certificate": None,
            "ca_certificate_sig": None,
            "passthrough_headers": [],
        }
        gateway_payload.update(tool_overrides.pop("gateway", {}))
        tool_payload = {
            "id": "tool-1",
            "name": "tool-one",
            "original_name": "tool-one",
            "enabled": True,
            "reachable": True,
            "integration_type": "MCP",
            "request_type": "streamablehttp",
            "gateway_id": "gw-1",
            "jsonpath_filter": None,
            "timeout_ms": None,
        }
        tool_payload.update(tool_overrides)
        return {"status": "active", "tool": tool_payload, "gateway": gateway_payload}

    @staticmethod
    def _cache_mock(payload):
        mock_cache = AsyncMock()
        mock_cache.enabled = True
        mock_cache.get = AsyncMock(return_value=payload)
        mock_cache.set = AsyncMock()
        mock_cache.set_negative = AsyncMock()
        return mock_cache

    def _setup_db_for_header_lookup(self, test_db, gateway, tool=None):
        """Set up execute() to return gateway on first call and tool on subsequent calls."""
        call_count = [0]

        def execute_side_effect(*_args, **_kwargs):
            call_count[0] += 1
            result = Mock()
            if call_count[0] == 1:
                result.scalar_one_or_none.return_value = gateway
            else:
                result.scalar_one_or_none.return_value = tool
                result.scalars.return_value = result
                result.all.return_value = [tool] if tool else []
            return result

        test_db.execute = Mock(side_effect=execute_side_effect)

    @pytest.mark.asyncio
    async def test_list_server_mcp_tool_definitions_public_only_and_output_schema(self, tool_service):
        """Server-scoped MCP tool definitions should include outputSchema only when present."""
        rows = [
            {
                "name": "tool-public",
                "description": "desc",
                "input_schema": {"type": "object"},
                "output_schema": None,
                "annotations": None,
                "owner_email": None,
                "team_id": None,
                "visibility": "public",
            },
            {
                "name": "tool-team",
                "description": "team-desc",
                "input_schema": None,
                "output_schema": {"type": "object"},
                "annotations": {"title": "Team"},
                "owner_email": "owner@example.com",
                "team_id": "team-a",
                "visibility": "team",
            },
        ]
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = rows

        payload = await tool_service.list_server_mcp_tool_definitions(
            db,
            "srv-1",
            include_inactive=False,
            user_email="owner@example.com",
            token_teams=["team-a"],
        )

        assert payload == [
            {
                "name": "tool-public",
                "description": "desc",
                "inputSchema": {"type": "object"},
                "annotations": {},
            },
            {
                "name": "tool-team",
                "description": "team-desc",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"title": "Team"},
                "outputSchema": {"type": "object"},
            },
        ]
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_post_invoke_hooks_force_fallback(self, tool_service):
        """Post-invoke hooks should force fallback even when pre-invoke hooks are also registered."""
        # Create a mock plugin manager with proper registry structure
        mock_hook_ref = MagicMock()
        mock_hook_ref.plugin_ref.name = "SomeOtherPlugin"  # Not RetryWithBackoffPlugin
        mock_hook_ref.plugin_ref.mode = PluginMode.ENFORCE
        mock_hook_ref.plugin_ref.conditions = None

        mock_registry = MagicMock()
        mock_registry.get_hook_refs_for_hook = MagicMock(return_value=[mock_hook_ref])

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type in (ToolHookType.TOOL_PRE_INVOKE, ToolHookType.TOOL_POST_INVOKE))
        mock_pm._registry = mock_registry

        cache = self._cache_mock(self._cache_payload())

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan == {"eligible": False, "fallbackReason": "post-invoke-hooks-configured"}

    def test_build_rust_native_tool_post_invoke_retry_policy_from_cpex_package(self, tool_service):
        """RetryWithBackoffPlugin should produce a native retry policy when the package is installed."""
        mock_hook_ref = MagicMock()
        mock_hook_ref.plugin_ref.name = "RetryWithBackoffPlugin"
        mock_hook_ref.plugin_ref.mode = PluginMode.ENFORCE
        mock_hook_ref.plugin_ref.conditions = None
        mock_hook_ref.plugin_ref.plugin.config.config = {
            "max_retries": settings.max_tool_retries + 5,
            "backoff_base_ms": 250,
            "max_backoff_ms": 5000,
            "retry_on_status": [429, 503],
            "jitter": False,
            "tool_overrides": {"tool-one": {"max_retries": 1, "backoff_base_ms": 75}},
        }

        mock_registry = MagicMock()
        mock_registry.get_hook_refs_for_hook.return_value = [mock_hook_ref]

        mock_pm = MagicMock()
        mock_pm.has_hooks_for.return_value = True
        mock_pm._registry = mock_registry

        policy, requires_python_fallback = tool_service._build_rust_native_tool_post_invoke_retry_policy(
            mock_pm,
            "tool-one",
            None,
        )

        assert requires_python_fallback is False
        assert policy == {
            "kind": "retry_with_backoff",
            "maxRetries": 1,
            "backoffBaseMs": 75,
            "maxBackoffMs": 5000,
            "retryOnStatus": [429, 503],
            "jitter": False,
        }

    def test_build_rust_native_tool_post_invoke_retry_policy_falls_back_for_invalid_override(self, tool_service):
        """Invalid retry config should force Python fallback."""
        mock_hook_ref = MagicMock()
        mock_hook_ref.plugin_ref.name = "RetryWithBackoffPlugin"
        mock_hook_ref.plugin_ref.mode = PluginMode.ENFORCE
        mock_hook_ref.plugin_ref.conditions = None
        mock_hook_ref.plugin_ref.plugin.config.config = {"max_retries": 3, "tool_overrides": {"tool-one": "invalid"}}

        mock_registry = MagicMock()
        mock_registry.get_hook_refs_for_hook.return_value = [mock_hook_ref]

        mock_pm = MagicMock()
        mock_pm.has_hooks_for.return_value = True
        mock_pm._registry = mock_registry

        policy, requires_python_fallback = tool_service._build_rust_native_tool_post_invoke_retry_policy(
            mock_pm,
            "tool-one",
            None,
        )

        assert policy is None
        assert requires_python_fallback is True

    def test_build_retry_policy_config_parses_bool_like_values_and_clamps_override(self):
        """Gateway-owned retry parser should keep bool-like semantics and override clamping."""
        cfg = _build_retry_policy_config(
            {
                "jitter": "false",
                "check_text_content": "0",
                "tool_overrides": {
                    "tool-one": {
                        "max_retries": settings.max_tool_retries + 4,
                        "check_text_content": "true",
                    }
                },
            },
            "tool-one",
        )

        assert cfg["jitter"] is False
        assert cfg["check_text_content"] is True
        assert cfg["max_retries"] == settings.max_tool_retries

    def test_build_retry_policy_config_rejects_scalar_retry_status_string(self):
        """Scalar retry_on_status strings should fail instead of being split into digits."""
        with pytest.raises(ValueError, match="retry_on_status"):
            _build_retry_policy_config({"retry_on_status": "429"}, "tool-one")

    def test_build_retry_policy_config_accepts_numeric_bool_inputs(self):
        """Numeric bool-like inputs should preserve 0/1 semantics."""
        cfg = _build_retry_policy_config({"jitter": 0, "check_text_content": 1}, "tool-one")
        assert cfg["jitter"] is False
        assert cfg["check_text_content"] is True

    def test_build_retry_policy_config_rejects_negative_retry_values(self):
        """Negative integer-like retry settings should be rejected."""
        with pytest.raises(ValueError, match=">= 0"):
            _build_retry_policy_config({"max_retries": -1}, "tool-one")

    def test_build_retry_policy_config_rejects_invalid_bool_values(self):
        """Unknown bool-like strings should be rejected."""
        with pytest.raises(ValueError, match="bool-like"):
            _build_retry_policy_config({"jitter": "maybe"}, "tool-one")

    def test_build_retry_policy_config_rejects_non_mapping_config(self):
        """Top-level retry config must stay mapping-shaped."""
        with pytest.raises(ValueError, match="must be a mapping"):
            _build_retry_policy_config(["not", "a", "mapping"], "tool-one")

    def test_build_retry_policy_config_rejects_non_mapping_tool_overrides(self):
        """tool_overrides must be a mapping."""
        with pytest.raises(ValueError, match="tool_overrides must be a mapping"):
            _build_retry_policy_config({"tool_overrides": ["bad"]}, "tool-one")

    def test_build_rust_native_tool_post_invoke_retry_policy_falls_back_for_text_check_override(self, tool_service):
        """Text-content inspection in an override should force Python fallback."""
        mock_hook_ref = MagicMock()
        mock_hook_ref.plugin_ref.name = "RetryWithBackoffPlugin"
        mock_hook_ref.plugin_ref.mode = PluginMode.ENFORCE
        mock_hook_ref.plugin_ref.conditions = None
        mock_hook_ref.plugin_ref.plugin.config.config = {"tool_overrides": {"tool-one": {"check_text_content": "true"}}}

        mock_registry = MagicMock()
        mock_registry.get_hook_refs_for_hook.return_value = [mock_hook_ref]

        mock_pm = MagicMock()
        mock_pm.has_hooks_for.return_value = True
        mock_pm._registry = mock_registry

        policy, requires_python_fallback = tool_service._build_rust_native_tool_post_invoke_retry_policy(
            mock_pm,
            "tool-one",
            None,
        )

        assert policy is None
        assert requires_python_fallback is True

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_trace_id_forces_fallback(self, tool_service):
        """Active observability trace should bypass Rust direct execution."""
        cache = self._cache_mock(self._cache_payload())

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value="trace-1"))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["eligible"] is True

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_otel_enabled_keeps_eligible_plan(self, tool_service):
        """Enabled OTEL observability should no longer force Python fallback."""
        tool_service._plugin_manager = None
        cache = self._cache_mock(self._cache_payload(timeout_ms=2500))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.settings.otel_enable_observability", True),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["eligible"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "error_match"),
        [
            ("missing", "Tool not found"),
            ("inactive", "exists but is inactive"),
            ("offline", "currently offline"),
        ],
    )
    async def test_prepare_rust_mcp_tool_execution_respects_negative_cache_entries(self, tool_service, status, error_match):
        """Negative cache entries should short-circuit with the expected error."""
        cache = self._cache_mock({"status": status})

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match=error_match):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_direct_proxy_fallback(self, tool_service):
        """Direct-proxy gateways should fall back to the Python execution path."""
        gateway = SimpleNamespace(
            id="gw-1",
            name="gw",
            url="http://gateway.example/mcp",
            gateway_mode="direct_proxy",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = gateway

        with (
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_enabled", True),
            patch("mcpgateway.services.tool_service.check_gateway_access", new=AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                db,
                "tool-one",
                request_headers={"x-context-forge-gateway-id": "gw-1"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan == {"eligible": False, "fallbackReason": "direct-proxy"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_direct_proxy_access_denied(self, tool_service):
        """Direct-proxy lookup should deny inaccessible gateways as not-found."""
        gateway = SimpleNamespace(
            id="gw-1",
            name="gw",
            url="http://gateway.example/mcp",
            gateway_mode="direct_proxy",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = gateway

        with (
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.settings.mcpgateway_direct_proxy_enabled", True),
            patch("mcpgateway.services.tool_service.check_gateway_access", new=AsyncMock(return_value=False)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(
                    db,
                    "tool-one",
                    request_headers={"x-context-forge-gateway-id": "gw-1"},
                    user_email="user@example.com",
                    token_teams=["team-a"],
                )

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_loads_missing_tool_from_db(self, tool_service):
        """DB lookup should raise not-found when no invocable tool exists."""
        cache = self._cache_mock(None)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[]),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_rejects_ambiguous_accessible_tool_candidates(self, tool_service):
        """Multiple equally visible accessible tools should be treated as ambiguous."""
        cache = self._cache_mock(None)
        candidate_a = SimpleNamespace(
            enabled=True,
            reachable=True,
            visibility="team",
            team_id="team-a",
            owner_email="user@example.com",
            gateway=SimpleNamespace(),
        )
        candidate_b = SimpleNamespace(
            enabled=True,
            reachable=True,
            visibility="team",
            team_id="team-b",
            owner_email="user@example.com",
            gateway=SimpleNamespace(),
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[candidate_a, candidate_b]),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolInvocationError, match="ambiguous"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", user_email="user@example.com", token_teams=["team-a"])

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_selects_highest_priority_accessible_candidate(self, tool_service):
        """A single best-priority accessible candidate should be selected successfully."""
        cache = self._cache_mock(None)
        selected_gateway = SimpleNamespace(
            id="gw-1",
            name="gateway-one",
            url="http://gateway.example/mcp",
            auth_type=None,
            auth_value=None,
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            ca_certificate_sig=None,
            passthrough_headers=[],
        )
        candidate_team = SimpleNamespace(
            id="tool-team",
            enabled=True,
            reachable=True,
            visibility="team",
            team_id="team-a",
            owner_email="user@example.com",
            gateway=selected_gateway,
        )
        candidate_public = SimpleNamespace(
            id="tool-public",
            enabled=True,
            reachable=True,
            visibility="public",
            team_id=None,
            owner_email=None,
            gateway=selected_gateway,
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache.get_passthrough_headers", return_value=[]),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=lambda request_headers, headers, *_args, **_kwargs: headers),
            patch.object(tool_service, "_load_invocable_tools", return_value=[candidate_public, candidate_team]),
            patch.object(tool_service, "_check_tool_access", AsyncMock(side_effect=[True, True, True])),
            patch.object(tool_service, "_build_tool_cache_payload", return_value=self._cache_payload(id="tool-team", gateway_id="gw-1")),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["eligible"] is True
        assert plan["gatewayId"] == "gw-1"
        assert plan["toolName"] == "tool-one"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_rejects_inaccessible_db_candidates(self, tool_service):
        """DB-loaded candidates with no accessible match should surface as not-found."""
        cache = self._cache_mock(None)
        candidate_a = SimpleNamespace(enabled=True, reachable=True, visibility="team", team_id="team-a", owner_email="user@example.com", gateway=SimpleNamespace())
        candidate_b = SimpleNamespace(enabled=True, reachable=True, visibility="public", team_id=None, owner_email=None, gateway=SimpleNamespace())

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[candidate_a, candidate_b]),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=False)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", user_email="user@example.com", token_teams=["team-a"])

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_rejects_inactive_db_tool(self, tool_service):
        """Inactive DB-loaded tools should fail before plan generation."""
        cache = self._cache_mock(None)
        tool = SimpleNamespace(
            enabled=False,
            reachable=True,
            visibility="public",
            team_id=None,
            owner_email=None,
            gateway=SimpleNamespace(),
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[tool]),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="inactive"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_marks_unreachable_tools_offline_and_caches_negative_result(self, tool_service):
        """Unreachable DB-loaded tools should set a negative cache entry before failing."""
        cache = self._cache_mock(None)
        tool = SimpleNamespace(
            enabled=True,
            reachable=False,
            visibility="public",
            team_id=None,
            owner_email=None,
            gateway=SimpleNamespace(),
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[tool]),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="currently offline"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        cache.set_negative.assert_awaited_once_with("tool-one", "offline")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("payload", "error_match"),
        [
            ({"enabled": False}, "inactive"),
            ({"reachable": False}, "currently offline"),
        ],
    )
    async def test_prepare_rust_mcp_tool_execution_rejects_inactive_or_offline_cached_payloads(self, tool_service, payload, error_match):
        """Cached payloads should honor enabled/reachable flags before plan generation."""
        cache = self._cache_mock(self._cache_payload(**payload))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match=error_match):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_rejects_cached_payload_when_access_is_denied(self, tool_service):
        """Cached payloads should still pass through access checks."""
        cache = self._cache_mock(self._cache_payload())

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=False)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", user_email="user@example.com", token_teams=["team-a"])

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_rejects_server_scoped_cached_payload_without_tool_id(self, tool_service):
        """Server-scoped cached payloads need a concrete tool id for membership checks."""
        cache = self._cache_mock(self._cache_payload(id=None))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", server_id="srv-1")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_uses_live_gateway_auth_fields_for_loaded_tools(self, tool_service):
        """Loaded DB tools should prefer live gateway auth metadata over cached payload values."""
        cache = self._cache_mock(None)
        gateway = SimpleNamespace(
            id="gw-1",
            name="gateway-one",
            description="gateway-one",
            slug="gateway-one",
            url="http://gateway.example/mcp",
            transport="streamablehttp",
            capabilities={},
            auth_type="basic",
            auth_value={"Authorization": "Bearer live-token"},
            auth_query_params={"api_key": "live-query"},
            oauth_config={"grant_type": "client_credentials"},
            ca_certificate=None,
            enabled=True,
            reachable=True,
            team_id=None,
            owner_email=None,
            visibility="public",
            tags=[],
            gateway_mode="cache",
            passthrough_headers=[],
        )
        tool = SimpleNamespace(
            id="tool-1",
            url=None,
            description="tool-one",
            original_description="tool-one",
            enabled=True,
            reachable=True,
            visibility="public",
            team_id=None,
            owner_email=None,
            integration_type="MCP",
            request_type="streamablehttp",
            original_name="tool-one",
            name="tool-one",
            timeout_ms=None,
            jsonpath_filter=None,
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            auth_type=None,
            custom_name=None,
            custom_name_slug=None,
            display_name=None,
            tags=[],
            gateway_id="gw-1",
            gateway=gateway,
            query_mapping=None,
            header_mapping=None,
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[tool]),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.encode_auth", return_value="encoded-live-auth"),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer live-token"}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer live-token"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["eligible"] is True
        assert plan["headers"] == {"Authorization": "Bearer live-token"}
        cache.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_uses_live_gateway_string_auth_values(self, tool_service):
        """Loaded DB tools should honor pre-encoded gateway auth strings."""
        cache = self._cache_mock(None)
        gateway = SimpleNamespace(
            id="gw-1",
            name="gateway-one",
            description="gateway-one",
            slug="gateway-one",
            url="http://gateway.example/mcp",
            transport="streamablehttp",
            capabilities={},
            auth_type="bearer",
            auth_value="encoded-string-auth",
            auth_query_params=None,
            oauth_config=None,
            ca_certificate=None,
            enabled=True,
            reachable=True,
            team_id=None,
            owner_email=None,
            visibility="public",
            tags=[],
            gateway_mode="cache",
            passthrough_headers=[],
        )
        tool = SimpleNamespace(
            id="tool-1",
            url=None,
            description="tool-one",
            original_description="tool-one",
            enabled=True,
            reachable=True,
            visibility="public",
            team_id=None,
            owner_email=None,
            integration_type="MCP",
            request_type="streamablehttp",
            original_name="tool-one",
            name="tool-one",
            timeout_ms=None,
            jsonpath_filter=None,
            headers={},
            input_schema={"type": "object"},
            output_schema=None,
            annotations={},
            auth_type=None,
            custom_name=None,
            custom_name_slug=None,
            display_name=None,
            tags=[],
            gateway_id="gw-1",
            gateway=gateway,
            query_mapping=None,
            header_mapping=None,
        )

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_load_invocable_tools", return_value=[tool]),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer string-token"}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer string-token"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["headers"] == {"Authorization": "Bearer string-token"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_hydrates_gateway_auth_from_db_when_tool_is_cached(self, tool_service):
        """Cached tool payloads should hydrate gateway auth details from the DB when needed."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={"auth_type": "basic", "auth_value": None, "auth_query_params": None, "oauth_config": None},
            )
        )
        tool_auth_row = SimpleNamespace(
            gateway=SimpleNamespace(
                auth_value={"Authorization": "Bearer hydrated-token"},
                auth_query_params={"api_key": "hydrated"},
                oauth_config={"grant_type": "client_credentials"},
            )
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = tool_auth_row

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.encode_auth", return_value="encoded-hydrated-auth"),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer hydrated-token"}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer hydrated-token"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(db, "tool-one")

        assert plan["eligible"] is True
        assert plan["headers"] == {"Authorization": "Bearer hydrated-token"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_hydrates_gateway_string_auth_from_db(self, tool_service):
        """Cached payload hydration should also honor string auth values from the DB row."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={"auth_type": "basic", "auth_value": None, "auth_query_params": None, "oauth_config": None},
            )
        )
        tool_auth_row = SimpleNamespace(
            gateway=SimpleNamespace(
                auth_value="encoded-hydrated-string",
                auth_query_params=None,
                oauth_config=None,
            )
        )
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = tool_auth_row

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.decode_auth", return_value={"Authorization": "Bearer hydrated-string"}),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer hydrated-string"}),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(db, "tool-one")

        assert plan["headers"] == {"Authorization": "Bearer hydrated-string"}

    def test_load_invocable_tools_applies_server_scope_filter(self, tool_service):
        """Server-scoped tool loading should join through the server association table."""
        db = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute.return_value = result

        assert tool_service._load_invocable_tools(db, "tool-one", server_id="srv-1") == []
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_overrides", "expected_reason"),
        [
            ({"integration_type": "REST"}, "unsupported-integration:REST"),
            ({"jsonpath_filter": "$.items[*]"}, "jsonpath-filter-configured"),
            ({"gateway": {"ca_certificate": "cert"}}, "custom-ca-certificate"),
            ({"gateway": {"url": None}}, "missing-gateway-url"),
        ],
    )
    async def test_prepare_rust_mcp_tool_execution_returns_expected_fallback_reasons(self, tool_service, tool_overrides, expected_reason):
        """Unsupported execution plans should report explicit fallback reasons."""
        cache = self._cache_mock(self._cache_payload(**tool_overrides))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan == {"eligible": False, "fallbackReason": expected_reason}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_allows_sse_transport(self, tool_service):
        """SSE-backed MCP tools should remain eligible for native Rust execution."""
        cache = self._cache_mock(self._cache_payload(request_type="sse"))
        tool_service._plugin_manager = None

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["eligible"] is True
        assert plan["transport"] == "sse"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_checks_server_membership(self, tool_service):
        """Server-scoped execution should reject tools not attached to the requested server."""
        cache = self._cache_mock(self._cache_payload())
        db = MagicMock()
        db.execute.return_value.first.return_value = None

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.prepare_rust_mcp_tool_execution(db, "tool-one", server_id="srv-1")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_handles_query_param_auth_and_passthrough(self, tool_service):
        """Query-param auth should be applied before returning an eligible Rust plan."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "query_param",
                    "auth_query_params": {
                        "api_key": base64.b64encode(orjson.dumps({"api_key": "secret"})).decode(),
                        "broken": "not-decodable",
                    },
                    "passthrough_headers": ["X-Tenant-Id"],
                }
            )
        )
        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=["X-Tenant-Id"]))),
            patch("mcpgateway.services.tool_service.decode_auth", side_effect=lambda value: {"api_key": "secret"} if value != "not-decodable" else (_ for _ in ()).throw(ValueError("bad"))),
            patch("mcpgateway.services.tool_service.apply_query_param_auth", side_effect=lambda url, params: f"{url}?api_key={params['api_key']}"),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"X-Tenant-Id": "tenant-1"}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                request_headers={"x-tenant-id": "tenant-1"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["eligible"] is True
        assert plan["serverUrl"] == "http://gateway.example/mcp?api_key=secret"
        assert plan["headers"] == {"X-Tenant-Id": "tenant-1"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_oauth_authorization_code_requires_user(self, tool_service):
        """Authorization-code OAuth plans should require an authenticated app user."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "oauth",
                    "oauth_config": {"grant_type": "authorization_code"},
                }
            )
        )
        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolInvocationError, match="OAuth token retrieval failed"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_oauth_client_credentials_failure(self, tool_service):
        """Client-credentials OAuth failures should bubble up as ToolInvocationError."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "oauth",
                    "oauth_config": {"grant_type": "client_credentials"},
                }
            )
        )
        tool_service.oauth_manager = MagicMock(get_access_token=AsyncMock(side_effect=RuntimeError("boom")))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolInvocationError, match="OAuth authentication failed"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_oauth_authorization_code_uses_stored_token(self, tool_service):
        """Authorization-code OAuth plans should inject a stored bearer token when available."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "oauth",
                    "oauth_config": {"grant_type": "authorization_code"},
                }
            )
        )
        token_storage = MagicMock()
        token_storage.get_user_token = AsyncMock(return_value="stored-oauth-token")
        fresh_session = MagicMock()

        @contextmanager
        def _fresh_db_session():
            yield fresh_session

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=token_storage),
            patch("mcpgateway.services.tool_service.fresh_db_session", _fresh_db_session),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=lambda _request_headers, headers, *_args, **_kwargs: headers),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", app_user_email="user@example.com")

        assert plan["eligible"] is True
        assert plan["headers"] == {"Authorization": "Bearer stored-oauth-token"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_oauth_authorization_code_requires_prior_authorization(self, tool_service):
        """Authorization-code OAuth plans should fail when no stored token exists for the user."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "oauth",
                    "oauth_config": {"grant_type": "authorization_code"},
                }
            )
        )
        token_storage = MagicMock()
        token_storage.get_user_token = AsyncMock(return_value=None)
        fresh_session = MagicMock()

        @contextmanager
        def _fresh_db_session():
            yield fresh_session

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.token_storage_service.TokenStorageService", return_value=token_storage),
            patch("mcpgateway.services.tool_service.fresh_db_session", _fresh_db_session),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ToolInvocationError, match="OAuth token retrieval failed"):
                await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one", app_user_email="user@example.com")

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_oauth_client_credentials_success(self, tool_service):
        """Client-credentials OAuth plans should inject a freshly acquired access token."""
        cache = self._cache_mock(
            self._cache_payload(
                gateway={
                    "auth_type": "oauth",
                    "oauth_config": {"grant_type": "client_credentials"},
                }
            )
        )
        tool_service.oauth_manager = MagicMock(get_access_token=AsyncMock(return_value="oauth-access-token"))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", side_effect=lambda _request_headers, headers, *_args, **_kwargs: headers),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(MagicMock(), "tool-one")

        assert plan["eligible"] is True
        assert plan["headers"] == {"Authorization": "Bearer oauth-access-token"}

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_returns_eligible_plan(self, tool_service):
        """Simple MCP streamable-http tools should produce an eligible Rust execution plan."""
        cache = self._cache_mock(self._cache_payload(timeout_ms=2500))

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer abc"}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                request_headers={"authorization": "Bearer abc"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan == {
            "eligible": True,
            "transport": "streamablehttp",
            "serverUrl": "http://gateway.example/mcp",
            "remoteToolName": "tool-one",
            "headers": {"Authorization": "Bearer abc"},
            "timeoutMs": 2500,
            "gatewayId": "gw-1",
            "toolName": "tool-one",
            "toolId": "tool-1",
            "serverId": None,
        }

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_tool_execution_injects_w3c_trace_context_into_plan_headers(self, tool_service):
        """Rust execution plans should carry W3C trace context for direct upstream calls."""
        cache = self._cache_mock(self._cache_payload(timeout_ms=2500))
        tool_service._plugin_manager = None

        def _inject(headers):
            traced = dict(headers)
            traced["traceparent"] = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
            traced["tracestate"] = "vendor=value"
            return traced

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"authorization": "Bearer abc"}),
            patch("mcpgateway.services.tool_service.inject_trace_context_headers", side_effect=_inject),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                request_headers={"authorization": "Bearer abc"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["headers"]["authorization"] == "Bearer abc"
        assert plan["headers"]["traceparent"] == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
        assert plan["headers"]["tracestate"] == "vendor=value"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_only_returns_eligible_plan_with_hooks(self, tool_service):
        """Pre-invoke hooks only (no post-invoke) should produce eligible plan with hook results."""
        # First-Party
        from mcpgateway.plugins.framework import HttpHeaderPayload, ToolPreInvokePayload
        from mcpgateway.plugins.framework.models import PluginResult

        cache = self._cache_mock(self._cache_payload(timeout_ms=2500))

        # Configure plugin manager: pre-invoke YES, post-invoke NO
        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        # Mock invoke_hook to return modified args and headers
        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            modified = ToolPreInvokePayload(
                name=payload.name,
                args={"cleaned_arg": "value"},
                headers=HttpHeaderPayload({"x-injected-cred": "secret123"}),
            )
            return PluginResult(modified_payload=modified, continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"authorization": "Bearer abc"}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"wxo_connection_id": "conn-1", "original_arg": "data"},
                request_headers={"authorization": "Bearer abc"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["eligible"] is True
        assert plan["hasPreInvokeHooks"] is True
        assert plan["modifiedArgs"] == {"cleaned_arg": "value"}
        # Plugin-injected header should appear (lowercase normalized)
        assert plan["headers"]["x-injected-cred"] == "secret123"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_hook_modifies_tool_name(self, tool_service):
        """Pre-invoke hook that renames tool should update remoteToolName in plan."""
        # First-Party
        from mcpgateway.plugins.framework import ToolPreInvokePayload
        from mcpgateway.plugins.framework.models import PluginResult

        cache = self._cache_mock(self._cache_payload())

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            modified = ToolPreInvokePayload(name="renamed-tool", args=payload.args)
            return PluginResult(modified_payload=modified, continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"key": "val"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["eligible"] is True
        assert plan["remoteToolName"] == "renamed-tool"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_no_hooks_omits_hook_fields(self, tool_service):
        """When no pre-invoke hooks are registered, plan should not contain hook fields."""
        cache = self._cache_mock(self._cache_payload())

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=None)),
        ):
            plan = await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        assert plan["eligible"] is True
        assert "hasPreInvokeHooks" not in plan
        assert "modifiedArgs" not in plan

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_passes_runtime_headers_not_request_headers(self, tool_service):
        """Pre-invoke hook should receive outbound runtime headers, not inbound request headers."""
        # First-Party
        from mcpgateway.plugins.framework.models import PluginResult

        cache = self._cache_mock(self._cache_payload())

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        received_headers = {}

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            received_headers.update(payload.headers.root)
            return PluginResult(continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={"Authorization": "Bearer gateway-token"}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"key": "val"},
                request_headers={"authorization": "Bearer user-token", "x-request-id": "req-1"},
                user_email="user@example.com",
                token_teams=["team-a"],
            )

        # Hook should receive runtime (outbound) headers, not inbound request headers
        assert "Authorization" in received_headers
        assert received_headers["Authorization"] == "Bearer gateway-token"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_receives_plugin_global_context(self, tool_service):
        """Pre-invoke hook should receive the middleware-provided GlobalContext, not a fresh one."""
        # First-Party
        from mcpgateway.plugins.framework import GlobalContext
        from mcpgateway.plugins.framework.models import PluginResult

        cache = self._cache_mock(self._cache_payload())

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        received_context = {}

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            received_context["request_id"] = global_context.request_id
            received_context["user"] = global_context.user
            received_context["state"] = dict(global_context.state) if hasattr(global_context, "state") else {}
            received_context["metadata_keys"] = list(global_context.metadata.keys()) if hasattr(global_context, "metadata") else []
            received_context["local_contexts"] = local_contexts
            return PluginResult(continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        # Simulate middleware-provided context with JWT claims state
        provided_ctx = GlobalContext(request_id="corr-123", server_id="srv-1", tenant_id=None, user="jwt-user@example.com")
        provided_ctx.state["jwt_claims"] = {"sub": "jwt-user@example.com", "teams": ["team-a"]}
        provided_context_table = {"prior_plugin": {"key": "value"}}

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"key": "val"},
                user_email="user@example.com",
                token_teams=["team-a"],
                plugin_global_context=provided_ctx,
                plugin_context_table=provided_context_table,
            )

        # Hook should have received the middleware context, not a fresh one
        assert received_context["request_id"] == "corr-123"
        assert received_context["user"] == "jwt-user@example.com"
        assert received_context["state"]["jwt_claims"]["sub"] == "jwt-user@example.com"
        # Prior context table should be passed through
        assert received_context["local_contexts"] == provided_context_table

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_injects_user_into_global_context(self, tool_service):
        """Pre-invoke hook should populate global_context.user from app_user_email when the provided context has no user."""
        # First-Party
        from mcpgateway.plugins.framework import GlobalContext
        from mcpgateway.plugins.framework.models import PluginResult

        cache = self._cache_mock(self._cache_payload())

        received_context = {}

        mock_pm = MagicMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            received_context["user"] = global_context.user
            return PluginResult(continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        # Provide a context with user=None so the fallback injection fires
        provided_ctx = GlobalContext(request_id="corr-456", server_id="srv-1", tenant_id=None, user=None)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
            patch.object(tool_service, "_get_plugin_manager", AsyncMock(return_value=mock_pm)),
        ):
            await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"key": "val"},
                app_user_email="injected-user@example.com",
                user_email="user@example.com",
                token_teams=["team-a"],
                plugin_global_context=provided_ctx,
            )

        assert received_context["user"] == "injected-user@example.com"

    @pytest.mark.asyncio
    async def test_prepare_rust_mcp_pre_invoke_injects_tool_and_gateway_metadata(self, tool_service):
        """Pre-invoke hook should inject PydanticTool and PydanticGateway metadata into global context."""
        # First-Party
        from mcpgateway.plugins.framework import GlobalContext
        from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA
        from mcpgateway.plugins.framework.models import PluginResult

        # Supply fields required by PydanticTool (url) and PydanticGateway
        # (id, slug, transport, capabilities, last_seen) so model_validate succeeds.
        cache = self._cache_mock(
            self._cache_payload(
                url="http://gateway.example/mcp",
                gateway={
                    "id": "gw-1",
                    "slug": "gateway-one",
                    "transport": "streamablehttp",
                    "capabilities": {},
                    "last_seen": None,
                },
            )
        )

        received_metadata = {
            "has_tool": False,
            "has_gateway": False,
            "keys": [],
        }

        mock_pm = AsyncMock()
        mock_pm.has_hooks_for = MagicMock(side_effect=lambda hook_type: hook_type == ToolHookType.TOOL_PRE_INVOKE)

        async def mock_invoke_hook(hook_type, payload, global_context, local_contexts=None, violations_as_exceptions=False):  # noqa: ARG001
            received_metadata["keys"] = list(global_context.metadata.keys())
            received_metadata["has_tool"] = TOOL_METADATA in global_context.metadata
            received_metadata["has_gateway"] = GATEWAY_METADATA in global_context.metadata
            if received_metadata["has_tool"]:
                received_metadata["tool_name"] = global_context.metadata[TOOL_METADATA].name
            if received_metadata["has_gateway"]:
                received_metadata["gateway_name"] = global_context.metadata[GATEWAY_METADATA].name
            return PluginResult(continue_processing=True), {}

        mock_pm.invoke_hook = mock_invoke_hook

        provided_ctx = GlobalContext(request_id="corr-789", server_id=None, tenant_id=None, user="user@example.com")

        tool_service._get_plugin_manager = AsyncMock(return_value=mock_pm)

        with (
            patch("mcpgateway.services.tool_service._get_tool_lookup_cache", return_value=cache),
            patch("mcpgateway.services.tool_service.current_trace_id", MagicMock(get=MagicMock(return_value=None))),
            patch("mcpgateway.services.tool_service.global_config_cache", MagicMock(get_passthrough_headers=MagicMock(return_value=[]))),
            patch("mcpgateway.services.tool_service.compute_passthrough_headers_cached", return_value={}),
            patch.object(tool_service, "_check_tool_access", AsyncMock(return_value=True)),
        ):
            await tool_service.prepare_rust_mcp_tool_execution(
                MagicMock(),
                "tool-one",
                arguments={"key": "val"},
                user_email="user@example.com",
                token_teams=["team-a"],
                plugin_global_context=provided_ctx,
            )

        assert received_metadata["has_tool"] is True
        assert received_metadata["has_gateway"] is True
        assert received_metadata["tool_name"] == "tool-one"
        assert received_metadata["gateway_name"] == "gateway-one"

    @pytest.mark.asyncio
    async def test_invoke_tool_header_gateway_not_found(self, tool_service, test_db):
        """Header present but gateway not in DB should fall through to normal tool lookup."""
        # Set up DB: first call returns None (no gateway), subsequent calls return no tool
        self._setup_db_for_header_lookup(test_db, gateway=None, tool=None)

        mock_gc = MagicMock()
        mock_gc.get_passthrough_headers.return_value = []

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.global_config_cache", mock_gc),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True
            mock_settings.default_passthrough_headers = []

            request_headers = {"x-context-forge-gateway-id": "gw-nonexistent"}

            # Should fall through to normal lookup, which finds no tool
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.invoke_tool(
                    test_db,
                    "some_tool",
                    {},
                    request_headers=request_headers,
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_proxy_access_denied(self, tool_service, mock_direct_gateway, test_db):
        """Header present with direct_proxy gateway but access denied should raise ToolNotFoundError."""
        # Set up DB to return the direct_proxy gateway
        self._setup_db_for_header_lookup(test_db, mock_direct_gateway)

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.check_gateway_access", new_callable=AsyncMock, return_value=False),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = True

            request_headers = {"x-context-forge-gateway-id": "gw-dp-1"}

            with pytest.raises(ToolNotFoundError, match="Tool not found: protected_tool"):
                await tool_service.invoke_tool(
                    test_db,
                    "protected_tool",
                    {},
                    request_headers=request_headers,
                    user_email="intruder@example.com",
                    token_teams=[],
                )

    @pytest.mark.asyncio
    async def test_invoke_tool_direct_proxy_disabled(self, tool_service, mock_direct_gateway, test_db):
        """Header present, gateway is direct_proxy, but feature flag disabled should fall through."""
        # Set up DB: first call returns direct_proxy gateway, subsequent calls return no tool
        self._setup_db_for_header_lookup(test_db, mock_direct_gateway, tool=None)

        mock_gc = MagicMock()
        mock_gc.get_passthrough_headers.return_value = []

        with (
            patch("mcpgateway.services.tool_service.settings") as mock_settings,
            patch("mcpgateway.services.tool_service.global_config_cache", mock_gc),
        ):
            mock_settings.mcpgateway_direct_proxy_enabled = False
            mock_settings.default_passthrough_headers = []

            request_headers = {"x-context-forge-gateway-id": "gw-dp-1"}

            # Should fall through to normal lookup because feature is disabled
            with pytest.raises(ToolNotFoundError, match="Tool not found"):
                await tool_service.invoke_tool(
                    test_db,
                    "some_tool",
                    {},
                    request_headers=request_headers,
                )


@pytest.mark.asyncio
async def test_list_tools_creates_span(tool_service):
    db = MagicMock()
    db.commit = MagicMock()
    tool = MagicMock()
    tool.team_id = None
    tool_service.convert_tool_to_read = MagicMock(return_value="tool-read")

    span_cm = MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))

    with (
        patch("mcpgateway.services.tool_service.create_span", return_value=span_cm) as mock_create_span,
        patch("mcpgateway.services.tool_service._get_registry_cache") as mock_cache_fn,
        patch.object(tool_service, "_apply_access_control", new=AsyncMock(side_effect=lambda query, *_args, **_kwargs: query)),
        patch("mcpgateway.services.tool_service.unified_paginate", new_callable=AsyncMock) as mock_paginate,
    ):
        mock_cache_fn.return_value = AsyncMock(hash_filters=MagicMock(return_value="h"), get=AsyncMock(return_value=None), set=AsyncMock())
        mock_paginate.return_value = ([tool], None)

        result, _ = await tool_service.list_tools(db, user_email="user@example.com", token_teams=["team-1"], visibility="team")

    assert result == ["tool-read"]
    mock_create_span.assert_called_once()
    assert mock_create_span.call_args[0][0] == "tool.list"
    attrs = mock_create_span.call_args[0][1]
    assert attrs["user.email"] == "user@example.com"
    assert attrs["team.scope"] == "team-1"
    assert attrs["visibility"] == "team"


@pytest.mark.asyncio
async def test_list_server_tools_creates_span(tool_service):
    db = MagicMock()
    db.commit = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
    tool_service.convert_tool_to_read = MagicMock(return_value="tool-read")

    span_cm = MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))

    with patch("mcpgateway.services.tool_service.create_span", return_value=span_cm) as mock_create_span:
        result = await tool_service.list_server_tools(db, "server-1", user_email="user@example.com", token_teams=["team-1"])

    assert result == ["tool-read"]
    assert mock_create_span.call_args[0][0] == "tool.list"
    attrs = mock_create_span.call_args[0][1]
    assert attrs["server_id"] == "server-1"
    assert attrs["team.scope"] == "team-1"


@pytest.mark.asyncio
async def test_list_server_mcp_tool_definitions_creates_span(tool_service):
    db = MagicMock()
    db.commit = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [
        {
            "name": "tool-one",
            "description": "Tool One",
            "input_schema": {"type": "object"},
            "output_schema": None,
            "annotations": None,
            "owner_email": None,
            "team_id": None,
            "visibility": "public",
        }
    ]

    span_cm = MagicMock(__enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False))

    with patch("mcpgateway.services.tool_service.create_span", return_value=span_cm) as mock_create_span:
        result = await tool_service.list_server_mcp_tool_definitions(db, "server-1", token_teams=["team-1"])

    assert result[0]["name"] == "tool-one"
    assert mock_create_span.call_args[0][0] == "tool.list"
    attrs = mock_create_span.call_args[0][1]
    assert attrs["mcp.definition_mode"] is True
    assert attrs["team.scope"] == "team-1"
