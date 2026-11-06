# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/resource_subscription_relay.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Relay of per-resource updates from modern (2026-07-28) upstream servers.

A downstream ``subscriptions/listen`` stream that names resource URIs holds a
watch on each upstream target for its lifetime. The relay keeps one upstream
``subscriptions/listen`` stream per ``(gateway_id, uri)`` on this worker,
shared by reference count across downstream streams. Each upstream
``notifications/resources/updated`` becomes an ``UpstreamResourceUpdated``
event, tagged with its gateway, on the worker-local listen bus.

Two upstream servers can expose the same URI to different teams. A stream that
honored URIs therefore listens through ``scoped_listen_bus()``, which passes a
resource update only when the stream watches that ``(gateway_id, uri)`` pair.
The SDK ``ListenHandler`` then stamps it with the stream's subscription ID.

The watch lives on the worker that holds the downstream stream, so no
cross-worker channel is needed.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import time
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

# Third-Party
from mcp.client.subscriptions import ListenNotSupportedError
from mcp.server.subscriptions import SubscriptionBus
from mcp.shared.subscriptions import ResourceUpdated, ServerEvent

# First-Party
from mcpgateway.cache.catalog_change_bus import get_listen_bus
from mcpgateway.services.modern_listener_service import BACKOFF_INITIAL_SECONDS, BACKOFF_MAX_SECONDS, ModernListenerService, UNSUPPORTED_REPROBE_SECONDS
from mcpgateway.utils.mcp_proxy_client import mcp_proxy_client

logger = logging.getLogger(__name__)

# Each distinct watch holds one upstream stream; bound them per worker.
MAX_RELAY_WATCHES = 256


@dataclass(frozen=True)
class UpstreamResourceTarget:
    """One upstream resource to watch, captured outside any DB session."""

    gateway_id: str
    url: str
    uri: str
    headers: Tuple[Tuple[str, str], ...] = ()

    def header_dict(self) -> Dict[str, str]:
        """Return the upstream auth headers as a dict.

        Returns:
            Dict[str, str]: Headers for the upstream client.
        """
        return dict(self.headers)


@dataclass(frozen=True)
class UpstreamResourceUpdated(ResourceUpdated):
    """A resource update from one upstream server; ``gateway_id`` scopes delivery."""

    gateway_id: str = ""


