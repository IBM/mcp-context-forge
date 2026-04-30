# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/passthrough_headers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

HTTP Header Passthrough Utilities.
This module provides utilities for handling HTTP header passthrough functionality
in ContextForge. It enables forwarding of specific headers from incoming
client requests to backing MCP servers while preventing conflicts with
existing authentication mechanisms.

Key Features:
- Global configuration support via environment variables and database
- Per-gateway header configuration overrides
- Intelligent conflict detection with existing authentication headers
- Security-first approach with explicit allowlist handling
- Comprehensive logging for debugging and monitoring
- Header validation and sanitization

The header passthrough system follows a priority hierarchy:
1. Gateway-specific headers (highest priority)
2. Global database configuration
3. Environment variable defaults (lowest priority)

Example Usage:
    See comprehensive unit tests in tests/unit/mcpgateway/utils/test_passthrough_headers*.py
    for detailed examples of header passthrough functionality.
"""

# Standard
import logging
import re
import threading
import time
from typing import Dict, List, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import GlobalConfig

logger = logging.getLogger(__name__)

# Header name validation regex - allows letters, numbers, and hyphens
HEADER_NAME_REGEX = re.compile(r"^[A-Za-z0-9\-]+$")

# Maximum header value length (4KB)
MAX_HEADER_VALUE_LENGTH = 4096


class PassthroughHeadersError(Exception):
    """Base class for passthrough headers-related errors.

    Examples:
        >>> error = PassthroughHeadersError("Test error")
        >>> str(error)
        'Test error'
        >>> isinstance(error, Exception)
        True
    """


def sanitize_header_value(value: str, max_length: int = MAX_HEADER_VALUE_LENGTH) -> str:
    """Sanitize header value for security.

    Removes dangerous characters and enforces length limits.

    Args:
        value: Header value to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized header value

    Examples:
        Remove CRLF and trim length:
        >>> s = sanitize_header_value('val' + chr(13) + chr(10) + 'more', max_length=6)
        >>> s
        'valmor'
        >>> len(s) <= 6
        True
        >>> sanitize_header_value('  spaced  ')
        'spaced'
    """
    # Remove newlines and carriage returns to prevent header injection
    value = value.replace("\r", "").replace("\n", "")

    # Trim to max length
    value = value[:max_length]

    # Remove control characters except tab (ASCII 9) and space (ASCII 32)
    value = "".join(c for c in value if ord(c) >= 32 or c == "\t")

    return value.strip()


def validate_header_name(name: str) -> bool:
    """Validate header name against allowed pattern.

    Args:
        name: Header name to validate

    Returns:
        True if valid, False otherwise

    Examples:
        Valid names:
        >>> validate_header_name('X-Tenant-Id')
        True
        >>> validate_header_name('X123-ABC')
        True

        Invalid names:
        >>> validate_header_name('Invalid Header:Name')
        False
        >>> validate_header_name('Bad@Name')
        False
    """
    return bool(HEADER_NAME_REGEX.match(name))


def get_passthrough_headers(request_headers: Dict[str, str], base_headers: Dict[str, str], db: Session, gateway: Optional[DbGateway] = None) -> Dict[str, str]:
    """Get headers that should be passed through to the target gateway.

    This function implements the core logic for HTTP header passthrough in ContextForge.
    It determines which headers from incoming client requests should be forwarded to
    backing MCP servers based on configuration settings and security policies.

    Configuration Priority (highest to lowest):
    1. Gateway-specific passthrough_headers setting
    2. Global headers from get_passthrough_headers() based on PASSTHROUGH_HEADERS_SOURCE:
       - "db": Database wins if configured, env var DEFAULT_PASSTHROUGH_HEADERS as fallback
       - "env": Environment variable always wins, database ignored
       - "merge": Union of both sources (DB casing wins for duplicates)

    Security Features:
    - Feature flag control (disabled by default)
    - Prevents conflicts with existing base headers (e.g., Content-Type)
    - Blocks Authorization header conflicts with gateway authentication
    - Header name validation (regex pattern matching)
    - Header value sanitization (removes dangerous characters, enforces limits)
    - Logs all conflicts and skipped headers for debugging
    - Uses case-insensitive header matching for robustness
    - Special X-Upstream-Authorization handling: When gateway uses auth, clients can
      send X-Upstream-Authorization header which gets renamed to Authorization for upstream

    Args:
        request_headers (Dict[str, str]): Headers from the incoming HTTP request.
            Keys should be header names, values should be header values.
            Example: {"Authorization": "Bearer token123", "X-Tenant-Id": "acme"}
        base_headers (Dict[str, str]): Base headers that should always be included
            in the final result. These take precedence over passthrough headers.
            Example: {"Content-Type": "application/json", "User-Agent": "MCPGateway/1.0"}
        db (Session): SQLAlchemy database session for querying global configuration.
            Used to retrieve GlobalConfig.passthrough_headers setting.
        gateway (Optional[DbGateway]): Target gateway instance. If provided, uses
            gateway.passthrough_headers to override global settings. Also checks
            gateway.auth_type to prevent Authorization header conflicts.

    Returns:
        Dict[str, str]: Combined dictionary of base headers plus allowed passthrough
            headers from the request. Base headers are preserved, and passthrough
            headers are added only if they don't conflict with security policies.

    Raises:
        No exceptions are raised. Errors are logged as warnings and processing continues.
        Database connection issues may propagate from the db.query() call.

    Examples:
        Feature disabled by default (secure by default):
        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.cache.global_config_cache import global_config_cache
        >>> global_config_cache.invalidate()  # Clear cache for isolated test
        >>> with patch(__name__ + ".settings") as mock_settings:
        ...     mock_settings.enable_header_passthrough = False
        ...     mock_settings.default_passthrough_headers = ["X-Tenant-Id"]
        ...     mock_db = Mock()
        ...     mock_db.query.return_value.first.return_value = None
        ...     request_headers = {"x-tenant-id": "should-be-ignored"}
        ...     base_headers = {"Content-Type": "application/json"}
        ...     get_passthrough_headers(request_headers, base_headers, mock_db)
        {'Content-Type': 'application/json'}

        Enabled with allowlist and conflicts:
        >>> global_config_cache.invalidate()  # Clear cache for isolated test
        >>> with patch(__name__ + ".settings") as mock_settings:
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_settings.default_passthrough_headers = ["X-Tenant-Id", "Authorization"]
        ...     # Mock DB returns no global override
        ...     mock_db = Mock()
        ...     mock_db.query.return_value.first.return_value = None
        ...     # Gateway with basic auth should block Authorization passthrough
        ...     gateway = Mock()
        ...     gateway.passthrough_headers = None
        ...     gateway.auth_type = "basic"
        ...     gateway.name = "gw1"
        ...     req_headers = {"X-Tenant-Id": "acme", "Authorization": "Bearer abc"}
        ...     base = {"Content-Type": "application/json", "Authorization": "Bearer base"}
        ...     res = get_passthrough_headers(req_headers, base, mock_db, gateway)
        ...     ("X-Tenant-Id" in res) and (res["Authorization"] == "Bearer base")
        True

        See comprehensive unit tests in tests/unit/mcpgateway/utils/test_passthrough_headers*.py
        for detailed examples of enabled functionality, conflict detection, and security features.

    Note:
        Header names are matched case-insensitively but preserved in their original
        case from the allowed_headers configuration. Request header values are
        matched case-insensitively against the request_headers dictionary.
    """
    passthrough_headers = base_headers.copy()

    # Special handling for X-Upstream-Authorization header (always enabled)
    # If gateway uses auth and client wants to pass Authorization to upstream,
    # client can use X-Upstream-Authorization which gets renamed to Authorization
    request_headers_lower = {k.lower(): v for k, v in request_headers.items()} if request_headers else {}
    upstream_auth = request_headers_lower.get("x-upstream-authorization")

    if upstream_auth:
        try:
            sanitized_value = sanitize_header_value(upstream_auth)
            if sanitized_value:
                # Always rename X-Upstream-Authorization to Authorization for upstream
                # This works for both auth and no-auth gateways
                passthrough_headers["Authorization"] = sanitized_value
                logger.debug("Renamed X-Upstream-Authorization to Authorization for upstream passthrough")
        except Exception as e:
            logger.warning(f"Failed to sanitize X-Upstream-Authorization header: {e}")
    elif gateway and gateway.auth_type == "none":
        # When gateway has no auth, pass through client's Authorization if present
        client_auth = request_headers_lower.get("authorization")
        if client_auth and "authorization" not in [h.lower() for h in base_headers.keys()]:
            try:
                sanitized_value = sanitize_header_value(client_auth)
                if sanitized_value:
                    passthrough_headers["Authorization"] = sanitized_value
                    logger.debug("Passing through client Authorization header (auth_type=none)")
            except Exception as e:
                logger.warning(f"Failed to sanitize Authorization header: {e}")

    # Early return if header passthrough feature is disabled
    if not settings.enable_header_passthrough:
        logger.debug("Header passthrough is disabled via ENABLE_HEADER_PASSTHROUGH flag")
        return passthrough_headers

    if settings.enable_overwrite_base_headers:
        logger.debug("Overwriting base headers is enabled via ENABLE_OVERWRITE_BASE_HEADERS flag")

    # Get global passthrough headers from in-memory cache (Issue #1715)
    # This eliminates redundant DB queries for static configuration
    allowed_headers = global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers)

    # Gateway specific headers override global config
    if gateway:
        if gateway.passthrough_headers is not None:
            allowed_headers = gateway.passthrough_headers

    # Create case-insensitive lookup for request headers
    request_headers_lower = {k.lower(): v for k, v in request_headers.items()} if request_headers else {}

    # Get auth headers to check for conflicts
    base_headers_keys = {key.lower(): key for key in passthrough_headers.keys()}

    # Copy allowed headers from request
    if request_headers_lower and allowed_headers:
        for header_name in allowed_headers:
            # Validate header name
            if not validate_header_name(header_name):
                logger.warning(f"Invalid header name '{header_name}' - skipping (must match pattern: {HEADER_NAME_REGEX.pattern})")
                continue

            header_lower = header_name.lower()
            header_value = request_headers_lower.get(header_lower)

            if header_value:
                # Sanitize header value
                try:
                    sanitized_value = sanitize_header_value(header_value)
                    if not sanitized_value:
                        logger.warning(f"Header {header_name} value became empty after sanitization - skipping")
                        continue
                except Exception as e:
                    logger.warning(f"Failed to sanitize header {header_name}: {e} - skipping")
                    continue

                # Skip if header would conflict with existing auth headers
                if header_lower in base_headers_keys and not settings.enable_overwrite_base_headers:
                    logger.warning(f"Skipping {header_name} header passthrough as it conflicts with pre-defined headers")
                    continue

                # Skip if header would conflict with gateway auth
                if gateway:
                    if gateway.auth_type == "basic" and header_lower == "authorization":
                        logger.warning(f"Skipping Authorization header passthrough due to basic auth configuration on gateway {gateway.name}")
                        continue
                    if gateway.auth_type == "bearer" and header_lower == "authorization":
                        logger.warning(f"Skipping Authorization header passthrough due to bearer auth configuration on gateway {gateway.name}")
                        continue

                # Use original header name casing from configuration, sanitized value from request
                passthrough_headers[header_name] = sanitized_value
                logger.debug(f"Added passthrough header: {header_name}")
            else:
                logger.debug(f"Header {header_name} not found in request headers, skipping passthrough")

    logger.debug(f"Final passthrough headers: {list(passthrough_headers.keys())}")
    return passthrough_headers


def compute_passthrough_headers_cached(
    request_headers: Dict[str, str],
    base_headers: Dict[str, str],
    allowed_headers: List[str],
    gateway_auth_type: Optional[str] = None,
    gateway_passthrough_headers: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Compute passthrough headers without database query.

    Use this when GlobalConfig has already been fetched and cached, to avoid
    repeated database queries during high-frequency operations like tool invocation.

    This function implements the same header passthrough logic as get_passthrough_headers()
    but accepts pre-fetched configuration values instead of querying the database.

    Args:
        request_headers: Headers from the incoming HTTP request.
        base_headers: Base headers that should always be included (auth, content-type, etc.).
        allowed_headers: List of header names allowed to pass through (from GlobalConfig).
        gateway_auth_type: The gateway's auth_type (basic, bearer, oauth, none) if applicable.
        gateway_passthrough_headers: Gateway-specific passthrough headers override.

    Returns:
        Combined dictionary of base headers plus allowed passthrough headers.

    Examples:
        >>> from unittest.mock import patch
        >>> from mcpgateway.utils.passthrough_headers import compute_passthrough_headers_cached
        >>> request = {"X-Tenant-Id": "acme", "Authorization": "secret"}
        >>> base = {"Content-Type": "application/json"}
        >>> allowed = ["X-Tenant-Id"]
        >>> with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_settings.enable_overwrite_base_headers = False
        ...     result = compute_passthrough_headers_cached(request, base, allowed, gateway_auth_type=None)
        >>> "X-Tenant-Id" in result
        True
        >>> result.get("Authorization") is None  # Not in allowed list
        True
    """
    passthrough_headers = base_headers.copy()

    # Special handling for X-Upstream-Authorization header (always enabled)
    request_headers_lower = {k.lower(): v for k, v in request_headers.items()} if request_headers else {}
    upstream_auth = request_headers_lower.get("x-upstream-authorization")

    if upstream_auth:
        try:
            sanitized_value = sanitize_header_value(upstream_auth)
            if sanitized_value:
                passthrough_headers["Authorization"] = sanitized_value
                logger.debug("Renamed X-Upstream-Authorization to Authorization for upstream passthrough")
        except Exception as e:
            logger.warning(f"Failed to sanitize X-Upstream-Authorization header: {e}")
    elif gateway_auth_type == "none":
        # When gateway has no auth, pass through client's Authorization if present
        client_auth = request_headers_lower.get("authorization")
        if client_auth and "authorization" not in [h.lower() for h in base_headers.keys()]:
            try:
                sanitized_value = sanitize_header_value(client_auth)
                if sanitized_value:
                    passthrough_headers["Authorization"] = sanitized_value
                    logger.debug("Passing through client Authorization header (auth_type=none)")
            except Exception as e:
                logger.warning(f"Failed to sanitize Authorization header: {e}")

    # Early return if header passthrough feature is disabled
    if not settings.enable_header_passthrough:
        logger.debug("Header passthrough is disabled via ENABLE_HEADER_PASSTHROUGH flag")
        return passthrough_headers

    # Use gateway-specific headers if provided, otherwise use global allowed_headers
    effective_allowed = gateway_passthrough_headers if gateway_passthrough_headers is not None else allowed_headers

    # Create case-insensitive lookup for base headers
    base_headers_keys = {key.lower(): key for key in passthrough_headers.keys()}

    # Copy allowed headers from request
    if request_headers_lower and effective_allowed:
        for header_name in effective_allowed:
            # Validate header name
            if not validate_header_name(header_name):
                logger.warning(f"Invalid header name '{header_name}' - skipping (must match pattern: {HEADER_NAME_REGEX.pattern})")
                continue

            header_lower = header_name.lower()
            header_value = request_headers_lower.get(header_lower)

            if header_value:
                # Sanitize header value
                try:
                    sanitized_value = sanitize_header_value(header_value)
                    if not sanitized_value:
                        logger.warning(f"Header {header_name} value became empty after sanitization - skipping")
                        continue
                except Exception as e:
                    logger.warning(f"Failed to sanitize header {header_name}: {e} - skipping")
                    continue

                # Skip if header would conflict with existing auth headers
                if header_lower in base_headers_keys and not settings.enable_overwrite_base_headers:
                    logger.warning(f"Skipping {header_name} header passthrough as it conflicts with pre-defined headers")
                    continue

                # Skip if header would conflict with gateway auth
                if gateway_auth_type in ("basic", "bearer") and header_lower == "authorization":
                    logger.warning(f"Skipping Authorization header passthrough due to {gateway_auth_type} auth configuration")
                    continue

                # Use original header name casing from configuration, sanitized value from request
                passthrough_headers[header_name] = sanitized_value
                logger.debug(f"Added passthrough header: {header_name}")
            else:
                logger.debug(f"Header {header_name} not found in request headers, skipping passthrough")

    logger.debug(f"Final passthrough headers (cached): {list(passthrough_headers.keys())}")
    return passthrough_headers


