# -*- coding: utf-8 -*-
"""F3 Final Verification — Live A2A SDK manual QA against running gateway.

Location: ./tests/live_gateway/a2a_compliance/test_f3_final_verification.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

13 wire-level scenarios from the plan's third final-verification gate
(``.omo/plans/a2a-native-passthrough.md:1077-1094``). The plan's
success criterion #2 requires this gate to APPROVE for completion.

Each scenario maps to one test function ``test_f3_<letter>_<descr>``:

    (a) Per-agent card discovery (D8 / D9 / URL rewrite)
    (b) Per-agent SendMessage unary dispatch
    (c) Per-agent SendStreamingMessage SSE chunks
    (d) V-server-scoped card + dispatch parity
    (e) V-server membership miss → HTTP 404 (D14)
    (f) Malformed JSON → -32700 (D17)
    (g) Bad A2A-Version → -32009 (D13)
    (h) Legacy v0.3 alias mapping
    (i) GetExtendedAgentCard a2a.read matrix (D18)
    (j) Auth deny matrix (missing / no-invoke / wrong-team)
    (k) UAID cross-gateway dispatch  ← DEFERRED (needs second gateway)
    (l) Concurrent SSE stream cancellation timing (D15)
    (m) Host-header spoofing protection (F15)

Run requirements:

* ``make testing-up`` (gateway on :4444, echo agent on :9100).
* Amendment I.2 fixtures provisioned on first run (team + non-admin
  user + role assignment) — the conftest fixtures self-skip when
  the gateway is unreachable.

Scenarios self-skip when prerequisites are missing (no live gateway,
no team-scoped agent, no v-server bundle, etc.) — mirroring the
existing fixture pattern in ``conftest.py``.

Evidence target: ``.omo/evidence/final-3-a2a-native-passthrough.md``.
Capture mechanism (pytest-html, transcript, or hand-written summary)
is TBD pending review.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from tests.helpers.auth import make_test_jwt

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_f3]


# ───────────────────────────────────────────────────────────────────────
# JSON-RPC payload helpers (mirror the shape used in v1_0_0/test_rbac_extra.py)
# ───────────────────────────────────────────────────────────────────────


def _message_params(text: str = "f3-verification") -> dict:
    """Minimal A2A 1.0.0 message params payload with controllable text."""
    return {"message": {"role": "ROLE_USER", "messageId": str(uuid4()), "parts": [{"text": text}]}}


def _send_message_payload() -> dict:
    """JSON-RPC envelope for SendMessage (unary)."""
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendMessage", "params": _message_params()}


def _streaming_message_payload(text: str = "f3-verification") -> dict:
    """JSON-RPC envelope for SendStreamingMessage.

    Pass ``text="stream:chunks=N,delay_ms=M"`` to drive the echo
    agent's test-mode streaming dispatcher: N JSON-RPC envelope chunks
    yielded at M ms intervals. Without the prefix the agent yields a
    single chunk (default).
    """
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "SendStreamingMessage", "params": _message_params(text)}


def _get_extended_card_payload() -> dict:
    """JSON-RPC envelope for GetExtendedAgentCard (no params)."""
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "GetExtendedAgentCard", "params": {}}


def _legacy_message_send_payload() -> dict:
    """JSON-RPC envelope for v0.3 legacy alias ``message/send``."""
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "message/send", "params": _message_params()}


def _tasks_list_payload() -> dict:
    """JSON-RPC envelope for ``tasks/list`` — Oracle #22 says NOT a mapped alias."""
    return {"jsonrpc": "2.0", "id": str(uuid4()), "method": "tasks/list", "params": {}}


