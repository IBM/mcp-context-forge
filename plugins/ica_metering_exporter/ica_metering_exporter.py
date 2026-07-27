# -*- coding: utf-8 -*-
"""Location: ./plugins/ica_metering_exporter/ica_metering_exporter.py

ICA Metering Exporter Plugin.
Exports MCP tool invocation metrics to ICA core-services.
"""

# Standard
import os
import time
from typing import Any, Optional

# Third-Party
import httpx

# First-Party
from cpex.framework import Plugin, PluginConfig, PluginContext
from cpex.framework.constants import GATEWAY_METADATA
from cpex.framework.hooks.tools import (
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class IcaMeteringExporterPlugin(Plugin):
    """Export MCP tool invocation metrics to ICA metering service."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.telemetry_config = config.config
        self.http_client: Optional[httpx.AsyncClient] = None
        self.env_model_name: Optional[str] = None

        # Parse gateway-level defaults from plugin config
        self._gateway_configs: dict[str, dict] = {}
        raw_gateways = self.telemetry_config.get("gateways", [])
        if isinstance(raw_gateways, list):
            for gw in raw_gateways:
                gw_id = gw.get("id")
                if gw_id:
                    self._gateway_configs[gw_id] = gw

        if self.telemetry_config.get("enabled", False):
            self.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=2.0),
                limits=httpx.Limits(max_keepalive_connections=5),
            )
            self.env_model_name = os.getenv("MCP_DEFAULT_MODEL")

    async def shutdown(self) -> None:
        """Plugin cleanup code - close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None

    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        if not self.telemetry_config.get("enabled", False):
            return ToolPreInvokeResult(continue_processing=True)

        context.state["ica_metering_start_time"] = time.monotonic()
        # Extract model name from transport headers (set by OpenWebUI)
        headers = getattr(payload.headers, "root", {})
        model_name = headers.get("x-openwebui-model-id") or headers.get("X-OpenWebUI-Model-Id")
        if model_name:
            context.state["ica_metering_model_name"] = model_name
        logger.debug("ICA metering: Pre-invoke for tool %s", payload.name)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        if not self.telemetry_config.get("enabled", False):
            return ToolPostInvokeResult(continue_processing=True)

        pre_invoke_time = context.state.get("ica_metering_start_time")
        latency_ms: Optional[int] = None
        if pre_invoke_time is not None:
            elapsed_ms = (time.monotonic() - pre_invoke_time) * 1000
            latency_ms = max(0, int(elapsed_ms))

        if not payload.name:
            logger.warning("ICA metering: Tool name is empty, skipping")
            return ToolPostInvokeResult(continue_processing=True)

        gateway_meta = context.global_context.metadata.get(GATEWAY_METADATA, {})
        if not isinstance(gateway_meta, dict):
            gateway_meta = {}

        ctx_meta = context.global_context.metadata.get("meta_data", {})
        if not isinstance(ctx_meta, dict):
            ctx_meta = {}

        # Resolve model name using priority cascade
        headers = getattr(getattr(payload, "headers", None), "root", {})
        if not isinstance(headers, dict):
            headers = {}
        model_name, model_source = self._resolve_model_name(context, headers, ctx_meta)

        tokens = self._extract_tokens(payload.result)

        tool_details: dict[str, Any] = {
            "toolName": payload.name,
            "serverId": context.global_context.server_id or "unknown",
            "serverName": gateway_meta.get("name"),
            "gatewayId": gateway_meta.get("id"),
            "integrationType": "MCP",
            "requestType": "SSE",
            "latencyMs": latency_ms,
            "hasError": self._is_error(payload.result),
            "errorMessage": self._extract_error_message(payload.result),
            "cached": context.state.get("cache_hit", False),
            "retryAttempt": context.state.get("retry_count", 0),
            "modelName": model_name,
            "traceId": context.global_context.request_id,
            "tokenInput": tokens.get("input"),
            "tokenOutput": tokens.get("output"),
            "source": "ContextForge",
        }

        metering_payload: dict[str, Any] = {
            "userEmail": context.global_context.user or "unknown",
            "teamName": context.global_context.tenant_id or "unknown",
            "toolDetails": tool_details,
        }

        # Optional model source tracking for debugging
        if self.telemetry_config.get("include_model_source", False):
            metering_payload.setdefault("_metadata", {})["modelSource"] = model_source

        await self._send_to_ica(metering_payload)
        return ToolPostInvokeResult(continue_processing=True)

    def _resolve_model_name(
        self,
        context: PluginContext,
        headers: dict,
        ctx_meta: dict,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Resolve model name from multiple sources in priority order.

        Priority:
          1. Transport header (X-OpenWebUI-Model-Id) — set by OpenWebUI tools.py,
             stored in context.state by tool_pre_invoke
          2. Session metadata (global_context.metadata["model_name"]) — CLI client session init
          3. Environment variable (MCP_DEFAULT_MODEL) — container/env config
          4. Tool call meta_data.model — API callers
          5. Gateway-level default from config — per-gateway fallback
          6. Global default from config — system-wide fallback
          7. None — truly unknown

        Returns:
            Tuple of (model_name, source_label)
        """
        # Priority 1: Transport headers (extracted by tool_pre_invoke from payload headers)
        model = context.state.get("ica_metering_model_name")
        if model:
            return str(model), "transport_header"

        # Priority 2: Session metadata (set by CLI client during session init)
        model = context.global_context.metadata.get("model_name")
        if model:
            return str(model), "session_init"

        # Priority 3: Environment variable
        if self.env_model_name:
            return self.env_model_name, "environment"

        # Priority 4: Tool call meta_data (API callers)
        model = ctx_meta.get("model")
        if model:
            return str(model), "tool_metadata"

        # Priority 5: Gateway-level default
        gw_meta = context.global_context.metadata.get(GATEWAY_METADATA)
        if isinstance(gw_meta, dict):
            gateway_id = gw_meta.get("id")
            if gateway_id and gateway_id in self._gateway_configs:
                model = self._gateway_configs[gateway_id].get("default_model")
                if model:
                    return str(model), "gateway_default"

        # Priority 6: Global default from config
        model = self.telemetry_config.get("global_default_model")
        if model:
            return str(model), "global_default"

        # Priority 7: Truly unknown
        return None, "unknown"

    @staticmethod
    def _is_error(result: Any) -> bool:
        """Check if result indicates an error."""
        if result is None:
            return False
        if isinstance(result, dict):
            return bool(result.get("isError", False))
        return False

    @staticmethod
    def _extract_error_message(result: Any) -> Optional[str]:
        """Extract error message from result."""
        if isinstance(result, dict) and result.get("isError"):
            return result.get("errorMessage")
        return None

    @staticmethod
    def _extract_tokens(result: Any) -> dict:
        """Safely extract token metadata from result."""
        if not isinstance(result, dict):
            return {}
        meta = result.get("meta", {})
        if not isinstance(meta, dict):
            return {}
        tokens = meta.get("tokens", {})
        return tokens if isinstance(tokens, dict) else {}

    async def _send_to_ica(self, payload: dict) -> None:
        """Send metering data to ICA endpoint (fire-and-forget)."""
        if not self.http_client:
            return

        metering_url = self.telemetry_config.get("metering_url")
        metering_token = self.telemetry_config.get("metering_token")

        if not metering_url or not metering_token:
            logger.warning("ICA metering URL or token not configured")
            return

        try:
            response = await self.http_client.post(
                metering_url,
                json=payload,
                headers={"X-MCP-Metering-Token": metering_token},
            )
            if response.status_code != 202:
                logger.warning(
                    "ICA metering endpoint returned %s: %s",
                    response.status_code,
                    response.text,
                )
            else:
                logger.debug("ICA metering: Successfully sent metrics")
        except httpx.TimeoutException:
            logger.warning("ICA metering: Timeout sending metrics")
        except httpx.NetworkError:
            logger.warning("ICA metering: Network error")
        except httpx.HTTPStatusError as e:
            logger.error(
                "ICA metering: HTTP %s: %s", e.response.status_code, e.response.text
            )
        except Exception as e:
            logger.error("ICA metering: Failed to send metrics: %s", e)
