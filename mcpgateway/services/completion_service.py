# -*- coding: utf-8 -*-
"""Completion Service Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements argument completion according to the MCP specification.
It handles completion suggestions for prompt arguments and resource URIs.
"""

# Standard
import logging
from typing import Any, Dict, List

# First-Party
from mcpgateway.db import Prompt as DbPrompt
from mcpgateway.db import Resource as DbResource
from mcpgateway.types import CompleteResult

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CompletionError(Exception):
    """Base class for completion errors."""


class CompletionService:
    """MCP completion service.

    Handles argument completion for:
    - Prompt arguments based on schema
    - Resource URIs with templates
    - Custom completion sources
    """

    def __init__(self):
        """Initialize completion service."""
        self._custom_completions: Dict[str, List[str]] = {}

    async def initialize(self) -> None:
        """Initialize completion service."""
        logger.info("Initializing completion service")

    async def shutdown(self) -> None:
        """Shutdown completion service."""
        logger.info("Shutting down completion service")
        self._custom_completions.clear()

    async def handle_completion(self, db: Session, request: Dict[str, Any]) -> CompleteResult:
        """Handle completion request.

        Args:
            db: Database session
            request: Completion request

        Returns:
            Completion result with suggestions

        Raises:
            CompletionError: If completion fails
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
                result = await self._complete_prompt_argument(db, ref, arg_name, arg_value)
            elif ref_type == "ref/resource":
                result = await self._complete_resource_uri(db, ref, arg_value)
            else:
                raise CompletionError(f"Invalid reference type: {ref_type}")

            return result

        except Exception as e:
            logger.error(f"Completion error: {e}")
            raise CompletionError(str(e))

    async def _complete_prompt_argument(self, db: Session, ref: Dict[str, Any], arg_name: str, arg_value: str) -> CompleteResult:
        """Complete prompt argument value.

        Args:
            db: Database session
            ref: Prompt reference
            arg_name: Argument name
            arg_value: Current argument value

        Returns:
            Completion suggestions

        Raises:
            CompletionError: If URI template is missing
        """
        # Get prompt
        prompt_name = ref.get("name")
        if not prompt_name:
            raise CompletionError("Missing prompt name")

        prompt = db.execute(select(DbPrompt).where(DbPrompt.name == prompt_name).where(DbPrompt.is_active)).scalar_one_or_none()

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

    async def _complete_resource_uri(self, db: Session, ref: Dict[str, Any], arg_value: str) -> CompleteResult:
        """Complete resource URI.

        Args:
            db: Database session
            ref: Resource reference
            arg_value: Current URI value

        Returns:
            URI completion suggestions

        Raises:
            CompletionError: If URI template is missing
        """
        # Get base URI template
        uri_template = ref.get("uri")
        if not uri_template:
            raise CompletionError("Missing URI template")

        # List matching resources
        resources = db.execute(select(DbResource).where(DbResource.is_active)).scalars().all()

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
        """
        self._custom_completions[arg_name] = list(values)

    def unregister_completions(self, arg_name: str) -> None:
        """Unregister custom completion values.

        Args:
            arg_name: Argument name
        """
        self._custom_completions.pop(arg_name, None)
