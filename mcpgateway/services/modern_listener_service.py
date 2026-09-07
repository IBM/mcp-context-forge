# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/modern_listener_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Standing change-event listeners for modern (2026-07-28) upstream servers.

This service holds one dedicated ``subscriptions/listen`` stream per modern-era
server so change events reach the gateway seconds after they
happen, independent of any client traffic.

Events are funneled into :class:`NotificationService`'s debounced refresh
pipeline (``notify_list_changed``), so listener-driven refreshes share the
same coalescing and rate limiting as session-delivered notifications.

The scheduled auto-refresh (``AUTO_REFRESH_SERVERS``) covers legacy servers, 
modern-era servers that never announce, and any window
where a listen stream is down.

Era detection is by attempt: ``Client.listen()`` raises
``ListenNotSupportedError`` when the negotiated protocol version predates
2026-07-28, and such servers are put on a long re-probe cooldown. Servers
registered with the SSE transport are skipped outright (SSE is a legacy-only
transport). OAuth-authenticated servers are currently skipped — their
token refresh lifecycle does not fit a single long-lived stream yet.

Naming note: registered upstream MCP servers live in the ``gateways`` DB
table (the ``Gateway`` model) for historical federation reasons, so
identifiers here say ``gateway`` to match the rest of the codebase.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Third-Party
from mcp.client.subscriptions import ListenNotSupportedError, PromptsListChanged, ResourcesListChanged, ResourceUpdated, ToolsListChanged
from sqlalchemy import select

# First-Party
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import SessionLocal
from mcpgateway.services.notification_service import NotificationService, NotificationType
from mcpgateway.utils.mcp_proxy_client import mcp_proxy_client
from mcpgateway.utils.services_auth import decode_auth

logger = logging.getLogger(__name__)

__all__ = ["ModernListenerService", "get_modern_listener_service", "init_modern_listener_service"]

# How often the reconcile loop compares running listeners against the gateways table (registered servers).
RECONCILE_INTERVAL_SECONDS = 30.0
# Reconnect backoff after a dropped stream: initial delay, doubling up to the cap.
BACKOFF_INITIAL_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 300.0
# How long to leave a server alone after it negotiated a pre-2026 protocol.
UNSUPPORTED_REPROBE_SECONDS = 3600.0


@dataclass
class _GatewaySnapshot:
    """Connection details captured from a DB row, used outside the DB session."""

    id: str
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)