async def set_global_passthrough_headers(db: Session) -> None:
    """Set global passthrough headers in the database if not already configured.

    This function checks if the global passthrough headers are already set in the
    GlobalConfig table. If not, it initializes them with the default headers from
    settings.default_passthrough_headers.

    When PASSTHROUGH_HEADERS_SOURCE=env, this function skips database writes entirely
    since the database configuration is ignored in that mode.

    Args:
        db (Session): SQLAlchemy database session for querying and updating GlobalConfig.

    Raises:
        PassthroughHeadersError: If unable to update passthrough headers in the database.

    Examples:
        Successful insert of default headers:
        >>> import pytest
        >>> from unittest.mock import Mock, patch
        >>> @pytest.mark.asyncio
        ... @patch("mcpgateway.utils.passthrough_headers.settings")
        ... async def test_default_headers(mock_settings):
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_settings.passthrough_headers_source = "db"
        ...     mock_settings.default_passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]
        ...     mock_db = Mock()
        ...     mock_db.query.return_value.first.return_value = None
        ...     await set_global_passthrough_headers(mock_db)
        ...     mock_db.add.assert_called_once()
        ...     mock_db.commit.assert_called_once()

        Database write failure:
        >>> import pytest
        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.utils.passthrough_headers import PassthroughHeadersError
        >>> @pytest.mark.asyncio
        ... @patch("mcpgateway.utils.passthrough_headers.settings")
        ... async def test_db_write_failure(mock_settings):
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_settings.passthrough_headers_source = "db"
        ...     mock_db = Mock()
        ...     mock_db.query.return_value.first.return_value = None
        ...     mock_db.commit.side_effect = Exception("DB write failed")
        ...     with pytest.raises(PassthroughHeadersError):
        ...         await set_global_passthrough_headers(mock_db)
        ...     mock_db.rollback.assert_called_once()

        Config already exists (no DB write):
        >>> import pytest
        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.common.models import GlobalConfig
        >>> @pytest.mark.asyncio
        ... @patch("mcpgateway.utils.passthrough_headers.settings")
        ... async def test_existing_config(mock_settings):
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_settings.passthrough_headers_source = "db"
        ...     mock_db = Mock()
        ...     existing = Mock(spec=GlobalConfig)
        ...     existing.passthrough_headers = ["X-Tenant-ID", "Authorization"]
        ...     mock_db.query.return_value.first.return_value = existing
        ...     await set_global_passthrough_headers(mock_db)
        ...     mock_db.add.assert_not_called()
        ...     mock_db.commit.assert_not_called()
        ...     assert existing.passthrough_headers == ["X-Tenant-ID", "Authorization"]

        Env mode skips DB entirely:
        >>> import pytest
        >>> from unittest.mock import Mock, patch
        >>> @pytest.mark.asyncio
        ... @patch("mcpgateway.utils.passthrough_headers.settings")
        ... async def test_env_mode_skips_db(mock_settings):
        ...     mock_settings.passthrough_headers_source = "env"
        ...     mock_db = Mock()
        ...     await set_global_passthrough_headers(mock_db)
        ...     mock_db.query.assert_not_called()
        ...     mock_db.add.assert_not_called()

    Note:
        This function is typically called during application startup to ensure
        global configuration is in place before any gateway operations.
    """
    # When source is "env", skip DB operations entirely - env vars always win
    if settings.passthrough_headers_source == "env":
        logger.debug("Passthrough headers source=env: skipping database initialization (env vars always used)")
        return

    # Query DB directly here (not cache) because we need to check if config exists
    # to decide whether to create it
    global_config = db.query(GlobalConfig).first()

    if not global_config:
        config_headers = settings.default_passthrough_headers
        allowed_headers = []
        if config_headers:
            for header_name in config_headers:
                # Validate header name
                if not validate_header_name(header_name):
                    logger.warning(f"Invalid header name '{header_name}' - skipping (must match pattern: {HEADER_NAME_REGEX.pattern})")
                    continue

                allowed_headers.append(header_name)
        try:
            db.add(GlobalConfig(passthrough_headers=allowed_headers))
            db.commit()
            # Invalidate both global and loopback caches so next read picks up new config (Issue #1715, #3640)
            invalidate_passthrough_header_caches()
        except Exception as e:
            db.rollback()
            raise PassthroughHeadersError(f"Failed to update passthrough headers: {str(e)}")


