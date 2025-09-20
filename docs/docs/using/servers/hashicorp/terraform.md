# Terraform MCP Server

## Overview

(Brief introduction to Terraform MCP Server capabilities)

The **Terraform MCP Server** is a Model Context Protocol Server that enables seamless integration with [Terraform Registry APIs](https://developer.hashicorp.com/terraform/registry/api-docs), supporting advanced automation and interactive workflows in Infrastructure as Code (IaC) development.

### Features

➡️ **Supports two transport mechannisms:**

#### 1. Stdio

Standard input/output streams for direct process communication between local processes on the same machine, providing optimal performance with no network overhead.

#### 2. Streamable HTTP

Uses HTTP POST for client-to-server messages with optional Server-Sent Events (SSE) for streaming capabilities. This is the recommended transport for remote/distributed setups.

➡️ **Terraform Provider Discovery**: Query and explore Terraform providers and their documentation

➡️ **Module Search & Analysis**: Search and retrieve detailed information about Terraform modules

➡️ **Registry Integration**: Direct integration with Terraform Registry APIs

➡️ **Container Ready**: Docker support for easy deployment

## Prerequisites

To install the server from source, you must have [Go](https://go.dev/doc/install) installed on your system.

## Installation and setup

#### Install the latest release version
```shell
go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest
```
#### Install the main branch from source
```shell
go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@main
```

#### Sessions mode in Streamable HTTP transport

The Terraform MCP Server supports two session modes when using the StreamableHTTP transport:

**Stateful Mode (Default)**: Maintains session state between requests, enabling context-aware operations.

**Stateless Mode**: Each request is processed independently without maintaining session state, which can be useful for high-availability deployments or when using load balancers.
To enable stateless mode, set the environment variable: `export MCP_SESSION_MODE=stateless`

#### Configuring Environment Variables

| Variable               | Description                                              | Default     |
|------------------------|----------------------------------------------------------|-------------|
| `TRANSPORT_MODE`       | Set to `streamable-http` to enable HTTP transport (legacy `http` value still supported) | `stdio`     |
| `TRANSPORT_HOST`       | Host to bind the HTTP server                             | `127.0.0.1` |
| `TRANSPORT_PORT`       | HTTP server port                                         | `8080`      |
| `MCP_ENDPOINT`         | HTTP server endpoint path                                | `/mcp`      |
| `MCP_SESSION_MODE`     | Session mode: `stateful` or `stateless`                  | `stateful`  |
| `MCP_ALLOWED_ORIGINS`  | Comma-separated list of allowed origins for CORS         | `""` (empty)|
| `MCP_CORS_MODE`        | CORS mode: `strict`, `development`, or `disabled`        | `strict`    |
| `MCP_RATE_LIMIT_GLOBAL`| Global rate limit (format: `rps:burst`)                  | `10:20`     |
| `MCP_RATE_LIMIT_SESSION`| Per-session rate limit (format: `rps:burst`)            | `5:10`      |


#### Running the server in Stdio mode

```shell
terraform-mcp-server stdio [--log-file /path/to/log]
```

#### Running the server in Streamable HTTP mode

```shell
terraform-mcp-server streamable-http [--transport-port 8080] [--transport-host 127.0.0.1] [--mcp-endpoint /mcp] [--log-file /path/to/log]
```

Given your configuration, the endpoint could be the following:

* Server: `http://{hostname}:8080/mcp`
* Health Check: `http://{hostname}:8080/health`

    ```shell
    curl -s http://127.0.0.1:8080/health | jq
    {
      "status": "ok",
      "service": "terraform-mcp-server",
      "transport": "streamable-http",
      "endpoint": "/mcp"
    }
    ```


<!-- - Terraform workspace configuration
- Provider authentication setup -->

## MCP Gateway Integration

### Registration with MCP Gateway

```shell
# Registering Terraform server in Streamable HTTP mode
curl --request POST \
  --url "http://${MCPGATEWAY_BASE_URL}:4444/gateways" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
	"name": "terraform_server",
	"url": "http://127.0.0.1:8080/mcp",
	"description": "Terraform MCP Server",
	"transport": "STREAMABLEHTTP"
}'
```

### Getting the Terraform server toolset

```shell
curl --request GET \
  --url http://localhost:4444/tools \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
```

### Available tools

#### Providers

##### `search_providers`

```json
"properties": {
    "provider_data_type": {
        "default": "resources",
        "description": "The type of the document to retrieve, for general information use 'guides', for deploying resources use 'resources', for reading pre-deployed resources use 'data-sources', for functions use 'functions', and for overview of the provider use 'overview'",
        "enum": [
            "resources",
            "data-sources",
            "functions",
            "guides",
            "overview"
        ],
        "type": "string"
    },
    "provider_name": {
        "description": "The name of the Terraform provider to perform the read or deployment operation",
        "type": "string"
    },
    "provider_namespace": {
        "description": "The publisher of the Terraform provider, typically the name of the company, or their GitHub organization name that created the provider",
        "type": "string"
    },
    "provider_version": {
        "description": "The version of the Terraform provider to retrieve in the format 'x.y.z', or 'latest' to get the latest version",
        "type": "string"
    },
    "service_slug": {
        "description": "The slug of the service you want to deploy or read using the Terraform provider, prefer using a single word, use underscores for multiple words and if unsure about the service_slug, use the provider_name for its value",
        "type": "string"
    }
}
```

##### `get_provider_details`

```json
"properties": {
    "provider_doc_id": {
        "description": "Exact tfprovider-compatible provider_doc_id, (e.g., '8894603', '8906901') retrieved from 'search_providers'",
        "type": "string"
    }
}
```

##### `get_latest_provider_version`

```json
"properties": {
    "name": {
        "description": "The name of the Terraform provider, e.g., 'aws', 'azurerm', 'google', etc.",
        "type": "string"
    },
    "namespace": {
        "description": "The namespace of the Terraform provider, typically the name of the company, or their GitHub organization name that created the provider e.g., 'hashicorp'",
        "type": "string"
    }
}
```

#### Modules

##### `search_modules`

```json
"properties": {
    "module_query": {
        "description": "The query to search for Terraform modules.",
        "type": "string"
    }
}
```

##### `get_module_details`

```json
"properties": {
    "module_id": {
        "description": "Exact valid and compatible module_id retrieved from search_modules (e.g., 'squareops/terraform-kubernetes-mongodb/mongodb/2.1.1', 'GoogleCloudPlatform/vertex-ai/google/0.2.0')",
        "type": "string"
    }
}
```

##### `get_latest_module_version`

```json
"properties": {
    "module_name": {
        "description": "The name of the module, this is usually the service or group of service the user is deploying e.g., 'security-group', 'secrets-manager' etc.",
        "type": "string"
    },
    "module_provider": {
        "description": "The name of the Terraform provider for the module, e.g., 'aws', 'google', 'azurerm' etc.",
        "type": "string"
    },
    "module_publisher": {
        "description": "The publisher of the module, e.g., 'hashicorp', 'aws-ia', 'terraform-google-modules', 'Azure' etc.",
        "type": "string"
    }
}
```

#### Policies

##### `search_policies`

```json
"properties": {
    "policy_query": {
        "description": "The query to search for Terraform modules.",
        "type": "string"
    }
```

##### `get_policy_details`

```json
"properties": {
    "terraform_policy_id": {
        "description": "Matching terraform_policy_id retrieved from the 'search_policies' tool (e.g., 'policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1')",
        "type": "string"
    }
}
```

Server configuration examples
Available IaC automation and interaction tools

### Create Virtual server and expose the Terraform tools

```shell
curl --request POST \
  --url "http://${MCPGATEWAY_BASE_URL}:4444/servers" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
	"name": "terraform_server",
	"description": "Terraform MCP Server with module search and registry integration",
	"associatedTools": [
        "'$TERRAFORM_TOOL_ID_1'",
        "'$TERRAFORM_TOOL_ID_2'",
        "'$TERRAFORM_TOOL_ID_3'",
        "'$TERRAFORM_TOOL_ID_4'",
        "'$TERRAFORM_TOOL_ID_5'",
        "'$TERRAFORM_TOOL_ID_6'",
        "'$TERRAFORM_TOOL_ID_7'",
        "'$TERRAFORM_TOOL_ID_8'"
    ]
}'
```

## Usage Examples

Infrastructure provisioning
State management operations
Plan and apply workflows
Resource inspection

## Troubleshooting

Authentication issues
Provider configuration problems
State file conflicts


