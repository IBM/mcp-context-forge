# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/workers/gateway_worker.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Background worker for asynchronous gateway lifecycle operations.

This module implements the background worker that processes pending gateway
operations (create, update, delete) with retry logic and observability.
"""

# Standard
import asyncio
from datetime import timedelta, timezone
import logging
import signal
import threading
import time
from typing import Any, Dict, List, Optional

# Third-Party
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import SessionLocal, utc_now
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.observability_service import ObservabilityService
from mcpgateway.services.structured_logger import get_structured_logger

logger = logging.getLogger(__name__)
structured_logger = get_structured_logger("gateway_worker")


class GatewayWorker:
    """Background worker for processing pending gateway operations.
    
    Handles asynchronous gateway lifecycle operations with retry logic,
    exponential backoff, and graceful shutdown support.
    """

    def __init__(self):
        """Initialize the gateway worker."""
        self.shutdown_requested = False
        self.worker_thread: Optional[threading.Thread] = None
        self.gateway_service = GatewayService()
        self.observability = ObservabilityService()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def handle_signal(signum: int, frame: Any) -> None:  # pylint: disable=unused-argument
            """Handle shutdown signals."""
            logger.info(f"Received shutdown signal {signum}, requesting graceful shutdown")
            structured_logger.info("worker.shutdown_requested", signal=signum)
            self.shutdown_requested = True
        
        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

    def start(self) -> None:
        """Start the background worker thread."""
        if self.worker_thread and self.worker_thread.is_alive():
            logger.warning("Gateway worker already running")
            return

        self.shutdown_requested = False
        self.worker_thread = threading.Thread(target=self._run_worker_loop, daemon=False, name="GatewayWorker")
        self.worker_thread.start()
        logger.info("Gateway worker started")
        structured_logger.info("worker.started", poll_interval=settings.gateway_worker_poll_interval_seconds, batch_size=settings.gateway_worker_batch_size)

    def stop(self) -> None:
        """Stop the background worker thread gracefully."""
        if not self.worker_thread or not self.worker_thread.is_alive():
            logger.warning("Gateway worker not running")
            return

        logger.info("Stopping gateway worker...")
        structured_logger.info("worker.stopping")
        self.shutdown_requested = True

        # Wait for worker thread to complete current cycle
        if self.worker_thread:
            self.worker_thread.join(timeout=30)
            if self.worker_thread.is_alive():
                logger.warning("Gateway worker did not stop within timeout")
                structured_logger.warning("worker.stop_timeout")
            else:
                logger.info("Gateway worker stopped")
                structured_logger.info("worker.stopped")

    def _run_worker_loop(self) -> None:
        """Main worker loop that processes pending gateways."""
        logger.info("Gateway worker loop started")
        
        while not self.shutdown_requested:
            try:
                # Process pending gateways
                asyncio.run(self._process_pending_gateways())
                
                # Log cycle completion
                structured_logger.debug("worker.cycle_completed")
                
            except Exception as e:
                logger.error(f"Error in gateway worker loop: {e}", exc_info=True)
                structured_logger.error("worker.cycle_error", error=e)
            
            # Sleep between cycles (check shutdown flag more frequently)
            for _ in range(settings.gateway_worker_poll_interval_seconds):
                if self.shutdown_requested:
                    break
                time.sleep(1)
        
        logger.info("Gateway worker loop exited")
        structured_logger.info("worker.loop_exited")

    async def _process_pending_gateways(self) -> None:
        """Process batch of pending gateways."""
        with SessionLocal() as db:
            # Claim pending gateways
            gateways = self._claim_pending_gateways(db, settings.gateway_worker_batch_size)
            
            if not gateways:
                return
            
            logger.info(f"Processing {len(gateways)} pending gateways")
            structured_logger.info("worker.batch_claimed", count=len(gateways))
            
            # Record metric
            if settings.observability_enabled:
                self.observability.record_metric(
                    name="gateway_worker_claimed_total",
                    value=len(gateways),
                    metric_type="counter"
                )
            
            # Process each gateway
            for gateway in gateways:
                if self.shutdown_requested:
                    logger.info("Shutdown requested, stopping gateway processing")
                    break
                
                try:
                    await self._process_gateway(db, gateway)
                except Exception as e:
                    logger.error(f"Error processing gateway {gateway.name}: {e}", exc_info=True)
                    structured_logger.error("worker.gateway_error", gateway_name=gateway.name, error=e)

    def _claim_pending_gateways(self, db: Session, batch_size: int) -> List[DbGateway]:
        """Claim pending gateways for processing.
        
        Uses database-specific locking to prevent concurrent processing:
        - PostgreSQL: FOR UPDATE SKIP LOCKED
        - SQLite: Simple SELECT with status re-check
        
        Args:
            db: Database session
            batch_size: Maximum number of gateways to claim
            
        Returns:
            List of claimed gateway objects
        """
        try:
            now = utc_now()
            dialect_name = db.bind.dialect.name if db.bind else "sqlite"
            
            # Build base query for pending gateways ready for retry
            query = select(DbGateway).where(
                and_(
                    DbGateway.status.in_(["pending", "deleting"]),
                    or_(
                        DbGateway.next_retry_at.is_(None),
                        DbGateway.next_retry_at <= now
                    )
                )
            ).order_by(
                # Fairness: process oldest pending operations first
                DbGateway.next_retry_at.asc().nullsfirst(),
                DbGateway.created_at.asc()
            ).limit(batch_size)
            
            # PostgreSQL: Use FOR UPDATE SKIP LOCKED for efficient locking
            if dialect_name == "postgresql":
                query = query.with_for_update(skip_locked=True)
                gateways = list(db.execute(query).scalars().all())
                logger.debug(f"Claimed {len(gateways)} gateways using FOR UPDATE SKIP LOCKED")
            else:
                # SQLite: Simple SELECT, rely on status re-check for safety
                gateways = list(db.execute(query).scalars().all())
                logger.debug(f"Claimed {len(gateways)} gateways using optimistic locking")
            
            return gateways
            
        except Exception as e:
            logger.error(f"Error claiming gateways: {e}", exc_info=True)
            raise

    async def _process_gateway(self, db: Session, gateway: DbGateway) -> None:
        """Process a single gateway operation.
        
        Args:
            db: Database session
            gateway: Gateway to process
        """
        try:
            # Re-check status (race condition protection)
            if not self._check_gateway_status(db, gateway):
                return
            
            if gateway.status == "deleting":
                await self._handle_deleting_gateway(db, gateway)
            elif gateway.status == "pending":
                await self._handle_pending_gateway(db, gateway)
            
        except Exception as e:
            logger.error(f"Error processing gateway {gateway.name}: {e}", exc_info=True)
            raise

    def _check_gateway_status(self, db: Session, gateway: DbGateway) -> bool:
        """Check gateway status before processing.
        
        Re-reads gateway from database to detect concurrent modifications.
        
        Args:
            db: Database session
            gateway: Gateway to check
            
        Returns:
            True if gateway should be processed, False if status changed
        """
        try:
            # Refresh from database
            db.refresh(gateway)
            
            if gateway.status not in ["pending", "deleting"]:
                logger.info(f"Gateway {gateway.name} status changed to {gateway.status}, skipping")
                structured_logger.info("worker.status_changed", gateway_name=gateway.name, new_status=gateway.status)
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking gateway status: {e}", exc_info=True)
            raise

    async def _handle_pending_gateway(self, db: Session, gateway: DbGateway) -> None:
        """Handle pending gateway registration/update.
        
        Args:
            db: Database session
            gateway: Gateway in pending status
        """
        try:
            # Attempt MCP initialization
            result = await self._initialize_gateway(gateway)
            
            # Double status check after MCP operation (race prevention)
            db.refresh(gateway)
            
            if gateway.status == "deleting":
                # Gateway was deleted during MCP operation
                logger.info(f"Gateway {gateway.name} marked for deletion during initialization, cleaning up")
                structured_logger.info("worker.deleted_during_init", gateway_name=gateway.name)
                await self._cleanup_gateway(gateway)
                db.delete(gateway)
                db.commit()
            elif gateway.status == "pending":
                # Success - update to active
                await self._handle_success(db, gateway, result)
            
        except Exception as e:
            self._handle_failure(db, gateway, e)

    async def _handle_deleting_gateway(self, db: Session, gateway: DbGateway) -> None:
        """Handle gateway deletion.
        
        Args:
            db: Database session
            gateway: Gateway in deleting status
        """
        try:
            # Perform cleanup
            await self._cleanup_gateway(gateway)
            
            # Delete from database
            db.delete(gateway)
            db.commit()
            
            logger.info(f"Gateway {gateway.name} deleted successfully")
            structured_logger.info("worker.gateway_deleted", gateway_name=gateway.name)
            
            # Record metric
            if settings.observability_enabled:
                self.observability.record_metric(
                    name="gateway_deletions_total",
                    value=1,
                    metric_type="counter"
                )
            
        except Exception as e:
            logger.error(f"Error deleting gateway {gateway.name}: {e}", exc_info=True)
            structured_logger.error("worker.delete_error", gateway_name=gateway.name, error=e)

    async def _initialize_gateway(self, gateway: DbGateway) -> Dict[str, Any]:
        """Initialize gateway via MCP.
        
        Calls shared service method for MCP initialization.
        
        Args:
            gateway: Gateway to initialize
            
        Returns:
            dict: Capabilities and entities from MCP
            
        Raises:
            Exception: If MCP initialization fails
        """
        try:
            # Task 28: Add span for MCP initialization
            trace_id = getattr(gateway, 'trace_id', None)
            if settings.observability_enabled and trace_id:
                with self.observability.trace_span(
                    trace_id=trace_id,
                    name="mcp.initialize",
                    attributes={
                        "gateway.name": gateway.name,
                        "gateway.url": gateway.url,
                        "gateway.transport": gateway.transport,
                    }
                ) as span_id:
                    try:
                        result = await self.gateway_service._perform_gateway_registration(gateway)  # pylint: disable=protected-access
                        return result
                    except Exception as e:
                        # Task 29: Add error event
                        self.observability.add_event(
                            span_id=span_id,
                            name="error",
                            severity="error",
                            message=f"MCP initialization failed: {str(e)[:200]}",
                            exception_type=type(e).__name__,
                            exception_message=str(e)[:500],
                            attributes={
                                "gateway.name": gateway.name,
                                "error_type": type(e).__name__,
                            }
                        )
                        raise
            else:
                result = await self.gateway_service._perform_gateway_registration(gateway)  # pylint: disable=protected-access
                return result
            
        except Exception as e:
            logger.error(f"MCP initialization failed for {gateway.name}: {e}", exc_info=True)
            raise

    async def _handle_success(self, db: Session, gateway: DbGateway, result: Dict[str, Any]) -> None:
        """Handle successful gateway initialization.
        
        Args:
            db: Database session
            gateway: Gateway that was initialized
            result: Result from MCP initialization
        """
        try:
            now = utc_now()
            
            # Calculate pending duration
            if gateway.created_at:
                created_at = gateway.created_at if gateway.created_at.tzinfo else gateway.created_at.replace(tzinfo=timezone.utc)
                pending_duration_seconds = (now - created_at).total_seconds()
            else:
                pending_duration_seconds = 0
            
            # Task 28: Add span for status update
            trace_id = getattr(gateway, 'trace_id', None)
            if settings.observability_enabled and trace_id:
                with self.observability.trace_span(
                    trace_id=trace_id,
                    name="status.update",
                    attributes={
                        "gateway.name": gateway.name,
                        "old_status": gateway.status,
                        "new_status": "active",
                    }
                ) as span_id:
                    # Update gateway to active
                    gateway.status = "active"
                    gateway.status_message = "Gateway active"
                    gateway.status_updated_at = now
                    gateway.capabilities = result.get("capabilities", {})
                    
                    # Clear retry metadata
                    attempts = gateway.registration_attempts
                    gateway.registration_attempts = 0
                    gateway.next_retry_at = None
                    gateway.last_error = None
                    
                    db.commit()
                    
                    # Task 29: Add event for status change
                    self.observability.add_event(
                        span_id=span_id,
                        name="status.changed",
                        severity="info",
                        message=f"Gateway {gateway.name} status changed from pending to active",
                        attributes={
                            "gateway.name": gateway.name,
                            "old_status": "pending",
                            "new_status": "active",
                            "attempts": attempts,
                        }
                    )
            else:
                # Update gateway to active
                gateway.status = "active"
                gateway.status_message = "Gateway active"
                gateway.status_updated_at = now
                gateway.capabilities = result.get("capabilities", {})
                
                # Clear retry metadata
                attempts = gateway.registration_attempts
                gateway.registration_attempts = 0
                gateway.next_retry_at = None
                gateway.last_error = None
                
                db.commit()
            
            logger.info(f"Gateway {gateway.name} activated successfully after {attempts} attempts")
            structured_logger.info("worker.gateway_activated", gateway_name=gateway.name, attempts=attempts, pending_duration_seconds=pending_duration_seconds)
            
            # Record metrics (no per-gateway labels for cardinality control)
            if settings.observability_enabled:
                self.observability.record_metric(
                    name="gateway_activations_total",
                    value=1,
                    metric_type="counter"
                )
                self.observability.record_metric(
                    name="gateway_status_active",
                    value=1,
                    metric_type="gauge"
                )
                self.observability.record_metric(
                    name="gateway_pending_duration_seconds",
                    value=pending_duration_seconds,
                    metric_type="histogram"
                )
                # Task 30: Add missing gateway_registration_attempts histogram
                self.observability.record_metric(
                    name="gateway_registration_attempts",
                    value=attempts,
                    metric_type="histogram"
                )
            
        except Exception as e:
            logger.error(f"Error updating gateway to active: {e}", exc_info=True)
            raise

    def _handle_failure(self, db: Session, gateway: DbGateway, error: Exception) -> None:
        """Handle failed gateway initialization.
        
        Implements exponential backoff retry logic.
        
        Args:
            db: Database session
            gateway: Gateway that failed
            error: Exception that occurred
        """
        try:
            # Increment attempts
            gateway.registration_attempts += 1
            
            # Calculate backoff
            backoff_seconds = self._calculate_backoff(gateway.registration_attempts)
            gateway.next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
            
            # Store error (truncate for database, internal only)
            gateway.last_error = str(error)[:1000]
            
            # Update status message (user-facing)
            gateway.status_message = f"Retrying after error (attempt {gateway.registration_attempts})"
            gateway.status_updated_at = utc_now()
            
            # Keep status as pending for retry
            db.commit()
            
            logger.warning(f"Gateway {gateway.name} initialization failed (attempt {gateway.registration_attempts}), retrying in {backoff_seconds}s: {error}")
            structured_logger.warning(
                "worker.gateway_retry",
                gateway_name=gateway.name,
                attempts=gateway.registration_attempts,
                backoff_seconds=backoff_seconds,
                error=str(error)[:200]
            )
            
            # Task 29: Add retry event
            trace_id = getattr(gateway, 'trace_id', None)
            if settings.observability_enabled and trace_id:
                with self.observability.trace_span(
                    trace_id=trace_id,
                    name="retry.attempt",
                    attributes={
                        "gateway.name": gateway.name,
                        "attempt": gateway.registration_attempts,
                        "backoff_seconds": backoff_seconds,
                    }
                ) as span_id:
                    self.observability.add_event(
                        span_id=span_id,
                        name="retry.attempt",
                        severity="warning",
                        message=f"Gateway {gateway.name} retry attempt {gateway.registration_attempts} scheduled in {backoff_seconds}s",
                        attributes={
                            "gateway.name": gateway.name,
                            "attempt": gateway.registration_attempts,
                            "backoff_seconds": backoff_seconds,
                            "error": str(error)[:200],
                        }
                    )
            
            # Record metrics
            if settings.observability_enabled:
                self.observability.record_metric(
                    name="gateway_registration_errors_total",
                    value=1,
                    metric_type="counter"
                )
            
        except Exception as e:
            logger.error(f"Error handling gateway failure: {e}", exc_info=True)
            raise

    def _calculate_backoff(self, attempts: int) -> int:
        """Calculate exponential backoff delay.
        
        Formula: min(2 ** (attempts - 1), 300)
        Results in: 1s, 2s, 4s, 8s, 16s, 32s, 64s, 128s, 256s, 300s (capped)
        
        Args:
            attempts: Number of attempts made
            
        Returns:
            Backoff delay in seconds
        """
        if attempts <= 0:
            return 1
        
        # Exponential backoff with 300s cap
        backoff = min(2 ** (attempts - 1), 300)
        return backoff

    async def _cleanup_gateway(self, gateway: DbGateway) -> None:
        """Cleanup gateway resources.
        
        Calls shared service method for MCP cleanup.
        Best-effort - logs errors but doesn't raise.
        
        Args:
            gateway: Gateway to cleanup
        """
        try:
            # Task 28: Add span for cleanup operation
            trace_id = getattr(gateway, 'trace_id', None)
            if settings.observability_enabled and trace_id:
                with self.observability.trace_span(
                    trace_id=trace_id,
                    name="mcp.cleanup",
                    attributes={
                        "gateway.name": gateway.name,
                        "gateway.url": gateway.url,
                    }
                ):
                    await self.gateway_service._perform_gateway_cleanup(gateway)  # pylint: disable=protected-access
            else:
                await self.gateway_service._perform_gateway_cleanup(gateway)  # pylint: disable=protected-access
            
        except Exception as e:
            # Best-effort cleanup - log but don't raise
            logger.warning(f"Gateway cleanup error (non-fatal): {e}")
            structured_logger.warning("worker.cleanup_error", gateway_name=gateway.name, error=str(e))

# Made with Bob
