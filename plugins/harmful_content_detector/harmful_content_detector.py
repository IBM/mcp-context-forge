# -*- coding: utf-8 -*-
"""Location: ./plugins/harmful_content_detector/harmful_content_detector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Harmful Content Detector Plugin.

Detects categories such as self-harm, violence, and hate via keyword lexicons.

Hooks: prompt_pre_fetch, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import re
from typing import Any, Dict, Iterable, List, Pattern, Tuple

# Third-Party
from pydantic import BaseModel, ConfigDict

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

DEFAULT_LEXICONS: Dict[str, List[str]] = {
    "self_harm": [
        r"\bkill myself\b",
        r"\bsuicide\b",
        r"\bself-harm\b",
        r"\bwant to die\b",
    ],
    "violence": [
        r"\bkill (?:him|her|them|someone)\b",
        r"\bshoot (?:him|her|them|someone)\b",
        r"\bstab (?:him|her|them|someone)\b",
    ],
    "hate": [
        r"\b(?:kill|eradicate) (?:[a-z]+) people\b",
        r"\b(?:racial slur|hate speech)\b",
    ],
}


class HarmfulContentConfig(BaseModel):
    """Configuration for the harmful content detector plugin.

    Attributes:
        categories: Dictionary mapping category names to compiled regex patterns.
        block_on: List of categories that should trigger blocking.
        redact: Whether to redact harmful content.
        redaction_text: Text to use for redaction.
    """

    categories: Dict[str, List[Pattern[str]]] = {}
    block_on: List[str] = ["self_harm", "violence", "hate"]
    redact: bool = False
    redaction_text: str = "[REDACTED]"

    def __init__(self, **data):
        """Initialize and precompile regex patterns."""
        # Convert string patterns to compiled patterns if needed
        if "categories" in data:
            compiled_cats = {}
            for cat, patterns in data["categories"].items():
                compiled_cats[cat] = [
                    re.compile(p, re.IGNORECASE) if isinstance(p, str) else p
                    for p in patterns
                ]
            data["categories"] = compiled_cats
        else:
            # Use default lexicons and compile them
            data["categories"] = {
                cat: [re.compile(p, re.IGNORECASE) for p in patterns]
                for cat, patterns in DEFAULT_LEXICONS.items()
            }
        super().__init__(**data)

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _scan_text(text: str, cfg: HarmfulContentConfig) -> List[Tuple[str, str]]:
    """Scan text for harmful content patterns.

    Args:
        text: The text to scan.
        cfg: Configuration containing category patterns.

    Returns:
        List of tuples containing (category, matched_pattern) for each finding.
    """
    findings: List[Tuple[str, str]] = []
    for cat, compiled_patterns in cfg.categories.items():
        for pat in compiled_patterns:
            if pat.search(text):
                findings.append((cat, pat.pattern))
    return findings


def _iter_strings(value: Any) -> Iterable[Tuple[str, str]]:
    """Recursively extract all strings from a nested data structure.

    Args:
        value: The value to extract strings from (can be dict, list, str, or other).

    Yields:
        Tuples of (path, string_value) for each string found in the structure.
    """

    def walk(obj: Any, path: str):
        """Recursively walk the data structure.

        Args:
            obj: The object to walk.
            path: The current path in dot notation.

        Yields:
            Tuples of (path, string_value).
        """
        if isinstance(obj, str):
            yield path, obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from walk(v, f"{path}[{i}]")

    yield from walk(value, "")


class HarmfulContentDetectorPlugin(Plugin):
    """Detects harmful content in prompts and tool outputs using keyword lexicons.

    This plugin scans for self-harm, violence, and hate categories.
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the harmful content detector plugin.

        Args:
            config: Plugin configuration containing harmful content detection settings.
        """
        super().__init__(config)
        self._cfg = HarmfulContentConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Scan prompt arguments for harmful content before fetching.

        Args:
            payload: The prompt pre-fetch payload containing arguments.
            context: Plugin execution context.

        Returns:
            PromptPrehookResult indicating whether to continue or block due to harmful content.
        """
        findings: List[Tuple[str, str]] = []
        for _, s in _iter_strings(payload.args or {}):
            findings.extend(_scan_text(s, self._cfg))
        cats = sorted(set([c for c, _ in findings]))
        if any(c in self._cfg.block_on for c in cats):
            return PromptPrehookResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Harmful content",
                    description=f"Detected categories: {', '.join(cats)}",
                    code="HARMFUL_CONTENT",
                    details={"categories": cats, "findings": findings[:5]},
                ),
            )
        return PromptPrehookResult(metadata={"harmful_categories": cats} if cats else {})

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Scan tool output for harmful content after invocation.

        Args:
            payload: The tool post-invoke payload containing the result.
            context: Plugin execution context.

        Returns:
            ToolPostInvokeResult indicating whether to continue or block due to harmful content.
        """
        text = payload.result
        if isinstance(text, dict) or isinstance(text, list):
            findings: List[Tuple[str, str]] = []
            for _, s in _iter_strings(text):
                findings.extend(_scan_text(s, self._cfg))
        elif isinstance(text, str):
            findings = _scan_text(text, self._cfg)
        else:
            findings = []
        cats = sorted(set([c for c, _ in findings]))
        if any(c in self._cfg.block_on for c in cats):
            return ToolPostInvokeResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Harmful content",
                    description=f"Detected categories: {', '.join(cats)}",
                    code="HARMFUL_CONTENT",
                    details={"categories": cats, "findings": findings[:5]},
                ),
            )
        return ToolPostInvokeResult(metadata={"harmful_categories": cats} if cats else {})
