# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Token team-claim matrix and scope-containment coverage."""

# Future
from __future__ import annotations

# Standard
from contextlib import suppress
from typing import Any
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from .conftest import BASE_URL, TEST_PASSWORD

_UNSET = object()


def _extract_token_id(response_json: dict[str, Any]) -> str | None:
    token_obj = response_json.get("token", response_json)
    return token_obj.get("id") or token_obj.get("token_id")


def _extract_servers(response_json: Any) -> list[dict[str, Any]]:
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        maybe_servers = response_json.get("servers")
        if isinstance(maybe_servers, list):
            return maybe_servers
    return []


def _make_jwt(
    email: str,
    *,
    is_admin: bool,
    teams: object = _UNSET,
    scopes: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"sub": email}
    if teams is not _UNSET:
        payload["teams"] = teams
    return _create_jwt_token(
        payload,
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        scopes=scopes,
    )


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def _create_server(admin_api: APIRequestContext, name: str, visibility: str, team_id: str | None = None) -> str:
    response = admin_api.post(
        "/servers",
        data={
            "server": {"name": name, "description": "playwright security test"},
            "team_id": team_id,
            "visibility": visibility,
        },
    )
    assert response.status in (200, 201), f"Failed to create server ({visibility}): {response.status} {response.text()}"
    return response.json()["id"]


@pytest.fixture
def scope_matrix_resources(playwright: Playwright):
    admin_ctx = _api_context(playwright, _make_jwt("admin@example.com", is_admin=True, teams=None))
    team_id: str | None = None
    public_server_id: str | None = None
    team_server_id: str | None = None
    try:
        team_name = f"scope-matrix-team-{uuid.uuid4().hex[:8]}"
        team_resp = admin_ctx.post("/teams/", data={"name": team_name, "description": "scope matrix team", "visibility": "private"})
        assert team_resp.status in (200, 201), f"Failed to create team: {team_resp.status} {team_resp.text()}"
        team_id = team_resp.json()["id"]

        public_server_id = _create_server(admin_ctx, f"scope-public-{uuid.uuid4().hex[:8]}", visibility="public")
        team_server_id = _create_server(admin_ctx, f"scope-team-{uuid.uuid4().hex[:8]}", visibility="team", team_id=team_id)

        yield {"team_id": team_id, "public_server_id": public_server_id, "team_server_id": team_server_id}
    finally:
        if team_server_id:
            with suppress(Exception):
                admin_ctx.delete(f"/servers/{team_server_id}")
        if public_server_id:
            with suppress(Exception):
                admin_ctx.delete(f"/servers/{public_server_id}")
        if team_id:
            with suppress(Exception):
                admin_ctx.delete(f"/teams/{team_id}")
        admin_ctx.dispose()