class ModernListenerService:
    """Maintain one ``subscriptions/listen`` stream per modern-era server.

    A reconcile loop periodically reads the gateways table (registered
    upstream servers) and ensures each eligible server has a running
    listener task; listeners for deleted or disabled servers are cancelled.
    Each listener task reconnects with exponential backoff and exits
    permanently (until the cooldown lapses) if the server turns out to be
    pre-2026.
    """

    def __init__(self, notification_service: NotificationService):
        """Wire the listener to the notification service it feeds.

        Args:
            notification_service: Debounced refresh pipeline that listen
                events are dispatched into.
        """
        self._notification_service = notification_service
        self._listener_tasks: Dict[str, asyncio.Task] = {}
        self._unsupported_until: Dict[str, float] = {}
        self._reconcile_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Start the reconcile loop."""
        self._reconcile_task = asyncio.create_task(self._reconcile_loop(), name="modern-listener-reconcile")
        logger.info(
            "ModernListenerService initialized (reconcile every %.0fs, reconnect backoff %.0f-%.0fs)",
            RECONCILE_INTERVAL_SECONDS,
            BACKOFF_INITIAL_SECONDS,
            BACKOFF_MAX_SECONDS,
        )

    async def shutdown(self) -> None:
        """Stop the reconcile loop and cancel all listener tasks."""
        self._shutdown_event.set()
        tasks = list(self._listener_tasks.values())
        if self._reconcile_task is not None:
            tasks.append(self._reconcile_task)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pylint: disable=broad-except
                pass
        self._listener_tasks.clear()
        logger.info("ModernListenerService shut down")

    async def _reconcile_loop(self) -> None:
        """Periodically align running listeners with the gateways table (registered servers)."""
        while not self._shutdown_event.is_set():
            try:
                await self._reconcile()
            except Exception:  # pylint: disable=broad-except
                logger.exception("Modern listener reconcile pass failed")
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=RECONCILE_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def _reconcile(self) -> None:
        """Start missing listeners, drop listeners for gone servers."""
        snapshots = {gw.id: gw for gw in self._load_eligible_gateways()}

        # Cancel listeners whose server disappeared or became ineligible.
        for gateway_id in list(self._listener_tasks):
            if gateway_id not in snapshots:
                task = self._listener_tasks.pop(gateway_id)
                task.cancel()
                logger.info("Stopped modern listener for removed/ineligible server %s", gateway_id)

        now = time.monotonic()
        for gateway_id, snapshot in snapshots.items():
            existing = self._listener_tasks.get(gateway_id)
            if existing is not None and not existing.done():
                continue
            if self._unsupported_until.get(gateway_id, 0.0) > now:
                continue
            self._listener_tasks[gateway_id] = asyncio.create_task(
                self._listen_forever(snapshot),
                name=f"modern-listener-{snapshot.name}",
            )

    def _load_eligible_gateways(self) -> List[_GatewaySnapshot]:
        """Read enabled, listener-eligible servers from the DB.

        Uses a short-lived session and returns plain snapshots so no ORM
        objects (or connections) are held while streams are open.
        """
        snapshots: List[_GatewaySnapshot] = []
        with SessionLocal() as db:
            rows = db.execute(select(DbGateway).where(DbGateway.enabled.is_(True))).scalars().all()
            for gw in rows:
                if (gw.transport or "").upper() == "SSE":
                    continue  # SSE is a legacy-only transport; listen can never succeed
                if gw.auth_type == "oauth":
                    logger.debug("Skipping modern listener for OAuth server %s (token lifecycle not supported on standing streams)", gw.name)
                    continue
                auth_data = gw.auth_value or {}
                if isinstance(auth_data, str):
                    headers = decode_auth(auth_data)
                elif isinstance(auth_data, dict):
                    headers = {str(k): str(v) for k, v in auth_data.items()}
                else:
                    headers = {}
                snapshots.append(_GatewaySnapshot(id=gw.id, name=gw.name, url=gw.url, headers=headers))
        return snapshots

    async def _listen_forever(self, gw: _GatewaySnapshot) -> None:
        """Hold a listen stream to one server, reconnecting with backoff."""
        backoff = BACKOFF_INITIAL_SECONDS
        while not self._shutdown_event.is_set():
            try:
                async with mcp_proxy_client(url=gw.url, headers=gw.headers) as client:
                    async with client.listen(tools_list_changed=True, prompts_list_changed=True, resources_list_changed=True) as subscription:
                        logger.info("Listening for change events on modern server %s (%s)", gw.name, gw.url)
                        backoff = BACKOFF_INITIAL_SECONDS
                        async for event in subscription:
                            await self._dispatch(gw, event)
                # Graceful close by the server: fall through and reconnect.
                logger.info("Listen stream to server %s closed by the server; reconnecting", gw.name)
            except ListenNotSupportedError:
                self._unsupported_until[gw.id] = time.monotonic() + UNSUPPORTED_REPROBE_SECONDS
                logger.info(
                    "Server %s negotiated a pre-2026 protocol; listen unsupported — scheduled auto-refresh remains its discovery path (re-probe in %.0fs)",
                    gw.name,
                    UNSUPPORTED_REPROBE_SECONDS,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-except  # SubscriptionLost, MCPError, transport errors
                logger.warning("Listen stream to server %s dropped (%s: %s); reconnecting in %.0fs", gw.name, type(exc).__name__, exc, backoff)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)

    async def _dispatch(self, gw: _GatewaySnapshot, event: object) -> None:
        """Map a typed listen event onto the debounced refresh pipeline."""
        if isinstance(event, ToolsListChanged):
            notification_type = NotificationType.TOOLS_LIST_CHANGED
        elif isinstance(event, PromptsListChanged):
            notification_type = NotificationType.PROMPTS_LIST_CHANGED
        elif isinstance(event, (ResourcesListChanged, ResourceUpdated)):
            notification_type = NotificationType.RESOURCES_LIST_CHANGED
        else:
            logger.debug("Ignoring unrecognized listen event from server %s: %s", gw.name, type(event).__name__)
            return
        logger.info("Change event %s from modern server %s", notification_type.value, gw.name)
        await self._notification_service.notify_list_changed(gw.id, notification_type)


_modern_listener_service: Optional[ModernListenerService] = None


def init_modern_listener_service(notification_service: NotificationService) -> ModernListenerService:
    """Create (or return) the process-wide ModernListenerService singleton.

    Args:
        notification_service: The initialized NotificationService whose
            debounced refresh pipeline listener events feed into.

    Returns:
        The singleton ModernListenerService instance.
    """
    global _modern_listener_service  # pylint: disable=global-statement
    if _modern_listener_service is None:
        _modern_listener_service = ModernListenerService(notification_service)
    return _modern_listener_service


def get_modern_listener_service() -> Optional[ModernListenerService]:
    """Return the singleton if initialized, else None."""
    return _modern_listener_service