# Headers that must never be forwarded via loopback — they are set by the caller
# or are gateway-internal routing/loop-prevention headers.
# IMPORTANT: keep this set in sync with internal headers set at merge sites
# (session_registry generate_response, WebSocket relay, Streamable HTTP affinity).
# httpx concatenates case-different duplicate keys rather than picking one, so an
# omission here could silently corrupt the internal header value.
_LOOPBACK_SKIP_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "connection",
        "content-type",
        "content-length",
        "host",
        "keep-alive",
        "mcp-session-id",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "x-mcp-session-id",
        "x-forwarded-internally",
    }
)


def _loopback_skip_set() -> frozenset[str]:
    """Return the full set of headers to skip in loopback forwarding.

    Extends ``_LOOPBACK_SKIP_HEADERS`` with the configurable
    ``proxy_user_header`` (default ``X-Authenticated-User``) so that
    passthrough headers can never overwrite the gateway-internal proxy
    user identity — even if that header name is added to the passthrough
    allowlist by mistake.

    Returns:
        frozenset[str]: Header names to skip during loopback forwarding.
    """
    proxy = settings.proxy_user_header.lower()
    if proxy in _LOOPBACK_SKIP_HEADERS:
        return _LOOPBACK_SKIP_HEADERS
    return _LOOPBACK_SKIP_HEADERS | {proxy}


