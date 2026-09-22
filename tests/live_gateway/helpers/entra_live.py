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
        "sub": claims.get("sub"),
        "idtyp": claims.get("idtyp"),
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


def _cleanup_entra_test_identity(cleanup: dict) -> None:
    """Delete provisioned users, groups, service principals, and applications.

    Best effort; errors are logged only. Fresh service principals and
    applications can 404 on delete until directory replication lands, so
    those deletions retry.
    """
    if not cleanup:
        return
    group_ids = list(cleanup.get("group_ids") or [])
    if cleanup.get("group_id"):
        group_ids.append(cleanup["group_id"])
    try:
        token = _azure_graph_token(cleanup["client_id"], cleanup["client_secret"], cleanup["tenant_id"])
        headers = {"Authorization": f"Bearer {token}"}
        if cleanup.get("user_id"):
            httpx.delete(f"https://graph.microsoft.com/v1.0/users/{cleanup['user_id']}", headers=headers, timeout=30)
        for group_id in group_ids:
            httpx.delete(f"https://graph.microsoft.com/v1.0/groups/{group_id}", headers=headers, timeout=30)

        def _delete_with_retry(kind: str, object_id: str) -> None:
            for attempt in range(3):
                response = httpx.delete(f"https://graph.microsoft.com/v1.0/{kind}/{object_id}", headers=headers, timeout=30)
                if response.status_code in (204, 404):
                    return
                time.sleep(10)

        if cleanup.get("sp_id"):
            _delete_with_retry("servicePrincipals", cleanup["sp_id"])
        if cleanup.get("app_object_id"):
            _delete_with_retry("applications", cleanup["app_object_id"])
    except Exception as exc:  # noqa: BLE001 — cleanup failures never fail the session
        print(f"WARNING: Entra cleanup incomplete ({exc}); delete these objects manually: {cleanup.get('user_id')} {cleanup.get('sp_id')} {cleanup.get('app_object_id')} {group_ids}")


def _resolve_default_domain(headers: dict[str, str]) -> str:
    """Resolve the tenant's default verified domain via GET /organization."""
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
    return domain


def _generate_password() -> str:
    """Generate a strong throwaway password for a provisioned test user."""
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20)) + "!E2e-Aa9"


def _ropc_until_valid(token_url: str, client_id: str, client_secret: str, upn: str, password: str, validator, attempts: int = 4, delay: int = 15) -> tuple[str, list]:
    """ROPC-acquire a token, retrying until the validator accepts it.

    Returns ``(token, problems)``; ``problems`` is empty on success and
    carries the validator's findings from the LAST attempt on exhaustion.
    Raises ``_ProvisioningError`` when the grant itself fails.
    """
    problems: list = []
    for attempt in range(1, attempts + 1):
        print(f"[entra] token attempt {attempt}/{attempts} (claim propagation can lag)")
        time.sleep(delay)
        response = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
                "username": upn,
                "password": password,
                "scope": f"{client_id}/.default openid profile",
            },
            timeout=30,
        )
        if response.status_code != 200:
            error = response.json().get("error", "unknown_error")
            raise _ProvisioningError(f"ROPC acquisition failed with HTTP {response.status_code} ({error}); the tenant may block ROPC")
        candidate = response.json()["access_token"]
        problems = validator(inspect_token(candidate))
        if not problems:
            return candidate, problems
    return "", problems


