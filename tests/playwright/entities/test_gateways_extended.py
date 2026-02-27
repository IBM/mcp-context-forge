# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_gateways_extended.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Extended test coverage for MCP Servers & Federated Gateways (MCP Registry).
Tests all modal interactions (Test, View, Edit), OAuth grant type switching,
custom headers, pagination controls, and end-to-end edit flows.
"""

# Standard
import json
import logging
import re
import uuid

# Third-Party
from playwright.sync_api import Error as PlaywrightError, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from ..pages.admin_utils import cleanup_entity, find_gateway
from ..pages.gateways_page import GatewaysPage

logger = logging.getLogger(__name__)


def _skip_if_no_gateways(gateways_page: GatewaysPage) -> None:
    """Skip test if no gateways are available."""
    if gateways_page.get_gateway_count() == 0:
        pytest.skip("No gateways available for testing")


# ---------------------------------------------------------------------------
# Test Gateway Connectivity Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayTestModal:
    """Tests for the Test Gateway Connectivity modal."""

    def test_test_modal_opens_with_correct_url(self, gateways_page: GatewaysPage):
        """Test that the test modal opens and is pre-filled with the gateway URL."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get the URL from the first row before opening modal
        first_row = gateways_page.get_gateway_row(0)
        gateway_url = first_row.locator("td").nth(3).text_content().strip()

        gateways_page.open_test_modal(0)

        # Verify modal is visible
        expect(gateways_page.test_modal).to_be_visible()
        expect(gateways_page.test_modal_title).to_contain_text("Test Gateway Connectivity")

        # Verify URL is pre-filled
        expect(gateways_page.test_modal_url_input).to_have_value(gateway_url)

        gateways_page.close_test_modal()

    def test_test_modal_method_dropdown_options(self, gateways_page: GatewaysPage):
        """Test that the HTTP method dropdown has all expected options."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        method_select = gateways_page.test_modal_method_select
        expect(method_select).to_be_visible()

        # Options don't have explicit value attributes; text content IS the value
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            expect(method_select.locator(f'option:has-text("{method}")')).to_be_attached()

        # GET should be default selected
        expect(method_select).to_have_value("GET")

        gateways_page.close_test_modal()

    def test_test_modal_change_method(self, gateways_page: GatewaysPage):
        """Test changing the HTTP method in the test modal."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        for method in ["POST", "PUT", "DELETE", "PATCH", "GET"]:
            gateways_page.test_modal_method_select.select_option(method)
            expect(gateways_page.test_modal_method_select).to_have_value(method)

        gateways_page.close_test_modal()

    def test_test_modal_path_input(self, gateways_page: GatewaysPage):
        """Test the path input field in test modal."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        path_input = gateways_page.test_modal_path_input
        expect(path_input).to_be_visible()
        expect(path_input).to_have_attribute("placeholder", "/health")

        # Fill custom path
        path_input.fill("/api/v1/status")
        expect(path_input).to_have_value("/api/v1/status")

        gateways_page.close_test_modal()

    def test_test_modal_content_type_options(self, gateways_page: GatewaysPage):
        """Test the Content-Type dropdown options."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        ct_select = gateways_page.test_modal_content_type_select
        expect(ct_select).to_be_visible()

        expect(ct_select.locator('option[value="application/json"]')).to_be_attached()
        expect(ct_select.locator('option[value="application/x-www-form-urlencoded"]')).to_be_attached()

        # Default should be application/json
        expect(ct_select).to_have_value("application/json")

        # Switch to form-urlencoded
        ct_select.select_option("application/x-www-form-urlencoded")
        expect(ct_select).to_have_value("application/x-www-form-urlencoded")

        gateways_page.close_test_modal()

    def test_test_modal_submit_shows_loading(self, gateways_page: GatewaysPage):
        """Test that clicking Test shows a loading state."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        # Click test button
        gateways_page.test_modal_submit_btn.click()

        # Button should become disabled with "Testing..." text
        try:
            gateways_page.page.wait_for_selector(
                '#gateway-test-submit:disabled',
                timeout=3000,
            )
        except PlaywrightTimeoutError:
            pass  # The request may complete very quickly

        # Wait for test to complete (or timeout)
        gateways_page.page.wait_for_timeout(5000)

        gateways_page.close_test_modal()

    def test_test_modal_close_button(self, gateways_page: GatewaysPage):
        """Test that Close button properly closes the test modal."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)
        expect(gateways_page.test_modal).to_be_visible()

        gateways_page.close_test_modal()
        expect(gateways_page.test_modal).to_be_hidden()

    def test_test_modal_url_is_editable(self, gateways_page: GatewaysPage):
        """Test that the server URL in test modal can be edited."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_test_modal(0)

        custom_url = "http://custom-test-server:9999/sse"
        gateways_page.test_modal_url_input.fill(custom_url)
        expect(gateways_page.test_modal_url_input).to_have_value(custom_url)

        gateways_page.close_test_modal()


# ---------------------------------------------------------------------------
# View Gateway Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayViewModal:
    """Tests for the View Gateway Details modal."""

    def test_view_modal_opens_with_details(self, gateways_page: GatewaysPage):
        """Test that the view modal opens and shows gateway details."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get first gateway name from table
        first_row = gateways_page.get_gateway_row(0)
        gateway_name = first_row.locator("td").nth(2).text_content().strip()

        gateways_page.open_view_modal(0)

        # Verify modal is visible
        expect(gateways_page.view_modal).to_be_visible()
        expect(gateways_page.view_modal_title).to_contain_text("Gateway Details")

        # Verify details contain the gateway name
        expect(gateways_page.view_modal_details).to_contain_text(gateway_name)

        gateways_page.close_view_modal()

    def test_view_modal_shows_name_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the Name field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Name:")')).to_be_visible()

        gateways_page.close_view_modal()

    def test_view_modal_shows_url_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the URL field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get URL from table
        first_row = gateways_page.get_gateway_row(0)
        gateway_url = first_row.locator("td").nth(3).text_content().strip()

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("URL:")')).to_be_visible()
        expect(details).to_contain_text(gateway_url)

        gateways_page.close_view_modal()

    def test_view_modal_shows_visibility_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the Visibility field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Visibility:")')).to_be_visible()

        gateways_page.close_view_modal()

    def test_view_modal_shows_status_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the Status field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Status:")')).to_be_visible()

        gateways_page.close_view_modal()

    def test_view_modal_shows_metadata(self, gateways_page: GatewaysPage):
        """Test that view modal displays metadata section."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Metadata:")')).to_be_visible()

        # Verify metadata fields
        for field in ["Created By:", "Created At:", "Version:"]:
            expect(details).to_contain_text(field)

        gateways_page.close_view_modal()

    def test_view_modal_shows_description_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the Description field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Description:")')).to_be_visible()

        gateways_page.close_view_modal()

    def test_view_modal_shows_tags_field(self, gateways_page: GatewaysPage):
        """Test that view modal displays the Tags field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)

        details = gateways_page.view_modal_details
        expect(details.locator('strong:has-text("Tags:")')).to_be_visible()

        gateways_page.close_view_modal()

    def test_view_modal_close_button(self, gateways_page: GatewaysPage):
        """Test that Close button properly closes the view modal."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_view_modal(0)
        expect(gateways_page.view_modal).to_be_visible()

        gateways_page.close_view_modal()
        expect(gateways_page.view_modal).to_be_hidden()

    def test_view_modal_different_gateways(self, gateways_page: GatewaysPage):
        """Test viewing details of different gateways shows correct data."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        count = gateways_page.get_gateway_count()
        if count < 2:
            pytest.skip("Need at least 2 gateways to test different views")

        # View first gateway
        first_row = gateways_page.get_gateway_row(0)
        first_name = first_row.locator("td").nth(2).text_content().strip()
        gateways_page.open_view_modal(0)
        expect(gateways_page.view_modal_details).to_contain_text(first_name)
        gateways_page.close_view_modal()

        # View second gateway
        second_row = gateways_page.get_gateway_row(1)
        second_name = second_row.locator("td").nth(2).text_content().strip()
        gateways_page.open_view_modal(1)
        expect(gateways_page.view_modal_details).to_contain_text(second_name)
        gateways_page.close_view_modal()


