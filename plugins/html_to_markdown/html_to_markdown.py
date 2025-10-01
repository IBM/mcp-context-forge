# -*- coding: utf-8 -*-
"""Location: ./plugins/html_to_markdown/html_to_markdown.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

HTML to Markdown Plugin.
Converts HTML resource content to Markdown, optionally preserving code blocks
and tables. Designed to run as a resource post-fetch transformer.
"""

# Future
from __future__ import annotations

# Standard
import html
import re
from typing import Any

# First-Party
from mcpgateway.models import ResourceContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
)


def _strip_tags(text: str) -> str:
    # Remove script/style blocks
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    # Replace common block elements with newlines
    text = re.sub(r"</?(p|div|section|article|br|hr|tr|table|ul|ol|li)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Headings -> Markdown
    for i in range(6, 0, -1):
        text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", lambda m: "#" * i + f" {m.group(1)}\n", text, flags=re.IGNORECASE | re.DOTALL)
    # Code/pre blocks -> fenced code
    # Allow optional whitespace between pre/code tags
    text = re.sub(
        r"<pre[^>]*>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>",
        lambda m: f"```\n{html.unescape(m.group(1))}\n```\n",
        text,
        flags=re.IGNORECASE,
    )

    # Fallback: any <pre>...</pre> to fenced code (strip inner tags)
    def _pre_fallback(m):
        inner = m.group(1)
        inner = re.sub(r"<[^>]+>", "", inner)
        return f"```\n{html.unescape(inner)}\n```\n"

    text = re.sub(r"<pre[^>]*>([\s\S]*?)</pre>", _pre_fallback, text, flags=re.IGNORECASE)
    text = re.sub(r"<code[^>]*>([\s\S]*?)</code>", lambda m: f"`{html.unescape(m.group(1)).strip()}`", text, flags=re.IGNORECASE)
    # Links -> [text](href)
    text = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", lambda m: f"[{m.group(2)}]({m.group(1)})", text, flags=re.IGNORECASE | re.DOTALL)
    # Images -> ![alt](src)
    text = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*src=\"([^\"]+)\"[^>]*>", lambda m: f"![{m.group(1)}]({m.group(2)})", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


class HTMLToMarkdownPlugin(Plugin):
    """Transform HTML ResourceContent to Markdown in `text` field."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:  # noqa: D401
        content: Any = payload.content
        if isinstance(content, ResourceContent):
            mime = (content.mime_type or "").lower()
            text = content.text or ""
            if "html" in mime or re.search(r"</?[a-zA-Z][^>]*>", text):
                md = _strip_tags(text)
                new_content = ResourceContent(type=content.type, uri=content.uri, mime_type="text/markdown", text=md, blob=None)
                return ResourcePostFetchResult(modified_payload=ResourcePostFetchPayload(uri=payload.uri, content=new_content))
        return ResourcePostFetchResult(continue_processing=True)
