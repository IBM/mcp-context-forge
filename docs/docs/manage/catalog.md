# MCP Server Catalog

> 🆕 **New in v0.7.0**: The MCP Server Catalog feature allows you to define a catalog of pre-configured MCP servers in a YAML file for easy discovery, registration, and management via the Admin UI and API.

## Overview

The MCP Server Catalog provides a declarative way to define and manage MCP servers, reducing manual configuration and enabling automated server registration and health monitoring.

**Key Features:**

- 📝 **Declarative Configuration**: Define servers in YAML format
- 🔍 **Automatic Discovery**: Servers are automatically registered on startup
- 💚 **Health Monitoring**: Automatic health checks for catalog servers
- 🗂️ **Categorization**: Organize servers with tags and descriptions
- ⚡ **Fast Onboarding**: Quickly add new MCP servers without API calls

---

## Configuration

### Environment Variables

Configure the catalog feature using these environment variables:

```bash
# Enable MCP server catalog feature (default: true)
MCPGATEWAY_CATALOG_ENABLED=true

# Path to catalog configuration file (default: mcp-catalog.yml)
MCPGATEWAY_CATALOG_FILE=mcp-catalog.yml

# Automatically health check catalog servers (default: true)
MCPGATEWAY_CATALOG_AUTO_HEALTH_CHECK=true

# Catalog cache TTL in seconds (default: 3600)
MCPGATEWAY_CATALOG_CACHE_TTL=3600

# Number of catalog servers to display per page (default: 12)
MCPGATEWAY_CATALOG_PAGE_SIZE=12
```

---

## Catalog File Format

The catalog file uses YAML format with the following structure:

### Basic Example

```yaml
# mcp-catalog.yml
catalog_servers:

  - id: "time-server"
    name: "Time Server"
    category: "Utilities"
    url: "http://localhost:9000/sse"
    auth_type: "Open"
    provider: "Local"
    description: "Fast time server providing current time utilities"
    requires_api_key: false
    tags:

      - "utilities"
      - "time"
      - "development"

  - id: "git-server"
    name: "Git Server"
    category: "Software Development"
    url: "http://localhost:9001/sse"
    auth_type: "Open"
    provider: "Local"
    description: "Git repository MCP server"
    requires_api_key: false
    tags:

      - "git"
      - "version-control"
      - "development"

# Optional: Categories for UI filtering
categories:

  - Utilities
  - Software Development

# Optional: Auth types for UI filtering
auth_types:

  - Open
  - OAuth2.1
  - API Key
```

### Full Example with All Fields

```yaml
# Production MCP Server Catalog
catalog_servers:

  - id: "production-time-server"
    name: "Production Time Server"
    category: "Utilities"
    url: "https://time.api.example.com/sse"
    transport: "SSE"  # Optional: Explicitly specify transport type
    auth_type: "OAuth2.1"
    provider: "Internal Platform"
    description: "Production time server with geo-replication"
    requires_api_key: false
    secure: true
    tags:

      - "production"
      - "utilities"
      - "time"
      - "geo-replicated"
    logo_url: "https://static.example.com/time-server-logo.png"
    documentation_url: "https://docs.example.com/time-server"

  - id: "websocket-server"
    name: "WebSocket MCP Server"
    category: "Development Tools"
    url: "wss://api.example.com/mcp"
    transport: "WEBSOCKET"  # Specify WebSocket transport
    auth_type: "API Key"
    provider: "Internal Platform"
    description: "Real-time MCP server using WebSocket protocol"
    requires_api_key: true
    secure: true
    tags:

      - "production"
      - "websocket"
      - "real-time"

  - id: "database-server"
    name: "Database Server"
    category: "Database"
    url: "https://db.api.example.com/sse"
    auth_type: "OAuth2.1"
    provider: "Internal Platform"
    description: "Database query and management MCP server"
    requires_api_key: false
    secure: true
    tags:

      - "production"
      - "database"
      - "postgresql"
    documentation_url: "https://docs.example.com/db-server"

  - id: "github-api"
    name: "GitHub"
    category: "Software Development"
    url: "https://api.githubcopilot.com/mcp"
    auth_type: "OAuth2.1"
    provider: "GitHub"
    description: "Version control and collaborative software development"
    requires_api_key: false
    secure: true
    tags:

      - "development"
      - "git"
      - "version-control"
    logo_url: "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png"
    documentation_url: "https://docs.github.com"

categories:

  - Utilities
  - Database
  - Software Development

auth_types:

  - OAuth2.1
  - API Key
  - Open
```

---

## Field Reference

### Root Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `catalog_servers` | array | Yes | List of MCP server definitions |
| `categories` | array | No | List of available categories for UI filtering |
| `auth_types` | array | No | List of available auth types for UI filtering |

