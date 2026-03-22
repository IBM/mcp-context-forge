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
from typing import Any, List, Set
from urllib.parse import urlparse
import logging

# Third-Party
from pydantic import BaseModel, Field, field_validator

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
)

logger = logging.getLogger(__name__)

# Try to import Rust-accelerated implementation
try:
    from url_reputation_rust import URLReputationPlugin as URLReputationPluginRust
    _RUST_AVAILABLE = True
    logger.info("Rust url reputation plugin available")
except ImportError as e:
    _RUST_AVAILABLE = False
    logger.warning("Rust url reputation not available (will use Python): %s", e)
except Exception as e:
    _RUST_AVAILABLE = False
    logger.error("Unexpected error loading Rust module: %s", e, exc_info=True)


class URLReputationConfig(BaseModel):
    """Configuration for URL reputation checks.
    """

    whitelist_domains: Set[str] = Field(
        default_factory=set,
        description="Domains that are always allowed, bypassing checks."
    )
    allowed_patterns: List[str] = Field(
        default_factory=list,
        description="URL patterns that are explicitly allowed."
    )
    blocked_domains: Set[str] = Field(
        default_factory=set,
        description="Domains that are blocked by the plugin."
    )
    blocked_patterns: List[str] = Field(
        default_factory=list,
        description="URL patterns that are blocked by the plugin."
    )
    use_heuristic_check: bool = Field(
        default=False,
        description="Enable heuristic checks for suspicious URLs."
    )
    entropy_threshold: float = Field(
        default=3.65,
        description="Entropy threshold for detecting suspicious URLs."
    )
    block_non_secure_http: bool = Field(
        default=True,
        description="Block non-HTTPS URLs if True."
    )

    @field_validator("whitelist_domains", "blocked_domains", mode="before")
    @classmethod
    def normalize_domains(cls, v: Any) -> Set[str]:
        """Transform domains for lowercase"""
        if not v:
            return set()
        return {d.lower() for d in v}


class URLReputationPlugin(Plugin):
    """Static allow/deny URL reputation checks."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the URL reputation plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = URLReputationConfig(**(config.config or {}))
        if _RUST_AVAILABLE:
            self.rust_plugin = URLReputationPluginRust(self._cfg)
        else:
            logger.warning(
                "Rust plugin not available. Using Python implementation with less features; "
                "Heuristic checks and regex patterns are not implemented in Python."
            )

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Check URL against blocked domains and patterns before fetch.

        Args:
            payload: Resource pre-fetch payload.
            context: Plugin execution context.

        Returns:
            Result indicating whether URL is allowed or blocked.
        """

        if _RUST_AVAILABLE:
            try:
                result_dict = self.rust_plugin.validate_url_py(payload.uri)
                return ResourcePreFetchResult(**result_dict)
            except Exception as e:
                logger.warning(
                    f"Rust plugin failed, blocking URL for security, error: {e}",
                )
                return ResourcePreFetchResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Rust validation failure",
                        description=f"URL {payload.uri} blocked due to internal error",
                        code="URL_REPUTATION_BLOCK",
                        details={"url": payload.uri},
                    ),
                )

        # Python plugin version will be deprecated
        parsed = urlparse(payload.uri)
        host = parsed.hostname or ""

        if host and (host in self._cfg.whitelist_domains or any(host.endswith("." + d) for d in self._cfg.whitelist_domains)):
            return ResourcePreFetchResult(continue_processing=True)

        # Block non-secure HTTP
        if self._cfg.block_non_secure_http and parsed.scheme != "https":
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=PluginViolation(
                    reason="Blocked non secure http url",
                    description=f"URL {payload.uri} is blocked",
                    code="URL_REPUTATION_BLOCK",
                    details={"url": payload.uri},
                ),
            )
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
