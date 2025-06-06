# -*- coding: utf-8 -*-
"""MCP Sampling Handler Implementation.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module implements the sampling handler for MCP LLM interactions.
It handles model selection, sampling preferences, and message generation.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from mcpgateway.types import CreateMessageResult, ModelPreferences, Role, TextContent

logger = logging.getLogger(__name__)


class SamplingError(Exception):
    """Base class for sampling errors."""


class SamplingHandler:
    """MCP sampling request handler.

    Handles:
    - Model selection based on preferences
    - Message sampling requests
    - Context management
    - Content validation
    """

    def __init__(self):
        """Initialize sampling handler."""
        self._supported_models = {
            # Maps model names to capabilities scores (cost, speed, intelligence)
            "claude-3-haiku": (0.8, 0.9, 0.7),
            "claude-3-sonnet": (0.5, 0.7, 0.9),
            "claude-3-opus": (0.2, 0.5, 1.0),
            "gemini-1.5-pro": (0.6, 0.8, 0.8),
        }

    async def initialize(self) -> None:
        """Initialize sampling handler."""
        logger.info("Initializing sampling handler")

    async def shutdown(self) -> None:
        """Shutdown sampling handler."""
        logger.info("Shutting down sampling handler")

    async def create_message(self, db: Session, request: Dict[str, Any]) -> CreateMessageResult:
        """Create message from sampling request.

        Args:
            db: Database session
            request: Sampling request parameters

        Returns:
            Sampled message result

        Raises:
            SamplingError: If sampling fails
        """
        try:
            # Extract request parameters
            messages = request.get("messages", [])
            max_tokens = request.get("maxTokens")
            model_prefs = ModelPreferences.parse_obj(request.get("modelPreferences", {}))
            include_context = request.get("includeContext", "none")
            request.get("metadata", {})

            # Validate request
            if not messages:
                raise SamplingError("No messages provided")
            if not max_tokens:
                raise SamplingError("Max tokens not specified")

            # Select model
            model = self._select_model(model_prefs)
            logger.info(f"Selected model: {model}")

            # Include context if requested
            if include_context != "none":
                messages = await self._add_context(db, messages, include_context)

            # Validate messages
            for msg in messages:
                if not self._validate_message(msg):
                    raise SamplingError(f"Invalid message format: {msg}")

            # TODO: Sample from selected model
            # For now return mock response
            response = self._mock_sample(messages=messages)

            # Convert to result
            return CreateMessageResult(
                content=TextContent(type="text", text=response),
                model=model,
                role=Role.ASSISTANT,
                stop_reason="maxTokens",
            )

        except Exception as e:
            logger.error(f"Sampling error: {e}")
            raise SamplingError(str(e))

    def _select_model(self, preferences: ModelPreferences) -> str:
        """Select model based on preferences.

        Args:
            preferences: Model selection preferences

        Returns:
            Selected model name

        Raises:
            SamplingError: If no suitable model found
        """
        # Check model hints first
        if preferences.hints:
            for hint in preferences.hints:
                for model in self._supported_models:
                    if hint.name and hint.name in model:
                        return model

        # Score models on preferences
        best_score = -1
        best_model = None

        for model, caps in self._supported_models.items():
            cost_score = caps[0] * (1 - preferences.cost_priority)
            speed_score = caps[1] * preferences.speed_priority
            intel_score = caps[2] * preferences.intelligence_priority

            total_score = (cost_score + speed_score + intel_score) / 3

            if total_score > best_score:
                best_score = total_score
                best_model = model

        if not best_model:
            raise SamplingError("No suitable model found")

        return best_model

    async def _add_context(self, _db: Session, messages: List[Dict[str, Any]], _context_type: str) -> List[Dict[str, Any]]:
        """Add context to messages.

        Args:
            _db: Database session
            messages: Message list
            _context_type: Context inclusion type

        Returns:
            Messages with added context
        """
        # TODO: Implement context gathering based on type
        # For now return original messages
        return messages

    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """Validate message format.

        Args:
            message: Message to validate

        Returns:
            True if valid
        """
        try:
            # Must have role and content
            if "role" not in message or "content" not in message or message["role"] not in ("user", "assistant"):
                return False

            # Content must be valid
            content = message["content"]
            if content.get("type") == "text":
                if not isinstance(content.get("text"), str):
                    return False
            elif content.get("type") == "image":
                if not (content.get("data") and content.get("mime_type")):
                    return False
            else:
                return False

            return True

        except Exception:
            return False

    def _mock_sample(
        self,
        messages: List[Dict[str, Any]],
    ) -> str:
        """Mock sampling response for testing.

        Args:
            messages: Input messages

        Returns:
            Sampled response text
        """
        # Extract last user message
        last_msg = None
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_msg = msg
                break

        if not last_msg:
            return "I'm not sure what to respond to."

        # Get user text
        user_text = ""
        content = last_msg["content"]
        if content["type"] == "text":
            user_text = content["text"]
        elif content["type"] == "image":
            user_text = "I see the image you shared."

        # Generate simple response
        return f"You said: {user_text}\nHere is my response..."
