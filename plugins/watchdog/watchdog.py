# -*- coding: utf-8 -*-
"""Location: ./plugins/watchdog/watchdog.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Watchdog Plugin.

Records tool execution duration and enforces a max runtime policy: warn or block.

Hooks: tool_pre_invoke, tool_post_invoke
"""

# Future
from __future__ import annotations

# Standard
import time
from typing import Any, Dict

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)


class WatchdogConfig(BaseModel):
    """Configuration for watchdog plugin.

    Attributes:
        max_duration_ms: Maximum execution duration in milliseconds.
        action: Action to take on timeout (warn or block).
        tool_overrides: Per-tool configuration overrides.
    """

    max_duration_ms: int = 30000
    action: str = "warn"  # warn | block
    tool_overrides: Dict[str, Dict[str, Any]] = {}


class WatchdogPlugin(Plugin):
    """Records tool execution duration and enforces maximum runtime policy."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the watchdog plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = WatchdogConfig(**(config.config or {}))

    def _cfg_for(self, tool: str) -> WatchdogConfig:
        """Get configuration for specific tool with overrides applied.

        Args:
            tool: Tool name.

        Returns:
            Tool-specific configuration or default configuration.
        """
        if tool in self._cfg.tool_overrides:
            merged = {**self._cfg.model_dump(), **self._cfg.tool_overrides[tool]}
            return WatchdogConfig(**merged)
        return self._cfg

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Record tool start time before execution.

        Args:
            payload: Tool invocation payload.
            context: Plugin execution context.

        Returns:
            Result allowing processing to continue.
        """
        context.set_state("watchdog_start", time.time())
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Check tool execution duration and enforce timeout policy.

        Args:
            payload: Tool result payload.
            context: Plugin execution context.

        Returns:
            Result indicating timeout violation or execution metadata.
        """
        start = context.get_state("watchdog_start", time.time())
        elapsed_ms = int((time.time() - start) * 1000)
        cfg = self._cfg_for(payload.name)
        meta = {"watchdog_elapsed_ms": elapsed_ms, "watchdog_limit_ms": cfg.max_duration_ms}
        if elapsed_ms > max(1, int(cfg.max_duration_ms)):
            if cfg.action == "block":
                return ToolPostInvokeResult(
                    continue_processing=False,
                    violation=PluginViolation(
                        reason="Execution time exceeded",
                        description=f"Tool '{payload.name}' exceeded max duration",
                        code="WATCHDOG_TIMEOUT",
                        details=meta,
                    ),
                )
            return ToolPostInvokeResult(metadata={**meta, "watchdog_violation": True})
        return ToolPostInvokeResult(metadata=meta)
