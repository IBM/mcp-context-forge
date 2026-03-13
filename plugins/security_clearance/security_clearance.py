# -*- coding: utf-8 -*-
"""Location: ./plugins/security_clearance/security_clearance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Katia Neli

Bell-LaPadula Mandatory Access Control (MAC) Security Clearance Plugin.

This plugin enforces the Bell-LaPadula security model:
- No Read Up: subjects cannot read objects at a higher security level
- No Write Down: subjects cannot write to objects at a lower security level
- Lateral Communication: allowed within configured security level bands
"""
# Standard
from typing import Any, Dict, List, Optional

# Third-Party
from pydantic import BaseModel, Field

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
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
from mcpgateway.services.logging_service import LoggingService

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


# Configuration Models
class DowngradeRulesConfig(BaseModel):
    """Configuration for write-down downgrade policy.

    Example:
        >>> cfg = DowngradeRulesConfig()
        >>> cfg.enable
        False
    """

    enable: bool = Field(False, description="Allow downgrade with redaction")
    redact_fields: List[str] = Field(
        default_factory=lambda: ["password", "ssn", "api_key", "secret", "token"],
        description="Fields to redact when downgrading",
    )
    redaction_strategy: str = Field(
        "redact",
        description="redact | remove | partial",
    )
    watermark_text: str = Field(
        "[DOWNGRADED FROM LEVEL {source}]",
        description="Watermark added to downgraded content",
    )


class SecurityClearanceConfig(BaseModel):
    """Configuration schema for the SecurityClearancePlugin.

    Defines the Bell-LaPadula MAC hierarchy, entity clearances,
    enforcement policies, and audit settings.

    Example:
        >>> cfg = SecurityClearanceConfig()
        >>> cfg.levels["PUBLIC"]
        0
        >>> cfg.enforce_no_read_up
        True
        >>> cfg.default_user_clearance
        0
    """

    levels: Dict[str, int] = Field(
        default_factory=lambda: {
            "PUBLIC": 0,
            "INTERNAL": 1,
            "CONFIDENTIAL": 2,
            "SECRET": 3,
            "TOP_SECRET": 4,
            "COMPARTMENTALIZED": 5,
        },
        description="Clearance level hierarchy mapping name to integer",
    )
    enforce_no_read_up: bool = Field(True, description="Block reading data above clearance level")
    enforce_no_write_down: bool = Field(True, description="Block writing data to lower classification")
    allow_lateral: bool = Field(True, description="Allow communication within same security band")
    level_bands: List[List[int]] = Field(
        default_factory=lambda: [[0, 1], [2, 3], [4, 5]],
        description="Level bands where lateral communication is allowed",
    )
    default_user_clearance: int = Field(0, description="Default clearance for users without explicit assignment")
    default_tool_classification: int = Field(1, description="Default classification for tools without explicit assignment")
    user_clearances: Dict[str, int] = Field(default_factory=dict, description="user -> clearance level")
    team_clearances: Dict[str, int] = Field(default_factory=dict, description="team_name -> clearance level")
    tool_levels: Dict[str, int] = Field(default_factory=dict, description="tool_name -> classification level")
    server_levels: Dict[str, int] = Field(default_factory=dict, description="server_name -> classification level")
    downgrade_rules: DowngradeRulesConfig = Field(default_factory=DowngradeRulesConfig)
    audit_all_access: bool = Field(True, description="Log all clearance checks")
    audit_denied_access: bool = Field(True, description="Log denied access attempts")


