# Configuration Export & Import

MCP Gateway provides comprehensive configuration export and import capabilities for backup, disaster recovery, environment promotion, and configuration management workflows.

---

## 🎯 Overview

The export/import system enables complete backup and restoration of your MCP Gateway configuration including:

- **Tools** (locally created REST API tools)
- **Gateways** (peer gateway connections)
- **Virtual Servers** (server compositions with tool associations)
- **Prompts** (template definitions with schemas)
- **Resources** (locally defined resources)
- **Roots** (filesystem and HTTP root paths)

> **Note**: Only locally configured entities are exported. Dynamic content from federated MCP servers is excluded to ensure exports contain only your gateway's configuration.

---

## 🔐 Security Features

- **Encrypted Authentication**: All sensitive auth data (passwords, tokens, API keys) is encrypted using AES-256-GCM
- **Cross-Environment Support**: Key rotation capabilities for moving configs between environments
- **Validation**: Complete JSON schema validation for import data integrity
- **Conflict Resolution**: Multiple strategies for handling naming conflicts during import

---

## 📱 Export Methods

### CLI Export

```bash
# Complete system backup
mcpgateway export --out backup-$(date +%F).json

# Export only production tools
mcpgateway export --types tools --tags production --out prod-tools.json

# Export specific entity types
mcpgateway export --types tools,gateways --out core-config.json

# Export with inactive entities included
mcpgateway export --include-inactive --out complete-backup.json

# Export excluding certain types
mcpgateway export --exclude-types servers,resources --out minimal-config.json
```

#### CLI Export Options

| Option | Description | Example |
|--------|-------------|---------|
| `--out, -o` | Output file path | `--out backup.json` |
| `--types` | Entity types to include | `--types tools,gateways` |
| `--exclude-types` | Entity types to exclude | `--exclude-types servers` |
| `--tags` | Filter by tags | `--tags production,api` |
| `--include-inactive` | Include inactive entities | `--include-inactive` |
| `--no-dependencies` | Don't include dependent entities | `--no-dependencies` |
| `--verbose, -v` | Verbose output | `--verbose` |

### REST API Export

```bash
# Basic export
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:4444/export" > export.json

# Export with filters
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:4444/export?types=tools,servers&tags=production" \
     > filtered-export.json

# Selective export (POST with entity selections)
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tools": ["tool1", "tool2"], "servers": ["server1"]}' \
     "http://localhost:4444/export/selective" > selective-export.json
```

### Admin UI Export

1. Navigate to `/admin` in your browser
2. Go to the "Export/Import" section
3. Select entity types and filters
4. Click "Export Configuration"
5. Download the generated JSON file

---

## 📥 Import Methods

### CLI Import

```bash
# Basic import with conflict resolution
mcpgateway import backup.json --conflict-strategy update

# Dry run to preview changes
mcpgateway import backup.json --dry-run

# Cross-environment import with key rotation
mcpgateway import prod-export.json --rekey-secret $NEW_ENV_SECRET

# Selective import of specific entities
mcpgateway import backup.json --include "tools:weather_api,translate;servers:ai-server"

# Import with different conflict strategies
mcpgateway import backup.json --conflict-strategy skip    # Skip conflicts
mcpgateway import backup.json --conflict-strategy rename  # Rename conflicting items
mcpgateway import backup.json --conflict-strategy fail    # Fail on conflicts
```

#### CLI Import Options

| Option | Description | Values | Default |
|--------|-------------|--------|---------|
| `--conflict-strategy` | How to handle conflicts | `skip`, `update`, `rename`, `fail` | `update` |
| `--dry-run` | Validate without changes | - | `false` |
| `--rekey-secret` | New encryption secret | String | - |
| `--include` | Selective import filter | `type:name1,name2;type2:name3` | - |
| `--verbose, -v` | Verbose output | - | `false` |

### REST API Import

