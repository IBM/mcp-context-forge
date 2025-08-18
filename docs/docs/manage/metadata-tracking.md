# 📊 Metadata Tracking & Audit Trails

MCP Gateway provides comprehensive metadata tracking for all entities (Tools, Resources, Prompts, Servers, Gateways) to enable enterprise-grade audit trails, compliance monitoring, and operational troubleshooting.

---

## 🎯 **Overview**

Every entity in MCP Gateway now includes detailed metadata about:
- **Who** created or modified the entity
- **When** the operation occurred
- **From where** (IP address, user agent)
- **How** it was created (UI, API, bulk import, federation)
- **Source tracking** for federated entities and bulk operations

---

## 📊 **Metadata Fields**

All entities include the following metadata fields:

| Category | Field | Description | Example Values |
|----------|-------|-------------|----------------|
| **Creation** | `created_by` | Username who created entity | `"admin"`, `"alice"`, `"anonymous"` |
| | `created_at` | Creation timestamp | `"2024-01-15T10:30:00Z"` |
| | `created_from_ip` | IP address of creator | `"192.168.1.100"`, `"10.0.0.1"` |
| | `created_via` | Creation method | `"ui"`, `"api"`, `"import"`, `"federation"` |
| | `created_user_agent` | Browser/client info | `"Mozilla/5.0"`, `"curl/7.68.0"` |
| **Modification** | `modified_by` | Last modifier username | `"bob"`, `"system"`, `"anonymous"` |
| | `modified_at` | Last modification timestamp | `"2024-01-16T14:22:00Z"` |
| | `modified_from_ip` | IP of last modifier | `"172.16.0.1"` |
| | `modified_via` | Modification method | `"ui"`, `"api"` |
| | `modified_user_agent` | Client of last change | `"HTTPie/2.4.0"` |
| **Source** | `import_batch_id` | Bulk import UUID | `"550e8400-e29b-41d4-a716-446655440000"` |
| | `federation_source` | Source gateway name | `"gateway-prod-east"` |
| | `version` | Change tracking version | `1`, `2`, `3`... |

---

## 🖥️ **Viewing Metadata**

### **Admin UI**

Metadata is displayed in the detail view modals for all entity types:

1. **Navigate** to any entity list (Tools, Resources, Prompts, Servers, Gateways)
2. **Click "View"** on any entity
3. **Scroll down** to the "Metadata" section

**Example metadata display:**
```
┌─ Metadata ──────────────────────────────────────┐
│ Created By:      admin                           │
│ Created At:      1/15/2024, 10:30:00 AM        │
│ Created From:    192.168.1.100                  │
│ Created Via:     ui                              │
│ Last Modified By: alice                          │
│ Last Modified At: 1/16/2024, 2:22:00 PM        │
│ Version:         3                               │
│ Import Batch:    N/A                             │
└─────────────────────────────────────────────────┘
```

### **API Responses**

All entity read endpoints include metadata fields in JSON responses:

```bash
# Get tool with metadata
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:4444/tools/abc123

{
  "id": "abc123",
  "name": "example_tool",
  "description": "Example tool",
  "createdBy": "admin",
  "createdAt": "2024-01-15T10:30:00Z",
  "createdFromIp": "192.168.1.100",
  "createdVia": "ui",
  "createdUserAgent": "Mozilla/5.0...",
  "modifiedBy": "alice",
  "modifiedAt": "2024-01-16T14:22:00Z",
  "version": 3,
  "importBatchId": null,
  "federationSource": null,
  ...
}
```

---

## 🔍 **Metadata by Source Type**

### **Manual Creation (UI/API)**
- `created_via`: `"ui"` or `"api"`
- `created_by`: Authenticated username
- `created_from_ip`: Client IP address
- `federation_source`: `null`
- `import_batch_id`: `null`

### **Bulk Import Operations**
- `created_via`: `"import"`
- `import_batch_id`: UUID linking related imports
- `created_by`: User who initiated import
- `federation_source`: `null`

### **Federation (MCP Server Discovery)**
- `created_via`: `"federation"`
- `federation_source`: Source gateway name
- `created_by`: User who registered the gateway
- `import_batch_id`: `null`

### **Legacy Entities (Pre-Metadata)**
- All metadata fields: `null`
- UI displays: `"Legacy Entity"`, `"Pre-metadata"`
- `version`: `1` (automatically assigned)

---

## 🛡️ **Authentication Compatibility**

Metadata tracking works seamlessly across all authentication modes:

### **With Authentication (`AUTH_REQUIRED=true`)**
```bash
# Example: User "admin" creates a tool
{
  "createdBy": "admin",
  "createdVia": "api",
  "createdFromIp": "192.168.1.100"
}
```

### **Without Authentication (`AUTH_REQUIRED=false`)**
```bash
# Example: Anonymous creation
{
  "createdBy": "anonymous",
  "createdVia": "api",
  "createdFromIp": "192.168.1.100"
}
```

### **JWT vs Basic Authentication**
- **JWT Authentication**: Extracts username from token payload (`username` or `sub` field)
- **Basic Authentication**: Uses provided username directly
- **Both formats handled gracefully** by the `extract_username()` utility

---

## 🔄 **Version Tracking**

Each entity maintains a version number that increments on modifications:

