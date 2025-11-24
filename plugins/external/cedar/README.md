# Cedar RBAC Plugin for MCP Gateway

> Author: Shriti Priya
> Version: 0.1.0

A plugin that evaluates Cedar policies and user‑friendly custom-DSL policies on incoming requests, and then allows or denies those requests using RBAC-based decisions which are enforced in cedar language and using library `cedarpy`.

## Cedar Language

Cedar is an open-source language and specification for defining and evaluating permission policies. It allows you to specify who is authorized to perform which actions within your application.
For more details: https://www.cedarpolicy.com/en

## RBAC

Role-based access control (RBAC) is an authorization model where permissions are attached to roles (like admin, manager, viewer), and users are assigned to those roles instead of getting permissions directly. This makes access control easier to manage and reason about in larger systems.

## CedarPolicyPlugin

This plugin supports two ways of defining policies in the configuration file, controlled by the `policy_lang` parameter.

### Cedar Mode
When `policy_lang` is set to cedar, policies are written in the Cedar language under the policy key, using the following structure:

```yaml
      - id: allow-employee-basic-access
        effect: Permit
        principal: Role::"employee"
        action:
        - Action::"get_leave_balance" #tool name
        - Action::"request_certificate"
        resource:
        - Server::"askHR" # mcp-server name
        - Agent::"employee_agent" # agent name
```
1. **id** is a unique string identifier for the policy.
2. **effect** can be either Permit or Forbid and determines whether matching requests are allowed or denied.
3. **principal** specifies who the policy applies to; here it targets the employee role.
4. **action** lists one or more operations (such as tools or API actions) that the principal is attempting to perform.
5. **resource** lists the servers, agents, or other resources that the actions can target.

### Custom DSL mode

When `policy_lang` is set to `custom_dsl`, policies are written in a compact, human-readable mini-language as a YAML multiline string. This allows non-experts to define role, resource, and action in a single, easy-to-scan block.
following syntax:


## Syntax

Policies use the following basic pattern:

```
[role:<role_name>:<resource>/<resource_name>]
<action_1>
<action_2>
```

For example:

```yaml
    [role:hr:server/hr_tool]
    update_payroll
```

In this example, role is hr, resource is server, and action is hr_tool. The line update_payroll represents the specific operation being authorized for that role–resource–action tuple.


## Installation

1. In the folder `plugins/external/cedar`,  copy `.env.example` to `.env` file.
2.  Add the plugin configuration to `plugins/external/cedar/resources/plugins/config.yaml`:

```yaml
plugins:
  - name: "CedarPolicyPlugin"
    kind: "cedarpolicyplugin.plugin.CedarPolicyPlugin"
    description: "A plugin that does policy decision and enforcement using cedar"
    version: "0.1.0"
    author: "Shriti Priya"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke"]
    tags: ["plugin"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 150
    conditions:
      # Apply to specific tools/servers
      - server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      policy_lang: cedar
      policy_output_keywords: 
        view_full: "view_full_output"
        view_redacted: "view_redacted_output"
      policy_redaction_spec:
        pattern: '"\$\d{1,}(,\d{1,})*"' # provide regex, if none, then replace all
      policy:
        - id: allow-employee-basic-access
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"get_leave_balance" #tool name
            - Action::"request_certificate"
          resource:
            - Server::"askHR" # mcp-server name
            - Agent::"employee_agent" # agent name

        - id: allow-manager-full-access
          effect: Permit
          principal: Role::"manager"
          action:
            - Action::"get_leave_balance" 
            - Action::"approve_leave"
            - Action::"promote_employee"
            - Action::"view_performance"
            - Action::"view_full_output"
          resource:
            - Agent::"manager_agent"
            - Server::"payroll_tool"

        - id: allow-hr-hr_tool
          effect: Permit
          principal: Role::"hr"
          action:
            - Action::"update_payroll"
            - Action::"view_performance"
            - Action::"view_full_output"
          resource: Server::"hr_tool"

        - id: redact-non-manager-views
          effect: Permit
          principal: Role::"employee"
          action: Action::"view_redacted_output"
          resource:
            - Server::"payroll_tool"
            - Agent::"manager_agent"
            - Server::"askHR"

        - id: allow-admin-resources # policy for resources
          effect: Permit
          principal: Role::"admin"
          action:
            - Action::"view_full_output"
          resource: Resource::""https://example.com/data"" #Resource::<resource_uri>

        - id: allow-employee-redacted-resources # policy for resources
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"view_redacted_output"
          resource: Resource::""https://example.com/data"" #Resource::<resource_uri>          

        - id: allow-admin-prompts # policy for resources
          effect: Permit
          principal: Role::"admin"
          action:
            - Action::"view_full_output"
          resource: Prompts::"judge_prompts" #Prompt::<prompt_name>

        - id: allow-employee-redacted-prompts # policy for resources
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"view_redacted_output"
          resource: Prompts::"judge_prompts" #Prompt::<prompt_name>

```


