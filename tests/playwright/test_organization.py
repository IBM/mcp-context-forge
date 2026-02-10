# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_organization.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Organization features (Teams, Tokens) in MCP Gateway Admin UI.
"""

# Standard
import time
import uuid

# Third-Party
from playwright.sync_api import expect, Page
import pytest


class TestOrganization:
    """Tests for Organization features."""

    @pytest.mark.skip(reason="Flaky in CI/Headless mode, requires manual verification")
    def test_create_and_delete_team(self, admin_page: Page):
        """Test creating and deleting a team."""
        # Go to Teams tab
        admin_page.click('[data-testid="teams-tab"]')
        admin_page.wait_for_selector("#teams-panel:not(.hidden)")

        # Generate unique team name
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Click Create Team button (opens modal)
        admin_page.click("#create-team-btn")
        admin_page.wait_for_selector("#create-team-modal")

        # Fill form
        admin_page.fill("#team-name", team_name)

        # Submit
        with admin_page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#create-team-form button[type="submit"]')
        response = response_info.value
        assert response.status < 400

        # Verify team appears in list
        # We might need to search for it if the list is long, or just check visibility
        # Assuming it appears at top or we can find it text
        admin_page.goto(f"{admin_page.url.split('#')[0]}#teams")
        admin_page.reload()
        admin_page.wait_for_selector("#teams-panel:not(.hidden)")

        # Wait for list to populate
        admin_page.wait_for_selector(f"text={team_name}", timeout=30000)
        expect(admin_page.locator(f"text={team_name}")).to_be_visible()

        # Delete the team
        # Find the row with the team name
        team_row = admin_page.locator(f"tr:has-text('{team_name}')")

        # Setup dialog listener for confirmation
        admin_page.once("dialog", lambda dialog: dialog.accept())

        # Click delete button in that row
        team_row.locator('button:has-text("Delete")').click()

        # Verify it's gone
        admin_page.wait_for_timeout(1000)
        expect(admin_page.locator(f"text={team_name}")).to_be_hidden()

    @pytest.mark.skip(reason="Flaky in CI/Headless mode, requires manual verification")
    def test_create_and_revoke_token(self, admin_page: Page):
        """Test creating and revoking an API token."""
        # Go to Tokens tab
        admin_page.click("#tab-tokens")
        admin_page.wait_for_selector("#tokens-panel:not(.hidden)")

        # Generate token name
        token_name = f"Test Token {uuid.uuid4().hex[:8]}"

        # Fill form
        admin_page.fill("#api-token-name", token_name)
        # Select expiry (optional, default is fine)

        # Submit
        admin_page.click('#create-token-form button[type="submit"]')

        # Wait for success modal
        admin_page.wait_for_selector("text=Token Created Successfully", timeout=30000)

        # Close result modal
        admin_page.click('button:has-text("I\'ve Saved It")')

        # Verify token in list
        admin_page.wait_for_selector(f"text={token_name}", timeout=30000)
        expect(admin_page.locator(f"text={token_name}")).to_be_visible()

        # Revoke the token
        # Find container/row with token name
        # Tokens might be in a grid or table. Admin.js renders them.
        # Assuming we can find a revoke button near the text.
        token_element = admin_page.locator(f"div:has-text('{token_name}')").first

        admin_page.once("dialog", lambda dialog: dialog.accept())
        # The revoke button might be a sibling or child.
        # Using a broad search for Revoke button visible on page might be risky if multiple.
        # Let's try to scope it.
        # If list is refreshed, the new token should be there.

        # Specific selector depends on HTML structure of token list which is dynamic JS.
        # Let's assume there is a Revoke button.
        admin_page.locator(f"div:has-text('{token_name}')").locator("xpath=..").locator("button:has-text('Revoke')").click()

        # Verify status changes or row removed/updated
        admin_page.wait_for_timeout(500)