def _base_headers(auth_token: str, version: str = "1.0.0") -> dict[str, str]:
    """Standard A2A request headers (Authorization + Content-Type + A2A-Version)."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "A2A-Version": version,
    }


# ───────────────────────────────────────────────────────────────────────
# Scenario (a) — Per-agent card discovery
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_agent_card_advertises_jsonrpc_binding_and_rewritten_url(
    gateway_base_url: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001 — triggers agent registration
) -> None:
    """(a) Per-agent card discovery — D8 (`protocolBinding`), D9 (per-interface `protocolVersion`), URL rewrite.

    ``GET /a2a/{name}/.well-known/agent-card.json`` returns a v1
    ``AgentCard`` whose ``supportedInterfaces[*]`` advertise
    ``protocolBinding="JSONRPC"`` (camelCase, NOT ``transportProtocol``)
    AND ``protocolVersion`` (per-interface, NOT top-level), with the
    URL rewritten to the gateway's coordinates.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text[:200]}"
    card = response.json()

    # D9: top-level protocolVersion MUST NOT appear; it lives on each interface.
    assert "protocolVersion" not in card, f"top-level protocolVersion forbidden per D9: {sorted(card)}"

    interfaces = card.get("supportedInterfaces") or []
    assert interfaces, f"supportedInterfaces missing or empty: {card!r}"

    iface = interfaces[0]
    # D8: protocolBinding is the camelCase field; transportProtocol is the typo.
    assert "protocolBinding" in iface, f"protocolBinding missing on interface: {iface!r}"
    assert "transportProtocol" not in iface, f"transportProtocol present — D8 violation: {iface!r}"
    assert iface["protocolBinding"] == "JSONRPC", f"phase-1 binding must be JSONRPC, got {iface['protocolBinding']!r}"

    # D9: protocolVersion is per-interface.
    assert "protocolVersion" in iface, f"per-interface protocolVersion missing: {iface!r}"

    # URL rewrite: the gateway base must be advertised, NOT the upstream
    # agent URL. F15 says the card uses configured ``a2a_public_base_url``
    # / ``app_domain`` (not the request Host), so the advertised host may
    # differ from the test client's connection host (e.g. ``localhost``
    # vs ``127.0.0.1`` — both reach the same nginx forward). Validate by
    # path + port instead of exact host string; sanity-check that the
    # URL is not the upstream echo agent's port.
    from urllib.parse import urlparse  # local import keeps test self-contained

    iface_url = iface.get("url", "")
    gw_parsed = urlparse(gateway_base_url)
    iface_parsed = urlparse(iface_url)
    assert iface_parsed.path == f"/a2a/{registered_agent_name}", f"URL not rewritten to gateway path /a2a/{{name}}: {iface_url!r}"
    assert iface_parsed.port == gw_parsed.port, f"URL port {iface_parsed.port} does not match gateway port {gw_parsed.port}: {iface_url!r}"
    # Sanity: must NOT leak the upstream echo agent port (9100 / 9101).
    assert iface_parsed.port not in (9100, 9101), f"URL leaks upstream echo agent port: {iface_url!r}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (b) — Per-agent SendMessage unary dispatch
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_agent_send_message_returns_jsonrpc_result(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(b) Per-agent SendMessage dispatch → JSON-RPC ``result`` envelope.

    HTTP 200 + ``{"jsonrpc":"2.0","result":...,"id":...}``. No
    ``error`` key, no HTTPException, body is a proper JSON-RPC
    response envelope.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=_base_headers(auth_token))
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text[:200]}"
    body = response.json()
    assert body.get("jsonrpc") == "2.0", f"jsonrpc field missing or wrong: {body!r}"
    assert "result" in body, f"result missing from envelope: {body!r}"
    assert "error" not in body, f"unexpected error envelope on success: {body!r}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (c) — Per-agent SendStreamingMessage SSE chunks
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_per_agent_streaming_emits_multiple_jsonrpc_chunks(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(c) Per-agent SendStreamingMessage → multiple SSE ``data:`` chunks, each parsing as JSON-RPC.

    The gateway returns ``text/event-stream``; each ``data: {...}\\n\\n``
    chunk MUST parse as a complete JSON-RPC envelope per D15.
    No double-encoding (D10): the chunk JSON should NOT contain a
    nested ``data:`` prefix.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(auth_token)
    payload = _streaming_message_payload(text="stream:chunks=3,delay_ms=50")

    chunks: list[dict] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            assert response.status_code == 200, f"expected 200, got {response.status_code}"
            assert response.headers.get("content-type", "").startswith("text/event-stream"), f"expected SSE content-type, got {response.headers.get('content-type')!r}"
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[len("data: ") :]
                # D10: no double-encoding — raw should be JSON, not "data: ..." again.
                assert not raw.startswith("data:"), f"double-encoded SSE chunk: {raw!r}"
                chunks.append(json.loads(raw))

    assert len(chunks) >= 2, f"expected multiple SSE data chunks (directive=chunks=3), got {len(chunks)}: {chunks!r}"
    for ch in chunks:
        assert ch.get("jsonrpc") == "2.0", f"chunk missing jsonrpc field: {ch!r}"
        assert "result" in ch or "error" in ch, f"chunk is neither result nor error envelope: {ch!r}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (d) — V-server-scoped card + dispatch parity
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vserver_scoped_card_and_dispatch_match_per_agent(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    server_id: str,
) -> None:
    """(d) V-server-scoped paths produce identical wire shape to per-agent paths.

    ``GET /servers/{id}/a2a/{name}/.well-known/agent-card.json`` →
    same card shape (D8 / D9 / URL rewrite).
    ``POST /servers/{id}/a2a/{name}`` SendMessage → same dispatch
    success envelope.
    """
    card_url = f"{gateway_base_url}/servers/{server_id}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    dispatch_url = f"{gateway_base_url}/servers/{server_id}/a2a/{registered_agent_name}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        card_resp = await client.get(card_url)
        dispatch_resp = await client.post(dispatch_url, json=_send_message_payload(), headers=_base_headers(auth_token))

    assert card_resp.status_code == 200, f"v-server card expected 200, got {card_resp.status_code}: {card_resp.text[:200]}"
    card = card_resp.json()
    assert "protocolVersion" not in card, f"top-level protocolVersion forbidden: {sorted(card)}"
    iface = (card.get("supportedInterfaces") or [{}])[0]
    assert iface.get("protocolBinding") == "JSONRPC"
    # V-server URL form should appear in the rewritten interface URL.
    assert f"/servers/{server_id}/a2a/{registered_agent_name}" in iface.get("url", ""), f"v-server URL not advertised: {iface.get('url')!r}"

    assert dispatch_resp.status_code == 200, f"v-server dispatch expected 200, got {dispatch_resp.status_code}: {dispatch_resp.text[:200]}"
    body = dispatch_resp.json()
    assert body.get("jsonrpc") == "2.0"
    assert "result" in body


# ───────────────────────────────────────────────────────────────────────
# Scenario (e) — V-server membership miss → HTTP 404 (D14)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vserver_membership_miss_returns_404(
    gateway_base_url: str,
    auth_token: str,
    server_id: str,
) -> None:
    """(e) V-server membership miss collapses to HTTP 404 per D14.

    Foreign agent name (not bound to the v-server) at the v-server URL
    form MUST return HTTP 404 — same wire outcome as agent-not-found
    (prevents existence-leak side channels per D11 / Oracle v2 #3).
    """
    foreign_name = f"definitely-not-bound-{uuid4().hex[:8]}"
    url = f"{gateway_base_url}/servers/{server_id}/a2a/{foreign_name}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=_base_headers(auth_token))
    assert response.status_code == 404, f"v-server foreign agent must 404 per D14, got {response.status_code}: {response.text[:200]}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (f) — Malformed JSON → HTTP 200 + -32700 ParseError (D17)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_returns_parse_error_envelope(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(f) Malformed JSON body → HTTP 200 + JSON-RPC ``-32700 ParseError``.

    D17 mandates manual ``await request.body()`` parsing — that is the
    only way to surface ``-32700`` (FastAPI's ``Body(...)`` would 422
    before the handler runs).
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(auth_token)
    # Deliberately broken JSON — unterminated brace, no value.
    bad_body = b'{"jsonrpc": "2.0", "method": "SendMessage", "params":'
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, content=bad_body, headers=headers)
    assert response.status_code == 200, f"malformed JSON must yield HTTP 200 + JSON-RPC error per D6, got {response.status_code}: {response.text[:200]}"
    body = response.json()
    assert body.get("error", {}).get("code") == -32700, f"expected -32700 ParseError, got {body!r}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (g) — Bad A2A-Version → HTTP 200 + -32009 VersionNotSupported (D13)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_a2a_version_returns_version_error_envelope(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(g) ``A2A-Version: 2.0`` header → HTTP 200 + JSON-RPC ``-32009 VersionNotSupported``.

    D13 method-aware validation: a v1 method (``SendMessage``) with a
    non-1.0 version header MUST reject via the JSON-RPC envelope, not
    via a transport-level error.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(auth_token, version="2.0")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 200, f"version error must yield HTTP 200, got {response.status_code}: {response.text[:200]}"
    body = response.json()
    assert body.get("error", {}).get("code") == -32009, f"expected -32009 VersionNotSupported, got {body!r}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (h) — Legacy v0.3 alias mapping (Q12 + Oracle #22)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_message_send_alias_dispatches_as_send_message(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(h.1) Legacy ``message/send`` alias maps to ``SendMessage`` (Q12 transition).

    A v0.3 method body without ``A2A-Version`` MUST dispatch
    successfully because legacy methods tolerate missing header per
    ``validate_a2a_version`` (T7).
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    # Omit A2A-Version intentionally — legacy alias path.
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=_legacy_message_send_payload(), headers=headers)
    assert response.status_code == 200, f"legacy alias dispatch expected 200, got {response.status_code}: {response.text[:200]}"
    body = response.json()
    # Either a success result OR a forwarded upstream error — both prove the alias mapped.
    # What MUST NOT happen: -32601 method-not-found (Oracle #22 negative case is on tasks/list, not this).
    error = body.get("error") or {}
    assert error.get("code") != -32601, f"message/send must NOT be -32601; alias mapping required: {body!r}"