```bash
# Basic import
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d @export.json \
     "http://localhost:4444/import"

# Import with options
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "import_data": {...},
       "conflict_strategy": "update",
       "dry_run": false,
       "rekey_secret": "new-secret"
     }' \
     "http://localhost:4444/import"

# Check import status
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:4444/import/status/IMPORT_ID"
```

### Admin UI Import

1. Navigate to `/admin` in your browser
2. Go to the "Export/Import" section
3. Upload or paste import data
4. Configure conflict resolution strategy
5. Choose entities to import (optional)
6. Run import and monitor progress

---

## ⚡ Conflict Resolution Strategies

When importing entities that already exist, you can choose how to handle conflicts:

### Skip Strategy
```bash
mcpgateway import backup.json --conflict-strategy skip
```
- **Behavior**: Skip entities that already exist
- **Use Case**: Adding new configs without modifying existing ones
- **Result**: Existing entities remain unmodified

### Update Strategy (Default)
```bash
mcpgateway import backup.json --conflict-strategy update
```
- **Behavior**: Update existing entities with imported data
- **Use Case**: Environment promotion, configuration updates
- **Result**: Existing entities are overwritten with import data

### Rename Strategy
```bash
mcpgateway import backup.json --conflict-strategy rename
```
- **Behavior**: Rename conflicting entities with timestamp suffix
- **Use Case**: Preserving both old and new configurations
- **Result**: Creates `entity_name_imported_1640995200`

### Fail Strategy
```bash
mcpgateway import backup.json --conflict-strategy fail
```
- **Behavior**: Fail import on any naming conflict
- **Use Case**: Strict imports where conflicts indicate errors
- **Result**: Import stops on first conflict

---

## 🌍 Cross-Environment Migration

### Key Rotation

When moving configurations between environments with different encryption keys:

```bash
# Export from source environment
mcpgateway export --out staging-config.json

# Import to target environment with new key
mcpgateway import staging-config.json --rekey-secret $PROD_ENCRYPTION_SECRET
```

### Environment Variables

Ensure these are configured in the target environment:

```bash
# Authentication
AUTH_ENCRYPTION_SECRET=your-prod-secret
JWT_SECRET_KEY=your-prod-jwt-secret

# Database
DATABASE_URL=postgresql+psycopg://user:pass@prod-db:5432/mcpgateway

# Gateway settings
HOST=prod.mcpgateway.com
PORT=443
```

---

## 📋 Export Format

Exports follow a standardized JSON schema:

```json
{
  "version": "2025-03-26",
  "exported_at": "2025-01-15T10:30:00Z",
  "exported_by": "admin",
  "source_gateway": "https://gateway.example.com:4444",
  "encryption_method": "AES-256-GCM",
  "entities": {
    "tools": [
      {
        "name": "weather_api",
        "url": "https://api.weather.com/v1/current",
        "integration_type": "REST",
        "request_type": "GET",
        "auth_type": "bearer",
        "auth_value": "encrypted_token_here",
        "tags": ["weather", "api"]
      }
    ],
    "gateways": [
      {
        "name": "production-east",
        "url": "https://prod-east.gateway.com:4444",
        "auth_type": "basic",
        "auth_value": "encrypted_credentials_here",
        "transport": "SSE"
      }
    ],
    "servers": [
      {
        "name": "ai-tools-server",
        "description": "AI tools virtual server",
        "tool_ids": ["weather_api", "translate_text"],
        "capabilities": {"tools": {"list_changed": true}}
      }
    ]
  },
  "metadata": {
    "entity_counts": {"tools": 1, "gateways": 1, "servers": 1},
    "dependencies": {
      "servers_to_tools": {
        "ai-tools-server": ["weather_api", "translate_text"]
      }
    }
  }
}
```

---

## 🔍 Import Validation

### Dry Run

Always validate imports before applying changes:

```bash
mcpgateway import backup.json --dry-run
```

**Output:**
```
🔍 Dry-run validation completed!
📊 Results:
   • Total entities: 15
   • Processed: 15
   • Would create: 12
   • Would update: 3
   • Conflicts: 0

⚠️  Warnings (2):
   • Would import tool: weather_api
   • Would import gateway: prod-east
```

