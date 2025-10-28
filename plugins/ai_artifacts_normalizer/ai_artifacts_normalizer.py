# -*- coding: utf-8 -*-
"""AI Artifacts Normalizer Plugin.

Replaces common AI output artifacts: smart quotes → ASCII, ligatures → letters,
en/em dashes → '-', ellipsis → '...', removes bidi controls and zero-width chars,
and normalizes excessive spacing.

Hooks: prompt_pre_fetch, resource_post_fetch, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import re

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
)

SMART_MAP = {
    """: '"',
    """: '"',
    "„": '"',
    '"': '"',
    "'": "'",
    "‚": "'",
    "—": "-",
    "–": "-",
    "−": "-",
    "…": "...",
    "•": "-",
    "·": "-",
    " ": " ",  # nbsp to space
}

LIGATURE_MAP = {
    "fi": "fi",
    "fl": "fl",
    "ffi": "ffi",
    "ffl": "ffl",
    "ff": "ff",
}

BIDI_AND_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069]")

SPACING_RE = re.compile(r"[ \t\x0b\x0c]+")


class AINormalizerConfig(BaseModel):
    """Configuration for AI artifacts normalizer plugin.

    Attributes:
        replace_smart_quotes: Replace smart quotes with ASCII equivalents.
        replace_ligatures: Replace ligatures with separate letters.
        remove_bidi_controls: Remove bidirectional and zero-width control characters.
        collapse_spacing: Collapse excessive horizontal whitespace.
        normalize_dashes: Replace en/em dashes with ASCII hyphens.
        normalize_ellipsis: Replace ellipsis character with three dots.
    """

    replace_smart_quotes: bool = True
    replace_ligatures: bool = True
    remove_bidi_controls: bool = True
    collapse_spacing: bool = True
    normalize_dashes: bool = True
    normalize_ellipsis: bool = True


def _normalize_text(text: str, cfg: AINormalizerConfig) -> str:
    """Normalize text by removing AI-generated artifacts.

    Args:
        text: Input text to normalize.
        cfg: Configuration specifying which normalizations to apply.

    Returns:
        Normalized text with AI artifacts removed or replaced.
    """
    out = text
    if cfg.replace_smart_quotes or cfg.normalize_dashes or cfg.normalize_ellipsis:
        for k, v in SMART_MAP.items():
            out = out.replace(k, v)
    if cfg.replace_ligatures:
        for k, v in LIGATURE_MAP.items():
            out = out.replace(k, v)
    if cfg.remove_bidi_controls:
        out = BIDI_AND_ZERO_WIDTH.sub("", out)
    if cfg.collapse_spacing:
        # Collapse horizontal whitespace, preserve newlines
        out = "\n".join(SPACING_RE.sub(" ", line).rstrip() for line in out.splitlines())
    return out


class AIArtifactsNormalizerPlugin(Plugin):
    """Plugin to normalize AI-generated text artifacts in prompts, resources, and tool results."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the AI artifacts normalizer plugin.

        Args:
            config: Plugin configuration including normalization settings.
        """
        super().__init__(config)
        self._cfg = AINormalizerConfig(**(config.config or {}))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Normalize text in prompt arguments before fetching.

        Args:
            payload: Prompt request payload containing arguments to normalize.
            context: Plugin execution context.

        Returns:
            Result with modified payload if any string arguments were normalized.
        """
        args = payload.args or {}
        changed = False
        new_args = {}
        for k, v in args.items():
            if isinstance(v, str):
                nv = _normalize_text(v, self._cfg)
                new_args[k] = nv
                changed = changed or (nv != v)
            else:
                new_args[k] = v
        if changed:
            return PromptPrehookResult(modified_payload=PromptPrehookPayload(name=payload.name, args=new_args))
        return PromptPrehookResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Normalize text content in resource after fetching.

        Args:
            payload: Resource fetch result containing content to normalize.
            context: Plugin execution context.

        Returns:
            Result with modified payload if resource text content was normalized.
        """
        c = payload.content
        if hasattr(c, "text") and isinstance(c.text, str):
            nt = _normalize_text(c.text, self._cfg)
            if nt != c.text:
                new_payload = ResourcePostFetchPayload(uri=payload.uri, content=type(c)(**{**c.model_dump(), "text": nt}))
                return ResourcePostFetchResult(modified_payload=new_payload)
        return ResourcePostFetchResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Normalize text in tool result after invocation.

        Args:
            payload: Tool invocation result containing text to normalize.
            context: Plugin execution context.

        Returns:
            Result with modified payload if tool result was normalized.
        """
        if isinstance(payload.result, str):
            nt = _normalize_text(payload.result, self._cfg)
            if nt != payload.result:
                return ToolPostInvokeResult(modified_payload=ToolPostInvokePayload(name=payload.name, result=nt))
        return ToolPostInvokeResult(continue_processing=True)
