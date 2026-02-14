# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""API abuse hardening tests: mass assignment, BOLA, HPP, XSS, and path traversal."""

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


def _make_jwt(email: str, *, is_admin: bool, teams: object = _UNSET) -> str:
    payload: dict[str, Any] = {"sub": email}
    if teams is not _UNSET:
        payload["teams"] = teams
    return _create_jwt_token(
        payload,
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
    )


def _api_context(playwright: Playwright, token: str) -> APIRequestContext:
    return playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


@pytest.fixture
def hpp_servers(playwright: Playwright):
    admin_ctx = _api_context(playwright, _make_jwt("admin@example.com", is_admin=True, teams=None))
    team_id: str | None = None
    public_server_id: str | None = None
    team_server_id: str | None = None
    try:
        team_resp = admin_ctx.post(
            "/teams/",
            data={"name": f"hpp-team-{uuid.uuid4().hex[:8]}", "description": "HPP test team", "visibility": "private"},
        )
        assert team_resp.status in (200, 201), f"Failed creating team for HPP test: {team_resp.status} {team_resp.text()}"
        team_id = team_resp.json()["id"]

        public_server_resp = admin_ctx.post(
            "/servers",
            data={"server": {"name": f"hpp-public-{uuid.uuid4().hex[:8]}"}, "team_id": None, "visibility": "public"},
        )
        team_server_resp = admin_ctx.post(
            "/servers",
            data={"server": {"name": f"hpp-team-{uuid.uuid4().hex[:8]}"}, "team_id": team_id, "visibility": "team"},
        )
        assert public_server_resp.status in (200, 201), f"Failed creating public server: {public_server_resp.status} {public_server_resp.text()}"
        assert team_server_resp.status in (200, 201), f"Failed creating team server: {team_server_resp.status} {team_server_resp.text()}"

        public_server_id = public_server_resp.json()["id"]
        team_server_id = team_server_resp.json()["id"]

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


class TestAPISecurityAbuseCases:
    """Coverage for high-priority API abuse vectors from manual security plans."""

    def test_mass_assignment_cannot_override_token_owner(self, admin_api: APIRequestContext):
        token_name = f"mass-assign-{uuid.uuid4().hex[:8]}"
        response = admin_api.post(
            "/tokens",
            data={
                "name": token_name,
                "expires_in_days": 1,
                "user_email": "victim@example.com",
                "is_admin": True,
            },
        )

        token_id: str | None = None
        if response.status in (200, 201):
            body = response.json()
            token_id = _extract_token_id(body)
            token_obj = body.get("token", body)
            assert token_obj.get("user_email") == "admin@example.com"
        else:
            assert response.status == 422, f"Unexpected response for mass-assignment probe: {response.status} {response.text()}"

        if token_id:
            with suppress(Exception):
                admin_api.delete(f"/tokens/{token_id}")

    def test_bola_user_cannot_read_or_revoke_another_users_token(self, admin_api: APIRequestContext, playwright: Playwright):
        email_a = f"bola-a-{uuid.uuid4().hex[:8]}@example.com"
        email_b = f"bola-b-{uuid.uuid4().hex[:8]}@example.com"

        created_token_id: str | None = None
        ctx_a = None
        ctx_b = None
        try:
            for email in (email_a, email_b):
                create_user_resp = admin_api.post(
                    "/auth/email/admin/users",
                    data={"email": email, "password": TEST_PASSWORD, "full_name": "BOLA Test User"},
                )
                assert create_user_resp.status in (200, 201), f"Failed creating {email}: {create_user_resp.status} {create_user_resp.text()}"

            ctx_a = _api_context(playwright, _make_jwt(email_a, is_admin=False, teams=[]))
            ctx_b = _api_context(playwright, _make_jwt(email_b, is_admin=False, teams=[]))

            create_token_resp = ctx_a.post(
                "/tokens",
                data={"name": f"bola-token-{uuid.uuid4().hex[:8]}", "expires_in_days": 1},
            )
            assert create_token_resp.status in (200, 201), f"User A failed to create token: {create_token_resp.status} {create_token_resp.text()}"
            created_token_id = _extract_token_id(create_token_resp.json())
            assert created_token_id

            read_other_resp = ctx_b.get(f"/tokens/{created_token_id}")
            revoke_other_resp = ctx_b.delete(f"/tokens/{created_token_id}")

            assert read_other_resp.status in (403, 404), f"User B should not read User A token: {read_other_resp.status} {read_other_resp.text()}"
            assert revoke_other_resp.status in (403, 404), f"User B should not revoke User A token: {revoke_other_resp.status} {revoke_other_resp.text()}"
        finally:
            if ctx_a:
                if created_token_id:
                    with suppress(Exception):
                        ctx_a.delete(f"/tokens/{created_token_id}")
                ctx_a.dispose()
            if ctx_b:
                ctx_b.dispose()
            with suppress(Exception):
                admin_api.delete(f"/auth/email/admin/users/{email_a}")
            with suppress(Exception):
                admin_api.delete(f"/auth/email/admin/users/{email_b}")

    def test_query_parameter_pollution_does_not_bypass_public_only_scope(self, hpp_servers: dict[str, str], playwright: Playwright):
        public_only_token = _make_jwt("admin@example.com", is_admin=True)
        ctx = _api_context(playwright, public_only_token)
        try:
            response = ctx.get("/servers?visibility=public&visibility=team")
            status_code = response.status
            payload = response.json()
        finally:
            ctx.dispose()

        assert status_code == 200, f"Unexpected status for HPP probe: {status_code}"
        ids = {server["id"] for server in _extract_servers(payload)}
        assert hpp_servers["team_server_id"] not in ids, "Public-only token must never obtain team-scoped resources via duplicate query params"

    def test_xss_payload_in_server_name_is_rejected_or_sanitized(self, admin_api: APIRequestContext):
        response = admin_api.post(
            "/servers",
            data={
                "server": {"name": '<script>alert("xss")</script>', "description": "xss probe"},
                "team_id": None,
                "visibility": "public",
            },
        )

        created_server_id: str | None = None
        if response.status in (200, 201):
            body = response.json()
            created_server_id = body.get("id")
            assert "<script>" not in (body.get("name", "")).lower()
        else:
            assert response.status in (400, 422), f"Unexpected XSS probe response: {response.status} {response.text()}"

        if created_server_id:
            with suppress(Exception):
                admin_api.delete(f"/servers/{created_server_id}")

    def test_path_traversal_payload_in_resource_uri_is_rejected(self, admin_api: APIRequestContext):
        response = admin_api.post(
            "/resources",
            data={
                "resource": {"uri": "../../etc/passwd", "name": f"traversal-{uuid.uuid4().hex[:8]}", "content": "probe"},
                "team_id": None,
                "visibility": "private",
            },
        )

        if response.status in (200, 201):
            body = response.json()
            assert ".." not in str(body.get("uri", "")), "Path traversal sequences should not persist in stored URI"
            created_id = body.get("id")
            if created_id:
                with suppress(Exception):
                    admin_api.delete(f"/resources/{created_id}")
            pytest.fail("Traversal payload unexpectedly accepted without normalization/rejection")

        assert response.status in (400, 422), f"Traversal payload should be rejected, got {response.status}: {response.text()}"
