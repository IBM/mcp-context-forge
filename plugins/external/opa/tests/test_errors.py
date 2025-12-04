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
from mcpgateway.plugins.framework import (
    GlobalContext,
    PluginConfig,
    PluginContext,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
    PluginError
)

from mcpgateway.services.logging_service import LoggingService
from opapluginfilter.plugin import OPAPluginFilter, OPAPluginErrorCodes

logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


@pytest.mark.asyncio
# Check for OPA Server returning none response
async def test_error_opa_server_error():
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

    incorrect_opa_url = "http://127.0.0.1:3000/v1/data/"
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_pre_invoke"], config={"opa_base_url": incorrect_opa_url}, applied_to=config)
    plugin = OPAPluginFilter(config)
    payload = ToolPreInvokePayload(name="fast-time-git-status", args={"repo_path": "/path/IBM"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    try:
        await plugin.tool_pre_invoke(payload, context)
    except PluginError as e:
        assert e.error.message == OPAPluginErrorCodes.OPA_SERVER_ERROR.value


@pytest.mark.asyncio
# Test for when opaplugin is configured with invalid endpoint
async def test_error_opa_server_invalid_endpoint():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_x_invoke",
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
    try:
        await plugin.tool_pre_invoke(payload, context)
    except PluginError as e:
        assert e.error.message == OPAPluginErrorCodes.INVALID_POLICY_ENDPOINT.value


@pytest.mark.asyncio
# Test for when opaplugin opa server sends none response
async def test_error_opa_server_none_response():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example1",
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
    try:
        await plugin.tool_pre_invoke(payload, context)
    except PluginError as e:
        assert e.error.message == OPAPluginErrorCodes.OPA_SERVER_NONE_RESPONSE.value


@pytest.mark.asyncio
# Test for when opaplugin is configured with no policy endpoint
async def test_error_opa_server_unconfigured_endpoint():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
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
    try:
        await plugin.tool_pre_invoke(payload, context)
    except PluginError as e:
        assert e.error.message == OPAPluginErrorCodes.OPA_SERVER_UNCONFIGURED_ENDPOINT.value


@pytest.mark.asyncio
# Test for when opaplugin if not supported policy modality location has been used in configuration
async def test_error_opa_server_unsupported_modality():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_tool_post_invoke",
                    ],
                    "policy_modality": ["location"],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_pre_invoke"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ToolPostInvokePayload(name="fast-time-git-status", result={"text": "IBM@example.com"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    try:
        await plugin.tool_post_invoke(payload, context)
    except PluginError as e:
        assert e.error.message == OPAPluginErrorCodes.UNSUPPORTED_POLICY_MODALITY.value


@pytest.mark.asyncio
# Test for when opaplugin has not been configured with a policy modality. The expected behavior is to pick up default policy modality as text
async def test_error_opa_server_unspecified_policy_modality():
    """Test that validates opa plugin applied on pre tool invocation is working successfully. Evaluates for both malign and benign cases"""
    config = {
        "tools": [
            {
                "tool_name": "fast-time-git-status",
                "extensions": {
                    "policy": "example",
                    "policy_endpoints": [
                        "allow_tool_post_invoke",
                    ],
                },
            }
        ]
    }
    config = PluginConfig(name="test", kind="opapluginfilter.OPAPluginFilter", hooks=["tool_pre_invoke"], config={"opa_base_url": "http://127.0.0.1:8181/v1/data/"}, applied_to=config)
    plugin = OPAPluginFilter(config)

    # Benign payload (allowed by OPA (rego) policy)
    payload = ToolPostInvokePayload(name="fast-time-git-status", result={"text": "IBM@example.com"})
    context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
    result = await plugin.tool_post_invoke(payload, context)
    assert not result.continue_processing
