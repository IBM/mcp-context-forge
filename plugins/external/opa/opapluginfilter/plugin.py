# -*- coding: utf-8 -*-
"""An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module loads configurations for plugins and applies hooks on pre/post requests for tools, prompts and resources.
"""

# Standard
from enum import Enum
from typing import Any, Union, TypeAlias
from urllib.parse import urlparse

# Third-Party
import requests


# First-Party
from mcpgateway.plugins.framework import (
    Plugin,
    PluginConfig,
    PluginContext,
    PluginViolation,
    PromptPosthookPayload,
    PromptPosthookResult,
    PromptPrehookPayload,
    PromptPrehookResult,
    ToolPostInvokePayload,
    ToolPostInvokeResult,
    ToolPreInvokePayload,
    ToolPreInvokeResult,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ResourcePreFetchResult,
    ResourcePostFetchResult
)
from mcpgateway.plugins.framework.models import AppliedTo
from mcpgateway.services.logging_service import LoggingService
from opapluginfilter.schema import BaseOPAInputKeys, OPAConfig, OPAInput


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class OPACodes(str,Enum):
    ALLOW_CODE = "ALLOW"
    DENIAL_CODE = "DENY"
    AUDIT_CODE = "AUDIT"
    REQUIRES_HUMAN_APPROVAL_CODE = "REQUIRES_APPROVAL"

class OPAResponseTemplates(str,Enum):
    OPA_REASON = "OPA policy denied for {hook_type}"
    OPA_DESC = "{hook_type} not allowed"

HookPayload: TypeAlias = (
    ToolPreInvokePayload |
    ToolPostInvokePayload |
    PromptPosthookPayload |
    PromptPrehookPayload |
    ResourcePreFetchPayload |
    ResourcePostFetchPayload
)


