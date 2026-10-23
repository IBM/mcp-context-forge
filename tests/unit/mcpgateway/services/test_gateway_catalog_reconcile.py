# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_catalog_reconcile.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression tests for catalog reconciliation: pending in-place updates to existing
tools must survive a refresh pass that also prunes stale rows.

See https://github.com/IBM/mcp-context-forge/issues/7273 (and #7152, same root cause).
"""

# Future
from __future__ import annotations

# Standard
from types import SimpleNamespace
from typing import Any

# Third-Party
from sqlalchemy import select

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import Tool as DbTool
from mcpgateway.services.gateway_service import GatewayService


def _add_gateway(db, name: str = "gw-7273") -> DbGateway:
    """Insert a gateway row and return it."""
    gateway = DbGateway(name=name, slug=name, url="http://gw.example.com/mcp", capabilities={})
    db.add(gateway)
    db.flush()
    return gateway


def _add_tool(db, gateway: DbGateway, name: str, schema: Any) -> DbTool:
    """Insert a tool row attached to the gateway and return it."""
    tool = DbTool(
        original_name=name,
        custom_name=name,
        custom_name_slug=name,
        name=name,
        input_schema=schema,
        description=f"{name} description",
        original_description=f"{name} description",
        url=gateway.url,
        integration_type="MCP",
        request_type="POST",
        headers={},
        gateway_id=gateway.id,
        enabled=True,
        reachable=True,
    )
    db.add(tool)
    return tool


def _fetched_tool(name: str, schema: Any) -> SimpleNamespace:
    """Build a fetched (upstream) tool object shaped like the ones the service consumes."""
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        input_schema=schema,
        output_schema=None,
        request_type="POST",
        headers={},
        annotations=None,
        jsonpath_filter="",
        extension_metadata=None,
        visibility=None,
    )


def test_pending_tool_updates_survive_refresh_that_prunes_stale_tools(test_db):
    """A refresh that updates A/B, adds D and removes C must persist A's new schema.

    Regression test for #7273: ``_reconcile_gateway_catalog`` expired the gateway
    before pending updates had been flushed, so with ``autoflush=False`` the
    in-place updates were discarded while the reported counts stayed non-zero.
    """
    db = test_db
    gateway = _add_gateway(db)
    for name in ("A", "B", "C"):
        _add_tool(db, gateway, name, {"schema": "old", "tool": name})
    db.commit()

    service = GatewayService()

    # A and B changed upstream, C is gone, D is new: update + removal in one pass.
    catalog_sync = service._sync_gateway_catalog(
        db,
        gateway=gateway,
        tools=[
            _fetched_tool("A", {"schema": "new", "tool": "A"}),
            _fetched_tool("B", {"schema": "old", "tool": "B"}),
            _fetched_tool("D", {"schema": "new", "tool": "D"}),
        ],
        resources=[],
        prompts=[],
        created_via="refresh",
    )
    reconcile_result = service._reconcile_gateway_catalog(
        db,
        gateway=gateway,
        catalog_sync=catalog_sync,
        log_context="manual refresh",
    )
    db.commit()

    assert reconcile_result.tools_removed == 1
    assert reconcile_result.tools_added == 1

    rows = {tool.original_name: tool for tool in db.execute(select(DbTool)).scalars().all()}
    assert set(rows) == {"A", "B", "D"}, "stale tool C should be pruned and D added"
    assert rows["A"].input_schema == {"schema": "new", "tool": "A"}, "pending update to A was discarded"
    assert rows["D"].input_schema == {"schema": "new", "tool": "D"}
