# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/meta_tool_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Meta-Tool Service Implementation.
This module implements the business logic for meta-tools (describe_tool, execute_tool).
"""

# Standard
import time
from typing import Any, Dict, List, Optional
import uuid

# Third-Party
import jsonschema
from sqlalchemy import select
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.db import Server as DbServer
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.meta_server.schemas import (
    DescribeToolResponse,
    ExecuteToolResponse,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.tool_service import ToolService

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class MetaToolService:
    """Service for meta-tool operations."""

    def __init__(self, db: Session):
        """Initialize the MetaToolService.

        Args:
            db: Database session
        """
        self.db = db
        self.tool_service = ToolService()

    async def describe_tool(
        self,
        tool_name: str,
        include_metrics: bool = False,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        is_admin: bool = False,
        scope: Optional[str] = None,
    ) -> DescribeToolResponse:
        """Get detailed information about a specific tool.

        This implements the describe_tool meta-tool functionality with:
        - Tool resolution by name
        - Schema and metadata fetching
        - Optional metrics fetching
        - Scope verification

        Args:
            tool_name: Name of the tool to describe
            include_metrics: Whether to include execution metrics
            user_email: Email of requesting user
            token_teams: Team IDs from JWT token
            is_admin: Whether user is an admin
            scope: Optional scope filter

        Returns:
            DescribeToolResponse with tool details

        Raises:
            ValueError: If tool not found or access denied
        """
        # Resolve tool by name with scope verification
        tool = await self._resolve_tool(tool_name, user_email, token_teams, is_admin, scope)

        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        # Fetch server information
        server_id = None
        server_name = None
        if tool.servers:
            # Get first server (tools can be associated with multiple servers)
            server = tool.servers[0]
            server_id = server.id
            server_name = server.name

        # Fetch metrics if requested
        metrics = None
        if include_metrics:
            metrics = await self._fetch_tool_metrics(tool.id)

        # Extract tag strings from database format
        # Tags may be stored as [{'id': 'tag', 'label': 'tag'}, ...] or ['tag', ...]
        tags_list = tool.tags or []
        if tags_list and isinstance(tags_list[0], dict):
            tags_list = [tag.get("id") or tag.get("label") for tag in tags_list if isinstance(tag, dict)]

        # Build response
        response = DescribeToolResponse(
            name=tool.name,
            description=tool.description or tool.original_description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            server_id=server_id,
            server_name=server_name,
            tags=tags_list,
            metrics=metrics,
            annotations=tool.annotations,
        )

        return response

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        is_admin: bool = False,
        scope: Optional[str] = None,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> ExecuteToolResponse:
        """Execute a tool with argument validation and routing.

        This implements the execute_tool meta-tool functionality with:
        - Tool resolution
        - Argument validation against JSON schema
        - Routing to backend server
        - Safe header forwarding
        - Execution metadata

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool
            user_email: Email of requesting user
            token_teams: Team IDs from JWT token
            is_admin: Whether user is an admin
            scope: Optional scope filter
            request_headers: Headers from the original request

        Returns:
            ExecuteToolResponse with execution result and metadata

        Raises:
            ValueError: If tool not found, validation fails, or execution fails
            PermissionError: If access is denied
        """
        start_time = time.time()

        # Resolve tool with scope verification
        tool = await self._resolve_tool(tool_name, user_email, token_teams, is_admin, scope)

        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        # Validate arguments against input schema
        if tool.input_schema:
            try:
                jsonschema.validate(instance=arguments, schema=tool.input_schema)
            except jsonschema.ValidationError as e:
                raise ValueError(f"Argument validation failed: {e.message}")

        # Execute tool via ToolService
        try:
            # Generate request ID for tracking
            request_id = str(uuid.uuid4())

            # Prepare metadata
            meta_data = {
                "request_id": request_id,
                "meta_tool": "execute_tool",
            }

            # Forward request to ToolService for execution
            tool_result = await self.tool_service.invoke_tool(
                db=self.db,
                name=tool_name,
                arguments=arguments,
                request_headers=request_headers,
                user_email=user_email,
                token_teams=token_teams,
                meta_data=meta_data,
            )

            # Extract result content
            result_data = None
            if tool_result.content:
                if isinstance(tool_result.content, list) and len(tool_result.content) > 0:
                    first_content = tool_result.content[0]
                    if hasattr(first_content, "text"):
                        result_data = first_content.text
                    else:
                        result_data = str(first_content)
                else:
                    result_data = str(tool_result.content)

            execution_time_ms = int((time.time() - start_time) * 1000)

            return ExecuteToolResponse(
                tool_name=tool_name,
                success=not tool_result.isError,
                result=result_data,
                error=None,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return ExecuteToolResponse(
                tool_name=tool_name,
                success=False,
                result=None,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

    async def _resolve_tool(
        self,
        tool_name: str,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        is_admin: bool,
        scope: Optional[str],
    ) -> Optional[DbTool]:
        """Resolve a tool by name with scope verification.

        Args:
            tool_name: Name of the tool
            user_email: Email of requesting user
            token_teams: Team IDs from JWT token
            is_admin: Whether user is an admin
            scope: Optional scope filter

        Returns:
            Tool object or None if not found/accessible
        """
        # Build query with eager loading of relationships
        query = select(DbTool).options(joinedload(DbTool.servers)).where(DbTool.name == tool_name, DbTool.enabled == True)

        # Apply scope filtering if provided
        # Scope filtering logic:
        # - If scope is provided, filter by visibility or team
        # - Admin bypass if is_admin=True
        if scope and not is_admin:
            # Scope can be: public, team:<team_id>, private
            if scope == "public":
                query = query.where(DbTool.visibility == "public")
            elif scope.startswith("team:"):
                team_id = scope.replace("team:", "")
                query = query.where(DbTool.team_id == team_id)
            elif scope == "private":
                query = query.where(DbTool.owner_email == user_email)

        # Apply team-based filtering if not admin
        if not is_admin and token_teams is not None:
            # If token_teams is empty list, only public tools
            # If token_teams has values, include team tools + public tools
            if len(token_teams) == 0:
                query = query.where(DbTool.visibility == "public")
            else:
                # Third-Party
                from sqlalchemy import or_

                query = query.where(or_(DbTool.visibility == "public", DbTool.team_id.in_(token_teams)))

        result = self.db.execute(query)
        tool = result.scalars().first()

        return tool

    async def _fetch_tool_metrics(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """Fetch execution metrics for a tool.

        Args:
            tool_id: Tool ID

        Returns:
            Dictionary with metrics or None
        """
        try:
            # Query ToolMetric for aggregated metrics
            query = select(ToolMetric).where(ToolMetric.tool_id == tool_id)
            result = self.db.execute(query)
            metrics_records = result.scalars().all()

            if not metrics_records:
                return None

            # Aggregate metrics
            execution_count = len(metrics_records)
            successful = sum(1 for m in metrics_records if m.success)
            failed = execution_count - successful
            total_time = sum(m.response_time for m in metrics_records if m.response_time)
            avg_time = total_time / execution_count if execution_count > 0 else 0

            return {
                "execution_count": execution_count,
                "successful_executions": successful,
                "failed_executions": failed,
                "success_rate": successful / execution_count if execution_count > 0 else 0,
                "avg_response_time_ms": avg_time,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch metrics for tool {tool_id}: {e}")
            return None
