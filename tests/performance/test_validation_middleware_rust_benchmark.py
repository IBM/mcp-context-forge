# -*- coding: utf-8 -*-
"""Benchmark the validation middleware Rust extension against the Python path.

This benchmark exercises the Rust-backed validation middleware surfaces and verifies Python/Rust
parity before reporting speedups for each timed scenario.
"""

# Standard
from __future__ import annotations

import importlib
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

# Third-Party
from fastapi import HTTPException
import orjson
from starlette.responses import Response

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.validation_middleware import ValidationMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_VALIDATION_MANIFEST = REPO_ROOT / "tools_rust" / "validation_middleware_rust" / "Cargo.toml"
UDS_TARGET_MEDIANS_MS = {
    "nested_safe": 0.153,
    "deep_nested": 0.806,
    "dangerous_string": 0.327,
}


class _JSONBodyRequest:
    """Minimal request stub for benchmarking the middleware request path."""

    def __init__(self, body: bytes, path_params: dict[str, str] | None = None, query_params: dict[str, str] | None = None) -> None:
        self._body = body
        self.path_params = path_params or {}
        self.query_params = query_params or {}
        self.headers = {"content-type": "application/json"}

    async def body(self) -> bytes:
        return self._body


class _QueryRequest:
    """Minimal request stub for benchmarking parameter validation."""

    def __init__(self, query_params: dict[str, str]) -> None:
        self.path_params = {"id": "123"}
        self.query_params = query_params
        self.headers = {}


def _ensure_rust_extension_installed() -> Any:
    env = os.environ.copy()
    virtual_env = sys.prefix
    env["VIRTUAL_ENV"] = virtual_env
    env["PATH"] = f"{Path(virtual_env) / 'bin'}:{env['PATH']}"
    subprocess.run(["maturin", "develop", "--release", "--manifest-path", str(RUST_VALIDATION_MANIFEST)], check=True, cwd=REPO_ROOT, env=env)
    return importlib.import_module("validation_middleware_rust")


def _build_python_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    return _build_python_request_validator(max_param_length, dangerous_patterns, {}, {})


def _build_python_request_validator(
    max_param_length: int,
    dangerous_patterns: list[str],
    path_params: dict[str, str],
    query_params: dict[str, str],
) -> Callable[[bytes], Awaitable[None]]:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = False
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)
    middleware.dangerous_patterns = [re.compile(pattern) for pattern in dangerous_patterns]

    async def _run(body: bytes) -> None:
        await middleware._validate_request(_JSONBodyRequest(body, path_params, query_params))

    return _run


def _build_rust_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    return _build_rust_request_validator(max_param_length, dangerous_patterns, {}, {})


def _build_rust_request_validator(
    max_param_length: int,
    dangerous_patterns: list[str],
    path_params: dict[str, str],
    query_params: dict[str, str],
) -> Callable[[bytes], Awaitable[None]]:
    _ensure_rust_extension_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = True
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)

    async def _run(body: bytes) -> None:
        await middleware._validate_request(_JSONBodyRequest(body, path_params, query_params))

    return _run


def _build_python_parameter_runner(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[dict[str, str]], None]:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = False
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)
    middleware.dangerous_patterns = [re.compile(pattern) for pattern in dangerous_patterns]

    def _run(query_params: dict[str, str]) -> None:
        request = _QueryRequest(query_params)
        middleware._validate_parameters([("id", "123"), *list(request.query_params.items())])

    return _run


def _build_rust_parameter_runner(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[dict[str, str]], None]:
    _ensure_rust_extension_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = True
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)

    def _run(query_params: dict[str, str]) -> None:
        request = _QueryRequest(query_params)
        middleware._validate_parameters([("id", "123"), *list(request.query_params.items())])

    return _run


def _build_python_resource_runner(
    max_param_length: int,
    dangerous_patterns: list[str],
    *,
    allowed_roots: list[str] | None = None,
    max_path_depth: int = 32,
) -> Callable[[str], None]:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = False
    settings.environment = "production"
    settings.max_path_depth = max_path_depth
    settings.allowed_roots = allowed_roots or []
    middleware = ValidationMiddleware(app=None)

    def _run(path: str) -> None:
        middleware.validate_resource_path(path)

    return _run


