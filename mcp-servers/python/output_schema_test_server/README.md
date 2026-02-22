# Output Schema Test MCP Server

A test MCP server for validating outputSchema field support in ContextForge.

## Purpose

This server demonstrates and tests the `outputSchema` field implementation (PR #1263) by providing tools with:
- **Structured output schemas** using Pydantic models
- **Complex nested structures** (lists, dicts, nested models)
- **Output validation** and error handling
- **Mixed output types** (typed models, dicts, simple strings)

## Features

### Tools with Output Schemas

1. **add_numbers** - Simple calculation with CalculationResult output
2. **multiply_numbers** - Multiplication with structured output
3. **divide_numbers** - Division with error handling in output
4. **create_user** - Complex nested structure (UserInfo model)
5. **validate_email** - Validation with ValidationResult output
6. **calculate_stats** - Dict-based output schema
7. **echo** - Simple string output (no schema for comparison)
8. **get_server_info** - Server capabilities information

### Output Schema Types

The server demonstrates three types of output schemas:

1. **Pydantic Models** (CalculationResult, UserInfo, ValidationResult)
   - Fully typed with field validation
   - Automatic JSON Schema generation
   - FastMCP converts these to outputSchema

2. **Dict Returns** (calculate_stats, get_server_info)
   - Flexible structure
   - No strict typing

3. **Simple Returns** (echo)
   - No output schema
   - For baseline comparison

## Installation

```bash
# From the server directory
make install

# Or with pip directly
pip install -e .
```

## Usage

### Run with stdio (for local testing)

```bash
make dev
```

### Run with HTTP

```bash
make serve-http
# Server runs on http://0.0.0.0:9100/mcp/
```

### Test the output schemas

```bash
# Start HTTP server first
make serve-http

# In another terminal, run tests
make test-tools
```

This will:
1. List all tools (showing outputSchema fields)
2. Call add_numbers and show structured output
3. Call create_user and show complex nested output

## Testing Output Schema Support

### 1. Register with ContextForge

```bash
# Add as a gateway peer
curl -X POST http://localhost:4444/gateways \
  -H "Content-Type: application/json" \
  -d '{
    "name": "output-schema-test",
    "url": "http://localhost:9100/mcp/",
    "description": "Test server for output schemas",
    "auth_type": "none"
  }'
```

### 2. List tools from gateway

```bash
# Should show outputSchema field for each tool
curl http://localhost:4444/tools | jq '.[] | select(.name | contains("add_numbers"))'
```

Expected output should include:
```json
{
  "name": "add_numbers",
  "description": "Add two numbers and return a structured result with output schema",
  "inputSchema": {...},
  "outputSchema": {
    "type": "object",
    "properties": {
      "result": {"type": "number", "description": "The calculated result"},
      "operation": {"type": "string", "description": "The operation performed"},
      "operands": {"type": "array", "items": {"type": "number"}},
      "success": {"type": "boolean", "description": "Whether the calculation succeeded"}
    },
    "required": ["result", "operation", "operands", "success"]
  }
}
```

### 3. Invoke a tool

```bash
# Call add_numbers
curl -X POST http://localhost:4444/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "name": "add_numbers",
    "arguments": {"a": 10, "b": 5}
  }'
```

Expected output:
```json
{
  "result": 15.0,
  "operation": "addition",
  "operands": [10.0, 5.0],
  "success": true
}
```

### 4. Test import/export

```bash
# Export tools (should include outputSchema)
curl http://localhost:4444/bulk/export > tools.json

# Check that output_schema is present
jq '.tools[] | select(.name == "add_numbers") | .output_schema' tools.json

# Re-import (should preserve outputSchema)
curl -X POST http://localhost:4444/bulk/import \
  -H "Content-Type: application/json" \
  -d @tools.json
```

## Validation Checklist

Use this server to verify:

- [ ] outputSchema field appears in tools/list response
- [ ] outputSchema is stored in database
- [ ] outputSchema is included in tool export
- [ ] outputSchema is restored on import
- [ ] outputSchema is displayed in admin UI
- [ ] FastMCP Pydantic models generate correct schemas
- [ ] Dict returns work with and without schemas
- [ ] Tools without output schemas still work (echo)
- [ ] Complex nested schemas work (create_user)
- [ ] Validation schemas work (validate_email)

## MCP Client Configuration

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "output-schema-test": {
      "command": "python",
      "args": ["-m", "output_schema_test_server.server_fastmcp"]
    }
  }
}
```

### Via ContextForge

Register as a gateway peer (see Testing section above).

## Development

```bash
# Install with dev dependencies
make dev-install

# Format code
make format

# Run linters
make lint

# Run tests
make test

# Clean caches
make clean
```

## License

Apache-2.0
