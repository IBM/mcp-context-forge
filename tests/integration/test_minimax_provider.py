# -*- coding: utf-8 -*-
"""Integration tests for MiniMax LLM provider support.

These tests verify the end-to-end MiniMax provider integration by
exercising the provider configuration, schema validation, and proxy
request building in combination. They use mocked HTTP responses to
simulate MiniMax API interactions without requiring a live API key.
"""

# Standard
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.db import LLMProviderType
from mcpgateway.llm_provider_configs import get_provider_config
from mcpgateway.llm_schemas import (
    ChatCompletionRequest,
    ChatMessage,
    LLMModelCreate,
    LLMProviderCreate,
    LLMProviderTypeEnum,
)
from mcpgateway.services.llm_proxy_service import LLMProxyService


def _make_minimax_provider(**overrides):
    data = {
        "id": "p-minimax-int",
        "name": "MiniMax-Integration",
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
        "id": "m-minimax-int",
        "model_id": "MiniMax-M2.7",
        "model_alias": None,
        "enabled": True,
        "provider_id": "p-minimax-int",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestMiniMaxProviderIntegration:
    """Integration tests verifying MiniMax provider config + schema + proxy work together."""

    def test_provider_config_matches_db_defaults(self):
        """Provider config and DB defaults must agree on API base and key requirement."""
        config = get_provider_config("minimax")
        defaults = LLMProviderType.get_provider_defaults()[LLMProviderType.MINIMAX]

        assert config.api_base_default == defaults["api_base"]
        assert config.requires_api_key == defaults["requires_api_key"]

    def test_schema_create_with_config_defaults(self):
        """Creating a provider from config defaults should pass schema validation."""
        config = get_provider_config("minimax")
        defaults = LLMProviderType.get_provider_defaults()[LLMProviderType.MINIMAX]

        provider = LLMProviderCreate(
            name="MiniMax",
            provider_type=LLMProviderTypeEnum.MINIMAX,
            api_base=config.api_base_default,
            default_model=defaults["default_model"],
        )
        provider.validate_provider_config()

        assert provider.api_base == "https://api.minimax.io/v1"
        assert provider.default_model == "MiniMax-M2.7"

    @pytest.mark.asyncio
    async def test_end_to_end_chat_completion(self):
        """Full chat completion flow: resolve model -> build request -> parse response."""
        service = LLMProxyService()
        provider = _make_minimax_provider()
        model = _make_minimax_model()
        service._resolve_model = MagicMock(return_value=(provider, model))

        request = ChatCompletionRequest(
            model="MiniMax-M2.7",
            messages=[
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="What is 2+2?"),
            ],
            temperature=0.5,
            max_tokens=100,
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "chatcmpl-minimax-int-1",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "MiniMax-M2.7",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "2+2 equals 4."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
        }

        service._client = AsyncMock()
        service._client.post = AsyncMock(return_value=mock_response)

        result = await service.chat_completion(MagicMock(), request)

        assert result.id == "chatcmpl-minimax-int-1"
        assert result.model == "MiniMax-M2.7"
        assert result.choices[0].message.content == "2+2 equals 4."
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 20
        assert result.usage.completion_tokens == 8

        # Verify the request was sent to the correct URL
        call_args = service._client.post.call_args
        assert call_args[0][0] == "https://api.minimax.io/v1/chat/completions"
        sent_body = call_args[1]["json"]
        assert sent_body["model"] == "MiniMax-M2.7"
        assert sent_body["temperature"] == 0.5
        assert sent_body["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_minimax_m27_highspeed_model(self):
        """MiniMax-M2.7-highspeed model should work the same way."""
        service = LLMProxyService()
        provider = _make_minimax_provider()
        model = _make_minimax_model(model_id="MiniMax-M2.7-highspeed")
        service._resolve_model = MagicMock(return_value=(provider, model))

        request = ChatCompletionRequest(
            model="MiniMax-M2.7-highspeed",
            messages=[ChatMessage(role="user", content="Hi")],
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "chatcmpl-hs-1",
            "created": 1,
            "model": "MiniMax-M2.7-highspeed",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
        }

        service._client = AsyncMock()
        service._client.post = AsyncMock(return_value=mock_response)

        result = await service.chat_completion(MagicMock(), request)

        assert result.model == "MiniMax-M2.7-highspeed"
        sent_body = service._client.post.call_args[1]["json"]
        assert sent_body["model"] == "MiniMax-M2.7-highspeed"

    def test_minimax_all_models_creatable(self):
        """All known MiniMax models should be creatable as LLMModelCreate."""
        models = [
            ("MiniMax-M2.7", "MiniMax M2.7", 1000000),
            ("MiniMax-M2.7-highspeed", "MiniMax M2.7 Highspeed", 1000000),
            ("MiniMax-M2.5", "MiniMax M2.5", 204800),
            ("MiniMax-M2.5-highspeed", "MiniMax M2.5 Highspeed", 204800),
        ]
        for model_id, model_name, context_window in models:
            model = LLMModelCreate(
                provider_id="minimax-provider",
                model_id=model_id,
                model_name=model_name,
                supports_chat=True,
                supports_streaming=True,
                supports_function_calling=True,
                context_window=context_window,
            )
            assert model.model_id == model_id
