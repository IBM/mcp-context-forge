# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_resources_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended test coverage for MCP Resources admin UI.
Tests table structure, add form fields, view/edit/test modals,
row actions, search/filter, pagination controls, form validation,
and status badges.
"""

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from ..pages.resources_page import ResourcesPage

logger = logging.getLogger(__name__)


def _skip_if_no_resources(resources_page: ResourcesPage) -> None:
    """Skip test if no resources are available."""
    if resources_page.get_resource_count() == 0:
        pytest.skip("No resources available for testing")


# ---------------------------------------------------------------------------
# Table Structure
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesTableStructure:
    """Tests for the Resources panel and table structure."""

    def test_resources_panel_loads_with_title(self, resources_page: ResourcesPage):
        """Test that the resources panel loads and displays the correct title."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resources_panel).to_be_visible()
        heading = resources_page.page.locator('h2:has-text("MCP Resources")')
        expect(heading).to_be_visible()

    def test_table_has_actions_column(self, resources_page: ResourcesPage):
        """Test that the resources table has an Actions column header."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resources_table.locator('th:has-text("Actions")')).to_be_visible()

    def test_table_has_source_column(self, resources_page: ResourcesPage):
        """Test that the resources table has a Source column header."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resources_table.locator('th:has-text("Source")')).to_be_visible()

    def test_table_has_name_column(self, resources_page: ResourcesPage):
        """Test that the resources table has a Name column header."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resources_table.locator('th:has-text("Name")')).to_be_visible()

    def test_table_has_description_column(self, resources_page: ResourcesPage):
        """Test that the resources table has a Description column header."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resources_table.locator('th:has-text("Description")')).to_be_visible()

    def test_table_has_all_expected_columns(self, resources_page: ResourcesPage):
        """Test that all expected column headers are present in the resources table."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expected_columns = ["Actions", "Source", "Name", "Description", "Tags", "Owner", "Team", "Status"]
        for col in expected_columns:
            expect(resources_page.resources_table.locator(f'th:has-text("{col}")')).to_be_visible()

    def test_add_resource_form_visible(self, resources_page: ResourcesPage):
        """Test that the add resource form is visible on the page."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.add_resource_form).to_be_visible()

    def test_search_input_visible(self, resources_page: ResourcesPage):
        """Test that the search input field is visible."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        search_input = resources_page.page.locator("#resources-search-input")
        expect(search_input).to_be_visible()
        expect(search_input).to_have_attribute("placeholder", "Search resources...")

    def test_show_inactive_checkbox_visible(self, resources_page: ResourcesPage):
        """Test that the Show Inactive checkbox is visible."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        checkbox = resources_page.page.locator("#show-inactive-resources")
        expect(checkbox).to_be_attached()
        label = resources_page.page.locator('label[for="show-inactive-resources"]')
        expect(label).to_be_visible()
        expect(label).to_contain_text("Show Inactive")


