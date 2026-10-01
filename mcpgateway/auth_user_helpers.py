# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/auth_user_helpers.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Helpers for interpreting persisted user authentication state.
"""

# Standard
from typing import Optional, Protocol


PASSWORDLESS_HASH_TYPE = "none"
DISABLED_PASSWORD_HASH = "!disabled"


class PasswordCredentialState(Protocol):
    """Minimal credential fields required for password-capability decisions."""

    password_hash: Optional[str]
    password_hash_type: str


def is_passwordless_user(user: PasswordCredentialState) -> bool:
    """Return whether a persisted user has no local password credential.

    Missing attributes are treated as programmer errors. Cached/read-only
    identity objects may omit credential material, and callers must not classify
    those objects as passwordless.
    """
    required = ("password_hash", "password_hash_type")
    missing = [field for field in required if not hasattr(user, field)]
    if missing:
        raise TypeError(f"user must expose credential fields: {', '.join(missing)}")

    return user.password_hash is None or user.password_hash_type == PASSWORDLESS_HASH_TYPE
