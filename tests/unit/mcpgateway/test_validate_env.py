# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_validate_env.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Module Description.
Module documentation...
"""

# File: tests/unit/mcpgateway/test_validate_env.py
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

# Import the validate_env script directly
from mcpgateway.scripts import validate_env as ve

# Suppress mcpgateway.config logs during tests
logging.getLogger("mcpgateway.config").setLevel(logging.ERROR)


@pytest.fixture
def valid_env(tmp_path: Path) -> Path:
    envfile = tmp_path / ".env"
    envfile.write_text(
        "APP_DOMAIN=http://localhost:8000\n"
        "PORT=8080\n"
        "LOG_LEVEL=info\n"
        "PLATFORM_ADMIN_PASSWORD=V7g!3Rf$Tz9&Lp2@Kq1Xh5Jm8Nc0YsR4\n"
        "BASIC_AUTH_USER=admin\n"
        "BASIC_AUTH_PASSWORD=V9r$2Tx!Bf8&kZq@3LpC#7Jm6Nh1UoR0\n"
        "JWT_SECRET_KEY=Z9x!3Tp#Rk8&Vm4Yq$2Lf6Jb0Nw1AoS5DdGh7KuCvBzPmY\n"
        "AUTH_ENCRYPTION_SECRET=Q2w@8Er#Tz5&Ui6Oy$1Lp0Kb7Nh3Xc9Vj4AmF2GsYmCvBnD\n"
    )
    return envfile


@pytest.fixture
def invalid_env(tmp_path: Path) -> Path:
    envfile = tmp_path / ".env"
    # Invalid URL + wrong log level + invalid port
    envfile.write_text("APP_DOMAIN=not-a-url\nPORT=-1\nLOG_LEVEL=wronglevel\n")
    return envfile


def test_validate_env_success_direct(valid_env: Path) -> None:
    """
    Test a valid .env. Warnings will be printed but do NOT fail the test.
    """
    # Clear any cached settings to ensure test isolation
    from mcpgateway.config import get_settings

    get_settings.cache_clear()

    # Clear environment variables that might interfere
    env_vars_to_clear = ["APP_DOMAIN", "PORT", "LOG_LEVEL", "PLATFORM_ADMIN_PASSWORD", "BASIC_AUTH_PASSWORD", "JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET"]

    with patch.dict(os.environ, {}, clear=False):
        for var in env_vars_to_clear:
            os.environ.pop(var, None)

        code = ve.main(env_file=str(valid_env), exit_on_warnings=False)
        assert code == 0


def test_validate_env_failure_direct(invalid_env: Path) -> None:
    """
    Test an invalid .env. Should fail due to ValidationError.
    """
    # Clear any cached settings to ensure test isolation
    from mcpgateway.config import get_settings

    get_settings.cache_clear()

    # Clear environment variables that might interfere
    env_vars_to_clear = ["APP_DOMAIN", "PORT", "LOG_LEVEL", "PLATFORM_ADMIN_PASSWORD", "BASIC_AUTH_PASSWORD", "JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET"]

    with patch.dict(os.environ, {}, clear=False):
        for var in env_vars_to_clear:
            os.environ.pop(var, None)

        print("Invalid env path:", invalid_env)
        code = ve.main(env_file=str(invalid_env), exit_on_warnings=False)
        print("Returned code:", code)
        assert code != 0


def test_get_security_warnings_flags_short_basic_password() -> None:
    class _Settings:
        port = 8080
        password_min_length = 8
        platform_admin_password = SecretStr("Str0ng!AdminPass")
        basic_auth_password = SecretStr("Ab1!")
        jwt_secret_key = SecretStr("Ab1!Cd2@Ef3#Gh4$Ij5%Kl6^Mn7&Op8*")
        auth_encryption_secret = SecretStr("Qr1!St2@Uv3#Wx4$Yz5%Aa6^Bb7&Cc8*")
        app_domain = "https://example.com"

    warnings = ve.get_security_warnings(_Settings())  # type: ignore[arg-type]

    assert any("BASIC_AUTH_PASSWORD should be at least 8 characters long" in w for w in warnings)


def test_validate_env_warning_path_nonprod_exit_on_warnings_false(tmp_path: Path, capsys) -> None:
    from mcpgateway.config import get_settings

    get_settings.cache_clear()

    envfile = tmp_path / ".env"
    envfile.write_text(
        "ENVIRONMENT=development\n"
        "APP_DOMAIN=https://example.com\n"
        "PORT=8080\n"
        "LOG_LEVEL=info\n"
        "PLATFORM_ADMIN_PASSWORD=V7g!3Rf$Tz9&Lp2@Kq1Xh5Jm8Nc0YsR4\n"
        "BASIC_AUTH_USER=admin\n"
        "BASIC_AUTH_PASSWORD=Ab1!\n"
        "JWT_SECRET_KEY=Z9x!3Tp#Rk8&Vm4Yq$2Lf6Jb0Nw1AoS5DdGh7KuCvBzPmY\n"
        "AUTH_ENCRYPTION_SECRET=Q2w@8Er#Tz5&Ui6Oy$1Lp0Kb7Nh3Xc9Vj4AmF2GsYmCvBnD\n"
    )

    with patch.dict(os.environ, {}, clear=False):
        for var in ["ENVIRONMENT", "APP_DOMAIN", "PORT", "LOG_LEVEL", "PLATFORM_ADMIN_PASSWORD", "BASIC_AUTH_PASSWORD", "JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET"]:
            os.environ.pop(var, None)

        code = ve.main(env_file=str(envfile), exit_on_warnings=False)

    out = capsys.readouterr().out
    assert code == 0
    assert "Warnings detected, but continuing in non-production environment." in out


def test_validate_env_warning_path_exit_on_warnings_true(tmp_path: Path) -> None:
    from mcpgateway.config import get_settings

    get_settings.cache_clear()

    envfile = tmp_path / ".env"
    envfile.write_text(
        "ENVIRONMENT=development\n"
        "APP_DOMAIN=https://example.com\n"
        "PORT=8080\n"
        "LOG_LEVEL=info\n"
        "PLATFORM_ADMIN_PASSWORD=V7g!3Rf$Tz9&Lp2@Kq1Xh5Jm8Nc0YsR4\n"
        "BASIC_AUTH_USER=admin\n"
        "BASIC_AUTH_PASSWORD=Ab1!\n"
        "JWT_SECRET_KEY=Z9x!3Tp#Rk8&Vm4Yq$2Lf6Jb0Nw1AoS5DdGh7KuCvBzPmY\n"
        "AUTH_ENCRYPTION_SECRET=Q2w@8Er#Tz5&Ui6Oy$1Lp0Kb7Nh3Xc9Vj4AmF2GsYmCvBnD\n"
    )

    with patch.dict(os.environ, {}, clear=False):
        for var in ["ENVIRONMENT", "APP_DOMAIN", "PORT", "LOG_LEVEL", "PLATFORM_ADMIN_PASSWORD", "BASIC_AUTH_PASSWORD", "JWT_SECRET_KEY", "AUTH_ENCRYPTION_SECRET"]:
            os.environ.pop(var, None)

        code = ve.main(env_file=str(envfile), exit_on_warnings=True)

    assert code == 1


def test_get_security_warnings_flags_short_jwt_secret() -> None:
    """validate_env.py line 161: JWT_SECRET_KEY shorter than effective_min triggers a length warning.

    Constructs a mock settings object where jwt_secret_key is 10 chars (not in WEAK_VALUES,
    so the weak-name branch on line 157 does NOT fire) but below the 32-char floor
    (line 160 condition is True).  This covers the previously-uncovered branch at line 161.
    """
    from pydantic import SecretStr  # already imported at module level, but explicit is fine

    class _Settings:
        port = 8080
        password_min_length = 8
        platform_admin_password = SecretStr("Str0ng!AdminPass")
        basic_auth_password = SecretStr("Complex!Pass99")
        # 10 chars, not in WEAK_VALUES (so not caught by line 157), but < 32 (line 160 fires)
        jwt_secret_key = SecretStr("abcdefghij")  # nosec B106
        auth_encryption_secret = SecretStr("Qr1!St2@Uv3#Wx4$Yz5%Aa6^Bb7&Cc8*")
        app_domain = "https://example.com"
        min_secret_length = 32

    warnings = ve.get_security_warnings(_Settings())  # type: ignore[arg-type]

    assert any("JWT_SECRET_KEY" in w and "at least" in w for w in warnings), (
        f"Expected JWT length warning, got: {warnings}"
    )


def test_get_security_warnings_flags_short_auth_encryption_secret() -> None:
    """validate_env.py line 172: AUTH_ENCRYPTION_SECRET shorter than effective_min triggers a length warning.

    Constructs a mock settings object where auth_encryption_secret is 10 chars (not in
    WEAK_VALUES, so line 168 does NOT fire) but below the 32-char floor (line 171 fires).
    This covers the previously-uncovered branch at line 172.
    """
    from pydantic import SecretStr

    class _Settings:
        port = 8080
        password_min_length = 8
        platform_admin_password = SecretStr("Str0ng!AdminPass")
        basic_auth_password = SecretStr("Complex!Pass99")
        jwt_secret_key = SecretStr("a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p")  # nosec B106 # pragma: allowlist secret
        # 10 chars, not in WEAK_VALUES (so line 168 does not fire), but < 32 (line 171 fires)
        auth_encryption_secret = SecretStr("abcdefghij")  # nosec B106
        app_domain = "https://example.com"
        min_secret_length = 32

    warnings = ve.get_security_warnings(_Settings())  # type: ignore[arg-type]

    assert any("AUTH_ENCRYPTION_SECRET" in w and "at least" in w for w in warnings), (
        f"Expected AUTH_ENCRYPTION_SECRET length warning, got: {warnings}"
    )
