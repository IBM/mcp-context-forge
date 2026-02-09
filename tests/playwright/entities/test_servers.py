# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/entities/test_servers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

CRUD tests for Servers entity in MCP Gateway Admin UI.
"""

# Local
from ..pages.servers_page import ServersPage
from ..pages.admin_utils import find_server, cleanup_server


class TestServersCRUD:
    """CRUD tests for Servers entity."""

    def test_create_new_server(self, servers_page: ServersPage, test_server_data):
        """Test creating a new server using ServersPage."""
        # Navigate to Servers tab
        servers_page.navigate_to_servers_tab()
        
        # Wait for the form to be visible
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Create server using the high-level method
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST") as response_info:
            servers_page.create_server(
                name=test_server_data["name"],
                icon=test_server_data["icon"]
            )
        response = response_info.value
        assert response.status < 400

        # Verify creation using helper
        created_server = find_server(servers_page.page, test_server_data["name"])
        assert created_server is not None

        # Cleanup: delete the created server for idempotency
        cleanup_server(servers_page.page, test_server_data["name"])

    def test_delete_server(self, servers_page: ServersPage, test_server_data):
        """Test deleting a server using ServersPage."""
        # Navigate to Servers tab
        servers_page.navigate_to_servers_tab()
        
        # Wait for the form to be visible
        servers_page.wait_for_visible(servers_page.add_server_form)

        # Create server first using the high-level method
        with servers_page.page.expect_response(lambda response: "/admin/servers" in response.url and response.request.method == "POST"):
            servers_page.create_server(
                name=test_server_data["name"],
                icon=test_server_data["icon"]
            )

        # Verify creation
        created_server = find_server(servers_page.page, test_server_data["name"])
        assert created_server is not None

        # Delete using helper
        delete_response = servers_page.page.request.post(
            f"/admin/servers/{created_server['id']}/delete",
            data="is_inactive_checked=false",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert delete_response.status < 400
        
        # Verify deletion
        assert find_server(servers_page.page, test_server_data["name"]) is None
