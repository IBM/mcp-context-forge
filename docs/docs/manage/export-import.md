# Configuration Export & Import

ContextForge provides comprehensive configuration export and import capabilities for backup, disaster recovery, environment promotion, and configuration management workflows.

---

## 🎯 Overview

The export/import system enables complete backup and restoration of your ContextForge configuration including:

- **Tools** (locally created REST API tools)
- **Gateways** (peer gateway connections)
- **Virtual Servers** (server compositions with tool associations)
- **Prompts** (template definitions with schemas)
- **Resources** (locally defined resources)
- **Roots** (filesystem and HTTP root paths)

> **Note**: Exports describe gateway configuration and resource metadata; they do not back up upstream resource content.

### Federated Resource Names

Federated resource names use the gateway slug, `GATEWAY_TOOL_NAME_SEPARATOR` (default `-`), and the resource base
slug. Local resource names and resource URIs are unchanged. Names are limited to 255 characters and are not unique:
long prefixes can consume the resource portion, and gateway slugs can collide. A virtual-server-scoped read resolves
a shared URI only when that server has one matching resource; prefixing names does not change URI routing.

Upgrading applies these prefixes to existing federated resource names. Integrations or saved searches that match
names may need updating; resource IDs and URIs do not change. Previously exported files are not rewritten.

Resource read responses include `original_name` and `custom_name_slug` for local resources too. For a local resource,
`original_name` records its initial naming history, not an upstream identity. Its visible name remains literal.
Updates can supply `custom_name` to explicitly rename the base (or the literal local name). A non-null `custom_name`
takes precedence over `name`; omitted or null values retain legacy `name` handling. Admin submits an explicit base
only when it changes. Bulk import updates treat the imported name as operator intent and preserve upstream identity.

Exports preserve local names verbatim. Federated exports select the effective base, then the upstream name, then the
derived name, using the first candidate that validates after applying the configured length limit (at most 255).
If none validates, the derived name is exported unchanged with a warning. Full `original_name` and `custom_name_slug`
values accompany federated exports as provenance; import consumes only `name` and does not restore that provenance.
Empty, oversized, or configuration-invalid bases can therefore change on import. Import also applies the destination's
validation settings. Lowering a validation limit does not truncate local names during export.

Changing the separator does not rewrite stored resource bases. They retain their separator until a manual rename or
an applicable upstream-name change replaces them, so derived names can contain mixed separators after a configuration
change. Separator-only differences do not count as manual overrides. Downgrading the resource-namespacing migration
restores upstream names for federated resources and discards manual base overrides.

---

## 🔐 Security Features

- **Credential handling**: Exports omit recognized credentials. Imports ignore those values in older files. Unrecognized header names and query keys keep their values.
- **Cross-Environment Support**: Move configuration and set credentials on the destination
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

# Cross-environment import
mcpgateway import prod-export.json

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
| `--dry-run` | Preview local outcomes without writes or upstream connections | - | `false` |
| `--team-name` | Destination team name | String | Personal team |
| `--include` | Selective import filter | `type:name1,name2;type2:name3` | - |
| `--verbose, -v` | Verbose output | - | `false` |

Without `--team-name`, new entities go into your personal team. With `--team-name`, the import targets that team. Imported entities keep explicit visibility from the file where the operation permits it. When you supply a selection, the import processes only the entity types in that selection. A selected gateway can still discover its own upstream tools, resources, and prompts.

A file containing roots requires an unrestricted platform administrator, even when the selection omits roots.

If you have no personal team, specify `team_name` in the API or Admin UI, or `--team-name` in the CLI, to create team-visible entities. Updates keep the destination entity's team.

This release removes `--rekey-secret` and `rekey_secret`. The CLI rejects the flag. After authorization, the API and Admin import endpoints return HTTP 400 if the field is present, including when its value is `null`. Use `python -m mcpgateway.scripts.migrate_enc_secret` for [encryption secret rotation](../operations/auth-encryption-secret-rotation.md).

Live import uses one transaction so a fatal error can roll back all registry changes. On PostgreSQL, row locks from successful items can remain held during upstream gateway discovery until the import commits.

An export can omit server tool bindings that are outside its visibility or activity filters. Import reports those omissions and preserves the destination server's existing bindings. Import also preserves existing bindings if any reference in the file cannot resolve.

### REST API Import

```bash
# Basic import (wrap export data in import_data field)
jq -n --slurpfile data export.json '{"import_data": $data[0]}' | \
  curl -X POST -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d @- "http://localhost:4444/import"

# Import with options
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "import_data": {...},
       "conflict_strategy": "update",
       "dry_run": false,
       "team_name": "Operations"
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
- **Behavior**: Rename conflicting entities with the first available numbered suffix
- **Use Case**: Preserving both old and new configurations
- **Result**: Creates a name such as `entity_name_imported_1`

### Fail Strategy
```bash
mcpgateway import backup.json --conflict-strategy fail
```
- **Behavior**: Fail import on any naming conflict
- **Use Case**: Strict imports where conflicts indicate errors
- **Result**: Import stops on the first conflict, rolls back all changes, and returns HTTP 409

---

## 🌍 Cross-Environment Migration

### Move Configuration

Export configuration from the source and import it into the destination. Configure credentials on the destination after import.

```bash
# Export from source environment
mcpgateway export --out staging-config.json

