# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/test_autocomplete.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Playwright E2E tests verifying autocomplete attributes on rendered password
inputs to prevent browser autofill on API key, secret, and token fields.
"""

# Standard
import re

# Third-Party
from playwright.sync_api import expect
import pytest

# Local
from .conftest import BASE_URL
from .pages.admin_page import AdminPage
from .pages.gateways_page import GatewaysPage
from .pages.login_page import LoginPage
from .pages.mcp_registry_page import MCPRegistryPage


@pytest.mark.ui
class TestAutocompleteAttributes:
    """Verify autocomplete attributes prevent browser autofill on sensitive fields."""

    # ---- Login form (unauthenticated) ----

    def test_login_form_has_correct_autocomplete(self, page, base_url):
        """Login form should have proper autocomplete for credential fields."""
        login_page = LoginPage(page, base_url)
        response = login_page.navigate()
        if response and response.status == 404:
            pytest.skip("Admin login page not available")
        if not login_page.is_login_form_available(timeout=5000):
            pytest.skip("Login form not present (auth may be disabled)")

        expect(login_page.password_input).to_have_attribute("autocomplete", "current-password")

    # ---- Gateway auth fields ----

    def test_gateway_basic_auth_password_has_autocomplete_off(self, gateways_page: GatewaysPage):
        """Gateway basic-auth password field should not trigger browser autofill."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.auth_type_select.select_option("basic")
        expect(gateways_page.auth_password_input).to_have_attribute("autocomplete", "off")

    def test_gateway_bearer_token_has_autocomplete_off(self, gateways_page: GatewaysPage):
        """Gateway bearer-token field should not trigger browser autofill."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.auth_type_select.select_option("bearer")
        expect(gateways_page.auth_token_input).to_have_attribute("autocomplete", "off")

    def test_gateway_oauth_client_secret_has_autocomplete_off(self, gateways_page: GatewaysPage):
        """Gateway OAuth client secret should not trigger browser autofill."""
        gateways_page.navigate_to_gateways_tab()
        gateways_page.auth_type_select.select_option("oauth")
        expect(gateways_page.oauth_client_secret_input).to_have_attribute("autocomplete", "off")

    # ---- User creation ----

    def test_user_creation_password_has_new_password(self, admin_page: AdminPage):
        """User creation password should use autocomplete=new-password for browser password generation."""
        admin_page.sidebar.click_users_tab()
        password_input = admin_page.page.locator("#new_user_password")
        expect(password_input).to_have_attribute("autocomplete", "new-password")

    # ---- LLM provider API key ----

    def test_llm_provider_api_key_has_autocomplete_off(self, admin_page: AdminPage):
        """LLM provider API key field should not trigger browser autofill."""
        admin_page.sidebar.click_tab_by_id("tab-llm-settings", "llm-settings-panel")
        api_key_input = admin_page.page.locator("#llm-provider-api-key")
        expect(api_key_input).to_have_attribute("autocomplete", "off")

    # ---- MCP Registry API key modal ----

    def test_mcp_registry_api_key_has_autocomplete_off(self, mcp_registry_page: MCPRegistryPage):
        """MCP Registry API key modal input should not trigger browser autofill."""
        mcp_registry_page.navigate_to_registry_tab()
        modal_api_key = mcp_registry_page.modal_api_key_input
        # The input exists in the DOM even when the modal is hidden; check its attribute
        expect(modal_api_key).to_have_attribute("autocomplete", "off")
