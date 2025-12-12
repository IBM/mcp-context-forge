# -*- coding: utf-8 -*-
"""A plugin that does policy decision and enforcement using cedar.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Standard
from enum import Enum
import re
from typing import Any
from urllib.parse import urlparse

# Third-Party
from cedarpolicyplugin.schema import CedarConfig, CedarInput
from cedarpy import AuthzResult, Decision, is_authorized

# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginErrorModel,
    PluginViolation,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)
from mcpgateway.plugins.framework.hooks.resources import ResourcePostFetchPayload, ResourcePostFetchResult, ResourcePreFetchPayload, ResourcePreFetchResult
from mcpgateway.services.logging_service import LoggingService

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CedarCodes(str, Enum):
    """CedarCodes implementation."""

    ALLOW_CODE = "ALLOW"
    DENIAL_CODE = "DENY"
    AUDIT_CODE = "AUDIT"
    REQUIRES_HUMAN_APPROVAL_CODE = "REQUIRES_APPROVAL"


class CedarResponseTemplates(str, Enum):
    """CedarResponseTemplates implementation."""

    CEDAR_REASON = "Cedar policy denied for {hook_type}"
    CEDAR_DESC = "{hook_type} not allowed"


class CedarResourceTemplates(str, Enum):
    """CedarResourceTemplates implementation."""

    SERVER = 'Server::"{resource_type}"'
    AGENT = 'Agent::"{resource_type}"'
    PROMPT = 'Prompt::"{resource_type}"'
    RESOURCE = 'Resource::"{resource_type}"'


class CedarErrorCodes(str, Enum):
    """CedarPolicyPlugin errors"""

    UNSUPPORTED_RESOURCE_TYPE = "Unspecified resource types, accepted resources server, prompt, agent and resource"
    UNSPECIFIED_USER_ROLE = "User role is not defined"
    UNSPECIFIED_POLICY = "No policy has been provided"
    UNSPECIFIED_OUTPUT_ACTION = "Unspecified output action in policy configuration"
    UNSPECIFIED_SERVER = "Unspecified server for tool request"
    UNSUPPORTED_CONTENT_TYPE = "Unsupported content type"


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
        logger.info(f"CedarPolicyPlugin initialised with configuration {self.cedar_config}")

    def _set_jwt_info(self, user_role_mapping: dict) -> None:
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
            logger.error(f"{CedarErrorCodes.UNSUPPORTED_CONTENT_TYPE.value}: {type(content)}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSUPPORTED_CONTENT_TYPE.value, plugin_name="CedarPolicyPlugin"))

    def _evaluate_policy(self, request: dict, policy_expr: str) -> str:
        """Function that evaluates and enforce cedar policy using is_authorized function in cedarpy library
        Args:
            request(dict): The request dict consisting of principal, action, resource or context keys.
            policy_exp(str): The policy expression to evaluate the request on

        Returns:
            decision(str): "Allow" or "Deny"
        """
        result: AuthzResult = is_authorized(request, policy_expr, [])
        decision = "Allow" if result.decision == Decision.Allow else "Deny"
        return decision

    def _yamlpolicy2text(self, policies: list) -> str:
        """Function to convert yaml representation of policies to text
        Args:
            policies(list): A list of cedar policies with dict values consisting of individual policies

        Returns:
            cedar_policy_text(str): string representation of policy
        """
        cedar_policy_text = ""
        for policy in policies:
            actions = policy["action"] if isinstance(policy["action"], list) else [policy["action"]]
            resources = policy["resource"] if isinstance(policy["resource"], list) else [policy["resource"]]

            for res in resources:
                actions_str = ", ".join(actions)
                cedar_policy_text += "permit(\n"
                cedar_policy_text += f'  principal == {policy["principal"]},\n'
                cedar_policy_text += f"  action in [{actions_str}],\n"
                cedar_policy_text += f"  resource == {res}\n"
                cedar_policy_text += ");\n\n"

        return cedar_policy_text

    def _dsl2cedar(self, policy_string: str) -> str:
        """Function to convert custom dsl representation of policies to cedar
        Args:
            policy_string: string representation of policies

        Returns:
            cedar_policy_text(str): string representation of policy
        """
        lines = [line.strip() for line in policy_string.splitlines() if line.strip()]
        policies = []
        current_role = None
        current_actions = []
        resource_category = None
        resource_name = None

        pattern = r"\[role:([A-Za-z0-9_]+):(resource|prompt|server|agent)/([^\]]+)\]"
        for line in lines:
            match = re.match(pattern, line)
            if match:
                if current_role and resource_category and resource_name and current_actions:
                    resource_category = resource_category.capitalize()
                    policies.append(
                        {
                            "id": f"allow-{current_role}-{resource_category}",
                            "effect": "Permit",
                            "principal": f'Role::"{current_role}"',
                            "action": [f'Action::"{a}"' for a in current_actions],
                            "resource": f'{resource_category}::"{resource_name}"',
                        }
                    )
                current_role, resource_category, resource_name = match.groups()
                current_actions = []
            else:
                current_actions.append(line)
        if current_role and resource_category and resource_name and current_actions:
            resource_category = resource_category.capitalize()
            policies.append(
                {
                    "id": f"allow-{current_role}-{resource_category}",
                    "effect": "Permit",
                    "principal": f'Role::"{current_role}"',
                    "action": [f'Action::"{a}"' for a in current_actions],
                    "resource": f'{resource_category}::"{resource_name}"',
                }
            )

        cedar_policy_text = self._yamlpolicy2text(policies)
        return cedar_policy_text

    def _preprocess_request(self, user: str, action: str, resource: str, hook_type: str) -> CedarInput:
        """Function to pre process request into a format that cedar accepts
        Args:
            user(str): name of the user
            action(str): action requested by the user
            resource(str): resource requested by the user
            hook_type(str): the hook type on which invocation is made

        Returns:
            request(CedarInput): pydantic representation of request as excpected by cedar policy
        """
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
            logger.error(f"{CedarErrorCodes.UNSUPPORTED_RESOURCE_TYPE.value}: {hook_type}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSUPPORTED_RESOURCE_TYPE.value, plugin_name="CedarPolicyPlugin"))

        if len(self.jwt_info) > 0 and "users" in self.jwt_info:
            user_role = self.jwt_info["users"].get(user)
        else:
            logger.error(f"{CedarErrorCodes.UNSPECIFIED_USER_ROLE.value}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_USER_ROLE.value, plugin_name="CedarPolicyPlugin"))

        principal_expr = f'Role::"{user_role}"'
        action_expr = f'Action::"{action}"'
        request = CedarInput(principal=principal_expr, action=action_expr, resource=resource_expr, context={}).model_dump()
        return request

    def _redact_output(self, payload: str, pattern: str) -> str:
        """Function that redacts the output of prompt, tool or resource
        NOTE: It's an extremely simple logic for redaction, could be replaced with more advanced
        as per need.
        Args:
            payload(str): payload or output
            pattern(str): regex expression to replace
        Returns:
            redacted_text(str): redacted representation of payload string
        """
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
        result_full = None
        result_redacted = None

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
            if not view_full and not view_redacted:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
            if view_full and policy:
                request = self._preprocess_request(user, view_full, payload.prompt_id, hook_type)
                result_full = self._evaluate_policy(request, policy)
            if view_redacted and policy:
                request = self._preprocess_request(user, view_redacted, payload.prompt_id, hook_type)
                result_redacted = self._evaluate_policy(request, policy)

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
        result_full = None
        result_redacted = None

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
            if not view_full and not view_redacted:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
            if view_full and policy:
                request = self._preprocess_request(user, view_full, payload.prompt_id, hook_type)
                result_full = self._evaluate_policy(request, policy)
            if view_redacted and policy:
                request = self._preprocess_request(user, view_redacted, payload.prompt_id, hook_type)
                result_redacted = self._evaluate_policy(request, policy)

            if result_full == Decision.Allow.value:
                return PromptPosthookResult(continue_processing=True)

            if result_redacted == Decision.Allow.value:
                if payload.result.messages:
                    for index, message in enumerate(payload.result.messages):
                        value = self._redact_output(message.content.text, self.cedar_config.policy_redaction_spec.pattern)
                        payload.result.messages[index].content.text = value
                return PromptPosthookResult(modified_payload=payload, continue_processing=True)

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
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id

        if server_id:
            request = self._preprocess_request(user, payload.name, server_id, hook_type)
        else:
            logger.error(f"{CedarErrorCodes.UNSPECIFIED_SERVER.value}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_SERVER.value, plugin_name="CedarPolicyPlugin"))

        if policy:
            decision = self._evaluate_policy(request, policy)
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
        result_full = None
        result_redacted = None

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user
            server_id = context.global_context.server_id

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
            if not view_full and not view_redacted:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
            if view_full and policy:
                request = self._preprocess_request(user, view_full, server_id, hook_type)
                result_full = self._evaluate_policy(request, policy)
            if view_redacted and policy:
                request = self._preprocess_request(user, view_redacted, server_id, hook_type)
                result_redacted = self._evaluate_policy(request, policy)

        # Evaluate Policy and based on that redact output
        if policy:
            request = self._preprocess_request(user, payload.name, server_id, hook_type)
            result_action = self._evaluate_policy(request, policy)
            # Check if full output view is allowed by policy
            if result_action == Decision.Allow.value:
                if result_full == Decision.Allow.value:
                    return ToolPostInvokeResult(continue_processing=True)
                if result_redacted == Decision.Allow.value:
                    if payload.result and isinstance(payload.result, dict):
                        for key in payload.result:
                            if isinstance(payload.result[key], str):
                                value = self._redact_output(payload.result[key], self.cedar_config.policy_redaction_spec.pattern)
                                payload.result[key] = value
                    elif payload.result and isinstance(payload.result, str):
                        payload.result = self._redact_output(payload.result, self.cedar_config.policy_redaction_spec.pattern)
                    return ToolPostInvokeResult(continue_processing=True, modified_payload=payload)
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
        result_full = None
        result_redacted = None

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
            if not view_full and not view_redacted:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
            if view_full and policy:
                request = self._preprocess_request(user, view_full, payload.uri, hook_type)
                result_full = self._evaluate_policy(request, policy)
            if view_redacted and policy:
                request = self._preprocess_request(user, view_redacted, payload.uri, hook_type)
                result_redacted = self._evaluate_policy(request, policy)

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
        result_full = None
        result_redacted = None

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))

        if context.global_context.user:
            user = context.global_context.user

        if self.cedar_config.policy_output_keywords:
            view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
            view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
            if not view_full and not view_redacted:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
            if view_full and policy:
                request = self._preprocess_request(user, view_full, payload.uri, hook_type)
                result_full = self._evaluate_policy(request, policy)
            if view_redacted and policy:
                request = self._preprocess_request(user, view_redacted, payload.uri, hook_type)
                result_redacted = self._evaluate_policy(request, policy)

            if result_full == Decision.Allow.value:
                return ResourcePostFetchResult(continue_processing=True)

            if result_redacted == Decision.Allow.value:
                if payload.content:
                    if hasattr(payload.content, "text"):
                        value = self._redact_output(payload.content.text, self.cedar_config.policy_redaction_spec.pattern)
                        payload.content.text = value
                return ResourcePostFetchResult(modified_payload=payload, continue_processing=True)

            violation = PluginViolation(
                reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                code=CedarCodes.DENIAL_CODE,
                details={},
            )
            return ResourcePostFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ResourcePostFetchResult(continue_processing=True)
