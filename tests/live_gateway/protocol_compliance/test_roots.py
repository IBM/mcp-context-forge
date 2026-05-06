# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_roots.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP roots compliance tests — client-announced roots are visible to the server.
"""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_roots_echo_receives_client_roots(connect, request) -> None:
    """roots_echo returns the URIs advertised by the client."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-003: gateway does not forward client roots to upstream",
    )
    roots = ["file:///tmp/alpha", "file:///tmp/beta"]
    async with connect(roots=roots) as client:
        name = await resolve_tool(client, "roots_echo")
        if name is None:
            pytest.skip("roots_echo tool not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={})
    assert result.isError is False
    text = result.content[0].text if result.content else ""
    assert "alpha" in text
    assert "beta" in text
