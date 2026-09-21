# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/observability_adapter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Adapter bridging ObservabilityService to the plugin framework's
ObservabilityProvider protocol.

The plugin framework defines a protocol-based ObservabilityProvider
interface so that it stays decoupled from gateway internals. This
adapter lives on the gateway side. ``ObservabilityService`` owns its
short-lived database sessions, so the executor never needs one.
"""

# Standard
import logging
from typing import Any, Dict, Optional

# First-Party
from mcpgateway.services.observability_service import ObservabilityService

logger = logging.getLogger(__name__)


class ObservabilityServiceAdapter:
    """Bridges ObservabilityService to the ObservabilityProvider protocol.

    Satisfies the ObservabilityProvider protocol via duck typing (no explicit
    inheritance needed). ``ObservabilityService`` creates an independent
    short-lived DB session for each write.
    """

    def __init__(self, service: Optional[ObservabilityService] = None):
        """Initialize the adapter.

        Args:
            service: ObservabilityService instance to wrap (creates one if not provided).
        """
        self._service = service or ObservabilityService()

    def start_span(
        self,
        trace_id: str,
        name: str,
        kind: str = "internal",
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Start a span by delegating to ObservabilityService.

        Args:
            trace_id: The trace identifier.
            name: The span name.
            kind: The span kind (e.g. "internal", "client", "server").
            resource_type: Optional resource type being traced.
            resource_name: Optional resource name being traced.
            attributes: Optional key-value attributes for the span.

        Returns:
            The span identifier, or None on failure.
        """
        try:
            return self._service.start_span(
                trace_id=trace_id,
                name=name,
                kind=kind,
                resource_type=resource_type,
                resource_name=resource_name,
                attributes=attributes,
            )
        except Exception as exc:
            logger.warning("ObservabilityServiceAdapter.start_span failed: %s", exc)
            return None

    def end_span(
        self,
        span_id: Optional[str],
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a span by delegating to ObservabilityService.

        Args:
            span_id: The span identifier returned by start_span.
            status: The span status (e.g. "ok", "error").
            attributes: Optional additional attributes to attach.
        """
        if span_id is None:
            return
        try:
            self._service.end_span(
                span_id=span_id,
                status=status,
                attributes=attributes,
            )
        except Exception as exc:
            logger.warning("ObservabilityServiceAdapter.end_span failed: %s", exc)
