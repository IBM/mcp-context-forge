# -*- coding: utf-8 -*-
"""Wave 2 gap-closure: A2A 1.0.0 v0.3 method alias acceptance (Section 7).

Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_v03_aliases_extra.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Closes the 4 Section-7 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T10):

- ``message/send`` → forwarded as ``SendMessage``.
- ``tasks/get`` → forwarded as ``GetTask``.
- ``message/stream`` → forwarded as ``SendStreamingMessage``.
- ``tasks/list`` is NOT a legacy alias (NEW in v1.0). Closes Oracle
  v3 #22 anti-pattern.

All 4 tests are GATEWAY-ONLY: the reference echo agent uses the
A2A SDK's native PascalCase methods, NOT the v0.3 slash-aliases. The
gateway's T4 ``LEGACY_V03_METHOD_MAP`` is the layer that translates
the aliases.

For positive-alias tests: the gate is "method is recognized" -- the
gateway returns SOMETHING other than ``-32601 Method Not Found``,
proving the alias was mapped to a v1 method internally.

For the negative ``tasks/list`` test: it MUST yield ``-32601`` (since
``tasks/list`` was never a v0.3 method -- it's NEW in v1.0 as
``ListTasks`` only, and clients sending the slash form are using a
broken assumption).
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_jsonrpc]


def _message_params() -> dict:
    return {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "alias-test"}]}}


def _headers(auth_token: str) -> dict[str, str]:
    """v0.3 clients do NOT send A2A-Version; gateway tolerates this for aliases."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
    }


async def _post(url: str, payload: dict, auth_token: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(url, json=payload, headers=_headers(auth_token))


def _alias_recognized(response: httpx.Response) -> bool:
    """An alias is RECOGNIZED iff response is NOT ``-32601 Method Not Found``.

    Format-agnostic: ``message/stream`` resolves to ``SendStreamingMessage``
    which streams ``text/event-stream`` chunks; unary aliases stream a
    single ``application/json`` envelope. Both representations embed a
    JSON-RPC envelope whose ``error.code`` we inspect for ``-32601``.
    """
    if response.status_code >= 500:
        return False
    if response.status_code == 404:
        return False
    if response.status_code not in (200, 400):
        return True

    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        for line in response.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[len("data: ") :])
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            err = chunk.get("error")
            if isinstance(err, dict) and err.get("code") == -32601:
                return False
            return True
        return False

    try:
        body = response.json()
    except Exception:
        return False
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and err.get("code") == -32601:
        return False
    return True


@pytest.mark.asyncio
async def test_message_send_alias_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``message/send`` MUST be mapped to ``SendMessage`` (NOT -32601)."""
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: v0.3 alias mapping is in T4 LEGACY_V03_METHOD_MAP")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "message/send", "params": _message_params()}
    response = await _post(raw_dispatch_url, payload, auth_token)
    assert _alias_recognized(response), f"[{gap_closure_target}] message/send NOT mapped: status={response.status_code} body={response.text[:200]!r}"


@pytest.mark.asyncio
async def test_tasks_get_alias_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``tasks/get`` MUST be mapped to ``GetTask`` (NOT -32601).

    A ``TaskNotFound`` error for a fake ID is FINE -- the gate is
    only "method name was mapped", NOT "the task exists".
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: v0.3 alias mapping is in T4 LEGACY_V03_METHOD_MAP")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "tasks/get", "params": {"id": f"nonexistent-{uuid4()}"}}
    response = await _post(raw_dispatch_url, payload, auth_token)
    assert _alias_recognized(response), f"[{gap_closure_target}] tasks/get NOT mapped: status={response.status_code} body={response.text[:200]!r}"


@pytest.mark.asyncio
async def test_message_stream_alias_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``message/stream`` MUST be mapped to ``SendStreamingMessage`` (NOT -32601)."""
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: v0.3 alias mapping is in T4 LEGACY_V03_METHOD_MAP")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "message/stream", "params": _message_params()}
    response = await _post(raw_dispatch_url, payload, auth_token)
    assert _alias_recognized(response), f"[{gap_closure_target}] message/stream NOT mapped: status={response.status_code} body={response.text[:200]!r}"


@pytest.mark.asyncio
async def test_tasks_list_is_NOT_a_legacy_alias(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``tasks/list`` MUST yield ``-32601`` -- NOT a v0.3 alias.

    ``ListTasks`` is NEW in v1.0; it has no v0.3 predecessor. Treating
    ``tasks/list`` as a legacy alias would be an anti-pattern (Oracle
    v3 #22) -- a client sending the slash form is confused about the
    protocol generation. The gateway MUST reject with method-not-found.
    """
    if gap_closure_target == "reference":
        pytest.skip("Gateway-only behavior: v0.3 alias-NOT-mapping logic is in T4")

    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "tasks/list", "params": {}}
    # A confused-but-v1 client sends ``A2A-Version: 1.0.0`` (they think
    # they're speaking v1 -- they just used the wrong method shape).
    # The shared ``_headers`` helper deliberately omits the version
    # header for the v0.3 alias-recognition tests; ``tasks/list`` is
    # NOT a v0.3 alias so this test sends a real v1 request envelope.
    headers = {**_headers(auth_token), "A2A-Version": "1.0.0"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(raw_dispatch_url, json=payload, headers=headers)

    # MUST yield -32601 (method not found) OR HTTP 4xx.
    if 400 <= response.status_code < 500:
        return
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    body = response.json()
    assert "error" in body, f"[{gap_closure_target}] tasks/list MUST be rejected; got success: {body}"
    assert body["error"].get("code") == -32601, f"[{gap_closure_target}] tasks/list MUST yield -32601 Method Not Found (NOT a legacy alias); got {body['error']}"
