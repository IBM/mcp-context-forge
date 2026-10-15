# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/mcp_cursor.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Encode authenticated, scope-bound MCP catalog cursors.
"""

# Standard
import base64
import binascii
from collections.abc import Mapping
import hashlib
import hmac
import logging
import os
import re
import time
from typing import Any

# Third-Party
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import orjson
from pydantic import SecretStr

# First-Party
from mcpgateway.config import settings
from mcpgateway.utils.correlation_id import get_correlation_id
from mcpgateway.validation.jsonrpc import JSONRPCError

logger = logging.getLogger(__name__)
_DOMAIN = b"contextforge:mcp-list:v1"


def catalog_session_id(headers: Mapping[str, str]) -> str | None:
    """Resolve protocol and forwarded session headers with consistent precedence.

    Args:
        headers: Request headers from the authenticated transport context.

    Returns:
        Forwarded session identifier, or the protocol session identifier.
    """
    normalized = {name.lower(): value for name, value in headers.items()}
    return normalized.get("x-mcp-session-id") or normalized.get("mcp-session-id")


def scope_fingerprint(method: str, server_id: str | None, user_email: str | None, token_teams: list[str] | None, session_id: str | None) -> str:
    """Hash the effective catalog scope.

    Args:
        method: MCP list method.
        server_id: Virtual server scope, or None for the global catalog.
        user_email: Canonical principal email.
        token_teams: Normalized visibility scope.
        session_id: Downstream session identifier, when present.

    Returns:
        SHA-256 scope fingerprint.
    """
    teams = sorted(set(token_teams)) if token_teams is not None else None
    return hashlib.sha256(orjson.dumps([method, server_id, user_email, teams, session_id])).hexdigest()


def _key(domain: bytes) -> bytes:
    """Derive a catalog key for the specified domain.

    Args:
        domain: Cryptographic purpose identifier.

    Returns:
        Domain-separated key bytes.
    """
    configured_secret = settings.auth_encryption_secret
    secret = configured_secret.get_secret_value() if isinstance(configured_secret, SecretStr) else configured_secret
    if not secret:
        raise JSONRPCError(-32603, "MCP pagination requires AUTH_ENCRYPTION_SECRET")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_DOMAIN, info=domain).derive(secret.encode())


def _cipher() -> AESGCM:
    """Derive the domain-separated catalog encryption key."""
    return AESGCM(_key(_DOMAIN))


def proxy_scope_fingerprint(binding: bytes) -> str:
    """Authenticate proxy scope without exposing credential hashes in Redis.

    Args:
        binding: Serialized scope and effective upstream authorization inputs.

    Returns:
        HMAC fingerprint with a purpose-specific key.
    """
    return hmac.new(_key(b"contextforge:mcp-list:proxy-scope:v1"), binding, hashlib.sha256).hexdigest()


def encode_cursor(scope: str, expires: int, position: dict[str, Any]) -> str:
    """Encrypt a catalog continuation position.

    Args:
        scope: Effective scope fingerprint.
        expires: Fixed traversal expiry as Unix seconds.
        position: Database or snapshot continuation position.

    Returns:
        URL-safe opaque cursor.
    """
    nonce = os.urandom(12)
    payload = orjson.dumps({"v": 1, "scope": scope, "expires": expires, **position}, option=orjson.OPT_SORT_KEYS)
    encrypted = _cipher().encrypt(nonce, payload, _DOMAIN)
    return base64.urlsafe_b64encode(nonce + encrypted).decode().rstrip("=")


def decode_cursor(cursor: Any, scope: str) -> dict[str, Any]:
    """Validate and decrypt a catalog continuation.

    Args:
        cursor: Untrusted client cursor.
        scope: Current effective scope fingerprint.

    Returns:
        Validated continuation payload.

    Raises:
        JSONRPCError: If the cursor is invalid, expired, or belongs to another scope.
    """
    category = "encoding"
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 8192 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
            raise ValueError("Invalid cursor length")
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor:
            raise ValueError("Invalid cursor encoding")
        category = "authentication"
        payload = orjson.loads(_cipher().decrypt(raw[:12], raw[12:], _DOMAIN))
        category = "version"
        if not isinstance(payload, dict) or not isinstance(payload.get("v"), int) or isinstance(payload.get("v"), bool) or payload["v"] != 1:
            raise ValueError("Invalid cursor version")
        category = "scope"
        if not isinstance(payload.get("scope"), str) or not hmac.compare_digest(payload["scope"], scope):
            raise ValueError("Invalid cursor scope")
        category = "expiration"
        if not isinstance(payload.get("expires"), int) or isinstance(payload.get("expires"), bool) or payload["expires"] <= int(time.time()):
            raise ValueError("Expired cursor")
        return payload
    except (ValueError, TypeError, KeyError, binascii.Error, InvalidTag, orjson.JSONDecodeError) as exc:
        logger.warning("MCP list cursor rejected: category=%s correlation_id=%s", category, get_correlation_id())
        raise JSONRPCError(-32602, "Invalid or expired MCP list cursor") from exc
