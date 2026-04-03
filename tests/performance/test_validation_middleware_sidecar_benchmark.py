# -*- coding: utf-8 -*-
"""Benchmark the validation middleware Rust sidecar against the Python path."""

# Standard
from __future__ import annotations

import importlib
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

# Third-Party
from fastapi import HTTPException

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.validation_middleware import ValidationMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_MANIFEST = REPO_ROOT / "tools_rust" / "validation_middleware_sidecar" / "Cargo.toml"


def _ensure_sidecar_installed() -> Any:
    subprocess.run(["uv", "run", "maturin", "develop", "--release", "--manifest-path", str(SIDECAR_MANIFEST)], check=True, cwd=REPO_ROOT)
    return importlib.import_module("validation_middleware_sidecar")


def _build_python_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[Any], None]:
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = False
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)
    middleware.dangerous_patterns = [re.compile(pattern) for pattern in dangerous_patterns]

    def _run(data: Any) -> None:
        middleware._validate_json_data(data)

    return _run


def _build_rust_validator(max_param_length: int, dangerous_patterns: list[str]) -> Callable[[Any], None]:
    sidecar = _ensure_sidecar_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.environment = "production"

    def _run(data: Any) -> None:
        result = sidecar.validate_json_data(data, max_param_length, dangerous_patterns)
        if result is None:
            return
        key, error_type = result
        if error_type == "max_length":
            raise HTTPException(status_code=422, detail=f"Parameter {key} exceeds maximum length")
        raise HTTPException(status_code=422, detail=f"Parameter {key} contains dangerous characters")

    return _run


def _measure(label: str, fn: Callable[[Any], None], payload: Any, iterations: int) -> tuple[float, float]:
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


def _assert_parity(python_fn: Callable[[Any], None], rust_fn: Callable[[Any], None], payloads: list[Any]) -> None:
    for payload in payloads:
        python_error = None
        rust_error = None

        try:
            python_fn(payload)
        except HTTPException as exc:
            python_error = (exc.status_code, exc.detail)

        try:
            rust_fn(payload)
        except HTTPException as exc:
            rust_error = (exc.status_code, exc.detail)

        if python_error != rust_error:
            raise AssertionError(f"Parity mismatch for payload {payload!r}: python={python_error!r} rust={rust_error!r}")


def main() -> None:
    max_param_length = 1024
    dangerous_patterns = [r"[;&|`$(){}\[\]<>]", r"\.\.[\\/]", r"[\x00-\x1f\x7f-\x9f]"]

    python_fn = _build_python_validator(max_param_length, dangerous_patterns)
    rust_fn = _build_rust_validator(max_param_length, dangerous_patterns)

    parity_payloads = [
        {"name": "safe", "nested": {"description": "still safe"}},
        {"prompt": "<script>alert(1)</script>"},
        {"outer": {"inner": "a" * 2048}},
    ]
    _assert_parity(python_fn, rust_fn, parity_payloads)

    scenarios = [
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

    for name, payload, iterations in scenarios:
        print(f"\n{name} ({iterations} iterations)")
        python_median, _ = _measure("python", python_fn, payload, iterations)
        rust_median, _ = _measure("rust", rust_fn, payload, iterations)
        print(f"speedup={python_median / rust_median:.2f}x")


if __name__ == "__main__":
    main()
