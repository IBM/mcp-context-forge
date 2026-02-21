# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Observability abstractions for the plugin framework.

Provides a protocol-based interface for observability so that host
applications can inject their own tracing implementation.
"""

# Standard
from contextvars import ContextVar
from typing import Any, Dict, Optional, Protocol

# Context variable for tracking the current trace_id across async calls.
# NOTE: This is bridged from mcpgateway.services.observability_service.current_trace_id
# by ObservabilityMiddleware. Both must be set together; see the middleware for details.
current_trace_id: ContextVar[Optional[str]] = ContextVar("current_trace_id", default=None)


class ObservabilityProvider(Protocol):
    """Interface for observability - host application implements this."""

    def start_span(
        self,
        trace_id: str,
        name: str,
        kind: str = "internal",
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Start a new span within a trace.

        Args:
            trace_id: The trace identifier.
            name: The span name.
            kind: The span kind (e.g. "internal", "client", "server").
            resource_type: Optional resource type being traced.
            resource_name: Optional resource name being traced.
            attributes: Optional key-value attributes for the span.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def end_span(
        self,
        span_id: Optional[str],
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a previously started span.

        Args:
            span_id: The span identifier returned by start_span.
            status: The span status (e.g. "ok", "error").
            attributes: Optional additional attributes to attach.
        """
        ...  # pylint: disable=unnecessary-ellipsis


class NullObservability:
    """Default no-op implementation for standalone operation."""

    def start_span(  # pylint: disable=unused-argument
        self,
        trace_id: str,
        name: str,
        kind: str = "internal",
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """No-op span start for standalone operation.

        Args:
            trace_id: The trace identifier.
            name: The span name.
            kind: The span kind.
            resource_type: Optional resource type.
            resource_name: Optional resource name.
            attributes: Optional span attributes.

        Returns:
            Always None (no-op implementation).
        """
        return None

    def end_span(  # pylint: disable=unused-argument
        self,
        span_id: Optional[str],
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """No-op span end for standalone operation.

        Args:
            span_id: The span identifier.
            status: The span status.
            attributes: Optional span attributes.
        """
