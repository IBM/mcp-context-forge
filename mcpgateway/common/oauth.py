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


def is_sensitive_oauth_key(key: Any) -> bool:
    """Return whether an oauth_config key should be treated as secret.

    Args:
        key: Candidate oauth_config key.

    Returns:
        bool: True when key maps to sensitive OAuth material.
    """
    return isinstance(key, str) and key.lower() in OAUTH_SENSITIVE_KEYS


# extra_auth_params must not set these parameters. The gateway or a dedicated oauth_config
# field sets them (PKCE included), or they override the others (RFC 9101 request objects).
OAUTH_RESERVED_AUTHORIZATION_PARAMS: frozenset[str] = frozenset(
    {"response_type", "client_id", "redirect_uri", "state", "scope", "code_challenge", "code_challenge_method", "code_verifier", "audience", "resource", "request", "request_uri"}
)


def is_reserved_authorization_param(name: Any) -> bool:
    """Return whether ``oauth_config["extra_auth_params"]`` must not use a parameter name.

    Names compare case-insensitively with ``.`` and ``-`` read as ``_``, because some
    servers normalize names that way. Secret names also count as reserved.

    Args:
        name: Candidate authorization request parameter name.

    Returns:
        bool: True when the name is reserved or is not a string.
    """
    if not isinstance(name, str):
        return True
    canonical = name.lower().replace(".", "_").replace("-", "_")
    return canonical in OAUTH_RESERVED_AUTHORIZATION_PARAMS or is_sensitive_oauth_key(canonical)
