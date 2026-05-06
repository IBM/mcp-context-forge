# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/tool_service.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tool Service Implementation.
This module implements tool management and invocation according to the MCP specification.
It handles:
- Tool registration and validation
- Tool invocation with schema validation
- Tool federation across gateways
- Event notifications for tool changes
- Active/inactive tool management
"""

# Standard
import asyncio
import base64
import binascii
from datetime import datetime, timezone
from functools import lru_cache
import json  # NOTE: httpx uses stdlib json, not orjson, so response.json() raises json.JSONDecodeError
import logging
import os
import re
import ssl
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse
import uuid

# Third-Party
import anyio
from cpex.framework import (
    GlobalContext,
    HttpHeaderPayload,
    PluginContextTable,
    PluginError,
    PluginViolationError,
    ToolHookType,
    ToolPostInvokePayload,
    ToolPreInvokePayload,
)
from cpex.framework.constants import GATEWAY_METADATA, TOOL_METADATA
import httpx
import jq
import jsonschema
from jsonschema import Draft4Validator, Draft6Validator, Draft7Validator, validators
from mcp import ClientSession, types
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
import orjson
from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import joinedload, selectinload, Session

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.common.models import Gateway as PydanticGateway
from mcpgateway.common.models import TextContent
from mcpgateway.common.models import Tool as PydanticTool
from mcpgateway.common.models import ToolResult
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.db import A2AAgent as DbA2AAgent
from mcpgateway.db import fresh_db_session
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import get_for_update, server_tool_association
from mcpgateway.db import Tool as DbTool
from mcpgateway.db import ToolMetric, ToolMetricsHourly
from mcpgateway.observability import create_child_span, create_span, inject_trace_context_headers, otel_context_active, set_span_attribute, set_span_error
from mcpgateway.schemas import AuthenticationValues, ToolCreate, ToolMetrics, ToolRead, ToolUpdate, TopPerformer
from mcpgateway.services.a2a_protocol import prepare_a2a_invocation
from mcpgateway.services.audit_trail_service import get_audit_trail_service
from mcpgateway.services.base_service import BaseService
from mcpgateway.services.content_security import ContentSecurityService
from mcpgateway.services.event_service import EventService
from mcpgateway.services.logging_service import LoggingService
from mcpgateway.services.metrics_buffer_service import get_metrics_buffer_service
from mcpgateway.services.metrics_cleanup_service import delete_metrics_in_batches, pause_rollup_during_purge
from mcpgateway.services.metrics_query_service import get_top_performers_combined
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.observability_service import current_trace_id, ObservabilityService
from mcpgateway.services.performance_tracker import get_performance_tracker
from mcpgateway.services.rust_a2a_runtime import get_rust_a2a_runtime_client, RustA2ARuntimeError
from mcpgateway.services.structured_logger import get_structured_logger
from mcpgateway.services.team_management_service import TeamManagementService
from mcpgateway.services.upstream_session_registry import downstream_session_id_from_request_context, get_upstream_session_registry, RegistryNotInitializedError, TransportType
from mcpgateway.transports.context import UserContext
from mcpgateway.utils.admin_check import is_user_admin
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.utils.create_slug import slugify
from mcpgateway.utils.display_name import generate_display_name
from mcpgateway.utils.gateway_access import build_gateway_auth_headers, check_gateway_access, extract_gateway_id_from_headers
from mcpgateway.utils.identity_propagation import build_identity_headers, build_identity_meta
from mcpgateway.utils.metrics_common import build_top_performers
from mcpgateway.utils.pagination import decode_cursor, encode_cursor, unified_paginate
from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached
from mcpgateway.utils.retry_manager import ResilientHttpClient
from mcpgateway.utils.services_auth import decode_auth, encode_auth
from mcpgateway.utils.sqlalchemy_modifier import json_contains_tag_expr
from mcpgateway.utils.ssl_context_cache import get_cached_ssl_context
from mcpgateway.utils.trace_context import format_trace_team_scope
from mcpgateway.utils.trace_redaction import is_input_capture_enabled, is_output_capture_enabled, serialize_trace_payload
from mcpgateway.utils.url_auth import apply_query_param_auth, sanitize_exception_message, sanitize_url_for_logging
from mcpgateway.utils.validate_signature import validate_signature

# Cache import (lazy to avoid circular dependencies)
_REGISTRY_CACHE = None
_TOOL_LOOKUP_CACHE = None


def _get_registry_cache():
    """Get registry cache singleton lazily.

    Returns:
        RegistryCache instance.
    """
    global _REGISTRY_CACHE  # pylint: disable=global-statement
    if _REGISTRY_CACHE is None:
        # First-Party
        from mcpgateway.cache.registry_cache import registry_cache  # pylint: disable=import-outside-toplevel

        _REGISTRY_CACHE = registry_cache
    return _REGISTRY_CACHE


# NOTE: downstream session-id extraction lives in upstream_session_registry so
# tool_service, prompt_service, and resource_service share one implementation.
_downstream_session_id_from_request = downstream_session_id_from_request_context


def _get_tool_lookup_cache():
    """Get tool lookup cache singleton lazily.

    Returns:
        ToolLookupCache instance.
    """
    global _TOOL_LOOKUP_CACHE  # pylint: disable=global-statement
    if _TOOL_LOOKUP_CACHE is None:
        # First-Party
        from mcpgateway.cache.tool_lookup_cache import tool_lookup_cache  # pylint: disable=import-outside-toplevel

        _TOOL_LOOKUP_CACHE = tool_lookup_cache
    return _TOOL_LOOKUP_CACHE


# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


def _extract_tenant_id_from_payload(team_id: Any) -> Optional[str]:
    """Extract a valid tenant id from a raw tool payload team_id value.

    Empty strings are treated as absent (None): a zero-length tenant prefix
    would collapse tenant-scoped Redis keys onto the unscoped layout.
    """
    if team_id is not None and not isinstance(team_id, str):
        logger.debug("Ignoring non-string team_id in tool payload: type=%s, value=%r", type(team_id).__name__, team_id)
        return None
    return team_id if team_id else None


def _apply_tool_payload_to_global_context(
    global_context: "GlobalContext",
    tool_gateway_id: Optional[str],
    app_user_email: Optional[str],
    payload_tenant_id: Optional[str],
) -> None:
    """Enrich an existing GlobalContext with tool-payload-derived values without overwriting.

    Populates server_id, user, and tenant_id on a GlobalContext that was
    supplied by the plugin manager / middleware — filling gaps the upstream
    propagation did not cover while never overwriting a value that was
    already set there. Shared by the two tool-invocation call sites so they
    stay in lockstep.
    """
    if tool_gateway_id and isinstance(tool_gateway_id, str):
        global_context.server_id = tool_gateway_id
    if not global_context.user and app_user_email and isinstance(app_user_email, str):
        global_context.user = app_user_email
    if not global_context.tenant_id and payload_tenant_id:
        global_context.tenant_id = payload_tenant_id


# Initialize performance tracker, structured logger, audit trail, and metrics buffer for tool operations
perf_tracker = get_performance_tracker()
structured_logger = get_structured_logger("tool_service")
audit_trail = get_audit_trail_service()
metrics_buffer = get_metrics_buffer_service()

_ENCRYPTED_TOOL_HEADER_VALUE_KEY = "_mcpgateway_encrypted_header_value_v1"
_TOOL_HEADER_DATA_KEY = "data"
_TOOL_HEADER_LEGACY_VALUE_KEY = "value"
_SENSITIVE_TOOL_HEADER_PATTERNS = (
    re.compile(r"^authorization$", re.IGNORECASE),
    re.compile(r"^proxy-authorization$", re.IGNORECASE),
    re.compile(r"^x-api-key$", re.IGNORECASE),
    re.compile(r"^api-key$", re.IGNORECASE),
    re.compile(r"^apikey$", re.IGNORECASE),
    # Keep broad-enough auth matching while avoiding operational noise from
    # non-secret tracing/idempotency headers (e.g. X-Correlation-Token).
    re.compile(r"^x-(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    re.compile(r"^(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    # Protocol-level and credential-bearing headers that must not be set via mapping.
    re.compile(r"^cookie$", re.IGNORECASE),
    re.compile(r"^set-cookie$", re.IGNORECASE),
    re.compile(r"^host$", re.IGNORECASE),
    re.compile(r"^transfer-encoding$", re.IGNORECASE),
    re.compile(r"^content-length$", re.IGNORECASE),
    re.compile(r"^connection$", re.IGNORECASE),
    re.compile(r"^upgrade$", re.IGNORECASE),
    # Prevent caller-controllable encoding dispatch via header_mapping (see #4139).
    re.compile(r"^content-type$", re.IGNORECASE),
)


def _is_sensitive_tool_header_name(name: str) -> bool:
    """Return whether a tool header name should be treated as sensitive.

    Args:
        name: Header name to evaluate.

    Returns:
        ``True`` when header value should be protected.
    """
    normalized_name = str(name).strip().lower()
    return any(pattern.match(normalized_name) for pattern in _SENSITIVE_TOOL_HEADER_PATTERNS)


def _is_encrypted_tool_header_value(value: Any) -> bool:
    """Return whether a header value uses encrypted envelope format.

    Args:
        value: Header value candidate.

    Returns:
        ``True`` when value is an encrypted envelope mapping.
    """
    return isinstance(value, dict) and isinstance(value.get(_ENCRYPTED_TOOL_HEADER_VALUE_KEY), str)


def _encrypt_tool_header_value(value: Any, existing_value: Any = None) -> Any:
    """Encrypt a single sensitive tool header value.

    Args:
        value: Incoming header value from payload.
        existing_value: Existing stored value used for masked-value merges.

    Returns:
        Encrypted envelope, preserved existing value, or ``None`` when cleared.
    """
    if value is None or value == "":
        return value

    if value == settings.masked_auth_value:
        if _is_encrypted_tool_header_value(existing_value):
            return existing_value
        if existing_value in (None, ""):
            return None
        return _encrypt_tool_header_value(existing_value, None)

    if _is_encrypted_tool_header_value(value):
        return value

    encrypted = encode_auth({_TOOL_HEADER_DATA_KEY: str(value)})
    return {_ENCRYPTED_TOOL_HEADER_VALUE_KEY: encrypted}


def _protect_tool_headers_for_storage(headers: Optional[Dict[str, Any]], existing_headers: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Encrypt sensitive tool header values before persistence.

    Args:
        headers: Incoming tool headers payload.
        existing_headers: Existing stored headers used for masked-value merges.

    Returns:
        Header mapping with sensitive values protected for storage, or ``None``.
    """
    if headers is None:
        return None
    if not isinstance(headers, dict):
        return None

    existing_by_lower: Dict[str, Any] = {}
    if isinstance(existing_headers, dict):
        for key, existing_value in existing_headers.items():
            existing_by_lower[str(key).strip().lower()] = existing_value

    protected: Dict[str, Any] = {}
    for key, value in headers.items():
        if _is_sensitive_tool_header_name(key):
            existing_value = existing_by_lower.get(str(key).strip().lower())
            protected[key] = _encrypt_tool_header_value(value, existing_value)
        else:
            protected[key] = value
    return protected


def _decrypt_tool_header_value(value: Any) -> Any:
    """Decrypt a single tool header envelope when possible.

    Args:
        value: Stored header value, possibly encrypted.

    Returns:
        Decrypted plain value when envelope is valid, else original value.
    """
    if not _is_encrypted_tool_header_value(value):
        return value

    encrypted_payload = value.get(_ENCRYPTED_TOOL_HEADER_VALUE_KEY)
    if not encrypted_payload:
        return value

    try:
        decoded = decode_auth(encrypted_payload)
        if isinstance(decoded, dict):
            if _TOOL_HEADER_DATA_KEY in decoded:
                return decoded[_TOOL_HEADER_DATA_KEY]
            if _TOOL_HEADER_LEGACY_VALUE_KEY in decoded:
                return decoded[_TOOL_HEADER_LEGACY_VALUE_KEY]
    except Exception as exc:
        logger.warning("Failed to decrypt tool header value: %s", exc)
    return value


