# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for team collaboration E2E tests."""

# Future
from __future__ import annotations

# Standard
import logging
import os
from typing import Generator
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
TEST_PASSWORD = "SecureTestPass123!"


_UNSET = object()


def _make_jwt(email: str, is_admin: bool = False, teams=_UNSET) -> str:
    """Create a JWT token for testing.

    For admin users, ``teams`` must be explicitly ``null`` in the JWT payload
    (not missing) for the admin bypass in ``normalize_token_teams`` to work.
    When ``teams`` is not provided (sentinel), admin users get ``null`` and
    non-admin users get the key omitted entirely (public-only default).
    """
    data: dict = {"sub": email}
    if teams is not _UNSET:
        # Explicit value provided — pass through to _create_jwt_token
        return _create_jwt_token(data, user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"}, teams=teams)
    if is_admin:
        # Admin bypass requires "teams": null in payload (present but null)
        data["teams"] = None
    return _create_jwt_token(data, user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"})


def create_test_user(admin_api: APIRequestContext, email: str) -> bool:
    """Create a test user in the database. Returns True on success or already-exists."""
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={"email": email, "password": TEST_PASSWORD, "full_name": f"Test User {email.split('@')[0]}"},
    )
    return resp.status in (200, 201, 409)


def delete_test_user(admin_api: APIRequestContext, email: str) -> None:
    """Delete a test user (best-effort, may fail if user has team memberships)."""
    try:
        admin_api.delete(f"/auth/email/admin/users/{email}")
    except Exception:
        pass


def invite_and_accept(admin_api: APIRequestContext, playwright: Playwright, team_id: str, email: str) -> dict:
    """Invite a user to a team and accept the invitation. Returns the invitation data."""
    inv_resp = admin_api.post(f"/teams/{team_id}/invitations", data={"email": email, "role": "member"})
    assert inv_resp.status in (200, 201), f"Failed to invite {email}: {inv_resp.status} {inv_resp.text()}"
    inv_data = inv_resp.json()
    invitation_token = inv_data["token"]

    # Accept as the invited user
    user_jwt = _make_jwt(email, is_admin=False)
    user_ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {user_jwt}", "Accept": "application/json"},
    )
    accept_resp = user_ctx.post(f"/teams/invitations/{invitation_token}/accept")
    user_ctx.dispose()
    assert accept_resp.status == 200, f"Failed to accept invitation: {accept_resp.status}"
    return inv_data


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context for team tests."""
    token = _make_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def private_team(admin_api: APIRequestContext):
    """Create a private team for invitation tests, cleanup after module."""
    team_name = f"priv-team-{uuid.uuid4().hex[:8]}"
    resp = admin_api.post("/teams/", data={"name": team_name, "description": "E2E invite tests", "visibility": "private"})
    assert resp.status in (200, 201), f"Failed to create private team: {resp.status}"
    team = resp.json()
    yield team
    try:
        admin_api.delete(f"/teams/{team['id']}")
    except Exception:
        pass


@pytest.fixture(scope="module")
def public_team(admin_api: APIRequestContext):
    """Create a public team for join request tests, cleanup after module."""
    team_name = f"pub-team-{uuid.uuid4().hex[:8]}"
    resp = admin_api.post("/teams/", data={"name": team_name, "description": "E2E join tests", "visibility": "public"})
    assert resp.status in (200, 201), f"Failed to create public team: {resp.status}"
    team = resp.json()
    yield team
    try:
        admin_api.delete(f"/teams/{team['id']}")
    except Exception:
        pass