@pytest.mark.asyncio
async def test_tasks_list_is_not_aliased_to_known_method(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(h.2) ``tasks/list`` is NOT a mapped alias (Oracle #22 negative case).

    Unlike ``message/send`` which became ``SendMessage``, ``tasks/list``
    is not mapped to anything — it should surface as either
    ``-32601 MethodNotFound`` (preferred per spec) OR an A2A-specific
    error code from the upstream, but NOT silently succeed.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_tasks_list_payload(), headers=headers)
    # Either HTTP 200 + JSON-RPC error envelope, or transport-level rejection — both prove non-mapping.
    if response.status_code == 200:
        body = response.json()
        assert "error" in body, f"tasks/list must NOT silently succeed (Oracle #22): {body!r}"
    else:
        # Transport-level rejection also acceptable (e.g., 400/404 for unknown method shape).
        assert response.status_code in {400, 404, 501}, f"unexpected status for unmapped tasks/list: {response.status_code} {response.text[:200]}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (i) — GetExtendedAgentCard a2a.read matrix (D18 + Oracle v3 #1)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extended_card_with_read_permission_returns_200(
    gateway_base_url: str,
    a2a_read_only_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(i.1) ``GetExtendedAgentCard`` with ``a2a.read`` → HTTP 200 (synthesized locally per D18).

    Proves the dispatch route did NOT use route-level
    ``@require_permission("a2a.invoke")`` (Oracle v3 #1). HTTP 200
    covers both a successful extended-card response AND the
    ``-32007 AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`` envelope —
    both prove the per-method permission check ran inside dispatch.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(a2a_read_only_token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_get_extended_card_payload(), headers=headers)
    assert response.status_code == 200, f"a2a.read on GetExtendedAgentCard must yield 200, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_extended_card_without_read_permission_returns_403(
    gateway_base_url: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
    no_perm_user_token: str,
) -> None:
    """(i.2) ``GetExtendedAgentCard`` without ``a2a.read`` → HTTP 403.

    Symmetric to the prior test: a non-admin user with no roles
    cannot call ``GetExtendedAgentCard``. Drives T12 step 8's
    per-method permission check. Uses ``no_perm_user_token`` (a real
    user in the DB with zero RBAC role assignments) so auth passes
    and the per-method ``a2a.read`` check is the one that 403s.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(no_perm_user_token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_get_extended_card_payload(), headers=headers)
    assert response.status_code == 403, f"no a2a.read must yield 403, got {response.status_code}: {response.text[:200]}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (j) — Auth deny matrix (D11 / Oracle #3)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_without_authorization_returns_401(
    gateway_base_url: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(j.1) Dispatch WITHOUT ``Authorization`` → HTTP 401 (transport-level).

    Auth middleware rejects unauthenticated requests BEFORE the
    JSON-RPC envelope is parsed — no ``-32600`` etc. in the body.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0.0"}  # NO Authorization
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 401, f"missing token must yield 401, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_dispatch_without_invoke_permission_returns_403(
    gateway_base_url: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
    no_perm_user_token: str,
) -> None:
    """(j.2) Authenticated caller without ``a2a.invoke`` → HTTP 403.

    Uses ``no_perm_user_token`` (real user, zero RBAC roles) so auth
    passes and the per-method ``a2a.invoke`` check is the one that
    denies with 403. Previously this test used a JWT for a nonexistent
    user, which auth correctly 401'd before reaching RBAC.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(no_perm_user_token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 403, f"no a2a.invoke must yield 403, got {response.status_code}: {response.text[:200]}"


@pytest.mark.asyncio
async def test_wrong_team_token_on_team_scoped_agent_returns_404(
    gateway_base_url: str,
    team_scoped_agent_name: str,
    team_scoped_agent_id: str,  # noqa: ARG001 — triggers team-scoped agent registration
    wrong_team_auth_token: str,
) -> None:
    """(j.3) Team-scoped agent + wrong-team token → HTTP 404 (visibility hide per D11).

    Layer-1 token scoping filters the team-scoped agent out, so the
    dispatch returns HTTP 404 instead of 403 — visibility HIDES,
    never 403s (D11 / Oracle #3).
    """
    url = f"{gateway_base_url}/a2a/{team_scoped_agent_name}"
    headers = _base_headers(wrong_team_auth_token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=_send_message_payload(), headers=headers)
    assert response.status_code == 404, f"wrong-team must yield 404 per D11, got {response.status_code}: {response.text[:200]}"


# ───────────────────────────────────────────────────────────────────────
# Scenario (k) — UAID cross-gateway dispatch [DEFERRED]
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uaid_cross_gateway_dispatch_routes_via_federation() -> None:
    """(k) UAID cross-gateway dispatch routes through federation path (Oracle #13).

    DEFERRED: requires a SECOND gateway instance with shared JWT
    secret / federated SSO + a registered UAID agent that points
    across gateways. The plan calls for echo agents on ports 9100
    AND 9101 plus a federation-configured gateway. Out of scope for
    the first F3 draft per user direction; tracked separately.
    """
    pytest.skip("Deferred: two-gateway federation setup required; see .omo/plans/a2a-native-passthrough.md:1088 (scenario k)")


# ───────────────────────────────────────────────────────────────────────
# Scenario (l) — Concurrent SSE stream cancellation (D15)
# ───────────────────────────────────────────────────────────────────────


async def _drain_sse(response: httpx.Response, chunks: list[dict]) -> None:
    """Consume an SSE response, appending parsed JSON-RPC envelopes to ``chunks``.

    Used by scenario (l) to run two streams concurrently and observe
    cancellation behavior on one while the other continues.
    """
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :]
        try:
            chunks.append(json.loads(raw))
        except json.JSONDecodeError:
            # Malformed chunk — not what this test verifies, surface via the chunks count.
            return


