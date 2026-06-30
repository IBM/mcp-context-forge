# -*- coding: utf-8 -*-
"""Location: ./plugins/primary_worker_multiinstance/marker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Test-only plugin for the multi-instance primary-worker e2e.

A non-hook plugin gated on ``is_primary_worker()``. When this process is the
primary, it pushes ``<hostname>:<pid>`` to a Redis list. Across several gateway
containers sharing one Redis (redis election backend), exactly one process is
primary, so the list ends up with a single entry — the cross-container proof a
per-container file marker cannot give.

Loaded only when the gateway is started with this fixture's plugin config; inert
otherwise. Not a production plugin.
"""

# Future
from __future__ import annotations

# Standard
import os
import socket

# Third-Party
from cpex.framework import Plugin, PluginConfig

# First-Party
from mcpgateway.utils.primary_worker import is_primary_worker

DEFAULT_MARKER_KEY = "mcpgw:primary_worker:e2e:markers"


class MultiInstanceMarkerPlugin(Plugin):
    """Records the primary process in a shared Redis list."""

    def __init__(self, config: PluginConfig):
        """Initialize the plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._key = os.environ.get("PRIMARY_WORKER_E2E_MARKER_KEY", DEFAULT_MARKER_KEY)
        self._redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    async def initialize(self) -> None:
        """Push this process to the shared Redis list when it is the primary."""
        if not is_primary_worker():
            return
        # Third-Party
        import redis.asyncio as aioredis  # pylint: disable=import-outside-toplevel

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.rpush(self._key, f"{socket.gethostname()}:{os.getpid()}")
        finally:
            await client.aclose()
