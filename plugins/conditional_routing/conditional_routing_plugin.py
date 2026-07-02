# -*- coding: utf-8 -*-
"""Location: ./plugins/conditional_routing/conditional_routing_plugin.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Conditional Routing Plugin — declarative content-based and attribute-based
agent/tool dispatch.

Hooks: tool_pre_invoke, agent_pre_invoke
"""

# Future
from __future__ import annotations

# Standard
import logging
from typing import Any, Dict, List, Optional

# Third-Party
from cpex.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
    PluginViolation,
)
from cpex.framework.hooks.agents import AgentPreInvokePayload
from cpex.framework.hooks.tools import ToolPreInvokePayload

# First-Party
from .models import ConditionalRoutingConfig, DefaultAction, RoutingRule
from .rule_engine import RequestContext, RuleEngine

logger = logging.getLogger(__name__)


class ConditionalRoutingPlugin(Plugin):
    """Declarative rule-based routing to agents and tools.

    Evaluates routing rules (priority-ordered, first-match-wins) against
    incoming tool and agent invocations. Rewrites the target agent_id or
    tool_name when a rule matches, injecting override_args when configured.

    Example config in plugins/config.yaml:

    .. code-block:: yaml

        plugins:
          - name: ConditionalRoutingPlugin
            kind: plugins.conditional_routing.ConditionalRoutingPlugin
            hooks: [tool_pre_invoke, agent_pre_invoke]
            mode: enforce
            priority: 10
            config:
              default_action: passthrough
              routing_rules:
                - name: "Finance to finance agent"
                  match:
                    tool_name_pattern: "finance_*"
                    user_teams: ["accounting"]
                  route_to:
                    agent_id: "finance-specialist"
                  priority: 10
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialise the plugin with routing rules from config.

        Args:
            config: Plugin configuration containing routing_rules.
        """
        super().__init__(config)
        raw_cfg = config.config or {}
        self._cfg = ConditionalRoutingConfig(**raw_cfg)
        self._engine = RuleEngine(self._cfg.routing_rules)
        logger.info(
            "ConditionalRoutingPlugin initialised: %d rules, default_action=%s",
            len(self._cfg.routing_rules),
            self._cfg.default_action.value,
        )

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext,
    ) -> PluginResult:
        """Route tool invocations based on matching rules.

        Args:
            payload: Tool invocation payload (name, args, etc.).
            context: Plugin execution context.

        Returns:
            PluginResult with modified tool name and args if matched.
        """
        ctx = _build_request_context(
            tool_name=payload.name,
            arguments=getattr(payload, "args", None) or getattr(payload, "arguments", {}) or {},
            context=context,
        )

        decision = self._engine.evaluate(ctx)
        self._audit(decision, ctx)

        if decision.matched:
            return PluginResult(
                modified_payload=type(payload)(
                    name=decision.target_tool_name or payload.name,
                    args={
                        **(getattr(payload, "args", None) or getattr(payload, "arguments", {}) or {}),
                        **decision.override_args,
                    },
                ),
            )

        if self._cfg.default_action == DefaultAction.DENY:
            return PluginResult(
                violation=PluginViolation(
                    "NO_ROUTE_MATCHED",
                    f"No routing rule matched for tool '{payload.name}'",
                ),
            )

        # Passthrough
        return PluginResult()

    async def agent_pre_invoke(
        self,
        payload: AgentPreInvokePayload,
        context: PluginContext,
    ) -> PluginResult:
        """Route agent invocations based on matching rules.

        Args:
            payload: Agent invocation payload.
            context: Plugin execution context.

        Returns:
            PluginResult with modified agent_id if matched.
        """
        # Extract user identity from context
        user_email = context.user if hasattr(context, "user") else None
        user_teams_raw = getattr(context, "token_teams", None) or []
        if isinstance(user_teams_raw, list):
            user_teams = [str(t) for t in user_teams_raw]
        else:
            user_teams = []

        ctx = RequestContext(
            agent_id=payload.agent_id,
            user_email=user_email,
            user_teams=user_teams,
            arguments=_extract_message_text(payload),
        )

        decision = self._engine.evaluate(ctx)
        self._audit(decision, ctx)

        if decision.matched:
            return PluginResult(
                modified_payload=type(payload)(
                    agent_id=decision.target_agent_id or payload.agent_id,
                    messages=payload.messages,
                    tools=payload.tools,
                    model=payload.model,
                    system_prompt=payload.system_prompt,
                    parameters=payload.parameters,
                ),
            )

        if self._cfg.default_action == DefaultAction.DENY:
            return PluginResult(
                violation=PluginViolation(
                    "NO_ROUTE_MATCHED",
                    f"No routing rule matched for agent '{payload.agent_id}'",
                ),
            )

        return PluginResult()

    def _audit(self, decision: Any, ctx: RequestContext) -> None:
        """Emit structured audit log if enabled.

        Args:
            decision: RoutingDecision from the rule engine.
            ctx: Request context.
        """
        if not self._cfg.audit_routing_decisions:
            return

        if decision.matched:
            logger.info(
                "routing_decision: matched rule=%s target=%s priority=%s details=%s",
                decision.rule_name,
                decision.target_agent_id,
                decision.match_details.get("priority", "?"),
                decision.match_details,
            )
        else:
            logger.info(
                "routing_decision: unmatched target=%s evaluated=%d rules",
                decision.original_target,
                len(self._engine._rules),
            )


# ── Helpers ──


def _build_request_context(
    *,
    tool_name: Optional[str] = None,
    agent_id: Optional[str] = None,
    arguments: Dict[str, Any] = None,
    context: PluginContext = None,
) -> RequestContext:
    """Build a RequestContext from tool/agent payload and plugin context.

    Args:
        tool_name: Tool name from payload.
        agent_id: Agent ID from payload.
        arguments: Arguments dict.
        context: Plugin execution context with user info.

    Returns:
        Normalised RequestContext.
    """
    user_email = getattr(context, "user", None) if context else None
    user_teams_raw = getattr(context, "token_teams", None) or []
    if isinstance(user_teams_raw, list):
        user_teams = [str(t) for t in user_teams_raw]
    else:
        user_teams = []

    return RequestContext(
        tool_name=tool_name,
        agent_id=agent_id,
        arguments=arguments or {},
        user_email=user_email,
        user_teams=user_teams,
    )


def _extract_message_text(payload: AgentPreInvokePayload) -> Dict[str, Any]:
    """Extract searchable text from agent messages for content matching.

    Args:
        payload: Agent pre-invoke payload.

    Returns:
        Dict with 'messages' key containing concatenated text.
    """
    texts = []
    for msg in (payload.messages or []):
        if hasattr(msg, "content"):
            texts.append(str(msg.content))
        elif isinstance(msg, dict):
            texts.append(str(msg.get("content", "")))
    return {"messages": " ".join(texts)}
