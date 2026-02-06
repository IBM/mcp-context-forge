# -*- coding: utf-8 -*-
"""Location: ./plugins/examples/cdm_tool_allowlist/cdm_tool_allowlist.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

CDM Tool Allowlist Plugin - Example demonstrating tool and resource access control.

This plugin shows how to use the Common Data Model's MessageView to implement
allowlist-based access control for tools and resources using URI patterns.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    MessageHookType,
    MessagePayload,
    MessageResult,
)
from mcpgateway.plugins.framework.cdm.view import ViewKind, ViewAction
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CDMToolAllowlistConfig(BaseModel):
    """Configuration for the CDM Tool Allowlist plugin."""

    # Tool allowlist (glob patterns)
    allowed_tools: List[str] = Field(
        default_factory=list,
        description="Allowed tool URI patterns (e.g., 'tool://*/search', 'tool://mcp/*')",
    )
    blocked_tools: List[str] = Field(
        default_factory=list,
        description="Explicitly blocked tool patterns (checked before allowlist)",
    )

    # Resource allowlist
    allowed_resources: List[str] = Field(
        default_factory=list,
        description="Allowed resource URI patterns (e.g., 'file:///safe/**')",
    )
    blocked_resources: List[str] = Field(
        default_factory=list,
        description="Explicitly blocked resource patterns",
    )

    # Prompt allowlist
    allowed_prompts: List[str] = Field(
        default_factory=list,
        description="Allowed prompt URI patterns",
    )

    # Behavior
    default_allow_tools: bool = Field(
        default=False,
        description="Allow tools not matching any pattern (less secure)",
    )
    default_allow_resources: bool = Field(
        default=False,
        description="Allow resources not matching any pattern",
    )
    default_allow_prompts: bool = Field(
        default=True,
        description="Allow prompts not matching any pattern",
    )
    log_decisions: bool = Field(
        default=True,
        description="Log allow/deny decisions",
    )


class CDMToolAllowlistPlugin(Plugin):
    """Tool and resource allowlist using CDM MessageView.

    This plugin demonstrates how to:
    1. Use MessageView.uri for tool/resource identification
    2. Use matches_uri_pattern() for glob matching
    3. Use ViewKind to differentiate tools, resources, prompts
    4. Use ViewAction to understand what operation is being performed
    """

    def __init__(self, config: PluginConfig):
        """Initialize the plugin."""
        super().__init__(config)
        self.allowlist_config = CDMToolAllowlistConfig.model_validate(self._config.config)

        logger.info(
            f"CDMToolAllowlistPlugin initialized: "
            f"{len(self.allowlist_config.allowed_tools)} tool patterns, "
            f"{len(self.allowlist_config.allowed_resources)} resource patterns"
        )

    def _check_patterns(
        self,
        uri: str,
        view: Any,
        allowed: List[str],
        blocked: List[str],
        default_allow: bool,
    ) -> tuple[bool, Optional[str]]:
        """Check URI against allowed/blocked patterns.

        Args:
            uri: The URI to check.
            view: The MessageView for pattern matching.
            allowed: List of allowed patterns.
            blocked: List of blocked patterns.
            default_allow: Default decision if no patterns match.

        Returns:
            Tuple of (is_allowed, matching_pattern).
        """
        # Check blocked patterns first
        for pattern in blocked:
            if view.matches_uri_pattern(pattern):
                return (False, pattern)

        # Check allowed patterns
        for pattern in allowed:
            if view.matches_uri_pattern(pattern):
                return (True, pattern)

        # No pattern matched - use default
        return (default_allow, None)

    async def message_evaluate(
        self, payload: MessagePayload, context: PluginContext
    ) -> MessageResult:
        """Evaluate a message for tool/resource access control.

        This method demonstrates how to use MessageView to:
        - Get URIs for tools, resources, and prompts
        - Match against allowlist patterns
        - Use ViewAction to understand the operation

        Args:
            payload: The CDM Message to evaluate.
            context: Plugin execution context.

        Returns:
            MessageResult with potential violation if access denied.
        """
        # Get views from the message
        views = payload.view(context)

        for view in views:
            uri = view.uri
            if not uri:
                continue

            # Check tool calls
            if view.kind == ViewKind.TOOL_CALL:
                allowed, pattern = self._check_patterns(
                    uri,
                    view,
                    self.allowlist_config.allowed_tools,
                    self.allowlist_config.blocked_tools,
                    self.allowlist_config.default_allow_tools,
                )

                if self.allowlist_config.log_decisions:
                    action = "ALLOWED" if allowed else "BLOCKED"
                    match_info = f" (matched: {pattern})" if pattern else " (no match, default)"
                    logger.info(f"Tool {action}: {uri}{match_info}")

                if not allowed:
                    violation = PluginViolation(
                        reason="Tool not allowed",
                        description=f"Tool '{view.name}' is not in the allowlist",
                        code="TOOL_NOT_ALLOWED",
                        details={
                            "uri": uri,
                            "tool_name": view.name,
                            "action": view.action.value if view.action else None,
                            "matched_pattern": pattern,
                        },
                    )
                    return MessageResult(continue_processing=False, violation=violation)

            # Check resource access
            elif view.kind in (ViewKind.RESOURCE, ViewKind.RESOURCE_REF):
                allowed, pattern = self._check_patterns(
                    uri,
                    view,
                    self.allowlist_config.allowed_resources,
                    self.allowlist_config.blocked_resources,
                    self.allowlist_config.default_allow_resources,
                )

                if self.allowlist_config.log_decisions:
                    action = "ALLOWED" if allowed else "BLOCKED"
                    match_info = f" (matched: {pattern})" if pattern else " (no match, default)"
                    logger.info(f"Resource {action}: {uri}{match_info}")

                if not allowed:
                    violation = PluginViolation(
                        reason="Resource not allowed",
                        description=f"Resource '{uri}' is not in the allowlist",
                        code="RESOURCE_NOT_ALLOWED",
                        details={
                            "uri": uri,
                            "resource_name": view.name,
                            "action": view.action.value if view.action else None,
                            "matched_pattern": pattern,
                        },
                    )
                    return MessageResult(continue_processing=False, violation=violation)

            # Check prompt requests
            elif view.kind == ViewKind.PROMPT_REQUEST:
                allowed, pattern = self._check_patterns(
                    uri,
                    view,
                    self.allowlist_config.allowed_prompts,
                    [],  # No blocked prompts by default
                    self.allowlist_config.default_allow_prompts,
                )

                if self.allowlist_config.log_decisions:
                    action = "ALLOWED" if allowed else "BLOCKED"
                    match_info = f" (matched: {pattern})" if pattern else " (no match, default)"
                    logger.info(f"Prompt {action}: {uri}{match_info}")

                if not allowed:
                    violation = PluginViolation(
                        reason="Prompt not allowed",
                        description=f"Prompt '{view.name}' is not in the allowlist",
                        code="PROMPT_NOT_ALLOWED",
                        details={
                            "uri": uri,
                            "prompt_name": view.name,
                            "matched_pattern": pattern,
                        },
                    )
                    return MessageResult(continue_processing=False, violation=violation)

        return MessageResult()

    async def shutdown(self) -> None:
        """Cleanup when plugin shuts down."""
        logger.info("CDMToolAllowlistPlugin shutting down")
