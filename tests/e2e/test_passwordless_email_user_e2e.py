# -*- coding: utf-8 -*-
"""Location: ./tests/e2e/test_passwordless_email_user_e2e.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Single-instance E2E coverage for passwordless email users.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import io
from typing import AsyncGenerator, Generator
from urllib.parse import quote
import uuid

# Third-Party
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.auth_user_helpers import PASSWORDLESS_HASH_TYPE
from mcpgateway.config import get_settings, settings
from mcpgateway.db import EmailUser, PasswordResetToken, utc_now
from mcpgateway.routers import email_auth as email_auth_router_mod
from mcpgateway.services.email_auth_service import EmailAuthService

pytestmark = pytest.mark.e2e

TEST_JWT_SECRET = "passwordless-e2e-jwt-secret-with-minimum-32-bytes"  # pragma: allowlist secret
TEST_AUTH_ENCRYPTION_SECRET = "passwordless-e2e-auth-encryption-secret-with-minimum-32-bytes"  # pragma: allowlist secret
ADMIN_PASSWORD = "AdminPass123!"  # pragma: allowlist secret
TARGET_PASSWORD = "TargetPass123!"  # pragma: allowlist secret
NEW_PASSWORD = "NewTargetPass123!"  # pragma: allowlist secret
STALE_RESET_TOKEN = "stale-reset-token-for-passwordless-e2e"  # pragma: allowlist secret


@dataclass
class PasswordlessE2EContext:
    """State shared by the single-instance passwordless E2E test."""

    app: FastAPI
    session_factory: sessionmaker[Session]
    admin_email: str
    target_email: str


@pytest.fixture
def passwordless_e2e_context(tmp_path, monkeypatch) -> Generator[PasswordlessE2EContext, None, None]:
    """Create a migrated SQLite app instance with the real email auth router."""
    db_url = f"sqlite:///{tmp_path / 'passwordless-e2e.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", TEST_AUTH_ENCRYPTION_SECRET)
    monkeypatch.setenv("EMAIL_AUTH_ENABLED", "true")
    monkeypatch.setenv("PASSWORD_RESET_ENABLED", "true")
    monkeypatch.setenv("MCPGATEWAY_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MCPGATEWAY_UI_ENABLED", "true")
    monkeypatch.setenv("PLUGINS_ENABLED", "false")
    monkeypatch.setenv("LLMCHAT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING_ENABLED", "false")

    get_settings.cache_clear()
    monkeypatch.setattr(settings, "database_url", db_url, raising=False)
    monkeypatch.setattr(settings, "jwt_secret_key", SecretStr(TEST_JWT_SECRET), raising=False)
    monkeypatch.setattr(settings, "auth_encryption_secret", SecretStr(TEST_AUTH_ENCRYPTION_SECRET), raising=False)
    monkeypatch.setattr(settings, "email_auth_enabled", True, raising=False)
    monkeypatch.setattr(settings, "password_reset_enabled", True, raising=False)
    monkeypatch.setattr(settings, "password_reset_min_response_ms", 0, raising=False)
    monkeypatch.setattr(settings, "password_policy_enabled", False, raising=False)
    monkeypatch.setattr(settings, "password_change_enforcement_enabled", False, raising=False)
    monkeypatch.setattr(settings, "auto_create_personal_teams", False, raising=False)
    monkeypatch.setattr(settings, "auth_cache_enabled", False, raising=False)
    monkeypatch.setattr(settings, "auth_cache_batch_queries", False, raising=False)
    monkeypatch.setattr(settings, "token_idle_timeout", 0, raising=False)
    monkeypatch.setattr(settings, "plugins_enabled", False, raising=False)
    monkeypatch.setattr(settings, "require_user_in_db", True, raising=False)

    alembic_cfg = Config("mcpgateway/alembic.ini")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        command.upgrade(alembic_cfg, "head")

    engine = create_engine(db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    test_session_factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    # Patch module-level session factories imported by the router/auth/RBAC stack.
    # First-Party
    import mcpgateway.auth as auth_mod
    import mcpgateway.cache.auth_cache as auth_cache_mod
    import mcpgateway.db as db_mod
    import mcpgateway.middleware.rbac as rbac_mod

    monkeypatch.setattr(db_mod, "engine", engine, raising=False)
    monkeypatch.setattr(db_mod, "SessionLocal", test_session_factory, raising=False)
    monkeypatch.setattr(email_auth_router_mod, "SessionLocal", test_session_factory, raising=False)
    monkeypatch.setattr(auth_mod, "SessionLocal", test_session_factory, raising=False)
    monkeypatch.setattr(auth_cache_mod.auth_cache, "_enabled", False, raising=False)
    monkeypatch.setattr(rbac_mod, "SessionLocal", test_session_factory, raising=False)

    admin_email = f"passwordless-admin-{uuid.uuid4().hex}@example.com"
    target_email = f"passwordless-target-{uuid.uuid4().hex}@example.com"
    with test_session_factory() as db:
        auth_service = EmailAuthService(db)
        db.add_all(
            [
                EmailUser(
                    email=admin_email,
                    password_hash=auth_service.password_service.hash_password(ADMIN_PASSWORD),
                    full_name="Passwordless E2E Admin",
                    is_admin=True,
                    is_active=True,
                    email_verified_at=utc_now(),
                ),
                EmailUser(
                    email=target_email,
                    password_hash=auth_service.password_service.hash_password(TARGET_PASSWORD),
                    full_name="Passwordless E2E Target",
                    is_admin=False,
                    is_active=True,
                    email_verified_at=utc_now(),
                ),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(email_auth_router_mod.email_auth_router, prefix="/auth/email")

    try:
        yield PasswordlessE2EContext(app=app, session_factory=test_session_factory, admin_email=admin_email, target_email=target_email)
    finally:
        engine.dispose()


def _make_target_passwordless(ctx: PasswordlessE2EContext) -> None:
    """Convert the target user to the passwordless state this PR supports."""
    with ctx.session_factory() as db:
        target = db.execute(select(EmailUser).where(EmailUser.email == ctx.target_email)).scalar_one()
        target.password_hash = None
        target.password_hash_type = PASSWORDLESS_HASH_TYPE
        db.commit()


def _insert_stale_reset_token(ctx: PasswordlessE2EContext) -> None:
    """Insert a valid outstanding reset token that must not localize a passwordless user."""
    with ctx.session_factory() as db:
        token_hash = hashlib.sha256(STALE_RESET_TOKEN.encode("utf-8")).hexdigest()
        db.add(
            PasswordResetToken(
                user_email=ctx.target_email,
                token_hash=token_hash,
                expires_at=utc_now() + timedelta(minutes=30),
                ip_address="127.0.0.1",
                user_agent="passwordless-e2e",
            )
        )
        db.commit()


def _get_target_user(ctx: PasswordlessE2EContext) -> EmailUser:
    """Fetch the target user from the E2E database."""
    with ctx.session_factory() as db:
        return db.execute(select(EmailUser).where(EmailUser.email == ctx.target_email)).scalar_one()


def _get_reset_tokens(ctx: PasswordlessE2EContext) -> list[PasswordResetToken]:
    """Fetch target reset tokens from the E2E database."""
    with ctx.session_factory() as db:
        return list(db.execute(select(PasswordResetToken).where(PasswordResetToken.user_email == ctx.target_email)).scalars().all())


@pytest_asyncio.fixture
async def passwordless_client(passwordless_e2e_context: PasswordlessE2EContext) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP client bound to the single in-process E2E app."""
    transport = ASGITransport(app=passwordless_e2e_context.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_passwordless_user_local_password_flows_fail_closed(passwordless_e2e_context: PasswordlessE2EContext, passwordless_client: AsyncClient) -> None:
    """Passwordless users cannot use or regain local password credentials over HTTP."""
    target_login = await passwordless_client.post("/auth/email/login", json={"email": passwordless_e2e_context.target_email, "password": TARGET_PASSWORD})
    assert target_login.status_code == 200
    target_access_token = target_login.json()["access_token"]

    admin_login = await passwordless_client.post("/auth/email/login", json={"email": passwordless_e2e_context.admin_email, "password": ADMIN_PASSWORD})
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    _make_target_passwordless(passwordless_e2e_context)

    denied_login = await passwordless_client.post("/auth/email/login", json={"email": passwordless_e2e_context.target_email, "password": TARGET_PASSWORD})
    assert denied_login.status_code == 401
    assert denied_login.json()["detail"] == "Invalid email or password"

    forgot_password = await passwordless_client.post("/auth/email/forgot-password", json={"email": passwordless_e2e_context.target_email})
    assert forgot_password.status_code == 200
    assert forgot_password.json()["message"] == "If this email is registered, you will receive a reset link."
    assert _get_reset_tokens(passwordless_e2e_context) == []

    _insert_stale_reset_token(passwordless_e2e_context)
    reset_password = await passwordless_client.post(f"/auth/email/reset-password/{STALE_RESET_TOKEN}", json={"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})
    assert reset_password.status_code == 400
    assert reset_password.json()["detail"] == "This reset link is invalid"
    reset_tokens = _get_reset_tokens(passwordless_e2e_context)
    assert len(reset_tokens) == 1
    assert reset_tokens[0].used_at is not None

    change_password = await passwordless_client.post(
        "/auth/email/change-password",
        json={"old_password": TARGET_PASSWORD, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {target_access_token}"},
    )
    assert change_password.status_code == 401
    assert change_password.json()["detail"] == "Current password is incorrect"

    admin_update = await passwordless_client.patch(
        f"/auth/email/admin/users/{quote(passwordless_e2e_context.target_email, safe='')}",
        json={"password": NEW_PASSWORD},
        headers=admin_headers,
    )
    assert admin_update.status_code == 400
    assert admin_update.json()["detail"] == "Local password updates are not allowed for passwordless users"

    target = _get_target_user(passwordless_e2e_context)
    assert target.password_hash is None
    assert target.password_hash_type == PASSWORDLESS_HASH_TYPE
