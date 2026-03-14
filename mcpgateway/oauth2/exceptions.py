# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/oauth2/exceptions.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

OAuth2 base library exceptions.
"""


class OAuth2BaseError(Exception):
    """Base exception for OAuth2 helper operations."""


class OAuth2DiscoveryError(OAuth2BaseError):
    """Raised when OAuth/OIDC metadata discovery fails."""


class OAuth2TokenValidationError(OAuth2BaseError):
    """Raised when token validation fails."""


class OAuth2TokenExchangeError(OAuth2BaseError):
    """Raised when OAuth 2.0 token exchange fails."""


class OAuth2TokenRefreshError(OAuth2BaseError):
    """Raised when refresh token grant fails."""
