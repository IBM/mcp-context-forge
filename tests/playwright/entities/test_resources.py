# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_resources.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Resources entity in MCP Gateway Admin UI.
"""

# Local
from ..pages.admin_utils import delete_resource, find_resource
from ..pages.resources_page import ResourcesPage


class TestResourcesCRUD:
    """CRUD tests for Resources entity."""

    def test_create_new_resource(self, resources_page: ResourcesPage, test_resource_data):
        """Test creating a new resource."""
        # Navigate to Resources tab
        resources_page.navigate_to_resources_tab()

        # Create resource using high-level Page Object method
        with resources_page.page.expect_response(lambda response: "/admin/resources" in response.url and response.request.method == "POST") as response_info:
            resources_page.create_resource(uri=test_resource_data["uri"], name=test_resource_data["name"], mime_type=test_resource_data["mimeType"], description=test_resource_data["description"])
        response = response_info.value
        assert response.status < 400

        # Verify creation using utility function
        created_resource = find_resource(resources_page.page, test_resource_data["name"])
        assert created_resource is not None

        # Cleanup: delete the created resource for idempotency
        if created_resource:
            delete_resource(resources_page.page, created_resource["id"])

    def test_delete_resource(self, resources_page: ResourcesPage, test_resource_data):
        """Test deleting a resource."""
        # Navigate to Resources tab
        resources_page.navigate_to_resources_tab()

        # Create resource using high-level Page Object method
        with resources_page.page.expect_response(lambda response: "/admin/resources" in response.url and response.request.method == "POST"):
            resources_page.create_resource(uri=test_resource_data["uri"], name=test_resource_data["name"], mime_type=test_resource_data["mimeType"], description=test_resource_data["description"])

        # Verify creation
        created_resource = find_resource(resources_page.page, test_resource_data["name"])
        assert created_resource is not None

        # Delete using API helper
        assert delete_resource(resources_page.page, created_resource["id"])

        # Verify deletion
        assert find_resource(resources_page.page, test_resource_data["name"]) is None
