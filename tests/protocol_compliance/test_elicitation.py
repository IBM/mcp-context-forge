"""MCP elicitation compliance tests — server can request user-input from the client."""

from __future__ import annotations

import pytest

from ._helpers import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_elicit_trigger_invokes_client_handler(connect, request) -> None:
    """elicit_trigger routes through ctx.elicit → client elicitation_handler → back."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-005: gateway does not relay server-initiated elicitation/create (see #4205)",
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
