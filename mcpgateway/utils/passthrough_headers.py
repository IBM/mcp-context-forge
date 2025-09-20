# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/passthrough_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

HTTP Header Passthrough Utilities.
This module provides utilities for handling HTTP header passthrough functionality
in the MCP Gateway. It enables forwarding of specific headers from incoming
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
from typing import Dict, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
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

    This function implements the core logic for HTTP header passthrough in the MCP Gateway.
    It determines which headers from incoming client requests should be forwarded to
    backing MCP servers based on configuration settings and security policies.

    Configuration Priority (highest to lowest):
    1. Gateway-specific passthrough_headers setting
    2. Global database configuration (GlobalConfig.passthrough_headers)
    3. Environment variable DEFAULT_PASSTHROUGH_HEADERS

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
    if gateway and gateway.auth_type in ["basic", "bearer", "oauth"]:
        request_headers_lower = {k.lower(): v for k, v in request_headers.items()} if request_headers else {}
        upstream_auth = request_headers_lower.get("x-upstream-authorization")
        if upstream_auth:
            try:
                sanitized_value = sanitize_header_value(upstream_auth)
                if sanitized_value:
                    # Rename X-Upstream-Authorization to Authorization for upstream
                    passthrough_headers["Authorization"] = sanitized_value
                    logger.debug("Renamed X-Upstream-Authorization to Authorization for upstream passthrough")
            except Exception as e:
                logger.warning(f"Failed to sanitize X-Upstream-Authorization header: {e}")

    # Early return if header passthrough feature is disabled
    if not settings.enable_header_passthrough:
        logger.debug("Header passthrough is disabled via ENABLE_HEADER_PASSTHROUGH flag")
        return passthrough_headers

    # Get global passthrough headers first
    global_config = db.query(GlobalConfig).first()
    allowed_headers = global_config.passthrough_headers if global_config else settings.default_passthrough_headers

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
                if header_lower in base_headers_keys:
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


async def set_global_passthrough_headers(db: Session) -> None:
    """Set global passthrough headers in the database if not already configured.

    This function checks if the global passthrough headers are already set in the
    GlobalConfig table. If not, it initializes them with the default headers from
    settings.default_passthrough_headers.

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
        ...     mock_db = Mock()
        ...     mock_db.query.return_value.first.return_value = None
        ...     mock_db.commit.side_effect = Exception("DB write failed")
        ...     with pytest.raises(PassthroughHeadersError):
        ...         await set_global_passthrough_headers(mock_db)
        ...     mock_db.rollback.assert_called_once()

        Config already exists (no DB write):
        >>> import pytest
        >>> from unittest.mock import Mock, patch
        >>> from mcpgateway.models import GlobalConfig
        >>> @pytest.mark.asyncio
        ... @patch("mcpgateway.utils.passthrough_headers.settings")
        ... async def test_existing_config(mock_settings):
        ...     mock_settings.enable_header_passthrough = True
        ...     mock_db = Mock()
        ...     existing = Mock(spec=GlobalConfig)
        ...     existing.passthrough_headers = ["X-Tenant-ID", "Authorization"]
        ...     mock_db.query.return_value.first.return_value = existing
        ...     await set_global_passthrough_headers(mock_db)
        ...     mock_db.add.assert_not_called()
        ...     mock_db.commit.assert_not_called()
        ...     assert existing.passthrough_headers == ["X-Tenant-ID", "Authorization"]

    Note:
        This function is typically called during application startup to ensure
        global configuration is in place before any gateway operations.
    """
    global_config = db.query(GlobalConfig).first()

    if not global_config:
        config_headers = settings.default_passthrough_headers
        if config_headers:
            allowed_headers = []
            for header_name in config_headers:
                # Validate header name
                if not validate_header_name(header_name):
                    logger.warning(f"Invalid header name '{header_name}' - skipping (must match pattern: {HEADER_NAME_REGEX.pattern})")
                    continue

                allowed_headers.append(header_name)
        try:
            db.add(GlobalConfig(passthrough_headers=allowed_headers))
            db.commit()
        except Exception as e:
            db.rollback()
            raise PassthroughHeadersError(f"Failed to update passthrough headers: {str(e)}")
