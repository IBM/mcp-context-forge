# -*- coding: utf-8 -*-
"""SSL context caching utilities for ContextForge services.

This module provides caching for SSL contexts to avoid repeatedly creating
them for the same CA certificates, improving performance for services that
make many SSL connections.
"""

# Standard
from datetime import datetime, timedelta
import hashlib
import logging
import os
import ssl
import tempfile

logger = logging.getLogger(__name__)

# Cache for SSL contexts keyed by SSL parameter hash
_ssl_context_cache: dict[str, ssl.SSLContext] = {}
_ssl_context_cache_timestamps: dict[str, datetime] = {}

_SSL_CONTEXT_CACHE_MAX_SIZE = int(os.getenv("SSL_CONTEXT_CACHE_MAX_SIZE", "100"))
_SSL_CONTEXT_CACHE_TTL = os.getenv("SSL_CONTEXT_CACHE_TTL")
if _SSL_CONTEXT_CACHE_TTL is not None and _SSL_CONTEXT_CACHE_TTL.strip() != "":
    try:
        _SSL_CONTEXT_CACHE_TTL = int(_SSL_CONTEXT_CACHE_TTL)
    except ValueError:
        raise ValueError("SSL_CONTEXT_CACHE_TTL must be an integer number of seconds")
else:
    _SSL_CONTEXT_CACHE_TTL = None


def _is_expired(cache_key: str) -> bool:
    """Check if a cached SSL context entry has expired based on TTL.

    Args:
        cache_key: The cache key to check for expiration.

    Returns:
        True if the entry has expired and should be refreshed, False otherwise.
    """
    if _SSL_CONTEXT_CACHE_TTL is None:
        return False
    created_at = _ssl_context_cache_timestamps.get(cache_key)
    if created_at is None:
        return False

    return datetime.now() - created_at > timedelta(seconds=_SSL_CONTEXT_CACHE_TTL)


def _is_pem(value: str) -> bool:
    """Check if a string looks like inline PEM content rather than a file path.

    Args:
        value: String to check (file path or PEM content).

    Returns:
        True if the string starts with a PEM header.
    """
    return value.lstrip().startswith("-----BEGIN ")


def _load_client_cert_chain(ctx: ssl.SSLContext, client_cert: str, client_key: str) -> None:
    """Load client cert/key into an SSL context, handling both file paths and PEM strings.

    ``ssl.SSLContext.load_cert_chain`` only accepts file paths.  When the
    values are inline PEM content (stored in the database), we write them
    to secure temporary files and load from there.

    Args:
        ctx: SSL context to load the client certificate chain into.
        client_cert: Client certificate as a file path or inline PEM string.
        client_key: Client private key as a file path or inline PEM string.
    """
    cert_is_pem = _is_pem(client_cert)
    key_is_pem = _is_pem(client_key)

    if not cert_is_pem and not key_is_pem:
        # Both are file paths — use directly
        ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
        return

    # At least one value is inline PEM — write temp files
    cert_tmp = key_tmp = None
    try:
        if cert_is_pem:
            cert_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False, encoding="utf-8")
            cert_tmp.write(client_cert)
            cert_tmp.close()
            cert_path = cert_tmp.name
        else:
            cert_path = client_cert

        if key_is_pem:
            key_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False, encoding="utf-8")
            key_tmp.write(client_key)
            key_tmp.close()
            key_path = key_tmp.name
        else:
            key_path = client_key

        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    finally:
        # Remove temp files immediately after loading
        if cert_tmp is not None:
            try:
                os.unlink(cert_tmp.name)
            except OSError:
                logger.debug("Failed to remove temp cert file %s", cert_tmp.name)
        if key_tmp is not None:
            try:
                os.unlink(key_tmp.name)
            except OSError:
                logger.debug("Failed to remove temp key file %s", key_tmp.name)


def get_cached_ssl_context(
    ca_certificate: str,
    client_cert: str | None = None,
    client_key: str | None = None,
) -> ssl.SSLContext:
    """Get or create cached SSL context for a CA certificate.

    Args:
        ca_certificate: CA certificate in PEM format (str or bytes)
        client_cert: Optional client cert path or PEM for mTLS
        client_key: Optional client key path or PEM for mTLS

    Returns:
        ssl.SSLContext: Configured SSL context

    Raises:
        ValueError: If only one of client_cert/client_key is provided.

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
    # Ensure CA certificate is normalized to bytes for hash calculation
    if isinstance(ca_certificate, bytes):
        ca_cert_bytes = ca_certificate
    elif isinstance(ca_certificate, str):
        ca_cert_bytes = ca_certificate.encode()
    else:
        ca_cert_bytes = str(ca_certificate).encode()

    # Client cert/key may be either path-like content or inlined PEM string.
    client_cert_value = client_cert or ""
    client_key_value = client_key or ""

    # Build stable cache key incrementally (avoids delimiter collisions).
    key_hash = hashlib.sha256()
    key_hash.update(b"ca_cert:")
    key_hash.update(ca_cert_bytes)
    key_hash.update(b"|client_cert:")
    key_hash.update(client_cert_value.encode())
    key_hash.update(b"|client_key:")
    key_hash.update(client_key_value.encode())

    cache_key = key_hash.hexdigest()

    if cache_key in _ssl_context_cache and not _is_expired(cache_key):
        return _ssl_context_cache[cache_key]

    # If expired, clear this entry so it is refreshed below
    if cache_key in _ssl_context_cache:
        _ssl_context_cache.pop(cache_key, None)
        _ssl_context_cache_timestamps.pop(cache_key, None)

    # Create new SSL context and configure CA cert
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=ca_certificate)

    # Validate mTLS: require both or neither
    if bool(client_cert) != bool(client_key):
        raise ValueError("mTLS requires both client_cert and client_key; got only one")

    # Load client certificates for mTLS when provided
    if client_cert and client_key:
        _load_client_cert_chain(ctx, client_cert, client_key)

    # Cache entry creation timestamp if TTL is enabled
    _ssl_context_cache[cache_key] = ctx
    if _SSL_CONTEXT_CACHE_TTL is not None:
        _ssl_context_cache_timestamps[cache_key] = datetime.now()

    # Evict all cache if size limit exceeded; keep this newly inserted item.
    # This avoids growing indefinitely without requiring LRU tracking.
    if len(_ssl_context_cache) > _SSL_CONTEXT_CACHE_MAX_SIZE:
        current_ctx = _ssl_context_cache.pop(cache_key)
        current_ts = _ssl_context_cache_timestamps.pop(cache_key, None)

        _ssl_context_cache.clear()
        _ssl_context_cache_timestamps.clear()

        _ssl_context_cache[cache_key] = current_ctx
        if current_ts is not None:
            _ssl_context_cache_timestamps[cache_key] = current_ts

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
    _ssl_context_cache_timestamps.clear()
