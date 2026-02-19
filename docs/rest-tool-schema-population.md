# REST Tool Schema Auto-Population from OpenAPI

## Overview

When creating REST tools in MCP Gateway, the `input_schema` and `output_schema` are now automatically populated from the OpenAPI specification of the target REST API. This eliminates manual schema definition and ensures consistency with the actual API contract.

## How It Works

The `ToolCreate` schema includes a model validator `populate_rest_schemas_from_openapi` that:

1. **Fetches OpenAPI Spec**: Retrieves the OpenAPI specification from `{base_url}/openapi.json`
2. **Matches Path**: Finds the matching path in the OpenAPI spec using `path_template`
3. **Extracts Input Schema**: Retrieves the request body schema (handles both `$ref` and direct schemas)
4. **Extracts Output Schema**: Retrieves the response schema from 200/201/default responses
5. **Validates**: Ensures `input_schema` is not empty for REST tools

## Usage

### Automatic Schema Population

When creating a REST tool, simply provide the `base_url` and `path_template`:

```python
from mcpgateway.schemas import ToolCreate

tool = ToolCreate(
    name="calculate_tool",
    integration_type="REST",
    request_type="POST",
    base_url="http://localhost:8100",
    path_template="/calculate",
    description="Calculator tool"
)

# Schemas are automatically populated from OpenAPI spec
print(tool.input_schema)  # Extracted from requestBody
print(tool.output_schema)  # Extracted from responses
```

### Manual Schema Override

If you provide schemas manually, auto-population is skipped:

```python
tool = ToolCreate(
    name="manual_tool",
    integration_type="REST",
    request_type="POST",
    base_url="http://localhost:8100",
    path_template="/calculate",
    input_schema={
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"}
        }
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "number"}
        }
    }
)
# Uses provided schemas, no OpenAPI fetch
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

## Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `Failed to fetch OpenAPI spec` | OpenAPI endpoint not accessible | Schema auto-population skipped, minimal default used |
| `Path not found in OpenAPI spec` | `path_template` doesn't match any path | Schema auto-population skipped, minimal default used |
| `Method not found for path` | HTTP method not defined for path | Schema auto-population skipped, minimal default used |
| `Schema reference not found` | `$ref` points to non-existent schema | Warning logged, minimal default used |

**Note**: The validator now gracefully handles missing or inaccessible OpenAPI specs by using a minimal default schema `{"type": "object", "properties": {}}` instead of raising validation errors. This allows REST tools to be created even when OpenAPI specs are not available.

## Validation Rules

1. **REST Tools Only**: Auto-population only applies to `integration_type="REST"`
2. **Optional base_url**: If `base_url` is not provided, auto-population is skipped and a minimal default schema is used
3. **Skip if Provided**: If schemas are manually provided and non-empty, auto-population is skipped
4. **Timeout**: OpenAPI fetch has a 10-second timeout
5. **Graceful Fallback**: If OpenAPI fetch fails or schemas cannot be extracted, a minimal default schema is used instead of raising an error

## API Endpoint Integration

When using the REST API to create tools:

```bash
# POST /tools
curl -X POST http://localhost:4444/tools \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "my_rest_tool",
    "integration_type": "REST",
    "request_type": "POST",
    "base_url": "http://api.example.com",
    "path_template": "/v1/endpoint",
    "description": "My REST tool"
  }'
```

The response will include the auto-populated schemas:

```json
{
  "id": "tool-123",
  "name": "my_rest_tool",
  "input_schema": {
    "type": "object",
    "properties": { ... }
  },
  "output_schema": {
    "type": "object",
    "properties": { ... }
  }
}
```

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
