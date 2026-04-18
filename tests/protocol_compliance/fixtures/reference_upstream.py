"""Reference-server subprocess fixture.

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
import time
from dataclasses import dataclass
from typing import Iterator

import httpx
import pytest


@dataclass
class ReferenceUpstream:
    url: str  # Base URL the *gateway* uses to reach the server (e.g. http://host.docker.internal:9137)
    mcp_url: str  # Full MCP endpoint the gateway POSTs to
    local_url: str  # Loopback URL the harness uses for the readiness probe
    process: subprocess.Popen


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


@pytest.fixture(scope="session")
def reference_upstream() -> Iterator[ReferenceUpstream]:
    port = _pick_ephemeral_port()
    bind_host = "0.0.0.0"
    upstream_host = os.getenv("MCP_REFERENCE_UPSTREAM_HOST", "host.docker.internal")
    upstream_url = f"http://{upstream_host}:{port}"
    mcp_url = f"{upstream_url}/mcp"
    local_url = f"http://127.0.0.1:{port}/mcp"

    proc = subprocess.Popen(
        [sys.executable, "-m", "compliance_reference_server.server", "--transport", "http", "--host", bind_host, "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_for_ready(local_url)
        yield ReferenceUpstream(
            url=upstream_url,
            mcp_url=mcp_url,
            local_url=local_url,
            process=proc,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
