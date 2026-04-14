# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""OWASP A01 test fixtures for cross-user and cross-tenant access control tests."""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
import os
from typing import Generator
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
TEST_PASSWORD = "SecureTestPass123!"


def _make_jwt(email: str, *, is_admin: bool, teams: list[str] | None = None, expires_in_minutes: int = 30) -> str:
    """Create a JWT token for OWASP A01 testing with a short-lived expiry."""
    return _create_jwt_token(
        {"sub": email},
        expires_in_minutes=expires_in_minutes,
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
    )


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    """Create a Playwright API request context with Bearer auth."""
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


@pytest.fixture(scope="module")
def owasp_anon_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Unauthenticated API context for force-browsing tests."""
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def owasp_admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context for OWASP A01 tests (admin bypass via teams=null).

    Prefers the ``MCP_AUTH`` env var (set by the Makefile from a token signed with
    the running gateway's secret) so signatures match the deployed instance. Falls
    back to a locally-signed JWT only when ``MCP_AUTH`` is unset.
    """
    token = os.getenv("MCP_AUTH", "") or _make_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture
def owasp_user_a_api(owasp_admin_api: APIRequestContext, playwright: Playwright):
    """Non-admin API context for User A, registered in the system. Cleans up after test."""
    email = f"owasp-a-{uuid.uuid4().hex[:8]}@example.com"
    create_resp = owasp_admin_api.post(
        "/auth/email/admin/users",
        data={"email": email, "password": TEST_PASSWORD, "full_name": "OWASP User A"},
    )
    assert create_resp.status in (200, 201), f"Failed to create User A: {create_resp.status} {create_resp.text()}"

    token = _make_jwt(email, is_admin=False, teams=[])
    ctx = _api_context(playwright, token)
    yield {"ctx": ctx, "email": email}
    ctx.dispose()
    with suppress(Exception):
        owasp_admin_api.delete(f"/auth/email/admin/users/{email}")


@pytest.fixture
def owasp_user_b_api(owasp_admin_api: APIRequestContext, playwright: Playwright):
    """Non-admin API context for User B, registered in the system. Cleans up after test."""
    email = f"owasp-b-{uuid.uuid4().hex[:8]}@example.com"
    create_resp = owasp_admin_api.post(
        "/auth/email/admin/users",
        data={"email": email, "password": TEST_PASSWORD, "full_name": "OWASP User B"},
    )
    assert create_resp.status in (200, 201), f"Failed to create User B: {create_resp.status} {create_resp.text()}"

    token = _make_jwt(email, is_admin=False, teams=[])
    ctx = _api_context(playwright, token)
    yield {"ctx": ctx, "email": email}
    ctx.dispose()
    with suppress(Exception):
        owasp_admin_api.delete(f"/auth/email/admin/users/{email}")


@pytest.fixture
def two_teams_setup(owasp_admin_api: APIRequestContext, playwright: Playwright):
    """Create two distinct teams with separate scoped tokens. Cleans up after test."""
    suffix = uuid.uuid4().hex[:8]
    team_a_id: str | None = None
    team_b_id: str | None = None
    server_a_id: str | None = None
    server_b_id: str | None = None
    ctx_a = None
    ctx_b = None
    try:
        # Team A
        resp_a = owasp_admin_api.post("/teams/", data={"name": f"owasp-team-a-{suffix}", "description": "OWASP Team A", "visibility": "private"})
        assert resp_a.status in (200, 201), f"Failed creating Team A: {resp_a.status} {resp_a.text()}"
        team_a_id = resp_a.json()["id"]

        # Team B
        resp_b = owasp_admin_api.post("/teams/", data={"name": f"owasp-team-b-{suffix}", "description": "OWASP Team B", "visibility": "private"})
        assert resp_b.status in (200, 201), f"Failed creating Team B: {resp_b.status} {resp_b.text()}"
        team_b_id = resp_b.json()["id"]

        # Server owned by Team A
        srv_a = owasp_admin_api.post(
            "/servers",
            data={"server": {"name": f"owasp-srv-a-{suffix}", "description": "Team A server"}, "team_id": team_a_id, "visibility": "team"},
        )
        assert srv_a.status in (200, 201), f"Failed creating Team A server: {srv_a.status} {srv_a.text()}"
        server_a_id = srv_a.json()["id"]

        # Server owned by Team B
        srv_b = owasp_admin_api.post(
            "/servers",
            data={"server": {"name": f"owasp-srv-b-{suffix}", "description": "Team B server"}, "team_id": team_b_id, "visibility": "team"},
        )
        assert srv_b.status in (200, 201), f"Failed creating Team B server: {srv_b.status} {srv_b.text()}"
        server_b_id = srv_b.json()["id"]

        # Token scoped to Team A only
        ctx_a = _api_context(playwright, _make_jwt("owasp-tenant-a@example.com", is_admin=False, teams=[team_a_id]))
        # Token scoped to Team B only
        ctx_b = _api_context(playwright, _make_jwt("owasp-tenant-b@example.com", is_admin=False, teams=[team_b_id]))

        yield {
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "server_a_id": server_a_id,
            "server_b_id": server_b_id,
            "ctx_team_a": ctx_a,
            "ctx_team_b": ctx_b,
        }
    finally:
        if ctx_a:
            ctx_a.dispose()
        if ctx_b:
            ctx_b.dispose()
        if server_a_id:
            with suppress(Exception):
                owasp_admin_api.delete(f"/servers/{server_a_id}")
        if server_b_id:
            with suppress(Exception):
                owasp_admin_api.delete(f"/servers/{server_b_id}")
        if team_a_id:
            with suppress(Exception):
                owasp_admin_api.delete(f"/teams/{team_a_id}")
        if team_b_id:
            with suppress(Exception):
                owasp_admin_api.delete(f"/teams/{team_b_id}")


@pytest.fixture
def private_server_owned_by_user_a(owasp_admin_api: APIRequestContext, owasp_user_a_api: dict):
    """Create a private server via admin on behalf of User A and return its ID. Cleans up after test."""
    server_id: str | None = None
    try:
        resp = owasp_admin_api.post(
            "/servers",
            data={
                "server": {"name": f"owasp-priv-{uuid.uuid4().hex[:8]}", "description": "User A private server"},
                "team_id": None,
                "visibility": "private",
                "owner_email": owasp_user_a_api["email"],
            },
        )
        assert resp.status in (200, 201), f"Failed creating private server: {resp.status} {resp.text()}"
        server_id = resp.json()["id"]
        yield server_id
    finally:
        if server_id:
            with suppress(Exception):
                owasp_admin_api.delete(f"/servers/{server_id}")
