# -*- coding: utf-8 -*-
"""An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins and applies hooks on pre/post requests for tools, prompts and resources.
"""

# Standard
from enum import Enum
from typing import Any, TypeAlias
from urllib.parse import urlparse

# Third-Party
import requests

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
    PromptHookType,
    ResourcePostFetchPayload,
    ResourcePostFetchResult,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ResourceHookType,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ToolHookType,
)
from mcpgateway.plugins.framework.models import AppliedTo
from mcpgateway.services.logging_service import LoggingService
from opapluginfilter.schema import BaseOPAInputKeys, OPAConfig, OPAInput

# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class OPAPluginCodes(str, Enum):
    """OPAPluginCodes implementation."""

    ALLOW_CODE = "ALLOW"
    DENIAL_CODE = "DENY"
    AUDIT_CODE = "AUDIT"
    REQUIRES_HUMAN_APPROVAL_CODE = "REQUIRES_APPROVAL"


class OPAPluginResponseTemplates(str, Enum):
    """OPAPluginResponseTemplates implementation."""

    OPA_REASON = "OPA policy denied for {hook_type}"
    OPA_DESC = "{hook_type} not allowed"


class OPAPluginErrorCodes(str, Enum):
    """OPA plugin error codes or reasons when raising plugin error"""

    OPA_SERVER_NONE_RESPONSE = "OPA server returned an empty response"
    OPA_SERVER_ERROR = "Error while communicating with the OPA server"
    OPA_SERVER_UNCONFIGURED_ENDPOINT = "Policy endpoint not configured on the OPA server"
    UNSPECIFIED_REQUIRED_PARAMS = "Required parameters missing: policy config, payload, or hook type"
    UNSUPPORTED_HOOK_TYPE = "Unsupported hook type (only tool, prompt, and resource are supported)"
    INVALID_POLICY_ENDPOINT = "Policy endpoint must be curated with the supported hooktypes"
    UNSPECIFIED_POLICY_MODALITY = "Unspecified policy modality. Picking up default modality: text"
    UNSUPPORTED_POLICY_MODALITY = "Unsupported policy modality (Supports text, image and resource)"
    UNSPECIFIED_POLICY_PACKAGE_NAME = "Unspecified policy package name"


HookPayload: TypeAlias = ToolPreInvokePayload | ToolPostInvokePayload | PromptPosthookPayload | PromptPrehookPayload | ResourcePreFetchPayload | ResourcePostFetchPayload


