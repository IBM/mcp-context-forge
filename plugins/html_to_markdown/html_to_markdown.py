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
from mcpgateway.common.models import ResourceContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
)

# Precompiled regex patterns for performance
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", flags=re.IGNORECASE)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", flags=re.IGNORECASE)
_BLOCK_ELEMENTS_RE = re.compile(r"</?(p|div|section|article|br|hr|tr|table|ul|ol|li)[^>]*>", flags=re.IGNORECASE)
_HEADING_RE = [
    re.compile(rf"<h{i}[^>]*>(.*?)</h{i}>", flags=re.IGNORECASE | re.DOTALL)
    for i in range(6, 0, -1)
]
_PRE_CODE_RE = re.compile(r"<pre[^>]*>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>", flags=re.IGNORECASE)
_PRE_FALLBACK_RE = re.compile(r"<pre[^>]*>([\s\S]*?)</pre>", flags=re.IGNORECASE)
_TAG_IN_PRE_RE = re.compile(r"<[^>]+>")
_CODE_RE = re.compile(r"<code[^>]*>([\s\S]*?)</code>", flags=re.IGNORECASE)
_LINK_RE = re.compile(r"<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", flags=re.IGNORECASE | re.DOTALL)
_IMAGE_RE = re.compile(r"<img[^>]*alt=\"([^\"]*)\"[^>]*src=\"([^\"]+)\"[^>]*>", flags=re.IGNORECASE)
_REMAINING_TAGS_RE = re.compile(r"<[^>]+>")
_CRLF_RE = re.compile(r"\r\n|\r")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_HTML_TAG_DETECT_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _strip_tags(text: str) -> str:
    """Convert HTML to Markdown by stripping tags and converting common elements.

    Args:
        text: HTML text to convert.

    Returns:
        Markdown-formatted text.
    """
    # Remove script/style blocks
    text = _SCRIPT_RE.sub("", text)
    text = _STYLE_RE.sub("", text)
    # Replace common block elements with newlines
    text = _BLOCK_ELEMENTS_RE.sub("\n", text)
    # Headings -> Markdown
    for i, heading_re in enumerate(_HEADING_RE, start=1):
        heading_level = 7 - i  # Convert index to heading level (6 down to 1)
        text = heading_re.sub(lambda m: "#" * heading_level + f" {m.group(1)}\n", text)
    # Code/pre blocks -> fenced code
    # Allow optional whitespace between pre/code tags
    text = _PRE_CODE_RE.sub(
        lambda m: f"```\n{html.unescape(m.group(1))}\n```\n",
        text,
    )

    # Fallback: any <pre>...</pre> to fenced code (strip inner tags)
    def _pre_fallback(m):
        """Convert pre tag match to fenced code block.

        Args:
            m: Regex match object.

        Returns:
            Fenced code block string.
        """
        inner = m.group(1)
        inner = _TAG_IN_PRE_RE.sub("", inner)
        return f"```\n{html.unescape(inner)}\n```\n"

    text = _PRE_FALLBACK_RE.sub(_pre_fallback, text)
    text = _CODE_RE.sub(lambda m: f"`{html.unescape(m.group(1)).strip()}`", text)
    # Links -> [text](href)
    text = _LINK_RE.sub(lambda m: f"[{m.group(2)}]({m.group(1)})", text)
    # Images -> ![alt](src)
    text = _IMAGE_RE.sub(lambda m: f"![{m.group(1)}]({m.group(2)})", text)
    # Remove remaining tags
    text = _REMAINING_TAGS_RE.sub("", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = _CRLF_RE.sub("\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


class HTMLToMarkdownPlugin(Plugin):
    """Transform HTML ResourceContent to Markdown in `text` field."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the HTML to Markdown plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Convert HTML resource content to Markdown.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with Markdown content if applicable.
        """
        content: Any = payload.content
        if isinstance(content, ResourceContent):
            mime = (content.mime_type or "").lower()
            text = content.text or ""
            if "html" in mime or _HTML_TAG_DETECT_RE.search(text):
                md = _strip_tags(text)
                new_content = ResourceContent(type=content.type, id=content.id, uri=content.uri, mime_type="text/markdown", text=md, blob=None)
                return ResourcePostFetchResult(modified_payload=ResourcePostFetchPayload(uri=payload.uri, content=new_content))
        return ResourcePostFetchResult(continue_processing=True)
