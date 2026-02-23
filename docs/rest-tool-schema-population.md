# REST Tool Schema Auto-Population from OpenAPI

## Overview

When creating REST tools in ContextForge, you can automatically populate `input_schema` and `output_schema` from the OpenAPI specification of the target REST API. This eliminates manual schema definition and ensures consistency with the actual API contract.

## How It Works

ContextForge provides dedicated API endpoints for fetching and extracting schemas from OpenAPI specifications with built-in security protections:

1. **SSRF Protection**: All URL requests are validated against Server-Side Request Forgery attacks
2. **Async I/O**: Non-blocking HTTP requests using `httpx.AsyncClient`
3. **Service Layer**: Schema extraction logic is centralized in `openapi_service.py`
4. **Frontend Integration**: Admin UI can fetch schemas without CORS issues

## API Endpoints

### 1. Generate Schemas from OpenAPI

**Endpoint**: `POST /admin/tools/generate-schemas-from-openapi`

**Purpose**: Fetch OpenAPI spec and extract input/output schemas for a specific tool endpoint.

**Request Body**:
```json
{
  "url": "http://localhost:8100/calculate",
  "request_type": "POST",
  "openapi_url": "http://localhost:8100/openapi.json"  // Optional
}
```

**Response**:
```json
{
  "message": "Schemas generated successfully from OpenAPI spec",
  "success": true,
  "input_schema": {
    "type": "object",
    "properties": {
      "a": {"type": "number"},
      "b": {"type": "number"}
    }
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "result": {"type": "number"}
    }
  },
  "spec_url": "http://localhost:8100/openapi.json"
}
```

### 2. Fetch OpenAPI Spec (Proxy)

**Endpoint**: `GET /admin/fetch-openapi-spec?base_url=http://localhost:8100`

**Purpose**: Fetch the complete OpenAPI specification from a service (acts as CORS proxy).

**Response**: The complete OpenAPI specification JSON.

## Usage Examples

### Using cURL

```bash
# Generate schemas for a specific endpoint
curl -X POST http://localhost:4444/admin/tools/generate-schemas-from-openapi \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "url": "http://localhost:8100/calculate",
    "request_type": "POST"
  }'

# Fetch complete OpenAPI spec
curl -X GET "http://localhost:4444/admin/fetch-openapi-spec?base_url=http://localhost:8100" \
  -H "Authorization: Bearer $TOKEN"
```

### Using Python

```python
import httpx

async def generate_schemas():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:4444/admin/tools/generate-schemas-from-openapi",
            json={
                "url": "http://localhost:8100/calculate",
                "request_type": "POST"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        data = response.json()
        return data["input_schema"], data["output_schema"]
```

## OpenAPI Spec Requirements

Your REST API must expose an OpenAPI specification at `{base_url}/openapi.json` with:

### Example OpenAPI Structure

```json
{
  "openapi": "3.0.0",
  "paths": {
    "/calculate": {
      "post": {
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/CalculateRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/CalculateResponse"
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "CalculateRequest": {
        "type": "object",
        "properties": {
          "a": {"type": "number"},
          "b": {"type": "number"},
          "operation": {"type": "string"}
        },
        "required": ["a", "b", "operation"]
      },
      "CalculateResponse": {
        "type": "object",
        "properties": {
          "result": {"type": "number"}
        }
      }
    }
  }
}
```

## Schema Extraction Logic

### Input Schema Extraction

1. Looks for `requestBody.content.application/json.schema`
2. If schema contains `$ref`, resolves it from `components.schemas`
3. If no requestBody exists, uses empty object schema

### Output Schema Extraction

1. Checks responses in order: `200`, `201`, `default`
2. Looks for `content.application/json.schema`
3. If schema contains `$ref`, resolves it from `components.schemas`
4. If no valid response schema found, leaves `output_schema` as `None`

## Security Features

### SSRF Protection

All OpenAPI spec fetching includes comprehensive SSRF (Server-Side Request Forgery) protection:

