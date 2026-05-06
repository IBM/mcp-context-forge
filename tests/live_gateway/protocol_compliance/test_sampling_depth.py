# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_sampling_depth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Sampling depth tests — parameters beyond prompt-only happy path.
"""

from __future__ import annotations

import pytest

from .helpers.compliance import resolve_tool, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_client_features]


async def test_sample_with_max_tokens_parameter(connect, request) -> None:
    """sample_trigger_with_params supplies max_tokens; handler sees it.

    The server-side tool invokes ``ctx.sample(..., max_tokens=N)`` and the
    client's sampling_handler receives a params object carrying that
    max_tokens. This test asserts the parameter survived the roundtrip.
    """
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

    captured_max_tokens: list[int | None] = []

    async def sampling_handler(messages, params, ctx):
        # FastMCP normalizes the handler signature; the second positional is the
        # params object (or dict) carrying the sampling request's fields.
        max_tokens = getattr(params, "maxTokens", None)
        if max_tokens is None and isinstance(params, dict):
            max_tokens = params.get("maxTokens")
        captured_max_tokens.append(max_tokens)
        return "canned"

    async with connect(sampling_handler=sampling_handler) as client:
        name = await resolve_tool(client, "sample_trigger_with_params")
        if name is None:
            pytest.skip("sample_trigger_with_params not advertised on this target")
        result = await client.call_tool_mcp(name=name, arguments={"prompt": "hi", "max_tokens": 77})
    assert result.isError is False, f"unexpected error: {result.content}"
    assert captured_max_tokens, "sampling_handler was never invoked"
    assert captured_max_tokens[0] == 77, f"max_tokens didn't round-trip to client sampling_handler: got {captured_max_tokens[0]!r}"
