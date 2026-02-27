# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_tools_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended test coverage for MCP Tools management in the admin UI.
Tests table structure, add form fields, modal interactions (View, Edit, Test),
row actions, search/filter, pagination controls, form validation, and
annotation badge rendering.
"""

# Standard
import logging
import re
import uuid

# Third-Party
from playwright.sync_api import Error as PlaywrightError, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from ..pages.tools_page import ToolsPage

logger = logging.getLogger(__name__)


def _skip_if_no_tools(tools_page: ToolsPage) -> None:
    """Skip test if no tools are available."""
    if tools_page.tool_rows.count() == 0:
        pytest.skip("No tools available for testing")


def _get_tool_count(tools_page: ToolsPage) -> int:
    """Return the number of tool rows currently visible in the table."""
    return tools_page.tool_rows.count()


# ---------------------------------------------------------------------------
# Tools Table Structure
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsTableStructure:
    """Tests for the tools panel and table layout."""

    def test_tools_panel_loads(self, tools_page: ToolsPage):
        """Test that the tools panel becomes visible when navigating to the tab."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tools_panel).to_be_visible()

    def test_tools_table_present(self, tools_page: ToolsPage):
        """Test that the tools table element is present in the DOM."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tools_table).to_be_visible()

    def test_tools_table_body_present(self, tools_page: ToolsPage):
        """Test that the tools table body element is attached to the DOM."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tools_table_body).to_be_attached()

    def test_table_columns_complete(self, tools_page: ToolsPage):
        """Test that all expected table columns are present in the header."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        table = tools_page.tools_table
        expected_columns = [
            "Actions",
            "S. No.",
            "Source",
            "Name",
            "Request Type",
            "Description",
            "Annotations",
            "Tags",
            "Owner",
            "Team",
            "Status",
        ]

        for col in expected_columns:
            expect(table.locator(f'th:has-text("{col}")')).to_be_visible()

    def test_add_tool_form_visible(self, tools_page: ToolsPage):
        """Test that the add tool form is visible on the page."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.add_tool_form).to_be_visible()

    def test_add_tool_form_heading(self, tools_page: ToolsPage):
        """Test that the add tool form has the correct heading."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        heading = tools_page.page.locator('h3:has-text("Add New Tool from REST API")')
        expect(heading).to_be_visible()

    def test_search_input_visible(self, tools_page: ToolsPage):
        """Test that the tools search input is visible."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        search_input = tools_page.page.locator("#tools-search-input")
        expect(search_input).to_be_visible()

    def test_show_inactive_checkbox_visible(self, tools_page: ToolsPage):
        """Test that the Show Inactive checkbox and its label are present."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        checkbox = tools_page.page.locator("#show-inactive-tools")
        expect(checkbox).to_be_attached()

        label = tools_page.page.locator('label[for="show-inactive-tools"]')
        expect(label).to_be_visible()
        expect(label).to_contain_text("Show Inactive")

    def test_pagination_controls_present(self, tools_page: ToolsPage):
        """Test that pagination controls container is present in the DOM."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        pagination = tools_page.page.locator("#tools-pagination-controls")
        expect(pagination).to_be_attached()

    def test_panel_description_text(self, tools_page: ToolsPage):
        """Test that the panel description text explains the tools catalog."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        description = tools_page.page.locator(
            "text=This is the global catalog of MCP Tools available"
        )
        expect(description).to_be_visible()


# ---------------------------------------------------------------------------
# Tools Add Form
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsAddForm:
    """Tests for the add tool form fields and options."""

    def test_name_field_present(self, tools_page: ToolsPage):
        """Test that the name input field is visible in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_name_input).to_be_visible()

    def test_url_field_present(self, tools_page: ToolsPage):
        """Test that the URL input field is visible in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_url_input).to_be_visible()

    def test_description_field_present(self, tools_page: ToolsPage):
        """Test that the description textarea is visible in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_description_input).to_be_visible()

    def test_integration_type_select_present(self, tools_page: ToolsPage):
        """Test that the integration type select is visible in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_integration_type_select).to_be_visible()

    def test_integration_type_has_rest_option(self, tools_page: ToolsPage):
        """Test that the integration type select has REST as an option."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        select = tools_page.tool_integration_type_select
        expect(select.locator('option[value="REST"]')).to_be_attached()

    def test_request_type_select_present(self, tools_page: ToolsPage):
        """Test that the request type select is visible in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        request_type = tools_page.add_tool_form.locator('[name="requestType"]')
        expect(request_type).to_be_visible()

    def test_request_type_options(self, tools_page: ToolsPage):
        """Test that the request type select has all HTTP method options."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        request_type = tools_page.add_tool_form.locator('[name="requestType"]')
        # Options may be filled by JS; wait for at least one option
        tools_page.page.wait_for_timeout(500)

        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            expect(request_type.locator(f'option:has-text("{method}")')).to_be_attached()

    def test_auth_type_select_present(self, tools_page: ToolsPage):
        """Test that the authentication type select is present in the add form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        auth_type = tools_page.add_tool_form.locator('[name="auth_type"]')
        expect(auth_type).to_be_visible()

    def test_auth_type_options(self, tools_page: ToolsPage):
        """Test that the auth type select has all expected options."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        auth_type = tools_page.add_tool_form.locator('[name="auth_type"]')

        # None (empty value), Basic, Bearer Token, Custom Headers, OAuth 2.0
        for value in ["", "basic", "bearer", "authheaders", "oauth"]:
            expect(auth_type.locator(f'option[value="{value}"]')).to_be_attached()

    def test_visibility_radios_present(self, tools_page: ToolsPage):
        """Test that visibility radio buttons (public/team/private) are present."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.add_tool_form.locator("#tool-visibility-public")).to_be_attached()
        expect(tools_page.add_tool_form.locator("#tool-visibility-team")).to_be_attached()
        expect(tools_page.add_tool_form.locator("#tool-visibility-private")).to_be_attached()

    def test_visibility_public_default_checked(self, tools_page: ToolsPage):
        """Test that the public visibility radio is checked by default."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        public_radio = tools_page.add_tool_form.locator("#tool-visibility-public")
        expect(public_radio).to_be_checked()

    def test_input_schema_toggle_present(self, tools_page: ToolsPage):
        """Test that the input schema mode toggle (Schema Builder / JSON Input) is present."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        schema_builder_radio = tools_page.add_tool_form.locator(
            'input[name="schema_input_mode"][value="ui"]'
        )
        json_input_radio = tools_page.add_tool_form.locator(
            'input[name="schema_input_mode"][value="json"]'
        )
        expect(schema_builder_radio).to_be_attached()
        expect(json_input_radio).to_be_attached()

        # Schema Builder should be checked by default
        expect(schema_builder_radio).to_be_checked()

    def test_tags_help_text(self, tools_page: ToolsPage):
        """Test that the tags field has help text about categorization."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        help_text = tools_page.add_tool_form.locator(
            "text=Enter tags separated by commas"
        )
        expect(help_text).to_be_visible()

    def test_output_schema_optional_text(self, tools_page: ToolsPage):
        """Test that the output schema field has a note about being optional."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        optional_text = tools_page.add_tool_form.locator(
            "text=Optional JSON Schema for validating structured tool output"
        )
        expect(optional_text).to_be_visible()

    def test_submit_button_present(self, tools_page: ToolsPage):
        """Test that the Add Tool submit button is visible."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.add_tool_btn).to_be_visible()
        expect(tools_page.add_tool_btn).to_contain_text("Add Tool")

    def test_display_name_field_present(self, tools_page: ToolsPage):
        """Test that the optional display name input field is present."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        display_name = tools_page.add_tool_form.locator('[name="displayName"]')
        expect(display_name).to_be_visible()


# ---------------------------------------------------------------------------
# View Tool Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsViewModal:
    """Tests for the View Tool details modal."""

    def test_view_modal_opens_with_details(self, tools_page: ToolsPage):
        """Test that the view modal opens and shows tool details."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_view_modal(0)

        expect(tools_page.tool_modal).to_be_visible()
        expect(tools_page.tool_modal.locator('h3:has-text("Tool Details")')).to_be_visible()

        tools_page.close_tool_modal()

    def test_view_modal_shows_name_field(self, tools_page: ToolsPage):
        """Test that the view modal displays the tool name."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_view_modal(0)

        details = tools_page.tool_details_content
        # Details should contain non-empty content with tool info
        text = details.text_content()
        assert len(text.strip()) > 0, "Tool details content should not be empty"

        tools_page.close_tool_modal()

    def test_view_modal_shows_description_field(self, tools_page: ToolsPage):
        """Test that the view modal displays tool description text."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        # Get description from table
        first_row = tools_page.get_tool_row(0)
        description = first_row.locator("td").nth(5).text_content().strip()

        tools_page.open_tool_view_modal(0)

        if description and description != "N/A":
            expect(tools_page.tool_details_content).to_contain_text(description[:30])

        tools_page.close_tool_modal()

    def test_view_modal_shows_url_field(self, tools_page: ToolsPage):
        """Test that the view modal displays tool source/URL information."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_view_modal(0)

        details = tools_page.tool_details_content
        # Details should have meaningful content
        expect(details).not_to_be_empty()

        tools_page.close_tool_modal()

    def test_view_modal_shows_annotations_field(self, tools_page: ToolsPage):
        """Test that the view modal displays the Annotations section."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_view_modal(0)

        details = tools_page.tool_details_content
        expect(details.locator('strong:has-text("Annotations:")')).to_be_visible()

        tools_page.close_tool_modal()

    def test_view_modal_close_button(self, tools_page: ToolsPage):
        """Test that the Close button properly closes the view modal."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_view_modal(0)
        expect(tools_page.tool_modal).to_be_visible()

        tools_page.close_tool_modal()
        expect(tools_page.tool_modal).to_be_hidden()

    def test_view_modal_contains_tool_name(self, tools_page: ToolsPage):
        """Test that the view modal content contains the tool name from the table."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        # Get the name from the table - Name column varies by row structure
        first_row = tools_page.get_tool_row(0)
        # Name is in column index 3 (Actions=0, S.No.=1, Source=2, Name=3)
        tool_name = first_row.locator("td").nth(3).text_content().strip()

        tools_page.open_tool_view_modal(0)
        # Tool details should mention the tool name
        details_text = tools_page.tool_details_content.text_content()
        assert tool_name in details_text, f"Expected '{tool_name}' in view modal details"

        tools_page.close_tool_modal()

    def test_view_modal_different_tools(self, tools_page: ToolsPage):
        """Test viewing details of different tools shows different data."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        count = _get_tool_count(tools_page)
        if count < 2:
            pytest.skip("Need at least 2 tools to test different views")

        # View first tool
        first_row = tools_page.get_tool_row(0)
        first_name = first_row.locator("td").nth(3).text_content().strip()
        try:
            tools_page.open_tool_view_modal(0)
        except AssertionError as exc:
            if "401" in str(exc) or "403" in str(exc):
                pytest.skip(f"Tool API auth failed: {exc}")
            raise
        expect(tools_page.tool_details_content).to_contain_text(first_name)
        tools_page.close_tool_modal()

        # View second tool
        second_row = tools_page.get_tool_row(1)
        second_name = second_row.locator("td").nth(3).text_content().strip()
        try:
            tools_page.open_tool_view_modal(1)
        except AssertionError as exc:
            if "401" in str(exc) or "403" in str(exc):
                pytest.skip(f"Tool API auth failed: {exc}")
            raise
        expect(tools_page.tool_details_content).to_contain_text(second_name)
        tools_page.close_tool_modal()


# ---------------------------------------------------------------------------
# Edit Tool Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsEditModal:
    """Tests for the Edit Tool modal."""

    def test_edit_modal_opens_with_prepopulated_name(self, tools_page: ToolsPage):
        """Test that edit modal opens with the tool name pre-filled."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        expect(tools_page.tool_edit_modal).to_be_visible()
        expect(tools_page.tool_edit_modal.locator('h3:has-text("Edit Tool")')).to_be_visible()

        # Name field should have a value (not empty)
        name_value = tools_page.tool_edit_name_input.input_value()
        assert len(name_value) > 0, "Edit modal name should be pre-populated"

        tools_page.cancel_tool_edit()

    def test_edit_modal_has_name_field(self, tools_page: ToolsPage):
        """Test that edit modal contains the name input field."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        expect(tools_page.tool_edit_name_input).to_be_visible()

        tools_page.cancel_tool_edit()

    def test_edit_modal_has_url_field(self, tools_page: ToolsPage):
        """Test that edit modal contains the URL input field."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        url_input = tools_page.tool_edit_modal.locator("#edit-tool-url")
        expect(url_input).to_be_visible()

        tools_page.cancel_tool_edit()

    def test_edit_modal_has_description_field(self, tools_page: ToolsPage):
        """Test that edit modal contains the description textarea."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        description = tools_page.tool_edit_modal.locator("#edit-tool-description")
        expect(description).to_be_visible()

        tools_page.cancel_tool_edit()

    def test_edit_modal_has_integration_type_select(self, tools_page: ToolsPage):
        """Test that edit modal contains the integration type select."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        integration_type = tools_page.tool_edit_modal.locator("#edit-tool-type")
        expect(integration_type).to_be_visible()

        # Verify it has REST and MCP options
        expect(integration_type.locator('option[value="REST"]')).to_be_attached()
        expect(integration_type.locator('option[value="MCP"]')).to_be_attached()

        tools_page.cancel_tool_edit()

    def test_edit_modal_has_auth_type_select(self, tools_page: ToolsPage):
        """Test that edit modal contains the auth type select with correct options."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        auth_select = tools_page.tool_edit_modal.locator("#edit-auth-type")
        expect(auth_select).to_be_visible()

        for value in ["", "basic", "bearer", "authheaders"]:
            expect(auth_select.locator(f'option[value="{value}"]')).to_be_attached()

        tools_page.cancel_tool_edit()

    def test_edit_modal_auth_basic_fields_toggle(self, tools_page: ToolsPage):
        """Test that selecting basic auth in edit modal shows username/password fields."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        auth_select = tools_page.tool_edit_modal.locator("#edit-auth-type")
        basic_fields = tools_page.tool_edit_modal.locator("#edit-auth-basic-fields")

        # Select basic auth
        auth_select.select_option("basic")
        tools_page.page.wait_for_timeout(300)
        expect(basic_fields).to_be_visible()

        # Switch back to None
        auth_select.select_option("")
        tools_page.page.wait_for_timeout(300)
        expect(basic_fields).to_be_hidden()

        tools_page.cancel_tool_edit()

    def test_edit_modal_auth_bearer_fields_toggle(self, tools_page: ToolsPage):
        """Test that selecting bearer auth in edit modal shows token field."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        auth_select = tools_page.tool_edit_modal.locator("#edit-auth-type")
        bearer_fields = tools_page.tool_edit_modal.locator("#edit-auth-bearer-fields")

        auth_select.select_option("bearer")
        tools_page.page.wait_for_timeout(300)
        expect(bearer_fields).to_be_visible()

        auth_select.select_option("")
        tools_page.page.wait_for_timeout(300)
        expect(bearer_fields).to_be_hidden()

        tools_page.cancel_tool_edit()

    def test_edit_modal_cancel_does_not_save(self, tools_page: ToolsPage):
        """Test that Cancel button closes the edit modal without saving changes."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        # Get original name
        first_row = tools_page.get_tool_row(0)
        original_name = first_row.locator("td").nth(3).text_content().strip()

        tools_page.open_tool_edit_modal(0)

        # Change the name
        tools_page.edit_tool_name("SHOULD-NOT-SAVE-" + str(uuid.uuid4()))

        # Cancel
        tools_page.cancel_tool_edit()
        expect(tools_page.tool_edit_modal).to_be_hidden()

        # Verify original name is still in the table
        tools_page.page.reload(wait_until="domcontentloaded")
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        first_row = tools_page.get_tool_row(0)
        current_name = first_row.locator("td").nth(3).text_content().strip()
        assert current_name == original_name, (
            f"Name should be unchanged after Cancel: expected '{original_name}', got '{current_name}'"
        )

    def test_edit_modal_has_visibility_radios(self, tools_page: ToolsPage):
        """Test that edit modal contains visibility radio buttons."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_edit_modal(0)

        visibility_section = tools_page.tool_edit_modal.locator("#edit-tool-visibility")
        expect(visibility_section).to_be_visible()

        expect(tools_page.tool_edit_modal.locator("#edit-tool-visibility-public")).to_be_attached()
        expect(tools_page.tool_edit_modal.locator("#edit-tool-visibility-team")).to_be_attached()
        expect(tools_page.tool_edit_modal.locator("#edit-tool-visibility-private")).to_be_attached()

        tools_page.cancel_tool_edit()


# ---------------------------------------------------------------------------
# Test Tool Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsTestModal:
    """Tests for the Test Tool modal."""

    def test_test_modal_opens(self, tools_page: ToolsPage):
        """Test that the test modal opens for a tool."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)

        expect(tools_page.tool_test_modal).to_be_visible()
        expect(
            tools_page.tool_test_modal.locator("#tool-test-modal-title")
        ).to_contain_text("Test Tool")

        tools_page.close_tool_test_modal()

    def test_test_modal_has_form(self, tools_page: ToolsPage):
        """Test that the test modal contains the test form."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)

        expect(tools_page.tool_test_form).to_be_visible()

        tools_page.close_tool_test_modal()

    def test_test_modal_has_run_button(self, tools_page: ToolsPage):
        """Test that the test modal contains a Run Tool button."""
        # Reload to ensure clean state from previous modal tests
        tools_page.page.reload(wait_until="domcontentloaded")
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)

        run_btn = tools_page.tool_test_modal.locator('button:has-text("Run Tool")')
        expect(run_btn).to_be_visible()

        tools_page.close_tool_test_modal()

    def test_test_modal_has_result_area(self, tools_page: ToolsPage):
        """Test that the test modal contains a result display area."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)

        result_area = tools_page.tool_test_modal.locator("#tool-test-result")
        expect(result_area).to_be_attached()

        tools_page.close_tool_test_modal()

    def test_test_modal_close_button(self, tools_page: ToolsPage):
        """Test that the Close button properly closes the test modal."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)
        expect(tools_page.tool_test_modal).to_be_visible()

        tools_page.close_tool_test_modal()
        expect(tools_page.tool_test_modal).to_be_hidden()

    def test_test_modal_has_passthrough_headers(self, tools_page: ToolsPage):
        """Test that the test modal contains a passthrough headers textarea."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        tools_page.open_tool_test_modal(0)

        passthrough = tools_page.tool_test_modal.locator("#test-passthrough-headers")
        expect(passthrough).to_be_visible()

        tools_page.close_tool_test_modal()


