# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tool Service Implementation.
This module implements tool management and invocation according to the MCP specification.
It handles:
- Tool registration and validation
- Tool invocation with schema validation
- Tool federation across gateways
- Event notifications for tool changes
- Active/inactive tool management
"""

# Standard
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import and_, case, delete, desc, Float, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.models import Gateway as PydanticGateway
from mcpgateway.models import TextContent
from mcpgateway.models import Tool as PydanticTool
from mcpgateway.models import ToolResult
from mcpgateway.observability import create_span
from mcpgateway.plugins.framework import GlobalContext, HttpHeaderPayload, PluginError, PluginManager, PluginViolationError, ToolPostInvokePayload, ToolPreInvokePayload
from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA
from mcpgateway.schemas import ToolCreate, ToolRead, ToolUpdate, TopPerformer
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.passthrough_headers import get_passthrough_headers
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

# Local
from ..config import extract_using_jq

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ToolError(Exception):
    """Base class for tool-related errors.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolError
        >>> err = ToolError("Something went wrong")
        >>> str(err)
        'Something went wrong'
    """


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolNotFoundError
        >>> err = ToolNotFoundError("Tool xyz not found")
        >>> str(err)
        'Tool xyz not found'
        >>> isinstance(err, ToolError)
        True
    """


class ToolNameConflictError(ToolError):
    """Raised when a tool name conflicts with existing (active or inactive) tool."""

    def __init__(self, name: str, enabled: bool = True, tool_id: Optional[int] = None, visibility: str = "public"):
        """Initialize the error with tool information.

        Args:
            name: The conflicting tool name.
            enabled: Whether the existing tool is enabled or not.
            tool_id: ID of the existing tool if available.
            visibility: The visibility of the tool ("public" or "team").

        Examples:
            >>> from mcpgateway.services.tool_service import ToolNameConflictError
            >>> err = ToolNameConflictError('test_tool', enabled=False, tool_id=123)
            >>> str(err)
            'Public Tool already exists with name: test_tool (currently inactive, ID: 123)'
            >>> err.name
            'test_tool'
            >>> err.enabled
            False
            >>> err.tool_id
            123
        """
        self.name = name
        self.enabled = enabled
        self.tool_id = tool_id
        if visibility == "team":
            vis_label = "Team-level"
        else:
            vis_label = "Public"
        message = f"{vis_label} Tool already exists with name: {name}"
        if not enabled:
            message += f" (currently inactive, ID: {tool_id})"
        super().__init__(message)


class ToolValidationError(ToolError):
    """Raised when tool validation fails.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolValidationError
        >>> err = ToolValidationError("Invalid tool configuration")
        >>> str(err)
        'Invalid tool configuration'
        >>> isinstance(err, ToolError)
        True
    """


class ToolInvocationError(ToolError):
    """Raised when tool invocation fails.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolInvocationError
        >>> err = ToolInvocationError("Tool execution failed")
        >>> str(err)
        'Tool execution failed'
        >>> isinstance(err, ToolError)
        True
        >>> # Test with detailed error
        >>> detailed_err = ToolInvocationError("Network timeout after 30 seconds")
        >>> "timeout" in str(detailed_err)
        True
        >>> isinstance(err, ToolError)
        True
    """


