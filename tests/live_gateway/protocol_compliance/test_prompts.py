# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_prompts.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP prompts capability compliance tests.
"""

from __future__ import annotations

import pytest
from fastmcp.client import Client

from .helpers.compliance import resolve_prompt, xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


async def test_prompt_listed(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_virtual",
        reason="GAP-006: gateway federation does not surface upstream prompts",
    )
    # Use resolve_prompt to handle both bare (reference) and slug-prefixed (gateway) names
    name = await resolve_prompt(client, "greet")
    assert name is not None, "greet prompt not found (expected bare 'greet' or slug-prefixed variant)"


async def test_prompt_renders_argument(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_virtual",
        reason="GAP-006: gateway federation does not surface upstream prompts",
    )
    # Resolve the prompt name (bare or slug-prefixed)
    name = await resolve_prompt(client, "greet")
    if name is None:
        pytest.skip("greet prompt not advertised by this target")

    rendered = await client.get_prompt(name, arguments={"name": "Grace"})
    texts = [getattr(m.content, "text", "") for m in rendered.messages]
    assert any("Grace" in t for t in texts)
