# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/trace_redaction.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Trace payload redaction and bounded serialization helpers.
"""

# Standard
import json
import re
from typing import Any

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.utils.url_auth import sanitize_exception_message, sanitize_url_for_logging

_DEFAULT_REDACT_FIELDS = ",".join(
    [
        "password",
        "secret",
        "token",
        "api_key",
        "authorization",
        "credential",
        "auth_value",
        "access_token",
        "refresh_token",
        "auth_token",
        "client_secret",
        "cookie",
        "set-cookie",
        "private_key",
        "session_id",
        "sessionid",
    ]
)
_DEFAULT_MAX_PAYLOAD_SIZE = 32768

_CONFIG_LOADED = False
_REDACT_FIELDS: set[str] = set()
_MAX_PAYLOAD_SIZE = _DEFAULT_MAX_PAYLOAD_SIZE
_INPUT_CAPTURE_SPANS: set[str] = set()
_OUTPUT_CAPTURE_SPANS: set[str] = set()
_TEXT_REDACT_PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str]]] = []


def _normalize_field_name(value: str) -> str:
    """Normalize a field name for loose matching across key styles.

    Args:
        value: Raw field name to normalize.

    Returns:
        Lowercase alphanumeric field name used for loose redaction matching.
    """
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _coerce_int(value: str, default: int) -> int:
    """Coerce an integer env var with a sane minimum.

    Args:
        value: Raw environment variable value.
        default: Fallback value to use when parsing fails.

    Returns:
        Parsed integer constrained to the configured minimum, or ``default`` on failure.
    """
    try:
        return max(256, int(value))
    except (TypeError, ValueError):
        return default


def _load_config() -> None:
    """Load redaction and output-capture configuration from the environment."""
    global _CONFIG_LOADED, _INPUT_CAPTURE_SPANS, _MAX_PAYLOAD_SIZE, _OUTPUT_CAPTURE_SPANS, _REDACT_FIELDS, _TEXT_REDACT_PATTERNS  # pylint: disable=global-statement

    settings = get_settings()
    fields = settings.otel_redact_fields or _DEFAULT_REDACT_FIELDS
    raw_fields = [field.strip() for field in fields.split(",") if field.strip()]
    _REDACT_FIELDS = {_normalize_field_name(field) for field in raw_fields}
    _MAX_PAYLOAD_SIZE = _coerce_int(str(settings.otel_max_trace_payload_size), _DEFAULT_MAX_PAYLOAD_SIZE)
    _INPUT_CAPTURE_SPANS = {span.strip() for span in settings.otel_capture_input_spans.split(",") if span.strip()}
    _OUTPUT_CAPTURE_SPANS = {span.strip() for span in settings.otel_capture_output_spans.split(",") if span.strip()}
    _TEXT_REDACT_PATTERNS = [_build_text_redaction_patterns(field) for field in raw_fields]
    _CONFIG_LOADED = True


def reload_trace_redaction_config() -> None:
    """Reload trace redaction configuration from the current environment."""
    global _CONFIG_LOADED  # pylint: disable=global-statement
    get_settings.cache_clear()
    _CONFIG_LOADED = False
    _load_config()


def _ensure_loaded() -> None:
    """Load configuration on first use."""
    if not _CONFIG_LOADED:
        _load_config()


def redact_sensitive_fields(data: Any) -> Any:
    """Recursively redact sensitive values in structured or scalar payloads.

    Args:
        data: Arbitrary payload to redact.

    Returns:
        Redacted payload preserving the original container structure where possible.
    """
    _ensure_loaded()
    data = _prepare_for_json(data)

    if isinstance(data, dict):
        redacted: dict[Any, Any] = {}
        for key, value in data.items():
            normalized_key = _normalize_field_name(str(key))
            if normalized_key in _REDACT_FIELDS:
                redacted[key] = "***"
            else:
                redacted[key] = _sanitize_trace_value(str(key), value)
        return redacted

    if isinstance(data, list):
        return [_sanitize_trace_value("item", item) for item in data]

    if isinstance(data, tuple):
        return tuple(_sanitize_trace_value("item", item) for item in data)

    if isinstance(data, str):
        return sanitize_trace_text(data)

    return data


def _field_looks_like_url(field_name: str) -> bool:
    """Return whether a normalized field name likely carries a URL or URI.

    Args:
        field_name: Candidate field name.

    Returns:
        ``True`` when the field likely carries a URL, URI, or endpoint value.
    """
    normalized = _normalize_field_name(field_name)
    return normalized.endswith("url") or normalized.endswith("uri") or normalized.endswith("endpoint")


def _sanitize_trace_value(field_name: str, value: Any) -> Any:
    """Sanitize a trace value using field-name context.

    Args:
        field_name: Field name associated with the value.
        value: Value to sanitize.

    Returns:
        Sanitized value with recursive redaction applied where appropriate.
    """
    prepared = _prepare_for_json(value)

    if isinstance(prepared, dict):
        return redact_sensitive_fields(prepared)

    if isinstance(prepared, list):
        return [_sanitize_trace_value(field_name, item) for item in prepared]

    if isinstance(prepared, tuple):
        return tuple(_sanitize_trace_value(field_name, item) for item in prepared)

    if isinstance(prepared, str):
        if _field_looks_like_url(field_name):
            return sanitize_url_for_logging(prepared)
        return sanitize_trace_text(prepared)

    return prepared


def _field_name_text_pattern(field_name: str) -> str:
    """Build a permissive regex for matching a field name in free text.

    Args:
        field_name: Configured field name, potentially containing separators.

    Returns:
        Regex snippet that tolerates separator variations such as ``_`` or ``-``.
    """
    parts = [re.escape(part) for part in re.split(r"[^A-Za-z0-9]+", field_name) if part]
    if not parts:
        return re.escape(field_name)
    return r"[\W_]*".join(parts)


def _build_text_redaction_patterns(field_name: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Build regexes that redact free-text ``key=value`` and ``key:"value"`` secrets.

    Args:
        field_name: Configured sensitive field name.

    Returns:
        Tuple of quoted-value and bare-value regex patterns.
    """
    key_pattern = _field_name_text_pattern(field_name)
    quoted_pattern = re.compile(rf"(?i)(\b{key_pattern}\b\s*(?:=|:)\s*['\"])([^'\"]*)(['\"])", re.IGNORECASE)
    # Include & as a terminator for URL query parameters
    bare_pattern = re.compile(rf"(?i)(\b{key_pattern}\b\s*(?:=|:)\s*)(?!['\"])(?!REDACTED\b)(?!\*\*\*)([^\s,;&]+)", re.IGNORECASE)
    return quoted_pattern, bare_pattern


