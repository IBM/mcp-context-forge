# Bulk Import Tools

ContextForge provides a bulk import endpoint for efficiently loading multiple tools in a single request, perfect for migrations, environment setup, and team onboarding.

!!! info "Configuration Options"
    This feature is controlled by several environment variables:

    - `MCPGATEWAY_BULK_IMPORT_ENABLED=true` - Enable/disable the endpoint (default: true)
    - `MCPGATEWAY_BULK_IMPORT_MAX_TOOLS=200` - Maximum tools per batch (default: 200)
    - `MCPGATEWAY_BULK_IMPORT_RATE_LIMIT=10` - Requests per minute limit (default: 10)

---

## 🚀 Overview

The bulk import feature allows you to register multiple tools at once through both the Admin UI and API, providing:

- **Per-item validation** - One invalid tool won't fail the entire batch
- **Detailed reporting** - Know exactly which tools succeeded or failed
- **Rate limiting** - Protected against abuse (10 requests/minute)
- **Batch size limits** - Maximum 200 tools per request
- **Multiple input formats** - JSON payload, form data, or file upload
- **User-friendly UI** - Modal dialog with drag-and-drop file support

---

## 🎨 Admin UI Usage

### Accessing the Bulk Import Modal

1. **Navigate to Admin UI** - Open your gateway's admin interface at `http://localhost:4444/admin`
2. **Go to Tools Tab** - Click on the "Tools" tab in the main navigation
3. **Open Bulk Import** - Click the "+ Bulk Import Tools" button next to "Add New Tool"

### Using the Modal

The bulk import modal provides two ways to input tool data:

#### Option 1: JSON Textarea
1. **Paste JSON directly** into the text area
2. **Validate format** - The modal will check JSON syntax before submission
3. **Click Import Tools** to process

#### Option 2: File Upload
1. **Prepare a JSON file** with your tools array
2. **Click "Choose File"** and select your `.json` file
3. **Click Import Tools** to process

### UI Features

- **Real-time validation** - JSON syntax checking before submission
- **Loading indicators** - Progress spinner during import
- **Detailed results** - Success/failure counts with error details
- **Auto-refresh** - Page reloads automatically after successful import
- **Modal controls** - Close with button, backdrop click, or ESC key

---

## 📡 API Endpoint

### Request Methods

#### Method 1: JSON Body
```http
POST /admin/tools/import
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

#### Method 2: Form Data (JSON String)
```http
POST /admin/tools/import
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data

Form field: tools_json=<json_string>
```

#### Method 3: File Upload
```http
POST /admin/tools/import
Authorization: Bearer <jwt_token>
Content-Type: multipart/form-data

Form field: tools_file=<uploaded_json_file>
```

### Payload Structure

```json
[
  {
    "name": "tool_name",
    "url": "https://api.example.com/endpoint",
    "integration_type": "REST",
    "request_type": "GET",
    "description": "Optional description",
    "headers": {
      "X-API-Key": "optional-key"
    },
    "input_schema": {
      "type": "object",
      "properties": {
        "param": {"type": "string"}
      }
    }
  },
  // ... more tools
]
```

### Response

```json
{
  "success": true,
  "created_count": 2,
  "failed_count": 1,
  "created": [
    {"index": 0, "name": "tool1"},
    {"index": 1, "name": "tool2"}
  ],
  "errors": [
    {
      "index": 2,
      "name": "tool3",
      "error": {
        "message": "Validation failed: Invalid request_type",
        "details": [...]
      }
    }
  ]
}
```

---

## 🛠️ Usage Examples

### Using cURL

```bash
# Generate JWT token
TOKEN=$(python3 -m mcpgateway.utils.create_jwt_token \
    --username admin --exp 60 --secret $JWT_SECRET_KEY)

# Import tools from file
curl -X POST http://localhost:4444/admin/tools/import \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @tools.json
```

### Using Python

```python
import requests
import json

# Your tools data
tools = [
    {
        "name": "list_users",
        "url": "https://api.example.com/users",
        "integration_type": "REST",
        "request_type": "GET"
    },
    {
        "name": "create_user",
        "url": "https://api.example.com/users",
        "integration_type": "REST",
        "request_type": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {"type": "object"}
            },
            "required": ["body"]
        }
    }
]

# Make the request
response = requests.post(
    "http://localhost:4444/admin/tools/import",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    json=tools
)

result = response.json()
print(f"Created: {result['created_count']}, Failed: {result['failed_count']}")
```

---

## 📋 Tool Schema Reference

Each tool in the array must follow this schema:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique tool identifier |
| `url` | string | ✅ | Tool endpoint URL |
| `integration_type` | string | ✅ | Must be "REST" or "MCP" |
| `request_type` | string | ✅ | HTTP method: GET, POST, PUT, DELETE, PATCH, SSE, STDIO, STREAMABLEHTTP |
| `description` | string | ❌ | Human-readable description |
| `headers` | object | ❌ | HTTP headers to include |
| `input_schema` | object | ❌ | JSON Schema for input validation |
| `output_schema` | object | ❌ | JSON Schema for output validation |
| `tags` | array | ❌ | List of tags for categorization |
| `rate_limit` | integer | ❌ | Max requests per minute |
| `timeout` | integer | ❌ | Request timeout in seconds |
| `auth_type` | string | ❌ | Authentication type: "basic", "bearer", "api_key" |
| `auth_value` | string | ❌ | Authentication credential |

---

## ⚠️ Error Handling

The endpoint provides detailed error information for each failed tool:

### Validation Errors
```json
{
  "index": 1,
  "name": "invalid_tool",
  "error": {
    "message": "Validation failed: Invalid request_type",
    "details": [
      {
        "field": "request_type",
        "message": "Must be one of: GET, POST, PUT, DELETE, PATCH"
      }
    ]
  }
}
```

### Duplicate Tools
```json
{
  "index": 2,
  "name": "existing_tool",
  "error": {
    "message": "Tool already exists: existing_tool"
  }
}
```

---

## 🎯 Best Practices

1. **Validate locally first** - Check your JSON schema before importing
2. **Use small batches** - Start with 10-20 tools to test your format
3. **Handle partial success** - Check both created and errors arrays
4. **Implement retry logic** - For failed items, fix and retry separately
5. **Monitor rate limits** - Stay under 10 requests per minute

---

## 🔒 Security Considerations

- **Authentication required** - All requests must include a valid JWT token
- **Rate limited** - 10 requests per minute per IP address
- **Size limited** - Maximum 200 tools per request
- **Audit logged** - All imports are logged with username and timestamp

---

## 🚦 Status Codes

| Code | Meaning |
|------|---------|
| `200` | Request processed (check success field for results) |
| `401` | Authentication required or invalid token |
| `403` | Feature disabled (MCPGATEWAY_BULK_IMPORT_ENABLED=false) |
| `413` | Payload too large (>200 tools) |
| `422` | Invalid request format |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

---

## 💡 Tips

- Use the bulk import for initial setup and migrations
- Export existing tools first to understand the schema
- Test with a small subset before importing hundreds of tools
- Keep your import files in version control for reproducibility
