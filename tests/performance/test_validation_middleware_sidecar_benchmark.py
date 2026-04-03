# -*- coding: utf-8 -*-
"""Benchmark Python, PyO3, and UDS sidecar validation middleware paths."""

# Standard
from __future__ import annotations

import importlib
import asyncio
import base64
import json
import os
import re
import socket
import statistics
import struct
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator

# Third-Party
from fastapi import HTTPException
import orjson

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.validation_middleware import ValidationMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
PYO3_SIDECAR_MANIFEST = REPO_ROOT / "tools_rust" / "validation_middleware_sidecar" / "Cargo.toml"
UDS_SIDECAR_MANIFEST = REPO_ROOT / "tools_rust" / "validation_sidecar" / "Cargo.toml"
FRAME_PREFIX = struct.Struct(">I")


class _JSONBodyRequest:
    """Minimal request stub for benchmarking the middleware request path."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.path_params = {}
        self.query_params = {}
        self.headers = {"content-type": "application/json"}

    async def body(self) -> bytes:
        return self._body


def _ensure_sidecar_installed() -> Any:
    subprocess.run(
        ["uv", "run", "maturin", "develop", "--release", "--manifest-path", str(PYO3_SIDECAR_MANIFEST)],
        check=True,
        cwd=REPO_ROOT,
    )
    return importlib.import_module("validation_middleware_sidecar")


def _configure_common_settings(max_param_length: int, dangerous_patterns: list[str]) -> None:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_validate_io = True
    settings.validation_middleware_enabled = True
    settings.validation_strict = True
    settings.environment = "production"


def _build_python_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    _configure_common_settings(max_param_length, dangerous_patterns)
    settings.experimental_rust_validation_middleware_enabled = False
    settings.experimental_rust_validation_sidecar_enabled = False
    middleware = ValidationMiddleware(app=None)
    middleware.dangerous_patterns = [re.compile(pattern) for pattern in dangerous_patterns]

    async def _run(body: bytes) -> None:
        await middleware._validate_request(_JSONBodyRequest(body))

    return _run


def _build_rust_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    _ensure_sidecar_installed()
    _configure_common_settings(max_param_length, dangerous_patterns)
    settings.experimental_rust_validation_middleware_enabled = True
    settings.experimental_rust_validation_sidecar_enabled = False
    middleware = ValidationMiddleware(app=None)

    async def _run(body: bytes) -> None:
        await middleware._validate_request(_JSONBodyRequest(body))

    return _run


def _healthcheck_sidecar(uds_path: Path, timeout_seconds: float = 10.0) -> None:
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
                if verdict in ({"ok": True, "key": None, "error_type": None, "detail": None}, {"ok": True}):
                    return
        except (ConnectionError, FileNotFoundError, OSError, RuntimeError, json.JSONDecodeError):
            time.sleep(0.05)

    raise RuntimeError(f"validation sidecar did not become ready at {uds_path}")


@contextmanager
def _launch_validation_sidecar(parser: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="vside-") as tmpdir:
        uds_path = Path(tmpdir) / "v.sock"
        process = subprocess.Popen(
            [
                "cargo",
                "run",
                "--release",
                "--manifest-path",
                str(UDS_SIDECAR_MANIFEST),
                "--",
                "--uds-path",
                str(uds_path),
                "--parser",
                parser,
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            try:
                _healthcheck_sidecar(uds_path)
            except RuntimeError as exc:
                stderr_output = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(f"{exc}\nsidecar stderr ({parser}): {stderr_output}") from exc
            yield uds_path
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _build_uds_sidecar_validator(
    max_param_length: int,
    dangerous_patterns: list[str],
    uds_path: Path,
) -> Callable[[bytes], Awaitable[None]]:
    _configure_common_settings(max_param_length, dangerous_patterns)
    settings.experimental_rust_validation_middleware_enabled = False
    settings.experimental_rust_validation_sidecar_enabled = True
    settings.experimental_rust_validation_sidecar_uds = str(uds_path)
    settings.experimental_rust_validation_sidecar_timeout_seconds = 30.0
    middleware = ValidationMiddleware(app=None)

    async def _run(body: bytes) -> None:
        await middleware._validate_request(_JSONBodyRequest(body))

    return _run


async def _measure(label: str, fn: Callable[[bytes], Awaitable[None]], body: bytes, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        try:
            await fn(body)
        except HTTPException:
            pass
        samples.append(time.perf_counter_ns() - started)

    median_ms = statistics.median(samples) / 1_000_000
    p95_ms = statistics.quantiles(samples, n=100)[94] / 1_000_000
    print(f"{label}: median={median_ms:.3f}ms p95={p95_ms:.3f}ms")
    return median_ms, p95_ms


async def _measure_ordered(
    ordered_backends: list[tuple[str, Callable[[bytes], Awaitable[None]]]],
    body: bytes,
    iterations: int,
) -> dict[str, tuple[float, float]]:
    run_result: dict[str, tuple[float, float]] = {}
    for label, fn in ordered_backends:
        run_result[label] = await _measure(label, fn, body, iterations)
    return run_result


async def _assert_parity(backends: dict[str, Callable[[bytes], Awaitable[None]]], payloads: list[bytes]) -> None:
    for payload in payloads:
        backend_errors: dict[str, tuple[int, str] | None] = {}
        for name, fn in backends.items():
            backend_error = None
            try:
                await fn(payload)
            except HTTPException as exc:
                backend_error = (exc.status_code, exc.detail)
            backend_errors[name] = backend_error

        first = next(iter(backend_errors.values()))
        mismatches = {name: error for name, error in backend_errors.items() if error != first}
        if mismatches:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: {backend_errors!r}")


async def _main() -> None:
    max_param_length = 1024
    dangerous_patterns = [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"]

    python_fn = _build_python_validator(max_param_length, dangerous_patterns)
    pyo3_fn = _build_rust_validator(max_param_length, dangerous_patterns)

    parity_payloads = [
        {"name": "safe", "nested": {"description": "still safe"}},
        {"prompt": "<script>alert(1)</script>"},
        {"outer": {"inner": "a" * 2048}},
        ["<script>alert(1)</script>"],
        {"emoji": "é" * 1025},
    ]

    scenarios: list[tuple[str, Any, int]] = [
        (
            "nested_safe",
            {
                "tool": {
                    "name": "safe-tool",
                    "description": "ok" * 32,
                    "metadata": [{"field": "value" * 8} for _ in range(256)],
                }
            },
            400,
        ),
        (
            "deep_nested",
            {"batch": [{"payload": {"name": f"item-{index}", "content": ("alpha-beta-gamma-" * 16)}} for index in range(512)]},
            250,
        ),
        (
            "dangerous_string",
            {"batch": [{"payload": {"name": f"item-{index}", "content": "safe-content"}} for index in range(511)] + [{"payload": {"name": "bad", "content": "<script>alert(1)</script>"}}]},
            250,
        ),
    ]

    with _launch_validation_sidecar("serde-json") as serde_uds_path, _launch_validation_sidecar("simd-json") as simd_uds_path:
        sidecar_serde_fn = _build_uds_sidecar_validator(max_param_length, dangerous_patterns, serde_uds_path)
        sidecar_simd_fn = _build_uds_sidecar_validator(max_param_length, dangerous_patterns, simd_uds_path)

        backends = {
            "python": python_fn,
            "pyo3": pyo3_fn,
            "sidecar-serde": sidecar_serde_fn,
            "sidecar-simd": sidecar_simd_fn,
        }
        await _assert_parity(backends, [orjson.dumps(payload) for payload in parity_payloads])

        for name, payload, iterations in scenarios:
            body = orjson.dumps(payload)
            print(f"\n{name} ({iterations} iterations)")
            ordered_runs = [
                await _measure_ordered(
                    [
                        ("python", python_fn),
                        ("pyo3", pyo3_fn),
                        ("sidecar-serde", sidecar_serde_fn),
                        ("sidecar-simd", sidecar_simd_fn),
                    ],
                    body,
                    iterations,
                ),
                await _measure_ordered(
                    [
                        ("sidecar-simd", sidecar_simd_fn),
                        ("sidecar-serde", sidecar_serde_fn),
                        ("pyo3", pyo3_fn),
                        ("python", python_fn),
                    ],
                    body,
                    iterations,
                ),
            ]

            avg_medians = {backend: statistics.mean(run[backend][0] for run in ordered_runs) for backend in backends}
            print(
                "avg_medians="
                f"python={avg_medians['python']:.3f}ms "
                f"pyo3={avg_medians['pyo3']:.3f}ms "
                f"sidecar-serde={avg_medians['sidecar-serde']:.3f}ms "
                f"sidecar-simd={avg_medians['sidecar-simd']:.3f}ms"
            )
            print(
                "speedups="
                f"pyo3={avg_medians['python'] / avg_medians['pyo3']:.2f}x "
                f"sidecar-serde={avg_medians['python'] / avg_medians['sidecar-serde']:.2f}x "
                f"sidecar-simd={avg_medians['python'] / avg_medians['sidecar-simd']:.2f}x"
            )


if __name__ == "__main__":
    asyncio.run(_main())
