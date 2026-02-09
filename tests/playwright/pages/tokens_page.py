# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/tokens_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tokens page object for API Tokens features.
"""

# Third-Party
from playwright.sync_api import Page, Locator, expect

# Local
from .base_page import BasePage


class TokensPage(BasePage):
    """Page object for API Token management features."""

    def __init__(self, page: Page):
        super().__init__(page)

    # ==================== Panel Elements ====================

    @property
    def tokens_panel(self) -> Locator:
        """Tokens panel container."""
        return self.page.locator("#tokens-panel")

    # ==================== Tokens Elements ====================

    @property
    def api_token_name_input(self) -> Locator:
        """API token name input field."""
        # Look for the input with the "Token Name" label
        return self.page.locator('input[placeholder="Production API Access"]')

    @property
    def token_expiry_input(self) -> Locator:
        """Token expiry input field (number of days)."""
        return self.create_token_form.locator('input[name="expires_in_days"]')

    @property
    def create_token_form(self) -> Locator:
        """Create API token form."""
        return self.page.locator("#create-token-form")

    @property
    def create_token_submit_btn(self) -> Locator:
        """Submit button for create token form."""
        return self.create_token_form.locator('button[type="submit"]')

    @property
    def token_created_modal(self) -> Locator:
        """Token created success modal."""
        return self.page.locator("text=Token Created Successfully")

    @property
    def token_saved_btn(self) -> Locator:
        """Button to confirm token has been saved."""
        return self.page.locator('button:has-text("I\'ve Saved It")')

    def get_token_element(self, token_name: str) -> Locator:
        """Get the container element for a specific token.
        
        Args:
            token_name: The name of the token to find
            
        Returns:
            Locator for the token container
        """
        return self.page.locator(f"div:has-text('{token_name}')").first

    def get_token_revoke_btn(self, token_name: str) -> Locator:
        """Get the revoke button for a specific token.
        
        Args:
            token_name: The name of the token
            
        Returns:
            Locator for the revoke button
        """
        # Use data-token-name attribute for reliable selection
        return self.page.locator(f'button[data-token-name="{token_name}"]')

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_tokens_tab(self) -> None:
        """Navigate to Tokens tab and wait for panel to be visible."""
        self.sidebar.click_tokens_tab()

    # ==================== High-Level Token Operations ====================

    def create_token(self, token_name: str, expiry_days: int = None) -> None:
        """Create a new API token.
        
        Args:
            token_name: The name for the new token
            expiry_days: Optional number of days until expiry (default is 30)
        """
        # Click the input first to focus it, then clear and type
        token_input = self.api_token_name_input
        token_input.click()
        token_input.fill("")  # Clear any existing value
        token_input.type(token_name)  # Type character by character
        
        # Set expiry if provided
        if expiry_days is not None:
            expiry_input = self.token_expiry_input
            expiry_input.click()
            expiry_input.fill("")
            expiry_input.type(str(expiry_days))
        
        # Submit form (JavaScript will handle the submission)
        self.click_locator(self.create_token_submit_btn)

    def close_token_created_modal(self) -> None:
        """Close the token created success modal."""
        self.click_locator(self.token_saved_btn)

    def revoke_token(self, token_name: str) -> None:
        """Revoke a token with confirmation.
        
        Args:
            token_name: The name of the token to revoke
        """
        # Setup dialog listener for confirmation
        self.page.once("dialog", lambda dialog: dialog.accept())
        
        # Click revoke button
        self.click_locator(self.get_token_revoke_btn(token_name))

    def token_exists(self, token_name: str) -> bool:
        """Check if a token with the given name exists.
        
        Args:
            token_name: The name of the token to check
            
        Returns:
            True if token exists, False otherwise
        """
        return self.page.locator(f"text={token_name}").is_visible()

    def wait_for_token_visible(self, token_name: str, timeout: int = 30000) -> None:
        """Wait for a token to be visible in the list.
        
        Args:
            token_name: The name of the token
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={token_name}", timeout=timeout)
        expect(self.page.locator(f"text={token_name}")).to_be_visible()

    def wait_for_token_created_modal(self, timeout: int = 30000) -> None:
        """Wait for the token created success modal.
        
        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("text=Token Created Successfully", timeout=timeout)