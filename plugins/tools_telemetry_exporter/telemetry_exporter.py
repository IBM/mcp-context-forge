# -*- coding: utf-8 -*-
"""Location: ./plugins/tools_telemetry_exporter/telemetry_exporter.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Tools Telemetry Exporter Plugin.
This plugin exports comprehensive tool invocation telemetry to OpenTelemetry.
"""

# Standard
from typing import Dict

# Third-Party
import orjson

# First-Party
from mcpgateway.plugins.framework import get_attr, Plugin, PluginConfig, PluginContext
from mcpgateway.plugins.framework.constants import GATEWAY_METADATA, TOOL_METADATA
from mcpgateway.plugins.framework.hooks.tools import ToolPostInvokePayload, ToolPostInvokeResult, ToolPreInvokePayload, ToolPreInvokeResult
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class ToolsTelemetryExporterPlugin(Plugin):
    """Export comprehensive tool invocation telemetry to OpenTelemetry."""

    def __init__(self, config: PluginConfig):
        """Initialize the ToolsTelemetryExporterPlugin.

        Args:
            config: Plugin configuration containing telemetry settings.
        """
        super().__init__(config)
        self.is_open_telemetry_available = self._is_open_telemetry_available()
        self.telemetry_config = config.config

    @staticmethod
    def _is_open_telemetry_available() -> bool:
        """Check if OpenTelemetry is available for import.

        Returns:
            True if OpenTelemetry can be imported, False otherwise.
        """
        try:
            # Third-Party
            from opentelemetry import trace  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import

            return True
        except ImportError:
            logger.warning("ToolsTelemetryExporter: OpenTelemetry is not available. Telemetry export will be disabled.")
            return False

    @staticmethod
    def _get_base_context_attributes(context: PluginContext) -> Dict:
        """Extract base context attributes from plugin context.

        Args:
            context: Plugin execution context containing global context.

        Returns:
            Dictionary with base attributes (request_id, user, tenant_id, server_id).
        """
        global_context = context.global_context
        return {
            "request_id": global_context.request_id or "",
            "user": global_context.user or "",
            "tenant_id": global_context.tenant_id or "",
            "server_id": global_context.server_id or "",
        }

    def _get_pre_invoke_context_attributes(self, context: PluginContext) -> Dict:
        """Extract pre-invocation context attributes including tool and gateway metadata.

        Args:
            context: Plugin execution context containing tool and gateway metadata.

        Returns:
            Dictionary with base attributes plus tool and target MCP server details.
        """
        global_context = context.global_context
        tool_metadata = global_context.metadata.get(TOOL_METADATA)
        target_mcp_server_metadata = global_context.metadata.get(GATEWAY_METADATA)

        return {
            **self._get_base_context_attributes(context),
            "tool": {
                "name": get_attr(tool_metadata, "name"),
                "target_tool_name": get_attr(tool_metadata, "original_name"),
                "description": get_attr(tool_metadata, "description"),
            },
            "target_mcp_server": {
                "id": get_attr(target_mcp_server_metadata, "id"),
                "name": get_attr(target_mcp_server_metadata, "name"),
                "url": str(get_attr(target_mcp_server_metadata, "url")),
            },
        }

    def _get_post_invoke_context_attributes(self, context: PluginContext) -> Dict:
        """Extract post-invocation context attributes.

        Args:
            context: Plugin execution context.

        Returns:
            Dictionary with base context attributes for post-invocation telemetry.
        """
        return {
            **self._get_base_context_attributes(context),
        }

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Capture pre-invocation telemetry for tools.

        Args:
            payload: The tool payload containing arguments.
            context: Plugin execution context.

        Returns:
            Result with potentially modified tool arguments.
        """
        logger.info("ToolsTelemetryExporter: Capturing pre-invocation tool telemetry.")
        context_attributes = self._get_pre_invoke_context_attributes(context)

        export_attributes = {
            "request_id": context_attributes["request_id"],
            "user": context_attributes["user"],
            "tenant_id": context_attributes["tenant_id"],
            "server_id": context_attributes["server_id"],
            "target_mcp_server.id": context_attributes["target_mcp_server"]["id"],
            "target_mcp_server.name": context_attributes["target_mcp_server"]["name"],
            "target_mcp_server.url": context_attributes["target_mcp_server"]["url"],
            "tool.name": context_attributes["tool"]["name"],
            "tool.target_tool_name": context_attributes["tool"]["target_tool_name"],
            "tool.description": context_attributes["tool"]["description"],
            "tool.invocation.args": orjson.dumps(payload.args, default=str).decode(),
            "headers": payload.headers.model_dump_json() if payload.headers else "{}",
        }

        await self._export_telemetry(attributes=export_attributes, span_name="tool.pre_invoke")
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Capture post-invocation telemetry.

        Args:
            payload: Tool result payload containing the tool name and execution result.
            context: Plugin context with state from pre-invoke hook.

        Returns:
            ToolPostInvokeResult allowing execution to continue.
        """
        logger.info("ToolsTelemetryExporter: Capturing post-invocation tool telemetry.")
        context_attributes = self._get_post_invoke_context_attributes(context)

        export_attributes = {
            "request_id": context_attributes["request_id"],
            "user": context_attributes["user"],
            "tenant_id": context_attributes["tenant_id"],
            "server_id": context_attributes["server_id"],
        }

        result = payload.result if payload.result else {}
        has_error = result.get("isError", False)
        if self.telemetry_config.get("export_full_payload", False) and not has_error:
            max_payload_bytes_size = self.telemetry_config.get("max_payload_bytes_size", 10000)
            result_content = result.get("content")
            if result_content:
                result_content_str = orjson.dumps(result_content, default=str).decode()
                if len(result_content_str) <= max_payload_bytes_size:
                    export_attributes["tool.invocation.result"] = result_content_str
                else:
                    truncated_content = result_content_str[:max_payload_bytes_size]
                    export_attributes["tool.invocation.result"] = truncated_content + "...<truncated>"
            else:
                export_attributes["tool.invocation.result"] = "<No content in result>"
        export_attributes["tool.invocation.has_error"] = has_error

        await self._export_telemetry(attributes=export_attributes, span_name="tool.post_invoke")
        return ToolPostInvokeResult(continue_processing=True)

    async def _export_telemetry(self, attributes: Dict, span_name: str) -> None:
        """Export telemetry attributes to OpenTelemetry.

        Args:
            attributes: Dictionary of telemetry attributes to export.
            span_name: Name of the OpenTelemetry span to create.
        """
        if not self.is_open_telemetry_available:
            logger.debug("ToolsTelemetryExporter: OpenTelemetry not available. Skipping telemetry export.")
            return

        # Third-Party
        from opentelemetry import trace  # pylint: disable=import-outside-toplevel

        try:
            tracer = trace.get_tracer(__name__)
            current_span = trace.get_current_span()
            if not current_span or not current_span.is_recording():
                logger.warning("ToolsTelemetryExporter: No active span found. Skipping telemetry export.")
                return

            with tracer.start_as_current_span(span_name) as span:
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                logger.debug(f"ToolsTelemetryExporter: Exported telemetry for span '{span_name}' with attributes: {attributes}")
        except Exception as e:
            logger.error(f"ToolsTelemetryExporter: Error creating span '{span_name}': {e}", exc_info=True)
