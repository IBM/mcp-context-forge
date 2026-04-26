# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/prompt_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Prompt Service Implementation.
This module implements prompt template management according to the MCP specification.
It handles:
- Prompt template registration and retrieval
- Prompt argument validation
- Template rendering with arguments
- Resource embedding in prompts
- Active/inactive prompt management
"""

# Standard
import binascii
from datetime import datetime, timezone
from functools import lru_cache
from string import Formatter
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union
import uuid

# Third-Party
from jinja2 import meta, select_autoescape, Template
from jinja2.exceptions import SecurityError as JinjaSecurityError
from jinja2.sandbox import SandboxedEnvironment
from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import GetPromptRequest, GetPromptRequestParams
import orjson
from pydantic import ValidationError
from sqlalchemy import and_, delete, desc, not_, or_, select
from sqlalchemy.exc import IntegrityError, MultipleResultsFound, OperationalError
from sqlalchemy.orm import joinedload, selectinload, Session

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.common.validators import validate_meta_data as _validate_meta_data
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam
from mcpgateway.db import EmailTeamMember as DbEmailTeamMember
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_for_update
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric, PromptMetricsHourly, server_prompt_association
from mcpgateway.observability import create_span, set_span_attribute, set_span_error
from mcpgateway.plugins.framework import GlobalContext, PluginContextTable, PromptHookType, PromptPosthookPayload, PromptPrehookPayload
from mcpgateway.schemas import PromptCreate, PromptMetrics, PromptRead, PromptUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.content_security import ContentPatternError, ContentSizeError, get_content_security_service, TemplateValidationError
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context as _downstream_session_id_from_request
from mcpgateway.services.upstream_session_registry import get_upstream_session_registry, RegistryNotInitializedError, TransportType
from mcpgateway.utils.admin_check import is_user_admin
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.gateway_access import build_gateway_auth_headers
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.services_auth import decode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr
from mcpgateway.utils.trace_context import format_trace_team_scope
from mcpgateway.utils.trace_redaction import is_input_capture_enabled, is_output_capture_enabled, serialize_trace_payload
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_exception_message

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None

# Module-level Jinja environment singleton for template caching
_JINJA_ENV: Optional[SandboxedEnvironment] = None


def _get_jinja_env() -> SandboxedEnvironment:
    """Get or create the module-level Jinja environment singleton.

    Uses SandboxedEnvironment (not plain Environment) so rendered templates
    cannot reach Python internals via __class__, __mro__, __subclasses__,
    getattr chains, etc. Regex-based template blocklist validation in
    content_security.validate_prompt_template() catches only literal
    occurrences in the template source; SandboxedEnvironment is what
    actually enforces the restriction at render time against hex escapes,
    string concatenation, attr() filter chains, and other well-known SSTI
    techniques. This is the primary defense; the regex list is advisory.

    Returns:
        Jinja2 SandboxedEnvironment with autoescape and trim settings.
    """
    global _JINJA_ENV  # pylint: disable=global-statement
    if _JINJA_ENV is None:
        _JINJA_ENV = SandboxedEnvironment(
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _JINJA_ENV


@lru_cache(maxsize=256)
def _compile_jinja_template(template: str) -> Template:
    """Cache compiled Jinja template by template string.

    Args:
        template: The template string to compile.

    Returns:
        Compiled Jinja Template object.
    """
    return _get_jinja_env().from_string(template)


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


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

# Initialize structured logger, audit trail, and metrics buffer for prompt operations
structured_logger = get_structured_logger("prompt_service")
audit_trail = get_audit_trail_service()
metrics_buffer = get_metrics_buffer_service()


def _build_get_prompt_request(name: str, arguments: Optional[Dict[str, str]], meta_data: Dict[str, Any]) -> "types.ClientRequest":
    """Build a GetPrompt ClientRequest that carries _meta (CWE-20, CWE-284).

    Using ``by_alias=True`` ensures the Pydantic alias ``_meta`` is the only
    key written into the dict so the subsequent ``model_validate`` call
    resolves it correctly regardless of ``populate_by_name`` settings.

    ``send_request`` is used instead of ``session.get_prompt()`` because the
    MCP SDK helper does not expose a ``_meta`` parameter; this wrapper must be
    updated if the SDK later adds that capability.

    Args:
        name: The prompt name.
        arguments: Optional prompt arguments.
        meta_data: Validated metadata dict to inject as ``_meta``.

    Returns:
        A :class:`types.ClientRequest` ready to be passed to ``session.send_request``.
    """
    _gp_dict = GetPromptRequestParams(name=name, arguments=arguments).model_dump(by_alias=True)
    _gp_dict["_meta"] = meta_data
    return types.ClientRequest(GetPromptRequest(params=GetPromptRequestParams.model_validate(_gp_dict)))


async def _get_prompt_with_meta(session: "ClientSession", name: str, arguments: Optional[Dict[str, str]], meta_data: Optional[Dict[str, Any]]) -> Any:
    """Dispatch a get_prompt call, injecting ``_meta`` when meta_data is provided.

    Eliminates the repeated ``if meta_data: send_request … else: get_prompt``
    pattern across every transport/pool branch in this module.

    Args:
        session: An active MCP :class:`ClientSession`.
        name: The prompt name.
        arguments: Optional prompt-rendering arguments.
        meta_data: Optional validated metadata dict. When ``None`` the standard
            SDK helper is used; when non-empty the low-level ``send_request``
            path is taken to carry ``_meta``.

    Returns:
        The raw MCP result object (caller extracts ``.messages``).
    """
    if meta_data:
        return await session.send_request(
            _build_get_prompt_request(name, arguments, meta_data),
            types.GetPromptResult,
        )
    return await session.get_prompt(name, arguments=arguments)


class PromptError(Exception):
    """Base class for prompt-related errors."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt is not found."""


class PromptNameConflictError(PromptError):
    """Raised when a prompt name conflicts with existing (active or inactive) prompt."""

    def __init__(self, name: str, enabled: bool = True, prompt_id: Optional[int] = None, visibility: str = "public") -> None:
        """Initialize the error with prompt information.

        Args:
            name: The conflicting prompt name
            enabled: Whether the existing prompt is enabled
            prompt_id: ID of the existing prompt if available
            visibility: Prompt visibility level (private, team, public).

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptNameConflictError
            >>> error = PromptNameConflictError("test_prompt")
            >>> error.name
            'test_prompt'
            >>> error.enabled
            True
            >>> error.prompt_id is None
            True
            >>> error = PromptNameConflictError("inactive_prompt", False, 123)
            >>> error.enabled
            False
            >>> error.prompt_id
            123
        """
        self.name = name
        self.enabled = enabled
        self.prompt_id = prompt_id
        message = f"{visibility.capitalize()} Prompt already exists with name: {name}"
        if not enabled:
            message += f" (currently inactive, ID: {prompt_id})"
        super().__init__(message)


class PromptValidationError(PromptError):
    """Raised when prompt validation fails."""


class PromptArgumentsJSONError(PromptError):
    """Raised when prompt arguments JSON is invalid.

    Attributes:
        field_name: Name of the field containing invalid JSON
        raw_value: First 200 characters of the invalid JSON string
        json_error: The original JSON parsing error message
    """

    def __init__(self, field_name: str, json_error: str, raw_value: str = "", context: str = "") -> None:
        """Initialize the error with JSON parsing details.

        Args:
            field_name: Name of the field (e.g., "arguments")
            json_error: The JSON parsing error message
            raw_value: First 200 characters of the invalid JSON (for logging)
            context: Optional context about where the error occurred (e.g., "prompt abc-123")

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptArgumentsJSONError
            >>> error = PromptArgumentsJSONError("arguments", "unexpected character: line 1 column 5")
            >>> error.field_name
            'arguments'
            >>> str(error)
            'Invalid JSON in arguments field: unexpected character: line 1 column 5'
        """
        self.field_name = field_name
        self.json_error = json_error
        self.raw_value = raw_value[:200] if raw_value else ""
        self.context = context
        context_str = f" for {context}" if context else ""
        message = f"Invalid JSON in {field_name} field{context_str}: {json_error}"
        super().__init__(message)


class PromptLockConflictError(PromptError):
    """Raised when a prompt row is locked by another transaction.

    Raises:
        PromptLockConflictError: When attempting to modify a prompt that is
            currently locked by another concurrent request.
    """


def _validate_prompt_team_assignment(db: Session, user_email: Optional[str], target_team_id: Optional[str]) -> None:
    """Validate team assignment for prompt updates.

    Args:
        db: Database session used for membership checks.
        user_email: Requesting user email. When omitted, ownership checks are skipped.
        target_team_id: Team identifier to validate.

    Raises:
        ValueError: If team does not exist or caller lacks ownership.
    """
    if not target_team_id:
        raise ValueError("Cannot set visibility to 'team' without a team_id")

    team = db.query(EmailTeam).filter(EmailTeam.id == target_team_id).first()
    if not team:
        raise ValueError(f"Team {target_team_id} not found")

    if not user_email:
        return

    membership = (
        db.query(DbEmailTeamMember)
        .filter(DbEmailTeamMember.team_id == target_team_id, DbEmailTeamMember.user_email == user_email, DbEmailTeamMember.is_active, DbEmailTeamMember.role == "owner")
        .first()
    )
    if not membership:
        raise ValueError("User membership in team not sufficient for this update.")


