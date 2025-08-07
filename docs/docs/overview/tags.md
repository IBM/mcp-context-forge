# 🏷️ Tags System

MCP Gateway provides a comprehensive tag system for organizing and filtering entities. Tags help categorize tools, resources, prompts, and servers, making them easier to discover and manage.

---

## 📋 Overview

Tags are metadata labels that can be attached to any entity in MCP Gateway:

- **Tools** - Categorize by functionality (e.g., `api`, `database`, `utility`)
- **Resources** - Group by content type (e.g., `documentation`, `config`, `data`)
- **Prompts** - Organize by purpose (e.g., `coding`, `analysis`, `creative`)
- **Servers** - Tag by environment (e.g., `production`, `development`, `testing`)

!!! info "Tag Format"
    - Tags are automatically normalized to lowercase
    - Length: 2-50 characters
    - Allowed characters: letters, numbers, hyphens, colons, dots
    - Spaces and underscores automatically converted to hyphens
    - Stored as JSON arrays in the database
    - Displayed as comma-separated values in forms

---

## 🎯 Quick Start

### Using the Admin UI

1. **View Tags**: All entity tables display tags as blue badges
2. **Filter by Tags**: Use the tag filter boxes to find entities
3. **Add Tags**: Include tags when creating entities (comma-separated)
4. **Edit Tags**: Modify tags through edit modals

### Using the REST API

All CRUD operations support tags through the REST API with JWT authentication.

---

## ✨ Tag Normalization

MCP Gateway automatically normalizes tags to ensure consistency and prevent duplicates:

### **Automatic Transformations**

- **Case Conversion**: `"Finance"` → `"finance"`
- **Space Replacement**: `"Machine Learning"` → `"machine-learning"`
- **Underscore Replacement**: `"web_development"` → `"web-development"`
- **Whitespace Trimming**: `"  api  "` → `"api"`
- **Multiple Spaces**: `"data   science"` → `"data-science"`

### **Duplicate Removal**

Tags are automatically deduplicated while preserving order:

```json
// Input
["Machine Learning", "machine-learning", "API", "api", "ML"]

// Result after normalization
["machine-learning", "api", "ml"]
```

### **Smart Input Handling**

The system intelligently handles various input formats:

- **Comma-separated**: `"api,web,mobile"` → `["api", "web", "mobile"]`
- **Mixed case**: `["API", "Api", "api"]` → `["api"]`
- **Invalid entries**: `["valid", "", "a", "toolong..."]` → `["valid"]`

!!! tip "User-Friendly Input"
    Users can type tags naturally (e.g., "Machine Learning", "Web Development") and the system automatically converts them to the standard format ("machine-learning", "web-development").

---

## 🛠️ Tools API

### Create Tool with Tags

```bash
# First, get a JWT token
JWT_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret your-secret-key)

# Create a tool with tags
curl -X POST "http://localhost:8080/admin/tools" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "weather-api",
    "url": "https://api.weather.com",
    "description": "Weather information tool",
    "integrationType": "REST",
    "tags": ["weather", "api", "external"]
  }'
```

### List Tools with Tag Filtering

```bash
# Get all tools
curl -X GET "http://localhost:8080/admin/tools" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Filter by single tag
curl -X GET "http://localhost:8080/admin/tools?tags=weather" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Filter by multiple tags (OR logic)
curl -X GET "http://localhost:8080/admin/tools?tags=weather,api" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Update Tool Tags

```bash
# Get existing tool
TOOL_ID=1
curl -X GET "http://localhost:8080/admin/tools/$TOOL_ID" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Update tool with new tags
curl -X PUT "http://localhost:8080/admin/tools/$TOOL_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "weather-api",
    "url": "https://api.weather.com",
    "description": "Weather information tool",
    "integrationType": "REST",
    "tags": ["weather", "api", "external", "production"]
  }'
```

---

## 📁 Resources API

### Create Resource with Tags

```bash
# Create a resource with tags
curl -X POST "http://localhost:8080/admin/resources" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "uri": "config://database.json",
    "name": "Database Configuration",
    "description": "Main database connection settings",
    "mimeType": "application/json",
    "content": "{\\"host\\": \\"localhost\\", \\"port\\": 5432}",
    "tags": ["config", "database", "production"]
  }'
