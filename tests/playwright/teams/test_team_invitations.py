# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Team Invitation E2E Tests.

Tests the invitation workflow: send, list, accept, cancel, and permission checks.
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


class TestTeamInvitations:
    """Test team invitation send/accept/cancel workflow."""

    def test_send_invitation(self, admin_api: APIRequestContext, private_team: dict):
        """Team owner can send an invitation to a user."""
        email = f"invite-send-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)

        resp = admin_api.post(
            f"/teams/{private_team['id']}/invitations",
            data={"email": email, "role": "member"},
        )
        assert resp.status in (200, 201)
        inv = resp.json()
        assert inv["email"] == email
        assert inv["role"] == "member"
        assert inv["token"], "Invitation should include a token"
        assert inv["is_active"] is True

        # Cleanup
        admin_api.delete(f"/teams/invitations/{inv['id']}")
        delete_test_user(admin_api, email)

    def test_list_pending_invitations(self, admin_api: APIRequestContext, private_team: dict):
        """Team owner can list pending invitations."""
        email = f"invite-list-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)
        inv_resp = admin_api.post(f"/teams/{private_team['id']}/invitations", data={"email": email, "role": "member"})
        assert inv_resp.status in (200, 201), f"Failed to create invitation: {inv_resp.status} {inv_resp.text()}"

        resp = admin_api.get(f"/teams/{private_team['id']}/invitations")
        assert resp.status == 200
        invitations = resp.json()
        assert isinstance(invitations, list)
        emails = [i["email"] for i in invitations]
        assert email in emails

        # Cleanup
        inv_id = next(i["id"] for i in invitations if i["email"] == email)
        admin_api.delete(f"/teams/invitations/{inv_id}")
        delete_test_user(admin_api, email)

    def test_accept_invitation(self, admin_api: APIRequestContext, private_team: dict, playwright: Playwright):
        """Invited user can accept an invitation and become a team member."""
        email = f"invite-accept-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)

        # Send invitation
        inv_resp = admin_api.post(f"/teams/{private_team['id']}/invitations", data={"email": email, "role": "member"})
        assert inv_resp.status in (200, 201), f"Failed to create invitation: {inv_resp.status} {inv_resp.text()}"
        invitation_token = inv_resp.json()["token"]

        # Accept as the invited user
        user_jwt = _make_jwt(email, is_admin=False)
        user_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {user_jwt}", "Accept": "application/json"},
        )
        accept_resp = user_ctx.post(f"/teams/invitations/{invitation_token}/accept")
        user_ctx.dispose()
        assert accept_resp.status == 200

        # Verify user is now a member
        members_resp = admin_api.get(f"/teams/{private_team['id']}/members")
        members = members_resp.json()
        member_list = members if isinstance(members, list) else members.get("members", [])
        member_emails = [m["user_email"] for m in member_list]
        assert email in member_emails

        # Cleanup
        admin_api.delete(f"/teams/{private_team['id']}/members/{email}")
        delete_test_user(admin_api, email)

    def test_cancel_invitation(self, admin_api: APIRequestContext, private_team: dict):
        """Team owner can cancel a pending invitation."""
        email = f"invite-cancel-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, email)
        inv_resp = admin_api.post(f"/teams/{private_team['id']}/invitations", data={"email": email, "role": "member"})
        assert inv_resp.status in (200, 201), f"Failed to create invitation: {inv_resp.status} {inv_resp.text()}"
        inv_id = inv_resp.json()["id"]

        # Cancel the invitation
        cancel_resp = admin_api.delete(f"/teams/invitations/{inv_id}")
        assert cancel_resp.status == 200

        # Verify invitation is no longer listed
        list_resp = admin_api.get(f"/teams/{private_team['id']}/invitations")
        inv_ids = [i["id"] for i in list_resp.json()]
        assert inv_id not in inv_ids

        delete_test_user(admin_api, email)

    def test_non_owner_cannot_invite(self, admin_api: APIRequestContext, private_team: dict, playwright: Playwright):
        """A non-owner member cannot send invitations."""
        # Create and add a member
        member_email = f"member-noinvite-{uuid.uuid4().hex[:8]}@example.com"
        invitee_email = f"target-noinvite-{uuid.uuid4().hex[:8]}@example.com"
        create_test_user(admin_api, member_email)
        create_test_user(admin_api, invitee_email)

        # Add member via invitation
        inv_resp = admin_api.post(f"/teams/{private_team['id']}/invitations", data={"email": member_email, "role": "member"})
        assert inv_resp.status in (200, 201), f"Failed to create invitation: {inv_resp.status} {inv_resp.text()}"
        inv_token = inv_resp.json()["token"]
        member_jwt = _make_jwt(member_email, is_admin=False)
        member_ctx = playwright.request.new_context(
            base_url=BASE_URL,
            extra_http_headers={"Authorization": f"Bearer {member_jwt}", "Accept": "application/json"},
        )
        member_ctx.post(f"/teams/invitations/{inv_token}/accept")

        # Try to invite as member (should be denied)
        invite_resp = member_ctx.post(
            f"/teams/{private_team['id']}/invitations",
            data={"email": invitee_email, "role": "member"},
        )
        member_ctx.dispose()
        assert invite_resp.status in (403, 422), f"Non-owner should be denied invite, got {invite_resp.status}"

        # Cleanup
        admin_api.delete(f"/teams/{private_team['id']}/members/{member_email}")
        delete_test_user(admin_api, member_email)
        delete_test_user(admin_api, invitee_email)
