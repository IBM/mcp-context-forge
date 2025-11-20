"""Tests for plugin."""

# Third-Party
import pytest

# First-Party
from cedarpolicyplugin.plugin import CedarPolicyPlugin
from mcpgateway.plugins.framework.models import (
    PluginConfig,
    PluginContext,
    GlobalContext,
    PluginResult
)

from mcpgateway.plugins.framework.hooks.resources import ResourcePreFetchPayload, ResourcePostFetchPayload
from mcpgateway.plugins.framework.hooks.prompts import PromptPrehookPayload, PromptPosthookPayload
from mcpgateway.plugins.framework.hooks.tools import ToolPostInvokePayload, ToolPreInvokePayload

from mcpgateway.common.models import Message, ResourceContent, Role, TextContent, PromptResult

# @pytest.mark.asyncio
# async def test_cedarpolicyplugin_native_cedar():
#     """Test plugin prompt prefetch hook."""
    
#     policy_config = [
#         {
#             'id': 'allow-users-tools', 
#             'effect': 'Permit', 
#             'principal': 'Role::"users"', 
#             'action': ['Action::"get_users"', 'Action::"submit_request"'], 
#             'resource': [
#                 {
#                     "type":"server",
#                     "name":"hr_services"
#                     }
#                 ]
#         }
#         # {'id': 'allow-admin-tools','effect': 'Permit','principal': 'Role::"admin"','action':['Action::"get_users"','Action::"submit_request"'],'resource': 'Resource::"tools"'}
#         ]
    
#     config = PluginConfig(
#         name="test",
#         kind="cedarpolicyplugin.CedarPolicyPlugin",
#         hooks=["tool_pre_invoke"],
#         config={"policy_lang": "cedar","policy" : policy_config },
#     )
#     plugin = CedarPolicyPlugin(config)

#     # Test your plugin logic
#     users = ["bob","alice"]
#     actions = ["submit_request","get_users"]
#     for user, action in zip(users,actions):
#         payload = ToolPreInvokePayload(name=action, args={})
#         context = PluginContext(global_context=GlobalContext(request_id="1", server_id="hr_services",user=user))
#         result = await plugin.tool_pre_invoke(payload, context)
#         assert result.continue_processing


# @pytest.mark.asyncio
# async def test_cedarpolicyplugin_custom_dsl():
#     """Test plugin prompt prefetch hook."""
    
#     policy_config = '[role:admin:agents]\ncustomer_service\napproval\n\n[role:admin:tools]\nget_users\nsubmit_request\n\n[role:users:agents]\ncustomer_service\n\n[role:users:tools]\nget_users\nsubmit_request'
    
#     config = PluginConfig(
#         name="test",
#         kind="cedarpolicyplugin.CedarPolicyPlugin",
#         hooks=["tool_pre_invoke"],
#         config={"policy_lang": "custom_dsl","policy" : policy_config },
#     )
#     plugin = CedarPolicyPlugin(config)

#     # Test your plugin logic
#     users = ["bob","alice"]
#     actions = ["submit_request","get_users"]
#     for user, action in zip(users,actions):
#         payload = ToolPreInvokePayload(name=action, args={})
#         context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=user))
#         result = await plugin.tool_pre_invoke(payload, context)
#         assert result.continue_processing


