# -*- coding: utf-8 -*-
"""Location: ./plugins/url_reputation/url_reputation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

URL Reputation Plugin.
Blocks known-bad domains or URL patterns before fetching resources.
"""

# Future
from __future__ import annotations

# Standard
from typing import List
from urllib.parse import urlparse

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)


class URLReputationConfig(BaseModel):
    """Configuration for URL reputation checks.

    Attributes:
        blocked_domains: List of blocked domain names.
        blocked_patterns: List of blocked URL patterns.
    """

    blocked_domains: List[str] = Field(default_factory=list)
    blocked_patterns: List[str] = Field(default_factory=list)


class URLReputationPlugin(Plugin):
    """Static allow/deny URL reputation checks."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the URL reputation plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = URLReputationConfig(**(config.config or {}))

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Check URL against blocked domains and patterns before fetch.

        Args:
            payload: Resource pre-fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating whether URL is allowed or blocked.
        """
        parsed = urlparse(payload.uri)
        host = parsed.hostname or ""
        # Domain check
        if host and any(host == d or host.endswith("." + d) for d in self._cfg.blocked_domains):
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Blocked domain",
                    description=f"Domain {host} is blocked",
                    code="URL_REPUTATION_BLOCK",
                    details={"domain": host},
                ),
            )
        # Pattern check
        uri = payload.uri
        for pat in self._cfg.blocked_patterns:
            if pat in uri:
                return ResourcePreFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Blocked pattern",
                        description=f"URL matches blocked pattern: {pat}",
                        code="URL_REPUTATION_BLOCK",
                        details={"pattern": pat},
                    ),
                )
        return ResourcePreFetchResult(continue_processing=True)
