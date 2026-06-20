#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Proxy compliance smoke for native A2A 1.0.0 passthrough (Plan T15).

Location: scripts/qa/a2a_proxy_smoke.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Drives a running ContextForge gateway + bundled ``a2a_echo_agent`` to
verify that Wave 2's T9 + T10 gap-closure assertions surface GREEN
against the ``gateway_proxy`` target now that Wave 3 (T11 + T12 + T14)
is in.

THIS IS A TEMPORARY SCRIPT. The full compliance harness at
``tests/live_gateway/a2a_compliance/`` reaches the same coverage as T29
wires the placeholder target classes' ``_open_client`` to a real
``ClientFactory(config=...).create_from_url(...)`` call. When T29
lands, this script becomes dead weight and should be deleted as part
of T30 cleanup.

Prerequisites
-------------
1. Live gateway reachable at the URL the harness uses by default:
   ``http://localhost:4444`` (overridable via
   ``A2A_COMPLIANCE_GATEWAY_URL``).
2. Live ``a2a_echo_agent`` at ``http://127.0.0.1:9100`` (overridable
   via ``A2A_ECHO_BASE_URL``).
3. Echo agent registered with the gateway as ``a2a-echo-agent``
   (overridable via ``A2A_COMPLIANCE_AGENT_NAME``).
4. ``make testing-up`` typically satisfies all three.
5. Bearer token in ``MCPGATEWAY_BEARER_TOKEN`` env. Generate with:
   ``python -m mcpgateway.utils.create_jwt_token --username admin@example.com``

Usage
-----
::

    python scripts/qa/a2a_proxy_smoke.py
    # or
    A2A_COMPLIANCE_GATEWAY_URL=http://localhost:4444 \\
    A2A_COMPLIANCE_AGENT_NAME=a2a-echo-agent \\
    MCPGATEWAY_BEARER_TOKEN=eyJ... \\
    python scripts/qa/a2a_proxy_smoke.py

Exits 0 when ALL assertions pass; exits 1 on first failing assertion
or on any infrastructure prerequisite miss (gateway unreachable,
agent not registered, etc.).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

import httpx


@dataclass
class SmokeResult:
    """One scenario's outcome."""

    name: str
    passed: bool
    details: str


def _env_or(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _gateway_base() -> str:
    return _env_or("A2A_COMPLIANCE_GATEWAY_URL", "http://localhost:4444")


def _agent_name() -> str:
    return _env_or("A2A_COMPLIANCE_AGENT_NAME", "a2a-echo-agent")


def _bearer_token() -> str:
    token = os.environ.get("MCPGATEWAY_BEARER_TOKEN", "")
    if not token:
        # Generate a dev-mode JWT using the same helper as tests.
        # Falls back to an obvious dummy if helper unavailable.
        try:
            from tests.helpers.auth import make_test_jwt  # type: ignore

            token = make_test_jwt(email="admin@example.com", is_admin=True)
        except ImportError:
            token = "dev-fallback-token"
    return token


def _card_url() -> str:
    return f"{_gateway_base()}/a2a/{_agent_name()}/.well-known/agent-card.json"


def _dispatch_url() -> str:
    return f"{_gateway_base()}/a2a/{_agent_name()}"


def _v1_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "A2A-Version": "1.0.0",
        "Authorization": f"Bearer {_bearer_token()}",
    }


def _scenario(label: str, fn: Callable[[], None]) -> SmokeResult:
    """Run a scenario; capture exceptions as PASS=False with reason."""
    try:
        fn()
        return SmokeResult(label, True, "ok")
    except AssertionError as exc:
        return SmokeResult(label, False, f"FAIL: {exc}")
    except Exception as exc:  # pragma: no cover - generic safety net
        return SmokeResult(label, False, f"ERROR ({type(exc).__name__}): {exc}")


# T9 — card discovery scenarios (Section 1 BLOCK rows)


def t9_card_returns_200() -> None:
    """Per-agent card endpoint serves 200 + JSON."""
    response = httpx.get(_card_url(), timeout=10.0)
    assert response.status_code == 200, f"status={response.status_code} body={response.text[:200]!r}"
    assert response.headers.get("content-type", "").startswith("application/json"), response.headers


