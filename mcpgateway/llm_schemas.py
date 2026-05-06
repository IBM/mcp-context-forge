# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/llm_schemas.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

LLM Settings Pydantic Schemas.
This module provides Pydantic models for LLM provider configuration, model management,
and chat completions for the internal LLM Chat feature.

The schemas support:
- LLM provider CRUD operations
- Model configuration and capabilities
- Chat completion requests/responses (OpenAI-compatible)
- Embedding requests/responses
"""

# Standard
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

# Third-Party
from pydantic import BaseModel, ConfigDict, Field, field_validator

# First-Party
from mcpgateway.common.validators import SecurityValidator, validate_core_url

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LLMProviderTypeEnum(str, Enum):
    """Enumeration of supported LLM provider types."""

    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    GOOGLE_VERTEX = "google_vertex"
    WATSONX = "watsonx"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    COHERE = "cohere"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER = "together"


class HealthStatus(str, Enum):
    """Health status values for LLM providers."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RequestStatus(str, Enum):
    """Request processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RequestType(str, Enum):
    """Types of LLM requests."""

    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"


# ---------------------------------------------------------------------------
# LLM Provider Schemas
# ---------------------------------------------------------------------------


class LLMProviderBase(BaseModel):
    """Base schema for LLM provider data."""

    name: str = Field(..., min_length=1, max_length=255, description="Display name for the provider")
    description: Optional[str] = Field(None, max_length=2000, description="Optional description")
    provider_type: LLMProviderTypeEnum = Field(..., description="Type of LLM provider")
    api_base: Optional[str] = Field(None, max_length=512, description="Base URL for API requests")
    api_version: Optional[str] = Field(None, max_length=50, description="API version (for Azure OpenAI)")
    config: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")
    default_model: Optional[str] = Field(None, max_length=255, description="Default model ID")
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Default temperature")
    default_max_tokens: Optional[int] = Field(None, ge=1, description="Default max tokens")
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    plugin_ids: List[str] = Field(default_factory=list, description="Attached plugin IDs")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        """Sanitize provider name against XSS and injection.

        Args:
            v: Raw name value.

        Returns:
            str: Validated name.
        """
        return SecurityValidator.validate_name(v, "Provider name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize provider description for safe display.

        Args:
            v: Raw description value.

        Returns:
            Optional[str]: Sanitized description.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("api_base")
    @classmethod
    def _validate_api_base(cls, v: Optional[str]) -> Optional[str]:
        """Validate provider API base URL.

        Args:
            v: Raw URL value.

        Returns:
            Optional[str]: Validated URL.
        """
        if v is None:
            return v
        return validate_core_url(v, "Provider API base URL")

    @field_validator("config")
    @classmethod
    def _validate_config(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Reject excessively nested provider config.

        Args:
            v: Config dictionary.

        Returns:
            Dict[str, Any]: Validated config.
        """
        SecurityValidator.validate_json_depth(v)
        return v

    def validate_provider_config(self) -> None:
        """Validate provider-specific configuration based on provider type.

        Raises:
            ValueError: If required provider-specific fields are missing.
        """
        # Import here to avoid circular dependency
        # First-Party
        from mcpgateway.llm_provider_configs import get_provider_config  # pylint: disable=import-outside-toplevel

        provider_def = get_provider_config(self.provider_type.value if isinstance(self.provider_type, LLMProviderTypeEnum) else self.provider_type)
        if not provider_def:
            return

        # Validate required config fields
        for field_def in provider_def.config_fields:
            if field_def.required and field_def.name not in self.config:
                raise ValueError(f"Required configuration field '{field_def.name}' missing for provider type '{self.provider_type}'")


class LLMProviderCreate(LLMProviderBase):
    """Schema for creating a new LLM provider."""

    api_key: Optional[str] = Field(None, description="API key (will be encrypted)")