1. **URL Validation**: URLs are validated for proper structure and allowed schemes
2. **Hostname Validation**: Hostnames are checked against blocked lists (cloud metadata, internal services)
3. **IP Address Validation**: Resolved IPs are checked against:
   - Blocked networks (e.g., `169.254.169.254/32` for cloud metadata)
   - Localhost/loopback addresses (configurable)
   - Private networks (configurable with allowlist support)
4. **DNS Resolution**: All A/AAAA records are checked to prevent DNS rebinding attacks

### Configuration

SSRF protection is controlled via environment variables:

```bash
SSRF_PROTECTION_ENABLED=true
SSRF_BLOCKED_NETWORKS=["169.254.169.254/32", "169.254.0.0/16"]
SSRF_BLOCKED_HOSTS=["metadata.google.internal", "169.254.169.254"]
SSRF_ALLOW_LOCALHOST=false
SSRF_ALLOW_PRIVATE_NETWORKS=false
```

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `Security validation failed` | URL blocked by SSRF protection | Use a public, non-blocked URL |
| `Failed to fetch OpenAPI spec` | OpenAPI endpoint not accessible | Verify the URL is correct and accessible |
| `Path not found in OpenAPI spec` | Path doesn't exist in the spec | Check the path matches the OpenAPI definition |
| `Method not found for path` | HTTP method not defined for path | Verify the method is correct (GET, POST, etc.) |
| `Timeout fetching OpenAPI spec` | Request took longer than 10 seconds | Check network connectivity or increase timeout |

## Validation Rules

1. **Authentication Required**: Both endpoints require appropriate RBAC permissions
2. **Timeout**: OpenAPI fetch has a 10-second timeout
3. **SSRF Protection**: All URLs are validated before making requests
4. **Async I/O**: Non-blocking requests prevent worker thread stalls

## Integration with Tool Creation

When creating REST tools via the Admin UI or API, you can use these endpoints to fetch schemas before submitting the tool creation form:

1. **Admin UI Flow**:
   - User enters the tool URL
   - Frontend calls `/admin/tools/generate-schemas-from-openapi`
   - Schemas are populated in the form
   - User reviews and submits the tool

2. **API Flow**:
   - Call `/admin/tools/generate-schemas-from-openapi` to get schemas
   - Use the returned schemas in the tool creation request
   - Submit to `POST /tools` with the schemas included

## Best Practices

1. **Keep OpenAPI Specs Updated**: Ensure your REST API's OpenAPI spec is always current
2. **Use Schema References**: Use `$ref` in OpenAPI for reusable schemas
3. **Document Required Fields**: Mark required fields in OpenAPI schemas
4. **Provide Descriptions**: Add descriptions to schema properties for better documentation
5. **Test Accessibility**: Verify `{base_url}/openapi.json` is accessible before creating tools

## Troubleshooting

### Debug Mode

Enable debug logging to see schema extraction details:

```python
import logging
logging.getLogger("mcpgateway.schemas").setLevel(logging.DEBUG)
```

### Manual Verification

Test OpenAPI endpoint manually:

```bash
curl http://localhost:8100/openapi.json | jq '.paths["/calculate"].post'
```

### Fallback to Manual Schemas

If auto-population fails, you can always provide schemas manually:

```python
tool = ToolCreate(
    name="fallback_tool",
    integration_type="REST",
    base_url="http://localhost:8100",
    path_template="/calculate",
    input_schema={...},  # Manual schema
    output_schema={...}  # Manual schema
)
```

## Implementation Details

The validator is implemented in `mcpgateway/schemas.py`:

```python
@model_validator(mode="before")
@classmethod
def populate_rest_schemas_from_openapi(cls, values: dict) -> dict:
    """
    For integration_type 'REST':
    Fetch OpenAPI spec from base_url and populate input_schema and output_schema
    if they are not already provided or are empty.
    """
    # Implementation details...
```

## Related Documentation

- [REST Tool Configuration](./rest-tools.md)
- [OpenAPI Specification](https://swagger.io/specification/)
- [Tool Registration API](./api/tools.md)
