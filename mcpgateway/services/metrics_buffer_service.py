# -*- coding: utf-8 -*-
"""Buffered metrics service for batching metric writes to the database.

This service accumulates metrics in memory and flushes them to the database
periodically, reducing DB write pressure under high load.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
"""

# Standard
import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Deque, Optional

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import A2AAgentMetric, fresh_db_session, PromptMetric, ResourceMetric, ServerMetric, ToolMetric

logger = logging.getLogger(__name__)


@dataclass
class BufferedToolMetric:
    """Buffered tool metric entry."""

    tool_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    error_message: Optional[str] = None


@dataclass
class BufferedResourceMetric:
    """Buffered resource metric entry."""

    resource_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    error_message: Optional[str] = None


@dataclass
class BufferedPromptMetric:
    """Buffered prompt metric entry."""

    prompt_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    error_message: Optional[str] = None


@dataclass
class BufferedServerMetric:
    """Buffered server metric entry."""

    server_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    error_message: Optional[str] = None


@dataclass
class BufferedA2AAgentMetric:
    """Buffered A2A agent metric entry."""

    a2a_agent_id: str
    timestamp: datetime
    response_time: float
    is_success: bool
    interaction_type: str = "invoke"
    error_message: Optional[str] = None


class MetricsBufferService:
    """Service for buffering and batching metrics writes to the database.

    This service provides:
    - Thread-safe buffering of tool, resource, prompt, server, and A2A agent metrics
    - Periodic flushing to database (configurable interval)
    - Graceful shutdown with final flush

    Configuration (via environment variables):
    - METRICS_BUFFER_ENABLED: Enable buffered metrics (default: True)
    - METRICS_BUFFER_FLUSH_INTERVAL: Seconds between flushes (default: 60)
    - METRICS_BUFFER_MAX_SIZE: Max entries before forced flush (default: 1000)
    """

    def __init__(
        self,
        flush_interval: Optional[int] = None,
        max_buffer_size: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the metrics buffer service.

        Args:
            flush_interval: Seconds between automatic flushes (default: from settings or 60)
            max_buffer_size: Maximum buffer entries before forced flush (default: from settings or 1000)
            enabled: Whether buffering is enabled (default: from settings or True)
        """
        self.flush_interval = flush_interval or getattr(settings, "metrics_buffer_flush_interval", 60)
        self.max_buffer_size = max_buffer_size or getattr(settings, "metrics_buffer_max_size", 1000)
        self.enabled = enabled if enabled is not None else getattr(settings, "metrics_buffer_enabled", True)

        # Thread-safe buffers using deque with locks
        self._tool_metrics: Deque[BufferedToolMetric] = deque()
        self._resource_metrics: Deque[BufferedResourceMetric] = deque()
        self._prompt_metrics: Deque[BufferedPromptMetric] = deque()
        self._server_metrics: Deque[BufferedServerMetric] = deque()
        self._a2a_agent_metrics: Deque[BufferedA2AAgentMetric] = deque()
        self._lock = threading.Lock()

        # Background flush task
        self._flush_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Stats for monitoring
        self._total_buffered = 0
        self._total_flushed = 0
        self._flush_count = 0

        logger.info(f"MetricsBufferService initialized: enabled={self.enabled}, " f"flush_interval={self.flush_interval}s, max_buffer_size={self.max_buffer_size}")

    async def start(self) -> None:
        """Start the background flush task."""
        if not self.enabled:
            logger.info("MetricsBufferService disabled, skipping start")
            return

        if self._flush_task is None or self._flush_task.done():
            self._shutdown_event.clear()
            self._flush_task = asyncio.create_task(self._flush_loop())
            logger.info("MetricsBufferService flush task started")

    async def shutdown(self) -> None:
        """Shutdown service with final flush."""
        logger.info("MetricsBufferService shutting down...")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel the flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush to persist any remaining metrics
        await self._flush_all()

        logger.info(f"MetricsBufferService shutdown complete: " f"total_buffered={self._total_buffered}, total_flushed={self._total_flushed}, " f"flush_count={self._flush_count}")

    def record_tool_metric(
        self,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer a tool metric for later flush.

        Args:
            tool_id: The UUID string of the tool.
            start_time: The monotonic start time of the invocation.
            success: True if the invocation succeeded.
            error_message: Error message if failed.
        """
        if not self.enabled:
            # Fall back to immediate write
            self._write_tool_metric_immediately(tool_id, start_time, success, error_message)
            return

        metric = BufferedToolMetric(
            tool_id=tool_id,
            timestamp=datetime.now(timezone.utc),
            response_time=time.monotonic() - start_time,
            is_success=success,
            error_message=error_message,
        )

        with self._lock:
            self._tool_metrics.append(metric)
            self._total_buffered += 1

    def record_resource_metric(
        self,
        resource_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer a resource metric for later flush.

        Args:
            resource_id: UUID of the resource.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        if not self.enabled:
            self._write_resource_metric_immediately(resource_id, start_time, success, error_message)
            return

        metric = BufferedResourceMetric(
            resource_id=resource_id,
            timestamp=datetime.now(timezone.utc),
            response_time=time.monotonic() - start_time,
            is_success=success,
            error_message=error_message,
        )

        with self._lock:
            self._resource_metrics.append(metric)
            self._total_buffered += 1

    def record_prompt_metric(
        self,
        prompt_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer a prompt metric for later flush.

        Args:
            prompt_id: UUID of the prompt.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        if not self.enabled:
            self._write_prompt_metric_immediately(prompt_id, start_time, success, error_message)
            return

        metric = BufferedPromptMetric(
            prompt_id=prompt_id,
            timestamp=datetime.now(timezone.utc),
            response_time=time.monotonic() - start_time,
            is_success=success,
            error_message=error_message,
        )

        with self._lock:
            self._prompt_metrics.append(metric)
            self._total_buffered += 1

    def record_server_metric(
        self,
        server_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer a server metric for later flush.

        Args:
            server_id: UUID of the server.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        if not self.enabled:
            self._write_server_metric_immediately(server_id, start_time, success, error_message)
            return

        metric = BufferedServerMetric(
            server_id=server_id,
            timestamp=datetime.now(timezone.utc),
            response_time=time.monotonic() - start_time,
            is_success=success,
            error_message=error_message,
        )

        with self._lock:
            self._server_metrics.append(metric)
            self._total_buffered += 1

    def record_a2a_agent_metric(
        self,
        a2a_agent_id: str,
        start_time: float,
        success: bool,
        interaction_type: str = "invoke",
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer an A2A agent metric for later flush.

        Args:
            a2a_agent_id: UUID of the A2A agent.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            interaction_type: Type of interaction (e.g., "invoke").
            error_message: Optional error message if failed.
        """
        if not self.enabled:
            self._write_a2a_agent_metric_immediately(a2a_agent_id, start_time, success, interaction_type, error_message)
            return

        metric = BufferedA2AAgentMetric(
            a2a_agent_id=a2a_agent_id,
            timestamp=datetime.now(timezone.utc),
            response_time=time.monotonic() - start_time,
            is_success=success,
            interaction_type=interaction_type,
            error_message=error_message,
        )

        with self._lock:
            self._a2a_agent_metrics.append(metric)
            self._total_buffered += 1

    def record_a2a_agent_metric_with_duration(
        self,
        a2a_agent_id: str,
        response_time: float,
        success: bool,
        interaction_type: str = "invoke",
        error_message: Optional[str] = None,
    ) -> None:
        """Buffer an A2A agent metric with pre-calculated response time.

        Args:
            a2a_agent_id: UUID of the A2A agent.
            response_time: Pre-calculated response time in seconds.
            success: Whether the operation succeeded.
            interaction_type: Type of interaction (e.g., "invoke").
            error_message: Optional error message if failed.
        """
        if not self.enabled:
            self._write_a2a_agent_metric_with_duration_immediately(a2a_agent_id, response_time, success, interaction_type, error_message)
            return

        metric = BufferedA2AAgentMetric(
            a2a_agent_id=a2a_agent_id,
            timestamp=datetime.now(timezone.utc),
            response_time=response_time,
            is_success=success,
            interaction_type=interaction_type,
            error_message=error_message,
        )

        with self._lock:
            self._a2a_agent_metrics.append(metric)
            self._total_buffered += 1

    async def _flush_loop(self) -> None:
        """Background task that periodically flushes buffered metrics.

        Raises:
            asyncio.CancelledError: When the flush loop is cancelled.
        """
        logger.info(f"Metrics flush loop started (interval={self.flush_interval}s)")

        while not self._shutdown_event.is_set():
            try:
                # Wait for flush interval or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.flush_interval,
                    )
                    # Shutdown signaled
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, proceed to flush
                    pass

                await self._flush_all()

            except asyncio.CancelledError:
                logger.debug("Flush loop cancelled")
                raise
            except Exception as e:
                logger.error(f"Error in metrics flush loop: {e}", exc_info=True)
                # Continue the loop despite errors
                await asyncio.sleep(5)

    async def _flush_all(self) -> None:
        """Flush all buffered metrics to the database."""
        # Swap out buffers atomically
        with self._lock:
            tool_metrics = list(self._tool_metrics)
            resource_metrics = list(self._resource_metrics)
            prompt_metrics = list(self._prompt_metrics)
            server_metrics = list(self._server_metrics)
            a2a_agent_metrics = list(self._a2a_agent_metrics)
            self._tool_metrics.clear()
            self._resource_metrics.clear()
            self._prompt_metrics.clear()
            self._server_metrics.clear()
            self._a2a_agent_metrics.clear()

        total = len(tool_metrics) + len(resource_metrics) + len(prompt_metrics) + len(server_metrics) + len(a2a_agent_metrics)
        if total == 0:
            return

        logger.debug(
            f"Flushing {total} metrics: "
            f"tools={len(tool_metrics)}, resources={len(resource_metrics)}, prompts={len(prompt_metrics)}, "
            f"servers={len(server_metrics)}, a2a_agents={len(a2a_agent_metrics)}"
        )

        # Flush in thread to avoid blocking event loop
        await asyncio.to_thread(
            self._flush_to_db,
            tool_metrics,
            resource_metrics,
            prompt_metrics,
            server_metrics,
            a2a_agent_metrics,
        )

        self._total_flushed += total
        self._flush_count += 1

        logger.info(
            f"Metrics flush #{self._flush_count}: wrote {total} records "
            f"(tools={len(tool_metrics)}, resources={len(resource_metrics)}, prompts={len(prompt_metrics)}, "
            f"servers={len(server_metrics)}, a2a={len(a2a_agent_metrics)})"
        )

    def _flush_to_db(
        self,
        tool_metrics: list[BufferedToolMetric],
        resource_metrics: list[BufferedResourceMetric],
        prompt_metrics: list[BufferedPromptMetric],
        server_metrics: list[BufferedServerMetric],
        a2a_agent_metrics: list[BufferedA2AAgentMetric],
    ) -> None:
        """Write buffered metrics to database (runs in thread).

        Args:
            tool_metrics: List of buffered tool metrics to write.
            resource_metrics: List of buffered resource metrics to write.
            prompt_metrics: List of buffered prompt metrics to write.
            server_metrics: List of buffered server metrics to write.
            a2a_agent_metrics: List of buffered A2A agent metrics to write.
        """
        try:
            with fresh_db_session() as db:
                # Bulk insert tool metrics
                if tool_metrics:
                    db.bulk_insert_mappings(
                        ToolMetric,
                        [
                            {
                                "tool_id": m.tool_id,
                                "timestamp": m.timestamp,
                                "response_time": m.response_time,
                                "is_success": m.is_success,
                                "error_message": m.error_message,
                            }
                            for m in tool_metrics
                        ],
                    )

                # Bulk insert resource metrics
                if resource_metrics:
                    db.bulk_insert_mappings(
                        ResourceMetric,
                        [
                            {
                                "resource_id": m.resource_id,
                                "timestamp": m.timestamp,
                                "response_time": m.response_time,
                                "is_success": m.is_success,
                                "error_message": m.error_message,
                            }
                            for m in resource_metrics
                        ],
                    )

                # Bulk insert prompt metrics
                if prompt_metrics:
                    db.bulk_insert_mappings(
                        PromptMetric,
                        [
                            {
                                "prompt_id": m.prompt_id,
                                "timestamp": m.timestamp,
                                "response_time": m.response_time,
                                "is_success": m.is_success,
                                "error_message": m.error_message,
                            }
                            for m in prompt_metrics
                        ],
                    )

                # Bulk insert server metrics
                if server_metrics:
                    db.bulk_insert_mappings(
                        ServerMetric,
                        [
                            {
                                "server_id": m.server_id,
                                "timestamp": m.timestamp,
                                "response_time": m.response_time,
                                "is_success": m.is_success,
                                "error_message": m.error_message,
                            }
                            for m in server_metrics
                        ],
                    )

                # Bulk insert A2A agent metrics
                if a2a_agent_metrics:
                    db.bulk_insert_mappings(
                        A2AAgentMetric,
                        [
                            {
                                "a2a_agent_id": m.a2a_agent_id,
                                "timestamp": m.timestamp,
                                "response_time": m.response_time,
                                "is_success": m.is_success,
                                "interaction_type": m.interaction_type,
                                "error_message": m.error_message,
                            }
                            for m in a2a_agent_metrics
                        ],
                    )

                db.commit()

        except Exception as e:
            logger.error(f"Failed to flush metrics to database: {e}", exc_info=True)
            # Metrics are lost on failure - acceptable trade-off for performance
            # Could implement retry queue if needed

    def _write_tool_metric_immediately(
        self,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Write a single tool metric immediately (fallback when buffering disabled).

        Args:
            tool_id: UUID of the tool.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = ToolMetric(
                    tool_id=tool_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=time.monotonic() - start_time,
                    is_success=success,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write tool metric: {e}")

    def _write_resource_metric_immediately(
        self,
        resource_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Write a single resource metric immediately.

        Args:
            resource_id: UUID of the resource.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = ResourceMetric(
                    resource_id=resource_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=time.monotonic() - start_time,
                    is_success=success,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write resource metric: {e}")

    def _write_prompt_metric_immediately(
        self,
        prompt_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Write a single prompt metric immediately.

        Args:
            prompt_id: UUID of the prompt.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = PromptMetric(
                    prompt_id=prompt_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=time.monotonic() - start_time,
                    is_success=success,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write prompt metric: {e}")

    def _write_server_metric_immediately(
        self,
        server_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Write a single server metric immediately.

        Args:
            server_id: UUID of the server.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = ServerMetric(
                    server_id=server_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=time.monotonic() - start_time,
                    is_success=success,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write server metric: {e}")

    def _write_a2a_agent_metric_immediately(
        self,
        a2a_agent_id: str,
        start_time: float,
        success: bool,
        interaction_type: str,
        error_message: Optional[str],
    ) -> None:
        """Write a single A2A agent metric immediately.

        Args:
            a2a_agent_id: UUID of the A2A agent.
            start_time: Monotonic start time for response_time calculation.
            success: Whether the operation succeeded.
            interaction_type: Type of interaction (e.g., "invoke").
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = A2AAgentMetric(
                    a2a_agent_id=a2a_agent_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=time.monotonic() - start_time,
                    is_success=success,
                    interaction_type=interaction_type,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write A2A agent metric: {e}")

    def _write_a2a_agent_metric_with_duration_immediately(
        self,
        a2a_agent_id: str,
        response_time: float,
        success: bool,
        interaction_type: str,
        error_message: Optional[str],
    ) -> None:
        """Write a single A2A agent metric with pre-calculated duration immediately.

        Args:
            a2a_agent_id: UUID of the A2A agent.
            response_time: Pre-calculated response time in seconds.
            success: Whether the operation succeeded.
            interaction_type: Type of interaction (e.g., "invoke").
            error_message: Optional error message if failed.
        """
        try:
            with fresh_db_session() as db:
                metric = A2AAgentMetric(
                    a2a_agent_id=a2a_agent_id,
                    timestamp=datetime.now(timezone.utc),
                    response_time=response_time,
                    is_success=success,
                    interaction_type=interaction_type,
                    error_message=error_message,
                )
                db.add(metric)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to write A2A agent metric: {e}")

    def get_stats(self) -> dict:
        """Get buffer statistics for monitoring.

        Returns:
            dict: Buffer statistics including enabled state, sizes, and counts.
        """
        with self._lock:
            current_size = len(self._tool_metrics) + len(self._resource_metrics) + len(self._prompt_metrics) + len(self._server_metrics) + len(self._a2a_agent_metrics)

        return {
            "enabled": self.enabled,
            "flush_interval": self.flush_interval,
            "max_buffer_size": self.max_buffer_size,
            "current_buffer_size": current_size,
            "total_buffered": self._total_buffered,
            "total_flushed": self._total_flushed,
            "flush_count": self._flush_count,
        }


# Singleton instance
_metrics_buffer_service: Optional[MetricsBufferService] = None


def get_metrics_buffer_service() -> MetricsBufferService:
    """Get or create the singleton MetricsBufferService instance.

    Returns:
        MetricsBufferService: The singleton metrics buffer service instance.
    """
    global _metrics_buffer_service  # pylint: disable=global-statement
    if _metrics_buffer_service is None:
        _metrics_buffer_service = MetricsBufferService()
    return _metrics_buffer_service
