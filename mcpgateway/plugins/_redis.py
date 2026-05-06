# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/_redis.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Dependency-inversion shim for Redis access inside the gateway plugin layer.

The gateway registers a Redis client provider at startup via
``set_shared_redis_provider``; plugin-layer modules call
``get_shared_redis_client()`` to retrieve a client without
depending on ``mcpgateway.utils`` directly.
"""

# Standard
from typing import Any, Awaitable, Callable, Optional

RedisProvider = Callable[[], Awaitable[Optional[Any]]]

_provider: Optional[RedisProvider] = None


def set_shared_redis_provider(provider: Optional[RedisProvider]) -> None:
    """Register (or clear) the gateway's Redis client factory."""
    global _provider
    _provider = provider


async def get_shared_redis_client() -> Optional[Any]:
    """Return the shared Redis client from the registered provider, or ``None``."""
    provider = _provider
    if provider is None:
        return None
    return await provider()