class ToolService:
    """Service for managing and invoking tools.

    Handles:
    - Tool registration and deregistration.
    - Tool invocation and validation.
    - Tool federation.
    - Event notifications.
    - Active/inactive tool management.
    """

    def __init__(self) -> None:
        """Initialize the tool service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> isinstance(service._event_subscribers, list)
            True
            >>> len(service._event_subscribers)
            0
            >>> hasattr(service, '_http_client')
            True
        """
        self._event_subscribers: List[asyncio.Queue] = []
        self._http_client = ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify})
        # Initialize plugin manager with env overrides to ease testing
        env_flag = os.getenv("PLUGINS_ENABLED")
        if env_flag is not None:
            env_enabled = env_flag.strip().lower() in {"1", "true", "yes", "on"}
            plugins_enabled = env_enabled
        else:
            plugins_enabled = settings.plugins_enabled
        config_file = os.getenv("PLUGIN_CONFIG_FILE", getattr(settings, "plugin_config_file", "plugins/config.yaml"))
        self._plugin_manager: PluginManager | None = PluginManager(config_file) if plugins_enabled else None
        self.oauth_manager = OAuthManager(
            request_timeout=int(settings.oauth_request_timeout if hasattr(settings, "oauth_request_timeout") else 30),
            max_retries=int(settings.oauth_max_retries if hasattr(settings, "oauth_max_retries") else 3),
        )

    async def initialize(self) -> None:
        """Initialize the service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> import asyncio
            >>> asyncio.run(service.initialize())  # Should log "Initializing tool service"
        """
        logger.info("Initializing tool service")

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> import asyncio
            >>> asyncio.run(service.shutdown())  # Should log "Tool service shutdown complete"
        """
        await self._http_client.aclose()
        logger.info("Tool service shutdown complete")

    async def get_top_tools(self, db: Session, limit: int = 5) -> List[TopPerformer]:
        """Retrieve the top-performing tools based on execution count.

        Queries the database to get tools with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing tool details and
        performance metrics.

        Args:
            db (Session): Database session for querying tool metrics.
            limit (int): Maximum number of tools to return. Defaults to 5.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Tool ID.
                - name: Tool name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        results = (
            db.query(
                DbTool.id,
                DbTool.name,
                func.count(ToolMetric.id).label("execution_count"),  # pylint: disable=not-callable
                func.avg(ToolMetric.response_time).label("avg_response_time"),  # pylint: disable=not-callable
                case(
                    (
                        func.count(ToolMetric.id) > 0,  # pylint: disable=not-callable
                        func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)).cast(Float) / func.count(ToolMetric.id) * 100,  # pylint: disable=not-callable
                    ),
                    else_=None,
                ).label("success_rate"),
                func.max(ToolMetric.timestamp).label("last_execution"),  # pylint: disable=not-callable
            )
            .outerjoin(ToolMetric)
            .group_by(DbTool.id, DbTool.name)
            .order_by(desc("execution_count"))
            .limit(limit)
            .all()
        )

        return build_top_performers(results)

    def _convert_tool_to_read(self, tool: DbTool) -> ToolRead:
        """Converts a DbTool instance into a ToolRead model, including aggregated metrics and
        new API gateway fields: request_type and authentication credentials (masked).

        Args:
            tool (DbTool): The ORM instance of the tool.

        Returns:
            ToolRead: The Pydantic model representing the tool, including aggregated metrics and new fields.
        """
        tool_dict = tool.__dict__.copy()
        tool_dict.pop("_sa_instance_state", None)
        tool_dict["execution_count"] = tool.execution_count
        tool_dict["metrics"] = tool.metrics_summary
        tool_dict["request_type"] = tool.request_type
        tool_dict["annotations"] = tool.annotations or {}

        decoded_auth_value = decode_auth(tool.auth_value)
        if tool.auth_type == "basic":
            decoded_bytes = base64.b64decode(decoded_auth_value["Authorization"].split("Basic ")[1])
            username, password = decoded_bytes.decode("utf-8").split(":")
            tool_dict["auth"] = {
                "auth_type": "basic",
                "username": username,
                "password": "********" if password else None,
            }
        elif tool.auth_type == "bearer":
            tool_dict["auth"] = {
                "auth_type": "bearer",
                "token": "********" if decoded_auth_value["Authorization"] else None,
            }
        elif tool.auth_type == "authheaders":
            tool_dict["auth"] = {
                "auth_type": "authheaders",
                "auth_header_key": next(iter(decoded_auth_value)),
                "auth_header_value": "********" if decoded_auth_value[next(iter(decoded_auth_value))] else None,
            }
        else:
            tool_dict["auth"] = None

        tool_dict["name"] = tool.name
        # Handle displayName with fallback and None checks
        display_name = getattr(tool, "display_name", None)
        custom_name = getattr(tool, "custom_name", tool.original_name)
        tool_dict["displayName"] = display_name or custom_name
        tool_dict["custom_name"] = custom_name
        tool_dict["gateway_slug"] = getattr(tool, "gateway_slug", "") or ""
        tool_dict["custom_name_slug"] = getattr(tool, "custom_name_slug", "") or ""
        tool_dict["tags"] = getattr(tool, "tags", []) or []

        return ToolRead.model_validate(tool_dict)

    async def _record_tool_metric(self, db: Session, tool: DbTool, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for a tool invocation.

        This function calculates the response time using the provided start time and records
        the metric details (including whether the invocation was successful and any error message)
        into the database. The metric is then committed to the database.

        Args:
            db (Session): The SQLAlchemy database session.
            tool (DbTool): The tool that was invoked.
            start_time (float): The monotonic start time of the invocation.
            success (bool): True if the invocation succeeded; otherwise, False.
            error_message (Optional[str]): The error message if the invocation failed, otherwise None.
        """
        end_time = time.monotonic()
        response_time = end_time - start_time
        metric = ToolMetric(
            tool_id=tool.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    async def register_tool(
        self,
        db: Session,
        tool: ToolCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: str = None,
    ) -> ToolRead:
        """Register a new tool with team support.

        Args:
            db: Database session.
            tool: Tool creation schema.
            created_by: Username who created this tool.
            created_from_ip: IP address of creator.
            created_via: Creation method (ui, api, import, federation).
            created_user_agent: User agent of creation request.
            import_batch_id: UUID for bulk import operations.
            federation_source: Source gateway for federated tools.
            team_id: Optional team ID to assign tool to.
            owner_email: Optional owner email for tool ownership.
            visibility: Tool visibility (private, team, public).

        Returns:
            Created tool information.

        Raises:
            IntegrityError: If there is a database integrity error.
            ToolNameConflictError: If a tool with the same name and visibility public exists.
            ToolError: For other tool registration errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> tool.name = 'test'
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> mock_gateway = MagicMock()
            >>> mock_gateway.name = 'test_gateway'
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> def mock_refresh(obj):
            ...     obj.gateway = mock_gateway
            >>> db.refresh = MagicMock(side_effect=mock_refresh)
            >>> service._notify_tool_added = AsyncMock()
            >>> service._convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.register_tool(db, tool))
            'tool_read'
        """
        try:
            if tool.auth is None:
                auth_type = None
                auth_value = None
            else:
                auth_type = tool.auth.auth_type
                auth_value = tool.auth.auth_value

            if team_id is None:
                team_id = tool.team_id

            if owner_email is None:
                owner_email = tool.owner_email
            if visibility is None:
                visibility = tool.visibility or "private"
            # Check for existing tool with the same name and visibility
            if visibility.lower() == "public":
                # Check for existing public tool with the same name
                existing_tool = db.execute(select(DbTool).where(DbTool.name == tool.name, DbTool.visibility == "public")).scalar_one_or_none()
                if existing_tool:
                    raise ToolNameConflictError(existing_tool.name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team tool with the same name, team_id
                existing_tool = db.execute(
                    select(DbTool).where(DbTool.name == tool.name, DbTool.visibility == "team", DbTool.team_id == team_id)  # pylint: disable=comparison-with-callable
                ).scalar_one_or_none()
                if existing_tool:
                    raise ToolNameConflictError(existing_tool.name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)

            db_tool = DbTool(
                original_name=tool.name,
                custom_name=tool.name,
                custom_name_slug=slugify(tool.name),
                display_name=tool.displayName or tool.name,
                url=str(tool.url),
                description=tool.description,
                integration_type=tool.integration_type,
                request_type=tool.request_type,
                headers=tool.headers,
                input_schema=tool.input_schema,
                annotations=tool.annotations,
                jsonpath_filter=tool.jsonpath_filter,
                auth_type=auth_type,
                auth_value=auth_value,
                gateway_id=tool.gateway_id,
                tags=tool.tags or [],
                # Metadata fields
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
                version=1,
                # Team scoping fields
                team_id=team_id,
                owner_email=owner_email or created_by,
                visibility=visibility,
            )
            db.add(db_tool)
            db.commit()
            db.refresh(db_tool)
            await self._notify_tool_added(db_tool)
            logger.info(f"Registered tool: {db_tool.name}")
            return self._convert_tool_to_read(db_tool)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityError during tool registration: {ie}")
            raise ie
        except ToolNameConflictError as tnce:
            db.rollback()
            logger.error(f"ToolNameConflictError during tool registration: {tnce}")
            raise tnce
        except Exception as e:
            db.rollback()
            raise ToolError(f"Failed to register tool: {str(e)}")

    async def list_tools(
        self, db: Session, include_inactive: bool = False, cursor: Optional[str] = None, tags: Optional[List[str]] = None, _request_headers: Optional[Dict[str, str]] = None
    ) -> List[ToolRead]:
        """
        Retrieve a list of registered tools from the database.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.
            tags (Optional[List[str]]): Filter tools by tags. If provided, only tools with at least one matching tag will be returned.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.

        Returns:
            List[ToolRead]: A list of registered tools represented as ToolRead objects.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service._convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_tools(db))
            >>> isinstance(result, list)
            True
        """
        query = select(DbTool)
        cursor = None  # Placeholder for pagination; ignore for now
        logger.debug(f"Listing tools with include_inactive={include_inactive}, cursor={cursor}, tags={tags}")
        if not include_inactive:
            query = query.where(DbTool.enabled)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbTool.tags, tags, match_any=True))

        tools = db.execute(query).scalars().all()
        return [self._convert_tool_to_read(t) for t in tools]

    async def list_server_tools(self, db: Session, server_id: str, include_inactive: bool = False, cursor: Optional[str] = None, _request_headers: Optional[Dict[str, str]] = None) -> List[ToolRead]:
        """
        Retrieve a list of registered tools from the database.

        Args:
            db (Session): The SQLAlchemy database session.
            server_id (str): Server ID
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.

        Returns:
            List[ToolRead]: A list of registered tools represented as ToolRead objects.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service._convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_tools(db, 'server1'))
            >>> isinstance(result, list)
            True
        """
        query = select(DbTool).join(server_tool_association, DbTool.id == server_tool_association.c.tool_id).where(server_tool_association.c.server_id == server_id)
        cursor = None  # Placeholder for pagination; ignore for now
        logger.debug(f"Listing server tools for server_id={server_id} with include_inactive={include_inactive}, cursor={cursor}")
        if not include_inactive:
            query = query.where(DbTool.enabled)
        tools = db.execute(query).scalars().all()
        return [self._convert_tool_to_read(t) for t in tools]

    async def list_tools_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[ToolRead]:
        """
        List tools user has access to with team filtering.

        Args:
            db: Database session
            user_email: Email of the user requesting tools
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive tools
            skip: Number of tools to skip for pagination
            limit: Maximum number of tools to return

        Returns:
            List[ToolRead]: Tools the user has access to
        """
        # Build query following existing patterns from list_tools()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        query = select(DbTool)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbTool.enabled.is_(True))

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team
            access_conditions.append(and_(DbTool.team_id == team_id, DbTool.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbTool.team_id == team_id, DbTool.owner_email == user_email))

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns

            access_conditions = []

            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbTool.owner_email == user_email)

            # 2. Team resources where user is member
            if team_ids:
                access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

            # 3. Public resources (if visibility allows)
            access_conditions.append(DbTool.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbTool.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.offset(skip).limit(limit)

        tools = db.execute(query).scalars().all()
        return [self._convert_tool_to_read(t) for t in tools]

    async def get_tool(self, db: Session, tool_id: str) -> ToolRead:
        """
        Retrieve a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.

        Returns:
            ToolRead: The tool object.

        Raises:
            ToolNotFoundError: If the tool is not found.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> service._convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.get_tool(db, 'tool_id'))
            'tool_read'
        """
        tool = db.get(DbTool, tool_id)
        if not tool:
            raise ToolNotFoundError(f"Tool not found: {tool_id}")
        return self._convert_tool_to_read(tool)

    async def delete_tool(self, db: Session, tool_id: str) -> None:
        """
        Delete a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.

        Raises:
            ToolNotFoundError: If the tool is not found.
            ToolError: For other deletion errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_tool_deleted = AsyncMock()
            >>> import asyncio
            >>> asyncio.run(service.delete_tool(db, 'tool_id'))
        """
        try:
            tool = db.get(DbTool, tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")
            tool_info = {"id": tool.id, "name": tool.name}
            db.delete(tool)
            db.commit()
            await self._notify_tool_deleted(tool_info)
            logger.info(f"Permanently deleted tool: {tool_info['name']}")
        except Exception as e:
            db.rollback()
            raise ToolError(f"Failed to delete tool: {str(e)}")

    async def toggle_tool_status(self, db: Session, tool_id: str, activate: bool, reachable: bool) -> ToolRead:
        """
        Toggle the activation status of a tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            activate (bool): True to activate, False to deactivate.
            reachable (bool): True if the tool is reachable.

        Returns:
            ToolRead: The updated tool object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            ToolError: For other errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_tool_activated = AsyncMock()
            >>> service._notify_tool_deactivated = AsyncMock()
            >>> service._convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.toggle_tool_status(db, 'tool_id', True, True))
            'tool_read'
        """
        try:
            tool = db.get(DbTool, tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            is_activated = is_reachable = False
            if tool.enabled != activate:
                tool.enabled = activate
                is_activated = True

            if tool.reachable != reachable:
                tool.reachable = reachable
                is_reachable = True

            if is_activated or is_reachable:
                tool.updated_at = datetime.now(timezone.utc)

                db.commit()
                db.refresh(tool)
                if activate:
                    await self._notify_tool_activated(tool)
                else:
                    await self._notify_tool_deactivated(tool)
                logger.info(f"Tool: {tool.name} is {'enabled' if activate else 'disabled'}{' and accessible' if reachable else ' but inaccessible'}")

            return self._convert_tool_to_read(tool)
        except Exception as e:
            db.rollback()
            raise ToolError(f"Failed to toggle tool status: {str(e)}")

    async def invoke_tool(self, db: Session, name: str, arguments: Dict[str, Any], request_headers: Optional[Dict[str, str]] = None, app_user_email: Optional[str] = None) -> ToolResult:
        """
        Invoke a registered tool and record execution metrics.

        Args:
            db: Database session.
            name: Name of tool to invoke.
            arguments: Tool arguments.
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.
            app_user_email (Optional[str], optional): MCP Gateway user email for OAuth token retrieval.
                Required for OAuth-protected gateways.

        Returns:
            Tool invocation result.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolInvocationError: If invocation fails.
            PluginViolationError: If plugin blocks tool invocation.
            PluginError: If encounters issue with plugin

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.side_effect = [tool, None]
            >>> tool.reachable = True
            >>> import asyncio
            >>> result = asyncio.run(service.invoke_tool(db, 'tool_name', {}))
            >>> isinstance(result, object)
            True
        """
        # pylint: disable=comparison-with-callable
        tool = db.execute(select(DbTool).where(DbTool.name == name).where(DbTool.enabled)).scalar_one_or_none()
        if not tool:
            inactive_tool = db.execute(select(DbTool).where(DbTool.name == name).where(not_(DbTool.enabled))).scalar_one_or_none()
            if inactive_tool:
                raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
            raise ToolNotFoundError(f"Tool not found: {name}")

        # is_reachable = db.execute(select(DbTool.reachable).where(slug_expr == name)).scalar_one_or_none()
        is_reachable = tool.reachable

        if not is_reachable:
            raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

        # Check if this is an A2A tool and route to A2A service
        if tool.integration_type == "A2A" and tool.annotations and "a2a_agent_id" in tool.annotations:
            return await self._invoke_a2a_tool(db, tool, arguments)

        # Plugin hook: tool pre-invoke
        context_table = None
        request_id = uuid.uuid4().hex
        # Use gateway_id if available, otherwise use a generic server identifier
        gateway_id = getattr(tool, "gateway_id", "unknown")
        server_id = gateway_id if isinstance(gateway_id, str) else "unknown"
        global_context = GlobalContext(request_id=request_id, server_id=server_id, tenant_id=None)

        start_time = time.monotonic()
        success = False
        error_message = None

        # Create a trace span for the tool invocation
        with create_span(
            "tool.invoke",
            {
                "tool.name": name,
                "tool.id": str(tool.id) if tool else "unknown",
                "tool.integration_type": tool.integration_type if tool else "unknown",
                "tool.gateway_id": str(tool.gateway_id) if tool and tool.gateway_id else None,
                "arguments_count": len(arguments) if arguments else 0,
                "has_headers": bool(request_headers),
            },
        ) as span:
            try:
                # Get combined headers for the tool including base headers, auth, and passthrough headers
                # headers = self._get_combined_headers(db, tool, tool.headers or {}, request_headers)
                headers = tool.headers or {}
                if tool.integration_type == "REST":
                    # Handle OAuth authentication for REST tools
                    if tool.auth_type == "oauth" and hasattr(tool, "oauth_config") and tool.oauth_config:
                        try:
                            access_token = await self.oauth_manager.get_access_token(tool.oauth_config)
                            headers["Authorization"] = f"Bearer {access_token}"
                        except Exception as e:
                            logger.error(f"Failed to obtain OAuth access token for tool {tool.name}: {e}")
                            raise ToolInvocationError(f"OAuth authentication failed: {str(e)}")
                    else:
                        credentials = decode_auth(tool.auth_value)
                        # Filter out empty header names/values to avoid "Illegal header name" errors
                        filtered_credentials = {k: v for k, v in credentials.items() if k and v}
                        headers.update(filtered_credentials)

                    # Only call get_passthrough_headers if we actually have request headers to pass through
                    if request_headers:
                        headers = get_passthrough_headers(request_headers, headers, db)

                    if self._plugin_manager:
                        tool_metadata = PydanticTool.model_validate(tool)
                        global_context.metadata[TOOL_METADATA] = tool_metadata
                        pre_result, context_table = await self._plugin_manager.tool_pre_invoke(
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(headers)),
                            global_context=global_context,
                            local_contexts=None,
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    # Build the payload based on integration type
                    payload = arguments.copy()

                    # Handle URL path parameter substitution
                    final_url = tool.url
                    if "{" in tool.url and "}" in tool.url:
                        # Extract path parameters from URL template and arguments
                        url_params = re.findall(r"\{(\w+)\}", tool.url)
                        url_substitutions = {}

                        for param in url_params:
                            if param in payload:
                                url_substitutions[param] = payload.pop(param)  # Remove from payload
                                final_url = final_url.replace(f"{{{param}}}", str(url_substitutions[param]))
                            else:
                                raise ToolInvocationError(f"Required URL parameter '{param}' not found in arguments")

                    # --- Extract query params from URL ---
                    parsed = urlparse(final_url)
                    final_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                    query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

                    # Merge leftover payload + query params
                    payload.update(query_params)

                    # Use the tool's request_type rather than defaulting to POST.
                    method = tool.request_type.upper()
                    if method == "GET":
                        response = await self._http_client.get(final_url, params=payload, headers=headers)
                    else:
                        response = await self._http_client.request(method, final_url, json=payload, headers=headers)
                    response.raise_for_status()

                    # Handle 204 No Content responses that have no body
                    if response.status_code == 204:
                        tool_result = ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")])
                        # Mark as successful only after all operations complete successfully
                        success = True
                    elif response.status_code not in [200, 201, 202, 206]:
                        result = response.json()
                        tool_result = ToolResult(
                            content=[TextContent(type="text", text=str(result["error"]) if "error" in result else "Tool error encountered")],
                            is_error=True,
                        )
                        # Don't mark as successful for error responses - success remains False
                    else:
                        result = response.json()
                        filtered_response = extract_using_jq(result, tool.jsonpath_filter)
                        tool_result = ToolResult(content=[TextContent(type="text", text=json.dumps(filtered_response, indent=2))])
                        # Mark as successful only after all operations complete successfully
                        success = True
                elif tool.integration_type == "MCP":
                    transport = tool.request_type.lower()
                    gateway = db.execute(select(DbGateway).where(DbGateway.id == tool.gateway_id).where(DbGateway.enabled)).scalar_one_or_none()

                    # Handle OAuth authentication for the gateway
                    if gateway and gateway.auth_type == "oauth" and gateway.oauth_config:
                        grant_type = gateway.oauth_config.get("grant_type", "client_credentials")

                        if grant_type == "authorization_code":
                            # For Authorization Code flow, try to get stored tokens
                            try:
                                # First-Party
                                from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                                token_storage = TokenStorageService(db)

                                # Get user-specific OAuth token
                                if not app_user_email:
                                    raise ToolInvocationError(f"User authentication required for OAuth-protected gateway '{gateway.name}'. Please ensure you are authenticated.")

                                access_token = await token_storage.get_user_token(gateway.id, app_user_email)

                                if access_token:
                                    headers = {"Authorization": f"Bearer {access_token}"}
                                else:
                                    # User hasn't authorized this gateway yet
                                    raise ToolInvocationError(f"Please authorize {gateway.name} first. Visit /oauth/authorize/{gateway.id} to complete OAuth flow.")
                            except Exception as e:
                                logger.error(f"Failed to obtain stored OAuth token for gateway {gateway.name}: {e}")
                                raise ToolInvocationError(f"OAuth token retrieval failed for gateway: {str(e)}")
                        else:
                            # For Client Credentials flow, get token directly
                            try:
                                access_token = await self.oauth_manager.get_access_token(gateway.oauth_config)
                                headers = {"Authorization": f"Bearer {access_token}"}
                            except Exception as e:
                                logger.error(f"Failed to obtain OAuth access token for gateway {gateway.name}: {e}")
                                raise ToolInvocationError(f"OAuth authentication failed for gateway: {str(e)}")
                    else:
                        headers = decode_auth(gateway.auth_value if gateway else None)

                    # Get combined headers including gateway auth and passthrough
                    if request_headers:
                        headers = get_passthrough_headers(request_headers, headers, db, gateway)

                    async def connect_to_sse_server(server_url: str):
                        """Connect to an MCP server running with SSE transport.

                        Args:
                            server_url: MCP Server SSE URL

                        Returns:
                            ToolResult: Result of tool call
                        """
                        async with sse_client(url=server_url, headers=headers) as streams:
                            async with ClientSession(*streams) as session:
                                await session.initialize()
                                tool_call_result = await session.call_tool(tool.original_name, arguments)
                        return tool_call_result

                    async def connect_to_streamablehttp_server(server_url: str):
                        """Connect to an MCP server running with Streamable HTTP transport.

                        Args:
                            server_url: MCP Server URL

                        Returns:
                            ToolResult: Result of tool call
                        """
                        async with streamablehttp_client(url=server_url, headers=headers) as (read_stream, write_stream, _get_session_id):
                            async with ClientSession(read_stream, write_stream) as session:
                                await session.initialize()
                                tool_call_result = await session.call_tool(tool.original_name, arguments)
                        return tool_call_result

                    tool_gateway_id = tool.gateway_id
                    tool_gateway = db.execute(select(DbGateway).where(DbGateway.id == tool_gateway_id).where(DbGateway.enabled)).scalar_one_or_none()

                    if self._plugin_manager:
                        tool_metadata = PydanticTool.model_validate(tool)
                        global_context.metadata[TOOL_METADATA] = tool_metadata
                        if tool_gateway:
                            gateway_metadata = PydanticGateway.model_validate(tool_gateway)
                            global_context.metadata[GATEWAY_METADATA] = gateway_metadata
                        pre_result, context_table = await self._plugin_manager.tool_pre_invoke(
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(headers)),
                            global_context=global_context,
                            local_contexts=None,
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    tool_call_result = ToolResult(content=[TextContent(text="", type="text")])
                    if transport == "sse":
                        tool_call_result = await connect_to_sse_server(tool_gateway.url)
                    elif transport == "streamablehttp":
                        tool_call_result = await connect_to_streamablehttp_server(tool_gateway.url)
                    content = tool_call_result.model_dump(by_alias=True).get("content", [])

                    filtered_response = extract_using_jq(content, tool.jsonpath_filter)
                    tool_result = ToolResult(content=filtered_response)
                    # Mark as successful only after all operations complete successfully
                    success = True
                else:
                    tool_result = ToolResult(content=[TextContent(type="text", text="Invalid tool type")])

                # Plugin hook: tool post-invoke
                if self._plugin_manager:
                    post_result, _ = await self._plugin_manager.tool_post_invoke(
                        payload=ToolPostInvokePayload(name=name, result=tool_result.model_dump(by_alias=True)),
                        global_context=global_context,
                        local_contexts=context_table,
                        violations_as_exceptions=True,
                    )
                    # Use modified payload if provided
                    if post_result.modified_payload:
                        # Reconstruct ToolResult from modified result
                        modified_result = post_result.modified_payload.result
                        if isinstance(modified_result, dict) and "content" in modified_result:
                            tool_result = ToolResult(content=modified_result["content"])
                        else:
                            # If result is not in expected format, convert it to text content
                            tool_result = ToolResult(content=[TextContent(type="text", text=str(modified_result))])

                return tool_result
            except (PluginError, PluginViolationError):
                raise
            except Exception as e:
                error_message = str(e)
                # Set span error status
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                raise ToolInvocationError(f"Tool invocation failed: {error_message}")
            finally:
                # Add final span attributes
                if span:
                    span.set_attribute("success", success)
                    span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)
                await self._record_tool_metric(db, tool, start_time, success, error_message)

    async def update_tool(
        self,
        db: Session,
        tool_id: str,
        tool_update: ToolUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> ToolRead:
        """
        Update an existing tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            tool_update (ToolUpdate): Tool update schema with new data.
            modified_by (Optional[str]): Username who modified this tool.
            modified_from_ip (Optional[str]): IP address of modifier.
            modified_via (Optional[str]): Modification method (ui, api).
            modified_user_agent (Optional[str]): User agent of modification request.

        Returns:
            The updated ToolRead object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            IntegrityError: If there is a database integrity error.
            ToolNameConflictError: If a tool with the same name already exists.
            ToolError: For other update errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service._notify_tool_updated = AsyncMock()
            >>> service._convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.update_tool(db, 'tool_id', MagicMock()))
            'tool_read'
        """
        try:
            tool = db.get(DbTool, tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            # Check for name change and ensure uniqueness
            if tool_update.name and tool_update.name != tool.name:
                # Check for existing tool with the same name and visibility
                if tool_update.visibility.lower() == "public":
                    # Check for existing public tool with the same name
                    existing_tool = db.execute(select(DbTool).where(DbTool.custom_name == tool_update.custom_name, DbTool.visibility == "public")).scalar_one_or_none()
                    if existing_tool:
                        raise ToolNameConflictError(existing_tool.custom_name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)
                elif tool_update.visibility.lower() == "team" and tool_update.team_id:
                    # Check for existing team tool with the same name
                    existing_tool = db.execute(
                        select(DbTool).where(DbTool.custom_name == tool_update.custom_name, DbTool.visibility == "team", DbTool.team_id == tool_update.team_id)
                    ).scalar_one_or_none()
                    if existing_tool:
                        raise ToolNameConflictError(existing_tool.custom_name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)

            if tool_update.custom_name is not None:
                tool.custom_name = tool_update.custom_name
            if tool_update.displayName is not None:
                tool.display_name = tool_update.displayName
            if tool_update.url is not None:
                tool.url = str(tool_update.url)
            if tool_update.description is not None:
                tool.description = tool_update.description
            if tool_update.integration_type is not None:
                tool.integration_type = tool_update.integration_type
            if tool_update.request_type is not None:
                tool.request_type = tool_update.request_type
            if tool_update.headers is not None:
                tool.headers = tool_update.headers
            if tool_update.input_schema is not None:
                tool.input_schema = tool_update.input_schema
            if tool_update.annotations is not None:
                tool.annotations = tool_update.annotations
            if tool_update.jsonpath_filter is not None:
                tool.jsonpath_filter = tool_update.jsonpath_filter
            if tool_update.visibility is not None:
                tool.visibility = tool_update.visibility

            if tool_update.auth is not None:
                if tool_update.auth.auth_type is not None:
                    tool.auth_type = tool_update.auth.auth_type
                if tool_update.auth.auth_value is not None:
                    tool.auth_value = tool_update.auth.auth_value
            else:
                tool.auth_type = None

            # Update tags if provided
            if tool_update.tags is not None:
                tool.tags = tool_update.tags

            # Update modification metadata
            if modified_by is not None:
                tool.modified_by = modified_by
            if modified_from_ip is not None:
                tool.modified_from_ip = modified_from_ip
            if modified_via is not None:
                tool.modified_via = modified_via
            if modified_user_agent is not None:
                tool.modified_user_agent = modified_user_agent

            # Increment version
            if hasattr(tool, "version") and tool.version is not None:
                tool.version += 1
            else:
                tool.version = 1

            tool.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(tool)
            await self._notify_tool_updated(tool)
            logger.info(f"Updated tool: {tool.name}")
            return self._convert_tool_to_read(tool)
        except IntegrityError as ie:
            logger.error(f"IntegrityError during tool update: {ie}")
            raise ie
        except ToolNotFoundError as tnfe:
            logger.error(f"Tool not found during update: {tnfe}")
            raise tnfe
        except ToolNameConflictError as tnce:
            logger.error(f"Tool name conflict during update: {tnce}")
            raise tnce
        except Exception as ex:
            db.rollback()
            raise ToolError(f"Failed to update tool: {str(ex)}")

    async def _notify_tool_updated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool update.

        Args:
            tool: Tool updated
        """
        event = {
            "type": "tool_updated",
            "data": {"id": tool.id, "name": tool.name, "url": tool.url, "description": tool.description, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_activated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool activation.

        Args:
            tool: Tool activated
        """
        event = {
            "type": "tool_activated",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_deactivated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool deactivation.

        Args:
            tool: Tool deactivated
        """
        event = {
            "type": "tool_deactivated",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_deleted(self, tool_info: Dict[str, Any]) -> None:
        """
        Notify subscribers of tool deletion.

        Args:
            tool_info: Dictionary on tool deleted
        """
        event = {
            "type": "tool_deleted",
            "data": tool_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to tool events.

        Yields:
            Tool event messages.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    async def _notify_tool_added(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool addition.

        Args:
            tool: Tool added
        """
        event = {
            "type": "tool_added",
            "data": {
                "id": tool.id,
                "name": tool.name,
                "url": tool.url,
                "description": tool.description,
                "enabled": tool.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_removed(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool removal (soft delete/deactivation).

        Args:
            tool: Tool removed
        """
        event = {
            "type": "tool_removed",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers.

        Args:
            event: Event to publish
        """
        for queue in self._event_subscribers:
            await queue.put(event)

    async def _validate_tool_url(self, url: str) -> None:
        """Validate tool URL is accessible.

        Args:
            url: URL to validate.

        Raises:
            ToolValidationError: If URL validation fails.
        """
        try:
            response = await self._http_client.get(url)
            response.raise_for_status()
        except Exception as e:
            raise ToolValidationError(f"Failed to validate tool URL: {str(e)}")

    async def _check_tool_health(self, tool: DbTool) -> bool:
        """Check if tool endpoint is healthy.

        Args:
            tool: Tool to check.

        Returns:
            True if tool is healthy.
        """
        try:
            response = await self._http_client.get(tool.url)
            return response.is_success
        except Exception:
            return False

    async def event_generator(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Generate tool events for SSE.

        Yields:
            Tool events.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """
        Aggregate metrics for all tool invocations across all tools.

        Args:
            db: Database session

        Returns:
            Aggregated metrics computed from all ToolMetric records.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar.return_value = 0
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> isinstance(result, dict)
            True
        """

        total = db.execute(select(func.count(ToolMetric.id))).scalar() or 0  # pylint: disable=not-callable
        successful = db.execute(select(func.count(ToolMetric.id)).where(ToolMetric.is_success.is_(True))).scalar() or 0  # pylint: disable=not-callable
        failed = db.execute(select(func.count(ToolMetric.id)).where(ToolMetric.is_success.is_(False))).scalar() or 0  # pylint: disable=not-callable
        failure_rate = failed / total if total > 0 else 0.0
        min_rt = db.execute(select(func.min(ToolMetric.response_time))).scalar()
        max_rt = db.execute(select(func.max(ToolMetric.response_time))).scalar()
        avg_rt = db.execute(select(func.avg(ToolMetric.response_time))).scalar()
        last_time = db.execute(select(func.max(ToolMetric.timestamp))).scalar()

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failure_rate,
            "min_response_time": min_rt,
            "max_response_time": max_rt,
            "avg_response_time": avg_rt,
            "last_execution_time": last_time,
        }

    async def reset_metrics(self, db: Session, tool_id: Optional[int] = None) -> None:
        """
        Reset all tool metrics by deleting all records from the tool metrics table.

        Args:
            db: Database session
            tool_id: Optional tool ID to reset metrics for a specific tool

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> db.execute = MagicMock()
            >>> db.commit = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.reset_metrics(db))
        """

        if tool_id:
            db.execute(delete(ToolMetric).where(ToolMetric.tool_id == tool_id))
        else:
            db.execute(delete(ToolMetric))
        db.commit()

    async def create_tool_from_a2a_agent(
        self,
        db: Session,
        agent: DbA2AAgent,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
    ) -> ToolRead:
        """Create a tool entry from an A2A agent for virtual server integration.

        Args:
            db: Database session.
            agent: A2A agent to create tool from.
            created_by: Username who created this tool.
            created_from_ip: IP address of creator.
            created_via: Creation method.
            created_user_agent: User agent of creation request.

        Returns:
            The created tool.

        Raises:
            ToolNameConflictError: If a tool with the same name already exists.
        """
        # Check if tool already exists for this agent
        tool_name = f"a2a_{agent.slug}"
        existing_query = select(DbTool).where(DbTool.original_name == tool_name)
        existing_tool = db.execute(existing_query).scalar_one_or_none()

        if existing_tool:
            # Tool already exists, return it
            return self._convert_tool_to_read(existing_tool)

        # Create tool entry for the A2A agent
        tool_data = ToolCreate(
            name=tool_name,
            displayName=generate_display_name(agent.name),
            url=agent.endpoint_url,
            description=f"A2A Agent: {agent.description or agent.name}",
            integration_type="A2A",  # Special integration type for A2A agents
            request_type="POST",
            input_schema={
                "type": "object",
                "properties": {
                    "parameters": {"type": "object", "description": "Parameters to pass to the A2A agent"},
                    "interaction_type": {"type": "string", "description": "Type of interaction", "default": "query"},
                },
                "required": ["parameters"],
            },
            annotations={
                "title": f"A2A Agent: {agent.name}",
                "a2a_agent_id": agent.id,
                "a2a_agent_type": agent.agent_type,
            },
            auth_type=agent.auth_type,
            auth_value=agent.auth_value,
            tags=agent.tags + ["a2a", "agent"],
        )

        return await self.register_tool(
            db,
            tool_data,
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via or "a2a_integration",
            created_user_agent=created_user_agent,
        )

    async def _invoke_a2a_tool(self, db: Session, tool: DbTool, arguments: Dict[str, Any]) -> ToolResult:
        """Invoke an A2A agent through its corresponding tool.

        Args:
            db: Database session.
            tool: The tool record that represents the A2A agent.
            arguments: Tool arguments.

        Returns:
            Tool result from A2A agent invocation.

        Raises:
            ToolNotFoundError: If the A2A agent is not found.
        """
        # Extract A2A agent ID from tool annotations
        agent_id = tool.annotations.get("a2a_agent_id")
        if not agent_id:
            raise ToolNotFoundError(f"A2A tool '{tool.name}' missing agent ID in annotations")

        # Get the A2A agent
        agent_query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(agent_query).scalar_one_or_none()

        if not agent:
            raise ToolNotFoundError(f"A2A agent not found for tool '{tool.name}' (agent ID: {agent_id})")

        if not agent.enabled:
            raise ToolNotFoundError(f"A2A agent '{agent.name}' is disabled")

        # Prepare parameters for A2A invocation
        parameters = arguments.get("parameters", arguments)
        interaction_type = arguments.get("interaction_type", "query")

        start_time = time.time()
        success = False
        error_message = None

        try:
            # Make the A2A agent call
            response_data = await self._call_a2a_agent(agent, parameters, interaction_type)
            success = True

            # Convert A2A response to MCP ToolResult format
            if isinstance(response_data, dict) and "response" in response_data:
                content = [TextContent(type="text", text=str(response_data["response"]))]
            else:
                content = [TextContent(type="text", text=str(response_data))]

            result = ToolResult(content=content, is_error=False)

        except Exception as e:
            error_message = str(e)
            success = False
            content = [TextContent(type="text", text=f"A2A agent error: {error_message}")]
            result = ToolResult(content=content, is_error=True)

        finally:
            # Record metrics for the tool
            end_time = time.time()
            response_time = end_time - start_time

            metric = ToolMetric(
                tool_id=tool.id,
                response_time=response_time,
                is_success=success,
                error_message=error_message,
            )
            db.add(metric)
            db.commit()

        return result

    async def _call_a2a_agent(self, agent: DbA2AAgent, parameters: Dict[str, Any], interaction_type: str = "query") -> Dict[str, Any]:
        """Call an A2A agent directly.

        Args:
            agent: The A2A agent to call.
            parameters: Parameters for the interaction.
            interaction_type: Type of interaction.

        Returns:
            Response from the A2A agent.

        Raises:
            Exception: If the call fails.
        """
        # Format request based on agent type and endpoint
        if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
            # Use JSONRPC format for agents that expect it
            request_data = {"jsonrpc": "2.0", "method": parameters.get("method", "message/send"), "params": parameters.get("params", parameters), "id": 1}
        else:
            # Use custom A2A format
            request_data = {"interaction_type": interaction_type, "parameters": parameters, "protocol_version": agent.protocol_version}

        # Make HTTP request to the agent endpoint
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Content-Type": "application/json"}

            # Add authentication if configured
            if agent.auth_type == "api_key" and agent.auth_value:
                headers["Authorization"] = f"Bearer {agent.auth_value}"
            elif agent.auth_type == "bearer" and agent.auth_value:
                headers["Authorization"] = f"Bearer {agent.auth_value}"

            http_response = await client.post(agent.endpoint_url, json=request_data, headers=headers)

            if http_response.status_code == 200:
                return http_response.json()

            raise Exception(f"HTTP {http_response.status_code}: {http_response.text}")
