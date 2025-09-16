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
import asyncio
from datetime import datetime, timezone
import os
from string import Formatter
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
import uuid

# Third-Party
from jinja2 import Environment, meta, select_autoescape
from sqlalchemy import case, delete, desc, Float, func, not_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import PromptMetric, server_prompt_association
from mcpgateway.models import Message, PromptResult, Role, TextContent
from mcpgateway.observability import create_span
from mcpgateway.plugins.framework import GlobalContext, PluginManager, PromptPosthookPayload, PromptPrehookPayload
from mcpgateway.schemas import PromptCreate, PromptRead, PromptUpdate, TopPerformer
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.sqlalchemy_modifier import json_contains_expr

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class PromptError(Exception):
    """Base class for prompt-related errors."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt is not found."""


class PromptNameConflictError(PromptError):
    """Raised when a prompt name conflicts with existing (active or inactive) prompt."""

    def __init__(self, name: str, is_active: bool = True, prompt_id: Optional[int] = None):
        """Initialize the error with prompt information.

        Args:
            name: The conflicting prompt name
            is_active: Whether the existing prompt is active
            prompt_id: ID of the existing prompt if available

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptNameConflictError
            >>> error = PromptNameConflictError("test_prompt")
            >>> error.name
            'test_prompt'
            >>> error.is_active
            True
            >>> error.prompt_id is None
            True
            >>> error = PromptNameConflictError("inactive_prompt", False, 123)
            >>> error.is_active
            False
            >>> error.prompt_id
            123
        """
        self.name = name
        self.is_active = is_active
        self.prompt_id = prompt_id
        message = f"Prompt already exists with name: {name}"
        if not is_active:
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
            >>> service._event_subscribers
            []
            >>> service._jinja_env is not None
            True
        """
        self._event_subscribers: List[asyncio.Queue] = []
        self._jinja_env = Environment(autoescape=select_autoescape(["html", "xml"]), trim_blocks=True, lstrip_blocks=True)
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

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> import asyncio
            >>> service = PromptService()
            >>> service._event_subscribers.append("test_subscriber")
            >>> asyncio.run(service.shutdown())
            >>> service._event_subscribers
            []
        """
        self._event_subscribers.clear()
        logger.info("Prompt service shutdown complete")

    async def get_top_prompts(self, db: Session, limit: int = 5) -> List[TopPerformer]:
        """Retrieve the top-performing prompts based on execution count.

        Queries the database to get prompts with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing prompt details and
        performance metrics.

        Args:
            db (Session): Database session for querying prompt metrics.
            limit (int): Maximum number of prompts to return. Defaults to 5.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Prompt ID.
                - name: Prompt name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        results = (
            db.query(
                DbPrompt.id,
                DbPrompt.name,
                func.count(PromptMetric.id).label("execution_count"),  # pylint: disable=not-callable
                func.avg(PromptMetric.response_time).label("avg_response_time"),  # pylint: disable=not-callable
                case(
                    (
                        func.count(PromptMetric.id) > 0,  # pylint: disable=not-callable
                        func.sum(case((PromptMetric.is_success.is_(True), 1), else_=0)).cast(Float) / func.count(PromptMetric.id) * 100,  # pylint: disable=not-callable
                    ),
                    else_=None,
                ).label("success_rate"),
                func.max(PromptMetric.timestamp).label("last_execution"),  # pylint: disable=not-callable
            )
            .outerjoin(PromptMetric)
            .group_by(DbPrompt.id, DbPrompt.name)
            .order_by(desc("execution_count"))
            .limit(limit)
            .all()
        )

        return build_top_performers(results)

    def _convert_db_prompt(self, db_prompt: DbPrompt) -> Dict[str, Any]:
        """
        Convert a DbPrompt instance to a dictionary matching the PromptRead schema,
        including aggregated metrics computed from the associated PromptMetric records.

        Args:
            db_prompt: Db prompt to convert

        Returns:
            dict: Dictionary matching the PromptRead schema
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
        total = len(db_prompt.metrics) if hasattr(db_prompt, "metrics") and db_prompt.metrics is not None else 0
        successful = sum(1 for m in db_prompt.metrics if m.is_success) if total > 0 else 0
        failed = sum(1 for m in db_prompt.metrics if not m.is_success) if total > 0 else 0
        failure_rate = failed / total if total > 0 else 0.0
        min_rt = min((m.response_time for m in db_prompt.metrics), default=None) if total > 0 else None
        max_rt = max((m.response_time for m in db_prompt.metrics), default=None) if total > 0 else None
        avg_rt = (sum(m.response_time for m in db_prompt.metrics) / total) if total > 0 else None
        last_time = max((m.timestamp for m in db_prompt.metrics), default=None) if total > 0 else None

        return {
            "id": db_prompt.id,
            "name": db_prompt.name,
            "description": db_prompt.description,
            "template": db_prompt.template,
            "arguments": arguments_list,
            "created_at": db_prompt.created_at,
            "updated_at": db_prompt.updated_at,
            "is_active": db_prompt.is_active,
            "metrics": {
                "totalExecutions": total,
                "successfulExecutions": successful,
                "failedExecutions": failed,
                "failureRate": failure_rate,
                "minResponseTime": min_rt,
                "maxResponseTime": max_rt,
                "avgResponseTime": avg_rt,
                "lastExecutionTime": last_time,
            },
            "tags": db_prompt.tags or [],
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
        }

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
        visibility: str = "private",
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
            >>> service._convert_db_prompt = MagicMock(return_value={})
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

            # Create DB model
            db_prompt = DbPrompt(
                name=prompt.name,
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

            # Add to DB
            db.add(db_prompt)
            db.commit()
            db.refresh(db_prompt)

            # Notify subscribers
            await self._notify_prompt_added(db_prompt)

            logger.info(f"Registered prompt: {prompt.name}")
            prompt_dict = self._convert_db_prompt(db_prompt)
            return PromptRead.model_validate(prompt_dict)

        except IntegrityError as ie:
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except Exception as e:
            db.rollback()
            raise PromptError(f"Failed to register prompt: {str(e)}")

    async def list_prompts(self, db: Session, include_inactive: bool = False, cursor: Optional[str] = None, tags: Optional[List[str]] = None) -> List[PromptRead]:
        """
        Retrieve a list of prompt templates from the database.

        This method retrieves prompt templates from the database and converts them into a list
        of PromptRead objects. It supports filtering out inactive prompts based on the
        include_inactive parameter. The cursor parameter is reserved for future pagination support
        but is currently not implemented.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive prompts in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.
            tags (Optional[List[str]]): Filter prompts by tags. If provided, only prompts with at least one matching tag will be returned.

        Returns:
            List[PromptRead]: A list of prompt templates represented as PromptRead objects.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> from mcpgateway.schemas import PromptRead
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> prompt_dict = {'id': '1', 'name': 'test', 'description': 'desc', 'template': 'tpl', 'arguments': [], 'createdAt': '2023-01-01T00:00:00', 'updatedAt': '2023-01-01T00:00:00', 'isActive': True, 'metrics': {}}
            >>> service._convert_db_prompt = MagicMock(return_value=prompt_dict)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> PromptRead.model_validate = MagicMock(return_value='prompt_read')
            >>> import asyncio
            >>> result = asyncio.run(service.list_prompts(db))
            >>> result == ['prompt_read']
            True
        """
        query = select(DbPrompt)
        if not include_inactive:
            query = query.where(DbPrompt.is_active)

        # Add tag filtering if tags are provided
        if tags:
            query = query.where(json_contains_expr(db, DbPrompt.tags, tags, match_any=True))

        # Cursor-based pagination logic can be implemented here in the future.
        logger.debug(cursor)
        prompts = db.execute(query).scalars().all()
        return [PromptRead.model_validate(self._convert_db_prompt(p)) for p in prompts]

    async def list_prompts_for_user(
        self, db: Session, user_email: str, team_id: Optional[str] = None, visibility: Optional[str] = None, include_inactive: bool = False, skip: int = 0, limit: int = 100
    ) -> List[PromptRead]:
        """
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
        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

        # Build query following existing patterns from list_prompts()
        query = select(DbPrompt)

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbPrompt.is_active)

        if team_id:
            # Filter by specific team
            query = query.where(DbPrompt.team_id == team_id)

            # Validate user has access to team
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            if team_id not in team_ids:
                return []  # No access to team
        else:
            # Get user's accessible teams
            team_service = TeamManagementService(db)
            user_teams = await team_service.get_user_teams(user_email)
            team_ids = [team.id for team in user_teams]

            # Build access conditions following existing patterns
            # Third-Party
            from sqlalchemy import and_, or_  # pylint: disable=import-outside-toplevel

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
        return [PromptRead.model_validate(self._convert_db_prompt(p)) for p in prompts]

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
            >>> prompt_dict = {'id': '1', 'name': 'test', 'description': 'desc', 'template': 'tpl', 'arguments': [], 'createdAt': '2023-01-01T00:00:00', 'updatedAt': '2023-01-01T00:00:00', 'isActive': True, 'metrics': {}}
            >>> service._convert_db_prompt = MagicMock(return_value=prompt_dict)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> PromptRead.model_validate = MagicMock(return_value='prompt_read')
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_prompts(db, 'server1'))
            >>> result == ['prompt_read']
            True
        """
        query = select(DbPrompt).join(server_prompt_association, DbPrompt.id == server_prompt_association.c.prompt_id).where(server_prompt_association.c.server_id == server_id)
        if not include_inactive:
            query = query.where(DbPrompt.is_active)
        # Cursor-based pagination logic can be implemented here in the future.
        logger.debug(cursor)
        prompts = db.execute(query).scalars().all()
        return [PromptRead.model_validate(self._convert_db_prompt(p)) for p in prompts]

    async def get_prompt(
        self,
        db: Session,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
        tenant_id: Optional[str] = None,
        server_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> PromptResult:
        """Get a prompt template and optionally render it.

        Args:
            db: Database session
            name: Name of prompt to get
            arguments: Optional arguments for rendering
            user: Optional user identifier for plugin context
            tenant_id: Optional tenant identifier for plugin context
            server_id: Optional server identifier for plugin context
            request_id: Optional request ID, generated if not provided

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
            ...     asyncio.run(service.get_prompt(db, 'prompt_name'))
            ... except Exception:
            ...     pass
        """

        start_time = time.monotonic()

        # Create a trace span for prompt rendering
        with create_span(
            "prompt.render",
            {
                "prompt.name": name,
                "arguments_count": len(arguments) if arguments else 0,
                "user": user or "anonymous",
                "server_id": server_id,
                "tenant_id": tenant_id,
                "request_id": request_id or "none",
            },
        ) as span:
            if self._plugin_manager:
                if not request_id:
                    request_id = uuid.uuid4().hex
                global_context = GlobalContext(request_id=request_id, user=user, server_id=server_id, tenant_id=tenant_id)
                pre_result, context_table = await self._plugin_manager.prompt_pre_fetch(
                    payload=PromptPrehookPayload(name=name, args=arguments), global_context=global_context, local_contexts=None, violations_as_exceptions=True
                )

                # Use modified payload if provided
                if pre_result.modified_payload:
                    payload = pre_result.modified_payload
                    name = payload.name
                    arguments = payload.args

            # Find prompt
            prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name).where(DbPrompt.is_active)).scalar_one_or_none()

            if not prompt:
                inactive_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name).where(not_(DbPrompt.is_active))).scalar_one_or_none()
                if inactive_prompt:
                    raise PromptNotFoundError(f"Prompt '{name}' exists but is inactive")

                raise PromptNotFoundError(f"Prompt not found: {name}")

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

            if self._plugin_manager:
                post_result, _ = await self._plugin_manager.prompt_post_fetch(
                    payload=PromptPosthookPayload(name=name, result=result), global_context=global_context, local_contexts=context_table, violations_as_exceptions=True
                )
                # Use modified payload if provided
                return post_result.modified_payload.result if post_result.modified_payload else result

            # Set success attributes on span
            if span:
                span.set_attribute("success", True)
                span.set_attribute("duration.ms", (time.monotonic() - start_time) * 1000)
                if result and hasattr(result, "messages"):
                    span.set_attribute("messages.count", len(result.messages))

            return result

    async def update_prompt(
        self,
        db: Session,
        name: str,
        prompt_update: PromptUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> PromptRead:
        """
        Update a prompt template.

        Args:
            db: Database session
            name: Name of prompt to update
            prompt_update: Prompt update object
            modified_by: Username of the person modifying the prompt
            modified_from_ip: IP address where the modification originated
            modified_via: Source of modification (ui/api/import)
            modified_user_agent: User agent string from the modification request

        Returns:
            The updated PromptRead object

        Raises:
            PromptNotFoundError: If the prompt is not found
            IntegrityError: If a database integrity error occurs.
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
            >>> service._convert_db_prompt = MagicMock(return_value={})
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.update_prompt(db, 'prompt_name', MagicMock()))
            ... except Exception:
            ...     pass
        """
        try:
            prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name).where(DbPrompt.is_active)).scalar_one_or_none()
            if not prompt:
                inactive_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name).where(not_(DbPrompt.is_active))).scalar_one_or_none()

                if inactive_prompt:
                    raise PromptNotFoundError(f"Prompt '{name}' exists but is inactive")

                raise PromptNotFoundError(f"Prompt not found: {name}")

            if prompt_update.name is not None:
                prompt.name = prompt_update.name
            if prompt_update.description is not None:
                prompt.description = prompt_update.description
            if prompt_update.template is not None:
                prompt.template = prompt_update.template
                self._validate_template(prompt.template)
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
            return PromptRead.model_validate(self._convert_db_prompt(prompt))

        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityErrors in group: {ie}")
            raise ie
        except PromptNotFoundError as e:
            db.rollback()
            logger.error(f"Prompt not found: {e}")
            raise e
        except Exception as e:
            db.rollback()
            raise PromptError(f"Failed to update prompt: {str(e)}")

    async def toggle_prompt_status(self, db: Session, prompt_id: int, activate: bool) -> PromptRead:
        """
        Toggle the activation status of a prompt.

        Args:
            db: Database session
            prompt_id: Prompt ID
            activate: True to activate, False to deactivate

        Returns:
            The updated PromptRead object

        Raises:
            PromptNotFoundError: If the prompt is not found
            PromptError: For other errors

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
            >>> service._convert_db_prompt = MagicMock(return_value={})
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
            if prompt.is_active != activate:
                prompt.is_active = activate
                prompt.updated_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(prompt)
                if activate:
                    await self._notify_prompt_activated(prompt)
                else:
                    await self._notify_prompt_deactivated(prompt)
                logger.info(f"Prompt {prompt.name} {'activated' if activate else 'deactivated'}")
            return PromptRead.model_validate(self._convert_db_prompt(prompt))
        except Exception as e:
            db.rollback()
            raise PromptError(f"Failed to toggle prompt status: {str(e)}")

    # Get prompt details for admin ui
    async def get_prompt_details(self, db: Session, name: str, include_inactive: bool = False) -> Dict[str, Any]:
        """
        Get prompt details by name.

        Args:
            db: Database session
            name: Name of prompt
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
            >>> service._convert_db_prompt = MagicMock(return_value=prompt_dict)
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock()
            >>> import asyncio
            >>> result = asyncio.run(service.get_prompt_details(db, 'prompt_name'))
            >>> result == prompt_dict
            True
        """
        query = select(DbPrompt).where(DbPrompt.name == name)
        if not include_inactive:
            query = query.where(DbPrompt.is_active)
        prompt = db.execute(query).scalar_one_or_none()
        if not prompt:
            if not include_inactive:
                inactive_prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name).where(not_(DbPrompt.is_active))).scalar_one_or_none()
                if inactive_prompt:
                    raise PromptNotFoundError(f"Prompt '{name}' exists but is inactive")
            raise PromptNotFoundError(f"Prompt not found: {name}")
        # Return the fully converted prompt including metrics
        return self._convert_db_prompt(prompt)

    async def delete_prompt(self, db: Session, name: str) -> None:
        """
        Delete a prompt template.

        Args:
            db: Database session
            name: Name of prompt to delete

        Raises:
            PromptNotFoundError: If the prompt is not found
            PromptError: For other deletion errors
            Exception: For unexpected errors

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
            ...     asyncio.run(service.delete_prompt(db, 'prompt_name'))
            ... except Exception:
            ...     pass
        """
        try:
            prompt = db.execute(select(DbPrompt).where(DbPrompt.name == name)).scalar_one_or_none()
            if not prompt:
                raise PromptNotFoundError(f"Prompt not found: {name}")
            prompt_info = {"id": prompt.id, "name": prompt.name}
            db.delete(prompt)
            db.commit()
            await self._notify_prompt_deleted(prompt_info)
            logger.info(f"Permanently deleted prompt: {name}")
        except Exception as e:
            db.rollback()
            if isinstance(e, PromptNotFoundError):
                raise e
            raise PromptError(f"Failed to delete prompt: {str(e)}")

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to prompt events.

        Yields:
            Prompt event messages
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._event_subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._event_subscribers.remove(queue)

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
        """Render template with arguments.

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
            jinja_template = self._jinja_env.from_string(template)
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
                "is_active": prompt.is_active,
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
                "is_active": prompt.is_active,
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
            "data": {"id": prompt.id, "name": prompt.name, "is_active": True},
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
            "data": {"id": prompt.id, "name": prompt.name, "is_active": False},
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
            "data": {"id": prompt.id, "name": prompt.name, "is_active": False},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers.

        Args:
            event: Dictionary containing event info
        """
        for queue in self._event_subscribers:
            await queue.put(event)

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> Dict[str, Any]:
        """
        Aggregate metrics for all prompt invocations across all prompts.

        Args:
            db: Database session

        Returns:
            Dict[str, Any]: Aggregated prompt metrics with keys:
                - total_executions
                - successful_executions
                - failed_executions
                - failure_rate
                - min_response_time
                - max_response_time
                - avg_response_time
                - last_execution_time
            Aggregated metrics computed from all PromptMetric records.

        Examples:
            >>> from mcpgateway.services.prompt_service import PromptService
            >>> from unittest.mock import MagicMock
            >>> service = PromptService()
            >>> db = MagicMock()
            >>> db.execute.return_value.scalar.return_value = 0
            >>> import asyncio
            >>> result = asyncio.run(service.aggregate_metrics(db))
            >>> isinstance(result, dict)
            True
        """

        total = db.execute(select(func.count(PromptMetric.id))).scalar() or 0  # pylint: disable=not-callable
        successful = db.execute(select(func.count(PromptMetric.id)).where(PromptMetric.is_success.is_(True))).scalar() or 0  # pylint: disable=not-callable
        failed = db.execute(select(func.count(PromptMetric.id)).where(PromptMetric.is_success.is_(False))).scalar() or 0  # pylint: disable=not-callable
        failure_rate = failed / total if total > 0 else 0.0
        min_rt = db.execute(select(func.min(PromptMetric.response_time))).scalar()
        max_rt = db.execute(select(func.max(PromptMetric.response_time))).scalar()
        avg_rt = db.execute(select(func.avg(PromptMetric.response_time))).scalar()
        last_time = db.execute(select(func.max(PromptMetric.timestamp))).scalar()

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

    async def reset_metrics(self, db: Session) -> None:
        """
        Reset all prompt metrics by deleting all records from the prompt metrics table.

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
        db.commit()
