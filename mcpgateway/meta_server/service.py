# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/meta_server/service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Server Service.

This module provides the service layer for Virtual Meta-Servers. It handles:
- Registration of meta-tools for meta-type servers
- Extension points for tool listing interception (hide underlying tools)
- search_tools: semantic + keyword hybrid search with scope filtering
- Placeholder (stub) responses for meta-tools not yet implemented

Implemented meta-tools:
- search_tools: natural language search + filters + ranking
- get_similar_tools: "more like this tool" vector similarity search

Stub meta-tools (not yet implemented):
- list_tools, describe_tool, execute_tool, get_tool_categories

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
import fnmatch
import logging
from typing import Any, Dict, List, Optional, Set

# Third-Party
from sqlalchemy import or_

# First-Party
from mcpgateway.db import get_db, Tool, ToolEmbedding
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
    ToolSummary,
)
from mcpgateway.schemas import ToolSearchResult
from mcpgateway.services.semantic_search_service import get_semantic_search_service
from mcpgateway.services.vector_search_service import VectorSearchService

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
            "search_tools": self._search_tools,
            "list_tools": self._list_tools,
            "describe_tool": self._stub_describe_tool,
            "execute_tool": self._stub_execute_tool,
            "get_tool_categories": self._get_tool_categories,
            "get_similar_tools": self._get_similar_tools,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown meta-tool: {tool_name}")

        logger.info(f"Handling meta-tool call: {tool_name}")
        return await handler(arguments)

    # ------------------------------------------------------------------
    # Implemented handlers
    # ------------------------------------------------------------------

    async def _search_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Search for tools using hybrid semantic + keyword search with scope filtering.

        Performs a hybrid search:
        1. Semantic search via embedding service + vector search
        2. Keyword fallback via basic name/description matching
        3. Merges and deduplicates results
        4. Normalizes ranking scores into a stable 0-1 range
        5. Applies scope filtering (last gate)
        6. Returns paginated response

        Args:
            arguments: Search parameters dict with keys:
                - query (str): Natural language search query (required)
                - limit (int): Max results to return (default 50)
                - offset (int): Pagination offset (default 0)
                - tags (List[str]): Optional tag filter
                - include_metrics (bool): Whether to include execution metrics

        Returns:
            SearchToolsResponse as dict with ranked, scoped results.
        """
        # -- Parse request params --
        query = arguments.get("query", "")
        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        tags = arguments.get("tags", [])
        include_metrics = arguments.get("include_metrics", False)

        # -- Step 1: Semantic search --
        semantic_results = []
        try:
            semantic_service = get_semantic_search_service()
            semantic_results = await semantic_service.search_tools(query=query, limit=limit)
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            # Proceed with empty semantic results as fallback

        # -- Step 2: Keyword fallback search --
        keyword_results = []
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                search_pattern = f"%{query}%"
                keyword_tools = (
                    db.query(Tool)
                    .filter(
                        Tool.enabled.is_(True),
                        or_(
                            Tool._computed_name.ilike(search_pattern),
                            Tool.description.ilike(search_pattern),
                        ),
                    )
                    .limit(limit)
                    .all()
                )

                query_lower = query.lower()
                for tool in keyword_tools:
                    # Score 1.0 for exact name match, 0.5 for partial match
                    if tool._computed_name.lower() == query_lower:
                        score = 1.0
                    elif query_lower in tool.name.lower():
                        score = 0.7
                    else:
                        score = 0.5

                    keyword_results.append(
                        ToolSearchResult(
                            tool_name=tool.name,
                            description=tool.description,
                            server_id=tool.gateway_id,
                            server_name=tool.gateway.name if tool.gateway else None,
                            similarity_score=score,
                        )
                    )
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")

        # -- Step 3: Merge and deduplicate results --
        # Combine semantic + keyword results, dedupe by tool_name,
        # keeping the higher score when duplicates are found.
        merged: Dict[str, ToolSearchResult] = {}
        for result in semantic_results + keyword_results:
            existing = merged.get(result.tool_name)
            if existing is None or result.similarity_score > existing.similarity_score:
                merged[result.tool_name] = result

        # -- Step 4: Normalize ranking scores and sort --
        # Scores from both sources are already in 0-1 range.
        # Sort descending by score.
        ranked_results = sorted(merged.values(), key=lambda r: r.similarity_score, reverse=True)

        # -- Step 5: Apply scope filtering (must be last gate) --
        # Enrich results with tool metadata from DB for scope fields
        # that aren't available on ToolSearchResult (tags, visibility, team_id).
        filtered_results = self._apply_scope_filtering(ranked_results, arguments.get("scope"))

        # -- Step 6: Apply tag filter from request args --
        if tags:
            filtered_results = [r for r in filtered_results if r.tool_name in self._get_tools_matching_tags(tags)]

        # -- Step 7: Paginate --
        total_count = len(filtered_results)
        paginated = filtered_results[offset : offset + limit]
        has_more = total_count > offset + limit

        # -- Step 8: Map results to ToolSummary objects --
        tool_summaries = self._map_to_tool_summaries(paginated, include_metrics)

        return SearchToolsResponse(
            tools=tool_summaries,
            total_count=total_count,
            query=query,
            has_more=has_more,
        ).model_dump(by_alias=True)

    async def _get_similar_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Find tools similar to a given reference tool using vector similarity.

        Performs a "more like this" search:
        1. Resolves the reference tool by name from the database
        2. Retrieves the tool's stored embedding vector
        3. Queries the vector search service for nearest neighbors
        4. Filters out the reference tool itself from results
        5. Applies scope filtering (last gate)
        6. Returns similarity scores with optional reason strings

        Args:
            arguments: Similarity query parameters dict with keys:
                - tool_name (str): Name of the reference tool (required)
                - limit (int): Max similar tools to return (default 10)

        Returns:
            GetSimilarToolsResponse as dict with similar tools and scores.
        """
        # -- Parse request params --
        tool_name = arguments.get("tool_name", "")
        limit = arguments.get("limit", 10)

        if not tool_name:
            return GetSimilarToolsResponse(
                reference_tool=tool_name,
                similar_tools=[],
                total_found=0,
            ).model_dump(by_alias=True)

        # -- Step 1: Resolve reference tool from the database --
        reference_tool = None
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                reference_tool = (
                    db.query(Tool)
                    .filter(
                        Tool._computed_name == tool_name,
                        Tool.enabled.is_(True),
                    )
                    .first()
                )
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Failed to look up reference tool '{tool_name}': {e}")

        if reference_tool is None:
            logger.info(f"Reference tool '{tool_name}' not found, returning empty results")
            return GetSimilarToolsResponse(
                reference_tool=tool_name,
                similar_tools=[],
                total_found=0,
            ).model_dump(by_alias=True)

        # -- Step 2: Retrieve the tool's stored embedding --
        embedding_vector = None
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                vector_service = VectorSearchService(db=db)
                tool_embedding = vector_service.get_tool_embedding(db, reference_tool.id)
                if tool_embedding is not None:
                    embedding_vector = tool_embedding.embedding
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Failed to retrieve embedding for tool '{tool_name}': {e}")

        if embedding_vector is None:
            logger.info(f"No embedding found for tool '{tool_name}', returning empty results")
            return GetSimilarToolsResponse(
                reference_tool=tool_name,
                similar_tools=[],
                total_found=0,
            ).model_dump(by_alias=True)

        # -- Step 3: Query vector search for nearest neighbors --
        similar_results: List[ToolSearchResult] = []
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                vector_service = VectorSearchService(db=db)
                # Request extra results so we still have enough after filtering out self
                similar_results = await vector_service.search_similar_tools(
                    embedding=embedding_vector,
                    limit=limit + 1,
                    db=db,
                )
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Vector search for similar tools failed: {e}")

        # -- Step 4: Filter out the reference tool itself --
        similar_results = [r for r in similar_results if r.tool_name != tool_name][:limit]

        # -- Step 5: Apply scope filtering --
        filtered_results = self._apply_scope_filtering(similar_results, arguments.get("scope"))

        # -- Step 6: Map results to ToolSummary objects --
        tool_summaries = self._map_to_tool_summaries(filtered_results)

        return GetSimilarToolsResponse(
            reference_tool=tool_name,
            similar_tools=tool_summaries,
            total_found=len(tool_summaries),
        ).model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # Helper methods for search and scope filtering
    # ------------------------------------------------------------------

    def _apply_scope_filtering(
        self,
        results: List[ToolSearchResult],
        scope_dict: Optional[Dict[str, Any]] = None,
    ) -> List[ToolSearchResult]:
        """Apply MetaToolScope filtering rules to search results.

        Scope filters combine with AND semantics — a tool must pass ALL
        active filters to be included. This is the last gate before
        pagination and should always be applied.

        Args:
            results: Ranked search results to filter.
            scope_dict: Optional scope configuration dict (MetaToolScope fields).

        Returns:
            Filtered list of ToolSearchResult objects.
        """
        if not scope_dict or not results:
            return results

        scope = MetaToolScope(**scope_dict)

        # Batch-fetch tool metadata for fields not on ToolSearchResult
        tool_names = [r.tool_name for r in results]
        metadata = self._get_tool_metadata(tool_names)

        filtered: List[ToolSearchResult] = []
        for result in results:
            meta = metadata.get(result.tool_name)
            if meta is None:
                # Tool not found in DB — exclude from scoped results
                continue

            tool_tags = meta.get("tags", [])
            tool_visibility = meta.get("visibility", "public")
            tool_team_id = meta.get("team_id")
            tool_server_id = result.server_id
            tool_name = result.tool_name

            # include_tags: tool must have at least one matching tag
            if scope.include_tags and not any(t in scope.include_tags for t in tool_tags):
                continue

            # exclude_tags: tool must NOT have any excluded tag
            if scope.exclude_tags and any(t in scope.exclude_tags for t in tool_tags):
                continue

            # include_servers: tool must be from one of these servers
            if scope.include_servers and tool_server_id not in scope.include_servers:
                continue

            # exclude_servers: tool must NOT be from excluded servers
            if scope.exclude_servers and tool_server_id in scope.exclude_servers:
                continue

            # include_visibility: tool must have one of these visibility levels
            if scope.include_visibility and tool_visibility not in scope.include_visibility:
                continue

            # include_teams: tool must belong to one of these teams
            if scope.include_teams and tool_team_id not in scope.include_teams:
                continue

            # name_patterns: tool name must match at least one glob pattern
            if scope.name_patterns and not any(fnmatch.fnmatch(tool_name, pat) for pat in scope.name_patterns):
                continue

            filtered.append(result)

        return filtered

    def _get_tool_metadata(self, tool_names: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch-fetch tool metadata from the database for scope filtering.

        Retrieves tags, visibility, and team_id for the given tool names.

        Args:
            tool_names: List of tool names to look up.

        Returns:
            Dict mapping tool_name -> {tags, visibility, team_id, input_schema}.
        """
        if not tool_names:
            return {}

        metadata: Dict[str, Dict[str, Any]] = {}
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                tools = db.query(Tool).filter(Tool._computed_name.in_(tool_names)).all()
                for tool in tools:
                    # Extract tag strings from tag objects
                    tags_list = tool.tags or []
                    if tags_list and isinstance(tags_list[0], dict):
                        # Tags are stored as dicts with 'id' and 'label', extract just the 'id'
                        tags_list = [tag.get("id") or tag.get("label") for tag in tags_list if isinstance(tag, dict)]
                    
                    metadata[tool.name] = {
                        "tags": tags_list,
                        "visibility": tool.visibility or "public",
                        "team_id": tool.team_id,
                        "input_schema": tool.input_schema,
                    }
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Failed to fetch tool metadata for scope filtering: {e}")

        return metadata

    def _get_tools_matching_tags(self, tags: List[str]) -> Set[str]:
        """Get the set of tool names that have at least one of the given tags.

        Args:
            tags: Tag values to match against.

        Returns:
            Set of tool names that match.
        """
        matching: Set[str] = set()
        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                tools = db.query(Tool).filter(Tool.enabled.is_(True)).all()
                for tool in tools:
                    tool_tags = tool.tags or []
                    if any(t in tags for t in tool_tags):
                        matching.add(tool.name)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.warning(f"Failed to fetch tools for tag filtering: {e}")

        return matching

    def _map_to_tool_summaries(
        self,
        results: List[ToolSearchResult],
        include_metrics: bool = False,
    ) -> List[ToolSummary]:
        """Map ToolSearchResult objects to ToolSummary objects.

        Enriches results with additional metadata (tags, input_schema)
        from the database.

        Args:
            results: Search results to map.
            include_metrics: Whether to include execution metrics.

        Returns:
            List of ToolSummary objects.
        """
        if not results:
            return []

        tool_names = [r.tool_name for r in results]
        metadata = self._get_tool_metadata(tool_names)

        summaries: List[ToolSummary] = []
        for result in results:
            meta = metadata.get(result.tool_name, {})
            summaries.append(
                ToolSummary(
                    name=result.tool_name,
                    description=result.description,
                    server_id=result.server_id,
                    server_name=result.server_name,
                    tags=meta.get("tags", []),
                    input_schema=meta.get("input_schema"),
                    metrics=None,  # TODO: populate from ToolMetric if include_metrics is True
                )
            )

        return summaries

    # ------------------------------------------------------------------
    # Implemented handlers
    # ------------------------------------------------------------------

    async def _list_tools(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List tools with pagination, sorting, and scope filtering.

        Performs paginated tool listing:
        1. Queries tools from database using ToolService
        2. Applies scope filtering (last gate)
        3. Supports sorting by name, created_at, or execution_count
        4. Returns paginated response with metadata

        Args:
            arguments: List parameters dict with keys:
                - limit (int): Max results to return (default 50)
                - offset (int): Pagination offset (default 0)
                - tags (List[str]): Optional tag filter
                - server_id (str): Optional server ID filter
                - include_metrics (bool): Whether to include execution metrics
                - sort_by (str): Field to sort by (name, created_at, execution_count)
                - sort_order (str): Sort order (asc, desc)
                - include_schema (bool): Whether to include input/output schemas

        Returns:
            ListToolsResponse as dict with tools, total_count, and pagination metadata.
        """
        # -- Parse request params --
        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        tags = arguments.get("tags", [])
        server_id = arguments.get("server_id")
        include_metrics = arguments.get("include_metrics", False)
        sort_by = arguments.get("sort_by", "created_at")
        sort_order = arguments.get("sort_order", "desc")
        include_schema = arguments.get("include_schema", False)

        # -- Step 1: Query tools from database using ToolService --
        # First-Party
        from mcpgateway.services.tool_service import ToolService

        tool_service = ToolService()
        all_tools = []

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                # Query with offset+limit+1 to determine has_more
                query_limit = limit + offset + 1

                # Call ToolService.list_tools with appropriate parameters
                result = await tool_service.list_tools(
                    db=db,
                    include_inactive=False,
                    tags=tags if tags else None,
                    gateway_id=server_id,
                    limit=query_limit,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    include_schema=include_schema,
                )

                # Extract tools from result (could be tuple or dict)
                if isinstance(result, tuple):
                    all_tools, _ = result
                elif isinstance(result, dict):
                    all_tools = result.get("data", [])
                else:
                    all_tools = result

            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Failed to query tools from database: {e}")
            # Return empty result on error
            return ListToolsResponse(
                tools=[],
                total_count=0,
                has_more=False,
            ).model_dump(by_alias=True)

        # -- Step 2: Convert to tool search results for scope filtering --
        # (Scope filtering expects ToolSearchResult objects)
        # First-Party
        from mcpgateway.schemas import ToolSearchResult

        search_results = []
        for tool in all_tools:
            server_name = None
            server_id_val = None
            if hasattr(tool, "gateway") and tool.gateway:
                server_name = tool.gateway.name
                server_id_val = tool.gateway.id
            elif hasattr(tool, "gateway_name"):
                server_name = tool.gateway_name
                server_id_val = getattr(tool, "gateway_id", None)

            search_results.append(
                ToolSearchResult(
                    tool_name=tool.name,
                    description=tool.description or "",
                    server_id=server_id_val,
                    server_name=server_name,
                    similarity_score=1.0,  # Not relevant for listing
                )
            )

        # -- Step 3: Apply scope filtering (must be last gate) --
        filtered_results = self._apply_scope_filtering(search_results, arguments.get("scope"))

        # -- Step 4: Paginate --
        total_count = len(filtered_results)
        paginated = filtered_results[offset : offset + limit]
        has_more = total_count > offset + limit

        # -- Step 5: Map results to ToolSummary objects --
        tool_summaries = self._map_to_tool_summaries(paginated, include_metrics)

        return ListToolsResponse(
            tools=tool_summaries,
            total_count=total_count,
            has_more=has_more,
        ).model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # Stub handlers — return placeholder responses
    # Business logic will be implemented by other teams.
    # ------------------------------------------------------------------

    async def _stub_describe_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to MetaToolService for describe_tool implementation.

        Args:
            arguments: Describe parameters.

        Returns:
            DescribeToolResponse as dict from MetaToolService.
        """
        # First-Party
        from mcpgateway.services.meta_tool_service import MetaToolService

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                service = MetaToolService(db)
                result = await service.describe_tool(
                    tool_name=arguments.get("tool_name", ""),
                    include_metrics=arguments.get("include_metrics", False),
                    scope=arguments.get("scope"),
                )
                return result.model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Error delegating describe_tool to MetaToolService: {e}")
            tool_name = arguments.get("tool_name", "unknown")
            return DescribeToolResponse(
                name=tool_name,
                description=f"Error describing tool {tool_name}: {str(e)}",
            ).model_dump(by_alias=True)

    async def _stub_execute_tool(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to MetaToolService for execute_tool implementation.

        Args:
            arguments: Execution parameters.

        Returns:
            ExecuteToolResponse as dict from MetaToolService.
        """
        # First-Party
        from mcpgateway.services.meta_tool_service import MetaToolService

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                service = MetaToolService(db)
                result = await service.execute_tool(
                    tool_name=arguments.get("tool_name", ""),
                    arguments=arguments.get("arguments", {}),
                    scope=arguments.get("scope"),
                )
                return result.model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Error delegating execute_tool to MetaToolService: {e}")
            tool_name = arguments.get("tool_name", "unknown")
            return ExecuteToolResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=f"Error executing tool {tool_name}: {str(e)}",
            ).model_dump(by_alias=True)

    async def _get_tool_categories(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get aggregated tool categories with counts from ToolService.

        Args:
            arguments: Category query parameters (include_counts).

        Returns:
            GetToolCategoriesResponse as dict with categories and counts.
        """
        # First-Party
        from mcpgateway.meta_server.schemas import ToolCategory
        from mcpgateway.services.tool_service import ToolService

        include_counts = arguments.get("include_counts", True)

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                tool_service = ToolService()
                
                # Call ToolService.get_tool_categories
                result = tool_service.get_tool_categories(
                    db=db,
                    actor_scope="public_user",  # Default to public scope
                )

                # Transform to meta-tool response format
                categories_list = []
                if include_counts:
                    categories_list = [
                        ToolCategory(
                            name=cat["name"],
                            description=cat.get("description"),
                            tool_count=cat.get("tool_count", 0),
                        )
                        for cat in result.get("categories", [])
                    ]
                else:
                    # Without counts
                    categories_list = [
                        ToolCategory(
                            name=cat["name"],
                            description=cat.get("description"),
                            tool_count=0,
                        )
                        for cat in result.get("categories", [])
                    ]

                return GetToolCategoriesResponse(
                    categories=categories_list,
                    total_categories=result.get("total_categories", 0),
                ).model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Error getting tool categories: {e}")
            return GetToolCategoriesResponse(
                categories=[],
                total_categories=0,
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