def sanitize_trace_text(text: str) -> str:
    """Sanitize free-text trace content such as exception messages.

    This redacts embedded URLs with sensitive query parameters, common
    ``key=value`` or ``key: value`` secret patterns derived from
    ``OTEL_REDACT_FIELDS``, and standalone bearer/basic credentials.

    Args:
        text: Raw free-text value.

    Returns:
        Sanitized text safe to attach to trace metadata.
    """
    _ensure_loaded()
    sanitized = sanitize_exception_message(text)
    sanitized = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+(?=$|[\s,;\x27\x22])", r"\1 ***", sanitized)

    for quoted_pattern, bare_pattern in _TEXT_REDACT_PATTERNS:
        sanitized = quoted_pattern.sub(r"\1***\3", sanitized)
        sanitized = bare_pattern.sub(r"\1***", sanitized)

    sanitized = re.sub(r"\*\*\*(?:\s+\*\*\*)+", "***", sanitized)
    return sanitized


def sanitize_trace_attribute_value(attribute_name: str, value: Any) -> Any:
    """Sanitize a scalar or structured span attribute before export.

    Args:
        attribute_name: Span attribute key.
        value: Attribute value.

    Returns:
        Sanitized attribute value.
    """
    _ensure_loaded()

    normalized_key = _normalize_field_name(attribute_name)
    if normalized_key in _REDACT_FIELDS:
        return "***"

    return _sanitize_trace_value(attribute_name, value)


def is_input_capture_enabled(span_name: str) -> bool:
    """Return whether input capture is enabled for the given span name.

    Args:
        span_name: Span name to check against the configured allowlist.

    Returns:
        ``True`` when input capture is enabled for the span.
    """
    _ensure_loaded()
    return span_name in _INPUT_CAPTURE_SPANS


