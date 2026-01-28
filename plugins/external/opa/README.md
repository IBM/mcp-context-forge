# OPA Plugin for MCP Gateway

> Author: Shriti Priya
> Version: 0.1.0

An OPA (Open Policy Agent) plugin that enforces Rego policies on requests and allows or denies requests based on policy evaluation.

The OPA plugin is composed of two components:
1. **OPA Server**: Runs as a background service evaluating policies
2. **Plugin Hooks**: Intercepts tool, prompt and resource invocations or fetching and communicates with the OPA server for policy decisions

Whenever either of the tool, prompt or resource is accessed, a policy is applied to both pre and post invocations (request and response) Based on the defined policy, the request or response is either allowed or denied further.

### OPA Server
To define a policy file, create a Rego policy file in `opaserver/rego/`. An example `policy.rego` file is provided.

When building the server, the OPA binaries will be downloaded and a container will be built. The `run_server.sh` script starts the OPA server as a background service within the container, loading the specified Rego policy file.

### OPA Plugin
The OPA plugin runs as an external plugin with pre/post tool, prompt and resource invocations or fetches. So everytime a tool invocation is made, and if OPAPluginFilter has been defined in config.yaml file, the tool invocation will pass through this OPA Plugin.

## Configuration

### MCP Server Container

The following enviornment variables can be used to customize the server container deployment.

- `API_SERVER_SCRIPT`: Path to the server script (optional, auto-detected)
- `PLUGINS_CONFIG_PATH`: Path to the plugin config (optional, default: ./resources/plugins/config.yaml)
- `CHUK_MCP_CONFIG_PATH`: Path to the chuck-mcp-runtime config (optional, default: ./resources/runtime/config.yaml)
- `POLICY_PATH`: Path to the repo policy file (optional, default: ./opaserver/rego/policy.rego)

### MCP Runtime

Changes to the MCP runtime configurations can be made in `resources/runtime/config.yaml`.

### OPA Plugin Configuration

The OPA plugin and loader configuration can be customized in `resources/plugins/config.yaml`.

## Installation

1. In the folder `external/opa`, copy .env.template .env
2. Add the plugin configuration to `plugins/external/opa/resources/plugins/config.yaml`:

```yaml
plugins:
  - name: "OPAPluginFilter"
    kind: "opapluginfilter.plugin.OPAPluginFilter"
    description: "An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies"
    version: "0.1.0"
    author: "Shriti Priya"
    hooks: ["tool_pre_invoke"]
    tags: ["plugin"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 10
    applied_to:
      tools:
        - tool_name: "fast-time-git-status"
          context:
            - "global.opa_policy_context.git_context"
          extensions:
            policy: "example"
            policy_endpoint: "allow"
            # policy_input_data_map:
            #  "context.git_context": "git_context"
            #  "payload.args.repo_path": "repo_path"
    conditions:
      # Apply to specific tools/servers
      - server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      # Plugin config dict passed to the plugin constructor
      opa_base_url: "http://127.0.0.1:8181/v1/data/"
```
The `applied_to` key in config.yaml, has been used to selectively apply policies and provide context for a specific tool.
Here, using this, you can provide the `tool_name` of the tool you want to apply policy on, you can also provide
context to the tool with the prefix `global` if it needs to check the context in global context provided.
The key `opa_policy_context` is used to get context for policies and you can have multiple contexts within this key using `git_context` key.

Under `extensions`, you can specify which policy to run and what endpoint to call for that policy. Optionally, an input data map can be specified to transform the input passed to the OPA policy. This works by mapping (transforming) the original input data onto a new representation. In the example above, the original input data `"input":{{"payload": {..., "args": {"repo_path": ..., ...}, "context": "git_context": {...}}, ...}}` is mapped to `"input":{"repo_path": ..., "git_context": {...}}`. Observe that the policy (rego file) must accept the input schema.

In the `config` key in `config.yaml` for the OPA plugin, the following attribute must be set to configure the OPA server endpoint:
`opa_base_url` : It is the base url on which opa server is running.


In the `config.yaml` file you can specify the information related to which particular tool, prompt or resource, you want to apply policies on. Since, all the tools in the gateway might have different modalities like text, image, etc, you can specify the modality to be used in policy. The result might have different types of content in it, could be image, text etc and using this `policy_modality` endpoint basically, you specify that type of content you extract from the result and apply policy on. This is particularly used in post hook, since the result could be a union of
`Union[TextContent, JSONContent, ImageContent, ResourceContent]`.

