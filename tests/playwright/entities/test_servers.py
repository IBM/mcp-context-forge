# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_servers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Servers entity in MCP Gateway Admin UI.
"""

# Standard
import time

# Third-Party
from playwright.sync_api import expect, Page


def _find_server(page: Page, server_name: str, retries: int = 5):
    """Find a server by name via the admin JSON endpoint."""
    for _ in range(retries):
        cache_bust = str(int(time.time() * 1000))
        response = page.request.get(f"/admin/servers?per_page=500&cache_bust={cache_bust}")
        if response.ok:
            payload = response.json()
            data = payload.get("data", [])
            for server in data:
                if server.get("name") == server_name:
                    return server
        time.sleep(0.5)
    return None


class TestServersCRUD:
    """CRUD tests for Servers entity."""

    def test_create_new_server(self, admin_page: Page, test_server_data):
        """Test creating a new server."""
        # Go to Catalog/Servers tab
        admin_page.click('[data-testid="servers-tab"]')
        admin_page.wait_for_selector("#catalog-panel:not(.hidden)")

        # Fill the form
        admin_page.fill("#server-name", test_server_data["name"])
        admin_page.fill('input[name="icon"]', test_server_data["icon"])

        # Submit
        with admin_page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-server-form button[type="submit"]')
        response = response_info.value
        assert response.status < 400

        # Verify creation
        created_server = _find_server(admin_page, test_server_data["name"])
        assert created_server is not None

    def test_delete_server(self, admin_page: Page, test_server_data):
        """Test deleting a server."""
        # Go to Catalog/Servers tab
        admin_page.click('[data-testid="servers-tab"]')
        admin_page.wait_for_selector("#catalog-panel:not(.hidden)")

        # Create server first
        admin_page.fill("#server-name", test_server_data["name"])
        admin_page.fill('input[name="icon"]', test_server_data["icon"])
        
        with admin_page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-server-form button[type="submit"]')
        
        created_server = _find_server(admin_page, test_server_data["name"])
        assert created_server is not None

        # Delete
        delete_response = admin_page.request.post(
            f"/admin/servers/{created_server['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400
        assert _find_server(admin_page, test_server_data["name"]) is None
