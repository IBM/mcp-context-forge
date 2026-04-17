# -*- coding: utf-8 -*-
"""Content moderation plugin package for ContextForge.

Provides AI-powered content safety using IBM Watson, IBM Granite Guardian,
OpenAI, Azure, or AWS with configurable thresholds and actions.

Usage::

    kind: cpex_content_moderation.ContentModerationPlugin
"""

from __future__ import annotations


def __getattr__(name: str):
    """Lazy-load plugin class to avoid importing mcpgateway at module import time.

    Args:
        name: Attribute name to resolve.

    Returns:
        The requested class.

    Raises:
        AttributeError: If the attribute does not exist in this module.
    """
    if name == "ContentModerationPlugin":
        from cpex_content_moderation.content_moderation import ContentModerationPlugin

        return ContentModerationPlugin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ContentModerationPlugin"]
