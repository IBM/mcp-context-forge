# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/api_helpers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared API test helpers for Playwright and API-oriented test suites.
"""

# Future
from __future__ import annotations

# Standard
from typing import TYPE_CHECKING, Any

# Local
from tests.helpers.auth import make_auth_headers

if TYPE_CHECKING:
    # Third-Party
    from playwright.sync_api import APIRequestContext, Playwright


class ApiTestHelper:
    """Helper for creating common test entities through real API calls."""

    def __init__(self, api_context: "APIRequestContext"):
        self.api = api_context

    @staticmethod
    def new_context(
        playwright: "Playwright",
        base_url: str,
        token: str,
        *,
        accept: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> "APIRequestContext":
        """Create a Playwright API request context with Bearer auth."""
        return playwright.request.new_context(
            base_url=base_url,
            extra_http_headers=make_auth_headers(token, accept=accept, extra_headers=extra_headers),
        )

    def create_team(self, name: str, *, description: str = "test team", visibility: str = "private") -> dict[str, Any]:
        """Create a team and return the decoded JSON body."""
        response = self.api.post(
            "/teams",
            data={"name": name, "description": description, "visibility": visibility},
        )
        assert response.status in (200, 201), f"Failed to create team: {response.status} {response.text()}"
        return response.json()

    def create_server(
        self,
        name: str,
        *,
        visibility: str = "public",
        team_id: str | None = None,
        description: str = "test server",
        server: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a virtual server and return the decoded JSON body."""
        response = self.api.post(
            "/servers",
            data={
                "server": server or {"name": name, "description": description},
                "team_id": team_id,
                "visibility": visibility,
            },
        )
        assert response.status in (200, 201), f"Failed to create server: {response.status} {response.text()}"
        return response.json()

    def create_tool(
        self,
        name: str,
        url: str,
        *,
        description: str = "test tool",
        integration_type: str = "REST",
        request_type: str = "POST",
        team_id: str | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        """Create a tool and return the decoded JSON body.

        Args:
            name: Tool name
            url: Tool URL (required to avoid external dependencies in tests)
            description: Tool description
            integration_type: Integration type (REST, MCP, etc.)
            request_type: HTTP method for REST tools
            team_id: Optional team ID for team-scoped tools
            visibility: Optional visibility setting
        """
        payload: dict[str, Any] = {
            "tool": {
                "name": name,
                "url": url,
                "description": description,
                "integration_type": integration_type,
                "request_type": request_type,
            },
            "team_id": team_id,
        }
        if visibility is not None:
            payload["visibility"] = visibility
        response = self.api.post("/tools", data=payload)
        assert response.status in (200, 201), f"Failed to create tool: {response.status} {response.text()}"
        return response.json()

    def create_resource(
        self,
        uri: str,
        name: str,
        *,
        content: str = "test content",
        description: str = "test resource",
        mime_type: str = "text/plain",
        team_id: str | None = None,
        visibility: str | None = None,
    ) -> dict[str, Any]:
        """Create a resource and return the decoded JSON body."""
        payload: dict[str, Any] = {
            "resource": {
                "uri": uri,
                "name": name,
                "content": content,
                "description": description,
                "mime_type": mime_type,
            },
            "team_id": team_id,
        }
        if visibility is not None:
            payload["visibility"] = visibility
        response = self.api.post("/resources", data=payload)
        assert response.status in (200, 201), f"Failed to create resource: {response.status} {response.text()}"
        return response.json()

    def create_gateway(
        self,
        name: str,
        *,
        url: str = "http://example.com/sse",
        description: str = "test gateway",
        transport: str = "SSE",
        visibility: str = "public",
        team_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a gateway and return the decoded JSON body."""
        response = self.api.post(
            "/gateways",
            data={
                "name": name,
                "url": url,
                "description": description,
                "transport": transport,
                "visibility": visibility,
                "team_id": team_id,
            },
        )
        assert response.status in (200, 201), f"Failed to create gateway: {response.status} {response.text()}"
        return response.json()

    def delete_team(self, team_id: str) -> None:
        """Delete a team, best-effort."""
        self.api.delete(f"/teams/{team_id}")

    def delete_server(self, server_id: str) -> None:
        """Delete a server, best-effort."""
        self.api.delete(f"/servers/{server_id}")

    def delete_tool(self, tool_id: str) -> None:
        """Delete a tool, best-effort."""
        self.api.delete(f"/tools/{tool_id}")

    def delete_resource(self, resource_id: str) -> None:
        """Delete a resource, best-effort."""
        self.api.delete(f"/resources/{resource_id}")

    def delete_gateway(self, gateway_id: str) -> None:
        """Delete a gateway, best-effort."""
        self.api.delete(f"/gateways/{gateway_id}")
