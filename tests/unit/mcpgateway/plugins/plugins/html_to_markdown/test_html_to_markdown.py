# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/plugins/html_to_markdown/test_html_to_markdown.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for HTMLToMarkdownPlugin.
"""

import pytest

from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ResourceHookType,
    ResourcePostFetchPayload,
)
from mcpgateway.common.models import ResourceContent
from plugins.html_to_markdown.html_to_markdown import HTMLToMarkdownPlugin


@pytest.mark.asyncio
async def test_html_to_markdown_transforms_basic_html():
    plugin = HTMLToMarkdownPlugin(
        PluginConfig(
            name="html2md",
            kind="plugins.html_to_markdown.html_to_markdown.HTMLToMarkdownPlugin",
            hooks=[ResourceHookType.RESOURCE_POST_FETCH],
        )
    )
    html = "<h1>Title</h1><p>Hello <a href=\"https://x\">link</a></p><pre><code>print('x')</code></pre>"
    content = ResourceContent(type="resource", id="123",uri="http://ex", mime_type="text/html", text=html)
    payload = ResourcePostFetchPayload(uri=content.uri, content=content)
    ctx = PluginContext(global_context=GlobalContext(request_id="r1"))
    res = await plugin.resource_post_fetch(payload, ctx)
    assert res.modified_payload is not None
    out = res.modified_payload.content
    assert isinstance(out, ResourceContent)
    assert out.mime_type == "text/markdown"
    assert "# Title" in out.text
    assert "[link](https://x)" in out.text
    assert ("```" in out.text) or ("`print('x')`" in out.text)
