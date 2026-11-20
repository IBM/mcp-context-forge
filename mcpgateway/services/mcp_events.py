#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authenticated MCP Events provider registration.

Location: ./mcpgateway/services/mcp_events.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Providers own event authorization, durable subscriptions, callback verification,
secret custody, expiration, revocation, and delivery. Registration grants none
of those rights. The gateway dispatches only authenticated protocol requests.
"""

# Future
from __future__ import annotations

# Standard
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

# Third-Party
from mcp_types import RequestParams
from pydantic import ConfigDict

EVENT_METHOD_PERMISSIONS = {
    "events/list": "events.read",
    "events/subscribe": "events.subscribe",
    "events/unsubscribe": "events.unsubscribe",
}


class EventRequestParams(RequestParams):
    """Preserve provider-owned arguments without logging validation input."""

    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)


@dataclass(frozen=True)
class EventRequestContext:
    """Current transport authority passed to one provider request.

    Providers must verify the original caller through their existing authority.
    Providers must not store this context as standing delivery authorization.
    """

    server_id: str
    user: Mapping[str, Any] = field(repr=False)
    headers: Mapping[str, Any] = field(repr=False)


class EventProvider(Protocol):
    """A virtual server's trusted application event owner."""

    async def authorize(self, context: EventRequestContext, method: str) -> bool:
        """Check current event-owner rights without creating a subscription.

        Args:
            context: Current authenticated transport context.
            method: Exact Events method requiring authorization.

        Returns:
            Whether the event owner permits this method for this caller.
        """

    async def request(self, context: EventRequestContext, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Handle one request under fresh original-caller authorization.

        Recheck authorization before subscription commits and all deliveries.
        Never substitute a privileged service account for the original caller.
        Verify public HTTPS callbacks before activation. Keep signing secrets
        in protected durable custody. Do not log request parameters.

        Args:
            context: Current authenticated transport context.
            method: Exact Events method to handle.
            params: Protocol parameters, including provider-owned arguments.

        Returns:
            The MCP Events method result, without credentials.
        """


_providers: dict[str, EventProvider] = {}


@contextmanager
def event_provider(server_id: str, provider: EventProvider) -> Generator[None, None, None]:
    """Bind one provider during trusted application startup and release it.

    This is not a remotely callable registration or authorization operation.
    Register providers on every worker through the application lifespan.

    Args:
        server_id: Exact virtual server identity.
        provider: Its application event owner.

    Yields:
        Nothing while the provider is registered.

    Raises:
        ValueError: If the identity is empty or already registered.
    """
    if not server_id or server_id.strip() != server_id or server_id in _providers:
        raise ValueError("One event provider per exact virtual server is required")
    _providers[server_id] = provider
    try:
        yield
    finally:
        if _providers.get(server_id) is provider:
            del _providers[server_id]


def get_event_provider(server_id: str) -> EventProvider | None:
    """Read the exact registered event owner without global fallback.

    Args:
        server_id: Exact virtual server identity.

    Returns:
        The registered provider, if any.
    """
    return _providers.get(server_id)
