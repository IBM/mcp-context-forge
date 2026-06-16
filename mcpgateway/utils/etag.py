# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/etag.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan Catanus

ETag generation and validation utilities for RFC 6585 Phase 2 conditional requests.

This module provides utilities for generating and parsing weak ETags based on
resource ID and version number, following RFC 7232 specifications.

Weak ETags (W/"...") indicate semantic equivalence rather than byte-for-byte
identity, which is appropriate for versioned database resources.

Examples:
    >>> from mcpgateway.utils.etag import generate_etag, parse_etag, validate_etag
    >>> etag = generate_etag("abc123", 5)
    >>> etag
    'W/"abc123-5"'
    >>> parse_etag(etag)
    ('abc123', 5)
    >>> validate_etag(etag, "abc123", 5)
    True
    >>> validate_etag(etag, "abc123", 6)
    False
"""

# Standard
import hashlib
import re
from typing import Optional, Tuple

# ETag format: W/"<resource_id>-<version>"
# Weak ETag prefix per RFC 7232 Section 2.3
ETAG_PATTERN = re.compile(r'^W/"([a-zA-Z0-9_-]+)-(\d+)"$')


def generate_etag(resource_id: str, version: int) -> str:
    """Generate a weak ETag for a resource based on ID and version.

    Creates a weak ETag (W/"...") following RFC 7232 format. Weak ETags
    indicate semantic equivalence rather than byte-for-byte identity.

    Args:
        resource_id: Unique resource identifier (UUID hex, slug, etc.)
        version: Integer version number from database

    Returns:
        Weak ETag string in format W/"resource_id-version"

    Examples:
        >>> generate_etag("abc123", 1)
        'W/"abc123-1"'
        >>> generate_etag("server-uuid-hex", 42)
        'W/"server-uuid-hex-42"'
    """
    # Sanitize resource_id to prevent ETag injection
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", resource_id)
    return f'W/"{safe_id}-{version}"'


def parse_etag(etag_header: str) -> Optional[Tuple[str, int]]:
    """Parse an ETag header into resource ID and version components.

    Validates and extracts the resource ID and version from a weak ETag.
    Returns None if the ETag format is invalid.

    Args:
        etag_header: ETag header value (e.g., W/"abc123-5")

    Returns:
        Tuple of (resource_id, version) if valid, None otherwise

    Examples:
        >>> parse_etag('W/"abc123-5"')
        ('abc123', 5)
        >>> parse_etag('invalid-etag')
        >>> parse_etag('W/"malformed')
    """
    if not etag_header:
        return None

    match = ETAG_PATTERN.match(etag_header.strip())
    if not match:
        return None

    try:
        resource_id = match.group(1)
        version = int(match.group(2))
        return (resource_id, version)
    except (ValueError, IndexError):
        return None


def validate_etag(etag_header: str, resource_id: str, current_version: int) -> bool:
    """Validate that an ETag matches the current resource state.

    Checks if the provided ETag corresponds to the current resource version.
    Used for If-Match conditional request validation.

    Args:
        etag_header: Client-provided ETag from If-Match header
        resource_id: Current resource identifier
        current_version: Current version from database

    Returns:
        True if ETag is valid and matches current state, False otherwise

    Examples:
        >>> validate_etag('W/"abc123-5"', 'abc123', 5)
        True
        >>> validate_etag('W/"abc123-5"', 'abc123', 6)
        False
        >>> validate_etag('W/"other-5"', 'abc123', 5)
        False
        >>> validate_etag('invalid', 'abc123', 5)
        False
    """
    parsed = parse_etag(etag_header)
    if not parsed:
        return False

    etag_id, etag_version = parsed
    return etag_id == resource_id and etag_version == current_version


def format_etag_header(etag: str) -> str:
    """Format an ETag for inclusion in HTTP response headers.

    This is primarily a pass-through for consistency, but ensures
    the ETag is properly formatted.

    Args:
        etag: Generated ETag string

    Returns:
        Formatted ETag ready for HTTP header

    Examples:
        >>> format_etag_header('W/"abc123-5"')
        'W/"abc123-5"'
    """
    return etag


def generate_strong_etag(content: bytes) -> str:
    """Generate a strong ETag based on content hash.

    Strong ETags indicate byte-for-byte identity. This is useful for
    static content or when precise content matching is required.

    Note: For most ContextForge resources, weak ETags (version-based)
    are preferred as they're more efficient and appropriate for
    database-backed entities.

    Args:
        content: Byte content to hash

    Returns:
        Strong ETag in format "sha256-hash"

    Examples:
        >>> generate_strong_etag(b"test content")  # doctest: +ELLIPSIS
        '"...'
    """
    content_hash = hashlib.sha256(content).hexdigest()[:16]
    return f'"{content_hash}"'


def parse_if_match_header(if_match_header: str) -> list[str]:
    """Parse If-Match header which may contain multiple ETags.

    The If-Match header can contain:
    - Single ETag: If-Match: W/"abc-1"
    - Multiple ETags: If-Match: W/"abc-1", W/"abc-2"
    - Wildcard: If-Match: * (matches any existing resource)

    Args:
        if_match_header: Raw If-Match header value

    Returns:
        List of ETag strings (empty list if invalid)

    Examples:
        >>> parse_if_match_header('W/"abc-1"')
        ['W/"abc-1"']
        >>> parse_if_match_header('W/"abc-1", W/"abc-2"')
        ['W/"abc-1"', 'W/"abc-2"']
        >>> parse_if_match_header('*')
        ['*']
    """
    if not if_match_header:
        return []

    # Handle wildcard
    if if_match_header.strip() == "*":
        return ["*"]

    # Split by comma and clean up whitespace
    etags = [etag.strip() for etag in if_match_header.split(",")]
    return [etag for etag in etags if etag]


def matches_any_etag(etags: list[str], resource_id: str, current_version: int) -> bool:
    """Check if any ETag in a list matches the current resource state.

    Used for processing If-Match headers that contain multiple ETags.

    Args:
        etags: List of ETag strings from If-Match header
        resource_id: Current resource identifier
        current_version: Current version from database

    Returns:
        True if any ETag matches or wildcard is present, False otherwise

    Examples:
        >>> matches_any_etag(['W/"abc-5"'], 'abc', 5)
        True
        >>> matches_any_etag(['W/"abc-4"', 'W/"abc-5"'], 'abc', 5)
        True
        >>> matches_any_etag(['W/"abc-4"'], 'abc', 5)
        False
        >>> matches_any_etag(['*'], 'abc', 5)
        True
    """
    # Wildcard matches any existing resource
    if "*" in etags:
        return True

    # Check if any ETag matches
    for etag in etags:
        if validate_etag(etag, resource_id, current_version):
            return True

    return False
