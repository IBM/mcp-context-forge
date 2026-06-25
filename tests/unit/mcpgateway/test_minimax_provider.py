# -*- coding: utf-8 -*-
"""Unit tests for MiniMax LLM provider support."""

# Standard
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_provider_configs import get_all_provider_configs, get_provider_config
from mcpgateway.llm_schemas import (
    ChatCompletionRequest,
    ChatMessage,
    LLMModelCreate,
    LLMProviderCreate,
    LLMProviderTypeEnum,
)
from mcpgateway.services.llm_proxy_service import LLMProxyService


# ---------------------------------------------------------------------------
# Enum and config registry tests
# ---------------------------------------------------------------------------


class TestMiniMaxEnumRegistration:
    """Verify MiniMax is registered in all provider enums and registries."""

    def test_minimax_in_provider_type_enum(self):
        """MiniMax must be a valid LLMProviderTypeEnum value."""
        assert LLMProviderTypeEnum.MINIMAX == "minimax"

    def test_minimax_in_db_provider_type(self):
        """MiniMax must be a valid LLMProviderType constant."""
        assert LLMProviderType.MINIMAX == "minimax"

    def test_minimax_in_get_all_types(self):
        """MiniMax must be included in LLMProviderType.get_all_types()."""
        all_types = LLMProviderType.get_all_types()
        assert "minimax" in all_types

    def test_minimax_in_provider_defaults(self):
        """MiniMax must have default configuration in get_provider_defaults()."""
        defaults = LLMProviderType.get_provider_defaults()
        assert LLMProviderType.MINIMAX in defaults
        minimax_defaults = defaults[LLMProviderType.MINIMAX]
        assert minimax_defaults["api_base"] == "https://api.minimax.io/v1"
        assert minimax_defaults["default_model"] == "MiniMax-M2.7"
        assert minimax_defaults["supports_model_list"] is True
        assert minimax_defaults["requires_api_key"] is True


class TestMiniMaxProviderConfig:
    """Verify MiniMax provider configuration definition."""

    def test_minimax_config_exists(self):
        """MiniMax config must exist in provider configs."""
        config = get_provider_config("minimax")
        assert config is not None

    def test_minimax_config_display_name(self):
        """MiniMax display name must be correct."""
        config = get_provider_config("minimax")
        assert config.display_name == "MiniMax"

    def test_minimax_config_requires_api_key(self):
        """MiniMax must require an API key."""
        config = get_provider_config("minimax")
        assert config.requires_api_key is True

    def test_minimax_config_api_base_default(self):
        """MiniMax default API base must point to api.minimax.io."""
        config = get_provider_config("minimax")
        assert config.api_base_default == "https://api.minimax.io/v1"

    def test_minimax_in_all_configs(self):
        """MiniMax must be in get_all_provider_configs()."""
        all_configs = get_all_provider_configs()
        assert "minimax" in all_configs

    def test_minimax_config_no_extra_fields(self):
        """MiniMax should have no extra config fields (uses OpenAI-compat API)."""
        config = get_provider_config("minimax")
        assert config.config_fields == []


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestMiniMaxSchemas:
    """Verify MiniMax works with LLM provider schemas."""

    def test_create_minimax_provider(self):
        """Creating a MiniMax provider with LLMProviderCreate should succeed."""
        provider = LLMProviderCreate(
            name="MiniMax-Provider",
            provider_type=LLMProviderTypeEnum.MINIMAX,
            api_key="test-minimax-key",
            api_base="https://api.minimax.io/v1",
        )
        assert provider.provider_type == LLMProviderTypeEnum.MINIMAX
        assert provider.api_key == "test-minimax-key"

    def test_create_minimax_provider_minimal(self):
        """Creating a MiniMax provider with minimal fields should succeed."""
        provider = LLMProviderCreate(
            name="MiniMax",
            provider_type=LLMProviderTypeEnum.MINIMAX,
        )
        assert provider.provider_type == LLMProviderTypeEnum.MINIMAX
        assert provider.enabled is True

    def test_create_minimax_model(self):
        """Creating a MiniMax model should succeed."""
        model = LLMModelCreate(
            provider_id="minimax-provider-id",
            model_id="MiniMax-M2.7",
            model_name="MiniMax M2.7",
            supports_chat=True,
            supports_streaming=True,
            supports_function_calling=True,
            context_window=1000000,
        )
        assert model.model_id == "MiniMax-M2.7"
        assert model.context_window == 1000000

    def test_validate_minimax_provider_config(self):
        """MiniMax provider config validation should pass (no required fields)."""
        provider = LLMProviderCreate(
            name="MiniMax",
            provider_type=LLMProviderTypeEnum.MINIMAX,
        )
        # Should not raise
        provider.validate_provider_config()


