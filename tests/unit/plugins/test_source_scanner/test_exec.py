#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_exec.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
Unit tests for subprocess execution utilities.
"""

# Standard
import sys

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.utils.exec import ExecResult, run_command


class TestExecResult:
    """Test ExecResult data class."""

    def test_exec_result_repr(self) -> None:
        """Test ExecResult repr shows key information."""
        result = ExecResult(returncode=0, stdout="out", stderr="err", timed_out=False)

        text = repr(result)

        assert "returncode=0" in text
        assert "timed_out=False" in text
        assert "stdout_len=3" in text
        assert "stderr_len=3" in text

    def test_exec_result_fields(self) -> None:
        """Test ExecResult has correct fields."""
        result = ExecResult(returncode=1, stdout="output", stderr="error", timed_out=True)

        assert result.returncode == 1
        assert result.stdout == "output"
        assert result.stderr == "error"
        assert result.timed_out is True

    def test_exec_result_empty_output(self) -> None:
        """Test ExecResult with empty output."""
        result = ExecResult(returncode=0, stdout="", stderr="", timed_out=False)

        assert result.stdout == ""
        assert result.stderr == ""
        assert "stdout_len=0" in repr(result)
        assert "stderr_len=0" in repr(result)

    def test_exec_result_large_output(self) -> None:
        """Test ExecResult with large output."""
        large_output = "x" * 10000
        result = ExecResult(returncode=0, stdout=large_output, stderr="", timed_out=False)

        assert len(result.stdout) == 10000
        assert "stdout_len=10000" in repr(result)


class TestRunCommand:
    """Test run_command async function."""

    @pytest.mark.asyncio
    async def test_run_command_success(self) -> None:
        """Test successful command execution."""
        result = await run_command([sys.executable, "-c", "print('hello')"])

        assert result.returncode == 0
        assert result.timed_out is False
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_captures_stderr(self) -> None:
        """Test that stderr is captured."""
        result = await run_command([sys.executable, "-c", "import sys; sys.stderr.write('oops')"])

        assert result.returncode == 0
        assert result.timed_out is False
        assert "oops" in result.stderr

    @pytest.mark.asyncio
    async def test_run_command_nonzero_exit(self) -> None:
        """Test command with non-zero exit code."""
        result = await run_command([sys.executable, "-c", "import sys; sys.exit(42)"])

        assert result.returncode == 42
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_run_command_timeout(self) -> None:
        """Test command timeout."""
        result = await run_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout_seconds=0.1)

        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_run_command_with_env(self) -> None:
        """Test command with environment variables."""
        # Standard
        import os

        env = os.environ.copy()
        env["TEST_VAR"] = "test_value"

        result = await run_command([sys.executable, "-c", "import os; print(os.environ.get('TEST_VAR', 'not_set'))"], env=env)

        assert result.returncode == 0
        assert "test_value" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_with_cwd(self) -> None:
        """Test command with working directory."""
        result = await run_command([sys.executable, "-c", "import os; print(os.getcwd())"])

        assert result.returncode == 0
        assert result.stdout  # Should have some path

    @pytest.mark.asyncio
    async def test_run_command_invalid_command(self) -> None:
        """Test command that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            await run_command(["nonexistent_command_that_does_not_exist_xyz"])

    @pytest.mark.asyncio
    async def test_run_command_multiline_output(self) -> None:
        """Test command with multiline output."""
        cmd = [sys.executable, "-c", "for i in range(3): print(f'line {i}')"]
        result = await run_command(cmd)

        assert result.returncode == 0
        assert "line 0" in result.stdout
        assert "line 1" in result.stdout
        assert "line 2" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_mixed_output(self) -> None:
        """Test command with both stdout and stderr."""
        cmd = [sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err')"]
        result = await run_command(cmd)

        assert result.returncode == 0
        assert "out" in result.stdout
        assert "err" in result.stderr

    @pytest.mark.asyncio
    async def test_run_command_returns_exec_result(self) -> None:
        """Test that run_command returns ExecResult instance."""
        result = await run_command([sys.executable, "-c", "print('test')"])

        assert isinstance(result, ExecResult)
        assert hasattr(result, "returncode")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "timed_out")
