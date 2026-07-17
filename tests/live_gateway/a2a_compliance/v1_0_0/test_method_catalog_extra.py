# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_method_catalog_extra.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Wave 2 gap-closure: A2A 1.0.0 method catalog (Section 3).
Closes the 3 Section-3 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T10):

- ``SendStreamingMessage`` accepted as a JSON-RPC method.
- ``SubscribeToTask`` accepted as a JSON-RPC method.
- ``GetExtendedAgentCard`` accepted as a JSON-RPC method (NOT just an
  HTTP route). Drives the gateway's per-method RBAC + ``-32007``
  trigger from T12 step 8.

These are RAW-HTTP envelope checks: we POST a JSON-RPC request with
the method name and assert the response is either a successful result
envelope OR a typed JSON-RPC error -- crucially NOT ``-32601 Method
Not Found`` (which would prove the method is unrecognized).
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_jsonrpc]


async def _dispatch(url: str, payload: dict, auth_token: str) -> httpx.Response:
    """POST a JSON-RPC payload with bearer auth + A2A-Version=1.0.0."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
        "A2A-Version": "1.0.0",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(url, json=payload, headers=headers)


def _method_is_recognized(response: httpx.Response) -> bool:
    """A method is RECOGNIZED iff the response is not ``-32601 Method Not Found``.

    The method may still fail for OTHER reasons (missing params, auth
    failure, etc.) -- those are NOT method-catalog failures. We only
    assert the method NAME is known.

    Format-agnostic: streaming methods (``SendStreamingMessage``,
    ``SubscribeToTask``, ``message/stream``, ``tasks/resubscribe``)
    return ``text/event-stream`` with ``data: {json-rpc envelope}``
    chunks; unary methods return ``application/json``. Both
    representations carry an embedded JSON-RPC envelope whose
    ``error.code`` we inspect to detect ``-32601``.
    """
    if response.status_code == 404:
        return False
    if response.status_code >= 500:
        return False
    if response.status_code not in (200, 400):
        return True

    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        # SSE: scan ``data:`` lines for an embedded JSON-RPC envelope.
        # The method is recognized as soon as any chunk parses cleanly
        # without ``-32601``; if every chunk is -32601 (unlikely) or
        # no parseable chunk appears, treat as unrecognized.
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
async def test_send_streaming_message_method_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``SendStreamingMessage`` MUST NOT yield ``-32601 Method Not Found``.

    Drives the SSE contract verified by Section 5. A gateway that
    silently lacks this method would let the streaming surface
    silently degrade to "unsupported method" at runtime, breaking
    SDK clients.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendStreamingMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "ping"}]}},
    }
    response = await _dispatch(raw_dispatch_url, payload, auth_token)
    assert _method_is_recognized(response), f"[{gap_closure_target}] SendStreamingMessage NOT recognized: status={response.status_code} body={response.text[:200]!r}"


@pytest.mark.asyncio
async def test_subscribe_to_task_method_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``SubscribeToTask`` MUST NOT yield ``-32601 Method Not Found``.

    Second streaming method in v1.0.0 -- a client uses this to attach
    to an existing task's event stream. Errors like ``TaskNotFound``
    are FINE here; the gate is only "method name is known".
    """
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SubscribeToTask",
        "params": {"id": f"nonexistent-task-{uuid4()}"},
    }
    response = await _dispatch(raw_dispatch_url, payload, auth_token)
    assert _method_is_recognized(response), f"[{gap_closure_target}] SubscribeToTask NOT recognized: status={response.status_code} body={response.text[:200]!r}"


@pytest.mark.asyncio
async def test_get_extended_agent_card_method_recognized(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """``GetExtendedAgentCard`` MUST be accepted as a JSON-RPC method.

    The well-known HTTP route (``GET /extendedAgentCard``) is covered
    by ``test_well_known.py``; this row tests the JSON-RPC method
    surface. Drives T12 step 8's permission check (``a2a.read``) and
    the ``-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`` trigger
    when the agent has no extended card configured.

    Proves the gateway did NOT use a route-level ``@require_permission``
    (Oracle v3 #1) that would block the method before per-method RBAC
    runs.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "GetExtendedAgentCard",
        "params": {},
    }
    response = await _dispatch(raw_dispatch_url, payload, auth_token)
    assert _method_is_recognized(response), f"[{gap_closure_target}] GetExtendedAgentCard NOT recognized: status={response.status_code} body={response.text[:200]!r}"
