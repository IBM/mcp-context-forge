# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/handlers/sampling.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

MCP Sampling Handler Implementation.
This module implements the sampling handler for MCP LLM interactions.
It handles model selection, sampling preferences, and message generation.

Examples:
    >>> import asyncio
    >>> from mcpgateway.models import ModelPreferences
    >>> handler = SamplingHandler()
    >>> asyncio.run(handler.initialize())
    >>>
    >>> # Test model selection
    >>> prefs = ModelPreferences(
    ...     cost_priority=0.2,
    ...     speed_priority=0.3,
    ...     intelligence_priority=0.5
    ... )
    >>> handler._select_model(prefs)
    'claude-3-haiku'
    >>>
    >>> # Test message validation
    >>> msg = {
    ...     "role": "user",
    ...     "content": {"type": "text", "text": "Hello"}
    ... }
    >>> handler._validate_message(msg)
    True
    >>>
    >>> # Test mock sampling
    >>> messages = [msg]
    >>> response = handler._mock_sample(messages)
    >>> print(response)
    You said: Hello
    Here is my response...
    >>>
    >>> asyncio.run(handler.shutdown())
"""

# Standard
from typing import Any, Dict, List

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.models import CreateMessageResult, ModelPreferences, Role, TextContent
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class SamplingError(Exception):
    """Base class for sampling errors."""


class SamplingHandler:
    """MCP sampling request handler.

    Handles:
    - Model selection based on preferences
    - Message sampling requests
    - Context management
    - Content validation

    Examples:
        >>> handler = SamplingHandler()
        >>> handler._supported_models['claude-3-haiku']
        (0.8, 0.9, 0.7)
        >>> len(handler._supported_models)
        4
    """

    def __init__(self):
        """Initialize sampling handler.

        Examples:
            >>> handler = SamplingHandler()
            >>> isinstance(handler._supported_models, dict)
            True
            >>> 'claude-3-opus' in handler._supported_models
            True
            >>> handler._supported_models['claude-3-sonnet']
            (0.5, 0.7, 0.9)
        """
        self._supported_models = {
            # Maps model names to capabilities scores (cost, speed, intelligence)
            "claude-3-haiku": (0.8, 0.9, 0.7),
            "claude-3-sonnet": (0.5, 0.7, 0.9),
            "claude-3-opus": (0.2, 0.5, 1.0),
            "gemini-1.5-pro": (0.6, 0.8, 0.8),
        }

    async def initialize(self) -> None:
        """Initialize sampling handler.

        Examples:
            >>> import asyncio
            >>> handler = SamplingHandler()
            >>> asyncio.run(handler.initialize())
            >>> # Handler is now initialized
        """
        logger.info("Initializing sampling handler")

    async def shutdown(self) -> None:
        """Shutdown sampling handler.

        Examples:
            >>> import asyncio
            >>> handler = SamplingHandler()
            >>> asyncio.run(handler.initialize())
            >>> asyncio.run(handler.shutdown())
            >>> # Handler is now shut down
        """
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

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> handler = SamplingHandler()
            >>> db = Mock()
            >>>
            >>> # Test with valid request
            >>> request = {
            ...     "messages": [{
            ...         "role": "user",
            ...         "content": {"type": "text", "text": "Hello"}
            ...     }],
            ...     "maxTokens": 100,
            ...     "modelPreferences": {
            ...         "cost_priority": 0.3,
            ...         "speed_priority": 0.3,
            ...         "intelligence_priority": 0.4
            ...     }
            ... }
            >>> result = asyncio.run(handler.create_message(db, request))
            >>> result.role
            <Role.ASSISTANT: 'assistant'>
            >>> result.content.type
            'text'
            >>> result.stop_reason
            'maxTokens'
            >>>
            >>> # Test with no messages
            >>> bad_request = {
            ...     "messages": [],
            ...     "maxTokens": 100,
            ...     "modelPreferences": {
            ...         "cost_priority": 0.3,
            ...         "speed_priority": 0.3,
            ...         "intelligence_priority": 0.4
            ...     }
            ... }
            >>> try:
            ...     asyncio.run(handler.create_message(db, bad_request))
            ... except SamplingError as e:
            ...     print(str(e))
            No messages provided
            >>>
            >>> # Test with no max tokens
            >>> bad_request = {
            ...     "messages": [{"role": "user", "content": {"type": "text", "text": "Hi"}}],
            ...     "modelPreferences": {
            ...         "cost_priority": 0.3,
            ...         "speed_priority": 0.3,
            ...         "intelligence_priority": 0.4
            ...     }
            ... }
            >>> try:
            ...     asyncio.run(handler.create_message(db, bad_request))
            ... except SamplingError as e:
            ...     print(str(e))
            Max tokens not specified
        """
        try:
            # Extract request parameters
            messages = request.get("messages", [])
            max_tokens = request.get("maxTokens")
            model_prefs = ModelPreferences.model_validate(request.get("modelPreferences", {}))
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

            # TODO: Implement actual model sampling - currently returns mock response  # pylint: disable=fixme
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

        Examples:
            >>> from mcpgateway.models import ModelPreferences, ModelHint
            >>> handler = SamplingHandler()
            >>>
            >>> # Test intelligence priority
            >>> prefs = ModelPreferences(
            ...     cost_priority=1.0,
            ...     speed_priority=0.0,
            ...     intelligence_priority=1.0
            ... )
            >>> handler._select_model(prefs)
            'claude-3-opus'
            >>>
            >>> # Test speed priority
            >>> prefs = ModelPreferences(
            ...     cost_priority=0.0,
            ...     speed_priority=1.0,
            ...     intelligence_priority=0.0
            ... )
            >>> handler._select_model(prefs)
            'claude-3-haiku'
            >>>
            >>> # Test balanced preferences
            >>> prefs = ModelPreferences(
            ...     cost_priority=0.33,
            ...     speed_priority=0.33,
            ...     intelligence_priority=0.34
            ... )
            >>> model = handler._select_model(prefs)
            >>> model in handler._supported_models
            True
            >>>
            >>> # Test with model hints
            >>> prefs = ModelPreferences(
            ...     hints=[ModelHint(name="opus")],
            ...     cost_priority=0.5,
            ...     speed_priority=0.3,
            ...     intelligence_priority=0.2
            ... )
            >>> handler._select_model(prefs)
            'claude-3-opus'
            >>>
            >>> # Test empty supported models (should raise error)
            >>> handler._supported_models = {}
            >>> try:
            ...     handler._select_model(prefs)
            ... except SamplingError as e:
            ...     print(str(e))
            No suitable model found
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

        Examples:
            >>> import asyncio
            >>> from unittest.mock import Mock
            >>> handler = SamplingHandler()
            >>> db = Mock()
            >>>
            >>> messages = [
            ...     {"role": "user", "content": {"type": "text", "text": "Hello"}},
            ...     {"role": "assistant", "content": {"type": "text", "text": "Hi there!"}}
            ... ]
            >>>
            >>> # Test with 'none' context type
            >>> result = asyncio.run(handler._add_context(db, messages, "none"))
            >>> result == messages
            True
            >>>
            >>> # Test with 'all' context type (currently returns same messages)
            >>> result = asyncio.run(handler._add_context(db, messages, "all"))
            >>> result == messages
            True
            >>> len(result)
            2
        """
        # TODO: Implement context gathering based on type - currently no-op  # pylint: disable=fixme
        # For now return original messages
        return messages

    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """Validate message format.

        Args:
            message: Message to validate

        Returns:
            True if valid

        Examples:
            >>> handler = SamplingHandler()
            >>>
            >>> # Valid text message
            >>> msg = {"role": "user", "content": {"type": "text", "text": "Hello"}}
            >>> handler._validate_message(msg)
            True
            >>>
            >>> # Valid assistant message
            >>> msg = {"role": "assistant", "content": {"type": "text", "text": "Hi!"}}
            >>> handler._validate_message(msg)
            True
            >>>
            >>> # Valid image message
            >>> msg = {
            ...     "role": "user",
            ...     "content": {
            ...         "type": "image",
            ...         "data": "base64data",
            ...         "mime_type": "image/png"
            ...     }
            ... }
            >>> handler._validate_message(msg)
            True
            >>>
            >>> # Missing role
            >>> msg = {"content": {"type": "text", "text": "Hello"}}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Invalid role
            >>> msg = {"role": "system", "content": {"type": "text", "text": "Hello"}}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Missing content
            >>> msg = {"role": "user"}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Invalid content type
            >>> msg = {"role": "user", "content": {"type": "audio"}}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Text content not string
            >>> msg = {"role": "user", "content": {"type": "text", "text": 123}}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Image missing data
            >>> msg = {"role": "user", "content": {"type": "image", "mime_type": "image/png"}}
            >>> handler._validate_message(msg)
            False
            >>>
            >>> # Invalid structure
            >>> handler._validate_message("not a dict")
            False
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

        Examples:
            >>> handler = SamplingHandler()
            >>>
            >>> # Single user message
            >>> messages = [{"role": "user", "content": {"type": "text", "text": "Hello world"}}]
            >>> handler._mock_sample(messages)
            'You said: Hello world\\nHere is my response...'
            >>>
            >>> # Conversation with multiple messages
            >>> messages = [
            ...     {"role": "user", "content": {"type": "text", "text": "Hi"}},
            ...     {"role": "assistant", "content": {"type": "text", "text": "Hello!"}},
            ...     {"role": "user", "content": {"type": "text", "text": "How are you?"}}
            ... ]
            >>> handler._mock_sample(messages)
            'You said: How are you?\\nHere is my response...'
            >>>
            >>> # Image message
            >>> messages = [{
            ...     "role": "user",
            ...     "content": {"type": "image", "data": "base64", "mime_type": "image/png"}
            ... }]
            >>> handler._mock_sample(messages)
            'You said: I see the image you shared.\\nHere is my response...'
            >>>
            >>> # No user messages
            >>> messages = [{"role": "assistant", "content": {"type": "text", "text": "Hi"}}]
            >>> handler._mock_sample(messages)
            "I'm not sure what to respond to."
            >>>
            >>> # Empty messages
            >>> handler._mock_sample([])
            "I'm not sure what to respond to."
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