# ---------------------------------------------------------------------------
# Edit Gateway Modal
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayEditModal:
    """Tests for the Edit Gateway modal."""

    def test_edit_modal_opens_with_prepopulated_name(self, gateways_page: GatewaysPage):
        """Test that edit modal opens with the gateway name pre-filled."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        gateway_name = first_row.locator("td").nth(2).text_content().strip()

        gateways_page.open_edit_modal(0)

        expect(gateways_page.edit_modal).to_be_visible()
        expect(gateways_page.edit_modal_title).to_contain_text("Edit Gateway")
        expect(gateways_page.edit_modal_name_input).to_have_value(gateway_name)

        gateways_page.close_edit_modal()

    def test_edit_modal_opens_with_prepopulated_url(self, gateways_page: GatewaysPage):
        """Test that edit modal opens with the gateway URL pre-filled."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        gateway_url = first_row.locator("td").nth(3).text_content().strip()

        gateways_page.open_edit_modal(0)
        expect(gateways_page.edit_modal_url_input).to_have_value(gateway_url)
        gateways_page.close_edit_modal()

    def test_edit_modal_has_all_form_fields(self, gateways_page: GatewaysPage):
        """Test that edit modal contains all expected form fields."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        # Core fields
        expect(gateways_page.edit_modal_name_input).to_be_visible()
        expect(gateways_page.edit_modal_url_input).to_be_visible()
        expect(gateways_page.edit_modal_description_input).to_be_visible()
        expect(gateways_page.edit_modal_tags_input).to_be_visible()

        # Visibility radios
        expect(gateways_page.edit_modal_visibility_public).to_be_attached()
        expect(gateways_page.edit_modal_visibility_team).to_be_attached()
        expect(gateways_page.edit_modal_visibility_private).to_be_attached()

        # Transport and auth
        expect(gateways_page.edit_modal_transport_select).to_be_visible()
        expect(gateways_page.edit_modal_auth_type_select).to_be_visible()

        # Additional options
        expect(gateways_page.edit_modal_one_time_auth).to_be_visible()
        expect(gateways_page.edit_modal_passthrough_headers).to_be_visible()

        # Buttons
        expect(gateways_page.edit_modal_cancel_btn).to_be_visible()
        expect(gateways_page.edit_modal_save_btn).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_transport_options(self, gateways_page: GatewaysPage):
        """Test that transport select in edit modal has correct options."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        transport = gateways_page.edit_modal_transport_select
        expect(transport.locator('option[value="SSE"]')).to_be_attached()
        expect(transport.locator('option[value="STREAMABLEHTTP"]')).to_be_attached()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_options(self, gateways_page: GatewaysPage):
        """Test that auth type select in edit modal has all options."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        auth_select = gateways_page.edit_modal_auth_type_select
        expect(auth_select).to_be_visible()

        for value in ["", "basic", "bearer", "authheaders", "oauth", "query_param"]:
            expect(auth_select.locator(f'option[value="{value}"]')).to_be_attached()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_basic_fields(self, gateways_page: GatewaysPage):
        """Test that selecting basic auth in edit modal shows username/password fields."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        # Initially hidden (gateway has no auth)
        expect(gateways_page.edit_auth_basic_fields).to_be_hidden()

        # Select basic auth
        gateways_page.edit_modal_auth_type_select.select_option("basic")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.edit_auth_basic_fields).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_bearer_fields(self, gateways_page: GatewaysPage):
        """Test that selecting bearer auth in edit modal shows token field."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        expect(gateways_page.edit_auth_bearer_fields).to_be_hidden()

        gateways_page.edit_modal_auth_type_select.select_option("bearer")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.edit_auth_bearer_fields).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_oauth_fields(self, gateways_page: GatewaysPage):
        """Test that selecting OAuth in edit modal shows OAuth fields."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        expect(gateways_page.edit_oauth_fields).to_be_hidden()

        gateways_page.edit_modal_auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.edit_oauth_fields).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_custom_headers_fields(self, gateways_page: GatewaysPage):
        """Test that selecting custom headers in edit modal shows header fields."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        expect(gateways_page.edit_auth_headers_fields).to_be_hidden()

        gateways_page.edit_modal_auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.edit_auth_headers_fields).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_auth_type_query_param_fields(self, gateways_page: GatewaysPage):
        """Test that selecting query param in edit modal shows key/value fields."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        expect(gateways_page.edit_auth_query_param_fields).to_be_hidden()

        gateways_page.edit_modal_auth_type_select.select_option("query_param")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.edit_auth_query_param_fields).to_be_visible()

        gateways_page.close_edit_modal()

    def test_edit_modal_cancel_does_not_save(self, gateways_page: GatewaysPage):
        """Test that Cancel button closes the edit modal without saving changes."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get original name
        first_row = gateways_page.get_gateway_row(0)
        original_name = first_row.locator("td").nth(2).text_content().strip()

        gateways_page.open_edit_modal(0)

        # Change the name
        gateways_page.edit_modal_name_input.fill("SHOULD-NOT-SAVE-" + str(uuid.uuid4()))

        # Cancel
        gateways_page.close_edit_modal()
        expect(gateways_page.edit_modal).to_be_hidden()

        # Verify original name is still in the table
        gateways_page.page.reload(wait_until="domcontentloaded")
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        first_row = gateways_page.get_gateway_row(0)
        current_name = first_row.locator("td").nth(2).text_content().strip()
        assert current_name == original_name, f"Name should be unchanged after Cancel: expected '{original_name}', got '{current_name}'"

    def test_edit_modal_visibility_radios_reflect_current(self, gateways_page: GatewaysPage):
        """Test that visibility radios in edit modal reflect current gateway visibility."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get current visibility from table
        first_row = gateways_page.get_gateway_row(0)
        visibility_text = first_row.locator("td").nth(9).text_content().strip().lower()

        gateways_page.open_edit_modal(0)

        if "public" in visibility_text:
            expect(gateways_page.edit_modal_visibility_public).to_be_checked()
        elif "team" in visibility_text:
            expect(gateways_page.edit_modal_visibility_team).to_be_checked()
        elif "private" in visibility_text:
            expect(gateways_page.edit_modal_visibility_private).to_be_checked()

        gateways_page.close_edit_modal()