"""This test case is responsible for verifying cedarplugin functionality for all hooks"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_post_tool_invoke_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'allow-employee-basic-access', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"get_leave_balance"', 'Action::"request_certificate"'], 
            'resource': ['Server::"askHR"','Agent::"employee_agent"']
        },
        {
            'id': 'allow-manager-full-access', 
            'effect': 'Permit', 
            'principal': 'Role::"manager"', 
            'action':  ['Action::"get_leave_balance"','Action::"approve_leave"','Action::"promote_employee"','Action::"view_performance"','Action::"view_full_output"'],
            'resource':  ['Agent::"manager_agent"','Server::"payroll_tool"']
        },
        {
            'id': 'allow-hr-hr_tool', 
            'effect': 'Permit', 
            'principal': 'Role::"hr"', 
            'action': ['Action::"update_payroll"','Action::"view_performance"','Action::"view_full_output"'],
            'resource': ['Server::"hr_tool"']
        },
        {
            'id': 'redact-non-manager-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': ['Server::"payroll_tool"','Agent::"manager_agent"','Server::"askHR"']

        },
        ]
    
    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "\$\d{1,}(,\d{1,})*" }
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "action": "get_leave_balance", "resource": "askHR"},   
        {"user": "bob", "action": "view_performance", "resource": "payroll_tool"},  
        {"user": "carol", "action": "update_payroll", "resource": "hr_tool"},    
        {"user": "alice", "action": "update_payroll", "resource": "hr_tool"},    
        ]
    
    redact_count = 0
    allow_count = 0
    deny_count = 0
    for req in requests:
        payload = ToolPostInvokePayload(name=req["action"], result={"text": "Alice has a salary of $250,000"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"],user=req["user"]))
        result = await plugin.tool_post_invoke(payload, context)
        if result.modified_payload and "[REDACTED]" in result.modified_payload.result["text"]:
            redact_count+=1
        if result.continue_processing:
            allow_count+=1
        if not result.continue_processing:
            deny_count +=1
    
    assert redact_count == 1
    assert allow_count == 3
    assert deny_count == 1
    
# """This test case is responsible for verifying cedarplugin functionality for tool pre invoke"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_pre_tool_invoke_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'allow-employee-basic-access', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"get_leave_balance"', 'Action::"request_certificate"'], 
            'resource': ['Server::"askHR"','Agent::"employee_agent"']
        },
        {
            'id': 'allow-manager-full-access', 
            'effect': 'Permit', 
            'principal': 'Role::"manager"', 
            'action':  ['Action::"get_leave_balance"','Action::"approve_leave"','Action::"promote_employee"','Action::"view_performance"','Action::"view_full_output"'],
            'resource':  ['Agent::"manager_agent"','Server::"payroll_tool"']
        },
        {
            'id': 'allow-hr-hr_tool', 
            'effect': 'Permit', 
            'principal': 'Role::"hr"', 
            'action': ['Action::"update_payroll"','Action::"view_performance"','Action::"view_full_output"'],
            'resource': ['Server::"hr_tool"']
        },
        {
            'id': 'redact-non-manager-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': ['Server::"payroll_tool"','Agent::"manager_agent"','Server::"askHR"']

        },
        ]
    
    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "\$\d{1,}(,\d{1,})*" }
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "action": "get_leave_balance", "resource": "askHR"},   
        {"user": "bob", "action": "view_performance", "resource": "payroll_tool"},  
        {"user": "carol", "action": "update_payroll", "resource": "hr_tool"},    
        {"user": "alice", "action": "update_payroll", "resource": "hr_tool"},    
        ]
    
    allow_count = 0
    deny_count = 0
    for req in requests:
        payload = ToolPreInvokePayload(name=req["action"], args={"arg1": "sample arg"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"],user=req["user"]))
        result = await plugin.tool_pre_invoke(payload, context)
        if result.continue_processing:
            allow_count+=1
        if not result.continue_processing:
            deny_count +=1
    
    assert allow_count == 3
    assert deny_count == 1


"""This test case is responsible for verifying cedarplugin functionality for tool pre invoke"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_pre_invoke_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'redact-non-admin-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': 'Prompt::"judge_prompts"'

        },
        {
            'id': 'allow-admin-prompts', # policy for resources
            'effect': 'Permit',
            'principal': 'Role::"admin"',
            'action':['Action::"view_full_output"'],
            'resource': 'Prompt::"judge_prompts"' #Prompt::<prompt_name>
        }
        ]

    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "all" }
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  #allow
        {"user": "robert", "resource": "judge_prompts"},  #allow
        {"user": "carol", "resource": "judge_prompts"}, # deny
        ]
    
    allow_count = 0
    deny_count = 0
    
    for req in requests:

        # Prompt pre hook input
        payload = PromptPrehookPayload(prompt_id=req["resource"], args={"text": "You are curseword"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=req["user"]))
        result = await plugin.prompt_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count+=1
        if not result.continue_processing:
            deny_count +=1

    assert allow_count == 2
    assert deny_count == 1



"""This test case is responsible for verifying cedarplugin functionality for tool pre invoke"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_post_invoke_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'redact-non-admin-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': 'Prompt::"judge_prompts"'

        },
        {
            'id': 'allow-admin-prompts', # policy for resources
            'effect': 'Permit',
            'principal': 'Role::"admin"',
            'action':['Action::"view_full_output"'],
            'resource': 'Prompt::"judge_prompts"' #Prompt::<prompt_name>
        }
        ]

    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "all" }
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  #allow
        {"user": "robert", "resource": "judge_prompts"},  #allow
        {"user": "carol", "resource": "judge_prompts"}, # deny
        ]

    allow_count = 0
    deny_count = 0
    redact_count = 0
    
    for req in requests:
        
        # Prompt post hook output
        message = Message(content=TextContent(type="text", text="abc"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        payload = PromptPosthookPayload(prompt_id=req["resource"], result=prompt_result)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=req["user"]))
        result = await plugin.prompt_post_fetch(payload, context)
        if result.continue_processing:
            allow_count +=1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.result.messages[0].content.text:
                redact_count+=1
        if not result.continue_processing:
            deny_count +=1
       
    
    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1

