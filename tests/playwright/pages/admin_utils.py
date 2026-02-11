# -*- coding: utf-8 -*-
"""Location: ./tests/playwright/pages/admin_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared utility functions for admin page interactions.
"""

# Standard
import logging

# Third-Party
from playwright.sync_api import Page

logger = logging.getLogger(__name__)


def _get_auth_headers(page: Page) -> dict:
    """Extract JWT token from browser cookies and return Authorization headers.

    The server rejects cookie-based authentication for programmatic API
    requests (page.request), requiring an Authorization header instead.
    This extracts the jwt_token cookie set during login and converts it
    to a Bearer token header.
    """
    cookies = page.context.cookies()
    jwt_cookie = next((c for c in cookies if c["name"] == "jwt_token"), None)
    if jwt_cookie:
        return {"Authorization": f"Bearer {jwt_cookie['value']}"}
    return {}


def find_entity_by_name(page: Page, endpoint: str, name: str, retries: int = 5):
    """Generic function to find any entity by name via admin API.

    Args:
        page: Playwright page object
        endpoint: API endpoint (e.g., "servers", "tools", "resources")
        name: Entity name to search for
        retries: Number of retry attempts

    Returns:
        Entity dict if found, None otherwise
    """
    headers = _get_auth_headers(page)
    for attempt in range(retries):
        cache_bust = str(attempt)
        url = f"/admin/{endpoint}?per_page=500&cache_bust={cache_bust}"
        response = page.request.get(url, headers=headers)
        if response.ok:
            payload = response.json()
            # Handle both list and dict responses
            if isinstance(payload, list):
                data = payload
            else:
                data = payload.get("data", [])
            for item in data:
                if item.get("name") == name:
                    return item
        else:
            logger.warning("find_entity_by_name: %s returned status=%d: %s", endpoint, response.status, response.text()[:200])
        page.wait_for_timeout(500)
    return None


def find_server(page: Page, server_name: str, retries: int = 5):
    """Find server by name.

    Args:
        page: Playwright page object
        server_name: Server name to search for
        retries: Number of retry attempts

    Returns:
        Server dict if found, None otherwise
    """
    return find_entity_by_name(page, "servers", server_name, retries)


def find_tool(page: Page, tool_name: str, retries: int = 5):
    """Find tool by name.

    Args:
        page: Playwright page object
        tool_name: Tool name to search for
        retries: Number of retry attempts

    Returns:
        Tool dict if found, None otherwise
    """
    return find_entity_by_name(page, "tools", tool_name, retries)


def find_resource(page: Page, resource_name: str, retries: int = 5):
    """Find resource by name.

    Args:
        page: Playwright page object
        resource_name: Resource name to search for
        retries: Number of retry attempts

    Returns:
        Resource dict if found, None otherwise
    """
    return find_entity_by_name(page, "resources", resource_name, retries)


def find_prompt(page: Page, prompt_name: str, retries: int = 5):
    """Find prompt by name.

    Args:
        page: Playwright page object
        prompt_name: Prompt name to search for
        retries: Number of retry attempts

    Returns:
        Prompt dict if found, None otherwise
    """
    return find_entity_by_name(page, "prompts", prompt_name, retries)


def find_agent(page: Page, agent_name: str, retries: int = 5):
    """Find A2A agent by name.

    Args:
        page: Playwright page object
        agent_name: Agent name to search for
        retries: Number of retry attempts

    Returns:
        Agent dict if found, None otherwise
    """
    return find_entity_by_name(page, "a2a", agent_name, retries)


def find_gateway(page: Page, gateway_name: str, retries: int = 5):
    """Find gateway by name.

    Args:
        page: Playwright page object
        gateway_name: Gateway name to search for
        retries: Number of retry attempts

    Returns:
        Gateway dict if found, None otherwise
    """
    return find_entity_by_name(page, "gateways", gateway_name, retries)


# ==================== Delete Operations ====================


