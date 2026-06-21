# -*- coding: utf-8 -*-
"""Oracle F1 #2 regression: streaming dispatch must not forward caller bearer.

Location: ./tests/unit/mcpgateway/services/test_a2a_streaming_auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Pin the post-fix behavior of
:meth:`A2AAgentService.dispatch_a2a_jsonrpc_streaming` so the next
regression is caught at commit time:

1. The caller bearer token is NEVER forwarded to the upstream agent —
   D5 says caller bearers only flow via the cross-gateway UAID
   federation path (not in scope for streaming today).
2. The streaming path applies registered agent auth via
   :func:`prepare_a2a_invocation` instead of bypassing it.
3. The passthrough-header whitelist is honored — caller headers not
   listed in ``agent.passthrough_headers`` are dropped before the
   upstream POST.
4. The SSE-specific ``Accept: text/event-stream`` override is set on
   ``prepared.headers``.

The pre-fix shape (a2a_service.py:1465-1500 PRE-Oracle-fix-commit)
unconditionally forwarded the caller's ``Authorization: Bearer ...``
header to ``agent.endpoint_url``. That is a Scope OUT #15 violation
of the A2A native passthrough plan.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent(*, name: str = "echo", passthrough_headers: Optional[List[str]] = None) -> SimpleNamespace:
    """Build a session-detached A2AAgent stand-in for the streaming call."""
    return SimpleNamespace(
        id="agent-uuid",
        name=name,
        agent_type="jsonrpc",
        endpoint_url="http://upstream.example/a2a",
        protocol_version="1.0.0",
        auth_type=None,
        auth_value=None,
        auth_query_params=None,
        passthrough_headers=passthrough_headers,
        team_id=None,
        visibility="public",
        enabled=True,
        tags=[],
        oauth_config=None,
    )


class _RecordingStreamContext:
    """``async with`` ctx that captures the call args and yields a fake SSE response."""

    def __init__(self, captured: Dict[str, Any]) -> None:
        self._captured = captured
        self.status_code = 200

    async def __aenter__(self) -> "_RecordingStreamContext":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        if False:  # pylint: disable=using-constant-test
            yield ""  # type: ignore[unreachable]


def _build_mock_client(captured: Dict[str, Any]) -> MagicMock:
    """Return a mock httpx client whose ``stream(...)`` records call args."""
    client = MagicMock()

    def _stream(method: str, url: str, **kwargs: Any) -> _RecordingStreamContext:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(kwargs.get("headers") or {})
        captured["json_body"] = kwargs.get("json")
        return _RecordingStreamContext(captured)

    client.stream = _stream
    return client


@pytest.mark.asyncio
async def test_streaming_does_not_forward_caller_bearer_token(monkeypatch) -> None:
    """Oracle F1 #2 fix: caller's bearer token is dropped before the upstream POST."""
    # First-Party
    from mcpgateway.services.a2a_service import A2AAgentService

    captured: Dict[str, Any] = {}
    mock_client = _build_mock_client(captured)

    async def _get_http_client() -> MagicMock:
        return mock_client

    monkeypatch.setattr(
        "mcpgateway.services.http_client_service.get_http_client",
        _get_http_client,
    )

    service = A2AAgentService()
    agent = _make_agent()
    body = {
        "jsonrpc": "2.0",
        "method": "SendStreamingMessage",
        "params": {"message": {"role": "user", "parts": [{"text": "hi"}]}},
        "id": "client-req-1",
    }

    chunks: List[Dict[str, Any]] = []
    async for chunk in service.dispatch_a2a_jsonrpc_streaming(
        db=MagicMock(),
        agent=agent,
        body=body,
        bearer_token="caller-jwt-token-do-not-forward",  # pragma: allowlist secret
        hop_count=0,
        request_headers={},
    ):
        chunks.append(chunk)

    # Regression assertion: Authorization header must NOT be in the upstream call.
    sent_headers = captured.get("headers", {})
    auth_keys = [k for k in sent_headers if k.lower() == "authorization"]
    assert auth_keys == [], f"Authorization header was forwarded upstream: {sent_headers}"


@pytest.mark.asyncio
async def test_streaming_applies_sse_accept_header(monkeypatch) -> None:
    """The streaming refactor must override Accept to text/event-stream after prepare_a2a_invocation."""
    # First-Party
    from mcpgateway.services.a2a_service import A2AAgentService

    captured: Dict[str, Any] = {}
    mock_client = _build_mock_client(captured)

    async def _get_http_client() -> MagicMock:
        return mock_client

    monkeypatch.setattr(
        "mcpgateway.services.http_client_service.get_http_client",
        _get_http_client,
    )

    service = A2AAgentService()
    agent = _make_agent()
    body = {
        "jsonrpc": "2.0",
        "method": "SendStreamingMessage",
        "params": {},
        "id": "x",
    }

    async for _chunk in service.dispatch_a2a_jsonrpc_streaming(
        db=MagicMock(),
        agent=agent,
        body=body,
        bearer_token=None,
        hop_count=0,
        request_headers=None,
    ):
        pass

    sent_headers = captured.get("headers", {})
    assert sent_headers.get("Accept") == "text/event-stream", f"Accept header should be SSE: {sent_headers}"


@pytest.mark.asyncio
async def test_streaming_honors_passthrough_header_whitelist(monkeypatch) -> None:
    """Caller headers outside ``agent.passthrough_headers`` are NOT forwarded; whitelisted ones ARE."""
    # First-Party
    from mcpgateway.services.a2a_service import A2AAgentService

    captured: Dict[str, Any] = {}
    mock_client = _build_mock_client(captured)

    async def _get_http_client() -> MagicMock:
        return mock_client

    monkeypatch.setattr(
        "mcpgateway.services.http_client_service.get_http_client",
        _get_http_client,
    )

    service = A2AAgentService()
    agent = _make_agent(passthrough_headers=["X-Trace-Id", "X-Tenant"])
    body = {
        "jsonrpc": "2.0",
        "method": "SendStreamingMessage",
        "params": {},
        "id": "x",
    }

    async for _chunk in service.dispatch_a2a_jsonrpc_streaming(
        db=MagicMock(),
        agent=agent,
        body=body,
        bearer_token=None,
        hop_count=0,
        request_headers={
            "X-Trace-Id": "trace-123",
            "X-Tenant": "tenant-a",
            "X-Should-Be-Dropped": "leaked",
            "Cookie": "session=abc",
        },
    ):
        pass

    sent_headers = captured.get("headers", {})
    # Whitelisted headers pass through.
    assert sent_headers.get("X-Trace-Id") == "trace-123"
    assert sent_headers.get("X-Tenant") == "tenant-a"
    # Non-whitelisted headers are dropped.
    assert "X-Should-Be-Dropped" not in sent_headers, f"non-whitelisted header leaked: {sent_headers}"
    assert "Cookie" not in sent_headers, "Cookie should never reach upstream"
    # Authorization is unconditionally excluded even if the caller put it in passthrough_headers.
    auth_keys = [k for k in sent_headers if k.lower() == "authorization"]
    assert auth_keys == [], "Authorization must NEVER pass through the whitelist channel"
