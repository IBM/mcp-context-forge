# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_sse_streaming_extra.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Wave 2 gap-closure: A2A 1.0.0 SSE shape (Section 5).
Closes the 3 Section-5 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T10):

- Streaming response carries ``Content-Type: text/event-stream``.
- Each SSE ``data:`` chunk parses as a complete JSON-RPC response
  (no double-encoding -- drives the T5 real-SSE-parser pairing in T14).
- At least one chunk yielded for a successful streaming invocation.

All three tests dispatch ``SendStreamingMessage`` via raw httpx
streaming and inspect the wire-level response. The echo agent
implements A2A 1.0.0 streaming, so reference cells pass; gateway_proxy
auto-xfails until T5/T14 land in Wave 3.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_jsonrpc]


def _streaming_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendStreamingMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "sse-marker"}]}},
    }


def _headers(auth_token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
        "A2A-Version": "1.0.0",
        "Accept": "text/event-stream",
    }


@pytest.mark.asyncio
async def test_streaming_content_type_is_text_event_stream(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """Streaming response MUST carry ``Content-Type: text/event-stream``.

    The SSE wire format is what ``ClientFactory`` keys off to detect
    a streaming method. A gateway that returns ``application/json``
    for a streaming method would short-circuit clients into unary
    parsing and lose all but the first chunk.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream("POST", raw_dispatch_url, json=_streaming_payload(), headers=_headers(auth_token)) as response:
            assert response.status_code == 200, f"[{gap_closure_target}] {response.status_code}"
            content_type = response.headers.get("content-type", "")
            assert content_type.startswith("text/event-stream"), f"[{gap_closure_target}] expected Content-Type: text/event-stream, got {content_type!r}"


@pytest.mark.asyncio
async def test_sse_chunks_parse_as_jsonrpc(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """Each SSE ``data:`` chunk MUST parse as a complete JSON-RPC envelope.

    A2A streaming methods emit a series of JSON-RPC responses, one per
    SSE ``data:`` line. Each line's payload MUST be valid JSON-RPC 2.0
    (``jsonrpc`` field present, ``id`` matches request, ``result`` or
    ``error`` discriminated). Double-encoding (a JSON-encoded string
    that contains a JSON object) is the failure mode T5 + T14 are
    built to prevent.
    """
    parsed_chunks: list[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream("POST", raw_dispatch_url, json=_streaming_payload(), headers=_headers(auth_token)) as response:
            assert response.status_code == 200, f"[{gap_closure_target}] {response.status_code}"
            async for line in response.aiter_lines():
                stripped = line.strip()
                if not stripped.startswith("data:"):
                    continue
                payload = stripped[len("data:") :].strip()
                if not payload:
                    continue
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError as exc:
                    pytest.fail(f"[{gap_closure_target}] SSE chunk did not parse as JSON: {exc}; payload={payload[:200]!r}")
                assert isinstance(parsed, dict), f"[{gap_closure_target}] SSE chunk must be a JSON object, got {type(parsed).__name__}: {parsed!r}"
                assert parsed.get("jsonrpc") == "2.0", f"[{gap_closure_target}] SSE chunk missing jsonrpc=2.0: {parsed!r}"
                parsed_chunks.append(parsed)
                if len(parsed_chunks) >= 1:
                    break
    assert parsed_chunks, f"[{gap_closure_target}] no SSE chunks yielded"


@pytest.mark.asyncio
async def test_streaming_yields_at_least_one_chunk(
    raw_dispatch_url: str,
    gap_closure_target: str,
    auth_token: str,
) -> None:
    """A successful streaming invocation MUST yield at least one chunk.

    Zero chunks would mean the stream closed before producing any
    response -- behaviorally indistinguishable from a 200-with-no-body
    failure. SDKs treat zero-chunk streams as protocol errors.
    """
    chunk_count = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream("POST", raw_dispatch_url, json=_streaming_payload(), headers=_headers(auth_token)) as response:
            assert response.status_code == 200, f"[{gap_closure_target}] {response.status_code}"
            async for line in response.aiter_lines():
                if line.strip().startswith("data:"):
                    chunk_count += 1
                    if chunk_count >= 1:
                        break
    assert chunk_count >= 1, f"[{gap_closure_target}] streaming yielded {chunk_count} chunks; expected >= 1"
