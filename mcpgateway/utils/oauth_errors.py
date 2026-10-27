# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/utils/oauth_errors.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Safe OAuth failure classification from explicit provider evidence.
"""

# Standard
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class OAuthFailure:
    """An allowlisted OAuth code and safe corrective guidance."""

    code: str
    message: str
    reauthorization_required: bool = False


_FAILURES = {
    "authorization_missing": OAuthFailure("authorization_missing", "Authorize this gateway before testing the connection.", True),
    "token_expired": OAuthFailure("token_expired", "The stored token has expired. Authorize this gateway again.", True),
    "invalid_token": OAuthFailure("invalid_token", "The stored token is invalid. Authorize this gateway again.", True),
    "insufficient_scope": OAuthFailure("insufficient_scope", "The provider reports insufficient scope. Review the requested scopes and authorize again.", True),
    "invalid_scope": OAuthFailure("insufficient_scope", "The provider rejects the requested scope. Review the scopes and authorize again.", True),
    "redirect_uri_mismatch": OAuthFailure("redirect_uri_mismatch", "The provider rejects the redirect URI. Check the registered callback URL.", True),
    "issuer_mismatch": OAuthFailure("issuer_mismatch", "Authorization response issuer mismatch. Check the issuer configuration and authorize again.", True),
    "invalid_client": OAuthFailure("invalid_client", "The provider rejects the OAuth client. Check the client configuration."),
    "token_exchange_failed": OAuthFailure("token_exchange_failed", "OAuth token exchange fails. Check the configuration and authorize again.", True),
    "token_url_unreachable": OAuthFailure("token_url_unreachable", "The token endpoint is unreachable. Check its URL and network access."),
    "access_denied": OAuthFailure("access_denied", "The provider denies authorization. Authorize this gateway again.", True),
    "oauth_error": OAuthFailure("oauth_error", "OAuth authorization failed. Check the configuration and try again."),
}


def oauth_failure(code: Any) -> OAuthFailure:
    """Select fixed guidance without copying provider text.

    Args:
        code: Provider error code or internal stable code.

    Returns:
        An allowlisted failure, or a generic OAuth failure.
    """
    return _FAILURES.get(code, _FAILURES["oauth_error"]) if isinstance(code, str) else _FAILURES["oauth_error"]


def response_oauth_code(response: Any) -> str | None:
    """Extract an explicit OAuth error from JSON or a Bearer challenge.

    Args:
        response: Upstream HTTP response.

    Returns:
        An allowlisted code, or None when the evidence is ambiguous.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = None
    code = body.get("error") if isinstance(body, dict) else None
    if isinstance(code, dict):
        data = code.get("data")
        code = data.get("error") if isinstance(data, dict) else None
    if isinstance(code, str) and code in _FAILURES:
        return oauth_failure(code).code
    challenge = response.headers.get("www-authenticate", "")
    if isinstance(challenge, str) and re.match(r"^\s*Bearer\s", challenge, re.IGNORECASE):
        match = re.search(r'\berror\s*=\s*"(invalid_token|insufficient_scope)"', challenge, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return None