class OPAPluginFilter(Plugin):
    """An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies."""

    def __init__(self, config: PluginConfig):
        """Entry init block for plugin.

        Args:
          logger: logger that the skill can make use of
          config: the skill configuration
        """
        super().__init__(config)
        self.opa_config = OPAConfig.model_validate(self._config.config)
        self.opa_context_key = "opa_policy_context"

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

        Returns:
            True, json_response if the opa policy is allowed else false. The json response is the actual response returned by OPA server.
            If OPA server encountered any error, the return would be True (to gracefully exit) and None would be the json_response, marking
            an issue with the OPA server running.

        """

        def _key(k: str, m: str) -> str:
            return f"{k}.{m}" if k.split(".")[0] == "context" else k

        payload = {"input": {m: self._get_nested_value(input.model_dump()["input"], _key(k, m)) for k, m in policy_input_data_map.items()}} if policy_input_data_map else input.model_dump()
        logger.info(f"OPA url {url}, OPA payload {payload}")
        rsp = requests.post(url, json=payload)
        logger.info(f"OPA connection response '{rsp}'")
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
                logger.debug(f"OPA sent a none response {json_response}")
        else:
            logger.debug(f"OPA error: {rsp}")
        return True, None

    def _preprocess_opa(self,policy_apply_config:AppliedTo = None ,payload: HookPayload = None, context : PluginContext = None,hook_type : str = None) -> dict:
        """Function to preprocess input for OPA server based on the type of hook it's invoked on.

        Args:
            policy_apply_config: The policy configuration to be applied on tool, prompts or resources.
            payload: The paylod of any of the hooks, pre-post tool, prompts or resources.
            context: The context provided by PluginContext
            hook_type: The type of the hook on which preprocessing needs to be applied,  pre-post tool, prompts or resources.

        Returns:
            dict: if a valid policy_apply_config, payload and hook_type, otherwise returns dictionary with none values

        """
        result = {
            "opa_server_url" : None,
            "policy_context" : None,
            "policy_input_data_map" : None,
            "policy_modality" : None
        }

        if not(policy_apply_config and payload and hook_type):
            logger.error(f"Unspecified required: {policy_apply_config} and payload: {payload} and hook_type: {hook_type}")
            return result

        input_context = []
        policy_context = {}
        policy = None
        policy_endpoint = None
        policy_input_data_map = {}
        hook_name = None

        if policy_apply_config:
            if "tool" in hook_type and policy_apply_config.tools:
                hook_info = policy_apply_config.tools
            elif "prompt" in hook_type and  policy_apply_config.prompts:
                hook_info = policy_apply_config.prompts
            elif "resource" in hook_type and  policy_apply_config.resources:
                hook_info = policy_apply_config.resources
            else:
                logger.error("The hooks should belong to either of the following: tool, prompts and resources")
                return result

            for hook in hook_info:
                if "tool" in hook_type:
                    hook_name = hook.tool_name
                    payload_name = payload.name
                elif "prompt" in hook_type:
                    hook_name = hook.prompt_name
                    payload_name = payload.name
                elif "resource" in hook_type:
                    hook_name = hook.resource_uri
                    payload_name = payload.uri
                else:
                    logger.error("The hooks should belong to either of the following: tool, prompts and resources")
                    return result

                if payload_name == hook_name or hook_name in payload_name:
                    if hook.context:
                        input_context = [ctx.rsplit(".", 1)[-1] for ctx in hook.context]
                    if self.opa_context_key in context.global_context.state:
                        policy_context = {k: context.global_context.state[self.opa_context_key][k] for k in input_context}
                    if hook.extensions:
                        policy = hook.extensions.get("policy")
                        policy_endpoints = hook.extensions.get("policy_endpoints", [])
                        policy_input_data_map = hook.extensions.get("policy_input_data_map", {})
                        policy_modality = hook.extensions.get("policy_modality", ["text"])
                        if policy_endpoints:
                            policy_endpoint = next((endpoint for endpoint in policy_endpoints if hook_type in endpoint),"allow")

        if not policy_endpoint:
            logger.debug(f"Unconfigured endpoint for policy {hook_type} {hook_name} invocation")
            return result

        result["policy_context"] = policy_context
        result["opa_server_url"] = "{opa_url}{policy}/{policy_endpoint}".format(opa_url=self.opa_config.opa_base_url, policy=policy, policy_endpoint=policy_endpoint)
        result["policy_input_data_map"] = policy_input_data_map
        result["policy_modality"] = policy_modality
        return result

    def _extract_payload_key(self, content: Any = None, key: str = None, result: dict[str,list] = None) -> None:
        """Function to extract values of passed in key in the payload recursively based on if the content is of type list, dict
        str or pydantic structure. The value is inplace updated in result.

        Args:
            content: The content of post hook results.
            key: The key for which value needs to be extracted for.
            result: A list of all the values for a key.

        Returns:
            None

        """
        if isinstance(content,list):
            for element in content:
                if isinstance(element,dict) and key in element:
                    self._extract_payload_key(element,key,result)
        elif isinstance(content,dict):
            if key in content or hasattr(content,key):
                result[key].append(content[key])
        elif isinstance(content,str):
            result[key].append(content)
        elif hasattr(content,key):
            result[key].append(getattr(content,key))
        else:
            logger.error(f"Can't handle content of {type(content)}")


    async def prompt_pre_fetch(self, payload: PromptPrehookPayload, context: PluginContext) -> PromptPrehookResult:
        """OPA Plugin hook run before a prompt is fetched. This hook takes in payload and context and further evaluates rego
        policies on the prompt input by sending the request to opa server.

        Args:
            payload: The prompt pre hook payload to be analyzed.
            context: Contextual information about the hook call.

        Returns:
            The result of the plugin's analysis, including whether prompt input could proceed further.
        """

        hook_type = "prompt_pre_fetch"
        logger.info(f"Processing {hook_type} for '{payload.name}' with {len(payload.args) if payload.args else 0} arguments")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return PromptPosthookResult()

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.prompts:
            opa_pre_prompt_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if not all(v is None for v in opa_pre_prompt_input.values()):
                opa_input = BaseOPAInputKeys(kind="post_tool", user="none", payload=payload.model_dump(), context=opa_pre_prompt_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(url=opa_pre_prompt_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_prompt_input["policy_input_data_map"])
                if not decision:
                        violation = PluginViolation(
                            reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                            description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                            code=OPACodes.DENIAL_CODE,
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

        hook_type = "prompt_post_fetch"
        logger.info(f"Processing {hook_type} for '{payload.result}'")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return PromptPosthookResult()

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.prompts:
            opa_post_prompt_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if opa_post_prompt_input:
                result = dict.fromkeys(opa_post_prompt_input["policy_modality"],[])

            if hasattr(payload.result,"messages") and isinstance(payload.result.messages,list):
                for message in payload.result.messages:
                    if hasattr(message,"content"):
                        for key in opa_post_prompt_input["policy_modality"]:
                            self._extract_payload_key(message.content,key,result)

                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_prompt_input["policy_context"], request_ip="none", headers={},mode="output")
                decision, decision_context = self._evaluate_opa_policy(url=opa_post_prompt_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_prompt_input["policy_input_data_map"])
                if not decision:
                        violation = PluginViolation(
                            reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                            description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                            code=OPACodes.DENIAL_CODE,
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

        hook_type = "tool_pre_invoke"
        logger.info(f"Processing {hook_type} for '{payload.name}' with {len(payload.args) if payload.args else 0} arguments")
        logger.info(f"Processing context {context}")

        if not payload.args:
            return ToolPreInvokeResult()

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.tools:
            opa_pre_tool_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if opa_pre_tool_input:
                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=payload.model_dump(), context=opa_pre_tool_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(url=opa_pre_tool_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_tool_input["policy_input_data_map"])
                if not decision:
                        violation = PluginViolation(
                            reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                            description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                            code=OPACodes.DENIAL_CODE,
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

        hook_type = "tool_post_invoke"
        logger.info(f"Processing {hook_type} for '{payload.result}' with {len(payload.result) if payload.result else 0}")
        logger.info(f"Processing context {context}")

        if not payload.result:
            return ToolPostInvokeResult()
        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.tools:
            opa_post_tool_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if opa_post_tool_input:
                result = dict.fromkeys(opa_post_tool_input["policy_modality"],[])

            if isinstance(payload.result,dict):
                content = payload.result["content"] if "content" in payload.result else payload.result
                for key in opa_post_tool_input["policy_modality"]:
                        self._extract_payload_key(content,key,result)

                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_tool_input["policy_context"], request_ip="none", headers={},mode="output")
                decision, decision_context = self._evaluate_opa_policy(url=opa_post_tool_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_tool_input["policy_input_data_map"])
                if not decision:
                        violation = PluginViolation(
                            reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                            description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                            code=OPACodes.DENIAL_CODE,
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

        hook_type = "resource_pre_fetch"
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
            opa_pre_resource_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if not all(v is None for v in opa_pre_resource_input.values()):
                opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=payload.model_dump(), context=opa_pre_resource_input["policy_context"], request_ip="none", headers={}, mode="input")
                decision, decision_context = self._evaluate_opa_policy(url=opa_pre_resource_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_pre_resource_input["policy_input_data_map"])
                if not decision:
                        violation = PluginViolation(
                            reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                            description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                            code=OPACodes.DENIAL_CODE,
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

        hook_type = "resource_post_fetch"
        logger.info(f"Processing {hook_type} for '{payload.content}' and uri {payload.uri}")
        logger.info(f"Processing context {context}")

        policy_apply_config = self._config.applied_to
        if policy_apply_config and policy_apply_config.resources:
            opa_post_resource_input = self._preprocess_opa(policy_apply_config,payload,context,hook_type)
            if not all(v is None for v in opa_post_resource_input.values()):
                result = dict.fromkeys(opa_post_resource_input["policy_modality"],[])
                for key in opa_post_resource_input["policy_modality"]:
                    if hasattr(payload.content,key):
                        self._extract_payload_key(payload.content,key,result)
                    opa_input = BaseOPAInputKeys(kind=hook_type, user="none", payload=result, context=opa_post_resource_input["policy_context"], request_ip="none", headers={},mode="output")
                    decision, decision_context = self._evaluate_opa_policy(url=opa_post_resource_input["opa_server_url"], input=OPAInput(input=opa_input), policy_input_data_map=opa_post_resource_input["policy_input_data_map"])
                    if not decision:
                            violation = PluginViolation(
                                reason=OPAResponseTemplates.OPA_REASON.format(hook_type=hook_type),
                                description=OPAResponseTemplates.OPA_DESC.format(hook_type=hook_type),
                                code=OPACodes.DENIAL_CODE,
                                details=decision_context,
                            )
                            return ResourcePostFetchResult(modified_payload=payload, violation=violation, continue_processing=False)
        return ResourcePostFetchResult(continue_processing=True)