### Catalog Server Fields

Based on the `CatalogServer` schema (schemas.py:5371-5387):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique identifier for the catalog server |
| `name` | string | Yes | Display name of the server |
| `category` | string | Yes | Server category (e.g., "Project Management", "Software Development") |
| `url` | string | Yes | Server endpoint URL |
| `auth_type` | string | Yes | Authentication type (e.g., "OAuth2.1", "API Key", "Open") |
| `provider` | string | Yes | Provider/vendor name |
| `description` | string | Yes | Server description |
| `requires_api_key` | boolean | No | Whether API key is required (default: `false`) |
| `secure` | boolean | No | Whether additional security is required (default: `false`) |
| `tags` | array | No | Tags for categorization (default: `[]`) |
| `transport` | string | No | Transport type: `SSE`, `STREAMABLEHTTP`, or `WEBSOCKET` (auto-detected if not specified) |
| `logo_url` | string | No | URL to server logo/icon |
| `documentation_url` | string | No | URL to server documentation |
| `is_registered` | boolean | No | Whether server is already registered (set by system) |
| `is_available` | boolean | No | Whether server is currently available (default: `true`) |

---

## Usage

### Automatic Registration on Startup

When `MCPGATEWAY_CATALOG_ENABLED=true`, the gateway automatically:

1. Reads the catalog file on startup
2. Registers all enabled servers
3. Starts health checks (if enabled)
4. Makes servers available via the Admin UI and API

### Manual Catalog Reload

Reload the catalog without restarting the gateway:

```bash
# Using the CLI
mcpgateway catalog reload

# Or via API
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/admin/catalog/reload
```

### Listing Catalog Servers

```bash
# Via CLI
mcpgateway catalog list

# Via API
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:4444/admin/catalog/servers
```

### Filtering by Tags

```bash
# List all production servers
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/catalog/servers?tag=production"

# List all database servers
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/admin/catalog/servers?tag=database"
```

---

## Best Practices

### 1. Use Consistent Naming

Use clear, descriptive IDs and names:

```yaml
catalog_servers:

  - id: "github-production"  # ✅ Good: Clear and unique
    name: "GitHub Production"
    # ... other fields
```

### 2. Organize with Tags

Use consistent tagging for easier filtering and management:

```yaml
catalog_servers:

  - id: "prod-db-server"
    name: "Production Database"
    category: "Database"
    tags:

      - "production"      # Environment
      - "postgresql"      # Technology
      - "critical"        # Priority
```

### 3. Categorize Clearly

Use standard categories that match your organization:

```yaml
categories:

  - "Software Development"
  - "Database"
  - "Productivity"
  - "Project Management"
```

### 4. Document Server Metadata

Include logo and documentation URLs for better UX:

```yaml
catalog_servers:

  - id: "time-server"
    name: "Time Server"
    description: "Provides current time utilities with geo-replication"
    documentation_url: "https://docs.example.com/time-server"
    logo_url: "https://static.example.com/logos/time-server.png"
```

---

## Examples

### Development Environment

```yaml
# mcp-catalog.dev.yml
catalog_servers:

  - id: "local-time"
    name: "Local Time Server"
    category: "Utilities"
    url: "http://localhost:9000/sse"
    auth_type: "Open"
    provider: "Local"
    description: "Local development time server"
    requires_api_key: false
    tags: ["dev", "utilities", "time"]

  - id: "local-git"
    name: "Local Git Server"
    category: "Software Development"
    url: "http://localhost:9001/sse"
    auth_type: "Open"
    provider: "Local"
    description: "Local Git MCP server"
    requires_api_key: false
    tags: ["dev", "git", "version-control"]

categories:

  - "Utilities"
  - "Software Development"

auth_types:

  - "Open"
```

### Production Environment

```yaml
# mcp-catalog.prod.yml
catalog_servers:

  - id: "prod-time-api"
    name: "Production Time API"
    category: "Utilities"
    url: "https://time.api.example.com/sse"
    auth_type: "OAuth2.1"
    provider: "Platform Engineering"
    description: "Production time API with geo-replication and high availability"
    requires_api_key: false
    secure: true
    tags: ["production", "critical", "utilities"]
    documentation_url: "https://docs.example.com/time-api"

  - id: "prod-database-api"
    name: "Production Database API"
    category: "Database"
    url: "https://db.api.example.com/sse"
    auth_type: "OAuth2.1"
    provider: "Platform Engineering"
    description: "Production PostgreSQL database API with RBAC"
    requires_api_key: false
    secure: true
    tags: ["production", "critical", "database", "postgresql"]
    documentation_url: "https://docs.example.com/db-api"

  - id: "stripe-payments"
    name: "Stripe Payments"
    category: "Payments"
    url: "https://mcp.stripe.com/"
    auth_type: "API Key"
    provider: "Stripe"
    description: "Payment processing and financial infrastructure"
    requires_api_key: true
    secure: true
    tags: ["production", "payments", "finance"]
    logo_url: "https://stripe.com/img/v3/home/social.png"
    documentation_url: "https://stripe.com/docs"

categories:

  - "Utilities"
  - "Database"
  - "Payments"

auth_types:

  - "OAuth2.1"
  - "API Key"
```

