"""Location: ./plugins/apiconnect_fam/activities/send_metrics.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

Send Metrics Activity.

Sends runtime metrics to FAM periodically.
"""

# Standard
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

# First-Party
from mcpgateway.db import Server, ServerMetric, SessionLocal, Tool, ToolMetric

# Local
from ..fam import FAMAssetCatalogClient, FAMMetricsPayload
from ..models import ActivityContext
from ..utils import RetryConfig, SyncError, with_retry
from .base import AbstractScheduledActivity


class SendMetricsActivity(AbstractScheduledActivity):
    """Activity for sending runtime metrics to FAM.

    Attributes:
        context: Shared activity context
        fam_client: FAM API client
        metrics_interval: Interval in seconds
    """

    def __init__(self, context: ActivityContext, fam_client: FAMAssetCatalogClient, metrics_interval: int = 300):
        """Initialize send metrics activity.

        Args:
            context: Shared activity context
            fam_client: FAM API client
            metrics_interval: Metrics interval in seconds
        """
        super().__init__(context)
        self._fam_client = fam_client
        self._metrics_interval = metrics_interval
        self._total_metrics_sent = 0

    def get_interval_seconds(self) -> int:
        """Get the metrics interval.

        Returns:
            Interval in seconds
        """
        return self._metrics_interval

    async def perform(self) -> None:
        """Send metrics to FAM.

        Raises:
            SyncError: If metrics sync fails
        """

        try:
            # Query and send metrics
            metrics_count = await with_retry(self._query_and_send_metrics, retry_config=RetryConfig(max_attempts=2, initial_delay=1.0), operation_name="Send Metrics")

            # Track success
            self._total_metrics_sent += metrics_count

            self.logger.info(f"Sent {metrics_count} metrics to FAM (total: {self._total_metrics_sent})")

        except Exception as e:
            error_msg = f"Failed to send metrics: {e}"
            self.logger.error(error_msg, exc_info=True)
            raise SyncError(error_msg, e)

    async def _query_and_send_metrics(self) -> int:
        """Query metrics from database and send to FAM.

        Returns:
            Number of metrics sent

        Raises:
            Exception: If query or send fails
        """
        with SessionLocal() as db:
            # Get all servers and tools
            servers = db.query(Server).all()
            tools = db.query(Tool).all()

            # Query metrics from last interval
            time_window_minutes = self._metrics_interval / 60
            time_window_start = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)

            server_metrics_raw = db.query(ServerMetric).filter(ServerMetric.timestamp >= time_window_start).all()

            tool_metrics_raw = db.query(ToolMetric).filter(ToolMetric.timestamp >= time_window_start).all()

            # Only count server metrics since tool invocations are already included in server metrics
            # (tools are part of servers, so tool metrics are reflected in server-level metrics)
            total_metrics = len(server_metrics_raw)

            # Organize metrics
            server_metrics_map = self._organize_server_metrics(server_metrics_raw)
            tool_metrics_by_server = self._organize_tool_metrics(tool_metrics_raw, servers)

            # Build and send metrics payload (always send, even if empty)
            if total_metrics == 0:
                self.logger.debug("Sending empty metrics payload (no metrics in time window)")

            # Build payload using FAMMetricsPayload builder
            self.logger.debug("Calling FAM API: POST /api/engine/v3/runtimes/.../metrics")
            payload = FAMMetricsPayload.build_payload(
                timestamp=datetime.now(timezone.utc), server_metrics_map=dict(server_metrics_map), tool_metrics_by_server={k: dict(v) for k, v in tool_metrics_by_server.items()}
            )

            success = await self._fam_client.submit_metrics(payload)

            if success:
                if total_metrics > 0:
                    self.logger.debug(f"FAM API call successful ({total_metrics} metrics sent)")
                else:
                    self.logger.debug("FAM API call successful (empty metrics payload sent)")
                return total_metrics
            else:
                self.logger.error("FAM API call failed")
                return 0

    def _organize_server_metrics(self, metrics: List[Any]) -> Dict[str, List[Any]]:
        """Organize server metrics by server ID.

        Args:
            metrics: List of ServerMetric objects

        Returns:
            Dictionary mapping server ID to metrics list
        """
        server_metrics_map = defaultdict(list)
        for metric in metrics:
            server_metrics_map[str(metric.server_id)].append(metric)
        return server_metrics_map

    def _organize_tool_metrics(self, metrics: List[Any], servers: List[Any]) -> Dict[str, Dict[str, List[Any]]]:
        """Organize tool metrics by server and tool.

        Args:
            metrics: List of ToolMetric objects
            servers: List of Server objects

        Returns:
            Dictionary mapping server ID to tool metrics
        """
        # Build tool-to-server mapping
        tool_to_server = {}
        for server in servers:
            if hasattr(server, "tools") and server.tools:
                for tool in server.tools:
                    tool_to_server[str(tool.id)] = str(server.id)

        # Organize by server and tool
        tool_metrics_by_server = defaultdict(lambda: defaultdict(list))
        for metric in metrics:
            tool_id = str(metric.tool_id)
            server_id = tool_to_server.get(tool_id)
            if server_id:
                tool_metrics_by_server[server_id][tool_id].append(metric)

        return tool_metrics_by_server
