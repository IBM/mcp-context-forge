# -*- coding: utf-8 -*-
"""Request-scoped context variables shared across transports and services.

These ``ContextVar``s are populated by the transport layer (primarily
``streamablehttp_transport``) and read by service-layer code that needs
request-scoped metadata without taking a dependency on the transport module.
Keeping them in a neutral module breaks the cycle that otherwise exists
between ``mcpgateway.services.*`` and
``mcpgateway.transports.streamablehttp_transport``.

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

# Future
from __future__ import annotations

# Standard
import contextvars
from datetime import datetime
from typing import Any, Dict, Optional

# Third-Party
from pydantic import BaseModel, Field

# Per-request HTTP headers. Set by the streamable-http ASGI layer before
# dispatching into business logic; read by anything that needs the caller's
# downstream ``Mcp-Session-Id``, passthrough headers, etc.
request_headers_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("request_headers", default={})

# Authenticated user context for the current request. Mirrors the headers
# ContextVar — transport layer fills it, service layer reads it.
user_context_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("user_context", default={})


class UserContext(BaseModel):
    """Authenticated user identity context for propagation to upstream servers and plugins."""

    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_admin: bool = False
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    team_id: Optional[str] = None
    teams: Optional[list[str]] = None
    department: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    auth_method: Optional[str] = None
    authenticated_at: Optional[datetime] = None
    service_account: Optional[str] = None
    delegation_chain: list[str] = Field(default_factory=list)


user_identity_var: contextvars.ContextVar[Optional[UserContext]] = contextvars.ContextVar("user_identity", default=None)
