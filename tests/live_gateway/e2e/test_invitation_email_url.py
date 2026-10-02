# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/e2e/test_invitation_email_url.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify invitation links through the live team API with SMTP disabled.

Set MCP_EMAIL_TEST_UI_BASE to the gateway's UI_BASE_URL or APP_DOMAIN + APP_ROOT_PATH.
Run against a disposable gateway with ALLOW_TEAM_INVITATIONS=true and SMTP_ENABLED=false.
"""

# Standard
import os
from urllib.parse import quote
from uuid import uuid4

# Third-Party
import httpx
import pytest

# First-Party
from tests.helpers.auth import make_test_jwt
from tests.live_gateway.helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway

pytestmark = [pytest.mark.e2e, skip_no_gateway]


def test_invitation_email_url_uses_frontend_route():
    """The team API returns an invitation link under the React mount point."""
    ui_base = os.getenv("MCP_EMAIL_TEST_UI_BASE")
    if not ui_base:
        pytest.skip("Set MCP_EMAIL_TEST_UI_BASE for a disposable gateway with SMTP disabled")

    token = make_test_jwt(email=ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET)
    with httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        response = client.post("/teams/", json={"name": f"email-route-{uuid4().hex[:12]}", "visibility": "private"})
        assert response.status_code == 201, response.text
        team_id = response.json()["id"]
        try:
            response = client.post(f"/teams/{team_id}/invitations", json={"email": f"invite-{uuid4().hex}@example.com", "role": "member"})
            assert response.status_code == 201, response.text
            invitation = response.json()
            assert invitation["email_delivery_status"] == "disabled"
            assert invitation["invitation_url"] == f"{ui_base.rstrip('/')}/app/accept-invitation/{quote(invitation['token'], safe='')}"
        finally:
            response = client.delete(f"/teams/{team_id}")
            assert response.status_code in (200, 204), response.text
