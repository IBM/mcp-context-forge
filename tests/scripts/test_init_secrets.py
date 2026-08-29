# -*- coding: utf-8 -*-
"""Location: ./tests/scripts/test_init_secrets.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

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
from mcpgateway._security_constants import calculate_entropy
from mcpgateway.scripts.init_secrets import (
    _WEAK_VALUES,
    _is_strong_value,
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
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False, patch=None, patch_env=None)

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
    mock_args.return_value = argparse.Namespace(output="test.env", force=False, stdout=False, patch=None, patch_env=None)

    with pytest.raises(SystemExit) as cm:
        main()

    assert cm.value.code == 1
    mock_open.assert_called_once()
    mock_fchmod.assert_called_once_with(123, 0o600)
    mock_close.assert_called_once_with(123)


@patch("argparse.ArgumentParser.parse_args")
def test_file_exists_prompt_decline(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    When the output file already exists and the user declines the overwrite prompt,
    the command must exit 0 and leave the existing file unchanged.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False, patch=None, patch_env=None)

    with patch("mcpgateway.scripts.init_secrets._prompt_overwrite", return_value=False):
        with pytest.raises(SystemExit) as cm:
            main()
    assert cm.value.code == 0
    assert output_path.read_text(encoding="utf-8") == "existing=true\n"


@patch("argparse.ArgumentParser.parse_args")
def test_file_exists_prompt_accept(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    When the output file already exists and the user accepts the overwrite prompt,
    the file must be overwritten with new secrets.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=False, stdout=False, patch=None, patch_env=None)

    with patch("mcpgateway.scripts.init_secrets._prompt_overwrite", return_value=True):
        main()
    content = output_path.read_text(encoding="utf-8")
    assert "existing=true" not in content
    assert "JWT_SECRET_KEY=" in content


@patch("argparse.ArgumentParser.parse_args")
def test_force_behavior(mock_args: MagicMock, tmp_path: Path) -> None:
    """
    Verify that --force allows overwriting an existing file.

    Ensures the file is opened for writing even if os.path.exists is True.
    """
    output_path = tmp_path / ".env.secrets"
    output_path.write_text("existing=true\n", encoding="utf-8")
    mock_args.return_value = argparse.Namespace(output=str(output_path), force=True, stdout=False, patch=None, patch_env=None)

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
    mock_args.return_value = argparse.Namespace(output=".env.secrets", force=False, stdout=True, patch=None, patch_env=None)

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

    def test_weak_env_var_strong_env_file_raises_for_rotation_guarded_field(self, tmp_path, monkeypatch):
        """Weak shell var + strong .env must raise, not silently overwrite AES key.

        Regression test for the data-loss defect where ensure_env_file_secrets()
        evaluated os.environ precedence first (current = env_val = weak), detected
        is_non_compliant=True, then fell through to file_generated because
        field IN env_file_values — silently overwriting the strong .env value with a
        freshly generated key.  For AUTH_ENCRYPTION_SECRET that rotation makes every
        stored encrypted credential permanently unreadable.
        """
        strong = "x3Kp_mQ8rZvN2wLsA5dYfB7cEjGhTuIo_X3K"  # pragma: allowlist secret
        env = tmp_path / ".env"
        env.write_text(f"AUTH_ENCRYPTION_SECRET={strong}\n", encoding="utf-8")  # pragma: allowlist secret
        # Shell carries a weak / non-compliant value for the guarded field.
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")  # pragma: allowlist secret
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with pytest.raises(ValueError, match="AUTH_ENCRYPTION_SECRET"):
            ensure_env_file_secrets(env_file=str(env))

        # The .env file must be unchanged — the strong key must not have been rotated.
        content = env.read_text(encoding="utf-8")
        assert strong in content

    def test_weak_env_var_short_env_file_value_raises_for_rotation_guarded_field(self, tmp_path, monkeypatch):
        """Weak shell var + ANY pre-existing .env value must raise for rotation-guarded fields.

        A short-but-non-default value in .env (e.g. ``abcd`` — not in WEAK_VALUES, not a
        placeholder, but only 4 chars) must still block rotation.  The guard condition is
        ``(_env_file_ci.get(field.lower()) or "").strip()`` — any non-empty pre-existing
        .env value blocks auto-rotation, not only values that pass the full strength predicate.
        """
        short_non_default = "abcd"  # nosec B105  # pragma: allowlist secret
        env = tmp_path / ".env"
        env.write_text(f"AUTH_ENCRYPTION_SECRET={short_non_default}\n", encoding="utf-8")  # pragma: allowlist secret
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")  # pragma: allowlist secret
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with pytest.raises(ValueError, match="AUTH_ENCRYPTION_SECRET"):
            ensure_env_file_secrets(env_file=str(env))

        # The .env file must be unchanged — the short value must not have been rotated.
        content = env.read_text(encoding="utf-8")
        assert short_non_default in content

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

    def test_ensure_writes_strong_fields_to_env_even_when_weak_value_from_environ(self, tmp_path, monkeypatch):
        """Strong fields (JWT_SECRET_KEY, AUTH_ENCRYPTION_SECRET) with a weak value in os.environ
        and absent from .env must be written to .env so the value survives process exit.
        Only non-strong fields (BASIC_AUTH_PASSWORD) stay environ-only to avoid shadowing
        container env-var injections."""
        env = tmp_path / ".env"
        env.write_text("OTHER=keep\n", encoding="utf-8")
        monkeypatch.setenv("JWT_SECRET_KEY", "changeme")
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated
        content = env.read_text(encoding="utf-8")
        # Strong fields must be persisted — a CLI process exits after patching so
        # an os.environ-only write would be silently lost.
        assert f"JWT_SECRET_KEY={generated['JWT_SECRET_KEY']}" in content
        assert f"AUTH_ENCRYPTION_SECRET={generated['AUTH_ENCRYPTION_SECRET']}" in content
        assert "OTHER=keep" in content

    # --- F6 regression: parser edge cases ---

    def test_read_env_file_handles_export_prefix(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("export JWT_SECRET_KEY=changeme\n", encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"

    def test_read_env_file_strips_inline_comment(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme # generated\n", encoding="utf-8")
        assert _read_env_file(str(env))["JWT_SECRET_KEY"] == "changeme"

    def test_merge_env_file_case_insensitive_key_replaced_in_place(self, tmp_path):
        """Regression: lowercase key in .env must be replaced in-place, not duplicated."""
        env = tmp_path / ".env"
        env.write_text("auth_encryption_secret=weak\nOTHER=keep\n", encoding="utf-8")
        _merge_env_file(str(env), {"AUTH_ENCRYPTION_SECRET": "strong-new-value-here-long-enough"})
        content = env.read_text(encoding="utf-8")
        # The weak lowercase line must be gone; the strong value written with canonical casing
        assert "weak" not in content
        assert "AUTH_ENCRYPTION_SECRET=strong-new-value-here-long-enough" in content
        # No duplication: key must appear exactly once
        assert content.count("ENCRYPTION_SECRET=") == 1
        assert "OTHER=keep" in content

    def test_ensure_respects_min_secret_length_env_var(self, tmp_path, monkeypatch):
        """Regression: MIN_SECRET_LENGTH=64 must result in a generated token >= 64 chars."""
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")
        monkeypatch.setenv("MIN_SECRET_LENGTH", "64")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "JWT_SECRET_KEY" in generated
        assert len(generated["JWT_SECRET_KEY"]) >= 64, (
            f"Expected token >= 64 chars with MIN_SECRET_LENGTH=64, got {len(generated['JWT_SECRET_KEY'])}"
        )
        assert "AUTH_ENCRYPTION_SECRET" in generated
        assert len(generated["AUTH_ENCRYPTION_SECRET"]) >= 64

    def test_ensure_reads_min_secret_length_from_env_file(self, tmp_path, monkeypatch):
        """Regression: MIN_SECRET_LENGTH=64 in .env (not os.environ) must size the token correctly."""
        env = tmp_path / ".env"
        env.write_text(
            "JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\nMIN_SECRET_LENGTH=64\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.delenv("MIN_SECRET_LENGTH", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert len(generated["JWT_SECRET_KEY"]) >= 64, (
            f"Expected ≥64 chars with MIN_SECRET_LENGTH=64 in .env, got {len(generated['JWT_SECRET_KEY'])}"
        )
        assert len(generated["AUTH_ENCRYPTION_SECRET"]) >= 64

    def test_ensure_invalid_min_secret_length_raises_value_error(self, tmp_path, monkeypatch):
        """Non-numeric MIN_SECRET_LENGTH produces a clear ValueError, not a cryptic int() traceback."""
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nMIN_SECRET_LENGTH=abc\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("MIN_SECRET_LENGTH", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with pytest.raises(ValueError, match="MIN_SECRET_LENGTH="):
            ensure_env_file_secrets(env_file=str(env))

    def test_ensure_min_secret_length_below_floor_raises_value_error(self, tmp_path, monkeypatch):
        """Regression: MIN_SECRET_LENGTH=0 must raise ValueError with an actionable message,
        not silently clamp and produce a token that Settings() then rejects."""
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\nMIN_SECRET_LENGTH=0\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.delenv("MIN_SECRET_LENGTH", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with pytest.raises(ValueError, match="below the enforced minimum"):
            ensure_env_file_secrets(env_file=str(env))

    def test_ensure_strong_field_weak_in_environ_writes_to_env_file(self, tmp_path, monkeypatch):
        """Regression: weak AUTH_ENCRYPTION_SECRET in os.environ (absent from .env) must be
        written to .env, not discarded into the subprocess environ and silently lost."""
        env = tmp_path / ".env"
        # .env exists but does not contain AUTH_ENCRYPTION_SECRET
        env.write_text("JWT_SECRET_KEY=changeme\n", encoding="utf-8")
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        generated = ensure_env_file_secrets(env_file=str(env))

        assert "AUTH_ENCRYPTION_SECRET" in generated
        # The value must be persisted to .env, not just os.environ
        content = env.read_text(encoding="utf-8")
        assert f"AUTH_ENCRYPTION_SECRET={generated['AUTH_ENCRYPTION_SECRET']}" in content


class TestMainPatchEnv:
    """Tests for the --patch-env branch of main()."""

    def test_patch_env_generates_and_prints_success(self, tmp_path, monkeypatch, capsys):
        """--patch-env with a weak .env prints a ✅ message and updates the file."""
        env = tmp_path / ".env"
        env.write_text("JWT_SECRET_KEY=changeme\nAUTH_ENCRYPTION_SECRET=changeme\n", encoding="utf-8")
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with patch("argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                output=None, force=False, stdout=False, patch=None, patch_env=str(env)
            )
            main()

        out = capsys.readouterr().out
        assert "✅" in out
        assert "JWT_SECRET_KEY" in out or "AUTH_ENCRYPTION_SECRET" in out
        # The weak values must be gone from the file
        content = env.read_text(encoding="utf-8")
        assert "changeme" not in content

    def test_patch_env_no_op_when_already_strong(self, tmp_path, monkeypatch, capsys):
        """--patch-env with an already-strong .env prints ℹ️ and makes no changes."""
        strong = "a" * 8 + "B" * 8 + "1" * 8 + "!" * 8  # 32 chars, mixed entropy
        # Use a high-entropy value that passes the entropy gate
        import secrets as _secrets
        strong = _secrets.token_urlsafe(32)
        env = tmp_path / ".env"
        env.write_text(
            f"JWT_SECRET_KEY={strong}\nAUTH_ENCRYPTION_SECRET={strong}\nBASIC_AUTH_PASSWORD={strong}\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        monkeypatch.delenv("AUTH_ENCRYPTION_SECRET", raising=False)
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")
        original = env.read_text(encoding="utf-8")

        with patch("argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                output=None, force=False, stdout=False, patch=None, patch_env=str(env)
            )
            main()

        out = capsys.readouterr().out
        assert "ℹ️" in out
        assert env.read_text(encoding="utf-8") == original


    def test_patch_env_value_error_exits_1(self, tmp_path, monkeypatch, capsys):
        """--patch-env must exit 1 with a clean message when ensure_env_file_secrets raises ValueError.

        Covers init_secrets.py lines 384-386: the except ValueError branch in the
        --patch-env section of main().
        """
        env = tmp_path / ".env"
        # A strong AUTH_ENCRYPTION_SECRET in .env with a weak value in os.environ
        # triggers the rotation-guard ValueError inside ensure_env_file_secrets.
        strong = "x3Kp_mQ8rZvN2wLsA5dYfB7cEjGhTuIo_X3K"  # pragma: allowlist secret
        env.write_text(f"AUTH_ENCRYPTION_SECRET={strong}\n", encoding="utf-8")  # pragma: allowlist secret
        monkeypatch.setenv("AUTH_ENCRYPTION_SECRET", "changeme")  # pragma: allowlist secret
        monkeypatch.setenv("MCPGATEWAY_AUTO_INIT_SECRETS", "true")

        with patch("argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                output=None, force=False, stdout=False, patch=None, patch_env=str(env)
            )
            with pytest.raises(SystemExit) as cm:
                main()

        assert cm.value.code == 1
        err = capsys.readouterr().err
        assert "AUTH_ENCRYPTION_SECRET" in err


class TestIsStrongValue:
    """Unit tests for the _is_strong_value helper (init_secrets.py lines 103-115)."""

    def test_empty_string_is_not_strong(self):
        """Empty / whitespace-only values must return False (line 109-110)."""
        assert _is_strong_value("", _WEAK_VALUES) is False
        assert _is_strong_value("   ", _WEAK_VALUES) is False

    def test_known_weak_value_is_not_strong(self):
        """Values in WEAK_VALUES must return False (line 111-112)."""
        assert _is_strong_value("changeme", _WEAK_VALUES) is False

    def test_replace_me_placeholder_is_not_strong(self):
        """__REPLACE_ME__ prefixed values must return False (line 111-112)."""
        assert _is_strong_value("__REPLACE_ME__init-secrets", _WEAK_VALUES) is False

    def test_short_but_high_entropy_is_not_strong(self):
        """Values shorter than MIN_SECRET_LENGTH must return False (line 113-114)."""
        # 8 chars is below the 32-byte minimum; token_urlsafe(6) gives high entropy
        import secrets as _secrets
        short_val = _secrets.token_urlsafe(6)  # ~8 chars, high entropy
        assert _is_strong_value(short_val, _WEAK_VALUES) is False

    def test_long_low_entropy_is_not_strong(self):
        """Values with entropy < MIN_ENTROPY must return False (line 113-114)."""
        low_entropy = "a" * 40  # 40 chars but zero entropy
        assert _is_strong_value(low_entropy, _WEAK_VALUES) is False

    def test_strong_value_returns_true(self):
        """A fully compliant value must return True (line 115)."""
        import secrets as _secrets
        strong = _secrets.token_urlsafe(32)  # 43 chars, high entropy
        assert _is_strong_value(strong, _WEAK_VALUES) is True


class TestCalculateEntropy:
    """Tests for calculate_entropy in _security_constants.py."""

    def test_empty_string_returns_zero(self):
        """Empty string must return 0.0 (line 29 of _security_constants.py)."""
        assert calculate_entropy("") == 0.0

    def test_single_char_string_returns_zero(self):
        """Single unique character has zero entropy."""
        assert calculate_entropy("aaaa") == 0.0

    def test_high_entropy_string(self):
        """Mixed string should return a positive entropy value."""
        assert calculate_entropy("aAbBcC123!@#") > 3.0
