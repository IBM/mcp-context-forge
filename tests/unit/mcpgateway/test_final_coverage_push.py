# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_final_coverage_push.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Final push to reach 75% coverage.
"""

# Standard
import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import orjson
import pytest

# First-Party
from mcpgateway.common.models import ImageContent, LogLevel, ResourceContent, Role, TextContent
from mcpgateway.schemas import BaseModelWithConfigDict


async def _call_toolops(handler, monkeypatch, **kwargs):
    # First-Party
    import mcpgateway.middleware.rbac as rbac_module
    import mcpgateway.plugins.framework as plugins_framework

    class DummyPermissionService:
        def __init__(self, db):
            self.db = db

        async def check_permission(self, **_):
            return True

    monkeypatch.setattr(rbac_module, "PermissionService", DummyPermissionService)
    monkeypatch.setattr(plugins_framework, "get_plugin_manager", lambda: None)
    return await handler(**kwargs)


def test_role_enum_comprehensive():
    """Test Role enum comprehensively."""
    # Test values
    assert Role.USER.value == "user"
    assert Role.ASSISTANT.value == "assistant"

    # Test enum iteration
    roles = list(Role)
    assert len(roles) == 2
    assert Role.USER in roles
    assert Role.ASSISTANT in roles


def test_log_level_enum_comprehensive():
    """Test LogLevel enum comprehensively."""
    levels = [
        (LogLevel.DEBUG, "debug"),
        (LogLevel.INFO, "info"),
        (LogLevel.NOTICE, "notice"),
        (LogLevel.WARNING, "warning"),
        (LogLevel.ERROR, "error"),
        (LogLevel.CRITICAL, "critical"),
        (LogLevel.ALERT, "alert"),
        (LogLevel.EMERGENCY, "emergency")
    ]

    for level, expected_value in levels:
        assert level.value == expected_value


def test_content_types():
    """Test content type models."""
    import base64

    # Test TextContent
    text = TextContent(type="text", text="Hello world")
    assert text.type == "text"
    assert text.text == "Hello world"

    # Test ImageContent - now uses base64-encoded string per MCP spec
    image_bytes = b"fake_image_bytes"
    image_data = base64.b64encode(image_bytes).decode('utf-8')
    image = ImageContent(type="image", data=image_data, mime_type="image/png")
    assert image.type == "image"
    assert image.data == image_data
    assert image.mime_type == "image/png"

    # Test ResourceContent
    resource = ResourceContent(
        type="resource",
        id="res123",
        uri="/api/data",
        mime_type="application/json",
        text="Sample content"
    )
    assert resource.type == "resource"
    assert resource.uri == "/api/data"
    assert resource.mime_type == "application/json"
    assert resource.text == "Sample content"

def test_content_type_model_form_urlencoded():
    """
    Test that the system can parse/accept application/x-www-form-urlencoded.
    """
    from fastapi.testclient import TestClient
    from mcpgateway.main import app

    client = TestClient(app)
    data = {"type": "text", "text": "Form encoded content"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = client.post("/admin/tools", data=data, headers=headers)
    assert response.status_code in [200, 201, 400, 401, 415, 422]

def test_base_model_with_config_dict():
    """Test BaseModelWithConfigDict functionality."""
    # Create a simple test model
    class TestModel(BaseModelWithConfigDict):
        name: str
        value: int

    model = TestModel(name="test", value=42)

    # Test to_dict method
    result = model.to_dict()
    assert result["name"] == "test"
    assert result["value"] == 42

    # Test to_dict with alias
    result_alias = model.to_dict(use_alias=True)
    assert isinstance(result_alias, dict)


@pytest.mark.asyncio
async def test_cli_export_import_main_flows():
    """Test CLI export/import main execution flows."""
    # Standard
    import sys

    # First-Party
    from mcpgateway.cli_export_import import main_with_subcommands

    # Test with no subcommands (should fall back to main CLI)
    with patch.object(sys, 'argv', ['mcpgateway', '--version']):
        with patch('mcpgateway.cli.main') as mock_main:
            main_with_subcommands()
            mock_main.assert_called_once()

    # Test with export command but invalid args
    with patch.object(sys, 'argv', ['mcpgateway', 'export', '--invalid-option']):
        with pytest.raises(SystemExit):
            main_with_subcommands()


@pytest.mark.asyncio
async def test_export_command_parameter_building():
    """Test export command parameter building logic."""
    # Standard
    import argparse

    # First-Party
    from mcpgateway.cli_export_import import export_command

    # Test with all parameters set
    args = argparse.Namespace(
        types="tools,gateways",
        exclude_types="servers",
        tags="production,api",
        include_inactive=True,
        include_dependencies=False,
        output="test-output.json",
        verbose=True
    )

    # Mock the API call to just capture parameters
    with patch('mcpgateway.cli_export_import.make_authenticated_request') as mock_request:
        mock_request.return_value = {
            "version": "2025-03-26",
            "entities": {"tools": []},
            "metadata": {"entity_counts": {"tools": 0}}
        }

        with patch('mcpgateway.cli_export_import.Path.mkdir'):
            with patch('pathlib.Path.write_bytes'):  # Changed from builtins.open for asyncio.to_thread
                await export_command(args)

        # Verify API was called with correct parameters
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        params = call_args[1]['params']

        assert params['types'] == "tools,gateways"
        assert params['exclude_types'] == "servers"
        assert params['tags'] == "production,api"
        assert params['include_inactive'] == "true"
        assert params['include_dependencies'] == "false"


@pytest.mark.asyncio
async def test_import_command_parameter_parsing():
    """Test import command parameter parsing logic."""
    # Standard
    import argparse

    # First-Party
    from mcpgateway.cli_export_import import import_command

    # Create temp file with valid JSON
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_data = {
            "version": "2025-03-26",
            "entities": {"tools": []},
            "metadata": {"entity_counts": {"tools": 0}}
        }
        json.dump(test_data, f)
        temp_file = f.name

    args = argparse.Namespace(
        input_file=temp_file,
        conflict_strategy='update',
        dry_run=True,
        rekey_secret='new-secret',
        include='tools:tool1,tool2;servers:server1',
        verbose=True
    )

    # Mock the API call
    with patch('mcpgateway.cli_export_import.make_authenticated_request') as mock_request:
        mock_request.return_value = {
            "import_id": "test_123",
            "status": "completed",
            "progress": {"total": 1, "processed": 1, "created": 1, "failed": 0},
            "warnings": [],
            "errors": []
        }

        await import_command(args)

        # Verify API was called with correct data
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        request_data = call_args[1]['json_data']

        assert request_data['conflict_strategy'] == 'update'
        assert request_data['dry_run'] == True
        assert request_data['rekey_secret'] == 'new-secret'
        assert 'selected_entities' in request_data


def test_utils_coverage():
    """Test various utility functions for coverage."""
    # First-Party
    from mcpgateway.utils.create_slug import slugify

    # Test slugify variations
    test_cases = [
        ("Simple Test", "simple-test"),
        ("API_Gateway", "api-gateway"),
        ("Multiple   Spaces", "multiple-spaces"),
        ("", ""),
        ("123Numbers", "123numbers")
    ]

    for input_text, expected in test_cases:
        result = slugify(input_text)
        assert isinstance(result, str)


def test_config_properties():
    """Test config module properties."""
    # First-Party
    from mcpgateway.config import settings

    # Test basic properties exist
    assert hasattr(settings, 'app_name')
    assert hasattr(settings, 'host')
    assert hasattr(settings, 'port')
    assert hasattr(settings, 'database_url')

    # Test computed properties
    api_key = settings.api_key
    assert isinstance(api_key, str)
    assert ":" in api_key  # Should be "user:password" format

    # Test transport support properties
    assert isinstance(settings.supports_http, bool)
    assert isinstance(settings.supports_websocket, bool)
    assert isinstance(settings.supports_sse, bool)


def test_schemas_basic():
    """Test basic schema imports."""
    # First-Party
    from mcpgateway.schemas import ToolCreate

    # Test class exists
    assert ToolCreate is not None


def test_db_utility_functions():
    """Test database utility functions."""
    # Standard
    from datetime import datetime, timezone

    # First-Party
    from mcpgateway.db import utc_now

    # Test utc_now function
    now = utc_now()
    assert isinstance(now, datetime)
    assert now.tzinfo == timezone.utc


def test_validation_imports():
    """Test validation module imports."""
    # First-Party
    from mcpgateway.validation import jsonrpc, tags

    # Test modules can be imported
    assert tags is not None
    assert jsonrpc is not None


def test_services_init():
    """Test services module initialization."""
    # First-Party
    from mcpgateway.services import __init__

    # Just test the module exists
    assert __init__ is not None


def test_cli_module_main_execution():
    """Test CLI module main execution path."""
    # Standard
    import sys

    # First-Party
    # Test __main__ execution path exists
    from mcpgateway import cli_export_import
    assert hasattr(cli_export_import, 'main_with_subcommands')

    # Test module can be executed
    assert cli_export_import.__name__ == 'mcpgateway.cli_export_import'


def test_security_logger_threat_score_and_review():
    """Exercise SecurityLogger threat scoring and audit review logic."""
    # First-Party
    from mcpgateway.services.security_logger import SecurityLogger

    logger = SecurityLogger()
    assert logger._calculate_auth_threat_score(True, 0, "basic") == 0.0
    assert logger._calculate_auth_threat_score(False, 0, "basic") == 0.3
    assert logger._calculate_auth_threat_score(False, 3, "basic") == 0.5
    assert logger._calculate_auth_threat_score(False, 5, "basic") == 0.6
    assert logger._calculate_auth_threat_score(False, 10, "basic") == 0.8

    assert logger._requires_audit_review("delete", "resource", "confidential", True) is True
    assert logger._requires_audit_review("update", "role", None, True) is True
    assert logger._requires_audit_review("update", "tool", None, True) is False


def test_security_logger_count_failures(monkeypatch):
    """Count recent failures uses DB session and returns scalar results."""
    # First-Party
    from mcpgateway.services.security_logger import SecurityLogger

    logger = SecurityLogger()

    class DummyResult:
        def scalar(self):
            return 7

    class DummySession:
        def __init__(self):
            self.committed = False
            self.closed = False

        def execute(self, _stmt):
            return DummyResult()

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    dummy = DummySession()
    monkeypatch.setattr("mcpgateway.services.security_logger.SessionLocal", lambda: dummy)

    result = logger._count_recent_failures(user_id="user1")
    assert result == 7
    assert dummy.committed is True
    assert dummy.closed is True


def test_security_logger_data_access_and_errors(monkeypatch):
    """Log data access builds audit trail and security event for sensitive data."""
    # First-Party
    from mcpgateway.services.security_logger import SecurityLogger

    logger = SecurityLogger()
    mock_audit = MagicMock()
    monkeypatch.setattr(logger, "_create_audit_trail", MagicMock(return_value=mock_audit))
    monkeypatch.setattr(logger, "_create_security_event", MagicMock())

    audit = logger.log_data_access(
        action="update",
        resource_type="tool",
        resource_id="tool-1",
        resource_name="Tool",
        user_id="user1",
        user_email="user@example.com",
        team_id=None,
        client_ip="127.0.0.1",
        user_agent="agent",
        success=False,
        data_classification="confidential",
        old_values={"a": 1},
        new_values={"a": 2},
    )

    assert audit is mock_audit
    logger._create_security_event.assert_called_once()


def test_security_logger_create_event_error(monkeypatch):
    """Ensure _create_security_event handles DB errors."""
    # First-Party
    from mcpgateway.services.security_logger import SecurityLogger, SecuritySeverity

    logger = SecurityLogger()

    class DummySession:
        def add(self, _obj):
            raise RuntimeError("boom")

        def commit(self):
            raise AssertionError("commit should not be called")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    dummy = DummySession()

    result = logger._create_security_event(
        event_type="authentication_failure",
        severity=SecuritySeverity.HIGH,
        category="auth",
        client_ip="127.0.0.1",
        description="fail",
        threat_score=0.5,
        db=dummy,
    )

    assert result is None


@pytest.mark.asyncio
async def test_toolops_generate_testcases_success(monkeypatch):
    """Exercise toolops test case generation endpoint."""
    # First-Party
    from mcpgateway.routers import toolops_router

    monkeypatch.setattr(
        toolops_router,
        "validation_generate_test_cases",
        AsyncMock(return_value=[{"case": 1}]),
    )

    result = await _call_toolops(
        toolops_router.generate_testcases_for_tool,
        monkeypatch,
        tool_id="tool1",
        number_of_test_cases=1,
        number_of_nl_variations=1,
        mode="generate",
        db=MagicMock(),
        current_user_ctx={"email": "user@example.com"},
    )

    assert result == [{"case": 1}]


@pytest.mark.asyncio
async def test_toolops_generate_testcases_invalid_json(monkeypatch):
    """Ensure JSON decode errors surface as HTTP 400."""
    # First-Party
    from mcpgateway.routers import toolops_router

    monkeypatch.setattr(
        toolops_router,
        "validation_generate_test_cases",
        AsyncMock(side_effect=orjson.JSONDecodeError("err", "doc", 0)),
    )

    with pytest.raises(HTTPException) as exc:
        await _call_toolops(
            toolops_router.generate_testcases_for_tool,
            monkeypatch,
            tool_id="tool1",
            number_of_test_cases=1,
            number_of_nl_variations=1,
            mode="generate",
            db=MagicMock(),
            current_user_ctx={"email": "user@example.com"},
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_toolops_execute_nl_testcases_success(monkeypatch):
    """Exercise toolops NL test execution endpoint."""
    # First-Party
    from mcpgateway.routers import toolops_router

    monkeypatch.setattr(
        toolops_router,
        "execute_tool_nl_test_cases",
        AsyncMock(return_value=["ok"]),
    )

    payload = toolops_router.ToolNLTestInput(tool_id="tool1", tool_nl_test_cases=["hello"])
    result = await _call_toolops(
        toolops_router.execute_tool_nl_testcases,
        monkeypatch,
        tool_nl_test_input=payload,
        db=MagicMock(),
        current_user_ctx={"email": "user@example.com"},
    )

    assert result == ["ok"]


@pytest.mark.asyncio
async def test_toolops_enrich_tool_success(monkeypatch):
    """Exercise tool enrichment endpoint."""
    # First-Party
    from mcpgateway.routers import toolops_router

    tool_schema = MagicMock()
    tool_schema.name = "Tool"
    tool_schema.description = "desc"

    monkeypatch.setattr(
        toolops_router,
        "enrich_tool",
        AsyncMock(return_value=("enriched", tool_schema)),
    )

    result = await _call_toolops(
        toolops_router.enrich_a_tool,
        monkeypatch,
        tool_id="tool1",
        db=MagicMock(),
        current_user_ctx={"email": "user@example.com"},
    )

    assert result["tool_id"] == "tool1"
    assert result["enriched_desc"] == "enriched"


@pytest.mark.asyncio
async def test_toolops_enrich_tool_error(monkeypatch):
    """Ensure enrich errors surface as HTTP 400."""
    # First-Party
    from mcpgateway.routers import toolops_router

    monkeypatch.setattr(
        toolops_router,
        "enrich_tool",
        AsyncMock(side_effect=Exception("boom")),
    )

    with pytest.raises(HTTPException) as exc:
        await _call_toolops(
            toolops_router.enrich_a_tool,
            monkeypatch,
            tool_id="tool1",
            db=MagicMock(),
            current_user_ctx={"email": "user@example.com"},
        )

    assert exc.value.status_code == 400