@pytest.mark.asyncio
async def test_concurrent_sse_stream_cancellation_isolates_streams(
    gateway_base_url: str,
    auth_token: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(l) Concurrent SSE streams — cancellation closes cleanly within target window (D15).

    First-draft contract:

    * Open two concurrent SSE streams to ``SendStreamingMessage``.
    * Both must successfully start (status 200, ``text/event-stream``).
    * Cancel ONE consumption task partway through.
    * The cancelled stream's context manager exits without leaking
      an exception.
    * The other stream's consumption is unaffected (continues to
      completion or yields at least one chunk).
    * Client-side cancellation completes within ``CANCEL_BUDGET_MS``
      — informational target derived from D15's "~100ms upstream
      close" budget. Treated as a soft assertion (logged, not
      hard-failed) in the first draft because definitive upstream-
      connection-close verification needs tcpdump / socket-level
      observation that pytest cannot do alone.

    Followups for a future iteration (NOT in first draft):

    * Add ``tcpdump -i any -w /tmp/f3-l.pcap host <echo-agent>``
      capture + post-test pcap parse to assert the upstream FIN
      lands within 100ms of the client cancel.
    * Instrument the gateway's ``dispatch_a2a_jsonrpc_streaming``
      with a structured-log event on async-generator close so the
      pytest run can correlate gateway-side close timing without
      tcpdump.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}"
    headers = _base_headers(auth_token)
    cancel_budget_ms = 250.0  # First-draft soft target; D15 aspirational is ~100ms.
    # Drive a ~2s stream (10 chunks at 200ms intervals) via the echo agent's
    # test directive — long enough to cancel mid-stream after the 50ms sleep
    # below, with plenty of headroom for stream B to keep yielding chunks
    # while A is being cancelled.
    payload = _streaming_message_payload(text="stream:chunks=10,delay_ms=200")

    chunks_a: list[dict] = []
    chunks_b: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp_a:
            assert resp_a.status_code == 200, f"stream A start expected 200, got {resp_a.status_code}"
            async with client.stream("POST", url, json=payload, headers=headers) as resp_b:
                assert resp_b.status_code == 200, f"stream B start expected 200, got {resp_b.status_code}"
                assert resp_a.headers.get("content-type", "").startswith("text/event-stream"), "stream A not SSE"
                assert resp_b.headers.get("content-type", "").startswith("text/event-stream"), "stream B not SSE"

                # Drive both streams in parallel tasks so we can cancel A while B continues.
                task_a = asyncio.create_task(_drain_sse(resp_a, chunks_a))
                task_b = asyncio.create_task(_drain_sse(resp_b, chunks_b))

                # Give both streams a tiny head start so at least one chunk lands before cancel.
                await asyncio.sleep(0.05)

                # Cancel A and time how long the cancellation actually takes to settle.
                cancel_start = time.monotonic()
                task_a.cancel()
                try:
                    await task_a
                except asyncio.CancelledError:
                    pass
                cancel_elapsed_ms = (time.monotonic() - cancel_start) * 1000.0

                # B must still be making progress or have completed cleanly.
                try:
                    await asyncio.wait_for(task_b, timeout=10.0)
                except asyncio.TimeoutError:
                    task_b.cancel()
                    pytest.fail("stream B did not complete within 10s after stream A was cancelled — concurrency broken")

    # Informational: log the cancel timing rather than hard-asserting until we have upstream observation.
    print(f"[F3 scenario l] client-side cancel completed in {cancel_elapsed_ms:.1f}ms (D15 target: ~100ms)")

    # The hard wire-level assertion: stream A's cancellation did not corrupt or block stream B.
    # We do NOT require any chunks from A (it may have been cancelled before any landed); B should
    # have at least started — the echo agent's SSE always produces ≥1 chunk on success.
    assert chunks_b, "stream B produced zero chunks — concurrent streams not isolated"

    # Soft assertion: client-side cancellation completed within the budget. Logged-not-failed
    # in first draft because the real D15 target is upstream-close timing, not client-receive
    # timing. Once tcpdump-based verification lands, flip this to a hard assertion.
    if cancel_elapsed_ms > cancel_budget_ms:
        print(f"[F3 scenario l] WARNING: cancel took {cancel_elapsed_ms:.1f}ms > {cancel_budget_ms:.1f}ms budget — investigate before flipping to hard assertion")


