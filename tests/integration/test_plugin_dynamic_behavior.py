# -*- coding: utf-8 -*-
"""Integration tests for dynamic plugin configuration — behavioral verification.

Verifies that runtime plugin mode changes via the admin API actually affect
plugin behavior on tool calls, not just the reported admin state.

Uses the ReplaceBadWordsPlugin (SearchReplacePlugin) with the fast-test-echo
tool: the plugin replaces "crap" → "crud" → "yikes" in tool arguments and
responses. When disabled, the echo returns the original text unchanged.

Requirements:
    - Running gateway (docker-compose with 3 replicas)
    - NGINX load balancer on port 8080
    - fast-test-server registered (provides echo tool)

Usage:
    uv run pytest tests/integration/test_plugin_dynamic_behavior.py -v --with-integration
"""

# Standard
import os
import time
import uuid

# Third-Party
import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

# NGINX caches GET responses for ~6s. After an admin PUT, wait this long
# before verifying behavior so all replicas serve the new state.
PROPAGATION_WAIT = 7

# The plugin we toggle and the word it transforms
PLUGIN_NAME = "ReplaceBadWordsPlugin"
# plugins/config.yaml: crap → crud, crud → yikes. Both rules apply sequentially,
# so "crap" becomes "yikes" when the plugin is enforcing.
TRIGGER_WORD = "crap"
EXPECTED_WHEN_ENFORCING = "yikes"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_session_token() -> str:
    """Login and return a session token."""
    resp = requests.post(
        f"{GATEWAY_URL}/auth/login",
        json={"email": GATEWAY_EMAIL, "password": GATEWAY_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fresh_headers() -> dict:
    """Get fresh auth headers."""
    return {
        "Authorization": f"Bearer {_get_session_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_gateway_running() -> bool:
    """Check if the gateway is reachable."""
    try:
        resp = requests.get(f"{GATEWAY_URL}/health", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def _auto_detect_echo_server() -> str:
    """Find the server ID that has the echo tool."""
    headers = _fresh_headers()
    resp = requests.get(f"{GATEWAY_URL}/servers", headers=headers, timeout=10)
    resp.raise_for_status()
    for server in resp.json():
        tools = server.get("associatedTools", [])
        if any("echo" in t.lower() for t in tools):
            return server["id"]
    pytest.skip("No server with echo tool found")


def _set_plugin_mode(mode: str) -> None:
    """Set plugin mode via admin API and wait for propagation."""
    headers = _fresh_headers()
    resp = requests.put(
        f"{GATEWAY_URL}/admin/plugins/{PLUGIN_NAME}",
        json={"mode": mode},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    time.sleep(PROPAGATION_WAIT)


def _call_echo(server_id: str, message: str) -> str:
    """Send a tools/call to the echo tool and return the response text."""
    headers = _fresh_headers()
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": "fast-test-echo",
            "arguments": {"message": message},
        },
    }
    resp = requests.post(
        f"{GATEWAY_URL}/servers/{server_id}/mcp",
        json=payload,
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", {})
    if result.get("isError"):
        content = result.get("content", [])
        text = content[0].get("text", "") if content else ""
        pytest.fail(f"Tool call returned error: {text}")
    content = result.get("content", [])
    return content[0].get("text", "") if content else ""


# ---------------------------------------------------------------------------
# Skip if gateway not running
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server_id():
    """Auto-detect the echo server ID once for the module."""
    return _auto_detect_echo_server()


@pytest.fixture(autouse=True)
def ensure_plugin_enforcing():
    """Restore plugin to enforce mode before and after each test."""
    _set_plugin_mode("enforce")
    yield
    _set_plugin_mode("enforce")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPluginEnforcingBehavior:
    """Verify the plugin actually transforms tool responses when enforcing."""

    def test_echo_with_trigger_word_is_transformed(self, server_id):
        """When plugin is enforcing, the trigger word is replaced in the response."""
        response_text = _call_echo(server_id, f"this is {TRIGGER_WORD} data")
        assert TRIGGER_WORD not in response_text, (
            f"Expected '{TRIGGER_WORD}' to be replaced, but got: {response_text}"
        )
        assert EXPECTED_WHEN_ENFORCING in response_text, (
            f"Expected '{EXPECTED_WHEN_ENFORCING}' in response, but got: {response_text}"
        )

    def test_echo_without_trigger_word_unchanged(self, server_id):
        """Normal text without the trigger word passes through unchanged."""
        response_text = _call_echo(server_id, "this is clean data")
        assert response_text == "this is clean data"


class TestPluginDisabledBehavior:
    """Verify the plugin stops transforming when disabled at runtime."""

    def test_disable_stops_transformation(self, server_id):
        """After disabling the plugin, the trigger word passes through unchanged."""
        # First verify it's enforcing
        text = _call_echo(server_id, f"test {TRIGGER_WORD}")
        assert TRIGGER_WORD not in text, f"Plugin should be enforcing but got: {text}"

        # Disable
        _set_plugin_mode("disabled")

        # Now the trigger word should pass through unchanged
        text = _call_echo(server_id, f"test {TRIGGER_WORD}")
        assert TRIGGER_WORD in text, (
            f"Plugin should be disabled but '{TRIGGER_WORD}' was still replaced: {text}"
        )

    def test_reenable_restores_transformation(self, server_id):
        """After re-enabling, the plugin transforms again."""
        # Disable
        _set_plugin_mode("disabled")
        text = _call_echo(server_id, f"test {TRIGGER_WORD}")
        assert TRIGGER_WORD in text, "Plugin should be disabled"

        # Re-enable
        _set_plugin_mode("enforce")
        text = _call_echo(server_id, f"test {TRIGGER_WORD}")
        assert TRIGGER_WORD not in text, (
            f"Plugin should be enforcing again but '{TRIGGER_WORD}' was not replaced: {text}"
        )
        assert EXPECTED_WHEN_ENFORCING in text


class TestCrossReplicaBehavior:
    """Verify all replicas reflect the mode change in actual behavior."""

    def test_all_replicas_enforce_after_enable(self, server_id):
        """After enabling, multiple requests (hitting all replicas) show transformation."""
        _set_plugin_mode("enforce")
        # Hit all 3 replicas at least twice via round-robin
        results = []
        for _ in range(6):
            text = _call_echo(server_id, f"check {TRIGGER_WORD}")
            results.append(TRIGGER_WORD not in text)
        assert all(results), (
            f"Expected all replicas to enforce, but got mixed results: {results}"
        )

    def test_all_replicas_stop_after_disable(self, server_id):
        """After disabling, multiple requests (hitting all replicas) show no transformation."""
        _set_plugin_mode("disabled")
        # Hit all 3 replicas at least twice
        results = []
        for _ in range(6):
            text = _call_echo(server_id, f"check {TRIGGER_WORD}")
            results.append(TRIGGER_WORD in text)
        assert all(results), (
            f"Expected all replicas to be disabled, but some still transformed: {results}"
        )


class TestModeToggleCycle:
    """Verify a full enable → disable → enable cycle works correctly."""

    def test_full_toggle_cycle(self, server_id):
        """Plugin behavior changes correctly across a full toggle cycle."""
        # Step 1: Enforce
        _set_plugin_mode("enforce")
        text = _call_echo(server_id, f"cycle {TRIGGER_WORD}")
        assert EXPECTED_WHEN_ENFORCING in text, f"Step 1 (enforce): got {text}"

        # Step 2: Disable
        _set_plugin_mode("disabled")
        text = _call_echo(server_id, f"cycle {TRIGGER_WORD}")
        assert TRIGGER_WORD in text, f"Step 2 (disabled): got {text}"

        # Step 3: Re-enable
        _set_plugin_mode("enforce")
        text = _call_echo(server_id, f"cycle {TRIGGER_WORD}")
        assert EXPECTED_WHEN_ENFORCING in text, f"Step 3 (re-enforce): got {text}"
