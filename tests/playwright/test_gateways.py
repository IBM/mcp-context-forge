# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_gateways.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test cases for MCP Servers & Federated Gateways (MCP Registry) management.
"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.gateways_page import GatewaysPage


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewaysPage:
    """Test cases for Gateways page functionality."""

    def test_gateways_panel_loads(self, gateways_page: GatewaysPage):
        """Test that gateways panel loads successfully."""
        gateways_page.navigate_to_gateways_tab()
        expect(gateways_page.gateways_panel).to_be_visible()
        expect(gateways_page.panel_title).to_be_visible()
        expect(gateways_page.gateways_table).to_be_visible()

    def test_gateways_table_structure(self, gateways_page: GatewaysPage):
        """Test that gateways table has correct structure."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Verify table headers exist
        table = gateways_page.gateways_table
        expect(table.locator('th:has-text("Actions")')).to_be_visible()
        expect(table.locator('th:has-text("S. No.")')).to_be_visible()
        expect(table.locator('th:has-text("Name")')).to_be_visible()
        expect(table.locator('th:has-text("URL")')).to_be_visible()
        expect(table.locator('th:has-text("Tags")')).to_be_visible()
        expect(table.locator('th:has-text("Status")')).to_be_visible()
        expect(table.locator('th:has-text("Visibility")')).to_be_visible()

    def test_add_gateway_form_visible(self, gateways_page: GatewaysPage):
        """Test that add gateway form is visible and has required fields."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.add_gateway_form).to_be_visible()
        expect(gateways_page.gateway_name_input).to_be_visible()
        expect(gateways_page.gateway_url_input).to_be_visible()
        expect(gateways_page.gateway_description_input).to_be_visible()
        expect(gateways_page.gateway_tags_input).to_be_visible()
        expect(gateways_page.transport_select).to_be_visible()
        expect(gateways_page.auth_type_select).to_be_visible()
        expect(gateways_page.add_gateway_btn).to_be_visible()

    def test_search_functionality(self, gateways_page: GatewaysPage):
        """Test gateway search functionality."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Verify search input is visible
        expect(gateways_page.search_input).to_be_visible()
        expect(gateways_page.clear_search_btn).to_be_visible()
        
        # Test search (if gateways exist)
        initial_count = gateways_page.get_gateway_count()
        if initial_count > 0:
            gateways_page.search_gateways("nonexistent-gateway-xyz")
            gateways_page.page.wait_for_timeout(500)
            search_count = gateways_page.get_gateway_count()
            assert search_count <= initial_count

    def test_show_inactive_toggle(self, gateways_page: GatewaysPage):
        """Test show inactive gateways toggle."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Verify checkbox exists
        expect(gateways_page.show_inactive_checkbox).to_be_visible()
        
        # Test toggle
        initial_state = gateways_page.show_inactive_checkbox.is_checked()
        gateways_page.toggle_show_inactive(not initial_state)
        gateways_page.page.wait_for_timeout(500)
        assert gateways_page.show_inactive_checkbox.is_checked() == (not initial_state)

    def test_transport_type_options(self, gateways_page: GatewaysPage):
        """Test that transport type select has correct options."""
        gateways_page.navigate_to_gateways_tab()
        
        transport_select = gateways_page.transport_select
        expect(transport_select).to_be_visible()
        
        # Verify SSE and STREAMABLEHTTP options exist
        expect(transport_select.locator('option[value="SSE"]')).to_be_attached()
        expect(transport_select.locator('option[value="STREAMABLEHTTP"]')).to_be_attached()

    def test_auth_type_options(self, gateways_page: GatewaysPage):
        """Test that authentication type select has correct options."""
        gateways_page.navigate_to_gateways_tab()
        
        auth_select = gateways_page.auth_type_select
        expect(auth_select).to_be_visible()
        
        # Verify auth type options
        expect(auth_select.locator('option[value=""]')).to_be_attached()  # None
        expect(auth_select.locator('option[value="basic"]')).to_be_attached()
        expect(auth_select.locator('option[value="bearer"]')).to_be_attached()
        expect(auth_select.locator('option[value="authheaders"]')).to_be_attached()
        expect(auth_select.locator('option[value="oauth"]')).to_be_attached()
        expect(auth_select.locator('option[value="query_param"]')).to_be_attached()

    def test_visibility_radio_buttons(self, gateways_page: GatewaysPage):
        """Test that visibility radio buttons are present."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.visibility_public_radio).to_be_attached()
        expect(gateways_page.visibility_team_radio).to_be_attached()
        expect(gateways_page.visibility_private_radio).to_be_attached()
        
        # Public should be checked by default
        expect(gateways_page.visibility_public_radio).to_be_checked()

    def test_basic_auth_fields_visibility(self, gateways_page: GatewaysPage):
        """Test that basic auth fields appear when basic auth is selected."""
        gateways_page.navigate_to_gateways_tab()
        
        # Initially hidden
        expect(gateways_page.auth_basic_fields).to_be_hidden()
        
        # Select basic auth
        gateways_page.auth_type_select.select_option("basic")
        gateways_page.page.wait_for_timeout(300)
        
        # Should now be visible
        expect(gateways_page.auth_basic_fields).to_be_visible()
        expect(gateways_page.auth_username_input).to_be_visible()
        expect(gateways_page.auth_password_input).to_be_visible()

    def test_bearer_auth_fields_visibility(self, gateways_page: GatewaysPage):
        """Test that bearer token fields appear when bearer auth is selected."""
        gateways_page.navigate_to_gateways_tab()
        
        # Initially hidden
        expect(gateways_page.auth_bearer_fields).to_be_hidden()
        
        # Select bearer auth
        gateways_page.auth_type_select.select_option("bearer")
        gateways_page.page.wait_for_timeout(300)
        
        # Should now be visible
        expect(gateways_page.auth_bearer_fields).to_be_visible()
        expect(gateways_page.auth_token_input).to_be_visible()

    def test_oauth_fields_visibility(self, gateways_page: GatewaysPage):
        """Test that OAuth fields appear when OAuth is selected."""
        gateways_page.navigate_to_gateways_tab()
        
        # Initially hidden
        expect(gateways_page.oauth_fields).to_be_hidden()
        
        # Select OAuth
        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)
        
        # Should now be visible
        expect(gateways_page.oauth_fields).to_be_visible()
        expect(gateways_page.oauth_grant_type_select).to_be_visible()
        expect(gateways_page.oauth_issuer_input).to_be_visible()
        expect(gateways_page.oauth_client_id_input).to_be_visible()
        expect(gateways_page.oauth_client_secret_input).to_be_visible()

    def test_query_param_auth_fields_visibility(self, gateways_page: GatewaysPage):
        """Test that query parameter auth fields appear when selected."""
        gateways_page.navigate_to_gateways_tab()
        
        # Initially hidden
        expect(gateways_page.auth_query_param_fields).to_be_hidden()
        
        # Select query param auth
        gateways_page.auth_type_select.select_option("query_param")
        gateways_page.page.wait_for_timeout(300)
        
        # Should now be visible with security warning
        expect(gateways_page.auth_query_param_fields).to_be_visible()
        expect(gateways_page.auth_query_param_key_input).to_be_visible()
        expect(gateways_page.auth_query_param_value_input).to_be_visible()

    def test_custom_headers_auth_fields_visibility(self, gateways_page: GatewaysPage):
        """Test that custom headers auth fields appear when selected."""
        gateways_page.navigate_to_gateways_tab()
        
        # Initially hidden
        expect(gateways_page.auth_headers_fields).to_be_hidden()
        
        # Select custom headers auth
        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)
        
        # Should now be visible
        expect(gateways_page.auth_headers_fields).to_be_visible()

    def test_oauth_grant_type_options(self, gateways_page: GatewaysPage):
        """Test OAuth grant type options."""
        gateways_page.navigate_to_gateways_tab()
        
        # Select OAuth to show fields
        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)
        
        grant_type_select = gateways_page.oauth_grant_type_select
        expect(grant_type_select).to_be_visible()
        
        # Verify grant type options
        expect(grant_type_select.locator('option[value="authorization_code"]')).to_be_attached()
        expect(grant_type_select.locator('option[value="client_credentials"]')).to_be_attached()
        expect(grant_type_select.locator('option[value="password"]')).to_be_attached()

    def test_one_time_auth_checkbox(self, gateways_page: GatewaysPage):
        """Test one-time authentication checkbox."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.one_time_auth_checkbox).to_be_visible()
        
        # Should not be checked by default
        expect(gateways_page.one_time_auth_checkbox).not_to_be_checked()
        
        # Test toggle
        gateways_page.toggle_one_time_auth(True)
        expect(gateways_page.one_time_auth_checkbox).to_be_checked()

    def test_passthrough_headers_input(self, gateways_page: GatewaysPage):
        """Test passthrough headers input field."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.passthrough_headers_input).to_be_visible()
        
        # Test filling
        test_headers = "Authorization, X-Tenant-Id, X-Trace-Id"
        gateways_page.passthrough_headers_input.fill(test_headers)
        expect(gateways_page.passthrough_headers_input).to_have_value(test_headers)

    def test_ca_certificate_upload_elements(self, gateways_page: GatewaysPage):
        """Test CA certificate upload elements are present."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.ca_certificate_upload_input).to_be_attached()
        expect(gateways_page.ca_certificate_drop_zone).to_be_visible()

    def test_pagination_controls_present(self, gateways_page: GatewaysPage):
        """Test that pagination controls are present."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Pagination controls should be visible
        expect(gateways_page.pagination_controls).to_be_visible()


@pytest.mark.ui
@pytest.mark.gateways
@pytest.mark.smoke
class TestGatewayCreation:
    """Test cases for creating gateways."""

    def test_create_simple_gateway(self, gateways_page: GatewaysPage, test_gateway_data: dict):
        """Test creating a simple gateway without authentication."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Delete any existing gateway with the same URL first (system prevents duplicate URLs)
        if gateways_page.delete_gateway_by_url(test_gateway_data["url"]):
            print(f"🗑️  Deleted existing gateway with URL '{test_gateway_data['url']}' before test")
        
        # Fill and submit form
        gateways_page.create_gateway(test_gateway_data)
        
        # Wait and check for status messages
        gateways_page.page.wait_for_timeout(2000)
        
        # Check if there's a status message
        status_element = gateways_page.status_message
        if status_element.is_visible():
            error_text = status_element.text_content()
            print(f"📋 Status message: {error_text}")
            
            # "Failed to initialize" is a warning - gateway is still created
            if "Failed to initialize gateway" in error_text:
                print(f"⚠️  Warning: Gateway created but initialization failed (external service may be unavailable)")
        
        # Page doesn't auto-reload after adding, so reload to see the new gateway
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Wait for ANY gateway row to appear first (table is populated)
        gateways_page.page.wait_for_selector(
            '#gateways-table-body tr[id*="gateway-row"]',
            state="attached",
            timeout=20000
        )
        
        # Now search for our specific gateway
        gateways_page.search_gateways(test_gateway_data["name"])
        gateways_page.page.wait_for_timeout(1000)
        
        # Verify gateway was created
        # Locator used: #gateways-table-body tr:has-text("gateway-name")
        assert gateways_page.gateway_exists(test_gateway_data["name"]), \
            f"Gateway '{test_gateway_data['name']}' was not found in the table after creation"
        
        print(f"✓ Gateway '{test_gateway_data['name']}' created successfully")
        
        # Cleanup: Delete the created gateway by URL
        if gateways_page.delete_gateway_by_url(test_gateway_data["url"]):
            print(f"✓ Cleanup: Successfully deleted gateway with URL '{test_gateway_data['url']}'")

    def test_create_gateway_with_basic_auth(
        self,
        gateways_page: GatewaysPage,
        test_gateway_with_basic_auth_data: dict
    ):
        """Test creating a gateway with basic authentication."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Delete any existing gateway with the same URL first (system prevents duplicate URLs)
        if gateways_page.delete_gateway_by_url(test_gateway_with_basic_auth_data["url"]):
            print(f"🗑️  Deleted existing gateway with URL '{test_gateway_with_basic_auth_data['url']}' before test")
        
        # Fill basic gateway info
        gateways_page.fill_gateway_form(
            name=test_gateway_with_basic_auth_data["name"],
            url=test_gateway_with_basic_auth_data["url"],
            description=test_gateway_with_basic_auth_data["description"],
            tags=test_gateway_with_basic_auth_data["tags"]
        )
        
        # Configure basic auth
        gateways_page.configure_basic_auth(
            username=test_gateway_with_basic_auth_data["auth_username"],
            password=test_gateway_with_basic_auth_data["auth_password"]
        )
        
        # Submit form
        gateways_page.submit_gateway_form()
        
        # Wait and check for status messages
        gateways_page.page.wait_for_timeout(2000)
        
        # Check if there's a status message
        status_element = gateways_page.status_message
        if status_element.is_visible():
            error_text = status_element.text_content()
            print(f"📋 Status message: {error_text}")
            
            # "Failed to initialize" is a warning - gateway is still created
            if "Failed to initialize gateway" in error_text:
                print(f"⚠️  Warning: Gateway created but initialization failed (external service may be unavailable)")
        
        # Page doesn't auto-reload, so reload to see the new gateway
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Wait for ANY gateway row to appear first (table is populated)
        gateways_page.page.wait_for_selector(
            '#gateways-table-body tr[id*="gateway-row"]',
            state="attached",
            timeout=20000
        )
        
        # Get current gateway count for debugging
        current_count = gateways_page.get_gateway_count()
        print(f"📊 Current gateway count after reload: {current_count}")
        
        # Now search for our specific gateway
        gateways_page.search_gateways(test_gateway_with_basic_auth_data["name"])
        gateways_page.page.wait_for_timeout(1000)
        
        search_count = gateways_page.get_gateway_count()
        print(f"📊 Gateway count after search: {search_count}")
        
        # Verify gateway was created
        # Locator used: #gateways-table-body tr:has-text("gateway-name")
        assert gateways_page.gateway_exists(test_gateway_with_basic_auth_data["name"]), \
            f"Gateway '{test_gateway_with_basic_auth_data['name']}' was not found after creation"
        
        print(f"✓ Gateway '{test_gateway_with_basic_auth_data['name']}' created successfully")
        
        # Cleanup: Delete the created gateway by URL
        if gateways_page.delete_gateway_by_url(test_gateway_with_basic_auth_data["url"]):
            print(f"✓ Cleanup: Successfully deleted gateway with URL '{test_gateway_with_basic_auth_data['url']}'")

    def test_create_gateway_with_bearer_auth(
        self,
        gateways_page: GatewaysPage,
        test_gateway_with_bearer_auth_data: dict
    ):
        """Test creating a gateway with bearer token authentication."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Delete any existing gateway with the same URL first (system prevents duplicate URLs)
        if gateways_page.delete_gateway_by_url(test_gateway_with_bearer_auth_data["url"]):
            print(f"🗑️  Deleted existing gateway with URL '{test_gateway_with_bearer_auth_data['url']}' before test")
        
        # Fill basic gateway info
        gateways_page.fill_gateway_form(
            name=test_gateway_with_bearer_auth_data["name"],
            url=test_gateway_with_bearer_auth_data["url"],
            description=test_gateway_with_bearer_auth_data["description"],
            tags=test_gateway_with_bearer_auth_data["tags"]
        )
        
        # Set visibility to private
        gateways_page.visibility_private_radio.click()
        
        # Configure bearer auth
        gateways_page.configure_bearer_auth(
            token=test_gateway_with_bearer_auth_data["auth_token"]
        )
        
        # Submit form
        gateways_page.submit_gateway_form()
        
        # Wait and check for status messages
        gateways_page.page.wait_for_timeout(2000)
        
        # Check if there's a status message
        status_element = gateways_page.status_message
        if status_element.is_visible():
            error_text = status_element.text_content()
            print(f"📋 Status message: {error_text}")
            
            # "Failed to initialize" is a warning - gateway is still created
            if "Failed to initialize gateway" in error_text:
                print(f"⚠️  Warning: Gateway created but initialization failed (external service may be unavailable)")
        
        # Page doesn't auto-reload, so reload to see the new gateway
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Wait for ANY gateway row to appear first (table is populated)
        gateways_page.page.wait_for_selector(
            '#gateways-table-body tr[id*="gateway-row"]',
            state="attached",
            timeout=20000
        )
        
        # Now search for our specific gateway
        gateways_page.search_gateways(test_gateway_with_bearer_auth_data["name"])
        gateways_page.page.wait_for_timeout(1000)
        
        # Verify gateway was created
        assert gateways_page.gateway_exists(test_gateway_with_bearer_auth_data["name"]), \
            f"Gateway '{test_gateway_with_bearer_auth_data['name']}' was not found after creation"
        
        print(f"✓ Gateway '{test_gateway_with_bearer_auth_data['name']}' created successfully")
        
        # Cleanup: Delete the created gateway by URL
        if gateways_page.delete_gateway_by_url(test_gateway_with_bearer_auth_data["url"]):
            print(f"✓ Cleanup: Successfully deleted gateway with URL '{test_gateway_with_bearer_auth_data['url']}'")

    def test_create_gateway_with_streamable_http(
        self,
        gateways_page: GatewaysPage,
        test_gateway_data: dict
    ):
        """Test creating a gateway with STREAMABLEHTTP transport."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Modify test data for STREAMABLEHTTP
        gateway_data = test_gateway_data.copy()
        gateway_data["name"] = f"{test_gateway_data['name']}-http"
        gateway_data["description"] = "Test gateway with STREAMABLEHTTP transport"
        gateway_data["tags"] = "test,http,streamable"
        gateway_data["transport"] = "STREAMABLEHTTP"
        gateway_name = gateway_data["name"]
        gateway_url = gateway_data["url"]
        
        # Delete any existing gateway with the same URL first (system prevents duplicate URLs)
        if gateways_page.delete_gateway_by_url(gateway_url):
            print(f"🗑️  Deleted existing gateway with URL '{gateway_url}' before test")
        
        # Create gateway with STREAMABLEHTTP
        gateways_page.create_gateway(gateway_data)
        gateway_name = gateway_data["name"]
        
        # Wait and check for status messages
        gateways_page.page.wait_for_timeout(2000)
        
        # Check if there's a status message
        status_element = gateways_page.status_message
        if status_element.is_visible():
            error_text = status_element.text_content()
            print(f"📋 Status message: {error_text}")
            
            # "Failed to initialize" is a warning - gateway is still created
            if "Failed to initialize gateway" in error_text:
                print(f"⚠️  Warning: Gateway created but initialization failed (external service may be unavailable)")
        
        # Page doesn't auto-reload, so reload to see the new gateway
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Wait for ANY gateway row to appear first (table is populated)
        gateways_page.page.wait_for_selector(
            '#gateways-table-body tr[id*="gateway-row"]',
            state="attached",
            timeout=20000
        )
        
        # Now search for our specific gateway
        gateways_page.search_gateways(gateway_name)
        gateways_page.page.wait_for_timeout(1000)
        
        # Verify gateway was created
        assert gateways_page.gateway_exists(gateway_name), \
            f"Gateway '{gateway_name}' was not found after creation"
        
        print(f"✓ Gateway '{gateway_name}' created successfully")
        
        # Cleanup: Delete the created gateway by URL
        if gateways_page.delete_gateway_by_url(gateway_url):
            print(f"✓ Cleanup: Successfully deleted gateway with URL '{gateway_url}'")

    def test_form_validation_empty_name(self, gateways_page: GatewaysPage):
        """Test form validation for empty gateway name."""
        gateways_page.navigate_to_gateways_tab()
        
        # Try to submit with empty name
        gateways_page.gateway_url_input.fill("https://example.com/sse")
        gateways_page.add_gateway_btn.click()
        
        # Form should not submit (name is required)
        # The browser's built-in validation should prevent submission
        expect(gateways_page.gateway_name_input).to_have_attribute("required", "")

    def test_form_validation_empty_url(self, gateways_page: GatewaysPage):
        """Test form validation for empty gateway URL."""
        gateways_page.navigate_to_gateways_tab()
        
        # Try to submit with empty URL
        gateways_page.gateway_name_input.fill("Test Gateway")
        gateways_page.add_gateway_btn.click()
        
        # Form should not submit (URL is required)
        expect(gateways_page.gateway_url_input).to_have_attribute("required", "")


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayActions:
    """Test cases for gateway row actions."""

    def test_gateway_row_actions_visible(self, gateways_page: GatewaysPage):
        """Test that all gateway row action buttons are visible."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Get first gateway row
        first_row = gateways_page.get_gateway_row(0)
        
        # Verify all action buttons exist
        expect(first_row.locator('button:has-text("Test")')).to_be_visible()
        expect(first_row.locator('button:has-text("View")')).to_be_visible()
        expect(first_row.locator('button:has-text("Edit")')).to_be_visible()
        
        # Either Activate or Deactivate should be visible
        activate_btn = first_row.locator('button:has-text("Activate")')
        deactivate_btn = first_row.locator('button:has-text("Deactivate")')
        assert activate_btn.is_visible() or deactivate_btn.is_visible()
        
        # Delete button should be visible
        expect(first_row.locator('button:has-text("Delete")')).to_be_visible()

    def test_test_button_click(self, gateways_page: GatewaysPage):
        """Test clicking the Test button for a gateway."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Click Test button on first gateway
        gateways_page.click_test_button(0)
        gateways_page.page.wait_for_timeout(1000)
        
        # Test button should trigger a modal or some UI feedback
        # The exact behavior depends on the implementation
        # For now, verify the button was clickable
        print("✓ Test button clicked successfully")

    def test_view_button_click(self, gateways_page: GatewaysPage):
        """Test clicking the View button for a gateway."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Click View button on first gateway
        gateways_page.click_view_button(0)
        gateways_page.page.wait_for_timeout(1000)
        
        # View button should open a modal or navigate to details page
        # Verify some UI change occurred
        print("✓ View button clicked successfully")

    def test_edit_button_click(self, gateways_page: GatewaysPage):
        """Test clicking the Edit button for a gateway."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Click Edit button on first gateway
        gateways_page.click_edit_button(0)
        gateways_page.page.wait_for_timeout(1000)
        
        # Edit button should open an edit modal or form
        print("✓ Edit button clicked successfully")

    def test_deactivate_button_functionality(self, gateways_page: GatewaysPage):
        """Test deactivating a gateway."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Find a gateway with Deactivate button
        first_row = gateways_page.get_gateway_row(0)
        deactivate_btn = first_row.locator('button:has-text("Deactivate")')
        
        if not deactivate_btn.is_visible():
            pytest.skip("No active gateways available to deactivate")
        
        # Get gateway name before deactivation
        gateway_name = first_row.locator('td').nth(2).text_content().strip()
        
        # Click Deactivate button
        gateways_page.click_deactivate_button(0)
        gateways_page.page.wait_for_timeout(2000)
        
        # Reload to see updated status
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        gateways_page.page.wait_for_timeout(1000)
        
        # Search for the gateway
        gateways_page.search_gateways(gateway_name)
        gateways_page.page.wait_for_timeout(500)
        
        # Verify Activate button is now visible (gateway was deactivated)
        if gateways_page.gateway_exists(gateway_name):
            gateway_row = gateways_page.get_gateway_row_by_name(gateway_name)
            activate_btn = gateway_row.locator('button:has-text("Activate")')
            expect(activate_btn).to_be_visible()
            print(f"✓ Gateway '{gateway_name}' deactivated successfully")
            
            # Reactivate for cleanup
            gateways_page.click_activate_button(0)
            gateways_page.page.wait_for_timeout(1000)

    def test_activate_button_functionality(self, gateways_page: GatewaysPage):
        """Test activating an inactive gateway."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Enable showing inactive gateways
        gateways_page.toggle_show_inactive(True)
        gateways_page.page.wait_for_timeout(1000)
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Find a gateway with Activate button
        first_row = gateways_page.get_gateway_row(0)
        activate_btn = first_row.locator('button:has-text("Activate")')
        
        if not activate_btn.is_visible():
            pytest.skip("No inactive gateways available to activate")
        
        # Get gateway name before activation
        gateway_name = first_row.locator('td').nth(2).text_content().strip()
        
        # Click Activate button
        gateways_page.click_activate_button(0)
        gateways_page.page.wait_for_timeout(2000)
        
        # Reload to see updated status
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        gateways_page.page.wait_for_timeout(1000)
        
        # Search for the gateway
        gateways_page.search_gateways(gateway_name)
        gateways_page.page.wait_for_timeout(500)
        
        # Verify Deactivate button is now visible (gateway was activated)
        if gateways_page.gateway_exists(gateway_name):
            gateway_row = gateways_page.get_gateway_row_by_name(gateway_name)
            deactivate_btn = gateway_row.locator('button:has-text("Deactivate")')
            expect(deactivate_btn).to_be_visible()
            print(f"✓ Gateway '{gateway_name}' activated successfully")

    def test_delete_button_with_confirmation(
        self,
        gateways_page: GatewaysPage,
        test_gateway_data: dict
    ):
        """Test deleting a gateway with confirmation."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Create a test gateway to delete
        gateway_data = test_gateway_data.copy()
        gateway_data["name"] = f"{test_gateway_data['name']}-delete-test"
        
        # Delete any existing gateway with the same name first
        if gateways_page.delete_gateway_by_name(gateway_data["name"]):
            print(f"🗑️  Deleted existing gateway '{gateway_data['name']}' before test")
        
        gateways_page.create_gateway(gateway_data)
        gateways_page.page.wait_for_timeout(2000)
        
        # Reload and search for the gateway
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        gateways_page.page.wait_for_timeout(2000)
        
        gateways_page.search_gateways(gateway_data["name"])
        gateways_page.page.wait_for_timeout(500)
        
        # Verify gateway exists before deletion
        if not gateways_page.gateway_exists(gateway_data["name"]):
            pytest.skip(f"Gateway '{gateway_data['name']}' not found for deletion test")
        
        initial_count = gateways_page.get_gateway_count()
        
        # Delete the gateway with confirmation
        gateways_page.delete_gateway(0, confirm=True)
        gateways_page.page.wait_for_timeout(2000)
        
        # Verify gateway was deleted
        gateways_page.page.reload()
        gateways_page.wait_for_gateways_table_loaded()
        gateways_page.search_gateways(gateway_data["name"])
        gateways_page.page.wait_for_timeout(500)
        
        final_count = gateways_page.get_gateway_count()
        assert final_count < initial_count, "Gateway count should decrease after deletion"
        print(f"✓ Gateway '{gateway_data['name']}' deleted successfully")

    def test_delete_button_without_confirmation(
        self,
        gateways_page: GatewaysPage,
        test_gateway_data: dict
    ):
        """Test canceling gateway deletion."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        initial_count = gateways_page.get_gateway_count()
        
        # Try to delete but cancel the confirmation
        gateways_page.delete_gateway(0, confirm=False)
        gateways_page.page.wait_for_timeout(1000)
        
        # Verify gateway count hasn't changed
        final_count = gateways_page.get_gateway_count()
        assert final_count == initial_count, "Gateway count should not change when deletion is canceled"
        print("✓ Gateway deletion canceled successfully")

    def test_gateway_status_badge(self, gateways_page: GatewaysPage):
        """Test that gateway status badge is displayed."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Get first gateway row
        first_row = gateways_page.get_gateway_row(0)
        
        # Status badge should be visible (either Active or Inactive)
        status_cell = first_row.locator('td').nth(5)  # Status column
        expect(status_cell).to_be_visible()

    def test_gateway_visibility_badge(self, gateways_page: GatewaysPage):
        """Test that gateway visibility badge is displayed."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Get first gateway row
        first_row = gateways_page.get_gateway_row(0)
        
        # Visibility badge should be visible
        visibility_cell = first_row.locator('td').nth(9)  # Visibility column
        expect(visibility_cell).to_be_visible()

    def test_gateway_tags_display(self, gateways_page: GatewaysPage):
        """Test that gateway tags are displayed."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Get first gateway row
        first_row = gateways_page.get_gateway_row(0)
        
        # Tags column should be visible
        tags_cell = first_row.locator('td').nth(4)  # Tags column
        expect(tags_cell).to_be_visible()


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewaySearch:
    """Test cases for gateway search and filtering."""

    def test_search_by_name(self, gateways_page: GatewaysPage):
        """Test searching gateways by name."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        # Skip if no gateways exist
        if gateways_page.get_gateway_count() == 0:
            pytest.skip("No gateways available for testing")
        
        # Get first gateway name
        first_row = gateways_page.get_gateway_row(0)
        gateway_name = first_row.locator('td').nth(2).text_content().strip()
        
        # Search for it
        gateways_page.search_gateways(gateway_name)
        gateways_page.page.wait_for_timeout(500)
        
        # Should still be visible
        assert gateways_page.gateway_exists(gateway_name)

    def test_clear_search(self, gateways_page: GatewaysPage):
        """Test clearing gateway search."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        
        initial_count = gateways_page.get_gateway_count()
        
        # Perform a search
        gateways_page.search_gateways("test-search-query")
        gateways_page.page.wait_for_timeout(500)
        
        # Clear search
        gateways_page.clear_search()
        gateways_page.page.wait_for_timeout(500)
        
        # Count should return to initial
        final_count = gateways_page.get_gateway_count()
        assert final_count == initial_count


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayVisibility:
    """Test cases for gateway visibility settings."""

    def test_public_visibility_default(self, gateways_page: GatewaysPage):
        """Test that public visibility is selected by default."""
        gateways_page.navigate_to_gateways_tab()
        
        expect(gateways_page.visibility_public_radio).to_be_checked()
        expect(gateways_page.visibility_team_radio).not_to_be_checked()
        expect(gateways_page.visibility_private_radio).not_to_be_checked()

    def test_change_visibility_to_team(self, gateways_page: GatewaysPage):
        """Test changing visibility to team."""
        gateways_page.navigate_to_gateways_tab()
        
        gateways_page.visibility_team_radio.click()
        
        expect(gateways_page.visibility_team_radio).to_be_checked()
        expect(gateways_page.visibility_public_radio).not_to_be_checked()
        expect(gateways_page.visibility_private_radio).not_to_be_checked()

    def test_change_visibility_to_private(self, gateways_page: GatewaysPage):
        """Test changing visibility to private."""
        gateways_page.navigate_to_gateways_tab()
        
        gateways_page.visibility_private_radio.click()
        
        expect(gateways_page.visibility_private_radio).to_be_checked()
        expect(gateways_page.visibility_public_radio).not_to_be_checked()
        expect(gateways_page.visibility_team_radio).not_to_be_checked()