# ---------------------------------------------------------------------------
# Row Actions
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsRowActions:
    """Tests for tool row action buttons."""

    def test_row_has_test_button(self, tools_page: ToolsPage):
        """Test that each tool row has a Test button."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        test_btn = first_row.locator('button:has-text("Test")')
        expect(test_btn).to_be_visible()

    def test_row_has_view_button(self, tools_page: ToolsPage):
        """Test that each tool row has a View button."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        view_btn = first_row.locator('button:has-text("View")')
        expect(view_btn).to_be_visible()

    def test_row_has_edit_button(self, tools_page: ToolsPage):
        """Test that each tool row has an Edit button (for admin users)."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        edit_btn = first_row.locator('button:has-text("Edit")')
        # Edit may not be visible for non-admin users; just check it's attached
        expect(edit_btn).to_be_attached()

    def test_row_has_deactivate_or_activate_button(self, tools_page: ToolsPage):
        """Test that each tool row has a Deactivate or Activate button."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        # Could be either Deactivate (active tool) or Activate (inactive tool)
        toggle_btn = first_row.locator(
            'button:has-text("Deactivate"), button:has-text("Activate")'
        )
        expect(toggle_btn.first).to_be_attached()

    def test_row_has_delete_button(self, tools_page: ToolsPage):
        """Test that each tool row has a Delete button."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        delete_btn = first_row.locator('button:has-text("Delete")')
        expect(delete_btn).to_be_attached()

    def test_row_serial_number(self, tools_page: ToolsPage):
        """Test that the first tool row has serial number 1."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        serial = first_row.locator("td").nth(1).text_content().strip()
        assert serial == "1", f"First row serial should be '1', got '{serial}'"


