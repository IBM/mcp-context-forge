# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/oauth2/models.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Typed models for OAuth2 base helpers.
"""

# Standard
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass(slots=True)
class OAuth2ValidationConfig:
    """Configuration for token validation."""

    issuer: Optional[str] = None
    audience: Optional[str] = None
    algorithms: Sequence[str] = ("RS256", "ES256", "HS256")
    jwks_uri: Optional[str] = None
    introspection_endpoint: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    require_exp: bool = True
    leeway_seconds: int = 0


@dataclass(slots=True)
class TokenValidationResult:
    """Canonical token validation response."""

    active: bool
    claims: Dict[str, Any] = field(default_factory=dict)
    source: str = "none"  # jwt | introspection | none
    scopes: List[str] = field(default_factory=list)


@dataclass(slots=True)
class OAuth2TokenRequest:
    """Common fields for token endpoint operations."""

    token_endpoint: str
    client_id: str
    client_secret: Optional[str] = None
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class TokenExchangeRequest(OAuth2TokenRequest):
    """RFC 8693 token exchange request."""

    subject_token: str = ""
    subject_token_type: str = "urn:ietf:params:oauth:token-type:access_token"
    requested_token_type: Optional[str] = None
    actor_token: Optional[str] = None
    actor_token_type: Optional[str] = None
    scope: Optional[List[str]] = None
    audience: Optional[List[str]] = None
    resource: Optional[List[str]] = None


@dataclass(slots=True)
class RefreshTokenRequest(OAuth2TokenRequest):
    """RFC 6749 refresh token request."""

    refresh_token: str = ""
    scope: Optional[List[str]] = None
    resource: Optional[List[str]] = None
