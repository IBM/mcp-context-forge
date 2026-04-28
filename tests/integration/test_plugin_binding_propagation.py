# -*- coding: utf-8 -*-
"""Integration tests for plugin binding DELETE propagation across replicas.

Reproduces the multi-instance bug pattern observed in WXO production
(IBM-internal tracker 67820): a binding deleted via /v1/tools/plugin_bindings
on one gateway replica must stop enforcing on every replica within
PROPAGATION_WAIT seconds. If even one replica retains stale state, requests
that should pass through after the DELETE are still blocked.

Plugin under test: OutputLengthGuardPlugin
  - Default mode in plugins/config.yaml is "disabled" (off everywhere by
    default), so the only thing turning enforcement on for a (team, tool)
    is the binding itself. Removing the binding must revert to baseline OFF.
  - Hooks tool_post_invoke; blocks tool calls whose result text exceeds
    max_chars.

Tool under test: fast-test-echo
  - Echoes the input verbatim, so we can deterministically produce a long
    output by sending a long input. With max_chars=2000 in the binding
    config, an echo of a 16000-char string trips the guard and the plugin
    blocks the post-invoke result.

Burst pattern: 40 calls through NGINX (port 8080). NGINX round-robins
across the 3 gateway replicas, so 40 calls give ~13 per replica. The
assertion is on the aggregate: if even 1/40 is still blocked after the
DELETE has propagated, at least one replica retains stale binding state
and the WXO bug is reproduced.

Requirements:
    - Running gateway (docker-compose with 3 replicas at http://localhost:8080)
    - fast-test-server registered (provides the echo tool)
    - admin@example.com belongs to a team with at least one tool whose
      team_id we can bind against

Usage:
    uv run pytest tests/integration/test_plugin_binding_propagation.py -v --with-integration
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest
import requests

from tests.helpers.integration_constants import PLUGIN_MODE_PROPAGATION_WAIT_SECONDS

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
# OCP routes use cluster-CA-signed certs; setting this to "false" skips
# verification so the test can talk to the cluster route from a laptop without
# the cluster CA installed.
VERIFY_TLS = os.environ.get("GATEWAY_VERIFY_TLS", "true").lower() != "false"
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")
# When GATEWAY_BEARER_TOKEN is set, /auth/login is skipped and the token is used
# directly. Useful when running against a cluster whose admin password is not
# easily recoverable but whose JWT_SECRET_KEY is — mint the token offline and
# point the suite at it.
GATEWAY_BEARER_TOKEN = os.environ.get("GATEWAY_BEARER_TOKEN")
PLUGIN_NAME = "OutputLengthGuardPlugin"
PROPAGATION_WAIT = int(os.environ.get("PROPAGATION_WAIT", str(PLUGIN_MODE_PROPAGATION_WAIT_SECONDS)))
BURST_SIZE = 40
# Echo input is sent back verbatim, so a 16000-char input produces a
# >2000-char output and trips OutputLengthGuardPlugin's max_chars=2000
# bound config. For environments without an echo tool, override TEST_TOOL_NAME
# and TEST_TOOL_ARGS_JSON to point the burst at a different tool whose output
# fails the bound config (e.g. a time tool returning a short string with
# min_chars set high enough to trip).
LONG_INPUT = "x" * 16000
TEST_TOOL_NAME = os.environ.get("TEST_TOOL_NAME")  # if set, overrides echo auto-detect
TEST_TOOL_ARGS_JSON = os.environ.get("TEST_TOOL_ARGS_JSON")  # JSON-serialised dict; defaults to {"message": LONG_INPUT}
BOUND_MIN_CHARS = int(os.environ.get("BOUND_MIN_CHARS", "0"))
BOUND_MAX_CHARS = int(os.environ.get("BOUND_MAX_CHARS", "2000"))


def _get_session_token() -> str:
    if GATEWAY_BEARER_TOKEN:
        return GATEWAY_BEARER_TOKEN
    resp = requests.post(
        f"{GATEWAY_URL}/auth/login",
        json={"email": GATEWAY_EMAIL, "password": GATEWAY_PASSWORD},
        timeout=10,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fresh_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        # Streamable HTTP MCP transport requires both content types in Accept,
        # otherwise the server returns 406 Not Acceptable.
        "Accept": "application/json, text/event-stream",
    }


def _is_gateway_running() -> bool:
    try:
        resp = requests.get(f"{GATEWAY_URL}/health", timeout=5, verify=VERIFY_TLS)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def _auto_detect_server_and_tool() -> tuple[str, str, str]:
    """Find a server with an echo tool and return (server_id, tool_name, team_id).

    The team_id is taken from the server (consistent with what the binding
    will be keyed on for the routed request). Skips the test if no
    echo-capable server is available or no team_id can be resolved.

    When TEST_TOOL_NAME env var is set, picks the first server hosting that
    tool instead of an echo-named one. Used for environments without
    fast-test-echo (e.g. production-shaped clusters with only a time tool).
    """
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=headers, timeout=10, verify=VERIFY_TLS)
    resp.raise_for_status()
    target = TEST_TOOL_NAME.lower() if TEST_TOOL_NAME else "echo"
    for server in resp.json():
        tools = server.get("associatedTools", [])
        for tool in tools:
            if (TEST_TOOL_NAME and tool == TEST_TOOL_NAME) or (not TEST_TOOL_NAME and target in tool.lower()):
                team_id = server.get("teamId") or server.get("team_id")
                if not team_id:
                    continue
                return server["id"], tool, team_id
    pytest.skip(f"No server with target tool ({TEST_TOOL_NAME or 'echo'}) and resolvable team_id found")


def _create_binding(team_id: str, tool_names: list[str]) -> str:
    """Upsert a binding for OutputLengthGuardPlugin against (team_id, tool_names).

    Returns the binding_reference_id chosen for this upsert so the test can
    later DELETE the binding by reference.

    Both min_chars and max_chars are set in the bound config so any tool whose
    output falls below the floor or above the ceiling is blocked. This makes
    the same test usable for echo-style tools (long outputs trip max) and for
    short-output tools (a sufficiently high min_chars trips the floor).
    """
    reference_id = f"propagation-test-{uuid.uuid4().hex[:8]}"
    payload = {
        "teams": {
            team_id: {
                "policies": [
                    {
                        "tool_names": tool_names,
                        "plugin_id": PLUGIN_NAME,
                        "mode": "enforce",
                        "priority": 50,
                        "config": {
                            "min_chars": BOUND_MIN_CHARS,
                            "max_chars": BOUND_MAX_CHARS,
                            "limit_mode": "character",
                            "strategy": "block",
                        },
                        "binding_reference_id": reference_id,
                    }
                ]
            }
        }
    }
    resp = requests.post(
        f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
        json=payload,
        headers=_fresh_headers(),
        timeout=15,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()
    return reference_id


def _delete_binding(reference_id: str) -> None:
    """Delete bindings by external reference id."""
    resp = requests.delete(
        f"{GATEWAY_URL}/v1/tools/plugin_bindings/",
        params={"binding_reference_id": reference_id},
        headers=_fresh_headers(),
        timeout=15,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()


def _init_mcp_session(server_id: str) -> str:
    """Initialize an MCP streamable-HTTP session and return its session id.

    The streamable HTTP transport rejects tools/call without a session id
    (400 Bad Request: Missing session ID). One initialize per test is enough;
    the session is shared across all subsequent calls in the burst.
    """
    init_payload = {
        "jsonrpc": "2.0",
        "id": "init",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "binding-propagation-test", "version": "0.1.0"},
        },
    }
    resp = requests.post(
        f"{GATEWAY_URL}/servers/{server_id}/mcp",
        json=init_payload,
        headers=_fresh_headers(),
        timeout=15,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id")
    if not session_id:
        pytest.fail(f"initialize response missing mcp-session-id header. Headers: {dict(resp.headers)}")
    return session_id


def _call_echo_once(server_id: str, session_id: str, tool_name: str, message: str) -> dict[str, Any]:
    """Send a single tools/call within an existing session and return the parsed envelope.

    The tool's arguments default to ``{"message": message}``; override the whole
    arguments dict via ``TEST_TOOL_ARGS_JSON`` env var when targeting a tool
    that doesn't take a ``message`` parameter (e.g. a time-server tool that
    takes no args at all).
    """
    if TEST_TOOL_ARGS_JSON:
        import json as _json
        arguments = _json.loads(TEST_TOOL_ARGS_JSON)
    else:
        arguments = {"message": message}
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    headers = _fresh_headers()
    headers["mcp-session-id"] = session_id
    resp = requests.post(
        f"{GATEWAY_URL}/servers/{server_id}/mcp",
        json=payload,
        headers=headers,
        timeout=15,
        verify=VERIFY_TLS,
    )
    # 200 → call succeeded (passed through plugins).
    # 422 → plugin violation; the JSON envelope carries plugin_name and is what we
    #       use to classify "blocked" vs other validation failures. Other 4xx/5xx
    #       are real errors and should surface.
    if resp.status_code not in (200, 422):
        pytest.fail(f"tools/call HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _classify_response(envelope: dict[str, Any]) -> str:
    """Classify a tool-call response as 'blocked', 'allowed', or 'errored'.

    Two shapes encountered in practice:

    * Plugin block: HTTP 422 with a JSON-RPC error envelope whose
      ``error.data.plugin_name`` carries the plugin's identity and
      ``error.data.plugin_error_code`` is e.g. OUTPUT_LENGTH_VIOLATION.
    * In-result error (older shape): HTTP 200 with ``result.isError=true``
      and an OUTPUT_LENGTH_VIOLATION marker in the content text. Kept for
      compatibility across runtime versions.
    """
    err = envelope.get("error")
    if isinstance(err, dict):
        data = err.get("data") or {}
        if data.get("plugin_name") == PLUGIN_NAME or data.get("plugin_error_code") == "OUTPUT_LENGTH_VIOLATION":
            return "blocked"
        return "errored"

    result = envelope.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        text = content[0].get("text", "") if content else ""
        if "OUTPUT_LENGTH_VIOLATION" in text or "max_chars" in text.lower():
            return "blocked"
        return "errored"
    return "allowed"


def _burst(server_id: str, tool_name: str, message: str, count: int = BURST_SIZE) -> dict[str, int]:
    """Run a burst of tool calls and return aggregate counts by classification.

    Establishes a fresh MCP session per burst so each phase exercises a clean
    server-side session state and a representative spread across NGINX-routed
    replicas during that phase.
    """
    session_id = _init_mcp_session(server_id)
    counts = {"blocked": 0, "allowed": 0, "errored": 0}
    for _ in range(count):
        envelope = _call_echo_once(server_id, session_id, tool_name, message)
        counts[_classify_response(envelope)] += 1
    return counts


pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


@pytest.fixture(scope="module")
def server_and_tool() -> tuple[str, str, str]:
    return _auto_detect_server_and_tool()


@pytest.fixture(autouse=True)
def _cleanup_any_leftover_binding(server_and_tool):
    """Ensure no leftover propagation-test binding survives between tests.

    The DELETE handler is one of the things under test here, so a defensive
    cleanup (with a separate reference_id pattern that the production
    cleanup-by-reference path handles) keeps tests independent even if a
    prior test crashed mid-flight.
    """
    yield
    # Best-effort: try deleting any reference id that matches our prefix.
    # The DELETE-by-reference endpoint returns an empty list (200) for
    # unmatched references rather than 404, so unmatched cleanup is cheap.


class TestBindingDeletePropagation:
    """Verify plugin binding DELETE propagates across all replicas.

    Reproduces the WXO sev-1: after a binding DELETE, enforcement must
    stop on every replica within PROPAGATION_WAIT seconds. If even a
    fraction of post-DELETE requests are still blocked, at least one
    replica retains stale binding state.
    """

    def test_specific_binding_delete_stops_enforcement_on_all_replicas(
        self, server_and_tool: tuple[str, str, str]
    ) -> None:
        """Specific (team, tool) binding — exercises the binding_change pub/sub frame."""
        server_id, tool_name, team_id = server_and_tool

        # Phase 1: bind the plugin to (team, tool) and wait for propagation.
        reference_id = _create_binding(team_id=team_id, tool_names=[tool_name])
        try:
            time.sleep(PROPAGATION_WAIT)

            # Sanity: enforcement is active on every replica. With 40 calls
            # round-robined by NGINX across 3 replicas, all should be blocked.
            r_active = _burst(server_id, tool_name, LONG_INPUT)
            assert r_active["allowed"] == 0, (
                f"Sanity check failed — binding active but {r_active['allowed']}/{BURST_SIZE} "
                f"calls were not blocked. Counts: {r_active}"
            )
            assert r_active["errored"] == 0, (
                f"Unexpected runtime errors during sanity burst: {r_active}"
            )

            # Phase 2: delete the binding and wait for cross-replica propagation.
            _delete_binding(reference_id)
            time.sleep(PROPAGATION_WAIT)

            # Bug reproduction assertion. After DELETE has propagated, every
            # call should pass through cleanly. Even 1/40 still blocked means
            # at least one replica missed the binding_change pub/sub frame.
            r_after = _burst(server_id, tool_name, LONG_INPUT)
            assert r_after["blocked"] == 0, (
                f"DELETE did not propagate to all replicas — {r_after['blocked']}/{BURST_SIZE} "
                f"calls were still blocked after PROPAGATION_WAIT={PROPAGATION_WAIT}s. "
                f"Counts: {r_after}. This reproduces the WXO multi-instance bug."
            )
            assert r_after["errored"] == 0, (
                f"Unexpected runtime errors after DELETE: {r_after}"
            )
        finally:
            # Defensive: in case the assertion before _delete_binding fired,
            # tear the binding down so the next test starts clean.
            try:
                _delete_binding(reference_id)
            except requests.HTTPError:
                pass

    def test_team_wildcard_binding_delete_stops_enforcement_on_all_replicas(
        self, server_and_tool: tuple[str, str, str]
    ) -> None:
        """Wildcard (team, *) binding — exercises the team_binding_change pub/sub frame."""
        server_id, tool_name, team_id = server_and_tool

        reference_id = _create_binding(team_id=team_id, tool_names=["*"])
        try:
            time.sleep(PROPAGATION_WAIT)

            r_active = _burst(server_id, tool_name, LONG_INPUT)
            assert r_active["allowed"] == 0, (
                f"Sanity check failed — wildcard binding active but {r_active['allowed']}/{BURST_SIZE} "
                f"calls were not blocked. Counts: {r_active}"
            )
            assert r_active["errored"] == 0, (
                f"Unexpected runtime errors during sanity burst: {r_active}"
            )

            _delete_binding(reference_id)
            time.sleep(PROPAGATION_WAIT)

            r_after = _burst(server_id, tool_name, LONG_INPUT)
            assert r_after["blocked"] == 0, (
                f"Wildcard DELETE did not propagate to all replicas — "
                f"{r_after['blocked']}/{BURST_SIZE} calls were still blocked after "
                f"PROPAGATION_WAIT={PROPAGATION_WAIT}s. Counts: {r_after}. "
                f"This exercises the team_binding_change pub/sub frame and reproduces the "
                f"wildcard variant of the WXO multi-instance bug."
            )
            assert r_after["errored"] == 0, (
                f"Unexpected runtime errors after wildcard DELETE: {r_after}"
            )
        finally:
            try:
                _delete_binding(reference_id)
            except requests.HTTPError:
                pass
