# -*- coding: utf-8 -*-
"""Location: ./tests/scripts/test_init_secrets.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Eleni Kechrioti

Unit tests for the secrets initialization script.
This module verifies token generation entropy, CLI argument handling,
file system interactions (creation/overwrite), and stdout output.
"""

# Standard
import argparse
from pathlib import Path
import stat
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.scripts.init_secrets import (
    _WEAK_VALUES,
    _merge_env_file,
    _read_env_file,
    ensure_env_file_secrets,
    generate_token,
    main,
)


def test_token_entropy_and_length() -> None:
    """
    Verify that tokens have the correct length and sufficient entropy.

    Checks:
    - 32 bytes input results in 43 chars (URL-safe Base64).
    - 18 bytes input results in 24 chars.
    - Subsequent calls produce different values.
    """
    assert len(generate_token(32)) == 43
    assert len(generate_token(18)) == 24
    # Entropy check
    assert generate_token(32) != generate_token(32)


@patch("os.chmod")
@patch("argparse.ArgumentParser.parse_args")
def test_file_creation(mock_args: MagicMock, mock_chmod: MagicMock, tmp_path: Path) -> None:
    """Verify that the secrets file is created and permissions are set."""
    output_path = tmp_path / "test.env"
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False)

    main()

    assert output_path.exists()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert "JWT_SECRET_KEY=" in output_path.read_text(encoding="utf-8")
    mock_chmod.assert_not_called()


@patch("os.close")
@patch("os.fchmod", side_effect=OSError("permission update failed"))
@patch("os.open", return_value=123)
@patch("argparse.ArgumentParser.parse_args")
def test_write_failure_closes_fd(mock_args: MagicMock, mock_open: MagicMock, mock_fchmod: MagicMock, mock_close: MagicMock) -> None:
    """Verify that a failed secure write closes the raw file descriptor."""
    mock_args.return_value = argparse.Namespace(output="test.env", force=False, stdout=False)

    with pytest.raises(SystemExit) as cm:
        main()

    assert cm.value.code == 1
    mock_open.assert_called_once()
    mock_fchmod.assert_called_once_with(123, 0o600)
    mock_close.assert_called_once_with(123)


@patch("argparse.ArgumentParser.parse_args")
def test_file_exists_error(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    Verify that the command fails if the file already exists without --force.

    Expects a SystemExit with code 1.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False)

    with pytest.raises(SystemExit) as cm:
        main()
    assert cm.value.code == 1
    assert output_path.read_text(encoding="utf-8") == "existing=true\n"


@patch("argparse.ArgumentParser.parse_args")
def test_force_behavior(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    Verify that --force allows overwriting an existing file.

    Ensures the file is opened for writing even if os.path.exists is True.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=True, stdout=False)

    main()

    content = output_path.read_text(encoding="utf-8")
    assert "existing=true" not in content
    assert "AUTH_ENCRYPTION_SECRET=" in content
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


@patch("builtins.print")
@patch("argparse.ArgumentParser.parse_args")
def test_stdout_behavior(mock_args: MagicMock, mock_print: MagicMock) -> None:
    """
    Verify that --stdout prints to console and bypasses file writing.

    Checks that the built-in open is never called when stdout is True.
    """
    mock_args.return_value = argparse.Namespace(output=".env.secrets", force=False, stdout=True)

    main()

    mock_print.assert_called_once()
    assert "JWT_SECRET_KEY=" in mock_print.call_args.args[0]


