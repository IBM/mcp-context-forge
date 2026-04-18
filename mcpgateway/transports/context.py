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
from typing import Any, Dict

# Per-request HTTP headers. Set by the streamable-http ASGI layer before
# dispatching into business logic; read by anything that needs the caller's
# downstream ``Mcp-Session-Id``, passthrough headers, etc.
request_headers_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("request_headers", default={})

# Authenticated user context for the current request. Mirrors the headers
# ContextVar — transport layer fills it, service layer reads it.
user_context_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("user_context", default={})
