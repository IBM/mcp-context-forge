# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/entra_live.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Live Microsoft Entra token sourcing for inline-groups e2e tests.

Tokens are NEVER mocked and NEVER logged. Three sourcing modes, first
match wins:

1. ``ENTRA_LIVE_TOKEN_FILE`` (or ``ENTRA_LIVE_TOKEN_DIR`` containing
   ``entra-token-valid-v2.txt``): a pre-acquired v2 end-user token, as
   produced interactively for the manual test run.
2. Self-provisioning when ``AZURE_CLIENT_ID``, ``AZURE_CLIENT_SECRET``
   and ``AZURE_TENANT_ID`` are set (the repository's integration-test
   credential names). The helper creates a security group and a test
   user, adds the user to the group, sets ``groupMembershipClaims`` on
   the application when missing, and acquires a v2 token through ROPC.
   The fixture deletes the user and the group after the session.
3. ROPC acquisition for a pre-existing account when ``ENTRA_TENANT_ID``,
   ``ENTRA_CLIENT_ID``, ``ENTRA_TEST_USERNAME`` and
   ``ENTRA_TEST_PASSWORD`` are set.

The self-provisioning mode needs these admin-consented Microsoft
Graph application permissions: ``User.ReadWrite.All``,
``Group.ReadWrite.All``, ``GroupMember.ReadWrite.All`` and
``Application.ReadWrite.All``. The last permission lets the helper set
``groupMembershipClaims``. The Graph API expects the string value
``"SecurityGroup"``, not an array. Without the permission, set the
manifest value by hand.