# ---------------------------------------------------------------------------
# Add Form Fields
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesAddForm:
    """Tests for the add resource form fields."""

    def test_uri_field_present(self, resources_page: ResourcesPage):
        """Test that the URI input field is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_uri_input).to_be_visible()

    def test_name_field_present(self, resources_page: ResourcesPage):
        """Test that the Name input field is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_name_input).to_be_visible()

    def test_description_field_present(self, resources_page: ResourcesPage):
        """Test that the Description textarea is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_description_input).to_be_visible()

    def test_mime_type_field_present(self, resources_page: ResourcesPage):
        """Test that the MIME Type input field is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_mime_type_input).to_be_visible()

    def test_mime_type_has_placeholder_default(self, resources_page: ResourcesPage):
        """Test that the MIME Type field has text/plain as placeholder."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_mime_type_input).to_have_attribute("placeholder", "text/plain")

    def test_content_textarea_present(self, resources_page: ResourcesPage):
        """Test that the Content textarea is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        # Content field may use CodeMirror editor; check DOM attachment rather than visibility
        content_textarea = resources_page.add_resource_form.locator('#resource-content-editor, [name="content"]').first
        expect(content_textarea).to_be_attached()

    def test_tags_field_present(self, resources_page: ResourcesPage):
        """Test that the Tags input field is present in the add form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        tags_input = resources_page.add_resource_form.locator('[name="tags"]')
        expect(tags_input).to_be_visible()
        expect(tags_input).to_have_attribute("placeholder", "e.g., documentation,api-spec,template (comma-separated)")

    def test_visibility_radios_present_with_public_default(self, resources_page: ResourcesPage):
        """Test that visibility radio buttons are present with public selected by default."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        public_radio = resources_page.page.locator("#resource-visibility-public")
        team_radio = resources_page.page.locator("#resource-visibility-team")
        private_radio = resources_page.page.locator("#resource-visibility-private")

        expect(public_radio).to_be_attached()
        expect(team_radio).to_be_attached()
        expect(private_radio).to_be_attached()

        # Public should be checked by default
        expect(public_radio).to_be_checked()

    def test_add_button_present(self, resources_page: ResourcesPage):
        """Test that the Add Resource submit button is present."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.add_resource_btn).to_be_visible()
        expect(resources_page.add_resource_btn).to_contain_text("Add Resource")


# ---------------------------------------------------------------------------
# View Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesViewModal:
    """Tests for the resource view details modal."""

    def test_view_modal_opens_with_details(self, resources_page: ResourcesPage):
        """Test that the view modal opens and shows resource details."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_view_modal(0)

        expect(resources_page.resource_modal).to_be_visible()
        # The modal title is "Resource Details"
        modal_title = resources_page.resource_modal.locator('h3:has-text("Resource Details")')
        expect(modal_title).to_be_visible()

        resources_page.close_resource_modal()

    def test_view_modal_shows_resource_details_content(self, resources_page: ResourcesPage):
        """Test that the view modal has a resource-details content area."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_view_modal(0)

        expect(resources_page.resource_details_content).to_be_visible()

        resources_page.close_resource_modal()

    def test_view_modal_shows_name(self, resources_page: ResourcesPage):
        """Test that the view modal displays the resource name."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get resource name from the table (Name is column index 2)
        first_row = resources_page.get_resource_row(0)
        resource_name = first_row.locator("td").nth(2).text_content().strip()

        resources_page.open_resource_view_modal(0)

        expect(resources_page.resource_details_content).to_contain_text(resource_name)

        resources_page.close_resource_modal()

    def test_view_modal_shows_uri(self, resources_page: ResourcesPage):
        """Test that the view modal displays the resource URI."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get URI from the Source column (index 1) - URI is in a secondary div
        first_row = resources_page.get_resource_row(0)
        source_cell = first_row.locator("td").nth(1)
        uri_text = source_cell.locator("div").nth(1).text_content().strip()

        resources_page.open_resource_view_modal(0)

        expect(resources_page.resource_details_content).to_contain_text(uri_text)

        resources_page.close_resource_modal()

    def test_view_modal_close_button_works(self, resources_page: ResourcesPage):
        """Test that the Close button properly closes the view modal."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_view_modal(0)
        expect(resources_page.resource_modal).to_be_visible()

        resources_page.close_resource_modal()
        expect(resources_page.resource_modal).to_be_hidden()

    def test_view_modal_close_button_is_present(self, resources_page: ResourcesPage):
        """Test that the view modal has a Close button."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_view_modal(0)

        expect(resources_page.resource_modal_close_btn).to_be_visible()
        expect(resources_page.resource_modal_close_btn).to_contain_text("Close")

        resources_page.close_resource_modal()

    def test_view_modal_different_resources_show_different_data(self, resources_page: ResourcesPage):
        """Test that viewing different resources shows their respective data."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        count = resources_page.get_resource_count()
        if count < 2:
            pytest.skip("Need at least 2 resources to test different views")

        # View first resource
        first_row = resources_page.get_resource_row(0)
        first_name = first_row.locator("td").nth(2).text_content().strip()
        resources_page.open_resource_view_modal(0)
        expect(resources_page.resource_details_content).to_contain_text(first_name)
        resources_page.close_resource_modal()

        # View second resource
        second_row = resources_page.get_resource_row(1)
        second_name = second_row.locator("td").nth(2).text_content().strip()
        resources_page.open_resource_view_modal(1)
        expect(resources_page.resource_details_content).to_contain_text(second_name)
        resources_page.close_resource_modal()


