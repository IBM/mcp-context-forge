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

`plugins/external/cedar/resources/config.yaml`

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
4. **action** lists one or more tools that the principal is attempting to invoke. It could also be actions controlling the visibility of output, either to see full output or redacted output based on user role.
5. **resource** lists the servers, agents, prompts and resources that the actions can target.

### Custom DSL mode

`plugins/external/cedar/examples/config-dsl.yaml`

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


## Configuration

1. **policy_lang**: Specifies the policy language used, `cedar` or `custom_dsl`.
2. **policy_output_keywords**: Defines keywords for output views such as `view_full_output` and `view_redacted_output` which can be used in policies or applications to control the output visibility.
3. **policy_redaction_spec**: Contains a regex pattern for redaction; in this case, the pattern matches currency-like strings (e.g., "$123,456") for potential redaction in the policy output, protecting sensitive information.
4. **policy**: Defines the RBAC policy

## Installation

1. In the folder `plugins/external/cedar`,  copy `.env.example` to `.env` file.
2. If you are using `policy_lang` to be `cedar`, add the plugin configuration to `plugins/external/cedar/resources/plugins/config.yaml`:

```yaml
plugins:
  - name: "CedarPolicyPlugin"
    kind: "cedarpolicyplugin.plugin.CedarPolicyPlugin"
    description: "A plugin that does policy decision and enforcement using cedar"
    version: "0.1.0"
    author: "Shriti Priya"
    hooks: ["prompt_pre_fetch", "prompt_post_fetch", "tool_pre_invoke", "tool_post_invoke", "resource_pre_fetch", "resource_post_fetch"]
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
        ### Tool invocation policies ###
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

        ### Resource invocation policies ###
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

        ### Prompt invocation policies ###
        - id: allow-admin-prompts # policy for resources
          effect: Permit
          principal: Role::"admin"
          action:
            - Action::"view_full_output"
          resource: Prompt::"judge_prompts" #Prompt::<prompt_name>


        - id: allow-employee-redacted-prompts # policy for resources
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"view_redacted_output"
          resource: Prompt::"judge_prompts" #Prompt::<prompt_name>

```

#### Tool Invocation Policies

For the RBAC policy related to `tool_pre_invoke` and `tool_post_invoke`
Example:
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

Here, user with role `employee` (**Role**) is only allowed to invoke tool `get_leave_balance` (**Action**) belonging to the MCP server or (**Server**).

In another policy defined for tools

```yaml

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
```


The actions like `view_full_output` and `view_redacted_output` has been used. This basically controls the
level of output visibile to the user. In the above policy, user with role `hr` is only allowed to view the output of `update_payroll`. Similary for the second policy, user with role `employee` is only allowed to view redacted output of the tool.


#### Prompt Invocation Policies


```yaml

        ### Prompt invocation policies ###
        - id: allow-admin-prompts # policy for resources
          effect: Permit
          principal: Role::"admin"
          action:
            - Action::"view_full_output"
          resource: Prompt::"judge_prompts" #Prompt::<prompt_name>


        - id: allow-employee-redacted-prompts # policy for resources
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"view_redacted_output"
          resource: Prompt::"judge_prompts" #Prompt::<prompt_name>
```

Here, in the above polcicy, given a prompt template `judge_prompts`, user of role `admin` is only allowed to view full prompt. However, if a user is of role `employee`, then it could only see redacted version of the prompt.


#### Resource Invocation Policies

**NOTE:** Please don't be confused with the word resource in cedar to the word resource in MCP ContextForge.

```yaml

        - id: allow-admin-resources # policy for resources
          effect: Permit
          principal: Role::"admin"
          action:
            - Action::"view_full_output"
          resource: Resource::"https://example.com/data" #Resource::<resource_uri>

        - id: allow-employee-redacted-resources # policy for resources
          effect: Permit
          principal: Role::"employee"
          action:
            - Action::"view_redacted_output"
          resource: Resource::"https://example.com/data" #Resource::<resource_uri>
```

Here, `Resource` word used in policy, is if resource hooks are invoked. So, in the above policy,
user with role `admin` is only allowed to view full output of uri `https://example.com/data`. Where, the user is of `employee` role, it can only see the redacted versionaaaaa of the resource output.


#### policy_output_keywords

```
        view_full: "view_full_output"
        view_redacted: "view_redacted_output"
```

has been provided, so everytime a user defines a policy, if it wants to control the output visibility of
any of the tool, prompt, resource or agent in MCP gateway, it can provide the keyword, it's supposed to use in the policy in `policy_output_keywords`. CedarPolicyPlugin will internally use this mapping to redact or fully display the tool, prompt or resource response in post hooks.




3. Now, the policy and plugin configurations are defined in `resources/config.yaml` file, next step is build this as an external MCP server.

* `make venv`: This will create a virtual environment to develop or build your plugin.
* `make install && make install-dev`: To install all the required libraries in the environment.
* `make build`:  This will build a docker image named `mcpgateway/cedarpolicyplugin`
* `make start`: This will start the cedarpolicyplugin container.

This confirms that your container is running fine:
```
WARNING:mcpgateway.observability:OpenTelemetry not installed. Proceeding with graceful fallbacks.
INFO:     Started server process [9]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:55196 - "GET /health HTTP/1.1" 200 OK

```

4. Now, you can add this external plugin configuration, in `plugins/config.yaml`:
3. The next step is to enable the opa plugin which you can do by adding `PLUGINS_ENABLED=true` and the following blob in `plugins/config.yaml` file. This will indicate that OPA Plugin is running as an external MCP server.

  ```yaml
  - name: "CedarPolicyPlugin"
    kind: "external"
    priority: 10 # adjust the priority
    mcp:
      proto: STREAMABLEHTTP
      url: http://127.0.0.1:8000/mcp
  ```

## Testing

There are set of test cases in the `cedar/tests` folder. The file named `test_cedarpolicyplugin.py` file which contains detailed test cases for RBAC policies enforced on tools, prompts and resources.
run `make test` to run all the test cases.



## Difference from OPAPlugin

The OPA plugin runs an OPA server to enforce policies, whereas the Cedar plugin uses the `cedarpy` library and performs policy enforcement locally without requiring an external service.
OPA plugin requires to know `rego` to define policies by user while the `Cedar` plugin can be defined either in `cedar` or user friendly `custom_dsl` language.
Right now, the cedar plugin enforces RBAC policies and it could be extended to enforce ABAC policies using the same plugin.
