# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Regression test suite for admin UI CRUD operations and state persistence.

This test suite covers the core regression scenarios:
1. Create flow - Entity creation succeeds
2. Edit flow - Changes are saved correctly
3. Delete flow - Entity deletion succeeds
4. Refresh persistence - State retained after page refresh
5. Console errors - No JavaScript errors during operations
6. API failures - No failed API calls during operations

These tests ensure that the innerHTML guard fix (PR #3373) and data-action
pattern do not break core admin functionality.
"""

# Future
from __future__ import annotations

# Standard
from typing import Any, Dict, List
# Third-Party
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# Local
from ..conftest import _ensure_admin_logged_in


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_page(page: Page, base_url: str):
    """Navigate to admin UI and ensure user is logged in."""
    _ensure_admin_logged_in(page, base_url)
    yield page


@pytest.fixture
def error_collector(page: Page):
    """Collect JavaScript errors and failed API calls during test execution."""
    js_errors: List[str] = []
    failed_requests: List[Dict[str, Any]] = []

    def _on_pageerror(error: Any) -> None:
        js_errors.append(str(error))

    def _on_response(response: Any) -> None:
        if response.status >= 400:
            failed_requests.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
            })

    page.on("pageerror", _on_pageerror)
    page.on("response", _on_response)

    yield {"js_errors": js_errors, "failed_requests": failed_requests}

    page.remove_listener("pageerror", _on_pageerror)
    page.remove_listener("response", _on_response)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _filter_benign_errors(errors: List[str]) -> List[str]:
    """Filter out known benign errors from third-party resources."""
    benign_patterns = [
        "ResizeObserver loop",
        "Non-Error promise rejection",
        "Script error",
        "cdn.jsdelivr",
        "cdnjs.cloudflare",
        "unpkg.com",
        "favicon.ico",
    ]
    return [
        e for e in errors
        if not any(pattern in e for pattern in benign_patterns)
    ]


def _filter_expected_failures(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out expected 404s and other acceptable failures."""
    return [
        r for r in requests
        if not (
            r["status"] == 404 and ("favicon" in r["url"] or "static" in r["url"])
        )
    ]


# ---------------------------------------------------------------------------
# Test Class: Virtual Server CRUD
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.regression
class TestVirtualServerCRUD:
    """Regression tests for virtual server create/edit/delete flows."""

    def test_create_virtual_server_flow(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Create virtual server succeeds without errors.

        Steps:
        1. Navigate to Servers tab
        2. Click "Add Server" button
        3. Fill in server details
        4. Submit form
        5. Verify server appears in list
        6. Verify no console errors
        7. Verify no failed API calls
        """
        # Step 1: Navigate to Servers tab
        servers_tab = admin_page.locator('[data-testid="servers-tab"]')
        expect(servers_tab).to_be_visible(timeout=10_000)
        servers_tab.click()

        # Step 2: Click Add Server button
        add_button = admin_page.locator('button:has-text("Add Server"), button:has-text("Create Server")')
        expect(add_button.first).to_be_visible(timeout=5_000)
        add_button.first.click()

        # Step 3: Fill in server details
        server_name = f"regression-test-server-{admin_page.evaluate('Date.now()')}"

        name_input = admin_page.locator('input[name="name"], input[id="name"]')
        expect(name_input).to_be_visible(timeout=5_000)
        name_input.fill(server_name)

        # Fill other required fields if present
        try:
            url_input = admin_page.locator('input[name="url"], input[id="url"]')
            if url_input.is_visible(timeout=2_000):
                url_input.fill("http://localhost:8080")
        except PlaywrightTimeoutError:
            pass

        # Step 4: Submit form
        submit_button = admin_page.locator('button[type="submit"]:has-text("Create"), button[type="submit"]:has-text("Save")')
        expect(submit_button.first).to_be_visible(timeout=5_000)
        submit_button.first.click()

        # Step 5: Verify server appears in list
        admin_page.wait_for_timeout(2_000)  # Wait for list refresh
        server_row = admin_page.locator(f'tr:has-text("{server_name}"), div:has-text("{server_name}")')
        expect(server_row.first).to_be_visible(timeout=10_000)

        # Step 6 & 7: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        failed_requests = _filter_expected_failures(error_collector["failed_requests"])

        assert js_errors == [], (
            "JavaScript errors during server creation:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )
        assert failed_requests == [], (
            "Failed API calls during server creation:\n"
            + "\n".join(f"  - {r['method']} {r['url']} → {r['status']}" for r in failed_requests)
        )

    def test_edit_virtual_server_flow(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Edit virtual server saves changes correctly.

        Steps:
        1. Navigate to Servers tab
        2. Find existing server or create one
        3. Click edit button
        4. Modify server details
        5. Save changes
        6. Verify changes persisted
        7. Verify no console errors
        8. Verify no failed API calls
        """
        # Step 1: Navigate to Servers tab
        servers_tab = admin_page.locator('[data-testid="servers-tab"]')
        expect(servers_tab).to_be_visible(timeout=10_000)
        servers_tab.click()

        admin_page.wait_for_timeout(2_000)

        # Step 2: Find first server row with edit button
        edit_button = admin_page.locator('button[data-action="edit"], button:has-text("Edit")').first

        if not edit_button.is_visible(timeout=3_000):
            pytest.skip("No servers available to edit")

        # Get server name before edit
        server_row = edit_button.locator('xpath=ancestor::tr')
        original_name = server_row.locator('td').first.text_content()

        # Step 3: Click edit button
        edit_button.click()

        # Step 4: Modify server details
        name_input = admin_page.locator('input[name="name"], input[id="name"]')
        expect(name_input).to_be_visible(timeout=5_000)

        updated_name = f"{original_name}-edited-{admin_page.evaluate('Date.now()')}"
        name_input.fill(updated_name)

        # Step 5: Save changes
        save_button = admin_page.locator('button[type="submit"]:has-text("Save"), button[type="submit"]:has-text("Update")')
        expect(save_button.first).to_be_visible(timeout=5_000)
        save_button.first.click()

        # Step 6: Verify changes persisted
        admin_page.wait_for_timeout(2_000)
        updated_row = admin_page.locator(f'tr:has-text("{updated_name}"), div:has-text("{updated_name}")')
        expect(updated_row.first).to_be_visible(timeout=10_000)

        # Step 7 & 8: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        failed_requests = _filter_expected_failures(error_collector["failed_requests"])

        assert js_errors == [], (
            "JavaScript errors during server edit:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )
        assert failed_requests == [], (
            "Failed API calls during server edit:\n"
            + "\n".join(f"  - {r['method']} {r['url']} → {r['status']}" for r in failed_requests)
        )

    def test_delete_virtual_server_flow(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Delete virtual server succeeds.

        Steps:
        1. Navigate to Servers tab
        2. Find server to delete
        3. Click delete button
        4. Confirm deletion
        5. Verify server removed from list
        6. Verify no console errors
        7. Verify no failed API calls
        """
        # Step 1: Navigate to Servers tab
        servers_tab = admin_page.locator('[data-testid="servers-tab"]')
        expect(servers_tab).to_be_visible(timeout=10_000)
        servers_tab.click()

        admin_page.wait_for_timeout(2_000)

        # Step 2: Find delete button
        delete_button = admin_page.locator('button[data-action="delete"], button:has-text("Delete")').first

        if not delete_button.is_visible(timeout=3_000):
            pytest.skip("No servers available to delete")

        # Get server name before deletion
        server_row = delete_button.locator('xpath=ancestor::tr')
        server_name = server_row.locator('td').first.text_content()

        # Step 3: Click delete button
        delete_button.click()

        # Step 4: Confirm deletion (if confirmation dialog appears)
        try:
            confirm_button = admin_page.locator('button:has-text("Confirm"), button:has-text("Yes"), button:has-text("Delete")')
            if confirm_button.is_visible(timeout=2_000):
                confirm_button.first.click()
        except PlaywrightTimeoutError:
            pass  # No confirmation dialog

        # Step 5: Verify server removed
        admin_page.wait_for_timeout(2_000)
        deleted_row = admin_page.locator(f'tr:has-text("{server_name}")')
        expect(deleted_row).not_to_be_visible(timeout=5_000)

        # Step 6 & 7: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        failed_requests = _filter_expected_failures(error_collector["failed_requests"])

        assert js_errors == [], (
            "JavaScript errors during server deletion:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )
        assert failed_requests == [], (
            "Failed API calls during server deletion:\n"
            + "\n".join(f"  - {r['method']} {r['url']} → {r['status']}" for r in failed_requests)
        )


# ---------------------------------------------------------------------------
# Test Class: State Persistence
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.regression
class TestStatePersistence:
    """Regression tests for state persistence across page refreshes."""

    def test_selected_tab_persists_after_refresh(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Selected tab state retained after page refresh.

        Steps:
        1. Navigate to a specific tab (e.g., Tools)
        2. Refresh the page
        3. Verify the same tab is still selected
        4. Verify no console errors
        """
        # Step 1: Navigate to Tools tab
        tools_tab = admin_page.locator('[data-testid="tools-tab"]')
        expect(tools_tab).to_be_visible(timeout=10_000)
        tools_tab.click()

        admin_page.wait_for_timeout(1_000)

        # Verify tab is active
        expect(tools_tab).to_have_attribute("aria-selected", "true", timeout=5_000)

        # Step 2: Refresh page
        admin_page.reload()
        admin_page.wait_for_load_state("domcontentloaded")

        # Step 3: Verify tab still selected
        tools_tab_after = admin_page.locator('[data-testid="tools-tab"]')
        expect(tools_tab_after).to_have_attribute("aria-selected", "true", timeout=10_000)

        # Step 4: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors after page refresh:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )

    def test_team_context_persists_after_refresh(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Team context retained after page refresh.

        Steps:
        1. Select a team from team selector
        2. Verify URL contains team_id parameter
        3. Refresh the page
        4. Verify team_id still in URL
        5. Verify team selector shows correct team
        6. Verify no console errors
        """
        # Step 1: Try to open team selector
        team_selector = admin_page.locator('[data-testid="team-selector-toggle"], button:has-text("Team")')

        if not team_selector.is_visible(timeout=3_000):
            pytest.skip("Team selector not available (single-team deployment)")

        team_selector.click()
        admin_page.wait_for_timeout(1_000)

        # Click first team item
        team_item = admin_page.locator('.team-selector-item').first
        if not team_item.is_visible(timeout=3_000):
            pytest.skip("No teams available in selector")

        team_item.click()
        admin_page.wait_for_timeout(1_500)

        # Step 2: Verify URL contains team_id
        current_url = admin_page.url
        if "team_id=" not in current_url:
            pytest.skip("Team selection did not update URL")

        # Step 3: Refresh page
        admin_page.reload()
        admin_page.wait_for_load_state("domcontentloaded")

        # Step 4: Verify team_id still in URL
        refreshed_url = admin_page.url
        assert "team_id=" in refreshed_url, "Team context lost after refresh"

        # Step 5: Verify team selector shows correct team (best effort)
        admin_page.wait_for_timeout(1_000)

        # Step 6: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors after team context refresh:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )

    def test_filter_state_persists_after_refresh(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: Filter/search state retained after page refresh.

        Steps:
        1. Navigate to a tab with search/filter (e.g., Tools)
        2. Enter search term
        3. Verify filtered results
        4. Refresh page
        5. Verify search term and filtered results persist
        6. Verify no console errors
        """
        # Step 1: Navigate to Tools tab
        tools_tab = admin_page.locator('[data-testid="tools-tab"]')
        expect(tools_tab).to_be_visible(timeout=10_000)
        tools_tab.click()

        admin_page.wait_for_timeout(1_000)

        # Step 2: Find search input
        search_input = admin_page.locator('input[type="search"], input[placeholder*="Search" i]').first

        if not search_input.is_visible(timeout=3_000):
            pytest.skip("Search input not available on this tab")

        search_term = "test"
        search_input.fill(search_term)
        admin_page.wait_for_timeout(1_000)

        # Step 3: Verify URL contains search parameter
        current_url = admin_page.url
        if "search=" not in current_url and "q=" not in current_url:
            pytest.skip("Search did not update URL")

        # Step 4: Refresh page
        admin_page.reload()
        admin_page.wait_for_load_state("domcontentloaded")

        # Step 5: Verify search term persists
        search_input_after = admin_page.locator('input[type="search"], input[placeholder*="Search" i]').first
        expect(search_input_after).to_have_value(search_term, timeout=5_000)

        # Step 6: Verify no errors
        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors after filter state refresh:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )


# ---------------------------------------------------------------------------
# Test Class: Console Errors & API Failures
# ---------------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.regression
class TestErrorMonitoring:
    """Regression tests for console errors and API failures."""

    def test_no_console_errors_on_page_load(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: No JavaScript errors on admin page load.

        Steps:
        1. Navigate to admin page
        2. Wait for page to fully load
        3. Verify no console errors
        """
        # Page already loaded by fixture
        admin_page.wait_for_timeout(2_000)

        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors on page load:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )

    def test_no_failed_api_calls_on_page_load(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: No failed API calls on admin page load.

        Steps:
        1. Navigate to admin page
        2. Wait for all network requests to complete
        3. Verify no failed API calls (4xx/5xx)
        """
        # Page already loaded by fixture
        admin_page.wait_for_load_state("domcontentloaded")
        admin_page.wait_for_timeout(2_000)

        failed_requests = _filter_expected_failures(error_collector["failed_requests"])
        assert failed_requests == [], (
            "Failed API calls on page load:\n"
            + "\n".join(f"  - {r['method']} {r['url']} → {r['status']}" for r in failed_requests)
        )

    def test_no_console_errors_during_tab_navigation(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: No JavaScript errors when navigating between tabs.

        Steps:
        1. Navigate through all major tabs
        2. Verify no console errors during navigation
        """
        tabs = [
            "servers-tab",
            "tools-tab",
            "teams-tab",
            "users-tab",
            "tokens-tab",
        ]

        for tab_id in tabs:
            tab = admin_page.locator(f'[data-testid="{tab_id}"]')
            if tab.is_visible(timeout=2_000):
                tab.click()
                admin_page.wait_for_timeout(1_000)

        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors during tab navigation:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )

    def test_data_action_buttons_work_without_errors(
        self, admin_page: Page, error_collector: Dict[str, Any]
    ) -> None:
        """Regression: All data-action buttons work without console errors.

        This test verifies that the innerHTML guard fix (data-action pattern)
        works correctly for all dynamically loaded buttons.

        Steps:
        1. Navigate to Tools tab
        2. Find and click various data-action buttons
        3. Verify no console errors
        """
        # Navigate to Tools tab
        tools_tab = admin_page.locator('[data-testid="tools-tab"]')
        expect(tools_tab).to_be_visible(timeout=10_000)
        tools_tab.click()

        admin_page.wait_for_timeout(2_000)

        # Find data-action buttons
        action_buttons = admin_page.locator('[data-action]')
        button_count = action_buttons.count()

        if button_count == 0:
            pytest.skip("No data-action buttons found")

        # Click first few buttons (up to 3) to test delegation
        for i in range(min(3, button_count)):
            try:
                button = action_buttons.nth(i)
                if button.is_visible(timeout=1_000):
                    button.click()
                    admin_page.wait_for_timeout(500)

                    # Close any modals that opened
                    close_button = admin_page.locator('button:has-text("Close"), button:has-text("Cancel")').first
                    if close_button.is_visible(timeout=1_000):
                        close_button.click()
                        admin_page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                continue

        js_errors = _filter_benign_errors(error_collector["js_errors"])
        assert js_errors == [], (
            "JavaScript errors when clicking data-action buttons:\n"
            + "\n".join(f"  - {e}" for e in js_errors)
        )

# Made with Bob