The gateway performs the real verification against Entra JWKS; the
payload decode here is for extracting seeding values only.
"""

# Future
from __future__ import annotations

# Standard
import base64
import json
import os
import secrets
import string
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


class _ProvisioningError(RuntimeError):
    """Raised when AZURE_* self-provisioning cannot complete."""


def _azure_graph_token(client_id: str, client_secret: str, tenant_id: str) -> str:
    """Acquire an app-only Microsoft Graph token via client credentials."""
    response = httpx.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise _ProvisioningError(f"client-credentials token failed with HTTP {response.status_code}; the body carried no logged secrets")
    return response.json()["access_token"]


def _ensure_group_claims(headers: dict[str, str], client_id: str) -> None:
    """Set groupMembershipClaims on the application when it is missing.

    A 403 means the credential lacks Application.ReadWrite.All. The
    check is an optimization: proceed, and let the token validation
    report a missing groups claim with the manual remediation.
    """
    lookup = httpx.get(
        "https://graph.microsoft.com/v1.0/applications",
        params={"$filter": f"appId eq '{client_id}'", "$select": "id,groupMembershipClaims"},
        headers=headers,
        timeout=30,
    )
    if lookup.status_code == 403:
        print("WARNING: cannot read the application manifest (HTTP 403); proceeding without the groupMembershipClaims check")
        return
    if lookup.status_code != 200:
        raise _ProvisioningError(f"application lookup failed with HTTP {lookup.status_code}")
    matches = lookup.json().get("value", [])
    if not matches:
        raise _ProvisioningError("the application object was not found for AZURE_CLIENT_ID")
    claims = matches[0].get("groupMembershipClaims") or []
    if "SecurityGroup" in claims or "All" in claims:
        return
    patch = httpx.patch(
        f"https://graph.microsoft.com/v1.0/applications/{matches[0]['id']}",
        headers=headers,
            json={"groupMembershipClaims": "SecurityGroup"},
        timeout=30,
    )
    if patch.status_code >= 300:
        raise _ProvisioningError(
            f"setting groupMembershipClaims failed with HTTP {patch.status_code}; "
            "set it to [\"SecurityGroup\"] manually on the App Registration"
        )


def _cleanup_entra_test_identity(cleanup: dict[str, str]) -> None:
    """Delete the provisioned user and group. Best effort; errors are logged only."""
    if not cleanup:
        return
    try:
        token = _azure_graph_token(cleanup["client_id"], cleanup["client_secret"], cleanup["tenant_id"])
        headers = {"Authorization": f"Bearer {token}"}
        if cleanup.get("user_id"):
            httpx.delete(f"https://graph.microsoft.com/v1.0/users/{cleanup['user_id']}", headers=headers, timeout=30)
        if cleanup.get("group_id"):
            httpx.delete(f"https://graph.microsoft.com/v1.0/groups/{cleanup['group_id']}", headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001 — cleanup failures never fail the session
        print(f"WARNING: Entra cleanup incomplete ({exc}); delete these objects manually: {cleanup.get('user_id')} {cleanup.get('group_id')}")


def provision_entra_test_identity() -> tuple[str, dict[str, str]]:
    """Provision a throwaway user, group, and membership; return (token, cleanup).

    Uses ``AZURE_CLIENT_ID``/``AZURE_CLIENT_SECRET``/``AZURE_TENANT_ID``.
    Raises ``_ProvisioningError`` when a step fails. The caller MUST pass
    the cleanup dict to ``_cleanup_entra_test_identity`` afterwards, even
    on failure paths: this function cleans up its own partial state
    before re-raising.
    """
    client_id = os.getenv("AZURE_CLIENT_ID", "")
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    if not (client_id and client_secret and tenant_id):
        raise _ProvisioningError("AZURE_CLIENT_ID, AZURE_CLIENT_SECRET and AZURE_TENANT_ID are not all set")
    cleanup: dict[str, str] = {"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id}
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    try:
        graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
        headers = {"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"}
        _ensure_group_claims(headers, client_id)
        org = httpx.get("https://graph.microsoft.com/v1.0/organization", params={"$select": "verifiedDomains"}, headers=headers, timeout=30)
        domain = None
        if org.status_code == 200:
            for org_row in org.json().get("value", []):
                for verified in org_row.get("verifiedDomains", []):
                    if verified.get("isDefault"):
                        domain = verified.get("name")
                        break
                if domain:
                    break
        if not domain:
            raise _ProvisioningError("the default tenant domain could not be resolved through GET /organization")
        unique = f"cf-live-e2e-{int(time.time())}"
        group = httpx.post(
            "https://graph.microsoft.com/v1.0/groups",
            headers=headers,
            json={"displayName": f"ContextForge-LiveE2E-{int(time.time())}", "mailNickname": unique, "mailEnabled": False, "securityEnabled": True},
            timeout=30,
        )
        if group.status_code not in (200, 201):
            raise _ProvisioningError(f"group creation failed with HTTP {group.status_code}; the Graph application permissions may be missing")
        cleanup["group_id"] = group.json()["id"]
        password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20)) + "!E2e-Aa9"
        user = httpx.post(
            "https://graph.microsoft.com/v1.0/users",
            headers=headers,
            json={
                "accountEnabled": True,
                "displayName": f"CF Live E2E {int(time.time())}",
                "mailNickname": unique,
                "userPrincipalName": f"{unique}@{domain}",
                "passwordProfile": {"password": password, "forceChangePasswordNextSignIn": False},
            },
            timeout=30,
        )
        if user.status_code not in (200, 201):
            raise _ProvisioningError(f"user creation failed with HTTP {user.status_code}; the Graph application permissions may be missing")
        cleanup["user_id"] = user.json()["id"]
        member = None
        for attempt in range(3):
            member = httpx.post(
                f"https://graph.microsoft.com/v1.0/groups/{cleanup['group_id']}/members/$ref",
                headers=headers,
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{cleanup['user_id']}"},
                timeout=30,
            )
            if member.status_code in (200, 201, 204) or member.status_code != 404:
                break
            time.sleep(10)  # a fresh user can 404 on members/$ref until directory replication lands
        if member is None or member.status_code not in (200, 201, 204):
            raise _ProvisioningError(f"group membership failed with HTTP {member.status_code if member else 'n/a'}: {member.text[:200] if member else ''} (group={cleanup['group_id']} user={cleanup['user_id']})")
        # Group-claim propagation can lag membership by a short delay: retry ROPC.
        last_problems: list[str] = []
        for _ in range(3):
            time.sleep(15)
            response = httpx.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": f"{unique}@{domain}",
                    "password": password,
                    "scope": f"{client_id}/.default openid profile",
                },
                timeout=30,
            )
            if response.status_code != 200:
                error = response.json().get("error", "unknown_error")
                raise _ProvisioningError(f"ROPC acquisition failed with HTTP {response.status_code} ({error}); the tenant may block ROPC")
            candidate = response.json()["access_token"]
            last_problems = validate_for_inline_groups(inspect_token(candidate))
            if not last_problems:
                return candidate, cleanup
        raise _ProvisioningError(f"the provisioned token never carried inline groups: {'; '.join(last_problems)}")
    except _ProvisioningError:
        _cleanup_entra_test_identity(cleanup)
        raise


@pytest.fixture(scope="session")
def entra_inline_token() -> Any:
    """Yield (token, info) from a REAL Entra v2 token; skip when unavailable.

    Skip reasons name the exact environment variables or the failing
    provisioning step; a skipped run never fails the suite.
    """
    token = load_entra_token()
    cleanup: dict[str, str] = {}
    if not token:
        if os.getenv("AZURE_CLIENT_ID") and os.getenv("AZURE_CLIENT_SECRET") and os.getenv("AZURE_TENANT_ID"):
            try:
                token, cleanup = provision_entra_test_identity()
            except _ProvisioningError as exc:
                pytest.skip(f"AZURE_* self-provisioning failed: {exc}")
            except httpx.HTTPError as exc:
                pytest.skip(
                    f"AZURE_* self-provisioning cannot reach Entra endpoints ({type(exc).__name__}); "
                    'set TESTS_DNS_PASSTHROUGH_HOSTS="login.microsoftonline.com,graph.microsoft.com" '
                    "(tests/conftest.py blackholes external DNS by default)"
                )
        else:
            token = acquire_entra_token_ropc()

    if not token:
        pytest.skip(
            "live Entra token not configured: set ENTRA_LIVE_TOKEN_FILE (or "
            "ENTRA_LIVE_TOKEN_DIR/entra-token-valid-v2.txt), or AZURE_CLIENT_ID + "
            "AZURE_CLIENT_SECRET + AZURE_TENANT_ID, or ROPC env ENTRA_TENANT_ID + "
            "ENTRA_CLIENT_ID + ENTRA_TEST_USERNAME + ENTRA_TEST_PASSWORD"
        )
    info = inspect_token(token)
    problems = validate_for_inline_groups(info)
    if problems:
        pytest.skip(f"live Entra token unusable for inline-groups tests: {'; '.join(problems)}")
    yield token, info
    _cleanup_entra_test_identity(cleanup)
