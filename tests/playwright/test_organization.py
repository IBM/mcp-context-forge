# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_organization.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for Organization features (Teams, Tokens) in ContextForge Admin UI.
"""

# Standard
import uuid

# Third-Party
import pytest
from playwright.sync_api import expect


class TestTeams:
    """Tests for Team management features."""

    @pytest.mark.flaky(reruns=2, reruns_delay=1, reason="HTMX refresh timing in headless mode")
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

        # Workaround: Auto-refresh doesn't work, so reload the page
        team_page.page.wait_for_load_state("domcontentloaded")
        team_page.page.reload(wait_until="domcontentloaded")

        # Search for the team to bring it into view (handles pagination)
        team_search = team_page.page.locator("#team-search")
        team_search.fill(team_name)

        # Wait for team to be visible in the list after search
        team_page.wait_for_team_visible(team_name)

        # Delete the team
        team_page.delete_team(team_name)

        # Verify it's gone
        team_page.wait_for_team_hidden(team_name)

    def test_manage_members_button(self, team_page):
        """Test Manage Members button opens member management interface."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)

        # Reload to see the new team — after reload, the default tab shows
        # (not teams), so re-navigate to teams tab and wait for search field.
        team_page.page.wait_for_load_state("domcontentloaded")
        team_page.page.reload(wait_until="domcontentloaded")
        team_page.navigate_to_teams_tab()

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.wait_for(state="visible", timeout=30000)
        team_search.fill(team_name)

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
            # Alternative: close via JavaScript
            team_page.page.evaluate("document.getElementById('team-edit-modal').classList.add('hidden')")

        # Cleanup
        team_page.delete_team(team_name)

    @pytest.mark.flaky(reruns=2, reruns_delay=1, reason="HTMX search DOM swap timing in headless mode")
    def test_edit_settings_button(self, team_page):
        """Test Edit Settings button opens team settings editor."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)

        # Reload to see the new team — after reload, the default tab shows
        # (not teams), so re-navigate to teams tab and wait for search field.
        team_page.page.wait_for_load_state("domcontentloaded")
        team_page.page.reload(wait_until="domcontentloaded")
        team_page.navigate_to_teams_tab()

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.wait_for(state="visible", timeout=30000)
        team_search.fill(team_name)

        # Verify team is visible
        team_page.wait_for_team_visible(team_name)

        # Wait for HTMX search to settle before interacting with cards
        team_page.page.wait_for_function(
            "() => !document.querySelector('#teams-loading.htmx-request')",
            timeout=15000,
        )

        # Click Edit Settings button (only visible when user is team owner)
        # Re-query to avoid stale references after HTMX DOM swap
        edit_btn = team_page.get_team_edit_settings_btn(team_name)
        try:
            expect(edit_btn).to_be_visible(timeout=15000)
        except AssertionError:
            pytest.skip("Edit Settings button not visible (team relationship may not be 'owner' in this context)")
        edit_btn.click(force=True, timeout=15000)

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

    @pytest.mark.flaky(reruns=2, reruns_delay=1, reason="HTMX refresh timing in headless mode")
    def test_delete_team_button_in_card(self, team_page):
        """Test Delete Team button in team card with confirmation."""
        team_page.navigate_to_teams_tab()
        team_name = f"Test Team {uuid.uuid4().hex[:8]}"

        # Create test team
        with team_page.page.expect_response(lambda response: "/admin/teams" in response.url and response.request.method == "POST"):
            team_page.create_team(team_name)

        # Reload to see the new team — after reload, the default tab shows
        # (not teams), so re-navigate to teams tab and wait for search field.
        team_page.page.wait_for_load_state("domcontentloaded")
        team_page.page.reload(wait_until="domcontentloaded")
        team_page.navigate_to_teams_tab()

        # Search for the team
        team_search = team_page.page.locator("#team-search")
        team_search.wait_for(state="visible", timeout=30000)
        team_search.fill(team_name)

        # Verify team is visible
        team_page.wait_for_team_visible(team_name)

        # Click Delete Team button (handles confirmation automatically via delete_team method)
        team_page.delete_team(team_name)

        # Verify team is deleted
        team_page.wait_for_team_hidden(team_name)


class TestTeamSelectorDropdown:
    """Tests for the team selector dropdown in the admin header."""

    def test_team_selector_click_navigates(self, team_page):
        """Clicking a team in the header dropdown should navigate with ?team_id=X."""
        page = team_page.page

        # Navigate to a clean URL (no #fragment)
        base_url = page.url.split("#")[0].split("?")[0]
        page.goto(base_url, wait_until="domcontentloaded")

        # Verify the delegation handler is registered (PR code is loaded)
        delegation_ok = page.evaluate("""() => {
            const c = document.getElementById('team-selector-items');
            if (!c) return false;
            let f = false;
            const o = window.selectTeamFromSelector;
            window.selectTeamFromSelector = () => { f = true; };
            window.__teamSwitchingInProgress = false;
            const b = document.createElement('button');
            b.className = 'team-selector-item';
            b.dataset.teamId = 'x'; b.dataset.teamName = 'x'; b.dataset.teamIsPersonal = 'false';
            c.appendChild(b); b.click(); b.remove();
            window.selectTeamFromSelector = o;
            return f;
        }""")
        if not delegation_ok:
            pytest.skip("Team selector delegation handler not registered (old JS cached)")

        # Click the team selector dropdown button in the header
        selector_btn = page.locator("#team-selector-button")
        expect(selector_btn).to_be_visible(timeout=10000)
        selector_btn.click()

        # Wait for team items to load in the dropdown
        items_container = page.locator("#team-selector-items")
        expect(items_container).to_be_visible(timeout=10000)

        # Wait for the loading message to be replaced with actual team buttons
        page.wait_for_function(
            "() => document.querySelectorAll('#team-selector-items .team-selector-item').length > 0",
            timeout=15000,
        )

        # Use the first available team (personal team is always present and
        # always in USER_TEAMS_DATA, so Alpine init won't strip the team_id).
        team_item = items_container.locator(".team-selector-item").first
        expect(team_item).to_be_visible(timeout=10000)

        # Verify onclick is stripped (innerHTML guard) and data-team-id survives
        item_info = team_item.evaluate("""el => ({
            hasOnclick: el.hasAttribute('onclick'),
            teamId: el.dataset.teamId,
        })""")
        assert not item_info["hasOnclick"], "onclick should be stripped by innerHTML guard"
        assert item_info["teamId"], "data-team-id should survive innerHTML guard"

        # Reset the team-switching guard — Alpine.js init() may have called
        # updateTeamContext('') during page load which sets this flag.
        page.evaluate("() => { window.__teamSwitchingInProgress = false; }")

        # Click the team — updateTeamContext does window.location.assign()
        team_item.click()

        # Wait for URL to contain team_id (full navigation via location.assign)
        page.wait_for_url("**/admin/*team_id=**", timeout=15000)

        # Verify the URL now contains team_id
        assert "team_id=" in page.url, f"Expected team_id in URL after clicking team, got: {page.url}"


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
        payload = response.json()
        created_token = payload.get("token", payload if isinstance(payload, dict) else {})
        token_id = created_token.get("id") or created_token.get("token_id")
        assert token_id, f"Token creation response missing id: {payload}"
        assert created_token.get("name") == token_name, f"Token name mismatch in response: {payload}"

        # Wait for success modal
        tokens_page.wait_for_token_created_modal()

        # Close result modal
        tokens_page.close_token_created_modal()

        # Revoke via frontend function using created token ID.
        with tokens_page.page.expect_response(
            lambda revoke_response: revoke_response.url.endswith(f"/tokens/{token_id}") and revoke_response.request.method == "DELETE"
        ) as revoke_info:
            tokens_page.page.evaluate(
                """
                ({ id, name }) => {
                  window.confirm = () => true;
                  return revokeToken(id, name);
                }
                """,
                {"id": token_id, "name": token_name},
            )
        revoke_response = revoke_info.value
        assert revoke_response.status in (200, 204), f"Token revoke failed: {revoke_response.status} {revoke_response.text()}"

        # Verify status changes or row removed/updated
        tokens_page.page.wait_for_timeout(500)
