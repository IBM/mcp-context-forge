# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/completion_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Completion Service Implementation.
This module implements argument completion according to the MCP specification.
It handles completion suggestions for prompt arguments and resource URIs.

Examples:
    >>> from mcpgateway.services.completion_service import CompletionService, CompletionError
    >>> service = CompletionService()
    >>> isinstance(service, CompletionService)
    True
    >>> service._custom_completions
    {}
"""

# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.common.models import CompleteResult
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CompletionError(Exception):
    """Base class for completion errors.

    Examples:
        >>> from mcpgateway.services.completion_service import CompletionError
        >>> err = CompletionError("Invalid reference")
        >>> str(err)
        'Invalid reference'
        >>> isinstance(err, Exception)
        True
    """


class CompletionService:
    """MCP completion service.

    Handles argument completion for:
    - Prompt arguments based on schema
    - Resource URIs with templates
    - Custom completion sources
    """

    def __init__(self):
        """Initialize completion service.

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> hasattr(service, '_custom_completions')
            True
            >>> service._custom_completions
            {}
        """
        self._custom_completions: Dict[str, List[str]] = {}

    async def initialize(self) -> None:
        """Initialize completion service."""
        logger.info("Initializing completion service")

    async def shutdown(self) -> None:
        """Shutdown completion service."""
        logger.info("Shutting down completion service")
        self._custom_completions.clear()

    async def handle_completion(
        self,
        db: Session,
        request: Dict[str, Any],
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> CompleteResult:
        """Handle completion request.

        Args:
            db: Database session
            request: Completion request
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)

        Returns:
            Completion result with suggestions

        Raises:
            CompletionError: If completion fails

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> from unittest.mock import MagicMock
            >>> service = CompletionService()
            >>> db = MagicMock()
            >>> request = {'ref': {'type': 'ref/prompt', 'name': 'prompt1'}, 'argument': {'name': 'arg1', 'value': ''}}
            >>> db.execute.return_value.scalars.return_value.all.return_value = []
            >>> import asyncio
            >>> try:
            ...     asyncio.run(service.handle_completion(db, request))
            ... except Exception:
            ...     pass
        """
        try:
            # Get reference and argument info
            ref = request.get("ref", {})
            ref_type = ref.get("type")
            arg = request.get("argument", {})
            arg_name = arg.get("name")
            arg_value = arg.get("value", "")

            if not ref_type or not arg_name:
                raise CompletionError("Missing reference type or argument name")

            # Handle different reference types
            if ref_type == "ref/prompt":
                result = await self._complete_prompt_argument(db, ref, arg_name, arg_value, user_email=user_email, token_teams=token_teams)
            elif ref_type == "ref/resource":
                result = await self._complete_resource_uri(db, ref, arg_value, user_email=user_email, token_teams=token_teams)
            else:
                raise CompletionError(f"Invalid reference type: {ref_type}")

            return result

        except Exception as e:
            logger.error(f"Completion error: {e}")
            raise CompletionError(str(e))

    async def _resolve_team_ids(self, db: Session, user_email: Optional[str], token_teams: Optional[List[str]]) -> List[str]:
        """Resolve effective team IDs for scoped visibility checks.

        Args:
            db: Database session
            user_email: Caller email for DB-based team lookup when token teams are not explicit
            token_teams: Explicit token team scope when present

        Returns:
            Effective team IDs used to build visibility filters.
        """
        if token_teams is not None:
            return token_teams
        if not user_email:
            return []

        # First-Party
        from mcpgateway.services.team_management_service import TeamManagementService  # pylint: disable=import-outside-toplevel

        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        return [team.id for team in user_teams]

    def _apply_visibility_scope(self, stmt, model, user_email: Optional[str], token_teams: Optional[List[str]], team_ids: List[str]):
        """Apply token/user visibility scope to a SQLAlchemy statement.

        Args:
            stmt: SQLAlchemy statement to constrain
            model: ORM model that includes visibility/team/owner columns
            user_email: Caller email used for owner visibility
            token_teams: Explicit token team scope when present
            team_ids: Effective team IDs for team visibility

        Returns:
            Scoped SQLAlchemy statement.
        """
        if token_teams is None and user_email is None:
            return stmt

        is_public_only_token = token_teams is not None and len(token_teams) == 0
        access_conditions = [model.visibility == "public"]

        if not is_public_only_token and user_email:
            access_conditions.append(model.owner_email == user_email)

        if team_ids:
            access_conditions.append(and_(model.team_id.in_(team_ids), model.visibility.in_(["team", "public"])))

        return stmt.where(or_(*access_conditions))

    async def _complete_prompt_argument(
        self,
        db: Session,
        ref: Dict[str, Any],
        arg_name: str,
        arg_value: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> CompleteResult:
        """Complete prompt argument value.

        Args:
            db: Database session
            ref: Prompt reference
            arg_name: Argument name
            arg_value: Current argument value
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)

        Returns:
            Completion suggestions

        Raises:
            CompletionError: If prompt is missing or not found

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService, CompletionError
            >>> from unittest.mock import MagicMock
            >>> import asyncio
            >>> service = CompletionService()
            >>> db = MagicMock()

            >>> # Test missing prompt name
            >>> ref = {}
            >>> try:
            ...     asyncio.run(service._complete_prompt_argument(db, ref, 'arg1', 'val'))
            ... except CompletionError as e:
            ...     str(e)
            'Missing prompt name'

            >>> # Test custom completions
            >>> service.register_completions('color', ['red', 'green', 'blue'])
            >>> db.execute.return_value.scalar_one_or_none.return_value = MagicMock(
            ...     argument_schema={'properties': {'color': {'name': 'color'}}}
            ... )
            >>> result = asyncio.run(service._complete_prompt_argument(
            ...     db, {'name': 'test'}, 'color', 'r'
            ... ))
            >>> result.completion['values']
            ['red', 'green']
        """
        # Get prompt
        prompt_name = ref.get("name")
        if not prompt_name:
            raise CompletionError("Missing prompt name")

        # Only consider prompts that are enabled and visible to caller
        team_ids = await self._resolve_team_ids(db, user_email, token_teams)
        stmt = select(DbPrompt).where(DbPrompt.name == prompt_name).where(DbPrompt.enabled)
        stmt = self._apply_visibility_scope(stmt, DbPrompt, user_email=user_email, token_teams=token_teams, team_ids=team_ids)
        stmt = stmt.order_by(desc(DbPrompt.created_at), desc(DbPrompt.id)).limit(1)
        prompt = db.execute(stmt).scalar_one_or_none()

        if not prompt:
            raise CompletionError(f"Prompt not found: {prompt_name}")

        # Find argument in schema
        arg_schema = None
        for arg in prompt.argument_schema.get("properties", {}).values():
            if arg.get("name") == arg_name:
                arg_schema = arg
                break

        if not arg_schema:
            raise CompletionError(f"Argument not found: {arg_name}")

        # Get enum values if defined
        if "enum" in arg_schema:
            values = [v for v in arg_schema["enum"] if arg_value.lower() in str(v).lower()]
            return CompleteResult(
                completion={
                    "values": values[:100],
                    "total": len(values),
                    "hasMore": len(values) > 100,
                }
            )

        # Check custom completions
        if arg_name in self._custom_completions:
            values = [v for v in self._custom_completions[arg_name] if arg_value.lower() in v.lower()]
            return CompleteResult(
                completion={
                    "values": values[:100],
                    "total": len(values),
                    "hasMore": len(values) > 100,
                }
            )

        # No completions available
        return CompleteResult(completion={"values": [], "total": 0, "hasMore": False})

    async def _complete_resource_uri(
        self,
        db: Session,
        ref: Dict[str, Any],
        arg_value: str,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> CompleteResult:
        """Complete resource URI.

        Args:
            db: Database session
            ref: Resource reference
            arg_value: Current URI value
            user_email: Caller email used for owner/team visibility checks
            token_teams: Normalized token teams (`None` admin bypass, `[]` public-only, list for team scope)

        Returns:
            URI completion suggestions

        Raises:
            CompletionError: If URI template is missing

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService, CompletionError
            >>> from unittest.mock import MagicMock
            >>> import asyncio
            >>> service = CompletionService()
            >>> db = MagicMock()

            >>> # Test missing URI template
            >>> ref = {}
            >>> try:
            ...     asyncio.run(service._complete_resource_uri(db, ref, 'test'))
            ... except CompletionError as e:
            ...     str(e)
            'Missing URI template'

            >>> # Test resource filtering
            >>> ref = {'uri': 'template://'}
            >>> mock_resources = [
            ...     MagicMock(uri='file://doc1.txt'),
            ...     MagicMock(uri='file://doc2.txt'),
            ...     MagicMock(uri='http://example.com')
            ... ]
            >>> db.execute.return_value.scalars.return_value.all.return_value = mock_resources
            >>> result = asyncio.run(service._complete_resource_uri(db, ref, 'doc'))
            >>> len(result.completion['values'])
            2
            >>> 'file://doc1.txt' in result.completion['values']
            True
        """
        # Get base URI template
        uri_template = ref.get("uri")
        if not uri_template:
            raise CompletionError("Missing URI template")

        # List matching resources visible to caller
        team_ids = await self._resolve_team_ids(db, user_email, token_teams)
        stmt = select(DbResource).where(DbResource.enabled)
        stmt = self._apply_visibility_scope(stmt, DbResource, user_email=user_email, token_teams=token_teams, team_ids=team_ids)
        resources = db.execute(stmt).scalars().all()

        # Filter by URI pattern
        matches = []
        for resource in resources:
            if arg_value.lower() in resource.uri.lower():
                matches.append(resource.uri)

        return CompleteResult(
            completion={
                "values": matches[:100],
                "total": len(matches),
                "hasMore": len(matches) > 100,
            }
        )

    def register_completions(self, arg_name: str, values: List[str]) -> None:
        """Register custom completion values.

        Args:
            arg_name: Argument name
            values: Completion values

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> service.register_completions('arg1', ['a', 'b'])
            >>> service._custom_completions['arg1']
            ['a', 'b']
            >>> service.register_completions('arg2', ['x', 'y', 'z'])
            >>> len(service._custom_completions)
            2
            >>> service.register_completions('arg1', ['c'])  # Overwrite
            >>> service._custom_completions['arg1']
            ['c']
        """
        self._custom_completions[arg_name] = list(values)

    def unregister_completions(self, arg_name: str) -> None:
        """Unregister custom completion values.

        Args:
            arg_name: Argument name

        Examples:
            >>> from mcpgateway.services.completion_service import CompletionService
            >>> service = CompletionService()
            >>> service.register_completions('arg1', ['a', 'b'])
            >>> service.unregister_completions('arg1')
            >>> 'arg1' in service._custom_completions
            False
        """
        self._custom_completions.pop(arg_name, None)
