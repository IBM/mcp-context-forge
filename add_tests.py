import sys

tests_to_add = """

    @patch("mcpgateway.routers.app.verify_jwt_token_cached")
    @patch("mcpgateway.routers.app.create_access_token")
    @patch("mcpgateway.routers.app.EmailAuthService")
    @patch("mcpgateway.routers.app.get_csrf_service")
    def test_login_success(self, mock_get_csrf_service, mock_auth_service, mock_create_token, mock_verify, client):
        \"\"\"Test successful login returns user and sets cookies.\"\"\"
        # Mock EmailAuthService
        mock_user = _make_mock_user()
        mock_auth_instance = AsyncMock()
        mock_auth_instance.authenticate_user = AsyncMock(return_value=mock_user)
        mock_auth_service.return_value = mock_auth_instance

        # Mock create_access_token
        mock_create_token.return_value = ("mock_jwt_token", datetime.now())

        # Mock verify_jwt_token_cached
        mock_verify.return_value = {"jti": "mock_jti"}

        # Mock csrf service
        mock_csrf = MagicMock()
        mock_csrf.generate_csrf_token.return_value = "mock_csrf_token"
        mock_get_csrf_service.return_value = mock_csrf

        response = client.post(
            "/app/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user"]["email"] == "test@example.com"
        assert data["csrf_token"] == "mock_csrf_token"
        
        # Verify cookies are set
        set_cookie_headers = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
        assert any("jwt_token=mock_jwt_token" in h for h in set_cookie_headers)
        assert any("csrf_token=mock_csrf_token" in h for h in set_cookie_headers)


    def test_get_me_success(self, client, dep_override):
        \"\"\"Test successful get_me returns user profile.\"\"\"
        mock_user = _make_mock_user()
        async def override_user():
            return (mock_user, "mock_jti")
        dep_override(get_current_user_from_cookie, override_user)

        response = client.get("/app/auth/me")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["email"] == "test@example.com"


    @patch("mcpgateway.routers.app.get_token_blocklist_service")
    def test_logout_success_with_jti(self, mock_get_blocklist, client, dep_override):
        \"\"\"Test logout with valid jti revokes token and clears cookies.\"\"\"
        mock_user = _make_mock_user()
        async def override_user():
            return (mock_user, "mock_jti")
        dep_override(get_current_user_from_cookie, override_user)
        
        mock_blocklist = MagicMock()
        mock_blocklist.revoke_token = MagicMock()
        mock_get_blocklist.return_value = mock_blocklist

        response = client.post("/app/auth/logout")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["message"] == "Logged out successfully"
        
        # Verify cookies are cleared
        set_cookie_headers = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
        assert any("jwt_token" in h and "Max-Age=0" in h for h in set_cookie_headers)

    @patch("mcpgateway.routers.app.get_token_blocklist_service")
    def test_logout_success_without_jti(self, mock_get_blocklist, client, dep_override):
        \"\"\"Test logout without jti skips revocation but clears cookies.\"\"\"
        mock_user = _make_mock_user()
        async def override_user():
            return (mock_user, None)
        dep_override(get_current_user_from_cookie, override_user)

        response = client.post("/app/auth/logout")

        assert response.status_code == status.HTTP_200_OK
        assert mock_get_blocklist.call_count == 0

    @patch("mcpgateway.routers.app.get_token_blocklist_service")
    def test_logout_internal_error(self, mock_get_blocklist, client, dep_override):
        \"\"\"Test logout handles unexpected errors.\"\"\"
        mock_user = _make_mock_user()
        async def override_user():
            return (mock_user, "mock_jti")
        dep_override(get_current_user_from_cookie, override_user)
        
        with patch("mcpgateway.routers.app.clear_auth_cookie", side_effect=Exception("Unexpected")):
            response = client.post("/app/auth/logout")
            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            detail = response.json()["detail"]
            if isinstance(detail, dict):
                assert detail["message"] == "Logout failed"
            else:
                assert "Logout failed" in detail


class TestCSRFTokenValidation:
    def test_validate_csrf_token_length_error(self):
        \"\"\"Test startup validation fails if CSRF token length is wrong.\"\"\"
        import mcpgateway.routers.app
        with patch("mcpgateway.utils.csrf.CSRF_TOKEN_LENGTH", 10):
            with pytest.raises(ValueError, match="CSRF token length mismatch"):
                mcpgateway.routers.app._validate_csrf_token_length()

"""

filepath = "tests/unit/mcpgateway/routers/test_app.py"

standalone_tests = """

class TestAppRouterCoverage:
    \"\"\"Additional tests for app.py coverage.\"\"\"
""" + tests_to_add

with open(filepath, "a", encoding="utf-8", newline='\n') as f:
    f.write(standalone_tests)

print("Tests appended successfully!")