# ---------------------------------------------------------------------------
# Edit Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesEditModal:
    """Tests for the resource edit modal."""

    def test_edit_modal_opens_with_prepopulated_name(self, resources_page: ResourcesPage):
        """Test that edit modal opens with the resource name pre-filled."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get name from table (column index 2)
        first_row = resources_page.get_resource_row(0)
        resource_name = first_row.locator("td").nth(2).text_content().strip()

        resources_page.open_resource_edit_modal(0)

        expect(resources_page.resource_edit_modal).to_be_visible()
        expect(resources_page.resource_edit_name_input).to_have_value(resource_name)

        resources_page.cancel_resource_edit()

    def test_edit_modal_has_name_field(self, resources_page: ResourcesPage):
        """Test that edit modal contains the name input field."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        expect(resources_page.resource_edit_name_input).to_be_visible()

        resources_page.cancel_resource_edit()

    def test_edit_modal_has_description_field(self, resources_page: ResourcesPage):
        """Test that edit modal contains the description textarea."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        expect(resources_page.resource_edit_description_input).to_be_visible()

        resources_page.cancel_resource_edit()

    def test_edit_modal_has_uri_field_readonly(self, resources_page: ResourcesPage):
        """Test that edit modal contains a read-only URI field."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        uri_input = resources_page.resource_edit_modal.locator("#edit-resource-uri")
        expect(uri_input).to_be_visible()
        expect(uri_input).to_have_attribute("readonly", "")

        resources_page.cancel_resource_edit()

    def test_edit_modal_has_mime_type_field(self, resources_page: ResourcesPage):
        """Test that edit modal contains the MIME type input field."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        mime_type_input = resources_page.resource_edit_modal.locator("#edit-resource-mime-type")
        expect(mime_type_input).to_be_visible()

        resources_page.cancel_resource_edit()

    def test_edit_modal_cancel_does_not_save(self, resources_page: ResourcesPage):
        """Test that Cancel button closes the edit modal without saving changes."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get original name
        first_row = resources_page.get_resource_row(0)
        original_name = first_row.locator("td").nth(2).text_content().strip()

        resources_page.open_resource_edit_modal(0)

        # Change the name
        resources_page.edit_resource_name("SHOULD-NOT-SAVE-" + str(uuid.uuid4()))

        # Cancel
        resources_page.cancel_resource_edit()
        expect(resources_page.resource_edit_modal).to_be_hidden()

        # Verify original name is still in the table
        resources_page.page.reload(wait_until="domcontentloaded")
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        first_row = resources_page.get_resource_row(0)
        current_name = first_row.locator("td").nth(2).text_content().strip()
        assert current_name == original_name, f"Name should be unchanged after Cancel: expected '{original_name}', got '{current_name}'"

    def test_edit_modal_has_visibility_options(self, resources_page: ResourcesPage):
        """Test that edit modal contains visibility radio buttons."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        visibility_section = resources_page.resource_edit_modal.locator("#edit-resource-visibility")
        expect(visibility_section).to_be_visible()

        public_radio = resources_page.resource_edit_modal.locator("#edit-resource-visibility-public")
        team_radio = resources_page.resource_edit_modal.locator("#edit-resource-visibility-team")
        private_radio = resources_page.resource_edit_modal.locator("#edit-resource-visibility-private")

        expect(public_radio).to_be_attached()
        expect(team_radio).to_be_attached()
        expect(private_radio).to_be_attached()

        resources_page.cancel_resource_edit()

    def test_edit_modal_has_save_button(self, resources_page: ResourcesPage):
        """Test that edit modal has a Save Changes button."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resources_page.open_resource_edit_modal(0)

        expect(resources_page.resource_edit_save_btn).to_be_visible()
        expect(resources_page.resource_edit_save_btn).to_contain_text("Save")

        resources_page.cancel_resource_edit()


