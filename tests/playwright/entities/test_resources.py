# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_resources.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Resources entity in MCP Gateway Admin UI.
"""

# Standard
import time

# Third-Party
from playwright.sync_api import expect, Page


def _find_resource(page: Page, resource_name: str, retries: int = 5):
    """Find a resource by name via the admin JSON endpoint."""
    for _ in range(retries):
        cache_bust = str(int(time.time() * 1000))
        response = page.request.get(f"/admin/resources?per_page=500&cache_bust={cache_bust}")
        if response.ok:
            payload = response.json()
            data = payload.get("data", [])
            for resource in data:
                if resource.get("name") == resource_name:
                    return resource
        time.sleep(0.5)
    return None


class TestResourcesCRUD:
    """CRUD tests for Resources entity."""

    def test_create_new_resource(self, admin_page: Page, test_resource_data):
        """Test creating a new resource."""
        # Go to Resources tab
        admin_page.click("#tab-resources")
        admin_page.wait_for_selector("#resources-panel:not(.hidden)")

        # Fill the form
        admin_page.fill('#add-resource-form [name="uri"]', test_resource_data["uri"])
        admin_page.fill('#add-resource-form [name="name"]', test_resource_data["name"])
        admin_page.fill('#add-resource-form [name="mimeType"]', test_resource_data["mimeType"])
        admin_page.fill('#add-resource-form [name="description"]', test_resource_data["description"])

        # Submit
        with admin_page.expect_response(lambda response: "/admin/resources" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-resource-form button[type="submit"]')
        response = response_info.value
        assert response.status < 400

        # Verify creation
        created_resource = _find_resource(admin_page, test_resource_data["name"])
        assert created_resource is not None

    def test_delete_resource(self, admin_page: Page, test_resource_data):
        """Test deleting a resource."""
        # Go to Resources tab
        admin_page.click("#tab-resources")
        admin_page.wait_for_selector("#resources-panel:not(.hidden)")

        # Create resource first
        admin_page.fill('#add-resource-form [name="uri"]', test_resource_data["uri"])
        admin_page.fill('#add-resource-form [name="name"]', test_resource_data["name"])
        admin_page.fill('#add-resource-form [name="mimeType"]', test_resource_data["mimeType"])
        admin_page.fill('#add-resource-form [name="description"]', test_resource_data["description"])
        
        with admin_page.expect_response(lambda response: "/admin/resources" in response.url and response.request.method == "POST") as response_info:
            admin_page.click('#add-resource-form button[type="submit"]')
        
        created_resource = _find_resource(admin_page, test_resource_data["name"])
        assert created_resource is not None

        # Delete
        delete_response = admin_page.request.post(
            f"/admin/resources/{created_resource['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400
        assert _find_resource(admin_page, test_resource_data["name"]) is None
