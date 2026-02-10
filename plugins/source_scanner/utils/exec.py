#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/source_scanner/utils/exec.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi, Ayo

Subprocess wrapper with timeout, stdout/stderr capture, and return code handling.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from typing import List, Optional


class ExecResult:
    """Result of subprocess execution.

    Attributes:
        returncode: Exit code of the process.
        stdout: Standard output as string.
        stderr: Standard error as string.
        timed_out: Whether the process timed out.
    """

    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out

    def __repr__(self) -> str:
        return f"ExecResult(returncode={self.returncode}, " f"timed_out={self.timed_out}, " f"stdout_len={len(self.stdout)}, " f"stderr_len={len(self.stderr)})"


async def run_command(
    cmd: List[str],
    timeout_seconds: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> ExecResult:
    """Execute a command with optional timeout.

    Notes:
        This utility never raises on timeout; it returns ExecResult(timed_out=True)
        and captures any partial stdout/stderr where possible. Callers decide how
        to map failures into domain-specific exceptions.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    try:
        if timeout_seconds is not None:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout_seconds)
        else:
            stdout_b, stderr_b = await proc.communicate()

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        return ExecResult(returncode=proc.returncode or 0, stdout=stdout, stderr=stderr, timed_out=False)

    except asyncio.TimeoutError:
        # Mark timeout and ensure process is terminated
        try:
            proc.kill()
        except ProcessLookupError:
            pass

        # Best-effort: wait shortly for pipes to flush
        stdout = ""
        stderr = ""
        try:
            stdout_b, stderr_b = await proc.communicate()
            stdout = (stdout_b or b"").decode("utf-8", errors="replace")
            stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        except Exception:
            # If communicate fails after kill, return empty outputs
            pass

        return ExecResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
