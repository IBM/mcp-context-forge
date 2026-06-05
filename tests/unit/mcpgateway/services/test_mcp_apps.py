# -*- coding: utf-8 -*-
"""Tests for the minimal MCP Apps extension helpers."""

# Standard
from types import SimpleNamespace

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import ServerCapabilities
from mcpgateway.services.mcp_apps import (
    MCP_UI_EXTENSION,
    MCPAppsValidationError,
    apply_resource_meta,
    build_extension_capabilities,
    filter_model_visible_tools,
    is_app_visible_tool,
    merge_mcp_protocol_meta,
    validate_extension_metadata,
    validate_ui_resource,
)


def test_server_capabilities_accept_extensions() -> None:
    """ServerCapabilities should serialize extension capabilities."""
    caps = ServerCapabilities(extensions={MCP_UI_EXTENSION: {"version": "test"}})

    assert caps.model_dump(exclude_none=True)["extensions"][MCP_UI_EXTENSION]["version"] == "test"


def test_build_extension_capabilities_respects_flag_and_authorization(monkeypatch) -> None:
    """MCP Apps capability is advertised only when enabled and authorized."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

    assert MCP_UI_EXTENSION in build_extension_capabilities(authorized=True)
    assert build_extension_capabilities(authorized=False) == {}

    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
    assert build_extension_capabilities(authorized=True) == {}


def test_validate_extension_metadata_rejects_unsafe_csp() -> None:
    """MCP Apps metadata rejects unsafe script CSP sources."""
    with pytest.raises(MCPAppsValidationError):
        validate_extension_metadata({MCP_UI_EXTENSION: {"csp": {"script-src": ["'unsafe-inline'"]}}})


def test_validate_ui_resource_requires_text_html_when_enabled(monkeypatch) -> None:
    """ui:// resources must be text/html when MCP Apps are enabled."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)

    policy = {MCP_UI_EXTENSION: {"csp": {"default-src": ["'self'"]}, "sandbox": ["allow-scripts"]}}
    validate_ui_resource("ui://example/widget", "text/html", policy)
    with pytest.raises(MCPAppsValidationError):
        validate_ui_resource("ui://example/widget", "application/json", policy)


def test_model_visible_filter_hides_app_only_tools(monkeypatch) -> None:
    """App-only helper tools should not appear in model-facing tool lists."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    model_tool = SimpleNamespace(name="model_tool", extension_metadata={MCP_UI_EXTENSION: {"audience": ["model"]}})
    app_tool = SimpleNamespace(name="app_tool", extension_metadata={MCP_UI_EXTENSION: {"audience": ["app"]}})

    assert filter_model_visible_tools([model_tool, app_tool]) == [model_tool]
    assert is_app_visible_tool(app_tool) is True


def test_apply_resource_meta_projects_ui_policy(monkeypatch) -> None:
    """Known UI resource policy should project into MCP _meta."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    payload: dict = {}

    apply_resource_meta(payload, {MCP_UI_EXTENSION: {"csp": {"default-src": ["'self'"]}, "sandbox": ["allow-scripts"], "permissions": ["clipboard-read"]}})

    assert payload["_meta"]["ui"]["sandbox"] == ["allow-scripts"]
    assert payload["_meta"]["ui"]["permissions"] == ["clipboard-read"]


def test_merge_mcp_protocol_meta_projects_ui_to_extension_metadata() -> None:
    """Upstream MCP _meta.ui should be stored as ContextForge extension metadata."""
    payload = {"_meta": {"ui": {"resourceUri": "ui://widgets/example", "audience": ["model"]}}}

    merge_mcp_protocol_meta(payload)

    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["resourceUri"] == "ui://widgets/example"
    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["audience"] == ["model"]
