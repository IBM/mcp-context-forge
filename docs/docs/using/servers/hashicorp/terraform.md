# Terraform MCP Server

## Overview

The Terraform MCP Server is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/docs/getting-started/intro) server that enables seamless integration between Terraform and MCP-compatible tools. It provides a consistent, typed interface for querying and interacting with the [Terraform Registry](https://registry.terraform.io/), making it easier to search providers, explore resources and data sources, and retrieve module details.

### Features

➡️ **Supports two transport mechanisms:**

* **Stdio**: Standard input/output streams for direct process communication between local processes on the same machine, providing optimal performance with no network overhead.
* **Streamable HTTP**: Uses HTTP POST for client-to-server messages with optional Server-Sent Events (SSE) for streaming capabilities. This is the recommended transport for remote/distributed setups.

➡️ **Terraform Provider Discovery**: Query and explore Terraform providers and their documentation

➡️ **Module Search & Analysis**: Search and retrieve detailed information about Terraform modules

➡️ **Registry Integration**: Direct integration with Terraform Registry APIs

➡️ **Container Ready**: Docker support for easy deployment

This makes the Terraform MCP Server a powerful tool for enabling advanced automation and interaction workflows in Infrastructure as Code (IaC) development.

## Prerequisites

* **Go** – Required if you plan to install the server from source. Install [Go](https://go.dev/doc/install).
* **Docker** – Required if you plan to run the server in a container. Install [Docker](https://www.docker.com/).
* **jq** – Optional but recommended for formatting JSON output in command results. Install [jq](https://jqlang.org/download/).

## Installation And Setup

### Option 1: Install from source (Go)

#### Install the latest release version
```shell
go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest
```
#### Install the main branch from source
```shell
go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@main
```

### Option 2: Build The Image (Docker)

```shell
# Clone the source repository
git clone https://github.com/hashicorp/terraform-mcp-server.git && cd terraform-mcp-server
# Build the docker image
make docker-build
```

### Sessions Mode In Streamable HTTP Transport

The Terraform MCP Server supports two session modes when using the Streamable HTTP transport:

**Stateful Mode (Default)**: Maintains session state between requests, enabling context-aware operations.

**Stateless Mode**: Each request is processed independently without maintaining session state, which can be useful for high-availability deployments or when using load balancers.
To enable stateless mode, set the environment variable: `export MCP_SESSION_MODE=stateless`

### Environment Variables Configuration

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

### Starting the Server

#### [Go] Running the server in Stdio mode

```shell
terraform-mcp-server stdio [--log-file /path/to/log]
```

#### [Go] Running the server in Streamable HTTP mode

```shell
terraform-mcp-server streamable-http [--transport-port 8080] [--transport-host 127.0.0.1] [--mcp-endpoint /mcp] [--log-file /path/to/log]
```

#### [Docker] Running the server in Stdio mode

```shell
docker run -i --rm terraform-mcp-server:dev
```

#### [Docker] Running the server in Streamable HTTP mode

```shell
docker run -p 8080:8080 --rm -e TRANSPORT_MODE=streamable-http -e TRANSPORT_HOST=0.0.0.0 terraform-mcp-server:dev
```

### Server endpoint

Given your configuration, the endpoint could be the following:

* Server: `http://{hostname}:8080/mcp`

## ContextForge Integration

> Set the following environment variables on your system, as they will be used in subsequent commands for ContextForge integration.

```shell
export MCPGATEWAY_BASE_URL=""       # e.g: http://mcp.gateway.com:4444
export MCPGATEWAY_BEARER_TOKEN=""   # e.g: gateway-bearer-token
```

### Registration With ContextForge

```shell
# Registering the Terraform Server in Streamable HTTP mode
curl --request POST \
  --url "${MCPGATEWAY_BASE_URL}/gateways" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
    "name": "terraform_server",
    "url": "http://127.0.0.1:8080/mcp",
    "description": "Terraform MCP Server",
    "transport": "STREAMABLEHTTP"
}' | jq
```

### Obtain IDs for available tools

```shell
# Lists Terraform tools from the registered server, fetches their IDs, and exports them as environment variables (TERRAFORM_TOOL_ID_1 … TERRAFORM_TOOL_ID_8)
i=1; for id in $(curl --url "${MCPGATEWAY_BASE_URL}/tools" --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" | jq -r '.[].id'); do export TERRAFORM_TOOL_ID_$i="$id"; echo "TERRAFORM_TOOL_ID_$i=$id"; i=$((i+1)); done
```

### Create Virtual Server And Expose The Terraform Tools

```shell
curl --request POST \
  --url "${MCPGATEWAY_BASE_URL}/servers" \
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
}' | jq
```

### Retrieve Exposed Terraform Tools

```shell
export TERRAFORM_SERVER_ID="" # Virtual Server ID returned by the previous command
curl --request GET \
  --url "${MCPGATEWAY_BASE_URL}/servers/${TERRAFORM_SERVER_ID}/tools" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" | jq
```

### Available Tools

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

### Available tools for Terraform Enterprise

| Toolset   | Tool               | Description                                                                |
|-----------|--------------------|----------------------------------------------------------------------------|
| `orgs`    | list_organizations | Lists all Terraform organizations accessible to the authenticated user.    |
| `projects`| list_projects      | Lists all projects within a specified Terraform organization.              |

## Example Tool Invocations

**Search for the latest IBM provider version**

```shell
curl --request POST \
  --url "${MCPGATEWAY_BASE_URL}/rpc" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "terraform-server-get-latest-provider-version",
    "params": {
        "name": "ibm",
        "namespace": "IBM-Cloud"
    }
}' | jq -r '.result.content[0].text'
```

**Search for AWS provider overview information**

```shell
curl --request POST \
  --url "${MCPGATEWAY_BASE_URL}/rpc" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "terraform-server-search-providers",
    "params": {
      "provider_data_type": "overview",
      "provider_name": "aws",
      "provider_namespace": "hashicorp",
      "provider_version": "latest",
      "service_slug": "aws"
    }
}' | jq -r '.result.content[0].text'
```

The command above outputs a server log containing the document ID:
```log
INFO[38080] [DEBUG] GET https://registry.terraform.io/v2/provider-docs/9983624
```
The document ID is used in the execution of the next tool.

**Search AWS provider details**

```shell
curl --request POST \
  --url "${MCPGATEWAY_BASE_URL}/rpc" \
  --header "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "terraform-server-get-provider-details",
    "params": {
        "provider_doc_id": "9983624"
    }
}' | jq -r '.result.content[0].text'
```

## Troubleshooting

### Server Health Check

```shell
# Run a Health Check on the Terraform MCP Server
curl http://127.0.0.1:8080/health
```

### Connection issues

```shell
# Test direct connection to Terraform MCP server
curl -X POST http://127.0.0.1:8080/mcp/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {},
    "id": 1
  }'
```

### Docker container issues

```shell
# Check container logs
docker ps --filter "ancestor=terraform-mcp-server:dev" --format "{{.ID}}"
```

## Additional Resources

* [Terraform MCP Server Repository](https://github.com/hashicorp/terraform-mcp-server/tree/main)
* [ContextForge Documentation](https://github.com/IBM/mcp-context-forge/blob/main/docs/docs/using/index.md)
