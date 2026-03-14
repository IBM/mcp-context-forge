# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/oauth2/__init__.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Public exports for OAuth2 base library.
"""

# First-Party
from mcpgateway.oauth2.base import (
    OAuth2BaseLibrary,
    apply_scope_modifications,
    extract_claims,
    normalize_scopes,
    scopes_to_string,
)
from mcpgateway.oauth2.exceptions import (
    OAuth2BaseError,
    OAuth2DiscoveryError,
    OAuth2TokenExchangeError,
    OAuth2TokenRefreshError,
    OAuth2TokenValidationError,
)
from mcpgateway.oauth2.models import (
    OAuth2ValidationConfig,
    RefreshTokenRequest,
    TokenExchangeRequest,
    TokenValidationResult,
)

__all__ = [
    "OAuth2BaseError",
    "OAuth2BaseLibrary",
    "OAuth2DiscoveryError",
    "OAuth2TokenExchangeError",
    "OAuth2TokenRefreshError",
    "OAuth2TokenValidationError",
    "OAuth2ValidationConfig",
    "RefreshTokenRequest",
    "TokenExchangeRequest",
    "TokenValidationResult",
    "apply_scope_modifications",
    "extract_claims",
    "normalize_scopes",
    "scopes_to_string",
]