class OPAPluginFilter(Plugin):
    """An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies."""

    def __init__(self, config: PluginConfig):
        """Entry init block for plugin.

        Args:
            config: the skill configuration
        """
        super().__init__(config)
        self.opa_config = OPAConfig.model_validate(self._config.config)
        self.opa_context_key = "opa_policy_context"
        logger.info(f"OPAPluginFilter initialised with configuraiton {self.opa_config}")

    def _get_nested_value(self, data, key_string, default=None):
        """
        Retrieves a value from a nested dictionary using a dot-notation string.

        Args:
            data (dict): The dictionary to search within.
            key_string (str): The dot-notation string representing the path to the value.
            default (any, optional): The value to return if the key path is not found.
                                    Defaults to None.

        Returns:
            any: The value at the specified key path, or the default value if not found.
        """
        keys = key_string.split(".")
        current_data = data
        for key in keys:
            if isinstance(current_data, dict) and key in current_data:
                current_data = current_data[key]
            else:
                return default  # Key not found at this level
        return current_data

    def _evaluate_opa_policy(self, url: str, input: OPAInput, policy_input_data_map: dict) -> tuple[bool, Any]:
        """Function to evaluate OPA policy. Makes a request to opa server with url and input.

        Args:
            url: The url to call opa server
            input: Contains the payload of input to be sent to opa server for policy evaluation.
            policy_input_data_map: Mapping of policy input data keys.

        Returns:
            tuple[bool, Any]: True, json_response if the opa policy is allowed else false. The json response is the actual response returned by OPA server.
            If OPA server encountered any error, the return would be True (to gracefully exit) and None would be the json_response, marking
            an issue with the OPA server running.

        """

        def _key(k: str, m: str) -> str:
            """Key implementation.

            Args:
                k: The key string.
                m: The mapping string.

            Returns:
                str: Combined key string.
            """

            return f"{k}.{m}" if k.split(".")[0] == "context" else k

        payload = {"input": {m: self._get_nested_value(input.model_dump()["input"], _key(k, m)) for k, m in policy_input_data_map.items()}} if policy_input_data_map else input.model_dump()
        logger.info(f"OPA url {url}, OPA payload {payload}")
        try:
            rsp = requests.post(url, json=payload)
            logger.info(f"OPA connection response '{rsp}'")
        except Exception as e:
            logger.error(f"{OPAPluginErrorCodes.OPA_SERVER_ERROR.value}")
            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.OPA_SERVER_ERROR.value, plugin_name="OPAPluginFilter", details={"reason": str(e)}))
        if rsp.status_code == 200:
            json_response = rsp.json()
            decision = json_response.get("result", None)
            logger.info(f"OPA server response '{json_response}'")
            if isinstance(decision, bool):
                logger.debug(f"OPA decision {decision}")
                return decision, json_response
            elif isinstance(decision, dict) and "allow" in decision:
                allow = decision["allow"]
                logger.debug(f"OPA decision {allow}")
                return allow, json_response
            else:
                logger.error(f"{OPAPluginErrorCodes.OPA_SERVER_NONE_RESPONSE.value} : {json_response}")
                raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.OPA_SERVER_NONE_RESPONSE.value, plugin_name="OPAPluginFilter", details={"reason": json_response}))

        else:
            logger.error(f"{OPAPluginErrorCodes.OPA_SERVER_ERROR.value}: {rsp}")
            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.OPA_SERVER_ERROR.value, plugin_name="OPAPluginFilter", details={"reason": rsp}))

    def _preprocess_opa(self, policy_apply_config: AppliedTo = None, payload: HookPayload = None, context: PluginContext = None, hook_type: str = None) -> dict:
        """Function to preprocess input for OPA server based on the type of hook it's invoked on.

        Args:
            policy_apply_config: The policy configuration to be applied on tool, prompts or resources.
            payload: The paylod of any of the hooks, pre-post tool, prompts or resources.
            context: The context provided by PluginContext
            hook_type: The type of the hook on which preprocessing needs to be applied,  pre-post tool, prompts or resources.

        Returns:
            dict: if a valid policy_apply_config, payload and hook_type, otherwise returns dictionary with none values

        """
        result = {"opa_server_url": None, "policy_context": None, "policy_input_data_map": None, "policy_modality": None, "policy_apply": None}

        if not (policy_apply_config and payload and hook_type):
            logger.error(f"{OPAPluginErrorCodes.UNSPECIFIED_REQUIRED_PARAMS.value} {policy_apply_config} and payload: {payload} and hook_type: {hook_type}")
            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSPECIFIED_REQUIRED_PARAMS.value, plugin_name="OPAPluginFilter"))

        input_context = []
        policy_context = {}
        policy = None
        policy_endpoint = None
        policy_input_data_map = {}
        policy_modality = None
        hook_name = None
        policy_apply = False

        if policy_apply_config:
            if "tool" in hook_type and policy_apply_config.tools:
                hook_info = policy_apply_config.tools
            elif "prompt" in hook_type and policy_apply_config.prompts:
                hook_info = policy_apply_config.prompts
            elif "resource" in hook_type and policy_apply_config.resources:
                hook_info = policy_apply_config.resources
            else:
                raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSUPPORTED_HOOK_TYPE.value, plugin_name="OPAPluginFilter"))

            for hook in hook_info:
                if "tool" in hook_type:
                    hook_name = hook.tool_name
                    payload_name = payload.name
                elif "prompt" in hook_type:
                    hook_name = hook.prompt_name
                    payload_name = payload.prompt_id
                elif "resource" in hook_type:
                    hook_name = hook.resource_uri
                    payload_name = payload.uri
                else:
                    logger.error(f"{OPAPluginErrorCodes.UNSUPPORTED_HOOK_TYPE.value}: {hook}")
                    raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSUPPORTED_HOOK_TYPE.value, plugin_name="OPAPluginFilter"))

                if payload_name == hook_name or hook_name in payload_name:
                    policy_apply = True
                    if hook.context:
                        input_context = [ctx.rsplit(".", 1)[-1] for ctx in hook.context]
                    if self.opa_context_key in context.global_context.state:
                        policy_context = {k: context.global_context.state[self.opa_context_key][k] for k in input_context}
                    if hook.extensions:
                        policy = hook.extensions.get("policy", None)
                        if not policy:
                            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSPECIFIED_POLICY_PACKAGE_NAME.value, plugin_name="OPAPluginFilter"))
                        policy_endpoints = hook.extensions.get("policy_endpoints", [])
                        policy_input_data_map = hook.extensions.get("policy_input_data_map", {})
                        if "policy_modality" not in hook.extensions:
                            logger.error(f"{OPAPluginErrorCodes.UNSPECIFIED_POLICY_MODALITY.value}")
                            policy_modality = hook.extensions.get("policy_modality", ["text"])
                        else:
                            policy_modality = hook.extensions.get("policy_modality", ["text"])
                        all_hook_types = [hook.value for hook in ToolHookType] + [hook.value for hook in PromptHookType] + [hook.value for hook in ResourceHookType]
                        all_hook_flag = 0
                        for hook in all_hook_types:
                            for endpoint in policy_endpoints:
                                if hook in endpoint:
                                    all_hook_flag += 1
                        if len(policy_endpoints) != all_hook_flag:
                            if "allow" not in policy_endpoints:
                                raise PluginError(
                                    PluginErrorModel(message=OPAPluginErrorCodes.INVALID_POLICY_ENDPOINT, plugin_name="OPAPluginFilter", details={"reason": f"Supported hook type: {all_hook_types}"})
                                )
                        if policy_endpoints:
                            policy_endpoint = next((endpoint for endpoint in policy_endpoints if hook_type in endpoint), "allow")
                        else:
                            logger.error(f"{OPAPluginErrorCodes.OPA_SERVER_UNCONFIGURED_ENDPOINT.value} {hook_type} {hook_name} invocation")
                            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.OPA_SERVER_UNCONFIGURED_ENDPOINT.value, plugin_name="OPAPluginFilter"))

        result["policy_context"] = policy_context
        result["opa_server_url"] = "{opa_url}{policy}/{policy_endpoint}".format(opa_url=self.opa_config.opa_base_url, policy=policy, policy_endpoint=policy_endpoint)
        result["policy_input_data_map"] = policy_input_data_map
        result["policy_modality"] = policy_modality
        result["policy_apply"] = policy_apply
        return result

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
                else:
                    logger.error(f"{OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value}: {type(content)}")
                    raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value, plugin_name="OPAPluginFilter"))
        elif isinstance(content, dict):
            if key in content or hasattr(content, key):
                result[key].append(content[key])
            else:
                logger.error(f"{OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value}: {type(content)}")
                raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value, plugin_name="OPAPluginFilter"))
        elif isinstance(content, str):
            result[key].append(content)
        elif hasattr(content, key):
            result[key].append(getattr(content, key))
        else:
            logger.error(f"{OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value}: {type(content)}")
            raise PluginError(PluginErrorModel(message=OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value, plugin_name="OPAPluginFilter"))

    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """OPA Plugin hook run before a prompt is fetched. This hook takes in payload and context and further evaluates rego
        policies on the prompt input by sending the request to opa server.

        Args:
            payload: The prompt pre hook payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether prompt input could proceed further.
        """

        hook_type = PromptHookType.PROMPT_PRE_FETCH.value
        logger.info(f"Processing {hook_type} for '{payload.prompt_id}' with {len(payload.args) if payload.args else 0} arguments")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return PromptPosthookResult()

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.prompts:
            opa_pre_prompt_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_pre_prompt_input["policy_apply"]:
                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=payload.model_dump(), context=opa_pre_prompt_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_pre_prompt_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_prompt_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
                    )
                    return PromptPrehookResult(modified_payload=payload, violation=violation, continue_processing=False)
        return PromptPrehookResult(continue_processing=True)

    async def prompt_post_fetch(self, payload: PromptPosthookPayload, context: PluginContext) -> PromptPosthookResult:
        """OPA Plugin hook run after a prompt is fetched. This hook takes in payload and context and further evaluates rego
        policies on the prompt output by sending the request to opa server.

        Args:
            payload: The prompt post hook payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether prompt result could proceed further.
        """

        hook_type = PromptHookType.PROMPT_POST_FETCH.value
        logger.info(f"Processing {hook_type} for '{payload.result}'")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return PromptPosthookResult()

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.prompts:
            opa_post_prompt_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_post_prompt_input["policy_apply"]:
                result = dict.fromkeys(opa_post_prompt_input["policy_modality"], [])

                if hasattr(payload.result, "messages") and isinstance(payload.result.messages, list):
                    for message in payload.result.messages:
                        if hasattr(message, "content"):
                            for key in opa_post_prompt_input["policy_modality"]:
                                self._extract_payload_key(message.content, key, result)

                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_prompt_input["policy_context"], request_ip="none", headers={}, mode="output")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_post_prompt_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_prompt_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
                    )
                    return PromptPosthookResult(modified_payload=payload, violation=violation, continue_processing=False)
        return PromptPosthookResult(continue_processing=True)

    async def tool_pre_invoke(self, payload: ToolPreInvokePayload, context: PluginContext) -> ToolPreInvokeResult:
        """OPA Plugin hook run before a tool is invoked. This hook takes in payload and context and further evaluates rego
        policies on the input by sending the request to opa server.

        Args:
            payload: The tool payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool can proceed.
        """

        hook_type = ToolHookType.TOOL_PRE_INVOKE.value
        logger.info(f"Processing {hook_type} for '{payload.name}' with {len(payload.args) if payload.args else 0} arguments")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return ToolPreInvokeResult()

        policy_apply_config = self._config.applied_to
        logger.info(f"policy_apply_config {policy_apply_config}")
        if policy_apply_config and policy_apply_config.tools:
            opa_pre_tool_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_pre_tool_input["policy_apply"]:
                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=payload.model_dump(), context=opa_pre_tool_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_pre_tool_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_tool_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
                    )
                    return ToolPreInvokeResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ToolPreInvokeResult(continue_processing=True)

    async def tool_post_invoke(self, payload: ToolPostInvokePayload, context: PluginContext) -> ToolPostInvokeResult:
        """Plugin hook run after a tool is invoked. This hook takes in payload and context and further evaluates rego
        policies on the tool output by sending the request to opa server.

        Args:
            payload: The tool result payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether the tool result should proceed.
        """

        hook_type = ToolHookType.TOOL_POST_INVOKE.value
        logger.info(f"Processing {hook_type} for '{payload.result}' with {len(payload.result) if payload.result else 0}")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return ToolPostInvokeResult()
        policy_apply_config = self._config.applied_to

        if policy_apply_config and policy_apply_config.tools:
            opa_post_tool_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_post_tool_input["policy_apply"]:
                result = dict.fromkeys(opa_post_tool_input["policy_modality"], [])

                if isinstance(payload.result, dict):
                    content = payload.result["content"] if "content" in payload.result else payload.result
                    for key in opa_post_tool_input["policy_modality"]:
                        self._extract_payload_key(content, key, result)

                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_tool_input["policy_context"], request_ip="none", headers={}, mode="output")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_post_tool_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_tool_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
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

        if not payload.uri:
            return ResourcePreFetchResult()

        hook_type = ResourceHookType.RESOURCE_PRE_FETCH.value
        logger.info(f"Processing {hook_type} for '{payload.uri}'")
        logger.info(f"Processing context {context}")

        try:
            parsed = urlparse(payload.uri)
        except Exception as e:
            violation = PluginViolation(reason="Invalid URI", description=f"Could not parse resource URI: {e}", code="INVALID_URI", details={"uri": payload.uri, "error": str(e)})
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        # Check if URI has a scheme
        if not parsed.scheme:
            violation = PluginViolation(reason="Invalid URI format", description="URI must have a valid scheme (protocol)", code="INVALID_URI", details={"uri": payload.uri})
            return ResourcePreFetchResult(continue_processing=False, violation=violation)

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.resources:
            opa_pre_resource_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_pre_resource_input["policy_apply"]:
                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=payload.model_dump(), context=opa_pre_resource_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_pre_resource_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_resource_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
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

        if not payload.content or not payload.uri:
            return ResourcePostFetchResult()

        hook_type = ResourceHookType.RESOURCE_POST_FETCH.value
        logger.info(f"Processing {hook_type} for '{payload.content}' and uri {payload.uri}")
        logger.info(f"Processing context {context}")

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.resources:
            opa_post_resource_input = self._preprocess_opa(policy_apply_config, payload, context, hook_type)
            if opa_post_resource_input["policy_apply"]:
                result = dict.fromkeys(opa_post_resource_input["policy_modality"], [])
                for key in opa_post_resource_input["policy_modality"]:
                    if hasattr(payload.content, key):
                        self._extract_payload_key(payload.content, key, result)

                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_resource_input["policy_context"], request_ip="none", headers={}, mode="output")
                decision, decision_context = self._evaluate_opa_policy(
                    url=opa_post_resource_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_resource_input["policy_input_data_map"]
                )
                if not decision:
                    violation = PluginViolation(
                        reason=OPAPluginResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                        description=OPAPluginResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                        code=OPAPluginCodes.DENIAL_CODE,
                        details=decision_context,
                    )
                    return ResourcePostFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ResourcePostFetchResult(continue_processing=True)
