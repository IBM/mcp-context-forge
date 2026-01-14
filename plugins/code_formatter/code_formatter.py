# -*- coding: utf-8 -*-
"""Location: ./plugins/code_formatter/code_formatter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Code Formatter Plugin.

Formats code/text outputs with lightweight, dependency-free normalization:
- Trim trailing whitespace
- Normalize indentation (spaces per tab)
- Ensure single trailing newline
- Optional JSON pretty-printing
- Optional Markdown code fence cleanup

Hooks: tool_post_invoke, resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
from textwrap import dedent
from typing import Any, Optional

# Third-Party
import orjson
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)


class CodeFormatterConfig(BaseModel):
    """Configuration for code formatting.

    Attributes:
        languages: List of supported language identifiers.
        tab_width: Number of spaces per tab character.
        trim_trailing: Whether to trim trailing whitespace.
        ensure_newline: Whether to ensure single trailing newline.
        dedent_code: Whether to dedent code blocks.
        format_json: Whether to pretty-print JSON.
        format_code_fences: Whether to format Markdown code fences.
        max_size_kb: Maximum file size in KB to format.
    """

    languages: list[str] = [
        "plaintext",
        "python",
        "javascript",
        "typescript",
        "json",
        "markdown",
        "shell",
    ]
    tab_width: int = 4
    trim_trailing: bool = True
    ensure_newline: bool = True
    dedent_code: bool = True
    format_json: bool = True
    format_code_fences: bool = True
    max_size_kb: int = 1024


def _normalize_text(text: str, cfg: CodeFormatterConfig) -> str:
    """Normalize text formatting according to configuration.

    Args:
        text: Text content to normalize.
        cfg: Code formatter configuration.

    Returns:
        Normalized text.
    """
    # Optionally dedent
    if cfg.dedent_code:
        text = dedent(text)
    # Normalize tabs to spaces
    if cfg.tab_width > 0:
        text = text.replace("\t", " " * cfg.tab_width)
    # Trim trailing spaces
    if cfg.trim_trailing:
        text = "\n".join([line.rstrip() for line in text.splitlines()])
    # Ensure single trailing newline
    if cfg.ensure_newline:
        if not text.endswith("\n"):
            text = text + "\n"
        # collapse to single
        while text.endswith("\n\n"):
            text = text[:-1]
    return text


def _try_format_json(text: str) -> Optional[str]:
    """Attempt to parse and pretty-print JSON.

    Args:
        text: Text content that may be JSON.

    Returns:
        Pretty-printed JSON string or None if parsing fails.
    """
    try:
        obj = orjson.loads(text)
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode() + "\n"
    except Exception:
        return None


def _format_by_language(result: Any, cfg: CodeFormatterConfig, language: str | None = None) -> Any:
    """Format content based on language and configuration.

    Args:
        result: Content to format.
        cfg: Code formatter configuration.
        language: Optional language identifier.

    Returns:
        Formatted content or original if not applicable.
    """
    if not isinstance(result, str):
        return result
    # Size guard
    if len(result.encode("utf-8")) > cfg.max_size_kb * 1024:
        return result

    lang = (language or "plaintext").lower()
    text = result
    if lang == "json" and cfg.format_json:
        pretty = _try_format_json(text)
        if pretty is not None:
            return pretty
    # Generic normalization
    return _normalize_text(text, cfg)


class CodeFormatterPlugin(Plugin):
    """Lightweight formatter for post-invoke and resource content."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the code formatter plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CodeFormatterConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Format tool result after invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with formatted content if applicable.
        """
        value = payload.result
        # Heuristics: allow explicit language hint via metadata or args
        language = None
        if isinstance(context.metadata, dict):
            language = context.metadata.get("language")
        # Apply formatting if applicable
        formatted = _format_by_language(value, self._cfg, language)
        if formatted is value:
            return ToolPostInvokeResult(continue_processing=True)
        return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=formatted))

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Format resource content after fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with formatted content if applicable.
        """
        content = payload.content
        # Only format textual resource content
        language = None
        meta = context.metadata if isinstance(context.metadata, dict) else {}
        language = meta.get("language")
        if hasattr(content, "text") and isinstance(content.text, str):
            new_text = _format_by_language(content.text, self._cfg, language)
            if new_text is not content.text:
                new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(content)(**{**content.model_dump(), "text": new_text}))
                return ResourcePostFetchResult(modified_payload=new_payload)
        return ResourcePostFetchResult(continue_processing=True)