### Schema Validation

Import data is validated for:

- **Required Fields**: Each entity type has mandatory fields
- **Data Types**: Field types match expected schemas
- **Dependencies**: Referenced entities exist or will be created
- **Security**: Auth data is properly encrypted

---

## 📊 Import Progress Tracking

### Real-time Status

Monitor import progress via API:

```bash
# Start import and get import ID
IMPORT_ID=$(curl -X POST -H "Authorization: Bearer $TOKEN" \
  -d @backup.json "http://localhost:4444/import" | jq -r .import_id)

# Check progress
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:4444/import/status/$IMPORT_ID"
```

**Response:**
```json
{
  "import_id": "abc-123-def",
  "status": "running",
  "progress": {
    "total": 50,
    "processed": 35,
    "created": 20,
    "updated": 10,
    "skipped": 5,
    "failed": 0
  },
  "errors": [],
  "warnings": ["Renamed tool 'duplicate_name' to 'duplicate_name_imported_1640995200'"]
}
```

---

## 🎛 Admin UI Features

### Export Interface

- **Entity Selection**: Checkboxes to select specific tools, gateways, servers
- **Filter Options**: Tag-based filtering and active/inactive inclusion
- **Dependency Resolution**: Automatic inclusion of dependent entities
- **Download Progress**: Real-time progress indication for large exports

### Import Wizard

- **File Upload**: Drag-and-drop import file support
- **Conflict Preview**: Shows potential naming conflicts before import
- **Resolution Options**: Visual selection of conflict resolution strategy
- **Progress Tracking**: Real-time import status with error/warning display

---

## 🚀 Automation & CI/CD

### GitHub Actions

```yaml
name: Config Backup
on:
  schedule:

    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:

      - name: Export Configuration
        run: |
          mcpgateway export --out backup-$(date +%F).json

      - name: Upload to S3
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
        run: |
          aws s3 cp backup-$(date +%F).json s3://backup-bucket/mcpgateway/
```

### Environment Promotion

```bash
#!/bin/bash
# promote-to-prod.sh

# Export from staging
mcpgateway export --types tools,servers --tags production --out prod-config.json

# Import to production with new encryption key
mcpgateway import prod-config.json \
  --rekey-secret $PROD_ENCRYPTION_SECRET \
  --conflict-strategy update \
  --verbose
```

---

## 🛡 Best Practices

### Security

1. **Encryption Keys**: Use different `AUTH_ENCRYPTION_SECRET` per environment
2. **Access Control**: Limit export/import permissions to administrators only
3. **Audit Logging**: Monitor all export/import operations
4. **Secure Storage**: Store export files in encrypted storage (S3-SSE, Azure Storage encryption)

### Operational

1. **Regular Backups**: Schedule daily exports via cron or CI/CD
2. **Version Control**: Store export files in Git for configuration versioning
3. **Testing**: Always use `--dry-run` before production imports
4. **Monitoring**: Set up alerts for failed import operations

### Performance

1. **Selective Exports**: Use filters to reduce export size
2. **Incremental Imports**: Import only changed entities when possible
3. **Batch Processing**: The import service processes entities in optimal dependency order
4. **Progress Tracking**: Use status APIs for long-running imports

---

## 🚨 Troubleshooting

### Common Issues

#### Export Fails with "No entities found"
```bash
# Check if entities exist
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/tools
curl -H "Authorization: Bearer $TOKEN" http://localhost:4444/gateways

# Check entity status (may be inactive)
mcpgateway export --include-inactive --types tools
```

#### Import Fails with "Invalid authentication data"
```bash
# Try re-keying with current environment's secret
mcpgateway import backup.json --rekey-secret $AUTH_ENCRYPTION_SECRET

# Or check the source environment's encryption key
echo "Source AUTH_ENCRYPTION_SECRET may differ from target environment"
```

#### Import Conflicts Not Resolving
```bash
# Use verbose mode to see detailed conflict resolution
mcpgateway import backup.json --conflict-strategy update --verbose

# Or use dry-run to preview conflicts
mcpgateway import backup.json --dry-run
```