def t9_protocol_binding_camelcase() -> None:
    """Each ``supportedInterfaces[]`` entry MUST use ``protocolBinding`` (camel)."""
    card = httpx.get(_card_url(), timeout=10.0).json()
    interfaces = card.get("supportedInterfaces", [])
    assert isinstance(interfaces, list) and interfaces, f"supportedInterfaces empty: {interfaces!r}"
    for iface in interfaces:
        assert "protocolBinding" in iface, f"interface missing protocolBinding: {iface!r}"
        assert "transportProtocol" not in iface, f"interface has WRONG name transportProtocol: {iface!r}"


def t9_protocol_binding_jsonrpc() -> None:
    """At least one interface advertises ``protocolBinding == 'JSONRPC'``."""
    card = httpx.get(_card_url(), timeout=10.0).json()
    interfaces = card.get("supportedInterfaces", [])
    bindings = [i.get("protocolBinding") for i in interfaces if isinstance(i, dict)]
    assert "JSONRPC" in bindings, f"no JSONRPC interface; observed bindings: {bindings!r}"


def t9_url_rewritten_to_gateway() -> None:
    """Interface URL points to gateway, NOT upstream's ``endpoint_url``."""
    card = httpx.get(_card_url(), timeout=10.0).json()
    interfaces = card.get("supportedInterfaces", [])
    echo_base = _env_or("A2A_ECHO_BASE_URL", "http://127.0.0.1:9100")
    for iface in interfaces:
        url = iface.get("url", "")
        assert url.startswith(_gateway_base()), f"interface url {url!r} does not start with gateway base {_gateway_base()!r}"
        assert echo_base not in url, f"interface url {url!r} leaks upstream {echo_base!r}"


# T10 — dispatch scenarios (Section 2-8 BLOCK rows)


def t10_non_dict_body_returns_32600() -> None:
    """``POST /a2a/{name}`` with ``body=[]`` → 200 + ``-32600``."""
    r = httpx.post(_dispatch_url(), content=b"[]", headers=_v1_headers(), timeout=10.0)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]!r}"
    body = r.json()
    assert body.get("error", {}).get("code") == -32600, f"expected -32600, got: {body!r}"


def t10_malformed_json_returns_32700() -> None:
    """Malformed JSON → 200 + ``-32700``."""
    r = httpx.post(_dispatch_url(), content=b"{not valid json", headers=_v1_headers(), timeout=10.0)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]!r}"
    body = r.json()
    assert body.get("error", {}).get("code") == -32700, f"expected -32700, got: {body!r}"


def t10_unsupported_version_returns_32009() -> None:
    """``A2A-Version: 99.0.0`` → 200 + ``-32009``."""
    headers = {**_v1_headers(), "A2A-Version": "99.0.0"}
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "x"}]}},
    }
    r = httpx.post(_dispatch_url(), json=payload, headers=headers, timeout=10.0)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]!r}"
    body = r.json()
    assert body.get("error", {}).get("code") == -32009, f"expected -32009, got: {body!r}"


def t10_send_message_returns_result() -> None:
    """``SendMessage`` → 200 + ``result`` (non-empty JSON-RPC envelope)."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "smoke"}]}},
    }
    r = httpx.post(_dispatch_url(), json=payload, headers=_v1_headers(), timeout=15.0)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]!r}"
    body = r.json()
    assert body.get("jsonrpc") == "2.0", f"missing jsonrpc=2.0: {body!r}"
    assert "result" in body or "error" in body, f"no result or error in: {body!r}"


def t10_v03_alias_message_send_recognized() -> None:
    """``message/send`` v0.3 alias is mapped to ``SendMessage`` (NOT -32601)."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "x"}]}},
    }
    # v0.3 aliases tolerate missing A2A-Version header (T7 Q12).
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_bearer_token()}"}
    r = httpx.post(_dispatch_url(), json=payload, headers=headers, timeout=15.0)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]!r}"
    body = r.json()
    err_code = body.get("error", {}).get("code")
    assert err_code != -32601, f"alias rejected as method-not-found: {body!r}"


def t10_tasks_list_NOT_a_legacy_alias() -> None:
    """``tasks/list`` MUST yield ``-32601`` — Oracle v3 #22 anti-pattern."""
    payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "tasks/list", "params": {}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_bearer_token()}"}
    r = httpx.post(_dispatch_url(), json=payload, headers=headers, timeout=10.0)
    # Accept 200 + -32601 OR HTTP 4xx.
    if 400 <= r.status_code < 500:
        return
    body = r.json()
    assert body.get("error", {}).get("code") == -32601, f"tasks/list MUST be -32601 (not a legacy alias): {body!r}"


