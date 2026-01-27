# -*- coding: utf-8 -*-
"""Location: ./plugins/robots_license_guard/robots_license_guard.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Robots and License Guard Plugin.

Honors basic content usage signals found in HTML: robots/noai/noimageai meta and license meta.
Blocks or annotates based on configuration.

Hooks: resource_post_fetch (primary), resource_pre_fetch (annotation)
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
    PluginViolation,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)

META_PATTERN = re.compile(
    r'<meta\b[^>]*?\bname="(?P<name>robots|x-robots-tag|genai|permissions-policy|license)"[^>]*?\bcontent="(?P<content>[^"]+)"[^>]*>',
    re.IGNORECASE,
)


class RobotsLicenseConfig(BaseModel):
    """Configuration for robots and license guard plugin.

    Attributes:
        user_agent: User-Agent string to use in requests.
        respect_noai_meta: Whether to respect noai/robots meta tags.
        block_on_violation: Whether to block on policy violations.
        license_required: Whether license metadata is required.
        allow_overrides: URI substrings that bypass checks.
    """

    user_agent: str = "MCP-Context-Forge/1.0"
    respect_noai_meta: bool = True
    block_on_violation: bool = True
    license_required: bool = False
    allow_overrides: list[str] = []  # substrings that allow bypass


def _has_override(uri: str, overrides: list[str]) -> bool:
    """Check if URI contains any override token.

    Args:
        uri: Resource URI to check.
        overrides: List of override tokens.

    Returns:
        True if URI contains any override token.
    """
    return any(token in uri for token in overrides)


def _parse_meta(text: str) -> dict[str, str]:
    """Parse HTML meta tags for robots and license information.

    Args:
        text: HTML text to parse.

    Returns:
        Dictionary mapping meta tag names to their content.
    """
    found: dict[str, str] = {}
    for m in META_PATTERN.finditer(text):
        name = m.group("name").lower()
        content = m.group("content").lower()
        found[name] = content
    return found


class RobotsLicenseGuardPlugin(Plugin):
    """Honors robots/noai/license meta tags in fetched HTML content."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the robots license guard plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = RobotsLicenseConfig(**(config.config or {}))

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Add User-Agent header before resource fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with modified payload containing User-Agent header.
        """
        # Annotate user-agent hint in metadata for downstream fetcher
        md = dict(payload.metadata or {})
        headers = {**md.get("headers", {}), "User-Agent": self._cfg.user_agent}
        md["headers"] = headers
        new_payload = ResourcePreFetchPayload(uri=payload.uri, metadata=md)
        return ResourcePreFetchResult(modified_payload=new_payload)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Check fetched content for robots/noai/license meta tags.

        Args:
            payload: Resource post-fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating whether content violates robots/license policies.
        """
        content = payload.content
        if not hasattr(content, "text") or not isinstance(content.text, str) or not content.text:
            return ResourcePostFetchResult(continue_processing=True)
        if _has_override(payload.uri, self._cfg.allow_overrides):
            return ResourcePostFetchResult(metadata={"robots_override": True})
        meta = _parse_meta(content.text)
        # Respect noai signals
        violation_reasons = []
        if self._cfg.respect_noai_meta:
            values = ",".join(meta.get("robots", "").split()) + "," + ",".join(meta.get("x-robots-tag", "").split()) + "," + meta.get("genai", "")
            if any(tag in values for tag in ["noai", "noimageai", "nofollow", "noindex"]):
                violation_reasons.append("robots/noai policy")
        if self._cfg.license_required and not meta.get("license"):
            violation_reasons.append("missing license metadata")

        if violation_reasons and self._cfg.block_on_violation:
            return ResourcePostFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Robots/License policy",
                    description=", ".join(violation_reasons),
                    code="ROBOTS_LICENSE",
                    details={"meta": meta},
                ),
            )
        return ResourcePostFetchResult(metadata={"robots_meta": meta, "robots_violation": bool(violation_reasons)})