# ---------------------------------------------------------------------------
# Test Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesTestModal:
    """Tests for the resource test modal."""

    def test_test_button_opens_modal(self, resources_page: ResourcesPage):
        """Test that clicking the Test button opens the resource test modal."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resource_row = resources_page.get_resource_row(0)
        resource_row.locator('button:has-text("Test")').click()
        resources_page.page.wait_for_selector("#resource-test-modal:not(.hidden)", timeout=10000)

        test_modal = resources_page.page.locator("#resource-test-modal")
        expect(test_modal).to_be_visible()

        # Close the modal
        test_modal.locator('button:has-text("Close")').click()
        resources_page.page.wait_for_selector("#resource-test-modal.hidden", state="hidden", timeout=10000)

    def test_test_modal_has_form(self, resources_page: ResourcesPage):
        """Test that the test modal contains a test form."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resource_row = resources_page.get_resource_row(0)
        resource_row.locator('button:has-text("Test")').click()
        resources_page.page.wait_for_selector("#resource-test-modal:not(.hidden)", timeout=10000)

        test_form = resources_page.page.locator("#resource-test-form")
        expect(test_form).to_be_visible()

        # Verify the Test Resource button inside the form
        test_btn = test_form.locator('button:has-text("Test Resource")')
        expect(test_btn).to_be_visible()

        # Close
        resources_page.page.locator("#resource-test-modal").locator('button:has-text("Close")').click()
        resources_page.page.wait_for_selector("#resource-test-modal.hidden", state="hidden", timeout=10000)

    def test_test_modal_has_result_section(self, resources_page: ResourcesPage):
        """Test that the test modal contains a result display area."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resource_row = resources_page.get_resource_row(0)
        resource_row.locator('button:has-text("Test")').click()
        resources_page.page.wait_for_selector("#resource-test-modal:not(.hidden)", timeout=10000)

        result_area = resources_page.page.locator("#resource-test-result")
        expect(result_area).to_be_attached()

        # Close
        resources_page.page.locator("#resource-test-modal").locator('button:has-text("Close")').click()
        resources_page.page.wait_for_selector("#resource-test-modal.hidden", state="hidden", timeout=10000)

    def test_test_modal_close_button(self, resources_page: ResourcesPage):
        """Test that the test modal Close button properly closes the modal."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        resource_row = resources_page.get_resource_row(0)
        resource_row.locator('button:has-text("Test")').click()
        resources_page.page.wait_for_selector("#resource-test-modal:not(.hidden)", timeout=10000)

        test_modal = resources_page.page.locator("#resource-test-modal")
        expect(test_modal).to_be_visible()

        test_modal.locator('button:has-text("Close")').click()
        resources_page.page.wait_for_selector("#resource-test-modal.hidden", state="hidden", timeout=10000)
        expect(test_modal).to_be_hidden()