def _decrypt_tool_headers_for_runtime(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Decrypt tool header map for runtime outbound requests.

    Args:
        headers: Stored header mapping.

    Returns:
        Header mapping with encrypted values decrypted where possible.
    """
    if not isinstance(headers, dict):
        return {}
    return {key: _decrypt_tool_header_value(value) for key, value in headers.items()}


#: Top-level keys that the MCP ``CallToolResult`` envelope admits (including
#: the gateway's internal snake-case aliases). Any dict with keys outside
#: this set is treated as a business payload rather than an MCP envelope.
#: See :func:`_looks_like_mcp_envelope`.
_MCP_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "content",
        "isError",
        "is_error",
        "structuredContent",
        "structured_content",
        "_meta",
        "meta",
    }
)


def _looks_like_mcp_envelope(payload: dict) -> bool:
    """Return ``True`` when a dict strongly resembles an MCP ``CallToolResult`` envelope.

    Used by :meth:`ToolService._coerce_to_tool_result` to decide whether a
    raw dict should be promoted to a ``ToolResult`` via
    ``ToolResult.model_validate``. The check has two layers:

    1. **No unknown top-level keys.** ``ToolResult`` inherits
       ``BaseModelWithConfigDict``, which uses Pydantic's default
       ``extra="ignore"`` — any sibling field not declared on the model
       is **silently dropped** at validation time. Without this first
       check, a REST payload like
       ``{"content": [{"type": "text", "text": "ok"}], "isError": false,
       "recognitionId": "rec-1"}`` would model-validate cleanly and lose
       ``recognitionId`` without warning (Codex-flagged regression).
       So we reject any dict whose keys aren't a subset of
       :data:`_MCP_ENVELOPE_KEYS`.

    2. **At least one positive MCP signal.** Even when the key set is a
       valid subset, we require at least one MCP-specific marker —
       either ``isError``/``is_error``, ``structuredContent``/
       ``structured_content``, or ``content`` holding MCP ``ContentBlock``-
       shaped items (dicts with a string ``type``). This stops a
       minimal ``{"content": "plain text"}`` shape, which *could* be a
       REST payload that coincidentally uses an allowed key name, from
       being interpreted as MCP.

    Both checks must pass. A REST business payload like
    ``{"content": [{"widget": "x"}], "id": 1}`` fails check (1) (``id`` is
    not an MCP envelope key); a minimal ``{"content": "hello"}`` fails
    check (2) (no positive marker); both are therefore correctly treated
    as opaque JSON by the caller.

    Args:
        payload: The dict candidate.

    Returns:
        ``True`` if the dict is confidently an MCP envelope and safe to
        round-trip through ``ToolResult.model_validate`` without losing
        sibling fields, else ``False``.
    """
    keys = payload.keys()
    # Layer 1: reject if there are any keys outside the envelope schema.
    # This is what guards against silent field-dropping for business payloads
    # that happen to include ``content`` / ``isError`` among other fields.
    if not keys <= _MCP_ENVELOPE_KEYS:
        return False
    # Layer 2: require a positive MCP signal so we don't misclassify
    # anonymous REST bodies that merely happen to use a subset of allowed keys.
    if "isError" in keys or "is_error" in keys:
        return True
    if "structuredContent" in keys or "structured_content" in keys:
        return True
    content = payload.get("content")
    if isinstance(content, list) and content and all(isinstance(item, dict) and isinstance(item.get("type"), str) for item in content):
        return True
    return False


def _safe_type_name(obj: Any) -> str:
    """Return ``type(obj).__name__``, or a sentinel if that itself raises.

    Used inside :meth:`ToolService._coerce_to_tool_result`'s last-resort
    fallback so logging and diagnostic text on a pathological object
    (broken proxy, ``__class__`` descriptor that raises, etc.) cannot
    themselves raise and escape the "always returns a valid
    ``ToolResult``" invariant.
    """
    try:
        return type(obj).__name__
    except Exception:  # pylint: disable=broad-except
        return "<untypeable>"


def _safe_text_repr(obj: Any, fallback_type: str) -> str:
    """Coerce an arbitrary object to a non-raising text representation.

    Tries ``str(obj)``, then ``repr(obj)``, then ``f"<{fallback_type}
    object>"``, and finally a fixed sentinel. Used by the opaque-JSON
    last-resort branch of
    :meth:`ToolService._coerce_to_tool_result` — neither ``str`` nor
    ``repr`` is guaranteed to succeed on arbitrary Python objects (a
    class can override either to raise), and without this staged
    fallback a malicious or simply buggy payload could escape the
    helper and break the "never raises" contract downstream code relies
    on.

    Args:
        obj: The payload to stringify.
        fallback_type: Pre-computed type name used in the third-tier
            sentinel; keeps ``type().__name__`` out of this function's
            hot path since it has its own :func:`_safe_type_name`
            guard upstream.

    Returns:
        A ``str``. Never raises.
    """
    try:
        text = str(obj)
        if isinstance(text, str):
            return text
    except Exception:  # pylint: disable=broad-except  # nosec B110
        pass
    try:
        text = repr(obj)
        if isinstance(text, str):
            return text
    except Exception:  # pylint: disable=broad-except  # nosec B110
        pass
    # ``fallback_type`` came from ``_safe_type_name`` so it's
    # guaranteed to be a ``str`` already.
    return f"<{fallback_type} object (unrepresentable)>"


def _handle_json_parse_error(response, error, is_error_response: bool = False) -> dict:
    """Handle JSON parsing failures with graceful fallback to raw text.

    Args:
        response: The HTTP response object with .text attribute
        error: The exception that was raised during JSON parsing
        is_error_response: If True, logs as "error response", else "response"

    Returns:
        Dictionary with response_text key containing the raw response text
        (truncated to REST_RESPONSE_TEXT_MAX_LENGTH if longer to avoid exposing sensitive data),
        or error details if response body is empty/None
    """
    msg = "error response" if is_error_response else "response"
    if not response.text:
        logger.warning(f"Failed to parse JSON {msg}: {error}. Response body was empty.")
        return {"error": "Empty response body"}

    max_length = settings.rest_response_text_max_length
    text = response.text[:max_length] if len(response.text) > max_length else response.text
    if len(response.text) > max_length:
        logger.warning(f"Failed to parse JSON {msg}: {error}. Response truncated from {len(response.text)} to {max_length} characters.")
    else:
        logger.warning(f"Failed to parse JSON {msg}: {error}")
    return {"response_text": text}


@lru_cache(maxsize=256)
def _compile_jq_filter(jq_filter: str):
    """Cache compiled jq filter program.

    Args:
        jq_filter: The jq filter string to compile.

    Returns:
        Compiled jq program object.

    Raises:
        ValueError: If the jq filter is invalid.
    """
    # pylint: disable=c-extension-no-member
    return jq.compile(jq_filter)


@lru_cache(maxsize=128)
def _get_validator_class_and_check(schema_json: str) -> Tuple[type, dict]:
    """Cache schema validation and validator class selection.

    This caches the expensive operations:
    1. Deserializing the schema
    2. Selecting the appropriate validator class based on $schema
    3. Checking the schema is valid

    Supports multiple JSON Schema drafts by using fallback validators when the
    auto-detected validator fails. This handles schemas using older draft features
    (e.g., Draft 4 style exclusiveMinimum: true) that are invalid in newer drafts.

    Args:
        schema_json: Canonical JSON string of the schema (used as cache key).

    Returns:
        Tuple of (validator_class, schema_dict) ready for instantiation.
    """
    schema = orjson.loads(schema_json)

    # First try auto-detection based on $schema
    validator_cls = validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
        return validator_cls, schema
    except jsonschema.exceptions.SchemaError:
        pass

    # Fallback: try older drafts that may accept schemas with legacy features
    # (e.g., Draft 4/6 style boolean exclusiveMinimum/exclusiveMaximum)
    for fallback_cls in [Draft7Validator, Draft6Validator, Draft4Validator]:
        try:
            fallback_cls.check_schema(schema)
            return fallback_cls, schema
        except jsonschema.exceptions.SchemaError:
            continue

    # If no validator accepts the schema, use the original and let it fail
    # with a clear error message during validation
    validator_cls.check_schema(schema)
    return validator_cls, schema


def _canonicalize_schema(schema: dict) -> str:
    """Create a canonical JSON string of a schema for use as a cache key.

    Args:
        schema: The JSON Schema dictionary.

    Returns:
        Canonical JSON string with sorted keys.
    """
    return orjson.dumps(schema, option=orjson.OPT_SORT_KEYS).decode()


def _validate_with_cached_schema(instance: Any, schema: dict) -> None:
    """Validate instance against schema using cached validator class.

    Creates a fresh validator instance for thread safety, but reuses
    the cached validator class and schema check. Uses best_match to
    preserve jsonschema.validate() error selection semantics.

    Args:
        instance: The data to validate.
        schema: The JSON Schema to validate against.

    Raises:
        error: The best matching ValidationError from jsonschema validation.
        jsonschema.exceptions.ValidationError: If validation fails.
        jsonschema.exceptions.SchemaError: If the schema itself is invalid.
    """
    schema_json = _canonicalize_schema(schema)
    validator_cls, checked_schema = _get_validator_class_and_check(schema_json)
    # Create fresh validator instance for thread safety
    validator = validator_cls(checked_schema)
    # Use best_match to match jsonschema.validate() error selection behavior
    error = jsonschema.exceptions.best_match(validator.iter_errors(instance))
    if error is not None:
        raise error


def extract_using_jq(data, jq_filter=""):
    """
    Extracts data from a given input (string, dict, or list) using a jq filter string.

    Uses cached compiled jq programs for performance.

    Args:
        data (str, dict, list): The input JSON data. Can be a string, dict, or list.
        jq_filter (str): The jq filter string to extract the desired data.

    Returns:
        The result of applying the jq filter to the input data.

    Examples:
        >>> extract_using_jq('{"a": 1, "b": 2}', '.a')
        [1]
        >>> extract_using_jq({'a': 1, 'b': 2}, '.b')
        [2]
        >>> extract_using_jq('[{"a": 1}, {"a": 2}]', '.[].a')
        [1, 2]
        >>> extract_using_jq('not a json', '.a')
        ['Invalid JSON string provided.']
        >>> extract_using_jq({'a': 1}, '')
        {'a': 1}
    """
    if not jq_filter or jq_filter == "":
        return data

    # Validate that jq_filter looks like a valid jq expression
    jq_filter_str = str(jq_filter).strip()
    if not jq_filter_str:
        return data

    # Check if it looks like an email address (common mistake when jsonpath_filter
    # field contains corrupted data). Intentionally simple regex to avoid false
    # positives with valid jq expressions like .foo|.bar
    if re.match(r"^[^.\[\]|]+@[^.\[\]|]+\.[^.\[\]|]+$", jq_filter_str):
        logger.warning(f"Invalid jq filter (email address): {jq_filter_str}. Treating as empty filter.")
        return data

    # Track if input was originally a string (for error handling)
    was_string = isinstance(data, str)

    if was_string:
        # If the input is a string, parse it as JSON
        try:
            data = orjson.loads(data)
        except orjson.JSONDecodeError:
            return ["Invalid JSON string provided."]
    elif not isinstance(data, (dict, list)):
        # If the input is not a string, dict, or list, raise an error
        return ["Input data must be a JSON string, dictionary, or list."]

    # Apply the jq filter to the data using cached compiled program
    try:
        program = _compile_jq_filter(jq_filter)
        result = program.input(data).all()
        if result == [None]:
            return [TextContent(type="text", text="Error applying jsonpath filter")]
    except Exception as e:
        message = "Error applying jsonpath filter: " + str(e)
        return [TextContent(type="text", text=message)]

    return result


_VALID_HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.0-9A-Z^_`a-z|~]+$")


_INVALID_HEADER_VALUE_CHARS = re.compile(r"[\r\n\x00]")


def _validate_mapping_contents(mapping: dict, label: str, tool_name: str) -> dict[str, str]:
    """Validate that a mapping dict contains only string keys and string values.

    Raises:
        ToolInvocationError: If the mapping contains non-string keys or values.
    """
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise ToolInvocationError(f"Tool '{tool_name}' has invalid {label}: non-string keys or values. Check the tool's {label} configuration.")
    return mapping


def _validate_header_mapping_targets(mapping: dict[str, str], tool_name: str) -> None:
    """Validate that header mapping target names are safe and well-formed.

    Raises:
        ToolInvocationError: If any target header name is sensitive or malformed.
    """
    for target_header in mapping.values():
        if _is_sensitive_tool_header_name(target_header):
            raise ToolInvocationError(f"header_mapping for tool '{tool_name}' targets sensitive header {repr(target_header[:64])}")
        if not _VALID_HTTP_HEADER_NAME.match(target_header):
            raise ToolInvocationError(f"header_mapping for tool '{tool_name}' contains invalid header name {repr(target_header[:64])}")


def apply_mapping_into_target(data_obj: dict, mapping_obj: dict | None, target_obj: dict | None = None) -> dict:
    """Map fields from data_obj whose keys appear in mapping_obj, renaming them per mapping_obj's values, and merge into target_obj.

    Only data_obj keys present in mapping_obj are included; unmapped keys are excluded from the result.
    If mapping_obj is None or empty, returns target_obj unchanged.
    If no target_obj is provided, an empty dict is used as the base.

    Args:
        data_obj: Source data whose keys may be mapped.
        mapping_obj: Key-renaming map (old_key -> new_key), or None/empty to skip mapping.
        target_obj: Base dict to merge mapped entries into. Mapped entries overwrite on collision.

    Returns:
        A new dict containing all entries from target_obj plus renamed entries from data_obj.
    """

    if target_obj is None:
        target_obj = {}

    if not mapping_obj:
        return target_obj

    if logger.isEnabledFor(logging.DEBUG):
        dropped = {k for k in data_obj if k not in mapping_obj}
        if dropped:
            structured_logger.log(level="DEBUG", message=f"apply_mapping_into_target: unmapped keys excluded: {sorted(dropped)}", component="tool_service")

    return {**target_obj, **{mapping_obj[k]: v for k, v in data_obj.items() if k in mapping_obj}}


class ToolError(Exception):
    """Base class for tool-related errors.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolError
        >>> err = ToolError("Something went wrong")
        >>> str(err)
        'Something went wrong'
    """


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolNotFoundError
        >>> err = ToolNotFoundError("Tool xyz not found")
        >>> str(err)
        'Tool xyz not found'
        >>> isinstance(err, ToolError)
        True
    """


class ToolNameConflictError(ToolError):
    """Raised when a tool name conflicts with existing (active or inactive) tool."""

    def __init__(self, name: str, enabled: bool = True, tool_id: Optional[int] = None, visibility: str = "public"):
        """Initialize the error with tool information.

        Args:
            name: The conflicting tool name.
            enabled: Whether the existing tool is enabled or not.
            tool_id: ID of the existing tool if available.
            visibility: The visibility of the tool ("public" or "team").

        Examples:
            >>> from mcpgateway.services.tool_service import ToolNameConflictError
            >>> err = ToolNameConflictError('test_tool', enabled=False, tool_id=123)
            >>> str(err)
            'Public Tool already exists with name: test_tool (currently inactive, ID: 123)'
            >>> err.name
            'test_tool'
            >>> err.enabled
            False
            >>> err.tool_id
            123
        """
        self.name = name
        self.enabled = enabled
        self.tool_id = tool_id
        if visibility == "team":
            vis_label = "Team-level"
        elif visibility == "private":
            vis_label = "Private"
        else:
            vis_label = "Public"
        message = f"{vis_label} Tool already exists with name: {name}"
        if not enabled:
            message += f" (currently inactive, ID: {tool_id})"
        super().__init__(message)


class ToolLockConflictError(ToolError):
    """Raised when a tool row is locked by another transaction."""


class ToolValidationError(ToolError):
    """Raised when tool validation fails.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolValidationError
        >>> err = ToolValidationError("Invalid tool configuration")
        >>> str(err)
        'Invalid tool configuration'
        >>> isinstance(err, ToolError)
        True
    """


class ToolInvocationError(ToolError):
    """Raised when tool invocation fails.

    Examples:
        >>> from mcpgateway.services.tool_service import ToolInvocationError
        >>> err = ToolInvocationError("Tool execution failed")
        >>> str(err)
        'Tool execution failed'
        >>> isinstance(err, ToolError)
        True
        >>> # Test with detailed error
        >>> detailed_err = ToolInvocationError("Network timeout after 30 seconds")
        >>> "timeout" in str(detailed_err)
        True
        >>> isinstance(err, ToolError)
        True
    """


class ToolTimeoutError(ToolInvocationError):
    """Raised when tool invocation times out.

    This subclass is used to distinguish timeout errors from other invocation errors.
    Timeout handlers call tool_post_invoke before raising this, so the generic exception
    handler should skip calling post_invoke again to avoid double-counting failures.

    Attributes:
        retry_delay_ms: Delay in milliseconds requested by the retry plugin.
            0 (default) means no retry.  Set by the timeout handler after
            invoking the post-invoke hook so the outer catch block can honour
            the signal without calling post_invoke a second time.
    """

    def __init__(self, message: str, retry_delay_ms: int = 0) -> None:
        """Initialise with an optional retry delay from the post-invoke hook.

        Args:
            message: Human-readable error description.
            retry_delay_ms: Milliseconds the gateway should wait before retrying.
        """
        super().__init__(message)
        self.retry_delay_ms = retry_delay_ms


def _coerce_retry_policy_int(raw_value: Any, *, default: int, minimum: int) -> int:
    """Normalize retry policy integer settings from plugin config."""
    if raw_value is None:
        return default
    value = int(raw_value)
    if value < minimum:
        raise ValueError(f"Retry policy integer must be >= {minimum}")
    return value


def _coerce_retry_policy_statuses(raw_value: Any) -> List[int]:
    """Normalize retryable status codes from plugin config."""
    if raw_value is None:
        return [429, 500, 502, 503, 504]
    if isinstance(raw_value, (str, bytes)) or not isinstance(raw_value, (list, tuple, set)):
        raise ValueError("Retry policy retry_on_status must be a sequence of integers")
    return [int(code) for code in raw_value]


def _coerce_retry_policy_bool(raw_value: Any, *, default: bool) -> bool:
    """Normalize retry policy booleans using explicit string parsing."""
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)) and raw_value in (0, 1):
        return bool(raw_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off"}:
            return False
    raise ValueError("Retry policy boolean must be a bool-like value")


def _build_retry_policy_config(raw_cfg: Optional[Dict[str, Any]], tool_name: str) -> Dict[str, Any]:
    """Build a gateway-owned retry policy view from plugin config."""
    cfg = raw_cfg or {}
    if not isinstance(cfg, dict):
        raise ValueError("Retry policy config must be a mapping")
    effective_cfg: Dict[str, Any] = {
        "max_retries": _coerce_retry_policy_int(cfg.get("max_retries"), default=2, minimum=0),
        "backoff_base_ms": _coerce_retry_policy_int(cfg.get("backoff_base_ms"), default=200, minimum=1),
        "max_backoff_ms": _coerce_retry_policy_int(cfg.get("max_backoff_ms"), default=5000, minimum=1),
        "retry_on_status": _coerce_retry_policy_statuses(cfg.get("retry_on_status")),
        "jitter": _coerce_retry_policy_bool(cfg.get("jitter"), default=True),
        "check_text_content": _coerce_retry_policy_bool(cfg.get("check_text_content"), default=False),
    }

    tool_overrides = cfg.get("tool_overrides") or {}
    if not isinstance(tool_overrides, dict):
        raise ValueError("Retry policy tool_overrides must be a mapping")

    overrides = tool_overrides.get(tool_name)
    if overrides:
        if not isinstance(overrides, dict):
            raise ValueError("Retry policy tool override must be a mapping")
        effective_cfg.update({key: value for key, value in overrides.items() if key in effective_cfg})
        effective_cfg["max_retries"] = _coerce_retry_policy_int(effective_cfg.get("max_retries"), default=2, minimum=0)
        effective_cfg["backoff_base_ms"] = _coerce_retry_policy_int(effective_cfg.get("backoff_base_ms"), default=200, minimum=1)
        effective_cfg["max_backoff_ms"] = _coerce_retry_policy_int(effective_cfg.get("max_backoff_ms"), default=5000, minimum=1)
        effective_cfg["retry_on_status"] = _coerce_retry_policy_statuses(effective_cfg.get("retry_on_status"))
        effective_cfg["jitter"] = _coerce_retry_policy_bool(effective_cfg.get("jitter"), default=True)
        effective_cfg["check_text_content"] = _coerce_retry_policy_bool(effective_cfg.get("check_text_content"), default=False)

    effective_cfg["max_retries"] = min(effective_cfg["max_retries"], settings.max_tool_retries)

    return effective_cfg


class ToolService(BaseService):
    """Service for managing and invoking tools.

    Handles:
    - Tool registration and deregistration.
    - Tool invocation and validation.
    - Tool federation.
    - Event notifications.
    - Active/inactive tool management.
    """

    _visibility_model_cls = DbTool

    def __init__(self) -> None:
        """Initialize the tool service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> isinstance(service._event_service, EventService)
            True
            >>> hasattr(service, '_http_client')
            True
        """
        self._event_service = EventService(channel_name="mcpgateway:tool_events")
        self._http_client = ResilientHttpClient(client_args={"timeout": settings.federation_timeout, "verify": not settings.skip_ssl_verify})
        self.oauth_manager = OAuthManager(
            request_timeout=int(settings.oauth_request_timeout if hasattr(settings, "oauth_request_timeout") else 30),
            max_retries=int(settings.oauth_max_retries if hasattr(settings, "oauth_max_retries") else 3),
        )
        self._content_security = ContentSecurityService()

    async def initialize(self) -> None:
        """Initialize the service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> import asyncio
            >>> asyncio.run(service.initialize())  # Should log "Initializing tool service"
        """
        logger.info("Initializing tool service")
        await self._event_service.initialize()

    async def shutdown(self) -> None:
        """Shutdown the service.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> import asyncio
            >>> asyncio.run(service.shutdown())  # Should log "Tool service shutdown complete"
        """
        await self._http_client.aclose()
        await self._event_service.shutdown()
        logger.info("Tool service shutdown complete")

    async def get_top_tools(self, db: Session, limit: Optional[int] = 5, include_deleted: bool = False) -> List[TopPerformer]:
        """Retrieve the top-performing tools based on execution count.

        Queries the database to get tools with their metrics, ordered by the number of executions
        in descending order. Returns a list of TopPerformer objects containing tool details and
        performance metrics. Results are cached for performance.

        Args:
            db (Session): Database session for querying tool metrics.
            limit (Optional[int]): Maximum number of tools to return. Defaults to 5.
            include_deleted (bool): Whether to include deleted tools from rollups.

        Returns:
            List[TopPerformer]: A list of TopPerformer objects, each containing:
                - id: Tool ID.
                - name: Tool name.
                - execution_count: Total number of executions.
                - avg_response_time: Average response time in seconds, or None if no metrics.
                - success_rate: Success rate percentage, or None if no metrics.
                - last_execution: Timestamp of the last execution, or None if no metrics.
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        effective_limit = limit or 5
        cache_key = f"top_tools:{effective_limit}:include_deleted={include_deleted}"

        if is_cache_enabled():
            cached = metrics_cache.get(cache_key)
            if cached is not None:
                return cached

        # Use combined query that includes both raw metrics and rollup data
        results = get_top_performers_combined(
            db,
            metric_type="tool",
            entity_model=DbTool,
            limit=effective_limit,
            include_deleted=include_deleted,
        )
        top_performers = build_top_performers(results)

        # Cache the result (if enabled)
        if is_cache_enabled():
            metrics_cache.set(cache_key, top_performers)

        return top_performers

    def _build_tool_cache_payload(self, tool: DbTool, gateway: Optional[DbGateway]) -> Dict[str, Any]:
        """Build cache payload for tool lookup by name.

        Args:
            tool: Tool ORM instance.
            gateway: Optional gateway ORM instance.

        Returns:
            Cache payload dict for tool lookup.
        """
        tool_payload = {
            "id": str(tool.id),
            "name": tool.name,
            "original_name": tool.original_name,
            "url": tool.url,
            "description": tool.description,
            "original_description": tool.original_description,
            "integration_type": tool.integration_type,
            "request_type": tool.request_type,
            "headers": tool.headers or {},
            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            "output_schema": tool.output_schema,
            "annotations": tool.annotations or {},
            "auth_type": tool.auth_type,
            "jsonpath_filter": tool.jsonpath_filter,
            "custom_name": tool.custom_name,
            "custom_name_slug": tool.custom_name_slug,
            "display_name": tool.display_name,
            "gateway_id": str(tool.gateway_id) if tool.gateway_id else None,
            "enabled": bool(tool.enabled),
            "reachable": bool(tool.reachable),
            "tags": tool.tags or [],
            "team_id": tool.team_id,
            "owner_email": tool.owner_email,
            "visibility": tool.visibility,
            "query_mapping": tool.query_mapping,
            "header_mapping": tool.header_mapping,
        }

        gateway_payload = None
        if gateway:
            gateway_payload = {
                "id": str(gateway.id),
                "name": gateway.name,
                "url": gateway.url,
                "description": gateway.description,
                "slug": gateway.slug,
                "transport": gateway.transport,
                "capabilities": gateway.capabilities or {},
                "passthrough_headers": gateway.passthrough_headers or [],
                "auth_type": gateway.auth_type,
                "ca_certificate": getattr(gateway, "ca_certificate", None),
                "ca_certificate_sig": getattr(gateway, "ca_certificate_sig", None),
                "enabled": bool(gateway.enabled),
                "reachable": bool(gateway.reachable),
                "team_id": gateway.team_id,
                "owner_email": gateway.owner_email,
                "visibility": gateway.visibility,
                "tags": gateway.tags or [],
                "gateway_mode": getattr(gateway, "gateway_mode", "cache"),  # Gateway mode for direct proxy support
                "client_cert": getattr(gateway, "client_cert", None),
                "client_key": getattr(gateway, "client_key", None),
            }

        return {"status": "active", "tool": tool_payload, "gateway": gateway_payload}

    def _pydantic_tool_from_payload(self, tool_payload: Dict[str, Any]) -> Optional[PydanticTool]:
        """Build Pydantic tool metadata from cache payload.

        Args:
            tool_payload: Cached tool payload dict.

        Returns:
            Pydantic tool metadata or None if validation fails.
        """
        try:
            return PydanticTool.model_validate(tool_payload)
        except Exception as exc:
            logger.debug("Failed to build PydanticTool from cache payload: %s", exc)
            return None

    def _pydantic_gateway_from_payload(self, gateway_payload: Dict[str, Any]) -> Optional[PydanticGateway]:
        """Build Pydantic gateway metadata from cache payload.

        Args:
            gateway_payload: Cached gateway payload dict.

        Returns:
            Pydantic gateway metadata or None if validation fails.
        """
        try:
            return PydanticGateway.model_validate(gateway_payload)
        except Exception as exc:
            logger.debug("Failed to build PydanticGateway from cache payload: %s", exc)
            return None

    async def _check_tool_access(
        self,
        db: Session,
        tool_payload: Dict[str, Any],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
    ) -> bool:
        """Check if user has access to a tool based on visibility rules.

        Implements the same access control logic as list_tools() for consistency.

        Access Rules:
        - Public tools: Accessible by all authenticated users
        - Team tools: Accessible by team members (team_id in user's teams)
        - Private tools: Accessible only by owner (owner_email matches)

        Args:
            db: Database session for team membership lookup if needed.
            tool_payload: Tool data dict with visibility, team_id, owner_email.
            user_email: Email of the requesting user (None = unauthenticated).
            token_teams: List of team IDs from token.
                - None = unrestricted admin access
                - [] = public-only token
                - [...] = team-scoped token

        Returns:
            True if access is allowed, False otherwise.
        """
        visibility = tool_payload.get("visibility", "public")
        tool_team_id = tool_payload.get("team_id")
        tool_owner_email = tool_payload.get("owner_email")

        # Public tools are accessible by everyone
        if visibility == "public":
            return True

        # Admin bypass (PR #4341 invariant): never reveal another user's private rows.
        # Anonymous bypass sees public + team only; a DB-resolved admin session
        # additionally sees their own private rows. Matches a2a_service._visible_agent_ids.
        if token_teams is None and user_email is None:
            return visibility != "private"
        if token_teams is None and user_email and is_user_admin(db, user_email):
            return visibility != "private" or tool_owner_email == user_email

        # No user context (but not admin) = deny access to non-public tools
        if not user_email:
            return False

        # Public-only tokens (empty teams array) can ONLY access public tools
        is_public_only_token = token_teams is not None and len(token_teams) == 0
        if is_public_only_token:
            return False  # Already checked public above

        # Owner can access their own private tools
        if visibility == "private" and tool_owner_email and tool_owner_email == user_email:
            return True

        # Team tools: check team membership (matches list_tools behavior)
        if tool_team_id:
            # Use token_teams if provided, otherwise look up from DB
            if token_teams is not None:
                team_ids = token_teams
            else:
                team_service = TeamManagementService(db)
                user_teams = await team_service.get_user_teams(user_email)
                team_ids = [team.id for team in user_teams]

            # Team/public visibility allows access if user is in the team
            if visibility in ["team", "public"] and tool_team_id in team_ids:
                return True

        return False

    def convert_tool_to_read(
        self,
        tool: DbTool,
        include_metrics: bool = False,
        include_auth: bool = True,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> ToolRead:
        """Converts a DbTool instance into a ToolRead model, including aggregated metrics and
        new API gateway fields: request_type and authentication credentials (masked).

        Args:
            tool (DbTool): The ORM instance of the tool.
            include_metrics (bool): Whether to include metrics in the result. Defaults to False.
            include_auth (bool): Whether to decode and include auth details. Defaults to True.
                When False, skips expensive AES-GCM decryption and returns minimal auth info.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

        Returns:
            ToolRead: The Pydantic model representing the tool, including aggregated metrics and new fields.
        """
        # NOTE: This serves two purposes:
        #   1. It determines whether to decode auth (used later)
        #   2. It forces the tool object to lazily evaluate (required before copy)
        has_encrypted_auth = tool.auth_type and tool.auth_value

        # Copy the dict from the tool
        tool_dict = tool.__dict__.copy()
        tool_dict.pop("_sa_instance_state", None)

        # Compute metrics in a single pass (matches server/resource/prompt service pattern)
        if include_metrics:
            metrics = tool.metrics_summary  # Single-pass computation
            tool_dict["metrics"] = metrics
            tool_dict["execution_count"] = metrics["total_executions"]
        else:
            tool_dict["metrics"] = None
            tool_dict["execution_count"] = None

        tool_dict["request_type"] = tool.request_type
        tool_dict["annotations"] = tool.annotations or {}

        # Only decode auth if include_auth=True AND we have encrypted credentials
        if include_auth and has_encrypted_auth:
            decoded_auth_value = decode_auth(tool.auth_value)
            if tool.auth_type == "basic":
                decoded_bytes = base64.b64decode(decoded_auth_value["Authorization"].split("Basic ")[1])
                username, password = decoded_bytes.decode("utf-8").split(":")
                tool_dict["auth"] = {
                    "auth_type": "basic",
                    "username": username,
                    "password": settings.masked_auth_value if password else None,
                }
            elif tool.auth_type == "bearer":
                tool_dict["auth"] = {
                    "auth_type": "bearer",
                    "token": settings.masked_auth_value if decoded_auth_value["Authorization"] else None,
                }
            elif tool.auth_type == "authheaders":
                # Support multi-header format (list of {key, value} dicts)
                if decoded_auth_value:
                    # Convert decoded dict to list format for frontend
                    auth_headers = [
                        {
                            "key": key,
                            "value": settings.masked_auth_value if value else None,
                        }
                        for key, value in decoded_auth_value.items()
                    ]
                    # Also include legacy single-header fields for backward compatibility
                    first_key = next(iter(decoded_auth_value))
                    tool_dict["auth"] = {
                        "auth_type": "authheaders",
                        "authHeaders": auth_headers,  # Multi-header format (masked)
                        "auth_header_key": first_key,  # Legacy format
                        "auth_header_value": settings.masked_auth_value if decoded_auth_value[first_key] else None,  # Legacy format
                    }
                else:
                    tool_dict["auth"] = None
            else:
                tool_dict["auth"] = None
        elif not include_auth and has_encrypted_auth:
            # LIST VIEW: Minimal auth info without decryption
            # Only show auth_type for tools that have encrypted credentials
            tool_dict["auth"] = {"auth_type": tool.auth_type}
        else:
            # No encrypted auth (includes OAuth tools where auth_value=None)
            # Behavior unchanged from current implementation
            tool_dict["auth"] = None

        tool_dict["name"] = tool.name
        # Handle displayName with fallback and None checks
        display_name = getattr(tool, "display_name", None)
        custom_name = getattr(tool, "custom_name", tool.original_name)
        tool_dict["displayName"] = display_name or custom_name
        tool_dict["custom_name"] = custom_name
        tool_dict["gateway_slug"] = getattr(tool, "gateway_slug", "") or ""
        tool_dict["custom_name_slug"] = getattr(tool, "custom_name_slug", "") or ""
        tool_dict["tags"] = getattr(tool, "tags", []) or []
        tool_dict["team"] = getattr(tool, "team", None)

        # Mask custom headers unless the requester is allowed to modify this tool.
        # Safe default: if no requester context is provided, mask everything.
        headers = tool_dict.get("headers")
        if headers:
            tool_dict["headers"] = _decrypt_tool_headers_for_runtime(headers)
            headers = tool_dict["headers"]
            can_view = requesting_user_is_admin
            if not can_view and getattr(tool, "owner_email", None) == requesting_user_email:
                can_view = True
            if (
                not can_view
                and getattr(tool, "visibility", None) == "team"
                and getattr(tool, "team_id", None) is not None
                and requesting_user_team_roles
                and requesting_user_team_roles.get(str(tool.team_id)) == "owner"
            ):
                can_view = True
            if not can_view:
                tool_dict["headers"] = {k: settings.masked_auth_value for k in headers}

        return ToolRead.model_validate(tool_dict)

    async def _record_tool_metric(self, db: Session, tool: DbTool, start_time: float, success: bool, error_message: Optional[str]) -> None:
        """
        Records a metric for a tool invocation.

        This function calculates the response time using the provided start time and records
        the metric details (including whether the invocation was successful and any error message)
        into the database. The metric is then committed to the database.

        Args:
            db (Session): The SQLAlchemy database session.
            tool (DbTool): The tool that was invoked.
            start_time (float): The monotonic start time of the invocation.
            success (bool): True if the invocation succeeded; otherwise, False.
            error_message (Optional[str]): The error message if the invocation failed, otherwise None.
        """
        end_time = time.monotonic()
        response_time = end_time - start_time
        metric = ToolMetric(
            tool_id=tool.id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    def _record_tool_metric_by_id(
        self,
        db: Session,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Record tool metric using tool ID instead of ORM object.

        This method is designed to be used with a fresh database session after the main
        request session has been released. It avoids requiring the ORM tool object,
        which may have been detached from the session.

        Args:
            db: A fresh database session (not the request session).
            tool_id: The UUID string of the tool.
            start_time: The monotonic start time of the invocation.
            success: True if the invocation succeeded; otherwise, False.
            error_message: The error message if the invocation failed, otherwise None.
        """
        end_time = time.monotonic()
        response_time = end_time - start_time
        metric = ToolMetric(
            tool_id=tool_id,
            response_time=response_time,
            is_success=success,
            error_message=error_message,
        )
        db.add(metric)
        db.commit()

    def _record_tool_metric_sync(
        self,
        tool_id: str,
        start_time: float,
        success: bool,
        error_message: Optional[str],
    ) -> None:
        """Synchronous helper to record tool metrics with its own session.

        This method creates a fresh database session, records the metric, and closes
        the session. Designed to be called via asyncio.to_thread() to avoid blocking
        the event loop.

        Args:
            tool_id: The UUID string of the tool.
            start_time: The monotonic start time of the invocation.
            success: True if the invocation succeeded; otherwise, False.
            error_message: The error message if the invocation failed, otherwise None.
        """
        with fresh_db_session() as db_metrics:
            self._record_tool_metric_by_id(
                db_metrics,
                tool_id=tool_id,
                start_time=start_time,
                success=success,
                error_message=error_message,
            )

    def _extract_and_validate_structured_content(self, tool: DbTool, tool_result: "ToolResult") -> bool:
        """
        Extract structured content (if any) and validate it against ``tool.output_schema``.

        This method is one of **three** output-schema validation layers the
        gateway relies on. Understanding where each fires — and, crucially,
        where each is *skipped* — is essential when reasoning about
        ContextForge #4202 (https://github.com/IBM/mcp-context-forge/issues/4202)
        and its successors. See
        ``docs/docs/architecture/tool-invocation-and-validation.md`` for the
        full flow diagram; a summary follows.

        Tool invocation flow (downstream client → gateway → upstream tool → back):

        1. **Downstream ingress (server SDK, inbound request)** — not a
           validator; just decodes the ``tools/call`` JSON-RPC into
           ``CallToolRequestParam`` and dispatches to the gateway's
           handler at
           ``mcpgateway/transports/streamablehttp_transport.py::call_tool``.

        2. **Gateway dispatch** — ``call_tool`` routes based on the tool's
           ``integration_type`` in the DB. Federation-backed MCP tools take
           the MCP client SDK path (step 3). REST, OpenAPI, A2A and
           admin-registered tools take the direct HTTP path (step 4).

        3. **Validator A — MCP Python client SDK (federation only)**.
           Upstream MCP calls go through ``mcp.ClientSession``, whose
           ``ClientSession._validate_tool_result`` in the installed
           ``mcp`` package
           validates ``structuredContent`` against the *upstream-advertised*
           output schema. Rules: (a) **skipped when ``isError=True``** —
           this is what the MCP spec's "Error Handling" section mandates,
           and why #4202 only surfaced on the gateway's own layer;
           (b) raises ``RuntimeError`` on violation, which the gateway
           catches at ``tool_service.py::invoke_tool`` and re-wraps as a
           ``Tool invocation failed: ...`` error.

        4. **Validator B — this method, ``_extract_and_validate_structured_content``**.
           Currently invoked **only** from the REST branch of
           ``invoke_tool`` (search for ``_extract_and_validate_structured_content(``).
           The MCP federation branch relies on Validator A; the A2A
           branch has **no gateway-side output-schema enforcement today**
           — a known gap tracked alongside the option-B pipeline unification
           refactor (see the issue below). Rules when Validator B does run:
           - Skip when ``is_error=True`` or ``isError=True`` — the
             ContextForge #4202 fix. Without this early return the gateway
             would clobber the upstream's original error message with a
             schema-mismatch dict.
           - Require ``structured_content`` to be a JSON object when
             explicitly set; reject lists, scalars and other shapes with a
             structured ``invalid_structured_content_type`` error (per MCP
             2025-11-25 "Output Schema").
           - Otherwise best-effort promote the first parseable
             ``TextContent`` item to ``structured_content`` (tolerates
             both dict and Pydantic shapes, which matters because
             ``_coerce_to_tool_result`` wraps REST JSON bodies into
             Pydantic ``TextContent``).
           - When no schema is declared, or no structured data can be
             obtained and ``is_error=False``, return ``True`` — currently a
             *lenient* deviation from the spec's "servers MUST provide
             conforming structured output" rule, tracked in
             https://github.com/IBM/mcp-context-forge/issues/4208.
           - On schema violation, mutate ``tool_result`` in place:
             replace ``content`` with a deterministic validation-error
             TextContent and set ``is_error=True``.

        5. **Validator C — MCP Python server SDK (downstream egress)**.
           The gateway's ``call_tool`` handler in
           ``mcpgateway/transports/streamablehttp_transport.py`` returns
           either a raw ``list``/``tuple`` shape (success path) or a
           fully-formed ``types.CallToolResult`` (``isError=True`` path).
           The server SDK (``mcp.server.lowlevel.server``)
           validates the list/tuple shape against the gateway's *own*
           advertised output schema, but **short-circuits when the
           handler returns a ``CallToolResult`` directly** (via the
           ``isinstance(results, types.CallToolResult)`` check in its
           ``_call_tool`` dispatch). We
           exploit that short-circuit to preserve #4202 on the egress —
           otherwise the server SDK's "Output validation error:
           outputSchema defined but no structured output returned" message
           would re-clobber the payload after Validator B had correctly
           preserved it.

        Net effect across paths:

        - MCP-federated tool, success: Validators A + C both run; this
          method does not.
        - MCP-federated tool, error (``isError=True``): Validators A and C
          both skip; this method does not run (no ingress invocation for
          MCP branch).
        - **REST** (incl. OpenAPI-imported) tool, success: this method
          runs (B); Validator C runs on the way out.
        - **REST** tool, error: this method skips (B early-return per
          #4202); Validator C short-circuits because the egress handler
          returns ``CallToolResult``.
        - **A2A** tool, any outcome: this method is **not invoked**
          today; Validator C runs (success) or short-circuits (error).
          Wiring A2A through the unified post-invoke pipeline is part of
          the option-B refactor and the A2A-specific validation gap.

        End-to-end coverage for non-MCP paths (REST/OpenAPI/A2A) is
        tracked in https://github.com/IBM/mcp-context-forge/issues/4207.
        The A2A Validator B gap and the broader "single post-invoke
        pipeline" refactor (option B) are tracked as a separate chore
        issue — see ``docs/docs/architecture/tool-invocation-and-validation.md``
        for the current per-path table.

        Args:
            tool: The tool with an optional output schema to validate against.
            tool_result: The tool result containing content to validate.

        Behavior:
        - Per MCP specification, validation is skipped for error responses (isError: true).
          Error responses with isError=true do not require structured content.
        - When ``tool_result.structured_content`` is present it must be a JSON object and is used as the structured payload.
        - Otherwise the method will try to parse the first ``TextContent`` item in
            ``tool_result.content`` as JSON and use that as the candidate.
        - If no output schema is declared on the tool the method returns True (nothing to validate).
        - On successful validation the parsed value is attached to ``tool_result.structured_content``.
            When structured content is present and valid callers may drop textual ``content`` in favour
            of the structured payload.
        - On validation failure the method sets ``tool_result.content`` to a single ``TextContent``
            containing a compact JSON object describing the validation error, sets
            ``tool_result.is_error = True`` and returns False.

        Returns:
                True when the structured content is valid or when no schema is declared.
                False when validation fails.

        Examples:
                >>> from mcpgateway.services.tool_service import ToolService
                >>> from mcpgateway.common.models import TextContent, ToolResult
                >>> import json
                >>> service = ToolService()
                >>> # No schema declared -> nothing to validate
                >>> tool = type("T", (object,), {"output_schema": None})()
                >>> r = ToolResult(content=[TextContent(type="text", text='{"a":1}')])
                >>> service._extract_and_validate_structured_content(tool, r)
                True

                >>> # Valid candidate provided -> attaches structured_content and returns True
                >>> tool = type(
                ...     "T",
                ...     (object,),
                ...     {"output_schema": {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}},
                ... )()
                >>> r = ToolResult(content=[])
                >>> r = ToolResult(content=[], structured_content={"foo": "bar"})
                >>> service._extract_and_validate_structured_content(tool, r)
                True
                >>> r.structured_content == {"foo": "bar"}
                True

                >>> # Invalid candidate -> returns False, marks result as error and emits details
                >>> tool = type(
                ...     "T",
                ...     (object,),
                ...     {"output_schema": {"type": "object", "properties": {"foo": {"type": "string"}}, "required": ["foo"]}},
                ... )()
                >>> r = ToolResult(content=[])
                >>> r = ToolResult(content=[], structured_content={"foo": 123})
                >>> ok = service._extract_and_validate_structured_content(tool, r)
                >>> ok
                False
                >>> r.is_error
                True
                >>> details = orjson.loads(r.content[0].text)
                >>> "received" in details
                True
        """
        try:
            # Error responses do not require structured content per MCP spec:
            # https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling
            is_error = getattr(tool_result, "is_error", False) or getattr(tool_result, "isError", False)
            if is_error:
                # Lazy %-formatting + SecurityValidator.sanitize_log_message to
                # prevent log injection via tool names containing control
                # characters. ``or "<unknown>"`` guards against explicit
                # ``tool.name = None`` on partially-hydrated ORM rows — plain
                # ``getattr(..., "<unknown>")`` would return ``None`` and the
                # sanitizer would collapse it to an empty string, losing the
                # diagnostic signal.
                logger.debug(
                    "Skipping output schema validation for error response from tool %s",
                    SecurityValidator.sanitize_log_message(getattr(tool, "name", None) or "<unknown>"),
                )
                return True

            output_schema = getattr(tool, "output_schema", None)
            # Nothing to do if the tool doesn't declare a schema
            if not output_schema:
                return True

            structured: Optional[Any] = None
            # Prefer normalized structured content already attached to the result
            structured = getattr(tool_result, "structured_content", None)
            if structured is None:
                structured = getattr(tool_result, "structuredContent", None)

            if structured is not None and not isinstance(structured, dict):
                details = {
                    "code": "invalid_structured_content_type",
                    "expected": "object",
                    "received": type(structured).__name__.lower(),
                    "path": [],
                    "message": "structured_content must be a JSON object",
                }
                try:
                    tool_result.content = [TextContent(type="text", text=orjson.dumps(details).decode())]
                except Exception:
                    tool_result.content = [TextContent(type="text", text=str(details))]
                tool_result.is_error = True
                return False

            if structured is None:
                # Try to parse first TextContent text payload as JSON. Content
                # items may be raw dicts (MCP wire shape) or pydantic objects
                # (e.g. TextContent synthesized by _coerce_to_tool_result
                # for REST responses); support both.
                for c in getattr(tool_result, "content", []) or []:
                    try:
                        c_type = c.get("type") if isinstance(c, dict) else getattr(c, "type", None)
                        c_text = c.get("text") if isinstance(c, dict) else getattr(c, "text", None)
                        if c_type == "text" and c_text is not None:
                            structured = orjson.loads(c_text)
                            break
                    except (orjson.JSONDecodeError, TypeError, ValueError):
                        # ignore JSON parse errors and continue
                        continue

            # If no structured data found, treat as valid (nothing to validate)
            if structured is None:
                return True

            # Attach structured content. A frozen or slotted ``tool_result``
            # that refuses the assignment is a genuine contract violation —
            # downstream code relies on ``structured_content`` being
            # populated — so surface at WARNING with a stack trace rather
            # than swallowing silently at DEBUG.
            try:
                setattr(tool_result, "structured_content", structured)
            except Exception:
                logger.warning(
                    "Failed to set structured_content on ToolResult for tool %s",
                    SecurityValidator.sanitize_log_message(getattr(tool, "name", None) or "<unknown>"),
                    exc_info=True,
                )

            # Validate using cached schema validator
            try:
                _validate_with_cached_schema(structured, output_schema)
                return True
            except jsonschema.exceptions.ValidationError as e:
                details = {
                    "code": getattr(e, "validator", "validation_error"),
                    "expected": e.schema.get("type") if isinstance(e.schema, dict) and "type" in e.schema else None,
                    "received": type(e.instance).__name__.lower() if e.instance is not None else None,
                    "path": list(e.absolute_path) if hasattr(e, "absolute_path") else list(e.path or []),
                    "message": e.message,
                }
                try:
                    tool_result.content = [TextContent(type="text", text=orjson.dumps(details).decode())]
                except Exception:
                    tool_result.content = [TextContent(type="text", text=str(details))]
                tool_result.is_error = True
                logger.debug(
                    "structured_content validation failed for tool %s: %s",
                    SecurityValidator.sanitize_log_message(getattr(tool, "name", None) or "<unknown>"),
                    details,
                )
                return False
        except Exception as exc:  # pragma: no cover - defensive
            # Defensive catch for unexpected validator failures (schema
            # compilation crash, attribute errors on malformed ``tool_result``,
            # orjson edge cases). Log with exc_info=True so the stack trace
            # reaches ops — without it, the method just returns False with no
            # diagnostic trail, which is a six-months-from-now debugging
            # nightmare.
            logger.error(
                "Error extracting/validating structured_content for tool %s: %s",
                SecurityValidator.sanitize_log_message(getattr(tool, "name", None) or "<unknown>"),
                exc,
                exc_info=True,
            )
            return False

    def _coerce_to_tool_result(self, payload: Any) -> ToolResult:
        """Coerce any tool-result-shaped payload into the gateway's canonical ``ToolResult``.

        Single source of truth for turning heterogeneous upstream
        responses into one canonical internal type. Funnelling every
        integration branch through here gives us uniform ``is_error`` and
        ``structured_content`` semantics regardless of source, which is
        the foundation of #4202's fix across multiple integration types
        (see https://github.com/IBM/mcp-context-forge/issues/4202) and
        the first structural step toward the option-B "single
        canonical-ToolResult pipeline" refactor tracked separately.

        Accepted inputs:

        - ``ToolResult`` → returned as-is (fast path).
        - MCP SDK ``CallToolResult`` (or any other Pydantic model whose
          ``model_dump(by_alias=True)`` emits an MCP-shaped envelope) →
          round-tripped through ``ToolResult.model_validate`` so
          camelCase ``isError`` / ``structuredContent`` map cleanly onto
          the gateway's snake-cased aliases. This path is what closes the
          direct-proxy egress regression Codex flagged: previously the
          egress ``is_error`` check only recognised snake-case and
          silently re-clobbered error responses coming back from
          ``session.call_tool(...)``.
        - A raw dict that looks *strongly* like an MCP envelope —
          presence of ``isError`` / ``is_error`` / ``structuredContent`` /
          ``structured_content`` keys, or a ``content`` list whose items
          carry a string ``type`` field (i.e. MCP ``ContentBlock`` shape).
          A dict with merely a top-level ``content`` key is **not**
          enough: a REST business payload like
          ``{"content": [{"widget": "x"}], "recognitionId": "rec-1"}``
          must not be reinterpreted as an MCP envelope with its sibling
          fields silently discarded (Codex P2).
        - Anything else → JSON-serialised into a single ``TextContent``.

        Args:
            payload: The upstream response in whatever shape the
                integration branch happens to produce.

        Returns:
            A canonical ``ToolResult`` instance.
        """
        # Fast path — already canonical.
        if isinstance(payload, ToolResult):
            return payload

        # MCP SDK CallToolResult (or any Pydantic model exposing
        # MCP-shaped fields via by-alias dump). The MCP SDK emits
        # ``isError`` / ``structuredContent`` in camelCase; our
        # ``ToolResult`` declares those as aliases, so the dump feeds
        # straight into ``model_validate`` without a bespoke mapper.
        if isinstance(payload, BaseModel) and hasattr(payload, "content"):
            try:
                return ToolResult.model_validate(payload.model_dump(by_alias=True, mode="json"))
            except ValidationError:
                # User-visible reshape: an MCP-looking Pydantic upstream
                # result is about to be downgraded to an opaque text blob.
                # Log at WARNING so operators notice protocol or schema
                # drift between the gateway and the upstream SDK.
                logger.warning(
                    "%s did not validate as ToolResult; falling back to text serialisation",
                    type(payload).__name__,
                    exc_info=True,
                )

        # Raw dict — only treat as MCP-shaped when strong markers are
        # present. Without this guard a REST payload that coincidentally
        # contains a top-level ``content`` field would be misread as an
        # MCP envelope and its sibling business fields silently dropped
        # (Codex P2 regression).
        if isinstance(payload, dict) and _looks_like_mcp_envelope(payload):
            try:
                return ToolResult.model_validate(payload)
            except ValidationError:
                # User-visible reshape: the heuristic admitted a dict as
                # an MCP envelope but the strict ToolResult model then
                # rejected it. Surface at WARNING so the non-conforming
                # upstream gets flagged in ops logs rather than silently
                # downgraded to text.
                logger.warning(
                    "Dict payload matched MCP-envelope heuristics but failed ToolResult validation; falling back to text serialisation",
                    exc_info=True,
                )

        # Last resort — opaque JSON body. Preserves the payload for the
        # caller to inspect while keeping the rest of the pipeline on a
        # uniform ``ToolResult`` contract. The helper's invariant is
        # "always returns a valid ``ToolResult``, never raises", so every
        # step below must be guarded — both ``BaseModel.model_dump`` and
        # ``orjson.dumps`` can raise on pathological inputs (custom
        # serialisers that throw, ``PydanticSerializationError`` —
        # ``ValueError`` subclass, not ``TypeError`` — fields holding
        # non-representable objects), and even ``str()`` / ``repr()`` /
        # ``type().__name__`` can fail on sufficiently broken proxy
        # objects.
        payload_type = _safe_type_name(payload)
        logger.debug("Coercing %s payload to opaque text content", payload_type)
        try:
            serializable_payload = payload.model_dump(mode="json", by_alias=True) if isinstance(payload, BaseModel) else payload
            serialized = orjson.dumps(serializable_payload, option=orjson.OPT_INDENT_2)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Payload of type %s could not be JSON-serialised; using textual fallback",
                payload_type,
                exc_info=True,
            )
            return ToolResult(content=[TextContent(type="text", text=_safe_text_repr(payload, payload_type))])
        return ToolResult(content=[TextContent(type="text", text=serialized.decode())])

    async def register_tool(
        self,
        db: Session,
        tool: ToolCreate,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: str = None,
    ) -> ToolRead:
        """Register a new tool with team support.

        Args:
            db: Database session.
            tool: Tool creation schema.
            created_by: Username who created this tool.
            created_from_ip: IP address of creator.
            created_via: Creation method (ui, api, import, federation).
            created_user_agent: User agent of creation request.
            import_batch_id: UUID for bulk import operations.
            federation_source: Source gateway for federated tools.
            team_id: Optional team ID to assign tool to.
            owner_email: Optional owner email for tool ownership.
            visibility: Tool visibility (private, team, public).

        Returns:
            Created tool information.

        Raises:
            IntegrityError: If there is a database integrity error.
            ToolNameConflictError: If a tool with the same name and visibility public exists.
            ToolError: For other tool registration errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> tool.name = 'test'
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> mock_gateway = MagicMock()
            >>> mock_gateway.name = 'test_gateway'
            >>> db.add = MagicMock()
            >>> db.commit = MagicMock()
            >>> def mock_refresh(obj):
            ...     obj.gateway = mock_gateway
            >>> db.refresh = MagicMock(side_effect=mock_refresh)
            >>> service._notify_tool_added = AsyncMock()
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.register_tool(db, tool))
            'tool_read'
        """
        try:
            if tool.auth is None:
                auth_type = None
                auth_value = None
            else:
                auth_type = tool.auth.auth_type
                auth_value = tool.auth.auth_value

            if team_id is None:
                team_id = tool.team_id

            if owner_email is None:
                owner_email = tool.owner_email

            if visibility is None:
                visibility = tool.visibility or "public"

            # Validate tool content for malicious patterns (CWE-20 fix - Issue #6)
            # Scan tool name, description, and inputSchema
            # Convert to string to handle both string and non-string inputs
            if tool.name:
                self._content_security.detect_malicious_patterns(
                    content=str(tool.name),
                    content_type="Tool name",
                    user_email=owner_email or created_by,
                    ip_address=created_from_ip,
                )
            if tool.description:
                self._content_security.detect_malicious_patterns(
                    content=str(tool.description),
                    content_type="Tool description",
                    user_email=owner_email or created_by,
                    ip_address=created_from_ip,
                )
            if tool.input_schema:
                # Convert inputSchema to string for pattern scanning
                # Handle both dict objects and test mocks gracefully
                try:
                    schema_str = orjson.dumps(tool.input_schema).decode()
                    self._content_security.detect_malicious_patterns(
                        content=schema_str,
                        content_type="Tool inputSchema",
                        user_email=owner_email or created_by,
                        ip_address=created_from_ip,
                    )
                except (TypeError, ValueError):
                    # Skip validation if schema is not JSON-serializable (e.g., test mocks)
                    pass

            # Check for existing tool with the same name and visibility
            if visibility.lower() == "public":
                # Check for existing public tool with the same name
                existing_tool = db.execute(select(DbTool).where(DbTool.name == tool.name, DbTool.visibility == "public")).scalar_one_or_none()  # pylint: disable=comparison-with-callable
                if existing_tool:
                    raise ToolNameConflictError(existing_tool.name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)
            elif visibility.lower() == "team" and team_id:
                # Check for existing team tool with the same name, team_id
                existing_tool = db.execute(
                    select(DbTool).where(DbTool.name == tool.name, DbTool.visibility == "team", DbTool.team_id == team_id)  # pylint: disable=comparison-with-callable
                ).scalar_one_or_none()
                if existing_tool:
                    raise ToolNameConflictError(existing_tool.name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)

            db_tool = DbTool(
                original_name=tool.name,
                custom_name=tool.name,
                custom_name_slug=slugify(tool.name),
                display_name=tool.displayName or tool.name,
                title=tool.title,
                url=str(tool.url),
                description=tool.description,
                original_description=tool.description,
                integration_type=tool.integration_type,
                request_type=tool.request_type,
                headers=_protect_tool_headers_for_storage(tool.headers),
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                annotations=tool.annotations,
                jsonpath_filter=tool.jsonpath_filter,
                auth_type=auth_type,
                auth_value=auth_value,
                gateway_id=tool.gateway_id,
                tags=tool.tags or [],
                # Metadata fields
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
                version=1,
                # Team scoping fields
                team_id=team_id,
                owner_email=owner_email or created_by,
                visibility=visibility,
                # passthrough REST tools fields
                base_url=tool.base_url if tool.integration_type == "REST" else None,
                path_template=tool.path_template if tool.integration_type == "REST" else None,
                query_mapping=tool.query_mapping if tool.integration_type == "REST" else None,
                header_mapping=tool.header_mapping if tool.integration_type == "REST" else None,
                timeout_ms=tool.timeout_ms if tool.integration_type == "REST" else None,
                expose_passthrough=(tool.expose_passthrough if tool.integration_type == "REST" and tool.expose_passthrough is not None else True) if tool.integration_type == "REST" else None,
                allowlist=tool.allowlist if tool.integration_type == "REST" else None,
                plugin_chain_pre=tool.plugin_chain_pre if tool.integration_type == "REST" else None,
                plugin_chain_post=tool.plugin_chain_post if tool.integration_type == "REST" else None,
            )
            db.add(db_tool)
            db.commit()
            db.refresh(db_tool)
            await self._notify_tool_added(db_tool)

            # Structured logging: Audit trail for tool creation
            audit_trail.log_action(
                user_id=created_by or "system",
                action="create_tool",
                resource_type="tool",
                resource_id=db_tool.id,
                resource_name=db_tool.name,
                user_email=owner_email,
                team_id=team_id,
                client_ip=created_from_ip,
                user_agent=created_user_agent,
                new_values={
                    "name": db_tool.name,
                    "display_name": db_tool.display_name,
                    "visibility": visibility,
                    "integration_type": db_tool.integration_type,
                },
                context={
                    "created_via": created_via,
                    "import_batch_id": import_batch_id,
                    "federation_source": federation_source,
                },
                db=db,
            )

            # Structured logging: Log successful tool creation
            structured_logger.log(
                level="INFO",
                message="Tool created successfully",
                event_type="tool_created",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                team_id=team_id,
                resource_type="tool",
                resource_id=db_tool.id,
                custom_fields={
                    "tool_name": db_tool.name,
                    "visibility": visibility,
                    "integration_type": db_tool.integration_type,
                },
            )

            # Refresh db_tool after logging commits (they expire the session objects)
            db.refresh(db_tool)

            # Invalidate cache after successful creation
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(db_tool.name, gateway_id=str(db_tool.gateway_id) if db_tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return self.convert_tool_to_read(db_tool, requesting_user_email=getattr(db_tool, "owner_email", None))
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityError during tool registration: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Tool creation failed due to database integrity error",
                event_type="tool_creation_failed",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                error=ie,
                custom_fields={
                    "tool_name": tool.name,
                },
            )
            raise ie
        except ToolNameConflictError as tnce:
            db.rollback()
            logger.error(f"ToolNameConflictError during tool registration: {tnce}")

            # Structured logging: Log name conflict error
            structured_logger.log(
                level="WARNING",
                message="Tool creation failed due to name conflict",
                event_type="tool_name_conflict",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                custom_fields={
                    "tool_name": tool.name,
                    "visibility": visibility,
                },
            )
            raise tnce
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool creation failure
            structured_logger.log(
                level="ERROR",
                message="Tool creation failed",
                event_type="tool_creation_failed",
                component="tool_service",
                user_id=created_by,
                user_email=owner_email,
                error=e,
                custom_fields={
                    "tool_name": tool.name,
                },
            )
            raise ToolError(f"Failed to register tool: {str(e)}")

    async def register_tools_bulk(
        self,
        db: Session,
        tools: List[ToolCreate],
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        team_id: Optional[str] = None,
        owner_email: Optional[str] = None,
        visibility: Optional[str] = "public",
        conflict_strategy: str = "skip",
    ) -> Dict[str, Any]:
        """Register multiple tools in bulk with a single commit.

        This method provides significant performance improvements over individual
        tool registration by:
        - Using db.add_all() instead of individual db.add() calls
        - Performing a single commit for all tools
        - Batch conflict detection
        - Chunking for very large imports (>500 items)

        Args:
            db: Database session
            tools: List of tool creation schemas
            created_by: Username who created these tools
            created_from_ip: IP address of creator
            created_via: Creation method (ui, api, import, federation)
            created_user_agent: User agent of creation request
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated tools
            team_id: Team ID to assign the tools to
            owner_email: Email of the user who owns these tools
            visibility: Tool visibility level (private, team, public)
            conflict_strategy: How to handle conflicts (skip, update, rename, fail)

        Returns:
            Dict with statistics:
                - created: Number of tools created
                - updated: Number of tools updated
                - skipped: Number of tools skipped
                - failed: Number of tools that failed
                - errors: List of error messages

        Raises:
            ToolError: If bulk registration fails critically

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tools = [MagicMock(), MagicMock()]
            >>> import asyncio
            >>> try:
            ...     result = asyncio.run(service.register_tools_bulk(db, tools))
            ... except Exception:
            ...     pass
        """
        if not tools:
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        # Process in chunks to avoid memory issues and SQLite parameter limits
        chunk_size = 500

        for chunk_start in range(0, len(tools), chunk_size):
            chunk = tools[chunk_start : chunk_start + chunk_size]
            chunk_stats = self._process_tool_chunk(
                db,
                chunk=chunk,
                conflict_strategy=conflict_strategy,
                visibility=visibility,
                team_id=team_id,
                owner_email=owner_email,
                created_by=created_by,
                created_from_ip=created_from_ip,
                created_via=created_via,
                created_user_agent=created_user_agent,
                import_batch_id=import_batch_id,
                federation_source=federation_source,
            )

            # Aggregate stats
            for key, value in chunk_stats.items():
                if key == "errors":
                    stats[key].extend(value)
                else:
                    stats[key] += value

            if chunk_stats["created"] or chunk_stats["updated"]:
                cache = _get_registry_cache()
                await cache.invalidate_tools()
                tool_lookup_cache = _get_tool_lookup_cache()
                tool_name_map: Dict[str, Optional[str]] = {}
                for tool in chunk:
                    name = getattr(tool, "name", None)
                    if not name:
                        continue
                    gateway_id = getattr(tool, "gateway_id", None)
                    tool_name_map[name] = str(gateway_id) if gateway_id else tool_name_map.get(name)
                for tool_name, gateway_id in tool_name_map.items():
                    await tool_lookup_cache.invalidate(tool_name, gateway_id=gateway_id)
                # Also invalidate tags cache since tool tags may have changed
                # First-Party
                from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

                await admin_stats_cache.invalidate_tags()

        return stats

    def _process_tool_chunk(
        self,
        db: Session,
        chunk: List[ToolCreate],
        conflict_strategy: str,
        visibility: str,
        team_id: Optional[int],
        owner_email: Optional[str],
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> dict:
        """Process a chunk of tools for bulk import.

        Args:
            db: The SQLAlchemy database session.
            chunk: List of ToolCreate objects to process.
            conflict_strategy: Strategy for handling conflicts ("skip", "update", or "fail").
            visibility: Tool visibility level ("public", "team", or "private").
            team_id: Team ID for team-scoped tools.
            owner_email: Email of the tool owner.
            created_by: Email of the user creating the tools.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            dict: Statistics dictionary with keys "created", "updated", "skipped", "failed", and "errors".
        """
        stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}

        try:
            # Batch check for existing tools to detect conflicts
            tool_names = [tool.name for tool in chunk]

            if visibility.lower() == "public":
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "public")
            elif visibility.lower() == "team" and team_id:
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "team", DbTool.team_id == team_id)
            else:
                # Private tools - check by owner
                existing_tools_query = select(DbTool).where(DbTool.name.in_(tool_names), DbTool.visibility == "private", DbTool.owner_email == (owner_email or created_by))

            existing_tools = db.execute(existing_tools_query).scalars().all()
            existing_tools_map = {tool.name: tool for tool in existing_tools}

            tools_to_add = []
            tools_to_update = []

            for tool in chunk:
                result = self._process_single_tool_for_bulk(
                    tool=tool,
                    existing_tools_map=existing_tools_map,
                    conflict_strategy=conflict_strategy,
                    visibility=visibility,
                    team_id=team_id,
                    owner_email=owner_email,
                    created_by=created_by,
                    created_from_ip=created_from_ip,
                    created_via=created_via,
                    created_user_agent=created_user_agent,
                    import_batch_id=import_batch_id,
                    federation_source=federation_source,
                )

                if result["status"] == "add":
                    tools_to_add.append(result["tool"])
                    stats["created"] += 1
                elif result["status"] == "update":
                    tools_to_update.append(result["tool"])
                    stats["updated"] += 1
                elif result["status"] == "skip":
                    stats["skipped"] += 1
                elif result["status"] == "fail":
                    stats["failed"] += 1
                    stats["errors"].append(result["error"])

            # Bulk add new tools
            if tools_to_add:
                db.add_all(tools_to_add)

            # Commit the chunk
            db.commit()

            # Refresh tools for notifications and audit trail
            for db_tool in tools_to_add:
                db.refresh(db_tool)
                # Notify subscribers (sync call in async context handled by caller)

            # Log bulk audit trail entry
            if tools_to_add or tools_to_update:
                audit_trail.log_action(
                    user_id=created_by or "system",
                    action="bulk_create_tools" if tools_to_add else "bulk_update_tools",
                    resource_type="tool",
                    resource_id=None,
                    details={"count": len(tools_to_add) + len(tools_to_update), "import_batch_id": import_batch_id},
                    db=db,
                )

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to process tool chunk: {str(e)}")
            stats["failed"] += len(chunk)
            stats["errors"].append(f"Chunk processing failed: {str(e)}")

        return stats

    def _process_single_tool_for_bulk(
        self,
        tool: ToolCreate,
        existing_tools_map: dict,
        conflict_strategy: str,
        visibility: str,
        team_id: Optional[int],
        owner_email: Optional[str],
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> dict:
        """Process a single tool for bulk import.

        Args:
            tool: ToolCreate object to process.
            existing_tools_map: Dictionary mapping tool names to existing DbTool objects.
            conflict_strategy: Strategy for handling conflicts ("skip", "update", or "fail").
            visibility: Tool visibility level ("public", "team", or "private").
            team_id: Team ID for team-scoped tools.
            owner_email: Email of the tool owner.
            created_by: Email of the user creating the tool.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            dict: Result dictionary with "status" key ("add", "update", "skip", or "fail")
                and either "tool" (DbTool object) or "error" (error message).
        """
        try:
            # Same three US-3 malicious-pattern scans that register_tool() runs.
            # Keep these in lock-step with the single-tool path.
            if tool.name:
                self._content_security.detect_malicious_patterns(
                    content=str(tool.name),
                    content_type="Tool name",
                    user_email=owner_email or created_by,
                    ip_address=created_from_ip,
                )
            if tool.description:
                self._content_security.detect_malicious_patterns(
                    content=str(tool.description),
                    content_type="Tool description",
                    user_email=owner_email or created_by,
                    ip_address=created_from_ip,
                )
            if tool.input_schema:
                try:
                    schema_str = orjson.dumps(tool.input_schema).decode()
                    self._content_security.detect_malicious_patterns(
                        content=schema_str,
                        content_type="Tool inputSchema",
                        user_email=owner_email or created_by,
                        ip_address=created_from_ip,
                    )
                except (TypeError, ValueError):
                    # Mirror register_tool(): skip scan when inputSchema isn't JSON-serializable
                    # (e.g. MagicMock in tests). Don't hide actual violations - only this narrow
                    # pre-scan serialization step.
                    pass

            # Extract auth information
            if tool.auth is None:
                auth_type = None
                auth_value = None
            else:
                auth_type = tool.auth.auth_type
                auth_value = tool.auth.auth_value

            # Use provided parameters or schema values
            tool_team_id = team_id if team_id is not None else getattr(tool, "team_id", None)
            tool_owner_email = owner_email or getattr(tool, "owner_email", None) or created_by
            tool_visibility = visibility if visibility is not None else (getattr(tool, "visibility", None) or "public")

            existing_tool = existing_tools_map.get(tool.name)

            if existing_tool:
                # Handle conflict based on strategy
                if conflict_strategy == "skip":
                    return {"status": "skip"}
                if conflict_strategy == "update":
                    # Update existing tool
                    existing_tool.display_name = tool.displayName or tool.name
                    existing_tool.title = tool.title
                    existing_tool.url = str(tool.url)
                    existing_tool.description = tool.description
                    if getattr(existing_tool, "original_description", None) is None:
                        existing_tool.original_description = tool.description
                    existing_tool.integration_type = tool.integration_type
                    existing_tool.request_type = tool.request_type
                    existing_tool.headers = _protect_tool_headers_for_storage(tool.headers, existing_headers=existing_tool.headers)
                    existing_tool.input_schema = tool.input_schema
                    existing_tool.output_schema = tool.output_schema
                    existing_tool.annotations = tool.annotations
                    existing_tool.jsonpath_filter = tool.jsonpath_filter
                    existing_tool.auth_type = auth_type
                    existing_tool.auth_value = auth_value
                    existing_tool.tags = tool.tags or []
                    existing_tool.modified_by = created_by
                    existing_tool.modified_from_ip = created_from_ip
                    existing_tool.modified_via = created_via
                    existing_tool.modified_user_agent = created_user_agent
                    existing_tool.updated_at = datetime.now(timezone.utc)
                    existing_tool.version = (existing_tool.version or 1) + 1

                    # Update REST-specific fields if applicable
                    if tool.integration_type == "REST":
                        existing_tool.base_url = tool.base_url
                        existing_tool.path_template = tool.path_template
                        existing_tool.query_mapping = tool.query_mapping
                        existing_tool.header_mapping = tool.header_mapping
                        existing_tool.timeout_ms = tool.timeout_ms
                        existing_tool.expose_passthrough = tool.expose_passthrough if tool.expose_passthrough is not None else True
                        existing_tool.allowlist = tool.allowlist
                        existing_tool.plugin_chain_pre = tool.plugin_chain_pre
                        existing_tool.plugin_chain_post = tool.plugin_chain_post

                    return {"status": "update", "tool": existing_tool}

                if conflict_strategy == "rename":
                    # Create with renamed tool
                    new_name = f"{tool.name}_imported_{int(datetime.now().timestamp())}"
                    db_tool = self._create_tool_object(
                        tool,
                        new_name,
                        auth_type,
                        auth_value,
                        tool_team_id,
                        tool_owner_email,
                        tool_visibility,
                        created_by,
                        created_from_ip,
                        created_via,
                        created_user_agent,
                        import_batch_id,
                        federation_source,
                    )
                    return {"status": "add", "tool": db_tool}

                if conflict_strategy == "fail":
                    return {"status": "fail", "error": f"Tool name conflict: {tool.name}"}

            # Create new tool
            db_tool = self._create_tool_object(
                tool,
                tool.name,
                auth_type,
                auth_value,
                tool_team_id,
                tool_owner_email,
                tool_visibility,
                created_by,
                created_from_ip,
                created_via,
                created_user_agent,
                import_batch_id,
                federation_source,
            )
            return {"status": "add", "tool": db_tool}

        except Exception as e:
            logger.warning(f"Failed to process tool {tool.name} in bulk operation: {str(e)}")
            return {"status": "fail", "error": f"Failed to process tool {tool.name}: {str(e)}"}

    def _create_tool_object(
        self,
        tool: ToolCreate,
        name: str,
        auth_type: Optional[str],
        auth_value: Optional[str],
        tool_team_id: Optional[int],
        tool_owner_email: Optional[str],
        tool_visibility: str,
        created_by: str,
        created_from_ip: Optional[str],
        created_via: Optional[str],
        created_user_agent: Optional[str],
        import_batch_id: Optional[str],
        federation_source: Optional[str],
    ) -> DbTool:
        """Create a DbTool object from ToolCreate schema.

        Args:
            tool: ToolCreate schema object containing tool data.
            name: Name of the tool.
            auth_type: Authentication type for the tool.
            auth_value: Authentication value/credentials for the tool.
            tool_team_id: Team ID for team-scoped tools.
            tool_owner_email: Email of the tool owner.
            tool_visibility: Tool visibility level ("public", "team", or "private").
            created_by: Email of the user creating the tool.
            created_from_ip: IP address of the request origin.
            created_via: Source of the creation (e.g., "api", "ui").
            created_user_agent: User agent string from the request.
            import_batch_id: Batch identifier for bulk imports.
            federation_source: Source identifier for federated tools.

        Returns:
            DbTool: Database model instance ready to be added to the session.
        """
        return DbTool(
            original_name=name,
            custom_name=name,
            custom_name_slug=slugify(name),
            display_name=tool.displayName or name,
            title=tool.title,
            url=str(tool.url),
            description=tool.description,
            original_description=tool.description,
            integration_type=tool.integration_type,
            request_type=tool.request_type,
            headers=_protect_tool_headers_for_storage(tool.headers),
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            annotations=tool.annotations,
            jsonpath_filter=tool.jsonpath_filter,
            auth_type=auth_type,
            auth_value=auth_value,
            gateway_id=tool.gateway_id,
            tags=tool.tags or [],
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via,
            created_user_agent=created_user_agent,
            import_batch_id=import_batch_id,
            federation_source=federation_source,
            version=1,
            team_id=tool_team_id,
            owner_email=tool_owner_email,
            visibility=tool_visibility,
            base_url=tool.base_url if tool.integration_type == "REST" else None,
            path_template=tool.path_template if tool.integration_type == "REST" else None,
            query_mapping=tool.query_mapping if tool.integration_type == "REST" else None,
            header_mapping=tool.header_mapping if tool.integration_type == "REST" else None,
            timeout_ms=tool.timeout_ms if tool.integration_type == "REST" else None,
            expose_passthrough=((tool.expose_passthrough if tool.integration_type == "REST" and tool.expose_passthrough is not None else True) if tool.integration_type == "REST" else None),
            allowlist=tool.allowlist if tool.integration_type == "REST" else None,
            plugin_chain_pre=tool.plugin_chain_pre if tool.integration_type == "REST" else None,
            plugin_chain_post=tool.plugin_chain_post if tool.integration_type == "REST" else None,
        )

    async def list_tools(
        self,
        db: Session,
        include_inactive: bool = False,
        cursor: Optional[str] = None,
        tags: Optional[List[str]] = None,
        gateway_id: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
        user_email: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        _request_headers: Optional[Dict[str, str]] = None,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> Union[tuple[List[ToolRead], Optional[str]], Dict[str, Any]]:
        """
        Retrieve a list of registered tools from the database with pagination support.

        Args:
            db (Session): The SQLAlchemy database session.
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination.
                Opaque base64-encoded string containing last item's ID.
            tags (Optional[List[str]]): Filter tools by tags. If provided, only tools with at least one matching tag will be returned.
            gateway_id (Optional[str]): Filter tools by gateway ID. Accepts the literal value 'null' to match NULL gateway_id.
            limit (Optional[int]): Maximum number of tools to return. Use 0 for all tools (no limit).
                If not specified, uses pagination_default_page_size.
            page: Page number for page-based pagination (1-indexed). Mutually exclusive with cursor.
            per_page: Items per page for page-based pagination. Defaults to pagination_default_page_size.
            user_email (Optional[str]): User email for team-based access control. If None, no access control is applied.
            team_id (Optional[str]): Filter by specific team ID. Requires user_email for access validation.
            visibility (Optional[str]): Filter by visibility (private, team, public).
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API token access
                where the token scope should be respected instead of the user's full team memberships.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

        Returns:
            tuple[List[ToolRead], Optional[str]]: Tuple containing:
                - List of tools for current page
                - Next cursor token if more results exist, None otherwise

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service.convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> tools, next_cursor = asyncio.run(service.list_tools(db))
            >>> isinstance(tools, list)
            True
        """
        with create_span(
            "tool.list",
            {
                "include_inactive": include_inactive,
                "tags.count": len(tags) if tags else 0,
                "gateway_id": gateway_id,
                "limit": limit,
                "page": page,
                "per_page": per_page,
                "user.email": user_email,
                "team.scope": format_trace_team_scope(token_teams) if token_teams is not None else None,
                "team.filter": team_id,
                "visibility": visibility,
            },
        ):
            # Check cache for first page only (cursor=None)
            # Skip caching when:
            # - user_email is provided (team-filtered results are user-specific)
            # - token_teams is set (scoped access, e.g., public-only or team-scoped tokens)
            # - page-based pagination is used
            # This prevents cache poisoning where admin results could leak to public-only requests
            cache = _get_registry_cache()
            filters_hash = None
            # Only use the cache when using the real converter. In unit tests we often patch
            # convert_tool_to_read() to exercise error handling, and a warm cache would bypass it.
            try:
                converter_is_default = self.convert_tool_to_read.__func__ is ToolService.convert_tool_to_read  # type: ignore[attr-defined]
            except Exception:
                converter_is_default = False

            if cursor is None and user_email is None and token_teams is None and page is None and converter_is_default:
                # Include visibility in the cache hash so admin requests that include
                # an explicit visibility filter don't get served stale results from
                # a previously cached unfiltered admin request.
                filters_hash = cache.hash_filters(
                    include_inactive=include_inactive,
                    tags=sorted(tags) if tags else None,
                    gateway_id=gateway_id,
                    limit=limit,
                    visibility=visibility,
                )
                cached = await cache.get("tools", filters_hash)
                if cached is not None:
                    # Reconstruct ToolRead objects from cached dicts
                    cached_tools = [ToolRead.model_validate(t) for t in cached["tools"]]
                    return (cached_tools, cached.get("next_cursor"))

            # Build base query with ordering and eager load gateway + email_team to avoid N+1
            query = select(DbTool).options(joinedload(DbTool.gateway), joinedload(DbTool.email_team)).order_by(desc(DbTool.created_at), desc(DbTool.id))

            # Apply active/inactive filter
            if not include_inactive:
                query = query.where(DbTool.enabled)
            query = await self._apply_access_control(query, db, user_email, token_teams, team_id)

            if visibility:
                query = query.where(DbTool.visibility == visibility)

            # Add gateway_id filtering if provided
            if gateway_id:
                if gateway_id.lower() == "null":
                    query = query.where(DbTool.gateway_id.is_(None))
                else:
                    query = query.where(DbTool.gateway_id == gateway_id)

            # Add tag filtering if tags are provided (supports both List[str] and List[Dict] formats)
            if tags:
                query = query.where(json_contains_tag_expr(db, DbTool.tags, tags, match_any=True))

            # Use unified pagination helper - handles both page and cursor pagination
            pag_result = await unified_paginate(
                db,
                query=query,
                page=page,
                per_page=per_page,
                cursor=cursor,
                limit=limit,
                base_url="/admin/tools",  # Used for page-based links
                query_params={"include_inactive": include_inactive} if include_inactive else {},
            )

            next_cursor = None
            # Extract servers based on pagination type
            if page is not None:
                # Page-based: pag_result is a dict
                tools_db = pag_result["data"]
            else:
                # Cursor-based: pag_result is a tuple
                tools_db, next_cursor = pag_result

            db.commit()  # Release transaction to avoid idle-in-transaction

            # Convert to ToolRead (common for both pagination types)
            # Team names are loaded via joinedload(DbTool.email_team)
            result = []
            for s in tools_db:
                try:
                    result.append(
                        self.convert_tool_to_read(
                            s,
                            include_metrics=False,
                            include_auth=False,
                            requesting_user_email=requesting_user_email,
                            requesting_user_is_admin=requesting_user_is_admin,
                            requesting_user_team_roles=requesting_user_team_roles,
                        )
                    )
                except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                    logger.exception(f"Failed to convert tool {getattr(s, 'id', 'unknown')} ({getattr(s, 'name', 'unknown')}): {e}")
                    # Continue with remaining tools instead of failing completely

            # Return appropriate format based on pagination type
            if page is not None:
                # Page-based format
                return {
                    "data": result,
                    "pagination": pag_result["pagination"],
                    "links": pag_result["links"],
                }

            # Cursor-based format

            # Cache first page results - only for non-user-specific/non-scoped queries
            # Must match the same conditions as cache lookup to prevent cache poisoning
            if filters_hash is not None and cursor is None and user_email is None and token_teams is None and page is None and converter_is_default:
                try:
                    cache_data = {"tools": [s.model_dump(mode="json") for s in result], "next_cursor": next_cursor}
                    await cache.set("tools", cache_data, filters_hash)
                except AttributeError:
                    pass  # Skip caching if result objects don't support model_dump (e.g., in doctests)

            return (result, next_cursor)

    async def list_server_tools(
        self,
        db: Session,
        server_id: str,
        include_inactive: bool = False,
        include_metrics: bool = False,
        cursor: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        _request_headers: Optional[Dict[str, str]] = None,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
    ) -> List[ToolRead]:
        """
        Retrieve a list of registered tools from the database.

        Args:
            db (Session): The SQLAlchemy database session.
            server_id (str): Server ID
            include_inactive (bool): If True, include inactive tools in the result.
                Defaults to False.
            include_metrics (bool): If True, all tool metrics included in result otherwise null.
                Defaults to False.
            cursor (Optional[str], optional): An opaque cursor token for pagination. Currently,
                this parameter is ignored. Defaults to None.
            user_email (Optional[str]): User email for visibility filtering. If None, no filtering applied.
            token_teams (Optional[List[str]]): Override DB team lookup with token's teams. Used for MCP/API
                token access where the token scope should be respected.
            _request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Currently unused but kept for API consistency. Defaults to None.
            requesting_user_email (Optional[str]): Email of the requesting user for header masking.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.

        Returns:
            List[ToolRead]: A list of registered tools represented as ToolRead objects.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool_read = MagicMock()
            >>> service.convert_tool_to_read = MagicMock(return_value=tool_read)
            >>> db.execute.return_value.scalars.return_value.all.return_value = [MagicMock()]
            >>> import asyncio
            >>> result = asyncio.run(service.list_server_tools(db, 'server1'))
            >>> isinstance(result, list)
            True
        """

        with create_span(
            "tool.list",
            {
                "server_id": server_id,
                "include_inactive": include_inactive,
                "include_metrics": include_metrics,
                "user.email": user_email,
                "team.scope": format_trace_team_scope(token_teams) if token_teams is not None else None,
            },
        ):
            if include_metrics:
                query = (
                    select(DbTool)
                    .options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))
                    .options(selectinload(DbTool.metrics))
                    .options(selectinload(DbTool.metrics_hourly))
                    .join(server_tool_association, DbTool.id == server_tool_association.c.tool_id)
                    .where(server_tool_association.c.server_id == server_id)
                )
            else:
                query = (
                    select(DbTool)
                    .options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))
                    .join(server_tool_association, DbTool.id == server_tool_association.c.tool_id)
                    .where(server_tool_association.c.server_id == server_id)
                )

            cursor = None  # Placeholder for pagination; ignore for now
            logger.debug(f"Listing server tools for server_id={server_id} with include_inactive={include_inactive}, cursor={cursor}")

            if not include_inactive:
                query = query.where(DbTool.enabled)

            # Add visibility filtering if user context OR token_teams provided
            # This ensures unauthenticated requests with token_teams=[] only see public tools
            if user_email is not None or token_teams is not None:  # empty-string user_email -> public-only filtering (secure default)
                # Use token_teams if provided (for MCP/API token access), otherwise look up from DB
                if token_teams is not None:
                    team_ids = token_teams
                elif user_email:
                    team_service = TeamManagementService(db)
                    user_teams = await team_service.get_user_teams(user_email)
                    team_ids = [team.id for team in user_teams]
                else:
                    team_ids = []

                # Check if this is a public-only token (empty teams array)
                # Public-only tokens can ONLY see public resources - no owner access
                is_public_only_token = token_teams is not None and len(token_teams) == 0

                access_conditions = [
                    DbTool.visibility == "public",
                ]
                # Only include owner access for non-public-only tokens with user_email
                if not is_public_only_token and user_email:
                    access_conditions.append(DbTool.owner_email == user_email)
                if team_ids:
                    access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            # Execute the query - team names are loaded via joinedload(DbTool.email_team)
            tools = db.execute(query).scalars().all()

            db.commit()  # Release transaction to avoid idle-in-transaction

            result = []
            for tool in tools:
                try:
                    result.append(
                        self.convert_tool_to_read(
                            tool,
                            include_metrics=include_metrics,
                            include_auth=False,
                            requesting_user_email=requesting_user_email,
                            requesting_user_is_admin=requesting_user_is_admin,
                            requesting_user_team_roles=requesting_user_team_roles,
                        )
                    )
                except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                    logger.exception(f"Failed to convert tool {getattr(tool, 'id', 'unknown')} ({getattr(tool, 'name', 'unknown')}): {e}")
                    # Continue with remaining tools instead of failing completely

            return result

    async def list_server_mcp_tool_definitions(
        self,
        db: Session,
        server_id: str,
        *,
        include_inactive: bool = False,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return server-scoped MCP tool definitions without building full ToolRead models.

        This is a hot-path helper for the internal Rust -> Python seam. It keeps
        auth and visibility semantics aligned with ``list_server_tools`` while
        avoiding the heavier ``ToolRead`` conversion that is only needed for the
        admin/API surfaces.

        Args:
            db: Active database session.
            server_id: Virtual server identifier used to scope the tool listing.
            include_inactive: Whether disabled tools should be included.
            user_email: Requester email for owner-scoped visibility checks.
            token_teams: Normalized team scope from the caller token.

        Returns:
            A list of MCP-compatible tool definition dictionaries.
        """
        with create_span(
            "tool.list",
            {
                "server_id": server_id,
                "include_inactive": include_inactive,
                "user.email": user_email,
                "team.scope": format_trace_team_scope(token_teams) if token_teams is not None else None,
                "mcp.definition_mode": True,
            },
        ):
            name_column = DbTool.__table__.c.name
            query = (
                select(
                    name_column.label("name"),
                    DbTool.description.label("description"),
                    DbTool.input_schema.label("input_schema"),
                    DbTool.output_schema.label("output_schema"),
                    DbTool.annotations.label("annotations"),
                    DbTool.owner_email.label("owner_email"),
                    DbTool.team_id.label("team_id"),
                    DbTool.visibility.label("visibility"),
                )
                .join(server_tool_association, DbTool.id == server_tool_association.c.tool_id)
                .where(server_tool_association.c.server_id == server_id)
            )

            if not include_inactive:
                query = query.where(DbTool.enabled)

            if user_email is not None or token_teams is not None:
                team_ids = token_teams if token_teams is not None else []
                is_public_only_token = token_teams is not None and len(token_teams) == 0

                access_conditions = [DbTool.visibility == "public"]
                if not is_public_only_token and user_email:
                    access_conditions.append(DbTool.owner_email == user_email)
                if team_ids:
                    access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))
                query = query.where(or_(*access_conditions))

            rows = db.execute(query).mappings().all()
            db.commit()

            result: List[Dict[str, Any]] = []
            for row in rows:
                payload: Dict[str, Any] = {
                    "name": row["name"],
                    "description": row["description"],
                    "inputSchema": row["input_schema"] or {"type": "object", "properties": {}},
                    "annotations": row["annotations"] or {},
                }
                if row["output_schema"] is not None:
                    payload["outputSchema"] = row["output_schema"]
                result.append(payload)

            return result

    async def list_tools_for_user(
        self,
        db: Session,
        user_email: str,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        include_inactive: bool = False,
        _skip: int = 0,
        _limit: int = 100,
        *,
        cursor: Optional[str] = None,
        gateway_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> tuple[List[ToolRead], Optional[str]]:
        """
        DEPRECATED: Use list_tools() with user_email parameter instead.

        List tools user has access to with team filtering and cursor pagination.

        This method is maintained for backward compatibility but is no longer used.
        New code should call list_tools() with user_email, team_id, and visibility parameters.

        Args:
            db: Database session
            user_email: Email of the user requesting tools
            team_id: Optional team ID to filter by specific team
            visibility: Optional visibility filter (private, team, public)
            include_inactive: Whether to include inactive tools
            _skip: Number of tools to skip for pagination (deprecated)
            _limit: Maximum number of tools to return (deprecated)
            cursor: Opaque cursor token for pagination
            gateway_id: Filter tools by gateway ID. Accepts literal 'null' for NULL gateway_id.
            tags: Filter tools by tags (match any)
            limit: Maximum number of tools to return. Use 0 for all tools (no limit).
                If not specified, uses pagination_default_page_size.

        Returns:
            tuple[List[ToolRead], Optional[str]]: Tools the user has access to and optional next_cursor
        """
        # Determine page size based on limit parameter
        # limit=None: use default, limit=0: no limit (all), limit>0: use specified (capped)
        if limit is None:
            page_size = settings.pagination_default_page_size
        elif limit == 0:
            page_size = None  # No limit - fetch all
        else:
            page_size = min(limit, settings.pagination_max_page_size)

        # Decode cursor to get last_id if provided
        last_id = None
        if cursor:
            try:
                cursor_data = decode_cursor(cursor)
                last_id = cursor_data.get("id")
                logger.debug(f"Decoded cursor: last_id={last_id}")
            except ValueError as e:
                logger.warning(f"Invalid cursor, ignoring: {e}")

        # Build query following existing patterns from list_tools()
        team_service = TeamManagementService(db)
        user_teams = await team_service.get_user_teams(user_email)
        team_ids = [team.id for team in user_teams]

        # Eager load gateway and email_team to avoid N+1 when accessing gateway_slug and team name
        query = select(DbTool).options(joinedload(DbTool.gateway), joinedload(DbTool.email_team))

        # Apply active/inactive filter
        if not include_inactive:
            query = query.where(DbTool.enabled.is_(True))

        if team_id:
            if team_id not in team_ids:
                return ([], None)  # No access to team

            access_conditions = [
                and_(DbTool.team_id == team_id, DbTool.visibility.in_(["team", "public"])),
                and_(DbTool.team_id == team_id, DbTool.owner_email == user_email),
            ]
            query = query.where(or_(*access_conditions))
        else:
            access_conditions = [
                DbTool.owner_email == user_email,
                DbTool.visibility == "public",
            ]
            if team_ids:
                access_conditions.append(and_(DbTool.team_id.in_(team_ids), DbTool.visibility.in_(["team", "public"])))

            query = query.where(or_(*access_conditions))

        # Apply visibility filter if specified
        if visibility:
            query = query.where(DbTool.visibility == visibility)

        if gateway_id:
            if gateway_id.lower() == "null":
                query = query.where(DbTool.gateway_id.is_(None))
            else:
                query = query.where(DbTool.gateway_id == gateway_id)

        if tags:
            query = query.where(json_contains_tag_expr(db, DbTool.tags, tags, match_any=True))

        # Apply cursor filter (WHERE id > last_id)
        if last_id:
            query = query.where(DbTool.id > last_id)

        # Execute query - team names are loaded via joinedload(DbTool.email_team)
        if page_size is not None:
            tools = db.execute(query.limit(page_size + 1)).scalars().all()
        else:
            tools = db.execute(query).scalars().all()

        db.commit()  # Release transaction to avoid idle-in-transaction

        # Check if there are more results (only when paginating)
        has_more = page_size is not None and len(tools) > page_size
        if has_more:
            tools = tools[:page_size]

        # Convert to ToolRead objects
        result = []
        for tool in tools:
            try:
                result.append(self.convert_tool_to_read(tool, include_metrics=False, include_auth=False, requesting_user_email=user_email, requesting_user_is_admin=False))
            except (ValidationError, ValueError, KeyError, TypeError, binascii.Error) as e:
                logger.exception(f"Failed to convert tool {getattr(tool, 'id', 'unknown')} ({getattr(tool, 'name', 'unknown')}): {e}")
                # Continue with remaining tools instead of failing completely

        next_cursor = None
        # Generate cursor if there are more results (cursor-based pagination)
        if has_more and tools:
            last_tool = tools[-1]
            next_cursor = encode_cursor({"created_at": last_tool.created_at.isoformat(), "id": last_tool.id})

        return (result, next_cursor)

    async def get_tool(
        self,
        db: Session,
        tool_id: str,
        requesting_user_email: Optional[str] = None,
        requesting_user_is_admin: bool = False,
        requesting_user_team_roles: Optional[Dict[str, str]] = None,
        token_teams: Optional[List[str]] = None,
    ) -> ToolRead:
        """
        Retrieve a tool by its ID with access control.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            requesting_user_email (Optional[str]): Email of the requesting user for access control.
            requesting_user_is_admin (bool): Whether the requester is an admin.
            requesting_user_team_roles (Optional[Dict[str, str]]): {team_id: role} for the requester.
                Used only for response masking (``convert_tool_to_read``), not for visibility.
            token_teams (Optional[List[str]]): JWT-scoped team list used for visibility checks.
                ``None`` means unrestricted admin (paired with ``requesting_user_email=None``).
                ``[]`` means public-only scope. ``[...]`` means team-scoped.
                This is kept separate from ``requesting_user_team_roles`` to avoid the Layer 1
                visibility check silently widening a scoped token to full DB team membership.

        Returns:
            ToolRead: The tool object.

        Raises:
            ToolNotFoundError: If the tool is not found or access is denied.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.get_tool(db, 'tool_id'))
            'tool_read'
        """
        tool = db.get(DbTool, tool_id)
        if not tool:
            raise ToolNotFoundError(f"Tool not found: {tool_id}")

        # SECURITY (Layer 1): forward JWT-scoped token_teams; DO NOT widen to DB team roles.
        is_admin_bypass = requesting_user_is_admin and requesting_user_email is None
        access_user_email = None if is_admin_bypass else requesting_user_email
        access_token_teams = None if is_admin_bypass else token_teams

        tool_payload = {
            "visibility": tool.visibility,
            "team_id": tool.team_id,
            "owner_email": tool.owner_email,
        }

        if not await self._check_tool_access(db, tool_payload, access_user_email, access_token_teams):
            structured_logger.log(
                level="INFO",
                message="Tool access denied",
                event_type="tool_access_denied",
                component="tool_service",
                resource_type="tool",
                resource_id=str(tool.id),
                team_id=getattr(tool, "team_id", None),
                user_email=requesting_user_email,
                custom_fields={
                    "visibility": tool.visibility,
                    "admin_bypass": is_admin_bypass,
                },
            )
            raise ToolNotFoundError(f"Tool not found: {tool_id}")

        tool_read = self.convert_tool_to_read(
            tool,
            requesting_user_email=requesting_user_email,
            requesting_user_is_admin=requesting_user_is_admin,
            requesting_user_team_roles=requesting_user_team_roles,
        )

        structured_logger.log(
            level="INFO",
            message="Tool retrieved successfully",
            event_type="tool_viewed",
            component="tool_service",
            team_id=getattr(tool, "team_id", None),
            resource_type="tool",
            resource_id=str(tool.id),
            custom_fields={
                "tool_name": tool.name,
                "include_metrics": bool(getattr(tool_read, "metrics", {})),
            },
        )

        return tool_read

    async def delete_tool(self, db: Session, tool_id: str, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """
        Delete a tool by its ID.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            user_email (Optional[str]): Email of user performing delete (for ownership check).
            purge_metrics (bool): If True, delete raw + rollup metrics for this tool.

        Raises:
            ToolNotFoundError: If the tool is not found.
            PermissionError: If user doesn't own the tool.
            ToolError: For other deletion errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.delete = MagicMock()
            >>> db.commit = MagicMock()
            >>> service._notify_tool_deleted = AsyncMock()
            >>> import asyncio
            >>> asyncio.run(service.delete_tool(db, 'tool_id'))
        """
        try:
            tool = db.get(DbTool, tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can delete this tool")

            tool_info = {"id": tool.id, "name": tool.name}
            tool_name = tool.name
            tool_team_id = tool.team_id

            if purge_metrics:
                with pause_rollup_during_purge(reason=f"purge_tool:{tool_id}"):
                    delete_metrics_in_batches(db, ToolMetric, ToolMetric.tool_id, tool_id)
                    delete_metrics_in_batches(db, ToolMetricsHourly, ToolMetricsHourly.tool_id, tool_id)

            # Clean up server_tool_association rows referencing this tool.
            # The association table FK has no ondelete cascade, so rows must
            # be removed explicitly before the tool row can be deleted.
            db.execute(delete(server_tool_association).where(server_tool_association.c.tool_id == tool_id))

            # Use DELETE with rowcount check for database-agnostic atomic delete
            stmt = delete(DbTool).where(DbTool.id == tool_id)
            result = db.execute(stmt)
            if result.rowcount == 0:
                # Tool was already deleted by another concurrent request
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            db.commit()
            await self._notify_tool_deleted(tool_info)
            logger.info(f"Permanently deleted tool: {tool_info['name']}")

            # Structured logging: Audit trail for tool deletion
            audit_trail.log_action(
                user_id=user_email or "system",
                action="delete_tool",
                resource_type="tool",
                resource_id=tool_info["id"],
                resource_name=tool_name,
                user_email=user_email,
                team_id=tool_team_id,
                old_values={
                    "name": tool_name,
                },
                db=db,
            )

            # Structured logging: Log successful tool deletion
            structured_logger.log(
                level="INFO",
                message="Tool deleted successfully",
                event_type="tool_deleted",
                component="tool_service",
                user_email=user_email,
                team_id=tool_team_id,
                resource_type="tool",
                resource_id=tool_info["id"],
                custom_fields={
                    "tool_name": tool_name,
                    "purge_metrics": purge_metrics,
                },
            )

            # Invalidate cache after successful deletion
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(tool_name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()
            # Invalidate top performers cache
            # First-Party
            from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

            metrics_cache.invalidate_prefix("top_tools:")
            metrics_cache.invalidate("tools")
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool deletion failed due to permission error",
                event_type="tool_delete_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=pe,
            )
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool deletion failure
            structured_logger.log(
                level="ERROR",
                message="Tool deletion failed",
                event_type="tool_deletion_failed",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
            )
            raise ToolError(f"Failed to delete tool: {str(e)}")

    async def set_tool_state(self, db: Session, tool_id: str, activate: bool, reachable: bool, user_email: Optional[str] = None, skip_cache_invalidation: bool = False) -> ToolRead:
        """
        Set the activation status of a tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            activate (bool): True to activate, False to deactivate.
            reachable (bool): True if the tool is reachable.
            user_email: Optional[str] The email of the user to check if the user has permission to modify.
            skip_cache_invalidation: If True, skip cache invalidation (used for batch operations).

        Returns:
            ToolRead: The updated tool object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            ToolLockConflictError: If the tool row is locked by another transaction.
            ToolError: For other errors.
            PermissionError: If user doesn't own the agent.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> service._notify_tool_activated = AsyncMock()
            >>> service._notify_tool_deactivated = AsyncMock()
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.set_tool_state(db, 'tool_id', True, True))
            'tool_read'
        """
        try:
            # Use nowait=True to fail fast if row is locked, preventing lock contention under high load
            try:
                tool = get_for_update(db, DbTool, tool_id, nowait=True)
            except OperationalError as lock_err:
                # Row is locked by another transaction - fail fast with 409
                db.rollback()
                raise ToolLockConflictError(f"Tool {tool_id} is currently being modified by another request") from lock_err
            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can activate the Tool" if activate else "Only the owner can deactivate the Tool")

            is_activated = is_reachable = False
            if tool.enabled != activate:
                tool.enabled = activate
                is_activated = True

            if tool.reachable != reachable:
                tool.reachable = reachable
                is_reachable = True

            if is_activated or is_reachable:
                tool.updated_at = datetime.now(timezone.utc)

                db.commit()
                db.refresh(tool)

                # Invalidate cache after status change (skip for batch operations)
                if not skip_cache_invalidation:
                    cache = _get_registry_cache()
                    await cache.invalidate_tools()
                    tool_lookup_cache = _get_tool_lookup_cache()
                    await tool_lookup_cache.invalidate(tool.name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)

                if not tool.enabled:
                    # Inactive
                    await self._notify_tool_deactivated(tool)
                elif tool.enabled and not tool.reachable:
                    # Offline
                    await self._notify_tool_offline(tool)
                else:
                    # Active
                    await self._notify_tool_activated(tool)

                logger.info(f"Tool: {tool.name} is {'enabled' if activate else 'disabled'}{' and accessible' if reachable else ' but inaccessible'}")

                # Structured logging: Audit trail for tool state change
                audit_trail.log_action(
                    user_id=user_email or "system",
                    action="set_tool_state",
                    resource_type="tool",
                    resource_id=tool.id,
                    resource_name=tool.name,
                    user_email=user_email,
                    team_id=tool.team_id,
                    new_values={
                        "enabled": tool.enabled,
                        "reachable": tool.reachable,
                    },
                    context={
                        "action": "activate" if activate else "deactivate",
                    },
                    db=db,
                )

                # Structured logging: Log successful tool state change
                structured_logger.log(
                    level="INFO",
                    message=f"Tool {'activated' if activate else 'deactivated'} successfully",
                    event_type="tool_state_changed",
                    component="tool_service",
                    user_email=user_email,
                    team_id=tool.team_id,
                    resource_type="tool",
                    resource_id=tool.id,
                    custom_fields={
                        "tool_name": tool.name,
                        "enabled": tool.enabled,
                        "reachable": tool.reachable,
                    },
                )

            return self.convert_tool_to_read(tool, requesting_user_email=getattr(tool, "owner_email", None))
        except PermissionError as e:
            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool state change failed due to permission error",
                event_type="tool_state_change_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
            )
            raise e
        except ToolLockConflictError:
            # Re-raise lock conflicts without wrapping - allows 409 response
            raise
        except ToolNotFoundError:
            # Re-raise not found without wrapping - allows 404 response
            raise
        except Exception as e:
            db.rollback()

            # Structured logging: Log generic tool state change failure
            structured_logger.log(
                level="ERROR",
                message="Tool state change failed",
                event_type="tool_state_change_failed",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=e,
            )
            raise ToolError(f"Failed to set tool state: {str(e)}")

    async def invoke_tool_direct(
        self,
        gateway_id: str,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Optional[Dict[str, str]] = None,
        meta_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        user_context: Optional[UserContext] = None,
    ) -> types.CallToolResult:
        """
        Invoke a tool directly on a remote MCP gateway in direct_proxy mode.

        This bypasses all gateway processing (caching, plugins, validation) and forwards
        the tool call directly to the remote MCP server, returning the raw result.

        Args:
            gateway_id: Gateway ID to invoke the tool on.
            name: Name of tool to invoke.
            arguments: Tool arguments.
            request_headers: Headers from the request to pass through.
            meta_data: Optional metadata dictionary for additional context (e.g., request ID).
            user_email: Email of the requesting user for access control.
            token_teams: Team IDs from the user's token for access control.
            user_context: Optional UserContext for identity propagation.

        Returns:
            CallToolResult from the remote MCP server (as-is, no normalization).

        Raises:
            ToolNotFoundError: If gateway not found or access denied.
            ToolInvocationError: If invocation fails.
        """
        logger.info(f"Direct proxy tool invocation: {name} via gateway {SecurityValidator.sanitize_log_message(gateway_id)}")
        # Look up gateway
        # Use a fresh session for this lookup
        with fresh_db_session() as db:
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id)).scalar_one_or_none()
            if not gateway:
                raise ToolNotFoundError(f"Gateway {gateway_id} not found")

            if getattr(gateway, "gateway_mode", "cache") != "direct_proxy" or not settings.mcpgateway_direct_proxy_enabled:
                raise ToolInvocationError(f"Gateway {gateway_id} is not in direct_proxy mode")

            # SECURITY: Defensive access check — callers should also check,
            # but enforce here to prevent RBAC bypass if called from a new context.
            if not await check_gateway_access(db, gateway, user_email, token_teams):
                raise ToolNotFoundError(f"Tool not found: {name}")

            # Prepare headers with gateway auth
            headers = build_gateway_auth_headers(gateway)

            # Forward passthrough headers if configured
            if gateway.passthrough_headers and request_headers:
                for header_name in gateway.passthrough_headers:
                    header_value = request_headers.get(header_name.lower()) or request_headers.get(header_name)
                    if header_value:
                        headers[header_name] = header_value

            # Inject identity propagation headers
            if user_context:
                headers.update(build_identity_headers(user_context, gateway))
                meta_data = build_identity_meta(user_context, meta_data, gateway)

            gateway_url = gateway.url

            # Resolve the original (unprefixed) tool name for the remote server.
            # Tools registered via gateways are stored as "{gateway_slug}{separator}{slugified_name}",
            # but the remote server only knows the original name (e.g. "get_system_time" not "get-system-time").
            # Look up the tool's original_name from the DB; fall back to the prefixed name if not found
            # (e.g. when calling a tool that exists on the remote but hasn't been cached locally).
            remote_name = name
            tool_row = db.execute(select(DbTool).where(DbTool.name == name, DbTool.gateway_id == gateway_id)).scalar_one_or_none()  # pylint: disable=comparison-with-callable
            if tool_row and tool_row.original_name:
                remote_name = tool_row.original_name
            else:
                # Fallback: strip the slug prefix (best-effort for tools not yet in DB)
                gateway_slug = getattr(gateway, "slug", None) or ""
                if gateway_slug:
                    prefix = f"{gateway_slug}{settings.gateway_tool_name_separator}"
                    if name.startswith(prefix):
                        remote_name = name[len(prefix) :]

        # Use MCP SDK to connect and call tool
        try:
            with create_span(
                "mcp.client.call",
                {
                    "mcp.tool.name": remote_name,
                    "contextforge.gateway_id": str(gateway.id),
                    "contextforge.runtime": "python",
                    "contextforge.transport": "streamablehttp",
                    "network.protocol.name": "mcp",
                    "server.address": urlparse(gateway_url).hostname,
                    "server.port": urlparse(gateway_url).port,
                    "url.path": urlparse(gateway_url).path or "/",
                    "url.full": sanitize_url_for_logging(gateway_url, {}),
                },
            ):
                traced_headers = inject_trace_context_headers(headers)
                async with streamablehttp_client(url=gateway_url, headers=traced_headers, timeout=settings.mcpgateway_direct_proxy_timeout) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(read_stream, write_stream) as session:
                        with create_span("mcp.client.initialize", {"contextforge.transport": "streamablehttp", "contextforge.runtime": "python"}):
                            await session.initialize()

                        with create_span(
                            "mcp.client.request",
                            {
                                "mcp.tool.name": remote_name,
                                "contextforge.gateway_id": str(gateway.id),
                                "contextforge.runtime": "python",
                            },
                        ):
                            # Call tool with meta if provided
                            if meta_data:
                                logger.debug(f"Forwarding _meta to remote gateway: {meta_data}")
                                tool_result = await session.call_tool(name=remote_name, arguments=arguments, meta=meta_data)
                            else:
                                tool_result = await session.call_tool(name=remote_name, arguments=arguments)
                        with create_span(
                            "mcp.client.response",
                            {
                                "mcp.tool.name": remote_name,
                                "contextforge.gateway_id": str(gateway.id),
                                "contextforge.runtime": "python",
                                "upstream.response.success": not getattr(tool_result, "is_error", False) and not getattr(tool_result, "isError", False),
                            },
                        ):
                            pass

                        logger.info(
                            f"[INVOKE TOOL] Using direct_proxy mode for gateway {SecurityValidator.sanitize_log_message(gateway.id)} (from X-Context-Forge-Gateway-Id header). Meta Attached: {meta_data is not None}"
                        )
                        return tool_result
        except Exception as e:
            logger.exception(f"Direct proxy tool invocation failed for {name}: {e}")
            raise ToolInvocationError(f"Direct proxy tool invocation failed: {str(e)}")

    async def prepare_rust_mcp_tool_execution(
        self,
        db: Session,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        request_headers: Optional[Dict[str, str]] = None,
        app_user_email: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        server_id: Optional[str] = None,
        plugin_global_context: Optional[GlobalContext] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
    ) -> Dict[str, Any]:
        """Build a narrow MCP execution plan for the Rust runtime hot path.

        This reuses Python's existing auth, scoping, and secret-handling logic,
        but stops before the actual upstream MCP call. The Rust runtime can then
        execute the call directly for the simple streamable HTTP MCP cases that
        dominate load tests, while Python remains the authority for policy.

        When tool_pre_invoke hooks are registered, they are executed during plan
        resolution and their modifications (cleaned args, injected headers) are
        returned in the plan for the Rust runtime to apply.

        Args:
            db: Active database session.
            name: Tool name requested by the caller.
            arguments: Tool call arguments from the JSON-RPC params (passed to pre-invoke hooks).
            request_headers: Incoming request headers used for passthrough/auth decisions.
            app_user_email: OAuth application user email, when present.
            user_email: Effective requester email after auth normalization.
            token_teams: Normalized team scope from the caller token.
            server_id: Optional virtual server identifier restricting tool access.
            plugin_global_context: Optional global context from middleware for hook continuity.
            plugin_context_table: Optional context table from prior hooks for state sharing.

        Returns:
            A Rust execution plan dictionary, or a fallback descriptor when direct
            Rust execution is not eligible.

        Raises:
            ToolNotFoundError: If the requested tool is not visible or invocable.
            ToolInvocationError: If gateway auth preparation fails or the tool name is ambiguous.
        """

        gateway_id_from_header = extract_gateway_id_from_headers(request_headers)
        is_direct_proxy = False
        tool = None
        gateway = None
        tool_selected_from_server_scope = False
        tool_payload: Dict[str, Any] = {}
        gateway_payload: Optional[Dict[str, Any]] = None
        if gateway_id_from_header:
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id_from_header)).scalar_one_or_none()
            if gateway and gateway.gateway_mode == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                if not await check_gateway_access(db, gateway, user_email, token_teams):
                    raise ToolNotFoundError(f"Tool not found: {name}")
                is_direct_proxy = True
                gateway_payload = {
                    "id": str(gateway.id),
                    "name": gateway.name,
                    "url": gateway.url,
                    "auth_type": gateway.auth_type,
                    "auth_value": encode_auth(gateway.auth_value) if isinstance(gateway.auth_value, dict) else gateway.auth_value,
                    "auth_query_params": gateway.auth_query_params,
                    "oauth_config": gateway.oauth_config,
                    "ca_certificate": gateway.ca_certificate,
                    "ca_certificate_sig": gateway.ca_certificate_sig,
                    "passthrough_headers": gateway.passthrough_headers,
                    "gateway_mode": gateway.gateway_mode,
                }
                tool_payload = {
                    "id": None,
                    "name": name,
                    "original_name": name,
                    "enabled": True,
                    "reachable": True,
                    "integration_type": "MCP",
                    "request_type": "streamablehttp",
                    "gateway_id": str(gateway.id),
                }

        if not is_direct_proxy:
            tool_lookup_cache = _get_tool_lookup_cache()
            cached_payload = await tool_lookup_cache.get(name) if tool_lookup_cache.enabled else None

            if cached_payload:
                status = cached_payload.get("status", "active")
                if status == "missing":
                    raise ToolNotFoundError(f"Tool not found: {name}")
                if status == "inactive":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
                if status == "offline":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")
                tool_payload = cached_payload.get("tool") or {}
                gateway_payload = cached_payload.get("gateway")

        if not tool_payload:
            tools = self._load_invocable_tools(db, name, server_id=server_id)
            tool_selected_from_server_scope = bool(server_id)

            if not tools:
                raise ToolNotFoundError(f"Tool not found: {name}")

            multiple_found = len(tools) > 1
            if not multiple_found:
                tool = tools[0]
            else:
                visibility_priority = {"team": 0, "private": 1, "public": 2}
                accessible_tools: list[tuple[int, Any]] = []
                for candidate in tools:
                    tool_dict = {"visibility": candidate.visibility, "team_id": candidate.team_id, "owner_email": candidate.owner_email}
                    if await self._check_tool_access(db, tool_dict, user_email, token_teams):
                        priority = visibility_priority.get(candidate.visibility, 99)
                        accessible_tools.append((priority, candidate))

                if not accessible_tools:
                    raise ToolNotFoundError(f"Tool not found: {name}")

                accessible_tools.sort(key=lambda item: item[0])
                best_priority = accessible_tools[0][0]
                best_tools = [candidate for priority, candidate in accessible_tools if priority == best_priority]
                if len(best_tools) > 1:
                    raise ToolInvocationError(f"Multiple tools found with name '{name}' at same priority level. Tool name is ambiguous.")
                tool = best_tools[0]

            if not tool.enabled:
                raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")

            if not tool.reachable:
                await tool_lookup_cache.set_negative(name, "offline")
                raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

            gateway = tool.gateway
            cache_payload = self._build_tool_cache_payload(tool, gateway)
            tool_payload = cache_payload.get("tool") or {}
            gateway_payload = cache_payload.get("gateway")
            if not multiple_found:
                await tool_lookup_cache.set(name, cache_payload, gateway_id=tool_payload.get("gateway_id"))

        if tool_payload.get("enabled") is False:
            raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
        if tool_payload.get("reachable") is False:
            raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

        if is_direct_proxy:
            return {"eligible": False, "fallbackReason": "direct-proxy"}

        if not await self._check_tool_access(db, tool_payload, user_email, token_teams):
            raise ToolNotFoundError(f"Tool not found: {name}")

        if server_id and not tool_selected_from_server_scope:
            tool_id_for_check = tool_payload.get("id")
            if not tool_id_for_check:
                raise ToolNotFoundError(f"Tool not found: {name}")
            server_match = db.execute(
                select(server_tool_association.c.tool_id).where(
                    server_tool_association.c.server_id == server_id,
                    server_tool_association.c.tool_id == tool_id_for_check,
                )
            ).first()
            if not server_match:
                raise ToolNotFoundError(f"Tool not found: {name}")

        tool_integration_type = tool_payload.get("integration_type")
        if tool_integration_type != "MCP":
            return {"eligible": False, "fallbackReason": f"unsupported-integration:{tool_integration_type or 'unknown'}"}

        tool_request_type = tool_payload.get("request_type")
        transport = tool_request_type.lower() if tool_request_type else "sse"
        if transport not in {"streamablehttp", "sse"}:
            return {"eligible": False, "fallbackReason": f"unsupported-transport:{transport}"}

        tool_jsonpath_filter = tool_payload.get("jsonpath_filter")
        if tool_jsonpath_filter:
            return {"eligible": False, "fallbackReason": "jsonpath-filter-configured"}

        passthrough_allowed = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)

        if tool is not None:
            gateway = tool.gateway

        tool_name_original = tool_payload.get("original_name") or tool_payload.get("name") or name
        tool_id = tool_payload.get("id")
        tool_gateway_id = tool_payload.get("gateway_id")
        tool_timeout_ms = tool_payload.get("timeout_ms")
        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else settings.tool_timeout

        # Resolve per-tool context_id for plugin manager (same pattern as invoke_tool)
        # First-Party
        from mcpgateway.plugins.gateway_plugin_manager import make_context_id  # pylint: disable=import-outside-toplevel

        _tool_team_id = tool_payload.get("team_id")
        # Use name (the gateway-scoped unique identifier, e.g. "mac-fs-read-file") as the binding key.
        # original_name (e.g. "read_file") is only unique per gateway, so two gateways in the same
        # team can share the same original_name — making it ambiguous as a binding key.
        # name is enforced unique per team by DB constraint uq_team_owner_email_name_tool.
        _binding_tool_name = tool_payload.get("name") or name
        plugin_context_id = make_context_id(str(_tool_team_id), _binding_tool_name) if _tool_team_id else server_id
        plugin_manager = await self._get_plugin_manager(plugin_context_id)
        has_pre_invoke = plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE)
        has_post_invoke = plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE)

        has_gateway = gateway_payload is not None
        gateway_url = gateway_payload.get("url") if has_gateway else None
        gateway_name = gateway_payload.get("name") if has_gateway else None
        gateway_auth_type = gateway_payload.get("auth_type") if has_gateway else None
        gateway_auth_value = gateway_payload.get("auth_value") if has_gateway and isinstance(gateway_payload.get("auth_value"), str) else None
        gateway_auth_query_params = gateway_payload.get("auth_query_params") if has_gateway and isinstance(gateway_payload.get("auth_query_params"), dict) else None
        gateway_oauth_config = gateway_payload.get("oauth_config") if has_gateway and isinstance(gateway_payload.get("oauth_config"), dict) else None
        if has_gateway and gateway is not None:
            runtime_gateway_auth_value = getattr(gateway, "auth_value", None)
            if isinstance(runtime_gateway_auth_value, dict):
                gateway_auth_value = encode_auth(runtime_gateway_auth_value)
            elif isinstance(runtime_gateway_auth_value, str):
                gateway_auth_value = runtime_gateway_auth_value
            runtime_gateway_query_params = getattr(gateway, "auth_query_params", None)
            if isinstance(runtime_gateway_query_params, dict):
                gateway_auth_query_params = runtime_gateway_query_params
            runtime_gateway_oauth_config = getattr(gateway, "oauth_config", None)
            if isinstance(runtime_gateway_oauth_config, dict):
                gateway_oauth_config = runtime_gateway_oauth_config
        # MCP invoke path: cert params come from the serialized gateway_payload dict
        # (the ORM session that produced the gateway object may already be closed).
        gateway_ca_cert = gateway_payload.get("ca_certificate") if has_gateway else None
        gateway_client_cert = gateway_payload.get("client_cert") if has_gateway else None
        gateway_client_key = gateway_payload.get("client_key") if has_gateway else None
        gateway_id_str = gateway_payload.get("id") if has_gateway else None

        if tool is None and has_gateway:
            requires_gateway_auth_hydration = gateway_auth_type in {"basic", "bearer", "authheaders", "oauth", "query_param"}
            if requires_gateway_auth_hydration:
                tool_id_for_hydration = tool_payload.get("id")
                if tool_id_for_hydration:
                    tool_auth_row = db.execute(select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.id == tool_id_for_hydration)).scalar_one_or_none()
                    if tool_auth_row and tool_auth_row.gateway:
                        hydrated_gateway_auth_value = getattr(tool_auth_row.gateway, "auth_value", None)
                        if isinstance(hydrated_gateway_auth_value, dict):
                            gateway_auth_value = encode_auth(hydrated_gateway_auth_value)
                        elif isinstance(hydrated_gateway_auth_value, str):
                            gateway_auth_value = hydrated_gateway_auth_value
                        hydrated_gateway_query_params = getattr(tool_auth_row.gateway, "auth_query_params", None)
                        if isinstance(hydrated_gateway_query_params, dict):
                            gateway_auth_query_params = hydrated_gateway_query_params
                        hydrated_gateway_oauth_config = getattr(tool_auth_row.gateway, "oauth_config", None)
                        if isinstance(hydrated_gateway_oauth_config, dict):
                            gateway_oauth_config = hydrated_gateway_oauth_config

        gateway_auth_query_params_decrypted: Optional[Dict[str, str]] = None
        if gateway_auth_type == "query_param" and gateway_auth_query_params:
            gateway_auth_query_params_decrypted = {}
            for param_key, encrypted_value in gateway_auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        gateway_auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:  # noqa: S110
                        logger.debug(f"Failed to decrypt query param '{param_key}' for Rust MCP tool execution plan")
            if gateway_auth_query_params_decrypted and gateway_url:
                gateway_url = apply_query_param_auth(gateway_url, gateway_auth_query_params_decrypted)

        if gateway_ca_cert:
            return {"eligible": False, "fallbackReason": "custom-ca-certificate"}

        if not gateway_url:
            return {"eligible": False, "fallbackReason": "missing-gateway-url"}

        # Tracks whether we entered the OAuth authorization_code "no DB token" branch.
        # When True, the auth requirement is deferred to AFTER tool_pre_invoke hooks
        # run so plugins (e.g. Vault) can inject auth. The deny-path check below the
        # plugin invocation enforces the requirement locally with an actionable error.
        oauth_authcode_no_db_token = False

        if has_gateway and gateway_auth_type == "oauth" and isinstance(gateway_oauth_config, dict) and gateway_oauth_config:
            grant_type = gateway_oauth_config.get("grant_type", "client_credentials")
            if grant_type == "authorization_code":
                try:
                    # First-Party
                    from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                    with fresh_db_session() as token_db:
                        token_storage = TokenStorageService(token_db)
                        if not app_user_email:
                            raise ToolInvocationError(f"User authentication required for OAuth-protected gateway '{gateway_name}'. Please ensure you are authenticated.")
                        access_token = await token_storage.get_user_token(gateway_id_str, app_user_email)

                    if access_token:
                        headers = {"Authorization": f"Bearer {access_token}"}
                    else:
                        # No DB-stored OAuth token. Defer the auth requirement to after
                        # tool_pre_invoke hooks run so plugins (e.g. Vault) can inject
                        # auth headers. The post-hook check below enforces the requirement
                        # locally with an actionable error if no plugin provides auth.
                        oauth_authcode_no_db_token = True
                        headers = {}
                        logger.info(
                            "OAuth authorization_code gateway '%s' invoked without DB-stored token; deferring auth check to allow plugin injection",
                            gateway_name,
                            extra={"gateway_id": gateway_id_str, "user": app_user_email or "<unknown>"},
                        )
                except Exception as e:
                    logger.error(f"Failed to obtain stored OAuth token for gateway {gateway_name}: {e}")
                    raise ToolInvocationError(f"OAuth token retrieval failed for gateway: {str(e)}")
            else:
                try:
                    access_token = await self.oauth_manager.get_access_token(gateway_oauth_config, ca_certificate=gateway_ca_cert, client_cert=gateway_client_cert, client_key=gateway_client_key)
                    headers = {"Authorization": f"Bearer {access_token}"}
                except Exception as e:
                    logger.error(f"Failed to obtain OAuth access token for gateway {gateway_name}: {e}")
                    raise ToolInvocationError(f"OAuth authentication failed for gateway: {str(e)}")
        else:
            headers = decode_auth(gateway_auth_value) if gateway_auth_value else {}

        if request_headers:
            headers = compute_passthrough_headers_cached(
                request_headers,
                headers,
                passthrough_allowed,
                gateway_auth_type=gateway_auth_type,
                gateway_passthrough_headers=gateway_payload.get("passthrough_headers") if has_gateway else None,
            )

        runtime_headers = {str(header_name): str(header_value) for header_name, header_value in headers.items() if header_name and header_value}

        hook_global_context = None
        if has_pre_invoke or has_post_invoke:
            hook_global_context = self._build_rust_tool_hook_global_context(
                app_user_email=app_user_email,
                server_id=server_id,
                tool_gateway_id=tool_gateway_id,
                plugin_global_context=plugin_global_context,
                tool_payload=tool_payload,
                gateway_payload=gateway_payload,
                request_headers=request_headers,
            )

        native_post_invoke_retry_policy = None
        if has_post_invoke:
            native_post_invoke_retry_policy, requires_python_fallback = self._build_rust_native_tool_post_invoke_retry_policy(plugin_manager, name, hook_global_context)
            if requires_python_fallback:
                return {"eligible": False, "fallbackReason": "post-invoke-hooks-configured"}

        # Run tool_pre_invoke hooks so that plugins (e.g. wxo_connections) can
        # inject credentials and clean arguments before the Rust direct call.
        modified_args = arguments
        if has_pre_invoke and arguments is not None:
            pre_result, _ = await plugin_manager.invoke_hook(
                ToolHookType.TOOL_PRE_INVOKE,
                payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=dict(runtime_headers))),
                global_context=hook_global_context,
                local_contexts=plugin_context_table,
                violations_as_exceptions=True,
            )
            if pre_result.modified_payload:
                modified_args = pre_result.modified_payload.args
                if pre_result.modified_payload.name and pre_result.modified_payload.name != name:
                    tool_name_original = pre_result.modified_payload.name
                if pre_result.modified_payload.headers is not None:
                    plugin_headers = pre_result.modified_payload.headers.root if hasattr(pre_result.modified_payload.headers, "root") else {}
                    for hk, hv in plugin_headers.items():
                        if hk and hv:
                            runtime_headers[str(hk).lower()] = str(hv)

        # Defense in depth: strip X-Vault-Tokens (case-insensitive) from outbound
        # headers. The Vault plugin removes this header when it processes the token,
        # but stripping unconditionally prevents leakage when the plugin is disabled,
        # errors in permissive mode, or the header is mistakenly in passthrough_allowed.
        runtime_headers = {hk: hv for hk, hv in runtime_headers.items() if hk.lower() != "x-vault-tokens"}

        # OAuth authorization_code deny-path: if we entered the no-DB-token branch
        # above and no plugin (or other auth source) injected an Authorization header,
        # fail locally with an actionable error rather than relying on upstream 401.
        # This restores the original UX directing the user to /oauth/authorize/{id}
        # while still allowing legitimate plugin-injected auth (e.g. Vault) to satisfy
        # the requirement.
        if oauth_authcode_no_db_token and not any(hk.lower() == "authorization" for hk in runtime_headers):
            raise ToolInvocationError(f"Please authorize {gateway_name} first. Visit /oauth/authorize/{gateway_id_str} to complete OAuth flow.")

        runtime_headers = inject_trace_context_headers(runtime_headers)

        plan: Dict[str, Any] = {
            "eligible": True,
            "transport": transport,
            "serverUrl": gateway_url,
            "remoteToolName": tool_name_original,
            "headers": runtime_headers,
            "timeoutMs": int(effective_timeout * 1000),
            "gatewayId": tool_gateway_id,
            "toolName": name,
            "toolId": tool_id or None,
            "serverId": server_id,
        }
        if native_post_invoke_retry_policy is not None:
            plan["postInvokeRetryPolicy"] = native_post_invoke_retry_policy
        if has_pre_invoke:
            plan["hasPreInvokeHooks"] = True
            if modified_args is not None:
                plan["modifiedArgs"] = modified_args
        return plan

    def _build_rust_tool_hook_global_context(
        self,
        *,
        app_user_email: Optional[str],
        server_id: Optional[str],
        tool_gateway_id: Optional[str],
        plugin_global_context: Optional[GlobalContext],
        tool_payload: Optional[Dict[str, Any]],
        gateway_payload: Optional[Dict[str, Any]],
        request_headers: Optional[Dict[str, str]] = None,
    ) -> GlobalContext:
        """Build plugin global context for Rust-direct tool plan resolution.

        Args:
            app_user_email: Effective authenticated user for plugin context.
            server_id: Explicit virtual server scope from the request.
            tool_gateway_id: Resolved tool gateway id.
            plugin_global_context: Existing middleware context if available.
            tool_payload: Resolved tool payload.
            gateway_payload: Resolved gateway payload.
            request_headers: Request headers for extracting content type.

        Returns:
            GlobalContext primed with the same metadata the Python invoke path exposes.
        """
        # Derive tenant_id from the tool payload so rate limiting and other
        # tenant-scoped plugin behaviour works on the fallback path where
        # middleware didn't run and _propagate_tenant_id never got a chance
        # to fill it in. Non-string team_id values are ignored defensively.
        payload_team_id = tool_payload.get("team_id") if tool_payload else None
        hook_tenant_id = _extract_tenant_id_from_payload(payload_team_id)

        if plugin_global_context:
            hook_global_context = plugin_global_context
            _apply_tool_payload_to_global_context(hook_global_context, tool_gateway_id, app_user_email, hook_tenant_id)
        else:
            request_id = get_correlation_id() or uuid.uuid4().hex
            context_server_id = tool_gateway_id if tool_gateway_id and isinstance(tool_gateway_id, str) else server_id
            content_type = request_headers.get("content-type") if request_headers else None
            hook_global_context = GlobalContext(request_id=request_id, server_id=context_server_id, tenant_id=hook_tenant_id, user=app_user_email, content_type=content_type)

        tool_metadata: Optional[PydanticTool] = self._pydantic_tool_from_payload(tool_payload) if tool_payload else None
        gateway_metadata: Optional[PydanticGateway] = self._pydantic_gateway_from_payload(gateway_payload) if gateway_payload else None
        if tool_metadata:
            hook_global_context.metadata[TOOL_METADATA] = tool_metadata
        if gateway_metadata:
            hook_global_context.metadata[GATEWAY_METADATA] = gateway_metadata
        return hook_global_context

    def _build_rust_native_tool_post_invoke_retry_policy(
        self,
        plugin_manager: Optional[Any],
        tool_name: str,
        hook_global_context: Optional[GlobalContext],
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Return a native Rust retry policy when the active post-invoke hooks allow it.

        The Rust runtime only supports native post-invoke execution for the
        default retry-with-backoff plugin. Any other active `tool_post_invoke`
        hook must still force the call back to Python to preserve plugin semantics.

        Args:
            plugin_manager: Plugin manager instance (may be None).
            tool_name: Requested tool name.
            hook_global_context: Resolved plugin context for condition matching.

        Returns:
            Tuple of `(policy, requires_python_fallback)`.
        """
        if not plugin_manager or not plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
            return (None, False)

        # Third-Party
        from cpex.framework import PluginMode  # pylint: disable=import-outside-toplevel
        from cpex.framework.utils import payload_matches  # pylint: disable=import-outside-toplevel

        global_context = hook_global_context or GlobalContext(request_id=get_correlation_id() or uuid.uuid4().hex)
        payload = ToolPostInvokePayload(name=tool_name, result={})
        hook_refs = plugin_manager._registry.get_hook_refs_for_hook(hook_type=ToolHookType.TOOL_POST_INVOKE)  # pylint: disable=protected-access

        active_hook_refs = []
        for hook_ref in hook_refs:
            if hook_ref.plugin_ref.mode == PluginMode.DISABLED:
                continue
            if hook_ref.plugin_ref.conditions and not payload_matches(payload, ToolHookType.TOOL_POST_INVOKE, hook_ref.plugin_ref.conditions, global_context):
                continue
            active_hook_refs.append(hook_ref)

        if not active_hook_refs:
            return (None, False)

        if len(active_hook_refs) != 1 or active_hook_refs[0].plugin_ref.name != "RetryWithBackoffPlugin":
            return (None, True)

        retry_hook = active_hook_refs[0]
        try:
            effective_cfg = _build_retry_policy_config(retry_hook.plugin_ref.plugin.config.config or {}, tool_name)
        except (TypeError, ValueError):
            return (None, True)

        if effective_cfg["check_text_content"]:
            return (None, True)

        return (
            {
                "kind": "retry_with_backoff",
                "maxRetries": effective_cfg["max_retries"],
                "backoffBaseMs": effective_cfg["backoff_base_ms"],
                "maxBackoffMs": effective_cfg["max_backoff_ms"],
                "retryOnStatus": effective_cfg["retry_on_status"],
                "jitter": effective_cfg["jitter"],
            },
            False,
        )

    def _load_invocable_tools(self, db: Session, name: str, server_id: Optional[str] = None) -> List[DbTool]:
        """Load candidate tools for invocation, narrowing to a virtual server when possible.

        Args:
            db: Active database session.
            name: Tool name to resolve.
            server_id: Optional virtual server identifier used to constrain results.

        Returns:
            A list of candidate tool ORM rows matching the request.
        """
        query = select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.name == name)  # pylint: disable=comparison-with-callable
        if server_id:
            query = query.join(server_tool_association, DbTool.id == server_tool_association.c.tool_id).where(server_tool_association.c.server_id == server_id)
        return db.execute(query).scalars().all()

    # ------------------------------------------------------------------
    # Retry helpers (used by invoke_tool)
    # ------------------------------------------------------------------

    async def _run_timeout_post_invoke(
        self,
        name: str,
        effective_timeout: float,
        global_context: Any,
        context_table: Any,
        plugin_manager: Any = None,
    ) -> None:
        """Invoke post-invoke plugins after a timeout and raise with retry signal if requested.

        Called from each transport-specific timeout handler so the retry plugin
        can record the failure and (optionally) request a retry.  If the plugin
        sets ``retry_delay_ms > 0``, a ``ToolTimeoutError`` carrying the delay
        is raised immediately; otherwise control returns to the caller which
        raises a plain ``ToolTimeoutError``.

        Args:
            name: Tool name.
            effective_timeout: Timeout duration in seconds.
            global_context: Plugin global context for cross-hook state.
            context_table: Plugin local context table for per-plugin state.
            plugin_manager: Optional pre-fetched plugin manager to avoid redundant lookups.

        Raises:
            ToolTimeoutError: When the retry plugin requests a delayed retry.
        """
        if context_table:
            for ctx in context_table.values():
                ctx.set_state("cb_timeout_failure", True)

        if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
            timeout_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation timed out after {effective_timeout}s")], is_error=True)
            timeout_post_result, _ = await plugin_manager.invoke_hook(
                ToolHookType.TOOL_POST_INVOKE,
                payload=ToolPostInvokePayload(name=name, result=timeout_error_result.model_dump(by_alias=True)),
                global_context=global_context,
                local_contexts=context_table,
                violations_as_exceptions=False,
            )
            if timeout_post_result and timeout_post_result.retry_delay_ms > 0:
                raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s", retry_delay_ms=timeout_post_result.retry_delay_ms)

    async def _retry_tool_invocation(
        self,
        delay_ms: int,
        retry_attempt: int,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Any,
        app_user_email: Optional[str],
        user_email: Optional[str],
        token_teams: Optional[List[str]],
        server_id: Optional[str],
        context_table: Any,
        global_context: Any,
        meta_data: Optional[Dict[str, Any]],
        skip_pre_invoke: bool,
        path_label: str,
    ) -> "ToolResult":
        """Sleep for the plugin-requested delay, then recursively re-invoke the tool.

        The sleep is cancellation-aware: if the calling task is cancelled (e.g.
        client disconnect) the ``CancelledError`` propagates immediately instead
        of wasting time on a retry that nobody will consume.

        Args:
            delay_ms: Backoff delay in milliseconds before retrying.
            retry_attempt: Current zero-based retry counter.
            name: Tool name to re-invoke.
            arguments: Tool arguments to forward.
            request_headers: Original request headers.
            app_user_email: ContextForge user email for OAuth.
            user_email: User email for authorization.
            token_teams: Team IDs from JWT token.
            server_id: Virtual server ID for scoping.
            context_table: Plugin local context table.
            global_context: Plugin global context.
            meta_data: Optional metadata dictionary.
            skip_pre_invoke: Whether to skip pre-invoke hooks.
            path_label: Label for log messages (success/timeout/exception).

        Returns:
            ToolResult from the retried invocation.
        """
        logger.debug(
            "tool_service: retry requested (%s) for tool=%s attempt=%d/%d delay_ms=%d",
            path_label,
            name,
            retry_attempt + 1,
            settings.max_tool_retries,
            delay_ms,
        )
        await asyncio.sleep(delay_ms / 1000)
        with fresh_db_session() as retry_db:
            return await self.invoke_tool(
                db=retry_db,
                name=name,
                arguments=arguments,
                request_headers=request_headers,
                app_user_email=app_user_email,
                user_email=user_email,
                token_teams=token_teams,
                server_id=server_id,
                plugin_context_table=context_table,
                plugin_global_context=global_context,
                meta_data=meta_data,
                skip_pre_invoke=skip_pre_invoke,
                retry_attempt=retry_attempt + 1,
            )

    async def invoke_tool(
        self,
        db: Session,
        name: str,
        arguments: Dict[str, Any],
        request_headers: Optional[Dict[str, str]] = None,
        app_user_email: Optional[str] = None,
        user_email: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        server_id: Optional[str] = None,
        plugin_context_table: Optional[PluginContextTable] = None,
        plugin_global_context: Optional[GlobalContext] = None,
        meta_data: Optional[Dict[str, Any]] = None,
        skip_pre_invoke: bool = False,
        retry_attempt: int = 0,
    ) -> ToolResult:
        """
        Invoke a registered tool and record execution metrics.

        Args:
            db: Database session.
            name: Name of tool to invoke.
            arguments: Tool arguments.
            request_headers (Optional[Dict[str, str]], optional): Headers from the request to pass through.
                Defaults to None.
            app_user_email (Optional[str], optional): ContextForge user email for OAuth token retrieval.
                Required for OAuth-protected gateways.
            user_email (Optional[str], optional): User email for authorization checks.
                None = unauthenticated request.
            token_teams (Optional[List[str]], optional): Team IDs from JWT token for authorization.
                None = unrestricted admin, [] = public-only, [...] = team-scoped.
            server_id (Optional[str], optional): Virtual server ID for server scoping enforcement.
                If provided, tool must be attached to this server.
            plugin_context_table: Optional plugin context table from previous hooks for cross-hook state sharing.
            plugin_global_context: Optional global context from middleware for consistency across hooks.
            meta_data: Optional metadata dictionary for additional context (e.g., request ID).
            skip_pre_invoke: When True, skip TOOL_PRE_INVOKE hooks (used by trusted Rust fallback path).
            retry_attempt: Zero-based retry counter; 0 = original call.  Incremented by the retry
                loop and compared against ``settings.max_tool_retries``.

        Returns:
            Tool invocation result.

        Raises:
            ToolNotFoundError: If tool not found or access denied.
            ToolInvocationError: If invocation fails or A2A authentication decryption fails.
            ToolTimeoutError: If tool invocation times out.
            PluginViolationError: If plugin blocks tool invocation.
            PluginError: If encounters issue with plugin.

        Examples:
            >>> # Note: This method requires extensive mocking of SQLAlchemy models,
            >>> # database relationships, and caching infrastructure, which is not
            >>> # suitable for doctests. See tests/unit/mcpgateway/services/test_tool_service.py
            >>> pass  # doctest: +SKIP
        """
        # pylint: disable=comparison-with-callable
        logger.info(f"Invoking tool: {name} with arguments: {arguments.keys() if arguments else None} and headers: {request_headers.keys() if request_headers else None}, server_id={server_id}")
        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 1: Check for X-Context-Forge-Gateway-Id header for direct_proxy mode (no DB lookup)
        # ═══════════════════════════════════════════════════════════════════════════
        gateway_id_from_header = extract_gateway_id_from_headers(request_headers)

        # If X-Context-Forge-Gateway-Id header is present, check if gateway is in direct_proxy mode
        is_direct_proxy = False
        tool = None
        gateway = None
        tool_payload: Dict[str, Any] = {}
        gateway_payload: Optional[Dict[str, Any]] = None

        if gateway_id_from_header:
            # Look up gateway to check if it's in direct_proxy mode
            gateway = db.execute(select(DbGateway).where(DbGateway.id == gateway_id_from_header)).scalar_one_or_none()
            if gateway and gateway.gateway_mode == "direct_proxy" and settings.mcpgateway_direct_proxy_enabled:
                # SECURITY: Check gateway access before allowing direct proxy
                # This prevents RBAC bypass where any authenticated user could invoke tools
                # on any gateway just by knowing the gateway ID
                if not await check_gateway_access(db, gateway, user_email, token_teams):
                    logger.warning(f"Access denied to gateway {gateway_id_from_header} in direct_proxy mode for user {SecurityValidator.sanitize_log_message(user_email)}")
                    raise ToolNotFoundError(f"Tool not found: {name}")

                is_direct_proxy = True
                # Build minimal gateway payload for direct proxy (no tool lookup needed)
                gateway_payload = {
                    "id": str(gateway.id),
                    "name": gateway.name,
                    "url": gateway.url,
                    "auth_type": gateway.auth_type,
                    # DbGateway.auth_value is JSON (dict); downstream code expects an encoded str.
                    "auth_value": encode_auth(gateway.auth_value) if isinstance(gateway.auth_value, dict) else gateway.auth_value,
                    "auth_query_params": gateway.auth_query_params,
                    "oauth_config": gateway.oauth_config,
                    "ca_certificate": gateway.ca_certificate,
                    "ca_certificate_sig": gateway.ca_certificate_sig,
                    "passthrough_headers": gateway.passthrough_headers,
                    "gateway_mode": gateway.gateway_mode,
                }
                # Create minimal tool payload for direct proxy (no DB tool needed)
                tool_payload = {
                    "id": None,  # No tool ID in direct proxy mode
                    "name": name,
                    "original_name": name,
                    "enabled": True,
                    "reachable": True,
                    "integration_type": "MCP",
                    "request_type": "streamablehttp",  # Default to streamablehttp
                    "gateway_id": str(gateway.id),
                }
                logger.info(f"Direct proxy mode via X-Context-Forge-Gateway-Id header: passing tool '{name}' directly to remote MCP server at {gateway.url}")
            elif gateway:
                logger.debug(f"Gateway {gateway_id_from_header} found but not in direct_proxy mode (mode: {gateway.gateway_mode}), using normal lookup")
            else:
                logger.warning(f"Gateway {gateway_id_from_header} specified in X-Context-Forge-Gateway-Id header not found")

        # Normal mode: look up tool in database/cache
        if not is_direct_proxy:
            tool_lookup_cache = _get_tool_lookup_cache()
            cached_payload = await tool_lookup_cache.get(name) if tool_lookup_cache.enabled else None

            if cached_payload:
                status = cached_payload.get("status", "active")
                if status == "missing":
                    raise ToolNotFoundError(f"Tool not found: {name}")
                if status == "inactive":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
                if status == "offline":
                    raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")
                tool_payload = cached_payload.get("tool") or {}
                gateway_payload = cached_payload.get("gateway")

        if not tool_payload:
            # Eager load tool WITH gateway in single query to prevent lazy load N+1
            # Use a single query to avoid a race between separate enabled/inactive lookups.
            # Use scalars().all() instead of scalar_one_or_none() to handle duplicate
            # tool names across teams without crashing on MultipleResultsFound.
            tools = self._load_invocable_tools(db, name, server_id=server_id)

            if not tools:
                raise ToolNotFoundError(f"Tool not found: {name}")

            multiple_found = len(tools) > 1
            if not multiple_found:
                tool = tools[0]
            else:
                # Multiple tools found with same name — filter by access using
                # _check_tool_access (same rules as list_tools) and prioritize.
                # Priority (lower is better): team (0) > private (1) > public (2)
                visibility_priority = {"team": 0, "private": 1, "public": 2}
                accessible_tools: list[tuple[int, Any]] = []
                for t in tools:
                    tool_dict = {"visibility": t.visibility, "team_id": t.team_id, "owner_email": t.owner_email}
                    if await self._check_tool_access(db, tool_dict, user_email, token_teams):
                        priority = visibility_priority.get(t.visibility, 99)
                        accessible_tools.append((priority, t))

                if not accessible_tools:
                    raise ToolNotFoundError(f"Tool not found: {name}")

                accessible_tools.sort(key=lambda x: x[0])

                # Check for ambiguity at the highest priority level
                best_priority = accessible_tools[0][0]
                best_tools = [t for p, t in accessible_tools if p == best_priority]

                if len(best_tools) > 1:
                    raise ToolInvocationError(f"Multiple tools found with name '{name}' at same priority level. Tool name is ambiguous.")

                tool = best_tools[0]

            if not tool.enabled:
                raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")

            if not tool.reachable:
                await tool_lookup_cache.set_negative(name, "offline")
                raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

            gateway = tool.gateway
            cache_payload = self._build_tool_cache_payload(tool, gateway)
            tool_payload = cache_payload.get("tool") or {}
            gateway_payload = cache_payload.get("gateway")
            # Skip caching when multiple tools share a name — resolution is
            # user-dependent, so a cached result could be wrong for other users.
            if not multiple_found:
                await tool_lookup_cache.set(name, cache_payload, gateway_id=tool_payload.get("gateway_id"))

        if tool_payload.get("enabled") is False:
            raise ToolNotFoundError(f"Tool '{name}' exists but is inactive")
        if tool_payload.get("reachable") is False:
            raise ToolNotFoundError(f"Tool '{name}' exists but is currently offline. Please verify if it is running.")

        # ═══════════════════════════════════════════════════════════════════════════
        # SECURITY: Check tool access based on visibility and team membership
        # Skip these checks for direct_proxy mode (no tool in database)
        # ═══════════════════════════════════════════════════════════════════════════
        if not is_direct_proxy:
            if not await self._check_tool_access(db, tool_payload, user_email, token_teams):
                # Don't reveal tool existence - return generic "not found"
                raise ToolNotFoundError(f"Tool not found: {name}")

            # ═══════════════════════════════════════════════════════════════════════════
            # SECURITY: Enforce server scoping if server_id is provided
            # Tool must be attached to the specified virtual server
            # ═══════════════════════════════════════════════════════════════════════════
            if server_id:
                tool_id_for_check = tool_payload.get("id")
                if not tool_id_for_check:
                    # Cannot verify server membership without tool ID - deny access
                    # This should not happen with properly cached tools, but fail safe
                    logger.warning(f"Tool '{name}' has no ID in payload, cannot verify server membership")
                    raise ToolNotFoundError(f"Tool not found: {name}")

                server_match = db.execute(
                    select(server_tool_association.c.tool_id).where(
                        server_tool_association.c.server_id == server_id,
                        server_tool_association.c.tool_id == tool_id_for_check,
                    )
                ).first()
                if not server_match:
                    raise ToolNotFoundError(f"Tool not found: {name}")

        # Extract A2A-related data from annotations (will be used after db.close() if A2A tool)
        tool_annotations = tool_payload.get("annotations") or {}
        tool_integration_type = tool_payload.get("integration_type")

        # Get passthrough headers from in-memory cache (Issue #1715)
        # This eliminates 42,000+ redundant DB queries under load
        passthrough_allowed = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)

        # Access gateway now (already eager-loaded) to prevent later lazy load
        if tool is not None:
            gateway = tool.gateway

        # ═══════════════════════════════════════════════════════════════════════════
        # PHASE 2: Extract all needed data to local variables before network I/O
        # This allows us to release the DB session before making HTTP calls
        # ═══════════════════════════════════════════════════════════════════════════
        tool_id = tool_payload.get("id") or (str(tool.id) if tool else "")
        tool_name_original = tool_payload.get("original_name") or tool_payload.get("name") or name
        tool_name_computed = tool_payload.get("name") or name
        tool_url = tool_payload.get("url")
        tool_integration_type = tool_payload.get("integration_type")
        tool_request_type = tool_payload.get("request_type")
        tool_headers = _decrypt_tool_headers_for_runtime(tool_payload.get("headers") or {})
        tool_auth_type = tool_payload.get("auth_type")
        tool_auth_value = tool_payload.get("auth_value")
        if tool is not None:
            runtime_tool_auth_value = getattr(tool, "auth_value", None)
            if isinstance(runtime_tool_auth_value, str):
                tool_auth_value = runtime_tool_auth_value
        if not isinstance(tool_auth_value, str):
            tool_auth_value = None
        tool_jsonpath_filter = tool_payload.get("jsonpath_filter")
        tool_output_schema = tool_payload.get("output_schema")
        tool_oauth_config = tool_payload.get("oauth_config") if isinstance(tool_payload.get("oauth_config"), dict) else None
        if tool is not None:
            runtime_tool_oauth_config = getattr(tool, "oauth_config", None)
            if isinstance(runtime_tool_oauth_config, dict):
                tool_oauth_config = runtime_tool_oauth_config
        tool_gateway_id = tool_payload.get("gateway_id")
        tool_query_mapping = tool_payload.get("query_mapping") if isinstance(tool_payload.get("query_mapping"), dict) else None
        if tool_query_mapping is not None:
            tool_query_mapping = _validate_mapping_contents(tool_query_mapping, "query_mapping", name)
        tool_header_mapping = tool_payload.get("header_mapping") if isinstance(tool_payload.get("header_mapping"), dict) else None
        if tool_header_mapping is not None:
            tool_header_mapping = _validate_mapping_contents(tool_header_mapping, "header_mapping", name)

        # Get effective timeout: per-tool timeout_ms (in seconds) or global fallback
        # timeout_ms is stored in milliseconds, convert to seconds
        tool_timeout_ms = tool_payload.get("timeout_ms")
        effective_timeout = (tool_timeout_ms / 1000) if tool_timeout_ms else settings.tool_timeout

        # Save gateway existence as local boolean BEFORE db.close()
        # to avoid checking ORM object truthiness after session is closed
        has_gateway = gateway_payload is not None
        gateway_url = gateway_payload.get("url") if has_gateway else None
        gateway_name = gateway_payload.get("name") if has_gateway else None
        gateway_auth_type = gateway_payload.get("auth_type") if has_gateway else None
        gateway_auth_value = gateway_payload.get("auth_value") if has_gateway and isinstance(gateway_payload.get("auth_value"), str) else None
        gateway_auth_query_params = gateway_payload.get("auth_query_params") if has_gateway and isinstance(gateway_payload.get("auth_query_params"), dict) else None
        gateway_oauth_config = gateway_payload.get("oauth_config") if has_gateway and isinstance(gateway_payload.get("oauth_config"), dict) else None
        if has_gateway and gateway is not None:
            runtime_gateway_auth_value = getattr(gateway, "auth_value", None)
            if isinstance(runtime_gateway_auth_value, dict):
                gateway_auth_value = encode_auth(runtime_gateway_auth_value)
            elif isinstance(runtime_gateway_auth_value, str):
                gateway_auth_value = runtime_gateway_auth_value
            runtime_gateway_query_params = getattr(gateway, "auth_query_params", None)
            if isinstance(runtime_gateway_query_params, dict):
                gateway_auth_query_params = runtime_gateway_query_params
            runtime_gateway_oauth_config = getattr(gateway, "oauth_config", None)
            if isinstance(runtime_gateway_oauth_config, dict):
                gateway_oauth_config = runtime_gateway_oauth_config
        # MCP invoke path: cert params come from the serialized gateway_payload dict
        # (the ORM session that produced the gateway object may already be closed).
        gateway_ca_cert = gateway_payload.get("ca_certificate") if has_gateway else None
        gateway_ca_cert_sig = gateway_payload.get("ca_certificate_sig") if has_gateway else None
        gateway_client_cert = gateway_payload.get("client_cert") if has_gateway else None
        gateway_client_key = gateway_payload.get("client_key") if has_gateway else None
        gateway_passthrough = gateway_payload.get("passthrough_headers") if has_gateway else None
        gateway_id_str = gateway_payload.get("id") if has_gateway else None

        # Cache payload intentionally excludes sensitive auth material. For cache hits
        # (tool is None), hydrate auth-related fields from DB only when needed.
        if tool is None:
            requires_tool_auth_hydration = tool_auth_type in {"basic", "bearer", "authheaders", "oauth"}
            requires_gateway_auth_hydration = has_gateway and gateway_auth_type in {"basic", "bearer", "authheaders", "oauth", "query_param"}
            if requires_tool_auth_hydration or requires_gateway_auth_hydration:
                tool_id_for_hydration = tool_payload.get("id")
                if tool_id_for_hydration:
                    tool_auth_row = db.execute(select(DbTool).options(joinedload(DbTool.gateway)).where(DbTool.id == tool_id_for_hydration)).scalar_one_or_none()
                    if tool_auth_row:
                        hydrated_tool_auth_value = getattr(tool_auth_row, "auth_value", None)
                        if isinstance(hydrated_tool_auth_value, str):
                            tool_auth_value = hydrated_tool_auth_value
                        hydrated_tool_oauth_config = getattr(tool_auth_row, "oauth_config", None)
                        if isinstance(hydrated_tool_oauth_config, dict):
                            tool_oauth_config = hydrated_tool_oauth_config
                        if has_gateway and tool_auth_row.gateway:
                            hydrated_gateway_auth_value = getattr(tool_auth_row.gateway, "auth_value", None)
                            if isinstance(hydrated_gateway_auth_value, dict):
                                gateway_auth_value = encode_auth(hydrated_gateway_auth_value)
                            elif isinstance(hydrated_gateway_auth_value, str):
                                gateway_auth_value = hydrated_gateway_auth_value
                            hydrated_gateway_query_params = getattr(tool_auth_row.gateway, "auth_query_params", None)
                            if isinstance(hydrated_gateway_query_params, dict):
                                gateway_auth_query_params = hydrated_gateway_query_params
                            hydrated_gateway_oauth_config = getattr(tool_auth_row.gateway, "oauth_config", None)
                            if isinstance(hydrated_gateway_oauth_config, dict):
                                gateway_oauth_config = hydrated_gateway_oauth_config

        # Decrypt and apply query param auth to URL if applicable
        gateway_auth_query_params_decrypted: Optional[Dict[str, str]] = None
        if gateway_auth_type == "query_param" and gateway_auth_query_params:
            # Decrypt the query param values
            gateway_auth_query_params_decrypted = {}
            for param_key, encrypted_value in gateway_auth_query_params.items():
                if encrypted_value:
                    try:
                        decrypted = decode_auth(encrypted_value)
                        gateway_auth_query_params_decrypted[param_key] = decrypted.get(param_key, "")
                    except Exception:  # noqa: S110 - intentionally skip failed decryptions
                        # Silently skip params that fail decryption (may be corrupted or use old key)
                        logger.debug(f"Failed to decrypt query param '{param_key}' for tool invocation")
            # Apply query params to gateway URL
            if gateway_auth_query_params_decrypted and gateway_url:
                gateway_url = apply_query_param_auth(gateway_url, gateway_auth_query_params_decrypted)

        # Create Pydantic models for plugins BEFORE HTTP calls (use ORM objects while still valid)
        # This prevents lazy loading during HTTP calls
        tool_metadata: Optional[PydanticTool] = None
        gateway_metadata: Optional[PydanticGateway] = None
        # Resolve per-tool context_id so DB plugin bindings (ToolPluginBinding) are applied.
        # Lazy import avoids circular: gateway_plugin_manager → services.__init__ → tool_service.
        # First-Party
        from mcpgateway.plugins.gateway_plugin_manager import make_context_id  # pylint: disable=import-outside-toplevel

        _tool_team_id = tool_payload.get("team_id")
        # Use name (the gateway-scoped unique identifier, e.g. "mac-fs-read-file") as the binding key.
        # original_name (e.g. "read_file") is only unique per gateway, so two gateways in the same
        # team can share the same original_name — making it ambiguous as a binding key.
        # name is enforced unique per team by DB constraint uq_team_owner_email_name_tool.
        _binding_tool_name = tool_payload.get("name") or name
        plugin_context_id = make_context_id(str(_tool_team_id), _binding_tool_name) if _tool_team_id else server_id
        plugin_manager = await self._get_plugin_manager(plugin_context_id)
        logger.debug("invoke_tool: plugin_context_id=%r plugin_manager=%r", plugin_context_id, plugin_manager)
        if plugin_manager:
            if tool is not None:
                tool_metadata = PydanticTool.model_validate(tool)
                if has_gateway and gateway is not None:
                    gateway_metadata = PydanticGateway.model_validate(gateway)
            else:
                tool_metadata = self._pydantic_tool_from_payload(tool_payload)
                if has_gateway and gateway_payload:
                    gateway_metadata = self._pydantic_gateway_from_payload(gateway_payload)

        tool_for_validation = tool if tool is not None else SimpleNamespace(output_schema=tool_output_schema, name=tool_name_computed)

        # ═══════════════════════════════════════════════════════════════════════════
        # A2A Agent Data Extraction (must happen before db.close())
        # Extract all A2A agent data to local variables so HTTP call can happen after db.close()
        # ═══════════════════════════════════════════════════════════════════════════
        a2a_agent_name: Optional[str] = None
        a2a_agent_endpoint_url: Optional[str] = None
        a2a_agent_type: Optional[str] = None
        a2a_agent_protocol_version: Optional[str] = None
        a2a_agent_auth_type: Optional[str] = None
        a2a_agent_auth_value: Optional[str] = None
        a2a_agent_auth_query_params: Optional[Dict[str, str]] = None

        if tool_integration_type == "A2A" and "a2a_agent_id" in tool_annotations:
            a2a_agent_id = tool_annotations.get("a2a_agent_id")
            if not a2a_agent_id:
                raise ToolNotFoundError(f"A2A tool '{name}' missing agent ID in annotations")

            # Query for the A2A agent
            agent_query = select(DbA2AAgent).where(DbA2AAgent.id == a2a_agent_id)
            a2a_agent = db.execute(agent_query).scalar_one_or_none()

            if not a2a_agent:
                raise ToolNotFoundError(f"A2A agent not found for tool '{name}' (agent ID: {a2a_agent_id})")

            if not a2a_agent.enabled:
                raise ToolNotFoundError(f"A2A agent '{a2a_agent.name}' is disabled")

            # Extract all needed data to local variables before db.close()
            a2a_agent_name = a2a_agent.name
            a2a_agent_endpoint_url = a2a_agent.endpoint_url
            a2a_agent_type = a2a_agent.agent_type
            a2a_agent_protocol_version = a2a_agent.protocol_version
            a2a_agent_auth_type = a2a_agent.auth_type
            a2a_agent_auth_value = a2a_agent.auth_value
            a2a_agent_auth_query_params = a2a_agent.auth_query_params

        # ═══════════════════════════════════════════════════════════════════════════
        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents connection pool exhaustion during slow upstream requests.
        # All needed data has been extracted to local variables above.
        # The session will be closed again by FastAPI's get_db() finally block (safe no-op).
        # ═══════════════════════════════════════════════════════════════════════════
        db.commit()  # End read-only transaction cleanly (commit not rollback to avoid inflating rollback stats)
        db.close()

        # Plugin hook: tool pre-invoke
        # Use existing context_table from previous hooks if available
        context_table = plugin_context_table

        # Reuse existing global_context from middleware or create new one
        # IMPORTANT: Use local variables (tool_gateway_id) instead of ORM object access
        # Derive tenant_id from the tool payload so by_tenant rate limiting
        # and other tenant-scoped plugin behaviour works on the fallback
        # path where middleware didn't run. Non-string values are ignored.
        payload_tenant_id = _extract_tenant_id_from_payload(_tool_team_id)

        if plugin_global_context:
            global_context = plugin_global_context
            _apply_tool_payload_to_global_context(global_context, tool_gateway_id, app_user_email, payload_tenant_id)
        else:
            # Create new context (fallback when middleware didn't run)
            # Use correlation ID from context if available, otherwise generate new one
            request_id = get_correlation_id() or uuid.uuid4().hex
            context_server_id = tool_gateway_id if tool_gateway_id and isinstance(tool_gateway_id, str) else "unknown"
            content_type = request_headers.get("content-type") if request_headers else None
            global_context = GlobalContext(request_id=request_id, server_id=context_server_id, tenant_id=payload_tenant_id, user=app_user_email, content_type=content_type)

        start_time = time.monotonic()
        success = False
        error_message = None
        tool_result: Optional[ToolResult] = None
        tool_team_scope = format_trace_team_scope(token_teams)

        # Get trace_id from context for database span creation
        trace_id = current_trace_id.get()
        db_span_id = None
        db_span_ended = False
        observability_service = ObservabilityService() if trace_id else None

        # Create database span for observability_spans table
        if trace_id and observability_service:
            try:
                # start_span creates its own independent session (issue #3883)
                db_span_id = observability_service.start_span(
                    trace_id=trace_id,
                    name="tool.invoke",
                    kind="client",
                    resource_type="tool",
                    resource_name=name,
                    resource_id=tool_id,
                    attributes={
                        "tool.name": name,
                        "tool.id": tool_id,
                        "tool.integration_type": tool_integration_type,
                        "tool.gateway_id": tool_gateway_id,
                        "arguments_count": len(arguments) if arguments else 0,
                        "has_headers": bool(request_headers),
                    },
                )
                logger.debug(f"✓ Created tool.invoke span: {db_span_id} for tool: {name}")
            except Exception as e:
                logger.warning(f"Failed to start observability span for tool invocation: {e}")
                db_span_id = None

        # Create a trace span for OpenTelemetry export (Jaeger, Zipkin, etc.)
        span_attributes = {
            "tool.name": name,
            "tool.id": tool_id,
            "tool.integration_type": tool_integration_type,
            "tool.gateway_id": tool_gateway_id,
            "arguments_count": len(arguments) if arguments else 0,
            "has_headers": bool(request_headers),
            "user.email": user_email or app_user_email or "anonymous",
            "team.scope": tool_team_scope,
            "server_id": server_id,
        }
        if is_input_capture_enabled("tool.invoke"):
            span_attributes["langfuse.observation.input"] = serialize_trace_payload(arguments or {})

        with create_span("tool.invoke", span_attributes) as span:
            try:
                # Create a lightweight lookup child span so Langfuse shows the invoke breakdown.
                with create_child_span(
                    "tool.lookup",
                    {
                        "tool.name": name,
                        "tool.id": tool_id,
                        "tool.integration_type": tool_integration_type,
                    },
                ):
                    headers = tool_headers.copy()
                if tool_integration_type == "REST":
                    # Handle OAuth authentication for REST tools
                    if tool_auth_type == "oauth" and isinstance(tool_oauth_config, dict) and tool_oauth_config:
                        try:
                            # REST invoke path: gateway ORM object is still attached to the
                            # active session, so attribute access is safe here.
                            access_token = await self.oauth_manager.get_access_token(
                                tool_oauth_config,
                                ca_certificate=gateway.ca_certificate if gateway else None,
                                client_cert=gateway.client_cert if gateway else None,
                                client_key=gateway.client_key if gateway else None,
                            )
                            headers["Authorization"] = f"Bearer {access_token}"
                        except Exception as e:
                            logger.error(f"Failed to obtain OAuth access token for tool {tool_name_computed}: {e}")
                            raise ToolInvocationError(f"OAuth authentication failed: {str(e)}")
                    else:
                        credentials = decode_auth(tool_auth_value) if tool_auth_value else {}
                        # Filter out empty header names/values to avoid "Illegal header name" errors
                        filtered_credentials = {k: v for k, v in credentials.items() if k and v}
                        headers.update(filtered_credentials)

                    # Use cached passthrough headers (no DB query needed)
                    if request_headers:
                        headers = compute_passthrough_headers_cached(
                            request_headers,
                            headers,
                            passthrough_allowed,
                            gateway_auth_type=None,
                            gateway_passthrough_headers=None,  # REST tools don't use gateway auth here
                        )
                        # Read MCP-Session-Id from downstream client (MCP protocol header)
                        # and normalize to x-mcp-session-id for our internal session affinity logic
                        # The pool will strip this before sending to upstream
                        # Check both mcp-session-id (direct client) and x-mcp-session-id (forwarded requests)
                        request_headers_lower = {k.lower(): v for k, v in request_headers.items()}
                        mcp_session_id = request_headers_lower.get("mcp-session-id") or request_headers_lower.get("x-mcp-session-id")
                        if mcp_session_id:
                            headers["x-mcp-session-id"] = mcp_session_id

                            worker_id = str(os.getpid())
                            session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id
                            logger.debug(f"[AFFINITY] Worker {worker_id} | Session {session_short}... | Tool: {name} | Normalized MCP-Session-Id → x-mcp-session-id for pool affinity")

                    # Inject identity propagation headers for REST tools
                    if global_context and global_context.user_context:
                        headers.update(build_identity_headers(global_context.user_context))

                    if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE) and not skip_pre_invoke:
                        # Use pre-created Pydantic model from Phase 2 (no ORM access)
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        pre_result, context_table = await plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
                            global_context=global_context,
                            local_contexts=context_table,  # Pass context from previous hooks
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    # Build the payload based on integration type
                    payload = arguments.copy()

                    # Handle URL path and query parameter substitution (using local variable)
                    final_url = tool_url
                    if "{" in tool_url and "}" in tool_url:
                        # Extract ALL parameters (path and query) from URL template
                        url_params = re.findall(r"\{(\w+)\}", tool_url)
                        url_substitutions = {}

                        for param in url_params:
                            if param in payload:
                                url_substitutions[param] = payload.pop(param)  # Remove from payload
                                final_url = final_url.replace(f"{{{param}}}", str(url_substitutions[param]))
                            else:
                                raise ToolInvocationError(f"Required URL parameter '{param}' not found in arguments")

                    # --- Extract query params from URL if query_mapping or header_mapping is used ---
                    # When mappings are present (not None/empty), we strip query params from URL and apply transformations.
                    # When mappings are absent (None/empty), preserve query params in URL for signed URLs.
                    query_params = {}
                    # Treat empty dict same as None (no mapping configured)
                    has_query_mapping = tool_query_mapping is not None and tool_query_mapping != {}
                    has_header_mapping = tool_header_mapping is not None and tool_header_mapping != {}

                    if has_query_mapping or has_header_mapping:
                        parsed = urlparse(final_url)
                        final_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

                        if tool_query_mapping:
                            # Only mapped payload keys (renamed) are kept, merged on top of URL query params.
                            # Unmapped payload keys are intentionally dropped (mapping acts as an allowlist).
                            payload = apply_mapping_into_target(payload, tool_query_mapping, query_params)
                            # Reject non-scalar values that would be inappropriate as query parameters.
                            for qk, qv in payload.items():
                                if isinstance(qv, (dict, list)):
                                    raise ToolInvocationError(f"Tool '{name}': query_mapping produced non-scalar value for parameter '{qk}'")

                        # Headers are mapped from the original arguments (not the path-param-reduced payload)
                        # to preserve all available data for header injection.
                        if tool_header_mapping:
                            _validate_header_mapping_targets(tool_header_mapping, name)
                            headers = apply_mapping_into_target(arguments.copy(), tool_header_mapping, headers)
                            # Reject header values containing CRLF or null bytes to prevent header injection.
                            for hdr_name, hdr_val in headers.items():
                                if isinstance(hdr_val, str) and _INVALID_HEADER_VALUE_CHARS.search(hdr_val):
                                    raise ToolInvocationError(f"Tool '{name}': header_mapping produced value with illegal characters for header '{hdr_name}'")

                    # Use the tool's request_type rather than defaulting to POST (using local variable)
                    method = tool_request_type.upper() if tool_request_type else "POST"
                    _url_query_params = query_params if not tool_query_mapping else None

                    # Detect body encoding from the final Content-Type header (after auth/plugin/mapping modifications).
                    # Supports application/x-www-form-urlencoded and multipart/form-data in addition to the default JSON.
                    _ct_base = next((v for k, v in headers.items() if k.lower() == "content-type"), "").lower().split(";")[0].strip()

                    # For non-GET form-urlencoded and multipart requests without mappings,
                    # extract URL query params so they are forwarded via params= (query string)
                    # rather than being silently embedded in the URL or lost.  GET has its own
                    # extraction below; JSON POST intentionally preserves query params in the URL
                    # for signed-URL support.
                    if method != "GET" and not has_query_mapping and not has_header_mapping and _ct_base in ("application/x-www-form-urlencoded", "multipart/form-data"):
                        parsed = urlparse(final_url)
                        if parsed.query:
                            final_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                            _url_query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

                    with create_child_span("tool.gateway_call", {"tool.name": name, "tool.id": tool_id, "tool.integration_type": "REST"}):
                        rest_start_time = time.time()
                        try:
                            if method == "GET":
                                # For GET: Extract and merge URL query params with input arguments
                                if not has_query_mapping and not has_header_mapping:
                                    # When no mappings (None or empty), extract query params from URL
                                    parsed = urlparse(final_url)
                                    final_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                                    query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

                                    conflicts = set(payload.keys()) & set(query_params.keys())
                                    if conflicts:
                                        logger.warning(
                                            f"REST tool GET request has conflicting parameters between URL and input arguments. "
                                            f"URL query params will take precedence for: {', '.join(sorted(conflicts))}. "
                                            f"Tool: {name}"
                                        )

                                payload.update(query_params)
                                response = await asyncio.wait_for(self._http_client.get(final_url, params=payload, headers=headers), timeout=effective_timeout)
                            elif _ct_base == "application/x-www-form-urlencoded":
                                # NOTE: Intentional asymmetry with the JSON/default path below.
                                # Form-encoded bodies use params= to keep URL query params on the
                                # query string (semantically correct for form encoding), whereas
                                # the JSON path merges them into the body via payload.update() for
                                # backward compatibility and signed-URL support.
                                form_payload = {k: self._form_value_to_str(v) for k, v in payload.items()}
                                response = await asyncio.wait_for(self._http_client.request(method, final_url, data=form_payload, params=_url_query_params, headers=headers), timeout=effective_timeout)
                            elif _ct_base == "multipart/form-data":
                                # Strip Content-Type so httpx can set it with the correct boundary parameter.
                                # URL query params forwarded via params= (same asymmetry as form-urlencoded above).
                                headers_mp = {k: v for k, v in headers.items() if k.lower() != "content-type"}
                                files_payload = {k: (None, self._form_value_to_str(v)) for k, v in payload.items()}
                                response = await asyncio.wait_for(
                                    self._http_client.request(method, final_url, files=files_payload, params=_url_query_params, headers=headers_mp), timeout=effective_timeout
                                )
                            else:
                                # For POST/PUT/PATCH/DELETE: Different behavior based on mapping presence
                                if has_query_mapping or has_header_mapping:
                                    # When mappings are used (not None/empty), query params were already extracted and mapped
                                    # Merge them into the JSON body for backward compatibility with mapped tools
                                    payload.update(query_params)
                                # else: No mappings (None or empty) - preserve query params in URL for signed URL support
                                # (Azure SAS, AWS presigned URLs, webhook signatures, etc.)
                                response = await asyncio.wait_for(self._http_client.request(method, final_url, json=payload, headers=headers), timeout=effective_timeout)
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            rest_elapsed_ms = (time.time() - rest_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"REST tool invocation timed out: {tool_name_computed}",
                                component="tool_service",
                                correlation_id=get_correlation_id(),
                                duration_ms=rest_elapsed_ms,
                                metadata={"event": "tool_timeout", "tool_name": tool_name_computed, "timeout_seconds": effective_timeout},
                            )

                            # Manually trigger circuit breaker (or other plugins) on timeout
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug(
                                    "Failed to increment tool_timeout_counter for %s: %s",
                                    name,
                                    exc,
                                    exc_info=True,
                                )
                            if plugin_manager:
                                await self._run_timeout_post_invoke(name, effective_timeout, global_context, context_table, plugin_manager)

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        try:
                            response.raise_for_status()
                        except httpx.HTTPStatusError:
                            # Non-2xx response — parse body (may be HTML, plain text, XML, etc.)
                            try:
                                result = response.json()
                            except (json.JSONDecodeError, orjson.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
                                result = _handle_json_parse_error(response, e, is_error_response=True)
                            if "error" in result:
                                error_val = result["error"]
                            elif "response_text" in result:
                                error_val = f"HTTP {response.status_code}: {result['response_text']}"
                            else:
                                error_val = f"HTTP {response.status_code}"
                            tool_result = ToolResult(
                                content=[TextContent(type="text", text=error_val if isinstance(error_val, str) else orjson.dumps(error_val).decode())],
                                is_error=True,
                                structured_content={"status_code": response.status_code},
                            )
                            # Don't mark as successful — success remains False

                        # Handle 204 No Content responses that have no body
                        if tool_result is not None and tool_result.is_error:
                            pass  # Already handled by HTTPStatusError above
                        elif response.status_code == 204:
                            tool_result = ToolResult(content=[TextContent(type="text", text="Request completed successfully (No Content)")])
                            success = True
                        elif response.status_code not in [200, 201, 202, 206]:
                            # Non-standard 2xx codes (203, 205, 207, etc.) treated as errors
                            try:
                                result = response.json()
                            except (json.JSONDecodeError, orjson.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
                                result = _handle_json_parse_error(response, e, is_error_response=True)
                            error_val = result["error"] if "error" in result else "Tool error encountered"
                            tool_result = ToolResult(
                                content=[TextContent(type="text", text=error_val if isinstance(error_val, str) else orjson.dumps(error_val).decode())],
                                is_error=True,
                            )
                            # Don't mark as successful for error responses - success remains False
                        else:
                            try:
                                result = response.json()
                            except (json.JSONDecodeError, orjson.JSONDecodeError, UnicodeDecodeError, AttributeError) as e:
                                result = _handle_json_parse_error(response, e, is_error_response=False)
                            logger.debug(f"REST API tool response: {result}")
                            filtered_response = extract_using_jq(result, tool_jsonpath_filter)
                            # Check if extract_using_jq returned an error (list of TextContent objects)
                            if isinstance(filtered_response, list) and len(filtered_response) > 0 and isinstance(filtered_response[0], TextContent):
                                # Error case - use the TextContent directly
                                tool_result = ToolResult(content=filtered_response, is_error=True)
                                success = False
                            else:
                                tool_result = self._coerce_to_tool_result(filtered_response)
                            # If output schema is present, validate and attach structured content.
                            # The validator skips for isError=true (per #4202) and, on validation
                            # failure, mutates tool_result in place with is_error=True, so the
                            # single post-validation read below covers all cases uniformly.
                            if tool_output_schema:
                                self._extract_and_validate_structured_content(tool_for_validation, tool_result)
                            # ``success`` must reflect both upstream ``isError`` *and* any
                            # validator-imposed error state. Previously this path set
                            # ``success = bool(valid)``, which clobbered an upstream
                            # ``is_error=True`` back to ``success=True`` because the
                            # validator skips (returns True) for error responses.
                            success = not getattr(tool_result, "is_error", False)
                elif tool_integration_type == "MCP":
                    transport = tool_request_type.lower() if tool_request_type else "sse"

                    # Tracks whether we entered the OAuth authorization_code "no DB token" branch.
                    # When True, the auth requirement is deferred to AFTER tool_pre_invoke hooks
                    # run so plugins (e.g. Vault) can inject auth. The deny-path check below the
                    # plugin invocation enforces the requirement locally with an actionable error.
                    oauth_authcode_no_db_token = False

                    # Handle OAuth authentication for the gateway (using local variables)
                    # NOTE: Use has_gateway instead of gateway to avoid accessing detached ORM object
                    if has_gateway and gateway_auth_type == "oauth" and isinstance(gateway_oauth_config, dict) and gateway_oauth_config:
                        grant_type = gateway_oauth_config.get("grant_type", "client_credentials")

                        if grant_type == "authorization_code":
                            # For Authorization Code flow, try to get stored tokens
                            # NOTE: Use fresh_db_session() since the original db was closed
                            try:
                                # First-Party
                                from mcpgateway.services.token_storage_service import TokenStorageService  # pylint: disable=import-outside-toplevel

                                with fresh_db_session() as token_db:
                                    token_storage = TokenStorageService(token_db)

                                    # Get user-specific OAuth token
                                    if not app_user_email:
                                        raise ToolInvocationError(f"User authentication required for OAuth-protected gateway '{gateway_name}'. Please ensure you are authenticated.")

                                    access_token = await token_storage.get_user_token(gateway_id_str, app_user_email)

                                if access_token:
                                    headers = {"Authorization": f"Bearer {access_token}"}
                                else:
                                    # No DB-stored OAuth token. Defer the auth requirement to after
                                    # tool_pre_invoke hooks run so plugins (e.g. Vault) can inject
                                    # auth headers. The post-hook check below enforces the requirement
                                    # locally with an actionable error if no plugin provides auth.
                                    oauth_authcode_no_db_token = True
                                    headers = {}
                                    logger.info(
                                        "OAuth authorization_code gateway '%s' invoked without DB-stored token; deferring auth check to allow plugin injection",
                                        gateway_name,
                                        extra={"gateway_id": gateway_id_str, "user": app_user_email or "<unknown>"},
                                    )
                            except Exception as e:
                                logger.error(f"Failed to obtain stored OAuth token for gateway {gateway_name}: {e}")
                                raise ToolInvocationError(f"OAuth token retrieval failed for gateway: {str(e)}")
                        else:
                            # For Client Credentials flow, get token directly (no DB needed)
                            try:
                                access_token = await self.oauth_manager.get_access_token(
                                    gateway_oauth_config, ca_certificate=gateway_ca_cert, client_cert=gateway_client_cert, client_key=gateway_client_key
                                )
                                headers = {"Authorization": f"Bearer {access_token}"}
                            except Exception as e:
                                logger.error(f"Failed to obtain OAuth access token for gateway {gateway_name}: {e}")
                                raise ToolInvocationError(f"OAuth authentication failed for gateway: {str(e)}")
                    else:
                        headers = decode_auth(gateway_auth_value) if gateway_auth_value else {}

                    # Use cached passthrough headers (no DB query needed)
                    if request_headers:
                        headers = compute_passthrough_headers_cached(
                            request_headers, headers, passthrough_allowed, gateway_auth_type=gateway_auth_type, gateway_passthrough_headers=gateway_passthrough
                        )
                        # Read MCP-Session-Id from downstream client (MCP protocol header)
                        # and normalize to x-mcp-session-id for our internal session affinity logic
                        # The pool will strip this before sending to upstream
                        # Check both mcp-session-id (direct client) and x-mcp-session-id (forwarded requests)
                        request_headers_lower = {k.lower(): v for k, v in request_headers.items()}
                        mcp_session_id = request_headers_lower.get("mcp-session-id") or request_headers_lower.get("x-mcp-session-id")
                        if mcp_session_id:
                            headers["x-mcp-session-id"] = mcp_session_id

                            worker_id = str(os.getpid())
                            session_short = mcp_session_id[:8] if len(mcp_session_id) >= 8 else mcp_session_id
                            logger.debug(f"[AFFINITY] Worker {worker_id} | Session {session_short}... | Tool: {name} | Normalized MCP-Session-Id → x-mcp-session-id for pool affinity (MCP transport)")

                    # Inject identity propagation headers and meta for MCP tools
                    if global_context and global_context.user_context:
                        headers.update(build_identity_headers(global_context.user_context))
                        meta_data = build_identity_meta(global_context.user_context, meta_data)

                    # mTLS client cert/key: resolve from payload, then override with runtime gateway if available
                    client_cert_from_payload = gateway_payload.get("client_cert") if has_gateway else None
                    client_key_from_payload = gateway_payload.get("client_key") if has_gateway else None

                    # Resolve client cert/key: payload values take precedence, runtime values override if present
                    gateway_client_cert = client_cert_from_payload
                    gateway_client_key = client_key_from_payload
                    if has_gateway and gateway is not None:
                        runtime_gateway_client_cert = getattr(gateway, "client_cert", None)
                        runtime_gateway_client_key = getattr(gateway, "client_key", None)
                        if runtime_gateway_client_cert:
                            gateway_client_cert = runtime_gateway_client_cert
                        if runtime_gateway_client_key:
                            gateway_client_key = runtime_gateway_client_key

                    # Decrypt client_key if stored encrypted
                    if gateway_client_key:
                        try:
                            # First-Party
                            from mcpgateway.services.encryption_service import get_encryption_service  # pylint: disable=import-outside-toplevel

                            _enc = get_encryption_service(settings.auth_encryption_secret)
                            gateway_client_key = _enc.decrypt_secret_or_plaintext(gateway_client_key)
                        except Exception as _dec_exc:
                            logger.debug("client_key decryption skipped, using as-is: %s", _dec_exc)

                    def create_ssl_context(
                        ca_certificate: str,
                        client_cert: str | None = None,
                        client_key: str | None = None,
                    ) -> ssl.SSLContext:
                        """Create an SSL context with the provided CA certificate and optional mTLS credentials.

                        Uses caching to avoid repeated SSL context creation for the same certificate(s).

                        Args:
                            ca_certificate: CA certificate in PEM format
                            client_cert: Optional client cert path or PEM for mTLS
                            client_key: Optional client key path or PEM for mTLS

                        Returns:
                            ssl.SSLContext: Configured SSL context
                        """
                        return get_cached_ssl_context(ca_certificate, client_cert=client_cert, client_key=client_key)

                    # Capture mTLS client cert/key values for passing to nested function
                    _client_cert_value = gateway_client_cert
                    _client_key_value = gateway_client_key

                    def get_httpx_client_factory(
                        headers: dict[str, str] | None = None,
                        timeout: httpx.Timeout | None = None,
                        auth: httpx.Auth | None = None,
                    ) -> httpx.AsyncClient:
                        """Factory function to create httpx.AsyncClient with optional CA certificate.

                        Args:
                            headers: Optional headers for the client
                            timeout: Optional timeout for the client
                            auth: Optional auth for the client

                        Returns:
                            httpx.AsyncClient: Configured HTTPX async client

                        Raises:
                            Exception: If CA certificate signature is invalid
                        """
                        # Use captured client cert/key values from closure
                        client_cert_value = _client_cert_value
                        client_key_value = _client_key_value
                        # Use local variables instead of ORM objects (captured from outer scope)
                        valid = False
                        if gateway_ca_cert:
                            if settings.enable_ed25519_signing:
                                public_key_pem = settings.ed25519_public_key
                                valid = validate_signature(gateway_ca_cert.encode(), gateway_ca_cert_sig, public_key_pem)
                            else:
                                valid = True
                        # First-Party
                        from mcpgateway.services.http_client_service import get_default_verify, get_http_timeout  # pylint: disable=import-outside-toplevel

                        # For plain HTTP gateway URLs, skip SSL context entirely to avoid unnecessary SSL setup.
                        if gateway_url and gateway_url.lower().startswith("http://"):
                            ctx = None
                        elif valid and gateway_ca_cert:
                            ctx = create_ssl_context(
                                gateway_ca_cert,
                                client_cert=client_cert_value,
                                client_key=client_key_value,
                            )
                        else:
                            ctx = None

                        # Use effective_timeout for read operations if not explicitly overridden by caller
                        # This ensures the underlying client waits at least as long as the tool configuration requires
                        factory_timeout = timeout if timeout else get_http_timeout(read_timeout=effective_timeout)

                        return httpx.AsyncClient(
                            verify=ctx if ctx else get_default_verify(),
                            follow_redirects=True,
                            headers=headers,
                            timeout=factory_timeout,
                            auth=auth,
                            limits=httpx.Limits(
                                max_connections=settings.httpx_max_connections,
                                max_keepalive_connections=settings.httpx_max_keepalive_connections,
                                keepalive_expiry=settings.httpx_keepalive_expiry,
                            ),
                        )

                    async def connect_to_sse_server(server_url: str, headers: dict = headers):
                        """Connect to an MCP server running with SSE transport.

                        Args:
                            server_url: MCP Server SSE URL
                            headers: HTTP headers to include in the request

                        Returns:
                            ToolResult: Result of tool call

                        Raises:
                            ToolInvocationError: If the tool invocation fails during execution.
                            ToolTimeoutError: If the tool invocation times out.
                            BaseException: On connection or communication errors

                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()
                        tracing_active = otel_context_active()

                        # NOTE: X-Correlation-ID is NOT added to headers for pooled sessions.
                        # MCP SDK pins headers at transport creation, so adding per-request headers
                        # would cause the first request's correlation ID to be reused for all
                        # subsequent requests on the same pooled session. Correlation IDs are
                        # still logged locally for tracing within the gateway.

                        # Log MCP call start (using local variables)
                        # Sanitize server_url to redact sensitive query params from logs
                        server_url_sanitized = sanitize_url_for_logging(server_url, gateway_auth_query_params_decrypted)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url_sanitized, "transport": "sse"},
                        )

                        try:
                            # #4205: Reuse upstream MCP sessions 1:1 per downstream session.
                            # Prefer the registry when we have a downstream Mcp-Session-Id and
                            # we're not inside a distributed trace (reused transports carry
                            # pinned headers, so per-request traceparent can't propagate).
                            tool_call_result = None
                            downstream_session_id = _downstream_session_id_from_request()
                            use_registry = bool(downstream_session_id) and not tracing_active and bool(gateway_id_str)

                            if use_registry:
                                # Registry path: 1:1 binding means upstream state is private to
                                # this downstream session. Connection reuse still amortizes the
                                # initialize cost across multiple tool calls in the same session.
                                try:
                                    registry = get_upstream_session_registry()
                                except RegistryNotInitializedError:
                                    # Registry not initialized (tests, early startup) — fall through.
                                    use_registry = False

                            if use_registry:
                                async with registry.acquire(
                                    downstream_session_id=downstream_session_id,
                                    gateway_id=gateway_id_str,
                                    url=server_url,
                                    headers=headers,
                                    transport_type=TransportType.SSE,
                                    httpx_client_factory=get_httpx_client_factory,
                                ) as upstream:
                                    with anyio.fail_after(effective_timeout):
                                        tool_call_result = await upstream.session.call_tool(tool_name_original, arguments, meta=meta_data)
                            else:
                                # Fallback: per-call session. Taken when no downstream session id
                                # is available (admin UI test-invoke, internal /rpc callers), or
                                # when a distributed trace needs per-request trace headers.
                                with create_span(
                                    "mcp.client.call",
                                    {
                                        "mcp.tool.name": tool_name_original,
                                        "contextforge.tool.id": tool_id,
                                        "contextforge.gateway_id": tool_gateway_id,
                                        "contextforge.runtime": "python",
                                        "contextforge.transport": "sse",
                                        "network.protocol.name": "mcp",
                                        "server.address": urlparse(server_url).hostname,
                                        "server.port": urlparse(server_url).port,
                                        "url.path": urlparse(server_url).path or "/",
                                        "url.full": server_url_sanitized,
                                    },
                                ):
                                    # Non-pooled path: safe to add per-request headers.
                                    # Inject within the active client span so an upstream service
                                    # can attach beneath this span when it extracts traceparent.
                                    request_headers = inject_trace_context_headers(headers)
                                    if correlation_id and request_headers:
                                        request_headers["X-Correlation-ID"] = correlation_id
                                    async with sse_client(url=server_url, headers=request_headers, httpx_client_factory=get_httpx_client_factory) as streams:
                                        async with ClientSession(*streams) as session:
                                            with create_span("mcp.client.initialize", {"contextforge.transport": "sse", "contextforge.runtime": "python"}):
                                                await session.initialize()
                                            with create_span(
                                                "mcp.client.request",
                                                {
                                                    "mcp.tool.name": tool_name_original,
                                                    "contextforge.tool.id": tool_id,
                                                    "contextforge.gateway_id": tool_gateway_id,
                                                    "contextforge.runtime": "python",
                                                },
                                            ):
                                                with anyio.fail_after(effective_timeout):
                                                    tool_call_result = await session.call_tool(tool_name_original, arguments, meta=meta_data)
                                            with create_span(
                                                "mcp.client.response",
                                                {
                                                    "mcp.tool.name": tool_name_original,
                                                    "contextforge.tool.id": tool_id,
                                                    "contextforge.gateway_id": tool_gateway_id,
                                                    "contextforge.runtime": "python",
                                                    "upstream.response.success": not getattr(tool_call_result, "is_error", False) and not getattr(tool_call_result, "isError", False),
                                                },
                                            ):
                                                pass

                            # Log successful MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="INFO",
                                message=f"MCP tool call completed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "mcp_call_completed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse", "success": True},
                            )

                            return tool_call_result
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            # Handle timeout specifically - log and raise ToolInvocationError
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"MCP SSE tool invocation timed out: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "tool_timeout", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse", "timeout_seconds": effective_timeout},
                            )

                            # Manually trigger circuit breaker (or other plugins) on timeout
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug(
                                    "Failed to increment tool_timeout_counter for %s: %s",
                                    name,
                                    exc,
                                    exc_info=True,
                                )

                            if plugin_manager:
                                await self._run_timeout_post_invoke(name, effective_timeout, global_context, context_table, plugin_manager)

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        except BaseException as e:
                            # Extract root cause from ExceptionGroup (Python 3.11+)
                            # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                            root_cause = e
                            if isinstance(e, BaseExceptionGroup):
                                while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                                    root_cause = root_cause.exceptions[0]
                            # Log failed MCP call (using local variables)
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            # Sanitize error message to prevent URL secrets from leaking in logs
                            sanitized_error = sanitize_exception_message(str(root_cause), gateway_auth_query_params_decrypted)
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(root_cause).__name__, "error_message": sanitized_error},
                                metadata={"event": "mcp_call_failed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "sse"},
                            )
                            raise

                    async def connect_to_streamablehttp_server(server_url: str, headers: dict = headers):
                        """Connect to an MCP server running with Streamable HTTP transport.

                        Args:
                            server_url: MCP Server URL
                            headers: HTTP headers to include in the request

                        Returns:
                            ToolResult: Result of tool call

                        Raises:
                            ToolInvocationError: If the tool invocation fails during execution.
                            ToolTimeoutError: If the tool invocation times out.
                            BaseException: On connection or communication errors
                        """
                        # Get correlation ID for distributed tracing
                        correlation_id = get_correlation_id()
                        tracing_active = otel_context_active()

                        # NOTE: X-Correlation-ID is NOT added to headers for pooled sessions.
                        # MCP SDK pins headers at transport creation, so adding per-request headers
                        # would cause the first request's correlation ID to be reused for all
                        # subsequent requests on the same pooled session. Correlation IDs are
                        # still logged locally for tracing within the gateway.

                        # Log MCP call start (using local variables)
                        # Sanitize server_url to redact sensitive query params from logs
                        server_url_sanitized = sanitize_url_for_logging(server_url, gateway_auth_query_params_decrypted)
                        mcp_start_time = time.time()
                        structured_logger.log(
                            level="INFO",
                            message=f"MCP tool call started: {tool_name_original}",
                            component="tool_service",
                            correlation_id=correlation_id,
                            metadata={"event": "mcp_call_started", "tool_name": tool_name_original, "tool_id": tool_id, "server_url": server_url_sanitized, "transport": "streamablehttp"},
                        )

                        try:
                            # #4205: Reuse upstream MCP sessions 1:1 per downstream session.
                            # See the SSE branch above for the full rationale.
                            tool_call_result = None
                            downstream_session_id = _downstream_session_id_from_request()
                            use_registry = bool(downstream_session_id) and not tracing_active and bool(gateway_id_str)

                            if use_registry:
                                try:
                                    registry = get_upstream_session_registry()
                                except RegistryNotInitializedError:
                                    use_registry = False

                            if use_registry:
                                registry_transport_type = TransportType.SSE if transport == "sse" else TransportType.STREAMABLE_HTTP
                                async with registry.acquire(
                                    downstream_session_id=downstream_session_id,
                                    gateway_id=gateway_id_str,
                                    url=server_url,
                                    headers=headers,
                                    transport_type=registry_transport_type,
                                    httpx_client_factory=get_httpx_client_factory,
                                ) as upstream:
                                    with anyio.fail_after(effective_timeout):
                                        tool_call_result = await upstream.session.call_tool(tool_name_original, arguments, meta=meta_data)
                            else:
                                # Fallback: per-call session. Taken when no downstream session id
                                # is available (admin UI test-invoke, internal /rpc callers), when
                                # a distributed trace needs per-request trace headers, or when the
                                # registry singleton isn't initialised (tests, early startup).
                                with create_span(
                                    "mcp.client.call",
                                    {
                                        "mcp.tool.name": tool_name_original,
                                        "contextforge.tool.id": tool_id,
                                        "contextforge.gateway_id": tool_gateway_id,
                                        "contextforge.runtime": "python",
                                        "contextforge.transport": "streamablehttp",
                                        "network.protocol.name": "mcp",
                                        "server.address": urlparse(server_url).hostname,
                                        "server.port": urlparse(server_url).port,
                                        "url.path": urlparse(server_url).path or "/",
                                        "url.full": server_url_sanitized,
                                    },
                                ):
                                    # Non-pooled path: safe to add per-request headers.
                                    # Inject within the active client span so an upstream service
                                    # can attach beneath this span when it extracts traceparent.
                                    request_headers = inject_trace_context_headers(headers)
                                    if correlation_id and request_headers:
                                        request_headers["X-Correlation-ID"] = correlation_id
                                    async with streamablehttp_client(url=server_url, headers=request_headers, httpx_client_factory=get_httpx_client_factory) as (
                                        read_stream,
                                        write_stream,
                                        _get_session_id,
                                    ):
                                        async with ClientSession(read_stream, write_stream) as session:
                                            with create_span("mcp.client.initialize", {"contextforge.transport": "streamablehttp", "contextforge.runtime": "python"}):
                                                await session.initialize()
                                            with create_span(
                                                "mcp.client.request",
                                                {
                                                    "mcp.tool.name": tool_name_original,
                                                    "contextforge.tool.id": tool_id,
                                                    "contextforge.gateway_id": tool_gateway_id,
                                                    "contextforge.runtime": "python",
                                                },
                                            ):
                                                with anyio.fail_after(effective_timeout):
                                                    tool_call_result = await session.call_tool(tool_name_original, arguments, meta=meta_data)
                                            with create_span(
                                                "mcp.client.response",
                                                {
                                                    "mcp.tool.name": tool_name_original,
                                                    "contextforge.tool.id": tool_id,
                                                    "contextforge.gateway_id": tool_gateway_id,
                                                    "contextforge.runtime": "python",
                                                    "upstream.response.success": not getattr(tool_call_result, "is_error", False) and not getattr(tool_call_result, "isError", False),
                                                },
                                            ):
                                                pass

                            # Log successful MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="INFO",
                                message=f"MCP tool call completed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "mcp_call_completed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp", "success": True},
                            )

                            return tool_call_result
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            # Handle timeout specifically - log and raise ToolInvocationError
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"MCP StreamableHTTP tool invocation timed out: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                metadata={"event": "tool_timeout", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp", "timeout_seconds": effective_timeout},
                            )

                            # Manually trigger circuit breaker (or other plugins) on timeout
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug(
                                    "Failed to increment tool_timeout_counter for %s: %s",
                                    name,
                                    exc,
                                    exc_info=True,
                                )

                            if plugin_manager:
                                await self._run_timeout_post_invoke(name, effective_timeout, global_context, context_table, plugin_manager)

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        except BaseException as e:
                            # Extract root cause from ExceptionGroup (Python 3.11+)
                            # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                            root_cause = e
                            if isinstance(e, BaseExceptionGroup):
                                while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                                    root_cause = root_cause.exceptions[0]
                            # Log failed MCP call
                            mcp_duration_ms = (time.time() - mcp_start_time) * 1000
                            # Sanitize error message to prevent URL secrets from leaking in logs
                            sanitized_error = sanitize_exception_message(str(root_cause), gateway_auth_query_params_decrypted)
                            structured_logger.log(
                                level="ERROR",
                                message=f"MCP tool call failed: {tool_name_original}",
                                component="tool_service",
                                correlation_id=correlation_id,
                                duration_ms=mcp_duration_ms,
                                error_details={"error_type": type(root_cause).__name__, "error_message": sanitized_error},
                                metadata={"event": "mcp_call_failed", "tool_name": tool_name_original, "tool_id": tool_id, "transport": "streamablehttp"},
                            )
                            raise

                    # REMOVED: Redundant gateway query - gateway already eager-loaded via joinedload
                    # tool_gateway = db.execute(select(DbGateway).where(DbGateway.id == tool_gateway_id)...)

                    plugin_manager = await self._get_plugin_manager(plugin_context_id)
                    if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE) and not skip_pre_invoke:
                        # Use pre-created Pydantic models from Phase 2 (no ORM access)
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        if gateway_metadata:
                            global_context.metadata[GATEWAY_METADATA] = gateway_metadata
                        pre_result, context_table = await plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
                            global_context=global_context,
                            local_contexts=None,
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    # Defense in depth: strip X-Vault-Tokens (case-insensitive) from outbound
                    # headers. The Vault plugin removes this header when it processes the token,
                    # but stripping unconditionally prevents leakage when the plugin is disabled,
                    # errors in permissive mode, or the header is mistakenly in passthrough_allowed.
                    headers = {hk: hv for hk, hv in headers.items() if hk.lower() != "x-vault-tokens"}

                    # OAuth authorization_code deny-path: if we entered the no-DB-token branch
                    # above and no plugin (or other auth source) injected an Authorization header,
                    # fail locally with an actionable error rather than relying on upstream 401.
                    # This restores the original UX directing the user to /oauth/authorize/{id}
                    # while still allowing legitimate plugin-injected auth (e.g. Vault) to satisfy
                    # the requirement.
                    if oauth_authcode_no_db_token and not any(hk.lower() == "authorization" for hk in headers):
                        raise ToolInvocationError(f"Please authorize {gateway_name} first. Visit /oauth/authorize/{gateway_id_str} to complete OAuth flow.")

                    with create_child_span("tool.gateway_call", {"tool.name": name, "tool.id": tool_id, "tool.integration_type": "MCP"}):
                        tool_call_result = ToolResult(content=[TextContent(text="", type="text")])
                        if transport == "sse":
                            tool_call_result = await connect_to_sse_server(gateway_url, headers=headers)
                        elif transport == "streamablehttp":
                            tool_call_result = await connect_to_streamablehttp_server(gateway_url, headers=headers)

                        # In direct proxy mode, preserve the upstream response verbatim
                        # (no jsonpath filtering, no structured/unstructured split) but
                        # still route through the canonical coercion so the egress sees
                        # a ``ToolResult`` with snake-case ``is_error`` rather than a
                        # raw MCP SDK ``CallToolResult`` with camelCase ``isError``
                        # (#4202 egress regression on the direct-proxy path).
                        if is_direct_proxy:
                            tool_result = self._coerce_to_tool_result(tool_call_result)
                            success = not tool_result.is_error
                            logger.debug(f"Direct proxy mode: using tool result as-is: {tool_result}")
                        else:
                            dump = tool_call_result.model_dump(by_alias=True, mode="json")
                            logger.debug(f"Tool call result dump: {dump}")
                            content = dump.get("content", [])
                            # Accept both alias and pythonic names for structured content
                            structured = dump.get("structuredContent") or dump.get("structured_content")
                            filtered_response = extract_using_jq(content, tool_jsonpath_filter)

                            is_err = getattr(tool_call_result, "is_error", None)
                            if is_err is None:
                                is_err = getattr(tool_call_result, "isError", False)
                            tool_result = ToolResult(content=filtered_response, structured_content=structured, is_error=is_err, meta=getattr(tool_call_result, "meta", None))
                            success = not is_err
                            logger.debug(f"Final tool_result: {tool_result}")

                elif tool_integration_type == "A2A" and a2a_agent_endpoint_url:
                    # A2A tool invocation using pre-extracted agent data (extracted in Phase 2 before db.close())
                    headers = {"Content-Type": "application/json"}

                    # Plugin hook: tool pre-invoke for A2A
                    plugin_manager = await self._get_plugin_manager(plugin_context_id)
                    if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_PRE_INVOKE) and not skip_pre_invoke:
                        if tool_metadata:
                            global_context.metadata[TOOL_METADATA] = tool_metadata
                        pre_result, context_table = await plugin_manager.invoke_hook(
                            ToolHookType.TOOL_PRE_INVOKE,
                            payload=ToolPreInvokePayload(name=name, args=arguments, headers=HttpHeaderPayload(root=headers)),
                            global_context=global_context,
                            local_contexts=context_table,
                            violations_as_exceptions=True,
                        )
                        if pre_result.modified_payload:
                            payload = pre_result.modified_payload
                            name = payload.name
                            arguments = payload.args
                            if payload.headers is not None:
                                headers = payload.headers.model_dump()

                    prepared = prepare_a2a_invocation(
                        agent_type=a2a_agent_type,
                        endpoint_url=a2a_agent_endpoint_url,
                        protocol_version=a2a_agent_protocol_version,
                        parameters=arguments if isinstance(arguments, dict) else {},
                        interaction_type=str(arguments.get("interaction_type", "query")) if isinstance(arguments, dict) else "query",
                        auth_type=a2a_agent_auth_type,
                        auth_value=a2a_agent_auth_value,
                        auth_query_params=a2a_agent_auth_query_params,
                        base_headers=headers,
                        correlation_id=get_correlation_id(),
                    )

                    with create_child_span("tool.gateway_call", {"tool.name": name, "tool.id": tool_id, "tool.integration_type": "A2A"}):
                        # Make HTTP request with timeout enforcement
                        logger.info(f"Calling A2A agent '{a2a_agent_name}' at {prepared.sanitized_endpoint_url}")
                        a2a_start_time = time.time()
                        try:
                            # First-Party
                            from mcpgateway.version import should_delegate_a2a_to_rust  # pylint: disable=import-outside-toplevel

                            if should_delegate_a2a_to_rust():
                                runtime_response = await get_rust_a2a_runtime_client().invoke(prepared, timeout_seconds=int(max(1, effective_timeout)))
                                status_code = int(runtime_response.get("status_code", 200))
                                response_data = runtime_response.get("json")
                                response_text = str(runtime_response.get("text") or "")
                            else:
                                http_response = await asyncio.wait_for(
                                    self._http_client.post(prepared.endpoint_url, json=prepared.request_data, headers=prepared.headers),
                                    timeout=effective_timeout,
                                )
                                status_code = http_response.status_code
                                response_data = http_response.json() if status_code == 200 else None
                                response_text = http_response.text
                        except (asyncio.TimeoutError, httpx.TimeoutException):
                            a2a_elapsed_ms = (time.time() - a2a_start_time) * 1000
                            structured_logger.log(
                                level="WARNING",
                                message=f"A2A tool invocation timed out: {name}",
                                component="tool_service",
                                correlation_id=get_correlation_id(),
                                duration_ms=a2a_elapsed_ms,
                                metadata={"event": "tool_timeout", "tool_name": name, "a2a_agent": a2a_agent_name, "timeout_seconds": effective_timeout},
                            )

                            # Increment timeout counter
                            try:
                                # First-Party
                                from mcpgateway.services.metrics import tool_timeout_counter  # pylint: disable=import-outside-toplevel

                                tool_timeout_counter.labels(tool_name=name).inc()
                            except Exception as exc:
                                logger.debug("Failed to increment tool_timeout_counter for %s: %s", name, exc, exc_info=True)

                            # Trigger circuit breaker on timeout
                            if plugin_manager:
                                await self._run_timeout_post_invoke(name, effective_timeout, global_context, context_table, plugin_manager)

                            raise ToolTimeoutError(f"Tool invocation timed out after {effective_timeout}s")
                        except RustA2ARuntimeError as e:
                            status_code = 502
                            response_data = None
                            response_text = str(e)

                        if status_code == 200:
                            if isinstance(response_data, dict) and "response" in response_data:
                                val = response_data["response"]
                                content = [TextContent(type="text", text=val if isinstance(val, str) else orjson.dumps(val).decode())]
                            elif response_data is not None:
                                content = [TextContent(type="text", text=response_data if isinstance(response_data, str) else orjson.dumps(response_data).decode())]
                            else:
                                content = [TextContent(type="text", text=response_text)]
                            tool_result = ToolResult(content=content, is_error=False)
                            success = True
                        else:
                            error_message = f"HTTP {status_code}: {response_text}"
                            content = [TextContent(type="text", text=f"A2A agent error: {error_message}")]
                            tool_result = ToolResult(content=content, is_error=True)
                else:
                    tool_result = ToolResult(content=[TextContent(type="text", text="Invalid tool type")], is_error=True)

                with create_child_span("tool.post_process", {"tool.name": name, "tool.id": tool_id}):
                    post_result = None
                    # Plugin hook: tool post-invoke
                    plugin_manager = await self._get_plugin_manager(plugin_context_id)
                    if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                        post_result, _ = await plugin_manager.invoke_hook(
                            ToolHookType.TOOL_POST_INVOKE,
                            payload=ToolPostInvokePayload(name=name, result=tool_result.model_dump(by_alias=True)),
                            global_context=global_context,
                            local_contexts=context_table,
                            violations_as_exceptions=True,
                        )
                        # Use modified payload if provided
                        if post_result.modified_payload:
                            # Reconstruct ToolResult from modified result
                            modified_result = post_result.modified_payload.result
                            if isinstance(modified_result, dict) and "content" in modified_result:
                                # Safely obtain structured content using .get() to avoid KeyError when
                                # plugins provide only the content without structured content fields.
                                structured = modified_result.get("structuredContent") if "structuredContent" in modified_result else modified_result.get("structured_content")

                                tool_result = ToolResult(content=modified_result["content"], structured_content=structured)
                            else:
                                # If result is not in expected format, convert it to text content
                                try:
                                    tool_result = ToolResult(content=[TextContent(type="text", text=modified_result if isinstance(modified_result, str) else orjson.dumps(modified_result).decode())])
                                except Exception:
                                    tool_result = ToolResult(content=[TextContent(type="text", text=str(modified_result))])

                    # Retry: if the plugin requested a delayed retry and we haven't hit the gateway ceiling.
                    # retry_attempt is 0-based (0 = original call).  The condition allows retry_attempt
                    # values 0..max_tool_retries-1, meaning up to max_tool_retries *retry* attempts on
                    # top of the original call (total attempts = max_tool_retries + 1).
                    if post_result is not None and post_result.retry_delay_ms > 0 and retry_attempt < settings.max_tool_retries:
                        return await self._retry_tool_invocation(
                            post_result.retry_delay_ms,
                            retry_attempt,
                            name,
                            arguments,
                            request_headers,
                            app_user_email,
                            user_email,
                            token_teams,
                            server_id,
                            context_table,
                            global_context,
                            meta_data,
                            skip_pre_invoke,
                            "success",
                        )

                return tool_result
            except (PluginError, PluginViolationError):
                raise
            except ToolTimeoutError as e:
                # ToolTimeoutError is raised by timeout handlers which already called tool_post_invoke.
                # Do NOT call post_invoke again — the retry_delay_ms signal is carried on the exception.
                error_message = str(e)
                if span:
                    set_span_error(span, error_message)

                # Retry if the post-invoke hook (called by the timeout handler) requested it.
                if e.retry_delay_ms > 0 and retry_attempt < settings.max_tool_retries:
                    return await self._retry_tool_invocation(
                        e.retry_delay_ms,
                        retry_attempt,
                        name,
                        arguments,
                        request_headers,
                        app_user_email,
                        user_email,
                        token_teams,
                        server_id,
                        context_table,
                        global_context,
                        meta_data,
                        skip_pre_invoke,
                        "timeout",
                    )
                raise
            except BaseException as e:
                # Extract root cause from ExceptionGroup (Python 3.11+)
                # MCP SDK uses TaskGroup which wraps exceptions in ExceptionGroup
                root_cause = e
                if isinstance(e, BaseExceptionGroup):
                    while isinstance(root_cause, BaseExceptionGroup) and root_cause.exceptions:
                        root_cause = root_cause.exceptions[0]
                error_message = str(root_cause)
                # Set span error status
                if span:
                    set_span_error(span, error_message)

                # Notify plugins of the failure so circuit breaker / retry plugin can track it.
                # Capture the result so we can honour a retry_delay_ms signal from the retry plugin.
                # When the exception carries an HTTP status code (e.g. httpx.HTTPStatusError),
                # include it in structuredContent so the retry plugin can honour retry_on_status
                # instead of blindly retrying every exception.
                exc_post_result = None
                plugin_manager = await self._get_plugin_manager(plugin_context_id)
                if plugin_manager and plugin_manager.has_hooks_for(ToolHookType.TOOL_POST_INVOKE):
                    try:
                        exc_structured: Optional[Dict[str, Any]] = None
                        if isinstance(root_cause, httpx.HTTPStatusError):
                            exc_structured = {"status_code": root_cause.response.status_code}
                        exception_error_result = ToolResult(content=[TextContent(type="text", text=f"Tool invocation failed: {error_message}")], is_error=True, structured_content=exc_structured)
                        exc_post_result, _ = await plugin_manager.invoke_hook(
                            ToolHookType.TOOL_POST_INVOKE,
                            payload=ToolPostInvokePayload(name=name, result=exception_error_result.model_dump(by_alias=True)),
                            global_context=global_context,
                            local_contexts=context_table,
                            violations_as_exceptions=False,  # Don't let plugin errors mask the original exception
                        )
                    except Exception as plugin_exc:
                        logger.debug("Failed to invoke post-invoke plugins on exception: %s", plugin_exc)

                # Retry if the plugin requested a delayed retry and we haven't hit the ceiling.
                # Same counting convention as the success path: retry_attempt is 0-based,
                # so this allows up to max_tool_retries retry attempts beyond the original call.
                if exc_post_result is not None and exc_post_result.retry_delay_ms > 0 and retry_attempt < settings.max_tool_retries:
                    return await self._retry_tool_invocation(
                        exc_post_result.retry_delay_ms,
                        retry_attempt,
                        name,
                        arguments,
                        request_headers,
                        app_user_email,
                        user_email,
                        token_teams,
                        server_id,
                        context_table,
                        global_context,
                        meta_data,
                        skip_pre_invoke,
                        "exception",
                    )

                raise ToolInvocationError(f"Tool invocation failed: {error_message}")
            finally:
                # Calculate duration
                duration_ms = (time.monotonic() - start_time) * 1000

                # End database span for observability_spans table
                # end_span creates its own independent session (issue #3883)
                if db_span_id and observability_service and not db_span_ended:
                    try:
                        observability_service.end_span(
                            span_id=db_span_id,
                            status="ok" if success else "error",
                            status_message=error_message if error_message else None,
                            attributes={
                                "success": success,
                                "duration_ms": duration_ms,
                            },
                        )
                        db_span_ended = True
                        logger.debug(f"✓ Ended tool.invoke span: {db_span_id}")
                    except Exception as e:
                        logger.warning(f"Failed to end observability span for tool invocation: {e}")

                # Add final span attributes for OpenTelemetry
                if span:
                    set_span_attribute(span, "success", success)
                    set_span_attribute(span, "duration.ms", duration_ms)
                    if success and tool_result and is_output_capture_enabled("tool.invoke"):
                        set_span_attribute(span, "langfuse.observation.output", serialize_trace_payload(tool_result))

                # ═══════════════════════════════════════════════════════════════════════════
                # PHASE 4: Record metrics via buffered service (batches writes for performance)
                # ═══════════════════════════════════════════════════════════════════════════
                # Only record metrics if tool_id is valid (skip for direct_proxy mode)
                if tool_id:
                    try:
                        metrics_buffer.record_tool_metric(
                            tool_id=tool_id,
                            start_time=start_time,
                            success=success,
                            error_message=error_message,
                        )
                    except Exception as metric_error:
                        logger.warning(f"Failed to record tool metric: {metric_error}")

                # Record server metrics ONLY when invoked through a specific virtual server
                # When server_id is provided, it means the tool was called via a virtual server endpoint
                # Direct tool calls via /rpc should NOT populate server metrics
                if tool_id and server_id:
                    try:
                        # Record server metric only for the specific virtual server being accessed
                        metrics_buffer.record_server_metric(
                            server_id=server_id,
                            start_time=start_time,
                            success=success,
                            error_message=error_message,
                        )
                    except Exception as metric_error:
                        logger.warning(f"Failed to record server metric: {metric_error}")

                # Log structured message with performance tracking (using local variables)
                if success:
                    structured_logger.info(
                        f"Tool '{name}' invoked successfully",
                        user_id=app_user_email,
                        resource_type="tool",
                        resource_id=tool_id,
                        resource_action="invoke",
                        duration_ms=duration_ms,
                        custom_fields={"tool_name": name, "integration_type": tool_integration_type, "arguments_count": len(arguments) if arguments else 0},
                    )
                else:
                    structured_logger.error(
                        f"Tool '{name}' invocation failed",
                        error=Exception(error_message) if error_message else None,
                        user_id=app_user_email,
                        resource_type="tool",
                        resource_id=tool_id,
                        resource_action="invoke",
                        duration_ms=duration_ms,
                        custom_fields={"tool_name": name, "integration_type": tool_integration_type, "error_message": error_message},
                    )

                # Track performance with threshold checking
                with perf_tracker.track_operation("tool_invocation", name):
                    pass  # Duration already captured above

    @staticmethod
    def _form_value_to_str(v: Any) -> str:
        """Coerce a payload value to string for form/multipart encoding."""
        if v is None:
            return ""
        if isinstance(v, (dict, list, bool)):
            return orjson.dumps(v).decode()
        return str(v)

    @staticmethod
    def _check_tool_name_conflict(db: Session, custom_name: str, visibility: str, tool_id: str, team_id: Optional[str] = None, owner_email: Optional[str] = None) -> None:
        """Raise ToolNameConflictError if another tool with the same name exists in the target visibility scope.

        Args:
            db: The SQLAlchemy database session.
            custom_name: The custom name to check for conflicts.
            visibility: The target visibility scope (``public``, ``team``, or ``private``).
            tool_id: The ID of the tool being updated (excluded from the conflict search).
            team_id: Required when *visibility* is ``team``; scopes the uniqueness check to this team.
            owner_email: Required when *visibility* is ``private``; scopes the uniqueness check to this owner.

        Raises:
            ToolNameConflictError: If a conflicting tool already exists in the target scope.
        """
        if visibility == "public":
            existing_tool = get_for_update(
                db,
                DbTool,
                where=and_(
                    DbTool.custom_name == custom_name,
                    DbTool.visibility == "public",
                    DbTool.id != tool_id,
                ),
            )
        elif visibility == "team" and team_id:
            existing_tool = get_for_update(
                db,
                DbTool,
                where=and_(
                    DbTool.custom_name == custom_name,
                    DbTool.visibility == "team",
                    DbTool.team_id == team_id,
                    DbTool.id != tool_id,
                ),
            )
        elif visibility == "private" and owner_email:
            existing_tool = get_for_update(
                db,
                DbTool,
                where=and_(
                    DbTool.custom_name == custom_name,
                    DbTool.visibility == "private",
                    DbTool.owner_email == owner_email,
                    DbTool.id != tool_id,
                ),
            )
        else:
            logger.warning("Skipping conflict check for tool %s: visibility=%r requires %s but none provided", tool_id, visibility, "team_id" if visibility == "team" else "owner_email")
            return
        if existing_tool:
            raise ToolNameConflictError(existing_tool.custom_name, enabled=existing_tool.enabled, tool_id=existing_tool.id, visibility=existing_tool.visibility)

    async def update_tool(
        self,
        db: Session,
        tool_id: str,
        tool_update: ToolUpdate,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> ToolRead:
        """
        Update an existing tool.

        Args:
            db (Session): The SQLAlchemy database session.
            tool_id (str): The unique identifier of the tool.
            tool_update (ToolUpdate): Tool update schema with new data.
            modified_by (Optional[str]): Username who modified this tool.
            modified_from_ip (Optional[str]): IP address of modifier.
            modified_via (Optional[str]): Modification method (ui, api).
            modified_user_agent (Optional[str]): User agent of modification request.
            user_email (Optional[str]): Email of user performing update (for ownership check).

        Returns:
            The updated ToolRead object.

        Raises:
            ToolNotFoundError: If the tool is not found.
            PermissionError: If user doesn't own the tool.
            IntegrityError: If there is a database integrity error.
            ToolNameConflictError: If a tool with the same name already exists.
            ToolError: For other update errors.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock, AsyncMock
            >>> from mcpgateway.schemas import ToolRead
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> tool = MagicMock()
            >>> db.get.return_value = tool
            >>> db.commit = MagicMock()
            >>> db.refresh = MagicMock()
            >>> db.execute.return_value.scalar_one_or_none.return_value = None
            >>> service._notify_tool_updated = AsyncMock()
            >>> service.convert_tool_to_read = MagicMock(return_value='tool_read')
            >>> ToolRead.model_validate = MagicMock(return_value='tool_read')
            >>> import asyncio
            >>> asyncio.run(service.update_tool(db, 'tool_id', MagicMock()))
            'tool_read'
        """
        try:
            tool = get_for_update(db, DbTool, tool_id)

            if not tool:
                raise ToolNotFoundError(f"Tool not found: {tool_id}")

            old_tool_name = tool.name
            old_gateway_id = tool.gateway_id

            # Check ownership if user_email provided
            if user_email:
                # First-Party
                from mcpgateway.services.permission_service import PermissionService  # pylint: disable=import-outside-toplevel

                permission_service = PermissionService(db)
                if not await permission_service.check_resource_ownership(user_email, tool):
                    raise PermissionError("Only the owner can update this tool")

            # Validate tool content for malicious patterns (CWE-20 fix - Issue #6)
            # Convert to string to handle both string and non-string inputs
            if tool_update.name:
                self._content_security.detect_malicious_patterns(
                    content=str(tool_update.name),
                    content_type="Tool name",
                    user_email=user_email or modified_by,
                    ip_address=modified_from_ip,
                )
            if tool_update.description:
                self._content_security.detect_malicious_patterns(
                    content=str(tool_update.description),
                    content_type="Tool description",
                    user_email=user_email or modified_by,
                    ip_address=modified_from_ip,
                )
            if tool_update.input_schema:
                # Convert inputSchema to string for pattern scanning
                # Handle both dict objects and test mocks gracefully
                try:
                    schema_str = orjson.dumps(tool_update.input_schema).decode()
                    self._content_security.detect_malicious_patterns(
                        content=schema_str,
                        content_type="Tool inputSchema",
                        user_email=user_email or modified_by,
                        ip_address=modified_from_ip,
                    )
                except (TypeError, ValueError):
                    # Skip validation if schema is not JSON-serializable (e.g., test mocks)
                    pass

            # Track whether a name change occurred (before tool.name is mutated)
            name_is_changing = bool(tool_update.name and tool_update.name != tool.name)

            # Check for name change and ensure uniqueness
            if name_is_changing:
                # Always derive ownership fields from the DB record — never trust client-provided team_id/owner_email
                tool_visibility_ref = tool.visibility if tool_update.visibility is None else tool_update.visibility.lower()
                if tool_update.custom_name is not None:
                    custom_name_ref = tool_update.custom_name
                elif tool.name == tool.custom_name:
                    custom_name_ref = tool_update.name  # custom_name will track the rename
                else:
                    custom_name_ref = tool.custom_name  # custom_name stays unchanged
                self._check_tool_name_conflict(db, custom_name_ref, tool_visibility_ref, tool.id, team_id=tool.team_id, owner_email=tool.owner_email)
                if tool_update.custom_name is None and tool.name == tool.custom_name:
                    tool.custom_name = tool_update.name
                tool.name = tool_update.name

            # Check for conflicts when visibility changes without a name change
            if tool_update.visibility is not None and tool_update.visibility.lower() != tool.visibility and not name_is_changing:
                new_visibility = tool_update.visibility.lower()
                self._check_tool_name_conflict(db, tool.custom_name, new_visibility, tool.id, team_id=tool.team_id, owner_email=tool.owner_email)

            if tool_update.custom_name is not None:
                tool.custom_name = tool_update.custom_name
            if tool_update.displayName is not None:
                tool.display_name = tool_update.displayName
            if tool_update.url is not None:
                tool.url = str(tool_update.url)
            if tool_update.description is not None:
                tool.description = tool_update.description
            if tool_update.title is not None:
                tool.title = tool_update.title
            if tool_update.integration_type is not None:
                tool.integration_type = tool_update.integration_type
            if tool_update.request_type is not None:
                tool.request_type = tool_update.request_type
            if tool_update.headers is not None:
                tool.headers = _protect_tool_headers_for_storage(tool_update.headers, existing_headers=tool.headers)
            if tool_update.input_schema is not None:
                tool.input_schema = tool_update.input_schema
            if tool_update.output_schema is not None:
                tool.output_schema = tool_update.output_schema
            if tool_update.annotations is not None:
                tool.annotations = tool_update.annotations
            if tool_update.jsonpath_filter is not None:
                tool.jsonpath_filter = tool_update.jsonpath_filter
            if tool_update.visibility is not None:
                tool.visibility = tool_update.visibility

            if tool_update.auth is not None:
                if tool_update.auth.auth_type is not None:
                    tool.auth_type = tool_update.auth.auth_type
                if tool_update.auth.auth_value is not None:
                    tool.auth_value = tool_update.auth.auth_value

            # Update tags if provided
            if tool_update.tags is not None:
                tool.tags = tool_update.tags

            # Update modification metadata
            if modified_by is not None:
                tool.modified_by = modified_by
            if modified_from_ip is not None:
                tool.modified_from_ip = modified_from_ip
            if modified_via is not None:
                tool.modified_via = modified_via
            if modified_user_agent is not None:
                tool.modified_user_agent = modified_user_agent

            # Increment version
            if hasattr(tool, "version") and tool.version is not None:
                tool.version += 1
            else:
                tool.version = 1
            logger.info(f"Update tool: {tool.name} (output_schema: {tool.output_schema})")

            tool.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(tool)
            await self._notify_tool_updated(tool)
            logger.info(f"Updated tool: {tool.name}")

            # Structured logging: Audit trail for tool update
            changes = []
            if tool_update.name:
                changes.append(f"name: {tool_update.name}")
            if tool_update.visibility:
                changes.append(f"visibility: {tool_update.visibility}")
            if tool_update.description:
                changes.append("description updated")

            audit_trail.log_action(
                user_id=user_email or modified_by or "system",
                action="update_tool",
                resource_type="tool",
                resource_id=tool.id,
                resource_name=tool.name,
                user_email=user_email,
                team_id=tool.team_id,
                client_ip=modified_from_ip,
                user_agent=modified_user_agent,
                new_values={
                    "name": tool.name,
                    "display_name": tool.display_name,
                    "version": tool.version,
                },
                context={
                    "modified_via": modified_via,
                    "changes": ", ".join(changes) if changes else "metadata only",
                },
                db=db,
            )

            # Structured logging: Log successful tool update
            structured_logger.log(
                level="INFO",
                message="Tool updated successfully",
                event_type="tool_updated",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                team_id=tool.team_id,
                resource_type="tool",
                resource_id=tool.id,
                custom_fields={
                    "tool_name": tool.name,
                    "version": tool.version,
                },
            )

            # Invalidate cache after successful update
            cache = _get_registry_cache()
            await cache.invalidate_tools()
            tool_lookup_cache = _get_tool_lookup_cache()
            await tool_lookup_cache.invalidate(old_tool_name, gateway_id=str(old_gateway_id) if old_gateway_id else None)
            await tool_lookup_cache.invalidate(tool.name, gateway_id=str(tool.gateway_id) if tool.gateway_id else None)
            # Also invalidate tags cache since tool tags may have changed
            # First-Party
            from mcpgateway.cache.admin_stats_cache import admin_stats_cache  # pylint: disable=import-outside-toplevel

            await admin_stats_cache.invalidate_tags()

            return self.convert_tool_to_read(tool, requesting_user_email=getattr(tool, "owner_email", None))
        except PermissionError as pe:
            db.rollback()

            # Structured logging: Log permission error
            structured_logger.log(
                level="WARNING",
                message="Tool update failed due to permission error",
                event_type="tool_update_permission_denied",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=pe,
            )
            raise
        except IntegrityError as ie:
            db.rollback()
            logger.error(f"IntegrityError during tool update: {ie}")

            # Structured logging: Log database integrity error
            structured_logger.log(
                level="ERROR",
                message="Tool update failed due to database integrity error",
                event_type="tool_update_failed",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=ie,
            )
            raise ie
        except ToolNotFoundError as tnfe:
            db.rollback()
            logger.error(f"Tool not found during update: {tnfe}")

            # Structured logging: Log not found error
            structured_logger.log(
                level="ERROR",
                message="Tool update failed - tool not found",
                event_type="tool_not_found",
                component="tool_service",
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=tnfe,
            )
            raise tnfe
        except ToolNameConflictError as tnce:
            db.rollback()
            logger.error(f"Tool name conflict during update: {tnce}")

            # Structured logging: Log name conflict error
            structured_logger.log(
                level="WARNING",
                message="Tool update failed due to name conflict",
                event_type="tool_name_conflict",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=tnce,
            )
            raise tnce
        except Exception as ex:
            db.rollback()

            # Structured logging: Log generic tool update failure
            structured_logger.log(
                level="ERROR",
                message="Tool update failed",
                event_type="tool_update_failed",
                component="tool_service",
                user_id=modified_by,
                user_email=user_email,
                resource_type="tool",
                resource_id=tool_id,
                error=ex,
            )
            raise ToolError(f"Failed to update tool: {str(ex)}")

    async def _notify_tool_updated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool update.

        Args:
            tool: Tool updated
        """
        event = {
            "type": "tool_updated",
            "data": {"id": tool.id, "name": tool.name, "url": tool.url, "description": tool.description, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_activated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool activation.

        Args:
            tool: Tool activated
        """
        event = {
            "type": "tool_activated",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled, "reachable": tool.reachable},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_deactivated(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool deactivation.

        Args:
            tool: Tool deactivated
        """
        event = {
            "type": "tool_deactivated",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled, "reachable": tool.reachable},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_offline(self, tool: DbTool) -> None:
        """
        Notify subscribers that tool is offline.

        Args:
            tool: Tool database object
        """
        event = {
            "type": "tool_offline",
            "data": {
                "id": tool.id,
                "name": tool.name,
                "enabled": True,
                "reachable": False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_deleted(self, tool_info: Dict[str, Any]) -> None:
        """
        Notify subscribers of tool deletion.

        Args:
            tool_info: Dictionary on tool deleted
        """
        event = {
            "type": "tool_deleted",
            "data": tool_info,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to tool events via the EventService.

        Yields:
            Tool event messages.
        """
        async for event in self._event_service.subscribe_events():
            yield event

    async def _notify_tool_added(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool addition.

        Args:
            tool: Tool added
        """
        event = {
            "type": "tool_added",
            "data": {
                "id": tool.id,
                "name": tool.name,
                "url": tool.url,
                "description": tool.description,
                "enabled": tool.enabled,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _notify_tool_removed(self, tool: DbTool) -> None:
        """
        Notify subscribers of tool removal (soft delete/deactivation).

        Args:
            tool: Tool removed
        """
        event = {
            "type": "tool_removed",
            "data": {"id": tool.id, "name": tool.name, "enabled": tool.enabled},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._publish_event(event)

    async def _publish_event(self, event: Dict[str, Any]) -> None:
        """
        Publish event to all subscribers via the EventService.

        Args:
            event: Event to publish
        """
        await self._event_service.publish_event(event)

    async def _validate_tool_url(self, url: str) -> None:
        """Validate tool URL is accessible.

        Args:
            url: URL to validate.

        Raises:
            ToolValidationError: If URL validation fails.
        """
        try:
            response = await self._http_client.get(url)
            response.raise_for_status()
        except Exception as e:
            raise ToolValidationError(f"Failed to validate tool URL: {str(e)}")

    async def _check_tool_health(self, tool: DbTool) -> bool:
        """Check if tool endpoint is healthy.

        Args:
            tool: Tool to check.

        Returns:
            True if tool is healthy.
        """
        try:
            response = await self._http_client.get(tool.url)
            return response.is_success
        except Exception:
            return False

    # async def event_generator(self) -> AsyncGenerator[Dict[str, Any], None]:
    #     """Generate tool events for SSE.

    #     Yields:
    #         Tool events.
    #     """
    #     queue: asyncio.Queue = asyncio.Queue()
    #     self._event_subscribers.append(queue)
    #     try:
    #         while True:
    #             event = await queue.get()
    #             yield event
    #     finally:
    #         self._event_subscribers.remove(queue)

    # --- Metrics ---
    async def aggregate_metrics(self, db: Session) -> ToolMetrics:
        """
        Aggregate metrics for all tool invocations across all tools.

        Combines recent raw metrics (within retention period) with historical
        hourly rollups for complete historical coverage. Uses in-memory caching
        (10s TTL) to reduce database load under high request rates.

        Args:
            db: Database session

        Returns:
            ToolMetrics: Aggregated metrics computed from raw ToolMetric + ToolMetricsHourly.

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> service = ToolService()
            >>> # Method exists and is callable
            >>> callable(service.aggregate_metrics)
            True
        """
        # Check cache first (if enabled)
        # First-Party
        from mcpgateway.cache.metrics_cache import is_cache_enabled, metrics_cache  # pylint: disable=import-outside-toplevel

        if is_cache_enabled():
            cached = metrics_cache.get("tools")
            if cached is not None:
                return ToolMetrics(**cached)

        # Use combined raw + rollup query for full historical coverage
        # First-Party
        from mcpgateway.services.metrics_query_service import aggregate_metrics_combined  # pylint: disable=import-outside-toplevel

        result = aggregate_metrics_combined(db, "tool")
        metrics = ToolMetrics(
            total_executions=result.total_executions,
            successful_executions=result.successful_executions,
            failed_executions=result.failed_executions,
            failure_rate=result.failure_rate,
            min_response_time=result.min_response_time,
            max_response_time=result.max_response_time,
            avg_response_time=result.avg_response_time,
            last_execution_time=result.last_execution_time,
        )

        # Cache the result as dict for serialization compatibility (if enabled)
        if is_cache_enabled():
            metrics_cache.set("tools", metrics.model_dump())

        return metrics

    async def reset_metrics(self, db: Session, tool_id: Optional[int] = None) -> None:
        """
        Reset all tool metrics by deleting raw and hourly rollup records.

        Args:
            db: Database session
            tool_id: Optional tool ID to reset metrics for a specific tool

        Examples:
            >>> from mcpgateway.services.tool_service import ToolService
            >>> from unittest.mock import MagicMock
            >>> service = ToolService()
            >>> db = MagicMock()
            >>> db.execute = MagicMock()
            >>> db.commit = MagicMock()
            >>> import asyncio
            >>> asyncio.run(service.reset_metrics(db))
        """

        if tool_id:
            db.execute(delete(ToolMetric).where(ToolMetric.tool_id == tool_id))
            db.execute(delete(ToolMetricsHourly).where(ToolMetricsHourly.tool_id == tool_id))
        else:
            db.execute(delete(ToolMetric))
            db.execute(delete(ToolMetricsHourly))
        db.commit()

        # Invalidate metrics cache
        # First-Party
        from mcpgateway.cache.metrics_cache import metrics_cache  # pylint: disable=import-outside-toplevel

        metrics_cache.invalidate("tools")
        metrics_cache.invalidate_prefix("top_tools:")

    async def create_tool_from_a2a_agent(
        self,
        db: Session,
        agent: DbA2AAgent,
        created_by: Optional[str] = None,
        created_from_ip: Optional[str] = None,
        created_via: Optional[str] = None,
        created_user_agent: Optional[str] = None,
    ) -> DbTool:
        """Create a tool entry from an A2A agent for virtual server integration.

        Args:
            db: Database session.
            agent: A2A agent to create tool from.
            created_by: Username who created this tool.
            created_from_ip: IP address of creator.
            created_via: Creation method.
            created_user_agent: User agent of creation request.

        Returns:
            The created tool database object.

        Raises:
            ToolNameConflictError: If a tool with the same name already exists.
        """
        # Check if tool already exists for this agent
        tool_name = f"a2a_{agent.slug}"
        existing_query = select(DbTool).where(DbTool.original_name == tool_name)
        existing_tool = db.execute(existing_query).scalar_one_or_none()

        if existing_tool:
            # Tool already exists, return it
            return existing_tool

        # Create tool entry for the A2A agent
        logger.debug(f"agent.tags: {agent.tags} for agent: {agent.name} (ID: {agent.id})")

        # Normalize tags: if agent.tags contains dicts like {'id':..,'label':..},
        # extract the human-friendly label. If tags are already strings, keep them.
        normalized_tags: list[str] = []
        for t in agent.tags or []:
            if isinstance(t, dict):
                # Prefer 'label', fall back to 'id' or stringified dict
                normalized_tags.append(t.get("label") or t.get("id") or str(t))
            elif hasattr(t, "label"):
                normalized_tags.append(getattr(t, "label"))
            else:
                normalized_tags.append(str(t))

        # Ensure we include identifying A2A tags
        normalized_tags = normalized_tags + ["a2a", "agent"]

        tool_data = ToolCreate(
            name=tool_name,
            displayName=generate_display_name(agent.name),
            url=agent.endpoint_url,
            description=f"A2A Agent: {agent.description or agent.name}",
            integration_type="A2A",  # Special integration type for A2A agents
            request_type="POST",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "User query", "default": "Hello from ContextForge Admin UI test!"},
                },
                "required": ["query"],
            },
            allow_auto=True,
            annotations={
                "title": f"A2A Agent: {agent.name}",
                "a2a_agent_id": agent.id,
                "a2a_agent_type": agent.agent_type,
            },
            auth_type=agent.auth_type,
            auth_value=agent.auth_value,
            tags=normalized_tags,
        )

        # Default to "public" visibility if agent visibility is not set
        # This ensures A2A tools are visible in the Global Tools Tab
        tool_visibility = agent.visibility or "public"

        tool_read = await self.register_tool(
            db,
            tool_data,
            created_by=created_by,
            created_from_ip=created_from_ip,
            created_via=created_via or "a2a_integration",
            created_user_agent=created_user_agent,
            team_id=agent.team_id,
            owner_email=agent.owner_email,
            visibility=tool_visibility,
        )

        # Return the DbTool object for relationship assignment
        tool_db = db.get(DbTool, tool_read.id)
        return tool_db

    async def update_tool_from_a2a_agent(
        self,
        db: Session,
        agent: DbA2AAgent,
        modified_by: Optional[str] = None,
        modified_from_ip: Optional[str] = None,
        modified_via: Optional[str] = None,
        modified_user_agent: Optional[str] = None,
    ) -> Optional[ToolRead]:
        """Update the tool associated with an A2A agent when the agent is updated.

        Args:
            db: Database session.
            agent: Updated A2A agent.
            modified_by: Username who modified this tool.
            modified_from_ip: IP address of modifier.
            modified_via: Modification method.
            modified_user_agent: User agent of modification request.

        Returns:
            The updated tool, or None if no associated tool exists.
        """
        # Use the tool_id from the agent for efficient lookup
        if not agent.tool_id:
            logger.debug(f"No tool_id found for A2A agent {agent.id}, skipping tool update")
            return None

        tool = db.get(DbTool, agent.tool_id)
        if not tool:
            logger.warning(f"Tool {agent.tool_id} not found for A2A agent {agent.id}, resetting tool_id")
            agent.tool_id = None
            db.commit()
            return None

        # Normalize tags: if agent.tags contains dicts like {'id':..,'label':..},
        # extract the human-friendly label. If tags are already strings, keep them.
        normalized_tags: list[str] = []
        for t in agent.tags or []:
            if isinstance(t, dict):
                # Prefer 'label', fall back to 'id' or stringified dict
                normalized_tags.append(t.get("label") or t.get("id") or str(t))
            elif hasattr(t, "label"):
                normalized_tags.append(getattr(t, "label"))
            else:
                normalized_tags.append(str(t))

        # Ensure we include identifying A2A tags
        normalized_tags = normalized_tags + ["a2a", "agent"]

        # Prepare update data matching the agent's current state
        # IMPORTANT: Preserve the existing tool's visibility to avoid unintentionally
        # making private/team tools public (ToolUpdate defaults to "public")
        # Note: team_id is not a field on ToolUpdate schema, so team assignment is preserved
        # implicitly by not changing visibility (team tools stay team-scoped)
        new_tool_name = f"a2a_{agent.slug}"
        tool_update = ToolUpdate(
            name=new_tool_name,
            custom_name=new_tool_name,  # Also set custom_name to ensure name update works
            displayName=generate_display_name(agent.name),
            url=agent.endpoint_url,
            description=f"A2A Agent: {agent.description or agent.name}",
            auth=AuthenticationValues(auth_type=agent.auth_type, auth_value=agent.auth_value) if agent.auth_type else None,
            tags=normalized_tags,
            visibility=tool.visibility,  # Preserve existing visibility
        )

        # Update the tool
        return await self.update_tool(
            db,
            tool_id=tool.id,
            tool_update=tool_update,
            modified_by=modified_by,
            modified_from_ip=modified_from_ip,
            modified_via=modified_via or "a2a_sync",
            modified_user_agent=modified_user_agent,
        )

    async def delete_tool_from_a2a_agent(self, db: Session, agent: DbA2AAgent, user_email: Optional[str] = None, purge_metrics: bool = False) -> None:
        """Delete the tool associated with an A2A agent when the agent is deleted.

        Args:
            db: Database session.
            agent: The A2A agent being deleted.
            user_email: Email of user performing delete (for ownership check).
            purge_metrics: If True, delete raw + rollup metrics for this tool.
        """
        # Use the tool_id from the agent for efficient lookup
        if not agent.tool_id:
            logger.debug(f"No tool_id found for A2A agent {agent.id}, skipping tool deletion")
            return

        tool = db.get(DbTool, agent.tool_id)
        if not tool:
            logger.warning(f"Tool {agent.tool_id} not found for A2A agent {agent.id}")
            return

        # Delete the tool
        await self.delete_tool(db=db, tool_id=tool.id, user_email=user_email, purge_metrics=purge_metrics)
        logger.info(f"Deleted tool {tool.id} associated with A2A agent {agent.id}")

    async def _invoke_a2a_tool(self, db: Session, tool: DbTool, arguments: Dict[str, Any]) -> ToolResult:
        """Invoke an A2A agent through its corresponding tool.

        Args:
            db: Database session.
            tool: The tool record that represents the A2A agent.
            arguments: Tool arguments.

        Returns:
            Tool result from A2A agent invocation.

        Raises:
            ToolNotFoundError: If the A2A agent is not found.
        """

        # Extract A2A agent ID from tool annotations
        agent_id = tool.annotations.get("a2a_agent_id")
        if not agent_id:
            raise ToolNotFoundError(f"A2A tool '{tool.name}' missing agent ID in annotations")

        # Get the A2A agent
        agent_query = select(DbA2AAgent).where(DbA2AAgent.id == agent_id)
        agent = db.execute(agent_query).scalar_one_or_none()

        if not agent:
            raise ToolNotFoundError(f"A2A agent not found for tool '{tool.name}' (agent ID: {agent_id})")

        if not agent.enabled:
            raise ToolNotFoundError(f"A2A agent '{agent.name}' is disabled")

        # Force-load all attributes needed by _call_a2a_agent before detaching
        # (accessing them ensures they're loaded into the object's __dict__)
        _ = (agent.name, agent.endpoint_url, agent.agent_type, agent.protocol_version, agent.auth_type, agent.auth_value, agent.auth_query_params)

        # Detach agent from session so its loaded data remains accessible after close
        db.expunge(agent)

        # CRITICAL: Release DB connection back to pool BEFORE making HTTP calls
        # This prevents "idle in transaction" connection pool exhaustion under load
        db.commit()
        db.close()

        # Prepare parameters for A2A invocation
        try:
            # Make the A2A agent call (agent is now detached but data is loaded)
            response_data = await self._call_a2a_agent(agent, arguments)

            # Convert A2A response to MCP ToolResult format
            if isinstance(response_data, dict) and "response" in response_data:
                val = response_data["response"]
                content = [TextContent(type="text", text=val if isinstance(val, str) else orjson.dumps(val).decode())]
            else:
                content = [TextContent(type="text", text=response_data if isinstance(response_data, str) else orjson.dumps(response_data).decode())]

            result = ToolResult(content=content, is_error=False)

        except Exception as e:
            error_message = str(e)
            content = [TextContent(type="text", text=f"A2A agent error: {error_message}")]
            result = ToolResult(content=content, is_error=True)

        # Note: Metrics are recorded by the calling invoke_tool method, not here
        return result

    async def _call_a2a_agent(self, agent: DbA2AAgent, parameters: Dict[str, Any]):
        """Call an A2A agent directly.

        Args:
            agent: The A2A agent to call.
            parameters: Parameters for the interaction.

        Returns:
            Response from the A2A agent.

        Raises:
            ToolInvocationError: If authentication decryption fails.
            Exception: If the call fails.
        """
        logger.info(f"Calling A2A agent '{agent.name}' at {agent.endpoint_url} with arguments: {parameters}")

        prepared = prepare_a2a_invocation(
            agent_type=agent.agent_type,
            endpoint_url=agent.endpoint_url,
            protocol_version=agent.protocol_version,
            parameters=parameters,
            interaction_type=str(parameters.get("interaction_type", "query")) if isinstance(parameters, dict) else "query",
            auth_type=agent.auth_type,
            auth_value=agent.auth_value,
            auth_query_params=agent.auth_query_params,
            correlation_id=get_correlation_id(),
        )
        logger.info(f"invoke tool request_data prepared: {prepared.request_data}")

        # First-Party
        from mcpgateway.version import should_delegate_a2a_to_rust  # pylint: disable=import-outside-toplevel

        if should_delegate_a2a_to_rust():
            runtime_response = await get_rust_a2a_runtime_client().invoke(
                prepared,
                timeout_seconds=int(settings.mcpgateway_a2a_default_timeout),
            )
            if int(runtime_response.get("status_code", 200)) == 200:
                return runtime_response.get("json") if runtime_response.get("json") is not None else runtime_response.get("text")
            raise Exception(f"HTTP {runtime_response.get('status_code')}: {runtime_response.get('text')}")

        # Make HTTP request to the agent endpoint using shared HTTP client
        # First-Party
        from mcpgateway.services.http_client_service import get_http_client  # pylint: disable=import-outside-toplevel

        client = await get_http_client()
        http_response = await client.post(prepared.endpoint_url, json=prepared.request_data, headers=prepared.headers)

        if http_response.status_code == 200:
            return http_response.json()

        raise Exception(f"HTTP {http_response.status_code}: {http_response.text}")


# Lazy singleton - created on first access, not at module import time.
# This avoids instantiation when only exception classes are imported.
_tool_service_instance = None  # pylint: disable=invalid-name


def __getattr__(name: str):
    """Module-level __getattr__ for lazy singleton creation.

    Args:
        name: The attribute name being accessed.

    Returns:
        The tool_service singleton instance if name is "tool_service".

    Raises:
        AttributeError: If the attribute name is not "tool_service".
    """
    global _tool_service_instance  # pylint: disable=global-statement
    if name == "tool_service":
        if _tool_service_instance is None:
            _tool_service_instance = ToolService()
        return _tool_service_instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
