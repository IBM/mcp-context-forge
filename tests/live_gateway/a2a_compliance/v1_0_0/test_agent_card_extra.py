# -*- coding: utf-8 -*-
"""Wave 2 gap-closure tests for A2A 1.0.0 agent-card structural fields.

Location: ./tests/live_gateway/a2a_compliance/v1_0_0/test_agent_card_extra.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Contributors

Closes the 3 Section-1 GAP-BLOCK rows from
``.omo/evidence/c4-audit-checklist.md`` (T9 in
``.omo/plans/a2a-native-passthrough.md``):

1. ``protocolBinding`` is camelCase, NOT ``transportProtocol`` -- closes
   the gotcha that the planning session burned a debug cycle on. The
   A2A 1.0.0 protobuf schema declares ``protocol_binding`` (snake) which
   serializes as ``protocolBinding`` (camel) per protobuf JSON
   convention. The wrong name ``transportProtocol`` is the
   obvious-but-wrong choice that the SDK silently drops, causing
   ``ClientFactory`` to raise "no compatible transports found".
2. ``protocolBinding`` value is ``"JSONRPC"`` for the JSON-RPC
   interface -- exact wire-form match for the SDK's transport router.
3. URL rewritten to gateway-public coordinates, NOT upstream's
   ``endpoint_url`` -- only meaningful against the ``gateway_proxy``
   target; the reference target serves its own URL directly. Closes
   the proxy-must-rewrite-URLs row that drives T2's
   ``synthesize_agent_card`` correctness in Wave 1.

All three tests run RAW HTTP (httpx) against ``raw_card_url``, NOT via
the SDK's ``ClientFactory``. The ``gateway_proxy`` parametrize cell is
auto-xfailed via the existing ``pytest_collection_modifyitems`` hook in
``conftest.py`` under **A2A-GAP-001**; when Wave 3 lands the native
passthrough, that hook gets removed and these tests start surfacing
``XPASS`` until they go fully green.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.a2a, pytest.mark.a2a_v1_0_0, pytest.mark.a2a_agent_card]


@pytest.mark.asyncio
async def test_protocol_binding_is_camelcase_not_transport_protocol(
    raw_card_url: str,
    gap_closure_target: str,
) -> None:
    """Every ``supportedInterfaces[]`` entry MUST use ``protocolBinding`` (camelCase).

    The opposite-but-wrong field name ``transportProtocol`` MUST NOT
    appear. ``a2a-sdk`` silently drops unknown fields, so emitting
    ``transportProtocol`` would make the gateway invisible to clients
    without raising any wire-level error -- exactly the failure mode
    we are guarding against.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(raw_card_url)
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    card = response.json()
    interfaces = card.get("supportedInterfaces", [])
    assert isinstance(interfaces, list) and len(interfaces) >= 1, f"[{gap_closure_target}] supportedInterfaces must be a non-empty list: {interfaces!r}"
    for interface in interfaces:
        assert "protocolBinding" in interface, f"[{gap_closure_target}] interface missing protocolBinding (camelCase): {interface!r}"
        assert "transportProtocol" not in interface, f"[{gap_closure_target}] interface has WRONG field transportProtocol (should be protocolBinding): {interface!r}"


@pytest.mark.asyncio
async def test_protocol_binding_value_is_jsonrpc(
    raw_card_url: str,
    gap_closure_target: str,
) -> None:
    """At least one interface MUST advertise ``protocolBinding == "JSONRPC"``.

    The SDK's ``ClientFactory`` matches transports by exact-string
    binding value. Any other casing (``"JsonRpc"``, ``"jsonrpc"``) or
    misspelling would cause it to reject the interface and fall back to
    "no compatible transports". A2A 1.0.0 echo agents and the
    ContextForge passthrough both standardize on ``"JSONRPC"``.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(raw_card_url)
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    card = response.json()
    interfaces = card.get("supportedInterfaces", [])
    bindings = [interface.get("protocolBinding") for interface in interfaces if isinstance(interface, dict)]
    assert "JSONRPC" in bindings, f"[{gap_closure_target}] no interface declares protocolBinding=JSONRPC; observed bindings: {bindings!r}"


@pytest.mark.asyncio
async def test_interface_url_matches_target_base(
    raw_card_url: str,
    gap_closure_target: str,
    gateway_base_url: str,
    echo_agent_base_url: str,
) -> None:
    """Each interface URL MUST be on the target the card was served from.

    Reference target: the echo agent serves its own card, so each
    interface URL must live under ``echo_agent_base_url``.

    Gateway proxy target: the gateway MUST rewrite each interface URL to
    gateway-public coordinates ``{gateway_base_url}/a2a/{agent_name}``
    (per F8 + T11). Leaving the upstream's ``endpoint_url`` in place
    would point clients straight at the unprotected agent and bypass
    RBAC -- exactly the leak T2 ``synthesize_agent_card`` is built to
    prevent. The check accepts any URL under the gateway base AND
    forbids the upstream URL substring to catch sneaky double-prefix
    leaks.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(raw_card_url)
    assert response.status_code == 200, f"[{gap_closure_target}] {response.text[:200]}"
    card = response.json()
    interfaces = card.get("supportedInterfaces", [])
    assert isinstance(interfaces, list) and len(interfaces) >= 1, f"[{gap_closure_target}] supportedInterfaces must be a non-empty list: {interfaces!r}"

    for interface in interfaces:
        url = interface.get("url", "")
        assert isinstance(url, str) and url, f"[{gap_closure_target}] interface missing url: {interface!r}"

        if gap_closure_target == "reference":
            assert url.startswith(echo_agent_base_url), f"[{gap_closure_target}] interface url {url!r} must start with echo_agent_base_url {echo_agent_base_url!r}"
        elif gap_closure_target in ("gateway_proxy", "gateway_virtual"):
            assert url.startswith(gateway_base_url), f"[{gap_closure_target}] interface url {url!r} must start with gateway_base_url {gateway_base_url!r} (NOT upstream's endpoint_url)"
            assert echo_agent_base_url not in url, f"[{gap_closure_target}] interface url {url!r} leaks upstream echo_agent_base_url {echo_agent_base_url!r} (URL was not rewritten)"
        else:
            raise AssertionError(f"unsupported gap-closure target {gap_closure_target!r}")
