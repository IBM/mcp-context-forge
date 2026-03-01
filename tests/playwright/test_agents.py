# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_agents.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A2A Agents UI tests for agent management features.
"""

# Standard
from typing import Any, Dict

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .pages.agents_page import AgentsPage


class TestAgentsUI:
    """A2A Agents UI tests for agent management features.

    Tests agent creation, configuration, authentication types, and management
    through the admin interface.

    Examples:
        pytest tests/playwright/test_agents.py
        pytest tests/playwright/test_agents.py -v -k "create_agent"
    """

    def test_agents_panel_loads(self, agents_page: AgentsPage):
        """Test that the A2A agents panel loads correctly."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify panel is visible
        expect(agents_page.agents_panel).to_be_visible()
        expect(agents_page.panel_title).to_be_visible()
        expect(agents_page.panel_title).to_have_text("A2A Agents Catalog")

    def test_add_agent_form_visible(self, agents_page: AgentsPage):
        """Test that the add agent form is visible and has correct title."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify form is visible
        expect(agents_page.add_agent_form).to_be_visible()
        expect(agents_page.form_title).to_be_visible()
        expect(agents_page.form_title).to_have_text("Add New A2A Agent")

    def test_agent_form_fields_present(self, agents_page: AgentsPage):
        """Test that all required form fields are present."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify all main form fields are present
        expect(agents_page.agent_name_input).to_be_visible()
        expect(agents_page.agent_endpoint_url_input).to_be_visible()
        expect(agents_page.agent_type_select).to_be_visible()
        expect(agents_page.auth_type_select).to_be_visible()
        expect(agents_page.agent_description_textarea).to_be_visible()
        expect(agents_page.agent_tags_input).to_be_visible()
        expect(agents_page.add_agent_btn).to_be_visible()

    def test_agent_type_options(self, agents_page: AgentsPage):
        """Test that agent type select has correct options."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Get agent type options
        options = agents_page.agent_type_select.locator("option")
        option_values = [options.nth(i).get_attribute("value") for i in range(options.count())]

        # Verify expected options are present
        assert "a2a-jsonrpc" in option_values
        assert "a2a-rest" in option_values
        assert "a2a-grpc" in option_values
        assert "rest-passthrough" in option_values
        assert "custom" in option_values

    def test_auth_type_options(self, agents_page: AgentsPage):
        """Test that authentication type select has correct options."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Get auth type options
        options = agents_page.auth_type_select.locator("option")
        option_values = [options.nth(i).get_attribute("value") for i in range(options.count())]

        # Verify expected options are present
        assert "" in option_values  # None option
        assert "basic" in option_values
        assert "bearer" in option_values
        assert "authheaders" in option_values
        assert "oauth" in option_values
        assert "query_param" in option_values

    def test_visibility_radio_buttons(self, agents_page: AgentsPage):
        """Test that visibility radio buttons are present and functional."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify all visibility options are present
        expect(agents_page.visibility_public_radio).to_be_visible()
        expect(agents_page.visibility_team_radio).to_be_visible()
        expect(agents_page.visibility_private_radio).to_be_visible()

        # Verify public is checked by default
        expect(agents_page.visibility_public_radio).to_be_checked()

        # Test switching visibility
        agents_page.click_locator(agents_page.visibility_team_radio)
        expect(agents_page.visibility_team_radio).to_be_checked()
        expect(agents_page.visibility_public_radio).not_to_be_checked()

    def test_basic_auth_fields_visibility(self, agents_page: AgentsPage):
        """Test that basic auth fields appear when basic auth is selected."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Initially, basic auth fields should be hidden
        expect(agents_page.auth_basic_fields).to_be_hidden()

        # Select basic auth
        agents_page.set_auth_type("basic")
        agents_page.page.wait_for_timeout(500)

        # Verify basic auth fields are now visible
        expect(agents_page.auth_basic_fields).to_be_visible()
        expect(agents_page.auth_username_input).to_be_visible()
        expect(agents_page.auth_password_input).to_be_visible()

    def test_bearer_auth_fields_visibility(self, agents_page: AgentsPage):
        """Test that bearer token fields appear when bearer auth is selected."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Initially, bearer auth fields should be hidden
        expect(agents_page.auth_bearer_fields).to_be_hidden()

        # Select bearer auth
        agents_page.set_auth_type("bearer")
        agents_page.page.wait_for_timeout(500)

        # Verify bearer auth fields are now visible
        expect(agents_page.auth_bearer_fields).to_be_visible()
        expect(agents_page.auth_token_input).to_be_visible()

    def test_oauth_fields_visibility(self, agents_page: AgentsPage):
        """Test that OAuth fields appear when OAuth is selected."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Initially, OAuth fields should be hidden
        expect(agents_page.auth_oauth_fields).to_be_hidden()

        # Select OAuth auth
        agents_page.set_auth_type("oauth")
        agents_page.page.wait_for_timeout(500)

        # Verify OAuth fields are now visible
        expect(agents_page.auth_oauth_fields).to_be_visible()
        expect(agents_page.oauth_grant_type_select).to_be_visible()
        expect(agents_page.oauth_issuer_input).to_be_visible()

    def test_query_param_auth_fields_visibility(self, agents_page: AgentsPage):
        """Test that query parameter auth fields appear when selected."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Initially, query param fields should be hidden
        expect(agents_page.auth_query_param_fields).to_be_hidden()

        # Select query param auth
        agents_page.set_auth_type("query_param")
        agents_page.page.wait_for_timeout(500)

        # Verify query param fields are now visible
        expect(agents_page.auth_query_param_fields).to_be_visible()
        expect(agents_page.auth_query_param_key_input).to_be_visible()
        expect(agents_page.auth_query_param_value_input).to_be_visible()

    def test_fill_agent_form_basic(self, agents_page: AgentsPage, test_agent_data: Dict[str, Any]):
        """Test filling the agent form with basic data."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Fill the form
        agents_page.fill_agent_form_basic(
            name=test_agent_data["name"],
            endpoint_url=test_agent_data["endpoint_url"],
            agent_type=test_agent_data["agent_type"],
            description=test_agent_data["description"],
            tags=test_agent_data["tags"],
            visibility=test_agent_data["visibility"],
        )

        # Verify fields are filled
        expect(agents_page.agent_name_input).to_have_value(test_agent_data["name"])
        expect(agents_page.agent_endpoint_url_input).to_have_value(test_agent_data["endpoint_url"])
        expect(agents_page.agent_description_textarea).to_have_value(test_agent_data["description"])
        expect(agents_page.agent_tags_input).to_have_value(test_agent_data["tags"])

    def test_form_validation_required_fields(self, agents_page: AgentsPage):
        """Test form validation for required fields."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Try to submit empty form
        agents_page.click_locator(agents_page.add_agent_btn)

        # Check for HTML5 validation on required fields
        name_valid = agents_page.agent_name_input.evaluate("el => el.checkValidity()")
        url_valid = agents_page.agent_endpoint_url_input.evaluate("el => el.checkValidity()")

        assert name_valid is False, "Name field should be invalid when empty"
        assert url_valid is False, "Endpoint URL field should be invalid when empty"

    def test_search_input_present(self, agents_page: AgentsPage):
        """Test that the agents search input is present."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify search input is visible
        expect(agents_page.agents_search_input).to_be_visible()

    def test_fill_basic_auth_helper(self, agents_page: AgentsPage):
        """Test the fill_basic_auth helper method."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Use helper to fill basic auth
        agents_page.fill_basic_auth("testuser", "testpass")

        # Verify fields are filled and visible
        expect(agents_page.auth_basic_fields).to_be_visible()
        expect(agents_page.auth_username_input).to_have_value("testuser")
        expect(agents_page.auth_password_input).to_have_value("testpass")

    def test_fill_bearer_auth_helper(self, agents_page: AgentsPage):
        """Test the fill_bearer_auth helper method."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Use helper to fill bearer auth
        agents_page.fill_bearer_auth("test-bearer-token-123")

        # Verify field is filled and visible
        expect(agents_page.auth_bearer_fields).to_be_visible()
        expect(agents_page.auth_token_input).to_have_value("test-bearer-token-123")

    def test_fill_oauth_config_helper(self, agents_page: AgentsPage):
        """Test the fill_oauth_config helper method."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Use helper to fill OAuth config
        agents_page.fill_oauth_config(
            grant_type="client_credentials",
            issuer="https://oauth.example.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
            token_url="https://oauth.example.com/token",
            scopes="read write",
        )

        # Verify fields are filled and visible
        expect(agents_page.auth_oauth_fields).to_be_visible()
        expect(agents_page.oauth_issuer_input).to_have_value("https://oauth.example.com")
        expect(agents_page.oauth_client_id_input).to_have_value("test-client-id")
        expect(agents_page.oauth_client_secret_input).to_have_value("test-client-secret")
        expect(agents_page.oauth_token_url_input).to_have_value("https://oauth.example.com/token")
        expect(agents_page.oauth_scopes_input).to_have_value("read write")

    def test_passthrough_headers_field(self, agents_page: AgentsPage):
        """Test the passthrough headers field."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Fill passthrough headers
        test_headers = "Authorization, X-Tenant-Id, X-Trace-Id"
        agents_page.fill_locator(agents_page.passthrough_headers_input, test_headers)

        # Verify field is filled
        expect(agents_page.passthrough_headers_input).to_have_value(test_headers)

    def test_search_clear_button_present(self, agents_page: AgentsPage):
        """Test that the clear search button is present."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify clear search button is visible
        expect(agents_page.agents_clear_search_btn).to_be_visible()

    def test_search_agents_by_tag(self, agents_page: AgentsPage):
        """Test searching agents by tag."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Get initial agent count (if any agents exist)
        initial_rows = agents_page.agent_rows.count()

        if initial_rows == 0:
            pytest.skip("No agents available to test search functionality")

        # Search for a common tag (based on test data: "test", "automation", "ai")
        agents_page.search_agents("test")

        # Wait for search to filter
        agents_page.page.wait_for_timeout(1000)

        # Verify search input has the value
        expect(agents_page.agents_search_input).to_have_value("test")

    def test_clear_search_functionality(self, agents_page: AgentsPage):
        """Test clearing the search input."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Get initial agent count
        initial_rows = agents_page.agent_rows.count()

        if initial_rows == 0:
            pytest.skip("No agents available to test search functionality")

        # Perform a search
        agents_page.search_agents("test")
        expect(agents_page.agents_search_input).to_have_value("test")

        # Clear the search
        agents_page.clear_search()

        # Verify search input is cleared
        expect(agents_page.agents_search_input).to_have_value("")

    def test_search_with_no_results(self, agents_page: AgentsPage):
        """Test searching with a term that returns no results."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Get initial agent count
        initial_rows = agents_page.agent_rows.count()

        if initial_rows == 0:
            pytest.skip("No agents available to test search functionality")

        # Search for something that won't match
        agents_page.search_agents("xyznonexistentag999")

        # Wait for search to filter
        agents_page.page.wait_for_timeout(1000)

        # Verify search input has the value
        expect(agents_page.agents_search_input).to_have_value("xyznonexistentag999")

    @pytest.mark.slow
    def test_create_agent_no_auth(self, agents_page: AgentsPage, test_agent_data: Dict[str, Any]):
        """Test creating an agent without authentication (integration test).

        Note: This test attempts actual agent creation and may fail if the backend
        is not properly configured or if the endpoint validation is strict.
        """
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Fill and submit the form
        agents_page.fill_agent_form_basic(
            name=test_agent_data["name"],
            endpoint_url=test_agent_data["endpoint_url"],
            agent_type=test_agent_data["agent_type"],
            description=test_agent_data["description"],
            tags=test_agent_data["tags"],
            visibility=test_agent_data["visibility"],
        )

        # Submit the form and capture response
        with agents_page.page.expect_response(lambda response: "/admin/a2a" in response.url and response.request.method == "POST") as response_info:
            agents_page.submit_agent_form()

        response = response_info.value

        # The server should respond with either success (2xx) or a validation error (4xx).
        # A 5xx would indicate an unexpected server error.
        assert response.status < 500, f"Unexpected server error: {response.status}"
