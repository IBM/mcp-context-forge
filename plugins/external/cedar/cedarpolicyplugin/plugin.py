"""A plugin that does policy decision and enforcement using cedar.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Standard
from enum import Enum
from typing import Any
import re

# First-Party
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    PluginViolation
)

from  mcpgateway.plugins.framework import PluginConfig
from mcpgateway.plugins.framework import (
    PluginConfig,
    Plugin,
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
from mcpgateway.plugins.framework.hooks.resources import ResourcePreFetchPayload, ResourcePostFetchPayload, ResourcePreFetchResult, ResourcePostFetchResult


# Third-Party
from cedarpolicyplugin.schema import CedarConfig, CedarInput
from cedarpy import is_authorized, AuthzResult, Decision
from urllib.parse import urlparse


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

class CedarResourceTemplates(str,Enum):
    """CedarResourceTemplates implementation."""
    SERVER = 'Server::"{resource_type}"'
    AGENT = 'Agent::"{resource_type}"'
    PROMPT = 'Prompt::"{resource_type}"'
    RESOURCE = 'Resource::"{resource_type}"'


class CedarPolicyPlugin(Plugin):
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
        self.jwt_info = {}

    def _set_jwt_info(self,user_role_mapping: dict) -> None:
        """Sets user role mapping information from jwt tokens

        Args:
          info(dict): with user mappings
        """
        self.jwt_info["users"] = user_role_mapping
    
    def _extract_payload_key(self, content: Any = None, key: str = None, result: dict[str, list] = None) -> None:
        """Function to extract values of passed in key in the payload recursively based on if the content is of type list, dict
        str or pydantic structure. The value is inplace updated in result.

        Args:
            content: The content of post hook results.
            key: The key for which value needs to be extracted for.
            result: A list of all the values for a key.
        """
        if isinstance(content, list):
            for element in content:
                if isinstance(element, dict) and key in element:
                    self._extract_payload_key(element, key, result)
        elif isinstance(content, dict):
            if key in content or hasattr(content, key):
                result[key].append(content[key])
        elif isinstance(content, str):
            result[key].append(content)
        elif hasattr(content, key):
            result[key].append(getattr(content, key))
        else:
            logger.error(f"Can't handle content of {type(content)}")

    def _evaluate_policy(self,request,policy_expr):
        result: AuthzResult = is_authorized(request, policy_expr, [])
        decision = "Allow" if result.decision == Decision.Allow else "Deny"
        return decision
            
    def _yamlpolicy2text(self,yaml_policies):
        cedar_policy_text = ""
        
        for policy in yaml_policies:
            actions = policy["action"] if isinstance(policy["action"], list) else [policy["action"]]
            resources = policy["resource"] if isinstance(policy["resource"], list) else [policy["resource"]]

            for res in resources:
                actions_str = ", ".join(actions)
                cedar_policy_text += f'permit(\n'
                cedar_policy_text += f'  principal == {policy["principal"]},\n'
                cedar_policy_text += f'  action in [{actions_str}],\n'
                cedar_policy_text += f'  resource == {res}\n'
                cedar_policy_text += f');\n\n'
        
        return cedar_policy_text

    def _dsl2cedar(self,policy_string:str) -> str:
        lines = [line.strip() for line in policy_string.splitlines() if line.strip()]
        policies = []
        current_role = None
        current_resource = None
        current_actions = []
        resource_category = None
        resource_name = None


        pattern = r'\[role:([A-Za-z0-9_]+):(resource|prompt|server|agent)/([^\]]+)\]'
        for line in lines:
            match = re.match(pattern, line)
            if match:
                if current_role and resource_category and resource_name and current_actions:
                    resource_category = resource_category.capitalize()
                    policies.append({
                        "id": f"allow-{current_role}-{resource_category}",
                        "effect": "Permit",
                        "principal": f'Role::"{current_role}"',
                        "action": [f'Action::"{a}"' for a in current_actions],
                        "resource": f'{resource_category}::"{resource_name}"'
                    })
                current_role, resource_category, resource_name = match.groups()
                current_actions = []
            else:
                current_actions.append(line)
        if current_role and resource_category and resource_name and current_actions:
            resource_category = resource_category.capitalize()
            policies.append({
                "id": f"allow-{current_role}-{resource_category}",
                "effect": "Permit",
                "principal": f'Role::"{current_role}"',
                "action": [f'Action::"{a}"' for a in current_actions],
                "resource": f'{resource_category}::"{resource_name}"'
            })

        cedar_policy_text = self._yamlpolicy2text(policies)
        return cedar_policy_text
    
    def _preprocess_request(self,user,action,resource,hook_type):
        user_role = ""
        if hook_type in ["tool_post_invoke", "tool_pre_invoke"]:
            resource_expr = CedarResourceTemplates.SERVER.format(resource_type=resource)
        elif hook_type in ["agent_post_invoke", "agent_pre_invoke"]:
            resource_expr = CedarResourceTemplates.AGENT.format(resource_type=resource)
        elif hook_type in ["resource_post_fetch", "resource_pre_fetch"]:
            resource_expr = CedarResourceTemplates.RESOURCE.format(resource_type=resource)
        elif hook_type in ["prompt_post_fetch", "prompt_pre_fetch"]:
            resource_expr = CedarResourceTemplates.PROMPT.format(resource_type=resource)
        else:
            logger.error("Unsupported resource type")
        
        if len(self.jwt_info) > 0 and "users" in self.jwt_info:
            user_role = self.jwt_info["users"].get(user)
        else:
            logger.error("Unspecified user roles")
        principal_expr = f'Role::"{user_role}"'
        action_expr = f'Action::"{action}"'
        request = CedarInput(principal=principal_expr,action=action_expr,resource=resource_expr,context={}).model_dump()
        return request
    
    def _redact_output(self,payload,pattern):
        redacted_text = ""
        if not pattern:
            redacted_text = payload
        elif pattern == "all":
            redacted_text = "[REDACTED]"
        else:
            redacted_text = re.sub(pattern, "[REDACTED]", payload)
        return redacted_text


    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        hook_type = "prompt_pre_fetch"
        logger.info(f"Processing {hook_type} for '{payload.args}' with {len(payload.args) if payload.args else 0}")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return PromptPrehookResult()
        
        policy = None
        user = ""
        server_id = ""



        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
        
        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full == None and view_redacted == None:
                logger.error("Unspecified action in request")
        
        
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full and policy:
                request = self._preprocess_request(user,view_full,payload.prompt_id,hook_type)
                result_full = self._evaluate_policy(request,policy)
            if view_redacted and policy:
                request = self._preprocess_request(user,view_redacted,payload.prompt_id,hook_type)
                result_redacted = self._evaluate_policy(request,policy)
        
        if result_full == Decision.Deny.value and result_redacted == Decision.Deny.value:
            violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )
            return PromptPrehookResult(modified_payload=payload, violation=violation, continue_processing=False)
        return PromptPrehookResult(continue_processing=True)
        
    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        hook_type = "prompt_post_fetch"
        logger.info(f"Processing {hook_type} for '{payload.result}'")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return PromptPosthookResult()
        
        policy = None
        user = ""
        server_id = ""

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)

        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full == None and view_redacted == None:
                logger.error("Unspecified action in request")
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full and policy:
                request = self._preprocess_request(user,view_full,payload.prompt_id,hook_type)
                result_full = self._evaluate_policy(request,policy)
            if view_redacted and policy:
                request = self._preprocess_request(user,view_redacted,payload.prompt_id,hook_type)
                result_redacted = self._evaluate_policy(request,policy)

            if result_full == Decision.Allow.value:
                return PromptPosthookResult(continue_processing=True)
            
            elif result_redacted == Decision.Allow.value:
                if payload.result.messages:
                    for index, message in enumerate(payload.result.messages):
                        value = self._redact_output(message.content.text,self.cedar_config.policy_redaction_spec.pattern)
                        payload.result.messages[index].content.text = value
                return PromptPosthookResult(modified_payload=payload, continue_processing=True)


            else:
                violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )
                return PromptPosthookResult(modified_payload=payload, violation=violation, continue_processing=False)
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
        logger.info(f"Processing {hook_type} for '{payload.args}' with {len(payload.args) if payload.args else 0}")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return ToolPreInvokeResult()
        
        policy = None
        user = ""
        server_id = ""

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
        
        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id
        
        request = self._preprocess_request(user,payload.name,server_id,hook_type)
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

        hook_type = "tool_post_invoke"
        logger.info(f"Processing {hook_type} for '{payload.result}' with {len(payload.result) if payload.result else 0}")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return ToolPostInvokeResult()
        
        policy = None
        user = ""
        server_id = ""

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)

        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id
        
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full and policy:
                request = self._preprocess_request(user,view_full,server_id,hook_type)
                result_full = self._evaluate_policy(request,policy)
            if view_redacted and policy:
                request = self._preprocess_request(user,view_redacted,server_id,hook_type)
                result_redacted = self._evaluate_policy(request,policy)

        
        # Evaluate Policy and based on that redact output
        if policy:
            request = self._preprocess_request(user,payload.name,server_id,hook_type)
            result_action = self._evaluate_policy(request,policy)
            # Check if full output view is allowed by policy
            if result_action == Decision.Allow.value:
                if result_full == Decision.Allow.value:
                    return ToolPostInvokeResult(continue_processing=True)
                if result_redacted == Decision.Allow.value:
                    if payload.result and isinstance(payload.result, dict):
                        for key in payload.result:
                            if isinstance(payload.result[key], str):
                                value = self._redact_output(payload.result[key],self.cedar_config.policy_redaction_spec.pattern)
                                payload.result[key] = value
                    elif payload.result and isinstance(payload.result, str):
                                payload.result = self._redact_output(payload.result,self.cedar_config.policy_redaction_spec.pattern)
                    return ToolPostInvokeResult(continue_processing=True,modified_payload=payload)                       
            # If none of the redacted or full output views are allowed by policy then deny
            else:
                violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )
                return ToolPostInvokeResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ToolPostInvokeResult(continue_processing=True)
            
    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """OPA Plugin hook that runs after resource pre fetch. This hook takes in payload and context and further evaluates rego
        policies on the input by sending the request to opa server.

        Args:
            payload: The resource pre fetch input or payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource input can be passed further.
        """

        hook_type = "resource_pre_fetch"
        logger.info(f"Processing {hook_type} for '{payload.uri}'")
        logger.info(f"Processing context {context}")

        if not payload.uri:
            return ResourcePreFetchResult()
        
        try:
            parsed = urlparse(payload.uri)
        except Exception as e:
            violation = PluginViolation(reason="Invalid URI", description=f"Could not parse resource URI: {e}", code="INVALID_URI", details={"uri": payload.uri, "error": str(e)})
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Check if URI has a scheme
        if not parsed.scheme:
            violation = PluginViolation(reason="Invalid URI format", description="URI must have a valid scheme (protocol)", code="INVALID_URI", details={"uri": payload.uri})
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        policy = None
        user = ""
        server_id = ""



        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
        
        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full == None and view_redacted == None:
                logger.error("Unspecified action in request")
        
        
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full and policy:
                request = self._preprocess_request(user,view_full,payload.uri,hook_type)
                result_full = self._evaluate_policy(request,policy)
            if view_redacted and policy:
                request = self._preprocess_request(user,view_redacted,payload.uri,hook_type)
                result_redacted = self._evaluate_policy(request,policy)
        
        if result_full == Decision.Deny.value and result_redacted == Decision.Deny.value:
            violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )
            return ResourcePreFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ResourcePreFetchResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """OPA Plugin hook that runs after resource post fetch. This hook takes in payload and context and further evaluates rego
        policies on the output by sending the request to opa server.

        Args:
            payload: The resource post fetch output or payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource output can be passed further.
        """
        hook_type = "resource_post_fetch"
        logger.info(f"Processing {hook_type} for '{payload.uri}'")
        logger.info(f"Processing context {context}")
        policy = None
        user = ""
        server_id = ""

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)

        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full == None and view_redacted == None:
                logger.error("Unspecified action in request")
        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full",None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted",None)
            if view_full and policy:
                request = self._preprocess_request(user,view_full,payload.uri,hook_type)
                result_full = self._evaluate_policy(request,policy)
            if view_redacted and policy:
                request = self._preprocess_request(user,view_redacted,payload.uri,hook_type)
                result_redacted = self._evaluate_policy(request,policy)

            if result_full == Decision.Allow.value:
                return ResourcePostFetchResult(continue_processing=True)
            
            elif result_redacted == Decision.Allow.value:
                if payload.content:
                    if hasattr(payload.content,"text"):
                        value = self._redact_output(payload.content.text,self.cedar_config.policy_redaction_spec.pattern)
                        payload.content.text = value
                return ResourcePostFetchResult(modified_payload=payload, continue_processing=True)

            else:
                violation = PluginViolation(
                    reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                    description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                    code=CedarCodes.DENIAL_CODE,
                    details={},
                    )     
                return ResourcePostFetchResult(modified_payload=payload, violation=violation, continue_processing=False)   
        return ResourcePostFetchResult(continue_processing=True)