class TestEnsureEnvFileSecrets:
    """Tests for ensure_env_file_secrets and helpers."""

    # --- _read_env_file ---

    def test_read_env_file_parses_key_value(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=abc\nAUTH_ENCRYPTION_SECRET=xyz\n", encoding="utf-8")
        result = _read_env_file(str(env))
        assert result["JWT_SECRET_KEY"] == "abc"
        assert result["AUTH_ENCRYPTION_SECRET"] == "xyz"

    def test_read_env_file_skips_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\n\nJWT_SECRET_KEY=val\n", encoding="utf-8")
        result = _read_env_file(str(env))
        assert list(result.keys()) == ["JWT_SECRET_KEY"]

    def test_read_env_file_returns_empty_when_missing(self, tmp_path):
        result = _read_env_file(str(tmp_path / "nonexistent.env"))
        assert result == {}

    def test_read_env_file_skips_lines_without_equals(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("export NO_EQUALS_HERE\nJWT_SECRET_KEY=val\n", encoding="utf-8")
        result = _read_env_file(str(env))
        assert list(result.keys()) == ["JWT_SECRET_KEY"]
        assert "NO_EQUALS_HERE" not in result

    # --- _merge_env_file ---

    def test_merge_env_file_updates_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=weak\nOTHER=keep\n", encoding="utf-8")
        _merge_env_file(str(env), {"JWT_SECRET_KEY": "strong-new-value"})
        content = env.read_text(encoding="utf-8")
        assert "JWT_SECRET_KEY=strong-new-value" in content
        assert "OTHER=keep" in content
        assert "weak" not in content

    def test_merge_env_file_appends_missing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("EXISTING=yes\n", encoding="utf-8")
        _merge_env_file(str(env), {"JWT_SECRET_KEY": "brand-new"})
        content = env.read_text(encoding="utf-8")
        assert "JWT_SECRET_KEY=brand-new" in content
        assert "EXISTING=yes" in content

    def test_merge_env_file_creates_file_when_missing(self, tmp_path):
        env = tmp_path / ".env"
        _merge_env_file(str(env), {"JWT_SECRET_KEY": "first"})
        assert env.exists()
        assert "JWT_SECRET_KEY=first" in env.read_text(encoding="utf-8")

    def test_merge_env_file_sets_permissions_0o600(self, tmp_path):
        import stat

        env = tmp_path / ".env"
        _merge_env_file(str(env), {"JWT_SECRET_KEY": "val"})
        assert stat.S_IMODE(env.stat().st_mode) == 0o600

    def test_merge_env_file_closes_fd_on_fdopen_failure(self, tmp_path):
        """os.close(fd) is called when os.fdopen raises before ownership transfer."""
        import os
        from unittest.mock import patch, call

        env = tmp_path / ".env"
        fake_fd = 99
        with patch("os.open", return_value=fake_fd) as mock_open, patch("os.fchmod"), patch("os.fdopen", side_effect=OSError("fdopen failed")), patch("os.close") as mock_close:
            with pytest.raises(OSError, match="fdopen failed"):
                _merge_env_file(str(env), {"JWT_SECRET_KEY": "val"})
            mock_close.assert_called_once_with(fake_fd)

    # --- ensure_env_file_secrets ---

    def test_ensure_generates_when_weak(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated
        assert "AUTH_ENCRYPTION_SECRET" in generated
        assert len(generated["JWT_SECRET_KEY"]) == 43  # 32-byte token_urlsafe

    def test_ensure_patches_os_environ(self, tmp_path, monkeypatch):
        import os as _os

        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert _os.environ.get("JWT_SECRET_KEY") == generated["JWT_SECRET_KEY"]

    def test_ensure_writes_to_env_file(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        content = env.read_text(encoding="utf-8")
        assert f"JWT_SECRET_KEY={generated['JWT_SECRET_KEY']}" in content

    def test_ensure_skips_strong_secrets(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        strong = "x3Kp_mQ8rZvN2wLsA5dYfB7cEjGhTuIo_X3K"  # pragma: allowlist secret
        env.write_text(f"JWT_SECRET_KEY={strong}\nAUTH_ENCRYPTION_SECRET={strong}\n", encoding="utf-8")  # pragma: allowlist secret
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert generated == {}

    def test_ensure_respects_os_environ_override(self, tmp_path, monkeypatch):
        """os.environ takes priority over .env file — if strong in os.environ, skip."""
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")  # pragma: allowlist secret
        strong = "x3Kp_mQ8rZvN2wLsA5dYfB7cEjGhTuIo_X3K"  # pragma: allowlist secret
        monkeypatch.setenv("JWT_SECRET_KEY", strong)
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", strong)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert generated == {}

    def test_ensure_disabled_by_env_var(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "false")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert generated == {}

    def test_ensure_blocks_replace_me_placeholder(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text(
            "JWT_SECRET_KEY=__REPLACE_ME__run_init-secrets\n" "AUTH_ENCRYPTION_SECRET=__REPLACE_ME__run_init-secrets\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated
        assert "AUTH_ENCRYPTION_SECRET" in generated

    def test_ensure_creates_env_file_when_missing(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert env.exists()
        assert "JWT_SECRET_KEY" in generated

    # --- F2 regression: all WEAK_VALUES must trigger regeneration ---

    @pytest.mark.parametrize("weak", sorted(_WEAK_VALUES))
    def test_ensure_regenerates_every_weak_value(self, tmp_path, monkeypatch, weak):
        env = tmp_path / ".env"
        env.write_text(f"JWT_SECRET_KEY={weak}\nAUTH_ENCRYPTION_SECRET={weak}\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated

    # --- F3 regression: quoted weak values must be detected ---

    def test_read_env_file_strips_double_quotes(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('JWT_SECRET_KEY="changeme"\n', encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"

    def test_read_env_file_strips_single_quotes(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY='changeme'\n", encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"

    def test_ensure_regenerates_quoted_weak_value(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text('JWT_SECRET_KEY="changeme"\nAUTH_ENCRYPTION_SECRET="changeme"\n', encoding="utf-8")  # pragma: allowlist secret
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated

    # --- F4 regression: os.environ-only weak values must not write to .env ---

    def test_ensure_does_not_write_env_for_environ_only_weak(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("OTHER=keep\n", encoding="utf-8")
        monkeypatch.setenv("JWT_SECRET_KEY", "changeme")
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated
        content = env.read_text(encoding="utf-8")
        assert "JWT_SECRET_KEY" not in content

    # --- F6 regression: parser edge cases ---

    def test_read_env_file_handles_export_prefix(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("export JWT_SECRET_KEY=changeme\n", encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"

    def test_read_env_file_strips_inline_comment(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme # generated\n", encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"
