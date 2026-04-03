# -*- coding: utf-8 -*-
"""CRUD tests for Teams entity in ContextForge Admin UI.

Location: ./tests/playwright/entities/test_teams_crud.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Marek Dano
"""

# Standard
import uuid

# Third-Party
import pytest

# Local
from ..pages.team_page import TeamPage


@pytest.fixture
def test_team_data():
    """Provide unique test data for team creation."""
    unique_id = uuid.uuid4().hex[:8]
    return {"name": f"Test Team {unique_id}"}


def _create_team_and_navigate(team_page: TeamPage, team_name: str) -> None:
    """Helper: create a team via the UI and wait for the in-page list refresh.

    Captures both the POST create response and the subsequent HTMX GET refresh
    of ``/admin/teams/partial`` (triggered by ``htmx:afterRequest`` → ``initializeTeamManagement()``)
    in a single round-trip, avoiding a full page reload.
    """
    team_page.navigate_to_teams_tab()
    team_page.wait_for_teams_loaded()

    # Capture the in-page list refresh that fires after the POST succeeds
    with team_page.page.expect_response(
        lambda r: "/admin/teams/partial" in r.url and r.request.method == "GET"
    ) as refresh_info:
        with team_page.page.expect_response(
            lambda r: "/admin/teams" in r.url and r.request.method == "POST" and "/partial" not in r.url and "/update" not in r.url
        ) as create_info:
            team_page.create_team(team_name)
        assert create_info.value.status < 400, f"Team creation failed with status {create_info.value.status}"
    assert refresh_info.value.status == 200, f"Teams list refresh returned status {refresh_info.value.status}"

    # Filter the list to the specific team so pagination doesn't hide it
    # (teams are sorted alphabetically, so a newly created team may be on page 2+)
    team_page.search_teams(team_name)
    team_page.wait_for_team_visible(team_name)


@pytest.mark.ui
@pytest.mark.crud
class TestTeamsCRUD:
    """CRUD tests for Teams entity via the admin UI."""

    def test_create_team(self, team_page: TeamPage, test_team_data):
        """Test creating a new team via the admin UI."""
        team_name = test_team_data["name"]
        _create_team_and_navigate(team_page, team_name)
        assert team_page.team_exists(team_name)

        # Cleanup
        team_page.delete_team(team_name)

    def test_edit_team(self, team_page: TeamPage, test_team_data):
        """Test that editing a team name updates the list and pre-fills the edit form."""
        team_name = test_team_data["name"]
        updated_name = f"Updated {team_name}"

        _create_team_and_navigate(team_page, team_name)

        # Open edit modal and verify it pre-fills with the original name
        team_page.click_edit_settings(team_name)
        original_form_value = team_page.get_edit_form_name_value()
        assert original_form_value == team_name, f"Edit form should show original name '{team_name}', got '{original_form_value}'"

        # Submit the new name; capture the in-page refresh driven by adminTeamAction HX-Trigger
        with team_page.page.expect_response(
            lambda r: "/admin/teams/partial" in r.url and r.request.method == "GET"
        ) as refresh_info:
            with team_page.page.expect_response(lambda r: "/update" in r.url and r.request.method == "POST") as response_info:
                team_page.submit_edit_team_form(updated_name)
            assert response_info.value.status < 400, f"Team edit failed with status {response_info.value.status}"
        assert refresh_info.value.status == 200, f"Teams list refresh returned status {refresh_info.value.status}"

        # Search for the updated name and verify it appears in the list
        team_page.search_teams(updated_name)
        team_page.wait_for_team_visible(updated_name)
        assert team_page.team_exists(updated_name), f"Updated name '{updated_name}' not visible in teams list"

        # Re-open edit modal and verify the form shows the updated name
        team_page.click_edit_settings(updated_name)
        edit_form_value = team_page.get_edit_form_name_value()
        assert edit_form_value == updated_name, f"Edit form should show updated name '{updated_name}', got '{edit_form_value}'"
        team_page.close_team_edit_modal()

        # Cleanup
        team_page.delete_team(updated_name)