# Import into the target environment
mcpgateway import staging-config.json
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
  "contextforge_version": "1.1.1",
  "exported_at": "2025-01-15T10:30:00Z",
  "exported_by": "admin",
  "source_gateway": "https://gateway.example.com:4444",
  "encryption_method": "AES-256-GCM",
  "entities": {
    "tools": [
      {
        "id": "<dummy-alpha-numeric-value>",
        "visibility": "team",
        "name": "weather_api",
        "url": "https://api.weather.com/v1/current",
        "integration_type": "REST",
        "request_type": "GET",
        "credentials_required": true,
        "tags": ["weather", "api"]
      }
    ],
    "gateways": [
      {
        "id": "<dummy-alpha-numeric-value>",
        "visibility": "team",
        "name": "production-east",
        "url": "https://prod-east.gateway.com:4444",
        "credentials_required": true,
        "transport": "SSE"
      }
    ],
    "servers": [
      {
        "id": "<dummy-alpha-numeric-value>",
        "visibility": "team",
        "name": "ai-tools-server",
        "description": "AI tools virtual server",
        "instructions": null,
        "tool_ids": ["<dummy-alpha-numeric-value>"],
        "tool_refs": [{"id": "<dummy-alpha-numeric-value>", "original_name": "weather_api"}],
        "tool_refs_complete": true
      }
    ]
  },
  "metadata": {
    "entity_counts": {"tools": 1, "gateways": 1, "servers": 1},
    "dependencies": {
      "servers_to_tools": {
        "ai-tools-server": ["<dummy-alpha-numeric-value>"]
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

If a federated item needs discovery on a new gateway, preview and dry run report that item as unknown. The item counts toward progress and any dependent tool binding stays unresolved until discovery finds an eligible tool.

**Output:**
```
🔍 Dry-run validation completed!
📊 Results:
   • Total entities: 15
   • Processed: 15
   • Created: 11
   • Updated: 3
   • Skipped: 0
   • Failed: 0
   • Unknown: 1

⚠️  Warnings (1):
   • tools item weather_api: match depends on upstream discovery
```

### Schema Validation

Import data is validated for:

- **Required Fields**: Each entity type has mandatory fields
- **Data Types**: Field types match expected schemas
- **Dependencies**: Referenced entities exist or will be created
- **Security**: Auth data is properly encrypted

---

## 📊 Import Progress Tracking

Import status is local to the worker that processed the request. API responses include outcome counts, unresolved reference warnings, and a `credentials_required` list. Status lookup, listing, and cleanup use the caller's current scope. A lookup outside that scope returns HTTP 404.

### Real-time Status

Monitor import progress via API:

```bash
# Start import and get import ID
IMPORT_ID=$(jq -n --slurpfile data backup.json '{"import_data": $data[0]}' | \
  curl -X POST -H "Authorization: Bearer $TOKEN" \
       -H "Content-Type: application/json" \
       -d @- "http://localhost:4444/import" | jq -r .import_id)

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
  "credentials_required": [{"type": "gateways", "identifier": "production-east"}],
  "errors": [],
  "warnings": []
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

# Import to production
mcpgateway import prod-config.json \
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

#### Import reports credentials required

Configure credentials on the destination for the entities listed in the API response's `credentials_required` field. A gateway that needs credentials remains pending and unreachable until you configure them. Imports keep destination credentials for same-origin updates. A change to a different URL origin clears the old credentials.

Import skips federated items that a credential-blocked gateway has yet to discover. Existing server bindings stay in place if a tool reference remains unresolved. Configure the gateway credentials, then repeat the import to resolve its items.

Use `python -m mcpgateway.scripts.migrate_enc_secret` to [rotate the encryption secret](../operations/auth-encryption-secret-rotation.md).

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
| 403 | Forbidden | Check import permissions, destination team scope, and root authority |
| 404 | Import status unavailable | Check the ID and current import status scope |
| 409 | Conflict; import rolled back | Choose a different conflict strategy |
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
| `GET` | `/import/status` | List import operations within the caller's scope |
| `POST` | `/import/cleanup` | Clean up eligible terminal statuses within the caller's scope |

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
  "team_name": "Operations",
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

# Encryption for auth data
AUTH_ENCRYPTION_SECRET=your-encryption-key

# Gateway connection
HOST=localhost
PORT=4444
```

!!! info "Authentication Methods"
    **JWT tokens are the recommended authentication method.** Basic authentication for API endpoints is disabled by default for security. If you need Basic auth for CLI tools, set `API_ALLOW_BASIC_AUTH=true` in your environment.

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
mcpgateway import staging-to-prod.json --dry-run
mcpgateway import staging-to-prod.json
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
mcpgateway import dev-to-staging.json

# Export from staging (filtered for production)
mcpgateway export --tags production-ready --out staging-to-prod.json

# Import to production
mcpgateway import staging-to-prod.json
```

---

## 🔗 Related Documentation

- [Backup & Restore](backup.md) - Database-level backup strategies
- [Bulk Import](bulk-import.md) - Bulk tool import from external sources
- [Securing](securing.md) - Security best practices and encryption
- [Observability](observability.md) - Monitoring export/import operations
