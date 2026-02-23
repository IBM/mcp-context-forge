# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openapi_service.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OpenAPI Service for ContextForge AI Gateway.
This module provides services for fetching and extracting schemas from OpenAPI specifications.
"""

# Standard
import logging
from typing import Optional, Tuple
import urllib.parse

# Third-Party
import httpx

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings

logger = logging.getLogger(__name__)


async def fetch_openapi_spec(spec_url: str, timeout: float = 10.0) -> dict:
    """
    Fetch OpenAPI specification from a URL with SSRF protection.

    Args:
        spec_url: The URL to fetch the OpenAPI spec from
        timeout: Request timeout in seconds (default: 10.0)

    Returns:
        dict: The parsed OpenAPI specification

    Raises:
        ValueError: If URL fails security validation
        httpx.HTTPError: If the request fails
    """
    # SSRF Protection: Validate the spec URL before making request
    SecurityValidator.validate_url(spec_url, "OpenAPI spec URL")
    parsed_spec = urllib.parse.urlparse(spec_url)
    if parsed_spec.hostname and settings.ssrf_protection_enabled:
        SecurityValidator._validate_ssrf(parsed_spec.hostname, "OpenAPI spec URL")

    # Fetch the spec
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(spec_url)
        response.raise_for_status()
        return response.json()


def extract_schemas_from_openapi(
    spec: dict,
    path: str,
    method: str,
) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Extract input and output schemas from an OpenAPI specification.

    This function parses an OpenAPI 3.x specification and extracts the request body
    schema (input) and response schema (output) for a specific path and HTTP method.
    It handles both inline schemas and $ref references to components/schemas.

    Args:
        spec: The OpenAPI specification dictionary
        path: The API path (e.g., "/calculate")
        method: The HTTP method (e.g., "post", "get")

    Returns:
        Tuple of (input_schema, output_schema), either may be None

    Raises:
        KeyError: If path or method not found in spec

    Examples:
        Basic usage with inline schemas:

        >>> spec = {
        ...     "paths": {
        ...         "/calculate": {
        ...             "post": {
        ...                 "requestBody": {
        ...                     "content": {
        ...                         "application/json": {
        ...                             "schema": {
        ...                                 "type": "object",
        ...                                 "properties": {"a": {"type": "number"}}
        ...                             }
        ...                         }
        ...                     }
        ...                 },
        ...                 "responses": {
        ...                     "200": {
        ...                         "content": {
        ...                             "application/json": {
        ...                                 "schema": {
        ...                                     "type": "object",
        ...                                     "properties": {"result": {"type": "number"}}
        ...                                 }
        ...                             }
        ...                         }
        ...                     }
        ...                 }
        ...             }
        ...         }
        ...     }
        ... }
        >>> input_schema, output_schema = extract_schemas_from_openapi(spec, "/calculate", "post")
        >>> input_schema["type"]
        'object'
        >>> output_schema["properties"]["result"]["type"]
        'number'

        With $ref references:

        >>> spec_with_refs = {
        ...     "paths": {
        ...         "/calculate": {
        ...             "post": {
        ...                 "requestBody": {
        ...                     "content": {
        ...                         "application/json": {
        ...                             "schema": {"$ref": "#/components/schemas/CalcRequest"}
        ...                         }
        ...                     }
        ...                 },
        ...                 "responses": {
        ...                     "200": {
        ...                         "content": {
        ...                             "application/json": {
        ...                                 "schema": {"$ref": "#/components/schemas/CalcResponse"}
        ...                             }
        ...                         }
        ...                     }
        ...                 }
        ...             }
        ...         }
        ...     },
        ...     "components": {
        ...         "schemas": {
        ...             "CalcRequest": {"type": "object", "properties": {"x": {"type": "number"}}},
        ...             "CalcResponse": {"type": "object", "properties": {"sum": {"type": "number"}}}
        ...         }
        ...     }
        ... }
        >>> input_schema, output_schema = extract_schemas_from_openapi(spec_with_refs, "/calculate", "post")
        >>> input_schema["properties"]["x"]["type"]
        'number'
        >>> output_schema["properties"]["sum"]["type"]
        'number'

        Path not found:

        >>> extract_schemas_from_openapi(spec, "/nonexistent", "post")
        Traceback (most recent call last):
            ...
        KeyError: "Path '/nonexistent' not found in OpenAPI spec"

        Method not found:

        >>> extract_schemas_from_openapi(spec, "/calculate", "get")
        Traceback (most recent call last):
            ...
        KeyError: "Method 'get' not found for path '/calculate'"
    """
    method = method.lower()

    # Check if path and method exist in spec
    if path not in spec.get("paths", {}):
        raise KeyError(f"Path '{path}' not found in OpenAPI spec")

    if method not in spec["paths"][path]:
        raise KeyError(f"Method '{method}' not found for path '{path}'")

    operation = spec["paths"][path][method]
    components_schemas = spec.get("components", {}).get("schemas", {})

    def resolve_schema(schema_obj):
        """
        Resolve schema from $ref or return inline schema.

        Args:
            schema_obj: Schema object that may contain a $ref or inline schema

        Returns:
            Resolved schema dictionary or None if no valid schema found
        """
        if isinstance(schema_obj, dict) and "$ref" in schema_obj:
            # Extract schema name from reference (e.g., "#/components/schemas/CalculateRequest")
            schema_ref = schema_obj["$ref"]
            schema_name = schema_ref.split("/")[-1]
            return components_schemas.get(schema_name)
        # Return inline schema or None if empty
        return schema_obj or None

    # Extract input schema from requestBody
    input_schema = None
    request_body = operation.get("requestBody", {})
    if request_body:
        json_content = request_body.get("content", {}).get("application/json", {})
        if "schema" in json_content:
            input_schema = resolve_schema(json_content["schema"])

    # Extract output schema from responses (200, 201, or default)
    output_schema = None
    responses = operation.get("responses", {})
    success_response = responses.get("200") or responses.get("201")
    if success_response:
        json_content = success_response.get("content", {}).get("application/json", {})
        if "schema" in json_content:
            output_schema = resolve_schema(json_content["schema"])

    return input_schema, output_schema


