"""MCP resources capability compliance tests."""

from __future__ import annotations

import json

import pytest
from fastmcp.client import Client

from .helpers.compliance import xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


async def test_static_resource_listed_and_readable(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_virtual",
        reason="GAP-009: virtual-server composition does not include upstream resources",
    )
    uris = {str(r.uri) for r in await client.list_resources()}
    assert "reference://static/greeting" in uris

    read = await client.read_resource("reference://static/greeting")
    assert any("hello from compliance-reference-server" in str(c) for c in read)


async def test_templated_resource_registered_and_resolves(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_virtual",
        reason="GAP-009: virtual-server composition does not include upstream resources (proxy path closed 2026-04-18)",
    )
    templates = {t.uriTemplate for t in await client.list_resource_templates()}
    assert "reference://users/{user_id}" in templates

    read = await client.read_resource("reference://users/7")
    decoded = [json.loads(c.text) for c in read if getattr(c, "text", None)]
    assert decoded and decoded[0] == {"user_id": "7", "name": "User 7"}
