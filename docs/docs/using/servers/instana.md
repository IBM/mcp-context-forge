# IBM Instance MCP Server

## Overview

The **Instana MCP server** is built as a comprehensive wrapper around Instana's public REST APIs. It translates conversational queries into precise API calls and formats responses for AI assistants.

The Instana MCP server enables seamless interaction with the Instana observability platform, allowing you to access real-time observability data directly within your development workflow.

It serves as a bridge between clients (such as AI agents or custom tools) and the Instana REST APIs, converting user queries into Instana API requests and formatting the responses into structured, easily consumable formats.

The server supports both Streamable HTTP and Stdio transport modes for maximum compatibility with different MCP clients.

## Features

- Comprehensive API coverage: Access to Instana's complete REST API suite, including metrics retrieval, resource discovery, alert management, and infrastructure analysis.
- Intelligent query processing: Features automatic parameter validation, pagination handling, response formatting, and contextual error messaging optimized for AI interactions.
- Flexible filtering: Offers advanced filtering options, such as, time-based queries, tag-based searches, metric thresholds, and text-based discovery across your observability stack.
- Natural language interface: Each tool is designed to understand conversational queries such as:
"Show me applications with high error rates in the last hour"
"What infrastructure plugins are available for monitoring databases?"
"List all active alert configurations for our production services."

## Prerequisites - IBM Instana setup, API tokens, required permissions

### Option 1: Install from PyPI (Recommended)

The easiest way to use mcp-instana is to install it directly from PyPI:

```py
pip install mcp-instana
```

After installation, you can run the server using the mcp-instana command directly.

### Option 2: Development Installation

For development or local customization, you can clone and set up the project locally.

### Installing uv

This project uses `uv`, a fast Python package installer and resolver. To install `uv`, you have several options:

#### Using pip

`pip install uv`

#### Using Homebrew (macOS)

`brew install uv`

For more installation options and detailed instructions, visit the `uv` documentation.

### Setting Up the Environment

After installing `uv`, set up the project environment by running:

`uv sync`

### Header-Based Authentication for Streamable HTTP Mode

When using Streamable HTTP mode, you must pass Instana credentials via HTTP headers. This approach enhances security and flexibility by:

- Avoiding credential storage in environment variables
- Enabling the use of different credentials for different requests
- Supporting shared environments where environment variable modification is restricted

### Required Headers

- `instana-base-url`: Your Instana instance URL
- `instana-api-token`: Your Instana API token

### Authentication Flow

HTTP headers (`instana-base-url, instana-api-token`) must be present in each request
Requests without these headers will fail
This design ensures secure credential transmission where credentials are only sent via headers for each request, making it suitable for scenarios requiring different credentials or avoiding credential storage in environment variables.

## Server Configuration

### Installation and Setup

### Instana authentication configuration

### Monitoring scope setup

## MCP Gateway Integration

### Registration with MCP Gateway

### Server configuration examples

### Available monitoring and inspection tools

## Usage Examples

### Claude Desktop Configuration

Claude Desktop supports both Streamable HTTP and Stdio modes for MCP integration.

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "Instana MCP Server": {
      "command": "mcp-instana",
      "args": ["--transport", "stdio"],
      "env": {
        "INSTANA_BASE_URL": "https://your-instana-instance.instana.io",
        "INSTANA_API_TOKEN": "your_instana_api_token"
      }
    }
  }
}
```

### GitHub Copilot Configuration

You can directly create or update .vscode/mcp.json with the following configuration:

Step 1: Start the MCP Server in Streamable HTTP Mode

Before configuring VS Code, you need to start the MCP server in Streamable HTTP mode.

Step 2: Configure VS Code

You can directly create or update .vscode/mcp.json with the following configuration:

{
  "servers": {
    "Instana MCP Server": {
      "command": "npx",
      "args": [
        "mcp-remote", "http://0.0.0.0:8080/mcp/",
        "--allow-http",
        "--header", "instana-base-url: https://your-instana-instance.instana.io",
        "--header", "instana-api-token: your_instana_api_token"
      ],
      "env": {
        "PATH": "/usr/local/bin:/bin:/usr/bin",
        "SHELL": "/bin/sh"
      }
    }
  }
}

### Application monitoring queries

### Infrastructure resource inspection

### Performance analysis

### Alert and incident management

## Troubleshooting

### Authentication issues

### API connectivity problems

### Data access permissions
