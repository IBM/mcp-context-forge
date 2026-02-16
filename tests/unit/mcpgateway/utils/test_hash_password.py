# -*- coding: utf-8 -*-
"""Unit tests for the password hash generation CLI utility."""

# Standard
from unittest.mock import AsyncMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils import hash_password as hash_password_mod


@pytest.mark.asyncio
async def test_generate_hash_uses_argon2_service() -> None:
    """_generate_hash should delegate to Argon2PasswordService.hash_password_async."""
    with patch("mcpgateway.utils.hash_password.Argon2PasswordService") as mock_service_cls:
        mock_service_cls.return_value.hash_password_async = AsyncMock(return_value="argon-hash")

        result = await hash_password_mod._generate_hash("Secret123!")

    assert result == "argon-hash"
    mock_service_cls.return_value.hash_password_async.assert_awaited_once_with("Secret123!")


def _close_coro_and_return(value: str):
    """Return an asyncio.run replacement that closes coroutines and returns a fixed value."""

    def _runner(coro):
        coro.close()
        return value

    return _runner


def test_main_with_password_argument_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main() should hash and print when --password is provided."""
    monkeypatch.setattr(hash_password_mod.sys, "argv", ["hash_password.py", "--password", "Secret123!"])

    with patch("mcpgateway.utils.hash_password.asyncio.run", side_effect=_close_coro_and_return("argon-hash")) as mock_asyncio_run:
        exit_code = hash_password_mod.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "argon-hash"
    assert captured.err == ""
    mock_asyncio_run.assert_called_once()


def test_main_prompt_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main() should prompt for password when missing and succeed on matching values."""
    monkeypatch.setattr(hash_password_mod.sys, "argv", ["hash_password.py"])

    with (
        patch("mcpgateway.utils.hash_password.getpass.getpass", side_effect=["Secret123!", "Secret123!"]),
        patch("mcpgateway.utils.hash_password.asyncio.run", side_effect=_close_coro_and_return("argon-hash")) as mock_asyncio_run,
    ):
        exit_code = hash_password_mod.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "argon-hash"
    assert captured.err == ""
    mock_asyncio_run.assert_called_once()


def test_main_prompt_mismatch_returns_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main() should fail fast when prompted password and confirmation do not match."""
    monkeypatch.setattr(hash_password_mod.sys, "argv", ["hash_password.py"])

    with (
        patch("mcpgateway.utils.hash_password.getpass.getpass", side_effect=["one", "two"]),
        patch("mcpgateway.utils.hash_password.asyncio.run") as mock_asyncio_run,
    ):
        exit_code = hash_password_mod.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Passwords do not match." in captured.err
    mock_asyncio_run.assert_not_called()


def test_main_prompt_empty_password_returns_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main() should reject empty prompted passwords."""
    monkeypatch.setattr(hash_password_mod.sys, "argv", ["hash_password.py"])

    with (
        patch("mcpgateway.utils.hash_password.getpass.getpass", side_effect=["", ""]),
        patch("mcpgateway.utils.hash_password.asyncio.run") as mock_asyncio_run,
    ):
        exit_code = hash_password_mod.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Password cannot be empty." in captured.err
    mock_asyncio_run.assert_not_called()
