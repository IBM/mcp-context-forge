# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openapi_service.py
Copyright 2026
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
import orjson

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.services.http_client_service import get_isolated_http_client

logger = logging.getLogger(__name__)


def _resolve_schema(schema_obj: Optional[dict], components_schemas: dict) -> Optional[dict]:
    """Resolve a schema from a ``$ref`` reference or return an inline schema.

    Only resolves top-level local ``$ref`` references of the form
    ``#/components/schemas/<Name>``.  Nested ``$ref`` chains (a resolved
    schema that itself contains ``$ref``) and external file references
    (e.g. ``./models.json#/Foo``) are **not** supported and will return
    ``None`` or the unresolved object respectively.

    Args:
        schema_obj: Schema object that may contain a ``$ref`` or inline schema.
        components_schemas: The ``components.schemas`` section of the OpenAPI spec.

    Returns:
        Resolved schema dictionary, or ``None`` if no valid schema found.
    """
    if isinstance(schema_obj, dict) and "$ref" in schema_obj:
        ref_path = schema_obj["$ref"]
        if not ref_path.startswith("#/components/schemas/"):
            logger.warning("Unsupported $ref format '%s': only local #/components/schemas/ references are resolved", ref_path)
            return None
        schema_name = ref_path.split("/")[-1]
        resolved = components_schemas.get(schema_name)
        if resolved is None:
            logger.warning("Unresolved $ref '%s': schema '%s' not found in components.schemas", ref_path, schema_name)
        return resolved
    return schema_obj if schema_obj is not None else None


# 10 MiB — generous for any realistic OpenAPI spec, prevents memory exhaustion from malicious servers.
_MAX_SPEC_BYTES = 10 * 1024 * 1024


async def fetch_openapi_spec(spec_url: str, timeout: float = 10.0) -> dict:
    """
    Fetch OpenAPI specification from a URL with SSRF protection.

    Redirects are disabled to prevent SSRF bypass (an attacker-controlled
    server could redirect to an internal address after the initial URL
    passes validation).  Response bodies larger than ``_MAX_SPEC_BYTES``
    are rejected to guard against memory exhaustion.

    Args:
        spec_url: The URL to fetch the OpenAPI spec from
        timeout: Request timeout in seconds (default: 10.0)

    Returns:
        dict: The parsed OpenAPI specification

    Raises:
        ValueError: If URL fails security validation, response is too large, or
            response body is not valid JSON
        httpx.HTTPError: If the request fails
    """
    # SSRF Protection: Validate the spec URL before making request
    SecurityValidator.validate_url(spec_url, "OpenAPI spec URL")

    async with get_isolated_http_client(timeout=timeout, follow_redirects=False) as client:
        async with client.stream("GET", spec_url) as response:
            response.raise_for_status()

            # Early reject via Content-Length when the header is present.
            try:
                cl = int(response.headers.get("content-length", "0"))
            except (ValueError, OverflowError):
                cl = 0  # Malformed header — fall through to streamed check below
            if cl > _MAX_SPEC_BYTES:
                raise ValueError(f"OpenAPI spec response too large ({cl} bytes, max {_MAX_SPEC_BYTES})")

            # Stream the body in chunks so we never buffer more than the cap.
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes(chunk_size=8192):
                total += len(chunk)
                if total > _MAX_SPEC_BYTES:
                    raise ValueError(f"OpenAPI spec response too large (>{_MAX_SPEC_BYTES} bytes)")
                chunks.append(chunk)

        body = b"".join(chunks)

        try:
            return orjson.loads(body)
        except (orjson.JSONDecodeError, ValueError) as exc:
            raise ValueError("Response is not valid JSON. Ensure the URL points to a JSON OpenAPI specification.") from exc


def extract_schemas_from_openapi(
    spec: dict,
    path: str,
    method: str,
) -> Tuple[Optional[dict], Optional[dict]]:
    """Extract input and output schemas from an OpenAPI specification.

    Args:
        spec: The OpenAPI specification dictionary.
        path: The API path (e.g., ``"/calculate"``).
        method: The HTTP method (e.g., ``"post"``).

    Returns:
        Tuple of (input_schema, output_schema), either may be ``None``.

    Raises:
        KeyError: If *path* or *method* is not found in the spec.
    """
    method = method.lower()

    # Check if path and method exist in spec
    if path not in spec.get("paths", {}):
        raise KeyError(f"Path '{path}' not found in OpenAPI spec")

    if method not in spec["paths"][path]:
        raise KeyError(f"Method '{method}' not found for path '{path}'")

    operation = spec["paths"][path][method]
    components_schemas = spec.get("components", {}).get("schemas", {})

    # Extract input schema from requestBody
    input_schema = None
    request_body = operation.get("requestBody", {})
    if request_body:
        json_content = request_body.get("content", {}).get("application/json", {})
        if "schema" in json_content:
            input_schema = _resolve_schema(json_content["schema"], components_schemas)

    # Extract output schema from responses (200, 201, or default)
    output_schema = None
    responses = operation.get("responses", {})
    success_response = responses.get("200") if "200" in responses else responses.get("201")
    if success_response:
        json_content = success_response.get("content", {}).get("application/json", {})
        if "schema" in json_content:
            output_schema = _resolve_schema(json_content["schema"], components_schemas)

    return input_schema, output_schema


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
