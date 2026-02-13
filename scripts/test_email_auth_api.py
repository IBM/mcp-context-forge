#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration test for the Email Auth User Management API.

Tests all /auth/email/* endpoints against a running ContextForge instance,
covering CRUD operations, partial updates, login flows, password management,
admin security controls, and edge cases.

Requirements:
    - A running ContextForge instance (e.g., docker-compose up)
    - PyJWT: pip install PyJWT (included in project venv)

Usage:
    # Using project venv (recommended)
    source .venv/bin/activate && python scripts/test_email_auth_api.py

    # With custom options
    python scripts/test_email_auth_api.py --base-url http://localhost:4444 --secret my-key

    # Verbose mode (show response bodies)
    python scripts/test_email_auth_api.py -v

    # Run a specific test group
    python scripts/test_email_auth_api.py --group admin-crud
"""

# Standard
import argparse
from dataclasses import dataclass, field
import json
import sys
import time
import traceback
from typing import Any, Optional
import urllib.error
import urllib.request
import uuid

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_JWT_SECRET = "my-test-key"
DEFAULT_ADMIN_EMAIL = "admin@example.com"
TEST_EMAIL_PREFIX = "itest-"  # prefix for test users to avoid collisions
TIMEOUT_SECONDS = 15
MAX_RETRIES = 2
RETRY_DELAY = 1.0

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------
PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0
ERRORS: list[str] = []
VERBOSE = False


@dataclass
class APIResponse:
    """Structured API response."""

    status: int
    body: Any
    headers: dict = field(default_factory=dict)
    error: Optional[str] = None


def generate_token(
    email: str,
    secret: str,
    is_admin: bool = True,
    teams: Any = None,
) -> str:
    """Generate a JWT token with the specified claims."""
    # Third-Party
    import jwt as pyjwt

    payload = {
        "username": email,
        "sub": email,
        "is_admin": is_admin,
        "iss": "mcpgateway",
        "aud": "mcpgateway-api",
        "iat": int(time.time()),
        "exp": int(time.time()) + 604800,
        "jti": str(uuid.uuid4()),
        "teams": teams,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def api(
    method: str,
    path: str,
    data: Any = None,
    token: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    retries: int = MAX_RETRIES,
) -> APIResponse:
    """Make an API request with retry logic for transient failures."""
    url = f"{base_url}{path}"
    body = json.dumps(data).encode() if data is not None else None

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, method=method)
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                resp_body = resp.read().decode()
                try:
                    parsed = json.loads(resp_body)
                except (json.JSONDecodeError, ValueError):
                    parsed = {"_raw": resp_body}
                return APIResponse(
                    status=resp.status,
                    body=parsed,
                    headers=dict(resp.headers),
                )
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode() if hasattr(e, "read") else ""
            try:
                parsed = json.loads(resp_body)
            except (json.JSONDecodeError, ValueError):
                parsed = {"detail": resp_body} if resp_body else {}
            return APIResponse(
                status=e.code,
                body=parsed,
                headers=dict(e.headers) if hasattr(e, "headers") else {},
            )
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt < retries:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            return APIResponse(
                status=0,
                body={},
                error=f"Connection failed after {retries + 1} attempts: {e}",
            )
    return APIResponse(status=0, body={}, error="Exhausted retries")


def test(name: str, condition: bool, detail: str = "") -> bool:
    """Record and print a test result."""
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  {GREEN}PASS{NC}: {name}")
        return True
    else:
        FAIL_COUNT += 1
        msg = f"  {RED}FAIL{NC}: {name}"
        if detail:
            msg += f" {DIM}({detail}){NC}"
        print(msg)
        ERRORS.append(f"{name}: {detail}")
        return False


def skip(name: str, reason: str = ""):
    """Record a skipped test."""
    global SKIP_COUNT
    SKIP_COUNT += 1
    msg = f"  {YELLOW}SKIP{NC}: {name}"
    if reason:
        msg += f" {DIM}({reason}){NC}"
    print(msg)


def vprint(msg: str):
    """Print only in verbose mode."""
    if VERBOSE:
        print(f"  {DIM}{msg}{NC}")


def test_email(suffix: str) -> str:
    """Generate a unique test email address."""
    return f"{TEST_EMAIL_PREFIX}{suffix}-{uuid.uuid4().hex[:6]}@example.com"


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------


class TestContext:
    """Shared context for all test groups."""

    def __init__(self, base_url: str, secret: str, admin_email: str):
        self.base_url = base_url
        self.secret = secret
        self.admin_email = admin_email
        self.admin_token = generate_token(admin_email, secret, is_admin=True, teams=None)
        self.created_users: list[str] = []

    def api(self, method: str, path: str, data: Any = None, token: str | None = None) -> APIResponse:
        tok = token if token is not None else self.admin_token
        resp = api(method, path, data=data, token=tok, base_url=self.base_url)
        vprint(f"{method} {path} -> {resp.status}")
        if VERBOSE and resp.body:
            vprint(f"  {json.dumps(resp.body, default=str)[:200]}")
        return resp

    def create_user(self, email: str, password: str = "SecurePass123!", **kwargs) -> APIResponse:
        """Create a test user and track for cleanup."""
        payload = {"email": email, "password": password, "full_name": kwargs.pop("full_name", "Test User"), **kwargs}
        resp = self.api("POST", "/auth/email/admin/users", payload)
        if resp.status == 201:
            self.created_users.append(email)
        return resp

    def cleanup(self):
        """Delete all test users created during the test run."""
        for email in self.created_users:
            self.api("DELETE", f"/auth/email/admin/users/{email}")
        self.created_users.clear()

    def cleanup_user(self, email: str):
        """Delete a specific user (ignoring errors)."""
        self.api("DELETE", f"/auth/email/admin/users/{email}")
        if email in self.created_users:
            self.created_users.remove(email)


def test_connectivity(ctx: TestContext):
    """Test 0: Connectivity and authentication."""
    print(f"\n{CYAN}--- 0. Connectivity & Authentication ---{NC}")

    resp = ctx.api("GET", "/health")
    test("Health check", resp.status == 200, f"status={resp.status}")

    resp = ctx.api("GET", "/version")
    test("Authenticated version endpoint", resp.status == 200, f"status={resp.status}")

    resp = ctx.api("GET", "/auth/email/admin/users")
    test("Admin user list accessible", resp.status == 200, f"status={resp.status}")

    # Non-admin should be rejected for admin endpoints
    non_admin_token = generate_token("viewer@example.com", ctx.secret, is_admin=False)
    resp = ctx.api("GET", "/auth/email/admin/users", token=non_admin_token)
    test("Non-admin rejected from admin endpoint", resp.status in (401, 403), f"status={resp.status}")

    # No token should be rejected
    resp = api("GET", f"/auth/email/admin/users", token=None, base_url=ctx.base_url)
    test("Unauthenticated request rejected", resp.status in (401, 403), f"status={resp.status}")


def test_admin_create(ctx: TestContext):
    """Test 1: Admin user creation."""
    print(f"\n{CYAN}--- 1. Admin Create User ---{NC}")

    # Basic creation
    email = test_email("basic")
    resp = ctx.create_user(email)
    test("Create user returns 201", resp.status == 201, f"status={resp.status}")
    if resp.status == 201:
        test("Correct email returned", resp.body.get("email") == email)
        test("Full name returned", resp.body.get("full_name") == "Test User")
        test("Not admin by default", resp.body.get("is_admin") is False)
        test("Active by default", resp.body.get("is_active") is True)
        test("password_change_required defaults to False", resp.body.get("password_change_required") is False)
        test("Auth provider is local", resp.body.get("auth_provider") == "local")

    # Create inactive user (#2524)
    email_inactive = test_email("inactive")
    resp = ctx.create_user(email_inactive, is_active=False, full_name="Inactive User")
    test("Create inactive user returns 201", resp.status == 201, f"status={resp.status}")
    if resp.status == 201:
        test("is_active=False honored", resp.body.get("is_active") is False)

    # Create with password_change_required (#2523)
    email_pcr = test_email("pcr")
    resp = ctx.create_user(email_pcr, password_change_required=True, full_name="PCR User")
    test("Create with password_change_required returns 201", resp.status == 201, f"status={resp.status}")
    if resp.status == 201:
        test("password_change_required=True honored", resp.body.get("password_change_required") is True)

    # Create admin user
    email_admin = test_email("admin")
    resp = ctx.create_user(email_admin, is_admin=True, full_name="Admin User")
    test("Create admin user returns 201", resp.status == 201, f"status={resp.status}")
    if resp.status == 201:
        test("is_admin=True honored", resp.body.get("is_admin") is True)

    # Create with all fields
    email_all = test_email("all-fields")
    resp = ctx.create_user(
        email_all,
        password="AllFields123!",
        full_name="All Fields",
        is_admin=True,
        is_active=False,
        password_change_required=True,
    )
    test("Create with all fields returns 201", resp.status == 201, f"status={resp.status}")
    if resp.status == 201:
        test("All fields: is_admin=True", resp.body.get("is_admin") is True)
        test("All fields: is_active=False", resp.body.get("is_active") is False)
        test("All fields: pcr=True", resp.body.get("password_change_required") is True)

    # Missing password validation — Pydantic now enforces required password, returns 422
    email_nopw = test_email("nopw")
    resp = ctx.api("POST", "/auth/email/admin/users", {"email": email_nopw, "full_name": "No PW"})
    test("Missing password returns 422", resp.status == 422, f"status={resp.status}")
    ctx.cleanup_user(email_nopw)  # clean up in case it was created

    # Short password validation
    email_short = test_email("shortpw")
    resp = ctx.api(
        "POST",
        "/auth/email/admin/users",
        {
            "email": email_short,
            "password": "Short1!",
            "full_name": "Short PW",
        },
    )
    test("Short password returns 422", resp.status == 422, f"status={resp.status}")

    # Duplicate user
    resp = ctx.api(
        "POST",
        "/auth/email/admin/users",
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": "Duplicate",
        },
    )
    test("Duplicate user returns 409", resp.status == 409, f"status={resp.status}")


def test_admin_read(ctx: TestContext):
    """Test 2: Admin read/list users."""
    print(f"\n{CYAN}--- 2. Admin Read/List Users ---{NC}")

    # Create a user to read
    email = test_email("read")
    ctx.create_user(email, full_name="Readable User")

    # Get specific user
    resp = ctx.api("GET", f"/auth/email/admin/users/{email}")
    test("Get user by email returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Returned correct email", resp.body.get("email") == email)
        test("Returned full_name", resp.body.get("full_name") == "Readable User")

    # Get non-existent user
    resp = ctx.api("GET", "/auth/email/admin/users/nonexistent-xyz@example.com")
    test("Non-existent user returns 404", resp.status == 404, f"status={resp.status}")

    # List users (basic)
    resp = ctx.api("GET", "/auth/email/admin/users")
    test("List users returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200 and isinstance(resp.body, list):
        test("List returns array of users", len(resp.body) > 0, f"count={len(resp.body)}")
        emails = [u.get("email") for u in resp.body]
        test("Created user in list", email in emails, f"emails={emails[:5]}")

    # List with cursor pagination
    resp = ctx.api("GET", "/auth/email/admin/users?include_pagination=true&limit=2")
    test("Paginated list returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200 and isinstance(resp.body, dict):
        test("Paginated response has 'users' key", "users" in resp.body)
        test("Paginated response has cursor key", "nextCursor" in resp.body or "next_cursor" in resp.body)


def test_admin_update_partial(ctx: TestContext):
    """Test 3: Partial updates (#2545, #2658)."""
    print(f"\n{CYAN}--- 3. Partial Updates (#2545, #2658) ---{NC}")

    # Create base user
    email = test_email("partial")
    ctx.create_user(email, full_name="Original Name")

    # Update name only — other fields must be preserved
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"full_name": "Updated Name"})
    test("Name-only update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Name updated", resp.body.get("full_name") == "Updated Name")
        test("is_admin preserved (False)", resp.body.get("is_admin") is False)
        test("is_active preserved (True)", resp.body.get("is_active") is True)
        test("pcr preserved (False)", resp.body.get("password_change_required") is False)

    # Verify login still works (password not wiped by partial update)
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "SecurePass123!"}, token="")
    test("Login after partial update works", resp.status in (200, 403), f"status={resp.status}")

    # Update is_active only
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"is_active": False})
    test("is_active-only update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("is_active changed to False", resp.body.get("is_active") is False)
        test("Name preserved", resp.body.get("full_name") == "Updated Name")

    # Reactivate
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"is_active": True})
    test("Reactivate returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("is_active back to True", resp.body.get("is_active") is True)

    # Update is_admin only
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"is_admin": True})
    test("is_admin-only update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("is_admin changed to True", resp.body.get("is_admin") is True)

    # Demote
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"is_admin": False})
    test("Demote returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("is_admin back to False", resp.body.get("is_admin") is False)

    # Update pcr only
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"password_change_required": True})
    test("pcr-only update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("pcr changed to True", resp.body.get("password_change_required") is True)

    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"password_change_required": False})
    test("Clear pcr returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("pcr back to False", resp.body.get("password_change_required") is False)

    # Empty body (no-op)
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {})
    test("Empty body update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("No-op preserves name", resp.body.get("full_name") == "Updated Name")
        test("No-op preserves is_admin", resp.body.get("is_admin") is False)
        test("No-op preserves is_active", resp.body.get("is_active") is True)

    # Multi-field update
    resp = ctx.api(
        "PATCH",
        f"/auth/email/admin/users/{email}",
        {
            "full_name": "Multi Updated",
            "is_admin": True,
            "is_active": False,
            "password_change_required": True,
        },
    )
    test("Multi-field update returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Multi: name updated", resp.body.get("full_name") == "Multi Updated")
        test("Multi: is_admin updated", resp.body.get("is_admin") is True)
        test("Multi: is_active updated", resp.body.get("is_active") is False)
        test("Multi: pcr updated", resp.body.get("password_change_required") is True)

    #----------> [#2754] Code to be removed after Sun, 16 Aug 2026 23:59:59 UTC
    # Update name only — other fields must be preserved
    resp = ctx.api("PUT", f"/auth/email/admin/users/{email}", {"full_name": "Updated Name2"})
    test("Name-only update with PUT returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Name updated", resp.body.get("full_name") == "Updated Name2")
        test("is_admin preserved (False)", resp.body.get("is_admin") is True)
        test("is_active preserved (True)", resp.body.get("is_active") is False)
        test("pcr preserved (False)", resp.body.get("password_change_required") is True)
    #---------->

    # Update non-existent user
    resp = ctx.api("PATCH", "/auth/email/admin/users/nonexistent-xyz@example.com", {"full_name": "Ghost"})
    test("Update non-existent user returns 404", resp.status == 404, f"status={resp.status}")


def test_password_management(ctx: TestContext):
    """Test 4: Password and password_change_required interactions."""
    print(f"\n{CYAN}--- 4. Password & password_change_required ---{NC}")

    email = test_email("pw-mgmt")
    ctx.create_user(email, full_name="PW Mgmt User")

    # Admin sets temp password + forces password change
    resp = ctx.api(
        "PATCH",
        f"/auth/email/admin/users/{email}",
        {
            "password": "TempPass999!",
            "password_change_required": True,
        },
    )
    test("Temp password + pcr=True returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("pcr=True honored despite password change", resp.body.get("password_change_required") is True)

    # Admin resets password without explicit pcr (should auto-clear)
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"password": "FinalPass999!"})
    test("Password reset without pcr returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("pcr auto-cleared to False", resp.body.get("password_change_required") is False)

    # Verify new password works
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "FinalPass999!"}, token="")
    test("Login with reset password works", resp.status in (200, 403), f"status={resp.status}")

    # Old password should not work
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "SecurePass123!"}, token="")
    test("Old password rejected after reset", resp.status == 401, f"status={resp.status}")

    # Password update with short password
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email}", {"password": "Short!"})
    test("Short password in update returns 400/422", resp.status in (400, 422), f"status={resp.status}")

    # Change password via user endpoint (self-service)
    user_token = None
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "FinalPass999!"}, token="")
    if resp.status == 200 and resp.body.get("access_token"):
        user_token = resp.body["access_token"]

        resp = ctx.api(
            "POST",
            "/auth/email/change-password",
            {
                "old_password": "FinalPass999!",
                "new_password": "ChangedPass999!",
            },
            token=user_token,
        )
        test("Self-service password change returns 200", resp.status == 200, f"status={resp.status}")

        # Verify new password works
        resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "ChangedPass999!"}, token="")
        test("Login with self-changed password works", resp.status in (200, 403), f"status={resp.status}")
    else:
        skip("Self-service password change", "could not obtain user token")
        skip("Login with self-changed password", "dependent on prior test")


def test_login_flows(ctx: TestContext):
    """Test 5: Login and authentication flows."""
    print(f"\n{CYAN}--- 5. Login & Auth Flows ---{NC}")

    # Normal login
    email = test_email("login")
    ctx.create_user(email, full_name="Login User")

    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "SecurePass123!"}, token="")
    test("Normal login returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Login returns access_token", "access_token" in resp.body)
        test("Login returns token_type bearer", resp.body.get("token_type") == "bearer")
        test("Login returns user object", "user" in resp.body)
        test("Login user has correct email", resp.body.get("user", {}).get("email") == email)

    # Wrong password
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "WrongPass123!"}, token="")
    test("Wrong password returns 401", resp.status == 401, f"status={resp.status}")

    # Non-existent user login
    resp = ctx.api("POST", "/auth/email/login", {"email": "nobody-xyz@example.com", "password": "SecurePass123!"}, token="")
    test("Non-existent user login returns 401", resp.status == 401, f"status={resp.status}")

    # Inactive user cannot login
    email_inactive = test_email("login-inactive")
    ctx.create_user(email_inactive, is_active=False, full_name="Inactive Login")
    resp = ctx.api("POST", "/auth/email/login", {"email": email_inactive, "password": "SecurePass123!"}, token="")
    test("Inactive user login returns 401", resp.status == 401, f"status={resp.status}")

    # Password change required - login returns 403
    email_pcr = test_email("login-pcr")
    ctx.create_user(email_pcr, password_change_required=True, full_name="PCR Login")
    resp = ctx.api("POST", "/auth/email/login", {"email": email_pcr, "password": "SecurePass123!"}, token="")
    test("Login with pcr returns 403", resp.status == 403, f"status={resp.status}")
    if resp.status == 403:
        test("403 includes password change message", "password" in resp.body.get("detail", "").lower())


def test_self_service(ctx: TestContext):
    """Test 6: Self-service endpoints (/me, /events)."""
    print(f"\n{CYAN}--- 6. Self-Service Endpoints ---{NC}")

    email = test_email("self-svc")
    ctx.create_user(email, full_name="Self Service User")

    # Get user token
    resp = ctx.api("POST", "/auth/email/login", {"email": email, "password": "SecurePass123!"}, token="")
    if resp.status != 200 or not resp.body.get("access_token"):
        skip("GET /me", "could not obtain user token")
        skip("GET /events", "could not obtain user token")
        return

    user_token = resp.body["access_token"]

    # Get own profile
    resp = ctx.api("GET", "/auth/email/me", token=user_token)
    test("/me returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("/me returns correct email", resp.body.get("email") == email)
        test("/me returns full_name", resp.body.get("full_name") == "Self Service User")

    # Get own auth events
    resp = ctx.api("GET", "/auth/email/events", token=user_token)
    test("/events returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("/events returns list", isinstance(resp.body, list))


def test_admin_delete(ctx: TestContext):
    """Test 7: Admin delete operations."""
    print(f"\n{CYAN}--- 7. Admin Delete ---{NC}")

    # Normal delete
    email = test_email("delete")
    ctx.create_user(email, full_name="Delete Me")

    resp = ctx.api("DELETE", f"/auth/email/admin/users/{email}")
    test("Delete user returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Delete returns success message", resp.body.get("success") is True)

    # Verify deleted
    resp = ctx.api("GET", f"/auth/email/admin/users/{email}")
    test("Deleted user returns 404", resp.status == 404, f"status={resp.status}")

    # Delete non-existent user
    resp = ctx.api("DELETE", "/auth/email/admin/users/nonexistent-xyz@example.com")
    test("Delete non-existent user returns 404/500", resp.status in (404, 500), f"status={resp.status}")

    # Cannot delete self
    resp = ctx.api("DELETE", f"/auth/email/admin/users/{ctx.admin_email}")
    test("Cannot delete self returns 400", resp.status == 400, f"status={resp.status}")
    if resp.status == 400:
        test("Self-delete error message", "own account" in resp.body.get("detail", "").lower())

    # Remove from tracking since we already deleted
    if email in ctx.created_users:
        ctx.created_users.remove(email)


def test_public_registration(ctx: TestContext):
    """Test 8: Public registration security."""
    print(f"\n{CYAN}--- 8. Public Registration Security ---{NC}")

    # Attempt to inject admin fields — should be rejected (extra="forbid") with 422,
    # or 403 if public registration is disabled
    email = test_email("pub-reg")
    resp = ctx.api(
        "POST",
        "/auth/email/register",
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": "Public User",
            "is_admin": True,
            "is_active": False,
            "password_change_required": True,
        },
        token="",
    )

    if resp.status == 403:
        test("Public registration disabled (403)", True)
        skip("Registration field injection test", "registration disabled")
    elif resp.status == 422:
        # extra="forbid" rejects unknown fields — this is the expected behavior
        test("Public reg rejects admin fields (422)", True)
    elif resp.status in (200, 201):
        # Fallback: if somehow accepted, verify security fields are hardcoded
        user_data = resp.body.get("user", resp.body)
        test("Public reg ignores is_admin=True", user_data.get("is_admin") is False, f"is_admin={user_data.get('is_admin')}")
        test("Public reg ignores is_active=False", user_data.get("is_active") is True, f"is_active={user_data.get('is_active')}")
        test("Public reg ignores pcr=True", user_data.get("password_change_required") is False, f"pcr={user_data.get('password_change_required')}")
        reg_email = user_data.get("email", email)
        ctx.created_users.append(reg_email)
    else:
        test("Public registration returns expected status", False, f"status={resp.status}")

    # Normal registration (without admin fields) should succeed or return 403
    email2 = test_email("pub-reg-clean")
    resp = ctx.api(
        "POST",
        "/auth/email/register",
        {
            "email": email2,
            "password": "SecurePass123!",
            "full_name": "Clean Public User",
        },
        token="",
    )
    if resp.status == 403:
        test("Public registration disabled for clean request (403)", True)
    elif resp.status in (200, 201):
        test("Clean public registration succeeds", True)
        user_data = resp.body.get("user", resp.body)
        test("Clean reg user is not admin", user_data.get("is_admin") is False)
        test("Clean reg user is active", user_data.get("is_active") is True)
        reg_email = user_data.get("email", email2)
        ctx.created_users.append(reg_email)
    else:
        test("Clean public registration returns expected status", False, f"status={resp.status}")


def test_admin_events(ctx: TestContext):
    """Test 9: Admin event audit log."""
    print(f"\n{CYAN}--- 9. Admin Event Audit ---{NC}")

    resp = ctx.api("GET", "/auth/email/admin/events?limit=10")
    test("Admin events returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Admin events returns list", isinstance(resp.body, list))
        if len(resp.body) > 0:
            event = resp.body[0]
            test("Event has expected fields", all(k in event for k in ("event_type", "user_email")), f"keys={list(event.keys())[:6]}")

    # Filter by user email
    resp = ctx.api("GET", f"/auth/email/admin/events?user_email={ctx.admin_email}&limit=5")
    test("Filtered admin events returns 200", resp.status == 200, f"status={resp.status}")


def test_edge_cases(ctx: TestContext):
    """Test 10: Edge cases and error handling."""
    print(f"\n{CYAN}--- 10. Edge Cases ---{NC}")

    # Very long full_name (max_length=255)
    email_long = test_email("long-name")
    resp = ctx.create_user(email_long, full_name="A" * 255)
    test("Max-length name (255 chars) accepted", resp.status == 201, f"status={resp.status}")

    email_toolong = test_email("toolong-name")
    resp = ctx.api(
        "POST",
        "/auth/email/admin/users",
        {
            "email": email_toolong,
            "password": "SecurePass123!",
            "full_name": "A" * 256,
        },
    )
    test("Over-max name (256 chars) rejected", resp.status == 422, f"status={resp.status}")

    # Invalid email format
    resp = ctx.api(
        "POST",
        "/auth/email/admin/users",
        {
            "email": "not-an-email",
            "password": "SecurePass123!",
            "full_name": "Invalid Email",
        },
    )
    test("Invalid email format rejected", resp.status in (400, 422), f"status={resp.status}")

    # Idempotent update (set same value)
    email_idem = test_email("idempotent")
    ctx.create_user(email_idem, full_name="Idempotent User", is_admin=False)
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email_idem}", {"is_admin": False})
    test("Idempotent update (same value) returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Value unchanged after idempotent update", resp.body.get("is_admin") is False)


def test_last_admin_lockout_prevention(ctx: TestContext):
    """Test 11: Last-admin lockout prevention.

    Strategy: count active admins in the system, then create two test admins
    and demote/deactivate ALL other admins (except the platform admin whose
    token we use) plus one of the two test admins, so the remaining test admin
    is the sole active admin.  Then verify the guard blocks demote/deactivate.
    Finally, restore everything.
    """
    print(f"\n{CYAN}--- 11. Last-Admin Lockout Prevention ---{NC}")

    # --- positive case: demoting a non-last admin ---
    email_a = test_email("guard-a")
    email_b = test_email("guard-b")
    ctx.create_user(email_a, is_admin=True, full_name="Guard Admin A")
    ctx.create_user(email_b, is_admin=True, full_name="Guard Admin B")

    # Demoting A should succeed (B + platform admin still active)
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email_a}", {"is_admin": False})
    test("Demote non-last admin returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Non-last admin demoted", resp.body.get("is_admin") is False)

    # Re-promote A, then deactivate A (different path)
    ctx.api("PATCH", f"/auth/email/admin/users/{email_a}", {"is_admin": True})
    resp = ctx.api("PATCH", f"/auth/email/admin/users/{email_a}", {"is_active": False})
    test("Deactivate non-last admin returns 200", resp.status == 200, f"status={resp.status}")
    if resp.status == 200:
        test("Non-last admin deactivated", resp.body.get("is_active") is False)

    # --- negative case: last-admin guard ---
    # To isolate a single active admin we need to know who else is admin.
    # List all users and find every active admin, then demote all except one
    # test user so we can safely test the guard and restore afterwards.
    resp = ctx.api("GET", "/auth/email/admin/users?limit=0")
    if resp.status != 200 or not isinstance(resp.body, list):
        skip("Demote last admin guard", "could not list users")
        skip("Deactivate last admin guard", "could not list users")
        return

    all_users = resp.body
    active_admins = [u for u in all_users if u.get("is_admin") and u.get("is_active")]
    vprint(f"Active admins before isolation: {len(active_admins)}")

    # We'll make email_b the sole active admin.
    # Reactivate B in case it got touched, ensure admin+active.
    ctx.api("PATCH", f"/auth/email/admin/users/{email_b}", {"is_admin": True, "is_active": True})

    # Demote every OTHER active admin (except email_b) temporarily.
    demoted: list[str] = []
    for u in active_admins:
        uemail = u["email"]
        if uemail == email_b:
            continue
        r = ctx.api("PATCH", f"/auth/email/admin/users/{uemail}", {"is_admin": False})
        if r.status == 200:
            demoted.append(uemail)
            vprint(f"Temporarily demoted {uemail}")

    try:
        # Now email_b should be the sole active admin. Verify the guard.
        resp = ctx.api("PATCH", f"/auth/email/admin/users/{email_b}", {"is_admin": False})
        test("Demote last admin returns 400", resp.status == 400, f"status={resp.status}")
        if resp.status == 400:
            test("Demote error mentions last admin", "last" in resp.body.get("detail", "").lower())

        resp = ctx.api("PATCH", f"/auth/email/admin/users/{email_b}", {"is_active": False})
        test("Deactivate last admin returns 400", resp.status == 400, f"status={resp.status}")
        if resp.status == 400:
            test("Deactivate error mentions last admin", "last" in resp.body.get("detail", "").lower())

        # Verify B is still intact
        resp = ctx.api("GET", f"/auth/email/admin/users/{email_b}")
        if resp.status == 200:
            test("Last admin still active after blocked ops", resp.body.get("is_active") is True)
            test("Last admin still admin after blocked ops", resp.body.get("is_admin") is True)
    finally:
        # Restore all temporarily demoted admins
        for uemail in demoted:
            ctx.api("PATCH", f"/auth/email/admin/users/{uemail}", {"is_admin": True})
            vprint(f"Restored admin: {uemail}")


# ---------------------------------------------------------------------------
# Test group registry
# ---------------------------------------------------------------------------
TEST_GROUPS = {
    "connectivity": test_connectivity,
    "admin-create": test_admin_create,
    "admin-read": test_admin_read,
    "admin-update": test_admin_update_partial,
    "password": test_password_management,
    "login": test_login_flows,
    "self-service": test_self_service,
    "admin-delete": test_admin_delete,
    "registration": test_public_registration,
    "admin-events": test_admin_events,
    "edge-cases": test_edge_cases,
    "lockout-prevention": test_last_admin_lockout_prevention,
}

# Shortcuts that map to multiple groups
TEST_GROUP_ALIASES = {
    "admin-crud": ["admin-create", "admin-read", "admin-update", "admin-delete"],
    "all": list(TEST_GROUPS.keys()),
}


def main():
    global VERBOSE

    parser = argparse.ArgumentParser(
        description="Integration tests for the Email Auth User Management API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test groups:
  connectivity   Health check, auth verification
  admin-create   Admin user creation with various options
  admin-read     Get user, list users, pagination
  admin-update   Partial updates, multi-field, empty body
  password       Password reset, pcr interaction, self-service change
  login          Login flows, inactive user, pcr enforcement
  self-service   /me profile, /events
  admin-delete   Delete user, self-delete prevention
  registration   Public registration security
  admin-events   Admin audit event log
  edge-cases     Long names, invalid email, idempotent updates
  lockout-prevention  Last-admin lockout prevention

Aliases:
  admin-crud     Runs admin-create, admin-read, admin-update, admin-delete
  all            Runs all test groups (default)
""",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--secret", default=DEFAULT_JWT_SECRET, help="JWT signing secret")
    parser.add_argument("--admin-email", default=DEFAULT_ADMIN_EMAIL, help=f"Admin email (default: {DEFAULT_ADMIN_EMAIL})")
    parser.add_argument("--group", nargs="*", default=["all"], help="Test group(s) to run (default: all)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show request/response details")
    args = parser.parse_args()

    VERBOSE = args.verbose

    # Resolve group aliases
    groups_to_run: list[str] = []
    for g in args.group:
        if g in TEST_GROUP_ALIASES:
            groups_to_run.extend(TEST_GROUP_ALIASES[g])
        elif g in TEST_GROUPS:
            groups_to_run.append(g)
        else:
            print(f"{RED}Unknown test group: {g}{NC}")
            print(f"Available: {', '.join(sorted(TEST_GROUPS.keys()))} | Aliases: {', '.join(TEST_GROUP_ALIASES.keys())}")
            sys.exit(2)
    # Deduplicate preserving order
    seen = set()
    groups_to_run = [g for g in groups_to_run if g not in seen and not seen.add(g)]

    # Banner
    print(f"{CYAN}{'=' * 70}{NC}")
    print(f"  Email Auth API Integration Tests")
    print(f"  Target: {args.base_url}")
    print(f"  Groups: {', '.join(groups_to_run)}")
    print(f"{CYAN}{'=' * 70}{NC}")

    ctx = TestContext(args.base_url, args.secret, args.admin_email)

    # Quick connectivity check before running everything
    resp = api("GET", "/health", base_url=args.base_url)
    if resp.status != 200:
        print(f"\n{RED}Cannot reach {args.base_url}/health (status={resp.status}){NC}")
        if resp.error:
            print(f"{RED}{resp.error}{NC}")
        print(f"\nEnsure the gateway is running. Example:")
        print(f"  docker-compose up -d")
        print(f"  make dev")
        sys.exit(1)

    start_time = time.time()

    try:
        for group_name in groups_to_run:
            try:
                TEST_GROUPS[group_name](ctx)
            except Exception:
                print(f"  {RED}ERROR{NC}: Unhandled exception in {group_name}:")
                traceback.print_exc()
                ERRORS.append(f"[{group_name}] unhandled exception")
    finally:
        # Always clean up test users
        if ctx.created_users:
            print(f"\n{DIM}Cleaning up {len(ctx.created_users)} test user(s)...{NC}")
            ctx.cleanup()

    elapsed = time.time() - start_time

    # Summary
    total = PASS_COUNT + FAIL_COUNT
    print(f"\n{CYAN}{'=' * 70}{NC}")
    print(f"  {GREEN}{PASS_COUNT} passed{NC}, ", end="")
    if FAIL_COUNT:
        print(f"{RED}{FAIL_COUNT} failed{NC}, ", end="")
    else:
        print(f"0 failed, ", end="")
    if SKIP_COUNT:
        print(f"{YELLOW}{SKIP_COUNT} skipped{NC}, ", end="")
    print(f"{total} total in {elapsed:.1f}s")
    print(f"{CYAN}{'=' * 70}{NC}")

    if ERRORS:
        print(f"\n{RED}Failed tests:{NC}")
        for e in ERRORS:
            print(f"  - {e}")

    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
