# -*- coding: utf-8 -*-
"""Users page object for User Management features in the admin UI.

Location: ./tests/playwright/pages/users_page.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Marek Dano
"""

# Third-Party
from playwright.sync_api import Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage


class UsersPage(BasePage):
    """Page object for User Management features.

    This page manages the Users tab where admins can:
    - View and search users
    - Create new users
    - Edit user details (full name, admin status, password)
    - Activate/deactivate users
    - Force password change
    - Delete users
    """

    # ==================== Panel Elements ====================

    @property
    def users_panel(self) -> Locator:
        """Users panel container."""
        return self.page.locator("#users-panel")

    # ==================== Create User Form Elements ====================

    @property
    def create_user_form(self) -> Locator:
        """Create user form."""
        return self.page.locator("#create-user-form")

    @property
    def user_email_input(self) -> Locator:
        """Email input field."""
        return self.create_user_form.locator('input[name="email"]')

    @property
    def user_full_name_input(self) -> Locator:
        """Full name input field."""
        return self.create_user_form.locator('input[name="full_name"]')

    @property
    def user_password_input(self) -> Locator:
        """Password input field."""
        return self.create_user_form.locator("#new_user_password")

    @property
    def user_is_admin_checkbox(self) -> Locator:
        """Is admin checkbox."""
        return self.create_user_form.locator("#is_admin")

    @property
    def create_user_submit_btn(self) -> Locator:
        """Create user submit button."""
        return self.create_user_form.locator("#create_user_submit")

    @property
    def user_creation_messages(self) -> Locator:
        """User creation messages container."""
        return self.page.locator("#user-creation-messages")

    # ==================== Users List Elements ====================

    @property
    def users_list_container(self) -> Locator:
        """Users list container (loaded via HTMX)."""
        return self.page.locator("#users-list-container")

    @property
    def user_cards(self) -> Locator:
        """All user cards in the list."""
        return self.page.locator(".user-card")

    # ==================== Edit Modal Elements ====================

    @property
    def user_edit_modal(self) -> Locator:
        """User edit modal overlay."""
        return self.page.locator("#user-edit-modal")

    @property
    def user_edit_modal_content(self) -> Locator:
        """User edit modal content container."""
        return self.page.locator("#user-edit-modal-content")

    # ==================== Navigation ====================

    def navigate_to_users_tab(self) -> None:
        """Navigate to Users tab and wait for panel to be visible."""
        self.sidebar.click_users_tab()
        self.wait_for_users_loaded()

    # ==================== User Creation ====================

    def create_user(self, email: str, full_name: str, password: str, is_admin: bool = False) -> None:
        """Create a new user by filling and submitting the form.

        Args:
            email: User email address
            full_name: User full name
            password: User password
            is_admin: Whether to grant admin privileges
        """
        self.fill_locator(self.user_email_input, email)
        self.fill_locator(self.user_full_name_input, full_name)
        self.fill_locator(self.user_password_input, password)
        if is_admin:
            if not self.user_is_admin_checkbox.is_checked():
                self.click_locator(self.user_is_admin_checkbox)
        # Wait briefly for password validation JS to enable submit button
        self.page.wait_for_timeout(500)
        self.click_locator(self.create_user_submit_btn)

    # ==================== User List Operations ====================

    def wait_for_users_loaded(self, timeout: int = 30000) -> None:
        """Wait for the users list to load via HTMX.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("#users-panel:not(.hidden)", timeout=timeout)
        self.wait_for_attached(self.users_list_container, timeout=timeout)
        # Wait for HTMX loading to complete
        try:
            self.page.wait_for_function(
                "() => !document.querySelector('#users-loading.htmx-request')",
                timeout=timeout,
            )
        except PlaywrightTimeoutError:
            pass

    def find_user_card(self, email: str) -> Locator:
        """Locate a user card by email text.

        Args:
            email: User email to search for

        Returns:
            Locator for the user card containing the email
        """
        return self.page.locator(f".user-card:has-text('{email}')")

    def user_exists_in_list(self, email: str) -> bool:
        """Check if a user with the given email exists in the user list.

        Args:
            email: User email to check

        Returns:
            True if user is visible in the list
        """
        return self.find_user_card(email).count() > 0

    def wait_for_user_visible(self, email: str, timeout: int = 30000) -> None:
        """Wait for a user to appear in the list.

        Args:
            email: User email to wait for
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector(f".user-card:has-text('{email}')", timeout=timeout)

    def reload_and_navigate_to_users(self) -> None:
        """Reload the page so the users list is refreshed.

        The HTMX in-place refresh does not update the UI reliably, so
        we wait for any pending JS navigation, then do a full page
        reload and click the users tab to get a fresh user list.
        """
        self.page.wait_for_timeout(4000)
        self.page.wait_for_load_state("domcontentloaded")

        self.page.reload(wait_until="domcontentloaded")
        self.sidebar.click_users_tab()
        self.wait_for_users_loaded()

    def user_has_badge(self, email: str, badge_text: str) -> bool:
        """Check if a user card has a specific badge.

        Args:
            email: User email to check
            badge_text: Badge text to look for (e.g., "Active", "Inactive", "Admin")

        Returns:
            True if the badge is present on the user card
        """
        card = self.find_user_card(email)
        return card.get_by_text(badge_text, exact=True).count() > 0

    # ==================== User Card Actions ====================

    def click_edit_button(self, email: str) -> None:
        """Click the Edit button on a user card and wait for the modal.

        Args:
            email: User email to edit
        """
        card = self.find_user_card(email)
        card.locator("button:has-text('Edit')").click()
        # Wait for the modal to become visible and content to load
        self.page.wait_for_selector("#user-edit-modal:not(.hidden)", timeout=10000)
        self.page.wait_for_selector("#user-edit-modal-content form", timeout=10000)

    def submit_edit_form(self, full_name: str | None = None, password: str | None = None, confirm_password: str | None = None, is_admin: bool | None = None) -> None:
        """Fill and submit the user edit modal form.

        Args:
            full_name: New full name (None to leave unchanged)
            password: New password (None to leave unchanged)
            confirm_password: Password confirmation (None to leave unchanged)
            is_admin: Admin status (None to leave unchanged)
        """
        modal_content = self.user_edit_modal_content
        if full_name is not None:
            name_input = modal_content.locator('input[name="full_name"]')
            name_input.fill(full_name)
        if is_admin is not None:
            admin_checkbox = modal_content.locator('input[name="is_admin"]')
            is_checked = admin_checkbox.is_checked()
            if is_admin and not is_checked:
                admin_checkbox.click()
            elif not is_admin and is_checked:
                admin_checkbox.click()
        if password is not None:
            pwd_input = modal_content.locator('input[name="password"]')
            pwd_input.fill(password)
        if confirm_password is not None:
            confirm_input = modal_content.locator('input[name="confirm_password"]')
            confirm_input.fill(confirm_password)
        # Submit the form
        modal_content.locator('button[type="submit"]').click()

    def close_edit_modal(self) -> None:
        """Close the user edit modal."""
        self.page.evaluate("""
            const modal = document.getElementById('user-edit-modal');
            if (modal) {
                modal.style.display = 'none';
                modal.classList.add('hidden');
            }
        """)

    def _click_action_with_confirm(self, email: str, button_text: str) -> None:
        """Click an action button on a user card that triggers an hx-confirm dialog.

        Sets up a dialog handler to accept the native confirm() dialog
        before clicking the button.

        Args:
            email: User email to act on
            button_text: Button text to click (e.g., "Activate", "Deactivate", "Delete")
        """
        card = self.find_user_card(email)
        # Accept the native confirm dialog triggered by hx-confirm
        self.page.once("dialog", lambda dialog: dialog.accept())
        card.locator(f"button:has-text('{button_text}')").click()

    def click_activate(self, email: str) -> None:
        """Click the Activate button on a user card (accepts confirm dialog).

        Args:
            email: User email to activate
        """
        self._click_action_with_confirm(email, "Activate")

    def click_deactivate(self, email: str) -> None:
        """Click the Deactivate button on a user card (accepts confirm dialog).

        Args:
            email: User email to deactivate
        """
        self._click_action_with_confirm(email, "Deactivate")

    def click_delete(self, email: str) -> None:
        """Click the Delete button on a user card (accepts confirm dialog).

        Args:
            email: User email to delete
        """
        self._click_action_with_confirm(email, "Delete")

    def click_force_password_change(self, email: str) -> None:
        """Click the Force Password Change button on a user card (accepts confirm dialog).

        Args:
            email: User email to force password change
        """
        self._click_action_with_confirm(email, "Force Password Change")

    def click_unlock(self, email: str) -> None:
        """Click the Unlock button on a user card (accepts confirm dialog).

        Args:
            email: User email to unlock
        """
        self._click_action_with_confirm(email, "Unlock")
