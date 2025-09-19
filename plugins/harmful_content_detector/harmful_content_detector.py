# -*- coding: utf-8 -*-
"""Location: ./plugins/harmful_content_detector/harmful_content_detector.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Harmful Content Detector Plugin.

Detects categories such as self-harm, violence, and hate via keyword lexicons.

Hooks: prompt_pre_fetch, tool_post_invoke
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from pydantic import BaseModel

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
    categories: Dict[str, List[str]] = DEFAULT_LEXICONS
    block_on: List[str] = ["self_harm", "violence", "hate"]
    redact: bool = False
    redaction_text: str = "[REDACTED]"


def _scan_text(text: str, cfg: HarmfulContentConfig) -> List[Tuple[str, str]]:
    findings: List[Tuple[str, str]] = []
    t = text.lower()
    for cat, pats in cfg.categories.items():
        for pat in pats:
            if re.search(pat, t, flags=re.IGNORECASE):
                findings.append((cat, pat))
    return findings


def _iter_strings(value: Any) -> Iterable[Tuple[str, str]]:
    def walk(obj: Any, path: str):
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
    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cfg = HarmfulContentConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
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