```

### Filter Resources by Tags

```bash
# Filter resources by configuration tag
curl -X GET "http://localhost:8080/admin/resources?tags=config" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Filter by multiple tags
curl -X GET "http://localhost:8080/admin/resources?tags=database,config" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Update Resource Tags

```bash
RESOURCE_URI="config://database.json"
curl -X PUT "http://localhost:8080/admin/resources/$(echo $RESOURCE_URI | sed 's/:/%3A/g; s/\//%2F/g')" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Database Configuration",
    "description": "Updated database connection settings",
    "mimeType": "application/json",
    "content": "{\\"host\\": \\"prod-db\\", \\"port\\": 5432}",
    "tags": ["config", "database", "production", "updated"]
  }'
```

---

## 💬 Prompts API

### Create Prompt with Tags

```bash
# Create a prompt with tags
curl -X POST "http://localhost:8080/admin/prompts" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-review",
    "description": "Code review assistant prompt",
    "template": "Please review the following code for best practices:\\n\\n{{code}}",
    "arguments": [
      {
        "name": "code",
        "description": "The code to review",
        "required": true
      }
    ],
    "tags": ["coding", "review", "quality-assurance"]
  }'
```

### Filter Prompts by Tags

```bash
# Get coding-related prompts
curl -X GET "http://localhost:8080/admin/prompts?tags=coding" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Get prompts for both coding and review
curl -X GET "http://localhost:8080/admin/prompts?tags=coding,review" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Update Prompt Tags

```bash
PROMPT_NAME="code-review"
curl -X PUT "http://localhost:8080/admin/prompts/$(echo $PROMPT_NAME | sed 's/ /%20/g')" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Enhanced code review assistant prompt",
    "template": "Please review the following code for best practices and security:\\n\\n{{code}}",
    "arguments": [
      {
        "name": "code",
        "description": "The code to review",
        "required": true
      }
    ],
    "tags": ["coding", "review", "security", "best-practices"]
  }'
```

---

## 🖥️ Servers API

### Create Server with Tags

```bash
# Create a server with tags
curl -X POST "http://localhost:8080/admin/servers" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-tools",
    "description": "Production environment tools server",
    "icon": "https://example.com/icon.png",
    "tags": ["production", "tools", "external"]
  }'
```

### Filter Servers by Tags

```bash
# Get production servers
curl -X GET "http://localhost:8080/admin/servers?tags=production" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Get servers by environment and type
curl -X GET "http://localhost:8080/admin/servers?tags=production,tools" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Update Server Tags

```bash
SERVER_ID=1
curl -X PUT "http://localhost:8080/admin/servers/$SERVER_ID" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-tools",
    "description": "Production environment tools server - updated",
    "icon": "https://example.com/new-icon.png",
    "tags": ["production", "tools", "external", "updated"]
  }'
```

---

## 🎯 Advanced Filtering

### Complex Tag Queries

```bash
# Filter tools by multiple criteria
curl -X GET "http://localhost:8080/admin/tools?tags=api,external&include_inactive=false" \
  -H "Authorization: Bearer $JWT_TOKEN"

# Paginated results with tag filtering
curl -X GET "http://localhost:8080/admin/tools?tags=weather&cursor=next_page_token" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Combining Filters

```bash
# Get active resources with specific tags
curl -X GET "http://localhost:8080/admin/resources?tags=config&include_inactive=false" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

---

## 🏷️ Tag Management Best Practices

### Naming Conventions

!!! tip "Recommended Tag Patterns"
    Thanks to automatic normalization, you can use natural language that gets converted automatically:

    ```bash
    # Environment tags (any case works)
    "Production", "Development", "Testing", "Staging"

    # Functional categories (spaces converted to hyphens)
    "API Gateway", "Database Access", "File Utility", "External Integration"

    # Content types (underscores converted to hyphens)
    "user_documentation", "config_files", "test_data", "email_templates"

    # Purpose/domain (mixed formats normalized)
    "Weather API", "financial_data", "SECURITY-TOOLS", "system monitoring"
    ```

    **All become properly formatted**: `"production"`, `"api-gateway"`, `"user-documentation"`, `"weather-api"`, etc.

### Organization Strategies

1. **Hierarchical Tags**: Use prefixes for organization
   ```json
   ["env:production", "type:api", "domain:weather"]
   ```

2. **Functional Grouping**: Group by what the entity does
   ```json
   ["data-processing", "external-api", "user-facing"]
   ```

