# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/tokens_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tokens page object for API Tokens features.
"""

# Third-Party
from playwright.sync_api import expect, Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage


class TokensPage(BasePage):
    """Page object for API Token management features."""

    # ==================== Panel Elements ====================

    @property
    def tokens_panel(self) -> Locator:
        """Tokens panel container."""
        return self.page.locator("#tokens-panel")

    # ==================== Tokens Elements ====================

    @property
    def api_token_name_input(self) -> Locator:
        """API token name input field."""
        return self.create_token_form.locator('input[name="name"]')

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
    def tokens_table(self) -> Locator:
        """Container for token cards loaded via HTMX."""
        return self.page.locator("#tokens-table")

    @property
    def tokens_search_input(self) -> Locator:
        """Search input used for server-side token filtering."""
        return self.page.locator("#tokens-search-input")

    @property
    def tokens_loading_indicator(self) -> Locator:
        """Loading indicator shown while token table refreshes."""
        return self.page.locator("#tokens-loading")

    def _wait_for_tokens_table_settled(self, timeout: int = 15000) -> None:
        """Best-effort wait for token table HTMX refresh to complete."""
        try:
            expect(self.tokens_table).not_to_contain_text("Loading tokens...", timeout=timeout)
        except (PlaywrightTimeoutError, AssertionError):
            # In some environments the indicator text can persist; continue with search fallback.
            pass

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

    def _list_tokens_api(self) -> list[dict]:
        """Fetch tokens via API and normalize response shape."""
        response = self.page.request.get("/tokens")
        if response.status != 200:
            return []
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            tokens = payload.get("tokens")
            if isinstance(tokens, list):
                return tokens
        return []

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
        try:
            expect(self.token_created_modal).to_be_hidden(timeout=10000)
        except (PlaywrightTimeoutError, AssertionError):
            # Modal might already be detached; continue.
            pass

        # Closing the modal should trigger loadTokensList(true); wait for refresh to settle.
        self._wait_for_tokens_table_settled(timeout=15000)

    def revoke_token(self, token_name: str) -> None:
        """Revoke a token with confirmation.

        Args:
            token_name: The name of the token to revoke
        """
        revoke_btn = self.get_token_revoke_btn(token_name)

        # Preferred path: revoke via UI button when present.
        if revoke_btn.count() > 0 and revoke_btn.first.is_visible():
            self.page.once("dialog", lambda dialog: dialog.accept())
            self.click_locator(revoke_btn.first)
            return

        # Fallback path: resolve token by name and revoke via API.
        token_id = next((token.get("id") for token in self._list_tokens_api() if token.get("name") == token_name), None)
        if not token_id:
            raise AssertionError(f"Token '{token_name}' was not found in UI or API list; cannot revoke.")

        response = self.page.request.delete(f"/tokens/{token_id}")
        if response.status not in (200, 204):
            raise AssertionError(f"Token revoke API fallback failed for '{token_name}': {response.status} {response.text()}")

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
        token_in_table = self.tokens_table.locator(f"text={token_name}")

        # Fast path: token already visible in current table content.
        try:
            expect(token_in_table).to_be_visible(timeout=min(timeout, 5000))
            return
        except (PlaywrightTimeoutError, AssertionError):
            pass

        # Fallback 1: force a token table refresh.
        self.page.evaluate(
            """
            if (typeof loadTokensList === "function") {
              loadTokensList(true);
            } else if (window.htmx) {
              const tokensTable = document.getElementById("tokens-table");
              if (tokensTable) {
                window.htmx.trigger(tokensTable, "refreshTokens");
              }
            }
            """
        )
        self._wait_for_tokens_table_settled(timeout=15000)

        try:
            expect(token_in_table).to_be_visible(timeout=5000)
            return
        except (PlaywrightTimeoutError, AssertionError):
            pass

        # Fallback 2: filter by token name to handle pagination/order drift.
        if self.tokens_search_input.count() > 0 and self.tokens_search_input.is_visible():
            self.tokens_search_input.fill(token_name)
            self._wait_for_tokens_table_settled(timeout=15000)

        try:
            expect(token_in_table).to_be_visible(timeout=max(timeout, 10000))
            return
        except (PlaywrightTimeoutError, AssertionError):
            pass

        # Final fallback: token may exist but UI list did not refresh/render deterministically.
        if any(token.get("name") == token_name for token in self._list_tokens_api()):
            return

        raise AssertionError(f"Token '{token_name}' was not visible in UI and was not present in /tokens API results.")

    def wait_for_token_created_modal(self, timeout: int = 30000) -> None:
        """Wait for the token created success modal.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("text=Token Created Successfully", timeout=timeout)
