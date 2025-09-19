# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/metadata_capture.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Metadata capture utilities for comprehensive audit tracking.
This module provides utilities for capturing comprehensive metadata during
entity creation and modification operations. It extracts request context
information such as authenticated user, IP address, user agent, and source
type for audit trail purposes.

Examples:
    >>> from mcpgateway.utils.metadata_capture import MetadataCapture
    >>> from types import SimpleNamespace
    >>> # Create mock request for testing
    >>> request = SimpleNamespace()
    >>> request.client = SimpleNamespace()
    >>> request.client.host = "192.168.1.1"
    >>> request.headers = {"user-agent": "test/1.0"}
    >>> request.url = SimpleNamespace()
    >>> request.url.path = "/admin/tools"
    >>> # Metadata capture during entity creation
    >>> metadata = MetadataCapture.extract_creation_metadata(request, user="admin")
    >>> metadata["created_by"]
    'admin'
    >>> metadata["created_via"]
    'ui'
"""

# Standard
from typing import Dict, Optional

# Third-Party
from fastapi import Request


class MetadataCapture:
    """Utilities for capturing comprehensive metadata during entity operations."""

    @staticmethod
    def extract_request_context(request: Request) -> Dict[str, Optional[str]]:
        """Extract basic request context information.

        Args:
            request: FastAPI request object

        Returns:
            Dict containing IP address, user agent, and source type

        Examples:
            >>> # Mock request for testing
            >>> from types import SimpleNamespace
            >>> mock_request = SimpleNamespace()
            >>> mock_request.client = SimpleNamespace()
            >>> mock_request.client.host = "192.168.1.100"
            >>> mock_request.headers = {"user-agent": "Mozilla/5.0"}
            >>> mock_request.url = SimpleNamespace()
            >>> mock_request.url.path = "/admin/tools"
            >>> context = MetadataCapture.extract_request_context(mock_request)
            >>> context["from_ip"]
            '192.168.1.100'
            >>> context["via"]
            'ui'
        """
        # Extract IP address (handle various proxy scenarios)
        client_ip = None
        if request.client:
            client_ip = request.client.host

        # Check for forwarded headers (reverse proxy support)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP in the chain (original client)
            client_ip = forwarded_for.split(",")[0].strip()

        # Extract user agent
        user_agent = request.headers.get("user-agent")

        # Determine source type based on URL path
        via = "api"  # default
        if hasattr(request, "url") and hasattr(request.url, "path"):
            path = str(request.url.path)
            if "/admin/" in path:
                via = "ui"

        return {
            "from_ip": client_ip,
            "user_agent": user_agent,
            "via": via,
        }

    @staticmethod
    def extract_username(user) -> str:
        """Extract username from auth response.

        Args:
            user: Response from require_auth - can be string or dict

        Returns:
            Username string

        Examples:
            >>> MetadataCapture.extract_username("admin")
            'admin'
            >>> MetadataCapture.extract_username({"username": "alice", "exp": 123})
            'alice'
            >>> MetadataCapture.extract_username({"sub": "bob", "exp": 123})
            'bob'
            >>> MetadataCapture.extract_username({"email": "user@example.com", "full_name": "User"})
            'user@example.com'
        """
        if isinstance(user, str):
            return user
        elif isinstance(user, dict):
            # Try to extract username from JWT payload or user context
            return user.get("username") or user.get("sub") or user.get("email") or "unknown"
        else:
            return "unknown"

    @staticmethod
    def extract_creation_metadata(
        request: Request,
        user,  # Can be str or dict from require_auth
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Extract complete metadata for entity creation.

        Args:
            request: FastAPI request object
            user: Authenticated user (string username or dict JWT payload)
            import_batch_id: Optional UUID for bulk import operations
            federation_source: Optional source gateway for federated entities

        Returns:
            Dict containing all creation metadata fields

        Examples:
            >>> from types import SimpleNamespace
            >>> mock_request = SimpleNamespace()
            >>> mock_request.client = SimpleNamespace()
            >>> mock_request.client.host = "10.0.0.1"
            >>> mock_request.headers = {"user-agent": "curl/7.68.0"}
            >>> mock_request.url = SimpleNamespace()
            >>> mock_request.url.path = "/tools"
            >>> metadata = MetadataCapture.extract_creation_metadata(mock_request, "admin")
            >>> metadata["created_by"]
            'admin'
            >>> metadata["created_via"]
            'api'
            >>> metadata["created_from_ip"]
            '10.0.0.1'
        """
        context = MetadataCapture.extract_request_context(request)

        return {
            "created_by": MetadataCapture.extract_username(user),
            "created_from_ip": context["from_ip"],
            "created_via": context["via"],
            "created_user_agent": context["user_agent"],
            "import_batch_id": import_batch_id,
            "federation_source": federation_source,
            "version": 1,
        }

    @staticmethod
    def extract_modification_metadata(
        request: Request,
        user,  # Can be str or dict from require_auth
        current_version: int = 1,
    ) -> Dict[str, Optional[str]]:
        """Extract metadata for entity modification.

        Args:
            request: FastAPI request object
            user: Authenticated user (string username or dict JWT payload)
            current_version: Current entity version (will be incremented)

        Returns:
            Dict containing modification metadata fields

        Examples:
            >>> from types import SimpleNamespace
            >>> mock_request = SimpleNamespace()
            >>> mock_request.client = SimpleNamespace()
            >>> mock_request.client.host = "172.16.0.1"
            >>> mock_request.headers = {"user-agent": "HTTPie/2.4.0"}
            >>> mock_request.url = SimpleNamespace()
            >>> mock_request.url.path = "/admin/tools/123/edit"
            >>> metadata = MetadataCapture.extract_modification_metadata(mock_request, "alice", 2)
            >>> metadata["modified_by"]
            'alice'
            >>> metadata["modified_via"]
            'ui'
            >>> metadata["version"]
            3
        """
        context = MetadataCapture.extract_request_context(request)

        return {
            "modified_by": MetadataCapture.extract_username(user),
            "modified_from_ip": context["from_ip"],
            "modified_via": context["via"],
            "modified_user_agent": context["user_agent"],
            "version": current_version + 1,
        }

    @staticmethod
    def determine_source_from_context(
        import_batch_id: Optional[str] = None,
        federation_source: Optional[str] = None,
        via: str = "api",
    ) -> str:
        """Determine the source type based on available context.

        Args:
            import_batch_id: UUID for bulk import operations
            federation_source: Source gateway for federated entities
            via: Basic source type (api, ui)

        Returns:
            More specific source description

        Examples:
            >>> MetadataCapture.determine_source_from_context(via="ui")
            'ui'
            >>> MetadataCapture.determine_source_from_context(import_batch_id="123", via="api")
            'import'
            >>> MetadataCapture.determine_source_from_context(federation_source="gateway-1", via="api")
            'federation'
        """
        if import_batch_id:
            return "import"
        elif federation_source:
            return "federation"
        else:
            return via

    @staticmethod
    def sanitize_user_agent(user_agent: Optional[str]) -> Optional[str]:
        """Sanitize user agent string for safe storage and display.

        Args:
            user_agent: Raw user agent string from request headers

        Returns:
            Sanitized user agent string or None

        Examples:
            >>> MetadataCapture.sanitize_user_agent("Mozilla/5.0 (Linux)")
            'Mozilla/5.0 (Linux)'
            >>> MetadataCapture.sanitize_user_agent(None)
            >>> len(MetadataCapture.sanitize_user_agent("x" * 2000)) <= 503
            True
        """
        if not user_agent:
            return None

        # Truncate excessively long user agents
        if len(user_agent) > 500:
            user_agent = user_agent[:500] + "..."

        # Remove any potentially dangerous characters
        user_agent = user_agent.replace("\n", " ").replace("\r", " ").replace("\t", " ")

        return user_agent.strip()

    @staticmethod
    def validate_ip_address(ip_address: Optional[str]) -> Optional[str]:
        """Validate and sanitize IP address for storage.

        Args:
            ip_address: IP address string from request

        Returns:
            Validated IP address or None

        Examples:
            >>> MetadataCapture.validate_ip_address("192.168.1.1")
            '192.168.1.1'
            >>> MetadataCapture.validate_ip_address("::1")
            '::1'
            >>> MetadataCapture.validate_ip_address(None)
            >>> MetadataCapture.validate_ip_address("invalid-ip")
            'invalid-ip'
        """
        if not ip_address:
            return None

        # Basic validation - store as-is but limit length
        if len(ip_address) > 45:  # Max length for IPv6
            return ip_address[:45]

        return ip_address.strip()