class TestTokenTeamsMatrix:
    """Cover secure-first team normalization behaviors from token claims."""

    def test_teams_claim_matrix_controls_visibility(self, playwright: Playwright, scope_matrix_resources: dict[str, str]):
        team_id = scope_matrix_resources["team_id"]
        public_server_id = scope_matrix_resources["public_server_id"]
        team_server_id = scope_matrix_resources["team_server_id"]

        tokens = {
            # Missing teams key -> public-only
            "teams_missing": _make_jwt("admin@example.com", is_admin=True),
            # Explicit empty teams -> public-only
            "teams_empty": _make_jwt("admin@example.com", is_admin=True, teams=[]),
            # Explicit null teams + admin=true -> unrestricted admin bypass
            "teams_null_admin_true": _make_jwt("admin@example.com", is_admin=True, teams=None),
            # Explicit null teams + admin=false -> public-only
            "teams_null_admin_false": _make_jwt("admin@example.com", is_admin=False, teams=None),
            # Team-scoped token -> public + team
            "teams_scoped": _make_jwt("admin@example.com", is_admin=False, teams=[team_id]),
        }

        results: dict[str, set[str]] = {}
        contexts: list[APIRequestContext] = []
        try:
            for case, token in tokens.items():
                ctx = _api_context(playwright, token)
                contexts.append(ctx)
                response = ctx.get("/servers")
                assert response.status == 200, f"{case} failed listing servers: {response.status} {response.text()}"
                results[case] = {item["id"] for item in _extract_servers(response.json())}
        finally:
            for ctx in contexts:
                ctx.dispose()

        assert public_server_id in results["teams_missing"]
        assert team_server_id not in results["teams_missing"]

        assert public_server_id in results["teams_empty"]
        assert team_server_id not in results["teams_empty"]

        assert public_server_id in results["teams_null_admin_true"]
        assert team_server_id in results["teams_null_admin_true"]

        assert public_server_id in results["teams_null_admin_false"]
        assert team_server_id not in results["teams_null_admin_false"]

        assert public_server_id in results["teams_scoped"]
        assert team_server_id in results["teams_scoped"]

    def test_non_admin_cannot_delegate_permissions_they_do_not_have(self, admin_api: APIRequestContext, playwright: Playwright):
        email = f"scope-nonadmin-{uuid.uuid4().hex[:8]}@example.com"
        create_user_resp = admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Scope Non Admin"},
        )
        assert create_user_resp.status in (200, 201), f"Failed to create test user: {create_user_resp.status} {create_user_resp.text()}"

        user_ctx = _api_context(playwright, _make_jwt(email, is_admin=False, teams=[]))
        baseline_token_id: str | None = None
        blocked_token_id: str | None = None
        try:
            # Verify token creation is otherwise allowed for this user.
            baseline_resp = user_ctx.post(
                "/tokens",
                data={
                    "name": f"baseline-token-{uuid.uuid4().hex[:8]}",
                    "expires_in_days": 1,
                },
            )
            assert baseline_resp.status in (200, 201), f"Expected unscoped token creation to succeed, got {baseline_resp.status}: {baseline_resp.text()}"
            baseline_token_id = _extract_token_id(baseline_resp.json())

            # Pick a valid permission the user does not currently hold to test scope containment.
            my_perms_resp = user_ctx.get("/rbac/my/permissions")
            assert my_perms_resp.status == 200, f"Failed reading caller permissions: {my_perms_resp.status} {my_perms_resp.text()}"
            my_permissions = set(my_perms_resp.json())

            all_perms_resp = user_ctx.get("/rbac/permissions/available")
            assert all_perms_resp.status == 200, f"Failed reading available permissions: {all_perms_resp.status} {all_perms_resp.text()}"
            available_permissions = [perm for perm in all_perms_resp.json().get("all_permissions", []) if perm != "*"]
            disallowed_permission = next((perm for perm in available_permissions if perm not in my_permissions), None)
            if not disallowed_permission:
                pytest.skip("Environment grants all available permissions to non-admin test user; cannot validate scope containment.")

            response = user_ctx.post(
                "/tokens",
                data={
                    "name": f"disallowed-scope-{uuid.uuid4().hex[:8]}",
                    "expires_in_days": 1,
                    "scope": {"permissions": [disallowed_permission]},
                },
            )
            if response.status in (200, 201):
                blocked_token_id = _extract_token_id(response.json())
            assert response.status == 400, f"Expected scope containment rejection, got {response.status}: {response.text()}"
        finally:
            user_ctx.dispose()
            if baseline_token_id:
                with suppress(Exception):
                    admin_api.delete(f"/tokens/{baseline_token_id}")
            if blocked_token_id:
                with suppress(Exception):
                    admin_api.delete(f"/tokens/{blocked_token_id}")
            with suppress(Exception):
                admin_api.delete(f"/auth/email/admin/users/{email}")

    def test_token_scope_permissions_restrict_runtime_operations(self, admin_api: APIRequestContext, playwright: Playwright):
        token_name = f"limited-scope-{uuid.uuid4().hex[:8]}"
        create_token_resp = admin_api.post(
            "/tokens",
            data={
                "name": token_name,
                "expires_in_days": 1,
                "scope": {"permissions": ["servers.read"]},
            },
        )
        assert create_token_resp.status in (200, 201), f"Failed creating scoped token: {create_token_resp.status} {create_token_resp.text()}"
        payload = create_token_resp.json()
        access_token = payload["access_token"]
        token_id = _extract_token_id(payload)

        limited_ctx = _api_context(playwright, access_token)
        created_server_id: str | None = None
        try:
            read_resp = limited_ctx.get("/servers")
            assert read_resp.status == 200, f"servers.read should succeed: {read_resp.status} {read_resp.text()}"

            create_resp = limited_ctx.post(
                "/servers",
                data={
                    "server": {"name": f"should-not-create-{uuid.uuid4().hex[:8]}", "description": "scope restriction check"},
                    "team_id": None,
                    "visibility": "public",
                },
            )
            if create_resp.status in (200, 201):
                created_server_id = create_resp.json().get("id")
            assert create_resp.status == 403, f"Expected create blocked by token scope, got {create_resp.status} {create_resp.text()}"
        finally:
            limited_ctx.dispose()
            if created_server_id:
                with suppress(Exception):
                    admin_api.delete(f"/servers/{created_server_id}")
            if token_id:
                with suppress(Exception):
                    admin_api.delete(f"/tokens/{token_id}")
