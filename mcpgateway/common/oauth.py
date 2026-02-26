# -*- coding: utf-8 -*-
"""Shared OAuth helpers and sensitive-key definitions."""

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
