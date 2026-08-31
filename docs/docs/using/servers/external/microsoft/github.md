# GitHub MCP Server

## Overview

The GitHub MCP Server connects AI tools directly to GitHub's platform, giving AI agents the ability to read repositories and code files, manage issues and PRs, analyze code, and automate workflows through natural language interactions.

**Remote Server Endpoint:** `https://api.githubcopilot.com/mcp/`

**Authentication:** OAuth or Personal Access Token

## Use Cases

- **Repository Management:** Browse and query code, search files, analyze commits, and understand project structure
- **Issue & PR Automation:** Create, update, and manage issues and pull requests, triage bugs, review code changes
- **CI/CD & Workflow Intelligence:** Monitor GitHub Actions workflow runs, analyze build failures, manage releases
- **Code Analysis:** Examine security findings, review Dependabot alerts, understand code patterns
- **Team Collaboration:** Access discussions, manage notifications, analyze team activity

## Integration with ContextForge

There are two ways to use the GitHub MCP Server with ContextForge:

### Option 1: Remote GitHub MCP Server (Recommended)

The remote server is hosted by GitHub at `https://api.githubcopilot.com/mcp/` and provides the easiest setup method.

#### Using OAuth Authentication

```bash
# Register the GitHub MCP server with ContextForge
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "name": "github-remote",
    "url": "https://api.githubcopilot.com/mcp/",
    "transport": "http",
    "description": "Remote GitHub MCP Server (OAuth)"
  }'
```

#### Using Personal Access Token

1. Create a GitHub Personal Access Token at [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Select the appropriate scopes for your needs

```bash
# Register with PAT authentication
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "name": "github-remote",
    "url": "https://api.githubcopilot.com/mcp/",
    "transport": "http",
    "auth_config": {
      "type": "bearer",
      "token": "'${GITHUB_PAT}'"
    },
    "description": "Remote GitHub MCP Server (PAT)"
  }'
```

### Option 2: Local GitHub MCP Server (Docker)

Run the GitHub MCP server locally using Docker and expose it through ContextForge.

#### Prerequisites

- Docker installed and running
- GitHub Personal Access Token

#### Setup

1. **Start the local server with translate:**

```bash
# Using mcpgateway.translate to expose the Docker container
python3 -m mcpgateway.translate --stdio \
  "docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} ghcr.io/github/github-mcp-server" \
  --port 9001
```

2. **Register with ContextForge:**

```bash
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "name": "github-local",
    "url": "http://localhost:9001",
    "transport": "sse",
    "description": "Local GitHub MCP Server"
  }'
```

## Tool Configuration

The GitHub MCP Server supports enabling or disabling specific groups of tools via environment variables or command-line flags.

### Available Toolsets

| Toolset | Description |
|---------|-------------|
| `context` | **Strongly recommended:** Tools that provide context about current user and GitHub environment |
| `actions` | GitHub Actions workflows and CI/CD operations |
| `code_security` | Code security related tools (Code Scanning) |
| `dependabot` | Dependabot tools |
| `discussions` | GitHub Discussions |
| `experiments` | Experimental features (not stable) |
| `gists` | GitHub Gist operations |
| `issues` | GitHub Issues |
| `notifications` | GitHub Notifications |
| `orgs` | GitHub Organization tools |
| `pull_requests` | GitHub Pull Request operations |
| `repos` | GitHub Repository tools |
| `secret_protection` | Secret scanning and protection |
| `security_advisories` | Security advisories |
| `users` | GitHub User tools |

### Configuring Toolsets

#### For Local Docker Server

```bash
# Enable specific toolsets
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_TOOLSETS="repos,issues,pull_requests,actions,code_security" \
  ghcr.io/github/github-mcp-server

# Or use all toolsets
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_TOOLSETS="all" \
  ghcr.io/github/github-mcp-server

# Run in read-only mode
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_READ_ONLY=1 \
  ghcr.io/github/github-mcp-server
```

### Dynamic Tool Discovery (Beta)

Enable dynamic toolset discovery to have tools enabled on-demand based on user prompts:

```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_DYNAMIC_TOOLSETS=1 \
  ghcr.io/github/github-mcp-server
```

## Creating a Virtual Server

After registering the gateway peer, create a virtual server to expose the GitHub tools:

```bash
# Create virtual server
curl -X POST http://localhost:4444/servers \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "name": "github-server",
    "description": "GitHub MCP Server with repository and issue management",
    "gateway_ids": ["github-remote"],
    "tool_choice": "auto"
  }'
```

## Using GitHub Tools

Once configured, you can access GitHub tools through ContextForge:

### List Available Tools

```bash
curl -X GET "http://localhost:4444/servers/{server_id}/tools" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}"
```

### Example Tool Invocations

#### Search Repositories
```bash
curl -X POST "http://localhost:4444/tools/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "server_id": "github-server",
    "tool_name": "search_repositories",
    "arguments": {
      "query": "language:python stars:>1000"
    }
  }'
```

#### Create Issue
```bash
curl -X POST "http://localhost:4444/tools/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "server_id": "github-server",
    "tool_name": "create_issue",
    "arguments": {
      "owner": "your-org",
      "repo": "your-repo",
      "title": "Bug: Application crashes on startup",
      "body": "## Description\nThe application fails to start..."
    }
  }'
```

#### List Workflow Runs
```bash
curl -X POST "http://localhost:4444/tools/invoke" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${MCPGATEWAY_BEARER_TOKEN}" \
  -d '{
    "server_id": "github-server",
    "tool_name": "list_workflow_runs",
    "arguments": {
      "owner": "your-org",
      "repo": "your-repo"
    }
  }'
```

## GitHub Enterprise Support

For GitHub Enterprise Server or Enterprise Cloud with data residency:

### Enterprise Server
```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_HOST="https://your-github-enterprise.com" \
  ghcr.io/github/github-mcp-server
```

### Enterprise Cloud with Data Residency
```bash
docker run -i --rm \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PAT} \
  -e GITHUB_HOST="https://yoursubdomain.ghe.com" \
  ghcr.io/github/github-mcp-server
```

## Security Considerations

1. **Token Management**: Store GitHub PATs securely using environment variables or secret management systems
2. **Scope Limitation**: Only grant the minimum required permissions for your use case
3. **Rate Limiting**: The GitHub API has rate limits - monitor usage and implement appropriate caching
4. **Audit Logging**: Enable ContextForge audit logging to track all GitHub operations

## Troubleshooting

### Connection Issues

```bash
# Test direct connection to GitHub MCP server
curl -X POST https://api.githubcopilot.com/mcp/ \
  -H "Authorization: Bearer ${GITHUB_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}'
```

### Docker Container Issues

```bash
# Check if container is running
docker ps | grep github-mcp-server

# View container logs
docker logs $(docker ps -q -f ancestor=ghcr.io/github/github-mcp-server)
```

### Authentication Errors

- Verify PAT has correct scopes
- Check token expiration
- Ensure proper header format: `Authorization: Bearer YOUR_TOKEN`

## Additional Resources

- [GitHub MCP Server Repository](https://github.com/github/github-mcp-server)
- [GitHub Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [GitHub API Documentation](https://docs.github.com/en/rest)
- [ContextForge Documentation](../../../index.md)
