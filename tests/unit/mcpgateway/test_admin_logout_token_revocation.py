# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_logout_token_revocation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

HTTP-level tests for ``/admin/logout`` token revocation.

These tests exercise the registered FastAPI route end-to-end (CSRF dependency,
cookie parsing, response shaping). The earlier revision of this file invoked
``_admin_logout`` directly via ``asyncio.run`` against a ``MagicMock`` request,
which bypassed middleware/dependency injection and would have passed even if
the route was unregistered or the CSRF dependency was removed. The current
revision relies on ``TestClient`` and dependency overrides so that those
regressions are caught.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

# Third-Party
import jwt
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.admin import enforce_admin_csrf
from mcpgateway.config import settings
from mcpgateway.main import app


def _jwt_secret() -> str:
    secret = settings.jwt_secret_key
    return secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret


def _build_admin_jwt(*, include_jti: bool = True, expires_in_minutes: int = 20) -> tuple[str, dict]:
    """Build a signed admin JWT and return (token, payload).

    Returns:
        Tuple of (encoded JWT string, payload dict).
    """
    now = datetime.now(timezone.utc)
    payload: dict = {
        "email": "admin@example.com",
        "exp": int((now + timedelta(minutes=expires_in_minutes)).timestamp()),
        "iat": int(now.timestamp()),
        "last_activity": int(now.timestamp()),
    }
    if include_jti:
        payload["jti"] = str(uuid.uuid4())
    token = jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, payload


@pytest.fixture
def disable_admin_csrf():
    """Bypass admin CSRF for happy-path tests via dependency override.

    A separate test (``test_admin_logout_post_rejects_missing_csrf_token``)
    exercises the real CSRF path without this override.
    """

    async def _noop():
        return None

    app.dependency_overrides[enforce_admin_csrf] = _noop
    try:
        yield
    finally:
        app.dependency_overrides.pop(enforce_admin_csrf, None)


class TestAdminLogoutTokenRevocation:
    """Happy-path: ``/admin/logout`` revokes the caller's token in the blocklist."""

    def test_post_revokes_token_in_blocklist(self, disable_admin_csrf):
        token, payload = _build_admin_jwt()

        with (
            patch("mcpgateway.admin.verify_jwt_token_cached", new_callable=AsyncMock) as mock_verify,
            patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service,
        ):
            mock_verify.return_value = payload
            mock_blocklist = MagicMock()
            mock_blocklist.revoke_token.return_value = True
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout", cookies={"jwt_token": token})

            assert response.status_code in (302, 303, 307, 200)
            mock_blocklist.revoke_token.assert_called_once()
            kwargs = mock_blocklist.revoke_token.call_args.kwargs
            assert kwargs["jti"] == payload["jti"]
            assert kwargs["revoked_by"] == "admin@example.com"
            assert kwargs["reason"] == "admin_logout"
            assert kwargs["token_expiry"] is not None
            assert kwargs["last_activity"] is not None

    def test_post_without_jwt_cookie_does_not_call_blocklist(self, disable_admin_csrf):
        with patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service:
            mock_blocklist = MagicMock()
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout")

            assert response.status_code in (302, 303, 307, 200)
            mock_blocklist.revoke_token.assert_not_called()

    def test_post_with_invalid_jwt_cookie_does_not_block_logout(self, disable_admin_csrf):
        with (
            patch("mcpgateway.admin.verify_jwt_token_cached", new_callable=AsyncMock) as mock_verify,
            patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service,
        ):
            mock_verify.side_effect = Exception("Invalid token")
            mock_blocklist = MagicMock()
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout", cookies={"jwt_token": "not.a.valid.jwt"})

            assert response.status_code in (302, 303, 307, 200)
            mock_blocklist.revoke_token.assert_not_called()

    def test_post_payload_without_jti_does_not_revoke(self, disable_admin_csrf):
        token, payload = _build_admin_jwt(include_jti=False)
        assert "jti" not in payload

        with (
            patch("mcpgateway.admin.verify_jwt_token_cached", new_callable=AsyncMock) as mock_verify,
            patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service,
        ):
            mock_verify.return_value = payload
            mock_blocklist = MagicMock()
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout", cookies={"jwt_token": token})

            assert response.status_code in (302, 303, 307, 200)
            mock_blocklist.revoke_token.assert_not_called()

    def test_post_blocklist_failure_does_not_block_logout(self, disable_admin_csrf):
        token, payload = _build_admin_jwt()

        with (
            patch("mcpgateway.admin.verify_jwt_token_cached", new_callable=AsyncMock) as mock_verify,
            patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service,
        ):
            mock_verify.return_value = payload
            mock_blocklist = MagicMock()
            mock_blocklist.revoke_token.side_effect = Exception("Database unavailable")
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout", cookies={"jwt_token": token})

            assert response.status_code in (302, 303, 307, 200)
            mock_blocklist.revoke_token.assert_called_once()


class TestAdminLogoutDenyPaths:
    """Deny-path regression tests required by AGENTS.md for security-sensitive changes."""

    def test_post_with_jwt_cookie_but_no_csrf_token_is_rejected(self):
        """Cookie auth + state-changing POST without a CSRF token must return 403.

        This protects against cross-site-forced-logout attacks. No
        ``disable_admin_csrf`` fixture here — the real ``enforce_admin_csrf``
        dependency runs and must reject the request.
        """
        token, _ = _build_admin_jwt()

        with patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service:
            mock_blocklist = MagicMock()
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.post("/admin/logout", cookies={"jwt_token": token})

            assert response.status_code == 403
            assert "csrf" in response.json().get("detail", "").lower()
            mock_blocklist.revoke_token.assert_not_called()

    def test_get_logout_is_exempt_from_csrf(self):
        """GET /admin/logout supports OIDC front-channel logout and is exempt from CSRF.

        Per the OIDC Front-Channel Logout 1.0 spec the IdP issues a GET; we
        must accept it without a CSRF token.
        """
        token, payload = _build_admin_jwt()

        with (
            patch("mcpgateway.admin.verify_jwt_token_cached", new_callable=AsyncMock) as mock_verify,
            patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service") as mock_get_service,
        ):
            mock_verify.return_value = payload
            mock_blocklist = MagicMock()
            mock_blocklist.revoke_token.return_value = True
            mock_get_service.return_value = mock_blocklist

            client = TestClient(app, follow_redirects=False)
            response = client.get(
                "/admin/logout",
                cookies={"jwt_token": token},
                headers={"accept": "application/json"},
            )

            assert response.status_code in (200, 302, 303, 307)