def _build_rust_resource_runner(
    max_param_length: int,
    dangerous_patterns: list[str],
    *,
    allowed_roots: list[str] | None = None,
    max_path_depth: int = 32,
) -> Callable[[str], None]:
    _ensure_rust_extension_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = True
    settings.environment = "production"
    settings.max_path_depth = max_path_depth
    settings.allowed_roots = allowed_roots or []
    middleware = ValidationMiddleware(app=None)

    def _run(path: str) -> None:
        middleware.validate_resource_path(path)

    return _run


def _build_python_sanitizer(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = False
    settings.environment = "production"
    settings.sanitize_output = True
    middleware = ValidationMiddleware(app=None)

    async def _run(body: bytes) -> bytes:
        response = await middleware._sanitize_response(Response(content=body))
        return response.body

    return _run


def _build_rust_sanitizer(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[bytes], Awaitable[None]]:
    _ensure_rust_extension_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = True
    settings.environment = "production"
    settings.sanitize_output = True
    middleware = ValidationMiddleware(app=None)

    async def _run(body: bytes) -> bytes:
        response = await middleware._sanitize_response(Response(content=body))
        return response.body

    return _run


async def _measure(label: str, fn: Callable[[bytes], Awaitable[None]], payload: bytes, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        try:
            await fn(payload)
        except HTTPException:
            pass
        samples.append(time.perf_counter_ns() - started)

    median_ms = statistics.median(samples) / 1_000_000
    p95_ms = statistics.quantiles(samples, n=100)[94] / 1_000_000
    print(f"{label}: median={median_ms:.3f}ms p95={p95_ms:.3f}ms")
    return median_ms, p95_ms


async def _measure_pair(
    python_fn: Callable[[bytes], Awaitable[None]],
    rust_fn: Callable[[bytes], Awaitable[None]],
    payload: bytes,
    iterations: int,
) -> tuple[float, float]:
    ordered_runs = []
    for order in (
        (("python", python_fn), ("rust", rust_fn)),
        (("rust", rust_fn), ("python", python_fn)),
    ):
        run_result: dict[str, tuple[float, float]] = {}
        for label, fn in order:
            run_result[label] = await _measure(label, fn, payload, iterations)
        ordered_runs.append(run_result)

    python_median = statistics.mean(result["python"][0] for result in ordered_runs)
    rust_median = statistics.mean(result["rust"][0] for result in ordered_runs)
    return python_median, rust_median


def _measure_sync(label: str, fn: Callable[[Any], None], payload: Any, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        try:
            fn(payload)
        except HTTPException:
            pass
        samples.append(time.perf_counter_ns() - started)

    median_ms = statistics.median(samples) / 1_000_000
    p95_ms = statistics.quantiles(samples, n=100)[94] / 1_000_000
    print(f"{label}: median={median_ms:.3f}ms p95={p95_ms:.3f}ms")
    return median_ms, p95_ms


def _measure_sync_pair(
    python_fn: Callable[[Any], None],
    rust_fn: Callable[[Any], None],
    payload: Any,
    iterations: int,
) -> tuple[float, float]:
    ordered_runs = []
    for order in (
        (("python", python_fn), ("rust", rust_fn)),
        (("rust", rust_fn), ("python", python_fn)),
    ):
        run_result: dict[str, tuple[float, float]] = {}
        for label, fn in order:
            run_result[label] = _measure_sync(label, fn, payload, iterations)
        ordered_runs.append(run_result)

    python_median = statistics.mean(result["python"][0] for result in ordered_runs)
    rust_median = statistics.mean(result["rust"][0] for result in ordered_runs)
    return python_median, rust_median


def _capture_sync_result(fn: Callable[[Any], Any], payload: Any) -> tuple[str, Any]:
    try:
        return "ok", fn(payload)
    except HTTPException as exc:
        return "http_error", (exc.status_code, exc.detail)


async def _capture_async_result(fn: Callable[[bytes], Awaitable[Any]], payload: bytes) -> tuple[str, Any]:
    try:
        return "ok", await fn(payload)
    except HTTPException as exc:
        return "http_error", (exc.status_code, exc.detail)


def _assert_sync_parity(
    python_fn: Callable[[Any], Any],
    rust_fn: Callable[[Any], Any],
    payloads: list[Any],
) -> None:
    for payload in payloads:
        python_result = _capture_sync_result(python_fn, payload)
        rust_result = _capture_sync_result(rust_fn, payload)
        if python_result != rust_result:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: python={python_result!r} rust={rust_result!r}")


async def _assert_async_bytes_parity(
    python_fn: Callable[[bytes], Awaitable[Any]],
    rust_fn: Callable[[bytes], Awaitable[Any]],
    payloads: list[bytes],
) -> None:
    for payload in payloads:
        python_result = await _capture_async_result(python_fn, payload)
        rust_result = await _capture_async_result(rust_fn, payload)
        if python_result != rust_result:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: python={python_result!r} rust={rust_result!r}")


async def _measure_extension_setup_pair(
    max_param_length: int,
    dangerous_patterns: list[str],
    payload: bytes,
) -> tuple[float, float]:
    started = time.perf_counter_ns()
    python_fn = _build_python_validator(max_param_length, dangerous_patterns)
    try:
        await python_fn(payload)
    except HTTPException:
        pass
    python_ms = (time.perf_counter_ns() - started) / 1_000_000

    started = time.perf_counter_ns()
    rust_fn = _build_rust_validator(max_param_length, dangerous_patterns)
    try:
        await rust_fn(payload)
    except HTTPException:
        pass
    rust_ms = (time.perf_counter_ns() - started) / 1_000_000

    return python_ms, rust_ms


async def _assert_parity(
    python_fn: Callable[[bytes], Awaitable[None]],
    rust_fn: Callable[[bytes], Awaitable[None]],
    payloads: list[bytes],
) -> None:
    for payload in payloads:
        python_error = None
        rust_error = None

        try:
            await python_fn(payload)
        except HTTPException as exc:
            python_error = (exc.status_code, exc.detail)

        try:
            await rust_fn(payload)
        except HTTPException as exc:
            rust_error = (exc.status_code, exc.detail)

        if python_error != rust_error:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: python={python_error!r} rust={rust_error!r}")


async def main() -> None:
    max_param_length = 1024
    dangerous_patterns = [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"]

    cold_payload = orjson.dumps({"tool": {"name": "safe-tool", "description": "ok"}})
    python_cold_ms, rust_cold_ms = await _measure_extension_setup_pair(max_param_length, dangerous_patterns, cold_payload)
    print("\nextension_setup_and_first_call (1 iteration)")
    print("note=this includes Rust extension build/install overhead and is not a steady-state middleware timing")
    print(f"python={python_cold_ms:.3f}ms rust={rust_cold_ms:.3f}ms")
    print(f"rust_setup_overhead_delta={rust_cold_ms - python_cold_ms:.3f}ms")

    python_fn = _build_python_validator(max_param_length, dangerous_patterns)
    rust_fn = _build_rust_validator(max_param_length, dangerous_patterns)
    python_mixed_fn = _build_python_request_validator(max_param_length, dangerous_patterns, {"id": "123"}, {"q": "safe"})
    rust_mixed_fn = _build_rust_request_validator(max_param_length, dangerous_patterns, {"id": "123"}, {"q": "safe"})
    python_param_fn = _build_python_parameter_runner(max_param_length, dangerous_patterns)
    rust_param_fn = _build_rust_parameter_runner(max_param_length, dangerous_patterns)
    python_sanitize_fn = _build_python_sanitizer(max_param_length, dangerous_patterns)
    rust_sanitize_fn = _build_rust_sanitizer(max_param_length, dangerous_patterns)

    parity_payloads = [
        orjson.dumps({"name": "safe", "nested": {"description": "still safe"}}),
        orjson.dumps({"prompt": "<script>alert(1)</script>"}),
        orjson.dumps({"outer": {"inner": "a" * 2048}}),
        orjson.dumps(["<script>alert(1)</script>"]),
        orjson.dumps({"emoji": "é" * 1025}),
        b"{",
    ]
    await _assert_parity(python_fn, rust_fn, parity_payloads)
    await _assert_parity(python_mixed_fn, rust_mixed_fn, parity_payloads)
    _assert_sync_parity(
        python_param_fn,
        rust_param_fn,
        [
            {"q": "safe"},
            {"q": "<script>alert(1)</script>"},
            {"q": "value", "extra": "x" * 32},
        ],
    )
    with tempfile.TemporaryDirectory() as allowed_root, tempfile.TemporaryDirectory() as outside_root:
        symlink_path = Path(allowed_root) / "escape"
        broken_symlink_path = Path(allowed_root) / "broken"
        os.symlink(outside_root, symlink_path)
        os.symlink(str(Path(outside_root) / "missing-target"), broken_symlink_path)

        python_resource_fn = _build_python_resource_runner(max_param_length, dangerous_patterns, allowed_roots=[allowed_root])
        rust_resource_fn = _build_rust_resource_runner(max_param_length, dangerous_patterns, allowed_roots=[allowed_root])
        _assert_sync_parity(
            python_resource_fn,
            rust_resource_fn,
            [
                str(Path(allowed_root) / "safe" / "file.txt"),
                "../unsafe/path",
                "http://example.com/resource",
                str(symlink_path / "file.txt"),
                str(broken_symlink_path / "file.txt"),
                "bad\0path",
            ],
        )
        print("\nresource_path (2000 iterations)")
        python_resource_median, rust_resource_median = _measure_sync_pair(
            python_resource_fn,
            rust_resource_fn,
            str(Path(allowed_root) / "safe" / "subdir" / "file.txt"),
            2000,
        )
        print(f"python_avg_median={python_resource_median:.3f}ms rust_avg_median={rust_resource_median:.3f}ms")
        print(f"speedup={python_resource_median / rust_resource_median:.2f}x")
    await _assert_async_bytes_parity(
        python_sanitize_fn,
        rust_sanitize_fn,
        [
            b"prefix\x00middle\x1fsuffix",
            b"plain-ascii-response-body",
        ],
    )

    scenarios = [
        (
            "small_safe",
            {"tool": {"name": "safe-tool", "description": "ok"}},
            1000,
        ),
        (
            "first_field_reject",
            {"tool": {"name": "<script>alert(1)</script>", "description": "ok"}},
            1000,
        ),
        (
            "unicode_safe_long",
            {"tool": {"name": "safe-tool", "description": "é" * 1024}},
            500,
        ),
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

    print("\nparameter_batch (2000 iterations)")
    python_param_median, rust_param_median = _measure_sync_pair(
        python_param_fn,
        rust_param_fn,
        {f"q{index}": f"value-{index}" for index in range(16)},
        2000,
    )
    print(f"python_avg_median={python_param_median:.3f}ms rust_avg_median={rust_param_median:.3f}ms")
    print(f"speedup={python_param_median / rust_param_median:.2f}x")

    print("\nresponse_sanitization (1000 iterations)")
    python_sanitize_median, rust_sanitize_median = await _measure_pair(
        python_sanitize_fn,
        rust_sanitize_fn,
        b"prefix\x00middle\x1fsuffix" * 256,
        1000,
    )
    print(f"python_avg_median={python_sanitize_median:.3f}ms rust_avg_median={rust_sanitize_median:.3f}ms")
    print(f"speedup={python_sanitize_median / rust_sanitize_median:.2f}x")

    print("\nresponse_sanitization_safe (1000 iterations)")
    python_sanitize_safe_median, rust_sanitize_safe_median = await _measure_pair(
        python_sanitize_fn,
        rust_sanitize_fn,
        b"plain-ascii-response-body-" * 256,
        1000,
    )
    print(f"python_avg_median={python_sanitize_safe_median:.3f}ms rust_avg_median={rust_sanitize_safe_median:.3f}ms")
    print(f"speedup={python_sanitize_safe_median / rust_sanitize_safe_median:.2f}x")

    for name, payload, iterations in scenarios:
        body = orjson.dumps(payload)
        print(f"\n{name} ({iterations} iterations)")
        python_median, rust_median = await _measure_pair(python_fn, rust_fn, body, iterations)
        print(f"python_avg_median={python_median:.3f}ms rust_avg_median={rust_median:.3f}ms")
        print(f"speedup={python_median / rust_median:.2f}x")
        uds_target = UDS_TARGET_MEDIANS_MS.get(name)
        if uds_target is not None:
            print(f"uds_target_median={uds_target:.3f}ms beat_target={rust_median < uds_target}")

    mixed_payload = orjson.dumps({"tool": {"name": "safe-tool", "description": "ok"}})
    print("\nmixed_params_json (1000 iterations)")
    python_mixed_median, rust_mixed_median = await _measure_pair(
        python_mixed_fn,
        rust_mixed_fn,
        mixed_payload,
        1000,
    )
    print(f"python_avg_median={python_mixed_median:.3f}ms rust_avg_median={rust_mixed_median:.3f}ms")
    print(f"speedup={python_mixed_median / rust_mixed_median:.2f}x")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
