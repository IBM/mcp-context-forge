# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openapi_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OpenAPI Service for ContextForge AI Gateway.
This module provides services for fetching and extracting schemas from OpenAPI specifications.
"""

# Standard
import asyncio
import collections
import copy
from itertools import chain
import logging
from sys import getsizeof
import time
from typing import Any, Iterator, NamedTuple, Optional, Tuple
import urllib.parse

# Third-Party
import orjson

# First-Party
from mcpgateway.common.validators import pin_url_to_resolved_ip, SecurityValidator
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
_SPEC_CACHE_MAX_BYTES = 64 * 1024 * 1024
_SPEC_CACHE_TTL = 60.0
# A failed fetch is cached too, for a much shorter window. Without a negative entry every
# queued single-flight waiter re-runs the failing fetch in turn, so N waiters pay N × timeout.
_SPEC_ERROR_TTL = 5.0
# Include the expiry object and OrderedDict node storage alongside the entry tuple.
_SPEC_CACHE_ENTRY_OVERHEAD_BYTES = getsizeof((0.0, None, 0)) + getsizeof(0.0) + 48


class _CachedFailure(NamedTuple):
    """A traceback-free failure record for the short negative-cache window."""

    exception_type: type[Exception]
    message: str


class _SpecLock(NamedTuple):
    """Per-URL single-flight lock and the number of callers using it."""

    lock: asyncio.Lock
    users: int


def _cacheable_failure(exc: Exception) -> Optional[_CachedFailure]:
    """Return a lightweight failure record when its exception can be rebuilt from its message."""
    exception_type = type(exc)
    if exception_type is not ValueError and exception_type.__module__ != "httpx":
        return None

    message = str(exc)
    try:
        exception_type(message)
    except Exception:
        return None
    return _CachedFailure(exception_type, message)


_spec_cache: collections.OrderedDict[str, tuple[float, dict[str, Any] | _CachedFailure, int]] = collections.OrderedDict()
_SPEC_CACHE_BYTES = 0
_spec_locks: dict[str, _SpecLock] = {}
_spec_locks_guard = asyncio.Lock()


async def fetch_openapi_spec(spec_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch an OpenAPI specification from a URL with SSRF protection.

    Results are cached in-process for ``_SPEC_CACHE_TTL`` seconds. Rebuildable
    value and HTTPX failures are cached for ``_SPEC_ERROR_TTL`` seconds without
    retaining their traceback or request objects. Concurrent callers for the
    same URL share a single in-flight fetch (single-flight).
    The cache is bounded by entry count and aggregate memory; expired and
    overflow entries are evicted on access.

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
    global _SPEC_CACHE_BYTES

    now = time.monotonic()

    # --- evict expired entries on every access ---
    expired_keys = [k for k, (expires_at, _, _) in _spec_cache.items() if expires_at <= now]
    for k in expired_keys:
        _SPEC_CACHE_BYTES -= _spec_cache.pop(k)[2]

    fresh = _fresh_cached_copy(spec_url)
    if fresh is not None:
        logger.debug("OpenAPI spec cache hit for %s", spec_url)
        return fresh

    # --- single-flight: one fetch per URL, concurrent callers wait ---
    async with _spec_locks_guard:
        shared_lock = _spec_locks.get(spec_url)
        if shared_lock is None:
            shared_lock = _SpecLock(asyncio.Lock(), 0)
        lock = shared_lock.lock
        _spec_locks[spec_url] = _SpecLock(lock, shared_lock.users + 1)

    try:
        async with lock:
            # Re-check after acquiring — another waiter may have populated the cache.
            fresh = _fresh_cached_copy(spec_url)
            if fresh is not None:
                logger.debug("OpenAPI spec single-flight coalesced for %s", spec_url)
                return fresh

            logger.debug("OpenAPI spec cache miss, fetching %s", spec_url)
            try:
                result = await _do_fetch(spec_url, timeout)
            except Exception as exc:
                failure = _cacheable_failure(exc)
                if failure is not None:
                    _store(spec_url, failure, _SPEC_ERROR_TTL)
                raise

            _store(spec_url, result, _SPEC_CACHE_TTL)
            return copy.deepcopy(result)
    finally:
        await _release_spec_lock(spec_url, lock)


async def _release_spec_lock(spec_url: str, lock: asyncio.Lock) -> None:
    """Remove an idle single-flight lock after its final caller leaves."""
    async with _spec_locks_guard:
        shared_lock = _spec_locks.get(spec_url)
        if shared_lock is None or shared_lock.lock is not lock:
            return
        if shared_lock.users == 1:
            _spec_locks.pop(spec_url, None)
        else:
            _spec_locks[spec_url] = _SpecLock(lock, shared_lock.users - 1)


def _estimate_spec_cache_size(spec_url: str, value: dict[str, Any] | _CachedFailure, max_bytes: int) -> int:
    """Estimate retained bytes without building a second copy of a large graph."""
    total = getsizeof(spec_url) + _SPEC_CACHE_ENTRY_OVERHEAD_BYTES
    seen: set[int] = set()
    pending: list[Iterator[object]] = [iter((value,))]
    while pending and total <= max_bytes:
        try:
            item = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += getsizeof(item)
        if total > max_bytes:
            break
        if isinstance(item, dict):
            pending.append(chain(item.keys(), item.values()))
        elif isinstance(item, (list, tuple, set, frozenset)):
            pending.append(iter(item))
    return total


def _store(spec_url: str, value: dict[str, Any] | _CachedFailure, ttl: float) -> None:
    """Cache *value* under *spec_url* within the entry and byte limits.

    Args:
        spec_url: Cache key for the OpenAPI spec.
        value: Parsed specification, or a traceback-free cached failure.
        ttl: Lifetime of the entry in seconds.
    """
    global _SPEC_CACHE_BYTES

    entry_size = _estimate_spec_cache_size(spec_url, value, _SPEC_CACHE_MAX_BYTES)
    previous = _spec_cache.pop(spec_url, None)
    if previous is not None:
        _SPEC_CACHE_BYTES -= previous[2]
    if entry_size > _SPEC_CACHE_MAX_BYTES:
        return

    _spec_cache[spec_url] = (time.monotonic() + ttl, value, entry_size)
    _SPEC_CACHE_BYTES += entry_size
    _spec_cache.move_to_end(spec_url)
    while len(_spec_cache) > _SPEC_CACHE_MAX or _SPEC_CACHE_BYTES > _SPEC_CACHE_MAX_BYTES:
        _, (_, _, evicted_size) = _spec_cache.popitem(last=False)
        _SPEC_CACHE_BYTES -= evicted_size


def _fresh_cached_copy(spec_url: str) -> Optional[dict[str, Any]]:
    """Return an independent copy of the cached spec while the entry is live.

    Args:
        spec_url: Cache key for the OpenAPI spec.

    Returns:
        A deep copy of the cached spec, or ``None`` when absent or expired.

    Raises:
        Exception: The cached failure, when the live entry is a negative-cache
            entry written by a recent failed fetch.
    """
    cached = _spec_cache.get(spec_url)
    if cached is None or cached[0] <= time.monotonic():
        return None
    _spec_cache.move_to_end(spec_url)
    if isinstance(cached[1], _CachedFailure):
        raise cached[1].exception_type(cached[1].message)
    return copy.deepcopy(cached[1])


async def _do_fetch(spec_url: str, timeout: float) -> dict[str, Any]:
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
    # Third-Party
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
