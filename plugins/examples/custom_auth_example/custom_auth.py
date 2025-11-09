# -*- coding: utf-8 -*-
"""Location: ./plugins/custom_auth_example/custom_auth.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: ContextForge

Custom Authentication Example Plugin.

This plugin demonstrates both layers of HTTP authentication hooks:
1. HTTP_PRE_REQUEST: Transform custom token formats to standard bearer tokens
2. HTTP_AUTH_RESOLVE_USER: Implement custom user authentication (LDAP, mTLS, external systems)

Use Cases:
- Convert X-API-Key headers to Authorization: Bearer tokens
- Authenticate users via LDAP/Active Directory
- Validate mTLS client certificates
- Integrate with external authentication services
- Transform proprietary token formats

Hook: http_pre_request, http_auth_resolve_user
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timezone
import logging
from typing import Dict

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework import (
    HttpAuthResolveUserPayload,
    HttpHeaderPayload,
    HttpPostRequestPayload,
    HttpPreRequestPayload,
    Plugin,
    PluginConfig,
    PluginContext,
    PluginResult,
    PluginViolation,
    PluginViolationError,
)

logger = logging.getLogger(__name__)


class CustomAuthConfig(BaseModel):
    """Configuration for custom authentication.

    Attributes:
        api_key_header: Custom header name to extract API key from (default: X-API-Key).
        api_key_mapping: Mapping of API keys to user information.
        blocked_api_keys: List of API keys that are explicitly blocked/revoked.
        ldap_enabled: Enable LDAP authentication (for demonstration).
        mtls_enabled: Enable mTLS certificate authentication (for demonstration).
        transform_headers: Whether to transform custom headers to standard bearer tokens.
        strict_mode: If True, deny auth when API key found but not in mapping (instead of fallback).
    """

    api_key_header: str = "x-api-key"
    api_key_mapping: Dict[str, Dict[str, str]] = {}
    blocked_api_keys: list[str] = []
    ldap_enabled: bool = False
    mtls_enabled: bool = False
    transform_headers: bool = True
    strict_mode: bool = False


class CustomAuthPlugin(Plugin):
    """Custom authentication plugin demonstrating two-layer auth hooks.

    Layer 1 (Middleware): HTTP_PRE_REQUEST
    - Transforms custom authentication headers to standard formats
    - Example: X-API-Key → Authorization: Bearer <token>

    Layer 2 (Auth Resolution): HTTP_AUTH_RESOLVE_USER
    - Implements custom user authentication mechanisms
    - Example: LDAP lookup, mTLS cert validation, external auth service
    """

    def __init__(self, config: PluginConfig) -> None:
        """Initialize the custom auth plugin.

        Args:
            config: Plugin configuration.
        """
        super().__init__(config)
        self._cfg = CustomAuthConfig(**(config.config or {}))
        logger.info(f"CustomAuthPlugin initialized with config: {self._cfg}")

    async def http_pre_request(
        self,
        payload: HttpPreRequestPayload,
        context: PluginContext,
    ) -> PluginResult[HttpHeaderPayload]:
        """Transform custom authentication headers before authentication.

        This hook runs in the middleware layer BEFORE get_current_user() is called.
        Use it to transform custom token formats to standard bearer tokens.

        Example transformations:
        - X-API-Key: secret123 → Authorization: Bearer <generated-jwt>
        - X-Custom-Token: abc → Authorization: Bearer abc
        - Proprietary-Auth: xyz → Authorization: Bearer xyz

        Args:
            payload: HTTP pre-request payload with headers.
            context: Plugin execution context.

        Returns:
            Result with modified headers if transformation applied.
        """
        if not self._cfg.transform_headers:
            return PluginResult(continue_processing=True)

        headers = dict(payload.headers.root)

        # Check if custom API key header is present
        api_key_header = self._cfg.api_key_header.lower()
        api_key = headers.get(api_key_header)

        if api_key and "authorization" not in headers:
            # Transform X-API-Key to Authorization: Bearer header
            logger.info(f"Transforming {self._cfg.api_key_header} to Authorization header")
            headers["authorization"] = f"Bearer {api_key}"

            # Return modified headers
            modified_headers = HttpHeaderPayload(root=headers)
            return PluginResult(
                modified_payload=modified_headers,
                metadata={"transformed": True, "original_header": self._cfg.api_key_header},
                continue_processing=True,
            )

        return PluginResult(continue_processing=True)

    async def http_auth_resolve_user(
        self,
        payload: HttpAuthResolveUserPayload,
        context: PluginContext,
    ) -> PluginResult[dict]:
        """Resolve user identity using custom authentication mechanisms.

        This hook runs inside get_current_user() BEFORE standard JWT validation.
        Use it to implement custom authentication systems that don't use JWT.

        Example use cases:
        - LDAP/Active Directory authentication
        - mTLS client certificate validation
        - External OAuth/OIDC providers
        - Custom token validation systems
        - Database-backed API key lookup

        Args:
            payload: Auth resolution payload with credentials and headers.
            context: Plugin execution context.

        Returns:
            Result with authenticated user dict if successful, or continue_processing=True
            to fall back to standard JWT authentication.
        """
        headers = dict(payload.headers.root)

        # Example 1: API Key Authentication with Error Handling
        # Check if we have a bearer token that matches our API key mapping
        if payload.credentials and payload.credentials.get("scheme") == "Bearer":
            token = payload.credentials.get("credentials")

            # Check if API key is explicitly blocked
            if token and token in self._cfg.blocked_api_keys:
                logger.warning(f"Blocked API key attempted: {token[:10]}...")
                # Raise PluginViolationError to explicitly deny authentication
                raise PluginViolationError(
                    message="API key has been revoked",
                    violation=PluginViolation(
                        reason="API key revoked",
                        description="The API key has been revoked and cannot be used for authentication",
                        code="API_KEY_REVOKED",
                        details={"key_prefix": token[:10]},
                    ),
                )

            # Check if API key is in valid mapping
            if token and token in self._cfg.api_key_mapping:
                user_info = self._cfg.api_key_mapping[token]
                logger.info(f"User authenticated via API key mapping: {user_info.get('email')}")

                # Convert is_admin to boolean (config stores as string)
                is_admin_str = user_info.get("is_admin", "false")
                is_admin = is_admin_str.lower() == "true" if isinstance(is_admin_str, str) else bool(is_admin_str)

                # Return user dictionary (will be converted to EmailUser in auth.py)
                return PluginResult(
                    modified_payload={
                        "email": user_info.get("email"),
                        "full_name": user_info.get("full_name", "API User"),
                        "is_admin": is_admin,
                        "is_active": True,
                        "password_hash": "",  # Not used for API key auth
                        "email_verified_at": datetime.now(timezone.utc),
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    },
                    metadata={"auth_method": "api_key"},
                    continue_processing=False,  # User authenticated, don't try standard auth
                )

            # Strict mode: If we have a bearer token but it's not in our mapping, deny
            if token and self._cfg.strict_mode:
                logger.warning(f"Invalid API key in strict mode: {token[:10]}...")
                raise PluginViolationError(
                    message="Invalid API key",
                    violation=PluginViolation(
                        reason="Invalid API key",
                        description="The provided API key is not valid",
                        code="INVALID_API_KEY",
                        details={"strict_mode": True},
                    ),
                )

        # Example 2: mTLS Certificate Authentication
        if self._cfg.mtls_enabled:
            # Check for client certificate headers (set by reverse proxy)
            client_cert_dn = headers.get("x-client-cert-dn")
            if client_cert_dn:
                logger.info(f"mTLS authentication for DN: {client_cert_dn}")
                # In a real implementation, you would:
                # 1. Validate the certificate DN
                # 2. Look up user in directory or database
                # 3. Return authenticated user
                # For demo purposes, we'll just pass through to standard auth
                return PluginResult(
                    continue_processing=True,
                    metadata={"mtls_cert_detected": True, "dn": client_cert_dn},
                )

        # Example 3: LDAP Authentication (placeholder)
        if self._cfg.ldap_enabled:
            # Check for LDAP token header
            ldap_token = headers.get("x-ldap-token")
            if ldap_token:
                logger.info("LDAP authentication requested")
                # In a real implementation, you would:
                # 1. Validate LDAP token
                # 2. Query LDAP server for user information
                # 3. Return authenticated user
                # For demo purposes, we'll fall back to standard auth
                return PluginResult(
                    continue_processing=True,
                    metadata={"ldap_attempted": True},
                )

        # No custom authentication matched - fall back to standard JWT/API token validation
        return PluginResult(
            continue_processing=True,
            metadata={"custom_auth": "not_applicable"},
        )

    async def http_post_request(
        self,
        payload: HttpPostRequestPayload,
        context: PluginContext,
    ) -> PluginResult[HttpHeaderPayload]:
        """Add custom headers to response after request completion.

        This hook runs AFTER the request has been processed and allows
        adding custom response headers based on the authentication context.

        Example use cases:
        - Add correlation IDs to response
        - Add auth method indicator headers
        - Add compliance/audit headers
        - Add rate limit headers

        Args:
            payload: HTTP post-request payload with response information.
            context: Plugin execution context.

        Returns:
            Result with modified response headers if applicable.
        """
        response_headers = dict(payload.response_headers.root) if payload.response_headers else {}

        # Add correlation ID from request to response (if present)
        request_headers = dict(payload.headers.root)
        if "x-correlation-id" in request_headers:
            response_headers["x-correlation-id"] = request_headers["x-correlation-id"]

        # Add auth method used (from context stored by auth resolution hook)
        auth_method = context.state.get("auth_method") if context.state else None
        if auth_method:
            response_headers["x-auth-method"] = auth_method

        # Add custom compliance header
        if payload.status_code and payload.status_code < 400:
            response_headers["x-auth-status"] = "authenticated"
        else:
            response_headers["x-auth-status"] = "failed"

        # Log authentication attempt for audit
        # Note: context.global_context.request_id is the same across all hooks for this request
        logger.info(
            f"[{context.global_context.request_id}] Auth request completed: "
            f"path={payload.path} method={payload.method} status={payload.status_code} "
            f"client={payload.client_host}"
        )

        return PluginResult(
            modified_payload=HttpHeaderPayload(root=response_headers),
            continue_processing=True,
        )
