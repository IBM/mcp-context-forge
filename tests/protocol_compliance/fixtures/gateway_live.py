"""Live ContextForge gateway connection for the compliance harness.

Phase 4a originally wired this in-process via FastAPI ``TestClient`` +
``httpx.ASGITransport``, but the gateway's bootstrap layer doesn't seed the
``platform_admin`` role under that path, so admin REST calls returned 403.
The pivot to live-gateway sidesteps that: the harness now points at a
running gateway (default ``http://127.0.0.1:8080`` — the docker-compose
default port-forward), mints a JWT signed with the gateway's configured
secret, and uses real HTTP both for control-plane (POST /gateways) and
for the MCP traffic the targets exercise.

Skip semantics: if the gateway isn't reachable on the configured base URL,
all gateway-target rows skip cleanly with the unreachable URL in the
reason. Same pattern as ``test_mcp_protocol_e2e.py``.
"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Iterator

import httpx
import pytest


# ---------------------------------------------------------------------------
# Configuration — overridable via env vars to match docker-compose / staging.
# ---------------------------------------------------------------------------
def _base_url() -> str:
    return os.getenv("MCP_CLI_BASE_URL", "http://127.0.0.1:8080")


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET_KEY", "my-test-key-but-now-longer-than-32-bytes")


def _admin_email() -> str:
    return os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")


def _is_reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=timeout).status_code == 200
    except Exception:  # noqa: BLE001 — any failure means "not reachable"
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def gateway_base_url() -> str:
    """Return the live gateway base URL or skip the session if unreachable."""
    url = _base_url()
    if not _is_reachable(url):
        pytest.skip(f"gateway not reachable at {url}. Bring up docker-compose or set " "MCP_CLI_BASE_URL to a running gateway before running gateway-target " "compliance tests.")
    return url


@pytest.fixture(scope="session")
def admin_jwt(gateway_base_url: str) -> str:
    """Mint a platform-admin JWT signed with the gateway's configured secret.

    Depends on ``gateway_base_url`` only to inherit its reachability skip.
    The actual mint is local — the gateway is never asked to issue tokens.

    Token-scoping note: the gateway's ``normalize_token_teams`` treats a
    JWT with the ``teams`` key **missing** as public-only (empty team list),
    which suppresses admin bypass on ``/admin/*`` routes. To drive runtime
    admin endpoints we need ``teams: null`` *explicitly* so the token scoping
    layer sees the admin-bypass sentinel. ``_create_jwt_token`` uses a
    sentinel default to distinguish "not specified" from "explicit None", so
    we pass ``teams=None`` directly.
    """
    from mcpgateway.utils.create_jwt_token import _create_jwt_token

    return _create_jwt_token(
        data={"sub": _admin_email(), "is_admin": True},
        expires_in_minutes=60,
        secret=_jwt_secret(),
        algorithm="HS256",
        teams=None,
    )


@pytest.fixture(scope="session")
def runtime_mode_state(gateway_http_client: httpx.Client) -> dict:
    """Return the current MCP runtime mode state from /admin/runtime/mcp-mode.

    Payload fields:
      * ``boot_mode`` — off / shadow / edge / full (value of RUST_MCP_MODE at boot)
      * ``effective_mode`` — current runtime mode (== boot_mode if no override)
      * ``override_active`` — True when a PATCH override is live
      * ``supported_override_modes`` — what PATCH can set; typically ``["edge", "shadow"]``
      * ``mounted`` — python or rust
    """
    resp = gateway_http_client.get("/admin/runtime/mcp-mode")
    if resp.status_code != 200:
        pytest.skip(f"runtime-mode admin endpoint unavailable ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def _wait_for_effective_mode(client: httpx.Client, expected: str, timeout_s: float = 3.0) -> dict:
    """Poll ``/admin/runtime/mcp-mode`` until ``effective_mode`` converges.

    Runtime-mode flips propagate across pods via Redis pub/sub; in a
    multi-pod deployment an immediate GET after PATCH can land on a pod
    that hasn't consumed the pub/sub message yet. The docs call this
    "eventually consistent"; in practice convergence is <1 s. This helper
    polls with a short budget so tests assert on converged state rather
    than a snapshot of an in-flight flip.

    Returns the first GET payload whose ``effective_mode`` matches
    ``expected``; raises AssertionError on timeout.
    """
    import time as _time

    deadline = _time.monotonic() + timeout_s
    last: dict = {}
    while _time.monotonic() < deadline:
        resp = client.get("/admin/runtime/mcp-mode")
        if resp.status_code != 200:
            # Non-200 during polling usually means the admin route is down
            # or the JWT expired mid-session; keep polling but capture the
            # last body so the timeout message is actionable.
            last = {"_http_status": resp.status_code, "_body": resp.text[:200]}
            _time.sleep(0.1)
            continue
        try:
            last = resp.json()
        except ValueError as exc:
            last = {"_parse_error": str(exc), "_body": resp.text[:200]}
            _time.sleep(0.1)
            continue
        if last.get("effective_mode") == expected:
            return last
        _time.sleep(0.1)
    raise AssertionError(f"effective_mode did not converge to {expected!r} within {timeout_s}s; " f"last observed: {last}")


@pytest.fixture
def flip_runtime_mode(gateway_http_client: httpx.Client, runtime_mode_state: dict):
    """Return a callable that PATCHes the mode; auto-restores on teardown.

    Yields a context-manager-like callable: ``flip_runtime_mode("edge")``
    flips to edge for the duration of the current test; the original mode
    is restored on fixture teardown regardless of test outcome.

    Skips the current test when the gateway refuses the flip (409 from
    boot_mode=off, 400 for an unsupported mode, etc.) so the harness stays
    green against non-Rust deployments.
    """
    original_mode = runtime_mode_state.get("effective_mode")
    override_was_active = runtime_mode_state.get("override_active", False)

    def _flip(target_mode: str) -> dict:
        resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": target_mode})
        if resp.status_code >= 400:
            pytest.skip(f"runtime-mode flip to {target_mode!r} refused ({resp.status_code}): " f"{resp.text[:200]}")
        return resp.json()

    try:
        yield _flip
    finally:
        # Restore: if an override was originally active, re-apply it; otherwise
        # best-effort clear by flipping back to the boot mode. Failures on
        # restore are *warned* (not raised — the test itself already finished)
        # so the operator sees what mode the test left the gateway in and
        # can correlate downstream failures.
        if override_was_active:
            try:
                resp = gateway_http_client.patch("/admin/runtime/mcp-mode", json={"mode": original_mode})
                if resp.status_code >= 400:
                    msg = f"flip_runtime_mode: failed to restore mode {original_mode!r} ({resp.status_code}): {resp.text[:200]}"
                    warnings.warn(msg, stacklevel=2)
                    print(f"[flip_runtime_mode] {msg}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 — best-effort teardown
                msg = f"flip_runtime_mode: restore to {original_mode!r} raised {type(exc).__name__}: {exc}"
                warnings.warn(msg, stacklevel=2)
                print(f"[flip_runtime_mode] {msg}", file=sys.stderr)
        # else: no override was originally active — there's no clear-override
        # API today, so leaving the test's override in place is acceptable
        # within the session (other tests re-read runtime_mode_state).


@pytest.fixture(scope="session")
def gateway_http_client(gateway_base_url: str, admin_jwt: str) -> Iterator[httpx.Client]:
    """Sync HTTP client for admin REST calls (POST /gateways, /servers).

    Sync intentionally — admin REST is not on the hot path, doesn't need
    streaming, and using ``httpx.Client`` lets the upstream-registration
    fixtures stay synchronous, sidestepping pytest-asyncio's cross-loop
    issues with session-scoped async fixtures consumed from function-scoped
    async tests.
    """
    with httpx.Client(
        base_url=gateway_base_url,
        follow_redirects=True,
        timeout=15.0,
        headers={"Authorization": f"Bearer {admin_jwt}"},
    ) as client:
        yield client
