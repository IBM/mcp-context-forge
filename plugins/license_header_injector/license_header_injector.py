# -*- coding: utf-8 -*-
"""Location: ./plugins/license_header_injector/license_header_injector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

License Header Injector Plugin.

Adds a language-appropriate license header to code outputs.

Hooks: tool_post_invoke, resource_post_fetch
"""

# Future
from __future__ import annotations

# Standard
from typing import Any

# Third-Party
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

LANG_COMMENT = {
    "python": ("# ", None),
    "shell": ("# ", None),
    "bash": ("# ", None),
    "javascript": ("// ", None),
    "typescript": ("// ", None),
    "go": ("// ", None),
    "java": ("// ", None),
    "c": ("/* ", " */"),
    "cpp": ("/* ", " */"),
}


class LicenseHeaderConfig(BaseModel):
    """Configuration for the license header injector plugin.

    Attributes:
        header_template: Template for the license header.
        languages: List of supported programming languages.
        max_size_kb: Maximum file size in KB to process.
        dedupe_marker: Marker to check if header already exists.
    """

    header_template: str = "SPDX-License-Identifier: Apache-2.0"
    languages: list[str] = ["python", "javascript", "typescript", "go", "java", "c", "cpp", "shell"]
    max_size_kb: int = 512
    dedupe_marker: str = "SPDX-License-Identifier:"


def _inject_header(text: str, cfg: LicenseHeaderConfig, language: str) -> str:
    """Inject a license header into text for a given language.

    Args:
        text: The text to inject the header into.
        cfg: Configuration containing header template and settings.
        language: Programming language to determine comment style.

    Returns:
        Text with the injected license header.
    """
    if cfg.dedupe_marker in text:
        return text
    prefix, suffix = LANG_COMMENT.get(language.lower(), ("# ", None))
    header_lines = cfg.header_template.strip().splitlines()
    if suffix:
        # Block-style comments
        commented = [f"{prefix}{line}{suffix if i == len(header_lines) - 1 else ''}" for i, line in enumerate(header_lines)]
        header_block = "\n".join(commented)
    else:
        commented = [f"{prefix}{line}" for line in header_lines]
        header_block = "\n".join(commented)
    # Ensure newline separation
    if not text.startswith("\n"):
        return f"{header_block}\n\n{text}"
    return f"{header_block}\n{text}"


class LicenseHeaderInjectorPlugin(Plugin):
    """Inject a license header into textual code outputs."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the license header injector plugin.

        Args:
            config: Plugin configuration containing license header settings.
        """
        super().__init__(config)
        self._cfg = LicenseHeaderConfig(**(config.config or {}))

    def _maybe_inject(self, value: Any, context: PluginContext) -> Any:
        """Conditionally inject license header based on value type and size.

        Args:
            value: The value to potentially inject a header into.
            context: Plugin execution context containing language metadata.

        Returns:
            The value with an injected header if applicable, otherwise unchanged.
        """
        if not isinstance(value, str):
            return value
        if len(value.encode("utf-8")) > self._cfg.max_size_kb * 1024:
            return value
        language = None
        if isinstance(context.metadata, dict):
            language = context.metadata.get("language")
        language = (language or "python").lower()
        if language not in self._cfg.languages:
            return value
        return _inject_header(value, self._cfg, language)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Inject license header into tool output after invocation.

        Args:
            payload: The tool post-invoke payload containing the result.
            context: Plugin execution context.

        Returns:
            ToolPostInvokeResult with modified payload if header was injected.
        """
        new_val = self._maybe_inject(payload.result, context)
        if new_val is payload.result:
            return ToolPostInvokeResult(continue_processing=True)
        return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=new_val))

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Inject license header into resource content after fetching.

        Args:
            payload: The resource post-fetch payload containing the content.
            context: Plugin execution context.

        Returns:
            ResourcePostFetchResult with modified payload if header was injected.
        """
        content = payload.content
        if hasattr(content, "text") and isinstance(content.text, str):
            new_text = self._maybe_inject(content.text, context)
            if new_text is not content.text:
                new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(content)(**{**content.model_dump(), "text": new_text}))
                return ResourcePostFetchResult(modified_payload=new_payload)
        return ResourcePostFetchResult(continue_processing=True)
