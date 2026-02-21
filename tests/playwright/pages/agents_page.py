# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/agents_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

A2A Agents page object for Agent management features.
"""

# Third-Party
from playwright.sync_api import expect, Locator

# Local
from .base_page import BasePage


class AgentsPage(BasePage):
    """Page object for A2A Agent management features."""

    # ==================== Panel Elements ====================

    @property
    def agents_panel(self) -> Locator:
        """A2A Agents panel container."""
        return self.page.locator("#a2a-agents-panel")

    @property
    def panel_title(self) -> Locator:
        """Panel title 'A2A Agents Catalog'."""
        return self.agents_panel.locator("h2").first

    # ==================== Agent Form Elements ====================

    @property
    def add_agent_form(self) -> Locator:
        """Add A2A agent form."""
        return self.page.locator("#add-a2a-form")

    @property
    def form_title(self) -> Locator:
        """Form title 'Add New A2A Agent' (located above the form in a separate div)."""
        return self.agents_panel.locator("h3:has-text('Add New A2A Agent')").first

    @property
    def registered_agents_title(self) -> Locator:
        """Registered agents section title 'Registered A2A Agents'."""
        return self.agents_panel.locator("h3:has-text('Registered A2A Agents')").first

    @property
    def agent_name_input(self) -> Locator:
        """Agent name input field."""
        return self.add_agent_form.locator("#a2a-agent-name")

    @property
    def agent_endpoint_url_input(self) -> Locator:
        """Agent endpoint URL input field."""
        return self.add_agent_form.locator("#a2a-agent-endpoint-url")

    @property
    def agent_type_select(self) -> Locator:
        """Agent type select field."""
        return self.add_agent_form.locator("#a2a-agent-type")

    @property
    def auth_type_select(self) -> Locator:
        """Authentication type select field."""
        return self.add_agent_form.locator("#auth-type-a2a")

    @property
    def agent_description_textarea(self) -> Locator:
        """Agent description textarea field."""
        return self.add_agent_form.locator("#a2a-agent-description")

    @property
    def agent_tags_input(self) -> Locator:
        """Agent tags input field."""
        return self.add_agent_form.locator("#a2a-agent-tags")

    @property
    def visibility_public_radio(self) -> Locator:
        """Public visibility radio button."""
        return self.add_agent_form.locator("#a2a-visibility-public")

    @property
    def visibility_team_radio(self) -> Locator:
        """Team visibility radio button."""
        return self.add_agent_form.locator("#a2a-visibility-team")

    @property
    def visibility_private_radio(self) -> Locator:
        """Private visibility radio button."""
        return self.add_agent_form.locator("#a2a-visibility-private")

    @property
    def passthrough_headers_input(self) -> Locator:
        """Passthrough headers input field."""
        return self.add_agent_form.locator('input[name="passthrough_headers"]')

    @property
    def add_agent_btn(self) -> Locator:
        """Add agent submit button."""
        return self.add_agent_form.locator('button[type="submit"]:has-text("Add A2A Agent")')

    @property
    def form_error_message(self) -> Locator:
        """Form error message display."""
        return self.page.locator("#a2aFormError")

    @property
    def form_loading_indicator(self) -> Locator:
        """Form loading indicator."""
        return self.page.locator("#add-a2a-loading")

    # ==================== Authentication Fields ====================

    # Basic Auth Fields
    @property
    def auth_basic_fields(self) -> Locator:
        """Basic auth fields container."""
        return self.page.locator("#auth-basic-fields-a2a")

    @property
    def auth_username_input(self) -> Locator:
        """Basic auth username input."""
        return self.auth_basic_fields.locator('input[name="auth_username"]')

    @property
    def auth_password_input(self) -> Locator:
        """Basic auth password input."""
        return self.auth_basic_fields.locator('input[name="auth_password"]')

    # Bearer Token Fields
    @property
    def auth_bearer_fields(self) -> Locator:
        """Bearer token fields container."""
        return self.page.locator("#auth-bearer-fields-a2a")

    @property
    def auth_token_input(self) -> Locator:
        """Bearer token input."""
        return self.auth_bearer_fields.locator('input[name="auth_token"]')

    # Custom Headers Fields
    @property
    def auth_headers_fields(self) -> Locator:
        """Custom headers fields container."""
        return self.page.locator("#auth-headers-fields-a2a")

    @property
    def auth_headers_container(self) -> Locator:
        """Custom headers dynamic container."""
        return self.page.locator("#auth-headers-container-a2a")

    # Query Parameter Fields
    @property
    def auth_query_param_fields(self) -> Locator:
        """Query parameter auth fields container."""
        return self.page.locator("#auth-query_param-fields-a2a")

    @property
    def auth_query_param_key_input(self) -> Locator:
        """Query parameter key input."""
        return self.auth_query_param_fields.locator('input[name="auth_query_param_key"]')

    @property
    def auth_query_param_value_input(self) -> Locator:
        """Query parameter value input."""
        return self.auth_query_param_fields.locator('input[name="auth_query_param_value"]')

    # OAuth Fields
    @property
    def auth_oauth_fields(self) -> Locator:
        """OAuth fields container."""
        return self.page.locator("#auth-oauth-fields-a2a")

    @property
    def oauth_grant_type_select(self) -> Locator:
        """OAuth grant type select."""
        return self.auth_oauth_fields.locator("#oauth-grant-type-a2a")

    @property
    def oauth_issuer_input(self) -> Locator:
        """OAuth issuer URL input."""
        return self.auth_oauth_fields.locator('input[name="oauth_issuer"]')

    @property
    def oauth_client_id_input(self) -> Locator:
        """OAuth client ID input."""
        return self.auth_oauth_fields.locator('input[name="oauth_client_id"]')

    @property
    def oauth_client_secret_input(self) -> Locator:
        """OAuth client secret input."""
        return self.auth_oauth_fields.locator('input[name="oauth_client_secret"]')

    @property
    def oauth_token_url_input(self) -> Locator:
        """OAuth token URL input."""
        return self.auth_oauth_fields.locator('input[name="oauth_token_url"]')

    @property
    def oauth_authorization_url_input(self) -> Locator:
        """OAuth authorization URL input."""
        return self.auth_oauth_fields.locator('input[name="oauth_authorization_url"]')

    @property
    def oauth_redirect_uri_input(self) -> Locator:
        """OAuth redirect URI input."""
        return self.auth_oauth_fields.locator('input[name="oauth_redirect_uri"]')

    @property
    def oauth_scopes_input(self) -> Locator:
        """OAuth scopes input."""
        return self.auth_oauth_fields.locator('input[name="oauth_scopes"]')

    # ==================== Search and Table Elements ====================

    @property
    def agents_search_input(self) -> Locator:
        """Agents search input."""
        return self.page.locator("#a2a-agents-search-input")

    @property
    def agents_clear_search_btn(self) -> Locator:
        """Clear search button."""
        return self.page.locator("#a2a-agents-clear-search")

    @property
    def agents_table(self) -> Locator:
        """Agents table (if exists)."""
        return self.agents_panel.locator("table")

    @property
    def agents_table_body(self) -> Locator:
        """Agents table body."""
        return self.agents_table.locator("tbody")

    @property
    def agent_rows(self) -> Locator:
        """All agent table rows."""
        return self.agents_table_body.locator("tr")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_agents_tab(self) -> None:
        """Navigate to A2A Agents tab and wait for panel to be visible."""
        self.sidebar.click_tab_by_id("tab-a2a-agents", "a2a-agents-panel")

    # ==================== High-Level Agent Operations ====================

    def wait_for_agents_panel_loaded(self, timeout: int = 30000) -> None:
        """Wait for agents panel to be loaded and ready.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#a2a-agents-panel:not(.hidden)", timeout=timeout)
        # Wait for form to be attached
        self.wait_for_attached(self.add_agent_form, timeout=timeout)

    def create_agent_basic(self, name: str, endpoint_url: str, agent_type: str = "a2a-jsonrpc", description: str = "", tags: str = "", visibility: str = "public") -> None:
        """Create a new A2A agent with basic configuration (no auth).

        Args:
            name: Agent name
            endpoint_url: Agent endpoint URL
            agent_type: Agent type (a2a-jsonrpc, a2a-rest, a2a-grpc, rest-passthrough, custom)
            description: Agent description
            tags: Comma-separated tags
            visibility: Visibility setting (public, team, private)
        """
        self.fill_locator(self.agent_name_input, name)
        self.fill_locator(self.agent_endpoint_url_input, endpoint_url)
        self.agent_type_select.select_option(agent_type)

        if description:
            self.fill_locator(self.agent_description_textarea, description)

        if tags:
            self.fill_locator(self.agent_tags_input, tags)

        # Set visibility
        if visibility == "team":
            self.click_locator(self.visibility_team_radio)
        elif visibility == "private":
            self.click_locator(self.visibility_private_radio)
        else:
            self.click_locator(self.visibility_public_radio)

        self.click_locator(self.add_agent_btn)

    def fill_agent_form_basic(self, name: str, endpoint_url: str, agent_type: str = "a2a-jsonrpc", description: str = "", tags: str = "", visibility: str = "public") -> None:
        """Fill the add agent form with basic data (without submitting).

        Args:
            name: Agent name
            endpoint_url: Agent endpoint URL
            agent_type: Agent type (a2a-jsonrpc, a2a-rest, a2a-grpc, rest-passthrough, custom)
            description: Agent description
            tags: Comma-separated tags
            visibility: Visibility setting (public, team, private)
        """
        self.fill_locator(self.agent_name_input, name)
        self.fill_locator(self.agent_endpoint_url_input, endpoint_url)
        self.agent_type_select.select_option(agent_type)

        if description:
            self.fill_locator(self.agent_description_textarea, description)

        if tags:
            self.fill_locator(self.agent_tags_input, tags)

        # Set visibility
        if visibility == "team":
            self.click_locator(self.visibility_team_radio)
        elif visibility == "private":
            self.click_locator(self.visibility_private_radio)
        else:
            self.click_locator(self.visibility_public_radio)

    def set_auth_type(self, auth_type: str) -> None:
        """Set the authentication type.

        Args:
            auth_type: Authentication type (none, basic, bearer, authheaders, oauth, query_param)
        """
        self.auth_type_select.select_option(auth_type if auth_type != "none" else "")

    def fill_basic_auth(self, username: str, password: str) -> None:
        """Fill basic authentication fields.

        Args:
            username: Basic auth username
            password: Basic auth password
        """
        self.set_auth_type("basic")
        self.wait_for_visible(self.auth_basic_fields)
        self.fill_locator(self.auth_username_input, username)
        self.fill_locator(self.auth_password_input, password)

    def fill_bearer_auth(self, token: str) -> None:
        """Fill bearer token authentication field.

        Args:
            token: Bearer token
        """
        self.set_auth_type("bearer")
        self.wait_for_visible(self.auth_bearer_fields)
        self.fill_locator(self.auth_token_input, token)

    def fill_query_param_auth(self, param_key: str, param_value: str) -> None:
        """Fill query parameter authentication fields.

        Args:
            param_key: Query parameter key
            param_value: Query parameter value
        """
        self.set_auth_type("query_param")
        self.wait_for_visible(self.auth_query_param_fields)
        self.fill_locator(self.auth_query_param_key_input, param_key)
        self.fill_locator(self.auth_query_param_value_input, param_value)

    def fill_oauth_config(self, grant_type: str = "client_credentials", issuer: str = "", client_id: str = "", client_secret: str = "", token_url: str = "", scopes: str = "") -> None:
        """Fill OAuth configuration fields.

        Args:
            grant_type: OAuth grant type (authorization_code, client_credentials, password)
            issuer: OAuth issuer URL
            client_id: OAuth client ID
            client_secret: OAuth client secret
            token_url: OAuth token URL
            scopes: Space-separated OAuth scopes
        """
        self.set_auth_type("oauth")
        self.wait_for_visible(self.auth_oauth_fields)

        self.oauth_grant_type_select.select_option(grant_type)

        if issuer:
            self.fill_locator(self.oauth_issuer_input, issuer)

        if client_id:
            self.fill_locator(self.oauth_client_id_input, client_id)

        if client_secret:
            self.fill_locator(self.oauth_client_secret_input, client_secret)

        if token_url:
            self.fill_locator(self.oauth_token_url_input, token_url)

        if scopes:
            self.fill_locator(self.oauth_scopes_input, scopes)

    def submit_agent_form(self) -> None:
        """Submit the add agent form."""
        self.click_locator(self.add_agent_btn)

    def get_agent_row(self, agent_index: int) -> Locator:
        """Get a specific agent row by index.

        Args:
            agent_index: Index of the agent row

        Returns:
            Locator for the agent row
        """
        return self.agent_rows.nth(agent_index)

    def agent_exists(self, agent_name: str) -> bool:
        """Check if an agent with the given name exists.

        Args:
            agent_name: The name of the agent to check

        Returns:
            True if agent exists, False otherwise
        """
        return self.page.locator(f"text={agent_name}").is_visible()

    def wait_for_agent_visible(self, agent_name: str, timeout: int = 30000) -> None:
        """Wait for an agent to be visible in the list.

        Args:
            agent_name: The name of the agent
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={agent_name}", timeout=timeout)
        expect(self.page.locator(f"text={agent_name}")).to_be_visible()

    def search_agents(self, query: str) -> None:
        """Search for agents using the search input.

        Args:
            query: Search query
        """
        self.fill_locator(self.agents_search_input, query)
        self.page.wait_for_timeout(500)  # Wait for search to filter

    def clear_search(self) -> None:
        """Clear the search input by clicking the clear button."""
        self.click_locator(self.agents_clear_search_btn)
        self.page.wait_for_timeout(500)  # Wait for search to clear