class _LoopbackAllowlistCache:
    """TTL cache for the merged passthrough header allowlist (global + all gateways).

    Avoids a full Gateway table scan on every loopback call by caching the union
    of global and gateway-specific passthrough headers with the same 60 s TTL used
    by global_config_cache.
    """

    def __init__(self, ttl_seconds: float = 60.0):
        self._cache: Optional[frozenset[str]] = None
        self._populated: bool = False
        self._expiry: float = 0
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def get(self, db: Session) -> frozenset[str]:
        """Return the cached merged allowlist, refreshing from DB when expired.

        Falls back to the last known good value during transient DB failures to
        avoid a thundering-herd of failing queries on every loopback call.

        Args:
            db: SQLAlchemy database session for querying gateway configurations.

        Returns:
            Frozen set of allowed passthrough header names (union of global and
            all gateway-specific configurations).

        Raises:
            Exception: Re-raised from DB query when no stale cache is available
                to fall back to (first call after startup with a broken DB).
        """
        now = time.time()
        # CPython GIL ensures atomic attribute reads on the fast path.
        if now < self._expiry and self._populated:
            return self._cache  # type: ignore[return-value]  # _populated guarantees non-None
        with self._lock:
            if now < self._expiry and self._populated:
                return self._cache  # type: ignore[return-value]  # _populated guarantees non-None
            try:
                merged: set[str] = set(global_config_cache.get_passthrough_headers(db, settings.default_passthrough_headers or []) or [])
                gw_rows = db.query(DbGateway.passthrough_headers).filter(DbGateway.passthrough_headers.isnot(None)).all()
                for (gw_headers,) in gw_rows:
                    if gw_headers:
                        merged.update(gw_headers)
                self._cache = frozenset(merged)
                self._populated = True
                self._expiry = now + self._ttl
            except Exception:
                logger.warning("Failed to refresh loopback allowlist cache from DB; using stale value if available", exc_info=True)
                if self._populated and self._cache is not None:
                    # Extend TTL briefly to avoid hammering DB on every request
                    self._expiry = now + min(self._ttl, 10.0)
                else:
                    raise
            return self._cache  # type: ignore[return-value]  # _populated guarantees non-None

    def invalidate(self) -> None:
        """Force a refresh on next access."""
        with self._lock:
            self._populated = False
            self._expiry = 0


