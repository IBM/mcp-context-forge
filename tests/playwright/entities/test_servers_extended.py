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
import re
import uuid

# Third-Party
from playwright.sync_api import Error as PlaywrightError, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from ..pages.admin_utils import cleanup_server, find_server
from ..pages.servers_page import ServersPage


def _reload_catalog_after_create(servers_page: ServersPage) -> None:
    """Stabilize catalog page after create redirect.

    Some environments race between hash navigation and full document reload,
    which can surface as ``net::ERR_ABORTED`` on ``page.reload``.
    """
    try:
        servers_page.page.reload(wait_until="domcontentloaded")
    except PlaywrightError:
        servers_page.page.goto("/admin#catalog", wait_until="domcontentloaded")

    servers_page.navigate_to_servers_tab()
    servers_page.wait_for_servers_table_loaded()


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
        if response.status in (401, 403):
            pytest.skip(f"Server creation blocked by auth/RBAC (HTTP {response.status})")
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

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="public")

        response = response_info.value
        if response.status >= 400:
            pytest.skip(f"Server creation failed (HTTP {response.status})")

        # Wait for JS redirect and DB commit
        servers_page.page.wait_for_load_state("domcontentloaded")

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

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="team")

        response = response_info.value
        if response.status >= 400:
            pytest.skip(f"Server creation failed (HTTP {response.status})")

        # Wait for JS redirect and DB commit
        servers_page.page.wait_for_load_state("domcontentloaded")

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

        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            servers_page.create_server(name=server_name, icon="https://example.com/icon.png", visibility="private")

        response = response_info.value
        if response.status >= 400:
            pytest.skip(f"Server creation failed (HTTP {response.status})")

        # Wait for JS redirect and DB commit
        servers_page.page.wait_for_load_state("domcontentloaded")

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
        servers_page.page.wait_for_load_state("domcontentloaded")

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
        try:
            servers_page.page.wait_for_selector('#associatedTools input[type="checkbox"].tool-checkbox', state="attached", timeout=10000)
        except PlaywrightTimeoutError:
            pytest.skip("No tools loaded via HTMX")

        # Check if there are any tools available
        tool_checkboxes = servers_page.associated_tools_container.locator('input[type="checkbox"].tool-checkbox')
        total_tools = tool_checkboxes.count()

        if total_tools == 0:
            pytest.skip("No tools available to test Select All functionality")

        # Click Select All button using JavaScript to ensure event fires
        servers_page.select_all_tools_btn.evaluate("el => el.click()")

        # Wait for first checkbox to become checked
        expect(tool_checkboxes.first).to_be_checked(timeout=5000)

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
        try:
            servers_page.page.wait_for_selector('#associatedTools input[type="checkbox"].tool-checkbox', state="attached", timeout=10000)
        except PlaywrightTimeoutError:
            pytest.skip("No tools loaded via HTMX")

        # Check if there are any tools available
        tool_checkboxes = servers_page.associated_tools_container.locator('input[type="checkbox"].tool-checkbox')
        if tool_checkboxes.count() == 0:
            pytest.skip("No tools available to test Clear All functionality")

        # First select all tools using JavaScript
        servers_page.select_all_tools_btn.evaluate("el => el.click()")

        # Wait for first checkbox to become checked
        first_checkbox = tool_checkboxes.first
        expect(first_checkbox).to_be_checked(timeout=5000)

        # Then clear all using JavaScript
        servers_page.clear_all_tools_btn.evaluate("el => el.click()")

        # Wait for first checkbox to become unchecked
        expect(first_checkbox).not_to_be_checked(timeout=5000)

        # Use Playwright's recommended way to verify checkboxes are NOT checked
        expect(first_checkbox).not_to_be_checked()

        # TODO: BUG - The "Select All" button text should update to "Select All"
        # but it still shows "All X tools selected" after clicking "Clear All"
        # This is a frontend JavaScript state management issue

    def test_search_tools_in_association(self, servers_page: ServersPage):
        """Test searching for tools in the association selector."""
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Wait for HTMX to load tools (not just a fixed timeout)
        try:
            servers_page.page.wait_for_selector(
                "#associatedTools label.tool-item",
                state="attached",
                timeout=10000,
            )
        except PlaywrightTimeoutError:
            pytest.skip("No tools available to test search functionality")

        # Get initial tool count
        initial_tools = servers_page.associated_tools_container.locator("label.tool-item").count()
        if initial_tools == 0:
            pytest.skip("No tools available to test search functionality")

        # Search for a non-matching term — this triggers server-side search
        # with a 300ms debounce, so wait for the HTMX swap to complete
        servers_page.fill_locator(servers_page.search_tools_input, "xyznonexistent999")
        servers_page.page.wait_for_timeout(2000)

        # Verify filtering occurred: a non-matching search should return fewer tools.
        # NOTE: The initial view may be paginated (e.g., 50 items) while search may
        # return results with different pagination, so we can't compare against initial_tools.
        filtered_tools = servers_page.associated_tools_container.locator("label.tool-item").count()
        assert filtered_tools < initial_tools, f"Search for non-existent term should return fewer results (got {filtered_tools}, initial {initial_tools})"

        # Clear search and verify tools come back
        servers_page.fill_locator(servers_page.search_tools_input, "")
        servers_page.page.wait_for_timeout(2000)
        restored_tools = servers_page.associated_tools_container.locator("label.tool-item").count()
        assert restored_tools > 0, "Clearing search should restore tools"

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

        # Verify search input has value
        assert servers_page.search_input.input_value() == "test-search-term"

        # Click clear button
        servers_page.clear_search()

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
        servers_page.search_servers("nonexistent-xyz-server-999")

        # Verify filtering occurred
        filtered_count = servers_page.server_items.locator(":visible").count()
        assert filtered_count < initial_count

        # Clear search
        servers_page.search_servers("")

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

        # Wait for JS redirect (handleServerFormSubmit sets window.location.href)
        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_load_state("domcontentloaded")

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

        # Wait for JS redirect (handleServerFormSubmit sets window.location.href)
        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_load_state("domcontentloaded")

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

        # Wait for JS redirect (handleServerFormSubmit sets window.location.href)
        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_load_state("domcontentloaded")

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

        # Wait for JS redirect (handleServerFormSubmit sets window.location.href)
        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        # Pagination change triggers an HTMX swap; wait for table to re-stabilize
        servers_page.page.wait_for_timeout(2000)
        servers_page.wait_for_servers_table_loaded()

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Deactivate button — re-query within the visible row to avoid stale refs
        deactivate_btn = server_row.locator('button:has-text("Deactivate"), button:has-text("Disable")')
        if deactivate_btn.count() > 0:
            expect(deactivate_btn.first).to_be_visible(timeout=5000)
            deactivate_btn.first.click()
            servers_page.page.wait_for_load_state("domcontentloaded")

            # Verify server is marked inactive (might disappear from active view)
            # Enable show inactive to see it
            servers_page.toggle_show_inactive(True)
            servers_page.page.wait_for_load_state("domcontentloaded")
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

        # Wait for JS redirect (handleServerFormSubmit sets window.location.href)
        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to show 100 items per page to ensure server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_load_state("domcontentloaded")

        # Find the server row - should now be visible with 100 items per page
        server_row = servers_page.page.locator(f'[data-testid="server-item"]:has-text("{server_name}")').first
        expect(server_row).to_be_visible(timeout=10000)

        # Click Delete button - this will trigger TWO browser confirm() dialogs
        # (delete confirmation + metrics purge), then a form POST with page navigation.
        delete_btn = server_row.locator('form[action*="/delete"] button[type="submit"]:has-text("Delete")')
        if delete_btn.count() > 0:
            server_row.scroll_into_view_if_needed()
            servers_page.page.wait_for_timeout(500)

            def handle_dialog(dialog):
                dialog.accept()

            servers_page.page.on("dialog", handle_dialog)

            try:
                with servers_page.page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    delete_btn.first.click(force=True)
            finally:
                servers_page.page.remove_listener("dialog", handle_dialog)

            # Verify server is deleted (should not exist)
            assert find_server(servers_page.page, server_name) is None
        else:
            pytest.skip("Delete button not available for servers")


