"""Location: ./plugins/apiconnect_fam/fam/payloads/tool.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

FAM Tool Payload Builder.
"""

# Standard
from typing import Any, Dict, List, Optional


class FAMToolPayload:
    """Builder for FAM MCP Tool payloads following OpenAPI spec.

    Ensures all data types and constraints match the Asset Catalog API v1 specification:
    - mcpServerId: string (parent server identifier)
    - mcpToolId: string (pattern: ^[a-zA-Z0-9_:-]+$) - optional
    - name: string (1-255 chars) - required
    - description: string (max 1000 chars)
    - requestType: MCPToolRequestType enum (HTTP, SSE)
    - inputSchema: MCPToolSchema object - required
    - outputSchema: MCPToolSchema object - optional
    - annotations: MCPToolAnnotations object - optional
    - tags: array of string (max 50 items)
    """

    # OpenAPI spec enums
    REQUEST_TYPE_HTTP = "HTTP"
    REQUEST_TYPE_SSE = "SSE"

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
    def _get_request_type(tool: Any) -> str:
        """Map ContextForge request_type to FAM MCPToolRequestType enum.

        Args:
            tool: ContextForge Tool ORM object

        Returns:
            MCPToolRequestType enum value (HTTP or SSE)
        """
        # ContextForge uses "SSE" or "HTTP" - map directly
        request_type = getattr(tool, "request_type", "SSE")
        if request_type and request_type.upper() in ["HTTP", "SSE"]:
            return request_type.upper()
        return FAMToolPayload.REQUEST_TYPE_SSE  # Default to SSE

    @staticmethod
    def _get_tags(tool: Any) -> List[str]:
        """Extract and validate tags from tool.

        Args:
            tool: ContextForge Tool ORM object

        Returns:
            List of tag strings (max 50 items)
        """
        tags = []
        if hasattr(tool, "tags") and isinstance(tool.tags, list):
            tags = tool.tags[:50]  # Enforce maxItems: 50
        return tags

    @staticmethod
    def _build_schema(schema_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Build MCPToolSchema from ContextForge schema.

        Args:
            schema_dict: ContextForge schema dictionary

        Returns:
            MCPToolSchema compliant dictionary or None
        """
        if not schema_dict or not isinstance(schema_dict, dict):
            return None

        # Ensure required 'type' field exists
        if "type" not in schema_dict:
            schema_dict["type"] = "object"

        return schema_dict

    @staticmethod
    def _build_annotations(tool: Any) -> Optional[Dict[str, Any]]:
        """Build MCPToolAnnotations from ContextForge tool.

        Args:
            tool: ContextForge Tool ORM object

        Returns:
            MCPToolAnnotations compliant dictionary or None
        """
        if not hasattr(tool, "annotations") or not tool.annotations:
            return None

        annotations = {}
        tool_annotations = tool.annotations

        # Map known annotation fields
        if "title" in tool_annotations:
            annotations["title"] = str(tool_annotations["title"])
        if "readOnlyHint" in tool_annotations:
            annotations["readOnlyHint"] = bool(tool_annotations["readOnlyHint"])
        if "destructiveHint" in tool_annotations:
            annotations["destructiveHint"] = bool(tool_annotations["destructiveHint"])
        if "idempotentHint" in tool_annotations:
            annotations["idempotentHint"] = bool(tool_annotations["idempotentHint"])
        if "openWorldHint" in tool_annotations:
            annotations["openWorldHint"] = bool(tool_annotations["openWorldHint"])

        return annotations if annotations else None

    @classmethod
    def build_create_payload(cls, tool: Any, server_id: str) -> Dict[str, Any]:
        """Build MCPToolCreate payload for POST request.

        Required fields: mcpServerId, name, inputSchema
        Optional fields: mcpToolId, description, requestType, outputSchema, annotations, tags, owner

        Args:
            tool: ContextForge Tool ORM object
            server_id: Parent MCP Server ID

        Returns:
            Dictionary matching MCPToolCreate schema
        """
        # Build input schema (required)
        input_schema = cls._build_schema(tool.input_schema)
        if not input_schema:
            # Provide minimal valid schema if missing
            input_schema = {"type": "object"}

        payload: Dict[str, Any] = {
            "mcpServerId": cls._truncate_string(server_id, 255),
            "name": cls._truncate_string(tool.original_name or tool.custom_name, 255),
            "inputSchema": input_schema,
        }

        # Optional mcpToolId
        if hasattr(tool, "id") and tool.id:
            payload["mcpToolId"] = cls._truncate_string(str(tool.id), 255)

        # Optional description
        description = cls._truncate_string(tool.description or tool.original_description, 1000)
        if description:
            payload["description"] = description

        # Optional requestType
        payload["requestType"] = cls._get_request_type(tool)

        # Optional outputSchema
        output_schema = cls._build_schema(tool.output_schema)
        if output_schema:
            payload["outputSchema"] = output_schema

        # Optional annotations
        annotations = cls._build_annotations(tool)
        if annotations:
            payload["annotations"] = annotations

        # Optional tags
        tags = cls._get_tags(tool)
        if tags:
            payload["tags"] = tags

        return payload

    @classmethod
    def build_update_payload(cls, tool: Any) -> Dict[str, Any]:
        """Build MCPToolUpdate payload for PUT request.

        All fields are optional in update schema.

        Args:
            tool: ContextForge Tool ORM object

        Returns:
            Dictionary matching MCPToolUpdate schema
        """
        payload: Dict[str, Any] = {}

        # Optional name
        name = cls._truncate_string(tool.original_name or tool.custom_name, 255)
        if name:
            payload["name"] = name

        # Optional description
        description = cls._truncate_string(tool.description or tool.original_description, 1000)
        if description:
            payload["description"] = description

        # Optional requestType
        payload["requestType"] = cls._get_request_type(tool)

        # Optional inputSchema
        input_schema = cls._build_schema(tool.input_schema)
        if input_schema:
            payload["inputSchema"] = input_schema

        # Optional outputSchema
        output_schema = cls._build_schema(tool.output_schema)
        if output_schema:
            payload["outputSchema"] = output_schema

        # Optional annotations
        annotations = cls._build_annotations(tool)
        if annotations:
            payload["annotations"] = annotations

        # Optional tags
        tags = cls._get_tags(tool)
        if tags:
            payload["tags"] = tags

        return payload
