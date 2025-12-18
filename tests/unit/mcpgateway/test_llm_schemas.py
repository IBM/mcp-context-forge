# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_llm_schemas.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for LLM schemas.
"""

# Standard
from datetime import datetime, timezone

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.llm_schemas import (
    ChatCompletionRequest,
    ChatMessage,
    GatewayModelInfo,
    GatewayModelsResponse,
    HealthStatus,
    LLMModelCreate,
    LLMModelResponse,
    LLMModelUpdate,
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderTypeEnum,
    LLMProviderUpdate,
    ProviderHealthCheck,
    UsageStats,
)


class TestLLMProviderSchemas:
    """Tests for LLM provider schemas."""

    def test_provider_create_minimal(self):
        """Test creating provider with minimal fields."""
        provider = LLMProviderCreate(
            name="Test Provider",
            provider_type=LLMProviderTypeEnum.OPENAI,
        )
        assert provider.name == "Test Provider"
        assert provider.provider_type == LLMProviderTypeEnum.OPENAI
        assert provider.enabled is True
        assert provider.default_temperature == 0.7

    def test_provider_create_full(self):
        """Test creating provider with all fields."""
        provider = LLMProviderCreate(
            name="Full Provider",
            description="Test description",
            provider_type=LLMProviderTypeEnum.AZURE_OPENAI,
            api_key="test-key",
            api_base="https://api.example.com",
            api_version="2024-02-15",
            config={"custom": "value"},
            default_model="gpt-4o",
            default_temperature=0.5,
            default_max_tokens=4096,
            enabled=True,
            plugin_ids=["plugin1", "plugin2"],
        )
        assert provider.name == "Full Provider"
        assert provider.api_key == "test-key"
        assert provider.default_max_tokens == 4096

    def test_provider_create_invalid_temperature(self):
        """Test provider creation fails with invalid temperature."""
        with pytest.raises(ValidationError):
            LLMProviderCreate(
                name="Test",
                provider_type=LLMProviderTypeEnum.OPENAI,
                default_temperature=3.0,  # Invalid: max is 2.0
            )

    def test_provider_update_partial(self):
        """Test partial provider update."""
        update = LLMProviderUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.description is None
        assert update.enabled is None

    def test_provider_response_from_attributes(self):
        """Test provider response creation from attributes."""
        response = LLMProviderResponse(
            id="test-id",
            name="Test Provider",
            slug="test-provider",
            provider_type="openai",
            enabled=True,
            health_status="healthy",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            model_count=5,
        )
        assert response.id == "test-id"
        assert response.model_count == 5


class TestLLMModelSchemas:
    """Tests for LLM model schemas."""

    def test_model_create_minimal(self):
        """Test creating model with minimal fields."""
        model = LLMModelCreate(
            provider_id="provider-123",
            model_id="gpt-4o",
            model_name="GPT-4o",
        )
        assert model.provider_id == "provider-123"
        assert model.model_id == "gpt-4o"
        assert model.supports_chat is True

    def test_model_create_with_capabilities(self):
        """Test creating model with capabilities."""
        model = LLMModelCreate(
            provider_id="provider-123",
            model_id="gpt-4o",
            model_name="GPT-4o",
            supports_chat=True,
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
            context_window=128000,
            max_output_tokens=4096,
        )
        assert model.supports_function_calling is True
        assert model.supports_vision is True
        assert model.context_window == 128000

    def test_model_update_partial(self):
        """Test partial model update."""
        update = LLMModelUpdate(enabled=False)
        assert update.enabled is False
        assert update.model_name is None


class TestChatCompletionSchemas:
    """Tests for chat completion schemas."""

    def test_chat_message_user(self):
        """Test user chat message."""
        message = ChatMessage(role="user", content="Hello")
        assert message.role == "user"
        assert message.content == "Hello"

    def test_chat_message_assistant(self):
        """Test assistant chat message."""
        message = ChatMessage(role="assistant", content="Hi there!")
        assert message.role == "assistant"

    def test_chat_completion_request_minimal(self):
        """Test minimal chat completion request."""
        request = ChatCompletionRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        assert request.model == "gpt-4o"
        assert len(request.messages) == 1
        assert request.stream is False

    def test_chat_completion_request_streaming(self):
        """Test streaming chat completion request."""
        request = ChatCompletionRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
            temperature=0.5,
        )
        assert request.stream is True
        assert request.temperature == 0.5

    def test_usage_stats(self):
        """Test usage statistics."""
        usage = UsageStats(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        assert usage.total_tokens == 150


class TestGatewayModelSchemas:
    """Tests for gateway model schemas."""

    def test_gateway_model_info(self):
        """Test gateway model info."""
        model = GatewayModelInfo(
            id="model-123",
            model_id="gpt-4o",
            model_name="GPT-4o",
            provider_id="provider-456",
            provider_name="OpenAI",
            provider_type="openai",
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=True,
        )
        assert model.model_id == "gpt-4o"
        assert model.provider_name == "OpenAI"

    def test_gateway_models_response(self):
        """Test gateway models response."""
        model = GatewayModelInfo(
            id="model-123",
            model_id="gpt-4o",
            model_name="GPT-4o",
            provider_id="provider-456",
            provider_name="OpenAI",
            provider_type="openai",
        )
        response = GatewayModelsResponse(models=[model], count=1)
        assert response.count == 1
        assert len(response.models) == 1


class TestHealthCheckSchemas:
    """Tests for health check schemas."""

    def test_provider_health_check(self):
        """Test provider health check."""
        check = ProviderHealthCheck(
            provider_id="provider-123",
            provider_name="OpenAI",
            provider_type="openai",
            status=HealthStatus.HEALTHY,
            response_time_ms=150.5,
            checked_at=datetime.now(timezone.utc),
        )
        assert check.status == HealthStatus.HEALTHY
        assert check.response_time_ms == 150.5

    def test_provider_health_check_unhealthy(self):
        """Test unhealthy provider health check."""
        check = ProviderHealthCheck(
            provider_id="provider-123",
            provider_name="OpenAI",
            provider_type="openai",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
            checked_at=datetime.now(timezone.utc),
        )
        assert check.status == HealthStatus.UNHEALTHY
        assert check.error == "Connection refused"
