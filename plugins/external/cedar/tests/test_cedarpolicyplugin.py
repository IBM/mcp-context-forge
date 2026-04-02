# -*- coding: utf-8 -*-
"""Tests for plugin."""

# Third-Party
from cedarpolicyplugin.plugin import CedarPolicyPlugin
import pytest

# First-Party
from mcpgateway.common.models import Message, PromptResult, ResourceContent, Role, TextContent
from mcpgateway.plugins.framework.hooks.prompts import PromptPosthookPayload, PromptPrehookPayload
from mcpgateway.plugins.framework.hooks.resources import ResourcePostFetchPayload, ResourcePreFetchPayload
from mcpgateway.plugins.framework.hooks.tools import ToolPostInvokePayload, ToolPreInvokePayload
from mcpgateway.plugins.framework.models import (
    GlobalContext,
    PluginConfig,
    PluginContext,
)


# This test case is responsible for verifying cedarplugin functionality for post tool hooks in cdear native mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_post_tool_invoke_rbac():
    """Test plugin for post tool invocation"""
    policy_config = [
        {
            "id": "allow-employee-basic-access",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"get_leave_balance"', 'Action::"request_certificate"'],
            "resource": ['Server::"askHR"', 'Agent::"employee_agent"'],
        },
        {
            "id": "allow-manager-full-access",
            "effect": "Permit",
            "principal": 'Role::"manager"',
            "action": ['Action::"get_leave_balance"', 'Action::"approve_leave"', 'Action::"promote_employee"', 'Action::"view_performance"', 'Action::"view_full_output"'],
            "resource": ['Agent::"manager_agent"', 'Server::"payroll_tool"'],
        },
        {
            "id": "allow-hr-hr_tool",
            "effect": "Permit",
            "principal": 'Role::"hr"',
            "action": ['Action::"update_payroll"', 'Action::"view_performance"', 'Action::"view_full_output"'],
            "resource": ['Server::"hr_tool"'],
        },
        {
            "id": "redact-non-manager-views",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"view_redacted_output"'],
            "resource": ['Server::"payroll_tool"', 'Agent::"manager_agent"', 'Server::"askHR"'],
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": r"\$\d{1,}(,\d{1,})*", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
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
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"], user=req["user"]))
        result = await plugin.tool_post_invoke(payload, context)
        if result.modified_payload and "[REDACTED]" in result.modified_payload.result["text"]:
            redact_count += 1
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert redact_count == 1
    assert allow_count == 3
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for post tool invocation with policy in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_post_tool_invoke_custom_dsl_rbac():
    """Test plugin for post tool invocation"""
    policy_config = "[role:employee:server/askHR]\nget_leave_balance\nrequest_certificate\n\n\
    [role:employee:agent/employee_agent]\nget_leave_balance\nrequest_certificate\n\n[role:manager:agent/manager_agent]\nget_leave_balance\napprove_leave\npromote_employee\nview_performance\nview_full_output\n\n[role:manager:server/payroll_tool]\
    \nget_leave_balance\napprove_leave\npromote_employee\nview_performance\nview_full_output\n\n[role:hr:server/hr_tool]\nupdate_payroll\nview_performance\nview_full_output\n\n[role:employee:server/payroll_tool]\nview_redacted_output\n\n[role:employee:agent/manager_agent]\nview_redacted_output\n\n\
    [role:employee:server/askHR]\nview_redacted_output"

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": r"\$\d{1,}(,\d{1,})*", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
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
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"], user=req["user"]))
        result = await plugin.tool_post_invoke(payload, context)
        if result.modified_payload and "[REDACTED]" in result.modified_payload.result["text"]:
            redact_count += 1
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert redact_count == 1
    assert allow_count == 3
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for tool pre invoke in cedar native mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_pre_tool_invoke_cedar_rbac():
    """Test plugin tool pre invoke hook."""
    policy_config = [
        {
            "id": "allow-employee-basic-access",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"get_leave_balance"', 'Action::"request_certificate"'],
            "resource": ['Server::"askHR"', 'Agent::"employee_agent"'],
        },
        {
            "id": "allow-manager-full-access",
            "effect": "Permit",
            "principal": 'Role::"manager"',
            "action": ['Action::"get_leave_balance"', 'Action::"approve_leave"', 'Action::"promote_employee"', 'Action::"view_performance"', 'Action::"view_full_output"'],
            "resource": ['Agent::"manager_agent"', 'Server::"payroll_tool"'],
        },
        {
            "id": "allow-hr-hr_tool",
            "effect": "Permit",
            "principal": 'Role::"hr"',
            "action": ['Action::"update_payroll"', 'Action::"view_performance"', 'Action::"view_full_output"'],
            "resource": ['Server::"hr_tool"'],
        },
        {
            "id": "redact-non-manager-views",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"view_redacted_output"'],
            "resource": ['Server::"payroll_tool"', 'Agent::"manager_agent"', 'Server::"askHR"'],
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": r"\$\d{1,}(,\d{1,})*"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
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
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"], user=req["user"]))
        result = await plugin.tool_pre_invoke(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 3
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for tool pre invoke in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_pre_tool_invoke_custom_dsl_rbac():
    """Test plugin tool pre invoke."""
    policy_config = "[role:employee:server/askHR]\nget_leave_balance\nrequest_certificate\n\n[role:employee:agent/employee_agent]\n\
    get_leave_balance\nrequest_certificate\n\n[role:manager:agent/manager_agent]\nget_leave_balance\napprove_leave\npromote_employee\n\
    view_performance\nview_full_output\n\n[role:manager:server/payroll_tool]\nget_leave_balance\napprove_leave\npromote_employee\nview_performance\n\
    view_full_output\n\n[role:hr:server/hr_tool]\nupdate_payroll\nview_performance\nview_full_output\n\n[role:employee:server/payroll_tool]\n\
    view_redacted_output\n\n[role:employee:agent/manager_agent]\nview_redacted_output\n\n[role:employee:server/askHR]\nview_redacted_output"
    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": r"\$\d{1,}(,\d{1,})*"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
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
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id=req["resource"], user=req["user"]))
        result = await plugin.tool_pre_invoke(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 3
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for prompt pre fetch in cedar mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_pre_fetch_rbac():
    """Test plugin prompt prefetch hook."""
    policy_config = [
        {"id": "redact-non-admin-views", "effect": "Permit", "principal": 'Role::"employee"', "action": ['Action::"view_redacted_output"'], "resource": 'Prompt::"judge_prompts"'},
        {
            "id": "allow-admin-prompts",  # policy for resources
            "effect": "Permit",
            "principal": 'Role::"admin"',
            "action": ['Action::"view_full_output"'],
            "resource": 'Prompt::"judge_prompts"',  # Prompt::<prompt_name>
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "all"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  # allow
        {"user": "robert", "resource": "judge_prompts"},  # allow
        {"user": "carol", "resource": "judge_prompts"},  # deny
    ]

    allow_count = 0
    deny_count = 0

    for req in requests:

        # Prompt pre hook input
        payload = PromptPrehookPayload(prompt_id=req["resource"], args={"text": "You are curseword"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.prompt_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for prompt pre fetch in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_pre_fetch_custom_dsl_rbac():
    """Test plugin prompt prefetch hook."""
    policy_config = "[role:employee:prompt/judge_prompts]\nview_redacted_output\n\n[role:admin:prompt/judge_prompts]\nview_full_output"

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "all"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  # allow
        {"user": "robert", "resource": "judge_prompts"},  # allow
        {"user": "carol", "resource": "judge_prompts"},  # deny
    ]

    allow_count = 0
    deny_count = 0

    for req in requests:

        # Prompt pre hook input
        payload = PromptPrehookPayload(prompt_id=req["resource"], args={"text": "You are curseword"})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.prompt_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for prompt post fetch in cedar native mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_post_fetch_cedar_rbac():
    """Test plugin prompt postfetch hook."""
    policy_config = [
        {"id": "redact-non-admin-views", "effect": "Permit", "principal": 'Role::"employee"', "action": ['Action::"view_redacted_output"'], "resource": 'Prompt::"judge_prompts"'},
        {
            "id": "allow-admin-prompts",  # policy for resources
            "effect": "Permit",
            "principal": 'Role::"admin"',
            "action": ['Action::"view_full_output"'],
            "resource": 'Prompt::"judge_prompts"',  # Prompt::<prompt_name>
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "all", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  # allow
        {"user": "robert", "resource": "judge_prompts"},  # allow
        {"user": "carol", "resource": "judge_prompts"},  # deny
    ]

    allow_count = 0
    deny_count = 0
    redact_count = 0

    for req in requests:

        # Prompt post hook output
        message = Message(content=TextContent(type="text", text="abc"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        payload = PromptPosthookPayload(prompt_id=req["resource"], result=prompt_result)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.prompt_post_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.result.messages[0].content.text:
                redact_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1


# This test case is responsible for verifying cedarplugin functionality for prompt post fetch in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_prompt_post_fetch_custom_dsl_rbac():
    """Test plugin prompt postfetch hook."""
    policy_config = "[role:employee:prompt/judge_prompts]\nview_redacted_output\n\n[role:admin:prompt/judge_prompts]\nview_full_output"

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "all", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "judge_prompts"},  # allow
        {"user": "robert", "resource": "judge_prompts"},  # allow
        {"user": "carol", "resource": "judge_prompts"},  # deny
    ]

    allow_count = 0
    deny_count = 0
    redact_count = 0

    for req in requests:

        # Prompt post hook output
        message = Message(content=TextContent(type="text", text="abc"), role=Role.USER)
        prompt_result = PromptResult(messages=[message])
        payload = PromptPosthookPayload(prompt_id=req["resource"], result=prompt_result)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.prompt_post_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.result.messages[0].content.text:
                redact_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1


# This test case is responsible for verifying cedarplugin functionality for resource pre fetch in cedar native mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_pre_fetch_cedar_rbac():
    """Test plugin resource prefetch hook."""
    policy_config = [
        {
            "id": "redact-non-admin-resource-views",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"view_redacted_output"'],
            "resource": 'Resource::"https://example.com/data"',
        },
        {
            "id": "allow-admin-resources",  # policy for resources
            "effect": "Permit",
            "principal": 'Role::"admin"',
            "action": ['Action::"view_full_output"'],
            "resource": 'Resource::"https://example.com/data"',
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  # allow
        {"user": "robert", "resource": "https://example.com/data"},  # allow
        {"user": "carol", "resource": "https://example.com/data"},  # deny
    ]

    allow_count = 0
    deny_count = 0

    for req in requests:

        # Prompt post hook output
        payload = ResourcePreFetchPayload(uri="https://example.com/data", metadata={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.resource_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for resource pre fetch in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_pre_fetch_custom_dsl_rbac():
    """Test plugin resource prefetch hook."""
    policy_config = "[role:employee:resource/https://example.com/data]\nview_redacted_output\n\n[role:admin:resource/https://example.com/data]\nview_full_output"

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  # allow
        {"user": "robert", "resource": "https://example.com/data"},  # allow
        {"user": "carol", "resource": "https://example.com/data"},  # deny
    ]

    allow_count = 0
    deny_count = 0

    for req in requests:

        # Prompt post hook output
        payload = ResourcePreFetchPayload(uri="https://example.com/data", metadata={})
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.resource_pre_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1


# This test case is responsible for verifying cedarplugin functionality for resource post fetch in cedar native mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_post_fetch_cedar_rbac():
    """Test plugin resource post fetch."""
    policy_config = [
        {
            "id": "redact-non-admin-resource-views",
            "effect": "Permit",
            "principal": 'Role::"employee"',
            "action": ['Action::"view_redacted_output"'],
            "resource": 'Resource::"https://example.com/data"',
        },
        {
            "id": "allow-admin-resources",  # policy for resources
            "effect": "Permit",
            "principal": 'Role::"admin"',
            "action": ['Action::"view_full_output"'],
            "resource": 'Resource::"https://example.com/data"',
        },
    ]

    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "cedar", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  # allow
        {"user": "robert", "resource": "https://example.com/data"},  # allow
        {"user": "carol", "resource": "https://example.com/data"},  # deny
    ]

    allow_count = 0
    deny_count = 0
    redact_count = 0

    for req in requests:

        # Prompt post hook output
        content = ResourceContent(type="resource", uri="test://large", text="test://abc@example.com", id="1")
        payload = ResourcePostFetchPayload(uri="https://example.com/data", content=content)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.resource_post_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.content.text:
                redact_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1


# This test case is responsible for verifying cedarplugin functionality for resource post fetch in custom dsl mode
@pytest.mark.asyncio
async def test_cedarpolicyplugin_resource_post_fetch_custom_dsl_rbac():
    """Test plugin resource postfetch hook."""
    policy_config = "[role:employee:resource/https://example.com/data]\nview_redacted_output\n\n[role:admin:resource/https://example.com/data]\nview_full_output"
    policy_output_keywords = {"view_full": "view_full_output", "view_redacted": "view_redacted_output"}
    policy_redaction_spec = {"pattern": "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}", "redaction_str": "[REDACTED]"}
    config = PluginConfig(
        name="test",
        kind="cedarpolicyplugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        config={"policy_lang": "custom_dsl", "policy": policy_config, "policy_output_keywords": policy_output_keywords, "policy_redaction_spec": policy_redaction_spec},
    )
    plugin = CedarPolicyPlugin(config)
    info = {"alice": "employee", "bob": "manager", "carol": "hr", "robert": "admin"}
    plugin._set_jwt_info(info)
    requests = [
        {"user": "alice", "resource": "https://example.com/data"},  # allow
        {"user": "robert", "resource": "https://example.com/data"},  # allow
        {"user": "carol", "resource": "https://example.com/data"},  # deny
    ]

    allow_count = 0
    deny_count = 0
    redact_count = 0

    for req in requests:

        # Prompt post hook output
        content = ResourceContent(type="resource", uri="test://large", text="test://abc@example.com", id="1")
        payload = ResourcePostFetchPayload(uri="https://example.com/data", content=content)
        context = PluginContext(global_context=GlobalContext(request_id="1", server_id="2", user=req["user"]))
        result = await plugin.resource_post_fetch(payload, context)
        if result.continue_processing:
            allow_count += 1
            if result.modified_payload and "[REDACTED]" in result.modified_payload.content.text:
                redact_count += 1
        if not result.continue_processing:
            deny_count += 1

    assert allow_count == 2
    assert deny_count == 1
    assert redact_count == 1


# ---------------------------------------------------------------------------
# http_auth_check_permission tests
# ---------------------------------------------------------------------------

CEDAR_HTTP_POLICY = [
    {
        "principal": 'Role::"data_scientist"',
        "action": ['Action::"data:read"', 'Action::"tools:read"'],
        "resource": 'Resource::"*"',
    },
    {
        "principal": 'Role::"team_admin"',
        "action": ['Action::"data:read"', 'Action::"security:read"', 'Action::"tools:read"'],
        "resource": 'Resource::"*"',
    },
]


def _make_cedar_http_plugin(policy=None, mode="permissive"):
    """Helper: build a CedarPolicyPlugin configured for HTTP permission checks."""
    config = PluginConfig(
        name="test-cedar-http",
        kind="cedarpolicyplugin.plugin.CedarPolicyPlugin",
        hooks=["http_auth_check_permission"],
        mode=mode,
        config={"policy_lang": "cedar", "policy": policy if policy is not None else CEDAR_HTTP_POLICY},
    )
    return CedarPolicyPlugin(config)


def _make_http_context():
    return PluginContext(global_context=GlobalContext(request_id="test-req"))


from mcpgateway.plugins.framework.hooks.http import HttpAuthCheckPermissionPayload  # noqa: E402


@pytest.mark.asyncio
async def test_cedar_http_auth_allow_matching_role_and_permission():
    """data_scientist requesting data:read should be allowed."""
    plugin = _make_cedar_http_plugin()
    payload = HttpAuthCheckPermissionPayload(
        user_email="alice@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["data_scientist"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is True
    assert result.modified_payload is None


@pytest.mark.asyncio
async def test_cedar_http_auth_deny_role_without_permission():
    """viewer role has no Cedar permit — enforce mode must deny."""
    plugin = _make_cedar_http_plugin(mode="enforce")
    payload = HttpAuthCheckPermissionPayload(
        user_email="bob@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["viewer"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is False
    assert result.modified_payload is not None
    assert result.modified_payload.granted is False
    assert result.modified_payload.reason is not None


@pytest.mark.asyncio
async def test_cedar_http_auth_admin_bypass_skips_cedar():
    """is_admin=True must bypass Cedar entirely and allow."""
    plugin = _make_cedar_http_plugin()
    payload = HttpAuthCheckPermissionPayload(
        user_email="admin@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=True,
        roles=[],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is True
    assert result.modified_payload is None


@pytest.mark.asyncio
async def test_cedar_http_auth_no_policy_passes_through():
    """When _cedar_policy is None (no compiled policy), must pass through without blocking."""
    plugin = _make_cedar_http_plugin()
    plugin._cedar_policy = None  # simulate unconfigured state
    payload = HttpAuthCheckPermissionPayload(
        user_email="carol@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["data_scientist"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_cedar_http_auth_any_role_allows_access():
    """Any permitted role is sufficient: first role denied, second role allowed — should allow."""
    plugin = _make_cedar_http_plugin(mode="enforce")
    # viewer is denied; data_scientist is permitted for data:read
    payload = HttpAuthCheckPermissionPayload(
        user_email="dave@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["viewer", "data_scientist"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is True
    assert result.modified_payload is None


@pytest.mark.asyncio
async def test_cedar_http_auth_first_role_allows_short_circuits():
    """When first role is permitted, remaining roles are not evaluated (any-allow wins)."""
    plugin = _make_cedar_http_plugin(mode="enforce")
    # First role is team_admin (has security:read permit), second is viewer (doesn't)
    payload = HttpAuthCheckPermissionPayload(
        user_email="dave@example.com",
        permission="security:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["team_admin", "viewer"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_cedar_http_auth_permissive_mode_passes_through_on_denial():
    """Permissive mode: even when Cedar denies all roles, the request passes through."""
    plugin = _make_cedar_http_plugin(mode="permissive")
    payload = HttpAuthCheckPermissionPayload(
        user_email="eve@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=["viewer"],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    # Permissive mode must not block, regardless of Cedar decision
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_cedar_http_auth_no_roles_falls_back_to_user_principal():
    """User with no roles falls back to User:: principal; no Cedar permit — enforce denies."""
    plugin = _make_cedar_http_plugin(mode="enforce")
    payload = HttpAuthCheckPermissionPayload(
        user_email="frank@example.com",
        permission="data:read",
        resource_type="tool",
        team_id="team1",
        is_admin=False,
        roles=[],
        auth_method="jwt",
        client_host="127.0.0.1",
        user_agent="test",
    )
    result = await plugin.http_auth_check_permission(payload, _make_http_context())
    assert result.continue_processing is False
    assert result.modified_payload.granted is False


# ---------------------------------------------------------------------------
# tool_pre_invoke role-aware tests
# ---------------------------------------------------------------------------

CEDAR_TOOL_POLICY = [
    {
        "principal": 'Role::"data_scientist"',
        "action": ['Action::"ping"', 'Action::"flaky_tool"'],
        "resource": 'Server::"dummy-server"',
    },
    {
        "principal": 'Role::"team_admin"',
        "action": ['Action::"ping"', 'Action::"reset_counter"'],
        "resource": 'Server::"dummy-server"',
    },
]


def _make_cedar_tool_plugin(mode="enforce"):
    config = PluginConfig(
        name="test-cedar-tool",
        kind="cedarpolicyplugin.plugin.CedarPolicyPlugin",
        hooks=["tool_pre_invoke"],
        mode=mode,
        config={"policy_lang": "cedar", "policy": CEDAR_TOOL_POLICY},
    )
    return CedarPolicyPlugin(config)


def _make_tool_context(user_dict, server_id="dummy-server"):
    return PluginContext(global_context=GlobalContext(request_id="test-req", server_id=server_id, user=user_dict))


@pytest.mark.asyncio
async def test_tool_pre_invoke_role_allowed():
    """data_scientist calling ping should be allowed."""
    plugin = _make_cedar_tool_plugin()
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "alice@example.com", "is_admin": False, "roles": ["data_scientist"]})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True
    assert result.violation is None


@pytest.mark.asyncio
async def test_tool_pre_invoke_role_denied_enforce():
    """viewer role has no Cedar tool permit — enforce mode blocks."""
    plugin = _make_cedar_tool_plugin(mode="enforce")
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "bob@example.com", "is_admin": False, "roles": ["viewer"]})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is False
    assert result.violation is not None


@pytest.mark.asyncio
async def test_tool_pre_invoke_role_denied_permissive():
    """viewer role has no Cedar tool permit — permissive mode passes through."""
    plugin = _make_cedar_tool_plugin(mode="permissive")
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "bob@example.com", "is_admin": False, "roles": ["viewer"]})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_tool_pre_invoke_admin_bypass():
    """Admin users bypass Cedar tool evaluation entirely."""
    plugin = _make_cedar_tool_plugin(mode="enforce")
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "admin@example.com", "is_admin": True, "roles": []})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True
    assert result.violation is None


@pytest.mark.asyncio
async def test_tool_pre_invoke_any_role_allows():
    """viewer + data_scientist: viewer denied, data_scientist allowed — should allow."""
    plugin = _make_cedar_tool_plugin(mode="enforce")
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "carol@example.com", "is_admin": False, "roles": ["viewer", "data_scientist"]})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True


@pytest.mark.asyncio
async def test_tool_pre_invoke_no_roles_denied():
    """No roles falls back to User:: principal; not in policy — enforce blocks."""
    plugin = _make_cedar_tool_plugin(mode="enforce")
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "nobody@example.com", "is_admin": False, "roles": []})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is False


@pytest.mark.asyncio
async def test_tool_pre_invoke_no_policy_passes_through():
    """When _cedar_policy is None, tool_pre_invoke passes through."""
    plugin = _make_cedar_tool_plugin(mode="enforce")
    plugin._cedar_policy = None
    payload = ToolPreInvokePayload(name="ping", args={})
    context = _make_tool_context({"email": "alice@example.com", "is_admin": False, "roles": ["data_scientist"]})
    result = await plugin.tool_pre_invoke(payload, context)
    assert result.continue_processing is True
