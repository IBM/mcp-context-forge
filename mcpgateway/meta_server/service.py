# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/meta_server/service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Server Service.

This module provides the service layer for Virtual Meta-Servers. It handles:
- Registration of stub meta-tools for meta-type servers
- Extension points for tool listing interception (hide underlying tools)
- Placeholder responses for meta-tool invocations

Business logic for actual tool search, listing, description, execution,
categorization, and similarity is NOT implemented here. This module only
provides the framework and stubs.

Examples:
    >>> from mcpgateway.meta_server.service import MetaServerService
    >>> service = MetaServerService()
    >>> tools = service.get_meta_tool_definitions()
    >>> len(tools)
    6
    >>> tools[0]["name"]
    'search_tools'
"""

# Standard
import logging
from typing import Any, Dict, List, Optional

# First-Party
from mcpgateway.meta_server.schemas import (
    DescribeToolResponse,
    ExecuteToolResponse,
    GetSimilarToolsResponse,
    GetToolCategoriesResponse,
    ListToolsResponse,
    META_TOOL_DEFINITIONS,
    MetaConfig,
    MetaToolScope,
    SearchToolsResponse,
    ServerType,
)

logger = logging.getLogger(__name__)


class MetaServerService:
    """Service for managing meta-server tool registration and dispatch.

    This service provides:
    - Meta-tool definitions that replace the underlying tool listing
    - Stub handlers for each meta-tool that return placeholder responses
    - Extension points for future business logic integration

    The service is stateless and can be used as a singleton.

    Examples:
        >>> service = MetaServerService()
        >>> defs = service.get_meta_tool_definitions()
        >>> isinstance(defs, list)
        True
        >>> len(defs) == 6
        True
    """

    def get_meta_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return the list of meta-tool definitions for MCP tool listing.

        Each definition contains the tool name, description, and input schema
        in a format compatible with the MCP SDK's types.Tool structure.

        Returns:
            List of meta-tool definition dicts with keys: name, description, inputSchema.

        Examples:
            >>> service = MetaServerService()
            >>> tools = service.get_meta_tool_definitions()
            >>> {t["name"] for t in tools} == {"search_tools", "list_tools", "describe_tool", "execute_tool", "get_tool_categories", "get_similar_tools"}
            True
        """
        return [{"name": name, "description": defn["description"], "inputSchema": defn["input_schema"]} for name, defn in META_TOOL_DEFINITIONS.items()]

    def is_meta_server(self, server_type: Optional[str]) -> bool:
        """Check if the given server type is a meta-server.

        Args:
            server_type: The server type string to check.

        Returns:
            True if the server type is 'meta', False otherwise.

        Examples:
            >>> service = MetaServerService()
            >>> service.is_meta_server("meta")
            True
            >>> service.is_meta_server("standard")
            False
            >>> service.is_meta_server(None)
            False
        """
        return server_type == ServerType.META.value

    def should_hide_underlying_tools(self, server_type: Optional[str], hide_underlying_tools: bool = True) -> bool:
        """Determine if underlying tools should be hidden for this server.

        Extension point for future filtering logic. Currently returns True
        when the server is a meta-server and hide_underlying_tools is enabled.

        Args:
            server_type: The server type string.
            hide_underlying_tools: The hide_underlying_tools flag value.

        Returns:
            True if underlying tools should be hidden.

        Examples:
            >>> service = MetaServerService()
            >>> service.should_hide_underlying_tools("meta", True)
            True
            >>> service.should_hide_underlying_tools("meta", False)
            False
            >>> service.should_hide_underlying_tools("standard", True)
            False
        """
        return self.is_meta_server(server_type) and hide_underlying_tools

    def is_meta_tool(self, tool_name: str) -> bool:
        """Check if a tool name is a registered meta-tool.

        Args:
            tool_name: The tool name to check.

        Returns:
            True if the tool name matches a meta-tool.

        Examples:
            >>> service = MetaServerService()
            >>> service.is_meta_tool("search_tools")
            True
            >>> service.is_meta_tool("some_real_tool")
            False
        """
        return tool_name in META_TOOL_DEFINITIONS

    async def handle_meta_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a meta-tool call to the appropriate stub handler.

        This is the main entry point for meta-tool invocations. Each meta-tool
        returns a placeholder response indicating that the actual business logic
        is not yet implemented.

        Args:
            tool_name: Name of the meta-tool to invoke.
            arguments: Arguments for the tool call.

        Returns:
            Dict containing the stub response.

        Raises:
            ValueError: If the tool_name is not a recognized meta-tool.

        Examples:
            >>> import asyncio
            >>> service = MetaServerService()
            >>> result = asyncio.run(service.handle_meta_tool_call("search_tools", {"query": "test"}))
            >>> result["query"]
            'test'
        """
        handlers = {
            "search_tools": self._stub_search_tools,
            "list_tools": self._stub_list_tools,
            "describe_tool": self._stub_describe_tool,
            "execute_tool": self._stub_execute_tool,
            "get_tool_categories": self._stub_get_tool_categories,
            "get_similar_tools": self._stub_get_similar_tools,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown meta-tool: {tool_name}")

        logger.info(f"Handling meta-tool call: {tool_name}")
        return await handler(arguments)

    # ------------------------------------------------------------------
    # Stub handlers — return placeholder responses
    # Business logic will be implemented by other teams.
    # ------------------------------------------------------------------

    async def _stub_search_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for search_tools meta-tool.

        Args:
            arguments: Search parameters.

        Returns:
            Placeholder SearchToolsResponse as dict.
        """
        query = arguments.get("query", "")
        return SearchToolsResponse(
            tools=[],
            total_count=0,
            query=query,
            has_more=False,
        ).model_dump(by_alias=True)

    async def _stub_list_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for list_tools meta-tool.

        Args:
            arguments: List parameters.

        Returns:
            Placeholder ListToolsResponse as dict.
        """
        return ListToolsResponse(
            tools=[],
            total_count=0,
            has_more=False,
        ).model_dump(by_alias=True)

    async def _stub_describe_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for describe_tool meta-tool.

        Args:
            arguments: Describe parameters.

        Returns:
            Placeholder DescribeToolResponse as dict.
        """
        tool_name = arguments.get("tool_name", "unknown")
        return DescribeToolResponse(
            name=tool_name,
            description=f"Stub description for {tool_name}. Business logic not yet implemented.",
        ).model_dump(by_alias=True)

    async def _stub_execute_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for execute_tool meta-tool.

        Args:
            arguments: Execution parameters.

        Returns:
            Placeholder ExecuteToolResponse as dict.
        """
        tool_name = arguments.get("tool_name", "unknown")
        return ExecuteToolResponse(
            tool_name=tool_name,
            success=False,
            result=None,
            error="Meta-tool execute_tool is not yet implemented. Business logic pending.",
        ).model_dump(by_alias=True)

    async def _stub_get_tool_categories(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for get_tool_categories meta-tool.

        Args:
            arguments: Category query parameters.

        Returns:
            Placeholder GetToolCategoriesResponse as dict.
        """
        return GetToolCategoriesResponse(
            categories=[],
            total_categories=0,
        ).model_dump(by_alias=True)

    async def _stub_get_similar_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stub handler for get_similar_tools meta-tool.

        Args:
            arguments: Similarity query parameters.

        Returns:
            Placeholder GetSimilarToolsResponse as dict.
        """
        tool_name = arguments.get("tool_name", "unknown")
        return GetSimilarToolsResponse(
            reference_tool=tool_name,
            similar_tools=[],
            total_found=0,
        ).model_dump(by_alias=True)


# Module-level singleton
_meta_server_service: Optional[MetaServerService] = None


def get_meta_server_service() -> MetaServerService:
    """Get or create the MetaServerService singleton.

    Returns:
        MetaServerService instance.

    Examples:
        >>> service = get_meta_server_service()
        >>> isinstance(service, MetaServerService)
        True
    """
    global _meta_server_service  # pylint: disable=global-statement
    if _meta_server_service is None:
        _meta_server_service = MetaServerService()
    return _meta_server_service