def extract_all_schemas_from_openapi(spec: dict) -> dict:
    """
    Extract all input and output schemas from all paths in an OpenAPI specification.

    This function parses an OpenAPI 3.x specification and extracts all request body
    schemas (input) and response schemas (output) for all paths and HTTP methods.
    It handles both inline schemas and $ref references to components/schemas.

    Args:
        spec: The OpenAPI specification dictionary

    Returns:
        Dictionary mapping paths to their methods and schemas:
        {
            "/path": {
                "method": {
                    "input_schema": {...},
                    "output_schema": {...}
                }
            }
        }

    Examples:
        >>> spec = {
        ...     "paths": {
        ...         "/calculate": {
        ...             "post": {
        ...                 "requestBody": {
        ...                     "content": {
        ...                         "application/json": {
        ...                             "schema": {"$ref": "#/components/schemas/CalcRequest"}
        ...                         }
        ...                     }
        ...                 },
        ...                 "responses": {
        ...                     "200": {
        ...                         "content": {
        ...                             "application/json": {
        ...                                 "schema": {"$ref": "#/components/schemas/CalcResponse"}
        ...                             }
        ...                         }
        ...                     }
        ...                 }
        ...             }
        ...         }
        ...     },
        ...     "components": {
        ...         "schemas": {
        ...             "CalcRequest": {"type": "object", "properties": {"x": {"type": "number"}}},
        ...             "CalcResponse": {"type": "object", "properties": {"sum": {"type": "number"}}}
        ...         }
        ...     }
        ... }
        >>> result = extract_all_schemas_from_openapi(spec)
        >>> result["/calculate"]["post"]["input_schema"]["properties"]["x"]["type"]
        'number'
        >>> result["/calculate"]["post"]["output_schema"]["properties"]["sum"]["type"]
        'number'
    """
    components_schemas = spec.get("components", {}).get("schemas", {})
    paths = spec.get("paths", {})

    result = {}

    def resolve_schema(schema_obj):
        """
        Resolve schema from $ref or return inline schema.

        Args:
            schema_obj: Schema object that may contain a $ref or inline schema

        Returns:
            Resolved schema dictionary or None if no valid schema found
        """
        if isinstance(schema_obj, dict) and "$ref" in schema_obj:
            # Extract schema name from reference (e.g., "#/components/schemas/CalculateRequest")
            schema_ref = schema_obj["$ref"]
            schema_name = schema_ref.split("/")[-1]
            return components_schemas.get(schema_name)
        # Return inline schema or None if empty
        return schema_obj or None

    # Iterate through all paths
    for path, path_item in paths.items():
        path_methods = {}

        # Iterate through all HTTP methods for this path
        for method in ["get", "post", "put", "patch", "delete", "head", "options"]:
            if method not in path_item:
                continue

            operation = path_item[method]
            method_schemas = {}

            # Extract input schema from requestBody
            input_schema = None
            request_body = operation.get("requestBody", {})
            if request_body:
                json_content = request_body.get("content", {}).get("application/json", {})
                if "schema" in json_content:
                    input_schema = resolve_schema(json_content["schema"])

            method_schemas["input_schema"] = input_schema

            # Extract output schema from responses (200, 201, or default)
            output_schema = None
            responses = operation.get("responses", {})
            success_response = responses.get("200") or responses.get("201")
            if success_response:
                json_content = success_response.get("content", {}).get("application/json", {})
                if "schema" in json_content:
                    output_schema = resolve_schema(json_content["schema"])

            method_schemas["output_schema"] = output_schema

            # Only add if at least one schema exists
            if input_schema is not None or output_schema is not None:
                path_methods[method] = method_schemas

        # Only add path if it has at least one method with schemas
        if path_methods:
            result[path] = path_methods

    return result