"""This test case is responsible for verifying cedarplugin functionality for tool pre invoke"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_pre_fetch_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'redact-non-admin-resource-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': 'Resource::"https://example.com/data"' 

        },
        {
            'id': 'allow-admin-resources', # policy for resources
            'effect': 'Permit',
            'principal': 'Role::"admin"',
            'action':['Action::"view_full_output"'],
            'resource': 'Resource::"https://example.com/data"' 
        }
        ]

    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  #allow
        {"user": "robert", "resource": "https://example.com/data"},  #allow
        {"user": "carol", "resource": "https://example.com/data"}, # deny
        ]

    allow_count = 0
    deny_count = 0
    redact_count = 0
    
    for req in requests:
        
        # Prompt post hook output
        payload = ResourcePreFetchPayload(uri="https://example.com/data", metadata={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=req["user"]))
        result = await plugin.resource_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count +=1
        if not result.continue_processing:
            deny_count +=1
       
    
    assert allow_count == 2
    assert deny_count == 1

"""This test case is responsible for verifying cedarplugin functionality for tool pre invoke"""
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_post_fetch_rbac():
    """Test plugin prompt prefetch hook."""   
    policy_config = [
        {
            'id': 'redact-non-admin-resource-views', 
            'effect': 'Permit', 
            'principal': 'Role::"employee"', 
            'action': ['Action::"view_redacted_output"'], 
            'resource': 'Resource::"https://example.com/data"' 

        },
        {
            'id': 'allow-admin-resources', # policy for resources
            'effect': 'Permit',
            'principal': 'Role::"admin"',
            'action':['Action::"view_full_output"'],
            'resource': 'Resource::"https://example.com/data"' 
        }
        ]

    policy_output_keywords = {"view_full": "view_full_output","view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern":  "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={
            "policy_lang": "cedar",
            "policy" : policy_config, 
            "policy_output_keywords": policy_output_keywords, 
            "policy_redaction_spec": policy_redaction_spec
            },
    )
    plugin = CedarPolicyPlugin(config)
    info = {
            "alice": "employee",
            "bob": "manager",
            "carol": "hr",
            "robert": "admin"
        }
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  #allow
        {"user": "robert", "resource": "https://example.com/data"},  #allow
        {"user": "carol", "resource": "https://example.com/data"}, # deny
        ]

    allow_count = 0
    deny_count = 0
    redact_count = 0
    
    for req in requests:
        
        # Prompt post hook output
        content = ResourceContent(
            type="resource",
            uri="test://large",
            text="test://abc@example.com",
            id="1"
            )
        payload = ResourcePostFetchPayload(uri="https://example.com/data", content=content)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2",user=req["user"]))
        result = await plugin.resource_post_fetch(payload, context)
        if result.continue_processing:
            allow_count +=1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.content.text:
                redact_count+=1
        if not result.continue_processing:
            deny_count +=1
       
    
    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1
