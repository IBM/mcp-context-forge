# -*- coding: utf-8 -*-
"""Trace payload redaction and bounded serialization helpers."""

# Standard
import json
import os
import re
from typing import Any

_DEFAULT_REDACT_FIELDS = "password,secret,token,api_key,authorization,credential,auth_value," "access_token,refresh_token,auth_token,client_secret,cookie,set-cookie," "private_key"
_DEFAULT_MAX_PAYLOAD_SIZE = 32768

_CONFIG_LOADED = False
_REDACT_FIELDS: set[str] = set()
_MAX_PAYLOAD_SIZE = _DEFAULT_MAX_PAYLOAD_SIZE
_OUTPUT_CAPTURE_SPANS: set[str] = set()


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
    global _CONFIG_LOADED, _MAX_PAYLOAD_SIZE, _OUTPUT_CAPTURE_SPANS, _REDACT_FIELDS  # pylint: disable=global-statement

    fields = os.getenv("OTEL_REDACT_FIELDS", _DEFAULT_REDACT_FIELDS)
    _REDACT_FIELDS = {_normalize_field_name(field.strip()) for field in fields.split(",") if field.strip()}
    _MAX_PAYLOAD_SIZE = _coerce_int(os.getenv("OTEL_MAX_TRACE_PAYLOAD_SIZE", str(_DEFAULT_MAX_PAYLOAD_SIZE)), _DEFAULT_MAX_PAYLOAD_SIZE)
    _OUTPUT_CAPTURE_SPANS = {span.strip() for span in os.getenv("OTEL_CAPTURE_OUTPUT_SPANS", "").split(",") if span.strip()}
    _CONFIG_LOADED = True


def reload_trace_redaction_config() -> None:
    """Reload trace redaction configuration from the current environment."""
    global _CONFIG_LOADED  # pylint: disable=global-statement
    _CONFIG_LOADED = False
    _load_config()


def _ensure_loaded() -> None:
    """Load configuration on first use."""
    if not _CONFIG_LOADED:
        _load_config()


def redact_sensitive_fields(data: Any) -> Any:
    """Recursively redact sensitive values in dictionaries and lists.

    Args:
        data: Arbitrary payload to redact.

    Returns:
        Redacted payload preserving the original container structure where possible.
    """
    _ensure_loaded()

    if isinstance(data, dict):
        redacted: dict[Any, Any] = {}
        for key, value in data.items():
            normalized_key = _normalize_field_name(str(key))
            redacted[key] = "***" if normalized_key in _REDACT_FIELDS else redact_sensitive_fields(value)
        return redacted

    if isinstance(data, list):
        return [redact_sensitive_fields(item) for item in data]

    if isinstance(data, tuple):
        return tuple(redact_sensitive_fields(item) for item in data)

    return data


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
