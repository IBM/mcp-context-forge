"""Location: ./plugins/apiconnect_fam/fam/payloads/metrics.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shankar N

FAM Metrics Payload Builder.
"""

# Standard
from datetime import datetime
from typing import Any, Dict, List


class FAMMetricsPayload:
    """Builder for FAM metrics payloads following OpenAPI spec.

    Builds AgentMetricsModel payload structure:
    - timestamp: epoch milliseconds
    - runtimeTransactionMetrics: runtime-level aggregated metrics
    - mcpServerTransactionMetricsList: list of server metrics with nested tool metrics
    - mcpServersTransactionMetricsSummary: pre-computed summary (optional)
    """

    @staticmethod
    def _convert_to_milliseconds(dt: datetime) -> int:
        """Convert datetime to epoch milliseconds.

        Args:
            dt: Datetime object

        Returns:
            Epoch milliseconds as integer
        """
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _aggregate_metrics(metrics: List[Any]) -> Dict[str, Any]:
        """Aggregate raw metrics into API metrics format.

        Args:
            metrics: List of metric objects (ToolMetric or ServerMetric)

        Returns:
            Dict with transactionCount, averageLatency, averageResponseTime
        """
        if not metrics:
            return {"transactionCount": 0, "averageLatency": 0.0, "averageResponseTime": 0.0, "averageBackendResponseTime": 0.0}

        total_count = len(metrics)
        # Convert response_time from seconds to milliseconds
        response_times_ms = [m.response_time * 1000 for m in metrics]
        avg_response_time = sum(response_times_ms) / total_count if total_count > 0 else 0.0

        return {
            "transactionCount": total_count,
            "averageLatency": 0.0,
            "averageResponseTime": avg_response_time,
            "averageBackendResponseTime": 0.0,
        }

    @staticmethod
    def _aggregate_metrics_by_status(metrics: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Aggregate metrics grouped by HTTP status code ranges.

        Args:
            metrics: List of metric objects

        Returns:
            Dict with keys "2xx", "4xx", "5xx" containing aggregated metrics
        """
        # Group metrics by success/failure (map to 2xx/5xx)
        success_metrics = [m for m in metrics if m.is_success]
        failure_metrics = [m for m in metrics if not m.is_success]

        result = {}

        if success_metrics:
            result["2xx"] = FAMMetricsPayload._aggregate_metrics(success_metrics)

        if failure_metrics:
            result["5xx"] = FAMMetricsPayload._aggregate_metrics(failure_metrics)

        return result

    @staticmethod
    def build_tool_metrics(tool_id: str, tool_metrics: List[Any]) -> Dict[str, Any]:
        """Build MCPToolTransactionMetrics payload.

        Args:
            tool_id: Tool identifier
            tool_metrics: List of ToolMetric objects

        Returns:
            MCPToolTransactionMetrics dict
        """
        return {"toolId": tool_id, "apiMetrics": FAMMetricsPayload._aggregate_metrics(tool_metrics), "metricsByStatusCode": FAMMetricsPayload._aggregate_metrics_by_status(tool_metrics)}

    @staticmethod
    def build_server_metrics(server_id: str, server_metrics: List[Any], tool_metrics_map: Dict[str, List[Any]]) -> Dict[str, Any]:
        """Build MCPServerTransactionMetrics payload.

        Args:
            server_id: Server identifier
            server_metrics: List of ServerMetric objects
            tool_metrics_map: Dict mapping tool_id to list of ToolMetric objects

        Returns:
            MCPServerTransactionMetrics dict
        """
        # Build tool metrics list
        tool_metrics_list = []
        for tool_id, metrics in tool_metrics_map.items():
            if metrics:
                tool_metrics_list.append(FAMMetricsPayload.build_tool_metrics(tool_id, metrics))

        return {
            "serverId": server_id,
            "apiMetrics": FAMMetricsPayload._aggregate_metrics(server_metrics),
            "metricsByStatusCode": FAMMetricsPayload._aggregate_metrics_by_status(server_metrics),
            "mcpToolTransactionMetricsList": tool_metrics_list,
        }

    @staticmethod
    def build_runtime_metrics(all_metrics: List[Any]) -> Dict[str, Any]:
        """Build RuntimeTransactionMetrics payload.

        Args:
            all_metrics: List of all ServerMetric objects (tool metrics are already included in server metrics)

        Returns:
            RuntimeTransactionMetrics dict
        """
        return {"apiMetrics": FAMMetricsPayload._aggregate_metrics(all_metrics), "metricsByStatusCode": FAMMetricsPayload._aggregate_metrics_by_status(all_metrics)}

    @staticmethod
    def build_payload(timestamp: datetime, server_metrics_map: Dict[str, List[Any]], tool_metrics_by_server: Dict[str, Dict[str, List[Any]]]) -> Dict[str, Any]:
        """Build complete AgentMetricsModel payload.

        Args:
            timestamp: Timestamp for the metrics collection
            server_metrics_map: Dict mapping server_id to list of ServerMetric objects
            tool_metrics_by_server: Dict mapping server_id to dict of tool_id to ToolMetric list

        Returns:
            Complete AgentMetricsModel payload dict
        """
        # Build server metrics list
        mcp_server_metrics_list = []
        all_server_metrics = []

        for server_id, server_metrics in server_metrics_map.items():
            tool_metrics_map = tool_metrics_by_server.get(server_id, {})

            # Only add server metrics to runtime summary
            # Tool invocations are already included in server metrics (tools are part of servers)
            all_server_metrics.extend(server_metrics)

            # Build server metrics entry
            if server_metrics or tool_metrics_map:
                mcp_server_metrics_list.append(FAMMetricsPayload.build_server_metrics(server_id, server_metrics, tool_metrics_map))

        # Build runtime metrics from server metrics only
        runtime_metrics = FAMMetricsPayload.build_runtime_metrics(all_server_metrics)

        # Build summary metrics from server metrics only
        summary_metrics = FAMMetricsPayload._aggregate_metrics(all_server_metrics)

        return {
            "timestamp": FAMMetricsPayload._convert_to_milliseconds(timestamp),
            "runtimeTransactionMetrics": runtime_metrics,
            "mcpServerTransactionMetricsList": mcp_server_metrics_list,
            "mcpServersTransactionMetricsSummary": summary_metrics,
        }
