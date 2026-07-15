# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/fixtures/hook_marker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Test-only HOOK plugin for the primary-worker e2e.

Declares a hook and is NOT gated on is_primary_worker(); its initialize()
appends its PID to ``MCPGW_PRIMARY_WORKER_E2E_HOOK_MARKER`` on every worker. So
with N workers the file has N lines, proving election does not suppress hooks
(vs the gated non-hook plugin's 1).
"""

# Future
from __future__ import annotations

# Standard
import os
import time

# Third-Party
from cpex.framework import (
    HttpHeaderPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
)

DEFAULT_MARKER = "/tmp/mcpgw_primary_worker_e2e_hook.log"  # nosec B108 - test artifact path, overridable via env


class PrimaryWorkerE2EHookPlugin(Plugin):
    """Ungated hook plugin: records every worker that loads it."""

    def __init__(self, config: PluginConfig):
        """Initialize the plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._marker = os.environ.get("MCPGW_PRIMARY_WORKER_E2E_HOOK_MARKER", DEFAULT_MARKER)

    async def initialize(self) -> None:
        """Append this PID on every worker (no primary gate)."""
        with open(self._marker, "a", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} t={time.time():.3f}\n")

    async def http_pre_request(
        self,
        payload: HttpPreRequestPayload,
        context: PluginContext,
    ) -> PluginResult[HttpHeaderPayload]:
        """Pass the request through unchanged.

        Args:
            payload: The HTTP pre-request payload.
            context: Plugin execution context.

        Returns:
            A passthrough result.
        """
        return PluginResult(continue_processing=True)
