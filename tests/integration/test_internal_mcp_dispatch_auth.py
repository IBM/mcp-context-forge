# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_internal_mcp_dispatch_auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Pratik Gandhi

End-to-end integration tests for trusted-internal MCP dispatch authorization.

These drive the *real* application through the ``/_internal/mcp/rpc`` endpoint using the
same loopback ASGI transport the session-affinity (and Rust runtime) dispatch uses, so the
full owner-side pipeline is exercised in-process: trust gate (HMAC + loopback) →
``_build_internal_mcp_forwarded_user`` → ``_handle_rpc_authenticated`` →
``_ensure_rpc_permission`` → method dispatch.

Contract under test:

- A **public-only** forwarded request (``is_authenticated: False``) is served, not RBAC-denied
  — the originating edge already applied public-only visibility. (The fix.)
- An **authenticated** forwarded caller without the required permission is still denied (-32003).
- A **forged** runtime-auth HMAC is rejected at the trust gate (it never reaches the RBAC skip).
- A valid HMAC with **no** auth-context header is rejected at the trust gate.
"""

# Standard
import orjson

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.auth_context import _expected_internal_mcp_runtime_auth_header, encode_internal_mcp_auth_context

PUBLIC_ONLY_CTX = {
    "email": None,
    "teams": [],
    "is_authenticated": False,
    "is_admin": False,
    "permission_is_admin": False,
    "auth_method": "anonymous",
}

AUTHENTICATED_CTX = {
    "email": "user@example.com",
    "teams": [],
    "is_authenticated": True,
    "is_admin": False,
    "permission_is_admin": False,
    "auth_method": "jwt",
}


def _trust_headers(ctx, *, hmac=None, include_ctx=True):
    """Build the trusted-internal dispatch headers.

    The HMAC is derived at call time (not captured at import) so suite-wide
    ``auth_encryption_secret`` mutation can't stale it.
    """
    headers = {
        "content-type": "application/json",
        "x-contextforge-mcp-runtime": "affinity",
        "x-contextforge-mcp-runtime-auth": hmac if hmac is not None else _expected_internal_mcp_runtime_auth_header(),
    }
    if include_ctx:
        headers["x-contextforge-auth-context"] = encode_internal_mcp_auth_context(ctx)
    return headers


async def _post_internal_rpc(app, method, ctx, *, hmac=None, include_ctx=True):
    """POST a JSON-RPC call to /_internal/mcp/rpc over a loopback ASGI transport."""
    body = orjson.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
    # client=("127.0.0.1", 0) makes scope["client"] loopback, satisfying the trust gate's
    # defense-in-depth loopback check (mirrors the real affinity dispatch transport).
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.post("/_internal/mcp/rpc", content=body, headers=_trust_headers(ctx, hmac=hmac, include_ctx=include_ctx))


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["tools/list", "resources/list", "prompts/list"])
async def test_public_only_internal_dispatch_is_served(app, method):
    """Public-only forwarded request is served (not RBAC-denied) — exercises the skip across list methods."""
    response = await _post_internal_rpc(app, method, PUBLIC_ONLY_CTX)
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("error", {}).get("code") != -32003, f"public-only {method} was RBAC-denied: {payload}"
    assert "result" in payload, f"expected a result for public-only {method}, got {payload}"


@pytest.mark.asyncio
async def test_authenticated_without_permission_is_denied(app):
    """An authenticated forwarded caller without permission still goes through RBAC and is denied."""
    response = await _post_internal_rpc(app, "tools/list", AUTHENTICATED_CTX)
    payload = response.json()
    assert payload.get("error", {}).get("code") == -32003, f"expected -32003 access denied, got {payload}"


@pytest.mark.asyncio
async def test_forged_runtime_auth_hmac_is_rejected(app):
    """A forged runtime-auth HMAC fails the trust gate; the public-only skip is never reached."""
    response = await _post_internal_rpc(app, "tools/list", PUBLIC_ONLY_CTX, hmac="forged-not-the-real-hmac")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_missing_auth_context_is_rejected(app):
    """A valid HMAC with no auth-context header fails the trust gate (non-authenticate path requires it)."""
    response = await _post_internal_rpc(app, "tools/list", PUBLIC_ONLY_CTX, include_ctx=False)
    assert response.status_code == 403
