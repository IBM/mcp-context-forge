# OPA Plugin for MCP Gateway

> Author: Shriti Priya
> Version: 0.1.0

An OPA plugin that enforces rego policies on requests and allows/denies requests as per policies.

The OPA plugin is composed of two components:
1. OPA server
2. The pre hooks on tools that talks to OPA server running as background service within the same container. Whenever a tool is invoked, if OPA Plugin is in action, a policy will be applied on the tool call to allow/deny it.

### OPA Server
To define a policy file you need to go into opaserver/rego and create a sample policy file for you.
Example -`example.rego` is present.
Once you have this file created in this location, when building the server, the opa binaries will be downloaded and a container will be build.
In the `run_server.sh` file, the opa server will run as a background service in the container with the rego policy file.

### OPA Plugin
The OPA plugin runs as an external plugin with pre/post tool invocations. So everytime, a tool invocation is made, and if OPAPluginFilter has been defined in config.yaml file, the tool invocation will pass through this OPA Plugin.


## Installation

1. In the folder `external/opa`, copy .env.example .env
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
    conditions:
      # Apply to specific tools/servers
      - server_ids: []  # Apply to all servers
        tenant_ids: []  # Apply to all tenants
    config:
      # Plugin config dict passed to the plugin constructor
      opa_base_url: "http://127.0.0.1:8181/v1/data/"
```
The `applied_to` key in config.yaml, has been used to selectively apply policies and provide context for a specific tool.
Here, using this, you can provide the `name` of the tool you want to apply policy on, you can also provide
context to the tool with the prefix `global` if it needs to check the context in global context provided.
The key `opa_policy_context` is used to get context for policies and you can have multiple contexts within this key using `git_context` key.
You can also provide policy within the `extensions` key where you can provide information to the plugin
related to which policy to run and what endpoint to call for that policy.
In the `config` key in `config.yaml` file OPAPlugin consists of the following things:
`opa_base_url` : It is the base url on which opa server is running.

3. Now suppose i have a sample policy, in `example.rego` file that allows a tool invocation only when "IBM" key word is present in the repo_path. Add the sample policy file or policy rego file that you defined, in `plugins/external/opa/opaserver/rego`.

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

## License

Apache-2.0

## Support

For issues or questions, please open an issue in the MCP Gateway repository.
