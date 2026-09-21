# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/entra_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live Microsoft Entra token sourcing for inline-groups e2e tests.

Tokens are NEVER mocked and NEVER logged. Two sourcing modes, first
match wins:

1. ``ENTRA_LIVE_TOKEN_FILE`` (or ``ENTRA_LIVE_TOKEN_DIR`` containing
   ``entra-token-valid-v2.txt``): a pre-acquired v2 end-user token, as
   produced interactively for the manual test run.
2. ROPC acquisition when ``ENTRA_TENANT_ID``, ``ENTRA_CLIENT_ID``,
   ``ENTRA_TEST_USERNAME`` and ``ENTRA_TEST_PASSWORD`` are set. ROPC
   requires a dedicated test account without interactive MFA; tenants
   that block ROPC should use mode 1.

The gateway performs the real verification against Entra JWKS; the
payload decode here is for extracting seeding values only.
"""

# Future
from __future__ import annotations

# Standard
import base64
import json
import os
import time
from typing import Any, Optional

# Third-Party
import httpx
import pytest

DEFAULT_TOKEN_FILENAME = "entra-token-valid-v2.txt"


def _decode_payload(token: str) -> dict[str, Any]:
    """Decode the JWT payload segment without verification (gateway verifies)."""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def inspect_token(token: str) -> dict[str, Any]:
    """Extract non-secret seeding values from a v2 token payload."""
    claims = _decode_payload(token)
    groups = claims.get("groups", [])
    audience = claims.get("aud")
    if isinstance(audience, list):
        audience = audience[0] if audience else None
    return {
        "issuer": claims.get("iss"),
        "audience": audience,
        "tenant_id": claims.get("tid"),
        "oid": claims.get("oid"),
        "uti": claims.get("uti"),
        "groups": [str(group) for group in groups] if isinstance(groups, list) else [],
        "has_overage_marker": bool(claims.get("hasgroups") or claims.get("_claim_names")),
        "exp": claims.get("exp"),
    }


def validate_for_inline_groups(info: dict[str, Any]) -> list[str]:
    """Return unmet requirements for the inline-groups use cases."""
    problems: list[str] = []
    if not info["groups"]:
        problems.append("token carries no inline groups claim")
    if info["has_overage_marker"]:
        problems.append("token carries a group-overage marker (need a non-overage user token for UC1-3)")
    if not isinstance(info["exp"], int) or info["exp"] <= int(time.time()):
        problems.append("token is expired")
    if not info["oid"]:
        problems.append("token lacks oid (JWT_CLAIM_USER_ID target)")
    if not info["uti"]:
        problems.append("token lacks uti (JWT_TRUST_REVOCATION_CLAIM target)")
    return problems


def load_entra_token() -> Optional[str]:
    """Load a pre-acquired token from file, if configured."""
    path = os.getenv("ENTRA_LIVE_TOKEN_FILE")
    if not path:
        directory = os.getenv("ENTRA_LIVE_TOKEN_DIR")
        if directory:
            path = os.path.join(directory, DEFAULT_TOKEN_FILENAME)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def acquire_entra_token_ropc() -> Optional[str]:
    """Acquire a token via ROPC when all credentials are configured."""
    tenant = os.getenv("ENTRA_TENANT_ID")
    client_id = os.getenv("ENTRA_CLIENT_ID")
    username = os.getenv("ENTRA_TEST_USERNAME")
    password = os.getenv("ENTRA_TEST_PASSWORD")
    if not (tenant and client_id and username and password):
        return None
    response = httpx.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": os.getenv("ENTRA_TOKEN_SCOPE", f"{client_id}/.default openid profile"),
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Entra ROPC acquisition failed with HTTP {response.status_code}; body carried no logged secrets")
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def entra_inline_token() -> Any:
    """Yield (token, info) from a REAL Entra v2 token; skip when unavailable.

    Skip reasons name the exact environment variables that enable the
    test; a skipped run never fails the suite.
    """
    token = load_entra_token() or acquire_entra_token_ropc()
    if not token:
        pytest.skip(
            "live Entra token not configured: set ENTRA_LIVE_TOKEN_FILE (or "
            "ENTRA_LIVE_TOKEN_DIR/entra-token-valid-v2.txt), or ROPC env "
            "ENTRA_TENANT_ID + ENTRA_CLIENT_ID + ENTRA_TEST_USERNAME + ENTRA_TEST_PASSWORD"
        )
    info = inspect_token(token)
    problems = validate_for_inline_groups(info)
    if problems:
        pytest.skip(f"live Entra token unusable for inline-groups tests: {'; '.join(problems)}")
    yield token, info
