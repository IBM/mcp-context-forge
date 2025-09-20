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
    curl -s http://localhost:8080/health | jq
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

Registration with MCP Gateway
Server configuration examples
Available IaC automation and interaction tools

## Usage Examples

Infrastructure provisioning
State management operations
Plan and apply workflows
Resource inspection

## Troubleshooting

Authentication issues
Provider configuration problems
State file conflicts