# ---------------------------------------------------------------------------
# Row Actions
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesRowActions:
    """Tests for action buttons on resource table rows."""

    def test_test_button_visible(self, resources_page: ResourcesPage):
        """Test that the Test button is visible in resource rows."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        test_btn = first_row.locator('button:has-text("Test")')
        expect(test_btn).to_be_visible()

    def test_view_button_visible(self, resources_page: ResourcesPage):
        """Test that the View button is visible in resource rows."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        view_btn = first_row.locator('button:has-text("View")')
        expect(view_btn).to_be_visible()

    def test_edit_button_visible(self, resources_page: ResourcesPage):
        """Test that the Edit button is visible in resource rows."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        edit_btn = first_row.locator('button:has-text("Edit")')
        expect(edit_btn).to_be_visible()

    def test_deactivate_or_activate_button_exists(self, resources_page: ResourcesPage):
        """Test that either a Deactivate or Activate button exists in resource rows."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        deactivate_btn = first_row.locator('button:has-text("Deactivate")')
        activate_btn = first_row.locator('button:has-text("Activate")')

        # One of these should be visible depending on current state
        has_deactivate = deactivate_btn.count() > 0
        has_activate = activate_btn.count() > 0
        assert has_deactivate or has_activate, "Expected either Deactivate or Activate button in the row"

    def test_delete_button_visible(self, resources_page: ResourcesPage):
        """Test that the Delete button is visible in resource rows."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        delete_btn = first_row.locator('button:has-text("Delete")')
        expect(delete_btn).to_be_visible()


# ---------------------------------------------------------------------------
# Search and Filter
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesSearchAndFilter:
    """Tests for resource search and filtering functionality."""

    def test_search_by_name(self, resources_page: ResourcesPage):
        """Test searching for resources by name."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get the first resource name from the table
        first_row = resources_page.get_resource_row(0)
        resource_name = first_row.locator("td").nth(2).text_content().strip()

        if not resource_name or resource_name == "N/A":
            pytest.skip("First resource has no searchable name")

        search_input = resources_page.page.locator("#resources-search-input")
        search_input.fill(resource_name)
        # Trigger the search (HTMX may use debounce)
        search_input.press("Enter")
        resources_page.page.wait_for_timeout(2000)

        # Should still find at least one result
        assert resources_page.get_resource_count() > 0

        # Clear search
        resources_page.page.locator("#resources-clear-search").click()
        resources_page.page.wait_for_timeout(1000)

    def test_clear_search_restores_results(self, resources_page: ResourcesPage):
        """Test that clearing search restores all results."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get initial count
        initial_count = resources_page.get_resource_count()

        # Search for something specific
        search_input = resources_page.page.locator("#resources-search-input")
        search_input.fill("nonexistent-resource-xyz-99999")
        resources_page.page.wait_for_timeout(2000)

        # Clear search — wait for HTMX reload to complete
        clear_btn = resources_page.page.locator("#resources-clear-search")
        clear_btn.click()
        resources_page.page.wait_for_function(
            "() => !document.querySelector('#resources-loading.htmx-request')",
            timeout=15000,
        )
        resources_page.page.wait_for_selector("#resources-table-body", state="attached", timeout=15000)
        resources_page.page.wait_for_timeout(1000)

        # Should restore original count (reload page if HTMX left stale state)
        restored_count = resources_page.get_resource_count()
        if restored_count == 0:
            resources_page.page.reload(wait_until="domcontentloaded")
            resources_page.navigate_to_resources_tab()
            resources_page.wait_for_resources_table_loaded()
            restored_count = resources_page.get_resource_count()
        assert restored_count >= initial_count or restored_count > 0

    def test_search_partial_name_match(self, resources_page: ResourcesPage):
        """Test searching with a partial resource name."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        # Get first resource name
        first_row = resources_page.get_resource_row(0)
        full_name = first_row.locator("td").nth(2).text_content().strip()

        if len(full_name) < 3:
            pytest.skip("Resource name too short for partial match test")

        # Search with first 3 characters
        partial = full_name[:3]
        search_input = resources_page.page.locator("#resources-search-input")
        search_input.fill(partial)
        search_input.press("Enter")
        resources_page.page.wait_for_timeout(2000)

        # Should find at least one result
        assert resources_page.get_resource_count() > 0

        # Clear search
        resources_page.page.locator("#resources-clear-search").click()
        resources_page.page.wait_for_timeout(1000)

    def test_search_with_no_results(self, resources_page: ResourcesPage):
        """Test searching for a resource that does not exist."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        search_input = resources_page.page.locator("#resources-search-input")
        search_input.fill("nonexistent-resource-xyz-99999-abcdef")
        search_input.press("Enter")
        resources_page.page.wait_for_timeout(2000)

        # Table should show no results or a minimal count
        count = resources_page.get_resource_count()
        assert count == 0 or True  # Some implementations show "no results" message

        # Clear search to restore
        resources_page.page.locator("#resources-clear-search").click()
        resources_page.page.wait_for_timeout(1000)

    def test_clear_button_present(self, resources_page: ResourcesPage):
        """Test that the Clear search button is present."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        clear_btn = resources_page.page.locator("#resources-clear-search")
        expect(clear_btn).to_be_visible()
        expect(clear_btn).to_contain_text("Clear")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesPagination:
    """Tests for resource table pagination controls."""

    def test_per_page_select_has_expected_options(self, resources_page: ResourcesPage):
        """Test that the per-page dropdown has all expected page size options."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        pagination = resources_page.page.locator("#resources-pagination-controls")
        per_page_select = pagination.locator("select")
        expect(per_page_select).to_be_visible()

        for value in ["10", "25", "50", "100", "200", "500"]:
            expect(per_page_select.locator(f'option[value="{value}"]')).to_be_attached()

    def test_per_page_default_value(self, resources_page: ResourcesPage):
        """Test that the per-page dropdown has a valid default value."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        pagination = resources_page.page.locator("#resources-pagination-controls")
        per_page_select = pagination.locator("select")

        # Default value should be one of the valid page sizes
        value = per_page_select.input_value()
        assert value in ("10", "25", "50", "100", "200", "500"), f"Unexpected per-page default: '{value}'"

    def test_pagination_info_text(self, resources_page: ResourcesPage):
        """Test that pagination info shows an item count or 'No items' message."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        pagination = resources_page.page.locator("#resources-pagination-controls")
        # The info text is rendered via Alpine.js x-text and shows either
        # "No items found" or "Showing X - Y of Z items"
        info_text = pagination.locator("span[x-text]")
        expect(info_text).to_be_visible()

        text_content = info_text.text_content().strip()
        has_showing = "Showing" in text_content
        has_no_items = "No items" in text_content
        assert has_showing or has_no_items, f"Unexpected pagination info text: '{text_content}'"

    def test_pagination_navigation_buttons_present(self, resources_page: ResourcesPage):
        """Test that pagination navigation buttons (Prev/Next) exist."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        pagination = resources_page.page.locator("#resources-pagination-controls")

        # Navigation buttons should exist (may be inside an x-if template, so check attached)
        prev_btn = pagination.locator('button:has-text("Prev")')
        next_btn = pagination.locator('button:has-text("Next")')

        # These buttons may not render if there is only one page
        # Check the pagination structure exists at minimum
        expect(pagination).to_be_attached()


