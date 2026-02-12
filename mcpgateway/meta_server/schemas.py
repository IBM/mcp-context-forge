# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/meta_server/schemas.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Server Schema Definitions.

This module defines Pydantic models for the Meta-Server feature including:
- Scope configuration for filtering tools across servers
- Meta-server configuration options
- Request/response contracts for all six meta-tools
- Server type enumeration supporting 'meta' type

These are contract-only definitions. Business logic is NOT implemented here.

Examples:
    >>> from mcpgateway.meta_server.schemas import MetaToolScope, MetaConfig
    >>> scope = MetaToolScope(include_tags=["production"], exclude_servers=["legacy-server"])
    >>> scope.include_tags
    ['production']
    >>> config = MetaConfig(enable_semantic_search=True, default_search_limit=25)
    >>> config.default_search_limit
    25
"""

# Standard
from enum import Enum
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, ConfigDict, Field, field_validator

# First-Party
from mcpgateway.utils.base_models import BaseModelWithConfigDict


# Server Type Enum

class ServerType(str, Enum):
    """Enumeration of supported virtual server types.

    Attributes:
        STANDARD: A standard virtual server that directly exposes associated tools.
        META: A meta-server that exposes meta-tools for tool discovery and execution
              instead of exposing underlying tools directly.

    Examples:
        >>> ServerType.STANDARD.value
        'standard'
        >>> ServerType.META.value
        'meta'
        >>> ServerType("meta") == ServerType.META
        True
    """

    STANDARD = "standard"
    META = "meta"

# Scope Configuration

class MetaToolScope(BaseModelWithConfigDict):
    """Scope configuration for filtering which tools are visible through a meta-server.

    This model defines the filtering rules that determine which underlying tools
    are accessible via meta-tool operations. Multiple filter fields combine with
    AND semantics (all conditions must match).

    Attributes:
        include_tags: Only include tools with at least one of these tags.
        exclude_tags: Exclude tools that have any of these tags.
        include_servers: Only include tools from these server IDs.
        exclude_servers: Exclude tools from these server IDs.
        include_visibility: Only include tools with these visibility levels.
        include_teams: Only include tools belonging to these team IDs.
        name_patterns: Only include tools whose names match one of these glob patterns.

    Examples:
        >>> scope = MetaToolScope(
        ...     include_tags=["production", "stable"],
        ...     exclude_tags=["deprecated"],
        ...     include_servers=["server-1", "server-2"],
        ... )
        >>> scope.include_tags
        ['production', 'stable']
        >>> scope.exclude_tags
        ['deprecated']
        >>> empty_scope = MetaToolScope()
        >>> empty_scope.include_tags
        []
    """

    include_tags: List[str] = Field(default_factory=list, description="Only include tools with at least one of these tags")
    exclude_tags: List[str] = Field(default_factory=list, description="Exclude tools that have any of these tags")
    include_servers: List[str] = Field(default_factory=list, description="Only include tools from these server IDs")
    exclude_servers: List[str] = Field(default_factory=list, description="Exclude tools from these server IDs")
    include_visibility: List[str] = Field(default_factory=list, description="Only include tools with these visibility levels (private, team, public)")
    include_teams: List[str] = Field(default_factory=list, description="Only include tools belonging to these team IDs")
    name_patterns: List[str] = Field(default_factory=list, description="Only include tools whose names match one of these glob patterns")

    @field_validator("include_visibility")
    @classmethod
    def validate_visibility_values(cls, v: List[str]) -> List[str]:
        """Validate that visibility values are valid.

        Args:
            v: List of visibility values to validate.

        Returns:
            Validated list of visibility values.

        Raises:
            ValueError: If any visibility value is invalid.

        Examples:
            >>> MetaToolScope.validate_visibility_values(["public", "team"])
            ['public', 'team']
        """
        valid_values = {"private", "team", "public"}
        for value in v:
            if value not in valid_values:
                raise ValueError(f"Invalid visibility value '{value}'. Must be one of: {valid_values}")
        return v


# Meta Configuration

class MetaConfig(BaseModelWithConfigDict):
    """Configuration options for meta-server behavior.

    Controls which meta-tool features are enabled and sets operational limits.

    Attributes:
        enable_semantic_search: Whether semantic search is available via search_tools.
        enable_categories: Whether tool categorization is available via get_tool_categories.
        enable_similar_tools: Whether similar tool discovery is available via get_similar_tools.
        default_search_limit: Default maximum number of results returned by search operations.
        max_search_limit: Hard upper limit for search results regardless of request parameters.
        include_metrics_in_search: Whether to include execution metrics in search results.

    Examples:
        >>> config = MetaConfig()
        >>> config.enable_semantic_search
        False
        >>> config.default_search_limit
        50
        >>> config.max_search_limit
        200
        >>> custom = MetaConfig(default_search_limit=10, max_search_limit=100)
        >>> custom.default_search_limit
        10
    """

    enable_semantic_search: bool = Field(False, description="Whether semantic search is available via search_tools")
    enable_categories: bool = Field(False, description="Whether tool categorization is available via get_tool_categories")
    enable_similar_tools: bool = Field(False, description="Whether similar tool discovery is available via get_similar_tools")
    default_search_limit: int = Field(50, ge=1, le=1000, description="Default maximum number of results returned by search operations")
    max_search_limit: int = Field(200, ge=1, le=10000, description="Hard upper limit for search results regardless of request parameters")
    include_metrics_in_search: bool = Field(False, description="Whether to include execution metrics in search results")

    @field_validator("max_search_limit")
    @classmethod
    def validate_max_gte_default(cls, v: int, info: Any) -> int:
        """Ensure max_search_limit is >= default_search_limit.

        Args:
            v: The max_search_limit value.
            info: Validation info containing other field values.

        Returns:
            Validated max_search_limit value.

        Raises:
            ValueError: If max_search_limit is less than default_search_limit.

        Examples:
            >>> MetaConfig(default_search_limit=50, max_search_limit=200)  # Valid
            MetaConfig(enable_semantic_search=False, enable_categories=False, enable_similar_tools=False, default_search_limit=50, max_search_limit=200, include_metrics_in_search=False)
        """
        default_limit = info.data.get("default_search_limit", 50)
        if v < default_limit:
            raise ValueError(f"max_search_limit ({v}) must be >= default_search_limit ({default_limit})")
        return v


# Meta-Tool Request/Response Schemas (Contracts Only)

class SearchToolsRequest(BaseModelWithConfigDict):
    """Request schema for the search_tools meta-tool.

    Attributes:
        query: Search query string for finding tools.
        limit: Maximum number of results to return.
        offset: Number of results to skip for pagination.
        tags: Optional tag filter to narrow results.
        include_metrics: Whether to include execution metrics in results.

    Examples:
        >>> req = SearchToolsRequest(query="database")
        >>> req.query
        'database'
        >>> req.limit
        50
    """

    query: str = Field(..., min_length=1, max_length=500, description="Search query string for finding tools")
    limit: int = Field(50, ge=1, le=1000, description="Maximum number of results to return")
    offset: int = Field(0, ge=0, description="Number of results to skip for pagination")
    tags: List[str] = Field(default_factory=list, description="Optional tag filter to narrow results")
    include_metrics: bool = Field(False, description="Whether to include execution metrics in results")


class ToolSummary(BaseModelWithConfigDict):
    """Summary representation of a tool in meta-tool responses.

    Attributes:
        name: Tool name identifier.
        description: Human-readable description of the tool.
        server_id: ID of the server hosting this tool.
        server_name: Name of the server hosting this tool.
        tags: Tags associated with the tool.
        input_schema: JSON Schema for the tool's input parameters.
        metrics: Optional execution metrics for the tool.

    Examples:
        >>> summary = ToolSummary(name="query_db", description="Run a DB query", server_id="s1", server_name="DB Server")
        >>> summary.name
        'query_db'
    """

    name: str = Field(..., description="Tool name identifier")
    description: Optional[str] = Field(None, description="Human-readable description of the tool")
    server_id: Optional[str] = Field(None, description="ID of the server hosting this tool")
    server_name: Optional[str] = Field(None, description="Name of the server hosting this tool")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the tool")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for the tool's input parameters")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Optional execution metrics for the tool")


class SearchToolsResponse(BaseModelWithConfigDict):
    """Response schema for the search_tools meta-tool.

    Attributes:
        tools: List of matching tool summaries.
        total_count: Total number of matching tools (before pagination).
        query: The original query string.
        has_more: Whether more results are available.

    Examples:
        >>> resp = SearchToolsResponse(tools=[], total_count=0, query="test", has_more=False)
        >>> resp.total_count
        0
    """

    tools: List[ToolSummary] = Field(default_factory=list, description="List of matching tool summaries")
    total_count: int = Field(0, ge=0, description="Total number of matching tools (before pagination)")
    query: str = Field(..., description="The original query string")
    has_more: bool = Field(False, description="Whether more results are available")


class ListToolsRequest(BaseModelWithConfigDict):
    """Request schema for the list_tools meta-tool.

    Attributes:
        limit: Maximum number of tools to return.
        offset: Number of tools to skip for pagination.
        tags: Optional tag filter.
        server_id: Optional server ID filter.
        include_metrics: Whether to include execution metrics.

    Examples:
        >>> req = ListToolsRequest()
        >>> req.limit
        50
        >>> req.offset
        0
    """

    limit: int = Field(50, ge=1, le=1000, description="Maximum number of tools to return")
    offset: int = Field(0, ge=0, description="Number of tools to skip for pagination")
    tags: List[str] = Field(default_factory=list, description="Optional tag filter")
    server_id: Optional[str] = Field(None, description="Optional server ID filter")
    include_metrics: bool = Field(False, description="Whether to include execution metrics")


class ListToolsResponse(BaseModelWithConfigDict):
    """Response schema for the list_tools meta-tool.

    Attributes:
        tools: List of tool summaries.
        total_count: Total number of tools matching the filter.
        has_more: Whether more results are available.

    Examples:
        >>> resp = ListToolsResponse(tools=[], total_count=0, has_more=False)
        >>> resp.total_count
        0
    """

    tools: List[ToolSummary] = Field(default_factory=list, description="List of tool summaries")
    total_count: int = Field(0, ge=0, description="Total number of tools matching the filter")
    has_more: bool = Field(False, description="Whether more results are available")


class DescribeToolRequest(BaseModelWithConfigDict):
    """Request schema for the describe_tool meta-tool.

    Attributes:
        tool_name: The name of the tool to describe.
        include_metrics: Whether to include execution metrics.

    Examples:
        >>> req = DescribeToolRequest(tool_name="query_db")
        >>> req.tool_name
        'query_db'
    """

    tool_name: str = Field(..., min_length=1, max_length=255, description="The name of the tool to describe")
    include_metrics: bool = Field(False, description="Whether to include execution metrics")


class DescribeToolResponse(BaseModelWithConfigDict):
    """Response schema for the describe_tool meta-tool.

    Attributes:
        name: Tool name identifier.
        description: Human-readable description.
        input_schema: JSON Schema for the tool's input.
        output_schema: JSON Schema for the tool's output.
        server_id: ID of the hosting server.
        server_name: Name of the hosting server.
        tags: Tags associated with the tool.
        metrics: Optional execution metrics.
        annotations: Optional tool annotations/metadata.

    Examples:
        >>> resp = DescribeToolResponse(name="query_db", description="Run a DB query")
        >>> resp.name
        'query_db'
    """

    name: str = Field(..., description="Tool name identifier")
    description: Optional[str] = Field(None, description="Human-readable description")
    input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for the tool's input")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for the tool's output")
    server_id: Optional[str] = Field(None, description="ID of the hosting server")
    server_name: Optional[str] = Field(None, description="Name of the hosting server")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the tool")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Optional execution metrics")
    annotations: Optional[Dict[str, Any]] = Field(None, description="Optional tool annotations/metadata")


class ExecuteToolRequest(BaseModelWithConfigDict):
    """Request schema for the execute_tool meta-tool.

    Attributes:
        tool_name: The name of the tool to execute.
        arguments: Arguments to pass to the tool.

    Examples:
        >>> req = ExecuteToolRequest(tool_name="query_db", arguments={"sql": "SELECT 1"})
        >>> req.tool_name
        'query_db'
        >>> req.arguments
        {'sql': 'SELECT 1'}
    """

    tool_name: str = Field(..., min_length=1, max_length=255, description="The name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool")


class ExecuteToolResponse(BaseModelWithConfigDict):
    """Response schema for the execute_tool meta-tool.

    Attributes:
        tool_name: Name of the tool that was executed.
        success: Whether the execution was successful.
        result: The execution result data.
        error: Error message if execution failed.
        execution_time_ms: Execution time in milliseconds.

    Examples:
        >>> resp = ExecuteToolResponse(tool_name="query_db", success=True, result={"rows": []})
        >>> resp.success
        True
    """

    tool_name: str = Field(..., description="Name of the tool that was executed")
    success: bool = Field(..., description="Whether the execution was successful")
    result: Optional[Any] = Field(None, description="The execution result data")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    execution_time_ms: Optional[float] = Field(None, ge=0, description="Execution time in milliseconds")


class GetToolCategoriesRequest(BaseModelWithConfigDict):
    """Request schema for the get_tool_categories meta-tool.

    Attributes:
        include_counts: Whether to include tool counts per category.

    Examples:
        >>> req = GetToolCategoriesRequest()
        >>> req.include_counts
        True
    """

    include_counts: bool = Field(True, description="Whether to include tool counts per category")


class ToolCategory(BaseModelWithConfigDict):
    """Representation of a tool category.

    Attributes:
        name: Category name.
        description: Category description.
        tool_count: Number of tools in this category.

    Examples:
        >>> cat = ToolCategory(name="database", description="Database tools", tool_count=5)
        >>> cat.name
        'database'
    """

    name: str = Field(..., description="Category name")
    description: Optional[str] = Field(None, description="Category description")
    tool_count: int = Field(0, ge=0, description="Number of tools in this category")


class GetToolCategoriesResponse(BaseModelWithConfigDict):
    """Response schema for the get_tool_categories meta-tool.

    Attributes:
        categories: List of tool categories.
        total_categories: Total number of categories.

    Examples:
        >>> resp = GetToolCategoriesResponse(categories=[], total_categories=0)
        >>> resp.total_categories
        0
    """

    categories: List[ToolCategory] = Field(default_factory=list, description="List of tool categories")
    total_categories: int = Field(0, ge=0, description="Total number of categories")


class GetSimilarToolsRequest(BaseModelWithConfigDict):
    """Request schema for the get_similar_tools meta-tool.

    Attributes:
        tool_name: The name of the reference tool.
        limit: Maximum number of similar tools to return.

    Examples:
        >>> req = GetSimilarToolsRequest(tool_name="query_db", limit=5)
        >>> req.tool_name
        'query_db'
    """

    tool_name: str = Field(..., min_length=1, max_length=255, description="The name of the reference tool")
    limit: int = Field(10, ge=1, le=100, description="Maximum number of similar tools to return")


class GetSimilarToolsResponse(BaseModelWithConfigDict):
    """Response schema for the get_similar_tools meta-tool.

    Attributes:
        reference_tool: Name of the reference tool.
        similar_tools: List of similar tool summaries with similarity scores.
        total_found: Total number of similar tools found.

    Examples:
        >>> resp = GetSimilarToolsResponse(reference_tool="query_db", similar_tools=[], total_found=0)
        >>> resp.reference_tool
        'query_db'
    """

    reference_tool: str = Field(..., description="Name of the reference tool")
    similar_tools: List[ToolSummary] = Field(default_factory=list, description="List of similar tool summaries")
    total_found: int = Field(0, ge=0, description="Total number of similar tools found")


# Meta-Tool Definition Constants

#: Registry of meta-tool names and their input schemas.
#: Used by the meta-server to register stubs and validate tool calls.
META_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "search_tools": {
        "description": "Search for tools across all servers in scope using text or semantic matching.",
        "input_schema": SearchToolsRequest.model_json_schema(),
    },
    "list_tools": {
        "description": "List all tools available in scope with optional filtering by tags or server.",
        "input_schema": ListToolsRequest.model_json_schema(),
    },
    "describe_tool": {
        "description": "Get detailed information about a specific tool including its schema and metadata.",
        "input_schema": DescribeToolRequest.model_json_schema(),
    },
    "execute_tool": {
        "description": "Execute a tool by name with the provided arguments, routing to the correct server.",
        "input_schema": ExecuteToolRequest.model_json_schema(),
    },
    "get_tool_categories": {
        "description": "Get a list of tool categories derived from tags and server groupings.",
        "input_schema": GetToolCategoriesRequest.model_json_schema(),
    },
    "get_similar_tools": {
        "description": "Find tools that are similar to a given tool based on description and schema similarity.",
        "input_schema": GetSimilarToolsRequest.model_json_schema(),
    },
}
