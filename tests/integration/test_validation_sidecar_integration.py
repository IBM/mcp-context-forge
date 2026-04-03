# -*- coding: utf-8 -*-
"""Integration tests for the Rust UDS validation sidecar."""

# Standard
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

# Third-Party
from fastapi import HTTPException
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.validation_middleware import ValidationMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_MANIFEST = REPO_ROOT / "tools_rust" / "validation_sidecar" / "Cargo.toml"
SIDECAR_BINARY = REPO_ROOT / "tools_rust" / "validation_sidecar" / "target" / "debug" / "contextforge_validation_sidecar"
FRAME_PREFIX = struct.Struct(">I")


class _JSONBodyRequest:
    """Minimal request stub for exercising middleware JSON-body validation."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.path_params = {}
        self.query_params = {}
        self.headers = {"content-type": "application/json"}

    async def body(self) -> bytes:
        return self._body


def _wait_for_sidecar_ready(uds_path: Path, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    envelope = {
        "request_body_b64": base64.b64encode(b"{}").decode("ascii"),
        "max_param_length": 1,
        "dangerous_patterns": [],
        "healthcheck": True,
    }
    payload = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
    frame = FRAME_PREFIX.pack(len(payload)) + payload

    while time.time() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.5)
                client.connect(os.fspath(uds_path))
                client.sendall(frame)
                prefix = client.recv(FRAME_PREFIX.size)
                if len(prefix) != FRAME_PREFIX.size:
                    raise RuntimeError("sidecar returned an incomplete frame prefix during readiness check")
                length = FRAME_PREFIX.unpack(prefix)[0]
                response = b""
                while len(response) < length:
                    chunk = client.recv(length - len(response))
                    if not chunk:
                        raise RuntimeError("sidecar returned an incomplete readiness response")
                    response += chunk
                verdict = json.loads(response.decode("utf-8"))
                if verdict in ({"ok": True}, {"ok": True, "key": None, "error_type": None, "detail": None}):
                    return
        except (ConnectionError, FileNotFoundError, OSError, RuntimeError, json.JSONDecodeError):
            time.sleep(0.05)

    raise RuntimeError(f"validation sidecar did not become ready at {uds_path}")


def _configure_sidecar_settings(monkeypatch: pytest.MonkeyPatch, uds_path: str, dangerous_patterns: list[str]) -> None:
    monkeypatch.setattr(settings, "experimental_validate_io", True)
    monkeypatch.setattr(settings, "validation_middleware_enabled", True)
    monkeypatch.setattr(settings, "experimental_rust_validation_middleware_enabled", False)
    monkeypatch.setattr(settings, "experimental_rust_validation_sidecar_enabled", True)
    monkeypatch.setattr(settings, "experimental_rust_validation_sidecar_uds", uds_path)
    monkeypatch.setattr(settings, "experimental_rust_validation_sidecar_timeout_seconds", 0.5)
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "sanitize_output", False)
    monkeypatch.setattr(settings, "allowed_roots", [])
    monkeypatch.setattr(settings, "max_param_length", 64)
    monkeypatch.setattr(settings, "dangerous_patterns", dangerous_patterns)
    monkeypatch.setattr(settings, "environment", "production")


@pytest.fixture(scope="module")
def running_validation_sidecar() -> str:
    subprocess.run(["cargo", "build", "--manifest-path", str(SIDECAR_MANIFEST)], check=True, cwd=REPO_ROOT)
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="vside-it-") as tmpdir:
        uds_path = Path(tmpdir) / "v.sock"
        process = subprocess.Popen(
            [os.fspath(SIDECAR_BINARY), "--uds-path", os.fspath(uds_path)],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for_sidecar_ready(uds_path)
            yield os.fspath(uds_path)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_validation_sidecar_integration_returns_validation_verdict(
    monkeypatch: pytest.MonkeyPatch,
    running_validation_sidecar: str,
) -> None:
    _configure_sidecar_settings(monkeypatch, running_validation_sidecar, [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"])
    middleware = ValidationMiddleware(app=None)

    with pytest.raises(HTTPException) as exc_info:
        await middleware._validate_request(_JSONBodyRequest(b'{"prompt":"<script>alert(1)</script>"}'))

    assert exc_info.value.status_code == 422
    assert "dangerous characters" in exc_info.value.detail


@pytest.mark.integration
@pytest.mark.asyncio
async def test_validation_sidecar_integration_returns_503_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_sidecar_settings(monkeypatch, "/tmp/validation-sidecar-missing.sock", [r"[;&|`$(){}\[\]<>]"])
    middleware = ValidationMiddleware(app=None)

    with pytest.raises(HTTPException) as exc_info:
        await middleware._validate_request(_JSONBodyRequest(b'{"prompt":"safe"}'))

    assert exc_info.value.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_validation_sidecar_integration_surfaces_invalid_regex_as_503(
    monkeypatch: pytest.MonkeyPatch,
    running_validation_sidecar: str,
) -> None:
    _configure_sidecar_settings(monkeypatch, running_validation_sidecar, [r"(?<=unsafe)pattern"])
    middleware = ValidationMiddleware(app=None)

    with pytest.raises(HTTPException) as exc_info:
        await middleware._validate_request(_JSONBodyRequest(b'{"prompt":"unsafepattern"}'))

    assert exc_info.value.status_code == 503
