# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openapi_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OpenAPI Service for ContextForge AI Gateway.
This module provides services for fetching and extracting schemas from OpenAPI specifications.
"""

import asyncio
import copy
import collections
import logging
import time
from typing import Optional, Tuple
import urllib.parse

# Third-Party
import orjson

# First-Party
from mcpgateway.common.validators import SecurityValidator, pin_url_to_resolved_ip
from mcpgateway.config import settings

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

_SPEC_CACHE_MAX = 64
_SPEC_CACHE_TTL = 60.0
_spec_cache: collections.OrderedDict[str, tuple[float, dict]] = collections.OrderedDict()
_spec_locks: dict[str, asyncio.Lock] = {}
_spec_locks_guard = asyncio.Lock()


async def fetch_openapi_spec(spec_url: str, timeout: float = 10.0) -> dict:
    """Fetch an OpenAPI specification from a URL with SSRF protection.

    Results are cached in-process for ``_SPEC_CACHE_TTL`` seconds.  Concurrent
    callers for the same URL share a single in-flight fetch (single-flight).
    The cache is bounded to ``_SPEC_CACHE_MAX`` entries; expired and overflow
    entries are evicted on every access.

    Connection pinning (DNS-rebinding prevention) follows the same pattern as
    ``tool_service`` and ``a2a_protocol``: the validated DNS resolution is
    pinned to the outbound request, and the original ``Host``/SNI are preserved.
    An isolated ephemeral HTTP client is used per fetch to prevent cross-host
    cookie leakage.

    Args:
        spec_url: The URL to fetch the OpenAPI spec from.
        timeout: Request timeout in seconds (default: 10.0).

    Returns:
        The parsed OpenAPI specification.

    Raises:
        ValueError: If URL fails security validation, response is too large, or
            response body is not valid JSON.
        httpx.HTTPError: If the request fails.
    """
    now = time.monotonic()

    # --- evict expired entries on every access ---
    expired_keys = [k for k, (ts, _) in _spec_cache.items() if (now - ts) >= _SPEC_CACHE_TTL]
    for k in expired_keys:
        _spec_cache.pop(k, None)
        _spec_locks.pop(k, None)

    fresh = _fresh_cached_copy(spec_url)
    if fresh is not None:
        logger.debug("OpenAPI spec cache hit for %s", spec_url)
        return fresh

    # --- single-flight: one fetch per URL, concurrent callers wait ---
    async with _spec_locks_guard:
        if spec_url not in _spec_locks:
            _spec_locks[spec_url] = asyncio.Lock()
        lock = _spec_locks[spec_url]

    async with lock:
        # Re-check after acquiring — another waiter may have populated the cache.
        fresh = _fresh_cached_copy(spec_url)
        if fresh is not None:
            logger.debug("OpenAPI spec single-flight coalesced for %s", spec_url)
            return fresh

        logger.debug("OpenAPI spec cache miss, fetching %s", spec_url)
        try:
            result = await _do_fetch(spec_url, timeout)
        except Exception:
            # A failed fetch writes no cache entry, so neither the TTL sweep nor
            # LRU eviction can ever drop this lock. Pop it here to keep
            # _spec_locks bounded against caller-controlled failing URLs.
            _spec_locks.pop(spec_url, None)
            raise

        # --- store and enforce maxsize (LRU eviction) ---
        _spec_cache[spec_url] = (time.monotonic(), result)
        _spec_cache.move_to_end(spec_url)
        while len(_spec_cache) > _SPEC_CACHE_MAX:
            evicted_key, _ = _spec_cache.popitem(last=False)
            _spec_locks.pop(evicted_key, None)

        return copy.deepcopy(result)


def _fresh_cached_copy(spec_url: str) -> Optional[dict]:
    """Return an independent copy of the cached spec while it is within its TTL.

    Args:
        spec_url: Cache key for the OpenAPI spec.

    Returns:
        A deep copy of the cached spec, or ``None`` when absent or expired.
    """
    cached = _spec_cache.get(spec_url)
    if cached and (time.monotonic() - cached[0]) < _SPEC_CACHE_TTL:
        _spec_cache.move_to_end(spec_url)
        return copy.deepcopy(cached[1])
    return None


async def _do_fetch(spec_url: str, timeout: float) -> dict:
    """Validate, pin, and fetch a single OpenAPI spec URL.

    Uses an isolated ephemeral HTTP client (no shared cookies, single
    connection) with the resolved IP pinned into the URL and the original
    Host/SNI preserved — identical to the REST tool-invocation pattern.

    Args:
        spec_url: Validated OpenAPI spec URL.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON specification dict.
    """
    import httpx  # pylint: disable=import-outside-toplevel

    # --- SSRF: validate + DNS-pin (closes the rebinding window) ---
    validated = await SecurityValidator.validate_url_for_connection_pinning(spec_url, "OpenAPI spec URL")
    resolved_ip = validated.get("resolved_ip")
    original_hostname = validated.get("hostname")
    original_authority = validated.get("original_authority")

    fetch_url = spec_url
    extra_headers: dict[str, str] = {}
    extensions: dict[str, str] = {}

    if resolved_ip and original_hostname and original_authority:
        fetch_url = pin_url_to_resolved_ip(spec_url, resolved_ip)
        extra_headers["Host"] = original_authority
        extensions["sni_hostname"] = original_hostname
    elif settings.ssrf_protection_enabled:
        raise ValueError("OpenAPI spec URL blocked by URL policy")

    # --- isolated client: no shared cookies, single connection ---
    async with httpx.AsyncClient(
        verify=not settings.skip_ssl_verify,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
    ) as client:
        request = client.build_request("GET", fetch_url, headers=extra_headers, timeout=timeout, extensions=extensions)
        response = await client.send(request, stream=True)
        try:
            response.raise_for_status()

            # Early reject via Content-Length when the header is present.
            try:
                cl = int(response.headers.get("content-length", "0"))
            except (ValueError, OverflowError):
                cl = 0  # Malformed header — fall through to streamed check.
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
        finally:
            await response.aclose()

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