class PromptService(BaseService):
    """Service for managing prompt templates.

    Handles:
    - Template registration and retrieval
    - Argument validation
    - Template rendering
    - Resource embedding
    - Active/inactive status management
    """

    _visibility_model_cls = DbPrompt

    def __init__(self) -> None:
        """
        Initialize the prompt service.

        Sets up the Jinja2 environment for rendering prompt templates.
        Although these templates are rendered as JSON for the API, if the output is ever
        embedded into an HTML page, unescaped content could be exploited for cross-site scripting (XSS) attacks.
        Enabling autoescaping for 'html' and 'xml' templates via select_autoescape helps mitigate this risk.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> isinstance(service._event_service, EventService)
            True
            >>> service._jinja_env is not None
            True
        """
        self._event_service = EventService(channel_name="mcpgateway:prompt_events")
        # Use the module-level singleton for template caching
        self._jinja_env = _get_jinja_env()

    @staticmethod
    def _should_fetch_gateway_prompt(prompt: DbPrompt) -> bool:
        """Return whether a prompt must be executed against its source gateway.

        Federated prompts are synced into the catalog as metadata via
        ``list_prompts()``. Those records often have ``template=""``, which
        means the gateway must call the upstream MCP ``prompts/get`` endpoint
        instead of trying to render a local template.

        Args:
            prompt: Prompt ORM object resolved from the catalog.

        Returns:
            ``True`` when the prompt is gateway-backed and has no local template.
        """
        return bool(getattr(prompt, "gateway_id", None)) and not bool(getattr(prompt, "template", ""))

    async def _fetch_gateway_prompt_result(self, prompt: DbPrompt, arguments: Optional[Dict[str, str]], meta_data: Optional[Dict[str, Any]] = None) -> PromptResult:
        """Fetch a rendered prompt from the upstream MCP gateway.

        Args:
            prompt: Gateway-backed prompt record from the catalog.
            arguments: Optional prompt-rendering arguments.
            meta_data: Optional metadata dict forwarded as ``_meta`` in the upstream MCP request.

        Returns:
            Prompt result normalized into ContextForge models.

        Raises:
            PromptError: If the gateway prompt cannot be fetched.
        """
        gateway = getattr(prompt, "gateway", None)
        if gateway is None:
            raise PromptError(f"Prompt '{prompt.name}' is gateway-backed but missing gateway metadata")

        gateway_url = str(gateway.url)
        headers = build_gateway_auth_headers(gateway)
        auth_query_params_decrypted: Optional[Dict[str, str]] = None

        if getattr(gateway, "auth_type", None) == "query_param" and getattr(gateway, "auth_query_params", None):
            auth_query_params_decrypted = {}
            for param_key, encrypted_value in (gateway.auth_query_params or {}).items():
                try:
                    decoded = decode_auth(encrypted_value)
                    auth_query_params_decrypted[param_key] = decoded.get(param_key, "")
                except Exception as exc:
                    raise PromptError(f"Failed to decode query-parameter auth for prompt gateway '{gateway.id}'") from exc
            if auth_query_params_decrypted:
                gateway_url = apply_query_param_auth(gateway_url, auth_query_params_decrypted)

        remote_name = getattr(prompt, "original_name", None) or prompt.name
        gateway_id = str(getattr(gateway, "id", ""))
        transport = str(getattr(gateway, "transport", "streamable_http") or "streamable_http").lower()
        registry_transport_type = TransportType.SSE if transport == "sse" else TransportType.STREAMABLE_HTTP
        prompt_arguments = arguments or None
        # CWE-400: Validate meta_data limits before forwarding to upstream
        _validate_meta_data(meta_data)

        try:
            # #4205: Use the upstream session registry when a downstream Mcp-Session-Id
            # is in scope; this binds the upstream session 1:1 to the downstream
            # session and preserves connection reuse across its tool/prompt calls.
            downstream_session_id = _downstream_session_id_from_request()
            if downstream_session_id and gateway_id:
                try:
                    registry = get_upstream_session_registry()
                except RegistryNotInitializedError:
                    registry = None
                if registry is not None:
                    async with registry.acquire(
                        downstream_session_id=downstream_session_id,
                        gateway_id=gateway_id,
                        url=gateway_url,
                        headers=headers,
                        transport_type=registry_transport_type,
                    ) as upstream:
                        remote_result = await _get_prompt_with_meta(upstream.session, remote_name, prompt_arguments, meta_data)
                        return PromptResult(
                            messages=[
                                Message.model_validate(message.model_dump(by_alias=True, exclude_none=True) if hasattr(message, "model_dump") else message)
                                for message in getattr(remote_result, "messages", []) or []
                            ],
                            description=getattr(remote_result, "description", None) or prompt.description,
                        )

            if transport == "sse":
                async with sse_client(url=gateway_url, headers=headers, timeout=settings.health_check_timeout) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        remote_result = await _get_prompt_with_meta(session, remote_name, prompt_arguments, meta_data)
            else:
                async with streamablehttp_client(url=gateway_url, headers=headers, timeout=settings.health_check_timeout) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        remote_result = await _get_prompt_with_meta(session, remote_name, prompt_arguments, meta_data)

            return PromptResult(
                messages=[
                    Message.model_validate(message.model_dump(by_alias=True, exclude_none=True) if hasattr(message, "model_dump") else message)
                    for message in getattr(remote_result, "messages", []) or []
                ],
                description=getattr(remote_result, "description", None) or prompt.description,
            )
        except Exception as exc:
            sanitized_error = sanitize_exception_message(str(exc), auth_query_params_decrypted)
            raise PromptError(f"Failed to fetch prompt '{remote_name}' from gateway: {sanitized_error}") from exc

    @staticmethod
    def validate_arguments_json(args_value: Any, context: str = "") -> List[Dict[str, Any]]:
        """Validate and parse prompt arguments JSON.

        Args:
            args_value: The raw arguments value from form data
            context: Additional context for error messages (e.g., "prompt 123", "new prompt")

        Returns:
            Parsed arguments as a list of dictionaries

        Raises:
            PromptArgumentsJSONError: If the JSON is invalid

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> PromptService.validate_arguments_json('[]')
            []
            >>> PromptService.validate_arguments_json('[{"name": "test"}]')
            [{'name': 'test'}]
            >>> PromptService.validate_arguments_json(None)
            []
            >>> try:
            ...     PromptService.validate_arguments_json('invalid json')
            ... except PromptArgumentsJSONError as e:
            ...     print(e.field_name)
            arguments
        """
        # Handle None or empty values
        if args_value is None or args_value == "":
            return []

        # Ensure it's a string
        if not isinstance(args_value, str):
            args_value = str(args_value)

        # Strip whitespace
        args_value = args_value.strip()

        # If still empty after strip, return empty list
        if not args_value:
            return []

        # Parse JSON
        try:
            arguments = orjson.loads(args_value)

            # Ensure the result is a list (JSON array)
            if not isinstance(arguments, list):
                error_msg = f"Arguments must be a JSON array, got {type(arguments).__name__}"
                logger.error(f"Invalid arguments type{' for ' + context if context else ''}: {error_msg}. " f"Raw value (first 200 chars): {args_value[:200]!r}")
                raise PromptArgumentsJSONError(field_name="arguments", json_error=error_msg, raw_value=args_value, context=context)

            return arguments
        except orjson.JSONDecodeError as json_err:
            # Log the error with context
            logger.error(f"Invalid JSON in arguments field{' for ' + context if context else ''}: {json_err}. " f"Raw value (first 200 chars): {args_value[:200]!r}")
            # Raise custom exception
            raise PromptArgumentsJSONError(field_name="arguments", json_error=str(json_err), raw_value=args_value, context=context) from json_err

    async def initialize(self) -> None:
        """Initialize the service."""
        logger.info("Initializing prompt service")
        await self._event_service.initialize()

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import AsyncMock
            >>> import asyncio
            >>> service = PromptService()
            >>> service._event_service = AsyncMock()
            >>> asyncio.run(service.shutdown())
            >>> # Verify event service shutdown was called
            >>> service._event_service.shutdown.assert_awaited_once()
        """
        await self._event_service.shutdown()
        logger.info("Prompt service shutdown complete")

    async def get_top_prompts(self, db: Session, limit: Optional[int] = 5, include_deleted: bool = False) -> List[TopPerformer]:
        """Retrieve the top-performing prompts based on execution count.

        Queries the database to get prompts with their metrics, ordered by the number of executions
        in descending order. Combines recent raw metrics with historical hourly rollups for complete
        historical coverage. Returns a list of TopPerformer objects containing prompt details and
        performance metrics. Results are cached for performance.

        Args:
            db (Session): Database session for querying prompt metrics.
            limit (Optional[int]): Maximum number of prompts to return. Defaults to 5.
            include_deleted (bool): Whether to include deleted prompts from rollups.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Prompt ID.
                - name: Prompt name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        effective_limit = limit or 5
        cache_key = f"top_prompts:{effective_limit}:include_deleted={include_deleted}"

        if is_cache_enabled():
            cached = metrics_cache.get(cache_key)
            if cached is not None:
                return cached

        # Use combined query that includes both raw metrics and rollup data
        # First-Party
        from mcpgateway.services.metrics_query_service import get_top_performers_combined  # pylint: disable=import-outside-toplevel

        results = get_top_performers_combined(
            db,
            metric_type="prompt",
            entity_model=DbPrompt,
            limit=effective_limit,
            include_deleted=include_deleted,
        )
        top_performers = build_top_performers(results)

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set(cache_key, top_performers)

        return top_performers

    def convert_prompt_to_read(self, db_prompt: DbPrompt, include_metrics: bool = False) -> PromptRead:
        """
        Convert a DbPrompt instance to a PromptRead Pydantic model,
        optionally including aggregated metrics computed from the associated PromptMetric records.

        Args:
            db_prompt: Db prompt to convert
            include_metrics: Whether to include metrics in the result. Defaults to False.
                Set to False for list operations to avoid N+1 query issues.

        Returns:
            PromptRead: Pydantic model instance
        """
        arg_schema = db_prompt.argument_schema or {}
        properties = arg_schema.get("properties", {})
        required_list = arg_schema.get("required", [])
        arguments_list = []
        for arg_name, prop in properties.items():
            arguments_list.append(
                {
                    "name": arg_name,
                    "description": prop.get("description") or "",
                    "required": arg_name in required_list,
                }
            )

        # Compute aggregated metrics only if requested (avoids N+1 queries in list operations)
        if include_metrics:
            # Use metrics_summary which combines raw + hourly rollup data (matches tool_service pattern)
            metrics = db_prompt.metrics_summary
            metrics_dict = {
                "totalExecutions": metrics["total_executions"],
                "successfulExecutions": metrics["successful_executions"],
                "failedExecutions": metrics["failed_executions"],
                "failureRate": metrics["failure_rate"],
                "minResponseTime": metrics["min_response_time"],
                "maxResponseTime": metrics["max_response_time"],
                "avgResponseTime": metrics["avg_response_time"],
                "lastExecutionTime": metrics["last_execution_time"],
            }
        else:
            metrics_dict = None

        original_name = getattr(db_prompt, "original_name", None) or db_prompt.name
        custom_name = getattr(db_prompt, "custom_name", None) or original_name
        custom_name_slug = getattr(db_prompt, "custom_name_slug", None) or slugify(custom_name)
        display_name = getattr(db_prompt, "display_name", None) or custom_name

        prompt_dict = {
            "id": db_prompt.id,
            "name": db_prompt.name,
            "original_name": original_name,
            "custom_name": custom_name,
            "custom_name_slug": custom_name_slug,
            "display_name": display_name,
            "gateway_id": getattr(db_prompt, "gateway_id", None),
            "gateway_slug": getattr(db_prompt, "gateway_slug", None),
            "description": db_prompt.description,
            "template": db_prompt.template,
            "arguments": arguments_list,
            "created_at": db_prompt.created_at,
            "updated_at": db_prompt.updated_at,
            "enabled": db_prompt.enabled,
            "metrics": metrics_dict,
            "tags": db_prompt.tags or [],
            "visibility": db_prompt.visibility,
            "team": getattr(db_prompt, "team", None),
            # Include metadata fields for proper API response
            "created_by": getattr(db_prompt, "created_by", None),
            "modified_by": getattr(db_prompt, "modified_by", None),
            "created_from_ip": getattr(db_prompt, "created_from_ip", None),
            "created_via": getattr(db_prompt, "created_via", None),
            "created_user_agent": getattr(db_prompt, "created_user_agent", None),
            "modified_from_ip": getattr(db_prompt, "modified_from_ip", None),
            "modified_via": getattr(db_prompt, "modified_via", None),
            "modified_user_agent": getattr(db_prompt, "modified_user_agent", None),
            "version": getattr(db_prompt, "version", None),
            "team_id": getattr(db_prompt, "team_id", None),
            "owner_email": getattr(db_prompt, "owner_email", None),
        }
        return PromptRead.model_validate(prompt_dict)

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
        db.commit()  # Release transaction to avoid idle-in-transaction
        return team.name if team else None

    def _compute_prompt_name(self, custom_name: str, gateway: Optional[Any] = None) -> str:
        """Compute the stored prompt name from custom_name and gateway context.

        Args:
            custom_name: Prompt name to slugify and store.
            gateway: Optional gateway for namespacing.

        Returns:
            The stored prompt name with gateway prefix when applicable.
        """
        name_slug = slugify(custom_name)
        if gateway:
            gateway_slug = slugify(gateway.name)
            return f"{gateway_slug}{settings.gateway_tool_name_separator}{name_slug}"
        return name_slug

    async def register_prompt(
        self,
        db: Session,
        prompt: PromptCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
    ) -> PromptRead:
        """Register a new prompt template.

        Args:
            db: Database session
            prompt: Prompt creation schema
            created_by: Username who created this prompt
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, import, federation)
            created_user_agent: User agent of creation request
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated prompts
            team_id (Optional[str]): Team ID to assign the prompt to.
            owner_email (Optional[str]): Email of the user who owns this prompt.
            visibility (str): Prompt visibility level (private, team, public).

        Returns:
            Created prompt information

        Raises:
            IntegrityError: If a database integrity error occurs.
            PromptNameConflictError: If a prompt with the same name already exists.
            PromptError: For other prompt registration errors
            ContentSizeError: For template size exceed
            ContentPatternError: If template contains malicious patterns (US-3)
            TemplateValidationError: For template security violations (US-4)

        Examples:
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import AsyncMock, MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> prompt.template = "Hello {{ name }}"
            >>> prompt.name = "test-prompt"
            >>> prompt.custom_name = None
            >>> prompt.display_name = None
            >>> prompt.arguments = []
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_added = AsyncMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.register_prompt(db, prompt))
            ... except Exception:
            ...     pass
            >>> logging.disable(logging.NOTSET)
        """
        try:
            content_security = get_content_security_service()
            content_security.validate_prompt_size(
                template=prompt.template,
                name=prompt.name,
                user_email=created_by or owner_email,
                ip_address=created_from_ip,
            )

            # Validate template security (US-4)
            content_security.validate_prompt_template(
                template=prompt.template,
                name=prompt.name,
                user_email=created_by or owner_email,
                ip_address=created_from_ip,
            )

            # Note: Template syntax validation is now handled by validate_prompt_template above
            # No need for duplicate _validate_template call

            # Extract required arguments from template
            required_args = self._get_required_arguments(prompt.template)

            # Create argument schema
            argument_schema = {
                "type": "object",
                "properties": {},
                "required": list(required_args),
            }
            for arg in prompt.arguments:
                schema = {"type": "string"}
                if arg.description is not None:
                    schema["description"] = arg.description
                argument_schema["properties"][arg.name] = schema

            custom_name = prompt.custom_name or prompt.name
            display_name = prompt.display_name or custom_name

            # Extract gateway_id from prompt if present and look up gateway for namespacing
            gateway_id = getattr(prompt, "gateway_id", None)
            gateway = None
            if gateway_id:
                gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()

            computed_name = self._compute_prompt_name(custom_name, gateway=gateway)

            # Create DB model
            db_prompt = DbPrompt(
                name=computed_name,
                original_name=prompt.name,
                custom_name=custom_name,
                display_name=display_name,
                title=prompt.title,
                description=prompt.description,
                template=prompt.template,
                argument_schema=argument_schema,
                tags=prompt.tags,
                # Metadata fields
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
                version=1,
                # Team scoping fields - use schema values if provided, otherwise fallback to parameters
                team_id=getattr(prompt, "team_id", None) or team_id,
                owner_email=getattr(prompt, "owner_email", None) or owner_email or created_by,
                visibility=getattr(prompt, "visibility", None) or visibility,
                gateway_id=gateway_id,
            )
            # Check for existing server with the same name
            if visibility.lower() == "public":
                # Check for existing public prompt with the same name and gateway_id
                existing_prompt = db.execute(
                    select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "public", DbPrompt.gateway_id == gateway_id)
                ).scalar_one_or_none()  # pylint: disable=comparison-with-callable
                if existing_prompt:
                    raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
            elif visibility.lower() == "team":
                # Check for existing team prompt with the same name and gateway_id
                existing_prompt = db.execute(
                    select(DbPrompt).where(
                        DbPrompt.name == computed_name, DbPrompt.visibility == "team", DbPrompt.team_id == team_id, DbPrompt.gateway_id == gateway_id
                    )  # pylint: disable=comparison-with-callable
                ).scalar_one_or_none()
                if existing_prompt:
                    raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)

            # Set gateway relationship to help the before_insert event handler compute the name correctly
            if gateway:
                db_prompt.gateway = gateway
                db_prompt.gateway_name_cache = gateway.name  # type: ignore[attr-defined]

            # Add to DB
            db.add(db_prompt)
            db.commit()
            db.refresh(db_prompt)
            # Notify subscribers
            await self._notify_prompt_added(db_prompt)

            logger.info(f"Registered prompt: {prompt.name}")

            # Structured logging: Audit trail for prompt creation
            audit_trail.log_action(
                user_id=created_by or "system",
                action="create_prompt",
                resource_type="prompt",
                resource_id=str(db_prompt.id),
                resource_name=db_prompt.name,
                user_email=owner_email,
                team_id=team_id,
                client_ip=created_from_ip,
                user_agent=created_user_agent,
                new_values={
                    "name": db_prompt.name,
                    "visibility": visibility,
                },
                context={
                    "created_via": created_via,
                    "import_batch_id": import_batch_id,
                    "federation_source": federation_source,
                },
                db=db,
            )

            # Structured logging: Log successful prompt creation
            structured_logger.log(
                level="INFO",
                message="Prompt created successfully",
                event_type="prompt_created",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="prompt",
                resource_id=str(db_prompt.id),
                custom_fields={
                    "prompt_name": db_prompt.name,
                    "visibility": visibility,
                },
            )

            db_prompt.team = self._get_team_name(db, db_prompt.team_id)
            prompt_dict = self.convert_prompt_to_read(db_prompt)

            # Invalidate cache after successful creation
            cache = _get_registry_cache()
            await cache.invalidate_prompts()
            # Also invalidate tags cache since prompt tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()
            # First-Party
            from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

            metrics_cache.invalidate_prefix("top_prompts:")
            metrics_cache.invalidate("prompts")

            return PromptRead.model_validate(prompt_dict)

        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")

            structured_logger.log(
                level="ERROR",
                message="Prompt creation failed due to database integrity error",
                event_type="prompt_creation_failed",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                error=ie,
                custom_fields={"prompt_name": prompt.name},
            )
            raise ie
        except PromptNameConflictError as se:
            db.rollback()

            structured_logger.log(
                level="WARNING",
                message="Prompt creation failed due to name conflict",
                event_type="prompt_name_conflict",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={"prompt_name": prompt.name, "visibility": visibility},
            )
            raise se
        except ContentSizeError as cse:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message=f"Prompt template size limit exceeded: {cse.actual_size} bytes (max: {cse.max_size} bytes)",
                event_type="prompt_size_exceed",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={"prompt_name": prompt.name, "visibility": visibility},
            )
            raise cse
        except TemplateValidationError as tve:
            db.rollback()
            # Re-raise without wrapping so global/admin handlers can catch it
            raise tve
        except ContentPatternError as cpe:
            db.rollback()
            # Sanitize pattern_matched to prevent log injection (CWE-117)
            sanitized_pattern = cpe.pattern_matched.replace("\n", "\\n").replace("\r", "\\r")
            logger.error(f"Malicious pattern detected in prompt template: {sanitized_pattern}")
            structured_logger.log(
                level="ERROR",
                message="Prompt creation failed - Malicious pattern detected",
                event_type="prompt_creation_failed",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                error=cpe,
                custom_fields={"prompt_name": prompt.name},
            )
            raise cpe
        except Exception as e:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message="Prompt creation failed",
                event_type="prompt_creation_failed",
                component="prompt_service",
                user_id=created_by,
                user_email=owner_email,
                error=e,
                custom_fields={"prompt_name": prompt.name},
            )
            raise PromptError(f"Failed to register prompt: {str(e)}")

    async def register_prompts_bulk(
        self,
        db: Session,
        prompts: List[PromptCreate],
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
        """Register multiple prompts in bulk with a single commit.

        This method provides significant performance improvements over individual
        prompt registration by:
        - Using db.add_all() instead of individual db.add() calls
        - Performing a single commit for all prompts
        - Batch conflict detection
        - Chunking for very large imports (>500 items)

        Args:
            db: Database session
            prompts: List of prompt creation schemas
            created_by: Username who created these prompts
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, import, federation)
            created_user_agent: User agent of creation request
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated prompts
            team_id: Team ID to assign the prompts to
            owner_email: Email of the user who owns these prompts
            visibility: Prompt visibility level (private, team, public)
            conflict_strategy: How to handle conflicts (skip, update, rename, fail)

        Returns:
            Dict with statistics:
                - created: Number of prompts created
                - updated: Number of prompts updated
                - skipped: Number of prompts skipped
                - failed: Number of prompts that failed
                - errors: List of error messages

        Raises:
            PromptError: If bulk registration fails critically
            ContentSizeError: If any template exceeds size limits
            TemplateValidationError: If any template contains dangerous patterns or invalid syntax

        Examples:
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> p1 = MagicMock()
            >>> p1.name = "prompt-1"
            >>> p1.template = "Hello"
            >>> p1.custom_name = None
            >>> p1.display_name = None
            >>> p1.arguments = []
            >>> p2 = MagicMock()
            >>> p2.name = "prompt-2"
            >>> p2.template = "World"
            >>> p2.custom_name = None
            >>> p2.display_name = None
            >>> p2.arguments = []
            >>> prompts = [p1, p2]
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.register_prompts_bulk(db, prompts))
            ... except Exception:
            ...     pass
            >>> logging.disable(logging.NOTSET)
        """
        if not prompts:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        # Process in chunks to avoid memory issues and SQLite parameter limits
        chunk_size = 500

        for chunk_start in range(0, len(prompts), chunk_size):
            chunk = prompts[chunk_start : chunk_start + chunk_size]

            try:
                # Collect unique gateway_ids and look them up
                gateway_ids = set()
                for prompt in chunk:
                    gw_id = getattr(prompt, "gateway_id", None)
                    if gw_id:
                        gateway_ids.add(gw_id)

                gateways_map: Dict[str, Any] = {}
                if gateway_ids:
                    gateways = db.execute(select(DbGateway).where(DbGateway.id.in_(gateway_ids))).scalars().all()
                    gateways_map = {gw.id: gw for gw in gateways}

                # Batch check for existing prompts to detect conflicts
                # Build computed names with gateway context
                prompt_names = []
                for prompt in chunk:
                    custom_name = getattr(prompt, "custom_name", None) or prompt.name
                    gw_id = getattr(prompt, "gateway_id", None)
                    gateway = gateways_map.get(gw_id) if gw_id else None
                    computed_name = self._compute_prompt_name(custom_name, gateway=gateway)
                    prompt_names.append(computed_name)

                # Query for existing prompts - need to consider gateway_id in conflict detection
                # Build base query conditions
                if visibility.lower() == "public":
                    base_conditions = [DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "public"]
                elif visibility.lower() == "team" and team_id:
                    base_conditions = [DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "team", DbPrompt.team_id == team_id]
                else:
                    # Private prompts - check by owner
                    base_conditions = [DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "private", DbPrompt.owner_email == (owner_email or created_by)]

                existing_prompts_query = select(DbPrompt).where(*base_conditions)
                existing_prompts = db.execute(existing_prompts_query).scalars().all()
                # Use (name, gateway_id) tuple as key for proper conflict detection
                existing_prompts_map = {(p.name, p.gateway_id): p for p in existing_prompts}

                prompts_to_add = []
                prompts_to_update = []

                for prompt in chunk:
                    try:
                        # Validate template size BEFORE any processing
                        content_security = get_content_security_service()
                        content_security.validate_prompt_size(template=prompt.template, name=prompt.name, user_email=created_by, ip_address=created_from_ip)

                        # Validate template security (US-4)
                        content_security.validate_prompt_template(
                            template=prompt.template,
                            name=prompt.name,
                            user_email=created_by,
                            ip_address=created_from_ip,
                        )

                        # Note: Template syntax validation is now handled by validate_prompt_template above
                        # No need for duplicate _validate_template call

                        # Extract required arguments from template
                        required_args = self._get_required_arguments(prompt.template)

                        # Create argument schema
                        argument_schema = {
                            "type": "object",
                            "properties": {},
                            "required": list(required_args),
                        }
                        for arg in prompt.arguments:
                            schema = {"type": "string"}
                            if arg.description is not None:
                                schema["description"] = arg.description
                            argument_schema["properties"][arg.name] = schema

                        # Use provided parameters or schema values
                        prompt_team_id = team_id if team_id is not None else getattr(prompt, "team_id", None)
                        prompt_owner_email = owner_email or getattr(prompt, "owner_email", None) or created_by
                        prompt_visibility = visibility if visibility is not None else (getattr(prompt, "visibility", None) or "public")
                        prompt_gateway_id = getattr(prompt, "gateway_id", None)

                        custom_name = getattr(prompt, "custom_name", None) or prompt.name
                        display_name = getattr(prompt, "display_name", None) or custom_name
                        gateway = gateways_map.get(prompt_gateway_id) if prompt_gateway_id else None
                        computed_name = self._compute_prompt_name(custom_name, gateway=gateway)

                        # Look up existing prompt by (name, gateway_id) tuple
                        existing_prompt = existing_prompts_map.get((computed_name, prompt_gateway_id))

                        if existing_prompt:
                            # Handle conflict based on strategy
                            if conflict_strategy == "skip":
                                stats["skipped"] += 1
                                continue
                            if conflict_strategy == "update":
                                # Update existing prompt
                                existing_prompt.title = getattr(prompt, "title", None)
                                existing_prompt.description = prompt.description
                                existing_prompt.template = prompt.template
                                # Clear template cache to reduce memory growth
                                _compile_jinja_template.cache_clear()
                                existing_prompt.argument_schema = argument_schema
                                existing_prompt.tags = prompt.tags or []
                                if getattr(prompt, "custom_name", None) is not None:
                                    existing_prompt.custom_name = custom_name
                                if getattr(prompt, "display_name", None) is not None:
                                    existing_prompt.display_name = display_name
                                existing_prompt.modified_by = created_by
                                existing_prompt.modified_from_ip = created_from_ip
                                existing_prompt.modified_via = created_via
                                existing_prompt.modified_user_agent = created_user_agent
                                existing_prompt.updated_at = datetime.now(timezone.utc)
                                existing_prompt.version = (existing_prompt.version or 1) + 1

                                prompts_to_update.append(existing_prompt)
                                stats["updated"] += 1
                            elif conflict_strategy == "rename":
                                # Create with renamed prompt
                                new_name = f"{prompt.name}_imported_{int(datetime.now().timestamp())}"
                                new_custom_name = new_name
                                new_display_name = new_name
                                computed_name = self._compute_prompt_name(new_custom_name, gateway=gateway)
                                db_prompt = DbPrompt(
                                    name=computed_name,
                                    original_name=prompt.name,
                                    custom_name=new_custom_name,
                                    display_name=new_display_name,
                                    title=getattr(prompt, "title", None),
                                    description=prompt.description,
                                    template=prompt.template,
                                    argument_schema=argument_schema,
                                    tags=prompt.tags or [],
                                    created_by=created_by,
                                    created_from_ip=created_from_ip,
                                    created_via=created_via,
                                    created_user_agent=created_user_agent,
                                    import_batch_id=import_batch_id,
                                    federation_source=federation_source,
                                    version=1,
                                    team_id=prompt_team_id,
                                    owner_email=prompt_owner_email,
                                    visibility=prompt_visibility,
                                    gateway_id=prompt_gateway_id,
                                )
                                # Set gateway relationship to help the before_insert event handler
                                if gateway:
                                    db_prompt.gateway = gateway
                                    db_prompt.gateway_name_cache = gateway.name  # type: ignore[attr-defined]
                                prompts_to_add.append(db_prompt)
                                stats["created"] += 1
                            elif conflict_strategy == "fail":
                                stats["failed"] += 1
                                stats["errors"].append(f"Prompt name conflict: {prompt.name}")
                                continue
                        else:
                            # Create new prompt
                            db_prompt = DbPrompt(
                                name=computed_name,
                                original_name=prompt.name,
                                custom_name=custom_name,
                                display_name=display_name,
                                title=getattr(prompt, "title", None),
                                description=prompt.description,
                                template=prompt.template,
                                argument_schema=argument_schema,
                                tags=prompt.tags or [],
                                created_by=created_by,
                                created_from_ip=created_from_ip,
                                created_via=created_via,
                                created_user_agent=created_user_agent,
                                import_batch_id=import_batch_id,
                                federation_source=federation_source,
                                version=1,
                                team_id=prompt_team_id,
                                owner_email=prompt_owner_email,
                                visibility=prompt_visibility,
                                gateway_id=prompt_gateway_id,
                            )
                            # Set gateway relationship to help the before_insert event handler
                            if gateway:
                                db_prompt.gateway = gateway
                                db_prompt.gateway_name_cache = gateway.name  # type: ignore[attr-defined]
                            prompts_to_add.append(db_prompt)
                            stats["created"] += 1

                    except TemplateValidationError as tve:
                        # Template validation errors should fail fast, not continue
                        db.rollback()
                        logger.error(f"Template validation failed for prompt {prompt.name}: {tve.reason}")
                        raise tve
                    except Exception as e:
                        stats["failed"] += 1
                        stats["errors"].append(f"Failed to process prompt {prompt.name}: {str(e)}")
                        logger.warning(f"Failed to process prompt {prompt.name} in bulk operation: {str(e)}")
                        continue

                # Bulk add new prompts
                if prompts_to_add:
                    db.add_all(prompts_to_add)

                # Commit the chunk
                db.commit()

                # Refresh prompts for notifications and audit trail
                for db_prompt in prompts_to_add:
                    db.refresh(db_prompt)
                    # Notify subscribers
                    await self._notify_prompt_added(db_prompt)

                # Log bulk audit trail entry
                if prompts_to_add or prompts_to_update:
                    audit_trail.log_action(
                        user_id=created_by or "system",
                        action="bulk_create_prompts" if prompts_to_add else "bulk_update_prompts",
                        resource_type="prompt",
                        resource_id=import_batch_id or "bulk_operation",
                        resource_name=f"Bulk operation: {len(prompts_to_add)} created, {len(prompts_to_update)} updated",
                        user_email=owner_email,
                        team_id=team_id,
                        client_ip=created_from_ip,
                        user_agent=created_user_agent,
                        new_values={
                            "prompts_created": len(prompts_to_add),
                            "prompts_updated": len(prompts_to_update),
                            "visibility": visibility,
                        },
                        context={
                            "created_via": created_via,
                            "import_batch_id": import_batch_id,
                            "federation_source": federation_source,
                            "conflict_strategy": conflict_strategy,
                        },
                        db=db,
                    )

                logger.info(f"Bulk registered {len(prompts_to_add)} prompts, updated {len(prompts_to_update)} prompts in chunk")

            except TemplateValidationError:
                # Template validation errors should fail fast - re-raise immediately
                raise
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to process chunk in bulk prompt registration: {str(e)}")
                stats["failed"] += len(chunk)
                stats["errors"].append(f"Chunk processing failed: {str(e)}")
                continue

        # Final structured logging
        structured_logger.log(
            level="INFO",
            message="Bulk prompt registration completed",
            event_type="prompts_bulk_created",
            component="prompt_service",
            user_id=created_by,
            user_email=owner_email,
            team_id=team_id,
            resource_type="prompt",
            custom_fields={
                "prompts_created": stats["created"],
                "prompts_updated": stats["updated"],
                "prompts_skipped": stats["skipped"],
                "prompts_failed": stats["failed"],
                "total_prompts": len(prompts),
                "visibility": visibility,
                "conflict_strategy": conflict_strategy,
            },
        )

        return stats

    async def list_prompts(
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
    ) -> Union[tuple[List[PromptRead], Optional[str]], Dict[str, Any]]:
        """
        Retrieve a list of prompt templates from the database with pagination support.

        This method retrieves prompt templates from the database and converts them into a list
        of PromptRead objects. It supports filtering out inactive prompts based on the
        include_inactive parameter and cursor-based pagination.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive prompts in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination.
                Opaque base64-encoded string containing last item's ID and created_at.
            tags (Optional[List[str]]): Filter prompts by tags. If provided, only prompts with at least one matching tag will be returned.
            gateway_id (Optional[str]): Filter prompts by gateway ID. Accepts the literal value 'null' to match NULL gateway_id.
            limit (Optional[int]): Maximum number of prompts to return. Use 0 for all prompts (no limit).
                If not specified, uses pagination_default_page_size.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email (Optional[str]): User email for team-based access control. If None, no access control is applied.
            team_id (Optional[str]): Filter by specific team ID. Requires user_email for access validation.
            visibility (Optional[str]): Filter by visibility (private, team, public).
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API token access
                where the token scope should be respected instead of the user's full team memberships.

        Returns:
            If page is provided: Dict with {"data": [...], "pagination": {...}, "links": {...}}
            If cursor is provided or neither: tuple of (list of PromptRead objects, next_cursor).

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import PromptRead
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt_read_obj = MagicMock(spec=PromptRead)
            >>> service.convert_prompt_to_read = MagicMock(return_value=prompt_read_obj)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> prompts, next_cursor = asyncio.run(service.list_prompts(db))
            >>> prompts == [prompt_read_obj]
            True
        """
        with create_span(
            "prompt.list",
            {
                "include_inactive": include_inactive,
                "tags.count": len(tags) if tags else 0,
                "gateway_id": gateway_id,
                "limit": limit,
                "page": page,
                "per_page": per_page,
                "user.email": user_email,
                "team.scope": format_trace_team_scope(token_teams) if token_teams is not None else None,
                "team.filter": team_id,
                "visibility": visibility,
            },
        ):
            # Check cache for first page only (cursor=None)
            # Skip caching when:
            # - user_email is provided (team-filtered results are user-specific)
            # - token_teams is set (scoped access, e.g., public-only or team-scoped tokens)
            # - page-based pagination is used
            # This prevents cache poisoning where admin results could leak to public-only requests
            cache = _get_registry_cache()
            if cursor is None and user_email is None and token_teams is None and page is None:
                filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None, gateway_id=gateway_id, limit=limit, visibility=visibility)
                cached = await cache.get("prompts", filters_hash)
                if cached is not None:
                    # Reconstruct PromptRead objects from cached dicts
                    cached_prompts = [PromptRead.model_validate(p) for p in cached["prompts"]]
                    return (cached_prompts, cached.get("next_cursor"))

            # Build base query with ordering and eager load gateway to avoid N+1
            query = select(DbPrompt).options(joinedload(DbPrompt.gateway)).order_by(desc(DbPrompt.created_at), desc(DbPrompt.id))

            if not include_inactive:
                query = query.where(DbPrompt.enabled)

            query = await self._apply_access_control(query, db, user_email, token_teams, team_id)

            if visibility:
                query = query.where(DbPrompt.visibility == visibility)

            # Add gateway_id filtering if provided
            if gateway_id:
                if gateway_id.lower() == "null":
                    query = query.where(DbPrompt.gateway_id.is_(None))
                else:
                    query = query.where(DbPrompt.gateway_id == gateway_id)

            # Add tag filtering if tags are provided (supports both List[str] and List[Dict] formats)
            if tags:
                query = query.where(json_contains_tag_expr(db, DbPrompt.tags, tags, match_any=True))

            # Use unified pagination helper - handles both page and cursor pagination
            pag_result = await unified_paginate(
                db,
                query=query,
                page=page,
                per_page=per_page,
                cursor=cursor,
                limit=limit,
                base_url="/admin/prompts",  # Used for page-based links
                query_params={"include_inactive": include_inactive} if include_inactive else {},
            )

            next_cursor = None
            # Extract servers based on pagination type
            if page is not None:
                # Page-based: pag_result is a dict
                prompts_db = pag_result["data"]
            else:
                # Cursor-based: pag_result is a tuple
                prompts_db, next_cursor = pag_result

            # Fetch team names for the prompts (common for both pagination types)
            team_ids_set = {s.team_id for s in prompts_db if s.team_id}
            team_map = {}
            if team_ids_set:
                teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(team_ids_set), EmailTeam.is_active.is_(True))).all()
                team_map = {team.id: team.name for team in teams}

            db.commit()  # Release transaction to avoid idle-in-transaction

            # Convert to PromptRead (common for both pagination types)
            result = []
            for s in prompts_db:
                try:
                    s.team = team_map.get(s.team_id) if s.team_id else None
                    result.append(self.convert_prompt_to_read(s, include_metrics=False))
                except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                    logger.exception(f"Failed to convert prompt {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                    # Continue with remaining prompts instead of failing completely
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
            if cursor is None and user_email is None and token_teams is None:
                try:
                    cache_data = {"prompts": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                    await cache.set("prompts", cache_data, filters_hash)
                except AttributeError:
                    pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

            return (result, next_cursor)

    async def list_prompts_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[PromptRead]:
        """
        DEPRECATED: Use list_prompts() with user_email parameter instead.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_prompts() with user_email, team_id, and visibility parameters.

        List prompts user has access to with team filtering.

        Args:
            db: Database session
            user_email: Email of the user requesting prompts
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive prompts
            skip: Number of prompts to skip for pagination
            limit: Maximum number of prompts to return

        Returns:
            List[PromptRead]: Prompts the user has access to
        """
        # Build query following existing patterns from list_prompts()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        # Build query following existing patterns from list_resources()
        # Eager load gateway to avoid N+1 when accessing gateway_slug
        query = select(DbPrompt).options(joinedload(DbPrompt.gateway))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbPrompt.enabled)

        if team_id:
            if team_id not in team_ids:
                return []  # No access to team

            access_conditions = []
            # Filter by specific team
            access_conditions.append(and_(DbPrompt.team_id == team_id, DbPrompt.visibility.in_(["team", "public"])))

            access_conditions.append(and_(DbPrompt.team_id == team_id, DbPrompt.owner_email == user_email))

            query = query.where(or_(*access_conditions))
        else:
            # Get user's accessible teams
            # Build access conditions following existing patterns
            access_conditions = []
            # 1. User's personal resources (owner_email matches)
            access_conditions.append(DbPrompt.owner_email == user_email)
            # 2. Team resources where user is member
            if team_ids:
                access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))
            # 3. Public resources (if visibility allows)
            access_conditions.append(DbPrompt.visibility == "public")

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbPrompt.visibility == visibility)

        # Apply pagination following existing patterns
        query = query.offset(skip).limit(limit)

        prompts = db.execute(query).scalars().all()

        # Batch fetch team names to avoid N+1 queries
        prompt_team_ids = {p.team_id for p in prompts if p.team_id}
        team_map = {}
        if prompt_team_ids:
            teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(prompt_team_ids), EmailTeam.is_active.is_(True))).all()
            team_map = {str(team.id): team.name for team in teams}

        db.commit()  # Release transaction to avoid idle-in-transaction

        result = []
        for t in prompts:
            try:
                t.team = team_map.get(str(t.team_id)) if t.team_id else None
                result.append(self.convert_prompt_to_read(t, include_metrics=False))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert prompt {getattr(t, 'id', 'unknown')} ({getattr(t, 'name', 'unknown')}): {e}")
                # Continue with remaining prompts instead of failing completely
        return result

    async def list_server_prompts(
        self,
        db: Session,
        server_id: str,
        include_inactive: bool = False,
        include_metrics: bool = False,
        cursor: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> List[PromptRead]:
        """
        Retrieve a list of prompt templates from the database.

        This method retrieves prompt templates from the database and converts them into a list
        of PromptRead objects. It supports filtering out inactive prompts based on the
        include_inactive parameter. The cursor parameter is reserved for future pagination support
        but is currently not implemented.

        Args:
            db (Session): The SQLAlchemy database session.
            server_id (str): Server ID
            include_inactive (bool): If True, include inactive prompts in the result.
                Defaults to False.
            include_metrics (bool): If True, include metrics data in the response.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.
            user_email (Optional[str]): User email for visibility filtering. If None, no filtering applied.
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API
                token access where the token scope should be respected.

        Returns:
            List[PromptRead]: A list of prompt templates represented as PromptRead objects.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import PromptRead
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt_read_obj = MagicMock(spec=PromptRead)
            >>> service.convert_prompt_to_read = MagicMock(return_value=prompt_read_obj)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_prompts(db, 'server1'))
            >>> result == [prompt_read_obj]
            True
        """
        with create_span(
            "prompt.list",
            {
                "server_id": server_id,
                "include_inactive": include_inactive,
                "include_metrics": include_metrics,
                "user.email": user_email,
                "team.scope": format_trace_team_scope(token_teams) if token_teams is not None else None,
            },
        ):
            # Eager load gateway to avoid N+1 when accessing gateway_slug
            query = (
                select(DbPrompt)
                .options(joinedload(DbPrompt.gateway))
                .join(server_prompt_association, DbPrompt.id == server_prompt_association.c.prompt_id)
                .where(server_prompt_association.c.server_id == server_id)
            )

            # Eager load metrics relationships to prevent N+1 queries when include_metrics=true
            if include_metrics:
                query = query.options(selectinload(DbPrompt.metrics), selectinload(DbPrompt.metrics_hourly))
            if not include_inactive:
                query = query.where(DbPrompt.enabled)

            # Add visibility filtering if user context OR token_teams provided
            # This ensures unauthenticated requests with token_teams=[] only see public prompts
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
                    DbPrompt.visibility == "public",
                ]
                # Only include owner access for non-public-only tokens with user_email
                if not is_public_only_token and user_email:
                    access_conditions.append(DbPrompt.owner_email == user_email)
                if team_ids:
                    access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            # Cursor-based pagination logic can be implemented here in the future.
            logger.debug(cursor)
            prompts = db.execute(query).scalars().all()

            # Batch fetch team names to avoid N+1 queries
            prompt_team_ids = {p.team_id for p in prompts if p.team_id}
            team_map = {}
            if prompt_team_ids:
                teams = db.execute(select(EmailTeam.id, EmailTeam.name).where(EmailTeam.id.in_(prompt_team_ids), EmailTeam.is_active.is_(True))).all()
                team_map = {str(team.id): team.name for team in teams}

            db.commit()  # Release transaction to avoid idle-in-transaction

            result = []
            for t in prompts:
                try:
                    t.team = team_map.get(str(t.team_id)) if t.team_id else None
                    result.append(self.convert_prompt_to_read(t, include_metrics=include_metrics))
                except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                    logger.exception(f"Failed to convert prompt {getattr(t, 'id', 'unknown')} ({getattr(t, 'name', 'unknown')}): {e}")
                    # Continue with remaining prompts instead of failing completely
            return result

    async def _record_prompt_metric(self, db: Session, prompt: DbPrompt, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for a prompt invocation.

        Args:
            db: Database session
            prompt: The prompt that was invoked
            start_time: Monotonic start time of the invocation
            success: True if successful, False otherwise
            error_message: Error message if failed, None otherwise
        """
        end_time = time.monotonic()
        response_time = end_time - start_time

        metric = PromptMetric(
            prompt_id=prompt.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    async def _check_prompt_access(
        self,
        db: Session,
        prompt: DbPrompt,
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if user has access to a prompt based on visibility rules.

        Implements the same access control logic as list_prompts() for consistency.

        Args:
            db: Database session for team membership lookup if needed.
            prompt: Prompt ORM object with visibility, team_id, owner_email.
            user_email: Email of the requesting user (None = unauthenticated).
            token_teams: List of team IDs from token.
                - None = unrestricted admin access
                - [] = public-only token
                - [...] = team-scoped token

        Returns:
            True if access is allowed, False otherwise.
        """
        visibility = getattr(prompt, "visibility", "public")
        prompt_team_id = getattr(prompt, "team_id", None)
        prompt_owner_email = getattr(prompt, "owner_email", None)

        # Public prompts are accessible by everyone
        if visibility == "public":
            return True

        # Admin bypass (PR #4341 invariant): never reveal another user's private rows.
        # Anonymous bypass sees public + team only; a DB-resolved admin session
        # additionally sees their own private rows. Matches a2a_service._visible_agent_ids.
        if token_teams is None and user_email is None:
            return visibility != "private"
        if token_teams is None and user_email and is_user_admin(db, user_email):
            return visibility != "private" or prompt_owner_email == user_email

        # No user context (but not admin) = deny access to non-public prompts
        if not user_email:
            return False

        # Public-only tokens (empty teams array) can ONLY access public prompts
        is_public_only_token = token_teams is not None and len(token_teams) == 0
        if is_public_only_token:
            return False  # Already checked public above

        # Owner can access their own private prompts
        if visibility == "private" and prompt_owner_email and prompt_owner_email == user_email:
            return True

        # Team prompts: check team membership (matches list_prompts behavior)
        if prompt_team_id:
            # Use token_teams if provided, otherwise look up from DB
            if token_teams is not None:
                team_ids = token_teams
            else:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]

            # Team/public visibility allows access if user is in the team
            if visibility in ["team", "public"] and prompt_team_id in team_ids:
                return True

        return False

    def _find_prompt_by_name_or_id(
        self,
        db: Session,
        scoped_query: Any,
        prompt_id: str,
    ) -> Optional[DbPrompt]:
        """Find a prompt by name or ID using a scoped query.

        Uses a single OR query for efficiency, with a fallback to name-only
        lookup if the OR matches multiple rows (e.g. one prompt's name equals
        another prompt's ID).

        Args:
            db: Database session
            scoped_query: Pre-scoped SQLAlchemy query with access control applied
            prompt_id: Name or ID of the prompt to find

        Returns:
            DbPrompt instance if found, None otherwise

        Raises:
            PromptError: If multiple accessible prompts share the same name.

        Note:
            The scoped_query must already have team-based access control applied
            via _apply_access_control() to ensure multi-tenancy security.
        """
        try:
            return db.execute(scoped_query.where(or_(DbPrompt.name == prompt_id, DbPrompt.id == prompt_id))).scalar_one_or_none()  # pylint: disable=comparison-with-callable
        except MultipleResultsFound:
            # OR matched multiple rows — try name-only (MCP spec primary key)
            try:
                return db.execute(scoped_query.where(DbPrompt.name == prompt_id)).scalar_one_or_none()  # pylint: disable=comparison-with-callable
            except MultipleResultsFound:
                raise PromptError(f"Prompt name '{prompt_id}' is ambiguous across multiple scopes; use /servers/{{id}}/mcp to disambiguate.")

    async def get_prompt(
        self,
        db: Session,
        prompt_id: Union[int, str],
        arguments: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
        tenant_id: Optional[str] = None,
        server_id: Optional[str] = None,
        request_id: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
        _meta_data: Optional[Dict[str, Any]] = None,
    ) -> PromptResult:
        """Retrieve and render a prompt by name or ID.

        This method implements MCP specification-compliant prompt lookup with
        multi-tenancy support and backward compatibility.

        Args:
            db: Database session
            prompt_id: Name or ID of the prompt to retrieve. Name-based lookup
                is prioritized per MCP spec, with ID fallback for backward
                compatibility. Team-based access control is applied before the
                lookup to ensure multi-tenancy security.
            arguments: Optional arguments for rendering
            user: Optional user email for authorization checks
            tenant_id: Optional tenant identifier for plugin context
            server_id: Optional server ID for server scoping enforcement
            request_id: Optional request ID, generated if not provided
            token_teams: Optional list of team IDs from token for authorization.
                None = unrestricted admin, [] = public-only, [...] = team-scoped.
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.
            _meta_data: Optional metadata forwarded as _meta to the upstream MCP gateway during prompt retrieval.

        Returns:
            Prompt result with rendered messages

        Raises:
            PluginViolationError: If prompt violates a plugin policy
            PromptNotFoundError: If prompt not found or access denied
            PromptError: For other prompt errors
            PluginError: If encounters issue with plugin

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.get_prompt(db, 'prompt_id'))
            ... except Exception:
            ...     pass
        """

        start_time = time.monotonic()
        success = False
        error_message = None
        prompt = None
        server_scoped = False

        # Create database span for observability dashboard
        trace_id = current_trace_id.get()
        db_span_id = None
        db_span_ended = False
        observability_service = ObservabilityService() if trace_id else None

        if trace_id and observability_service:
            try:
                db_span_id = observability_service.start_span(
                    trace_id=trace_id,
                    name="prompt.render",
                    attributes={
                        "prompt.id": str(prompt_id),
                        "arguments_count": len(arguments) if arguments else 0,
                        "user": user or "anonymous",
                        "server_id": server_id,
                        "tenant_id": tenant_id,
                        "request_id": request_id or "none",
                    },
                )
                logger.debug(f"✓ Created prompt.render span: {db_span_id} for prompt: {prompt_id}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for prompt rendering: {e}")
                db_span_id = None

        # Create a trace span for OpenTelemetry export (Jaeger, Zipkin, etc.)
        span_attributes = {
            "prompt.id": prompt_id,
            "arguments_count": len(arguments) if arguments else 0,
            "user": user or "anonymous",
            "server_id": server_id,
            "tenant_id": tenant_id,
            "request_id": request_id or "none",
        }
        if is_input_capture_enabled("prompt.render"):
            span_attributes["langfuse.observation.input"] = serialize_trace_payload(arguments or {})

        with create_span("prompt.render", span_attributes) as span:
            try:
                # Check if any prompt hooks are registered to avoid unnecessary context creation
                plugin_manager = await self._get_plugin_manager(server_id)
                has_pre_fetch = plugin_manager and plugin_manager.has_hooks_for(PromptHookType.PROMPT_PRE_FETCH)
                has_post_fetch = plugin_manager and plugin_manager.has_hooks_for(PromptHookType.PROMPT_POST_FETCH)

                # Initialize plugin context variables only if hooks are registered
                context_table = None
                global_context = None
                if has_pre_fetch or has_post_fetch:
                    context_table = plugin_context_table
                    if plugin_global_context:
                        global_context = plugin_global_context
                        # Update fields with prompt-specific information
                        if user:
                            global_context.user = user
                        if server_id:
                            global_context.server_id = server_id
                        if tenant_id:
                            global_context.tenant_id = tenant_id
                    else:
                        # Create new context (fallback when middleware didn't run)
                        if not request_id:
                            request_id = uuid.uuid4().hex
                        global_context = GlobalContext(request_id=request_id, user=user, server_id=server_id, tenant_id=tenant_id)

                if has_pre_fetch:
                    pre_result, context_table = await plugin_manager.invoke_hook(
                        PromptHookType.PROMPT_PRE_FETCH,
                        payload=PromptPrehookPayload(prompt_id=prompt_id, args=arguments),
                        global_context=global_context,
                        local_contexts=context_table,  # Pass context from previous hooks
                        violations_as_exceptions=True,
                    )

                    # Use modified payload if provided
                    if pre_result.modified_payload:
                        payload = pre_result.modified_payload
                        arguments = payload.args

                # ═══════════════════════════════════════════════════════════════════════════
                # SECURITY: Apply team scoping BEFORE lookup to prevent multi-tenancy issues
                # This ensures users only see prompts they have access to, matching list_prompts()
                # Build base query and apply access control (matches list_prompts architecture)
                # ═══════════════════════════════════════════════════════════════════════════
                search_key = str(prompt_id)

                # Build base query with server + team scoping applied FIRST
                base_query = select(DbPrompt).options(joinedload(DbPrompt.gateway)).where(DbPrompt.enabled)
                if server_id:
                    base_query = base_query.join(server_prompt_association, DbPrompt.id == server_prompt_association.c.prompt_id).where(server_prompt_association.c.server_id == server_id)
                scoped_query = await self._apply_access_control(base_query, db, user, token_teams, team_id=None)

                # Find prompt by name or ID (active prompts only) using optimized OR query
                prompt = self._find_prompt_by_name_or_id(db, scoped_query, prompt_id)

                # If not found in active prompts, check inactive prompts (with team + server scoping)
                if not prompt:
                    inactive_base_query = select(DbPrompt).options(joinedload(DbPrompt.gateway)).where(not_(DbPrompt.enabled))
                    if server_id:
                        inactive_base_query = inactive_base_query.join(server_prompt_association, DbPrompt.id == server_prompt_association.c.prompt_id).where(
                            server_prompt_association.c.server_id == server_id
                        )
                    inactive_scoped_query = await self._apply_access_control(inactive_base_query, db, user, token_teams, team_id=None)

                    # Find in inactive prompts using optimized OR query
                    inactive_prompt = self._find_prompt_by_name_or_id(db, inactive_scoped_query, prompt_id)

                    if inactive_prompt:
                        raise PromptNotFoundError(f"Prompt '{search_key}' exists but is inactive")

                    raise PromptNotFoundError(f"Prompt not found: {search_key}")

                # Access control already applied via scoped query - no additional check needed

                # ═══════════════════════════════════════════════════════════════════════════
                # SECURITY: Enforce server scoping if server_id is provided
                # Prompt must be attached to the specified virtual server
                # ═══════════════════════════════════════════════════════════════════════════
                if server_id:
                    server_match = db.execute(
                        select(server_prompt_association.c.prompt_id).where(
                            server_prompt_association.c.server_id == server_id,
                            server_prompt_association.c.prompt_id == prompt.id,
                        )
                    ).first()
                    if not server_match:
                        raise PromptNotFoundError(f"Prompt not found: {search_key}")
                    server_scoped = True

                if self._should_fetch_gateway_prompt(prompt):
                    # Release the read transaction before any remote network I/O.
                    db.commit()
                    result = await self._fetch_gateway_prompt_result(prompt, arguments, meta_data=_meta_data)
                elif not arguments:
                    result = PromptResult(
                        messages=[
                            Message(
                                role=Role.USER,
                                content=TextContent(type="text", text=prompt.template),
                            )
                        ],
                        description=prompt.description,
                    )
                else:
                    try:
                        prompt.validate_arguments(arguments)
                        rendered = self._render_template(prompt.template, arguments)
                        messages = self._parse_messages(rendered)
                        result = PromptResult(messages=messages, description=prompt.description)
                    except Exception as e:
                        set_span_error(span, e)
                        raise PromptError(f"Failed to process prompt: {str(e)}")

                if has_post_fetch:
                    post_result, _ = await plugin_manager.invoke_hook(
                        PromptHookType.PROMPT_POST_FETCH,
                        payload=PromptPosthookPayload(prompt_id=prompt.name, result=result),
                        global_context=global_context,
                        local_contexts=context_table,
                        violations_as_exceptions=True,
                    )
                    # Use modified payload if provided
                    result = post_result.modified_payload.result if post_result.modified_payload else result

                arguments_supplied = bool(arguments)

                audit_trail.log_action(
                    user_id=user or "anonymous",
                    action="view_prompt",
                    resource_type="prompt",
                    resource_id=str(prompt.id),
                    resource_name=prompt.name,
                    team_id=prompt.team_id,
                    context={
                        "tenant_id": tenant_id,
                        "server_id": server_id,
                        "arguments_provided": arguments_supplied,
                        "request_id": request_id,
                    },
                    db=db,
                )

                structured_logger.log(
                    level="INFO",
                    message="Prompt retrieved successfully",
                    event_type="prompt_viewed",
                    component="prompt_service",
                    user_id=user,
                    team_id=prompt.team_id,
                    resource_type="prompt",
                    resource_id=str(prompt.id),
                    request_id=request_id,
                    custom_fields={
                        "prompt_name": prompt.name,
                        "arguments_provided": arguments_supplied,
                        "tenant_id": tenant_id,
                        "server_id": server_id,
                    },
                )

                # Set success attributes on span
                if span:
                    set_span_attribute(span, "success", True)
                    set_span_attribute(span, "duration.ms", (time.monotonic() - start_time) * 1000)
                    set_span_attribute(span, "langfuse.observation.prompt.name", prompt.name)
                    if getattr(prompt, "version", None) is not None:
                        set_span_attribute(span, "langfuse.observation.prompt.version", int(prompt.version))
                    if result and hasattr(result, "messages"):
                        set_span_attribute(span, "messages.count", len(result.messages))
                        if is_output_capture_enabled("prompt.render"):
                            set_span_attribute(span, "langfuse.observation.output", serialize_trace_payload(result))

                success = True
                logger.info(f"Retrieved prompt: {prompt.id} successfully")
                return result

            except Exception as e:
                success = False
                error_message = str(e)
                raise
            finally:
                # Record metrics only if we found a prompt
                if prompt:
                    try:
                        metrics_buffer.record_prompt_metric(
                            prompt_id=prompt.id,
                            start_time=start_time,
                            success=success,
                            error_message=error_message,
                        )
                    except Exception as metrics_error:
                        logger.warning(f"Failed to record prompt metric: {metrics_error}")

                    # Record server metrics ONLY when the server scoping check passed.
                    # This prevents recording metrics with unvalidated server_id values
                    # from admin API headers (X-Server-ID) or RPC params.
                    if server_scoped:
                        try:
                            # Record server metric only for the specific virtual server being accessed
                            metrics_buffer.record_server_metric(
                                server_id=server_id,
                                start_time=start_time,
                                success=success,
                                error_message=error_message,
                            )
                        except Exception as metrics_error:
                            logger.warning(f"Failed to record server metric: {metrics_error}")

                # End database span for observability dashboard
                if db_span_id and observability_service and not db_span_ended:
                    try:
                        observability_service.end_span(
                            span_id=db_span_id,
                            status="ok" if success else "error",
                            status_message=error_message if error_message else None,
                        )
                        db_span_ended = True
                        logger.debug(f"✓ Ended prompt.render span: {db_span_id}")
                    except Exception as e:
                        logger.warning(f"Failed to end observability span for prompt rendering: {e}")

    async def update_prompt(
        self,
        db: Session,
        prompt_id: Union[int, str],
        prompt_update: PromptUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> PromptRead:
        """
        Update a prompt template.

        Args:
            db: Database session
            prompt_id: ID of prompt to update
            prompt_update: Prompt update object
            modified_by: Username of the person modifying the prompt
            modified_from_ip: IP address where the modification originated
            modified_via: Source of modification (ui/api/import)
            modified_user_agent: User agent string from the modification request
            user_email: Email of user performing update (for ownership check)

        Returns:
            The updated PromptRead object

        Raises:
            PromptNotFoundError: If the prompt is not found
            PermissionError: If user doesn't own the prompt
            IntegrityError: If a database integrity error occurs.
            PromptNameConflictError: If a prompt with the same name already exists.
            PromptError: For other update errors
            ContentSizeError: For template size exceed
            ContentPatternError: If template contains malicious patterns (US-3)
            TemplateValidationError: If template contains dangerous patterns or invalid syntax

        Examples:
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import AsyncMock, MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> existing = MagicMock()
            >>> existing.custom_name = "test-prompt"
            >>> existing.name = "test-prompt"
            >>> existing.gateway = None
            >>> db.execute.return_value.scalar_one_or_none.return_value = existing
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_updated = AsyncMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> update = MagicMock()
            >>> update.name = None
            >>> update.visibility = None
            >>> update.team_id = None
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.update_prompt(db, 'prompt_name', update))
            ... except Exception:
            ...     pass
            >>> logging.disable(logging.NOTSET)
        """
        try:
            # Acquire a row-level lock for the prompt being updated to make
            # name-checks and the subsequent update atomic in PostgreSQL.
            # For SQLite `get_for_update` falls back to a regular get.
            prompt = get_for_update(db, DbPrompt, prompt_id)
            if not prompt:
                raise PromptNotFoundError(f"Prompt not found: {prompt_id}")

            visibility = prompt_update.visibility or prompt.visibility
            team_id = prompt_update.team_id or prompt.team_id
            owner_email = prompt.owner_email or user_email

            candidate_custom_name = prompt.custom_name

            if prompt_update.name is not None:
                candidate_custom_name = prompt_update.custom_name or prompt_update.name
            elif prompt_update.custom_name is not None:
                candidate_custom_name = prompt_update.custom_name

            computed_name = self._compute_prompt_name(candidate_custom_name, prompt.gateway)
            if computed_name != prompt.name:
                if visibility.lower() == "public":
                    # Lock any conflicting row so concurrent updates cannot race.
                    existing_prompt = get_for_update(
                        db, DbPrompt, where=and_(DbPrompt.name == computed_name, DbPrompt.visibility == "public", DbPrompt.id != prompt.id)
                    )  # pylint: disable=comparison-with-callable
                    if existing_prompt:
                        raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
                elif visibility.lower() == "team" and team_id:
                    existing_prompt = get_for_update(
                        db, DbPrompt, where=and_(DbPrompt.name == computed_name, DbPrompt.visibility == "team", DbPrompt.team_id == team_id, DbPrompt.id != prompt.id)
                    )  # pylint: disable=comparison-with-callable
                    logger.info(f"Existing prompt check result: {existing_prompt}")
                    if existing_prompt:
                        raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
                elif visibility.lower() == "private":
                    existing_prompt = get_for_update(
                        db,
                        DbPrompt,
                        where=and_(
                            DbPrompt.name == computed_name, DbPrompt.visibility == "private", DbPrompt.owner_email == owner_email, DbPrompt.id != prompt.id
                        ),  # pylint: disable=comparison-with-callable
                    )
                    if existing_prompt:
                        raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, prompt):
                    raise PermissionError("Only the owner can update this prompt")

            if prompt_update.name is not None:
                if prompt.gateway_id:
                    prompt.custom_name = prompt_update.custom_name or prompt_update.name
                else:
                    prompt.original_name = prompt_update.name
                    if prompt_update.custom_name is None:
                        prompt.custom_name = prompt_update.name
            if prompt_update.custom_name is not None:
                prompt.custom_name = prompt_update.custom_name
            if prompt_update.display_name is not None:
                prompt.display_name = prompt_update.display_name
            if prompt_update.description is not None:
                prompt.description = prompt_update.description
            if prompt_update.title is not None:
                prompt.title = prompt_update.title
            if prompt_update.template is not None:
                # Validate template size before updating
                content_security = get_content_security_service()
                content_security.validate_prompt_size(
                    template=prompt_update.template,
                    name=prompt.name,
                    user_email=modified_by or user_email,
                    ip_address=modified_from_ip,
                )

                # Validate template security (US-4)
                content_security.validate_prompt_template(
                    template=prompt_update.template,
                    name=prompt.name,
                    user_email=modified_by or user_email,
                    ip_address=modified_from_ip,
                )

                # Note: Template syntax validation is now handled by validate_prompt_template above
                # No need for duplicate _validate_template call

                prompt.template = prompt_update.template
                # Clear template cache to reduce memory growth
                _compile_jinja_template.cache_clear()
            if prompt_update.arguments is not None:
                required_args = self._get_required_arguments(prompt.template)
                argument_schema = {
                    "type": "object",
                    "properties": {},
                    "required": list(required_args),
                }
                for arg in prompt_update.arguments:
                    schema = {"type": "string"}
                    if arg.description is not None:
                        schema["description"] = arg.description
                    argument_schema["properties"][arg.name] = schema
                prompt.argument_schema = argument_schema

            if prompt_update.visibility is not None:
                # Validate visibility transitions
                if prompt_update.visibility == "team":
                    target_team_id = prompt_update.team_id if prompt_update.team_id is not None else prompt.team_id
                    _validate_prompt_team_assignment(db, user_email, target_team_id)
                prompt.visibility = prompt_update.visibility

            # Update tags if provided
            if prompt_update.tags is not None:
                prompt.tags = prompt_update.tags

            # Update team assignment if provided, validating ownership
            if prompt_update.team_id is not None:
                if prompt_update.team_id != prompt.team_id:
                    _validate_prompt_team_assignment(db, user_email, prompt_update.team_id)
                prompt.team_id = prompt_update.team_id

            # Update metadata fields
            prompt.updated_at = datetime.now(timezone.utc)
            if modified_by:
                prompt.modified_by = modified_by
            if modified_from_ip:
                prompt.modified_from_ip = modified_from_ip
            if modified_via:
                prompt.modified_via = modified_via
            if modified_user_agent:
                prompt.modified_user_agent = modified_user_agent
            if hasattr(prompt, "version") and prompt.version is not None:
                prompt.version = prompt.version + 1
            else:
                prompt.version = 1

            db.commit()
            db.refresh(prompt)

            await self._notify_prompt_updated(prompt)

            # Structured logging: Audit trail for prompt update
            audit_trail.log_action(
                user_id=user_email or modified_by or "system",
                action="update_prompt",
                resource_type="prompt",
                resource_id=str(prompt.id),
                resource_name=prompt.name,
                user_email=user_email,
                team_id=prompt.team_id,
                client_ip=modified_from_ip,
                user_agent=modified_user_agent,
                new_values={"name": prompt.name, "version": prompt.version},
                context={"modified_via": modified_via},
                db=db,
            )

            structured_logger.log(
                level="INFO",
                message="Prompt updated successfully",
                event_type="prompt_updated",
                component="prompt_service",
                user_id=modified_by,
                user_email=user_email,
                team_id=prompt.team_id,
                resource_type="prompt",
                resource_id=str(prompt.id),
                custom_fields={"prompt_name": prompt.name, "version": prompt.version},
            )

            prompt.team = self._get_team_name(db, prompt.team_id)

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_prompts()
            # Also invalidate tags cache since prompt tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return self.convert_prompt_to_read(prompt)

        except PermissionError as pe:
            db.rollback()

            structured_logger.log(
                level="WARNING",
                message="Prompt update failed due to permission error",
                event_type="prompt_update_permission_denied",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=pe,
            )
            raise
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")

            structured_logger.log(
                level="ERROR",
                message="Prompt update failed due to database integrity error",
                event_type="prompt_update_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=ie,
            )
            raise ie
        except PromptNotFoundError as e:
            db.rollback()
            logger.error(f"Prompt not found: {e}")

            structured_logger.log(
                level="ERROR",
                message="Prompt update failed - prompt not found",
                event_type="prompt_not_found",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
            )
            raise e
        except PromptNameConflictError as pnce:
            db.rollback()
            logger.error(f"Prompt name conflict: {pnce}")

            structured_logger.log(
                level="WARNING",
                message="Prompt update failed due to name conflict",
                event_type="prompt_name_conflict",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=pnce,
            )
            raise pnce
        except ContentSizeError as cse:
            db.rollback()
            logger.error(f"Prompt template size limit exceeded: {cse.actual_size} bytes (max: {cse.max_size} bytes)")
            structured_logger.log(
                level="ERROR",
                message="Prompt update failed - Template size exceeded",
                event_type="prompt_update_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=cse,
            )
            raise cse
        except TemplateValidationError as tve:
            db.rollback()
            # Re-raise without wrapping so global/admin handlers can catch it
            raise tve
        except ContentPatternError as cpe:
            db.rollback()
            # Sanitize pattern_matched to prevent log injection (CWE-117)
            sanitized_pattern = cpe.pattern_matched.replace("\n", "\\n").replace("\r", "\\r")
            logger.error(f"Malicious pattern detected in prompt template: {sanitized_pattern}")
            structured_logger.log(
                level="ERROR",
                message="Prompt update failed - Malicious pattern detected",
                event_type="prompt_update_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=cpe,
            )
            raise cpe
        except Exception as e:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message="Prompt update failed",
                event_type="prompt_update_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
            )
            raise PromptError(f"Failed to update prompt: {str(e)}")

    async def set_prompt_state(self, db: Session, prompt_id: int, activate: bool, user_email: Optional[str] = None, skip_cache_invalidation: bool = False) -> PromptRead:
        """
        Set the activation status of a prompt.

        Args:
            db: Database session
            prompt_id: Prompt ID
            activate: True to activate, False to deactivate
            user_email: Optional[str] The email of the user to check if the user has permission to modify.
            skip_cache_invalidation: If True, skip cache invalidation (used for batch operations).

        Returns:
            The updated PromptRead object

        Raises:
            PromptNotFoundError: If the prompt is not found.
            PromptLockConflictError: If the prompt is locked by another transaction.
            PromptError: For other errors.
            PermissionError: If user doesn't own the prompt.

        Examples:
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import AsyncMock, MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> db.get.return_value = prompt
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_activated = AsyncMock()
            >>> service._notify_prompt_deactivated = AsyncMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.set_prompt_state(db, 1, True))
            ... except Exception:
            ...     pass
            >>> logging.disable(logging.NOTSET)
        """
        try:
            # Use nowait=True to fail fast if row is locked, preventing lock contention under high load
            try:
                prompt = get_for_update(db, DbPrompt, prompt_id, nowait=True)
            except OperationalError as lock_err:
                # Row is locked by another transaction - fail fast with 409
                db.rollback()
                raise PromptLockConflictError(f"Prompt {prompt_id} is currently being modified by another request") from lock_err
            if not prompt:
                raise PromptNotFoundError(f"Prompt not found: {prompt_id}")

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, prompt):
                    raise PermissionError("Only the owner can activate the Prompt" if activate else "Only the owner can deactivate the Prompt")

            if prompt.enabled != activate:
                prompt.enabled = activate
                prompt.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(prompt)

                # Invalidate cache after status change (skip for batch operations)
                if not skip_cache_invalidation:
                    cache = _get_registry_cache()
                    await cache.invalidate_prompts()

                if activate:
                    await self._notify_prompt_activated(prompt)
                else:
                    await self._notify_prompt_deactivated(prompt)
                logger.info(f"Prompt {prompt.name} {'activated' if activate else 'deactivated'}")

                # Structured logging: Audit trail for prompt state change
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="set_prompt_state",
                    resource_type="prompt",
                    resource_id=str(prompt.id),
                    resource_name=prompt.name,
                    user_email=user_email,
                    team_id=prompt.team_id,
                    new_values={"enabled": prompt.enabled},
                    context={"action": "activate" if activate else "deactivate"},
                    db=db,
                )

                structured_logger.log(
                    level="INFO",
                    message=f"Prompt {'activated' if activate else 'deactivated'} successfully",
                    event_type="prompt_state_changed",
                    component="prompt_service",
                    user_email=user_email,
                    team_id=prompt.team_id,
                    resource_type="prompt",
                    resource_id=str(prompt.id),
                    custom_fields={"prompt_name": prompt.name, "enabled": prompt.enabled},
                )

            prompt.team = self._get_team_name(db, prompt.team_id)
            return self.convert_prompt_to_read(prompt)
        except PermissionError as e:
            structured_logger.log(
                level="WARNING",
                message="Prompt state change failed due to permission error",
                event_type="prompt_state_change_permission_denied",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
            )
            raise e
        except PromptLockConflictError:
            # Re-raise lock conflicts without wrapping - allows 409 response
            raise
        except PromptNotFoundError:
            # Re-raise not found without wrapping - allows 404 response
            raise
        except Exception as e:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message="Prompt state change failed",
                event_type="prompt_state_change_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
            )
            raise PromptError(f"Failed to set prompt state: {str(e)}")

    # Get prompt details for admin ui

    async def get_prompt_details(
        self,
        db: Session,
        prompt_id: Union[int, str],
        include_inactive: bool = False,  # pylint: disable=unused-argument
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Get prompt details by ID with access control.

        Args:
            db: Database session
            prompt_id: ID of prompt
            include_inactive: Whether to include inactive prompts
            user_email: Email of the requesting user. ``None`` paired with ``token_teams=None`` means admin bypass.
            token_teams: JWT-scoped team list used for Layer 1 visibility checks.

        Returns:
            Dictionary of prompt details

        Raises:
            PromptNotFoundError: If the prompt is not found or the caller lacks visibility.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt_dict = {'id': '1', 'name': 'test', 'description': 'desc', 'template': 'tpl', 'arguments': [], 'createdAt': '2023-01-01T00:00:00', 'updatedAt': '2023-01-01T00:00:00', 'isActive': True, 'metrics': {}}
            >>> service.convert_prompt_to_read = MagicMock(return_value=prompt_dict)
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
            >>> import asyncio
            >>> result = asyncio.run(service.get_prompt_details(db, 'prompt_name'))
            >>> result == prompt_dict
            True
        """
        prompt = db.get(DbPrompt, prompt_id)
        if not prompt:
            raise PromptNotFoundError(f"Prompt not found: {prompt_id}")

        if not await self._check_prompt_access(db, prompt, user_email, token_teams):
            structured_logger.log(
                level="INFO",
                message="Prompt access denied",
                event_type="prompt_access_denied",
                component="prompt_service",
                resource_type="prompt",
                resource_id=str(prompt.id),
                team_id=getattr(prompt, "team_id", None),
                user_email=user_email,
                custom_fields={
                    "visibility": getattr(prompt, "visibility", None),
                    "admin_bypass": user_email is None and token_teams is None,
                },
            )
            raise PromptNotFoundError(f"Prompt not found: {prompt_id}")
        prompt.team = self._get_team_name(db, prompt.team_id)
        prompt_data = self.convert_prompt_to_read(prompt)

        audit_trail.log_action(
            user_id="system",
            action="view_prompt_details",
            resource_type="prompt",
            resource_id=str(prompt.id),
            resource_name=prompt.name,
            team_id=prompt.team_id,
            context={"include_inactive": include_inactive},
            db=db,
        )

        structured_logger.log(
            level="INFO",
            message="Prompt details retrieved",
            event_type="prompt_details_viewed",
            component="prompt_service",
            resource_type="prompt",
            resource_id=str(prompt.id),
            team_id=prompt.team_id,
            custom_fields={
                "prompt_name": prompt.name,
                "include_inactive": include_inactive,
            },
        )

        return prompt_data

    async def delete_prompt(self, db: Session, prompt_id: Union[int, str], user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """
        Delete a prompt template by its ID.

        Args:
            db (Session): Database session.
            prompt_id (str): ID of the prompt to delete.
            user_email (Optional[str]): Email of user performing delete (for ownership check).
            purge_metrics (bool): If True, delete raw + rollup metrics for this prompt.

        Raises:
            PromptNotFoundError: If the prompt is not found.
            PermissionError: If user doesn't own the prompt.
            PromptError: For other deletion errors.
            Exception: For unexpected errors.

        Examples:
            >>> import logging
            >>> logging.disable(logging.CRITICAL)
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import AsyncMock, MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> db.get.return_value = prompt
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_prompt_deleted = AsyncMock()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.delete_prompt(db, '123'))
            ... except Exception:
            ...     pass
            >>> logging.disable(logging.NOTSET)
        """
        try:
            prompt = db.get(DbPrompt, prompt_id)
            if not prompt:
                raise PromptNotFoundError(f"Prompt not found: {prompt_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, prompt):
                    raise PermissionError("Only the owner can delete this prompt")

            prompt_info = {"id": prompt.id, "name": prompt.name}
            prompt_name = prompt.name
            prompt_team_id = prompt.team_id

            if purge_metrics:
                with pause_rollup_during_purge(reason=f"purge_prompt:{prompt_id}"):
                    delete_metrics_in_batches(db, PromptMetric, PromptMetric.prompt_id, prompt_id)
                    delete_metrics_in_batches(db, PromptMetricsHourly, PromptMetricsHourly.prompt_id, prompt_id)

            db.delete(prompt)
            db.commit()
            await self._notify_prompt_deleted(prompt_info)
            logger.info(f"Deleted prompt: {prompt_info['name']}")

            # Structured logging: Audit trail for prompt deletion
            audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_prompt",
                resource_type="prompt",
                resource_id=str(prompt_info["id"]),
                resource_name=prompt_name,
                user_email=user_email,
                team_id=prompt_team_id,
                old_values={"name": prompt_name},
                db=db,
            )

            # Structured logging: Log successful prompt deletion
            structured_logger.log(
                level="INFO",
                message="Prompt deleted successfully",
                event_type="prompt_deleted",
                component="prompt_service",
                user_email=user_email,
                team_id=prompt_team_id,
                resource_type="prompt",
                resource_id=str(prompt_info["id"]),
                custom_fields={
                    "prompt_name": prompt_name,
                    "purge_metrics": purge_metrics,
                },
            )

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_prompts()
            # Also invalidate tags cache since prompt tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Prompt deletion failed due to permission error",
                event_type="prompt_delete_permission_denied",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=pe,
            )
            raise
        except Exception as e:
            db.rollback()
            if isinstance(e, PromptNotFoundError):
                # Structured logging: Log not found error
                structured_logger.log(
                    level="ERROR",
                    message="Prompt deletion failed - prompt not found",
                    event_type="prompt_not_found",
                    component="prompt_service",
                    user_email=user_email,
                    resource_type="prompt",
                    resource_id=str(prompt_id),
                    error=e,
                )
                raise e

            # Structured logging: Log generic prompt deletion failure
            structured_logger.log(
                level="ERROR",
                message="Prompt deletion failed",
                event_type="prompt_deletion_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
            )
            raise PromptError(f"Failed to delete prompt: {str(e)}")

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to Prompt events via the EventService.

        Yields:
            Prompt event messages.
        """
        async for event in self._event_service.subscribe_events():
            yield event

    def _validate_template(self, template: str) -> None:
        """Validate template syntax.

        Args:
            template: Template to validate

        Raises:
            PromptValidationError: If template is invalid

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> service._validate_template("Hello {{ name }}")  # Valid template
            >>> try:
            ...     service._validate_template("Hello {{ invalid")  # Invalid template
            ... except Exception as e:
            ...     "Invalid template syntax" in str(e)
            True
        """
        try:
            self._jinja_env.parse(template)
        except Exception as e:
            raise PromptValidationError(f"Invalid template syntax: {str(e)}")

    def _get_required_arguments(self, template: str) -> Set[str]:
        """Extract required arguments from template.

        Args:
            template: Template to analyze

        Returns:
            Set of required argument names

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> args = service._get_required_arguments("Hello {{ name }} from {{ place }}")
            >>> sorted(args)
            ['name', 'place']
            >>> service._get_required_arguments("No variables") == set()
            True
        """
        ast = self._jinja_env.parse(template)
        variables = meta.find_undeclared_variables(ast)
        formatter = Formatter()
        format_vars = {field_name for _, field_name, _, _ in formatter.parse(template) if field_name is not None}
        return variables.union(format_vars)

    def _render_template(self, template: str, arguments: Dict[str, str]) -> str:
        """Render template with arguments using cached compiled templates.

        Args:
            template: Template to render
            arguments: Arguments for rendering

        Returns:
            Rendered template text

        Raises:
            PromptError: If rendering fails

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> result = service._render_template("Hello {{ name }}", {"name": "World"})
            >>> result
            'Hello World'
            >>> service._render_template("No variables", {})
            'No variables'
        """
        try:
            jinja_template = _compile_jinja_template(template)
            return jinja_template.render(**arguments)
        except JinjaSecurityError as sec_err:
            # SandboxedEnvironment caught an unsafe attribute / call access
            # (e.g. {{ x.__class__.__subclasses__() }}). Do NOT fall through
            # to str.format: its attribute-access syntax ({x.__class__}) would
            # re-open the same hole we just blocked.
            raise PromptError(f"Failed to render template: sandbox rejected unsafe operation ({sec_err})")
        except Exception:
            try:
                return template.format(**arguments)
            except Exception as e:
                raise PromptError(f"Failed to render template: {str(e)}")

    def _parse_messages(self, text: str) -> List[Message]:
        """Parse rendered text into messages.

        Args:
            text: Text to parse

        Returns:
            List of parsed messages

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> messages = service._parse_messages("Simple text")
            >>> len(messages)
            1
            >>> messages[0].role.value
            'user'
            >>> messages = service._parse_messages("# User:\\nHello\\n# Assistant:\\nHi there")
            >>> len(messages)
            2
        """
        messages = []
        current_role = Role.USER
        current_text = []
        for line in text.split("\n"):
            if line.startswith("# Assistant:"):
                if current_text:
                    messages.append(
                        Message(
                            role=current_role,
                            content=TextContent(type="text", text="\n".join(current_text).strip()),
                        )
                    )
                current_role = Role.ASSISTANT
                current_text = []
            elif line.startswith("# User:"):
                if current_text:
                    messages.append(
                        Message(
                            role=current_role,
                            content=TextContent(type="text", text="\n".join(current_text).strip()),
                        )
                    )
                current_role = Role.USER
                current_text = []
            else:
                current_text.append(line)
        if current_text:
            messages.append(
                Message(
                    role=current_role,
                    content=TextContent(type="text", text="\n".join(current_text).strip()),
                )
            )
        return messages

    async def _notify_prompt_added(self, prompt: DbPrompt) -> None:
        """
        Notify subscribers of prompt addition.

        Args:
            prompt: Prompt to add
        """
        event = {
            "type": "prompt_added",
            "data": {
                "id": prompt.id,
                "name": prompt.name,
                "description": prompt.description,
                "enabled": prompt.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_prompt_updated(self, prompt: DbPrompt) -> None:
        """
        Notify subscribers of prompt update.

        Args:
            prompt: Prompt to update
        """
        event = {
            "type": "prompt_updated",
            "data": {
                "id": prompt.id,
                "name": prompt.name,
                "description": prompt.description,
                "enabled": prompt.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_prompt_activated(self, prompt: DbPrompt) -> None:
        """
        Notify subscribers of prompt activation.

        Args:
            prompt: Prompt to activate
        """
        event = {
            "type": "prompt_activated",
            "data": {"id": prompt.id, "name": prompt.name, "enabled": True},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_prompt_deactivated(self, prompt: DbPrompt) -> None:
        """
        Notify subscribers of prompt deactivation.

        Args:
            prompt: Prompt to deactivate
        """
        event = {
            "type": "prompt_deactivated",
            "data": {"id": prompt.id, "name": prompt.name, "enabled": False},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_prompt_deleted(self, prompt_info: Dict[str, Any]) -> None:
        """
        Notify subscribers of prompt deletion.

        Args:
            prompt_info: Dict on prompt to notify as deleted
        """
        event = {
            "type": "prompt_deleted",
            "data": prompt_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_prompt_removed(self, prompt: DbPrompt) -> None:
        """
        Notify subscribers of prompt removal (deactivation).

        Args:
            prompt: Prompt to remove
        """
        event = {
            "type": "prompt_removed",
            "data": {"id": prompt.id, "name": prompt.name, "enabled": False},
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

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> PromptMetrics:
        """
        Aggregate metrics for all prompt invocations across all prompts.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session

        Returns:
            PromptMetrics: Aggregated prompt metrics from raw + hourly rollups.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> service = PromptService()
            >>> # Method exists and is callable
            >>> callable(service.aggregate_metrics)
            True
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("prompts")
            if cached is not None:
                return PromptMetrics(**cached)

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "prompt")

        metrics = PromptMetrics(
            total_executions=result.total_executions,
            successful_executions=result.successful_executions,
            failed_executions=result.failed_executions,
            failure_rate=result.failure_rate,
            min_response_time=result.min_response_time,
            max_response_time=result.max_response_time,
            avg_response_time=result.avg_response_time,
            last_execution_time=result.last_execution_time,
        )

        # Cache the result as dict for serialization compatibility (if enabled)
        if is_cache_enabled():
            metrics_cache.set("prompts", metrics.model_dump())

        return metrics

    async def reset_metrics(self, db: Session) -> None:
        """
        Reset all prompt metrics by deleting raw and hourly rollup records.

        Args:
            db: Database session

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> db.execute = MagicMock()
            >>> db.commit = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.reset_metrics(db))
        """

        db.execute(delete(PromptMetric))
        db.execute(delete(PromptMetricsHourly))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("prompts")
        metrics_cache.invalidate_prefix("top_prompts:")


# Lazy singleton - created on first access, not at module import time.
# This avoids instantiation when only exception classes are imported.
_prompt_service_instance = None  # pylint: disable=invalid-name


def __getattr__(name: str):
    """Module-level __getattr__ for lazy singleton creation.

    Args:
        name: The attribute name being accessed.

    Returns:
        The prompt_service singleton instance if name is "prompt_service".

    Raises:
        AttributeError: If the attribute name is not "prompt_service".
    """
    global _prompt_service_instance  # pylint: disable=global-statement
    if name == "prompt_service":
        if _prompt_service_instance is None:
            _prompt_service_instance = PromptService()
        return _prompt_service_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
