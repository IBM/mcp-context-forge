# -*- coding: utf-8 -*-
"""Header processing utilities for dynamic environment injection in translate module.

Location: ./mcpgateway/translate_header_utils.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Manav Gupta

Header processing utilities for dynamic environment variable injection in mcpgateway.translate.
"""

# Standard
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

# Security constants
ALLOWED_HEADERS_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*$")
MAX_HEADER_VALUE_LENGTH = 4096
MAX_ENV_VAR_NAME_LENGTH = 64


class HeaderMappingError(Exception):
    """Raised when header mapping configuration is invalid."""


def validate_header_mapping(header_name: str, env_var_name: str) -> None:
    """Validate header name and environment variable name.

    Args:
        header_name: HTTP header name
        env_var_name: Environment variable name

    Raises:
        HeaderMappingError: If validation fails

    Examples:
        >>> # Valid mappings
        >>> validate_header_mapping("Authorization", "AUTH_TOKEN")
        >>> validate_header_mapping("X-Custom-Header", "CUSTOM_VAR")
        >>>
        >>> # Invalid header name
        >>> try:
        ...     validate_header_mapping("Invalid Header!", "VAR")
        ... except HeaderMappingError as e:
        ...     "Invalid header name" in str(e)
        True
        >>>
        >>> # Invalid env var name
        >>> try:
        ...     validate_header_mapping("Header", "123_VAR")
        ... except HeaderMappingError as e:
        ...     "Invalid environment variable name" in str(e)
        True
    """
    if not ALLOWED_HEADERS_REGEX.match(header_name):
        raise HeaderMappingError(f"Invalid header name '{header_name}' - must contain only alphanumeric characters and hyphens")

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", env_var_name):
        raise HeaderMappingError(f"Invalid environment variable name '{env_var_name}' - must start with letter/underscore and contain only alphanumeric characters and underscores")

    if len(env_var_name) > MAX_ENV_VAR_NAME_LENGTH:
        raise HeaderMappingError(f"Environment variable name too long: {env_var_name}")


def sanitize_header_value(value: str, max_length: int = MAX_HEADER_VALUE_LENGTH) -> str:
    """Sanitize header value for environment variable injection.

    Args:
        value: Raw header value
        max_length: Maximum allowed length for the value

    Returns:
        Sanitized value safe for environment variable

    Examples:
        >>> # Normal value passes through
        >>> sanitize_header_value("Bearer token123")
        'Bearer token123'
        >>>
        >>> # Long value gets truncated
        >>> sanitize_header_value("a" * 100, max_length=10)
        'aaaaaaaaaa'
        >>>
        >>> # Non-printable characters removed
        >>> sanitize_header_value("hello\\x00world")
        'helloworld'
        >>>
        >>> # Only printable ASCII kept
        >>> sanitize_header_value("test\\x01value")
        'testvalue'
    """
    if len(value) > max_length:
        logger.warning(f"Header value truncated from {len(value)} to {max_length} characters")
        value = value[:max_length]

    # Remove potentially dangerous characters
    value = re.sub(r"[^\x20-\x7E]", "", value)  # Only printable ASCII
    value = value.replace("\x00", "")  # Remove null bytes

    return value


def parse_header_mappings(header_mappings: List[str]) -> Dict[str, str]:
    """Parse header-to-environment mappings from CLI arguments.

    Args:
        header_mappings: List of "HEADER=ENV_VAR" strings

    Returns:
        Dictionary mapping header names to environment variable names

    Raises:
        HeaderMappingError: If any mapping is invalid, including case-insensitive duplicates

    Examples:
        >>> # Parse valid mappings
        >>> parse_header_mappings(["Authorization=AUTH_TOKEN"])
        {'Authorization': 'AUTH_TOKEN'}
        >>>
        >>> # Multiple mappings
        >>> result = parse_header_mappings(["X-Api-Key=API_KEY", "X-User-Id=USER_ID"])
        >>> result == {'X-Api-Key': 'API_KEY', 'X-User-Id': 'USER_ID'}
        True
        >>>
        >>> # Invalid format (no equals)
        >>> try:
        ...     parse_header_mappings(["InvalidMapping"])
        ... except HeaderMappingError as e:
        ...     "Invalid mapping format" in str(e)
        True
        >>>
        >>> # Empty list returns empty dict
        >>> parse_header_mappings([])
        {}
        >>>
        >>> # Case-insensitive duplicates are rejected
        >>> try:
        ...     parse_header_mappings(["Authorization=AUTH1", "authorization=AUTH2"])
        ... except HeaderMappingError as e:
        ...     "Case-insensitive duplicate" in str(e)
        True
    """
    mappings = {}
    # Track lowercase header names to detect case-insensitive duplicates
    seen_lowercase: Dict[str, str] = {}

    for mapping in header_mappings:
        if "=" not in mapping:
            raise HeaderMappingError(f"Invalid mapping format '{mapping}' - expected HEADER=ENV_VAR")

        header_name, env_var_name = mapping.split("=", 1)
        header_name = header_name.strip()
        env_var_name = env_var_name.strip()

        if not header_name or not env_var_name:
            raise HeaderMappingError(f"Empty header name or environment variable name in '{mapping}'")

        validate_header_mapping(header_name, env_var_name)

        # Check for exact duplicate
        if header_name in mappings:
            raise HeaderMappingError(f"Duplicate header mapping for '{header_name}'")

        # Check for case-insensitive duplicate (e.g., "Authorization" and "authorization")
        header_lower = header_name.lower()
        if header_lower in seen_lowercase:
            original = seen_lowercase[header_lower]
            raise HeaderMappingError(f"Case-insensitive duplicate header mapping: '{header_name}' conflicts with '{original}'")

        seen_lowercase[header_lower] = header_name
        mappings[header_name] = env_var_name

    return mappings


