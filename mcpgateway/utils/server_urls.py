# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/server_urls.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

APP_DOMAIN-derived URL construction for virtual servers.

Kept as a standalone leaf module (only mcpgateway.config as a dependency) so
it can be imported from low-level modules like services/server_service.py
without pulling in transports/streamablehttp_transport.py's own import graph,
which reaches back into middleware/auth and would otherwise form a circular
import (server_service -> streamablehttp_transport -> middleware.rbac ->
middleware -> middleware.token_scoping -> auth -> ... -> services ->
gateway_service -> server_service).
"""

# Standard
import logging

# First-Party
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


def build_server_mcp_url(server_id: str) -> str:
    """Construct the canonical, fully-qualified MCP endpoint URL for a virtual server.

    This URL is also the RFC 8707 OAuth resource/audience identifier used for
    token validation and persisted learned audiences. Keep its path format
    stable; a future display-only path change must use a separate function so
    existing OAuth tokens and persisted audiences remain valid.

    .. important::
        The base URL is derived from :data:`settings.app_domain`, **not** any
        inbound ``Host`` / ``X-Forwarded-Host`` header. Both are
        caller-controlled (any client can send an arbitrary ``Host``; a
        permissive proxy can forward one too), so trusting them here would
        let a client spoof the URL a caller is told to use.
        ``settings.app_domain`` is operator-set at deployment time and
        therefore a safe trust anchor. Operators MUST set it to the gateway's
        public URL for the returned URL to actually be reachable.

    Args:
        server_id: Virtual-server identifier.

    Returns:
        Fully-qualified MCP endpoint URL string, or ``""`` if
        ``settings.app_domain`` isn't a usable URL.
    """
    try:
        raw = str(settings.app_domain).rstrip("/")
    except (AttributeError, ValueError) as exc:
        logger.warning("settings.app_domain is not a usable URL: %s: %s", type(exc).__name__, exc)
        return ""
    if not raw:
        return ""
    return f"{raw}/servers/{server_id}/mcp"


def build_server_display_url(server_id: str) -> str:
    """Construct the human-facing, actually-reachable MCP endpoint URL for a virtual server.

    :func:`build_server_mcp_url` deliberately omits ``settings.app_root_path``
    because its output is also the RFC 8707/9728 OAuth resource/audience
    identifier, whose path shape must stay stable for already-issued tokens
    and persisted audiences. That omission makes it unusable as-is for
    display purposes: when the gateway is reverse-proxied under a subpath
    (``APP_ROOT_PATH=/gateway``), the URL a user is shown or copies into
    their MCP client config must include that prefix to actually resolve.

    Use this helper anywhere the URL is shown to a user or copied into
    client config (e.g. ``ServerRead.url``); use
    :func:`build_server_mcp_url` anywhere the value participates in OAuth
    resource binding or audience validation.

    Args:
        server_id: Virtual-server identifier.

    Returns:
        Fully-qualified, reachable MCP endpoint URL string, or ``""`` if
        ``settings.app_domain`` isn't a usable URL.
    """
    try:
        raw = str(settings.app_domain).rstrip("/")
    except (AttributeError, ValueError) as exc:
        logger.warning("settings.app_domain is not a usable URL: %s: %s", type(exc).__name__, exc)
        return ""
    if not raw:
        return ""
    root_path = str(getattr(settings, "app_root_path", "") or "").strip("/")
    base = f"{raw}/{root_path}" if root_path else raw
    return f"{base}/servers/{server_id}/mcp"