---

## Troubleshooting

### Catalog File Not Loading

**Symptoms:** Servers from catalog don't appear in the Admin UI

**Solutions:**

1. Check that catalog is enabled:
   ```bash
   echo $MCPGATEWAY_CATALOG_ENABLED  # Should be "true"
   ```

2. Verify catalog file path:
   ```bash
   ls -la mcp-catalog.yml  # Or your configured path
   ```

3. Check gateway logs for parsing errors:
   ```bash
   docker logs mcpgateway | grep -i catalog
   ```

4. Validate YAML syntax:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('mcp-catalog.yml'))"
   ```

### Servers Not Appearing in Catalog

**Symptoms:** Catalog servers don't appear in the Admin UI

**Solutions:**

1. Verify server URLs are accessible:
   ```bash
   curl -v http://localhost:9000/sse
   ```

2. Check server entry has all required fields:
   ```yaml
   catalog_servers:

     - id: "my-server"          # Required
       name: "My Server"        # Required
       category: "Utilities"    # Required
       url: "http://..."        # Required
       auth_type: "Open"        # Required
       provider: "MyProvider"   # Required
       description: "..."       # Required
   ```

3. Validate YAML syntax:
   ```bash
   python3 -c "import yaml; print(yaml.safe_load(open('mcp-catalog.yml')))"
   ```

### Authentication Errors

**Symptoms:** 401/403 errors when accessing catalog servers after registration

**Solutions:**

1. Verify the `auth_type` matches the server's requirements:
   - `"Open"` - No authentication required
   - `"API Key"` - Requires API key (set `requires_api_key: true`)
   - `"OAuth2.1"` - Requires OAuth configuration

2. For OAuth servers, ensure you complete the OAuth flow after registration via the Admin UI

3. For API Key servers, provide the API key during registration

### Transport Type Issues

**Symptoms:** WebSocket servers fail to connect after registration

**Solutions:**

1. Explicitly specify the `transport` field in your catalog YAML:
   ```yaml
   catalog_servers:

     - id: "websocket-server"
       url: "wss://api.example.com/mcp"
       transport: "WEBSOCKET"  # Explicitly set transport
   ```

2. Verify URL scheme matches transport type:
   - WebSocket: `ws://` or `wss://`
   - SSE: `http://` or `https://` with `/sse` path
   - HTTP: `http://` or `https://` with `/mcp` path

---

## Recent Improvements (v0.9.0)

### Enhanced UI Features

The catalog UI now includes several UX improvements:

- **🔄 Refresh Button**: Manually refresh the catalog without page reload
- **🔍 Debounced Search**: 300ms debounce on search input for better performance
- **📝 Custom Server Names**: Ability to specify custom names when registering servers
- **📄 Pagination with Filters**: Filter parameters preserved when navigating pages
- **⚡ Better Error Messages**: User-friendly error messages for common issues (connection, auth, SSL, etc.)
- **🔐 OAuth Support**: OAuth servers can be registered without credentials and configured later

### Transport Type Detection

The catalog now supports:

- **Explicit Transport**: Specify `transport` field in catalog YAML (`SSE`, `WEBSOCKET`, `STREAMABLEHTTP`)
- **Auto-Detection**: Automatically detects transport from URL if not specified
  - `ws://` or `wss://` → `WEBSOCKET`
  - URLs ending in `/sse` → `SSE`
  - URLs with `/mcp` path → `STREAMABLEHTTP`
  - Default fallback → `SSE`

### Authentication Improvements

- **Custom Auth Headers**: Properly mapped as list of header key-value pairs
- **OAuth Registration**: OAuth servers can be registered in "disabled" state until OAuth flow is completed
- **API Key Modal**: Enhanced modal with custom name field and proper authorization headers

---

## See Also

- [Configuration Reference](./index.md) - Complete configuration guide
- [SSO Configuration](./sso.md) - Authentication and SSO setup
- [Export/Import](./export-import.md) - Bulk operations and data migration
- [Observability](./observability.md) - Monitoring and tracing