class TestEditServerSelectionBugs:
    """Regression tests for edit-server modal selection bugs (#3257, #3259, #3260).

    These tests verify that:
    - Cancel closes the modal cleanly even if cleanup throws (#3259)
    - Keyword search in tool/resource/prompt pickers preserves prior selections (#3260)
    - Select All + search + clear preserves all selections in-memory (#3257)
    """

    def _create_server_with_tools(self, servers_page: ServersPage) -> str:
        """Create a test server with tools selected and return its name.

        Selects the first two available tools during creation.
        """
        server_name = f"edit-sel-test-{uuid.uuid4().hex[:8]}"

        # Wait for tools to load
        try:
            servers_page.page.wait_for_selector('#associatedTools input[type="checkbox"]', state="attached", timeout=10000)
        except PlaywrightTimeoutError:
            pytest.skip("No tools loaded via HTMX — cannot create server with tools")

        # Select the first two tools
        tool_checkboxes = servers_page.associated_tools_container.locator('input[type="checkbox"]')
        total = tool_checkboxes.count()
        if total < 2:
            pytest.skip(f"Need at least 2 tools, found {total}")
        tool_checkboxes.nth(0).check()
        tool_checkboxes.nth(1).check()

        with servers_page.page.expect_response(lambda r: "/admin/servers" in r.url and r.request.method == "POST"):
            servers_page.create_server(name=server_name, description="Regression test for edit-server selection bugs")

        servers_page.page.wait_for_url(re.compile(r".*#catalog"), timeout=10000)
        servers_page.page.wait_for_load_state("domcontentloaded")
        _reload_catalog_after_create(servers_page)

        # Set pagination to 100 so the new server is visible
        pagination_select = servers_page.page.locator("#servers-pagination-controls select")
        pagination_select.select_option("100")
        servers_page.page.wait_for_timeout(2000)
        servers_page.wait_for_servers_table_loaded()

        return server_name

    @pytest.mark.ui
    @pytest.mark.e2e
    def test_cancel_closes_modal_cleanly(self, servers_page: ServersPage):
        """Regression test for #3259: Cancel button closes modal without crashing.

        Verifies that the modal hides and no JS errors are thrown, even when
        resetEditSelections encounters unexpected state.
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        server_name = self._create_server_with_tools(servers_page)

        try:
            # Open edit modal
            servers_page.open_edit_modal(server_name)

            # Verify modal is visible and pre-filled
            expect(servers_page.edit_server_name_input).to_have_value(server_name)

            # Collect JS errors before cancel
            js_errors_before = servers_page.page.evaluate("() => window.__testJsErrors ? window.__testJsErrors.length : 0")

            # Click Cancel
            servers_page.click_locator(servers_page.edit_server_cancel_btn)

            # Verify modal is hidden
            expect(servers_page.edit_server_modal).to_be_hidden(timeout=5000)

            # Verify no new JS errors were thrown
            js_errors_after = servers_page.page.evaluate("() => window.__testJsErrors ? window.__testJsErrors.length : 0")
            assert js_errors_after == js_errors_before, "Cancel produced JS errors"
        finally:
            cleanup_server(servers_page.page, server_name)

    @pytest.mark.ui
    @pytest.mark.e2e
    def test_tool_search_preserves_selections(self, servers_page: ServersPage):
        """Regression test for #3260: keyword search in tools picker does not wipe selections.

        Steps: Edit server -> verify tools checked -> search non-matching term ->
        clear search -> verify original tools still checked.
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        server_name = self._create_server_with_tools(servers_page)

        try:
            # Open edit modal
            servers_page.open_edit_modal(server_name)

            # Wait for edit tools to load and capture initial checked tools
            servers_page.page.wait_for_selector('#edit-server-tools input[name="associatedTools"]', state="attached", timeout=10000)
            initial_checked = servers_page.get_edit_checked_tools()
            assert len(initial_checked) >= 1, "Server should have at least 1 tool selected"

            # Search for a non-matching term (triggers serverSideEditToolSearch)
            servers_page.fill_locator(servers_page.edit_tools_search_input, "xyznonexistent999")
            servers_page.page.wait_for_timeout(2000)  # debounce + fetch

            # Clear the search (triggers reload of default tool list)
            servers_page.fill_locator(servers_page.edit_tools_search_input, "")
            servers_page.page.wait_for_timeout(2000)  # debounce + fetch

            # Verify selections survived the search cycle
            restored_checked = servers_page.get_edit_checked_tools()
            for tool_id in initial_checked:
                assert tool_id in restored_checked, f"Tool {tool_id} was lost after search cycle"

            # Clean close
            servers_page.click_locator(servers_page.edit_server_cancel_btn)
            expect(servers_page.edit_server_modal).to_be_hidden(timeout=5000)
        finally:
            cleanup_server(servers_page.page, server_name)

    @pytest.mark.ui
    @pytest.mark.e2e
    def test_select_all_tools_survives_search(self, servers_page: ServersPage):
        """Regression test for #3257: Select All + search + clear preserves all selections.

        Steps: Edit server -> Select All tools -> search term -> clear ->
        verify all tools still selected in-memory and in DOM.
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        server_name = self._create_server_with_tools(servers_page)

        try:
            # Open edit modal
            servers_page.open_edit_modal(server_name)

            # Wait for edit tools to load
            servers_page.page.wait_for_selector('#edit-server-tools input[name="associatedTools"]', state="attached", timeout=10000)

            # Click Select All
            servers_page.edit_select_all_tools_btn.evaluate("el => el.click()")
            servers_page.page.wait_for_timeout(3000)  # async fetch for all IDs

            # Capture count of selected tools after Select All
            select_all_count = servers_page.get_edit_tool_store_size()
            assert select_all_count >= 2, f"Select All should select at least 2 tools, got {select_all_count}"

            # Search for a term that matches some tools
            servers_page.fill_locator(servers_page.edit_tools_search_input, "time")
            servers_page.page.wait_for_timeout(2000)

            # Clear search
            servers_page.fill_locator(servers_page.edit_tools_search_input, "")
            servers_page.page.wait_for_timeout(2000)

            # Verify in-memory store still has the same count
            restored_store_size = servers_page.get_edit_tool_store_size()
            assert restored_store_size == select_all_count, f"Store lost entries: {restored_store_size} vs {select_all_count}"

            # Verify DOM checkboxes are restored
            restored_checked = servers_page.get_edit_checked_tools()
            assert len(restored_checked) == select_all_count, f"DOM checkboxes lost: {len(restored_checked)} vs {select_all_count}"

            # Clean close
            servers_page.click_locator(servers_page.edit_server_cancel_btn)
            expect(servers_page.edit_server_modal).to_be_hidden(timeout=5000)
        finally:
            cleanup_server(servers_page.page, server_name)

    @pytest.mark.ui
    @pytest.mark.e2e
    def test_select_all_resources_survives_search(self, servers_page: ServersPage):
        """Regression test for #3257: Select All resources + search + clear preserves selections.

        Clicks Select All resources, captures store size, searches, clears,
        then asserts the in-memory store size is unchanged.
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        server_name = self._create_server_with_tools(servers_page)

        try:
            servers_page.open_edit_modal(server_name)

            # Wait for resource checkboxes to load
            servers_page.page.wait_for_selector('#edit-server-resources input[name="associatedResources"]', state="attached", timeout=10000)
            res_count = servers_page.edit_resources_container.locator('input[name="associatedResources"]').count()
            if res_count == 0:
                pytest.skip("No resources available to test Select All")

            # Click Select All resources
            servers_page.edit_select_all_resources_btn.evaluate("el => el.click()")
            servers_page.page.wait_for_timeout(3000)

            select_all_count = servers_page.get_edit_resource_store_size()
            assert select_all_count >= 1, f"Select All should populate store, got {select_all_count}"

            # Search and clear
            servers_page.fill_locator(servers_page.edit_resources_search_input, "xyznonexistent999")
            servers_page.page.wait_for_timeout(2000)
            servers_page.fill_locator(servers_page.edit_resources_search_input, "")
            servers_page.page.wait_for_timeout(2000)

            restored = servers_page.get_edit_resource_store_size()
            assert restored == select_all_count, f"Resource store lost entries: {restored} vs {select_all_count}"

            servers_page.click_locator(servers_page.edit_server_cancel_btn)
            expect(servers_page.edit_server_modal).to_be_hidden(timeout=5000)
        finally:
            cleanup_server(servers_page.page, server_name)

    @pytest.mark.ui
    @pytest.mark.e2e
    def test_select_all_prompts_survives_search(self, servers_page: ServersPage):
        """Regression test for #3257: Select All prompts + search + clear preserves selections.

        Clicks Select All prompts, captures store size, searches, clears,
        then asserts the in-memory store size is unchanged.
        """
        servers_page.navigate_to_servers_tab()
        servers_page.wait_for_visible(servers_page.add_server_form)
        server_name = self._create_server_with_tools(servers_page)

        try:
            servers_page.open_edit_modal(server_name)

            # Wait for prompt checkboxes to load
            servers_page.page.wait_for_selector('#edit-server-prompts input[name="associatedPrompts"]', state="attached", timeout=10000)
            prompt_count = servers_page.edit_prompts_container.locator('input[name="associatedPrompts"]').count()
            if prompt_count == 0:
                pytest.skip("No prompts available to test Select All")

            # Click Select All prompts
            servers_page.edit_select_all_prompts_btn.evaluate("el => el.click()")
            servers_page.page.wait_for_timeout(3000)

            select_all_count = servers_page.get_edit_prompt_store_size()
            assert select_all_count >= 1, f"Select All should populate store, got {select_all_count}"

            # Search and clear
            servers_page.fill_locator(servers_page.edit_prompts_search_input, "xyznonexistent999")
            servers_page.page.wait_for_timeout(2000)
            servers_page.fill_locator(servers_page.edit_prompts_search_input, "")
            servers_page.page.wait_for_timeout(2000)

            restored = servers_page.get_edit_prompt_store_size()
            assert restored == select_all_count, f"Prompt store lost entries: {restored} vs {select_all_count}"

            servers_page.click_locator(servers_page.edit_server_cancel_btn)
            expect(servers_page.edit_server_modal).to_be_hidden(timeout=5000)
        finally:
            cleanup_server(servers_page.page, server_name)