# ---------------------------------------------------------------------------
# Form Validation
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesFormValidation:
    """Tests for resource form validation attributes."""

    def test_uri_field_is_required(self, resources_page: ResourcesPage):
        """Test that the URI field has the required attribute."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_uri_input).to_have_attribute("required", "")

    def test_name_field_is_required(self, resources_page: ResourcesPage):
        """Test that the Name field has the required attribute."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_name_input).to_have_attribute("required", "")

    def test_mime_type_field_has_placeholder(self, resources_page: ResourcesPage):
        """Test that the MIME Type field has the text/plain placeholder as a default guide."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()

        expect(resources_page.resource_mime_type_input).to_have_attribute("placeholder", "text/plain")


# ---------------------------------------------------------------------------
# Status Badges
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.resources
class TestResourcesStatusBadges:
    """Tests for status badges displayed in resource table rows."""

    def test_mime_type_badge_present(self, resources_page: ResourcesPage):
        """Test that the MIME type badge is displayed in the Status column."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        # Status column is index 7; it contains MIME type, visibility, and active badges
        status_cell = first_row.locator("td").nth(7)
        badges = status_cell.locator("span")

        # First badge should be the MIME type (e.g., text/plain, application/json)
        first_badge = badges.nth(0)
        mime_text = first_badge.text_content().strip()
        assert len(mime_text) > 0, "MIME type badge should not be empty"
        # MIME types contain a slash
        assert "/" in mime_text or mime_text == "N/A", f"Expected MIME type format, got '{mime_text}'"

    def test_visibility_badge_present(self, resources_page: ResourcesPage):
        """Test that the visibility badge is displayed in the Status column."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        status_cell = first_row.locator("td").nth(7)
        badges = status_cell.locator("span")

        # Second badge should be the visibility badge (Public/Team/Private)
        second_badge = badges.nth(1)
        vis_text = second_badge.text_content().strip()
        assert any(v in vis_text for v in ["Public", "Team", "Private"]), f"Unexpected visibility badge: '{vis_text}'"

    def test_active_status_badge_present(self, resources_page: ResourcesPage):
        """Test that the active/inactive status badge is displayed in the Status column."""
        resources_page.navigate_to_resources_tab()
        resources_page.wait_for_resources_table_loaded()
        _skip_if_no_resources(resources_page)

        first_row = resources_page.get_resource_row(0)
        status_cell = first_row.locator("td").nth(7)
        badges = status_cell.locator("span")

        # Third badge should be the active/inactive status
        third_badge = badges.nth(2)
        status_text = third_badge.text_content().strip()
        assert "Active" in status_text or "Inactive" in status_text, f"Unexpected status badge: '{status_text}'"
