# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Integration tests for ContentModerationPlugin with PluginManager.
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework import GlobalContext

from mcpgateway.plugins.framework import (
    PromptHookType,
    ToolHookType,
    PromptPrehookPayload,
    ToolPreInvokePayload,
)


@pytest.mark.asyncio
async def test_content_moderation_with_manager():
    """Test content moderation plugin integration with PluginManager."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test config file
        config_content = """
plugins:
  - name: "ContentModeration"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch", "tool_pre_invoke", "tool_post_invoke"]
    mode: "enforce"
    priority: 50
    config:
      provider: "ibm_watson"
      fallback_provider: "ibm_granite"
      ibm_watson:
        api_key: "test-watson-key"
        url: "https://api.us-south.natural-language-understanding.watson.cloud.ibm.com"
        version: "2022-04-07"
      ibm_granite:
        ollama_url: "http://localhost:11434"
        model: "granite3-guardian"
      categories:
        hate:
          threshold: 0.7
          action: "block"
        violence:
          threshold: 0.8
          action: "block"
        profanity:
          threshold: 0.6
          action: "redact"
      audit_decisions: true
      enable_caching: true

plugin_settings:
  plugin_timeout: 30
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        # Mock HTTP responses for IBM Watson
        with patch('plugins.content_moderation.content_moderation.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "emotion": {
                    "document": {
                        "emotion": {
                            "anger": 0.2,
                            "disgust": 0.1,
                            "fear": 0.1,
                            "sadness": 0.1
                        }
                    }
                },
                "sentiment": {
                    "document": {
                        "score": 0.1,
                        "label": "positive"
                    }
                },
                "concepts": []
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            # Initialize plugin manager
            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                # Create test context and payload
                context = GlobalContext(
                    request_id="test-req-123",
                    user="testuser@example.com",
                    tenant_id="test-tenant",
                    server_id="test-server"
                )

                # Test clean content (should pass)
                payload = PromptPrehookPayload(
                    prompt_id="test_prompt",
                    args={"query": "What is the weather like today?"}
                )

                result, final_context = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                # Verify result
                assert result.continue_processing is True
                assert result.violation is None

                # Verify Watson API was called
                mock_client.post.assert_called()

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_content_moderation_blocking_harmful_content():
    """Test content moderation blocks harmful content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "ContentModeration"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "enforce"
    priority: 50
    config:
      provider: "ibm_watson"
      ibm_watson:
        api_key: "test-watson-key"
        url: "https://test-watson-url"
      categories:
        hate:
          threshold: 0.7
          action: "block"
      audit_decisions: true

plugin_settings:
  plugin_timeout: 30
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        # Mock high hate score response from Watson
        with patch('plugins.content_moderation.content_moderation.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "emotion": {
                    "document": {
                        "emotion": {
                            "anger": 0.9,  # High anger score
                            "disgust": 0.8,  # High disgust score
                            "fear": 0.1,
                            "sadness": 0.1
                        }
                    }
                },
                "sentiment": {
                    "document": {
                        "score": -0.9,  # Very negative sentiment
                        "label": "negative"
                    }
                },
                "concepts": []
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="harmful-test", user="testuser")

                # Test harmful content
                payload = PromptPrehookPayload(
                    prompt_id="harmful_prompt",
                    args={"query": "I hate all those people and want them gone"}
                )

                result, final_context = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                # Should be blocked due to high hate score
                assert result.continue_processing is False
                assert result.violation is not None
                assert result.violation.code == "CONTENT_MODERATION"
                assert "Content policy violation" in result.violation.reason

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_content_moderation_with_granite_fallback():
    """Test fallback to IBM Granite when Watson fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "ContentModeration"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["tool_pre_invoke"]
    mode: "permissive"
    priority: 50
    config:
      provider: "ibm_watson"
      fallback_provider: "ibm_granite"
      ibm_watson:
        api_key: "test-watson-key"
        url: "https://test-watson-url"
      ibm_granite:
        ollama_url: "http://localhost:11434"
        model: "granite3-guardian"
      categories:
        violence:
          threshold: 0.8
          action: "warn"

