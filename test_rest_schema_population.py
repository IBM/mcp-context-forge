#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to demonstrate REST tool schema population from OpenAPI spec.

This script shows how the new model validator automatically populates
input_schema and output_schema for REST tools by fetching the OpenAPI spec.
"""

from mcpgateway.schemas import ToolCreate

# Example 1: REST tool with base_url - schemas will be auto-populated
print("=" * 80)
print("Example 1: Creating REST tool with auto-populated schemas")
print("=" * 80)

try:
    tool_data = {
        "name": "calculate_tool",
        "integration_type": "REST",
        "request_type": "POST",
        "base_url": "http://localhost:8100",
        "path_template": "/calculate",
        "description": "A calculator tool",
    }

    tool = ToolCreate(**tool_data)
    print(f"✓ Tool created successfully: {tool.name}")
    print(f"✓ Input Schema: {tool.input_schema}")
    print(f"✓ Output Schema: {tool.output_schema}")

except ValueError as e:
    print(f"✗ Error: {e}")
    print("\nThis is expected if:")
    print("  1. The OpenAPI endpoint is not accessible")
    print("  2. The path is not found in the OpenAPI spec")
    print("  3. The schemas are missing or invalid")

print("\n" + "=" * 80)
print("Example 2: REST tool with nonexistent path - should use default schema")
print("=" * 80)

try:
    tool_data = {
        "name": "fallback_tool",
        "integration_type": "REST",
        "request_type": "POST",
        "base_url": "http://localhost:8100",
        "path_template": "/nonexistent",
        "description": "Tool with nonexistent path",
    }

    tool = ToolCreate(**tool_data)
    print(f"✓ Tool created with fallback schema: {tool.name}")
    print(f"✓ Input Schema (default): {tool.input_schema}")

except ValueError as e:
    print(f"✗ Unexpected error: {e}")

print("\n" + "=" * 80)
print("Example 3: REST tool with pre-populated schemas - should skip auto-population")
print("=" * 80)

try:
    tool_data = {
        "name": "manual_schema_tool",
        "integration_type": "REST",
        "request_type": "POST",
        "base_url": "http://localhost:8100",
        "path_template": "/calculate",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"}
            },
            "required": ["a", "b"]
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "number"}
            }
        },
        "description": "Tool with manual schemas",
    }

    tool = ToolCreate(**tool_data)
    print(f"✓ Tool created with manual schemas: {tool.name}")
    print(f"✓ Input Schema: {tool.input_schema}")
    print(f"✓ Output Schema: {tool.output_schema}")

except ValueError as e:
    print(f"✗ Error: {e}")

print("\n" + "=" * 80)
print("Summary")
print("=" * 80)
print("""
The model validator `populate_rest_schemas_from_openapi`:

1. ✓ Automatically fetches OpenAPI spec from base_url/openapi.json
2. ✓ Extracts input_schema from requestBody (handles $ref and direct schemas)
3. ✓ Extracts output_schema from responses (200, 201, or default)
4. ✓ Gracefully handles missing/inaccessible OpenAPI specs with default schema
5. ✓ Skips auto-population if schemas are already provided
6. ✓ Only applies to integration_type='REST'
7. ✓ Allows REST tools to be created even without OpenAPI specs

Graceful Fallback Scenarios:
- Missing base_url → Uses default schema: {"type": "object", "properties": {}}
- OpenAPI endpoint not accessible → Uses default schema with warning
- Path not found in spec → Uses default schema with warning
- Empty/invalid schemas → Uses default schema with warning
""")

# Made with Bob
