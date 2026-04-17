# -*- coding: utf-8 -*-
"""Integration tests for ContentModerationPlugin with PluginManager.

Migrated from tests/unit/mcpgateway/plugins/plugins/content_moderation/test_content_moderation_integration.py
SPDX-License-Identifier: Apache-2.0
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcpgateway.plugins.framework.manager import PluginManager
from mcpgateway.plugins.framework import (
    GlobalContext,
    PromptHookType,
    ToolHookType,
    PromptPrehookPayload,
    ToolPreInvokePayload,
)


@pytest.mark.asyncio
async def test_content_moderation_with_manager():
    """Test content moderation plugin integration with PluginManager."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_content = """
plugins:
  - name: "ContentModeration"
    kind: "cpex_content_moderation.ContentModerationPlugin"
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

        with patch("cpex_content_moderation.content_moderation.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "emotion": {"document": {"emotion": {"anger": 0.2, "disgust": 0.1, "fear": 0.1, "sadness": 0.1}}},
                "sentiment": {"document": {"score": 0.1, "label": "positive"}},
                "concepts": [],
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="test-req-123", user="testuser@example.com", tenant_id="test-tenant", server_id="test-server")

                payload = PromptPrehookPayload(prompt_id="test_prompt", args={"query": "What is the weather like today?"})
                result, final_context = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                assert result.continue_processing is True
                assert result.violation is None
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
    kind: "cpex_content_moderation.ContentModerationPlugin"
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
"""
        config_path = Path(tmp_dir) / "test_config.yaml"
        config_path.write_text(config_content)

        with patch("cpex_content_moderation.content_moderation.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "emotion": {"document": {"emotion": {"anger": 0.9, "disgust": 0.8, "fear": 0.1, "sadness": 0.1}}},
                "sentiment": {"document": {"score": -0.9, "label": "negative"}},
                "concepts": [],
            }
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            manager = PluginManager(str(config_path), timeout=30)
            await manager.initialize()

            try:
                context = GlobalContext(request_id="test-req-456", user="testuser@example.com", tenant_id="test-tenant", server_id="test-server")

                payload = PromptPrehookPayload(prompt_id="harmful_prompt", args={"query": "I hate all those people"})
                result, _ = await manager.invoke_hook(PromptHookType.PROMPT_PRE_FETCH, payload, context)

                assert result.continue_processing is False
                assert result.violation is not None
                assert result.violation.code == "CONTENT_MODERATION"
            finally:
                await manager.shutdown()
