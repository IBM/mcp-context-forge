# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/protocol_compliance/fixtures/reference_upstream.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Reference-server subprocess fixture.

Spawns ``compliance-reference-server --transport http`` on an ephemeral port
so the live gateway-under-test can register it as a real upstream and federate
real HTTP traffic to it.

Cross-network reachability: the reference server binds to ``0.0.0.0`` so a
gateway running in docker-compose can reach it on the host. The URL the
gateway *sees* defaults to ``host.docker.internal`` (Mac/Win); Linux users
should override via ``MCP_REFERENCE_UPSTREAM_HOST`` (e.g. ``172.17.0.1``).
The harness probes its own loopback for the readiness wait either way.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import httpx
import pytest


@dataclass(frozen=True)
class ReferenceUpstream:
    """Immutable handle returned to tests for a running reference server.

    The ``subprocess.Popen`` is deliberately **not** a field — exposing
    it lets a test accidentally ``proc.kill()`` or ``proc.communicate()``
    and race the fixture's teardown. The process handle stays in the
    fixture closure so teardown has exclusive ownership. Tests that need
    to diagnose a crash read the ``log_path`` tail instead.
    """

    url: str  # Base URL the *gateway* uses to reach the server (e.g. http://host.docker.internal:9137)
    mcp_url: str  # Full MCP endpoint the gateway POSTs to
    local_url: str  # Loopback URL the harness uses for the readiness probe
    log_path: Path  # Combined stdout+stderr capture for post-mortem on failure


def _pick_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _wait_for_ready(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001 — connection refused expected during boot
            last_err = exc
        time.sleep(0.1)
    raise TimeoutError(f"Reference server at {url} did not come up in {timeout}s (last error: {last_err})")


def _dump_log_tail(log_path: Path, max_bytes: int = 4096) -> str:
    """Read the tail of the captured log for a failure diagnostic."""
    try:
        data = log_path.read_bytes()
    except OSError as exc:
        return f"<could not read log: {exc}>"
    if len(data) > max_bytes:
        data = b"...<truncated>...\n" + data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


@pytest.fixture(scope="session")
def reference_upstream() -> Iterator[ReferenceUpstream]:
    port = _pick_ephemeral_port()
    bind_host = "0.0.0.0"
    upstream_host = os.getenv("MCP_REFERENCE_UPSTREAM_HOST", "host.docker.internal")
    upstream_url = f"http://{upstream_host}:{port}"
    mcp_url = f"{upstream_url}/mcp"
    local_url = f"http://127.0.0.1:{port}/mcp"

    # Capture stdout+stderr to a session-scoped tmp log. DEVNULL would erase
    # exactly the diagnostic we need when the server crashes mid-boot or
    # under load — every downstream test then fails with a cryptic
    # "connection refused" with no stack trace anywhere to point at the
    # actual cause.
    log_fd, log_name = tempfile.mkstemp(prefix="compliance_reference_server-", suffix=".log")
    log_path = Path(log_name)
    os.close(log_fd)
    log_file = log_path.open("wb")

    proc = subprocess.Popen(
        [sys.executable, "-m", "compliance_reference_server.server", "--transport", "http", "--host", bind_host, "--port", str(port)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    try:
        try:
            _wait_for_ready(local_url)
        except TimeoutError as exc:
            # Server never came up; process may still be running or may have
            # crashed. Include the log tail in the error so the operator
            # sees the real traceback instead of a bare "connection refused".
            tail = _dump_log_tail(log_path)
            exit_code = proc.poll()
            raise TimeoutError(f"{exc}\nreference server log (exit_code={exit_code}, last {len(tail)} chars):\n{tail}") from exc
        yield ReferenceUpstream(
            url=upstream_url,
            mcp_url=mcp_url,
            local_url=local_url,
            log_path=log_path,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log_file.close()
        # Leave the log file in place after the session so a post-mortem
        # is still possible; tmpdir cleanup happens at OS level. The path
        # is reported in the ReferenceUpstream instance while it's live.
