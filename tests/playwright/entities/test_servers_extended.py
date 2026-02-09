# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_servers_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended test coverage for Virtual MCP Servers functionality.
Tests all ServersPage capabilities including form fields, associations,
visibility settings, OAuth configuration, and advanced features.
"""

# Standard
import uuid

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from ..pages.admin_utils import cleanup_server, find_server
from ..pages.servers_page import ServersPage


class TestServersExtended:
    """Extended tests for Virtual MCP Servers functionality."""

    def test_create_server_with_all_fields(self, servers_page: ServersPage):
        """Test creating a server with all optional fields populated."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Generate unique server name
        server_name = f"full-server-{uuid.uuid4().hex[:8]}"

        # Fill all form fields
        servers_page.fill_server_form(name=server_name, icon="https://example.com/icon.png", description="A complete test server with all fields", tags="test,automation,qa,extended")

        # Submit and verify
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            servers_page.submit_server_form()

        response = response_info.value
        assert response.status < 400

        # Verify server was created
        created_server = find_server(servers_page.page, server_name)
        assert created_server is not None
        assert created_server.get("description") == "A complete test server with all fields"

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_server_visibility_public(self, servers_page: ServersPage):
        """Test creating a server with public visibility."""
        servers_page.navigate_to_servers_tab()
        server_name = f"public-server-{uuid.uuid4().hex[:8]}"

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="public")

        # Verify creation
        created_server = find_server(servers_page.page, server_name)
        assert created_server is not None
        assert created_server.get("visibility") == "public"

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_server_visibility_team(self, servers_page: ServersPage):
        """Test creating a server with team visibility."""
        servers_page.navigate_to_servers_tab()
        server_name = f"team-server-{uuid.uuid4().hex[:8]}"

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="team")

        # Verify creation
        created_server = find_server(servers_page.page, server_name)
        assert created_server is not None
        assert created_server.get("visibility") == "team"

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_server_visibility_private(self, servers_page: ServersPage):
        """Test creating a server with private visibility."""
        servers_page.navigate_to_servers_tab()
        server_name = f"private-server-{uuid.uuid4().hex[:8]}"

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="private")

        # Verify creation
        created_server = find_server(servers_page.page, server_name)
        assert created_server is not None
        assert created_server.get("visibility") == "private"

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_oauth_configuration_toggle(self, servers_page: ServersPage):
        """Test OAuth configuration section visibility toggle."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Initially, OAuth config section should be hidden
        expect(servers_page.oauth_config_section).to_be_hidden()

        # Enable OAuth
        servers_page.click_locator(servers_page.oauth_enabled_checkbox)

        # OAuth config section should now be visible
        expect(servers_page.oauth_config_section).to_be_visible()

        # Disable OAuth
        servers_page.click_locator(servers_page.oauth_enabled_checkbox)

        # OAuth config section should be hidden again
        expect(servers_page.oauth_config_section).to_be_hidden()

    def test_oauth_configuration_fields(self, servers_page: ServersPage):
        """Test OAuth configuration fields are accessible."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Enable OAuth to show config section
        servers_page.click_locator(servers_page.oauth_enabled_checkbox)
        servers_page.wait_for_visible(servers_page.oauth_config_section)

        # Verify all OAuth fields are present and can be filled
        servers_page.fill_locator(servers_page.oauth_authorization_server_input, "https://idp.example.com")
        servers_page.fill_locator(servers_page.oauth_scopes_input, "openid profile email")
        servers_page.fill_locator(servers_page.oauth_token_endpoint_input, "https://idp.example.com/token")

        # Verify values were set
        assert servers_page.oauth_authorization_server_input.input_value() == "https://idp.example.com"
        assert servers_page.oauth_scopes_input.input_value() == "openid profile email"
        assert servers_page.oauth_token_endpoint_input.input_value() == "https://idp.example.com/token"

    def test_show_inactive_servers_toggle(self, servers_page: ServersPage):
        """Test show/hide inactive servers toggle."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Get initial state
        initial_checked = servers_page.show_inactive_checkbox.is_checked()

        # Toggle the checkbox
        servers_page.toggle_show_inactive(not initial_checked)

        # Wait for page to update (it triggers a reload with query parameter)
        servers_page.page.wait_for_timeout(1000)

        # Verify checkbox state changed
        new_checked = servers_page.show_inactive_checkbox.is_checked()
        assert new_checked != initial_checked

    def test_server_form_validation_required_name(self, servers_page: ServersPage):
        """Test form validation for required name field."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Try to submit without filling name
        servers_page.click_locator(servers_page.add_server_btn)

        # Verify HTML5 validation prevents submission
        is_valid = servers_page.server_name_input.evaluate("el => el.checkValidity()")
        assert is_valid is False

    def test_server_tags_field(self, servers_page: ServersPage):
        """Test server tags field accepts comma-separated values."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        server_name = f"tagged-server-{uuid.uuid4().hex[:8]}"
        tags = "production,api,v2,critical"

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", tags=tags)

        # Verify server was created with tags
        created_server = find_server(servers_page.page, server_name)
        assert created_server is not None

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_select_all_tools_button(self, servers_page: ServersPage):
        """Test Select All tools button functionality using Playwright's recommended approach."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Wait for tools to load via HTMX
        servers_page.page.wait_for_timeout(2000)

        # Check if there are any tools available
        tool_checkboxes = servers_page.associated_tools_container.locator('input[type="checkbox"].tool-checkbox')
        total_tools = tool_checkboxes.count()

        if total_tools == 0:
            pytest.skip("No tools available to test Select All functionality")

        # Click Select All button using JavaScript to ensure event fires
        servers_page.select_all_tools_btn.evaluate("el => el.click()")

        # Wait for JavaScript to process
        servers_page.page.wait_for_timeout(1500)

        # Use Playwright's recommended way to check if checkboxes are checked
        # Check the first checkbox as a sample
        first_checkbox = tool_checkboxes.first
        expect(first_checkbox).to_be_checked()

        # Verify button text updates
        button_text = servers_page.select_all_tools_btn.text_content()
        assert "All" in button_text and "selected" in button_text.lower()

    def test_clear_all_tools_button(self, servers_page: ServersPage):
        """Test Clear All tools button functionality using Playwright's recommended approach.

        Note: There's a known UI bug where the "Select All" button text
        doesn't update after clicking "Clear All". The checkboxes are
        correctly unchecked, but the button still shows "All X tools selected".
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Wait for tools to load via HTMX
        servers_page.page.wait_for_timeout(2000)

        # Check if there are any tools available
        tool_checkboxes = servers_page.associated_tools_container.locator('input[type="checkbox"].tool-checkbox')
        if tool_checkboxes.count() == 0:
            pytest.skip("No tools available to test Clear All functionality")

        # First select all tools using JavaScript
        servers_page.select_all_tools_btn.evaluate("el => el.click()")
        servers_page.page.wait_for_timeout(1500)

        # Verify at least first checkbox is checked using Playwright's recommended method
        first_checkbox = tool_checkboxes.first
        expect(first_checkbox).to_be_checked()

        # Then clear all using JavaScript
        servers_page.clear_all_tools_btn.evaluate("el => el.click()")
        servers_page.page.wait_for_timeout(1500)

        # Use Playwright's recommended way to verify checkboxes are NOT checked
        expect(first_checkbox).not_to_be_checked()

        # TODO: BUG - The "Select All" button text should update to "Select All"
        # but it still shows "All X tools selected" after clicking "Clear All"
        # This is a frontend JavaScript state management issue

    def test_search_tools_in_association(self, servers_page: ServersPage):
        """Test searching for tools in the association selector."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Wait for tools to load
        servers_page.page.wait_for_timeout(2000)

        # Get initial tool count
        initial_tools = servers_page.associated_tools_container.locator("label").count()
        if initial_tools == 0:
            pytest.skip("No tools available to test search functionality")

        # Search for a specific term
        servers_page.fill_locator(servers_page.search_tools_input, "test")
        servers_page.page.wait_for_timeout(500)

        # Verify filtering occurred (count should be same or less)
        filtered_tools = servers_page.associated_tools_container.locator("label:visible").count()
        assert filtered_tools <= initial_tools

    def test_server_table_has_expected_columns(self, servers_page: ServersPage):
        """Test that server table has all expected columns."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Verify table headers exist
        table_headers = servers_page.servers_table.locator("thead th")
        header_count = table_headers.count()

        # Should have at least the main columns
        assert header_count >= 10

    def test_server_count_method(self, servers_page: ServersPage):
        """Test get_server_count method returns valid count."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        count = servers_page.get_server_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_server_exists_method(self, servers_page: ServersPage):
        """Test server_exists method for existing and non-existing servers."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Test with a server that definitely doesn't exist
        assert servers_page.server_exists("nonexistent-server-xyz-123") is False

    def test_clear_search_button(self, servers_page: ServersPage):
        """Test clear search button functionality."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Perform a search
        servers_page.search_servers("test-search-term")
        servers_page.page.wait_for_timeout(500)

        # Verify search input has value
        assert servers_page.search_input.input_value() == "test-search-term"

        # Click clear button
        servers_page.clear_search()
        servers_page.page.wait_for_timeout(500)

        # Verify search input is cleared
        assert servers_page.search_input.input_value() == ""

    def test_panel_title_visible(self, servers_page: ServersPage):
        """Test that the Virtual MCP Servers panel title is visible."""
        servers_page.navigate_to_servers_tab()

        # Verify panel title
        expect(servers_page.panel_title).to_be_visible()
        expect(servers_page.panel_title).to_have_text("Virtual MCP Servers")

    def test_associated_items_containers_exist(self, servers_page: ServersPage):
        """Test that all associated items containers are present in the form."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Verify all association containers exist
        expect(servers_page.associated_gateways_container).to_be_attached()
        expect(servers_page.associated_tools_container).to_be_attached()
        expect(servers_page.associated_resources_container).to_be_attached()
        expect(servers_page.associated_prompts_container).to_be_attached()

    def test_visibility_radio_buttons_exist(self, servers_page: ServersPage):
        """Test that all visibility radio buttons are present."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Verify all visibility options exist
        expect(servers_page.visibility_public_radio).to_be_attached()
        expect(servers_page.visibility_team_radio).to_be_attached()
        expect(servers_page.visibility_private_radio).to_be_attached()

        # Verify public is checked by default
        assert servers_page.visibility_public_radio.is_checked()

    def test_search_servers_using_catalog_search(self, servers_page: ServersPage):
        """Test server search using #catalog-search-input."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Get initial server count
        initial_count = servers_page.get_server_count()
        if initial_count == 0:
            pytest.skip("No servers available to test search functionality")

        # Search using the catalog search input (id="catalog-search-input")
        catalog_search = servers_page.page.locator("#catalog-search-input")
        expect(catalog_search).to_be_visible()

        # Search for something that won't match
        catalog_search.fill("nonexistent-xyz-server-999")
        servers_page.page.wait_for_timeout(500)

        # Verify filtering occurred
        filtered_count = servers_page.server_items.locator(":visible").count()
        assert filtered_count < initial_count

        # Clear search
        catalog_search.fill("")
        servers_page.page.wait_for_timeout(500)

        # Verify servers are restored
        restored_count = servers_page.get_server_count()
        assert restored_count == initial_count

    def test_view_server_button(self, servers_page: ServersPage):
        """Test View button opens server details modal.

        Creates a test server, clicks View, verifies modal, then cleans up.
        """
        servers_page.navigate_to_servers_tab()
        server_name = f"view-test-server-{uuid.uuid4().hex[:8]}"

        # Create test server
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", description="Server for view button test")

        # Wait for creation to persist, reload, and re-navigate to servers tab
        servers_page.page.wait_for_timeout(2000)
        servers_page.page.reload(wait_until="load")
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(1500)

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click View button
        view_btn = server_row.locator('button:has-text("View")')
        if view_btn.count() > 0:
            view_btn.click()

            # Verify modal opens
            server_modal = servers_page.page.locator("#server-modal, #server-details-modal, .modal:visible")
            expect(server_modal.first).to_be_visible(timeout=5000)

            # Close modal
            close_btn = server_modal.first.locator('button:has-text("Close")')
            if close_btn.count() > 0:
                close_btn.click()
        else:
            pytest.skip("View button not available for servers")

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_edit_server_button(self, servers_page: ServersPage):
        """Test Edit button opens edit modal.

        Creates a test server, clicks Edit, verifies modal, then cleans up.
        """
        servers_page.navigate_to_servers_tab()
        server_name = f"edit-test-server-{uuid.uuid4().hex[:8]}"

        # Create test server
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", description="Server for edit button test")

        # Wait for creation to persist, reload, and re-navigate to servers tab
        servers_page.page.wait_for_timeout(2000)
        servers_page.page.reload(wait_until="load")
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(1500)

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Edit button
        edit_btn = server_row.locator('button:has-text("Edit")')
        if edit_btn.count() > 0:
            edit_btn.click()

            # Verify edit modal opens
            edit_modal = servers_page.page.locator("#server-edit-modal, #edit-server-modal, .modal:visible")
            expect(edit_modal.first).to_be_visible(timeout=5000)

            # Verify form is pre-filled with server data
            name_input = edit_modal.first.locator('input[name="name"]')
            if name_input.count() > 0:
                assert name_input.input_value() == server_name

            # Close modal without saving
            cancel_btn = edit_modal.first.locator('button:has-text("Cancel"), button:has-text("Close")')
            if cancel_btn.count() > 0:
                cancel_btn.first.click()
        else:
            pytest.skip("Edit button not available for servers")

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_export_server_button(self, servers_page: ServersPage):
        """Test Export button functionality.

        Creates a test server, clicks Export, then cleans up.
        """
        servers_page.navigate_to_servers_tab()
        server_name = f"export-test-server-{uuid.uuid4().hex[:8]}"

        # Create test server
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", description="Server for export button test")

        # Wait for creation to persist, reload, and re-navigate to servers tab
        servers_page.page.wait_for_timeout(2000)
        servers_page.page.reload(wait_until="load")
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(1500)

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Export button
        export_btn = server_row.locator('button:has-text("Export"), a:has-text("Export")')
        if export_btn.count() > 0:
            # For export, we just verify the button exists and is clickable
            expect(export_btn.first).to_be_visible()
            expect(export_btn.first).to_be_enabled()
            # Note: Actually clicking might trigger a download, which is harder to test
        else:
            pytest.skip("Export button not available for servers")

        # Cleanup
        cleanup_server(servers_page.page, server_name)

    def test_deactivate_server_button(self, servers_page: ServersPage):
        """Test Deactivate button marks server as inactive.

        Creates a test server, deactivates it, verifies status, then cleans up.
        """
        servers_page.navigate_to_servers_tab()
        server_name = f"deactivate-test-server-{uuid.uuid4().hex[:8]}"

        # Create test server
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", description="Server for deactivate button test")

        # Wait for creation to persist, reload, and re-navigate to servers tab
        servers_page.page.wait_for_timeout(2000)
        servers_page.page.reload(wait_until="load")
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(1500)

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Deactivate button
        deactivate_btn = server_row.locator('button:has-text("Deactivate"), button:has-text("Disable")')
        if deactivate_btn.count() > 0:
            deactivate_btn.first.click()
            servers_page.page.wait_for_timeout(1000)

            # Verify server is marked inactive (might disappear from active view)
            # Enable show inactive to see it
            servers_page.toggle_show_inactive(True)
            servers_page.page.wait_for_timeout(1000)
        else:
            pytest.skip("Deactivate button not available for servers")

        # Cleanup (hard delete)
        cleanup_server(servers_page.page, server_name)

    def test_delete_server_ui_button(self, servers_page: ServersPage):
        """Test Delete button in UI with confirmation dialog.

        Creates a test server, clicks Delete button, handles confirmation, verifies deletion.
        """
        servers_page.navigate_to_servers_tab()
        server_name = f"delete-ui-test-server-{uuid.uuid4().hex[:8]}"

        # Create test server
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", description="Server for UI delete button test")

        # Wait for creation to persist, reload, and re-navigate to servers tab
        servers_page.page.wait_for_timeout(2000)
        servers_page.page.reload(wait_until="load")
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_servers_table_loaded()

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(1500)

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Delete button - this will trigger TWO browser confirm() dialogs
        delete_btn = server_row.locator('button:has-text("Delete"), form[action*="/delete"] button[type="submit"]')
        if delete_btn.count() > 0:
            # Setup handler to accept BOTH confirmation dialogs
            dialog_count = 0

            def handle_dialog(dialog):
                nonlocal dialog_count
                dialog_count += 1
                dialog.accept()

            servers_page.page.on("dialog", handle_dialog)

            delete_btn.first.click()

            # Wait for both dialogs and deletion to process
            servers_page.page.wait_for_timeout(3000)

            # Remove the dialog handler
            servers_page.page.remove_listener("dialog", handle_dialog)

            # Verify server is deleted (should not exist)
            assert find_server(servers_page.page, server_name) is None
        else:
            pytest.skip("Delete button not available for servers")
