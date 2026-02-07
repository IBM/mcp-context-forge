# -*- coding: utf-8 -*-
"""A plugin that does policy decision and enforcement using cedar.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins.
"""

# Standard
import asyncio
import copy
import logging
import re

from enum import Enum
from typing import Any
from urllib.parse import urlparse

# Third-Party
from cedarpy import AuthzResult, Decision, is_authorized, is_authorized_batch

# First-Party
from cedarpolicyplugin.schema import CedarConfig, CedarInput
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
    PromptHookType,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ResourceHookType,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

# Initialize logging service first
logger = logging.getLogger(__name__)


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
    INVALID_CEDAR_CONFIG = "Invalid cedar configuration"
    CEDAR_POLICY_EVALUATION_ERROR = "Cedar policy evaluation error"


# Template for cedar policy
CEDAR_POLICY_TEMPLATE = """
permit(
  principal == {principal_str},
  action in [{actions_str}],
  resource == {resource_str}
);
"""


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
        self.jwt_info: dict[str, dict[str, str]] = {}
        self._cedar_policy: str | None = None
        self._output_redaction_pattern: str | re.Pattern[str] | None = "all"
        self._output_redaction_string: str = "[REDACTED]"

        # Regexes are compiled once
        self._custom_dsl_pattern = re.compile(r"\[role:([A-Za-z0-9_]+):(resource|prompt|server|agent)/([^\]]+)\]")
        redaction_spec = self.cedar_config.policy_redaction_spec

        if redaction_spec:
            self._output_redaction_string = redaction_spec.redaction_str
            if not redaction_spec.pattern:
                self._output_redaction_pattern = None
            elif redaction_spec.pattern == "all":
                self._output_redaction_pattern = "all"
            else:
                self._output_redaction_pattern = re.compile(redaction_spec.pattern)

        if self.cedar_config.policy_lang == "cedar":
            if self.cedar_config.policy:
                self._cedar_policy = self._yamlpolicy2text(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        if self.cedar_config.policy_lang == "custom_dsl":
            if self.cedar_config.policy:
                self._cedar_policy = self._dsl2cedar(self.cedar_config.policy)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_POLICY.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_POLICY.value, plugin_name="CedarPolicyPlugin"))
        logger.info(f"CedarPolicyPlugin initialised with configuration {self.cedar_config}")

    def _set_jwt_info(self, user_role_mapping: dict) -> None:
        """Sets user role mapping information from jwt tokens

        Args:
          info(dict): with user mappings
        """
        self.jwt_info["users"] = user_role_mapping

    def _create_dsl_policy_template(self, current_role: str, resource_category: str, current_actions: list, resource_name: str) -> dict[str, Any]:
        """Create a Cedar policy dict from DSL-parsed role/resource/action components.

        Args:
          current_role(str): role of the user
          resource_category(str): category of resource
          current_actions(list): a specified list of actions
          resource_name(str): name of the resource
        """
        return {
            "id": f"allow-{current_role}-{resource_category}",
            "effect": "Permit",
            "principal": f'Role::"{current_role}"',
            "action": [f'Action::"{a}"' for a in current_actions],
            "resource": f'{resource_category}::"{resource_name}"',
        }

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

    async def _evaluate_policy(self, request: dict, policy_expr: str) -> str:
        """Function that evaluates and enforce cedar policy using is_authorized function in cedarpy library
        Args:
            request(dict): The request dict consisting of principal, action, resource or context keys.
            policy_exp(str): The policy expression to evaluate the request on

        Returns:
            decision(str): "Allow" or "Deny"
        """
        result: AuthzResult = await asyncio.to_thread(is_authorized, request, policy_expr, [])
        if result.decision == Decision.NoDecision:
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.CEDAR_POLICY_EVALUATION_ERROR.value, plugin_name="CedarPolicyPlugin", details=result.diagnostics.errors))
        return "Allow" if result.decision == Decision.Allow else "Deny"

    async def _evaluate_policy_batch(self, batch_requests: dict, policy_expr: str) -> dict:
        """Function that evaluates and enforce cedar policy using is_authorized function in cedarpy library
        Args:
            request(dict): The request dict consisting of principal, action, resource or context keys.
            policy_exp(str): The policy expression to evaluate the request on

        Returns:
            decision(str): "Allow" or "Deny"
        """
        results: list[AuthzResult] = await asyncio.to_thread(is_authorized_batch, batch_requests, policy_expr, [])
        return {res.correlation_id: res.decision.value for res in results}

    def _yamlpolicy2text(self, policies: list) -> str:
        """Function to convert yaml representation of policies to text
        Args:
            policies(list): A list of cedar policies with dict values consisting of individual policies

        Returns:
            cedar_policy_text(str): string representation of policy
        """
        cedar_policy_texts = []
        for policy in policies:
            actions = policy["action"] if isinstance(policy["action"], list) else [policy["action"]]
            resources = policy["resource"] if isinstance(policy["resource"], list) else [policy["resource"]]
            for res in resources:
                cedar_policy_texts.append(CEDAR_POLICY_TEMPLATE.format(principal_str=policy["principal"], actions_str=", ".join(actions), resource_str=res))
        return "\n\n".join(cedar_policy_texts)

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
        for line in lines:
            match = self._custom_dsl_pattern.match(line)
            if match:
                if current_role and resource_category and resource_name and current_actions:
                    policies.append(
                        self._create_dsl_policy_template(current_role=current_role, resource_category=resource_category.capitalize(), current_actions=current_actions, resource_name=resource_name)
                    )
                current_role, resource_category, resource_name = match.groups()
                current_actions = []
            else:
                current_actions.append(line)

        if current_role and resource_category and resource_name and current_actions:
            policies.append(self._create_dsl_policy_template(current_role=current_role, resource_category=resource_category.capitalize(), current_actions=current_actions, resource_name=resource_name))

        cedar_policy_text = self._yamlpolicy2text(policies)
        return cedar_policy_text

    def _preprocess_request(self, user: Any = None, action: str = "", resource: str = "", hook_type: str = "", context: dict | None = None, correlation_id: str = "") -> CedarInput:
        """Function to pre process request into a format that cedar accepts
        Args:
            user(str): name of the user
            action(str): action requested by the user
            resource(str): resource requested by the user
            hook_type(str): the hook type on which invocation is made

        Returns:
            request(CedarInput): pydantic representation of request as excpected by cedar policy
        """
        if user is None:
            user = {}
        if context is None:
            context = {}
        user_role = None
        if "tool" in hook_type:
            resource_expr = CedarResourceTemplates.SERVER.format(resource_type=resource)
        elif "agent" in hook_type:
            resource_expr = CedarResourceTemplates.AGENT.format(resource_type=resource)
        elif "resource" in hook_type:
            resource_expr = CedarResourceTemplates.RESOURCE.format(resource_type=resource)
        elif "prompt" in hook_type:
            resource_expr = CedarResourceTemplates.PROMPT.format(resource_type=resource)
        else:
            logger.error(f"{CedarErrorCodes.UNSUPPORTED_RESOURCE_TYPE.value}: {hook_type}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSUPPORTED_RESOURCE_TYPE.value, plugin_name="CedarPolicyPlugin"))

        if len(self.jwt_info) > 0 and "users" in self.jwt_info:
            user_role = self.jwt_info["users"].get(user)
        elif "is_admin" in user:
            user_role = "admin" if user["is_admin"] else "non-admin"
        else:
            logger.error(f"{CedarErrorCodes.UNSPECIFIED_USER_ROLE.value}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_USER_ROLE.value, plugin_name="CedarPolicyPlugin"))

        principal_expr = f'Role::"{user_role}"'
        action_expr = f'Action::"{action}"'
        request = CedarInput(principal=principal_expr, action=action_expr, resource=resource_expr, context=context, correlation_id=correlation_id).model_dump()
        return request

    def _redact_output(self, payload: Any) -> Any:
        """Function that redacts the output of prompt, tool or resource
        NOTE: It's an extremely simple logic for redaction, could be replaced with more advanced
        as per need.
        Args:
            payload(str): payload or output
        """
        if not self.cedar_config.policy_redaction_spec:
            return payload

        if not self._output_redaction_pattern:
            return payload

        if isinstance(payload, dict):
            for key, value in payload.items():
                payload[key] = self._redact_output(value)
        elif isinstance(payload, list):
            for i, item in enumerate(payload):
                payload[i] = self._redact_output(item)
        elif isinstance(payload, str):
            if self._output_redaction_pattern == "all":
                payload = self._output_redaction_string
            else:
                payload = self._output_redaction_pattern.sub(self._output_redaction_string, payload)

        return payload

    def _get_output_request_list(self, user: str, payload: str, hook_type: str) -> list:
        """Function that takes in user, payload and hook_type to give an appended list of requests for
        full view and redacted view
        Args:
            user(str): user name or id
            payload(str): payload or output
            hook_type(str): the type of hook. For example - tool_pre_invoke, tool_post_invoke etc.
        """
        output_view_checks = []
        resource = payload

        view_full = self.cedar_config.policy_output_keywords.get("view_full", None)
        view_redacted = self.cedar_config.policy_output_keywords.get("view_redacted", None)
        if view_full:
            request = self._preprocess_request(user, view_full, resource, hook_type, context={}, correlation_id="view_full")
            output_view_checks.append(request)
        if view_redacted:
            request = self._preprocess_request(user, view_redacted, resource, hook_type, context={}, correlation_id="view_redacted")
            output_view_checks.append(request)
        return output_view_checks

    def _check_view_disallowed(self, results_map: dict) -> bool:
        """Function that takes in results of policy evaluation and then checks gives final allow or deny on view type
        Args:
            results_map(str): dict
        """
        return ("view_full" in results_map and results_map["view_full"] == "Deny") and ("view_redacted" in results_map and results_map["view_redacted"] == "Deny")

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """The plugin hook run before a prompt is retrieved and rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        hook_type = PromptHookType.PROMPT_PRE_FETCH
        logger.info(f"Processing {hook_type} for '{payload.args}' with {len(payload.args) if payload.args else 0}")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return PromptPrehookResult()

        user = ""

        if context.global_context.user:
            user = context.global_context.user

        # If a cedar policy has been defined
        if self._cedar_policy:
            # If output keywords have been defined
            if self.cedar_config.policy_output_keywords:
                output_view_checks = self._get_output_request_list(user, payload.prompt_id, hook_type)
                if len(output_view_checks) > 0:
                    results_map = await self._evaluate_policy_batch(output_view_checks, self._cedar_policy)
                    if self._check_view_disallowed(results_map):
                        violation = PluginViolation(
                            reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                            description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                            code=CedarCodes.DENIAL_CODE,
                            details={},
                        )
                        return PromptPrehookResult(modified_payload=payload, violation=violation, continue_processing=False)
                    else:
                        return PromptPrehookResult(continue_processing=True)
                else:
                    logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                    raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """Plugin hook run after a prompt is rendered.

        Args:
            payload: The prompt payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the prompt can proceed.
        """
        hook_type = PromptHookType.PROMPT_POST_FETCH
        logger.info(f"Processing {hook_type} for '{payload.result}'")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return PromptPosthookResult()

        user = ""

        if context.global_context.user:
            user = context.global_context.user

        if self._cedar_policy:
            # If output keywords have been defined
            if self.cedar_config.policy_output_keywords:
                output_view_checks = self._get_output_request_list(user, payload.prompt_id, hook_type)
                if len(output_view_checks) > 0:
                    results_map = await self._evaluate_policy_batch(output_view_checks, self._cedar_policy)
                    if "view_full" in results_map and results_map["view_full"] == "Allow":
                        return PromptPosthookResult(continue_processing=True)
                    elif "view_redacted" in results_map and results_map["view_redacted"] == "Allow":
                        if payload.result.messages:
                            for index, message in enumerate(payload.result.messages):
                                value = copy.deepcopy(message.content.text)
                                payload.result.messages[index].content.text = self._redact_output(value)
                        return PromptPosthookResult(modified_payload=payload, continue_processing=True)
                    else:
                        violation = PluginViolation(
                            reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                            description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                            code=CedarCodes.DENIAL_CODE,
                            details={},
                        )
                        return PromptPosthookResult(modified_payload=payload, violation=violation, continue_processing=False)
                else:
                    return PromptPosthookResult(continue_processing=True)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """Plugin hook run before a tool is invoked.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """
        hook_type = ToolHookType.TOOL_PRE_INVOKE
        logger.info(f"Processing {hook_type} for '{payload.args}' with {len(payload.args) if payload.args else 0}")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return ToolPreInvokeResult()

        user = ""
        server_id = ""
        if context.global_context.user:
            user = context.global_context.user

        if "gateway" in context.global_context.metadata and "name" in context.global_context.metadata["gateway"]:
            server_id = context.global_context.metadata["gateway"]["name"]
        else:
            server_id = context.global_context.server_id

        if server_id:
            request = self._preprocess_request(user, payload.name, server_id, hook_type)
        else:
            logger.error(f"{CedarErrorCodes.UNSPECIFIED_SERVER.value}")
            raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_SERVER.value, plugin_name="CedarPolicyPlugin"))

        if self._cedar_policy:
            decision = await self._evaluate_policy(request, self._cedar_policy)
            if decision == "Deny":
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
        hook_type = ToolHookType.TOOL_POST_INVOKE
        logger.info(f"Processing {hook_type} for '{payload.result}' with {len(payload.result) if payload.result else 0}")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return ToolPostInvokeResult()

        user = ""
        server_id = ""

        if context.global_context.user:
            user = context.global_context.user

        if "gateway" in context.global_context.metadata and "name" in context.global_context.metadata["gateway"]:
            server_id = context.global_context.metadata["gateway"]["name"]
        else:
            server_id = context.global_context.server_id

        # If a cedar policy has been defined
        if self._cedar_policy:
            # If output keywords have been defined
            if self.cedar_config.policy_output_keywords:
                output_view_checks = self._get_output_request_list(user, server_id, hook_type)
                if len(output_view_checks) > 0:
                    request = self._preprocess_request(user, payload.name, server_id, hook_type, context={}, correlation_id="tool")
                    output_view_checks.append(request)
                    results_map = await self._evaluate_policy_batch(output_view_checks, self._cedar_policy)
                    if results_map["tool"] == "Allow":
                        if "view_full" in results_map and results_map["view_full"] == "Allow":
                            return ToolPostInvokeResult(continue_processing=True)
                        elif "view_redacted" in results_map and results_map["view_redacted"] == "Allow":
                            data = copy.deepcopy(payload.result)
                            payload.result = self._redact_output(payload=data)
                            return ToolPostInvokeResult(continue_processing=True, modified_payload=payload)
                        else:
                            return ToolPostInvokeResult(continue_processing=True)
                    else:
                        violation = PluginViolation(
                            reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                            description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                            code=CedarCodes.DENIAL_CODE,
                            details={},
                        )
                        return ToolPostInvokeResult(modified_payload=payload, violation=violation, continue_processing=False)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
        return ToolPostInvokeResult(continue_processing=True)

    async def resource_pre_fetch(self, payload: ResourcePreFetchPayload, context: PluginContext) -> ResourcePreFetchResult:
        """Cedar Plugin hook that runs before resource fetch. This hook takes in payload and context and evaluates cedar
        policies on the input.

        Args:
            payload: The resource pre fetch input or payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource input can be passed further.
        """

        hook_type = ResourceHookType.RESOURCE_PRE_FETCH.value
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

        user = ""

        if context.global_context.user:
            user = context.global_context.user

        if self._cedar_policy:
            # If output keywords have been defined
            if self.cedar_config.policy_output_keywords:
                output_view_checks = self._get_output_request_list(user, payload.uri, hook_type)
                if len(output_view_checks) > 0:
                    results_map = await self._evaluate_policy_batch(output_view_checks, self._cedar_policy)
                    if self._check_view_disallowed(results_map):
                        violation = PluginViolation(
                            reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                            description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                            code=CedarCodes.DENIAL_CODE,
                            details={},
                        )
                        return ResourcePreFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
                    else:
                        return ResourcePreFetchResult(continue_processing=True)
                else:
                    logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                    raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))
        return ResourcePreFetchResult(continue_processing=True)

    async def resource_post_fetch(self, payload: ResourcePostFetchPayload, context: PluginContext) -> ResourcePostFetchResult:
        """Cedar Plugin hook that runs after resource post fetch. This hook takes in payload and context and evaluates cedar
        policies on the output.

        Args:
            payload: The resource post fetch output or payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the resource output can be passed further.
        """
        hook_type = ResourceHookType.RESOURCE_POST_FETCH.value
        logger.info(f"Processing {hook_type} for '{payload.uri}'")
        logger.info(f"Processing context {context}")

        user = ""

        if context.global_context.user:
            user = context.global_context.user

        if self._cedar_policy:
            # If output keywords have been defined
            if self.cedar_config.policy_output_keywords:
                output_view_checks = self._get_output_request_list(user, payload.uri, hook_type)
                if len(output_view_checks) > 0:
                    results_map = await self._evaluate_policy_batch(output_view_checks, self._cedar_policy)
                    if "view_full" in results_map and results_map["view_full"] == "Allow":
                        return ResourcePostFetchResult(continue_processing=True)
                    elif "view_redacted" in results_map and results_map["view_redacted"] == "Allow":
                        if payload.content:
                            if hasattr(payload.content, "text"):
                                value = copy.deepcopy(payload.content.text)
                                payload.content.text = self._redact_output(value)
                            return ResourcePostFetchResult(modified_payload=payload, continue_processing=True)
                    else:
                        violation = PluginViolation(
                            reason=CedarResponseTemplates.CEDAR_REASON.format(hook_type=hook_type),
                            description=CedarResponseTemplates.CEDAR_DESC.format(hook_type=hook_type),
                            code=CedarCodes.DENIAL_CODE,
                            details={},
                        )
                        return ResourcePostFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
                else:
                    return ResourcePostFetchResult(continue_processing=True)
            else:
                logger.error(f"{CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value}")
                raise PluginError(PluginErrorModel(message=CedarErrorCodes.UNSPECIFIED_OUTPUT_ACTION.value, plugin_name="CedarPolicyPlugin"))

        return ResourcePostFetchResult(continue_processing=True)
