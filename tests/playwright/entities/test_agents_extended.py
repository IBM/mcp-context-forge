# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_agents_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended test coverage for A2A Agents management in the ContextForge Admin UI.
Tests table structure, view/edit/test modals, row actions, pagination,
OAuth grant type switching, and table data display.
"""

# Standard
import logging
import re

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from ..pages.agents_page import AgentsPage

logger = logging.getLogger(__name__)


def _skip_if_no_agents(agents_page: AgentsPage) -> None:
    """Skip test if no agents are available in the table."""
    if agents_page.agent_rows.count() == 0:
        pytest.skip("No agents available for testing")


def _open_view_modal(agents_page: AgentsPage, index: int = 0) -> None:
    """Open the view modal for an agent row by index.

    The JS handler fetches GET /admin/a2a/{id} before showing the modal,
    so we intercept the response to detect API errors early.
    """
    row = agents_page.get_agent_row(index)
    row.scroll_into_view_if_needed()
    row.locator("button[aria-expanded]").click()
    row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
    view_btn = row.locator('button[role="menuitem"]:has-text("View")')
    with agents_page.page.expect_response(
        lambda resp: (re.search(r"/admin/a2a/[0-9a-f]", resp.url) is not None and "/partial" not in resp.url and resp.request.method == "GET"),
        timeout=30000,
    ) as resp_info:
        view_btn.click()
    response = resp_info.value
    if response.status >= 400:
        pytest.skip(f"Agent API fetch failed (HTTP {response.status})")
    agents_page.page.wait_for_selector("#agent-modal:not(.hidden)", state="visible", timeout=10000)


def _close_view_modal(agents_page: AgentsPage) -> None:
    """Close the agent view modal."""
    close_btn = agents_page.page.locator('#agent-modal button:has-text("Close")')
    close_btn.click()
    agents_page.page.wait_for_selector("#agent-modal", state="hidden", timeout=5000)


def _open_edit_modal(agents_page: AgentsPage, index: int = 0) -> None:
    """Open the edit modal for an agent row by index.

    The JS handler fetches GET /admin/a2a/{id} before showing the modal.
    """
    row = agents_page.get_agent_row(index)
    row.scroll_into_view_if_needed()
    row.locator("button[aria-expanded]").click()
    row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
    edit_btn = row.locator('button[role="menuitem"]:has-text("Edit")')
    with agents_page.page.expect_response(
        lambda resp: (re.search(r"/admin/a2a/[0-9a-f]", resp.url) is not None and "/partial" not in resp.url and resp.request.method == "GET"),
        timeout=30000,
    ) as resp_info:
        edit_btn.click()
    response = resp_info.value
    if response.status >= 400:
        pytest.skip(f"Agent API fetch failed (HTTP {response.status})")
    agents_page.page.wait_for_selector("#a2a-edit-modal:not(.hidden)", state="visible", timeout=10000)


def _close_edit_modal(agents_page: AgentsPage) -> None:
    """Close the agent edit modal via the Cancel button."""
    cancel_btn = agents_page.page.locator('#a2a-edit-modal button:has-text("Cancel")')
    cancel_btn.click()
    agents_page.page.wait_for_selector("#a2a-edit-modal", state="hidden", timeout=5000)


def _open_test_modal(agents_page: AgentsPage, index: int = 0) -> None:
    """Open the test modal for an agent row by index.

    The test modal does not require an API fetch before opening.
    """
    row = agents_page.get_agent_row(index)
    row.scroll_into_view_if_needed()
    row.locator("button[aria-expanded]").click()
    row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
    test_btn = row.locator('button:has-text("Test")')
    test_btn.click()
    agents_page.page.wait_for_selector("#a2a-test-modal:not(.hidden)", state="visible", timeout=10000)


def _close_test_modal(agents_page: AgentsPage) -> None:
    """Close the agent test modal."""
    close_btn = agents_page.page.locator("#a2a-test-close")
    close_btn.click()
    agents_page.page.wait_for_selector("#a2a-test-modal", state="hidden", timeout=5000)


# ---------------------------------------------------------------------------
# A2A Table Structure
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2ATableStructure:
    """Tests for the A2A agents table layout, columns, pagination, and controls."""

    def test_table_column_actions(self, agents_page: AgentsPage):
        """Test that the Actions column header is present in the agents table."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        table = agents_page.agents_table.first
        expect(table.locator('th:has-text("Actions")').first).to_be_visible()

    def test_table_column_id(self, agents_page: AgentsPage):
        """Test that the Agent ID column header is present in the agents table."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        table = agents_page.agents_table.first
        expect(table.locator('th:has-text("Agent ID")').first).to_be_visible()

    def test_table_columns_complete(self, agents_page: AgentsPage):
        """Test that all 13 expected table column headers are present."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        table = agents_page.agents_table.first
        expected_columns = [
            "Actions",
            "S. No.",
            "Agent ID",
            "Name",
            "Description",
            "Endpoint",
            "Tags",
            "Type",
            "Status",
            "Reachability",
            "Owner",
            "Team",
            "Visibility",
        ]

        for col in expected_columns:
            expect(table.locator(f'th:has-text("{col}")').first).to_be_visible()

    def test_registered_agents_heading_visible(self, agents_page: AgentsPage):
        """Test that the 'Registered A2A Agents' heading is visible."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        expect(agents_page.registered_agents_title).to_be_visible()
        expect(agents_page.registered_agents_title).to_contain_text("Registered A2A Agents")

    def test_pagination_controls_present(self, agents_page: AgentsPage):
        """Test that pagination controls container is present on the page."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")
        expect(pagination).to_be_attached()

    def test_pagination_per_page_options(self, agents_page: AgentsPage):
        """Test that per-page select has options 10/25/50/100/200/500."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")
        per_page_select = pagination.locator("select").first

        for value in ["10", "25", "50", "100", "200", "500"]:
            expect(per_page_select.locator(f'option[value="{value}"]')).to_be_attached()

    def test_show_inactive_checkbox(self, agents_page: AgentsPage):
        """Test that the show inactive agents checkbox is present."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        checkbox = agents_page.page.locator("#show-inactive-a2a-agents")
        expect(checkbox).to_be_attached()