def normalize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Normalize request headers to lowercase keys for O(1) lookups.

    Args:
        headers: HTTP request headers with original case

    Returns:
        Dictionary with lowercase keys mapping to original values

    Examples:
        >>> normalize_headers({"Authorization": "Bearer token", "X-Api-Key": "key123"})
        {'authorization': 'Bearer token', 'x-api-key': 'key123'}
        >>> normalize_headers({})
        {}
        >>> normalize_headers({"CONTENT-TYPE": "application/json"})
        {'content-type': 'application/json'}
    """
    return {k.lower(): v for k, v in headers.items()}


class NormalizedMappings:
    """Pre-normalized header mappings for efficient lookups.

    Stores mappings with lowercase header keys for O(1) case-insensitive lookups.
    Intended to be created once at config load time for repeated use.

    Examples:
        >>> mappings = NormalizedMappings({"Authorization": "AUTH_TOKEN", "X-Api-Key": "API_KEY"})
        >>> mappings.get_env_var("authorization")
        'AUTH_TOKEN'
        >>> mappings.get_env_var("AUTHORIZATION")
        'AUTH_TOKEN'
        >>> mappings.get_env_var("x-api-key")
        'API_KEY'
        >>> mappings.get_env_var("unknown") is None
        True
        >>> list(mappings)
        [('authorization', 'AUTH_TOKEN'), ('x-api-key', 'API_KEY')]
    """

    def __init__(self, header_mappings: Dict[str, str]):
        """Initialize with header-to-env-var mappings.

        Args:
            header_mappings: Mapping of header names to environment variable names
        """
        # Store with lowercase keys for O(1) case-insensitive lookups
        self._mappings: Dict[str, str] = {k.lower(): v for k, v in header_mappings.items()}

    def get_env_var(self, header_name: str) -> str | None:
        """Get environment variable name for a header (case-insensitive).

        Args:
            header_name: HTTP header name (any case)

        Returns:
            Environment variable name or None if not mapped
        """
        return self._mappings.get(header_name.lower())

    def __iter__(self):
        """Iterate over (lowercase_header, env_var) pairs.

        Returns:
            Iterator of (header_name, env_var_name) tuples
        """
        return iter(self._mappings.items())

    def __len__(self) -> int:
        """Return number of mappings.

        Returns:
            Number of header-to-env-var mappings
        """
        return len(self._mappings)

    def values(self):
        """Return environment variable names (values of the mappings).

        Returns:
            View of environment variable names

        Examples:
            >>> mappings = NormalizedMappings({"Authorization": "AUTH", "X-Api-Key": "KEY"})
            >>> sorted(mappings.values())
            ['AUTH', 'KEY']
        """
        return self._mappings.values()

    def __bool__(self) -> bool:
        """Return True if there are any mappings.

        Returns:
            True if mappings exist, False if empty
        """
        return bool(self._mappings)


def extract_env_vars_from_headers(request_headers: Dict[str, str], header_mappings: Dict[str, str] | NormalizedMappings) -> Dict[str, str]:
    """Extract environment variables from request headers.

    Optimized for O(mappings + headers) complexity by pre-normalizing headers
    to lowercase for O(1) lookups instead of nested O(mappings × headers) scans.

    Args:
        request_headers: HTTP request headers
        header_mappings: Mapping of header names to environment variable names,
                        or a pre-normalized NormalizedMappings instance

    Returns:
        Dictionary of environment variable name -> sanitized value

    Examples:
        >>> # Extract matching headers
        >>> headers = {"Authorization": "Bearer token123", "Content-Type": "application/json"}
        >>> mappings = {"Authorization": "AUTH_TOKEN"}
        >>> extract_env_vars_from_headers(headers, mappings)
        {'AUTH_TOKEN': 'Bearer token123'}
        >>>
        >>> # Case-insensitive matching
        >>> headers = {"authorization": "Bearer token"}
        >>> mappings = {"Authorization": "AUTH"}
        >>> extract_env_vars_from_headers(headers, mappings)
        {'AUTH': 'Bearer token'}
        >>>
        >>> # No matching headers
        >>> headers = {"X-Other": "value"}
        >>> mappings = {"Authorization": "AUTH"}
        >>> extract_env_vars_from_headers(headers, mappings)
        {}
        >>>
        >>> # Empty mappings
        >>> extract_env_vars_from_headers({"Header": "value"}, {})
        {}
        >>>
        >>> # Using NormalizedMappings for repeated lookups
        >>> nm = NormalizedMappings({"Authorization": "AUTH"})
        >>> extract_env_vars_from_headers({"authorization": "token"}, nm)
        {'AUTH': 'token'}
    """
    env_vars = {}

    # Pre-normalize request headers once - O(headers)
    normalized_headers = normalize_headers(request_headers)

    # Convert to NormalizedMappings if plain dict provided
    if isinstance(header_mappings, dict):
        normalized_mappings = NormalizedMappings(header_mappings)
    else:
        normalized_mappings = header_mappings

    # O(1) lookup per mapping - O(mappings) total
    for header_lower, env_var_name in normalized_mappings:
        header_value = normalized_headers.get(header_lower)

        if header_value is not None:
            try:
                sanitized_value = sanitize_header_value(header_value)
                if sanitized_value:  # Only add non-empty values
                    env_vars[env_var_name] = sanitized_value
                    logger.debug(f"Mapped header {header_lower} to {env_var_name}")
                else:
                    logger.warning(f"Header {header_lower} value became empty after sanitization")
            except Exception as e:
                logger.warning(f"Failed to process header {header_lower}: {e}")

    return env_vars