#### Large Import Times Out
```bash
# Use selective import for large configurations
mcpgateway import large-backup.json --include "tools:tool1,tool2;servers:server1"

# Or import in batches by entity type
mcpgateway import backup.json --types tools
mcpgateway import backup.json --types gateways
mcpgateway import backup.json --types servers
```

### Error Codes

| HTTP Code | Meaning | Resolution |
|-----------|---------|------------|
| 400 | Bad Request - Invalid data | Check export file format and required fields |
| 401 | Unauthorized | Verify `MCPGATEWAY_BEARER_TOKEN` or basic auth credentials |
| 409 | Conflict | Naming conflicts detected - choose resolution strategy |
| 422 | Validation Error | Export data doesn't match expected schema |
| 500 | Internal Error | Check server logs for detailed error information |

---

## 📚 API Reference

### Export Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/export` | Full configuration export with filters |
| `POST` | `/export/selective` | Export specific entities by ID/name |

### Import Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/import` | Import configuration with conflict resolution |
| `GET` | `/import/status/{id}` | Get import operation status |
| `GET` | `/import/status` | List all import operations |
| `POST` | `/import/cleanup` | Clean up completed import statuses |

### Query Parameters

**Export (`GET /export`)**:

- `types` - Comma-separated entity types
- `exclude_types` - Entity types to exclude
- `tags` - Tag-based filtering
- `include_inactive` - Include inactive entities
- `include_dependencies` - Include dependent entities

**Import (`POST /import`)**:
```json
{
  "import_data": { /* export data */ },
  "conflict_strategy": "update",
  "dry_run": false,
  "rekey_secret": "optional-new-secret",
  "selected_entities": {
    "tools": ["tool1", "tool2"],
    "servers": ["server1"]
  }
}
```

---

## 🎛 Environment Variables

Configure export/import behavior:

```bash
# Authentication (required for API access)
MCPGATEWAY_BEARER_TOKEN=your-jwt-token
# OR
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=your-password

# Encryption for auth data
AUTH_ENCRYPTION_SECRET=your-encryption-key

# Gateway connection
HOST=localhost
PORT=4444
```

---

## 📈 Use Cases

### Disaster Recovery
```bash
# 1. Regular automated backups
0 2 * * * /usr/local/bin/mcpgateway export --out /backups/daily-$(date +\%F).json

# 2. Restore from backup
mcpgateway import /backups/daily-2025-01-15.json --conflict-strategy update
```

### Environment Promotion
```bash
# 1. Export production-ready configs from staging
mcpgateway export --tags production --out staging-to-prod.json

# 2. Import to production
mcpgateway import staging-to-prod.json --rekey-secret $PROD_SECRET --dry-run
mcpgateway import staging-to-prod.json --rekey-secret $PROD_SECRET
```

### Configuration Versioning
```bash
# 1. Export current state
mcpgateway export --out config-v1.2.3.json

# 2. Commit to version control
git add config-v1.2.3.json
git commit -m "Configuration snapshot v1.2.3"

# 3. Restore specific version later
mcpgateway import config-v1.2.3.json --conflict-strategy update
```

### Multi-Environment Setup
```bash
# Development → Staging → Production pipeline

# Export from dev (filtered for staging)
mcpgateway export --tags staging-ready --out dev-to-staging.json

# Import to staging
mcpgateway import dev-to-staging.json --rekey-secret $STAGING_SECRET

# Export from staging (filtered for production)
mcpgateway export --tags production-ready --out staging-to-prod.json

# Import to production
mcpgateway import staging-to-prod.json --rekey-secret $PROD_SECRET
```

---

## 🔗 Related Documentation

- [Backup & Restore](backup.md) - Database-level backup strategies
- [Bulk Import](bulk-import.md) - Bulk tool import from external sources
- [Securing](securing.md) - Security best practices and encryption
- [Observability](observability.md) - Monitoring export/import operations
