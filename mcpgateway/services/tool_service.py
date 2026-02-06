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
import binascii
from datetime import datetime, timezone
from functools import lru_cache
import os
import re
import ssl
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import httpx
import jq
import jsonschema
from jsonschema import Draft4Validator, Draft6Validator, Draft7Validator, validators
from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
import orjson
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload, selectinload, Session

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.common.models import Gateway as PydanticGateway
from mcpgateway.common.models import TextContent
from mcpgateway.common.models import Tool as PydanticTool
from mcpgateway.common.models import ToolResult
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import fresh_db_session
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_for_update, server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric, ToolMetricsHourly
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
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolRead, ToolUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.mcp_session_pool import get_mcp_session_pool, TransportType
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.metrics_query_service import get_top_performers_combined
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import decode_cursor, encode_cursor, unified_paginate
from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr
from mcpgateway.utils.ssl_context_cache import get_cached_ssl_context
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_exception_message, sanitize_url_for_logging
from mcpgateway.utils.validate_signature import validate_signature

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None
_TOOL_LOOKUP_CACHE = None


def _get_registry_cache():
    """Get registry cache singleton lazily.

    Returns:
        RegistryCache instance.
    """
    global _REGISTRY_CACHE  # pylint: disable=global-statement
    if _REGISTRY_CACHE is None:
        # First-Party
        from mcpgateway.cache.registry_cache import registry_cache  # pylint: disable=import-outside-toplevel

        _REGISTRY_CACHE = registry_cache
    return _REGISTRY_CACHE


def _get_tool_lookup_cache():
    """Get tool lookup cache singleton lazily.

    Returns:
        ToolLookupCache instance.
    """
    global _TOOL_LOOKUP_CACHE  # pylint: disable=global-statement
    if _TOOL_LOOKUP_CACHE is None:
        # First-Party
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel

        _TOOL_LOOKUP_CACHE = tool_lookup_cache
    return _TOOL_LOOKUP_CACHE


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize performance tracker, structured logger, and audit trail for tool operations
perf_tracker = get_performance_tracker()
structured_logger = get_structured_logger("tool_service")
audit_trail = get_audit_trail_service()


@lru_cache(maxsize=256)
def _compile_jq_filter(jq_filter: str):
    """Cache compiled jq filter program.

    Args:
        jq_filter: The jq filter string to compile.

    Returns:
        Compiled jq program object.

    Raises:
        ValueError: If the jq filter is invalid.
    """
    # pylint: disable=c-extension-no-member
    return jq.compile(jq_filter)


@lru_cache(maxsize=128)
def _get_validator_class_and_check(schema_json: str) -> Tuple[type, dict]:
    """Cache schema validation and validator class selection.

    This caches the expensive operations:
    1. Deserializing the schema
    2. Selecting the appropriate validator class based on $schema
    3. Checking the schema is valid

    Supports multiple JSON Schema drafts by using fallback validators when the
    auto-detected validator fails. This handles schemas using older draft features
    (e.g., Draft 4 style exclusiveMinimum: true) that are invalid in newer drafts.

    Args:
        schema_json: Canonical JSON string of the schema (used as cache key).

    Returns:
        Tuple of (validator_class, schema_dict) ready for instantiation.
    """
    schema = orjson.loads(schema_json)

    # First try auto-detection based on $schema
    validator_cls = validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
        return validator_cls, schema
    except jsonschema.exceptions.SchemaError:
        pass

    # Fallback: try older drafts that may accept schemas with legacy features
    # (e.g., Draft 4/6 style boolean exclusiveMinimum/exclusiveMaximum)
    for fallback_cls in [Draft7Validator, Draft6Validator, Draft4Validator]:
        try:
            fallback_cls.check_schema(schema)
            return fallback_cls, schema
        except jsonschema.exceptions.SchemaError:
            continue

    # If no validator accepts the schema, use the original and let it fail
    # with a clear error message during validation
    validator_cls.check_schema(schema)
    return validator_cls, schema


def _canonicalize_schema(schema: dict) -> str:
    """Create a canonical JSON string of a schema for use as a cache key.

    Args:
        schema: The JSON Schema dictionary.

    Returns:
        Canonical JSON string with sorted keys.
    """
    return orjson.dumps(schema, option=orjson.OPT_SORT_KEYS).decode()


def _validate_with_cached_schema(instance: Any, schema: dict) -> None:
    # noqa: DAR401
    """Validate instance against schema using cached validator class.

    Creates a fresh validator instance for thread safety, but reuses
    the cached validator class and schema check. Uses best_match to
    preserve jsonschema.validate() error selection semantics.

    Args:
        instance: The data to validate.
        schema: The JSON Schema to validate against.

    Raises:
        jsonschema.exceptions.ValidationError: If validation fails.
    """
    schema_json = _canonicalize_schema(schema)
    validator_cls, checked_schema = _get_validator_class_and_check(schema_json)
    # Create fresh validator instance for thread safety
    validator = validator_cls(checked_schema)
    # Use best_match to match jsonschema.validate() error selection behavior
    error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
    if error is not None:
        raise error


