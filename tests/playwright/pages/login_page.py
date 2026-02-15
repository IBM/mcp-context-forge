# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/login_page.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti, Manav Gupta

Login page object for authentication functionality.
"""

# Third-Party
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Local
from .base_page import BasePage


class LoginPage(BasePage):
    """Login page object with authentication-related locators and methods."""

    def __init__(self, page: Page, base_url: str):
        super().__init__(page)
        self.base_url = base_url
        self.login_url = f"{base_url}/admin/login"
        self.change_password_url = f"{base_url}/admin/change-password-required"

    # ==================== Locators ====================

    @property
    def email_input(self) -> Locator:
        """Email input field."""
        return self.page.locator('input[name="email"]')

    @property
    def password_input(self) -> Locator:
        """Password input field."""
        return self.page.locator('input[name="password"]')

    @property
    def submit_button(self) -> Locator:
        """Login form submit button."""
        return self.page.locator('button[type="submit"]')

    @property
    def error_message(self) -> Locator:
        """Error message element."""
        return self.page.locator("#error-message")

    # ==================== Change Password Form Locators ====================

    @property
    def current_password_input(self) -> Locator:
        """Current password input field (change password form)."""
        return self.page.locator('input[name="current_password"]')

    @property
    def new_password_input(self) -> Locator:
        """New password input field (change password form)."""
        return self.page.locator('input[name="new_password"]')

    @property
    def confirm_password_input(self) -> Locator:
        """Confirm password input field (change password form)."""
        return self.page.locator('input[name="confirm_password"]')

    # ==================== Navigation ====================

    def navigate(self):
        """Navigate to login page."""
        return self.page.goto(self.login_url)

    # ==================== Helper Methods ====================

    def is_login_form_available(self, timeout: int = 3000) -> bool:
        """Check if login form is available.

        Args:
            timeout: Timeout in milliseconds (default: 3000)

        Returns:
            True if login form is available, False otherwise
        """
        try:
            self.page.wait_for_selector('input[name="email"]', timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    def is_on_login_page(self) -> bool:
        """Check if currently on login page."""
        return "/admin/login" in self.page.url

    def is_on_change_password_page(self) -> bool:
        """Check if currently on change password page."""
        return "/admin/change-password-required" in self.page.url

    def has_invalid_credentials_error(self) -> bool:
        """Check if URL contains invalid credentials error."""
        return "error=invalid_credentials" in self.page.url

    # ==================== Actions ====================

    def fill_email(self, email: str) -> None:
        """Fill email input field.

        Args:
            email: Email address to fill
        """
        self.fill_locator(self.email_input, email)

    def fill_password(self, password: str) -> None:
        """Fill password input field.

        Args:
            password: Password to fill
        """
        self.fill_locator(self.password_input, password)

    def click_submit(self) -> None:
        """Click submit button."""
        previous_url = self.page.url
        self.click_locator(self.submit_button)
        self.page.wait_for_load_state("domcontentloaded")
        # Give extra time if URL hasn't changed
        if self.page.url == previous_url:
            self.page.wait_for_timeout(500)

    def submit_login(self, email: str, password: str) -> None:
        """Fill and submit login form.

        Args:
            email: Email address
            password: Password
        """
        self.fill_email(email)
        self.fill_password(password)
        self.click_submit()

    def submit_password_change(self, current_password: str, new_password: str) -> None:
        """Fill and submit password change form.

        Args:
            current_password: Current password
            new_password: New password
        """
        self.fill_locator(self.current_password_input, current_password)
        self.fill_locator(self.new_password_input, new_password)
        self.fill_locator(self.confirm_password_input, new_password)
        self.click_submit()

    # ==================== High-Level Login Flow ====================

    def login(self, email: str, password: str, new_password: str = None) -> bool:
        """Perform complete login flow with optional password change.

        Args:
            email: Email address
            password: Password
            new_password: New password if password change is required

        Returns:
            True if login successful, False otherwise
        """
        # Submit initial login
        self.submit_login(email, password)

        # Handle password change if required
        if self.is_on_change_password_page() and new_password:
            self.submit_password_change(password, new_password)
        # Handle case where password was already changed
        elif self.has_invalid_credentials_error() and new_password and new_password != password:
            self.submit_login(email, new_password)

        # Return success status
        return not self.has_invalid_credentials_error()
