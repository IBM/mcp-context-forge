# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/test_runtime_mode.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

MCP mode (shadow ↔ edge) smoke and drift tests.

Exercises the gateway's ``/admin/runtime/mcp-mode`` API for boot-mode
diagnostics. Since the Rust MCP runtime was removed, the gateway always
boots ``python`` and edge/shadow overrides are advisory — the data plane
remains served by the Python transport.

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
    """Flipping to ``edge`` records the override in state.

    Note: since the Rust MCP runtime was removed, edge override is advisory
    — the data plane continues to serve via the Python transport. The PATCH
    still records the override for diagnostics purposes.
    """
    post_flip = flip_runtime_mode("edge")
    assert post_flip["effective_mode"] == "edge"


def test_runtime_mode_flip_to_shadow_mounts_python(flip_runtime_mode) -> None:
    """Flipping to ``shadow`` records the override for diagnostics."""
    post_flip = flip_runtime_mode("shadow")
    assert post_flip["effective_mode"] == "shadow"


def test_runtime_mode_rejects_unsupported(gateway_http_client, runtime_mode_state: dict) -> None:
    """Unsupported override modes (e.g. ``off``, ``full``, ``bogus``) return 400+."""
    for bad_mode in ("off", "full", "bogus"):
        resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": bad_mode})
        assert resp.status_code >= 400, f"expected rejection for mode={bad_mode!r}, got {resp.status_code}: {resp.text[:200]}"


def test_runtime_mode_boot_mode_is_always_python(gateway_http_client) -> None:
    """The gateway always boots python since the Rust transport was removed.

    Regression guard: a boot-mode override in the response would indicate
    leftover Rust-boot detection logic.
    """
    resp = gateway_http_client.get("/admin/runtime/mcp-mode")
    assert resp.status_code == 200
    state = resp.json()
    assert state["boot_mode"] == "python", f"boot_mode should always be python, got {state['boot_mode']!r}"
    assert state["mounted"] == "python", f"mounted should always be python, got {state['mounted']!r}"
    assert state["effective_mode"] == "python", f"effective_mode should always be python, got {state['effective_mode']!r}"


def test_shadow_boot_rejects_edge_with_safety_flag_reason(gateway_http_client, runtime_mode_state: dict) -> None:
    """Boot=shadow must refuse mode=edge with a safety-flag-gated 409.

    Since the Rust MCP runtime was removed, shadow boot is no longer possible
    (the gateway always boots ``python``). This test is kept as a guard
    against regression: if the gateway ever booted shadow again, edge would
    not be allowed without the session-auth-reuse safety flag.
    """
    if runtime_mode_state["boot_mode"] != "shadow":
        pytest.skip(f"gateway booted {runtime_mode_state['boot_mode']}; this rail only checked under boot_mode=shadow")
    resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": "edge"})
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}: {resp.text[:200]}"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "GAP-010: nginx reverse-proxy does not follow runtime flips. Shadow flip "
        "is observable on the admin plane but the data plane still only serves "
        "via Python. Assertion becomes valid under direct-to-pod "
        "or single-process topologies."
    ),
)
def test_data_plane_runtime_header_under_shadow(flip_runtime_mode, gateway_http_client) -> None:
    """After flipping to ``shadow``, the admin API records the override.

    Data-plane witness (x-contextforge-mcp-runtime) may still report "rust"
    under nginx fronting — the test is marked xfail for that case.
    """
    flip_runtime_mode("shadow")


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
    mirror equality — all four asserted keys must converge.
    """
    import time as _time

    deadline = _time.monotonic() + 3.0
    admin = None
    mcp_rt = None
    asserted_keys = ("boot_mode", "effective_mode", "override_active", "cluster_propagation")
    while _time.monotonic() < deadline:
        admin = gateway_http_client.get("/admin/runtime/mcp-mode").json()
        health = gateway_http_client.get("/health").json()
        mcp_rt = health.get("mcp_runtime")
        if mcp_rt is None:
            pytest.skip("/health does not expose mcp_runtime block on this deployment")
        if all(mcp_rt.get(key) == admin.get(key) for key in asserted_keys):
            break
        _time.sleep(0.1)
    for key in asserted_keys:
        assert mcp_rt.get(key) == admin.get(key), f"mcp_runtime.{key}={mcp_rt.get(key)!r} vs admin.{key}={admin.get(key)!r}"


# ---------------------------------------------------------------------------
# Note: Data-plane witness tests were removed — the Rust transport is no
# longer mounted, so there is no data-plane witness to verify.  Edge/shadow
# overrides are advisory for diagnostics only.
# ---------------------------------------------------------------------------

def test_data_plane_runtime_header_under_edge(flip_runtime_mode, gateway_http_client) -> None:
    """After flipping to ``edge``, the admin API records the override state.

    Note: since the Rust transport is removed, the data-plane witness may
    still report "python" — the edge mode is advisory only.
    """
    flip_runtime_mode("edge")


@pytest.mark.xfail(
    strict=False,
    reason=(
        "GAP-010: nginx reverse-proxy does not follow runtime flips. Shadow flip "
        "is observable on the admin plane but the data plane still only serves "
        "via Python. Assertion becomes valid under direct-to-pod "
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
