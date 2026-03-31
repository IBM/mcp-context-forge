# Export/Import Tutorial

Step-by-step tutorial for using ContextForge's configuration export and import capabilities.

---

## 🎯 Prerequisites

1. **Running ContextForge**: Ensure your gateway is running and accessible
2. **Authentication**: Configure either JWT token or basic auth credentials
3. **Some Configuration**: Have at least a few tools, gateways, or servers configured

### Setup Authentication

Choose one authentication method:

=== "JWT Token"
    ```bash
    # Generate a JWT token
    export MCPGATEWAY_BEARER_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
        --username admin@example.com --exp 10080 --secret my-test-key-but-now-longer-than-32-bytes)
    ```

=== "Basic Auth"
    ```bash
    # Using default credentials (change in production!)
    export BASIC_AUTH_USER=admin
    export BASIC_AUTH_PASSWORD=changeme
    ```

---

## 📤 Tutorial 1: Your First Export

Let's start by exporting your current configuration.

### Step 1: Check What You Have

```bash
# List your current tools
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/tools

# List your gateways
curl -H "Authorization: Bearer $MCPGATEWAY_BEARER_TOKEN" \
     http://localhost:4444/gateways
```

### Step 2: Export Everything

```bash
# Export complete configuration
mcpgateway export --out my-first-export.json
```

**Expected Output:**
```
Exporting configuration from gateway at http://127.0.0.1:4444
✅ Export completed successfully!
📁 Output file: my-first-export.json
📊 Exported 15 total entities:
   • tools: 8
   • gateways: 2
   • servers: 3
   • prompts: 2
```

### Step 3: Examine the Export

```bash
# View the export structure
jq 'keys' my-first-export.json

# Check entity counts
jq '.metadata.entity_counts' my-first-export.json

# View a sample tool (without showing sensitive auth data)
jq '.entities.tools[0] | {name, url, integration_type}' my-first-export.json
```

---

## 📥 Tutorial 2: Test Import with Dry Run

Before importing to another environment, let's test the import process.

### Step 1: Validate the Export

```bash
# Run dry-run import to validate
mcpgateway import my-first-export.json --dry-run
```

**Expected Output:**
```
Importing configuration from my-first-export.json
🔍 Dry-run validation completed!
📊 Results:
   • Total entities: 15
   • Processed: 15
   • Created: 0
   • Updated: 15
   • Skipped: 0
   • Failed: 0

⚠️  Warnings (15):
   • Would import tool: weather_api
   • Would import gateway: external_service
   • Would import server: ai_tools
   ...
```

### Step 2: Test Different Conflict Strategies

```bash
# Test skip strategy (won't modify existing entities)
mcpgateway import my-first-export.json --conflict-strategy skip --dry-run

# Test rename strategy (creates new entities with timestamp)
mcpgateway import my-first-export.json --conflict-strategy rename --dry-run

# Test fail strategy (stops on first conflict)
mcpgateway import my-first-export.json --conflict-strategy fail --dry-run
```

---

## 🎨 Tutorial 3: Selective Export and Import

Learn to work with specific subsets of your configuration.

### Step 1: Export Only Tools

```bash
# Export just your REST API tools
mcpgateway export --types tools --out tools-only.json --verbose
```

**Verbose Output Shows:**
```
🔍 Export details:
   • Version: 2025-03-26
   • Exported at: 2025-01-15T10:30:00Z
   • Exported by: admin
   • Source: http://127.0.0.1:4444
```

### Step 2: Tagged Export

```bash
# Export production-ready entities
mcpgateway export --tags production --out production-config.json

# Export development tools
mcpgateway export --tags development,staging --out dev-config.json
```

### Step 3: Selective Import

```bash
# Import only specific tools
mcpgateway import production-config.json --include "tools:weather_api,translate_service"

# Import tools and their dependent servers
mcpgateway import production-config.json --include "tools:weather_api;servers:*"
```

---

## 🌍 Tutorial 4: Cross-Environment Migration

Migrate configuration from staging to production with different encryption keys.

### Scenario Setup

- **Staging**: `AUTH_ENCRYPTION_SECRET=staging-secret-123`
- **Production**: `AUTH_ENCRYPTION_SECRET=prod-secret-xyz`

### Step 1: Export from Staging

```bash
# On staging environment
mcpgateway export --tags production-ready --out staging-to-prod.json
```

### Step 2: Import to Production

```bash
# On production environment
# First, validate with dry-run
mcpgateway import staging-to-prod.json \
  --rekey-secret prod-secret-xyz \
  --conflict-strategy update \
  --dry-run

# If validation passes, perform actual import
mcpgateway import staging-to-prod.json \
  --rekey-secret prod-secret-xyz \
  --conflict-strategy update
```

**Expected Output:**
```
Importing configuration from staging-to-prod.json
✅ Import completed!
📊 Results:
   • Total entities: 12
   • Processed: 12
   • Created: 5
   • Updated: 7
   • Skipped: 0
   • Failed: 0
```

---

