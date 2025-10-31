"""A plugin that does policy decision and enforcement using cedar.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Standard
from enum import Enum
import re

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
from cedarpy import is_authorized, AuthzResult, Decision


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
        self.cedar_context_key = "cedar_policy_context"

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

    def _evaluate_policy(self,request,policy_expr):
        result: AuthzResult = is_authorized(request, policy_expr, [])
        decision = "Permit" if result.decision == Decision.Allow else "Deny"
        return decision
            
    def _yamlpolicy2text(self,yaml_policies):
        cedar_policy_text = ""
        for policy in yaml_policies:
            actions_str = ", ".join(policy["action"])
            cedar_policy_text += f'permit(\n'
            cedar_policy_text += f'  principal == {policy["principal"]},\n'
            cedar_policy_text += f'  action in [{actions_str}],\n'
            cedar_policy_text += f'  resource == {policy["resource"]}\n'
            cedar_policy_text += f');\n\n'
        return cedar_policy_text

    def _dsl2cedar(self,policy_string:str) -> str:
        lines = [line.strip() for line in policy_string.splitlines() if line.strip()]
        policies = []
        current_role = None
        current_resource = None
        current_actions = []

        for line in lines:
            match = re.match(r'\[role:(\w+):(\w+)\]', line)
            if match:
                if current_role and current_resource and current_actions:
                    policies.append({
                        "id": f"allow-{current_role}-{current_resource}",
                        "effect": "Permit",
                        "principal": f'Role::"{current_role}"',
                        "action": [f'Action::"{a}"' for a in current_actions],
                        "resource": f'Resource::"{current_resource}"'
                    })
                current_role, current_resource = match.groups()
                current_actions = []
            else:
                current_actions.append(line)
        if current_role and current_resource and current_actions:
            policies.append({
                "id": f"allow-{current_role}-{current_resource}",
                "effect": "Permit",
                "principal": f'Role::"{current_role}"',
                "action": [f'Action::"{a}"' for a in current_actions],
                "resource": f'Resource::"{current_resource}"'
            })

        cedar_policy_text = self._yamlpolicy2text(policies)
        return cedar_policy_text
    
    def _preprocess_request(self,user,action,resource):
        jwt_info = self._extract_jwt_info()
        user_role = jwt_info["users"].get(user)
        principal_expr = f'Role::"{user_role}"'
        action_expr = f'Action::"{action}"'
        resource_expr = f'Resource::"{resource}"'
        request = CedarInput(principal=principal_expr,action=action_expr,resource=resource_expr,context={}).model_dump()
        return request

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
        

        policy = None
        user = ""
        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy) 

        if context.global_context.user:
            user = context.global_context.user
        
        request = self._preprocess_request(user,payload.name,"tools")
        import pdb
        pdb.set_trace()
        if policy:
            decision = self._evaluate_policy(request,policy)
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
