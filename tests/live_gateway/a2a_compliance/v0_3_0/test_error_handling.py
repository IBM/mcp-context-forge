# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v0_3_0/test_error_handling.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

JSON-RPC envelope error-code compliance for A2A 0.3.0.
Wire-level tests: the SDK Client smooths over JSON-RPC envelope
details (raising typed Python exceptions instead of surfacing the
``code``/``message`` pair), so we drive these checks with raw
``httpx`` to assert on the exact JSON-RPC 2.0 error codes the spec
defines:

  * ``-32700`` Parse error      — malformed JSON
  * ``-32600`` Invalid Request  — well-formed JSON, bad RPC envelope
  * ``-32601`` Method not found — unknown method name
  * ``-32602`` Invalid params   — method exists, params malformed
  * ``-32603`` Internal error   — server-side fault

A2A leaves implementation latitude on which of these to use for which
failure modes, but the JSON-RPC 2.0 reservations apply unconditionally.
Phase 1 covers the cases the echo agent can be made to surface today.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v0_3_0, pytest.mark.a2a_error_handling]


_JSON_RPC_PATH = "/"


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found(echo_agent_base_url: str) -> None:
    """An unknown JSON-RPC ``method`` MUST yield ``code: -32601 Method not found``.

    JSON-RPC 2.0 § 5.1 reserves this code specifically for the
    "method does not exist or is not available" condition. Using a
    generic ``-32000`` server-defined code instead loses the
    interoperable distinction routing-aware clients depend on.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "BogusMethodThatDoesNotExist",
        "params": {},
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(f"{echo_agent_base_url}{_JSON_RPC_PATH}", json=payload)
    assert response.status_code in (200, 400), response.text[:200]
    body = response.json()
    assert "error" in body, f"expected error envelope, got: {body}"
    assert body["error"].get("code") == -32601, f"expected code -32601 (Method not found), got {body['error']}"


@pytest.mark.asyncio
async def test_malformed_json_returns_parse_error(echo_agent_base_url: str) -> None:
    """A malformed JSON request body MUST yield ``code: -32700`` or HTTP 4xx.

    JSON-RPC 2.0 § 5.1 reserves ``-32700`` for "invalid JSON received
    by the server". Some implementations reject before they can frame
    a JSON-RPC error response and return HTTP 400 with no body —
    accept either; the ``200 + result`` shape would be a real bug.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{echo_agent_base_url}{_JSON_RPC_PATH}",
            content=b"{this is not valid json",
            headers={"content-type": "application/json"},
        )
    if 400 <= response.status_code < 500:
        return
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert "error" in body, f"expected error envelope, got: {body}"
    assert body["error"].get("code") == -32700, f"expected code -32700 (Parse error), got {body['error']}"


@pytest.mark.asyncio
async def test_missing_method_returns_invalid_request(echo_agent_base_url: str) -> None:
    """A JSON-RPC payload missing the ``method`` field MUST yield ``-32600`` or HTTP 4xx.

    The ``method`` field is mandatory per JSON-RPC 2.0 § 4. Absence
    isn't "method not found" — there's no name to look up — it's
    "invalid request" (``-32600``).
    """
    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "params": {}}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{echo_agent_base_url}{_JSON_RPC_PATH}",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    if 400 <= response.status_code < 500:
        return
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert "error" in body, f"expected error envelope, got: {body}"
    assert body["error"].get("code") == -32600, f"expected code -32600 (Invalid Request), got {body['error']}"