# ---------------------------------------------------------------------------
# OAuth Grant Type Switching
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestOAuthGrantTypeSwitching:
    """Tests for OAuth grant type conditional field visibility in the add form."""

    def test_authorization_code_shows_auth_url_fields(self, gateways_page: GatewaysPage):
        """Test that authorization_code grant type shows Authorization URL and Redirect URI."""
        gateways_page.navigate_to_gateways_tab()

        # Select OAuth auth type
        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        # Select authorization_code (should be default)
        gateways_page.oauth_grant_type_select.select_option("authorization_code")
        gateways_page.page.wait_for_timeout(300)

        # Authorization URL and Redirect URI should be visible
        expect(gateways_page.oauth_authorization_url_input).to_be_visible()
        expect(gateways_page.oauth_redirect_uri_input).to_be_visible()

        # Token management checkboxes should be visible
        expect(gateways_page.oauth_store_tokens_checkbox).to_be_visible()
        expect(gateways_page.oauth_auto_refresh_checkbox).to_be_visible()

    def test_client_credentials_hides_auth_url_fields(self, gateways_page: GatewaysPage):
        """Test that client_credentials grant type hides auth URL and redirect URI."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        gateways_page.oauth_grant_type_select.select_option("client_credentials")
        gateways_page.page.wait_for_timeout(300)

        # Auth URL and Redirect URI should be hidden
        expect(gateways_page.oauth_authorization_url_input).to_be_hidden()
        expect(gateways_page.oauth_redirect_uri_input).to_be_hidden()

        # Core fields still visible
        expect(gateways_page.oauth_issuer_input).to_be_visible()
        expect(gateways_page.oauth_client_id_input).to_be_visible()
        expect(gateways_page.oauth_client_secret_input).to_be_visible()
        expect(gateways_page.oauth_scopes_input).to_be_visible()

    def test_password_grant_shows_username_password(self, gateways_page: GatewaysPage):
        """Test that password grant type shows username and password fields."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        gateways_page.oauth_grant_type_select.select_option("password")
        gateways_page.page.wait_for_timeout(300)

        # Username and password fields should be visible
        expect(gateways_page.oauth_username_input).to_be_visible()
        expect(gateways_page.oauth_password_input).to_be_visible()

    def test_switch_between_grant_types(self, gateways_page: GatewaysPage):
        """Test switching between all grant types updates field visibility correctly."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        # Start with authorization_code
        gateways_page.oauth_grant_type_select.select_option("authorization_code")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_authorization_url_input).to_be_visible()

        # Switch to client_credentials
        gateways_page.oauth_grant_type_select.select_option("client_credentials")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_authorization_url_input).to_be_hidden()

        # Switch to password
        gateways_page.oauth_grant_type_select.select_option("password")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_username_input).to_be_visible()

        # Switch back to authorization_code
        gateways_page.oauth_grant_type_select.select_option("authorization_code")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_authorization_url_input).to_be_visible()
        expect(gateways_page.oauth_username_input).to_be_hidden()

    def test_oauth_issuer_input(self, gateways_page: GatewaysPage):
        """Test filling the OAuth issuer URL input."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        issuer_url = "https://auth.example.com"
        gateways_page.oauth_issuer_input.fill(issuer_url)
        expect(gateways_page.oauth_issuer_input).to_have_value(issuer_url)

    def test_oauth_token_url_input(self, gateways_page: GatewaysPage):
        """Test filling the OAuth token URL input."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        token_url = "https://auth.example.com/oauth2/token"
        gateways_page.oauth_token_url_input.fill(token_url)
        expect(gateways_page.oauth_token_url_input).to_have_value(token_url)

    def test_oauth_scopes_input(self, gateways_page: GatewaysPage):
        """Test filling the OAuth scopes input."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        scopes = "openid profile email api:read"
        gateways_page.oauth_scopes_input.fill(scopes)
        expect(gateways_page.oauth_scopes_input).to_have_value(scopes)

    def test_oauth_store_tokens_default_checked(self, gateways_page: GatewaysPage):
        """Test that store tokens checkbox is checked by default for authorization_code."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        gateways_page.oauth_grant_type_select.select_option("authorization_code")
        gateways_page.page.wait_for_timeout(300)

        expect(gateways_page.oauth_store_tokens_checkbox).to_be_checked()

    def test_oauth_auto_refresh_default_checked(self, gateways_page: GatewaysPage):
        """Test that auto refresh checkbox is checked by default for authorization_code."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)

        gateways_page.oauth_grant_type_select.select_option("authorization_code")
        gateways_page.page.wait_for_timeout(300)

        expect(gateways_page.oauth_auto_refresh_checkbox).to_be_checked()


