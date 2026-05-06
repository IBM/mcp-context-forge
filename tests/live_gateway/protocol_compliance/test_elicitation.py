# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_elicitation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP elicitation compliance tests — server can request user-input from the client.
"""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_elicit_trigger_invokes_client_handler(connect, request) -> None:
    """elicit_trigger routes through ctx.elicit → client elicitation_handler → back."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-005: server→client `elicitation/create` request must travel on "
            "the POST-correlated stream (spec forbids it on the standalone "
            "stream); gateway does not broker server→client requests there."
        ),
    )
    prompts: list[str] = []

    async def elicitation_handler(message, response_type, params, ctx):
        prompts.append(str(message))
        return {"value": "canned-elicit-response"}

    async with connect(elicitation_handler=elicitation_handler) as client:
        name = await resolve_tool(client, "elicit_trigger")
        if name is None:
            pytest.skip("elicit_trigger tool not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"message": "q"})
    assert result.isError is False
    assert "canned-elicit-response" in str(result.content)
    assert prompts, "elicitation_handler was never invoked"
