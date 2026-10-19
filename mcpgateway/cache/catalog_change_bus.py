# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/cache/catalog_change_bus.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Catalog change bus for ``subscriptions/listen``.

This module turns registry-cache invalidations into SDK ``ServerEvent`` values.
It coalesces bursts into one event per kind per ``COALESCE_SECONDS`` window and
publishes them on a per-worker ``InMemorySubscriptionBus``.

Echo suppression is done by coalescing. A worker's own Redis echo arrives inside
the window and merges with the local emit. A later echo causes one duplicate
``list_changed`` event, which is harmless.

This module imports only the MCP SDK and the standard library, so
``registry_cache`` can import it without an import cycle.
"""

# Standard
import asyncio
from asyncio import AbstractEventLoop
import logging
from typing import Optional
import weakref

# Third-Party
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler
from mcp.shared.subscriptions import PromptsListChanged, ResourcesListChanged, ServerEvent, ToolsListChanged

logger = logging.getLogger(__name__)

CACHE_TYPE_EVENTS: dict[str, tuple[type[ServerEvent], ...]] = {
    "tools": (ToolsListChanged,),
    "prompts": (PromptsListChanged,),
    "resources": (ResourcesListChanged,),
    "servers": (ToolsListChanged, PromptsListChanged, ResourcesListChanged),
}

COALESCE_SECONDS: float = 0.3

_listen_bus: Optional[InMemorySubscriptionBus] = None  # pylint: disable=invalid-name
_listen_handler: Optional[ListenHandler] = None  # pylint: disable=invalid-name
_pending: "weakref.WeakKeyDictionary[AbstractEventLoop, set[type[ServerEvent]]]" = weakref.WeakKeyDictionary()
_publish_tasks: "set[asyncio.Task[None]]" = set()


def get_listen_bus() -> InMemorySubscriptionBus:
    """Return the process-wide listen bus.

    Returns:
        InMemorySubscriptionBus: The singleton bus that listen streams subscribe to.
    """
    global _listen_bus  # pylint: disable=global-statement
    if _listen_bus is None:
        _listen_bus = InMemorySubscriptionBus()
    return _listen_bus


def get_listen_handler() -> ListenHandler:
    """Return the process-wide ``subscriptions/listen`` handler.

    Returns:
        ListenHandler: The singleton handler over ``get_listen_bus()`` with SDK default limits.
    """
    global _listen_handler  # pylint: disable=global-statement
    if _listen_handler is None:
        _listen_handler = ListenHandler(get_listen_bus())
    return _listen_handler


async def _publish(kinds: set[type[ServerEvent]]) -> None:
    """Publish one event per kind on the listen bus.

    Args:
        kinds: Event classes to instantiate and publish.
    """
    bus = get_listen_bus()
    for kind in kinds:
        try:
            await bus.publish(kind())  # type: ignore[call-arg]  # mapped kinds take no arguments
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to publish %s on the listen bus", kind.__name__)


def _flush(loop: AbstractEventLoop) -> None:
    """Swap out the pending kinds for ``loop`` and start a publish task.

    Args:
        loop: Event loop whose window just closed.
    """
    kinds = _pending.pop(loop, None)
    if not kinds:
        return
    task = loop.create_task(_publish(kinds))
    _publish_tasks.add(task)
    task.add_done_callback(_publish_tasks.discard)


def notify_catalog_change(cache_type: str) -> None:
    """Record a catalog change for the listen bus.

    Does nothing without a running event loop or for unmapped cache types.
    Never raises.

    Args:
        cache_type: Registry cache type that was invalidated, for example ``"tools"``.
    """
    try:
        events = CACHE_TYPE_EVENTS.get(cache_type)
        if not events:
            return
        loop = asyncio.get_running_loop()
        pending = _pending.get(loop)
        if pending is None:
            pending = _pending[loop] = set()
            loop.call_later(COALESCE_SECONDS, _flush, loop)
        pending.update(events)
    except RuntimeError:
        return
    except Exception:  # pylint: disable=broad-except
        logger.exception("Failed to record catalog change for %s", cache_type)
