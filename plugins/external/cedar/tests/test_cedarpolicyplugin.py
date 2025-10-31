"""Tests for plugin."""

# Third-Party
import pytest

# First-Party
from cedarpolicyplugin.plugin import CedarPolicyPlugin
from mcpgateway.plugins.framework import (
    PluginConfig,
    PluginContext,
    GlobalContext
)
from  mcpgateway.plugins.mcp.entities.models import (
    ToolPreInvokePayload,
    ToolPreInvokeResult,
)

@pytest.mark.asyncio
async def test_cedarpolicyplugin_native_cedar():
    """Test plugin prompt prefetch hook."""
    
    policy_config = [
        {'id': 'allow-users-tools', 'effect': 'Permit', 'principal': 'Role::"users"', 'action': ['Action::"get_users"', 'Action::"submit_request"'], 'resource': 'Resource::"tools"'},
        {'id': 'allow-admin-tools','effect': 'Permit','principal': 'Role::"admin"','action':['Action::"get_users"','Action::"submit_request"'],'resource': 'Resource::"tools"'}
        ]
    
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar","policy" : policy_config },
    )
    plugin = CedarPolicyPlugin(config)

    # Test your plugin logic
    users = ["bob","alice"]
    actions = ["submit_request","get_users"]
    for user, action in zip(users,actions):
        payload = ToolPreInvokePayload(name=action, args={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=user))
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.continue_processing


@pytest.mark.asyncio
async def test_cedarpolicyplugin_custom_dsl():
    """Test plugin prompt prefetch hook."""
    
    policy_config = '[role:admin:agents]\ncustomer_service\napproval\n\n[role:admin:tools]\nget_users\nsubmit_request\n\n[role:users:agents]\ncustomer_service\n\n[role:users:tools]\nget_users\nsubmit_request'
    
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl","policy" : policy_config },
    )
    plugin = CedarPolicyPlugin(config)

    # Test your plugin logic
    users = ["bob","alice"]
    actions = ["submit_request","get_users"]
    for user, action in zip(users,actions):
        payload = ToolPreInvokePayload(name=action, args={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=user))
        result = await plugin.tool_pre_invoke(payload, context)
        assert result.continue_processing