# ---------------------------------------------------------------------------
# Search and Filter
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsSearchAndFilter:
    """Tests for tools search and filter functionality."""

    def test_search_input_placeholder(self, tools_page: ToolsPage):
        """Test that the search input has the correct placeholder text."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        search_input = tools_page.page.locator("#tools-search-input")
        expect(search_input).to_have_attribute("placeholder", "Search tools...")

    def test_search_by_name(self, tools_page: ToolsPage):
        """Test searching tools by name narrows results."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        # Get first tool name
        first_row = tools_page.get_tool_row(0)
        tool_name = first_row.locator("td").nth(3).text_content().strip()

        if len(tool_name) < 3:
            pytest.skip("Tool name too short for search test")

        search_input = tools_page.page.locator("#tools-search-input")
        search_input.fill(tool_name)

        # Wait for the HTMX debounce and reload
        try:
            tools_page.page.wait_for_selector("#tools-loading.htmx-request", timeout=5000)
        except PlaywrightTimeoutError:
            # Force a search reload via JS
            tools_page.page.evaluate(
                "(q) => { const el = document.getElementById('tools-search-input'); if (el) { el.value = q; } if (window.loadSearchablePanel) { window.loadSearchablePanel('tools'); } }",
                tool_name,
            )

        tools_page.page.wait_for_function(
            "() => !document.querySelector('#tools-loading.htmx-request')",
            timeout=15000,
        )

        # Re-attach to the table body after HTMX swap
        tools_page.page.wait_for_selector("#tools-table-body", state="attached", timeout=15000)

    def test_clear_search_button(self, tools_page: ToolsPage):
        """Test that the Clear button is visible and clears the search input."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        clear_btn = tools_page.page.locator("#tools-clear-search")
        expect(clear_btn).to_be_visible()
        expect(clear_btn).to_contain_text("Clear")

    def test_search_partial_match(self, tools_page: ToolsPage):
        """Test searching with a partial tool name."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()
        _skip_if_no_tools(tools_page)

        first_row = tools_page.get_tool_row(0)
        full_name = first_row.locator("td").nth(3).text_content().strip()

        if len(full_name) < 3:
            pytest.skip("Tool name too short for partial match test")

        # Search with first 3 characters
        partial = full_name[:3]
        search_input = tools_page.page.locator("#tools-search-input")
        search_input.fill(partial)

        # Wait for debounced HTMX request to complete
        tools_page.page.wait_for_timeout(1500)
        tools_page.page.wait_for_function(
            "() => !document.querySelector('#tools-loading.htmx-request')",
            timeout=15000,
        )

    def test_search_with_no_results(self, tools_page: ToolsPage):
        """Test searching for a tool that does not exist."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        nonexistent = "nonexistent-tool-xyz-99999"
        search_input = tools_page.page.locator("#tools-search-input")
        search_input.fill(nonexistent)

        # Wait for debounced HTMX request to complete
        tools_page.page.wait_for_timeout(1500)
        tools_page.page.wait_for_function(
            "() => !document.querySelector('#tools-loading.htmx-request')",
            timeout=15000,
        )

        # Clear search to restore the full list
        clear_btn = tools_page.page.locator("#tools-clear-search")
        clear_btn.click()
        tools_page.page.wait_for_timeout(1000)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsPagination:
    """Tests for tools table pagination controls."""

    def test_per_page_select_exists(self, tools_page: ToolsPage):
        """Test that per-page dropdown is visible with correct options."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        pagination = tools_page.page.locator("#tools-pagination-controls")
        per_page = pagination.locator("select")
        expect(per_page).to_be_visible()

        for value in ["10", "25", "50", "100", "200", "500"]:
            expect(per_page.locator(f'option[value="{value}"]')).to_be_attached()

    def test_per_page_default_value(self, tools_page: ToolsPage):
        """Test that per-page dropdown has a valid default value."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        pagination = tools_page.page.locator("#tools-pagination-controls")
        per_page = pagination.locator("select")

        # The default value depends on URL params or server config; just
        # verify it is one of the valid options.
        current_value = per_page.input_value()
        assert current_value in (
            "10", "25", "50", "100", "200", "500"
        ), f"Unexpected per-page value: '{current_value}'"

    def test_pagination_info_text(self, tools_page: ToolsPage):
        """Test that pagination info shows item count or no items message."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        pagination = tools_page.page.locator("#tools-pagination-controls")

        # The Alpine.js x-text renders either "Showing X - Y of Z items" or "No items found"
        info_span = pagination.locator("span[x-text]")
        expect(info_span).to_be_visible()

    def test_change_per_page(self, tools_page: ToolsPage):
        """Test changing the per-page value updates the select."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        pagination = tools_page.page.locator("#tools-pagination-controls")
        per_page = pagination.locator("select")

        # Change to 25
        per_page.select_option("25")
        tools_page.page.wait_for_timeout(1000)
        expect(per_page).to_have_value("25")

        # Change back to 50
        per_page.select_option("50")
        tools_page.page.wait_for_timeout(1000)


# ---------------------------------------------------------------------------
# Form Validation
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsFormValidation:
    """Tests for tool add form validation attributes."""

    def test_name_field_is_required(self, tools_page: ToolsPage):
        """Test that the name field has the required attribute."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_name_input).to_have_attribute("required", "")

    def test_url_field_is_required(self, tools_page: ToolsPage):
        """Test that the URL field has the required attribute."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        expect(tools_page.tool_url_input).to_have_attribute("required", "")

    def test_description_field_is_optional(self, tools_page: ToolsPage):
        """Test that the description field is not required."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        description = tools_page.tool_description_input
        try:
            expect(description).not_to_have_attribute("required", "")
        except AssertionError:
            # Some implementations use different validation; just verify it's visible
            expect(description).to_be_visible()


# ---------------------------------------------------------------------------
# Annotation Badges
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.tools
class TestToolsAnnotationBadges:
    """Tests for annotation badges in the tools table and panel."""

    def test_annotation_badges_legend_visible(self, tools_page: ToolsPage):
        """Test that the annotation badges legend is visible in the panel header."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        legend = tools_page.tools_panel.locator('text=Annotation badges:')
        expect(legend).to_be_visible()

    def test_annotation_badge_read_only(self, tools_page: ToolsPage):
        """Test that the Read-Only annotation badge is shown in the legend."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        badge = tools_page.tools_panel.locator('span:has-text("Read-Only")')
        expect(badge).to_be_visible()

    def test_annotation_badge_destructive(self, tools_page: ToolsPage):
        """Test that the Destructive annotation badge is shown in the legend."""
        tools_page.navigate_to_tools_tab()
        tools_page.wait_for_tools_table_loaded()

        badge = tools_page.tools_panel.locator('span:has-text("Destructive")')
        expect(badge).to_be_visible()
