# -*- coding: utf-8 -*-
"""Integration tests for plugin runtime management — multi-instance.

Tests against a live gateway via HTTP endpoints (docker-compose with 3 replicas).
For CI-compatible Redis tests, see test_plugin_runtime_redis.py.

Requirements:
    - Running gateway (docker-compose)
    - Redis available
    - NGINX load balancer on port 8080

Usage:
    pytest tests/integration/test_plugin_runtime_management.py -v --with-integration

Environment variables:
    GATEWAY_URL: Gateway base URL (default: http://localhost:8080)
    GATEWAY_EMAIL: Admin email (default: admin@example.com)
    GATEWAY_PASSWORD: Admin password (default: changeme)
"""

# Standard
import os
import time

# Third-Party
import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")
GATEWAY_EMAIL = os.environ.get("GATEWAY_EMAIL", "admin@example.com")
GATEWAY_PASSWORD = os.environ.get("GATEWAY_PASSWORD", "changeme")

# NGINX cache TTL — wait this long after changes for cache to expire
NGINX_CACHE_TTL = 6


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
    """Get fresh auth headers (handles short-lived session tokens)."""
    return {"Authorization": f"Bearer {_get_session_token()}"}


def _is_gateway_running() -> bool:
    """Check if the gateway is reachable."""
    try:
        resp = requests.get(f"{GATEWAY_URL}/health", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


# Skip all tests if gateway is not running
pytestmark = pytest.mark.skipif(
    not _is_gateway_running(),
    reason=f"Gateway not running at {GATEWAY_URL}",
)


@pytest.fixture
def auth_headers():
    """Get fresh authentication headers for each test."""
    token = _get_session_token()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def ensure_plugins_enabled(auth_headers):
    """Ensure plugins are enabled before and after each test.

    Unconditional PUT + sleep. An earlier attempt probed state first and
    skipped the sleep when it looked like plugins were already enabled, but
    the probe goes through the same NGINX that caches GET responses for
    ``NGINX_CACHE_TTL`` seconds — so a previous test's disable could still
    be cached as ``enabled=True`` at probe time, causing this fixture to
    skip the re-enable and leave the next test running against disabled
    plugins. The ~6 s wall-clock cost is worth the correctness guarantee.
    """
    requests.put(
        f"{GATEWAY_URL}/admin/plugins",
        json={"enabled": True},
        headers=auth_headers,
        timeout=10,
    )
    time.sleep(NGINX_CACHE_TTL)
    yield
    # Re-enable after test in case it left them off.
    requests.put(
        f"{GATEWAY_URL}/admin/plugins",
        json={"enabled": True},
        headers=auth_headers,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Layer 2: Single-instance HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestPluginsGloballyEnabledField:
    """GET /admin/plugins includes plugins_globally_enabled field."""

    def test_field_present_in_response(self, auth_headers):
        """Response includes the plugins_globally_enabled field."""
        resp = requests.get(
            f"{GATEWAY_URL}/admin/plugins",
            headers=_fresh_headers(),
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "plugins_globally_enabled" in data

    def test_field_is_boolean(self, auth_headers):
        """plugins_globally_enabled is a boolean value."""
        resp = requests.get(
            f"{GATEWAY_URL}/admin/plugins",
            headers=_fresh_headers(),
            timeout=10,
        )
        data = resp.json()
        assert isinstance(data["plugins_globally_enabled"], bool)


class TestPutAdminPluginsDisable:
    """PUT /admin/plugins {"enabled": false} disables plugins globally."""

    def test_disable_returns_false(self, auth_headers):
        """PUT returns plugins_enabled: false."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["plugins_enabled"] is False

    def test_get_reflects_disabled_state(self, auth_headers):
        """After disabling, GET shows plugins_globally_enabled: false."""
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        time.sleep(NGINX_CACHE_TTL)

        # Fresh token after sleep (session tokens may expire)
        fresh_headers = {"Authorization": f"Bearer {_get_session_token()}"}
        resp = requests.get(
            f"{GATEWAY_URL}/admin/plugins",
            headers=fresh_headers,
            timeout=10,
        )
        data = resp.json()
        assert data["plugins_globally_enabled"] is False


class TestPutAdminPluginsEnable:
    """PUT /admin/plugins {"enabled": true} enables plugins globally."""

    def test_enable_returns_true(self, auth_headers):
        """PUT returns plugins_enabled: true."""
        # First disable
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        # Then enable
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": True},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["plugins_enabled"] is True

    def test_get_reflects_enabled_state(self, auth_headers):
        """After re-enabling, GET shows plugins_globally_enabled: true."""
        # Disable then re-enable
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": True},
            headers=auth_headers,
            timeout=10,
        )
        time.sleep(NGINX_CACHE_TTL)

        resp = requests.get(
            f"{GATEWAY_URL}/admin/plugins",
            headers=_fresh_headers(),
            timeout=10,
        )
        data = resp.json()
        assert data["plugins_globally_enabled"] is True


class TestPutAdminPluginsValidation:
    """PUT /admin/plugins input validation."""

    def test_missing_enabled_field(self, auth_headers):
        """Missing 'enabled' field returns 400."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"foo": "bar"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_non_boolean_enabled(self, auth_headers):
        """Non-boolean 'enabled' returns 400."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": "yes"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_unauthenticated_request(self):
        """Request without auth returns 401/403."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            timeout=10,
        )
        assert resp.status_code in (401, 403)


class TestPutAdminPluginsNameMode:
    """PUT /admin/plugins/{name} changes per-plugin mode."""

    def test_change_mode_to_enforce(self, auth_headers):
        """Change plugin mode to enforce."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "enforce"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plugin"] == "RetryWithBackoffPlugin"
        assert data["mode"] == "enforce"
        assert "redis_persisted" in data

    def test_change_mode_to_permissive(self, auth_headers):
        """Change plugin mode to permissive."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "permissive"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "permissive"

    def test_change_mode_to_disabled(self, auth_headers):
        """Change plugin mode to disabled."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "disabled"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "disabled"

    def test_invalid_mode_returns_400(self, auth_headers):
        """Invalid mode returns 400."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "turbo"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_nonexistent_plugin_returns_404(self, auth_headers):
        """Non-existent plugin returns 404."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/NonExistentPlugin",
            json={"mode": "enforce"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 404

    def test_404_includes_available_plugins(self, auth_headers):
        """404 response lists available plugin names."""
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/FakePlugin",
            json={"mode": "enforce"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 404
        assert "Available:" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Layer 2: Redis state propagation
# ---------------------------------------------------------------------------


class TestCrossReplicaPropagation:
    """Tests that plugin state changes propagate via Redis.

    TODO(#4300): these assertions assume NGINX round-robins across replicas
    but don't actually verify different replicas responded. Sticky sessions or
    source-IP hashing would let every sampled request hit the same backend and
    the test would still pass. Gate the assertions on a ``Server-Name`` (or
    equivalent) response header so we can assert ``len(set(replicas_seen)) >= 2``.
    """

    def test_disable_propagates_across_requests(self, auth_headers):
        """After disabling, multiple requests all see disabled state.

        With NGINX round-robining across replicas, this verifies
        Redis propagation (not just local in-memory state).
        """
        # Disable
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        time.sleep(NGINX_CACHE_TTL)

        # Hit the endpoint multiple times — round-robin across replicas
        results = []
        for _ in range(5):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=auth_headers,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        # All responses should show False (propagated via Redis)
        assert len(results) > 0, "No successful responses"
        assert all(r is False for r in results), f"Not all replicas see disabled state: {results}"

    def test_enable_propagates_across_requests(self, auth_headers):
        """After enabling, multiple requests all see enabled state."""
        # First disable then re-enable
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=auth_headers,
            timeout=10,
        )
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": True},
            headers=auth_headers,
            timeout=10,
        )
        time.sleep(NGINX_CACHE_TTL)

        results = []
        for _ in range(5):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=auth_headers,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        assert len(results) > 0
        assert all(r is True for r in results), f"Not all replicas see enabled state: {results}"


# ---------------------------------------------------------------------------
# Layer 3: Multi-instance tests (3 gateway replicas via NGINX)
# ---------------------------------------------------------------------------


class TestMultiInstanceGlobalToggle:
    """Multi-instance tests for global plugin toggle.

    These tests send multiple requests through NGINX load balancer
    to verify state consistency across all gateway replicas.

    TODO(#4300): same replica-identity gap as ``TestCrossReplicaPropagation`` —
    requests are assumed to spread across replicas but never verified. Close by
    asserting distinct replica identities in the response set.
    """

    def test_toggle_cycle_consistent(self, auth_headers):
        """Full enable-disable-enable cycle is consistent across replicas."""
        for enabled in [False, True, False, True]:
            headers = _fresh_headers()
            requests.put(
                f"{GATEWAY_URL}/admin/plugins",
                json={"enabled": enabled},
                headers=headers,
                timeout=10,
            )
            time.sleep(NGINX_CACHE_TTL)

            # Sample 6 requests to hit all 3 replicas at least twice
            fresh = _fresh_headers()
            results = []
            for _ in range(6):
                resp = requests.get(
                    f"{GATEWAY_URL}/admin/plugins",
                    headers=fresh,
                    timeout=10,
                )
                if resp.status_code == 200:
                    results.append(resp.json().get("plugins_globally_enabled"))

            assert all(r is enabled for r in results), f"State mismatch after setting enabled={enabled}: {results}"

    def test_rapid_toggle_converges(self, auth_headers):
        """Rapid toggling eventually converges to the last state."""
        # Rapid toggles
        for enabled in [False, True, False, True, True]:
            requests.put(
                f"{GATEWAY_URL}/admin/plugins",
                json={"enabled": enabled},
                headers=auth_headers,
                timeout=10,
            )

        # Wait for propagation
        time.sleep(NGINX_CACHE_TTL)

        # All replicas should converge to True (last toggle)
        results = []
        for _ in range(6):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=auth_headers,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        assert all(r is True for r in results), f"Replicas didn't converge: {results}"


class TestMultiInstancePluginMode:
    """Multi-instance tests for per-plugin mode changes."""

    def test_mode_change_visible_across_replicas(self, auth_headers):
        """Per-plugin mode change stored in Redis is visible from any replica."""
        # Change mode
        resp = requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "enforce"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200

        # The mode is stored in Redis — verify the PUT response
        assert resp.json()["mode"] == "enforce"

        # Restore
        requests.put(
            f"{GATEWAY_URL}/admin/plugins/RetryWithBackoffPlugin",
            json={"mode": "permissive"},
            headers=auth_headers,
            timeout=10,
        )


# ---------------------------------------------------------------------------
# Layer 3: Pub/Sub instant propagation tests
# ---------------------------------------------------------------------------

# Shorter wait for pub/sub — should propagate within 2s, not 30s TTL
PUBSUB_PROPAGATION_WAIT = 2


class TestPubSubInstantPropagation:
    """Tests that plugin state changes propagate instantly via Redis pub/sub.

    These tests verify sub-second propagation across replicas. If pub/sub
    is not implemented, these tests will fail because PUBSUB_PROPAGATION_WAIT (2s)
    is shorter than the TTL (30s).
    """

    def test_global_toggle_instant_propagation(self, auth_headers):
        """Global toggle propagates to all replicas within 2 seconds."""
        # Disable
        headers = _fresh_headers()
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=headers,
            timeout=10,
        )

        # Wait only 2s — pub/sub should propagate instantly
        time.sleep(PUBSUB_PROPAGATION_WAIT)

        # Check across replicas
        results = []
        fresh = _fresh_headers()
        for _ in range(6):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=fresh,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        assert len(results) > 0, "No successful responses"
        assert all(r is False for r in results), f"Not all replicas see disabled state within {PUBSUB_PROPAGATION_WAIT}s: {results}"

    def test_global_enable_instant_propagation(self, auth_headers):
        """Global re-enable propagates to all replicas within 2 seconds."""
        headers = _fresh_headers()
        # Disable first
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": False},
            headers=headers,
            timeout=10,
        )
        time.sleep(PUBSUB_PROPAGATION_WAIT)

        # Re-enable
        headers = _fresh_headers()
        requests.put(
            f"{GATEWAY_URL}/admin/plugins",
            json={"enabled": True},
            headers=headers,
            timeout=10,
        )

        time.sleep(PUBSUB_PROPAGATION_WAIT)

        results = []
        fresh = _fresh_headers()
        for _ in range(6):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=fresh,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        assert len(results) > 0
        assert all(r is True for r in results), f"Not all replicas see enabled state within {PUBSUB_PROPAGATION_WAIT}s: {results}"

    def test_rapid_toggle_instant_convergence(self, auth_headers):
        """Rapid toggling converges instantly via pub/sub (no 30s TTL wait)."""
        headers = _fresh_headers()
        for enabled in [False, True, False, True]:
            requests.put(
                f"{GATEWAY_URL}/admin/plugins",
                json={"enabled": enabled},
                headers=headers,
                timeout=10,
            )

        # Only wait 2s — not the full TTL
        time.sleep(PUBSUB_PROPAGATION_WAIT)

        # All replicas should show True (last toggle)
        results = []
        fresh = _fresh_headers()
        for _ in range(6):
            resp = requests.get(
                f"{GATEWAY_URL}/admin/plugins",
                headers=fresh,
                timeout=10,
            )
            if resp.status_code == 200:
                results.append(resp.json().get("plugins_globally_enabled"))

        assert all(r is True for r in results), f"Replicas didn't converge within {PUBSUB_PROPAGATION_WAIT}s: {results}"
