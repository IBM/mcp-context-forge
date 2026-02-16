# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/gateways_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Gateways page object for MCP Server & Federated Gateway management.
"""

# Standard
import logging

# Third-Party
from playwright.sync_api import expect, Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage

logger = logging.getLogger(__name__)


class GatewaysPage(BasePage):
    """Page object for MCP Servers & Federated Gateways (MCP Registry) management.

    This page manages external MCP Servers (SSE/HTTP) registration to retrieve
    their tools/resources/prompts.
    """

    # ==================== Panel Elements ====================

    @property
    def gateways_panel(self) -> Locator:
        """Gateways panel container."""
        return self.page.locator("#gateways-panel")

    @property
    def panel_title(self) -> Locator:
        """Panel title 'MCP Servers & Federated Gateways'."""
        return self.gateways_panel.locator("h2:has-text('MCP Servers & Federated Gateways')")

    # ==================== Search and Filter Elements ====================

    @property
    def search_input(self) -> Locator:
        """Gateway search input."""
        return self.page.locator("#gateways-search-input")

    @property
    def clear_search_btn(self) -> Locator:
        """Clear search button."""
        return self.page.locator("#gateways-clear-search")

    @property
    def show_inactive_checkbox(self) -> Locator:
        """Show inactive gateways checkbox."""
        return self.page.locator("#show-inactive-gateways")

    @property
    def tag_filter_input(self) -> Locator:
        """Hidden tag filter input."""
        return self.page.locator("#gateways-tag-filter")

    # ==================== Gateway Table Elements ====================

    @property
    def gateways_table(self) -> Locator:
        """Gateways table."""
        return self.page.locator("#gateways-table")

    @property
    def gateways_table_body(self) -> Locator:
        """Gateways table body."""
        return self.page.locator("#gateways-table-body")

    @property
    def gateway_rows(self) -> Locator:
        """All gateway table rows."""
        return self.gateways_table_body.locator("tr")

    @property
    def loading_indicator(self) -> Locator:
        """HTMX loading indicator."""
        return self.page.locator("#gateways-loading")

    # ==================== Gateway Form Elements ====================

    @property
    def add_gateway_form(self) -> Locator:
        """Add gateway form."""
        return self.page.locator("#add-gateway-form")

    @property
    def gateway_name_input(self) -> Locator:
        """MCP Server name input field."""
        return self.add_gateway_form.locator("#mcp-server-name")

    @property
    def gateway_url_input(self) -> Locator:
        """MCP Server URL input field."""
        return self.add_gateway_form.locator("#mcp-server-url")

    @property
    def gateway_description_input(self) -> Locator:
        """Gateway description textarea."""
        return self.add_gateway_form.locator('[name="description"]')

    @property
    def gateway_tags_input(self) -> Locator:
        """Gateway tags input field."""
        return self.add_gateway_form.locator('[name="tags"]')

    @property
    def transport_select(self) -> Locator:
        """Transport type select (SSE/STREAMABLEHTTP)."""
        return self.add_gateway_form.locator('[name="transport"]')

    @property
    def auth_type_select(self) -> Locator:
        """Authentication type select field."""
        return self.add_gateway_form.locator("#auth-type-gw")

    @property
    def add_gateway_btn(self) -> Locator:
        """Add gateway submit button."""
        return self.add_gateway_form.locator('button[type="submit"]:has-text("Add Gateway")')

    # ==================== Visibility Radio Buttons ====================

    @property
    def visibility_public_radio(self) -> Locator:
        """Public visibility radio button."""
        return self.add_gateway_form.locator('[name="visibility"][value="public"]')

    @property
    def visibility_team_radio(self) -> Locator:
        """Team visibility radio button."""
        return self.add_gateway_form.locator('[name="visibility"][value="team"]')

    @property
    def visibility_private_radio(self) -> Locator:
        """Private visibility radio button."""
        return self.add_gateway_form.locator('[name="visibility"][value="private"]')

    # ==================== Authentication Fields ====================

    @property
    def auth_basic_fields(self) -> Locator:
        """Basic auth fields container."""
        return self.page.locator("#auth-basic-fields-gw")

    @property
    def auth_username_input(self) -> Locator:
        """Basic auth username input."""
        return self.add_gateway_form.locator('[name="auth_username"]')

    @property
    def auth_password_input(self) -> Locator:
        """Basic auth password input."""
        return self.page.locator("#auth-password-gw")

    @property
    def auth_bearer_fields(self) -> Locator:
        """Bearer token fields container."""
        return self.page.locator("#auth-bearer-fields-gw")

    @property
    def auth_token_input(self) -> Locator:
        """Bearer token input."""
        return self.page.locator("#auth-token-gw")

    @property
    def auth_headers_fields(self) -> Locator:
        """Custom headers fields container."""
        return self.page.locator("#auth-headers-fields-gw")

    @property
    def auth_query_param_fields(self) -> Locator:
        """Query parameter auth fields container."""
        return self.page.locator("#auth-query_param-fields-gw")

    @property
    def auth_query_param_key_input(self) -> Locator:
        """Query parameter key input."""
        return self.add_gateway_form.locator('[name="auth_query_param_key"]')

    @property
    def auth_query_param_value_input(self) -> Locator:
        """Query parameter value input."""
        return self.page.locator("#auth-query-param-value-gw")

    # ==================== OAuth Configuration Elements ====================

    @property
    def oauth_fields(self) -> Locator:
        """OAuth configuration fields container."""
        return self.page.locator("#auth-oauth-fields-gw")

    @property
    def oauth_grant_type_select(self) -> Locator:
        """OAuth grant type select."""
        return self.page.locator("#oauth-grant-type-gw")

    @property
    def oauth_issuer_input(self) -> Locator:
        """OAuth issuer URL input."""
        return self.add_gateway_form.locator('[name="oauth_issuer"]')

    @property
    def oauth_client_id_input(self) -> Locator:
        """OAuth client ID input."""
        return self.add_gateway_form.locator('[name="oauth_client_id"]')

    @property
    def oauth_client_secret_input(self) -> Locator:
        """OAuth client secret input."""
        return self.add_gateway_form.locator('[name="oauth_client_secret"]')

    @property
    def oauth_username_input(self) -> Locator:
        """OAuth username input (for password grant)."""
        return self.page.locator("#oauth-username-gw")

    @property
    def oauth_password_input(self) -> Locator:
        """OAuth password input (for password grant)."""
        return self.page.locator("#oauth-password-gw")

    @property
    def oauth_token_url_input(self) -> Locator:
        """OAuth token URL input."""
        return self.add_gateway_form.locator('[name="oauth_token_url"]')

    @property
    def oauth_authorization_url_input(self) -> Locator:
        """OAuth authorization URL input."""
        return self.add_gateway_form.locator('[name="oauth_authorization_url"]')

    @property
    def oauth_redirect_uri_input(self) -> Locator:
        """OAuth redirect URI input."""
        return self.add_gateway_form.locator('[name="oauth_redirect_uri"]')

    @property
    def oauth_scopes_input(self) -> Locator:
        """OAuth scopes input."""
        return self.add_gateway_form.locator('[name="oauth_scopes"]')

    @property
    def oauth_store_tokens_checkbox(self) -> Locator:
        """OAuth store tokens checkbox."""
        return self.add_gateway_form.locator('[name="oauth_store_tokens"]')

    @property
    def oauth_auto_refresh_checkbox(self) -> Locator:
        """OAuth auto refresh checkbox."""
        return self.add_gateway_form.locator('[name="oauth_auto_refresh"]')

    # ==================== Additional Form Elements ====================

    @property
    def one_time_auth_checkbox(self) -> Locator:
        """One-time authentication checkbox."""
        return self.page.locator("#single-use-auth-gw")

    @property
    def passthrough_headers_input(self) -> Locator:
        """Passthrough headers input."""
        return self.add_gateway_form.locator('[name="passthrough_headers"]')

    @property
    def ca_certificate_upload_input(self) -> Locator:
        """CA certificate file upload input."""
        return self.page.locator("#upload-ca-certificate")

    @property
    def ca_certificate_drop_zone(self) -> Locator:
        """CA certificate drag-and-drop zone."""
        return self.page.locator("#ca-certificate-upload-drop-zone")

    @property
    def status_message(self) -> Locator:
        """Status message display area."""
        return self.page.locator("#status-gateways")

    # ==================== Pagination Elements ====================

    @property
    def pagination_controls(self) -> Locator:
        """Pagination controls container."""
        return self.page.locator("#gateways-pagination-controls")

    # ==================== High-Level Navigation Methods ====================

    def navigate_to_gateways_tab(self) -> None:
        """Navigate to Gateways tab and wait for panel to be visible."""
        self.sidebar.click_gateways_tab()

    # ==================== High-Level Gateway Operations ====================

    def wait_for_gateways_table_loaded(self, timeout: int = 30000) -> None:
        """Wait for gateways table to be loaded and ready.

        Handles the Alpine.js + HTMX loading sequence where x-init sets
        the hx-get attribute before HTMX fires the load trigger and
        swaps in the table content via outerHTML.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                self.page.wait_for_selector("#gateways-panel:not(.hidden)", timeout=timeout)
                self.wait_for_attached(self.gateways_table_body, timeout=timeout)
                return
            except (AssertionError, PlaywrightTimeoutError) as exc:
                last_error = exc
                if attempt == 2:
                    break
                # Alpine.js x-init / HTMX load race: reload + re-open tab.
                self.page.reload(wait_until="domcontentloaded")
                self.navigate_to_gateways_tab()

        if last_error:
            raise last_error

    def create_gateway(self, gateway_data: dict) -> None:
        """Create a new MCP Server gateway by filling and submitting the form.

        Args:
            gateway_data: Dictionary containing gateway configuration with keys:
                - name: MCP Server name (required)
                - url: MCP Server URL (required)
                - description: Gateway description (optional)
                - tags: Comma-separated tags (optional)
                - transport: Transport type - "SSE" or "STREAMABLEHTTP" (default: "SSE")
                - visibility: Visibility setting - "public", "team", or "private" (default: "public")
                - auth_type: Authentication type (optional)
        """
        self.fill_locator(self.gateway_name_input, gateway_data["name"])
        self.fill_locator(self.gateway_url_input, gateway_data["url"])

        if gateway_data.get("description"):
            self.fill_locator(self.gateway_description_input, gateway_data["description"])
        if gateway_data.get("tags"):
            self.fill_locator(self.gateway_tags_input, gateway_data["tags"])

        # Set transport type
        transport = gateway_data.get("transport", "SSE")
        self.transport_select.select_option(transport)

        # Set visibility
        visibility = gateway_data.get("visibility", "public")
        if visibility == "team":
            self.click_locator(self.visibility_team_radio)
        elif visibility == "private":
            self.click_locator(self.visibility_private_radio)
        else:
            self.click_locator(self.visibility_public_radio)

        # Set auth type if provided
        if gateway_data.get("auth_type"):
            self.auth_type_select.select_option(gateway_data["auth_type"])

        self.click_locator(self.add_gateway_btn)

    def fill_gateway_form(self, name: str, url: str, description: str = "", tags: str = "", transport: str = "SSE") -> None:
        """Fill the add gateway form with provided data (without submitting).

        Args:
            name: MCP Server name
            url: MCP Server URL
            description: Gateway description (optional)
            tags: Comma-separated tags (optional)
            transport: Transport type (default: "SSE")
        """
        self.fill_locator(self.gateway_name_input, name)
        self.fill_locator(self.gateway_url_input, url)
        if description:
            self.fill_locator(self.gateway_description_input, description)
        if tags:
            self.fill_locator(self.gateway_tags_input, tags)
        self.transport_select.select_option(transport)

    def submit_gateway_form(self) -> None:
        """Submit the add gateway form."""
        self.click_locator(self.add_gateway_btn)

    def search_gateways(self, query: str) -> None:
        """Search for gateways using the search input.

        Search is server-side via HTMX with a debounce. Avoid Playwright
        ``networkidle`` because the admin UI can keep long-lived requests open.
        Wait for table/indicator state instead.

        Args:
            query: Search query string
        """
        if query == "":
            self.clear_search()
            return

        # Searches are debounced in admin.js (250ms) and search inputs are
        # occasionally re-initialized on tab switches (cloned/replaced). That
        # can create a short window where filling doesn't trigger a request.
        self.search_input.fill(query)

        try:
            self.page.wait_for_selector("#gateways-loading.htmx-request", timeout=5000)
        except PlaywrightTimeoutError:
            # Fallback: explicitly trigger the server-side reload.
            self.page.evaluate(
                "(q) => { const el = document.getElementById('gateways-search-input'); if (el) { el.value = q; } if (window.loadSearchablePanel) { window.loadSearchablePanel('gateways'); } }",
                query,
            )
            try:
                self.page.wait_for_selector("#gateways-loading.htmx-request", timeout=5000)
            except PlaywrightTimeoutError:
                pass

        self.page.wait_for_function(
            "() => !document.querySelector('#gateways-loading.htmx-request')",
            timeout=15000,
        )
        try:
            self.page.wait_for_selector(
                "#gateways-table-body",
                state="attached",
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            # Recovery path: if the partial response did not restore the table
            # structure, hard-reload and reopen gateways.
            self.page.reload(wait_until="domcontentloaded")
            self.navigate_to_gateways_tab()
            self.wait_for_gateways_table_loaded()
            return

        # In some environments the clear action can leave the table in a stale
        # empty state (e.g., after a zero-result search). Recover by reloading
        # and re-opening the gateways tab so subsequent assertions see the
        # canonical gateway list.
        if self.get_gateway_count() == 0:
            self.page.reload(wait_until="domcontentloaded")
            self.navigate_to_gateways_tab()
            self.wait_for_gateways_table_loaded()

    def clear_search(self) -> None:
        """Clear the gateway search.

        Triggers an HTMX reload of the gateways table, then waits for
        table/indicator settling.
        """
        request_seen = False
        try:
            with self.page.expect_response(
                lambda response: "/admin/gateways/partial" in response.url and response.request.method == "GET",
                timeout=5000,
            ):
                self.click_locator(self.clear_search_btn)
            request_seen = True
        except PlaywrightTimeoutError:
            pass

        if not request_seen:
            # Fallback: invoke the same clear function the button uses and
            # explicitly wait for the partial reload request.
            try:
                with self.page.expect_response(
                    lambda response: "/admin/gateways/partial" in response.url and response.request.method == "GET",
                    timeout=5000,
                ):
                    self.page.evaluate("window.clearSearch && window.clearSearch('gateways')")
                request_seen = True
            except PlaywrightTimeoutError:
                # Last-resort best effort: force a reload call even if request
                # observation missed due timing.
                self.page.evaluate(
                    "() => { const el = document.getElementById('gateways-search-input'); if (el) { el.value = ''; } if (window.loadSearchablePanel) { window.loadSearchablePanel('gateways'); } }",
                )

        self.page.wait_for_function(
            "() => !document.querySelector('#gateways-loading.htmx-request')",
            timeout=15000,
        )
        self.page.wait_for_selector("#gateways-table-body", state="attached", timeout=15000)

    def toggle_show_inactive(self, show: bool = True) -> None:
        """Toggle the show inactive gateways checkbox.

        Args:
            show: True to show inactive gateways, False to hide them
        """
        is_checked = self.show_inactive_checkbox.is_checked()
        if (show and not is_checked) or (not show and is_checked):
            self.click_locator(self.show_inactive_checkbox)

    def get_gateway_row(self, gateway_index: int) -> Locator:
        """Get a specific gateway row by index.

        Args:
            gateway_index: Index of the gateway row

        Returns:
            Locator for the gateway row
        """
        return self.gateway_rows.nth(gateway_index)

    def get_gateway_row_by_name(self, gateway_name: str) -> Locator:
        """Get a gateway row by its name.

        Args:
            gateway_name: Name of the gateway

        Returns:
            Locator for the gateway row
        """
        return self.gateways_table_body.locator(f'tr:has-text("{gateway_name}")')

    def gateway_exists(self, gateway_name: str) -> bool:
        """Check if a gateway with the given name exists in the table.

        Args:
            gateway_name: The name of the gateway to check

        Returns:
            True if gateway exists, False otherwise
        """
        # Use more specific selector to avoid strict mode violations
        return self.gateways_table_body.locator(f'tr:has-text("{gateway_name}")').count() > 0

    def get_gateway_count(self) -> int:
        """Get number of gateways displayed.

        Returns:
            Number of visible gateway rows
        """
        self.page.wait_for_selector("#gateways-table-body", state="attached")
        # Use more specific selector to count only actual gateway rows (not pagination or other elements)
        return self.page.locator('#gateways-table-body tr[id*="gateway-row"]').count()

    # ==================== Gateway Row Actions ====================

    def click_test_button(self, gateway_index: int = 0) -> None:
        """Click the Test button for a gateway.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        test_btn = gateway_row.locator('button:has-text("Test")')
        self.click_locator(test_btn)

    def click_view_button(self, gateway_index: int = 0) -> None:
        """Click the View button for a gateway.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        view_btn = gateway_row.locator('button:has-text("View")')
        self.click_locator(view_btn)

    def click_edit_button(self, gateway_index: int = 0) -> None:
        """Click the Edit button for a gateway.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        edit_btn = gateway_row.locator('button:has-text("Edit")')
        self.click_locator(edit_btn)

    def click_deactivate_button(self, gateway_index: int = 0) -> None:
        """Click the Deactivate button for a gateway.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        deactivate_btn = gateway_row.locator('button:has-text("Deactivate")')
        self.click_locator(deactivate_btn)

    def click_activate_button(self, gateway_index: int = 0) -> None:
        """Click the Activate button for a gateway.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        activate_btn = gateway_row.locator('button:has-text("Activate")')
        self.click_locator(activate_btn)

    def _click_delete_and_wait(self, delete_btn, confirm: bool = True) -> None:
        """Click a delete button, handle both confirmation dialogs, and wait for navigation.

        handleDeleteSubmit shows TWO confirm() dialogs (delete + purge metrics).
        form.submit() triggers a full page navigation (POST → 303 redirect).
        We must use expect_navigation to detect the new page load, since
        wait_for_load_state("domcontentloaded") returns immediately for the
        already-loaded current page.

        Args:
            delete_btn: Locator for the delete button to click
            confirm: Whether to accept or dismiss the dialogs
        """

        def _handle_dialog(dialog):
            if confirm:
                dialog.accept()
            else:
                dialog.dismiss()

        self.page.on("dialog", _handle_dialog)

        try:
            if confirm:
                with self.page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    delete_btn.click(force=True)
            else:
                delete_btn.click(force=True)
                self.page.wait_for_timeout(1000)
        finally:
            self.page.remove_listener("dialog", _handle_dialog)

    def delete_gateway(self, gateway_index: int = 0, confirm: bool = True) -> None:
        """Delete a gateway with optional confirmation.

        Args:
            gateway_index: Index of the gateway row (default: 0 for first gateway)
            confirm: Whether to confirm the deletion dialog (default: True)
        """
        gateway_row = self.gateway_rows.nth(gateway_index)

        # Scroll the row into view first
        gateway_row.scroll_into_view_if_needed()
        self.page.wait_for_timeout(500)

        # Find the delete button within the row's action column
        delete_btn = gateway_row.locator('form[action*="/delete"] button[type="submit"]:has-text("Delete")')
        self._click_delete_and_wait(delete_btn, confirm)

    def delete_gateway_by_name(self, gateway_name: str, confirm: bool = True) -> bool:
        """Delete a gateway by locating the matching row and clicking its delete button.

        Unlike delete_gateway(index), this method targets the specific row by name,
        avoiding the issue where client-side search filtering hides rows via CSS
        but gateway_rows.nth(0) still returns the first DOM row (possibly hidden).

        Args:
            gateway_name: Name of the gateway to delete
            confirm: Whether to confirm the deletion dialog (default: True)

        Returns:
            True if gateway was found and deleted, False if not found
        """
        # Check if gateway exists
        if not self.gateway_exists(gateway_name):
            return False

        # Find the specific row by name and click its delete button
        gateway_row = self.get_gateway_row_by_name(gateway_name)
        gateway_row.first.scroll_into_view_if_needed()
        self.page.wait_for_timeout(500)

        delete_btn = gateway_row.first.locator('form[action*="/delete"] button[type="submit"]:has-text("Delete")')
        self._click_delete_and_wait(delete_btn, confirm)

        return True

    def delete_gateway_by_url(self, gateway_url: str, confirm: bool = True) -> bool:
        """Delete ALL gateways with the specified URL.

        Since the system prevents duplicate URLs, this method will delete all
        gateways that match the URL (there might be multiple from failed test runs).

        Args:
            gateway_url: URL of the gateway(s) to delete
            confirm: Whether to confirm the deletion dialog (default: True)

        Returns:
            True if at least one gateway was found and deleted, False if none found
        """
        deleted_any = False

        # Keep deleting until no more gateways with this URL exist
        while True:
            # Search for the gateway by URL
            self.search_gateways(gateway_url)
            self.page.wait_for_timeout(500)

            # Check if any gateway with this URL exists
            gateway_row = self.gateways_table_body.locator(f'tr:has-text("{gateway_url}")')
            if gateway_row.count() == 0:
                if not deleted_any:
                    logger.info("No gateway found with URL '%s' - nothing to delete", gateway_url)
                self.clear_search()
                return deleted_any

            # Get gateway name for logging
            try:
                gateway_name = gateway_row.first.locator("td").nth(2).text_content().strip()
            except Exception:
                gateway_name = "Unknown"

            # Get the delete button and use shared delete+navigation helper
            try:
                delete_btn = gateway_row.first.locator('form[action*="/delete"] button[type="submit"]:has-text("Delete")')
                self._click_delete_and_wait(delete_btn, confirm)

                logger.info("Deleted gateway '%s' with URL '%s'", gateway_name, gateway_url)
                deleted_any = True

                # Reload to see updated table
                self.page.reload()
                self.wait_for_gateways_table_loaded()
                self.page.wait_for_timeout(1000)

            except Exception as e:
                logger.warning("Could not delete gateway '%s' with URL '%s': %s", gateway_name, gateway_url, e)
                self.clear_search()
                return deleted_any

    # ==================== Authentication Configuration Methods ====================

    def configure_basic_auth(self, username: str, password: str) -> None:
        """Configure basic authentication.

        Args:
            username: Basic auth username
            password: Basic auth password
        """
        self.auth_type_select.select_option("basic")
        self.wait_for_visible(self.auth_basic_fields)
        self.fill_locator(self.auth_username_input, username)
        self.fill_locator(self.auth_password_input, password)

    def configure_bearer_auth(self, token: str) -> None:
        """Configure bearer token authentication.

        Args:
            token: Bearer token
        """
        self.auth_type_select.select_option("bearer")
        self.wait_for_visible(self.auth_bearer_fields)
        self.fill_locator(self.auth_token_input, token)

    def configure_query_param_auth(self, param_key: str, param_value: str) -> None:
        """Configure query parameter authentication.

        Args:
            param_key: Query parameter name
            param_value: Query parameter value (API key)
        """
        self.auth_type_select.select_option("query_param")
        self.wait_for_visible(self.auth_query_param_fields)
        self.fill_locator(self.auth_query_param_key_input, param_key)
        self.fill_locator(self.auth_query_param_value_input, param_value)

    def configure_oauth(
        self, grant_type: str, issuer: str, client_id: str = "", client_secret: str = "", scopes: str = "openid profile email", token_url: str = "", authorization_url: str = "", redirect_uri: str = ""
    ) -> None:
        """Configure OAuth 2.0 authentication.

        Args:
            grant_type: OAuth grant type - "authorization_code", "client_credentials", or "password"
            issuer: OAuth issuer URL (required)
            client_id: OAuth client ID (optional for DCR)
            client_secret: OAuth client secret (optional for DCR)
            scopes: Space-separated OAuth scopes (default: "openid profile email")
            token_url: OAuth token endpoint URL (optional)
            authorization_url: OAuth authorization endpoint URL (optional, for authorization_code)
            redirect_uri: OAuth redirect URI (optional, for authorization_code)
        """
        self.auth_type_select.select_option("oauth")
        self.wait_for_visible(self.oauth_fields)

        self.oauth_grant_type_select.select_option(grant_type)
        self.fill_locator(self.oauth_issuer_input, issuer)

        if client_id:
            self.fill_locator(self.oauth_client_id_input, client_id)
        if client_secret:
            self.fill_locator(self.oauth_client_secret_input, client_secret)
        if scopes:
            self.fill_locator(self.oauth_scopes_input, scopes)
        if token_url:
            self.fill_locator(self.oauth_token_url_input, token_url)
        if authorization_url:
            self.fill_locator(self.oauth_authorization_url_input, authorization_url)
        if redirect_uri:
            self.fill_locator(self.oauth_redirect_uri_input, redirect_uri)

    def toggle_one_time_auth(self, enable: bool = True) -> None:
        """Toggle one-time authentication checkbox.

        Args:
            enable: True to enable one-time auth, False to disable
        """
        is_checked = self.one_time_auth_checkbox.is_checked()
        if (enable and not is_checked) or (not enable and is_checked):
            self.click_locator(self.one_time_auth_checkbox)

    # ==================== Verification Methods ====================

    def wait_for_gateway_visible(self, gateway_name: str, timeout: int = 30000) -> None:
        """Wait for a gateway to be visible in the table.

        Args:
            gateway_name: The name of the gateway
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f"text={gateway_name}", timeout=timeout)
        expect(self.page.locator(f"text={gateway_name}")).to_be_visible()

    def wait_for_gateway_hidden(self, gateway_name: str) -> None:
        """Wait for a gateway to be hidden from the table.

        Args:
            gateway_name: The name of the gateway
        """
        expect(self.page.locator(f"text={gateway_name}")).to_be_hidden()

    def verify_gateway_status(self, gateway_index: int, expected_status: str) -> None:
        """Verify the status of a gateway.

        Args:
            gateway_index: Index of the gateway row
            expected_status: Expected status text (e.g., "Active", "Inactive")
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        status_badge = gateway_row.locator(f'span:has-text("{expected_status}")')
        expect(status_badge).to_be_visible()

    def verify_gateway_visibility(self, gateway_index: int, expected_visibility: str) -> None:
        """Verify the visibility setting of a gateway.

        Args:
            gateway_index: Index of the gateway row
            expected_visibility: Expected visibility (e.g., "🌍 Public", "👥 Team", "🔒 Private")
        """
        gateway_row = self.gateway_rows.nth(gateway_index)
        visibility_badge = gateway_row.locator(f'span:has-text("{expected_visibility}")')
        expect(visibility_badge).to_be_visible()