# Core Access Control Logic
class ClearanceEngine:
    """Implements Bell-LaPadula MAC access control decisions.

    Example:
        >>> engine = ClearanceEngine(SecurityClearanceConfig())
        >>> engine.check_no_read_up(user_level=2, resource_level=3)
        False
        >>> engine.check_no_read_up(user_level=3, resource_level=2)
        True
        >>> engine.check_lateral(2, 3, [[0, 1], [2, 3]])
        True
        >>> engine.check_lateral(2, 4, [[0, 1], [2, 3]])
        False
    """

    def __init__(self, config: SecurityClearanceConfig):
        """Initialise the engine with the plugin configuration.

        Args:
            config: SecurityClearanceConfig instance.
        """
        self.config = config

    def resolve_user_clearance(self, user_id: Optional[str], tenant_id: Optional[str]) -> int:
        """Resolve effective clearance level for a user.

        Lookup order: user_id -> tenant_id as team -> default.

        Args:
            user_id: The user identifier (email or username).
            tenant_id: The tenant identifier used as team fallback.

        Returns:
            Integer clearance level.

        Example:
            >>> cfg = SecurityClearanceConfig(user_clearances={"alice": 3})
            >>> engine = ClearanceEngine(cfg)
            >>> engine.resolve_user_clearance("alice", None)
            3
            >>> engine.resolve_user_clearance("unknown", None)
            0
        """
        if user_id and user_id in self.config.user_clearances:
            return self.config.user_clearances[user_id]
        if tenant_id and tenant_id in self.config.team_clearances:
            return self.config.team_clearances[tenant_id]
        return self.config.default_user_clearance

    def resolve_tool_level(self, tool_name: Optional[str]) -> int:
        """Resolve classification level for a tool.

        Args:
            tool_name: The tool name.

        Returns:
            Integer classification level.

        Example:
            >>> cfg = SecurityClearanceConfig(tool_levels={"admin-panel": 3})
            >>> engine = ClearanceEngine(cfg)
            >>> engine.resolve_tool_level("admin-panel")
            3
            >>> engine.resolve_tool_level("unknown-tool")
            1
        """
        if tool_name and tool_name in self.config.tool_levels:
            return self.config.tool_levels[tool_name]
        return self.config.default_tool_classification

    def check_no_read_up(self, user_level: int, resource_level: int) -> bool:
        """Check the No Read Up (Simple Security) property.

        Args:
            user_level: Effective clearance level of the subject.
            resource_level: Classification level of the object.

        Returns:
            True if access is allowed, False if denied.

        Example:
            >>> engine = ClearanceEngine(SecurityClearanceConfig())
            >>> engine.check_no_read_up(3, 3)
            True
            >>> engine.check_no_read_up(2, 3)
            False
        """
        return user_level >= resource_level

    def check_no_write_down(self, source_level: int, dest_level: int) -> bool:
        """Check the No Write Down (Star) property.

        Args:
            source_level: Classification level of the source output.
            dest_level: Classification level of the destination context.

        Returns:
            True if write is allowed, False if denied.

        Example:
            >>> engine = ClearanceEngine(SecurityClearanceConfig())
            >>> engine.check_no_write_down(2, 2)
            True
            >>> engine.check_no_write_down(4, 2)
            False
        """
        return source_level <= dest_level

    def check_lateral(self, level_a: int, level_b: int, bands: Optional[List[List[int]]] = None) -> bool:
        """Check if two levels are in the same security band.

        Args:
            level_a: First security level.
            level_b: Second security level.
            bands: List of level bands. Defaults to config bands.

        Returns:
            True if both levels are in the same band.

        Example:
            >>> engine = ClearanceEngine(SecurityClearanceConfig())
            >>> engine.check_lateral(2, 3)
            True
            >>> engine.check_lateral(1, 4)
            False
        """
        if bands is None:
            bands = self.config.level_bands
        for band in bands:
            if level_a in band and level_b in band:
                return True
        return False

    def redact_fields(self, data: Any, fields: List[str], strategy: str = "redact") -> Any:
        """Recursively redact sensitive fields from a dict or list.

        Args:
            data: The data structure to redact.
            fields: List of field names to redact.
            strategy: One of 'redact', 'remove', 'partial'.

        Returns:
            Data with sensitive fields redacted.

        Example:
            >>> engine = ClearanceEngine(SecurityClearanceConfig())
            >>> result = engine.redact_fields({"password": "secret", "name": "Alice"}, ["password"])
            >>> result["password"]
            '[REDACTED]'
            >>> result["name"]
            'Alice'
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key in fields:
                    if strategy == "remove":
                        continue
                    elif strategy == "partial" and isinstance(value, str) and len(value) > 4:
                        result[key] = value[:2] + "***" + value[-2:]
                    else:
                        result[key] = "[REDACTED]"
                else:
                    result[key] = self.redact_fields(value, fields, strategy)
            return result
        if isinstance(data, list):
            return [self.redact_fields(item, fields, strategy) for item in data]
        return data


# Plugin Class
class SecurityClearancePlugin(Plugin):
    """Bell-LaPadula Mandatory Access Control plugin for ContextForge.

    Enforces hierarchical security clearance levels across tool invocations,
    resource fetches, and prompt renders.

    Example:
        >>> from mcpgateway.plugins.framework import PluginConfig
        >>> pc = PluginConfig(name="test", kind="security_clearance", hooks=[], mode="enforce", priority=5, config={})
        >>> plugin = SecurityClearancePlugin(pc)
        >>> plugin.name
        'test'
    """

    def __init__(self, config: PluginConfig):
        """Initialise the plugin, parsing typed config from PluginConfig.

        Args:
            config: PluginConfig provided by the plugin framework.
        """
        super().__init__(config)
        self._clearance_config = SecurityClearanceConfig(**(config.config or {}))
        self._engine = ClearanceEngine(self._clearance_config)
        logger.info(
            "SecurityClearancePlugin initialised | enforce_no_read_up=%s enforce_no_write_down=%s",
            self._clearance_config.enforce_no_read_up,
            self._clearance_config.enforce_no_write_down,
        )

    # Internal helpers
    def _get_user_context(self, context: PluginContext) -> tuple[Optional[str], Optional[str]]:
        """Extract user and tenant_id from plugin context.

        Uses context.global_context.user and context.global_context.tenant_id.

        Args:
            context: PluginContext from the framework.

        Returns:
            Tuple of (user_id, tenant_id).
        """
        gc = context.global_context
        user_id = gc.user if isinstance(gc.user, str) else None
        tenant_id = gc.tenant_id
        return user_id, tenant_id

    def _build_violation(self, code: str, reason: str) -> PluginViolation:
        """Build a PluginViolation with the given code and reason.

        Args:
            code: Violation code string.
            reason: Human-readable reason (must not leak level details).

        Returns:
            PluginViolation instance.
        """
        return PluginViolation(code=code, reason=reason)

    # Hook: tool_pre_invoke
    async def tool_pre_invoke(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> ToolPreInvokeResult:
        """Enforce No Read Up before a tool is invoked.

        Args:
            payload: Tool pre-invoke payload with tool name and arguments.
            context: Plugin context with user and tenant metadata.

        Returns:
            ToolPreInvokeResult — continue if allowed, violation if denied.
        """
        user_id, tenant_id = self._get_user_context(context)
        tool_name = getattr(payload, "tool_name", None) or getattr(payload, "name", None)

        user_level = self._engine.resolve_user_clearance(user_id, tenant_id)
        tool_level = self._engine.resolve_tool_level(tool_name)

        # Same band, lateral communication allowed
        if self._clearance_config.allow_lateral and self._engine.check_lateral(user_level, tool_level):
            if self._clearance_config.audit_all_access:
                logger.info(
                    "CLEARANCE LATERAL | user=%s user_level=%d tool=%s tool_level=%d",
                    user_id, user_level, tool_name, tool_level,
                )
            return ToolPreInvokeResult(continue_processing=True)

        # No Read Up check
        if self._clearance_config.enforce_no_read_up and not self._engine.check_no_read_up(user_level, tool_level):
            logger.warning(
                "CLEARANCE DENIED no-read-up | user=%s user_level=%d tool=%s tool_level=%d",
                user_id, user_level, tool_name, tool_level,
            )
            return ToolPreInvokeResult(
                continue_processing=False,
                violation=self._build_violation(
                    code="CLEARANCE_INSUFFICIENT",
                    reason="Insufficient security clearance to invoke this tool",
                ),
            )

        if self._clearance_config.audit_all_access:
            logger.info(
                "CLEARANCE ALLOWED | user=%s user_level=%d tool=%s tool_level=%d",
                user_id, user_level, tool_name, tool_level,
            )
        return ToolPreInvokeResult(continue_processing=True)


    async def tool_post_invoke(
        self, payload: ToolPostInvokePayload, context: PluginContext
    ) -> ToolPostInvokeResult:
        """Enforce No Write Down after a tool returns its result.

        Args:
            payload: Tool post-invoke payload with tool name and result.
            context: Plugin context with user and tenant metadata.

        Returns:
            ToolPostInvokeResult — allow, block, or redact based on policy.
        """
        user_id, tenant_id = self._get_user_context(context)
        tool_name = getattr(payload, "tool_name", None) or getattr(payload, "name", None)

        tool_level = self._engine.resolve_tool_level(tool_name)
        dest_level = self._engine.resolve_user_clearance(user_id, tenant_id)

        if self._clearance_config.enforce_no_write_down and not self._engine.check_no_write_down(tool_level, dest_level):
            downgrade = self._clearance_config.downgrade_rules
            if downgrade.enable:
                logger.warning(
                    "CLEARANCE DOWNGRADE | tool=%s tool_level=%d dest_level=%d applying redaction",
                    tool_name, tool_level, dest_level,
                )
                result = getattr(payload, "result", None)
                if isinstance(result, dict):
                    redacted = self._engine.redact_fields(
                        result, downgrade.redact_fields, downgrade.redaction_strategy
                    )
                    redacted["_clearance_notice"] = downgrade.watermark_text.format(source=tool_level)
                    return ToolPostInvokeResult(continue_processing=True, modified_payload=redacted)
            else:
                logger.warning(
                    "CLEARANCE DENIED no-write-down | tool=%s tool_level=%d dest_level=%d",
                    tool_name, tool_level, dest_level,
                )
                return ToolPostInvokeResult(
                    continue_processing=False,
                    violation=self._build_violation(
                        code="WRITE_DOWN_VIOLATION",
                        reason="Output classification exceeds destination security level",
                    ),
                )

        return ToolPostInvokeResult(continue_processing=True)


    async def resource_pre_fetch(
        self, payload: ResourcePreFetchPayload, context: PluginContext
    ) -> ResourcePreFetchResult:
        """Enforce No Read Up before a resource is fetched.

        Args:
            payload: Resource pre-fetch payload with resource URI.
            context: Plugin context with user and tenant metadata.

        Returns:
            ResourcePreFetchResult — allow or block.
        """
        user_id, tenant_id = self._get_user_context(context)
        user_level = self._engine.resolve_user_clearance(user_id, tenant_id)
        resource_level = self._clearance_config.default_user_clearance

        if self._clearance_config.enforce_no_read_up and not self._engine.check_no_read_up(user_level, resource_level):
            logger.warning(
                "CLEARANCE DENIED resource_pre_fetch | user=%s user_level=%d resource_level=%d",
                user_id, user_level, resource_level,
            )
            return ResourcePreFetchResult(
                continue_processing=False,
                violation=self._build_violation(
                    code="CLEARANCE_INSUFFICIENT",
                    reason="Insufficient security clearance to access this resource",
                ),
            )

        return ResourcePreFetchResult(continue_processing=True)


    async def resource_post_fetch(
        self, payload: ResourcePostFetchPayload, context: PluginContext
    ) -> ResourcePostFetchResult:
        """Pass-through hook — write-down check placeholder for Phase 3.

        Args:
            payload: Resource post-fetch payload with content.
            context: Plugin context with user and tenant metadata.

        Returns:
            ResourcePostFetchResult always allowing the response.
        """
        return ResourcePostFetchResult(continue_processing=True)


    async def prompt_pre_fetch(
        self, payload: PromptPrehookPayload, context: PluginContext
    ) -> PromptPrehookResult:
        """Enforce No Read Up before a prompt is rendered.

        Args:
            payload: Prompt pre-fetch payload with prompt name.
            context: Plugin context with user and tenant metadata.

        Returns:
            PromptPrehookResult — allow or block.
        """
        user_id, tenant_id = self._get_user_context(context)
        user_level = self._engine.resolve_user_clearance(user_id, tenant_id)
        prompt_level = self._clearance_config.default_user_clearance

        if self._clearance_config.enforce_no_read_up and not self._engine.check_no_read_up(user_level, prompt_level):
            logger.warning(
                "CLEARANCE DENIED prompt_pre_fetch | user=%s user_level=%d prompt_level=%d",
                user_id, user_level, prompt_level,
            )
            return PromptPrehookResult(
                continue_processing=False,
                violation=self._build_violation(
                    code="CLEARANCE_INSUFFICIENT",
                    reason="Insufficient security clearance to access this prompt",
                ),
            )

        return PromptPrehookResult(continue_processing=True)


    async def shutdown(self) -> None:
        """Graceful shutdown — release any held resources.

        Example:
            >>> from mcpgateway.plugins.framework import PluginConfig
            >>> import asyncio
            >>> pc = PluginConfig(name="t", kind="sc", hooks=[], mode="enforce", priority=1, config={})
            >>> plugin = SecurityClearancePlugin(pc)
            >>> asyncio.run(plugin.shutdown())
        """
        logger.info("SecurityClearancePlugin shutdown complete")