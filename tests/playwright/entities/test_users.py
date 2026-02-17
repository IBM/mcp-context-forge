# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_users.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Marek Dano

CRUD tests for Users entity in MCP Gateway Admin UI.
"""

# Third-Party
import pytest

# Local
from ..pages.admin_utils import cleanup_user
from ..pages.users_page import UsersPage


def _create_user_and_navigate(users_page: UsersPage, test_user_data: dict) -> None:
    """Helper: create a user via the UI form and reload to see the change.

    The HTMX in-place refresh does not update the user list reliably,
    so we wait for any pending JS activity, then do a full page reload
    and re-navigate to the users tab.
    """
    users_page.navigate_to_users_tab()
    users_page.wait_for_visible(users_page.create_user_form, timeout=15000)

    with users_page.page.expect_response(
        lambda response: "/admin/users" in response.url
        and response.request.method == "POST"
        and "/partial" not in response.url
    ) as response_info:
        users_page.create_user(
            email=test_user_data["email"],
            full_name=test_user_data["full_name"],
            password=test_user_data["password"],
        )
    response = response_info.value
    assert response.status < 400, f"User creation failed with status {response.status}"

    # Reload the page to pick up the newly created user
    users_page.reload_and_navigate_to_users()

    # Verify user now appears in the list
    users_page.wait_for_user_visible(test_user_data["email"])


@pytest.mark.ui
@pytest.mark.crud
class TestUsersCRUD:
    """CRUD tests for Users entity via the admin UI."""

    def test_create_user(self, users_page: UsersPage, test_user_data):
        """Test creating a new user via the admin UI form."""
        _create_user_and_navigate(users_page, test_user_data)
        assert users_page.user_exists_in_list(test_user_data["email"])

        # Cleanup
        cleanup_user(users_page.page, test_user_data["email"])

    def test_edit_user(self, users_page: UsersPage, test_user_data):
        """Test editing a user's full name via the edit modal."""
        _create_user_and_navigate(users_page, test_user_data)

        # Edit user
        updated_name = f"Updated {test_user_data['full_name']}"
        users_page.click_edit_button(test_user_data["email"])

        with users_page.page.expect_response(
            lambda response: "/update" in response.url
            and response.request.method == "POST"
        ) as response_info:
            users_page.submit_edit_form(full_name=updated_name)
        response = response_info.value
        assert response.status < 400, f"User edit failed with status {response.status}"

        # Reload the page to pick up the edit
        users_page.reload_and_navigate_to_users()

        # Verify the updated name appears in the user card
        card = users_page.find_user_card(test_user_data["email"])
        assert updated_name in card.text_content()

        # Cleanup
        cleanup_user(users_page.page, test_user_data["email"])

    def test_delete_user(self, users_page: UsersPage, test_user_data):
        """Test deleting a user via the Delete button (with confirm dialog)."""
        _create_user_and_navigate(users_page, test_user_data)

        # Delete user (accepts hx-confirm dialog)
        with users_page.page.expect_response(
            lambda response: "/admin/users" in response.url
            and response.request.method == "DELETE"
        ) as response_info:
            users_page.click_delete(test_user_data["email"])
        response = response_info.value
        assert response.status < 400, f"User deletion failed with status {response.status}"

        # The delete uses hx-swap="outerHTML" on closest .user-card,
        # so the card is replaced in-place.
        users_page.page.wait_for_timeout(1000)
        assert not users_page.user_exists_in_list(test_user_data["email"])

    def test_deactivate_user(self, users_page: UsersPage, test_user_data):
        """Test deactivating a user via the Deactivate button."""
        _create_user_and_navigate(users_page, test_user_data)

        # Deactivate user (in-place HTMX outerHTML swap on .user-card)
        with users_page.page.expect_response(
            lambda response: "/deactivate" in response.url
            and response.request.method == "POST"
        ) as response_info:
            users_page.click_deactivate(test_user_data["email"])
        response = response_info.value
        assert response.status < 400, f"User deactivation failed with status {response.status}"

        # Wait for card to update via HTMX outerHTML swap
        users_page.page.wait_for_timeout(1000)
        assert users_page.user_has_badge(test_user_data["email"], "Inactive")

        # Cleanup
        cleanup_user(users_page.page, test_user_data["email"])

    def test_activate_user(self, users_page: UsersPage, test_user_data):
        """Test activating a previously deactivated user."""
        _create_user_and_navigate(users_page, test_user_data)

        # Deactivate user first (in-place swap)
        with users_page.page.expect_response(
            lambda response: "/deactivate" in response.url
            and response.request.method == "POST"
        ):
            users_page.click_deactivate(test_user_data["email"])
        users_page.page.wait_for_timeout(1000)

        # Now activate user (in-place swap)
        with users_page.page.expect_response(
            lambda response: "/activate" in response.url
            and response.request.method == "POST"
        ) as response_info:
            users_page.click_activate(test_user_data["email"])
        response = response_info.value
        assert response.status < 400, f"User activation failed with status {response.status}"

        # Wait for card to update via HTMX outerHTML swap
        users_page.page.wait_for_timeout(1000)
        assert users_page.user_has_badge(test_user_data["email"], "Active")

        # Cleanup
        cleanup_user(users_page.page, test_user_data["email"])

    def test_force_password_change(self, users_page: UsersPage, test_user_data):
        """Test forcing a password change on a user."""
        _create_user_and_navigate(users_page, test_user_data)

        # Force password change (in-place swap)
        with users_page.page.expect_response(
            lambda response: "/force-password-change" in response.url
            and response.request.method == "POST"
        ) as response_info:
            users_page.click_force_password_change(test_user_data["email"])
        response = response_info.value
        assert response.status < 400, f"Force password change failed with status {response.status}"

        # Wait for card to update via HTMX outerHTML swap
        users_page.page.wait_for_timeout(1000)
        assert users_page.user_has_badge(test_user_data["email"], "Password Change Required")

        # Cleanup
        cleanup_user(users_page.page, test_user_data["email"])