## Example with multiple hooks
Similar to above example, the policies could also be applied to other hooks like prompts, tools and resources for both pre and post hook invocation. In the provided example below:

```yaml
plugins:
  - name: "OPAPluginFilter"
    kind: "opapluginfilter.plugin.OPAPluginFilter"
    description: "An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies"
    version: "0.1.0"
    author: "Shriti Priya"
    hooks: ["tool_pre_invoke","tool_post_invoke", "prompt_pre_fetch", "prompt_post_fetch", "resource_pre_fetch", "resource_post_fetch"]
    tags: ["plugin"]
    mode: "permissive"  # enforce | permissive | disabled
    priority: 30
    applied_to:
      tools:
        - tool_name: "fast-time-git-status"
          extensions:
            policy: "example"
            policy_endpoints:
              - "allow_tool_pre_invoke"
              - "allow_tool_post_invoke"
            policy_modality:
              - "text"
      prompts:
        - prompt_name: "test_prompt"
          extensions:
            policy: "example"
            policy_endpoints:
              - "allow_prompt_pre_fetch"
              - "allow_prompt_post_fetch"
            policy_modality:
              - "text"
      resources:
        - resource_uri: "https://example.com"
          extensions:
            policy: "example"
            policy_endpoints:
              - "allow_resource_pre_fetch"
              - "allow_resource_post_fetch"
            policy_modality:
              - "text"

    conditions:
      # Apply to specific tools/servers
      - server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      # Plugin config dict passed to the plugin constructor
      opa_base_url: "http://127.0.0.1:8181/v1/data/"

# Plugin directories to scan
plugin_dirs:
  - "opapluginfilter"

# Global plugin settings
plugin_settings:
  parallel_execution_within_band: true
  plugin_timeout: 30
  fail_on_plugin_error: false
  enable_plugin_api: true
  plugin_health_check_interval: 60
```

3. Now suppose you have a sample policy in `policy.rego` file that allows a tool invocation only when "IBM" key word is present in the repo_path. Add the sample policy file or policy rego file that you defined, in `plugins/external/opa/opaserver/rego`.

3. Once you have your plugin defined in `config.yaml` and policy added in the rego file, run the following commands to build your OPA Plugin external MCP server using:
* `make build`:  This will build a docker image named `opapluginfilter`

```bash
Verification point:
docker images mcpgateway/opapluginfilter:latest
REPOSITORY                   TAG       IMAGE ID       CREATED        SIZE
mcpgateway/opapluginfilter   latest    a94428dd9c64   1 second ago   810MB
```

* `make start`: This will start the OPA Plugin server
```bash
Verification point:
✅ Container started
🔍 Health check status:
starting
```

## Testing with gateway

### Authentication & Tokens
Run the following from the project root folder:

```bash
# Generate JWT bearer token
python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key

# Export for API calls
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 0 --secret my-test-key)
```


1. Add server fast-time that exposes git tools in the mcp gateway
```bash
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast-time","url":"http://localhost:9000/sse"}' \
     http://localhost:4444/gateways
```

2. This adds server to the gateway and exposes all the tools for git. You would see `fast-time-git-status` as the tool appearing in the tools tab of mcp gateway.

3. The next step is to enable the opa plugin which you can do by adding `PLUGINS_ENABLED=true` and the following blob in `plugins/config.yaml` file. This will indicate that OPA Plugin is running as an external MCP server.

  ```yaml
  - name: "OPAPluginFilter"
    kind: "external"
    priority: 10 # adjust the priority
    mcp:
      proto: STREAMABLEHTTP
      url: http://127.0.0.1:8000/mcp
  ```

