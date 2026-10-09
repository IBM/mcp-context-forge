#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for tool custom-name conflict handling.
Location: ./tests/unit/mcpgateway/services/test_tool_name_conflict_regression.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.db import Tool as DbTool
from mcpgateway.schemas import ToolUpdate
from mcpgateway.services.tool_service import ToolNameConflictError, ToolService


def _make_tool(tool_id: str, internal_name: str, visibility: str, owner_email: str | None = None) -> DbTool:
    """Build a persisted tool with an intentionally shared custom name."""
    return DbTool(
        id=tool_id,
        original_name=internal_name,
        custom_name="execute_sql",
        custom_name_slug=internal_name,
        name=internal_name,
        input_schema={},
        owner_email=owner_email,
        visibility=visibility,
    )


@pytest.mark.asyncio
async def test_update_tool_visibility_conflict_handles_duplicate_public_custom_names(test_db):
    """Changing a private tool to public raises the domain conflict error, not a query cardinality error."""
    test_db.add_all(
        [
            _make_tool("tool-a", "gateway-a-execute-sql", "public"),
            _make_tool("tool-b", "gateway-b-execute-sql", "public"),
            _make_tool("tool-c", "gateway-c-execute-sql", "private", owner_email="owner@example.com"),
        ]
    )
    test_db.commit()

    with pytest.raises(ToolNameConflictError):
        await ToolService().update_tool(test_db, "tool-c", ToolUpdate(visibility="public"))