async def fetch_and_extract_schemas(
    base_url: str,
    path: str,
    method: str,
    openapi_url: Optional[str] = None,
    timeout: float = 10.0,
) -> Tuple[Optional[dict], Optional[dict], str]:
    """
    Fetch OpenAPI spec and extract input/output schemas with SSRF protection.

    Args:
        base_url: The base URL of the API (e.g., "http://localhost:8100")
        path: The API path (e.g., "/calculate")
        method: The HTTP method (e.g., "POST")
        openapi_url: Optional direct URL to OpenAPI spec (overrides base_url)
        timeout: Request timeout in seconds (default: 10.0)

    Returns:
        Tuple of (input_schema, output_schema, spec_url)

    Raises:
        ValueError: If URL fails security validation
        httpx.HTTPError: If the request fails
        KeyError: If path or method not found in spec
    """
    # Determine OpenAPI spec URL
    if openapi_url:
        spec_url = openapi_url
    else:
        spec_url = urllib.parse.urljoin(base_url, "/openapi.json")

    # Fetch the spec with SSRF protection
    spec = await fetch_openapi_spec(spec_url, timeout=timeout)

    # Extract schemas
    input_schema, output_schema = extract_schemas_from_openapi(spec, path, method)

    return input_schema, output_schema, spec_url


async def fetch_and_extract_all_schemas(
    base_url: str,
    openapi_url: Optional[str] = None,
    timeout: float = 10.0,
) -> Tuple[dict, str]:
    """
    Fetch OpenAPI spec and extract all input/output schemas for all routes with SSRF protection.

    Args:
        base_url: The base URL of the API (e.g., "http://localhost:8100")
        openapi_url: Optional direct URL to OpenAPI spec (overrides base_url)
        timeout: Request timeout in seconds (default: 10.0)

    Returns:
        Tuple of (all_schemas_dict, spec_url) where all_schemas_dict maps paths to methods to schemas

    Raises:
        ValueError: If URL fails security validation
        httpx.HTTPError: If the request fails

    Examples:
        >>> # Fetch all schemas from an API (async function, cannot be tested in doctest)
        >>> # all_schemas, spec_url = await fetch_and_extract_all_schemas("http://localhost:8100")
        >>> # "/calculate" in all_schemas
        >>> # "post" in all_schemas["/calculate"]
        >>> pass  # doctest: +SKIP
    """
    # Determine OpenAPI spec URL
    if openapi_url:
        spec_url = openapi_url
    else:
        spec_url = urllib.parse.urljoin(base_url, "/openapi.json")

    # Fetch the spec with SSRF protection
    spec = await fetch_openapi_spec(spec_url, timeout=timeout)

    # Extract all schemas
    all_schemas = extract_all_schemas_from_openapi(spec)

    return all_schemas, spec_url