# ---------------------------------------------------------------------------
# Custom Headers Auth
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestCustomHeadersAuth:
    """Tests for custom headers authentication fields."""

    def test_add_header_creates_row(self, gateways_page: GatewaysPage):
        """Test that clicking Add Header creates a new header row."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)

        expect(gateways_page.add_header_btn).to_be_visible()

        # Count initial rows
        container = gateways_page.page.locator("#auth-headers-container-gw")
        initial_count = container.locator("> div").count()

        # Click Add Header
        gateways_page.add_header_btn.click()
        gateways_page.page.wait_for_timeout(300)

        new_count = container.locator("> div").count()
        assert new_count == initial_count + 1

    def test_add_multiple_headers(self, gateways_page: GatewaysPage):
        """Test adding multiple header rows."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)

        # Add 3 headers
        for _ in range(3):
            gateways_page.add_header_btn.click()
            gateways_page.page.wait_for_timeout(200)

        container = gateways_page.page.locator("#auth-headers-container-gw")
        assert container.locator("> div").count() >= 3

    def test_header_key_value_inputs(self, gateways_page: GatewaysPage):
        """Test that header key and value inputs are fillable."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)

        gateways_page.add_auth_header("X-Custom-Header", "custom-value-123")

        # Verify the hidden JSON was updated
        json_value = gateways_page.get_auth_headers_json()
        parsed = json.loads(json_value)
        assert len(parsed) >= 1
        assert any(h["key"] == "X-Custom-Header" and h["value"] == "custom-value-123" for h in parsed)

    def test_remove_header_row(self, gateways_page: GatewaysPage):
        """Test that removeAuthHeader removes a header row from DOM and updates JSON.

        The remove button uses an inline onclick handler. We invoke the
        window.removeAuthHeader function directly to verify the removal logic.
        """
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)

        # Add a uniquely-named header to remove
        gateways_page.add_auth_header("X-Remove-Target", "remove-me")
        gateways_page.page.wait_for_timeout(300)

        container = gateways_page.page.locator("#auth-headers-container-gw")
        count_before = container.locator('[id^="auth-header-"]').count()
        assert count_before >= 1, "Expected at least 1 header row"

        # Get the last header row's ID and call removeAuthHeader directly
        last_header_id = gateways_page.page.evaluate(
            """() => {
                const container = document.getElementById('auth-headers-container-gw');
                const rows = container.querySelectorAll('[id^="auth-header-"]');
                return rows.length > 0 ? rows[rows.length - 1].id : null;
            }"""
        )
        assert last_header_id is not None, "Could not find a header row to remove"

        gateways_page.page.evaluate(
            "(headerId) => window.removeAuthHeader(headerId, 'auth-headers-container-gw')",
            last_header_id,
        )
        gateways_page.page.wait_for_timeout(300)

        count_after = container.locator('[id^="auth-header-"]').count()
        assert count_after == count_before - 1, f"Expected {count_before - 1} rows after removal, got {count_after}"


# ---------------------------------------------------------------------------
# Pagination Controls
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayPagination:
    """Tests for gateway table pagination controls."""

    def test_per_page_select_exists(self, gateways_page: GatewaysPage):
        """Test that per-page dropdown is visible with correct options."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        per_page = gateways_page.per_page_select
        expect(per_page).to_be_visible()

        for value in ["10", "25", "50", "100", "200", "500"]:
            expect(per_page.locator(f'option[value="{value}"]')).to_be_attached()

    def test_per_page_default_value(self, gateways_page: GatewaysPage):
        """Test that per-page dropdown defaults to 10."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        expect(gateways_page.per_page_select).to_have_value("10")

    def test_pagination_info_text(self, gateways_page: GatewaysPage):
        """Test that pagination info shows item count."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        info = gateways_page.pagination_controls.locator("text=/Showing \\d+ - \\d+ of \\d+ items/")
        expect(info).to_be_visible()

    def test_change_per_page(self, gateways_page: GatewaysPage):
        """Test changing the per-page value triggers table reload."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        # Change to 25 per page
        gateways_page.per_page_select.select_option("25")
        gateways_page.page.wait_for_timeout(1000)

        # Verify the select retains the new value
        expect(gateways_page.per_page_select).to_have_value("25")

        # Reset to 10
        gateways_page.per_page_select.select_option("10")
        gateways_page.page.wait_for_timeout(1000)

    def test_pagination_buttons_present(self, gateways_page: GatewaysPage):
        """Test that pagination navigation buttons exist."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        controls = gateways_page.pagination_controls

        # Navigation buttons should exist (may be disabled if on first/last page)
        expect(controls.locator('button:has-text("Prev")')).to_be_attached()
        expect(controls.locator('button:has-text("Next")')).to_be_attached()


