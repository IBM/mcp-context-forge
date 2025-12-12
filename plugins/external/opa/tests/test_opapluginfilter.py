# -*- coding: utf-8 -*-
"""Test cases for OPA plugin

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Shriti Priya

This module contains test cases for running opa plugin. Here, the OPA server is scoped under session fixture,
and started once, and further used by all test cases for policy evaluations.
"""

# Standard

# Third-Party
import pytest

# First-Party
from mcpgateway.common.models import Message, ResourceContent, Role, TextContent, PromptResult
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    PromptPosthookPayload,
    PromptPrehookPayload,
    ResourcePostFetchPayload,
    ResourcePreFetchPayload,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)

from mcpgateway.services.logging_service import LoggingService
from opapluginfilter.plugin import OPAPluginFilter

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


@pytest.mark.asyncio
# Test for when opaplugin is not applied to tools
async def test_pre_tool_invoke_opapluginfilter():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_tool_pre_invoke",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_pre_invoke"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IBM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/ibm"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to tools
async def test_post_tool_invoke_opapluginfilter():
    """Test that validates opa plugin applied on post tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_tool_post_invoke",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_post_invoke"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ToolPostInvokePayload(name="fast-time-git-status", result={"text": "IBM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_post_invoke(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    payload = ToolPostInvokePayload(name="fast-time-git-status", result={"text": "IBM@example.com"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_post_invoke(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to prompts
async def test_pre_prompt_fetch_opapluginfilter():
    """Test that validates opa plugin applied on pre prompt fetch is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "prompts": [
            {
                "prompt_name": "test_prompt",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_prompt_pre_fetch",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["prompt_pre_fetch"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = PromptPrehookPayload(prompt_id="test_prompt", args={"text": "You are curseword"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.prompt_pre_fetch(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    payload = PromptPrehookPayload(prompt_id="test_prompt", args={"text": "You are curseword1"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.prompt_pre_fetch(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to prompts
async def test_post_prompt_fetch_opapluginfilter():
    """Test that validates opa plugin applied on post prompt fetch is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "prompts": [
            {
                "prompt_name": "test_prompt",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_prompt_post_fetch",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["prompt_post_fetch"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    message = Message(content=TextContent(type="text", text="abc"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.prompt_post_fetch(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    message = Message(content=TextContent(type="text", text="abc@example.com"), role=Role.USER)
    prompt_result = PromptResult(messages=[message])
    payload = PromptPosthookPayload(prompt_id="test_prompt", result=prompt_result)
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.prompt_post_fetch(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to resources
async def test_pre_resource_fetch_opapluginfilter():
    """Test that validates opa plugin applied on resource pre fetch is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "resources": [
            {
                "resource_uri": "https://example.com",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_resource_pre_fetch",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["resource_pre_fetch"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ResourcePreFetchPayload(uri="https://example.com/docs", metadata={})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.resource_pre_fetch(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    payload = ResourcePreFetchPayload(uri="https://example.com/root", metadata={})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.resource_pre_fetch(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to resources
async def test_post_resource_fetch_opapluginfilter():
    """Test that validates opa plugin applied on resource post fetch is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "resources": [
            {
                "resource_uri": "https://example.com",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_resource_post_fetch",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["prompt_post_fetch"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    content = ResourceContent(
        type="resource",
        uri="test://abc",
        text="abc",
        id="1"
    )
    payload = ResourcePostFetchPayload(uri="https://example.com/docs", content=content)
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.resource_post_fetch(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    content = ResourceContent(
        type="resource",
        uri="test://large",
        text="test://abc@example.com",
        id="1"
    )
    payload = ResourcePostFetchPayload(uri="https://example.com", content=content)
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.resource_post_fetch(payload, context)
    assert not result.continue_processing


@pytest.mark.asyncio
# Test for when opaplugin is not applied to resources
async def test_opapluginfilter_backward_compatibility():
    """Test that validates opa plugin applied on resource post fetch is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow",
                    ],
                    "policy_modality": ["text"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_pre_invoke"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IBM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing

    # Malign payload (denied by OPA (rego) policy)
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/ibm"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_pre_invoke(payload, context)
    assert not result.continue_processing
