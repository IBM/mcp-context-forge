# -*- coding: utf-8 -*-
"""Tests for the minimal MCP Apps extension helpers."""

# Standard
from types import SimpleNamespace
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import ServerCapabilities
from mcpgateway.services.mcp_apps import (
    apply_resource_meta,
    build_extension_capabilities,
    filter_model_visible_tools,
    is_app_visible_tool,
    mcp_app_session_service,
    MCP_UI_EXTENSION,
    MCPAppsValidationError,
    merge_mcp_protocol_meta,
    serialize_resource_content_for_mcp,
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
    model_tool = SimpleNamespace(name="model_tool", extension_metadata={MCP_UI_EXTENSION: {"visibility": ["model"]}})
    app_tool = SimpleNamespace(name="app_tool", extension_metadata={MCP_UI_EXTENSION: {"visibility": ["app"]}})

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
    payload = {"_meta": {"ui": {"resourceUri": "ui://widgets/example", "visibility": ["model"]}}}

    merge_mcp_protocol_meta(payload)

    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["resourceUri"] == "ui://widgets/example"
    assert payload["extensionMetadata"][MCP_UI_EXTENSION]["visibility"] == ["model"]


def test_merge_mcp_protocol_meta_ignores_missing_ui_and_merges_existing_metadata() -> None:
    """Protocol metadata merge should ignore non-UI metadata and preserve extension data."""
    payload = {"_meta": {"ui": {}}}
    merge_mcp_protocol_meta(payload)
    assert "extensionMetadata" not in payload

    payload = {
        "_meta": {"ui": {"resourceUri": "ui://widgets/example"}},
        "extensionMetadata": {MCP_UI_EXTENSION: {"visibility": ["model"]}},
    }
    merge_mcp_protocol_meta(payload)

    assert payload["extensionMetadata"][MCP_UI_EXTENSION] == {
        "visibility": ["model"],
        "resourceUri": "ui://widgets/example",
    }


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ("bad", "extensionMetadata must be an object"),
        ({MCP_UI_EXTENSION: {"resourceUri": "http://example.com"}}, "resourceUri must use the ui:// scheme"),
        ({MCP_UI_EXTENSION: {"visibility": ["operator"]}}, "visibility entries"),
        ({MCP_UI_EXTENSION: {"csp": "default-src 'self'"}}, "csp must be an object"),
        ({MCP_UI_EXTENSION: {"csp": {"object-src": ["'none'"]}}}, "Unsupported MCP Apps CSP directive"),
        ({MCP_UI_EXTENSION: {"sandbox": 123}}, "sandbox must be a string or list of strings"),
        ({MCP_UI_EXTENSION: {"permissions": ["clipboard_read"]}}, "Unsupported MCP Apps permission"),
    ],
)
def test_validate_extension_metadata_rejects_malformed_mcp_apps_values(metadata, message) -> None:
    """MCP Apps metadata should fail closed for malformed policy fields."""
    with pytest.raises(MCPAppsValidationError, match=message):
        validate_extension_metadata(metadata)


def test_validate_extension_metadata_accepts_absent_ui_block() -> None:
    """Unknown extension metadata can be stored when known MCP Apps policy is absent."""
    validate_extension_metadata({"io.example/custom": {"ok": True}})


def test_validate_extension_metadata_accepts_string_visibility_and_csp_source() -> None:
    """String-or-list metadata fields should normalize as valid string lists."""
    validate_extension_metadata(
        {
            MCP_UI_EXTENSION: {
                "resourceUri": "ui://widgets/example",
                "visibility": "app",
                "csp": {"default-src": "'self'"},
                "sandbox": "allow-scripts",
                "permissions": "clipboard-read",
            }
        }
    )


def test_validate_extension_metadata_accepts_current_app_csp_and_permissions() -> None:
    """Current MCP Apps CSP and permissions metadata should be accepted."""
    validate_extension_metadata(
        {
            MCP_UI_EXTENSION: {
                "csp": {"connectDomains": ["https://api.example.com"], "resourceDomains": ["https://cdn.example.com"]},
                "permissions": {"clipboardWrite": {}},
            }
        }
    )


def test_apply_resource_meta_noops_without_enabled_extension_or_ui(monkeypatch) -> None:
    """Resource metadata projection should no-op when disabled or UI metadata is absent."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", False)
    payload: dict = {}
    apply_resource_meta(payload, {MCP_UI_EXTENSION: {"sandbox": ["allow-scripts"]}})
    assert payload == {}

    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    apply_resource_meta(payload, {"io.example/custom": {"sandbox": ["allow-scripts"]}})
    assert payload == {}


def test_serialize_resource_content_for_mcp_preserves_mime_and_meta() -> None:
    """Legacy resource content should serialize to MCP resources/read content."""
    # First-Party
    from mcpgateway.common.models import ResourceContent

    content = ResourceContent(type="resource", id="r1", uri="ui://widgets/example", mimeType="text/html;profile=mcp-app", text="<html></html>", _meta={"ui": {"prefersBorder": True}})

    assert serialize_resource_content_for_mcp(content) == {
        "uri": "ui://widgets/example",
        "mimeType": "text/html;profile=mcp-app",
        "text": "<html></html>",
        "_meta": {"ui": {"prefersBorder": True}},
    }


def test_create_app_session_persists_ttl_bound_record(monkeypatch) -> None:
    """AppBridge session creation should persist and return the database record."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_session_ttl", 60)
    db = MagicMock()
    db.refresh.side_effect = lambda session: setattr(session, "refreshed", True)

    session = mcp_app_session_service.create_session(
        db,
        mcp_session_id="mcp-session-1",
        user_email="user@example.com",
        server_id="server-1",
        resource_uri="ui://widgets/example",
        token_teams=["team-1"],
    )

    db.add.assert_called_once_with(session)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(session)
    assert session.refreshed is True
    assert session.mcp_session_id == "mcp-session-1"
    assert session.token_teams == ["team-1"]
