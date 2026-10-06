#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./scripts/demo_openfga_seed.py

Seed the OpenFGA demo environment on a running ContextForge gateway.

Creates the fast-time federation gateway, a public virtual server that
carries its tools, and 4 non-administrative users. The tmux launcher
mints per-user API keys at chat start, so this seeder stores no keys.

Every step is idempotent: run it against a seeded stack and it only
fills the gaps.

Environment:
    GATEWAY_URL            Gateway base URL (default http://gateway:4444).
    PLATFORM_ADMIN_EMAIL   Admin account (default admin@example.com).
    PLATFORM_ADMIN_PASSWORD  Admin password. Required.
    DEMO_USER_PASSWORD     Password for the 4 demo users
                           (default Demo!Passw0rd#2026).
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

USERS = ("alice", "becky", "carol", "david")
SERVER_NAME = "fast-time-demo"
GATEWAY_NAME = "fast_time"
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:4444")
ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
DEMO_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "Demo!Passw0rd#2026")  # pragma: allowlist secret
FAST_TIME_UPSTREAM = "http://fast_time_server:9080/mcp"


def log(message: str) -> None:
    """Print one progress line."""
    print(f"[demo-seed] {message}", flush=True)


def wait_healthy(client: httpx.Client) -> None:
    """Block until the gateway answers /health."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2.0)
    raise SystemExit("gateway never became healthy")


def login(client: httpx.Client, email: str, password: str) -> str:
    """Return a session bearer token for the account."""
    response = client.post("/auth/email/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def ensure_federation_gateway(client: httpx.Client, headers: dict[str, str]) -> str:
    """Register the fast-time gateway and return its id."""
    gateways = client.get("/gateways", headers=headers).json()
    for row in gateways:
        if row.get("name") == GATEWAY_NAME:
            log(f"federation gateway present: {GATEWAY_NAME} ({row['id']})")
            return str(row["id"])
    response = client.post("/gateways", headers=headers, json={"name": GATEWAY_NAME, "url": FAST_TIME_UPSTREAM, "transport": "STREAMABLEHTTP"})
    if response.status_code not in (200, 201):
        raise SystemExit(f"gateway registration failed: {response.status_code} {response.text[:200]}")
    gateway_id = response.json()["id"]
    log(f"federation gateway registered: {GATEWAY_NAME} ({gateway_id})")
    return str(gateway_id)


def wait_tool_sync(client: httpx.Client, headers: dict[str, str], gateway_id: str) -> list[str]:
    """Wait for the federated tool catalog and return the tool ids."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        tools = client.get("/tools", headers=headers).json()
        owned = [str(tool["id"]) for tool in tools if tool.get("gatewayId") == gateway_id]
        if owned:
            return owned
        time.sleep(2.0)
    raise SystemExit("fast-time tools never synced")


def ensure_virtual_server(client: httpx.Client, headers: dict[str, str], tool_ids: list[str]) -> str:
    """Create the demo virtual server and return its id."""
    servers = client.get("/servers", headers=headers).json()
    for row in servers:
        if row.get("name") == SERVER_NAME:
            server_id = str(row["id"])
            response = client.put(
                f"/servers/{server_id}",
                headers=headers,
                json={"name": SERVER_NAME, "description": "OpenFGA demo: fast-time tools behind the policy engine", "associated_tools": tool_ids},
            )
            if response.status_code not in (200, 201):
                raise SystemExit(f"virtual server tool refresh failed: {response.status_code} {response.text[:200]}")
            log(f"virtual server present: {SERVER_NAME} ({server_id}), tools refreshed ({len(tool_ids)})")
            return server_id
    response = client.post(
        "/servers",
        headers=headers,
        json={
            "server": {
                "name": SERVER_NAME,
                "description": "OpenFGA demo: fast-time tools behind the policy engine",
                "associated_tools": tool_ids,
            },
            "visibility": "public",
        },
    )
    if response.status_code not in (200, 201):
        raise SystemExit(f"virtual server creation failed: {response.status_code} {response.text[:200]}")
    server_id = response.json()["id"]
    log(f"virtual server created: {SERVER_NAME} ({server_id}) with {len(tool_ids)} tools")
    return str(server_id)


DEMO_TEAM_NAME = "OpenFGA Demo Team"


def ensure_developer_role(client: httpx.Client, headers: dict[str, str]) -> str:
    """Resolve the team-scoped developer role id for tool-execution grants."""
    roles = client.get("/rbac/roles", headers=headers).json()
    for role in roles:
        if role.get("name") == "developer" and role.get("scope") == "team":
            return str(role["id"])
    raise SystemExit("team-scoped developer role not found in the role catalog")


def ensure_demo_team(client: httpx.Client, headers: dict[str, str]) -> str:
    """Create the demo team that anchors the developer role grants."""
    raw = client.get("/teams/", headers=headers).json()
    teams = raw if isinstance(raw, list) else raw.get("teams", [])
    for team in teams:
        if team.get("name") == DEMO_TEAM_NAME:
            log(f"demo team present: {DEMO_TEAM_NAME} ({team['id']})")
            return str(team["id"])
    response = client.post("/teams/", headers=headers, json={"name": DEMO_TEAM_NAME, "description": "Anchor team for the OpenFGA demo role grants"})
    if response.status_code not in (200, 201):
        raise SystemExit(f"demo team creation failed: {response.status_code} {response.text[:200]}")
    team_id = response.json()["id"]
    log(f"demo team created: {DEMO_TEAM_NAME} ({team_id})")
    return str(team_id)


def ensure_membership(client: httpx.Client, headers: dict[str, str], team_id: str, email: str) -> None:
    """Add one demo user to the demo team."""
    response = client.post(f"/teams/{team_id}/members", headers=headers, json={"email": email, "role": "member"})
    if response.status_code not in (200, 201, 409):
        raise SystemExit(f"team membership failed for {email}: {response.status_code} {response.text[:200]}")


DEMO_ADMIN_ROLE = "demo-server-admin"
ADMIN_PERMISSIONS = [
    "servers.read",
    "servers.use",
    "servers.create",
    "servers.update",
    "servers.delete",
    "rbac.rules.manage",
    "tools.read",
    "tools.execute",
]


def assign_role(client: httpx.Client, headers: dict[str, str], email: str, role_id: str, team_id: str) -> None:
    """Grant one team-scoped role, skipping an assignment that exists.

    Args:
        client: HTTP client bound to the gateway.
        headers: Authorization headers for an admin session.
        email: User receiving the role.
        role_id: Role to assign.
        team_id: Team that scopes the assignment.
    """
    existing = client.get(f"/rbac/users/{email}/roles", headers=headers)
    if existing.status_code == 200:
        for row in existing.json():
            if str(row.get("role_id")) == role_id and row.get("scope") == "team" and str(row.get("scope_id")) == team_id:
                return
    assignment = client.post(f"/rbac/users/{email}/roles", headers=headers, json={"role_id": role_id, "scope": "team", "scope_id": team_id})
    if assignment.status_code not in (200, 201, 409):
        raise SystemExit(f"role assignment failed for {email}: {assignment.status_code} {assignment.text[:200]}")


def ensure_admin_role(client: httpx.Client, headers: dict[str, str]) -> Optional[str]:
    """Create the demo server-administrator role for policy management.

    Args:
        client: HTTP client bound to the gateway.
        headers: Authorization headers for an admin session.

    Returns:
        The role id, or None when the catalog already carries the role.
    """
    roles = client.get("/rbac/roles", headers=headers).json()
    for role in roles:
        if role.get("name") == DEMO_ADMIN_ROLE and role.get("scope") == "team":
            log(f"admin role present: {DEMO_ADMIN_ROLE} ({role['id']})")
            return None
    response = client.post(
        "/rbac/roles",
        headers=headers,
        json={"name": DEMO_ADMIN_ROLE, "description": "Demo server administrator: servers.* plus the policy rules API", "scope": "team", "permissions": ADMIN_PERMISSIONS},
    )
    if response.status_code not in (200, 201):
        raise SystemExit(f"admin role creation failed: {response.status_code} {response.text[:200]}")
    role_id = str(response.json()["id"])
    log(f"admin role created: {DEMO_ADMIN_ROLE} ({role_id})")
    return role_id


def ensure_admin_user(client: httpx.Client, headers: dict[str, str], email: str, admin_role_id: str, team_id: str) -> None:
    """Grant the demo administrator role to one user."""
    assign_role(client, headers, email, admin_role_id, team_id)
    log(f"role assigned: {DEMO_ADMIN_ROLE} -> {email}")


def ensure_user(client: httpx.Client, headers: dict[str, str], name: str, role_id: str, team_id: str) -> None:
    """Create one non-administrative demo user with tool execution.

    The built-in default role carries tools.read only, and token scope
    containment refuses to mint a key that carries a permission the
    caller lacks. The developer role adds tools.execute, so each demo
    user can run fast-time tools through a scoped key.
    """
    email = f"{name}@demo.example.com"
    response = client.post(
        "/auth/email/admin/users",
        headers=headers,
        json={
            "email": email,
            "password": DEMO_PASSWORD,
            "full_name": name.capitalize(),
            "is_admin": False,
            "is_active": True,
            "password_change_required": False,
        },
    )
    if response.status_code not in (200, 201, 409):
        raise SystemExit(f"user creation failed for {email}: {response.status_code} {response.text[:200]}")
    log(f"user ready: {email} (non-admin)")
    ensure_membership(client, headers, team_id, email)
    assign_role(client, headers, email, role_id, team_id)
    log(f"role assigned: developer (team) -> {email}")


def main() -> None:
    """Run every seeding step and print the summary."""
    if not ADMIN_PASSWORD:
        raise SystemExit("PLATFORM_ADMIN_PASSWORD is required")
    client = httpx.Client(base_url=GATEWAY_URL, timeout=30.0)
    wait_healthy(client)
    admin_token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {admin_token}"}

    gateway_id = ensure_federation_gateway(client, headers)
    tool_ids = wait_tool_sync(client, headers, gateway_id)
    server_id = ensure_virtual_server(client, headers, tool_ids)
    role_id = ensure_developer_role(client, headers)
    team_id = ensure_demo_team(client, headers)
    for name in USERS:
        ensure_user(client, headers, name, role_id, team_id)
    admin_role_id = ensure_admin_role(client, headers)
    if admin_role_id:
        ensure_admin_user(client, headers, "david@demo.example.com", admin_role_id, team_id)

    print("[demo-seed] summary")
    print(f"[demo-seed]   gateway url      {GATEWAY_URL}")
    print(f"[demo-seed]   virtual server   {SERVER_NAME} ({server_id})")
    print(f"[demo-seed]   users            {', '.join(f'{u}@demo.example.com' for u in USERS)}")
    print("[demo-seed] next: BOBSHELL_API_KEY=<key> demos/openfga/bob-chat.sh mints per-user API keys and opens the tmux chat")


if __name__ == "__main__":
    main()
