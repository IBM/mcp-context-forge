# -*- coding: utf-8 -*-
"""Location: ./plugins/code_safety_linter/code_safety_linter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Code Safety Linter Plugin.
Detects risky code patterns (eval/exec/system/spawn) in tool outputs and
either blocks or annotates based on mode.
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, List, Pattern

# Third-Party
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    """Configuration for code safety linter plugin.

    Attributes:
        blocked_patterns: List of compiled regex patterns for dangerous code constructs.
    """

    blocked_patterns: List[Pattern[str]] = Field(
        default_factory=lambda: [
            re.compile(r"\beval\s*\("),
            re.compile(r"\bexec\s*\("),
            re.compile(r"\bos\.system\s*\("),
            re.compile(r"\bsubprocess\.(Popen|call|run)\s*\("),
            re.compile(r"\brm\s+-rf\b"),
        ]
    )

    @field_validator('blocked_patterns', mode='before')
    @classmethod
    def compile_patterns(cls, v: Any) -> List[Pattern[str]]:
        """Compile string patterns to regex Pattern objects.

        Args:
            v: List of regex pattern strings or Pattern objects.

        Returns:
            List of compiled Pattern objects.
        """
        if not isinstance(v, list):
            return v
        compiled = []
        for item in v:
            if isinstance(item, str):
                compiled.append(re.compile(item))
            elif isinstance(item, Pattern):
                compiled.append(item)
            else:
                compiled.append(item)
        return compiled

    model_config = ConfigDict(arbitrary_types_allowed=True)


class CodeSafetyLinterPlugin(Plugin):
    """Scan text outputs for dangerous code patterns."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the code safety linter plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CodeSafetyConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Scan tool output for dangerous code patterns.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result blocking if dangerous patterns found, or allowing.
        """
        text: str | None = None
        if isinstance(payload.result, str):
            text = payload.result
        elif isinstance(payload.result, dict) and isinstance(payload.result.get("text"), str):
            text = payload.result.get("text")
        if not text:
            return ToolPostInvokeResult(continue_processing=True)

        findings: list[str] = []
        for pat in self._cfg.blocked_patterns:
            if pat.search(text):
                findings.append(pat.pattern)
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