2. To test this plugin with the above tool `fast-time-git-status` you can either invoke it through the UI
```bash
# 1️⃣  Add fast-time server to mcpgateway
curl -s -X POST -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name":"fast-time","url":"http://localhost:9000/sse"}' \
     http://localhost:4444/gateways

# 2️⃣  Check if policies are in action.
# Deny case
curl -X POST -H "Content-Type: application/json" \
     -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -d '{"jsonrpc":"2.0","id":1,"method":"fast-time-git-status","params":{"repo_path":"path/BIM"}}' \
     http://localhost:4444/rpc

>>>
`{"detail":"policy_deny"}`

# 3️⃣ Check if policies are in action
# Allow case
curl -X POST -H "Content-Type: application/json" \
     -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     -d '{"jsonrpc":"2.0","id":1,"method":"fast-time-git-status","params":{"repo_path":"path/IBM"}}' \
     http://localhost:4444/rpc

>>>
`{"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"/Users/shritipriya/Documents/2025/271-PR/mcp-context-forge/path/IBM"}],"is_error":false},"id":1}`
```

## Test Coverage

In `policy.rego` file, the policy defaults to denying all requests unless specific conditions are met. It enforces security through pattern detection and filtering:

1. **Email**: Uses regex (barred_pattern) to detect email-like strings in text payloads, blocking outputs containing sensitive patterns
2. **Keyword Filtering**: Searches for specific words (e.g., "IBM") in request arguments and blocks profanity ("curseword1") in prompt inputs
3. **URL Validation**: Parses URIs to extract protocol, domain, port, and path components, then blocks resource access containing "root" in the path

The test file `test_opapluginfilter.py` validates OPA plugin behavior at six different hook points for tools, prompts, and resources:

1. **Tool Invocation Hooks** - Two tests (test_pre_tool_invoke_opapluginfilter and test_post_tool_invoke_opapluginfilter) verify policy enforcement before and after tool execution. Each test validates both benign requests (e.g., /path/IBM) that pass policy checks and malicious requests (e.g., /path/ibm or emails) that are correctly blocked by defined policy in `policy.rego` file.
2. **Prompt Fetch Hooks** - Two tests (test_pre_prompt_fetch_opapluginfilter and test_post_prompt_fetch_opapluginfilter) ensure policies properly filter prompt arguments and results. Tests check text content for prohibited patterns like specific curse words or email addresses.
3. **Resource Fetch Hooks** - Two tests (test_pre_resource_fetch_opapluginfilter and test_post_resource_fetch_opapluginfilter) validate policy enforcement on resource URIs and content. Tests verify that restricted paths (e.g., /root) and email-containing content are denied while safe content is allowed.
4. **Backward Compatibility** - One test (test_opapluginfilter_backward_compatibility) confirms the plugin supports legacy policy endpoint naming conventions using the generic allow endpoint instead of hook-specific endpoints.

To run the test cases, run the following command:
1. As a first step, first install OPA in your development machine.

```bash
# For Apple Silicon (M1/M2/M3)
curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_darwin_arm64_static

# For Intel Macs
curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_darwin_amd64

# Make executable
chmod 755 ./opa

# Verify installation
opa --version
```

2. Once, OPA is installed run the test using:
```bash
make test
```

The`make test` command executes a complete testing workflow: it launches an OPA server using the policy file located at ./opaserver/rego/policy.rego (as specified by `POLICY_PATH`), runs all test cases against this server, and automatically terminates the OPA server process once testing finishes.


## Error Handling Verification

1. `OPA_SERVER_NONE_RESPONSE` = "OPA server returned an empty response"
2. `OPA_SERVER_ERROR` = "Error while communicating with the OPA server"
3. `OPA_SERVER_UNCONFIGURED_ENDPOINT` = "Policy endpoint not configured on the OPA server"
4. `UNSPECIFIED_REQUIRED_PARAMS` = "Required parameters missing: policy config, payload, or hook type"
5. `UNSUPPORTED_HOOK_TYPE` = "Unsupported hook type (only tool, prompt, and resource are supported)"
6. `INVALID_POLICY_ENDPOINT` = "Policy endpoint must be curated with the supported hooktypes"
7. `UNSPECIFIED_POLICY_MODALITY` = "Unspecified policy modality. Picking up default modality: text"
8. `UNSUPPORTED_POLICY_MODALITY` = "Unsupported policy modality (Supports text, image and resource)"
9. `UNSPECIFIED_POLICY_PACKAGE_NAME` = "Unspecified policy package name"

If OPA plugin encounters any of the errors above, it raises a PluginError.
The file `test_errors.py` includes unit tests to verify that these errors are correctly raised under the corresponding conditions.
Run it using `make test`

## License

Apache-2.0

## Support

For issues or questions, please open an issue in the MCP Gateway repository.