## 🖥 Tutorial 5: Admin UI Workflow

Use the web interface for visual export/import management.

### Step 1: Access Admin UI

1. Open your browser to `http://localhost:4444/admin`
2. Login with your credentials
3. Navigate to the "Export/Import" section

### Step 2: Visual Export

1. **Select Entity Types**: Check boxes for Tools, Gateways, Servers
2. **Apply Filters**:

   - Tags: `production, api`
   - Include Inactive: ✅

3. **Export Options**:

   - Include Dependencies: ✅

4. **Download**: Click "Export Configuration"

### Step 3: Import with Preview

1. **Upload File**: Drag-and-drop your export JSON file
2. **Preview**: Review entity counts and potential conflicts
3. **Configure Options**:

   - Conflict Strategy: "Update existing items"
   - Dry Run: ✅ (for testing)

4. **Execute**: Click "Import Configuration"
5. **Monitor**: Watch real-time progress and results

---

## 🔧 Tutorial 6: Automation Scripts

Create reusable scripts for common export/import operations.

### Daily Backup Script

```bash
#!/bin/bash
# daily-backup.sh

set -e

DATE=$(date +%F)
BACKUP_DIR="/backups/mcpgateway"
BACKUP_FILE="$BACKUP_DIR/config-backup-$DATE.json"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Export configuration
echo "🔄 Starting daily backup for $DATE"
mcpgateway export --out "$BACKUP_FILE" --verbose

# Verify backup
if [[ -f "$BACKUP_FILE" ]]; then
    SIZE=$(stat -c%s "$BACKUP_FILE")
    ENTITIES=$(jq '.metadata.entity_counts | add' "$BACKUP_FILE")
    echo "✅ Backup completed: $BACKUP_FILE ($SIZE bytes, $ENTITIES entities)"
else
    echo "❌ Backup failed: file not created"
    exit 1
fi

# Optional: Upload to cloud storage
# aws s3 cp "$BACKUP_FILE" s3://backup-bucket/mcpgateway/
# gsutil cp "$BACKUP_FILE" gs://backup-bucket/mcpgateway/
```

### Environment Promotion Script

```bash
#!/bin/bash
# promote-staging-to-prod.sh

set -e

STAGING_CONFIG="staging-export.json"
PROD_SECRET="${PROD_ENCRYPTION_SECRET:-prod-secret-key}"

echo "🚀 Promoting staging configuration to production"

# Export from staging (assuming we're connected to staging)
echo "📤 Exporting staging configuration..."
mcpgateway export --tags production-ready --out "$STAGING_CONFIG"

# Validate export
ENTITY_COUNT=$(jq '.metadata.entity_counts | add' "$STAGING_CONFIG")
echo "📊 Exported $ENTITY_COUNT entities from staging"

# Dry run import to production
echo "🔍 Validating import to production..."
mcpgateway import "$STAGING_CONFIG" \
  --rekey-secret "$PROD_SECRET" \
  --conflict-strategy update \
  --dry-run

# Prompt for confirmation
read -p "Proceed with production import? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📥 Importing to production..."
    mcpgateway import "$STAGING_CONFIG" \
      --rekey-secret "$PROD_SECRET" \
      --conflict-strategy update \
      --verbose
    echo "✅ Production promotion completed!"
else
    echo "❌ Import cancelled"
    exit 1
fi
```

### Selective Tool Migration

```bash
#!/bin/bash
# migrate-tools.sh

TOOLS_TO_MIGRATE="weather_api,translate_service,sentiment_analysis"
EXPORT_FILE="tool-migration.json"

echo "🔄 Migrating tools: $TOOLS_TO_MIGRATE"

# Export current config to find tool IDs
mcpgateway export --types tools --out all-tools.json

# Create selective export
mcpgateway export --types tools --out "$EXPORT_FILE"

# Import only specified tools
mcpgateway import "$EXPORT_FILE" \
  --include "tools:$TOOLS_TO_MIGRATE" \
  --conflict-strategy update

echo "✅ Tool migration completed"
```

---

## 🎯 Next Steps

After completing these tutorials, you should be able to:

- ✅ Export your complete gateway configuration
- ✅ Import configurations with conflict resolution
- ✅ Use selective export/import for specific entities
- ✅ Migrate configurations between environments
- ✅ Set up automated backup and promotion workflows
- ✅ Use both CLI and Admin UI interfaces

### Advanced Topics

- [Observability](observability.md) - Monitor export/import operations
- [Securing](securing.md) - Advanced security practices for config management
- [Tuning](tuning.md) - Performance optimization for large configurations

### Troubleshooting

If you encounter issues:

1. **Check the logs**: Gateway logs show detailed export/import operations
2. **Validate data**: Use `jq` to verify export file structure
3. **Test incrementally**: Start with small subsets before full imports
4. **Use dry-run**: Always validate imports before applying changes
5. **Check authentication**: Verify tokens and encryption keys are correct

For detailed troubleshooting, see the main [Export & Import Guide](export-import.md).
