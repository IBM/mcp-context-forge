"""Gateway Worker Service for Async Lifecycle Management.

This module implements background processing for gateway lifecycle operations:
- Retry failed gateway initializations with exponential backoff
- Handle gateway deletions
- Process pending gateways

Copyright 2026
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from mcpgateway.cache.admin_stats_cache import admin_stats_cache
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import SessionLocal
from mcpgateway.observability import create_span, set_span_attribute, set_span_error
from mcpgateway.services.gateway_service import GatewayService, gateway_service, _evict_upstream_sessions_for_gateway, _get_registry_cache, _get_tool_lookup_cache
from mcpgateway.services.metrics import gateway_pending_duration, gateway_registration_attempts, gateway_registration_errors, gateway_retry_backoff, gateway_status_total
from mcpgateway.utils.passthrough_headers import invalidate_passthrough_header_caches

logger = logging.getLogger(__name__)


class GatewayWorker:
    """Background worker for gateway lifecycle operations."""

    def __init__(self):
        """Initialize the gateway worker."""
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def process_pending_gateways(self) -> None:
        """Find and process pending gateways ready for retry."""
        with SessionLocal() as db:
            try:
                now = datetime.now(timezone.utc)
                pending = (
                    db.query(DbGateway)
                    .filter(
                        DbGateway.status == "pending",
                        or_(DbGateway.next_retry_at == None, DbGateway.next_retry_at <= now),
                    )
                    .all()
                )

                for gateway in pending:
                    await self.retry_gateway_init(gateway, db)

            except Exception as e:
                logger.error(f"Error processing pending gateways: {e}", exc_info=True)

    async def retry_gateway_init(self, gateway: DbGateway, db: Session) -> None:
        """Attempt MCP initialization with exponential backoff.

        Args:
            gateway: Gateway to initialize
            db: Database session
        """
        datetime.now(timezone.utc)

        with create_span(
            "gateway.registration_retry",
            attributes={
                "gateway.name": gateway.name,
                "gateway.id": gateway.id,
                "gateway.attempt": gateway.registration_attempts + 1,
                "gateway.url": gateway.url,
            },
        ) as span:
            try:
                # Check if deleted during retry
                if gateway.status == "deleting":
                    await self.cleanup_gateway(gateway, db)
                    set_span_attribute(span, "gateway.status", "deleting")
                    return

                gateway_service = GatewayService()

                # Attempt MCP initialization
                capabilities, tools, resources, prompts, _ = await gateway_service._initialize_gateway(
                    gateway.url,
                    None,  # auth headers handled internally
                    gateway.transport,
                    gateway.auth_type,
                    gateway.oauth_config,
                    gateway.ca_certificate,
                    auth_query_params=None,
                    client_cert=gateway.client_cert,
                    client_key=gateway.client_key,
                )

                # Success: update to active
                gateway.status = "active"
                gateway.capabilities = capabilities
                gateway.registration_attempts += 1
                gateway.next_retry_at = None
                gateway.last_error = None
                gateway.status_message = "Gateway successfully initialized"

                # Store tools, resources, prompts
                gateway_service._update_or_create_tools(db, tools, gateway, "worker", update_visibility=False)
                gateway_service._update_or_create_resources(db, resources, gateway, "worker", update_visibility=False)
                gateway_service._update_or_create_prompts(db, prompts, gateway, "worker", update_visibility=False)

                db.commit()

                # Metrics: success
                gateway_status_total.labels(status="active").inc()
                gateway_registration_attempts.labels(gateway_name=gateway.name, outcome="success").inc()

                # Record pending duration
                if gateway.created_at:
                    pending_duration = (datetime.now(timezone.utc) - gateway.created_at).total_seconds()
                    gateway_pending_duration.labels(gateway_name=gateway.name).observe(pending_duration)

                # Clear backoff gauge
                gateway_retry_backoff.labels(gateway_name=gateway.name).set(0)

                # Span attributes: success
                set_span_attribute(span, "gateway.status", "active")
                set_span_attribute(span, "gateway.registration_attempts", gateway.registration_attempts)

                logger.info(
                    "gateway_registration_success",
                    extra={
                        "gateway_name": gateway.name,
                        "gateway_id": gateway.id,
                        "gateway_url": gateway.url,
                        "attempts": gateway.registration_attempts,
                        "pending_duration_seconds": pending_duration if gateway.created_at else None,
                        "status": "active",
                    },
                )

            except Exception as e:
                # Failure: increment attempts, calculate backoff
                gateway.registration_attempts += 1
                backoff_seconds = self.calculate_backoff(gateway.registration_attempts)
                gateway.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                gateway.last_error = str(e)
                gateway.status_message = f"Initialization failed: {str(e)[:200]}"

                db.commit()

                # Metrics: failure
                gateway_registration_attempts.labels(gateway_name=gateway.name, outcome="failure").inc()
                gateway_retry_backoff.labels(gateway_name=gateway.name).set(backoff_seconds)

                # Classify error type
                error_type = type(e).__name__
                gateway_registration_errors.labels(error_type=error_type).inc()

                # Span attributes: failure
                set_span_error(span, e, record_exception=True)
                set_span_attribute(span, "gateway.backoff_seconds", backoff_seconds)
                set_span_attribute(span, "gateway.next_retry_at", gateway.next_retry_at.isoformat() if gateway.next_retry_at else None)

                logger.warning(
                    "gateway_registration_failure",
                    extra={
                        "gateway_name": gateway.name,
                        "gateway_id": gateway.id,
                        "gateway_url": gateway.url,
                        "attempt": gateway.registration_attempts,
                        "backoff_seconds": backoff_seconds,
                        "next_retry_at": gateway.next_retry_at.isoformat() if gateway.next_retry_at else None,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "status": "pending",
                    },
                )

    async def cleanup_gateway(self, gateway: DbGateway, db: Session) -> None:
        """Clean up a gateway marked for deletion.

        Args:
            gateway: Gateway to delete
            db: Database session
        """
        with create_span(
            "gateway.cleanup",
            attributes={
                "gateway.name": gateway.name,
                "gateway.id": gateway.id,
                "gateway.status": "deleting",
            },
        ) as span:
            try:
                logger.info(
                    "gateway_cleanup_started",
                    extra={
                        "gateway_name": gateway.name,
                        "gateway_id": gateway.id,
                        "status": "deleting",
                    },
                )


                gateway_id = gateway.id
                gateway_url = gateway.url

                # Delete from DB first
                db.delete(gateway)
                db.commit()

                # Evict upstream sessions (#4205)
                try:
                    await _evict_upstream_sessions_for_gateway(str(gateway_id))
                except Exception as e:
                    logger.warning(f"Failed to evict upstream sessions: {e}")

                # Invalidate caches
                try:
                    cache = _get_registry_cache()
                    await cache.invalidate_gateways()
                    tool_lookup_cache = _get_tool_lookup_cache()
                    await tool_lookup_cache.invalidate_gateway(str(gateway_id))

                    await admin_stats_cache.invalidate_tags()

                    invalidate_passthrough_header_caches()
                except Exception as e:
                    logger.warning(f"Failed to invalidate caches: {e}")

                # Update tracking
                if hasattr(gateway_service, '_active_gateways'):
                    gateway_service._active_gateways.discard(gateway_url)

                # Metrics: deletion complete
                gateway_status_total.labels(status="deleted").inc()

                set_span_attribute(span, "gateway.deleted", True)

                logger.info(
                    "gateway_cleanup_complete",
                    extra={
                        "gateway_name": gateway.name,
                        "gateway_id": gateway.id,
                    },
                )
            except Exception as e:
                logger.error(
                    "gateway_cleanup_error",
                    extra={
                        "gateway_name": gateway.name,
                        "gateway_id": gateway.id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )
                db.rollback()
                set_span_error(span, e, record_exception=True)

    def calculate_backoff(self, attempt: int) -> int:
        """Calculate exponential backoff delay.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Backoff delay in seconds (max 300s)
        """
        return min(2**attempt, 300)

    async def run_forever(self) -> None:
        """Poll for pending gateways every 5 seconds."""
        self._running = True
        logger.info("Gateway worker started")

        while self._running:
            try:
                await self.process_pending_gateways()
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)

            await asyncio.sleep(5)

        logger.info("Gateway worker stopped")

    def stop(self) -> None:
        """Stop the worker loop."""
        self._running = False

    async def wait_for_completion(self, timeout: int = 30) -> None:
        """Wait for current work to complete.

        Args:
            timeout: Maximum seconds to wait
        """
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Worker did not complete within {timeout}s")


# Global worker instance
_worker_instance: Optional[GatewayWorker] = None


def get_worker() -> GatewayWorker:
    """Get or create the global worker instance."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = GatewayWorker()
    return _worker_instance
