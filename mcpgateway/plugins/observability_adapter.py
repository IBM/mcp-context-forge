# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/observability_adapter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Adapter bridging ObservabilityService to the plugin framework's
ObservabilityProvider protocol.

The plugin framework defines a protocol-based ObservabilityProvider
interface so that it stays decoupled from gateway internals. This
adapter lives on the gateway side, wrapping ObservabilityService
with its own database sessions so the executor can call
start_span/end_span without needing a db parameter.
"""

# Standard
import logging
from typing import Any, Dict, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import SessionLocal
from mcpgateway.services.observability_service import ObservabilityService

logger = logging.getLogger(__name__)


class ObservabilityServiceAdapter:
    """Bridges ObservabilityService to the ObservabilityProvider protocol.

    Satisfies the ObservabilityProvider protocol via duck typing (no explicit
    inheritance needed). Each call creates its own short-lived DB session,
    matching the pattern used in observability_middleware.py.
    """

    def __init__(self, service: Optional[ObservabilityService] = None):
        """Initialize the adapter.

        Args:
            service: ObservabilityService instance to wrap (creates one if not provided).
        """
        self._service = service or ObservabilityService()

    def _make_session(self) -> Session:
        """Create a fresh DB session for observability writes.

        Returns:
            A new SQLAlchemy session.
        """
        return SessionLocal()

    def start_span(
        self,
        trace_id: str,
        name: str,
        kind: str = "internal",
        resource_type: Optional[str] = None,
        resource_name: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Start a span by delegating to ObservabilityService with a fresh DB session.

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
        db: Optional[Session] = None
        try:
            db = self._make_session()
            return self._service.start_span(
                db=db,
                trace_id=trace_id,
                name=name,
                kind=kind,
                resource_type=resource_type,
                resource_name=resource_name,
                attributes=attributes,
            )
        except Exception as exc:
            logger.warning("ObservabilityServiceAdapter.start_span failed: %s", exc)
            if db:
                try:
                    db.rollback()
                except Exception:  # nosec B110
                    pass
            return None
        finally:
            if db:
                try:
                    db.close()
                except Exception:  # nosec B110
                    pass

    def end_span(
        self,
        span_id: Optional[str],
        status: str = "ok",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """End a span by delegating to ObservabilityService with a fresh DB session.

        Args:
            span_id: The span identifier returned by start_span.
            status: The span status (e.g. "ok", "error").
            attributes: Optional additional attributes to attach.
        """
        if span_id is None:
            return
        db: Optional[Session] = None
        try:
            db = self._make_session()
            self._service.end_span(
                db=db,
                span_id=span_id,
                status=status,
                attributes=attributes,
            )
        except Exception as exc:
            logger.warning("ObservabilityServiceAdapter.end_span failed: %s", exc)
            if db:
                try:
                    db.rollback()
                except Exception:  # nosec B110
                    pass
        finally:
            if db:
                try:
                    db.close()
                except Exception:  # nosec B110
                    pass