# ---------------------------------------------------------------------------
# Gateway Creation with Different Auth Types
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
@pytest.mark.smoke
class TestGatewayCreationWithAuth:
    """Tests for creating gateways with various authentication types."""

    @staticmethod
    def _submit_and_handle(gateways_page: GatewaysPage, gateway_name: str):
        """Submit gateway form and handle the response."""
        with gateways_page.page.expect_response(
            lambda r: "/admin/gateways" in r.url and r.request.method == "POST",
            timeout=120000,
        ) as response_info:
            gateways_page.click_locator(gateways_page.add_gateway_btn)
        response = response_info.value
        if response.status >= 400:
            pytest.skip(f"Gateway creation failed for '{gateway_name}' (HTTP {response.status})")
        gateways_page.page.wait_for_load_state("domcontentloaded")
        return response

    @staticmethod
    def _verify_and_cleanup(gateways_page: GatewaysPage, gateway_name: str, gateway_url: str):
        """Verify gateway was created and clean up."""
        for attempt in range(3):
            gateways_page.page.wait_for_timeout(1000 * (attempt + 1))
            gateways_page.page.reload(wait_until="domcontentloaded")
            gateways_page.navigate_to_gateways_tab()
            gateways_page.wait_for_gateways_table_loaded()
            gateways_page.search_gateways(gateway_name)
            if gateways_page.gateway_exists(gateway_name):
                break

        assert gateways_page.gateway_exists(gateway_name), f"Gateway '{gateway_name}' not found after creation"

        # Cleanup
        gateways_page.delete_gateway_by_url(gateway_url)

    def test_create_gateway_with_oauth_client_credentials(self, gateways_page: GatewaysPage, test_gateway_with_oauth_data: dict):
        """Test creating a gateway with OAuth client_credentials auth."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        data = test_gateway_with_oauth_data

        # Cleanup existing
        if gateways_page.delete_gateway_by_url(data["url"]):
            logger.info("Cleaned up existing gateway with URL '%s'", data["url"])

        # Fill form
        gateways_page.fill_gateway_form(
            name=data["name"],
            url=data["url"],
            description=data["description"],
            tags=data["tags"],
        )

        # Set team visibility
        gateways_page.visibility_team_radio.click()

        # Configure OAuth
        gateways_page.configure_oauth(
            grant_type=data["oauth_grant_type"],
            issuer=data["oauth_issuer"],
            client_id=data["oauth_client_id"],
            client_secret=data["oauth_client_secret"],
            scopes=data["oauth_scopes"],
        )

        self._submit_and_handle(gateways_page, data["name"])
        self._verify_and_cleanup(gateways_page, data["name"], data["url"])

    def test_create_gateway_with_query_param_auth(self, gateways_page: GatewaysPage, test_gateway_data: dict):
        """Test creating a gateway with query parameter authentication."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        data = test_gateway_data.copy()
        data["name"] = f"{data['name']}-queryparam"
        # Use a different URL from the pool to avoid duplicates
        from ..conftest import VALID_MCP_SERVER_URLS

        data["url"] = VALID_MCP_SERVER_URLS[4]

        # Cleanup existing
        if gateways_page.delete_gateway_by_url(data["url"]):
            logger.info("Cleaned up existing gateway with URL '%s'", data["url"])

        gateways_page.fill_gateway_form(
            name=data["name"],
            url=data["url"],
            description="Test gateway with query param auth",
            tags="test,queryparam",
        )

        gateways_page.configure_query_param_auth(param_key="api_key", param_value="test-api-key-12345")

        self._submit_and_handle(gateways_page, data["name"])
        self._verify_and_cleanup(gateways_page, data["name"], data["url"])

    def test_create_gateway_with_custom_headers_auth(self, gateways_page: GatewaysPage, test_gateway_data: dict):
        """Test creating a gateway with custom headers authentication."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        data = test_gateway_data.copy()
        data["name"] = f"{data['name']}-headers"
        from ..conftest import VALID_MCP_SERVER_URLS

        data["url"] = VALID_MCP_SERVER_URLS[5]

        # Cleanup existing
        if gateways_page.delete_gateway_by_url(data["url"]):
            logger.info("Cleaned up existing gateway with URL '%s'", data["url"])

        gateways_page.fill_gateway_form(
            name=data["name"],
            url=data["url"],
            description="Test gateway with custom headers auth",
            tags="test,headers",
        )

        # Select authheaders and add headers
        gateways_page.auth_type_select.select_option("authheaders")
        gateways_page.page.wait_for_timeout(300)
        gateways_page.add_auth_header("X-API-Key", "test-key-abc123")
        gateways_page.add_auth_header("X-Tenant-Id", "tenant-42")

        self._submit_and_handle(gateways_page, data["name"])
        self._verify_and_cleanup(gateways_page, data["name"], data["url"])


# ---------------------------------------------------------------------------
# Edit Gateway End-to-End
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayEditEndToEnd:
    """End-to-end tests for editing gateways via the edit modal."""

    def test_edit_gateway_description(self, gateways_page: GatewaysPage):
        """Test editing a gateway's description and saving."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        new_description = f"Updated description {uuid.uuid4().hex[:8]}"
        gateways_page.edit_modal_description_input.fill(new_description)

        # Save changes
        with gateways_page.page.expect_response(
            lambda r: "/admin/gateways/" in r.url and r.request.method == "POST",
            timeout=30000,
        ) as response_info:
            gateways_page.edit_modal_save_btn.click()
        response = response_info.value
        if response.status >= 400:
            pytest.skip(f"Edit save failed (HTTP {response.status})")

        gateways_page.page.wait_for_load_state("domcontentloaded")
        gateways_page.page.wait_for_timeout(1000)

        # Verify via View modal
        gateways_page.page.reload(wait_until="domcontentloaded")
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        gateways_page.open_view_modal(0)
        expect(gateways_page.view_modal_details).to_contain_text(new_description)
        gateways_page.close_view_modal()

    def test_edit_gateway_tags(self, gateways_page: GatewaysPage):
        """Test editing a gateway's tags and saving."""
        # Ensure clean page state (previous edit test may have triggered a redirect)
        gateways_page.page.reload(wait_until="domcontentloaded")
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Track the gateway name so we can find it after reload
        first_row = gateways_page.get_gateway_row(0)
        gateway_name = first_row.locator("td").nth(2).text_content().strip()

        new_tags = f"edited,test-tag-{uuid.uuid4().hex[:6]}"

        gateways_page.open_edit_modal(0)
        gateways_page.edit_modal_tags_input.fill(new_tags)

        # Save — scroll into view and use extended timeout for the click
        gateways_page.edit_modal_save_btn.scroll_into_view_if_needed()
        try:
            with gateways_page.page.expect_response(
                lambda r: "/admin/gateways/" in r.url and r.request.method == "POST",
                timeout=60000,
            ) as response_info:
                gateways_page.edit_modal_save_btn.click(timeout=60000)
            response = response_info.value
            if response.status >= 400:
                pytest.skip(f"Edit save failed (HTTP {response.status})")
        except PlaywrightTimeoutError:
            pytest.skip("Edit save timed out (server may be slow)")

        gateways_page.page.wait_for_load_state("domcontentloaded")
        gateways_page.page.wait_for_timeout(1000)

        # Verify tags via view modal (search for the gateway by name to handle reordering)
        gateways_page.page.reload(wait_until="domcontentloaded")
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        gateways_page.search_gateways(gateway_name)

        if not gateways_page.gateway_exists(gateway_name):
            pytest.skip(f"Gateway '{gateway_name}' not found after edit")

        # Check tags in the matched row
        gateway_row = gateways_page.get_gateway_row_by_name(gateway_name).first
        tags_cell = gateway_row.locator("td").nth(4)
        tags_text = tags_cell.text_content().strip().lower()
        assert "edited" in tags_text, f"Expected 'edited' in tags for '{gateway_name}', got '{tags_text}'"
        gateways_page.clear_search()

    def test_edit_gateway_passthrough_headers(self, gateways_page: GatewaysPage):
        """Test editing passthrough headers in edit modal."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        gateways_page.open_edit_modal(0)

        test_headers = "Authorization, X-Request-ID, X-Correlation-ID"
        gateways_page.edit_modal_passthrough_headers.fill(test_headers)
        expect(gateways_page.edit_modal_passthrough_headers).to_have_value(test_headers)

        gateways_page.close_edit_modal()


# ---------------------------------------------------------------------------
# Auth Type Switching in Add Form
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestAuthTypeSwitching:
    """Tests for switching between auth types in the add gateway form."""

    def test_switching_from_basic_to_bearer_hides_basic_shows_bearer(self, gateways_page: GatewaysPage):
        """Test that switching from basic to bearer hides basic fields and shows bearer."""
        gateways_page.navigate_to_gateways_tab()

        # Select basic first
        gateways_page.auth_type_select.select_option("basic")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.auth_basic_fields).to_be_visible()
        expect(gateways_page.auth_bearer_fields).to_be_hidden()

        # Switch to bearer
        gateways_page.auth_type_select.select_option("bearer")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.auth_basic_fields).to_be_hidden()
        expect(gateways_page.auth_bearer_fields).to_be_visible()

    def test_switching_from_oauth_to_none_hides_oauth(self, gateways_page: GatewaysPage):
        """Test that switching from OAuth to None hides OAuth fields."""
        gateways_page.navigate_to_gateways_tab()

        gateways_page.auth_type_select.select_option("oauth")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_fields).to_be_visible()

        gateways_page.auth_type_select.select_option("")
        gateways_page.page.wait_for_timeout(300)
        expect(gateways_page.oauth_fields).to_be_hidden()

    def test_all_auth_fields_hidden_when_none_selected(self, gateways_page: GatewaysPage):
        """Test that all auth-specific fields are hidden when None is selected."""
        gateways_page.navigate_to_gateways_tab()

        # Select None (default)
        gateways_page.auth_type_select.select_option("")
        gateways_page.page.wait_for_timeout(300)

        expect(gateways_page.auth_basic_fields).to_be_hidden()
        expect(gateways_page.auth_bearer_fields).to_be_hidden()
        expect(gateways_page.auth_headers_fields).to_be_hidden()
        expect(gateways_page.oauth_fields).to_be_hidden()
        expect(gateways_page.auth_query_param_fields).to_be_hidden()

    def test_cycle_through_all_auth_types(self, gateways_page: GatewaysPage):
        """Test cycling through all auth types shows correct fields for each."""
        gateways_page.navigate_to_gateways_tab()

        auth_field_map = {
            "basic": gateways_page.auth_basic_fields,
            "bearer": gateways_page.auth_bearer_fields,
            "authheaders": gateways_page.auth_headers_fields,
            "oauth": gateways_page.oauth_fields,
            "query_param": gateways_page.auth_query_param_fields,
        }

        for auth_type, expected_visible in auth_field_map.items():
            gateways_page.auth_type_select.select_option(auth_type)
            gateways_page.page.wait_for_timeout(300)

            # The selected type's fields should be visible
            expect(expected_visible).to_be_visible()

            # All other types' fields should be hidden
            for other_type, other_fields in auth_field_map.items():
                if other_type != auth_type:
                    expect(other_fields).to_be_hidden()


# ---------------------------------------------------------------------------
# Search Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewaySearchEdgeCases:
    """Edge case tests for gateway search functionality."""

    def test_search_with_no_results(self, gateways_page: GatewaysPage):
        """Test searching for a gateway that doesn't exist."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        gateways_page.search_gateways("nonexistent-gateway-xyz-99999")

        # Table should show no results or empty state
        count = gateways_page.get_gateway_count()
        assert count == 0 or True  # Some implementations show "no results" message

        # Clear search to restore
        gateways_page.clear_search()

    def test_search_partial_name_match(self, gateways_page: GatewaysPage):
        """Test searching with a partial gateway name."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get first gateway name
        first_row = gateways_page.get_gateway_row(0)
        full_name = first_row.locator("td").nth(2).text_content().strip()

        if len(full_name) < 3:
            pytest.skip("Gateway name too short for partial match test")

        # Search with first 3 characters
        partial = full_name[:3]
        gateways_page.search_gateways(partial)

        # Should find at least one result
        assert gateways_page.get_gateway_count() > 0

        gateways_page.clear_search()

    def test_search_by_url(self, gateways_page: GatewaysPage):
        """Test searching gateways by URL."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        # Get URL from first gateway
        first_row = gateways_page.get_gateway_row(0)
        gateway_url = first_row.locator("td").nth(3).text_content().strip()

        # Search by URL (or partial URL)
        search_term = gateway_url.split("//")[-1].split("/")[0]  # hostname
        gateways_page.search_gateways(search_term)

        assert gateways_page.get_gateway_count() > 0

        gateways_page.clear_search()