_loopback_allowlist_cache = _LoopbackAllowlistCache()


def invalidate_passthrough_header_caches() -> None:
    """Invalidate both the global config cache and the loopback allowlist cache.

    Call this after any mutation to passthrough header configuration (global or
    per-gateway) so that loopback transports (SSE, WebSocket, Streamable HTTP)
    converge immediately with direct /rpc rather than waiting for TTL expiry.
    """
    global_config_cache.invalidate()
    _loopback_allowlist_cache.invalidate()
    logger.debug("Invalidated global_config_cache and _loopback_allowlist_cache for passthrough headers")


def filter_loopback_skip_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of *headers* with gateway-internal loopback headers removed.

    Defense-in-depth filter applied at loopback merge sites (SSE generate_response,
    WebSocket relay) to ensure passthrough headers can never override the gateway's
    internal JWT, content-type, proxy-user, or session/routing headers — even if
    ``extract_headers_for_loopback`` is bypassed or its skip-list is out of sync.

    Values are re-sanitized via ``sanitize_header_value()`` so this function is
    safe to call on input that has not been pre-sanitized.

    Args:
        headers: Candidate passthrough headers to filter.

    Returns:
        New dictionary containing only headers whose lowercased names are
        **not** in the skip set (``_LOOPBACK_SKIP_HEADERS`` plus the
        configurable ``proxy_user_header``), with values sanitized.
    """
    skip = _loopback_skip_set()
    filtered: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in skip:
            continue
        try:
            filtered[k] = sanitize_header_value(v)
        except Exception:
            logger.warning("Dropped unsafe header %s during loopback filter", k, exc_info=True)
    return filtered


def extract_headers_for_loopback(request_headers: Dict[str, str]) -> Dict[str, str]:
    """Extract passthrough-relevant headers to forward in internal loopback /rpc calls.

    SSE and WebSocket transports make internal loopback HTTP calls to /rpc. Client
    passthrough headers (like X-Upstream-Authorization) must be included in those
    loopback requests so that /rpc can forward them to upstream MCP servers via
    get_passthrough_headers().

    Always extracts:
    - x-upstream-authorization (always enabled per design, renamed to Authorization upstream)

    When ENABLE_HEADER_PASSTHROUGH is True, also extracts headers matching the
    cached union of:
    - The global allowlist resolved via global_config_cache.get_passthrough_headers()
      (respects PASSTHROUGH_HEADERS_SOURCE priority: env, db, merge)
    - All gateway-specific passthrough_headers configured on any Gateway

    The merged allowlist is cached with a 60 s TTL (matching global_config_cache)
    so the gateway table scan only runs once per TTL window, not per request.

    All extracted values are sanitized via sanitize_header_value() for defense-in-depth,
    even though the /rpc endpoint re-sanitizes via get_passthrough_headers().

    Headers in _LOOPBACK_SKIP_HEADERS (authorization, content-type, and gateway-internal
    routing/session headers) are never returned, regardless of configuration.

    Args:
        request_headers: Headers from the incoming client HTTP request or WebSocket
            handshake. Keys are header names, values are header values.

    Returns:
        Dictionary of headers to merge into the loopback /rpc request.
        Does not include authorization, content-type, or gateway-internal headers
        (those are handled separately by the caller).

    Examples:
        X-Upstream-Authorization is always extracted:
        >>> from unittest.mock import patch
        >>> with patch("mcpgateway.utils.passthrough_headers.settings") as s:
        ...     s.enable_header_passthrough = False
        ...     s.default_passthrough_headers = []
        ...     extract_headers_for_loopback({"X-Upstream-Authorization": "Bearer tok"})
        {'x-upstream-authorization': 'Bearer tok'}

        Empty when no relevant headers present:
        >>> from unittest.mock import patch
        >>> with patch("mcpgateway.utils.passthrough_headers.settings") as s:
        ...     s.enable_header_passthrough = False
        ...     s.default_passthrough_headers = []
        ...     extract_headers_for_loopback({"Accept": "text/html"})
        {}
    """
    forwarded: Dict[str, str] = {}
    if not request_headers:
        return forwarded

    headers_lower = {k.lower(): v for k, v in request_headers.items()}

    # Always forward x-upstream-authorization (always-enabled passthrough header).
    # On sanitization failure, drop the header rather than forwarding an unsanitized value —
    # sanitization prevents CRLF/control-character injection, so bypassing it is unsafe.
    upstream_auth = headers_lower.get("x-upstream-authorization")
    if upstream_auth:
        try:
            forwarded["x-upstream-authorization"] = sanitize_header_value(upstream_auth)
        except Exception:
            logger.warning("Failed to sanitize x-upstream-authorization; dropping header for safety", exc_info=True)

    # When passthrough feature is enabled, also forward configured allowlist headers.
    # The merged allowlist (global + all gateways) is cached with a 60 s TTL.
    try:
        if settings.enable_header_passthrough:
            # First-Party
            from mcpgateway.db import SessionLocal  # pylint: disable=import-outside-toplevel

            with SessionLocal() as db:
                allowed = _loopback_allowlist_cache.get(db)
            skip = _loopback_skip_set()
            for header_name in allowed:
                header_lower = header_name.lower()
                if header_lower in skip:
                    continue
                if header_lower in headers_lower:
                    try:
                        forwarded[header_lower] = sanitize_header_value(headers_lower[header_lower])
                    except Exception:
                        logger.warning("Failed to sanitize passthrough header %s; skipping", header_lower, exc_info=True)
    except Exception:
        logger.warning("Failed to read passthrough header allowlist; forwarding only previously extracted headers", exc_info=True)

    if forwarded:
        logger.debug("Extracted %d passthrough header(s) for loopback: %s", len(forwarded), list(forwarded.keys()))

    return forwarded


def safe_extract_headers_for_loopback(request_headers: Dict[str, str], transport_name: str = "transport") -> Dict[str, str]:
    """Safely extract passthrough headers, returning ``{}`` on failure.

    Wraps :func:`extract_headers_for_loopback` so that SSE / WebSocket setup
    is never blocked by passthrough configuration issues.  ``ImportError``
    propagates (broken deployment should fail loudly).

    Args:
        request_headers: Incoming HTTP headers to extract from.
        transport_name: Label for warning logs on failure.

    Returns:
        Dict[str, str]: Extracted passthrough headers, or empty dict on error.
    """
    try:
        return extract_headers_for_loopback(request_headers)
    except Exception:
        logger.warning("Failed to extract passthrough headers for %s; upstream auth may fail", transport_name, exc_info=True)
        return {}


def safe_extract_and_filter_for_loopback(request_headers: Dict[str, str]) -> Dict[str, str]:
    """Extract *and* filter passthrough headers, returning ``{}`` on failure.

    Combines :func:`extract_headers_for_loopback` and
    :func:`filter_loopback_skip_headers` with error handling so that
    Streamable HTTP affinity loopback calls degrade gracefully.

    Args:
        request_headers: Incoming HTTP headers to extract and filter.

    Returns:
        Dict[str, str]: Filtered passthrough headers, or empty dict on error.
    """
    try:
        return filter_loopback_skip_headers(extract_headers_for_loopback(request_headers))
    except Exception:
        logger.warning("Failed to extract passthrough headers for loopback; upstream auth may fail", exc_info=True)
        return {}
