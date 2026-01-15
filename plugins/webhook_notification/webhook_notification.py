# -*- coding: utf-8 -*-
"""Location: ./plugins/webhook_notification/webhook_notification.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Webhook Notification Plugin.
Sends HTTP webhook notifications on specific events, violations, or state changes.
Supports multiple webhooks, event filtering, retry logic, and authentication.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

# Third-Party
import httpx
import orjson
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.config import settings
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Event types for webhook notifications."""

    VIOLATION = "violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    PII_DETECTED = "pii_detected"
    HARMFUL_CONTENT = "harmful_content"
    TOOL_SUCCESS = "tool_success"
    TOOL_ERROR = "tool_error"
    PROMPT_SUCCESS = "prompt_success"
    RESOURCE_SUCCESS = "resource_success"
    PLUGIN_ERROR = "plugin_error"


class AuthenticationType(str, Enum):
    """Authentication types for webhook requests."""

    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    HMAC = "hmac"


class AuthenticationConfig(BaseModel):
    """Authentication configuration for webhooks."""

    type: AuthenticationType = AuthenticationType.NONE
    token: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    hmac_secret: Optional[str] = None
    hmac_algorithm: str = "sha256"
    hmac_header: str = "X-Signature"


class WebhookConfig(BaseModel):
    """Configuration for a single webhook endpoint."""

    url: str = Field(description="Webhook URL")
    events: List[EventType] = Field(default_factory=lambda: [EventType.VIOLATION])
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)
    retry_attempts: int = Field(default=3, ge=0, le=10)
    retry_delay: int = Field(default=1000, ge=100, le=60000, description="Delay in milliseconds")
    timeout: int = Field(default=10, ge=1, le=120, description="Request timeout in seconds")
    enabled: bool = True


class WebhookNotificationConfig(BaseModel):
    """Configuration for the webhook notification plugin."""

    webhooks: List[WebhookConfig] = Field(default_factory=list)
    payload_templates: Dict[str, str] = Field(default_factory=dict)
    default_template: str = Field(
        default="""{
    "event": "{{event}}",
    "plugin": "{{plugin_name}}",
    "timestamp": "{{timestamp}}",
    "request_id": "{{request_id}}",
    "user": "{{user}}",
    "tenant_id": "{{tenant_id}}",
    "server_id": "{{server_id}}",
    "violation": {{violation}},
    "metadata": {{metadata}}
}"""
    )
    include_payload_data: bool = Field(default=False, description="Include request payload in notifications")
    max_payload_size: int = Field(default=1000, description="Max payload size to include in notifications")


