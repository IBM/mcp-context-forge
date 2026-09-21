# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the auth router module.
"""

# Standard
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
from pydantic import SecretStr
import pytest

# First-Party
from mcpgateway.routers.auth import get_csrf_token, get_db, login, LoginRequest


class TestLoginRequest:
    """Tests for LoginRequest model."""

    def test_get_email_from_email_field(self):
        """Test getting email from email field."""
        req = LoginRequest(email="test@example.com", password="pass")
        assert req.get_email() == "test@example.com"

    def test_get_email_from_username_with_at(self):
        """Test getting email from username field with @ symbol."""
        req = LoginRequest(username="user@domain.com", password="pass")
        assert req.get_email() == "user@domain.com"

    def test_get_email_from_username_without_at_raises(self):
        """Test that plain username raises ValueError."""
        req = LoginRequest(username="plainuser", password="pass")
        with pytest.raises(ValueError, match="Username format not supported"):
            req.get_email()

    def test_get_email_missing_both_raises(self):
        """Test that missing email and username raises ValueError."""
        req = LoginRequest(password="pass")
        with pytest.raises(ValueError, match="Either email or username must be provided"):
            req.get_email()

    def test_email_takes_precedence_over_username(self):
        """Test that email field takes precedence over username."""
        req = LoginRequest(email="email@example.com", username="user@domain.com", password="pass")
        assert req.get_email() == "email@example.com"


class TestGetDb:
    """Tests for get_db dependency."""

    def test_get_db_yields_session(self):
        """Test that get_db yields a session."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            gen = get_db()
            db = next(gen)

            assert db == mock_db

            # Complete the generator
            try:
                next(gen)
            except StopIteration:
                pass

            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_rollback_on_exception(self):
        """Test that get_db rolls back on exception."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.rollback.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_invalidate_on_rollback_failure(self):
        """Test that get_db invalidates on rollback failure."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.rollback.assert_called_once()
            mock_db.invalidate.assert_called_once()
            mock_db.close.assert_called_once()

    def test_get_db_passes_on_invalidate_failure(self):
        """Test that get_db passes on invalidate failure."""
        with patch("mcpgateway.routers.auth.SessionLocal") as mock_session_local:
            mock_db = MagicMock()
            mock_db.rollback.side_effect = Exception("Rollback failed")
            mock_db.invalidate.side_effect = Exception("Invalidate failed")
            mock_session_local.return_value = mock_db

            gen = get_db()
            next(gen)

            # Simulate exception during usage - should not raise additional errors
            with pytest.raises(RuntimeError):
                gen.throw(RuntimeError("Test error"))

            mock_db.close.assert_called_once()


