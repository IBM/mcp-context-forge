# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/team_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Team page object for Teams features.
"""

# Third-Party
from playwright.sync_api import expect, Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage


class TeamPage(BasePage):
    """Page object for Team management features."""

    # ==================== Panel Elements ====================

    @property
    def teams_panel(self) -> Locator:
        """Teams panel container."""
        return self.page.locator("#teams-panel")

    # ==================== Teams Elements ====================

    @property
    def create_team_btn(self) -> Locator:
        """Create Team button that opens the modal."""
        return self.page.locator("#create-team-btn")

    @property
    def create_team_modal(self) -> Locator:
        """Create Team modal dialog."""
        return self.page.locator("#create-team-modal")

    @property
    def team_name_input(self) -> Locator:
        """Team name input field in create team form."""
        return self.create_team_form.locator('input[name="name"]')

    @property
    def create_team_form(self) -> Locator:
        """Create team form."""
        return self.page.locator("#create-team-form")

    @property
    def create_team_submit_btn(self) -> Locator:
        """Submit button for create team form."""
        return self.create_team_form.locator('button[type="submit"]')

    def get_team_card(self, team_name: str) -> Locator:
        """Get the team card div containing the specified team name.

        Args:
            team_name: The name of the team to find

        Returns:
            Locator for the team card
        """
        # Use filter with has_text to match partial text (works with emoji prefix)
        return self.page.locator("div.team-card").filter(has=self.page.locator(f'h4.team-name:has-text("{team_name}")')).first

    def get_team_delete_btn(self, team_name: str) -> Locator:
        """Get the delete button for a specific team.

        Args:
            team_name: The name of the team

        Returns:
            Locator for the delete button
        """
        # Find the delete button within the team card
        return self.get_team_card(team_name).locator('button:has-text("Delete Team")')

    def get_team_manage_members_btn(self, team_name: str) -> Locator:
        """Get the Manage Members button for a specific team.

        Args:
            team_name: The name of the team

        Returns:
            Locator for the Manage Members button
        """
        return self.get_team_card(team_name).locator('button:has-text("Manage Members")')

    def get_team_edit_settings_btn(self, team_name: str) -> Locator:
        """Get the Edit Settings button for a specific team.

        Args:
            team_name: The name of the team

        Returns:
            Locator for the Edit Settings button
        """
        return self.get_team_card(team_name).locator('button:has-text("Edit Settings")')

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_teams_tab(self) -> None:
        """Navigate to Teams tab and wait for panel to be visible."""
        self.sidebar.click_teams_tab()

    # ==================== High-Level Team Operations ====================

    def create_team(self, team_name: str) -> None:
        """Create a new team.

        Args:
            team_name: The name for the new team
        """
        # Open create team modal
        self.click_locator(self.create_team_btn)
        self.wait_for_visible(self.create_team_modal)

        # Fill form
        self.fill_locator(self.team_name_input, team_name)

        # Submit
        self.click_locator(self.create_team_submit_btn)

    def delete_team(self, team_name: str) -> None:
        """Delete a team with confirmation.

        Args:
            team_name: The name of the team to delete
        """
        # Setup dialog listener for confirmation
        self.page.once("dialog", lambda dialog: dialog.accept())

        # Click delete button
        self.click_locator(self.get_team_delete_btn(team_name))

        # Wait for DELETE request to complete and HX-Trigger to fire
        # Then wait for the subsequent GET /admin/teams/partial refresh
        # Total: DELETE + 1000ms delay + GET + DOM update
        self.page.wait_for_timeout(5000)

    def team_exists(self, team_name: str) -> bool:
        """Check if a team with the given name exists.

        Args:
            team_name: The name of the team to check

        Returns:
            True if team exists, False otherwise
        """
        return self.page.locator(f"text={team_name}").is_visible()

    def wait_for_team_visible(self, team_name: str, timeout: int = 30000) -> None:
        """Wait for a team to be visible in the list.

        Args:
            team_name: The name of the team
            timeout: Maximum time to wait in milliseconds
        """
        # Wait for the team card to be visible
        team_card = self.get_team_card(team_name)
        expect(team_card).to_be_visible(timeout=timeout)

    def wait_for_team_hidden(self, team_name: str, timeout: int = 30000) -> None:
        """Wait for a team to be hidden from the list.

        Args:
            team_name: The name of the team
            timeout: Maximum time to wait in milliseconds
        """
        # Clear the search filter so HTMX refresh shows all teams (not filtered by deleted team name)
        team_search = self.page.locator("#team-search")
        if team_search.is_visible():
            team_search.fill("")

            # Teams search is debounced + HTMX-driven; avoid networkidle because
            # admin pages can keep long-lived requests open.
            try:
                self.page.wait_for_selector("#teams-loading.htmx-request", timeout=3000)
            except PlaywrightTimeoutError:
                # Fallback: explicitly trigger server-side teams search refresh.
                self.page.evaluate("window.serverSideTeamSearch && window.serverSideTeamSearch('')")

            self.page.wait_for_function(
                "() => !document.querySelector('#teams-loading.htmx-request')",
                timeout=10000,
            )
            self.page.wait_for_selector("#unified-teams-list", state="attached", timeout=10000)

        # Now check that the team card is hidden
        team_card = self.get_team_card(team_name)
        expect(team_card).to_be_hidden(timeout=timeout)