# ---------------------------------------------------------------------------
# Proxy service tests
# ---------------------------------------------------------------------------


def _make_minimax_provider(**overrides):
    data = {
        "id": "p-minimax",
        "name": "MiniMax",
        "provider_type": LLMProviderType.MINIMAX,
        "enabled": True,
        "api_key": None,
        "api_base": "https://api.minimax.io/v1",
        "default_temperature": 0.7,
        "default_max_tokens": 4096,
        "config": {},
        "api_version": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _make_minimax_model(**overrides):
    data = {
        "id": "m-minimax",
        "model_id": "MiniMax-M2.7",
        "model_alias": None,
        "enabled": True,
        "provider_id": "p-minimax",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestMiniMaxProxyRouting:
    """Verify MiniMax routes through OpenAI-compatible request builder."""

    def test_build_openai_request_for_minimax(self):
        """MiniMax should use the OpenAI-compatible request builder."""
        service = LLMProxyService()
        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        provider = _make_minimax_provider()
        model = _make_minimax_model()

        url, headers, body = service._build_openai_request(request, provider, model)

        assert url == "https://api.minimax.io/v1/chat/completions"
        assert headers["Content-Type"] == "application/json"
        assert body["model"] == "MiniMax-M2.7"
        assert body["messages"][0]["content"] == "Hello"

    def test_minimax_request_includes_temperature(self):
        """MiniMax request should include temperature from provider defaults."""
        service = LLMProxyService()
        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="Hi")],
        )
        provider = _make_minimax_provider(default_temperature=0.9)
        model = _make_minimax_model()

        _, _, body = service._build_openai_request(request, provider, model)

        assert body["temperature"] == 0.9

    def test_minimax_request_explicit_temperature_overrides(self):
        """Explicit request temperature should override provider default."""
        service = LLMProxyService()
        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="Hi")],
            temperature=0.3,
        )
        provider = _make_minimax_provider(default_temperature=0.9)
        model = _make_minimax_model()

        _, _, body = service._build_openai_request(request, provider, model)

        assert body["temperature"] == 0.3

    def test_minimax_streaming_request(self):
        """MiniMax streaming should set stream=True in body."""
        service = LLMProxyService()
        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=True,
        )
        provider = _make_minimax_provider()
        model = _make_minimax_model()

        _, _, body = service._build_openai_request(request, provider, model)

        assert body["stream"] is True

    def test_minimax_with_tools(self):
        """MiniMax request with tools should include them in body."""
        from mcpgateway.llm_schemas import FunctionDefinition, ToolDefinition

        service = LLMProxyService()
        tool = ToolDefinition(
            function=FunctionDefinition(name="get_weather", parameters={"type": "object"}),
        )
        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="What is the weather?")],
            tools=[tool],
            tool_choice="auto",
        )
        provider = _make_minimax_provider()
        model = _make_minimax_model()

        _, _, body = service._build_openai_request(request, provider, model)

        assert body["tools"] is not None
        assert body["tool_choice"] == "auto"

    @pytest.mark.asyncio
    async def test_chat_completion_minimax_routes_to_openai(self):
        """MiniMax chat completion should route through OpenAI-compat path."""
        service = LLMProxyService()
        provider = _make_minimax_provider()
        model = _make_minimax_model()
        service._resolve_model = MagicMock(return_value=(provider, model))

        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[ChatMessage(role="user", content="Hi")],
        )

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            "id": "chatcmpl-minimax-1",
            "created": 1,
            "model": "MiniMax-M2.7",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }

        service._client = AsyncMock()
        service._client.post = AsyncMock(return_value=response)

        result = await service.chat_completion(MagicMock(), request)

        assert result.model == "MiniMax-M2.7"
        assert result.choices[0].message.content == "Hello!"
        assert result.usage.total_tokens == 8


# ---------------------------------------------------------------------------
# Provider service tests
# ---------------------------------------------------------------------------


class TestMiniMaxProviderService:
    """Verify MiniMax works with the provider service layer."""

    def test_create_minimax_provider_service(self):
        """Creating a MiniMax provider through the service should succeed."""
        from mcpgateway.services.llm_provider_service import LLMProviderService

        service = LLMProviderService()
        db = MagicMock()

        # Mock no existing provider with same name
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        provider_data = LLMProviderCreate(
            name="MiniMax",
            provider_type=LLMProviderTypeEnum.MINIMAX,
            api_key="test-key",
            api_base="https://api.minimax.io/v1",
        )

        from unittest.mock import patch

        with patch("mcpgateway.services.llm_provider_service.encode_auth", return_value="encoded"):
            provider = service.create_provider(db, provider_data, created_by="test-user")

        assert provider.name == "MiniMax"
        assert provider.provider_type == "minimax"
        assert provider.api_key == "encoded"
        db.add.assert_called_once()
        db.commit.assert_called_once()
