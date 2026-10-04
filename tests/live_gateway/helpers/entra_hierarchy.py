# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/helpers/entra_hierarchy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Provision a hierarchical Entra org for the hierarchy live e2e suite.

Creates 3 nested security groups (executives → division-leads →
engineers) and 3 users, one at each level. Returns the tokens and the
cleanup manifest. Uses the existing ``AZURE_*`` credentials.
"""

# Future
from __future__ import annotations

# Standard
import time
from typing import Any

# Third-Party
import httpx

# First-Party
from tests.live_gateway.helpers.entra_live import (
    _azure_credentials,
    _azure_graph_token,
    _ensure_group_claims,
    _generate_password,
    _resolve_default_domain,
    _ropc_until_valid,
    _decode_payload,
)

GRAPH = "https://graph.microsoft.com/v1.0"


def _create_group(headers: dict[str, str], display_name: str, nick: str) -> str:
    """Create a security group and return its id."""
    resp = httpx.post(
        f"{GRAPH}/groups",
        headers=headers,
        json={"displayName": display_name, "mailNickname": nick, "mailEnabled": False, "securityEnabled": True},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"group creation failed ({display_name}): HTTP {resp.status_code}")
    return resp.json()["id"]


def _create_user(headers: dict[str, str], display_name: str, upn: str, password: str) -> str:
    """Create a user and return its id."""
    resp = httpx.post(
        f"{GRAPH}/users",
        headers=headers,
        json={
            "accountEnabled": True,
            "displayName": display_name,
            "mailNickname": upn.split("@", 1)[0],
            "userPrincipalName": upn,
            "passwordProfile": {"password": password, "forceChangePasswordNextSignIn": False},
        },
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"user creation failed ({upn}): HTTP {resp.status_code}")
    return resp.json()["id"]


def _add_member(headers: dict[str, str], group_id: str, member_id: str, member_type: str = "users") -> None:
    """Add a member (user or group) to a group, retrying on replication lag."""
    for attempt in range(5):
        resp = httpx.post(
            f"{GRAPH}/groups/{group_id}/members/$ref",
            headers=headers,
            json={"@odata.id": f"{GRAPH}/{member_type}/{member_id}"},
            timeout=30,
        )
        if resp.status_code in (200, 201, 204):
            return
        if resp.status_code == 404 and attempt < 4:
            time.sleep(10)
            continue
        raise RuntimeError(f"member add failed ({member_type}/{member_id} → {group_id}): HTTP {resp.status_code}")


def provision_entra_hierarchy() -> dict[str, Any]:
    """Provision a 3-level org hierarchy in Entra.

    Creates nested groups and one user per level. Returns a dict with
    the tokens, group IDs, user IDs, and the cleanup manifest.

    Raises:
        RuntimeError: When any provisioning step fails.
    """
    client_id, client_secret, tenant_id, token_url = _azure_credentials()
    cleanup: dict[str, str] = {"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id}
    group_ids: list[str] = []
    user_ids: list[str] = []
    try:
        graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
        headers = {"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"}
        _ensure_group_claims(headers, client_id)
        domain = _resolve_default_domain(headers)
        stamp = int(time.time())
        prefix = f"cf-hier-{stamp}"

        # Create the hierarchy: executives > division-leads > engineers
        exec_group = _create_group(headers, f"{prefix}-executives", f"{prefix}exec")
        lead_group = _create_group(headers, f"{prefix}-division-leads", f"{prefix}lead")
        eng_group = _create_group(headers, f"{prefix}-engineers", f"{prefix}eng")
        group_ids = [exec_group, lead_group, eng_group]
        cleanup["hierarchy_group_ids"] = ",".join(group_ids)

        # Nest: engineers → division-leads → executives
        _add_member(headers, lead_group, eng_group, member_type="groups")
        _add_member(headers, exec_group, lead_group, member_type="groups")

        # Create one user per level
        passwords: dict[str, str] = {}
        upns: dict[str, str] = {}

        for level, group_id in [("exec", exec_group), ("lead", lead_group), ("eng", eng_group)]:
            password = _generate_password()
            upn = f"{prefix}-{level}@{domain}"
            user_id = _create_user(headers, f"CF Hier {level} {stamp}", upn, password)
            user_ids.append(user_id)
            cleanup[f"hier_user_{level}"] = user_id
            _add_member(headers, group_id, user_id)
            passwords[level] = password
            upns[level] = upn

        # Acquire tokens (retry until groups appear)
        tokens: dict[str, str] = {}
        for level in ("exec", "lead", "eng"):
            token, problems = _ropc_until_valid(
                token_url,
                client_id,
                client_secret,
                upns[level],
                passwords[level],
                lambda info: [] if info.get("groups") else ["no groups claim"],
            )
            if not token:
                raise RuntimeError(f"ROPC token for {level} failed: {problems}")
            tokens[level] = token

        return {
            "tokens": tokens,
            "upns": upns,
            "group_ids": {"exec": exec_group, "lead": lead_group, "eng": eng_group},
            "user_ids": user_ids,
            "cleanup": cleanup,
            "domain": domain,
            "prefix": prefix,
        }
    except Exception:
        _cleanup_entra_hierarchy(cleanup, group_ids, user_ids, headers if "headers" in dir() else {})
        raise


def _cleanup_entra_hierarchy(cleanup: dict, group_ids: list[str], user_ids: list[str], headers: dict) -> None:
    """Delete provisioned hierarchy objects, best-effort."""
    for uid in user_ids:
        try:
            httpx.delete(f"{GRAPH}/users/{uid}", headers=headers, timeout=15)
        except Exception:
            pass
    for gid in group_ids:
        try:
            httpx.delete(f"{GRAPH}/groups/{gid}", headers=headers, timeout=15)
        except Exception:
            pass


def get_transitive_groups(token: str) -> list[str]:
    """Call getMemberGroups on the token's user to resolve the hierarchy."""
    payload = _decode_payload(token)
    oid = payload.get("oid")
    if not oid:
        return []
    client_id, client_secret, tenant_id, _ = _azure_credentials()
    graph_token = _azure_graph_token(client_id, client_secret, tenant_id)
    resp = httpx.post(
        f"{GRAPH}/users/{oid}/getMemberGroups",
        headers={"Authorization": f"Bearer {graph_token}", "Content-Type": "application/json"},
        json={"securityEnabledOnly": True},
        timeout=30,
    )
    if resp.status_code != 200:
        return []
    return resp.json().get("value", [])


def inspect_token_groups(token: str) -> set[str]:
    """Return the direct group IDs from the token's groups claim."""
    payload = _decode_payload(token)
    return set(payload.get("groups", []))
