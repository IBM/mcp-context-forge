# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/markdown_cleaner/test_markdown_cleaner.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for MarkdownCleanerPlugin.
"""

import pytest

from mcpgateway.common.models import Message, PromptResult, TextContent
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptHookType,
    PromptPosthookPayload,
)
from plugins.markdown_cleaner.markdown_cleaner import MarkdownCleanerPlugin


@pytest.mark.asyncio
async def test_cleans_markdown_prompt():
    plugin = MarkdownCleanerPlugin(
        PluginConfig(
            name="mdclean",
            kind="plugins.markdown_cleaner.markdown_cleaner.MarkdownCleanerPlugin",
            hooks=[PromptHookType.PROMPT_POST_FETCH],
        )
    )
    txt = "#Heading\n\n\n* item\n\n```\n\n```\n"
    pr = PromptResult(messages=[Message(role="assistant", content=TextContent(type="text", text=txt))])
    payload = PromptPosthookPayload(prompt_id="p", result=pr)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.prompt_post_fetch(payload, ctx)
    assert res.modified_payload is not None
    out = res.modified_payload.result.messages[0].content.text
    assert out.startswith("# Heading")
    assert "\n\n\n" not in out
