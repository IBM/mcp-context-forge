"""MCP sampling compliance tests — server can request sampling from the client."""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_sample_trigger_invokes_client_handler(connect, request) -> None:
    """sample_trigger routes through ctx.sample → client sampling_handler → back."""
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason=(
            "GAP-004: server→client `sampling/createMessage` request must travel "
            "on the POST-correlated stream (spec forbids it on the standalone "
            "stream); gateway does not broker server→client requests there."
        ),
    )
    invocations: list[str] = []

    async def sampling_handler(messages, params, ctx):
        invocations.append(str(messages))
        return "canned-sample-response"

    async with connect(sampling_handler=sampling_handler) as client:
        name = await resolve_tool(client, "sample_trigger")
        if name is None:
            pytest.skip("sample_trigger tool not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"prompt": "ping"})
    assert result.isError is False
    assert "canned-sample-response" in str(result.content)
    assert invocations, "sampling_handler was never invoked"
