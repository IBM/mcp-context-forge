#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/unit/plugins/test_image_signing/test_runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Unit tests for cosign runner.
"""

# Future
from __future__ import annotations

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.utils.exec import ExecResult
from plugins.image_signing.cosign.runner import check_cosign_installed, run_cosign
from plugins.image_signing.errors import (
    CosignNotFoundError,
    CosignTimeoutError,
    CosignVerificationError,
)


# ---------------------------------------------------------------------------
# Tests: check_cosign_installed
# ---------------------------------------------------------------------------

class TestCheckCosignInstalled:
    """Tests for check_cosign_installed."""

    @patch("plugins.image_signing.cosign.runner.shutil.which", return_value="/usr/local/bin/cosign")
    def test_cosign_found(self, mock_which) -> None:
        """No exception when cosign is found."""
        check_cosign_installed("/usr/local/bin/cosign")
        mock_which.assert_called_once_with("/usr/local/bin/cosign")

    @patch("plugins.image_signing.cosign.runner.shutil.which", return_value=None)
    def test_cosign_not_found(self, mock_which) -> None:
        """Raises CosignNotFoundError when cosign is missing."""
        with pytest.raises(CosignNotFoundError, match="not found"):
            check_cosign_installed("/usr/local/bin/cosign")


# ---------------------------------------------------------------------------
# Tests: run_cosign - success
# ---------------------------------------------------------------------------

class TestRunCosignSuccess:
    """Tests for successful cosign execution."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_basic_success(self, mock_run) -> None:
        """Successful cosign execution returns ExecResult."""
        mock_run.return_value = ExecResult(
            returncode=0, stdout='[{"optional":{}}]', stderr="", timed_out=False
        )

        result = await run_cosign(cmd=["cosign", "verify", "nginx:latest"])

        assert result.returncode == 0
        assert result.stdout == '[{"optional":{}}]'
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_nonzero_without_raise(self, mock_run) -> None:
        """Non-zero exit returned normally when raise_on_nonzero=False."""
        mock_run.return_value = ExecResult(
            returncode=1, stdout="", stderr="no matching signatures", timed_out=False
        )

        result = await run_cosign(cmd=["cosign", "verify", "nginx:latest"])

        assert result.returncode == 1
        assert "no matching signatures" in result.stderr


# ---------------------------------------------------------------------------
# Tests: run_cosign - error handling
# ---------------------------------------------------------------------------

class TestRunCosignErrors:
    """Tests for cosign error handling."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_timeout(self, mock_run) -> None:
        """Raises CosignTimeoutError on timeout."""
        mock_run.return_value = ExecResult(
            returncode=-1, stdout="", stderr="", timed_out=True
        )

        with pytest.raises(CosignTimeoutError, match="timed out"):
            await run_cosign(
                cmd=["cosign", "verify", "nginx:latest"],
                timeout_seconds=5,
            )

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_nonzero_with_raise(self, mock_run) -> None:
        """Raises CosignVerificationError when raise_on_nonzero=True."""
        mock_run.return_value = ExecResult(
            returncode=1, stdout="", stderr="no matching signatures", timed_out=False
        )

        with pytest.raises(CosignVerificationError, match="exit=1"):
            await run_cosign(
                cmd=["cosign", "verify", "nginx:latest"],
                raise_on_nonzero=True,
            )

    @pytest.mark.asyncio
    @patch(
        "plugins.image_signing.cosign.runner.run_command",
        side_effect=FileNotFoundError("not found"),
    )
    async def test_file_not_found(self, mock_run) -> None:
        """Raises CosignNotFoundError on FileNotFoundError."""
        with pytest.raises(CosignNotFoundError, match="not found"):
            await run_cosign(cmd=["cosign", "verify", "nginx:latest"])

    @pytest.mark.asyncio
    @patch(
        "plugins.image_signing.cosign.runner.run_command",
        side_effect=OSError("permission denied"),
    )
    async def test_os_error(self, mock_run) -> None:
        """Raises CosignVerificationError on OSError."""
        with pytest.raises(CosignVerificationError, match="permission denied"):
            await run_cosign(cmd=["cosign", "verify", "nginx:latest"])

    @pytest.mark.asyncio
    async def test_empty_cmd_raises(self) -> None:
        """Raises ValueError on empty command list."""
        with pytest.raises(ValueError, match="empty"):
            await run_cosign(cmd=[])


# ---------------------------------------------------------------------------
# Tests: run_cosign - environment variables
# ---------------------------------------------------------------------------

class TestRunCosignEnv:
    """Tests for environment variable handling."""

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_env_override_passed(self, mock_run) -> None:
        """Environment override is merged and passed to run_command."""
        mock_run.return_value = ExecResult(
            returncode=0, stdout="", stderr="", timed_out=False
        )

        await run_cosign(
            cmd=["cosign", "verify", "nginx:latest"],
            env_override={"COSIGN_PUBLIC_KEY": "test-key"},
        )

        call_kwargs = mock_run.call_args.kwargs
        env = call_kwargs.get("env")
        assert env is not None
        assert env["COSIGN_PUBLIC_KEY"] == "test-key"

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_no_env_override(self, mock_run) -> None:
        """No env_override passes env=None to run_command."""
        mock_run.return_value = ExecResult(
            returncode=0, stdout="", stderr="", timed_out=False
        )

        await run_cosign(cmd=["cosign", "verify", "nginx:latest"])

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("env") is None

    @pytest.mark.asyncio
    @patch("plugins.image_signing.cosign.runner.run_command")
    async def test_cwd_passed(self, mock_run) -> None:
        """cwd parameter is passed through to run_command."""
        mock_run.return_value = ExecResult(
            returncode=0, stdout="", stderr="", timed_out=False
        )

        await run_cosign(
            cmd=["cosign", "verify", "nginx:latest"],
            cwd="/tmp/work",
        )

        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs.get("cwd") == "/tmp/work"