def delete_entity_by_id(page: Page, endpoint: str, entity_id: str, mark_inactive: bool = False) -> bool:
    """Generic function to delete any entity by ID via admin API.

    Args:
        page: Playwright page object
        endpoint: API endpoint (e.g., "tools", "servers", "resources")
        entity_id: Entity ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    data = f"is_inactive_checked={'true' if mark_inactive else 'false'}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    headers.update(_get_auth_headers(page))
    response = page.request.post(
        f"/admin/{endpoint}/{entity_id}/delete",
        data=data,
        headers=headers,
    )
    return response.status < 400


def delete_tool(page: Page, tool_id: str, mark_inactive: bool = False) -> bool:
    """Delete tool by ID.

    Args:
        page: Playwright page object
        tool_id: Tool ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    return delete_entity_by_id(page, "tools", tool_id, mark_inactive)


def delete_server(page: Page, server_id: str, mark_inactive: bool = False) -> bool:
    """Delete server by ID.

    Args:
        page: Playwright page object
        server_id: Server ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    return delete_entity_by_id(page, "servers", server_id, mark_inactive)


def delete_resource(page: Page, resource_id: str, mark_inactive: bool = False) -> bool:
    """Delete resource by ID.

    Args:
        page: Playwright page object
        resource_id: Resource ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    return delete_entity_by_id(page, "resources", resource_id, mark_inactive)


def delete_prompt(page: Page, prompt_id: str, mark_inactive: bool = False) -> bool:
    """Delete prompt by ID.

    Args:
        page: Playwright page object
        prompt_id: Prompt ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    return delete_entity_by_id(page, "prompts", prompt_id, mark_inactive)


def delete_agent(page: Page, agent_id: str, mark_inactive: bool = False) -> bool:
    """Delete A2A agent by ID.

    Args:
        page: Playwright page object
        agent_id: Agent ID to delete
        mark_inactive: If True, mark as inactive instead of hard delete

    Returns:
        True if deletion successful, False otherwise
    """
    return delete_entity_by_id(page, "a2a", agent_id, mark_inactive)


# ==================== Cleanup Helpers ====================


def cleanup_entity(page: Page, endpoint: str, entity_name: str) -> bool:
    """Find and delete an entity by name (convenience method for test cleanup).

    Args:
        page: Playwright page object
        endpoint: API endpoint (e.g., "tools", "servers")
        entity_name: Entity name to find and delete

    Returns:
        True if entity was found and deleted, False otherwise
    """
    entity = find_entity_by_name(page, endpoint, entity_name)
    if entity:
        return delete_entity_by_id(page, endpoint, entity["id"])
    return False


def cleanup_tool(page: Page, tool_name: str) -> bool:
    """Find and delete a tool by name.

    Args:
        page: Playwright page object
        tool_name: Tool name to find and delete

    Returns:
        True if tool was found and deleted, False otherwise
    """
    return cleanup_entity(page, "tools", tool_name)


def cleanup_server(page: Page, server_name: str) -> bool:
    """Find and delete a server by name.

    Args:
        page: Playwright page object
        server_name: Server name to find and delete

    Returns:
        True if server was found and deleted, False otherwise
    """
    return cleanup_entity(page, "servers", server_name)


def cleanup_resource(page: Page, resource_name: str) -> bool:
    """Find and delete a resource by name.

    Args:
        page: Playwright page object
        resource_name: Resource name to find and delete

    Returns:
        True if resource was found and deleted, False otherwise
    """
    return cleanup_entity(page, "resources", resource_name)


def cleanup_prompt(page: Page, prompt_name: str) -> bool:
    """Find and delete a prompt by name.

    Args:
        page: Playwright page object
        prompt_name: Prompt name to find and delete

    Returns:
        True if prompt was found and deleted, False otherwise
    """
    return cleanup_entity(page, "prompts", prompt_name)


def cleanup_agent(page: Page, agent_name: str) -> bool:
    """Find and delete an A2A agent by name.

    Args:
        page: Playwright page object
        agent_name: Agent name to find and delete

    Returns:
        True if agent was found and deleted, False otherwise
    """
    return cleanup_entity(page, "a2a", agent_name)
