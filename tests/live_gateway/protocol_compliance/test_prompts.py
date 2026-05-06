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

from .helpers.compliance import xfail_on

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_server_features]


async def test_prompt_listed(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-006: gateway federation does not surface upstream prompts",
    )
    names = {p.name for p in await client.list_prompts()}
    assert "greet" in names


async def test_prompt_renders_argument(client: Client, request) -> None:
    xfail_on(
        request,
        "gateway_proxy",
        "gateway_virtual",
        reason="GAP-006: gateway federation does not surface upstream prompts",
    )
    rendered = await client.get_prompt("greet", arguments={"name": "Grace"})
    texts = [getattr(m.content, "text", "") for m in rendered.messages]
    assert any("Grace" in t for t in texts)