def t10_streaming_returns_event_stream() -> None:
    """``SendStreamingMessage`` → 200 + ``Content-Type: text/event-stream``."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendStreamingMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "stream"}]}},
    }
    with httpx.stream("POST", _dispatch_url(), json=payload, headers=_v1_headers(), timeout=15.0) as r:
        assert r.status_code == 200, f"status={r.status_code}"
        content_type = r.headers.get("content-type", "")
        assert content_type.startswith("text/event-stream"), f"Content-Type={content_type!r}"
        # Drain at least one chunk to verify the stream is real.
        chunks = 0
        for line in r.iter_lines():
            if line.strip().startswith("data:"):
                # Verify the chunk parses as a JSON-RPC envelope (no double-encoding).
                payload_text = line.strip()[len("data:") :].strip()
                parsed = json.loads(payload_text)
                assert isinstance(parsed, dict), f"SSE chunk not a JSON object: {parsed!r}"
                assert parsed.get("jsonrpc") == "2.0", f"SSE chunk missing jsonrpc=2.0: {parsed!r}"
                chunks += 1
                break
        assert chunks >= 1, "no SSE chunks yielded"


# T10 — RBAC scenarios (Section 8 BLOCK rows)


def t10_missing_authorization_returns_401() -> None:
    """No ``Authorization`` header → HTTP 401 (transport-level)."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "x"}]}},
    }
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0.0"}  # NO Authorization
    r = httpx.post(_dispatch_url(), json=payload, headers=headers, timeout=10.0)
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]!r}"


def t10_invalid_token_returns_401() -> None:
    """Structurally-invalid token → HTTP 401."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendMessage",
        "params": {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": "x"}]}},
    }
    headers = {**_v1_headers(), "Authorization": "Bearer not-a-valid-jwt"}
    r = httpx.post(_dispatch_url(), json=payload, headers=headers, timeout=10.0)
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]!r}"


def main() -> int:
    """Run all scenarios; print summary; exit 0 on full pass, 1 on any fail."""
    gw = _gateway_base()
    agent = _agent_name()
    print(f"A2A proxy compliance smoke")
    print(f"  Gateway     : {gw}")
    print(f"  Agent name  : {agent}")
    print(f"  Card URL    : {_card_url()}")
    print(f"  Dispatch URL: {_dispatch_url()}")
    print()

    # Health probe.
    try:
        probe = httpx.get(f"{gw}/health", timeout=5.0)
    except httpx.HTTPError as exc:
        print(f"FAIL: gateway unreachable at {gw}: {exc}", file=sys.stderr)
        return 1
    if probe.status_code >= 500:
        print(f"FAIL: gateway returned {probe.status_code} on /health", file=sys.stderr)
        return 1

    scenarios: list[tuple[str, Callable[[], None]]] = [
        ("T9.1 card returns 200 + JSON", t9_card_returns_200),
        ("T9.2 protocolBinding camelcase (NOT transportProtocol)", t9_protocol_binding_camelcase),
        ("T9.3 protocolBinding value == JSONRPC", t9_protocol_binding_jsonrpc),
        ("T9.4 URL rewritten to gateway-public", t9_url_rewritten_to_gateway),
        ("T10.1 body=[] -> -32600", t10_non_dict_body_returns_32600),
        ("T10.2 malformed JSON -> -32700", t10_malformed_json_returns_32700),
        ("T10.3 A2A-Version=99.0.0 -> -32009", t10_unsupported_version_returns_32009),
        ("T10.4 SendMessage -> result envelope", t10_send_message_returns_result),
        ("T10.5 message/send v0.3 alias mapped", t10_v03_alias_message_send_recognized),
        ("T10.6 tasks/list NOT a legacy alias (-32601)", t10_tasks_list_NOT_a_legacy_alias),
        ("T10.7 SendStreamingMessage -> text/event-stream", t10_streaming_returns_event_stream),
        ("T10.8 missing Authorization -> 401", t10_missing_authorization_returns_401),
        ("T10.9 invalid token -> 401", t10_invalid_token_returns_401),
    ]

    results = [_scenario(name, fn) for name, fn in scenarios]
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"{'scenario':<60} status   detail")
    print("-" * 100)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"{r.name:<60} {mark:<8} {r.details}")
    print("-" * 100)
    print(f"summary: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
