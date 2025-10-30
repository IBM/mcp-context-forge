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
async def test_cedarpolicyplugin():
    """Test plugin prompt prefetch hook."""
    
    policy_config = [
        {'id': 'allow-users-tools', 'effect': 'Permit', 'principal': 'Role::"users"', 'action': ['Action::"get_users"', 'Action::"submit_request"'], 'resource': 'Resource::"tools"'}]
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
    flag = 0
    for user, action in zip(users,actions):
        payload = ToolPreInvokePayload(name=action, args={"user" : user})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2"))
        result = await plugin.tool_pre_invoke(payload, context)
        if result.continue_processing:
            flag+=1
        
    assert flag ==1