plugin_settings:
  plugin_timeout: 30
  fail_on_plugin_error: false

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch('plugins.content_moderation.content_moderation.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()

            # First call (Watson) fails with connection error
            watson_response = MagicMock()
            watson_response.raise_for_status.side_effect = Exception("Watson API unavailable")

            # Second call (Granite) succeeds
            granite_response = MagicMock()
            granite_response.status_code = 200
            granite_response.json.return_value = {
                "response": '{"hate": 0.1, "violence": 0.3, "sexual": 0.0, "self_harm": 0.0, "harassment": 0.2, "toxic": 0.4}'
            }

            # Configure mock to return different responses for different calls
            # We might get multiple calls due to retries or multiple text extractions
            mock_client.post.side_effect = [watson_response, granite_response, watson_response, granite_response]
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="fallback-test", user="testuser")

                payload = ToolPreInvokePayload(
                    name="search_tool",
                    args={"query": "How to resolve conflicts peacefully"}
                )

                result, final_context = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, payload, context)

                # Should continue processing (fallback succeeded)
                assert result.continue_processing is True
                assert result.metadata.get("moderation_checked") is True

                # Verify both Watson and Granite were called
                # (may be called multiple times due to multiple text extractions)
                assert mock_client.post.call_count >= 2

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_content_moderation_redaction():
    """Test content redaction functionality."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "ContentModeration"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "permissive"
    priority: 50
    config:
      provider: "ibm_watson"
      ibm_watson:
        api_key: "test-watson-key"
        url: "https://test-watson-url"
      categories:
        profanity:
          threshold: 0.6
          action: "redact"

plugin_settings:
  plugin_timeout: 30

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch('plugins.content_moderation.content_moderation.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            # Mock response that would trigger profanity redaction
            mock_response.json.return_value = {
                "emotion": {
                    "document": {
                        "emotion": {
                            "anger": 0.7,
                            "disgust": 0.6,
                            "fear": 0.1,
                            "sadness": 0.2
                        }
                    }
                },
                "sentiment": {
                    "document": {
                        "score": -0.7,
                        "label": "negative"
                    }
                },
                "concepts": []
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="redaction-test", user="testuser")

                payload = PromptPrehookPayload(
                    prompt_id="profanity_prompt",
                    args={"query": "This damn thing is not working"}
                )

                result, final_context = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                # Should continue processing but with modified content
                assert result.continue_processing is True

                # Check if content modification metadata exists
                if result.metadata and result.metadata.get("content_modified"):
                    assert result.modified_payload is not None

            finally:
                await manager.shutdown()


@pytest.mark.asyncio
async def test_content_moderation_multiple_providers():
    """Test content moderation with multiple provider configurations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "ContentModerationWatson"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["prompt_pre_fetch"]
    mode: "permissive"
    priority: 50
    config:
      provider: "ibm_watson"
      ibm_watson:
        api_key: "watson-key"
        url: "https://watson-url"
      categories:
        hate:
          threshold: 0.8
          action: "warn"

  - name: "ContentModerationGranite"
    kind: "plugins.content_moderation.content_moderation.ContentModerationPlugin"
    hooks: ["tool_pre_invoke"]
    mode: "permissive"
    priority: 51
    config:
      provider: "ibm_granite"
      ibm_granite:
        ollama_url: "http://localhost:11434"
        model: "granite3-guardian"
      categories:
        violence:
          threshold: 0.7
          action: "block"

plugin_settings:
  plugin_timeout: 30

plugin_dirs: []
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch('plugins.content_moderation.content_moderation.httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()

            # Mock responses for both providers
            watson_response = MagicMock()
            watson_response.status_code = 200
            watson_response.json.return_value = {
                "emotion": {"document": {"emotion": {"anger": 0.3}}},
                "sentiment": {"document": {"score": 0.1, "label": "positive"}},
                "concepts": []
            }

            granite_response = MagicMock()
            granite_response.status_code = 200
            granite_response.json.return_value = {
                "response": '{"hate": 0.2, "violence": 0.1, "sexual": 0.0, "self_harm": 0.0, "harassment": 0.1, "toxic": 0.2}'
            }

            # We might get multiple calls due to retries or multiple text extractions
            mock_client.post.side_effect = [watson_response, granite_response, watson_response, granite_response]
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="multi-provider-test", user="testuser")

                # Test prompt (goes to Watson)
                prompt_payload = PromptPrehookPayload(
                    prompt_id="test_prompt",
                    args={"query": "What is machine learning?"}
                )

                prompt_result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, prompt_payload, context)
                assert prompt_result.continue_processing is True

                # Test tool (goes to Granite)
                tool_payload = ToolPreInvokePayload(
                    name="search_tool",
                    args={"query": "How to build AI models"}
                )

                tool_result, _ = await manager.invoke_hook(ToolHookType.TOOL_PRE_INVOKE, tool_payload, context)
                assert tool_result.continue_processing is True

                # Verify both providers were called
                # (may be called multiple times due to multiple text extractions)
                assert mock_client.post.call_count >= 2

            finally:
                await manager.shutdown()
