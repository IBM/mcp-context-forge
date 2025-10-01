# -*- coding: utf-8 -*-
"""Location: ./plugins/markdown_cleaner/markdown_cleaner.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Markdown Cleaner Plugin.
Tidies Markdown by fixing headings, list markers, code fences, and collapsing
excess blank lines. Works on prompt results and resource content.
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any

# First-Party
from mcpgateway.models import Message, PromptResult, ResourceContent, TextContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
)


def _clean_md(text: str) -> str:
    # Normalize CRLF
    text = re.sub(r"\r\n?|\u2028|\u2029", "\n", text)
    # Ensure space after heading hashes
    text = re.sub(r"^(#{1,6})(\S)", r"\1 \2", text, flags=re.MULTILINE)
    # Normalize list markers to '-'
    text = re.sub(r"^(\s*)([*•+])\s+", r"\1- ", text, flags=re.MULTILINE)
    # Ensure fenced code blocks have fences
    text = re.sub(r"```[ \t]*\n+```", "", text)  # remove empty fences
    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class MarkdownCleanerPlugin(Plugin):
    """Clean Markdown in prompts and resources."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        pr: PromptResult = payload.result
        changed = False
        new_msgs: list[Message] = []
        for m in pr.messages:
            if isinstance(m.content, TextContent) and isinstance(m.content.text, str):
                clean = _clean_md(m.content.text)
                if clean != m.content.text:
                    changed = True
                    new_msgs.append(Message(role=m.role, content=TextContent(type="text", text=clean)))
                else:
                    new_msgs.append(m)
            else:
                new_msgs.append(m)
        if changed:
            return PromptPosthookResult(modified_payload=PromptPosthookPayload(name=payload.name, result=PromptResult(messages=new_msgs)))
        return PromptPosthookResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        content: Any = payload.content
        if isinstance(content, ResourceContent) and content.text:
            clean = _clean_md(content.text)
            if clean != content.text:
                new_content = ResourceContent(type=content.type, uri=content.uri, mime_type=content.mime_type, text=clean, blob=content.blob)
                return ResourcePostFetchResult(modified_payload=ResourcePostFetchPayload(uri=payload.uri, content=new_content))
        return ResourcePostFetchResult(continue_processing=True)
