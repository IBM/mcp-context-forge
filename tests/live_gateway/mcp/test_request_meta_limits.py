# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_request_meta_limits.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tests for request ``_meta`` limits at the /mcp endpoint (issue #6568).

- Oversize, over-keyed, and over-deep ``_meta`` is rejected with -32602 on
  ``tools/call``, ``resources/read``, and ``prompts/get``.
- The mandatory modern keys, with nested client capabilities, pass the limits.
- A request without a bearer token is rejected with 401.

Environment variables consumed:
    MCP_CLI_BASE_URL        Gateway URL (default: http://127.0.0.1:8080)
    JWT_SECRET_KEY          JWT signing secret of the target gateway.
    PLATFORM_ADMIN_EMAIL    Bootstrap admin email.

Usage:
    pytest tests/live_gateway/mcp/test_request_meta_limits.py -v
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

MODERN_PROTOCOL_VERSION = "2026-07-28"
MCP_URL = f"{BASE_URL}/mcp/"
ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientInfo": {"name": "meta-limits-test", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
}
METHODS = {
    "tools/call": {"name": "no-such-tool", "arguments": {}},
    "resources/read": {"uri": "test://no-such-resource"},
    "prompts/get": {"name": "no-such-prompt"},
}
BAD_META = {
    "bytes": {"big": "x" * 70000},
    "keys": {f"k{i}": i for i in range(30)},
    "depth": {"d": {"a": {"b": {"c": 1}}}},
}


def _post(method: str, extra_meta: dict[str, Any], token: str | None) -> httpx.Response:
    """POST a modern-era request carrying the mandatory envelope plus extra ``_meta`` keys.

    Args:
        method: MCP method name.
        extra_meta: Additional ``_meta`` keys.
        token: Bearer token, or None to omit Authorization.

    Returns:
        The raw httpx response.
    """
    params = dict(METHODS[method])
    params["_meta"] = {**ENVELOPE, **extra_meta}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
        "Mcp-Method": method,
        "Mcp-Name": params.get("name") or params["uri"],
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15.0)


def _admin_jwt() -> str:
    """Mint a platform-admin JWT for the bootstrap user.

    Returns:
        Signed JWT string.
    """
    return make_test_jwt(ADMIN_EMAIL, is_admin=True, secret=JWT_SECRET)


@pytest.mark.parametrize("limit", sorted(BAD_META))
@pytest.mark.parametrize("method", sorted(METHODS))
def test_invalid_meta_is_rejected_with_invalid_params(method: str, limit: str) -> None:
    """Every method answers over-limit ``_meta`` with -32602 that names the limit."""
    resp = _post(method, BAD_META[limit], _admin_jwt())
    body = resp.json()
    assert resp.status_code == 400, f"{method}/{limit}: {resp.status_code} {resp.text[:300]}"
    assert body["error"]["code"] == -32602, body
    assert "meta_data exceeds maximum" in body["error"]["message"], body


@pytest.mark.parametrize("method", sorted(METHODS))
def test_modern_envelope_passes_the_limits(method: str) -> None:
    """The mandatory modern keys never trigger a ``_meta`` limit error."""
    resp = _post(method, {}, _admin_jwt())
    assert "meta_data exceeds" not in resp.text, f"{method}: {resp.text[:300]}"


def test_unauthenticated_request_is_rejected() -> None:
    """A request without a bearer token gets 401 before ``_meta`` is read."""
    resp = _post("tools/call", BAD_META["bytes"], None)
    assert resp.status_code == 401, resp.text[:300]