def is_output_capture_enabled(span_name: str) -> bool:
    """Return whether output capture is enabled for the given span name.

    Args:
        span_name: Span name to check against the configured allowlist.

    Returns:
        ``True`` when output capture is enabled for the span.
    """
    _ensure_loaded()
    return span_name in _OUTPUT_CAPTURE_SPANS


def _prepare_for_json(value: Any) -> Any:
    """Convert Pydantic-like objects to JSON-ready data when possible.

    Args:
        value: Arbitrary object that may support ``model_dump``.

    Returns:
        JSON-ready representation of ``value`` when conversion is available, otherwise the original object.
    """
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json", by_alias=True)
    return value


def _iterencode_preview(value: Any, max_size: int) -> tuple[str, bool, int]:
    """Serialize JSON incrementally while keeping only a bounded preview.

    Args:
        value: JSON-serializable value to encode.
        max_size: Maximum preview size to retain while encoding.

    Returns:
        Tuple of preview text, truncation flag, and full serialized size.
    """
    encoder = json.JSONEncoder(ensure_ascii=False, default=str, separators=(",", ":"))
    preview_chunks: list[str] = []
    preview_size = 0
    total_size = 0
    truncated = False

    for chunk in encoder.iterencode(value):
        chunk_length = len(chunk)
        remaining = max_size - preview_size
        total_size += chunk_length
        if preview_size < max_size:
            preview_chunks.append(chunk[:remaining])
            preview_size += min(chunk_length, remaining)
        if total_size > max_size:
            truncated = True

    return "".join(preview_chunks), truncated, total_size


def _bounded_truncation_wrapper(preview: str, total_size: int, max_size: int) -> str:
    """Wrap a truncated preview in valid JSON that fits within the size budget.

    Args:
        preview: Truncated serialized preview content.
        total_size: Size of the original full serialized payload.
        max_size: Maximum number of characters allowed for the wrapped payload.

    Returns:
        Valid JSON string describing the truncation while fitting within ``max_size``.
    """
    payload = {"_truncated": True, "_original_size": total_size, "_preview": preview}
    wrapped = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    while len(wrapped) > max_size and payload["_preview"]:
        overflow = len(wrapped) - max_size
        payload["_preview"] = payload["_preview"][: max(0, len(payload["_preview"]) - overflow - 1)]
        wrapped = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    if len(wrapped) <= max_size:
        return wrapped

    minimal = json.dumps({"_truncated": True}, ensure_ascii=False, separators=(",", ":"))
    if len(minimal) <= max_size:
        return minimal

    return minimal[:max_size]


def safe_serialize(obj: Any, max_size: int = 0) -> str:
    """Serialize a trace payload to bounded JSON.

    Args:
        obj: Arbitrary payload to serialize.
        max_size: Optional maximum serialized size. When zero, the configured default is used.

    Returns:
        JSON string representation of the payload, truncated safely when necessary.
    """
    _ensure_loaded()
    effective_max_size = max_size or _MAX_PAYLOAD_SIZE

    try:
        prepared = _prepare_for_json(obj)

        if isinstance(prepared, (dict, list, tuple)):
            preview, truncated, total_size = _iterencode_preview(prepared, effective_max_size)
            if not truncated:
                return preview
            return _bounded_truncation_wrapper(preview, total_size, effective_max_size)

        scalar_preview, truncated, total_size = _iterencode_preview(prepared, effective_max_size)
        if not truncated:
            return scalar_preview
        return _bounded_truncation_wrapper(scalar_preview, total_size, effective_max_size)
    except Exception:
        return json.dumps({"_error": "serialization_failed"}, ensure_ascii=False, separators=(",", ":"))


def serialize_trace_payload(obj: Any, max_size: int = 0) -> str:
    """Redact and serialize a trace payload to bounded JSON.

    Args:
        obj: Arbitrary payload to sanitize and serialize.
        max_size: Optional maximum serialized size. When zero, the configured default is used.

    Returns:
        JSON string representation of the sanitized payload.
    """
    return safe_serialize(redact_sensitive_fields(obj), max_size=max_size)
