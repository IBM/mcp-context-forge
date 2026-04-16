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
    7
    >>> tools[0]["name"]
    'search_tools'
"""

# Standard
import fnmatch
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

# Third-Party
from sqlalchemy import or_

# First-Party
from mcpgateway.db import fresh_db_session, get_db, Tool, ToolEmbedding
from mcpgateway.meta_server.schemas import (
    AuthorizeAllGatewaysResponse,
    AuthorizeGatewayResponse,
    DescribeToolResponse,
    ExecuteToolResponse,
    GatewayAuthStatus,
    GetPromptResponse,
    GetSimilarToolsResponse,
    GetToolCategoriesResponse,
    ListPromptsResponse,
    ListResourcesResponse,
    ListToolsResponse,
    META_TOOL_DEFINITIONS,
    MetaConfig,
    MetaToolScope,
    PromptSummary,
    ReadResourceResponse,
    ResourceSummary,
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

    async def handle_meta_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Dispatch a meta-tool call to the appropriate stub handler.

        This is the main entry point for meta-tool invocations. Each meta-tool
        returns a placeholder response indicating that the actual business logic
        is not yet implemented.

        MCP clients send arguments using camelCase keys (from the JSON schema),
        but handlers expect snake_case keys. This method normalizes keys before
        dispatching to ensure both conventions work.

        Args:
            tool_name: Name of the meta-tool to invoke.
            arguments: Arguments for the tool call (may use camelCase or snake_case keys).
            user_email: Email of the authenticated user (for OAuth token retrieval).
            token_teams: Team IDs from JWT token.
            request_headers: Headers from the original request.

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
            "authorize_gateway": self._authorize_gateway,
            "authorize_all_gateways": self._authorize_all_gateways,
            "list_resources": self._list_resources,
            "read_resource": self._read_resource,
            "list_prompts": self._list_prompts,
            "get_prompt": self._get_prompt,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown meta-tool: {tool_name}")

        # Normalize camelCase keys to snake_case so handlers can use consistent key names.
        # MCP JSON schemas expose camelCase (e.g. "toolName") but handlers use snake_case
        # (e.g. "tool_name"). Accept both conventions by normalizing before dispatch.
        normalized_args = self._normalize_arguments(arguments)

        logger.info(f"Handling meta-tool call: {tool_name}")
        return await handler(
            normalized_args,
            user_email=user_email,
            token_teams=token_teams,
            request_headers=request_headers,
        )

    @staticmethod
    def _normalize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize argument keys from camelCase to snake_case.

        MCP JSON schemas use camelCase aliases (e.g. ``toolName``), but
        internal handlers expect snake_case (e.g. ``tool_name``).  This
        method converts all top-level keys so that both conventions are
        supported transparently.  Keys that are already snake_case pass
        through unchanged.

        Args:
            arguments: Raw arguments dict from the MCP request.

        Returns:
            A new dict with all top-level keys converted to snake_case.

        Examples:
            >>> MetaServerService._normalize_arguments({"toolName": "x", "limit": 5})
            {'tool_name': 'x', 'limit': 5}
        """
        _camel_re = re.compile(r"(?<=[a-z0-9])([A-Z])")

        def _to_snake(key: str) -> str:
            return _camel_re.sub(r"_\1", key).lower()

        return {_to_snake(k): v for k, v in arguments.items()}

    @staticmethod
    def _extract_user_context(kwargs: Dict[str, Any]) -> tuple:
        """Extract access-control parameters from handler kwargs.

        ``handle_meta_tool_call`` passes ``user_email``, ``token_teams``,
        and ``request_headers`` through to every handler.  This helper
        provides a single extraction point so handlers don't repeat the
        pattern.

        Returns:
            Tuple of (user_email, token_teams, request_headers).
        """
        return (
            kwargs.get("user_email"),
            kwargs.get("token_teams"),
            kwargs.get("request_headers"),
        )

    # ------------------------------------------------------------------
    # Implemented handlers
    # ------------------------------------------------------------------

    async def _search_tools(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
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

        # -- Extract user context for access control --
        user_email, token_teams, _ = self._extract_user_context(kwargs)

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
            from mcpgateway.services.tool_service import ToolService as _KwToolService  # pylint: disable=import-outside-toplevel
            _kw_ts = _KwToolService()

            db_gen = get_db()
            db = next(db_gen)
            try:
                # Use ToolService.list_tools for consistent access control
                kw_result = await _kw_ts.list_tools(
                    db=db,
                    include_inactive=False,
                    limit=limit,
                    user_email=user_email,
                    token_teams=token_teams,
                )
                kw_tools_list, _ = kw_result if isinstance(kw_result, tuple) else (kw_result, None)

                query_lower = query.lower()
                search_pattern = query_lower
                for tool in kw_tools_list:
                    tool_name = getattr(tool, "name", "")
                    tool_desc = getattr(tool, "description", "") or ""
                    # Filter to only matching tools
                    if search_pattern not in tool_name.lower() and search_pattern not in tool_desc.lower():
                        continue
                    # Score 1.0 for exact name match, 0.5 for partial match
                    if tool_name.lower() == query_lower:
                        score = 1.0
                    elif query_lower in tool_name.lower():
                        score = 0.7
                    else:
                        score = 0.5

                    keyword_results.append(
                        ToolSearchResult(
                            tool_name=tool_name,
                            description=tool_desc,
                            server_id=getattr(tool, "gateway_id", None),
                            server_name=None,
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

    async def _get_similar_tools(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
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

        # -- Extract user context for access control --
        user_email, token_teams, _ = self._extract_user_context(kwargs)

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

        # -- Step 4.5: Apply access-control filtering --
        # Build set of tool names the user can access, then discard the rest.
        if user_email is not None or token_teams is not None:
            try:
                from mcpgateway.services.tool_service import ToolService as _AcToolService  # pylint: disable=import-outside-toplevel

                _ac_ts = _AcToolService()
                db_gen = get_db()
                db = next(db_gen)
                try:
                    ac_result = await _ac_ts.list_tools(
                        db=db,
                        include_inactive=False,
                        limit=0,
                        user_email=user_email,
                        token_teams=token_teams,
                    )
                    ac_tools_list, _ = ac_result if isinstance(ac_result, tuple) else (ac_result, None)
                    accessible_names = {getattr(t, "name", "") for t in ac_tools_list}
                    similar_results = [r for r in similar_results if r.tool_name in accessible_names]
                finally:
                    try:
                        next(db_gen)
                    except StopIteration:
                        pass
            except Exception as e:
                logger.warning(f"Access control filtering failed for similar tools: {e}")

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

    async def _list_tools(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
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

        # -- Extract user context for access control --
        user_email, token_teams, _ = self._extract_user_context(kwargs)

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
                    user_email=user_email,
                    token_teams=token_teams,
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
            # ToolService.list_tools returns ToolRead objects (Pydantic)
            # which have gateway_id but not gateway relationship
            server_id_val = getattr(tool, "gateway_id", None)

            search_results.append(
                ToolSearchResult(
                    tool_name=tool.name,
                    description=getattr(tool, "description", "") or "",
                    server_id=server_id_val,
                    server_name=None,
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

    async def _stub_describe_tool(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Delegate to MetaToolService for describe_tool implementation.

        Args:
            arguments: Describe parameters.

        Returns:
            DescribeToolResponse as dict from MetaToolService.
        """
        # First-Party
        from mcpgateway.services.meta_tool_service import MetaToolService

        user_email, token_teams, _ = self._extract_user_context(kwargs)

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                service = MetaToolService(db)
                result = await service.describe_tool(
                    tool_name=arguments.get("tool_name", ""),
                    include_metrics=arguments.get("include_metrics", False),
                    scope=arguments.get("scope"),
                    user_email=user_email,
                    token_teams=token_teams,
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

    async def _stub_execute_tool(
        self,
        arguments: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Delegate to MetaToolService for execute_tool implementation.

        Args:
            arguments: Execution parameters.
            user_email: Email of the authenticated user (for OAuth token retrieval).
            token_teams: Team IDs from JWT token.
            request_headers: Headers from the original request.

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
                tool_name = arguments.get("tool_name", "")
                tool_arguments = arguments.get("arguments", {})

                # Tolerate flat argument layout: some clients (e.g. Copilot Studio)
                # send tool arguments at the same level as tool_name instead of
                # nesting them inside "arguments". Detect this by collecting any
                # keys that are not part of the execute_tool schema itself.
                if not tool_arguments:
                    _meta_keys = {"tool_name", "arguments", "scope"}
                    extra = {k: v for k, v in arguments.items() if k not in _meta_keys}
                    if extra:
                        tool_arguments = extra
                        logger.info(
                            "execute_tool: restructured flat arguments into nested format "
                            f"for tool '{tool_name}': {list(extra.keys())}"
                        )

                result = await service.execute_tool(
                    tool_name=tool_name,
                    arguments=tool_arguments,
                    scope=arguments.get("scope"),
                    user_email=user_email,
                    token_teams=token_teams,
                    request_headers=request_headers,
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

    async def _get_tool_categories(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
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

    async def _authorize_gateway(
        self,
        arguments: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        request_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Check OAuth authorization status for a gateway and return an authorize URL if needed.

        Args:
            arguments: Must contain gateway_name (name or ID of the gateway).
            user_email: Email of the authenticated user.
            token_teams: Team IDs from JWT token.
            request_headers: Headers from the original request.

        Returns:
            AuthorizeGatewayResponse as dict with status and optional authorize_url.
        """
        # First-Party
        from mcpgateway.config import get_settings
        from mcpgateway.db import Gateway
        from mcpgateway.services.token_storage_service import TokenStorageService

        # Resolve user_email: prefer explicit param, fall back to JWT in request_headers
        effective_email = user_email
        if not effective_email and request_headers:
            auth_header = request_headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    import jwt as pyjwt  # pylint: disable=import-outside-toplevel
                    token = auth_header[7:]
                    payload = pyjwt.decode(token, options={"verify_signature": False})
                    effective_email = payload.get("email") or payload.get("sub")
                    if effective_email:
                        effective_email = effective_email.strip().lower()
                except Exception:
                    pass

        gateway_name = arguments.get("gateway_name", "")
        if not gateway_name:
            return AuthorizeGatewayResponse(
                gateway_id="",
                gateway_name="",
                status="error",
                message="gateway_name is required",
            ).model_dump(by_alias=True)

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                from sqlalchemy import or_, select  # pylint: disable=import-outside-toplevel

                # Find gateway by name or ID
                gateway = db.execute(
                    select(Gateway).where(
                        or_(Gateway.name == gateway_name, Gateway.id == gateway_name)
                    )
                ).scalar_one_or_none()

                if not gateway:
                    return AuthorizeGatewayResponse(
                        gateway_id="",
                        gateway_name=gateway_name,
                        status="not_found",
                        message=f"Gateway '{gateway_name}' not found",
                    ).model_dump(by_alias=True)

                gateway_id = gateway.id

                # Check if gateway has OAuth config
                if not gateway.oauth_config:
                    return AuthorizeGatewayResponse(
                        gateway_id=gateway_id,
                        gateway_name=gateway.name,
                        status="authorized",
                        message="Gateway does not require OAuth authorization",
                    ).model_dump(by_alias=True)

                # Check if user already has a valid token (attempt refresh if expired)
                if effective_email:
                    token_service = TokenStorageService(db)
                    # get_user_token attempts automatic refresh via refresh_token
                    valid_token = await token_service.get_user_token(gateway_id, effective_email)
                    if valid_token:
                        token_info = await token_service.get_token_info(gateway_id, effective_email)
                        expires_at = token_info.get('expires_at', 'unknown') if token_info else 'unknown'
                        return AuthorizeGatewayResponse(
                            gateway_id=gateway_id,
                            gateway_name=gateway.name,
                            status="authorized",
                            message=f"You already have a valid OAuth token for '{gateway.name}' (expires {expires_at})",
                        ).model_dump(by_alias=True)

                # Build the authorize URL
                settings = get_settings()
                app_domain = str(settings.app_domain or "").rstrip("/")
                root_path = str(settings.app_root_path or "").strip("/")
                base = f"{app_domain}/{root_path}" if root_path else app_domain
                authorize_url = f"{base}/oauth/authorize/{gateway_id}"

                return AuthorizeGatewayResponse(
                    gateway_id=gateway_id,
                    gateway_name=gateway.name,
                    status="authorization_required",
                    authorize_url=authorize_url,
                    message=f"OAuth authorization required for '{gateway.name}'. [Click here to authorize]({authorize_url})",
                ).model_dump(by_alias=True)

            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass

        except Exception as e:
            logger.error(f"Error in authorize_gateway: {e}")
            return AuthorizeGatewayResponse(
                gateway_id="",
                gateway_name=gateway_name,
                status="error",
                message=f"Error checking gateway authorization: {str(e)}",
            ).model_dump(by_alias=True)

    async def _authorize_all_gateways(
        self,
        arguments: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        request_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Check OAuth authorization status for all gateways and return a single authorize-all URL.

        Args:
            arguments: No required arguments.
            user_email: Email of the authenticated user.
            token_teams: Team IDs from JWT token.
            request_headers: Headers from the original request.

        Returns:
            AuthorizeAllGatewaysResponse as dict with status and optional authorize_url.
        """
        # First-Party
        from mcpgateway.config import get_settings
        from mcpgateway.db import Gateway
        from mcpgateway.services.token_storage_service import TokenStorageService

        # Resolve user_email from JWT if not provided
        effective_email = user_email
        if not effective_email and request_headers:
            auth_header = request_headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    import jwt as pyjwt  # pylint: disable=import-outside-toplevel
                    token = auth_header[7:]
                    payload = pyjwt.decode(token, options={"verify_signature": False})
                    effective_email = payload.get("email") or payload.get("sub")
                    if effective_email:
                        effective_email = effective_email.strip().lower()
                except Exception:
                    pass

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                from sqlalchemy import select  # pylint: disable=import-outside-toplevel

                # Find all active OAuth gateways with authorization_code flow
                gateways = db.execute(
                    select(Gateway).where(
                        Gateway.auth_type == "oauth",
                        Gateway.enabled.is_(True),
                    )
                ).scalars().all()

                token_service = TokenStorageService(db)
                gateway_statuses = []
                pending_count = 0

                for gw in gateways:
                    if not gw.oauth_config or gw.oauth_config.get("grant_type") != "authorization_code":
                        continue

                    gw_status = "authorization_required"
                    if effective_email:
                        # get_user_token attempts automatic refresh via refresh_token
                        valid_token = await token_service.get_user_token(gw.id, effective_email)
                        if valid_token:
                            gw_status = "authorized"

                    if gw_status == "authorization_required":
                        pending_count += 1

                    gateway_statuses.append(GatewayAuthStatus(
                        gateway_id=gw.id,
                        gateway_name=gw.name,
                        status=gw_status,
                    ))

                if not gateway_statuses:
                    return AuthorizeAllGatewaysResponse(
                        status="all_authorized",
                        gateways=[],
                        message="No OAuth gateways found.",
                    ).model_dump(by_alias=True)

                if pending_count == 0:
                    names = ", ".join(gs.gateway_name for gs in gateway_statuses)
                    return AuthorizeAllGatewaysResponse(
                        status="all_authorized",
                        gateways=[gs.model_dump(by_alias=True) for gs in gateway_statuses],
                        message=f"All {len(gateway_statuses)} OAuth gateways are authorized: {names}",
                    ).model_dump(by_alias=True)

                # Build authorize-all URL
                settings = get_settings()
                app_domain = str(settings.app_domain or "").rstrip("/")
                root_path = str(settings.app_root_path or "").strip("/")
                base = f"{app_domain}/{root_path}" if root_path else app_domain
                authorize_url = f"{base}/oauth/authorize-all"

                pending_names = ", ".join(
                    gs.gateway_name for gs in gateway_statuses
                    if gs.status == "authorization_required"
                )

                return AuthorizeAllGatewaysResponse(
                    status="authorization_required",
                    authorize_url=authorize_url,
                    gateways=[gs.model_dump(by_alias=True) for gs in gateway_statuses],
                    message=f"{pending_count} gateway(s) need authorization: {pending_names}. [Click here to authorize all at once]({authorize_url})",
                ).model_dump(by_alias=True)

            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass

        except Exception as e:
            logger.error(f"Error in authorize_all_gateways: {e}")
            return AuthorizeAllGatewaysResponse(
                status="error",
                gateways=[],
                message=f"Error checking gateway authorization: {str(e)}",
            ).model_dump(by_alias=True)

    # ------------------------------------------------------------------
    # Resource and Prompt handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_tags(raw_tags: Any) -> List[str]:
        """Normalize tags from DB format to plain strings.

        Tags may be stored as dicts {'id': ..., 'label': ...} or plain strings.
        """
        if not raw_tags:
            return []
        result: List[str] = []
        for tag in raw_tags:
            if isinstance(tag, dict):
                result.append(tag.get("id") or tag.get("label") or str(tag))
            else:
                result.append(str(tag))
        return result

    async def _list_resources(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """List MCP resources with pagination and optional filtering.

        Args:
            arguments: List parameters dict with keys:
                - limit (int): Max results to return (default 50)
                - offset (int): Pagination offset (default 0)
                - tags (List[str]): Optional tag filter
                - mime_type (str): Optional MIME type filter

        Returns:
            ListResourcesResponse as dict.
        """
        from mcpgateway.db import Resource  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.resource_service import ResourceService as _RsService  # pylint: disable=import-outside-toplevel

        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        tags = arguments.get("tags", [])
        mime_type = arguments.get("mime_type")

        # Extract user context for access control
        user_email, token_teams, _ = self._extract_user_context(kwargs)

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                query = db.query(Resource).filter(Resource.enabled.is_(True))

                # Apply access control
                _rs = _RsService()
                query = await _rs._apply_access_control(query, db, user_email, token_teams)

                if mime_type:
                    query = query.filter(Resource.mime_type == mime_type)

                all_resources = query.order_by(Resource.created_at.desc()).all()

                # Apply tag filtering in Python (tags stored as JSON)
                if tags:
                    all_resources = [
                        r for r in all_resources
                        if r.tags and any(t in self._normalize_tags(r.tags) for t in tags)
                    ]

                total_count = len(all_resources)
                paginated = all_resources[offset: offset + limit]
                has_more = total_count > offset + limit

                summaries = [
                    ResourceSummary(
                        uri=r.uri,
                        name=r.name,
                        description=r.description,
                        mime_type=r.mime_type,
                        size=r.size,
                        tags=self._normalize_tags(r.tags),
                    )
                    for r in paginated
                ]

                return ListResourcesResponse(
                    resources=summaries,
                    total_count=total_count,
                    has_more=has_more,
                ).model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Error listing resources: {e}")
            return ListResourcesResponse(
                resources=[],
                total_count=0,
                has_more=False,
            ).model_dump(by_alias=True)

    async def _read_resource(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Read the content of an MCP resource by URI.

        Args:
            arguments: Must contain uri (str) of the resource to read.

        Returns:
            ReadResourceResponse as dict with content.
        """
        from mcpgateway.db import Resource  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.observability_service import ObservabilityService, current_trace_id  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.resource_service import ResourceService as _RsService  # pylint: disable=import-outside-toplevel

        uri = arguments.get("uri", "")
        if not uri:
            return ReadResourceResponse(
                uri="",
                name="",
                text="Error: uri is required",
            ).model_dump(by_alias=True)

        # Extract user context for access control
        user_email, token_teams, _ = self._extract_user_context(kwargs)

        start_time = time.monotonic()
        success = False
        error_message = None
        trace_id = current_trace_id.get()
        db_span_id = None
        observability_service = ObservabilityService() if trace_id else None

        # Start observability span
        if trace_id and observability_service:
            try:
                with fresh_db_session() as span_db:
                    db_span_id = observability_service.start_span(
                        db=span_db,
                        trace_id=trace_id,
                        name="resource.read",
                        attributes={
                            "resource.uri": uri,
                            "user": kwargs.get("user_email", "anonymous"),
                        },
                        commit=False,
                    )
                logger.debug(f"✓ Created resource.read span: {db_span_id} for resource: {uri}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for resource read: {e}")
                db_span_id = None

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                resource = (
                    db.query(Resource)
                    .filter(Resource.uri == uri, Resource.enabled.is_(True))
                    .first()
                )

                if resource is None:
                    error_message = f"Resource not found: {uri}"
                    return ReadResourceResponse(
                        uri=uri,
                        name="",
                        text=error_message,
                    ).model_dump(by_alias=True)

                # Check access control
                _rs = _RsService()
                if not await _rs._check_resource_access(db, resource, user_email, token_teams):
                    error_message = f"Resource not found: {uri}"
                    return ReadResourceResponse(
                        uri=uri,
                        name="",
                        text=error_message,
                    ).model_dump(by_alias=True)

                text_content = resource.text_content
                if text_content is None and resource.binary_content is not None:
                    text_content = "(binary content — not displayable as text)"

                success = True
                return ReadResourceResponse(
                    uri=resource.uri,
                    name=resource.name,
                    mime_type=resource.mime_type,
                    text=text_content,
                    size=resource.size,
                ).model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error reading resource '{uri}': {e}")
            return ReadResourceResponse(
                uri=uri,
                name="",
                text=f"Error reading resource: {str(e)}",
            ).model_dump(by_alias=True)
        finally:
            # End observability span
            if db_span_id and observability_service:
                try:
                    with fresh_db_session() as span_db:
                        observability_service.end_span(
                            db=span_db,
                            span_id=db_span_id,
                            status="ok" if success else "error",
                            status_message=error_message,
                            attributes={
                                "duration_ms": (time.monotonic() - start_time) * 1000,
                            },
                            commit=False,
                        )
                    logger.debug(f"✓ Ended resource.read span: {db_span_id}")
                except Exception as e:
                    logger.warning(f"Failed to end observability span for resource read: {e}")

    async def _list_prompts(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """List MCP prompts with pagination and optional filtering.

        Args:
            arguments: List parameters dict with keys:
                - limit (int): Max results to return (default 50)
                - offset (int): Pagination offset (default 0)
                - tags (List[str]): Optional tag filter

        Returns:
            ListPromptsResponse as dict.
        """
        from mcpgateway.db import Prompt  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.prompt_service import PromptService as _PsService  # pylint: disable=import-outside-toplevel

        limit = arguments.get("limit", 50)
        offset = arguments.get("offset", 0)
        tags = arguments.get("tags", [])

        # Extract user context for access control
        user_email, token_teams, _ = self._extract_user_context(kwargs)

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                query = db.query(Prompt).filter(Prompt.enabled.is_(True))

                # Apply access control
                _ps = _PsService()
                query = await _ps._apply_access_control(query, db, user_email, token_teams)

                all_prompts = query.order_by(Prompt.created_at.desc()).all()

                # Apply tag filtering in Python (tags stored as JSON)
                if tags:
                    all_prompts = [
                        p for p in all_prompts
                        if p.tags and any(t in self._normalize_tags(p.tags) for t in tags)
                    ]

                total_count = len(all_prompts)
                paginated = all_prompts[offset: offset + limit]
                has_more = total_count > offset + limit

                summaries = [
                    PromptSummary(
                        name=p.name,
                        description=p.description,
                        tags=self._normalize_tags(p.tags),
                        argument_schema=p.argument_schema,
                    )
                    for p in paginated
                ]

                return ListPromptsResponse(
                    prompts=summaries,
                    total_count=total_count,
                    has_more=has_more,
                ).model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.error(f"Error listing prompts: {e}")
            return ListPromptsResponse(
                prompts=[],
                total_count=0,
                has_more=False,
            ).model_dump(by_alias=True)

    async def _get_prompt(self, arguments: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Get a prompt template by name with optional rendering.

        Args:
            arguments: Must contain name (str). Optional arguments (dict) for rendering.

        Returns:
            GetPromptResponse as dict with template and optionally rendered content.
        """
        from mcpgateway.db import Prompt  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.observability_service import ObservabilityService, current_trace_id  # pylint: disable=import-outside-toplevel
        from mcpgateway.services.prompt_service import PromptService as _PsService  # pylint: disable=import-outside-toplevel

        name = arguments.get("name", "")
        prompt_args = arguments.get("arguments", {})

        if not name:
            return GetPromptResponse(
                name="",
                template="",
                description="Error: name is required",
            ).model_dump(by_alias=True)

        # Extract user context for access control
        user_email, token_teams, _ = self._extract_user_context(kwargs)

        start_time = time.monotonic()
        success = False
        error_message = None
        trace_id = current_trace_id.get()
        db_span_id = None
        observability_service = ObservabilityService() if trace_id else None

        # Start observability span
        if trace_id and observability_service:
            try:
                with fresh_db_session() as span_db:
                    db_span_id = observability_service.start_span(
                        db=span_db,
                        trace_id=trace_id,
                        name="prompt.render",
                        attributes={
                            "prompt.id": name,
                            "arguments_count": len(prompt_args) if prompt_args else 0,
                            "user": kwargs.get("user_email", "anonymous"),
                        },
                        commit=False,
                    )
                logger.debug(f"✓ Created prompt.render span: {db_span_id} for prompt: {name}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for prompt render: {e}")
                db_span_id = None

        try:
            db_gen = get_db()
            db = next(db_gen)
            try:
                prompt = (
                    db.query(Prompt)
                    .filter(Prompt.name == name, Prompt.enabled.is_(True))
                    .first()
                )

                if prompt is None:
                    error_message = f"Prompt not found: {name}"
                    return GetPromptResponse(
                        name=name,
                        template="",
                        description=error_message,
                    ).model_dump(by_alias=True)

                # Check access control
                _ps = _PsService()
                if not await _ps._check_prompt_access(db, prompt, user_email, token_teams):
                    error_message = f"Prompt not found: {name}"
                    return GetPromptResponse(
                        name=name,
                        template="",
                        description=error_message,
                    ).model_dump(by_alias=True)

                rendered = None
                if prompt_args:
                    try:
                        prompt.validate_arguments(prompt_args)
                        rendered = prompt.template.format(**prompt_args)
                    except (ValueError, KeyError) as e:
                        rendered = f"Error rendering prompt: {str(e)}"

                success = True
                return GetPromptResponse(
                    name=prompt.name,
                    description=prompt.description,
                    template=prompt.template,
                    rendered=rendered,
                    argument_schema=prompt.argument_schema,
                    tags=self._normalize_tags(prompt.tags),
                ).model_dump(by_alias=True)
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error getting prompt '{name}': {e}")
            return GetPromptResponse(
                name=name,
                template="",
                description=f"Error getting prompt: {str(e)}",
            ).model_dump(by_alias=True)
        finally:
            # End observability span
            if db_span_id and observability_service:
                try:
                    with fresh_db_session() as span_db:
                        observability_service.end_span(
                            db=span_db,
                            span_id=db_span_id,
                            status="ok" if success else "error",
                            status_message=error_message,
                            attributes={
                                "duration_ms": (time.monotonic() - start_time) * 1000,
                            },
                            commit=False,
                        )
                    logger.debug(f"✓ Ended prompt.render span: {db_span_id}")
                except Exception as e:
                    logger.warning(f"Failed to end observability span for prompt render: {e}")


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