# ───────────────────────────────────────────────────────────────────────
# Scenario (m) — Host-header spoofing protection (F15)
# ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_host_header_spoofing_does_not_poison_card_url(
    gateway_base_url: str,
    registered_agent_name: str,
    registered_agent_id: str,  # noqa: ARG001
) -> None:
    """(m) Host-header spoofing — card URL uses configured ``a2a_public_base_url``, not spoofed ``Host``.

    F15 + Oracle re-review #4: a malicious ``Host: evil.example.com``
    on the well-known card request MUST NOT poison the advertised
    interface URL. The gateway derives the public base from
    ``settings.a2a_public_base_url`` or ``settings.app_domain``,
    NEVER from the request ``Host`` header.

    Prerequisite: the gateway has either ``a2a_public_base_url`` or
    ``app_domain`` configured to a value that differs from the
    spoofed Host. If not configured, the gateway falls back to the
    request Host and this test skips with an informational note.
    """
    url = f"{gateway_base_url}/a2a/{registered_agent_name}/.well-known/agent-card.json"
    spoofed_host = "evil.example.com"
    headers = {"Host": spoofed_host}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # First, baseline: fetch without spoofing to see what URL the card normally advertises.
        baseline = await client.get(url)
        if baseline.status_code != 200:
            pytest.skip(f"baseline card fetch failed: {baseline.status_code} {baseline.text[:200]}")
        baseline_card = baseline.json()
        baseline_iface = (baseline_card.get("supportedInterfaces") or [{}])[0]
        baseline_url = baseline_iface.get("url", "")

        if spoofed_host in baseline_url:
            pytest.skip(f"baseline card URL already contains '{spoofed_host}' — gateway has no configured base URL distinct from Host; F15 protection cannot be tested in this deployment")

        # Now spoof Host and assert the advertised URL does NOT pick it up.
        spoofed = await client.get(url, headers=headers)

    assert spoofed.status_code == 200, f"spoofed-Host card fetch expected 200, got {spoofed.status_code}: {spoofed.text[:200]}"
    spoofed_card = spoofed.json()
    spoofed_iface = (spoofed_card.get("supportedInterfaces") or [{}])[0]
    spoofed_advertised_url = spoofed_iface.get("url", "")

    assert spoofed_host not in spoofed_advertised_url, f"F15 violation: spoofed Host poisoned advertised URL: {spoofed_advertised_url!r}"
    # And: the advertised URL should match the baseline (both come from settings, not from the request).
    assert (
        spoofed_advertised_url == baseline_url
    ), f"F15 partial: spoofed card URL ({spoofed_advertised_url!r}) differs from baseline ({baseline_url!r}) — spoofed value SHOULD be ignored, baseline SHOULD be stable"
