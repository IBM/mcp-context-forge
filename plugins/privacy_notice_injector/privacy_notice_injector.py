# -*- coding: utf-8 -*-
"""Location: ./plugins/privacy_notice_injector/privacy_notice_injector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Privacy Notice Injector Plugin.

Adds a configurable privacy notice to rendered prompts by modifying the first
user message (prepend/append) or by inserting a separate message when none exists.

Hook: prompt_post_fetch
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from mcpgateway.models import Message, Role, TextContent
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPosthookResult,
)


class PrivacyNoticeConfig(BaseModel):
    notice_text: str = (
        "Privacy notice: Do not include PII, secrets, or confidential information in prompts or outputs."
    )
    placement: str = "append"  # prepend | append | separate_message
    marker: str = "[PRIVACY]"  # used to dedupe


def _inject_text(existing: str, notice: str, placement: str) -> str:
    if placement == "prepend":
        return f"{notice}\n\n{existing}" if existing else notice
    if placement == "append":
        return f"{existing}\n\n{notice}" if existing else notice
    return existing


class PrivacyNoticeInjectorPlugin(Plugin):
    """Inject a privacy notice into prompt messages."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = PrivacyNoticeConfig(**(config.config or {}))

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        result = payload.result
        if not result or not result.messages:
            return PromptPosthookResult(continue_processing=True)

        notice = self._cfg.notice_text
        marker = self._cfg.marker
        # If any message already contains the marker, skip
        for m in result.messages:
            if isinstance(m.content, TextContent) and marker in m.content.text:
                return PromptPosthookResult(continue_processing=True)

        if self._cfg.placement == "separate_message":
            # Insert a dedicated user message at the end
            msg = Message(role=Role.USER, content=TextContent(type="text", text=f"{marker} {notice}"))
            new_messages = [*result.messages, msg]
            new_payload = PromptPosthookPayload(name=payload.name, result=type(result)(messages=new_messages, description=result.description))
            return PromptPosthookResult(modified_payload=new_payload)

        # Find first user message to modify
        for idx, m in enumerate(result.messages):
            if m.role == Role.USER and isinstance(m.content, TextContent):
                new_text = _inject_text(m.content.text, f"{marker} {notice}", self._cfg.placement)
                if new_text != m.content.text:
                    new_msg = Message(role=m.role, content=TextContent(type="text", text=new_text))
                    new_msgs = result.messages.copy()
                    new_msgs[idx] = new_msg
                    new_payload = PromptPosthookPayload(name=payload.name, result=type(result)(messages=new_msgs, description=result.description))
                    return PromptPosthookResult(modified_payload=new_payload)
        # If no user message, append a separate one
        msg = Message(role=Role.USER, content=TextContent(type="text", text=f"{marker} {notice}"))
        new_messages = [*result.messages, msg]
        new_payload = PromptPosthookPayload(name=payload.name, result=type(result)(messages=new_messages, description=result.description))
        return PromptPosthookResult(modified_payload=new_payload)