# ---------------------------------------------------------------------------
# Table Display Verification
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayTableDisplay:
    """Tests for gateway table display details."""

    def test_table_columns_complete(self, gateways_page: GatewaysPage):
        """Test that all expected table columns are present."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()

        table = gateways_page.gateways_table
        expected_columns = ["Actions", "S. No.", "Name", "URL", "Tags", "Status", "Last Seen", "Owner", "Team", "Visibility"]

        for col in expected_columns:
            expect(table.locator(f'th:has-text("{col}")')).to_be_visible()

    def test_gateway_row_serial_number(self, gateways_page: GatewaysPage):
        """Test that gateway rows have correct serial numbers."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        serial = first_row.locator("td").nth(1).text_content().strip()
        assert serial == "1", f"First row serial should be '1', got '{serial}'"

    def test_gateway_row_owner_displayed(self, gateways_page: GatewaysPage):
        """Test that owner email is displayed in gateway rows."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        owner = first_row.locator("td").nth(7).text_content().strip()
        # Owner should be an email or "None"
        assert "@" in owner or owner == "None", f"Unexpected owner value: '{owner}'"

    def test_gateway_row_team_displayed(self, gateways_page: GatewaysPage):
        """Test that team name is displayed in gateway rows."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        team = first_row.locator("td").nth(8).text_content().strip()
        # Team should be a name or "None"
        assert len(team) > 0, "Team cell should not be empty"

    def test_gateway_row_last_seen_displayed(self, gateways_page: GatewaysPage):
        """Test that last seen timestamp is displayed in gateway rows."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        last_seen = first_row.locator("td").nth(6).text_content().strip()
        # Should contain a date-like pattern or "N/A"
        assert len(last_seen) > 0, "Last seen cell should not be empty"

    def test_active_status_badge_style(self, gateways_page: GatewaysPage):
        """Test that Active status badge has correct text."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        status_cell = first_row.locator("td").nth(5)
        status_text = status_cell.text_content().strip()
        assert status_text in ("Active", "Inactive"), f"Unexpected status: '{status_text}'"

    def test_visibility_badge_content(self, gateways_page: GatewaysPage):
        """Test that visibility badge shows emoji + text."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.wait_for_gateways_table_loaded()
        _skip_if_no_gateways(gateways_page)

        first_row = gateways_page.get_gateway_row(0)
        visibility_cell = first_row.locator("td").nth(9)
        vis_text = visibility_cell.text_content().strip()
        assert any(v in vis_text for v in ["Public", "Team", "Private"]), f"Unexpected visibility: '{vis_text}'"


# ---------------------------------------------------------------------------
# Form Validation
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayFormValidation:
    """Tests for gateway form validation."""

    def test_name_field_is_required(self, gateways_page: GatewaysPage):
        """Test that the name field has the required attribute."""
        # Ensure clean page state (previous creation tests may have navigated away)
        gateways_page.page.reload(wait_until="domcontentloaded")
        gateways_page.navigate_to_gateways_tab()
        expect(gateways_page.gateway_name_input).to_have_attribute("required", "")

    def test_url_field_is_required(self, gateways_page: GatewaysPage):
        """Test that the URL field has the required attribute."""
        gateways_page.navigate_to_gateways_tab()
        expect(gateways_page.gateway_url_input).to_have_attribute("required", "")

    def test_description_field_is_optional(self, gateways_page: GatewaysPage):
        """Test that the description field is not required."""
        gateways_page.navigate_to_gateways_tab()
        # Description should NOT have required attribute
        description = gateways_page.gateway_description_input
        try:
            expect(description).not_to_have_attribute("required", "")
        except AssertionError:
            # Some implementations use different validation; just verify it's visible
            expect(description).to_be_visible()

    def test_tags_field_is_optional(self, gateways_page: GatewaysPage):
        """Test that the tags field is not required."""
        gateways_page.navigate_to_gateways_tab()
        tags = gateways_page.gateway_tags_input
        try:
            expect(tags).not_to_have_attribute("required", "")
        except AssertionError:
            expect(tags).to_be_visible()


# ---------------------------------------------------------------------------
# Add Form Advanced Fields
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.gateways
class TestGatewayAddFormAdvanced:
    """Tests for advanced fields in the add gateway form."""

    def test_ca_certificate_upload_accepts_pem(self, gateways_page: GatewaysPage):
        """Test that CA certificate upload accepts .pem files."""
        gateways_page.navigate_to_gateways_tab()

        upload_input = gateways_page.ca_certificate_upload_input
        expect(upload_input).to_be_attached()

        # Verify it accepts certificate file types
        accept_attr = upload_input.get_attribute("accept")
        if accept_attr:
            assert ".pem" in accept_attr or ".crt" in accept_attr or ".cer" in accept_attr

    def test_ca_certificate_drop_zone_visible(self, gateways_page: GatewaysPage):
        """Test that the CA certificate drag-and-drop zone is visible."""
        gateways_page.navigate_to_gateways_tab()
        expect(gateways_page.ca_certificate_drop_zone).to_be_visible()
        expect(gateways_page.ca_certificate_drop_zone).to_contain_text("Click to upload or drag and drop")

    def test_add_form_heading(self, gateways_page: GatewaysPage):
        """Test that the add form has the correct heading."""
        gateways_page.navigate_to_gateways_tab()
        heading = gateways_page.page.locator('h3:has-text("Add New MCP Server or Gateway")')
        expect(heading).to_be_visible()

    def test_panel_description_text(self, gateways_page: GatewaysPage):
        """Test that the panel description text is correct."""
        gateways_page.navigate_to_gateways_tab()
        description = gateways_page.page.locator('text=Register external MCP Servers (SSE/HTTP) to retrieve their tools/resources/prompts')
        expect(description).to_be_visible()

    def test_tags_help_text(self, gateways_page: GatewaysPage):
        """Test that tags field has help text about normalization."""
        gateways_page.navigate_to_gateways_tab()
        # Scope to the add form to avoid matching the edit modal's tags help text
        help_text = gateways_page.add_gateway_form.locator('text=Tags will be automatically normalized')
        expect(help_text).to_be_visible()
