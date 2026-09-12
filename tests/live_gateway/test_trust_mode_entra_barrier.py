# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_trust_mode_entra_barrier.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live-gateway evidence for the external-issuer A2A ingress contract (issues
#5884 / #5885, acceptance intent of #5976 / #6272; ingress fix #5903).

What this module pins:

    Microsoft Entra end-user access token
      -> POST /a2a/<deliberately-nonexistent-agent>/invoke
      -> 401 "Invalid authentication credentials"

The barrier scenario seeds no SSO providers, so the Entra issuer is NOT a
configured trust root. Under the post-fix dispatch semantics
(``get_current_user()`` -> ``_try_external_verification``), an issuer that
is not a configured trust root falls through to the internal JWT verifier
exactly as before, and the internal verifier rejects the externally-signed
token with 401. This 401 is now the correct, by-design fall-through — NOT
the pre-fix wiring failure, where the external JWKS path was unreachable
even for a seeded trust root.

The seeded-trust-root denial paths are proven by the ingress matrix
(tests/live_gateway/test_trust_mode_external_ingress_e2e.py):
authenticated-without-mapping -> 403 (``unmapped_user_invoke``) and
authenticated-with-role + deliberately nonexistent agent -> 404
(``nonexistent_agent_with_role``).

Both tests read the bearer material from untracked files and never log
their contents:

    entra-token-valid.txt   real Entra user access token
    entra-token-fake.txt    deliberately invalid token

Set ``ENTRA_BARRIER_TOKEN_DIR`` if the files live outside the repository
root. Point ``MCP_CLI_BASE_URL`` at the gateway under test (default
``http://127.0.0.1:8080``).

Expected result: both requests return 401 — the fake token because it is
forged, the valid token because its issuer is untrusted in this scenario
(fall-through). A fresh (unexpired) valid token is not required for these
assertions; expiry does not change the untrusted-issuer outcome.
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
def test_valid_entra_user_token_untrusted_issuer_falls_to_internal_verifier() -> None:
    """Unseeded Entra issuer -> fall-through to the internal verifier -> 401.

    Post-fix dispatch semantics (#5903): the ingress dispatch in
    ``get_current_user()`` routes a bearer to the external JWKS verifier
    only when its issuer IS a configured trust root. The barrier scenario
    seeds no providers, so the Entra issuer is NOT a configured trust root
    here and the token falls through to the internal verifier, which
    rejects it with 401 — the correct, by-design outcome for an untrusted
    issuer, NOT the pre-fix wiring failure (where even a seeded trust-root
    token could not authenticate).

    The seeded-issuer paths are proven by the ingress matrix
    (tests/live_gateway/test_trust_mode_external_ingress_e2e.py):
    authenticated-without-mapping -> 403 (``unmapped_user_invoke``) and
    authenticated-with-role + nonexistent agent -> 404
    (``nonexistent_agent_with_role``).
    """
    response = _invoke_agent(_bearer(_VALID_TOKEN_FILE))
    assert response.status_code == 401, f"untrusted-issuer fall-through no longer yields 401: {response.status_code} {response.text[:200]}"
    assert "Invalid authentication credentials" in response.text