3. **Lifecycle Tags**: Track entity status
   ```json
   ["active", "deprecated", "beta", "experimental"]
   ```

---

## 🔍 Admin UI Features

### Tag Display

- **Table Views**: Tags shown as blue badges in all entity tables
- **Details Views**: Tags displayed with proper styling in view modals
- **Filtering**: Real-time tag-based filtering with suggestions

### Tag Management

- **Add Tags**: During entity creation via comma-separated input
- **Edit Tags**: Modify tags through edit modals
- **Visual Feedback**: Immediate updates and proper validation

### Filter Interface

```markdown
🔍 **Tag Filter Box**: Type comma-separated tags
💡 **Available Tags**: Click suggested tags to add to filter
🔄 **Real-time**: Results update as you type
```

---

## 📊 Response Formats

### Entity with Tags Response

```json
{
  "id": 1,
  "name": "weather-api",
  "url": "https://api.weather.com",
  "description": "Weather information tool",
  "integrationType": "REST",
  "tags": ["weather", "api", "external"],
  "isActive": true,
  "createdAt": "2024-01-15T10:00:00Z",
  "updatedAt": "2024-01-15T10:00:00Z"
}
```

### Filtered Results

```json
{
  "items": [
    {
      "id": 1,
      "name": "weather-api",
      "tags": ["weather", "api", "external"]
    }
  ],
  "total": 1,
  "cursor": null
}
```

---

## 🚨 Error Handling

### Common Issues

!!! warning "Tag Validation Rules"
    - **Length**: Tags must be 2-50 characters after normalization
    - **Characters**: Only letters, numbers, hyphens, colons, dots allowed
    - **Special Characters**: Invalid characters are filtered out (e.g., `@`, `#`, `$`)
    - **Empty Tags**: Null, empty strings, and whitespace-only tags are filtered out
    - **Automatic Filtering**: Invalid tags are silently removed rather than causing errors

### Normalization Examples

```bash
# Input with mixed formats and invalid tags
curl -X POST "http://localhost:8080/admin/tools" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-tool",
    "url": "https://example.com",
    "tags": ["Machine Learning", "API", "web_development", "", "a", "invalid@tag", "ML"]
  }'

# Result: Tags automatically normalized and filtered
# Stored as: ["machine-learning", "api", "web-development", "ml"]
# Filtered out: "", "a" (too short), "invalid@tag" (special char)

# Comma-separated input also works
curl -X POST "http://localhost:8080/admin/tools" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "api-tool",
    "url": "https://api.example.com",
    "tags": ["web,mobile,API"]
  }'

# Result: ["web", "mobile", "api"]
```

!!! success "Robust Handling"
    The system gracefully handles invalid input by filtering out problematic tags rather than rejecting the entire request. This makes the API more user-friendly and robust.

---

## 🔧 Authentication

All tag operations require JWT authentication. Generate tokens using:

```bash
# Generate token for admin user
JWT_TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token -u admin --secret your-secret-key)

# Use token in requests
curl -H "Authorization: Bearer $JWT_TOKEN" ...
```

!!! info "Token Management"
    - Tokens expire based on server configuration
    - Include `Authorization: Bearer <token>` header in all requests
    - 401 responses indicate expired or invalid tokens

---

## 🎉 Summary

The MCP Gateway tag system provides:

- ✅ **Universal Support**: Tags for all entity types (tools, resources, prompts, servers)
- ✅ **Smart Normalization**: Automatic case conversion, space-to-hyphen, deduplication
- ✅ **REST API**: Full CRUD operations with intelligent tag filtering
- ✅ **Admin UI**: Visual tag management, editing, and real-time filtering
- ✅ **User-Friendly Input**: Natural language input automatically formatted
- ✅ **Robust Validation**: Invalid tags filtered out, not rejected
- ✅ **Flexible Formats**: Arrays, comma-separated strings, mixed case all supported
- ✅ **Security**: Special characters and malicious input automatically filtered

**Key Benefits:**

- 🚀 **Zero Learning Curve**: Type tags naturally, system handles the rest
- 🔍 **Powerful Search**: Find entities by any combination of tags
- 🛡️ **Bulletproof**: Handles any input format gracefully
- ⚡ **Performance**: Optimized database queries and indexing

Tags make organizing and discovering MCP Gateway entities simple, intuitive, and bulletproof!
