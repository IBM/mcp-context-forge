#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./plugins/sbom_generator/extraction/syft_wrapper.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fionn Gavin

Async wrapper around the Syft CLI binary.
Syft (https://github.com/anchore/syft) is invoked as a subprocess so the
gateway event loop is never blocked.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import logging
import shutil
from typing import Any

# Local
from ..errors import ExtractionError

logger = logging.getLogger(__name__)

# Syft output scheme names per format
_FORMAT_SCHEMES: dict[str, str] = {
    "cyclonedx": "cyclonedx-json",
    "spdx": "spdx-json",
}


def _find_syft() -> str:
    """Locate the Syft binary on PATH.

    Returns:
        Absolute path to the ``syft`` executable.

    Raises:
        ExtractionError: If Syft is not installed or not on PATH.
    """
    path = shutil.which("syft")
    if not path:
        raise ExtractionError("Syft binary not found on PATH. " "Install from https://github.com/anchore/syft")
    return path


async def run_syft(
    target: str,
    fmt: str = "cyclonedx",
    timeout: int = 300,
) -> dict[str, Any]:
    """Invoke Syft against *target* and return the parsed JSON output.

    Args:
        target: Container image name (e.g. ``"nginx:latest"``) or a
            ``dir:<path>`` string for source directory scanning.
        fmt: SBOM format — ``"cyclonedx"`` or ``"spdx"``.
        timeout: Maximum seconds to wait for Syft to complete.

    Returns:
        Parsed JSON dict from Syft's stdout.

    Raises:
        ExtractionError: If Syft is not found, times out, or exits non-zero.
    """
    scheme = _FORMAT_SCHEMES.get(fmt)
    if scheme is None:
        raise ExtractionError(
            f"Unsupported format {fmt!r}. Choose 'cyclonedx' or 'spdx'.",
            details={"format": fmt},
        )

    syft_bin = _find_syft()
    cmd = [syft_bin, target, "-o", scheme, "--quiet"]

    logger.debug("Running Syft: %s", " ".join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise ExtractionError(
                f"Syft timed out after {timeout}s for target {target!r}",
                details={"target": target, "timeout": timeout},
            )
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            f"Failed to launch Syft: {exc}",
            details={"target": target},
        ) from exc

    if proc.returncode != 0:
        stderr_text = stderr.decode(errors="replace").strip()
        raise ExtractionError(
            f"Syft exited with code {proc.returncode} for target {target!r}",
            details={
                "target": target,
                "returncode": proc.returncode,
                "stderr": stderr_text[:500],
            },
        )

    raw = stdout.decode(errors="replace").strip()
    if not raw:
        raise ExtractionError(
            f"Syft produced no output for target {target!r}",
            details={"target": target},
        )

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"Failed to parse Syft JSON output: {exc}",
            details={"target": target, "raw_snippet": raw[:200]},
        ) from exc


async def get_syft_version() -> str | None:
    """Return the installed Syft version string, or ``None`` if unavailable.

    Returns:
        Version string such as ``"0.98.0"``, or ``None``.
    """
    try:
        syft_bin = _find_syft()
        proc = await asyncio.create_subprocess_exec(
            syft_bin,
            "version",
            "--output",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("version")
    except Exception:
        return None
