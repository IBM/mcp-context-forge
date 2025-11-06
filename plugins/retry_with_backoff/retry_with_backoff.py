# -*- coding: utf-8 -*-
"""Location: ./plugins/retry_with_backoff/retry_with_backoff.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Retry With Backoff Plugin.
Advisory plugin that annotates retry policy metadata for downstream systems.
Note: The framework cannot re-execute tools/resources; this provides guidance only.
"""

# Future
from __future__ import annotations

# Third-Party
from pydantic import BaseModel, Field

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


class RetryPolicyConfig(BaseModel):
    """Configuration for retry policy.

    Attributes:
        max_retries: Maximum number of retry attempts.
        backoff_base_ms: Base backoff duration in milliseconds.
        max_backoff_ms: Maximum backoff duration in milliseconds.
        retry_on_status: HTTP status codes that trigger retries.
    """

    max_retries: int = Field(default=2, ge=0)
    backoff_base_ms: int = Field(default=200, ge=0)
    max_backoff_ms: int = Field(default=5000, ge=0)
    retry_on_status: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])


class RetryWithBackoffPlugin(Plugin):
    """Attach retry/backoff policy in metadata for observability/orchestration."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the retry with backoff plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = RetryPolicyConfig(**(config.config or {}))

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Attach retry policy metadata after tool invocation.

        Args:
            payload: Tool invocation result payload.
            context: Plugin execution context.

        Returns:
            Result with retry policy metadata.
        """
        return ToolPostInvokeResult(
            metadata={
                "retry_policy": {
                    "max_retries": self._cfg.max_retries,
                    "backoff_base_ms": self._cfg.backoff_base_ms,
                    "max_backoff_ms": self._cfg.max_backoff_ms,
                }
            }
        )

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Attach retry policy metadata after resource fetch.

        Args:
            payload: Resource fetch payload.
            context: Plugin execution context.

        Returns:
            Result with retry policy metadata.
        """
        return ResourcePostFetchResult(
            metadata={
                "retry_policy": {
                    "max_retries": self._cfg.max_retries,
                    "backoff_base_ms": self._cfg.backoff_base_ms,
                    "max_backoff_ms": self._cfg.max_backoff_ms,
                    "retry_on_status": self._cfg.retry_on_status,
                }
            }
        )
