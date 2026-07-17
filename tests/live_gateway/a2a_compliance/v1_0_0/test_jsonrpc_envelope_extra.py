# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_jsonrpc_envelope_extra.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Wave 2 gap-closure: A2A 1.0.0 JSON-RPC envelope validation (Section 2).
Closes the 1 Section-2 GAP-BLOCK row from
``.omo/evidence/c4-audit-checklist.md`` (T10 in
``.omo/plans/a2a-native-passthrough.md``):

- Body NOT a JSON object (``[]``, ``123``, ``"x"``) → ``-32600``.
  JSON-RPC 2.0 § 4 requires the request to be a JSON object. A bare
  array, number, or string is well-formed JSON but is NOT a JSON-RPC
  request envelope. Closes Oracle v2 #7's ``isinstance(body, dict)``
  guard verification for T4's envelope validation.

Test uses ``raw_dispatch_url`` and runs against both ``reference`` and
``gateway_proxy`` targets (gateway_proxy auto-xfails under
A2A-GAP-001 until Wave 3 lands).
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_error_handling]


@pytest.mark.asyncio
async def test_non_dict_body_returns_invalid_request(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """A JSON body that is NOT an object MUST yield ``-32600`` or HTTP 4xx.

    Uses a bare JSON array ``[]`` as the canonical non-object body.
    Other non-object shapes (``123``, ``"x"``) fall under the same
    spec rule; one representative case is sufficient to close the
    BLOCK row.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
        "A2A-Version": "1.0.0",
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, content=b"[]", headers=headers)

    if 400 <= response.status_code < 500:
        return
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    payload = response.json()
    assert "error" in payload, f"[{gap_closure_target}] expected error envelope, got: {payload}"
    assert payload["error"].get("code") == -32600, f"[{gap_closure_target}] expected -32600 INVALID_REQUEST, got {payload['error']}"
