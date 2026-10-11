# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/common/oauth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Shared OAuth helpers and sensitive-key definitions.
"""

# Standard
from typing import Any

# OAuth config keys that should always be treated as secret material.
OAUTH_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "client_secret",
        "password",
        "refresh_token",
        "access_token",
        "id_token",
        "token",
        "secret",
        "private_key",
    }
)

# Token endpoint client authentication methods honored at runtime (RFC 6749
# Section 2.3.1, RFC 7591 Section 2.3, RFC 7523 Section 2.2). The schema and
# the runtime read this same set so a config value rejected at the API
# boundary can never be silently honored with a different method later.
SUPPORTED_TOKEN_ENDPOINT_AUTH_METHODS: frozenset[str] = frozenset(
    {
        "none",
        "client_secret_basic",
        "client_secret_post",
        "private_key_jwt",
    }
)

# client_assertion_type value for JWT bearer client assertions (RFC 7523
# Section 2.2).
CLIENT_ASSERTION_TYPE_JWT_BEARER: str = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

# Asymmetric signing algorithms allowed for private_key_jwt client
# assertions. Symmetric HS* and the "none" algorithm are intentionally
# excluded: the gateways signs outbound assertions with asymmetric key
# material and must never fall back to a shared-secret or unsigned mode.
SUPPORTED_TOKEN_ENDPOINT_SIGNING_ALGS: frozenset[str] = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
        "PS256",
    }
)

DEFAULT_TOKEN_ENDPOINT_SIGNING_ALG: str = "RS256"

# Upper bound for the assertion exp-iat window (RFC 7523 recommends a short
# lifetime; providers reject assertions that live too long).
MAX_CLIENT_ASSERTION_TTL_SECONDS: int = 300


def is_sensitive_oauth_key(key: Any) -> bool:
    """Return whether an oauth_config key should be treated as secret.

    Args:
        key: Candidate oauth_config key.

    Returns:
        bool: True when key maps to sensitive OAuth material.
    """
    return isinstance(key, str) and key.lower() in OAUTH_SENSITIVE_KEYS
