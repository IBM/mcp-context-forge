# -*- coding: utf-8 -*-
# File: tests/unit/mcpgateway/test_validate_env.py
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

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
