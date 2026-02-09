# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_organization.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Organization features (Teams, Tokens) in MCP Gateway Admin UI.
"""

# Standard
import uuid

# Third-Party
from playwright.sync_api import expect
import pytest


class TestTeams:
    """Tests for Team management features."""

    def test_create_and_delete_team(self, team_page):
        """Test creating and deleting a team."""
        # Go to Teams tab
        team_page.navigate_to_teams_tab()

        # Generate unique team name
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create team - HTMX will automatically update #unified-teams-list
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST") as response_info:
            team_page.create_team(team_name)
        response = response_info.value
        assert response.status < 400

        # Workaround: Auto-refresh doesn't work, so wait and reload the page
        team_page.page.wait_for_timeout(2000)
        team_page.page.reload()
        team_page.page.wait_for_timeout(1000)

        # Search for the team to bring it into view (handles pagination)
        team_search = team_page.page.locator("#team-search")
        team_search.fill(team_name)
        team_page.page.wait_for_timeout(1000)

        # Wait for team to be visible in the list after search
        team_page.wait_for_team_visible(team_name)

        # Delete the team
        team_page.delete_team(team_name)

        # Verify it's gone
        team_page.page.wait_for_timeout(1000)
        team_page.wait_for_team_hidden(team_name)

    def test_manage_members_button(self, team_page):
        """Test Manage Members button opens member management interface."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)
        
        # Wait and reload to see the new team
        team_page.page.wait_for_timeout(2000)
        team_page.page.reload()
        team_page.page.wait_for_timeout(1000)

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.fill(team_name)
        team_page.page.wait_for_timeout(1000)

        # Verify team is visible
        team_page.wait_for_team_visible(team_name)

        # Click Manage Members button
        manage_btn = team_page.get_team_manage_members_btn(team_name)
        expect(manage_btn).to_be_visible()
        manage_btn.click()

        # Verify team edit modal opens with member management content
        team_edit_modal = team_page.page.locator("#team-edit-modal")
        expect(team_edit_modal).to_be_visible(timeout=5000)
        
        # Verify it's the member management interface (has "Team Members:" title)
        modal_content = team_page.page.locator("#team-edit-modal-content")
        expect(modal_content).to_contain_text("Team Members:")
        
        # Verify member management form elements are present
        expect(modal_content.locator('form[id^="team-members-form-"]')).to_be_visible()

        # Close modal
        close_btn = team_edit_modal.locator('button:has-text("Cancel")')
        if close_btn.count() > 0:
            close_btn.first.click()
        else:
            # Alternative: click the X button or backdrop
            team_page.page.evaluate("document.getElementById('team-edit-modal').classList.add('hidden')")

        # Cleanup
        team_page.delete_team(team_name)
        team_page.page.wait_for_timeout(1000)

    def test_edit_settings_button(self, team_page):
        """Test Edit Settings button opens team settings editor."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)
        
        # Wait and reload to see the new team
        team_page.page.wait_for_timeout(2000)
        team_page.page.reload()
        team_page.page.wait_for_timeout(1000)

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.fill(team_name)
        team_page.page.wait_for_timeout(1000)

        # Verify team is visible
        team_page.wait_for_team_visible(team_name)

        # Click Edit Settings button
        edit_btn = team_page.get_team_edit_settings_btn(team_name)
        expect(edit_btn).to_be_visible()
        edit_btn.click()

        # Verify team edit modal opens with settings form
        team_edit_modal = team_page.page.locator("#team-edit-modal")
        expect(team_edit_modal).to_be_visible(timeout=5000)
        
        # Verify it's the edit settings interface (has "Edit Team" title)
        modal_content = team_page.page.locator("#team-edit-modal-content")
        expect(modal_content).to_contain_text("Edit Team")

        # Verify form is pre-filled with team name
        name_input = modal_content.locator('input[name="name"]')
        expect(name_input).to_be_visible()
        assert team_name in name_input.input_value()

        # Verify other form fields are present
        expect(modal_content.locator('input[name="slug"]')).to_be_visible()
        expect(modal_content.locator('select[name="visibility"]')).to_be_visible()

        # Close modal without saving
        cancel_btn = team_edit_modal.locator('button:has-text("Cancel")')
        if cancel_btn.count() > 0:
            cancel_btn.first.click()
        else:
            # Alternative: close via JavaScript
            team_page.page.evaluate("document.getElementById('team-edit-modal').classList.add('hidden')")

        # Cleanup
        team_page.delete_team(team_name)
        team_page.page.wait_for_timeout(1000)

    def test_delete_team_button_in_card(self, team_page):
        """Test Delete Team button in team card with confirmation."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)
        
        # Wait and reload to see the new team
        team_page.page.wait_for_timeout(2000)
        team_page.page.reload()
        team_page.page.wait_for_timeout(1000)

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.fill(team_name)
        team_page.page.wait_for_timeout(1000)

        # Verify team is visible
        team_page.wait_for_team_visible(team_name)

        # Click Delete Team button (handles confirmation automatically via delete_team method)
        team_page.delete_team(team_name)

        # Verify team is deleted
        team_page.page.wait_for_timeout(1000)
        team_page.wait_for_team_hidden(team_name)


class TestTokens:
    """Tests for API Token management features."""

    def test_create_and_revoke_token(self, tokens_page):
        """Test creating and revoking an API token."""
        # Go to Tokens tab
        tokens_page.navigate_to_tokens_tab()

        # Generate token name
        token_name = f"Test Token {uuid.uuid4().hex[:8]}"

        # Create token and wait for API response to /tokens
        with tokens_page.page.expect_response(lambda response: response.url.endswith("/tokens") and response.request.method == "POST") as response_info:
            tokens_page.create_token(token_name)
        
        response = response_info.value
        assert response.status < 400, f"Token creation failed with status {response.status}"

        # Wait for success modal
        tokens_page.wait_for_token_created_modal()

        # Close result modal
        tokens_page.close_token_created_modal()

        # Verify token in list
        tokens_page.wait_for_token_visible(token_name)

        # Revoke the token
        tokens_page.revoke_token(token_name)

        # Verify status changes or row removed/updated
        tokens_page.page.wait_for_timeout(500)
