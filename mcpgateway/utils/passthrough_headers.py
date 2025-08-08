# -*- coding: utf-8 -*-
"""HTTP Header Passthrough Utilities.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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

The header passthrough system follows a priority hierarchy:
1. Gateway-specific headers (highest priority)
2. Global database configuration
3. Environment variable defaults (lowest priority)

Example Usage:
    Basic header passthrough with global configuration:
    >>> from unittest.mock import Mock
    >>> mock_db = Mock()
    >>> mock_global_config = Mock()
    >>> mock_global_config.passthrough_headers = ["X-Tenant-Id"]
    >>> mock_db.query.return_value.first.return_value = mock_global_config
    >>> headers = get_passthrough_headers(
    ...     request_headers={"x-tenant-id": "123"},
    ...     base_headers={"Content-Type": "application/json"},
    ...     db=mock_db
    ... )
    >>> sorted(headers.items())
    [('Content-Type', 'application/json'), ('X-Tenant-Id', '123')]
"""

# Standard
import logging
from typing import Dict, Optional

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import GlobalConfig

logger = logging.getLogger(__name__)


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
    - Prevents conflicts with existing base headers (e.g., Content-Type)
    - Blocks Authorization header conflicts with gateway authentication
    - Logs all conflicts and skipped headers for debugging
    - Uses case-insensitive header matching for robustness

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
        Basic usage with global configuration:
        >>> # Mock database and settings for doctest
        >>> from unittest.mock import Mock, MagicMock
        >>> mock_db = Mock()
        >>> mock_global_config = Mock()
        >>> mock_global_config.passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]
        >>> mock_db.query.return_value.first.return_value = mock_global_config
        >>>
        >>> request_headers = {
        ...     "authorization": "Bearer token123",
        ...     "x-tenant-id": "acme-corp",
        ...     "x-trace-id": "trace-456",
        ...     "user-agent": "TestClient/1.0"
        ... }
        >>> base_headers = {"Content-Type": "application/json"}
        >>>
        >>> result = get_passthrough_headers(request_headers, base_headers, mock_db)
        >>> sorted(result.items())
        [('Content-Type', 'application/json'), ('X-Tenant-Id', 'acme-corp'), ('X-Trace-Id', 'trace-456')]

        Gateway-specific configuration override:
        >>> mock_gateway = Mock()
        >>> mock_gateway.passthrough_headers = ["X-Custom-Header"]
        >>> mock_gateway.auth_type = None
        >>> request_headers = {
        ...     "x-custom-header": "custom-value",
        ...     "x-tenant-id": "should-be-ignored"
        ... }
        >>>
        >>> result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)
        >>> sorted(result.items())
        [('Content-Type', 'application/json'), ('X-Custom-Header', 'custom-value')]

        Authorization header conflict with basic auth:
        >>> mock_gateway.auth_type = "basic"
        >>> mock_gateway.passthrough_headers = ["Authorization", "X-Tenant-Id"]
        >>> request_headers = {
        ...     "authorization": "Bearer should-be-blocked",
        ...     "x-tenant-id": "acme-corp"
        ... }
        >>>
        >>> result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)
        >>> sorted(result.items())  # Authorization blocked due to basic auth conflict
        [('Content-Type', 'application/json'), ('X-Tenant-Id', 'acme-corp')]

        Base header conflict prevention:
        >>> base_headers_with_conflict = {"Content-Type": "application/json", "x-tenant-id": "from-base"}
        >>> request_headers = {"x-tenant-id": "from-request"}
        >>> mock_gateway.auth_type = None
        >>> mock_gateway.passthrough_headers = ["X-Tenant-Id"]
        >>>
        >>> result = get_passthrough_headers(request_headers, base_headers_with_conflict, mock_db, mock_gateway)
        >>> result["x-tenant-id"]  # Base header preserved, request header blocked
        'from-base'

        Empty allowed headers (no passthrough):
        >>> empty_global_config = Mock()
        >>> empty_global_config.passthrough_headers = []
        >>> mock_db.query.return_value.first.return_value = empty_global_config
        >>>
        >>> request_headers = {"x-tenant-id": "should-be-ignored"}
        >>> result = get_passthrough_headers(request_headers, {"Content-Type": "application/json"}, mock_db)
        >>> result
        {'Content-Type': 'application/json'}

    Note:
        Header names are matched case-insensitively but preserved in their original
        case from the allowed_headers configuration. Request header values are
        matched case-insensitively against the request_headers dictionary.
    """
    passthrough_headers = base_headers.copy()

    # Get global passthrough headers first
    global_config = db.query(GlobalConfig).first()
    allowed_headers = global_config.passthrough_headers if global_config else settings.default_passthrough_headers

    # Gateway specific headers override global config
    if gateway:
        if gateway.passthrough_headers is not None:
            allowed_headers = gateway.passthrough_headers

    # Get auth headers to check for conflicts
    base_headers_keys = {key.lower(): key for key in passthrough_headers.keys()}

    # Copy allowed headers from request
    if request_headers and allowed_headers:
        for header_name in allowed_headers:
            header_value = request_headers.get(header_name.lower())
            if header_value:

                header_lower = header_name.lower()
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

                passthrough_headers[header_name] = header_value
            else:
                logger.warning(f"Header {header_name} not found in request headers, skipping passthrough")

    return passthrough_headers
