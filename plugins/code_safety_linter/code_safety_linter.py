# -*- coding: utf-8 -*-
"""Location: ./plugins/code_safety_linter/code_safety_linter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Code Safety Linter Plugin.
Detects risky code patterns (eval/exec/system/spawn) in tool outputs and
either blocks or annotates based on mode.
"""

from __future__ import annotations

# Standard
import re
from typing import Any, List

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)


class CodeSafetyConfig(BaseModel):
    blocked_patterns: List[str] = Field(
        default_factory=lambda: [
            r"\beval\s*\(",
            r"\bexec\s*\(",
            r"\bos\.system\s*\(",
            r"\bsubprocess\.(Popen|call|run)\s*\(",
            r"\brm\s+-rf\b",
        ]
    )


class CodeSafetyLinterPlugin(Plugin):
    """Scan text outputs for dangerous code patterns."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = CodeSafetyConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        text: str | None = None
        if isinstance(payload.result, str):
            text = payload.result
        elif isinstance(payload.result, dict) and isinstance(payload.result.get("text"), str):
            text = payload.result.get("text")
        if not text:
            return ToolPostInvokeResult(continue_processing=True)

        findings: list[str] = []
        for pat in self._cfg.blocked_patterns:
            if re.search(pat, text):
                findings.append(pat)
        if findings:
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Unsafe code pattern",
                    description="Detected unsafe code constructs",
                    code="CODE_SAFETY",
                    details={"patterns": findings},
                ),
            )
        return ToolPostInvokeResult(continue_processing=True)