class _ScopedBus:
    """Listen bus view that drops resource updates outside one stream's watched targets."""

    def __init__(self, bus: SubscriptionBus, allowed: FrozenSet[Tuple[str, str]]) -> None:
        """Wrap ``bus`` for one stream.

        Args:
            bus: The worker-local listen bus.
            allowed: ``(gateway_id, uri)`` pairs the stream watches.
        """
        self._bus = bus
        self._allowed = allowed

    async def publish(self, event: ServerEvent) -> None:
        """Publish on the wrapped bus.

        Args:
            event: Event to publish.
        """
        await self._bus.publish(event)

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register ``listener`` for list events and for resource updates of watched targets only.

        Args:
            listener: The stream's delivery callback.

        Returns:
            Callable[[], None]: Unsubscribe callable from the wrapped bus.
        """
        allowed = self._allowed

        def scoped(event: ServerEvent) -> None:
            if isinstance(event, ResourceUpdated) and (getattr(event, "gateway_id", None), event.uri) not in allowed:
                return
            listener(event)

        return self._bus.subscribe(scoped)


def scoped_listen_bus(targets: Sequence["UpstreamResourceTarget"]) -> SubscriptionBus:
    """Return a listen bus view that delivers resource updates only from ``targets``.

    Args:
        targets: Upstream resources one stream watches.

    Returns:
        SubscriptionBus: Filtered view of the worker-local listen bus.
    """
    return _ScopedBus(get_listen_bus(), frozenset((target.gateway_id, target.uri) for target in targets))


@dataclass
class _Watch:
    """A shared upstream stream and the number of downstream streams using it."""

    count: int
    task: asyncio.Task


class ResourceSubscriptionRelay:
    """Hold one upstream listen stream per watched ``(gateway_id, uri)`` on this worker."""

    def __init__(self) -> None:
        """Start with no watches."""
        self._watches: Dict[Tuple[str, str], _Watch] = {}
        self._unsupported_until: Dict[str, float] = {}

    @asynccontextmanager
    async def watch(self, targets: Sequence[UpstreamResourceTarget]) -> AsyncIterator[List[UpstreamResourceTarget]]:
        """Keep the upstream streams for the admitted ``targets`` open while the context is active.

        A target is admitted unless its upstream recently negotiated a pre-2026 protocol,
        or it would start a new watch past ``MAX_RELAY_WATCHES``.

        Args:
            targets: Upstream resources the caller subscribed to.

        Yields:
            List[UpstreamResourceTarget]: The admitted targets, held until the context exits.
        """
        now = time.monotonic()
        admitted: List[UpstreamResourceTarget] = []
        for target in targets:
            if self._unsupported_until.get(target.gateway_id, 0.0) > now:
                continue
            if (target.gateway_id, target.uri) not in self._watches and len(self._watches) >= MAX_RELAY_WATCHES:
                continue
            self._acquire(target)
            admitted.append(target)
        try:
            yield admitted
        finally:
            for target in admitted:
                self._release((target.gateway_id, target.uri))

    def _acquire(self, target: UpstreamResourceTarget) -> Tuple[str, str]:
        """Count one watcher of ``target``, starting its upstream stream on the first.

        Args:
            target: Upstream resource to watch.

        Returns:
            Tuple[str, str]: The watch key to release later.
        """
        key = (target.gateway_id, target.uri)
        watch = self._watches.get(key)
        if watch is None:
            task = asyncio.create_task(self._relay_forever(target), name=f"resource-relay-{target.gateway_id}")
            self._watches[key] = _Watch(count=1, task=task)
        else:
            watch.count += 1
        return key

    def _release(self, key: Tuple[str, str]) -> None:
        """Drop one watcher of ``key`` and cancel its upstream stream after the last.

        Args:
            key: Watch key returned by ``_acquire``.
        """
        watch = self._watches.get(key)
        if watch is None:
            return
        watch.count -= 1
        if watch.count <= 0:
            del self._watches[key]
            watch.task.cancel()

    async def shutdown(self) -> None:
        """Cancel every upstream stream and forget every watch."""
        tasks = [watch.task for watch in self._watches.values()]
        self._watches.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _relay_forever(self, target: UpstreamResourceTarget) -> None:
        """Relay upstream updates for one resource, reconnecting with jittered backoff.

        The spec defines no replay, so each re-listen after a drop publishes one update.
        Downstream clients then read the resource again in case they missed a change.

        Args:
            target: Upstream resource to watch.
        """
        backoff = BACKOFF_INITIAL_SECONDS
        relisten = False
        while True:
            acked_at: Optional[float] = None
            try:
                async with mcp_proxy_client(url=target.url, headers=target.header_dict()) as client:
                    async with client.listen(resource_subscriptions=[target.uri]) as subscription:
                        acked_at = time.monotonic()
                        if target.uri not in (subscription.honored.resource_subscriptions or ()):
                            logger.info("Upstream server %s did not honor a subscription to %s; no updates will be relayed", target.gateway_id, target.uri)
                            return
                        if relisten:
                            await self._publish(target)
                        async for _event in subscription:
                            await self._publish(target)
            except ListenNotSupportedError:
                self._unsupported_until[target.gateway_id] = time.monotonic() + UNSUPPORTED_REPROBE_SECONDS
                logger.info("Upstream server %s negotiated a pre-2026 protocol; no updates will be relayed for %s", target.gateway_id, target.uri)
                return
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception as exc:  # pylint: disable=broad-except  # SubscriptionLost, MCPError, transport errors
                logger.warning("Resource subscription to %s on server %s dropped (%s: %s)", target.uri, target.gateway_id, type(exc).__name__, exc)
            if acked_at is not None and time.monotonic() - acked_at >= BACKOFF_MAX_SECONDS:
                backoff = BACKOFF_INITIAL_SECONDS
            relisten = True
            await asyncio.sleep(ModernListenerService._backoff_with_jitter(backoff))  # pylint: disable=protected-access
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)

    @staticmethod
    async def _publish(target: UpstreamResourceTarget) -> None:
        """Publish an update for ``target`` on the worker-local listen bus.

        The upstream stream watches exactly this URI, so every event names it.
        The SDK ``ListenHandler`` matches URIs exactly, so the relay publishes the subscribed URI.

        Args:
            target: The watched upstream resource.
        """
        await get_listen_bus().publish(UpstreamResourceUpdated(uri=target.uri, gateway_id=target.gateway_id))


_relay: Optional[ResourceSubscriptionRelay] = None  # pylint: disable=invalid-name


def get_resource_subscription_relay() -> ResourceSubscriptionRelay:
    """Return the process-wide relay.

    Returns:
        ResourceSubscriptionRelay: The singleton relay.
    """
    global _relay  # pylint: disable=global-statement
    if _relay is None:
        _relay = ResourceSubscriptionRelay()
    return _relay
