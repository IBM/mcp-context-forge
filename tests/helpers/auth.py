# -*- coding: utf-8 -*-
"""Location: ./tests/helpers/auth.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared authentication helpers for tests.

This module centralizes JWT creation and Authorization header construction for
integration, end-to-end, Playwright, and live-gateway tests.
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
from typing import Any

# Third-Party
import jwt

# First-Party
from mcpgateway.utils import create_jwt_token as jwt_util

_UNSET = object()
_create_jwt_token: Any = jwt_util._create_jwt_token  # pylint: disable=protected-access  # type: ignore[attr-defined]


def make_test_jwt(
    email: str = "admin@example.com",
    *,
    is_admin: bool = False,
    teams: object = _UNSET,
    scopes: dict[str, Any] | None = None,
    expires_in_minutes: int = 30,
    secret: str = "",
    algorithm: str = "",
    auth_provider: str = "local",
    include_user_data: bool = False,
    include_email_claim: bool = False,
    user_data: dict[str, Any] | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> str:
    """Create a standardized JWT for tests while preserving legacy helper semantics.

    When is_admin=True is passed, automatically enables include_user_data to ensure
    the is_admin claim is properly embedded in the token's user_data field.
    """
    payload: dict[str, Any] = {"sub": email}
    if include_email_claim:
        payload["email"] = email
    if extra_payload:
        payload.update(extra_payload)

    # Auto-enable include_user_data when is_admin=True to ensure the claim is embedded
    if is_admin and not include_user_data and user_data is None:
        include_user_data = True

    resolved_user_data = user_data
    if include_user_data and resolved_user_data is None:
        resolved_user_data = {"email": email, "is_admin": is_admin, "auth_provider": auth_provider}

    if teams is _UNSET:
        return _create_jwt_token(
            payload,
            expires_in_minutes=expires_in_minutes,
            secret=secret,
            algorithm=algorithm,
            user_data=resolved_user_data,
            scopes=scopes,
        )

    return _create_jwt_token(
        payload,
        expires_in_minutes=expires_in_minutes,
        secret=secret,
        algorithm=algorithm,
        user_data=resolved_user_data,
        teams=teams,
        scopes=scopes,
    )


def make_legacy_test_jwt(
    email: str = "admin@example.com",
    *,
    is_admin: bool = False,
    teams: object = _UNSET,
    expires_in_minutes: int = 30,
    secret: str = "",
    algorithm: str = "",
    include_email_claim: bool = False,
    include_iat: bool = True,
    extra_payload: dict[str, Any] | None = None,
) -> str:
    """Create a minimal raw JWT for legacy-compatible test payloads."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {"sub": email, "exp": int((now + timedelta(minutes=expires_in_minutes)).timestamp())}
    if include_iat:
        payload["iat"] = int(now.timestamp())
    if include_email_claim:
        payload["email"] = email
    if is_admin:
        payload["is_admin"] = True
    if teams is not _UNSET:
        payload["teams"] = teams
    if extra_payload:
        payload.update(extra_payload)
    if "iss" not in payload:
        payload["iss"] = "mcpgateway"
    if "aud" not in payload:
        payload["aud"] = "mcpgateway-api"
    return jwt.encode(payload, secret, algorithm=algorithm)


def make_auth_headers(token: str, *, accept: str | None = None, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    """Build a standard Bearer Authorization header mapping."""
    headers = {"Authorization": f"Bearer {token}"}
    if accept is not None:
        headers["Accept"] = accept
    if extra_headers:
        headers.update(extra_headers)
    return headers


def make_auth_header_for_email(
    email: str = "admin@example.com",
    *,
    is_admin: bool = False,
    teams: object = _UNSET,
    scopes: dict[str, Any] | None = None,
    expires_in_minutes: int = 30,
    secret: str = "",
    algorithm: str = "",
    accept: str | None = None,
    include_user_data: bool = False,
    include_email_claim: bool = False,
    extra_payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Create a JWT and return a standard Authorization header mapping."""
    token = make_test_jwt(
        email,
        is_admin=is_admin,
        teams=teams,
        scopes=scopes,
        expires_in_minutes=expires_in_minutes,
        secret=secret,
        algorithm=algorithm,
        include_user_data=include_user_data,
        include_email_claim=include_email_claim,
        extra_payload=extra_payload,
    )
    return make_auth_headers(token, accept=accept, extra_headers=extra_headers)


def make_playwright_api_context(playwright: Any, base_url: str, token: str, *, accept: str | None = "application/json", extra_headers: dict[str, str] | None = None) -> Any:
    """Create a Playwright API request context with Bearer auth.

    DEPRECATED: Use ApiTestHelper.new_context() instead for consistency.
    This function delegates to ApiTestHelper.new_context().
    """
    # Import here to avoid circular dependency
    from tests.helpers.api_helpers import ApiTestHelper  # pylint: disable=import-outside-toplevel

    return ApiTestHelper.new_context(playwright, base_url, token, accept=accept or "application/json", extra_headers=extra_headers)
