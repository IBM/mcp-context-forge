# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Team Join Request E2E Tests.

Tests the join request workflow: request, list, approve, reject.
Join requests only work for public-visibility teams.
"""

# Future
from __future__ import annotations

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright

# Local
from .conftest import _make_jwt, BASE_URL, create_test_user, delete_test_user

logger = logging.getLogger(__name__)


class TestTeamJoinRequests:
    """Test team join request workflow."""

    def _make_join_request(self, playwright: Playwright, team_id: str, email: str) -> dict:
        """Submit a join request as the given user. Returns the request data."""
        user_jwt = _make_jwt(email, is_admin=False)
        user_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {user_jwt}", "Accept": "application/json"},
        )
        resp = user_ctx.post(f"/teams/{team_id}/join", data={"message": "Please let me join"})
        status = resp.status
        data = resp.json()
        user_ctx.dispose()
        assert status == 200, f"Join request failed: {status}"
        return data

    def test_request_to_join_public_team(self, admin_api: APIRequestContext, public_team: dict, playwright: Playwright):
        """User can request to join a public team."""
        email = f"join-req-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)

        req_data = self._make_join_request(playwright, public_team["id"], email)
        assert req_data["status"] == "pending"
        assert req_data["user_email"] == email

        # Cleanup: reject the request (by deleting it)
        admin_api.delete(f"/teams/{public_team['id']}/join-requests/{req_data['id']}")
        delete_test_user(admin_api, email)

    def test_list_join_requests(self, admin_api: APIRequestContext, public_team: dict, playwright: Playwright):
        """Team owner can list pending join requests."""
        email = f"join-list-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)
        req_data = self._make_join_request(playwright, public_team["id"], email)

        resp = admin_api.get(f"/teams/{public_team['id']}/join-requests")
        assert resp.status == 200
        requests = resp.json()
        assert isinstance(requests, list)
        req_emails = [r["user_email"] for r in requests]
        assert email in req_emails

        # Cleanup
        admin_api.delete(f"/teams/{public_team['id']}/join-requests/{req_data['id']}")
        delete_test_user(admin_api, email)

    def test_approve_join_request(self, admin_api: APIRequestContext, public_team: dict, playwright: Playwright):
        """Team owner can approve a join request, making the user a member."""
        email = f"join-approve-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)
        req_data = self._make_join_request(playwright, public_team["id"], email)

        # Approve
        approve_resp = admin_api.post(f"/teams/{public_team['id']}/join-requests/{req_data['id']}/approve")
        assert approve_resp.status == 200

        # Verify user is now a member
        members_resp = admin_api.get(f"/teams/{public_team['id']}/members")
        members = members_resp.json()
        member_list = members if isinstance(members, list) else members.get("members", [])
        member_emails = [m["user_email"] for m in member_list]
        assert email in member_emails

        # Cleanup
        admin_api.delete(f"/teams/{public_team['id']}/members/{email}")
        delete_test_user(admin_api, email)

    def test_private_team_join_request_denied(self, admin_api: APIRequestContext, private_team: dict, playwright: Playwright):
        """Users cannot request to join private teams."""
        email = f"join-priv-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)

        user_jwt = _make_jwt(email, is_admin=False)
        user_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {user_jwt}", "Accept": "application/json"},
        )
        resp = user_ctx.post(f"/teams/{private_team['id']}/join", data={"message": "Let me in"})
        user_ctx.dispose()
        assert resp.status == 403, f"Private team join should be denied, got {resp.status}"

        delete_test_user(admin_api, email)
