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
import base64
from datetime import datetime, timedelta, timezone
import os
import re
import ssl
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import httpx
import jq
import jsonschema
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
import orjson
from sqlalchemy import and_, case, delete, desc, Float, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.common.models import Gateway as PydanticGateway
from mcpgateway.common.models import TextContent
from mcpgateway.common.models import Tool as PydanticTool
from mcpgateway.common.models import ToolResult
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import EmailTeam, fresh_db_session, server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric
from mcpgateway.observability import create_span
from mcpgateway.plugins.framework import (
    GlobalContext,
    HttpHeaderPayload,
    PluginContextTable,
    PluginError,
    PluginManager,
    PluginViolationError,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA
from mcpgateway.schemas import ToolCreate, ToolRead, ToolUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import decode_cursor, encode_cursor
from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr
from mcpgateway.utils.validate_signature import validate_signature

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize performance tracker, structured logger, and audit trail for tool operations
perf_tracker = get_performance_tracker()
structured_logger = get_structured_logger("tool_service")
audit_trail = get_audit_trail_service()


def extract_using_jq(data, jq_filter=""):
    """
    Extracts data from a given input (string, dict, or list) using a jq filter string.

    Args:
        data (str, dict, list): The input JSON data. Can be a string, dict, or list.
        jq_filter (str): The jq filter string to extract the desired data.

    Returns:
        The result of applying the jq filter to the input data.

    Examples:
        >>> extract_using_jq('{"a": 1, "b": 2}', '.a')
        [1]
        >>> extract_using_jq({'a': 1, 'b': 2}, '.b')
        [2]
        >>> extract_using_jq('[{"a": 1}, {"a": 2}]', '.[].a')
        [1, 2]
        >>> extract_using_jq('not a json', '.a')
        ['Invalid JSON string provided.']
        >>> extract_using_jq({'a': 1}, '')
        {'a': 1}
    """
    if jq_filter == "":
        return data
    if isinstance(data, str):
        # If the input is a string, parse it as JSON
        try:
            data = orjson.loads(data)
        except orjson.JSONDecodeError:
            return ["Invalid JSON string provided."]

    elif not isinstance(data, (dict, list)):
        # If the input is not a string, dict, or list, raise an error
        return ["Input data must be a JSON string, dictionary, or list."]

    # Apply the jq filter to the data
    try:
        # Pylint can't introspect C-extension modules, so it doesn't know that jq really does export an all() function.
        # pylint: disable=c-extension-no-member
        result = jq.all(jq_filter, data)  # Use `jq.all` to get all matches (returns a list)
        if result == [None]:
            result = "Error applying jsonpath filter"
    except Exception as e:
        message = "Error applying jsonpath filter: " + str(e)
        return message

    return result


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
            >>> isinstance(service._event_service, EventService)
            True
            >>> hasattr(service, '_http_client')
            True
        """
        self._event_service = EventService(channel_name="mcpgateway:tool_events")
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
        await self._event_service.initialize()

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> import asyncio
            >>> asyncio.run(service.shutdown())  # Should log "Tool service shutdown complete"
        """
        await self._http_client.aclose()
        await self._event_service.shutdown()
        logger.info("Tool service shutdown complete")

    async def get_top_tools(self, db: Session, limit: Optional[int] = 5) -> List[TopPerformer]:
        """Retrieve the top-performing tools based on execution count.

        Queries the database to get tools with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing tool details and
        performance metrics.

        Args:
            db (Session): Database session for querying tool metrics.
            limit (Optional[int]): Maximum number of tools to return. Defaults to 5. If None, returns all tools.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Tool ID.
                - name: Tool name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """

        success_rate = case(
            (func.count(ToolMetric.id) > 0, func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)).cast(Float) * 100 / func.count(ToolMetric.id)), else_=None  # pylint: disable=not-callable
        )

        query = (
            select(
                DbTool.id,
                DbTool.name,
                func.count(ToolMetric.id).label("execution_count"),  # pylint: disable=not-callable
                func.avg(ToolMetric.response_time).label("avg_response_time"),
                success_rate.label("success_rate"),
                func.max(ToolMetric.timestamp).label("last_execution"),
            )
            .outerjoin(ToolMetric, ToolMetric.tool_id == DbTool.id)
            .group_by(DbTool.id, DbTool.name)
            .order_by(desc("execution_count"))
            .limit(limit or 5)
        )

        results = db.execute(query).all()

        return build_top_performers(results)

    def _get_team_name(self, db: Session, team_id: Optional[str]) -> Optional[str]:
        """Retrieve the team name given a team ID.

        Args:
            db (Session): Database session for querying teams.
            team_id (Optional[str]): The ID of the team.

        Returns:
            Optional[str]: The name of the team if found, otherwise None.
        """
        if not team_id:
            return None
        team = db.query(EmailTeam).filter(EmailTeam.id == team_id, EmailTeam.is_active.is_(True)).first()
        return team.name if team else None

    def _convert_tool_to_read(self, tool: DbTool, include_metrics: bool = True, db: Optional[Session] = None) -> ToolRead:
        """Converts a DbTool instance into a ToolRead model, including aggregated metrics and
        new API gateway fields: request_type and authentication credentials (masked).

        Args:
            tool (DbTool): The ORM instance of the tool.
            include_metrics (bool): Whether to include metrics in the result. Defaults to True.
            db (Optional[Session]): Database session for SQL-based metrics computation.
                When provided, uses efficient SQL aggregation instead of loading all metric rows.

        Returns:
            ToolRead: The Pydantic model representing the tool, including aggregated metrics and new fields.
        """
        # NOTE: This serves two purposes:
        #   1. It determines whether to decode auth (used later)
        #   2. It forces the tool object to lazily evaluate (required before copy)
        auth_type_set = tool.auth_type and tool.auth_value

        # Copy the dict from the tool
        tool_dict = tool.__dict__.copy()
        tool_dict.pop("_sa_instance_state", None)

        if include_metrics and db is not None:
            # Use SQL aggregation to avoid loading all metric rows into memory
            try:
                tool_dict["metrics"] = DbTool.compute_metrics_summary(db, tool.id)
                tool_dict["execution_count"] = tool_dict["metrics"]["total_executions"]
            except Exception:
                # Fallback to ORM properties if SQL aggregation fails
                tool_dict["metrics"] = tool.metrics_summary
                tool_dict["execution_count"] = tool.execution_count
        elif include_metrics:
            tool_dict["metrics"] = tool.metrics_summary
            tool_dict["execution_count"] = tool.execution_count
        else:
            tool_dict["metrics"] = None
            tool_dict["execution_count"] = None

        tool_dict["request_type"] = tool.request_type
        tool_dict["annotations"] = tool.annotations or {}

        # Only decode auth if auth_type is set
        if auth_type_set:
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
                # Get first key
                first_key = next(iter(decoded_auth_value))
                tool_dict["auth"] = {
                    "auth_type": "authheaders",
                    "auth_header_key": first_key,
                    "auth_header_value": "********" if decoded_auth_value[first_key] else None,
                }
            else:
                tool_dict["auth"] = None
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
        tool_dict["team"] = getattr(tool, "team", None)

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

    def _record_tool_metric_by_id(
        self,
        db: Session,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Record tool metric using tool ID instead of ORM object.

        This method is designed to be used with a fresh database session after the main
        request session has been released. It avoids requiring the ORM tool object,
        which may have been detached from the session.

        Args:
            db: A fresh database session (not the request session).
            tool_id: The UUID string of the tool.
            start_time: The monotonic start time of the invocation.
            success: True if the invocation succeeded; otherwise, False.
            error_message: The error message if the invocation failed, otherwise None.
        """
        end_time = time.monotonic()
        response_time = end_time - start_time
        metric = ToolMetric(
            tool_id=tool_id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    def _record_tool_metric_sync(
        self,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Synchronous helper to record tool metrics with its own session.

        This method creates a fresh database session, records the metric, and closes
        the session. Designed to be called via asyncio.to_thread() to avoid blocking
        the event loop.

        Args:
            tool_id: The UUID string of the tool.
            start_time: The monotonic start time of the invocation.
            success: True if the invocation succeeded; otherwise, False.
            error_message: The error message if the invocation failed, otherwise None.
        """
        with fresh_db_session() as db_metrics:
            self._record_tool_metric_by_id(
                db_metrics,
                tool_id=tool_id,
                start_time=start_time,
                success=success,
                error_message=error_message,
            )

    def _extract_and_validate_structured_content(self, tool: DbTool, tool_result: "ToolResult", candidate: Optional[Any] = None) -> bool:
        """
        Extract structured content (if any) and validate it against ``tool.output_schema``.

        Args:
            tool: The tool with an optional output schema to validate against.
            tool_result: The tool result containing content to validate.
            candidate: Optional structured payload to validate. If not provided, will attempt
                      to parse the first TextContent item as JSON.

        Behavior:
        - If ``candidate`` is provided it is used as the structured payload to validate.
        - Otherwise the method will try to parse the first ``TextContent`` item in
            ``tool_result.content`` as JSON and use that as the candidate.
        - If no output schema is declared on the tool the method returns True (nothing to validate).
        - On successful validation the parsed value is attached to ``tool_result.structured_content``.
            When structured content is present and valid callers may drop textual ``content`` in favour
            of the structured payload.
        - On validation failure the method sets ``tool_result.content`` to a single ``TextContent``
            containing a compact JSON object describing the validation error, sets
            ``tool_result.is_error = True`` and returns False.

        Returns:
                True when the structured content is valid or when no schema is declared.
                False when validation fails.

        Examples:
                >>> from mcpgateway.services.tool_service import ToolService
                >>> from mcpgateway.common.models import TextContent, ToolResult
                >>> import json
                >>> service = ToolService()
                >>> # No schema declared -> nothing to validate
                >>> tool = type("T", (object,), {"output_schema": None})()
                >>> r = ToolResult(content=[TextContent(type="text", text='{"a":1}')])
                >>> service._extract_and_validate_structured_content(tool, r)
                True

                >>> # Valid candidate provided -> attaches structured_content and returns True
                >>> tool = type(
                ...     "T",
                ...     (object,),
                ...     {"output_schema": {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}},
                ... )()
                >>> r = ToolResult(content=[])
                >>> service._extract_and_validate_structured_content(tool, r, candidate={"foo": "bar"})
                True
                >>> r.structured_content == {"foo": "bar"}
                True

                >>> # Invalid candidate -> returns False, marks result as error and emits details
                >>> tool = type(
                ...     "T",
                ...     (object,),
                ...     {"output_schema": {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}},
                ... )()
                >>> r = ToolResult(content=[])
                >>> ok = service._extract_and_validate_structured_content(tool, r, candidate={"foo": 123})
                >>> ok
                False
                >>> r.is_error
                True
                >>> details = orjson.loads(r.content[0].text)
                >>> "received" in details
                True
        """
        try:
            output_schema = getattr(tool, "output_schema", None)
            # Nothing to do if the tool doesn't declare a schema
            if not output_schema:
                return True

            structured: Optional[Any] = None
            # Prefer explicit candidate
            if candidate is not None:
                structured = candidate
            else:
                # Try to parse first TextContent text payload as JSON
                for c in getattr(tool_result, "content", []) or []:
                    try:
                        if isinstance(c, dict) and "type" in c and c.get("type") == "text" and "text" in c:
                            structured = orjson.loads(c.get("text") or "null")
                            break
                    except (orjson.JSONDecodeError, TypeError, ValueError):
                        # ignore JSON parse errors and continue
                        continue

            # If no structured data found, treat as valid (nothing to validate)
            if structured is None:
                return True

            # Try to normalize common wrapper shapes to match schema expectations
            schema_type = None
            try:
                if isinstance(output_schema, dict):
                    schema_type = output_schema.get("type")
            except Exception:
                schema_type = None

            # Unwrap single-element list wrappers when schema expects object
            if isinstance(structured, list) and len(structured) == 1 and schema_type == "object":
                inner = structured[0]
                # If inner is a TextContent-like dict with 'text' JSON string, parse it
                if isinstance(inner, dict) and "text" in inner and "type" in inner and inner.get("type") == "text":
                    try:
                        structured = orjson.loads(inner.get("text") or "null")
                    except Exception:
                        # leave as-is if parsing fails
                        structured = inner
                else:
                    structured = inner

            # Attach structured content
            try:
                setattr(tool_result, "structured_content", structured)
            except Exception:
                logger.debug("Failed to set structured_content on ToolResult")

            # Validate using jsonschema
            try:
                jsonschema.validate(instance=structured, schema=output_schema)
                return True
            except jsonschema.exceptions.ValidationError as e:
                details = {
                    "code": getattr(e, "validator", "validation_error"),
                    "expected": e.schema.get("type") if isinstance(e.schema, dict) and "type" in e.schema else None,
                    "received": type(e.instance).__name__.lower() if e.instance is not None else None,
                    "path": list(e.absolute_path) if hasattr(e, "absolute_path") else list(e.path or []),
                    "message": e.message,
                }
                try:
                    tool_result.content = [TextContent(type="text", text=orjson.dumps(details).decode())]
                except Exception:
                    tool_result.content = [TextContent(type="text", text=str(details))]
                tool_result.is_error = True
                logger.debug(f"structured_content validation failed for tool {getattr(tool, 'name', '<unknown>')}: {details}")
                return False
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Error extracting/validating structured_content: {exc}")
            return False

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
                visibility = tool.visibility or "public"
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
                output_schema=tool.output_schema,
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
                # passthrough REST tools fields
                base_url=tool.base_url if tool.integration_type == "REST" else None,
                path_template=tool.path_template if tool.integration_type == "REST" else None,
                query_mapping=tool.query_mapping if tool.integration_type == "REST" else None,
                header_mapping=tool.header_mapping if tool.integration_type == "REST" else None,
                timeout_ms=tool.timeout_ms if tool.integration_type == "REST" else None,
                expose_passthrough=(tool.expose_passthrough if tool.integration_type == "REST" and tool.expose_passthrough is not None else True) if tool.integration_type == "REST" else None,
                allowlist=tool.allowlist if tool.integration_type == "REST" else None,
                plugin_chain_pre=tool.plugin_chain_pre if tool.integration_type == "REST" else None,
                plugin_chain_post=tool.plugin_chain_post if tool.integration_type == "REST" else None,
            )
            db.add(db_tool)
            db.commit()
            db.refresh(db_tool)
            await self._notify_tool_added(db_tool)

            # Structured logging: Audit trail for tool creation
            audit_trail.log_action(
                user_id=created_by or "system",
                action="create_tool",
                resource_type="tool",
                resource_id=db_tool.id,
                resource_name=db_tool.name,
                user_email=owner_email,
                team_id=team_id,
                client_ip=created_from_ip,
                user_agent=created_user_agent,
                new_values={
                    "name": db_tool.name,
                    "display_name": db_tool.display_name,
                    "visibility": visibility,
                    "integration_type": db_tool.integration_type,
                },
                context={
                    "created_via": created_via,
                    "import_batch_id": import_batch_id,
                    "federation_source": federation_source,
                },
                db=db,
            )

            # Structured logging: Log successful tool creation
            structured_logger.log(
                level="INFO",
                message="Tool created successfully",
                event_type="tool_created",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="tool",
                resource_id=db_tool.id,
                custom_fields={
                    "tool_name": db_tool.name,
                    "visibility": visibility,
                    "integration_type": db_tool.integration_type,
                },
                db=db,
            )

            # Refresh db_tool after logging commits (they expire the session objects)
            db.refresh(db_tool)
            return self._convert_tool_to_read(db_tool, db=db)
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityError during tool registration: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Tool creation failed due to database integrity error",
                event_type="tool_creation_failed",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                error=ie,
                custom_fields={
                    "tool_name": tool.name,
                },
                db=db,
            )
            raise ie
        except ToolNameConflictError as tnce:
            db.rollback()
            logger.error(f"ToolNameConflictError during tool registration: {tnce}")

            # Structured logging: Log name conflict error
            structured_logger.log(
                level="WARNING",
                message="Tool creation failed due to name conflict",
                event_type="tool_name_conflict",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={
                    "tool_name": tool.name,
                    "visibility": visibility,
                },
                db=db,
            )
            raise tnce
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool creation failure
            structured_logger.log(
                level="ERROR",
                message="Tool creation failed",
                event_type="tool_creation_failed",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                error=e,
                custom_fields={
                    "tool_name": tool.name,
                },
                db=db,
            )
            raise ToolError(f"Failed to register tool: {str(e)}")

    async def register_tools_bulk(
        self,
        db: Session,
        tools: List[ToolCreate],
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
        conflict_strategy: str = "skip",
    ) -> Dict[str, Any]:
        """Register multiple tools in bulk with a single commit.

        This method provides significant performance improvements over individual
        tool registration by:
        - Using db.add_all() instead of individual db.add() calls
        - Performing a single commit for all tools
        - Batch conflict detection
        - Chunking for very large imports (>500 items)

        Args:
            db: Database session
            tools: List of tool creation schemas
            created_by: Username who created these tools
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, import, federation)
            created_user_agent: User agent of creation request
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated tools
            team_id: Team ID to assign the tools to
            owner_email: Email of the user who owns these tools
            visibility: Tool visibility level (private, team, public)
            conflict_strategy: How to handle conflicts (skip, update, rename, fail)

        Returns:
            Dict with statistics:
                - created: Number of tools created
                - updated: Number of tools updated
                - skipped: Number of tools skipped
                - failed: Number of tools that failed
                - errors: List of error messages

        Raises:
            ToolError: If bulk registration fails critically

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tools = [MagicMock(), MagicMock()]
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.register_tools_bulk(db, tools))
            ... except Exception:
            ...     pass
        """
        if not tools:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        # Process in chunks to avoid memory issues and SQLite parameter limits
        chunk_size = 500

        for chunk_start in range(0, len(tools), chunk_size):
            chunk = tools[chunk_start : chunk_start + chunk_size]
            chunk_stats = self._process_tool_chunk(
                db=db,
                chunk=chunk,
                conflict_strategy=conflict_strategy,
                visibility=visibility,
                team_id=team_id,
                owner_email=owner_email,
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
            )

            # Aggregate stats
            for key, value in chunk_stats.items():
                if key == "errors":
                    stats[key].extend(value)
                else:
                    stats[key] += value

        return stats

    def _process_tool_chunk(
        self,
        db: Session,
        chunk: List[ToolCreate],
        conflict_strategy: str,
        visibility: str,
        team_id: Optional[int],
        owner_email: Optional[str],
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> dict:
        """Process a chunk of tools for bulk import.

        Args:
            db: The SQLAlchemy database session.
            chunk: List of ToolCreate objects to process.
            conflict_strategy: Strategy for handling conflicts ("skip", "update", or "fail").
            visibility: Tool visibility level ("public", "team", or "private").
            team_id: Team ID for team-scoped tools.
            owner_email: Email of the tool owner.
            created_by: Email of the user creating the tools.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            dict: Statistics dictionary with keys "created", "updated", "skipped", "failed", and "errors".
        """
        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        try:
            # Batch check for existing tools to detect conflicts
            tool_names = [tool.name for tool in chunk]

            if visibility.lower() == "public":
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "public")
            elif visibility.lower() == "team" and team_id:
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "team", DbTool.team_id == team_id)
            else:
                # Private tools - check by owner
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "private", DbTool.owner_email == (owner_email or created_by))

            existing_tools = db.execute(existing_tools_query).scalars().all()
            existing_tools_map = {tool.name: tool for tool in existing_tools}

            tools_to_add = []
            tools_to_update = []

            for tool in chunk:
                result = self._process_single_tool_for_bulk(
                    tool=tool,
                    existing_tools_map=existing_tools_map,
                    conflict_strategy=conflict_strategy,
                    visibility=visibility,
                    team_id=team_id,
                    owner_email=owner_email,
                    created_by=created_by,
                    created_from_ip=created_from_ip,
                    created_via=created_via,
                    created_user_agent=created_user_agent,
                    import_batch_id=import_batch_id,
                    federation_source=federation_source,
                )

                if result["status"] == "add":
                    tools_to_add.append(result["tool"])
                    stats["created"] += 1
                elif result["status"] == "update":
                    tools_to_update.append(result["tool"])
                    stats["updated"] += 1
                elif result["status"] == "skip":
                    stats["skipped"] += 1
                elif result["status"] == "fail":
                    stats["failed"] += 1
                    stats["errors"].append(result["error"])

            # Bulk add new tools
            if tools_to_add:
                db.add_all(tools_to_add)

            # Commit the chunk
            db.commit()

            # Refresh tools for notifications and audit trail
            for db_tool in tools_to_add:
                db.refresh(db_tool)
                # Notify subscribers (sync call in async context handled by caller)

            # Log bulk audit trail entry
            if tools_to_add or tools_to_update:
                audit_trail.log_action(
                    user_id=created_by or "system",
                    action="bulk_create_tools" if tools_to_add else "bulk_update_tools",
                    resource_type="tool",
                    resource_id=None,
                    details={"count": len(tools_to_add) + len(tools_to_update), "import_batch_id": import_batch_id},
                    db=db,
                )

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to process tool chunk: {str(e)}")
            stats["failed"] += len(chunk)
            stats["errors"].append(f"Chunk processing failed: {str(e)}")

        return stats

    def _process_single_tool_for_bulk(
        self,
        tool: ToolCreate,
        existing_tools_map: dict,
        conflict_strategy: str,
        visibility: str,
        team_id: Optional[int],
        owner_email: Optional[str],
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> dict:
        """Process a single tool for bulk import.

        Args:
            tool: ToolCreate object to process.
            existing_tools_map: Dictionary mapping tool names to existing DbTool objects.
            conflict_strategy: Strategy for handling conflicts ("skip", "update", or "fail").
            visibility: Tool visibility level ("public", "team", or "private").
            team_id: Team ID for team-scoped tools.
            owner_email: Email of the tool owner.
            created_by: Email of the user creating the tool.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            dict: Result dictionary with "status" key ("add", "update", "skip", or "fail")
                and either "tool" (DbTool object) or "error" (error message).
        """
        try:
            # Extract auth information
            if tool.auth is None:
                auth_type = None
                auth_value = None
            else:
                auth_type = tool.auth.auth_type
                auth_value = tool.auth.auth_value

            # Use provided parameters or schema values
            tool_team_id = team_id if team_id is not None else getattr(tool, "team_id", None)
            tool_owner_email = owner_email or getattr(tool, "owner_email", None) or created_by
            tool_visibility = visibility if visibility is not None else getattr(tool, "visibility", "public")

            existing_tool = existing_tools_map.get(tool.name)

            if existing_tool:
                # Handle conflict based on strategy
                if conflict_strategy == "skip":
                    return {"status": "skip"}
                if conflict_strategy == "update":
                    # Update existing tool
                    existing_tool.display_name = tool.displayName or tool.name
                    existing_tool.url = str(tool.url)
                    existing_tool.description = tool.description
                    existing_tool.integration_type = tool.integration_type
                    existing_tool.request_type = tool.request_type
                    existing_tool.headers = tool.headers
                    existing_tool.input_schema = tool.input_schema
                    existing_tool.output_schema = tool.output_schema
                    existing_tool.annotations = tool.annotations
                    existing_tool.jsonpath_filter = tool.jsonpath_filter
                    existing_tool.auth_type = auth_type
                    existing_tool.auth_value = auth_value
                    existing_tool.tags = tool.tags or []
                    existing_tool.modified_by = created_by
                    existing_tool.modified_from_ip = created_from_ip
                    existing_tool.modified_via = created_via
                    existing_tool.modified_user_agent = created_user_agent
                    existing_tool.updated_at = datetime.now(timezone.utc)
                    existing_tool.version = (existing_tool.version or 1) + 1

                    # Update REST-specific fields if applicable
                    if tool.integration_type == "REST":
                        existing_tool.base_url = tool.base_url
                        existing_tool.path_template = tool.path_template
                        existing_tool.query_mapping = tool.query_mapping
                        existing_tool.header_mapping = tool.header_mapping
                        existing_tool.timeout_ms = tool.timeout_ms
                        existing_tool.expose_passthrough = tool.expose_passthrough if tool.expose_passthrough is not None else True
                        existing_tool.allowlist = tool.allowlist
                        existing_tool.plugin_chain_pre = tool.plugin_chain_pre
                        existing_tool.plugin_chain_post = tool.plugin_chain_post

                    return {"status": "update", "tool": existing_tool}

                if conflict_strategy == "rename":
                    # Create with renamed tool
                    new_name = f"{tool.name}_imported_{int(datetime.now().timestamp())}"
                    db_tool = self._create_tool_object(
                        tool,
                        new_name,
                        auth_type,
                        auth_value,
                        tool_team_id,
                        tool_owner_email,
                        tool_visibility,
                        created_by,
                        created_from_ip,
                        created_via,
                        created_user_agent,
                        import_batch_id,
                        federation_source,
                    )
                    return {"status": "add", "tool": db_tool}

                if conflict_strategy == "fail":
                    return {"status": "fail", "error": f"Tool name conflict: {tool.name}"}

            # Create new tool
            db_tool = self._create_tool_object(
                tool,
                tool.name,
                auth_type,
                auth_value,
                tool_team_id,
                tool_owner_email,
                tool_visibility,
                created_by,
                created_from_ip,
                created_via,
                created_user_agent,
                import_batch_id,
                federation_source,
            )
            return {"status": "add", "tool": db_tool}

        except Exception as e:
            logger.warning(f"Failed to process tool {tool.name} in bulk operation: {str(e)}")
            return {"status": "fail", "error": f"Failed to process tool {tool.name}: {str(e)}"}

    def _create_tool_object(
        self,
        tool: ToolCreate,
        name: str,
        auth_type: Optional[str],
        auth_value: Optional[str],
        tool_team_id: Optional[int],
        tool_owner_email: Optional[str],
        tool_visibility: str,
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> DbTool:
        """Create a DbTool object from ToolCreate schema.

        Args:
            tool: ToolCreate schema object containing tool data.
            name: Name of the tool.
            auth_type: Authentication type for the tool.
            auth_value: Authentication value/credentials for the tool.
            tool_team_id: Team ID for team-scoped tools.
            tool_owner_email: Email of the tool owner.
            tool_visibility: Tool visibility level ("public", "team", or "private").
            created_by: Email of the user creating the tool.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            DbTool: Database model instance ready to be added to the session.
        """
        return DbTool(
            original_name=name,
            custom_name=name,
            custom_name_slug=slugify(name),
            display_name=tool.displayName or name,
            url=str(tool.url),
            description=tool.description,
            integration_type=tool.integration_type,
            request_type=tool.request_type,
            headers=tool.headers,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            annotations=tool.annotations,
            jsonpath_filter=tool.jsonpath_filter,
            auth_type=auth_type,
            auth_value=auth_value,
            gateway_id=tool.gateway_id,
            tags=tool.tags or [],
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via,
            created_user_agent=created_user_agent,
            import_batch_id=import_batch_id,
            federation_source=federation_source,
            version=1,
            team_id=tool_team_id,
            owner_email=tool_owner_email,
            visibility=tool_visibility,
            base_url=tool.base_url if tool.integration_type == "REST" else None,
            path_template=tool.path_template if tool.integration_type == "REST" else None,
            query_mapping=tool.query_mapping if tool.integration_type == "REST" else None,
            header_mapping=tool.header_mapping if tool.integration_type == "REST" else None,
            timeout_ms=tool.timeout_ms if tool.integration_type == "REST" else None,
            expose_passthrough=((tool.expose_passthrough if tool.integration_type == "REST" and tool.expose_passthrough is not None else True) if tool.integration_type == "REST" else None),
            allowlist=tool.allowlist if tool.integration_type == "REST" else None,
            plugin_chain_pre=tool.plugin_chain_pre if tool.integration_type == "REST" else None,
            plugin_chain_post=tool.plugin_chain_post if tool.integration_type == "REST" else None,
        )

    async def list_tools(
        self,
        db: Session,
        include_inactive: bool = False,
        cursor: Optional[str] = None,
        tags: Optional[List[str]] = None,
        gateway_id: Optional[str] = None,
        limit: Optional[int] = None,
        _request_headers: Optional[Dict[str, str]] = None,
    ) -> tuple[List[ToolRead], Optional[str]]:
        """
        Retrieve a list of registered tools from the database with pagination support.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination.
                Opaque base64-encoded string containing last item's ID.
            tags (Optional[List[str]]): Filter tools by tags. If provided, only tools with at least one matching tag will be returned.
            gateway_id (Optional[str]): Filter tools by gateway ID. Accepts the literal value 'null' to match NULL gateway_id.
            limit (Optional[int]): Maximum number of tools to return. Use 0 for all tools (no limit).
                If not specified, uses pagination_default_page_size.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.

        Returns:
            tuple[List[ToolRead], Optional[str]]: Tuple containing:
                - List of tools for current page
                - Next cursor token if more results exist, None otherwise

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service._convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> tools, next_cursor = asyncio.run(service.list_tools(db))
            >>> isinstance(tools, list)
            True
        """
        # Determine page size based on limit parameter
        # limit=None: use default, limit=0: no limit (all), limit>0: use specified (capped)
        if limit is None:
            page_size = settings.pagination_default_page_size
        elif limit == 0:
            page_size = None  # No limit - fetch all
        else:
            page_size = min(limit, settings.pagination_max_page_size)

        # Decode cursor to get last_id if provided
        last_id = None
        if cursor:
            try:
                cursor_data = decode_cursor(cursor)
                last_id = cursor_data.get("id")
                logger.debug(f"Decoded cursor: last_id={last_id}")
            except ValueError as e:
                logger.warning(f"Invalid cursor, ignoring: {e}")

        logger.debug(
            "Listing tools with include_inactive=%s, cursor=%s, tags=%s, gateway_id=%s, page_size=%s",
            include_inactive,
            cursor,
            tags,
            gateway_id,
            page_size,
        )

        # Build query with LEFT JOIN for team names in single query instead of batch fetching
        query = select(DbTool, EmailTeam.name.label("team_name")).outerjoin(EmailTeam, and_(DbTool.team_id == EmailTeam.id, EmailTeam.is_active.is_(True))).order_by(DbTool.id)

        # Apply cursor filter (WHERE id > last_id)
        if last_id:
            query = query.where(DbTool.id > last_id)

        if not include_inactive:
            query = query.where(DbTool.enabled)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbTool.tags, tags, match_any=True))

        if gateway_id:
            if gateway_id.lower() == "null":
                query = query.where(DbTool.gateway_id.is_(None))
            else:
                query = query.where(DbTool.gateway_id == gateway_id)

        # Fetch page_size + 1 to determine if there are more results (unless no limit)
        if page_size is not None:
            query = query.limit(page_size + 1)
        rows = db.execute(query).all()

        # Check if there are more results (only when paginating)
        has_more = page_size is not None and len(rows) > page_size
        if has_more:
            rows = rows[:page_size]  # Trim to page_size

        # Convert to ToolRead objects with team names from join result
        result = []
        tools = []
        for row in rows:
            tool, team_name = row[0], row.team_name
            tool.team = team_name
            tools.append(tool)
            result.append(self._convert_tool_to_read(tool, include_metrics=False))

        # Generate next_cursor if there are more results
        next_cursor = None
        if has_more and result:
            last_tool = tools[-1]  # Get last DB object (not ToolRead)
            next_cursor = encode_cursor({"id": last_tool.id})
            logger.debug(f"Generated next_cursor for id={last_tool.id}")

        return (result, next_cursor)

    async def list_server_tools(
        self, db: Session, server_id: str, include_inactive: bool = False, include_metrics: bool = False, cursor: Optional[str] = None, _request_headers: Optional[Dict[str, str]] = None
    ) -> List[ToolRead]:
        """
        Retrieve a list of registered tools from the database.

        Args:
            db (Session): The SQLAlchemy database session.
            server_id (str): Server ID
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            include_metrics (bool): If True, all tool metrics included in result otherwise null.
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

        query = select(DbTool).options(joinedload(DbTool.gateway)).join(server_tool_association, DbTool.id == server_tool_association.c.tool_id).where(server_tool_association.c.server_id == server_id)

        cursor = None  # Placeholder for pagination; ignore for now
        logger.debug(f"Listing server tools for server_id={server_id} with include_inactive={include_inactive}, cursor={cursor}")

        if not include_inactive:
            query = query.where(DbTool.enabled)

        # Execute the query with LEFT JOIN for team names in single query
        query_with_join = query.outerjoin(EmailTeam, and_(DbTool.team_id == EmailTeam.id, EmailTeam.is_active.is_(True))).add_columns(EmailTeam.name.label("team_name"))

        rows = db.execute(query_with_join).all()

        # Add team names to tools based on join result
        result = []
        for row in rows:
            tool = row[0]
            team_name = row.team_name
            tool.team = team_name
            if include_metrics:
                # Use SQL aggregation for metrics instead of loading all metric rows
                result.append(self._convert_tool_to_read(tool, include_metrics=True, db=db))
            else:
                result.append(self._convert_tool_to_read(tool, include_metrics=False))

        return result

    async def list_tools_for_user(
        self,
        db: Session,
        user_email: str,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        include_inactive: bool = False,
        _skip: int = 0,
        _limit: int = 100,
        *,
        cursor: Optional[str] = None,
        gateway_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> tuple[List[ToolRead], Optional[str]]:
        """
        List tools user has access to with team filtering and cursor pagination.

        Args:
            db: Database session
            user_email: Email of the user requesting tools
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive tools
            _skip: Number of tools to skip for pagination (deprecated)
            _limit: Maximum number of tools to return (deprecated)
            cursor: Opaque cursor token for pagination
            gateway_id: Filter tools by gateway ID. Accepts literal 'null' for NULL gateway_id.
            tags: Filter tools by tags (match any)
            limit: Maximum number of tools to return. Use 0 for all tools (no limit).
                If not specified, uses pagination_default_page_size.

        Returns:
            tuple[List[ToolRead], Optional[str]]: Tools the user has access to and optional next_cursor
        """
        # Determine page size based on limit parameter
        # limit=None: use default, limit=0: no limit (all), limit>0: use specified (capped)
        if limit is None:
            page_size = settings.pagination_default_page_size
        elif limit == 0:
            page_size = None  # No limit - fetch all
        else:
            page_size = min(limit, settings.pagination_max_page_size)

        # Decode cursor to get last_id if provided
        last_id = None
        if cursor:
            try:
                cursor_data = decode_cursor(cursor)
                last_id = cursor_data.get("id")
                logger.debug(f"Decoded cursor: last_id={last_id}")
            except ValueError as e:
                logger.warning(f"Invalid cursor, ignoring: {e}")

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
                return ([], None)  # No access to team

            access_conditions = [
                and_(DbTool.team_id == team_id, DbTool.visibility.in_(["team", "public"])),
                and_(DbTool.team_id == team_id, DbTool.owner_email == user_email),
            ]
            query = query.where(or_(*access_conditions))
        else:
            access_conditions = [
                DbTool.owner_email == user_email,
                DbTool.visibility == "public",
            ]
            if team_ids:
                access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbTool.visibility == visibility)

        if gateway_id:
            if gateway_id.lower() == "null":
                query = query.where(DbTool.gateway_id.is_(None))
            else:
                query = query.where(DbTool.gateway_id == gateway_id)

        if tags:
            query = query.where(json_contains_expr(db, DbTool.tags, tags, match_any=True))

        # Apply cursor filter (WHERE id > last_id)
        if last_id:
            query = query.where(DbTool.id > last_id)

        query = query.order_by(DbTool.id)

        # Execute query with LEFT JOIN for team names in single query
        query_with_join = query.outerjoin(EmailTeam, and_(DbTool.team_id == EmailTeam.id, EmailTeam.is_active.is_(True))).add_columns(EmailTeam.name.label("team_name"))
        if page_size is not None:
            rows = db.execute(query_with_join.limit(page_size + 1)).all()
        else:
            rows = db.execute(query_with_join).all()

        # Check if there are more results (only when paginating)
        has_more = page_size is not None and len(rows) > page_size
        if has_more:
            rows = rows[:page_size]

        # Convert to ToolRead objects with team names from join result
        result = []
        tools = []
        for row in rows:
            tool = row[0]
            team_name = row.team_name
            tool.team = team_name
            tools.append(tool)
            result.append(self._convert_tool_to_read(tool, include_metrics=False))

        next_cursor = None
        if has_more and tools:
            last_tool = tools[-1]
            next_cursor = encode_cursor({"id": last_tool.id})

        return (result, next_cursor)

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
        tool.team = self._get_team_name(db, getattr(tool, "team_id", None))

        tool_read = self._convert_tool_to_read(tool, db=db)

        structured_logger.log(
            level="INFO",
            message="Tool retrieved successfully",
            event_type="tool_viewed",
            component="tool_service",
            team_id=getattr(tool, "team_id", None),
            resource_type="tool",
            resource_id=str(tool.id),
            custom_fields={
                "tool_name": tool.name,
                "include_metrics": bool(getattr(tool_read, "metrics", {})),
            },
            db=db,
        )

        return tool_read

    async def delete_tool(self, db: Session, tool_id: str, user_email: Optional[str] = None) -> None:
        """
        Delete a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            user_email (Optional[str]): Email of user performing delete (for ownership check).

        Raises:
            ToolNotFoundError: If the tool is not found.
            PermissionError: If user doesn't own the tool.
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

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can delete this tool")

            tool_info = {"id": tool.id, "name": tool.name}
            tool_name = tool.name
            tool_team_id = tool.team_id

            db.delete(tool)
            db.commit()
            await self._notify_tool_deleted(tool_info)
            logger.info(f"Permanently deleted tool: {tool_info['name']}")

            # Structured logging: Audit trail for tool deletion
            audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_tool",
                resource_type="tool",
                resource_id=tool_info["id"],
                resource_name=tool_name,
                user_email=user_email,
                team_id=tool_team_id,
                old_values={
                    "name": tool_name,
                },
                db=db,
            )

            # Structured logging: Log successful tool deletion
            structured_logger.log(
                level="INFO",
                message="Tool deleted successfully",
                event_type="tool_deleted",
                component="tool_service",
                user_email=user_email,
                team_id=tool_team_id,
                resource_type="tool",
                resource_id=tool_info["id"],
                custom_fields={
                    "tool_name": tool_name,
                },
                db=db,
            )
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool deletion failed due to permission error",
                event_type="tool_delete_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=pe,
                db=db,
            )
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool deletion failure
            structured_logger.log(
                level="ERROR",
                message="Tool deletion failed",
                event_type="tool_deletion_failed",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
                db=db,
            )
            raise ToolError(f"Failed to delete tool: {str(e)}")

    async def toggle_tool_status(self, db: Session, tool_id: str, activate: bool, reachable: bool, user_email: Optional[str] = None) -> ToolRead:
        """
        Toggle the activation status of a tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            activate (bool): True to activate, False to deactivate.
            reachable (bool): True if the tool is reachable.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            ToolRead: The updated tool object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            ToolError: For other errors.
            PermissionError: If user doesn't own the agent.

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

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can activate the Tool" if activate else "Only the owner can deactivate the Tool")

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

                if not tool.enabled:
                    # Inactive
                    await self._notify_tool_deactivated(tool)
                elif tool.enabled and not tool.reachable:
                    # Offline
                    await self._notify_tool_offline(tool)
                else:
                    # Active
                    await self._notify_tool_activated(tool)

                logger.info(f"Tool: {tool.name} is {'enabled' if activate else 'disabled'}{' and accessible' if reachable else ' but inaccessible'}")

                # Structured logging: Audit trail for tool status toggle
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="toggle_tool_status",
                    resource_type="tool",
                    resource_id=tool.id,
                    resource_name=tool.name,
                    user_email=user_email,
                    team_id=tool.team_id,
                    new_values={
                        "enabled": tool.enabled,
                        "reachable": tool.reachable,
                    },
                    context={
                        "action": "activate" if activate else "deactivate",
                    },
                    db=db,
                )

                # Structured logging: Log successful tool status toggle
                structured_logger.log(
                    level="INFO",
                    message=f"Tool {'activated' if activate else 'deactivated'} successfully",
                    event_type="tool_status_toggled",
                    component="tool_service",
                    user_email=user_email,
                    team_id=tool.team_id,
                    resource_type="tool",
                    resource_id=tool.id,
                    custom_fields={
                        "tool_name": tool.name,
                        "enabled": tool.enabled,
                        "reachable": tool.reachable,
                    },
                    db=db,
                )

            return self._convert_tool_to_read(tool, db=db)
        except PermissionError as e:
            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool status toggle failed due to permission error",
                event_type="tool_toggle_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
                db=db,
            )
            raise e
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool status toggle failure
            structured_logger.log(
                level="ERROR",
                message="Tool status toggle failed",
                event_type="tool_toggle_failed",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
                db=db,
            )
            raise ToolError(f"Failed to toggle tool status: {str(e)}")

    async def invoke_tool(
        self,
        db: Session,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Optional[Dict[str, str]] = None,
        app_user_email: Optional[str] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
    ) -> ToolResult:
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
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.

        Returns:
            Tool invocation result.

        Raises:
            ToolNotFoundError: If tool not found.
            ToolInvocationError: If invocation fails.
            PluginViolationError: If plugin blocks tool invocation.
            PluginError: If encounters issue with plugin

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, patch
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.side_effect = [tool, None]
            >>> tool.reachable = True
            >>> import asyncio
            >>> # Mock structured_logger to prevent database writes during doctest
            >>> with patch('mcpgateway.services.tool_service.structured_logger'):
            ...     result = asyncio.run(service.invoke_tool(db, 'tool_name', {}))
            ...     isinstance(result, object)
            True
        """
        # pylint: disable=comparison-with-callable
        logger.info(f"Invoking tool: {name} with arguments: {arguments.keys() if arguments else None} and headers: {request_headers.keys() if request_headers else None}")

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Fetch all required data with eager loading to minimize DB queries
        # ═══════════════════════════════════════════════════════════════════════════

        # Eager load tool WITH gateway in single query to prevent lazy load N+1
        tool = db.execute(select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.name == name).where(DbTool.enabled)).scalar_one_or_none()
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
            return await self._invoke_a2a_tool(db=db, tool=tool, arguments=arguments)

        # Get passthrough headers from in-memory cache (Issue #1715)
        # This eliminates 42,000+ redundant DB queries under load
        passthrough_allowed = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)

        # Access gateway now (already eager-loaded) to prevent later lazy load
        gateway = tool.gateway

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 2: Extract all needed data to local variables before network I/O
        # This allows us to release the DB session before making HTTP calls
        # ═══════════════════════════════════════════════════════════════════════════

        tool_id = str(tool.id)
        tool_name_original = tool.original_name
        tool_name_computed = tool.name
        tool_url = tool.url
        tool_integration_type = tool.integration_type
        tool_request_type = tool.request_type
        tool_headers = dict(tool.headers) if tool.headers else {}
        tool_auth_type = tool.auth_type
        tool_auth_value = tool.auth_value
        tool_jsonpath_filter = tool.jsonpath_filter
        tool_output_schema = tool.output_schema
        tool_oauth_config = getattr(tool, "oauth_config", None)
        tool_gateway_id = tool.gateway_id

        # Save gateway existence as local boolean BEFORE db.close()
        # to avoid checking ORM object truthiness after session is closed
        has_gateway = gateway is not None
        gateway_url = gateway.url if has_gateway else None
        gateway_name = gateway.name if has_gateway else None
        gateway_auth_type = gateway.auth_type if has_gateway else None
        gateway_auth_value = gateway.auth_value if has_gateway else None
        gateway_oauth_config = gateway.oauth_config if has_gateway else None
        gateway_ca_cert = gateway.ca_certificate if has_gateway else None
        gateway_ca_cert_sig = gateway.ca_certificate_sig if has_gateway else None
        gateway_passthrough = gateway.passthrough_headers if has_gateway else None
        gateway_id_str = str(gateway.id) if has_gateway else None

        # Create Pydantic models for plugins BEFORE HTTP calls (use ORM objects while still valid)
        # This prevents lazy loading during HTTP calls
        tool_metadata: Optional[PydanticTool] = None
        gateway_metadata: Optional[PydanticGateway] = None
        if self._plugin_manager:
            tool_metadata = PydanticTool.model_validate(tool)
            if has_gateway:
                gateway_metadata = PydanticGateway.model_validate(gateway)

        # ═══════════════════════════════════════════════════════════════════════════
        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents connection pool exhaustion during slow upstream requests.
        # All needed data has been extracted to local variables above.
        # The session will be closed again by FastAPI's get_db() finally block (safe no-op).
        # ═══════════════════════════════════════════════════════════════════════════
        db.rollback()  # End the transaction so connection returns to "idle" not "idle in transaction"
        db.close()

        # Plugin hook: tool pre-invoke
        # Use existing context_table from previous hooks if available
        context_table = plugin_context_table

        # Reuse existing global_context from middleware or create new one
        # IMPORTANT: Use local variables (tool_gateway_id) instead of ORM object access
        if plugin_global_context:
            global_context = plugin_global_context
            # Update server_id using local variable (not ORM access)
            if tool_gateway_id and isinstance(tool_gateway_id, str):
                global_context.server_id = tool_gateway_id
            # Propagate user email to global context for plugin access
            if app_user_email and isinstance(app_user_email, str):
                global_context.user = app_user_email
        else:
            # Create new context (fallback when middleware didn't run)
            # Use correlation ID from context if available, otherwise generate new one
            request_id = get_correlation_id() or uuid.uuid4().hex
            server_id = tool_gateway_id if tool_gateway_id and isinstance(tool_gateway_id, str) else "unknown"
            global_context = GlobalContext(request_id=request_id, server_id=server_id, tenant_id=None, user=app_user_email)

        start_time = time.monotonic()
        success = False
        error_message = None

        # Create a trace span for the tool invocation (using local variables)
        with create_span(
            "tool.invoke",
            {
                "tool.name": name,
                "tool.id": tool_id,
                "tool.integration_type": tool_integration_type,
                "tool.gateway_id": tool_gateway_id,
                "arguments_count": len(arguments) if arguments else 0,
                "has_headers": bool(request_headers),
            },
        ) as span:
            try:
                # Get combined headers for the tool including base headers, auth, and passthrough headers
                headers = tool_headers.copy()
                if tool_integration_type == "REST":
                    # Handle OAuth authentication for REST tools
                    if tool_auth_type == "oauth" and tool_oauth_config:
                        try:
                            access_token = await self.oauth_manager.get_access_token(tool_oauth_config)
                            headers["Authorization"] = f"Bearer {access_token}"
                        except Exception as e:
                            logger.error(f"Failed to obtain OAuth access token for tool {tool_name_computed}: {e}")
                            raise ToolInvocationError(f"OAuth authentication failed: {str(e)}")
                    else:
                        credentials = decode_auth(tool_auth_value)
                        # Filter out empty header names/values to avoid "Illegal header name" errors
                        filtered_credentials = {k: v for k, v in credentials.items() if k and v}
                        headers.update(filtered_credentials)

                    # Use cached passthrough headers (no DB query needed)
                    if request_headers:
                        headers = compute_passthrough_headers_cached(
                            request_headers, headers, passthrough_allowed, gateway_auth_type=None, gateway_passthrough_headers=None  # REST tools don't use gateway auth here
                        )

                    if self._plugin_manager:
                        # Use pre-created Pydantic model from Phase 2 (no ORM access)
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        pre_result, context_table = await self._plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
                            global_context=global_context,
                            local_contexts=context_table,  # Pass context from previous hooks
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

                    # Handle URL path parameter substitution (using local variable)
                    final_url = tool_url
                    if "{" in tool_url and "}" in tool_url:
                        # Extract path parameters from URL template and arguments
                        url_params = re.findall(r"\{(\w+)\}", tool_url)
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

                    # Use the tool's request_type rather than defaulting to POST (using local variable)
                    method = tool_request_type.upper() if tool_request_type else "POST"
                    if method == "GET":
                        response = await self._http_client.get(final_url, params=payload, headers=headers)
                    else:
                        response = await self._http_client.request(method, final_url, json=payload, headers=headers)
                    response.raise_for_status()

                    # Handle 204 No Content responses that have no body
                    if response.status_code == 204:
                        tool_result = ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")])
                        success = True
                    elif response.status_code not in [200, 201, 202, 206]:
                        try:
                            result = response.json()
                        except orjson.JSONDecodeError:
                            result = {"response_text": response.text} if response.text else {}
                        tool_result = ToolResult(
                            content=[TextContent(type="text", text=str(result["error"]) if "error" in result else "Tool error encountered")],
                            is_error=True,
                        )
                        # Don't mark as successful for error responses - success remains False
                    else:
                        try:
                            result = response.json()
                        except orjson.JSONDecodeError:
                            result = {"response_text": response.text} if response.text else {}
                        logger.debug(f"REST API tool response: {result}")
                        filtered_response = extract_using_jq(result, tool_jsonpath_filter)
                        tool_result = ToolResult(content=[TextContent(type="text", text=orjson.dumps(filtered_response, option=orjson.OPT_INDENT_2).decode())])
                        success = True
                        # If output schema is present, validate and attach structured content
                        if tool_output_schema:
                            valid = self._extract_and_validate_structured_content(tool, tool_result, candidate=filtered_response)
                            success = bool(valid)
                elif tool_integration_type == "MCP":
                    transport = tool_request_type.lower() if tool_request_type else "sse"

                    # Handle OAuth authentication for the gateway (using local variables)
                    # NOTE: Use has_gateway instead of gateway to avoid accessing detached ORM object
                    if has_gateway and gateway_auth_type == "oauth" and gateway_oauth_config:
                        grant_type = gateway_oauth_config.get("grant_type", "client_credentials")

                        if grant_type == "authorization_code":
                            # For Authorization Code flow, try to get stored tokens
                            # NOTE: Use fresh_db_session() since the original db was closed
                            try:
                                # First-Party
                                from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                                with fresh_db_session() as token_db:
                                    token_storage = TokenStorageService(token_db)

                                    # Get user-specific OAuth token
                                    if not app_user_email:
                                        raise ToolInvocationError(f"User authentication required for OAuth-protected gateway '{gateway_name}'. Please ensure you are authenticated.")

                                    access_token = await token_storage.get_user_token(gateway_id_str, app_user_email)

                                if access_token:
                                    headers = {"Authorization": f"Bearer {access_token}"}
                                else:
                                    # User hasn't authorized this gateway yet
                                    raise ToolInvocationError(f"Please authorize {gateway_name} first. Visit /oauth/authorize/{gateway_id_str} to complete OAuth flow.")
                            except Exception as e:
                                logger.error(f"Failed to obtain stored OAuth token for gateway {gateway_name}: {e}")
                                raise ToolInvocationError(f"OAuth token retrieval failed for gateway: {str(e)}")
                        else:
                            # For Client Credentials flow, get token directly (no DB needed)
                            try:
                                access_token = await self.oauth_manager.get_access_token(gateway_oauth_config)
                                headers = {"Authorization": f"Bearer {access_token}"}
                            except Exception as e:
                                logger.error(f"Failed to obtain OAuth access token for gateway {gateway_name}: {e}")
                                raise ToolInvocationError(f"OAuth authentication failed for gateway: {str(e)}")
                    else:
                        headers = decode_auth(gateway_auth_value)

                    # Use cached passthrough headers (no DB query needed)
                    if request_headers:
                        headers = compute_passthrough_headers_cached(
                            request_headers, headers, passthrough_allowed, gateway_auth_type=gateway_auth_type, gateway_passthrough_headers=gateway_passthrough
                        )

                    def create_ssl_context(ca_certificate: str) -> ssl.SSLContext:
                        """Create an SSL context with the provided CA certificate.

                        Args:
                            ca_certificate: CA certificate in PEM format

                        Returns:
                            ssl.SSLContext: Configured SSL context
                        """
                        ctx = ssl.create_default_context()
                        ctx.load_verify_locations(cadata=ca_certificate)
                        return ctx

                    def get_httpx_client_factory(
                        headers: dict[str, str] | None = None,
                        timeout: httpx.Timeout | None = None,
                        auth: httpx.Auth | None = None,
                    ) -> httpx.AsyncClient:
                        """Factory function to create httpx.AsyncClient with optional CA certificate.

                        Args:
                            headers: Optional headers for the client
                            timeout: Optional timeout for the client
                            auth: Optional auth for the client

                        Returns:
                            httpx.AsyncClient: Configured HTTPX async client

                        Raises:
                            Exception: If CA certificate signature is invalid
                        """
                        # Use local variables instead of ORM objects (captured from outer scope)
                        valid = False
                        if gateway_ca_cert:
                            if settings.enable_ed25519_signing:
                                public_key_pem = settings.ed25519_public_key
                                valid = validate_signature(gateway_ca_cert.encode(), gateway_ca_cert_sig, public_key_pem)
                            else:
                                valid = True
                        if valid:
                            ctx = create_ssl_context(gateway_ca_cert)
                        else:
                            ctx = None
                        return httpx.AsyncClient(
                            verify=ctx if ctx else True,
                            follow_redirects=True,
                            headers=headers,
                            timeout=timeout or httpx.Timeout(30.0),
                            auth=auth,
                        )

                    async def connect_to_sse_server(server_url: str, headers: dict = headers):
                        """Connect to an MCP server running with SSE transport.

                        Args:
                            server_url: MCP Server SSE URL
                            headers: HTTP headers to include in the request

                        Returns:
                            ToolResult: Result of tool call

                        Raises:
                            Exception: On connection or communication errors
                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()

                        # Add correlation ID to headers
                        if correlation_id and headers:
                            headers["X-Correlation-ID"] = correlation_id

                        # Log MCP call start (using local variables)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url, "transport": "sse"},
                        )

                        try:
                            async with sse_client(url=server_url, headers=headers, httpx_client_factory=get_httpx_client_factory) as streams:
                                async with ClientSession(*streams) as session:
                                    await session.initialize()
                                    tool_call_result = await session.call_tool(tool_name_original, arguments)

                            # Log successful MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="INFO",
                                message=f"MCP tool call completed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "mcp_call_completed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse", "success": True},
                            )

                            return tool_call_result
                        except Exception as e:
                            # Log failed MCP call (using local variables)
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(e).__name__, "error_message": str(e)},
                                metadata={"event": "mcp_call_failed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse"},
                            )
                            raise

                    async def connect_to_streamablehttp_server(server_url: str, headers: dict = headers):
                        """Connect to an MCP server running with Streamable HTTP transport.

                        Args:
                            server_url: MCP Server URL
                            headers: HTTP headers to include in the request

                        Returns:
                            ToolResult: Result of tool call

                        Raises:
                            Exception: On connection or communication errors
                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()

                        # Add correlation ID to headers
                        if correlation_id and headers:
                            headers["X-Correlation-ID"] = correlation_id

                        # Log MCP call start (using local variables)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url, "transport": "streamablehttp"},
                        )

                        try:
                            async with streamablehttp_client(url=server_url, headers=headers, httpx_client_factory=get_httpx_client_factory) as (read_stream, write_stream, _get_session_id):
                                async with ClientSession(read_stream, write_stream) as session:
                                    await session.initialize()
                                    tool_call_result = await session.call_tool(tool_name_original, arguments)

                            # Log successful MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="INFO",
                                message=f"MCP tool call completed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "mcp_call_completed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp", "success": True},
                            )

                            return tool_call_result
                        except Exception as e:
                            # Log failed MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(e).__name__, "error_message": str(e)},
                                metadata={"event": "mcp_call_failed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp"},
                            )
                            raise

                    # REMOVED: Redundant gateway query - gateway already eager-loaded via joinedload
                    # tool_gateway = db.execute(select(DbGateway).where(DbGateway.id == tool_gateway_id)...)

                    if self._plugin_manager:
                        # Use pre-created Pydantic models from Phase 2 (no ORM access)
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        if gateway_metadata:
                            global_context.metadata[GATEWAY_METADATA] = gateway_metadata
                        pre_result, context_table = await self._plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
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
                        tool_call_result = await connect_to_sse_server(gateway_url, headers=headers)
                    elif transport == "streamablehttp":
                        tool_call_result = await connect_to_streamablehttp_server(gateway_url, headers=headers)
                    dump = tool_call_result.model_dump(by_alias=True)
                    logger.debug(f"Tool call result dump: {dump}")
                    content = dump.get("content", [])
                    # Accept both alias and pythonic names for structured content
                    structured = dump.get("structuredContent") or dump.get("structured_content")
                    filtered_response = extract_using_jq(content, tool_jsonpath_filter)

                    is_err = getattr(tool_call_result, "is_error", None)
                    if is_err is None:
                        is_err = getattr(tool_call_result, "isError", False)
                    tool_result = ToolResult(content=filtered_response, structured_content=structured, is_error=is_err, meta=getattr(tool_call_result, "meta", None))
                    success = not is_err
                    logger.debug(f"Final tool_result: {tool_result}")
                else:
                    tool_result = ToolResult(content=[TextContent(type="text", text="Invalid tool type")], is_error=True)

                # Plugin hook: tool post-invoke
                if self._plugin_manager:
                    post_result, _ = await self._plugin_manager.invoke_hook(
                        ToolHookType.TOOL_POST_INVOKE,
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
                            # Safely obtain structured content using .get() to avoid KeyError when
                            # plugins provide only the content without structured content fields.
                            structured = modified_result.get("structuredContent") if "structuredContent" in modified_result else modified_result.get("structured_content")

                            tool_result = ToolResult(content=modified_result["content"], structured_content=structured)
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
                # Calculate duration
                duration_ms = (time.monotonic() - start_time) * 1000

                # Add final span attributes
                if span:
                    span.set_attribute("success", success)
                    span.set_attribute("duration.ms", duration_ms)

                # ═══════════════════════════════════════════════════════════════════════════
                # PHASE 4: Record metrics via buffered service (batches writes for performance)
                # ═══════════════════════════════════════════════════════════════════════════
                try:
                    # First-Party
                    from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                    metrics_buffer = get_metrics_buffer_service()
                    metrics_buffer.record_tool_metric(
                        tool_id=tool_id,
                        start_time=start_time,
                        success=success,
                        error_message=error_message,
                    )
                except Exception as metric_error:
                    logger.warning(f"Failed to record tool metric: {metric_error}")

                # Log structured message with performance tracking (using local variables)
                if success:
                    structured_logger.info(
                        f"Tool '{name}' invoked successfully",
                        user_id=app_user_email,
                        resource_type="tool",
                        resource_id=tool_id,
                        resource_action="invoke",
                        duration_ms=duration_ms,
                        custom_fields={"tool_name": name, "integration_type": tool_integration_type, "arguments_count": len(arguments) if arguments else 0},
                    )
                else:
                    structured_logger.error(
                        f"Tool '{name}' invocation failed",
                        error=Exception(error_message) if error_message else None,
                        user_id=app_user_email,
                        resource_type="tool",
                        resource_id=tool_id,
                        resource_action="invoke",
                        duration_ms=duration_ms,
                        custom_fields={"tool_name": name, "integration_type": tool_integration_type, "error_message": error_message},
                    )

                # Track performance with threshold checking
                with perf_tracker.track_operation("tool_invocation", name):
                    pass  # Duration already captured above

    async def update_tool(
        self,
        db: Session,
        tool_id: str,
        tool_update: ToolUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        user_email: Optional[str] = None,
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
            user_email (Optional[str]): Email of user performing update (for ownership check).

        Returns:
            The updated ToolRead object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            PermissionError: If user doesn't own the tool.
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

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can update this tool")

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
                if tool_update.custom_name is None and tool.name == tool.custom_name:
                    tool.custom_name = tool_update.name
                tool.name = tool_update.name

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
            if tool_update.output_schema is not None:
                tool.output_schema = tool_update.output_schema
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
            logger.info(f"Update tool: {tool.name} (output_schema: {tool.output_schema})")

            tool.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(tool)
            await self._notify_tool_updated(tool)
            logger.info(f"Updated tool: {tool.name}")

            # Structured logging: Audit trail for tool update
            changes = []
            if tool_update.name:
                changes.append(f"name: {tool_update.name}")
            if tool_update.visibility:
                changes.append(f"visibility: {tool_update.visibility}")
            if tool_update.description:
                changes.append("description updated")

            audit_trail.log_action(
                user_id=user_email or modified_by or "system",
                action="update_tool",
                resource_type="tool",
                resource_id=tool.id,
                resource_name=tool.name,
                user_email=user_email,
                team_id=tool.team_id,
                client_ip=modified_from_ip,
                user_agent=modified_user_agent,
                new_values={
                    "name": tool.name,
                    "display_name": tool.display_name,
                    "version": tool.version,
                },
                context={
                    "modified_via": modified_via,
                    "changes": ", ".join(changes) if changes else "metadata only",
                },
                db=db,
            )

            # Structured logging: Log successful tool update
            structured_logger.log(
                level="INFO",
                message="Tool updated successfully",
                event_type="tool_updated",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                team_id=tool.team_id,
                resource_type="tool",
                resource_id=tool.id,
                custom_fields={
                    "tool_name": tool.name,
                    "version": tool.version,
                },
                db=db,
            )

            return self._convert_tool_to_read(tool, db=db)
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool update failed due to permission error",
                event_type="tool_update_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=pe,
                db=db,
            )
            raise
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityError during tool update: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Tool update failed due to database integrity error",
                event_type="tool_update_failed",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=ie,
                db=db,
            )
            raise ie
        except ToolNotFoundError as tnfe:
            db.rollback()
            logger.error(f"Tool not found during update: {tnfe}")

            # Structured logging: Log not found error
            structured_logger.log(
                level="ERROR",
                message="Tool update failed - tool not found",
                event_type="tool_not_found",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=tnfe,
                db=db,
            )
            raise tnfe
        except ToolNameConflictError as tnce:
            db.rollback()
            logger.error(f"Tool name conflict during update: {tnce}")

            # Structured logging: Log name conflict error
            structured_logger.log(
                level="WARNING",
                message="Tool update failed due to name conflict",
                event_type="tool_name_conflict",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=tnce,
                db=db,
            )
            raise tnce
        except Exception as ex:
            db.rollback()

            # Structured logging: Log generic tool update failure
            structured_logger.log(
                level="ERROR",
                message="Tool update failed",
                event_type="tool_update_failed",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=ex,
                db=db,
            )
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
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled, "reachable": tool.reachable},
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
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled, "reachable": tool.reachable},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_offline(self, tool: DbTool) -> None:
        """
        Notify subscribers that tool is offline.

        Args:
            tool: Tool database object
        """
        event = {
            "type": "tool_offline",
            "data": {
                "id": tool.id,
                "name": tool.name,
                "enabled": True,
                "reachable": False,
            },
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
        """Subscribe to tool events via the EventService.

        Yields:
            Tool event messages.
        """
        async for event in self._event_service.subscribe_events():
            yield event

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
        Publish event to all subscribers via the EventService.

        Args:
            event: Event to publish
        """
        await self._event_service.publish_event(event)

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

    # async def event_generator(self) -> AsyncGenerator[Dict[str, Any], None]:
    #     """Generate tool events for SSE.

    #     Yields:
    #         Tool events.
    #     """
    #     queue: asyncio.Queue = asyncio.Queue()
    #     self._event_subscribers.append(queue)
    #     try:
    #         while True:
    #             event = await queue.get()
    #             yield event
    #     finally:
    #         self._event_subscribers.remove(queue)

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
            >>> # Mock the row result object returned by db.execute().one()
            >>> mock_result_row = MagicMock()
            >>> mock_result_row.total = 10
            >>> mock_result_row.successful = 8
            >>> mock_result_row.failed = 2
            >>> mock_result_row.min_rt = 50.0
            >>> mock_result_row.max_rt = 250.0
            >>> mock_result_row.avg_rt = 150.0
            >>> mock_result_row.last_time = "2023-01-01T12:00:00"
            >>> db.execute.return_value.one.return_value = mock_result_row
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> isinstance(result, dict)
            True
            >>> result['total_executions']
            10
            >>> result['failure_rate']
            0.2
        """

        # Query to get all aggregated metrics at once
        result = db.execute(
            select(
                func.count(ToolMetric.id).label("total"),  # pylint: disable=not-callable
                func.sum(case((ToolMetric.is_success.is_(True), 1), else_=0)).label("successful"),  # pylint: disable=not-callable
                func.sum(case((ToolMetric.is_success.is_(False), 1), else_=0)).label("failed"),  # pylint: disable=not-callable
                func.min(ToolMetric.response_time).label("min_rt"),  # pylint: disable=not-callable
                func.max(ToolMetric.response_time).label("max_rt"),  # pylint: disable=not-callable
                func.avg(ToolMetric.response_time).label("avg_rt"),  # pylint: disable=not-callable
                func.max(ToolMetric.timestamp).label("last_time"),  # pylint: disable=not-callable
            )
        ).one()

        total = result.total or 0
        successful = result.successful or 0
        failed = result.failed or 0
        failure_rate = failed / total if total > 0 else 0.0

        return {
            "total_executions": total,
            "successful_executions": successful,
            "failed_executions": failed,
            "failure_rate": failure_rate,
            "min_response_time": result.min_rt,
            "max_response_time": result.max_rt,
            "avg_response_time": result.avg_rt,
            "last_execution_time": result.last_time,
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

    async def cleanup_old_metrics(self, db: Session, retention_days: int = 30) -> int:
        """Delete tool metrics older than the retention period.

        Args:
            db: Database session.
            retention_days: Number of days to retain metrics.

        Returns:
            int: Number of deleted metric records.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        result = db.execute(delete(ToolMetric).where(ToolMetric.timestamp < cutoff))
        deleted = result.rowcount
        db.commit()
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old tool metrics (retention: {retention_days} days)")
        return deleted

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
            return self._convert_tool_to_read(existing_tool, db=db)

        # Create tool entry for the A2A agent
        logger.debug(f"agent.tags: {agent.tags} for agent: {agent.name} (ID: {agent.id})")

        # Normalize tags: if agent.tags contains dicts like {'id':..,'label':..},
        # extract the human-friendly label. If tags are already strings, keep them.
        normalized_tags: list[str] = []
        for t in agent.tags or []:
            if isinstance(t, dict):
                # Prefer 'label', fall back to 'id' or stringified dict
                normalized_tags.append(t.get("label") or t.get("id") or str(t))
            elif hasattr(t, "label"):
                normalized_tags.append(getattr(t, "label"))
            else:
                normalized_tags.append(str(t))

        # Ensure we include identifying A2A tags
        normalized_tags = normalized_tags + ["a2a", "agent"]

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
                    "query": {"type": "string", "description": "User query", "default": "Hello from MCP Gateway Admin UI test!"},
                },
                "required": ["query"],
            },
            allow_auto=True,
            annotations={
                "title": f"A2A Agent: {agent.name}",
                "a2a_agent_id": agent.id,
                "a2a_agent_type": agent.agent_type,
            },
            auth_type=agent.auth_type,
            auth_value=agent.auth_value,
            tags=normalized_tags,
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
        try:
            # Make the A2A agent call
            response_data = await self._call_a2a_agent(agent, arguments)

            # Convert A2A response to MCP ToolResult format
            if isinstance(response_data, dict) and "response" in response_data:
                content = [TextContent(type="text", text=str(response_data["response"]))]
            else:
                content = [TextContent(type="text", text=str(response_data))]

            result = ToolResult(content=content, is_error=False)

        except Exception as e:
            error_message = str(e)
            content = [TextContent(type="text", text=f"A2A agent error: {error_message}")]
            result = ToolResult(content=content, is_error=True)

        # Note: Metrics are recorded by the calling invoke_tool method, not here
        return result

    async def _call_a2a_agent(self, agent: DbA2AAgent, parameters: Dict[str, Any]):
        """Call an A2A agent directly.

        Args:
            agent: The A2A agent to call.
            parameters: Parameters for the interaction.

        Returns:
            Response from the A2A agent.

        Raises:
            Exception: If the call fails.
        """
        logger.info(f"Calling A2A agent '{agent.name}' at {agent.endpoint_url} with arguments: {parameters}")
        # Patch: Build correct JSON-RPC params structure from flat UI input
        params = None
        # If UI sends flat fields, convert to nested message structure
        if isinstance(parameters, dict) and "query" in parameters and isinstance(parameters["query"], str):
            # Build the nested message object
            message_id = f"admin-test-{int(time.time())}"
            params = {"message": {"messageId": message_id, "role": "user", "parts": [{"type": "text", "text": parameters["query"]}]}}
            method = parameters.get("method", "message/send")
        else:
            # Already in correct format or unknown, pass through
            params = parameters.get("params", parameters)
            method = parameters.get("method", "message/send")

        if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
            try:
                request_data = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
                logger.info(f"invoke tool JSONRPC request_data prepared: {request_data}")
            except Exception as e:
                logger.error(f"Error preparing JSONRPC request data: {e}")
                raise
        else:
            logger.info(f"invoke tool Using custom A2A format for A2A agent '{parameters}'")
            request_data = {"interaction_type": parameters.get("interaction_type", "query"), "parameters": params, "protocol_version": agent.protocol_version}
        logger.info(f"invoke tool request_data prepared: {request_data}")
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
