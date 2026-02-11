# -*- coding: utf-8 -*-
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
