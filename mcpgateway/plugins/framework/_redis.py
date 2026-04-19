# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/_redis.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Dependency-inversion shim for Redis access inside the plugin framework.

The framework package must not import from ``mcpgateway.utils`` directly
(enforced by ``scripts/pre-commit/check_framework_imports.py``). Instead, the
gateway registers a Redis client provider at startup via
``set_shared_redis_provider``; framework modules call
``get_shared_redis_client()`` to retrieve a client without naming the
gateway util.

When the provider is unset (tests, framework-only deployments, or before
lifespan startup runs), ``get_shared_redis_client`` returns ``None`` and
the caller's Redis-unavailable fallback paths engage.
"""

from typing import Any, Awaitable, Callable, Optional

RedisProvider = Callable[[], Awaitable[Optional[Any]]]

_provider: Optional[RedisProvider] = None


def set_shared_redis_provider(provider: Optional[RedisProvider]) -> None:
    """Register (or clear) the gateway's Redis client factory.

    Call with ``None`` to unregister — useful for test isolation.
    """
    global _provider
    _provider = provider


async def get_shared_redis_client() -> Optional[Any]:
    """Return the shared Redis client from the registered provider, or ``None``.

    ``None`` is returned when no provider has been registered, when the
    provider yields ``None`` (e.g. Redis disabled in config), or when the
    provider raises — callers treat all three cases as "Redis unavailable".
    """
    provider = _provider
    if provider is None:
        return None
    return await provider()
