#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Location: tests/unit/plugins/test_source_scanner/test_exec.py
Copyright: 2026
SPDX-License-Identifier: Apache-2.0
Authors: Yaser
"""

# Standard
import sys

# Third-Party
import pytest

# First-Party
from plugins.source_scanner.utils.exec import ExecResult, run_command


def test_exec_result_repr() -> None:
    result = ExecResult(returncode=0, stdout="out", stderr="err", timed_out=False)

    text = repr(result)

    assert "returncode=0" in text
    assert "timed_out=False" in text
    assert "stdout_len=3" in text
    assert "stderr_len=3" in text


@pytest.mark.asyncio
async def test_run_command_success() -> None:
    result = await run_command([sys.executable, "-c", "print('hello')"])

    assert result.returncode == 0
    assert result.timed_out is False
    assert "hello" in result.stdout


@pytest.mark.asyncio
async def test_run_command_captures_stderr() -> None:
    result = await run_command([sys.executable, "-c", "import sys; sys.stderr.write('oops')"])

    assert result.returncode == 0
    assert result.timed_out is False
    assert "oops" in result.stderr


@pytest.mark.asyncio
async def test_run_command_timeout() -> None:
    result = await run_command([sys.executable, "-c", "import time; time.sleep(1)"], timeout_seconds=0.01)

    assert result.timed_out is True
    assert result.returncode != 0
