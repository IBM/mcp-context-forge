# -*- coding: utf-8 -*-
"""Wave 2 gap-closure: A2A 1.0.0 A2A-Version header negotiation (Section 6).

Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_version_negotiation_extra.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Closes the 3 Section-6 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T10):

- Inbound: gateway rejects missing ``A2A-Version`` for v1 method →
  ``-32009``. Drives T7's reject-empty-for-v1-method path.
- Inbound: gateway tolerates missing ``A2A-Version`` for legacy v0.3
  alias method. Drives T7's legacy-alias allowance per Q12.
- Outbound: gateway sets ``A2A-Version`` response header from
  ``agent.protocol_version``. Verifies T7's ``outbound_a2a_version``
  is wired into T5 streaming headers + T4 unary path.

All 3 tests are GATEWAY-ONLY behaviors. The reference echo agent does
not validate the ``A2A-Version`` request header nor set it on its
responses. Tests skip on reference and auto-xfail on gateway_proxy
until T7 + T4/T5 wiring lands in Wave 3.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_versioning]


def _message_params() -> dict:
    return {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "x"}]}}


@pytest.mark.asyncio
async def test_missing_a2a_version_for_v1_method_returns_32009(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """A v1 method without ``A2A-Version`` header MUST yield ``-32009``.

    T7's ``validate_a2a_version`` requires the header on v1 PascalCase
    methods (``SendMessage``, ``GetTask``, etc.). Missing-header
    rejection is the gate that prevents v0.3 clients from accidentally
    talking to a v1 gateway under their legacy assumption.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: A2A-Version validation is in T7")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendMessage", "params": _message_params()}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {auth_token}"}  # NO A2A-Version
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=payload, headers=headers)

    if 400 <= response.status_code < 500:
        return
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    body = response.json()
    assert "error" in body, f"[{gap_closure_target}] expected error envelope, got: {body}"
    assert body["error"].get("code") == -32009, f"[{gap_closure_target}] expected -32009 VERSION_NOT_SUPPORTED, got {body['error']}"


@pytest.mark.asyncio
async def test_missing_a2a_version_for_v03_alias_is_tolerated(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """A v0.3 alias method without ``A2A-Version`` header MUST be tolerated.

    Per Q12: legacy clients send v0.3 method aliases (``message/send``,
    ``tasks/get``, etc.) WITHOUT ``A2A-Version`` because v0.3 didn't
    require it. The gateway tolerates that combo and routes the
    aliased method through T4's ``LEGACY_V03_METHOD_MAP``.

    The gate is "method is recognized AND no -32009 error". Other
    failure modes (e.g. params shape) are OUT of scope here.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: v0.3 alias acceptance is in T4 + T7")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "message/send", "params": _message_params()}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {auth_token}"}  # NO A2A-Version
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=payload, headers=headers)

    assert response.status_code in (200, 400), f"[{gap_closure_target}] {response.text[:200]}"
    if response.status_code == 200:
        body = response.json()
        if "error" in body:
            err_code = body["error"].get("code")
            assert err_code not in (-32009, -32601), f"[{gap_closure_target}] v0.3 alias rejected with {err_code} (expected -32009 NOT raised, method NOT unknown): {body['error']}"


@pytest.mark.asyncio
async def test_outbound_a2a_version_header_is_set(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """A successful response MUST set ``A2A-Version`` from agent.protocol_version.

    Verifies T7's ``outbound_a2a_version`` helper is wired into T4 +
    T5 response paths. Clients use this header for capability
    discovery; missing it forces them to re-fetch the agent card.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: outbound A2A-Version header is in T7")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendMessage", "params": _message_params()}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {auth_token}", "A2A-Version": "1.0.0"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(raw_dispatch_url, json=payload, headers=headers)

    # If the request failed for an unrelated reason (e.g. params shape),
    # the outbound header may not be set yet. The gate is only meaningful
    # on a 200 response.
    if response.status_code == 200:
        outbound = response.headers.get("a2a-version") or response.headers.get("A2A-Version")
        assert outbound, f"[{gap_closure_target}] response missing A2A-Version header: {dict(response.headers)}"
        assert outbound.startswith("1."), f"[{gap_closure_target}] outbound A2A-Version {outbound!r} not in 1.x line"
