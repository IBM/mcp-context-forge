# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_runtime_mode.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Runtime-mutable MCP mode (shadow ↔ edge) smoke and drift tests.

Exercises the gateway's ``/admin/runtime/mcp-mode`` API and, when the
gateway booted with Rust support (``RUST_MCP_MODE=shadow|edge``), flips
between ``shadow`` and ``edge`` mid-run to catch behavioral drift between
the Python and Rust ingress paths.

The fixtures skip cleanly when:
  * The gateway isn't reachable (shared with other gateway-target tests).
  * The runtime-mode admin endpoint is missing (older gateway builds).
  * The gateway booted ``off`` — PATCH rejects with 409 and this test skips.

Issue #4273 tracks the underlying feature.
"""

from __future__ import annotations

import json

import pytest

pytestmark = [pytest.mark.protocol_compliance, pytest.mark.mcp_transport_core]


def test_runtime_mode_state_is_readable(runtime_mode_state: dict) -> None:
    """GET /admin/runtime/mcp-mode returns a well-shaped state payload."""
    for key in ("runtime", "boot_mode", "effective_mode", "mounted", "supported_override_modes"):
        assert key in runtime_mode_state, f"state payload missing {key!r}: {runtime_mode_state}"
    assert runtime_mode_state["runtime"] == "mcp"
    assert runtime_mode_state["boot_mode"] in {"off", "shadow", "edge", "full"}
    assert runtime_mode_state["mounted"] in {"python", "rust"}


def test_runtime_mode_off_rejects_flip(gateway_http_client, runtime_mode_state: dict) -> None:
    """When booted ``off``, PATCHing any mode returns 409 with a clear reason.

    This asserts the gateway's safety rail: overrides require the Rust
    sidecar present at boot, which ``off`` does not include. Skip when the
    gateway didn't boot ``off`` — the rail doesn't apply there.
    """
    if runtime_mode_state["boot_mode"] != "off":
        pytest.skip(f"gateway booted {runtime_mode_state['boot_mode']}; this rail only checked under boot_mode=off")
    resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": "edge"})
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}: {resp.text[:200]}"
    assert "boot_mode" in resp.text or "off" in resp.text, f"409 body should reference the boot_mode=off constraint: {resp.text[:200]}"


def test_runtime_mode_flip_to_edge_mounts_rust(flip_runtime_mode) -> None:
    """Flipping to ``edge`` updates ``mounted`` to ``rust``.

    Asserts only against the PATCH response, which is the authoritative
    acknowledgement of the flip on the serving pod. Cross-pod GET
    consistency is documented as eventual (Redis pub/sub) — concurrent
    flips from other pods can supersede version counters in ways a
    single-pod harness shouldn't try to synchronize. The publish_status
    and audit_persisted assertions elsewhere cover the cluster-propagation
    contract.
    """
    post_flip = flip_runtime_mode("edge")
    assert post_flip["effective_mode"] == "edge"
    assert post_flip["mounted"] == "rust", f"flip to edge should mount rust ingress, got mounted={post_flip['mounted']!r}"


def test_runtime_mode_flip_to_shadow_mounts_python(flip_runtime_mode) -> None:
    """Flipping to ``shadow`` mounts the Python ingress path (see sibling docstring)."""
    post_flip = flip_runtime_mode("shadow")
    assert post_flip["effective_mode"] == "shadow"
    assert post_flip["mounted"] == "python", f"flip to shadow should mount python ingress, got mounted={post_flip['mounted']!r}"


def test_runtime_mode_rejects_unsupported(gateway_http_client, runtime_mode_state: dict) -> None:
    """Unsupported override modes (e.g. ``off``, ``full``, ``bogus``) return 400+."""
    for bad_mode in ("off", "full", "bogus"):
        resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": bad_mode})
        assert resp.status_code >= 400, f"expected rejection for mode={bad_mode!r}, got {resp.status_code}: {resp.text[:200]}"


def test_shadow_boot_rejects_edge_with_safety_flag_reason(gateway_http_client, runtime_mode_state: dict) -> None:
    """Boot=shadow must refuse mode=edge with a safety-flag-gated 409.

    The spec requires ``experimental_rust_mcp_session_auth_reuse_enabled``,
    which only boot_mode=edge sets. Any PATCH asking for edge from a
    non-edge boot is rejected with a message naming that constraint.
    """
    if runtime_mode_state["boot_mode"] != "shadow":
        pytest.skip(f"gateway booted {runtime_mode_state['boot_mode']}; this rail only checked under boot_mode=shadow")
    resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": "edge"})
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}: {resp.text[:200]}"
    body = resp.text.lower()
    assert "safety" in body or "reuse" in body or "edge" in body, f"409 body should explain the safety-flag constraint: {resp.text[:300]}"


def test_patch_response_carries_publish_and_audit_fields(flip_runtime_mode, runtime_mode_state: dict) -> None:
    """Successful PATCH returns ``publish_status`` and ``audit_persisted`` fields.

    Both fields are part of the documented response contract; callers use
    them to know whether peers received the flip and whether the audit
    trail landed.
    """
    # A no-op flip (shadow→shadow on shadow boot, or edge→edge on edge boot)
    # is the broadest way to get a 200 PATCH response across boot modes.
    # flip_runtime_mode skips if the flip is refused.
    target = runtime_mode_state["effective_mode"]
    if target not in ("shadow", "edge"):
        pytest.skip(f"no flippable target for boot_mode={target!r}")
    resp = flip_runtime_mode(target)
    assert "publish_status" in resp, f"missing publish_status: {resp}"
    assert resp["publish_status"] in {"propagated", "local-only", "failed", "superseded"}, f"unexpected publish_status: {resp['publish_status']!r}"
    assert "audit_persisted" in resp, f"missing audit_persisted: {resp}"
    assert isinstance(resp["audit_persisted"], bool), f"audit_persisted must be bool, got {type(resp['audit_persisted']).__name__}"


def test_get_carries_cluster_propagation_and_reconcile_status(runtime_mode_state: dict) -> None:
    """GET payload exposes cluster_propagation and boot_reconcile_status with valid enums."""
    assert "cluster_propagation" in runtime_mode_state
    assert runtime_mode_state["cluster_propagation"] in {"redis", "disabled", "degraded"}, f"unexpected cluster_propagation: {runtime_mode_state['cluster_propagation']!r}"
    assert "boot_reconcile_status" in runtime_mode_state
    assert runtime_mode_state["boot_reconcile_status"] in {
        "ok",
        "incompatible_no_dispatcher",
        "incompatible_boot_full",
        "incompatible_safety_flag",
    }, f"unexpected boot_reconcile_status: {runtime_mode_state['boot_reconcile_status']!r}"


def test_health_mirrors_runtime_mode_state(gateway_http_client) -> None:
    """`/health` surfaces the same runtime-mode state as the admin endpoint.

    Multi-pod deployments propagate state via Redis, so a single admin GET
    and a single health GET may land on different pods at different
    propagation points. Poll briefly for convergence before asserting
    mirror equality — ``effective_mode`` is the leading indicator.
    """
    import time as _time

    deadline = _time.monotonic() + 3.0
    admin = None
    mcp_rt = None
    while _time.monotonic() < deadline:
        admin = gateway_http_client.get("/admin/runtime/mcp-mode").json()
        health = gateway_http_client.get("/health").json()
        mcp_rt = health.get("mcp_runtime")
        if mcp_rt is None:
            pytest.skip("/health does not expose mcp_runtime block on this deployment")
        if mcp_rt.get("effective_mode") == admin.get("effective_mode"):
            break
        _time.sleep(0.1)
    for key in ("boot_mode", "effective_mode", "override_active", "cluster_propagation"):
        assert mcp_rt.get(key) == admin.get(key), f"mcp_runtime.{key}={mcp_rt.get(key)!r} vs admin.{key}={admin.get(key)!r}"


# ---------------------------------------------------------------------------
# Data-plane witness tests
#
# Control-plane assertions above prove the admin API accepts the flip and
# reports the new state. These tests go further: they issue a real MCP
# ``initialize`` request after the flip and read ``x-contextforge-mcp-runtime``
# off the response to confirm the actual dispatch path changed. That header
# is the data-plane witness — its value tells us which transport served the
# request.
# ---------------------------------------------------------------------------
_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "compliance-harness", "version": "0.1.0"},
    },
}
_MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-03-26",
}


def _mcp_initialize_runtime_header(gateway_http_client) -> str:
    """POST an initialize and return ``x-contextforge-mcp-runtime`` on the response."""
    resp = gateway_http_client.post("/mcp/", headers=_MCP_HEADERS, json=_INIT_BODY)
    assert resp.status_code == 200, f"initialize failed: {resp.status_code} {resp.text[:200]}"
    runtime = resp.headers.get("x-contextforge-mcp-runtime")
    assert runtime in {"python", "rust"}, f"response missing or invalid x-contextforge-mcp-runtime header: {runtime!r}"
    return runtime


def test_data_plane_runtime_header_under_edge(flip_runtime_mode, gateway_http_client) -> None:
    """After flipping to ``edge``, an MCP initialize response names the Rust runtime.

    This is the strict data-plane witness. It passes on both direct-to-pod
    topologies and nginx-fronted topologies (where nginx always routes to
    Rust under boot_mode=edge, matching the flip target).
    """
    flip_runtime_mode("edge")
    runtime = _mcp_initialize_runtime_header(gateway_http_client)
    assert runtime == "rust", f"after flipping to edge, expected the Rust runtime on the data plane, " f"got x-contextforge-mcp-runtime={runtime!r}"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "GAP-010: nginx reverse-proxy does not follow runtime flips. Shadow flip "
        "is observable on the admin plane but the data plane continues to serve "
        "via Rust (nginx → :8787). Assertion becomes valid under direct-to-pod "
        "or single-process topologies."
    ),
)
def test_data_plane_runtime_header_under_shadow(flip_runtime_mode, gateway_http_client) -> None:
    """After flipping to ``shadow``, an MCP initialize response names the Python runtime."""
    flip_runtime_mode("shadow")
    runtime = _mcp_initialize_runtime_header(gateway_http_client)
    assert runtime == "python", f"after flipping to shadow, expected the Python runtime on the data plane, " f"got x-contextforge-mcp-runtime={runtime!r}"


# ---------------------------------------------------------------------------
# A2A mode — same contract as MCP mode, different runtime
# ---------------------------------------------------------------------------
def test_a2a_mode_endpoint_has_equivalent_shape(gateway_http_client) -> None:
    """`/admin/runtime/a2a-mode` mirrors the MCP endpoint's contract.

    Field-name drift from MCP: the a2a runtime uses ``invoke_mode`` (the
    per-invocation path) where MCP uses ``mounted`` (the /mcp transport).
    Both name their boot/effective/override fields the same.
    """
    resp = gateway_http_client.get("/admin/runtime/a2a-mode")
    if resp.status_code != 200:
        pytest.skip(f"a2a-mode admin endpoint unavailable ({resp.status_code}): {resp.text[:200]}")
    state = resp.json()
    # ``invoke_mode`` is the a2a analogue of MCP's ``mounted``.
    for key in ("runtime", "boot_mode", "effective_mode", "invoke_mode", "supported_override_modes"):
        assert key in state, f"a2a state payload missing {key!r}: {state}"
    assert state["runtime"] == "a2a"
    assert state["boot_mode"] in {"off", "shadow", "edge", "full"}
    assert state["invoke_mode"] in {"python", "rust"}
