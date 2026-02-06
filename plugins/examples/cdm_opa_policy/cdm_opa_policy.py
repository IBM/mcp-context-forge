# -*- coding: utf-8 -*-
"""Location: ./plugins/examples/cdm_opa_policy/cdm_opa_policy.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

CDM OPA Policy Plugin - Example demonstrating OPA integration using CDM MessageView.

This plugin shows how to serialize MessageView to JSON and send it to an
Open Policy Agent (OPA) server for policy decisions.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginErrorModel,
    PluginViolation,
    MessageHookType,
    MessagePayload,
    MessageResult,
)
from mcpgateway.plugins.framework.cdm.view import ViewKind
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CDMOpaPolicyConfig(BaseModel):
    """Configuration for the CDM OPA Policy plugin."""

    opa_url: str = Field(
        default="http://localhost:8181/v1/data/apex/allow",
        description="OPA policy endpoint URL",
    )
    timeout_seconds: float = Field(
        default=5.0,
        description="HTTP timeout for OPA requests",
    )
    fail_open: bool = Field(
        default=False,
        description="Allow if OPA is unreachable (fail-open vs fail-closed)",
    )
    include_content: bool = Field(
        default=True,
        description="Include message content in OPA input (may be large)",
    )
    evaluate_per_view: bool = Field(
        default=False,
        description="Evaluate each view separately (vs entire message)",
    )
    log_decisions: bool = Field(
        default=True,
        description="Log OPA decisions",
    )


class CDMOpaPolicyPlugin(Plugin):
    """OPA policy evaluation using CDM MessageView.

    This plugin demonstrates how to:
    1. Use MessageView.to_dict() to serialize views to JSON
    2. Use Message.to_opa_input() for full message serialization
    3. Send policy requests to OPA
    4. Handle OPA responses and make allow/deny decisions

    Example OPA policy (Rego):

        package apex

        default allow = false

        # Allow if no tool calls
        allow {
            count([v | v := input.views[_]; v.kind == "tool_call"]) == 0
        }

        # Allow safe tools
        allow {
            some i
            view := input.views[i]
            view.kind == "tool_call"
            startswith(view.name, "read_")
        }

        # Block dangerous tools in production
        deny[msg] {
            some i
            view := input.views[i]
            view.kind == "tool_call"
            view.name == "execute_shell"
            view.context.environment == "production"
            msg := "Shell execution blocked in production"
        }
    """

    def __init__(self, config: PluginConfig):
        """Initialize the plugin."""
        super().__init__(config)
        self.opa_config = CDMOpaPolicyConfig.model_validate(self._config.config)
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.opa_config.timeout_seconds)
        )
        logger.info(f"CDMOpaPolicyPlugin initialized with OPA URL: {self.opa_config.opa_url}")

    async def _query_opa(self, input_data: dict[str, Any]) -> tuple[bool, Optional[dict]]:
        """Query OPA for a policy decision.

        Args:
            input_data: The input data to send to OPA.

        Returns:
            Tuple of (allow, response_data).
        """
        try:
            response = await self._http_client.post(
                self.opa_config.opa_url,
                json=input_data,
            )
            response.raise_for_status()
            result = response.json()

            # OPA returns {"result": true/false} or {"result": {"allow": true/false}}
            decision = result.get("result")
            if isinstance(decision, bool):
                return decision, result
            elif isinstance(decision, dict):
                return decision.get("allow", False), result
            else:
                logger.warning(f"Unexpected OPA response format: {result}")
                return self.opa_config.fail_open, result

        except httpx.HTTPError as e:
            logger.error(f"OPA HTTP error: {e}")
            if self.opa_config.fail_open:
                return True, None
            raise PluginError(
                PluginErrorModel(
                    message="OPA server error",
                    plugin_name="CDMOpaPolicyPlugin",
                    details={"error": str(e)},
                )
            )

    async def _evaluate_view(
        self, view: Any, context: PluginContext
    ) -> tuple[bool, Optional[dict]]:
        """Evaluate a single view against OPA.

        Args:
            view: The MessageView to evaluate.
            context: Plugin context.

        Returns:
            Tuple of (allow, response_data).
        """
        opa_input = view.to_opa_input(include_content=self.opa_config.include_content)
        return await self._query_opa(opa_input)

    async def _evaluate_message(
        self, message: MessagePayload, context: PluginContext
    ) -> tuple[bool, Optional[dict]]:
        """Evaluate entire message against OPA.

        Args:
            message: The CDM Message to evaluate.
            context: Plugin context.

        Returns:
            Tuple of (allow, response_data).
        """
        opa_input = message.to_opa_input(
            ctx=context,
            include_content=self.opa_config.include_content,
        )
        return await self._query_opa(opa_input)

    async def message_evaluate(
        self, payload: MessagePayload, context: PluginContext
    ) -> MessageResult:
        """Evaluate a message using OPA policy.

        This method demonstrates two evaluation modes:
        1. Per-message: Send entire message to OPA once
        2. Per-view: Send each view separately for granular decisions

        Args:
            payload: The CDM Message to evaluate.
            context: Plugin execution context.

        Returns:
            MessageResult with potential violation if OPA denies.
        """
        if self.opa_config.evaluate_per_view:
            # Evaluate each view separately
            views = payload.view(context)
            for view in views:
                allowed, result = await self._evaluate_view(view, context)

                if self.opa_config.log_decisions:
                    decision = "ALLOWED" if allowed else "DENIED"
                    logger.info(f"OPA {decision} view: kind={view.kind.value}, uri={view.uri}")

                if not allowed:
                    # Extract denial reason from OPA response
                    reason = "Policy denied"
                    details = {}
                    if result:
                        deny_reasons = result.get("result", {}).get("deny", [])
                        if deny_reasons:
                            reason = deny_reasons[0] if isinstance(deny_reasons[0], str) else str(deny_reasons[0])
                        details = result

                    violation = PluginViolation(
                        reason=reason,
                        description=f"OPA policy denied {view.kind.value}: {view.uri or view.name}",
                        code="OPA_POLICY_DENIED",
                        details={
                            "view_kind": view.kind.value,
                            "uri": view.uri,
                            "name": view.name,
                            "opa_response": details,
                        },
                    )
                    return MessageResult(continue_processing=False, violation=violation)

        else:
            # Evaluate entire message at once
            allowed, result = await self._evaluate_message(payload, context)

            if self.opa_config.log_decisions:
                decision = "ALLOWED" if allowed else "DENIED"
                logger.info(f"OPA {decision} message: role={payload.role.value}")

            if not allowed:
                reason = "Policy denied"
                details = {}
                if result:
                    deny_reasons = result.get("result", {}).get("deny", [])
                    if deny_reasons:
                        reason = deny_reasons[0] if isinstance(deny_reasons[0], str) else str(deny_reasons[0])
                    details = result

                violation = PluginViolation(
                    reason=reason,
                    description="OPA policy denied message",
                    code="OPA_POLICY_DENIED",
                    details={
                        "role": payload.role.value,
                        "opa_response": details,
                    },
                )
                return MessageResult(continue_processing=False, violation=violation)

        return MessageResult()

    async def shutdown(self) -> None:
        """Cleanup HTTP client when plugin shuts down."""
        await self._http_client.aclose()
        logger.info("CDMOpaPolicyPlugin shutting down")
