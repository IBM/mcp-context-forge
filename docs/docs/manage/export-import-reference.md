# Export/Import Quick Reference

Quick reference for ContextForge configuration export and import commands.

---

## 🚀 CLI Commands

### Export Commands

```bash
# Complete backup
mcpgateway export --out backup.json

# Production tools only
mcpgateway export --types tools --tags production --out prod-tools.json

# Everything except metrics
mcpgateway export --exclude-types metrics --out config.json

# Include inactive entities
mcpgateway export --include-inactive --out complete.json

# Minimal export (no dependencies)
mcpgateway export --no-dependencies --out minimal.json
```

### Import Commands

```bash
# Standard import
mcpgateway import backup.json

# Dry-run validation
mcpgateway import backup.json --dry-run

# Import into a named team
mcpgateway import backup.json --team-name "Operations"

# Skip conflicts
mcpgateway import backup.json --conflict-strategy skip

# Cross-environment import
mcpgateway import backup.json

# Selective import
mcpgateway import backup.json --include "tools:api_tool;servers:ai_server"
```

---

## 🌐 API Endpoints

### Export APIs

```bash
# GET /export - Full export with filters
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/export?types=tools,gateways&include_inactive=true"

# POST /export/selective - Export specific entities
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -d '{"tools": ["tool1"], "servers": ["server1"]}' \
  "http://localhost:4444/export/selective"
```

### Import APIs

```bash
# POST /import - Import configuration
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -d '{"import_data": {...}, "conflict_strategy": "update"}' \
  "http://localhost:4444/import"

# GET /import/status/{id} - Check import progress
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/import/status/import-123"

# GET /import/status - List all imports
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/import/status"
```

---

## ⚙️ Configuration

### Required Environment Variables

```bash
# Authentication (choose one)
MCPGATEWAY_BEARER_TOKEN=your-jwt-token
# OR
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=your-password

# Encryption key for auth data
AUTH_ENCRYPTION_SECRET=your-32-char-secret

# Gateway connection
HOST=localhost
PORT=4444
```

### Optional Settings

```bash
# Enable Admin UI for web-based export/import
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true

# Import limits and timeouts
MCPGATEWAY_BULK_IMPORT_MAX_TOOLS=200
MCPGATEWAY_BULK_IMPORT_RATE_LIMIT=10
```

---

## 🎭 Conflict Resolution

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| `skip` | Skip existing entities | Additive imports |
| `update` | Overwrite existing entities | Environment promotion |
| `rename` | Add a numbered suffix such as `_imported_1` | Preserve both versions |
| `fail` | Roll back the import on conflict and return HTTP 409 | Strict validation |

---

## 📊 Entity Types

| Type | Identifier | Description |
|------|------------|-------------|
| `tools` | `name` | REST API tools and MCP integrations |
| `gateways` | `name` | Peer gateway connections |
| `servers` | `name` | Virtual server compositions |
| `prompts` | `name` | Template definitions with schemas |
| `resources` | `uri` | Static and dynamic resources |
| `roots` | `uri` | Filesystem and HTTP root paths |

---

## 🔍 Filtering Examples

### By Entity Type
```bash
# Tools and gateways only
mcpgateway export --types tools,gateways

# Everything except servers
mcpgateway export --exclude-types servers,metrics
```

### By Tags
```bash
# Production-tagged entities
mcpgateway export --tags production

# Multiple tags (OR condition)
mcpgateway export --tags api,data,production
```

### By Status
```bash
# Active entities only (default)
mcpgateway export

# Include inactive entities
mcpgateway export --include-inactive
```

### Selective Import
```bash
# Specific tools and servers
mcpgateway import backup.json --include "tools:weather_api,translate;servers:ai_server"

# Single entity type
mcpgateway import backup.json --include "tools:*"
```

---

## 🔧 Troubleshooting Quick Fixes

### "Authentication Error"
```bash
export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes)
```

### "Gateway Connection Failed"
```bash
# Check gateway is running
curl http://localhost:4444/health

# Verify port and host
netstat -tlnp | grep 4444
```

### "Invalid Export Format"
```bash
# Validate JSON structure
jq empty export.json

# Check required fields
jq 'has("version") and has("entities")' export.json
```

### Import reports credentials required

Configure credentials on the destination for each entity listed in the API response's `credentials_required` field. To rotate an instance's encryption secret, follow the [rotation guide](../operations/auth-encryption-secret-rotation.md).

---

## 📋 Common Workflows

### Daily Backup
```bash
#!/bin/bash
DATE=$(date +%F)
mcpgateway export --out "backup-$DATE.json"
echo "✅ Backup created: backup-$DATE.json"
```

### Environment Sync
```bash
#!/bin/bash
# Sync staging to production
mcpgateway export --tags production --out staging-config.json
mcpgateway import staging-config.json --dry-run
mcpgateway import staging-config.json
```

### Selective Migration
```bash
#!/bin/bash
# Migrate specific tools between environments
mcpgateway export --types tools --tags migrate --out tools-migration.json
mcpgateway import tools-migration.json --include "tools:*" --conflict-strategy update
```
