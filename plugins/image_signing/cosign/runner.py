#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/image_signing/cosign/runner.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Xinyi

Run cosign CLI commands with timeout, capture stdout/stderr.
"""

# Future
from __future__ import annotations

# Standard
import logging
import os
import shutil
from typing import Dict, List, Optional

# First-Party
from mcpgateway.utils.exec import ExecResult, run_command
from plugins.image_signing.errors import (
    CosignNotFoundError,
    CosignTimeoutError,
    CosignVerificationError,
)

logger = logging.getLogger(__name__)


def check_cosign_installed(cosign_path: str) -> None:
    """Verify that the cosign binary is available.

    Args:
        cosign_path: Path to the cosign binary.

    Raises:
        CosignNotFoundError: If cosign binary is not found.
    """
    resolved = shutil.which(cosign_path)
    if resolved is None:
        raise CosignNotFoundError(f"Cosign binary not found at: {cosign_path}")


async def run_cosign(
    cmd: List[str],
    timeout_seconds: int | None = 30,
    env_override: Optional[Dict[str, str]] = None,
    cwd: str | None = None,
    raise_on_nonzero: bool = False,
) -> ExecResult:
    """Execute a cosign CLI command and capture output.

    Wraps the shared run_command utility with cosign-specific
    error handling and logging.

    Args:
        cmd: Full command-line arguments list.
        timeout_seconds: Maximum execution time in seconds, None for no limit.
        env_override: Optional environment variables to merge into the process env.
        cwd: Optional working directory for the subprocess.
        raise_on_nonzero: If True, raise CosignVerificationError on non-zero exit code.

    Returns:
        ExecResult with returncode, stdout, stderr, and timed_out flag.

    Raises:
        ValueError: If cmd is empty.
        CosignNotFoundError: If the cosign binary is not found.
        CosignTimeoutError: If the command exceeds the timeout.
        CosignVerificationError: If raise_on_nonzero is True and exit code is non-zero,
            or if an unexpected OS error occurs during execution.
    """
    if not cmd:
        raise ValueError("Command list cannot be empty")
    
    logger.debug("Running cosign command: %s", " ".join(cmd))

    # Build environment: inherit current env, overlay any overrides
    env: Optional[Dict[str, str]] = None
    if env_override:
        env = {**os.environ, **env_override}

    try:
        result = await run_command(
            cmd=cmd,
            timeout_seconds=timeout_seconds,
            env=env,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise CosignNotFoundError(f"Cosign binary not found: {cmd[0]}") from exc
    except OSError as exc:
        raise CosignVerificationError(reason=f"Cosign execution error: {exc}") from exc

    if result.timed_out:
        raise CosignTimeoutError(f"Cosign command timed out after {timeout_seconds}s")
    if raise_on_nonzero and result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()[:2000]
        raise CosignVerificationError(reason=f"exit={result.returncode}: {reason}")

    logger.debug(
        "Cosign exited with code %d, stdout=%d bytes, stderr=%d bytes",
        result.returncode,
        len(result.stdout),
        len(result.stderr),
    )

    return result