# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_mcp_apps_protocol.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Protocol-facing MCP Apps behavior tests.
"""

# Standard
from types import SimpleNamespace

# First-Party
from mcpgateway.main import _serialize_mcp_tool_definition, _serialize_mcp_tool_definitions
from mcpgateway.services.mcp_apps import MCP_UI_EXTENSION


def test_tool_serializer_projects_ui_resource_uri(monkeypatch) -> None:
    """MCP tools/list should project app resource metadata into _meta."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    tool = SimpleNamespace(
        name="open_widget",
        description="Open widget",
        input_schema={"type": "object"},
        output_schema=None,
        annotations={},
        extension_metadata={MCP_UI_EXTENSION: {"resourceUri": "ui://widgets/example", "visibility": ["model"]}},
    )

    payload = _serialize_mcp_tool_definition(tool)

    assert payload["_meta"]["ui"]["resourceUri"] == "ui://widgets/example"
    assert payload["_meta"]["ui"]["visibility"] == ["model"]


def test_tool_serializer_filters_app_only_tools(monkeypatch) -> None:
    """MCP tools/list should hide helper tools that are app-only."""
    monkeypatch.setattr("mcpgateway.services.mcp_apps.settings.mcpgateway_mcp_apps_enabled", True)
    model_tool = {
        "name": "open_widget",
        "description": "Open widget",
        "inputSchema": {"type": "object"},
        "extensionMetadata": {MCP_UI_EXTENSION: {"visibility": ["model"]}},
    }
    app_only_tool = {
        "name": "widget_helper",
        "description": "Helper",
        "inputSchema": {"type": "object"},
        "extensionMetadata": {MCP_UI_EXTENSION: {"visibility": ["app"]}},
    }

    payload = _serialize_mcp_tool_definitions([model_tool, app_only_tool])

    assert [tool["name"] for tool in payload] == ["open_widget"]