class LLMProviderUpdate(BaseModel):
    """Schema for updating an LLM provider."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    provider_type: Optional[LLMProviderTypeEnum] = None
    api_key: Optional[str] = Field(None, description="API key (will be encrypted)")
    api_base: Optional[str] = Field(None, max_length=512)
    api_version: Optional[str] = Field(None, max_length=50)
    config: Optional[Dict[str, Any]] = None
    default_model: Optional[str] = Field(None, max_length=255)
    default_temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    default_max_tokens: Optional[int] = Field(None, ge=1)
    enabled: Optional[bool] = None
    plugin_ids: Optional[List[str]] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize provider name against XSS and injection.

        Args:
            v: Raw name value.

        Returns:
            Optional[str]: Validated name.
        """
        if v is None:
            return v
        return SecurityValidator.validate_name(v, "Provider name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize provider description for safe display.

        Args:
            v: Raw description value.

        Returns:
            Optional[str]: Sanitized description.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Description")

    @field_validator("api_base")
    @classmethod
    def _validate_api_base(cls, v: Optional[str]) -> Optional[str]:
        """Validate provider API base URL.

        Args:
            v: Raw URL value.

        Returns:
            Optional[str]: Validated URL.
        """
        if v is None:
            return v
        return validate_core_url(v, "Provider API base URL")

    @field_validator("config")
    @classmethod
    def _validate_config(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Reject excessively nested provider config.

        Args:
            v: Config dictionary.

        Returns:
            Optional[Dict[str, Any]]: Validated config.
        """
        if v is None:
            return v
        SecurityValidator.validate_json_depth(v)
        return v


class LLMProviderResponse(BaseModel):
    """Schema for LLM provider response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    description: Optional[str] = None
    provider_type: str
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    default_model: Optional[str] = None
    default_temperature: float = 0.7
    default_max_tokens: Optional[int] = None
    enabled: bool = True
    health_status: str = "unknown"
    last_health_check: Optional[datetime] = None
    plugin_ids: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    modified_by: Optional[str] = None
    model_count: int = Field(default=0, description="Number of models for this provider")


class LLMProviderListResponse(BaseModel):
    """Schema for paginated list of LLM providers."""

    providers: List[LLMProviderResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# LLM Model Schemas
# ---------------------------------------------------------------------------


class LLMModelBase(BaseModel):
    """Base schema for LLM model data."""

    model_id: str = Field(..., min_length=1, max_length=255, description="Provider's model ID")
    model_name: str = Field(..., min_length=1, max_length=255, description="Display name")
    model_alias: Optional[str] = Field(None, max_length=255, description="Optional routing alias")
    description: Optional[str] = Field(None, max_length=2000, description="Model description")
    supports_chat: bool = Field(default=True, description="Supports chat completions")
    supports_streaming: bool = Field(default=True, description="Supports streaming")
    supports_function_calling: bool = Field(default=False, description="Supports function/tool calling")
    supports_vision: bool = Field(default=False, description="Supports vision/images")
    context_window: Optional[int] = Field(None, ge=1, description="Max context tokens")
    max_output_tokens: Optional[int] = Field(None, ge=1, description="Max output tokens")
    enabled: bool = Field(default=True, description="Whether model is enabled")
    deprecated: bool = Field(default=False, description="Whether model is deprecated")

    @field_validator("model_id")
    @classmethod
    def _validate_model_id(cls, v: str) -> str:
        """Sanitize model ID against XSS while allowing provider punctuation.

        Provider model IDs commonly contain colons (``llama3.2:latest``),
        dots, slashes, and other punctuation.  Uses display-text sanitization
        (rejects HTML tags / script injection) rather than the strict
        tool-name pattern.

        Args:
            v: Raw model ID.

        Returns:
            str: Sanitized model ID.
        """
        return SecurityValidator.sanitize_display_text(v, "Model ID")

    @field_validator("model_name")
    @classmethod
    def _validate_model_name(cls, v: str) -> str:
        """Sanitize model display name against XSS while allowing display punctuation.

        Model names from providers may contain parentheses, colons, and
        other punctuation (e.g. ``GPT-4o (Latest)``).  Uses display-text
        sanitization rather than strict name pattern.

        Args:
            v: Raw model name.

        Returns:
            str: Sanitized name.
        """
        return SecurityValidator.sanitize_display_text(v, "Model name")

    @field_validator("model_alias")
    @classmethod
    def _validate_model_alias(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model alias against XSS and injection.

        Args:
            v: Raw alias value.

        Returns:
            Optional[str]: Validated alias.
        """
        if v is None:
            return v
        return SecurityValidator.validate_name(v, "Model alias")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model description for safe display.

        Args:
            v: Raw description value.

        Returns:
            Optional[str]: Sanitized description.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Description")


class LLMModelCreate(LLMModelBase):
    """Schema for creating a new LLM model."""

    provider_id: str = Field(..., description="Provider ID this model belongs to")


class LLMModelUpdate(BaseModel):
    """Schema for updating an LLM model."""

    model_id: Optional[str] = Field(None, min_length=1, max_length=255)
    model_name: Optional[str] = Field(None, min_length=1, max_length=255)
    model_alias: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    supports_chat: Optional[bool] = None
    supports_streaming: Optional[bool] = None
    supports_function_calling: Optional[bool] = None
    supports_vision: Optional[bool] = None
    context_window: Optional[int] = Field(None, ge=1)
    max_output_tokens: Optional[int] = Field(None, ge=1)
    enabled: Optional[bool] = None
    deprecated: Optional[bool] = None

    @field_validator("model_id")
    @classmethod
    def _validate_model_id(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model ID against XSS while allowing provider punctuation.

        Args:
            v: Raw model ID.

        Returns:
            Optional[str]: Sanitized model ID.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Model ID")

    @field_validator("model_name")
    @classmethod
    def _validate_model_name(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model display name against XSS while allowing display punctuation.

        Args:
            v: Raw model name.

        Returns:
            Optional[str]: Sanitized name.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Model name")

    @field_validator("model_alias")
    @classmethod
    def _validate_model_alias(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model alias against XSS and injection.

        Args:
            v: Raw alias value.

        Returns:
            Optional[str]: Validated alias.
        """
        if v is None:
            return v
        return SecurityValidator.validate_name(v, "Model alias")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: Optional[str]) -> Optional[str]:
        """Sanitize model description for safe display.

        Args:
            v: Raw description value.

        Returns:
            Optional[str]: Sanitized description.
        """
        if v is None:
            return v
        return SecurityValidator.sanitize_display_text(v, "Description")


class LLMModelResponse(BaseModel):
    """Schema for LLM model response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    model_id: str
    model_name: str
    model_alias: Optional[str] = None
    description: Optional[str] = None
    supports_chat: bool = True
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    enabled: bool = True
    deprecated: bool = False
    created_at: datetime
    updated_at: datetime
    provider_name: Optional[str] = Field(None, description="Provider name for display")
    provider_type: Optional[str] = Field(None, description="Provider type for display")


class LLMModelListResponse(BaseModel):
    """Schema for paginated list of LLM models."""

    models: List[LLMModelResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# Chat Completion Schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------


class FunctionDefinition(BaseModel):
    """Function definition for tool calling."""

    name: str = Field(..., description="Function name")
    description: Optional[str] = Field(None, description="Function description")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="JSON Schema for parameters")


class ToolDefinition(BaseModel):
    """Tool definition for function calling."""

    type: Literal["function"] = "function"
    function: FunctionDefinition


class ChatMessage(BaseModel):
    """A single chat message."""

    role: Literal["system", "user", "assistant", "tool"] = Field(..., description="Message role")
    content: Optional[str] = Field(None, description="Message content")
    name: Optional[str] = Field(None, description="Optional name for the participant")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="Tool calls made by assistant")
    tool_call_id: Optional[str] = Field(None, description="ID of tool call this message responds to")


class ChatCompletionRequest(BaseModel):
    """Request for chat completions (OpenAI-compatible)."""

    model: str = Field(..., description="Model ID to use")
    messages: List[ChatMessage] = Field(..., min_length=1, description="Conversation messages")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, ge=1, description="Maximum tokens to generate")
    stream: bool = Field(default=False, description="Enable streaming response")
    tools: Optional[List[ToolDefinition]] = Field(None, description="Available tools")
    tool_choice: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Tool choice preference")
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Nucleus sampling")
    frequency_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0, description="Frequency penalty")
    presence_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0, description="Presence penalty")
    stop: Optional[Union[str, List[str]]] = Field(None, description="Stop sequences")
    user: Optional[str] = Field(None, description="User identifier")


class UsageStats(BaseModel):
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatChoice(BaseModel):
    """A single chat completion choice."""

    index: int = 0
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionResponse(BaseModel):
    """Response from chat completions."""

    id: str = Field(..., description="Unique response ID")
    object: str = "chat.completion"
    created: int = Field(..., description="Unix timestamp")
    model: str = Field(..., description="Model used")
    choices: List[ChatChoice]
    usage: Optional[UsageStats] = None


class ChatCompletionChunk(BaseModel):
    """Streaming chunk for chat completions."""

    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Embedding Schemas
# ---------------------------------------------------------------------------


class EmbeddingRequest(BaseModel):
    """Request for embeddings."""

    model: str = Field(..., description="Model ID to use")
    input: Union[str, List[str]] = Field(..., description="Text to embed")
    encoding_format: Optional[Literal["float", "base64"]] = Field(None, description="Encoding format")
    user: Optional[str] = Field(None, description="User identifier")


class EmbeddingData(BaseModel):
    """A single embedding result."""

    object: str = "embedding"
    embedding: List[float]
    index: int = 0


class EmbeddingResponse(BaseModel):
    """Response from embeddings."""

    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: UsageStats


# ---------------------------------------------------------------------------
# Gateway Models Response (for LLM Chat dropdown)
# ---------------------------------------------------------------------------


class GatewayModelInfo(BaseModel):
    """Simplified model info for the LLM Chat dropdown."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique model ID")
    model_id: str = Field(..., description="Provider's model identifier")
    model_name: str = Field(..., description="Display name")
    provider_id: str = Field(..., description="Provider ID")
    provider_name: str = Field(..., description="Provider display name")
    provider_type: str = Field(..., description="Provider type")
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False


class GatewayModelsResponse(BaseModel):
    """Response for /llmchat/gateway/models endpoint."""

    models: List[GatewayModelInfo]
    count: int


# ---------------------------------------------------------------------------
# Health Check Schemas
# ---------------------------------------------------------------------------


class ProviderHealthCheck(BaseModel):
    """Result of a provider health check."""

    provider_id: str
    provider_name: str
    provider_type: str
    status: HealthStatus
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: datetime
