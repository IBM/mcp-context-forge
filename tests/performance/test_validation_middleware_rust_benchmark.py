# -*- coding: utf-8 -*-
"""Benchmark the validation middleware Rust extension against the Python path.

This benchmark exercises `ValidationMiddleware._validate_json_data()` for both paths so the
measurements include the Python wrapper work around the extension call.
"""

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
RUST_VALIDATION_MANIFEST = REPO_ROOT / "tools_rust" / "validation_middleware_rust" / "Cargo.toml"


def _ensure_rust_extension_installed() -> Any:
    subprocess.run(["uv", "run", "maturin", "develop", "--release", "--manifest-path", str(RUST_VALIDATION_MANIFEST)], check=True, cwd=REPO_ROOT)
    return importlib.import_module("validation_middleware_rust")


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
    _ensure_rust_extension_installed()
    settings.max_param_length = max_param_length
    settings.dangerous_patterns = dangerous_patterns
    settings.experimental_rust_validation_middleware_enabled = True
    settings.environment = "production"
    middleware = ValidationMiddleware(app=None)

    def _run(data: Any) -> None:
        middleware._validate_json_data(data)

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


def _measure_pair(
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
            run_result[label] = _measure(label, fn, payload, iterations)
        ordered_runs.append(run_result)

    python_median = statistics.mean(result["python"][0] for result in ordered_runs)
    rust_median = statistics.mean(result["rust"][0] for result in ordered_runs)
    return python_median, rust_median


def _measure_cold_pair(
    max_param_length: int,
    dangerous_patterns: list[str],
    payload: Any,
) -> tuple[float, float]:
    started = time.perf_counter_ns()
    python_fn = _build_python_validator(max_param_length, dangerous_patterns)
    try:
        python_fn(payload)
    except HTTPException:
        pass
    python_ms = (time.perf_counter_ns() - started) / 1_000_000

    started = time.perf_counter_ns()
    rust_fn = _build_rust_validator(max_param_length, dangerous_patterns)
    try:
        rust_fn(payload)
    except HTTPException:
        pass
    rust_ms = (time.perf_counter_ns() - started) / 1_000_000

    return python_ms, rust_ms


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
        ["<script>alert(1)</script>"],
        {"emoji": "é" * 1025},
    ]
    _assert_parity(python_fn, rust_fn, parity_payloads)

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

    cold_payload = {"tool": {"name": "safe-tool", "description": "ok"}}
    python_cold_ms, rust_cold_ms = _measure_cold_pair(max_param_length, dangerous_patterns, cold_payload)
    print("\ncold_first_call (1 iteration)")
    print(f"python={python_cold_ms:.3f}ms rust={rust_cold_ms:.3f}ms")
    print(f"speedup={python_cold_ms / rust_cold_ms:.2f}x")

    for name, payload, iterations in scenarios:
        print(f"\n{name} ({iterations} iterations)")
        python_median, rust_median = _measure_pair(python_fn, rust_fn, payload, iterations)
        print(f"python_avg_median={python_median:.3f}ms rust_avg_median={rust_median:.3f}ms")
        print(f"speedup={python_median / rust_median:.2f}x")


if __name__ == "__main__":
    main()
