# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_agents.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Entity-level tests for A2A Agents.
"""

# Third-Party
import pytest

# Local
from ..pages.agents_page import AgentsPage


class TestAgentsEntity:
    """Entity-level tests for A2A Agent CRUD operations.

    These tests focus on the data model and business logic of agents,
    testing creation, retrieval, updates, and deletion through the UI.

    Examples:
        pytest tests/playwright/entities/test_agents.py
        pytest tests/playwright/entities/test_agents.py -v -k "agent_creation"
    """

    def test_agent_entity_structure(self, agents_page: AgentsPage):
        """Test that the agent entity has the expected structure."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()
        agents_page.wait_for_agents_panel_loaded()

        # Verify form fields represent the agent entity structure
        assert agents_page.agent_name_input.count() > 0, "Agent name field should exist"
        assert agents_page.agent_endpoint_url_input.count() > 0, "Endpoint URL field should exist"
        assert agents_page.agent_type_select.count() > 0, "Agent type field should exist"
        assert agents_page.auth_type_select.count() > 0, "Auth type field should exist"
        assert agents_page.agent_description_textarea.count() > 0, "Description field should exist"
        assert agents_page.agent_tags_input.count() > 0, "Tags field should exist"

    def test_agent_required_fields(self, agents_page: AgentsPage):
        """Test that required fields are properly marked."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check required attribute on name field
        name_required = agents_page.agent_name_input.get_attribute("required")
        assert name_required is not None, "Agent name should be required"

        # Check required attribute on endpoint URL field
        url_required = agents_page.agent_endpoint_url_input.get_attribute("required")
        assert url_required is not None, "Endpoint URL should be required"

    def test_agent_type_enum_values(self, agents_page: AgentsPage):
        """Test that agent type has correct enum values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Get all agent type options
        options = agents_page.agent_type_select.locator("option")
        option_values = []
        for i in range(options.count()):
            value = options.nth(i).get_attribute("value")
            if value:
                option_values.append(value)

        # Verify expected agent types
        expected_types = ["generic", "openai", "anthropic", "custom"]
        for expected_type in expected_types:
            assert expected_type in option_values, f"Agent type '{expected_type}' should be available"

    def test_auth_type_enum_values(self, agents_page: AgentsPage):
        """Test that authentication type has correct enum values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Get all auth type options
        options = agents_page.auth_type_select.locator("option")
        option_values = []
        for i in range(options.count()):
            value = options.nth(i).get_attribute("value")
            option_values.append(value)  # Include empty string for "None"

        # Verify expected auth types
        expected_auth_types = ["", "basic", "bearer", "authheaders", "oauth", "query_param"]
        for expected_auth in expected_auth_types:
            assert expected_auth in option_values, f"Auth type '{expected_auth or 'none'}' should be available"

    def test_visibility_enum_values(self, agents_page: AgentsPage):
        """Test that visibility has correct enum values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check visibility radio buttons
        public_value = agents_page.visibility_public_radio.get_attribute("value")
        team_value = agents_page.visibility_team_radio.get_attribute("value")
        private_value = agents_page.visibility_private_radio.get_attribute("value")

        assert public_value == "public", "Public visibility should have value 'public'"
        assert team_value == "team", "Team visibility should have value 'team'"
        assert private_value == "private", "Private visibility should have value 'private'"

    def test_agent_default_values(self, agents_page: AgentsPage):
        """Test that agent fields have correct default values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check default agent type
        default_agent_type = agents_page.agent_type_select.input_value()
        assert default_agent_type == "generic", "Default agent type should be 'generic'"

        # Check default auth type (should be empty/none)
        default_auth_type = agents_page.auth_type_select.input_value()
        assert default_auth_type == "", "Default auth type should be empty (none)"

        # Check default visibility (should be public)
        assert agents_page.visibility_public_radio.is_checked(), "Default visibility should be public"

    def test_agent_name_validation(self, agents_page: AgentsPage):
        """Test agent name field validation."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check placeholder text
        placeholder = agents_page.agent_name_input.get_attribute("placeholder")
        assert placeholder == "my-assistant-agent", "Name field should have helpful placeholder"

        # Verify it's a text input
        input_type = agents_page.agent_name_input.get_attribute("type")
        assert input_type == "text", "Name field should be text input"

    def test_endpoint_url_validation(self, agents_page: AgentsPage):
        """Test endpoint URL field validation."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check placeholder text
        placeholder = agents_page.agent_endpoint_url_input.get_attribute("placeholder")
        assert "https://" in placeholder, "URL field should have URL placeholder"

        # Verify it's a URL input
        input_type = agents_page.agent_endpoint_url_input.get_attribute("type")
        assert input_type == "url", "Endpoint URL field should be URL input type"

    def test_oauth_grant_type_values(self, agents_page: AgentsPage):
        """Test OAuth grant type enum values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Select OAuth to reveal grant type field
        agents_page.set_auth_type("oauth")
        agents_page.wait_for_visible(agents_page.auth_oauth_fields)

        # Get grant type options
        options = agents_page.oauth_grant_type_select.locator("option")
        option_values = []
        for i in range(options.count()):
            value = options.nth(i).get_attribute("value")
            if value:
                option_values.append(value)

        # Verify expected grant types
        expected_grant_types = ["authorization_code", "client_credentials", "password"]
        for expected_grant in expected_grant_types:
            assert expected_grant in option_values, f"OAuth grant type '{expected_grant}' should be available"

    def test_tags_field_format(self, agents_page: AgentsPage):
        """Test that tags field accepts comma-separated values."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check placeholder text
        placeholder = agents_page.agent_tags_input.get_attribute("placeholder")
        assert "comma-separated" in placeholder.lower(), "Tags field should indicate comma-separated format"

    def test_description_field_multiline(self, agents_page: AgentsPage):
        """Test that description field is a textarea."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify it's a textarea element
        tag_name = agents_page.agent_description_textarea.evaluate("el => el.tagName")
        assert tag_name.lower() == "textarea", "Description field should be a textarea"

        # Check rows attribute
        rows = agents_page.agent_description_textarea.get_attribute("rows")
        assert rows == "2", "Description textarea should have 2 rows"

    def test_passthrough_headers_field_format(self, agents_page: AgentsPage):
        """Test passthrough headers field format."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Check placeholder text
        placeholder = agents_page.passthrough_headers_input.get_attribute("placeholder")
        assert "," in placeholder, "Passthrough headers should show comma-separated format"
        assert "Authorization" in placeholder, "Placeholder should show example headers"

    def test_form_error_display_element(self, agents_page: AgentsPage):
        """Test that form has error display element."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify error message element exists
        assert agents_page.form_error_message.count() > 0, "Form should have error message element"

        # Check it has correct ID
        error_id = agents_page.form_error_message.get_attribute("id")
        assert error_id == "a2aFormError", "Error element should have correct ID"

    def test_form_loading_indicator_element(self, agents_page: AgentsPage):
        """Test that form has loading indicator element."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Verify loading indicator exists
        assert agents_page.form_loading_indicator.count() > 0, "Form should have loading indicator"

        # Check it has correct ID
        loading_id = agents_page.form_loading_indicator.get_attribute("id")
        assert loading_id == "add-a2a-loading", "Loading indicator should have correct ID"

    def test_basic_auth_fields_structure(self, agents_page: AgentsPage):
        """Test basic authentication fields structure."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Select basic auth
        agents_page.set_auth_type("basic")
        agents_page.wait_for_visible(agents_page.auth_basic_fields)

        # Verify username field
        username_name = agents_page.auth_username_input.get_attribute("name")
        assert username_name == "auth_username", "Username field should have correct name attribute"

        # Verify password field
        password_name = agents_page.auth_password_input.get_attribute("name")
        password_type = agents_page.auth_password_input.get_attribute("type")
        assert password_name == "auth_password", "Password field should have correct name attribute"
        assert password_type == "password", "Password field should be password type"

    def test_bearer_token_field_structure(self, agents_page: AgentsPage):
        """Test bearer token field structure."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Select bearer auth
        agents_page.set_auth_type("bearer")
        agents_page.wait_for_visible(agents_page.auth_bearer_fields)

        # Verify token field
        token_name = agents_page.auth_token_input.get_attribute("name")
        token_type = agents_page.auth_token_input.get_attribute("type")
        assert token_name == "auth_token", "Token field should have correct name attribute"
        assert token_type == "password", "Token field should be password type for security"

    def test_query_param_security_warning(self, agents_page: AgentsPage):
        """Test that query parameter auth shows security warning."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Select query param auth
        agents_page.set_auth_type("query_param")
        agents_page.wait_for_visible(agents_page.auth_query_param_fields)

        # Verify security warning is visible
        warning = agents_page.auth_query_param_fields.locator("text=Security Warning")
        assert warning.count() > 0, "Query param auth should show security warning"
        assert warning.is_visible(), "Security warning should be visible"

    @pytest.mark.parametrize(
        "auth_type,expected_fields",
        [
            ("basic", ["auth_username", "auth_password"]),
            ("bearer", ["auth_token"]),
            ("query_param", ["auth_query_param_key", "auth_query_param_value"]),
        ],
    )
    def test_auth_type_field_mapping(self, agents_page: AgentsPage, auth_type: str, expected_fields: list):
        """Test that each auth type shows correct fields."""
        # Navigate to agents tab
        agents_page.navigate_to_agents_tab()

        # Select auth type and wait for fields to appear
        agents_page.set_auth_type(auth_type)
        auth_fields_map = {"basic": agents_page.auth_basic_fields, "bearer": agents_page.auth_bearer_fields, "query_param": agents_page.auth_query_param_fields}
        agents_page.wait_for_visible(auth_fields_map[auth_type])

        # Verify expected fields are present - scope to agents panel to avoid strict mode violations
        # (multiple forms on page with same field names)
        for field_name in expected_fields:
            field = agents_page.agents_panel.locator(f'input[name="{field_name}"]').first
            assert field.count() > 0, f"Field '{field_name}' should exist for auth type '{auth_type}'"
            assert field.is_visible(), f"Field '{field_name}' should be visible for auth type '{auth_type}'"
