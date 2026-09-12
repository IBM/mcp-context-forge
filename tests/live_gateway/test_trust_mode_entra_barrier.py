# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_entra_barrier.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway evidence for the external-token ingress barrier on the A2A
invocation route (issues #5884 / #5885, acceptance intent of #5976 / #6272).

What this module pins:

    Microsoft Entra end-user access token
      -> POST /a2a/<deliberately-nonexistent-agent>/invoke
      -> 401 "Invalid authentication credentials"

The agent name is intentionally nonexistent: with a correctly wired
ingress, an authenticated and authorized caller reaches agent lookup and
receives 404. The current stack instead rejects the request at
authentication because the A2A dependency chain
(``require_permission`` -> ``get_current_user_with_permissions`` ->
``get_current_user``) calls ContextForge's internal verifier
(``verify_jwt_token_cached``), which accepts gateway-signed JWTs only.
The external issuer/JWKS path lives in
``mcpgateway/utils/verify_credentials.py`` but is never dispatched to on
this route, so a genuine Entra-signed token is indistinguishable from a
forged one at this choke point.

Both tests read the bearer material from untracked files and never log
their contents:

    entra-token-valid.txt   real Entra user access token
    entra-token-fake.txt    deliberately invalid token

Set ``ENTRA_BARRIER_TOKEN_DIR`` if the files live outside the repository
root. Point ``MCP_CLI_BASE_URL`` at the gateway under test (default
``http://127.0.0.1:8080``).

Expected result while the ingress is unfixed: both requests return 401.
When the external-aware verifier is wired into the authentication choke
points, the valid-token expectation flips to 404 (agent not found) and
the fake-token expectation stays 401.
"""

# Future
from __future__ import annotations

# Standard
import os
from pathlib import Path

# Third-Party
import httpx
import pytest

# Local
from .helpers.mcp_test_helpers import BASE_URL, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]

# Expected gateway mode for this run; must match the stack configuration.
EXPECTED_TRUST_MODE = os.getenv("JWT_TRUST_MODE", "db")

skip_unless_trust_mode = pytest.mark.skipif(
    EXPECTED_TRUST_MODE != "jwt-trust",
    reason="requires the stack started with JWT_TRUST_MODE=jwt-trust",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOKEN_DIR = Path(os.getenv("ENTRA_BARRIER_TOKEN_DIR", str(_REPO_ROOT)))
_VALID_TOKEN_FILE = _TOKEN_DIR / "entra-token-valid.txt"
_FAKE_TOKEN_FILE = _TOKEN_DIR / "entra-token-fake.txt"

skip_no_entra_tokens = pytest.mark.skipif(
    not (_VALID_TOKEN_FILE.is_file() and _FAKE_TOKEN_FILE.is_file()),
    reason=f"entra-token-valid.txt / entra-token-fake.txt not found in {_TOKEN_DIR} (set ENTRA_BARRIER_TOKEN_DIR)",
)

# Deliberately nonexistent: the fixed ingress must terminate at agent
# lookup with 404, not 401.
_NONEXISTENT_AGENT = "Agent-A-that-does-not-exist"


def _bearer(path: Path) -> str:
    """Read a bearer token from file without logging it."""
    return path.read_text(encoding="utf-8").strip()


def _invoke_agent(token: str) -> httpx.Response:
    """POST the A2A invocation route with the given bearer token."""
    return httpx.post(
        f"{BASE_URL}/a2a/{_NONEXISTENT_AGENT}/invoke",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"parameters": {}, "interaction_type": "query"},
        timeout=15,
    )


@skip_no_entra_tokens
def test_fake_entra_token_is_rejected() -> None:
    """Control: a deliberately invalid bearer gets 401 regardless of trust mode."""
    response = _invoke_agent(_bearer(_FAKE_TOKEN_FILE))
    assert response.status_code == 401, f"fake token not rejected: {response.status_code} {response.text[:200]}"
    assert "Invalid authentication credentials" in response.text


@skip_unless_trust_mode
@skip_no_entra_tokens
def test_valid_entra_user_token_is_blocked_before_external_verification() -> None:
    """PINNED NON-COMPLIANCE: a genuine Entra user token gets 401 at ingress.

    With ``JWT_TRUST_MODE=jwt-trust`` and
    ``SSO_API_TOKEN_AUTH_ENABLED=true`` on the gateway, a real Entra-signed
    end-user access token still fails the internal verifier before the
    trust-mode branch, group mapping, RBAC, visibility, or agent lookup can
    run: the request is rejected exactly like the forged-token control.

    Flipping expectation: once ``get_current_user()`` dispatches external
    issuers to the JWKS verifier (``verify_credentials_cached``), this
    caller authenticates, ``a2a.invoke`` authorization proceeds, and the
    deliberately nonexistent agent yields 404. Update this assertion to
    404 as part of that change; the fake-token control above must stay 401.
    """
    response = _invoke_agent(_bearer(_VALID_TOKEN_FILE))
    assert response.status_code == 401, f"Ingress no longer blocked: valid Entra token got {response.status_code} (expected 401 pre-fix, 404 post-fix) {response.text[:200]}"
    assert "Invalid authentication credentials" in response.text
