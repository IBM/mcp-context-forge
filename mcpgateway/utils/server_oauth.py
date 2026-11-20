# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/server_oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Validate virtual-server OAuth trust and approval generations.
"""

# Standard
import ipaddress
import logging
from typing import Any
from urllib.parse import urlsplit

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Server

logger = logging.getLogger(__name__)


def _warn_rejected_issuer() -> None:
    """Report invalid issuer configuration without exposing URL secrets."""
    logger.warning("Ignoring invalid OAuth authorization server: URL scheme, host, or port is not permitted")


def resolve_server_oauth_issuers(config: dict[str, Any]) -> list[str]:
    """Return configured issuer URLs with permitted schemes and hosts.

    Args:
        config: Stored virtual-server OAuth configuration.

    Returns:
        Valid issuer URLs, including explicitly permitted local HTTP issuers.
    """
    values = config.get("authorization_servers") or []
    if not isinstance(values, list) or not any(isinstance(value, str) and value.strip() for value in values):
        singular = config.get("authorization_server")
        values = [singular] if isinstance(singular, str) else []
    result = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        try:
            parts = urlsplit(value)
            hostname = parts.hostname
            _ = parts.port
        except ValueError:
            _warn_rejected_issuer()
            continue
        if not parts.netloc or not hostname:
            _warn_rejected_issuer()
            continue
        if parts.scheme.lower() == "https":
            result.append(value)
        elif parts.scheme.lower() == "http" and settings.ssrf_allow_localhost:
            hostname = hostname.rstrip(".").lower()
            try:
                local = ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                local = hostname in {"localhost", "localhost.localdomain"}
            if local:
                result.append(value)
            else:
                _warn_rejected_issuer()
        else:
            _warn_rejected_issuer()
    return result


def server_oauth_is_approved(server: Any, generation: str | None = None) -> bool:
    """Check stored approval and an optional verified configuration generation.

    Args:
        server: Persisted server or equivalent security snapshot.
        generation: Generation bound to an authenticated OAuth context.

    Returns:
        Whether enabled OAuth settings retain administrator approval.
    """
    current = getattr(server, "oauth_config_generation", None)
    return bool(
        server is not None
        and getattr(server, "oauth_enabled", False) is True
        and getattr(server, "oauth_config_approved", False) is True
        and isinstance(current, str)
        and current
        and (generation is None or generation == current)
    )


def server_oauth_context_is_current(db: Session, context: dict[str, Any], server_id: str | None = None) -> bool:
    """Revalidate OAuth-derived identities before request or session dispatch.

    Args:
        db: Session for a fresh approval lookup.
        context: Trusted authenticated context, including OAuth provenance.
        server_id: Request server scope, when available.

    Returns:
        Whether independent authentication or current approved OAuth authorizes this context.
    """
    if context.get("auth_method") != "oauth_access_token":
        return True
    source = context.get("oauth_server_id")
    generation = context.get("oauth_config_generation")
    if not isinstance(source, str) or not source or not isinstance(generation, str) or not generation:
        return False
    if server_id and server_id != source:
        return False
    server = db.execute(select(Server).where(Server.id == source).execution_options(populate_existing=True)).scalar_one_or_none()
    return server_oauth_is_approved(server, generation)