def extract_using_jq(data, jq_filter=""):
    """
    Extracts data from a given input (string, dict, or list) using a jq filter string.

    Uses cached compiled jq programs for performance.

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
    if not jq_filter or jq_filter == "":
        return data

    # Track if input was originally a string (for error handling)
    was_string = isinstance(data, str)

    if was_string:
        # If the input is a string, parse it as JSON
        try:
            data = orjson.loads(data)
        except orjson.JSONDecodeError:
            return ["Invalid JSON string provided."]
    elif not isinstance(data, (dict, list)):
        # If the input is not a string, dict, or list, raise an error
        return ["Input data must be a JSON string, dictionary, or list."]

    # Apply the jq filter to the data using cached compiled program
    try:
        program = _compile_jq_filter(jq_filter)
        result = program.input(data).all()
        if result == [None]:
            return [TextContent(type="text", text="Error applying jsonpath filter")]
    except Exception as e:
        message = "Error applying jsonpath filter: " + str(e)
        return [TextContent(type="text", text=message)]

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


class ToolLockConflictError(ToolError):
    """Raised when a tool row is locked by another transaction."""


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


class ToolTimeoutError(ToolInvocationError):
    """Raised when tool invocation times out.

    This subclass is used to distinguish timeout errors from other invocation errors.
    Timeout handlers call tool_post_invoke before raising this, so the generic exception
    handler should skip calling post_invoke again to avoid double-counting failures.
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

    async def get_top_tools(self, db: Session, limit: Optional[int] = 5, include_deleted: bool = False) -> List[TopPerformer]:
        """Retrieve the top-performing tools based on execution count.

        Queries the database to get tools with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing tool details and
        performance metrics. Results are cached for performance.

        Args:
            db (Session): Database session for querying tool metrics.
            limit (Optional[int]): Maximum number of tools to return. Defaults to 5.
            include_deleted (bool): Whether to include deleted tools from rollups.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Tool ID.
                - name: Tool name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        effective_limit = limit or 5
        cache_key = f"top_tools:{effective_limit}:include_deleted={include_deleted}"

        if is_cache_enabled():
            cached = metrics_cache.get(cache_key)
            if cached is not None:
                return cached

        # Use combined query that includes both raw metrics and rollup data
        results = get_top_performers_combined(
            db=db,
            metric_type="tool",
            entity_model=DbTool,
            limit=effective_limit,
            include_deleted=include_deleted,
        )
        top_performers = build_top_performers(results)

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set(cache_key, top_performers)

        return top_performers

    def _build_tool_cache_payload(self, tool: DbTool, gateway: Optional[DbGateway]) -> Dict[str, Any]:
        """Build cache payload for tool lookup by name.

        Args:
            tool: Tool ORM instance.
            gateway: Optional gateway ORM instance.

        Returns:
            Cache payload dict for tool lookup.
        """
        tool_payload = {
            "id": str(tool.id),
            "name": tool.name,
            "original_name": tool.original_name,
            "url": tool.url,
            "description": tool.description,
            "integration_type": tool.integration_type,
            "request_type": tool.request_type,
            "headers": tool.headers or {},
            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            "output_schema": tool.output_schema,
            "annotations": tool.annotations or {},
            "auth_type": tool.auth_type,
            "auth_value": tool.auth_value,
            "oauth_config": getattr(tool, "oauth_config", None),
            "jsonpath_filter": tool.jsonpath_filter,
            "custom_name": tool.custom_name,
            "custom_name_slug": tool.custom_name_slug,
            "display_name": tool.display_name,
            "gateway_id": str(tool.gateway_id) if tool.gateway_id else None,
            "enabled": bool(tool.enabled),
            "reachable": bool(tool.reachable),
            "tags": tool.tags or [],
            "team_id": tool.team_id,
            "owner_email": tool.owner_email,
            "visibility": tool.visibility,
        }

        gateway_payload = None
        if gateway:
            gateway_payload = {
                "id": str(gateway.id),
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "slug": gateway.slug,
                "transport": gateway.transport,
                "capabilities": gateway.capabilities or {},
                "passthrough_headers": gateway.passthrough_headers or [],
                "auth_type": gateway.auth_type,
                "auth_value": gateway.auth_value,
                "auth_query_params": getattr(gateway, "auth_query_params", None),  # Query param auth
                "oauth_config": getattr(gateway, "oauth_config", None),
                "ca_certificate": getattr(gateway, "ca_certificate", None),
                "ca_certificate_sig": getattr(gateway, "ca_certificate_sig", None),
                "enabled": bool(gateway.enabled),
                "reachable": bool(gateway.reachable),
                "team_id": gateway.team_id,
                "owner_email": gateway.owner_email,
                "visibility": gateway.visibility,
                "tags": gateway.tags or [],
                "gateway_mode": getattr(gateway, "gateway_mode", "cache"),  # Gateway mode for direct proxy support
            }

        return {"status": "active", "tool": tool_payload, "gateway": gateway_payload}

    def _pydantic_tool_from_payload(self, tool_payload: Dict[str, Any]) -> Optional[PydanticTool]:
        """Build Pydantic tool metadata from cache payload.

        Args:
            tool_payload: Cached tool payload dict.

        Returns:
            Pydantic tool metadata or None if validation fails.
        """
        try:
            return PydanticTool.model_validate(tool_payload)
        except Exception as exc:
            logger.debug("Failed to build PydanticTool from cache payload: %s", exc)
            return None

    def _pydantic_gateway_from_payload(self, gateway_payload: Dict[str, Any]) -> Optional[PydanticGateway]:
        """Build Pydantic gateway metadata from cache payload.

        Args:
            gateway_payload: Cached gateway payload dict.

        Returns:
            Pydantic gateway metadata or None if validation fails.
        """
        try:
            return PydanticGateway.model_validate(gateway_payload)
        except Exception as exc:
            logger.debug("Failed to build PydanticGateway from cache payload: %s", exc)
            return None

    async def _check_tool_access(
        self,
        db: Session,
        tool_payload: Dict[str, Any],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if user has access to a tool based on visibility rules.

        Implements the same access control logic as list_tools() for consistency.

        Access Rules:
        - Public tools: Accessible by all authenticated users
        - Team tools: Accessible by team members (team_id in user's teams)
        - Private tools: Accessible only by owner (owner_email matches)

        Args:
            db: Database session for team membership lookup if needed.
            tool_payload: Tool data dict with visibility, team_id, owner_email.
            user_email: Email of the requesting user (None = unauthenticated).
            token_teams: List of team IDs from token.
                - None = unrestricted admin access
                - [] = public-only token
                - [...] = team-scoped token

        Returns:
            True if access is allowed, False otherwise.
        """
        visibility = tool_payload.get("visibility", "public")
        tool_team_id = tool_payload.get("team_id")
        tool_owner_email = tool_payload.get("owner_email")

        # Public tools are accessible by everyone
        if visibility == "public":
            return True

        # Admin bypass: token_teams=None AND user_email=None means unrestricted admin
        # This happens when is_admin=True and no team scoping in token
        if token_teams is None and user_email is None:
            return True

        # No user context (but not admin) = deny access to non-public tools
        if not user_email:
            return False

        # Public-only tokens (empty teams array) can ONLY access public tools
        is_public_only_token = token_teams is not None and len(token_teams) == 0
        if is_public_only_token:
            return False  # Already checked public above

        # Owner can always access their own tools
        if tool_owner_email and tool_owner_email == user_email:
            return True

        # Team tools: check team membership (matches list_tools behavior)
        if tool_team_id:
            # Use token_teams if provided, otherwise look up from DB
            if token_teams is not None:
                team_ids = token_teams
            else:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]

            # Team/public visibility allows access if user is in the team
            if visibility in ["team", "public"] and tool_team_id in team_ids:
                return True

        return False

    def convert_tool_to_read(
        self,
        tool: DbTool,
        include_metrics: bool = False,
        include_auth: bool = True,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> ToolRead:
        """Converts a DbTool instance into a ToolRead model, including aggregated metrics and
        new API gateway fields: request_type and authentication credentials (masked).

        Args:
            tool (DbTool): The ORM instance of the tool.
            include_metrics (bool): Whether to include metrics in the result. Defaults to False.
            include_auth (bool): Whether to decode and include auth details. Defaults to True.
                When False, skips expensive AES-GCM decryption and returns minimal auth info.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

        Returns:
            ToolRead: The Pydantic model representing the tool, including aggregated metrics and new fields.
        """
        # NOTE: This serves two purposes:
        #   1. It determines whether to decode auth (used later)
        #   2. It forces the tool object to lazily evaluate (required before copy)
        has_encrypted_auth = tool.auth_type and tool.auth_value

        # Copy the dict from the tool
        tool_dict = tool.__dict__.copy()
        tool_dict.pop("_sa_instance_state", None)

        # Compute metrics in a single pass (matches server/resource/prompt service pattern)
        if include_metrics:
            metrics = tool.metrics_summary  # Single-pass computation
            tool_dict["metrics"] = metrics
            tool_dict["execution_count"] = metrics["total_executions"]
        else:
            tool_dict["metrics"] = None
            tool_dict["execution_count"] = None

        tool_dict["request_type"] = tool.request_type
        tool_dict["annotations"] = tool.annotations or {}

        # Only decode auth if include_auth=True AND we have encrypted credentials
        if include_auth and has_encrypted_auth:
            decoded_auth_value = decode_auth(tool.auth_value)
            if tool.auth_type == "basic":
                decoded_bytes = base64.b64decode(decoded_auth_value["Authorization"].split("Basic ")[1])
                username, password = decoded_bytes.decode("utf-8").split(":")
                tool_dict["auth"] = {
                    "auth_type": "basic",
                    "username": username,
                    "password": settings.masked_auth_value if password else None,
                }
            elif tool.auth_type == "bearer":
                tool_dict["auth"] = {
                    "auth_type": "bearer",
                    "token": settings.masked_auth_value if decoded_auth_value["Authorization"] else None,
                }
            elif tool.auth_type == "authheaders":
                # Get first key
                if decoded_auth_value:
                    first_key = next(iter(decoded_auth_value))
                    tool_dict["auth"] = {
                        "auth_type": "authheaders",
                        "auth_header_key": first_key,
                        "auth_header_value": settings.masked_auth_value if decoded_auth_value[first_key] else None,
                    }
                else:
                    tool_dict["auth"] = None
            else:
                tool_dict["auth"] = None
        elif not include_auth and has_encrypted_auth:
            # LIST VIEW: Minimal auth info without decryption
            # Only show auth_type for tools that have encrypted credentials
            tool_dict["auth"] = {"auth_type": tool.auth_type}
        else:
            # No encrypted auth (includes OAuth tools where auth_value=None)
            # Behavior unchanged from current implementation
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

        # Mask custom headers unless the requester is allowed to modify this tool.
        # Safe default: if no requester context is provided, mask everything.
        headers = tool_dict.get("headers")
        if headers:
            can_view = requesting_user_is_admin
            if not can_view and getattr(tool, "owner_email", None) == requesting_user_email:
                can_view = True
            if (
                not can_view
                and getattr(tool, "visibility", None) == "team"
                and getattr(tool, "team_id", None) is not None
                and requesting_user_team_roles
                and requesting_user_team_roles.get(str(tool.team_id)) == "owner"
            ):
                can_view = True
            if not can_view:
                tool_dict["headers"] = {k: settings.masked_auth_value for k in headers}

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

            # Validate using cached schema validator
            try:
                _validate_with_cached_schema(structured, output_schema)
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
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
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

            # Invalidate cache after successful creation
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(db_tool.name, gateway_id=str(db_tool.gateway_id) if db_tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return self.convert_tool_to_read(db_tool, requesting_user_email=getattr(db_tool, "owner_email", None))
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

            if chunk_stats["created"] or chunk_stats["updated"]:
                cache = _get_registry_cache()
                await cache.invalidate_tools()
                tool_lookup_cache = _get_tool_lookup_cache()
                tool_name_map: Dict[str, Optional[str]] = {}
                for tool in chunk:
                    name = getattr(tool, "name", None)
                    if not name:
                        continue
                    gateway_id = getattr(tool, "gateway_id", None)
                    tool_name_map[name] = str(gateway_id) if gateway_id else tool_name_map.get(name)
                for tool_name, gateway_id in tool_name_map.items():
                    await tool_lookup_cache.invalidate(tool_name, gateway_id=gateway_id)
                # Also invalidate tags cache since tool tags may have changed
                # First-Party
                from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

                await admin_stats_cache.invalidate_tags()

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
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        _request_headers: Optional[Dict[str, str]] = None,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> Union[tuple[List[ToolRead], Optional[str]], Dict[str, Any]]:
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
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email (Optional[str]): User email for team-based access control. If None, no access control is applied.
            team_id (Optional[str]): Filter by specific team ID. Requires user_email for access validation.
            visibility (Optional[str]): Filter by visibility (private, team, public).
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API token access
                where the token scope should be respected instead of the user's full team memberships.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

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
            >>> service.convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> tools, next_cursor = asyncio.run(service.list_tools(db))
            >>> isinstance(tools, list)
            True
        """
        # Check cache for first page only (cursor=None)
        # Skip caching when:
        # - user_email is provided (team-filtered results are user-specific)
        # - token_teams is set (scoped access, e.g., public-only or team-scoped tokens)
        # - page-based pagination is used
        # This prevents cache poisoning where admin results could leak to public-only requests
        cache = _get_registry_cache()
        filters_hash = None
        # Only use the cache when using the real converter. In unit tests we often patch
        # convert_tool_to_read() to exercise error handling, and a warm cache would bypass it.
        try:
            converter_is_default = self.convert_tool_to_read.__func__ is ToolService.convert_tool_to_read  # type: ignore[attr-defined]
        except Exception:
            converter_is_default = False

        if cursor is None and user_email is None and token_teams is None and page is None and converter_is_default:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None, gateway_id=gateway_id, limit=limit)
            cached = await cache.get("tools", filters_hash)
            if cached is not None:
                # Reconstruct ToolRead objects from cached dicts
                cached_tools = [ToolRead.model_validate(t) for t in cached["tools"]]
                return (cached_tools, cached.get("next_cursor"))

        # Build base query with ordering and eager load gateway + email_team to avoid N+1
        query = select(DbTool).options(joinedload(DbTool.gateway), joinedload(DbTool.email_team)).order_by(desc(DbTool.created_at), desc(DbTool.id))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbTool.enabled)
        # Apply team-based access control if user_email is provided OR token_teams is explicitly set
        # This ensures unauthenticated requests with token_teams=[] only see public tools
        if user_email is not None or token_teams is not None:  # empty-string user_email -> public-only filtering (secure default)
            # Use token_teams if provided (for MCP/API token access), otherwise look up from DB
            if token_teams is not None:
                team_ids = token_teams
            elif user_email:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]
            else:
                team_ids = []

            # Check if this is a public-only token (empty teams array)
            # Public-only tokens can ONLY see public resources - no owner access
            is_public_only_token = token_teams is not None and len(token_teams) == 0

            if team_id:
                # User requesting specific team - verify access
                if team_id not in team_ids:
                    return ([], None)
                access_conditions = [
                    and_(DbTool.team_id == team_id, DbTool.visibility.in_(["team", "public"])),
                ]
                # Only include owner access for non-public-only tokens
                if not is_public_only_token and user_email:
                    access_conditions.append(and_(DbTool.team_id == team_id, DbTool.owner_email == user_email))
                query = query.where(or_(*access_conditions))
            else:
                # General access: public tools + team tools (+ owner tools if not public-only token)
                access_conditions = [
                    DbTool.visibility == "public",
                ]
                # Only include owner access for non-public-only tokens with user_email
                if not is_public_only_token and user_email:
                    access_conditions.append(DbTool.owner_email == user_email)
                if team_ids:
                    access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            if visibility:
                query = query.where(DbTool.visibility == visibility)

        # Add gateway_id filtering if provided
        if gateway_id:
            if gateway_id.lower() == "null":
                query = query.where(DbTool.gateway_id.is_(None))
            else:
                query = query.where(DbTool.gateway_id == gateway_id)

        # Add tag filtering if tags are provided (supports both List[str] and List[Dict] formats)
        if tags:
            query = query.where(json_contains_tag_expr(db, DbTool.tags, tags, match_any=True))

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
            query=query,
            page=page,
            per_page=per_page,
            cursor=cursor,
            limit=limit,
            base_url="/admin/tools",  # Used for page-based links
            query_params={"include_inactive": include_inactive} if include_inactive else {},
        )

        next_cursor = None
        # Extract servers based on pagination type
        if page is not None:
            # Page-based: pag_result is a dict
            tools_db = pag_result["data"]
        else:
            # Cursor-based: pag_result is a tuple
            tools_db, next_cursor = pag_result

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Convert to ToolRead (common for both pagination types)
        # Team names are loaded via joinedload(DbTool.email_team)
        result = []
        for s in tools_db:
            try:
                result.append(
                    self.convert_tool_to_read(
                        s,
                        include_metrics=False,
                        include_auth=False,
                        requesting_user_email=requesting_user_email,
                        requesting_user_is_admin=requesting_user_is_admin,
                        requesting_user_team_roles=requesting_user_team_roles,
                    )
                )
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert tool {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                # Continue with remaining tools instead of failing completely

        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format

        # Cache first page results - only for non-user-specific/non-scoped queries
        # Must match the same conditions as cache lookup to prevent cache poisoning
        if filters_hash is not None and cursor is None and user_email is None and token_teams is None and page is None and converter_is_default:
            try:
                cache_data = {"tools": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                await cache.set("tools", cache_data, filters_hash)
            except AttributeError:
                pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

        return (result, next_cursor)

    async def list_server_tools(
        self,
        db: Session,
        server_id: str,
        include_inactive: bool = False,
        include_metrics: bool = False,
        cursor: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        _request_headers: Optional[Dict[str, str]] = None,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
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
            user_email (Optional[str]): User email for visibility filtering. If None, no filtering applied.
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API
                token access where the token scope should be respected.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

        Returns:
            List[ToolRead]: A list of registered tools represented as ToolRead objects.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service.convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_tools(db, 'server1'))
            >>> isinstance(result, list)
            True
        """

        if include_metrics:
            query = (
                select(DbTool)
                .options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))
                .options(selectinload(DbTool.metrics))
                .join(server_tool_association, DbTool.id == server_tool_association.c.tool_id)
                .where(server_tool_association.c.server_id == server_id)
            )
        else:
            query = (
                select(DbTool)
                .options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))
                .join(server_tool_association, DbTool.id == server_tool_association.c.tool_id)
                .where(server_tool_association.c.server_id == server_id)
            )

        cursor = None  # Placeholder for pagination; ignore for now
        logger.debug(f"Listing server tools for server_id={server_id} with include_inactive={include_inactive}, cursor={cursor}")

        if not include_inactive:
            query = query.where(DbTool.enabled)

        # Add visibility filtering if user context OR token_teams provided
        # This ensures unauthenticated requests with token_teams=[] only see public tools
        if user_email is not None or token_teams is not None:  # empty-string user_email -> public-only filtering (secure default)
            # Use token_teams if provided (for MCP/API token access), otherwise look up from DB
            if token_teams is not None:
                team_ids = token_teams
            elif user_email:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]
            else:
                team_ids = []

            # Check if this is a public-only token (empty teams array)
            # Public-only tokens can ONLY see public resources - no owner access
            is_public_only_token = token_teams is not None and len(token_teams) == 0

            access_conditions = [
                DbTool.visibility == "public",
            ]
            # Only include owner access for non-public-only tokens with user_email
            if not is_public_only_token and user_email:
                access_conditions.append(DbTool.owner_email == user_email)
            if team_ids:
                access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))
            query = query.where(or_(*access_conditions))

        # Execute the query - team names are loaded via joinedload(DbTool.email_team)
        tools = db.execute(query).scalars().all()

        db.commit()  # Release transaction to avoid idle-in-transaction

        result = []
        for tool in tools:
            try:
                result.append(
                    self.convert_tool_to_read(
                        tool,
                        include_metrics=include_metrics,
                        include_auth=False,
                        requesting_user_email=requesting_user_email,
                        requesting_user_is_admin=requesting_user_is_admin,
                        requesting_user_team_roles=requesting_user_team_roles,
                    )
                )
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert tool {getattr(tool, 'id', 'unknown')} ({getattr(tool, 'name', 'unknown')}): {e}")
                # Continue with remaining tools instead of failing completely

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
        DEPRECATED: Use list_tools() with user_email parameter instead.

        List tools user has access to with team filtering and cursor pagination.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_tools() with user_email, team_id, and visibility parameters.

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

        # Eager load gateway and email_team to avoid N+1 when accessing gateway_slug and team name
        query = select(DbTool).options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))

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
            query = query.where(json_contains_tag_expr(db, DbTool.tags, tags, match_any=True))

        # Apply cursor filter (WHERE id > last_id)
        if last_id:
            query = query.where(DbTool.id > last_id)

        # Execute query - team names are loaded via joinedload(DbTool.email_team)
        if page_size is not None:
            tools = db.execute(query.limit(page_size + 1)).scalars().all()
        else:
            tools = db.execute(query).scalars().all()

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Check if there are more results (only when paginating)
        has_more = page_size is not None and len(tools) > page_size
        if has_more:
            tools = tools[:page_size]

        # Convert to ToolRead objects
        result = []
        for tool in tools:
            try:
                result.append(self.convert_tool_to_read(tool, include_metrics=False, include_auth=False, requesting_user_email=user_email, requesting_user_is_admin=False))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert tool {getattr(tool, 'id', 'unknown')} ({getattr(tool, 'name', 'unknown')}): {e}")
                # Continue with remaining tools instead of failing completely

        next_cursor = None
        # Generate cursor if there are more results (cursor-based pagination)
        if has_more and tools:
            last_tool = tools[-1]
            next_cursor = encode_cursor({"created_at": last_tool.created_at.isoformat(), "id": last_tool.id})

        return (result, next_cursor)

    async def get_tool(
        self,
        db: Session,
        tool_id: str,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> ToolRead:
        """
        Retrieve a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

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
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.get_tool(db, 'tool_id'))
            'tool_read'
        """
        tool = db.get(DbTool, tool_id)
        if not tool:
            raise ToolNotFoundError(f"Tool not found: {tool_id}")

        tool_read = self.convert_tool_to_read(
            tool,
            requesting_user_email=requesting_user_email,
            requesting_user_is_admin=requesting_user_is_admin,
            requesting_user_team_roles=requesting_user_team_roles,
        )

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

    async def delete_tool(self, db: Session, tool_id: str, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """
        Delete a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            user_email (Optional[str]): Email of user performing delete (for ownership check).
            purge_metrics (bool): If True, delete raw + rollup metrics for this tool.

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

            if purge_metrics:
                with pause_rollup_during_purge(reason=f"purge_tool:{tool_id}"):
                    delete_metrics_in_batches(db, ToolMetric, ToolMetric.tool_id, tool_id)
                    delete_metrics_in_batches(db, ToolMetricsHourly, ToolMetricsHourly.tool_id, tool_id)

            # Use DELETE with rowcount check for database-agnostic atomic delete
            # (RETURNING is not supported on MySQL/MariaDB)
            stmt = delete(DbTool).where(DbTool.id == tool_id)
            result = db.execute(stmt)
            if result.rowcount == 0:
                # Tool was already deleted by another concurrent request
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

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
                    "purge_metrics": purge_metrics,
                },
                db=db,
            )

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(tool_name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()
            # Invalidate top performers cache
            # First-Party
            from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

            metrics_cache.invalidate_prefix("top_tools:")
            metrics_cache.invalidate("tools")
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

    async def set_tool_state(self, db: Session, tool_id: str, activate: bool, reachable: bool, user_email: Optional[str] = None, skip_cache_invalidation: bool = False) -> ToolRead:
        """
        Set the activation status of a tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            activate (bool): True to activate, False to deactivate.
            reachable (bool): True if the tool is reachable.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.
            skip_cache_invalidation: If True, skip cache invalidation (used for batch operations).

        Returns:
            ToolRead: The updated tool object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            ToolLockConflictError: If the tool row is locked by another transaction.
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
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.set_tool_state(db, 'tool_id', True, True))
            'tool_read'
        """
        try:
            # Use nowait=True to fail fast if row is locked, preventing lock contention under high load
            try:
                tool = get_for_update(db, DbTool, tool_id, nowait=True)
            except OperationalError as lock_err:
                # Row is locked by another transaction - fail fast with 409
                db.rollback()
                raise ToolLockConflictError(f"Tool {tool_id} is currently being modified by another request") from lock_err
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

                # Invalidate cache after status change (skip for batch operations)
                if not skip_cache_invalidation:
                    cache = _get_registry_cache()
                    await cache.invalidate_tools()
                    tool_lookup_cache = _get_tool_lookup_cache()
                    await tool_lookup_cache.invalidate(tool.name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)

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

                # Structured logging: Audit trail for tool state change
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="set_tool_state",
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

                # Structured logging: Log successful tool state change
                structured_logger.log(
                    level="INFO",
                    message=f"Tool {'activated' if activate else 'deactivated'} successfully",
                    event_type="tool_state_changed",
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

            return self.convert_tool_to_read(tool, requesting_user_email=getattr(tool, "owner_email", None))
        except PermissionError as e:
            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool state change failed due to permission error",
                event_type="tool_state_change_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
                db=db,
            )
            raise e
        except ToolLockConflictError:
            # Re-raise lock conflicts without wrapping - allows 409 response
            raise
        except ToolNotFoundError:
            # Re-raise not found without wrapping - allows 404 response
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool state change failure
            structured_logger.log(
                level="ERROR",
                message="Tool state change failed",
                event_type="tool_state_change_failed",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
                db=db,
            )
            raise ToolError(f"Failed to set tool state: {str(e)}")

    async def invoke_tool_direct(
        self,
        gateway_id: str,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Optional[Dict[str, str]] = None,
        meta_data: Optional[Dict[str, Any]] = None,
    ) -> types.CallToolResult:
        """
        Invoke a tool directly on a remote MCP gateway in direct_proxy mode.

        This bypasses all gateway processing (caching, plugins, validation) and forwards
        the tool call directly to the remote MCP server, returning the raw result.

        Args:
            gateway_id: Gateway ID to invoke the tool on.
            name: Name of tool to invoke.
            arguments: Tool arguments.
            request_headers: Headers from the request to pass through.
            meta_data: Optional metadata dictionary for additional context (e.g., request ID).

        Returns:
            CallToolResult from the remote MCP server (as-is, no normalization).

        Raises:
            ToolNotFoundError: If gateway not found.
            ToolInvocationError: If invocation fails.
        """
        logger.info(f"Direct proxy tool invocation: {name} via gateway {gateway_id}")

        # Look up gateway
        # First-Party
        from mcpgateway.db import Gateway as DbGateway  # pylint: disable=import-outside-toplevel
        from mcpgateway.utils.services_auth import decode_auth  # pylint: disable=import-outside-toplevel

        # Use a fresh session for this lookup
        with fresh_db_session() as db:
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
            if not gateway:
                raise ToolNotFoundError(f"Gateway {gateway_id} not found")

            if getattr(gateway, "gateway_mode", "cache") != "direct_proxy":
                raise ToolInvocationError(f"Gateway {gateway_id} is not in direct_proxy mode")

            # Prepare headers with gateway auth
            headers = {}
            if gateway.auth_type == "bearer" and gateway.auth_value:
                if isinstance(gateway.auth_value, dict):
                    token = gateway.auth_value.get("Authorization", "").replace("Bearer ", "")
                    headers["Authorization"] = f"Bearer {token}"
                elif isinstance(gateway.auth_value, str):
                    decoded = decode_auth(gateway.auth_value)
                    headers["Authorization"] = decoded.get("Authorization", "")
            elif gateway.auth_type == "basic" and gateway.auth_value:
                if isinstance(gateway.auth_value, dict):
                    headers["Authorization"] = gateway.auth_value.get("Authorization", "")
                elif isinstance(gateway.auth_value, str):
                    decoded = decode_auth(gateway.auth_value)
                    headers["Authorization"] = decoded.get("Authorization", "")

            # Forward passthrough headers if configured
            if gateway.passthrough_headers and request_headers:
                for header_name in gateway.passthrough_headers:
                    header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
                    if header_value:
                        headers[header_name] = header_value

            gateway_url = gateway.url

        # Use MCP SDK to connect and call tool
        try:
            async with streamablehttp_client(url=gateway_url, headers=headers, timeout=30.0) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    # Call tool with meta if provided
                    if meta_data:
                        logger.debug(f"Forwarding _meta to remote gateway: {meta_data}")
                        tool_result = await session.call_tool(name=name, arguments=arguments, meta=meta_data)
                    else:
                        tool_result = await session.call_tool(name=name, arguments=arguments)

                    logger.info(f"[INVOKE TOOL] Using direct_proxy mode for gateway {gateway.id} (from X-Context-Forge-Gateway-Id header). Meta Attached: {meta_data is not None}")
                    return tool_result
        except Exception as e:
            logger.exception(f"Direct proxy tool invocation failed for {name}: {e}")
            raise ToolInvocationError(f"Direct proxy tool invocation failed: {str(e)}")

    async def invoke_tool(
        self,
        db: Session,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Optional[Dict[str, str]] = None,
        app_user_email: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        server_id: Optional[str] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
        meta_data: Optional[Dict[str, Any]] = None,
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
            user_email (Optional[str], optional): User email for authorization checks.
                None = unauthenticated request.
            token_teams (Optional[List[str]], optional): Team IDs from JWT token for authorization.
                None = unrestricted admin, [] = public-only, [...] = team-scoped.
            server_id (Optional[str], optional): Virtual server ID for server scoping enforcement.
                If provided, tool must be attached to this server.
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.
            meta_data: Optional metadata dictionary for additional context (e.g., request ID).

        Returns:
            Tool invocation result.

        Raises:
            ToolNotFoundError: If tool not found or access denied.
            ToolInvocationError: If invocation fails.
            ToolTimeoutError: If tool invocation times out.
            PluginViolationError: If plugin blocks tool invocation.
            PluginError: If encounters issue with plugin

        Examples:
            >>> # Note: This method requires extensive mocking of SQLAlchemy models,
            >>> # database relationships, and caching infrastructure, which is not
            >>> # suitable for doctests. See tests/unit/mcpgateway/services/test_tool_service.py
            >>> pass  # doctest: +SKIP
        """
        # pylint: disable=comparison-with-callable
        logger.info(f"Invoking tool: {name} with arguments: {arguments.keys() if arguments else None} and headers: {request_headers.keys() if request_headers else None}")

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Check for X-Context-Forge-Gateway-Id header for direct_proxy mode (no DB lookup)
        # ═══════════════════════════════════════════════════════════════════════════
        gateway_id_from_header = None
        if request_headers:
            for header_name, header_value in request_headers.items():
                if header_name.lower() == "x-context-forge-gateway-id":
                    gateway_id_from_header = header_value
                    break

        # If X-Context-Forge-Gateway-Id header is present, check if gateway is in direct_proxy mode
        is_direct_proxy = False
        tool = None
        gateway = None
        tool_payload: Dict[str, Any] = {}
        gateway_payload: Optional[Dict[str, Any]] = None

        if gateway_id_from_header:
            # Look up gateway to check if it's in direct_proxy mode
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id_from_header)).scalar_one_or_none()
            if gateway and gateway.gateway_mode == "direct_proxy":
                is_direct_proxy = True
                # Build minimal gateway payload for direct proxy (no tool lookup needed)
                gateway_payload = {
                    "id": str(gateway.id),
                    "name": gateway.name,
                    "url": gateway.url,
                    "auth_type": gateway.auth_type,
                    "auth_value": gateway.auth_value,
                    "auth_query_params": gateway.auth_query_params,
                    "oauth_config": gateway.oauth_config,
                    "ca_certificate": gateway.ca_certificate,
                    "ca_certificate_sig": gateway.ca_certificate_sig,
                    "passthrough_headers": gateway.passthrough_headers,
                    "gateway_mode": gateway.gateway_mode,
                }
                # Create minimal tool payload for direct proxy (no DB tool needed)
                tool_payload = {
                    "id": None,  # No tool ID in direct proxy mode
                    "name": name,
                    "original_name": name,
                    "enabled": True,
                    "reachable": True,
                    "integration_type": "MCP",
                    "request_type": "streamablehttp",  # Default to streamablehttp
                    "gateway_id": str(gateway.id),
                }
                logger.info(f"Direct proxy mode via X-Context-Forge-Gateway-Id header: passing tool '{name}' directly to remote MCP server at {gateway.url}")
            elif gateway:
                logger.debug(f"Gateway {gateway_id_from_header} found but not in direct_proxy mode (mode: {gateway.gateway_mode}), using normal lookup")
            else:
                logger.warning(f"Gateway {gateway_id_from_header} specified in X-Context-Forge-Gateway-Id header not found")

        # Normal mode: look up tool in database/cache
        if not is_direct_proxy:
            tool_lookup_cache = _get_tool_lookup_cache()
            cached_payload = await tool_lookup_cache.get(name) if tool_lookup_cache.enabled else None

            if cached_payload:
                status = cached_payload.get("status", "active")
                if status == "missing":
                    raise ToolNotFoundError(f"Tool not found: {name}")
                if status == "inactive":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
                if status == "offline":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")
                tool_payload = cached_payload.get("tool") or {}
                gateway_payload = cached_payload.get("gateway")

            if not tool_payload:
                # Eager load tool WITH gateway in single query to prevent lazy load N+1
                # Use a single query to avoid a race between separate enabled/inactive lookups.
                tool = db.execute(select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.name == name)).scalar_one_or_none()
                if not tool:
                    raise ToolNotFoundError(f"Tool not found: {name}")
                if not tool.enabled:
                    raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")

                if not tool.reachable:
                    await tool_lookup_cache.set_negative(name, "offline")
                    raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

                gateway = tool.gateway
                cache_payload = self._build_tool_cache_payload(tool, gateway)
                tool_payload = cache_payload.get("tool") or {}
                gateway_payload = cache_payload.get("gateway")
                await tool_lookup_cache.set(name, cache_payload, gateway_id=tool_payload.get("gateway_id"))

            if tool_payload.get("enabled") is False:
                raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
            if tool_payload.get("reachable") is False:
                raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

        # ═══════════════════════════════════════════════════════════════════════════
        # SECURITY: Check tool access based on visibility and team membership
        # Skip these checks for direct_proxy mode (no tool in database)
        # ═══════════════════════════════════════════════════════════════════════════
        if not is_direct_proxy:
            if not await self._check_tool_access(db, tool_payload, user_email, token_teams):
                # Don't reveal tool existence - return generic "not found"
                raise ToolNotFoundError(f"Tool not found: {name}")

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY: Enforce server scoping if server_id is provided
            # Tool must be attached to the specified virtual server
            # ═══════════════════════════════════════════════════════════════════════════
            if server_id:
                tool_id_for_check = tool_payload.get("id")
                if not tool_id_for_check:
                    # Cannot verify server membership without tool ID - deny access
                    # This should not happen with properly cached tools, but fail safe
                    logger.warning(f"Tool '{name}' has no ID in payload, cannot verify server membership")
                    raise ToolNotFoundError(f"Tool not found: {name}")

                server_match = db.execute(
                    select(server_tool_association.c.tool_id).where(
                        server_tool_association.c.server_id == server_id,
                        server_tool_association.c.tool_id == tool_id_for_check,
                    )
                ).first()
                if not server_match:
                    raise ToolNotFoundError(f"Tool not found: {name}")

        # Extract A2A-related data from annotations (will be used after db.close() if A2A tool)
        tool_annotations = tool_payload.get("annotations") or {}
        tool_integration_type = tool_payload.get("integration_type")

        # Get passthrough headers from in-memory cache (Issue #1715)
        # This eliminates 42,000+ redundant DB queries under load
        passthrough_allowed = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)

        # Access gateway now (already eager-loaded) to prevent later lazy load
        if tool is not None:
            gateway = tool.gateway

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 2: Extract all needed data to local variables before network I/O
        # This allows us to release the DB session before making HTTP calls
        # ═══════════════════════════════════════════════════════════════════════════
        tool_id = tool_payload.get("id") or (str(tool.id) if tool else "")
        tool_name_original = tool_payload.get("original_name") or tool_payload.get("name") or name
        tool_name_computed = tool_payload.get("name") or name
        tool_url = tool_payload.get("url")
        tool_integration_type = tool_payload.get("integration_type")
        tool_request_type = tool_payload.get("request_type")
        tool_headers = dict(tool_payload.get("headers") or {})
        tool_auth_type = tool_payload.get("auth_type")
        tool_auth_value = tool_payload.get("auth_value")
        tool_jsonpath_filter = tool_payload.get("jsonpath_filter")
        tool_output_schema = tool_payload.get("output_schema")
        tool_oauth_config = tool_payload.get("oauth_config")
        tool_gateway_id = tool_payload.get("gateway_id")

        # Get effective timeout: per-tool timeout_ms (in seconds) or global fallback
        # timeout_ms is stored in milliseconds, convert to seconds
        tool_timeout_ms = tool_payload.get("timeout_ms")
        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else settings.tool_timeout

        # Save gateway existence as local boolean BEFORE db.close()
        # to avoid checking ORM object truthiness after session is closed
        has_gateway = gateway_payload is not None
        gateway_url = gateway_payload.get("url") if has_gateway else None
        gateway_name = gateway_payload.get("name") if has_gateway else None
        gateway_auth_type = gateway_payload.get("auth_type") if has_gateway else None
        gateway_auth_value = gateway_payload.get("auth_value") if has_gateway else None
        gateway_auth_query_params = gateway_payload.get("auth_query_params") if has_gateway else None
        gateway_oauth_config = gateway_payload.get("oauth_config") if has_gateway else None
        gateway_ca_cert = gateway_payload.get("ca_certificate") if has_gateway else None
        gateway_ca_cert_sig = gateway_payload.get("ca_certificate_sig") if has_gateway else None
        gateway_passthrough = gateway_payload.get("passthrough_headers") if has_gateway else None
        gateway_id_str = gateway_payload.get("id") if has_gateway else None
        gateway_mode = gateway_payload.get("gateway_mode", "cache") if has_gateway else "cache"

        # Decrypt and apply query param auth to URL if applicable
        gateway_auth_query_params_decrypted: Optional[Dict[str, str]] = None
        if gateway_auth_type == "query_param" and gateway_auth_query_params:
            # Decrypt the query param values
            gateway_auth_query_params_decrypted = {}
            for param_key, encrypted_value in gateway_auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        gateway_auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:  # noqa: S110 - intentionally skip failed decryptions
                        # Silently skip params that fail decryption (may be corrupted or use old key)
                        logger.debug(f"Failed to decrypt query param '{param_key}' for tool invocation")
            # Apply query params to gateway URL
            if gateway_auth_query_params_decrypted and gateway_url:
                gateway_url = apply_query_param_auth(gateway_url, gateway_auth_query_params_decrypted)

        # Create Pydantic models for plugins BEFORE HTTP calls (use ORM objects while still valid)
        # This prevents lazy loading during HTTP calls
        tool_metadata: Optional[PydanticTool] = None
        gateway_metadata: Optional[PydanticGateway] = None
        if self._plugin_manager:
            if tool is not None:
                tool_metadata = PydanticTool.model_validate(tool)
                if has_gateway and gateway is not None:
                    gateway_metadata = PydanticGateway.model_validate(gateway)
            else:
                tool_metadata = self._pydantic_tool_from_payload(tool_payload)
                if has_gateway and gateway_payload:
                    gateway_metadata = self._pydantic_gateway_from_payload(gateway_payload)

        tool_for_validation = tool if tool is not None else SimpleNamespace(output_schema=tool_output_schema, name=tool_name_computed)

        # ═══════════════════════════════════════════════════════════════════════════
        # A2A Agent Data Extraction (must happen before db.close())
        # Extract all A2A agent data to local variables so HTTP call can happen after db.close()
        # ═══════════════════════════════════════════════════════════════════════════
        a2a_agent_name: Optional[str] = None
        a2a_agent_endpoint_url: Optional[str] = None
        a2a_agent_type: Optional[str] = None
        a2a_agent_protocol_version: Optional[str] = None
        a2a_agent_auth_type: Optional[str] = None
        a2a_agent_auth_value: Optional[str] = None
        a2a_agent_auth_query_params: Optional[Dict[str, str]] = None

        if tool_integration_type == "A2A" and "a2a_agent_id" in tool_annotations:
            a2a_agent_id = tool_annotations.get("a2a_agent_id")
            if not a2a_agent_id:
                raise ToolNotFoundError(f"A2A tool '{name}' missing agent ID in annotations")

            # Query for the A2A agent
            agent_query = select(DbA2AAgent).where(DbA2AAgent.id == a2a_agent_id)
            a2a_agent = db.execute(agent_query).scalar_one_or_none()

            if not a2a_agent:
                raise ToolNotFoundError(f"A2A agent not found for tool '{name}' (agent ID: {a2a_agent_id})")

            if not a2a_agent.enabled:
                raise ToolNotFoundError(f"A2A agent '{a2a_agent.name}' is disabled")

            # Extract all needed data to local variables before db.close()
            a2a_agent_name = a2a_agent.name
            a2a_agent_endpoint_url = a2a_agent.endpoint_url
            a2a_agent_type = a2a_agent.agent_type
            a2a_agent_protocol_version = a2a_agent.protocol_version
            a2a_agent_auth_type = a2a_agent.auth_type
            a2a_agent_auth_value = a2a_agent.auth_value
            a2a_agent_auth_query_params = a2a_agent.auth_query_params

        # ═══════════════════════════════════════════════════════════════════════════
        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents connection pool exhaustion during slow upstream requests.
        # All needed data has been extracted to local variables above.
        # The session will be closed again by FastAPI's get_db() finally block (safe no-op).
        # ═══════════════════════════════════════════════════════════════════════════
        db.commit()  # End read-only transaction cleanly (commit not rollback to avoid inflating rollback stats)
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
            if not plugin_global_context.user and app_user_email and isinstance(app_user_email, str):
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

        # Get trace_id from context for database span creation
        trace_id = current_trace_id.get()
        db_span_id = None
        db_span_ended = False
        observability_service = ObservabilityService() if trace_id else None

        # Create database span for observability_spans table
        if trace_id and observability_service:
            try:
                # Re-open database session for span creation (original was closed at line 2285)
                # Use commit=False since fresh_db_session() handles commits on exit
                with fresh_db_session() as span_db:
                    db_span_id = observability_service.start_span(
                        db=span_db,
                        trace_id=trace_id,
                        name="tool.invoke",
                        kind="client",
                        resource_type="tool",
                        resource_name=name,
                        resource_id=tool_id,
                        attributes={
                            "tool.name": name,
                            "tool.id": tool_id,
                            "tool.integration_type": tool_integration_type,
                            "tool.gateway_id": tool_gateway_id,
                            "arguments_count": len(arguments) if arguments else 0,
                            "has_headers": bool(request_headers),
                        },
                        commit=False,
                    )
                    logger.debug(f"✓ Created tool.invoke span: {db_span_id} for tool: {name}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for tool invocation: {e}")
                db_span_id = None

        # Create a trace span for OpenTelemetry export (Jaeger, Zipkin, etc.)
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
                            request_headers,
                            headers,
                            passthrough_allowed,
                            gateway_auth_type=None,
                            gateway_passthrough_headers=None,  # REST tools don't use gateway auth here
                        )
                        # Read MCP-Session-Id from downstream client (MCP protocol header)
                        # and normalize to x-mcp-session-id for our internal session affinity logic
                        # The pool will strip this before sending to upstream
                        # Check both mcp-session-id (direct client) and x-mcp-session-id (forwarded requests)
                        request_headers_lower = {k.lower(): v for k, v in request_headers.items()}
                        mcp_session_id = request_headers_lower.get("mcp-session-id") or request_headers_lower.get("x-mcp-session-id")
                        if mcp_session_id:
                            headers["x-mcp-session-id"] = mcp_session_id

                            worker_id = str(os.getpid())
                            session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id
                            logger.debug(f"[AFFINITY] Worker {worker_id} | Session {session_short}... | Tool: {name} | Normalized MCP-Session-Id → x-mcp-session-id for pool affinity")

                    if self._plugin_manager and self._plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE):
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
                    rest_start_time = time.time()
                    try:
                        if method == "GET":
                            response = await asyncio.wait_for(self._http_client.get(final_url, params=payload, headers=headers), timeout=effective_timeout)
                        else:
                            response = await asyncio.wait_for(self._http_client.request(method, final_url, json=payload, headers=headers), timeout=effective_timeout)
                    except (asyncio.TimeoutError, httpx.TimeoutException):
                        rest_elapsed_ms = (time.time() - rest_start_time) * 1000
                        structured_logger.log(
                            level="WARNING",
                            message=f"REST tool invocation timed out: {tool_name_computed}",
                            component="tool_service",
                            correlation_id=get_correlation_id(),
                            duration_ms=rest_elapsed_ms,
                            metadata={"event": "tool_timeout", "tool_name": tool_name_computed, "timeout_seconds": effective_timeout},
                        )

                        # Manually trigger circuit breaker (or other plugins) on timeout
                        try:
                            # First-Party
                            from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                            tool_timeout_counter.labels(tool_name=name).inc()
                        except Exception as exc:
                            logger.debug(
                                "Failed to increment tool_timeout_counter for %s: %s",
                                name,
                                exc,
                                exc_info=True,
                            )

                        if self._plugin_manager:
                            if context_table:
                                for ctx in context_table.values():
                                    ctx.set_state("cb_timeout_failure", True)

                            if self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                                timeout_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation timed out after {effective_timeout}s")], is_error=True)
                                await self._plugin_manager.invoke_hook(
                                    ToolHookType.TOOL_POST_INVOKE,
                                    payload=ToolPostInvokePayload(name=name, result=timeout_error_result.model_dump(by_alias=True)),
                                    global_context=global_context,
                                    local_contexts=context_table,
                                    violations_as_exceptions=False,
                                )

                        raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
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
                        # Check if extract_using_jq returned an error (list of TextContent objects)
                        if isinstance(filtered_response, list) and len(filtered_response) > 0 and isinstance(filtered_response[0], TextContent):
                            # Error case - use the TextContent directly
                            tool_result = ToolResult(content=filtered_response, is_error=True)
                            success = False
                        else:
                            # Success case - serialize the filtered response
                            serialized = orjson.dumps(filtered_response, option=orjson.OPT_INDENT_2)
                            tool_result = ToolResult(content=[TextContent(type="text", text=serialized.decode())])
                            success = True
                        # If output schema is present, validate and attach structured content
                        if tool_output_schema:
                            valid = self._extract_and_validate_structured_content(tool_for_validation, tool_result, candidate=filtered_response)
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
                        # Read MCP-Session-Id from downstream client (MCP protocol header)
                        # and normalize to x-mcp-session-id for our internal session affinity logic
                        # The pool will strip this before sending to upstream
                        # Check both mcp-session-id (direct client) and x-mcp-session-id (forwarded requests)
                        request_headers_lower = {k.lower(): v for k, v in request_headers.items()}
                        mcp_session_id = request_headers_lower.get("mcp-session-id") or request_headers_lower.get("x-mcp-session-id")
                        if mcp_session_id:
                            headers["x-mcp-session-id"] = mcp_session_id

                            worker_id = str(os.getpid())
                            session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id
                            logger.debug(f"[AFFINITY] Worker {worker_id} | Session {session_short}... | Tool: {name} | Normalized MCP-Session-Id → x-mcp-session-id for pool affinity (MCP transport)")

                    def create_ssl_context(ca_certificate: str) -> ssl.SSLContext:
                        """Create an SSL context with the provided CA certificate.

                        Uses caching to avoid repeated SSL context creation for the same certificate.

                        Args:
                            ca_certificate: CA certificate in PEM format

                        Returns:
                            ssl.SSLContext: Configured SSL context
                        """
                        return get_cached_ssl_context(ca_certificate)

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
                        # First-Party
                        from mcpgateway.services.http_client_service import get_default_verify, get_http_timeout  # pylint: disable=import-outside-toplevel

                        if valid:
                            ctx = create_ssl_context(gateway_ca_cert)
                        else:
                            ctx = None

                        # Use effective_timeout for read operations if not explicitly overridden by caller
                        # This ensures the underlying client waits at least as long as the tool configuration requires
                        factory_timeout = timeout if timeout else get_http_timeout(read_timeout=effective_timeout)

                        return httpx.AsyncClient(
                            verify=ctx if ctx else get_default_verify(),
                            follow_redirects=True,
                            headers=headers,
                            timeout=factory_timeout,
                            auth=auth,
                            limits=httpx.Limits(
                                max_connections=settings.httpx_max_connections,
                                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                                keepalive_expiry=settings.httpx_keepalive_expiry,
                            ),
                        )

                    async def connect_to_sse_server(server_url: str, headers: dict = headers):
                        """Connect to an MCP server running with SSE transport.

                        Args:
                            server_url: MCP Server SSE URL
                            headers: HTTP headers to include in the request

                        Returns:
                            ToolResult: Result of tool call

                        Raises:
                            ToolInvocationError: If the tool invocation fails during execution.
                            ToolTimeoutError: If the tool invocation times out.
                            BaseException: On connection or communication errors

                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()

                        # NOTE: X-Correlation-ID is NOT added to headers for pooled sessions.
                        # MCP SDK pins headers at transport creation, so adding per-request headers
                        # would cause the first request's correlation ID to be reused for all
                        # subsequent requests on the same pooled session. Correlation IDs are
                        # still logged locally for tracing within the gateway.

                        # Log MCP call start (using local variables)
                        # Sanitize server_url to redact sensitive query params from logs
                        server_url_sanitized = sanitize_url_for_logging(server_url, gateway_auth_query_params_decrypted)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url_sanitized, "transport": "sse"},
                        )

                        try:
                            # Use session pool if enabled for 10-20x latency improvement
                            use_pool = False
                            pool = None
                            if settings.mcp_session_pool_enabled:
                                try:
                                    pool = get_mcp_session_pool()
                                    use_pool = True
                                except RuntimeError:
                                    # Pool not initialized (e.g., in tests), fall back to per-call sessions
                                    pass

                            if use_pool and pool is not None:
                                # Pooled path: do NOT add per-request headers (they would be pinned)
                                async with pool.session(
                                    url=server_url,
                                    headers=headers,
                                    transport_type=TransportType.SSE,
                                    httpx_client_factory=get_httpx_client_factory,
                                    user_identity=app_user_email,
                                    gateway_id=gateway_id_str,
                                ) as pooled:
                                    tool_call_result = await asyncio.wait_for(pooled.session.call_tool(tool_name_original, arguments, meta=meta_data), timeout=effective_timeout)
                            else:
                                # Non-pooled path: safe to add per-request headers
                                if correlation_id and headers:
                                    headers["X-Correlation-ID"] = correlation_id
                                # Fallback to per-call sessions when pool disabled or not initialized
                                async with sse_client(url=server_url, headers=headers, httpx_client_factory=get_httpx_client_factory) as streams:
                                    async with ClientSession(*streams) as session:
                                        await session.initialize()
                                        tool_call_result = await asyncio.wait_for(session.call_tool(tool_name_original, arguments, meta=meta_data), timeout=effective_timeout)

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
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            # Handle timeout specifically - log and raise ToolInvocationError
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"MCP SSE tool invocation timed out: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "tool_timeout", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse", "timeout_seconds": effective_timeout},
                            )

                            # Manually trigger circuit breaker (or other plugins) on timeout
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug(
                                    "Failed to increment tool_timeout_counter for %s: %s",
                                    name,
                                    exc,
                                    exc_info=True,
                                )

                            if self._plugin_manager:
                                if context_table:
                                    for ctx in context_table.values():
                                        ctx.set_state("cb_timeout_failure", True)

                                if self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                                    timeout_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation timed out after {effective_timeout}s")], is_error=True)
                                    await self._plugin_manager.invoke_hook(
                                        ToolHookType.TOOL_POST_INVOKE,
                                        payload=ToolPostInvokePayload(name=name, result=timeout_error_result.model_dump(by_alias=True)),
                                        global_context=global_context,
                                        local_contexts=context_table,
                                        violations_as_exceptions=False,
                                    )

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        except BaseException as e:
                            # Extract root cause from ExceptionGroup (Python 3.11+)
                            # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                            root_cause = e
                            if isinstance(e, BaseExceptionGroup):
                                while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                                    root_cause = root_cause.exceptions[0]
                            # Log failed MCP call (using local variables)
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            # Sanitize error message to prevent URL secrets from leaking in logs
                            sanitized_error = sanitize_exception_message(str(root_cause), gateway_auth_query_params_decrypted)
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(root_cause).__name__, "error_message": sanitized_error},
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
                            ToolInvocationError: If the tool invocation fails during execution.
                            ToolTimeoutError: If the tool invocation times out.
                            BaseException: On connection or communication errors
                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()

                        # NOTE: X-Correlation-ID is NOT added to headers for pooled sessions.
                        # MCP SDK pins headers at transport creation, so adding per-request headers
                        # would cause the first request's correlation ID to be reused for all
                        # subsequent requests on the same pooled session. Correlation IDs are
                        # still logged locally for tracing within the gateway.

                        # Log MCP call start (using local variables)
                        # Sanitize server_url to redact sensitive query params from logs
                        server_url_sanitized = sanitize_url_for_logging(server_url, gateway_auth_query_params_decrypted)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url_sanitized, "transport": "streamablehttp"},
                        )

                        try:
                            # Use session pool if enabled for 10-20x latency improvement
                            use_pool = False
                            pool = None
                            if settings.mcp_session_pool_enabled:
                                try:
                                    pool = get_mcp_session_pool()
                                    use_pool = True
                                except RuntimeError:
                                    # Pool not initialized (e.g., in tests), fall back to per-call sessions
                                    pass

                            if use_pool and pool is not None:
                                # Pooled path: do NOT add per-request headers (they would be pinned)
                                # Determine transport type based on current transport setting
                                pool_transport_type = TransportType.SSE if transport == "sse" else TransportType.STREAMABLE_HTTP
                                async with pool.session(
                                    url=server_url,
                                    headers=headers,
                                    transport_type=pool_transport_type,
                                    httpx_client_factory=get_httpx_client_factory,
                                    user_identity=app_user_email,
                                    gateway_id=gateway_id_str,
                                ) as pooled:
                                    tool_call_result = await asyncio.wait_for(pooled.session.call_tool(tool_name_original, arguments, meta=meta_data), timeout=effective_timeout)
                            else:
                                # Non-pooled path: safe to add per-request headers
                                if correlation_id and headers:
                                    headers["X-Correlation-ID"] = correlation_id

                                # Fallback to per-call sessions when pool disabled or not initialized
                                async with streamablehttp_client(url=server_url, headers=headers, httpx_client_factory=get_httpx_client_factory) as (read_stream, write_stream, _get_session_id):
                                    async with ClientSession(read_stream, write_stream) as session:
                                        await session.initialize()
                                        tool_call_result = await asyncio.wait_for(session.call_tool(tool_name_original, arguments, meta=meta_data), timeout=effective_timeout)

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
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            # Handle timeout specifically - log and raise ToolInvocationError
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"MCP StreamableHTTP tool invocation timed out: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "tool_timeout", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp", "timeout_seconds": effective_timeout},
                            )

                            # Manually trigger circuit breaker (or other plugins) on timeout
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug(
                                    "Failed to increment tool_timeout_counter for %s: %s",
                                    name,
                                    exc,
                                    exc_info=True,
                                )

                            if self._plugin_manager:
                                if context_table:
                                    for ctx in context_table.values():
                                        ctx.set_state("cb_timeout_failure", True)

                                if self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                                    timeout_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation timed out after {effective_timeout}s")], is_error=True)
                                    await self._plugin_manager.invoke_hook(
                                        ToolHookType.TOOL_POST_INVOKE,
                                        payload=ToolPostInvokePayload(name=name, result=timeout_error_result.model_dump(by_alias=True)),
                                        global_context=global_context,
                                        local_contexts=context_table,
                                        violations_as_exceptions=False,
                                    )

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        except BaseException as e:
                            # Extract root cause from ExceptionGroup (Python 3.11+)
                            # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                            root_cause = e
                            if isinstance(e, BaseExceptionGroup):
                                while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                                    root_cause = root_cause.exceptions[0]
                            # Log failed MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            # Sanitize error message to prevent URL secrets from leaking in logs
                            sanitized_error = sanitize_exception_message(str(root_cause), gateway_auth_query_params_decrypted)
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(root_cause).__name__, "error_message": sanitized_error},
                                metadata={"event": "mcp_call_failed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp"},
                            )
                            raise

                    # REMOVED: Redundant gateway query - gateway already eager-loaded via joinedload
                    # tool_gateway = db.execute(select(DbGateway).where(DbGateway.id == tool_gateway_id)...)

                    if self._plugin_manager and self._plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE):
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

                    # In direct proxy mode, use the tool result as-is without splitting content
                    if is_direct_proxy:
                        tool_result = tool_call_result
                        success = not getattr(tool_call_result, "is_error", False) and not getattr(tool_call_result, "isError", False)
                        logger.debug(f"Direct proxy mode: using tool result as-is: {tool_result}")
                    else:
                        dump = tool_call_result.model_dump(by_alias=True, mode="json")
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

                elif tool_integration_type == "A2A" and a2a_agent_endpoint_url:
                    # A2A tool invocation using pre-extracted agent data (extracted in Phase 2 before db.close())
                    headers = {"Content-Type": "application/json"}

                    # Plugin hook: tool pre-invoke for A2A
                    if self._plugin_manager and self._plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE):
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        pre_result, context_table = await self._plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
                            global_context=global_context,
                            local_contexts=context_table,
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    # Build request data based on agent type
                    endpoint_url = a2a_agent_endpoint_url
                    if a2a_agent_type in ["generic", "jsonrpc"] or endpoint_url.endswith("/"):
                        # JSONRPC agents: Convert flat query to nested message structure
                        params = None
                        if isinstance(arguments, dict) and "query" in arguments and isinstance(arguments["query"], str):
                            message_id = f"admin-test-{int(time.time())}"
                            # A2A v0.3.x: message.parts use "kind" (not "type").
                            params = {
                                "message": {
                                    "kind": "message",
                                    "messageId": message_id,
                                    "role": "user",
                                    "parts": [{"kind": "text", "text": arguments["query"]}],
                                }
                            }
                            method = arguments.get("method", "message/send")
                        else:
                            params = arguments.get("params", arguments) if isinstance(arguments, dict) else arguments
                            method = arguments.get("method", "message/send") if isinstance(arguments, dict) else "message/send"
                        request_data = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
                    else:
                        # Custom agents: Pass parameters directly
                        params = arguments if isinstance(arguments, dict) else {}
                        request_data = {"interaction_type": params.get("interaction_type", "query"), "parameters": params, "protocol_version": a2a_agent_protocol_version}

                    # Add authentication
                    if a2a_agent_auth_type == "api_key" and a2a_agent_auth_value:
                        headers["Authorization"] = f"Bearer {a2a_agent_auth_value}"
                    elif a2a_agent_auth_type == "bearer" and a2a_agent_auth_value:
                        headers["Authorization"] = f"Bearer {a2a_agent_auth_value}"
                    elif a2a_agent_auth_type == "query_param" and a2a_agent_auth_query_params:
                        auth_query_params_decrypted: dict[str, str] = {}
                        for param_key, encrypted_value in a2a_agent_auth_query_params.items():
                            if encrypted_value:
                                try:
                                    decrypted = decode_auth(encrypted_value)
                                    auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                                except Exception:
                                    logger.debug(f"Failed to decrypt query param for key '{param_key}'")
                        if auth_query_params_decrypted:
                            endpoint_url = apply_query_param_auth(endpoint_url, auth_query_params_decrypted)

                    # Make HTTP request with timeout enforcement
                    logger.info(f"Calling A2A agent '{a2a_agent_name}' at {endpoint_url}")
                    a2a_start_time = time.time()
                    try:
                        http_response = await asyncio.wait_for(self._http_client.post(endpoint_url, json=request_data, headers=headers), timeout=effective_timeout)
                    except (asyncio.TimeoutError, httpx.TimeoutException):
                        a2a_elapsed_ms = (time.time() - a2a_start_time) * 1000
                        structured_logger.log(
                            level="WARNING",
                            message=f"A2A tool invocation timed out: {name}",
                            component="tool_service",
                            correlation_id=get_correlation_id(),
                            duration_ms=a2a_elapsed_ms,
                            metadata={"event": "tool_timeout", "tool_name": name, "a2a_agent": a2a_agent_name, "timeout_seconds": effective_timeout},
                        )

                        # Increment timeout counter
                        try:
                            # First-Party
                            from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                            tool_timeout_counter.labels(tool_name=name).inc()
                        except Exception as exc:
                            logger.debug("Failed to increment tool_timeout_counter for %s: %s", name, exc, exc_info=True)

                        # Trigger circuit breaker on timeout
                        if self._plugin_manager:
                            if context_table:
                                for ctx in context_table.values():
                                    ctx.set_state("cb_timeout_failure", True)

                            if self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                                timeout_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation timed out after {effective_timeout}s")], is_error=True)
                                await self._plugin_manager.invoke_hook(
                                    ToolHookType.TOOL_POST_INVOKE,
                                    payload=ToolPostInvokePayload(name=name, result=timeout_error_result.model_dump(by_alias=True)),
                                    global_context=global_context,
                                    local_contexts=context_table,
                                    violations_as_exceptions=False,
                                )

                        raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")

                    if http_response.status_code == 200:
                        response_data = http_response.json()
                        if isinstance(response_data, dict) and "response" in response_data:
                            content = [TextContent(type="text", text=str(response_data["response"]))]
                        else:
                            content = [TextContent(type="text", text=str(response_data))]
                        tool_result = ToolResult(content=content, is_error=False)
                        success = True
                    else:
                        error_message = f"HTTP {http_response.status_code}: {http_response.text}"
                        content = [TextContent(type="text", text=f"A2A agent error: {error_message}")]
                        tool_result = ToolResult(content=content, is_error=True)
                else:
                    tool_result = ToolResult(content=[TextContent(type="text", text="Invalid tool type")], is_error=True)

                # Plugin hook: tool post-invoke
                if self._plugin_manager and self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
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
            except ToolTimeoutError as e:
                # ToolTimeoutError is raised by timeout handlers which already called tool_post_invoke
                # Re-raise without calling post_invoke again to avoid double-counting failures
                # But DO set error_message and span attributes for observability
                error_message = str(e)
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", error_message)
                raise
            except BaseException as e:
                # Extract root cause from ExceptionGroup (Python 3.11+)
                # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                root_cause = e
                if isinstance(e, BaseExceptionGroup):
                    while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                        root_cause = root_cause.exceptions[0]
                error_message = str(root_cause)
                # Set span error status
                if span:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", error_message)

                # Notify plugins of the failure so circuit breaker can track it
                # This ensures HTTP 4xx/5xx errors and MCP failures are counted
                if self._plugin_manager and self._plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                    try:
                        exception_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation failed: {error_message}")], is_error=True)
                        await self._plugin_manager.invoke_hook(
                            ToolHookType.TOOL_POST_INVOKE,
                            payload=ToolPostInvokePayload(name=name, result=exception_error_result.model_dump(by_alias=True)),
                            global_context=global_context,
                            local_contexts=context_table,
                            violations_as_exceptions=False,  # Don't let plugin errors mask the original exception
                        )
                    except Exception as plugin_exc:
                        logger.debug("Failed to invoke post-invoke plugins on exception: %s", plugin_exc)

                raise ToolInvocationError(f"Tool invocation failed: {error_message}")
            finally:
                # Calculate duration
                duration_ms = (time.monotonic() - start_time) * 1000

                # End database span for observability_spans table
                # Use commit=False since fresh_db_session() handles commits on exit
                if db_span_id and observability_service and not db_span_ended:
                    try:
                        with fresh_db_session() as span_db:
                            observability_service.end_span(
                                db=span_db,
                                span_id=db_span_id,
                                status="ok" if success else "error",
                                status_message=error_message if error_message else None,
                                attributes={
                                    "success": success,
                                    "duration_ms": duration_ms,
                                },
                                commit=False,
                            )
                            db_span_ended = True
                            logger.debug(f"✓ Ended tool.invoke span: {db_span_id}")
                    except Exception as e:
                        logger.warning(f"Failed to end observability span for tool invocation: {e}")

                # Add final span attributes for OpenTelemetry
                if span:
                    span.set_attribute("success", success)
                    span.set_attribute("duration.ms", duration_ms)

                # ═══════════════════════════════════════════════════════════════════════════
                # PHASE 4: Record metrics via buffered service (batches writes for performance)
                # ═══════════════════════════════════════════════════════════════════════════
                # Only record metrics if tool_id is valid (skip for direct_proxy mode)
                if tool_id:
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
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.update_tool(db, 'tool_id', MagicMock()))
            'tool_read'
        """
        try:
            tool = get_for_update(db, DbTool, tool_id)

            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            old_tool_name = tool.name
            old_gateway_id = tool.gateway_id

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
                    # Check for existing public tool with the same name (row-locked)
                    existing_tool = get_for_update(
                        db,
                        DbTool,
                        where=and_(
                            DbTool.custom_name == tool_update.custom_name,
                            DbTool.visibility == "public",
                            DbTool.id != tool.id,
                        ),
                    )
                    if existing_tool:
                        raise ToolNameConflictError(existing_tool.custom_name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)
                elif tool_update.visibility.lower() == "team" and tool_update.team_id:
                    # Check for existing team tool with the same name
                    existing_tool = get_for_update(
                        db,
                        DbTool,
                        where=and_(
                            DbTool.custom_name == tool_update.custom_name,
                            DbTool.visibility == "team",
                            DbTool.team_id == tool_update.team_id,
                            DbTool.id != tool.id,
                        ),
                    )
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

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(old_tool_name, gateway_id=str(old_gateway_id) if old_gateway_id else None)
            await tool_lookup_cache.invalidate(tool.name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return self.convert_tool_to_read(tool, requesting_user_email=getattr(tool, "owner_email", None))
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

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session

        Returns:
            Aggregated metrics computed from raw ToolMetric + ToolMetricsHourly.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> # Method exists and is callable
            >>> callable(service.aggregate_metrics)
            True
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("tools")
            if cached is not None:
                return cached

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "tool")
        metrics = result.to_dict()

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set("tools", metrics)

        return metrics

    async def reset_metrics(self, db: Session, tool_id: Optional[int] = None) -> None:
        """
        Reset all tool metrics by deleting raw and hourly rollup records.

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
            db.execute(delete(ToolMetricsHourly).where(ToolMetricsHourly.tool_id == tool_id))
        else:
            db.execute(delete(ToolMetric))
            db.execute(delete(ToolMetricsHourly))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("tools")
        metrics_cache.invalidate_prefix("top_tools:")

    async def create_tool_from_a2a_agent(
        self,
        db: Session,
        agent: DbA2AAgent,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
    ) -> DbTool:
        """Create a tool entry from an A2A agent for virtual server integration.

        Args:
            db: Database session.
            agent: A2A agent to create tool from.
            created_by: Username who created this tool.
            created_from_ip: IP address of creator.
            created_via: Creation method.
            created_user_agent: User agent of creation request.

        Returns:
            The created tool database object.

        Raises:
            ToolNameConflictError: If a tool with the same name already exists.
        """
        # Check if tool already exists for this agent
        tool_name = f"a2a_{agent.slug}"
        existing_query = select(DbTool).where(DbTool.original_name == tool_name)
        existing_tool = db.execute(existing_query).scalar_one_or_none()

        if existing_tool:
            # Tool already exists, return it
            return existing_tool

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

        # Default to "public" visibility if agent visibility is not set
        # This ensures A2A tools are visible in the Global Tools Tab
        tool_visibility = agent.visibility or "public"

        tool_read = await self.register_tool(
            db,
            tool_data,
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via or "a2a_integration",
            created_user_agent=created_user_agent,
            team_id=agent.team_id,
            owner_email=agent.owner_email,
            visibility=tool_visibility,
        )

        # Return the DbTool object for relationship assignment
        tool_db = db.get(DbTool, tool_read.id)
        return tool_db

    async def update_tool_from_a2a_agent(
        self,
        db: Session,
        agent: DbA2AAgent,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> Optional[ToolRead]:
        """Update the tool associated with an A2A agent when the agent is updated.

        Args:
            db: Database session.
            agent: Updated A2A agent.
            modified_by: Username who modified this tool.
            modified_from_ip: IP address of modifier.
            modified_via: Modification method.
            modified_user_agent: User agent of modification request.

        Returns:
            The updated tool, or None if no associated tool exists.
        """
        # Use the tool_id from the agent for efficient lookup
        if not agent.tool_id:
            logger.debug(f"No tool_id found for A2A agent {agent.id}, skipping tool update")
            return None

        tool = db.get(DbTool, agent.tool_id)
        if not tool:
            logger.warning(f"Tool {agent.tool_id} not found for A2A agent {agent.id}, resetting tool_id")
            agent.tool_id = None
            db.commit()
            return None

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

        # Prepare update data matching the agent's current state
        # IMPORTANT: Preserve the existing tool's visibility to avoid unintentionally
        # making private/team tools public (ToolUpdate defaults to "public")
        # Note: team_id is not a field on ToolUpdate schema, so team assignment is preserved
        # implicitly by not changing visibility (team tools stay team-scoped)
        new_tool_name = f"a2a_{agent.slug}"
        tool_update = ToolUpdate(
            name=new_tool_name,
            custom_name=new_tool_name,  # Also set custom_name to ensure name update works
            displayName=generate_display_name(agent.name),
            url=agent.endpoint_url,
            description=f"A2A Agent: {agent.description or agent.name}",
            auth=AuthenticationValues(auth_type=agent.auth_type, auth_value=agent.auth_value) if agent.auth_type else None,
            tags=normalized_tags,
            visibility=tool.visibility,  # Preserve existing visibility
        )

        # Update the tool
        return await self.update_tool(
            db=db,
            tool_id=tool.id,
            tool_update=tool_update,
            modified_by=modified_by,
            modified_from_ip=modified_from_ip,
            modified_via=modified_via or "a2a_sync",
            modified_user_agent=modified_user_agent,
        )

    async def delete_tool_from_a2a_agent(self, db: Session, agent: DbA2AAgent, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """Delete the tool associated with an A2A agent when the agent is deleted.

        Args:
            db: Database session.
            agent: The A2A agent being deleted.
            user_email: Email of user performing delete (for ownership check).
            purge_metrics: If True, delete raw + rollup metrics for this tool.
        """
        # Use the tool_id from the agent for efficient lookup
        if not agent.tool_id:
            logger.debug(f"No tool_id found for A2A agent {agent.id}, skipping tool deletion")
            return

        tool = db.get(DbTool, agent.tool_id)
        if not tool:
            logger.warning(f"Tool {agent.tool_id} not found for A2A agent {agent.id}")
            return

        # Delete the tool
        await self.delete_tool(db=db, tool_id=tool.id, user_email=user_email, purge_metrics=purge_metrics)
        logger.info(f"Deleted tool {tool.id} associated with A2A agent {agent.id}")

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

        # Force-load all attributes needed by _call_a2a_agent before detaching
        # (accessing them ensures they're loaded into the object's __dict__)
        _ = (agent.name, agent.endpoint_url, agent.agent_type, agent.protocol_version, agent.auth_type, agent.auth_value, agent.auth_query_params)

        # Detach agent from session so its loaded data remains accessible after close
        db.expunge(agent)

        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents "idle in transaction" connection pool exhaustion under load
        db.commit()
        db.close()

        # Prepare parameters for A2A invocation
        try:
            # Make the A2A agent call (agent is now detached but data is loaded)
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

        # Build request data based on agent type
        if agent.agent_type in ["generic", "jsonrpc"] or agent.endpoint_url.endswith("/"):
            # JSONRPC agents: Convert flat query to nested message structure
            params = None
            if isinstance(parameters, dict) and "query" in parameters and isinstance(parameters["query"], str):
                # Build the nested message object for JSONRPC protocol
                message_id = f"admin-test-{int(time.time())}"
                # A2A v0.3.x: message.parts use "kind" (not "type").
                params = {
                    "message": {
                        "kind": "message",
                        "messageId": message_id,
                        "role": "user",
                        "parts": [{"kind": "text", "text": parameters["query"]}],
                    }
                }
                method = parameters.get("method", "message/send")
            else:
                # Already in correct format or unknown, pass through
                params = parameters.get("params", parameters)
                method = parameters.get("method", "message/send")

            try:
                request_data = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
                logger.info(f"invoke tool JSONRPC request_data prepared: {request_data}")
            except Exception as e:
                logger.error(f"Error preparing JSONRPC request data: {e}")
                raise
        else:
            # Custom agents: Pass parameters directly without JSONRPC message conversion
            # Custom agents expect flat fields like {"query": "...", "message": "..."}
            params = parameters if isinstance(parameters, dict) else {}
            logger.info(f"invoke tool Using custom A2A format for A2A agent '{params}'")
            request_data = {"interaction_type": params.get("interaction_type", "query"), "parameters": params, "protocol_version": agent.protocol_version}
        logger.info(f"invoke tool request_data prepared: {request_data}")
        # Make HTTP request to the agent endpoint using shared HTTP client
        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        headers = {"Content-Type": "application/json"}

        # Determine the endpoint URL (may be modified for query_param auth)
        endpoint_url = agent.endpoint_url

        # Add authentication if configured
        if agent.auth_type == "api_key" and agent.auth_value:
            headers["Authorization"] = f"Bearer {agent.auth_value}"
        elif agent.auth_type == "bearer" and agent.auth_value:
            headers["Authorization"] = f"Bearer {agent.auth_value}"
        elif agent.auth_type == "query_param" and agent.auth_query_params:
            # Handle query parameter authentication (imports at top: decode_auth, apply_query_param_auth, sanitize_url_for_logging)
            auth_query_params_decrypted: dict[str, str] = {}
            for param_key, encrypted_value in agent.auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:
                        logger.debug(f"Failed to decrypt query param for key '{param_key}'")
            if auth_query_params_decrypted:
                endpoint_url = apply_query_param_auth(endpoint_url, auth_query_params_decrypted)
                # Log sanitized URL to avoid credential leakage
                sanitized_url = sanitize_url_for_logging(endpoint_url, auth_query_params_decrypted)
                logger.debug(f"Applied query param auth to A2A agent endpoint: {sanitized_url}")

        http_response = await client.post(endpoint_url, json=request_data, headers=headers)

        if http_response.status_code == 200:
            return http_response.json()

        raise Exception(f"HTTP {http_response.status_code}: {http_response.text}")


# Lazy singleton - created on first access, not at module import time.
# This avoids instantiation when only exception classes are imported.
_tool_service_instance = None  # pylint: disable=invalid-name


def __getattr__(name: str):
    """Module-level __getattr__ for lazy singleton creation.

    Args:
        name: The attribute name being accessed.

    Returns:
        The tool_service singleton instance if name is "tool_service".

    Raises:
        AttributeError: If the attribute name is not "tool_service".
    """
    global _tool_service_instance  # pylint: disable=global-statement
    if name == "tool_service":
        if _tool_service_instance is None:
            _tool_service_instance = ToolService()
        return _tool_service_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
