"""Elicitation depth tests beyond the happy-path string response.

Covers non-string schemas (numeric multi-field) so the harness proves the
wire envelope carries structured response data correctly — not just a
single string field.
"""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_elicit_numeric_schema_roundtrip(connect, request) -> None:
    """elicit_trigger_numeric requests a two-field numeric schema.

    Proves the response payload carries non-string types (int + float)
    through elicitation and back to the server tool unchanged.
    """
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

    async def elicitation_handler(message, response_type, params, ctx):
        return {"count": 42, "ratio": 0.25}

    async with connect(elicitation_handler=elicitation_handler) as client:
        name = await resolve_tool(client, "elicit_trigger_numeric")
        if name is None:
            pytest.skip("elicit_trigger_numeric not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"message": "q"})
    assert result.isError is False, f"unexpected error: {result.content}"
    text = result.content[0].text if result.content else ""
    assert "count=42" in text, f"int field didn't round-trip: {text!r}"
    assert "ratio=0.25" in text, f"float field didn't round-trip: {text!r}"
