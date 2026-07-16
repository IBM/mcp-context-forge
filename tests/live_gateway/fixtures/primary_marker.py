# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/fixtures/primary_marker.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Test-only plugin for the primary-worker e2e.

A non-hook plugin whose ``initialize()`` side effect is gated on
``is_primary_worker()`` and appends its PID to ``MCPGW_PRIMARY_WORKER_E2E_MARKER``.
A multi-worker gateway should leave exactly one line in that file.
"""

# Standard
import os
import time

# Third-Party
from cpex.framework import Plugin, PluginConfig

# First-Party
from mcpgateway.utils.primary_worker import is_primary_worker

DEFAULT_MARKER = "/tmp/mcpgw_primary_worker_e2e.log"  # nosec B108 - test artifact path, overridable via env


class PrimaryWorkerE2EMarkerPlugin(Plugin):
    """Records a marker line only on the primary worker."""

    def __init__(self, config: PluginConfig):
        """Initialize the plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._marker = os.environ.get("MCPGW_PRIMARY_WORKER_E2E_MARKER", DEFAULT_MARKER)

    async def initialize(self) -> None:
        """Append this PID to the marker file when this worker is primary."""
        if not is_primary_worker():
            return
        with open(self._marker, "a", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} t={time.time():.3f}\n")
