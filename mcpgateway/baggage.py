# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/baggage.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

OpenTelemetry W3C Baggage support for HTTP header extraction and propagation.

This module provides secure header-to-baggage conversion with:
- Strict allowlist validation (fail-closed security model)
- Value sanitization (reuses translate_header_utils.py)
- Size limits (DoS prevention)
- Audit logging for rejected headers
- Dual processing model: strict for headers, permissive for existing baggage
"""

# Standard
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

# First-Party
from mcpgateway.config import get_settings
from mcpgateway.translate_header_utils import ALLOWED_HEADERS_REGEX, MAX_HEADER_VALUE_LENGTH, sanitize_header_value

logger = logging.getLogger(__name__)

# W3C Baggage specification constants
BAGGAGE_HEADER_NAME = "baggage"
BAGGAGE_KEY_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\.\-]*$")
MAX_BAGGAGE_KEY_LENGTH = 256


class BaggageError(Exception):
    """Base exception for baggage processing errors."""


class BaggageConfigError(BaggageError):
    """Raised when baggage configuration is invalid."""


class BaggageSizeLimitError(BaggageError):
    """Raised when baggage size limits are exceeded."""


class HeaderMapping:
    """Represents a validated header-to-baggage mapping.

    Examples:
        >>> mapping = HeaderMapping("X-Tenant-ID", "tenant.id")
        >>> mapping.header_name
        'X-Tenant-ID'
        >>> mapping.baggage_key
        'tenant.id'
        >>> mapping.header_name_lower
        'x-tenant-id'
    """

    def __init__(self, header_name: str, baggage_key: str):
        """Initialize a header mapping.

        Args:
            header_name: HTTP header name (e.g., "X-Tenant-ID")
            baggage_key: Baggage key (e.g., "tenant.id")

        Raises:
            BaggageConfigError: If validation fails
        """
        self.header_name = header_name
        self.baggage_key = baggage_key
        self.header_name_lower = header_name.lower()
        self._validate()

    def _validate(self) -> None:
        """Validate header name and baggage key.

        Raises:
            BaggageConfigError: If validation fails
        """
        # Validate header name (reuse existing regex)
        if not ALLOWED_HEADERS_REGEX.match(self.header_name):
            raise BaggageConfigError(f"Invalid header name '{self.header_name}' - must start with letter and contain only alphanumeric characters and hyphens")

        # Validate baggage key (W3C spec: alphanumeric + dots, underscores, hyphens)
        if not BAGGAGE_KEY_REGEX.match(self.baggage_key):
            raise BaggageConfigError(f"Invalid baggage key '{self.baggage_key}' - must start with letter and contain only alphanumeric, dots, underscores, hyphens")

        if len(self.baggage_key) > MAX_BAGGAGE_KEY_LENGTH:
            raise BaggageConfigError(f"Baggage key too long: {self.baggage_key} (max {MAX_BAGGAGE_KEY_LENGTH} chars)")

    def __repr__(self) -> str:
        """Return string representation.

        Returns:
            String representation of the mapping
        """
        return f"HeaderMapping(header_name='{self.header_name}', baggage_key='{self.baggage_key}')"


class BaggageConfig:
    """Validated baggage configuration loaded from settings.

    Examples:
        >>> config = BaggageConfig.from_settings()
        >>> config.enabled
        False
        >>> len(config.mappings)
        0
    """

    def __init__(
        self,
        enabled: bool,
        mappings: List[HeaderMapping],
        propagate_to_external: bool,
        max_items: int,
        max_size_bytes: int,
        log_rejected: bool,
        log_sanitization: bool,
    ):
        """Initialize baggage configuration.

        Args:
            enabled: Whether baggage processing is enabled
            mappings: List of validated header mappings
            propagate_to_external: Whether to propagate baggage downstream
            max_items: Maximum number of baggage items from headers
            max_size_bytes: Maximum total size of header-derived baggage
            log_rejected: Whether to log rejected headers
            log_sanitization: Whether to log sanitization events
        """
        self.enabled = enabled
        self.mappings = mappings
        self.propagate_to_external = propagate_to_external
        self.max_items = max_items
        self.max_size_bytes = max_size_bytes
        self.log_rejected = log_rejected
        self.log_sanitization = log_sanitization

        # Build lookup map for O(1) header matching
        self._header_to_baggage: Dict[str, str] = {m.header_name_lower: m.baggage_key for m in mappings}

    def get_baggage_key(self, header_name: str) -> Optional[str]:
        """Get baggage key for a header name (case-insensitive).

        Args:
            header_name: HTTP header name

        Returns:
            Baggage key or None if not mapped

        Examples:
            >>> config = BaggageConfig(True, [HeaderMapping("X-Tenant-ID", "tenant.id")], False, 32, 8192, True, True)
            >>> config.get_baggage_key("X-Tenant-ID")
            'tenant.id'
            >>> config.get_baggage_key("x-tenant-id")
            'tenant.id'
            >>> config.get_baggage_key("Unknown") is None
            True
        """
        return self._header_to_baggage.get(header_name.lower())

    @classmethod
    def from_settings(cls) -> "BaggageConfig":
        """Load and validate baggage configuration from settings.

        Returns:
            Validated BaggageConfig instance

        Raises:
            BaggageConfigError: If configuration is invalid
        """
        settings = get_settings()

        if not settings.otel_baggage_enabled:
            return cls(
                enabled=False,
                mappings=[],
                propagate_to_external=False,
                max_items=32,
                max_size_bytes=8192,
                log_rejected=True,
                log_sanitization=True,
            )

        # Parse header mappings from JSON
        # Third-Party
        import orjson

        try:
            mappings_data = orjson.loads(settings.otel_baggage_header_mappings)
        except orjson.JSONDecodeError as e:
            raise BaggageConfigError(f"Invalid JSON in OTEL_BAGGAGE_HEADER_MAPPINGS: {e}") from e

        if not isinstance(mappings_data, list):
            raise BaggageConfigError("OTEL_BAGGAGE_HEADER_MAPPINGS must be a JSON array")

        # Validate and create mappings
        mappings: List[HeaderMapping] = []
        seen_headers: Dict[str, str] = {}  # lowercase -> original for duplicate detection
        seen_keys: set[str] = set()

        for idx, item in enumerate(mappings_data):
            if not isinstance(item, dict):
                raise BaggageConfigError(f"Mapping at index {idx} must be an object with 'header_name' and 'baggage_key'")

            header_name = item.get("header_name")
            baggage_key = item.get("baggage_key")

            if not header_name or not baggage_key:
                raise BaggageConfigError(f"Mapping at index {idx} missing 'header_name' or 'baggage_key'")

            if not isinstance(header_name, str) or not isinstance(baggage_key, str):
                raise BaggageConfigError(f"Mapping at index {idx} 'header_name' and 'baggage_key' must be strings")

            # Check for case-insensitive duplicate headers
            header_lower = header_name.lower()
            if header_lower in seen_headers:
                raise BaggageConfigError(f"Duplicate header mapping (case-insensitive): '{header_name}' conflicts with '{seen_headers[header_lower]}'")

            # Check for duplicate baggage keys
            if baggage_key in seen_keys:
                raise BaggageConfigError(f"Duplicate baggage key: '{baggage_key}'")

            mapping = HeaderMapping(header_name, baggage_key)
            mappings.append(mapping)
            seen_headers[header_lower] = header_name
            seen_keys.add(baggage_key)

        if len(mappings) > settings.otel_baggage_max_items:
            raise BaggageConfigError(f"Too many header mappings: {len(mappings)} (max {settings.otel_baggage_max_items})")

        logger.info(f"Loaded {len(mappings)} baggage header mappings")

        return cls(
            enabled=True,
            mappings=mappings,
            propagate_to_external=settings.otel_baggage_propagate_to_external,
            max_items=settings.otel_baggage_max_items,
            max_size_bytes=settings.otel_baggage_max_size_bytes,
            log_rejected=settings.otel_baggage_log_rejected,
            log_sanitization=settings.otel_baggage_log_sanitization,
        )


def extract_baggage_from_headers(
    headers: Dict[str, str],
    config: BaggageConfig,
) -> Dict[str, str]:
    """Extract baggage from HTTP headers using configured mappings.

    This implements the strict security model:
    - Only explicitly configured headers are processed
    - Undefined headers are dropped and logged
    - All values are sanitized
    - Size limits are enforced

    Args:
        headers: HTTP request headers (case-insensitive keys)
        config: Validated baggage configuration

    Returns:
        Dictionary of baggage_key -> sanitized_value

    Raises:
        BaggageSizeLimitError: If size limits are exceeded

    Examples:
        >>> config = BaggageConfig(True, [HeaderMapping("X-Tenant-ID", "tenant.id")], False, 32, 8192, True, True)
        >>> headers = {"x-tenant-id": "tenant-123", "x-unknown": "value"}
        >>> result = extract_baggage_from_headers(headers, config)
        >>> result
        {'tenant.id': 'tenant-123'}
    """
    if not config.enabled or not config.mappings:
        return {}

    baggage: Dict[str, str] = {}
    total_size = 0

    # Normalize headers to lowercase for O(1) lookups
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    for mapping in config.mappings:
        header_value = normalized_headers.get(mapping.header_name_lower)

        if header_value is None:
            continue

        # Check item limit
        if len(baggage) >= config.max_items:
            if config.log_rejected:
                logger.warning(f"Baggage item limit reached ({config.max_items}), dropping header '{mapping.header_name}'")
            break

        # Sanitize value (reuse existing security function)
        try:
            sanitized_value = sanitize_header_value(header_value, max_length=MAX_HEADER_VALUE_LENGTH)

            if not sanitized_value:
                if config.log_sanitization:
                    logger.warning(f"Header '{mapping.header_name}' value became empty after sanitization, skipping")
                continue

            # Check if sanitization changed the value
            if config.log_sanitization and sanitized_value != header_value:
                logger.info(f"Sanitized header '{mapping.header_name}' value (length: {len(header_value)} -> {len(sanitized_value)})")

            # Check size limit
            entry_size = len(mapping.baggage_key) + len(sanitized_value) + 2  # key=value overhead
            if total_size + entry_size > config.max_size_bytes:
                if config.log_rejected:
                    logger.warning(f"Baggage size limit reached ({config.max_size_bytes} bytes), dropping header '{mapping.header_name}'")
                break

            baggage[mapping.baggage_key] = sanitized_value
            total_size += entry_size

            logger.debug(f"Mapped header '{mapping.header_name}' to baggage key '{mapping.baggage_key}'")

        except Exception as e:
            logger.warning(f"Failed to process header '{mapping.header_name}': {e}")
            continue

    # Log rejected undefined headers (security audit)
    if config.log_rejected:
        configured_headers = {m.header_name_lower for m in config.mappings}
        for header_name in normalized_headers:
            if header_name.startswith("x-") and header_name not in configured_headers:
                logger.debug(f"Rejected undefined header '{header_name}' (not in allowlist)")

    return baggage


def parse_w3c_baggage_header(baggage_header: str) -> Dict[str, str]:
    """Parse W3C baggage header into key-value pairs.

    Implements W3C Baggage specification parsing:
    - Format: key1=value1,key2=value2
    - Values are URL-encoded
    - Metadata (;properties) is ignored

    Args:
        baggage_header: Raw baggage header value

    Returns:
        Dictionary of baggage key -> decoded value

    Examples:
        >>> parse_w3c_baggage_header("tenant.id=tenant-123,user.id=user-456")
        {'tenant.id': 'tenant-123', 'user.id': 'user-456'}
        >>> parse_w3c_baggage_header("key=value%20with%20spaces")
        {'key': 'value with spaces'}
        >>> parse_w3c_baggage_header("")
        {}
    """
    baggage: Dict[str, str] = {}

    if not baggage_header:
        return baggage

    # Split by comma (list members)
    for member in baggage_header.split(","):
        member = member.strip()
        if not member:
            continue

        # Split by semicolon (key=value;properties)
        parts = member.split(";", 1)
        key_value = parts[0].strip()

        if "=" not in key_value:
            logger.debug(f"Skipping invalid baggage member (no '='): {key_value}")
            continue

        key, value = key_value.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            continue

        try:
            # URL-decode value per W3C spec
            decoded_value = unquote(value)
            baggage[key] = decoded_value
        except Exception as e:
            logger.debug(f"Failed to decode baggage value for key '{key}': {e}")
            continue

    return baggage


def filter_incoming_baggage(
    baggage: Dict[str, str],
    config: BaggageConfig,
) -> Dict[str, str]:
    """Filter untrusted inbound baggage using the configured baggage-key allowlist.

    Incoming HTTP baggage is external input. Apply the same fail-closed posture used
    for mapped headers: only configured baggage keys are accepted and values remain
    subject to sanitization and size limits.

    Args:
        baggage: Dictionary of baggage key-value pairs to filter
        config: BaggageConfig instance with allowlist and limits

    Returns:
        Filtered dictionary containing only allowed baggage keys
    """
    if not config.enabled or not baggage:
        return {}

    allowed_keys = {mapping.baggage_key for mapping in config.mappings}
    filtered: Dict[str, str] = {}
    total_size = 0

    for key, value in baggage.items():
        if key not in allowed_keys:
            if config.log_rejected:
                logger.debug(f"Rejected inbound baggage key '{key}' (not in allowlist)")
            continue

        if len(filtered) >= config.max_items:
            if config.log_rejected:
                logger.warning(f"Inbound baggage item limit reached ({config.max_items}), dropping key '{key}'")
            break

        try:
            sanitized_value = sanitize_header_value(value, max_length=MAX_HEADER_VALUE_LENGTH)
            if not sanitized_value:
                if config.log_sanitization:
                    logger.warning(f"Inbound baggage key '{key}' value became empty after sanitization, skipping")
                continue

            if config.log_sanitization and sanitized_value != value:
                logger.info(f"Sanitized inbound baggage key '{key}' value (length: {len(value)} -> {len(sanitized_value)})")

            entry_size = len(key) + len(sanitized_value) + 2
            if total_size + entry_size > config.max_size_bytes:
                if config.log_rejected:
                    logger.warning(f"Inbound baggage size limit reached ({config.max_size_bytes} bytes), dropping key '{key}'")
                break

            filtered[key] = sanitized_value
            total_size += entry_size
        except Exception as e:
            logger.warning(f"Failed to process inbound baggage key '{key}': {e}")

    return filtered


def format_w3c_baggage_header(baggage: Dict[str, str]) -> str:
    """Format baggage dictionary as W3C baggage header value.

    Args:
        baggage: Dictionary of baggage key -> value

    Returns:
        W3C baggage header value (comma-separated key=value pairs)

    Examples:
        >>> format_w3c_baggage_header({"tenant.id": "tenant-123", "user.id": "user-456"})
        'tenant.id=tenant-123,user.id=user-456'
        >>> format_w3c_baggage_header({})
        ''
    """
    if not baggage:
        return ""

    members: List[str] = []
    for key, value in baggage.items():
        # URL-encode value per W3C spec
        encoded_value = quote(value, safe="")
        members.append(f"{key}={encoded_value}")

    return ",".join(members)


def merge_baggage(
    header_baggage: Dict[str, str],
    existing_baggage: Dict[str, str],
) -> Dict[str, str]:
    """Merge header-derived baggage with existing upstream baggage.

    Implements the request merge model:
    - Header-derived baggage: validated and size-limited
    - Existing baggage: already filtered before merge

    Header-derived baggage takes precedence over existing baggage.

    Args:
        header_baggage: Baggage extracted from headers (validated)
        existing_baggage: Baggage from upstream services (trusted)

    Returns:
        Merged baggage dictionary

    Examples:
        >>> merge_baggage({"tenant.id": "new-123"}, {"tenant.id": "old-123", "user.id": "user-456"})
        {'tenant.id': 'new-123', 'user.id': 'user-456'}
        >>> merge_baggage({}, {"key": "value"})
        {'key': 'value'}
    """
    # Start with existing baggage (trusted context)
    merged = dict(existing_baggage)

    # Overlay header-derived baggage (takes precedence)
    merged.update(header_baggage)

    return merged


def sanitize_baggage_for_propagation(baggage: Dict[str, str]) -> Dict[str, str]:
    """Sanitize baggage values before propagation to downstream services.

    Applies sanitization to all values before propagation.

    Args:
        baggage: Baggage dictionary to sanitize

    Returns:
        Sanitized baggage dictionary

    Examples:
        >>> sanitize_baggage_for_propagation({"key": "value\\x00with\\x01control"})
        {'key': 'valuewithcontrol'}
    """
    sanitized: Dict[str, str] = {}

    for key, value in baggage.items():
        try:
            # Sanitize value (remove control characters, etc.)
            sanitized_value = sanitize_header_value(value, max_length=MAX_HEADER_VALUE_LENGTH)
            if sanitized_value:
                sanitized[key] = sanitized_value
        except Exception as e:
            logger.debug(f"Failed to sanitize baggage value for key '{key}': {e}")
            continue

    return sanitized