```bash
# Initial creation
POST /tools -> version: 1

# First update
PUT /tools/123 -> version: 2

# Second update
PUT /tools/123 -> version: 3
```

Version tracking helps identify:
- **Configuration drift** between environments
- **Change frequency** for troubleshooting
- **Rollback points** for recovery scenarios

---

## 📈 **Use Cases**

### **Security Auditing**
- Track who created/modified sensitive configurations
- Identify unauthorized changes by IP address
- Monitor bulk import operations for compliance

### **Operational Troubleshooting**
- Trace entity origins during incident response
- Identify batch operations that may have caused issues
- Understand federation dependencies between gateways

### **Compliance Reporting**
- Generate audit reports for regulatory requirements
- Track change management processes
- Demonstrate access controls and change attribution

### **Development & Testing**
- Identify test vs production entities
- Track deployment-specific configurations
- Monitor cross-environment migrations

---

## 🔧 **Configuration**

### **No Additional Setup Required**

Metadata tracking is **automatically enabled** for all new installations and upgrades:

- **Database migration** runs automatically on startup
- **Existing entities** show graceful fallbacks for missing metadata
- **No environment variables** needed - uses existing `AUTH_REQUIRED` setting

### **Proxy Support**

Metadata capture automatically handles reverse proxy scenarios:

```bash
# Respects X-Forwarded-For headers
X-Forwarded-For: 203.0.113.1, 192.168.1.1, 127.0.0.1
# Records: created_from_ip = "203.0.113.1" (original client)
```

### **Privacy Considerations**

The system captures IP addresses and user agents for audit purposes:

- **IP addresses**: Consider GDPR/privacy implications for EU deployments
- **User agents**: May contain personally identifiable information
- **Data retention**: Define policies for metadata archival
- **Access control**: Metadata follows same permissions as parent entity

---

## 🚀 **Migration Guide**

### **Upgrading Existing Deployments**

1. **Automatic Migration**
   ```bash
   # Migration runs automatically on startup
   # Or run manually:
   alembic upgrade head
   ```

2. **Verify Migration**
   - Check admin UI - all entities show metadata sections
   - API responses include new metadata fields
   - Legacy entities display gracefully

3. **No Downtime Required**
   - All metadata columns are nullable
   - Existing functionality unmodified
   - Gradual adoption of metadata features

### **Metadata Backfill (Optional)**

For enhanced audit trails, optionally backfill known metadata:

```sql
-- Backfill system-created entities
UPDATE tools SET
    created_by = 'system',
    created_via = 'migration',
    version = 1
WHERE created_by IS NULL;

-- Similar for other entity tables
UPDATE gateways SET created_by = 'system', created_via = 'migration', version = 1 WHERE created_by IS NULL;
UPDATE servers SET created_by = 'system', created_via = 'migration', version = 1 WHERE created_by IS NULL;
UPDATE prompts SET created_by = 'system', created_via = 'migration', version = 1 WHERE created_by IS NULL;
UPDATE resources SET created_by = 'system', created_via = 'migration', version = 1 WHERE created_by IS NULL;
```

---

## 🔮 **Future Enhancements**

### **Enhanced Audit Features**
- **Change history tracking** - Before/after state comparison
- **Metadata-based filtering** - Search entities by creator, date, source
- **Audit log export** - Generate compliance reports
- **Custom metadata fields** - User-defined entity attributes

### **Cross-Gateway Features**
- **Metadata synchronization** across federated gateways
- **Trust scoring** based on metadata quality
- **Provenance tracking** for complex federation scenarios

### **Analytics Integration**
- **Usage pattern analysis** from metadata
- **Creator activity dashboards**
- **Import/export trend monitoring**

---

## 📋 **API Examples**

### **Creating Entities with Metadata**

Metadata is captured automatically - no additional parameters needed:

```bash
# Create tool - metadata captured automatically
curl -X POST http://localhost:4444/tools \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example_tool",
    "url": "http://example.com/api",
    "integration_type": "REST",
    "request_type": "GET"
  }'

# Response includes metadata
{
  "id": "abc123",
  "name": "example_tool",
  "createdBy": "admin",
  "createdAt": "2024-01-15T10:30:00Z",
  "createdVia": "api",
  "version": 1,
  ...
}
```

### **Filtering by Metadata (Future)**

```bash
# Future enhancement - filter by creator
GET /tools?created_by=admin

# Filter by creation method
GET /tools?created_via=federation

# Filter by date range
GET /tools?created_after=2024-01-01&created_before=2024-01-31
```

---

## ❓ **FAQ**

### **Q: Will this affect existing deployments?**
A: No breaking changes. Existing entities show graceful fallbacks, all APIs work unmodified.

### **Q: What happens if authentication is disabled?**
A: Metadata still works - `created_by` will be `"anonymous"` instead of a username.

### **Q: How much storage does metadata require?**
A: Minimal - approximately 13 additional nullable text columns per entity.

### **Q: Can I disable metadata tracking?**
A: Not currently - metadata is core to the audit system. All fields are optional and backwards compatible.

### **Q: How do I export metadata for compliance?**
A: Use the standard export functionality - metadata is included in all entity exports.

This comprehensive metadata system provides enterprise-grade audit capabilities while maintaining full backwards compatibility and operational simplicity.