class WebhookNotificationPlugin(Plugin):
    """Plugin for sending webhook notifications on events and violations."""

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the webhook notification plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = WebhookNotificationConfig(**(config.config or {}))
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                keepalive_expiry=settings.httpx_keepalive_expiry,
            ),
            timeout=httpx.Timeout(
                connect=settings.httpx_connect_timeout,
                read=settings.httpx_read_timeout,
                write=settings.httpx_write_timeout,
                pool=settings.httpx_pool_timeout,
            ),
        )

    async def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """Render a Jinja2-style template with the given context.

        Args:
            template: The template string to render.
            context: The context dictionary for template rendering.

        Returns:
            str: The rendered template string.
        """
        # Simple template substitution for now - could be enhanced with Jinja2
        result = template
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            if value is None:
                result = result.replace(placeholder, "null")
            elif isinstance(value, (dict, list)):
                result = result.replace(placeholder, orjson.dumps(value).decode())
            else:
                result = result.replace(placeholder, str(value))
        return result

    def _create_hmac_signature(self, payload: str, secret: str, algorithm: str) -> str:
        """Create HMAC signature for the payload.

        Args:
            payload: The payload to sign.
            secret: The secret key for HMAC.
            algorithm: The hash algorithm to use.

        Returns:
            str: The HMAC signature string.
        """
        hash_func = getattr(hashlib, algorithm, hashlib.sha256)
        signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hash_func).hexdigest()
        return f"{algorithm}={signature}"

    async def _send_webhook(
        self,
        webhook: WebhookConfig,
        event: EventType,
        context: PluginContext,
        violation: Optional[PluginViolation] = None,
        metadata: Optional[Dict[str, Any]] = None,
        payload_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a webhook notification with retry logic.

        Args:
            webhook: The webhook configuration.
            event: The event type to notify.
            context: The plugin context.
            violation: Optional violation details.
            metadata: Optional metadata dictionary.
            payload_data: Optional payload data dictionary.
        """
        if not webhook.enabled or event not in webhook.events:
            return

        # Prepare context for template rendering
        template_context = {
            "event": event.value,
            "plugin_name": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": context.global_context.request_id,
            "user": context.global_context.user,
            "tenant_id": context.global_context.tenant_id,
            "server_id": context.global_context.server_id,
            "violation": violation.dict() if violation else None,
            "metadata": metadata or {},
        }

        # Add payload data if enabled and size is reasonable
        if self._cfg.include_payload_data and payload_data:
            payload_str = orjson.dumps(payload_data).decode()
            if len(payload_str) <= self._cfg.max_payload_size:
                template_context["payload"] = payload_data

        # Select template
        template = self._cfg.payload_templates.get(event.value, self._cfg.default_template)

        try:
            payload_json = await self._render_template(template, template_context)
            payload_bytes = payload_json.encode("utf-8")
        except Exception as e:
            logger.error(f"Failed to render webhook template for {event.value}: {e}")
            return

        # Prepare headers
        headers = {"Content-Type": "application/json", "User-Agent": "MCP-Gateway-Webhook-Plugin/1.0"}

        # Add authentication
        auth_config = webhook.authentication
        if auth_config.type == AuthenticationType.BEARER and auth_config.token:
            headers["Authorization"] = f"Bearer {auth_config.token}"
        elif auth_config.type == AuthenticationType.API_KEY and auth_config.api_key:
            headers[auth_config.api_key_header] = auth_config.api_key
        elif auth_config.type == AuthenticationType.HMAC and auth_config.hmac_secret:
            signature = self._create_hmac_signature(payload_json, auth_config.hmac_secret, auth_config.hmac_algorithm)
            headers[auth_config.hmac_header] = signature

        # Attempt delivery with retry logic
        for attempt in range(webhook.retry_attempts + 1):
            try:
                response = await self._client.post(webhook.url, content=payload_bytes, headers=headers, timeout=webhook.timeout)

                if 200 <= response.status_code < 300:
                    logger.debug(f"Webhook delivered successfully to {webhook.url} on attempt {attempt + 1}")
                    return
                else:
                    logger.warning(f"Webhook delivery failed with status {response.status_code} to {webhook.url}")

            except Exception as e:
                logger.warning(f"Webhook delivery attempt {attempt + 1} failed to {webhook.url}: {e}")

            # Don't sleep after the last attempt
            if attempt < webhook.retry_attempts:
                delay_seconds = webhook.retry_delay / 1000.0 * (2**attempt)  # Exponential backoff
                await asyncio.sleep(delay_seconds)

        logger.error(f"All webhook delivery attempts failed for {webhook.url}")

    async def _notify_webhooks(
        self, event: EventType, context: PluginContext, violation: Optional[PluginViolation] = None, metadata: Optional[Dict[str, Any]] = None, payload_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send notifications to all configured webhooks.

        Args:
            event: The event type to notify.
            context: The plugin context.
            violation: Optional violation details.
            metadata: Optional metadata dictionary.
            payload_data: Optional payload data dictionary.
        """
        if not self._cfg.webhooks:
            return

        # Send webhooks concurrently
        tasks = [self._send_webhook(webhook, event, context, violation, metadata, payload_data) for webhook in self._cfg.webhooks]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _determine_event_type(self, violation: Optional[PluginViolation]) -> EventType:
        """Determine event type based on violation details.

        Args:
            violation: Optional violation details.

        Returns:
            EventType: The determined event type.
        """
        if not violation:
            return EventType.TOOL_SUCCESS

        if violation.code == "RATE_LIMIT":
            return EventType.RATE_LIMIT_EXCEEDED
        elif "pii" in violation.reason.lower():
            return EventType.PII_DETECTED
        elif "harmful" in violation.reason.lower() or "content" in violation.reason.lower():
            return EventType.HARMFUL_CONTENT
        else:
            return EventType.VIOLATION

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """Hook for prompt pre-fetch events.

        Args:
            payload: The prompt pre-hook payload.
            context: The plugin context.

        Returns:
            PromptPrehookResult: The result of the pre-fetch hook.
        """
        return PromptPrehookResult()

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Hook for prompt post-fetch events.

        Args:
            payload: The prompt post-hook payload.
            context: The plugin context.

        Returns:
            PromptPosthookResult: The result of the post-fetch hook.
        """
        await self._notify_webhooks(EventType.PROMPT_SUCCESS, context, metadata={"prompt_id": payload.prompt_id})
        return PromptPosthookResult()

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Hook for tool pre-invoke events.

        Args:
            payload: The tool pre-invoke payload.
            context: The plugin context.

        Returns:
            ToolPreInvokeResult: The result of the pre-invoke hook.
        """
        return ToolPreInvokeResult()

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Hook for tool post-invoke events.

        Args:
            payload: The tool post-invoke payload.
            context: The plugin context.

        Returns:
            ToolPostInvokeResult: The result of the post-invoke hook.
        """
        # Check if there was an error in the result
        event = EventType.TOOL_SUCCESS
        metadata = {"tool_name": payload.name}

        if hasattr(payload.result, "error") and payload.result.error:
            event = EventType.TOOL_ERROR
            metadata["error"] = str(payload.result.error)

        payload_data = None
        if self._cfg.include_payload_data:
            payload_data = {"tool_name": payload.name, "args": payload.result}

        await self._notify_webhooks(event, context, metadata=metadata, payload_data=payload_data)
        return ToolPostInvokeResult()

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Hook for resource pre-fetch events.

        Args:
            payload: The resource pre-fetch payload.
            context: The plugin context.

        Returns:
            ResourcePreFetchResult: The result of the pre-fetch hook.
        """
        return ResourcePreFetchResult()

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Hook for resource post-fetch events.

        Args:
            payload: The resource post-fetch payload.
            context: The plugin context.

        Returns:
            ResourcePostFetchResult: The result of the post-fetch hook.
        """
        await self._notify_webhooks(EventType.RESOURCE_SUCCESS, context, metadata={"resource_uri": payload.uri})
        return ResourcePostFetchResult()

    async def shutdown(self) -> None:
        """Shutdown and cleanup HTTP client when plugin shuts down."""
        client = getattr(self, "_client", None)
        if client:
            await client.aclose()
            self._client = None

    async def __aenter__(self):
        """Async context manager entry.

        Returns:
            WebhookNotificationPlugin: The plugin instance.
        """
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        """Async context manager exit - cleanup HTTP client."""
        await self.shutdown()
