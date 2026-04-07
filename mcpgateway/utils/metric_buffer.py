# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/metric_buffer.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge Team

Simple metric buffering utility for batching database inserts.

This module provides a lightweight MetricBuffer class that batches metric
inserts to reduce database write pressure. It can be used as a drop-in
replacement for individual session.add() calls.

Usage:
    # Create a buffer with default batch size (1000)
    tool_buffer = MetricBuffer(session_factory, ToolMetric)
    server_buffer = MetricBuffer(session_factory, ServerMetric)

    # Add metrics (automatically flushes when batch_size is reached)
    tool_buffer.add({"tool_id": "uuid1", "response_time": 1.5, "is_success": True})
    tool_buffer.add({"tool_id": "uuid2", "response_time": 0.8, "is_success": False})

    # Explicitly flush remaining metrics
    tool_buffer.flush()

    # On shutdown
    tool_buffer.flush()
"""

import logging
from typing import Any, Dict, List, Type

from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)


class MetricBuffer:
    """Buffer for batching metric inserts into the database.

    This class accumulates metric records in memory and flushes them in batches
    to reduce database write pressure. It supports both automatic flushing
    (when batch_size is reached) and manual flushing.

    Thread-safe: Uses threading.Lock for concurrent access.
    """

    def __init__(
        self,
        session_factory,
        metric_model: Type,
        batch_size: int = 1000,
    ):
        """Initialize the metric buffer.

        Args:
            session_factory: SQLAlchemy session factory (callable that returns a Session).
            metric_model: The SQLAlchemy model class (e.g., ToolMetric, ServerMetric).
            batch_size: Number of records to accumulate before automatic flush.
                       Defaults to 1000.
        """
        self.buffer: List[Dict[str, Any]] = []
        self.batch_size = batch_size
        self.session_factory = session_factory
        self.metric_model = metric_model
        self._lock = __import__("threading").Lock()

        # Statistics
        self.total_added = 0
        self.total_flushed = 0
        self.flush_count = 0

        logger.debug(
            f"MetricBuffer initialized for {metric_model.__tablename__} "
            f"(batch_size={batch_size})"
        )

    def add(self, metric_data: Dict[str, Any]) -> None:
        """Add a metric record to the buffer.

        Automatically flushes if the buffer reaches batch_size.

        Args:
            metric_data: Dictionary of column values to insert.
                        Should match the model's column names.
        """
        with self._lock:
            self.buffer.append(metric_data)
            self.total_added += 1

            if len(self.buffer) >= self.batch_size:
                self._flush_internal()

    def flush(self) -> None:
        """Flush all buffered metrics to the database.

        Thread-safe public entry point for manual flushing.
        """
        with self._lock:
            self._flush_internal()

    def _flush_internal(self) -> None:
        """Internal flush logic (must be called with lock held).

        Uses PostgreSQL multi-row INSERT via pg_insert().values() for maximum efficiency
        when connected to PostgreSQL. Falls back to generic insert for other databases.

        Returns:
            None
        """
        if not self.buffer:
            return

        batch = self.buffer.copy()
        self.buffer.clear()

        try:
            with self.session_factory() as session:
                # Use PostgreSQL multi-row INSERT for efficiency
                stmt = pg_insert(self.metric_model).values(batch)
                session.execute(stmt)
                session.commit()

            self.total_flushed += len(batch)
            self.flush_count += 1

            logger.debug(
                f"Flushed {len(batch)} {self.metric_model.__tablename__} records "
                f"(total_flushed={self.total_flushed})"
            )
        except Exception as e:
            # Restore buffer on failure (metrics are not lost)
            self.buffer.extend(batch)
            logger.error(
                f"Failed to flush {len(batch)} {self.metric_model.__tablename__} "
                f"metrics: {e}",
                exc_info=True,
            )
            # Re-raise to allow caller to handle if needed
            raise

    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics for monitoring.

        Returns:
            Dictionary with buffer statistics.
        """
        with self._lock:
            return {
                "model": self.metric_model.__tablename__,
                "batch_size": self.batch_size,
                "current_buffer_size": len(self.buffer),
                "total_added": self.total_added,
                "total_flushed": self.total_flushed,
                "flush_count": self.flush_count,
            }

    def __del__(self):
        """Ensure final flush on deletion (best-effort)."""
        if self.buffer:
            try:
                self.flush()
            except Exception as e:
                logger.warning(f"Failed to flush remaining metrics on cleanup: {e}")