def _azure_credentials() -> tuple[str, str, str, str]:
    """Read and validate the AZURE_* triple; returns (client_id, client_secret, tenant_id, token_url)."""
    client_id = os.getenv("AZURE_CLIENT_ID", "")
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "")
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    if not (client_id and client_secret and tenant_id):
        raise _ProvisioningError("AZURE_CLIENT_ID, AZURE_CLIENT_SECRET and AZURE_TENANT_ID are not all set")
    return client_id, client_secret, tenant_id, f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def provision_entra_test_identity() -> tuple[str, dict[str, str]]:
    """Provision a throwaway user, group, and membership; return (token, cleanup).

    Uses ``AZURE_CLIENT_ID``/``AZURE_CLIENT_SECRET``/``AZURE_TENANT_ID``.
    Raises ``_ProvisioningError`` when a step fails. The caller MUST pass
    the cleanup dict to ``_cleanup_entra_test_identity`` afterwards, even
    on failure paths: this function cleans up its own partial state
    before re-raising.
    """
    client_id, client_secret, tenant_id, token_url = _azure_credentials()
    cleanup: dict[str, str] = {"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id}
    try:
        graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
        headers = {"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"}
        _ensure_group_claims(headers, client_id)
        domain = _resolve_default_domain(headers)
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
        password = _generate_password()
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
        for _attempt in range(3):
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
        token, problems = _ropc_until_valid(token_url, client_id, client_secret, f"{unique}@{domain}", password, validate_for_inline_groups)
        if not token:
            raise _ProvisioningError(f"the provisioned token never carried inline groups: {'; '.join(problems)}")
        return token, cleanup
    except _ProvisioningError:
        _cleanup_entra_test_identity(cleanup)
        raise


def validate_for_overage(info: dict[str, Any]) -> list[str]:
    """Return unmet requirements for the overage use case (UC4)."""
    problems: list[str] = []
    if not info["has_overage_marker"]:
        problems.append("token carries no group-overage marker (the user must belong to more than 200 groups)")
    if not isinstance(info["exp"], int) or info["exp"] <= int(time.time()):
        problems.append("token is expired")
    if not info["oid"]:
        problems.append("token lacks oid (JWT_CLAIM_USER_ID target)")
    if not info["uti"]:
        problems.append("token lacks uti (JWT_TRUST_REVOCATION_CLAIM target)")
    return problems


OVERAGE_GROUP_COUNT = 201
"""Memberships required to push a user past Entra's 200-group inline-claim limit."""


def provision_entra_overage_identity() -> tuple[str, dict]:
    """Provision a user in more than 200 groups; return (token, cleanup).

    Creates one mapped group plus ``OVERAGE_GROUP_COUNT - 1`` filler
    groups, adds the user to all of them, and ROPC-acquires a token that
    carries the group-overage marker instead of inline groups. The mapped
    group GUID is stashed in the returned info as
    ``provisioned_mapped_group`` by the caller (see the fixture). Cleanup
    deletes the user and every group.
    """
    client_id, client_secret, tenant_id, token_url = _azure_credentials()
    cleanup: dict = {"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id, "group_ids": [], "mapped_group_id": None}
    try:
        graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
        headers = {"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"}
        _ensure_group_claims(headers, client_id)
        domain = _resolve_default_domain(headers)
        unique = f"cf-overage-{int(time.time())}"
        password = _generate_password()
        user = httpx.post(
            "https://graph.microsoft.com/v1.0/users",
            headers=headers,
            json={
                "accountEnabled": True,
                "displayName": f"CF Overage E2E {int(time.time())}",
                "mailNickname": unique,
                "userPrincipalName": f"{unique}@{domain}",
                "passwordProfile": {"password": password, "forceChangePasswordNextSignIn": False},
            },
            timeout=30,
        )
        if user.status_code not in (200, 201):
            raise _ProvisioningError(f"user creation failed with HTTP {user.status_code}; the Graph application permissions may be missing")
        cleanup["user_id"] = user.json()["id"]
        stamp = int(time.time())
        print(f"[entra-overage] user created; creating {OVERAGE_GROUP_COUNT} groups")
        # Phase 1: create every group first (no per-group sleeps).
        for index in range(OVERAGE_GROUP_COUNT):
            if index % 25 == 0:
                print(f"[entra-overage] create group {index}/{OVERAGE_GROUP_COUNT}")
            filler = httpx.post(
                "https://graph.microsoft.com/v1.0/groups",
                headers=headers,
                json={"displayName": f"ContextForge-Overage-{stamp}-{index:03d}", "mailNickname": f"{unique}-{index:03d}", "mailEnabled": False, "securityEnabled": True},
                timeout=30,
            )
            if filler.status_code not in (200, 201):
                raise _ProvisioningError(f"filler group {index} creation failed with HTTP {filler.status_code}: {filler.text[:200]}")
            group_id = filler.json()["id"]
            cleanup["group_ids"].append(group_id)
            if index == 0:
                cleanup["mapped_group_id"] = group_id
        # Phase 2: add the user to every group. By now the groups have
        # replicated; a straggler 404 retries with a short sleep.
        print(f"[entra-overage] groups created; adding the user to {OVERAGE_GROUP_COUNT} groups")
        for index, group_id in enumerate(cleanup["group_ids"]):
            if index % 25 == 0:
                print(f"[entra-overage] membership {index}/{OVERAGE_GROUP_COUNT}")
            member = None
            for _attempt in range(4):
                member = httpx.post(
                    f"https://graph.microsoft.com/v1.0/groups/{group_id}/members/$ref",
                    headers=headers,
                    json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{cleanup['user_id']}"},
                    timeout=30,
                )
                if member.status_code in (200, 201, 204) or member.status_code != 404:
                    break
                time.sleep(2)  # a fresh group can 404 on members/$ref until replication lands
            if member is None or member.status_code not in (200, 201, 204):
                raise _ProvisioningError(f"filler membership {index} failed with HTTP {member.status_code if member else 'n/a'}")
        print(f"[entra-overage] all {OVERAGE_GROUP_COUNT} groups and memberships done; acquiring overage token")
        # Membership propagation can lag: retry until the overage marker appears.
        token, problems = _ropc_until_valid(token_url, client_id, client_secret, f"{unique}@{domain}", password, validate_for_overage, attempts=5, delay=20)
        if not token:
            raise _ProvisioningError(f"the provisioned token never carried the overage marker: {'; '.join(problems)}")
        return token, cleanup
    except _ProvisioningError:
        _cleanup_entra_test_identity(cleanup)
        raise


def load_entra_app_only_token() -> Optional[str]:
    """Load a pre-acquired app-only token from ENTRA_APPONLY_TOKEN_FILE."""
    path = os.getenv("ENTRA_APPONLY_TOKEN_FILE")
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read().strip()


def acquire_entra_app_only_token(client_id: str, client_secret: str, tenant_id: str) -> str:
    """Acquire an app-only (client-credentials) token for the app's own audience.

    The token carries idtyp=app only when the app registration requests
    v2.0 access tokens (api.requestedAccessTokenVersion=2) and lists
    idtyp as an optional claim. Raises ``_ProvisioningError`` on failure;
    the response body is never logged.
    """
    response = None
    for _attempt in range(6):
        response = httpx.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": f"{client_id}/.default",
            },
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()["access_token"]
        time.sleep(10)  # a fresh client secret can 401 at the token endpoint until it propagates
    raise _ProvisioningError(f"app-only token acquisition failed with HTTP {response.status_code if response else 'n/a'}; the body carried no logged secrets")


def validate_for_app_only(info: dict[str, Any]) -> list[str]:
    """Return unmet requirements for the app-only use case."""
    problems: list[str] = []
    if info.get("idtyp") != "app":
        problems.append(
            "idtyp claim is not 'app': v1 access tokens omit idtyp. Register the app with "
            "api.requestedAccessTokenVersion=2 (Microsoft Graph manifest) and the idtyp "
            "optional claim, or point ENTRA_APPONLY_TOKEN_FILE at a v2 app-only token"
        )
    if info.get("groups"):
        problems.append("groups claim is present; expected none on an app-only token")
    if info.get("has_overage_marker"):
        problems.append("token carries a group-overage marker (unexpected for app-only)")
    if not isinstance(info.get("exp"), int) or info["exp"] <= int(time.time()):
        problems.append("token is expired")
    if not info.get("oid"):
        problems.append("token lacks oid (the Graph service-principal lookup key)")
    if not info.get("uti"):
        problems.append("token lacks uti (JWT_TRUST_REVOCATION_CLAIM target)")
    return problems


def provision_entra_app_only_identity() -> tuple[str, dict[str, str]]:
    """Provision a throwaway v2 app and a group holding its service principal.

    Creates an application with api.requestedAccessTokenVersion=2 and the
    idtyp optional claim (Microsoft Graph manifest format), its service
    principal, a client secret, and one security group holding the service
    principal. The client-credentials token for the app's own audience
    then carries idtyp=app, no groups claim, and a v2 issuer. Raises
    ``_ProvisioningError`` when a step fails; partial state is cleaned up
    before re-raising. The caller MUST pass the cleanup dict to
    ``_cleanup_entra_test_identity`` afterwards.
    """
    client_id, client_secret, tenant_id, _token_url = _azure_credentials()
    cleanup: dict[str, str] = {"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id}
    try:
        unique = f"cf-live-e2e-apponly-{int(time.time())}"
        app = httpx.post(
            "https://graph.microsoft.com/v1.0/applications",
            headers={"Authorization": f"Bearer {_azure_graph_token(client_id, client_secret, tenant_id)}", "Content-Type": "application/json"},
            json={"displayName": f"ContextForge-LiveE2E-AppOnly-{int(time.time())}", "api": {"requestedAccessTokenVersion": 2}, "optionalClaims": {"accessToken": [{"name": "idtyp"}]}},
            timeout=30,
        )
        if app.status_code not in (200, 201):
            raise _ProvisioningError(f"throwaway application creation failed with HTTP {app.status_code}; the Graph application permissions may be missing")
        app_id = app.json()["appId"]
        cleanup["app_object_id"] = app.json()["id"]
        sp = None
        for _attempt in range(6):
            sp = httpx.post("https://graph.microsoft.com/v1.0/servicePrincipals", headers={"Authorization": f"Bearer {_azure_graph_token(client_id, client_secret, tenant_id)}", "Content-Type": "application/json"}, json={"appId": app_id}, timeout=30)
            if sp.status_code in (200, 201):
                break
            time.sleep(10)  # a fresh application can 400 on service-principal creation until directory replication lands
        if sp is None or sp.status_code not in (200, 201):
            raise _ProvisioningError(f"service-principal creation failed with HTTP {sp.status_code if sp else 'n/a'}")
        sp_id = sp.json()["id"]
        cleanup["sp_id"] = sp_id
        password = httpx.post(f"https://graph.microsoft.com/v1.0/applications/{cleanup['app_object_id']}/addPassword", headers={"Authorization": f"Bearer {_azure_graph_token(client_id, client_secret, tenant_id)}", "Content-Type": "application/json"}, json={"passwordCredential": {"displayName": "e2e"}}, timeout=30)
        if password.status_code not in (200, 201):
            raise _ProvisioningError(f"client-secret creation failed with HTTP {password.status_code}")
        app_secret = password.json()["secretText"]
        token = acquire_entra_app_only_token(app_id, app_secret, tenant_id)
        problems = validate_for_app_only(inspect_token(token))
        if problems:
            raise _ProvisioningError(f"the app-only token did not satisfy trust-mode prerequisites: {'; '.join(problems)}")
        headers = {"Authorization": f"Bearer {_azure_graph_token(client_id, client_secret, tenant_id)}", "Content-Type": "application/json"}
        group = httpx.post(
            "https://graph.microsoft.com/v1.0/groups",
            headers=headers,
            json={"displayName": f"ContextForge-LiveE2E-AppOnly-Group-{int(time.time())}", "mailNickname": unique, "mailEnabled": False, "securityEnabled": True},
            timeout=30,
        )
        if group.status_code not in (200, 201):
            raise _ProvisioningError(f"group creation failed with HTTP {group.status_code}; the Graph application permissions may be missing")
        cleanup["group_id"] = group.json()["id"]
        member = None
        for _attempt in range(3):
            member = httpx.post(
                f"https://graph.microsoft.com/v1.0/groups/{cleanup['group_id']}/members/$ref",
                headers=headers,
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{sp_id}"},
                timeout=30,
            )
            if member.status_code in (200, 201, 204) or member.status_code != 404:
                break
            time.sleep(10)  # a fresh group can 404 on members/$ref until directory replication lands
        if member is None or member.status_code not in (200, 201, 204):
            raise _ProvisioningError(f"service-principal membership failed with HTTP {member.status_code if member else 'n/a'}: {member.text[:200] if member else ''} (group={cleanup['group_id']} sp={sp_id})")
        for _attempt in range(9):
            visible = httpx.post(
                f"https://graph.microsoft.com/v1.0/servicePrincipals/{sp_id}/getMemberObjects",
                headers=headers,
                json={"securityEnabledOnly": False},
                timeout=30,
            )
            if visible.status_code == 200 and cleanup["group_id"] in visible.json().get("value", []):
                break
            time.sleep(10)  # getMemberObjects can lag the members/$ref write; the gateway reads it at request time

        return token, cleanup
    except _ProvisioningError:
        _cleanup_entra_test_identity(cleanup)
        raise


def resolve_entra_sp_first_group(token: str) -> Optional[str]:
    """Return the service principal's first current group ID via Graph.

    Operator mode for the app-only use case: the token's own SP
    membership supplies the group to map. Returns None when Graph cannot
    resolve the SP or it holds no membership.
    """
    try:
        client_id, client_secret, tenant_id, _token_url = _azure_credentials()
    except _ProvisioningError:
        return None
    try:
        graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
        headers = {"Authorization": f"Bearer {graph_token}"}
        oid = inspect_token(token).get("oid")
        if not oid:
            return None
        member = httpx.get(f"https://graph.microsoft.com/v1.0/servicePrincipals/{oid}/memberOf", headers=headers, params={"$select": "id"}, timeout=30)
        if member.status_code != 200 or not member.json().get("value"):
            return None
        return member.json()["value"][0]["id"]
    except (httpx.HTTPError, _ProvisioningError):
        return None


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
