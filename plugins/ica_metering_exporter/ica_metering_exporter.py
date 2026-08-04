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
from cpex.framework import Plugin, PluginConfig, PluginContext  # type: ignore[import-untyped]
from cpex.framework.constants import GATEWAY_METADATA  # type: ignore[import-untyped]
from cpex.framework.hooks.tools import (  # type: ignore[import-untyped]
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
import httpx
import jwt

# First-Party
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class IcaMeteringExporterPlugin(Plugin):  # type: ignore[misc, no-any-unimported]  # noqa: E501
    """Export MCP tool invocation metrics to ICA metering service."""

    # Call-context headers set by the invoking application (Open WebUI), mirroring
    # ica-litellm-extensions/ica_metering_callbacks.py. Header names are identical
    # so the MCP and LLM metering pipelines stay symmetric.
    CALL_CONTEXT_HEADERS: dict[str, str] = {
        "ica_llm_call_type": "llm_call_type",
        "ica_assistant_name": "assistant_name",
        "ica_assistant_uuid": "assistant_uuid",
        "ica_agent_name": "agent_name",
        "ica_agent_uuid": "agent_uuid",
        "ica_agent_tool_ids": "agent_tool_ids",
        "ica_digital_ibmer_name": "digital-ibmer_name",
        "ica_digital_ibmer_uuid": "digital-ibmer_uuid",
        "ica_digital_ibmer_tool_ids": "digital-ibmer_tool_ids",
    }

    def __init__(self, config: PluginConfig) -> None:  # type: ignore[no-any-unimported]  # noqa: E501
        """Initialize plugin: parse config, parse gateway defaults, create HTTP client if enabled."""
        super().__init__(config)
        self.telemetry_config = config.config
        self.http_client: Optional[httpx.AsyncClient] = None
        self.env_model_name: Optional[str] = None
        self._jwt_secret: Optional[str] = config.config.get("jwt_secret")

        # Parse gateway-level defaults from plugin config
        self._gateway_configs: dict[str, dict[str, Any]] = {}
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

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:  # type: ignore[no-any-unimported]  # noqa: E501
        """Record tool invocation start time and extract model name from transport headers."""
        if not self.telemetry_config.get("enabled", False):
            return ToolPreInvokeResult(continue_processing=True)

        context.state["ica_metering_start_time"] = time.monotonic()
        # Extract model name from transport headers (set by OpenWebUI)
        headers = getattr(payload.headers, "root", {})
        model_name = headers.get("x-openwebui-model-id") or headers.get("X-OpenWebUI-Model-Id")
        if model_name:
            context.state["ica_metering_model_name"] = model_name
        app_id = headers.get("x-app-id") or headers.get("X-App-Id")
        if app_id:
            context.state["ica_app_id"] = app_id
        user_agent = headers.get("x-forwarded-user-agent") or headers.get("X-Forwarded-User-Agent") or headers.get("user-agent") or headers.get("User-Agent")
        if user_agent:
            context.state["ica_user_agent"] = user_agent
        for state_key, header_name in self.CALL_CONTEXT_HEADERS.items():
            value = self._get_header(headers, header_name)
            if value:
                context.state[state_key] = value
        logger.debug("ICA metering: Pre-invoke for tool %s", payload.name)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:  # type: ignore[no-any-unimported]  # noqa: E501
        """Compute latency, resolve model name via cascade, build metering payload, fire-and-forget to ICA."""
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
            "tokenInput": self._coerce_int(tokens.get("input")),
            "tokenOutput": self._coerce_int(tokens.get("output")),
            "source": "ContextForge",
        }

        metering_payload: dict[str, Any] = {
            "userEmail": context.global_context.user or "unknown",
            "teamName": context.global_context.tenant_id or "unknown",
            "appId": context.state.get("ica_app_id"),
            "userAgent": context.state.get("ica_user_agent"),
            "llmCallType": context.state.get("ica_llm_call_type"),
            "assistantName": context.state.get("ica_assistant_name"),
            "assistantUuid": context.state.get("ica_assistant_uuid"),
            "agentName": context.state.get("ica_agent_name"),
            "agentUuid": context.state.get("ica_agent_uuid"),
            "agentToolIds": context.state.get("ica_agent_tool_ids"),
            "digitalIbmerName": context.state.get("ica_digital_ibmer_name"),
            "digitalIbmerUuid": context.state.get("ica_digital_ibmer_uuid"),
            "digitalIbmerToolIds": context.state.get("ica_digital_ibmer_tool_ids"),
            "toolDetails": tool_details,
        }

        # Optional model source tracking for debugging
        if self.telemetry_config.get("include_model_source", False):
            metering_payload.setdefault("_metadata", {})["modelSource"] = model_source

        await self._send_to_ica(metering_payload)
        return ToolPostInvokeResult(continue_processing=True)

    def _resolve_model_name(  # type: ignore[no-any-unimported]  # noqa: E501
        self,
        context: PluginContext,
        headers: dict[str, Any],
        ctx_meta: dict[str, Any],
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
    def _get_header(headers: dict[str, Any], name: str) -> Optional[str]:
        """Case-insensitive lookup of a header value in a dict."""
        for key, val in headers.items():
            if isinstance(key, str) and key.lower() == name.lower() and val is not None:
                return str(val)
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        """Coerce a value to int or return None if not possible."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_service_jwt(secret: str) -> str:
        now = int(time.time())
        payload = {
            "sub": "contextforge-metering",
            "service": "mcp-context-forge",
            "instance": os.getenv("HOSTNAME", "unknown"),
            "scope": "metering:write",
            "iat": now,
            "exp": now + 86400,
        }
        return jwt.encode(payload, secret, algorithm="HS256")

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
    def _extract_tokens(result: Any) -> dict[str, Any]:
        """Safely extract token metadata from result."""
        if not isinstance(result, dict):
            return {}
        meta = result.get("meta", {})
        if not isinstance(meta, dict):
            return {}
        tokens = meta.get("tokens", {})
        return tokens if isinstance(tokens, dict) else {}

    async def _send_to_ica(self, payload: dict[str, Any]) -> None:
        """Send metering data to ICA endpoint (fire-and-forget)."""
        if not self.http_client:
            return

        metering_url = self.telemetry_config.get("metering_url")
        metering_token = self.telemetry_config.get("metering_token")

        if not metering_url:
            logger.warning("ICA metering URL not configured")
            return

        if self._jwt_secret:
            headers = {"Authorization": f"Bearer {self._get_service_jwt(self._jwt_secret)}"}
        elif metering_token:
            headers = {"X-MCP-Metering-Token": metering_token}
        else:
            logger.warning("ICA metering: neither jwt_secret nor metering_token configured")
            return

        try:
            response = await self.http_client.post(
                metering_url,
                json=payload,
                headers=headers,
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
            logger.error("ICA metering: HTTP %s: %s", e.response.status_code, e.response.text)
        except Exception as e:
            logger.error("ICA metering: Failed to send metrics: %s", e)