class TestLogin:
    """Tests for login endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "test-agent"}
        return request

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def mock_user(self):
        """Create a mock email user."""
        user = MagicMock()
        user.id = "test-user-id"
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_active = True
        user.is_admin = False
        user.auth_provider = "local"
        user.teams = []
        return user

    @pytest.mark.asyncio
    async def test_login_success(self, mock_request, mock_db, mock_user):
        """Test successful login."""
        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
            patch("mcpgateway.routers.auth.settings") as mock_settings,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service

            mock_create_token.return_value = ("test_token", 3600)
            mock_settings.sso_enabled = False
            mock_settings.csrf_rotate_on_login = False

            login_request = LoginRequest(email="test@example.com", password="password123")  # pragma: allowlist secret

            response = await login(login_request, mock_request, mock_db)

            assert response.access_token == "test_token"
            assert response.token_type == "bearer"
            assert response.expires_in == 3600
            mock_service.authenticate_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, mock_request, mock_db):
        """Test login with invalid credentials.

        Note: Due to exception handling structure, HTTPException from failed auth
        is caught by the generic Exception handler and re-raised as 500.
        """
        with patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service:
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=None)
            mock_auth_service.return_value = mock_service

            login_request = LoginRequest(email="test@example.com", password="wrongpass")  # pragma: allowlist secret

            with pytest.raises(HTTPException) as exc_info:
                await login(login_request, mock_request, mock_db)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_value_error(self, mock_request, mock_db):
        """Test login with missing email/username."""
        login_request = LoginRequest(password="password123")  # pragma: allowlist secret

        with pytest.raises(HTTPException) as exc_info:
            await login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_login_service_error(self, mock_request, mock_db):
        """Test login when auth service fails."""
        with patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service:
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(side_effect=Exception("Service error"))
            mock_auth_service.return_value = mock_service

            login_request = LoginRequest(email="test@example.com", password="password123")  # pragma: allowlist secret

            with pytest.raises(HTTPException) as exc_info:
                await login(login_request, mock_request, mock_db)

            assert exc_info.value.status_code == 500
            assert "Authentication service error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_with_username_field(self, mock_request, mock_db, mock_user):
        """Test login using username field instead of email."""
        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
            patch("mcpgateway.routers.auth.settings") as mock_settings,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service

            mock_create_token.return_value = ("test_token", 3600)
            mock_settings.sso_enabled = False
            mock_settings.csrf_rotate_on_login = False

            login_request = LoginRequest(username="user@domain.com", password="password123")  # pragma: allowlist secret

            response = await login(login_request, mock_request, mock_db)

            assert response.access_token == "test_token"
            mock_service.authenticate_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_csrf_rotation_sets_cookie(self, mock_request, mock_db, mock_user):
        """Test login with csrf_rotate_on_login=True sets CSRF cookie."""
        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
            patch("mcpgateway.routers.auth.settings") as mock_settings,
            patch("jwt.decode", return_value={"jti": "session-123"}),
            patch("mcpgateway.routers.auth.generate_csrf_token", return_value="csrf-token-123") as mock_generate,
            patch("mcpgateway.routers.auth.set_csrf_cookie") as mock_set_cookie,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service

            mock_create_token.return_value = ("test_token", 3600)
            mock_settings.sso_enabled = False
            mock_settings.csrf_rotate_on_login = True
            mock_settings.csrf_secret_key = SecretStr("secret")  # pragma: allowlist secret
            mock_settings.csrf_token_expiry = 60

            login_request = LoginRequest(email="test@example.com", password="password123")  # pragma: allowlist secret

            response = await login(login_request, mock_request, mock_db)

            assert response.status_code == 200
            mock_generate.assert_called_once()
            mock_set_cookie.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_csrf_token_success(self):
        """Test CSRF token endpoint returns token and cookie."""
        request = MagicMock()
        request.state = SimpleNamespace(jti="session-123")
        current_user = SimpleNamespace(email="test@example.com")

        with (
            patch("mcpgateway.routers.auth.settings") as mock_settings,
            patch("mcpgateway.routers.auth.generate_csrf_token", return_value="csrf-token-123") as mock_generate,
            patch("mcpgateway.routers.auth.set_csrf_cookie") as mock_set_cookie,
        ):
            mock_settings.csrf_secret_key = SecretStr("secret")  # pragma: allowlist secret
            mock_settings.csrf_token_expiry = 60

            response = await get_csrf_token(request, current_user)

            assert response.status_code == 200
            assert response.body is not None
            mock_generate.assert_called_once_with(user_id="test@example.com", session_id="session-123", secret="secret", expiry=60)
            mock_set_cookie.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_csrf_token_missing_jti_raises_401(self):
        """Test CSRF token endpoint rejects missing session id."""
        request = MagicMock()
        request.state = SimpleNamespace()
        current_user = SimpleNamespace(email="test@example.com")

        with pytest.raises(HTTPException) as exc_info:
            await get_csrf_token(request, current_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_csrf_token_exception_raises_500(self):
        """Test CSRF token endpoint handles unexpected errors."""
        request = MagicMock()
        request.state = SimpleNamespace(jti="session-123")
        current_user = SimpleNamespace(email="test@example.com")

        with (
            patch("mcpgateway.routers.auth.settings") as mock_settings,
            patch("mcpgateway.routers.auth.generate_csrf_token", side_effect=Exception("boom")),
        ):
            mock_settings.csrf_secret_key = SecretStr("secret")  # pragma: allowlist secret
            mock_settings.csrf_token_expiry = 60

            with pytest.raises(HTTPException) as exc_info:
                await get_csrf_token(request, current_user)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_login_with_plain_username_fails(self, mock_request, mock_db):
        """Test login with plain username (no @) fails."""
        login_request = LoginRequest(username="plainuser", password="password123")  # pragma: allowlist secret

        with pytest.raises(HTTPException) as exc_info:
            await login(login_request, mock_request, mock_db)

        assert exc_info.value.status_code == 400
        assert "Username format not supported" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_non_admin_blocked_when_sso_preserve_admin_enabled(self, mock_request, mock_db, mock_user):
        """Non-admin password login should be blocked when SSO preserve-admin mode is enabled."""
        mock_user.is_admin = False

        with (
            patch("mcpgateway.routers.auth.EmailAuthService") as mock_auth_service,
            patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock) as mock_create_token,
            patch("mcpgateway.routers.auth.settings") as mock_settings,
        ):
            mock_service = MagicMock()
            mock_service.authenticate_user = AsyncMock(return_value=mock_user)
            mock_auth_service.return_value = mock_service
            mock_settings.sso_enabled = True
            mock_settings.sso_preserve_admin_auth = True

            login_request = LoginRequest(email="test@example.com", password="password123")  # pragma: allowlist secret

            with pytest.raises(HTTPException) as exc_info:
                await login(login_request, mock_request, mock_db)

            assert exc_info.value.status_code == 400
            assert "restricted to admin accounts" in exc_info.value.detail
            mock_create_token.assert_not_called()


class TestLogout:
    """Tests for logout endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request with auth header."""
        request = MagicMock()
        request.headers = {"Authorization": "Bearer test_token_with_jti"}
        return request

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def mock_current_user(self):
        """Create a mock current user."""
        user = SimpleNamespace()
        user.email = "test@example.com"
        user.id = "test-user-id"
        return user

    @pytest.mark.asyncio
    async def test_logout_with_secret_str_jwt_key(self, mock_request, mock_db, mock_current_user):
        """Test logout when jwt_secret_key is a SecretStr type (covers line 239)."""
        # First-Party
        from mcpgateway.routers.auth import logout

        # Create a mock SecretStr
        mock_secret_str = MagicMock()
        mock_secret_str.get_secret_value.return_value = "test-secret-key"

        with (
            patch("mcpgateway.routers.auth.get_token_blocklist_service") as mock_blocklist_service,
            patch("mcpgateway.routers.auth.settings") as mock_settings,
        ):
            # Setup settings with SecretStr
            mock_settings.jwt_secret_key = mock_secret_str
            mock_settings.jwt_algorithm = "HS256"

            # Setup blocklist service
            mock_service = MagicMock()
            mock_service.revoke_token.return_value = True
            mock_blocklist_service.return_value = mock_service

            # Mock jwt.decode inside the function
            with patch("jwt.decode") as mock_jwt_decode:
                mock_jwt_decode.return_value = {
                    "jti": "test-jti-123",
                    "exp": 1234567890,
                    "iat": 1234567800,
                }

                response = await logout(mock_request, mock_current_user, mock_db)

                assert response["message"] == "Logged out successfully"
                assert response["revoked_token"] == "test-jti-123"
                mock_secret_str.get_secret_value.assert_called_once()
                mock_service.revoke_token.assert_called_once()


class TestSessionRefreshAndValidate:
    """Tests for POST /auth/refresh and GET /auth/validate."""

    SECRET = "test-secret-key"  # pragma: allowlist secret

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = "test-user-id"
        user.email = "test@example.com"
        user.full_name = "Test User"
        user.is_active = True
        user.is_admin = False
        user.auth_provider = "local"
        return user

    def _make_token(self, **overrides):
        """Build a real session JWT so unverified claim decoding works."""
        # Standard
        import time as time_mod

        # Third-Party
        import jwt as jwt_lib

        now = int(time_mod.time())
        payload = {
            "sub": "test-user-id",
            "jti": "old-jti",
            "iat": now,
            "exp": now + 1200,
            "token_use": "session",
            "auth_provider": "local",
            "scopes": {"server_id": None, "permissions": ["*"], "ip_restrictions": [], "time_restrictions": {}},
        }
        payload.update(overrides)
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt_lib.encode(payload, self.SECRET, algorithm="HS256"), payload

    def _make_request(self, token, via_cookie=False):
        """Create a mock request carrying the JWT in header or cookie."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        if via_cookie:
            request.headers = {"user-agent": "test-agent"}
            request.cookies = {"jwt_token": token}
        else:
            request.headers = {"authorization": f"Bearer {token}", "user-agent": "test-agent"}
            request.cookies = {}
        return request

    def _patch_stack(self, payload, expires_in=1200):
        """Patch session-endpoint collaborators for the given verified payload."""
        # Standard
        import time as time_mod

        # Third-Party
        import jwt as jwt_lib

        now = int(time_mod.time())
        issued = jwt_lib.encode({"jti": "new-jti", "exp": now + expires_in}, self.SECRET, algorithm="HS256")
        blocklist = MagicMock()
        blocklist.is_token_revoked.return_value = False
        blocklist.revoke_token.return_value = True
        return {
            "verify": patch("mcpgateway.routers.auth.verify_jwt_token_cached", new_callable=AsyncMock, return_value=payload),
            "blocklist": patch("mcpgateway.routers.auth.get_token_blocklist_service", return_value=blocklist),
            "create_token": patch("mcpgateway.routers.auth.create_access_token", new_callable=AsyncMock, return_value=(issued, expires_in)),
            "csrf": patch("mcpgateway.routers.auth.generate_csrf_token", return_value="csrf-rotated"),
            "set_csrf": patch("mcpgateway.routers.auth.set_csrf_cookie"),
            "set_auth": patch("mcpgateway.routers.auth.set_auth_cookie"),
            "audit": patch("mcpgateway.routers.auth.get_audit_trail_service"),
        }

    # ------------------------------------------------------------------
    # POST /auth/refresh
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_refresh_success_bearer(self, mock_user):
        """A valid local session refreshes: new token issued, CSRF rotated, audit logged, no auth cookie set."""
        # Standard
        import json

        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token()
        request = self._make_request(token)
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(p) for name, p in self._patch_stack(payload).items()}
            response = await refresh_session(request, mock_user)

        body = json.loads(response.body)
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 1200
        assert body["expires_at"]
        assert body["csrf_token"] == "csrf-rotated"
        # Header-authenticated request must NOT receive an auth cookie
        mocks["set_auth"].assert_not_called()
        mocks["audit"].return_value.log_action.assert_called_once()
        audit_kwargs = mocks["audit"].return_value.log_action.call_args.kwargs
        assert audit_kwargs["action"] == "session_refresh"
        assert "db" not in audit_kwargs
        # session_start carried into the new token
        assert "session_start" in mocks["create_token"].call_args.kwargs["extra_claims"]
        # Predecessor token revoked single-use (compare-and-set) before minting
        revoke_kwargs = mocks["blocklist"].return_value.revoke_token.call_args.kwargs
        assert revoke_kwargs["jti"] == "old-jti"
        assert revoke_kwargs["reason"] == "token_refresh"
        assert revoke_kwargs["fail_if_already_revoked"] is True

    @pytest.mark.asyncio
    async def test_refresh_success_cookie_sets_auth_cookie(self, mock_user):
        """A cookie-authenticated refresh re-sets the jwt_token cookie."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token()
        request = self._make_request(token, via_cookie=True)
        with ExitStack() as stack:
            mocks = {name: stack.enter_context(p) for name, p in self._patch_stack(payload).items()}
            await refresh_session(request, mock_user)

        mocks["set_auth"].assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_preserves_session_start_claim(self, mock_user):
        """session_start from the old token is carried over, not re-stamped."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(session_start=1000000000, iat=1000000000)
        request = self._make_request(token)
        with ExitStack() as stack:
            mock_settings = stack.enter_context(patch("mcpgateway.routers.auth.settings"))
            mock_settings.session_max_lifetime = 0  # disable the cap for this test
            mock_settings.csrf_secret_key = SecretStr(self.SECRET)
            mock_settings.csrf_token_expiry = 3600
            mocks = {name: stack.enter_context(p) for name, p in self._patch_stack(payload).items()}
            await refresh_session(request, mock_user)

        assert mocks["create_token"].call_args.kwargs["extra_claims"]["session_start"] == 1000000000

    @pytest.mark.asyncio
    async def test_refresh_refuses_api_token(self, mock_user):
        """API tokens (token_use=api) are refused with 403."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(token_use="api")
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_refuses_token_without_token_use(self, mock_user):
        """Legacy tokens without token_use are refused with 403 (fail-closed)."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(token_use=None)
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_refresh_refuses_when_no_token_present(self, mock_user):
        """Non-JWT auth (basic/proxy) has no session token to refresh: 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        request = MagicMock()
        request.headers = {"user-agent": "test-agent"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_refuses_forged_token(self, mock_user):
        """A token that fails signature verification is rejected with 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, _ = self._make_token()
        request = self._make_request(token)

        with patch("mcpgateway.routers.auth.verify_jwt_token_cached", new_callable=AsyncMock, side_effect=Exception("bad signature")):
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_refuses_revoked_token(self, mock_user):
        """A revoked (blocklisted) token cannot refresh: 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token()
        request = self._make_request(token)
        patches = self._patch_stack(payload)

        blocklist = MagicMock()
        blocklist.is_token_revoked.return_value = True
        with patches["verify"], patch("mcpgateway.routers.auth.get_token_blocklist_service", return_value=blocklist):
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_refuses_subject_mismatch(self, mock_user):
        """A verified token whose subject is a different user is rejected with 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(sub="another-user-id")
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_enforces_max_lifetime(self, mock_user):
        """A session older than SESSION_MAX_LIFETIME cannot be refreshed: 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(session_start=1000000000)  # ancient session
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401
        assert "maximum lifetime" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_fails_closed_when_rotation_not_persisted(self, mock_user):
        """If the predecessor token cannot be revoked (already rotated or store failure): 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token()
        request = self._make_request(token)
        patches = self._patch_stack(payload)

        blocklist = MagicMock()
        blocklist.is_token_revoked.return_value = False
        blocklist.revoke_token.return_value = False  # CAS lost or persistence failure
        with patches["verify"], patch("mcpgateway.routers.auth.get_token_blocklist_service", return_value=blocklist):
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401
        assert "rotated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_refuses_token_without_jti(self, mock_user):
        """A session token without a jti cannot be rotated: 401."""
        # First-Party
        from mcpgateway.routers.auth import refresh_session

        token, payload = self._make_token(jti=None)
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            with pytest.raises(HTTPException) as exc_info:
                await refresh_session(request, mock_user)

        assert exc_info.value.status_code == 401
        assert "jti" in exc_info.value.detail

    # ------------------------------------------------------------------
    # GET /auth/validate
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_validate_local_session(self, mock_user):
        """A local session reports valid=True with accurate expiry and source."""
        # First-Party
        from mcpgateway.routers.auth import validate_session

        token, payload = self._make_token()
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            result = await validate_session(request, mock_user)

        assert result.valid is True
        assert result.session_source == "local"
        assert result.expires_in is not None and 0 < result.expires_in <= 1200
        assert result.expires_at is not None
        assert result.user.email == "test@example.com"
        for key in ("token_expiry", "idle_timeout", "max_lifetime", "warning_time", "refresh_buffer", "activity_tracking"):
            assert key in result.config

    @pytest.mark.asyncio
    async def test_validate_sso_session(self, mock_user):
        """An SSO-provisioned session reports session_source=sso."""
        # First-Party
        from mcpgateway.routers.auth import validate_session

        token, payload = self._make_token(auth_provider="github")
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            result = await validate_session(request, mock_user)

        assert result.session_source == "sso"

    @pytest.mark.asyncio
    async def test_validate_api_token_session(self, mock_user):
        """An API-token session reports session_source=api_token."""
        # First-Party
        from mcpgateway.routers.auth import validate_session

        token, payload = self._make_token(token_use="api")
        request = self._make_request(token)

        with ExitStack() as stack:
            for name in ("verify", "blocklist"):
                stack.enter_context(self._patch_stack(payload)[name])
            result = await validate_session(request, mock_user)

        assert result.session_source == "api_token"

    @pytest.mark.asyncio
    async def test_validate_refuses_forged_token(self, mock_user):
        """A token that fails signature verification is rejected with 401."""
        # First-Party
        from mcpgateway.routers.auth import validate_session

        token, _ = self._make_token()
        request = self._make_request(token)

        with patch("mcpgateway.routers.auth.verify_jwt_token_cached", new_callable=AsyncMock, side_effect=Exception("bad signature")):
            with pytest.raises(HTTPException) as exc_info:
                await validate_session(request, mock_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_validate_refuses_when_no_token_present(self, mock_user):
        """Non-JWT auth has no session token to validate: 401."""
        # First-Party
        from mcpgateway.routers.auth import validate_session

        request = MagicMock()
        request.headers = {"user-agent": "test-agent"}
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await validate_session(request, mock_user)

        assert exc_info.value.status_code == 401

    def test_session_source_external_idp(self):
        """Tokens minted for external-IdP identities classify as sso."""
        # First-Party
        from mcpgateway.routers.auth import _session_source_from_payload

        assert _session_source_from_payload({"token_use": "session", "source": "external_idp"}) == "sso"
        assert _session_source_from_payload({"token_use": "session", "auth_provider": "local"}) == "local"
        assert _session_source_from_payload({"token_use": "api"}) == "api_token"
        assert _session_source_from_payload({}) == "local"


class TestGetSessionUser:
    """Tests for the get_session_user dependency."""

    def _request(self, cookies=None):
        """Create a mock request with the given cookies."""
        request = MagicMock()
        request.cookies = cookies or {}
        return request

    @pytest.mark.asyncio
    async def test_bearer_header_delegates_to_get_current_user(self):
        """A bearer header authenticates through get_current_user."""
        # Third-Party
        from fastapi.security import HTTPAuthorizationCredentials

        # First-Party
        from mcpgateway.routers.auth import get_session_user

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")  # pragma: allowlist secret
        with patch("mcpgateway.routers.auth.get_current_user", new_callable=AsyncMock, return_value="user") as mock_gcu:
            result = await get_session_user(self._request(), creds)

        assert result == "user"
        mock_gcu.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cookie_fallback_uses_validate_token_user(self):
        """Without a bearer header, the jwt_token cookie authenticates via validate_token_user."""
        # First-Party
        from mcpgateway.routers.auth import get_session_user

        with patch("mcpgateway.routers.auth.validate_token_user", new_callable=AsyncMock, return_value="user") as mock_vtu:
            result = await get_session_user(self._request({"jwt_token": "cookie-tok"}), None)

        assert result == "user"
        assert mock_vtu.call_args.args[1] == "cookie-tok"

    @pytest.mark.asyncio
    async def test_no_credentials_rejected(self):
        """Neither header nor cookie: 401."""
        # First-Party
        from mcpgateway.routers.auth import get_session_user

        with pytest.raises(HTTPException) as exc_info:
            await get_session_user(self._request(), None)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_cookie_rejected(self):
        """An invalid session cookie is rejected with the validator's status."""
        # First-Party
        from mcpgateway.auth import TokenValidationError
        from mcpgateway.routers.auth import get_session_user

        with patch("mcpgateway.routers.auth.validate_token_user", new_callable=AsyncMock, side_effect=TokenValidationError("bad", status_code=401)):
            with pytest.raises(HTTPException) as exc_info:
                await get_session_user(self._request({"jwt_token": "bad-tok"}), None)

        assert exc_info.value.status_code == 401


class TestCookieOnlySessionSmoke:
    """Cookie-only requests reach the session endpoints through the full route path."""

    SECRET = "test-secret-key"  # pragma: allowlist secret

    def _payload(self):
        """Session JWT payload whose subject matches the smoke user."""
        # Standard
        import time as time_mod

        now = int(time_mod.time())
        return {
            "sub": "smoke@example.com",
            "email": "smoke@example.com",
            "jti": "smoke-jti",
            "iat": now,
            "exp": now + 1200,
            "token_use": "session",
            "auth_provider": "local",
        }

    def _user(self):
        """Mock user satisfying EmailUserResponse.from_email_user."""
        # Standard
        from datetime import datetime as dt
        from datetime import timezone as tz

        user = MagicMock()
        user.id = "smoke-user-id"
        user.email = "smoke@example.com"
        user.full_name = "Smoke User"
        user.is_admin = False
        user.is_active = True
        user.auth_provider = "local"
        user.created_at = dt.now(tz.utc)
        user.last_login = None
        user.password_change_required = False
        user.failed_login_attempts = 0
        user.locked_until = None
        user.is_account_locked.return_value = False
        user.is_email_verified.return_value = True
        return user

    def _smoke_patches(self, stack, payload):
        """Enter the boundary patches shared by the smoke tests (no real DB in unit runs)."""
        user = self._user()
        stack.enter_context(patch("mcpgateway.routers.auth.validate_token_user", new_callable=AsyncMock, return_value=user))
        stack.enter_context(patch("mcpgateway.utils.verify_credentials.verify_jwt_token", new_callable=AsyncMock, return_value=payload))
        blocklist = MagicMock()
        blocklist.is_token_revoked.return_value = False
        blocklist.revoke_token.return_value = True
        blocklist.get_last_activity.return_value = None
        stack.enter_context(patch("mcpgateway.routers.auth.get_token_blocklist_service", return_value=blocklist))
        stack.enter_context(patch("mcpgateway.services.token_blocklist_service.get_token_blocklist_service", return_value=blocklist))
        stack.enter_context(patch("mcpgateway.routers.auth.get_audit_trail_service"))
        # Middleware-level auth helpers that would otherwise hit the (absent) unit-test DB
        stack.enter_context(patch("mcpgateway.auth._check_token_revoked_sync", return_value=False))
        stack.enter_context(patch("mcpgateway.auth._get_user_by_email_sync", return_value=user))
        stack.enter_context(patch("mcpgateway.auth._is_api_token_jti_sync", return_value=False))
        stack.enter_context(patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch("mcpgateway.middleware.token_scoping.resolve_session_teams", new_callable=AsyncMock, return_value=[]))

    def test_validate_with_cookie_only(self):
        """GET /auth/validate succeeds with only the jwt_token cookie (no auth header)."""
        # Third-Party
        from fastapi.testclient import TestClient
        import jwt as jwt_lib

        # First-Party
        from mcpgateway.main import app

        payload = self._payload()
        token = jwt_lib.encode(payload, self.SECRET, algorithm="HS256")

        with ExitStack() as stack:
            self._smoke_patches(stack, payload)
            client = TestClient(app)
            client.cookies.set("jwt_token", token)
            response = client.get("/auth/validate")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is True
        assert body["session_source"] == "local"
        assert body["user"]["email"] == "smoke@example.com"

    def test_refresh_with_cookie_only_and_csrf(self):
        """POST /auth/refresh succeeds cookie-only (with same-origin CSRF token) and re-sets the auth cookie."""
        # Standard
        from urllib.parse import urlparse

        # Third-Party
        from fastapi.testclient import TestClient
        import jwt as jwt_lib

        # First-Party
        from mcpgateway.config import settings
        from mcpgateway.main import app
        from mcpgateway.services.csrf_service import get_csrf_service

        payload = self._payload()
        token = jwt_lib.encode(payload, self.SECRET, algorithm="HS256")
        csrf_token = get_csrf_service().generate_csrf_token(user_id="smoke@example.com", session_id="smoke-jti")
        parsed_app = urlparse(str(settings.app_domain))
        app_origin = f"{parsed_app.scheme}://{parsed_app.netloc}"

        with ExitStack() as stack:
            self._smoke_patches(stack, payload)
            client = TestClient(app)
            client.cookies.set("jwt_token", token)
            client.cookies.set("mcpgateway_csrf_token", csrf_token)
            response = client.post("/auth/refresh", headers={"X-CSRF-Token": csrf_token, "Origin": app_origin})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["access_token"]
        assert "jwt_token" in response.cookies

    def test_refresh_with_cookie_only_without_csrf_rejected(self):
        """POST /auth/refresh cookie-only without a CSRF token is rejected (path not exempt)."""
        # Third-Party
        from fastapi.testclient import TestClient
        import jwt as jwt_lib

        # First-Party
        from mcpgateway.main import app

        payload = self._payload()
        token = jwt_lib.encode(payload, self.SECRET, algorithm="HS256")

        with ExitStack() as stack:
            self._smoke_patches(stack, payload)
            client = TestClient(app)
            client.cookies.set("jwt_token", token)
            response = client.post("/auth/refresh")

        assert response.status_code == 403