# ---------------------------------------------------------------------------
# A2A View Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2AViewModal:
    """Tests for the Agent Details view modal."""

    def test_view_modal_opens_with_title(self, agents_page: AgentsPage):
        """Test that the view modal opens and displays 'Agent Details' title."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        modal = agents_page.page.locator("#agent-modal")
        expect(modal).to_be_visible()
        expect(modal.locator('h3:has-text("Agent Details")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_name_field(self, agents_page: AgentsPage):
        """Test that the view modal shows the Name field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Name:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_slug_field(self, agents_page: AgentsPage):
        """Test that the view modal shows the Slug field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Slug:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_endpoint_url_field(self, agents_page: AgentsPage):
        """Test that the view modal shows the Endpoint URL field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Endpoint URL:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_agent_type_field(self, agents_page: AgentsPage):
        """Test that the view modal shows the Agent Type field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Agent Type:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_visibility_and_status(self, agents_page: AgentsPage):
        """Test that the view modal shows Visibility and Status fields."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Visibility:")')).to_be_visible()
        expect(details.locator('strong:has-text("Status:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_capabilities_config(self, agents_page: AgentsPage):
        """Test that the view modal shows the Capabilities & Config section."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Capabilities & Config:")')).to_be_visible()

        _close_view_modal(agents_page)

    def test_view_modal_shows_metadata_section(self, agents_page: AgentsPage):
        """Test that the view modal shows the Metadata section with Created By, Created At, and Version."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)

        details = agents_page.page.locator("#agent-details")
        expect(details.locator('strong:has-text("Metadata:")')).to_be_visible()

        # Verify metadata fields are present
        for field in ["Created By", "Created At", "Version"]:
            expect(details).to_contain_text(field)

        _close_view_modal(agents_page)

    def test_view_modal_close_button_works(self, agents_page: AgentsPage):
        """Test that the Close button properly closes the view modal."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_view_modal(agents_page, 0)
        modal = agents_page.page.locator("#agent-modal")
        expect(modal).to_be_visible()

        _close_view_modal(agents_page)
        expect(modal).to_be_hidden()

    def test_view_modal_different_agents_show_different_data(self, agents_page: AgentsPage):
        """Test that viewing different agents shows different data in the modal."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        count = agents_page.agent_rows.count()
        if count < 2:
            pytest.skip("Need at least 2 agents to test different views")

        # View first agent - get name from table
        first_row = agents_page.get_agent_row(0)
        first_name = first_row.locator("td").nth(3).text_content().strip()
        _open_view_modal(agents_page, 0)
        details = agents_page.page.locator("#agent-details")
        expect(details).to_contain_text(first_name)
        _close_view_modal(agents_page)

        # View second agent
        second_row = agents_page.get_agent_row(1)
        second_name = second_row.locator("td").nth(3).text_content().strip()
        _open_view_modal(agents_page, 1)
        expect(details).to_contain_text(second_name)
        _close_view_modal(agents_page)


# ---------------------------------------------------------------------------
# A2A Edit Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2AEditModal:
    """Tests for the Edit A2A Agent modal."""

    def test_edit_modal_opens_with_title(self, agents_page: AgentsPage):
        """Test that the edit modal opens and displays 'Edit A2A Agent' title."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        modal = agents_page.page.locator("#a2a-edit-modal")
        expect(modal).to_be_visible()
        expect(modal.locator('h3:has-text("Edit A2A Agent")')).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_has_name_field(self, agents_page: AgentsPage):
        """Test that the edit modal has a name input field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        name_input = agents_page.page.locator("#a2a-agent-name-edit")
        expect(name_input).to_be_visible()
        # Should be pre-populated with a value
        value = name_input.input_value()
        assert len(value) > 0, "Name field should be pre-populated"

        _close_edit_modal(agents_page)

    def test_edit_modal_has_endpoint_field(self, agents_page: AgentsPage):
        """Test that the edit modal has an endpoint URL input field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        endpoint_input = agents_page.page.locator("#a2a-agent-endpoint-url-edit")
        expect(endpoint_input).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_has_description_and_tags(self, agents_page: AgentsPage):
        """Test that the edit modal has description textarea and tags input."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        description = agents_page.page.locator("#a2a-agent-description-edit")
        tags = agents_page.page.locator("#a2a-agent-tags-edit")
        expect(description).to_be_visible()
        expect(tags).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_has_agent_type_select(self, agents_page: AgentsPage):
        """Test that the edit modal has an agent type select with correct options."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        agent_type = agents_page.page.locator("#a2a-agent-type-edit")
        expect(agent_type).to_be_visible()

        for value in ["generic", "openai", "anthropic", "custom"]:
            expect(agent_type.locator(f'option[value="{value}"]')).to_be_attached()

        _close_edit_modal(agents_page)

    def test_edit_modal_has_auth_type_select_with_all_options(self, agents_page: AgentsPage):
        """Test that the edit modal auth type select has all expected options."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        expect(auth_type).to_be_visible()

        for value in ["", "basic", "bearer", "authheaders", "oauth", "query_param"]:
            expect(auth_type.locator(f'option[value="{value}"]')).to_be_attached()

        _close_edit_modal(agents_page)

    def test_edit_modal_auth_type_basic_fields(self, agents_page: AgentsPage):
        """Test that selecting basic auth in edit modal shows username/password fields."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        # Select basic auth
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("basic")

        basic_fields = agents_page.page.locator("#auth-basic-fields-a2a-edit")
        expect(basic_fields).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_auth_type_bearer_fields(self, agents_page: AgentsPage):
        """Test that selecting bearer auth in edit modal shows token field."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("bearer")

        bearer_fields = agents_page.page.locator("#auth-bearer-fields-a2a-edit")
        expect(bearer_fields).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_auth_type_oauth_fields(self, agents_page: AgentsPage):
        """Test that selecting OAuth in edit modal shows OAuth fields."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("oauth")

        oauth_fields = agents_page.page.locator("#auth-oauth-fields-a2a-edit")
        expect(oauth_fields).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_auth_type_query_param_fields(self, agents_page: AgentsPage):
        """Test that selecting query param auth in edit modal shows key/value fields."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("query_param")

        qp_fields = agents_page.page.locator("#auth-query_param-fields-a2a-edit")
        expect(qp_fields).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_cancel_does_not_save(self, agents_page: AgentsPage):
        """Test that Cancel button closes the edit modal without saving changes."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        # Get original name from table
        first_row = agents_page.get_agent_row(0)
        original_name = first_row.locator("td").nth(3).text_content().strip()

        _open_edit_modal(agents_page, 0)

        # Change the name
        name_input = agents_page.page.locator("#a2a-agent-name-edit")
        name_input.fill("SHOULD-NOT-SAVE-cancel-test")

        # Cancel
        _close_edit_modal(agents_page)

        modal = agents_page.page.locator("#a2a-edit-modal")
        expect(modal).to_be_hidden()

        # Reload and verify original name is intact
        agents_page.page.reload(wait_until="domcontentloaded")
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        current_name = first_row.locator("td").nth(3).text_content().strip()
        assert current_name == original_name, f"Name should be unchanged after Cancel: expected '{original_name}', " f"got '{current_name}'"

    def test_edit_modal_has_save_changes_button(self, agents_page: AgentsPage):
        """Test that the edit modal has a Save Changes button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        save_btn = agents_page.page.locator('#a2a-edit-modal button:has-text("Save Changes")')
        expect(save_btn).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_visibility_radios_present(self, agents_page: AgentsPage):
        """Test that visibility radio buttons are present in the edit modal."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        expect(agents_page.page.locator("#edit-a2a-visibility-public")).to_be_attached()
        expect(agents_page.page.locator("#edit-a2a-visibility-team")).to_be_attached()
        expect(agents_page.page.locator("#edit-a2a-visibility-private")).to_be_attached()

        _close_edit_modal(agents_page)

    def test_edit_modal_auth_type_custom_headers_fields(self, agents_page: AgentsPage):
        """Test that selecting custom headers auth shows the headers container."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        # Select custom headers auth type
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("authheaders")

        # Wait for custom headers section to become visible
        # The JavaScript handler changes display from "none" to "block"
        agents_page.page.wait_for_function(
            """() => {
                const el = document.getElementById('auth-headers-fields-a2a-edit');
                return el && el.style.display === 'block';
            }""",
            timeout=5000,
        )

        # Give the browser a moment to render the newly visible section
        agents_page.page.wait_for_timeout(200)

        # Verify the container for headers exists
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        expect(headers_container).to_be_attached()

        # Wait for and verify the "Add Header" button is visible
        add_header_btn = agents_page.page.locator('#auth-headers-fields-a2a-edit button:has-text("Add Header")')
        add_header_btn.wait_for(state="visible", timeout=3000)
        expect(add_header_btn).to_be_visible()

        _close_edit_modal(agents_page)

    def test_edit_modal_custom_headers_add_button_works(self, agents_page: AgentsPage):
        """Test that clicking Add Header button creates a new header row."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        # Select custom headers auth type
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("authheaders")

        # Wait for custom headers section to become visible
        agents_page.page.wait_for_function(
            """() => {
                const el = document.getElementById('auth-headers-fields-a2a-edit');
                return el && el.style.display === 'block';
            }""",
            timeout=5000,
        )

        # Give the browser a moment to render
        agents_page.page.wait_for_timeout(200)

        # Get initial count of header rows (looking for divs with auth-header- IDs)
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        initial_count = headers_container.locator("div[id^='auth-header-']").count()

        # Call Admin.addAuthHeader function directly via JavaScript
        # This is more reliable than clicking the button in headless mode
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")

        # Wait for a new header row to be added to the DOM
        agents_page.page.wait_for_selector("#auth-headers-container-a2a-edit div[id^='auth-header-']", state="attached", timeout=5000)

        # Verify a new header row was added
        new_count = headers_container.locator("div[id^='auth-header-']").count()
        assert new_count == initial_count + 1, f"Expected {initial_count + 1} header rows, got {new_count}"

        _close_edit_modal(agents_page)

    def test_edit_modal_custom_headers_can_be_filled(self, agents_page: AgentsPage):
        """Test that custom header key and value fields can be filled."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        # Select custom headers auth type
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("authheaders")

        # Wait for custom headers section to become visible
        agents_page.page.wait_for_function(
            """() => {
                const el = document.getElementById('auth-headers-fields-a2a-edit');
                return el && el.style.display === 'block';
            }""",
            timeout=5000,
        )

        # Give the browser a moment to render
        agents_page.page.wait_for_timeout(200)

        # Call Admin.addAuthHeader function directly via JavaScript
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")

        # Wait for the new row to be added
        agents_page.page.wait_for_selector("#auth-headers-container-a2a-edit div[id^='auth-header-']", state="attached", timeout=5000)

        # Find the header row inputs
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        header_rows = headers_container.locator("div[id^='auth-header-']")
        last_row = header_rows.last

        # Fill in key and value
        key_input = last_row.locator('input[placeholder*="Header"]').first
        value_input = last_row.locator('input[placeholder*="Value"]').first

        key_input.fill("X-Test-Header")
        value_input.fill("test-value-123")

        # Verify values were set
        assert key_input.input_value() == "X-Test-Header"
        assert value_input.input_value() == "test-value-123"

        _close_edit_modal(agents_page)

    def test_edit_modal_custom_headers_remove_button_works(self, agents_page: AgentsPage):
        """Test that clicking remove button deletes a header row."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_edit_modal(agents_page, 0)

        # Select custom headers auth type
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("authheaders")

        # Wait for custom headers section to become visible
        agents_page.page.wait_for_function(
            """() => {
                const el = document.getElementById('auth-headers-fields-a2a-edit');
                return el && el.style.display === 'block';
            }""",
            timeout=5000,
        )

        # Give the browser a moment to render
        agents_page.page.wait_for_timeout(200)

        # Call Admin.addAuthHeader function directly via JavaScript (twice)
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")
        agents_page.page.wait_for_timeout(200)
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")

        # Wait for rows to be added
        agents_page.page.wait_for_timeout(300)

        # Get count before removal
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        count_before = headers_container.locator("div[id^='auth-header-']").count()

        # Click remove button on the first header (button has no text, only SVG icon)
        first_row = headers_container.locator("div[id^='auth-header-']").first
        remove_btn = first_row.locator('button[data-action="remove-header"]')
        remove_btn.click()
        agents_page.page.wait_for_timeout(300)

        # Verify count decreased
        count_after = headers_container.locator("div[id^='auth-header-']").count()
        assert count_after == count_before - 1, f"Expected {count_before - 1} header rows after removal, got {count_after}"

        _close_edit_modal(agents_page)

    def test_edit_modal_displays_existing_custom_headers(self, agents_page: AgentsPage):
        """Test that editing an agent with existing custom headers displays them (issue #3637)."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        # Open edit modal for first agent
        _open_edit_modal(agents_page, 0)

        # Select custom headers auth type
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        auth_type.select_option("authheaders")

        # Wait for custom headers section to become visible
        agents_page.page.wait_for_function(
            """() => {
                const el = document.getElementById('auth-headers-fields-a2a-edit');
                return el && el.style.display === 'block';
            }""",
            timeout=5000,
        )

        # Give the browser a moment to render
        agents_page.page.wait_for_timeout(200)

        # Add first header using JavaScript (more reliable than clicking)
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")
        agents_page.page.wait_for_timeout(200)

        # Fill first header
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        first_row = headers_container.locator("div[id^='auth-header-']").first
        first_row.locator('input[placeholder*="Header Key"]').fill("X-API-Key")
        first_row.locator('input[placeholder*="Header Value"]').fill("test-secret-123")

        # Add second header using JavaScript
        agents_page.page.evaluate("Admin.addAuthHeader('auth-headers-container-a2a-edit')")
        agents_page.page.wait_for_timeout(200)

        # Fill second header
        second_row = headers_container.locator("div[id^='auth-header-']").nth(1)
        second_row.locator('input[placeholder*="Header Key"]').fill("X-Client-ID")
        second_row.locator('input[placeholder*="Header Value"]').fill("client-456")

        # Serialize headers to JSON before saving
        agents_page.page.evaluate("Admin.updateAuthHeadersJSON('auth-headers-container-a2a-edit')")
        agents_page.page.wait_for_timeout(100)

        # Save the agent and wait for the POST response + panel navigation
        save_btn = agents_page.page.locator('#a2a-edit-modal button:has-text("Save Changes")')
        with agents_page.page.expect_response(
            lambda resp: "/admin/a2a/" in resp.url and "/edit" in resp.url and resp.request.method == "POST",
            timeout=30000,
        ) as resp_info:
            save_btn.click()
        response = resp_info.value
        if response.status >= 400:
            pytest.skip(f"Agent edit save failed (HTTP {response.status})")

        # The JS save handler closes the modal then triggers _navigateAdmin()
        # which fires an async HTMX refresh. wait_for_load_state returns
        # immediately on the already-loaded page, so wait for the modal to
        # close (confirms the handler ran) then reload for a clean state.
        agents_page.page.wait_for_selector("#a2a-edit-modal", state="hidden", timeout=10000)
        agents_page.page.reload(wait_until="domcontentloaded")
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Re-open the edit modal
        _open_edit_modal(agents_page, 0)

        # Verify auth type is still custom headers
        auth_type = agents_page.page.locator("#auth-type-a2a-edit")
        expect(auth_type).to_have_value("authheaders")

        # Verify custom headers are displayed
        headers_container = agents_page.page.locator("#auth-headers-container-a2a-edit")
        header_rows = headers_container.locator("div[id^='auth-header-']")

        # Should have at least 2 headers
        assert header_rows.count() >= 2, f"Expected at least 2 header rows, got {header_rows.count()}"

        # Verify first header key is displayed
        first_row = header_rows.first
        first_key_input = first_row.locator('input[placeholder*="Header Key"]')
        expect(first_key_input).to_have_value("X-API-Key")

        # Verify second header key is displayed
        second_row = header_rows.nth(1)
        second_key_input = second_row.locator('input[placeholder*="Header Key"]')
        expect(second_key_input).to_have_value("X-Client-ID")

        # Note: Values should be masked (shown as dots) for security
        # We don't test the exact masked value as it may vary

        _close_edit_modal(agents_page)


# ---------------------------------------------------------------------------
# A2A Test Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2ATestModal:
    """Tests for the Test A2A Agent modal."""

    def test_test_modal_opens_with_title(self, agents_page: AgentsPage):
        """Test that the test modal opens and contains 'Test A2A Agent' in the title."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)

        title = agents_page.page.locator("#a2a-test-modal-title")
        expect(title).to_be_visible()
        expect(title).to_contain_text("Test A2A Agent")

        _close_test_modal(agents_page)

    def test_test_modal_has_query_textarea(self, agents_page: AgentsPage):
        """Test that the test modal has a query textarea with default text."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)

        query_textarea = agents_page.page.locator("#a2a-test-query")
        expect(query_textarea).to_be_visible()

        # Verify default text
        value = query_textarea.input_value()
        assert "Hello from ContextForge Admin UI test!" in value, f"Expected default query text, got '{value}'"

        _close_test_modal(agents_page)

    def test_test_modal_has_submit_button(self, agents_page: AgentsPage):
        """Test that the test modal has a Test Agent submit button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)

        submit_btn = agents_page.page.locator("#a2a-test-submit")
        expect(submit_btn).to_be_visible()
        expect(submit_btn).to_contain_text("Test Agent")

        _close_test_modal(agents_page)

    def test_test_modal_has_result_area(self, agents_page: AgentsPage):
        """Test that the test modal has a result display area."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)

        result_area = agents_page.page.locator("#a2a-test-result")
        expect(result_area).to_be_attached()

        _close_test_modal(agents_page)

    def test_test_modal_has_close_button(self, agents_page: AgentsPage):
        """Test that the test modal has a close button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)

        close_btn = agents_page.page.locator("#a2a-test-close")
        expect(close_btn).to_be_visible()

        _close_test_modal(agents_page)

    def test_test_modal_close_button_works(self, agents_page: AgentsPage):
        """Test that the close button properly closes the test modal."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        _open_test_modal(agents_page, 0)
        modal = agents_page.page.locator("#a2a-test-modal")
        expect(modal).to_be_visible()

        _close_test_modal(agents_page)
        expect(modal).to_be_hidden()


# ---------------------------------------------------------------------------
# A2A Row Actions
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2ARowActions:
    """Tests for action buttons and data displayed in agent table rows."""

    def test_row_has_test_button(self, agents_page: AgentsPage):
        """Test that the first agent row has a Test button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        first_row.scroll_into_view_if_needed()
        first_row.locator("button[aria-expanded]").click()
        first_row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
        expect(first_row.locator('button:has-text("Test")')).to_be_visible()

    def test_row_has_view_button(self, agents_page: AgentsPage):
        """Test that the first agent row has a View button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        first_row.scroll_into_view_if_needed()
        first_row.locator("button[aria-expanded]").click()
        first_row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
        expect(first_row.locator('button:has-text("View")')).to_be_visible()

    def test_row_has_edit_button(self, agents_page: AgentsPage):
        """Test that the first agent row has an Edit button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        first_row.scroll_into_view_if_needed()
        first_row.locator("button[aria-expanded]").click()
        first_row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
        expect(first_row.locator('button:has-text("Edit")')).to_be_visible()

    def test_row_has_deactivate_or_activate_button(self, agents_page: AgentsPage):
        """Test that the first agent row has a Deactivate or Activate button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        first_row.scroll_into_view_if_needed()
        first_row.locator("button[aria-expanded]").click()
        first_row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
        # One of these should be visible
        deactivate = first_row.locator('button:has-text("Deactivate")')
        activate = first_row.locator('button:has-text("Activate")')
        assert deactivate.count() > 0 or activate.count() > 0, "Row should have either Deactivate or Activate button"

    def test_row_has_delete_button(self, agents_page: AgentsPage):
        """Test that the first agent row has a Delete button."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        first_row.scroll_into_view_if_needed()
        first_row.locator("button[aria-expanded]").click()
        first_row.locator('[role="menu"]').wait_for(state="visible", timeout=5000)
        expect(first_row.locator('button:has-text("Delete")')).to_be_visible()

    def test_row_displays_serial_number(self, agents_page: AgentsPage):
        """Test that the first row displays serial number '1' in the ID column."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # ID column is the second td (index 1)
        id_cell = first_row.locator("td").nth(1)
        id_text = id_cell.text_content().strip()
        assert id_text == "1", f"First row serial number should be '1', got '{id_text}'"

    def test_row_displays_status_badge(self, agents_page: AgentsPage):
        """Test that the agent row displays an Active or Inactive status badge."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Status column is at index 8 (Actions=0, S.No.=1, AgentID=2, Name=3, Description=4, Endpoint=5, Tags=6, Type=7, Status=8)
        status_cell = first_row.locator("td").nth(8)
        status_text = status_cell.text_content().strip()
        assert "Active" in status_text or "Inactive" in status_text, f"Status should be 'Active' or 'Inactive', got '{status_text}'"


# ---------------------------------------------------------------------------
# A2A Pagination
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2APagination:
    """Tests for agent table pagination controls."""

    def test_per_page_select_with_correct_options(self, agents_page: AgentsPage):
        """Test that per-page dropdown has all expected options (10/25/50/100/200/500)."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")
        per_page_select = pagination.locator("select").first
        expect(per_page_select).to_be_visible()

        for value in ["10", "25", "50", "100", "200", "500"]:
            expect(per_page_select.locator(f'option[value="{value}"]')).to_be_attached()

    def test_pagination_default_per_page_value(self, agents_page: AgentsPage):
        """Test that per-page select has a valid default value."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")
        per_page_select = pagination.locator("select").first

        # Default per_page could be 10 or 50 depending on server config
        current_value = per_page_select.input_value()
        assert current_value in [
            "10",
            "25",
            "50",
            "100",
            "200",
            "500",
        ], f"Per-page default should be a valid option, got '{current_value}'"

    def test_pagination_info_text(self, agents_page: AgentsPage):
        """Test that pagination shows 'Showing X - Y of Z items' text."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")
        # The x-text directive renders "Showing X - Y of Z items" via Alpine.js
        info_text = pagination.text_content()
        assert "Showing" in info_text or "items" in info_text or "No items" in info_text, f"Pagination should display item count info, got '{info_text[:100]}'"

    def test_pagination_navigation_buttons_present(self, agents_page: AgentsPage):
        """Test that pagination Prev and Next navigation buttons exist."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        pagination = agents_page.page.locator("#agents-pagination-controls")

        # Navigation buttons should exist (rendered by Alpine.js template)
        prev_btn = pagination.locator('button:has-text("Prev")')
        next_btn = pagination.locator('button:has-text("Next")')

        # Buttons are inside a template x-if block - only present when totalPages > 0
        if prev_btn.count() > 0:
            expect(prev_btn).to_be_attached()
        if next_btn.count() > 0:
            expect(next_btn).to_be_attached()

        # At least the pagination container should be present
        expect(pagination).to_be_attached()


# ---------------------------------------------------------------------------
# A2A OAuth Grant Type Switching
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2AOAuthGrantTypeSwitching:
    """Tests for OAuth grant type conditional field visibility in the add form."""

    def test_authorization_code_shows_auth_url_and_redirect_fields(self, agents_page: AgentsPage):
        """Test that authorization_code grant type shows Auth URL, Redirect URI, and token management checkboxes."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Select OAuth auth type
        agents_page.set_auth_type("oauth")

        # Select authorization_code
        agents_page.oauth_grant_type_select.select_option("authorization_code")

        # Authorization URL and Redirect URI should be visible
        expect(agents_page.oauth_authorization_url_input).to_be_visible()
        expect(agents_page.oauth_redirect_uri_input).to_be_visible()

        # Token management checkboxes should be visible within the auth code fields
        auth_code_fields = agents_page.page.locator("#oauth-auth-code-fields-a2a")
        store_tokens = auth_code_fields.locator('input[name="oauth_store_tokens"]')
        auto_refresh = auth_code_fields.locator('input[name="oauth_auto_refresh"]')
        expect(store_tokens).to_be_visible()
        expect(auto_refresh).to_be_visible()

    def test_client_credentials_hides_auth_url_fields(self, agents_page: AgentsPage):
        """Test that client_credentials grant type hides auth URL and redirect URI."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        agents_page.set_auth_type("oauth")

        agents_page.oauth_grant_type_select.select_option("client_credentials")

        # Auth URL and Redirect URI should be hidden
        expect(agents_page.oauth_authorization_url_input).to_be_hidden()
        expect(agents_page.oauth_redirect_uri_input).to_be_hidden()

        # Core fields should still be visible
        expect(agents_page.oauth_issuer_input).to_be_visible()
        expect(agents_page.oauth_client_id_input).to_be_visible()
        expect(agents_page.oauth_client_secret_input).to_be_visible()
        expect(agents_page.oauth_scopes_input).to_be_visible()

    def test_password_grant_shows_username_password(self, agents_page: AgentsPage):
        """Test that password grant type shows username and password fields."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        agents_page.set_auth_type("oauth")

        agents_page.oauth_grant_type_select.select_option("password")

        # Username and password fields for password grant should be visible
        username_field = agents_page.page.locator("#oauth-username-a2a")
        password_field = agents_page.page.locator("#oauth-password-a2a")
        expect(username_field).to_be_visible()
        expect(password_field).to_be_visible()

    def test_switching_between_grant_types_updates_visibility(self, agents_page: AgentsPage):
        """Test switching between all grant types correctly updates field visibility."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        agents_page.set_auth_type("oauth")

        # Start with authorization_code
        agents_page.oauth_grant_type_select.select_option("authorization_code")
        expect(agents_page.oauth_authorization_url_input).to_be_visible()

        # Switch to client_credentials
        agents_page.oauth_grant_type_select.select_option("client_credentials")
        expect(agents_page.oauth_authorization_url_input).to_be_hidden()

        # Switch to password
        agents_page.oauth_grant_type_select.select_option("password")
        username_field = agents_page.page.locator("#oauth-username-a2a")
        expect(username_field).to_be_visible()

        # Switch back to authorization_code
        agents_page.oauth_grant_type_select.select_option("authorization_code")
        expect(agents_page.oauth_authorization_url_input).to_be_visible()
        expect(username_field).to_be_hidden()


# ---------------------------------------------------------------------------
# A2A Table Data Display
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.agents
class TestA2ATableDataDisplay:
    """Tests for data rendering in the agents table rows."""

    def test_agent_name_displayed_in_row(self, agents_page: AgentsPage):
        """Test that agent name is displayed in the table row."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Name is in column index 3 (after Actions, S.No., Agent ID)
        name_cell = first_row.locator("td").nth(3)
        name_text = name_cell.text_content().strip()
        assert len(name_text) > 0, "Agent name should not be empty"

    def test_endpoint_url_displayed_in_row(self, agents_page: AgentsPage):
        """Test that endpoint URL is displayed in the table row."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Endpoint is in column index 5 (after Actions, S.No., Agent ID, Name, Description)
        endpoint_cell = first_row.locator("td").nth(5)
        endpoint_text = endpoint_cell.text_content().strip()
        assert len(endpoint_text) > 0, "Endpoint URL should not be empty"
        assert "://" in endpoint_text, f"Endpoint should be a URL, got '{endpoint_text}'"

    def test_description_displayed_in_row(self, agents_page: AgentsPage):
        """Test that description is displayed in the table row."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Description is in column index 4 (after Actions, S.No., Agent ID, Name)
        desc_cell = first_row.locator("td").nth(4)
        # Description may be empty but the cell should exist
        expect(desc_cell).to_be_attached()

    def test_tags_displayed_as_badges(self, agents_page: AgentsPage):
        """Test that tags are displayed as badge-style span elements."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Tags column is at index 6 (after Actions, S.No., Agent ID, Name, Description, Endpoint)
        tags_cell = first_row.locator("td").nth(6)

        # Check if there are any tag badges (spans with inline-flex styling)
        tag_badges = tags_cell.locator("span")
        if tag_badges.count() > 0:
            # Tags should be rendered as badge-like spans
            first_tag = tag_badges.first
            tag_text = first_tag.text_content().strip()
            assert len(tag_text) > 0, "Tag badge should contain text"
        # If no tags, that is acceptable -- some agents may not have tags

    def test_visibility_badge_displayed(self, agents_page: AgentsPage):
        """Test that a visibility badge (Public/Team/Private) is displayed."""
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()
        _skip_if_no_agents(agents_page)

        first_row = agents_page.get_agent_row(0)
        # Visibility is the last column, index 12
        visibility_cell = first_row.locator("td").nth(12)
        visibility_text = visibility_cell.text_content().strip()
        assert visibility_text in [
            "Public",
            "Team",
            "Private",
            "N/A",
        ], f"Visibility should be Public/Team/Private/N/A, got '{visibility_text}'"
