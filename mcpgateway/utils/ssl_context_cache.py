# -*- coding: utf-8 -*-
"""SSL context caching utilities for ContextForge services.

This module provides caching for SSL contexts to avoid repeatedly creating
them for the same CA certificates, improving performance for services that
make many SSL connections.
"""

# Standard
import hashlib
import ssl

# Cache for SSL contexts keyed by CA certificate hash
_ssl_context_cache: dict[str, ssl.SSLContext] = {}


def get_cached_ssl_context(ca_certificate: str) -> ssl.SSLContext:
    """Get or create cached SSL context for a CA certificate.

    Args:
        ca_certificate: CA certificate in PEM format (str or bytes)

    Returns:
        ssl.SSLContext: Configured SSL context

    Examples:
        The actual `ssl.SSLContext.load_verify_locations()` call requires valid PEM
        data; in doctests we mock it to focus on caching behavior.

        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache, get_cached_ssl_context
        >>> clear_ssl_context_cache()
        >>> with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ...     ctx = Mock()
        ...     mock_create.return_value = ctx
        ...     a = get_cached_ssl_context("CERTDATA")
        ...     b = get_cached_ssl_context(b"CERTDATA")  # same bytes => same cache entry
        ...     (a is ctx, b is ctx, mock_create.call_count)
        (True, True, 1)

    Note:
        The function handles bytes, str, and other types (for test mocks).
        SSL contexts are cached by the SHA256 hash of the certificate to
        avoid repeated expensive SSL setup operations.
    """
    # Handle bytes, string, or other types (e.g., MagicMock in tests)
    if isinstance(ca_certificate, bytes):
        cert_bytes = ca_certificate
    elif isinstance(ca_certificate, str):
        cert_bytes = ca_certificate.encode()
    else:
        # For non-string/non-bytes (e.g., MagicMock in tests), convert to string first
        cert_bytes = str(ca_certificate).encode()

    cert_hash = hashlib.sha256(cert_bytes).hexdigest()

    if cert_hash in _ssl_context_cache:
        return _ssl_context_cache[cert_hash]

    # Create new SSL context
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=ca_certificate)

    # Cache it (limit cache size)
    if len(_ssl_context_cache) > 100:
        _ssl_context_cache.clear()
    _ssl_context_cache[cert_hash] = ctx

    return ctx


def clear_ssl_context_cache() -> None:
    """Clear the SSL context cache.

    Call this function:
    - In test fixtures to ensure test isolation
    - After CA certificate rotation
    - When memory pressure requires cache cleanup

    Examples:
        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.utils.ssl_context_cache import clear_ssl_context_cache, get_cached_ssl_context
        >>> with patch("mcpgateway.utils.ssl_context_cache.ssl.create_default_context") as mock_create:
        ...     mock_create.return_value = Mock()
        ...     _ = get_cached_ssl_context("CERTDATA")
        ...     clear_ssl_context_cache()
        ...     _ = get_cached_ssl_context("CERTDATA")
        ...     mock_create.call_count
        2
    """
    _ssl_context_cache.clear()
