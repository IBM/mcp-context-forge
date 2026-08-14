# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/reverse_proxy_relay_runtime.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Process-local construction and identity for reverse-proxy relay wiring.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
import logging
import os
import socket
from typing import Protocol
import uuid

# Third-Party
import anyio

# First-Party
from mcpgateway.config import settings
from mcpgateway.services.reverse_proxy_relay import RelayUnavailableError, ReverseProxyRelay
from mcpgateway.services.reverse_proxy_sessions import get_reverse_proxy_session_manager, ReverseProxyEviction, ReverseProxySessionManager
from mcpgateway.utils.redis_client import get_redis_client

_OWNER_TTL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class _WorkerIdentity:
    """One identity generated inside the current worker process."""

    pid: int
    value: str


class _GatewayReachabilityService(Protocol):
    """Minimal lazy gateway-service seam used by authority-loss persistence."""

    async def mark_reverse_proxy_gateways_unreachable(
        self,
        manager: ReverseProxySessionManager,
        evictions: tuple[ReverseProxyEviction, ...],
        *,
        seen_at: datetime,
    ) -> None:
        """Persist replacement-aware reverse-proxy reachability loss."""


_worker_identity: _WorkerIdentity | None = None
_default_relay: ReverseProxyRelay | None = None
_relay_pid: int | None = None
_relay_lock = anyio.Lock()
LOGGER = logging.getLogger(__name__)


def current_reverse_proxy_worker_id() -> str:
    """Return a worker identity that is regenerated after a process fork."""
    global _worker_identity
    pid = os.getpid()
    if _worker_identity is None or _worker_identity.pid != pid:
        _worker_identity = _WorkerIdentity(pid=pid, value=f"{socket.gethostname()}:{pid}:{uuid.uuid4().hex[:8]}")
    return _worker_identity.value


async def get_reverse_proxy_relay() -> ReverseProxyRelay:
    """Return the configured process-local relay wrapper."""
    global _default_relay, _relay_pid
    async with _relay_lock:
        pid = os.getpid()
        if _default_relay is None or _relay_pid != pid:
            manager = await get_reverse_proxy_session_manager()
            redis = None
            if settings.mcpgateway_reverse_proxy_distributed_enabled:
                redis = await get_redis_client()
                if redis is None:
                    raise RelayUnavailableError
            _default_relay = ReverseProxyRelay(
                manager,
                redis=redis,
                worker_id=current_reverse_proxy_worker_id,
                owner_ttl_seconds=_OWNER_TTL_SECONDS,
                ownership_lost=_persist_lost_authority,
            )
            _relay_pid = pid
        return _default_relay


async def run_reverse_proxy_relay_heartbeat(relay: ReverseProxyRelay | None = None) -> None:
    """Refresh relay liveness until lifespan cancellation."""
    active_relay = relay or await get_reverse_proxy_relay()
    while True:
        await active_relay.heartbeat()
        await anyio.sleep(_OWNER_TTL_SECONDS / 3)


async def _persist_lost_authority(evictions: tuple[ReverseProxyEviction, ...]) -> None:
    """Persist authority loss through the replacement-aware gateway policy."""
    gateway_service: _GatewayReachabilityService = getattr(import_module("mcpgateway.services.gateway_service"), "gateway_service")
    manager = await get_reverse_proxy_session_manager()
    try:
        await gateway_service.mark_reverse_proxy_gateways_unreachable(manager, evictions, seen_at=datetime.now(tz=timezone.utc))
    except Exception:  # best-effort persistence must not restore stale authority
        LOGGER.warning("Reverse-proxy authority-loss persistence failed")


async def release_reverse_proxy_owners_best_effort(relay: ReverseProxyRelay, evictions: tuple[ReverseProxyEviction, ...]) -> None:
    """Attempt every exact-generation release without interrupting local cleanup."""
    for eviction in evictions:
        try:
            await relay.release_owner(eviction.stable_id, eviction.connection_id)
        except Exception:  # every release attempt must run despite backend-specific failures
            LOGGER.warning("Reverse-proxy owner release failed", extra={"stable_id": str(eviction.stable_id)})


@asynccontextmanager
async def reverse_proxy_relay_lifespan() -> AsyncGenerator[ReverseProxyRelay]:
    """Supervise listener and heartbeat with readiness and deterministic cleanup."""
    relay = await get_reverse_proxy_relay()
    try:
        async with anyio.create_task_group() as task_group:
            await task_group.start(relay.listen)
            await relay.heartbeat()
            task_group.start_soon(run_reverse_proxy_relay_heartbeat, relay)
            try:
                yield relay
            finally:
                task_group.cancel_scope.cancel()
    finally:
        reset_reverse_proxy_relay()


def reset_reverse_proxy_relay() -> None:
    """Clear process-local relay and worker state for startup or isolated tests."""
    global _default_relay, _relay_pid, _worker_identity
    _default_relay = None
    _relay_pid = None
    _worker_identity = None


async def shutdown_reverse_proxy_relay() -> None:
    """Clear relay state after its lifespan tasks have stopped."""
    reset_reverse_proxy_relay()
