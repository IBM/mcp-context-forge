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
from datetime import datetime, timezone
from functools import lru_cache
import os
from string import Formatter
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union
import uuid

# Third-Party
from jinja2 import Environment, meta, select_autoescape, Template
from sqlalchemy import and_, delete, desc, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, Session

# First-Party
from mcpgateway.common.models import Message, PromptResult, Role, TextContent
from mcpgateway.config import settings
from mcpgateway.db import EmailTeam
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric, PromptMetricsHourly, server_prompt_association
from mcpgateway.observability import create_span
from mcpgateway.plugins.framework import GlobalContext, PluginContextTable, PluginManager, PromptHookType, PromptPosthookPayload, PromptPrehookPayload
from mcpgateway.schemas import PromptCreate, PromptRead, PromptUpdate, TopPerformer
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import unified_paginate
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None

# Module-level Jinja environment singleton for template caching
_JINJA_ENV: Optional[Environment] = None


def _get_jinja_env() -> Environment:
    """Get or create the module-level Jinja environment singleton.

    Returns:
        Jinja2 Environment with autoescape and trim settings.
    """
    global _JINJA_ENV  # pylint: disable=global-statement
    if _JINJA_ENV is None:
        _JINJA_ENV = Environment(
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

# Initialize structured logger and audit trail for prompt operations
structured_logger = get_structured_logger("prompt_service")
audit_trail = get_audit_trail_service()


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


class PromptService:
    """Service for managing prompt templates.

    Handles:
    - Template registration and retrieval
    - Argument validation
    - Template rendering
    - Resource embedding
    - Active/inactive status management
    """

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
        # Initialize plugin manager with env overrides for testability
        env_flag = os.getenv("PLUGINS_ENABLED")
        if env_flag is not None:
            env_enabled = env_flag.strip().lower() in {"1", "true", "yes", "on"}
            plugins_enabled = env_enabled
        else:
            plugins_enabled = settings.plugins_enabled
        config_file = os.getenv("PLUGIN_CONFIG_FILE", getattr(settings, "plugin_config_file", "plugins/config.yaml"))
        self._plugin_manager: PluginManager | None = PluginManager(config_file) if plugins_enabled else None

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
            db=db,
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
            total = len(db_prompt.metrics) if hasattr(db_prompt, "metrics") and db_prompt.metrics is not None else 0
            successful = sum(1 for m in db_prompt.metrics if m.is_success) if total > 0 else 0
            failed = sum(1 for m in db_prompt.metrics if not m.is_success) if total > 0 else 0
            failure_rate = failed / total if total > 0 else 0.0
            min_rt = min((m.response_time for m in db_prompt.metrics), default=None) if total > 0 else None
            max_rt = max((m.response_time for m in db_prompt.metrics), default=None) if total > 0 else None
            avg_rt = (sum(m.response_time for m in db_prompt.metrics) / total) if total > 0 else None
            last_time = max((m.timestamp for m in db_prompt.metrics), default=None) if total > 0 else None

            metrics_dict = {
                "totalExecutions": total,
                "successfulExecutions": successful,
                "failedExecutions": failed,
                "failureRate": failure_rate,
                "minResponseTime": min_rt,
                "maxResponseTime": max_rt,
                "avgResponseTime": avg_rt,
                "lastExecutionTime": last_time,
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

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_added = MagicMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.register_prompt(db, prompt))
            ... except Exception:
            ...     pass
        """
        try:
            # Validate template syntax
            self._validate_template(prompt.template)

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
            computed_name = self._compute_prompt_name(custom_name)

            # Create DB model
            db_prompt = DbPrompt(
                name=computed_name,
                original_name=prompt.name,
                custom_name=custom_name,
                display_name=display_name,
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
            )
            # Check for existing server with the same name
            if visibility.lower() == "public":
                # Check for existing public prompt with the same name
                existing_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "public")).scalar_one_or_none()
                if existing_prompt:
                    raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
            elif visibility.lower() == "team":
                # Check for existing team prompt with the same name
                existing_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "team", DbPrompt.team_id == team_id)).scalar_one_or_none()
                if existing_prompt:
                    raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)

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
                db=db,
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
                db=db,
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
                db=db,
            )
            raise se
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
                db=db,
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

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompts = [MagicMock(), MagicMock()]
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.register_prompts_bulk(db, prompts))
            ... except Exception:
            ...     pass
        """
        if not prompts:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        # Process in chunks to avoid memory issues and SQLite parameter limits
        chunk_size = 500

        for chunk_start in range(0, len(prompts), chunk_size):
            chunk = prompts[chunk_start : chunk_start + chunk_size]

            try:
                # Batch check for existing prompts to detect conflicts
                prompt_names = []
                for prompt in chunk:
                    custom_name = getattr(prompt, "custom_name", None) or prompt.name
                    prompt_names.append(self._compute_prompt_name(custom_name))

                if visibility.lower() == "public":
                    existing_prompts_query = select(DbPrompt).where(DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "public")
                elif visibility.lower() == "team" and team_id:
                    existing_prompts_query = select(DbPrompt).where(DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "team", DbPrompt.team_id == team_id)
                else:
                    # Private prompts - check by owner
                    existing_prompts_query = select(DbPrompt).where(DbPrompt.name.in_(prompt_names), DbPrompt.visibility == "private", DbPrompt.owner_email == (owner_email or created_by))

                existing_prompts = db.execute(existing_prompts_query).scalars().all()
                existing_prompts_map = {prompt.name: prompt for prompt in existing_prompts}

                prompts_to_add = []
                prompts_to_update = []

                for prompt in chunk:
                    try:
                        # Validate template syntax
                        self._validate_template(prompt.template)

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
                        prompt_visibility = visibility if visibility is not None else getattr(prompt, "visibility", "public")

                        custom_name = getattr(prompt, "custom_name", None) or prompt.name
                        display_name = getattr(prompt, "display_name", None) or custom_name
                        computed_name = self._compute_prompt_name(custom_name)

                        existing_prompt = existing_prompts_map.get(computed_name)

                        if existing_prompt:
                            # Handle conflict based on strategy
                            if conflict_strategy == "skip":
                                stats["skipped"] += 1
                                continue
                            if conflict_strategy == "update":
                                # Update existing prompt
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
                                computed_name = self._compute_prompt_name(new_custom_name)
                                db_prompt = DbPrompt(
                                    name=computed_name,
                                    original_name=prompt.name,
                                    custom_name=new_custom_name,
                                    display_name=new_display_name,
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
                                )
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
                            )
                            prompts_to_add.append(db_prompt)
                            stats["created"] += 1

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
            db=db,
        )

        return stats

    async def list_prompts(
        self,
        db: Session,
        include_inactive: bool = False,
        cursor: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
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
            limit (Optional[int]): Maximum number of prompts to return. Use 0 for all prompts (no limit).
                If not specified, uses pagination_default_page_size.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email (Optional[str]): User email for team-based access control. If None, no access control is applied.
            team_id (Optional[str]): Filter by specific team ID. Requires user_email for access validation.
            visibility (Optional[str]): Filter by visibility (private, team, public).

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
        # Check cache for first page only (cursor=None) - skip when user_email provided or page based pagination
        cache = _get_registry_cache()
        if cursor is None and user_email is None and page is None:
            filters_hash = cache.hash_filters(include_inactive=include_inactive, tags=sorted(tags) if tags else None)
            cached = await cache.get("prompts", filters_hash)
            if cached is not None:
                # Reconstruct PromptRead objects from cached dicts
                cached_prompts = [PromptRead.model_validate(p) for p in cached["prompts"]]
                return (cached_prompts, cached.get("next_cursor"))

        # Build base query with ordering and eager load gateway to avoid N+1
        query = select(DbPrompt).options(joinedload(DbPrompt.gateway)).order_by(desc(DbPrompt.created_at), desc(DbPrompt.id))

        if not include_inactive:
            query = query.where(DbPrompt.enabled)

        # Apply team-based access control if user_email is provided
        if user_email:
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            if team_id:
                # User requesting specific team - verify access
                if team_id not in team_ids:
                    return ([], None)
                access_conditions = [
                    and_(DbPrompt.team_id == team_id, DbPrompt.visibility.in_(["team", "public"])),
                    and_(DbPrompt.team_id == team_id, DbPrompt.owner_email == user_email),
                ]
                query = query.where(or_(*access_conditions))
            else:
                # General access: user's prompts + public prompts + team prompts
                access_conditions = [
                    DbPrompt.owner_email == user_email,
                    DbPrompt.visibility == "public",
                ]
                if team_ids:
                    access_conditions.append(and_(DbPrompt.team_id.in_(team_ids), DbPrompt.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            if visibility:
                query = query.where(DbPrompt.visibility == visibility)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbPrompt.tags, tags, match_any=True))

        # Use unified pagination helper - handles both page and cursor pagination
        pag_result = await unified_paginate(
            db=db,
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
            s.team = team_map.get(s.team_id) if s.team_id else None
            result.append(self.convert_prompt_to_read(s, include_metrics=False))
        # Return appropriate format based on pagination type
        if page is not None:
            # Page-based format
            return {
                "data": result,
                "pagination": pag_result["pagination"],
                "links": pag_result["links"],
            }

        # Cursor-based format

        # Cache first page results - only for non-user-specific queries
        if cursor is None and user_email is None:
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
            t.team = team_map.get(str(t.team_id)) if t.team_id else None
            result.append(self.convert_prompt_to_read(t, include_metrics=False))
        return result

    async def list_server_prompts(self, db: Session, server_id: str, include_inactive: bool = False, cursor: Optional[str] = None) -> List[PromptRead]:
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
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.

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
        # Eager load gateway to avoid N+1 when accessing gateway_slug
        query = (
            select(DbPrompt)
            .options(joinedload(DbPrompt.gateway))
            .join(server_prompt_association, DbPrompt.id == server_prompt_association.c.prompt_id)
            .where(server_prompt_association.c.server_id == server_id)
        )
        if not include_inactive:
            query = query.where(DbPrompt.enabled)
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
            t.team = team_map.get(str(t.team_id)) if t.team_id else None
            result.append(self.convert_prompt_to_read(t, include_metrics=False))
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

    async def get_prompt(
        self,
        db: Session,
        prompt_id: Union[int, str],
        arguments: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
        tenant_id: Optional[str] = None,
        server_id: Optional[str] = None,
        request_id: Optional[str] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
    ) -> PromptResult:
        """Get a prompt template and optionally render it.

        Args:
            db: Database session
            prompt_id: ID of the prompt to retrieve
            arguments: Optional arguments for rendering
            user: Optional user identifier for plugin context
            tenant_id: Optional tenant identifier for plugin context
            server_id: Optional server identifier for plugin context
            request_id: Optional request ID, generated if not provided
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.

        Returns:
            Prompt result with rendered messages

        Raises:
            PluginViolationError: If prompt violates a plugin policy
            PromptNotFoundError: If prompt not found
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

        # Create database span for observability dashboard
        trace_id = current_trace_id.get()
        db_span_id = None
        db_span_ended = False
        observability_service = ObservabilityService() if trace_id else None

        if trace_id and observability_service:
            try:
                db_span_id = observability_service.start_span(
                    db=db,
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
        with create_span(
            "prompt.render",
            {
                "prompt.id": prompt_id,
                "arguments_count": len(arguments) if arguments else 0,
                "user": user or "anonymous",
                "server_id": server_id,
                "tenant_id": tenant_id,
                "request_id": request_id or "none",
            },
        ) as span:
            try:
                # Check if any prompt hooks are registered to avoid unnecessary context creation
                has_pre_fetch = self._plugin_manager and self._plugin_manager.has_hooks_for(PromptHookType.PROMPT_PRE_FETCH)
                has_post_fetch = self._plugin_manager and self._plugin_manager.has_hooks_for(PromptHookType.PROMPT_POST_FETCH)

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
                    pre_result, context_table = await self._plugin_manager.invoke_hook(
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

                # Find prompt by ID first, then by name (active prompts only)
                search_key = str(prompt_id)
                prompt = db.execute(select(DbPrompt).where(DbPrompt.id == prompt_id).where(DbPrompt.enabled)).scalar_one_or_none()
                if not prompt:
                    prompt = db.execute(select(DbPrompt).where(DbPrompt.name == prompt_id).where(DbPrompt.enabled)).scalar_one_or_none()

                if not prompt:
                    # Check if an inactive prompt exists
                    inactive_prompt = db.execute(select(DbPrompt).where(DbPrompt.id == prompt_id).where(not_(DbPrompt.enabled))).scalar_one_or_none()
                    if not inactive_prompt:
                        inactive_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == prompt_id).where(not_(DbPrompt.enabled))).scalar_one_or_none()

                    if inactive_prompt:
                        raise PromptNotFoundError(f"Prompt '{search_key}' exists but is inactive")

                    raise PromptNotFoundError(f"Prompt not found: {search_key}")

                if not arguments:
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
                        if span:
                            span.set_attribute("error", True)
                            span.set_attribute("error.message", str(e))
                        raise PromptError(f"Failed to process prompt: {str(e)}")

                if has_post_fetch:
                    post_result, _ = await self._plugin_manager.invoke_hook(
                        PromptHookType.PROMPT_POST_FETCH,
                        payload=PromptPosthookPayload(prompt_id=str(prompt.id), result=result),
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
                    db=db,
                )

                # Set success attributes on span
                if span:
                    span.set_attribute("success", True)
                    span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)
                    if result and hasattr(result, "messages"):
                        span.set_attribute("messages.count", len(result.messages))

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
                        # First-Party
                        from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service  # pylint: disable=import-outside-toplevel

                        metrics_buffer = get_metrics_buffer_service()
                        metrics_buffer.record_prompt_metric(
                            prompt_id=prompt.id,
                            start_time=start_time,
                            success=success,
                            error_message=error_message,
                        )
                    except Exception as metrics_error:
                        logger.warning(f"Failed to record prompt metric: {metrics_error}")

                # End database span for observability dashboard
                if db_span_id and observability_service and not db_span_ended:
                    try:
                        observability_service.end_span(
                            db=db,
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

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_updated = MagicMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.update_prompt(db, 'prompt_name', MagicMock()))
            ... except Exception:
            ...     pass
        """
        try:
            prompt = db.get(DbPrompt, prompt_id)
            if not prompt:
                raise PromptNotFoundError(f"Prompt not found: {prompt_id}")

            visibility = prompt_update.visibility or prompt.visibility
            team_id = prompt_update.team_id or prompt.team_id
            owner_email = prompt_update.owner_email or prompt.owner_email or user_email

            candidate_custom_name = prompt.custom_name

            if prompt_update.name is not None:
                candidate_custom_name = prompt_update.custom_name or prompt_update.name
            elif prompt_update.custom_name is not None:
                candidate_custom_name = prompt_update.custom_name

            computed_name = self._compute_prompt_name(candidate_custom_name, prompt.gateway)
            if computed_name != prompt.name:
                if visibility.lower() == "public":
                    existing_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "public", DbPrompt.id != prompt.id)).scalar_one_or_none()
                    if existing_prompt:
                        raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
                elif visibility.lower() == "team" and team_id:
                    existing_prompt = db.execute(
                        select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "team", DbPrompt.team_id == team_id, DbPrompt.id != prompt.id)
                    ).scalar_one_or_none()
                    logger.info(f"Existing prompt check result: {existing_prompt}")
                    if existing_prompt:
                        raise PromptNameConflictError(computed_name, enabled=existing_prompt.enabled, prompt_id=existing_prompt.id, visibility=existing_prompt.visibility)
                elif visibility.lower() == "private":
                    existing_prompt = db.execute(
                        select(DbPrompt).where(DbPrompt.name == computed_name, DbPrompt.visibility == "private", DbPrompt.owner_email == owner_email, DbPrompt.id != prompt.id)
                    ).scalar_one_or_none()
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
            if prompt_update.template is not None:
                prompt.template = prompt_update.template
                self._validate_template(prompt.template)
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
                prompt.visibility = prompt_update.visibility

            # Update tags if provided
            if prompt_update.tags is not None:
                prompt.tags = prompt_update.tags

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
                db=db,
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
                db=db,
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
                db=db,
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
                db=db,
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
                db=db,
            )
            raise pnce
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
                db=db,
            )
            raise PromptError(f"Failed to update prompt: {str(e)}")

    async def toggle_prompt_status(self, db: Session, prompt_id: int, activate: bool, user_email: Optional[str] = None) -> PromptRead:
        """
        Toggle the activation status of a prompt.

        Args:
            db: Database session
            prompt_id: Prompt ID
            activate: True to activate, False to deactivate
            user_email: Optional[str] The email of the user to check if the user has permission to modify.

        Returns:
            The updated PromptRead object

        Raises:
            PromptNotFoundError: If the prompt is not found
            PromptError: For other errors
            PermissionError: If user doesn't own the agent.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> db.get.return_value = prompt
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_prompt_activated = MagicMock()
            >>> service._notify_prompt_deactivated = MagicMock()
            >>> service.convert_prompt_to_read = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.toggle_prompt_status(db, 1, True))
            ... except Exception:
            ...     pass
        """
        try:
            prompt = db.get(DbPrompt, prompt_id)
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

                # Invalidate cache after status change
                cache = _get_registry_cache()
                await cache.invalidate_prompts()

                if activate:
                    await self._notify_prompt_activated(prompt)
                else:
                    await self._notify_prompt_deactivated(prompt)
                logger.info(f"Prompt {prompt.name} {'activated' if activate else 'deactivated'}")

                # Structured logging: Audit trail for prompt status toggle
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="toggle_prompt_status",
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
                    event_type="prompt_status_toggled",
                    component="prompt_service",
                    user_email=user_email,
                    team_id=prompt.team_id,
                    resource_type="prompt",
                    resource_id=str(prompt.id),
                    custom_fields={"prompt_name": prompt.name, "enabled": prompt.enabled},
                    db=db,
                )

            prompt.team = self._get_team_name(db, prompt.team_id)
            return self.convert_prompt_to_read(prompt)
        except PermissionError as e:
            structured_logger.log(
                level="WARNING",
                message="Prompt status toggle failed due to permission error",
                event_type="prompt_toggle_permission_denied",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
                db=db,
            )
            raise e
        except Exception as e:
            db.rollback()

            structured_logger.log(
                level="ERROR",
                message="Prompt status toggle failed",
                event_type="prompt_toggle_failed",
                component="prompt_service",
                user_email=user_email,
                resource_type="prompt",
                resource_id=str(prompt_id),
                error=e,
                db=db,
            )
            raise PromptError(f"Failed to toggle prompt status: {str(e)}")

    # Get prompt details for admin ui
    async def get_prompt_details(self, db: Session, prompt_id: Union[int, str], include_inactive: bool = False) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """
        Get prompt details by ID.

        Args:
            db: Database session
            prompt_id: ID of prompt
            include_inactive: Whether to include inactive prompts

        Returns:
            Dictionary of prompt details

        Raises:
            PromptNotFoundError: If the prompt is not found

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
        # Return the fully converted prompt including metrics
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
            db=db,
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
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt = MagicMock()
            >>> db.get.return_value = prompt
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_prompt_deleted = MagicMock()
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.delete_prompt(db, '123'))
            ... except Exception:
            ...     pass
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
                db=db,
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
                db=db,
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
                    db=db,
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
                db=db,
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
    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """
        Aggregate metrics for all prompt invocations across all prompts.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session

        Returns:
            Dict[str, Any]: Aggregated prompt metrics from raw + hourly rollups.

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
                return cached

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "prompt")
        metrics = result.to_dict()

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set("prompts", metrics)

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
