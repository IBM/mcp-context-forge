# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/llm_proxy_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

LLM Proxy Service

This module implements the internal proxy for routing LLM requests
to configured providers. It translates requests to provider-specific
formats and handles streaming responses.
"""

# Standard
import json
import time
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
import uuid

# Third-Party
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import LLMModel, LLMProvider, LLMProviderType
from mcpgateway.llm_schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    UsageStats,
)
from mcpgateway.services.llm_provider_service import (
    LLMModelNotFoundError,
    LLMProviderNotFoundError,
)
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.utils.services_auth import decode_auth

# Initialize logging
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class LLMProxyError(Exception):
    """Base class for LLM proxy errors."""


class LLMProxyAuthError(LLMProxyError):
    """Raised when authentication fails."""


class LLMProxyRequestError(LLMProxyError):
    """Raised when request to provider fails."""


class LLMProxyService:
    """Service for proxying LLM requests to configured providers.

    Handles request translation, streaming, and response formatting
    for the internal /v1/chat/completions endpoint.
    """

    def __init__(self) -> None:
        """Initialize the LLM proxy service."""
        self._initialized = False
        self._client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the proxy service and HTTP client."""
        if not self._initialized:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_request_timeout, connect=30.0))
            logger.info("Initialized LLM Proxy Service")
            self._initialized = True

    async def shutdown(self) -> None:
        """Shutdown the proxy service and close connections."""
        if self._initialized and self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Shutdown LLM Proxy Service")
            self._initialized = False

    def _resolve_model(
        self,
        db: Session,
        model_id: str,
    ) -> Tuple[LLMProvider, LLMModel]:
        """Resolve a model ID to provider and model.

        Args:
            db: Database session.
            model_id: Model ID (can be model.id, model.model_id, or model.model_alias).

        Returns:
            Tuple of (LLMProvider, LLMModel).

        Raises:
            LLMModelNotFoundError: If model not found.
            LLMProviderNotFoundError: If provider not found or disabled.
        """
        # Try to find by model.id first
        model = db.execute(select(LLMModel).where(LLMModel.id == model_id)).scalar_one_or_none()

        # Try by model_id
        if not model:
            model = db.execute(select(LLMModel).where(LLMModel.model_id == model_id)).scalar_one_or_none()

        # Try by model_alias
        if not model:
            model = db.execute(select(LLMModel).where(LLMModel.model_alias == model_id)).scalar_one_or_none()

        if not model:
            raise LLMModelNotFoundError(f"Model not found: {model_id}")

        if not model.enabled:
            raise LLMModelNotFoundError(f"Model is disabled: {model_id}")

        # Get provider
        provider = db.execute(select(LLMProvider).where(LLMProvider.id == model.provider_id)).scalar_one_or_none()

        if not provider:
            raise LLMProviderNotFoundError(f"Provider not found for model: {model_id}")

        if not provider.enabled:
            raise LLMProviderNotFoundError(f"Provider is disabled: {provider.name}")

        return provider, model

    def _get_api_key(self, provider: LLMProvider) -> Optional[str]:
        """Extract API key from provider.

        Args:
            provider: LLM provider instance.

        Returns:
            Decrypted API key or None.
        """
        if not provider.api_key:
            return None

        try:
            auth_data = decode_auth(provider.api_key)
            return auth_data.get("api_key")
        except Exception as e:
            logger.error(f"Failed to decode API key for provider {provider.name}: {e}")
            return None

    def _build_openai_request(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
        model: LLMModel,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """Build request for OpenAI-compatible providers.

        Args:
            request: Chat completion request.
            provider: LLM provider.
            model: LLM model.

        Returns:
            Tuple of (url, headers, body).
        """
        api_key = self._get_api_key(provider)
        base_url = provider.api_base or "https://api.openai.com/v1"

        url = f"{base_url.rstrip('/')}/chat/completions"

        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Build request body
        body: Dict[str, Any] = {
            "model": model.model_id,
            "messages": [msg.model_dump(exclude_none=True) for msg in request.messages],
        }

        # Add optional parameters
        if request.temperature is not None:
            body["temperature"] = request.temperature
        elif provider.default_temperature:
            body["temperature"] = provider.default_temperature

        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        elif provider.default_max_tokens:
            body["max_tokens"] = provider.default_max_tokens

        if request.stream:
            body["stream"] = True

        if request.tools:
            body["tools"] = [t.model_dump() for t in request.tools]
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.frequency_penalty is not None:
            body["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            body["presence_penalty"] = request.presence_penalty
        if request.stop:
            body["stop"] = request.stop

        return url, headers, body

    def _build_azure_request(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
        model: LLMModel,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """Build request for Azure OpenAI.

        Args:
            request: Chat completion request.
            provider: LLM provider.
            model: LLM model.

        Returns:
            Tuple of (url, headers, body).
        """
        api_key = self._get_api_key(provider)
        base_url = provider.api_base or ""
        api_version = provider.api_version or "2024-02-15-preview"
        deployment = provider.config.get("deployment") or model.model_id

        url = f"{base_url.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

        headers = {
            "Content-Type": "application/json",
            "api-key": api_key or "",
        }

        # Build request body (similar to OpenAI)
        body: Dict[str, Any] = {
            "messages": [msg.model_dump(exclude_none=True) for msg in request.messages],
        }

        if request.temperature is not None:
            body["temperature"] = request.temperature
        elif provider.default_temperature:
            body["temperature"] = provider.default_temperature

        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        elif provider.default_max_tokens:
            body["max_tokens"] = provider.default_max_tokens

        if request.stream:
            body["stream"] = True

        return url, headers, body

    def _build_anthropic_request(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
        model: LLMModel,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """Build request for Anthropic Claude.

        Args:
            request: Chat completion request.
            provider: LLM provider.
            model: LLM model.

        Returns:
            Tuple of (url, headers, body).
        """
        api_key = self._get_api_key(provider)
        base_url = provider.api_base or "https://api.anthropic.com"

        url = f"{base_url.rstrip('/')}/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key or "",
            "anthropic-version": provider.api_version or "2023-06-01",
        }

        # Convert messages to Anthropic format
        system_message = None
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                messages.append(
                    {
                        "role": msg.role,
                        "content": msg.content or "",
                    }
                )

        body: Dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens or provider.default_max_tokens or 4096,
        }

        if system_message:
            body["system"] = system_message

        if request.temperature is not None:
            body["temperature"] = request.temperature
        elif provider.default_temperature:
            body["temperature"] = provider.default_temperature

        if request.stream:
            body["stream"] = True

        return url, headers, body

    def _build_ollama_request(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
        model: LLMModel,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        """Build request for Ollama.

        Args:
            request: Chat completion request.
            provider: LLM provider.
            model: LLM model.

        Returns:
            Tuple of (url, headers, body).
        """
        base_url = provider.api_base or "http://localhost:11434"
        base_url = base_url.rstrip("/")

        # Check if using OpenAI-compatible endpoint
        if base_url.endswith("/v1"):
            # Use OpenAI-compatible API
            url = f"{base_url}/chat/completions"
            headers = {"Content-Type": "application/json"}
            body: Dict[str, Any] = {
                "model": model.model_id,
                "messages": [{"role": msg.role, "content": msg.content or ""} for msg in request.messages],
                "stream": request.stream,
            }
            if request.temperature is not None:
                body["temperature"] = request.temperature
            elif provider.default_temperature:
                body["temperature"] = provider.default_temperature
            if request.max_tokens:
                body["max_tokens"] = request.max_tokens
            elif provider.default_max_tokens:
                body["max_tokens"] = provider.default_max_tokens
        else:
            # Use native Ollama API
            url = f"{base_url}/api/chat"
            headers = {"Content-Type": "application/json"}
            body = {
                "model": model.model_id,
                "messages": [{"role": msg.role, "content": msg.content or ""} for msg in request.messages],
                "stream": request.stream,
            }
            options = {}
            if request.temperature is not None:
                options["temperature"] = request.temperature
            elif provider.default_temperature:
                options["temperature"] = provider.default_temperature
            if options:
                body["options"] = options

        return url, headers, body

    async def chat_completion(
        self,
        db: Session,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """Process a chat completion request (non-streaming).

        Args:
            db: Database session.
            request: Chat completion request.

        Returns:
            ChatCompletionResponse.

        Raises:
            LLMProxyRequestError: If request fails.
        """
        if not self._client:
            await self.initialize()

        provider, model = self._resolve_model(db, request.model)

        # Build request based on provider type
        if provider.provider_type == LLMProviderType.AZURE_OPENAI:
            url, headers, body = self._build_azure_request(request, provider, model)
        elif provider.provider_type == LLMProviderType.ANTHROPIC:
            url, headers, body = self._build_anthropic_request(request, provider, model)
        elif provider.provider_type == LLMProviderType.OLLAMA:
            url, headers, body = self._build_ollama_request(request, provider, model)
        else:
            # Default to OpenAI-compatible
            url, headers, body = self._build_openai_request(request, provider, model)

        # Ensure non-streaming
        body["stream"] = False

        try:
            response = await self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

            # Transform response based on provider
            if provider.provider_type == LLMProviderType.ANTHROPIC:
                return self._transform_anthropic_response(data, model.model_id)
            if provider.provider_type == LLMProviderType.OLLAMA:
                # Check if using OpenAI-compatible endpoint
                base_url = (provider.api_base or "").rstrip("/")
                if base_url.endswith("/v1"):
                    return self._transform_openai_response(data)
                return self._transform_ollama_response(data, model.model_id)
            return self._transform_openai_response(data)

        except httpx.HTTPStatusError as e:
            logger.error(f"LLM request failed: {e.response.status_code} - {e.response.text}")
            raise LLMProxyRequestError(f"Request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"LLM request error: {e}")
            raise LLMProxyRequestError(f"Connection error: {str(e)}")

    async def chat_completion_stream(
        self,
        db: Session,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[str, None]:
        """Process a streaming chat completion request.

        Args:
            db: Database session.
            request: Chat completion request.

        Yields:
            SSE-formatted string chunks.
        """
        if not self._client:
            await self.initialize()

        provider, model = self._resolve_model(db, request.model)

        # Build request based on provider type
        if provider.provider_type == LLMProviderType.AZURE_OPENAI:
            url, headers, body = self._build_azure_request(request, provider, model)
        elif provider.provider_type == LLMProviderType.ANTHROPIC:
            url, headers, body = self._build_anthropic_request(request, provider, model)
        elif provider.provider_type == LLMProviderType.OLLAMA:
            url, headers, body = self._build_ollama_request(request, provider, model)
        else:
            url, headers, body = self._build_openai_request(request, provider, model)

        # Ensure streaming
        body["stream"] = True

        response_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        try:
            async with self._client.stream("POST", url, headers=headers, json=body) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    # Handle SSE format
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break

                        try:
                            data = json.loads(data_str)

                            # Transform based on provider
                            if provider.provider_type == LLMProviderType.ANTHROPIC:
                                chunk = self._transform_anthropic_stream_chunk(data, response_id, created, model.model_id)
                            elif provider.provider_type == LLMProviderType.OLLAMA:
                                # Check if using OpenAI-compatible endpoint
                                base_url = (provider.api_base or "").rstrip("/")
                                if base_url.endswith("/v1"):
                                    chunk = data_str  # Already OpenAI format
                                else:
                                    chunk = self._transform_ollama_stream_chunk(data, response_id, created, model.model_id)
                            else:
                                chunk = data_str

                            if chunk:
                                yield f"data: {chunk}\n\n"

                        except json.JSONDecodeError:
                            continue

                    # Handle Ollama's newline-delimited JSON (native API only)
                    elif provider.provider_type == LLMProviderType.OLLAMA:
                        base_url = (provider.api_base or "").rstrip("/")
                        if not base_url.endswith("/v1"):
                            try:
                                data = json.loads(line)
                                chunk = self._transform_ollama_stream_chunk(data, response_id, created, model.model_id)
                                if chunk:
                                    yield f"data: {chunk}\n\n"
                            except json.JSONDecodeError:
                                continue

        except httpx.HTTPStatusError as e:
            error_chunk = {
                "error": {
                    "message": f"Request failed: {e.response.status_code}",
                    "type": "proxy_error",
                }
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
        except httpx.RequestError as e:
            error_chunk = {
                "error": {
                    "message": f"Connection error: {str(e)}",
                    "type": "proxy_error",
                }
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"

    def _transform_openai_response(self, data: Dict[str, Any]) -> ChatCompletionResponse:
        """Transform OpenAI response to standard format.

        Args:
            data: Raw OpenAI API response data.

        Returns:
            ChatCompletionResponse in standard format.
        """
        choices = []
        for choice in data.get("choices", []):
            message_data = choice.get("message", {})
            choices.append(
                ChatChoice(
                    index=choice.get("index", 0),
                    message=ChatMessage(
                        role=message_data.get("role", "assistant"),
                        content=message_data.get("content"),
                        tool_calls=message_data.get("tool_calls"),
                    ),
                    finish_reason=choice.get("finish_reason"),
                )
            )

        usage_data = data.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
            created=data.get("created", int(time.time())),
            model=data.get("model", "unknown"),
            choices=choices,
            usage=usage,
        )

    def _transform_anthropic_response(
        self,
        data: Dict[str, Any],
        model_id: str,
    ) -> ChatCompletionResponse:
        """Transform Anthropic response to OpenAI format.

        Args:
            data: Raw Anthropic API response data.
            model_id: Model ID to include in response.

        Returns:
            ChatCompletionResponse in OpenAI format.
        """
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        usage_data = data.get("usage", {})

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
            created=int(time.time()),
            model=model_id,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason=data.get("stop_reason", "stop"),
                )
            ],
            usage=UsageStats(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            ),
        )

    def _transform_ollama_response(
        self,
        data: Dict[str, Any],
        model_id: str,
    ) -> ChatCompletionResponse:
        """Transform Ollama response to OpenAI format.

        Args:
            data: Raw Ollama API response data.
            model_id: Model ID to include in response.

        Returns:
            ChatCompletionResponse in OpenAI format.
        """
        message = data.get("message", {})

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model_id,
            choices=[
                ChatChoice(
                    index=0,
                    message=ChatMessage(
                        role=message.get("role", "assistant"),
                        content=message.get("content", ""),
                    ),
                    finish_reason="stop" if data.get("done") else None,
                )
            ],
            usage=UsageStats(
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            ),
        )

    def _transform_anthropic_stream_chunk(
        self,
        data: Dict[str, Any],
        response_id: str,
        created: int,
        model_id: str,
    ) -> Optional[str]:
        """Transform Anthropic streaming chunk to OpenAI format.

        Args:
            data: Raw Anthropic streaming event data.
            response_id: Response ID for the chunk.
            created: Timestamp for the response.
            model_id: Model ID to include in response.

        Returns:
            JSON string chunk in OpenAI format, or None if not applicable.
        """
        event_type = data.get("type")

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                chunk = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta.get("text", "")},
                            "finish_reason": None,
                        }
                    ],
                }
                return json.dumps(chunk)

        elif event_type == "message_stop":
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            return json.dumps(chunk)

        return None

    def _transform_ollama_stream_chunk(
        self,
        data: Dict[str, Any],
        response_id: str,
        created: int,
        model_id: str,
    ) -> Optional[str]:
        """Transform Ollama streaming chunk to OpenAI format.

        Args:
            data: Raw Ollama streaming event data.
            response_id: Response ID for the chunk.
            created: Timestamp for the response.
            model_id: Model ID to include in response.

        Returns:
            JSON string chunk in OpenAI format, or None if not applicable.
        """
        message = data.get("message", {})
        content = message.get("content", "")

        if data.get("done"):
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        else:
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content} if content else {},
                        "finish_reason": None,
                    }
                ],
            }

        return json.dumps(chunk)
