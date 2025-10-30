"""A plugin that does policy decision and enforcement using cedar.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Standard
from enum import Enum

# First-Party
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    PluginViolation
)

from  mcpgateway.plugins.framework import PluginConfig
from  mcpgateway.plugins.mcp.entities import MCPPlugin
from  mcpgateway.plugins.mcp.entities.models import (
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookResult,
    PromptPrehookPayload
)
from mcpgateway.services.logging_service import LoggingService


# Third-Party
from cedarpolicyplugin.schema import CedarConfig, CedarInput
from cedarpy import Decision, format_policies


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CedarCodes(str, Enum):
    """OPACodes implementation."""

    ALLOW_CODE = "ALLOW"
    DENIAL_CODE = "DENY"
    AUDIT_CODE = "AUDIT"
    REQUIRES_HUMAN_APPROVAL_CODE = "REQUIRES_APPROVAL"


class CedarResponseTemplates(str, Enum):
    """OPAResponseTemplates implementation."""

    CEDAR_REASON = "Cedar policy denied for {hook_type}"
    CEDAR_DESC = "{hook_type} not allowed"


class CedarPolicyPlugin(MCPPlugin):
    """A plugin that does policy decision and enforcement using cedar."""

    def __init__(self, config: PluginConfig):
        """Entry init block for plugin.

        Args:
          logger: logger that the skill can make use of
          config: the skill configuration
        """
        super().__init__(config)
        self.cedar_config = CedarConfig.model_validate(self._config.config)
        self.opa_context_key = "cedar_policy_context"

    def _extract_jwt_info(self) -> dict:
        jwt_info = {}
        jwt_info["roles"] = ["admin", "users"]
        jwt_info["resources"] = ["tools"]
        jwt_info["actions"] = ["get_users", "submit_request"]
        jwt_info["users"] = {
            "alice": "admin",
            "bob": "users",
            "carol": "users"
        }
        return jwt_info

    def _evaluate_policy(self,user, action, resource, policies):
        jwt_info = self._extract_jwt_info()
        user_role = jwt_info["users"].get(user)
        if not user_role:
            return "Deny"  

        for policy in policies:
            if policy["principal"] == f'Role::"{user_role}"' and \
            f'Action::"{action}"' in policy["action"] and \
            policy["resource"] == f'Resource::"{resource}"':
                return policy["effect"]
            else:
                return "Deny"

    def _dsl2cedar(self,policy_string:str) -> str:
        return "policy"

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        hook_type = "tool_pre_invoke"
        logger.info(f"Processing {hook_type} for '{payload.name}' with {len(payload.args) if payload.args else 0} arguments")
        logger.info(f"Processing context {context}")
        
        if not payload.args:
            return ToolPreInvokeResult()

        policy = None
        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self.cedar_config.policy
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)  
        request = CedarInput(user=payload.args["user"],action=payload.name,resource="tools",context={}).model_dump()
        if policy:
            decision = self._evaluate_policy(request["user"], request["action"], request["resource"],policy)
            if decision == Decision.Deny.value:
                violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )
                return ToolPreInvokeResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """
        return ToolPostInvokeResult(continue_processing=True)
