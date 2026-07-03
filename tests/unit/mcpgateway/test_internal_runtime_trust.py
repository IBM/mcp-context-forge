# -*- coding: utf-8 -*-
"""Unit tests for the consolidated internal-runtime trust gate.

Covers the shared helper in ``auth_context`` (``is_trusted_internal_runtime_request`` /
``is_trusted_internal_mcp_request``), the path-aware auth-context rule, the A2A
feature guard, the affinity marker, the HMAC-is-the-trust-boundary property, and
that the forwarded/client-IP headers are stripped from loopback passthrough.
"""

# Third-Party
import pytest
from starlette.requests import Request

# First-Party
from mcpgateway.auth_context import (
    _expected_internal_mcp_runtime_auth_header,
    _internal_path_requires_auth_context,
    is_trusted_internal_mcp_request,
    is_trusted_internal_runtime_request,
)

def _req(path, *, marker="rust", hmac="valid", ctx="ctx", client="127.0.0.1", extra=None):
    """Build a synthetic internal request."""
    headers = []
    if marker is not None:
        headers.append((b"x-contextforge-mcp-runtime", marker.encode()))
    if hmac is not None:
        # Derive the expected HMAC at call time, not module-import time. Other tests in the suite
        # mutate ``settings.auth_encryption_secret`` (the HMAC's input), so a value captured at import
        # would go stale and the gate would correctly reject the now-mismatched header.
        valid_hmac = _expected_internal_mcp_runtime_auth_header()
        headers.append((b"x-contextforge-mcp-runtime-auth", (valid_hmac if hmac == "valid" else hmac).encode()))
    if ctx is not None:
        headers.append((b"x-contextforge-auth-context", ctx.encode()))
    for k, v in (extra or []):
        headers.append((k, v))
    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "client": (client, 12345) if client else None}
    return Request(scope)


# --- path-aware auth-context rule ------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/_internal/mcp/authenticate", False),
    ("/_internal/mcp/authenticate/", False),
    ("/_internal/a2a/authenticate", False),
    ("/_internal/mcp/rpc", True),
    ("/_internal/mcp/initialize", True),
    ("/_internal/a2a/tasks/get", True),
])
def test_path_requires_auth_context(path, expected):
    assert _internal_path_requires_auth_context(path) is expected


# --- MCP gate: allow --------------------------------------------------------

def test_rpc_trusted_with_rust_marker_hmac_and_ctx():
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc")) is True


def test_rpc_trusted_with_affinity_marker():
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc", marker="affinity")) is True


def test_authenticate_trusted_without_ctx():
    # /authenticate creates the context, so no ctx required.
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/authenticate", ctx=None)) is True


# --- MCP gate: deny ---------------------------------------------------------

def test_deny_bad_hmac_even_on_loopback_with_ctx():
    # The HMAC is the trust boundary: loopback + marker + ctx but a bad HMAC is denied.
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc", hmac="not-the-real-hmac")) is False


def test_deny_wrong_marker():
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc", marker="bogus")) is False


def test_deny_non_loopback_client():
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc", client="10.0.0.9")) is False


def test_deny_rpc_missing_ctx():
    assert is_trusted_internal_mcp_request(_req("/_internal/mcp/rpc", ctx=None)) is False


def test_deny_non_internal_prefix():
    assert is_trusted_internal_mcp_request(_req("/servers/x/mcp")) is False


def test_xff_cannot_make_untrusted_request_trusted():
    # Even with a spoofed X-Forwarded-For and a loopback client, a bad HMAC is denied:
    # loopback is defense-in-depth, the HMAC is the boundary.
    req = _req("/_internal/mcp/rpc", hmac="forged", extra=[(b"x-forwarded-for", b"127.0.0.1")])
    assert is_trusted_internal_mcp_request(req) is False


# --- A2A feature guard ------------------------------------------------------

def test_a2a_trusted_when_enabled(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.settings.mcpgateway_a2a_enabled", True)
    assert is_trusted_internal_mcp_request(_req("/_internal/a2a/tasks/get")) is True


def test_a2a_denied_when_disabled(monkeypatch):
    monkeypatch.setattr("mcpgateway.auth_context.settings.mcpgateway_a2a_enabled", False)
    assert is_trusted_internal_mcp_request(_req("/_internal/a2a/tasks/get")) is False


# --- generic helper: explicit require_auth_context + prefixes ---------------

def test_generic_helper_respects_prefix_allowlist():
    req = _req("/_internal/mcp/rpc")
    assert is_trusted_internal_runtime_request(req, allowed_prefixes=("/_internal/a2a",), require_auth_context=True) is False
    assert is_trusted_internal_runtime_request(req, allowed_prefixes=("/_internal/mcp",), require_auth_context=True) is True


# --- token_scoping now trusts the affinity marker ---------------------------

def test_token_scoping_trusts_affinity_hop():
    # First-Party
    from mcpgateway.middleware.token_scoping import token_scoping_middleware

    req = _req("/_internal/mcp/rpc", marker="affinity")
    assert token_scoping_middleware._is_trusted_internal_mcp_runtime_request(req, "/_internal/mcp/rpc") is True


# --- forwarded / client-IP headers are stripped from loopback passthrough ---

@pytest.mark.parametrize("header", [
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-forwarded-port", "x-forwarded-prefix", "x-real-ip", "cf-connecting-ip", "true-client-ip",
])
def test_loopback_passthrough_strips_forwarded_headers(header):
    # First-Party
    from mcpgateway.utils.passthrough_headers import filter_loopback_skip_headers

    out = filter_loopback_skip_headers({header: "1.2.3.4", "x-keep": "ok"})
    assert header not in {k.lower() for k in out}
    assert out.get("x-keep") == "ok"
