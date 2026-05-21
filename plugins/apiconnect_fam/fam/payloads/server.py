"""Location: ./plugins/apiconnect_fam/fam/payloads/server.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

FAM Server Payload Builder.
"""

# Standard
from typing import Any, Dict, List, Optional


class FAMServerPayload:
    """Builder for FAM MCP Server payloads following OpenAPI spec.

    Ensures all data types and constraints match the Asset Catalog API v1 specification:
    - mcpServerId: string (pattern: ^[a-zA-Z0-9_:-]+$, 1-255 chars)
    - name: string (1-255 chars)
    - description: string (max 1000 chars)
    - status: AssetStatus enum (ACTIVE, INACTIVE, DEPRECATED)
    - capabilities: array of MCPCapability enum
    - tags: array of string (max 50 items)
    - url: string (format: uri) - optional
    """

    # OpenAPI spec enums
    ASSET_STATUS_ACTIVE = "ACTIVE"
    ASSET_STATUS_INACTIVE = "INACTIVE"

    CAPABILITY_LOGGING = "LOGGING"
    CAPABILITY_COMPLETIONS = "COMPLETIONS"
    CAPABILITY_PROMPTS = "PROMPTS"
    CAPABILITY_RESOURCES = "RESOURCES"
    CAPABILITY_TOOLS = "TOOLS"

    @staticmethod
    def _truncate_string(value: Optional[str], max_length: int) -> str:
        """Truncate string to maximum length.

        Args:
            value: String value to truncate
            max_length: Maximum allowed length

        Returns:
            Truncated string
        """
        if not value:
            return ""
        return str(value)[:max_length]

    @staticmethod
    def _get_status(enabled: bool) -> str:
        """Map ContextForge enabled flag to FAM AssetStatus enum.

        Args:
            enabled: ContextForge server enabled flag

        Returns:
            AssetStatus enum value (ACTIVE or INACTIVE)
        """
        return FAMServerPayload.ASSET_STATUS_ACTIVE if enabled else FAMServerPayload.ASSET_STATUS_INACTIVE

    @staticmethod
    def _get_capabilities(server: Any) -> List[str]:
        """Detect server capabilities from associated items.

        Args:
            server: ContextForge Server ORM object

        Returns:
            List of MCPCapability enum values
        """
        capabilities = []

        if hasattr(server, "tools") and server.tools and len(server.tools) > 0:
            capabilities.append(FAMServerPayload.CAPABILITY_TOOLS)

        if hasattr(server, "resources") and server.resources and len(server.resources) > 0:
            capabilities.append(FAMServerPayload.CAPABILITY_RESOURCES)

        if hasattr(server, "prompts") and server.prompts and len(server.prompts) > 0:
            capabilities.append(FAMServerPayload.CAPABILITY_PROMPTS)

        return capabilities

    @staticmethod
    def _get_tags(server: Any) -> List[str]:
        """Extract and validate tags from server.

        Args:
            server: ContextForge Server ORM object

        Returns:
            List of tag strings (max 50 items)
        """
        tags = []
        if hasattr(server, "tags") and isinstance(server.tags, list):
            tags = server.tags[:50]  # Enforce maxItems: 50
        return tags

    @classmethod
    def build_create_payload(cls, server: Any) -> Dict[str, Any]:
        """Build MCPServerCreate payload for POST request.

        Required fields: mcpServerId, name
        Optional fields: id, description, url, status, capabilities, tags, owner

        Args:
            server: ContextForge Server ORM object

        Returns:
            Dictionary matching MCPServerCreate schema
        """
        server_id = cls._truncate_string(str(server.id), 255)
        payload: Dict[str, Any] = {
            "id": server_id,  # Same as mcpServerId to avoid confusion
            "mcpServerId": server_id,
            "name": cls._truncate_string(server.name, 255),
        }

        # Optional fields
        description = cls._truncate_string(server.description, 1000)
        if description:
            payload["description"] = description

        # Add URL if available
        if hasattr(server, "url") and server.url:
            payload["url"] = cls._truncate_string(server.url, 2048)

        payload["status"] = cls._get_status(server.enabled)

        capabilities = cls._get_capabilities(server)
        if capabilities:
            payload["capabilities"] = capabilities

        tags = cls._get_tags(server)
        if tags:
            payload["tags"] = tags

        return payload

    @classmethod
    def build_update_payload(cls, server: Any) -> Dict[str, Any]:
        """Build MCPServerUpdate payload for PUT request.

        All fields are optional in update schema.

        Args:
            server: ContextForge Server ORM object

        Returns:
            Dictionary matching MCPServerUpdate schema
        """
        payload: Dict[str, Any] = {}

        name = cls._truncate_string(server.name, 255)
        if name:
            payload["name"] = name

        description = cls._truncate_string(server.description, 1000)
        if description:
            payload["description"] = description

        payload["status"] = cls._get_status(server.enabled)

        capabilities = cls._get_capabilities(server)
        if capabilities:
            payload["capabilities"] = capabilities

        tags = cls._get_tags(server)
        if tags:
            payload["tags"] = tags

        return payload
