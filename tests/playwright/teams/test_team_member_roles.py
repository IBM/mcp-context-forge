# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Team Member Role E2E Tests.

Tests member role changes, member removal, and leaving teams.
Team roles are "owner" or "member" (distinct from RBAC roles).
"""

# Future
from __future__ import annotations

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# Local
from .conftest import _make_jwt, BASE_URL, create_test_user, delete_test_user, invite_and_accept

logger = logging.getLogger(__name__)


class TestTeamMemberRoles:
    """Test team member role changes and member management."""

    @pytest.fixture
    def team_with_member(self, admin_api: APIRequestContext, playwright: Playwright):
        """Create a team with a member, yield both, cleanup after test."""
        team_name = f"role-team-{uuid.uuid4().hex[:8]}"
        team_resp = admin_api.post("/teams/", data={"name": team_name, "description": "Role tests", "visibility": "private"})
        assert team_resp.status in (200, 201)
        team = team_resp.json()

        member_email = f"role-member-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, member_email)
        invite_and_accept(admin_api, playwright, team["id"], member_email)

        yield {"team": team, "member_email": member_email}

        # Cleanup
        try:
            admin_api.delete(f"/teams/{team['id']}/members/{member_email}")
        except Exception:
            pass
        try:
            admin_api.delete(f"/teams/{team['id']}")
        except Exception:
            pass
        delete_test_user(admin_api, member_email)

    def test_update_member_role_to_owner(self, admin_api: APIRequestContext, team_with_member: dict):
        """Team owner can promote a member to owner."""
        team_id = team_with_member["team"]["id"]
        member = team_with_member["member_email"]

        resp = admin_api.put(
            f"/teams/{team_id}/members/{member}",
            data={"role": "owner"},
        )
        assert resp.status == 200
        updated = resp.json()
        assert updated["role"] == "owner"

    def test_demote_owner_to_member(self, admin_api: APIRequestContext, team_with_member: dict):
        """Team owner can demote another owner back to member."""
        team_id = team_with_member["team"]["id"]
        member = team_with_member["member_email"]

        # First promote to owner
        admin_api.put(f"/teams/{team_id}/members/{member}", data={"role": "owner"})

        # Then demote back to member
        resp = admin_api.put(f"/teams/{team_id}/members/{member}", data={"role": "member"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["role"] == "member"

    def test_remove_member(self, admin_api: APIRequestContext, team_with_member: dict):
        """Team owner can remove a member from the team."""
        team_id = team_with_member["team"]["id"]
        member = team_with_member["member_email"]

        resp = admin_api.delete(f"/teams/{team_id}/members/{member}")
        assert resp.status == 200

        # Verify member is removed
        members_resp = admin_api.get(f"/teams/{team_id}/members")
        members = members_resp.json()
        member_list = members if isinstance(members, list) else members.get("members", [])
        member_emails = [m["user_email"] for m in member_list]
        assert member not in member_emails

    def test_member_leaves_team(self, admin_api: APIRequestContext, team_with_member: dict, playwright: Playwright):
        """A member can voluntarily leave a team."""
        team_id = team_with_member["team"]["id"]
        member = team_with_member["member_email"]

        # Leave as the member
        member_jwt = _make_jwt(member, is_admin=False)
        member_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {member_jwt}", "Accept": "application/json"},
        )
        resp = member_ctx.delete(f"/teams/{team_id}/leave")
        member_ctx.dispose()
        assert resp.status == 200

    def test_list_team_members(self, admin_api: APIRequestContext, team_with_member: dict):
        """Team owner can list all team members."""
        team_id = team_with_member["team"]["id"]

        resp = admin_api.get(f"/teams/{team_id}/members")
        assert resp.status == 200
        members = resp.json()
        member_list = members if isinstance(members, list) else members.get("members", [])
        assert len(member_list) >= 2  # owner + added member

    def test_non_owner_cannot_change_roles(self, admin_api: APIRequestContext, team_with_member: dict, playwright: Playwright):
        """A regular member cannot change other members' roles."""
        team_id = team_with_member["team"]["id"]
        member = team_with_member["member_email"]

        # Add a second member
        second_email = f"second-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, second_email)
        invite_and_accept(admin_api, playwright, team_id, second_email)

        # Try to change role as the first member (non-owner)
        member_jwt = _make_jwt(member, is_admin=False)
        member_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {member_jwt}", "Accept": "application/json"},
        )
        resp = member_ctx.put(f"/teams/{team_id}/members/{second_email}", data={"role": "owner"})
        member_ctx.dispose()
        assert resp.status in (403, 422), f"Non-owner should be denied role change, got {resp.status}"

        # Cleanup
        admin_api.delete(f"/teams/{team_id}/members/{second_email}")
        delete_test_user(admin_api, second_email)
